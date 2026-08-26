"""Reading and writing a WeeWX archive database.

Everything here is written so that WeeWX 5 can pick the file up again
afterwards and not notice anyone else was in it. That means:

  * Columns come from the file, never from a list in this code. An
    installation with sensors we have never heard of keeps them.
  * Observations the database has no column for are dropped, not added. Adding
    a column changes the schema under WeeWX's feet.
  * The daily summaries are maintained the same way WeeWX maintains them, with
    the same weighting, and the metadata version stays at 4.0.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from ..aggregate import Accumulator, start_of_archive_day
from ..obstypes import DEFAULT_POLICY, Policy
from .daily import IntervalError, day_accumulator, weight_of
from .schema import DAY_COLUMNS, DAY_SUMMARY_VERSION, STATS_COLUMNS, Schema
from .schema import read as read_schema
from .wview import ARCHIVE_TABLE, DAY_SUMMARIES

log = logging.getLogger(__name__)


class ArchiveStore:
    """A WeeWX archive database, open for reading and writing."""

    def __init__(self, path: str | Path, table_name: str = "archive",
                 policy: Policy = DEFAULT_POLICY, create: bool = True) -> None:
        self.path = Path(path)
        self.table_name = table_name
        self.policy = policy
        # Fields we had to drop for want of a column, and how often. Reported,
        # never fixed on the quiet.
        self._homeless: dict[str, int] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)

        existed = self.path.exists()
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")

        if not existed:
            if not create:
                raise FileNotFoundError(self.path)
            self._create()
        self.schema = read_schema(self.conn, table_name)
        self._check_version()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> ArchiveStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def reload_schema(self) -> None:
        """Re-read the schema. Needed after anything alters the tables."""
        self.schema = read_schema(self.conn, self.table_name)

    # -- creation --------------------------------------------------------

    def _create(self) -> None:
        """Lay out a fresh database, identical to what WeeWX would create."""
        cols = ", ".join(f'"{name}" {sql_type}' for name, sql_type in ARCHIVE_TABLE)
        with self.conn:
            self.conn.execute(f"CREATE TABLE {self.table_name} ({cols})")
            for obs_type, kind in DAY_SUMMARIES:
                self._create_day_table(obs_type, kind)
            self.conn.execute(
                f"CREATE TABLE {self.table_name}_day__metadata"
                " (name VARCHAR(64) NOT NULL PRIMARY KEY, value TEXT)"
            )
            self.conn.execute(
                f"INSERT INTO {self.table_name}_day__metadata VALUES (?, ?)",
                ("Version", DAY_SUMMARY_VERSION),
            )

    def _create_day_table(self, obs_type: str, kind: str) -> None:
        types = {"dateTime": "INTEGER NOT NULL PRIMARY KEY", "count": "INTEGER",
                 "mintime": "INTEGER", "maxtime": "INTEGER",
                 "sumtime": "INTEGER", "dirsumtime": "INTEGER"}
        cols = ", ".join(
            f'"{c}" {types.get(c, "REAL")}' for c in DAY_COLUMNS[kind]
        )
        self.conn.execute(f"CREATE TABLE {self.table_name}_day_{obs_type} ({cols})")

    def _check_version(self) -> None:
        """Refuse a database whose daily summaries carry known-bad weights.

        WeeWX 4.2.0 read version-2 sums as version 1, and 4.3.0's repair left
        `dirsumtime` unweighted. Both are fixable, by `weectl database
        rebuild-daily` or WeeWX's own `patch_sums`, but silently writing new
        records on top of the damage would mix two weighting schemes in one
        table and make the result unfixable.
        """
        version = self.schema.version
        if version is None or version == DAY_SUMMARY_VERSION:
            return
        raise ValueError(
            f"daily summaries are at version {version}, not {DAY_SUMMARY_VERSION}. "
            "Let WeeWX upgrade them first (weectl database rebuild-daily)."
        )

    # -- reading ---------------------------------------------------------

    def last_timestamp(self) -> int | None:
        return self.conn.execute(f"SELECT max(dateTime) FROM {self.table_name}").fetchone()[0]

    def count(self) -> int:
        return self.conn.execute(f"SELECT count(*) FROM {self.table_name}").fetchone()[0]

    def exists(self, ts: float) -> bool:
        return self.conn.execute(
            f"SELECT 1 FROM {self.table_name} WHERE dateTime = ?", (ts,)
        ).fetchone() is not None

    def record(self, ts: float) -> dict | None:
        cursor = self.conn.execute(
            f"SELECT * FROM {self.table_name} WHERE dateTime = ?", (ts,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return {c: v for c, v in zip(cols, row) if v is not None}

    # -- writing ---------------------------------------------------------

    def add_record(self, record: dict, replace: bool = False,
                   update_daily: bool = True) -> bool:
        """Write one archive record and fold it into the daily summaries.

        Returns False if a record for that timestamp was already there and
        `replace` is not set. That is the normal case when catching up: the
        primary key makes the write idempotent, so replaying packets cannot
        double-count anything.
        """
        known = [c for c in record if self.schema.has_column(c)]
        if "dateTime" not in known:
            raise ValueError("record has no dateTime")
        if len(known) != len(record):
            self._note_homeless(c for c in record if not self.schema.has_column(c))

        verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
        columns = ", ".join(f'"{c}"' for c in known)
        holders = ", ".join("?" for _ in known)
        with self.conn:
            if replace and update_daily:
                # Take the old record back out of the summaries before its
                # replacement goes in, or the two would both be counted.
                old = self.record(record["dateTime"])
                if old is not None:
                    self._unapply_daily(old)
            cur = self.conn.execute(
                f"{verb} INTO {self.table_name} ({columns}) VALUES ({holders})",
                [record[c] for c in known],
            )
            if not cur.rowcount:
                return False
            if update_daily:
                self._apply_daily(record)
        return True

    def _note_homeless(self, columns: Iterable[str]) -> None:
        """Say once, per field, that a reading has nowhere to live.

        A reading only survives the archive interval if the table has a column
        for it. Ecowitt hardware can fill four times the 113 the standard schema
        has, so dropping some is normal -- dropping them *silently* is how a
        sensor ends up missing from a series for a year before anybody notices.

        Nothing is created automatically. Which column a reading belongs in is
        a decision, and the wrong one mixes two sensors into a column that
        nothing afterwards can separate. `weewx-evo columns` lists what is
        being lost; the driver's own tooling says where each one should go.
        """
        for name in columns:
            if name in self._homeless:
                self._homeless[name] += 1
                continue
            self._homeless[name] = 1
            log.warning(
                "%r has no column in %s and is being dropped at every archive "
                "interval. Run 'weewx-evo columns' to see everything affected.",
                name, self.path.name)

    @property
    def homeless(self) -> dict[str, int]:
        """Fields dropped for want of a column, and how often, since startup."""
        return dict(self._homeless)

    def add_column(self, name: str, sql_type: str = "REAL") -> bool:
        """Give a reading somewhere to live. Returns False if it already has one.

        WeeWX reads its schema from the file, so a column added here is one it
        picks up by itself. Back the database up first: SQLite rewrites the
        table, and on a decade of records that is not instant.
        """
        if self.schema.has_column(name):
            return False
        if not name.replace("_", "").isalnum():
            raise ValueError(f"{name!r} is not a usable column name")
        if sql_type.upper() not in ("REAL", "INTEGER", "TEXT"):
            raise ValueError(f"{sql_type!r} is not a column type WeeWX uses")
        with self.conn:
            self.conn.execute(
                f'ALTER TABLE {self.table_name} ADD COLUMN "{name}" {sql_type.upper()}')
            if name not in self.schema.day_types:
                self._create_day_table(name, "scalar")
        self.reload_schema()
        self._homeless.pop(name, None)
        log.info("added column %r (%s) to %s", name, sql_type.upper(), self.path.name)
        return True

    def add_records(self, records: Iterable[dict], replace: bool = False) -> int:
        """Write many records, touching each day's summaries once.

        WeeWX reads and rewrites all of a day's summary tables for every single
        record. At one record every five minutes nobody notices; catching up a
        year turns it into millions of statements. Here the records are grouped
        by day, the day is loaded once, and it is written once -- which is the
        same arithmetic in the same order, because the accumulator does not care
        whether its records arrive one at a time or in a batch.

        Records must be in ascending time order.
        """
        written = 0
        day_sod: int | None = None
        accum: Accumulator | None = None

        for record in records:
            sod = start_of_archive_day(record["dateTime"])
            if sod != day_sod:
                if accum is not None:
                    with self.conn:
                        self._store_day(day_sod, accum)  # type: ignore[arg-type]
                day_sod, accum = sod, None

            if not self.add_record(record, replace=replace, update_daily=False):
                continue
            written += 1

            try:
                weight = weight_of(record)
            except IntervalError:
                continue
            if accum is None:
                accum = self._load_day(sod, record.get("usUnits"))
            accum.add_record(record, weight=weight)

        if accum is not None:
            with self.conn:
                self._store_day(day_sod, accum)  # type: ignore[arg-type]
        return written

    # -- daily summaries -------------------------------------------------

    def _apply_daily(self, record: dict) -> None:
        """Fold one record into its day's summaries."""
        try:
            weight = weight_of(record)
        except IntervalError:
            # WeeWX logs and moves on. The archive record still stands; only
            # its contribution to the daily average is lost.
            return
        sod = start_of_archive_day(record["dateTime"])
        accum = self._load_day(sod, record.get("usUnits"))
        accum.add_record(record, weight=weight)
        self._store_day(sod, accum)

    def _unapply_daily(self, record: dict) -> None:
        """Remove one record's contribution again, for a recomputation.

        Only the sums come back out. Extremes cannot be reversed -- a maximum
        does not remember what the second-highest value was -- so a day whose
        records changed needs `rebuild_day` to get its highs and lows right.
        """
        try:
            weight = weight_of(record)
        except IntervalError:
            return
        sod = start_of_archive_day(record["dateTime"])
        accum = self._load_day(sod, record.get("usUnits"))
        negative = day_accumulator(sod, record.get("usUnits"), self.policy)
        negative.add_record(record, add_hilo=False, weight=weight)
        for obs_type in negative:
            if obs_type not in accum:
                continue
            mine, theirs = accum[obs_type], negative[obs_type]
            for field in ("sum", "count", "wsum", "sumtime",
                          "xsum", "ysum", "dirsumtime", "squaresum", "wsquaresum"):
                if hasattr(mine, field) and hasattr(theirs, field):
                    setattr(mine, field, getattr(mine, field) - getattr(theirs, field))
        self._store_day(sod, accum)

    def _load_day(self, sod: int, unit_system: int | None) -> Accumulator:
        """A day's accumulator, primed with every type the database knows.

        Types with no stored row are initialised empty rather than left out.
        That is deliberate: WeeWX writes a row for every known observation on
        every day it touches, even one that stayed null all day, and a database
        missing those rows is visibly not one WeeWX wrote.
        """
        accum = day_accumulator(sod, unit_system, self.policy)
        for obs_type, kind in self.schema.day_types.items():
            cols = ", ".join(f'"{c}"' for c in STATS_COLUMNS[kind])
            row = self.conn.execute(
                f"SELECT {cols} FROM {self.table_name}_day_{obs_type} WHERE dateTime = ?",
                (sod,),
            ).fetchone()
            accum.set_stats(obs_type, tuple(row) if row is not None else None)
        return accum

    def _store_day(self, sod: int, accum: Accumulator) -> None:
        for obs_type in accum:
            kind = self.schema.day_types.get(obs_type)
            if kind is None:
                # No daily table for this observation. WeeWX ignores it too;
                # the tables are made when the database is, not on the fly.
                continue
            cols = STATS_COLUMNS[kind]
            stats = accum[obs_type].stats_tuple()
            names = ", ".join(f'"{c}"' for c in ("dateTime", *cols))
            holders = ", ".join("?" for _ in range(len(cols) + 1))
            self.conn.execute(
                f"INSERT OR REPLACE INTO {self.table_name}_day_{obs_type}"
                f" ({names}) VALUES ({holders})",
                (sod, *stats),
            )
        self._set_meta("lastUpdate", str(int(time.time())))

    def rebuild_day(self, sod: int) -> int:
        """Recompute one day's summaries from the archive table.

        This is what makes a correction possible: change the records, rebuild
        the day, and the statistics follow. It also blunts any extreme that
        only ever existed in a LOOP packet -- see tools/difftest.py.
        """
        cursor = self.conn.execute(
            f"SELECT * FROM {self.table_name} WHERE dateTime > ? AND dateTime <= ?"
            " ORDER BY dateTime", (sod, sod + 86400),
        )
        cols = [d[0] for d in cursor.description]
        accum = day_accumulator(sod, policy=self.policy)
        # Prime every known type, so the rebuilt day has the same rows as one
        # WeeWX built -- including the empty ones. See _load_day.
        for obs_type in self.schema.day_types:
            accum.set_stats(obs_type)
        n = 0
        for row in cursor:
            record = {c: v for c, v in zip(cols, row) if v is not None}
            try:
                accum.add_record(record, weight=weight_of(record))
            except IntervalError:
                continue
            n += 1

        with self.conn:
            for obs_type in self.schema.day_types:
                self.conn.execute(
                    f"DELETE FROM {self.table_name}_day_{obs_type} WHERE dateTime = ?", (sod,)
                )
            if n:
                self._store_day(sod, accum)
        return n

    def days(self) -> Iterator[int]:
        """Every archive day that has records, in order."""
        seen = None
        for (ts,) in self.conn.execute(
            f"SELECT dateTime FROM {self.table_name} ORDER BY dateTime"
        ):
            sod = start_of_archive_day(ts)
            if sod != seen:
                seen = sod
                yield sod

    # -- metadata --------------------------------------------------------

    def set_meta(self, name: str, value: str) -> None:
        """Write one metadata row. The table WeeWX keeps `lastUpdate` in.

        Drivers use this too: weewx-ecowitt keeps its console list here, under
        the same key WeeWX writes it under, so a database moved between the two
        keeps knowing which console it belongs to.
        """
        self._set_meta(name, value)

    def _set_meta(self, name: str, value: str) -> None:
        self.conn.execute(
            f"INSERT OR REPLACE INTO {self.table_name}_day__metadata (name, value)"
            " VALUES (?, ?)", (name, value),
        )

    def get_meta(self, name: str) -> str | None:
        row = self.conn.execute(
            f"SELECT value FROM {self.table_name}_day__metadata WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else None

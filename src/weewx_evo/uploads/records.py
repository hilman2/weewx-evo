"""Getting an upload the records it owes, in the shape a service expects.

Two jobs, and both are here rather than in each upload.

**Reading from the right thread.** Every upload runs on its own thread, and an
SQLite connection belongs to the thread that opened it. Handing the archiver's
connection to an upload thread is the kind of mistake that works on a laptop
and throws `SQLite objects created in a thread can only be used in that same
thread` on the station, at two in the morning, once. So each thread gets its
own read-only connection, opened the first time it asks.

**Rain the way these services mean it.** The archive stores `rain`: how much
fell in this interval. Every service in this package wants `rainin` -- the last
hour -- and `dailyrainin` -- since local midnight. Neither is a column, both
are a sum over a span, and computing them once here is what keeps the four
uploads from each having their own quietly different SQL. That was WeeWX's
mistake with the two chart generators: both right on their own, disagreeing in
the third decimal, and nobody finds it.

The spans are WeeWX's, exactly: the hour is exclusive on the left and
inclusive on the right, and the day starts at local midnight. A rainfall total
that disagrees with the one WeeWX posted from the same database would be a
transcription error, not an improvement.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, ClassVar

from ..aggregate import start_of_archive_day

log = logging.getLogger(__name__)


class Archive:
    """Read-only access to the archive, one connection per thread."""

    def __init__(self, path: str | Path, table_name: str = "archive") -> None:
        self.path = Path(path)
        self.table_name = table_name
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # Opened read-only through a URI: an upload has no business
            # writing to the archive, and saying so to SQLite is better than
            # trusting that none of this code ever will.
            uri = f"file:{self.path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=10)
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def after(self, ts: int, limit: int) -> list[dict]:
        """Up to `limit` records newer than `ts`, oldest first.

        `ts` of 0 means "the newest one", not "all of history": an upload
        configured today has nothing to catch up on, and posting a station's
        entire archive to Weather Underground on first run is not a thing to
        do by accident.
        """
        conn = self._conn()
        if not ts:
            cursor = conn.execute(
                f"SELECT * FROM {self.table_name} ORDER BY dateTime DESC LIMIT 1")
        else:
            cursor = conn.execute(
                f"SELECT * FROM {self.table_name} WHERE dateTime > ? "
                f"ORDER BY dateTime ASC LIMIT ?", (ts, limit))
        cols = [d[0] for d in cursor.description]
        found = [{c: v for c, v in zip(cols, row, strict=True) if v is not None}
                 for row in cursor.fetchall()]
        return [self.augment(record) for record in found]

    def augment(self, record: dict) -> dict:
        """Add the rain totals these services ask for.

        Leaves the record alone if the database has no `rain` column, which a
        station without a gauge legitimately does not. Absent is the right
        answer there; a zero would be a claim about the weather.
        """
        ts = int(record.get("dateTime") or 0)
        if not ts or "rain" not in self._columns():
            return record
        record = dict(record)
        system = record.get("usUnits")
        if "hourRain" not in record:
            # Exclusive on the left, inclusive on the right -- WeeWX's span,
            # kept because a total that differs from the one it posted from
            # the same database is a transcription error, not a better idea.
            record["hourRain"] = self._rain(ts - 3600, ts, system)
        if "rain24" not in record:
            record["rain24"] = self._rain(ts - 86400, ts, system)
        if "dayRain" not in record:
            # Local midnight, and the record stamped exactly midnight belongs
            # to the day that just ended. That is WeeWX's reading of it and
            # the archive's own day boundary, so the two agree.
            record["dayRain"] = self._rain(start_of_archive_day(ts), ts, system)
        return {k: v for k, v in record.items() if v is not None}

    def _rain(self, start: int, stop: int, system: object) -> float | None:
        """Rain in a span, or None if the units in it are not all the same.

        The units check is not pedantry. A database whose station was swapped
        from a US console to a metric one has both in it, and summing across
        that boundary produces a number that is neither -- a downpour or a
        drizzle, published as fact.
        """
        row = self._conn().execute(
            f"SELECT SUM(rain), MIN(usUnits), MAX(usUnits) FROM {self.table_name} "
            f"WHERE dateTime > ? AND dateTime <= ?", (start, stop)).fetchone()
        if row is None or row[0] is None:
            return None
        if system is not None and not (row[1] == row[2] == system):
            log.debug("mixed unit systems between %s and %s; leaving the rain "
                      "total out rather than adding two of them together",
                      start, stop)
            return None
        return float(row[0])

    def _columns(self) -> set[str]:
        columns = getattr(self._local, "columns", None)
        if columns is None:
            cursor = self._conn().execute(f"SELECT * FROM {self.table_name} LIMIT 0")
            columns = {d[0] for d in cursor.description}
            self._local.columns = columns
        return columns

    #: The object itself is the callable the runner wants. A bare bound
    #: method would work too and was the first version -- but then nothing
    #: can reach the instance again, so nothing can close the connection.
    #: On Windows that is a file that cannot be deleted while the process
    #: lives, which is how the tests found it.
    __call__ = after


def source(path: str | Path, table_name: str = "archive") -> Archive:
    """A `records(after, limit)` callable over an archive file.

    What the runner wants, without the runner knowing there is a database
    behind it -- which is what lets a test hand it a list.
    """
    return Archive(path, table_name)


class Live:
    """Read-only access to the live packets, one connection per thread.

    Why this exists beside `Archive`: an archive record is a five-minute
    average that appears five minutes late, and a dashboard showing one is a
    dashboard that is wrong for four minutes and fifty-nine seconds. The
    skins this is for -- Belchertown, jas, weewx-wdc -- redraw on every
    packet, and the packets are in this table the moment the listener writes
    them.

    It stays a read of the database rather than a callback from the listener,
    because that is what lets the listener and the archiver run as separate
    processes. A live feed that only works when they are one process would
    quietly take that apart.

    **The quality rules apply here too, and that is not optional.** They live
    in `archiver.build()`, which is the right place for the decision: the
    archive is what has to be defensible. But this table is read by two
    things, and only one of them went through the archiver -- so a spike the
    archive throws away was still published, every ten seconds, to the live
    page and the broker. The reading a visitor sees would be one the
    station's own charts do not have, and nothing on either side could show
    the disagreement.

    Same rules, same file, same `Check`. Not a second copy of the arithmetic:
    that is the mistake `chartdata.py` describes, and a limit that disagreed
    with the archiver by a tenth would be worse than none.
    """

    #: Which console a live reading comes from, when a site has more than
    #: one. There is one live table and several consoles writing into it, so
    #: "the newest packet" is not an answer -- it is whichever of them
    #: happened to report last, and a page built on it flickers between a
    #: garden and a shed.
    #:
    #: `main` is the default and is what a station means by "the readings":
    #: the console whose measurements go in their own columns. The rest
    #: exist because a real installation has reasons for each -- a main
    #: console that drops out at night, two sensors worth averaging, a shed
    #: that is the only thing measuring what somebody wants to see.
    PICKS: ClassVar[dict[str, str]] = {
        "main": "The main console. Its readings are the station's.",
        "main-or-extra": "The main console, or an extra one when it is "
                         "silent.",
        "newest": "Whichever console reported last.",
        "average": "The average of every console that reported.",
        "extra": "The extra consoles only.",
    }
    DEFAULT_PICK = "main"

    #: How stale the main console's last reading may be before
    #: `main-or-extra` falls back to another. Two archive intervals at the
    #: usual five minutes: long enough that one missed upload is not a
    #: switch, short enough that a console off since last night is.
    STALE = 600.0

    def __init__(self, path: str | Path,
                 sources: list[str] | None = None,
                 pick: str = DEFAULT_PICK,
                 main: list[str] | None = None,
                 policy: Any = None) -> None:
        self.path = Path(path)
        #: The quality rules, or None where none are configured -- which is
        #: every installation until somebody writes some, and costs it a
        #: single `is None`.
        #:
        #: The policy rather than a `Check`: a check carries the run-up a
        #: spike rule needs, so it is state, and this object is read from one
        #: thread per upload. Shared, two uploads would judge each other's
        #: readings as their own history -- and the second one publishing
        #: would see every packet twice.
        self.policy = policy
        #: Whose readings to publish. There is one live table for the whole
        #: installation -- only the archive is per series -- so an upload
        #: that belongs to one site has to say which consoles are its own.
        #:
        #: Without it a station with two sites published the same live
        #: readings to both, taken from whichever console reported last: a
        #: north-field page showing 21 C beside its own archive's 8 C, with
        #: nothing on the page able to notice. The archiver has always
        #: filtered here (`live.packets(..., sources=...)`); this is the
        #: same filter on the other reader of the same table.
        #:
        #: None means every console, which is what one archive wants and
        #: what every installation had before there were two.
        self.sources = list(sources) if sources else None
        #: Which of them a reading is taken from. See `PICKS`.
        self.pick = str(pick or self.DEFAULT_PICK)
        #: The consoles that call themselves the main one -- normally one.
        #: Empty means nobody said, and then every pick behaves as `newest`,
        #: which is what an installation without announced stations had.
        self.main = list(main) if main else []
        self._local = threading.local()

    def for_sources(self, sources: list[str] | None,
                    pick: str = "", main: list[str] | None = None) -> Live:
        """The same table, seen through one site's consoles."""
        return Live(self.path, sources, pick or self.pick,
                    main if main is not None else self.main, self.policy)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            uri = f"file:{self.path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=10)
            # The listener writes this file continuously. WAL is what lets a
            # reader in without blocking it, and it is already set by the
            # writer -- this only avoids fighting over it.
            conn.execute("PRAGMA query_only=ON")
            self._local.conn = conn
        return conn

    def after(self, ts: int, limit: int = 1) -> list[dict]:
        """The newest packets after `ts`, oldest first.

        `limit` is honoured but a live publisher wants one: what is current.
        Publishing a backlog to a broker leaves the last of it showing as
        now, which is worse than having published nothing.
        """
        conn = self._conn()
        # The consoles this upload speaks for, as a WHERE clause. Built from
        # a list this process holds rather than interpolated from anything
        # that arrived over the network -- the names come from
        # `stations.toml`, and they are placeholders either way.
        wanted = self._chosen()
        mine, names = "", []
        if wanted:
            mine = f" AND source IN ({','.join('?' * len(wanted))})"
            names = list(wanted)

        # The average of several consoles is not a row in the table, so it is
        # worked out rather than selected. Only for the current reading:
        # averaging a backlog would invent records that never existed.
        if self.pick == "average" and not ts:
            averaged = self._averaged(conn, wanted)
            if averaged is not None:
                return [averaged]

        if not ts:
            rows = conn.execute(
                "SELECT dateTime, usUnits, interval, data FROM packet "
                f"WHERE 1=1{mine} "
                "ORDER BY dateTime DESC, seq DESC LIMIT 1", names).fetchall()
        else:
            rows = conn.execute(
                "SELECT dateTime, usUnits, interval, data FROM packet "
                f"WHERE dateTime > ?{mine} "
                "ORDER BY dateTime ASC, seq ASC LIMIT ?",
                [ts, *names, limit]).fetchall()
        found = []
        for when, units, interval, data in rows:
            try:
                record = dict(json.loads(data))
            except (TypeError, ValueError):
                continue
            record["dateTime"] = int(when)
            record["usUnits"] = units
            if interval is not None:
                record["interval"] = interval
            found.append({k: v for k, v in record.items() if v is not None})
        return [self._screened(one) for one in found]

    def _screened(self, record: dict) -> dict:
        """One packet with the rules applied. Unchanged where there are none.

        Calibration as well as the limits, and in that order, because that is
        the order `archiver.build()` uses: an offset is part of what the
        reading *is*, so a limit is about the corrected value. A live page
        showing the raw one beside an archive holding the corrected one is
        the same disagreement in a smaller font.

        A reading the rules refuse is dropped, not zeroed and not held: the
        packet after it is seconds away, and the live table is the one place
        where an absent reading costs nothing.
        """
        checker = self._checker()
        if checker is None:
            return record
        try:
            stamp = float(record.get("dateTime") or 0)
            system = record.get("usUnits")
            source = str(record.get("source") or "")
            fixed = checker.calibrate(record, source, system)
            # The verdicts are the archiver's to log: it has the interval
            # the reading belongs to and something to say about it. Here the
            # same reading is judged six times a minute, and a line each
            # would bury the log the moment one sensor went odd.
            screened, _verdicts = checker.check(fixed, stamp, source, system)
            return screened
        except Exception:
            # The rules must never be able to stop the live readings. A
            # quality file with something odd in it is a settings problem;
            # a page that stops updating because of one is an outage.
            log.warning("could not apply the quality rules to a live packet",
                        exc_info=True)
            return record

    def _checker(self) -> Any:
        """This thread's `Check`, built once. None where there are no rules."""
        if not self.policy:
            return None
        found = getattr(self._local, "check", None)
        if found is None:
            from .. import quality as quality_module

            found = self._local.check = quality_module.Check(self.policy)
        return found

    # -- which console ---------------------------------------------------

    def _chosen(self) -> list[str]:
        """The consoles to read from, after applying `pick`.

        Empty means every console, which is the answer for an installation
        that has announced none: there is nothing to pick between, and the
        newest packet is the reading.
        """
        mine = self.sources
        main = [one for one in self.main if not mine or one in mine]
        if not main:
            # Nobody said which is the main one. Every pick collapses to
            # "the newest of what there is" -- not a fallback being clever,
            # but what this did before there was a choice.
            return list(mine or [])

        if self.pick in ("newest", "average"):
            return list(mine or [])
        if self.pick == "extra":
            # The extras only. Falling back to the main one rather than to
            # nothing: a site whose extras have all been removed should show
            # a reading, not an empty page.
            return [one for one in (mine or []) if one not in main] or list(main)
        if self.pick == "main-or-extra":
            # The main console unless it has gone quiet. Measured against
            # the newest packet in this table rather than against the clock:
            # a site that has been off for a week must not read as "the main
            # console is stale", and a container whose clock is adrift must
            # not decide it either.
            if self._quiet_for() > self.STALE:
                return list(mine or [])
            return main
        return main

    def _quiet_for(self) -> float:
        """Seconds between the main console's last packet and any console's.

        Both facts come out of the same file, so a site switched off
        entirely compares as "not stale": there is nothing newer to compare
        against, and switching away from the main console because the whole
        site is quiet would be noise.
        """
        conn = self._conn()
        main = [one for one in self.main
                if not self.sources or one in self.sources]
        if not main:
            return 0.0
        theirs = conn.execute(
            "SELECT MAX(dateTime) FROM packet WHERE source IN "
            f"({','.join('?' * len(main))})", main).fetchone()[0]
        if theirs is None:
            return float("inf")      # it has never reported
        if self.sources:
            newest = conn.execute(
                "SELECT MAX(dateTime) FROM packet WHERE source IN "
                f"({','.join('?' * len(self.sources))})",
                list(self.sources)).fetchone()[0]
        else:
            newest = conn.execute(
                "SELECT MAX(dateTime) FROM packet").fetchone()[0]
        return float((newest or theirs) - theirs)

    def _averaged(self, conn: sqlite3.Connection,
                  wanted: list[str]) -> dict | None:
        """One reading per console, averaged field by field.

        Each console's *newest* packet, not every packet in a window: two
        sensors are being combined, not a time series smoothed. A field only
        one of them reports comes through as that one's value, which is
        right -- the average of one number is that number.

        Directions are taken from the newest console rather than averaged.
        350 and 10 average to 180, which is the opposite direction.
        """
        mine, names = "", []
        if wanted:
            mine = f" WHERE source IN ({','.join('?' * len(wanted))})"
            names = list(wanted)
        rows = conn.execute(
            "SELECT source, MAX(dateTime), usUnits, interval, data "
            f"FROM packet{mine} GROUP BY source", names).fetchall()
        if not rows:
            return None

        latest: dict[str, Any] = {}
        sums: dict[str, list[float]] = {}
        when, units, interval = 0, None, None
        for _source, stamp, unit, gap, data in sorted(rows,
                                                      key=lambda r: r[1]):
            try:
                record = dict(json.loads(data))
            except (TypeError, ValueError):
                continue
            if stamp >= when:
                when, units, interval = int(stamp), unit, gap
            for field, value in record.items():
                if value is None:
                    continue
                if (isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or field.endswith("Dir")):
                    latest[field] = value
                    continue
                sums.setdefault(field, []).append(float(value))

        out: dict[str, Any] = dict(latest)
        for field, values in sums.items():
            out[field] = sum(values) / len(values)
        out["dateTime"] = when
        out["usUnits"] = units
        if interval is not None:
            out["interval"] = interval
        return {k: v for k, v in out.items() if v is not None}

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    __call__ = after


def live_source(path: str | Path, policy: Any = None) -> Live:
    """A `records(after, limit)` callable over the live table."""
    return Live(path, policy=policy)

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
    """

    def __init__(self, path: str | Path,
                 sources: list[str] | None = None) -> None:
        self.path = Path(path)
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
        self._local = threading.local()

    def for_sources(self, sources: list[str] | None) -> Live:
        """The same table, seen through one site's consoles."""
        return Live(self.path, sources)

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
        mine, names = "", []
        if self.sources:
            mine = f" AND source IN ({','.join('?' * len(self.sources))})"
            names = list(self.sources)

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
        return found

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    __call__ = after


def live_source(path: str | Path) -> Live:
    """A `records(after, limit)` callable over the live table."""
    return Live(path)

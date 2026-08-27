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


def source(path: str | Path, table_name: str = "archive"):
    """A `records(after, limit)` callable over an archive file.

    What the runner wants, without the runner knowing there is a database
    behind it -- which is what lets a test hand it a list.
    """
    archive = Archive(path, table_name)
    return archive.after

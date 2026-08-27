"""Where forecasts are kept: its own file, never the archive.

That is the one rule of this project restated. `archive` is what WeeWX wrote
and what WeeWX must be able to keep reading -- a column of predicted
temperatures in it would be a lie that averages badly for years, and
`archive_day_*` would cheerfully summarise the lie.

So: `forecast.sdb`, beside the archive, and everything about it is designed
around the fact that it is disposable.

  * **Replaced, not accumulated.** A new run from a source deletes that
    source's previous one. Nobody wants yesterday's forecast for today, and
    keeping it turns a small file into a large one with no reader.
  * **One table for the hours, one for the days, one for the warnings.** Not
    one wide table: a warning has nothing in common with a temperature, and a
    day is not an hour with different columns.
  * **Deleting the file costs one download.** Which is the definition of a
    cache, and the reason nothing here needs a migration path.

Each source's rows are tagged with its name, so two sources can be configured
at once and a page can ask for either -- the German page shows MOSMIX and the
warnings from the DWD, the same station's English page shows Open-Meteo.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from . import Day, Moment, Reading, Warning

log = logging.getLogger(__name__)

#: Columns in the hourly table, in order. Kept explicit rather than derived
#: from the dataclass: a rename in the model would otherwise silently drop a
#: column's data on the next write.
HOUR_COLUMNS = ("outTemp", "dewpoint", "appTemp", "outHumidity", "barometer",
                "windSpeed", "windDir", "windGust", "cloudCover", "rain",
                "snow", "rainProbability", "radiation", "UV", "visibility",
                "code")

DAY_COLUMNS = ("tempMax", "tempMin", "rain", "snow", "rainProbability",
               "windMax", "windGustMax", "windDir", "UVMax", "sunrise",
               "sunset", "sunshine", "code")

WARNING_COLUMNS = ("identifier", "event", "severity", "urgency", "certainty",
                   "starts", "ends", "issued", "headline", "description",
                   "instruction", "area", "kind", "language")


class ForecastStore:
    """The forecast database, open for reading and writing."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._create()

    # -- connections -----------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        """This thread's connection, opened on first use.

        The poller writes on its own thread and a feed reads on another. An
        SQLite connection belongs to the thread that opened it, and the
        alternative -- one connection with `check_same_thread=False` -- moves
        the problem rather than solving it.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, isolation_level=None, timeout=10)
            # WAL so a reader never blocks the poller, the same as the live
            # table. `synchronous=NORMAL` because this is a cache: losing the
            # last write to a power cut costs one fetch.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def __enter__(self) -> ForecastStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _create(self) -> None:
        hours = ", ".join(f"{name} REAL" for name in HOUR_COLUMNS)
        days = ", ".join(f"{name} REAL" for name in DAY_COLUMNS)
        self.conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS moment (
                source TEXT NOT NULL, dateTime INTEGER NOT NULL,
                usUnits INTEGER NOT NULL, {hours},
                PRIMARY KEY (source, dateTime));
            CREATE TABLE IF NOT EXISTS day (
                source TEXT NOT NULL, dateTime INTEGER NOT NULL,
                usUnits INTEGER NOT NULL, {days},
                PRIMARY KEY (source, dateTime));
            CREATE TABLE IF NOT EXISTS warning (
                source TEXT NOT NULL, identifier TEXT NOT NULL,
                event TEXT, severity TEXT, urgency TEXT, certainty TEXT,
                starts INTEGER, ends INTEGER, issued INTEGER,
                headline TEXT, description TEXT, instruction TEXT,
                area TEXT, kind TEXT, language TEXT,
                PRIMARY KEY (source, identifier));
            CREATE TABLE IF NOT EXISTS run (
                source TEXT PRIMARY KEY, issued INTEGER, fetched INTEGER,
                note TEXT, hours INTEGER, days INTEGER, warnings INTEGER);
            CREATE INDEX IF NOT EXISTS moment_time ON moment (dateTime);
            CREATE INDEX IF NOT EXISTS warning_span ON warning (starts, ends);
        """)

    # -- writing ---------------------------------------------------------

    def store(self, reading: Reading, fetched: int) -> None:
        """Replace everything this source had with what it just returned.

        In one transaction: a page reading halfway through a replace would
        see a forecast with a hole in it, and the hole would look like a gap
        in the data rather than a moment in time.

        A source that returned nothing replaces nothing. That matters --
        MeteoAlarm answers with an empty feed when the weather is calm, and
        that *is* the answer, but a source that failed and returned an empty
        `Reading` would otherwise wipe a good forecast. The runner never
        calls this on a failure, which is where the distinction is kept.
        """
        source = reading.source
        with self._lock:
            conn = self.conn
            conn.execute("BEGIN")
            try:
                if reading.hours:
                    conn.execute("DELETE FROM moment WHERE source = ?", (source,))
                    conn.executemany(
                        f"INSERT INTO moment (source, dateTime, usUnits, "
                        f"{', '.join(HOUR_COLUMNS)}) VALUES "
                        f"({', '.join(['?'] * (len(HOUR_COLUMNS) + 3))})",
                        [self._row(source, m, HOUR_COLUMNS) for m in reading.hours])
                if reading.days:
                    conn.execute("DELETE FROM day WHERE source = ?", (source,))
                    conn.executemany(
                        f"INSERT INTO day (source, dateTime, usUnits, "
                        f"{', '.join(DAY_COLUMNS)}) VALUES "
                        f"({', '.join(['?'] * (len(DAY_COLUMNS) + 3))})",
                        [self._row(source, d, DAY_COLUMNS) for d in reading.days])
                # Warnings are always replaced, including with nothing: an
                # empty warning feed means the warnings have ended, and
                # leaving the old ones up is the one failure that matters
                # here. A source that could not be reached does not get this
                # far.
                conn.execute("DELETE FROM warning WHERE source = ?", (source,))
                if reading.warnings:
                    conn.executemany(
                        f"INSERT INTO warning (source, "
                        f"{', '.join(WARNING_COLUMNS)}) VALUES "
                        f"({', '.join(['?'] * (len(WARNING_COLUMNS) + 1))})",
                        [self._warning_row(source, w) for w in reading.warnings])
                conn.execute(
                    "INSERT OR REPLACE INTO run (source, issued, fetched, note, "
                    "hours, days, warnings) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (source, reading.issued or fetched, fetched, reading.note,
                     len(reading.hours), len(reading.days),
                     len(reading.warnings)))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _row(source: str, item: object, columns: tuple[str, ...]) -> tuple:
        return (source, int(item.dateTime), int(item.usUnits),
                *(getattr(item, name, None) for name in columns))

    @staticmethod
    def _warning_row(source: str, warning: Warning) -> tuple:
        return (source, *(getattr(warning, name, None)
                          for name in WARNING_COLUMNS))

    def forget(self, source: str) -> None:
        """Everything from one source, gone. For an unconfigured source."""
        with self._lock:
            conn = self.conn
            for table in ("moment", "day", "warning", "run"):
                conn.execute(f"DELETE FROM {table} WHERE source = ?", (source,))

    def prune(self, before: int) -> int:
        """Drop hours and warnings that are in the past.

        A forecast is only ever about the future, so what is behind us is
        landfill -- except that a page drawing the forecast against what
        happened wants a little of it, which is why the caller decides how
        far back rather than this.
        """
        with self._lock:
            conn = self.conn
            dropped = conn.execute(
                "DELETE FROM moment WHERE dateTime < ?", (before,)).rowcount
            dropped += conn.execute(
                "DELETE FROM warning WHERE ends IS NOT NULL AND ends < ?",
                (before,)).rowcount
            return dropped

    # -- reading ---------------------------------------------------------

    def sources(self) -> list[str]:
        return [row[0] for row in
                self.conn.execute("SELECT source FROM run ORDER BY source")]

    def run(self, source: str) -> dict | None:
        """When this source last answered, and with how much."""
        cursor = self.conn.execute(
            "SELECT source, issued, fetched, note, hours, days, warnings "
            "FROM run WHERE source = ?", (source,))
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([d[0] for d in cursor.description], row, strict=True))

    def hours(self, source: str = "", start: int = 0, stop: int = 0,
              limit: int = 0) -> list[Moment]:
        """The hourly forecast, in time order."""
        rows = self._select("moment", HOUR_COLUMNS, source, start, stop, limit)
        return [Moment(dateTime=r["dateTime"], usUnits=r["usUnits"],
                       **{k: r[k] for k in HOUR_COLUMNS if r.get(k) is not None})
                for r in rows]

    def days(self, source: str = "", start: int = 0, stop: int = 0,
             limit: int = 0) -> list[Day]:
        rows = self._select("day", DAY_COLUMNS, source, start, stop, limit)
        return [Day(dateTime=r["dateTime"], usUnits=r["usUnits"],
                    **{k: r[k] for k in DAY_COLUMNS if r.get(k) is not None})
                for r in rows]

    def warnings(self, source: str = "", active_at: int = 0,
                 minimum: str = "") -> list[Warning]:
        """Warnings, most severe first.

        `active_at` keeps only what covers that instant. A warning that has
        not started yet is real and worth showing -- "storm tonight" is the
        point of a warning -- so the default shows everything stored, and a
        page that wants only what is happening now asks for it.
        """
        sql = ["SELECT source, " + ", ".join(WARNING_COLUMNS) + " FROM warning"]
        where, params = [], []
        if source:
            where.append("source = ?")
            params.append(source)
        if active_at:
            where.append("starts <= ? AND (ends IS NULL OR ends >= ?)")
            params += [active_at, active_at]
        if where:
            sql.append("WHERE " + " AND ".join(where))
        cursor = self.conn.execute(" ".join(sql), params)
        names = [d[0] for d in cursor.description]
        found = [Warning(**dict(zip(names, row, strict=True)))
                 for row in cursor.fetchall()]
        rank = {"minor": 1, "moderate": 2, "severe": 3, "extreme": 4}.get(
            minimum.lower(), 0)
        found = [w for w in found if w.rank >= rank]
        # Most severe first, then soonest. That is the order a page wants and
        # doing it here means every reader gets it right.
        found.sort(key=lambda w: (-w.rank, w.starts))
        return found

    def _select(self, table: str, columns: tuple[str, ...], source: str,
                start: int, stop: int, limit: int) -> list[dict]:
        sql = [f"SELECT dateTime, usUnits, {', '.join(columns)} FROM {table}"]
        where, params = [], []
        if source:
            where.append("source = ?")
            params.append(source)
        if start:
            where.append("dateTime >= ?")
            params.append(start)
        if stop:
            where.append("dateTime <= ?")
            params.append(stop)
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY dateTime")
        if limit:
            sql.append("LIMIT ?")
            params.append(limit)
        cursor = self.conn.execute(" ".join(sql), params)
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

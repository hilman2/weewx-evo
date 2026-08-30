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

And with the **series** they are for. An installation may keep several, each
for its own place, and a forecast is about a place before it is about
anything else. One file for all of them, beside whichever archive
`archive_db` names: the path is a property of the installation, and a file
per place would separate nothing on the layout the settings page offers,
where every archive is proposed as `data/<name>.sdb` and every one of them
resolves to the same parent.

So `archive` is the first part of every key here. Not merely a column: a run
replaces what its source had by deleting on the key first, so an unkeyed
column would have the second place erase the first every hour, alternating,
with every page reading whichever ran last.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from . import DEFAULT_ARCHIVE as _DEFAULT_ARCHIVE
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

#: What the one series was called before there were several, and what every
#: row a migration carries over is given. Spelled out rather than imported:
#: this module imports nothing of the project's outside its own package and
#: is the better for it. The tests check it against `archives.DEFAULT` and
#: `db.live.DEFAULT_ARCHIVE`, which is where a drift would otherwise wait.
DEFAULT_ARCHIVE = _DEFAULT_ARCHIVE

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
        self._migrate()

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
                archive TEXT NOT NULL DEFAULT '{DEFAULT_ARCHIVE}',
                source TEXT NOT NULL, dateTime INTEGER NOT NULL,
                usUnits INTEGER NOT NULL, {hours},
                PRIMARY KEY (archive, source, dateTime));
            CREATE TABLE IF NOT EXISTS day (
                archive TEXT NOT NULL DEFAULT '{DEFAULT_ARCHIVE}',
                source TEXT NOT NULL, dateTime INTEGER NOT NULL,
                usUnits INTEGER NOT NULL, {days},
                PRIMARY KEY (archive, source, dateTime));
            CREATE TABLE IF NOT EXISTS warning (
                archive TEXT NOT NULL DEFAULT '{DEFAULT_ARCHIVE}',
                source TEXT NOT NULL, identifier TEXT NOT NULL,
                event TEXT, severity TEXT, urgency TEXT, certainty TEXT,
                starts INTEGER, ends INTEGER, issued INTEGER,
                headline TEXT, description TEXT, instruction TEXT,
                area TEXT, kind TEXT, language TEXT,
                PRIMARY KEY (archive, source, identifier));
            CREATE TABLE IF NOT EXISTS run (
                archive TEXT NOT NULL DEFAULT '{DEFAULT_ARCHIVE}',
                source TEXT NOT NULL, issued INTEGER, fetched INTEGER,
                note TEXT, hours INTEGER, days INTEGER, warnings INTEGER,
                PRIMARY KEY (archive, source));
            CREATE INDEX IF NOT EXISTS moment_time ON moment (dateTime);
            CREATE INDEX IF NOT EXISTS warning_span ON warning (starts, ends);
        """)

    def _migrate(self) -> None:
        """Bring a store made before there were several series up to date.

        `CREATE TABLE IF NOT EXISTS` with a different key is a silent no-op on
        a file that already has the table -- measured -- so without this every
        installation with a `forecast.sdb` would keep the one-column key while
        the new code inserted onto it, and the second place would replace the
        first's rows on their shared key.

        The rows are carried over rather than dropped. A forecast is a cache
        and dropping it costs one download, which this module's own header
        says -- but the download happens in whichever process runs the poller,
        and on a split deployment that is not the process that opens the file
        first. The web process would empty the store and the archiver would
        not refetch until its next slot: an hour of blank pages, for nothing.

        The old key's meaning becomes the new column's value. Not an
        invention: before there were archives every row was about the one
        place, and that place is `default`.

        One transaction for all four tables. Separately, a crash between the
        second and the third leaves a store that opens clean, is missing a
        table's rows, and has a `*_one_series` table beside it that nothing
        will ever look at again.

        The indexes are recreated at the end because `ALTER TABLE ... RENAME
        TO` carries them to the renamed table and `DROP TABLE` takes them with
        it -- measured, and invisible afterwards, because every query still
        answers, by scan.
        """
        # `not have` as well, for the reason `db/live.py` has it: `table_info`
        # on a table that does not exist answers with nothing rather than
        # raising, and a fresh file has none of these yet.
        have = {row[1] for row in self.conn.execute("PRAGMA table_info(moment)")}
        if not have or "archive" in have:
            return

        hours = ", ".join(f"{name} REAL" for name in HOUR_COLUMNS)
        days = ", ".join(f"{name} REAL" for name in DAY_COLUMNS)
        hour_names = ", ".join(HOUR_COLUMNS)
        day_names = ", ".join(DAY_COLUMNS)
        warning_names = ", ".join(WARNING_COLUMNS)
        self.conn.executescript(f"""
            BEGIN;
            ALTER TABLE moment RENAME TO moment_one_series;
            CREATE TABLE moment (
                archive TEXT NOT NULL DEFAULT '{DEFAULT_ARCHIVE}',
                source TEXT NOT NULL, dateTime INTEGER NOT NULL,
                usUnits INTEGER NOT NULL, {hours},
                PRIMARY KEY (archive, source, dateTime));
            INSERT INTO moment (archive, source, dateTime, usUnits, {hour_names})
                SELECT '{DEFAULT_ARCHIVE}', source, dateTime, usUnits,
                       {hour_names} FROM moment_one_series;
            DROP TABLE moment_one_series;

            ALTER TABLE day RENAME TO day_one_series;
            CREATE TABLE day (
                archive TEXT NOT NULL DEFAULT '{DEFAULT_ARCHIVE}',
                source TEXT NOT NULL, dateTime INTEGER NOT NULL,
                usUnits INTEGER NOT NULL, {days},
                PRIMARY KEY (archive, source, dateTime));
            INSERT INTO day (archive, source, dateTime, usUnits, {day_names})
                SELECT '{DEFAULT_ARCHIVE}', source, dateTime, usUnits,
                       {day_names} FROM day_one_series;
            DROP TABLE day_one_series;

            ALTER TABLE warning RENAME TO warning_one_series;
            CREATE TABLE warning (
                archive TEXT NOT NULL DEFAULT '{DEFAULT_ARCHIVE}',
                source TEXT NOT NULL, identifier TEXT NOT NULL,
                event TEXT, severity TEXT, urgency TEXT, certainty TEXT,
                starts INTEGER, ends INTEGER, issued INTEGER,
                headline TEXT, description TEXT, instruction TEXT,
                area TEXT, kind TEXT, language TEXT,
                PRIMARY KEY (archive, source, identifier));
            INSERT INTO warning (archive, source, {warning_names})
                SELECT '{DEFAULT_ARCHIVE}', source, {warning_names}
                FROM warning_one_series;
            DROP TABLE warning_one_series;

            ALTER TABLE run RENAME TO run_one_series;
            CREATE TABLE run (
                archive TEXT NOT NULL DEFAULT '{DEFAULT_ARCHIVE}',
                source TEXT NOT NULL, issued INTEGER, fetched INTEGER,
                note TEXT, hours INTEGER, days INTEGER, warnings INTEGER,
                PRIMARY KEY (archive, source));
            INSERT INTO run (archive, source, issued, fetched, note,
                             hours, days, warnings)
                SELECT '{DEFAULT_ARCHIVE}', source, issued, fetched, note,
                       hours, days, warnings FROM run_one_series;
            DROP TABLE run_one_series;

            CREATE INDEX IF NOT EXISTS moment_time ON moment (dateTime);
            CREATE INDEX IF NOT EXISTS warning_span ON warning (starts, ends);
            COMMIT;
        """)
        log.info("%s: the forecast now names the series it is for", self.path)

    # -- writing ---------------------------------------------------------

    def store(self, reading: Reading, fetched: int, archive: str) -> None:
        """Replace everything this source had, for this series, with what it
        just returned.

        `archive` is third and required. A default here is the one thing that
        would let a caller store a second place's forecast on the first
        place's key, and every delete below is on that key.

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
                    conn.execute("DELETE FROM moment WHERE archive = ? AND source = ?",
                             (archive, source))
                    conn.executemany(
                        f"INSERT INTO moment (archive, source, dateTime, "
                        f"usUnits, {', '.join(HOUR_COLUMNS)}) VALUES "
                        f"({', '.join(['?'] * (len(HOUR_COLUMNS) + 4))})",
                        [self._row(archive, source, m, HOUR_COLUMNS)
                         for m in reading.hours])
                if reading.days:
                    conn.execute("DELETE FROM day WHERE archive = ? AND source = ?",
                             (archive, source))
                    conn.executemany(
                        f"INSERT INTO day (archive, source, dateTime, "
                        f"usUnits, {', '.join(DAY_COLUMNS)}) VALUES "
                        f"({', '.join(['?'] * (len(DAY_COLUMNS) + 4))})",
                        [self._row(archive, source, d, DAY_COLUMNS)
                         for d in reading.days])
                # Warnings are always replaced, including with nothing: an
                # empty warning feed means the warnings have ended, and
                # leaving the old ones up is the one failure that matters
                # here. A source that could not be reached does not get this
                # far.
                conn.execute("DELETE FROM warning WHERE archive = ? AND source = ?",
                             (archive, source))
                if reading.warnings:
                    conn.executemany(
                        f"INSERT INTO warning (archive, source, "
                        f"{', '.join(WARNING_COLUMNS)}) VALUES "
                        f"({', '.join(['?'] * (len(WARNING_COLUMNS) + 2))})",
                        [self._warning_row(archive, source, w)
                         for w in reading.warnings])
                conn.execute(
                    "INSERT OR REPLACE INTO run (archive, source, issued, "
                    "fetched, note, hours, days, warnings) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (archive, source, reading.issued or fetched, fetched,
                     reading.note,
                     len(reading.hours), len(reading.days),
                     len(reading.warnings)))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _row(archive: str, source: str, item: object,
             columns: tuple[str, ...]) -> tuple:
        return (archive, source, int(item.dateTime), int(item.usUnits),
                *(getattr(item, name, None) for name in columns))

    @staticmethod
    def _warning_row(archive: str, source: str, warning: Warning) -> tuple:
        return (archive, source, *(getattr(warning, name, None)
                                   for name in WARNING_COLUMNS))

    def forget(self, archive: str, source: str) -> None:
        """Everything one source had for one series, gone."""
        with self._lock:
            conn = self.conn
            for table in ("moment", "day", "warning", "run"):
                conn.execute(
                    f"DELETE FROM {table} WHERE archive = ? AND source = ?",
                    (archive, source))

    def keep(self, known: set[tuple[str, str]]) -> int:
        """Everything not in `known`, gone. Pairs of (archive, source).

        Two things end up here. A source taken out of the configuration:
        nothing ever called `forget`, so its rows went on answering
        `$forecast` for good -- a pre-existing leak this closes on the way
        past. And, once per installation, the rows a store made before its
        key named an entry rather than a provider.

        An empty set does nothing rather than emptying the store. It means
        the caller could not work out what is configured, and a tidy that
        empties the cache on a failed read is not a tidy.
        """
        if not known:
            return 0
        dropped = 0
        with self._lock:
            conn = self.conn
            stored = {(row[0], row[1]) for row in
                      conn.execute("SELECT archive, source FROM run")}
            for archive, source in sorted(stored - known):
                for table in ("moment", "day", "warning", "run"):
                    dropped += conn.execute(
                        f"DELETE FROM {table} WHERE archive = ? AND source = ?",
                        (archive, source)).rowcount
                log.info("forecast: %r is not configured for %r any more; "
                         "its rows are gone", source, archive)
        return dropped

    def archives(self) -> list[str]:
        """Which series this file holds a forecast for."""
        return [row[0] for row in self.conn.execute(
            "SELECT DISTINCT archive FROM run ORDER BY archive")]

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

    def sources(self, archive: str) -> list[str]:
        return [row[0] for row in self.conn.execute(
            "SELECT source FROM run WHERE archive = ? ORDER BY source",
            (archive,))]

    def run(self, archive: str, source: str) -> dict | None:
        """When this source last answered for this series, and with how much."""
        cursor = self.conn.execute(
            "SELECT source, issued, fetched, note, hours, days, warnings "
            "FROM run WHERE archive = ? AND source = ?", (archive, source))
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([d[0] for d in cursor.description], row, strict=True))

    def hours(self, archive: str, source: str = "", start: int = 0,
              stop: int = 0, limit: int = 0) -> list[Moment]:
        """The hourly forecast for one series, in time order."""
        rows = self._select("moment", HOUR_COLUMNS, archive, source,
                            start, stop, limit)
        return [Moment(dateTime=r["dateTime"], usUnits=r["usUnits"],
                       **{k: r[k] for k in HOUR_COLUMNS if r.get(k) is not None})
                for r in rows]

    def days(self, archive: str, source: str = "", start: int = 0,
             stop: int = 0, limit: int = 0) -> list[Day]:
        rows = self._select("day", DAY_COLUMNS, archive, source,
                            start, stop, limit)
        return [Day(dateTime=r["dateTime"], usUnits=r["usUnits"],
                    **{k: r[k] for k in DAY_COLUMNS if r.get(k) is not None})
                for r in rows]

    def warnings(self, archive: str, source: str = "", active_at: int = 0,
                 minimum: str = "") -> list[Warning]:
        """Warnings, most severe first.

        `active_at` keeps only what covers that instant. A warning that has
        not started yet is real and worth showing -- "storm tonight" is the
        point of a warning -- so the default shows everything stored, and a
        page that wants only what is happening now asks for it.
        """
        sql = ["SELECT source, " + ", ".join(WARNING_COLUMNS) + " FROM warning"]
        where, params = ["archive = ?"], [archive]
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

    def _select(self, table: str, columns: tuple[str, ...], archive: str,
                source: str, start: int, stop: int, limit: int) -> list[dict]:
        # `archive` is required and is never blank. `source` keeps its "empty
        # means every source" behaviour, because that is what one configured
        # source means and what the tag layer asks for -- but it is also the
        # door two sources' days already come through interleaved, one row per
        # source for the same calendar day. The same door for places would put
        # two places' forecasts on one page in date order, with nothing on the
        # page able to tell which was which.
        sql = [f"SELECT dateTime, usUnits, {', '.join(columns)} FROM {table}"]
        where, params = ["archive = ?"], [archive]
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

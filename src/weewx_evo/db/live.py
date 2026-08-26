"""The live table: every packet that ever arrived, kept for a while.

This is the store that replaces WeeWX's in-memory accumulator. A packet is
written here the moment it arrives and nothing else happens to it. Archive
records are worked out from this table afterwards, which is what makes them
reproducible: the same packets always yield the same record, whether they are
aggregated now, after a restart, or a week later because a calibration turned
out to be wrong.

It lives in its own database file. Its size and its retention then have nothing
to do with the archive, and it can be thrown away entirely without losing
history -- everything that mattered is already in `archive`.

Sizing, measured against the Kirchdorf console at one packet per 8 s:
roughly 11 MB per day, so about 80 MB at the default seven days. A Vantage at
one LOOP packet per 2 s is four times that.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS packet (
    seq       INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    dateTime  INTEGER NOT NULL,          -- when it was measured
    received  INTEGER NOT NULL,          -- when it reached us; the two differ for late packets
    source    TEXT    NOT NULL,          -- which driver or station sent it
    kind      TEXT    NOT NULL,          -- 'loop' or 'archive'
    usUnits   INTEGER NOT NULL,
    interval  REAL,                      -- set on 'archive' packets only
    digest    TEXT    NOT NULL,          -- of the payload, so a retry is not a second packet
    data      TEXT    NOT NULL,          -- JSON, the observations as they arrived
    -- The upload exactly as it came off the wire. Cleared after an hour by
    -- default: it is a debugging aid, not part of the measurement, and the
    -- parsed packet beside it is what everything downstream reads.
    raw       TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS packet_identity
    ON packet(source, kind, dateTime, digest);
CREATE INDEX IF NOT EXISTS packet_dateTime ON packet(dateTime);

-- Archive intervals waiting to be worked out. A packet arriving late puts its
-- interval back in here, which is the whole of the late-packet handling.
CREATE TABLE IF NOT EXISTS pending (
    stop    INTEGER NOT NULL PRIMARY KEY,   -- the interval ends here
    seconds INTEGER NOT NULL                -- and is this long
);

CREATE TABLE IF NOT EXISTS live_metadata (
    name  TEXT NOT NULL PRIMARY KEY,
    value TEXT
);
"""


def interval_stop(ts: float, seconds: int) -> int:
    """The end of the archive interval a timestamp belongs to.

    Intervals are half-open at the start, so a packet stamped exactly on a
    boundary closes the interval that ends there rather than opening the next.
    """
    return int(((int(ts) - 1) // seconds + 1) * seconds)


@dataclass(frozen=True, slots=True)
class Packet:
    """One reading as it arrived, before anything was done to it."""

    dateTime: int
    usUnits: int
    data: dict[str, Any]
    source: str = "unknown"
    kind: str = "loop"
    interval: float | None = None
    received: int | None = None
    #: The upload as it came off the wire, while it is still kept.
    #:
    #: This is what an issue about a new sensor needs. A parsed packet only
    #: shows what the driver already understood; the field it did not is
    #: precisely the one missing from it. Getting hold of a raw upload
    #: otherwise means reconfiguring the console and waiting for an interval.
    #:
    #: Kept for an hour, not for the retention period. Long enough to look at
    #: what just arrived, short enough that nobody has to think about the disk.
    raw: str | None = None

    def digest(self) -> str:
        """A short hash of the payload, so a retransmission is not a new packet."""
        canonical = json.dumps(self.data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def record(self) -> dict[str, Any]:
        """The packet as an observation record, ready for the accumulator."""
        rec = dict(self.data)
        rec["dateTime"] = self.dateTime
        rec["usUnits"] = self.usUnits
        if self.interval is not None:
            rec["interval"] = self.interval
        return rec


class LiveStore:
    """The live packet database."""

    def __init__(self, path: str | Path, interval_seconds: int = 300,
                 keep_raw_seconds: int = 3600) -> None:
        self.path = Path(path)
        self.interval_seconds = interval_seconds
        # How long the raw upload is kept beside the parsed packet. An hour is
        # plenty to look at what just arrived; keeping it for the whole
        # retention period would multiply the database for no further benefit.
        # 0 switches it off entirely.
        self.keep_raw_seconds = keep_raw_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # SQLite connections belong to the thread that made them, and the
        # listener answers each upload on its own thread. One connection per
        # thread, all onto the same file; WAL is what makes that safe.
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Bring a database made by an older version up to date.

        Only ever additive. This file is a cache with a few days in it, so a
        migration that went wrong would cost little -- but the packets that
        have not been archived yet are not replaceable, and the point of the
        live table is that nothing is lost.
        """
        have = {row[1] for row in self.conn.execute("PRAGMA table_info(packet)")}
        if "raw" not in have:
            self.conn.execute("ALTER TABLE packet ADD COLUMN raw TEXT")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=10.0)
        # WAL so a reader never blocks the listener. Writers are serialised by
        # SQLite itself, which is what lets several ingest processes share this
        # file without a broker in between.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        with self._lock:
            self._all.append(conn)
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        """This thread's connection, opened on first use."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        with self._lock:
            connections, self._all = self._all, []
        for conn in connections:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                # Belongs to a thread that has already gone. SQLite releases it
                # with the thread; there is nothing left to close.
                pass
        self._local = threading.local()

    def __enter__(self) -> LiveStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writing ---------------------------------------------------------

    def add(self, packet: Packet) -> bool:
        """Store one packet. Returns False if it was already there.

        Storing is idempotent on (source, kind, dateTime, payload). A console
        that retries an upload does not get counted twice; a genuinely
        different reading with the same timestamp still gets in.
        """
        received = packet.received if packet.received is not None else int(time.time())
        raw = packet.raw if self.keep_raw_seconds else None
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO packet"
            " (dateTime, received, source, kind, usUnits, interval, digest, data, raw)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (packet.dateTime, received, packet.source, packet.kind, packet.usUnits,
             packet.interval, packet.digest(),
             json.dumps(packet.data, sort_keys=True, separators=(",", ":")), raw),
        )
        if not cur.rowcount:
            return False
        self.mark_pending(packet.dateTime)
        return True

    def add_all(self, packets: Iterable[Packet]) -> int:
        """Store many packets in one transaction. Returns how many were new."""
        with self.conn:
            self.conn.execute("BEGIN")
            return sum(self.add(p) for p in packets)

    def mark_pending(self, ts: float, seconds: int | None = None) -> int:
        """Note that the interval containing `ts` needs working out."""
        seconds = seconds or self.interval_seconds
        stop = interval_stop(ts, seconds)
        self.conn.execute(
            "INSERT OR REPLACE INTO pending (stop, seconds) VALUES (?, ?)", (stop, seconds)
        )
        return stop

    def clear_pending(self, stop: int) -> None:
        self.conn.execute("DELETE FROM pending WHERE stop = ?", (stop,))

    # -- reading ---------------------------------------------------------

    def due(self, now: float | None = None, grace: int = 15) -> list[tuple[int, int]]:
        """Intervals that have ended and can be worked out, oldest first.

        `grace` holds an interval back for a few seconds after it closes, so a
        packet that is merely slow does not turn into a late packet and force a
        second computation.
        """
        now = now if now is not None else time.time()
        return [
            (stop, seconds)
            for stop, seconds in self.conn.execute(
                "SELECT stop, seconds FROM pending WHERE stop + ? <= ? ORDER BY stop",
                (grace, int(now)),
            )
        ]

    def packets(self, start: float, stop: float, kind: str | None = None,
                with_raw: bool = False) -> Iterator[Packet]:
        """Every packet in (start, stop], in time order.

        `with_raw` reads the original upload too. Off by default: the archiver
        walks thousands of packets and has no use for it, and the column is the
        largest one in the table.
        """
        columns = "dateTime, received, source, kind, usUnits, interval, data"
        if with_raw:
            columns += ", raw"
        sql = f"SELECT {columns} FROM packet WHERE dateTime > ? AND dateTime <= ?"
        params: list[Any] = [start, stop]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY dateTime, seq"
        for row in self.conn.execute(sql, params):
            ts, received, source, k, units, interval, data = row[:7]
            yield Packet(dateTime=ts, usUnits=units, data=json.loads(data),
                         source=source, kind=k, interval=interval, received=received,
                         raw=row[7] if with_raw else None)

    def forget_raw(self, before: float) -> int:
        """Drop the raw uploads of packets received before `before`.

        The packets themselves stay. Only the debugging copy goes, and it goes
        on arrival time rather than measurement time: a late packet was still
        looked at when it arrived, which is when anyone would want its body.
        """
        cur = self.conn.execute(
            "UPDATE packet SET raw = NULL WHERE raw IS NOT NULL AND received < ?",
            (int(before),))
        return cur.rowcount

    def raw_of(self, seq: int) -> tuple[Packet, str | None] | None:
        """One packet by its sequence number, with its raw upload if still held."""
        row = self.conn.execute(
            "SELECT dateTime, received, source, kind, usUnits, interval, data, raw"
            " FROM packet WHERE seq = ?", (seq,)).fetchone()
        if row is None:
            return None
        ts, received, source, kind, units, interval, data, raw = row
        return Packet(dateTime=ts, usUnits=units, data=json.loads(data), source=source,
                      kind=kind, interval=interval, received=received, raw=raw), raw

    def span(self) -> tuple[int | None, int | None]:
        return self.conn.execute("SELECT min(dateTime), max(dateTime) FROM packet").fetchone()

    def count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM packet").fetchone()[0]

    def get_meta(self, name: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM live_metadata WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else None

    def set_meta(self, name: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO live_metadata (name, value) VALUES (?, ?)", (name, value)
        )

    # -- retention -------------------------------------------------------

    def prune(self, before: float, archive_dir: str | Path | None = None) -> int:
        """Drop packets older than `before`, optionally writing them out first.

        With `archive_dir` set, each day leaving the table is written as
        gzipped NDJSON before it goes. Nothing is deleted until its file is
        closed and on disk, so an interrupted prune loses no packets -- it
        merely leaves a file to be overwritten next time.
        """
        before = int(before)
        if archive_dir is not None:
            self._spool(before, Path(archive_dir))
        cur = self.conn.execute("DELETE FROM packet WHERE dateTime < ?", (before,))
        self.conn.execute("PRAGMA incremental_vacuum")
        return cur.rowcount

    def _spool(self, before: int, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        days = [
            day for (day,) in self.conn.execute(
                "SELECT DISTINCT date(dateTime, 'unixepoch', 'localtime') FROM packet"
                " WHERE dateTime < ? ORDER BY 1", (before,)
            )
        ]
        for day in days:
            rows = self.conn.execute(
                "SELECT seq, dateTime, received, source, kind, usUnits, interval, data"
                " FROM packet"
                " WHERE dateTime < ? AND date(dateTime, 'unixepoch', 'localtime') = ?"
                " ORDER BY dateTime, seq", (before, day),
            ).fetchall()
            if not rows:
                continue
            target = out_dir / f"packets-{day}.ndjson.gz"
            partial = target.with_suffix(".gz.part")
            with gzip.open(partial, "wt", encoding="utf-8") as fp:
                for seq, ts, received, source, kind, units, interval, data in rows:
                    fp.write(json.dumps({
                        "seq": seq, "dateTime": ts, "received": received,
                        "source": source, "kind": kind, "usUnits": units,
                        "interval": interval, "data": json.loads(data),
                    }, separators=(",", ":")) + "\n")
            partial.replace(target)

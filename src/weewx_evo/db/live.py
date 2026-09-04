"""The live table: every reading that ever arrived, kept for a while.

This is the store that replaces WeeWX's in-memory accumulator. A packet is
written here the moment it arrives and nothing else happens to it. Archive
records are worked out from this table afterwards, which is what makes them
reproducible: the same packets always yield the same record, whether they are
aggregated now, after a restart, or a week later because a calibration turned
out to be wrong.

**It is a sensor journal, not a queue of finished packets.** `data` holds the
readings under the names the console sent them with, and `dialect` says which
vocabulary that is. Nothing here has been placed into an archive column yet,
and nothing has been left out: a field two drivers disagree about, one the
catalog has never heard of, one somebody has deliberately placed nowhere, an
indoor temperature nobody wants recorded -- they are all in this table. Which
of them reaches an archive, and under which column, is read out of
`placement.toml` when the record is built (see `placement.py`).

That is what makes a placement repairable. WeeWX cannot store this because it
has nowhere to put it: the driver hands a packet straight to the accumulator,
so the naming has to be finished before the packet exists. Here the naming is
a lookup on the way out, and a wrong one costs a `rebuild` rather than the
measurements.

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
import logging
import sqlite3
import threading
import time
import weakref
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote_to_bytes

log = logging.getLogger(__name__)

#: The archive a packet belongs to when nobody has said otherwise. Spelled out
#: here rather than imported from `stations`: this module imports nothing of
#: ours and is the better for it. The two constants are checked against each
#: other in the tests.
DEFAULT_ARCHIVE = "default"
#: Rows from the live-table shape that already held WeeWX column names. The
#: reserved driver keeps them selectable without pretending a real plugin
#: produced them.
LEGACY_DRIVER = "__legacy__"

#: A sender is what an archive selects.  Driver plus hardware identity was
#: already the real key; spelling it as one versioned value lets
#: ``archives.toml`` carry that key without teaching the archiver about the
#: listener's station file.  Percent encoding is reversible and avoids the
#: collision risk of shortening identities to a digest.
SENDER_ID_VERSION = "v1"


def sender_id(driver: str, identity: str) -> str:
    """The stable, reversible id for one driver/hardware-identity pair."""
    driver = str(driver or "unknown")
    # Station matching has always treated hardware identity case-insensitively
    # (some consoles change hexadecimal case between firmware versions).  Put
    # that rule in the canonical id itself so the same device cannot become
    # two archive members merely by changing letter case.
    identity = str(identity or "").casefold()
    return (f"{SENDER_ID_VERSION}/{quote(driver, safe='')}/"
            f"{quote(identity, safe='')}")


def sender_parts(value: str) -> tuple[str, str]:
    """Decode a canonical sender id, rejecting aliases and bad UTF-8."""
    try:
        version, encoded_driver, encoded_identity = str(value).split("/", 2)
        driver = unquote_to_bytes(encoded_driver).decode("utf-8", "strict")
        identity = unquote_to_bytes(encoded_identity).decode("utf-8", "strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{value!r} is not a sender id") from exc
    if version != SENDER_ID_VERSION or sender_id(driver, identity) != value:
        raise ValueError(f"{value!r} is not a canonical sender id")
    return driver, identity

SCHEMA = """
CREATE TABLE IF NOT EXISTS packet (
    seq       INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    dateTime  INTEGER NOT NULL,          -- when it was measured
    received  INTEGER NOT NULL,          -- when it reached us; the two differ for late packets
    -- Who sent it, as the pair that stays the same when somebody renames a
    -- station. The name is looked up when the packet is read, so a rename
    -- does not split a series in two and adopting a stranger reaches back
    -- over everything it has already sent.
    driver    TEXT    NOT NULL,          -- which plugin read it
    identity  TEXT    NOT NULL,          -- what the hardware calls itself; '' if it offers none
    -- The same pair as one canonical, versioned id. Archives select this
    -- value directly; they never open stations.toml or a driver registry.
    sender    TEXT    NOT NULL,
    -- Which vocabulary `data` is written in. NULL means the names are already
    -- WeeWX's, which is what the envelope promises and what every collector,
    -- the WeeWX shim and any driver somebody else wrote deliver.
    dialect   TEXT,
    -- The SHA-256 of a versioned, declarative description of that vocabulary
    -- in dialect_mapping. Driver code runs at the listener; the archiver
    -- executes only that JSON with core code. NULL is valid for WeeWX-named
    -- packets and marks an old or broken dialect packet as visibly
    -- untranslatable. A reference rather than 26 KB of repeated catalog per
    -- upload keeps the journal near its measured size.
    mapping   TEXT,
    kind      TEXT    NOT NULL,          -- 'loop' or 'archive'
    usUnits   INTEGER NOT NULL,
    interval  REAL,                      -- set on 'archive' packets only
    digest    TEXT    NOT NULL,          -- of the measurements, so a retry is not a second packet
    data      TEXT    NOT NULL,          -- JSON, the readings under the names they arrived with
    -- The upload exactly as it came off the wire. Cleared after an hour by
    -- default: it is what to look at when a driver could not parse something
    -- at all, and the readings beside it are what everything downstream reads.
    raw       TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS packet_identity
    ON packet(driver, identity, kind, dateTime, digest);
CREATE INDEX IF NOT EXISTS packet_dateTime ON packet(dateTime);
CREATE INDEX IF NOT EXISTS packet_station ON packet(driver, identity, dateTime);

-- A mapping is normally stable for the life of a console. Keep each JSON
-- document once, addressed by its full digest, rather than beside every
-- eight-second packet. A spool expands the reference again so the NDJSON is
-- self-contained.
CREATE TABLE IF NOT EXISTS dialect_mapping (
    digest TEXT NOT NULL PRIMARY KEY,
    spec   TEXT NOT NULL
);

-- The live database is the process boundary, including the directory of
-- senders it contains. `label` is listener/UI metadata only: archive
-- selection and member policy always use the canonical id.
CREATE TABLE IF NOT EXISTS sender_identity (
    sender   TEXT NOT NULL PRIMARY KEY,
    driver   TEXT NOT NULL,
    identity TEXT NOT NULL,
    label    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS sender_pair
    ON sender_identity(driver, identity COLLATE NOCASE);

-- Archive intervals waiting to be worked out. A packet arriving late puts its
-- interval back in here, which is the whole of the late-packet handling.
--
-- Keyed on the archive as well as the interval, because two archives are two
-- readers of this one table. With a single key the first archiver to finish
-- an interval cleared it, and the second never saw it at all -- a series that
-- silently stops at whichever site is quicker.
CREATE TABLE IF NOT EXISTS pending (
    stop    INTEGER NOT NULL,               -- the interval ends here
    seconds INTEGER NOT NULL,               -- and is this long
    archive TEXT    NOT NULL DEFAULT 'default',
    PRIMARY KEY (stop, archive)
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
    #: The readings, under whichever names `dialect` says. Not placed into
    #: archive columns: that is `placement.py`'s job and it happens on the way
    #: out.
    data: dict[str, Any]
    #: Which plugin read it. Stamped by the listener, because that is what
    #: knows the name this driver is registered under -- a driver that had to
    #: know its own name would be one more thing to keep in step.
    driver: str = "unknown"
    #: What the hardware calls itself: a PASSKEY, a serial, the `source` of an
    #: envelope. Empty when it offers none and one was handed out instead.
    identity: str = ""
    #: Canonical, versioned driver/identity key. The store computes it rather
    #: than trusting a plugin-supplied value; empty is accepted on an in-memory
    #: packet and means "derive it" for old callers.
    sender: str = ""
    #: The vocabulary `data` is written in, as `<protocol>/<dialect>`. None
    #: means the names are already WeeWX's.
    dialect: str | None = None
    #: The driver's declarative account of that vocabulary, as JSON values
    #: only. Kept beside the raw readings so an archiver never imports or
    #: calls the driver that accepted them.
    mapping: dict[str, Any] | None = None
    kind: str = "loop"
    interval: float | None = None
    received: int | None = None
    #: The upload as it came off the wire, while it is still kept.
    #:
    #: What this is for is a reading the driver did not parse *at all* -- the
    #: readings beside it show what it understood, so the one it did not is
    #: precisely what is missing from them. Getting hold of a raw upload
    #: otherwise means reconfiguring the console and waiting for an interval.
    #:
    #: Kept for an hour, not for the retention period. Long enough to look at
    #: what just arrived, short enough that nobody has to think about the disk.
    raw: str | None = None
    #: Names in `data` that say something about the console rather than about
    #: the weather: uptime, free heap, signal counters. Excluded from the
    #: digest, so a console retransmitting the same measurements a second
    #: later is still the same packet rather than a second one that gets
    #: accumulated twice.
    volatile: frozenset[str] = frozenset()
    #: Whose reading this is. The table has no column for it, on purpose: a
    #: name is a lookup that changes, and writing the answer down at arrival
    #: is what used to split a series in two when somebody renamed a console.
    #:
    #: A packet read back carries the identity it uploaded with, which is
    #: what an *unannounced* console has always been called. Anything holding
    #: the station register -- `placement.Placer.place` -- replaces that with
    #: the name somebody chose. Filled either way, so a reader with no
    #: register still knows whose reading it has rather than getting an empty
    #: string and quietly skipping every per-station rule.
    source: str = ""

    @property
    def sender_id(self) -> str:
        """This packet's canonical sender, including for old constructors."""
        return sender_id(self.driver, self.identity)

    def digest(self) -> str:
        """A short hash of the measurements, so a retransmission is not a new packet."""
        payload = ({name: value for name, value in self.data.items()
                    if name not in self.volatile}
                   if self.volatile else self.data)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def record(self) -> dict[str, Any]:
        """The packet as an observation record, ready for the accumulator."""
        rec = dict(self.data)
        rec["dateTime"] = self.dateTime
        rec["usUnits"] = self.usUnits
        if self.interval is not None:
            rec["interval"] = self.interval
        return rec


@dataclass(frozen=True, slots=True)
class SenderIdentity:
    """One sender known to the live journal, with optional display metadata."""

    sender: str
    driver: str
    identity: str
    label: str = ""


class _Held:
    """One thread's connection, held for exactly as long as that thread.

    `sqlite3.Connection` cannot be weakly referenced, so the store registers
    these instead. When a thread ends its locals go, this goes with them, and
    the store's weak set notices -- which is the whole point: the registry
    must be able to reach another thread's connection without keeping it
    alive.
    """

    __slots__ = ("__weakref__", "conn")

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


class LiveStore:
    """The live packet database."""

    def __init__(self, path: str | Path, interval_seconds: int = 300,
                 keep_raw_seconds: int = 3600) -> None:
        self.path = Path(path)
        self.interval_seconds = interval_seconds
        #: Every archive reading out of this table. The listener replaces the
        #: conventional initial name from the archive register; stations do
        #: not carry archive assignments.
        self.archives: list[str] = [DEFAULT_ARCHIVE]
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
        # Weakly, so a connection is free to die with the thread that made it.
        # Held strongly it could not, and this list is the only other place
        # one is named: every upload answered on its own thread left a file
        # descriptor behind for the life of the process. A console uploading
        # every eight seconds reached the 1024 limit in ten hours, and what
        # broke first was reading plots.toml -- nothing near the leak, and
        # nothing naming a database.
        self._all: weakref.WeakSet[_Held] = weakref.WeakSet()
        self._lock = threading.Lock()
        # Before the schema, not after it. `CREATE TABLE IF NOT EXISTS` is a
        # no-op against a table that is already there, so the *indexes* are
        # the first thing to touch the new columns -- and `CREATE INDEX ... ON
        # packet(driver, identity, dateTime)` against a table from before the
        # journal fails with "no such column: driver", which is a service that
        # will not start rather than one that migrates.
        self._retire_old_shape()
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _retire_old_shape(self) -> None:
        """Stage a packet table that predates the sensor journal for import.

        Its rows hold WeeWX names under a station name, and there is no way
        back to their raw hardware vocabulary. They are nevertheless honest
        passthrough packets: keeping the WeeWX names preserves an interval not
        archived before the upgrade. `_migrate_legacy_packets` copies them
        after the new table and its columns exist.

        Rename before `SCHEMA`: `CREATE TABLE IF NOT EXISTS` cannot add the
        journal columns to the old shape, and its indexes refer to columns the
        old table does not have. A crash after this rename is safe; the next
        opening sees `packet_pre_journal` and resumes the copy.
        """
        have = {row[1] for row in self.conn.execute("PRAGMA table_info(packet)")}
        if not have or "source" not in have:
            return
        staged = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table'"
            " AND name = 'packet_pre_journal'").fetchone()
        if staged:
            raise RuntimeError(
                f"{self.path}: both legacy packet tables exist; refusing to overwrite")
        self.conn.execute("ALTER TABLE packet RENAME TO packet_pre_journal")

    def _migrate(self) -> None:
        """Bring a database made by an older version up to date.

        Additive wherever it can be. This file is a cache with a few days in
        it, so a migration that went wrong would cost little -- but the packets
        that have not been archived yet are not replaceable, and the point of
        the live table is that nothing is lost.
        """
        have = {row[1] for row in self.conn.execute("PRAGMA table_info(packet)")}
        if have and "raw" not in have:
            self.conn.execute("ALTER TABLE packet ADD COLUMN raw TEXT")
        if have and "mapping" not in have:
            self.conn.execute("ALTER TABLE packet ADD COLUMN mapping TEXT")
        if have and "sender" not in have:
            # Filled and indexed below. SQLite cannot add a NOT NULL column
            # without inventing a default for all old rows, and an invented
            # sender is precisely what archive selection must not see.
            self.conn.execute("ALTER TABLE packet ADD COLUMN sender TEXT")

        self._migrate_legacy_packets()
        self._repair_senders()
        self._migrate_pending()

    def _migrate_legacy_packets(self) -> None:
        """Copy already-placed rows into the raw journal without losing one."""
        columns = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(packet_pre_journal)")}
        if not columns:
            return
        required = {"dateTime", "source", "kind", "usUnits", "data"}
        missing = required - columns
        if missing:
            raise RuntimeError(
                f"{self.path}: legacy packet table lacks {', '.join(sorted(missing))}")

        count, first, last = self.conn.execute(
            "SELECT count(*), min(dateTime), max(dateTime)"
            " FROM packet_pre_journal").fetchone()
        names = ["dateTime", "received", "driver", "identity", "sender",
                 "dialect", "mapping", "kind", "usUnits", "interval",
                 "digest", "data", "raw"]
        values = [
            "dateTime",
            "received" if "received" in columns else "dateTime",
            "?",
            "source",
            "''",  # backfilled from (__legacy__, source) before commit
            "NULL",
            "NULL",
            "kind",
            "usUnits",
            "interval" if "interval" in columns else "NULL",
            ("digest" if "digest" in columns else
             "lower(hex(randomblob(16)))"),
            "data",
            "raw" if "raw" in columns else "NULL",
        ]
        with self.conn:
            self.conn.execute("BEGIN")
            self.conn.execute(
                f"INSERT OR IGNORE INTO packet ({', '.join(names)})"
                f" SELECT {', '.join(values)} FROM packet_pre_journal",
                (LEGACY_DRIVER,))
            self.conn.execute("DROP TABLE packet_pre_journal")
            # The renamed table carried these index names with it, so
            # SCHEMA could not create them on the new table. Dropping it frees
            # the names; ensure every new index now exists on `packet`.
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS packet_identity"
                " ON packet(driver, identity, kind, dateTime, digest)")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS packet_dateTime ON packet(dateTime)")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS packet_station"
                " ON packet(driver, identity, dateTime)")
        log.warning(
            "%s: migrated %s already-placed live packet(s) as %s; span %s",
            self.path, count, LEGACY_DRIVER,
            f"{first} to {last}" if count else "empty")

    def _repair_senders(self) -> None:
        """Backfill the canonical packet key and its live-side directory."""
        rows = self.conn.execute(
            "SELECT DISTINCT driver, identity, sender FROM packet").fetchall()
        with self.conn:
            self.conn.execute("BEGIN")
            for driver, identity, stored in rows:
                canonical = sender_id(driver, identity)
                if stored != canonical:
                    self.conn.execute(
                        "UPDATE packet SET sender = ?"
                        " WHERE driver = ? AND identity = ?",
                        (canonical, driver, identity))
                label = identity if driver == LEGACY_DRIVER else None
                self.conn.execute(
                    "INSERT INTO sender_identity"
                    " (sender, driver, identity, label) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(sender) DO UPDATE SET"
                    " driver = excluded.driver, identity = excluded.identity,"
                    " label = COALESCE(sender_identity.label, excluded.label)",
                    (canonical, driver, identity, label))
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS packet_sender"
                " ON packet(sender, dateTime)")

    def _migrate_pending(self) -> None:
        """Give pending rows an archive, resuming safely after either rename."""
        pending = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(pending)")}
        staged = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(pending_one_archive)")}
        if not staged and (not pending or "archive" in pending):
            return
        if staged and not {"stop", "seconds"} <= staged:
            raise RuntimeError(f"{self.path}: staged pending table is not readable")

        with self.conn:
            self.conn.execute("BEGIN")
            if pending and "archive" not in pending:
                if staged:
                    raise RuntimeError(
                        f"{self.path}: two old pending tables exist; refusing to overwrite")
                self.conn.execute(
                    "ALTER TABLE pending RENAME TO pending_one_archive")
                staged = pending
                self.conn.execute("""
                    CREATE TABLE pending (
                        stop    INTEGER NOT NULL,
                        seconds INTEGER NOT NULL,
                        archive TEXT    NOT NULL DEFAULT 'default',
                        PRIMARY KEY (stop, archive)
                    )
                """)
            # After a crash immediately after RENAME, SCHEMA has already made
            # the new empty table. Merge rather than replacing: a listener may
            # have put new markers in it before this opener resumed migration.
            self.conn.execute(
                "INSERT OR IGNORE INTO pending (stop, seconds, archive)"
                " SELECT stop, seconds, ? FROM pending_one_archive",
                (DEFAULT_ARCHIVE,))
            self.conn.execute("DROP TABLE pending_one_archive")
        log.info("%s: the pending table now names an archive", self.path)

    def _connect(self) -> _Held:
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=10.0)
        # WAL so a reader never blocks the listener. Writers are serialised by
        # SQLite itself, which is what lets several ingest processes share this
        # file without a broker in between.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        held = _Held(conn)
        with self._lock:
            self._all.add(held)
        return held

    @property
    def conn(self) -> sqlite3.Connection:
        """This thread's connection, opened on first use."""
        held = getattr(self._local, "held", None)
        if held is None:
            held = self._connect()
            self._local.held = held
        return held.conn

    def close(self) -> None:
        with self._lock:
            held, self._all = list(self._all), weakref.WeakSet()
        for one in held:
            try:
                one.conn.close()
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

        Storing is idempotent on (driver, identity, kind, dateTime, payload). A
        console that retries an upload does not get counted twice; a genuinely
        different reading with the same timestamp still gets in.

        `packet.source` is not stored. A friendly label is metadata in
        ``sender_identity``; the immutable selection key is ``packet.sender``.
        """
        # The mapping row, packet row and pending marker are one fact. With
        # three autocommit statements, a concurrent prune could delete the
        # briefly unreferenced mapping between the first two and leave a raw
        # dialect packet that could never be interpreted again.
        if self.conn.in_transaction:
            return self._add(packet)
        with self.conn:
            self.conn.execute("BEGIN")
            return self._add(packet)

    def _add(self, packet: Packet) -> bool:
        """The write half of `add`, inside the caller's transaction."""
        received = packet.received if packet.received is not None else int(time.time())
        raw = packet.raw if self.keep_raw_seconds else None
        mapping = self._store_mapping(packet.mapping)
        sender = sender_id(packet.driver, packet.identity)
        self.conn.execute(
            "INSERT INTO sender_identity"
            " (sender, driver, identity, label) VALUES (?, ?, ?, NULL)"
            " ON CONFLICT(sender) DO UPDATE SET"
            " driver = excluded.driver, identity = excluded.identity",
            (sender, packet.driver, packet.identity))
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO packet"
            " (dateTime, received, driver, identity, sender, dialect, mapping, kind,"
            "  usUnits, interval, digest, data, raw)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (packet.dateTime, received, packet.driver, packet.identity, sender,
             packet.dialect, mapping,
             packet.kind, packet.usUnits, packet.interval, packet.digest(),
             json.dumps(packet.data, sort_keys=True, separators=(",", ":")), raw),
        )
        if not cur.rowcount:
            return False
        self.mark_pending(packet.dateTime)
        return True

    def _store_mapping(self, mapping: dict[str, Any] | None) -> str | None:
        """Store one inert dialect description and return its stable reference."""
        if mapping is None:
            return None
        canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        self.conn.execute(
            "INSERT OR IGNORE INTO dialect_mapping (digest, spec) VALUES (?, ?)",
            (digest, canonical))
        return digest

    @staticmethod
    def _mapping(reference: str | None, stored: str | None) -> dict[str, Any] | None:
        """Decode a referenced spec, accepting the short-lived inline shape too.

        Inline JSON was written during development before the catalog was
        normalised. It is harmless to keep accepting it, and it also makes an
        interrupted upgrade degrade as an old row rather than fail the whole
        interval.
        """
        encoded = stored
        if encoded is None and reference and reference.lstrip().startswith("{"):
            encoded = reference
        if encoded is None:
            return None
        if stored is not None and reference:
            actual = hashlib.sha256(stored.encode()).hexdigest()
            if actual != reference:
                # Treat a damaged or hand-edited catalog like a missing one.
                # The placer will report the affected driver/dialect once and
                # refuse to turn it into a plausible but false record.
                return None
        try:
            value = json.loads(encoded)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def add_all(self, packets: Iterable[Packet]) -> int:
        """Store many packets in one transaction. Returns how many were new."""
        with self.conn:
            self.conn.execute("BEGIN")
            return sum(self.add(p) for p in packets)

    def mark_pending(self, ts: float, seconds: int | None = None,
                     archives: Iterable[str] | None = None) -> int:
        """Note that the interval containing `ts` needs working out.

        Marked for every archive rather than only the one the packet belongs
        to. Working out which archive a source writes into means reading the
        station register from in here, and getting it wrong loses readings
        with no trace. The cost of the blunt version is one query per archive
        per interval that turns up empty, which is nothing; the cost of the
        clever version being wrong is a series with a hole in it.
        """
        seconds = seconds or self.interval_seconds
        stop = interval_stop(ts, seconds)
        for archive in (archives if archives is not None else self.archives):
            self.conn.execute(
                "INSERT OR REPLACE INTO pending (stop, seconds, archive)"
                " VALUES (?, ?, ?)", (stop, seconds, archive))
        return stop

    def clear_pending(self, stop: int, archive: str = DEFAULT_ARCHIVE) -> None:
        """One archive is done with this interval. The others are not."""
        self.conn.execute("DELETE FROM pending WHERE stop = ? AND archive = ?",
                          (stop, archive))

    # -- reading ---------------------------------------------------------

    def due(self, now: float | None = None, grace: int = 15,
            archive: str | None = None) -> list[tuple[int, int]]:
        """Intervals that have ended and can be worked out, oldest first.

        `grace` holds an interval back for a few seconds after it closes, so a
        packet that is merely slow does not turn into a late packet and force a
        second computation.

        `archive` is which series is asking. None means all of them, which is
        what `status` wants and no archiver does.
        """
        now = now if now is not None else time.time()
        sql = ("SELECT DISTINCT stop, seconds FROM pending"
               " WHERE stop + ? <= ?")
        args: list[Any] = [grace, int(now)]
        if archive is not None:
            sql += " AND archive = ?"
            args.append(archive)
        return [(stop, seconds)
                for stop, seconds in self.conn.execute(
                    sql + " ORDER BY stop", args)]

    def packets(self, start: float, stop: float, kind: str | None = None,
                with_raw: bool = False,
                stations: Iterable[tuple[str, str]] | None = None,
                senders: Iterable[str] | None = None) -> Iterator[Packet]:
        """Every packet in (start, stop], in time order.

        `with_raw` reads the original upload too. Off by default: the archiver
        walks thousands of packets and has no use for it, and the column is the
        largest one in the table.

        Args:
            senders (Iterable[str]|None): Canonical ids selected by this
                archive. None means its explicit ``senders = "*"``. An empty
                iterable means none. This is the archive-facing interface.
            stations: Compatibility interface for old non-service callers.
                The archive service never resolves or supplies station pairs.
        """
        if stations is not None and senders is not None:
            raise TypeError("choose senders or legacy station pairs, not both")
        columns = ("p.dateTime, p.received, p.driver, p.identity, p.sender, p.dialect, "
                   "p.mapping, m.spec, p.kind, p.usUnits, p.interval, p.data")
        if with_raw:
            columns += ", p.raw"
        sql = (f"SELECT {columns} FROM packet AS p "
               "LEFT JOIN dialect_mapping AS m ON m.digest = p.mapping "
               "WHERE p.dateTime > ? AND p.dateTime <= ?")
        params: list[Any] = [start, stop]
        if kind is not None:
            sql += " AND p.kind = ?"
            params.append(kind)
        if senders is not None:
            wanted_senders = [str(one) for one in senders]
            if not wanted_senders:
                return
            for canonical in wanted_senders:
                sender_parts(canonical)
            marks = ",".join("?" for _one in wanted_senders)
            sql += f" AND p.sender IN ({marks})"
            params.extend(wanted_senders)
        elif stations is not None:
            wanted = list(stations)
            if not wanted:
                # An archive with no stations takes nothing. Falling through
                # to "everything" here would be the opposite of the request.
                return
            marks = ",".join(["(?,?)"] * len(wanted))
            sql += f" AND (p.driver, p.identity) IN (VALUES {marks})"
            for driver, identity in wanted:
                params.extend((driver, identity))
        sql += " ORDER BY p.dateTime, p.seq"
        for row in self.conn.execute(sql, params):
            (ts, received, driver, identity, sender, dialect, mapping, described, k,
             units, interval, data) = row[:12]
            yield Packet(dateTime=ts, usUnits=units, data=json.loads(data),
                         driver=driver, identity=identity, sender=sender,
                         dialect=dialect,
                         mapping=self._mapping(mapping, described),
                         kind=k, interval=interval, received=received,
                         raw=row[12] if with_raw else None,
                         source=identity or driver)

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
            "SELECT p.dateTime, p.received, p.driver, p.identity, p.sender,"
            " p.dialect, p.mapping,"
            " m.spec, p.kind, p.usUnits, p.interval, p.data, p.raw FROM packet AS p"
            " LEFT JOIN dialect_mapping AS m ON m.digest = p.mapping WHERE p.seq = ?",
            (seq,)).fetchone()
        if row is None:
            return None
        (ts, received, driver, identity, sender, dialect, mapping, described, kind,
         units, interval, data, raw) = row
        return Packet(dateTime=ts, usUnits=units, data=json.loads(data), driver=driver,
                      identity=identity, sender=sender, dialect=dialect,
                      mapping=self._mapping(mapping, described),
                      kind=kind, interval=interval,
                      received=received, raw=raw, source=identity or driver), raw

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

    # -- sender directory ------------------------------------------------

    def senders(self) -> list[SenderIdentity]:
        """Every canonical sender observed here, with optional UI label."""
        return [SenderIdentity(
            sender=str(row[0]), driver=str(row[1]), identity=str(row[2]),
            label=str(row[3] or ""))
            for row in self.conn.execute(
                "SELECT sender, driver, identity, label FROM sender_identity"
                " ORDER BY COALESCE(label, ''), driver, identity")]

    def sync_sender_labels(self, stations: Iterable[Any]) -> None:
        """Replace listener-owned display labels without changing any id.

        The station file is a listener/UI concern. Copying only its friendly
        names into the live database gives a split archiver everything it may
        read, while archive selection remains the canonical sender id.
        """
        labels: list[tuple[str, str, str, str]] = []
        for station in stations:
            driver = str(station.driver)
            identity = str(station.identity)
            label = str(station.name)
            labels.append((sender_id(driver, identity), driver, identity, label))
        with self.conn:
            self.conn.execute("BEGIN")
            # Legacy labels describe the already-normalised rows themselves;
            # they are not a copy of stations.toml and survive this refresh.
            self.conn.execute(
                "UPDATE sender_identity SET label = NULL WHERE driver != ?",
                (LEGACY_DRIVER,))
            self.conn.executemany(
                "INSERT INTO sender_identity"
                " (sender, driver, identity, label) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(sender) DO UPDATE SET"
                " driver = excluded.driver, identity = excluded.identity,"
                " label = excluded.label",
                labels)

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
        self.conn.execute(
            "DELETE FROM dialect_mapping WHERE digest NOT IN "
            "(SELECT mapping FROM packet WHERE mapping IS NOT NULL)")
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
                "SELECT p.seq, p.dateTime, p.received, p.driver, p.identity, p.sender,"
                " p.dialect,"
                " p.mapping, m.spec, p.kind, p.usUnits, p.interval, p.data"
                " FROM packet AS p LEFT JOIN dialect_mapping AS m"
                " ON m.digest = p.mapping WHERE p.dateTime < ?"
                " AND date(p.dateTime, 'unixepoch', 'localtime') = ?"
                " ORDER BY p.dateTime, p.seq", (before, day),
            ).fetchall()
            if not rows:
                continue
            target = out_dir / f"packets-{day}.ndjson.gz"
            partial = target.with_suffix(".gz.part")
            with gzip.open(partial, "wt", encoding="utf-8") as fp:
                for (seq, ts, received, driver, identity, sender, dialect, mapping,
                     described, kind, units, interval, data) in rows:
                    fp.write(json.dumps({
                        "seq": seq, "dateTime": ts, "received": received,
                        "driver": driver, "identity": identity, "sender": sender,
                        "dialect": dialect,
                        "mapping": self._mapping(mapping, described),
                        "kind": kind, "usUnits": units,
                        "interval": interval, "data": json.loads(data),
                    }, separators=(",", ":")) + "\n")
            partial.replace(target)

"""Backup, integrity and housekeeping for a file holding fifteen years.

The one thing this project promises is that an existing WeeWX database stays
readable and writable. Everything else here is arranged around that -- and
until now there was no command to copy it, no way to ask whether it was still
sound, and nothing to reclaim the space a pruned column left behind.

## `cp` is the trap this exists for

An archive is opened in WAL mode, so at any moment part of it is in
`weewx.sdb-wal` and not in `weewx.sdb`. Copying the file alone takes a
database missing everything written since the last checkpoint; copying the
three files with `cp` takes them at three different instants, which is worse
because the result *opens*.

Both fail the same way: silently, and only when somebody restores.

`sqlite3.Connection.backup` is the answer, and it is in the standard library.
It copies pages under a read lock, retries the ones that changed underneath
it, and produces a file that is a database rather than a photograph of one.
It also works **while the archiver is writing**, which matters: the whole
point is a backup nobody has to stop the station for.

## Verifying is two questions, not one

    PRAGMA integrity_check    is the file sound?
    archive vs archive_day_*  do the summaries still follow from the records?

The second is ours and the more useful. `archive_day_*` is a cache; everything
in it is derivable from `archive`, and `rebuild_day` is the derivation. So a
day whose summary differs from a fresh computation is a day something went
wrong on, and it can be repaired -- which is not true of anything in `archive`
itself.

**Checked without writing.** `verify` computes and compares; `rebuild` is the
command that changes something. A check that repaired as it went would mean
nobody ever found out how often it was needed.

## What is not here

**No schedule.** These are commands. A backup that runs itself needs a
retention policy, a destination with room on it, and an answer to what happens
when the disk fills -- and getting that wrong quietly is worse than a person
remembering to type it. `schedule.py` is there for an installation that wants
one, and `docs/Maintenance.md` says how.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# `with sqlite3.connect(...)` commits the transaction and leaves the
# connection **open**. Every connection here is therefore wrapped in `closing`
# as well.
#
# On Windows the open handle stops the finished copy being renamed, which is
# how this was found. On Linux it is a leaked descriptor -- the exact fault
# that once took an instance down with 477 of them, three subsystems
# reporting errors and none of them anywhere near the leak.

#: How the copies are named. Sorts chronologically as text, which is what
#: makes `--keep` a matter of taking the last few.
STAMP = "%Y%m%d-%H%M%S"

#: Rows copied between progress callbacks. Small enough that a checkpoint
#: mid-copy retries little, large enough not to be the bottleneck.
PAGES = 2000


@dataclass
class Copied:
    """What one backup did."""

    path: Path | None = None
    bytes: int = 0
    seconds: float = 0.0
    pages: int = 0
    removed: list[Path] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.path is not None

    def summary(self) -> str:
        if self.error:
            return f"failed: {self.error}"
        return (f"{self.bytes / 1_048_576:.1f} MB in {self.seconds:.1f}s"
                + (f", {len(self.removed)} old one(s) removed"
                   if self.removed else ""))


@dataclass
class Verdict:
    """What a verification found."""

    file: Path
    sound: bool = True
    #: What `PRAGMA integrity_check` said, where it said anything but "ok".
    problems: list[str] = field(default_factory=list)
    #: Days whose summaries do not follow from the records, oldest first.
    days: list[int] = field(default_factory=list)
    checked_days: int = 0
    records: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.sound and not self.days

    def summary(self) -> str:
        parts = [f"{self.records} record(s)"]
        if self.checked_days:
            parts.append(f"{self.checked_days} day(s) checked")
        if not self.sound:
            parts.append(f"{len(self.problems)} integrity problem(s)")
        if self.days:
            parts.append(f"{len(self.days)} day(s) out of step")
        return ", ".join(parts)


# ---------------------------------------------------------------------------
# Backup.
# ---------------------------------------------------------------------------

def backup(source: str | Path, into: str | Path | None = None,
           keep: int = 7, name: str = "") -> Copied:
    """Copy a database safely, while it is being written to.

    `sqlite3.Connection.backup`, not a file copy. See the module docstring:
    the file on disk is not the database when WAL is on, and a copy of it
    opens perfectly and is missing everything since the last checkpoint.
    """
    source = Path(source)
    result = Copied()
    if not source.exists():
        result.error = f"there is no database at {source}"
        return result

    into = Path(into) if into else source.parent / "backups"
    into.mkdir(parents=True, exist_ok=True)
    stem = name or source.stem
    target = into / f"{stem}-{time.strftime(STAMP)}.sdb"

    started = time.monotonic()
    pages = 0

    def progress(_status: int, remaining: int, total: int) -> None:
        nonlocal pages
        pages = total - remaining

    # Written beside and renamed, so an interrupted run leaves a `.part` and
    # not a short database that looks like a backup.
    working = target.with_suffix(".part")
    try:
        with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as origin, \
                closing(sqlite3.connect(working)) as copy:
            origin.backup(copy, pages=PAGES, progress=progress)
            # Without this the copy carries its own WAL, and the file somebody
            # takes away is again not the whole database.
            copy.execute("PRAGMA journal_mode=DELETE")
            copy.commit()
    except sqlite3.Error as exc:
        _remove(working)
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    working.replace(target)
    result.path = target
    result.bytes = target.stat().st_size
    result.pages = pages
    result.seconds = time.monotonic() - started
    result.removed = prune_backups(into, stem, keep)
    return result


def prune_backups(into: Path, stem: str, keep: int) -> list[Path]:
    """Remove all but the newest `keep`. Zero keeps everything.

    By name, not by modification time: the name carries the moment the backup
    was *taken*, and a file copied to another disk keeps that while its
    timestamp becomes the moment it was copied.
    """
    if keep <= 0:
        return []
    found = sorted(into.glob(f"{stem}-*.sdb"))
    removed = []
    for path in found[:-keep] if len(found) > keep else []:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            log.warning("could not remove the old backup %s", path)
    return removed


def restorable(path: str | Path) -> str:
    """Open a backup and see whether it is one. Empty means it is.

    The check people skip, and the only one that matters: a backup nobody has
    opened is a hope. Cheap enough to run on every copy -- it reads the
    schema and counts, not the whole file.
    """
    path = Path(path)
    if not path.exists():
        return f"there is no file at {path}"
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            found = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                "AND name = 'archive'").fetchone()[0]
            if not found:
                return "it opens, but there is no archive table in it"
            count = conn.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
            if not count:
                return "it opens, and the archive table is empty"
    except sqlite3.Error as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


# ---------------------------------------------------------------------------
# Verify.
# ---------------------------------------------------------------------------

def verify(path: str | Path, days: int = 0, deep: bool = False) -> Verdict:
    """Ask whether the file is sound and whether the summaries still follow.

    `days` limits the second question to the most recent ones. Fifteen years
    is five and a half thousand rebuilds, and somebody checking after a crash
    wants an answer this afternoon.

    Nothing is written. `rebuild` is the command that changes something, and
    a check that repaired as it went would mean nobody found out how often it
    was needed.
    """
    path = Path(path)
    verdict = Verdict(file=path)
    started = time.monotonic()
    if not path.exists():
        verdict.sound = False
        verdict.problems = [f"there is no database at {path}"]
        return verdict

    # `quick_check` finds a corrupt page; `integrity_check` also walks every
    # index. The second is minutes on a large file, so it is asked for.
    pragma = "integrity_check" if deep else "quick_check"
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            said = [row[0] for row in conn.execute(f"PRAGMA {pragma}")]
            verdict.problems = [one for one in said if one != "ok"]
            verdict.sound = not verdict.problems
            verdict.records = conn.execute(
                "SELECT COUNT(*) FROM archive").fetchone()[0]
    except sqlite3.Error as exc:
        verdict.sound = False
        verdict.problems = [f"{type(exc).__name__}: {exc}"]
        return verdict

    if not verdict.sound:
        # No point comparing summaries in a file SQLite has already called
        # damaged: every difference would be a symptom of the same thing.
        verdict.seconds = time.monotonic() - started
        return verdict

    # The summaries, against a fresh computation. On a copy, because
    # `rebuild_day` writes -- and this command promises not to.
    working = path.with_suffix(path.suffix + ".verify")
    try:
        copy = backup(path, into=working.parent, keep=0,
                      name=working.name)
        if not copy.ok or copy.path is None:
            verdict.problems.append(f"could not take a copy: {copy.error}")
            verdict.sound = False
            return verdict
        verdict.days = _days_out_of_step(copy.path, days)
        verdict.checked_days = _day_count(copy.path, days)
    finally:
        if copy.path is not None:
            _remove(copy.path)

    verdict.seconds = time.monotonic() - started
    return verdict


def _remove(path: Path) -> None:
    """A database and the two files that belong to it.

    Opening one in WAL mode leaves `-wal` and `-shm` beside it, and deleting
    only the database leaves those in the archive directory for ever --
    named after a working copy nobody can explain a week later.
    """
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def _day_starts(conn: sqlite3.Connection, limit: int = 0) -> list[int]:
    """Every day the summaries hold, newest first where limited."""
    rows = conn.execute(
        "SELECT DISTINCT dateTime FROM archive_day_outTemp ORDER BY dateTime "
        + ("DESC" if limit else "ASC") + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()
    return sorted(int(row[0]) for row in rows)


def _day_count(path: Path, limit: int = 0) -> int:
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            return len(_day_starts(conn, limit))
    except sqlite3.Error:
        return 0


def _days_out_of_step(path: Path, limit: int = 0) -> list[int]:
    """Days whose stored summaries differ from a fresh computation.

    Compared field by field on the numbers that matter -- the count, the sum,
    the extremes -- rather than on the whole row: `wsum` and `sumtime` are
    floating point and a rebuild of the same records can differ in the last
    bit without meaning anything.
    """
    from .db.archive import ArchiveStore

    out: list[int] = []
    store = ArchiveStore(path)
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro",
                                     uri=True)) as reader:
            days = _day_starts(reader, limit)
        for start in days:
            before = _day_rows(store.conn, start)
            store.rebuild_day(start)
            after = _day_rows(store.conn, start)
            if _differs(before, after):
                out.append(start)
    except sqlite3.Error as exc:
        log.warning("could not compare the daily summaries: %s", exc)
    finally:
        store.close()
    return out


#: What is compared, and how.
#:
#: Not `wsum` or `sumtime`: both are floating point, and a rebuild of
#: identical records can differ in the last bit without anything being wrong.
#:
#: And the extremes are compared **one-sidedly**, which is the whole
#: difficulty. A stored minimum *below* what the archive records produce is
#: normal and right: the daily summaries take their highs and lows from LOOP
#: packets, so a gust between two archive records is in the summary and
#: nowhere else. `difftest.py` counts 189 of those on the reference database
#: and calls them expected.
#:
#: Comparing them for equality therefore reports every day of every healthy
#: installation, which is the same as reporting nothing. What is a real fault
#: is the other direction: a summary *duller* than the records it is supposed
#: to summarise means a record that never reached it.
EXACT = ("count", "sum")
AT_LEAST = ("max",)      # stored must be >= rebuilt
AT_MOST = ("min",)       # stored must be <= rebuilt
COMPARED = EXACT + AT_LEAST + AT_MOST


def _day_rows(conn: sqlite3.Connection, start: int) -> dict[str, dict]:
    """One day of every summary table, as comparable numbers."""
    found: dict[str, dict] = {}
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name LIKE 'archive_day_%' AND name NOT LIKE '%__metadata'")]
    for table in tables:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        wanted = [one for one in COMPARED if one in columns]
        if not wanted:
            continue
        row = conn.execute(
            f"SELECT {', '.join(wanted)} FROM {table} WHERE dateTime = ?",
            (start,)).fetchone()
        if row is not None:
            found[table] = {
                name: (round(value, 6) if isinstance(value, float) else value)
                for name, value in zip(wanted, row, strict=True)}
    return found


def _differs(stored: dict[str, dict], rebuilt: dict[str, dict]) -> bool:
    """Whether the stored summaries fail to follow from the records.

    One-sided on the extremes. See `COMPARED`: a summary sharper than the
    records is what LOOP highs and lows are for, and calling that a fault
    would flag every day of every healthy installation.
    """
    # A row the rebuild *adds* with nothing in it is not a finding. Our
    # rebuild primes every reading the schema knows, so a day WeeWX left out
    # of `archive_day_eventRain` entirely comes back with an empty row --
    # `roundtrip.py` counts 266 of those and calls them expected. Treating
    # them as damage would report every day of every adopted database.
    added = {table for table in set(rebuilt) - set(stored)
             if not rebuilt[table].get("count")}
    if sorted(set(stored)) != sorted(set(rebuilt) - added):
        # A row that has *gone* is the other direction, and is real: a
        # reading that was summarised and no longer is.
        return True
    for table, mine in stored.items():
        theirs = rebuilt[table]
        for name in EXACT:
            if name in mine and mine[name] != theirs.get(name):
                return True
        for name in AT_LEAST:
            a, b = mine.get(name), theirs.get(name)
            if a is not None and b is not None and a < b:
                return True
        for name in AT_MOST:
            a, b = mine.get(name), theirs.get(name)
            if a is not None and b is not None and a > b:
                return True
    return False


# ---------------------------------------------------------------------------
# Housekeeping.
# ---------------------------------------------------------------------------

def vacuum(path: str | Path) -> tuple[int, int]:
    """Rewrite the file without its free pages. Returns (before, after).

    Worth doing after a column is dropped or a long span deleted, and not
    otherwise: it rewrites the whole database and needs room for a second
    copy while it does.
    """
    path = Path(path)
    before = path.stat().st_size if path.exists() else 0
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("VACUUM")
    return before, path.stat().st_size if path.exists() else 0


def checkpoint(path: str | Path) -> int:
    """Fold the write-ahead log back into the database. Returns pages moved.

    What makes the file on disk *be* the database again. Useful before
    copying one by hand, and the reason `backup` does not need it.
    """
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    return int(row[1]) if row and len(row) > 1 else 0


def space(path: str | Path) -> dict[str, int]:
    """What the file costs, and what a vacuum would give back."""
    path = Path(path)
    out = {"bytes": path.stat().st_size if path.exists() else 0,
           "free": 0, "wal": 0}
    for suffix in ("-wal", "-shm"):
        beside = Path(str(path) + suffix)
        if beside.exists():
            out["wal"] += beside.stat().st_size
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro",
                                     uri=True)) as conn:
            size = conn.execute("PRAGMA page_size").fetchone()[0]
            free = conn.execute("PRAGMA freelist_count").fetchone()[0]
            out["free"] = int(size) * int(free)
    except sqlite3.Error:
        pass
    return out


def disk_free(path: str | Path) -> int:
    """Room where the backups go. A backup that fills the disk is worse than
    none: it takes the station down with it."""
    try:
        return shutil.disk_usage(Path(path)).free
    except OSError:
        return 0


def enough_room(source: str | Path, into: str | Path) -> str:
    """Whether a backup will fit. Empty means it will.

    Asked before rather than found out during. A copy that runs out of space
    leaves a partial file and, on a station whose archive shares a disk with
    its database, can stop the archiver writing.
    """
    source, into = Path(source), Path(into)
    if not source.exists():
        return ""
    needed = source.stat().st_size
    free = disk_free(into if into.exists() else into.parent)
    if free and free < needed * 1.1:
        return (f"{free / 1_048_576:.0f} MB free where the backups go and the "
                f"database is {needed / 1_048_576:.0f} MB")
    return ""


def owner_readable_only(path: str | Path) -> None:
    """A backup holds everything the database holds. Same rule as the
    datasource file the Grafana provisioning writes."""
    try:
        os.chmod(Path(path), 0o600)
    except OSError:  # pragma: no cover - Windows, and not a failure
        pass

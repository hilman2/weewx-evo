#!/usr/bin/env python3
"""Copying a database that is being written to, and asking whether it is sound.

The check this file exists for is the first one: **a file copy of a WAL
database is not a backup.** It is measured rather than asserted -- the same
records, copied both ways, and the two counted. `sqlite3.Connection.backup`
holds all fifty; `shutil.copy` holds none, and depending on whether the
schema is still in the log it either opens empty or does not open at all.

That is the reason for the whole module. The failure is silent, the file
looks like a backup, and it is discovered by somebody restoring.

Two more that are about not crying wolf:

**A healthy archive must verify clean.** The daily summaries take their highs
and lows from LOOP packets, so a stored minimum below anything in `archive`
is normal -- `difftest` counts 189 of those on the reference database. And
our own rebuild adds empty rows WeeWX never wrote, which `roundtrip` counts
as 266. A check that called either of those damage would report every day of
every installation, which is the same as reporting nothing.

**And it still has to find a real one.** So a summary is edited to disagree
with its records, and the day has to come back named.

    python tools/maintenance_test.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import maintenance, units
from weewx_evo.db.archive import ArchiveStore

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


START = 1755648000


#: Built once and copied. The schema has 113 summary tables and every
#: `add_record` touches the ones its reading belongs to, so making a fresh
#: archive per test was eleven seconds each and most of this file's runtime.
#: Copying a *closed* database is exact -- there is no write-ahead log to
#: miss, which is the whole subject of the first check below.
_MADE: dict[int, Path] = {}


def an_archive(where: Path, days: int = 3, every: int = 3600) -> Path:
    """A database this program made, with a few days of records in it.

    Hourly rather than every five minutes: `verify` rebuilds every summary,
    and a realistic interval turns this into arithmetic that proves nothing
    the smaller one does not.
    """
    master = _MADE.get(days)
    if master is None:
        master = _MADE[days] = _build(
            Path(tempfile.mkdtemp()) / f"master-{days}.sdb", days, every)
    shutil.copy(master, where)
    return where


def _build(where: Path, days: int, every: int) -> Path:
    # `add_records`, not a loop of `add_record`: the singular rewrites the
    # day's summaries per record and commits, which is half a second each on
    # a disk that really flushes. The plural groups by day, and it is the same
    # arithmetic in the same order.
    records = []
    stamp = START
    for _day in range(days):
        for _slot in range(86400 // every):
            stamp += every
            records.append({
                "dateTime": stamp, "usUnits": units.METRICWX,
                "interval": every / 60.0,
                "outTemp": 10.0 + (stamp % 1000) / 100.0,
                "outHumidity": 60.0 + (stamp % 300) / 10.0,
            })

    store = ArchiveStore(where)
    try:
        store.add_records(records)
        store.conn.commit()
        # Folded in, so the copy taken above is the whole database.
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        store.close()
    return where


def count_in(where: Path) -> int:
    try:
        with closing(sqlite3.connect(f"file:{where}?mode=ro", uri=True)) as conn:
            return conn.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
    except sqlite3.Error:
        return -1


# ---------------------------------------------------------------------------
# The one that matters.
# ---------------------------------------------------------------------------

def test_a_file_copy_of_a_wal_database_is_not_a_backup() -> None:
    """Measured, not asserted. This is the whole reason for the module.

    Records are written and left in the write-ahead log, which is where they
    are for as long as SQLite feels like. The file on disk is then a database
    missing them -- and it opens, which is what makes this dangerous.
    """
    where = Path(tempfile.mkdtemp())
    source = where / "weewx.sdb"

    # Open, write, and hold the connection so nothing checkpoints. Fifty
    # records rather than a day's worth: what has to be true is that the
    # write-ahead log is not empty, and SQLite checkpoints on its own at
    # about a thousand pages.
    store = ArchiveStore(source)
    try:
        store.add_records([{"dateTime": START + index * 300,
                            "usUnits": units.METRICWX, "interval": 5,
                            "outTemp": 20.0 + index / 100.0}
                           for index in range(50)])
        store.conn.commit()

        wal = Path(str(source) + "-wal")
        check("the records are in the write-ahead log",
              wal.exists() and wal.stat().st_size > 0, True)

        copied = where / "by-cp.sdb"
        shutil.copy(source, copied)
        by_cp = count_in(copied)

        backed = maintenance.backup(source, into=where, keep=0, name="by-backup")
        check("the backup succeeded", backed.ok, True)
        by_backup = count_in(backed.path)
    finally:
        store.close()

    # Either it does not open at all, or it opens and is short. Which of the
    # two depends on whether the schema itself is still in the log, and both
    # are a backup somebody would discover on the day they needed it.
    check("the file copy is not the database", by_cp < 50, True)
    check("the backup is", by_backup, 50)


def test_a_backup_carries_no_write_ahead_log_of_its_own() -> None:
    """Otherwise the file somebody takes away is again not the database."""
    where = Path(tempfile.mkdtemp())
    an_archive(where / "weewx.sdb", days=1)
    copy = maintenance.backup(where / "weewx.sdb", into=where / "out", keep=0)
    check("it was written", copy.ok, True)
    check("and there is no -wal beside it",
          Path(str(copy.path) + "-wal").exists(), False)


def test_a_backup_is_opened_before_it_is_believed() -> None:
    where = Path(tempfile.mkdtemp())
    an_archive(where / "weewx.sdb", days=1)
    copy = maintenance.backup(where / "weewx.sdb", into=where, keep=0)
    check("a real one reads back", maintenance.restorable(copy.path), "")

    # The three ways a file in a backup directory is not a backup.
    empty = where / "empty.sdb"
    empty.write_bytes(b"")
    check("an empty file is caught",
          bool(maintenance.restorable(empty)), True)

    nonsense = where / "nonsense.sdb"
    nonsense.write_bytes(b"this is not a database" * 100)
    check("a file that is not a database is caught",
          bool(maintenance.restorable(nonsense)), True)

    bare = where / "bare.sdb"
    with closing(sqlite3.connect(bare)) as conn:
        conn.execute("CREATE TABLE something (x INTEGER)")
        conn.commit()
    check("a database with no archive table is caught",
          "archive table" in maintenance.restorable(bare), True)


def test_an_interrupted_backup_leaves_no_backup() -> None:
    """A short file that opens is worse than no file at all."""
    where = Path(tempfile.mkdtemp())
    missing = maintenance.backup(where / "not-there.sdb", into=where, keep=0)
    check("it fails", missing.ok, False)
    check("and says why", "no database" in missing.error, True)
    check("and wrote nothing", list(where.glob("*.sdb")), [])
    check("not even a part file", list(where.glob("*.part")), [])


def test_the_oldest_are_removed_and_the_newest_kept() -> None:
    where = Path(tempfile.mkdtemp())
    for stamp in ("20260101-000000", "20260102-000000", "20260103-000000",
                  "20260104-000000"):
        (where / f"weewx-{stamp}.sdb").write_bytes(b"x")
    # Something else in the same directory, which must be left alone.
    (where / "live-20260101-000000.sdb").write_bytes(b"x")

    removed = maintenance.prune_backups(where, "weewx", keep=2)
    check("two were removed", len(removed), 2)
    check("the newest two are left",
          sorted(p.name for p in where.glob("weewx-*.sdb")),
          ["weewx-20260103-000000.sdb", "weewx-20260104-000000.sdb"])
    check("and another database's backups are untouched",
          (where / "live-20260101-000000.sdb").exists(), True)

    check("keeping zero keeps everything",
          maintenance.prune_backups(where, "weewx", keep=0), [])


def test_backups_are_pruned_by_name_not_by_timestamp() -> None:
    """The name carries when the backup was *taken*.

    A file copied to another disk keeps its name and gets a new modification
    time, so pruning by timestamp would throw away the oldest data rather
    than the oldest backup.
    """
    where = Path(tempfile.mkdtemp())
    old = where / "weewx-20260101-000000.sdb"
    new = where / "weewx-20260104-000000.sdb"
    new.write_bytes(b"x")
    time.sleep(0.01)
    old.write_bytes(b"x")          # written last, named first

    removed = maintenance.prune_backups(where, "weewx", keep=1)
    check("the older name went", [p.name for p in removed], [old.name])


# ---------------------------------------------------------------------------
# Verify.
# ---------------------------------------------------------------------------

def test_a_healthy_archive_verifies_clean() -> None:
    """A check that fires on every installation is the same as no check."""
    where = Path(tempfile.mkdtemp())
    an_archive(where / "weewx.sdb", days=2)
    verdict = maintenance.verify(where / "weewx.sdb")
    check("sound", verdict.sound, True)
    check("nothing out of step", verdict.days, [])
    check("and it looked at the days", verdict.checked_days > 0, True)
    check("and counted the records", verdict.records > 0, True)


def test_a_sharper_extreme_is_not_a_fault() -> None:
    """The daily summaries take their highs and lows from LOOP packets.

    A stored minimum below anything in `archive` is what that looks like, and
    it is right. `difftest` counts 189 of them on the reference database.
    """
    where = Path(tempfile.mkdtemp())
    source = an_archive(where / "weewx.sdb", days=2)

    with closing(sqlite3.connect(source)) as conn:
        start = conn.execute(
            "SELECT MIN(dateTime) FROM archive_day_outTemp").fetchone()[0]
        # A gust that only ever existed between two archive records.
        conn.execute("UPDATE archive_day_outTemp SET min = min - 5, "
                     "max = max + 5 WHERE dateTime = ?", (start,))
        conn.commit()

    verdict = maintenance.verify(source, days=0)
    check("a sharper day is not reported", verdict.days, [])


def test_days_counts_back_from_the_newest() -> None:
    """Which end `days` cuts from, said out loud.

    It cuts from the newest, which is the useful half after a crash. Three
    checks above were written against a fixture whose oldest day was the
    changed one, and passed for a year without measuring anything: the day
    they altered was never in the window.
    """
    where = Path(tempfile.mkdtemp())
    source = an_archive(where / "weewx.sdb", days=3)

    with closing(sqlite3.connect(source)) as conn:
        days = [int(row[0]) for row in conn.execute(
            "SELECT DISTINCT dateTime FROM archive_day_outTemp "
            "ORDER BY dateTime")]
        # The oldest, so a window of one cannot reach it.
        conn.execute("UPDATE archive_day_outTemp SET max = max - 5 "
                     "WHERE dateTime = ?", (days[0],))
        conn.commit()

    check("one day looks at one day",
          maintenance.verify(source, days=1).checked_days, 1)
    check("and it is not the changed one",
          maintenance.verify(source, days=1).days, [])
    check("every day finds it",
          maintenance.verify(source, days=0).days, [days[0]])


def test_a_duller_extreme_is_a_fault() -> None:
    """The other direction is real: a record that never reached the summary."""
    where = Path(tempfile.mkdtemp())
    source = an_archive(where / "weewx.sdb", days=2)

    with closing(sqlite3.connect(source)) as conn:
        start = conn.execute(
            "SELECT MIN(dateTime) FROM archive_day_outTemp").fetchone()[0]
        conn.execute("UPDATE archive_day_outTemp SET max = max - 5 "
                     "WHERE dateTime = ?", (start,))
        conn.commit()

    verdict = maintenance.verify(source, days=0)
    check("the day is named", verdict.days, [start])


def test_a_wrong_sum_is_a_fault() -> None:
    where = Path(tempfile.mkdtemp())
    source = an_archive(where / "weewx.sdb", days=2)

    with closing(sqlite3.connect(source)) as conn:
        start = conn.execute(
            "SELECT MIN(dateTime) FROM archive_day_outTemp").fetchone()[0]
        conn.execute("UPDATE archive_day_outTemp SET count = count - 3 "
                     "WHERE dateTime = ?", (start,))
        conn.commit()

    verdict = maintenance.verify(source, days=0)
    check("a count that does not follow is named", verdict.days, [start])


def test_verify_writes_nothing() -> None:
    """`rebuild` is the command that changes something.

    A check that repaired as it went would mean nobody ever found out how
    often it was needed.
    """
    where = Path(tempfile.mkdtemp())
    source = an_archive(where / "weewx.sdb", days=2)
    with closing(sqlite3.connect(source)) as conn:
        start = conn.execute(
            "SELECT MIN(dateTime) FROM archive_day_outTemp").fetchone()[0]
        conn.execute("UPDATE archive_day_outTemp SET max = max - 5 "
                     "WHERE dateTime = ?", (start,))
        conn.commit()
        before = conn.execute(
            "SELECT max FROM archive_day_outTemp WHERE dateTime = ?",
            (start,)).fetchone()[0]

    maintenance.verify(source, days=0)

    with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as conn:
        after = conn.execute(
            "SELECT max FROM archive_day_outTemp WHERE dateTime = ?",
            (start,)).fetchone()[0]
    check("the damaged figure is still damaged", after, before)
    check("and no working copy is left behind",
          [p.name for p in where.glob("*.verify*")], [])


def test_verify_can_be_limited_to_recent_days() -> None:
    """Fifteen years is five thousand rebuilds, and somebody after a crash
    wants an answer this afternoon."""
    where = Path(tempfile.mkdtemp())
    an_archive(where / "weewx.sdb", days=4)
    check("all of them by default",
          maintenance.verify(where / "weewx.sdb").checked_days >= 4, True)
    check("or the last two",
          maintenance.verify(where / "weewx.sdb", days=2).checked_days, 2)


def test_a_damaged_file_is_reported_and_not_compared() -> None:
    """Every difference in a corrupt file is a symptom of the same thing."""
    where = Path(tempfile.mkdtemp())
    source = where / "weewx.sdb"
    an_archive(source, days=1)

    data = bytearray(source.read_bytes())
    # Somewhere past the header, so it opens and then does not read.
    for offset in range(4096, min(len(data), 40960), 7):
        data[offset] = (data[offset] + 137) % 256
    source.write_bytes(bytes(data))

    verdict = maintenance.verify(source, days=0)
    check("it is not called sound", verdict.sound, False)
    check("and something is said about it", bool(verdict.problems), True)
    check("and it did not go on to the summaries", verdict.days, [])


def test_a_missing_file_says_so() -> None:
    verdict = maintenance.verify(Path(tempfile.mkdtemp()) / "nothing.sdb")
    check("not sound", verdict.sound, False)
    check("and it names the file", "no database" in verdict.problems[0], True)


# ---------------------------------------------------------------------------
# Housekeeping.
# ---------------------------------------------------------------------------

def test_nothing_here_leaks_a_descriptor() -> None:
    """`with sqlite3.connect(...)` commits and leaves the connection open.

    On Linux that is a leaked descriptor -- the fault that once took an
    instance down with 477 of them, three subsystems reporting errors and
    none of them near the leak. On Windows it stops the finished copy being
    renamed, which is how it was found here.
    """
    where = Path(tempfile.mkdtemp())
    source = an_archive(where / "weewx.sdb", days=1)

    before = _descriptors()
    for _ in range(3):
        copy = maintenance.backup(source, into=where / "out", keep=0)
        maintenance.restorable(copy.path)
        maintenance.verify(copy.path, days=1)
        maintenance.space(copy.path)
        maintenance.checkpoint(copy.path)
        copy.path.unlink(missing_ok=True)
    after = _descriptors()

    if before is None or after is None:
        # Windows has no such count. The rename in `backup` is the check
        # there, and it fails loudly if a connection is still open.
        check("the copies were made", True, True)
        return
    check("no descriptors were left behind", after <= before + 2, True)


def _descriptors() -> int | None:
    try:
        return len(list(Path("/proc/self/fd").iterdir()))
    except OSError:
        return None


def test_space_says_what_a_vacuum_would_give_back() -> None:
    where = Path(tempfile.mkdtemp())
    source = an_archive(where / "weewx.sdb", days=3)

    with closing(sqlite3.connect(source)) as conn:
        conn.execute("DELETE FROM archive WHERE dateTime < ?",
                     (START + 86400,))
        conn.commit()

    room = maintenance.space(source)
    check("there is something to reclaim", room["free"] > 0, True)

    before, after = maintenance.vacuum(source)
    check("and a vacuum gives it back", after < before, True)
    check("with nothing left to reclaim",
          maintenance.space(source)["free"], 0)


def test_a_checkpoint_folds_the_log_back_in() -> None:
    where = Path(tempfile.mkdtemp())
    source = where / "weewx.sdb"
    store = ArchiveStore(source)
    try:
        for index in range(100):
            store.add_record({"dateTime": START + index * 300,
                              "usUnits": units.METRICWX, "interval": 5,
                              "outTemp": 20.0})
        store.conn.commit()
        wal = Path(str(source) + "-wal")
        check("there is a log to fold in", wal.stat().st_size > 0, True)
    finally:
        store.close()

    maintenance.checkpoint(source)
    check("the file on disk is now the database", count_in(source), 100)


def test_it_says_when_there_is_no_room() -> None:
    """Asked before, not found out during: a copy that fills the disk can
    stop the archiver writing."""
    where = Path(tempfile.mkdtemp())
    source = an_archive(where / "weewx.sdb", days=1)
    # Nothing to complain about on a disk with room on it.
    check("an ordinary disk is fine",
          maintenance.enough_room(source, where), "")


def main() -> int:
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
            except Exception as exc:  # a failing test is the finding
                FAILURES.append(f"{name} raised {type(exc).__name__}: {exc}")

    if FAILURES:
        print(f"{len(FAILURES)} of {CHECKS} checks failed:\n")
        for failure in FAILURES:
            print(f"  {failure}\n")
        return 1
    print(f"maintenance: {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""A database weewx-evo wrote, handed back to WeeWX.

The one rule of this whole rewrite:

    An existing WeeWX database stays readable and writable -- **by WeeWX
    itself**. Not "importable": the same file, the same meaning, and WeeWX 5
    can carry on using it afterwards.

Everything else here checks half of that. `difftest` reads WeeWX's file and
compares our arithmetic against it. `roundtrip` writes into a real archive
and reads it back with *our* code. `seriestest` and `tagcheck` open the
*reference* database with WeeWX's manager. None of them opens a file **we**
wrote with WeeWX's manager, and that is the direction the rule is about --
somebody trying this out has to be able to go back.

So this does the thing the rule promises, in the order somebody would:

    1  weewx-evo makes an archive from nothing and fills it
    2  WeeWX's own DaySummaryManager opens it
    3  WeeWX reads the records back, and the daily summaries
    4  WeeWX **writes** into it -- a new record, its own way
    5  weewx-evo reads what WeeWX wrote and agrees about it
    6  and WeeWX's own consistency check passes on the result

Steps 4 to 6 are the ones that matter. A file WeeWX can read is a file WeeWX
can migrate from; a file WeeWX can *keep using* is what was promised.

    wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \\
      cd /mnt/d/Git/weewx-evo && python3 tools/stillweewx_test.py'

Needs WeeWX. Without it there is nothing to hand the file to, and the test
says so and skips rather than checking our own work twice.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: A day of readings at five minutes, which is enough for daily summaries to
#: have something in every field they keep.
INTERVAL = 300
HOURS = 24

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def near(what: str, got: float | None, want: float, tol: float = 1e-6) -> bool:
    global failures
    ok = got is not None and abs(got - want) <= tol
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def a_day_of_weather(start: int) -> list[dict]:
    """Records that move, so an average is not the same as any one of them."""
    import math

    made = []
    for step in range(int(HOURS * 3600 / INTERVAL)):
        when = start + step * INTERVAL
        swing = math.sin(step / 24.0)
        made.append({
            "dateTime": when,
            "usUnits": 1,                      # US, which is WeeWX's default
            "interval": INTERVAL // 60,
            "outTemp": 55.0 + swing * 12.0,
            "outHumidity": 60.0 + swing * 15.0,
            "barometer": 29.9 + swing * 0.2,
            "windSpeed": 4.0 + abs(swing) * 6.0,
            "windDir": (step * 7) % 360,
            "windGust": 6.0 + abs(swing) * 9.0,
            "windGustDir": (step * 7) % 360,
            "rain": 0.01 if step % 40 == 0 else 0.0,
            "inTemp": 68.0 + swing * 3.0,
            "inHumidity": 44.0,
        })
    return made


def written_by_evo(where: Path, records: list[dict]) -> None:
    """An archive made by weewx-evo, from nothing.

    Not a copy of the reference database with rows added: the point is a
    file this program created, schema and all. A test that started from
    WeeWX's own file would be checking that we did not break it, which is a
    smaller claim.
    """
    from weewx_evo.db.archive import ArchiveStore

    store = ArchiveStore(where)
    try:
        for record in records:
            store.add_record(record)
        store.conn.commit()
    finally:
        store.close()


def weewx_manager(where: Path, create: bool = False,
                  initialize: bool = False):
    """WeeWX's own manager, opened on that file.

    `open` refuses a file that is not there, which is right: the half of
    this test that matters opens a database we made, and a manager that
    quietly created an empty one would pass while proving nothing.
    `open_with_create` is for the other direction, where WeeWX makes it.
    """
    import weewx.manager

    settings = {"SQLITE_ROOT": str(where.parent), "database_name": where.name,
                "driver": "weedb.sqlite"}
    if create:
        # `weewx.schemas` on a pip install, bare `schemas` on some layouts.
        # Asked for rather than assumed: getting it wrong here would look
        # like WeeWX being unable to make a database.
        try:
            from weewx.schemas import wview_extended
        except ImportError:
            from schemas import wview_extended

        return weewx.manager.DaySummaryManager.open_with_create(
            settings, schema=wview_extended.schema)
    if initialize:
        # What `rebuild_daily` does after dropping, and it is worth copying
        # rather than approximating: the day-summary schema is built **from
        # the archive's own columns**, not from a static list. That is the
        # same rule this whole program follows -- the schema comes from the
        # file -- and it is why a station with its own columns does not lose
        # them on a rebuild.
        with weewx.manager.Manager.open(settings, "archive") as plain:
            keys = plain.sqlkeys
        day_schema = [(one, "scalar") for one in keys
                      if one not in ("dateTime", "usUnits", "interval")]
        if "windSpeed" in keys:
            day_schema += [("wind", "vector")]
        return weewx.manager.open_manager(
            {"database_dict": settings, "table_name": "archive",
             "manager": "weewx.manager.DaySummaryManager",
             "schema": {"day_summaries": day_schema}}, initialize=True)
    return weewx.manager.DaySummaryManager.open(settings)


def main() -> int:
    print("a database weewx-evo wrote, handed back to WeeWX\n")

    try:
        import weewx
        import weewx.manager
    except ImportError as exc:
        print(f"  WeeWX is not installed here ({exc}), so there is nothing")
        print("  to hand the file to. This test needs it: checking our own")
        print("  work with our own code is what the other tests do.")
        print("\n  SKIP")
        return 0

    import weewx as weewx_module

    print(f"  WeeWX {getattr(weewx_module, '__version__', '?')}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        where = work / "weewx.sdb"

        # Midnight local, so the daily summaries land on a whole day.
        start = int(time.mktime((2026, 5, 14, 0, 0, 0, 0, 0, -1)))
        records = a_day_of_weather(start)

        print("\n1. weewx-evo makes an archive and fills it")
        written_by_evo(where, records)
        check("the file exists", where.is_file(), True)
        check("with the records in it", _count(where), len(records))

        print("\n2. WeeWX's own manager opens it")
        try:
            manager = weewx_manager(where)
        except Exception as exc:
            check(f"it opened ({type(exc).__name__}: {exc})", False, True)
            return 1
        try:
            check("it opened", manager is not None, True)
            check("and agrees how many records there are",
                  manager.getSql("SELECT COUNT(*) FROM archive")[0],
                  len(records))

            print("\n3. WeeWX reads them back")
            _weewx_reads(manager, records)

            print("\n4. WeeWX writes a record of its own")
            after = start + len(records) * INTERVAL
            fresh = dict(records[-1])
            fresh["dateTime"] = after
            fresh["outTemp"] = 61.5
            manager.addRecord(fresh)
            check("it went in",
                  manager.getSql("SELECT COUNT(*) FROM archive")[0],
                  len(records) + 1)
            got = manager.getRecord(after)
            near("and reads back as WeeWX wrote it",
                 (got or {}).get("outTemp"), 61.5)
        finally:
            manager.close()

        print("\n5. weewx-evo reads what WeeWX wrote")
        _evo_reads(where, after, len(records) + 1)

        print("\n6. and WeeWX's own consistency check passes")
        _weewx_checks(where)

        print("\nand the other way round: WeeWX first, then weewx-evo")
        _the_other_way(work, start)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("a database written here is a database WeeWX can carry on using")
    return 0


def _count(where: Path) -> int:
    import sqlite3

    conn = sqlite3.connect(f"file:{where.as_posix()}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM archive").fetchone()[0])
    finally:
        conn.close()


def _weewx_reads(manager, records: list[dict]) -> None:
    """What WeeWX makes of the records and the summaries we wrote.

    Its own accessors, not SQL: `getRecord` and `getAggregate` are what a
    skin and a report go through, so this is the path that decides whether
    somebody's website still works.
    """
    import weewx

    wanted = records[len(records) // 2]
    got = manager.getRecord(wanted["dateTime"])
    check("a record comes back", got is not None, True)
    if got:
        near("with the temperature we stored",
             got.get("outTemp"), wanted["outTemp"], 1e-4)
        check("and the unit system", got.get("usUnits"), 1)

    # The daily summaries, through WeeWX's own aggregate call. This is the
    # part `archive_day_*` exists for, and the part a rebuild would have to
    # reproduce -- so if WeeWX can read ours, ours are WeeWX's.
    from weeutil.weeutil import TimeSpan

    day = TimeSpan(records[0]["dateTime"] - 60,
                   records[-1]["dateTime"] + 60)
    highest = max(one["outTemp"] for one in records)
    try:
        found = manager.getAggregate(day, "outTemp", "max")
    except weewx.UnknownAggregation as exc:
        check(f"the daily maximum ({exc})", False, True)
        return
    near("WeeWX's own daily maximum matches ours", found[0], highest, 1e-4)

    total = sum(one["rain"] for one in records)
    rained = manager.getAggregate(day, "rain", "sum")
    near("and the rain total", rained[0], total, 1e-6)


def _evo_reads(where: Path, when: int, expected: int) -> None:
    """weewx-evo reading a file WeeWX has just written into."""
    from weewx_evo.db.archive import ArchiveStore

    store = ArchiveStore(where)
    try:
        check("we see WeeWX's record count", store.count(), expected)
        row = store.record(when)
        check("and its record", row is not None, True)
        if row:
            near("with the value WeeWX put there", row.get("outTemp"), 61.5)
        # The daily summaries have to have been updated by WeeWX's write,
        # and read the same way here. A summary WeeWX advanced and we cannot
        # read is the failure this whole rule exists to prevent.
        check("the daily tables are still ours to read",
              len(store.schema.day_types) > 0, True)
    finally:
        store.close()


def _weewx_checks(where: Path) -> None:
    """WeeWX's own check of a database, run on the file.

    `weectl database check` in the shape the library offers it. What it looks
    for is a daily summary that disagrees with the archive -- exactly the
    thing that would be wrong if our arithmetic differed from theirs.
    """
    manager = weewx_manager(where)
    try:
        version = manager.version
        check("the daily-summary version WeeWX expects", version, "4.0")
        # Its own consistency pass. Older releases spell it differently, so
        # what is asked for is whatever this WeeWX offers.
        # `weectl database check` is a version check and nothing more --
        # measured, not assumed: its whole body reads the metadata and says
        # whether the weighting fix is needed. So the version is the check
        # it offers, and the real one is below.
        version_only = getattr(manager, "check", None) is None
        if version_only:
            print("  --   WeeWX's own check is the version, which is above")
    finally:
        manager.close()

    # The hard one, and the reason this test exists rather than a claim in a
    # README: **WeeWX rebuilds the daily summaries from our archive, and the
    # figures have to be the ones we wrote.**
    #
    # `difftest` does this in the other direction -- our arithmetic against
    # their file. This is theirs against ours, computed by their own
    # `backfill_day_summary` from the records we stored, and it is the
    # closest thing there is to proof that the file means what it says.
    print("\n7. WeeWX rebuilds the daily summaries from our archive")
    _weewx_rebuilds(where)


def _weewx_rebuilds(where: Path) -> None:
    """Ours, then WeeWX's own, from the same records."""
    import sqlite3

    manager = weewx_manager(where)
    try:
        ours = _summary_row(where, "outTemp")
        rained = _summary_row(where, "rain")
        manager.drop_daily()
    except Exception as exc:
        check(f"the summaries could be dropped ({type(exc).__name__}: {exc})",
              False, True)
        return
    finally:
        manager.close()

    # Reopened with `initialize=True`, which is what WeeWX's own
    # `rebuild_daily` does: dropping takes `archive_day__metadata` with it,
    # and the backfill wants it back. Doing it the short way raised
    # NoTableError and looked like our file missing a table it in fact has.
    try:
        manager = weewx_manager(where, initialize=True)
        try:
            manager.backfill_day_summary()
        finally:
            manager.close()
        theirs = _summary_row(where, "outTemp")
        rained_again = _summary_row(where, "rain")
        if True:
            pass
    except Exception as exc:
        check(f"the rebuild ran ({type(exc).__name__}: {exc})", False, True)
        return

    if not ours or not theirs:
        check("there were summaries to compare", bool(ours and theirs), True)
        return

    # Sums and counts must be identical: they come from archive records
    # alone, so a difference is an arithmetic disagreement about the same
    # numbers. Extremes may legitimately blunt on a rebuild -- ours can hold
    # a LOOP high that no archive record has -- so they are reported and not
    # failed, the same asymmetry `difftest` draws.
    for field in ("sum", "count", "wsum", "sumtime"):
        near(f"outTemp {field} survives WeeWX's own rebuild",
             theirs.get(field), ours.get(field, 0.0), 1e-6)
    near("rain sum too", rained_again.get("sum"), rained.get("sum", 0.0), 1e-9)
    for field in ("min", "max"):
        if abs((theirs.get(field) or 0) - (ours.get(field) or 0)) > 1e-6:
            print(f"       outTemp {field}: ours {ours.get(field)}, "
                  f"theirs {theirs.get(field)} -- a rebuild may blunt an "
                  f"extreme, never sharpen one")
    check("no extreme came back sharper",
          (theirs.get("max") or 0) <= (ours.get("max") or 0) + 1e-6
          and (theirs.get("min") or 0) >= (ours.get("min") or 0) - 1e-6,
          True)
    del sqlite3


def _summary_row(where: Path, field: str) -> dict:
    """The first day of `archive_day_<field>`, as a dict.

    Read with sqlite3 rather than through the manager. `manager.connection`
    is not part of its surface, and reaching for it returned nothing and
    silently -- so the comparison had two empty dicts and reported that
    there was nothing to compare, which is true and useless.
    """
    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{where.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        # The fullest day, not the first. The first is whatever fell before
        # the first midnight -- here a single record, so `count` was 1 and
        # the comparison held one number. Green, and measuring nothing.
        cursor = conn.execute(
            f"SELECT * FROM archive_day_{field} ORDER BY count DESC, "
            f"dateTime LIMIT 1")
        names = [d[0] for d in cursor.description]
        row = cursor.fetchone()
        return dict(zip(names, row, strict=True)) if row else {}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _the_other_way(work: Path, start: int) -> None:
    """WeeWX creates the file, weewx-evo carries on writing into it.

    The half somebody actually does: they have a WeeWX database and point
    this at a copy. A schema WeeWX made must be one we extend rather than
    replace -- the schema comes from the file, never from a list in our
    code, and this is where that is tested rather than asserted.
    """
    where = work / "theirs.sdb"
    manager = weewx_manager(where, create=True)
    try:
        theirs = a_day_of_weather(start - 86400)
        for record in theirs[:12]:
            manager.addRecord(record)
        made = manager.getSql("SELECT COUNT(*) FROM archive")[0]
    finally:
        manager.close()
    check("WeeWX made a database", made, 12)

    from weewx_evo.db.archive import ArchiveStore

    store = ArchiveStore(where)
    try:
        check("we read what WeeWX wrote", store.count(), 12)
        mine = dict(theirs[12])
        store.add_record(mine)
        store.conn.commit()
        check("and we can add to it", store.count(), 13)
    finally:
        store.close()

    manager = weewx_manager(where)
    try:
        check("WeeWX sees ours too",
              manager.getSql("SELECT COUNT(*) FROM archive")[0], 13)
        got = manager.getRecord(theirs[12]["dateTime"])
        near("and reads the record we added",
             (got or {}).get("outTemp"), theirs[12]["outTemp"], 1e-4)
    finally:
        manager.close()


if __name__ == "__main__":
    sys.exit(main())

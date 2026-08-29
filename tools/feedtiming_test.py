#!/usr/bin/env python3
"""When a feed runs, and that every declared trigger actually does something.

`feeds.TRIGGERS` named three of them and the runner read none: every feed
produced on the archive record, `realtime` included, whose whole reason for
existing is being newer than that. A file consumers poll every ten seconds was
as old as the archive interval, and nothing about the output showed it.

So this is the check the derived readings ended up with, in the same shape:
every name in TRIGGERS has to make a feed run differently from the others.
Declaring one and having it ignored is what this is here to stop.

    python tools/feedtiming_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import feedrunner  # noqa: E402
from weewx_evo import feeds as feed_registry  # noqa: E402

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def runner_with(schedule: dict) -> feedrunner.Runner:
    """A runner that produces nothing, so only the timing is under test."""
    with tempfile.TemporaryDirectory() as raw:
        return feedrunner.Runner([], archive_path=Path(raw) / "none.sdb",
                                 schedule=schedule)


def every_trigger_does_something() -> None:
    """The one that would have caught `realtime` on the day it was written."""
    print("\nevery trigger in TRIGGERS changes when a feed runs")
    schedule = {
        "onrecord": {"trigger": "record", "every": 0},
        "onpacket": {"trigger": "packet", "every": 0},
        "onclock": {"trigger": "schedule", "every": 3600},
    }
    runner = runner_with(schedule)
    now = 1787800000.0
    # Prime the scheduled one, or its first call is the startup produce.
    runner.due_now("onclock", "schedule", now)

    ran = {}
    for because in ("record", "packet", "schedule"):
        ran[because] = sorted(
            name for name in schedule
            if runner.due_now(name, because, now))

    check("an archive record runs only the archive feeds",
          ran["record"], ["onrecord"])
    check("a reading runs only the packet feeds", ran["packet"], ["onpacket"])
    check("and the clock runs neither of those", ran["schedule"], [])

    covered = {one for names in ran.values() for one in names}
    # `schedule` fires by the clock rather than by `because`, so it is
    # counted separately -- but it has to fire.
    later = runner.due_now("onclock", "schedule", now + 3601)
    check("the scheduled one runs when its time comes", later, True)
    check("every declared trigger reached a feed",
          sorted(covered | {"onclock"}), ["onclock", "onpacket", "onrecord"])


def the_clock_is_the_clock() -> None:
    print("\nan hourly feed produces on the hour, not an hour after starting")
    runner = runner_with({"hourly": {"trigger": "schedule", "every": 3600}})
    # Part way into an hour, wherever that falls. Computed rather than
    # guessed: the first attempt asserted "not at 59 minutes", which is after
    # the next whole hour when the start is 43 minutes in, and failed for a
    # reason that had nothing to do with the code.
    started = 1787800631.0
    on_the_hour = (int(started // 3600) + 1) * 3600

    check("the first pass produces at once, so nothing waits an hour",
          runner.due_now("hourly", "schedule", started), True)
    check("not again a minute later",
          runner.due_now("hourly", "schedule", started + 60), False)
    check("nor a minute before the hour",
          runner.due_now("hourly", "schedule", on_the_hour - 60), False)
    check("but on the hour it does",
          runner.due_now("hourly", "schedule", on_the_hour), True)
    check("and the one after that is a whole hour on",
          runner._next["hourly"], on_the_hour + 3600)


def a_feed_that_says_nothing() -> None:
    """Every installation that predates the setting."""
    print("\na feed with no schedule runs on the archive, as they all did")
    runner = runner_with({})
    check("on a record", runner.due_now("anything", "record"), True)
    check("not on a reading", runner.due_now("anything", "packet"), False)
    check("not on the clock", runner.due_now("anything", "schedule"), False)


def what_the_feeds_declare() -> None:
    """The declarations themselves, so a new feed cannot invent a trigger."""
    print("\nwhat the bundled feeds ask for")
    feed_registry.load()
    for kind in feed_registry.kinds():
        factory = feed_registry.factory_for(kind)
        declared = getattr(factory, "trigger", "record")
        check(f"{kind} declares a real trigger",
              declared in feed_registry.TRIGGERS, True)
    # The one that was wrong. Named on its own, because it is the reason all
    # of this exists.
    realtime = feed_registry.factory_for("realtime")
    check("realtime still asks for every reading",
          getattr(realtime, "trigger", None), "packet")


def the_runner_wakes_for_packets_only_when_asked() -> None:
    """An eight-second console must not rebuild a skin eight times a minute."""
    print("\nthe listener's packets only wake a runner that wants them")
    quiet = runner_with({"page": {"trigger": "record", "every": 0}})
    quiet.packet_stored()
    check("no packet feed, nothing woken", quiet.live.is_set(), False)

    live = runner_with({"now": {"trigger": "packet", "every": 0}})
    live.packet_stored()
    check("with one, it is woken", live.live.is_set(), True)


def a_feed_deleted_while_running_stops() -> None:
    """And a new one starts, without a restart.

    `apply_live` rebuilds the exports, the uploads and the forecasts when the
    file changes, and its own docstring warns that scattering this across the
    loop is how three of them came to be missing. The feeds were the fourth:
    one deleted on the settings page went on being produced, and a new one
    was not produced at all, until somebody restarted. Nothing said so.

    Seen in the field: a feed removed from the file, and the log still
    reporting "images: 68 chart(s)" two minutes later.
    """
    print("\nthe set of feeds can be swapped while the runner is up")
    runner = runner_with({"json": {"trigger": "record"}})
    made = [("json", lambda reader: None, Path("json")),
            ("images", lambda reader: None, Path("images"))]
    runner.replace(made, {"json": {"trigger": "record"},
                          "images": {"trigger": "record"}})
    check("both are in", [n for n, _b, _i in runner.feeds],
          ["json", "images"])

    # A due time for a feed that is gone would keep a name alive that
    # nothing produces any more.
    runner._next = {"json": 1.0, "images": 2.0}
    runner.replace([made[0]], {"json": {"trigger": "record"}})
    check("the deleted one is gone", [n for n, _b, _i in runner.feeds],
          ["json"])
    check("and takes its due time with it", sorted(runner._next), ["json"])
    check("while the survivor keeps its own", runner._next.get("json"), 1.0)


def main() -> int:
    every_trigger_does_something()
    the_clock_is_the_clock()
    a_feed_that_says_nothing()
    what_the_feeds_declare()
    the_runner_wakes_for_packets_only_when_asked()
    a_feed_deleted_while_running_stops()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("every trigger a feed can declare is one the runner acts on")
    return 0


if __name__ == "__main__":
    sys.exit(main())

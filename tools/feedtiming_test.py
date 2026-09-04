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

import argparse
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

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


def archive_names_are_resolved_once_and_exactly() -> None:
    """A configured name never means whichever database happens to exist."""
    print("\nfeed schedules use the registry's actual implicit name")
    from weewx_evo import settings as settings_state
    from weewx_evo.cli import feed_schedule, forecast_db, settings_for, status_placer

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        config = work / "evo.toml"
        config.write_text(
            '[feeds.page]\nkind = "json"\n\n'
            '[feeds.bad]\nkind = "json"\narchive = "gone"\n',
            encoding="utf-8")
        (work / "archives.toml").write_text(
            '[archives.north]\nfile = "elsewhere/north.sdb"\n'
            'senders = "*"\n', encoding="utf-8")
        args = argparse.Namespace(config=config, weewx_conf=None)
        settings_state.forget_running()
        cfg = settings_for(args)
        scheduled = feed_schedule(args, cfg)
        check("a sole custom place is the implicit series",
              scheduled["page"]["archive"], "north")
        check("an unknown explicit name is preserved for refusal",
              scheduled["bad"]["archive"], "gone")
        check("the shared forecast is anchored on the installation",
              forecast_db(args, cfg), work / "forecast.sdb")

        (work / "archives.toml").write_text(
            '[archives.north]\nfile = "north.sdb"\nsenders = "*"\n\n'
            '[archives.south]\nfile = "south.sdb"\nsenders = []\n',
            encoding="utf-8")
        config.write_text(
            '[feeds.implicit]\nkind = "json"\n\n'
            '[feeds.explicit]\nkind = "json"\narchive = "south"\n',
            encoding="utf-8")
        settings_state.forget_running()
        cfg = settings_for(args)
        scheduled = feed_schedule(args, cfg)
        check("two custom places do not invent a default",
              scheduled["implicit"]["archive"], "")
        check("an explicit place remains exact",
              scheduled["explicit"]["archive"], "south")
        class Ambiguous:
            @staticmethod
            def default_name():
                raise LookupError("ambiguous")

            @staticmethod
            def get(_name):
                raise AssertionError("an ambiguous registry has no default")

        check("the diagnostic status has no arbitrary placer",
              status_placer(Ambiguous(), None, None), None)

        strict = feedrunner.Runner(
            [], archive_path=work / "north.sdb",
            schedule={"bad": {"archive": "gone"}},
            archives={"north": work / "north.sdb"},
            default_archive="north")
        check("the runner does not redirect an unknown name",
              strict.path_for("bad"), None)


def cheetah_fallback_uses_the_placed_archive() -> None:
    """A direct renderer never revives the central archive_db setting."""
    print("\na direct Cheetah renderer uses its placed archive as fallback")
    from weewx_evo.feeds.cheetah import _forecast_archive, _placed_forecast_path

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)

        class Placed:
            archive = SimpleNamespace(name="north", file="data/north.sdb")
            _path = work / "evo.toml"

            @staticmethod
            def get(name: str, default=None):
                return "wrong/central.sdb" if name == "archive_db" else default

        check("the compatibility cache follows the placed archive",
              _placed_forecast_path(Placed()),
              work / "data" / "forecast.sdb")
        check("and its rows use that archive's name",
              _forecast_archive(Placed()), "north")


def form_defaults_follow_the_registry() -> None:
    """A new entry must not save a literal place that does not exist."""
    print("\nfeed, forecast and upload forms use the real implicit place")
    from weewx_evo import options as option_defs
    from weewx_evo import uploads
    from weewx_evo.forecast import place_options

    def archive_option(groups):
        return next(option for group in groups for option in group.options
                    if option.name == "archive")

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        config = work / "evo.toml"
        config.write_text("", encoding="utf-8")
        archives = work / "archives.toml"
        archives.write_text(
            '[archives.north]\nfile = "north.sdb"\nsenders = "*"\n',
            encoding="utf-8")
        option_defs.building_for(config)
        try:
            defaults = (
                archive_option(feed_registry.schedule_options()).default,
                archive_option(place_options()).default,
                archive_option(uploads.when_options()).default,
            )
            check("a sole custom-named place is selected", defaults,
                  ("north", "north", "north"))

            archives.write_text(
                '[archives.north]\nfile = "north.sdb"\nsenders = "*"\n\n'
                '[archives.south]\nfile = "south.sdb"\nsenders = []\n',
                encoding="utf-8")
            choices = tuple(
                archive_option(groups) for groups in (
                    feed_registry.schedule_options(), place_options(),
                    uploads.when_options()))
            check("several custom places invent no default",
                  tuple(one.default for one in choices), ("", "", ""))
            check("the forms require a visible choice",
                  tuple(one.options()[0][0] for one in choices), ("", "", ""))

            # A broken authority is no authority. Offering the conventional
            # name here would let saving an unrelated form persist a place
            # that the existing file never defined.
            archives.write_text("[archives.north\n", encoding="utf-8")
            check("an unreadable registry offers no invented place",
                  feed_registry.archive_names(), [])
            check("an unreadable registry invents no default",
                  feed_registry.default_archive_name(), "")
            broken = archive_option(feed_registry.schedule_options())
            check("the feed form leaves the broken choice unset",
                  broken.default, "")
            check("and asks for a real place instead",
                  broken.options()[0][0], "")
        finally:
            option_defs.building_for(None)


def main() -> int:
    every_trigger_does_something()
    the_clock_is_the_clock()
    a_feed_that_says_nothing()
    what_the_feeds_declare()
    the_runner_wakes_for_packets_only_when_asked()
    a_feed_deleted_while_running_stops()
    archive_names_are_resolved_once_and_exactly()
    cheetah_fallback_uses_the_placed_archive()
    form_defaults_follow_the_registry()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("every trigger a feed can declare is one the runner acts on")
    return 0


if __name__ == "__main__":
    sys.exit(main())

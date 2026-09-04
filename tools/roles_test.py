#!/usr/bin/env python3
"""Two stations, one archive, and one `outTemp` between them.

Left alone they take turns writing it every few seconds, and the column ends
up holding a mixture that nothing afterwards can separate. There are three
answers to that and this checks the third: the second station's readings are
*moved* into `extraTemp<n>` rather than thrown away or given a file of their
own.

The two halves that matter, and the first is the larger one:

  * a single station is untouched. That is every installation, and a role
    mechanism that changed anything for it would be a mechanism that could
    break the ordinary case in exchange for the rare one.
  * an extra station's wind, rain and pressure have nowhere to go. They are
    dropped, and it is said once -- because the alternative is somebody
    adding a second weather station and discovering a year later that two of
    its readings were ever kept.

    python tools/roles_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import dataclasses  # noqa: E402

from weewx_evo import archives as archive_defs  # noqa: E402
from weewx_evo import placement, roles  # noqa: E402
from weewx_evo import stations as station_defs  # noqa: E402
from weewx_evo.db.live import LiveStore, Packet, sender_id  # noqa: E402
from weewx_evo.ingest.listener import Ingest  # noqa: E402

failures = 0

READING = {
    "outTemp": 20.5, "outHumidity": 62.0, "dewpoint": 13.1,
    "windSpeed": 3.2, "windDir": 210.0, "barometer": 29.9, "rain": 0.0,
    "outTempBatteryStatus": 0.0,
}


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def a_single_station_is_untouched() -> None:
    """Every installation. This has to change nothing at all for it."""
    print("\none station, which is every installation")
    kept = roles.apply(dict(READING), roles.MAIN, 0, "kirchdorf")
    check("nothing is moved", sorted(kept), sorted(READING))
    check("and the values are the same", kept, READING)
    # Even given a channel, which a main station should never have.
    check("a channel does not make it extra",
          roles.apply(dict(READING), roles.MAIN, 3), READING)


def an_extra_station_is_moved_aside() -> None:
    print("\na second station in the same archive")
    roles._said.clear()
    moved = roles.apply(dict(READING), roles.EXTRA, 3, "garten")
    check("its temperature has somewhere to go",
          moved.get("extraTemp3"), 20.5)
    check("and its humidity", moved.get("extraHumid3"), 62.0)
    check("and its dew point follows the temperature",
          moved.get("extraDewpoint3"), 13.1)
    check("the main station's columns are not touched",
          [n for n in ("outTemp", "outHumidity", "dewpoint") if n in moved],
          [])


def what_has_nowhere_to_go_is_dropped() -> None:
    """The limit, said rather than hidden."""
    print("\nwind, rain and pressure have no second column")
    roles._said.clear()
    moved = roles.apply(dict(READING), roles.EXTRA, 3, "garten")
    check("they are not written",
          [n for n in ("windSpeed", "windDir", "barometer", "rain")
           if n in moved], [])
    # Its own housekeeping stays: two stations do not collide on a battery
    # name, and an extra station whose battery nobody can see is worse.
    check("but its own battery does",
          moved.get("outTempBatteryStatus"), 0.0)

    # Nothing at all to keep is an empty packet, which the listener drops.
    only_wind = roles.apply({"windSpeed": 3.2}, roles.EXTRA, 3, "windy")
    check("a station with only wind writes nothing", only_wind, {})


def the_channels_are_handed_out_in_order() -> None:
    print("\nwhich channel a second station gets")
    check("the first free one", roles.next_channel(set()), 1)
    check("then the next", roles.next_channel({1}), 2)
    check("and it fills gaps", roles.next_channel({1, 3}), 2)
    check("until there are none",
          roles.next_channel(set(range(1, roles.CHANNELS + 1))), None)


def one_station_can_have_two_roles() -> None:
    """The role belongs to the archive/member edge, not the station node."""
    print("\none console used differently by two places")
    station = sender_id("ecowitt", "BBBB")
    own = archive_defs.Archive(
        "garden", "garden.sdb", stations=(station,))
    combined = archive_defs.Archive(
        "combined", "combined.sdb", stations=(station,), members={
            station: archive_defs.MemberPolicy(
                role="extra", channel=4, indoor=False),
        })
    check("it is main in its own place", own.policy_for(station),
          archive_defs.MemberPolicy())
    check("and extra in the combined place", combined.policy_for(station),
          archive_defs.MemberPolicy(role="extra", channel=4, indoor=False))


def the_reader_applies_it() -> None:
    """Through the core, which is where a driver never has to know.

    Measured on the way *out*. The shift used to happen in the listener,
    before the packet was stored, and this test asked the listener for it --
    so it was testing the mechanism rather than the outcome, and could not
    have noticed that a wrong channel was unrecoverable. What the table holds
    is what the console sent; who gets which column is decided when a record
    is built, and that is what is checked here.
    """
    print("\nthrough the reader, where no driver is involved")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "stations.toml").write_text(
            '[stations.kirchdorf]\ndriver = "ecowitt"\n'
            'identity = "AAAA"\n\n'
            '[stations.garten]\ndriver = "ecowitt"\n'
            'identity = "BBBB"\n', encoding="utf-8")
        register = station_defs.load(work / "stations.toml")
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        try:
            ingest = Ingest(live, token=None, stations=register)
            roles._said.clear()
            garden = sender_id("ecowitt", "BBBB")
            own = archive_defs.Archive(
                "own", "own.sdb", stations=(garden,), members={
                    garden: archive_defs.MemberPolicy(),
                })
            combined = archive_defs.Archive(
                "combined", "combined.sdb", stations=(garden,), members={
                    garden: archive_defs.MemberPolicy(
                        role="extra", channel=2, indoor=False),
                })
            own_placer = placement.Placer(
                own, placement.Placements(), register)
            combined_placer = placement.Placer(
                combined, placement.Placements(), register)

            stored = ingest._named(
                Packet(dateTime=1787900000, usUnits=1,
                       data={**READING, "inTemp": 19.0},
                       identity="BBBB"), "ecowitt", "127.0.0.1")
            check("the console's own reading is kept as it arrived",
                  stored.data.get("outTemp"), 20.5)

            main = own_placer.place(stored)
            check("the same console is main in its own place",
                  main.data.get("outTemp"), 20.5)
            check("and keeps its indoor reading there",
                  main.data.get("inTemp"), 19.0)

            extra = combined_placer.place(stored)
            check("it is moved in the combined place",
                  extra.data.get("extraTemp2"), 20.5)
            check("and does not write outTemp",
                  "outTemp" in extra.data, False)
            check("and the combined place omits its indoor reading",
                  "inTemp" in extra.data, False)

            # And the whole point of the move: change the channel, place the
            # same stored packet again, and the reading follows. Under the old
            # arrangement the table held `extraTemp2` and there was nothing
            # left to move.
            moved = dataclasses.replace(combined, members={
                garden: archive_defs.MemberPolicy(
                    role="extra", channel=5, indoor=False),
            })
            roles._said.clear()
            again = placement.Placer(moved, placement.Placements(),
                                     register).place(stored)
            check("a channel changed today reaches yesterday's reading",
                  again.data.get("extraTemp5"), 20.5)
        finally:
            live.close()


def a_station_with_nothing_left_is_stored_anyway() -> None:
    """It has nowhere to go in the archive. It is still a measurement."""
    print("\nan extra station that sends only what it cannot keep")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "stations.toml").write_text(
            '[stations.windy]\ndriver = "ecowitt"\n'
            'identity = "CCCC"\n', encoding="utf-8")
        register = station_defs.load(work / "stations.toml")
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        try:
            ingest = Ingest(live, token=None, stations=register)
            roles._said.clear()
            got = ingest._named(
                Packet(dateTime=1787900000, usUnits=1,
                       data={"windSpeed": 3.2}, identity="CCCC"),
                "ecowitt", "127.0.0.1")
            check("the wind is in the table", got.data.get("windSpeed"), 3.2)
            check("it is stored", live.add(got), True)
            archive = archive_defs.Archive(
                "default", "default.sdb",
                stations=(sender_id("ecowitt", "CCCC"),), members={
                    sender_id("ecowitt", "CCCC"): archive_defs.MemberPolicy(
                        role="extra", channel=1),
                })
            placer = placement.Placer(archive, placement.Placements(), register)
            check("but no record is built from it", placer.place(got), None)
        finally:
            live.close()


def the_page_writes_and_reads_it_back() -> None:
    print("\nsetting the role, and the channel it implies")
    from weewx_evo import adminarchives
    from weewx_evo.admin import Admin
    from weewx_evo.cli import all_schemas

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "evo.toml").write_text('token = "abcdefghij123456"\n',
                                       encoding="utf-8")
        (work / "stations.toml").write_text(
            '[stations.kirchdorf]\ndriver = "ecowitt"\n'
            'identity = "AAAA"\n\n'
            '[stations.garten]\ndriver = "ecowitt"\n'
            'identity = "BBBB"\n', encoding="utf-8")
        (work / "archives.toml").write_text(
            '[archives.default]\nfile = "data/weewx.sdb"\n'
            'stations = ["kirchdorf", "garten"]\n', encoding="utf-8")
        path = work / "evo.toml"
        admin = Admin(path, lambda: all_schemas(path), "abcdefghij123456")
        garden = sender_id("ecowitt", "BBBB")
        kirchdorf = sender_id("ecowitt", "AAAA")

        error = adminarchives.configure(admin, "default", {
            "_members": "1", f"sender:{garden}": "1",
            f"sender:{kirchdorf}": "1",
            f"member-role:{garden}": "extra",
            f"member-channel:{garden}": "",
            f"member-indoor:{garden}": "1",
            f"member-role:{kirchdorf}": "main",
            f"member-indoor:{kirchdorf}": "1"})
        check("it saves", error, "")
        again = adminarchives.load(admin).get("default")
        check("the role is written on the place",
              again.policy_for(garden).role, "extra")
        check("and a channel was chosen",
              again.policy_for(garden).channel, 1)
        check("and indoor belongs to the same relationship",
              again.policy_for(garden).indoor, True)

        # A second extra station gets the next one, not the same.
        adminarchives.configure(admin, "default", {
            "_members": "1", f"sender:{garden}": "1",
            f"sender:{kirchdorf}": "1",
            f"member-role:{garden}": "extra",
            f"member-channel:{garden}": "1",
            f"member-indoor:{garden}": "1",
            f"member-role:{kirchdorf}": "extra",
            f"member-channel:{kirchdorf}": ""})
        both = adminarchives.load(admin).get("default")
        check("the second gets its own channel",
              sorted(both.policy_for(one).channel
                     for one in (garden, kirchdorf)), [1, 2])

        # Back to main, and the channel goes with it.
        adminarchives.configure(admin, "default", {
            "_members": "1", f"sender:{garden}": "1",
            f"sender:{kirchdorf}": "1",
            f"member-role:{garden}": "main",
            f"member-indoor:{garden}": "1",
            f"member-role:{kirchdorf}": "extra",
            f"member-channel:{kirchdorf}": "2"})
        back = adminarchives.load(admin).get("default").policy_for(garden)
        check("a main station has no channel", (back.role, back.channel),
              ("main", 0))
        check("the station object has no role authority",
              hasattr(station_defs.load(work / "stations.toml").by_name(
                  "kirchdorf"), "role"), False)


def main() -> int:
    a_single_station_is_untouched()
    an_extra_station_is_moved_aside()
    what_has_nowhere_to_go_is_dropped()
    the_channels_are_handed_out_in_order()
    one_station_can_have_two_roles()
    the_reader_applies_it()
    a_station_with_nothing_left_is_stored_anyway()
    the_page_writes_and_reads_it_back()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("a second station is moved aside, and one station notices nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())

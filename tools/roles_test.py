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

from weewx_evo import roles  # noqa: E402
from weewx_evo import stations as station_defs  # noqa: E402
from weewx_evo.db.live import LiveStore, Packet  # noqa: E402
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


def two_main_stations_are_worth_saying() -> None:
    """A configuration that asks for the failure this prevents."""
    print("\ntwo stations both calling themselves the station")
    made = [station_defs.Station(name=n, driver="ecowitt", identity=n)
            for n in ("kirchdorf", "garten")]
    check("both are named", roles.too_many_main(made), ["garten", "kirchdorf"])

    from dataclasses import replace

    made[1] = replace(made[1], role=roles.EXTRA, channel=1)
    check("one of each is fine", roles.too_many_main(made), [])
    check("and one alone certainly is",
          roles.too_many_main(made[:1]), [])


def the_listener_applies_it() -> None:
    """Through the core, which is where a driver never has to know."""
    print("\nthrough the listener, where no driver is involved")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "stations.toml").write_text(
            '[stations.kirchdorf]\ndriver = "ecowitt"\n'
            'identity = "AAAA"\narchive = "default"\n\n'
            '[stations.garten]\ndriver = "ecowitt"\n'
            'identity = "BBBB"\narchive = "default"\n'
            'role = "extra"\nchannel = 2\n', encoding="utf-8")
        register = station_defs.load(work / "stations.toml")
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        try:
            ingest = Ingest(live, token=None, stations=register)
            roles._said.clear()

            main = ingest._named(
                Packet(dateTime=1787900000, usUnits=1, data=dict(READING),
                       source="AAAA"), "ecowitt", "127.0.0.1")
            check("the main station keeps its own columns",
                  main.data.get("outTemp"), 20.5)
            check("under its name", main.source, "kirchdorf")

            extra = ingest._named(
                Packet(dateTime=1787900000, usUnits=1, data=dict(READING),
                       source="BBBB"), "ecowitt", "127.0.0.1")
            check("the extra one is moved", extra.data.get("extraTemp2"), 20.5)
            check("and does not write outTemp",
                  "outTemp" in extra.data, False)
            check("under its own name", extra.source, "garten")
        finally:
            live.close()


def a_station_with_nothing_left_is_not_stored() -> None:
    """An empty packet is not a packet."""
    print("\nan extra station that sends only what it cannot keep")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "stations.toml").write_text(
            '[stations.windy]\ndriver = "ecowitt"\n'
            'identity = "CCCC"\narchive = "default"\n'
            'role = "extra"\nchannel = 1\n', encoding="utf-8")
        register = station_defs.load(work / "stations.toml")
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        try:
            ingest = Ingest(live, token=None, stations=register)
            roles._said.clear()
            got = ingest._named(
                Packet(dateTime=1787900000, usUnits=1,
                       data={"windSpeed": 3.2}, source="CCCC"),
                "ecowitt", "127.0.0.1")
            check("nothing comes back rather than an empty packet", got, None)
        finally:
            live.close()


def the_page_writes_and_reads_it_back() -> None:
    print("\nsetting the role, and the channel it implies")
    from weewx_evo import adminstations
    from weewx_evo.admin import Admin
    from weewx_evo.cli import all_schemas

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "evo.toml").write_text('token = "abcdefghij123456"\n',
                                       encoding="utf-8")
        (work / "stations.toml").write_text(
            '[stations.kirchdorf]\ndriver = "ecowitt"\n'
            'identity = "AAAA"\narchive = "default"\n\n'
            '[stations.garten]\ndriver = "ecowitt"\n'
            'identity = "BBBB"\narchive = "default"\n', encoding="utf-8")
        path = work / "evo.toml"
        admin = Admin(path, lambda: all_schemas(path), "abcdefghij123456")

        error = adminstations.configure(admin, "garten",
                                        {"role": "extra", "indoor": "1"})
        check("it saves", error, "")
        again = station_defs.load(work / "stations.toml").by_name("garten")
        check("the role is written", again.role, "extra")
        check("and a channel was chosen", again.channel, 1)

        # A second extra station gets the next one, not the same.
        adminstations.configure(admin, "kirchdorf", {"role": "extra"})
        both = station_defs.load(work / "stations.toml")
        check("the second gets its own channel",
              sorted(one.channel for one in both), [1, 2])

        # Back to main, and the channel goes with it.
        adminstations.configure(admin, "garten", {"role": "main"})
        back = station_defs.load(work / "stations.toml").by_name("garten")
        check("a main station has no channel", (back.role, back.channel),
              ("main", 0))


def main() -> int:
    a_single_station_is_untouched()
    an_extra_station_is_moved_aside()
    what_has_nowhere_to_go_is_dropped()
    the_channels_are_handed_out_in_order()
    two_main_stations_are_worth_saying()
    the_listener_applies_it()
    a_station_with_nothing_left_is_not_stored()
    the_page_writes_and_reads_it_back()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("a second station is moved aside, and one station notices nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())

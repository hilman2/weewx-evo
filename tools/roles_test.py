#!/usr/bin/env python3
"""One place, one primary sender, and everything else placed by hand.

Two senders both send `outTemp`, and a place has one `outTemp`. Left alone
they take turns writing it every few seconds and the column ends up holding a
mixture nothing afterwards can separate -- worse for `rain`, whose extractor
is `sum`, so two consoles reporting 1 mm store 2.

What this checks is that the arrangement makes that unsayable rather than
merely invalid, and what it costs:

  * a single sender is untouched. That is every installation, and a mechanism
    that changed anything for it would break the ordinary case in exchange
    for the rare one.
  * `Archive.primary` is one sender ID, so two primaries have no spelling --
    not in the file, not through the form, not through the API.
  * every other sender writes only what somebody has placed. Nothing is
    guessed for it, which is the deliberate cost: its readings sit in the
    live journal until a column is named, and a rebuild then brings the whole
    retention period with them.
  * with nobody having said, the *earliest* sender is the primary. A console
    plugged in this afternoon cannot take over a series that predates it.

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
from weewx_evo.db.live import LiveStore, Packet, SenderIdentity, sender_id  # noqa: E402
from weewx_evo.ingest.listener import Ingest  # noqa: E402

failures = 0

READING = {
    "outTemp": 20.5, "outHumidity": 62.0, "dewpoint": 13.1,
    "windSpeed": 3.2, "windDir": 210.0, "barometer": 29.9, "rain": 0.0,
    "outTempBatteryStatus": 0.0,
}

KIRCHDORF = sender_id("ecowitt", "AAAA")
GARDEN = sender_id("ecowitt", "BBBB")


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def heard(*pairs: tuple[str, float]) -> list[SenderIdentity]:
    """A live sender directory, as `LiveStore.senders` hands one over."""
    return [SenderIdentity(sender=one, driver="ecowitt", identity=one[-4:],
                           label=one, first_seen=when)
            for one, when in pairs]


def a_single_sender_is_untouched() -> None:
    """Every installation. This has to change nothing at all for it."""
    print("\none sender, which is every installation")
    one = archive_defs.Archive("default", "d.sdb", stations=(KIRCHDORF,))
    check("it is the primary without anybody saying so",
          one.primary_sender(), KIRCHDORF)
    check("and it is main", one.role_of(KIRCHDORF), roles.MAIN)
    check("nothing was written into the file to make that true",
          one.primary, "")

    broad = archive_defs.Archive("default", "d.sdb", stations=None)
    check("a place that takes every arrival says the same",
          broad.role_of(KIRCHDORF, heard((KIRCHDORF, 1000.0))), roles.MAIN)


def two_primaries_have_no_spelling() -> None:
    """The whole point: not rejected, unsayable.

    The old arrangement put a role on each member, so N mains was a state the
    model could hold and nothing checked. This tries every way in.
    """
    print("\nthere is no way to say 'both of these are primary'")
    one = archive_defs.Archive(
        "default", "d.sdb", stations=(KIRCHDORF, GARDEN), primary=GARDEN)
    check("one is primary", one.role_of(GARDEN, heard((KIRCHDORF, 1.0))),
          roles.MAIN)
    check("so the other is not",
          one.role_of(KIRCHDORF, heard((KIRCHDORF, 1.0))), roles.EXTRA)

    # Setting the second one replaces the first. There is one field.
    moved = dataclasses.replace(one, primary=KIRCHDORF)
    check("naming another one moves it rather than adding it",
          [moved.role_of(x) for x in (KIRCHDORF, GARDEN)],
          [roles.MAIN, roles.EXTRA])

    # And a primary the place does not select is refused rather than ignored:
    # ignored, the place would quietly fall back to a different sender and
    # keep working, with the line that says otherwise doing nothing.
    try:
        archive_defs.Archive("default", "d.sdb", stations=(KIRCHDORF,),
                             primary=GARDEN)
    except ValueError as exc:
        check("a primary that is not a member is refused",
              "which it does not select" in str(exc), True)
    else:
        check("a primary that is not a member is refused", False, True)


def the_earliest_sender_is_the_primary() -> None:
    """With nobody having said. The rule the console order has to survive."""
    print("\nnobody has said, so the earliest one is it")
    both = archive_defs.Archive("default", "d.sdb", stations=None)
    # Deliberately the other way round from the IDs' sort order, so a test
    # that passed by sorting rather than by dating would fail here.
    directory = heard((GARDEN, 1000.0), (KIRCHDORF, 9000.0))
    check("the one heard first", both.primary_sender(directory), GARDEN)
    check("and the later one is extra",
          both.role_of(KIRCHDORF, directory), roles.EXTRA)

    # A sender the station file announced but the journal never heard sits at
    # 0. Sorted in it would come first of all and take over the series.
    never = heard((GARDEN, 0.0), (KIRCHDORF, 9000.0))
    check("one that has never sent cannot be the series",
          both.primary_sender(never), KIRCHDORF)

    check("with nothing heard at all, a typed selection keeps its order",
          archive_defs.Archive("d", "d.sdb",
                               stations=(KIRCHDORF, GARDEN)).primary_sender(),
          KIRCHDORF)
    check("and a place with no senders has no primary",
          archive_defs.Archive("d", "d.sdb", stations=()).primary_sender(), "")


def an_extra_sender_writes_only_what_it_was_placed() -> None:
    """Through the reader, which is where a driver never has to know.

    Measured on the way *out*. What the live table holds is what the console
    sent; which column that becomes is decided when a record is built, and
    that is what makes a wrong decision recoverable.
    """
    print("\nan additional sender, placed by hand and not otherwise")
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
            placement._said.clear()
            own = archive_defs.Archive(
                "own", "own.sdb", stations=(GARDEN,), primary=GARDEN)
            combined = archive_defs.Archive(
                "combined", "combined.sdb", stations=(KIRCHDORF, GARDEN),
                primary=KIRCHDORF, members={
                    GARDEN: archive_defs.MemberPolicy(indoor=False)})

            stored = ingest._named(
                Packet(dateTime=1787900000, usUnits=1,
                       data={**READING, "inTemp": 19.0},
                       identity="BBBB"), "ecowitt", "127.0.0.1")
            check("the console's own reading is kept as it arrived",
                  stored.data.get("outTemp"), 20.5)

            main = placement.Placer(
                own, placement.Placements(), register).place(stored)
            check("the same console is the series in its own place",
                  main.data.get("outTemp"), 20.5)
            check("and keeps its indoor reading there",
                  main.data.get("inTemp"), 19.0)

            # Its battery is the exception, and only its battery: those names
            # already carry their sensor, so two senders cannot collide on
            # them, and a sender whose battery nobody can see is worse.
            bare = placement.Placer(
                combined, placement.Placements(), register).place(stored)
            check("beside another sender it writes nothing but housekeeping",
                  bare.data, {"outTempBatteryStatus": 0.0})

            nothing = placement.Placer(
                combined, placement.Placements(), register).place(
                    dataclasses.replace(stored, data={"outTemp": 20.5}))
            check("and with nothing to keep it builds no record at all",
                  nothing, None)

            # And what somebody places, it writes -- including the column the
            # old preset used to fill on its own.
            plans = placement.Placements()
            plans.decide("combined", GARDEN, "", "outTemp", "extraTemp3")
            placed = placement.Placer(
                combined, plans, register).place(stored)
            check("a placed reading goes where it was placed",
                  placed.data.get("extraTemp3"), 20.5)
            check("and nothing else came with it",
                  sorted(placed.data), ["extraTemp3", "outTempBatteryStatus"])
        finally:
            live.close()


def a_changed_primary_reaches_yesterday() -> None:
    """The reason the decision is on the read side at all."""
    print("\nchange who the series comes from, and last week follows")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "stations.toml").write_text(
            '[stations.garten]\ndriver = "ecowitt"\n'
            'identity = "BBBB"\n', encoding="utf-8")
        register = station_defs.load(work / "stations.toml")
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        try:
            ingest = Ingest(live, token=None, stations=register)
            placement._said.clear()
            stored = ingest._named(
                Packet(dateTime=1787900000, usUnits=1, data=dict(READING),
                       identity="BBBB"), "ecowitt", "127.0.0.1")
            check("it is stored", live.add(stored), True)

            combined = archive_defs.Archive(
                "combined", "c.sdb", stations=(KIRCHDORF, GARDEN),
                primary=KIRCHDORF)
            aside = placement.Placer(combined, placement.Placements(),
                                     register).place(stored)
            check("as an additional sender its temperature reaches no column",
                  "outTemp" in aside.data, False)

            promoted = dataclasses.replace(combined, primary=GARDEN)
            again = placement.Placer(promoted, placement.Placements(),
                                     register).place(stored)
            check("made the primary today, yesterday's packet is a reading",
                  again.data.get("outTemp"), 20.5)
        finally:
            live.close()


def the_page_writes_and_reads_it_back() -> None:
    print("\nchoosing the primary on the settings page")
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
            f'senders = ["{KIRCHDORF}", "{GARDEN}"]\n', encoding="utf-8")
        path = work / "evo.toml"
        admin = Admin(path, lambda: all_schemas(path), "abcdefghij123456")

        error = adminarchives.configure(admin, "default", {
            "_members": "1", f"sender:{GARDEN}": "1",
            f"sender:{KIRCHDORF}": "1",
            f"member-policy:{GARDEN}": "1",
            f"member-policy:{KIRCHDORF}": "1",
            "member-primary": GARDEN,
            f"member-indoor:{GARDEN}": "1"})
        check("it saves", error, "")
        again = adminarchives.load(admin).get("default")
        check("the primary is written on the place", again.primary, GARDEN)
        check("so the other one is additional",
              again.role_of(KIRCHDORF), roles.EXTRA)
        check("indoor still belongs to the member relationship",
              (again.policy_for(GARDEN).indoor,
               again.policy_for(KIRCHDORF).indoor), (True, False))

        # The radio group carries one value, so this is the only shape a
        # second choice can arrive in: it replaces, never adds.
        adminarchives.configure(admin, "default", {
            "_members": "1", f"sender:{GARDEN}": "1",
            f"sender:{KIRCHDORF}": "1",
            f"member-policy:{GARDEN}": "1",
            f"member-policy:{KIRCHDORF}": "1",
            "member-primary": KIRCHDORF})
        moved = adminarchives.load(admin).get("default")
        check("choosing another one moves it", moved.primary, KIRCHDORF)
        check("and there is still exactly one",
              [moved.role_of(x) for x in (KIRCHDORF, GARDEN)],
              [roles.MAIN, roles.EXTRA])

        # Unticking the primary row is how it arrives with none named. The
        # place does not lose its series over it.
        adminarchives.configure(admin, "default", {
            "_members": "1", f"sender:{GARDEN}": "1",
            f"member-policy:{GARDEN}": "1",
            "member-primary": KIRCHDORF})
        alone = adminarchives.load(admin).get("default")
        check("removing the primary sender clears the name", alone.primary, "")
        check("and the remaining sender is the series",
              alone.primary_sender(), GARDEN)

        check("the sender object has no role authority",
              hasattr(station_defs.load(work / "stations.toml").by_name(
                  "kirchdorf"), "role"), False)


def the_file_carries_it() -> None:
    print("\nand it survives the file")
    with tempfile.TemporaryDirectory() as raw:
        where = Path(raw) / "archives.toml"
        register = archive_defs.Register([archive_defs.Archive(
            "default", "d.sdb", stations=(KIRCHDORF, GARDEN),
            primary=GARDEN)])
        register.save(where)
        back = archive_defs.Register.load(where).get("default")
        check("the primary round trips", back.primary, GARDEN)
        check("and a member policy is only what is left of one",
              dataclasses.asdict(back.policy_for(GARDEN)), {"indoor": True})

        where.write_text(
            '[archives.default]\nfile = "d.sdb"\n'
            f'senders = ["{KIRCHDORF}"]\nprimary = "nonsense"\n',
            encoding="utf-8")
        try:
            archive_defs.Register.load(where)
        except ValueError as exc:
            check("a mistyped primary is refused rather than shrugged at",
                  "not a sender ID" in str(exc), True)
        else:
            check("a mistyped primary is refused rather than shrugged at",
                  False, True)


def main() -> int:
    a_single_sender_is_untouched()
    two_primaries_have_no_spelling()
    the_earliest_sender_is_the_primary()
    an_extra_sender_writes_only_what_it_was_placed()
    a_changed_primary_reaches_yesterday()
    the_page_writes_and_reads_it_back()
    the_file_carries_it()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("one place has one primary, and everything else is placed by hand")
    return 0


if __name__ == "__main__":
    sys.exit(main())

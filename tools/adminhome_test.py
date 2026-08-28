#!/usr/bin/env python3
"""The overview, and the two ways a dashboard becomes worthless.

One is saying nothing while something is broken. The other is saying
something while nothing is -- and that one is worse, because a page that
cries wolf gets a glance and then gets ignored, and then it is not a
dashboard, it is decoration.

So the rules here are comparisons rather than clocks, and this checks both
directions of every one of them. The case that matters most is a station
switched off: everything goes old at once, and none of it is a fault.

    python tools/adminhome_test.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import adminhome  # noqa: E402
from weewx_evo.admin import Admin  # noqa: E402
from weewx_evo.cli import all_schemas  # noqa: E402
from weewx_evo.db.archive import ArchiveStore  # noqa: E402
from weewx_evo.db.live import LiveStore, Packet  # noqa: E402

failures = 0

TOKEN = "abcdefghij123456"
INTERVAL = 300


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def an_installation(work: Path, *, token: str = TOKEN,
                    packets_ago: int | None = 20,
                    record_ago: int | None = 120,
                    stranger: bool = False,
                    announced: bool = True) -> Admin:
    """A station on disk, aged to order."""
    (work / "data").mkdir(exist_ok=True)
    lines = [
        f'token = "{token}"\n' if token else "",
        f'live_db = "{(work / "data" / "live.sdb").as_posix()}"\n',
        f'archive_db = "{(work / "data" / "weewx.sdb").as_posix()}"\n',
        f'feeds_dir = "{(work / "data" / "feeds").as_posix()}"\n',
        f"interval = {INTERVAL}\n",
        '[station]\nname = "Kirchdorf"\n',
        "latitude = 48.4012\nlongitude = 11.6301\naltitude = 440.0\n",
    ]
    (work / "evo.toml").write_text("".join(lines), encoding="utf-8")
    if announced:
        (work / "stations.toml").write_text(
            '[stations.kirchdorf]\ndriver = "wunderground"\n'
            'identity = "evo-3f9a2c"\narchive = "default"\n', encoding="utf-8")

    now = int(time.time())
    live = LiveStore(work / "data" / "live.sdb", interval_seconds=INTERVAL)
    if packets_ago is not None:
        for n in range(5):
            live.add(Packet(dateTime=now - packets_ago - n * 16, usUnits=1,
                            data={"outTemp": 20.0}, source="kirchdorf"))
        if stranger:
            live.add(Packet(dateTime=now - packets_ago, usUnits=1,
                            data={"outTemp": 9.0}, source="somebody-else"))
        # The archiver has taken these; a backlog is its own test.
        for stop, _seconds in live.due(now=now + 86400, grace=0):
            live.clear_pending(stop)
    live.close()

    archive = ArchiveStore(work / "data" / "weewx.sdb")
    if record_ago is not None:
        archive.conn.execute(
            "INSERT INTO archive (dateTime, usUnits, `interval`, outTemp)"
            " VALUES (?, ?, ?, ?)", (now - record_ago, 1, 5, 20.0))
        archive.conn.commit()
    archive.close()

    return Admin(work / "evo.toml",
                 lambda: all_schemas(work / "evo.toml"), TOKEN)


def a_working_station_says_nothing() -> None:
    print("\nnothing wrong, nothing said")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw))
        state = adminhome.read(admin)
        check("no concerns", state.concerns, [])
        check("the station is listed", [one.name for one in state.stations],
              ["kirchdorf"])
        check("and the archive is", len(state.archives), 1)
        check("with its records counted",
              "1 records" in state.archives[0].detail, True)


def a_station_switched_off_is_not_a_fault() -> None:
    """The one that decides whether this page is worth having open.

    Everything goes old together. A rule written as "the archive is older
    than ten minutes" fires here and is wrong: there is nothing to archive.
    """
    print("\na station that has been off for a day")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw), packets_ago=86400,
                                record_ago=86400 + 60)
        state = adminhome.read(admin)
        check("nothing is reported as broken", state.concerns, [])
        # It stays visible, which is the other half: quiet is not the same as
        # hidden. A day reads as "24 h ago" -- the switch to days is at two,
        # because "1 d ago" is vaguer than the hours it replaces.
        check("but the age is plain to see",
              adminhome.ago(state.newest_packet), "24 h ago")


def an_archiver_that_stopped_is_a_fault() -> None:
    """Packets arriving, nothing archived. The comparison, not the clock."""
    print("\nreadings arriving and nothing being archived")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw), packets_ago=5,
                                record_ago=INTERVAL * 6)
        state = adminhome.read(admin)
        check("it is reported", len(state.concerns), 1)
        check("and it says which way round it is",
              "behind the newest packet" in state.concerns[0], True)


def a_backlog_is_a_fault() -> None:
    print("\nintervals piling up unarchived")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work)
        # Mark more intervals pending than the limit allows, the way a
        # stopped archiver would leave them.
        live = LiveStore(work / "data" / "live.sdb", interval_seconds=INTERVAL)
        now = int(time.time())
        for n in range(adminhome.PENDING_LIMIT + 3):
            live.mark_pending(now - n * INTERVAL - 10)
        live.close()

        state = adminhome.read(admin)
        check("the backlog is counted",
              state.pending > adminhome.PENDING_LIMIT, True)
        check("and reported",
              any("waiting to be archived" in one for one in state.concerns),
              True)


def a_stranger_is_worth_saying() -> None:
    """Readings arriving that reach no archive at all."""
    print("\nsomething uploading that no station answers for")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw), stranger=True)
        state = adminhome.read(admin)
        check("it is counted", state.strangers, 1)
        check("and named as not reaching an archive",
              any("no station answers for" in one for one in state.concerns),
              True)


def a_console_that_was_renamed_is_not_a_stranger() -> None:
    """The live instance's own case, and it was a false alarm.

    A console announced under a new name leaves its old packets behind, and
    they stay for the whole retention period. Sixteen hours after the rename
    the page still said a source "is uploading" that nothing answered for,
    and it would have said so for a fortnight. A stranger is something
    arriving now.
    """
    print("\nold packets from a console that has since been named")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work)
        live = LiveStore(work / "data" / "live.sdb", interval_seconds=INTERVAL)
        old = int(time.time() - adminhome.STRANGER_WINDOW - 3600)
        live.add(Packet(dateTime=old, usUnits=1, data={"outTemp": 20.0},
                        source="3178AB6B42A759F51A5A4AD72E37F8DE"))
        live.close()

        state = adminhome.read(admin)
        check("nothing is reported", state.strangers, 0)
        check("and the page stays quiet", state.concerns, [])

        # One arriving now is still a stranger, which is the half that has
        # to keep working.
        live = LiveStore(work / "data" / "live.sdb", interval_seconds=INTERVAL)
        live.add(Packet(dateTime=int(time.time()) - 5, usUnits=1,
                        data={"outTemp": 9.0}, source="a-neighbour"))
        live.close()
        state = adminhome.read(admin)
        check("a current one is", state.strangers, 1)
        check("and it says when it last did",
              "uploaded" in state.concerns[0] and "ago" in state.concerns[0],
              True)


def two_stations_claiming_one_archive() -> None:
    """A configuration that asks for the one failure that cannot be undone.

    Two stations of one archive both writing `outTemp` take turns at it every
    few seconds. The listener moves the extra one aside rather than let that
    happen -- but a configuration that asks for it is worth saying out loud
    rather than silently working around.
    """
    print("\ntwo main stations in one archive")
    both = ('[stations.kirchdorf]\ndriver = "ecowitt"\n'
            'identity = "AAAA"\narchive = "default"\n\n'
            '[stations.garten]\ndriver = "ecowitt"\n'
            'identity = "BBBB"\narchive = "default"\n')
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work)
        (work / "stations.toml").write_text(both, encoding="utf-8")

        state = adminhome.read(admin)
        check("it is reported",
              any("as the main one" in one for one in state.concerns), True)
        check("naming both",
              any("garten, kirchdorf" in one for one in state.concerns), True)

        # One of each is the arrangement, not a fault.
        (work / "stations.toml").write_text(
            both + 'role = "extra"\nchannel = 1\n', encoding="utf-8")
        state = adminhome.read(admin)
        check("with a role set, nothing is said",
              [one for one in state.concerns if "main one" in one], [])

        # And two archives are two places, so two main stations are right.
        (work / "archives.toml").write_text(
            "[archives.default]\n"
            f'file = "{(work / "data" / "weewx.sdb").as_posix()}"\n\n'
            "[archives.nordfeld]\n"
            f'file = "{(work / "data" / "nord.sdb").as_posix()}"\n',
            encoding="utf-8")
        (work / "stations.toml").write_text(
            both.replace('[stations.garten]', '[stations.nordhof]')
                .replace('identity = "BBBB"\narchive = "default"',
                         'identity = "BBBB"\narchive = "nordfeld"'),
            encoding="utf-8")
        state = adminhome.read(admin)
        check("two archives, two main stations, no complaint",
              [one for one in state.concerns if "main one" in one], [])


def no_token_is_worth_saying() -> None:
    print("\nno upload token")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw), token="")
        state = adminhome.read(admin)
        check("it is reported",
              any("No upload token" in one for one in state.concerns), True)


def what_cannot_be_read_says_so() -> None:
    """A zero and 'not reachable from here' are different facts."""
    print("\na database this process cannot see")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work, packets_ago=None, record_ago=None)
        (work / "data" / "live.sdb").unlink()
        state = adminhome.read(admin)
        check("the live table says why, rather than showing nothing",
              bool(state.live and state.live.unreachable), True)
        check("and it names the path",
              "live.sdb" in (state.live.unreachable if state.live else ""),
              True)


def a_relative_path_and_an_environment_variable() -> None:
    """How this page finds the databases, which it got wrong twice.

    Once as "a station that has never been heard from" beside a database
    holding four hundred of its packets, and once as `/data/data/live.sdb`
    on the running instance. Both times the file was read and the
    environment, which is what a container actually sets, was not.

    Everything else in this test writes absolute paths, so none of it would
    have caught either.
    """
    print("\nwhere the databases are, the way a container writes it")
    import os

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "data").mkdir()
        (work / "evo.toml").write_text(
            f'token = "{TOKEN}"\n'
            'live_db = "data/live.sdb"\n'      # relative, as shipped
            'archive_db = "data/weewx.sdb"\n', encoding="utf-8")
        LiveStore(work / "data" / "live.sdb", interval_seconds=INTERVAL).close()
        admin = Admin(work / "evo.toml",
                      lambda: all_schemas(work / "evo.toml"), TOKEN)

        state = adminhome.read(admin)
        check("a relative path resolves against the settings file",
              bool(state.live and not state.live.unreachable), True)

        # And the environment beats it, because that is the order the
        # archiver itself resolves in.
        elsewhere = work / "elsewhere.sdb"
        LiveStore(elsewhere, interval_seconds=INTERVAL).close()
        was = os.environ.get("WEEWX_EVO_LIVE")
        os.environ["WEEWX_EVO_LIVE"] = str(elsewhere)
        try:
            found = adminhome._setting(admin, "live_db", "data/live.sdb")
            check("the environment wins", found, elsewhere)
        finally:
            if was is None:
                del os.environ["WEEWX_EVO_LIVE"]
            else:
                os.environ["WEEWX_EVO_LIVE"] = was


def never_is_only_said_when_it_is_true() -> None:
    """The running instance said "never" for five exports that had just run.

    An export's own record of what it has sent is named after a hash of both
    ends, so this page cannot find it. Guessing a path and finding nothing
    produced a confident wrong answer -- worse than no answer, because
    somebody would have gone looking for a broken export.
    """
    print("\nexports, and what this page can actually know")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work)
        published = work / "site"
        published.mkdir()
        (published / "index.html").write_text("<p>hi</p>", encoding="utf-8")

        current = admin.config()
        current["exports"] = {
            "site": {"kind": "local", "directory": str(published)},
            # `source`, which is what the setting is called. This said
            # `feed` and so did the page, so the two agreed and neither was
            # right: on a real installation the line read "ftp, on feed"
            # and never named anything.
            "away": {"kind": "ftp", "trigger": "feed", "source": "json"},
        }
        # The uploads that ran, as the progress file records them. `live` is
        # not in the configuration at all: it is set up from the export.
        (work / "data" / "uploads.json").write_text(
            f'{{"through": {{"live": {int(time.time() - 10)}}}}}',
            encoding="utf-8")
        current["uploads"] = {}
        admin.config = lambda: current  # type: ignore[method-assign]

        state = adminhome.read(admin)
        by_name = {one.name: one for one in state.exports}
        check("a local export is dated from what it published",
              by_name["site"].when is not None, True)
        check("one that has not run says so, rather than 'never'",
              by_name["away"].unreachable, "waiting for its first run")
        check("and says what it waits for",
              "on the json feed" in by_name["away"].detail, True)
        check("which is not a fault", by_name["away"].wrong, False)

        # And once it has run. This is the whole point of the record: the
        # page is a different process from the one that does the uploading,
        # so an FTP export used to say "not recorded here" for ever -- true,
        # and no use to somebody asking whether their upload is working.
        from weewx_evo.db.live import LiveStore
        from weewx_evo.exports import Sent
        from weewx_evo.exports import record as export_record

        live = LiveStore(work / "data" / "live.sdb", interval_seconds=300)
        try:
            export_record.write(live, "away",
                                Sent(sent=9, skipped=33, seconds=3.2))
        finally:
            live.close()
        after = {one.name: one for one in adminhome.read(admin).exports}
        check("once it has run, it is dated",
              after["away"].when is not None, True)
        check("and says what it did",
              "9 sent, 33 unchanged" in after["away"].detail, True)

        live = LiveStore(work / "data" / "live.sdb", interval_seconds=300)
        try:
            export_record.write(live, "away", None,
                                error="530 login incorrect")
        finally:
            live.close()
        broken = {one.name: one for one in adminhome.read(admin).exports}
        check("a refusal is what the page shows",
              broken["away"].unreachable, "530 login incorrect")
        check("marked as something wrong", broken["away"].wrong, True)

        posted = {one.name: one for one in state.uploads}
        check("an upload nobody configured but that is running shows up",
              "live" in posted, True)
        check("marked as what it is",
              posted["live"].detail if "live" in posted else "",
              "set up automatically")


def a_duration_is_a_duration() -> None:
    """`interval = "5m"` is what the file says, and it is not an integer.

    `int("5m")` raised on the first line of the rules, so nothing after it
    ran and the page reported nothing wrong about an installation with a
    backlog. A dashboard silenced by a format it writes itself.
    """
    print("\nthe archive interval, written the way the file writes it")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work, packets_ago=5,
                                record_ago=INTERVAL * 6)
        current = admin.config()
        current["interval"] = "5m"
        admin.config = lambda: current  # type: ignore[method-assign]

        state = adminhome.read(admin)
        check("it is read as seconds", state.interval, 300)
        check("and the rules after it still run",
              any("behind the newest packet" in one
                  for one in state.concerns), True)

        # And something unreadable does not stop them either.
        current["interval"] = "whenever"
        state = adminhome.read(admin)
        check("an unreadable one falls back", state.interval, 300)
        check("rather than stopping the page", len(state.concerns) >= 1, True)


def the_live_file_dates_itself() -> None:
    """`live.json` needs no bookkeeping to be reported.

    The live upload keeps its position in memory on purpose -- it moves every
    few seconds, and a file written that often wears out an SD card. So this
    page reads the file the upload already writes instead. Nothing was added
    to the upload for the page's benefit.
    """
    print("\nlive readings, dated from the file they are written to")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work)
        published = work / "site"
        published.mkdir()
        current = admin.config()
        current["exports"] = {"site": {"kind": "local",
                                       "directory": str(published)}}
        admin.config = lambda: current  # type: ignore[method-assign]

        # Configured but nothing written yet. The row is there, because the
        # export asked for it -- with no date, which is the same answer an
        # export gives before its first run. Saying nothing at all would be
        # the page disagreeing with what is set up.
        state = adminhome.read(admin)
        posted = {one.name: one for one in state.uploads}
        check("it is reported as soon as an export asks for it",
              "live readings" in posted, True)
        check("with no date before anything is written",
              posted["live readings"].when
              if "live readings" in posted else "x", None)

        (published / "live.json").write_text('{"outTemp": 20}',
                                             encoding="utf-8")
        state = adminhome.read(admin)
        posted = {one.name: one for one in state.uploads}
        check("dated from the file itself",
              posted["live readings"].when is not None
              if "live readings" in posted else False, True)
        check("and it names what it writes",
              "writes live.json" in posted["live readings"].detail
              if "live readings" in posted else "", True)


def every_section_is_the_one_the_rest_of_the_program_reads() -> None:
    """Four sections, and one of them is not plural.

    `[forecast]` is singular where `[feeds]`, `[exports]` and `[uploads]` are
    not. Reading `forecasts` gave a card saying nothing was configured on an
    installation fetching one every hour -- a page confidently wrong about
    the thing it exists to report.

    Checked all four together, because the next one to be renamed will not
    be the one somebody remembers to look at.
    """
    print("\nthe four sections, spelled the way the program spells them")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work)
        current = admin.config()
        current["feeds"] = {"json": {"kind": "json"}}
        # `live_push = false`, so the exports imply no live upload and this
        # counts what the section is spelled as rather than what is beside it.
        current["exports"] = {"site": {"kind": "local", "directory": str(work),
                                       "live_push": False}}
        current["uploads"] = {"wu": {"kind": "wunderground"}}
        # `kind` is the provider, and it is what the forecast store keys its
        # `run` table on -- not the name of the entry.
        current["forecast"] = {"kirchdorf": {"kind": "open-meteo"}}
        admin.config = lambda: current  # type: ignore[method-assign]

        state = adminhome.read(admin)
        for what, links in (("feeds", state.feeds), ("exports", state.exports),
                            ("uploads", state.uploads),
                            ("forecast", state.forecasts)):
            check(f"[{what}] reaches the page", len(links), 1)

        # And a real forecast database, built by the store that writes it.
        # The first version of this read a table called `hour`; there is no
        # such table, the query raised, and the exception was caught and
        # logged. A made-up database would have agreed with the mistake.
        from weewx_evo.forecast import Reading
        from weewx_evo.forecast.store import ForecastStore

        store = ForecastStore(work / "data" / "forecast.sdb")
        try:
            store.store(Reading(source="open-meteo", issued=int(time.time())),
                        fetched=int(time.time() - 30))
        finally:
            store.close()

        state = adminhome.read(admin)
        found = state.forecasts[0]
        check("a forecast that has been fetched is dated",
              found.when is not None, True)
        check("and not reported as unreachable", found.unreachable, "")


def the_shape_of_the_last_day() -> None:
    """A count is a moment; this page is about whether it is still working.

    "It stopped at four this morning" is a different fact from "it is not
    working now", and one number cannot tell you which you have.
    """
    print("\nthe last day, drawn")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work)
        live = LiveStore(work / "data" / "live.sdb", interval_seconds=INTERVAL)
        now = int(time.time())
        start = now - adminhome.HOURS * 3600
        # Three hours of readings, a gap, then two more. The gap is the thing
        # a single figure hides.
        #
        # Placed in the middle of each bucket, not at "now minus N hours":
        # four readings a minute apart straddle an hour boundary whenever the
        # clock is near one, and the first version of this counted eight
        # buckets instead of six depending on the time of day it ran.
        filled = (3, 4, 5, 20, 21)
        for bucket in filled:
            for n in range(4):
                live.add(Packet(dateTime=start + bucket * 3600 + 1800 + n,
                                usUnits=1, data={"outTemp": 20.0},
                                source="kirchdorf"))
        live.close()

        state = adminhome.read(admin)
        counts = state.live.history if state.live else []
        check("a bar for each of the last 24 hours",
              len(counts), adminhome.HOURS)
        check("filled where the readings are",
              [n for n, one in enumerate(counts) if one][:len(filled)],
              list(filled))
        check("four in each of them",
              [counts[n] for n in filled], [4] * len(filled))

        drawn = adminhome.sparkline(counts, "test")
        check("it draws as an svg", drawn.startswith("<svg"), True)
        check("one bar per hour that had something",
              drawn.count("<rect"), sum(1 for one in counts if one))
        check("and an hour with nothing draws nothing",
              drawn.count("<rect") < adminhome.HOURS, True)

        # Nothing at all draws nothing at all, rather than a flat line that
        # looks like a reading of zero.
        check("no data, no picture", adminhome.sparkline([0] * 24, "x"), "")
        check("and no list either", adminhome.sparkline([], "x"), "")


def the_page_renders_and_carries_the_numbers() -> None:
    """The HTML itself, because everything above tests the reading."""
    print("\nthe page")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw), stranger=True)
        html = adminhome.overview(admin)
        check("the station is on it", "kirchdorf" in html, True)
        check("so is the archive", "Kirchdorf" in html, True)
        check("the concern is at the top",
              html.index("to look at") < html.index("Arriving"), True)
        check("ages are words, not timestamps",
              "ago<" in html or "ago</" in html, True)
        check("and no unix timestamp leaked through",
              "17878" in html or "17879" in html, False)

        nav = "".join(adminhome.nav(admin, "overview"))
        check("the nav marks that there is something to see",
              'class="warn"' in nav, True)


def ages_read_as_ages() -> None:
    print("\nhow long ago")
    now = time.time()
    check("seconds", adminhome.ago(now - 12), "12 s ago")
    check("minutes", adminhome.ago(now - 600), "10 min ago")
    check("hours", adminhome.ago(now - 7200), "2 h ago")
    check("days", adminhome.ago(now - 3 * 86400), "3 d ago")
    check("and never is never", adminhome.ago(None), "never")


def the_live_row_says_all_of_it() -> None:
    """One upload, every destination it has.

    The row said "live.json in <a directory>" while the same upload was also
    posting to a web host -- and the web host is the half somebody configured
    on purpose, so it is the half they came to the page to see.

    Read from the same function the service builds the upload with. This page
    said one thing and the service did another for exactly as long as there
    were two readings of it.
    """
    print("\nthe live readings row names every destination")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        served = work / "data" / "site"
        served.mkdir(parents=True, exist_ok=True)
        (served / "live.json").write_text('{"dateTime": 1}', encoding="utf-8")

        current = admin.config()
        current["feeds"] = {"wdc": {"kind": "cheetah", "skin": "deck"}}
        current["exports"] = {
            "away": {"kind": "ftp", "host": "example.org", "source": "wdc",
                     "live_push": True,
                     "live_push_url": "https://evoftp.example.de"},
            "here": {"kind": "local", "directory": str(served),
                     "source": "wdc", "live_push": True},
        }
        current["uploads"] = {}
        admin.config = lambda: current  # type: ignore[method-assign]

        rows = {one.name: one for one in adminhome.read(admin).uploads}
        check("there is a row for it", "live readings" in rows, True)
        said = rows["live readings"].detail if "live readings" in rows else ""
        check("it names the web host", "evoftp.example.de" in said, True)
        check("and the directory it also writes",
              "1 directory" in said, True)
        check("dated from the file it writes",
              rows["live readings"].when is not None, True)

        # Switched off everywhere is no row at all.
        current["exports"] = {
            "away": {"kind": "ftp", "host": "example.org", "live_push": False}}
        check("nothing when no export asks for it",
              [one for one in adminhome.read(admin).uploads
               if one.name == "live readings"], [])


def main() -> int:
    a_working_station_says_nothing()
    a_station_switched_off_is_not_a_fault()
    an_archiver_that_stopped_is_a_fault()
    a_backlog_is_a_fault()
    a_stranger_is_worth_saying()
    a_console_that_was_renamed_is_not_a_stranger()
    two_stations_claiming_one_archive()
    no_token_is_worth_saying()
    what_cannot_be_read_says_so()
    a_relative_path_and_an_environment_variable()
    never_is_only_said_when_it_is_true()
    every_section_is_the_one_the_rest_of_the_program_reads()
    a_duration_is_a_duration()
    the_live_row_says_all_of_it()
    the_live_file_dates_itself()
    the_shape_of_the_last_day()
    the_page_renders_and_carries_the_numbers()
    ages_read_as_ages()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("the overview says what is wrong, and only when something is")
    return 0


if __name__ == "__main__":
    sys.exit(main())

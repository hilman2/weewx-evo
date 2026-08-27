#!/usr/bin/env python3
"""Stations: announced, seen, and what happens to an upload from each.

The two halves are deliberately stored differently and this checks both.
`stations.toml` is decided by a person and diffable; sightings are observed,
change every few seconds and live in the live database.

    python tools/stations_test.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import stations  # noqa: E402
from weewx_evo.db.live import LiveStore  # noqa: E402
from weewx_evo.ingest import drivers  # noqa: E402
from weewx_evo.ingest.listener import Ingest  # noqa: E402
from weewx_evo.ingest.sightings import Sightings  # noqa: E402

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def the_register() -> None:
    print("\nannouncing a station")
    reg = stations.Register()
    one = reg.add(stations.Station("kirchdorf", "wunderground", "evo-3f9a2c"))
    check("it is there", reg.by_name("kirchdorf"), one)
    check("found by its identity",
          reg.by_identity("wunderground", "evo-3f9a2c"), one)
    check("consoles upper-case things, so case is ignored",
          reg.by_identity("wunderground", "EVO-3F9A2C"), one)
    check("another driver with the same string is not it",
          reg.by_identity("ecowitt", "evo-3f9a2c"), None)
    check("the default archive is filled in", one.archive, "default")

    print("\nwhat is refused, and why it is refused rather than merged")
    for station, why in (
        (stations.Station("kirchdorf", "ecowitt", "ABC"), "the name"),
        (stations.Station("garten", "wunderground", "EVO-3F9A2C"), "the identity"),
        (stations.Station("Groß Garten", "ecowitt", "ABC"), "a bad name"),
        (stations.Station("garten", "ecowitt", ""), "no identity"),
    ):
        problem = reg.why_not(station)
        check(f"refused: {why}", bool(problem), True)
    check("and only the first station is registered", len(reg), 1)


def the_identity_we_hand_out() -> None:
    """The whole reason stations exist rather than adoption."""
    print("\nan identity nobody can type twice")
    reg = stations.Register()
    made = {reg.identity_for("wunderground") for _ in range(50)}
    check("50 asked for, 50 different", len(made), 50)
    check("they look like ours",
          all(one.startswith("evo-") for one in made), True)

    # A WU station ID is typed by a person, so two consoles can carry the
    # same one. That is the failure this makes impossible: the operator never
    # chooses the string.
    one = reg.identity_for("wunderground")
    reg.add(stations.Station("first", "wunderground", one))
    check("and one already handed out never comes back",
          reg.identity_for("wunderground") == one, False)


def several_archives() -> None:
    """`archive` is here from the first version, not added later."""
    print("\nstations belong to archives")
    reg = stations.Register()
    reg.add(stations.Station("haus", "wunderground", "evo-a", archive="haus"))
    reg.add(stations.Station("boden", "ecowitt", "PASS1", archive="haus"))
    reg.add(stations.Station("koppel", "wunderground", "evo-b", archive="koppel"))

    check("two stations in one series",
          [s.name for s in reg.for_archive("haus")], ["haus", "boden"])
    check("one in the other",
          [s.name for s in reg.for_archive("koppel")], ["koppel"])
    check("and the default is always offered",
          reg.archives(), ["default", "haus", "koppel"])


def the_file() -> None:
    print("\nwritten and read back")
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "stations.toml"
        reg = stations.Register()
        reg.add(stations.Station("kirchdorf", "wunderground", "evo-3f9a2c",
                                 note='a "quoted" note'))
        reg.add(stations.Station("garten", "ecowitt", "4F2A9C", archive="haus",
                                 learnt=True))
        stations.save(path, reg)

        back = stations.load(path)
        check("both came back", len(back), 2)
        check("the note survived quoting",
              back.by_name("kirchdorf").note, 'a "quoted" note')
        check("the archive survived", back.by_name("garten").archive, "haus")
        check("and whether it was learnt", back.by_name("garten").learnt, True)

        # An operator opens this file. It should say what it is.
        text = path.read_text(encoding="utf-8")
        check("the file explains itself", text.startswith("#"), True)
        check("no file, no stations, not an error",
              len(stations.load(Path(raw) / "nothing.toml")), 0)


def the_sightings() -> None:
    print("\nsomething uploaded that is not a station")
    with tempfile.TemporaryDirectory() as raw:
        live = LiveStore(Path(raw) / "live.sdb", interval_seconds=60)
        try:
            seen = Sightings(live)
            seen.saw("wunderground", "KNACHBAR", "192.168.33.51",
                     fields=["outTemp", "humidity"])
            seen.saw("wunderground", "KNACHBAR", "192.168.33.51")
            check("one sighting, two packets", len(seen.waiting()), 1)
            check("counted", seen.waiting()[0].packets, 2)
            check("with what it sent",
                  seen.waiting()[0].fields, ["outTemp", "humidity"])

            # What is *stored*, not what is in memory. A live run found this:
            # the first sighting was written before its counters were set, so
            # the database held `last_seen = 0` until the next write a minute
            # later. A restart inside that minute read a sighting last seen in
            # 1970 and the next expiry dropped it. Every check above passed
            # while that was true, because they all read the object.
            print("\nand what reached the database is complete, at once")
            fresh = Sightings(live)
            stored = fresh.find("wunderground", "KNACHBAR")
            check("stored at all", stored is not None, True)
            check("with a last_seen", stored.last_seen > 0, True)
            check("and where it came from", stored.peer, "192.168.33.51")
            # One, not two. The second upload is held rather than written:
            # a console posts every sixteen seconds and this would otherwise
            # be a database write each time for a number nobody reads. The
            # stored count lags by up to a minute on purpose.
            check("counted at least once", stored.packets >= 1, True)

            print("\nignoring folds it away, it stays adoptable")
            seen.ignore("wunderground", "KNACHBAR")
            check("out of the waiting list", len(seen.waiting()), 0)
            check("into the ignored one", len(seen.ignored()), 1)
            check("and still findable",
                  seen.find("wunderground", "KNACHBAR") is not None, True)

            print("\nand it survives a restart, because it is in the database")
            again = Sightings(live)
            check("still there", len(again.ignored()), 1)
            check("still ignored", again.ignored()[0].ignored, True)

            print("\nwhat is not seen again is forgotten")
            old = again.find("wunderground", "KNACHBAR")
            old.last_seen = int(time.time()) - 20 * 86400
            check("dropped after a fortnight", again.expire(), 1)
            check("nothing left", len(again.seen), 0)
        finally:
            live.close()


def an_upload_from_each() -> None:
    """The listener end: announced gets a name, unannounced gets noticed."""
    print("\nan upload from an announced station, and from a stranger")
    with tempfile.TemporaryDirectory() as raw:
        live = LiveStore(Path(raw) / "live.sdb", interval_seconds=60)
        try:
            reg = stations.Register()
            reg.add(stations.Station("kirchdorf", "wunderground", "evo-3f9a2c"))
            seen = Sightings(live)
            ingest = Ingest(live, token=None, default_driver="wunderground",
                            stations=reg, sightings=seen)

            ingest.submit(b"ID=evo-3f9a2c&action=updateraw&tempf=68.4",
                          "/wunderground/", "192.168.33.20")
            ingest.submit(b"ID=KSTRANGER&action=updateraw&tempf=51.1",
                          "/wunderground/", "192.168.33.51")

            stored = list(live.packets(0, 2_000_000_000))
            names = sorted(one.source for one in stored)
            check("both were stored", len(stored), 2)
            check("the announced one under its name, not its identity",
                  "kirchdorf" in names, True)
            check("the stranger under whatever it called itself",
                  "KSTRANGER" in names, True)
            check("and the stranger is on the list",
                  [s.identity for s in seen.waiting()], ["KSTRANGER"])
            check("the announced one is not",
                  seen.find("wunderground", "evo-3f9a2c"), None)
        finally:
            live.close()


def nothing_announced_changes_nothing() -> None:
    """An installation that has never seen the settings page."""
    print("\nwith no stations announced, an upload is untouched")
    with tempfile.TemporaryDirectory() as raw:
        live = LiveStore(Path(raw) / "live.sdb", interval_seconds=60)
        try:
            ingest = Ingest(live, token=None, default_driver="wunderground")
            ingest.submit(b"ID=KTEST&action=updateraw&tempf=68.4",
                          "/wunderground/", "192.168.33.20")
            stored = list(live.packets(0, 2_000_000_000))
            check("stored", len(stored), 1)
            check("under the identity its driver gave it",
                  stored[0].source, "KTEST")
        finally:
            live.close()


def the_settings_page() -> None:
    """Announce one, adopt a stranger, fold one away. Through the real page.

    Driven over HTTP rather than by calling the functions, because the bugs
    this page can have are in the wiring: a button in the wrong form, a POST
    that answers 200 where it should redirect, an action that reaches the
    wrong list. None of those show when the functions are called directly.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    from weewx_evo.admin import Admin, AdminServer
    from weewx_evo.cli import all_schemas
    from weewx_evo.ingest.sightings import Sightings
    from weewx_evo.ratelimit import Limits

    print("\nthe stations page, driven over HTTP")
    token = "a" * 32

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    def post(url, form):
        data = urllib.parse.urlencode(form).encode()
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(urllib.request.Request(url, data=data),
                             timeout=5) as answer:
                return answer.status, answer.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def get(url):
        with urllib.request.urlopen(url, timeout=5) as answer:
            return answer.status, answer.read().decode("utf-8", "replace")

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        path = tmp / "evo.toml"
        # The upload token too, not just the admin one. They are different
        # tokens on different ports, and it is the upload token a console has
        # to be told -- so the page has to read it from the configuration.
        path.write_text(
            f'live_db = "{(tmp / "live.sdb").as_posix()}"\n'
            f'token = "{"u" * 32}"\n', encoding="utf-8")
        live = LiveStore(tmp / "live.sdb", interval_seconds=60)
        # A stranger the listener would have noted.
        Sightings(live).saw("ecowitt", "STRANGER1", "192.168.33.51",
                            fields=["outTemp", "humidity"])
        live.close()

        admin = Admin(path, lambda: all_schemas(path), token,
                      limits=Limits(rate=0, failures=0))
        server = AdminServer(admin, "127.0.0.1", 0)
        server.start()
        base = f"http://127.0.0.1:{server.port}/{token}"
        try:
            status, body = get(f"{base}/stations")
            check("the page is there", status, 200)
            check("and the stranger is on it", "STRANGER1" in body, True)

            print("\nannouncing one hands out an identity to copy over")
            status, body = post(f"{base}/new-station",
                                {"name": "garden", "driver": "wunderground",
                                 "archive": "default"})
            check("it answers with what to enter", status, 200)
            check("naming the console", "garden" in body, True)
            check("and the identity it was given", "evo-" in body, True)
            check("with the upload token to type in",
                  ("u" * 32) in body, True)

            print("\nadopting the stranger")
            status, _ = post(f"{base}/stations/adopt",
                             {"driver": "ecowitt", "identity": "STRANGER1",
                              "name": "roof"})
            check("it redirects rather than rendering", status, 303)

            _, body = get(f"{base}/stations")
            check("both are announced now",
                  "garden" in body and "roof" in body, True)
            check("and the stranger is off the waiting list",
                  body.count("STRANGER1"), 1)   # only as the adopted station

            print("\nwhat the file says")
            register = stations.load(tmp / "stations.toml")
            check("two stations", len(register), 2)
            check("the announced one got an evo- identity",
                  register.by_name("garden").identity.startswith("evo-"), True)
            check("and is marked as ours to hand out",
                  register.by_name("garden").learnt, False)
            check("the adopted one kept the hardware's",
                  register.by_name("roof").identity, "STRANGER1")
            check("and is marked as read off it",
                  register.by_name("roof").learnt, True)

            print("\na name already taken is refused, and says so")
            status, body = post(f"{base}/new-station",
                                {"name": "garden", "driver": "wunderground"})
            check("the page comes back", status, 200)
            check("saying what is wrong", "already a station" in body, True)
            check("and nothing was added",
                  len(stations.load(tmp / "stations.toml")), 2)

            print("\nremoving one")
            status, _ = post(f"{base}/stations/roof/remove", {})
            check("redirects", status, 303)
            check("and it is gone",
                  stations.load(tmp / "stations.toml").by_name("roof"), None)
        finally:
            server.stop()


def main() -> int:
    drivers.DEFAULT.load()
    the_register()
    the_identity_we_hand_out()
    several_archives()
    the_file()
    the_sightings()
    an_upload_from_each()
    nothing_announced_changes_nothing()
    the_settings_page()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("stations are announced, strangers are noticed, neither is guessed at")
    return 0


if __name__ == "__main__":
    sys.exit(main())

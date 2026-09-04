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

from weewx_evo import archives as archive_defs  # noqa: E402
from weewx_evo import placement, stations  # noqa: E402
from weewx_evo.db.live import LiveStore, sender_id  # noqa: E402
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
    check("the console carries no archive assignment",
          hasattr(one, "archive"), False)
    check("and neither does the register",
          hasattr(reg, "for_archive") or hasattr(reg, "archives"), False)

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


def the_file() -> None:
    print("\nwritten and read back")
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "stations.toml"
        reg = stations.Register()
        reg.add(stations.Station("kirchdorf", "wunderground", "evo-3f9a2c",
                                 note='a "quoted" note'))
        reg.add(stations.Station("garten", "ecowitt", "4F2A9C", learnt=True,
                                 model="GW2000",
                                 max_behind=1200, max_ahead=60))
        stations.save(path, reg)

        back = stations.load(path)
        check("both came back", len(back), 2)
        check("the note survived quoting",
              back.by_name("kirchdorf").note, 'a "quoted" note')
        check("and whether it was learnt", back.by_name("garten").learnt, True)
        check("console settings survived", (
            back.by_name("garten").model,
            back.by_name("garten").max_behind,
            back.by_name("garten").max_ahead,
        ), ("GW2000", 1200.0, 60.0))

        # An operator opens this file. It should say what it is.
        text = path.read_text(encoding="utf-8")
        check("the file explains itself", text.startswith("#"), True)
        check("a new file carries no archive assignment", "archive =" in text,
              False)

        # A file with the keys that used to route a console. They are not
        # station state and never were runtime authority; the place selects
        # its senders and says what each is to it.
        print("\nrouting keys in this file are not station state")
        path.write_text(text.replace(
            'identity = "4F2A9C"',
            'identity = "4F2A9C"\narchive = "haus"\n'
            'role = "extra"\nchannel = 3\nindoor = false'),
            encoding="utf-8")
        stray = stations.load(path)
        check("the file still loads", stray.by_name("garten") is not None,
              True)
        check("the assignment is not part of the station",
              hasattr(stray.by_name("garten"), "archive"), False)
        check("nor is a role",
              hasattr(stray.by_name("garten"), "role"), False)
        stations.save(path, stray)
        check("and the next save writes neither back",
              any(key in path.read_text(encoding="utf-8")
                  for key in ("archive =", "role =", "channel =", "indoor =")),
              False)
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
            # The name is a lookup and the table records the pair, so the
            # name comes from the register on the way out. Frozen into the
            # row it used to split a series in two the moment somebody
            # renamed a console.
            placer = placement.Placer('default', placement.Placements(), reg,
                                       drivers.DEFAULT)
            names = sorted(placer.name_of(one) for one in stored)
            check("both were stored", len(stored), 2)
            check("the announced one resolves to its name, not its identity",
                  "kirchdorf" in names, True)
            check("the stranger to whatever it called itself",
                  sender_id("wunderground", "KSTRANGER") in names, True)
            check("and the stranger is on the list",
                  [s.identity for s in seen.waiting()], ["KSTRANGER"])
            check("the announced one is not",
                  seen.find("wunderground", "evo-3f9a2c"), None)
        finally:
            live.close()


def indoor_is_the_places_answer() -> None:
    """The journal stays raw; each place decides whether indoor belongs."""
    print("\nindoor readings are left out when the place says so")
    with tempfile.TemporaryDirectory() as raw:
        live = LiveStore(Path(raw) / "live.sdb", interval_seconds=60)
        try:
            reg = stations.Register()
            reg.add(stations.Station("inside", "wunderground", "evo-in"))
            reg.add(stations.Station("outside", "wunderground", "evo-out"))
            ingest = Ingest(live, token=None, default_driver="wunderground",
                            stations=reg, sightings=Sightings(live))

            body = (b"ID=%s&action=updateraw&dateutc=now&tempf=68.4"
                    b"&indoortempf=70.1&indoorhumidity=48")
            ingest.submit(body % b"evo-in", "/wunderground/", "1.2.3.4")
            ingest.submit(body % b"evo-out", "/wunderground/", "1.2.3.4")

            # Both packets are stored whole -- the indoor reading of the
            # console that does not want it recorded is in the table, which
            # is what makes turning the setting back on a rebuild rather
            # than a week of measurements nobody kept.
            raws = list(live.packets(0, 2_000_000_000))
            check("both consoles sent their indoor reading",
                  [("indoortempf" in one.data) for one in raws], [True, True])
            inside = sender_id("wunderground", "evo-in")
            outside = sender_id("wunderground", "evo-out")
            archive = archive_defs.Archive(
                "default", "default.sdb", stations=(inside, outside),
                members={outside: archive_defs.MemberPolicy(indoor=False)})
            placer = placement.Placer(archive, placement.Placements(), reg)
            stored = {}
            for one in raws:
                placed = placer.place(one)
                if placed is not None:
                    stored[placed.source] = placed
            check("the one that wants them has them",
                  stored[inside].data.get("inTemp"), 70.1)
            check("the one that does not, does not",
                  "inTemp" in stored[outside].data, False)
            check("and its outdoor reading is untouched",
                  stored[outside].data.get("outTemp"), 68.4)
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
                  stored[0].identity, "KTEST")
        finally:
            live.close()


def only_sender_clocks_reach_the_driver() -> None:
    """Legacy field maps stop at the explicit Place migration boundary."""
    print("\nonly sender clocks reach the listener driver")
    from weewx_evo import cli
    from weewx_evo import options as option_defs
    from weewx_evo.settings import Settings

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        config_path = work / "evo.toml"
        config_path.write_text("", encoding="utf-8")
        register = stations.Register(stations=[
            stations.Station("clocked", "ecowitt", "AAAA", max_behind=1800),
            stations.Station("plain", "ecowitt", "BBBB"),
        ])
        stations.save(work / "stations.toml", register)
        schema = option_defs.Schema(
            name="core", label="core", groups=tuple(option_defs.core_options()))
        cfg = Settings(schema, config={"live_db": str(work / "live.sdb")},
                       path=config_path)

        cli.configure_drivers(cfg, placements=placement.Placements())
        configured = drivers.get("ecowitt")
        clocked = configured.stations.get("aaaa") or {}
        check("the sender-specific clock tolerance remains",
              clocked.get("max_behind"), 1800)
        # Placement is read when a record is built, so nothing about a
        # column reaches the driver -- the listener stores raw names.
        check("no field placement is injected",
              "field_map_extensions" in clocked, False)
        check("and a console with nothing to say about its clock gets no entry",
              "bbbb" in configured.stations, False)


def the_live_database_schema_default() -> None:
    """The Admin and process schema resolve an omitted live_db identically."""
    print("\nthe sender page follows the live database schema default")
    import os

    from weewx_evo import adminstations

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "data").mkdir()
        expected = work / "data" / "live.sdb"
        LiveStore(expected).close()

        class BareAdmin:
            path = work / "evo.toml"

            @staticmethod
            def config():
                return {}

        names = ("WEEWX_EVO_LIVE", "WEEWX_EVO_LIVE_DB")
        previous = {name: os.environ.get(name) for name in names}
        try:
            for name in names:
                os.environ.pop(name, None)
            check("an omitted setting means data/live.sdb",
                  adminstations.live_db(BareAdmin()), expected)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


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
        # Place membership is a relation to the canonical live sender, never
        # a setting owned by the sender page.
        (tmp / "archives.toml").write_text(
            "[archives.default]\n"
            f'file = "{(tmp / "default.sdb").as_posix()}"\n'
            'senders = []\n\n'
            "[archives.roof]\n"
            f'file = "{(tmp / "roof.sdb").as_posix()}"\n'
            'senders = []\n',
            encoding="utf-8")
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
            status, body = get(f"{base}/senders")
            check("the page is there", status, 200)
            check("and the stranger is on it", "STRANGER1" in body, True)
            check("the page consistently calls them senders",
                  ("<h2>Senders</h2>" in body, "Add sender" in body),
                  (True, True))
            check("it does not display an archive column",
                  "<th>Place</th>" in body, False)
            check("it does not offer an archive while adopting",
                  'name="archive"' in body, False)
            check("a new sender has an explicit assignment action",
                  "Assign to a Place" in body, True)

            status, body = get(f"{base}/new-sender")
            check("the add page is there", status, 200)
            check("it does not offer an archive while announcing",
                  'name="archive"' in body, False)

            print("\nannouncing one hands out an identity to copy over")
            status, body = post(f"{base}/new-sender",
                                {"name": "garden", "driver": "wunderground"})
            check("it answers with what to enter", status, 200)
            check("naming the console", "garden" in body, True)
            check("and the identity it was given", "evo-" in body, True)
            check("with the upload token to type in",
                  ("u" * 32) in body, True)

            # Assignment is configured on the Place, then reflected here as
            # a read-only link back to that authority.
            from dataclasses import replace

            named = stations.load(tmp / "stations.toml").by_name("garden")
            places = archive_defs.Register.load(tmp / "archives.toml")
            current = places.get("default")
            canonical = sender_id(named.driver, named.identity)
            places.replace("default", replace(
                current, stations=(canonical,),
                members={canonical: archive_defs.MemberPolicy()}))
            places.save()
            _, assigned_page = get(f"{base}/senders")
            check("a Place-owned assignment is shown",
                  (">default</a>" in assigned_page,
                   "./places?open=default#place-members-default"
                   in assigned_page), (True, True))

            print("\nadopting the stranger")
            status, _ = post(f"{base}/senders/adopt",
                             {"driver": "ecowitt", "identity": "STRANGER1",
                              "name": "roof"})
            check("it redirects rather than rendering", status, 303)

            _, body = get(f"{base}/senders")
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
            check("the console page does not own a member role",
                  'name="role"' in body, False)
            check("or the place-specific indoor decision",
                  'name="indoor"' in body, False)
            garden_sender = sender_id("wunderground",
                                      register.by_name("garden").identity)
            check("the canonical ID is secondary and read-only",
                  ("<summary>Technical ID</summary>" in body,
                   garden_sender in body), (True, True))

            # Old bookmarks or hand-written POSTs cannot put the policy back
            # on the console. Only clock tolerances are accepted here; the
            # place form owns these values now.
            status, _ = post(f"{base}/senders/garden/set", {
                "role": "extra", "channel": "4", "indoor": ""})
            check("an obsolete policy post still redirects", status, 303)
            untouched = stations.load(tmp / "stations.toml").by_name("garden")
            check("and cannot restore station-owned policy fields",
                  tuple(hasattr(untouched, name)
                        for name in ("role", "channel", "indoor")),
                  (False, False, False))

            print("\na name already taken is refused, and says so")
            status, body = post(f"{base}/new-sender",
                                {"name": "garden", "driver": "wunderground"})
            check("the page comes back", status, 200)
            check("saying what is wrong", "already a sender" in body, True)
            check("and nothing was added",
                  len(stations.load(tmp / "stations.toml")), 2)

            print("\nwhat a station sends, and the upload behind it")
            # The reason this is on the page: a field with no column is
            # dropped at every archive interval, and until now it said so
            # only in a log line and a file in /var/tmp.
            from weewx_evo import adminstations
            from weewx_evo.db.live import Packet

            live2 = LiveStore(tmp / "live.sdb", interval_seconds=60)
            # Keyed on the pair the console uploads with, which is what
            # the page looks the row up by, and under the names the
            # console used -- a placement is a decision about `tempf`.
            garden = stations.load(tmp / "stations.toml").by_name("garden")
            live2.add(Packet(
                dateTime=1787800000, usUnits=1, driver=garden.driver,
                identity=garden.identity, dialect="wunderground",
                mapping={"version": 1, "usUnits": 1,
                         "fields": {"tempf": "outTemp"},
                         "metadata": [], "contested": [], "scale": {},
                         "absent": [], "groups": {}},
                data={"tempf": 68.4, "somethingNew": 1.5},
                raw="ID=evo-x&PASSWORD=[redacted]&tempf=68.4&somethingNew=1.5"))
            live2.close()

            station = stations.load(tmp / "stations.toml").by_name("garden")
            old_load = drivers.DEFAULT.load
            old_get = drivers.get

            def forbidden(*_args, **_kwargs):
                raise AssertionError("driver registry used after ingest")

            drivers.DEFAULT.load = forbidden
            drivers.get = forbidden
            try:
                found = adminstations.what_it_sends(admin, station)
            finally:
                drivers.DEFAULT.load = old_load
                drivers.get = old_get
            check("it knows what arrived",
                  found.get("sent"), ["somethingNew", "tempf"])
            check("the stored mapping describes it without the driver",
                  found.get("catalog"), {"tempf": "outTemp"})
            check("and keeps the upload to hand on",
                  "somethingNew=1.5" in found.get("raw", ""), True)
            check("with the secret already out of it",
                  "[redacted]" in found.get("raw", ""), True)
            _, sender_page = get(f"{base}/senders")
            check("sender details stay read-only about Place fields",
                  ('name="place:' in sender_page
                   or 'action="./senders/garden/fields"' in sender_page),
                  False)
            check("but the raw diagnosis is available",
                  "somethingNew" in sender_page, True)

            print("\nremoving one")
            status, _ = post(f"{base}/senders/roof/remove", {})
            check("redirects", status, 303)
            check("and it is gone",
                  stations.load(tmp / "stations.toml").by_name("roof"), None)
        finally:
            server.stop()


def main() -> int:
    drivers.DEFAULT.load()
    the_register()
    the_identity_we_hand_out()
    the_file()
    the_sightings()
    an_upload_from_each()
    nothing_announced_changes_nothing()
    indoor_is_the_places_answer()
    the_settings_page()
    only_sender_clocks_reach_the_driver()
    the_live_database_schema_default()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("stations are announced, strangers are noticed, neither is guessed at")
    return 0


if __name__ == "__main__":
    sys.exit(main())

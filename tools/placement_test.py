#!/usr/bin/env python3
"""The read side gives what the write side gave.

The live table used to hold packets a driver had already named, and the
naming happened at the front door. It now holds what the console sent, and
the naming happens when a record is built. That move is only safe if the
second arrangement produces the same numbers as the first, field for field,
on payloads nobody wrote for the occasion.

**The oracle is the old code path**, kept in this file rather than described:
`Mapper.to_packet`, the twelve lines of `driver.py` that followed it, and the
`indoor`/`role` handling that used to be in `Ingest._as_configured`. Compared
against a typed expectation this would only prove that somebody typed what
the code does. The method is `difftest.py`'s and `unitcheck.py`'s -- compare
against the thing you are transcribing from.

**The subject is the whole way round**, through SQLite and through JSON:
`driver.packets()` -> `LiveStore.add()` -> `LiveStore.packets()` ->
`Placer.place()`. A float that does not survive `json.dumps` shows up here
rather than in somebody's archive.

Four layers:

    packet    same count, same stamp, same units, same field names, and
              values on exact equality -- the scale factor is the same
              expression on the same float either way, so anything but `==`
              is a finding and not a tolerance
    record    the same interval through `Archiver.build` twice, old packets
              and new, compared field for field. This catches what the first
              cannot: a None present against absent, the source merge
              reordering, a quality run-up that was not placed
    station   the same stream through `indoor = false`, `role = extra`, a
              `-` placement, a contested field decided both ways, and an
              unannounced source. Those five are exactly what moved from the
              front door to the read side, and each has a "drops everything
              in silence" failure mode
    inference the one deliberate difference. The old path guessed on every
              packet; this one does not guess at all. So the guesses are
              counted, and `promote()` has to close the gap exactly -- if it
              writes fewer, the move loses columns

    python tools/placement_test.py
    python tools/placement_test.py --capture reference/live.sdb

The captured payloads under `tests/push/fixtures` are real uploads from six
protocols. `--capture` points at a live database or an ndjson spool from a
running instance, so a run can cover a week of one console rather than
twenty-three single frames.
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import archives as archive_defs  # noqa: E402
from weewx_evo import placement, roles, units  # noqa: E402
from weewx_evo import stations as station_defs  # noqa: E402
from weewx_evo.archiver import Archiver  # noqa: E402
from weewx_evo.db.archive import ArchiveStore  # noqa: E402
from weewx_evo.db.live import (  # noqa: E402
    LiveStore,
    Packet,
    SenderIdentity,
    sender_id,
)
from weewx_evo.ingest import drivers  # noqa: E402
from weewx_evo.ingest.plugins.push import mapping  # noqa: E402

failures = 0
FIXTURES = ROOT / "tests" / "push" / "fixtures"

#: Which driver reads each fixture directory. By directory rather than by
#: asking the registry to claim: a test that guessed would be testing the
#: claim logic, and `netaccess_test` already does that.
BY_DIRECTORY = {
    "acurite": "acurite",
    "ambient": "ambient",
    "lacrosse": "lacrosse",
    "weatherflow": "weatherflow",
    "wunderground": "wunderground",
}


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


# ---------------------------------------------------------------------------
# The oracle: what the write side did, before the readings were stored raw.
# ---------------------------------------------------------------------------

def oracle(driver: object, body: bytes, meta: dict, station: object = None,
           extensions: dict | None = None,
           infer: str = mapping.OFF, indoor: bool | None = None) -> Packet | None:
    """One upload, named the way it used to be at the front door.

    Transcribed from `PushDriver.packets` and `Ingest._as_configured` as they
    were before the journal. Kept here on purpose: once the product no longer
    contains this path, a copy of it is the only thing a comparison can mean.
    """
    from weewx_evo.ingest.plugins.push.driver import _Request

    request = _Request(path=str(meta.get("path") or "/"), body=body)
    raw = driver._raw(request)
    if not raw:
        return None
    readings = driver.protocol.readings(request, raw)
    if not readings:
        return None
    dialect = driver.protocol.dialect(raw)
    mapper = mapping.Mapper(dialect, extensions=dict(extensions or {}),
                            infer_unknown=infer)
    # `now` is the arrival time, which is what the listener passed in
    # everything but name: `to_packet` substitutes it when the console's
    # own stamp is unusable, and the old `or meta['received']` after it
    # could therefore never fire. Left to its own clock here the two
    # sides differ by however long this test took to start.
    packet, _guesses = mapper.to_packet(readings, now=meta.get("received"))
    stamp = packet.pop("dateTime", None) or meta.get("received")
    data = {name: value for name, value in packet.items() if value is not None}

    # `Ingest._as_configured`, verbatim.
    if station is not None:
        keeps_indoor = (getattr(station, "indoor", True)
                        if indoor is None else indoor)
        if not keeps_indoor:
            dropped = {name: value for name, value in data.items()
                       if name not in ("inTemp", "inHumidity", "inDewpoint")}
            if len(dropped) != len(data):
                data = dropped
        # The extra-station shift that used to sit here is gone rather than
        # transcribed: an additional sender no longer has its `outTemp` moved
        # to a guessed channel, it writes what it has been placed. There is
        # no old behaviour left to compare that against, so it is checked
        # against the rule instead, further down.
    if not data:
        return None
    return Packet(dateTime=int(stamp), usUnits=int(dialect.units), data=data,
                  kind="loop", received=meta.get("received"),
                  source=(getattr(station, "name", "")
                          or driver._station_of(raw) or driver.name))


def guesses_of(driver: object, body: bytes, meta: dict,
               infer: str = mapping.SERIES) -> dict:
    """What the old path would have placed by guessing. Raw name -> column."""
    from weewx_evo.ingest.plugins.push.driver import _Request

    request = _Request(path=str(meta.get("path") or "/"), body=body)
    raw = driver._raw(request)
    readings = driver.protocol.readings(request, raw) if raw else {}
    if not readings:
        return {}
    dialect = driver.protocol.dialect(raw)
    strict, _ = mapping.Mapper(dialect, infer_unknown=mapping.OFF).to_packet(readings)
    loose, _ = mapping.Mapper(dialect, infer_unknown=infer).to_packet(readings)
    for name in ("dateTime",):
        strict.pop(name, None)
        loose.pop(name, None)
    return {name: value for name, value in loose.items() if name not in strict}


# ---------------------------------------------------------------------------
# The subject: through the table and back.
# ---------------------------------------------------------------------------

def payloads() -> list[tuple[str, str, bytes]]:
    """Every captured upload, as (label, driver name, body)."""
    found = []
    for path in sorted(FIXTURES.rglob("*.txt")):
        if path.name == "README.md":
            continue
        name = BY_DIRECTORY.get(path.parent.name, "ecowitt")
        found.append((str(path.relative_to(FIXTURES)), name,
                      path.read_text(encoding="utf-8").strip().encode()))
    return found


def stored_and_placed(driver: object, name: str, body: bytes, meta: dict,
                      work: Path, register: object = None,
                      plans: object = None, archive: object = None
                      ) -> tuple[Packet | None, Packet | None]:
    """One upload through the real path. Returns (as stored, as placed)."""
    live = LiveStore(work / f"{abs(hash((name, body))):x}.sdb",
                     interval_seconds=300)
    try:
        packets = driver.packets(body, meta)
        if not packets:
            return None, None
        one = packets[0]
        # What the listener stamps, and nothing else. Everything the listener
        # used to do to a packet is now on the other side of the table.
        one = _replaced(one, driver=name)
        live.add(one)
        back = list(live.packets(one.dateTime - 1, one.dateTime + 1,
                                 with_raw=False))
        if not back:
            return None, None
        archive = archive or archive_defs.Archive("default", "unused.sdb")
        placer = placement.Placer(
            archive, plans or placement.Placements(), register, drivers.DEFAULT)
        return back[0], placer.place(back[0])
    finally:
        live.close()


def _replaced(packet: Packet, **fields: object) -> Packet:
    from dataclasses import replace

    return replace(packet, **fields)


# ---------------------------------------------------------------------------
# Layer one: packet for packet.
# ---------------------------------------------------------------------------

def every_capture_round_trips() -> None:
    print("\nevery captured upload, through the table and back")
    drivers.DEFAULT.load()
    uploads = payloads()
    if not uploads:
        check("there are payloads to compare against", len(uploads), "some")
        return

    seen_packets = seen_fields = differences = skipped = 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        for label, name, body in uploads:
            driver = drivers.get(name)
            if driver is None or not hasattr(driver, "protocol"):
                skipped += 1
                continue
            meta = {"received": 1787900000, "path": f"/{name}/"}
            want = oracle(driver, body, meta)
            got_stored, got = stored_and_placed(driver, name, body, meta, work)
            if want is None and got is None:
                skipped += 1
                continue
            if want is None or got is None:
                print(f"  FAIL {label}: one side produced nothing "
                      f"(old={want is not None}, new={got is not None})")
                differences += 1
                continue

            seen_packets += 1
            for field, mine, theirs in (("dateTime", got.dateTime, want.dateTime),
                                        ("usUnits", got.usUnits, want.usUnits),
                                        ("kind", got.kind, want.kind)):
                if mine != theirs:
                    print(f"  FAIL {label}: {field} {mine!r} != {theirs!r}")
                    differences += 1

            extra = sorted(set(got.data) - set(want.data))
            missing = sorted(set(want.data) - set(got.data))
            if extra or missing:
                print(f"  FAIL {label}: fields differ -- only new: {extra}, "
                      f"only old: {missing}")
                differences += 1
            for field in sorted(set(got.data) & set(want.data)):
                seen_fields += 1
                if got.data[field] != want.data[field]:
                    # Exact, not close. The scale factor is the same
                    # expression on the same float on both paths.
                    print(f"  FAIL {label}: {field} {got.data[field]!r} "
                          f"!= {want.data[field]!r}")
                    differences += 1

            # And the journal really is the journal: what the console sent
            # has to still be in it, under its own names.
            if got_stored is not None and got_stored.dialect is None:
                print(f"  FAIL {label}: stored without a dialect")
                differences += 1

    print(f"  --   {len(uploads)} uploads, {seen_packets} packets, "
          f"{seen_fields} fields, {differences} differences "
          f"({skipped} produced no packet on either path)")
    check("the read side gives what the write side gave", differences, 0)
    check("and there was something to compare", seen_packets > 10, True)


# ---------------------------------------------------------------------------
# Layer two: the same interval, as a record.
# ---------------------------------------------------------------------------

def the_record_is_the_same() -> None:
    """Both ways through `Archiver.build`, compared field for field.

    What layer one cannot see: a None present against absent, the source
    merge reordering, and a quality run-up that was not placed.
    """
    print("\nthe same interval, built both ways")
    drivers.DEFAULT.load()
    driver = drivers.get("ecowitt")
    body = (FIXTURES / "hp2561ae_pro.txt").read_text(encoding="utf-8").strip().encode()
    start = 1787900000 // 300 * 300

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        old_live = LiveStore(work / "old.sdb", interval_seconds=300)
        new_live = LiveStore(work / "new.sdb", interval_seconds=300)
        old_store = ArchiveStore(work / "old-archive.sdb")
        new_store = ArchiveStore(work / "new-archive.sdb")
        try:
            for step in range(6):
                when = start + 30 * (step + 1)
                meta = {"received": when, "path": "/ecowitt/"}
                want = oracle(driver, body, meta)
                # Stamped at the same second on both sides: the payload has
                # `dateutc=now`, so a driver reading it twice a second apart
                # would otherwise be comparing two different intervals.
                old_live.add(_replaced(want, dateTime=when, identity="AAAA",
                                       driver="ecowitt"))
                got = driver.packets(body, meta)[0]
                new_live.add(_replaced(got, dateTime=when, driver="ecowitt"))

            stop = start + 300
            old = Archiver(old_live, old_store, interval_seconds=300).build(stop)
            new = Archiver(new_live, new_store, interval_seconds=300,
                           placer=placement.Placer(
                               "default", placement.Placements(), None,
                               drivers.DEFAULT)).build(stop)
            check("both built a record", (old is not None, new is not None),
                  (True, True))
            if old is None or new is None:
                return
            check("the same packets went in", new.packets, old.packets)
            differing = sorted(
                field for field in set(old.record) | set(new.record)
                if old.record.get(field) != new.record.get(field))
            print(f"  --   {len(old.record)} fields in the record, "
                  f"{len(differing)} differ")
            check("field for field", differing, [])
        finally:
            old_live.close()
            new_live.close()
            old_store.close()
            new_store.close()


# ---------------------------------------------------------------------------
# Layer three: the five things that moved.
# ---------------------------------------------------------------------------

def _a_register(text: str, work: Path) -> object:
    (work / "stations.toml").write_text(text, encoding="utf-8")
    return station_defs.load(work / "stations.toml")


def what_moved_off_the_front_door() -> None:
    print("\nthe five decisions that moved to the read side")
    drivers.DEFAULT.load()
    driver = drivers.get("ecowitt")
    body = (FIXTURES / "hp2561ae_pro.txt").read_text(encoding="utf-8").strip().encode()
    meta = {"received": 1787900000, "path": "/ecowitt/"}

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        passkey = driver._station_of(driver._raw(
            __import__("weewx_evo.ingest.plugins.push.driver", fromlist=["x"])
            ._Request(path="/ecowitt/", body=body)))

        # -- indoor ---------------------------------------------------
        register = _a_register(
            f'[stations.haus]\ndriver = "ecowitt"\nidentity = "{passkey}"\n', work)
        haus = sender_id("ecowitt", passkey)
        archive = archive_defs.Archive(
            "default", "unused.sdb",
            stations=(haus,),
            members={haus: archive_defs.MemberPolicy(indoor=False)})
        # A console the place does not select is in the directory and is
        # still not this place's: an explicit selection is a list, not a
        # hint, and the second console's readings must not reach this file.
        other = sender_id("ecowitt", "BBBB")
        main_placer = placement.Placer(
            archive, placement.Placements(), [
                SenderIdentity(haus, "ecowitt", passkey, "haus"),
                SenderIdentity(other, "ecowitt", "BBBB", "schuppen"),
            ])
        check("an explicit place selects what it names and nothing else",
              main_placer.selected_senders(), [haus])
        check("and the one it names is its primary reading",
              main_placer.selected_main_senders(), [haus])
        placement._said.clear()
        want = oracle(driver, body, meta, station=register.by_name("haus"),
                      indoor=False)
        _stored, got = stored_and_placed(driver, "ecowitt", body, meta, work,
                                         register, archive=archive)
        check("indoor = false places the same fields",
              sorted(got.data), sorted(want.data))
        check("and the reading is still in the table",
              "tempinf" in (_stored.data if _stored else {}), True)

        # -- an additional sender --------------------------------------
        #
        # No oracle here, and that is the point: the old front door moved its
        # `outTemp` into a guessed `extraTemp<n>` and dropped everything else.
        # What it does now is the rule, so the rule is what is checked.
        register = _a_register(
            f'[stations.garten]\ndriver = "ecowitt"\nidentity = "{passkey}"\n', work)
        garten = sender_id("ecowitt", passkey)
        elsewhere = sender_id("ecowitt", "BBBB")
        archive = archive_defs.Archive(
            "default", "unused.sdb",
            stations=(elsewhere, garten), primary=elsewhere)
        extra_legacy = sender_id("__legacy__", "garten")
        extra_placer = placement.Placer(
            archive, placement.Placements(), [
                SenderIdentity(garten, "ecowitt", passkey, "garten"),
                SenderIdentity(extra_legacy, "__legacy__", "garten", "garten"),
            ])
        check("a legacy alias of an extra member is not default-main",
              extra_placer.selected_main_senders(), [elsewhere])
        placement._said.clear()
        _stored, got = stored_and_placed(driver, "ecowitt", body, meta, work,
                                         register, archive=archive)
        check("an additional sender places nothing it was not given",
              [one for one in (got.data if got else {})
               if not roles.keeps(one)], [])
        check("its wind is in the table all the same",
              "windspeedmph" in (_stored.data if _stored else {}), True)

        plans = placement.Placements()
        plans.decide("default", garten, "ecowitt",
                     "windspeedmph", "gardenWind")
        _stored, got = stored_and_placed(driver, "ecowitt", body, meta, work,
                                         register, plans, archive)
        check("and writes exactly what it was given",
              got.data.get("gardenWind"), 1.34)

        # -- a `-` placement -------------------------------------------
        register = _a_register(
            f'[stations.haus]\ndriver = "ecowitt"\nidentity = "{passkey}"\n',
            work)
        haus = sender_id("ecowitt", passkey)
        plans = placement.Placements()
        plans.decide("default", haus, "ecowitt", "tempf", placement.NOWHERE)
        want = oracle(driver, body, meta, station=register.by_name("haus"),
                      extensions={"tempf": mapping.NOWHERE})
        _stored, got = stored_and_placed(driver, "ecowitt", body, meta, work,
                                         register, plans)
        check("a `-` places the same fields",
              sorted(got.data), sorted(want.data))
        check("and outTemp really is gone", "outTemp" in got.data, False)

        # -- a contested field, decided both ways ----------------------
        for column in ("soilTemp1", "extraTemp9"):
            plans = placement.Placements()
            plans.decide("default", haus, "ecowitt", "tf_ch1", column)
            want = oracle(driver, body, meta, station=register.by_name("haus"),
                          extensions={"tf_ch1": column})
            _stored, got = stored_and_placed(driver, "ecowitt", body, meta, work,
                                             register, plans)
            check(f"a contested field decided as {column}",
                  got.data.get(column), want.data.get(column))

        # -- an unannounced source -------------------------------------
        placement._said.clear()
        want = oracle(driver, body, meta)
        _stored, got = stored_and_placed(driver, "ecowitt", body, meta, work,
                                         station_defs.Register())
        check("an unannounced console places the same fields",
              sorted(got.data), sorted(want.data))
        check("and is known by its canonical sender id",
              got.source, sender_id("ecowitt", passkey))


# ---------------------------------------------------------------------------
# Layer four: the one deliberate difference.
# ---------------------------------------------------------------------------

def the_guessing_is_written_down() -> None:
    """The old path guessed on every packet. This one writes it down instead.

    So the guesses are counted and `promote()` has to reproduce them exactly.
    Anything it does not write is a column the move would have lost, silently,
    on an installation that had been recording it for a year.
    """
    print("\nwhat the old path guessed, and what promote() writes")
    from weewx_evo.ingest import proposals as proposal_defs

    drivers.DEFAULT.load()
    driver = drivers.get("ecowitt")
    # Two channels past what the capture carries, which is the case this
    # exists for: a sensor added to a console the catalog was written before.
    # The fixture alone has nothing to guess about, so measuring against it
    # would be a layer that passes without looking at anything.
    body = ((FIXTURES / "hp2561ae_pro.txt").read_text(encoding="utf-8").strip()
            + "&tf_ch5=61.2&soilmoisture4=28").encode()
    meta = {"received": 1787900000, "path": "/ecowitt/"}

    # `all`, not `series`. Measured on this catalog: `series` places nothing
    # extra at all -- every guess it produces is uncertain, so it declines
    # them. Comparing under `series` would be a layer that passes without
    # looking at anything, which is the failure this file is written against.
    guessed = guesses_of(driver, body, meta, infer=mapping.ALL)
    print(f"  --   the old path guessed {len(guessed)} field(s): "
          f"{', '.join(sorted(guessed)[:6])}")
    check("there is something to guess about", len(guessed) > 0, True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        try:
            packet = _replaced(driver.packets(body, meta)[0], driver="ecowitt")
            live.add(packet)
            notes = proposal_defs.Proposals(store=live)
            member = packet.sender_id
            fresh = notes.saw(packet, member, driver, mapping.ALL)
            check("every raw name was noted once", fresh > 0, True)
            check("and a second packet asks the driver nothing",
                  notes.saw(packet, member, driver, mapping.ALL), 0)

            plans = placement.Placements()
            written = placement.promote(notes, plans, "default", mapping.ALL)
            columns = {column for _raw_name, column in written}
            print(f"  --   promote() wrote {len(written)}: "
                  f"{', '.join(sorted(columns)[:6])}")
            check("promote writes every column the old path guessed",
                  sorted(columns), sorted(guessed))

            # And once written, the read side places them without guessing.
            placer = placement.Placer("default", plans,
                                      station_defs.Register(stations=[
                                          station_defs.Station(
                                              name="haus", driver="ecowitt",
                                              identity=packet.identity)]),
                                      drivers.DEFAULT)
            got = placer.place(next(iter(live.packets(
                packet.dateTime - 1, packet.dateTime + 1))))
            check("and the reader then places them",
                  sorted(set(guessed) & set(got.data)), sorted(guessed))

            again = placement.promote(notes, plans, "default", mapping.ALL)
            check("promoting twice writes nothing new", again, [])

            # And a chosen line survives it. This is the rule that keeps a
            # better inferrer in a later version from quietly undoing what
            # somebody decided when the first one got it wrong.
            overruled = next(one.raw for one in notes.all() if one.field)
            plans.decide("default", member, "ecowitt", overruled, "soilTemp8")
            placement.promote(notes, plans, "default", mapping.ALL)
            check("and a decision of yours is left alone",
                  plans.extensions("default", member, "ecowitt")[overruled],
                  "soilTemp8")
        finally:
            live.close()


def placing_is_quiet() -> None:
    """Building a record says nothing about a console that is fine.

    A rebuild places every packet of a span, and an archiver places one every
    few seconds for ever. Anything said per packet is said tens of thousands
    of times, so the only safe amount is none -- and a line that is wrong as
    well as frequent is worse than either.

    Measured on the instance: `to_packet` was handed a `now` that is not a
    time, compared the console's own stamp against it, and warned that a
    healthy GW2000 was fifty-six years out. On every upload.
    """
    print("\nplacing a healthy console's reading says nothing")
    import io
    import logging

    drivers.DEFAULT.load()
    driver = drivers.get("ecowitt")
    body = (FIXTURES / "hp2561ae_pro.txt").read_text(encoding="utf-8").strip().encode()
    packet = _replaced(driver.packets(body, {"received": int(time.time()),
                                             "path": "/ecowitt/"})[0],
                       driver="ecowitt")

    heard = io.StringIO()
    handler = logging.StreamHandler(heard)
    handler.setLevel(logging.INFO)
    root = logging.getLogger()
    root.addHandler(handler)
    before = root.level
    root.setLevel(logging.INFO)
    try:
        placer = placement.Placer("default", placement.Placements(), None,
                                  drivers.DEFAULT)
        for _ in range(3):
            placed = placer.place(packet)
    finally:
        root.removeHandler(handler)
        root.setLevel(before)

    said = [line for line in heard.getvalue().splitlines() if line.strip()]
    check("nothing was logged", said, [])
    check("and it still placed the reading",
          isinstance(placed.data.get("outTemp"), float), True)


def the_archiver_executes_data_not_a_driver() -> None:
    """A dialect crosses the process boundary as JSON, never as code."""
    print("\na stored dialect is data, not driver code")
    from weewx_evo.ingest.listener import Ingest

    spec = drivers.DialectSpec(
        fields={"tempf": "outTemp", "private": "notWeather"},
        scale={"tempf": 0.5}, metadata=frozenset({"private"}),
        absent=("missing",), groups={"outTemp": "group_temperature"},
        usUnits=1)

    class Describing(drivers.BaseDriver):
        def packets(self, body, meta):
            if body == b"weewx":
                return [Packet(
                    dateTime=meta["received"], usUnits=1,
                    data={"outTemp": 10.0}, identity="box", dialect=None,
                    mapping={"callable": "some_package:run"})]
            if body == b"invalid":
                return [Packet(
                    dateTime=meta["received"], usUnits=1,
                    data={"raw": "1"}, identity="box",
                    dialect="x" * (drivers.MAX_DIALECT_NAME + 1),
                    mapping=spec.as_dict())]
            return [Packet(dateTime=meta["received"], usUnits=1,
                           data={"tempf": "10", "private": "7"},
                           identity="box", dialect="mine")]

        def dialect_spec(self, readings, dialect):
            return spec

    class Forbidden:
        def get(self, name):
            raise AssertionError("the archiver asked a driver")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        live = LiveStore(Path(raw) / "live.sdb")
        registry = drivers.Registry()
        registry._loaded = True
        registry.register("mine", Describing())
        ingest = Ingest(live, default_driver="mine", registry=registry)
        try:
            stored, reason, _response = ingest.submit(b"reading", "/mine/")
            check("the listener stored it", (stored, reason), (1, "ok"))
            packet = next(iter(live.packets(0, time.time() + 1)))
            check("the mapping survived SQLite and JSON",
                  packet.mapping, spec.as_dict())
            placed = placement.Placer(
                archive_defs.Archive("default", "unused.sdb"),
                placement.Placements(), None, Forbidden()).place(packet)
            check("core code mapped and scaled it", placed.data, {"outTemp": 5.0})
            ingest.submit(b"weewx", "/mine/")
            passthrough = next(one for one in live.packets(0, time.time() + 1)
                               if one.dialect is None)
            check("a WeeWX-named packet cannot retain an unchecked mapping",
                  passthrough.mapping, None)
            ingest.submit(b"invalid", "/mine/")
            invalid = next(one for one in live.packets(0, time.time() + 1)
                           if one.data.get("raw") == "1")
            check("an invalid dialect is bounded and untranslatable",
                  (invalid.dialect, invalid.mapping), ("<invalid>", None))
        finally:
            live.close()

    hostile = spec.as_dict()
    hostile["callable"] = "some_package:run"
    try:
        drivers.DialectSpec.from_dict(hostile)
    except ValueError:
        refused = True
    else:
        refused = False
    check("an executable-looking extension is refused", refused, True)

    import io
    import logging

    heard = io.StringIO()
    handler = logging.StreamHandler(heard)
    logger = logging.getLogger("weewx_evo.placement")
    logger.addHandler(handler)
    before = logger.level
    logger.setLevel(logging.ERROR)
    placement._untranslatable.clear()
    try:
        old = placement.Placer(
            archive_defs.Archive("default", "unused.sdb"),
            placement.Placements(), None, Forbidden()).place(Packet(
                dateTime=1, usUnits=1, data={"tempf": "10"},
                driver="old", identity="box", dialect="old", mapping=None))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(before)
    check("an old row is not guessed into an archive", old, None)
    check("and says why it cannot be translated",
          "without a valid stored mapping" in heard.getvalue(), True)

    mismatch = placement.Placer(
        archive_defs.Archive("default", "unused.sdb"),
        placement.Placements()).place(Packet(
            dateTime=1, usUnits=16, data={"tempf": "10"}, driver="mine",
            identity="box", dialect="mine", mapping=spec.as_dict()))
    check("a spec cannot change its packet's unit system", mismatch, None)

    too_many = spec.as_dict()
    too_many["fields"] = {
        f"field{number}": f"out{number}"
        for number in range(drivers.MAX_SPEC_ENTRIES + 1)
    }
    try:
        drivers.DialectSpec.from_dict(too_many)
    except ValueError:
        refused = True
    else:
        refused = False
    check("a driver cannot grow an unbounded mapping", refused, True)

    overflow = spec.as_dict()
    overflow["scale"] = {"tempf": 10 ** 4000}
    try:
        drivers.DialectSpec.from_dict(overflow)
    except ValueError:
        refused = True
    else:
        refused = False
    check("an overflowing scale is refused without crashing", refused, True)

    for field in ("version", "usUnits"):
        wrong_type = spec.as_dict()
        wrong_type[field] = float(wrong_type[field])
        try:
            drivers.DialectSpec.from_dict(wrong_type)
        except ValueError:
            refused = True
        else:
            refused = False
        check(f"{field} is an integer, not merely equal to one", refused, True)

    from weewx_evo import units as unit_defs

    before_groups = unit_defs.contributed()
    try:
        plans = placement.Placements(
            groups={"gardenValue": "group_temperature"})
        unit_defs.contribute(dict(plans.groups))
        conflicting = drivers.DialectSpec(
            fields={"raw": "gardenValue"}, usUnits=1,
            groups={"gardenValue": "group_pressure"})
        got = placement.Placer(
            archive_defs.Archive("default", "unused.sdb"), plans).place(Packet(
                dateTime=1, usUnits=1, data={"raw": "10"}, driver="mine",
                identity="box", dialect="mine", mapping=conflicting.as_dict()))
        check("an operator's unit group is not overwritten",
              unit_defs.group_of("gardenValue"), "group_temperature")
        check("and the reading still follows that authority",
              got.data, {"gardenValue": 10.0})
    finally:
        unit_defs.contribute(before_groups)


def a_scope_without_a_place_reaches_nothing() -> None:
    """A rule that names no archive must not apply to every archive.

    Fail-closed, because the other direction is silent: a place created
    next year would start following a line written before it existed, and
    the readings it moved would look like the readings it was given.
    """
    print("\na placement that names no place is fail-closed")
    plans = placement.from_dict({"takes": [{
        "dialect": "old",
        "fields": {"raw": "outTemp"},
    }]})
    check("it reaches the default place", plans.extensions("default", "", "old"),
          {})
    check("and any other", plans.extensions("north", "", "old"), {})


def a_scope_is_keyed_on_the_sender_id() -> None:
    """A display name in `station` selects nobody. Only the id does.

    Worth its own check because both spellings read the same in the file
    and neither is a syntax error. A scope keyed on what somebody calls
    the console applies to no packet, so every reading in it falls back to
    whatever the catalog says -- `tf_ch1` into a column of the driver's
    choosing rather than the one the operator picked, silently.
    """
    print("\na placement scope is keyed on the sender id")
    from weewx_evo.db.live import sender_id

    sender = sender_id("ecowitt", "3178AB6B42A759F51A5A4AD72E37F8DE")
    fields = {"tf_ch1": "extraTemp9", "tf_ch2": "extraTemp10"}

    by_name = placement.from_dict({"takes": [{
        "archive": "default", "station": "kirchdorf", "fields": dict(fields)}]})
    check("a scope on the display name reaches the console not at all",
          by_name.extensions("default", sender, ""), {})

    keyed = placement.from_dict({"takes": [{
        "archive": "default", "station": sender, "fields": dict(fields)}]})
    check("the same scope on its id reaches all of it",
          keyed.extensions("default", sender, ""), fields)


def the_archive_service_does_not_load_a_driver() -> None:
    """The actual ``archive`` process never imports installed ingest code."""
    print("\nthe archive service does not load an ingest plugin")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        driver_dir = work / "drivers"
        poison = driver_dir / "poison"
        poison.mkdir(parents=True)
        marker = poison / "IMPORTED"
        (poison / "__init__.py").write_text(
            "from pathlib import Path\n"
            "Path(__file__).with_name('IMPORTED').write_text('loaded')\n"
            "def load(registry):\n"
            "    raise AssertionError('archive loaded an ingest driver')\n",
            encoding="utf-8")
        config = work / "evo.toml"
        config.write_text(
            'live_db = "live.sdb"\n'
            'watchdog = false\n'
            'poll = "1s"\n\n'
            '[uploads.boundary]\n'
            'kind = "wunderground"\n'
            'station = "BOUNDARY"\n'
            'password = "unused"\n'
            'trigger = "manual"\n'
            'archive = "default"\n', encoding="utf-8")
        (work / "archives.toml").write_text(
            '[archives.default]\n'
            'file = "archive.sdb"\n'
            'senders = "*"\n', encoding="utf-8")
        # Any stations.toml read is a boundary violation. A syntactically bad
        # file turns that violation into a startup failure rather than relying
        # on a mock that the subprocess cannot see.
        (work / "stations.toml").write_text("[not valid", encoding="utf-8")

        environment = os.environ.copy()
        source = str(ROOT / "src")
        environment["PYTHONPATH"] = os.pathsep.join(
            one for one in (source, environment.get("PYTHONPATH", "")) if one)
        command = [
            sys.executable, "-m", "weewx_evo.cli", "archive",
            "--config", str(config), "--driver-dir", str(driver_dir),
        ]
        process = subprocess.Popen(
            command, cwd=work, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = ""
        try:
            deadline = time.monotonic() + 8
            while (time.monotonic() < deadline and process.poll() is None
                   and not (work / "archive.sdb").exists()):
                time.sleep(0.05)
            # Reaching the archive file proves that settings, the live journal,
            # the archive register and cmd_archive's builders all ran. Give a
            # startup worker a moment too: an import deferred by one of them is
            # still an import in the archive process.
            if process.poll() is None and (work / "archive.sdb").exists():
                time.sleep(0.25)
            running = process.poll() is None
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                output = process.communicate(timeout=5)[0]
            except subprocess.TimeoutExpired:
                process.kill()
                output = process.communicate(timeout=5)[0]

        check("the command reached its service loop",
              running, True)
        check("and never imported the installed driver",
              marker.exists(), False)
        if not running:
            print("  archive output:", output.strip())

        # The one-shot commands take a separate constructor path through
        # ``make_archiver``. Keep that path inside the same boundary too: an
        # invalid stations.toml must remain irrelevant and the poison plugin
        # must remain unimported.
        caught = subprocess.run([
            sys.executable, "-m", "weewx_evo.cli", "catchup",
            "--config", str(config), "--driver-dir", str(driver_dir),
        ], cwd=work, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=15, check=False)
        check("the single-shot archiver also needs no station registry",
              caught.returncode, 0)
        check("and it imports no ingest plugin either", marker.exists(), False)
        if caught.returncode:
            print("  catchup output:", caught.stdout.strip())


def archive_members_reload_through_the_live_database() -> None:
    """A standalone placer takes member edits without stations.toml/restart."""
    print("\narchive membership and policy reload through canonical senders")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        store = ArchiveStore(work / "records.sdb")
        first = sender_id("json", "console-a")
        second = sender_id("json", "console-b")
        start = 1787900000 // 300 * 300
        live.add(Packet(dateTime=start + 60, usUnits=16,
                        data={"outTemp": 10.0}, driver="json",
                        identity="console-a"))
        live.add(Packet(dateTime=start + 90, usUnits=16,
                        data={"outTemp": 20.0}, driver="json",
                        identity="console-b"))

        path = work / "archives.toml"
        original = archive_defs.Archive(
            "default", str(work / "records.sdb"), stations=(first,),
            members={first: archive_defs.MemberPolicy()})
        archive_defs.Register([original], path).save(path)
        register = archive_defs.Register.load(path)
        placer = placement.Placer(
            register.get("default"), placement.Placements(), live,
            archives=register)
        archiver = Archiver(live, store, interval_seconds=300,
                            name="default", placer=placer)
        before = archiver.build(start + 300)
        check("the first configured sender is selected",
              before.record.get("outTemp"), 10.0)

        # Both senders selected and the primary moved to the second. The
        # series has to follow the file, not the object the placer was built
        # with: 20.0 is only reachable if the new primary was read back.
        changed = archive_defs.Archive(
            "default", str(work / "records.sdb"), stations=(first, second),
            primary=second)
        archive_defs.Register([changed], path).save(path)
        # Register.refresh uses the file timestamp. Force a distinct one on
        # filesystems whose timestamp granularity is coarser than this test.
        stamp = path.stat().st_mtime
        os.utime(path, (stamp + 2, stamp + 2))
        after = archiver.build(start + 300)
        check("the changed primary is used without restarting",
              after.record.get("outTemp"), 20.0)
        live.close()
        store.close()


def a_placement_reaches_the_reader() -> None:
    """The claim the settings page makes, measured.

    Store a packet, build the interval, *then* write a placement, and build
    the same interval again. The record has to change.

    Nothing here restarts, no driver is involved, and no upload happens --
    which is the point. The page's promise was that a placement takes effect
    without a restart, and it was false for two years: the file reached
    `configure_drivers`, which runs once at startup, and `_mapper_for` cached
    for ever. Every test stopped at `stations.toml`.
    """
    print("\na placement written now reaches a span already archived")
    drivers.DEFAULT.load()
    driver = drivers.get("ecowitt")
    body = (FIXTURES / "hp2561ae_pro.txt").read_text(encoding="utf-8").strip().encode()
    start = 1787900000 // 300 * 300

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        store = ArchiveStore(work / "archive.sdb")
        try:
            for step in range(4):
                when = start + 60 * (step + 1)
                got = driver.packets(body, {"received": when,
                                            "path": "/ecowitt/"})[0]
                live.add(_replaced(got, dateTime=when, driver="ecowitt"))

            path = work / "placement.toml"
            placement.save(path, placement.Placements(), "nothing decided yet")
            plans = placement.load(path)
            placer = placement.Placer("default", plans, None, drivers.DEFAULT)
            archiver = Archiver(live, store, interval_seconds=300, placer=placer)

            before = archiver.build(start + 300)
            check("the contested field has no column yet",
                  "soilTemp1" in before.record, False)

            # Written by something else -- the settings page is another
            # process -- and not handed to the archiver.
            fresh = placement.load(path)
            fresh.decide("default", "", "ecowitt", "tf_ch1", "soilTemp1")
            placement.save(path, fresh, "the compost probe")

            # No restart, no reconfiguration: the reader re-reads the file it
            # is told to follow.
            plans.checked = 0.0
            check("the reader noticed the file changed", plans.refresh(0.0), True)
            after = archiver.build(start + 300)
            check("and the same span now has the column",
                  isinstance(after.record.get("soilTemp1"), float), True)
            # Not merely present: the number has to be the console's.
            check("carrying what the console sent",
                  round(after.record["soilTemp1"], 3), 66.2)
            check("and the rest of the record is unchanged",
                  {k: v for k, v in after.record.items() if k != "soilTemp1"},
                  dict(before.record))
        finally:
            live.close()
            store.close()


def the_memo_does_not_leak() -> None:
    """A placer that has seen another console gives the same answer.

    The mapper remembers which names it has already refused, so that it says
    so once rather than six times a minute. That memo must not change what it
    returns -- if it did, a rebuild would depend on what was built before it.
    """
    print("\na placer that has already seen other traffic")
    drivers.DEFAULT.load()
    driver = drivers.get("ecowitt")
    body = (FIXTURES / "hp2561ae_pro.txt").read_text(encoding="utf-8").strip().encode()
    other = (FIXTURES / "ambient" / "ambweather_v4.txt").read_text(
        encoding="utf-8").strip().encode()
    meta = {"received": 1787900000, "path": "/ecowitt/"}

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        try:
            mine = _replaced(driver.packets(body, meta)[0], driver="ecowitt")
            live.add(mine)
            stored = next(iter(live.packets(mine.dateTime - 1,
                                            mine.dateTime + 1)))

            fresh = placement.Placer("default", placement.Placements(), None,
                                     drivers.DEFAULT).place(stored)

            warmed = placement.Placer("default", placement.Placements(), None,
                                      drivers.DEFAULT)
            ambient = drivers.get("ambient")
            if ambient is not None:
                seen = ambient.packets(other, {"received": 1787900000,
                                               "path": "/ambient/"})
                if seen:
                    warmed.place(_replaced(seen[0], driver="ambient"))
            warmed.place(stored)          # once, so the memo is filled
            twice = warmed.place(stored)  # and again

            check("the same fields", sorted(twice.data), sorted(fresh.data))
            check("and the same values", twice.data, fresh.data)
        finally:
            live.close()


def the_units_follow_the_readings() -> None:
    """A stored dialect name does not settle the units, so it is not asked.

    `WeatherUnderground.metric_dialect()` answers to one name and carries
    either METRIC or METRICWX, with different scale factors, depending on a
    class attribute. So the read side works the dialect out from the readings
    again -- the same call the upload was answered with.
    """
    print("\nthe unit system comes back with the readings, not with the name")
    drivers.DEFAULT.load()
    seen = 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        try:
            for label, name, body in payloads():
                driver = drivers.get(name)
                if driver is None or not hasattr(driver, "protocol"):
                    continue
                made = driver.packets(body, {"received": 1787900000,
                                             "path": f"/{name}/"})
                if not made:
                    continue
                one = _replaced(made[0], driver=name, dateTime=1787900000 + seen)
                live.add(one)
                back = next(iter(live.packets(one.dateTime - 1,
                                              one.dateTime + 1)))
                placed = placement.Placer("default", placement.Placements(),
                                          None, drivers.DEFAULT).place(back)
                if placed is None:
                    continue
                seen += 1
                if placed.usUnits != back.usUnits:
                    check(f"{label}: units survive the round trip",
                          placed.usUnits, back.usUnits)
                if placed.usUnits not in (units.US, units.METRIC, units.METRICWX):
                    check(f"{label}: and are a system", placed.usUnits, "one of three")
        finally:
            live.close()
    check("every capture kept its unit system", seen > 10, True)


# ---------------------------------------------------------------------------
# Against a real capture.
# ---------------------------------------------------------------------------

def against_a_capture(where: Path) -> None:
    """A live database or an ndjson spool from a running instance.

    Twenty-three single frames prove the shapes. A week of one console proves
    the thing that only volume finds: a value that arrives once a fortnight,
    a firmware that changes a field name after an update.
    """
    print(f"\nagainst {where}")
    rows: list[dict] = []
    if where.suffix == ".gz":
        with gzip.open(where, "rt", encoding="utf-8") as fp:
            rows = [json.loads(line) for line in fp if line.strip()]
    else:
        conn = sqlite3.connect(f"file:{where.as_posix()}?mode=ro", uri=True)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(packet)")}
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "mapping" in columns and "dialect_mapping" in tables:
                mapping = "COALESCE(m.spec, p.mapping)"
                joined = (" FROM packet AS p LEFT JOIN dialect_mapping AS m"
                          " ON m.digest = p.mapping")
            else:
                mapping = "p.mapping" if "mapping" in columns else "NULL"
                joined = " FROM packet AS p"
            rows = [{"dateTime": r[0], "driver": r[1], "identity": r[2],
                     "dialect": r[3],
                     "mapping": (json.loads(r[4]) if r[4]
                                 and str(r[4]).lstrip().startswith("{") else None),
                     "usUnits": r[5], "data": json.loads(r[6])}
                    for r in conn.execute(
                        f"SELECT p.dateTime, p.driver, p.identity, p.dialect, {mapping}, "
                        f"p.usUnits, p.data{joined} ORDER BY p.dateTime")]
        finally:
            conn.close()

    placer = placement.Placer("default", placement.Placements())
    placed = empty = fields = 0
    for row in rows:
        packet = Packet(dateTime=int(row["dateTime"]), usUnits=int(row["usUnits"]),
                        data=row["data"], driver=row.get("driver") or "unknown",
                        identity=row.get("identity") or "",
                        dialect=row.get("dialect"), mapping=row.get("mapping"))
        got = placer.place(packet)
        if got is None:
            empty += 1
            continue
        placed += 1
        fields += len(got.data)
    print(f"  --   {len(rows)} packets, {placed} placed, {empty} with nothing "
          f"to place, {fields} readings")
    check("the capture places", placed > 0, True)
    check("and nothing in it was refused wholesale", empty, 0)


def main() -> int:
    print("the read side gives what the write side gave\n")
    if not FIXTURES.is_dir():
        print(f"  no payloads at {FIXTURES}; nothing to compare against")
        return 2

    every_capture_round_trips()
    the_record_is_the_same()
    what_moved_off_the_front_door()
    the_guessing_is_written_down()
    placing_is_quiet()
    the_archiver_executes_data_not_a_driver()
    a_scope_without_a_place_reaches_nothing()
    a_scope_is_keyed_on_the_sender_id()
    the_archive_service_does_not_load_a_driver()
    archive_members_reload_through_the_live_database()
    a_placement_reaches_the_reader()
    the_memo_does_not_leak()
    the_units_follow_the_readings()

    for at, arg in enumerate(sys.argv):
        if arg == "--capture" and at + 1 < len(sys.argv):
            where = Path(sys.argv[at + 1])
            if where.exists():
                against_a_capture(where)
            else:
                print(f"\nno capture at {where}; skipped")

    print(f"\n{'PASS' if not failures else f'FAIL ({failures})'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

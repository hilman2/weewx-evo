"""The isolated source-policy API and the product's Place-only wiring.

`weewx-metadriver` combines stations by wrapping their drivers: worker threads
per child, one shared queue, a `source` key on each packet. Its README names
the limits that follow, and they follow from *where* it sits, not from how it
is written. A driver merges packets as they arrive, and by then the choice is
already made.

The first checks the old explicit library API against an architecture that
merges when the interval is worked out, with every packet still on the table:

  1. Field-level merge. The garden thermometer is the temperature series; the
     roof station has the barometer. Each field comes from the station that
     should have it, not from whichever driver was declared primary.
  2. A source going quiet. When the garden stops reporting, the roof covers
     the fields it has -- per field, with no configuration change -- and the
     garden takes over again when it returns.
  3. Archive records from a secondary. There is no primary, so any station may
     deliver history.

The product runtime deliberately does not opt into that API. Its second check
builds an Archiver through ``cli.build_archivers`` and proves that Place
membership, member role and Place-scoped mapping are the only routing inputs.

    python tools/multisource.py
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import placement
from weewx_evo.archiver import Archiver
from weewx_evo.archives import Archive, MemberPolicy, Register
from weewx_evo.cli import _resolve, build_archivers
from weewx_evo.db.archive import ArchiveStore
from weewx_evo.db.live import LiveStore, Packet, sender_id
from weewx_evo.sources import Policy
from weewx_evo.units import US

INTERVAL = 300


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


class _Messages(logging.Handler):
    """Warnings emitted while production wiring is built."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def product_uses_place_policy(tmp: Path) -> int:
    """Configured Archivers never activate the retired global policy."""
    work = tmp / "product"
    work.mkdir()
    config = work / "evo.toml"
    config.write_text(
        '[sources]\noutTemp = "roof, garden"\n', encoding="utf-8")
    old_sources = work / "sources.toml"
    # Ignored means not even parsed. A retired file must not be able to stop
    # the service merely because its old syntax is damaged.
    old_sources.write_text("this is not TOML [", encoding="utf-8")

    garden = sender_id("test", "garden")
    roof = sender_id("test", "roof")
    plans = placement.Placements(takes=[placement.Takes(
        archive="default", station=roof,
        fields={"outTemp": "extraTemp1", "windSpeed": "extraTemp2"})])
    placement.save(work / placement.FILENAME, plans)
    place = Archive(
        name="default", file=str(work / "archive.sdb"),
        stations=(garden, roof), primary=garden,
        members={garden: MemberPolicy()})
    args = argparse.Namespace(config=config, sources=old_sources, quality=None)
    cfg = _resolve(args)
    live = LiveStore(work / "live.sdb", interval_seconds=INTERVAL)
    messages = _Messages()
    logger = logging.getLogger("weewx_evo")
    before = logger.level
    logger.setLevel(logging.WARNING)
    logger.addHandler(messages)
    made = []
    failures = 0
    try:
        made = build_archivers(args, cfg, live, Register([place]))
        archiver = made[0][2]
        failures += not check(
            "production has no source policy", archiver.sources, None)
        warning = "\n".join(messages.messages)
        failures += not check(
            "obsolete source configuration is reported",
            "obsolete and ignored" in warning, True)

        base = (int(time.time()) // INTERVAL) * INTERVAL
        live.add(Packet(dateTime=base + 60, usUnits=US,
                        data={"outTemp": 20.0, "windSpeed": 2.0},
                        driver="test", identity="garden"))
        live.add(Packet(dateTime=base + 60, usUnits=US,
                        data={"outTemp": 30.0, "windSpeed": 7.0},
                        driver="test", identity="roof"))
        built = archiver.build(base + INTERVAL)
        assert built is not None
        failures += not check(
            "the main member owns outTemp", built.record.get("outTemp"), 20.0)
        failures += not check(
            "the additional member writes where it was placed",
            built.record.get("extraTemp1"), 30.0)
        failures += not check(
            "including a reading with no column of its own",
            built.record.get("extraTemp2"), 7.0)
        failures += not check(
            "and its outTemp did not reach the primary's column",
            built.record.get("outTemp"), 20.0)
        failures += not check(
            "configured routing adds no source provenance", built.provenance, {})
    finally:
        logger.removeHandler(messages)
        logger.setLevel(before)
        for _definition, store, _archiver in made:
            store.close()
        live.close()
    return failures


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-sources-"))
    failures = 0
    try:
        live = LiveStore(tmp / "live.sdb", interval_seconds=INTERVAL)
        archive = ArchiveStore(tmp / "weewx.sdb")

        # The garden is the temperature series. The roof has the barometer and
        # the wind, being on a roof. Neither is "the" station.
        policy = Policy.from_config({
            "outTemp": "garden, roof",
            "outHumidity": "garden, roof",
            "barometer": "roof",
            "wind*": "roof, garden",
            "*": "garden, roof",
        })
        archiver = Archiver(live, archive, interval_seconds=INTERVAL, sources=policy)

        base = (int(time.time()) // INTERVAL) * INTERVAL

        def put(source: str, ts: int, kind: str = "loop", **data: float) -> None:
            live.add(Packet(dateTime=ts, usUnits=US, data=data,
                            identity=source, kind=kind))

        print("1. both stations report; each field comes from the right one")
        for i in range(5):
            ts = base + 30 + i * 30
            put("garden", ts, outTemp=20.0 + i, outHumidity=70.0, barometer=1013.0)
            put("roof", ts, outTemp=25.0 + i, barometer=1015.0,
                windSpeed=3.0 + i, windDir=180.0)
        stop = base + INTERVAL
        built = archiver.build(stop)
        assert built is not None
        failures += not check("outTemp from the garden", built.provenance["outTemp"], "garden")
        failures += not check("barometer from the roof", built.provenance["barometer"], "roof")
        failures += not check("windSpeed from the roof",
                              built.provenance["windSpeed"], "roof")
        failures += not check("outTemp is the garden mean",
                              round(built.record["outTemp"], 2), 22.0)
        failures += not check("barometer is the roof value",
                              round(built.record["barometer"], 1), 1015.0)
        failures += not check("no average across stations",
                              built.record["outTemp"] != 24.5, True)
        archiver.store(built)

        print("\n2. the garden goes quiet; the roof covers what it has")
        stop2 = base + 2 * INTERVAL
        for i in range(5):
            ts = base + INTERVAL + 30 + i * 30
            put("roof", ts, outTemp=25.0 + i, barometer=1015.0, windSpeed=4.0)
        built2 = archiver.build(stop2)
        assert built2 is not None
        failures += not check("outTemp now from the roof",
                              built2.provenance["outTemp"], "roof")
        failures += not check("outTemp is the roof mean",
                              round(built2.record["outTemp"], 2), 27.0)
        failures += not check("outHumidity absent, nobody has it",
                              built2.record.get("outHumidity"), None)
        archiver.store(built2)

        print("\n3. the garden returns; it takes its field back")
        stop3 = base + 3 * INTERVAL
        for i in range(5):
            ts = base + 2 * INTERVAL + 30 + i * 30
            put("garden", ts, outTemp=21.0 + i, outHumidity=72.0)
            put("roof", ts, outTemp=26.0 + i, barometer=1016.0)
        built3 = archiver.build(stop3)
        assert built3 is not None
        failures += not check("outTemp from the garden again",
                              built3.provenance["outTemp"], "garden")
        failures += not check("outTemp is the garden mean",
                              round(built3.record["outTemp"], 2), 23.0)
        failures += not check("barometer still the roof",
                              round(built3.record["barometer"], 1), 1016.0)
        archiver.store(built3)

        print("\n4. a secondary station delivers an archive record")
        # metadriver: "Only the primary driver is used for genArchiveRecords()."
        stop4 = base + 4 * INTERVAL
        put("roof", stop4, kind="archive", outTemp=30.0, barometer=1020.0,
            interval=INTERVAL / 60)
        for i in range(3):
            put("garden", base + 3 * INTERVAL + 60 + i * 60, outHumidity=75.0)
        built4 = archiver.build(stop4)
        assert built4 is not None
        failures += not check("record came from hardware", built4.from_hardware, True)
        failures += not check("hardware outTemp kept", built4.record["outTemp"], 30.0)
        failures += not check("and the other station still contributed",
                              round(built4.record["outHumidity"], 1), 75.0)
        archiver.store(built4)

        print("\n5. what landed in the archive")
        failures += not check("four records", archive.count(), 4)
        first = archive.record(stop)
        assert first is not None
        failures += not check("the first is unchanged",
                              round(first["outTemp"], 2), 22.0)

        print("\n6. the low-level API stays opt-in")
        plain = Archiver(live, archive, interval_seconds=INTERVAL)
        mixed = plain.build(stop)
        assert mixed is not None
        failures += not check("both stations averaged together",
                              round(mixed.record["outTemp"], 2), 24.5)
        failures += not check("nothing to record about provenance",
                              mixed.provenance, {})

        print("\n7. production routing belongs only to the Place")
        failures += product_uses_place_policy(tmp)

        live.close()
        archive.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

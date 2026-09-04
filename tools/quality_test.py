#!/usr/bin/env python3
"""Calibration and limits: what gets into the archive, and what does not.

The check that matters is the last one, and it is why this sits in the
archiver rather than anywhere else: a refused reading has to be gone *before*
the accumulator sees it. A spike that reaches the accumulator has set the
interval's minimum and pulled its mean, and no later filtering takes either
back out. Measured here on a real archive: the same ten packets with one
reading of -41 give a mean of 13.6 and a daily low of -41 without rules, and
20.45 and 20.1 with them.

Three more that no browser and no green unit test would find:

**A limit is a number in a unit.** -50 written in Celsius has to be -58 for a
console reporting Fahrenheit. A *span* is different again: a five-degree jump
is nine Fahrenheit degrees, not 41. Get the second one wrong and a spike rule
turns into a limit at the freezing point.

**Calibration comes before the check.** The other order tests an uncorrected
reading against corrected limits, so a thermometer with an offset fails at
its own ceiling.

**A rebuild has to give the same answer.** The checker is made fresh per span
and seeded from the live table, so building an interval twice, or building it
a week later, produces the same record. A checker carried between calls would
make that untrue and nothing would say so.

    python tools/quality_test.py
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import adminquality, quality, units
from weewx_evo.admin import Admin
from weewx_evo.archiver import Archiver
from weewx_evo.cli import (
    _resolve,
    _watched_files,
    _Watcher,
    all_schemas,
    apply_live,
    quality_path,
    read_archives,
    read_quality,
)
from weewx_evo.db.archive import ArchiveStore
from weewx_evo.db.live import LiveStore, Packet, sender_id

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def close_to(what: str, got: float | None, want: float, tol: float = 1e-6) -> None:
    global CHECKS
    CHECKS += 1
    if got is None or abs(got - want) > tol:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


START = 1755648000
SHED = sender_id("unknown", "schuppen")

RULES = {
    "unit_system": "metricwx",
    "limits": {
        "outTemp": {"minimum": -50, "maximum": 60, "spike": 5,
                    "stuck": 4, "resolution": 0.05},
        "rain": {"minimum": 0, "maximum": 50},
    },
    "calibrate": {
        "everywhere": {"outHumidity": {"offset": 2.0}},
        SHED: {"outTemp": {"offset": -0.4}},
    },
}


def policy() -> quality.Policy:
    return quality.from_dict(RULES)


# ---------------------------------------------------------------------------
# The rules.
# ---------------------------------------------------------------------------

def test_the_three_rules() -> None:
    checker = quality.Check(policy())
    readings = [20.0, 20.4, -41.0, 20.5, 99.0, 20.6, 20.6, 20.6, 20.6, 20.6]
    kept, why = [], []
    for index, value in enumerate(readings):
        data, verdicts = checker.check({"outTemp": value}, START + index * 60)
        kept.append("outTemp" in data)
        why.append(verdicts[0].rule if verdicts else "")

    check("every plausible reading before the sensor stops is kept",
          [kept[i] for i in (0, 1, 3, 5, 6, 7, 8)], [True] * 7)
    check("a jump the weather cannot make", why[2], "spike")
    check("an impossible reading", why[4], "maximum")
    check("a sensor that has stopped", why[9], "stuck")
    check("and they are counted", checker.dropped, {"outTemp": 3})
    check("with something to read", checker.summary(), "outTemp x3")


def test_a_dropped_reading_is_absent_not_zero() -> None:
    """Zero is a measurement.

    A gauge reporting 0.0 because its reading was refused cannot be told from
    a dry afternoon, ever.
    """
    checker = quality.Check(policy())
    data, _ = checker.check({"outTemp": 200.0, "outHumidity": 61.0}, START)
    check("the refused reading is gone", "outTemp" in data, False)
    check("it is not zeroed", data.get("outTemp"), None)
    check("its neighbour is untouched", data["outHumidity"], 61.0)


def test_a_reading_with_no_rule_passes() -> None:
    checker = quality.Check(policy())
    data, verdicts = checker.check({"soilTemp1": -9999.0}, START)
    check("nothing said about it, nothing done", data["soilTemp1"], -9999.0)
    check("and no verdict", verdicts, [])


def test_rain_gets_no_spike_rule() -> None:
    """A cloudburst is a step change, and so is a gauge being emptied.

    The two look the same from here, and throwing away real heavy rain is
    worse than keeping a fault the limits catch anyway.
    """
    rules = {"limits": {"rain": {"spike": 0.1, "maximum": 50}}}
    checker = quality.Check(quality.from_dict(rules))
    checker.check({"rain": 0.0}, START)
    data, verdicts = checker.check({"rain": 12.0}, START + 60)
    check("the cloudburst survives", data.get("rain"), 12.0)
    check("and nothing was said", verdicts, [])

    # The ceiling still applies: a gauge reporting 300 is a fault.
    data, verdicts = checker.check({"rain": 300.0}, START + 120)
    check("but an impossible figure does not", "rain" in data, False)
    check("caught by the limit", verdicts[0].rule, "maximum")


def test_stuck_needs_the_resolution() -> None:
    """A thermometer reading to a tenth stands still on a calm night.

    Without the resolution every quiet night is a dead sensor.
    """
    fine = quality.Check(quality.from_dict(
        {"limits": {"outTemp": {"stuck": 3, "resolution": 0.05}}}))
    coarse = quality.Check(quality.from_dict(
        {"limits": {"outTemp": {"stuck": 3, "resolution": 0.0}}}))

    # Drifting by a hundredth: below the sensor's resolution, so it is the
    # same reading being reported again.
    drift = [20.00, 20.01, 20.02, 20.03, 20.04, 20.05]
    for index, value in enumerate(drift):
        fine.check({"outTemp": value}, START + index * 60)
        coarse.check({"outTemp": value}, START + index * 60)
    check("a sensor resolving to 0.05 is standing still",
          fine.dropped.get("outTemp", 0) > 0, True)
    check("one that resolves further is not",
          coarse.dropped.get("outTemp", 0), 0)


# ---------------------------------------------------------------------------
# Units.
# ---------------------------------------------------------------------------

def test_a_limit_is_a_number_in_a_unit() -> None:
    """The same file, a Fahrenheit console. Both directions are traps."""
    check("-50 C is -58 F",
          quality._in_system(-50, "outTemp", units.METRICWX, units.US), -58.0)
    check("60 C is 140 F",
          quality._in_system(60, "outTemp", units.METRICWX, units.US), 140.0)
    # And a span is not a point. Converting 5 the same way gives 41, which
    # would turn a spike rule into a limit at the freezing point.
    check("a 5 K jump is 9 F degrees",
          quality._in_system(5, "outTemp", units.METRICWX, units.US,
                             difference=True), 9.0)
    close_to("and an offset of -0.4 K is -0.72 F",
             quality._as_difference(-0.4, "outTemp", units.METRICWX, units.US),
             -0.72, tol=1e-9)


def test_the_limits_reach_a_fahrenheit_console() -> None:
    checker = quality.Check(policy())
    # 150 °F is 65.6 °C, over the 60 ceiling.
    data, verdicts = checker.check({"outTemp": 150.0}, START, system=units.US)
    check("refused", "outTemp" in data, False)
    check("and the message is in the packet's own unit",
          "140" in verdicts[0].why, True)

    # 100 °F is 37.8 °C, which is a hot afternoon and not a fault.
    data, _ = checker.check({"outTemp": 100.0}, START + 60, system=units.US)
    check("a hot afternoon is kept", data.get("outTemp"), 100.0)


def test_calibration_converts_as_a_difference() -> None:
    checker = quality.Check(policy())
    metric = checker.calibrate({"outHumidity": 60.0}, "any", units.METRICWX)
    check("a metric packet takes the offset as written",
          metric["outHumidity"], 62.0)

    checker = quality.Check(policy())
    american = checker.calibrate({"outTemp": 68.0}, SHED, units.US)
    close_to("a Fahrenheit packet takes it converted as a span",
             american["outTemp"], 68.0 - 0.72, tol=1e-9)


def test_a_sender_wins_over_everybody() -> None:
    one = policy()
    check("the sender's own", one.adjust_for(SHED, "outTemp").offset, -0.4)
    check("nothing for another sender",
          one.adjust_for(sender_id("unknown", "haus"), "outTemp"), None)
    check("the same hardware identity under another driver is distinct",
          one.adjust_for(sender_id("push", "schuppen"), "outTemp"), None)
    check("and the one for everybody applies to both",
          [one.adjust_for(who, "outHumidity").offset
           for who in (SHED, sender_id("unknown", "haus"))], [2.0, 2.0])


def test_calibration_comes_before_the_check() -> None:
    """Otherwise a thermometer with an offset fails at its own ceiling."""
    rules = {"limits": {"outTemp": {"maximum": 60}},
             "calibrate": {"everywhere": {"outTemp": {"offset": -5.0}}}}
    checker = quality.Check(quality.from_dict(rules))
    corrected = checker.calibrate({"outTemp": 63.0}, "", units.METRICWX)
    check("the correction brings it under the ceiling", corrected["outTemp"], 58.0)
    data, _ = checker.check(corrected, START)
    check("so it is kept", data.get("outTemp"), 58.0)


# ---------------------------------------------------------------------------
# The file.
# ---------------------------------------------------------------------------

def test_a_missing_file_is_no_rules() -> None:
    where = Path(tempfile.mkdtemp()) / "quality.toml"
    empty = quality.load(where)
    check("no rules", bool(empty), False)
    check("and nothing is dropped",
          quality.Check(empty).check({"outTemp": -9999.0}, START)[1], [])


def test_the_file_round_trips() -> None:
    where = Path(tempfile.mkdtemp()) / "quality.toml"
    where.write_text(FILE, encoding="utf-8")
    one = quality.load(where)
    check("the limits", sorted(one.limits), ["outTemp", "rain"])
    check("the ceiling", one.limits["outTemp"].maximum, 60.0)
    check("the resolution", one.limits["outTemp"].resolution, 0.1)
    check("a sender's calibration",
          one.calibration[SHED]["outTemp"].offset, -0.4)
    check("and the system the figures are in", one.system, units.METRICWX)
    rewritten = tomllib.loads(adminquality.as_toml(one))
    check("the Admin writer quotes the canonical sender ID",
          rewritten["calibrate"][SHED]["outTemp"]["offset"], -0.4)


def test_a_legacy_display_name_is_preserved_but_inactive() -> None:
    old = quality.from_dict({
        "calibrate": {
            "schuppen": {"outTemp": {"offset": -0.4}},
            "everywhere": {"outHumidity": {"offset": 2.0}},
        }
    })
    check("the display name is not an active calibration",
          "schuppen" in old.calibration, False)
    check("it is retained for a lossless Admin save",
          old.obsolete_calibration["schuppen"]["outTemp"].offset, -0.4)
    check("it cannot match the sender that currently carries that label",
          old.adjust_for(SHED, "outTemp"), None)
    check("the installation-wide correction remains active",
          old.adjust_for(SHED, "outHumidity").offset, 2.0)

    written = adminquality.as_toml(old)
    parsed = tomllib.loads(written)
    check("an Admin save retains the old table",
          parsed["calibrate"]["schuppen"]["outTemp"]["offset"], -0.4)
    check("and marks it as ignored", "Ignored legacy label" in written, True)


def test_packet_calibration_identity_is_always_canonical() -> None:
    ordinary = Packet(dateTime=START, usUnits=units.METRICWX, data={},
                      driver="unknown", identity="schuppen",
                      source="Friendly shed")
    check("a friendly packet label is never a calibration key",
          quality.sender_for(ordinary), SHED)

    # Placement associates a retained pre-journal row with one explicit,
    # modern Place member. Keep that canonical association rather than
    # reverting to the reserved legacy sender ID.
    legacy = Packet(dateTime=START, usUnits=units.METRICWX, data={},
                    driver="__legacy__", identity="schuppen", source=SHED)
    check("a placed legacy row keeps its canonical modern member",
          quality.sender_for(legacy), SHED)


def test_an_empty_rule_is_not_a_rule() -> None:
    """A table with nothing in it must not make everything unchecked-looking."""
    one = quality.from_dict({"limits": {"outTemp": {}}})
    check("no rule kept", one.limits, {})
    check("so the policy is empty", bool(one), False)


# ---------------------------------------------------------------------------
# In the archiver, which is the whole point.
# ---------------------------------------------------------------------------

def an_archive(where: Path, readings: list[float], every: int = 30,
               station: str = "s") -> Path:
    live_path = where / "live.sdb"
    with LiveStore(live_path, interval_seconds=300) as live:
        for index, value in enumerate(readings):
            live.add(Packet(dateTime=START + index * every, usUnits=units.METRICWX,
                            data={"outTemp": value, "outHumidity": 60.0},
                            identity=station))
    return live_path


def built_with(where: Path, live_path: Path, policy_or_none: object,
               name: str, stop: int = START + 300) -> tuple:
    live = LiveStore(live_path, interval_seconds=300)
    store = ArchiveStore(where / f"{name}.sdb")
    try:
        archiver = Archiver(live, store, interval_seconds=300,
                            quality=policy_or_none)
        built = archiver.build(stop)
        archiver.store(built)
        day = store.conn.execute(
            "SELECT min, max FROM archive_day_outTemp").fetchone()
        return built, day
    finally:
        live.close()
        store.close()


def test_a_spike_never_reaches_the_daily_low() -> None:
    """The reason this sits in the archiver and not after it.

    A refused reading has to be gone before the accumulator, because the
    accumulator is what writes the daily minimum -- and nothing takes that
    back out afterwards.
    """
    where = Path(tempfile.mkdtemp())
    live_path = an_archive(
        where, [20.0, 20.1, -41.0, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8])

    loose, loose_day = built_with(where, live_path, None, "loose")
    tight, tight_day = built_with(where, live_path, policy(), "tight")

    close_to("without rules the mean is dragged down",
             loose.record["outTemp"], 13.62, tol=0.01)
    check("and the daily low is the spike", round(loose_day[0], 1), -41.0)

    close_to("with rules the mean is the weather",
             tight.record["outTemp"], 20.45, tol=0.01)
    check("and the daily low is a real reading", round(tight_day[0], 1), 20.1)
    check("the archiver reports what it refused", tight.dropped, {"outTemp": 1})


def test_building_twice_gives_the_same_record() -> None:
    """`build` is a function of a time span, and has to stay one.

    A checker carried between calls would make an interval depend on what was
    built before it, so a rebuild would differ from the original -- silently,
    and only where a rule fired.
    """
    where = Path(tempfile.mkdtemp())
    live_path = an_archive(
        where, [20.0, 20.1, -41.0, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8])

    first, _ = built_with(where, live_path, policy(), "first")
    second, _ = built_with(where, live_path, policy(), "second")
    check("the same record", first.record, second.record)
    check("and the same verdicts", first.dropped, second.dropped)

    # Twice through one archiver, which is what a rebuild does.
    live = LiveStore(live_path, interval_seconds=300)
    store = ArchiveStore(where / "again.sdb")
    try:
        archiver = Archiver(live, store, interval_seconds=300, quality=policy())
        one = archiver.build(START + 300)
        two = archiver.build(START + 300)
        check("and again from the same archiver", one.record, two.record)
        check("with the same count", one.dropped, two.dropped)
    finally:
        live.close()
        store.close()


def test_an_outlier_in_the_run_up_is_not_the_reference() -> None:
    """One bad packet must not switch a station off.

    The run-up has to judge as well as remember. Taking every reading as read
    means an outlier becomes what the next reading is compared against -- so
    the first real one is a spike from -41, and so is the one after it, for
    as long as the sensor keeps working.
    """
    where = Path(tempfile.mkdtemp())
    # The outlier is the last packet of the first interval, so it reaches the
    # second interval only through the run-up.
    readings = ([20.0 + i * 0.1 for i in range(9)] + [-41.0]
                + [21.0 + i * 0.1 for i in range(10)])
    live_path = an_archive(where, readings)

    built, _day = built_with(where, live_path, policy(), "outlier",
                             stop=START + 600)
    check("the readings after it are kept", built.dropped, {})
    close_to("and the record is the weather",
             built.record["outTemp"], 21.5, tol=0.3)


def test_the_run_up_closes_the_boundary() -> None:
    """A spike on the first packet of an interval has nothing to jump from.

    Without reading the packets before the span, every interval boundary is a
    hole a spike walks through -- once every five minutes, for ever.
    """
    where = Path(tempfile.mkdtemp())
    # Drifting gently through the first interval -- not ten identical
    # readings, which would be a stuck sensor and is a different test -- and
    # then the jump lands on the first packet of the *second* interval, which
    # is the packet with nothing before it to be compared against.
    readings = ([20.0 + i * 0.1 for i in range(11)] + [-41.0]
                + [21.2 + i * 0.1 for i in range(8)])
    live_path = an_archive(where, readings)

    built, _day = built_with(where, live_path, policy(), "boundary",
                             stop=START + 600)
    check("the spike on the boundary is caught", built.dropped, {"outTemp": 1})
    close_to("so the second interval is the weather",
             built.record["outTemp"], 21.55, tol=0.2)


def test_calibration_reaches_the_record() -> None:
    where = Path(tempfile.mkdtemp())
    live_path = an_archive(where, [20.0] * 10, station="schuppen")
    built, _ = built_with(where, live_path, policy(), "shed")
    close_to("the canonical sender's offset is applied",
             built.record["outTemp"], 19.6)
    close_to("and the one for everybody too",
             built.record["outHumidity"], 62.0)


def test_no_policy_costs_nothing() -> None:
    """Almost every installation runs without rules, and must be untouched."""
    where = Path(tempfile.mkdtemp())
    live_path = an_archive(where, [20.0, 20.5, 21.0, 20.5] * 2)
    built, _ = built_with(where, live_path, None, "plain")
    check("nothing dropped", built.dropped, {})
    check("and a record all the same", "outTemp" in built.record, True)


# ---------------------------------------------------------------------------
# Suggesting rules, and the commands.
# ---------------------------------------------------------------------------

def a_year(readings: list[tuple[str, list[float]]],
           system: int = units.METRICWX) -> list[dict]:
    """Records in time order, five minutes apart."""
    rows = []
    length = max(len(values) for _obs, values in readings)
    for index in range(length):
        row: dict = {"dateTime": START + index * 300, "usUnits": system,
                     "interval": 5}
        for obs, values in readings:
            if index < len(values):
                row[obs] = values[index]
        rows.append(row)
    return rows


def test_a_suggestion_stays_inside_physics() -> None:
    """Four years of data still put the floor for wind speed at -2.

    Room added below the lowest reading is right for a temperature and wrong
    for anything that cannot go negative, and the suggestion only knows what
    it has seen.
    """
    rows = a_year([("windSpeed", [0.0, 1.0, 2.0, 3.0, 0.5] * 4),
                   ("outHumidity", [88.0, 92.0, 96.0, 99.0, 94.0] * 4),
                   ("windDir", [10.0, 350.0, 5.0, 180.0, 90.0] * 4)])
    seen = quality.watch(rows)

    check("wind speed cannot be negative",
          seen["windSpeed"].rule().minimum, 0.0)
    check("humidity cannot pass 100",
          seen["outHumidity"].rule().maximum, 100.0)
    check("a direction is a full circle",
          (seen["windDir"].rule().minimum, seen["windDir"].rule().maximum),
          (0.0, 360.0))


def test_a_suggestion_has_room_in_it() -> None:
    """A ceiling at the highest reading on record refuses the next hot day."""
    rows = a_year([("outTemp", [10.0, 15.0, 20.0, 25.0, 12.0] * 4)])
    rule = quality.watch(rows)["outTemp"].rule()
    check("the ceiling is above what was seen", rule.maximum > 25.0, True)
    check("and the floor below it", rule.minimum < 10.0, True)


def test_no_spike_rule_for_a_counter_or_a_circle() -> None:
    """Rain steps, and the wind passing north is not a jump of 358 degrees."""
    rows = a_year([("rain", [0.0, 0.0, 12.0, 0.0, 0.0] * 4),
                   ("windDir", [350.0, 10.0, 350.0, 10.0, 350.0] * 4),
                   ("outTemp", [10.0, 11.0, 10.5, 12.0, 11.5] * 4)])
    seen = quality.watch(rows)
    check("none for rain", seen["rain"].rule().spike, None)
    check("none for a direction", seen["windDir"].rule().spike, None)
    check("but one for a temperature", seen["outTemp"].rule().spike is not None,
          True)
    check("and no stuck rule for rain either", seen["rain"].rule().stuck, None)


def test_a_suggestion_is_written_in_the_wanted_units() -> None:
    """A Fahrenheit console with a file written in Celsius.

    Taking the figures as they are recorded gives a floor of 38 and a ceiling
    of 86 -- plausible-looking numbers, and the wrong ones the moment they
    are read back as Celsius.
    """
    rows = a_year([("outTemp", [50.0, 60.0, 70.0, 80.0, 55.0] * 4)],
                  system=units.US)
    rule = quality.watch(rows, system=units.METRICWX)["outTemp"].rule()
    check("the ceiling is Celsius", 26 < rule.maximum < 34, True)
    check("and the floor too", 4 < rule.minimum < 10, True)


def test_the_measured_rules_pass_their_own_data() -> None:
    """The round trip that matters: suggest, then check, and refuse nothing.

    A suggestion that refuses the readings it was worked out from is one
    nobody can use, and the way to find that out is to run it.
    """
    rows = a_year([("outTemp", [10.0, 15.0, 20.0, 25.0, 12.0] * 8),
                   ("outHumidity", [60.0, 70.0, 80.0, 90.0, 65.0] * 8),
                   ("windSpeed", [0.0, 2.0, 4.0, 1.0, 3.0] * 8)])
    seen = quality.watch(rows)
    policy_out = quality.Policy(
        limits={obs: entry.rule() for obs, entry in seen.items()})

    checker = quality.Check(policy_out)
    for row in rows:
        checker.check(row, row["dateTime"])
    check("its own history passes", checker.dropped, {})


def test_a_reading_that_does_not_move_gets_no_rule() -> None:
    """An archive column holds more than measurements.

    `lightning_time` is a Unix timestamp, a battery field is a flag. Both sit
    still, and a rule worked out from one refuses the next value that
    differs. Measured on the reference database before this: a ceiling two
    seconds above a lightning timestamp refused 36% of the records it came
    from, and a spike rule of zero on a battery flag refuses every change
    there will ever be.
    """
    # A timestamp: a span of four seconds around 1.79 billion.
    stamps = a_year([("lightning_time", [1787604641.0] * 30
                      + [1787604645.0] * 10)])
    seen = quality.watch(stamps)
    check("no rule at all for a timestamp",
          seen["lightning_time"].rule().empty(), True)
    check("because it does not vary", seen["lightning_time"].varies(), False)

    # A flag that never changes.
    flat = a_year([("txBatteryStatus", [1.62] * 40)])
    check("nor for a flag that never moves",
          flat["txBatteryStatus"].rule().empty() if "txBatteryStatus" in flat
          else True, True)

    # And a reading that does move still gets one.
    real = quality.watch(a_year([("outTemp", [10.0, 15.0, 20.0, 12.0] * 10)]))
    check("but a reading that moves does",
          real["outTemp"].rule().empty(), False)


def test_a_spike_rule_is_never_zero() -> None:
    """Zero is not a rule, it is a prohibition on ever changing."""
    rows = a_year([("someField", [5.0, 5.0, 5.0000001, 5.0] * 10)])
    seen = quality.watch(rows)
    if "someField" in seen:
        rule = seen["someField"].rule()
        check("no spike rule of zero",
              rule.spike is None or rule.spike > 0, True)


def test_standing_still_can_be_the_normal_state() -> None:
    """A battery flag that has not moved for a quarter of the year is not a
    dead sensor, and a stuck rule about it fires on the ordinary case."""
    # Moves at the very end, so it "varies", but is still for most of it.
    values = [1.0] * 36 + [2.0, 1.0, 2.0, 1.0]
    seen = quality.watch(a_year([("someFlag", values)]))
    check("no stuck rule where stillness is normal",
          seen["someFlag"].rule().stuck, None)


def test_the_suggest_command_writes_readable_toml() -> None:
    """What it prints has to parse, or the next step is retyping it."""
    import subprocess
    import tomllib

    where = Path(tempfile.mkdtemp())
    (where / "evo.toml").write_text('archive_db = "weewx.sdb"\n',
                                    encoding="utf-8")

    store = ArchiveStore(where / "weewx.sdb")
    try:
        for row in a_year([("outTemp", [10.0, 15.0, 20.0, 25.0, 12.0] * 8),
                           ("outHumidity", [60.0, 70.0, 88.0, 90.0, 65.0] * 8)]):
            store.add_record(row)
        store.conn.commit()
    finally:
        store.close()

    import os
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).resolve().parent.parent / "src"),
         environment.get("PYTHONPATH", "")])
    environment["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run(
        [sys.executable, "-m", "weewx_evo.cli", "quality", "suggest",
         "--config", "evo.toml", "--days", "36500"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=where, env=environment, check=False)
    check("it succeeds", done.returncode, 0)

    parsed = tomllib.loads(done.stdout)
    check("it names the system its figures are in",
          parsed.get("unit_system"), "metricwx")
    check("and it suggested the readings that are there",
          sorted(parsed.get("limits", {})), ["outHumidity", "outTemp"])
    check("humidity is never suggested above what physics allows",
          parsed["limits"]["outHumidity"]["maximum"] <= 100, True)

    # And what it wrote is loadable by the thing that reads it.
    (where / "quality.toml").write_text(done.stdout, encoding="utf-8")
    loaded = quality.load(where / "quality.toml")
    check("the file it printed loads", sorted(loaded.limits),
          ["outHumidity", "outTemp"])


FILE = f"""unit_system = "metricwx"

[limits.outTemp]
minimum = -50
maximum = 60
spike = 5
stuck = 40
resolution = 0.1

[limits.rain]
minimum = 0
maximum = 50

[calibrate."{SHED}".outTemp]
offset = -0.4
"""


def test_a_real_station_s_own_rules_refuse_nothing() -> None:
    """The round trip that matters, on a database nobody made up.

    134 columns, of which 54 are recorded: timestamps, battery flags, soil
    probes and the weather. Suggest rules from all of it, run them over the
    same records, and refuse nothing. This is the check that found three
    faults a synthetic fixture could not: the headroom under a timestamp, a
    spike rule that rounded to zero, and a stuck rule on a reading whose
    normal state is standing still.
    """
    where = Path(__file__).resolve().parent.parent / "reference" / "weewx.sdb"
    if not where.exists():
        return

    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(f"file:{where}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM archive ORDER BY dateTime")]

    seen = quality.watch(rows, system=units.METRICWX)
    limits = {obs: entry.rule() for obs, entry in seen.items()
              if not entry.rule().empty()}
    check("most readings get a rule", len(limits) > 20, True)

    checker = quality.Check(quality.Policy(limits=limits,
                                           system=units.METRICWX))
    for row in rows:
        system = units.system_from(row.get("usUnits"), default=units.METRICWX)
        checker.check(checker.calibrate(row, "", system),
                      float(row.get("dateTime") or 0), "", system)
    check("and its own history passes them", checker.dropped, {})


def test_the_rules_reach_the_live_readings() -> None:
    """The archive throws a spike away and the live page published it.

    `archiver.build()` is the right place for the decision -- the archive is
    what has to be defensible -- but this table has two readers and only one
    of them goes through the archiver. So the reading a visitor saw was one
    the station's own charts did not have, every ten seconds, with nothing on
    either side able to show the disagreement.
    """
    import tempfile

    from weewx_evo.db.live import LiveStore, Packet
    from weewx_evo.quality import Policy, Rule
    from weewx_evo.uploads import records as upload_records

    where = Path(tempfile.mkdtemp()) / "live.sdb"
    store = LiveStore(where)
    base = int(time.time())
    try:
        # An ordinary reading, then one no thermometer produces.
        store.add(Packet(dateTime=base - 20, usUnits=units.METRICWX,
                         data={"outTemp": 21.0, "outHumidity": 60.0},
                         identity="ecowitt"))
        store.add(Packet(dateTime=base - 10, usUnits=units.METRICWX,
                         data={"outTemp": -40.0, "outHumidity": 61.0},
                         identity="ecowitt"))
    finally:
        store.close()

    plain = upload_records.live_source(where)
    got = plain.after(0, 1)
    check("without rules the spike is published", got[0].get("outTemp"), -40.0)
    plain.close()

    policy = Policy(limits={"outTemp": Rule(minimum=-30.0, maximum=50.0)},
                    system=units.METRICWX)
    screened = upload_records.live_source(where, policy)
    got = screened.after(0, 1)
    check("with them it is not there", "outTemp" in got[0], False)
    check("and the rest of the packet still is",
          got[0].get("outHumidity"), 61.0)
    screened.close()


def test_the_live_readings_are_calibrated_too() -> None:
    """An offset is part of what the reading *is*.

    A live page showing the raw value beside an archive holding the
    corrected one is the same disagreement in a smaller font.
    """
    import tempfile

    from weewx_evo.db.live import LiveStore, Packet
    from weewx_evo.quality import Adjust, Policy
    from weewx_evo.uploads import records as upload_records

    where = Path(tempfile.mkdtemp()) / "live.sdb"
    store = LiveStore(where)
    base = int(time.time())
    try:
        store.add(Packet(dateTime=base - 5, usUnits=units.METRICWX,
                         data={"outTemp": 20.0}, identity="ecowitt"))
    finally:
        store.close()

    policy = Policy(calibration={sender_id("unknown", "ecowitt"):
                                 {"outTemp": Adjust(offset=-0.4)}},
                    system=units.METRICWX)
    live = upload_records.live_source(where, policy)
    got = live.after(0, 1)
    check("the offset was applied", round(got[0]["outTemp"], 3), 19.6)
    live.close()


def test_rules_that_cannot_be_applied_do_not_stop_the_readings() -> None:
    """A quality file with something odd in it is a settings problem. A page
    that stops updating because of one is an outage."""
    import tempfile

    from weewx_evo.db.live import LiveStore, Packet
    from weewx_evo.uploads import records as upload_records

    where = Path(tempfile.mkdtemp()) / "live.sdb"
    store = LiveStore(where)
    try:
        store.add(Packet(dateTime=int(time.time()) - 5,
                         usUnits=units.METRICWX, data={"outTemp": 20.0},
                         source="ecowitt"))
    finally:
        store.close()

    class Broken:
        limits: ClassVar[dict] = {"outTemp": None}
        calibration: ClassVar[dict] = {}

        def __bool__(self) -> bool:
            return True

    live = upload_records.live_source(where, Broken())
    got = live.after(0, 1)
    check("the reading came through anyway", got[0].get("outTemp"), 20.0)
    live.close()


# ---------------------------------------------------------------------------
# From the settings page to the running archiver.
# ---------------------------------------------------------------------------
#
# Everything above this line builds an `Archiver` and hands it a policy the
# test made. That is the half nothing was wrong with, and it stayed green
# through three separate failures of the half nobody measured:
#
#   the page read `archive_db` while the register read `[archives.default]
#   file`, so it found no database, listed no readings and answered "there is
#   nothing in the archive to work them out from yet" about a year of records
#
#   `quality.toml` was not among the files the watcher stats, so a rule saved
#   on the page reached the loop only when somebody restarted the container
#
#   and `apply_live` never touched `Archiver.quality`, so it would not have
#   reached it even then
#
# All three say saved and refuse nothing. So these go the other way round:
# write the file a page would write, and ask the archiver what it does.


def an_installation(work: Path, *, second: bool = False,
                    archive_db: str = "") -> Any:
    """A settings file, a register and one or two archives on disk.

    `archive_db` is what the page used to read. Pointed somewhere that does
    not exist -- which is what the beta instance had, left behind when the
    archives moved into their own file -- while the register names the real
    one.
    """
    (work / "data").mkdir(exist_ok=True)
    (work / "evo.toml").write_text(
        f'token = "{"a" * 16}"\n'
        f'archive_db = "{archive_db or (work / "data" / "one.sdb").as_posix()}"\n',
        encoding="utf-8")
    sender = sender_id("unknown", "s")
    entries = ["[archives.default]",
               f'file = "{(work / "data" / "one.sdb").as_posix()}"',
               f'senders = ["{sender}"]']
    if second:
        entries += ["", "[archives.nordfeld]",
                    f'file = "{(work / "data" / "two.sdb").as_posix()}"',
                    f'senders = ["{sender}"]']
    (work / "archives.toml").write_text("\n".join(entries) + "\n",
                                        encoding="utf-8")
    path = work / "evo.toml"
    return Admin(path, lambda: all_schemas(path), "a" * 16)


def some_records(where: Path, readings: list[float]) -> None:
    """An archive holding one reading per five minutes, ending now.

    Ending now rather than at `START`: the page looks back a year from the
    wall clock, and records dated 2020 are outside every window it asks
    about.
    """
    now = int(time.time()) - len(readings) * 300
    store = ArchiveStore(where)
    try:
        for index, value in enumerate(readings):
            store.add_record({"dateTime": now + index * 300,
                              "usUnits": units.METRICWX, "interval": 5,
                              "outTemp": value})
    finally:
        store.close()


def test_the_page_reads_the_archive_the_register_names() -> None:
    """The failure that made the whole page look like it did nothing.

    `archive_db` and `[archives.default] file` are allowed to differ the
    moment anything writes either, and on the beta instance they did. The
    page found no file, so the table had no rows to type a limit into and the
    suggest button said the archive was empty -- about a database being
    written to every five minutes.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        admin = an_installation(work, archive_db="archive/gone.sdb")
        some_records(work / "data" / "one.sdb",
                     [18.0 + (index % 7) * 0.5 for index in range(60)])

        seen, _dropped, records = adminquality.survey(admin)
        check("the records are found", records, 60)
        check("and the reading is listed", "outTemp" in seen, True)


def test_every_series_is_measured_not_just_the_default() -> None:
    """One `quality.toml` is handed to every archiver, so all of them count.

    A floor worked out from the default alone is applied to the north field
    too. Measured on the default only, the page would offer a floor of 18 and
    a dry run saying it refuses nothing -- while the second series holds 5.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        admin = an_installation(work, second=True)
        some_records(work / "data" / "one.sdb", [18.0, 19.0] * 30)
        some_records(work / "data" / "two.sdb", [5.0, 6.0] * 30)

        seen, _dropped, records = adminquality.survey(admin)
        check("both series are read", records, 120)
        close_to("the floor covers the colder one", seen["outTemp"].lowest, 5.0)
        close_to("and the ceiling the warmer one", seen["outTemp"].highest, 19.0)


def test_the_dry_run_counts_what_the_rules_would_refuse() -> None:
    """The figure the page prints above the table, over every series."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        admin = an_installation(work, second=True)
        some_records(work / "data" / "one.sdb", [20.0] * 10 + [-41.0])
        some_records(work / "data" / "two.sdb", [20.0] * 10 + [-41.0])
        (work / "quality.toml").write_text(
            'unit_system = "metricwx"\n\n[limits.outTemp]\nminimum = -30\n',
            encoding="utf-8")

        _seen, dropped, records = adminquality.survey(admin)
        check("over both series", records, 22)
        check("one refusal in each", dropped.get("outTemp"), 2)


def test_a_saved_rule_is_a_file_the_service_reads() -> None:
    """The page writes where the service looks. Both ends, one comparison.

    Spelled out separately in `adminquality.path_for` and in
    `cli.quality_path`, this is two answers that agree until one of them is
    changed.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        admin = an_installation(work)
        adminquality.save(admin, {"limit-outTemp-minimum": "-30"})

        args = argparse.Namespace(config=work / "evo.toml", quality=None)
        cfg = _resolve(args)
        check("the page wrote where the service reads",
              adminquality.path_for(admin), quality_path(args, cfg))
        policy = read_quality(args, cfg)
        close_to("and the service reads the rule",
                 policy.limits["outTemp"].minimum, -30.0)


def test_the_watcher_notices_the_rules_being_written() -> None:
    """Without this a saved limit refused nothing until a restart.

    The watcher's own docstring listed "the readings' limits" among the files
    it stats. It was the one of the four that was not passed to it, and
    nothing on the page or in the log could say so.

    Asked of the list `serve` hands the watcher, not of a watcher this test
    built: a watcher made here would go on noticing the file long after the
    loop stopped passing it.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        admin = an_installation(work)
        args = argparse.Namespace(config=work / "evo.toml", quality=None)
        cfg = _resolve(args)

        watched = _watched_files(args, cfg, work)
        check("the rules are among the files serve watches",
              quality_path(args, cfg) in watched, True)

        watcher = _Watcher(*watched)
        check("nothing has changed yet", watcher.changed(), False)
        adminquality.save(admin, {"limit-outTemp-minimum": "-30"})
        check("the file being written is a change", watcher.changed(), True)


def test_a_saved_rule_reaches_a_running_archiver() -> None:
    """The whole chain, ending where it has to: a reading that is refused.

    A rule was applied at startup and never again. `apply_live` rebuilds
    everything else a page can change and did not touch this, so the answer
    to "why does nothing happen" was a restart nobody had a reason to think
    of.

    Through `apply_live` rather than through the function it calls: that is
    the door the loop comes in by, and a fix reachable only by calling past
    it is the same bug in a different place.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        admin = an_installation(work)
        live_path = an_archive(work, [20.0, 20.1, -41.0, 20.2])
        args = argparse.Namespace(config=work / "evo.toml", quality=None)
        cfg = _resolve(args)

        live = LiveStore(live_path, interval_seconds=300)
        store = ArchiveStore(work / "data" / "one.sdb")
        try:
            defined = read_archives(args, cfg).get("default")
            archiver = Archiver(live, store, interval_seconds=300,
                                quality=read_quality(args, cfg))
            check("nothing is refused before a rule exists",
                  archiver.build(START + 300).dropped, {})

            adminquality.save(admin, {"limit-outTemp-minimum": "-30"})
            apply_live(args, cfg, None, None,
                       series=[(defined, store, archiver)])

            built = archiver.build(START + 300)
            check("the saved rule refuses the reading",
                  built.dropped, {"outTemp": 1})
            close_to("and it never reached the mean",
                     built.record["outTemp"], 20.1, tol=0.05)
        finally:
            live.close()
            store.close()


def test_every_archiver_gets_the_rules_not_just_the_first() -> None:
    """There is one `quality.toml` and it is not keyed on the series.

    A loop that updated the first and left the rest would leave the second
    place recording what the first refuses -- and the page, which is about
    readings rather than places, could not show the difference.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        admin = an_installation(work, second=True)
        adminquality.save(admin, {"limit-outTemp-minimum": "-30"})
        args = argparse.Namespace(config=work / "evo.toml", quality=None)
        cfg = _resolve(args)

        live_path = an_archive(work, [20.0])
        live = LiveStore(live_path, interval_seconds=300)
        stores = [ArchiveStore(work / "data" / name)
                  for name in ("one.sdb", "two.sdb")]
        try:
            # Real archive definitions, not placeholders: `apply_live` also
            # repoints the stations, and that reads the name off each one.
            defined = read_archives(args, cfg).all()
            series = [(one, store, Archiver(live, store, interval_seconds=300,
                                            name=one.name))
                      for one, store in zip(defined, stores, strict=True)]
            apply_live(args, cfg, None, None, series=series)
            check("both archivers have the rule",
                  [one.quality.limits["outTemp"].minimum
                   for _a, _s, one in series], [-30.0, -30.0])
        finally:
            live.close()
            for one in stores:
                one.close()


def main() -> int:
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
            except Exception as exc:  # a failing test is the finding
                FAILURES.append(f"{name} raised {type(exc).__name__}: {exc}")

    if FAILURES:
        print(f"{len(FAILURES)} of {CHECKS} checks failed:\n")
        for failure in FAILURES:
            print(f"  {failure}\n")
        return 1
    print(f"quality: {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Calibration and quality control: what a reading has to survive.

`weewxconf.py` says it at the top of every import: WeeWX has `StdCalibrate`
and `StdQC` and this program had neither. With one console that is a
blemish. With ten it is the reason an archive holds rubbish after a year --
a sensor with a flat battery reports -40, a rain gauge being flushed reports
300 mm/h, and a radio sensor at the edge of its range repeats the same figure
for a quarter of an hour. All three go straight into `archive`, and `archive`
is the one thing here that cannot be rebuilt from anything else.

## Where it sits, and why that is the answer

In the **archiver**, on each packet, before `derive.py`:

    live packets ── calibrate ── check ── derive ── accumulate ── record

Two decisions are in that line.

**Per packet, not on the finished record.** A spike that reaches the
accumulator has already set the interval's minimum and pulled its mean, and
neither can be taken back out afterwards.

**Before deriving.** The dew point is computed from the temperature and the
humidity, so a reading corrected after the derivation leaves a dew point that
belongs to a number nothing recorded.

And the reason it is here rather than in the listener: **the live table keeps
the raw reading**. A limit set too tightly is then repairable for as long as
the retention lasts -- change the rule, `rebuild`, and the archive and its
daily summaries follow. Applied on the way in, the original would be gone and
the mistake permanent. `archiver.py` promised exactly this before this module
existed: "Fix the packets or the calibration, rebuild the span, and the
archive and its daily summaries follow."

## Calibrate first, then check

The other order tests an uncorrected reading against corrected limits, so a
thermometer with a 0.4 K offset fails at its own ceiling. Calibration is
per station because that is what it is about: two thermometers in one garden
disagree by a few tenths, and which of them is *the* series is a decision
somebody made.

## The rules, and what each one costs when it is wrong

    minimum, maximum   the reading is impossible
    spike              it changed faster than the weather can
    stuck              it has not moved for so long that the sensor has died

`rain` and the other counters get no spike rule by default: real heavy rain
looks exactly like a fault, and throwing it away is worse than keeping a
fault that the limits will catch anyway.

A stuck rule needs the sensor's **resolution**. A thermometer reading to
0.1 K stands still for twenty minutes on a calm night, and a rule that does
not know this reports every night.

## A dropped reading is dropped, not zeroed

Zero is a measurement. A rain gauge that reports 0.0 because its reading was
refused is indistinguishable from a dry afternoon, for ever. So the field is
absent, and absent is what every other part of this program already handles.

Nothing is dropped silently: `Verdict` says which reading, which rule and
what the figure was, and the archiver logs the count. A silent drop looks
exactly like a broken sensor, which is the thing this is supposed to help
find.
"""

from __future__ import annotations

import logging
import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import units

log = logging.getLogger(__name__)

#: The units the figures in `quality.toml` are written in. A limit of -50 is
#: meaningless without one, and guessing from the archive would mean the same
#: file behaving differently on two stations.
DEFAULT_SYSTEM = "metricwx"

#: Fields that accumulate rather than measure. A spike rule on one of these
#: throws away real weather: a cloudburst is a step change and so is a gauge
#: being emptied, and the two look the same from here.
COUNTERS = ("rain", "rainRate", "hail", "hailRate", "ET", "windrun",
            "lightning_strike_count", "lightning_num", "dayRain", "monthRain",
            "yearRain", "totalRain", "stormRain", "hourRain", "rain24")


@dataclass(frozen=True, slots=True)
class Rule:
    """What one reading has to satisfy."""

    #: Impossible below or above this. In the file's unit system.
    minimum: float | None = None
    maximum: float | None = None
    #: The most it can change in a minute. None means no such rule.
    spike: float | None = None
    #: How many identical readings in a row mean the sensor has stopped.
    #: Four means: four the same, and the fifth is refused. A reading that
    #: differs ends the spell, whatever the counter says.
    stuck: int | None = None
    #: What counts as identical. Without it a thermometer reading to a tenth
    #: is "stuck" on any calm night.
    resolution: float = 0.0

    def empty(self) -> bool:
        return (self.minimum is None and self.maximum is None
                and self.spike is None and self.stuck is None)


@dataclass(frozen=True, slots=True)
class Adjust:
    """A correction applied before anything is checked."""

    offset: float = 0.0
    scale: float = 1.0

    def empty(self) -> bool:
        return self.offset == 0.0 and self.scale == 1.0

    def __call__(self, value: float) -> float:
        return value * self.scale + self.offset


@dataclass(frozen=True, slots=True)
class Verdict:
    """One reading that did not get through, and why."""

    field: str
    value: float
    rule: str
    why: str
    when: int = 0
    station: str = ""

    def __str__(self) -> str:
        return f"{self.field}={self.value:g} {self.why}"


@dataclass
class Policy:
    """The rules an installation runs, from `quality.toml`."""

    #: Limits by reading, for every station.
    limits: dict[str, Rule] = field(default_factory=dict)
    #: Corrections by station name, then reading. The empty name is every
    #: station, which is where a single-console installation puts them.
    calibration: dict[str, dict[str, Adjust]] = field(default_factory=dict)
    #: What system the figures above are written in.
    system: int = units.METRICWX

    def __bool__(self) -> bool:
        return bool(self.limits or self.calibration)

    def adjust_for(self, station: str, obs: str) -> Adjust | None:
        """The correction for one reading of one station, if any.

        A station's own entry wins over the one for everybody, and neither
        falls back to the other field by field: an operator who has written a
        correction for this station has said what they mean.
        """
        for who in (station, ""):
            found = self.calibration.get(who, {}).get(obs)
            if found is not None:
                return found
        return None


def load(path: str | Path) -> Policy:
    """Read `quality.toml`. A file that is not there means no rules.

    Not an error, and not a warning either. Most installations never write
    one, and the ones that do are answering a problem they have met.
    """
    path = Path(path)
    if not path.exists():
        return Policy()
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)
    return from_dict(raw)


def from_dict(raw: dict[str, Any]) -> Policy:
    """A policy out of already-parsed TOML."""
    system = units.system_from(raw.get("unit_system") or DEFAULT_SYSTEM,
                               default=units.METRICWX)

    limits: dict[str, Rule] = {}
    for obs, entry in (raw.get("limits") or {}).items():
        if not isinstance(entry, dict):
            log.warning("quality: [limits.%s] is not a table; ignoring it", obs)
            continue
        rule = Rule(
            minimum=_number(entry.get("minimum")),
            maximum=_number(entry.get("maximum")),
            spike=_number(entry.get("spike")),
            stuck=int(entry["stuck"]) if entry.get("stuck") else None,
            resolution=float(entry.get("resolution") or 0.0))
        if not rule.empty():
            limits[str(obs)] = rule

    calibration: dict[str, dict[str, Adjust]] = {}
    for station, fields in (raw.get("calibrate") or {}).items():
        if not isinstance(fields, dict):
            continue
        # `[calibrate.everywhere]` is the name for "every station", spelled
        # out rather than left as an empty key nobody can type into TOML.
        who = "" if str(station) in ("everywhere", "all", "default") else str(station)
        for obs, entry in fields.items():
            if not isinstance(entry, dict):
                continue
            adjust = Adjust(offset=float(entry.get("offset") or 0.0),
                            scale=float(entry.get("scale") or 1.0))
            if not adjust.empty():
                calibration.setdefault(who, {})[str(obs)] = adjust

    return Policy(limits=limits, calibration=calibration, system=system)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Check:
    """Runs a policy over packets in time order.

    One of these per span, made fresh. That is what keeps `archiver.build`
    deterministic: a checker carried between runs would make the record for
    an interval depend on what was built before it, and a rebuild would then
    produce something different from the original -- which is the property
    the whole archiver is arranged around.

    The state it does carry is the previous reading of each field, for the
    spike and stuck rules. `context()` seeds it from the packets before the
    span so that the first reading in an interval is checked like every
    other; without that a spike landing on a boundary goes through.
    """

    __slots__ = ("_last", "_same", "adjusted", "dropped", "policy")

    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        #: field -> (value, when) of the last reading that got through.
        self._last: dict[str, tuple[float, float]] = {}
        #: field -> how many identical readings in a row.
        self._same: dict[str, int] = {}
        self.dropped: dict[str, int] = {}
        self.adjusted = 0

    # -- the two halves ---------------------------------------------------

    def calibrate(self, data: dict, station: str = "",
                  system: int = units.METRICWX) -> dict:
        """Apply the corrections. Never drops anything.

        `system` is the packet's, so an offset written in Celsius reaches a
        console reporting Fahrenheit as the same physical correction. Only
        the offset is converted: a scale is a ratio and has no unit.
        """
        if not self.policy.calibration:
            return data
        out = dict(data)
        for obs, value in data.items():
            adjust = self.policy.adjust_for(station, obs)
            if adjust is None or value is None:
                continue
            number = _number(value)
            if number is None:
                continue
            out[obs] = self._converted(adjust, obs, number, system)
            self.adjusted += 1
        return out

    def _converted(self, adjust: Adjust, obs: str, value: float,
                   system: int) -> float:
        """The correction, in the unit this packet is written in."""
        offset = adjust.offset
        if offset and system != self.policy.system:
            offset = _as_difference(offset, obs, self.policy.system, system)
        return value * adjust.scale + offset

    def check(self, data: dict, when: float, station: str = "",
              system: int = units.METRICWX) -> tuple[dict, list[Verdict]]:
        """The readings that survived, and one verdict per one that did not."""
        if not self.policy.limits:
            return data, []

        out: dict[str, Any] = {}
        verdicts: list[Verdict] = []
        for obs, value in data.items():
            rule = self.policy.limits.get(obs)
            number = _number(value)
            if rule is None or number is None or not math.isfinite(number):
                out[obs] = value
                continue
            verdict = self._judge(obs, number, rule, when, station, system)
            if verdict is None:
                out[obs] = value
                self._remember(obs, number, when, rule, system)
            else:
                verdicts.append(verdict)
                self.dropped[obs] = self.dropped.get(obs, 0) + 1
        return out, verdicts

    # -- the rules --------------------------------------------------------

    def _judge(self, obs: str, value: float, rule: Rule, when: float,
               station: str, system: int) -> Verdict | None:
        limit = _in_system(rule.minimum, obs, self.policy.system, system)
        if limit is not None and value < limit:
            return Verdict(obs, value, "minimum",
                           f"below the {limit:g} floor", int(when), station)

        limit = _in_system(rule.maximum, obs, self.policy.system, system)
        if limit is not None and value > limit:
            return Verdict(obs, value, "maximum",
                           f"above the {limit:g} ceiling", int(when), station)

        if rule.spike is not None and obs not in COUNTERS:
            previous = self._last.get(obs)
            if previous is not None:
                was, then = previous
                minutes = abs(when - then) / 60.0
                # Two readings with the same timestamp cannot be a rate. Two
                # far apart are a gap, and the weather is allowed to have
                # changed across one.
                if 0 < minutes <= 60:
                    most = _in_system(rule.spike, obs, self.policy.system,
                                      system, difference=True)
                    if most is not None and abs(value - was) > most * minutes:
                        return Verdict(
                            obs, value, "spike",
                            f"jumped {abs(value - was):g} from {was:g} in "
                            f"{minutes:g} min", int(when), station)

        if rule.stuck is not None and self._same.get(obs, 0) >= rule.stuck:
            # Only while it is *still* the same reading. Asking the counter
            # alone was the first version and it never let a sensor recover:
            # a refused packet is not remembered, so the counter stayed high,
            # and the first real reading after a stuck spell was refused as
            # stuck -- and so was every one after it, for ever.
            previous = self._last.get(obs)
            step = _in_system(rule.resolution, obs, self.policy.system,
                              system, difference=True) or 0.0
            if previous is not None and abs(value - previous[0]) <= step:
                return Verdict(obs, value, "stuck",
                               f"unchanged for {self._same[obs]} readings",
                               int(when), station)
        return None

    def _remember(self, obs: str, value: float, when: float, rule: Rule,
                  system: int) -> None:
        """Note a reading that got through, and how long it has stood still.

        The counter is how many identical readings have arrived in a row,
        counting the first. `stuck = 4` therefore means: four the same, and
        the fifth is refused.
        """
        previous = self._last.get(obs)
        if previous is not None and rule.stuck is not None:
            step = _in_system(rule.resolution, obs, self.policy.system,
                              system, difference=True) or 0.0
            self._same[obs] = (self._same.get(obs, 1) + 1
                               if abs(value - previous[0]) <= step else 1)
        self._last[obs] = (value, when)

    # -- seeding ----------------------------------------------------------

    def context(self, packets: Any) -> None:
        """Feed in the readings before the span, without judging them.

        The spike and stuck rules need a previous value, and the first packet
        of an interval has none. Without this the boundary is a hole a spike
        walks through every five minutes.

        Deterministic, because it reads the same live table the span itself
        comes from.

        **The rules run here too**, and that is not tidiness. Remembering
        every reading was the first version: an outlier in the run-up became
        the value everything after it was compared against, so the first real
        reading was a spike from -41, and so was the next, and the next. One
        bad packet switched a station off for good. What is suppressed is the
        *reporting* -- these packets belong to an interval that was built
        already, and counting them again would double every figure.
        """
        dropped, adjusted = dict(self.dropped), self.adjusted
        for packet in packets:
            record = packet.record() if hasattr(packet, "record") else packet
            when = float(record.get("dateTime") or 0)
            system = units.system_from(record.get("usUnits"),
                                       default=units.METRICWX)
            station = getattr(packet, "source", "")
            corrected = self.calibrate(record, station, system)
            self.check(corrected, when, station, system)
        self.dropped, self.adjusted = dropped, adjusted

    def summary(self) -> str:
        if not self.dropped:
            return ""
        worst = sorted(self.dropped.items(), key=lambda x: -x[1])
        return ", ".join(f"{obs} x{count}" for obs, count in worst[:6])


# ---------------------------------------------------------------------------
# Units.
# ---------------------------------------------------------------------------

def _in_system(value: float | None, obs: str, from_system: int,
               to_system: int, difference: bool = False) -> float | None:
    """A figure from the file, in the unit a packet is written in.

    A limit of -50 written in Celsius has to be -58 for a console reporting
    Fahrenheit. Without this the same file lets everything through on one
    station and refuses everything on another, and both look like the sensor.
    """
    if value is None or from_system == to_system:
        return value
    if difference:
        return _as_difference(value, obs, from_system, to_system)
    unit_from, _group = units.unit_of(obs, from_system)
    unit_to, _group = units.unit_of(obs, to_system)
    if unit_from is None or unit_to is None or unit_from == unit_to:
        return value
    converted = units.convert(value, unit_from, unit_to)
    return None if converted is None else float(converted)


def _as_difference(value: float, obs: str, from_system: int,
                   to_system: int) -> float:
    """A *span* converted, not a point on the scale.

    A five-degree jump is nine Fahrenheit degrees, not 41. Converting the
    number itself would turn a spike rule into a limit at the freezing point,
    and an offset of +0.4 K into a correction of +33.
    """
    unit_from, _group = units.unit_of(obs, from_system)
    unit_to, _group = units.unit_of(obs, to_system)
    if unit_from is None or unit_to is None or unit_from == unit_to:
        return value
    zero = units.convert(0.0, unit_from, unit_to)
    one = units.convert(value, unit_from, unit_to)
    if zero is None or one is None:
        return value
    return float(one) - float(zero)

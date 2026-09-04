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
thermometer with a 0.4 K offset fails at its own ceiling. Calibration is per
sender because that is what it is about: two thermometers in one garden
disagree by a few tenths. The key is the canonical sender ID, never its
editable display name.

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
from .db.live import sender_parts

log = logging.getLogger(__name__)

# One warning per obsolete key and process. The Admin page reads the file more
# than once per render; repeating the same migration notice is log noise.
_obsolete_said: set[str] = set()

#: Where the rules live, beside the configuration like `plots.toml` and
#: `archives.toml`. A constant because three places need the same answer --
#: the service that reads it, the settings page that writes it, and the
#: watcher that notices the write. Spelled out in two of them and forgotten
#: in the third, a rule saved on the page reached the running process only
#: after somebody restarted the container.
FILENAME = "quality.toml"

#: The units the figures in `quality.toml` are written in. A limit of -50 is
#: meaningless without one, and guessing from the archive would mean the same
#: file behaving differently on two stations.
DEFAULT_SYSTEM = "metricwx"

#: Readings that wrap. The difference between 359 and 1 is two degrees, not
#: 358, and a rule that subtracts them reports a gale every time the wind
#: passes north. Same property that stops a wind direction being drawn as a
#: line in `grafana/style.py`.
CIRCULAR = ("group_direction",)

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
    #: Corrections by canonical sender ID, then reading. The empty name is
    #: every sender, which is where a single-console installation puts them.
    calibration: dict[str, dict[str, Adjust]] = field(default_factory=dict)
    #: What system the figures above are written in.
    system: int = units.METRICWX
    #: Pre-canonical files keyed corrections by a mutable station label. Keep
    #: those tables so an Admin save is lossless, but never execute them: a
    #: renamed or reused label must not apply a physical correction to the
    #: wrong sender.
    obsolete_calibration: dict[str, dict[str, Adjust]] = field(
        default_factory=dict)

    def __post_init__(self) -> None:
        """Keep only canonical sender keys active; retain old labels inert."""
        active: dict[str, dict[str, Adjust]] = {}
        obsolete = {str(who): dict(fields)
                    for who, fields in self.obsolete_calibration.items()}
        for who, fields in self.calibration.items():
            sender = str(who)
            if not sender or _is_sender_id(sender):
                active.setdefault(sender, {}).update(fields)
                continue
            obsolete.setdefault(sender, {}).update(fields)
            if sender not in _obsolete_said:
                _obsolete_said.add(sender)
                log.warning(
                    "quality: calibration for legacy station name %r is ignored; "
                    "replace it with the canonical sender ID from the Senders page",
                    sender)
        self.calibration = active
        self.obsolete_calibration = obsolete

    def __bool__(self) -> bool:
        return bool(self.limits or self.calibration)

    def adjust_for(self, sender: str, obs: str) -> Adjust | None:
        """The correction for one reading from one canonical sender, if any.

        A sender's own entry wins over the one for everybody, and neither
        falls back to the other field by field: an operator who has written a
        correction for this sender has said what they mean.
        """
        specific = sender if _is_sender_id(sender) else None
        for who in (specific, ""):
            if who is None:
                continue
            found = self.calibration.get(who, {}).get(obs)
            if found is not None:
                return found
        return None


def _is_sender_id(value: str) -> bool:
    """Whether a value is the canonical, reversible live-journal key."""
    try:
        sender_parts(str(value))
    except ValueError:
        return False
    return True


def sender_for(packet: Any) -> str:
    """The canonical calibration key carried by a packet.

    A placer may bind a retained pre-journal row to its modern canonical
    member in ``source``. Otherwise the key is derived from the immutable
    driver/identity pair. Friendly labels and bare identities are never
    returned.
    """
    placed = str(getattr(packet, "source", "") or "")
    if _is_sender_id(placed):
        return placed
    canonical = str(getattr(packet, "sender_id", "") or "")
    return canonical if _is_sender_id(canonical) else ""


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
    for sender, fields in (raw.get("calibrate") or {}).items():
        if not isinstance(fields, dict):
            continue
        # `[calibrate.everywhere]` is the name for "every sender", spelled
        # out rather than left as an empty key nobody can type into TOML.
        who = "" if str(sender) in ("everywhere", "all", "default") else str(sender)
        for obs, entry in fields.items():
            if not isinstance(entry, dict):
                continue
            adjust = Adjust(offset=float(entry.get("offset") or 0.0),
                            scale=float(entry.get("scale") or 1.0))
            if not adjust.empty():
                calibration.setdefault(who, {})[str(obs)] = adjust

    return Policy(limits=limits, calibration=calibration, system=system)


def _circular(obs: str) -> float | None:
    """The wrap point for a reading that has one, or None."""
    if units.group_of(obs) in CIRCULAR:
        return 360.0
    return None


def _apart(value: float, was: float, wrap: float | None) -> float:
    """How far two readings are apart, the short way round where that
    applies."""
    change = abs(value - was)
    if wrap:
        change = min(change, wrap - change)
    return change


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
                    change = _apart(value, was, _circular(obs))
                    if most is not None and change > most * minutes:
                        return Verdict(
                            obs, value, "spike",
                            f"jumped {change:g} from {was:g} in "
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
            sender = sender_for(packet)
            corrected = self.calibrate(record, sender, system)
            self.check(corrected, when, sender, system)
        self.dropped, self.adjusted = dropped, adjusted

    def summary(self) -> str:
        if not self.dropped:
            return ""
        worst = sorted(self.dropped.items(), key=lambda x: -x[1])
        return ", ".join(f"{obs} x{count}" for obs, count in worst[:6])


# ---------------------------------------------------------------------------
# Working rules out of what a station has actually recorded.
# ---------------------------------------------------------------------------

#: How far outside what has been seen a limit is put. A ceiling at exactly
#: the highest reading ever recorded refuses the next hot afternoon.
HEADROOM = 0.25

#: And a floor under that, so a reading that barely moves does not get a
#: limit a millimetre away from it. In the unit of the reading.
LEAST_HEADROOM = 2.0

#: How small a reading's whole range may be, against its own size, before it
#: is taken as something that does not vary.
#:
#: An archive column holds more than measurements. `lightning_time` is a Unix
#: timestamp, a battery field is a flag, a firmware field is a version. All of
#: them sit still, and a rule worked out from one refuses the next value that
#: differs -- measured on a real station: a ceiling two seconds above a
#: lightning timestamp refused 36% of the records it was derived from, and a
#: spike rule of zero on a battery flag refuses every change there will ever
#: be.
#:
#: A ratio rather than a list of field names, because the next station has a
#: field nobody here has heard of.
VARIES = 1e-6

#: And how much of a reading's history may be one unbroken still spell before
#: standing still is taken as its normal state rather than as a fault. A
#: battery flag that has not moved for a quarter of the year is not a dead
#: sensor.
STILL_ENOUGH = 0.2

#: The most of a reading's whole range its resolution is allowed to be.
#:
#: The resolution is measured as the smallest change ever seen between two
#: readings, which is right for a real sensor and wrong for a coarse record:
#: a wind speed going 0, 2, 4, 1, 3 has a smallest change of 2, and taking
#: that as the resolution makes every ordinary step count as "unchanged". The
#: stuck rule then fires on data it was worked out from. A real sensor's
#: resolution is a small fraction of its range; anything larger was not a
#: resolution, it was just the coarsest thing on record.
FINEST = 0.01

#: The fastest change ever seen, times this. A spike rule at exactly the
#: largest jump on record refuses the next storm front.
SPIKE_ALLOWANCE = 2.0

#: What physics allows, whatever the readings say. A suggestion worked out
#: from four years of data still put the floor for wind speed at -2 and the
#: ceiling for humidity at 114, because it only knew what it had seen and
#: added room in both directions.
#:
#: By unit group, so a driver's own fields are covered: `units.contribute`
#: tells us a soil probe reports a percentage, and a percentage runs 0 to
#: 100 on every station.
PHYSICAL = {
    "group_percent": (0.0, 100.0),
    "group_humidity": (0.0, 100.0),
    "group_speed": (0.0, None),
    "group_rain": (0.0, None),
    "group_rainrate": (0.0, None),
    "group_direction": (0.0, 360.0),
    "group_radiation": (0.0, None),
    "group_uv": (0.0, None),
    "group_distance": (0.0, None),
    "group_interval": (0.0, None),
    "group_count": (0.0, None),
}


@dataclass
class Seen:
    """What one reading has actually done. The basis for a suggestion."""

    obs: str
    count: int = 0
    lowest: float = math.inf
    highest: float = -math.inf
    #: The fastest change per minute between consecutive readings.
    fastest: float = 0.0
    #: The longest run of readings that did not move, and by how little.
    longest_still: int = 0
    #: The smallest non-zero step between consecutive readings -- the
    #: sensor's resolution, measured rather than looked up.
    step: float = math.inf

    def varies(self) -> bool:
        """Whether this reading actually moves.

        Against its own size, not against a fixed figure: a span of four is
        the whole range of a lightning timestamp and nothing at all for a
        number near 1.8 billion. See `VARIES`.
        """
        span = self.highest - self.lowest
        if span <= 0:
            return False
        scale = max(abs(self.highest), abs(self.lowest), 1.0)
        return span / scale > VARIES

    def rule(self) -> Rule:
        """A rule with room in it, inside what physics allows.

        Never tighter than what has been seen, and never wider than what can
        happen: the room added below the lowest reading would otherwise put
        the floor for wind speed at -2.

        And nothing at all for a reading that does not vary. A column holding
        a flag or a timestamp is not a measurement, and every rule derived
        from one refuses the next value that differs.
        """
        if not self.varies():
            return Rule()

        span = max(self.highest - self.lowest, 0.0)
        # The floor under the headroom is relative as well. Two units is
        # generous for a temperature and invisible next to a timestamp.
        room = max(span * HEADROOM, LEAST_HEADROOM,
                   abs(self.highest) * VARIES)
        floor, ceiling = PHYSICAL.get(units.group_of(self.obs) or "",
                                      (None, None))

        low = self.lowest - room
        if floor is not None:
            low = max(low, floor)
        high = self.highest + room
        if ceiling is not None:
            high = min(high, ceiling)

        counter = self.obs in COUNTERS
        # A spike rule of zero is not a rule, it is a prohibition: it refuses
        # every change there will ever be. It comes from a reading whose
        # fastest observed change rounded to nothing.
        spike = round(self.fastest * SPIKE_ALLOWANCE, 3)
        # Standing still is this reading's normal state where it has done it
        # for a large part of its history, and a rule about it would fire on
        # the ordinary case.
        settled = (self.longest_still >= self.count * STILL_ENOUGH
                   if self.count else True)
        return Rule(
            minimum=round(low, 3),
            maximum=round(high, 3),
            # No spike rule for a counter, and none for a reading that
            # wraps: the wind passing north is not a jump of 358 degrees.
            spike=(spike if spike > 0 and not counter
                   and not _circular(self.obs) else None),
            # Twice the longest quiet spell on record, and never fewer than
            # ten: a rule at the observed figure fires on the first calm
            # night that is calmer than the ones measured.
            #
            # Never for a counter. Rain sits at zero for a fortnight in
            # August, and that is the weather rather than a dead gauge.
            stuck=(max(10, self.longest_still * 2)
                   if self.longest_still and not counter and not settled
                   else None),
            resolution=self.resolution())

    def resolution(self) -> float:
        """The smallest step this sensor makes, as far as can be told."""
        if not math.isfinite(self.step):
            return 0.0
        span = max(self.highest - self.lowest, 0.0)
        finest = span * FINEST if span else self.step
        return round(min(self.step, finest), 4)

    def as_toml(self) -> str:
        rule = self.rule()
        lines = [f"[limits.{self.obs}]",
                 f"minimum = {rule.minimum:g}",
                 f"maximum = {rule.maximum:g}"]
        if rule.spike is not None:
            lines.append(f"spike = {rule.spike:g}      "
                         f"# per minute; fastest seen {self.fastest:g}")
        if rule.stuck is not None:
            lines.append(f"stuck = {rule.stuck}        "
                         f"# longest still spell seen: {self.longest_still}")
        if rule.resolution:
            lines.append(f"resolution = {rule.resolution:g}   "
                         f"# smallest step seen: {self.step:g}")
        return "\n".join(lines)


def watch(rows: Any, fields: Any = None,
          system: int = units.METRICWX) -> dict[str, Seen]:
    """Measure what each reading has done, over records in time order.

    Fed the archive for the limits and the live table for the rest. Both,
    because they answer different questions: the archive has years and knows
    how cold it gets, and only the live table has the packet-to-packet steps
    a spike rule and a resolution are about. Suggesting a spike rule from
    five-minute records would produce one several times too tight, because
    the weather has five minutes to move between them.
    """
    seen: dict[str, Seen] = {}
    last: dict[str, tuple[float, float]] = {}
    still: dict[str, int] = {}

    for row in rows:
        when = float(row.get("dateTime") or 0)
        # Converted into the system the file is written in. Without this a
        # station whose console reports Fahrenheit gets a floor of 38 and a
        # ceiling of 86, which look like plausible figures and are the wrong
        # ones the moment they are read back as Celsius.
        was = units.system_from(row.get("usUnits"), default=system)
        for obs, value in row.items():
            if obs in ("dateTime", "usUnits", "interval"):
                continue
            if fields is not None and obs not in fields:
                continue
            number = _number(value)
            if number is None or not math.isfinite(number):
                continue
            if was != system:
                converted = _in_system(number, obs, was, system)
                if converted is None:
                    continue
                number = converted

            entry = seen.get(obs)
            if entry is None:
                entry = seen[obs] = Seen(obs)
            entry.count += 1
            entry.lowest = min(entry.lowest, number)
            entry.highest = max(entry.highest, number)

            previous = last.get(obs)
            if previous is not None:
                # Not `was`: that holds the row's unit system, and shadowing
                # it here made every field after the first convert as though
                # the previous *reading* were a system number. One field per
                # record hid it completely; two showed it at once.
                before, then = previous
                minutes = (when - then) / 60.0
                change = _apart(number, before, _circular(obs))
                if 0 < minutes <= 60:
                    entry.fastest = max(entry.fastest, change / minutes)
                if change == 0:
                    still[obs] = still.get(obs, 1) + 1
                    entry.longest_still = max(entry.longest_still, still[obs])
                else:
                    still[obs] = 1
                    entry.step = min(entry.step, change)
            last[obs] = (number, when)

    return {obs: entry for obs, entry in seen.items() if entry.count > 1}


def merge(limits: dict[str, Seen], rates: dict[str, Seen]) -> dict[str, Seen]:
    """The floors and ceilings from one measurement, the rest from another.

    The archive knows how cold it gets; the live table knows how fast the
    weather moves between two packets. Neither knows both.
    """
    out: dict[str, Seen] = {}
    for obs, wide in limits.items():
        close = rates.get(obs)
        out[obs] = Seen(
            obs=obs, count=wide.count,
            lowest=wide.lowest, highest=wide.highest,
            fastest=close.fastest if close else wide.fastest,
            longest_still=close.longest_still if close else 0,
            step=close.step if close else math.inf)
    for obs, close in rates.items():
        if obs not in out:
            out[obs] = close
    return out


def across(parts: list[dict[str, Seen]]) -> dict[str, Seen]:
    """One measurement out of several series, widest reading wins.

    There is one `quality.toml` and every archiver gets the same policy out
    of it, so a floor worked out from one place is applied to all of them. A
    page that measured only the default series would offer a ceiling the
    north field exceeds twice a summer, and the dry run beside it would say
    the rule refuses nothing.

    Each series is measured on its own before it gets here -- `watch` carries
    the previous reading forward, and the last record of one place followed
    by the first of another is a step neither sensor took. So this takes one
    `watch` result per series and returns the readings any of them holds,
    each widened to cover all of them.
    """
    out: dict[str, Seen] = {}
    for part in parts:
        for obs, entry in part.items():
            was = out.get(obs)
            if was is None:
                out[obs] = entry
                continue
            out[obs] = Seen(
                obs=obs, count=was.count + entry.count,
                lowest=min(was.lowest, entry.lowest),
                highest=max(was.highest, entry.highest),
                fastest=max(was.fastest, entry.fastest),
                longest_still=max(was.longest_still, entry.longest_still),
                # The finest step any of them resolves. A rule needs the
                # resolution to tell a calm night from a dead sensor, and the
                # coarser figure would call a moving sensor stuck.
                step=min(was.step, entry.step))
    return out


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

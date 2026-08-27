"""Several stations, one measurement series.

WeeWX allows exactly one `station_type`, so combining two stations means a
driver that wraps other drivers. `weewx-metadriver` does that: worker threads
per child, one shared queue, a `source` key on each packet. It works, and its
limitations follow from where it has to sit -- packets are merged as they
arrive, so only the primary driver may produce archive records, only its clock
is read, and a child that dies stays dead.

Here nothing wraps anything. Every source posts to the listener on its own and
its packets land in the live table with its name on them. Merging is not a
thing that happens at the front door; it happens when an interval is worked
out, at which point every packet of that interval is on the table with its
provenance intact. That moves the decision from "which driver is in charge" to
"which source do I believe for *this field* in *this interval*", which is the
question one actually wants answered.

Three consequences worth stating, because they are the argument:

  * A source that goes quiet costs only the fields nobody else has. The next
    source down the list covers the rest, per field, without configuration
    changing.
  * Any source may deliver history. An archive packet is a packet with
    `kind='archive'`; there is no primary.
  * A source is a separate process, so restarting one is systemd's job and not
    something this code has to get right.

The rule is the one from the Kirchdorf station's `messreihe_1d` view: per
field, not per record. A station that measures temperature and rain but cannot
measure snow contributes its temperature and its rain, and the snow comes from
whoever has it.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Rule:
    """Which sources may supply a field, best first."""

    pattern: str
    order: tuple[str, ...]

    def matches(self, obs_type: str) -> bool:
        return fnmatch.fnmatchcase(obs_type, self.pattern)


@dataclass
class Policy:
    """Which source wins for which field.

    Rules are checked in order and the first matching pattern decides, so put
    the specific ones before the general ones:

        Policy.from_config({
            "outTemp":  "garden, roof",   # the garden sensor is the series
            "soil*":    "garden",         # only the garden has soil probes
            "*":        "roof, garden",   # everything else: the roof first
        })

    A source not named anywhere is still used for fields no rule covers.
    Silently dropping a reading because its station was not listed is how
    measurements disappear without anybody noticing.
    """

    rules: list[Rule] = field(default_factory=list)
    #: Seconds after which a source counts as quiet for an interval. None means
    #: presence in the interval is the only test.
    stale_after: int | None = None

    @classmethod
    def from_config(cls, mapping: dict[str, str] | None,
                    stale_after: int | None = None) -> Policy:
        rules = [
            Rule(pattern, tuple(s.strip() for s in order.split(",") if s.strip()))
            for pattern, order in (mapping or {}).items()
        ]
        return cls(rules=rules, stale_after=stale_after)

    @property
    def is_empty(self) -> bool:
        return not self.rules

    def order_for(self, obs_type: str) -> tuple[str, ...] | None:
        """The preference list for one field, or None if no rule covers it."""
        for rule in self.rules:
            if rule.matches(obs_type):
                return rule.order
        return None

    def choose(self, obs_type: str, available: set[str]) -> str | None:
        """Which of the sources that actually have this field should supply it.

        `available` is the set of sources that carried the field in the
        interval being built -- not the set that was configured. A source with
        a broken sensor is not in it, so it does not win by being listed first.
        """
        if not available:
            return None
        order = self.order_for(obs_type)
        if order is None:
            # No rule. With one source that is the answer; with several it is
            # ambiguous, and the caller resolves it by falling back to the
            # ordinary "use everything" behaviour.
            return next(iter(available)) if len(available) == 1 else None
        for name in order:
            if name in available:
                return name
        # Nobody preferred has it. Someone does, or `available` would be empty,
        # and a reading from an unranked station beats no reading at all.
        return min(available)


def sources_by_field(packets: list) -> dict[str, set[str]]:
    """Which sources carried which field, across a list of packets."""
    seen: dict[str, set[str]] = {}
    for packet in packets:
        for obs_type in packet.data:
            seen.setdefault(obs_type, set()).add(packet.source)
    return seen


def apply(packets: list, policy: Policy) -> tuple[list, dict[str, str]]:
    """Thin the packets down to the winning source for each field.

    Returns the packets with losing fields removed, and a record of which
    source each field came from. Packets left with nothing are dropped.

    Nothing is averaged across sources. Two thermometers reading 19 °C and
    21 °C do not make it 20 °C anywhere real -- they are two measurements of
    two places, and picking one is the only honest answer. Whoever wants both
    gives the second its own column.
    """
    if policy.is_empty or not packets:
        return packets, {}

    available = sources_by_field(packets)
    chosen: dict[str, str] = {}
    for obs_type, sources in available.items():
        if len(sources) == 1:
            chosen[obs_type] = next(iter(sources))
            continue
        winner = policy.choose(obs_type, sources)
        if winner is not None:
            chosen[obs_type] = winner

    thinned = []
    for packet in packets:
        keep = {
            name: value for name, value in packet.data.items()
            if chosen.get(name, packet.source) == packet.source
        }
        if keep:
            thinned.append(replace_data(packet, keep))
    return thinned, chosen


def replace_data(packet, data: dict):
    """A copy of a packet carrying different observations."""
    from dataclasses import replace

    return replace(packet, data=data)

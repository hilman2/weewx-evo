"""Which station may fill which column, when two write into one archive.

One station needs none of this. It is the station, its readings go to the
fields they belong in, and nothing here does anything. That case has to stay
exactly as simple as it was, so everything below only comes into play once a
place selects a second station.

With two, the question is unavoidable: they both send `outTemp`, and there is
one `outTemp`. Left alone they take turns writing it every few seconds, and
the column ends up holding a mixture that nothing afterwards can separate --
the same failure contested fields and explicit placement both exist to
prevent, arriving from a different direction.

## Two answers

    separate selection   two places, two files. Nothing is shared, so
                         nothing collides. The right answer whenever the
                         two are genuinely different places.
    a role               one place, and the second station's readings are
                         *moved* rather than dropped. `outTemp` becomes
                         `extraTemp3`, and it keeps its own history.

The role is what a second sensor in one garden wants. A second archive gives
it its own sunrise and its own altitude, which is wrong for a probe ten metres
from the first. An explicit Place-to-Sender mapping can keep, rename or drop
individual fields when the role preset is not enough.

## Honest about the limit

The standard schema has `extraTemp1` to `extraTemp8` and `extraHumid1` to
`extraHumid8`, and nothing of the sort for wind, rain or pressure. So an
extra station contributes its temperature and its humidity, and anything else
it sends has nowhere to go and is dropped rather than written over the main
station's.

That is said here rather than hidden, and the settings page repeats it,
because the alternative is somebody adding a second full weather station and
discovering a year later that only two of its readings were ever kept.

## Where this sits

After the dialect mapping, not before it. The Listener stores the raw values
and the inert mapping supplied with the packet. When the Archiver reads that
row, the Place maps it to `outTemp` first and only then applies the role, so
the move is `outTemp -> extraTemp3`. The role is independent of the driver.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MAIN = "main"
EXTRA = "extra"
ROLES = (MAIN, EXTRA)

#: What an extra station's readings become, given its channel. Only the two
#: that have somewhere to go; everything else is dealt with by the rule below.
SHIFT = {
    "outTemp": "extraTemp%d",
    "outHumidity": "extraHumid%d",
    # The dew point follows its temperature: a second thermometer's dew point
    # in the main station's column would be as wrong as its temperature.
    "dewpoint": "extraDewpoint%d",
}

#: How many channels the standard schema ships for them. Past this a column
#: has to be added, which the placement page offers.
CHANNELS = 8

#: What an extra station keeps regardless of its role.
#:
#: Its own housekeeping: battery levels and signal strengths are already
#: per-sensor names, so two stations do not collide on them, and losing them
#: would mean an extra station whose battery nobody can see.
KEEPS = ("Batt", "batt", "_rssi", "_sig", "BatteryStatus")


def shifted(field: str, channel: int) -> str | None:
    """Where an extra station's reading goes, or None if it has nowhere."""
    pattern = SHIFT.get(field)
    return pattern % channel if pattern else None


def keeps(field: str) -> bool:
    """Whether this is a field an extra station may write unchanged."""
    return any(field.endswith(one) for one in KEEPS)


def next_channel(taken: set[int]) -> int | None:
    """The lowest channel no extra station has yet, or None if all are used."""
    for channel in range(1, CHANNELS + 1):
        if channel not in taken:
            return channel
    return None


#: What has already been said about a station, so that dropping the same
#: fields six times a minute is one log line rather than a stream.
_said: set[str] = set()


def apply(data: dict, role: str, channel: int, station: str = "") -> dict:
    """One extra station's readings, moved out of the main station's way.

    A `main` station is returned untouched, which is the whole of the
    single-station case: no lookup, no copy, nothing.
    """
    if role != EXTRA or not channel:
        return data
    moved = {}
    lost = []
    for name, value in data.items():
        where = shifted(name, channel)
        if where is not None:
            moved[where] = value
        elif keeps(name):
            moved[name] = value
        else:
            # Writing it would put a second sensor's wind or pressure into
            # the main station's column every few seconds, and nothing
            # afterwards can separate that.
            lost.append(name)

    if lost and station not in _said:
        _said.add(station)
        log.info(
            "%s is an extra station on channel %d, so its %s %s nowhere to "
            "go and %s dropped. The schema has extraTemp and extraHumid and "
            "nothing of the sort for these; a column of its own, or an "
            "archive of its own, is what keeps them.",
            station or "this station", channel, ", ".join(sorted(lost)[:6]),
            "has" if len(lost) == 1 else "have",
            "is" if len(lost) == 1 else "are")
    return moved


def collisions(by_station: dict[str, set[str]]) -> dict[str, list[str]]:
    """Fields more than one station of an archive writes.

    Sorted, so the answer is the same every time somebody looks at it.
    """
    owners: dict[str, set[str]] = {}
    for station, fields in by_station.items():
        for field in fields:
            owners.setdefault(field, set()).add(station)
    return {field: sorted(who) for field, who in sorted(owners.items())
            if len(who) > 1}

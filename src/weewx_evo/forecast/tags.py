"""What a template asks for: `$forecast.days[0].tempMax`.

The same idea as `tags.py` and deliberately the same shapes: a forecast
temperature comes back as the same `Value` a measured one does, so a template
formats both the same way and `units.Target` converts both. A page written for
Celsius shows the forecast in Celsius without knowing there is a second
system underneath.

What a skin can write:

    $forecast.now.outTemp                  the hour we are in
    $forecast.now.text                      "Light rain"
    $forecast.now.symbol                    "rain", for whichever icons
    $forecast.hours[3].outTemp              four hours from now
    $forecast.days[0].tempMax               today's high
    $forecast.days[1].sunrise               tomorrow's sunrise
    $forecast.warnings                      the official ones, worst first
    $forecast.warning                       the worst one, or nothing
    $forecast.updated                       when the model last ran
    $forecast.ahead.days[0].tempMax         from the source named "ahead"

`$forecast.<name>` reaching a named source is what makes two of them useful:
the numbers come from one and the warnings from another, and a template can
say which it means. Without a name, everything stored answers -- which is the
right default when there is only one.

**A missing forecast is not an error.** Nothing has been fetched yet on a
station that started a minute ago, and a template must render anyway. Empty
lists and `Unknown` come back, the same as anywhere else in the tag layer, and
the miss is counted so the feed can report it.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .. import units
from ..tags import Unknown, Value
from . import codes

log = logging.getLogger(__name__)


class Entry:
    """One hour or one day, as a template sees it.

    Attribute lookup does the binding, the same way the rest of the tag layer
    works: `$forecast.now.outTemp` finds the field, converts it into what the
    page is written in, and hands back a `Value` that knows how to print
    itself.
    """

    __slots__ = ("item", "kind", "language", "owner", "target")

    def __init__(self, item: Any, target: units.Target,
                 language: Any = None, kind: str = "hour",
                 owner: Any = None) -> None:
        self.item = item
        self.target = target
        self.language = language
        self.kind = kind
        #: The source this came from, so a day can be asked for its own
        #: hours. Only days carry one; an hour has nothing to look up.
        self.owner = owner

    def hours(self, step: int = 1) -> list[Entry]:
        """The hours inside this day, one entry per `step` of them.

        What a page does with it: seven days across the top, and the one
        somebody clicked drawn out hour by hour underneath.

        Today starts at the hour we are in rather than at midnight. A
        forecast for this morning is not a forecast, and a row that opens
        with six hours nobody can act on pushes the ones they can off the
        screen.
        """
        if self.kind != "day" or self.owner is None:
            return []
        start = int(self.item.dateTime)
        stop = start + 86400
        now = int(time.time())
        # Today starts at the hour we are in, and a day still ahead starts
        # where it starts. Written as "is now inside this day" rather than as
        # `max(start, now)`, which quietly returns nothing for a day already
        # over -- and a source told to fetch `past_days` has those.
        if start <= now < stop:
            start = now - 3600
        return self.owner.between(start, stop, step)

    @property
    def dateTime(self) -> Value:  # noqa: N802 - the column's name
        return Value(self.item.dateTime, "unix_epoch", "group_time",
                     "current", self.target)

    @property
    def code(self) -> int | None:
        """The raw WMO code, for a template that wants to switch on it."""
        return self.item.code

    @property
    def text(self) -> str:
        """What the weather is doing, in the station's language."""
        return codes.text(self.item.code, self.language)

    @property
    def symbol(self) -> str:
        """A name for the picture, not the picture.

        Which file that is belongs to whoever draws the page: a skin brings
        its own icons, and mapping to one set here would make every other
        set unusable.
        """
        return codes.symbol(self.item.code, night=self._is_night())

    @property
    def wet(self) -> bool:
        return codes.is_wet(self.item.code)

    @property
    def severe(self) -> bool:
        return codes.is_severe(self.item.code)

    def _is_night(self) -> bool:
        """Whether this hour is after dark, roughly.

        Roughly on purpose: the sun module could answer exactly, and doing so
        would mean a sunrise calculation per hour of a seven-day forecast --
        168 of them per page, to decide which of two icons to draw. The
        source's own sunrise is used when there is one; otherwise the hours
        between eight in the evening and six in the morning are night, which
        is wrong for an hour twice a year and invisible either way.
        """
        if self.kind != "hour":
            return False
        hour = time.localtime(self.item.dateTime).tm_hour
        return hour >= 20 or hour < 6

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        value = getattr(self.item, name, None)
        if value is None:
            # Not every source publishes every field, and a template asking
            # for one a source does not have is ordinary. `Unknown` prints as
            # `?'name'?`, which is what WeeWX does with an unknown tag.
            return Unknown(f"forecast.{name}")
        if name in ("sunrise", "sunset"):
            return Value(value, "unix_epoch", "group_time", "current",
                         self.target)
        # `tempMax` is a temperature, `windMax` is a speed. The archive's
        # names carry the group, so the aliases below are the only mapping
        # this needs.
        obs = ALIASES.get(name, name)
        stored, group = units.unit_of(obs, self.item.usUnits)
        wanted = self.target.unit(group) or stored
        try:
            converted = units.convert(value, stored, wanted)
        except ValueError:
            converted, wanted = value, stored
        return Value(converted, wanted, group, "current", self.target)

    def __str__(self) -> str:
        return f"{self.text} at {time.strftime('%H:%M', time.localtime(self.item.dateTime))}"

    def __bool__(self) -> bool:
        return True


def _severity(code: int | None) -> tuple:
    """A ranking for picking the one code that speaks for a span of hours.

    Not a physical ordering and not meant as one: thunder first, then
    anything falling out of the sky, then the state of the sky itself, and
    within each the WMO number, which runs light to heavy. Sorting on the
    number alone would let "light rain showers" (80) outrank "heavy rain"
    (65), which is the wrong one to put on the tile.
    """
    if code is None:
        return (False, False, -1)
    return (codes.is_severe(code), codes.is_wet(code), int(code))


def _summarise(block: list) -> Any:
    """One hour standing for several, without losing the interesting one.

    Sampling every third hour and taking what happens to be there throws the
    shower away: nothing is sampled at 17:00, so an hour of rain between two
    dry ones disappears from the page entirely. So the entry keeps its own
    hour's temperature -- that is what its label says -- and the worst of the
    span for the sky and for the chance of rain, which is what somebody
    deciding whether to go out has to see.
    """
    from dataclasses import replace

    head = block[0]
    chances = [m.rainProbability for m in block if m.rainProbability is not None]
    falls = [m.rain for m in block if m.rain is not None]
    seen = [m.code for m in block if m.code is not None]
    return replace(
        head,
        rainProbability=max(chances) if chances else head.rainProbability,
        # Summed, not maxed: rain is an accumulation and three hours of it
        # is three hours of it.
        rain=sum(falls) if falls else head.rain,
        code=max(seen, key=_severity) if seen else head.code,
    )


#: Forecast field names that are an archive reading under another name, so
#: `units.py` can say what group they are in. Without this a daily maximum is
#: a number with no unit and no conversion.
ALIASES = {
    "tempMax": "outTemp", "tempMin": "outTemp",
    "windMax": "windSpeed", "windGustMax": "windGust",
    "UVMax": "UV", "sunshine": "dateTime",
}


class WarningTag:
    """One official warning, as a template sees it."""

    __slots__ = ("target", "warning")

    def __init__(self, warning: Any, target: units.Target) -> None:
        self.warning = warning
        self.target = target

    @property
    def starts(self) -> Value:
        return Value(self.warning.starts, "unix_epoch", "group_time",
                     "current", self.target)

    @property
    def ends(self) -> Value:
        return Value(self.warning.ends, "unix_epoch", "group_time",
                     "current", self.target)

    @property
    def active(self) -> bool:
        """Whether it covers this moment.

        A warning that has not started is real and worth showing -- "storm
        tonight" is the point of one -- so this is a question a template asks
        rather than a filter applied for it.
        """
        now = time.time()
        return (self.warning.starts <= now
                and (self.warning.ends is None or self.warning.ends >= now))

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        value = getattr(self.warning, name, None)
        return "" if value is None else value

    def __str__(self) -> str:
        return self.warning.headline or self.warning.event

    def __bool__(self) -> bool:
        return True


class SourceTag:
    """One forecast source. `$forecast.ahead`, or `$forecast` for all of them."""

    __slots__ = ("language", "source", "store", "tags", "target")

    def __init__(self, store: Any, source: str, target: units.Target,
                 language: Any = None, tags: Any = None) -> None:
        self.store = store
        self.source = source
        self.target = target
        self.language = language
        # The `Tags` object, so a miss is counted in the same report as
        # everything else a skin asked for and did not get.
        self.tags = tags

    # -- the numbers -----------------------------------------------------

    @property
    def hours(self) -> list[Entry]:
        """From this hour forward. The past is not a forecast."""
        start = int(time.time()) - 3600
        return [Entry(m, self.target, self.language, "hour")
                for m in self._hours(start)]

    @property
    def days(self) -> list[Entry]:
        """From today forward, today first."""
        start = _midnight(time.time())
        try:
            found = self.store.days(self.source, start=start)
        except Exception:
            log.debug("could not read the forecast days", exc_info=True)
            return []
        # Each day knows which source it came from, so it can be asked for
        # its own hours. See `Entry.hours`.
        return [Entry(d, self.target, self.language, "day", owner=self)
                for d in found]

    def every(self, step: int = 1) -> list[Entry]:
        """From this hour forward, one entry per `step` hours."""
        return self._blocks(self._hours(int(time.time()) - 3600), step)

    def between(self, start: int, stop: int, step: int = 1) -> list[Entry]:
        """The hours in a span, one entry per `step` of them."""
        try:
            found = self.store.hours(self.source, start=int(start),
                                     stop=int(stop))
        except Exception:
            log.debug("could not read the forecast hours", exc_info=True)
            return []
        return self._blocks(found, step)

    def _blocks(self, moments: list, step: int) -> list[Entry]:
        """Group hours into spans of `step`, one entry each."""
        step = max(1, int(step))
        made = []
        for at in range(0, len(moments), step):
            block = moments[at:at + step]
            made.append(Entry(block[0] if step == 1 else _summarise(block),
                              self.target, self.language, "hour"))
        return made

    @property
    def now(self) -> Entry | Unknown:
        """The hour we are in.

        The hour whose stamp is at or just before now -- not the nearest,
        which would show the next hour's rain from twenty-nine minutes past.
        """
        now = int(time.time())
        found = self._hours(now - 3600)
        current = [m for m in found if m.dateTime <= now]
        if current:
            return Entry(current[-1], self.target, self.language, "hour")
        if found:
            # Nothing in the past hour: the forecast starts later than now,
            # which happens right after a fetch on a slow source. The first
            # hour it does have is closer to the truth than nothing.
            return Entry(found[0], self.target, self.language, "hour")
        return self._missed("forecast.now")

    @property
    def today(self) -> Entry | Unknown:
        days = self.days
        return days[0] if days else self._missed("forecast.today")

    @property
    def tomorrow(self) -> Entry | Unknown:
        days = self.days
        return days[1] if len(days) > 1 else self._missed("forecast.tomorrow")

    def _hours(self, start: int) -> list:
        try:
            return self.store.hours(self.source, start=start)
        except Exception:
            log.debug("could not read the forecast hours", exc_info=True)
            return []

    # -- the warnings ----------------------------------------------------

    @property
    def warnings(self) -> list[WarningTag]:
        """Every warning stored, worst first."""
        try:
            found = self.store.warnings(self.source)
        except Exception:
            log.debug("could not read the warnings", exc_info=True)
            return []
        return [WarningTag(w, self.target) for w in found]

    @property
    def warning(self) -> WarningTag | Unknown:
        """The worst one, for a page with room for a single banner."""
        found = self.warnings
        return found[0] if found else self._missed("forecast.warning")

    @property
    def active_warnings(self) -> list[WarningTag]:
        """Only what covers this moment."""
        try:
            found = self.store.warnings(self.source, active_at=int(time.time()))
        except Exception:
            return []
        return [WarningTag(w, self.target) for w in found]

    # -- about the forecast itself ---------------------------------------

    @property
    def updated(self) -> Value | Unknown:
        """When the source last answered.

        Which is not when the model ran -- see `issued`. A page that says
        "updated a minute ago" about a six-hour-old model run is lying
        politely, and both numbers are here so it does not have to.
        """
        run = self._run()
        if not run:
            return self._missed("forecast.updated")
        return Value(run.get("fetched"), "unix_epoch", "group_time",
                     "current", self.target)

    @property
    def issued(self) -> Value | Unknown:
        """When the model behind this forecast actually ran."""
        run = self._run()
        if not run:
            return self._missed("forecast.issued")
        return Value(run.get("issued"), "unix_epoch", "group_time",
                     "current", self.target)

    @property
    def exists(self) -> bool:
        return bool(self._run())

    @property
    def sources(self) -> list[str]:
        try:
            return self.store.sources()
        except Exception:
            return []

    def _run(self) -> dict | None:
        try:
            if self.source:
                return self.store.run(self.source)
            # No source named: the most recently fetched one speaks for all
            # of them, which is what a page asking `$forecast.updated` with
            # one source configured means.
            found = [self.store.run(name) for name in self.store.sources()]
            found = [r for r in found if r]
            return max(found, key=lambda r: r.get("fetched") or 0) if found else None
        except Exception:
            return None

    def _missed(self, what: str) -> Unknown:
        if self.tags is not None:
            return self.tags.missed(what)
        return Unknown(what)

    def __getattr__(self, name: str) -> Any:
        """A named source: `$forecast.ahead`.

        Anything not defined above is taken as the name of a configured
        source. That is what makes two of them usable from one template --
        and an unknown name comes back as `Unknown` rather than raising,
        because `#if $forecast.warnings` on a station with none must not
        break the page.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self.sources:
            return SourceTag(self.store, name, self.target, self.language,
                             self.tags)
        return self._missed(f"forecast.{name}")

    def __bool__(self) -> bool:
        """Whether there is a forecast at all.

        `#if $forecast` is how a template asks, and on a station that has
        fetched nothing the answer has to be no rather than a page of empty
        boxes.
        """
        return bool(self.hours or self.days or self.warnings)

    def __str__(self) -> str:
        now = self.now
        return str(now) if not isinstance(now, Unknown) else ""


def install(tags: Any, store: Any, language: Any = None) -> None:
    """Give a `Tags` object its `$forecast`.

    Called by whatever built the tags and knows where the forecast database
    is. Nothing in `tags.py` imports this: a station with no forecast
    configured should not open a database it has no rows in, and the tag
    layer has no business knowing this package exists.
    """
    tags.forecast = SourceTag(store, "", tags.target, language, tags)


def _midnight(when: float) -> int:
    import datetime

    return int(datetime.datetime.fromtimestamp(when).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())

"""What a template asks for: `$day.outTemp.max`.

The layer between a skin and the database. A template written for WeeWX says

    $current.outTemp
    $day.outTemp.max at $day.outTemp.maxtime
    $month.rain.sum.formatted
    $year.wind.vecdir.ordinal_compass

and every one of those is a chain of small objects, each holding a little more
of the question, until something finally asks the database. This is that
chain, and it is the whole reason a skin somebody has been using for eight
years can keep working here.

## Why it is a layer and not part of a renderer

Cheetah is one renderer. A page builder would be another, and so would Jinja.
None of them should know how a daily maximum is found. So the chain below
returns plain objects with `__str__`, and a renderer only has to call the
right one.

## The chain

    Tags               $day, $current, $station, $unit ...
      TimespanBinder   a span. $day, $week, $month, $span(hour_delta=6)
        Reading        a span and a reading. $day.outTemp
          Aggregate    a span, a reading and a question. $day.outTemp.max
            Value      the answer, and how to print it

Attribute lookup does the binding, exactly as WeeWX does it, because that is
what makes `$day.<anything>.<anything>` work without a list of names anywhere.
An unknown reading or an impossible aggregate raises `AttributeError`, which
is how Cheetah is told to leave the text alone rather than printing a wrong
number.

## Deliberately not silent

WeeWX answers an unknown tag with an empty string. Here every miss is
recorded on the `Tags` object, so a feed can say afterwards which tags a skin
asked for and did not get. A page that renders at 95% looks like our bug and
cannot be reproduced; a list of what was missing can be acted on.
"""

from __future__ import annotations

import datetime
import logging
import math
import time
from typing import Any, Iterator

from . import sun as sun_module
from . import units
from .series import Reader

log = logging.getLogger(__name__)

#: The builtin, kept because `Value.round` shadows the name inside the class.
_round = round

#: Attributes Cheetah's NameMapper probes for on every lookup. Answering them
#: with a database query would be a query per attribute per tag.
IGNORE = {
    "__call__", "has_key", "__getstate__", "__setstate__", "__deepcopy__",
    "__len__", "__iter__", "__next__", "__reduce__", "__reduce_ex__",
    "__getitem__", "keys", "items", "values", "_no_aggregate",
}

#: How a time is printed, per span. WeeWX keeps these in a skin so they can be
#: translated; these are the defaults it ships.
TIME_FORMATS = {
    "hour": "%H:%M", "day": "%X", "week": "%X (%A)", "month": "%x %X",
    "year": "%x %X", "rainyear": "%x %X", "current": "%x %X",
    "ephem_day": "%X", "ephem_year": "%x %X",
}
DEFAULT_TIME_FORMAT = "%d-%b-%Y %H:%M"

#: The sixteen points, plus what to say when there is no direction at all.
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW", "N/A")


class Missing(AttributeError):
    """A tag nothing here can answer.

    An AttributeError, because that is what tells Cheetah to leave the text
    alone. Its own type so that a renderer can tell "this skin asked for
    something we do not have" from "this code has a bug".
    """


# -- the answer ------------------------------------------------------------

class Value:
    """One number, and everything needed to print it.

    WeeWX calls this a ValueHelper. `str()` of it is the formatted, labelled,
    localised text, which is what a template gets when it prints the tag
    without asking for anything more.
    """

    __slots__ = ("value", "unit", "group", "context", "target")

    def __init__(self, value: Any, unit: str | None, group: str | None,
                 context: str = "current",
                 target: units.Target | None = None) -> None:
        self.value = value
        self.unit = unit
        self.group = group
        #: Which span this came from. Decides how a time is printed: the
        #: minimum of a day wants a clock, the minimum of a year wants a date.
        self.context = context
        self.target = target

    # -- printing ---------------------------------------------------------

    def __str__(self) -> str:
        return self.format()

    def __repr__(self) -> str:  # pragma: no cover - for a traceback
        return f"<Value {self.value!r} {self.unit}>"

    def format(self, format_string: str | None = None,
               none_string: str | None = None,
               add_label: bool = True) -> str:
        """The value as text.

        `format_string` is a printf format for a number and a strftime format
        for a time, which is WeeWX's arrangement and worth keeping: a template
        says `$day.outTemp.maxtime.format("%H:%M")` and means the clock.
        """
        if self.value is None:
            return none_string if none_string is not None else "   N/A"

        if self.unit in ("unix_epoch", "unix_epoch_ms", "unix_epoch_ns"):
            when = float(self.value)
            if self.unit == "unix_epoch_ms":
                when /= 1000.0
            elif self.unit == "unix_epoch_ns":
                when /= 1000000.0
            shape = format_string or TIME_FORMATS.get(self.context,
                                                      DEFAULT_TIME_FORMAT)
            return time.strftime(shape, time.localtime(when))

        shape = format_string or units.FORMATS.get(self.unit or "", "%s")
        try:
            text = shape % self.value
        except (TypeError, ValueError):
            text = str(self.value)
        if add_label:
            text += units.label(self.unit, plural=self.value != 1)
        return text

    # WeeWX's spelling, so a template written for it works unchanged.
    def toString(self, addLabel: bool = True,  # noqa: N802, N803
                 useThisFormat: str | None = None,  # noqa: N803
                 None_string: str | None = None,  # noqa: N803
                 localize: bool = True) -> str:
        return self.format(useThisFormat, None_string, addLabel)

    @property
    def formatted(self) -> str:
        """The value with no label. `$day.outTemp.max.formatted`."""
        return self.format(add_label=False)

    def nolabel(self, format_string: str,
                none_string: str | None = None) -> str:
        return self.format(format_string, none_string, add_label=False)

    def string(self, none_string: str | None = None) -> str:
        return self.format(none_string=none_string)

    @property
    def raw(self) -> Any:
        """The number itself, unformatted. What a JSON document wants."""
        return self.value

    def round(self, ndigits: int | None = None) -> Value:
        value = (_round(self.value, ndigits) if isinstance(self.value, float)
                 else self.value)
        return Value(value, self.unit, self.group, self.context, self.target)

    @property
    def ordinal_compass(self) -> str:
        """A bearing as a point of the compass. `$day.wind.vecdir`."""
        if self.value is None:
            return COMPASS[-1]
        sector = 360.0 / (len(COMPASS) - 1)
        degrees = (float(self.value) + sector / 2.0) % 360.0
        return COMPASS[int(degrees / sector)]

    def json(self, **_kwargs: Any) -> str:
        import json as _json

        return _json.dumps(self.value)

    # -- converting -------------------------------------------------------

    def convert(self, target_unit: str) -> Value:
        """The same reading in another unit. `$day.outTemp.max.degree_C`."""
        try:
            converted = units.convert(self.value, self.unit, target_unit)
        except ValueError as exc:
            raise Missing(str(exc)) from None
        return Value(converted, target_unit, self.group, self.context,
                     self.target)

    def __getattr__(self, name: str) -> Any:
        """`$day.outTemp.max.degree_C` -- a unit name is a conversion.

        Only reached for attributes this class does not have, which is why
        every real one above is a slot or a property.
        """
        if name.startswith("_") or name in IGNORE:
            raise AttributeError(name)
        if name in units.CONVERT or name == self.unit:
            return self.convert(name)
        raise Missing(f"{name} is not a unit this can be shown in")

    # -- what a template asks about the value itself ----------------------

    @property
    def exists(self) -> bool:
        return True

    @property
    def has_data(self) -> bool:
        return self.value is not None

    def __bool__(self) -> bool:
        return self.value is not None

    def __float__(self) -> float:
        return float(self.value) if self.value is not None else float("nan")


class Unknown:
    """A reading nothing knows about.

    Printed as WeeWX prints it, so a template that mentions a sensor this
    station has never had says so rather than failing. Every one of these is
    counted, and the feed reports them.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return f"?'{self.name}'?"

    def __getattr__(self, _name: str) -> Unknown:
        return self

    def __call__(self, *_args: Any, **_kwargs: Any) -> Unknown:
        return self

    def __bool__(self) -> bool:
        return False

    @property
    def exists(self) -> bool:
        return False

    @property
    def has_data(self) -> bool:
        return False


# -- the chain -------------------------------------------------------------

class Aggregate:
    """A span, a reading, and a question. `$day.outTemp.max`.

    Nothing has been asked of the database yet: a template may still say
    `.max_ge((30, 'degree_C'))`, and Cheetah probes several attributes before
    it prints anything. The query happens when somebody wants the answer.
    """

    __slots__ = ("tags", "reading", "how", "span", "context", "options")

    def __init__(self, tags: "Tags", reading: str, how: str,
                 span: tuple[float, float], context: str) -> None:
        self.tags = tags
        self.reading = reading
        self.how = how
        self.span = span
        self.context = context
        self.options: dict[str, Any] = {}

    def __call__(self, *args: Any, **kwargs: Any) -> Aggregate:
        """`$month.outTemp.max_ge((30.0, 'degree_C'))`."""
        if args:
            self.options["val"] = args[0]
        self.options.update(kwargs)
        return self

    def answer(self) -> Value:
        """Ask, and wrap the answer so a template can print it."""
        return self.tags.answer(self.reading, self.how, self.span,
                                self.context, self.options)

    def __str__(self) -> str:
        return str(self.answer())

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in IGNORE:
            raise AttributeError(name)
        return getattr(self.answer(), name)


class Reading:
    """A span and a reading. `$day.outTemp`.

    Prints as the reading over that span, which for a template is almost
    always the average -- but only `$current.outTemp` prints without an
    aggregate in practice, and that one comes from `Current` instead.
    """

    __slots__ = ("tags", "reading", "span", "context")

    def __init__(self, tags: "Tags", reading: str,
                 span: tuple[float, float], context: str) -> None:
        self.tags = tags
        self.reading = reading
        self.span = span
        self.context = context

    def __getattr__(self, how: str) -> Any:
        if how.startswith("_") or how in IGNORE:
            raise AttributeError(how)
        if how == "exists":
            return self.tags.exists(self.reading)
        if how == "has_data":
            return self.tags.has_data(self.reading, self.span)
        return Aggregate(self.tags, self.reading, how, self.span, self.context)

    def series(self, aggregate_type: str | None = None,
               aggregate_interval: Any = None, **_options: Any) -> Any:
        """The same series every feed uses, for a template that draws itself."""
        return self.tags.reader.series(self.reading, self.span[0], self.span[1],
                                       aggregate=aggregate_type,
                                       interval=aggregate_interval)

    def __str__(self) -> str:
        return str(Aggregate(self.tags, self.reading, "avg", self.span,
                             self.context).answer())


class Span:
    """A stretch of time. `$day`, `$week`, `$month`, `$span(hour_delta=6)`.

    Any attribute is a reading, which is what lets a skin name a sensor this
    code has never heard of.
    """

    __slots__ = ("tags", "span", "context")

    def __init__(self, tags: "Tags", span: tuple[float, float],
                 context: str) -> None:
        self.tags = tags
        self.span = span
        self.context = context

    def __getattr__(self, reading: str) -> Any:
        if reading.startswith("_") or reading in IGNORE:
            raise AttributeError(reading)
        return Reading(self.tags, reading, self.span, self.context)

    # What a template asks about the span itself.
    @property
    def start(self) -> Value:
        return Value(self.span[0], "unix_epoch", "group_time", self.context)

    dateTime = start  # noqa: N815 -- WeeWX's spelling

    @property
    def end(self) -> Value:
        return Value(self.span[1], "unix_epoch", "group_time", self.context)

    stop = end

    @property
    def length(self) -> Value:
        return Value(self.span[1] - self.span[0], "second", "group_deltatime",
                     self.context)

    # Walking a span in smaller pieces: `for m in $year.months`.
    @property
    def hours(self) -> Iterator[Span]:
        return self._walk("hour", 3600)

    @property
    def days(self) -> Iterator[Span]:
        return self._walk("day", "day")

    @property
    def months(self) -> Iterator[Span]:
        return self._walk("month", "month")

    @property
    def years(self) -> Iterator[Span]:
        return self._walk("year", "year")

    def spans(self, context: str = "day",
              interval: Any = 10800) -> Iterator[Span]:
        return self._walk(context, interval)

    def _walk(self, context: str, interval: Any) -> Iterator[Span]:
        for begin, end in self.tags.reader.buckets(self.span[0], self.span[1],
                                                   interval):
            yield Span(self.tags, (begin, end), context)

    def __call__(self, data_binding: str | None = None) -> Span:
        return self

    def __str__(self) -> str:
        return f"{self.context}: {self.start} to {self.end}"


class Current:
    """The latest reading of everything. `$current.outTemp`.

    One record, not a span. A template printing `$current.barometer` is asking
    what the station says right now, and the answer is a row rather than an
    aggregate over anything.
    """

    __slots__ = ("tags", "record", "when")

    def __init__(self, tags: "Tags", record: dict[str, Any],
                 when: float) -> None:
        self.tags = tags
        self.record = record
        self.when = when

    def __getattr__(self, reading: str) -> Any:
        if reading.startswith("_") or reading in IGNORE:
            raise AttributeError(reading)
        if reading == "dateTime":
            return Value(self.when, "unix_epoch", "group_time", "current")
        if reading not in self.record:
            if reading not in self.tags.reader.columns:
                return self.tags.missed(reading)
            return Value(None, *self.tags.units_of(reading), "current")
        stored = self.record.get(reading)
        unit, group = self.tags.units_of(reading)
        shown = self.tags.target.unit(group)
        try:
            value = units.convert(stored, unit, shown)
        except ValueError:
            value, shown = stored, unit
        return Value(value, shown, group, "current", self.tags.target)


# -- what a template names besides the readings ----------------------------

class Station:
    """`$station.location`, `$station.latitude_f`.

    Where the station is and what it is called. Every one of these comes out
    of the settings, so a skin that prints a heading gets the operator's own
    words rather than a placeholder.
    """

    __slots__ = ("tags", "values")

    def __init__(self, tags: "Tags", values: dict[str, Any]) -> None:
        self.tags = tags
        self.values = values

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in IGNORE:
            raise AttributeError(name)
        if name in self.values:
            return self.values[name]
        # WeeWX spells the numbers with a suffix and the text without.
        if name.endswith("_f") and name[:-2] in self.values:
            try:
                return float(self.values[name[:-2]])
            except (TypeError, ValueError):
                return None
        return self.tags.missed(f"station.{name}")

    def __str__(self) -> str:
        return str(self.values.get("location", ""))


class Labels:
    """`$obs.label.outTemp` -- what a reading is called, in words.

    A skin prints these as table headings. They belong to the station's
    language, not to this code, so whatever the operator configured wins and
    the reading's own name is the fallback.
    """

    __slots__ = ("tags", "labels")

    def __init__(self, tags: "Tags", labels: dict[str, str]) -> None:
        self.tags = tags
        self.labels = labels

    @property
    def label(self) -> "Labels":
        return self

    def __getattr__(self, reading: str) -> str:
        if reading.startswith("_") or reading in IGNORE:
            raise AttributeError(reading)
        return self.labels.get(reading, reading)

    def __getitem__(self, reading: str) -> str:
        return self.labels.get(reading, reading)


class UnitInfo:
    """`$unit.label.outTemp`, `$unit.unit_type.rain`.

    What a reading is shown in, asked about rather than printed. A skin uses
    it for an axis label or a column heading, where the number itself is
    somewhere else.
    """

    __slots__ = ("tags",)

    def __init__(self, tags: "Tags") -> None:
        self.tags = tags

    @property
    def label(self) -> "_UnitField":
        return _UnitField(self.tags, "label")

    @property
    def unit_type(self) -> "_UnitField":
        return _UnitField(self.tags, "unit")

    @property
    def format(self) -> "_UnitField":
        return _UnitField(self.tags, "format")

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in IGNORE:
            raise AttributeError(name)
        return self.tags.missed(f"unit.{name}")


class _UnitField:
    """One of the three things `$unit` can say about a reading."""

    __slots__ = ("tags", "which")

    def __init__(self, tags: "Tags", which: str) -> None:
        self.tags = tags
        self.which = which

    def __getattr__(self, reading: str) -> str:
        if reading.startswith("_") or reading in IGNORE:
            raise AttributeError(reading)
        return self[reading]

    def __getitem__(self, reading: str) -> str:
        stored, group = self.tags.units_of(reading)
        shown = self.tags.target.unit(group) or stored
        if self.which == "unit":
            return shown or ""
        if self.which == "format":
            return units.FORMATS.get(shown or "", "%s")
        return units.label(shown)


# -- the sky ---------------------------------------------------------------

class Almanac:
    """`$almanac.sunrise`, `$almanac.moon_phase`, `$almanac.moon.rise`.

    What is in the sky, for the day the page is being made for. A weather
    page shows this beside the readings because they belong together: the
    temperature falling at four in the afternoon means one thing in December
    and another in June.

    What can be worked out without pyephem is: sunrise, sunset, the twilights,
    the sun's height, and the moon's phase. What needs it is the moon's
    rising and setting, and the equinoxes. Those come back as "N/A" rather
    than as a wrong time, and `$almanac.hasExtras` says which world you are
    in -- which is the same question WeeWX answers with the same tag.
    """

    __slots__ = ("tags", "latitude", "longitude", "altitude", "horizon")

    def __init__(self, tags: "Tags", latitude: float | None,
                 longitude: float | None, altitude: float = 0.0,
                 horizon: float | None = None) -> None:
        self.tags = tags
        self.latitude = latitude
        self.longitude = longitude
        self.altitude = altitude
        self.horizon = horizon

    def __call__(self, almanac_time: float | None = None,
                 horizon: float | None = None, **_kwargs: Any) -> "Almanac":
        """`$almanac(horizon=-6)` -- the same sky, a different threshold."""
        return Almanac(self.tags, self.latitude, self.longitude,
                       self.altitude,
                       self.horizon if horizon is None else horizon)

    @property
    def hasExtras(self) -> bool:  # noqa: N802 -- WeeWX's spelling
        """Whether the harder questions can be answered at all."""
        return sun_module._ephem is not None

    @property
    def _placed(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def _time(self, when: float | None, context: str = "ephem_day") -> Value:
        return Value(when, "unix_epoch", "group_time", context,
                     self.tags.target)

    # -- the sun ----------------------------------------------------------

    @property
    def sunrise(self) -> Value:
        return self.sun.rise

    @property
    def sunset(self) -> Value:
        return self.sun.set

    @property
    def sun(self) -> "Body":
        return Body(self, "sun")

    @property
    def moon(self) -> "Body":
        return Body(self, "moon")

    # -- the moon ---------------------------------------------------------

    @property
    def moon_phase(self) -> str:
        names = self.tags.moon_phases or sun_module.MOON_PHASES
        index = sun_module.moon_phase(self.tags.when)[0]
        return names[index] if index < len(names) else ""

    @property
    def moon_index(self) -> int:
        return sun_module.moon_phase(self.tags.when)[0]

    @property
    def moon_fullness(self) -> int:
        return sun_module.moon_fullness(self.tags.when)

    @property
    def moon_age(self) -> float:
        return sun_module.moon_age(self.tags.when)

    # -- the rest ---------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """The events pyephem knows about, and an honest miss otherwise."""
        if name.startswith("_") or name in IGNORE:
            raise AttributeError(name)

        events = {
            "next_full_moon": "next_full_moon",
            "next_new_moon": "next_new_moon",
            "next_first_quarter_moon": "next_first_quarter_moon",
            "next_last_quarter_moon": "next_last_quarter_moon",
            "previous_full_moon": "previous_full_moon",
            "previous_new_moon": "previous_new_moon",
            "next_equinox": "next_equinox",
            "next_solstice": "next_solstice",
            "previous_equinox": "previous_equinox",
            "previous_solstice": "previous_solstice",
            "next_vernal_equinox": "next_vernal_equinox",
            "next_autumnal_equinox": "next_autumnal_equinox",
            "next_summer_solstice": "next_summer_solstice",
            "next_winter_solstice": "next_winter_solstice",
        }
        if name in events:
            return self._time(_ephem_event(events[name], self.tags.when),
                              "ephem_year")
        return self.tags.missed(f"almanac.{name}")


class Body:
    """One thing in the sky. `$almanac.sun.rise`, `$almanac.moon.transit`."""

    __slots__ = ("almanac", "which")

    def __init__(self, almanac: Almanac, which: str) -> None:
        self.almanac = almanac
        self.which = which

    def _events(self) -> dict[str, float | None]:
        """When this body rises and sets, on the day the page is for.

        Anchored at local midnight and asking for the *next* one, which is
        how WeeWX does it. The alternative -- "the rising nearest noon" --
        has no answer on the days the moon rises twice.
        """
        tags = self.almanac.tags
        if not self.almanac._placed:
            return {}
        found = sun_module.rising_setting(
            _midnight(tags.when), self.almanac.latitude,
            self.almanac.longitude, body=self.which,
            horizon=self.almanac.horizon,
            altitude_m=self.almanac.altitude or 0.0)
        if self.which == "sun" and self.almanac.horizon is None:
            twilight = sun_module.events(tags.when, self.almanac.latitude,
                                         self.almanac.longitude)
            found["dawn"], found["dusk"] = twilight["dawn"], twilight["dusk"]
        return found

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in IGNORE:
            raise AttributeError(name)

        if name in ("rise", "set", "transit", "dawn", "dusk"):
            return self.almanac._time(self._events().get(name))

        if name == "visible":
            found = self._events()
            rise, sets = found.get("rise"), found.get("set")
            length = None if rise is None or sets is None else sets - rise
            return Value(length, "second", "group_deltatime", "day",
                         self.almanac.tags.target)

        if name in ("alt", "az", "dec", "ra"):
            return Value(_position(self, name), "degree_compass",
                         "group_direction", "current", self.almanac.tags.target)

        return self.almanac.tags.missed(f"almanac.{self.which}.{name}")


def _position(body: Body, what: str) -> float | None:
    """Where something is in the sky right now, in degrees.

    Only the sun's height is worked out without pyephem; the rest of it is
    orbital mechanics that has no business being approximated here.
    """
    tags = body.almanac.tags
    if not body.almanac._placed:
        return None

    if sun_module._ephem is not None:
        try:
            observer = sun_module._ephem.Observer()
            observer.lat = str(body.almanac.latitude)
            observer.lon = str(body.almanac.longitude)
            observer.date = sun_module._ephem.Date(
                sun_module._ephem.Date("1970/1/1 00:00:00")
                + tags.when / 86400.0)
            thing = (sun_module._ephem.Sun(observer) if body.which == "sun"
                     else sun_module._ephem.Moon(observer))
            return math.degrees(float(getattr(thing, what)))
        except Exception:
            log.debug("pyephem could not place the %s", body.which,
                      exc_info=True)

    if body.which == "sun" and what == "alt":
        return sun_module.position(tags.when, body.almanac.latitude,
                                   body.almanac.longitude)[0]
    if body.which == "sun" and what == "dec":
        return sun_module.solar(tags.when)[0]
    return None


def _ephem_event(name: str, when: float) -> float | None:
    """One of pyephem's moments, as a timestamp. None without pyephem."""
    if sun_module._ephem is None:
        return None
    try:
        date = sun_module._ephem.Date(
            sun_module._ephem.Date("1970/1/1 00:00:00") + when / 86400.0)
        found = getattr(sun_module._ephem, name)(date)
        return ((float(found)
                 - float(sun_module._ephem.Date("1970/1/1 00:00:00")))
                * 86400.0)
    except Exception:
        log.debug("pyephem could not work out %s", name, exc_info=True)
        return None


# -- the root --------------------------------------------------------------

class Tags:
    """Everything a template can name, and a record of what it could not.

    One of these per render. It holds the database, what the readings should
    be shown in, and the moment the page is being made for -- and it counts
    every tag a skin asked for that nothing here could answer.
    """

    def __init__(self, reader: Reader, when: float | None = None,
                 target: units.Target | None = None,
                 unit_system: int = units.US,
                 station: dict[str, Any] | None = None,
                 extra_groups: dict[str, str] | None = None,
                 rain_year_start: int = 1,
                 week_start: int = 6) -> None:
        self.reader = reader
        found = reader.span()
        #: The moment the page is for. The last record rather than the clock,
        #: so two pages of one run agree with each other and with the data.
        self.when = float(when if when is not None
                          else (found[1] if found else time.time()))
        self.target = target or units.Target(unit_system)
        #: What the archive holds. Not what to show.
        self.unit_system = unit_system
        self.extra_groups = dict(extra_groups or {})
        #: The station's own settings, for `$station.location`. Named with a
        #: suffix because `station` itself is the tag.
        self.station_info = dict(station or {})
        #: What each reading is called, for `$obs.label.outTemp`. The skin's,
        #: in the skin's language.
        self.labels: dict[str, str] = {}
        #: Translated strings, for `$gettext`.
        self.text: dict[str, str] = {}
        #: What the eight phases are called. A skin names its own, and the
        #: names go straight into a page, so this is the skin's to decide.
        self.moon_phases: tuple[str, ...] = ()
        self.rain_year_start = rain_year_start
        #: Which day a week starts on, as `time.localtime().tm_wday`: 6 is
        #: Sunday, which is WeeWX's default and not everybody's.
        self.week_start = week_start
        #: Tags a skin asked for and nothing could answer. Kept because a
        #: page rendering at 95% otherwise looks like our bug and cannot be
        #: reproduced.
        self.missing: dict[str, int] = {}
        self.asked = 0
        self._current: Current | None = None

    # -- the record of what did not work ---------------------------------

    def missed(self, what: str) -> Unknown:
        self.missing[what] = self.missing.get(what, 0) + 1
        return Unknown(what)

    def report(self) -> str:
        """What a skin asked for and did not get, for the log and the page."""
        if not self.missing:
            return f"{self.asked} tag(s), all answered"
        worst = sorted(self.missing.items(), key=lambda kv: -kv[1])
        named = ", ".join(f"{name} ({count})" for name, count in worst[:8])
        more = "" if len(worst) <= 8 else f", and {len(worst) - 8} more"
        return (f"{self.asked} tag(s), {len(self.missing)} not answered: "
                f"{named}{more}")

    # -- what the chain calls back into ----------------------------------

    def units_of(self, reading: str,
                 how: str | None = None) -> tuple[str | None, str | None]:
        return units.unit_of(reading, self.unit_system, how, self.extra_groups)

    def exists(self, reading: str) -> bool:
        from .series import VECTORS

        # `wind` and `windvec` are not columns. They are the pair of columns,
        # and which one is meant depends on the question -- the highest wind
        # of a day is the highest gust. series.py knows; this only has to
        # agree that they are real.
        return (reading in self.reader.columns or reading in VECTORS
                or (reading == "wind" and "windSpeed" in self.reader.columns))

    def has_data(self, reading: str, span: tuple[float, float]) -> bool:
        try:
            return bool(self.reader.aggregate(reading, span[0], span[1],
                                              "not_null"))
        except Exception:  # noqa: BLE001
            return False

    def answer(self, reading: str, how: str, span: tuple[float, float],
               context: str, options: dict[str, Any]) -> Value:
        """The one place a tag becomes a database query."""
        self.asked += 1
        if not self.exists(reading):
            # AttributeError, as WeeWX does it, because that is the contract
            # a template is written against: `#if $day.foo.has_data` guards
            # the tag, and a bare `$day.foo.max` is left for the renderer to
            # deal with rather than printed as "N/A". Counted either way.
            self.missed(reading)
            raise Missing(reading)

        try:
            raw = self.reader.aggregate(reading, span[0], span[1], how)
        except ValueError:
            # Not an aggregate this knows. Raised as AttributeError, which is
            # what tells a renderer to leave the text alone rather than print
            # a wrong number.
            self.missed(f"{reading}.{how}")
            raise Missing(f"{how} is not an aggregate") from None
        except Exception:
            log.exception("could not work out %s.%s", reading, how)
            self.missed(f"{reading}.{how}")
            return Value(None, None, None, context, self.target)

        stored, group = self.units_of(reading, how)
        shown = self.target.unit(group) or stored
        try:
            value = units.convert(raw, stored, shown)
        except ValueError:
            value, shown = raw, stored
        return Value(value, shown, group, context, self.target)

    # -- the spans a template names --------------------------------------

    def _span(self, start: float, stop: float, context: str) -> Span:
        return Span(self, (start, stop), context)

    @property
    def almanac(self) -> Almanac:
        return Almanac(self, _number(self.station_info.get("latitude")),
                       _number(self.station_info.get("longitude")),
                       _number(self.station_info.get("altitude")) or 0.0)

    @property
    def station(self) -> Station:
        return Station(self, self.station_info)

    @property
    def obs(self) -> Labels:
        return Labels(self, self.labels)

    @property
    def unit(self) -> UnitInfo:
        return UnitInfo(self)

    def gettext(self, text: str) -> str:
        """`$gettext("Outside Temperature")`.

        Whatever the skin's own language files say, and the text itself when
        they say nothing. A skin translated into six languages must not come
        out in English here.
        """
        return self.text.get(text, text)

    def pgettext(self, context: str, text: str) -> str:
        return self.text.get(f"{context}\x04{text}", self.text.get(text, text))

    @property
    def current(self) -> Current:
        if self._current is None:
            self._current = Current(self, self._latest_record(), self.when)
        return self._current

    @property
    def latest(self) -> Current:
        return self.current

    def _latest_record(self) -> dict[str, Any]:
        try:
            cursor = self.reader.conn.execute(
                f"SELECT * FROM {self.reader.table}"
                " WHERE dateTime <= ? ORDER BY dateTime DESC LIMIT 1",
                (self.when,))
            row = cursor.fetchone()
            if row is None:
                return {}
            return dict(zip([c[0] for c in cursor.description], row))
        except Exception:  # noqa: BLE001
            log.exception("could not read the latest record")
            return {}

    @property
    def hour(self) -> Span:
        return self.hours_ago(0)

    def hours_ago(self, hours_ago: int = 0) -> Span:
        start = _floor_hour(self.when) - hours_ago * 3600
        return self._span(start, start + 3600, "hour")

    @property
    def day(self) -> Span:
        return self.days_ago(0)

    def days_ago(self, days_ago: int = 0) -> Span:
        start = _add_days(self.when, -days_ago)
        return self._span(start, _add_days(start, 1), "day")

    @property
    def yesterday(self) -> Span:
        return self.days_ago(1)

    @property
    def week(self) -> Span:
        return self.weeks_ago(0)

    def weeks_ago(self, weeks_ago: int = 0) -> Span:
        start = _add_days(_week_start(self.when, self.week_start),
                          -7 * weeks_ago)
        return self._span(start, _add_days(start, 7), "week")

    @property
    def month(self) -> Span:
        return self.months_ago(0)

    def months_ago(self, months_ago: int = 0) -> Span:
        start = _month_start(self.when, -months_ago)
        return self._span(start, _month_start(start, 1), "month")

    @property
    def year(self) -> Span:
        return self.years_ago(0)

    def years_ago(self, years_ago: int = 0) -> Span:
        start = _year_start(self.when, -years_ago)
        return self._span(start, _year_start(start, 1), "year")

    @property
    def rainyear(self) -> Span:
        """The year as a rain gauge counts it, which need not start in January."""
        start = _rain_year_start(self.when, self.rain_year_start)
        return self._span(start, _month_start(start, 12), "rainyear")

    @property
    def alltime(self) -> Span:
        """Everything there is, rounded out to whole days.

        Not the first and last record: that span falls between day
        boundaries, so it is answered from the archive rather than from the
        daily summaries, and comes back with duller extremes than `$year`
        over the same readings. An all-time high lower than this year's is
        the kind of wrong nobody reports as a bug because it looks like one
        of ours anyway.
        """
        found = self.reader.span()
        if found is None:
            return self._span(self.when, self.when, "year")
        return self._span(_midnight(found[0]), _add_days(found[1], 1), "year")

    def span(self, data_binding: str | None = None, time_delta: float = 0,
             hour_delta: float = 0, day_delta: float = 0,
             week_delta: float = 0, month_delta: float = 0,
             year_delta: float = 0, boundary: str | None = None) -> Span:
        """`$span($hour_delta=6)` -- a stretch ending now."""
        seconds = (time_delta + hour_delta * 3600 + day_delta * 86400
                   + week_delta * 604800)
        start = self.when - seconds
        if month_delta:
            start = _month_start(start, -int(month_delta))
        if year_delta:
            start = _year_start(start, -int(year_delta))
        if boundary == "midnight":
            start = _midnight(start)
        return self._span(start, self.when, "current")

    @property
    def trend(self) -> "Trend":
        """`$trend.barometer`, and `$trend($time_delta=7200).barometer`.

        Both spellings, because templates use both. A property that returns
        something callable is the only way to have it.
        """
        return Trend(self, 10800, 300)

    # -- everything else a template names --------------------------------

    def __getattr__(self, name: str) -> Any:
        """Anything not defined above. Counted, and reported afterwards."""
        if name.startswith("_") or name in IGNORE:
            raise AttributeError(name)
        return self.missed(name)


class Trend:
    """How much a reading has moved. `$trend.barometer`.

    The difference between now and a few hours ago, which is what a station
    means by rising or falling.
    """

    __slots__ = ("tags", "delta", "grace")

    def __init__(self, tags: Tags, delta: float, grace: float) -> None:
        self.tags = tags
        self.delta = delta
        self.grace = grace

    def __call__(self, time_delta: float | None = None,
                 time_grace: float | None = None,
                 data_binding: str | None = None) -> "Trend":
        return Trend(self.tags,
                     self.delta if time_delta is None else time_delta,
                     self.grace if time_grace is None else time_grace)

    def __getattr__(self, reading: str) -> Any:
        if reading.startswith("_") or reading in IGNORE:
            raise AttributeError(reading)
        if not self.tags.exists(reading):
            return self.tags.missed(reading)

        now = self.tags.answer(reading, "last",
                               (self.tags.when - 60, self.tags.when),
                               "current", {})
        then = self.tags.when - self.delta
        before = self.tags.answer(reading, "last",
                                  (then - self.grace, then + self.grace),
                                  "current", {})
        if now.value is None or before.value is None:
            return Value(None, now.unit, now.group, "current", self.tags.target)
        return Value(now.value - before.value, now.unit, now.group, "current",
                     self.tags.target)


# -- moments in local time -------------------------------------------------

def _number(value: Any) -> float | None:
    """A number out of a setting, however it was written. `440 meter` is 440."""
    if value is None:
        return None
    try:
        return float(str(value).split(",")[0].split()[0])
    except (ValueError, IndexError):
        return None


def _midnight(when: float) -> int:
    return int(datetime.datetime.fromtimestamp(when).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())


def _floor_hour(when: float) -> int:
    return int(datetime.datetime.fromtimestamp(when).replace(
        minute=0, second=0, microsecond=0).timestamp())


def _add_days(when: float, days: int) -> int:
    """Midnight, `days` from the day this moment is in.

    Walked in local time rather than added in seconds: a day is 23 or 25
    hours when the clocks change, and a week of daily figures read from the
    wrong boundary is a week of wrong figures.
    """
    moved = datetime.datetime.fromtimestamp(when) + datetime.timedelta(days=days)
    return int(moved.replace(hour=0, minute=0, second=0,
                             microsecond=0).timestamp())


def _week_start(when: float, first_day: int) -> int:
    """Midnight at the start of the week this moment is in.

    `first_day` is a `tm_wday`: Monday is 0 and Sunday is 6, which is WeeWX's
    default and not everybody's.
    """
    weekday = datetime.datetime.fromtimestamp(when).weekday()
    return _add_days(when, -((weekday - first_day) % 7))


def _month_start(when: float, months: int = 0) -> int:
    day = datetime.datetime.fromtimestamp(when).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    total = day.year * 12 + (day.month - 1) + months
    return int(day.replace(year=total // 12, month=total % 12 + 1).timestamp())


def _year_start(when: float, years: int = 0) -> int:
    day = datetime.datetime.fromtimestamp(when)
    return int(day.replace(year=day.year + years, month=1, day=1, hour=0,
                           minute=0, second=0, microsecond=0).timestamp())


def _rain_year_start(when: float, first_month: int) -> int:
    day = datetime.datetime.fromtimestamp(when)
    year = day.year if day.month >= first_month else day.year - 1
    return int(day.replace(year=year, month=first_month, day=1, hour=0,
                           minute=0, second=0, microsecond=0).timestamp())

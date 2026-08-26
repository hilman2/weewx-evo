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

#: The builtin, kept because `Tags.getattr` shadows the name inside the class.
builtin_getattr = getattr

#: When this process started, for `$station.uptime`. Taken at import rather
#: than at the first call, so a page rendered an hour in reports the hour.
STARTED = time.time()

#: The builtin, kept because `Value.round` shadows the name inside the class.
_round = round

#: Names a template imports rather than asks us for.
#:
#: Cheetah looks a `$name` up in the search list *before* the frame the
#: template was compiled in, so an object that answers everything -- which
#: `Tags` deliberately is -- swallows the template's own imports. A skin
#: writing `#import datetime` and then `$datetime.now()` gets our polite
#: `?'datetime'?` where WeeWX hands it the module, because WeeWX's search
#: list does not answer for a name it has never heard of.
#:
#: Declining these by name is the narrow fix. The wide one -- answer only
#: what we know about -- is exactly what must not happen: the whole point
#: of the tag layer is that `$day.<anything>` works for a sensor nobody
#: wrote down.
IMPORTED = {
    # Modules a template imports, and names it imports out of them.
    "datetime", "date", "timedelta", "time", "calendar", "math", "os",
    "sys", "json", "random", "re", "string", "itertools", "collections",
    "strftime", "strptime", "localtime", "gmtime", "mktime", "locale",
    "decimal", "operator", "Decimal",
    # And the pieces of WeeWX's own toolkit that a skin imports directly.
    "startOfDay", "startOfArchiveDay", "TimeSpan", "archiveDaySpan",
    "to_bool", "to_int", "to_float", "option_as_list", "search_up",
    "accumulateLeaves", "rounder",
    # And the builtins. `$str($x)` and `$len($y)` are ordinary in a
    # template, and a search list that answers for `str` hands the template
    # our `?'str'?` to call -- which fails as "can only concatenate str
    # (not Unknown) to str", nine pages at a time.
    "str", "int", "float", "bool", "len", "list", "dict", "tuple", "set",
    "sorted", "reversed", "enumerate", "range", "zip", "min", "max", "sum",
    "abs", "round", "type", "isinstance", "hasattr", "repr", "any", "all",
    "map", "filter", "print", "format",
}

#: Attributes Cheetah's NameMapper probes for on every lookup. Answering them
#: with a database query would be a query per attribute per tag.
IGNORE = {
    "__call__", "has_key", "__getstate__", "__setstate__", "__deepcopy__",
    "__len__", "__iter__", "__next__", "__reduce__", "__reduce_ex__",
    "__getitem__", "keys", "items", "values", "_no_aggregate",
    # NameMapper walks these looking for a way in. Answering them with a
    # database query is a query per attribute per tag.
    "mro", "im_func", "func_code", "__members__", "__methods__",
    "__class__", "__dict__", "__name__", "__module__", "__doc__",
}

#: How a time is printed, per span. WeeWX keeps these in a skin so they can be
#: translated; these are the defaults it ships.
TIME_FORMATS = {
    "hour": "%H:%M", "day": "%X", "week": "%X (%A)", "month": "%x %X",
    "year": "%x %X", "rainyear": "%x %X", "current": "%x %X",
    "ephem_day": "%X", "ephem_year": "%x %X",
}
DEFAULT_TIME_FORMAT = "%d-%b-%Y %H:%M"

#: How a *length* of time is spelled out, per span. A day is measured in
#: hours and minutes, a year in days: the same seconds, read differently.
DELTATIME_FORMATS = {
    "current": "%(minute)d%(minute_label)s, %(second)d%(second_label)s",
    "hour": "%(minute)d%(minute_label)s, %(second)d%(second_label)s",
    "day": "%(hour)d%(hour_label)s, %(minute)d%(minute_label)s, "
           "%(second)d%(second_label)s",
    "week": "%(day)d%(day_label)s, %(hour)d%(hour_label)s, "
            "%(minute)d%(minute_label)s",
    "month": "%(day)d%(day_label)s, %(hour)d%(hour_label)s, "
             "%(minute)d%(minute_label)s",
    "year": "%(day)d%(day_label)s, %(hour)d%(hour_label)s, "
            "%(minute)d%(minute_label)s",
}
DEFAULT_DELTATIME_FORMAT = ("%(day)d%(day_label)s, %(hour)d%(hour_label)s, "
                            "%(minute)d%(minute_label)s")

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
               None_string: str | None = None,  # noqa: N803
               add_label: bool = True, localize: bool = True) -> str:
        """The value as text.

        `format_string` is a printf format for a number and a strftime format
        for a time, which is WeeWX's arrangement and worth keeping: a template
        says `$day.outTemp.maxtime.format("%H:%M")` and means the clock.
        """
        if self.value is None:
            return None_string if None_string is not None else "   N/A"

        if self.unit in ("unix_epoch", "unix_epoch_ms", "unix_epoch_ns"):
            when = float(self.value)
            if self.unit == "unix_epoch_ms":
                when /= 1000.0
            elif self.unit == "unix_epoch_ns":
                when /= 1000000.0
            shape = format_string or self._time_format()
            return time.strftime(shape, time.localtime(when))

        shape = format_string or self._number_format()
        try:
            text = shape % self.value
        except (TypeError, ValueError):
            text = str(self.value)
        if add_label:
            text += self._label()
        return text

    # -- what the skin said, then what we ship ----------------------------

    def _time_format(self) -> str:
        if self.target and self.context in self.target.time_formats:
            return self.target.time_formats[self.context]
        return TIME_FORMATS.get(self.context, DEFAULT_TIME_FORMAT)

    def _number_format(self) -> str:
        if self.target:
            return self.target.format_for(self.unit) or "%s"
        return units.FORMATS.get(self.unit or "", "%s")

    def _label(self) -> str:
        plural = self.value != 1
        if self.target:
            return self.target.label_for(self.unit, plural)
        return units.label(self.unit, plural)

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
                None_string: str | None = None) -> str:  # noqa: N803
        return self.format(format_string, None_string, add_label=False)

    def string(self, None_string: str | None = None) -> str:  # noqa: N803
        return self.format(None_string=None_string)

    def long_form(self, format_string: str | None = None,
                  None_string: str | None = None) -> str:  # noqa: N803
        """A length of time in words. "5 hours, 12 minutes, 3 seconds".

        What `$almanac.sun.visible` wants: eighteen thousand seconds is not
        an answer anybody reads. Which pieces appear is decided by the span
        the value came from, so a day says hours and a year says days.
        """
        if self.value is None:
            return None_string if None_string is not None else "   N/A"
        shape = format_string
        if not shape and self.target:
            shape = self.target.deltatime_formats.get(self.context)
        if not shape:
            shape = DELTATIME_FORMATS.get(self.context,
                                          DEFAULT_DELTATIME_FORMAT)
        left = abs(units.convert(self.value, self.unit, "second") or 0.0)
        pieces: dict[str, Any] = {}
        for label, size in (("day", 86400), ("hour", 3600),
                            ("minute", 60), ("second", 1)):
            amount = int(left // size)
            pieces[label] = amount
            pieces[label + "_label"] = (
                self.target.label_for(label, amount != 1) if self.target
                else units.label(label, plural=amount != 1))
            left %= size
        if "day" not in shape:
            # Days were asked to be left out, so they are counted as hours
            # rather than dropped: "26 hours" beats "2 hours" for a value
            # that is really more than a day.
            pieces["hour"] += 24 * pieces["day"]
        return shape % pieces

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
        """A bearing as a point of the compass. `$day.wind.vecdir`.

        The skin's own words where it has them: a German page says NNO
        where an English one says NNE, and the difference goes straight
        into a sentence.
        """
        points = (self.target.ordinals if self.target
                  and self.target.ordinals else COMPASS)
        if self.value is None:
            return points[-1]
        sector = 360.0 / (len(points) - 1)
        degrees = (float(self.value) + sector / 2.0) % 360.0
        return points[int(degrees / sector)]

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

    def check_for_data(self, reading: str) -> bool:
        """`#if $recent.check_for_data($obs)` -- is there anything to draw?

        A template with the reading's name in a variable cannot write
        `$recent.outTemp.has_data`, so it asks this way instead. Same
        question, and Seasons decides whether to show a chart with it.
        """
        return self.tags.has_data(str(reading), self.span)

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

    def __call__(self, *_args: Any, **_kwargs: Any) -> "Current":
        """`$current($data_binding='wx_binding')`. The same readings again.

        WeeWX lets a template switch databases here. There is one archive
        in weewx-evo, so it comes back unchanged rather than pretending to
        bind something else -- and a skin that asks keeps working instead
        of failing with "'Current' object is not callable".
        """
        return self

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
        # `$station.latitude` is three strings, not a number: degrees,
        # minutes, and the direction. A NOAA report prints them one at a
        # time as `$station.latitude[0]`, and a float there raises.
        if name in ("latitude", "longitude") and name in self.values:
            return _sexagesimal(self.values[name],
                                "NS" if name == "latitude" else "EW")
        if name in self.values:
            return self.values[name]
        # WeeWX spells the number with a suffix and the text without.
        if name.endswith("_f") and name[:-2] in self.values:
            return _number(self.values[name[:-2]])
        if name == "uptime":
            return Value(time.time() - STARTED, "second", "group_deltatime",
                         "day", self.tags.target)
        if name == "os_uptime":
            return Value(_os_uptime(), "second", "group_deltatime", "day",
                         self.tags.target)
        return self.tags.missed(f"station.{name}")

    def __str__(self) -> str:
        return str(self.values.get("location", ""))


def _os_uptime() -> float | None:
    """How long the machine has been up, in seconds.

    Linux keeps it in a file, and nowhere else does. A skin printing it on a
    Windows box gets N/A, which is the truth rather than a guess.
    """
    try:
        with open("/proc/uptime", encoding="ascii") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


class Labels:
    """`$obs.label.outTemp` -- what a reading is called, in words.

    Deliberately *not* dict-like. Cheetah tries `obj[name]` on anything that
    has `__getitem__`, so a namespace that also answered subscripts would
    hand back the string "label" for `$obs.label` and the template would then
    subscript a string.
    """

    __slots__ = ("tags", "labels")

    def __init__(self, tags: "Tags", labels: dict[str, str]) -> None:
        self.tags = tags
        self.labels = labels

    @property
    def label(self) -> "_LabelMap":
        return _LabelMap(self.labels)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in IGNORE:
            raise AttributeError(name)
        return self.tags.missed(f"obs.{name}")


class _LabelMap(dict):
    """What each reading is called. `$obs.label.outTemp`, `$obs.label[$x]`.

    A real dictionary, so both spellings work: subscripting is the mapping,
    and an attribute falls through to it. A reading nobody named is called
    by its own name, which is better than blank.
    """

    def __getattr__(self, reading: str) -> str:
        if reading.startswith("_") or reading in IGNORE:
            raise AttributeError(reading)
        return self.get(reading, reading)

    def __missing__(self, reading: str) -> str:
        return reading


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

    @property
    def unit_type_dict(self) -> "_UnitField":
        """`$unit.unit_type_dict.outTemp` -- WeeWX's older spelling."""
        return _UnitField(self.tags, "unit")

    @property
    def label_dict(self) -> "_UnitField":
        return _UnitField(self.tags, "label")

    @property
    def format_dict(self) -> "_UnitField":
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
        """Whether the harder questions can be answered at all.

        Always, now. In WeeWX this asks "is pyephem installed", because
        without it there is no moon, no equinox and no next full moon. Here
        all three are worked out from Meeus's series and measured against
        pyephem in `tools/mooncheck.py`, so the honest answer is yes.

        It stays as a tag because a skin branches on it, and a skin that
        prints "install ephem for detailed celestial timings" should stop
        saying so rather than be edited.
        """
        return True

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
        # The skin's own names first: it prints them straight into a page,
        # so they are its to decide. Then the station's language, then the
        # English WeeWX ships.
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

        found = _moment(name, self.tags.when)
        if found is not None:
            return self._time(found, "ephem_year")
        if name in BODIES:
            # A planet. pyephem knows where they are; nothing here does,
            # and putting VSOP87 in would be another `moon.py` for four
            # readings nobody checks against a clock. With pyephem
            # installed these answer properly; without it they answer
            # "N/A", which is the truth and lets the page render.
            return Body(self.almanac, name)
        return self.tags.missed(f"almanac.{name}")


#: The bodies an almanac can be asked about. The sun and the moon are
#: worked out here; the planets need pyephem, and a skin that asks for one
#: gets an honest "N/A" rather than a broken page when it is not installed.
BODIES = frozenset({
    "sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn",
    "uranus", "neptune", "pluto",
})

#: The long name of each angle, and the short one it is the same reading as.
LONG_ANGLES = {"altitude": "alt", "azimuth": "az",
               "topo_dec": "dec", "topo_ra": "ra"}


class Body:
    """One thing in the sky. `$almanac.sun.rise`, `$almanac.moon.transit`."""

    __slots__ = ("almanac", "which", "use_center")

    def __init__(self, almanac: Almanac, which: str,
                 use_center: bool = False) -> None:
        self.almanac = almanac
        self.which = which
        #: Whether a rising is the moment the middle of the disc crosses the
        #: horizon rather than its upper edge. Twilight is defined on the
        #: centre, so `$almanac(horizon=-6).sun(use_center=1)` is how a skin
        #: asks for dawn.
        self.use_center = use_center

    def __call__(self, use_center: bool = False) -> "Body":
        return Body(self.almanac, self.which, bool(use_center))

    def _events(self, when: float | None = None) -> dict[str, float | None]:
        """When this body rises and sets, on the day the page is for.

        Anchored at local midnight and asking for the *next* one, which is
        how WeeWX does it. The alternative -- "the rising nearest noon" --
        has no answer on the days the moon rises twice.
        """
        tags = self.almanac.tags
        if not self.almanac._placed:
            return {}
        moment = tags.when if when is None else when
        found = sun_module.rising_setting(
            _midnight(moment), self.almanac.latitude,
            self.almanac.longitude, body=self.which,
            horizon=self.almanac.horizon,
            altitude_m=self.almanac.altitude or 0.0,
            use_center=self.use_center)
        if self.which == "sun" and self.almanac.horizon is None:
            twilight = sun_module.events(moment, self.almanac.latitude,
                                         self.almanac.longitude)
            found["dawn"], found["dusk"] = twilight["dawn"], twilight["dusk"]
        return found

    def _up_for(self, when: float | None = None) -> float | None:
        """How long the body is above the horizon that day, in seconds."""
        found = self._events(when)
        rise, sets = found.get("rise"), found.get("set")
        return None if rise is None or sets is None else sets - rise

    def visible_change(self, days_ago: int = 1) -> "Value":
        """How much longer the body is up today than it was `days_ago`.

        The number behind "three minutes more daylight". The earlier day is
        found by stepping the calendar back rather than by subtracting
        86400 seconds, because across a clock change those are not the same
        day and the answer would be off by an hour.
        """
        now = self._up_for()
        then = self._up_for(_add_days(self.almanac.tags.when, -days_ago))
        change = None if now is None or then is None else now - then
        return Value(change, "second", "group_deltatime", "hour",
                     self.almanac.tags.target)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in IGNORE:
            raise AttributeError(name)

        if name in ("rise", "set", "transit", "dawn", "dusk"):
            return self.almanac._time(self._events().get(name))

        if name == "visible":
            return Value(self._up_for(), "second", "group_deltatime", "day",
                         self.almanac.tags.target)

        # Every angle has two names in WeeWX, and they are not the same
        # thing. The long one is a Value that formats itself, the short one
        # is the bare number pyephem returned. A skin uses both --
        # `$almanac.sun.altitude.format("%.1f")` to print it and `#if
        # $almanac.sun.alt < 0` to decide with it -- so answering only one
        # breaks a page either way round.
        if name in LONG_ANGLES:
            short = LONG_ANGLES[name]
            degrees = _position(self, short)
            if name == "azimuth":
                return self.almanac.tags.shown(
                    degrees, "degree_compass", "group_direction",
                    "ephem_day")
            # Radians, as WeeWX stores an angle, and shown in whatever the
            # target says -- which is degrees. Handed back unconverted, a
            # skin's `.format("%.1f")` prints 0.7 where it has always
            # printed 41.3, and nothing says why.
            return self.almanac.tags.shown(
                None if degrees is None else math.radians(degrees),
                "radian", "group_angle", "ephem_day")

        if name in ("alt", "az", "dec", "ra"):
            # Radians and a plain float: what pyephem hands back, and what
            # a template comparing it to zero was written against.
            degrees = _position(self, name)
            return None if degrees is None else math.radians(degrees)

        return self.almanac.tags.missed(f"almanac.{self.which}.{name}")


def _position(body: Body, what: str) -> float | None:
    """Where something is in the sky right now, in degrees.

    pyephem where it is installed, because a skin that has printed the
    moon's azimuth for years should keep printing the same number. Without
    it: NOAA's series for the sun and Meeus's for the moon, both in this
    package, both measured.
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

    if body.which == "moon":
        from . import moon as moon_module

        right_ascension, declination, _parallax = moon_module.equatorial(
            tags.when)
        if what == "ra":
            return right_ascension
        if what == "dec":
            return declination
        if what in ("alt", "az"):
            return _horizon_of(right_ascension, declination, tags.when,
                               body.almanac.latitude,
                               body.almanac.longitude)[what == "az"]
        return None

    if body.which == "sun":
        if what == "alt":
            # From the refraction-corrected series rather than from the
            # geometry below, because that is the number the night shading
            # and `$almanac.sun.alt < 0` are both decided on.
            return sun_module.position(tags.when, body.almanac.latitude,
                                       body.almanac.longitude)[0]
        right_ascension, declination = sun_module.equatorial(tags.when)
        if what == "ra":
            return right_ascension
        if what == "dec":
            return declination
        if what == "az":
            return _horizon_of(right_ascension, declination, tags.when,
                               body.almanac.latitude,
                               body.almanac.longitude)[1]
    return None


def _horizon_of(right_ascension: float, declination: float, when: float,
                latitude: float, longitude: float) -> tuple[float, float]:
    """Altitude and azimuth, in degrees, from right ascension and declination.

    Azimuth from north through east, which is the convention every compass
    rose and every wind vane uses.
    """
    from . import moon as moon_module

    hour_angle = math.radians(
        (moon_module._gmst(when) + longitude - right_ascension) % 360.0)
    lat = math.radians(latitude)
    dec = math.radians(declination)

    altitude = math.asin(math.sin(lat) * math.sin(dec)
                         + math.cos(lat) * math.cos(dec)
                         * math.cos(hour_angle))
    azimuth = math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(lat)
        - math.tan(dec) * math.cos(lat))
    # atan2 there measures from south through west, which is the older
    # convention and is 180 degrees from what anybody expects to read.
    return math.degrees(altitude), (math.degrees(azimuth) + 180.0) % 360.0


#: Which point of the moon's cycle each name asks for, and which way to
#: look. WeeWX offers all of them and a skin uses two or three.
MOON_MOMENTS = {
    "next_new_moon": (0.0, True),
    "next_first_quarter_moon": (0.25, True),
    "next_full_moon": (0.5, True),
    "next_last_quarter_moon": (0.75, True),
    "previous_new_moon": (0.0, False),
    "previous_first_quarter_moon": (0.25, False),
    "previous_full_moon": (0.5, False),
    "previous_last_quarter_moon": (0.75, False),
}

#: And the four turns of the year. `next_equinox` is whichever comes first;
#: the named ones are for a page that wants a particular one.
SEASON_MOMENTS = {
    "next_vernal_equinox": (0, True),
    "next_summer_solstice": (1, True),
    "next_autumnal_equinox": (2, True),
    "next_winter_solstice": (3, True),
    "previous_vernal_equinox": (0, False),
    "previous_summer_solstice": (1, False),
    "previous_autumnal_equinox": (2, False),
    "previous_winter_solstice": (3, False),
}


def _moment(name: str, when: float) -> float | None:
    """One of the almanac's moments, or None if that is not one of them."""
    from . import moon as moon_module

    if name in MOON_MOMENTS:
        phase, forwards = MOON_MOMENTS[name]
        return moon_module.phase_event(when, phase, forwards)
    if name in SEASON_MOMENTS:
        which, forwards = SEASON_MOMENTS[name]
        return sun_module.season(when, which, forwards)
    # The unqualified pair: whichever equinox or solstice is nearest. Both
    # of the four turns are equinoxes or solstices, so each of these picks
    # from its own two.
    if name in ("next_equinox", "previous_equinox"):
        forwards = name.startswith("next")
        return _nearest(when, (0, 2), forwards)
    if name in ("next_solstice", "previous_solstice"):
        forwards = name.startswith("next")
        return _nearest(when, (1, 3), forwards)
    return None


def _nearest(when: float, which: tuple[int, ...], forwards: bool) -> float:
    found = [sun_module.season(when, quarter, forwards) for quarter in which]
    return min(found) if forwards else max(found)


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
        #: `[Extras]` and `[DisplayOptions]` from the skin: whatever its
        #: author invented, and what the skin shows or hides.
        self.extras: dict[str, Any] = {}
        self.display: dict[str, Any] = {}
        #: Which language the skin is being rendered in.
        self.language: str = "en"
        #: The charts there are, for `$getobs`. A template names one and asks
        #: which readings it draws.
        self.plots: Any = ()
        #: What degree days are counted from. A skin may move them, and two
        #: skins in one process may disagree, so they live here rather than
        #: on the reader they share.
        from .series import DEGREE_DAY_BASES

        self.degree_day_bases = dict(DEGREE_DAY_BASES)
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
        from .series import DEGREE_DAY_BASES, VECTORS

        # `wind` and `windvec` are not columns. They are the pair of columns,
        # and which one is meant depends on the question -- the highest wind
        # of a day is the highest gust. series.py knows; this only has to
        # agree that they are real.
        if reading in DEGREE_DAY_BASES:
            # Worked out from the daily mean temperature, so they exist
            # exactly where that does.
            return "outTemp" in self.reader.columns
        return (reading in self.reader.columns or reading in VECTORS
                or (reading == "wind" and "windSpeed" in self.reader.columns))

    def has_data(self, reading: str, span: tuple[float, float]) -> bool:
        try:
            return bool(self.reader.aggregate(reading, span[0], span[1],
                                              "not_null",
                                              self.degree_day_bases))
        except Exception:  # noqa: BLE001
            return False

    def shown(self, value: Any, unit: str | None, group: str | None,
              context: str = "current") -> "Value":
        """A number worked out in one unit, wrapped in what to show it in.

        Everything the database answers goes through `answer`, which does
        this on the way past. The almanac does not touch the database, so
        without this its angles came out in radians on a page set to
        degrees -- `.format("%.1f")` printing 0.7 where it had always
        printed 41.3.
        """
        wanted = self.target.unit(group) or unit
        try:
            converted = units.convert(value, unit, wanted)
        except ValueError:
            converted, wanted = value, unit
        return Value(converted, wanted, group, context, self.target)

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
            raw = self.reader.aggregate(reading, span[0], span[1], how,
                                        self.degree_day_bases)
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
    def Extras(self) -> "Section":  # noqa: N802 -- the tag's own spelling
        """`$Extras.something` -- whatever the skin's author invented."""
        return Section(self.extras)

    @property
    def DisplayOptions(self) -> "Section":  # noqa: N802
        """`$DisplayOptions.get('...')` -- what the skin shows and hides."""
        return Section(self.display)

    @property
    def lang(self) -> str:
        """Which language the skin is being rendered in."""
        return self.language

    @staticmethod
    def to_list(value: Any) -> list:
        """`$to_list($DisplayOptions.get('x'))`.

        A configuration file gives one string where there is one value and a
        list where there are several, so a template that wants to walk them
        has to say which it got. WeeWX has this helper for the same reason.
        """
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value]

    @staticmethod
    def getattr(obj: Any, name: str, default: Any = None) -> Any:
        """`$getattr($current, $x)` -- a reading whose name is in a variable.

        A template walking a list of readings cannot write `$current.outTemp`;
        it has the name in hand and has to ask for it. Python's own getattr,
        offered under the name WeeWX offers it under.
        """
        try:
            found = builtin_getattr(obj, str(name))
        except AttributeError:
            return default
        return default if found is None else found

    def getobs(self, plot_name: str) -> set:
        """`$getobs($plot_name)` -- which readings a chart draws.

        A template asks so that it can say "temperature and dew point" under
        a chart without the two being written down twice.
        """
        for plot in self.plots:
            if plot.name == str(plot_name):
                return plot.uses()
        return set()

    @staticmethod
    def to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def to_int(value: Any) -> int | None:
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def to_float(value: Any) -> float | None:
        return _number(value)

    @staticmethod
    def jsonize(value: Any) -> str:
        import json as _json

        return _json.dumps(value)

    @staticmethod
    def rnd(value: Any, ndigits: int = 2) -> Any:
        number = _number(value)
        return "N/A" if number is None else _round(number, ndigits)

    def season(self, seasons_ago: int = 0, **_kwargs: Any) -> Span:
        """The meteorological season this moment is in.

        Three months at a time, starting in December: what a forecaster means
        by winter, not what an almanac does.
        """
        day = datetime.datetime.fromtimestamp(self.when)
        first = ((day.month // 3) * 3) or 12
        year = day.year if day.month >= 3 else day.year - 1
        start = int(day.replace(year=year, month=first, day=1, hour=0,
                                minute=0, second=0,
                                microsecond=0).timestamp())
        start = _month_start(start, -3 * seasons_ago)
        return self._span(start, _month_start(start, 3), "month")

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
        """Anything not defined above. Counted, and then declined.

        Counted, because a skin asking for something nothing here has is
        worth reporting -- that is the whole reason this layer keeps a
        tally. Declined, because a template asks `$varExists('x')` before
        using `$x`, and an object that answers everything makes that always
        true. weewx-wdc does exactly this:

            #if $varExists('diagram_classes_custom')

        and with a polite `?'x'?` coming back it took the branch, then
        called `len()` on it.

        `$current.foo` and `$day.foo.max` are different questions and still
        answer WeeWX's way -- one prints `?'foo'?`, the other raises. This
        is the top level only: a bare `$foo` that nothing defines.
        """
        if name.startswith("_") or name in IGNORE or name in IMPORTED:
            raise AttributeError(name)
        self.missed(name)
        raise AttributeError(name)


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

class Section(dict):
    """A block of a skin's own configuration. `$Extras`, `$DisplayOptions`.

    A real dictionary, deliberately. Cheetah's NameMapper tries `obj[name]`
    on anything that looks like a mapping and only falls back to attributes
    when that raises `KeyError`. A stand-in that answered every subscript --
    returning None for a missing key, say -- swallows `$DisplayOptions.get`
    itself, and the template then calls None.

    Attribute access is the other half: `#if $Extras.radar_url` is how a
    template asks whether the operator configured something, and the answer
    when they did not is empty, not an error.
    """

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_") or key in IGNORE:
            raise AttributeError(key)
        found = self.get(key)
        if isinstance(found, dict):
            return Section(found)
        # Not a miss worth reporting: most of these are questions whose
        # answer is "not configured", asked once per page.
        return "" if found is None else found

    def __getitem__(self, key: str) -> Any:
        found = super().__getitem__(key)
        return Section(found) if isinstance(found, dict) else found


def _sexagesimal(value: Any, directions: str) -> tuple[str, str, str]:
    """A coordinate as degrees, minutes and a direction.

    What `$station.latitude` is in WeeWX, and what a NOAA report prints one
    piece at a time.
    """
    number = _number(value)
    if number is None:
        return ("", "", "")
    sign = directions[0] if number >= 0 else directions[1]
    number = abs(number)
    degrees = int(number)
    minutes = (number - degrees) * 60.0
    return (f"{degrees:02d}", f"{minutes:05.2f}", sign)


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

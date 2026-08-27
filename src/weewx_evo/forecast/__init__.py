"""Forecasts and warnings: what is going to happen, from somebody who knows.

A weather station measures. A forecast is the other half of what people
actually look at a weather page for, and WeeWX has never had one in the core --
which is why `weewx-DWD` exists and why it has grown to ten data sources, two
dependencies outside the standard library, radar animation and pollen counts.
That growth is the argument for drawing a line here rather than not having
this at all.

**The line: three sources and a fourth for the Americas.**

    open-meteo    the world. No key, plain JSON, and it picks the best model
                  for a location by itself -- ICON in Germany, ECMWF or GFS
                  elsewhere. One source covers almost everybody.
    dwd           Germany's own station forecast (MOSMIX). The point forecast
                  for an actual place rather than a grid cell, and what a
                  German page has always shown.
    meteoalarm    warnings for 38 European countries, in one Atom feed of CAP
                  documents. The official aggregator.
    nws           the United States: forecast and alerts in one API, no key.

Explicitly not here: radar animation, map servers, pollen, anything needing a
paid key. Each of those is a plugin's job, and the plugin interface is the
same one the drivers use.

**Where it goes: its own database, never the archive.**

That is the one rule of this project. `archive` is what WeeWX wrote and what
WeeWX must be able to keep reading; a column of predicted temperatures in it
would be a lie that averages badly for years. Forecasts live in
`forecast.sdb`, they are replaced wholesale when a new run arrives, and
deleting the file costs one download.

**What a source has to provide:**

    class MySource:
        def fetch(self, place: Place) -> Reading:
            ...

        @staticmethod
        def options():
            return [...]

`Reading` carries the hours, the days and the warnings a source found -- any
of them may be empty, because a warning service has no temperatures and a
model has no warnings.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "weewx_evo.forecast"


@dataclass(frozen=True, slots=True)
class Place:
    """Where the forecast is for."""

    latitude: float
    longitude: float
    altitude: float | None = None
    #: Only some sources need this: DWD wants one of its own station ids,
    #: MeteoAlarm wants a country. Left empty, a source works it out or says
    #: it cannot.
    station: str = ""
    name: str = ""


@dataclass(slots=True)
class Moment:
    """The forecast for one hour.

    Field names are the archive's, deliberately: `outTemp` here means the
    same thing it means in a record, so a template that formats one formats
    the other and `units.py` converts both. A forecast in its own vocabulary
    would need its own units table and its own formatting, and the two would
    drift.
    """

    #: Unix time this applies to.
    dateTime: int
    #: Which unit system the values below are in. Sources produce metric;
    #: this is carried rather than assumed so a US source can stay US.
    usUnits: int
    outTemp: float | None = None
    dewpoint: float | None = None
    appTemp: float | None = None
    outHumidity: float | None = None
    barometer: float | None = None
    windSpeed: float | None = None
    windDir: float | None = None
    windGust: float | None = None
    cloudCover: float | None = None
    #: Millimetres in this hour, not a rate.
    rain: float | None = None
    snow: float | None = None
    #: Per cent, where the source gives one. Absent is not zero.
    rainProbability: float | None = None
    radiation: float | None = None
    UV: float | None = None
    visibility: float | None = None
    #: The WMO present-weather code, which is what every source speaks once
    #: it is translated. `codes.py` turns it into a word and a symbol.
    code: int | None = None

    def values(self) -> dict[str, Any]:
        """The readings that are actually present, by name."""
        return {k: v for k, v in _as_dict(self).items()
                if v is not None and k not in ("dateTime", "usUnits")}


@dataclass(slots=True)
class Day:
    """The forecast for one day, as a source summarised it.

    Not derived from the hours. A source's own daily summary knows things the
    hours do not -- the maximum between two hourly samples, the sunrise for
    that date -- and recomputing it from the hours would quietly disagree
    with the numbers the same source publishes on its own site.
    """

    #: Local midnight of the day this describes.
    dateTime: int
    usUnits: int
    tempMax: float | None = None
    tempMin: float | None = None
    rain: float | None = None
    snow: float | None = None
    rainProbability: float | None = None
    windMax: float | None = None
    windGustMax: float | None = None
    windDir: float | None = None
    UVMax: float | None = None
    sunrise: int | None = None
    sunset: int | None = None
    sunshine: float | None = None
    code: int | None = None

    def values(self) -> dict[str, Any]:
        return {k: v for k, v in _as_dict(self).items()
                if v is not None and k not in ("dateTime", "usUnits")}


@dataclass(slots=True)
class Warning:
    """One official warning.

    Modelled on CAP, because every European and American warning service
    publishes CAP and the rest can be mapped onto it. The severity words are
    CAP's own -- Minor, Moderate, Severe, Extreme -- and are not translated
    here: a page decides how to say them, and `language.py` is where that
    lives.
    """

    #: A stable id from the source, so an update replaces rather than doubles.
    identifier: str
    event: str
    severity: str = "Unknown"
    urgency: str = ""
    certainty: str = ""
    #: Unix times. `ends` may be absent -- CAP allows a warning with no end.
    starts: int = 0
    ends: int | None = None
    issued: int = 0
    headline: str = ""
    description: str = ""
    instruction: str = ""
    area: str = ""
    #: What the source calls this kind of event, kept as it arrived. A German
    #: page wants "Sturmböen", not "Wind".
    kind: str = ""
    language: str = ""
    source: str = ""

    @property
    def rank(self) -> int:
        """How serious, as a number, so warnings can be sorted."""
        return {"minor": 1, "moderate": 2, "severe": 3, "extreme": 4}.get(
            self.severity.lower(), 0)


@dataclass(slots=True)
class Reading:
    """Everything one source returned in one fetch."""

    source: str = ""
    #: When the source issued this run. Not when we asked: a model that runs
    #: every six hours has an age, and a page that says "updated a minute
    #: ago" about a six-hour-old run is lying politely.
    issued: int = 0
    hours: list[Moment] = field(default_factory=list)
    days: list[Day] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    #: What the source said about itself, for the diagnostics page.
    note: str = ""

    @property
    def empty(self) -> bool:
        return not (self.hours or self.days or self.warnings)

    def summary(self) -> str:
        parts = []
        if self.hours:
            parts.append(f"{len(self.hours)} hours")
        if self.days:
            parts.append(f"{len(self.days)} days")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        if not parts:
            parts.append("nothing")
        if self.note:
            parts.append(self.note)
        return ", ".join(parts)


class ForecastError(Exception):
    """Something that stopped a source from answering."""

    def __init__(self, message: str, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


@runtime_checkable
class Source(Protocol):
    """Somewhere a forecast comes from."""

    def fetch(self, place: Place) -> Reading:
        ...


class BaseSource:
    """Defaults for a source. Only `fetch` has to be written."""

    label: str = "forecast"
    summary: str = ""
    #: How often it is worth asking. A model that runs every six hours does
    #: not produce anything new in between, and asking anyway is somebody
    #: else's bandwidth for nothing.
    every: int = 3600
    #: Whether this source produces warnings rather than numbers. Only used
    #: to word the settings page.
    warns: bool = False

    def fetch(self, place: Place) -> Reading:
        raise NotImplementedError

    def check(self, place: Place) -> str:
        """Fetch once and say what came back, for the settings page."""
        try:
            got = self.fetch(place)
        except ForecastError as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        return got.summary()

    def close(self) -> None:
        """Release anything held. Optional."""


#: The largest XML document any source here should send. MeteoAlarm's German
#: feed is about 60 kB, the DWD's warning bundle about 400 kB unpacked, and a
#: MOSMIX station file is 350 kB. Ten megabytes is far above all of them and
#: far below what an expansion attack needs to hurt.
MAX_XML = 10 * 1024 * 1024


def parse_xml(text: str, what: str = "document"):
    """Parse XML from a weather service, with a size limit in front.

    `xml.etree` rather than `defusedxml`, which is the usual answer and is a
    dependency this core does not take. What that costs and why it is
    acceptable here:

      * External entities and DTD retrieval are already off in `xml.etree` --
        it has never resolved them, so the classic XXE file-read does not
        apply.
      * What remains is entity expansion -- the "billion laughs" -- which
        turns a small document into a large one in memory. The defence is
        the size of what is accepted, and that is the check below plus the
        HTTP timeout.
      * These four sources are national weather services reached over TLS.
        An attacker who can substitute their responses can also substitute
        the forecast, which is a more direct problem than a memory one.

    Written once, here, so that reasoning exists in one place rather than as
    three copies of a `# noqa` comment.
    """
    from xml.etree import ElementTree

    if len(text) > MAX_XML:
        raise ForecastError(
            f"the {what} is {len(text) // 1024} kB, past the {MAX_XML // 1024} kB "
            f"limit; refusing to parse it")
    try:
        return ElementTree.fromstring(text)  # noqa: S314 - see the docstring
    except ElementTree.ParseError as exc:
        raise ForecastError(f"the {what} will not parse: {exc}") from exc


def _as_dict(obj: Any) -> dict[str, Any]:
    """A slotted dataclass as a dictionary.

    `dataclasses.asdict` recurses and copies; these are flat and hot, and the
    difference showed up as most of the time spent storing a week of hours.
    """
    return {name: getattr(obj, name) for name in obj.__slots__}


class Registry:
    """The forecast sources this installation has."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., object]] = {}
        self._loaded = False

    def register_factory(self, name: str, factory: Callable[..., object]) -> None:
        self._factories[name] = factory

    def factory_for(self, kind: str) -> Callable[..., object] | None:
        self.load()
        return self._factories.get(kind)

    def kinds(self) -> list[str]:
        self.load()
        return sorted(self._factories)

    def describe(self, kind: str) -> str:
        factory = self.factory_for(kind)
        return getattr(factory, "summary", "") if factory else ""

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        from importlib.metadata import entry_points

        for entry in entry_points(group=ENTRY_POINT_GROUP):
            try:
                self.register_factory(entry.name, entry.load())
                log.info("forecast source %r from %s", entry.name, entry.value)
            except Exception:
                log.exception("could not load the forecast source %r", entry.name)

        from . import dwd, meteoalarm, nws, openmeteo

        self.register_factory("open-meteo", openmeteo.OpenMeteo)
        self.register_factory("dwd", dwd.Mosmix)
        self.register_factory("dwd-warnings", dwd.DwdWarnings)
        self.register_factory("meteoalarm", meteoalarm.MeteoAlarm)
        self.register_factory("nws", nws.NationalWeatherService)


DEFAULT = Registry()


def kinds() -> list[str]:
    return DEFAULT.kinds()


def describe(kind: str) -> str:
    return DEFAULT.describe(kind)

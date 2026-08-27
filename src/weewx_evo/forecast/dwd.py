"""The Deutscher Wetterdienst: MOSMIX point forecasts and CAP warnings.

Open-Meteo already serves Germany well -- it runs ICON, which is the DWD's own
model. So why this file:

**MOSMIX is not a model, it is a correction of one.** It takes ICON's output
for a specific station and applies the statistical corrections that station's
history calls for. Where a grid cell says the valley is at 500 m and the
station is at 440, MOSMIX knows. It is what German weather pages have shown
for years, and it is a point forecast for an actual place rather than an
interpolation between four of them.

**The warnings are the DWD's own words.** MeteoAlarm carries the same
warnings, translated to English event names. `Sturmböen` is what a German page
wants, together with the paragraph of description the DWD writes for it, and
that only exists in the original feed.

Three things this file has to deal with.

**KMZ.** MOSMIX is a zipped KML file, encoded ISO-8859-1, about 350 kB per
station, with every value as a space-separated list under an element name. It
is not JSON and there is no JSON alternative. `zipfile` and
`xml.etree.ElementTree` are both in the standard library, so this costs
nothing but the code.

**Kelvin.** `TTT` is 287.35, not 14.2. Every temperature in MOSMIX is
absolute, and reading one as Celsius produces a forecast of 287 degrees --
which is at least obvious. The pressure is in pascals for the same reason.

**A station id, not a coordinate.** MOSMIX is published per station, and the
id is a WMO number. The nearest one is not derivable without the station list,
so `check()` fetches that list and names the five nearest -- which is how
somebody finds theirs, the same arrangement as the MeteoAlarm regions.
"""

from __future__ import annotations

import io
import logging
import math
import re
import zipfile

from .. import units
from ..uploads import request
from . import BaseSource, ForecastError, Moment, Place, Reading, Warning, parse_xml
from .meteoalarm import parse_time

log = logging.getLogger(__name__)

HOST = "opendata.dwd.de"
MOSMIX_PATH = ("/weather/local_forecasts/mos/MOSMIX_L/single_stations/"
               "{station}/kml/MOSMIX_L_LATEST_{station}.kmz")
STATIONS_PATH = "/weather/local_forecasts/mos/MOSMIX_L/single_stations/"
WARNINGS_PATH = ("/weather/alerts/cap/COMMUNEUNION_DWD_STAT/"
                 "Z_CAP_C_EDZW_LATEST_PVW_STATUS_PREMIUMDWD_COMMUNEUNION_{lang}.zip")

DWD = "{https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd}"
KML = "{http://www.opengis.net/kml/2.2}"
CAP = "{urn:oasis:names:tc:emergency:cap:1.2}"

#: (MOSMIX element, our name, how to convert). Only the elements a forecast
#: page uses -- MOSMIX publishes about a hundred, most of them ensemble
#: spreads and probability thresholds nobody draws.
ELEMENTS: tuple[tuple[str, str, str], ...] = (
    ("TTT", "outTemp", "K"),
    ("Td", "dewpoint", "K"),
    ("TX", "tempMax", "K"),
    ("TN", "tempMin", "K"),
    ("FF", "windSpeed", ""),
    ("DD", "windDir", ""),
    ("FX1", "windGust", ""),
    ("N", "cloudCover", ""),
    ("PPPP", "barometer", "Pa"),
    ("RR1c", "rain", ""),
    ("R101", "rainProbability", ""),
    ("ww", "code", "int"),
    ("Rad1h", "radiation", "kJ"),
    ("VV", "visibility", "m"),
)


class Mosmix(BaseSource):
    """A point forecast for one DWD station."""

    label = "DWD MOSMIX"
    summary = ("Germany's own station forecast: ICON corrected for a "
               "specific place, which is what German weather pages show.")
    #: MOSMIX_L runs four times a day, MOSMIX_S hourly. Asking hourly is
    #: enough for either and never more than an hour behind.
    every = 3600

    def __init__(self, station: str = "", host: str = HOST,
                 timeout: int = 30, every: int = 3600) -> None:
        self.station = str(station or "").strip()
        self.host = host or HOST
        self.timeout = int(timeout)
        self.every = int(every)

    # -- fetching --------------------------------------------------------

    def _kml(self, station: str) -> str:
        status, body = request(
            self.host, MOSMIX_PATH.format(station=station),
            timeout=self.timeout, binary=True)
        if status == 404:
            raise ForecastError(
                f"The DWD has no MOSMIX station {station!r}. It is a WMO "
                f"number, five digits or five characters -- press 'Test' to "
                f"see the ones nearest to this station.", permanent=True)
        if status != 200:
            raise ForecastError(f"The DWD answered {status}")
        try:
            archive = zipfile.ZipFile(io.BytesIO(body))
            raw = archive.read(archive.namelist()[0])
        except (zipfile.BadZipFile, IndexError, KeyError) as exc:
            raise ForecastError(f"The DWD file will not open: {exc}") from exc
        # ISO-8859-1, declared in the file and not UTF-8. Reading it as UTF-8
        # fails on the first German place name with an umlaut in it.
        return raw.decode("iso-8859-1")

    def fetch(self, place: Place) -> Reading:
        station = self.station or place.station
        if not station:
            raise ForecastError(
                "MOSMIX needs a DWD station id: the forecast is published per "
                "station, not per coordinate.", permanent=True)
        return self.read(self._kml(station))

    def read(self, kml: str) -> Reading:
        """Turn one MOSMIX document into hours. Separate so a test can run it."""
        root = parse_xml(kml, "MOSMIX file")
        steps = [parse_time(node.text) for node in
                 root.iter(f"{DWD}TimeStep")]
        if not steps:
            raise ForecastError("MOSMIX gave no time steps")

        columns: dict[str, list[float | None]] = {}
        for forecast in root.iter(f"{DWD}Forecast"):
            name = forecast.get(f"{DWD}elementName")
            if name is None:
                continue
            value = forecast.find(f"{DWD}value")
            if value is None or not value.text:
                continue
            columns[name] = _numbers(value.text)

        issued = 0
        for node in root.iter(f"{DWD}IssueTime"):
            issued = parse_time(node.text)
            break
        name = ""
        for node in root.iter(f"{KML}description"):
            name = (node.text or "").strip()
            break

        reading = Reading(source="dwd", issued=issued,
                          note=name.title() if name else "")
        for index, when in enumerate(steps):
            if not when:
                continue
            moment = Moment(dateTime=when, usUnits=units.METRICWX)
            for element, ours, how in ELEMENTS:
                if ours in ("tempMax", "tempMin"):
                    # MOSMIX publishes TX and TN as hourly columns that are
                    # empty except at the hours the 24-hour window closes,
                    # and which window that is differs by station. Turning
                    # that into a calendar day is guesswork, and a wrong
                    # daily maximum is worse than none -- so the days come
                    # from Open-Meteo, which states them directly.
                    continue
                column = columns.get(element)
                if column is None or index >= len(column):
                    continue
                value = column[index]
                if value is None:
                    continue
                setattr(moment, ours, _convert(value, how))
            reading.hours.append(moment)
        return reading

    # -- finding a station -----------------------------------------------

    def nearest(self, place: Place, limit: int = 5) -> list[tuple[float, str]]:
        """The station ids nearest to a point, from the DWD's own listing.

        The directory index is the station list: one directory per station,
        named by its id. It has no coordinates in it, so this uses the
        catalogue the DWD publishes beside it.
        """
        status, body = request(self.host, STATIONS_PATH, timeout=self.timeout)
        if status != 200:
            raise ForecastError(f"could not read the DWD station list ({status})")
        ids = sorted(set(re.findall(r'href="(\w{4,5})/"', body)))
        if not ids:
            raise ForecastError("the DWD station list came back empty")
        found = self._catalogue()
        scored = []
        for station in ids:
            where = found.get(station)
            if where is None:
                continue
            scored.append((_distance(place.latitude, place.longitude,
                                     where[0], where[1]),
                           f"{station}  {where[2]}"))
        scored.sort()
        return scored[:limit]

    def _catalogue(self) -> dict[str, tuple[float, float, str]]:
        """Station coordinates, from the DWD's fixed-width catalogue."""
        status, body = request(
            self.host,
            "/weather/local_forecasts/mos/MOSMIX_L/single_stations/"
            "mosmix_stationskatalog.cfg", timeout=self.timeout)
        if status != 200:
            return {}
        found = {}
        for line in body.split("\n"):
            # `10870 EDDM MUENCHEN-FLUGH.       48.35    11.78    453`
            parts = line.split()
            if len(parts) < 5 or not parts[0].strip():
                continue
            try:
                longitude = float(parts[-2])
                latitude = float(parts[-3])
            except ValueError:
                continue
            name = " ".join(parts[2:-3]) or parts[1]
            found[parts[0]] = (latitude, longitude, name)
        return found

    def check(self, place: Place) -> str:
        station = self.station or place.station
        if not station:
            try:
                near = self.nearest(place)
            except Exception as exc:
                return f"no station set, and the list could not be read: {exc}"
            lines = ["No station set. The nearest DWD stations to this one:"]
            lines += [f"  {name}  ({how:.0f} km)" for how, name in near]
            return "\n".join(lines)
        try:
            got = self.fetch(place)
        except ForecastError as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"could not reach {self.host}: {exc}"
        first = got.hours[0] if got.hours else None
        now = ""
        if first is not None and first.outTemp is not None:
            now = f" The first hour is {first.outTemp:.1f} °C."
        return f"{got.summary()} from station {station}.{now}"

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("Which station", "", (
                Option("station", "DWD station id", placeholder="10870",
                       help="A WMO number. Leave it empty and press 'Test' to "
                            "see the stations nearest to yours."),
            )),
            Group("How often", "", (
                Option("every", "Ask every", kind="duration", default=3600,
                       minimum=900, maximum=86400,
                       help="MOSMIX_L runs four times a day. Hourly is never "
                            "more than an hour behind it."),
            )),
            Group("How", "", (
                Option("host", "Server", default=HOST, advanced=True),
                Option("timeout", "Give up after", kind="duration",
                       default=30, minimum=10, maximum=180, advanced=True,
                       help="A station file is about 350 kB."),
            )),
        ]


class DwdWarnings(BaseSource):
    """Warnings straight from the DWD, in their own words."""

    label = "DWD warnings"
    summary = ("Germany's official warnings, with the DWD's own wording and "
               "description -- which MeteoAlarm translates away.")
    warns = True
    every = 600

    #: The languages the DWD publishes the same warnings in.
    LANGUAGES = (("DE", "German"), ("EN", "English"), ("FR", "French"),
                 ("ES", "Spanish"), ("MUL", "all of them"))

    def __init__(self, area: str = "", language: str = "DE",
                 minimum: str = "Minor", host: str = HOST,
                 timeout: int = 30, every: int = 600) -> None:
        self.areas = [a.strip().lower() for a in (area or "").split(",")
                      if a.strip()]
        self.language = (language or "DE").strip().upper()
        self.minimum = (minimum or "Minor").strip()
        self.host = host or HOST
        self.timeout = int(timeout)
        self.every = int(every)

    def _documents(self) -> list[str]:
        status, body = request(
            self.host, WARNINGS_PATH.format(lang=self.language),
            timeout=self.timeout, binary=True)
        if status != 200:
            raise ForecastError(f"The DWD answered {status} for the warnings")
        try:
            archive = zipfile.ZipFile(io.BytesIO(body))
            return [archive.read(name).decode("utf-8", "replace")
                    for name in archive.namelist()]
        except zipfile.BadZipFile as exc:
            raise ForecastError(f"the DWD warning file will not open: "
                                f"{exc}") from exc

    def fetch(self, place: Place) -> Reading:
        reading = Reading(source="dwd-warnings")
        for document in self._documents():
            reading.warnings.extend(w for w in self.read(document)
                                    if self._wanted(w))
        if not self.areas:
            reading.note = ("no area set, so every warning in Germany is "
                            "kept")
        return reading

    def read(self, xml: str) -> list[Warning]:
        """One CAP document. It carries several areas per alert."""
        try:
            root = parse_xml(xml, "DWD warning")
        except ForecastError:
            # One unparseable document in a bundle of several is not a reason
            # to lose the rest, and the bundle is where they arrive.
            log.debug("skipping a DWD warning document that will not parse")
            return []
        identifier = _find(root, f"{CAP}identifier")
        sent = parse_time(_find(root, f"{CAP}sent"))
        found = []
        for info in root.findall(f"{CAP}info"):
            severity = _find(info, f"{CAP}severity") or "Unknown"
            event = _find(info, f"{CAP}event")
            starts = parse_time(_find(info, f"{CAP}onset")
                                or _find(info, f"{CAP}effective"))
            ends = parse_time(_find(info, f"{CAP}expires")) or None
            for area in info.findall(f"{CAP}area"):
                where = _find(area, f"{CAP}areaDesc")
                # One alert covers many districts, and each is its own
                # warning as far as a page is concerned. Without the area in
                # the identifier they collapse into one and a station sees
                # somebody else's district.
                found.append(Warning(
                    identifier=f"{identifier}:{where}",
                    event=event,
                    severity=severity,
                    urgency=_find(info, f"{CAP}urgency"),
                    certainty=_find(info, f"{CAP}certainty"),
                    starts=starts, ends=ends, issued=sent,
                    headline=_find(info, f"{CAP}headline"),
                    description=_find(info, f"{CAP}description"),
                    instruction=_find(info, f"{CAP}instruction"),
                    area=where,
                    kind=_find(info, f"{CAP}category"),
                    language=_find(info, f"{CAP}language"),
                    source="dwd",
                ))
        return found

    def _wanted(self, warning: Warning) -> bool:
        if warning.rank < _rank(self.minimum):
            return False
        if not self.areas:
            return True
        return any(a in warning.area.lower() for a in self.areas)

    def check(self, place: Place) -> str:
        try:
            everything = [w for d in self._documents() for w in self.read(d)]
        except ForecastError as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"could not reach {self.host}: {exc}"
        if not everything:
            return ("Reachable, and there are no warnings for Germany right "
                    "now -- which is what calm weather looks like.")
        kept = [w for w in everything if self._wanted(w)]
        areas = sorted({w.area for w in everything if w.area})
        lines = [(f"{len(everything)} warning(s) for Germany, {len(kept)} of "
                  f"them matching this setting."), "",
                 "Areas with a warning right now -- any part of a name works:"]
        lines += [f"  {a}" for a in areas[:40]]
        if len(areas) > 40:
            lines.append(f"  ... and {len(areas) - 40} more")
        return "\n".join(lines)

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("Where", "", (
                Option("area", "District", kind="list",
                       placeholder="Kreis Freising, Stadt München",
                       help="The DWD publishes warnings for every German "
                            "district at once. Any part of a name works, and "
                            "several are allowed. Empty keeps all of them, "
                            "which is loud but never misses one. Press 'Test' "
                            "to see the districts with a warning right now."),
            )),
            Group("What to keep", "", (
                Option("language", "Language", kind="choice", default="DE",
                       choices=DwdWarnings.LANGUAGES,
                       help="The DWD publishes the same warnings in each. "
                            "The German wording is the original."),
                Option("minimum", "At least", kind="choice", default="Minor",
                       choices=(("Minor", "everything, including yellow"),
                                ("Moderate", "orange and above"),
                                ("Severe", "red and above"),
                                ("Extreme", "only the most severe"))),
            )),
            Group("How often", "", (
                Option("every", "Ask every", kind="duration", default=600,
                       minimum=300, maximum=7200),
            )),
            Group("How", "", (
                Option("host", "Server", default=HOST, advanced=True),
                Option("timeout", "Give up after", kind="duration",
                       default=30, minimum=10, maximum=180, advanced=True),
            )),
        ]


# ---------------------------------------------------------------------------

def _numbers(text: str) -> list[float | None]:
    """A MOSMIX value list. `-` means the model has no value for that hour."""
    out: list[float | None] = []
    for entry in text.split():
        if entry == "-":
            out.append(None)
            continue
        try:
            out.append(float(entry))
        except ValueError:
            out.append(None)
    return out


def _convert(value: float, how: str) -> float:
    if how == "K":
        # 287.35, not 14.2. Reading Kelvin as Celsius gives a forecast of
        # 287 degrees, which is at least unmistakable.
        converted = units.convert(value, "degree_K", "degree_C")
        return float(converted) if converted is not None else value
    if how == "Pa":
        return value / 100.0                     # pascals to millibars
    if how == "kJ":
        # kJ/m2 over the hour, and `group_radiation` is W/m2: 1 kJ over 3600
        # seconds is 1000/3600 W.
        return value * 1000.0 / 3600.0
    if how == "m":
        return value / 1000.0                    # metres to kilometres
    if how == "int":
        return int(value)
    return value


def _find(element: object, path: str) -> str:
    found = element.find(path) if element is not None else None
    if found is None or found.text is None:
        return ""
    return re.sub(r"[ \t]+", " ", found.text).strip()


def _rank(severity: str) -> int:
    return {"minor": 1, "moderate": 2, "severe": 3, "extreme": 4}.get(
        severity.lower(), 0)


def _distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle kilometres. Only ever used to sort a list of stations."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))

"""The National Weather Service: forecasts and alerts for the United States.

`api.weather.gov` needs no account and publishes CAP, so this is the American
half of what MeteoAlarm is for Europe -- with the forecast in the same API
rather than a separate one.

Three things this file has to deal with.

**A User-Agent is required.** The NWS asks for one identifying the
application, and answers 403 without it. That is unusual enough to be worth
stating: the same request from a browser works and from a library does not,
which reads as a network problem for an afternoon.

**A point is not a grid square.** Everything goes through `/points/{lat},{lon}`
first, which answers with the office and grid coordinates to ask next. That
lookup is stable for a fixed station, so it is done once and remembered -- two
requests every hour for a station that has not moved since 2019 is rude.

**The forecast is prose.** `/forecast/hourly` gives `"10 mph"` and
`"Mostly Cloudy"` rather than numbers and codes, because it is written for
people. The strings are parsed back into numbers here, and the phrases mapped
onto WMO codes -- which is lossy, and the reason Open-Meteo stays the default
even in America. What the NWS is unambiguously best at is the alerts.
"""

from __future__ import annotations

import json
import logging
import re

from .. import units
from ..uploads import request
from . import BaseSource, ForecastError, Moment, Place, Reading, Warning
from .meteoalarm import parse_time

log = logging.getLogger(__name__)

HOST = "api.weather.gov"

#: The NWS asks for an identifying User-Agent and answers 403 without one.
#: A contact address is what they suggest; the project's home is the honest
#: equivalent and does not put anybody's email in a header.
USER_AGENT = "weewx-evo (https://github.com/hilman2/weewx-evo)"

#: NWS forecast phrases onto WMO codes. Matched longest first, so
#: "Slight Chance Rain Showers" is a shower and not clear sky.
PHRASES: tuple[tuple[str, int], ...] = (
    ("thunderstorm", 95),
    ("freezing rain", 67),
    ("freezing drizzle", 57),
    ("ice pellets", 77),
    ("sleet", 77),
    ("snow showers", 86),
    ("blowing snow", 75),
    ("heavy snow", 75),
    ("snow", 73),
    ("rain showers", 81),
    ("showers", 81),
    ("heavy rain", 65),
    ("drizzle", 53),
    ("rain", 63),
    ("freezing fog", 48),
    ("fog", 45),
    ("haze", 45),
    ("smoke", 45),
    ("overcast", 3),
    ("cloudy", 3),
    ("mostly cloudy", 3),
    ("partly cloudy", 2),
    ("partly sunny", 2),
    ("mostly sunny", 1),
    ("mostly clear", 1),
    ("sunny", 0),
    ("clear", 0),
    ("fair", 0),
)

_NUMBER = re.compile(r"(-?\d+(?:\.\d+)?)")
#: `NNW` and the rest, as bearings. The NWS gives wind direction as a word.
BEARINGS = {"N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5, "E": 90,
            "ESE": 112.5, "SE": 135, "SSE": 157.5, "S": 180,
            "SSW": 202.5, "SW": 225, "WSW": 247.5, "W": 270,
            "WNW": 292.5, "NW": 315, "NNW": 337.5}


def code_for(phrase: str) -> int | None:
    """A WMO code for an NWS phrase, or None if it says nothing about weather.

    Longest match wins, so "Chance Rain Showers" is 81 rather than 63. This
    is lossy by nature: the NWS writes for people, and "Slight Chance" is a
    probability that has its own field.
    """
    lowered = (phrase or "").lower()
    best: tuple[int, int] | None = None
    for text, code in PHRASES:
        if text in lowered and (best is None or len(text) > best[0]):
            best = (len(text), code)
    return best[1] if best else None


def speed(text: str) -> float | None:
    """`"10 mph"` or `"5 to 10 mph"` as metres per second.

    A range becomes its upper end, which is what a forecast of "5 to 10" is
    warning about. Silently taking the lower one would be the friendlier
    number and the wrong one.
    """
    found = _NUMBER.findall(text or "")
    if not found:
        return None
    value = max(float(n) for n in found)
    unit = "km_per_hour" if "km/h" in (text or "").lower() else "mile_per_hour"
    converted = units.convert(value, unit, "meter_per_second")
    return None if converted is None else float(converted)


class NationalWeatherService(BaseSource):
    """Forecasts and alerts from api.weather.gov."""

    label = "US National Weather Service"
    summary = ("The United States: official alerts, and a forecast, with no "
               "account. The alerts are what it is best at.")
    warns = True
    every = 1800

    def __init__(self, alerts: bool = True, forecast: bool = False,
                 minimum: str = "Minor", host: str = HOST,
                 timeout: int = 20, every: int = 1800) -> None:
        self.alerts = bool(alerts)
        # Off by default: Open-Meteo already has the numbers, in numbers,
        # and this one has to be parsed back out of English.
        self.forecast = bool(forecast)
        self.minimum = (minimum or "Minor").strip()
        self.host = host or HOST
        self.timeout = int(timeout)
        self.every = int(every)
        self._grid: str | None = None
        if not (self.alerts or self.forecast):
            raise ValueError("the NWS source with neither alerts nor a "
                             "forecast would fetch nothing")

    # -- requests --------------------------------------------------------

    def _get(self, path: str) -> dict:
        status, body = request(self.host, path, timeout=self.timeout,
                               headers={"User-Agent": USER_AGENT,
                                        "Accept": "application/geo+json"})
        if status == 404:
            raise ForecastError(
                "The NWS has no data for that point. It covers the United "
                "States and its territories only.", permanent=True)
        if status == 403:
            raise ForecastError("The NWS refused the request; it requires a "
                                "User-Agent identifying the application.",
                                permanent=True)
        if status != 200:
            raise ForecastError(f"The NWS answered {status}: {body[:120]}")
        try:
            return json.loads(body)
        except ValueError as exc:
            raise ForecastError(f"The NWS sent something that is not JSON: "
                                f"{exc}") from exc

    def grid(self, place: Place) -> str:
        """The hourly-forecast path for this point, looked up once.

        Remembered because it does not change for a station that stays where
        it is, and two requests an hour for a fixed answer is bad manners.
        """
        if self._grid is None:
            found = self._get(f"/points/{place.latitude:.4f},{place.longitude:.4f}")
            url = (found.get("properties") or {}).get("forecastHourly")
            if not url:
                raise ForecastError("The NWS knows that point but offers no "
                                    "hourly forecast for it.", permanent=True)
            # Their answer is a full URL; only the path is wanted, and taking
            # the host from it would follow a redirect nobody checked.
            self._grid = url.split(self.host, 1)[-1] or url
        return self._grid

    # -- reading ---------------------------------------------------------

    def fetch(self, place: Place) -> Reading:
        reading = Reading(source="nws")
        if self.alerts:
            found = self._get(
                f"/alerts/active?point={place.latitude:.4f},{place.longitude:.4f}")
            reading.warnings = self.read_alerts(found)
        if self.forecast:
            reading.hours = self.read_forecast(self._get(self.grid(place)))
        return reading

    def read_alerts(self, data: dict) -> list[Warning]:
        found = []
        for feature in data.get("features") or []:
            p = feature.get("properties") or {}
            if _rank(str(p.get("severity") or "")) < _rank(self.minimum):
                continue
            if str(p.get("messageType") or "").lower() == "cancel":
                # A cancellation is not a warning. Keeping it would put
                # "Flood Warning" on a page for something that just ended.
                continue
            found.append(Warning(
                identifier=str(p.get("id") or ""),
                event=str(p.get("event") or ""),
                severity=str(p.get("severity") or "Unknown"),
                urgency=str(p.get("urgency") or ""),
                certainty=str(p.get("certainty") or ""),
                starts=parse_time(p.get("onset") or p.get("effective")),
                # `ends` is when the weather stops, `expires` is when the
                # message goes stale. A page wants the first where there is
                # one -- they differ by half an hour on most alerts.
                ends=parse_time(p.get("ends") or p.get("expires")) or None,
                issued=parse_time(p.get("sent")),
                headline=str(p.get("headline") or ""),
                description=str(p.get("description") or ""),
                instruction=str(p.get("instruction") or ""),
                area=str(p.get("areaDesc") or ""),
                kind=str(p.get("category") or ""),
                language=str(p.get("language") or ""),
                source="nws",
            ))
        return found

    def read_forecast(self, data: dict) -> list[Moment]:
        hours = []
        for period in (data.get("properties") or {}).get("periods") or []:
            when = parse_time(period.get("startTime"))
            if not when:
                continue
            moment = Moment(dateTime=when, usUnits=units.METRICWX)
            temperature = period.get("temperature")
            if temperature is not None:
                value = float(temperature)
                if str(period.get("temperatureUnit") or "F").upper() == "F":
                    converted = units.convert(value, "degree_F", "degree_C")
                    value = float(converted) if converted is not None else value
                moment.outTemp = value
            humidity = (period.get("relativeHumidity") or {}).get("value")
            if humidity is not None:
                moment.outHumidity = float(humidity)
            chance = (period.get("probabilityOfPrecipitation") or {}).get("value")
            if chance is not None:
                moment.rainProbability = float(chance)
            moment.windSpeed = speed(str(period.get("windSpeed") or ""))
            bearing = BEARINGS.get(str(period.get("windDirection") or "").upper())
            if bearing is not None:
                moment.windDir = bearing
            moment.code = code_for(str(period.get("shortForecast") or ""))
            hours.append(moment)
        return hours

    def check(self, place: Place) -> str:
        try:
            got = self.fetch(place)
        except ForecastError as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"could not reach {self.host}: {exc}"
        if got.empty:
            return ("Reachable, and there is nothing active for that point -- "
                    "which is what ordinary weather looks like.")
        lines = [got.summary()]
        for warning in got.warnings[:5]:
            lines.append(f"  {warning.severity:<9} {warning.event} "
                         f"({warning.area[:50]})")
        return "\n".join(lines)

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("What to fetch", "", (
                Option("alerts", "Warnings", kind="bool", default=True,
                       help="The official US warnings for this point. This is "
                            "what the NWS is best at."),
                Option("forecast", "Also the forecast", kind="bool",
                       default=False,
                       help="Off, because Open-Meteo already covers the "
                            "United States with actual numbers. The NWS "
                            "forecast is written in English -- '10 mph', "
                            "'Mostly Cloudy' -- and has to be parsed back "
                            "out, which loses something every time."),
            )),
            Group("What to keep", "", (
                Option("minimum", "At least", kind="choice", default="Minor",
                       choices=(("Minor", "everything"),
                                ("Moderate", "moderate and above"),
                                ("Severe", "severe and above"),
                                ("Extreme", "only extreme"))),
            )),
            Group("How often", "", (
                Option("every", "Ask every", kind="duration", default=1800,
                       minimum=300, maximum=7200),
            )),
            Group("How", "", (
                Option("host", "API host", default=HOST, advanced=True),
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True),
            )),
        ]


def _rank(severity: str) -> int:
    return {"minor": 1, "moderate": 2, "severe": 3, "extreme": 4}.get(
        severity.lower(), 0)

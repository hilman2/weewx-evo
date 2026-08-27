"""Open-Meteo: a forecast for anywhere, without an account.

This is the one source that covers almost everybody, which is why it is the
default. No API key, plain JSON, and its `best_match` model picks what is
actually best for a location -- ICON in Germany, AROME in France, HRRR in the
United States, ECMWF or GFS where nothing local exists. A station in Chile and
a station in Bavaria both get a sensible answer from the same configuration.

Three details that are decisions:

**`timeformat=unixtime`.** The default is local ISO strings without a zone,
and parsing those means knowing which zone the API decided on and hoping it
agrees with ours. Unix time has none of that; the API supports it; use it.

**Metric, and said so.** Open-Meteo can answer in Fahrenheit and inches, and
asking it to would put the conversion in two places. It answers in metric,
`units.py` converts on the way out, and the archive's own unit system is left
out of it entirely.

**The daily numbers are the source's own.** Not recomputed from the hours. A
maximum between two hourly samples is in their daily figure and not in ours,
and a page showing a different high than Open-Meteo's own site would be our
bug even though the arithmetic is defensible.
"""

from __future__ import annotations

import json
import logging

from .. import units
from ..uploads import request  # the same stdlib HTTP, one place
from . import BaseSource, Day, ForecastError, Moment, Place, Reading

log = logging.getLogger(__name__)

HOST = "api.open-meteo.com"
PATH = "/v1/forecast"

#: (their name, our name). Ours are the archive's names on purpose: a
#: template that formats `outTemp` from a record formats it from a forecast,
#: and `units.py` converts both.
HOURLY: tuple[tuple[str, str], ...] = (
    ("temperature_2m", "outTemp"),
    ("dew_point_2m", "dewpoint"),
    ("apparent_temperature", "appTemp"),
    ("relative_humidity_2m", "outHumidity"),
    ("pressure_msl", "barometer"),
    ("wind_speed_10m", "windSpeed"),
    ("wind_direction_10m", "windDir"),
    ("wind_gusts_10m", "windGust"),
    ("cloud_cover", "cloudCover"),
    ("precipitation", "rain"),
    ("snowfall", "snow"),
    ("precipitation_probability", "rainProbability"),
    ("shortwave_radiation", "radiation"),
    ("uv_index", "UV"),
    ("visibility", "visibility"),
    ("weather_code", "code"),
)

DAILY: tuple[tuple[str, str], ...] = (
    ("temperature_2m_max", "tempMax"),
    ("temperature_2m_min", "tempMin"),
    ("precipitation_sum", "rain"),
    ("snowfall_sum", "snow"),
    ("precipitation_probability_max", "rainProbability"),
    ("wind_speed_10m_max", "windMax"),
    ("wind_gusts_10m_max", "windGustMax"),
    ("wind_direction_10m_dominant", "windDir"),
    ("uv_index_max", "UVMax"),
    ("sunshine_duration", "sunshine"),
    ("sunrise", "sunrise"),
    ("sunset", "sunset"),
    ("weather_code", "code"),
)

#: What Open-Meteo calls the models, and what to call them on a form. Left as
#: `best_match` unless somebody has a reason: it is genuinely better than
#: picking one, and picking one is how a station in France ends up on GFS.
MODELS: tuple[tuple[str, str], ...] = (
    ("best_match", "whatever is best for this location"),
    ("icon_seamless", "DWD ICON -- Germany and central Europe"),
    ("ecmwf_ifs025", "ECMWF -- the European global model"),
    ("gfs_seamless", "NOAA GFS -- the American global model"),
    ("meteofrance_seamless", "Meteo-France ARPEGE and AROME"),
    ("ukmo_seamless", "UK Met Office"),
    ("jma_seamless", "JMA -- Japan"),
    ("gem_seamless", "MSC -- Canada"),
    ("metno_seamless", "MET Norway -- Scandinavia"),
)


class OpenMeteo(BaseSource):
    """A forecast from open-meteo.com."""

    label = "Open-Meteo"
    summary = ("A forecast for anywhere, without an account. Picks the best "
               "model for the location by itself -- the right answer for "
               "almost every station.")
    #: Their models run every one to six hours. Asking every hour is polite
    #: and still never misses a run by more than an hour.
    every = 3600

    def __init__(self, model: str = "best_match", days: int = 7,
                 past_days: int = 0, host: str = HOST, timeout: int = 20,
                 every: int = 3600) -> None:
        self.model = (model or "best_match").strip()
        self.days = max(1, min(int(days), 16))
        self.past_days = max(0, min(int(past_days), 2))
        self.host = host or HOST
        self.timeout = int(timeout)
        self.every = int(every)

    # -- the request -----------------------------------------------------

    def path(self, place: Place) -> str:
        fields = {
            "latitude": f"{place.latitude:.4f}",
            "longitude": f"{place.longitude:.4f}",
            "hourly": ",".join(name for name, _ours in HOURLY),
            "daily": ",".join(name for name, _ours in DAILY),
            # Unix time throughout, so nothing here has to guess a zone.
            "timeformat": "unixtime",
            # Still needed with unixtime: it decides where a "day" starts,
            # and a daily maximum for the wrong midnight is a wrong maximum.
            "timezone": "auto",
            "forecast_days": str(self.days),
            "models": self.model,
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
            "temperature_unit": "celsius",
        }
        if place.altitude is not None:
            # Open-Meteo corrects temperature for height. Left out, it uses
            # the terrain model's idea of the elevation, which in a valley
            # can be a couple of degrees away from the actual station.
            fields["elevation"] = f"{place.altitude:.0f}"
        if self.past_days:
            fields["past_days"] = str(self.past_days)
        query = "&".join(f"{k}={v}" for k, v in fields.items())
        return f"{PATH}?{query}"

    def fetch(self, place: Place) -> Reading:
        status, body = request(self.host, self.path(place), timeout=self.timeout)
        if status == 400:
            # Open-Meteo says what was wrong in the body, and it is almost
            # always a variable name -- which means our table, not the user.
            raise ForecastError(f"Open-Meteo refused the request: {body[:200]}",
                                permanent=True)
        if status == 429:
            raise ForecastError("Open-Meteo is rate-limiting this address; "
                                "asking less often will fix it")
        if status != 200:
            raise ForecastError(f"Open-Meteo answered {status}: {body[:120]}")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise ForecastError(f"Open-Meteo sent something that is not JSON: "
                                f"{exc}") from exc
        return self.read(data)

    # -- reading it ------------------------------------------------------

    def read(self, data: dict) -> Reading:
        """Turn one response into hours and days.

        Separate from `fetch` so a test can hand it a saved document, which
        is the only way to check this without the network.
        """
        reading = Reading(source="open-meteo")
        offset = int(data.get("utc_offset_seconds") or 0)
        # Their "issued" is not in the response, so the generation time is
        # the honest answer: this is when the numbers were produced for us.
        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        for index, when in enumerate(times):
            moment = Moment(dateTime=int(when), usUnits=units.METRICWX)
            for theirs, ours in HOURLY:
                column = hourly.get(theirs)
                if not column or index >= len(column):
                    continue
                value = column[index]
                if value is None:
                    continue
                if ours == "code":
                    moment.code = int(value)
                elif ours == "visibility":
                    # Metres from them, and `group_distance` is kilometres in
                    # METRICWX. Converting here rather than letting a page
                    # show 24000 km.
                    moment.visibility = float(value) / 1000.0
                else:
                    setattr(moment, ours, float(value))
            reading.hours.append(moment)

        daily = data.get("daily") or {}
        times = daily.get("time") or []
        for index, when in enumerate(times):
            # Their daily timestamp is local midnight expressed as UTC, so
            # the offset has to come off to get the actual instant. Without
            # this a day in Berlin starts at 02:00 and the whole column is
            # keyed to the wrong date twice a year.
            day = Day(dateTime=int(when) - offset, usUnits=units.METRICWX)
            for theirs, ours in DAILY:
                column = daily.get(theirs)
                if not column or index >= len(column):
                    continue
                value = column[index]
                if value is None:
                    continue
                if ours == "code":
                    day.code = int(value)
                elif ours in ("sunrise", "sunset"):
                    # These come back as unix time already, and unlike the
                    # day itself they are instants rather than dates -- so
                    # they are right as they are.
                    setattr(day, ours, int(value))
                else:
                    setattr(day, ours, float(value))
            reading.days.append(day)

        generated = data.get("generationtime_ms")
        if generated is not None:
            reading.note = f"{self.model}, {generated:.0f} ms"
        return reading

    def check(self, place: Place) -> str:
        try:
            got = self.fetch(place)
        except ForecastError as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"could not reach {self.host}: {exc}"
        if got.empty:
            return "answered, but with nothing in it."
        first = got.hours[0] if got.hours else None
        where = f" for {place.latitude:.3f}, {place.longitude:.3f}"
        now = ""
        if first is not None and first.outTemp is not None:
            now = f" The first hour is {first.outTemp:.1f} °C."
        return f"{got.summary()}{where}.{now}"

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("What to ask for", "", (
                Option("days", "How far ahead", kind="int", default=7,
                       minimum=1, maximum=16, unit="days",
                       help="Beyond about seven days a forecast is a "
                            "climatology with error bars, but the data is "
                            "there if a page wants to show it."),
                Option("model", "Model", kind="choice", default="best_match",
                       choices=MODELS,
                       help="Leave this alone unless there is a reason. "
                            "'Best for this location' is not a compromise: "
                            "it uses the high-resolution national model "
                            "where one exists and a global one where none "
                            "does, which is better than any single choice."),
            )),
            Group("How often", "", (
                Option("every", "Ask every", kind="duration", default=3600,
                       minimum=600, maximum=86400,
                       help="Their models run every one to six hours, so "
                            "asking more often than hourly gets the same "
                            "numbers back."),
            )),
            Group("How", "", (
                Option("host", "API host", default=HOST, advanced=True,
                       help="Change this only to point at a self-hosted "
                            "Open-Meteo, which is a thing they support."),
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True),
                Option("past_days", "Also fetch the last", kind="int",
                       default=0, minimum=0, maximum=2, unit="days",
                       advanced=True,
                       help="For a page that draws the forecast against what "
                            "actually happened."),
            )),
        ]

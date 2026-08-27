"""Weathercloud.

Metric, and every value is an integer in tenths: 21.4 °C goes as `214`. That
is the whole protocol -- a query string of scaled integers, with the date and
the time in two separate parameters, both UTC.

The one thing to get right is that a scaled integer has no way to say
"absent". A missing temperature and a temperature of 0.0 °C are `` and `0`,
and only one of them is a fact. So the same rule as everywhere else here: what
is None never reaches the query.

Weathercloud takes readings no more than once a minute and, on a free account,
prefers ten. The default trigger is still every archive record, because an
archive interval is five minutes on almost every station and that is inside
what they allow.
"""

from __future__ import annotations

import datetime
import logging

from . import BaseUpload, Posted, Readings, Rejected, query, request, when_options

log = logging.getLogger(__name__)

HOST = "api.weathercloud.net"
PATH = "/v01/set"

#: (our name, their name, unit, scale). The value goes as
#: `round(reading * scale)`.
FIELDS: tuple[tuple[str, str, str | None, int], ...] = (
    ("outTemp", "temp", "degree_C", 10),
    ("outHumidity", "hum", "percent", 1),
    ("dewpoint", "dew", "degree_C", 10),
    ("windchill", "chill", "degree_C", 10),
    ("heatindex", "heat", "degree_C", 10),
    ("windSpeed", "wspd", "meter_per_second", 10),
    ("windGust", "wspdhi", "meter_per_second", 10),
    ("windDir", "wdir", "degree_compass", 1),
    ("barometer", "bar", "mbar", 10),
    ("dayRain", "rain", "mm", 10),
    ("rainRate", "rainrate", "mm_per_hour", 10),
    ("radiation", "solarrad", "watt_per_meter_squared", 10),
    ("UV", "uvi", None, 10),
    ("ET", "et", "mm", 10),
)

INDOOR_FIELDS: tuple[tuple[str, str, str | None, int], ...] = (
    ("inTemp", "tempin", "degree_C", 10),
    ("inHumidity", "humin", "percent", 1),
)


class WeathercloudUpload(BaseUpload):
    """Posts records to Weathercloud."""

    label = "Weathercloud"
    summary = ("A map and a dashboard, popular in Europe. Metric, and every "
               "reading goes as an integer in tenths.")
    #: Weathercloud takes the reading as current: there is no timestamp in the
    #: protocol beyond the date and time it is posted at, and no way to say
    #: "this is from twenty minutes ago". So a missed record stays missed.
    backfill = False

    def __init__(self, wid: str = "", key: str = "", indoor: bool = False,
                 trigger: str = "record", every: int = 900,
                 catch_up: int = 0, timeout: int = 20) -> None:
        self.wid = str(wid or "").strip()
        self.key = str(key or "").strip()
        self.indoor = bool(indoor)
        self.trigger = trigger
        self.every = int(every)
        self.catch_up_limit = 0
        self.timeout = int(timeout)
        if not self.wid or not self.key:
            raise ValueError("a Weathercloud ID and a key are both needed")

    def _query(self, record: dict) -> str:
        readings = Readings(record)
        when = datetime.datetime.fromtimestamp(readings.ts, datetime.UTC)
        values: dict[str, object] = {
            "wid": self.wid,
            "key": self.key,
            # 251 is the number Weathercloud gave WeeWX. Ours is a different
            # program posting the same protocol, and inventing a number they
            # have not assigned would be worse than being honest about the
            # family it belongs to.
            "type": "251",
            "ver": "weewx-evo",
            "date": when.strftime("%Y%m%d"),
            "time": when.strftime("%H:%M"),
        }
        fields = FIELDS + (INDOOR_FIELDS if self.indoor else ())
        for obs, name, unit, scale in fields:
            value = readings.get(obs, unit)
            if value is not None:
                values[name] = str(round(value * scale))
        return query(PATH, values)

    def _send(self, record: dict) -> None:
        status, body = request(HOST, self._query(record), timeout=self.timeout)
        text = body.strip().lower()
        # Weathercloud answers in words, on HTTP 200 whatever happened.
        if text in ("400", "401", "invalid") or "wrong" in text:
            raise Rejected(f"Weathercloud rejected the ID or key: {body[:120]}",
                           permanent=True)
        if status != 200:
            raise Rejected(f"Weathercloud answered {status}: {body[:120]}")
        if text and text != "200" and "ok" not in text:
            raise Rejected(f"Weathercloud answered {body[:120]!r}")

    def post(self, records: list[dict]) -> Posted:
        result = Posted()
        # Only the newest: this service has no timestamp, so an older record
        # would be published as the current conditions.
        record = records[-1]
        result.skipped = len(records) - 1
        try:
            self._send(record)
        except Rejected as exc:
            if exc.permanent:
                raise
            result.failures.append((str(record.get("dateTime")), str(exc)))
            return result
        result.sent = 1
        result.through = int(record.get("dateTime") or 0)
        return result

    def check(self) -> str:
        import time
        try:
            self._send({"dateTime": int(time.time()), "usUnits": 16})
        except Rejected as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"could not reach {HOST}: {exc}"
        return f"Weathercloud accepted the ID {self.wid!r}."

    def status(self) -> dict:
        return {"host": HOST, "wid": self.wid}

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("The account", "", (
                Option("wid", "Weathercloud ID", required=True,
                       help="The device ID from the Weathercloud device "
                            "settings. Twelve hexadecimal characters."),
                Option("key", "Key", kind="secret", required=True,
                       help="The device key, beside the ID on the same page."),
            )),
            Group("What is sent", "", (
                Option("indoor", "Include indoor temperature and humidity",
                       kind="bool", default=False),
            )),
            *when_options(),
            Group("How", "", (
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True),
            )),
        ]

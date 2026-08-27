"""Windy.com.

The one service in this package that is not the Ambient protocol: JSON in the
body of a POST, metric units, and the API key in the path rather than a
parameter. Windy is what people sailing and flying look at, which is why a
station gets asked for it.

Two things worth knowing:

**Pressure is in pascals.** Not hectopascals, which is what every other
service and every barometer uses. `101325`, not `1013.25`. Sending the
hectopascal figure gets it accepted and drawn as a vacuum.

**The key is in the URL.** So it lands in any proxy log between here and
Windy, and in ours if a request is ever logged whole. Nothing logs the path
here, and `status()` does not return it.
"""

from __future__ import annotations

import datetime
import json
import logging

from . import BaseUpload, Posted, Readings, Rejected, request, when_options

log = logging.getLogger(__name__)

HOST = "stations.windy.com"

#: (our name, Windy's name, unit, decimals). Metric throughout, and pressure
#: in pascals -- see the module docstring.
FIELDS: tuple[tuple[str, str, str | None, int], ...] = (
    ("outTemp", "temp", "degree_C", 1),
    ("dewpoint", "dewpoint", "degree_C", 1),
    ("outHumidity", "rh", "percent", 0),
    ("windSpeed", "wind", "meter_per_second", 1),
    ("windDir", "winddir", "degree_compass", 0),
    ("windGust", "gust", "meter_per_second", 1),
    # Pressure is handled separately: Windy wants pascals and `units.py` has
    # no such unit, because no barometer and no other service uses it.
    ("barometer", "pressure", "mbar", 2),
    ("hourRain", "precip", "mm", 2),
    ("UV", "uv", None, 1),
)


class WindyUpload(BaseUpload):
    """Posts records to Windy."""

    label = "Windy"
    summary = ("What people sailing and flying look at. Metric, JSON, and "
               "the one service here that is not the Ambient protocol.")

    def __init__(self, api_key: str = "", station: int = 0,
                 trigger: str = "record", every: int = 900,
                 catch_up: int = 12, timeout: int = 20) -> None:
        self.api_key = str(api_key or "").strip()
        # Windy allows several stations under one key, numbered from zero.
        # Almost everybody has one and leaves this alone.
        self.station = int(station or 0)
        self.trigger = trigger
        self.every = int(every)
        self.catch_up_limit = int(catch_up)
        self.timeout = int(timeout)
        if not self.api_key:
            raise ValueError("an API key is needed")

    def _observation(self, record: dict) -> dict:
        readings = Readings(record)
        when = datetime.datetime.fromtimestamp(readings.ts, datetime.UTC)
        observation: dict[str, object] = {
            "station": self.station,
            "dateutc": when.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for obs, name, unit, places in FIELDS:
            value = readings.get(obs, unit)
            if value is None:
                continue
            if name == "pressure":
                # Millibars are hectopascals; Windy wants pascals. 1013.25
                # sent as-is is accepted and drawn as a vacuum.
                value *= 100.0
                places = 0
            observation[name] = round(value, places)
        return observation

    def _send(self, records: list[dict]) -> int:
        """Post a batch and return how many went. Raises `Rejected`.

        Windy takes several observations in one request, so a catch-up is one
        request rather than twelve. That is its own argument for doing it:
        twelve requests to a free service in one second is what a rate limiter
        is for.
        """
        body = json.dumps({"observations": [self._observation(r) for r in records]})
        status, text = request(
            HOST, f"/pws/update/{self.api_key}", method="POST",
            body=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=self.timeout)
        if status in (401, 403):
            raise Rejected(f"Windy rejected the API key: {text[:120]}",
                           permanent=True)
        if status != 200:
            raise Rejected(f"Windy answered {status}: {text[:120]}")
        return len(records)

    def post(self, records: list[dict]) -> Posted:
        result = Posted()
        try:
            result.sent = self._send(records)
            result.through = int(records[-1].get("dateTime") or 0)
        except Rejected as exc:
            if exc.permanent:
                raise
            result.failures.append((str(records[-1].get("dateTime")), str(exc)))
        return result

    def check(self) -> str:
        import time
        try:
            self._send([{"dateTime": int(time.time()), "usUnits": 16}])
        except Rejected as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"could not reach {HOST}: {exc}"
        return "Windy accepted the API key."

    def status(self) -> dict:
        # No key here. It is in the URL, which is bad enough already.
        return {"host": HOST, "station": self.station}

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("The account", "", (
                Option("api_key", "API key", kind="secret", required=True,
                       help="From the Windy station settings page. Windy puts "
                            "this in the address of every request, so treat "
                            "it as public knowledge at the far end."),
                Option("station", "Station number", kind="int", default=0,
                       minimum=0, maximum=99, advanced=True,
                       help="Windy allows several stations under one key, "
                            "numbered from zero. Leave it at zero unless you "
                            "have more than one."),
            )),
            *when_options(),
            Group("How", "", (
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True),
            )),
        ]

"""The Ambient protocol: Weather Underground, PWSweather, WOW.

Weather Underground defined this and the others copied it, down to the
parameter names. So it is one module with three hosts rather than three
near-identical files -- which is also how a fix to the timestamp format
reaches all three instead of two.

The formats are transcribed from `weewx.restx.AmbientThread`, field by field,
including the decimal places. That is not deference: a station that has been
posting `windspeedmph=003.1` for eight years and starts posting `3.1` is
posting the same number, but a rainfall total that arrives with two decimals
instead of three is a different number, and finding out which of the two
services rounds it costs an afternoon.

Three things that are decisions rather than transcription:

**US units, always, whatever the archive holds.** The protocol is defined in
Fahrenheit and inches, and there is no parameter to say otherwise. A console
in Germany reporting Celsius is the ordinary case here, so the conversion
happens on the way out -- `units.py`, the same table everything else uses.

**An absent reading is absent, never zero.** A station with no rain gauge that
posts `rainin=0.00` every five minutes is indistinguishable from one in a
drought, and Weather Underground keeps it forever. `query()` drops what is
None, which is why every reading comes back as None rather than a default.

**A bad password is said once.** These services answer a wrong password with
a cheerful HTTP 200 and the word `INVALIDPASSWORDID` in the body, so the
status code decides nothing and the body has to be read. Getting it wrong
means retrying a wrong password every five minutes for a year.
"""

from __future__ import annotations

import datetime
import logging

from . import BaseUpload, Posted, Readings, Rejected, query, request, when_options

log = logging.getLogger(__name__)

#: Every reading the Ambient protocol takes, as (our name, their name, unit,
#: format). Transcribed from `weewx.restx.AmbientThread._FORMATS`, including
#: the widths: `humidity=061` and `windspeedmph=003.1` are what the protocol
#: defines, and the zero-padding is not decoration.
FIELDS: tuple[tuple[str, str, str | None, str], ...] = (
    ("outTemp", "tempf", "degree_F", ".1f"),
    ("outHumidity", "humidity", "percent", "03.0f"),
    ("dewpoint", "dewptf", "degree_F", ".1f"),
    ("barometer", "baromin", "inHg", ".3f"),
    ("windSpeed", "windspeedmph", "mile_per_hour", "03.1f"),
    ("windDir", "winddir", "degree_compass", "03.0f"),
    ("windGust", "windgustmph", "mile_per_hour", "03.1f"),
    # Not in WeeWX's table, though the protocol defines it. A gust with no
    # direction is half a reading, and the field costs nothing.
    ("windGustDir", "windgustdir", "degree_compass", "03.0f"),
    ("hourRain", "rainin", "inch", ".2f"),
    ("dayRain", "dailyrainin", "inch", ".2f"),
    ("radiation", "solarradiation", "watt_per_meter_squared", ".2f"),
    ("UV", "UV", None, ".2f"),
    ("soilTemp1", "soiltempf", "degree_F", ".1f"),
    ("soilTemp2", "soiltemp2f", "degree_F", ".1f"),
    ("soilTemp3", "soiltemp3f", "degree_F", ".1f"),
    ("soilTemp4", "soiltemp4f", "degree_F", ".1f"),
    # Soil moisture is centibars in both unit systems, so there is nothing to
    # convert -- and asking for a conversion to `percent` would silently do
    # nothing while reading as though it did something.
    ("soilMoist1", "soilmoisture", None, "03.0f"),
    ("soilMoist2", "soilmoisture2", None, "03.0f"),
    ("soilMoist3", "soilmoisture3", None, "03.0f"),
    ("soilMoist4", "soilmoisture4", None, "03.0f"),
    ("leafWet1", "leafwetness", None, "03.0f"),
    ("leafWet2", "leafwetness2", None, "03.0f"),
    ("pm2_5", "AqPM2.5", "microgram_per_meter_cubed", ".1f"),
    ("pm10_0", "AqPM10", "microgram_per_meter_cubed", ".1f"),
)

#: Inside the house. Off by default and a setting, because publishing the
#: temperature of somebody's living room to a public map is their decision to
#: make and not ours to make for them.
INDOOR_FIELDS: tuple[tuple[str, str, str | None, str], ...] = (
    ("inTemp", "indoortempf", "degree_F", ".1f"),
    ("inHumidity", "indoorhumidity", "percent", ".0f"),
)

#: What these services say when the credentials are wrong. Checked in the
#: body, because the status code is 200 for all of them.
BAD_LOGIN = ("invalidpasswordid", "badauth", "error: not authorized",
             "unable to validate", "invalid")


def _stamp(ts: int) -> str:
    """The timestamp, in UTC, in the shape the protocol wants.

    `2020-10-19 21:43:18`. Not ISO 8601, not with a `T`, not with a zone: the
    protocol says UTC and reading the field as local time is a station whose
    readings arrive an hour early twice a year.
    """
    when = datetime.datetime.fromtimestamp(ts, datetime.UTC)
    return when.strftime("%Y-%m-%d %H:%M:%S")


class AmbientUpload(BaseUpload):
    """Posts records using the Ambient protocol."""

    label = "Ambient"
    #: Overridden by each service.
    host = ""
    path = ""
    #: What the two credentials are called in the query string. WOW renamed
    #: both and changed nothing else, so this is all it takes.
    id_field = "ID"
    key_field = "PASSWORD"
    #: WOW answers a bad login with HTTP 403 rather than a word in the body.
    bad_login_status: tuple[int, ...] = ()
    fields: tuple[tuple[str, str, str | None, str], ...] = FIELDS

    def __init__(self, station: str = "", password: str = "",
                 indoor: bool = False, trigger: str = "record",
                 every: int = 900, catch_up: int = 12,
                 timeout: int = 20, host: str = "") -> None:
        self.station = str(station or "").strip()
        self.password = str(password or "")
        self.indoor = bool(indoor)
        self.trigger = trigger
        self.every = int(every)
        self.catch_up_limit = int(catch_up)
        self.timeout = int(timeout)
        if host:
            self.host = host
        if not self.station or not self.password:
            raise ValueError("a station id and a password are both needed")

    # -- the request -----------------------------------------------------

    def _fields(self) -> tuple[tuple[str, str, str | None, str], ...]:
        return self.fields + (INDOOR_FIELDS if self.indoor else ())

    def _query(self, record: dict) -> str:
        readings = Readings(record)
        values: dict[str, object] = {
            "action": "updateraw",
            self.id_field: self.station,
            self.key_field: self.password,
            "dateutc": _stamp(readings.ts),
            "softwaretype": "weewx-evo",
        }
        for obs, name, unit, spec in self._fields():
            values[name] = readings.text(obs, unit, spec)
        return query(self.path, values)

    def _send(self, record: dict) -> None:
        """One record. Raises `Rejected` with whether it is worth retrying."""
        status, body = request(self.host, self._query(record),
                               timeout=self.timeout)
        lowered = body.lower()
        if status in self.bad_login_status or any(w in lowered for w in BAD_LOGIN):
            raise Rejected(
                f"{self.label} rejected the credentials for station "
                f"{self.station!r}: {body or status}", permanent=True)
        if status != 200:
            raise Rejected(f"{self.label} answered {status}: {body[:120]}")
        if "success" not in lowered and body:
            # Not an error on its own -- several of these answer with an empty
            # body on success -- but worth carrying into the summary so that
            # "it says it worked" can be checked rather than assumed.
            log.debug("%s answered %r", self.label, body[:120])

    # -- the interface ---------------------------------------------------

    def post(self, records: list[dict]) -> Posted:
        result = Posted()
        for record in records:
            try:
                self._send(record)
            except Rejected as exc:
                if exc.permanent:
                    # Nothing after this one will work either, and the runner
                    # needs to hear about it rather than see a failure count.
                    raise
                result.failures.append((str(record.get("dateTime")), str(exc)))
                # Stop at the first refusal. The rest are almost certainly the
                # same problem, and firing eleven more requests at a service
                # that is having a bad afternoon is how a station gets
                # rate-limited.
                break
            result.sent += 1
            result.through = int(record.get("dateTime") or 0)
        return result

    def check(self) -> str:
        """Post nothing and see whether the credentials are accepted.

        These services have no endpoint for this, so it posts a record with a
        timestamp and no readings. That is accepted as an empty update and
        records nothing, which is what makes it safe to run from a button.
        """
        import time
        try:
            self._send({"dateTime": int(time.time()), "usUnits": 1})
        except Rejected as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"could not reach {self.host}: {exc}"
        return f"{self.host} accepted the credentials for {self.station!r}."

    def status(self) -> dict:
        return {"host": self.host, "station": self.station}

    # -- settings --------------------------------------------------------

    @staticmethod
    def _credential_options(id_label: str, key_label: str, id_help: str = "",
                            key_help: str = "") -> list:
        from ..options import Group, Option

        return [
            Group("The account", "", (
                Option("station", id_label, required=True, help=id_help),
                Option("password", key_label, kind="secret", required=True,
                       help=key_help),
            )),
            Group("What is sent", "", (
                Option("indoor", "Include indoor temperature and humidity",
                       kind="bool", default=False,
                       help="Off. What it is like inside somebody's house is "
                            "not weather, and once it is on a public map it "
                            "stays there."),
            )),
            *when_options(),
            Group("How", "", (
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True,
                       help="A service that has stopped answering must not "
                            "hold up the next interval."),
            )),
        ]


class WundergroundUpload(AmbientUpload):
    """Weather Underground."""

    label = "Weather Underground"
    summary = ("The largest network of personal weather stations. Free, and "
               "what most people mean by publishing their readings.")
    host = "weatherstation.wunderground.com"
    path = "/weatherstation/updateweatherstation.php"

    @staticmethod
    def options() -> list:
        return AmbientUpload._credential_options(
            "Station ID", "Station key",
            id_help="The ID Weather Underground gave the station, like "
                    "IBAYERN123. Not the account's email address.",
            key_help="The station key from the Weather Underground member "
                     "settings -- not the password used to log in.")


class PwsWeatherUpload(AmbientUpload):
    """PWSweather, from AerisWeather."""

    label = "PWSweather"
    summary = ("A second network, same protocol. Costs nothing and takes the "
               "readings a station is already sending elsewhere.")
    host = "www.pwsweather.com"
    path = "/pwsupdate/pwsupdate.php"

    @staticmethod
    def options() -> list:
        return AmbientUpload._credential_options(
            "Station ID", "Password",
            id_help="The station ID registered at pwsweather.com.",
            key_help="The account password.")


class WowUpload(AmbientUpload):
    """The Met Office's Weather Observations Website.

    The same protocol with both credentials renamed and a bad login answered
    with a 403 instead of a word in the body.
    """

    label = "Met Office WOW"
    summary = ("The UK Met Office's observations site. Takes stations from "
               "anywhere, not only the UK.")
    host = "wow.metoffice.gov.uk"
    path = "/automaticreading"
    id_field = "siteid"
    key_field = "siteAuthenticationKey"
    bad_login_status = (403,)
    #: WOW's shorter list. It ignores what it does not know, but sending a
    #: field a service never reads is a line in somebody's traffic bill and a
    #: field in a log, so it goes by their list rather than ours.
    fields = (
        ("outTemp", "tempf", "degree_F", ".1f"),
        ("outHumidity", "humidity", "percent", ".0f"),
        ("dewpoint", "dewptf", "degree_F", ".1f"),
        ("barometer", "baromin", "inHg", ".3f"),
        ("windSpeed", "windspeedmph", "mile_per_hour", ".0f"),
        ("windDir", "winddir", "degree_compass", ".0f"),
        ("windGust", "windgustmph", "mile_per_hour", ".0f"),
        ("windGustDir", "windgustdir", "degree_compass", ".0f"),
        ("hourRain", "rainin", "inch", ".2f"),
        ("dayRain", "dailyrainin", "inch", ".3f"),
    )

    @staticmethod
    def options() -> list:
        return AmbientUpload._credential_options(
            "Site ID", "Authentication key",
            id_help="The site ID from the WOW site settings. A long number.",
            key_help="The six-digit PIN WOW calls the authentication key.")

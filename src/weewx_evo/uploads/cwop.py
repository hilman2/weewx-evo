"""CWOP: the Citizen Weather Observer Program, over APRS-IS.

Not HTTP. A TCP socket, a login line, and one line of ASCII in the TNC2 packet
format that amateur radio has used since the 1990s -- which is why it looks
the way it does:

    DW1234>APZEVO,TCPIP*:/271830z4823.15N/01142.30E_045/003g007t054r000p000P000b10132h72

Every field is fixed-width, every absent field is dots of the same width, and
the whole thing is positional. Getting a width wrong does not produce an
error: it produces a reading in the wrong place, silently, forever.

So the packet builder here is transcribed from `weewx.restx.CWOPThread`
character for character, including `h00` meaning 100 % humidity and the two
different letters for solar radiation above and below 1000 W/m². Those are not
quirks to tidy up; they are the protocol.

Where the readings go is what makes CWOP worth having: NOAA's MADIS ingests it,
so a back garden station ends up in the same feed as the airports. That also
means the position has to be right -- it is what the reading is attributed to,
and there is no correcting it afterwards.

Two decisions:

**Ten minutes, not five.** CWOP asks for one report every five to ten minutes
and means it. The default here is ten, on its own schedule rather than on the
archive record, because an archive interval of one minute would otherwise post
sixty times an hour to a service that asked for six.

**No backfill.** An APRS position report is where a station is and what it
reads *now*. Posting a twenty-minute-old reading into that feed is not a
late reading, it is a wrong one.
"""

from __future__ import annotations

import logging
import math
import socket
import time

from . import BaseUpload, Posted, Readings, Rejected, when_options

log = logging.getLogger(__name__)

#: APRS-IS entry points. Two, because port 14580 is the filtered feed that
#: sometimes refuses and 23 is the plain one that almost never does.
DEFAULT_SERVERS = ("cwop.aprs.net:14580", "cwop.aprs.net:23")

#: The APRS software identifier in the packet's path. `APWEE5` is assigned to
#: WeeWX and is not ours to send. `APZ...` is the range the APRS specification
#: reserves for software with no registered identifier, which is what this is
#: until somebody registers one.
DESTINATION = "APZEVO"


def latlon(value: float, hemispheres: tuple[str, str], which: str) -> str:
    """Decimal degrees as APRS writes them: `4823.15N`, `01142.30E`.

    Degrees and decimal minutes, zero-padded to two digits for latitude and
    three for longitude. Transcribed from `weeutil.weeutil.latlon_string`.
    """
    magnitude = abs(value)
    fraction, degrees = math.modf(magnitude)
    minutes = fraction * 60.0
    whole = f"{int(degrees):02d}" if which == "lat" else f"{int(degrees):03d}"
    hemisphere = hemispheres[0] if value >= 0 else hemispheres[1]
    return f"{whole}{minutes:05.2f}{hemisphere}"


class CwopUpload(BaseUpload):
    """Posts records to APRS-IS for CWOP."""

    label = "CWOP"
    summary = ("The Citizen Weather Observer Program. Feeds NOAA's MADIS, "
               "so the readings reach the same place the airports do.")
    #: An APRS position report means "now". See the module docstring.
    backfill = False

    def __init__(self, station: str = "", passcode: str = "-1",
                 latitude: float | None = None, longitude: float | None = None,
                 servers: object = DEFAULT_SERVERS, trigger: str = "interval",
                 every: int = 600, catch_up: int = 0,
                 timeout: int = 20) -> None:
        self.station = str(station or "").strip().upper()
        # `-1` is what an unlicensed station sends, and it is what almost
        # every weather station is. A DW/EW callsign needs no real passcode.
        self.passcode = str(passcode or "-1").strip()
        self.latitude = latitude
        self.longitude = longitude
        self.servers = self._servers(servers)
        self.trigger = trigger
        self.every = int(every)
        self.catch_up_limit = 0
        self.timeout = int(timeout)
        if not self.station:
            raise ValueError("a CWOP station id is needed, such as DW1234")
        if self.latitude is None or self.longitude is None:
            raise ValueError(
                "CWOP needs the station's latitude and longitude: the packet "
                "is a position report, and the reading is attributed to it")

    @staticmethod
    def _servers(value: object) -> list[tuple[str, int]]:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        found = []
        for entry in value or DEFAULT_SERVERS:
            host, _, port = str(entry).partition(":")
            try:
                found.append((host.strip(), int(port or 14580)))
            except ValueError:
                log.warning("ignoring the CWOP server %r: %r is not a port",
                            entry, port)
        if not found:
            raise ValueError("no usable CWOP server address")
        return found

    # -- the packet ------------------------------------------------------

    def login(self) -> str:
        return f"user {self.station} pass {self.passcode} vers weewx-evo 1\r\n"

    def packet(self, record: dict) -> str:
        """The TNC2 packet. Fixed width throughout -- see the module docstring.

        Everything is US customary except the barometer, which CWOP wants in
        tenths of a millibar. That is the protocol's own inconsistency and it
        is load-bearing: sending inches of mercury there reads as 3000 mbar.
        """
        readings = Readings(record)
        prefix = f"{self.station}>{DESTINATION},TCPIP*:"
        # `/` is a position report with a timestamp and *without* APRS
        # messaging. An unattended station cannot answer a message, so it must
        # not advertise that it can by using `@`.
        when = time.strftime("/%d%H%Mz", time.gmtime(readings.ts))
        position = (latlon(float(self.latitude), ("N", "S"), "lat") + "/"
                    + latlon(float(self.longitude), ("E", "W"), "lon"))

        wind = []
        for obs, unit in (("windDir", "degree_compass"),
                          ("windSpeed", "mile_per_hour"),
                          ("windGust", "mile_per_hour")):
            value = readings.get(obs, unit)
            wind.append("..." if value is None else f"{int(value + 0.5):03d}")
        weather = f"_{wind[0]}/{wind[1]}g{wind[2]}t{_temperature(readings)}"

        rain = []
        for obs in ("hourRain", "rain24", "dayRain"):
            value = readings.get(obs, "inch")
            rain.append("..." if value is None
                        else f"{int(value * 100.0 + 0.5):03d}")
        weather += f"r{rain[0]}p{rain[1]}P{rain[2]}"

        # The barometer in tenths of a millibar, from the altimeter -- which
        # is the pressure reduced to sea level the way aviation does it, and
        # what CWOP means by `b`.
        altimeter = readings.get("altimeter", "mbar")
        if altimeter is None:
            altimeter = readings.get("barometer", "mbar")
        weather += ("b....." if altimeter is None
                    else f"b{int(altimeter * 10.0 + 0.5):05d}")

        humidity = readings.get("outHumidity", "percent")
        if humidity is None:
            weather += "h.."
        else:
            # `h00` is how APRS writes 100 %. Two digits, no room for three.
            weather += f"h{int(humidity + 0.5):02d}" if humidity < 99.5 else "h00"

        radiation = readings.get("radiation", "watt_per_meter_squared")
        if radiation is not None and radiation < 999.5:
            weather += f"L{int(radiation + 0.5):03d}"
        elif radiation is not None and radiation < 1999.5:
            # Over 1000, the letter changes and the thousand is dropped. Not
            # a typo: `l` is lowercase L and means "add 1000".
            weather += f"l{int(radiation - 1000 + 0.5):03d}"

        return f"{prefix}{when}{position}{weather}.weewx-evo\r\n"

    # -- sending ---------------------------------------------------------

    def _send(self, record: dict) -> str:
        packet = self.packet(record)
        last = ""
        for host, port in self.servers:
            try:
                with socket.create_connection((host, port), timeout=self.timeout) as sock:
                    sock.sendall(self.login().encode("ascii"))
                    # APRS-IS answers the login with a banner. Read it before
                    # sending: a server that refused the callsign says so
                    # here, and pushing the packet at it anyway gets it
                    # silently dropped.
                    banner = sock.recv(1024).decode("ascii", "replace")
                    if "unverified" in banner.lower() and self.passcode != "-1":
                        log.info("CWOP: %s took the login but did not verify "
                                 "the passcode; readings still go through",
                                 host)
                    sock.sendall(packet.encode("ascii"))
                    return f"{host}:{port}"
            except OSError as exc:
                last = f"{host}:{port}: {exc}"
                log.debug("CWOP: %s", last)
        raise Rejected(f"no CWOP server answered ({last})")

    def post(self, records: list[dict]) -> Posted:
        result = Posted()
        record = records[-1]
        result.skipped = len(records) - 1
        try:
            result.note = self._send(record)
        except Rejected as exc:
            result.failures.append((str(record.get("dateTime")), str(exc)))
            return result
        result.sent = 1
        result.through = int(record.get("dateTime") or 0)
        return result

    def check(self) -> str:
        """Connect and log in, without sending a packet.

        APRS-IS has no way to validate a reading, so this tests the half that
        can be tested: that a server answers and takes the callsign.
        """
        for host, port in self.servers:
            try:
                with socket.create_connection((host, port), timeout=self.timeout) as sock:
                    sock.sendall(self.login().encode("ascii"))
                    banner = sock.recv(1024).decode("ascii", "replace").strip()
                return (f"{host}:{port} answered: {banner[:120]}\n"
                        f"  packet: {self.packet(_example()).strip()}")
            except OSError as exc:
                log.debug("CWOP check: %s:%s: %s", host, port, exc)
        return "no CWOP server answered."

    def status(self) -> dict:
        return {"station": self.station,
                "servers": [f"{h}:{p}" for h, p in self.servers]}

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("The station", "", (
                Option("station", "CWOP or ham callsign", required=True,
                       placeholder="DW1234",
                       help="The ID from the CWOP registration, such as "
                            "DW1234 or EW1234. A licensed operator uses their "
                            "own callsign here instead."),
                Option("passcode", "Passcode", kind="secret", default="-1",
                       help="-1 for a DW or EW station, which is almost "
                            "everybody. Only a licensed amateur callsign has "
                            "a real passcode."),
            )),
            Group("Where it is",
                  "The packet is a position report, and the reading is "
                  "attributed to this point. Left empty, the station's own "
                  "latitude and longitude are used.", (
                      Option("latitude", "Latitude", kind="float",
                             minimum=-90, maximum=90),
                      Option("longitude", "Longitude", kind="float",
                             minimum=-180, maximum=180),
                  )),
            *when_options(trigger="interval", every=600, catch_up=0),
            Group("How", "", (
                Option("servers", "APRS-IS servers", kind="list",
                       default=list(DEFAULT_SERVERS), advanced=True,
                       help="Tried in order until one answers. Port 14580 is "
                            "the filtered feed and 23 is the plain one."),
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True),
            )),
        ]


def _temperature(readings: Readings) -> str:
    """Temperature in the three characters APRS allows.

    Below zero Fahrenheit the sign takes one of them, so it is `-05` and not
    `-005`. Above 999 there is nothing to be done and the field goes empty --
    which cannot happen on Earth, but a sensor reporting nonsense should
    produce dots rather than a packet that parses as something else.
    """
    value = readings.get("outTemp", "degree_F")
    if value is None:
        return "..."
    whole = int(value + 0.5) if value >= 0 else int(value - 0.5)
    if whole < 0:
        return f"-{min(99, abs(whole)):02d}"
    return f"{whole:03d}" if whole <= 999 else "..."


def _example() -> dict:
    """A record with nothing in it, for showing the packet shape in `check`."""
    return {"dateTime": int(time.time()), "usUnits": 1}

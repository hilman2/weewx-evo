"""The Weather Underground upload protocol, received rather than sent.

Weather Underground defined how a personal weather station posts a reading in
2010, and the industry copied it verbatim. Ambient Weather, Acurite, La Crosse
gateways, Froggit, Sainlogic, a long tail of rebadged consoles -- almost
anything with a "Custom Server" field speaks this, because speaking it is how
it got onto wunderground.com in the first place.

    GET /weatherstation/updateweatherstation.php?ID=x&PASSWORD=y&tempf=68.4&...

That is the whole protocol: a query string of readings, and `success` back.
There is no version, no handshake and no content type. Which is exactly why it
is still the widest door into a weather station in 2026, long after the USB
consoles this project cannot buy any more stopped being sold.

**The path is fixed and the token cannot live in it.** Ecowitt consoles let
you set the path, so `/<token>/ecowitt/` works there. Most WU-protocol
consoles do not: host and port are the only fields, and the path is burned in.
So the token is read from `PASSWORD` instead, which is a field every one of
them has, was always meant to be a shared secret, and is exactly where the
operator expects to type one. `ID` is accepted too, for the handful that
validate the password field's shape.

**Everything arrives in US units.** The protocol is Fahrenheit, inches and
miles per hour with no way to say otherwise, so the packet is tagged
`usUnits = US` and converted on the way out like anything else. A console in
Germany set to Celsius converts to Fahrenheit before it posts -- that is the
console's job and it does it, because wunderground.com would be wrong
otherwise.

**What it will not do is guess.** A field this driver does not know is
counted, named once, and left out of the packet rather than dropped into a
column that looked close. `weewx-evo columns` then reports it, which is the
same route every other unplaceable reading takes.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import parse_qsl

from ....db.live import Packet
from ....units import US
from ...drivers import BaseDriver
from .fields import FIELDS, GROUPS, IGNORED, MISSING

log = logging.getLogger(__name__)

DRIVER_NAME = "wunderground"

#: What these stations want to hear. Weather Underground answers `success` and
#: the clones check for it; several stop uploading for an hour on anything
#: else, which looks like the console broke rather than like a wrong reply.
WU_RESPONSE = (b"success\n", "text/plain")

#: How long a name we have never seen is remembered before being reported
#: again. Once per name per run, not once per upload: a console posts every
#: sixteen seconds and the same warning 5000 times a day is how a log stops
#: being read.
_REPORT_ONCE = True


class WundergroundDriver(BaseDriver):
    """Readings out of a Weather Underground query string."""

    response = WU_RESPONSE

    def __init__(self, station_id: str | None = None,
                 indoor: bool = True) -> None:
        #: Which station to accept, when more than one posts here. Empty means
        #: all of them, which is right while there is one.
        self.station_id = (station_id or "").strip()
        self.indoor = indoor
        self.seen: dict[str, int] = {}
        self.unknown: dict[str, str] = {}
        self.received = 0
        self.refused = 0

    @property
    def hardware_name(self) -> str:
        return "Weather Underground protocol"

    @staticmethod
    def options() -> list:
        """What this driver can be configured with.

        Groups, not bare options: the admin page, the command line and the
        comments in the written file are all built from this, and every one of
        them expects the settings to arrive under a prefix.
        """
        from ....options import Group, Option

        return [
            Group("Station", "Which console this driver answers to.", (
                Option("station_id", "Station ID",
                       help="The ID the console sends. Only uploads carrying "
                            "it are taken. Empty accepts whatever arrives, "
                            "which is right while one station posts here -- "
                            "and each station is recorded under its own ID "
                            "either way."),
                Option("indoor", "Record indoor readings", kind="bool",
                       default=True,
                       help="Consoles report the temperature and humidity of "
                            "the room they stand in. Off leaves them out."),
            ), prefix="drivers.wunderground"),
        ]

    def claims(self, body: bytes, meta: dict) -> float:
        """Whether this looks like a Weather Underground upload.

        Cheap on purpose: this runs for every upload whose path named no
        driver. A marker is looked for in the raw bytes rather than parsing
        the payload to find out whether it is worth parsing.

        `action=updateraw` is the strong one -- it is in the protocol, every
        station sends it, and nothing else here uses the word. `ID` with
        `PASSWORD` is weaker: it is how the protocol authenticates, but an
        Ecowitt console carrying its own `PASSKEY` is more certainly Ecowitt
        than this is WU, so it answers below that.
        """
        if b"PASSKEY=" in body:
            # Not ours, and saying so is cheaper than the two checks below.
            return 0.0
        if b"action=updateraw" in body:
            return 0.9
        if b"ID=" in body and b"PASSWORD=" in body:
            return 0.5
        return 0.0

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        """One upload, whether it arrived as a query string or a form body.

        The listener hands over `parsed.query` for a GET and the body for a
        POST; both are the same urlencoded bytes, so both land here.
        """
        text = body.decode("utf-8", errors="replace")
        data = dict(parse_qsl(text, keep_blank_values=True))
        if not data:
            return []

        who = (data.get("ID") or "").strip()
        if self.station_id and who != self.station_id:
            self.refused += 1
            log.warning("upload from station %r; this driver is set to %r",
                        who, self.station_id)
            return []

        readings = self._readings(data)
        if not readings:
            # A console checking that the server is there posts the
            # housekeeping fields and nothing else. Not an error.
            return []

        self.received += 1
        self.seen[who or "?"] = int(time.time())
        return [Packet(
            dateTime=self._when(data.get("dateutc"), meta),
            usUnits=US,
            data=readings,
            source=(who or "wunderground")[:64],
            kind="loop",
        )]

    def _readings(self, data: dict[str, str]) -> dict[str, float]:
        """The measurements, under our names, with the non-answers removed."""
        out: dict[str, float] = {}
        for name, raw in data.items():
            if name in IGNORED:
                continue
            ours = FIELDS.get(name)
            if ours is None:
                self._unknown(name, raw)
                continue
            if not self.indoor and ours in ("inTemp", "inHumidity"):
                continue
            value = self._number(raw)
            if value is not None:
                out[ours] = value
        return out

    @staticmethod
    def _number(raw: str) -> float | None:
        """A reading, or None for the several ways of saying there isn't one.

        `-9999` is what these stations send for a sensor that did not report,
        and it is the one that matters: taken at face value it is a
        temperature two hundred degrees below anything, which passes every
        range check that only looks for nulls and ruins a daily minimum for
        good.
        """
        raw = raw.strip()
        if not raw or raw.lower() in ("na", "n/a", "null", "none", "--"):
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        if value in MISSING:
            return None
        return value

    def _when(self, stamp: str | None, meta: dict) -> int:
        """The reading's own time, or ours.

        `dateutc=now` is in the spec and means "use your clock". A real stamp
        is UTC in a fixed format, and it is preferred over arrival time
        because a console that queued an upload through a network outage is
        reporting when it measured, not when it got through.
        """
        received = int(meta.get("received") or time.time())
        if not stamp or stamp.strip().lower() == "now":
            return received
        text = stamp.strip().replace("%20", " ")
        for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                      "%Y-%m-%d %H:%M"):
            try:
                # The protocol says UTC, so it is parsed as UTC. Reading it as
                # local time is a two-hour error that only shows up as a chart
                # that leads or trails the rest of the day.
                return int(_utc(text, shape))
            except ValueError:
                continue
        log.debug("could not read dateutc=%r; using arrival time", stamp)
        return received

    def _unknown(self, name: str, raw: str) -> None:
        """Name it once, then stop.

        Reported rather than guessed at. A field whose name looks like one we
        know is the tempting case and the wrong one: a reading put in the
        wrong column cannot be separated out afterwards.
        """
        if name in self.unknown:
            return
        self.unknown[name] = raw
        log.info("wunderground: no column for %s=%s. If that is a reading, "
                 "say so at https://github.com/hilman2/weewx-evo/issues",
                 name, raw)

    def redact(self, raw: str) -> str:
        """The stored upload, without the token in it.

        The password field is the token here, and the raw upload is kept for
        an hour beside the packet so a new sensor can be identified from it.
        That is the one place a token would sit in the database.
        """
        import re
        return re.sub(r"(?i)\b(PASSWORD|PASSKEY)=[^&\s]*",
                      r"\1=[redacted]", raw)

    def status(self) -> dict[str, Any]:
        return {
            "protocol": "weather underground",
            "uploads": self.received,
            "refused": self.refused,
            "stations": sorted(self.seen),
            "unknown_fields": sorted(self.unknown),
        }

    def unit_groups(self) -> dict[str, str]:
        return dict(GROUPS)


def _utc(text: str, shape: str) -> float:
    """`time.strptime` in UTC, without touching the process's timezone.

    `time.mktime` is local and `calendar.timegm` is the UTC counterpart. Using
    the first here would date every reading by the server's offset -- and it
    would look right on a machine set to UTC, which is what a container is.
    """
    import calendar
    return calendar.timegm(time.strptime(text, shape))


def load(registry) -> bool:
    """Register the driver. Called by the plugin loader."""
    registry.register_factory(DRIVER_NAME, WundergroundDriver)
    registry.register(DRIVER_NAME, WundergroundDriver(), replace=True)
    return True

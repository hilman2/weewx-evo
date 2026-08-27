"""The weewx-evo end of it.

Deliberately thin, the same way `driver.py` is thin in the WeeWX build of this
driver. The socket belongs to the core listener, the protocol to protocol.py,
the field names to catalog.py, and which consoles are recorded to the core.
What is left here is the part that has to know about weewx-evo: producing
packets, and saying what the gateway needs to hear back.

Configuration, under `[drivers.ecowitt]` in the configuration file:

    [drivers.ecowitt]
    # What to do with a field the catalog does not know yet:
    #   off     drop it
    #   series  keep it when it continues a known series, report the rest
    #   all     keep whatever can be named, including from naming rules
    infer_unknown = "series"

    report_file = "/var/tmp/weewx-evo-ecowitt-report.txt"

    # Your own mapping, which wins over the catalog.
    [drivers.ecowitt.field_map_extensions]
    yearlyrainin = "rain_year"

    # A field map per console, where there is more than one. Two consoles both
    # number their channels from one, so without this a WN34 on channel 1 of
    # each would overwrite the other.
    [drivers.ecowitt.stations.garden]
    passkey = "AAAA..."
    [drivers.ecowitt.stations.roof]
    passkey = "BBBB..."

**Which consoles are recorded is not decided here.** It is `stations.toml`,
where a console gets a name and an archive, and where the answer covers every
driver rather than this one. This driver produces packets for whatever it can
read, with the PASSKEY as the source, and the core turns that into a station.

It used to refuse a console it did not know, and that was wrong in a way that
only showed with more than one archive: no packet reached the core, so the
console did not turn up as a stranger either. Two consoles at two sites, and
the second one existed only in a log line.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ....db.live import Packet
from ....units import US
from ...drivers import BaseDriver
from . import VERSION, catalog, columns, protocol, report
from .mapping import Mapper

log = logging.getLogger(__name__)

DRIVER_NAME = "ecowitt"
DRIVER_VERSION = VERSION

# What the gateway wants to hear before it counts the upload as delivered.
# Anything else and some models retry, then back off for an hour.
ECOWITT_RESPONSE = (b'{"errcode":"0","errmsg":"ok"}', "application/json")


class EcowittDriver(BaseDriver):
    """Receives uploads from Ecowitt hardware and turns them into packets."""

    response = ECOWITT_RESPONSE

    def __init__(self, passkey: str | None = None,
                 stations: dict[str, dict[str, Any]] | None = None,
                 field_map_extensions: dict[str, str] | None = None,
                 infer_unknown: str = "series",
                 max_behind: int | None = None, max_ahead: int | None = None,
                 report_file: str | None = None, console_file: str | None = None,
                 state: Any = None, model: str = "Ecowitt") -> None:
        self.model = model
        self.version = VERSION
        self._report_file = report_file
        self._reported = False

        # How far the console's clock may be out before its own timestamp is
        # dropped. A console on the internet keeps its clock by NTP, so a stamp
        # a few minutes old means the upload was delayed, not the clock wrong.
        self.max_behind = int(max_behind if max_behind is not None
                              else protocol.MAX_BEHIND)
        self.max_ahead = int(max_ahead if max_ahead is not None
                             else protocol.MAX_AHEAD)

        # A field map per console, keyed on its PASSKEY, and a default for
        # everything else. Two consoles both number their channels from one,
        # so `temp1f` means a different thermometer on each -- that is what a
        # per-console map is for, and it is knowledge only this driver has.
        self.maps = self._read_maps(stations, infer_unknown)
        self.mapper = Mapper(
            extensions=dict(field_map_extensions or {}),
            infer_unknown=infer_unknown,
            max_behind=self.max_behind, max_ahead=self.max_ahead)
        self.seen_fields: dict[str, Any] = {}
        self.consoles: dict[str, int] = {}

        # `passkey` and `[stations]` used to decide which consoles were
        # answered at all, and the first console heard was adopted. That
        # decision has moved to `stations.toml`, where it covers every driver
        # and can say which archive a console writes into. Refusing here made
        # a second console invisible: no packet reached the core, so it did
        # not appear as a stranger either, and the only trace was a log line.
        if passkey or (stations and any(
                one.get("passkey") for one in stations.values())):
            log.warning(
                "a PASSKEY is configured under [drivers.ecowitt]. This driver "
                "no longer decides which consoles are recorded; announce them "
                "as stations instead, where each one gets a name and an "
                "archive. The field maps under [stations] are still read.")

        log.info("ecowitt %s: %d field map(s), every console recorded",
                 self.version, len(self.maps) + 1)

    @property
    def hardware_name(self) -> str:
        return self.model

    @staticmethod
    def options() -> list:
        """What this driver can be configured with.

        Declared rather than documented: the command line reads this, the
        admin page builds its form from it, and the configuration file gets
        its comments from it. Adding a setting here is all there is to it.
        """
        from ....options import Group, Option

        return [
            Group("Console", "How this driver reads Ecowitt hardware.", (
                Option("model", "Model", default="Ecowitt",
                       help="Shown in logs. Cosmetic.", advanced=True),
            ), prefix="drivers.ecowitt"),

            Group("Unknown fields",
                  "Ecowitt ships sensors faster than any catalog is updated.", (
                Option("infer_unknown", "Fields the catalog does not know",
                       kind="choice", default="series",
                       choices=(("off", "Drop them"),
                                ("series", "Take them when they continue a "
                                           "known series, report the rest"),
                                ("all", "Take whatever can be named")),
                       help="'series' is the sensible default: a channel the "
                            "hardware gains needs no release, and anything "
                            "merely recognisable by its name is reported "
                            "rather than guessed at. A reading put in the "
                            "wrong column cannot be separated out afterwards."),
                Option("report_file", "Write a report to", kind="path",
                       default="/var/tmp/weewx-evo-ecowitt-report.txt",
                       help="Where to leave the first upload that contains "
                            "something the driver cannot place. The file has "
                            "the PASSKEY removed already and is meant to be "
                            "pasted into an issue. Empty switches it off."),
            ), prefix="drivers.ecowitt"),

            Group("Clock", "How far a console's clock may be out.", (
                Option("max_behind", "Accept timestamps up to this old",
                       kind="duration", default=3600, minimum=0, advanced=True,
                       help="A console on the internet keeps its clock by NTP, "
                            "so a stamp a few minutes old means a delayed "
                            "upload rather than a wrong clock. Beyond this the "
                            "arrival time is used instead."),
                Option("max_ahead", "And this far into the future",
                       kind="duration", default=60, minimum=0, advanced=True,
                       help="There is no such thing as a reading from the "
                            "future, so this only covers drift between two "
                            "clocks that are both roughly right."),
            ), prefix="drivers.ecowitt"),
        ]

    # -- the driver interface --------------------------------------------

    def claims(self, body: bytes, meta: dict) -> float:
        """Whether this is an Ecowitt upload.

        `PASSKEY` is the certain one: it is how an Ecowitt console identifies
        itself, no other protocol here sends it, and it is present on every
        upload including the empty probes.

        `stationtype` is the fallback for the handful of firmwares that leave
        the passkey out. Below certain, because a rebadged console running
        somebody else's firmware could say it too.
        """
        if b"PASSKEY=" in body:
            return 1.0
        if b"stationtype=" in body and b"action=updateraw" not in body:
            return 0.8
        return 0.0

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        text = body.decode("utf-8", "replace")
        passkey = protocol.station_id(text)
        mapper = self.maps.get(passkey, self.mapper)

        packet, guesses = mapper.to_packet(text, now=meta.get("received"))
        self._maybe_report(text, guesses)
        if len(packet) <= 1:
            # Nothing but the timestamp. Usually a probe or a health check.
            return []

        stamp = packet.pop("dateTime")
        self.seen_fields.update(packet)
        if passkey:
            self.consoles[passkey] = int(time.time())
        # The PASSKEY, not a name. It is what the hardware says it is, and the
        # core turns it into a station name -- so renaming a station does not
        # mean touching this driver or its field maps.
        source = passkey or DRIVER_NAME
        return [Packet(
            dateTime=int(stamp),
            # Ecowitt uploads are imperial whatever the console displays. That
            # is a property of the protocol, so the driver settles it.
            usUnits=US,
            data=packet,
            source=str(source)[:64],
            kind="loop",
        )]

    def redact(self, raw: str) -> str:
        """The upload with the PASSKEY replaced.

        The PASSKEY is what identifies the station and what somebody would need
        in order to forge its readings. Everything else in an Ecowitt upload is
        weather, which is why a redacted body can go straight into an issue.
        """
        return protocol.redact(raw)

    def status(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "model": self.model,
            # Which consoles have uploaded, not which ones are allowed to.
            # Whether a console is recorded is the core's answer now, and it
            # is on the stations page.
            "consoles": sorted(self.consoles),
            "field_maps": sorted(self.maps),
            "fields_seen": len(self.seen_fields),
        }

    # -- what the core may ask a driver for ------------------------------

    def unit_groups(self) -> dict[str, str]:
        """Which unit group each field belongs to.

        The catalog's, plus whatever the mappers have inferred since. Under
        WeeWX this goes into `weewx.units.obs_group_dict`; here it is offered
        to whoever formats a value or types a column.
        """
        groups = dict(catalog.GROUPS)
        for mapper in self._mappers():
            groups.update(mapper.wanted_groups())
        return {field: group for field, group in groups.items() if group}

    def missing_columns(self, known: set[str]) -> list[tuple[str, str]]:
        """Columns this station's readings need and the database does not have.

        A reading only survives the archive interval if there is a column for
        it. The type comes from the catalog's unit groups rather than from the
        field's name: counted and stamped things are INTEGER, measured things
        are REAL.
        """
        packet = dict(self.seen_fields)
        packet.setdefault("dateTime", 0)
        return columns.missing(packet, self.unit_groups(), known=known)

    # -- consoles --------------------------------------------------------

    def _read_maps(self, configured: dict | None,
                   infer_unknown: str) -> dict[str, Mapper]:
        """A field map per console, keyed on its PASSKEY.

        `[stations]` used to carry a name as well, and the name decided what
        the readings were recorded under. That belongs to `stations.toml` now,
        where it is one name per console across every driver and carries the
        archive with it. A name left here is read and reported, so nobody is
        left wondering why it stopped having an effect.
        """
        if not configured:
            return {}
        made: dict[str, Mapper] = {}
        for name, options in configured.items():
            passkey = options.get("passkey")
            if not passkey:
                raise ValueError(
                    f"station {name!r} has no 'passkey'. It is the value the console "
                    "sends first in every upload, and what its field map hangs on.")
            made[str(passkey).strip()] = Mapper(
                extensions=dict(options.get("field_map_extensions", {})),
                infer_unknown=options.get("infer_unknown", infer_unknown),
                max_behind=self.max_behind, max_ahead=self.max_ahead)
        log.info("field maps for %d console(s)", len(made))
        return made

    def _mappers(self) -> list[Mapper]:
        return [self.mapper, *self.maps.values()]

    # -- reporting -------------------------------------------------------

    def _maybe_report(self, payload: str, guesses: list) -> None:
        """Write out one upload, the first time something cannot be placed.

        Getting hold of a raw upload otherwise means reconfiguring the console
        and waiting for an interval. The driver has it in hand, so it writes it
        once, with the PASSKEY already redacted, and says where the file is.
        """
        if self._reported or not self._report_file:
            return
        waiting = {}
        for mapper in self._mappers():
            waiting.update({raw: field for raw, field in mapper.undecided.items()
                            if raw in mapper.warned})
        if not guesses and not waiting:
            return
        self._reported = True
        try:
            path = report.write(payload, guesses, waiting, self._report_file)
        except Exception:
            log.exception("could not write the report")
            return
        if path:
            log.info("this station sends fields I cannot place on my own. Everything "
                     "needed to report them is in %s", path)


#: No aliases. This driver used to answer to `wunderground` as well, on the
#: reasoning that the two protocols are the same shape -- a urlencoded body and
#: a query string differ only in where they sit.
#:
#: The shape is the same and the *names are not*, which is the part that
#: matters. Measured against what a WU station actually sends, this driver
#: placed 30 of 63 fields and lost the other 33 -- `baromin` among them, so the
#: pressure was simply absent, which reads as a dead sensor rather than as a
#: wrong driver. Ecowitt says `baromrelin`; Weather Underground says `baromin`.
#:
#: `plugins/wunderground/` reads that protocol properly now.
ALIASES: tuple[str, ...] = ()


def load(registry) -> bool:
    """Register the driver. Called by the plugin loader."""
    registry.register_factory(DRIVER_NAME, EcowittDriver, aliases=ALIASES)
    # An unconfigured instance, so a checkout works with no configuration file.
    # `weewx-evo serve` replaces it with a configured one at startup.
    instance = EcowittDriver()
    registry.register(DRIVER_NAME, instance, replace=True)
    for alias in ALIASES:
        registry.register(alias, instance, replace=True)
    return True

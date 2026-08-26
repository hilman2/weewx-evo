"""The weewx-evo end of it.

Deliberately thin, the same way `driver.py` is thin in the WeeWX build of this
driver. The socket belongs to the core listener, the protocol to protocol.py,
the field names to catalog.py, the console list to consoles.py. What is left
here is the part that has to know about weewx-evo: producing packets, and
saying what the gateway needs to hear back.

Configuration, under `[drivers.ecowitt]` in the configuration file:

    [drivers.ecowitt]
    # The console to answer to. Setting it here settles the question for good
    # and does not depend on any file surviving.
    passkey = "3178AB6B42A759F51A5A4AD72E37F8DE"

    # What to do with a field the catalog does not know yet:
    #   off     drop it
    #   series  keep it when it continues a known series, report the rest
    #   all     keep whatever can be named, including from naming rules
    infer_unknown = "series"

    report_file = "/var/tmp/weewx-evo-ecowitt-report.txt"

    # Your own mapping, which wins over the catalog.
    [drivers.ecowitt.field_map_extensions]
    yearlyrainin = "rain_year"

    # Or one console per station, each with its own field map. Two consoles
    # both number their channels from one, so without this a WN34 on channel 1
    # of each would overwrite the other.
    [drivers.ecowitt.stations.garden]
    passkey = "AAAA..."
    [drivers.ecowitt.stations.roof]
    passkey = "BBBB..."
"""

from __future__ import annotations

import logging
from typing import Any

from ....db.live import Packet
from ....units import US
from ...drivers import BaseDriver
from . import VERSION, catalog, columns, consoles, protocol, report
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

        # One mapping, or one per console.
        self.stations = self._read_stations(stations, infer_unknown)
        self.mapper = None if self.stations else Mapper(
            extensions=dict(field_map_extensions or {}),
            infer_unknown=infer_unknown,
            max_behind=self.max_behind, max_ahead=self.max_ahead)

        # Which consoles to answer to. Anyone who can reach the port can point a
        # console at it, and a second one writing the same channels would mix two
        # sensors into a column that nothing afterwards can separate.
        # `state` is get/set/delete on strings and nothing else. The driver
        # cannot reach the archive through it, which is the point: producing
        # packets is its job, and writing records is not.
        self.store = consoles.Store(
            console_file or consoles.path_for(configured=console_file),
            state=state)
        self.configured_passkey = str(passkey).strip() if passkey else None
        self.known = self._known_consoles()
        self.unknown_consoles: set[str] = set()
        self.adopted: str | None = None
        self.seen_fields: dict[str, Any] = {}

        log.info("ecowitt %s: %s", self.version,
                 f"answering to {len(self.known)} console(s)" if self.known
                 else "no console on record; the next one to upload is adopted")

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
            Group("Console", "Which hardware this driver answers to.", (
                Option("passkey", "Console PASSKEY", kind="secret",
                       help="The value the console sends first in every upload. "
                            "Setting it here settles the question for good. "
                            "Left empty, the first console heard is adopted and "
                            "remembered in the database -- which works, but is "
                            "lost with the database and hands the station to "
                            "whichever console speaks first after that."),
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

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        text = body.decode("utf-8", "replace")
        name, mapper = self._mapper_for(text, meta.get("source", "?"))
        if mapper is None:
            return []

        packet, guesses = mapper.to_packet(text, now=meta.get("received"))
        self._maybe_report(text, guesses)
        if len(packet) <= 1:
            # Nothing but the timestamp. Usually a probe or a health check.
            return []

        stamp = packet.pop("dateTime")
        self.seen_fields.update(packet)
        source = name or protocol.station_id(text) or DRIVER_NAME
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
            "consoles": sorted(self.known),
            "consoles_kept_in": self.store.where,
            "adopted": self.adopted,
            "refused": sorted(self.unknown_consoles),
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

    def _read_stations(self, configured: dict | None,
                       infer_unknown: str) -> dict[str, tuple[str, Mapper]]:
        """Return {PASSKEY: (name, Mapper)} for a station with several consoles."""
        if not configured:
            return {}
        stations = {}
        for name, options in configured.items():
            passkey = options.get("passkey")
            if not passkey:
                raise ValueError(
                    f"station {name!r} has no 'passkey'. It is the value the console "
                    "sends first in every upload.")
            stations[str(passkey).strip()] = (name, Mapper(
                extensions=dict(options.get("field_map_extensions", {})),
                infer_unknown=options.get("infer_unknown", infer_unknown),
                max_behind=self.max_behind, max_ahead=self.max_ahead))
        log.info("listening for %d consoles: %s",
                 len(stations), ", ".join(sorted(n for n, _ in stations.values())))
        return stations

    def _mappers(self) -> list[Mapper]:
        if self.mapper is not None:
            return [self.mapper]
        return [mapper for _name, mapper in self.stations.values()]

    def _known_consoles(self) -> set[str]:
        """The PASSKEYs this driver answers to.

        From the configuration, from [stations], or from where the first console
        ever heard was recorded. Empty means nothing has been heard yet, and the
        next console to upload is adopted.
        """
        known = set(self.stations)
        if self.configured_passkey:
            known.add(self.configured_passkey)
        if known:
            return known
        remembered = set(self.store.read())
        if remembered:
            log.info("answering to %d console(s) on record in the %s",
                     len(remembered), self.store.where)
        return remembered

    def _mapper_for(self, text: str, client: str) -> tuple[str | None, Mapper | None]:
        """Which mapping this upload belongs to, or None to leave it alone."""
        passkey = protocol.station_id(text)

        if not self.known:
            self._adopt(passkey, client)

        if passkey not in self.known:
            self._refuse(passkey, client)
            return None, None

        if self.mapper is not None:
            return None, self.mapper
        return self.stations[passkey]

    def _adopt(self, passkey: str, client: str) -> None:
        """Record the first console ever heard, and answer to it from then on."""
        self.known.add(passkey)
        self.adopted = passkey
        where = self.store.add(passkey, f"first console seen, from {client}")
        log.info(
            "console %r at %s is now this driver's station, on record in the %s. "
            "Uploads from any other console are refused until it is named under "
            "[stations].", passkey, client, where or "log only")
        self._suggest_passkey(passkey)

    def _suggest_passkey(self, passkey: str) -> None:
        """Point at the setting that does not depend on a file surviving.

        The file is a convenience. A copied database, a rebuilt machine or a
        directory nobody backed up leaves it behind, and then the next console
        to upload becomes the station. One line in the configuration does not
        have that problem, so say so where somebody will see it.
        """
        if self.configured_passkey or self.stations:
            return
        log.info("to keep it independent of anything stored, put it in the "
                 "configuration: passkey = %r under [drivers.ecowitt].", passkey)

    def _refuse(self, passkey: str, client: str) -> None:
        if passkey in self.unknown_consoles:
            return
        self.unknown_consoles.add(passkey)
        log.warning(
            "an upload from %s carries PASSKEY %r, which is not one of this "
            "driver's consoles. Ignoring it. If it is yours, add it under "
            "[stations] with its own field map: two consoles number their "
            "channels from one, and would otherwise write into the same fields.",
            client, passkey)

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


#: The Weather Underground protocol is the same shape and the same driver reads
#: it -- a urlencoded body and a query string differ only in where they sit. It
#: is the *same instance* under both names, not a second one: two instances
#: would each adopt a console and each keep their own list.
ALIASES = ("wunderground",)


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

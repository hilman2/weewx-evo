"""Every protocol that pushes readings at us, as drivers.

Six protocols, one place. They were three separate plugins here -- ecowitt,
wunderground, and nothing at all for the other four -- and each new one meant
another copy of the same parsing, the same inference, the same argument about
what a field name means.

Upstream this is `weewx-ultimate-push`, and the split it makes is the reason
the whole thing fits under one roof:

    A **protocol** is an exchange. A path, an answer, a way of naming the
    station. Ecowitt and Weather Underground are different protocols.

    A **dialect** is a catalog. The same exchange with different field names,
    or the same names in different units. Fine Offset firmwares speak Weather
    Underground in Fahrenheit and inches, or in Celsius and millimetres, on
    the same endpoint with the same credentials. One protocol, two dialects.

`protocols/` and `catalogs/` are taken from there unchanged, because they
import nothing -- not WeeWX, not us -- and a fix should be able to travel in
either direction. This file is the whole of the adaptation: it turns a
`Protocol` class into something the listener can call.

## What the listener already does for them

Their `driver.py` is 1610 lines, and most of it is work this program has
done elsewhere for a while:

    the socket, threads, shutdown      ingest/listener.py
    which console may write            stations.toml
    what a station is allowed to fill  sources.py, and the archive it names
    unit registration                  units.contribute
    telling somebody what is wrong     the settings page

So none of that comes over. What is left is a per-protocol parse and a
per-dialect mapper, which is this file.
"""

from __future__ import annotations

import logging
from typing import Any

from ....db.live import Packet
from ...drivers import Response
from . import mapping, transport
from . import protocols as protocol_defs

log = logging.getLogger(__name__)

#: WeeWX's unit-system constants, which are also ours: the envelope carries
#: `usUnits` because the archive column does.
US = 1
METRIC = 16
METRICWX = 17


class _Request:
    """What a protocol asks about the request it is deciding on.

    Three attributes, because that is all any of the six look at. Made here
    rather than passing our `meta` dictionary through, so that the protocols
    stay code that can be lifted back out unchanged.
    """

    __slots__ = ("body", "method", "path")

    def __init__(self, path: str = "/", body: bytes = b"",
                 method: str = "POST") -> None:
        self.path = path
        self.body = body
        self.method = method

    @property
    def text(self) -> str:
        if isinstance(self.body, bytes):
            return self.body.decode("utf-8", "replace")
        return str(self.body or "")


class PushDriver:
    """One protocol, as a driver.

    A mapper per dialect, not per protocol. Inference learned from `tempf`
    and `soiltemp2f` has no business being applied to `outtemp` and
    `absbaro`, and Weather Underground carries both on one endpoint.
    """

    #: Set on each subclass by `driver_class`. Here so that `__init__` can
    #: take the protocol from the class rather than as an argument, which is
    #: what lets the subclass keep this constructor -- see the note there.
    protocol_class: Any = None

    def __init__(self, protocol: Any = None,
                 field_map_extensions: dict[str, str] | None = None,
                 infer_unknown: str = mapping.SERIES,
                 max_behind: int | None = None, max_ahead: int | None = None,
                 stations: dict[str, dict] | None = None,
                 **ignored: Any) -> None:
        # `field_map_extensions` keeps the name the ecowitt driver used, and
        # the running instance has two decisions written under it -- which
        # column `tf_ch1` and `soil_ec_temp1` go to. Renaming the option would
        # mean two sensors quietly landing in one column, which is the one
        # failure the whole contested-field mechanism exists to prevent.
        protocol = protocol or type(self).protocol_class
        self.protocol = protocol
        self.name = protocol.name
        #: One mapper per dialect seen, built on first use.
        self._mappers: dict[str, mapping.Mapper] = {}
        self.field_map = dict(field_map_extensions or {})
        self.infer_unknown = infer_unknown
        # Read here rather than relying on a schema to have done it. These
        # arrive from three places now -- the core settings, a station, and
        # `drivers.<name>.max_behind` left in a file from when this was a
        # per-protocol option -- and only the first two are parsed on the way.
        # Handed the string "4h", `int()` raises during startup, the
        # exception is swallowed, and the driver runs on its default: nothing
        # in any log reads as a wrong setting and the figure silently does
        # nothing.
        self.max_behind = _duration(max_behind, transport.MAX_BEHIND)
        self.max_ahead = _duration(max_ahead, transport.MAX_AHEAD)
        #: What each console says about itself, keyed by the identity it
        #: uploads with. The core hands these over from stations.toml.
        #:
        #: Keyed by identity, not by name, and that is the whole of a bug
        #: this had: the lookup below is made with what the protocol read off
        #: the upload -- a PASSKEY -- while the dictionary arrived keyed by
        #: the name somebody typed. It therefore never matched, and every
        #: placement the settings page wrote went nowhere. The installation
        #: kept working because the same decisions were also sitting in the
        #: driver's own `field_map_extensions`, where they had been put by
        #: hand before the page existed.
        self.stations = _by_identity(stations)
        #: What could not be placed, for the settings page to show.
        self.unplaced: dict[str, Any] = {}
        #: What the device wants to read back. An attribute, because that is
        #: what `drivers.response_of` reads -- a method here was taken as the
        #: answer itself and indexed, which is a 500 on every upload.
        #:
        #: Many of these treat an upload as failed until they have seen the
        #: right answer: they retry, and eventually give up. Ecowitt wants
        #: JSON, Weather Underground wants the word `success`.
        self.response: Response = ((protocol.answer or "success").encode(),
                                   protocol.content_type)

    # -- what the listener calls -----------------------------------------

    def claims(self, body: bytes, meta: dict) -> float:
        """How sure this protocol is that the upload is its own.

        Their scale is 0 to 5 and ours is 0 to 1, so it is divided. The
        ordering is what matters and that survives.
        """
        request = _Request(path=str(meta.get("path") or "/"), body=body)
        try:
            raw = self._raw(request)
        except Exception:
            return 0.0
        try:
            return self.protocol.claims(request, raw) / 5.0
        except Exception:
            log.debug("%s could not decide about an upload", self.name,
                      exc_info=True)
            return 0.0

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        request = _Request(path=str(meta.get("path") or "/"), body=body)
        raw = self._raw(request)
        if not raw:
            return []

        readings = self.protocol.readings(request, raw)
        if not readings:
            return []
        dialect = self.protocol.dialect(raw)
        mapper = self._mapper_for(dialect, self._station_of(raw))

        packet, guesses = mapper.to_packet(readings)
        if guesses:
            for guess in guesses:
                self.unplaced[guess.raw] = guess
        stamp = packet.pop("dateTime", None) or meta.get("received")
        data = {name: value for name, value in packet.items()
                if value is not None}
        if not data:
            return []
        return [Packet(dateTime=int(stamp), usUnits=int(dialect.units),
                       data=data, source=self._station_of(raw) or self.name,
                       kind="loop", received=meta.get("received"))]

    def unit_groups(self) -> dict[str, str]:
        """What this protocol's fields measure, for anything that formats one.

        The catalog's own groups plus whatever inference has settled on. Both,
        because a field the catalog does not name still needs a unit before a
        page can print it.
        """
        found = dict(self.protocol.groups)
        for mapper in self._mappers.values():
            found.update(mapper.wanted_groups())
        return found

    def redact(self, raw: str) -> str:
        """The upload with whatever names the station replaced.

        The raw body is kept beside the packet for an hour so that a question
        about a new sensor can be answered from it, and that copy is meant to
        be pasteable into an issue. A PASSKEY is what somebody would need to
        forge this station's readings and a Weather Underground PASSWORD is a
        password; everything else in these uploads is weather, which is the
        point of sending one to somebody who can help.

        Without this the listener keeps the body as it arrived. That is how
        it was before the six protocols moved in together, and losing it was
        the only thing this move broke that a test caught.
        """
        return transport.redact(raw)

    def status(self) -> dict[str, Any]:
        return {
            "protocol": self.name,
            "hardware": self.protocol.hardware,
            "dialects": sorted(self._mappers),
            "unplaced": sorted(self.unplaced),
        }

    # -- the parts of it -------------------------------------------------

    def _raw(self, request: _Request) -> dict[str, str]:
        """The name/value pairs, however this protocol shapes them."""
        return transport.parse(request.text)

    def _station_of(self, raw: dict) -> str:
        try:
            return self.protocol.station_of(raw) or ""
        except Exception:
            return ""

    def _mapper_for(self, dialect: Any, station: str) -> mapping.Mapper:
        key = f"{dialect.name}\x00{station}"
        mapper = self._mappers.get(key)
        if mapper is None:
            mine = self.stations.get((station or "").casefold()) or {}
            # The station's own map wins over the driver-wide one: two
            # consoles both number their channels from one, and the whole
            # point of a per-station map is that channel 1 is not the same
            # sensor on both.
            extensions = dict(self.field_map)
            extensions.update(mine.get("field_map_extensions") or {})
            # And its own clock, where it has been given one. A stamp is too
            # old because a *clock* is wrong, and a clock belongs to a box:
            # an old display that drifts and a GW2000 keeping NTP are one
            # protocol and two different answers.
            mapper = mapping.Mapper(
                dialect, extensions=extensions,
                infer_unknown=self.infer_unknown,
                max_behind=_clock(mine, "max_behind", self.max_behind),
                max_ahead=_clock(mine, "max_ahead", self.max_ahead))
            self._mappers[key] = mapper
        return mapper


def _duration(value: Any, fallback: float) -> float:
    """Seconds from a number or from what somebody typed ("4h", "5m")."""
    if value is None or value == "":
        return fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        from ....options import parse_duration

        return float(parse_duration(str(value)))
    except Exception:
        log.warning("could not read %r as a length of time; using %s seconds",
                    value, fallback)
        return float(fallback)


def _by_identity(stations: dict[str, dict] | None) -> dict[str, dict]:
    """The stations keyed by what a console actually sends.

    They arrive keyed by the name somebody typed, because that is what the
    settings page and `sources.toml` use. What reaches the lookup is a
    PASSKEY or a station ID, read off the upload -- so the key has to be the
    identity, and folded, since consoles upper-case what is typed into them.
    """
    found: dict[str, dict] = {}
    for name, entry in (stations or {}).items():
        if not isinstance(entry, dict):
            continue
        identity = str(entry.get("passkey") or entry.get("identity") or "")
        if identity:
            found[identity.casefold()] = entry
        # Under its name as well: a protocol that names its station some
        # other way still finds itself, and it costs one dictionary entry.
        found.setdefault(str(name).casefold(), entry)
    return found


def _clock(station: dict, name: str, fallback: float) -> float:
    found = station.get(name)
    return fallback if found is None else float(found)


def _options(protocol: Any) -> list:
    """Nothing. A protocol has nothing to configure.

    It had three: what to do with a field the catalog does not name, and how
    far a console's clock may be out in either direction. Six protocols
    arrived at once, so that was six settings pages carrying the same three
    fields, and every one of them described something that is not a property
    of a protocol:

        infer_unknown   a policy of the installation. Somebody careful about
                        a guessed field name is careful about all six of
                        them, so it is asked once, in the core.
        max_behind      a property of a console. A stamp is too old because
        max_ahead       a clock is wrong, and a clock is in a box: an old
                        display that drifts and a GW2000 keeping NTP are one
                        protocol and two answers. Set per protocol, the
                        tolerant figure the old one needs would be handed to
                        the new one as well. They are on the station now,
                        defaulting to the core's.

    What is genuinely per-protocol -- the endpoint, the answer the hardware
    waits for, the catalog, which dialects exist -- is in `protocols/` and
    `catalogs/`, and none of it is anybody's to change.

    So the six drivers have no page, and the sidebar has no six entries. A
    driver from outside the repository is unaffected: it declares whatever it
    likes and gets its own page, which is the point of the mechanism.
    """
    return []


def driver_class(protocol: Any) -> type:
    """A class per protocol, so each can be asked what it configures.

    `cli.all_schemas` asks `type(driver)` for its options, which is right --
    the settings of a driver are a property of the driver and not of the one
    instance that happens to be running. But six protocols sharing one class
    would then be six identical forms under six names, all of them the last
    protocol's.

    So each gets a subclass with its own `options()` and its own protocol
    bound. Six lines of machinery to keep one line of the core unchanged.
    """
    def options() -> list:
        return _options(protocol)

    # No `__init__` of its own, and that is not tidiness. The core decides
    # what to hand a driver by reading its constructor -- `_accepts` in
    # cli.py, the same way `state` is offered only to a driver that asks for
    # one. A subclass whose `__init__` was `lambda self, **kw` has a
    # signature with no parameters in it at all, so it was offered nothing:
    # not `stations`, not the clock, not the placements the settings page
    # writes. Uploads kept working on the driver-wide field map alone, which
    # is why it went unnoticed. The protocol comes off the class instead.
    return type(
        f"{protocol.name.title()}Driver", (PushDriver,),
        {
            "__doc__": f"{protocol.label}: {protocol.hardware}",
            "protocol_class": protocol,
            "options": staticmethod(options),
        },
    )


def load(registry: Any) -> bool:
    """Every pushing protocol, as its own driver.

    One driver each rather than one that reads six, because the core already
    chooses between drivers by asking each what it makes of an upload. That
    is their `detect()`, one layer up, and having it in both places would be
    two answers to one question.
    """
    for protocol in protocol_defs.registry():
        made = driver_class(protocol)
        registry.register_factory(protocol.name, made)
        registry.register(protocol.name, made(), replace=True)
    return True

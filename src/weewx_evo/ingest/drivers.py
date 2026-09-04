"""What a driver is, and what the core does not get to know.

The split is the whole architecture, so it is worth stating flatly:

**The core owns the socket.** Threads, shutdown, body limits, IPv6, the token
check, and writing to the live table. Those are the same for every protocol,
they are where push drivers go wrong, and doing them once is doing them once.

**The driver owns everything else.** Parsing, units, which device it will
answer to, and what that device needs to hear back. The core does not know
what an Ecowitt is and cannot be made to care.

**The naming is shared, and the seam is data.** A driver hands over readings
under the names the hardware used and a declarative `DialectSpec`: field map,
scale factors, missing values and unit system, made entirely of JSON values.
The listener stores both. The archiver executes the description with core
code and never imports or calls the driver. A driver whose names are already
WeeWX's leaves `dialect` and `mapping` unset, which is every collector, the
WeeWX shim, and the envelope.

That last part is not tidiness. Field lists are the hard part of this business
and they change faster than releases: a current HP2561AE Pro sends 45 fields,
and `weewx-interceptor` maps 25 of them. Whoever keeps up with that ships on
their own schedule. That important drivers -- Ecowitt above all -- should live
in this repository and be maintained centrally is a separate argument, and a
good one. It changes nothing here: in the repository or out of it, a driver
plugs in through this interface and through nothing else.

A driver is any object with `packets()`. Everything else has a default:

    class MyDriver:
        def packets(self, body: bytes, meta: dict) -> list[Packet]:
            ...

Register it from a package:

    [project.entry-points."weewx_evo.drivers"]
    mine = "my_package:MyDriver"

The entry point may be a class (instantiated with its configuration), a
factory, or a plain function for the trivial case.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..db.live import Packet

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "weewx_evo.drivers"

#: What to send back, as (body, content type). Devices are picky about this and
#: it is protocol knowledge, so the driver decides and the core repeats it.
Response = tuple[bytes, str]

DEFAULT_RESPONSE: Response = (b"success\n", "text/plain")


@runtime_checkable
class Driver(Protocol):
    """Bytes in, finished packets out."""

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        """Turn one upload into packets.

        `meta` carries `received` (arrival time, unix) and `source` (the peer
        address). Returning an empty list is normal and not an error: consoles
        send probes and health checks.

        Raising is also allowed. The listener logs it and answers anyway,
        because a console that gets an error stops uploading and the next
        measurement is worth more than the tidy status code.
        """
        ...

    def dialect_spec(self, readings: dict[str, Any], dialect: str) -> DialectSpec:
        """Describe a dialect using JSON data only. Optional."""
        ...


class BaseDriver:
    """A driver that only needs to parse. Defaults for everything else."""

    #: What the hardware wants to hear. Override for anything that checks.
    response: Response = DEFAULT_RESPONSE

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        raise NotImplementedError

    def claims(self, body: bytes, meta: dict) -> float:
        """How sure this driver is that the upload is its protocol.

        Asked only when the path did not name a driver, which is the ordinary
        case for hardware with no server-path field: an Ambient WS-2902 is
        reached by pointing DNS at us and sends whatever its firmware has
        burned in.

        Zero means "not mine" and is the default, so a driver that only ever
        answers on a named path need not implement this. Above zero is a
        confidence, and the highest wins:

            1.0   something only this protocol has -- Ecowitt's PASSKEY
            0.9   a strong marker -- `action=updateraw`
            0.5   plausible, but another driver may know better

        A number rather than a boolean because a boolean needs a tie-break,
        and the only one available is registration order, which is
        alphabetical. `ecowitt` before `wunderground` would work today and
        break silently on the first driver named `ambient`.

        **Cheap and certain, in that order.** This runs on every upload whose
        path says nothing. Look for a marker, do not parse the payload.
        """
        return 0.0

    def dialect_spec(self, readings: dict[str, Any], dialect: str
                     ) -> DialectSpec | None:
        """A serializable account of `dialect`, or None for WeeWX names.

        Called by the listener, while the driver is already in scope. The
        returned data is stored beside the readings; no driver method is
        called while an archive record is built.
        """
        return None

    def status(self) -> dict[str, Any]:
        """Whatever the driver wants reported at /status. Optional."""
        return {}

    def start(self, deliver: Callable[[bytes], int]) -> None:
        """Begin whatever this driver runs on its own. Optional.

        For hardware with nowhere to type a server address into. A PurpleAir
        sensor, a Davis AirLink and an Ecowitt gateway on its own API all
        answer whoever asks and can be pointed at nothing, so a driver that
        only ever waits never sees them.

        `deliver(body)` takes the answer, and is the same door an upload
        comes through: what arrives is parsed by this driver, stored under
        the names the hardware used, and reaches a page and an archive the
        way a pushed reading does. It returns how many packets were stored.

        **The whole of what a polling driver is given.** Not the store, not
        the archive, not the settings -- the same reasoning as `state`: hand
        over the narrow thing and the wide one is not reachable. A driver
        that could write records would make that our bug to explain.

        Run it on a thread of your own and return. This is called once, while
        the listener is coming up, and `close()` is called when it goes down.

        ## Why here and not in a process of its own

        `CLAUDE.md` says a collector costs a process and a parser costs
        lines, and that is still the rule: a serial Vantage or anything
        needing pyusb belongs outside, where it may hang and crash without
        taking the archiver with it. An HTTP GET to an address on the same
        network every sixty seconds is the other case. It needs no device
        access, no dependency and no supervision, so it costs lines -- and
        the same arrangement the export runners use, a thread each so that
        one host which stops answering holds up only itself.
        """

    def close(self) -> None:
        """Release anything held, and stop anything `start` began. Optional."""

    def place(self, readings: dict[str, Any], dialect: str,
              decisions: dict[str, str], infer: str = "off") -> Placed | None:
        """Propose names for the listener's settings page. Optional.

        This compatibility hook runs only in the listener process. Archive
        records are built from `dialect_spec`, never through this method.

        Args:
            readings (dict): What `packets()` put in `Packet.data`, read back.
            dialect (str): The `Packet.dialect` those readings were stored
                with, so a driver reading two catalogs knows which one.
            decisions (dict): Raw name -> archive column, or `-` for nowhere.
                The operator's, merged from the widest scope to the narrowest
                by `placement.Placements.extensions`.
            infer (str): Whether to guess at names nothing has placed: `off`,
                `series` or `all`.

        Returns:
            Placed|None: None means "my names are already WeeWX's", which is
            the default and what a driver that never implements this says.

        What a driver would like to infer is proposed at ingest and written
        down -- see `placement.promote`.
        """
        return None


DIALECT_SPEC_VERSION = 1
MAX_DIALECT_NAME = 128
MAX_SPEC_BYTES = 128 * 1024
MAX_SPEC_ENTRIES = 2048
MAX_SPEC_NAME = 256
MAX_ABSENT_VALUES = 256
_SPEC_KEYS = frozenset({
    "version", "fields", "contested", "scale", "metadata", "absent",
    "groups", "usUnits",
})
_UNIT_SYSTEMS = frozenset({1, 16, 17})


def valid_dialect_name(value: object) -> bool:
    """Whether a driver-supplied dialect is safe to retain and diagnose."""
    return (isinstance(value, str) and 0 < len(value) <= MAX_DIALECT_NAME
            and all(character.isprintable() for character in value))


@dataclass(frozen=True, slots=True)
class DialectSpec:
    """A driver's vocabulary in the only form the archiver accepts.

    Every value is a JSON primitive, list or object. In particular there is
    no class name, module name or callable for the read side to import. A
    packet therefore carries everything core code needs to map it without
    granting its driver access to the archive process.
    """

    fields: dict[str, str]
    usUnits: int
    contested: frozenset[str] = frozenset()
    scale: dict[str, float] = field(default_factory=dict)
    metadata: frozenset[str] = frozenset()
    absent: tuple[str | int | float, ...] = ()
    groups: dict[str, str] = field(default_factory=dict)
    version: int = DIALECT_SPEC_VERSION

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != DIALECT_SPEC_VERSION:
            raise ValueError(f"dialect mapping version must be {DIALECT_SPEC_VERSION}")
        if type(self.usUnits) is not int or self.usUnits not in _UNIT_SYSTEMS:
            raise ValueError("dialect mapping usUnits must be 1, 16 or 17")
        object.__setattr__(self, "fields", _string_map(self.fields, "fields"))
        object.__setattr__(self, "groups", _string_map(self.groups, "groups"))
        object.__setattr__(self, "contested",
                           frozenset(_string_list(self.contested, "contested")))
        object.__setattr__(self, "metadata",
                           frozenset(_string_list(self.metadata, "metadata")))
        factors: dict[str, float] = {}
        if not isinstance(self.scale, dict):
            raise ValueError("dialect mapping scale must be an object")
        if len(self.scale) > MAX_SPEC_ENTRIES:
            raise ValueError("dialect mapping scale has too many entries")
        for name, value in self.scale.items():
            if (not isinstance(name, str) or not name
                    or len(name) > MAX_SPEC_NAME):
                raise ValueError("dialect mapping scale names must be non-empty strings")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"dialect mapping scale for {name!r} must be a number")
            try:
                factor = float(value)
            except OverflowError as exc:
                raise ValueError(
                    f"dialect mapping scale for {name!r} must be finite") from exc
            if not math.isfinite(factor):
                raise ValueError(f"dialect mapping scale for {name!r} must be finite")
            factors[name] = factor
        object.__setattr__(self, "scale", factors)
        if not isinstance(self.absent, (list, tuple)):
            raise ValueError("dialect mapping absent must be a list")
        if len(self.absent) > MAX_ABSENT_VALUES:
            raise ValueError("dialect mapping absent has too many values")
        absent = []
        for value in self.absent:
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError("dialect mapping absent values must be strings or numbers")
            if isinstance(value, str) and len(value) > MAX_SPEC_NAME:
                raise ValueError("dialect mapping absent strings are too long")
            try:
                finite = not isinstance(value, str) and math.isfinite(float(value))
            except OverflowError:
                finite = False
            if not isinstance(value, str) and not finite:
                raise ValueError("dialect mapping absent numbers must be finite")
            absent.append(value)
        object.__setattr__(self, "absent", tuple(absent))
        try:
            size = len(json.dumps(
                self.as_dict(), sort_keys=True, separators=(",", ":"),
                allow_nan=False).encode())
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("dialect mapping must contain JSON values only") from exc
        if size > MAX_SPEC_BYTES:
            raise ValueError(
                f"dialect mapping is larger than {MAX_SPEC_BYTES} bytes")

    @classmethod
    def from_dict(cls, raw: object) -> DialectSpec:
        if not isinstance(raw, dict):
            raise ValueError("dialect mapping must be an object")
        unknown = set(raw) - _SPEC_KEYS
        if unknown:
            raise ValueError("unknown dialect mapping key(s): "
                             + ", ".join(sorted(str(one) for one in unknown)))
        missing = {"version", "fields", "usUnits"} - set(raw)
        if missing:
            raise ValueError("missing dialect mapping key(s): "
                             + ", ".join(sorted(missing)))
        return cls(
            version=raw["version"], fields=raw["fields"],
            usUnits=raw["usUnits"], contested=raw.get("contested", ()),
            scale=raw.get("scale", {}), metadata=raw.get("metadata", ()),
            absent=raw.get("absent", ()), groups=raw.get("groups", {}),
        )

    def as_dict(self) -> dict[str, Any]:
        """A stable object containing JSON values and nothing executable."""
        return {
            "version": self.version,
            "fields": dict(sorted(self.fields.items())),
            "contested": sorted(self.contested),
            "scale": dict(sorted(self.scale.items())),
            "metadata": sorted(self.metadata),
            "absent": list(self.absent),
            "groups": dict(sorted(self.groups.items())),
            "usUnits": self.usUnits,
        }


def _string_map(raw: object, label: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(f"dialect mapping {label} must be an object")
    if len(raw) > MAX_SPEC_ENTRIES:
        raise ValueError(f"dialect mapping {label} has too many entries")
    made = {}
    for name, value in raw.items():
        if (not isinstance(name, str) or not name
                or len(name) > MAX_SPEC_NAME):
            raise ValueError(f"dialect mapping {label} names must be non-empty strings")
        if (not isinstance(value, str) or not value
                or len(value) > MAX_SPEC_NAME):
            raise ValueError(f"dialect mapping {label} values must be non-empty strings")
        made[name] = value
    return made


def _string_list(raw: object, label: str) -> list[str]:
    if not isinstance(raw, (list, tuple, set, frozenset)):
        raise ValueError(f"dialect mapping {label} must be a list")
    if len(raw) > MAX_SPEC_ENTRIES:
        raise ValueError(f"dialect mapping {label} has too many entries")
    if any(not isinstance(one, str) or not one or len(one) > MAX_SPEC_NAME
           for one in raw):
        raise ValueError(f"dialect mapping {label} values must be non-empty strings")
    return list(raw)


@dataclass(frozen=True, slots=True)
class Placed:
    """One packet's readings, in archive column names."""

    #: Column name -> value. A value of None is a reading the console said it
    #: did not take; the caller drops those.
    record: dict[str, Any] = field(default_factory=dict)
    #: Which unit system `record` is in. The driver's, because the dialect
    #: decides it and only the driver has the dialect.
    usUnits: int = 1
    #: What the driver would have guessed about names it could not place, for
    #: the listener's proposal collector. Empty when nothing is inferred.
    proposals: tuple[Any, ...] = ()


def dialect_spec_of(driver: object, packet: Packet) -> dict[str, Any] | None:
    """The validated JSON description to persist beside one raw packet.

    A driver may put one on the packet itself or provide `dialect_spec`.
    Validation happens at this boundary, in the listener process. The same
    validation runs again when the archive reads it, because the live database
    is a file and files can be edited independently of this process.
    """
    if packet.dialect is None:
        return None
    if not valid_dialect_name(packet.dialect):
        return None
    found: object = packet.mapping
    if found is None:
        fn = getattr(driver, "dialect_spec", None)
        if fn is None:
            return None
        try:
            found = fn(packet.data, packet.dialect)
        except Exception:
            log.exception("driver could not describe its %r dialect", packet.dialect)
            return None
    if found is None:
        return None
    try:
        spec = found if isinstance(found, DialectSpec) else DialectSpec.from_dict(found)
        if type(packet.usUnits) is not int or packet.usUnits != spec.usUnits:
            raise ValueError("dialect mapping unit system disagrees with its packet")
    except (TypeError, ValueError, OverflowError):
        log.exception("driver returned an invalid description for %r", packet.dialect)
        return None
    return spec.as_dict()


def place_with(driver: object, readings: dict[str, Any], dialect: str,
               decisions: dict[str, str], infer: str = "off") -> Placed | None:
    """Ask a driver for listener-side proposals, or None if it cannot.

    This must stay out of the archive path: calling it there would execute
    third-party code in the process holding the archive database.
    """
    if driver is None:
        return None
    fn = getattr(driver, "place", None)
    if fn is None:
        return None
    try:
        found = fn(readings, dialect, decisions, infer)
    except Exception:
        log.exception("driver could not place a %r packet", dialect)
        return None
    return found if isinstance(found, Placed) else None


@dataclass(frozen=True, slots=True)
class Setup:
    """How somebody points a console at this driver.

    What the Senders page needs in order to offer a piece of hardware and
    then say what to type into it. A driver that says nothing gets the
    generic envelope text, which is what everything before this had.

    The values in `fields` and `notes` carry placeholders, filled in by
    whoever renders them:

        %(address)s   the host a console sends to, on its own
        %(port)s      the port, on its own
        %(base)s      the two as a URL, with the scheme and without a
                      redundant `:80` -- for a field that takes one string
        %(path)s      the upload path, token included where it carries one
        %(identity)s  what this sender is called, where we hand that out
        %(token)s     the upload token, for hardware with a field for it

    This process cannot know the first two: port publishing, NAT and any
    reverse proxy all sit between the console and us, and a container asked
    of its own socket answers with its bridge address in complete
    confidence. So the answer belongs to the page, which has the operator's
    setting for it. The last two are the page's for a different reason --
    they are per sender, and a driver is not.
    """

    #: What to call the protocol in a list: "Ecowitt", "Ambient Weather".
    label: str = ""
    #: The devices that speak it, as a sentence. This is what somebody
    #: standing over a box actually searches for -- they know they have a
    #: WS-2902, not that it speaks Weather Underground.
    hardware: str = ""
    #: `(label, value)` per line of what to type into the console. Empty
    #: means the hardware cannot be pointed anywhere and has to be adopted:
    #: a WeatherFlow hub broadcasts, and the two bridges have their endpoint
    #: burned into the firmware.
    fields: tuple[tuple[str, str], ...] = ()
    #: The steps around it, in the order somebody does them.
    notes: tuple[str, ...] = ()
    #: What the console calls itself with, if it brings its own identity.
    #: Empty means one can be handed out, which is the better arrangement:
    #: an identity somebody chooses can be chosen twice.
    identity: str = ""
    #: Where the token goes on this protocol: `path`, `password`, or empty
    #: for hardware that carries neither.
    secret: str = ""

    @property
    def tellable(self) -> bool:
        """Whether this hardware can be told where to upload."""
        return bool(self.fields)


def setup_of(driver: object) -> Setup | None:
    """How to point hardware at this driver, or None if it does not say.

    Optional, like `status` and `unit_groups`. The six push protocols each
    carry their own answer already -- what to type into the app, what the
    console names itself with, which of them cannot be pointed anywhere at
    all -- and before this nothing read any of it. The Senders page had a
    list of three written out by hand instead, so the four protocols that
    were not on it could not be set up from the page at all.
    """
    fn = getattr(driver, "setup", None)
    if fn is None:
        return None
    try:
        found = fn()
    except Exception:
        log.exception("driver setup failed")
        return None
    return found if isinstance(found, Setup) else None


@dataclass(frozen=True, slots=True)
class Step:
    """One stage of getting a piece of hardware recording here.

    A `Setup` says what somebody types into a console. This says the order
    they do things in, and it covers the two halves that were never in the
    same place: what to enter into the hardware, and what to enter here.

    That split is what made the ingest pages hard. A PurpleAir sensor is
    pointed at nothing and answers whoever asks, so setting one up is
    entirely a matter of telling *us* its address -- and that was a form on
    another page, reached from a different menu, with nothing on the sender
    page to suggest it existed. An Ecowitt is the mirror image. Both are one
    piece of hardware somebody is standing in front of.
    """

    #: A few words naming what this step accomplishes.
    title: str
    #: A sentence, where the title is not enough on its own.
    explain: str = ""
    #: `(label, value)` per line to type into the hardware, with the same
    #: placeholders `Setup.fields` uses.
    enter: tuple[tuple[str, str], ...] = ()
    #: Instructions, in the order somebody does them.
    notes: tuple[str, ...] = ()
    #: This driver's own option names, asked here instead of on a settings
    #: page somewhere else. Names rather than the options themselves: what
    #: they are is `options()`, and repeating it would be the same fact in
    #: two places, one of which goes stale.
    settings: tuple[str, ...] = ()
    #: Whether this step ends by watching for the first reading to arrive.
    #: The one step that checks rather than instructs.
    listens: bool = False


def option_names(driver: object) -> tuple[str, ...]:
    """Every setting this driver declares, in the order it declares them."""
    describe = getattr(type(driver), "options", None) or getattr(
        driver, "options", None)
    if describe is None:
        return ()
    try:
        groups = describe() or ()
    except Exception:
        log.exception("driver options failed")
        return ()
    found = []
    for group in groups:
        for one in getattr(group, "options", ()) or ():
            name = getattr(one, "name", "")
            if name:
                found.append(str(name))
    return tuple(found)


def steps_of(driver: object) -> tuple[Step, ...]:
    """How this driver is set up, guided. Its own answer, or one derived.

    Derived rather than required, for the reason `plots.implied` is: a
    sequence written into every driver is a sequence that cannot be improved
    afterwards. Six protocols already say everything the ordinary one needs
    -- what to type in, what cannot be told anything, what to configure --
    and a driver written before this existed gets a wizard without being
    touched.

    A driver whose setup is genuinely different says `steps()` and that is
    used unchanged. Nothing here is merged into it: half a derived sequence
    and half a written one would be an order nobody chose.
    """
    fn = getattr(driver, "steps", None)
    if fn is not None:
        try:
            found = fn()
        except Exception:
            log.exception("driver steps failed")
            found = None
        if found:
            return tuple(one for one in found if isinstance(one, Step))

    said = setup_of(driver)
    settings = option_names(driver)
    steps: list[Step] = []

    if settings:
        # First, because the rest may depend on it: a driver that has to be
        # told an address cannot be told to wait for a reading first.
        steps.append(Step(
            title="Settings", settings=settings,
            explain="What this driver needs to know."))

    if said is not None and (said.fields or said.notes):
        steps.append(Step(
            title=("Enter this into the hardware" if said.tellable
                   else "Point the hardware here"),
            enter=said.fields, notes=said.notes,
            explain=("" if said.tellable else
                     "This hardware cannot be told where to upload.")))

    steps.append(Step(
        title="Wait for the first reading", listens=True,
        explain="Nothing is set up until something has arrived."))
    return tuple(steps)


def response_of(driver: object) -> Response:
    """What to answer an upload to this driver with."""
    return getattr(driver, "response", None) or DEFAULT_RESPONSE


def status_of(driver: object) -> dict[str, Any]:
    fn = getattr(driver, "status", None)
    if fn is None:
        return {}
    try:
        return fn() or {}
    except Exception:
        log.exception("driver status failed")
        return {}


def groups_of(driver: object) -> dict[str, str]:
    """Which unit group each of this driver's fields belongs to.

    Optional, like `status`. A driver that reports nothing but the standard
    schema has nothing to say here; one that reports soil conductivity, four
    extra thermometers and the signal strength of every sensor is the only
    thing that knows what those columns measure.
    """
    fn = getattr(driver, "unit_groups", None)
    if fn is None:
        return {}
    try:
        return dict(fn() or {})
    except Exception:
        # A driver that cannot answer must not stop the ones that can, and
        # must not stop the process either. What it costs is unconverted
        # numbers on a page, which is what happens without it anyway.
        log.exception("driver unit_groups failed")
        return {}


class _FunctionDriver(BaseDriver):
    """Wraps a plain `(body, meta) -> packets` function."""

    def __init__(self, fn: Callable[[bytes, dict], list[Packet]],
                 response: Response = DEFAULT_RESPONSE) -> None:
        self._fn = fn
        self.response = response

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        return self._fn(body, meta)


def _parsed(factory: Callable[..., object],
            options: dict[str, Any]) -> dict[str, Any]:
    """Options in the shape the driver declared, not the shape the file had.

    A driver says `kind="duration"` and then gets handed the string `"4h"`,
    because that is what is written in the configuration file. Every driver
    parsing its own values again is the thing the option schema exists to
    stop, and one that forgets gets a `ValueError` at startup -- caught, and
    then quietly running on its default.

    So the driver's own declaration is applied here, once. Anything the schema
    cannot make sense of is dropped rather than passed on, so the driver
    falls back to its own default and the station keeps recording. Said
    loudly, because the setting is not doing what whoever wrote it thinks.
    """
    from ..options import schema_of

    schema = schema_of(factory, name="driver", label="driver")
    if schema is None:
        return options

    out = dict(options)
    for _group, option in schema:
        if option.name not in out:
            continue
        try:
            out[option.name] = option.parse(out[option.name])
        except Exception as exc:
            log.warning("driver setting %s = %r is not usable (%s);"
                        " falling back to the default, %r", option.name,
                        out[option.name], exc, option.default)
            del out[option.name]
    return out


class Registry:
    """The drivers this installation has.

    Instances, not classes: a driver holds parser configuration and protocol
    state, and those have to survive between uploads. Place-specific field
    mappings are downstream data and never belong to this registry.
    """

    def __init__(self) -> None:
        self._drivers: dict[str, object] = {}
        self._factories: dict[str, Callable[..., object]] = {}
        self._aliases: dict[str, list[str]] = {}
        self._loaded = False

    def register(self, name: str, driver: object, replace: bool = False) -> None:
        if name in self._drivers and not replace:
            raise ValueError(f"a driver named {name!r} is already registered")
        if callable(driver) and not hasattr(driver, "packets"):
            driver = _FunctionDriver(driver)  # type: ignore[arg-type]
        self._drivers[name] = driver

    def register_factory(self, name: str, factory: Callable[..., object],
                         aliases: tuple[str, ...] = ()) -> None:
        """Register something to be built when its configuration is known.

        `aliases` are other names for the same driver -- a second protocol it
        also reads. Configuring one configures all of them, and they share the
        instance: two instances would each adopt a station and each keep their
        own idea of which one it is.
        """
        self._factories[name] = factory
        for alias in aliases:
            self._factories[alias] = factory
            self._aliases.setdefault(name, []).append(alias)

    def configure(self, name: str, options: dict[str, Any]) -> object | None:
        """Build a registered factory with its options, and install the result."""
        factory = self._factories.get(name)
        if factory is None:
            return self._drivers.get(name)
        options = _parsed(factory, options)
        try:
            driver = factory(**options)
        except Exception:
            log.exception("driver %r could not be configured; leaving it out", name)
            return None
        self._drivers[name] = driver
        for alias in self._aliases.get(name, ()):
            self._drivers[alias] = driver
        return driver

    def get(self, name: str) -> object | None:
        self.load()
        return self._drivers.get(name)

    def known(self, name: str) -> bool:
        self.load()
        return name in self._drivers or name in self._factories

    def names(self) -> list[str]:
        self.load()
        return sorted(set(self._drivers) | set(self._factories))

    def canonical_names(self) -> list[str]:
        """Names that are not an alias of another driver.

        Configuring an alias would build a second instance of the same driver,
        and two instances each adopt a station and each keep their own list.
        """
        self.load()
        aliased = {alias for aliases in self._aliases.values() for alias in aliases}
        return [name for name in self.names() if name not in aliased]

    def aliases_of(self, name: str) -> list[str]:
        return list(self._aliases.get(name, ()))

    def claimant(self, body: bytes, meta: dict) -> str | None:
        """Which driver recognises this upload, or None.

        Canonical names only and sorted, so two drivers that answer with the
        same confidence resolve the same way on every start rather than by
        whatever order the registry happened to fill up in.

        A driver that raises here is passed over rather than allowed to decide
        which protocol every other upload is. This is a guess being made about
        an unidentified payload; it must never be the thing that stops one
        being read.
        """
        best, chosen = 0.0, None
        for name in sorted(self.canonical_names()):
            driver = self.get(name)
            fn = getattr(driver, "claims", None)
            if fn is None:
                continue
            try:
                sure = float(fn(body, meta) or 0.0)
            except Exception:
                log.exception("driver %r failed while identifying an upload", name)
                continue
            if sure > best:
                best, chosen = sure, name
        return chosen

    def unit_groups(self) -> dict[str, str]:
        """What every driver here says about its own fields, in one table.

        Canonical names only: an alias shares its driver's instance, and
        asking twice would only merge the same answer into itself.

        Two drivers claiming the same field with different groups is possible
        and not worth arbitrating: the last one wins, sorted by name so the
        answer is at least the same on every start. Two stations reporting the
        same column in different quantities is a configuration problem, and
        one that shows up as a wrong unit rather than as silence.
        """
        merged: dict[str, str] = {}
        for name in sorted(self.canonical_names()):
            merged.update(groups_of(self.get(name)))
        return merged

    def close(self) -> None:
        for driver in self._drivers.values():
            fn = getattr(driver, "close", None)
            if fn is not None:
                try:
                    fn()
                except Exception:
                    log.exception("driver close failed")

    def load(self) -> None:
        """Pull in what is installed. A broken plugin is reported, never fatal.

        One package failing to import must not take the listener down: the
        other protocols still have measurements arriving, and losing all of
        them over one bad dependency is by far the worse outcome.
        """
        if self._loaded:
            return
        self._loaded = True

        # Before the entry points are walked, never after: an add-on lives in
        # the data directory so that it outlives the container it was
        # installed from, and a distribution is found by looking along
        # `sys.path` for its `.dist-info`. Without this it is installed and
        # invisible, which is indistinguishable from not installed.
        try:
            from .. import addons

            addons.on_path()
        except Exception:
            log.debug("could not add the add-on directory to the path",
                      exc_info=True)

        from importlib.metadata import entry_points

        for entry in entry_points(group=ENTRY_POINT_GROUP):
            try:
                loaded = entry.load()
                if isinstance(loaded, type):
                    self.register_factory(entry.name, loaded)
                    self._drivers.setdefault(entry.name, loaded())
                else:
                    self.register(entry.name, loaded, replace=True)
                log.info("driver %r from %s", entry.name, entry.value)
            except Exception:
                log.exception("could not load the driver %r; carrying on without it",
                              entry.name)

        # The envelope, which is not a driver: it is the door every collector
        # delivers through, so it is always here and an add-on cannot displace
        # it. Registered after the entry points for exactly that reason.
        from .envelope import EnvelopeDriver

        self.register("json", EnvelopeDriver(), replace=True)

        from . import userdrivers

        userdrivers.load(self)


#: The registry the listener uses unless it is given another.
DEFAULT = Registry()


def register(name: str, driver: object, replace: bool = False) -> None:
    DEFAULT.register(name, driver, replace=replace)


def get(name: str) -> object | None:
    return DEFAULT.get(name)


def known(name: str) -> bool:
    return DEFAULT.known(name)


def names() -> list[str]:
    return DEFAULT.names()

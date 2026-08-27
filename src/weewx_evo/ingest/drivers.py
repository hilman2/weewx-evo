"""What a driver is, and what the core does not get to know.

The split is the whole architecture, so it is worth stating flatly:

**The core owns the socket.** Threads, shutdown, body limits, IPv6, the token
check, and writing to the live table. Those are the same for every protocol,
they are where push drivers go wrong, and doing them once is doing them once.

**The driver owns everything else.** Parsing, field names, units, which device
it will answer to, and what that device needs to hear back. It hands over a
finished packet. The core does not inspect it, does not know what an Ecowitt
is, and cannot be made to care.

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

import logging
from collections.abc import Callable
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


class BaseDriver:
    """A driver that only needs to parse. Defaults for everything else."""

    #: What the hardware wants to hear. Override for anything that checks.
    response: Response = DEFAULT_RESPONSE

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        """Whatever the driver wants reported at /status. Optional."""
        return {}

    def close(self) -> None:
        """Release anything held. Optional."""


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

    Instances, not classes: a driver holds configuration and state -- which
    consoles it answers to, which field map belongs to which of them -- and
    that has to survive between uploads.
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

        from . import plugins
        plugins.load(self)


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

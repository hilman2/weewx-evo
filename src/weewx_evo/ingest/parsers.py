"""The parser registry.

A parser gets bytes and returns packets. It does not touch a database, open a
socket, or know what time it is unless the payload says so. That is what makes
a protocol testable against a saved capture -- and captures are the only honest
test here, because consoles do not send what their documentation says.

**The core knows no weather protocol.** It knows its own JSON envelope, which
is the contract, not a protocol. Everything a station actually speaks --
Ecowitt, Weather Underground, whatever comes next -- arrives as a plugin.

That is not tidiness. Field lists are the hard part of this whole business and
they change faster than releases: a current HP2561AE Pro sends 45 fields, and
`weewx-interceptor` maps 25 of them. Whoever keeps up with that has to be able
to ship without waiting for the core, and the core must not hold a second,
worse copy of their work.

Registering one, in a plugin package's pyproject.toml:

    [project.entry-points."weewx_evo.parsers"]
    ecowitt = "my_package:parse"

Or, in code:

    from weewx_evo.ingest.parsers import register
    register("ecowitt", parse)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from ..db.live import Packet
from ..units import METRICWX

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "weewx_evo.parsers"

#: A parser: (body, meta) -> packets. `meta` carries at least `received`, the
#: arrival time as a unix timestamp, and `source`, the peer it came from.
Parser = Callable[[bytes, dict], "list[Packet]"]

_PARSERS: dict[str, Parser] = {}
_LOADED = False


def register(name: str, parser: Parser, replace: bool = False) -> None:
    """Make a parser available under `name`."""
    if name in _PARSERS and not replace:
        raise ValueError(f"a parser named {name!r} is already registered")
    _PARSERS[name] = parser


def parse_json(body: bytes, meta: dict) -> list[Packet]:
    """weewx-evo's own envelope. This is the contract every driver can rely on.

    One object or a list of them:

        {"dateTime": 1787734265, "usUnits": 1, "source": "vantage-1",
         "kind": "loop", "interval": null, "data": {"outTemp": 21.4}}

    `data` may also be flattened into the object itself, which is what a
    hand-written driver tends to produce. Field names are WeeWX's, and
    `usUnits` is a WeeWX unit constant: a parser's job is to have already
    decided both.
    """
    payload = json.loads(body)
    items = payload if isinstance(payload, list) else [payload]

    packets = []
    for item in items:
        data = item.get("data")
        if data is None:
            reserved = {"dateTime", "usUnits", "source", "kind", "interval", "received"}
            data = {k: v for k, v in item.items() if k not in reserved}
        packets.append(Packet(
            dateTime=int(item.get("dateTime") or meta["received"]),
            usUnits=int(item.get("usUnits", METRICWX)),
            data=data,
            source=str(item.get("source") or meta.get("source", "json"))[:64],
            kind=item.get("kind", "loop"),
            interval=item.get("interval"),
        ))
    return packets


register("json", parse_json)


def _load_plugins() -> None:
    """Pull in whatever is installed. Failures are reported, never fatal.

    A plugin that will not import must not stop the listener: the other
    protocols still have measurements coming in, and losing all of them
    because one package is broken is the worse outcome by far.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    from importlib.metadata import entry_points

    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            register(entry.name, entry.load(), replace=True)
            log.info("parser %r from %s", entry.name, entry.value)
        except Exception:
            log.exception("could not load the parser %r; carrying on without it",
                          entry.name)

    # Bundled adapters for drivers that are not packaged for us yet. Each is
    # optional and silent when its driver is absent.
    from . import plugins
    plugins.load()


def get(name: str) -> Parser | None:
    _load_plugins()
    return _PARSERS.get(name)


def names() -> list[str]:
    _load_plugins()
    return sorted(_PARSERS)


def known(name: str) -> bool:
    _load_plugins()
    return name in _PARSERS

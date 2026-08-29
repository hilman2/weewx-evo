"""Collectors: the things that go and fetch, named and configured.

A parser waits for a device to upload; a collector goes and reads one. The
difference costs a process, and that is deliberate -- `ingest/weewxshim.py`
explains why a serial port that stops answering must not be able to stop the
archiver.

What was missing was everything around it. A WeeWX driver ran only as six
command-line arguments typed into a unit file, so it had no page on the
settings site, nothing to name it in the configuration, and -- the part that
mattered -- **no name of its own where it arrived**.

That last one is the whole point of this module. Packets from a collector
went in at `/<token>/json/`, so as far as the listener was concerned the
driver was called `json`:

    stations.toml:  driver = "json"     identity = "WH1080 (USB)"

Which works, and is wrong in the way that costs an afternoon: a second
collector would be `json` too, `stations.by_identity()` would match on the
identity alone, and two consoles would be one station. Everything downstream
-- the role that moves a second station's readings into `extraTemp3`, the
archive it writes to, whether its indoor readings are kept -- hangs off that
pair.

So a configured collector claims its own name at the listener:

    [collectors.shed]
    kind = "weewx-driver"
    conf = "/etc/weewx/weewx.conf"

and its packets arrive at `/<token>/shed/`, as `driver = "shed"`. The
listener registers the name because the *configuration* has it, not because
a plugin is installed: the collector is somewhere else entirely, possibly on
another machine, and the listener never imports a line of it.

**The process stays separate.** This is configuration and a name, not an
embedding. `weewx-evo weewx-driver run --collector shed` reads its settings
from the file instead of from arguments, and still runs where the hardware
is.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

#: What a collector can be. Two so far, and they differ only in what they go
#: and read: the naming, the endpoint and the settings page are the same
#: problem either way, which is all of what this module does. A third -- a
#: script that prints envelopes -- would add a line here and nothing else.
KINDS = {
    "weewx-driver": "A WeeWX driver, running in its own process",
    "mqtt": "A broker to subscribe to, in its own process",
}

#: Names that would collide with something the listener already answers to.
#: A collector called `json` would take the envelope endpoint's name, and a
#: collector called `ecowitt` would take a real driver's -- in both cases the
#: uploads would still arrive and be recorded under the wrong driver, which
#: is exactly the confusion this module exists to end.
def reserved(registry: Any = None) -> set[str]:
    """Names already spoken for, so a new collector cannot take one."""
    from .ingest import drivers

    known = registry or drivers.DEFAULT
    try:
        return {name.casefold() for name in known.names()}
    except Exception:
        # A registry that has not loaded yet. Better to allow the name and
        # let `register_names` decline it later than to refuse every name.
        log.debug("could not list driver names", exc_info=True)
        return {"json"}


def configured(settings: Any) -> dict[str, dict]:
    """The collectors in the configuration, by name.

    `Settings.config` is the parsed file, which is where every other named
    section is read from -- exports, feeds, uploads all do exactly this. A
    plain dict is accepted too, because `all_schemas` has the file and not a
    Settings when it builds the pages.
    """
    if settings is None:
        return {}
    section = (settings if isinstance(settings, dict)
               else getattr(settings, "config", {}) or {}).get("collectors")
    return {str(name): dict(one) for name, one in (section or {}).items()
            if isinstance(one, dict)}


def describe(kind: str) -> str:
    return KINDS.get(kind, "A collector")


def register_names(registry: Any, settings: Any) -> list[str]:
    """Give each configured collector its own endpoint at the listener.

    The parser behind every one of them is the envelope -- a collector sends
    the same JSON whatever it read, which is the contract that lets one be
    written in Go. What differs is only the *name*, and the name is what
    `stations.by_identity(driver, source)` matches on.

    A name already taken is declined and said out loud rather than replaced.
    Quietly winning would mean a collector shadowing the Ecowitt endpoint,
    and the uploads that used to be parsed as Ecowitt arriving as envelopes
    it cannot read.
    """
    from .ingest.envelope import EnvelopeDriver

    taken = reserved(registry)
    claimed = []
    for name, one in sorted(configured(settings).items()):
        if str(one.get("kind", "")).strip() not in KINDS:
            continue
        if name.casefold() in taken:
            log.warning(
                "collector %r cannot have that name: something already "
                "answers to it. Its packets would be recorded under the "
                "wrong driver; rename it in the configuration.", name)
            continue
        registry.register(name, EnvelopeDriver())
        claimed.append(name)
    if claimed:
        log.info("collectors with their own endpoint: %s", ", ".join(claimed))
    return claimed


def options(kind: str = "weewx-driver") -> list:
    """One collector's settings, for its page.

    Per kind, because they have almost nothing in common: a WeeWX driver is
    a `weewx.conf` and a serial port, a broker is an address and a map from
    topics to field names. One page carrying both would ask a broker for its
    catch-up interval and a USB console for its topic filter, and every
    field somebody has to work out is not theirs is a field they might fill
    in.

    What *is* shared is the first group, and it is the only thing that has
    to be: the kind decides the rest, so it has to be answerable before the
    rest is drawn.

    `conf` is a WeeWX configuration file and not a copy of its contents. The
    settings a driver needs -- the serial port, the model, the sensor map --
    were working before this existed, and copying them here would mean
    maintaining a second place for them and getting the translation wrong for
    the drivers nobody here can test.
    """
    from .options import Group, Option

    kind = kind if kind in KINDS else "weewx-driver"
    which = Group("The collector", "What this one is.", (
        Option("kind", "What kind of collector this is",
               kind="choice", default=kind, choices=tuple(KINDS.items()),
               help="Both run in their own process and deliver over the "
                    "loopback, so a serial port or a broker that stops "
                    "answering cannot stop the archiver."),
    ))

    if kind == "mqtt":
        from .ingest import mqttsub

        return [
            which,
            Group("The broker", "Where it is, and what to listen to.",
                  tuple(one for one in mqttsub.options()
                        if one.name != "unit_system")),
            Group("The readings", "What the topics mean.", (
                Option("source", "Record its readings under this name",
                       kind="text", default="",
                       help="Empty means the collector's own name. This is "
                            "the identity a station is matched on, so it is "
                            "what to announce on the Stations page."),
                Option("unit_system", "Units the broker publishes in",
                       kind="choice", default="metricwx",
                       choices=(("metricwx", "Celsius, mm, m/s"),
                                ("metric", "Celsius, cm, km/h"),
                                ("us", "Fahrenheit, inches, mph")),
                       help="A broker states no units. Getting this wrong "
                            "writes Fahrenheit into a Celsius column, and "
                            "nothing downstream can tell."),
            )),
        ]

    return [
        which,
        Group("What it runs", "The driver, and where its settings are.", (
            Option("conf", "The weewx.conf it is configured by",
                   kind="path", default="/etc/weewx/weewx.conf",
                   help="Its own file. The driver reads its settings from "
                        "the section named after it -- serial port, model, "
                        "sensor map -- and those are not copied here."),
            Option("driver", "The driver module, if not the one it names",
                   kind="text", default="",
                   help="For example weewx.drivers.vantage. Empty means the "
                        "one [Station] station_type points at."),
            Option("driver_file", "Load the driver from this file",
                   kind="path", default="",
                   help="A driver is one file. With this set, WeeWX itself "
                        "does not have to be installed: what the file "
                        "imports is stood in for."),
        )),
        Group("The console", "What it is, and what it keeps.", (
            Option("source", "Record its readings under this name",
                   kind="text", default="",
                   help="Empty means the driver's own hardware name. This is "
                        "the identity a station is matched on, so it is what "
                        "to announce on the Stations page."),
            Option("catchup", "Fetch this much of the console's own log at "
                              "startup",
                   kind="duration", default=0,
                   help="For hardware that keeps its own records. This is "
                        "what turns an outage into a filled gap rather than "
                        "a lost one. Zero for hardware that logs nothing."),
            Option("batch", "Seconds of packets per delivery",
                   kind="duration", default=5,
                   help="One request per loop packet is a round trip every "
                        "two seconds for readings that are aggregated at the "
                        "end of the interval anyway."),
        )),
    ]


def settings_for(settings: Any, name: str) -> dict:
    """One collector's settings, or {} if there is no such collector."""
    return configured(settings).get(name, {})


def endpoint(name: str) -> str:
    """The path a collector delivers to, without the token."""
    return f"/{name}/"

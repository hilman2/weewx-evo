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
-- which place selects it, the member policy that moves its readings into
`extraTemp3`, whether that place keeps its indoor readings -- starts with that
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
from typing import Any, NamedTuple

log = logging.getLogger(__name__)


class Kind(NamedTuple):
    """One sort of collector: what it is called, what it reads, how to run it.

    The command is in here rather than on the page because the page is not
    the only place that has to say it, and the two kinds are started by two
    different commands. Written out once, the "Add a collector" page said
    the WeeWX one whichever kind was chosen -- and `weewx-evo mqtt run` is
    the other, as the CLI itself says when it refuses the wrong one.
    """

    label: str
    reads: str
    command: str


#: What a collector can be. Two so far, and they differ only in what they go
#: and read: the naming, the endpoint and the settings page are the same
#: problem either way, which is all of what this module does. A third -- a
#: script that prints envelopes -- would add a line here and nothing else.
#: Which is the point of `reads` being here: the page draws its list from
#: this, so a third kind cannot arrive in the menu and be missing from the
#: explanation under it. That is exactly what happened to MQTT.
KINDS = {
    "weewx-driver": Kind(
        "A WeeWX driver, running in its own process",
        "Any of the hundred-odd drivers written for WeeWX, unchanged -- a "
        "serial console, one on the USB bus, a radio. WeeWX itself does not "
        "have to be installed: point at the driver file and what it imports "
        "is stood in for.",
        "weewx-driver run"),
    "mqtt": Kind(
        "A broker to subscribe to, in its own process",
        "Readings a broker already carries, from a console that publishes "
        "them itself or from a home-automation system. The command "
        "weewx-evo mqtt check prints what a broker publishes, which is how "
        "the topic names its page asks for are found.",
        "mqtt run"),
}

#: Where a hosted driver's own settings sit, under the collector's section.
#:
#: In the option *name* rather than as a group prefix, and that is not a
#: detail: a form field is addressed by the option's name alone, so two
#: options called `source` -- one ours, one the driver's -- would be two
#: fields of the same name in one form. The browser sends both, one wins by
#: the order they were parsed in, and both settings get that value. The core
#: options do the same thing for the same reason (`station.name`).
#:
#: None of the thirteen drivers WeeWX ships collides today. That is not a
#: reason: the point of this whole module is the hundred drivers written
#: elsewhere, which nobody here can read.
PREFIX = "settings"

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


def describe(kind: str, name: str = "") -> str:
    """What a collector is, and -- given its name -- how it is started.

    Named, it says the command, because the settings page never does. A
    collector's page is generated from its schema like any other, and the
    schema's help goes into the configuration file rather than onto the
    page -- so somebody redirected there after creating one saw a form and
    nothing about the process it configures, which is a process this program
    does not start.
    """
    one = KINDS.get(kind)
    if one is None:
        return "A collector"
    if not name:
        return one.label
    # Three lines rather than a sentence: the command is the useful half and
    # it has to be copyable, which it is not when a wrap lands in the middle
    # of it. The file writer wraps each line of this on its own.
    return (f"{one.label}.\n"
            f"Nothing here starts it. Where the hardware is, run:\n"
            f"weewx-evo {one.command} --collector {name}")


def start_command(kind: str, name: str = "<name>") -> str:
    """What to type where the hardware is, for this kind of collector."""
    one = KINDS.get(kind) or KINDS["weewx-driver"]
    return f"weewx-evo {one.command} --collector {name}"


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


def options(kind: str = "weewx-driver", settings: dict | None = None) -> list:
    """One collector's settings, for its page.

    Per kind, because they have almost nothing in common: a WeeWX driver is
    a serial port and a model, a broker is an address and a map from topics
    to field names. One page carrying both would ask a broker for its
    catch-up interval and a USB console for its topic filter, and every
    field somebody has to work out is not theirs is a field they might fill
    in.

    What *is* shared is the first group, and it is the only thing that has
    to be: the kind decides the rest, so it has to be answerable before the
    rest is drawn. `settings` is what is already stored, and it decides the
    rest again one level down -- which driver was chosen decides which
    fields that driver has.

    **A driver's own settings are asked for here now, and that is a change
    of position.** They used to be reached only through `conf`, a path to a
    `weewx.conf`, on the grounds that copying them here would mean keeping a
    second copy of something the driver already says. The grounds were right
    and the conclusion did not follow: `weewxdrivers.py` does not copy them,
    it reads them out of the driver, so the second copy never exists. What
    the old arrangement cost was the thing `weewxnames.py` was built for --
    somebody with one USB console and no WeeWX had to write a configuration
    file for software that is not installed.

    `conf` stays, and a path in it wins. An installation that has a working
    `weewx.conf` keeps using it, untouched.
    """
    from .options import Group, Option

    kind = kind if kind in KINDS else "weewx-driver"
    which = Group("The collector", "What this one is.", (
        Option("kind", "What kind of collector this is",
               kind="choice", default=kind,
               choices=tuple((name, one.label) for name, one in KINDS.items()),
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

    stored = dict(settings or {})
    chosen = str(stored.get("driver") or "").strip()
    return [
        which,
        Group("The hardware", "What it reads, and how it is reached.", (
            Option("driver", "The hardware this collector reads",
                   kind="choice", default="",
                   choices=(("", "-- from a weewx.conf --"),),
                   choices_from=lambda: _hardware_choices(chosen),
                   help="Every WeeWX driver on this machine. Choosing one "
                        "and saving brings up its own settings below, read "
                        "out of the driver itself."),
            Option("conf", "The weewx.conf it is configured by",
                   kind="path", default="",
                   when=("driver", ("",)),
                   help="For an installation that already has one. The "
                        "driver reads its settings from the section named "
                        "after it, and nothing here touches that file."),
            Option("driver_file", "Load the driver from this file",
                   kind="path", default="",
                   help="A driver is one file. With this set, WeeWX itself "
                        "does not have to be installed: what the file "
                        "imports is stood in for."),
        )),
        *_hardware_settings(chosen),
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


def _hardware_choices(chosen: str = "") -> list[tuple[str, str]]:
    """Every WeeWX driver on this machine, for the hardware list.

    `chosen` is what is configured now, and it is always in the list even
    when nothing on disk answers to it any more. A driver file that was
    removed would otherwise take its own setting with it: the page would
    refuse the stored value as one that is not offered, fall back to the
    default, and the collector would quietly become one reading a weewx.conf
    that may not exist. That is the `archive_names` failure -- the page
    telling the operator that the truth is a mistake.
    """
    from .ingest import weewxdrivers

    out: list[tuple[str, str]] = []
    for one in weewxdrivers.available(_driver_directory()):
        if one.problem:
            label = f"{one.name} -- {one.problem}"
        elif one.needs:
            label = f"{one.name} ({one.module}), needs {one.needs}"
        else:
            label = f"{one.name} ({one.module})"
        out.append((one.module, label))
    if chosen and chosen not in [value for value, _ in out]:
        out.append((chosen, f"{chosen} -- not found on this machine"))
    return out


def _driver_directory() -> Any:
    """Where WeeWX driver files are kept, for the file the form describes.

    Through `options._current_config` and not through `settings.running()`.
    The settings page can be its own process (`weewx-evo admin`) and builds
    forms for a named file, so a list read off the running settings would be
    a list of what some other file has -- which is the mistake `building_for`
    exists to prevent, and it has been made twice before.
    """
    from pathlib import Path

    from . import archives as archive_defs
    from . import config as config_file
    from . import options as option_defs
    from .ingest import weewxdrivers

    current = option_defs._current_config() or {}
    for_file = option_defs._config_path()
    base = Path(str(for_file)).parent if for_file else Path(".")

    class Saved:
        def get(self, name: str, default: Any = None) -> Any:
            value = config_file.get(current, name)
            return default if value in (None, "") else value

    register = archive_defs.Register.load(base / archive_defs.FILENAME, Saved())
    beside = register.get(None).file
    # A relative path counts against the file it is written in, not against
    # whatever directory this process was started in. `Settings._anchor` is
    # the same rule and says why: `archive_db = "weewx.sdb"` otherwise names
    # two different files, and the page acts on the one the service is not
    # using -- while reporting success. Here the symptom would be a hardware
    # list that is empty on an installation whose drivers are right there.
    found = Path(str(beside))
    if not found.is_absolute():
        if for_file:
            found = base / found
    return weewxdrivers.directory(beside=found)


def _hardware_settings(module: str) -> list:
    """One group holding the chosen driver's own options, or none.

    The whole point of the module behind it: these are not written down here.
    They are what the driver's own configuration editor describes, and a
    driver that gains an option gains a field with no change on this side.
    """
    if not module:
        return []
    from .ingest import weewxdrivers
    from .options import Group, Option

    found = weewxdrivers.by_module(module, _driver_directory())
    if found is None:
        return [Group(
            "The hardware's own settings",
            f"{module} is not on this machine, so its settings cannot be "
            f"read. Install it, or point at its file above.", ())]
    if found.problem:
        return [Group("The hardware's own settings", found.problem, ())]

    made = []
    for one in found.settings:
        # The driver's author wrote this comment above this option. It is the
        # help text, and it is worth more than anything that could be written
        # here: it is current, and it is about this version of this driver.
        help_text = " ".join(one.help)
        made.append(Option(
            f"{PREFIX}.{one.name}",
            # The option's own name as the label. A driver says `iss_id` and
            # its documentation says `iss_id`; renaming it to "ISS identifier"
            # would mean the field and every answer written about it disagree.
            one.name,
            kind="choice" if one.choices else "text",
            default=one.value,
            help=help_text,
            choices=one.choices,
            advanced=one.advanced,
            when=((f"{PREFIX}.{one.when[0]}", one.when[1])
                  if one.when else None),
            suggestions_from=(weewxdrivers.serial_ports
                              if one.name == "port" else None),
        ))
    note = found.about or (
        f"Read out of {found.module}, which is where they are defined.")
    if found.needs:
        note += (f" It reaches its hardware through {found.needs}, which has "
                 f"to be installed where this collector runs.")
    # No group prefix: the names carry it, because a form field is addressed
    # by the option's name alone. See PREFIX.
    return [Group(f"{found.name}", note, tuple(made))]


def settings_for(settings: Any, name: str) -> dict:
    """One collector's settings, or {} if there is no such collector."""
    return configured(settings).get(name, {})


def driver_settings(settings: Any, name: str) -> dict:
    """What was chosen for the driver itself, under its own prefix.

    Separate from the collector's own settings because the names are the
    driver's: a driver with an option called `source` or `batch` would
    otherwise take one of ours, and which of the two won would depend on the
    order a dictionary happened to be built in.
    """
    found = settings_for(settings, name).get(PREFIX)
    return dict(found) if isinstance(found, dict) else {}


def endpoint(name: str) -> str:
    """The path a collector delivers to, without the token."""
    return f"/{name}/"

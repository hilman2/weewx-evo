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
embedding. `weewx-evo-weewx-driver run --collector shed` reads its settings
from the file instead of from arguments, and still runs where the hardware
is. The command belongs to whatever provides the kind -- that one is an
add-on's, and nothing here puts a program name in front of it.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

log = logging.getLogger(__name__)


class Choice(NamedTuple):
    """Something to pick while a collector of one kind is being created.

    Asked on the "add" page rather than on the page after, and that is not a
    preference: which WeeWX driver was chosen decides which fields that
    driver's page has, so leaving it until then means arriving at a form with
    nothing on it -- and the driver's own settings are what somebody came for.

    The core renders it and knows nothing about what is in it. It used to
    call the WeeWX hardware list directly, which meant the page could not be
    drawn at all once that moved into an add-on.
    """

    #: The form field's name, which is also the setting it becomes.
    name: str
    label: str
    help: str
    #: `picked -> list[(value, label)]`. The empty value comes first if the
    #: kind wants one; nothing here supplies it.
    options: Any


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
    #: The whole command, program name included: `weewx-evo mqtt run`, or
    #: `weewx-evo-weewx-driver run` for one an add-on brings. Nothing is put
    #: in front of it. It held only the subcommand while every kind was one
    #: of this program's, and an add-on's own command then came out as
    #: "weewx-evo weewx-evo-weewx-driver run" -- printed on the page that
    #: exists to say what to type, for a command that is not on any machine.
    command: str
    #: `settings -> list[Group]`, the page below the shared first group.
    #: A kind with nothing of its own leaves it None.
    #:
    #: A callable rather than a list, for two reasons that are the same
    #: reason: the fields depend on what is already stored -- which driver
    #: was chosen decides which fields that driver has -- and a kind
    #: contributed by an add-on must not be asked for its options while the
    #: entry points are being walked, or every collector add-on installed
    #: would be imported to draw any page.
    options: Any = None
    #: A `Choice` to make while creating one, or None for a kind that has
    #: nothing to decide before its own page.
    choosing: Any = None


#: The entry point an add-on contributing a kind of collector declares.
#: Same shape as the driver one: a name, and something that answers.
ENTRY_POINT_GROUP = "weewx_evo.collectors"

_contributed: dict[str, Kind] | None = None


def kinds() -> dict[str, Kind]:
    """What a collector can be here: the core's own, and what is installed.

    Asked rather than listed, for the reason the drivers are: what a machine
    can collect from is what somebody installed on it. Running a WeeWX driver
    is an add-on now -- it carries the shim, the stand-ins and the form read
    out of a driver file, which is 2 100 lines that a station with an Ecowitt
    on the wifi has no use for.

    A kind that will not load is reported and left out. The page still has to
    render: an add-on that breaks must cost its own line and not the ability
    to configure anything at all.
    """
    global _contributed
    if _contributed is None:
        from importlib.metadata import entry_points

        # Same reason as in `drivers.Registry.load`: an add-on installed into
        # the data directory is found by looking along `sys.path`, and this
        # is the other place that looks.
        try:
            from . import addons

            addons.on_path()
        except Exception:
            log.debug("could not add the add-on directory to the path",
                      exc_info=True)

        found: dict[str, Kind] = {}
        for entry in entry_points(group=ENTRY_POINT_GROUP):
            try:
                one = entry.load()
                one = one() if callable(one) and not isinstance(one, Kind) else one
                if isinstance(one, Kind):
                    found[entry.name] = one
                else:
                    log.warning("the collector kind %r did not answer with a "
                                "Kind; leaving it out", entry.name)
            except Exception:
                log.exception("could not load the collector kind %r; carrying "
                              "on without it", entry.name)
        _contributed = found
    return {**KINDS, **_contributed}


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
    one = kinds().get(kind)
    if one is None:
        return "A driver"
    if not name:
        return one.label
    # Three lines rather than a sentence: the command is the useful half and
    # it has to be copyable, which it is not when a wrap lands in the middle
    # of it. The file writer wraps each line of this on its own.
    return (f"{one.label}.\n"
            f"Nothing here starts it. Where the hardware is, run:\n"
            f"{one.command} --collector {name}")


def start_command(kind: str, name: str = "<name>") -> str:
    """What to type where the hardware is, for this kind of collector."""
    table = kinds()
    one = table.get(kind) or next(iter(table.values()), None)
    if one is None:
        # No kind installed at all. Saying nothing would leave the page
        # with a blank where the command goes.
        return "no driver add-on is installed"
    # The kind's command, whole. Nothing is put in front of it: an add-on
    # brings a command of its own -- `weewx-evo-weewx-driver run` -- and a
    # core that prefixed `weewx-evo` printed
    # "weewx-evo weewx-evo-weewx-driver run", which is not a command on any
    # machine. That was right while every kind was a subcommand of this
    # program, and it stopped being right the day one arrived from outside.
    return f"{one.command} --collector {name}"


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
        if str(one.get("kind", "")).strip() not in kinds():
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


def options(kind: str = "mqtt", settings: dict | None = None) -> list:
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
    fields that driver has, and only the kind knows that.
    """
    from .options import Group, Option

    table = kinds()
    kind = kind if kind in table else next(iter(table), "")
    # "The driver", not "The collector". The split is real and it stays in
    # the code, but it is ours: to somebody with a weather station this is a
    # driver, whether it listens on a socket or asks a USB console. What the
    # reader has to know is that this one runs somewhere else, and that is
    # what the group and the help say instead of the word.
    which = Group("The driver", "What this one runs.", (
        Option("kind", "What kind of driver this is",
               kind="choice", default=kind,
               choices=tuple((name, one.label) for name, one in table.items()),
               help="It gets a process of its own and delivers over the "
                    "network -- so a serial port or a broker that stops "
                    "answering cannot hold up the archiver."),
        Option("runs_here", "Start it on this machine", kind="bool",
               default=True,
               help="On is the ordinary case: the hardware is plugged into "
                    "this machine, and weewx-evo starts the driver and keeps "
                    "it alive, so it comes back after a reboot with "
                    "everything else. Turn it off only for hardware plugged "
                    "into a different machine -- the page then prints the "
                    "command to run over there."),
    ))

    # The kind says what else it needs. A kind an add-on contributed answers
    # for itself, which is the whole reason this is a callable: the core has
    # no way to know what running a WeeWX driver asks for once that add-on is
    # what carries it.
    build = getattr(table.get(kind), "options", None)
    if build is not None:
        try:
            return [which, *build(dict(settings or {}))]
        except Exception:
            log.exception("the collector kind %r could not describe itself", kind)
            return [which]

    return [which]


def _mqtt_options(settings: dict) -> list:
    """A broker: where it is, what to listen to, and what the topics mean."""
    from .ingest import mqttsub
    from .options import Group, Option

    return [
        Group("The broker", "Where it is, and what to listen to.",
              tuple(one for one in mqttsub.options()
                    if one.name != "unit_system")),
        Group("The readings", "What the topics mean.", (
            Option("source", "Record its readings under this name",
                   kind="text", default="",
                   help="Empty means this driver's own name. This is "
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


#: What the core itself can collect from. Last in the file because each entry
#: names the function that draws its page, and an add-on adds to this through
#: `kinds()` rather than by editing it.
#:
#: `reads` is here rather than on the page because the page draws its list
#: from this, so a kind cannot arrive in the menu and be missing from the
#: explanation under it. That is exactly what happened to MQTT.
KINDS = {
    "mqtt": Kind(
        "A broker to subscribe to, in its own process",
        "Readings a broker already carries, from a console that publishes "
        "them itself or from a home-automation system. The command "
        "weewx-evo mqtt check prints what a broker publishes, which is how "
        "the topic names its page asks for are found.",
        "weewx-evo mqtt run", _mqtt_options),
}

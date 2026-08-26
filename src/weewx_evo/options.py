"""What a component can be configured with, declared rather than documented.

Every part of weewx-evo says what its settings are: their type, their default,
what they mean, and what makes a value wrong. Nothing else has to know. The
command line reads it, the admin page builds its form from it, the validator
checks against it, and a driver that gains a setting gains a form field with
no change anywhere else.

The alternative is what most systems end up with: settings documented in a
wiki, parsed in one place, validated in another, and rendered in a third, with
the four drifting apart. A weather station runs for years without being
touched, and the day somebody comes back to it the configuration file is the
only thing left explaining what it does.

A component declares its settings like this:

    def options():
        return [
            Group("Station", "Where this station is", [
                Option("latitude", "Latitude", kind="float",
                       help="Decimal degrees. Negative south of the equator.",
                       minimum=-90, maximum=90, required=True),
            ]),
        ]

`kind` decides how it is parsed, checked and drawn. Adding a kind means
teaching all three, which is the point: there is one list of them.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

#: The kinds a setting can be. Each one is a parser, a check and a form field.
#:
#: `secret` is `text` that is never rendered back: the admin page shows whether
#: one is set, not what it is. A token that has been displayed once is a token
#: in a screenshot.
KINDS = ("text", "secret", "int", "float", "bool", "choice", "path",
         "duration", "list")

#: Durations are written the way people say them. Seconds are the unit
#: everything is stored in, but nobody configures a retention of 604800.
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.I)
_DURATION_SCALE = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


class Invalid(ValueError):
    """A value that a setting cannot take, with a reason a person can act on."""


@dataclass(frozen=True, slots=True)
class Option:
    """One setting."""

    name: str
    label: str
    kind: str = "text"
    default: Any = None
    help: str = ""
    #: What the value is measured in, shown after the field: "seconds", "°C".
    unit: str = ""
    choices: tuple[tuple[str, str], ...] = ()   # (value, label)
    #: Choices that depend on the installation rather than the code: which
    #: drivers are installed, which feeds exist, what tables the database has.
    #: A function, because the answer changes while the process runs -- adding
    #: a feed must put it in the export's list without a restart.
    choices_from: Any = None
    #: Values worth offering without forbidding others. Rendered as a browser
    #: suggestion list: the three usual answers are one click away and an
    #: unusual one can still be typed. `allow` is the case this exists for --
    #: "private", "any", or a list of networks nobody can enumerate.
    suggestions: tuple[tuple[str, str], ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    required: bool = False
    #: Settings most people never touch. The form hides them behind a toggle
    #: rather than leaving them out: a hidden setting is one that gets found
    #: by reading the source, which is worse than a long page.
    advanced: bool = False
    #: Changing this needs the service restarted to take effect.
    restart: bool = False
    #: What to show in an empty field, when there is no sensible default.
    placeholder: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.name}: no such kind {self.kind!r}")
        if self.kind == "choice" and not self.choices and self.choices_from is None:
            raise ValueError(f"{self.name}: a choice needs choices")

    def options(self) -> tuple[tuple[str, str], ...]:
        """The choices, asking the installation if that is where they are.

        A failure here is not fatal: an empty list renders as "nothing to
        choose from yet", which is the truth, rather than a stack trace on a
        settings page.
        """
        if self.choices_from is None:
            return self.choices
        try:
            found = tuple(self.choices_from())
        except Exception:
            return self.choices
        return self.choices + found

    def parse(self, raw: Any) -> Any:
        """Turn what arrived into the value this setting holds.

        Raises Invalid with a message meant for whoever typed it. Empty means
        "not set" and comes back as None, unless the setting is required --
        the distinction between empty and absent is one people get wrong, so
        it is made here once.
        """
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if self.required and self.default is None:
                raise Invalid(f"{self.label} is required")
            # A choice that offers an empty entry means it: "-- none --" is
            # one of the answers, not the absence of one. Falling back to the
            # default here made every such setting impossible to clear once
            # it had been set.
            if self.kind == "choice" and any(
                    value == "" for value, _label in self.options()):
                return ""
            return self.default

        if self.kind == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on")

        if self.kind in ("int", "float"):
            try:
                value = float(str(raw).strip())
            except ValueError:
                raise Invalid(f"{self.label} must be a number") from None
            if self.kind == "int":
                if value != int(value):
                    raise Invalid(f"{self.label} must be a whole number")
                value = int(value)
            self._check_range(value)
            return value

        if self.kind == "duration":
            value = parse_duration(str(raw), self.label)
            self._check_range(value)
            return value

        if self.kind == "choice":
            value = str(raw).strip()
            allowed = [v for v, _ in self.options()]
            discovered = [v for v, _ in self.options()
                          if v not in [c for c, _ in self.choices]]
            if not allowed or (self.choices_from is not None and not discovered):
                # Nothing could be discovered. That is not evidence the value
                # is wrong: the list comes from somewhere else -- a plugin
                # that is not installed right now, another file that could
                # not be read this second -- and refusing on that basis
                # silently replaces a setting with its default. Which is
                # exactly what happened to a running station: a reload read
                # the list a moment too early and the page it was serving
                # changed underneath it.
                return value
            if value not in allowed:
                # By their labels: an empty choice is a real answer and its
                # value is the empty string, which reads as a missing word in
                # a list of names.
                named = ", ".join(label if not option else option
                                  for option, label in self.options())
                raise Invalid(f"{self.label} must be one of: {named}")
            return value

        if self.kind == "list":
            if isinstance(raw, (list, tuple)):
                items = [str(x).strip() for x in raw]
            else:
                # One per line, because the things that go in these lists are
                # URLs and paths, and both contain commas often enough.
                items = [line.strip() for line in str(raw).splitlines()]
            return [x for x in items if x]

        value = str(raw).strip()
        if self.kind == "path" and not value:
            return self.default
        return value

    def _check_range(self, value: float) -> None:
        if self.minimum is not None and value < self.minimum:
            raise Invalid(f"{self.label} cannot be below {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise Invalid(f"{self.label} cannot be above {self.maximum}")

    def render(self, value: Any) -> Any:
        """The value as the form should show it. Secrets never come back."""
        if self.kind == "secret":
            return "" if not value else "•" * 12
        if self.kind == "list" and isinstance(value, (list, tuple)):
            return "\n".join(str(v) for v in value)
        if value is None:
            return ""
        return value


def parse_duration(text: str, label: str = "value") -> int:
    """Seconds from '90', '5m', '2h', '7d'. A bare number is seconds."""
    match = _DURATION.match(text)
    if not match:
        raise Invalid(f"{label}: '{text}' is not a duration. Try 30s, 5m, 2h or 7d.")
    amount, suffix = match.groups()
    return int(float(amount) * _DURATION_SCALE[suffix.lower()])


def format_duration(seconds: float | None) -> str:
    """The other way, choosing the largest unit that stays whole."""
    if seconds is None:
        return ""
    amount, suffix = split_duration(seconds)
    return f"{amount}{suffix}"


#: The units a duration is offered in, largest first. Shown as a dropdown
#: beside the number: typing "5m" works, but nobody should have to know that
#: it does, and "300" in a box labelled "interval" is a question about units
#: that a form should not be asking.
UNITS = (("s", "seconds"), ("m", "minutes"), ("h", "hours"), ("d", "days"))


def split_duration(seconds: float | None) -> tuple[int, str]:
    """Seconds as (amount, unit), in the largest unit that stays whole.

    604800 becomes (7, "d"), not (604800, "s"). A retention shown as 604800
    is a number nobody can check at a glance.
    """
    if seconds is None:
        return 0, "s"
    seconds = int(seconds)
    for suffix, scale in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds and seconds % scale == 0:
            return seconds // scale, suffix
    return seconds, "s"


@dataclass(frozen=True, slots=True)
class Group:
    """Settings that belong together, and become one section of the form."""

    label: str
    help: str = ""
    options: tuple[Option, ...] = ()
    #: Where these live in the configuration file, e.g. "drivers.ecowitt".
    #: Empty means the top level.
    prefix: str = ""


@dataclass
class Schema:
    """Everything one component can be configured with."""

    name: str
    label: str
    groups: tuple[Group, ...] = ()
    help: str = ""
    #: What this is: the core itself, a driver, or something else later.
    kind: str = "component"

    def __iter__(self) -> Iterator[tuple[Group, Option]]:
        for group in self.groups:
            for option in group.options:
                yield group, option

    def option(self, name: str) -> Option | None:
        for _group, option in self:
            if option.name == name:
                return option
        return None

    def defaults(self) -> dict[str, Any]:
        return {option.name: option.default for _g, option in self
                if option.default is not None}

    def parse(self, values: dict[str, Any],
              only_present: bool = False) -> tuple[dict[str, Any], dict[str, str]]:
        """Check a whole form's worth at once.

        Returns the parsed settings and, separately, what was wrong with which
        field. Everything is checked rather than stopping at the first error: a
        form that reports one problem per submission is a form people fight.

        `only_present` leaves out settings the caller did not mention at all,
        rather than treating them as empty. That distinction matters more than
        it looks: an absent field means "not part of this request", an empty
        one means "clear it". Without it, anything posting half a form would
        quietly reset the other half to its defaults -- and the browser is not
        the only thing that posts.
        """
        parsed: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for _group, option in self:
            if only_present and option.name not in values:
                continue
            if option.kind == "secret" and _unchanged_secret(values.get(option.name)):
                # The form showed dots, and dots came back. That means "leave
                # it alone", not "set it to dots".
                continue
            try:
                value = option.parse(values.get(option.name))
            except Invalid as exc:
                errors[option.name] = str(exc)
                continue
            if value is not None:
                parsed[option.name] = value
        return parsed, errors


def _unchanged_secret(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and set(value) == {"•"}


#: How a component is asked for its schema. A class or module with this is
#: configurable; anything without it simply has no settings.
Describable = Callable[[], "list[Group]"]


def schema_of(component: object, name: str, label: str | None = None,
              kind: str = "component") -> Schema | None:
    """Ask a component to describe itself, if it can."""
    describe = getattr(component, "options", None)
    if describe is None:
        return None
    try:
        groups = describe()
    except Exception:  # pragma: no cover - a broken plugin
        return None
    if not groups:
        return None
    return Schema(name=name, label=label or name, kind=kind,
                  groups=tuple(groups),
                  help=(getattr(component, "__doc__", "") or "").strip().split("\n")[0])


# ---------------------------------------------------------------------------
# The core's own settings.
# ---------------------------------------------------------------------------

def installed_drivers() -> list[tuple[str, str]]:
    """The drivers this installation actually has.

    Asked at render time, not listed here: installing a driver should put it
    in the dropdown, and a name typed by hand is a name that can be typed
    wrong.
    """
    from .ingest import drivers

    return [(name, name) for name in drivers.names()]


def installed_skins() -> list[tuple[str, str]]:
    """The Cheetah skins that are there, for the dropdown that offers them.

    Read from the directory a feed points at rather than from a list, so a
    skin dropped in beside the others appears without anything being told.
    """
    from pathlib import Path

    from . import config as config_file

    try:
        current = config_file.read(_config_path())
    except Exception:  # noqa: BLE001
        return []

    roots = []
    for settings in (current.get("feeds") or {}).values():
        if isinstance(settings, dict) and settings.get("kind") == "cheetah":
            roots.append(str(settings.get("skins_dir") or "skins"))
    roots.append("skins")

    found: dict[str, str] = {}
    for root in roots:
        where = Path(root)
        if not where.is_dir():
            continue
        for entry in sorted(where.iterdir()):
            if (entry / "skin.conf").is_file() and entry.name not in found:
                found[entry.name] = entry.name
    return sorted(found.items())


def published_names() -> list[tuple[str, str]]:
    """What the built-in web server has to hand out.

    The local exports, by name: an export is where somebody said a feed's
    files should end up, so it is also the thing that has an address. Reading
    the exports rather than the feeds is the difference between offering what
    exists and offering what might.
    """
    from . import config as config_file

    try:
        current = config_file.read(_config_path())
    except Exception:  # noqa: BLE001
        return []
    out = []
    for name, options in sorted((current.get("exports") or {}).items()):
        if isinstance(options, dict) and options.get("kind") == "local":
            where = str(options.get("directory", "")).strip()
            out.append((name, f"{name} -- {where}" if where else name))
    for name in sorted((current.get("web", {}) or {}).get("serve", {}) or {}):
        out.append((name, f"{name} -- named directly"))
    return out


#: Which configuration file the forms being built belong to. Set by
#: `all_schemas`, because that is the one moment when it is known and the
#: dropdowns are built long after it.
_FOR_FILE: Any = None


def building_for(path: Any) -> None:
    """Say which file the forms about to be built describe.

    A dropdown that lists the exports has to read them from somewhere, and it
    is called from inside the renderer with no argument. Reaching for the
    command line instead was wrong twice already: the settings page passes
    its own path, and a form built from a different file offers exports that
    are not in it.
    """
    global _FOR_FILE
    _FOR_FILE = path


def _config_path() -> Any:
    """Which file the forms are being built for."""
    if _FOR_FILE is not None:
        return _FOR_FILE
    from .cli import _ARGS

    return getattr(_ARGS, "config", None) if _ARGS else None


def defined_feeds() -> list[tuple[str, str]]:
    """The feeds that exist, by the names the operator gave them.

    Names, not kinds. Two sets of JSON in two unit systems are two feeds
    with two names, and an export has to be able to point at one of them.
    Reading the kinds back meant an export could be aimed at "json" and
    never at "metric", and a feed the operator named was refused at startup
    as though it did not exist.
    """
    from . import config as config_file
    from . import feeds
    from .cli import DEFAULT_FEEDS

    try:
        current = config_file.read(_config_path()) or {}
    except Exception:  # noqa: BLE001
        current = {}
    configured = current.get("feeds") or {}
    if not configured:
        # A file that names none still gets the two that ship, so the list
        # has to say the same thing the runner does.
        configured = DEFAULT_FEEDS

    out = []
    for name in sorted(configured):
        settings = configured[name]
        kind = (settings.get("kind") if isinstance(settings, dict) else "") or ""
        said = feeds.describe(str(kind))
        out.append((name, f"{name} -- {said}" if said else name))
    return out


def website_options() -> list[Group]:
    """The built-in web server.

    Its own page, because "where does what I made end up" is the question
    people actually arrive with, and it was previously three fields halfway
    down a page about databases and ports.
    """
    return [
        Group("The built-in web server",
              "Hands what the exports published to a browser. Enough to look "
              "at a station's own pages on the local network without "
              "installing anything else.", (
                  Option("web.enabled", "Serve the pages", kind="bool",
                         default=False, restart=True,
                         help="Off, nothing is served and the exports still "
                              "publish. On, whatever a local export wrote is "
                              "reachable at the addresses below."),
                  Option("web.port", "Port", kind="int", default=8081,
                         minimum=1, maximum=65535, restart=True,
                         help="Its own, separate from the upload port and the "
                              "settings page. Those two answer hardware and "
                              "an operator; this answers browsers."),
                  Option("web.default", "Show this at /", kind="choice",
                         choices=(("", "-- a list of what there is --"),),
                         choices_from=published_names,
                         help="What appears at the address itself. With one "
                              "chosen, / is that one and the rest stay at "
                              "/<name>/. Without, / lists them."),
              )),
        Group("Who gets an answer", "", (
            Option("web.allow", "Answer", default="private",
                   suggestions=(("private", "the local network"),
                                ("any", "anywhere, including the internet")),
                   help="A page of weather is not a secret, but it is still "
                        "this machine answering strangers. Behind a reverse "
                        "proxy leave this alone: the proxy connects from "
                        "loopback, which is private."),
            Option("web.host", "Listen on", default="0.0.0.0",
                   restart=True, advanced=True,
                   help="Bound to everything and answering private networks "
                        "only. What keeps it private is the line above, not "
                        "this one."),
        )),
    ]


def core_options() -> list[Group]:
    """What weewx-evo itself is configured with."""
    return [
        Group("Station", "Where the readings come from, and where it is.", (
            Option("station.name", "Station name", default="weewx-evo",
                   help="Shown on the live page and in reports."),
            Option("station.latitude", "Latitude", kind="float",
                   minimum=-90, maximum=90, unit="° N", placeholder="48.4596",
                   help="Decimal degrees. Negative south of the equator. "
                        "Used for sunrise, sunset and the clear-sky radiation "
                        "a solar sensor is measured against."),
            Option("station.longitude", "Longitude", kind="float",
                   minimum=-180, maximum=180, unit="° E", placeholder="11.6539",
                   help="Decimal degrees. Negative west of Greenwich."),
            Option("station.altitude", "Altitude", kind="float", unit="m above sea level",
                   help="Above sea level. This is what turns station pressure "
                        "into the barometer reading everyone compares. Take it "
                        "from a map, not from the console: consoles are usually "
                        "set to whatever made the display look right."),
            Option("station.url", "Station web page", default="",
                   placeholder="https://example.org/weather",
                   help="Where the published pages live. A skin prints it in "
                        "its footer and a weather network wants it in a "
                        "registration."),
            Option("station.rain_year_start", "Rain year starts in",
                   kind="int", default=1, minimum=1, maximum=12,
                   advanced=True,
                   help="Which month a rainfall year is counted from. "
                        "January nearly everywhere; October where the water "
                        "year is what people mean by a wet or dry year."),
        )),

        Group("Archive", "How readings become the record that is kept.", (
            Option("interval", "Archive interval", kind="duration", default=300,
                   minimum=60, maximum=3600, restart=True,
                   help="How much time one archive record covers. Five minutes "
                        "is the usual choice. Changing it does not disturb what "
                        "is already recorded -- each record carries the span it "
                        "stands for, so old and new average correctly together."),
            Option("grace", "Settling time", kind="duration", default=15,
                   minimum=0, maximum=300, advanced=True,
                   help="How long to wait after an interval closes before "
                        "working it out, so a packet that is merely slow does "
                        "not force the record to be computed twice."),
            Option("loop_hilo", "Sharpen highs and lows from packets",
                   kind="bool", default=True, advanced=True,
                   help="Let individual packets set the daily extremes, not "
                        "just the archive records. On by default and the same "
                        "as WeeWX. Turning it off makes the daily highs and "
                        "lows exactly reproducible from the archive alone."),
        )),

        Group("Databases", "Two files: the record, and the packets behind it.", (
            Option("feeds_dir", "Feed output", kind="path",
                   default="data/feeds", restart=True,
                   help="Where the feeds write. Each gets a directory under "
                        "it. This is their working directory and not a "
                        "published one: an export is what puts the files "
                        "somewhere anybody can read them."),
            Option("plots_file", "Plot definitions", kind="path",
                   default="plots.toml", restart=True,
                   help="Which charts exist, and what goes in each. Its own "
                        "file rather than a section here: it is a list of "
                        "many similar records, and one imported from an old "
                        "skin is something you want to be able to diff."),
            Option("archive_db", "Archive database", kind="path",
                   default="data/weewx.sdb", restart=True,
                   help="The WeeWX database. Existing ones are used as they "
                        "are -- the schema is read from the file, so an "
                        "installation with its own columns keeps them."),
            Option("live_db", "Live database", kind="path",
                   default="data/live.sdb", restart=True,
                   help="Where packets are kept until they have been worked "
                        "into records. Its own file, so its size and its "
                        "retention have nothing to do with the archive."),
            Option("retention", "Keep packets for", kind="duration",
                   default=604800, minimum=3600,
                   help="How long raw packets stay. They are what makes a "
                        "record reproducible: while they are here, a bad "
                        "calibration or a late packet can be corrected. Seven "
                        "days is about 80 MB at one packet every eight seconds."),
            Option("raw_retention", "Keep raw uploads for", kind="duration",
                   default=3600, minimum=0, maximum=86400, advanced=True,
                   help="How long the upload as it came off the wire is kept "
                        "beside the parsed packet. It is a debugging aid -- "
                        "the thing to attach to an issue about a sensor the "
                        "driver could not place. 0 does not keep them."),
            Option("spool", "Write packets out before dropping them",
                   kind="path", advanced=True,
                   help="A directory. Each day of packets leaving the live "
                        "table is written there as gzipped NDJSON first. Empty "
                        "means they are simply dropped."),
        )),

        Group("Listener", "The port the hardware uploads to.", (
            Option("host", "Listen on", default="0.0.0.0", restart=True,
                   advanced=True,
                   help="0.0.0.0 is every interface. Narrow it if the machine "
                        "is on more than one network."),
            Option("port", "Port", kind="int", default=8000,
                   minimum=1, maximum=65535, restart=True,
                   help="Ports below 1024 need root, which this should not have."),
            Option("token", "Upload token", kind="secret", required=True,
                   help="A path segment every upload must carry. It is the "
                        "only thing between the open internet and the "
                        "measurement series: hardware cannot send a header, so "
                        "a path nobody can guess is the practical answer. "
                        "Anyone who learns it can forge readings."),
            Option("driver", "Default driver", kind="choice",
                   default="ecowitt", choices_from=installed_drivers,
                   help="Which driver reads an upload whose path does not name "
                        "one. A console that can only be pointed at a bare "
                        "path needs this to be right. The list is what is "
                        "installed -- add more with 'weewx-evo driver install'."),
            Option("udp_port", "UDP port", kind="int", default=0,
                   minimum=0, maximum=65535, restart=True, advanced=True,
                   help="For hardware that broadcasts instead of posting. 0 "
                        "switches it off. A datagram carries no path, so the "
                        "port itself is the access control."),
        )),

        Group("Who is answered",
              "Bound to every interface; this decides who gets a reply.", (
            Option("allow", "Answer", default="private", restart=True,
                   suggestions=(("private", "the local network"),
                                ("any", "anywhere, including the internet"),
                                ("192.168.0.0/16", "one network"),
                                ("127.0.0.1", "this machine only")),
                   help="'private' means the local network -- the shed, the "
                        "console, the laptop in the kitchen -- and covers a "
                        "reverse proxy, which always connects from a private "
                        "address. 'any' includes the open internet. Or list "
                        "networks: 10.0.0.0/8, 192.168.1.50. Loopback is "
                        "always answered."),
            Option("rate", "Requests a second, per address", kind="float",
                   default=10.0, minimum=0, advanced=True, unit="per second",
                   help="A console at its fastest sends half a request a "
                        "second, so this only catches something that has gone "
                        "wrong. What stops somebody guessing the token is the "
                        "separate limit on wrong ones. 0 switches it off."),
            Option("behind_proxy", "Behind a reverse proxy", kind="bool",
                   default=False, advanced=True,
                   help="Then every request arrives from the proxy's address, "
                        "and limiting per address would slow down everyone "
                        "except whoever is doing it. Rate limiting is left to "
                        "the proxy, which is the only thing able to do it."),
        )),

        Group("Settings page",
              "Its own port and its own token: it can do far more than an "
              "upload can.", (
            Option("admin.token", "Admin token", kind="secret",
                   help="Never the same as the upload token. Anything that "
                        "could send a reading would otherwise be able to "
                        "change what the station records. Empty switches the "
                        "page off."),
            Option("admin.port", "Port", kind="int", default=8080,
                   minimum=1, maximum=65535, restart=True),
            Option("admin.host", "Listen on", default="0.0.0.0",
                   restart=True, advanced=True),
            Option("admin.allow", "Answer", default="private",
                   suggestions=(("private", "the local network"),
                                ("127.0.0.1", "this machine only, via SSH tunnel"),
                                ("any", "anywhere, including the internet")),
                   help="As above, and worth keeping narrower. This page "
                        "points the archive at files. To reach it from "
                        "elsewhere without opening it up: "
                        "ssh -L 8080:localhost:8080 the-station"),
            Option("admin.rate", "Requests a second, per address",
                   kind="float", default=5.0, minimum=0, advanced=True,
                   unit="per second",
                   help="Saving is two requests, and clicking through the "
                        "tabs makes several a second. A limit that gets in "
                        "the way is one that gets turned off."),
        )),

        Group("Running", "Where things are put and how often they happen.", (
            Option("table", "Archive table", default="archive", advanced=True,
                   restart=True,
                   help="The table inside the database. Only worth changing "
                        "for an installation that renamed it."),
            Option("poll", "Check for closed intervals every", kind="duration",
                   default=5, minimum=1, maximum=300, advanced=True,
                   help="How often the archiver looks. The work is idempotent "
                        "and the interval boundaries come from the packets, "
                        "so a tick that is late or missed changes nothing."),
            Option("driver_dir", "Third-party drivers", kind="path",
                   advanced=True, restart=True,
                   help="Where drivers installed with 'weewx-evo driver "
                        "install' live. Empty means beside the archive."),
            Option("weewx_conf", "Fall back on this weewx.conf", kind="path",
                   advanced=True,
                   help="Settings both systems share -- latitude, altitude, "
                        "the archive interval -- can go on living there. Read, "
                        "never written. Anything set here wins over it."),
        )),
    ]

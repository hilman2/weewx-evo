"""The consoles this installation takes readings from.

A **station** is a thing that uploads. It has a name somebody chose, the
driver that reads it, and an identity that tells its packets apart from
everybody else's. A **archive** is where those readings end up: a measurement
series for one place, with its own file and its own altitude.

    [stations.kirchdorf]
    driver = "wunderground"
    identity = "evo-3f9a2c"
    archive = "default"

Two stations, one archive, is the ordinary case: a console and a soil probe
measuring the same garden. Two stations, two archives, is a weewx-evo on a VPS
collecting from two fields. The second one is why `archive` is here from the
first version rather than added later: a field that exists from the start is a
row to fill in, and one added afterwards is a migration.

**Announced, not adopted.** Today the first console heard becomes the station
and everything else is refused. That works for one driver and was written
three times over for the others. Worse, it cannot work for Weather Underground
at all: an Ecowitt PASSKEY comes from the hardware, but a WU station ID is
typed by a person, so two consoles can carry the same one and nothing
downstream can separate them.

So we hand out the identity where we can. `identity_for()` produces
`evo-3f9a2c`, the page shows it, and the operator copies it onto the console.
They do not choose it, so they cannot choose it twice. Where the hardware
brings its own -- an Ecowitt PASSKEY, a Tempest serial -- it is learnt instead,
at the moment somebody is standing at the console expecting it to be learnt.

**What is not in this file.** When a station was last heard from, how many
packets it has sent, which consoles have turned up uninvited. That is
observed, not decided, and it changes every few seconds. It lives in the live
database, and `last_seen` is not stored anywhere at all: the live table
already knows when a packet with that source arrived, so keeping a second
answer would only create a wrong one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

FILENAME = "stations.toml"

#: The archive a station writes into when nobody said otherwise. One archive
#: is the ordinary case and it should need no configuring; the name exists so
#: that the second one is a row rather than a rewrite.
DEFAULT_ARCHIVE = "default"

#: What an identity we hand out looks like. Short because some firmware limits
#: the field, lower case because some consoles upper-case what is typed into
#: them, and prefixed so it is recognisable as ours in somebody's log.
IDENTITY_PREFIX = "evo-"
IDENTITY_DIGITS = 6

#: A station name, as it appears in `sources.toml` and in a URL.
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class Station:
    """One console, announced."""

    #: What people call it. Also the `source` its packets are recorded under,
    #: which is what `sources.py` matches its rules against.
    name: str
    #: Which driver reads its uploads.
    driver: str
    #: What tells its packets apart. A PASSKEY, a serial, or one we handed out.
    identity: str
    #: Which measurement series it writes into.
    archive: str = DEFAULT_ARCHIVE
    #: Whatever the operator wants to remember about it.
    note: str = ""
    #: True when the identity came from the hardware rather than from us. Only
    #: used to word the page: one is copied onto the console, the other is
    #: read off it.
    learnt: bool = False

    # -- what is true of this console, not of its protocol --------------
    #
    # These lived on the drivers, which is where they do not belong. A
    # protocol has no opinion about whether the room a console stands in is
    # worth recording; this console does, and the next one may not. The
    # symptom was plain once two drivers stood side by side: the Weather
    # Underground one could be told to leave indoor readings out and the
    # Ecowitt one could not, for no reason anybody could give.

    #: Record the temperature and humidity of the room the console is in.
    #: A console in a living room measures a living room; one in a shed on the
    #: same station measures a shed, and only one of them is worth a column.
    indoor: bool = True
    #: What the hardware is, for the page and the log. Cosmetic, and a
    #: property of this box rather than of the protocol it speaks.
    model: str = ""
    #: This console's own field names, where they differ. Two consoles both
    #: number their channels from one, so `tf_ch1` is a different thermometer
    #: on each -- which is why the map hangs on the console and not on the
    #: driver. Applied by the driver, because only it knows what the names
    #: mean before they are parsed.
    field_map: dict[str, str] = field(default_factory=dict)
    #: `main` or `extra`. One archive has one main station, whose readings go
    #: where they belong; an extra one's are moved into `extraTemp<n>` and
    #: `extraHumid<n>` so that two sensors cannot take turns in one column.
    #: See roles.py -- and note that a second *archive* is the other answer,
    #: and usually the better one when the two are different places.
    role: str = "main"
    #: Which channel an extra station takes. Assigned when the role is set,
    #: because the lowest free one is not a decision anybody wants to make.
    channel: int = 0
    #: How far out this console's clock may be before the arrival time is
    #: used instead. None means the figure from the settings, which is what
    #: nearly every console wants.
    #:
    #: Here rather than on the protocol, where both of these were: a stamp is
    #: too old because a *clock* is wrong, and a clock belongs to a box. Two
    #: Ecowitt consoles, one a GW2000 keeping NTP and one an older display
    #: that drifts a quarter of an hour a week, are one protocol and two
    #: different answers -- and set on the protocol, the tolerant figure the
    #: old one needs would have been extended to the new one as well.
    max_behind: float | None = None
    max_ahead: float | None = None

    def matches(self, driver: str, identity: str) -> bool:
        """Whether an upload belongs to this station.

        The identity is compared without regard to case. Consoles upper-case
        what is typed into them often enough that treating `EVO-3F9A2C` as a
        different station would be a support question rather than a safeguard.
        """
        return (self.driver == driver
                and self.identity.casefold() == (identity or "").casefold())


@dataclass
class Register:
    """The stations this installation has.

    Held as a list rather than keyed by identity: two drivers may legitimately
    see the same identity string, and the pair is what identifies a station.
    """

    stations: list[Station] = field(default_factory=list)
    path: Path | None = None
    #: When the file was last read, and how recently that was checked.
    stamp: float = 0.0
    checked: float = 0.0

    # -- keeping up with the file --------------------------------------

    def refresh(self, every: float = 5.0) -> bool:
        """Re-read the file if it has changed. True when it did.

        The settings page writes this file and the listener is a different
        process, so without this an adopted console keeps arriving as a
        stranger until somebody restarts the service. Restarting a listener to
        register a station is exactly the sort of thing people do not do, and
        then the page looks broken.

        A `stat` every few seconds rather than on every upload. A console
        posts every sixteen seconds, so the cost is nil either way, but there
        is no reason to ask the filesystem more often than the answer can
        change.
        """
        import time as clock

        if self.path is None:
            return False
        now = clock.time()
        if now - self.checked < every:
            return False
        self.checked = now
        try:
            stamp = self.path.stat().st_mtime
        except OSError:
            # Deleted while running. Keep what we have rather than forgetting
            # every station because a file went missing for a moment.
            return False
        if stamp == self.stamp:
            return False

        try:
            fresh = load(self.path)
        except Exception:
            # A half-written or hand-edited file that does not parse. The
            # previous stations stay, because the alternative is recording
            # nothing under any name until somebody notices.
            log.exception("could not re-read %s; keeping the stations already "
                          "loaded", self.path)
            self.stamp = stamp
            return False
        self.stations = fresh.stations
        self.stamp = stamp
        log.info("%s changed: %d station(s) now announced (%s)", self.path,
                 len(self.stations),
                 ", ".join(sorted(one.name for one in self.stations)) or "none")
        return True

    # -- looking things up ---------------------------------------------

    def __len__(self) -> int:
        return len(self.stations)

    def __iter__(self):
        return iter(self.stations)

    def by_name(self, name: str) -> Station | None:
        for one in self.stations:
            if one.name == name:
                return one
        return None

    def by_identity(self, driver: str, identity: str) -> Station | None:
        """Which station an upload belongs to, or None if it is a stranger."""
        for one in self.stations:
            if one.matches(driver, identity):
                return one
        return None

    def for_archive(self, archive: str) -> list[Station]:
        """The stations writing into one measurement series."""
        return [one for one in self.stations if one.archive == archive]

    def archives(self) -> list[str]:
        """Every archive named by a station, plus the default.

        The default is always in the list even when nothing points at it, so a
        fresh installation has somewhere to put its first station.
        """
        found = {one.archive for one in self.stations}
        found.add(DEFAULT_ARCHIVE)
        return sorted(found)

    def drivers(self) -> set[str]:
        return {one.driver for one in self.stations}

    def identities_for(self, driver: str) -> set[str]:
        return {one.identity.casefold() for one in self.stations
                if one.driver == driver}

    # -- changing them -------------------------------------------------

    def add(self, station: Station) -> Station:
        """Announce a station. Raises if the name or the identity is taken.

        Refused rather than merged: a second station under a name that is
        already in `sources.toml` would silently take over the first one's
        rules, and two stations sharing an identity is the failure this whole
        module exists to make impossible.
        """
        problem = self.why_not(station)
        if problem:
            raise ValueError(problem)
        self.stations.append(station)
        return station

    def why_not(self, station: Station, replacing: str | None = None) -> str:
        """Why this station cannot be added, or an empty string.

        Separate from `add` because the page needs to say what is wrong beside
        the field that is wrong, before anybody presses save.
        """
        if not _NAME.match(station.name or ""):
            return ("a name is lower case letters, digits, dashes and "
                    "underscores, up to 64 of them")
        if not (station.identity or "").strip():
            return "a station needs an identity, or its uploads cannot be told apart"
        for one in self.stations:
            if one.name == replacing:
                continue
            if one.name == station.name:
                return f"there is already a station called {station.name!r}"
            if one.matches(station.driver, station.identity):
                return (f"{one.name!r} already answers to that identity on the "
                        f"{station.driver} driver")
        return ""

    def remove(self, name: str) -> Station | None:
        for at, one in enumerate(self.stations):
            if one.name == name:
                return self.stations.pop(at)
        return None

    def rename(self, name: str, to: str) -> Station | None:
        """Rename a station, keeping everything else.

        The name is the `source` on its packets, so renaming does not reach
        backwards: readings already stored keep the old name. That is right --
        they were recorded under it -- and it is why the page has to say so.
        """
        one = self.by_name(name)
        if one is None:
            return None
        changed = replace(one, name=to)
        problem = self.why_not(changed, replacing=name)
        if problem:
            raise ValueError(problem)
        self.stations[self.stations.index(one)] = changed
        return changed

    def identity_for(self, driver: str) -> str:
        """An identity nobody else here has.

        Handed out rather than chosen, which is the whole point: an operator
        cannot type the same one twice if they never typed it at all.
        """
        import secrets

        taken = self.identities_for(driver)
        for _ in range(64):
            made = IDENTITY_PREFIX + secrets.token_hex(4)[:IDENTITY_DIGITS]
            if made.casefold() not in taken:
                return made
        # Sixty-four collisions on six hex digits means something is wrong
        # with the random source, not that we were unlucky.
        raise RuntimeError("could not find an unused identity")


# -- the file ----------------------------------------------------------


def path_for(directory: str | Path) -> Path:
    return Path(directory) / FILENAME


def load(path: str | Path) -> Register:
    """Read stations.toml. A missing file is an installation with none yet."""
    import tomllib

    path = Path(path)
    if not path.exists():
        return Register(path=path)
    with open(path, "rb") as fp:
        raw = tomllib.load(fp)
    made = from_dict(raw, path=path)
    try:
        made.stamp = path.stat().st_mtime
    except OSError:
        pass
    return made


def _seconds(value: Any) -> float | None:
    """A clock tolerance, or None for "whatever the settings say".

    Written as `"20m"` by hand as often as `1200`, because the setting it
    overrides is a duration and the file is meant to be editable.
    """
    if value is None or value == "":
        return None
    # A number is already seconds. `parse_duration` takes text -- it is for
    # what a person types -- and handing it 1200 raised, so a figure this
    # file had written itself would not read back.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        from .options import parse_duration

        return float(parse_duration(str(value)))
    except Exception:
        log.warning("could not read %r as a length of time; using the "
                    "configured one", value)
        return None


def from_dict(raw: dict[str, Any], path: Path | None = None) -> Register:
    made: list[Station] = []
    for name, entry in (raw.get("stations") or {}).items():
        if not isinstance(entry, dict):
            log.warning("[stations.%s] is not a section; ignoring it", name)
            continue
        driver = str(entry.get("driver") or "").strip()
        identity = str(entry.get("identity") or "").strip()
        if not driver or not identity:
            # Reported, not dropped in silence. A station missing one of these
            # takes no readings, and the operator would see a console that
            # uploads and a page that says nothing arrived.
            log.warning("[stations.%s] has no %s; it will take no readings",
                        name, "driver" if not driver else "identity")
            continue
        made.append(Station(
            name=str(name),
            driver=driver,
            identity=identity,
            archive=str(entry.get("archive") or DEFAULT_ARCHIVE),
            role=str(entry.get("role") or "main"),
            channel=int(entry.get("channel") or 0),
            note=str(entry.get("note") or ""),
            learnt=bool(entry.get("learnt", False)),
            indoor=bool(entry.get("indoor", True)),
            model=str(entry.get("model") or ""),
            field_map={str(k): str(v) for k, v
                       in (entry.get("field_map") or {}).items()},
            max_behind=_seconds(entry.get("max_behind")),
            max_ahead=_seconds(entry.get("max_ahead")),
        ))
    return Register(stations=made, path=path)


def save(path: str | Path, register: Register, note: str = "") -> Path:
    """Write stations.toml, keeping the previous one.

    Written beside and moved into place, like the configuration and
    `plots.toml`: this file decides whose readings are taken, and an
    interrupted write must not leave half of it.
    """
    import shutil
    import tomllib

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render(register, note)

    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(text, encoding="utf-8")
    with open(partial, "rb") as fp:
        tomllib.load(fp)  # what was written, not what we meant to write
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    partial.replace(path)
    return path


def render(register: Register, note: str = "") -> str:
    """The stations as a TOML file somebody can edit."""
    out = [
        "# The consoles this installation takes readings from.",
        "#",
        "# Each station has a driver that reads its uploads, an identity that",
        "# tells its packets apart, and the archive it writes into. The name is",
        "# also what `sources.toml` matches its rules against.",
        "#",
        "# Written by weewx-evo, and editable by hand. An identity beginning",
        "# with `evo-` was handed out by the settings page and belongs in the",
        "# console's own configuration; anything else was read off the hardware.",
    ]
    if note:
        out += ["#", *[f"# {line}" for line in note.splitlines()]]
    out.append("")

    for one in sorted(register.stations, key=lambda s: s.name):
        out.append(f"[stations.{one.name}]")
        out.append(f'driver = "{_escape(one.driver)}"')
        out.append(f'identity = "{_escape(one.identity)}"')
        out.append(f'archive = "{_escape(one.archive)}"')
        if one.role != "main":
            out.append(f'role = "{_escape(one.role)}"')
            if one.channel:
                out.append(f"channel = {one.channel}")
        if one.learnt:
            out.append("learnt = true")
        if not one.indoor:
            out.append("indoor = false")
        if one.model:
            out.append(f'model = "{_escape(one.model)}"')
        # Only when this console differs from the configured figure. Writing
        # the default out would freeze it: a later change to the setting
        # would then reach every console except the ones already listed.
        if one.max_behind is not None:
            out.append(f"max_behind = {one.max_behind:g}")
        if one.max_ahead is not None:
            out.append(f"max_ahead = {one.max_ahead:g}")
        if one.note:
            out.append(f'note = "{_escape(one.note)}"')
        if one.field_map:
            out.append("")
            out.append(f"[stations.{one.name}.field_map]")
            for their, ours in sorted(one.field_map.items()):
                out.append(f'"{_escape(their)}" = "{_escape(ours)}"')
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')

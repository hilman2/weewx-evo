"""The consoles this installation takes readings from.

A **station** is a thing that uploads. It has a name somebody chose, the
driver that reads it, and an identity that tells its packets apart from
everybody else's. It also holds settings intrinsic to that console, such as
its model and clock tolerance. How a series treats its readings belongs to
that archive's member policy.

    [stations.kirchdorf]
    driver = "wunderground"
    identity = "evo-3f9a2c"

Which measurement series takes those readings is not a property of the
console. Archives name their consoles, so one console may feed no series, one
series, or several without a second and conflicting answer in this file.

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
database, and `last_seen` is not stored anywhere at all: the live table already
knows when a packet with that driver and identity arrived, so keeping a second
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

#: What an identity we hand out looks like. Short because some firmware limits
#: the field, lower case because some consoles upper-case what is typed into
#: them, and prefixed so it is recognisable as ours in somebody's log.
IDENTITY_PREFIX = "evo-"
IDENTITY_DIGITS = 6

#: A station display name, as it appears in the admin URL.
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: Settings that lived on a Station before one console could feed several
#: archives.  They remain readable for the staged migration in `archives.py`;
#: new runtime authority is `Archive.members`.
LEGACY_MEMBER_FIELDS = ("role", "channel", "indoor")


@dataclass(frozen=True, slots=True)
class Station:
    """One console, announced."""

    #: What people call it. Published as display metadata in the live sender
    #: directory; archive routing uses the canonical driver/identity key.
    name: str
    #: Which driver reads its uploads.
    driver: str
    #: What tells its packets apart. A PASSKEY, a serial, or one we handed out.
    identity: str
    #: Whatever the operator wants to remember about it.
    note: str = ""
    #: True when the identity came from the hardware rather than from us. Only
    #: used to word the page: one is copied onto the console, the other is
    #: read off it.
    learnt: bool = False

    #: What the hardware is, for the page and the log. Cosmetic, and a
    #: property of this box rather than of the protocol it speaks.
    model: str = ""
    #: A station-owned field map from older configurations. Runtime placement
    #: never reads it; it is retained only so ``placement import`` can move the
    #: decisions to the Place-scoped placement file without losing them.
    field_map: dict[str, str] = field(default_factory=dict)
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
    #: Old station-owned role settings, retained only so a station-file save
    #: cannot erase them before `archives.toml` has copied them. No runtime
    #: caller reads this; the archive migration clears it after committing
    #: the canonical member policies.
    _legacy_member: dict[str, Any] = field(
        default_factory=dict, repr=False, compare=False)

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

    def drivers(self) -> set[str]:
        return {one.driver for one in self.stations}

    def identities_for(self, driver: str) -> set[str]:
        return {one.identity.casefold() for one in self.stations
                if one.driver == driver}

    # -- changing them -------------------------------------------------

    def add(self, station: Station) -> Station:
        """Announce a station. Raises if the name or the identity is taken.

        Refused rather than merged: display names must identify one sender,
        and two stations sharing an identity is the failure this whole module
        exists to make impossible.
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

        Packets are stored under driver and identity, so renaming changes only
        the name looked up for them. The journal itself does not have to be
        rewritten.
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


def legacy_member_settings(path: str | Path) -> dict[str, dict[str, Any]]:
    """Old role/channel/indoor values, without making them runtime authority.

    Only complete station announcements count, exactly as in `from_dict`.
    Values are deliberately returned uncoerced: `archives.MemberPolicy`
    validates them before committing the one-time migration, so a quoted
    ``"false"`` cannot quietly become true and an extra source without a
    usable channel cannot start writing main columns.
    """
    import tomllib

    path = Path(path)
    if not path.exists():
        return {}
    with open(path, "rb") as fp:
        raw = tomllib.load(fp)
    found: dict[str, dict[str, Any]] = {}
    for name, entry in (raw.get("stations") or {}).items():
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("driver") or "").strip():
            continue
        if not str(entry.get("identity") or "").strip():
            continue
        policy = {field_name: entry[field_name]
                  for field_name in LEGACY_MEMBER_FIELDS
                  if field_name in entry}
        if policy:
            found[str(name)] = policy
    return found


def clear_legacy_member_settings(path: str | Path) -> bool:
    """Remove copied role settings from a writable station file.

    Called only after ``archives.toml`` has committed the versioned member
    policies. A read-only split deployment may leave the obsolete keys on
    disk; they remain harmless because no Station exposes them and a marked
    archive registry never consults them again.
    """
    path = Path(path)
    register = load(path)
    if not any(one._legacy_member for one in register):
        return False
    register.stations = [replace(one, _legacy_member={})
                         for one in register.stations]
    save(path, register, "member policies moved to archives.toml")
    return True


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
            # `archive` may be present in a file written by an older version.
            # It is deliberately ignored: archives own that relationship now,
            # and keeping a second answer here would let the two disagree.
            note=str(entry.get("note") or ""),
            learnt=bool(entry.get("learnt", False)),
            model=str(entry.get("model") or ""),
            field_map={str(k): str(v) for k, v
                       in (entry.get("field_map") or {}).items()},
            max_behind=_seconds(entry.get("max_behind")),
            max_ahead=_seconds(entry.get("max_ahead")),
            _legacy_member={field_name: entry[field_name]
                            for field_name in LEGACY_MEMBER_FIELDS
                            if field_name in entry},
        ))
    return Register(stations=made, path=path)


def save(path: str | Path, register: Register, note: str = "") -> Path:
    """Write stations.toml, keeping the previous one.

    Written beside and moved into place, like the configuration and
    `plots.toml`: this file decides which identity has which name and console
    settings, and an interrupted write must not leave half of it.
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
        "# Each station has a driver that reads its uploads and an identity",
        "# that tells its packets apart. The name is display metadata only;",
        "# archives select canonical sender IDs from the live database.",
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
        if one.learnt:
            out.append("learnt = true")
        # Only until the place registry has committed the migration. Keeping
        # the raw values here makes a listener-only station edit lossless;
        # they are not attributes of Station and never affect routing.
        for field_name in LEGACY_MEMBER_FIELDS:
            if field_name in one._legacy_member:
                out.append(f"{field_name} = "
                           f"{_toml_scalar(one._legacy_member[field_name])}")
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


def _toml_scalar(value: Any) -> str:
    """A legacy scalar, preserved until its archive migration commits."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return f'"{_escape(str(value))}"'


def _escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')

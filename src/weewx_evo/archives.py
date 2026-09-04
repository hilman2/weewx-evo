"""The measurement series this installation keeps, and where each one is.

An **archive** is a series for one *place*. It has a file, a name to print on
a page, and the three numbers every formula about the sky needs: latitude,
longitude and altitude. It selects station readings from `live`; feeds read
out of it.

    [archives.nordfeld]
    file = "data/nordfeld.sdb"
    label = "Nordfeld"
    latitude = 48.4012
    longitude = 11.6301
    altitude = 452.0

One archive is the ordinary case, but it is still an archive and is still
described here. An installation with no file at all has one anyway: the
`station.*` and `archive_db` settings are written out once as
`[archives.default]`. From then on this file is the authority.

The second archive is why `station.*` had to stop being global. Sunrise,
pressure reduction, evapotranspiration and every skin hang off those three
numbers, and with two sites a global one is not merely wrong -- it is
plausibly wrong. Sunrise for the north field, computed with the south field's
coordinates, differs by seconds and looks entirely correct.

## Where the values come from

    no archives.toml        write the settings out as one place, atomically
    archives.toml exists    read only this list

There is no live fallback to the old settings. A misspelled archive name or a
broken file must fail where it is read; silently choosing another place mixes
correct-looking readings under the wrong name.

## What is not here

A timezone. `archive_day_*` is keyed on local midnight, so a per-archive
timezone means every aggregate has to be told which one -- that is a change to
the arithmetic, not to the configuration, and this file is not the place to
pretend otherwise. Sites in different zones remain a real case and an open
question.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar

log = logging.getLogger(__name__)

FILENAME = "archives.toml"

#: The name the settings become when they are written out as one place. Not
#: an archive silently supplied at runtime: it exists only when the file
#: names it.
DEFAULT = "default"

#: The same shape as a station name: this ends up in a filename and in a URL.
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: Which settings become the first archive.
FROM_SETTINGS = ("archive_db", "station.name", "station.latitude",
                 "station.longitude", "station.altitude", "station.url",
                 "station.rain_year_start")


@dataclass(frozen=True, slots=True)
class MemberPolicy:
    """How one archive treats one of the senders it selects.

    Whether a sender is the primary one is not here: that is `primary` on the
    archive, because "exactly one" is a property of the place and not of N
    independent members. See `roles.py`.

    What is left is relative to the series all the same. The same console can
    have an indoor reading worth a column in one place and deliberately
    absent from another.
    """

    indoor: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.indoor, bool):
            raise ValueError("member indoor is true or false")

    #: Settings this used to have, and what replaced each. Refused like any
    #: other unknown key -- reading and ignoring one would leave a place
    #: working with a line in it that means nothing, which is how somebody
    #: spends an afternoon on a setting that was never applied.
    #:
    #: What they get instead of "unknown member setting" is what to do. The
    #: message is read by somebody whose station has just refused to start,
    #: and "unknown" is true and no help at all.
    RETIRED: ClassVar[dict[str, str]] = {
        "role": "a place names one primary sender instead, on the Place page",
        "channel": "the Fields page places a reading in the column you choose",
    }

    @classmethod
    def from_dict(cls, raw: Any) -> MemberPolicy:
        """One strictly checked policy from TOML values."""
        if not isinstance(raw, dict):
            raise ValueError("a member policy is a table")
        unknown = set(raw) - {"indoor"}
        retired = sorted(unknown & set(cls.RETIRED))
        if retired:
            raise ValueError(
                "; ".join(f"{name} is no longer a member setting: "
                          f"{cls.RETIRED[name]}" for name in retired)
                + ". Take the line out of the file.")
        if unknown:
            raise ValueError(
                "unknown member setting" + ("s" if len(unknown) != 1 else "")
                + f": {', '.join(sorted(str(one) for one in unknown))}")
        indoor = raw.get("indoor", True)
        if not isinstance(indoor, bool):
            raise ValueError("member indoor is true or false")
        return cls(indoor=indoor)


@dataclass(frozen=True, slots=True)
class Archive:
    """One measurement series, and what is true of the place it measures."""

    name: str
    file: str
    #: What a page calls this place.
    label: str = ""
    latitude: float | None = None
    longitude: float | None = None
    #: Metres above sea level.
    altitude: float | None = None
    url: str = ""
    rain_year_start: int = 1

    #: What this place is drawn in wherever two are drawn together: a line
    #: on a comparison chart, the rule down its row on an overview, its chip
    #: in a sidebar. Here rather than in a skin, for the reason plot
    #: definitions are not in a skin either -- Deck, the image generator and
    #: Grafana would hold three copies, and the day they disagree the same
    #: place is one colour on a page and another in the picture beside it.
    #:
    #: Empty means the renderer picks, and that is the honest default: a
    #: place created for its file alone should not be handed a colour
    #: nobody chose and cannot tell from one they did.
    color: str = ""

    #: Up to four characters, for a chip beside a value and a legend where
    #: the label will not fit. Truncating the label instead gives two places
    #: called "Kirc" the day somebody adds "Kirchdorf Sued".
    code: str = ""

    #: Where this place stands in a list that has no order of its own: the
    #: overview, the compare legend, the sidebar.
    #:
    #: Not the file's line order, and `Register.all()` is deliberately left
    #: alone. Storage order and display order are separate facts.
    order: int = 0

    #: Which senders from the live database feed this series. Values are the
    #: canonical, versioned IDs produced by ``db.live.sender_id``. The public
    #: spelling is :attr:`senders`, and the file spells it ``senders``.
    #:
    #: **None and empty are different answers.** None selects every sender
    #: that arrives, including one nobody has announced; an empty tuple
    #: selects none. Both belong to this archive -- neither is looked up on a
    #: station.
    stations: tuple[str, ...] | None = ()

    #: Per-sender interpretation inside this archive. For an explicit
    #: selection this table is also the selection: it is normalised to exactly
    #: the IDs in ``stations``. This keeps one writable authority rather than
    #: a list and a policy table that can disagree. In broad mode it contains
    #: optional overrides; unlisted live senders use ``MemberPolicy()``.
    members: dict[str, MemberPolicy] = field(default_factory=dict)

    #: The canonical ID of the sender this series is taken from. Every other
    #: member writes only what has been placed by hand -> `roles.py`.
    #:
    #: One field holding one ID, rather than a role on each member, is what
    #: makes "two primaries" unsayable instead of merely invalid. It was
    #: sayable before, nothing rejected it, and the archiver then accumulated
    #: both into the same columns -- which for `rain` is a sum, so two
    #: consoles reporting 1 mm stored 2.
    #:
    #: Empty means nobody has said. `primary_sender` answers it then; the
    #: settings page writes it out whenever a place is saved, so an empty one
    #: is a hand-written file or a place nobody has opened yet.
    primary: str = ""

    def __post_init__(self) -> None:
        made: dict[str, MemberPolicy] = {}
        try:
            entries = self.members.items()
        except AttributeError as exc:
            raise ValueError("archive members is a table") from exc
        for raw_name, raw_policy in entries:
            name = str(raw_name)
            policy = (raw_policy if isinstance(raw_policy, MemberPolicy)
                      else MemberPolicy.from_dict(raw_policy))
            made[name] = policy

        if self.stations is not None:
            selected = tuple(dict.fromkeys(str(one) for one in self.stations))
            # Policy entries and selection become one fact in memory too.
            # A removed sender loses its policy; adding it later starts with
            # the explicit ordinary defaults instead of reviving stale state.
            made = {name: made.get(name, MemberPolicy()) for name in selected}
            object.__setattr__(self, "stations", selected)
        # Frozen protects assignment, not a caller mutating a dict it retained.
        # Keep our own copy so an Archive remains a stable configuration value.
        object.__setattr__(self, "members", made)

        primary = str(self.primary).strip()
        if primary and self.stations is not None and primary not in self.stations:
            # A primary that is not a member is a place whose series comes
            # from a sender it does not read. Silently dropping it would make
            # the next sender in the list the series without anybody saying
            # so, which is the whole failure this field exists to prevent.
            raise ValueError(
                f"archive {self.name!r} takes its primary readings from "
                f"{primary!r}, which it does not select")
        object.__setattr__(self, "primary", primary)

    @property
    def title(self) -> str:
        """What to print. The label if there is one, else the name."""
        return self.label or self.name

    def place(self) -> dict[str, Any]:
        """The three numbers, in the shape `derive.Station` wants them."""
        return {"latitude": self.latitude, "longitude": self.longitude,
                "altitude": self.altitude}

    def as_dict(self) -> dict[str, Any]:
        names = [name for name, _read_as in FIELDS]
        names.extend(EXTRA_FIELDS)
        return {name: getattr(self, name) for name in names}

    def policy_for(self, station: str) -> MemberPolicy:
        """How this archive treats one sender; defaults are intentionally plain."""
        return self.members.get(station, MemberPolicy())

    def primary_sender(self, known: Iterable[Any] = ()) -> str:
        """Which sender this series is taken from, or `""` if it has none.

        `known` is the live sender directory, as `db.live.LiveStore.senders`
        returns it. It settles the case nobody has settled: the earliest
        sender this place selects becomes its primary, so a console plugged
        in this afternoon cannot take over a series that predates it. That
        rule needs `first_seen`, which is why the directory is asked rather
        than the file.

        The one answer to derive it from and never write back. Written down,
        an install that once had a second sender would keep whatever was
        derived on the day it did -- and a place restored from a backup would
        need the same value to have survived. Derived, it is a fact about the
        senders that are here.
        """
        chosen = self.primary
        if chosen and self.selects(chosen):
            return chosen

        heard: list[tuple[float, str]] = []
        for one in known:
            sender = str(getattr(one, "sender", one))
            when = float(getattr(one, "first_seen", 0.0) or 0.0)
            # 0 is "announced but never heard": a sender named in the station
            # file that has sent nothing. It cannot be the series, and sorting
            # it in would put it first of all.
            if when > 0 and self.selects(sender):
                heard.append((when, sender))
        if heard:
            return min(heard)[1]

        # Nothing has been heard yet. A hand-written selection still has an
        # order somebody typed, and its first entry is the best reading of it.
        return self.senders[0] if self.senders else ""

    def role_of(self, sender: str, known: Iterable[Any] = (),
                primary: str | None = None) -> str:
        """`roles.MAIN` for the sender this series comes from, else `roles.EXTRA`.

        `primary` short-circuits the derivation for a caller that has already
        done it. `Placer` works it out once per directory read and asks this
        for every packet of a span, and a rebuild is millions of them.

        A place that can name no primary at all reports every sender as its
        series. That is the single-console case -- nobody has said, nothing
        has been heard, and there is nothing to collide with. The state worth
        preventing is *several* primaries; answering "none" with a refusal to
        place anything would be a place that silently stops recording, which
        is a worse failure than the one being prevented.
        """
        from . import roles

        if primary is None:
            primary = self.primary_sender(known)
        if not primary:
            return roles.MAIN
        return roles.MAIN if sender == primary else roles.EXTRA

    @property
    def senders(self) -> tuple[str, ...] | None:
        """Canonical live sender IDs selected by this place.

        ``None`` is the explicit broad selection: every arrival, including a
        console nobody has announced. The storage name is deliberately hidden
        behind this property so nothing mistakes a display name for the
        journal identity.
        """
        return self.stations

    def selects(self, sender: str) -> bool:
        """Whether this place reads one canonical sender ID."""
        return self.senders is None or sender in self.senders


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or(fallback: int) -> Any:
    """Read a whole number, or the value that means "nothing said"."""
    def read(value: Any) -> int:
        found = _number(value)
        return fallback if found is None else int(found)
    return read


#: Every field of an `Archive` beyond its name, and how to read one out of
#: the file. One table rather than three hand-written walkers, because the
#: failure when the three disagree is silent and delayed: the value is
#: accepted, shown back once from the form, and gone at the next save. That
#: is exactly how `url` and `rain_year_start` came to be readable by the
#: settings page and written back by nothing.
FIELDS: tuple[tuple[str, Any], ...] = (
    ("file", str),
    ("label", str),
    ("latitude", _number),
    ("longitude", _number),
    ("altitude", _number),
    ("url", str),
    ("rain_year_start", _int_or(1)),
    ("color", str),
    ("code", str),
    ("order", _int_or(0)),
)

#: Fields the settings page does not offer as a text box, so they are not in
#: `FIELDS`. `stations` is a list and its own page; putting it in the table
#: would render it as a line of text somebody could half-edit. `primary` is
#: one of those IDs and is chosen beside them, for the same reason.
EXTRA_FIELDS: tuple[str, ...] = ("stations", "members", "primary")


def _sender_ids(value: Any, *, missing: tuple[str, ...] | None = ()) \
        -> tuple[str, ...] | None:
    """Canonical sender IDs, or ``None`` for an explicit ``*``.

    Missing means empty for the sender-owned format. That fail-closed default
    is deliberate: a typo or partially-written place must never start reading
    every station in the shared journal.
    """
    if value is None:
        return missing
    if isinstance(value, str):
        text = value.strip()
        values: Any = None if text == "*" else ((text,) if text else ())
        if values is None:
            return None
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        raise ValueError("senders is '*' or a list of canonical sender IDs")
    from .db.live import sender_parts

    found: list[str] = []
    try:
        for one in values:
            sender = str(one).strip()
            if not sender or sender in found:
                continue
            sender_parts(sender)
            found.append(sender)
    except TypeError as exc:
        raise ValueError(
            "senders is '*' or a list of canonical sender IDs") from exc
    return tuple(found)


def _primary(value: Any, archive: str) -> str:
    """The canonical sender ID a place takes its readings from.

    Checked here rather than shrugged at, because the failure of a mistyped
    one is invisible: the place would fall back to its earliest sender and
    keep working, and the line saying otherwise would sit in the file being
    read every restart and doing nothing.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(
            f"[archives.{archive}] primary is one canonical sender ID")
    sender = value.strip()
    if not sender:
        return ""
    from .db.live import sender_parts

    try:
        sender_parts(sender)
    except ValueError as exc:
        raise ValueError(
            f"[archives.{archive}] primary is not a sender ID: "
            f"{sender!r}") from exc
    return sender


def _members(value: Any, archive: str) -> dict[str, MemberPolicy]:
    """Strict member policies from one archive table."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"[archives.{archive}.members] is not a table")
    found: dict[str, MemberPolicy] = {}
    from .db.live import sender_parts

    for raw_name, raw_policy in value.items():
        name = str(raw_name)
        try:
            sender_parts(name)
        except ValueError as exc:
            raise ValueError(
                f"[archives.{archive}.members] has invalid sender ID "
                f"{name!r}") from exc
        try:
            found[name] = MemberPolicy.from_dict(raw_policy)
        except ValueError as exc:
            raise ValueError(
                f"[archives.{archive}.members.{name}]: {exc}") from exc
    return found

#: Eight hues a place can be given when nobody chose one, mid-lightness so
#: each reads on both the light and the dark ground. Assigned by position.
#:
#: `plots.LINE_COLORS` cannot do this job and it is worth saying why: it
#: cycles five colours modulo the index *within one plot*, so the same place
#: comes out blue on the temperature chart and red on the humidity chart --
#: and a chip saying a place *is* a colour would then be lying on every
#: second card.
PLACE_COLORS = ("#4282b4", "#d1642a", "#3d8f5c", "#8a5cc4",
                "#b44242", "#2f9ba6", "#a67c22", "#c4569a")

#: Names a place may not take, because its pages are published in a
#: directory of that name at the root of a site.
#:
#: Deck's page names are listed in the core, and that is a layering
#: inversion taken deliberately: asking a skin would mean importing one in
#: order to check a name, which fails on an installation that has no skin --
#: and the failure would be silent permission to create the collision.
#: `tools/archives_test.py` keeps the list honest by measuring what the
#: bundled skins actually write.
#:
#: Two of them are nobody's skin. `api` is matched by the web server
#: *before* the feeds, so a place called `api` would be reachable and then
#: not be. `names` is a method on `tags.Archives`, and a place called
#: `names` takes the word out of the template namespace -- every
#: `$archives.names()` becomes "cannot find 'names'".
RESERVED = frozenset({
    "api", "names", "data", "json", "assets", "vendor", "lang", "includes",
    "icons", "noaa", "day-archive",
    "index", "week", "month", "year", "yesterday", "statistics",
    "celestial", "sensor-status", "computer-monitor", "externals",
    "offline", "manifest", "compare", "places", "overview",
})

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_CODE = re.compile(r"^[A-Za-z0-9]{1,4}$")


def from_settings(cfg: Any) -> Archive:
    """The one place an installation's `station.*` settings describe.

    Read only where there is no `archives.toml` yet, and never a live
    fallback: `Register.load` writes the result to the file before returning
    it, and from then on the file is the authority.
    """
    return Archive(
        name=DEFAULT,
        file=str(cfg.get("archive_db") or "data/weewx.sdb"),
        label=str(cfg.get("station.name") or ""),
        latitude=_number(cfg.get("station.latitude")),
        longitude=_number(cfg.get("station.longitude")),
        altitude=_number(cfg.get("station.altitude")),
        url=str(cfg.get("station.url") or ""),
        rain_year_start=int(cfg.get("station.rain_year_start") or 1),
        # Every arrival, written out explicitly. An installation with one
        # place has nothing to tell apart, and a console plugged in next
        # week must reach it without anybody selecting it first.
        stations=None,
    )


#: How far a place may sit from the process's timezone before the daily
#: statistics stop meaning what they say. Solar time and clock time differ by
#: up to about an hour and a half inside a single zone -- Spain runs an hour
#: ahead of its own sun, western China two and a half -- so anything under two
#: hours is normal and worth no words. Beyond that, the day is starting at the
#: wrong end of the morning.
TIMEZONE_TOLERANCE = 2.0


def timezone_gap(archive: Archive, now: float | None = None) -> float | None:
    """Hours between this place's sun and the clock this process keeps.

    None when the archive has no longitude, because then there is nothing to
    compare and guessing would be worse than silence.

    Longitude rather than a configured zone, because longitude is already
    there: it had to be, for sunrise. A place at 174.8 degrees east keeps a
    day that begins twelve hours before UTC, whatever this machine thinks.
    """
    if archive.longitude is None:
        return None
    import datetime

    when = (datetime.datetime.fromtimestamp(now) if now is not None
            else datetime.datetime.now())
    offset = when.astimezone().utcoffset()
    if offset is None:  # pragma: no cover - a clock with no zone at all
        return None
    return archive.longitude / 15.0 - offset.total_seconds() / 3600.0


def timezone_concern(archive: Archive, now: float | None = None) -> str:
    """Why this archive's days may not be its days, or an empty string.

    Said rather than fixed. The fix is to run this archive's archiver in its
    own process with TZ set, which is a deployment decision -- and one this
    program must not make on somebody's behalf by quietly writing days at a
    boundary they did not choose.
    """
    gap = timezone_gap(archive, now)
    if gap is None or abs(gap) < TIMEZONE_TOLERANCE:
        return ""
    where = "east" if archive.longitude >= 0 else "west"
    return (f"{abs(archive.longitude):.1f}° {where} is about "
            f"{abs(gap):.0f} h from this process's timezone. Daily "
            f"statistics for this series use this machine's midnight, not "
            f"the one where it stands. Run its archiver separately with TZ "
            f"set to fix it.")


class Register:
    """Every archive, and which file each one is.

    Re-read when the file changes, for the same reason the station register
    is: the page that writes it and the archiver that reads it are different
    processes, and on a split deployment they are different machines.
    """

    def __init__(self, archives: list[Archive], path: Path | None = None) -> None:
        self.archives = archives
        self.path = path
        self._mtime: float | None = None
        if path is not None and path.exists():
            self._mtime = path.stat().st_mtime

    # -- reading -------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None, cfg: Any = None) -> Register:
        """Read the list without consulting listener configuration.

        A present file is the whole answer. In particular, this method never
        opens ``stations.toml``: it is on the Archiver path, and the Archiver
        knows only the live database and this Place configuration.

        With no file, `station.*` in the settings is the one place, and it is
        written out here. That is how an installation that has never needed a
        second series gets its first file, without anything to fill in.
        """
        if path is None:
            raise ValueError("archives.toml needs a path")
        path = Path(path)
        if not path.exists():
            if cfg is None:
                raise FileNotFoundError(path)
            log.info("writing the one place from the settings to %s", path)
            register = cls([from_settings(cfg)], path)
            register.save(path)
            return register
        found = _read(path)
        if not found:
            raise ValueError(f"{path} defines no archives")
        return cls(found, path)

    def refresh(self) -> bool:
        """Re-read if the file has changed. True when something did."""
        if self.path is None:
            return False
        try:
            now = self.path.stat().st_mtime if self.path.exists() else None
        except OSError:
            return False
        if now == self._mtime:
            return False
        self._mtime = now
        if now is None:
            log.error("%s disappeared; keeping the archives already loaded",
                      self.path)
            return False
        try:
            self.archives = _read(self.path)
        except Exception:
            log.exception("could not re-read %s; keeping what was loaded",
                          self.path)
            return False
        log.info("%s changed: %d archive(s) (%s)", self.path,
                 len(self), ", ".join(self.names()))
        return True

    # -- looking things up ---------------------------------------------

    def __len__(self) -> int:
        return len(self.all())

    def __iter__(self):
        return iter(self.all())

    def all(self) -> list[Archive]:
        """Every archive the file names, in storage order."""
        return list(self.archives)

    def names(self) -> list[str]:
        return [one.name for one in self.all()]

    def default_name(self) -> str:
        """The unambiguous implicit name, or a clear refusal.

        A literal `[archives.default]` is an explicit choice in the file. A
        sole differently named archive is unambiguous too. With several and
        no such entry, the caller must name one.
        """
        if len(self.archives) == 1:
            return self.archives[0].name
        if any(one.name == DEFAULT for one in self.archives):
            return DEFAULT
        if not self.archives:
            raise LookupError("archives.toml defines no archives")
        raise LookupError("more than one archive exists; name one")

    def get(self, name: str | None) -> Archive:
        """One archive by exact name.

        `None` is accepted only through `default_name`; an unknown non-empty
        name never redirects to another archive.
        """
        wanted = self.default_name() if name in (None, "") else str(name)
        for one in self.archives:
            if one.name == wanted:
                return one
        known = ", ".join(self.names()) or "none"
        raise KeyError(f"no archive called {wanted!r}; configured: {known}")

    def ordered(self) -> list[Archive]:
        """Every place, in the order pages present them.

        Separate from `all()` on purpose, and the docstring on `Archive.order`
        says why: `all()` is the storage order with the default first, and
        three things depend on that.
        """
        found = self.all()
        return sorted(found, key=lambda one: (one.order, found.index(one)))

    def presented(self) -> list[Archive]:
        """The same list with a colour and a short code filled in.

        For renderers, never for saving. Writing these back would turn "the
        renderer picks" into a choice somebody appears to have made, and the
        next release's palette would then not reach any station that had
        ever opened the page.
        """
        # The colour comes from where a place sits in the *file*, not from
        # where it sits in the list. Dragging a place up a settings page
        # must not repaint it: the colour is how somebody recognises it on
        # the chart they were looking at a minute ago.
        stored = [one.name for one in self.all()]
        out: list[Archive] = []
        taken: set[str] = set()
        for one in self.ordered():
            code = one.code or _short(one.title or one.name, taken)
            taken.add(code.casefold())
            position = stored.index(one.name) if one.name in stored else 0
            out.append(replace(
                one,
                color=one.color or PLACE_COLORS[position % len(PLACE_COLORS)],
                code=code))
        return out

    def several(self) -> bool:
        """Whether anything has to be told apart in the presentation."""
        return len(self.all()) > 1

    def overriding(self) -> bool:
        """Compatibility answer: a loaded register always comes from the file."""
        return self.path is not None

    def concerns(self, now: float | None = None) -> dict[str, str]:
        """What is wrong with this arrangement, by archive name.

        Empty is the ordinary answer. It exists because the one thing that
        can be wrong here is wrong *silently*: readings stay correct and only
        the day boundaries move, so nothing fails and nothing looks odd.
        """
        found = {}
        for one in self.all():
            said = timezone_concern(one, now)
            if said:
                found[one.name] = said
        return found

    # -- changing them -------------------------------------------------

    def add(self, archive: Archive) -> Archive:
        problem = self.why_not(archive)
        if problem:
            raise ValueError(problem)
        self.archives.append(archive)
        return archive

    def replace(self, name: str, archive: Archive) -> None:
        for n, one in enumerate(self.archives):
            if one.name == name:
                self.archives[n] = archive
                return
        self.archives.append(archive)

    def remove(self, name: str) -> bool:
        """Take an archive off the list. The file is left where it is.

        Deliberately not deleted. It holds the readings, `archive_day_*` in it
        cannot be rebuilt from anywhere else, and an operator who wanted the
        file gone can say so to their own filesystem.
        """
        if name == DEFAULT:
            raise ValueError("the default archive cannot be removed")
        before = len(self.archives)
        self.archives = [one for one in self.archives if one.name != name]
        return len(self.archives) != before

    def why_not(self, archive: Archive, replacing: str | None = None) -> str:
        """Why this archive cannot be added, or an empty string."""
        if not _NAME.match(archive.name or ""):
            return ("a name is lower case letters, digits, dashes and "
                    "underscores, up to 64 of them")
        if not (archive.file or "").strip():
            return "an archive needs a file to keep its readings in"
        if archive.name.lower() in RESERVED:
            # Named as a collision rather than as a rule. "Invalid name"
            # sends somebody looking for a syntax; this sends them to a
            # different name, which is what they actually need.
            return (f"a place's pages are published in a directory of its "
                    f"own name, and {archive.name!r} is already a page or a "
                    f"directory of a published site. Try "
                    f"{archive.name}feld, or {archive.name}-nord.")
        if archive.name.isdigit():
            # A place name is three things at once: a directory at the root
            # of a published site, a key in `live.json`, and a `data-archive`
            # attribute. PHP has one array type, so `{"archives": {"0": ...}}`
            # comes back out of `live.php` as `{"archives": [...]}` and every
            # lookup on the page finds nothing -- one place called `0` is
            # enough, the names do not have to run 0..n.
            return ("a place cannot be called by a number alone: it becomes "
                    "a key in a file that a web host rewrites, and a numeric "
                    "key comes back as a position. Try "
                    f"feld{archive.name}.")
        if archive.color and not _HEX.match(archive.color):
            # Refused rather than warned about: an unreadable colour renders
            # as black, and black is already what "nobody said" looks like
            # in this skin's icon set -- so the two would be
            # indistinguishable on the one page that exists to tell them
            # apart.
            return (f"{archive.color!r} is not a colour. Write it as "
                    "#2f6f4e, or leave it empty to have one picked.")
        if archive.code and not _CODE.match(archive.code):
            return "a short code is one to four letters or digits"
        for one in self.all():
            if one.name == replacing:
                continue
            if one.name == archive.name:
                return f"there is already an archive called {archive.name!r}"
            if Path(one.file) == Path(archive.file):
                return (f"{one.name!r} already keeps its readings in "
                        f"{archive.file!r}, and two series in one file is one "
                        "series with the readings mixed")
            if archive.code and one.code.casefold() == archive.code.casefold():
                # A chip that means two places is worse than no chip: it is
                # read as an answer.
                return (f"{one.name!r} already goes by {one.code!r}")
            if (archive.label
                    and one.label.casefold() == archive.label.casefold()):
                # The label is what a legend prints, and a chart's legend is
                # keyed on it: two places called "Garten" become one legend
                # entry, and pressing one chip removes the other place's
                # line. Refused here rather than made unique when drawn --
                # a legend reading "Garten" and "Garten (2)" answers nobody's
                # question about which garden.
                return (f"{one.name!r} is already called {one.label!r}. "
                        "Two places with one name make one line on a "
                        "comparison chart.")
        return ""

    # -- writing -------------------------------------------------------

    def render(self) -> str:
        lines = [
            "# The measurement series this installation keeps.",
            "#",
            "# Each one is a place: its own file, its own altitude and its own",
            "# coordinates. Its members select sender IDs from the live DB;",
            "# feeds name the archive they read out of.",
            "#",
            "# Written by the settings page. Editing it by hand is fine.",
            "",
        ]
        blank = Archive("", "")
        for one in self.all():
            lines.append(f"[archives.{one.name}]")
            for field_name, _read_as in FIELDS:
                value = getattr(one, field_name)
                # Written only where it says something. `file` is the
                # exception: an archive without one is not an archive, and a
                # file that silently went missing is the failure this whole
                # module exists to make impossible.
                if field_name != "file" and (
                        value in (None, "")
                        or value == getattr(blank, field_name)):
                    continue
                lines.append(f'{field_name} = "{_escape(value)}"'
                             if isinstance(value, str)
                             else f"{field_name} = {value}")
            # Broad and empty are written explicitly. A non-empty explicit
            # selection is the member-table keys themselves; there is no
            # second list that can drift away from its policies.
            if one.senders is None:
                lines.append('senders = "*"')
            elif not one.senders:
                lines.append("senders = []")
            if one.primary:
                lines.append(f'primary = "{_escape(one.primary)}"')
            lines.append("")
            for sender, policy in one.members.items():
                lines.append(
                    f"[archives.{one.name}.members.{_toml_key(sender)}]")
                lines.append("indoor = " + ("true" if policy.indoor else "false"))
                lines.append("")
        return "\n".join(lines)

    def save(self, path: str | Path | None = None) -> Path:
        """Write the file, atomically. Same as the station register."""
        import tomllib

        where = Path(path or self.path or FILENAME)
        where.parent.mkdir(parents=True, exist_ok=True)
        temp = where.with_suffix(where.suffix + ".tmp")
        temp.write_text(self.render(), encoding="utf-8")
        # Parse the bytes that reached disk before replacing the authority
        # every archiver will read. A renderer regression must leave the last
        # valid Place configuration in service.
        with open(temp, "rb") as handle:
            tomllib.load(handle)
        temp.replace(where)
        self.path = where
        self._mtime = where.stat().st_mtime
        return where


def _short(title: str, taken: set[str]) -> str:
    """A code for a place that did not give itself one.

    Letters and digits from the name, three of them, then a digit if that is
    already somebody else's. Deduplicated because the whole point of a code
    is telling two places apart, and two places called NOR is worse than no
    code at all.
    """
    letters = [c for c in str(title) if c.isalnum()]
    stem = ("".join(letters[:3]).upper() or "S")
    if stem.casefold() not in taken:
        return stem
    for n in range(2, 100):
        tried = f"{stem[:3]}{n}"[:4]
        if tried.casefold() not in taken:
            return tried
    return stem


def _escape(value: str) -> str:
    # JSON's string escapes are also TOML basic-string escapes. Unlike the
    # old quote/backslash-only replacement this covers newlines and control
    # characters supplied through an Admin form without escaping Unicode.
    # JSON permits a literal DEL while TOML does not, so cover that one extra
    # code point explicitly.
    return json.dumps(str(value), ensure_ascii=False)[1:-1].replace(
        "\x7f", "\\u007f")


def _toml_key(value: str) -> str:
    """One quoted TOML key segment.

    Sender IDs contain slashes and percent escapes, so treating them as bare
    table components would either be invalid TOML or change the table shape.
    """
    return f'"{_escape(value)}"'


def _data(path: Path) -> dict[str, Any]:
    import tomllib

    with open(path, "rb") as handle:
        return tomllib.load(handle)






def _read(path: Path, data: dict[str, Any] | None = None) -> list[Archive]:
    data = _data(path) if data is None else data
    found = []
    for name, entry in (data.get("archives") or {}).items():
        if not isinstance(entry, dict):
            log.warning("%s: [archives.%s] is not a table; skipped", path, name)
            continue
        made: dict[str, Any] = {"name": str(name)}
        for field_name, read_as in FIELDS:
            raw = entry.get(field_name)
            made[field_name] = read_as("" if raw is None else raw)
        if "stations" in entry:
            # Said rather than ignored. The selection is `senders`, and a
            # hand-edited file naming the other one would otherwise read as
            # an archive that has deliberately selected nobody.
            raise ValueError(
                f"[archives.{name}] selects with `senders`, not `stations`")
        members = _members(entry.get("members"), str(name))
        made["stations"] = _sender_ids(
            entry.get("senders") if "senders" in entry else None,
            missing=tuple(members))
        made["members"] = members
        made["primary"] = _primary(entry.get("primary"), str(name))
        found.append(Archive(**made))
    return found


class Placed:
    """The settings as one archive sees them.

    Everything that formats or draws a page reads `station.latitude` and its
    two neighbours out of the settings. There are about fifty such reads
    across eleven files, and rewriting each one to take an archive would be
    fifty chances to miss one -- and the symptom of a missed one is a sunrise
    that is wrong by seconds on a page where everything else is right.

    So the settings are wrapped instead. A feed reading the north field gets
    the north field's numbers from the name it has always used, and nothing
    downstream had to be told that archives exist.

    Everything else passes straight through, `.config` and the rest included:
    this is a view of the settings, not a copy, and a copy would go stale the
    moment somebody saved the page.
    """

    #: Which names this answers for. `station.name` is here because a page
    #: prints it, and with two sites printing the same one is the clearest
    #: possible way to publish the wrong field's readings.
    #: `archive_db` is deliberately **not** here, and it was for a while.
    #: The reason it was: the forecast store is derived from it, so a placed
    #: `archive_db` looked like the way to give each place its own forecast.
    #: The reason it is not: there is one forecast file for the whole
    #: installation and its rows name the series they are for, so a placed
    #: `archive_db` sent every page but the default's to a file nothing
    #: writes -- measured on a live two-place instance, where the second
    #: place's pages carried no forecast section at all.
    PLACE: ClassVar[dict[str, str]] = {
        "station.latitude": "latitude",
        "station.longitude": "longitude",
        "station.altitude": "altitude",
        "station.name": "label",
        "station.url": "url",
        "station.rain_year_start": "rain_year_start",
    }

    def __init__(self, settings: Any, archive: Archive) -> None:
        self.settings = settings
        self.archive = archive

    def get(self, name: str, default: Any = None) -> Any:
        field_name = self.PLACE.get(name)
        if field_name is not None:
            if field_name == "label":
                return self.archive.title
            # A missing coordinate stays missing. Falling through to the old
            # central station.* value would give this place another place's
            # sun and pressure correction while every reading still looked
            # plausible.
            return getattr(self.archive, field_name)
        return self.settings.get(name, default)

    def __getattr__(self, name: str) -> Any:
        # Only reached for what this class does not define, which is
        # everything except `get`.
        return getattr(self.settings, name)


def placed(settings: Any, archive: Archive | None) -> Any:
    """The settings for one archive; a place is required."""
    if archive is None:
        raise ValueError("placed settings need an archive")
    return Placed(settings, archive)

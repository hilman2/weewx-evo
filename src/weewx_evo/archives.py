"""The measurement series this installation keeps, and where each one is.

An **archive** is a series for one *place*. It has a file, a name to print on
a page, and the three numbers every formula about the sky needs: latitude,
longitude and altitude. Stations write into it; feeds read out of it.

    [archives.nordfeld]
    file = "data/nordfeld.sdb"
    label = "Nordfeld"
    latitude = 48.4012
    longitude = 11.6301
    altitude = 452.0

One archive is the ordinary case and it needs no file at all: the settings
already describe it. `station.name`, `station.latitude`, `station.longitude`
and `station.altitude` **are** the default archive, and an installation that
never has a second one never sees this module's file.

The second archive is why `station.*` had to stop being global. Sunrise,
pressure reduction, evapotranspiration and every skin hang off those three
numbers, and with two sites a global one is not merely wrong -- it is
plausibly wrong. Sunrise for the north field, computed with the south field's
coordinates, differs by seconds and looks entirely correct.

## Where the values come from

    no archives.toml        the settings are the one archive
    archives.toml exists    it is the list, and it names the default too

The switch is deliberate and it is the reason there is no migration. The file
appears when somebody adds a second archive, and the page writes the first one
into it at the same time. Until then nothing changed and there is nothing to
change.

The trap that follows: with the file there, `station.altitude` in the settings
is no longer read. Saying nothing about that would be the settings page
appearing to work and doing nothing -- the same failure as an environment
variable quietly beating a saved field. So `overriding()` answers it, and the
page prints it beside the field.

## What is not here

A timezone. `archive_day_*` is keyed on local midnight, so a per-archive
timezone means every aggregate has to be told which one -- that is a change to
the arithmetic, not to the configuration, and this file is not the place to
pretend otherwise. Sites in different zones remain a real case and an open
question.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

log = logging.getLogger(__name__)

FILENAME = "archives.toml"

#: The archive everything writes into when nobody said otherwise. Matches
#: `stations.DEFAULT_ARCHIVE`, which is what a station names.
DEFAULT = "default"

#: The same shape as a station name: this ends up in a filename and in a URL.
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: Which settings the default archive is made of. Named here rather than
#: spelled out at each use, because the settings page has to say which of them
#: have stopped being read once the file exists.
FROM_SETTINGS = ("archive_db", "station.name", "station.latitude",
                 "station.longitude", "station.altitude", "station.url",
                 "station.rain_year_start")


@dataclass(frozen=True, slots=True)
class Archive:
    """One measurement series, and what is true of the place it measures."""

    name: str
    file: str
    #: What a page calls this place. `station.name` for the default one.
    label: str = ""
    latitude: float | None = None
    longitude: float | None = None
    #: Metres above sea level, as `station.altitude` has always been.
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
    #: alone. `cmd_serve` takes `all()[0]` as the default archive, which is
    #: only correct because `add()` inserts the fallback first -- sorting
    #: that list would move the drivers' state, the `status` command and
    #: every feed naming nothing to a different series, silently.
    order: int = 0

    @property
    def title(self) -> str:
        """What to print. The label if there is one, else the name."""
        return self.label or self.name

    def place(self) -> dict[str, Any]:
        """The three numbers, in the shape `derive.Station` wants them."""
        return {"latitude": self.latitude, "longitude": self.longitude,
                "altitude": self.altitude}

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name, _read_as in FIELDS}


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
    """The one archive an installation has before it has two.

    Reads exactly what has always been read, so nothing about a single-site
    installation changes: this object is a view of the settings, not a second
    copy of them.
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

    def __init__(self, archives: list[Archive], path: Path | None = None,
                 fallback: Archive | None = None) -> None:
        self.archives = archives
        self.path = path
        #: What `default` means when the file does not name it. The settings,
        #: which is what every installation had before this module existed.
        self.fallback = fallback
        self._mtime: float | None = None
        if path is not None and path.exists():
            self._mtime = path.stat().st_mtime

    # -- reading -------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None, cfg: Any) -> Register:
        """The list, or the settings where there is no list.

        `cfg` is always used for the fallback even when the file exists, so
        that a file naming only a second archive still has a first one.
        """
        fallback = from_settings(cfg)
        if path is None:
            return cls([], None, fallback)
        path = Path(path)
        if not path.exists():
            return cls([], path, fallback)
        try:
            found = _read(path)
        except Exception:
            # A broken file must not stop the archiver: it would take the
            # series with it, and the series is the thing being protected.
            log.exception("could not read %s; carrying on with the settings "
                          "alone", path)
            return cls([], path, fallback)
        return cls(found, path, fallback)

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
        try:
            self.archives = _read(self.path) if now is not None else []
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
        """Every archive, with the default first.

        The default is here whether or not the file names it. An installation
        whose file lists only `nordfeld` still has the series it had before,
        and dropping it would mean dropping the history in it.
        """
        found = list(self.archives)
        if not any(one.name == DEFAULT for one in found) and self.fallback:
            found.insert(0, self.fallback)
        return found

    def names(self) -> list[str]:
        return [one.name for one in self.all()]

    def get(self, name: str | None) -> Archive:
        """One archive by name, falling back to the default.

        Falling back rather than raising: the name comes from a feed's
        settings or a station's, and one pointing at an archive somebody
        removed must produce a page from the remaining series rather than an
        exception at four in the morning.
        """
        wanted = name or DEFAULT
        for one in self.all():
            if one.name == wanted:
                return one
        if wanted != DEFAULT:
            log.warning("no archive called %r; using %r", wanted, DEFAULT)
        return self.get(DEFAULT) if wanted != DEFAULT else (
            self.fallback or Archive(DEFAULT, "data/weewx.sdb"))

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
        """Whether anything has to be told apart at all.

        The rule that hangs off this: with one archive it takes every packet,
        because that is what it has always done and an installation that never
        heard of stations must keep working. With two, each takes the packets
        of its own stations, because there is nothing left to guess with.
        """
        return len(self.all()) > 1

    def overriding(self) -> bool:
        """Whether the file is what decides, rather than the settings."""
        return bool(self.archives)

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
        # The first write has to carry the default in with it. Otherwise the
        # file says "nordfeld" and the series that has a year of readings in
        # it becomes a fallback nobody can edit.
        if not self.archives and self.fallback:
            self.archives.append(self.fallback)
        self.archives.append(archive)
        return archive

    def replace(self, name: str, archive: Archive) -> None:
        if not self.archives and self.fallback:
            self.archives.append(self.fallback)
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
            "# coordinates. Stations name the archive they write into; feeds",
            "# name the one they read out of.",
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
            lines.append("")
        return "\n".join(lines)

    def save(self, path: str | Path | None = None) -> Path:
        """Write the file, atomically. Same as the station register."""
        where = Path(path or self.path or FILENAME)
        where.parent.mkdir(parents=True, exist_ok=True)
        temp = where.with_suffix(where.suffix + ".tmp")
        temp.write_text(self.render(), encoding="utf-8")
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
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _read(path: Path) -> list[Archive]:
    import tomllib

    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    found = []
    for name, entry in (data.get("archives") or {}).items():
        if not isinstance(entry, dict):
            log.warning("%s: [archives.%s] is not a table; skipped", path, name)
            continue
        made = {"name": str(name)}
        for field_name, read_as in FIELDS:
            raw = entry.get(field_name)
            made[field_name] = read_as("" if raw is None else raw)
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
            value = getattr(self.archive, field_name)
            # An archive that says nothing about its coordinates falls back
            # to the settings rather than to None. A second archive added for
            # its file alone should not silently lose the sun.
            if value not in (None, ""):
                return value
        return self.settings.get(name, default)

    def __getattr__(self, name: str) -> Any:
        # Only reached for what this class does not define, which is
        # everything except `get`.
        return getattr(self.settings, name)


def placed(settings: Any, archive: Archive | None) -> Any:
    """The settings for one archive, or the settings themselves."""
    return settings if archive is None else Placed(settings, archive)

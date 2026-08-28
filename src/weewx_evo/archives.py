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
from dataclasses import dataclass
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

    @property
    def title(self) -> str:
        """What to print. The label if there is one, else the name."""
        return self.label or self.name

    def place(self) -> dict[str, Any]:
        """The three numbers, in the shape `derive.Station` wants them."""
        return {"latitude": self.latitude, "longitude": self.longitude,
                "altitude": self.altitude}

    def as_dict(self) -> dict[str, Any]:
        return {"file": self.file, "label": self.label,
                "latitude": self.latitude, "longitude": self.longitude,
                "altitude": self.altitude, "url": self.url,
                "rain_year_start": self.rain_year_start}


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
        for one in self.all():
            if one.name == replacing:
                continue
            if one.name == archive.name:
                return f"there is already an archive called {archive.name!r}"
            if Path(one.file) == Path(archive.file):
                return (f"{one.name!r} already keeps its readings in "
                        f"{archive.file!r}, and two series in one file is one "
                        "series with the readings mixed")
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
        for one in self.all():
            lines.append(f"[archives.{one.name}]")
            lines.append(f'file = "{_escape(one.file)}"')
            if one.label:
                lines.append(f'label = "{_escape(one.label)}"')
            for field_name in ("latitude", "longitude", "altitude"):
                value = getattr(one, field_name)
                if value is not None:
                    lines.append(f"{field_name} = {value}")
            if one.url:
                lines.append(f'url = "{_escape(one.url)}"')
            if one.rain_year_start != 1:
                lines.append(f"rain_year_start = {one.rain_year_start}")
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
        found.append(Archive(
            name=str(name),
            file=str(entry.get("file") or ""),
            label=str(entry.get("label") or ""),
            latitude=_number(entry.get("latitude")),
            longitude=_number(entry.get("longitude")),
            altitude=_number(entry.get("altitude")),
            url=str(entry.get("url") or ""),
            rain_year_start=int(entry.get("rain_year_start") or 1),
        ))
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

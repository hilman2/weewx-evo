"""Exports: how what a feed produced gets somewhere else.

A feed writes files into a directory. An export takes that directory and puts
it where people can see it -- a web host over FTP, a server over rsync, a
mounted share. The directory is the entire interface between the two: an
export does not know what produced the files and a feed does not know where
they are going.

Two of them are built:

    ftp      FTP and FTPS, which is what shared hosting gives you
    rsync    over SSH, which is what everything else gives you

Both take the same three things: a source, a destination, and what to do about
files that have not changed. That last one is the difference between a useful
export and one people switch off. A weather site is a few hundred files, most
of them identical from one run to the next; sending all of them every five
minutes over a domestic connection saturates it. rsync works this out itself;
FTP cannot, so we remember (see `tracker.py`).

An export is any object with `send()`:

    class MyExport:
        def send(self, source: Path, files: list[Path] | None = None) -> Sent:
            ...

        @staticmethod
        def options():        # the admin page builds a form from this
            return [...]

`files` is what a feed said it changed. None means "look at the directory
yourself", which is what a manual run does.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "weewx_evo.exports"


@dataclass
class Sent:
    """What one run of an export did."""

    sent: int = 0
    skipped: int = 0
    deleted: int = 0
    bytes: int = 0
    seconds: float = 0.0
    #: Files that failed, with why. An export carries on past one bad file:
    #: a permission problem on one page must not hold back the rest of a site.
    failures: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        parts = [f"{self.sent} sent"]
        if self.skipped:
            parts.append(f"{self.skipped} unchanged")
        if self.deleted:
            parts.append(f"{self.deleted} removed")
        if self.bytes:
            parts.append(f"{self.bytes / 1e6:.1f} MB")
        parts.append(f"{self.seconds:.1f}s")
        if self.failures:
            parts.append(f"{len(self.failures)} FAILED")
        return ", ".join(parts)


class ExportError(Exception):
    """Something that stopped an export before it sent anything."""


@runtime_checkable
class Export(Protocol):
    """Files out."""

    def send(self, source: Path, files: list[Path] | None = None) -> Sent:
        """Send `source` to wherever this export sends things.

        `files` is what changed, when the caller knows. None means work it out
        from the directory.

        Raising means nothing was sent and why. Individual files that fail go
        in `Sent.failures` instead, because one unreadable file is not a
        reason to abandon a site.
        """
        ...


class BaseExport:
    """Defaults for an export. Only `send` has to be written."""

    #: Shown on the admin page and in `weewx-evo export list`.
    label: str = "export"

    def send(self, source: Path, files: list[Path] | None = None) -> Sent:
        raise NotImplementedError

    def check(self) -> str:
        """Try the destination and say what happened, without sending.

        The admin page offers this as a button. Getting a wrong password or a
        wrong path back immediately is worth a great deal more than finding
        out at the next archive interval, in a log nobody is reading.
        """
        return "This export cannot be tested without sending something."

    def status(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        """Release anything held. Optional."""


class Registry:
    """The exports this installation has.

    The same shape as the driver registry, and for the same reason: an export
    holds configuration and a little state -- what it has already sent -- and
    that has to survive between runs.
    """

    def __init__(self) -> None:
        self._exports: dict[str, object] = {}
        self._factories: dict[str, Callable[..., object]] = {}
        self._loaded = False

    def register(self, name: str, export: object, replace: bool = False) -> None:
        if name in self._exports and not replace:
            raise ValueError(f"an export named {name!r} is already registered")
        self._exports[name] = export

    def register_factory(self, name: str, factory: Callable[..., object]) -> None:
        self._factories[name] = factory

    def configure(self, name: str, options: dict[str, Any]) -> object | None:
        factory = self._factories.get(name)
        if factory is None:
            return self._exports.get(name)
        try:
            export = factory(**options)
        except Exception:
            log.exception("export %r could not be configured; leaving it out", name)
            return None
        self._exports[name] = export
        return export

    def factory_for(self, kind: str) -> Callable[..., object] | None:
        """The class behind a kind, loading the registry first.

        A method rather than reaching into `_factories`, because reaching in
        skips `load()` and then nothing is registered yet -- which shows up as
        "'ftp' is not one of: ftp, rsync", a message that reads like a joke.
        """
        self.load()
        return self._factories.get(kind)

    def get(self, name: str) -> object | None:
        self.load()
        return self._exports.get(name)

    def known(self, name: str) -> bool:
        self.load()
        return name in self._exports or name in self._factories

    def names(self) -> list[str]:
        self.load()
        return sorted(set(self._exports) | set(self._factories))

    def kinds(self) -> list[str]:
        """The kinds available, as opposed to the ones configured."""
        self.load()
        return sorted(self._factories)

    def load(self) -> None:
        """Pull in what is installed. A broken one is reported, never fatal."""
        if self._loaded:
            return
        self._loaded = True

        from importlib.metadata import entry_points

        for entry in entry_points(group=ENTRY_POINT_GROUP):
            try:
                loaded = entry.load()
                if isinstance(loaded, type):
                    self.register_factory(entry.name, loaded)
                else:
                    self.register(entry.name, loaded, replace=True)
                log.info("export %r from %s", entry.name, entry.value)
            except Exception:
                log.exception("could not load the export %r; carrying on", entry.name)

        from . import ftp, local, rsync

        self.register_factory("ftp", ftp.FtpExport)
        self.register_factory("rsync", rsync.RsyncExport)
        # A directory on this machine. The one most stations want: the
        # built-in web server serves it and the feed is on the local network
        # without anything else being installed.
        self.register_factory("local", local.LocalExport)


#: The registry the CLI and the admin page use.
DEFAULT = Registry()


def get(name: str) -> object | None:
    return DEFAULT.get(name)


def names() -> list[str]:
    return DEFAULT.names()


def kinds() -> list[str]:
    return DEFAULT.kinds()


def _feed_choices() -> list[tuple[str, str]]:
    """The feeds an export can point at.

    An export sends what something produced, so the list is the feeds and not
    the filesystem. There are none yet; until there are, the form offers a
    directory instead and says so.
    """
    from .. import feeds

    return [(name, f"the {name} feed"
             + (f" -- {feeds.describe(name)}" if feeds.describe(name) else ""))
            for name in feeds.names()]


def source_for(settings: dict[str, Any], feed_directory: Any = None) -> Path | None:
    """Where an export's files are, from a feed name or a plain directory.

    A feed is asked where it wrote; a directory is taken as it is. Both are
    kept because feeds do not exist yet and an export has to be usable before
    they do -- pointing one at a directory somebody else fills is a legitimate
    arrangement and not only a stopgap.
    """
    feed = str(settings.get("source") or "").strip()
    if feed:
        if feed_directory is not None:
            found = feed_directory(feed)
            if found is not None:
                return Path(found)
        # Named a feed that is not installed. Not a directory to fall back on:
        # sending the wrong directory is worse than sending nothing.
        return None
    directory = settings.get("directory_source")
    return Path(directory) if directory else None


def walk(source: Path, files: list[Path] | None = None) -> list[Path]:
    """Every file to consider, as paths relative to `source`.

    Directories that should never be uploaded are skipped here rather than in
    each export: a `.git` inside a published site is a mistake anybody can
    make once, and one that puts the whole history on a public web server.
    """
    if files is not None:
        return [f if not f.is_absolute() else f.relative_to(source) for f in files]

    skip_dirs = {".git", ".svn", "__pycache__", ".DS_Store", "node_modules"}
    # A `.part` is by definition a file somebody is in the middle of writing.
    # Uploading one publishes half a page and, worse, leaves it there under a
    # name nothing will ever overwrite.
    skip_suffixes = (".part", ".tmp", ".swp")
    found = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        parts = set(path.relative_to(source).parts)
        if parts & skip_dirs or path.name.startswith(".~"):
            continue
        if path.name.endswith(skip_suffixes):
            continue
        found.append(path.relative_to(source))
    return found

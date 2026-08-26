"""Publishing to a directory on this machine.

The third destination beside FTP and rsync, and the one most stations
actually want: put what a feed produced somewhere, and let the built-in web
server hand it to a browser.

That could have been a setting on the web server instead -- "serve this
directory" -- and it was. Making it an export is better for one reason: there
is then a single place where anybody asks "where does this end up". A feed
writes into its own working directory and knows nothing about publishing. One
export sends it to a web host, another puts it under the local site, a third
copies it to a mounted share. Three destinations, one idea, one page in the
settings.

## Why it copies rather than pointing

The web server could serve the feed's own directory and save the copy. It
does not, for the same reason the FTP export exists: a feed rewrites its
directory while it runs, and a browser loading a page halfway through gets
half a page. What lands here is one whole set of files or the previous one.

The copy is cheap. Only what changed moves, judged the same way FTP judges
it, and a feed that rewrote `index.html` with identical bytes moves nothing.
On the same filesystem a hard link is used instead of a copy, so publishing a
hundred JSON files costs a hundred directory entries and no second copy of
anything.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from . import BaseExport, ExportError, Sent, walk
from .tracker import Tracker

log = logging.getLogger(__name__)


class LocalExport(BaseExport):
    """Copies what a feed produced into a directory on this machine."""

    label = "local directory"
    #: One line for the form that offers the kinds. Somebody adding an
    #: export is choosing a destination, and "local" on its own is not a
    #: destination.
    summary = (
        "A directory on this machine. The built-in web server serves "
        "it, so a feed is readable on the local network with nothing "
        "else installed.")

    def __init__(self, directory: str = "", source: str = "",
                 directory_source: str = "", trigger: str = "feed",
                 every: int = 900, link: bool = True, delete: bool = False,
                 tracker: str = "") -> None:
        #: Where it ends up. Under what the web server serves, this is the
        #: address it appears at.
        self.directory = str(directory or "").strip()
        #: Which feed, or which directory. Same two options as every other
        #: export, and the same rule: a feed if one is chosen.
        self.source = (source or "").strip()
        self.directory_source = (directory_source or "").strip()
        self.trigger = trigger
        self.every = every
        #: Hard link where the filesystem allows it. A link is one directory
        #: entry; a copy of a year of JSON is a second year of JSON.
        #:
        #: This is safe only because a feed replaces a file rather than
        #: rewriting it in place -- the replace breaks the link and the
        #: published copy keeps the old content until this runs again. A feed
        #: that opened its own output and wrote into it would change what is
        #: published underneath a reader, so turn this off for one that does.
        self.link = link
        #: Remove what the feed no longer produces. Off by default, and only
        #: files this export put there are ever considered -- it keeps a
        #: record. A hand-written page in the same directory is not this
        #: export's to delete.
        self.delete = delete
        self._tracker_path = tracker
        self._tracker: Tracker | None = None
        self.sent_files = 0
        self.last_note = ""

    # -- sending ----------------------------------------------------------

    def send(self, source: Path, files: list[Path] | None = None) -> Sent:
        source = Path(source)
        if not self.directory:
            raise ExportError("no directory is set")
        if not source.is_dir():
            raise ExportError(f"{source} is not a directory")

        started = time.monotonic()
        result = Sent()
        target = Path(self.directory)
        if target.resolve() == source.resolve():
            # Publishing a directory into itself would compare every file
            # against itself and then hard link it over itself. Nothing good
            # happens next.
            raise ExportError(f"{target} is the source directory")

        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ExportError(f"cannot write to {target}: {exc}") from exc

        tracker = self._tracker_for(source)
        candidates = walk(source, files)
        wanted, result.skipped = tracker.changed(source, candidates)
        if not wanted and not self.delete:
            result.seconds = time.monotonic() - started
            result.note = "nothing had changed"
            return result

        try:
            for relative in wanted:
                try:
                    result.bytes += self._place(source / relative,
                                                target / relative)
                    tracker.record(source, relative)
                    result.sent += 1
                except OSError as exc:
                    # One file, not the run. A page that cannot be written
                    # must not cost the publishing of everything after it.
                    result.failures.append((relative.as_posix(), str(exc)))
                    log.warning("could not publish %s: %s", relative, exc)

            if self.delete:
                result.deleted = self._remove(target, tracker, candidates)
        finally:
            tracker.save()

        result.seconds = time.monotonic() - started
        self.sent_files += result.sent
        self.last_note = result.note
        return result

    def _place(self, source: Path, destination: Path) -> int:
        """One file, atomically. Returns its size.

        Written beside and moved into place, so a browser reading it while it
        is replaced gets one version or the other and never half of each.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        partial.unlink(missing_ok=True)
        try:
            if self.link:
                try:
                    os.link(source, partial)
                except OSError:
                    # A different filesystem, or one that will not link.
                    # Copying works everywhere, and from here on it copies.
                    log.info("hard links are not available from %s to %s;"
                             " copying instead", source.parent,
                             destination.parent)
                    self.link = False
            if not self.link:
                shutil.copy2(source, partial)
            size = partial.stat().st_size
            partial.replace(destination)
            return size
        except OSError:
            partial.unlink(missing_ok=True)
            raise

    def _remove(self, target: Path, tracker: Tracker,
                present: list[Path]) -> int:
        """Delete what this export put there and the feed no longer writes."""
        removed = 0
        for name in tracker.gone(present):
            path = target / name
            try:
                if path.is_file():
                    path.unlink()
                    removed += 1
            except OSError as exc:
                log.debug("could not remove %s: %s", path, exc)
            tracker.forget(Path(name))
        return removed

    def _tracker_for(self, source: Path) -> Tracker:
        if self._tracker is None:
            where = (Path(self._tracker_path) if self._tracker_path
                     else source.parent / f".sent-local-{_slug(self.directory)}.json")
            self._tracker = Tracker(where)
        return self._tracker

    # -- the button on the settings page ----------------------------------

    def check(self) -> str:
        """Whether this can be written to, and what is there now."""
        if not self.directory:
            return "No directory is set."
        target = Path(self.directory)
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".weewx-evo-write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return f"Cannot write to {target}: {exc}"

        existing = sum(1 for p in target.rglob("*") if p.is_file())
        free = ""
        try:
            usage = shutil.disk_usage(target)
            free = f", {usage.free / 1e9:.1f} GB free"
        except OSError:
            pass
        return (f"{target.resolve()} is writable"
                + (f", holding {existing} file(s)" if existing else " and empty")
                + free + ".")

    def status(self) -> dict[str, Any]:
        return {
            "kind": "local",
            "directory": self.directory,
            "files": self.sent_files,
            "hard_links": self.link,
            "note": self.last_note,
        }

    # -- what the admin page asks for -------------------------------------

    @staticmethod
    def options() -> list:
        from ..options import Group, Option
        from . import _feed_choices

        return [
            Group("Where it goes", "", (
                Option("directory", "Publish to", kind="path",
                       default="data/site", required=True,
                       placeholder="data/site",
                       help="A directory on this machine. Put it under what "
                            "the built-in web server serves and the feed is "
                            "on the local network immediately. A directory "
                            "nginx already serves, or a mounted share, works "
                            "the same way."),
            )),
            Group("What is sent", "", (
                Option("source", "Send what this feed produced",
                       kind="choice",
                       choices=(("", "-- a directory instead --"),),
                       choices_from=_feed_choices,
                       help="An export moves what a feed made."),
                Option("directory_source", "Or a directory", kind="path",
                       placeholder="data/public_html",
                       help="Used when no feed is chosen. Everything under it "
                            "is published, keeping the structure."),
                Option("delete", "Remove files that are no longer produced",
                       kind="bool", default=False,
                       help="Off by default. Only files this export put there "
                            "are ever removed -- it keeps a record -- but a "
                            "directory usually holds more than one thing."),
            )),
            Group("When it runs", "", (
                Option("trigger", "Publish", kind="choice", default="feed",
                       choices=(("feed", "when the feed above has finished"),
                                ("record", "after every archive record"),
                                ("interval", "on its own schedule"),
                                ("manual", "only when asked")),
                       help="Coupled to the feed is the right answer when "
                            "there is one: publishing starts after the feed "
                            "has written its files rather than while it is "
                            "still writing them."),
                Option("every", "Its own schedule", kind="duration",
                       default=900, minimum=60, maximum=86400,
                       help="Only used with 'on its own schedule'."),
            )),
            Group("How", "", (
                Option("link", "Hard link instead of copying", kind="bool",
                       default=True, advanced=True,
                       help="On one filesystem a link costs a directory entry "
                            "rather than a second copy of every file. Falls "
                            "back to copying by itself where the filesystem "
                            "will not link."),
                Option("tracker", "Remember what was published in",
                       kind="path", advanced=True,
                       help="Empty means beside the source directory. This is "
                            "what stops every file being copied every time; "
                            "losing it costs one full copy."),
            )),
        ]


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text).strip("-")[:40] or "site"

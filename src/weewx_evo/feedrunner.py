"""Running the feeds, off the archiver's thread.

A hundred charts is most of a second of reading and writing. Done where the
archiver runs, that is a second the archiver is not archiving, every interval,
for ever. So the same arrangement the exports have: the archiver sets a flag
and returns, and the work happens here.

One thread for all the feeds rather than one each. They are ordered -- the
diagnostic page draws what the JSON feed wrote -- and a feed that takes a
minute should delay the next feed rather than racing it. The exports are the
other way round, one thread each, because an FTP host that has stopped
answering must not hold up an rsync that is working.

Each feed gets its own read-only connection to the archive. Read-only because
a feed reports history and does not write it, and its own because SQLite
connections belong to one thread.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: How long to wait after a record before running. Several records can land
#: within a second or two of each other when the archiver catches up, and
#: producing a hundred files for each of them is waste.
SETTLE = 2.0


class Runner:
    """Produces every feed, in order, whenever a record lands."""

    def __init__(self, feeds: list[tuple[str, Callable, Path]],
                 archive_path: Path,
                 on_produced: Callable[[str, list], None] | None = None) -> None:
        #: (name, build(reader) -> feed, where to write). Built late, with a
        #: connection made on this thread.
        self.feeds = list(feeds)
        self.archive_path = Path(archive_path)
        #: Called with (name, files) after each feed finishes. This is what
        #: an export set to run "when its feed finishes" is waiting for, and
        #: without it such an export waits for ever without saying so.
        #:
        #: A callback rather than a reference to the export runner: a feed
        #: has no business knowing that exports exist, and the two are wired
        #: together where both are already in scope.
        self.on_produced = on_produced
        self.due = threading.Event()
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None
        self.runs = 0
        self.failures = 0
        self.last_note = ""
        self.last_run: float | None = None

    def record_written(self) -> None:
        """Called by the archiver. Sets a flag and returns."""
        self.due.set()

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, daemon=True,
                                       name="feeds")
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self.due.set()
        if self.thread is not None:
            self.thread.join(timeout=10)

    def _loop(self) -> None:
        while not self.stopping.is_set():
            self.due.wait()
            if self.stopping.is_set():
                return
            self.due.clear()
            # Let a burst settle. Catching up ten intervals should produce
            # one set of files, not ten.
            self.stopping.wait(SETTLE)
            self.due.clear()
            if self.stopping.is_set():
                return
            self.run_once()

    def run_once(self) -> str:
        """Every feed, in order. Returns what happened, for a status page."""
        if not self.archive_path.exists():
            log.debug("no archive at %s yet", self.archive_path)
            return ""

        started = time.time()
        notes = []
        try:
            connection = sqlite3.connect(
                f"file:{self.archive_path}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            log.error("could not open the archive to produce the feeds: %s",
                      exc)
            self.failures += 1
            return ""

        try:
            from .series import Reader

            reader = Reader(connection)
            for name, build, into in self.feeds:
                try:
                    feed = build(reader)
                    made = feed.produce(into)
                    notes.append(f"{name}: {made.note}" if made.note else name)
                    if self.on_produced is not None:
                        # After the files are written, never before. That
                        # ordering is the whole reason an export prefers this
                        # over the archive record: started by the record it
                        # can begin while the feed is still writing, and half
                        # a page gets published.
                        try:
                            self.on_produced(name, list(made.files))
                        except Exception:
                            log.exception("could not hand %r on to the "
                                          "exports; carrying on", name)
                except Exception:
                    # One feed failing must not cost the others. A broken
                    # template should not stop the JSON that everything else
                    # is built on.
                    log.exception("the feed %r failed; carrying on", name)
                    self.failures += 1
                    notes.append(f"{name}: failed")
        finally:
            connection.close()

        self.runs += 1
        self.last_run = time.time()
        self.last_note = "; ".join(notes)
        # At info, like the exports. A feed that quietly does nothing is
        # indistinguishable from one that is not running, and the difference
        # took an hour to find once.
        log.info("feeds in %.2fs -- %s", time.time() - started,
                 self.last_note or "nothing to do")
        return self.last_note

    def status(self) -> dict[str, Any]:
        return {
            "feeds": [name for name, _build, _into in self.feeds],
            "runs": self.runs,
            "failures": self.failures,
            "last_run": self.last_run,
            "last": self.last_note,
        }

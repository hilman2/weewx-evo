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
    """Produces feeds, in order, when whatever each one waits for happens.

    Three things can set a feed going, and until this took notice of them
    only one did. Every feed ran on the archive record, including `realtime`,
    whose whole reason for existing is being newer than that: a file consumers
    poll every ten seconds was as old as the last archive interval.
    """

    def __init__(self, feeds: list[tuple[str, Callable, Path]],
                 archive_path: Path,
                 on_produced: Callable[[str, list], None] | None = None,
                 schedule: dict[str, dict] | None = None) -> None:
        #: (name, build(reader) -> feed, where to write). Built late, with a
        #: connection made on this thread.
        self.feeds = list(feeds)
        self.archive_path = Path(archive_path)
        #: Per feed: {"trigger": ..., "every": seconds, "archive": name}.
        #: Anything not named here runs on the archive record, which is what
        #: every feed did before there was a choice.
        self.schedule = dict(schedule or {})
        #: When each scheduled feed is next due, by name.
        self._next: dict[str, float] = {}
        #: Called with (name, files) after each feed finishes. This is what
        #: an export set to run "when its feed finishes" is waiting for, and
        #: without it such an export waits for ever without saying so.
        #:
        #: A callback rather than a reference to the export runner: a feed
        #: has no business knowing that exports exist, and the two are wired
        #: together where both are already in scope.
        self.on_produced = on_produced
        self.due = threading.Event()
        #: Set for a reading rather than a record. Separate from `due` so a
        #: packet does not also produce the feeds waiting on the archive.
        self.live = threading.Event()
        self.stopping = threading.Event()
        self._wrote = ""
        self._wants_packets = any(
            one.get("trigger") == "packet" for one in self.schedule.values())
        self.thread: threading.Thread | None = None
        self.runs = 0
        self.failures = 0
        self.last_note = ""
        self.last_run: float | None = None

    #: Which archive last wrote a record, so a feed reading another one is
    #: not produced for somebody else's data. One archive today; the field
    #: exists so the second is a name rather than a rewrite.
    def record_written(self, archive: str = "") -> None:
        """Called by the archiver. Sets a flag and returns."""
        self._wrote = archive or self._wrote
        self.due.set()

    def packet_stored(self) -> None:
        """Called by the listener for every reading that lands.

        Only wakes feeds that asked for it. A feed on `record` is not produced
        here, or an eight-second console would rebuild a whole skin eight
        times a minute.
        """
        if self._wants_packets:
            self.live.set()

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
            # Wake for a record, for a reading, or when the next scheduled
            # feed falls due -- whichever comes first. Waiting on the event
            # with a timeout rather than polling: a feed due in an hour costs
            # one wakeup, not three thousand.
            waited = self.due.wait(timeout=self._until_next())
            if self.stopping.is_set():
                return

            if waited:
                self.due.clear()
                # Let a burst settle. Catching up ten intervals should
                # produce one set of files, not ten.
                self.stopping.wait(SETTLE)
                self.due.clear()
                if self.stopping.is_set():
                    return
                self.run_once(because="record")
            elif self.live.is_set():
                self.live.clear()
                self.run_once(because="packet")
            else:
                self.run_once(because="schedule")

    def _until_next(self) -> float | None:
        """Seconds until the next scheduled feed is due, or None for never.

        None rather than a long number, so a configuration with nothing on a
        clock waits on the event exactly as it did before.
        """
        due = list(self._next.values())
        if not due:
            return None if not self._wants_packets else 1.0
        return max(0.0, min(due) - time.time())

    def _plan(self, name: str, now: float | None = None) -> None:
        """When this feed is next due, rounded to the clock.

        On the hour rather than an hour after the service started: an hourly
        feed that produces at 14:37 because that is when somebody restarted
        is one whose files nobody can predict the age of.
        """
        now = now or time.time()
        every = float(self.schedule.get(name, {}).get("every") or 0)
        if every <= 0:
            return
        self._next[name] = (int(now // every) + 1) * every

    def due_now(self, name: str, because: str, now: float | None = None) -> bool:
        """Whether this feed runs on this pass."""
        wanted = self.schedule.get(name, {}).get("trigger", "record")
        if wanted == "packet":
            return because == "packet"
        if wanted != "schedule":
            return because == "record"
        now = now or time.time()
        if name not in self._next:
            self._plan(name, now)
            # Produced once at startup, so a feed on a nightly clock does not
            # leave an empty directory until midnight.
            return True
        if now >= self._next[name]:
            self._plan(name, now)
            return True
        return False

    def run_once(self, because: str = "record") -> str:
        """The feeds this pass is for, in order. Returns what happened.

        `because` says what woke the thread. A feed set to its own clock is
        not produced by an archive record, and one on the archive is not
        produced by a reading -- which is the whole point of the setting.
        """
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
                if not self.due_now(name, because):
                    continue
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

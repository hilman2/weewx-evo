"""Running the uploads at the right time, without holding anything up.

The same arrangement as `exports/runner.py`, and for the same reason: one
thread each, so a service that has stopped answering sits in its own timeout
instead of the archiver's. Weather Underground goes down for an hour now and
then, and an archive interval that is late because of it is a bug in us.

What is different from an export is where the work comes from. An export is
handed a directory. An upload is handed nothing -- it goes and reads the
archive itself, from wherever it last got to. That is the same rule the rest
of the system follows: the components talk through the database and not to
each other. It buys two things that are hard to get any other way.

  * A restart costs nothing. The upload knows where it was because the number
    is on disk, not because a process remembered.
  * A connection that was down for twenty minutes comes back and sends the
    twenty minutes, rather than the current reading and a hole.

Three triggers, one fewer than the exports have: there is no `feed` here,
because an upload is not waiting for anybody to finish writing files.

    record     after every archive record. The default and almost always right.
    interval   on its own clock, for a service that asks for less often
    manual     only on `weewx-evo upload run`
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from . import Rejected
from .progress import Progress

log = logging.getLogger(__name__)

#: How far back a catch-up will ever reach, whatever the limit says. A station
#: that has been off for a month should come back and post the current
#: reading, not two weeks of history nobody is waiting for.
CATCH_UP_HORIZON = 6 * 3600


class Scheduled:
    """One upload, and when it is next due."""

    __slots__ = (
        "blocked",
        "failures",
        "last",
        "last_summary",
        "name",
        "progress",
        "records",
        "running",
        "runs",
        "skipped",
        "upload",
    )

    def __init__(self, name: str, upload: Any, progress: Progress,
                 records: Callable[[int, int], list[dict]]) -> None:
        self.name = name
        self.upload = upload
        self.progress = progress
        #: Given (after_ts, limit), the archive records to send, oldest first.
        #: A callable rather than the store itself: this module has no
        #: business holding a database handle, and a test has no business
        #: building one.
        self.records = records
        self.last: float = 0.0
        self.running = False
        self.runs = 0
        self.failures = 0
        self.skipped = 0
        self.last_summary = ""
        #: Set when the service said something permanent -- a bad password, a
        #: station id it does not know. Retrying that every five minutes for a
        #: year is how an account gets blocked, and the log line that says so
        #: is the useful output.
        self.blocked = ""

    @property
    def trigger(self) -> str:
        return getattr(self.upload, "trigger", "record")

    @property
    def every(self) -> int:
        return int(getattr(self.upload, "every", 900))

    def due(self, now: float, fired: str) -> bool:
        if self.blocked or self.trigger == "manual":
            return False
        if self.trigger == "record":
            return fired == "record"
        return now - self.last >= self.every

    def pending(self) -> list[dict]:
        """The records this upload still owes, oldest first.

        Empty when it is up to date, which is the ordinary answer between
        archive intervals and costs one indexed query.
        """
        through = self.progress.through(self.name)
        limit = int(getattr(self.upload, "catch_up_limit", 12))
        if not getattr(self.upload, "backfill", True):
            limit = 0
        if through and limit:
            # Never reach further back than the horizon, whatever the limit
            # says. Both bounds exist: the limit caps the requests, the
            # horizon caps the age of what gets posted as though it mattered.
            through = max(through, int(time.time()) - CATCH_UP_HORIZON)
        found = self.records(through, max(1, limit))
        if not limit and found:
            # No backfill: the newest and nothing else.
            return found[-1:]
        return found

    def run(self) -> None:
        """Send whatever is owed, and remember what happened. Never raises."""
        self.running = True
        self.last = time.monotonic()
        started = time.monotonic()
        try:
            records = self.pending()
            if not records:
                self.last_summary = "nothing new"
                return
            result = self.upload.post(records)
            self.runs += 1
            result.seconds = result.seconds or (time.monotonic() - started)
            self.last_summary = result.summary()
            if result.through:
                self.progress.sent(self.name, result.through)
                self.progress.save()
            if result.failures:
                self.failures += 1
                log.warning("upload %s: %s", self.name, result.summary())
            elif result.sent:
                log.info("upload %s: %s", self.name, result.summary())
            else:
                log.debug("upload %s: %s", self.name, result.summary())
        except Rejected as exc:
            self.failures += 1
            self.last_summary = str(exc)
            if exc.permanent:
                # Said once, loudly, and then not again. The alternative is
                # the same line every five minutes forever, which is how a
                # log stops being read.
                self.blocked = str(exc)
                log.error("upload %s is switched off: %s. Fix the settings "
                          "and restart, or run `weewx-evo upload check`.",
                          self.name, exc)
            else:
                log.warning("upload %s failed: %s", self.name, exc)
        except Exception as exc:
            self.failures += 1
            self.last_summary = str(exc)
            # One service failing is not the others' problem and certainly not
            # the archiver's. The readings are safe in the archive either way.
            log.warning("upload %s failed: %s", self.name, exc)
        finally:
            self.running = False


class Runner:
    """Keeps the uploads going, one thread each."""

    def __init__(self, uploads: list[Scheduled]) -> None:
        self.uploads = uploads
        self._stopping = threading.Event()
        self._wake = {s.name: threading.Event() for s in uploads}
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for scheduled in self.uploads:
            if scheduled.trigger == "manual":
                log.info("upload %s runs only when asked", scheduled.name)
                continue
            thread = threading.Thread(target=self._loop, args=(scheduled,),
                                      name=f"upload-{scheduled.name}", daemon=True)
            thread.start()
            self._threads.append(thread)
            if scheduled.trigger == "record":
                log.info("upload %s runs after every archive record", scheduled.name)
            else:
                log.info("upload %s runs every %ds", scheduled.name, scheduled.every)

    def record_written(self) -> None:
        """A new archive record landed.

        Called from the archiver's thread and returns at once: it sets flags,
        and the upload threads pick them up. Nothing about a network request
        happens on the archiver's thread, which is the whole point.
        """
        for scheduled in self.uploads:
            if scheduled.trigger == "record":
                self._wake[scheduled.name].set()

    def stop(self) -> None:
        self._stopping.set()
        for event in self._wake.values():
            event.set()
        for thread in self._threads:
            thread.join(timeout=2)
        for scheduled in self.uploads:
            close = getattr(scheduled.upload, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    log.debug("upload %s did not close cleanly", scheduled.name)

    def _loop(self, scheduled: Scheduled) -> None:
        waiting = scheduled.trigger == "record"
        event = self._wake[scheduled.name]
        while not self._stopping.is_set():
            if waiting:
                event.wait(timeout=30)
                if self._stopping.is_set():
                    return
                if not event.is_set():
                    continue
                # Cleared here rather than by whoever set it, so a record
                # arriving while this upload is busy is not lost.
                event.clear()
                fired = "record"
            else:
                self._stopping.wait(timeout=min(30, max(1, scheduled.every)))
                if self._stopping.is_set():
                    return
                fired = ""

            if not scheduled.due(time.monotonic(), fired):
                continue
            # No check for "already running": this thread is the only one that
            # runs this upload. Overlap is not possible, so there is nothing
            # to guard -- and a service being posted two readings at once is
            # exactly how a duplicate gets recorded.
            scheduled.run()

    def status(self) -> list[dict]:
        return [{
            "name": s.name,
            "trigger": s.trigger,
            "every": s.every if s.trigger == "interval" else None,
            "runs": s.runs,
            "failures": s.failures,
            "through": s.progress.through(s.name) or None,
            "running": s.running,
            "blocked": s.blocked or None,
            "last": s.last_summary,
        } for s in self.uploads]


def build(configured: dict[str, dict], make: Callable[[str, dict], Any],
          progress: Progress,
          records: Callable[[int, int], list[dict]]) -> list[Scheduled]:
    """Turn configuration into things the runner can run.

    Anything that cannot be built is reported and left out. A misconfigured
    upload must not stop the others, and it certainly must not stop the
    station: the readings are what matters, and an upload is a copy of them.
    """
    ready = []
    for name, settings in sorted(configured.items()):
        try:
            upload = make(name, dict(settings))
        except Exception as exc:
            log.warning("upload %s is not usable: %s", name, exc)
            continue
        ready.append(Scheduled(name, upload, progress, records))
    return ready

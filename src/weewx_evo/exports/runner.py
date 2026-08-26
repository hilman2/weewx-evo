"""Running the exports at the right time, without holding anything up.

Each export gets its own thread. That is not for speed -- there are two or
three of them and each is idle almost all the time -- it is so that one cannot
hold up the others or the archiver.

The reason is concrete. An FTP export to a host that has stopped answering
sits in a connect for its timeout, thirty seconds by default. Run inline in
the archiver tick, that is thirty seconds in which packets accumulate and the
next interval is late. Run in its own thread, it is thirty seconds during
which nothing else notices.

Four triggers:

    feed       when the feed it sends has finished writing. The one to prefer
               where there is a feed: started by the archive record instead,
               an export can begin while the feed is still writing, and half
               a site goes up -- which looks like a broken template and
               cannot be reproduced afterwards.
    record     after every archive record. For an export pointed at a
               directory something else fills.
    interval   on its own schedule, for a slow destination or a site nobody
               needs a minute fresh
    manual     only on `weewx-evo export run`

An export cannot overlap itself, and it is the one-thread-each arrangement
that guarantees it rather than a check: the thread is inside `send()` and is
not reading its own trigger. Anything that fires while it is busy is
remembered and acted on when it finishes, and several firings collapse into
one -- which is what is wanted. Nobody needs four consecutive uploads of a
site that changed once.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)


class Scheduled:
    """One export, and when it is next due."""

    __slots__ = ("name", "export", "source", "last", "running", "skipped",
                 "runs", "failures", "last_summary", "feed", "changed",
                 "caught_up")

    def __init__(self, name: str, export: Any, source: Path,
                 feed: str = "") -> None:
        self.name = name
        self.export = export
        self.source = source
        # The feed this export sends, when it names one. It waits for that
        # feed and no other: two feeds writing two sites must not each
        # trigger both uploads.
        self.feed = feed
        # What the feed said it wrote, if it said. Used as a guarantee that a
        # file written a second ago is included, not as the whole list: an
        # export only ever given the changed files can never send one that
        # changed before it existed. Adding an export to a station that had
        # been running for a week published one file out of seventy, and the
        # missing ones would never have appeared.
        self.changed: list[Path] | None = None
        # Set once the first run has been through the whole directory.
        self.caught_up = False
        self.last: float = 0.0
        self.running = False
        self.skipped = 0
        self.runs = 0
        self.failures = 0
        self.last_summary = ""

    @property
    def trigger(self) -> str:
        return getattr(self.export, "trigger", "record")

    @property
    def every(self) -> int:
        return int(getattr(self.export, "every", 900))

    def due(self, now: float, fired: str) -> bool:
        """`fired` is what just happened: "record", a feed name, or ""."""
        if self.trigger == "manual":
            return False
        if self.trigger == "feed":
            return bool(self.feed) and fired == self.feed
        if self.trigger == "record":
            return fired == "record"
        return now - self.last >= self.every

    def run(self) -> None:
        """Send, and remember what happened. Never raises."""
        self.running = True
        self.last = time.monotonic()
        changed, self.changed = self.changed, None
        if not self.caught_up:
            # The first run looks at everything. The export's own record of
            # what it has sent decides what actually moves, so this costs one
            # directory walk and nothing else.
            changed = None
            self.caught_up = True
        try:
            result = self.export.send(self.source, changed)
            self.runs += 1
            self.last_summary = result.summary()
            if result.failures:
                self.failures += 1
                log.warning("export %s: %s", self.name, result.summary())
            elif result.sent or result.deleted:
                log.info("export %s: %s", self.name, result.summary())
            else:
                log.debug("export %s: %s", self.name, result.summary())
        except Exception as exc:
            self.failures += 1
            self.last_summary = str(exc)
            # One export failing is not the others' problem, and certainly not
            # the archiver's. A host that is down comes back.
            log.warning("export %s failed: %s", self.name, exc)
        finally:
            self.running = False


class Runner:
    """Keeps the exports going, one thread each."""

    def __init__(self, exports: list[Scheduled]) -> None:
        self.exports = exports
        self._stopping = threading.Event()
        # One event per export rather than one shared: an export coupled to
        # the "website" feed must not wake when "csv" finishes.
        self._wake = {s.name: threading.Event() for s in exports}
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for scheduled in self.exports:
            if scheduled.trigger == "manual":
                log.info("export %s runs only when asked", scheduled.name)
                continue
            thread = threading.Thread(target=self._loop, args=(scheduled,),
                                      name=f"export-{scheduled.name}", daemon=True)
            thread.start()
            self._threads.append(thread)
            if scheduled.trigger == "feed":
                log.info("export %s runs when the %s feed finishes",
                         scheduled.name, scheduled.feed)
            elif scheduled.trigger == "record":
                log.info("export %s runs after every archive record", scheduled.name)
            else:
                log.info("export %s runs every %ds", scheduled.name, scheduled.every)

    def record_written(self) -> None:
        """A new archive record landed.

        Called from the archiver's thread and returns at once: it sets flags,
        and the export threads pick them up. Nothing about an upload happens
        on the archiver's thread, which is the whole point.
        """
        for scheduled in self.exports:
            if scheduled.trigger == "record":
                self._wake[scheduled.name].set()

    def feed_produced(self, feed: str, files: list[Path] | None = None) -> None:
        """A feed has finished writing. Wake whatever sends it.

        This is the trigger to prefer where there is a feed. An export
        started by the archive record instead can begin while the feed is
        still writing, and half a site gets uploaded -- which looks like a
        broken template and is impossible to reproduce.
        """
        for scheduled in self.exports:
            if scheduled.trigger == "feed" and scheduled.feed == feed:
                if files is not None:
                    scheduled.changed = list(files)
                self._wake[scheduled.name].set()

    def stop(self) -> None:
        self._stopping.set()
        for event in self._wake.values():
            event.set()
        for thread in self._threads:
            thread.join(timeout=2)

    def _loop(self, scheduled: Scheduled) -> None:
        # An export waiting on something waits on its own event; one on a
        # schedule waits on the clock. Both wake for the stop.
        waiting = scheduled.trigger in ("feed", "record")
        event = self._wake[scheduled.name]
        while not self._stopping.is_set():
            if waiting:
                event.wait(timeout=30)
                if self._stopping.is_set():
                    return
                if not event.is_set():
                    continue
                # Cleared here rather than by whoever set it, so something
                # arriving while this export is running is not lost.
                event.clear()
                fired = scheduled.feed if scheduled.trigger == "feed" else "record"
            else:
                self._stopping.wait(timeout=min(30, max(1, scheduled.every)))
                if self._stopping.is_set():
                    return
                fired = ""

            now = time.monotonic()
            if not scheduled.due(now, fired):
                continue
            # No check for "already running" here: this thread is the only
            # one that runs this export, and it is here rather than in
            # send(). Overlap is not possible, so there is nothing to guard.
            behind = time.monotonic() - now
            if behind > scheduled.every and scheduled.trigger == "interval":
                scheduled.skipped += 1
                if scheduled.skipped in (1, 10, 100):
                    log.warning("export %s takes longer than the %ds between "
                                "runs (%d turns missed so far).",
                                scheduled.name, scheduled.every,
                                scheduled.skipped)
            scheduled.run()

    def status(self) -> list[dict]:
        return [{
            "name": s.name,
            "trigger": s.trigger,
            "feed": s.feed or None,
            "every": s.every if s.trigger == "interval" else None,
            "runs": s.runs,
            "failures": s.failures,
            "skipped": s.skipped,
            "running": s.running,
            "last": s.last_summary,
        } for s in self.exports]


def build(configured: dict[str, dict], make: Callable[[str, dict], Any],
          source_of: Callable[[dict], Path | None]) -> list[Scheduled]:
    """Turn configuration into things the runner can run.

    Anything that cannot be built is reported and left out. A misconfigured
    export must not stop the others, and it certainly must not stop the
    station: the readings are what matters, and an upload is a copy of them.
    """
    ready = []
    for name, settings in sorted(configured.items()):
        try:
            export = make(name, dict(settings))
        except Exception as exc:
            log.warning("export %s is not usable: %s", name, exc)
            continue
        source = source_of(settings)
        if source is None:
            log.warning("export %s has no feed and no directory set; not "
                        "running it", name)
            continue
        feed = str(settings.get("source") or "").strip()
        if getattr(export, "trigger", "") == "feed" and not feed:
            # Coupled to a feed but pointed at a directory. Nothing would ever
            # wake it, and a silent export is worse than a wrong one.
            log.warning("export %s is set to run when its feed finishes, but "
                        "it is pointed at a directory rather than a feed. It "
                        "will not run; choose another trigger.", name)
            continue
        ready.append(Scheduled(name, export, Path(source), feed=feed))
    return ready

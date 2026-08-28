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
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _add(into: Any, more: Any) -> None:
    """Fold a second source's result into the first.

    One line per export in the log, however many feeds it carried: what the
    operator wants to know is whether the site went up.
    """
    into.sent += more.sent
    into.skipped += more.skipped
    into.deleted += more.deleted
    into.bytes += more.bytes
    into.failures.extend(more.failures)


class Scheduled:
    """One export, and when it is next due."""

    __slots__ = (
        "caught_up",
        "changed",
        "export",
        "extra",
        "failures",
        "feed",
        "finished",
        "last",
        "last_summary",
        "name",
        "running",
        "runs",
        "skipped",
        "source",
    )

    def __init__(self, name: str, export: Any, source: Path,
                 feed: str = "",
                 extra: tuple[tuple[str, Path, str], ...] = ()) -> None:
        self.name = name
        self.export = export
        self.source = source
        # The feed this export sends, when it names one. It waits for that
        # feed and no other: two feeds writing two sites must not each
        # trigger both uploads.
        self.feed = feed
        #: Further feeds this export carries, each as (feed, directory,
        #: sub-path). A skin is pages and the charts they draw from, and the
        #: charts are a different feed writing a different directory -- so
        #: publishing the skin alone publishes a site whose diagrams are
        #: empty. Two exports to one account would do it, but nothing would
        #: hold the second until the first had finished.
        self.extra = tuple(extra)
        #: Which of them have finished since this last ran. An export that
        #: sends two feeds waits for both: fired by the first, it would
        #: upload pages that refer to charts still being written.
        self.finished: set[str] = set()
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

    def _sub_paths(self) -> tuple[str, ...]:
        return tuple(into for _f, _d, into in self.extra if into)

    @property
    def trigger(self) -> str:
        return getattr(self.export, "trigger", "record")

    @property
    def every(self) -> int:
        return int(getattr(self.export, "every", 900))

    @property
    def feeds(self) -> tuple[str, ...]:
        """Every feed this export waits for, the main one first."""
        names = [self.feed] if self.feed else []
        return tuple(names + [f for f, _d, _i in self.extra])

    def due(self, now: float, fired: str) -> bool:
        """`fired` is what just happened: "record", a feed name, or ""."""
        if self.trigger == "manual":
            return False
        if self.trigger == "feed":
            wanted = self.feeds
            if not wanted:
                return False
            if fired and fired in wanted:
                self.finished.add(fired)
            if not self.finished.issuperset(wanted):
                return False
            # Only what was waited for is taken out. Clearing the set would
            # throw away a feed that finished while this was deciding, and
            # the next round would wait for it all over again.
            self.finished.difference_update(wanted)
            return True
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
            # Passed only when there is something to protect, so an export
            # that carries one feed is called exactly as it always was --
            # including one from outside this repository, written against the
            # older signature.
            guard = self._sub_paths()
            result = (self.export.send(self.source, changed, protect=guard)
                      if guard else self.export.send(self.source, changed))
            for _feed, where, into in self.extra:
                # Each on its own: a different directory, a different place
                # at the far end, and a record of its own so that neither
                # sees the other's files as ones its feed stopped writing.
                _add(result, self.export.send(where, None, into=into))
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
            if scheduled.trigger != "feed" or feed not in scheduled.feeds:
                continue
            # Noted here rather than passed through the event, which carries
            # nothing: an export waiting on two feeds has to know which of
            # them this was.
            scheduled.finished.add(feed)
            if files is not None and feed == scheduled.feed:
                # Only for the main source. The changed files of another feed
                # are relative to *its* directory, and handed to the main one
                # they would be the only files it looked at -- so a skin
                # would publish whichever three charts had just been drawn
                # and nothing else.
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
                fired = "" if scheduled.trigger == "feed" else "record"
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


def named(settings: dict) -> list[tuple[str, str]]:
    """The further feeds an export names, as (feed, sub-path).

    Written one per line, because that is how every list here is written:

        json -> data/json
        images -> charts

    A line with no arrow puts that feed at the destination itself, which is
    what somebody means who has two feeds and one site. The arrow is the
    ordinary case: a skin's charts belong under the skin, not mixed into it.

    Only the reading. Whether the feed exists is `also`'s question, because
    the settings page wants the name somebody typed even when it is wrong --
    that page is where they find out.
    """
    out = []
    for line in settings.get("also") or []:
        text = str(line).strip()
        if not text:
            continue
        for arrow in ("->", "→", "=", ":"):
            if arrow in text:
                feed, into = text.split(arrow, 1)
                break
        else:
            feed, into = text, ""
        feed = feed.strip()
        if feed:
            out.append((feed, into.strip().strip("/")))
    return out


def also(settings: dict, feeds: dict[str, Path],
         name: str = "") -> tuple[tuple[str, Path, str], ...]:
    """The ones that exist, as (feed, directory, sub-path).

    A feed nobody has configured is named and left out rather than waited
    for. Waiting for it would be an export that never runs again, and the
    reason would be a line in a file somebody edited a month ago.
    """
    out = []
    seen = set()
    for feed, into in named(settings):
        if feed in seen:
            log.warning("export %s names the feed %r twice; using the first",
                        name or "?", feed)
            continue
        where = feeds.get(feed)
        if where is None:
            log.warning("export %s also sends the feed %r, and no feed of "
                        "that name is configured. It is left out -- waiting "
                        "for it would stop the export altogether.",
                        name or "?", feed)
            continue
        seen.add(feed)
        out.append((feed, Path(where), into))
    return tuple(out)


def build(configured: dict[str, dict], make: Callable[[str, dict], Any],
          source_of: Callable[[dict], Path | None],
          feeds: dict[str, Path] | None = None) -> list[Scheduled]:
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
        extra = also(settings, feeds or {}, name)
        if getattr(export, "trigger", "") == "feed" and not feed:
            # Coupled to a feed but pointed at a directory. Nothing would ever
            # wake it, and a silent export is worse than a wrong one.
            log.warning("export %s is set to run when its feed finishes, but "
                        "it is pointed at a directory rather than a feed. It "
                        "will not run; choose another trigger.", name)
            continue
        made = Scheduled(name, export, Path(source), feed=feed, extra=extra)
        if extra:
            log.info("export %s carries %s", name, ", ".join(
                f"{f} into {i or 'the destination itself'}"
                for f, _d, i in extra))
        ready.append(made)
    return ready

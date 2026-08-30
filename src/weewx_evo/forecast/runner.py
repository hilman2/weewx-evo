"""Asking the forecast sources, on their own schedule and their own thread.

The same arrangement as the exports and the uploads, for the third time and
the same reason: a weather service that has stopped answering must sit in its
own timeout rather than in the archiver's tick. A MOSMIX file is 350 kB over
somebody else's connection, and thirty seconds of that on the archive loop is
thirty seconds of packets piling up.

What is different here is what a failure means.

**A failed fetch keeps the old forecast.** Not an empty one. A source that
could not be reached has told us nothing about the weather, and replacing
yesterday's good forecast with nothing would turn a network hiccup into a
blank page. The store is only written when a fetch actually returned.

**An empty warning feed is an answer.** MeteoAlarm returns no entries when
the weather is calm, and that means the warnings have ended -- so warnings
*are* replaced with nothing, deliberately. Leaving an expired storm warning on
a page is the one failure in this file that matters.

The two are distinguished by where they happen: an exception never reaches the
store, and a successful fetch always does.

**A first fetch happens at startup.** A station restarted at eight in the
morning must not show an empty forecast until nine. Every source is asked once
as soon as its thread starts, then on its own interval.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .. import schedule
from . import ForecastError, Place
from . import store as store_module

log = logging.getLogger(__name__)

#: The series a forecast is for when nobody said. From the
#: store, so the two cannot disagree about the word.
DEFAULT_ARCHIVE = store_module.DEFAULT_ARCHIVE

#: How far back to keep hours that have already happened. Enough for a page
#: that draws the forecast against what actually occurred, little enough that
#: the file stays small.
KEEP_BEHIND = 24 * 3600


class Scheduled:
    """One source, and when it is next due."""

    __slots__ = (
        "_slot",
        "archive",
        "blocked",
        "failures",
        "fetched",
        "issued",
        "last",
        "last_summary",
        "name",
        "place",
        "running",
        "runs",
        "source",
        "store",
    )

    def __init__(self, name: str, source: Any, place: Place, store: Any,
                 fetched: Callable[[str], None] | None = None,
                 archive: str = DEFAULT_ARCHIVE) -> None:
        self.name = name
        self.source = source
        self.place = place
        self.store = store
        #: Which measurement series this forecast is for. The rows are keyed
        #: on it, so a second place's run cannot replace the first's -- which
        #: is what one key for two places would have done, alternating, every
        #: hour, with every page reading whichever ran last.
        self.archive = archive
        #: Called with this source's name after a run has been stored. The
        #: forecast is a second store's worth of data like the archive is,
        #: and whoever mirrors it needs to know when there is a new one.
        self.fetched = fetched
        self.last: float = 0.0
        #: The wall-clock moment this is next due on. None until the first
        #: turn, which fetches at once.
        self._slot: float | None = None
        self.running = False
        self.runs = 0
        self.failures = 0
        self.last_summary = ""
        self.issued = 0
        #: Set when the source said something permanent -- a station id that
        #: does not exist, a point outside the country it covers. Asking
        #: again every hour for a year would not fix it and the log line is
        #: the useful output.
        self.blocked = ""

    @property
    def every(self) -> int:
        return max(300, int(getattr(self.source, "every", 3600)))

    def due(self, now: float) -> bool:
        if self.blocked:
            return False
        # On the hour's grid: an hourly forecast is fetched on the hour,
        # whatever time the service came up. See schedule.py.
        wall = time.time()
        if self._slot is None:
            self._slot = schedule.next_slot(wall, self.every)
            return True
        if wall < self._slot:
            return False
        self._slot = schedule.next_slot(wall, self.every)
        return True

    def next_run(self) -> float:
        return time.time() if self._slot is None else self._slot

    def run(self) -> None:
        """Fetch and store. Never raises."""
        self.running = True
        self.last = time.monotonic()
        try:
            reading = self.source.fetch(self.place)
            # The entry's name, not the provider's. Every bundled source sets
            # `Reading.source` to its own kind, so `or self.name` never fired
            # -- and the store's key, `$forecast.<name>`, and what the mirror
            # asks the store for were all naming something not in the file.
            # The provider is `kind` in the configuration, where it belongs.
            reading.source = self.name
            self.store.store(reading, int(time.time()), self.archive)
            self.runs += 1
            self.issued = reading.issued
            self.last_summary = reading.summary()
            log.info("forecast %s: %s", self.name, self.last_summary)
            self._tell(self.name, self.archive)
        except ForecastError as exc:
            self.failures += 1
            self.last_summary = str(exc)
            if exc.permanent:
                self.blocked = str(exc)
                log.error("forecast %s is switched off: %s. Fix the settings "
                          "and restart, or run `weewx-evo forecast check`.",
                          self.name, exc)
            else:
                # The previous forecast stays. A source that could not be
                # reached has said nothing about the weather.
                log.warning("forecast %s failed: %s", self.name, exc)
        except Exception as exc:
            self.failures += 1
            self.last_summary = f"{type(exc).__name__}: {exc}"
            log.warning("forecast %s failed: %s", self.name, exc)
        finally:
            self.running = False

    def _tell(self, name: str, archive: str = DEFAULT_ARCHIVE) -> None:
        """Say a new run has landed, without letting the listener stop this.

        The one listener today is the InfluxDB upload, and it reaches over
        the network. A source that fetched successfully has done its job
        whatever happens next, and the alternative is a forecast that stops
        updating because a database somewhere is down.

        The series goes with the name. An upload writes under one `location`
        tag, so it must be told which place this run is about -- without
        that, two places' forecasts land under one set of tags and the pair
        with the same timestamp overwrite each other.
        """
        if self.fetched is None:
            return
        try:
            self.fetched(name, archive)
        except Exception:
            log.warning("forecast %s: could not pass the new run on",
                        name, exc_info=True)


class Runner:
    """Keeps the forecast sources going, one thread each."""

    def __init__(self, sources: list[Scheduled], store: Any = None) -> None:
        self.sources = sources
        self.store = store
        #: Whether the one-off tidy has run. See `_tidy`.
        self._tidied = False
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []
        self._pruned = 0.0

    def start(self) -> None:
        for scheduled in self.sources:
            thread = threading.Thread(target=self._loop, args=(scheduled,),
                                      name=f"forecast-{scheduled.name}",
                                      daemon=True)
            thread.start()
            self._threads.append(thread)
            log.info("forecast %s every %ds", scheduled.name, scheduled.every)

    def stop(self) -> None:
        self._stopping.set()
        for thread in self._threads:
            thread.join(timeout=2)
        for scheduled in self.sources:
            close = getattr(scheduled.source, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    log.debug("forecast %s did not close cleanly", scheduled.name)

    def replace(self, sources: list[Scheduled]) -> None:
        """Swap in a new set, after the configuration changed."""
        self.stop()
        self.sources = sources
        self._stopping = threading.Event()
        self._threads = []
        self.start()

    def _loop(self, scheduled: Scheduled) -> None:
        # Once at startup. A station restarted in the morning must not show
        # an empty forecast until the interval comes round.
        scheduled.run()
        self._tidy()
        self._prune()
        while not self._stopping.is_set():
            # Waking every thirty seconds rather than sleeping the whole
            # interval, so a stop is answered in seconds rather than in an
            # hour. The `due` check is what actually decides.
            # Soon enough to land on the slot rather than up to half a
            # minute past it. See schedule.py.
            self._stopping.wait(timeout=max(0.5, min(
                30.0, min((one.next_run() for one in self.sources),
                          default=time.time() + 30) - time.time())))
            if self._stopping.is_set():
                return
            if scheduled.due(time.monotonic()):
                scheduled.run()
                self._prune()

    def _tidy(self) -> None:
        """Drop what nobody is configured for. Once, after the first round.

        Two things end up here. A source taken out of the configuration:
        `forget` was written for it and nothing ever called it, so its rows
        went on answering `$forecast` for good. And, once per installation,
        the rows a store made before its key named the configured entry
        rather than the provider it uses.

        After every source has had its first turn, not at start-up: a fetch
        that fails because the network is not up yet must not cost the page
        the forecast it had. And once, because a store with nothing stale in
        it is the ordinary state and walking it every hour buys nothing.
        """
        if self.store is None or self._tidied:
            return
        if any(one.runs == 0 and not one.blocked for one in self.sources):
            return
        self._tidied = True
        try:
            self.store.keep({(one.archive, one.name) for one in self.sources})
        except Exception:
            log.debug("could not tidy the forecast store", exc_info=True)

    def _prune(self) -> None:
        """Drop what is in the past. Once an hour is plenty."""
        if self.store is None or time.monotonic() - self._pruned < 3600:
            return
        self._pruned = time.monotonic()
        try:
            dropped = self.store.prune(int(time.time()) - KEEP_BEHIND)
            if dropped:
                log.debug("dropped %d forecast row(s) that are now the past",
                          dropped)
        except Exception:
            log.debug("could not prune the forecast store", exc_info=True)

    def status(self) -> list[dict]:
        return [{
            "name": s.name,
            "archive": s.archive,
            "every": s.every,
            "runs": s.runs,
            "failures": s.failures,
            "issued": s.issued or None,
            "running": s.running,
            "blocked": s.blocked or None,
            "last": s.last_summary,
        } for s in self.sources]


def build(configured: dict[str, dict], make: Callable[[str, dict], Any],
          place: Place | Callable[[dict], tuple[str, Place]], store: Any,
          fetched: Callable[[str], None] | None = None) -> list[Scheduled]:
    """Turn configuration into things the runner can run.

    Anything that cannot be built is reported and left out. A misconfigured
    source must not stop the others, and it certainly must not stop the
    station: the readings are what matters, and a forecast is somebody
    else's opinion about tomorrow.

    `place` is either one `Place` for every entry -- which is what an
    installation with one series has and had -- or a callable answering
    `(archive, place)` for an entry's settings. The callable is how a second
    series gets its own coordinates rather than the first one's, and how an
    entry naming a series that does not exist is left out instead of being
    stored on somebody else's key.
    """
    ready = []
    for name, settings in sorted(configured.items()):
        try:
            archive, where = (place(settings) if callable(place)
                              else (DEFAULT_ARCHIVE, place))
            source = make(name, dict(settings))
        except Exception as exc:
            log.warning("forecast source %s is not usable: %s", name, exc)
            continue
        ready.append(Scheduled(name, source, where, store, fetched, archive))
    return ready

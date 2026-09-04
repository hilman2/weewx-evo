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
    live       every few seconds, from the live table -- for a broker feeding
               a dashboard somebody is looking at
    interval   on its own clock, for a service that asks for less often
    manual     only on `weewx-evo upload run`

`live` is the one that makes a modern skin worth running. An archive record
is a five-minute average that arrives five minutes late; a page showing one
is out of date for almost all of that. The packets are already in the live
table, so this reads them there rather than being handed them -- which is
what keeps the listener and the archiver separable.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .. import schedule
from . import Rejected
from .progress import Progress

log = logging.getLogger(__name__)

#: How far back a catch-up will ever reach, whatever the limit says. A station
#: that has been off for a month should come back and post the current
#: reading, not two weeks of history nobody is waiting for.
CATCH_UP_HORIZON = 6 * 3600

#: How long one upload may go without a line of its own. Anything slower than
#: this is logged run by run as it always was; anything faster is collected
#: and reported once.
QUIETLY = 60.0


def _spell(seconds: float) -> str:
    """A window, in the roundest words that stay true."""
    if seconds < 90:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.0f} min"


class Scheduled:
    """One upload, and when it is next due."""

    __slots__ = (
        "_logged_at",
        "_refused_since",
        "_runs_since",
        "_sent_since",
        "_slot",
        "archive",
        "blocked",
        "failures",
        "last",
        "last_summary",
        "live_through",
        "name",
        "packets",
        "progress",
        "records",
        "running",
        "runs",
        "skipped",
        "upload",
    )

    def __init__(self, name: str, upload: Any, progress: Progress,
                 records: Callable[[int, int], list[dict]],
                 packets: Callable[[int, int], list[dict]] | None = None,
                 archive: str = "") -> None:
        self.name = name
        self.upload = upload
        self.progress = progress
        #: Which measurement series this upload publishes. Empty is the
        #: default one, which is what `records` already resolves to. Kept
        #: rather than looked up again because the forecast has to be handed
        #: to the upload it belongs to: everything here goes out under one
        #: `location` tag, and a second place's rows sent through it would
        #: overwrite the first place's, timestamp for timestamp.
        self.archive = archive
        #: The live table, for `trigger = "live"`. None when this
        #: installation has no live database to read.
        self.packets = packets
        #: How far the live path has got. In memory rather than in
        #: `progress.json`: it moves every few seconds, and writing a file
        #: that often to record something nobody needs after a restart is how
        #: an SD card wears out.
        self.live_through = 0
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
        #: When a refusal that claims to be permanent was first seen. A
        #: sequence, not a state: see `_settled`.
        self._refused_since = 0.0
        #: When this last wrote a line, and what has happened since. See
        #: `_say`: the live upload runs six times a minute and used to write
        #: a line for each.
        # -1, not 0: `monotonic()` can legitimately be 0.0, and tested
        # against falsiness the first run counted as "never logged" -- so the
        # second one printed its own line as well.
        #: The wall-clock moment this is next due on, for `interval`.
        self._slot: float | None = None
        self._logged_at = -1.0
        self._runs_since = 0
        self._sent_since = 0

    @property
    def trigger(self) -> str:
        return getattr(self.upload, "trigger", "record")

    @property
    def every(self) -> int:
        return int(getattr(self.upload, "every", 900))

    @property
    def is_live(self) -> bool:
        return self.trigger == "live" and self.packets is not None

    def due(self, now: float, fired: str) -> bool:
        if self.blocked or self.trigger == "manual":
            return False
        if self.trigger == "record":
            return fired == "record"
        # On the hour's grid, not counted from whenever the service started:
        # a ten-minute upload goes at :00, :10, :20 and stays there across a
        # restart. See schedule.py.
        wall = time.time()
        if self._slot is None:
            self._slot = schedule.next_slot(wall, self.every)
            return True
        if wall < self._slot:
            return False
        self._slot = schedule.next_slot(wall, self.every)
        return True

    def next_run(self) -> float:
        """When this is next due on the wall clock, for the loop to wait.

        Worked out rather than read where nothing has set it. The live
        trigger never calls `due` -- the clock is the whole of its decision
        and the query returns nothing when no packet has arrived -- so this
        answered "now", the loop waited its floor of half a second, and a
        ten-second upload asked the database a hundred and twenty times a
        minute instead of six.

        Nothing is stored here. The slot belongs to `due`, and a `next_run`
        that moved it would make the loop skip the run it just waited for.
        """
        if self._slot is not None:
            return self._slot
        if self.trigger == "live":
            # This one never reaches `due`, so nothing will ever set the
            # slot: it has to be worked out every time round.
            return schedule.next_slot(time.time(), self.every)
        # The first turn of anything else runs at once rather than waiting
        # out an interval, and `due` takes it from there.
        return time.time()

    def pending(self) -> list[dict]:
        """The records this upload still owes, oldest first.

        Empty when it is up to date, which is the ordinary answer between
        archive intervals and costs one indexed query.
        """
        if self.is_live:
            # Only what is current. A dashboard wants now, and a packet from
            # forty seconds ago published as now is a wrong reading rather
            # than a late one.
            found = self.packets(self.live_through, 1)
            if found:
                self.live_through = int(found[-1].get("dateTime") or 0)
            return found[-1:] if found else []
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
            if result.through and not self.is_live:
                self.progress.sent(self.name, result.through)
                self.progress.save()
            if result.failures:
                self.failures += 1
                log.warning("upload %s: %s", self.name, result.summary())
            elif result.sent:
                self._say(result)
            else:
                log.debug("upload %s: %s", self.name, result.summary())
        except Rejected as exc:
            self.failures += 1
            self.last_summary = str(exc)
            if exc.permanent and self._settled(exc):
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


    def _say(self, result: Any) -> None:
        """One line at a time, but never more than one a minute.

        The live upload runs every ten seconds, so it wrote three hundred and
        sixty identical lines an hour -- `upload live: 1 sent, 0.1s`, over and
        over. A log at that rate is one nobody reads, which costs the lines
        that matter.

        Collected instead, and reported with the two things worth knowing:
        how many times it went, and how far apart. A slower upload is
        unaffected -- more than a minute since the last line means this one
        is printed at once, which is what a five-minute upload has always
        done.

        Only the ordinary case is held back. A refusal or a failed file is
        logged as it happens: something wrong should not wait for a summary.
        """
        now = time.monotonic()
        self._runs_since += 1
        self._sent_since += int(getattr(result, "sent", 0))
        if self._logged_at >= 0 and now - self._logged_at < QUIETLY:
            return
        window = now - self._logged_at if self._logged_at >= 0 else 0.0
        if self._runs_since > 1 and window > 0:
            log.info("upload %s: %d runs in %s, one every %.1fs, %d sent",
                     self.name, self._runs_since, _spell(window),
                     window / self._runs_since, self._sent_since)
        else:
            log.info("upload %s: %s", self.name, result.summary())
        self._logged_at = now
        self._runs_since = 0
        self._sent_since = 0

    def _settled(self, exc: Rejected) -> bool:
        """Whether a refusal has lasted long enough to be believed.

        Most of them are believed at once: a 401 means one thing and no
        amount of waiting changes it. `live.php` answering 404 is the
        exception, because the file is carried up by an export -- so the
        first answer after a new export is configured is a 404 that means
        "not yet", and the file appears a few seconds later.

        Waiting separates the two without having to ask anybody: a wrong
        token answers 404 for ever, and a missing file stops as soon as the
        export that carries it has run once.
        """
        if not exc.after:
            self._refused_since = 0.0
            return True
        now = time.monotonic()
        if not self._refused_since:
            self._refused_since = now
            log.warning("upload %s: %s. Waiting -- a new export carries "
                        "live.php up with it, so this is the expected answer "
                        "until it has run once.", self.name, exc)
            return False
        return now - self._refused_since >= exc.after


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
            elif scheduled.trigger == "live":
                log.info("upload %s publishes live, every %ds",
                         scheduled.name, scheduled.every)
            else:
                log.info("upload %s runs every %ds", scheduled.name, scheduled.every)

    def replace(self, uploads: list[Scheduled]) -> None:
        """Swap in a new set, after the configuration changed.

        A method rather than three assignments at the call site: the events
        and the stop flag have to be rebuilt with the list, and a caller that
        remembers two of the three gets a runner whose threads never wake.
        """
        self.stop()
        self.uploads = uploads
        self._stopping = threading.Event()
        self._wake = {s.name: threading.Event() for s in uploads}
        self._threads = []
        self.start()

    def record_written(self) -> None:
        """A new archive record landed.

        Called from the archiver's thread and returns at once: it sets flags,
        and the upload threads pick them up. Nothing about a network request
        happens on the archiver's thread, which is the whole point.
        """
        for scheduled in self.uploads:
            if scheduled.trigger == "record":
                self._wake[scheduled.name].set()
            elif scheduled.trigger == "live" and scheduled.packets is None:
                # Asked for live but there is no live database in this
                # process -- a split deployment where the archiver has the
                # archive and the listener has the packets. Fall back to the
                # record rather than publishing nothing at all.
                self._wake[scheduled.name].set()

    def stop(self) -> None:
        self._stopping.set()
        for event in self._wake.values():
            event.set()
        for thread in self._threads:
            thread.join(timeout=2)
        for scheduled in self.uploads:
            for what in (scheduled.upload, scheduled.records, scheduled.packets):
                close = getattr(what, "close", None)
                if close is None:
                    continue
                try:
                    close()
                except Exception:
                    log.debug("upload %s did not close cleanly", scheduled.name)

    def _loop(self, scheduled: Scheduled) -> None:
        # A live upload with no live table behind it waits on the record
        # instead, so a split deployment publishes late rather than never.
        waiting = (scheduled.trigger == "record"
                   or (scheduled.trigger == "live" and scheduled.packets is None))
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
                self._stopping.wait(timeout=max(0.5, schedule.wait_for(
                    time.time(), scheduled.next_run())))
                if self._stopping.is_set():
                    return
                fired = ""

            if scheduled.trigger == "live":
                # No `due` check: the clock already decided, and the query
                # returns nothing when no packet has arrived. Asking the
                # database is cheaper than the bookkeeping to avoid it.
                scheduled.run()
                continue

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
          records: Callable[[int, int], list[dict]],
          packets: Callable[[int, int], list[dict]] | None = None,
          by_archive: dict[str, Callable[[int, int], list[dict]]] | None = None,
          packets_by_archive: dict[str, Any] | None = None,
          consoles: dict[str, list[str]] | None = None,
          main_consoles: dict[str, list[str]] | None = None,
          places: list[tuple[str, str, str]] | None = None,
          default_archive: str = "",
          ) -> list[Scheduled]:
    """Turn configuration into things the runner can run.

    Anything that cannot be built is reported and left out. A misconfigured
    upload must not stop the others, and it certainly must not stop the
    station: the readings are what matters, and an upload is a copy of them.

    `by_archive` is one reader per measurement series. An upload naming a
    series that is not there is left out: silently publishing another place's
    data under its credentials is not a fallback.

    `packets_by_archive` is the same split for live readers. Placement is a
    property of the place, so sharing one reader would apply the default
    place's column choices to every other one.

    `places` is every series, as `(name, label, code)`, in the order pages
    present them. Only a live-readings upload uses it, and only where there
    is more than one: one document carries every place, so one page can show
    them all. Built here rather than in `cli` because everything it needs is
    already here -- the live table, each site's consoles, and which of them a
    reading is taken from.
    """
    ready = []
    for name, settings in sorted(configured.items()):
        try:
            upload = make(name, dict(settings))
        except Exception as exc:
            log.warning("upload %s is not usable: %s", name, exc)
            continue
        wanted = str(settings.get("archive") or default_archive).strip()
        if by_archive is not None and wanted not in by_archive:
            log.warning("upload %s names unknown series %r; leaving it out",
                        name, wanted)
            continue
        source = (by_archive or {}).get(wanted, records)

        # And the live packets, through this site's consoles. One live table
        # serves the whole installation, so an upload for one series has to
        # be told which sources are its own -- otherwise it publishes
        # whichever console reported last, from any site.
        #
        # `for_sources` only where the reader has it: a split deployment
        # passes something else here, and an upload publishing everything is
        # what it did before and is not worse than not publishing.
        # And which of that site's consoles a live reading is taken from.
        # An archive record is worked out from all of them together; a live
        # reading is one packet, so something has to say which -- and
        # "whichever reported last" makes a page flicker between a garden
        # and a shed.
        mine = (packets_by_archive or {}).get(wanted, packets)
        named = (consoles or {}).get(wanted) if wanted else None
        main = (main_consoles or {}).get(wanted or "") or []
        pick = str(settings.get("live_source") or "main")
        # `is not None`, not truthiness. An empty list is a place whose
        # stations are known and are none of them -- which is every place
        # between "add it on the Archives page" and pointing a console at
        # it. Read as "nobody said", that place was fed the whole
        # installation's live table, so a site with nothing behind its
        # second place published its first place's readings under the
        # second one's name and counted it as reporting.
        if (named is not None or main) and hasattr(mine, "for_sources"):
            mine = mine.for_sources(named, pick, main)

        # One document, every place, for a site that publishes several. The
        # page reads one file and finds a slice per place; without this an
        # overview showed the same reading in every row, taken from whichever
        # console reported last.
        #
        # Only where the upload can carry them, so nothing here has to know
        # which kind it is: `carry` exists on the live-readings upload and
        # nowhere else, and it is `carry` that refuses a one-place list.
        if places and len(places) > 1 and hasattr(upload, "carry"):
            upload.carry(_places_for(wanted, places, packets,
                                     packets_by_archive, consoles,
                                     main_consoles, pick))
        ready.append(Scheduled(name, upload, progress, source, mine,
                               wanted))
    return ready


def _places_for(home: str, places: list[tuple[str, str, str]],
                packets: Any,
                packets_by_archive: dict[str, Any] | None,
                consoles: dict[str, list[str]] | None,
                main_consoles: dict[str, list[str]] | None,
                pick: str) -> list[Any]:
    """Every series, as the live document wants them, this one's first.

    First because the document has a size limit and drops from the end: the
    place whose pages this upload belongs to is the one that must never be
    the one left out.

    Each place's reader is bound now, in a default argument. A lambda closing
    over the loop variable hands every place the last one's reader, and every
    slice then comes out identical -- which reads as a document that is
    working.
    """
    from .webpush import Place

    ordered = sorted(places, key=lambda one: one[0] != home)
    out = []
    for name, label, code in ordered:
        reader = (packets_by_archive or {}).get(name, packets)
        named = (consoles or {}).get(name)
        main = (main_consoles or {}).get(name) or []
        if named is not None and not named and not main:
            # Known, and none: a place somebody added on the Archives page
            # before pointing a console at it. Left out of the document
            # entirely.
            #
            # Not filtered to an empty list, which is the obvious move and
            # does not work: `Live.__init__` reads an empty list as "nobody
            # said" and hands back every console in the table. The slice
            # would then carry another place's readings under this place's
            # name and code -- wrong data, labelled, on the page built to
            # compare places. Its board row says "no readings yet" and goes
            # on saying it, which is the truth.
            log.debug("no console writes into %r yet; it carries no live "
                      "readings", name)
            continue
        if (named is not None or main) and hasattr(reader, "for_sources"):
            reader = reader.for_sources(named, pick, main)
        if reader is None:
            # A split deployment where the live table is on another machine.
            # Left out rather than carried empty: a slice with no reading is
            # a place the page will draw as silent, which is a different
            # claim from one it does not draw at all.
            continue
        out.append(Place(
            name=name, label=label or name, code=code,
            packet=lambda source=reader: (source.after(0, 1) or [None])[-1],
            # How often this place reports, measured, so the page can tell
            # "late" from "stopped" per place. A console reporting every
            # sixteen seconds and one reporting every five minutes stand on
            # the same site, and one threshold is wrong for one of them.
            #
            # Without it the page falls back to a single fixed window, and
            # the state that says "this station has stopped" is unreachable
            # in a browser: a dead console reads as amber "a bit late" for
            # ever.
            rhythm=getattr(reader, "rhythm", None)))
    return out

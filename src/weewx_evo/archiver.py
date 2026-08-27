"""Working archive records out of stored packets.

This is the service that replaces WeeWX's `StdArchive`. The difference is not
what it computes but where it gets it from: WeeWX accumulates in memory as
packets arrive and writes the result once at the end of the interval, so a
restart in the middle loses the interval and a late packet has nowhere to go.
Here the packets are already in the live table, and building a record is a
function of a time span -- callable now, after a restart, or a week later.

The consequences are worth spelling out, because they are the reason to do
this at all:

  * A restart mid-interval costs nothing. The interval is built from the table
    when it closes, not from what a process happened to remember.
  * A packet arriving after its interval closed marks the interval and it is
    built again. Late data is ordinary data.
  * A record can be corrected. Fix the packets or the calibration, rebuild the
    span, and the archive and its daily summaries follow.

What is *not* different is the arithmetic. Records come out of the same
accumulator WeeWX uses, in the same order, with the same weighting.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .aggregate import Accumulator, start_of_archive_day
from .db.archive import ArchiveStore
from .db.live import LiveStore, interval_stop
from .derive import Deriver
from .obstypes import DEFAULT_POLICY, Policy
from .sources import Policy as SourcePolicy
from .sources import apply as source_merge

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Built:
    """One archive interval, worked out."""

    stop: int
    seconds: int
    record: dict
    accumulator: Accumulator
    packets: int
    from_hardware: bool
    #: Which source supplied each field, where more than one offered it. Empty
    #: with a single station. The full provenance is always in the live table;
    #: this is the summary of what the merge decided.
    provenance: dict[str, str] = field(default_factory=dict)


class Archiver:
    """Turns live packets into archive records and daily summaries."""

    def __init__(self, live: LiveStore, archive: ArchiveStore,
                 interval_seconds: int = 300, policy: Policy = DEFAULT_POLICY,
                 loop_hilo: bool = True, sources: SourcePolicy | None = None,
                 deriver: Deriver | None = None) -> None:
        self.live = live
        self.archive = archive
        self.interval_seconds = interval_seconds
        self.policy = policy
        # Whether LOOP packets sharpen the daily highs and lows. WeeWX's
        # StdArchive option of the same name, and on by default there too.
        self.loop_hilo = loop_hilo
        # Which station wins for which field when several report it. Empty by
        # default, which means every packet contributes everything it carries --
        # the right answer when there is only one station.
        self.sources = sources or SourcePolicy()
        # Readings that follow from other readings: dew point, wind chill,
        # and -- the one that is a measurement rather than a convenience --
        # rain, which almost no console sends and which is otherwise absent
        # from the record entirely.
        self.deriver = deriver or Deriver()

    # -- building --------------------------------------------------------

    def build(self, stop: int, seconds: int | None = None) -> Built | None:
        """Work out the record for the interval ending at `stop`.

        Returns None if no packet fell in the interval. A gap in the data is a
        gap in the archive; inventing a record for it would be a lie that
        averages badly for years.
        """
        seconds = seconds or self.interval_seconds
        start = stop - seconds

        loop, archived = [], []
        for packet in self.live.packets(start, stop):
            (archived if packet.kind == "archive" else loop).append(packet)

        # Decide which station supplies which field before any arithmetic. Two
        # thermometers must not be averaged into one; one of them is the series
        # and the other is a different place.
        loop, provenance = source_merge(loop, self.sources)
        archived, archive_provenance = source_merge(archived, self.sources)
        provenance = {**archive_provenance, **provenance}

        accum = Accumulator(start, stop, policy=self.policy)
        n = 0
        for packet in loop:
            # Derived per packet, before accumulating. The other way round
            # gives the dew point of an average hour, which is not a thing
            # that happened: dewpoint(mean(T)) != mean(dewpoint(T)).
            accum.add_record(self.deriver.apply(packet.record()), weight=1)
            n += 1

        hardware: dict | None = None
        for packet in archived:
            # The console kept its own record. It wins: it was computed from
            # readings we never saw, at a resolution we cannot match. Several
            # sources may deliver one -- there is no primary station here --
            # so they are laid over each other in arrival order.
            hardware = {**(hardware or {}), **packet.record()}

        if hardware is None and n == 0:
            return None

        if hardware is not None:
            record = dict(hardware)
            record.setdefault("interval", seconds / 60.0)
            self.deriver.apply(record)
            if n:
                # Fill in only what the console left out. `augment` never
                # overwrites, which is what keeps hardware values authoritative.
                accum.augment(record)
        else:
            record = accum.record()
            record["interval"] = seconds / 60.0
            # Once more on the finished record, for the few that need the
            # interval: windrun is a speed times a span, and there is no span
            # until the record exists.
            self.deriver.apply(record)

        return Built(stop=stop, seconds=seconds, record=record, accumulator=accum,
                     packets=n, from_hardware=hardware is not None,
                     provenance=provenance)

    # -- writing ---------------------------------------------------------

    def store(self, built: Built, replace: bool = False) -> bool:
        """Write one built interval, then let its LOOP packets sharpen the day.

        The order matters. The record goes in first and carries the sums; the
        accumulator is merged afterwards and touches only highs and lows. Doing
        it the other way round would count the interval twice.
        """
        written = self.archive.add_record(built.record, replace=replace)
        if not written:
            return False
        if self.loop_hilo and built.packets:
            self._sharpen_day(built)
        return True

    def _sharpen_day(self, built: Built) -> None:
        """Fold an interval's highs and lows into its day.

        This is WeeWX's `_updateHiLo`. Only extremes move: the accumulator's
        sums already reached the day through the archive record.
        """
        sod = start_of_archive_day(built.stop)
        day = self.archive._load_day(sod, built.record.get("usUnits"))
        day.merge_hilo(built.accumulator)
        with self.archive.conn:
            self.archive._store_day(sod, day)

    # -- the loop --------------------------------------------------------

    def process_due(self, now: float | None = None, grace: int = 15,
                    replace: bool = False) -> int:
        """Build and store every interval that has closed. Returns how many.

        Safe to call at any moment and safe to interrupt: an interval is only
        cleared from `pending` once its record is in the archive, so a crash
        costs a repeated computation and nothing else.
        """
        done = 0
        for stop, seconds in self.live.due(now=now, grace=grace):
            built = self.build(stop, seconds)
            if built is None:
                # No packets in the span. Nothing to write, and nothing to
                # come back to -- a late packet would mark it pending again.
                self.live.clear_pending(stop)
                continue
            existing = self.archive.exists(stop)
            if existing and not replace:
                log.debug("interval %s already archived, leaving it alone", stop)
            else:
                self.store(built, replace=existing)
                done += 1
            self.live.clear_pending(stop)
        return done

    def catch_up(self, since: float | None = None, until: float | None = None,
                 replace: bool = False) -> int:
        """Build every interval covered by the live table.

        Used at startup, after downtime, and by the differential test. Unlike
        `process_due` this ignores the pending list and works straight from the
        packets, so it also fills intervals whose marks were lost.
        """
        first, last = self.live.span()
        if first is None:
            return 0
        since = max(since, first) if since is not None else first
        until = min(until, last) if until is not None else last

        seconds = self.interval_seconds
        stop = interval_stop(since, seconds)
        done = 0
        while stop <= interval_stop(until, seconds):
            built = self.build(stop, seconds)
            if built is not None:
                existing = self.archive.exists(stop)
                if not existing or replace:
                    self.store(built, replace=existing)
                    done += 1
            self.live.clear_pending(stop)
            stop += seconds
        return done

    def rebuild(self, start: float, stop: float) -> int:
        """Work out every interval in (start, stop] again, replacing what is there.

        The daily summaries of every affected day are rebuilt from the archive
        table afterwards, then re-sharpened from the packets. Extremes cannot
        be subtracted -- a maximum does not remember the runner-up -- so the
        only honest way to correct a day is to build it from nothing.
        """
        seconds = self.interval_seconds
        first = interval_stop(start + 1, seconds)
        last = interval_stop(stop, seconds)

        days: set[int] = set()
        ts = first
        while ts <= last:
            days.add(start_of_archive_day(ts))
            ts += seconds

        # Records first, without touching the summaries: they are about to be
        # thrown away and built again.
        ts, done = first, 0
        while ts <= last:
            built = self.build(ts, seconds)
            if built is not None:
                self.archive.add_record(built.record, replace=True, update_daily=False)
                done += 1
            ts += seconds

        for sod in sorted(days):
            self.archive.rebuild_day(sod)
        if self.loop_hilo:
            ts = first
            while ts <= last:
                built = self.build(ts, seconds)
                if built is not None and built.packets:
                    self._sharpen_day(built)
                ts += seconds
        return done

    def run(self, grace: int = 15, poll: float = 5.0,
            stop_when: object = None) -> None:  # pragma: no cover - a loop
        """Poll for closed intervals until told to stop.

        A plain sleep loop rather than a scheduler. The work is idempotent and
        the interval boundaries come from the packets, so a tick that is late,
        early, or missed entirely changes nothing about the result.
        """
        while stop_when is None or not stop_when():  # type: ignore[operator]
            try:
                n = self.process_due(grace=grace)
                if n:
                    log.info("archived %d interval(s)", n)
            except Exception:
                log.exception("archiver tick failed; carrying on")
            time.sleep(poll)

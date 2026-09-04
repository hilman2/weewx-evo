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
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import units
from .aggregate import Accumulator, start_of_archive_day
from .db.archive import ArchiveStore
from .db.live import DEFAULT_ARCHIVE, LiveStore, interval_stop, sender_parts
from .derive import Deriver
from .obstypes import DEFAULT_POLICY, Policy
from .quality import Check, sender_for
from .quality import Policy as QualityPolicy
from .sources import Policy as SourcePolicy
from .sources import apply as source_merge

log = logging.getLogger(__name__)

#: How far before a span to read for context, at most. A stuck rule counts
#: readings, not minutes, so the run-up is worked out from the longest one on
#: the assumption that packets arrive at least once a minute -- which is the
#: slowest any of these consoles report. Capped, because the point is to seed
#: two numbers per field and not to re-read the day.
MAX_RUN_UP = 6 * 3600


def _run_up(policy: QualityPolicy, seconds: int) -> int:
    """Seconds of packets to read before a span, for the rules that need them."""
    if not policy.limits:
        return seconds
    longest = max((rule.stuck or 0) for rule in policy.limits.values())
    return min(MAX_RUN_UP, max(seconds, longest * 60))


def _pairs(stations: Iterable) -> list[tuple[str, str]]:
    """The station list as (driver, identity) pairs, or a clear refusal.

    A caller holding station *names* is the mistake this catches, and it is
    one that used to pass: `tuple("kirchdorf")` is thirteen single characters,
    which selects nothing at all. The archive would then have been built from
    an empty table, stored, and reported as an interval with no readings --
    which is what a station that has gone quiet also looks like.
    """
    found = []
    for one in stations:
        if isinstance(one, str) or len(tuple(one)) != 2:
            raise TypeError(
                f"an archiver takes (driver, identity) pairs, not {one!r}. "
                "A name is a lookup that changes; the live table is keyed on "
                "the pair. `placement.Placer.identities` turns one into the "
                "other.")
        driver, identity = one
        found.append((str(driver), str(identity)))
    return found


def _sender_ids(senders: Iterable[str]) -> list[str]:
    """Strict canonical ids, never friendly names or driver objects."""
    found = []
    for one in senders:
        value = str(one)
        sender_parts(value)
        found.append(value)
    return found


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
    #: Readings quality control refused, by name and count. Empty where no
    #: rules are configured, which is most installations. Reported rather
    #: than dropped in silence: a silent drop looks exactly like a broken
    #: sensor, which is the thing this is meant to help find.
    dropped: dict[str, int] = field(default_factory=dict)


class Archiver:
    """Turns live packets into archive records and daily summaries."""

    def __init__(self, live: LiveStore, archive: ArchiveStore,
                 interval_seconds: int = 300, policy: Policy = DEFAULT_POLICY,
                 loop_hilo: bool = True, sources: SourcePolicy | None = None,
                 deriver: Deriver | None = None,
                 name: str = DEFAULT_ARCHIVE,
                 stations: Iterable[tuple[str, str]] | None = None,
                 quality: QualityPolicy | None = None,
                 placer: object | None = None,
                 senders: Iterable[str] | None = None) -> None:
        self.live = live
        self.archive = archive
        #: Which series this is. It keys this archiver's own place in the
        #: pending table, so two of them working the same live table do not
        #: clear each other's work.
        self.name = name
        #: Which consoles belong here, as (driver, identity) pairs, or None
        #: for all of them. None is the single-archive case and is what every
        #: installation had before there could be two: it takes everything
        #: that arrives, including consoles nobody has announced. With two
        #: archives that guess is not available, so each is told.
        #:
        #: The pair rather than the name, because the live table records the
        #: pair -- a name is a lookup that changes, and this list has to go on
        #: selecting the same rows after somebody renames a console.
        if stations is not None and senders is not None:
            raise TypeError("choose canonical senders or legacy station pairs")
        self.stations = None if stations is None else _pairs(stations)
        #: Canonical live-journal keys for callers without a place-aware
        #: placer. The service gets its current selection from
        #: ``placer.selected_senders()`` at the start of every build, so a
        #: member edit in archives.toml needs no restart.
        self.senders = None if senders is None else _sender_ids(senders)
        #: Turns a stored reading into an archive column, out of
        #: `placement.toml`. None means the packets are taken as they are,
        #: which is what a WeeWX-named packet from a collector or a test
        #: already is.
        self.placer = placer
        #: Which dialects have already been reported as unplaceable, so a
        #: misconfiguration is one line rather than one per packet.
        self._said_unplaced: set[str] = set()
        self.interval_seconds = interval_seconds
        self.policy = policy
        # Whether LOOP packets sharpen the daily highs and lows. WeeWX's
        # StdArchive option of the same name, and on by default there too.
        self.loop_hilo = loop_hilo
        # Optional low-level source selection for callers of this class. The
        # product runtime never supplies it: Place membership, member roles and
        # Place-scoped mappings are its complete routing authority.
        self.sources = sources
        # Readings that follow from other readings: dew point, wind chill,
        # and -- the one that is a measurement rather than a convenience --
        # rain, which almost no console sends and which is otherwise absent
        # from the record entirely.
        self.deriver = deriver or Deriver()
        # Calibration and limits. Applied per packet and before deriving, so
        # a corrected reading is what the dew point is computed from and a
        # refused one never reaches the accumulator. Empty by default.
        self.quality = quality or QualityPolicy()

    # -- building --------------------------------------------------------

    def build(self, stop: int, seconds: int | None = None) -> Built | None:
        """Work out the record for the interval ending at `stop`.

        Returns None if no packet fell in the interval. A gap in the data is a
        gap in the archive; inventing a record for it would be a lie that
        averages badly for years.
        """
        seconds = seconds or self.interval_seconds
        start = stop - seconds

        # One reading of the placements for the whole interval, run-up
        # included. Consulted live, a rebuild running while somebody saves the
        # settings page would place the first half of a span by one file and
        # the second half by another -- and the record it produced would be
        # plausible, reproducible by nothing, and impossible to notice.
        placer = self._placing()
        place_selects = (placer is not None
                         and getattr(placer, "archive_definition", None) is not None
                         and hasattr(placer, "selected_senders"))
        selected_senders = (placer.selected_senders()
                            if place_selects else self.senders)
        selected_stations = (None if selected_senders is not None
                             or place_selects else self.stations)

        loop, archived = [], []
        for packet in self.live.packets(
                start, stop, stations=selected_stations,
                senders=selected_senders):
            if placer is None:
                self._unplaced(packet)
                placed = packet
            else:
                placed = placer.place(packet)
            if placed is None:
                # Nothing this archive has a column for. An extra station's
                # upload of wind and rain, or a console every one of whose
                # readings is placed nowhere.
                continue
            (archived if placed.kind == "archive" else loop).append(placed)

        # `sources.Policy` remains an explicit low-level API, but is not part
        # of the configured Archiver path. A caller opting into it gets the old
        # per-field reduction after placement; ordinary runs have no second
        # routing decision hidden behind their Place policy.
        provenance: dict[str, str] = {}
        if self.sources is not None:
            loop, provenance = source_merge(loop, self.sources)
            archived, archive_provenance = source_merge(archived, self.sources)
            provenance = {**archive_provenance, **provenance}

        checker = self._checker(start, seconds, placer,
                                selected_senders, selected_stations)

        accum = Accumulator(start, stop, policy=self.policy)
        n = 0
        for packet in loop:
            # Corrected and checked before deriving. The other order computes
            # a dew point from a reading that is about to be corrected or
            # thrown away, and leaves it in the record either way.
            record = self._sound(checker, packet)
            # Derived per packet, before accumulating. The other way round
            # gives the dew point of an average hour, which is not a thing
            # that happened: dewpoint(mean(T)) != mean(dewpoint(T)).
            accum.add_record(self.deriver.apply(record), weight=1)
            n += 1

        hardware: dict | None = None
        for packet in archived:
            # The console kept its own record. It wins: it was computed from
            # readings we never saw, at a resolution we cannot match. Several
            # sources may deliver one -- there is no primary station here --
            # so they are laid over each other in arrival order.
            #
            # Checked all the same. A console with a dead sensor writes its
            # own records out of the same reading.
            hardware = {**(hardware or {}), **self._sound(checker, packet)}

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

        if checker is not None and checker.dropped:
            log.info("%s: interval ending %d dropped %s",
                     self.name, stop, checker.summary())

        return Built(stop=stop, seconds=seconds, record=record, accumulator=accum,
                     packets=n, from_hardware=hardware is not None,
                     provenance=provenance,
                     dropped=dict(checker.dropped) if checker else {})

    def _unplaced(self, packet: object) -> None:
        """Say once that a packet arrived in a vocabulary nothing translates.

        An archiver with no placer takes the readings as they are, which is
        right for a WeeWX-named packet from a collector or a test. Given one
        that names a dialect it is not right and it is not visible: every
        field goes to the accumulator under the console's own name, the
        archive has a column for none of them, and the record written is
        empty. It builds, it stores, it reports success.
        """
        dialect = getattr(packet, "dialect", None)
        if dialect is None or dialect in self._said_unplaced:
            return
        self._said_unplaced.add(dialect)
        log.error(
            "%s: packets arrive as %r and this archiver has no placement, so their "
            "readings keep the names the console used and the archive has a column "
            "for none of them. Records will be built and will be empty.",
            self.name, dialect)

    def _placing(self):
        """This archiver's placements, re-read and then frozen for one build.

        Re-read, because the settings page writes that file and this is a
        different process: without it a placement saved on the page would not
        reach a record until somebody restarted, which is the promise the page
        makes and the bug this whole arrangement exists to make impossible.

        Frozen, because `build` has to be a function of a time span. Consulted
        live, a rebuild running while somebody saves would place the first half
        of a span by one file and the second half by another, and the record it
        produced would be plausible and reproducible by nothing.

        `replace` rather than two assignments: the merged copies the placer
        keeps have to go with the file they were merged from, and a caller
        that swapped one and kept the other gets a placer reporting the new
        file and applying the old one.

        None where nothing places, which is a store handed WeeWX-named
        packets by a test or by a collector and given no placer at all.
        """
        if self.placer is None:
            return None
        refresh = getattr(self.placer, "refresh", None)
        if refresh is not None:
            refresh()
        self.placer.placements.refresh()
        self.placer.replace(placements=self.placer.placements.snapshot())
        return self.placer

    def _checker(self, start: int, seconds: int, placer=None,
                 senders=None, stations=None) -> Check | None:
        """A fresh checker for this span, seeded from the packets before it.

        Fresh, because `build` has to be a function of a time span and
        nothing else: a checker carried between calls would make a record
        depend on what was built before it, and a rebuild would then differ
        from the original.

        Seeded, because the spike and stuck rules need a previous reading and
        the first packet of an interval has none. Without the run-up, a
        boundary is a hole a spike walks through every five minutes. It reads
        the same live table the span comes from, so it is deterministic.

        The run-up is placed like everything else. Missed, the limits would be
        matched against raw names, no rule would find its field, and the spike
        and stuck checks would run over the boundary they exist for and
        silently pass everything.
        """
        if not self.quality:
            return None
        checker = Check(self.quality)
        run_up = _run_up(self.quality, seconds)
        if run_up:
            checker.context(self._placed(
                self.live.packets(start - run_up, start, kind="loop",
                                  stations=stations, senders=senders), placer))
        return checker

    @staticmethod
    def _placed(packets, placer):
        for packet in packets:
            found = placer.place(packet) if placer is not None else packet
            if found is not None:
                yield found

    def _sound(self, checker: Check | None, packet: object) -> dict:
        """One packet, corrected and checked. The record itself where neither."""
        record = packet.record()
        if checker is None:
            return record
        # Calibration follows the immutable live-journal key. A display name
        # may change, and the bare hardware identity is not unique across
        # drivers; neither may select a physical correction.
        station = sender_for(packet)
        system = units.system_from(record.get("usUnits"),
                                   default=units.METRICWX)
        record = checker.calibrate(record, station, system)
        record, _verdicts = checker.check(
            record, float(record.get("dateTime") or 0), station, system)
        return record

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
        # ArchiveStore runs in autocommit mode. Its connection context manager
        # therefore does not start a transaction; without the explicit helper
        # every one of the standard schema's daily rows is an individual
        # FULL-sync commit. Keep the record and its LOOP extrema atomic, too.
        with self.archive._transaction():
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
        for stop, seconds in self.live.due(now=now, grace=grace,
                                           archive=self.name):
            built = self.build(stop, seconds)
            if built is None:
                # No packets in the span. Nothing to write, and nothing to
                # come back to -- a late packet would mark it pending again.
                self.live.clear_pending(stop, self.name)
                continue
            existing = self.archive.exists(stop)
            if existing and not replace:
                log.debug("interval %s already archived, leaving it alone", stop)
            else:
                self.store(built, replace=existing)
                done += 1
            self.live.clear_pending(stop, self.name)
        return done

    def catch_up(self, since: float | None = None, until: float | None = None,
                 replace: bool = False) -> int:
        """Build every interval covered by the live table that is not archived.

        Used at startup, after downtime, and by the differential test. Unlike
        `process_due` this ignores the pending list and works straight from the
        packets, so it also fills intervals whose marks were lost.

        **What is already in the archive is not built again.** It used to be:
        the record was built, `exists` was asked afterwards, and the answer
        threw the work away. At startup that meant rebuilding the whole live
        retention every time -- reading the packets, running the quality
        rules, deriving and accumulating -- to arrive at records that were all
        already there. Measured on a running instance: 153 intervals, 43
        seconds, and "caught up 0" at the end of it.

        The cost is one primary-key lookup per interval, against building one.
        `replace` still builds everything, because that is what it is for.
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
            existing = self.archive.exists(stop)
            if existing and not replace:
                # Asked before building rather than after. A gap inside the
                # live span is still filled: this skips the intervals that
                # are there, not the ones that are missing.
                self.live.clear_pending(stop, self.name)
                stop += seconds
                continue
            built = self.build(stop, seconds)
            if built is not None:
                self.store(built, replace=existing)
                done += 1
            self.live.clear_pending(stop, self.name)
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

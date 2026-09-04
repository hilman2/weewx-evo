"""Raw field names nobody has placed yet, and what the driver would guess.

The other half of `placement.py`, and the half that is *observed* rather than
decided -- the same split as `stations.toml` against `sightings.py`, for the
same reason.

## Why inference cannot happen where it is used

`Archiver.build` has to be a function of a time span: the same packets and the
same files must give the same record today and in a year, because `rebuild`
depends on it. An inferrer learns from what it has seen, so a placer that
inferred would give a different answer depending on which console's traffic
went through it first -- and the record it produced would be plausible,
reproducible by nothing, and impossible to notice.

So inference runs **once**, here, when a raw name turns up that this
installation has not seen before. What it decides is written down
(`placement.promote`), and from then on the read side is a lookup.

That is a gain and not a compromise. Before this the guess lived in a
`Mapper` in one process, was re-derived from scratch on every start, and was
invisible: `tf_ch9 -> soilTemp9` happened, nothing recorded that it had, and
nobody could disagree with it. Now it is a line in a file with `learned =
true` on it, which somebody can read, change, or delete.

## The cost on the ordinary path

One set difference per upload. The inferrer is built and run only when a name
arrives that is not already in the set, which on a settled installation is
never.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field

log = logging.getLogger(__name__)

#: Where the proposals sit in the live database's metadata. Beside the
#: sightings, and for the same reason: the listener writes no configuration
#: file, and the database is the only channel between the parts.
METADATA_KEY = "placements"

#: How long changes are held before being written back.
FLUSH_AFTER = 60.0

#: A cap, so a console that varies its field names cannot grow this without
#: limit. The oldest go first.
MAX_PROPOSALS = 500


@dataclass
class Proposal:
    """One raw name, and where it would go if nobody said otherwise."""

    driver: str
    dialect: str
    station: str
    raw: str
    #: The column the driver would put it in, or empty where it could not
    #: name one. Empty is worth keeping: it is what the settings page shows
    #: as "this arrives and goes nowhere", which is the row somebody opens
    #: the page for.
    field: str = ""
    #: What the driver thinks it measures, so a column made for it gets a
    #: unit rather than printing a bare number beside converted ones.
    group: str = ""
    #: Whether the driver would act on this by itself under `series`. An
    #: uncertain guess is offered and never promoted.
    certain: bool = False
    #: The driver's own sentence about how it got there, for the page.
    why: str = ""
    first_seen: int = 0
    last_seen: int = 0
    #: What it last carried. A name alone does not say whether a placement is
    #: right; "65.5" beside `tf_ch1` does.
    last_value: object = None

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.driver, self.dialect, self.station, self.raw)


@dataclass
class Proposals:
    """Every raw name seen, and what was guessed about it."""

    store: object | None = None
    seen: dict[tuple[str, str, str, str], Proposal] = field(default_factory=dict)
    #: Which (driver, dialect, station) triples have had their names read
    #: already, so the steady path is a set difference and nothing more.
    known: dict[tuple[str, str, str], set[str]] = field(default_factory=dict)
    _dirty: bool = False
    _flushed: float = 0.0

    def __post_init__(self) -> None:
        self.load()

    # -- reading and writing -------------------------------------------

    def load(self) -> None:
        if self.store is None:
            return
        try:
            raw = self.store.get_meta(METADATA_KEY)
        except Exception:
            log.debug("could not read the placement proposals", exc_info=True)
            return
        if not raw:
            return
        try:
            found = json.loads(raw)
        except ValueError:
            log.warning("the stored placement proposals are not readable; starting over")
            return
        for entry in found if isinstance(found, list) else []:
            try:
                one = Proposal(**entry)
            except TypeError:
                # Written by a newer version with a field this one has never
                # heard of. Skipped rather than fatal: what it costs is one
                # row on a page, and the reading itself is in the table.
                continue
            self.seen[one.key] = one
            self.known.setdefault(
                (one.driver, one.dialect, one.station), set()).add(one.raw)

    def flush(self, force: bool = False) -> None:
        """Write them back, if there is anything to write."""
        if self.store is None or not self._dirty:
            return
        now = time.time()
        if not force and now - self._flushed < FLUSH_AFTER:
            return
        keep = sorted(self.seen.values(), key=lambda one: one.last_seen)
        keep = keep[-MAX_PROPOSALS:]
        try:
            self.store.set_meta(METADATA_KEY,
                                json.dumps([asdict(one) for one in keep]))
        except Exception:
            # A proposal that cannot be recorded must not stop the reading
            # that was being recorded when it happened.
            log.debug("could not store the placement proposals", exc_info=True)
            return
        self._dirty = False
        self._flushed = now

    # -- what the listener does ----------------------------------------

    def saw(self, packet: object, station: str, driver: object,
            mode: str = "series", when: float | None = None) -> int:
        """Note the raw names in one packet. Returns how many were new.

        Returns 0 without asking the driver anything on the ordinary path,
        which is every packet after the first from a given console.

        Args:
            packet (weewx_evo.db.live.Packet): As stored, so `data` holds the
                names the console used.
            station (str): What this console is called, which is what a
                placement is written against.
            driver (object): The driver that read it. Asked for its guesses
                through `drivers.place_with`, so a driver that does not place
                simply contributes nothing.
            mode (str): The installation's `infer_unknown`. Passed straight
                to the driver: `off` still records the names, so the page can
                show what arrives and goes nowhere.
        """
        dialect = getattr(packet, "dialect", None)
        if dialect is None:
            # The names are already ours. There is nothing to guess about
            # them, and the archive either has the column or does not --
            # which `weewx-evo columns` answers.
            return 0
        data = getattr(packet, "data", None) or {}
        triple = (packet.driver, dialect, station)
        already = self.known.setdefault(triple, set())
        fresh = [name for name in data if name not in already]
        if not fresh:
            return 0
        already.update(fresh)

        now = int(when or time.time())
        guessed = self._guessed(driver, data, dialect, mode)
        for name in fresh:
            one = Proposal(driver=packet.driver, dialect=dialect, station=station,
                           raw=name, first_seen=now)
            found = guessed.get(name)
            if found is not None:
                one.field = str(getattr(found, "field", "") or "")
                one.group = str(getattr(found, "group", "") or "")
                one.certain = bool(getattr(found, "certain", False))
                one.why = str(getattr(found, "why", "") or "")
            one.last_seen = now
            one.last_value = data.get(name)
            self.seen[one.key] = one
        self._dirty = True
        log.info("%s sends %d name(s) nothing has placed yet: %s", station,
                 len(fresh), ", ".join(sorted(fresh)[:8]))
        self.flush(force=True)
        return len(fresh)

    @staticmethod
    def _guessed(driver: object, data: dict, dialect: str, mode: str) -> dict:
        """What the driver would make of these names, keyed by raw name.

        Empty when it cannot say, which is every driver that does not place
        and every failure. A proposal with no guess is still worth having:
        the page shows it as a reading that arrives and goes nowhere.
        """
        from . import drivers

        try:
            placed = drivers.place_with(driver, data, dialect, {}, infer=mode)
        except Exception:
            log.debug("could not ask %r about its unplaced names", dialect,
                      exc_info=True)
            return {}
        if placed is None:
            return {}
        return {getattr(one, "raw", ""): one for one in placed.proposals}

    # -- what the settings page reads ----------------------------------

    def all(self) -> list[Proposal]:
        """Every proposal, newest first."""
        return sorted(self.seen.values(), key=lambda one: -one.last_seen)

    def for_station(self, station: str) -> list[Proposal]:
        return [one for one in self.all() if one.station == station]

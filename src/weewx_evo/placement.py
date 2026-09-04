"""Where each reading a console sends is written.

The live table holds what the *sensor* said, under the sensor's own names (see
`db/live.py`). This module is the other half: which archive column each of
those readings goes into, for one measurement series.

## Why it is here and not in the driver

With WeeWX the driver has to decide, because nothing sits between it and the
accumulator -- a packet reaching `StdArchive` is already `outTemp`, or it is
nothing. Here the live table sits in between, so the decision can be made on
the way out, and that changes what a wrong decision costs:

    at the door       the reading is gone. No rebuild brings it back, because
                      what was thrown away is not in any file.
    on the way out    the reading is in the journal. Change the line, rebuild
                      the span, and the archive follows.

That is the same argument `quality.py` makes for living in the archiver, and
it is worth more here: a limit set too tightly loses one reading, a field
placed in a column that already holds another sensor's history mixes two
series, and nothing afterwards can separate them.

## The catalog knows the protocol, not the garden

`tf_ch1` is a WN34 probe, and every Ecowitt catalog agrees. Whether it is in
the compost heap, under the lawn or lying in the sun on a windowsill is known
only to whoever put it there -- and often not until they have watched the
numbers for a week. Under the old arrangement that week had already gone
through the catalog's guess.

## The one rule for this module

**Nothing here learns.** `Archiver.build` is a function of a time span, and
`rebuild` depends on that: the same packets and the same files must give the
same record today and in a year. So the inferrer is switched off here and
every decision it ever made is written down instead (`placement.toml`,
`learned = true`, promoted by `promote()`), which turns a silent per-process
guess into something with a record that somebody can overrule.

The consequence to keep in mind: `build` is now a function of the span, the
place and `placement.toml`. Which is the point -- but both files and the live
sender directory must be snapshotted for the length of a build rather than
consulted live, or a rebuild running while somebody saves the settings page
would disagree with itself halfway through a span.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import roles
from .db.live import Packet, SenderIdentity, sender_id

log = logging.getLogger(__name__)

FILENAME = "placement.toml"

#: What a placement says when a reading is to be written nowhere at all.
#: Spelled the same as `mapping.NOWHERE` and `adminfields.NOWHERE`, and passed
#: straight through to the driver's own map: an empty placement and no
#: placement are different answers, and only this one means somebody decided.
NOWHERE = "-"

#: What happens to a reading no line mentions.
CATALOG = "catalog"   # the driver places it, which is what one console wants
NOWHERE_ELSE = "nowhere"  # only what is listed is written -- an extra station
UNLISTED = (CATALOG, NOWHERE_ELSE)
MAX_DIAGNOSTICS = 512


@dataclass(frozen=True, slots=True)
class Takes:
    """One scope, and what it says about the readings in it.

    `archive` is required, and a scope without one never matches: a rule
    written before a place existed must not start applying to it. Empty
    `station` or `dialect` still means any sender or vocabulary *inside that
    one archive*. The narrowest scope wins, field by field.
    """

    archive: str = ""
    station: str = ""
    dialect: str = ""
    #: Worked out from the field name and promoted, rather than chosen. Kept
    #: apart so that a better inference in a later version can rewrite it,
    #: and so that a person's decision is never quietly replaced.
    learned: bool = False
    #: What happens to a reading with no line of its own: `catalog` or
    #: `nowhere`. The second is what an extra station needs -- without it a
    #: sensor added to one next year would be placed by the catalog into the
    #: main station's column, silently, which is the failure `roles.py` was
    #: written to prevent.
    unlisted: str = CATALOG
    #: Raw name -> archive column, or `-` for nowhere.
    fields: dict[str, str] = field(default_factory=dict)

    def covers(self, archive: str, station: str, dialect: str) -> bool:
        return (bool(self.archive) and self.archive == archive
                and (not self.station or self.station == station)
                and (not self.dialect or self.dialect == dialect))

    @property
    def score(self) -> int:
        """How specific this scope is. Higher wins."""
        return 4 * bool(self.archive) + 2 * bool(self.station) + bool(self.dialect)


@dataclass
class Placements:
    """Every placement this installation has decided or been told."""

    takes: list[Takes] = field(default_factory=list)
    #: What a column measures, where neither the core schema nor the driver's
    #: own table says. Beside the placements because it is the same decision:
    #: a column with no unit group prints a bare number on a page where
    #: everything around it has been converted.
    groups: dict[str, str] = field(default_factory=dict)
    path: Path | None = None
    #: A hash of the file as it was last read, so `refresh` can tell a
    #: change from a re-save. Not a timestamp -- see `refresh`.
    stamp: int = 0
    checked: float = 0.0

    # -- looking things up ---------------------------------------------

    def matching(self, archive: str, station: str, dialect: str) -> list[Takes]:
        """Every scope that covers this console, least specific first.

        At equal specificity a learned scope comes before a chosen one, so a
        person's decision is what survives the merge.
        """
        found = [one for one in self.takes if one.covers(archive, station, dialect)]
        return sorted(found, key=lambda one: (one.score, not one.learned))

    def extensions(self, archive: str, station: str, dialect: str) -> dict[str, str]:
        """The placements for one console, merged. Raw name -> column or `-`."""
        out: dict[str, str] = {}
        for one in self.matching(archive, station, dialect):
            out.update(one.fields)
        return out

    def unlisted(self, archive: str, station: str, dialect: str) -> str:
        """What happens to a reading with no line, for one console."""
        answer = CATALOG
        for one in self.matching(archive, station, dialect):
            if one.unlisted in UNLISTED:
                answer = one.unlisted
        return answer

    def snapshot(self) -> Placements:
        """A copy that will not change under a build.

        `Takes` is frozen and `decide` replaces rather than mutates, so the
        shallow copy is enough -- and it has to be cheap, because a rebuild
        takes one of these per interval.
        """
        return Placements(takes=list(self.takes), groups=dict(self.groups),
                          path=self.path, stamp=self.stamp)

    # -- changing them -------------------------------------------------

    def decide(self, archive: str, station: str, dialect: str,
               raw: str, column: str, learned: bool = False) -> None:
        """Say where one raw reading goes. An empty column forgets the decision.

        A learned decision never overwrites a chosen one: inference proposes,
        and what somebody has actually said stays said.
        """
        if not archive:
            raise ValueError("a placement must name its archive")
        for at, one in enumerate(self.takes):
            if (one.archive == archive and one.station == station
                    and one.dialect == dialect and one.learned == learned):
                fields = dict(one.fields)
                if column:
                    fields[raw] = column
                else:
                    fields.pop(raw, None)
                self.takes[at] = replace(one, fields=fields)
                return
        if not column:
            return
        if learned and any(raw in one.fields for one
                           in self.matching(archive, station, dialect)
                           if not one.learned):
            return
        self.takes.append(Takes(archive=archive, station=station, dialect=dialect,
                                learned=learned, fields={raw: column}))

    def set_unlisted(self, archive: str, station: str, dialect: str, how: str) -> None:
        """Whether unlisted readings follow the catalog or are dropped."""
        if not archive:
            raise ValueError("a placement must name its archive")
        if how not in UNLISTED:
            raise ValueError(f"unlisted is one of {UNLISTED}, not {how!r}")
        for at, one in enumerate(self.takes):
            if (one.archive == archive and one.station == station
                    and one.dialect == dialect and not one.learned):
                self.takes[at] = replace(one, unlisted=how)
                return
        self.takes.append(Takes(archive=archive, station=station, dialect=dialect,
                                unlisted=how))

    # -- keeping up with the file --------------------------------------

    def refresh(self, every: float = 5.0) -> bool:
        """Re-read the file if it has changed. True when it did.

        The same discipline as `stations.Register.refresh`, and for the same
        reason: the settings page writes this file and the archiver is a
        different process. Without it a placement saved on the page would not
        reach a record until somebody restarted the service -- which is
        exactly the bug this arrangement is meant to make impossible.
        """
        import time as clock

        if self.path is None:
            return False
        now = clock.time()
        if now - self.checked < every:
            return False
        self.checked = now
        try:
            # The contents, not the timestamp. A placement file is a few
            # kilobytes and this runs once per interval, so reading it costs
            # nothing -- and a timestamp does not answer the question on
            # every filesystem. Measured in the test container, whose bind
            # mount has one-second granularity: a decision saved in the same
            # second as the one before it kept the same `st_mtime`, so the
            # change was invisible and stayed invisible for ever.
            stamp = hash(self.path.read_bytes())
        except OSError:
            return False
        if stamp == self.stamp:
            return False
        try:
            fresh = load(self.path)
        except Exception:
            # A half-written or hand-edited file that does not parse. The
            # previous placements stay: the alternative is every reading
            # falling back to the catalog, which for an extra station means
            # writing over the main station's columns.
            log.exception("could not re-read %s; keeping the placements already loaded",
                          self.path)
            self.stamp = stamp
            return False
        self.takes = fresh.takes
        self.groups = fresh.groups
        self.stamp = stamp
        log.info("%s changed: %d placement scope(s)", self.path, len(self.takes))
        return True


class Placer:
    """Journal packets as WeeWX-named packets, for one archive.

    A pure lookup. The inferrer is off, so a raw name the catalog does not
    know and nobody has ruled on falls out the same way every time -- whether
    the span is being built now or rebuilt in a year.
    """

    def __init__(self, archive: Any, placements: Placements,
                 directory: Any = None, registry: Any = None,
                 archives: Any = None) -> None:
        # An Archive object carries the per-place policy for each member. A
        # string remains accepted for narrow tools and old callers; it means
        # the plain main/indoor policy, never the old global station policy.
        self.archive_definition = archive if hasattr(archive, "policy_for") else None
        self.archive = str(getattr(archive, "name", archive))
        self.placements = placements
        # A LiveStore in the archive service; a station Register remains
        # accepted by narrow listener/UI callers during the configuration
        # migration. No archive builder passes one.
        self.directory = directory
        self.archives = archives
        self._senders: dict[str, SenderIdentity] = {}
        self._read_directory()
        self._dropped: dict[str, int] = {}
        # Merged placements per (name, dialect). Rebuilt whole in `replace`,
        # never patched: a cache that keeps some entries across a change is
        # a build that disagrees with the file it claims to follow.
        self._decisions: dict[tuple[str, str], tuple[dict[str, str], str]] = {}

    # -- who sent it -----------------------------------------------------

    def _read_directory(self) -> None:
        """Snapshot labels from the live DB (or a listener-side register)."""
        if self.directory is None:
            self._senders = {}
            return
        source = getattr(self.directory, "senders", None)
        if source is not None:
            entries = source()
        else:
            values = list(self.directory)
            # Transitional listener/status callers already hold this narrow
            # register. Keeping support here does not widen the archive path:
            # build_archivers passes the LiveStore and its boundary test
            # poisons every driver/station fallback.
            entries = (values if all(hasattr(one, "sender") for one in values)
                       else [SenderIdentity(
                           sender=sender_id(one.driver, one.identity),
                           driver=one.driver, identity=one.identity,
                           label=one.name)
                           for one in values])
        self._senders = {str(one.sender): one for one in entries}

    def refresh(self) -> None:
        """Freeze current place policy and live sender metadata for a build."""
        if self.archives is not None:
            self.archives.refresh()
            try:
                fresh = self.archives.get(self.archive)
            except (KeyError, LookupError, ValueError):
                log.exception("archive %r disappeared; keeping its last policy",
                              self.archive)
            else:
                self.archive_definition = fresh
        self._read_directory()
        self._decisions = {}

    def station_of(self, packet: Packet) -> Any:
        """Display metadata for this packet, or None for an unknown sender."""
        return self.announced(packet.driver, packet.identity)

    def announced(self, driver: str, identity: str) -> Any:
        return self._senders.get(sender_id(driver, identity))

    def sender_of(self, packet: Packet) -> str:
        """The immutable member key used for every archive decision."""
        return packet.sender_id

    def name_of(self, packet: Packet) -> str:
        """Friendly UI name, falling back to the canonical sender id."""
        return self.named(packet.driver, packet.identity)

    def named(self, driver: str, identity: str) -> str:
        """What to call the console behind a (driver, identity) pair.

        An unannounced one is shown by the identity it gave. The pair rather
        than a packet lets a query grouping by it put names on its rows without
        reading a packet back. Routing continues to use the canonical ID.
        """
        canonical = sender_id(driver, identity)
        found = self._senders.get(canonical)
        return found.label if found is not None and found.label else canonical

    def identities(self, names: Iterable[str]) -> list[tuple[str, str]]:
        """Compatibility lookup for non-archive readers during migration.

        Archive code selects sender ids directly and never calls this method.
        """
        found = []
        for name in names:
            entry = self._senders.get(str(name))
            if entry is None:
                entry = next((one for one in self._senders.values()
                              if one.label == name), None)
            if entry is not None:
                found.append((entry.driver, entry.identity))
        return found


    def selected_senders(self, role: str | None = None) -> list[str] | None:
        """This place's live-db selection, optionally narrowed by role.

        A broad ``senders = "*"`` remains ``None`` when no role is requested,
        because that is the live reader's explicit wildcard.  A role needs a
        concrete list and is therefore resolved against this frozen live
        sender-directory snapshot.
        """
        if self.archive_definition is None:
            return []
        selected = getattr(self.archive_definition, "senders", ())
        if selected is None and role is None:
            return None
        if role is not None and role not in roles.ROLES:
            raise ValueError(f"sender role is one of {roles.ROLES}, not {role!r}")
        candidates = list(self._senders) if selected is None else list(selected)
        found: list[str] = []
        for canonical in candidates:
            canonical = str(canonical)
            if (role is not None
                    and self.archive_definition.policy_for(canonical).role != role):
                continue
            if canonical not in found:
                found.append(canonical)
        return found

    def selected_main_senders(self) -> list[str]:
        """Concrete main-sender addresses for live publishing."""
        selected = self.selected_senders(role=roles.MAIN)
        # A role-filtered selection is always concrete, including broad
        # places: it was resolved against the frozen directory above.
        return [] if selected is None else selected

    # -- placing ---------------------------------------------------------

    def place(self, packet: Packet) -> Packet | None:
        """One journal packet in this archive's column names, or None.

        None means the packet said nothing this archive can hold: an extra
        station's upload of nothing but wind, or a console whose every reading
        is placed nowhere.
        """
        member = self.sender_of(packet)
        decisions, unlisted = self._for(member, packet.dialect or "")

        if packet.dialect is None:
            data = _renamed(packet.data, decisions)
            units = packet.usUnits
        else:
            mapped = _mapped(packet.data, packet.mapping, decisions,
                             packet.usUnits)
            if mapped is None:
                # An old row from before mappings were persisted, or a damaged
                # one. Keep its raw names rather than inventing a catalog, and
                # say why the archive cannot use them. Crucially, no driver is
                # imported here to fill the gap.
                self._cannot_place(packet.driver, packet.dialect)
                return None
            else:
                data, units, groups = mapped
                if groups:
                    self._install_groups(groups, packet.driver, packet.dialect)

        # A reading the console explicitly did not take. Dropped rather than
        # stored as a null: null is a measurement, and a rain gauge reporting
        # 0.0 because its value was refused is indistinguishable from a dry
        # afternoon.
        data = {obs: value for obs, value in data.items() if value is not None}

        if unlisted == NOWHERE_ELSE:
            data = self._only_listed(data, decisions, member)
        data = self._as_the_place_says(data, member, decisions)
        if not data:
            return None
        return replace(packet, data=data, usUnits=units, source=member)

    def _install_groups(self, groups: dict[str, str], driver: str,
                        dialect: str) -> None:
        """Add only previously unknown catalog groups; authority never moves.

        Core groups and `placement.toml` are authoritative. A catalog also
        cannot overwrite a group learned from another packet: doing so would
        let one driver's data change the interpretation of another place.
        """
        from . import units as unit_defs

        current = unit_defs.contributed()
        added: dict[str, str] = {}
        conflicts: list[str] = []
        for column, group in groups.items():
            authoritative = (self.placements.groups.get(column)
                             or unit_defs.GROUPS.get(column))
            existing = authoritative or current.get(column)
            if existing is None:
                added[column] = group
            elif existing != group:
                conflicts.append(column)
        if added:
            unit_defs.contribute({**current, **added})
        key = (_safe_name(driver), _safe_name(dialect))
        if conflicts and _first(_group_conflicts, key):
            log.error(
                "the stored %r/%r dialect disagrees with existing unit groups "
                "for %s; the existing groups remain authoritative",
                key[0], key[1], ", ".join(sorted(conflicts)[:8]))

    def _as_the_place_says(self, data: dict[str, Any], name: str,
                           decisions: dict[str, str]) -> dict[str, Any]:
        """How this place uses one member's readings.

        Role, channel and indoor are properties of the place/station
        relationship. The same console can therefore be main in one archive
        and extra in another. Explicit placement targets outrank the preset:
        a person who names a column has settled the collision themselves.

        A `main` member with `indoor` left on passes through untouched.
        """
        if self.archive_definition is None:
            return data
        policy = self.archive_definition.policy_for(name)
        targets = {target for target in decisions.values() if target != NOWHERE}
        protected = {obs: value for obs, value in data.items() if obs in targets}
        ordinary = {obs: value for obs, value in data.items() if obs not in targets}
        if not policy.indoor:
            # A console in a living room measures a living room; one in a
            # shed on the same station measures a shed, and only one of them
            # is worth a column.
            dropped = {obs: value for obs, value in ordinary.items()
                       if obs not in ("inTemp", "inHumidity", "inDewpoint")}
            ordinary = dropped
        if policy.role != roles.MAIN:
            # Out of the main station's way. Both sending `outTemp` would
            # otherwise take turns writing it every few seconds, and the
            # column would hold a mixture nothing afterwards can separate.
            ordinary = roles.apply(ordinary, policy.role, policy.channel, name)
        return {**ordinary, **protected}

    def _cannot_place(self, driver: str, dialect: str) -> None:
        """Say once that a vocabulary reached here with nothing to translate it.

        A packet naming a dialect without a valid mapping is an old row or a
        damaged one. Its raw readings remain intact, but this archive cannot
        safely guess their units or names and will not load the driver to ask.
        """
        key = (_safe_name(driver), _safe_name(dialect))
        if not _first(_untranslatable, key):
            return
        log.error(
            "packets from %r arrive as %r without a valid stored mapping. "
            "Their raw readings remain in the live journal, but this archive "
            "will not load the driver or guess how to interpret them.", *key)

    def _for(self, name: str, dialect: str) -> tuple[dict[str, str], str]:
        key = (name, dialect)
        found = self._decisions.get(key)
        if found is None:
            found = (self.placements.extensions(self.archive, name, dialect),
                     self.placements.unlisted(self.archive, name, dialect))
            self._decisions[key] = found
        return found

    def _only_listed(self, data: dict[str, Any], decisions: dict[str, str],
                     station: str) -> dict[str, Any]:
        """What an extra station may write: what it was told, and its own housekeeping.

        Default-deny, because the alternative is a sensor added next year
        landing in the main station's column with nobody watching. Battery
        levels and signal strengths come through regardless: those names
        already carry their sensor, so two stations cannot collide on them,
        and dropping them would leave an extra station whose battery nobody
        can see.
        """
        wanted = {column for column in decisions.values() if column != NOWHERE}
        kept, lost = {}, []
        for obs, value in data.items():
            if obs in wanted or roles.keeps(obs):
                kept[obs] = value
            else:
                lost.append(obs)
        for obs in lost:
            self._dropped[obs] = self._dropped.get(obs, 0) + 1
        said_station = _safe_name(station)
        if lost and _first(_said, said_station):
            log.info(
                "%s writes only what it has been placed, so its %s %s nowhere to go in "
                "%r. The readings are in the live table either way: give one a column "
                "on the settings page and a rebuild will fill it in.",
                said_station, ", ".join(sorted(lost)[:6]),
                "has" if len(lost) == 1 else "have", self.archive)
        return kept

    # -- housekeeping ----------------------------------------------------

    def replace(self, placements: Placements | None = None,
                stations: Any = None, archive: Any = None,
                directory: Any = None) -> None:
        """Take up a changed file.

        Both halves and the cache go together. A caller that swapped the
        placements and kept the merged copies would get a placer that reports
        the new file and applies the old one.
        """
        if placements is not None:
            self.placements = placements
        replacement = directory if directory is not None else stations
        if replacement is not None:
            self.directory = replacement
            self._read_directory()
        if archive is not None:
            self.archive_definition = archive if hasattr(archive, "policy_for") else None
            self.archive = str(getattr(archive, "name", archive))
        self._decisions = {}

    def dropped(self) -> dict[str, int]:
        """Readings this archive had nowhere to put, by name and count."""
        return dict(self._dropped)


def promote(proposals: Any, placements: Placements, archive: str = "",
            mode: str = "series") -> list[tuple[str, str]]:
    """Write down what inference has worked out. Returns what it added.

    This is the whole of the migration from a guess to a decision. Before it,
    `tf_ch9 -> soilTemp9` happened inside a `Mapper` in one process, was
    re-derived on every start, and nothing recorded that it had happened at
    all -- so nobody could disagree with it and no second process could see
    it. Afterwards it is a line with `learned = true` on it.

    Args:
        proposals (weewx_evo.ingest.proposals.Proposals): What has turned up
            and what the driver made of it.
        placements (Placements): Written into, in place. The caller saves.
        archive (str): Which series to write the scopes for. Required even
            when the installation has one place.
        mode (str): The installation's `infer_unknown`.

            off     nothing is promoted. The page still lists every unplaced
                    name, because they are all in the journal -- with no
                    suggestion beside them.
            series  a guess the driver calls certain. This is exactly what
                    used to happen silently on every packet.
            all     anything the driver could name at all.

    Returns:
        list[tuple[str, str]]: The (raw, column) pairs written, so a caller
        can say what it did rather than "saved".

    A learned line never overwrites a chosen one -- `Placements.decide`
    refuses that -- so running this after somebody has overruled a guess
    leaves the overrule alone.
    """
    if not archive:
        raise ValueError("promoted placements must name their archive")
    if mode == "off":
        return []
    written = []
    for one in proposals.all():
        if not one.field or one.field == NOWHERE:
            continue
        if mode == "series" and not one.certain:
            continue
        before = placements.extensions(archive, one.station, one.dialect)
        if one.raw in before:
            continue
        placements.decide(archive, one.station, one.dialect, one.raw,
                          one.field, learned=True)
        if one.group:
            placements.groups.setdefault(one.field, one.group)
        written.append((one.raw, one.field))
    return written


def name_for(stations: Any, driver: str, identity: str) -> str:
    """What to call a console, for anything that has no `Placer`.

    The table records the pair; a name is a lookup, and several queries only
    need the lookup. Same answer as `Placer.named`, which calls this -- a
    second version of the fallback would be two pages disagreeing about what
    an unannounced console is called.
    """
    if stations is not None and hasattr(stations, "senders"):
        canonical = sender_id(driver, identity)
        entry = next((one for one in stations.senders()
                      if one.sender == canonical), None)
        if entry is not None and entry.label:
            return entry.label
        return canonical
    station = (stations.by_identity(driver, identity)
               if stations is not None else None)
    if station is not None:
        return station.name
    return sender_id(driver, identity)


def _renamed(data: dict[str, Any], decisions: dict[str, str]) -> dict[str, Any]:
    """Readings that are already WeeWX-named, moved where the placements say.

    This is the whole of `indoor = false` and of an extra station's shift,
    expressed as data: `inTemp = "-"` and `outTemp = "extraTemp3"`. A driver
    somebody else wrote gets both without knowing they exist, which is what
    the old arrangement in the listener also achieved -- the difference is
    that here it is reversible.
    """
    if not decisions:
        return data
    out = {}
    for obs, value in data.items():
        where = decisions.get(obs, obs)
        if where == NOWHERE:
            continue
        out[where] = value
    return out


def _mapped(data: dict[str, Any], raw_spec: object,
            decisions: dict[str, str], packet_units: object
            ) -> tuple[dict[str, Any], int, dict[str, str]] | None:
    """Execute one stored dialect description using core code only.

    `DialectSpec.from_dict` is deliberately strict. The live database is a
    boundary between processes and can be edited independently; accepting an
    unknown version or shape would make a plausible record with semantics the
    running code does not understand.
    """
    from .ingest.drivers import DialectSpec

    try:
        spec = DialectSpec.from_dict(raw_spec)
        if type(packet_units) is not int or packet_units != spec.usUnits:
            return None
    except (TypeError, ValueError, OverflowError):
        return None

    fields = dict(spec.fields)
    fields.update(decisions)
    contested = set(spec.contested) - set(decisions)
    record: dict[str, Any] = {}
    for raw, value in data.items():
        if raw in spec.metadata:
            continue
        if isinstance(value, str) and value.strip() in spec.absent:
            value = None
        elif value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(value):
                continue
        if raw in contested:
            continue
        target = fields.get(raw)
        if target is None or target == NOWHERE:
            continue
        factor = spec.scale.get(raw)
        if factor is not None and value is not None:
            value *= factor
        record[target] = value
    # A catalog may describe fields not present in this upload. Do not let
    # those declarations mutate process-wide units until the field itself has
    # arrived and been mapped.
    groups = {field: group for field, group in spec.groups.items()
              if field in record}
    return record, spec.usUnits, groups


#: Which stations have already been told that they write only what they were
#: given. Once per station for the life of the process rather than six times a
#: minute, the same as `roles.apply` did before it.
_said: set[str] = set()

#: And which (driver, dialect) pairs have been reported as having nothing to
#: translate them. A second set rather than a second kind of key in the first:
#: a station named `ecowitt` would otherwise silence a real misconfiguration.
_untranslatable: set[tuple[str, str]] = set()
_group_conflicts: set[tuple[str, str]] = set()


def _safe_name(value: object) -> str:
    """A bounded printable label for a driver-controlled diagnostic."""
    text = str(value)
    clean = "".join(character if character.isprintable() else "?"
                    for character in text)
    return clean[:128] or "<empty>"


def _first(seen: set, key: object) -> bool:
    if key in seen or len(seen) >= MAX_DIAGNOSTICS:
        return False
    seen.add(key)
    return True


# -- the file ------------------------------------------------------------

def path_for(directory: str | Path) -> Path:
    return Path(directory) / FILENAME


def load(path: str | Path) -> Placements:
    """Read placement.toml. A missing file is an installation with none yet."""
    import tomllib

    path = Path(path)
    if not path.exists():
        return Placements(path=path)
    with open(path, "rb") as fp:
        raw = tomllib.load(fp)
    made = from_dict(raw, path=path)
    made.stamp = hash(path.read_bytes())
    return made


def from_dict(raw: dict[str, Any], path: Path | None = None) -> Placements:
    made: list[Takes] = []
    unbound = 0
    for entry in raw.get("takes") or []:
        if not isinstance(entry, dict):
            log.warning("a [[takes]] entry is not a section; ignoring it")
            continue
        unlisted = str(entry.get("unlisted") or CATALOG)
        if unlisted not in UNLISTED:
            # Reported rather than corrected: read as `catalog` a mistyped
            # `nowere` would let an extra station write over the main one's
            # columns, which is the thing it was typed to prevent.
            log.warning("unlisted = %r is not one of %s; taking it as %r",
                        unlisted, ", ".join(UNLISTED), NOWHERE_ELSE)
            unlisted = NOWHERE_ELSE
        archive = str(entry.get("archive") or "")
        if not archive:
            unbound += 1
        made.append(Takes(
            archive=archive,
            station=str(entry.get("station") or ""),
            dialect=str(entry.get("dialect") or ""),
            learned=bool(entry.get("learned", False)),
            unlisted=unlisted,
            fields={str(k): str(v) for k, v in (entry.get("fields") or {}).items()},
        ))
    if unbound:
        log.warning(
            "%s has %d placement scope(s) that name no archive; each of them "
            "reaches nothing. Add `archive = \"<place>\"` to the block.",
            path or FILENAME, unbound)
    groups = {str(k): str(v) for k, v in (raw.get("groups") or {}).items()}
    return Placements(takes=made, groups=groups, path=path)


def save(path: str | Path, placements: Placements, note: str = "") -> Path:
    """Write placement.toml, keeping the previous one.

    Written beside and moved into place, like `stations.toml` and
    `plots.toml`: an interrupted write here would leave an archive taking
    half its readings, and the half would be whichever the file got to.
    """
    import shutil
    import tomllib

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render(placements, note)

    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(text, encoding="utf-8")
    with open(partial, "rb") as fp:
        tomllib.load(fp)  # what was written, not what we meant to write
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    partial.replace(path)
    return path


def render(placements: Placements, note: str = "") -> str:
    """The placements as a TOML file somebody can edit."""
    out = [
        "# Where each reading a console sends is written.",
        "#",
        "# One [[takes]] per scope. `archive` is the series it is for. Leave",
        "# `station` out and it holds for every console of that archive --",
        "# including one nobody has announced yet, which is the only place",
        "# such a decision can be written down at all. `dialect` narrows it to",
        "# one catalog: a Weather Underground console speaks two, and `tempf`",
        "# and `outtemp` are not the same reading.",
        "#",
        f'# The narrowest scope wins, field by field. "{NOWHERE}" writes it nowhere.',
        "# `learned = true` was worked out from the field name and is rewritten",
        "# when a better answer turns up; anything without it is yours and is",
        "# left alone.",
        "#",
        "# Nothing here can lose a measurement. The readings are in the live",
        "# table under the names the console sent, so a line changed today and",
        "# a rebuild put yesterday's readings where you meant them.",
    ]
    if note:
        out += ["#", *[f"# {line}" for line in note.splitlines()]]
    out.append("")

    for one in sorted(placements.takes,
                      key=lambda t: (t.archive, t.station, t.dialect, t.learned)):
        out.append("[[takes]]")
        for label, value in (("archive", one.archive), ("station", one.station),
                             ("dialect", one.dialect)):
            if value:
                out.append(f'{label} = "{_escape(value)}"')
        if one.learned:
            out.append("learned = true")
        if one.unlisted != CATALOG:
            out.append(f'unlisted = "{_escape(one.unlisted)}"')
        if one.fields:
            out.append("")
            out.append("[takes.fields]")
            for their, ours in sorted(one.fields.items()):
                out.append(f'"{_escape(their)}" = "{_escape(ours)}"')
        out.append("")

    if placements.groups:
        out += [
            "# What those columns measure, where neither the core schema nor the",
            "# driver already says. Without a group a page prints a bare number",
            "# beside readings it has converted.",
            "[groups]",
        ]
        for column, group in sorted(placements.groups.items()):
            out.append(f'"{_escape(column)}" = "{_escape(group)}"')
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')

"""Consoles that turned up and have not been announced.

The other half of `stations.py`, and the half that is observed rather than
decided. A station in `stations.toml` is a decision somebody made; a sighting
is a thing that happened, it changes every few seconds, and it goes stale. So
it lives in the live database instead of in a file.

**It catches more than the obvious.** The list is not just for hardware that
announces itself. It also holds:

  * a device reached by pointing DNS at us, which has no server field to type
    anything into,
  * a console whose identity has a typo in it,
  * a second Ecowitt that would be adopted silently today.

In every one of those the operator needs the same thing: *something is here
and does not belong yet*. Today all three vanish -- a wrong PASSKEY is
refused, a wrong ID becomes a second source and gets averaged into the first,
an unrecognised upload falls through to the default driver. None of it is
visible anywhere.

**Ignoring is not a decision, it is a fold.** An ignored sighting stays
adoptable; it just stops taking up room. What removes it is time: anything not
seen for `FORGET_AFTER` is dropped, so a neighbour's console that appeared
once does not sit in the list for ever.

Written back rarely on purpose. A console uploads every sixteen seconds and
this would otherwise be a database write and a JSON round trip each time, for
a number nobody is reading. Changes are held and flushed on the first sighting
of something new, every `FLUSH_AFTER` seconds otherwise, and on shutdown.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field

log = logging.getLogger(__name__)

#: Where the list sits in the live database's metadata.
METADATA_KEY = "sightings"

#: Not seen for this long, and it is forgotten. Long enough that a console
#: taken indoors for a fortnight is still in the list when it comes back,
#: short enough that a stranger seen once does not stay for ever.
FORGET_AFTER = 14 * 86400

#: How long changes are held before being written back.
FLUSH_AFTER = 60.0

#: A cap, so a misconfigured device that varies its identity every upload
#: cannot grow this without limit. The oldest go first.
MAX_SIGHTINGS = 200


@dataclass
class Sighting:
    """Something that uploaded and is not a station."""

    driver: str
    identity: str
    #: Where it uploaded from. The only identification some hardware offers,
    #: and it moves with DHCP, so it is shown rather than relied on.
    peer: str = ""
    first_seen: int = 0
    last_seen: int = 0
    packets: int = 0
    #: Folded away. Still adoptable, still subject to the same expiry.
    ignored: bool = False
    #: A few field names from what it sent, so the page can say what it is
    #: without anybody having to read a raw upload.
    fields: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.driver, self.identity.casefold())


class Sightings:
    """The list, kept in the live database.

    Held in memory and written back rarely. The store is passed in rather than
    opened here for the same reason the drivers get `state` and not a
    connection: this has no business reaching the archive.
    """

    def __init__(self, store: object | None = None,
                 forget_after: int = FORGET_AFTER) -> None:
        self.store = store
        self.forget_after = forget_after
        self.seen: dict[tuple[str, str], Sighting] = {}
        self._dirty = False
        self._flushed = 0.0
        self.load()

    # -- reading and writing -------------------------------------------

    def load(self) -> None:
        if self.store is None:
            return
        try:
            raw = self.store.get_meta(METADATA_KEY)
        except Exception:
            log.debug("could not read the sightings", exc_info=True)
            return
        if not raw:
            return
        try:
            found = json.loads(raw)
        except ValueError:
            log.warning("the stored sightings are not readable; starting over")
            return
        for entry in found if isinstance(found, list) else []:
            try:
                one = Sighting(**entry)
            except TypeError:
                # Written by a newer version with a field this one has never
                # heard of. Skipped rather than fatal: it is a list of things
                # that turned up, and losing one costs a line on a page.
                continue
            self.seen[one.key] = one

    def flush(self, force: bool = False) -> None:
        """Write the list back, if there is anything to write."""
        if self.store is None or not self._dirty:
            return
        now = time.time()
        if not force and now - self._flushed < FLUSH_AFTER:
            return
        try:
            self.store.set_meta(METADATA_KEY, json.dumps(
                [asdict(one) for one in self.seen.values()]))
        except Exception:
            # A sighting that cannot be recorded must not stop the reading
            # that was being recorded when it happened.
            log.debug("could not store the sightings", exc_info=True)
            return
        self._dirty = False
        self._flushed = now

    # -- what the listener does ----------------------------------------

    def saw(self, driver: str, identity: str, peer: str = "",
            fields: list[str] | None = None, when: float | None = None) -> Sighting:
        """Note that something uploaded. Returns the sighting.

        Called for uploads that did not match an announced station. The
        identity may be empty for hardware that offers none; those are kept
        under the peer address, which is all there is.
        """
        now = int(when or time.time())
        identity = (identity or "").strip()
        key = (driver, identity.casefold())

        one = self.seen.get(key)
        first = one is None
        if first:
            one = Sighting(driver=driver, identity=identity, peer=peer,
                           first_seen=now, fields=list(fields or [])[:12])
            self.seen[key] = one
        one.last_seen = now
        one.packets += 1
        if peer:
            one.peer = peer
        if fields and not one.fields:
            one.fields = list(fields)[:12]
        self._dirty = True

        # Filled in first, written afterwards. The other order stored a
        # sighting with `last_seen = 0`, because the forced write happened
        # before the counters were set and the next write was rate limited a
        # minute away. A restart inside that minute read a sighting last seen
        # in 1970, and the next expiry dropped it.
        if first:
            log.info("a %s upload from %s carries %s, which is not a station "
                     "here. It is on the settings page to be adopted or "
                     "ignored.", driver, peer or "?", identity or "no identity")
            self.flush(force=True)   # something new is worth a write at once
        else:
            self.flush()
        return one

    # -- what the page does --------------------------------------------

    def waiting(self) -> list[Sighting]:
        """Seen and not folded away, most recent first."""
        return sorted((one for one in self.seen.values() if not one.ignored),
                      key=lambda s: s.last_seen, reverse=True)

    def ignored(self) -> list[Sighting]:
        return sorted((one for one in self.seen.values() if one.ignored),
                      key=lambda s: s.last_seen, reverse=True)

    def find(self, driver: str, identity: str) -> Sighting | None:
        return self.seen.get((driver, (identity or "").casefold()))

    def ignore(self, driver: str, identity: str, ignored: bool = True) -> bool:
        one = self.find(driver, identity)
        if one is None:
            return False
        one.ignored = ignored
        self._dirty = True
        self.flush(force=True)
        return True

    def forget(self, driver: str, identity: str) -> bool:
        """Drop one outright. Adopting is the other way it leaves the list."""
        if self.seen.pop((driver, (identity or "").casefold()), None) is None:
            return False
        self._dirty = True
        self.flush(force=True)
        return True

    def expire(self, now: float | None = None) -> int:
        """Drop what has not been seen for a while. Returns how many went.

        Ignored and waiting alike: an entry nobody has adopted in a fortnight
        and nothing has sent since is not a decision anybody is still putting
        off.
        """
        now = now or time.time()
        going = [key for key, one in self.seen.items()
                 if now - one.last_seen > self.forget_after]
        # And a cap, oldest first, for a device that varies its identity.
        if len(self.seen) - len(going) > MAX_SIGHTINGS:
            rest = sorted((one for key, one in self.seen.items()
                           if key not in going),
                          key=lambda s: s.last_seen)
            over = len(rest) - MAX_SIGHTINGS
            going.extend(one.key for one in rest[:over])
        for key in going:
            self.seen.pop(key, None)
        if going:
            self._dirty = True
            self.flush(force=True)
            log.info("forgot %d sighting(s) not seen for %d days",
                     len(going), self.forget_after // 86400)
        return len(going)

    def close(self) -> None:
        self.flush(force=True)

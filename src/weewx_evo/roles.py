"""Which sender a place takes its readings from, when it selects several.

One sender needs none of this. It is the place's sender, its readings go to
the columns they belong in, and nothing here does anything. That case has to
stay exactly as simple as it was, so everything below only comes into play
once a place selects a second one.

With two, the question is unavoidable: they both send `outTemp`, and there is
one `outTemp`. Left alone they take turns writing it every few seconds, and
the column ends up holding a mixture that nothing afterwards can separate --
the same failure contested fields and explicit placement both exist to
prevent, arriving from a different direction.

## One place, one primary

A place names the sender its series comes from. That sender is placed by the
catalog, exactly as a single console always was: `outTemp` is `outTemp`.

Every other sender the place selects writes **only what somebody has placed
by hand** (`placement.toml`, the Fields page). Not because its readings are
worth less, but because there is nothing to derive: a second sender may be a
second full weather station ten metres away, a soil probe, a lightning
detector or a gateway with one thermometer on it, and which of those it is
cannot be read off the protocol. The catalog knows the protocol, not the
garden.

So a place cannot have two primaries. It is not a warning and not a check --
`Archive.primary` holds one sender ID, and two of them is not a thing the
model can express.

## What the preset here used to do, and why it is gone

Until this version an additional sender had a channel, and its `outTemp`,
`outHumidity` and `dewpoint` were moved to `extraTemp<n>`, `extraHumid<n>`
and `extraDewpoint<n>` on the way into the record. Everything else it sent
was dropped. Two things were wrong with that, and both were silent:

  * **The guess was carried out rather than offered.** Whoever plugged in the
    second sender found three columns filled and the rest of its readings
    gone, with one log line to say so. Now the readings sit in the live
    journal until somebody places them, and placing them and rebuilding
    brings the whole retention period with it.
  * **One of the three targets does not exist.** The standard schema has
    `extraTemp1..8` and `extraHumid1..8` and no `extraDewpoint` at all, so
    every moved dew point went straight to `_note_homeless` and was dropped.
    The comment above the table said "only the two that have somewhere to
    go" and listed three.

The channel went with it. It numbered that preset and nothing else; what the
Fields page offers instead is worked out from the columns the archive
actually has free, which is a measurement rather than a stored intention.

## Where this sits

On the read side, in `placement.Placer`, after the dialect mapping. The
listener stores what the sender said under the sender's own names. When the
archiver builds a record, the place maps it to archive columns and the role
decides whether anything it did not name may come through. Change the role,
run `rebuild`, and the archive follows -- which is the whole reason the
decision is here and not at the door.
"""

from __future__ import annotations

MAIN = "main"
EXTRA = "extra"
ROLES = (MAIN, EXTRA)

#: What an additional sender writes regardless of anything placed by hand.
#:
#: Its own housekeeping: battery levels and signal strengths already carry
#: their sensor in the name, so two senders cannot collide on them, and
#: dropping them would leave an extra sender whose battery nobody can see.
KEEPS = ("Batt", "batt", "_rssi", "_sig", "BatteryStatus")


def keeps(field: str) -> bool:
    """Whether an additional sender may write this column unplaced."""
    return any(field.endswith(one) for one in KEEPS)

"""When something on its own clock next runs.

Everything with an interval used to count from whenever it happened to
start: restart the service at 14:23 and the five-minute export ran at 14:28,
14:33, 14:38. Restart it again and the times moved again. Two installations
of the same thing never agreed, a chart written every ten minutes carried
timestamps nobody could line up against the archive records beside it, and
"why is it always a couple of minutes late" had no answer because it was not
late -- it was on its own clock.

So the slots are pinned to the hour. Five minutes means :00, :05, :10 and so
on, ten minutes means :00, :10, :20, and an hour means the hour. Whatever the
service was doing at 14:23 has no bearing on it.

**The local hour**, not the epoch. `now // every` is one line and gives the
same answer wherever the offset is a whole number of hours -- but in India,
Nepal or the Chatham Islands the epoch is half an hour or three quarters out
of step with the clock on the wall, and a two-hourly report would land at
odd-numbered half hours. The hour somebody can see is the one to line up
with.

**An interval that does not divide the hour** gets a short slot rather than
drifting. At seven minutes: :00, :07, :14 … :56, and then the hour, which is
four minutes later rather than seven. Drifting would put it on a different
minute every hour, which is the thing this exists to stop.
"""

from __future__ import annotations

import time

HOUR = 3600.0


def into_hour(now: float) -> float:
    """How far into the local hour a moment is, in seconds."""
    local = time.localtime(now)
    return local.tm_min * 60.0 + local.tm_sec + (now - int(now))


def next_slot(now: float, every: float) -> float:
    """The next time on the grid `every` makes, counted from the hour.

    Always in the future, never `now` itself: a caller asking at exactly
    14:05:00 has just run, and wants the next one.
    """
    if every <= 0:
        return now
    every = float(every)
    into = into_hour(now)
    started = now - into
    if every >= HOUR:
        # Longer than an hour: the grid is the hour it falls in, so this is
        # the next whole hour rather than a slot inside one.
        return started + HOUR * max(1.0, round(every / HOUR))
    slot = started + (int(into // every) + 1) * every
    # The last slot of an hour is short where the interval does not divide
    # it. Better than carrying the remainder into the next hour and landing
    # on a different minute every time.
    return min(slot, started + HOUR)


def wait_for(now: float, until: float, cap: float = 30.0) -> float:
    """How long to sleep, in the sizes a loop that must also stop can use.

    Capped, because the thread waiting on this is also waiting to be told to
    stop, and a service that takes ten minutes to shut down is one that gets
    killed instead. The last wait before a slot is the exact one, so the run
    lands on the second rather than up to `cap` after it.
    """
    left = until - now
    if left <= 0:
        return 0.0
    return min(cap, left)

#!/usr/bin/env python3
"""Anything on its own clock runs on the hour's grid.

Five minutes means :00, :05, :10, whatever time the service happened to
start. Before this, a restart at 14:23 moved a five-minute export to 14:28,
14:33, 14:38 -- and the next restart moved it again. Two installations of the
same thing never agreed, and a chart written every ten minutes carried
timestamps nobody could line up against the archive records beside it.

    python tools/schedule_test.py
"""

from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import schedule  # noqa: E402

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def at(hour: int, minute: int, second: int = 0) -> float:
    """A local moment, whatever zone this machine is in."""
    return time.mktime((2026, 8, 28, hour, minute, second, 0, 0, -1))


def clock(when: float) -> str:
    return datetime.datetime.fromtimestamp(when).strftime("%H:%M:%S")


def series(start: float, every: float, how_many: int = 5) -> list[str]:
    out, when = [], start
    for _ in range(how_many):
        when = schedule.next_slot(when, every)
        out.append(clock(when))
    return out


def the_ordinary_intervals() -> None:
    print("\nthe grid, from an awkward moment")
    start = at(14, 23, 17)
    check("five minutes", series(start, 300),
          ["14:25:00", "14:30:00", "14:35:00", "14:40:00", "14:45:00"])
    check("ten minutes", series(start, 600),
          ["14:30:00", "14:40:00", "14:50:00", "15:00:00", "15:10:00"])
    check("a quarter of an hour", series(start, 900),
          ["14:30:00", "14:45:00", "15:00:00", "15:15:00", "15:30:00"])
    check("an hour", series(start, 3600),
          ["15:00:00", "16:00:00", "17:00:00", "18:00:00", "19:00:00"])


def it_does_not_depend_on_when_the_service_started() -> None:
    """The whole point. Two starts, one timetable."""
    print("\nwhen the service came up makes no difference")
    from_one = series(at(14, 23, 17), 300, 3)
    from_other = series(at(14, 2, 44), 300, 3)[2:]
    check("a restart does not move the slots", from_one[0], "14:25:00")
    check("and the other start lands on the same grid", from_other,
          ["14:15:00"])

    # Asked at exactly a slot, the answer is the next one: the caller has
    # just run.
    check("on the second, the answer is the next slot",
          clock(schedule.next_slot(at(14, 5, 0), 300)), "14:10:00")


def one_that_does_not_divide_the_hour() -> None:
    """A short slot, rather than a different minute every hour."""
    print("\nseven minutes, which the hour does not hold a whole number of")
    check("it starts from the hour", series(at(14, 0, 30), 420, 9),
          ["14:07:00", "14:14:00", "14:21:00", "14:28:00", "14:35:00",
           "14:42:00", "14:49:00", "14:56:00", "15:00:00"])
    check("and the next hour starts over",
          clock(schedule.next_slot(at(15, 0, 0), 420)), "15:07:00")


def the_awkward_values() -> None:
    print("\nvalues that could divide by zero or run away")
    now = at(14, 23, 17)
    check("zero is not a schedule", schedule.next_slot(now, 0), now)
    check("nor is a negative one", schedule.next_slot(now, -60), now)
    check("a second still lands on the second",
          clock(schedule.next_slot(at(14, 23, 17), 1)), "14:23:18")
    # Longer than an hour rounds to whole hours, so a two-hourly report is
    # on an even hour rather than two hours after the service started.
    check("two hours is a whole hour",
          clock(schedule.next_slot(at(14, 23, 17), 7200)), "16:00:00")


def the_wait_is_bounded() -> None:
    """A loop waiting on this also has to notice a stop."""
    print("\nhow long a loop waits for a slot")
    now = at(14, 23, 17)
    check("a long way off, it waits the cap",
          schedule.wait_for(now, now + 600), 30.0)
    check("close to, it waits exactly that",
          schedule.wait_for(now, now + 4.5), 4.5)
    check("past it, not at all", schedule.wait_for(now, now - 5), 0.0)


def the_runners_use_it() -> None:
    """All four of them, so none drifts off on its own clock."""
    print("\nevery runner with an interval is on the grid")
    from weewx_evo.exports import runner as export_runner
    from weewx_evo.forecast import runner as forecast_runner
    from weewx_evo.uploads import runner as upload_runner

    for module in (export_runner, upload_runner, forecast_runner):
        source = Path(module.__file__).read_text(encoding="utf-8")
        name = module.__name__.split(".")[-2]
        check(f"{name} asks the schedule", "schedule.next_slot" in source,
              True)
        check(f"{name} does not count from its own start",
              "now - self.last >= self.every" in source, False)

    from weewx_evo import feedrunner

    check("and so do the feeds",
          "schedule.next_slot" in Path(
              feedrunner.__file__).read_text(encoding="utf-8"), True)


def main() -> int:
    the_ordinary_intervals()
    it_does_not_depend_on_when_the_service_started()
    one_that_does_not_divide_the_hour()
    the_awkward_values()
    the_wait_is_bounded()
    the_runners_use_it()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("everything on a clock runs on the hour's grid")
    return 0


if __name__ == "__main__":
    sys.exit(main())

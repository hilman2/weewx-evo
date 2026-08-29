"""The thread that looks, decides and sends.

One thread for every channel, not one each. There are two or three of them,
they are idle almost always, and the work is a handful of queries against a
database that is already open. What one channel must not do is hold up
another -- so a channel that hangs is given a deadline and the rest carry on.

**It looks before it is asked to.** The runner owns the schedule rather than
being woken by the archiver, because the symptom this exists for is the
archiver having stopped. A check that runs when a record is written cannot
report that no record was written.

**And it says nothing for the first few minutes.** A process that has just
started has an empty picture of the world: the watchdog has no heartbeat yet
and the export runners have not had a turn. Sending during that window means
every restart produces a burst of alarms that clear themselves a minute
later, which is the fastest way to teach somebody to ignore these messages.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from . import Memory, Standing, Timing, decide
from . import rules as rules_module

log = logging.getLogger(__name__)

#: How often it looks. A minute is often enough for an alert measured in
#: tens of minutes, and cheap: four queries against an open database.
EVERY = 60.0

#: And how long after starting before it will send anything. See the module
#: docstring: a fresh process does not yet know what is true.
SETTLE = 300.0


@dataclass
class Channel:
    """One configured channel, with its own timing."""

    name: str
    channel: Any
    timing: Timing


class Runner:
    """Watches for symptoms and tells the channels about them."""

    def __init__(self, channels: list[Channel], live: Any = None,
                 stations: Any = None, dog: Any = None,
                 senders: Any = None, station_name: str = "",
                 floor: float = 900.0, every: float = EVERY,
                 settle: float = SETTLE) -> None:
        self.channels = channels
        self.live = live
        self.stations = stations
        self.dog = dog
        self.senders = list(senders or [])
        self.station_name = station_name
        self.floor = float(floor)
        self.every = float(every)
        self.settle = float(settle)

        self.memory = Memory(live)
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0
        #: What the last pass found, for the settings page.
        self.standing: dict[str, Any] = {}

    def replace(self, channels: list[Channel]) -> None:
        """Swap in a new set after the configuration changed.

        A method rather than assignments at the call site, for the reason
        written down at `exports/runner.replace`: the stop flag and the
        thread go with the list, and a caller that remembers two of the three
        gets a runner whose thread never wakes.
        """
        self.stop()
        self.channels = channels
        self.start()

    # -- the loop ---------------------------------------------------------

    def start(self) -> threading.Thread | None:
        if not self.channels:
            return None
        self._stopping.clear()
        self._started = time.time()
        self._thread = threading.Thread(target=self._loop, name="notify",
                                        daemon=True)
        self._thread.start()
        log.info("notifications: watching, %d channel(s)", len(self.channels))
        return self._thread

    def stop(self) -> None:
        self._stopping.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                self.once()
            except Exception:
                # A notification thread that dies is a station with no alarm
                # and nothing saying so. The watchdog would notice it dead;
                # carrying on is better than being noticed.
                log.exception("the notification pass failed; carrying on")
            self._stopping.wait(self.every)

    def once(self, now: float | None = None) -> list:
        """One pass: look, decide, send. Returns what was sent."""
        now = time.time() if now is None else now
        seen = rules_module.everything(
            self.live, self.stations, self.dog, self.senders, self.floor, now)
        self.standing = dict(seen)

        if now - self._started < self.settle:
            # Noticed, remembered, not sent. The state is still updated so
            # that a symptom which was already true when the process started
            # is dated from when it started being true rather than from the
            # end of the settling period.
            for key, event in seen.items():
                if key not in self.memory.standing:
                    self.memory.standing[key] = Standing(
                        since=event.since or now)
            return []

        events = decide(seen, self.memory, self._timing(), now)
        self.memory.save()
        for event in events:
            self._tell(event)
        return events

    def _timing(self) -> Timing:
        """The shortest wait any channel asked for, and the longest repeat.

        One decision for all of them, because the state is one row. Taking the
        shortest means a channel configured to speak up quickly does, and a
        channel configured to wait then hears about it at the same time --
        which is what somebody who set two channels up wanted.
        """
        after = min((one.timing.after for one in self.channels), default=1800)
        repeat = max((one.timing.repeat for one in self.channels), default=86400)
        return Timing(after=after, repeat=repeat)

    def _tell(self, event: Any) -> None:
        for one in self.channels:
            try:
                one.channel.send(event, self.station_name)
                log.info("notified %s: %s", one.name,
                         event.subject_line(self.station_name))
            except Exception as exc:
                # Said at warning and not raised. One channel refusing must
                # not stop the others: the whole reason for having two is
                # that one of them may be the thing that is broken.
                log.warning("could not notify %s: %s", one.name, exc)

    def close(self) -> None:
        for one in self.channels:
            closing = getattr(one.channel, "close", None)
            if closing is not None:
                try:
                    closing()
                except Exception:
                    log.debug("could not close %s", one.name, exc_info=True)

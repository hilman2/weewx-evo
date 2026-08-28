"""Noticing that this process is no longer well, and standing aside.

A long-running program accumulates. A descriptor that is never given back, a
thread that died inside an exception nothing caught, a loop that stopped
going round. None of these announce themselves: what arrives in the log is
whatever needed a resource next and could not get it, which is somewhere
else entirely.

The one that built this: a connection to the live table was held for every
upload answered, so the process reached its 1024 descriptor limit after ten
hours. What the log showed was a feed failing to read `plots.toml`, then
another failing to list a directory, then the live upload failing to send.
Three errors in three subsystems, none of them near the leak, none of them
naming a database. The instance served a stale page for nine hours because
nothing was watching the one number that was wrong.

## What it does about it

Nothing clever: it lets the process stop, and the supervisor starts it
again. `restart: unless-stopped` in compose, `Restart=always` in a unit
file. Both are already there for the settings that cannot be applied to a
running process, so this is the same road with a different reason to take
it.

Restarting rather than repairing is the decision here. Closing the leaked
descriptors from inside would need to know which ones were leaked; a new
process gets that for free, along with whatever else had gone quietly wrong
beside it. The cost is a second of deafness, once.

## What it watches, and what it will not

Only what a fresh process actually fixes:

    descriptors   near the limit, which is a leak by definition
    threads       a runner whose thread has died never comes back
    heartbeat     the archiver loop stopped going round

Deliberately not watched: whether packets are arriving, whether an upload is
being accepted, whether a feed rendered. Those fail when somebody else's
equipment is off, and restarting into an outage is how a watchdog becomes
the outage. The rule is narrow on purpose -- a symptom that a restart does
not cure must not be able to cause one.

## Not more than once an hour

The count of the last restart goes in the live database, because it has to
survive the restart it is counting. An in-memory limit resets to zero in the
process that comes back, which is not a limit at all.

And if it cannot be written, nothing happens. A restart that cannot be
remembered is the first step of a loop, so the memory is taken first and the
restart only follows if it stuck.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

#: Where the time of the last self-restart is kept, in the live database's
#: meta table. It has to outlive the process to be worth anything.
MEMORY = "watchdog_last_restart"

#: How full the descriptor table has to be before this counts as a leak.
#: Well clear of a busy moment -- the instance that prompted this sits at
#: about 50 of 1024 -- and well below the point where the next open fails.
DESCRIPTOR_SHARE = 0.85

#: How often a pass runs. A constant rather than a setting: the number
#: nobody has a reason to choose, and one minute is far below the hours a
#: leak takes to matter.
EVERY = 60.0

#: How long the archiver loop may go without a tick. Its own poll is 5
#: seconds by default and a slow pass is well under one, so five minutes is
#: not "late", it is "stopped".
HEARTBEAT_SILENCE = 300.0


class Unwell(Exception):
    """What a check raises when a restart is the answer.

    The message is what goes in the log and it is the only explanation
    anybody gets, so it says the measurement, not the conclusion.
    """


def descriptors_open() -> int | None:
    """How many files this process has open, or None where nobody will say.

    `/proc` is Linux. That covers the container and every deployment this
    has, but not a development machine, and a check that cannot measure
    reports that rather than guessing a number.
    """
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None


def descriptor_limit() -> int | None:
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows
        return None
    soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft in (-1, resource.RLIM_INFINITY):
        return None
    return int(soft)


class Watchdog:
    """Watches from its own thread, because it cannot watch from inside.

    A check that runs in the loop it is checking is not a check: the case it
    exists for is the loop having stopped, and a stopped loop does not run
    anything, least of all its own alarm.
    """

    def __init__(self, live: Any, ask_to_restart: Callable[[str], None], *,
                 cooldown: float = 3600.0, every: float | None = None,
                 heartbeat: bool = True,
                 threads: Callable[[], dict[str, bool]] | None = None) -> None:
        self.live = live
        self.ask_to_restart = ask_to_restart
        self.cooldown = cooldown
        # Read at construction rather than defaulted in the signature, so
        # that changing the constant changes the behaviour. A default
        # argument is bound when the function is defined, which is before
        # anybody could have.
        self.every = EVERY if every is None else every
        #: Whether there is a loop here to watch at all. The listener has
        #: none -- it sits in serve_forever, and how long since it last did
        #: something is a fact about the console, not about this process.
        #: Left on there, a station switched off overnight would look like a
        #: stopped loop and get restarted into an outage every hour.
        self.heartbeat = heartbeat
        #: Named threads and whether each is still alive, asked fresh every
        #: pass. A callable rather than a list because the runners are built
        #: after this is, and one of them may not exist at all.
        self.threads = threads or dict
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None
        #: Last time the archiver loop went round. It sets this itself; the
        #: point is that a loop which has stopped stops setting it.
        self.beat = time.time()
        #: Counted for the status page, so an installation that restarts
        #: itself weekly is visible as that rather than as good luck.
        self.restarts = 0

    # -- the loop --------------------------------------------------------

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, daemon=True,
                                       name="watchdog")
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def beats(self) -> None:
        """Called by the loop being watched, every time round."""
        self.beat = time.time()

    def _loop(self) -> None:
        while not self.stopping.is_set():
            # The first pass waits, so a slow start is not a symptom. Threads
            # are being started while this one already runs.
            self.stopping.wait(self.every)
            if self.stopping.is_set():
                return
            try:
                self.check()
            except Exception:
                # A watchdog that takes the process down by failing is worse
                # than no watchdog. This is the one place where carrying on
                # regardless is right.
                log.exception("the watchdog's own pass failed; carrying on")

    # -- the checks ------------------------------------------------------

    def symptoms(self) -> list[str]:
        """Everything wrong right now that a new process would fix."""
        found = []
        for check in (self._descriptors, self._threads, self._heartbeat):
            try:
                check()
            except Unwell as why:
                found.append(str(why))
        return found

    def _descriptors(self) -> None:
        open_now, limit = descriptors_open(), descriptor_limit()
        if open_now is None or limit is None:
            return
        if open_now >= limit * DESCRIPTOR_SHARE:
            raise Unwell(f"{open_now} of {limit} file descriptors are open")

    def _threads(self) -> None:
        dead = sorted(name for name, alive in self.threads().items() if not alive)
        if dead:
            raise Unwell(f"the {', '.join(dead)} thread(s) have died")

    def _heartbeat(self) -> None:
        if not self.heartbeat:
            return
        silent = time.time() - self.beat
        if silent > HEARTBEAT_SILENCE:
            raise Unwell(f"the archiver loop has not gone round for {silent:.0f}s")

    # -- acting on them --------------------------------------------------

    def check(self) -> bool:
        """One pass. Returns True if it asked for a restart."""
        found = self.symptoms()
        if not found:
            return False
        why = "; ".join(found)

        since = time.time() - self.last_restart()
        if since < self.cooldown:
            # Said every pass on purpose. Something is wrong and the one
            # remedy is on hold, which is exactly when silence is worst.
            log.error("unwell: %s. Restarted %.0f min ago, so not again for "
                      "another %.0f min.", why, since / 60,
                      (self.cooldown - since) / 60)
            return False

        if not self.remember_restart():
            log.error("unwell: %s. Not restarting: the restart could not be "
                      "written down, and one that is not counted is the "
                      "first of a loop.", why)
            return False

        self.restarts += 1
        log.error("unwell: %s. Stopping so the supervisor starts a fresh "
                  "process.", why)
        self.ask_to_restart(why)
        return True

    # -- the memory ------------------------------------------------------

    def last_restart(self) -> float:
        try:
            written = self.live.get_meta(MEMORY)
        except Exception:
            # Unreadable counts as long ago rather than as never: the write
            # below is the guard, and it is about to be tried.
            return 0.0
        try:
            return float(written or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def remember_restart(self) -> bool:
        """Write the time down, and say whether it stuck.

        Read back rather than trusted. The failure this guards against is a
        database that has stopped accepting writes, and one that does so
        without raising is the version of that which loops.
        """
        now = time.time()
        try:
            self.live.set_meta(MEMORY, f"{now:.0f}")
            return abs(self.last_restart() - now) < 5
        except Exception:
            log.exception("could not write down the restart")
            return False


def threads_of(*runners: Any) -> Callable[[], dict[str, bool]]:
    """Name each runner's threads and whether they are alive.

    Takes the runners rather than their threads, because they are started
    after the watchdog is built, and a `None` runner is normal -- an
    installation with no feeds has no feed runner. The threads name
    themselves ("feeds", "upload-live", "export-json"), so what a dead one
    looks like in the log is the name somebody configured.
    """
    def alive() -> dict[str, bool]:
        found: dict[str, bool] = {}
        for runner in runners:
            if runner is None:
                continue
            # One runner has a single thread, the rest have one per
            # configured thing. Both are set in start(), so a thread that is
            # here has been started.
            one = getattr(runner, "thread", None)
            many = getattr(runner, "_threads", None) or []
            for thread in [one, *many]:
                if thread is not None:
                    found[thread.name] = thread.is_alive()
        return found
    return alive

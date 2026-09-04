"""Drivers that run in their own process, started and kept alive here.

The settings page printed a command and left it there: `weewx-evo-weewx-driver
run --collector shed`, copy it, open a terminal, type it. Which is right for a
driver on *another* machine -- there is no channel to it, and building one
would mean an agent over there, the same problem one floor down.

But the ordinary arrangement is one machine. weewx-evo on the Pi, the Vantage
on a USB-to-serial adapter of that same Pi. "Over there" is "here", and a
command to type is a step nobody should have to take.

**A button alone would be worse than the command.** A process somebody started
from a web page is gone after the next reboot, and then the station is quietly
silent -- exactly the failure `notify/` and the watchdog exist for. So this is
not a button that spawns something: it is a supervisor, and the driver comes
back up with weewx-evo, which systemd or Docker brings back.

**The isolation is untouched, and that is the point.** It is still a separate
process. A serial port that stops answering hangs the driver and nothing else;
the archiver keeps archiving, the listener keeps listening. That was the whole
reason for the split (`ingest/weewxshim.py`), and running the process from
here does not weaken it -- it only removes the terminal.

Four things this has to get right, each of them a way to be worse than the
command it replaces:

  * **A driver whose hardware is absent dies at once.** Without a backoff
    that is a loop that pins a core and fills the log. So: wait longer each
    time, capped, and stop trying after enough failures in a row -- the same
    shape as the watchdog's restart limit.
  * **"Died" on its own is useless.** `no module named 'serial'` is the
    answer, and it is on the process's stderr. The last lines are kept.
  * **The page is another process**, so the state goes through the live
    table, like `exports/record.py`. Nothing else connects the two.
  * **Stopping has to actually stop it.** A child still holding the serial
    port makes the next start fail with a message about the hardware.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import threading
import time
from collections import deque
from typing import Any, NamedTuple

log = logging.getLogger(__name__)

#: Where the state of each one is written, for the settings page to read.
#: One row per driver, replaced each time something happens to it.
KEY = "driver_process"


def key(name: str) -> str:
    """The metadata row for one driver."""
    return f"{KEY}:{name}"

#: How long to wait before starting one again, growing per failure in a row.
#: The first is short because the ordinary case is a driver that was stopped
#: on purpose and started again; the cap is a minute because a driver whose
#: cable is unplugged should cost one line a minute, not a busy core.
BACKOFF = (2.0, 5.0, 15.0, 30.0, 60.0)

#: Failures in a row before it stops trying and says so. A driver that cannot
#: start is a thing to fix, not a thing to retry forever -- and a page that
#: says "failed 4 times, gave up, here is why" is more use than one that says
#: "starting" every minute for a week.
GIVE_UP_AFTER = 5

#: Lines of the process's own output to keep. Enough for a traceback's last
#: frame and its message, which is what says *why*.
KEPT_LINES = 12

#: How long a stopped driver gets to end on its own before it is killed.
PATIENCE = 5.0


class Supervised(NamedTuple):
    """One driver this process starts and watches."""

    name: str
    #: The command, already split. From `collectors.start_command`, which is
    #: what the page prints -- so what runs is what a person would have
    #: typed, and there is no second version of it to drift.
    command: list[str]


def wanted(settings: Any) -> list[Supervised]:
    """The drivers configured to run on this machine.

    Read from the configuration rather than from a registry: a driver that
    runs elsewhere is in the same file with the same shape, and the only
    thing that separates them is this setting.
    """
    from .. import collectors as collector_defs

    out = []
    for name, one in sorted(collector_defs.configured(settings).items()):
        kind = str(one.get("kind", "")).strip()
        if kind not in collector_defs.kinds():
            continue
        if not _here(one):
            continue
        try:
            said = collector_defs.start_command(kind, name)
        except Exception:
            log.debug("no start command for %r", kind, exc_info=True)
            continue
        # `shlex` and not `.split()`: a path with a space in it is a
        # Windows path, and this runs there too.
        out.append(Supervised(name=name, command=shlex.split(said)))
    return out


def _here(one: dict) -> bool:
    """Whether this entry says it runs on this machine.

    Missing means yes. Every entry that existed before this setting was
    written by somebody sitting at the machine they wanted it to run on,
    and defaulting to "somewhere else" would leave all of them stopped with
    nothing on the page saying why.
    """
    said = one.get("runs_here")
    if said is None:
        return True
    if isinstance(said, str):
        return said.strip().lower() not in ("false", "no", "0", "off", "")
    return bool(said)


class Runner:
    """Starts each driver, watches it, and writes down what happened."""

    def __init__(self, drivers: list[Supervised], live: Any = None) -> None:
        self.drivers = drivers
        self.live = live
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []
        #: name -> Popen, so `stop` can end them and the page can be told
        #: whether one is up. Guarded because the watching threads write it.
        self._running: dict[str, Any] = {}
        self._lock = threading.Lock()

    # -- the same three the other runners have -----------------------------

    def replace(self, drivers: list[Supervised]) -> None:
        """Swap in a new set after the configuration changed.

        A method rather than three assignments at the call site, for the
        reason written down at `exports/runner.replace`: the stop flag and
        the thread list have to be rebuilt together, and a caller that
        remembers one of the two gets a runner whose threads end at once.
        """
        self.stop()
        self.drivers = drivers
        self._stopping = threading.Event()
        self._threads = []
        self.start()

    def start(self) -> None:
        if self._stopping.is_set():
            self._stopping = threading.Event()
            self._threads = []
        for one in self.drivers:
            thread = threading.Thread(target=self._loop, args=(one,),
                                      name=f"driver-{one.name}", daemon=True)
            thread.start()
            self._threads.append(thread)
        if self.drivers:
            log.info("running %d driver(s) here: %s", len(self.drivers),
                     ", ".join(one.name for one in self.drivers))

    def stop(self) -> None:
        self._stopping.set()
        with self._lock:
            children = list(self._running.items())
        for name, child in children:
            _end(name, child)
        for thread in self._threads:
            thread.join(timeout=PATIENCE + 1)

    # -- one driver --------------------------------------------------------

    def _loop(self, one: Supervised) -> None:
        """Start it, watch it, start it again -- until told to stop."""
        failures = 0
        while not self._stopping.is_set():
            said: deque[str] = deque(maxlen=KEPT_LINES)
            started = time.time()
            try:
                child = subprocess.Popen(
                    one.command, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1)
            except Exception as exc:
                # The command is not on this machine at all: the add-on that
                # provides it is not installed, or not on PATH. Naming it is
                # the whole answer, and retrying will not change it.
                log.error("driver %s could not be started: %s", one.name, exc)
                self._note(one, "failed", f"{exc}", failures + 1)
                failures += 1
                if failures >= GIVE_UP_AFTER:
                    self._note(one, "gave up", f"{exc}", failures)
                    return
                self._wait(failures)
                continue

            with self._lock:
                self._running[one.name] = child
            self._note(one, "running", "", failures)
            log.info("driver %s started (pid %s)", one.name, child.pid)

            # Its output, line by line, so that what it says while dying is
            # kept. Read on this thread: it is the thread whose job is this
            # process, and a pipe nobody reads fills and blocks the child.
            try:
                if child.stdout is not None:
                    for line in child.stdout:
                        said.append(line.rstrip())
                code = child.wait()
            except Exception:
                log.debug("driver %s: could not read its output", one.name,
                          exc_info=True)
                code = child.poll() or 0
            finally:
                with self._lock:
                    self._running.pop(one.name, None)

            if self._stopping.is_set():
                self._note(one, "stopped", "", 0)
                return

            # A driver that ran for a while and then stopped is a different
            # thing from one that cannot start: the first is worth trying
            # again from scratch, and counting it against the give-up limit
            # would eventually stop a station that works.
            lived = time.time() - started
            failures = 0 if lived >= 60 else failures + 1
            tail = "\n".join(said)
            log.warning("driver %s ended (%s) after %.0fs%s", one.name, code,
                        lived, f": {said[-1]}" if said else "")
            if failures >= GIVE_UP_AFTER:
                self._note(one, "gave up", tail, failures)
                log.error("driver %s failed %d times in a row; not trying "
                          "again until the settings change", one.name, failures)
                return
            self._note(one, "failed", tail, failures)
            self._wait(failures)

    def _wait(self, failures: int) -> None:
        """Sleep before the next try, interruptibly."""
        delay = BACKOFF[min(failures, len(BACKOFF)) - 1] if failures else 0.0
        self._stopping.wait(timeout=delay)

    # -- what the page reads -----------------------------------------------

    def _note(self, one: Supervised, state: str, said: str,
              failures: int) -> None:
        """Write the state where the settings page can see it.

        Through the live table, because the page is a different process and
        that table is the only channel between the parts of this program.
        Same arrangement, and the same reason, as `exports/record.py`.
        """
        if self.live is None:
            return
        try:
            import json

            self.live.set_meta(key(one.name), json.dumps({
                "name": one.name, "state": state, "when": int(time.time()),
                "failures": failures, "said": said[-2000:],
                "command": " ".join(one.command),
            }, separators=(",", ":")))
        except Exception:
            # Never the reason a driver stops running. The page falls back
            # to "not started yet", which is wrong but harmless; a crash
            # here would take the hardware off the air.
            log.debug("could not record the state of driver %s", one.name,
                      exc_info=True)


def _end(name: str, child: Any) -> None:
    """Ask it to stop, then make it.

    A child still holding the serial port makes the next start fail with a
    message about the hardware -- which reads as a broken cable rather than
    as our own process still sitting on it.
    """
    try:
        if child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=PATIENCE)
        except subprocess.TimeoutExpired:
            log.warning("driver %s did not stop; killing it", name)
            child.kill()
            child.wait(timeout=PATIENCE)
    except Exception:
        log.debug("could not stop driver %s", name, exc_info=True)


def states(live: Any, names: list[str]) -> dict[str, dict]:
    """What each named driver is doing, for the settings page.

    By name rather than by scanning the table: the live store answers one
    key at a time (`get_meta`), and the caller has the names -- they are the
    entries in the configuration it is already reading to draw the rows.
    """
    if live is None:
        return {}
    import json

    found: dict[str, dict] = {}
    for name in names:
        try:
            raw = live.get_meta(key(name))
        except Exception:
            log.debug("could not read the state of driver %s", name,
                      exc_info=True)
            continue
        if not raw:
            continue
        try:
            one = json.loads(raw)
        except ValueError:
            continue
        if isinstance(one, dict):
            found[name] = one
    return found

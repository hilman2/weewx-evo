#!/usr/bin/env python3
"""A driver that runs on this machine is started here, not typed in.

The settings page printed a command and left it there. Right for hardware on
another machine -- there is no channel to it -- and wrong for the ordinary
arrangement, which is one machine: weewx-evo on the Pi, the console on a USB
adapter of that same Pi.

What is measured, in the order it can go wrong:

  * it actually starts, and the state reaches the page's process
  * a driver that dies is started again, and the reason it died is kept --
    "died" on its own sends somebody to a log file
  * one that cannot start at all is given up on rather than retried forever
  * stopping ends the child. A process still holding the serial port makes
    the next start fail with a message about the hardware
  * `runs_here = false` starts nothing, because then it is somebody else's
    process on somebody else's machine

The child is a small Python program written by the test rather than a real
driver: what is under test is the supervising, and a real driver would need
hardware to be honest about it.

    python tools/driverprocess_test.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo.db.live import LiveStore  # noqa: E402
from weewx_evo.ingest import driverrunner  # noqa: E402

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def until(answers, want=True, patience: float = 10.0) -> object:
    """Wait for a condition, or give up and let the check report it.

    Polled rather than slept-then-asserted: a fixed sleep is either slower
    than it needs to be or shorter than a loaded machine needs, and the
    second one is a test that fails for nobody's fault.
    """
    deadline = time.time() + patience
    got = answers()
    while got != want and time.time() < deadline:
        time.sleep(0.05)
        got = answers()
    return got


def a_child(work: Path, name: str, body: str) -> list[str]:
    """A program to supervise, and the command that runs it."""
    path = work / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return [sys.executable, str(path)]


#: Runs until it is told to stop. Prints one line first, so the test can
#: tell "started" from "about to start".
FOREVER = """
import sys, time
print("up", flush=True)
while True:
    time.sleep(0.05)
"""

#: Dies immediately, the way a driver whose library is missing dies.
DIES = """
import sys
print("ModuleNotFoundError: No module named 'serial'", file=sys.stderr,
      flush=True)
raise SystemExit(1)
"""


def it_starts_and_says_so(work: Path) -> None:
    print("\na driver that runs here")
    live = LiveStore(work / "live.sdb", interval_seconds=60)
    try:
        one = driverrunner.Supervised(
            name="shed", command=a_child(work, "forever", FOREVER))
        runner = driverrunner.Runner([one], live)
        runner.start()
        try:
            state = until(lambda: (driverrunner.states(live, ["shed"])
                                   .get("shed", {}).get("state")), "running")
            check("it is running", state, "running")
            # The page is a different process, so this is the half that
            # matters: the state has to be in the live table, not in the
            # runner's memory.
            said = driverrunner.states(live, ["shed"]).get("shed", {})
            check("and the row names the command it ran",
                  "forever" in str(said.get("command", "")), True)
        finally:
            runner.stop()

        check("stopping says so", driverrunner.states(live, ["shed"])
              .get("shed", {}).get("state"), "stopped")
    finally:
        live.close()


def a_dead_one_is_restarted_and_explained(work: Path) -> None:
    print("\none that dies")
    live = LiveStore(work / "live2.sdb", interval_seconds=60)
    try:
        one = driverrunner.Supervised(
            name="roof", command=a_child(work, "dies", DIES))
        # A backoff of a minute would make this test a minute long. Shortened
        # here rather than in the module: what is under test is that it waits
        # and gives up, not how long it waits.
        was, driverrunner.BACKOFF = driverrunner.BACKOFF, (0.05,)
        runner = driverrunner.Runner([one], live)
        runner.start()
        try:
            state = until(lambda: (driverrunner.states(live, ["roof"])
                                   .get("roof", {}).get("state")), "gave up")
            check("it gives up rather than looping forever", state, "gave up")
            said = driverrunner.states(live, ["roof"]).get("roof", {})
            check("after the limit", said.get("failures"),
                  driverrunner.GIVE_UP_AFTER)
            # The whole point of keeping the output. Without this the page
            # says "failed" and the reason is in a log nobody opens.
            check("and it kept what the process said",
                  "No module named 'serial'" in str(said.get("said", "")), True)
        finally:
            runner.stop()
            driverrunner.BACKOFF = was
    finally:
        live.close()


def stopping_ends_the_child(work: Path) -> None:
    """A child still holding the port makes the next start fail."""
    print("\nstopping it")
    live = LiveStore(work / "live3.sdb", interval_seconds=60)
    try:
        one = driverrunner.Supervised(
            name="barn", command=a_child(work, "forever2", FOREVER))
        runner = driverrunner.Runner([one], live)
        runner.start()
        until(lambda: (driverrunner.states(live, ["barn"])
                       .get("barn", {}).get("state")), "running")
        child = runner._running.get("barn")
        check("there is a process", child is not None, True)
        started = time.time()
        runner.stop()
        took = time.time() - started
        if child is not None:
            # `poll` is None while it lives. Asked after the stop returned:
            # a stop that comes back before its child is gone is one that
            # leaves the port held.
            check("and it is gone when stop() returns",
                  child.poll() is not None, True)
        # And it is asked to stop before it is killed. Killing works either
        # way, so this is the check that would otherwise be missing: without
        # the terminate, every stop waits out the full patience -- and every
        # `replace` goes through a stop, so saving a setting would take five
        # seconds for each driver configured.
        check(f"without waiting out the patience ({took:.1f}s)",
              took < driverrunner.PATIENCE, True)
    finally:
        live.close()


def one_that_runs_elsewhere_is_not_started() -> None:
    print("\none that runs somewhere else")
    settings = {"collectors": {
        "here": {"kind": "mqtt"},
        "there": {"kind": "mqtt", "runs_here": False},
        "also_there": {"kind": "mqtt", "runs_here": "false"},
    }}
    got = [one.name for one in driverrunner.wanted(settings)]
    check("only the one that says it runs here", got, ["here"])

    # A setting nobody has written means yes: every entry that existed
    # before this was made by somebody at the machine they wanted it on,
    # and defaulting to "elsewhere" would stop all of them silently.
    check("a missing setting means here",
          [one.name for one in driverrunner.wanted(
              {"collectors": {"old": {"kind": "mqtt"}}})], ["old"])

    # And the command is the one the page prints, not a second version of
    # it -- there is nothing here to drift out of step.
    from weewx_evo import collectors as collector_defs

    made = driverrunner.wanted({"collectors": {"x": {"kind": "mqtt"}}})
    check("it runs what the page says to run",
          " ".join(made[0].command), collector_defs.start_command("mqtt", "x"))


def main() -> int:
    print("a driver on this machine is started here")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        it_starts_and_says_so(work)
        a_dead_one_is_restarted_and_explained(work)
        stopping_ends_the_child(work)
        one_that_runs_elsewhere_is_not_started()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("started, watched, explained when it dies, and stopped for real")
    return 0


if __name__ == "__main__":
    sys.exit(main())

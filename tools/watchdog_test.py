#!/usr/bin/env python3
"""When the process stands aside for a fresh one, and when it must not.

A watchdog has two ways to be worthless and they pull in opposite
directions. One is never firing, which is a comment pretending to be code.
The other is firing at things a restart does not cure -- a station switched
off overnight, a weather service having a bad hour -- which turns one
outage into an hourly outage. So both halves are checked here, and the
second half is the longer one.

The floor between restarts is the part that has to survive the restart it is
limiting, so it lives in the live database rather than in memory. The test
for it makes a second watchdog against the same database, which is what the
next process is.

    python tools/watchdog_test.py
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import watchdog  # noqa: E402
from weewx_evo.db.live import LiveStore  # noqa: E402

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def _a_free_port() -> int:
    """One nobody is using, asked of the kernel rather than picked here.

    A test that binds a chosen number passes until something else on the
    machine has it, and then fails now and then for a reason unconnected to
    what it checks. That is worse than failing every time.
    """
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Asked:
    """Stands in for the loop being asked to stop."""

    def __init__(self) -> None:
        self.why: list[str] = []

    def __call__(self, why: str) -> None:
        self.why.append(why)


def watchdog_on(store: LiveStore, **kw: object) -> tuple[watchdog.Watchdog, Asked]:
    asked = Asked()
    dog = watchdog.Watchdog(store, asked, **kw)  # type: ignore[arg-type]
    return dog, asked


def a_healthy_process_is_left_alone() -> None:
    print("\nnothing wrong, nothing done")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        dog, asked = watchdog_on(store)
        check("no symptoms", dog.symptoms(), [])
        check("and no restart asked for", dog.check(), False)
        check("nobody was told to stop", asked.why, [])
        store.close()


def a_dead_thread_is_a_symptom() -> None:
    """A runner thread that has died never comes back by itself."""
    print("\na runner thread that has died")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")

        class Runner:
            def __init__(self, name: str) -> None:
                self.thread = threading.Thread(target=lambda: None, name=name)
                self.thread.start()
                self.thread.join()

        alive = threading.Event()
        keep = threading.Thread(target=lambda: alive.wait(10), name="feeds")
        keep.start()

        class Living:
            thread = keep

        dog, asked = watchdog_on(store, threads=watchdog.threads_of(
            Runner("upload-live"), Living(), None))
        found = dog.symptoms()
        check("the dead one is named", found,
              ["the upload-live thread(s) have died"])
        check("and the living one is not mentioned",
              "feeds" in "".join(found), False)
        check("a restart is asked for", dog.check(), True)
        check("with the reason", asked.why,
              ["the upload-live thread(s) have died"])
        alive.set()
        keep.join(5)
        store.close()


def a_stopped_loop_is_a_symptom() -> None:
    print("\nan archiver loop that stopped going round")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        dog, asked = watchdog_on(store)
        dog.beat = time.time() - watchdog.HEARTBEAT_SILENCE - 1
        check("it is noticed", len(dog.symptoms()), 1)
        dog.beats()
        check("and a beat clears it", dog.symptoms(), [])
        check("nobody was asked to stop in between", asked.why, [])
        store.close()


def a_listener_has_no_loop_to_watch() -> None:
    """The half that stops it restarting into somebody else's outage.

    The listener sits in serve_forever. How long since it last did anything
    is a fact about the console, so a station switched off overnight would
    look exactly like a stopped loop.
    """
    print("\na listener is not judged by how long the console has been quiet")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        dog, _ = watchdog_on(store, heartbeat=False)
        dog.beat = time.time() - 86400  # a day of silence
        check("a day with no packets is not a symptom", dog.symptoms(), [])
        store.close()


def not_more_than_once_an_hour() -> None:
    print("\nthe floor between two restarts")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        dog, asked = watchdog_on(store, cooldown=3600)
        dog.beat = time.time() - watchdog.HEARTBEAT_SILENCE - 1

        check("the first one goes through", dog.check(), True)
        check("the second, straight after, does not", dog.check(), False)
        check("and only one restart was asked for", len(asked.why), 1)

        # The next process. It has the same database and nothing else.
        again, asked_again = watchdog_on(store, cooldown=3600)
        again.beat = time.time() - watchdog.HEARTBEAT_SILENCE - 1
        check("a fresh process is held to the same floor",
              again.check(), False)
        check("so a loop cannot start", asked_again.why, [])

        # An hour later.
        store.set_meta(watchdog.MEMORY, f"{time.time() - 3601:.0f}")
        check("an hour on, it may act again", again.check(), True)
        store.close()


def a_restart_that_cannot_be_written_down_does_not_happen() -> None:
    """Because that is precisely the loop the floor exists to prevent."""
    print("\nwhen the floor cannot be recorded")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")

        class Deaf:
            """A database that takes a write and forgets it."""

            def get_meta(self, name: str) -> str | None:
                return None

            def set_meta(self, name: str, value: str) -> None:
                return None

        dog, asked = watchdog_on(Deaf())
        dog.beat = time.time() - watchdog.HEARTBEAT_SILENCE - 1
        check("the symptom is there", len(dog.symptoms()), 1)
        check("but no restart is asked for", dog.check(), False)
        check("nobody was told to stop", asked.why, [])

        class Broken:
            """One that raises instead."""

            def get_meta(self, name: str) -> str | None:
                raise OSError("disk")

            def set_meta(self, name: str, value: str) -> None:
                raise OSError("disk")

        loud, asked_loud = watchdog_on(Broken())
        loud.beat = time.time() - watchdog.HEARTBEAT_SILENCE - 1
        check("a database that raises is the same answer", loud.check(), False)
        check("and still nobody was told to stop", asked_loud.why, [])
        store.close()


def the_watchdogs_own_failure_is_not_the_end() -> None:
    """It runs on its own thread. A thread that dies takes the check with it."""
    print("\nthe watchdog's own pass failing")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")

        def explode() -> dict[str, bool]:
            raise RuntimeError("the check itself is broken")

        dog, asked = watchdog_on(store, every=0.05, threads=explode)
        # It logs the traceback on purpose -- that is the point of the branch.
        # Quiet here so the provoked one does not bury the results.
        watchdog.log.setLevel(logging.CRITICAL)
        dog.start()
        time.sleep(0.3)
        check("its thread is still running", dog.thread.is_alive(), True)
        check("and it asked for nothing", asked.why, [])
        dog.stop()
        watchdog.log.setLevel(logging.NOTSET)
        check("and it stops when told", dog.thread.is_alive(), False)
        store.close()


def descriptors_are_measured_not_guessed() -> None:
    """The count is real; the line it is compared against is moved to meet it.

    Opening 85% of the table would mean 8704 files here and close to a
    million in a container -- the share is the point, not the number. So a
    real handful is opened and the line is put between the two counts, which
    exercises the same code with the same measurement.
    """
    print("\nthe descriptor check")
    open_now = watchdog.descriptors_open()
    limit = watchdog.descriptor_limit()
    if open_now is None or limit is None:
        print("  --   no /proc or no RLIMIT here, so this check stands down")
        # Standing down is itself worth verifying: a check that cannot
        # measure must report nothing rather than guess.
        with tempfile.TemporaryDirectory() as raw:
            store = LiveStore(Path(raw) / "live.sdb")
            dog, _ = watchdog_on(store)
            check("and reports nothing rather than guessing",
                  dog.symptoms(), [])
            store.close()
        return

    print(f"  --   {open_now} of {limit} open")
    check("a healthy process is well under the real line",
          open_now < limit * watchdog.DESCRIPTOR_SHARE, True)

    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        dog, _ = watchdog_on(store)
        held = []
        was = watchdog.DESCRIPTOR_SHARE
        try:
            before = watchdog.descriptors_open()
            # Held open on purpose, which is what a leak is. A context
            # manager here would close each one as it opened, and the count
            # would never move.
            held = [open(store.path, "rb") for _ in range(50)]  # noqa: SIM115
            after = watchdog.descriptors_open()
            check("the count follows what was opened", after - before >= 50, True)

            # Halfway between the two counts, so the same comparison decides
            # it -- the leak this was built for, at a scale a test can hold.
            watchdog.DESCRIPTOR_SHARE = (before + 25) / limit
            check("over the line, it says so", len(dog.symptoms()), 1)
            check("and the message names the numbers",
                  "descriptors are open" in dog.symptoms()[0], True)

            for handle in held:
                handle.close()
            held = []
            check("under it again, it says nothing", dog.symptoms(), [])
        finally:
            watchdog.DESCRIPTOR_SHARE = was
            for handle in held:
                handle.close()
        store.close()


def a_real_serve_stops_when_asked() -> None:
    """The wiring, which no check above touches.

    Everything else here exercises the watchdog against a stand-in. What is
    left is the part that failed at review: `ask_to_restart` has to reach the
    loop's event, and the loop has to run its shutdown and leave. A call in a
    branch nothing walks through is exactly the shape that gets committed
    working and stays broken, so this walks it -- a real process, started the
    way the container starts it.

    The symptom is provoked by moving the descriptor line under the count
    rather than by leaking anything: same comparison, same code path, over in
    a second.
    """
    print("\na real serve, asked to stand aside")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "sitecustomize.py").write_text(
            "import weewx_evo.watchdog as w\n"
            # Under any real count, so the first pass finds it.
            "w.DESCRIPTOR_SHARE = 0.00001\n"
            "w.EVERY = 0.5\n", encoding="utf-8")
        (work / "evo.toml").write_text(
            'token = "abcdefghij123456"\n'
            f"port = {_a_free_port()}\n"
            f'live_db = "{(work / "live.sdb").as_posix()}"\n'
            f'archive_db = "{(work / "weewx.sdb").as_posix()}"\n'
            "watchdog = true\n"
            "watchdog_cooldown = 300\n", encoding="utf-8")

        env = dict(os.environ)
        # The real entry point, in a subprocess, for the reason the settings
        # test gives: `cli` run as `__main__` is a different module object
        # from `weewx_evo.cli`, and importing it here would hide that.
        env["PYTHONPATH"] = os.pathsep.join(
            [str(work), str(ROOT / "src"), env.get("PYTHONPATH", "")])
        proc = subprocess.run(
            [sys.executable, "-m", "weewx_evo.cli", "serve",
             "--config", str(work / "evo.toml")],
            # The exit code is a result here, not a precondition: a clean 0
            # is exactly what is being checked.
            env=env, capture_output=True, text=True, timeout=60, check=False)
        out = proc.stdout + proc.stderr

        check("it noticed", "file descriptors are open" in out, True)
        check("and said it was standing aside",
              "Stopping so the supervisor starts a fresh process" in out, True)
        check("it actually left", proc.returncode, 0)
        check("and told anybody reading what has to happen next",
              "supervisor is missing" in out, True)

        # The floor was written before it went, so the process that comes
        # back finds it. That is the difference between a restart and a loop.
        store = LiveStore(work / "live.sdb")
        try:
            check("and wrote the floor down before going",
                  store.get_meta(watchdog.MEMORY) is not None, True)
        finally:
            store.close()

        if failures:
            print("  --   output was:")
            for line in out.splitlines()[-12:]:
                print(f"       {line}")


def main() -> int:
    a_healthy_process_is_left_alone()
    a_dead_thread_is_a_symptom()
    a_stopped_loop_is_a_symptom()
    a_listener_has_no_loop_to_watch()
    not_more_than_once_an_hour()
    a_restart_that_cannot_be_written_down_does_not_happen()
    the_watchdogs_own_failure_is_not_the_end()
    descriptors_are_measured_not_guessed()
    a_real_serve_stops_when_asked()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("it restarts for what a restart fixes, and not more than once an hour")
    return 0


if __name__ == "__main__":
    sys.exit(main())

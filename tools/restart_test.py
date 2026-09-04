#!/usr/bin/env python3
"""What a restart costs, and what is reachable while it is being paid.

An instance that has been running has a live table full of packets whose
intervals are all in the archive already. Coming back up it has, at most, the
one interval that was open when it went down. Anything more than that is work
being done twice.

Two things are measured here, and both were wrong on a running instance:

    the catch-up   built every interval the live table covered, and asked
                   whether it was already archived afterwards. Twelve hours of
                   retention meant 153 intervals rebuilt to arrive at 153
                   records that were already there.
    the web server started after that, so a reverse proxy in front of it
                   answered 502 for the whole of it -- for pages sitting
                   complete on disk the entire time.

    python tools/restart_test.py
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo.archiver import Archiver  # noqa: E402
from weewx_evo.db.archive import ArchiveStore  # noqa: E402
from weewx_evo.db.live import LiveStore, Packet  # noqa: E402

failures = 0

#: Long enough that rebuilding it is plainly not free, short enough that the
#: first pass -- which is real work either way -- does not dominate the run.
HOURS = 3
#: What an Ecowitt console sends. The packet count is what the catch-up reads,
#: so it is the number that decides whether this measures anything.
EVERY = 16
INTERVAL = 300


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def _lines_until(proc: subprocess.Popen, marker: str,
                 seconds: float = 30.0, settle: float = 2.0) -> list[str]:
    """A running process's output, up to `marker` and a moment after it.

    `communicate(timeout=30)` was here and waited the whole thirty seconds
    every time: a `serve` does not exit, so the timeout was not a limit on
    anything, it was the runtime.

    **One marker, not two.** Waiting for the archiver's first line as well
    looks tighter and is the same bug in a smaller font -- the check below
    says outright that the line may never come, so waiting for it is waiting
    for the timeout. What is being measured is which of the two came first,
    and for that the second only has to have had its chance: `settle` is how
    long that chance is.

    On its own thread, because reading here would block on a process that is
    busy and not talking -- which is exactly what a catch-up does. And
    `readline` rather than iterating the pipe: iteration reads ahead into a
    buffer in *this* process, so a line the child wrote is held here until
    enough of them arrive.
    """
    import threading

    lines: list[str] = []
    said = threading.Event()

    def reader() -> None:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line.rstrip())
            if marker in lines[-1]:
                said.set()
        said.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    if said.wait(seconds):
        time.sleep(settle)
    proc.terminate()
    thread.join(5)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    return lines


def _a_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _filled(home: Path, hours: int = HOURS) -> tuple[LiveStore, ArchiveStore,
                                                     Archiver, int]:
    """A live table with `hours` of packets, and an archiver over it."""
    live = LiveStore(home / "live.sdb")
    archive = ArchiveStore(home / "weewx.sdb", create=True)
    archiver = Archiver(live, archive, interval_seconds=INTERVAL)

    now = 1787900000 // INTERVAL * INTERVAL
    at = now - hours * 3600
    while at < now:
        live.add(Packet(dateTime=at, usUnits=1, identity="probe", kind="loop",
                        data={"outTemp": 60.0 + (at % 7),
                              "outHumidity": 50.0}))
        at += EVERY
    return live, archive, archiver, now


def a_second_catch_up_costs_nothing() -> None:
    """The measurement. Same packets, same archive, second pass.

    Timed rather than counted, because the count was already right: the old
    code returned 0 as well. It just spent a minute arriving at it, and a
    return value of 0 after sixty seconds of work reads exactly like a return
    value of 0 after none.
    """
    print("\nwhat a restart re-does")
    with tempfile.TemporaryDirectory() as raw:
        live, archive, archiver, _now = _filled(Path(raw))
        try:
            print(f"  --   {live.count()} packet(s), {HOURS}h of live table")
            at = time.monotonic()
            first = archiver.catch_up()
            cold = time.monotonic() - at
            check("the first pass builds the intervals", first > 0, True)
            print(f"  --   {first} interval(s) in {cold:.1f}s")

            at = time.monotonic()
            second = archiver.catch_up()
            warm = time.monotonic() - at
            check("the second builds nothing", second, 0)
            print(f"  --   and took {warm:.2f}s")

            # The point, as a proportion rather than a wall-clock figure:
            # this runs on machines of every speed, and what is being claimed
            # is that the work is not done, not that a machine is fast.
            check("because it does not build what is already archived",
                  warm < cold / 10, True)
        finally:
            live.close()
            archive.close()


def a_gap_is_still_filled() -> None:
    """The regression the fix could have introduced.

    Skipping what is archived must not become skipping from the last archived
    record onwards. An interval that failed the first time is inside the live
    span with archived records on both sides, and it is exactly the one a
    catch-up is for.
    """
    print("\na hole in the middle")
    with tempfile.TemporaryDirectory() as raw:
        live, archive, archiver, now = _filled(Path(raw))
        try:
            archiver.catch_up()
            # Take one record out from the middle, the way a crash between
            # building and storing would have left it.
            missing = now - (HOURS * 3600) // 2
            missing -= missing % INTERVAL
            with archive.conn:
                archive.conn.execute("DELETE FROM archive WHERE dateTime = ?",
                                     (missing,))
            check("it is gone", archive.exists(missing), False)

            built = archiver.catch_up()
            check("the catch-up puts it back", built, 1)
            check("and it is there again", archive.exists(missing), True)
        finally:
            live.close()
            archive.close()


def replace_still_builds_everything() -> None:
    """`--replace` is the one caller that wants the work done again."""
    print("\nwhen it is asked to build them anyway")
    with tempfile.TemporaryDirectory() as raw:
        live, archive, archiver, _now = _filled(Path(raw), hours=1)
        try:
            first = archiver.catch_up()
            again = archiver.catch_up(replace=True)
            check("every interval is built again", again, first)
        finally:
            live.close()
            archive.close()


def the_site_answers_before_the_catch_up() -> None:
    """The order, from a real process started the way the container starts it.

    Read off the log rather than by polling the port: a poll races the very
    thing being measured, and would pass on a machine where the catch-up is
    quick regardless of the order.
    """
    print("\nwhat is up before the catch-up is done")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        # An hour is enough: the ordering is a property of the code, not
        # of how long the catch-up takes, and this one waits it out.
        live, archive, _archiver, _now = _filled(work, hours=1)
        live.close()
        archive.close()

        (work / "evo.toml").write_text(
            'token = "abcdefghij123456"\n'
            f"port = {_a_free_port()}\n"
            f'live_db = "{(work / "live.sdb").as_posix()}"\n'
            f'archive_db = "{(work / "weewx.sdb").as_posix()}"\n'
            "web.enabled = true\n"
            f"web.port = {_a_free_port()}\n"
            'web.host = "127.0.0.1"\n',
            encoding="utf-8")

        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT / "src"), env.get("PYTHONPATH", "")])
        # Or nothing arrives until the child fills a buffer. Its
        # stdout is a pipe, so Python block-buffers it, and a reader
        # watching for a log line waits for eight kilobytes of them --
        # which a startup does not produce, so it waited the whole
        # timeout instead.
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "-m", "weewx_evo.cli", "serve",
             "--config", str(work / "evo.toml")],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True)

        # Read until the web server has said it is up, then a moment more
        # so that anything the archiver was going to say has had its
        # chance. Which of the two came first is the whole claim.
        lines = _lines_until(proc, "feed(s) on", seconds=30)
        serving = next((n for n, one in enumerate(lines)
                        if "feed(s) on" in one), None)
        catching = next((n for n, one in enumerate(lines)
                         if "weewx_evo.archiver" in one), None)

        check("the web server said it was up", serving is not None, True)
        if serving is None:
            for line in lines[-8:]:
                print(f"       {line}")
            return
        # `catching` may be None on a run where nothing was left to do, and
        # that is a pass: the claim is about which comes first, and a
        # catch-up that says nothing cannot come first.
        check("before the archiver started working through the live table",
              catching is None or serving < catching, True)


def main() -> int:
    a_second_catch_up_costs_nothing()
    a_gap_is_still_filled()
    replace_still_builds_everything()
    the_site_answers_before_the_catch_up()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("a restart re-does nothing, and the site is up while it happens")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""What the live table leaves behind when a thread that used it goes away.

An SQLite connection belongs to the thread that opened it, so `LiveStore`
keeps one per thread. The listener is a `ThreadingHTTPServer`: every upload is
answered on its own thread, which then ends. That is meant to be fine -- the
connection dies with the thread and the descriptor comes back.

It did not. The store also kept a list of every connection it had ever made,
so `close()` could reach the ones other threads were holding. Held strongly,
no connection was ever the last reference to itself, so none was ever
collected: one descriptor per upload, for the life of the process.

The reason this is a test and not a comment is what it looked like from
outside. The instance hit the 1024 descriptor limit after ten hours, and the
first thing to fail was reading `plots.toml`. Then listing a skin directory,
then the live upload. Three unrelated-looking errors, none of them near the
leak, none of them naming a database.

The measurement is the slope, not a count. SQLite's unix layer keeps closed
descriptors in a pool rather than returning them, because closing any one of
them would drop this process's POSIX locks on the file. So a correct run
settles at a few dozen open and reuses them -- 37 on the machine this was
written on, 61 in the container. A leak is what does not settle.

    python tools/livedb_test.py
"""

from __future__ import annotations

import gc
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo.db.live import LiveStore, Packet, sender_id  # noqa: E402

failures = 0

#: One round is a console's uploads for eight minutes at one every eight
#: seconds. Four rounds is half an hour, which was enough to show the slope.
PER_ROUND = 60
ROUNDS = 4


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def descriptors_on(path: Path) -> int:
    """How many descriptors this process holds on one file, or -1.

    The kernel's answer, where it will give one. `/proc` is Linux, which is
    where this runs in the container and on the instance that found the bug.
    Elsewhere the store's own registry is the measurement, and it counts the
    same thing one step earlier.
    """
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.is_dir():
        return -1
    wanted = str(path.resolve())
    count = 0
    for entry in list(fd_dir.iterdir()):
        try:
            if os.readlink(entry) == wanted:
                count += 1
        except OSError:
            # Closed while we were looking, so it is not one of ours.
            continue
    return count


def one_upload(store: LiveStore, when: int) -> None:
    """What the listener does with an upload, minus the HTTP."""
    store.add(Packet(dateTime=when, usUnits=1, data={"outTemp": 20.0},
                     identity="console"))


def uploads_on_their_own_threads(store: LiveStore, start: int) -> None:
    for n in range(PER_ROUND):
        thread = threading.Thread(target=one_upload, args=(store, start + n))
        thread.start()
        thread.join()
    # Refcounting frees a thread's locals as it ends; the collect is for the
    # cycles `threading.local` leaves behind.
    gc.collect()


def rounds_of_uploads(store: LiveStore) -> list[tuple[int, int]]:
    """Registered connections and open descriptors, after each round."""
    seen = []
    when = 1787800000
    for _ in range(ROUNDS):
        uploads_on_their_own_threads(store, when)
        when += PER_ROUND
        seen.append((len(store._all), descriptors_on(store.path)))
    return seen


def nothing_accumulates() -> None:
    print("\nfour rounds of uploads, each on its own thread")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        seen = rounds_of_uploads(store)
        for n, (held, fds) in enumerate(seen, 1):
            where = "" if fds < 0 else f", {fds} descriptor(s) open"
            print(f"  --   after {n * PER_ROUND:3d} uploads: "
                  f"{held} connection(s) registered{where}")

        check("the store registers this thread's connection and no more",
              [held for held, _ in seen], [1] * ROUNDS)
        check(f"all {ROUNDS * PER_ROUND} packets were stored",
              store.count(), ROUNDS * PER_ROUND)

        counts = [fds for _, fds in seen]
        # Zero is not a measurement either. Windows has no /proc and this
        # returned 0 rather than -1, so the comparison ran, compared 0 with
        # 0, and passed without looking at anything -- exactly what the
        # control below exists to catch.
        if counts[0] <= 0:
            print("  --   descriptors: none counted here, the registry is the check")
        else:
            # Not "few", and not "no more than the first": SQLite's pool fills
            # up over the early rounds and then stops. The container settles at
            # 61 where this machine settles at 37, so the number is not the
            # property. Standing still is -- a leak never stops climbing.
            check("the descriptors reach a plateau instead of climbing",
                  counts[-1], counts[-2])
        store.close()


def dialect_descriptions_are_stored_once() -> None:
    """A large field catalog is one row, not repeated on every upload."""
    print("\none inert dialect description for many packets")
    described = {
        "version": 1,
        "fields": {"tempf": "outTemp"},
        "contested": [],
        "scale": {"tempf": 0.5},
        "metadata": [],
        "absent": ["missing"],
        "groups": {"outTemp": "group_temperature"},
        "usUnits": 1,
    }
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        try:
            for offset in range(3):
                store.add(Packet(
                    dateTime=1787800000 + offset, usUnits=1,
                    data={"tempf": 70 + offset}, driver="push",
                    identity="console", dialect="imperial", mapping=described))
            references = list(store.conn.execute(
                "SELECT DISTINCT mapping FROM packet"))
            check("packets carry one full SHA-256 reference",
                  len(references) == 1 and len(references[0][0]) == 64, True)
            check("the catalog is stored once", store.conn.execute(
                "SELECT count(*) FROM dialect_mapping").fetchone()[0], 1)
            back = list(store.packets(1787799999, 1787800010))
            check("and every read expands it again",
                  [packet.mapping for packet in back], [described] * 3)
            canonical = sender_id("push", "console")
            check("the packet carries its canonical sender id",
                  {packet.sender for packet in back}, {canonical})
            check("and the live directory stores it once",
                  [(one.sender, one.label) for one in store.senders()],
                  [(canonical, "")])

            # A failure after packet insertion must not leave an orphaned
            # packet or catalog. Pending is what makes the archiver ever see
            # it, so all three rows are one transaction.
            original = store.mark_pending

            def fail_pending(*_args: object, **_kwargs: object) -> int:
                raise RuntimeError("stop here")

            store.mark_pending = fail_pending  # type: ignore[method-assign]
            changed = {**described, "fields": {"tempf": "extraTemp1"}}
            try:
                store.add(Packet(
                    dateTime=1787800100, usUnits=1, data={"tempf": 73},
                    driver="push", identity="console", dialect="imperial",
                    mapping=changed))
            except RuntimeError:
                pass
            finally:
                store.mark_pending = original  # type: ignore[method-assign]
            check("a failed pending marker rolls the packet back", store.count(), 3)
            check("and rolls its new catalog back", store.conn.execute(
                "SELECT count(*) FROM dialect_mapping").fetchone()[0], 1)
        finally:
            store.close()


def and_this_test_can_tell() -> None:
    """The same run with the bug put back, so a green pass means something.

    Without this, every check above would still pass against a store that
    never registered anything at all.
    """
    print("\nthe same, with the strong list put back")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        # What it was: nothing put here is ever released. Replacing it
        # drops the connection this thread already registered, so the
        # count is a clean multiple of the uploads.
        store._all = set()
        seen = rounds_of_uploads(store)
        held = [count for count, _ in seen]
        print(f"  --   registered after each round: {held}")
        check("it grows by one per upload, which is the bug",
              held, [PER_ROUND * n for n in range(1, ROUNDS + 1)])
        counts = [fds for _, fds in seen]
        if counts[0] > 0:
            check("and the descriptors grow with it", counts[-1] > counts[0], True)
        store.close()
        # This branch deliberately reinstates the old strong registry. Its
        # foreign-thread connections can only be finalized after those strong
        # references are dropped; collect them before Windows removes the DB.
        gc.collect()


def a_thread_that_stays_keeps_its_connection() -> None:
    """The other half: releasing must not reach a connection still in use."""
    print("\na long-lived thread keeps the one it opened")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        seen: list[object] = []
        go = threading.Event()
        ready = threading.Event()

        def worker() -> None:
            try:
                one_upload(store, 1787800000)
                seen.append(store.conn)
                ready.set()
                go.wait(5)
                seen.append(store.conn)
            finally:
                # The assertions retain this thread's connection in `seen`.
                # Close it here, where SQLite permits it, before Windows
                # removes the temporary database.
                store.conn.close()

        thread = threading.Thread(target=worker)
        thread.start()
        ready.wait(5)
        gc.collect()
        check("it is registered for as long as its thread runs",
              len(store._all), 2)
        go.set()
        thread.join(5)
        check("and it is the same connection both times",
              seen[0] is seen[1], True)
        store.close()


def close_reaches_the_other_threads() -> None:
    """Why the registry exists at all, so the weak version still earns it."""
    print("\nclose() still closes what another thread opened")
    with tempfile.TemporaryDirectory() as raw:
        store = LiveStore(Path(raw) / "live.sdb")
        held: list[object] = []
        release = threading.Event()
        ready = threading.Event()

        def worker() -> None:
            connection = store.conn
            try:
                held.append(connection)
                ready.set()
                release.wait(5)
            finally:
                # `held` deliberately outlives this thread. Closing here makes
                # that retained test reference harmless during temp cleanup.
                connection.close()

        thread = threading.Thread(target=worker)
        thread.start()
        ready.wait(5)
        store.close()
        try:
            held[0].execute("SELECT 1")  # type: ignore[attr-defined]
            closed = False
        except Exception:
            closed = True
        check("the other thread's connection was closed too", closed, True)
        release.set()
        thread.join(5)


def main() -> int:
    nothing_accumulates()
    dialect_descriptions_are_stored_once()
    and_this_test_can_tell()
    a_thread_that_stays_keeps_its_connection()
    close_reaches_the_other_threads()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("the live table gives a descriptor back when its thread ends")
    return 0


if __name__ == "__main__":
    sys.exit(main())

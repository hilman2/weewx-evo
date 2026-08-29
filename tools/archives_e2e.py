#!/usr/bin/env python3
"""Two archives, all the way out: readings in, pages and files out.

`archives_test.py` follows two consoles into two files. This one carries on
from there, because that is only half the chain and the other half is where
an operator would notice:

    ingest       two consoles, announced, into one live table
    archiver     one per series, each with its own place and stations
    feeds        one per series, each reading its own file          <- here
    exports      each moving its own feed's directory               <- here
    a page       one place, or several                              <- here

Run against a real `serve` process with a simulator uploading throughout, so
nothing here is a code path called by hand. Roughly two minutes: the archive
interval is a minute and records have to actually appear.

    python tools/archives_e2e.py
    python tools/archives_e2e.py --keep   # leave the directory to look at

What it is looking for is the thing that cannot be seen from inside one
component: a feed reading the wrong file produces a perfectly good page of
somebody else's weather, and nothing about it looks wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

TOKEN = "e2e-token-for-the-archives-test"

#: A minute, so a record appears while the test is still running. Everything
#: about the arithmetic is the same at five.
INTERVAL = 60

#: The two places. Far enough apart that a page computed with the wrong
#: coordinates is obviously the wrong one -- Kirchdorf and a field in Chile,
#: where the sun is on the other side of the year.
SOUTH = {"label": "Suedfeld", "latitude": 48.3858, "longitude": 11.7050,
         "altitude": 440.0}
NORTH = {"label": "Nordfeld", "latitude": 53.5511, "longitude": 9.9937,
         "altitude": 6.0}

#: What each console reports. Different enough that a value in the wrong file
#: is unmistakable rather than a rounding difference.
READINGS = {
    "suedhof": {"outTemp": 21.5, "outHumidity": 55.0, "barometer": 1013.2},
    "nordhof": {"outTemp": 8.3, "outHumidity": 82.0, "barometer": 1002.7},
    # A third console, on the north field, announced as an extra station.
    # Its readings must be moved aside rather than take turns with the main
    # one -- the roles rule, exercised here across two archives at once.
    "nordschuppen": {"outTemp": 11.9, "outHumidity": 70.0},
}

failures = 0
gaps: list[str] = []
#: Which checks failed, so the summary can name them. `runtests.py` shows the
#: last few lines of a failing tool, and this one prints forty lines of the
#: service's own log before its verdict -- so "1 check(s) failed" was all
#: that survived, and finding out which one meant running it again by hand.
failed: list[str] = []


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    if not ok:
        failures += 1
        failed.append(f"{what}: {got!r} (wanted {want!r})")
    return ok


def gap(what: str, works: bool, why: str) -> bool:
    """Something two archives cannot do yet. Reported, not failed.

    These are decisions nobody has made rather than code that is wrong, and
    a test that stays red for them is a test that gets ignored -- which is
    how the two real bugs above it would have gone unnoticed. Listed at the
    end so they are countable, and it says so out loud when one starts
    working, because a gap that closes and is still described as open is
    worse than one nobody wrote down.
    """
    if works:
        print(f"  ok   {what} -- this now works; drop it from the gaps")
        return True
    print(f"  gap  {what}")
    print(f"       {why}")
    gaps.append(what)
    return False


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Simulator(threading.Thread):
    """Three consoles, uploading for as long as the test runs.

    A thread rather than a burst before the wait, because an archive interval
    is worked out from what arrived *during* it. Uploading everything up
    front and then sleeping produces one interval with data and several
    without, which is a different test and an easier one.
    """

    def __init__(self, base: str, every: float = 2.0) -> None:
        super().__init__(daemon=True)
        self.base = base
        self.every = every
        self.stopping = threading.Event()
        self.sent = 0
        self.refused = 0
        self.why: str | None = None

    def run(self) -> None:
        step = 0
        while not self.stopping.is_set():
            for source, readings in READINGS.items():
                # A little movement, so the archive holds an average of
                # something rather than one value repeated.
                data = {k: round(v + (step % 5) * 0.1, 2)
                        for k, v in readings.items()}
                body = json.dumps([{
                    "dateTime": int(time.time()), "usUnits": 16,
                    "source": source, "kind": "loop", "data": data,
                }]).encode()
                try:
                    request = urllib.request.Request(
                        f"{self.base}/{TOKEN}/json/", data=body,
                        headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(request, timeout=5) as answer:
                        answer.read()
                    self.sent += 1
                except Exception as exc:
                    self.refused += 1
                    # The first one, verbatim. A simulator that swallows why
                    # it was refused turns "the rate limit locked us out"
                    # into "the archive is empty", which is a much longer
                    # afternoon.
                    if self.why is None:
                        self.why = f"{type(exc).__name__}: {exc}"
            step += 1
            self.stopping.wait(self.every)

    def stop(self) -> None:
        self.stopping.set()


def lay_out(work: Path, port: int) -> Path:
    """Write the whole configuration: two archives, three stations, feeds."""
    (work / "data").mkdir(exist_ok=True)
    (work / "out").mkdir(exist_ok=True)
    (work / "published").mkdir(exist_ok=True)

    (work / "archives.toml").write_text(f"""
[archives.default]
file = "data/sued.sdb"
label = "{SOUTH['label']}"
latitude = {SOUTH['latitude']}
longitude = {SOUTH['longitude']}
altitude = {SOUTH['altitude']}

[archives.nordfeld]
file = "data/nord.sdb"
label = "{NORTH['label']}"
latitude = {NORTH['latitude']}
longitude = {NORTH['longitude']}
altitude = {NORTH['altitude']}
""", encoding="utf-8")

    (work / "stations.toml").write_text("""
[stations.suedhof]
driver = "json"
identity = "suedhof"
archive = "default"

[stations.nordhof]
driver = "json"
identity = "nordhof"
archive = "nordfeld"

[stations.nordschuppen]
driver = "json"
identity = "nordschuppen"
archive = "nordfeld"
role = "extra"
channel = 1
""", encoding="utf-8")

    # The JSON feed writes one file per chart, so with no charts it has
    # nothing to write and says so. That is right, and it means this test
    # needs one -- otherwise both feeds "work" by producing nothing, and the
    # comparison between them passes on two empty directories.
    (work / "plots.toml").write_text("""
[[plot]]
name = "temperature"
span = "day"
time_length = "27h"
title = "Temperature"

  [[plot.line]]
  obs = "outTemp"

[[plot]]
name = "humidity"
span = "day"
time_length = "27h"
title = "Humidity"

  [[plot.line]]
  obs = "outHumidity"
""", encoding="utf-8")

    config = work / "evo.toml"
    # The bare keys come *first*. Everything after a `[section]` header
    # belongs to that section, so `port` under `[station]` is `station.port`
    # and the listener goes on using its default -- which is what happened,
    # and looked like the service ignoring the setting.
    config.write_text(f"""
archive_db = "data/sued.sdb"
live_db = "data/live.sdb"
interval = {INTERVAL}
port = {port}
token = "{TOKEN}"
allow = "any"
feeds_dir = "out"
grace = 1
poll = 1
watchdog = false

[station]
name = "Suedfeld"
latitude = {SOUTH['latitude']}
longitude = {SOUTH['longitude']}
altitude = {SOUTH['altitude']}

# One JSON feed per series, each naming the archive it reads. This is the
# setting the whole test is about: get it wrong and the north page shows the
# south's weather, correctly formatted.
[feeds.sued_json]
kind = "json"
destination = "sued"
archive = "default"

[feeds.nord_json]
kind = "json"
destination = "nord"
archive = "nordfeld"

# And an export per feed, so the files really move rather than merely being
# written. Local, because a test that needs an FTP server is testing FTP.
[exports.sued_files]
kind = "local"
source = "sued_json"
directory = "published/sued"

[exports.nord_files]
kind = "local"
source = "nord_json"
directory = "published/nord"
""", encoding="utf-8")
    return config


def serve(work: Path, config: Path, port: int):
    """A real service, with everything it would have in production."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        # `archives.toml` and `stations.toml` are found beside the
        # configuration file rather than named: that is the convention, and
        # naming them here would test a path this has.
        [sys.executable, "-m", "weewx_evo.cli", "serve",
         "--config", str(config)],
        cwd=str(work), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)


def up(base: str, seconds: float = 60) -> bool:
    until = time.time() + seconds
    while time.time() < until:
        try:
            with urllib.request.urlopen(f"{base}/", timeout=2) as answer:
                answer.read()
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.3)
    return False


def records(path: Path) -> int:
    if not path.exists():
        return 0
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def newest(path: Path) -> dict:
    """The last archive record, as a dict. {} if there is none."""
    if not path.exists():
        return {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM archive ORDER BY dateTime DESC LIMIT 1").fetchone()
        return dict(row) if row else {}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def wait_for_records(*paths: Path, seconds: float) -> bool:
    until = time.time() + seconds
    while time.time() < until:
        if all(records(one) > 0 for one in paths):
            return True
        time.sleep(1.0)
    return False


def wait_for_files(*folders: Path, seconds: float) -> bool:
    """Every folder holds at least one JSON. All of them, existing or not.

    The `if one.exists()` this had was a hole: a folder that has not been
    created yet was left out of the comparison, and `all()` over nothing is
    True -- so "both feeds wrote" passed while one of them had not started.
    """
    until = time.time() + seconds
    while time.time() < until:
        if all(one.exists() and any(one.rglob("*.json")) for one in folders):
            return True
        time.sleep(1.0)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true",
                        help="leave the working directory behind")
    args = parser.parse_args()

    print("two archives, from the console to the published file\n")

    work = Path(tempfile.mkdtemp(prefix="weewx-evo-e2e-"))
    port = free_port()
    config = lay_out(work, port)
    base = f"http://127.0.0.1:{port}"
    print(f"  working in {work}")
    print(f"  listener on {base}, interval {INTERVAL}s")

    process = serve(work, config, port)
    sim = Simulator(base)
    try:
        if not up(base):
            out = ""
            try:
                process.terminate()
                out = process.communicate(timeout=10)[0]
            except Exception as exc:
                # Nothing useful left to do: the point of this branch is to
                # print why the service did not start, and it not stopping
                # cleanly is a second problem for a second day.
                print(f"    (and it would not stop: {exc})")
            print("  the service never came up. It said:")
            for line in (out or "").splitlines()[-8:]:
                print(f"    {line}")
            return 1

        sim.start()
        south = work / "data" / "sued.sdb"
        north = work / "data" / "nord.sdb"

        print("\nreadings in, and each series takes its own")
        got = wait_for_records(south, north, seconds=INTERVAL * 2 + 40)
        check("both archives have records", got, True)
        if sim.why:
            print(f"  the first refusal was: {sim.why}")
        check(f"{sim.sent} uploads accepted, {sim.refused} refused",
              sim.refused, 0)

        s_rec, n_rec = newest(south), newest(north)
        print(f"  south outTemp {s_rec.get('outTemp')}, "
              f"north outTemp {n_rec.get('outTemp')}")

        # The readings are metric on the wire and the archive is US by
        # default, so compare in the right direction rather than to the raw
        # number: what matters is that the two files differ by the amount the
        # two consoles differ by, not that they hold a particular value.
        check("the two files hold different temperatures",
              s_rec.get("outTemp") != n_rec.get("outTemp"), True)
        check("the south is the warmer one",
              (s_rec.get("outTemp") or 0) > (n_rec.get("outTemp") or 0), True)

        # The third console is an extra station on the north field. Its
        # readings belong in extraTemp1 of the *north* file and nowhere in
        # the south one.
        check("the extra console is in extraTemp1 of the north",
              n_rec.get("extraTemp1") is not None, True)
        check("and nowhere in the south",
              s_rec.get("extraTemp1"), None)

        print("\nfeeds, each on its own series")
        got = wait_for_files(work / "out" / "sued", work / "out" / "nord",
                             seconds=INTERVAL + 40)
        check("both feeds wrote", got, True)
        _compare_feeds(work / "out" / "sued", work / "out" / "nord")

        print("\nexports, each moving its own feed")
        got = wait_for_files(work / "published" / "sued",
                             work / "published" / "nord", seconds=60)
        check("both exports published", got, True)
        for side in ("sued", "nord"):
            # `live.json` is not the feed's: a local export writes the live
            # readings beside what it publishes, so the page has something
            # newer than the last archive interval. Expected, and checked on
            # its own below.
            made = sorted(p.name for p in
                          (work / "published" / side).rglob("*.json")
                          if p.name != "live.json")
            written = sorted(p.name for p in
                             (work / "out" / side).rglob("*.json"))
            if not check(f"{side}: what the feed wrote is what was published",
                         made == written and bool(made), True):
                # Both lists, because "they differ" is not something anybody
                # can act on. An export that published nothing and one that
                # published into a subdirectory look the same from here.
                print(f"       feed wrote:  {written}")
                print(f"       published:   {made}")
                for one in sorted((work / "published" / side).rglob("*")):
                    print(f"       in published/{side}: "
                          f"{one.relative_to(work / 'published' / side)}")

        print("\nthe live readings each site publishes")
        _live_per_site(work)

        print("\nand a page that wants both")
        _one_page_two_places(work)

    finally:
        sim.stop()
        process.terminate()
        try:
            out = process.communicate(timeout=20)[0]
        except subprocess.TimeoutExpired:
            process.kill()
            out = process.communicate()[0]
        if failures:
            print("\n  the service said:")
            for line in (out or "").splitlines()[-40:]:
                print(f"    {line}")
        if args.keep:
            print(f"\n  left behind: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    print()
    if gaps:
        print(f"{len(gaps)} thing(s) two archives cannot do yet:")
        for one in gaps:
            print(f"  - {one}")
        print()
    if failures:
        print(f"{failures} check(s) failed:")
        for one in failed:
            print(f"  {one}")
        return 1
    print("two archives: ingest, archiver, feeds and exports keep them apart")
    return 0


def _compare_feeds(south: Path, north: Path) -> None:
    """What the two feeds wrote, and whether it is two different series."""
    def series(folder: Path) -> dict:
        for one in sorted(folder.rglob("*.json")):
            try:
                loaded = json.loads(one.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(loaded, dict) and loaded:
                return loaded
        return {}

    s, n = series(south), series(north)
    check("the south feed produced something", bool(s), True)
    check("the north feed produced something", bool(n), True)
    if s and n:
        # Not a deep comparison of the numbers: what is being asked is
        # whether the two feeds read two files. Identical output from two
        # feeds pointed at two archives means one of them read the other's.
        check("and the two are not the same document",
              json.dumps(s, sort_keys=True) != json.dumps(n, sort_keys=True),
              True)


def _live_per_site(work: Path) -> None:
    """What each site's `live.json` holds.

    A local export writes one beside the pages it publishes, so a page can
    show something newer than the last archive interval. With two sites there
    are two of them -- and the question is whether each holds its own site's
    readings or whether both hold whatever arrived last.

    The live table is one table for the whole installation; only the archive
    is per series. So this is the one place where "two archives" and "one
    live table" meet, and what it does is worth knowing either way.
    """
    found = {}
    for side in ("sued", "nord"):
        one = work / "published" / side / "live.json"
        if not one.exists():
            print(f"  {side}: no live.json")
            continue
        try:
            found[side] = json.loads(one.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  {side}: could not read it ({exc})")

    check("each site published live readings", sorted(found), ["nord", "sued"])

    def temp_of(doc: dict):
        """outTemp, whatever unit it was published in.

        The live document names its fields with the unit in them --
        `outTemp_C` -- because the page reading it does no conversion.
        Looking for a bare `outTemp` finds nothing and reads as no data,
        which is what the first version of this reported.
        """
        for key, value in (doc or {}).items():
            if key.split("_")[0] == "outTemp":
                return value
        return None

    for side, doc in sorted(found.items()):
        shown = ", ".join(k for k in sorted(doc) if not k.startswith("_"))
        print(f"  {side}: outTemp {temp_of(doc)}   ({shown})")

    if len(found) == 2:
        # There is one live table for the installation; only the archive is
        # per series. So both sites are handed the same document, and a page
        # for the north field shows whichever console reported last.
        #
        # Checked rather than merely printed, and expected to fail until it
        # is decided: this is the one place the two halves meet, and a note
        # in a log is not something anybody finds.
        # One live table serves the installation, so an upload for one
        # site is told which consoles are its own -- the same filter the
        # archiver has always applied on the other side of the same
        # table. Without it both sites published whichever console
        # reported last: a north page showing 21 C beside its own
        # archive's 8 C, and nothing able to notice.
        check("each site publishes its own live readings",
              temp_of(found["sued"]) != temp_of(found["nord"]), True)


def _one_page_two_places(work: Path) -> None:
    """Can one render see both series? The overview-page question.

    Asked directly of the tag layer, because there is no skin here that would
    ask it -- and because the answer is a property of the layer rather than
    of any skin. A page is built on a `Tags`, and a `Tags` is built on one
    `Reader`.
    """
    from weewx_evo import units
    from weewx_evo.series import Reader
    from weewx_evo.tags import Tags

    south = sqlite3.connect(f"file:{work / 'data' / 'sued.sdb'}?mode=ro",
                            uri=True)
    north = sqlite3.connect(f"file:{work / 'data' / 'nord.sdb'}?mode=ro",
                            uri=True)
    try:
        reader = Reader(south)
        tags = Tags(reader, target=units.Target(reader.system),
                    unit_system=reader.system,
                    station={"location": SOUTH["label"], **SOUTH})
        here = tags.day.outTemp.max
        check("a page has its own series", here.raw is not None, True)

        # And the other one. `$archives.<name>` would be the shape; whether
        # it exists is what this reports.
        # The hook the feed fills in. Set here by hand, because this test
        # builds `Tags` directly rather than through a feed -- what it is
        # asking is whether the tag layer can do it at all.
        from weewx_evo.series import Reader as _Reader

        def reach(name: str):
            if name != "nordfeld":
                return None
            reader = _Reader(north)
            return Tags(reader, target=units.Target(reader.system),
                        unit_system=reader.system,
                        station={"location": NORTH["label"], **NORTH})

        tags.open_archive = reach
        tags.archive_names = ("default", "nordfeld")

        other = getattr(tags, "archives", None)
        works = other is not None and getattr(other, "nordfeld", None) is not None
        check("a page can reach another series", works, True)
        if works:
            theirs = other.nordfeld.day.outTemp.max
            check("and gets that series' reading, not this one's",
                  theirs.raw != here.raw, True)
    finally:
        south.close()
        north.close()


if __name__ == "__main__":
    sys.exit(main())

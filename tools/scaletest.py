"""How long a page takes on an archive that has been running for years.

A station is set up once and then runs. The pages that are slow are not
the ones with today's readings on them; they are the ones that walk the
whole history, and those get slower every year while nobody is watching.
The reference database holds a week, so nothing in the ordinary test run
says anything about this.

So: build an archive of a given length, with the daily summaries a real
one has, and render against it. The summaries matter more than anything
else here. `archive_day_outTemp` makes "the maximum in May" thirty rows
over a primary key; without it the same question reads a quarter of a
million rows, and a measurement taken that way describes a database no
station actually has.

    python tools/scaletest.py [years] [--keep] [--db PATH]

Ten years at five-minute readings is about a million rows. Put the
database somewhere the filesystem is quick: on a repository mounted into
WSL, writing it to the mount takes minutes and writing it to the Linux
side takes seconds, and the difference is the filesystem rather than
anything being measured here. `--db /tmp/scale.sdb` is the usual answer.

`--keep` leaves the database behind so the next run reuses it.
"""

from __future__ import annotations

import math
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import ClassVar

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

os.environ.setdefault("TZ", "Europe/Berlin")
if hasattr(time, "tzset"):
    time.tzset()

from weewx_evo.db.archive import ArchiveStore  # noqa: E402
from weewx_evo.feeds import cheetah  # noqa: E402
from weewx_evo.series import Reader  # noqa: E402

#: Five minutes, which is what most stations record at.
INTERVAL = 300

#: What a page is allowed to take before it is a problem. A feed runs on
#: its own thread, but everything on that thread waits behind it, and a
#: run that outlasts the archive interval never catches up.
BUDGET = {"index.html": 5.0, "week.html": 8.0, "month.html": 10.0,
          "year.html": 25.0, "statistics.html": 60.0,
          "celestial.html": 5.0}


class Counting(sqlite3.Connection):
    """A connection that counts its statements.

    The number matters as much as the seconds, and it is the more stable
    of the two. A page that asks the database a hundred thousand times is
    doing something wrong whatever the machine underneath it manages; the
    same page on a Raspberry Pi is slow for reasons that have nothing to
    say about the code.

    It caught the thing this file exists for. Charts over a long span used
    to cut it into a hundred equal buckets, which put every boundary in
    the middle of a day -- and `aggregate()` only reads the daily
    summaries for whole days, so each bar scanned ten thousand archive
    rows to produce one number the summary tables already held. The page
    looked right. It just asked 117,692 questions to draw it.
    """

    #: Statements since the last reset, as a one-element list so the
    #: instances and the module share it.
    tally: ClassVar[list[int]] = [0]

    def execute(self, *args, **kwargs):
        Counting.tally[0] += 1
        return super().execute(*args, **kwargs)


#: What a page may ask the database, at roughly half again what it asks
#: now. Generous on purpose: this is here to catch a page that has gone
#: back to scanning the archive record by record, not to hold anyone to a
#: particular query plan. The one it caught asked 117,692 times.
#:
#: The numbers only mean anything against the database this file builds,
#: which is why it builds one rather than measuring whatever is lying
#: around. A station with thirty sensors asks more; that is not a
#: regression.
QUERIES = {"index.html": 1800, "week.html": 2500, "month.html": 4000,
           "year.html": 1200, "statistics.html": 6000,
           "celestial.html": 400}


class Settings:
    def __init__(self, values: dict) -> None:
        self.values = values
        self.config: dict = {}

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def source(self, key: str) -> str:
        return "the configuration file" if key in self.values else "default"


def build(path: Path, years: int) -> None:
    """An archive of `years` years, with its daily summaries.

    Written through `ArchiveStore` rather than with a hand-rolled CREATE:
    that is what lays out the `archive_day_*` tables, and a database
    without them measures something else entirely.
    """
    store = ArchiveStore(str(path))
    # A database that exists to be measured against and thrown away. The
    # journal and the fsync per commit are what make writing a million
    # rows take minutes; neither protects anything here.
    store.conn.execute("PRAGMA journal_mode = OFF")
    store.conn.execute("PRAGMA synchronous = OFF")
    now = int(time.time())
    start = now - years * 365 * 86400

    print(f"  writing {years} years of readings at {INTERVAL}s ...",
          flush=True)
    began = time.time()
    written = 0
    when = start
    batch = []
    while when < now:
        day = (when - start) // 86400
        # A year of weather in two sine waves: warm in July, cold in
        # January, and a daily swing on top. Enough shape that the
        # aggregates have something to do.
        season = math.sin((day % 365) / 365.0 * 2 * math.pi - 1.9)
        hour = math.sin((when % 86400) / 86400.0 * 2 * math.pi - 1.9)
        batch.append((
            when, 17, INTERVAL // 60,
            round(10.0 + 12.0 * season + 5.0 * hour, 2),
            round(70.0 - 12.0 * hour, 1),
            round(1013.0 + 4.0 * season, 1),
            0.2 if (day % 7 == 3 and when % 86400 < 21600) else 0.0,
            round(1.5 + hour, 2), round(3.0 + 2.0 * hour, 2),
            (day * 13) % 360,
        ))
        when += INTERVAL
        if len(batch) >= 50_000:
            _flush(store, batch)
            written += len(batch)
            batch = []
    if batch:
        _flush(store, batch)
        written += len(batch)
    print(f"  {written:,} readings in {time.time() - began:.1f}s", flush=True)

    print("  building daily summaries ...", flush=True)
    began = time.time()
    day = start - start % 86400
    days = 0
    while day <= now:
        store.rebuild_day(day)
        days += 1
        day += 86400
    print(f"  {days:,} days in {time.time() - began:.1f}s", flush=True)


def _flush(store: ArchiveStore, batch: list) -> None:
    with store.conn:
        store.conn.executemany(
            "INSERT INTO archive (dateTime, usUnits, `interval`, outTemp,"
            " outHumidity, barometer, rain, windSpeed, windGust, windDir)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)


def render(database: Path, into: Path,
           every_page: bool = True) -> tuple[dict, dict, list]:
    """Render the skin and time each page.

    `every_page` forces the ones a running station skips: a month that is
    over cannot change, and a page with a `stale_age` is left alone while
    it is young enough. Both are the whole reason a ten-year archive does
    not cost ten years of work every five minutes, so the run is measured
    twice -- once as it actually behaves, and once with nothing skipped,
    which is what a fresh install or a changed template does.
    """
    reader = Reader(sqlite3.connect(f"file:{database}?mode=ro", uri=True,
                                    factory=Counting))
    feed = cheetah.from_settings(Settings({
        "language": "de",
        "station.latitude": 48.4596,
        "station.longitude": 11.6539,
        "station.altitude": 440.0,
        "station.name": "Scale test",
        "feeds.deck.skin": "deck",
        "feeds.deck.extras": {"base_path": "/"},
        "feeds.deck.stale_ok": not every_page,
    }), reader, (), prefix="feeds.deck")

    timings: dict[str, float] = {}
    asked: dict[str, int] = {}
    original = feed._one

    def timed(template, target, *args, **kwargs):
        began = time.time()
        before = Counting.tally[0]
        out = original(template, target, *args, **kwargs)
        timings[target.name] = timings.get(target.name, 0.0) + (
            time.time() - began)
        asked[target.name] = asked.get(target.name, 0) + (
            Counting.tally[0] - before)
        return out

    feed._one = timed
    began = time.time()
    feed.produce(into)
    timings["(whole run)"] = time.time() - began
    return timings, asked, feed.failed


def main(argv: list[str]) -> int:
    years = 10
    keep = "--keep" in argv
    for one in argv[1:]:
        if one.isdigit():
            years = int(one)

    database = Path(f".scaletest-{years}y.sdb")
    for index, one in enumerate(argv):
        if one == "--db" and index + 1 < len(argv):
            database = Path(argv[index + 1])
    if database.exists():
        print(f"reusing {database}")
    else:
        print(f"building {database}")
        build(database, years)

    out = Path(tempfile.mkdtemp(prefix="scale-"))
    second = Path(tempfile.mkdtemp(prefix="scale-again-"))
    try:
        print("\nfirst run: every page, which is a fresh install")
        timings, asked, failed = render(database, out, every_page=True)
        # The same directory again. Now the months that are over are
        # already written, which is what happens every five minutes on a
        # station that has been up for a while.
        print("second run: what a running station actually does")
        steady, _, more = render(database, out, every_page=False)
        failed = list(failed) + list(more)
    finally:
        shutil.rmtree(out, ignore_errors=True)
        shutil.rmtree(second, ignore_errors=True)
        if not keep:
            database.unlink(missing_ok=True)

    print()
    failures = []
    for name, why in failed:
        failures.append(f"{name} did not render: {why[:90]}")

    whole = timings.pop("(whole run)", 0.0)
    steady_whole = steady.pop("(whole run)", 0.0)
    print(f"{'page':<26} {'seconds':>9} {'queries':>9}   budget")
    for name, took in sorted(timings.items(), key=lambda kv: -kv[1])[:12]:
        budget = BUDGET.get(name)
        mark = ""
        if budget and took > budget:
            mark = f"  over {budget:.0f}s"
            failures.append(f"{name} took {took:.1f}s, budget {budget:.0f}s")
        elif budget:
            mark = f"  under {budget:.0f}s"
        print(f"{name:<26} {took:9.2f} {asked.get(name, 0):9,}{mark}")

    # The query count, which is the same on every machine and so the one
    # worth failing on.
    for name, limit in QUERIES.items():
        count = asked.get(name)
        if count is not None and count > limit:
            failures.append(f"{name} asked the database {count:,} times, "
                            f"budget {limit:,}")
    print(f"\n{'whole run, every page':<26} {whole:9.2f}")
    print(f"{'whole run, steady state':<26} {steady_whole:9.2f}")

    # A run that outlasts the archive interval never catches up: the next
    # one starts before this one has finished. The steady state is the one
    # that has to fit, because it runs every interval; a first build may
    # take longer, once.
    if steady_whole > 300:
        failures.append(f"a steady-state run took {steady_whole:.0f}s, "
                        "longer than a five-minute archive interval")

    for one in failures:
        print("  FAIL", one)
    print(f"\n{'FAIL' if failures else 'PASS'} ({len(failures)} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

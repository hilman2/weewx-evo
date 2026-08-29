#!/usr/bin/env python3
"""What the process publishes about itself, and what it must not.

Two halves.

**The format, against the grammar.** Prometheus does not report a malformed
exposition: it drops the scrape and the target goes stale, which looks exactly
like the process being down -- on the day somebody set this up. So every line
is parsed back here: a HELP and a TYPE before each metric, a name that matches
the character set, labels quoted and escaped, and a value that is a number.

**The figures, against their sources.** A metric is only worth having if it is
the same number the thing itself would give, so each is compared with the
database or the object it came from rather than with something typed in.

And one that is a decision rather than a check: **no weather is in here.**
Prometheus is for a value scraped, kept for weeks and reasoned about as a
rate. A reading is kept for fifteen years, is backfilled when a console
catches up, and is a measurement -- put it here and the result is a second,
worse archive that disagrees with the first. The test greps for it, because
this is the sort of line somebody adds meaning well.

    python tools/metrics_test.py
"""

from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
import urllib.request
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import units
from weewx_evo.db.archive import ArchiveStore
from weewx_evo.db.live import LiveStore, Packet
from weewx_evo.exports import record as export_record
from weewx_evo.metrics import Metrics

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def close_to(what: str, got: float | None, want: float, tol: float = 1.0) -> None:
    global CHECKS
    CHECKS += 1
    if got is None or abs(got - want) > tol:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


START = 1755648000
NOW = START + 7200

#: The names Prometheus accepts, and the same for a label.
NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
LABEL = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def parse(text: str) -> dict[str, list[tuple[dict[str, str], float]]]:
    """The exposition back into figures, strictly.

    Written out rather than split on spaces, because what is being checked is
    that the format is right -- a lenient parser here would accept exactly
    what Prometheus rejects.
    """
    found: dict[str, list] = {}
    helped: set[str] = set()
    typed: set[str] = set()

    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("# HELP "):
            helped.add(line.split(" ", 2)[2].split(" ", 1)[0])
            continue
        if line.startswith("# TYPE "):
            rest = line.split(" ", 2)[2]
            name, kind = rest.split(" ", 1)
            if kind.strip() not in ("gauge", "counter", "histogram",
                                    "summary", "untyped"):
                raise AssertionError(f"{name}: {kind!r} is not a metric type")
            typed.add(name)
            continue
        if line.startswith("#"):
            continue

        head, _, value = line.rpartition(" ")
        name, _, labels = head.partition("{")
        if not NAME.match(name):
            raise AssertionError(f"{name!r} is not a metric name")
        if name not in helped or name not in typed:
            raise AssertionError(f"{name} has no HELP or no TYPE before it")
        float(value)                       # raises where it is not a number

        parsed: dict[str, str] = {}
        if labels:
            for part in _split_labels(labels.rstrip("}")):
                key, _, one = part.partition("=")
                if not LABEL.match(key):
                    raise AssertionError(f"{key!r} is not a label name")
                if not (one.startswith('"') and one.endswith('"')):
                    raise AssertionError(f"{key}: label values must be quoted")
                parsed[key] = one[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        found.setdefault(name, []).append((parsed, float(value)))
    return found


def _split_labels(text: str) -> list[str]:
    """Commas that are not inside a quoted value."""
    parts, current, inside, escaped = [], [], False, False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char == '"':
            current.append(char)
            inside = not inside
        elif char == "," and not inside:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


def only(found: dict, name: str, **labels: str) -> float:
    for marks, value in found.get(name, []):
        if all(marks.get(k) == v for k, v in labels.items()):
            return value
    raise AssertionError(f"no {name} with {labels}")


# ---------------------------------------------------------------------------
# A station to measure.
# ---------------------------------------------------------------------------

_MADE: tuple[Path, Path] | None = None


def a_station() -> tuple[Path, Path]:
    """A live table and an archive, built once."""
    global _MADE
    if _MADE is not None:
        return _MADE

    where = Path(tempfile.mkdtemp())
    live_path, archive_path = where / "live.sdb", where / "weewx.sdb"

    with LiveStore(live_path) as live:
        # One station reporting every thirty seconds up to now, one that
        # stopped an hour ago.
        for index in range(40):
            live.add(Packet(dateTime=int(NOW - index * 30),
                            usUnits=units.METRICWX,
                            data={"outTemp": 20.0}, source="haus"))
        for index in range(20):
            live.add(Packet(dateTime=int(NOW - 3600 - index * 60),
                            usUnits=units.METRICWX,
                            data={"outTemp": 19.0}, source="schuppen"))
        export_record.write(live, "site", error="refused", when=NOW - 300)
        export_record.write(live, "site", error="refused", when=NOW - 100)

    store = ArchiveStore(archive_path)
    try:
        store.add_records([
            {"dateTime": int(NOW - index * 300), "usUnits": units.METRICWX,
             "interval": 5, "outTemp": 20.0}
            for index in range(48, 0, -1)])
        store.conn.commit()
    finally:
        store.close()

    _MADE = (live_path, archive_path)
    return _MADE


def some_metrics(**kw: object) -> Metrics:
    live_path, archive_path = a_station()
    settings: dict = {"live": live_path, "archives": {"default": archive_path},
                      "senders": ["site"], "station_name": "Kirchdorf",
                      "started": NOW - 600}
    settings.update(kw)
    return Metrics(**settings)


# ---------------------------------------------------------------------------
# The format.
# ---------------------------------------------------------------------------

def test_it_parses_as_an_exposition() -> None:
    """Prometheus drops a malformed scrape, and the target goes stale.

    Which looks exactly like the process being down, on the day somebody set
    this up.
    """
    found = parse(some_metrics().render(NOW))
    check("something was measured", len(found) > 5, True)
    check("and it ends with a newline",
          some_metrics().render(NOW).endswith("\n"), True)


def test_a_label_with_a_quotation_mark_survives() -> None:
    """A station is called whatever somebody typed."""
    live_path, _archive = a_station()
    with LiveStore(live_path) as live:
        live.add(Packet(dateTime=int(NOW - 10), usUnits=units.METRICWX,
                        data={"outTemp": 20.0},
                        source='Kirchdorf "old"'))
    found = parse(some_metrics().render(NOW))
    names = {marks.get("station")
             for marks, _v in found["weewx_evo_station_last_seen_seconds"]}
    check("the name comes back whole", 'Kirchdorf "old"' in names, True)


def test_every_metric_is_named_and_typed() -> None:
    """A sample with no HELP or TYPE above it is what `parse` refuses."""
    text = some_metrics().render(NOW)
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name = line.split("{")[0].split(" ")[0]
            check(f"{name} has a HELP", f"# HELP {name} " in text, True)
            check(f"{name} has a TYPE", f"# TYPE {name} " in text, True)
            break


# ---------------------------------------------------------------------------
# The figures, against what they came from.
# ---------------------------------------------------------------------------

def test_the_archive_figures_are_the_archive() -> None:
    _live, archive_path = a_station()
    found = parse(some_metrics().render(NOW))

    with closing(sqlite3.connect(f"file:{archive_path}?mode=ro",
                                 uri=True)) as conn:
        rows, newest = conn.execute(
            "SELECT COUNT(*), MAX(dateTime) FROM archive").fetchone()

    check("the record count", only(found, "weewx_evo_archive_records",
                                   archive="default"), rows)
    close_to("and how old the newest is",
             only(found, "weewx_evo_newest_record_age_seconds",
                  archive="default"), NOW - newest)
    check("the file size is the file",
          only(found, "weewx_evo_archive_bytes", archive="default") >=
          archive_path.stat().st_size, True)


def test_a_station_that_stopped_shows_as_stopped() -> None:
    """With one console "something is arriving" says everything.

    With ten, the useful figure is which of them has gone quiet, and an
    average over all of them hides exactly that.
    """
    found = parse(some_metrics().render(NOW))
    close_to("the one still reporting",
             only(found, "weewx_evo_station_last_seen_seconds",
                  station="haus"), 0, tol=60)
    close_to("and the one that stopped an hour ago",
             only(found, "weewx_evo_station_last_seen_seconds",
                  station="schuppen"), 3600, tol=120)

    # Thirty seconds apart is two a minute.
    close_to("its rate is what it does",
             only(found, "weewx_evo_station_packets_per_minute",
                  station="haus"), 2.0, tol=0.5)


def test_a_failing_export_is_counted() -> None:
    """From what it wrote down, not from the runner.

    A metric that only worked while a runner was running would go quiet in
    the case it exists for.
    """
    found = parse(some_metrics().render(NOW))
    check("it is not ok", only(found, "weewx_evo_sender_ok", sender="site"), 0)
    check("and the run of failures is counted",
          only(found, "weewx_evo_sender_failures", sender="site"), 2)
    close_to("and dated", only(found, "weewx_evo_sender_last_run_seconds",
                               sender="site"), 100, tol=5)


def test_the_runners_report_whether_they_are_alive() -> None:
    class Dog:
        def threads(self):
            return {"feeds": True, "exports": False}

    found = parse(some_metrics(dog=Dog()).render(NOW))
    check("a living one", only(found, "weewx_evo_runner_alive",
                               runner="feeds"), 1)
    check("and one that has died",
          only(found, "weewx_evo_runner_alive", runner="exports"), 0)


def test_up_is_always_one() -> None:
    """Its absence is the alarm, not its value."""
    found = parse(some_metrics().render(NOW))
    check("up", only(found, "weewx_evo_up"), 1)
    close_to("and how long for", only(found, "weewx_evo_uptime_seconds"),
             600, tol=5)


# ---------------------------------------------------------------------------
# What must not be in it.
# ---------------------------------------------------------------------------

def test_no_weather_is_published() -> None:
    """A reading is kept for fifteen years and backfilled when a console
    catches up. Prometheus is for neither, and a second worse archive that
    disagrees with the first is what putting it here produces."""
    text = some_metrics().render(NOW).lower()
    # Only the sample lines: the help text is allowed to say the word.
    samples = "\n".join(one for one in text.splitlines()
                        if one and not one.startswith("#"))
    for word in ("outtemp", "humidity", "barometer", "rain", "wind",
                 "dewpoint", "celsius", "degree"):
        check(f"no {word} in the samples", word in samples, False)


def test_a_gatherer_that_throws_does_not_take_the_scrape() -> None:
    """The metrics that still work are how somebody finds out what is wrong."""

    class Broken:
        def threads(self):
            raise RuntimeError("no watchdog")

    text = some_metrics(dog=Broken()).render(NOW)
    found = parse(text)
    check("the rest came through", "weewx_evo_archive_records" in found, True)
    check("and the broken one is simply absent",
          "weewx_evo_runner_alive" in found, False)


def test_a_missing_database_is_not_an_error() -> None:
    """A split deployment has the archive on another machine."""
    text = Metrics(live=Path("/nonesuch/live.sdb"),
                   archives={"default": Path("/nonesuch/weewx.sdb")}).render(NOW)
    found = parse(text)
    check("it still answers", "weewx_evo_up" in found, True)
    check("without inventing an archive",
          "weewx_evo_archive_records" in found, False)


def test_nothing_leaks_a_descriptor() -> None:
    """Scraped every fifteen seconds, so a handle held per scrape is a leak
    with a schedule."""
    before = _descriptors()
    for _ in range(10):
        some_metrics().render(NOW)
    after = _descriptors()
    if before is None or after is None:
        check("it rendered", True, True)
        return
    check("no descriptors left behind", after <= before + 2, True)


def _descriptors() -> int | None:
    try:
        return len(list(Path("/proc/self/fd").iterdir()))
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Through the real server.
# ---------------------------------------------------------------------------

def test_it_is_served_at_slash_metrics() -> None:
    from weewx_evo.netaccess import Access
    from weewx_evo.webserver import Site, WebServer

    server = WebServer(Site({}), "127.0.0.1", 0, access=Access.parse("any"),
                       metrics=some_metrics())
    server.start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{server.port}/metrics", timeout=5) as answer:
            check("it answers", answer.status, 200)
            # The version matters: a scraper uses it to decide how to parse.
            check("as an exposition",
                  answer.headers.get("Content-Type"),
                  "text/plain; version=0.0.4; charset=utf-8")
            body = answer.read().decode("utf-8")
        found = parse(body)
        check("with figures in it", "weewx_evo_up" in found, True)
    finally:
        server.stop()


def main() -> int:
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
            except Exception as exc:  # a failing test is the finding
                FAILURES.append(f"{name} raised {type(exc).__name__}: {exc}")

    if FAILURES:
        print(f"{len(FAILURES)} of {CHECKS} checks failed:\n")
        for failure in FAILURES:
            print(f"  {failure}\n")
        return 1
    print(f"metrics: {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

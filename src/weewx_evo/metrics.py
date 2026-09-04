"""What the process is doing, in the format Prometheus reads.

Everything here is already measured. The watchdog counts descriptors and
threads and knows when the archiver last went round; the export runners write
how their last attempt went into `live_metadata`; the live table knows when
each station was last heard from. None of it was anywhere a monitoring system
could see, so the only way to know whether an installation was healthy was to
open a page and look.

    GET /metrics

## The weather is not in here

Deliberately, and it is the decision worth writing down. Prometheus is built
for a value that is scraped, kept for weeks and reasoned about as a rate. A
weather reading is kept for fifteen years, has to be backfilled when a console
catches up, and is a measurement rather than a counter -- put it here and the
result is a second, worse archive that silently disagrees with the first.

Prometheus gets the **process**. Grafana gets the weather, out of the archive
or out of InfluxDB. `docs/Grafana.md` has the same split written from the
other side.

## What a metric costs

Every figure here is either already in memory or one indexed query. A
`/metrics` endpoint that is expensive to answer becomes a thing that is
scraped every fifteen seconds and makes the problem it is meant to report --
so a station's packet rate comes from one grouped query against a table
holding a day, not from counting rows over the retention period.

## The names

`weewx_evo_` throughout, `_seconds` and `_bytes` suffixed as Prometheus asks,
and a `_total` only where the number really only goes up. Nothing is invented
twice: `station` and `archive` are the labels the rest of this program uses,
so a query written against these reads like the configuration file.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import placement, watchdog

log = logging.getLogger(__name__)

#: How far back a packet rate is measured. Long enough to be steady, short
#: enough to notice a station stopping within a scrape or two.
WINDOW = 900


@dataclass
class Metric:
    """One figure, with what it means."""

    name: str
    help: str
    kind: str = "gauge"
    samples: list[tuple[dict[str, str], float]] = field(default_factory=list)

    def add(self, value: float, **labels: str) -> None:
        self.samples.append((dict(labels), float(value)))

    def render(self) -> str:
        if not self.samples:
            return ""
        lines = [f"# HELP {self.name} {self.help}",
                 f"# TYPE {self.name} {self.kind}"]
        for labels, value in self.samples:
            marked = ",".join(f'{key}="{_escape(one)}"'
                              for key, one in sorted(labels.items()))
            lines.append(f"{self.name}{{{marked}}} {_number(value)}"
                         if marked else f"{self.name} {_number(value)}")
        return "\n".join(lines)


def _escape(value: str) -> str:
    """A label value. Backslash, quote and newline are the three that break
    the line format."""
    return (str(value).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", " "))


def _number(value: float) -> str:
    """Prometheus takes a bare float. An integer prints as one."""
    if value != value or value in (float("inf"), float("-inf")):
        return "NaN"
    return str(int(value)) if float(value).is_integer() else repr(float(value))


class Metrics:
    """Everything the process knows about itself, on demand.

    Holds no connection, for the reason `api.py` holds none: this answers a
    scrape every fifteen seconds, and a pool of long-lived SQLite handles is
    the shape that once took an instance down with 477 descriptors.
    """

    def __init__(self, live: Path | None = None,
                 archives: dict[str, Path] | None = None,
                 dog: Any = None, senders: Any = None,
                 station_name: str = "", started: float | None = None,
                 stations: Any = None) -> None:
        self.live = Path(live) if live else None
        self.archives = dict(archives or {})
        self.dog = dog
        self.senders = list(senders or [])
        self.station_name = station_name
        #: The announced consoles, so a series is labelled with the name
        #: somebody chose rather than with a PASSKEY. The table records the
        #: pair a console uploads with; the name is a lookup, and one this
        #: does not have to make means a dashboard whose labels change the
        #: day a station is renamed.
        self.stations = stations
        self.started = started if started is not None else time.time()

    def render(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        out = []
        for gather in (self._process, self._threads, self._live,
                       self._archives, self._stations, self._sending):
            try:
                out.extend(gather(now))
            except Exception:
                # A metric that cannot be gathered must not take the scrape
                # with it: the ones that still work are how somebody finds
                # out what is wrong.
                log.debug("a metric could not be gathered", exc_info=True)
        return "\n".join(one.render() for one in out if one.render()) + "\n"

    # -- the process ------------------------------------------------------

    def _process(self, now: float) -> list[Metric]:
        up = Metric("weewx_evo_up",
                    "1 when the process is answering. Always 1 here -- the "
                    "absence of this line is the alarm.")
        up.add(1)

        since = Metric("weewx_evo_uptime_seconds",
                       "How long this process has been running.")
        since.add(now - self.started)

        out = [up, since]

        open_now = watchdog.descriptors_open()
        limit = watchdog.descriptor_limit()
        if open_now is not None:
            one = Metric("weewx_evo_open_descriptors",
                         "File descriptors this process holds. Rising "
                         "steadily is a leak; the watchdog restarts on it.")
            one.add(open_now)
            out.append(one)
        if limit is not None:
            one = Metric("weewx_evo_descriptor_limit",
                         "The limit those are counted against.")
            one.add(limit)
            out.append(one)
        return out

    def _threads(self, _now: float) -> list[Metric]:
        """Which runners are alive. A dead one never comes back on its own."""
        if self.dog is None:
            return []
        alive = Metric("weewx_evo_runner_alive",
                       "1 while a runner's thread is alive. A runner that has "
                       "died does not restart itself.")
        for name, living in sorted(self.dog.threads().items()):
            alive.add(1 if living else 0, runner=name)
        return [alive] if alive.samples else []

    def _live(self, now: float) -> list[Metric]:
        """The packet table: how much is in it, and how fresh."""
        if self.live is None or not self.live.exists():
            return []
        held = Metric("weewx_evo_live_packets",
                      "Packets in the live table. It holds the retention "
                      "period, so this is steady on a working station.")
        age = Metric("weewx_evo_newest_packet_age_seconds",
                     "How long ago any station last sent anything. The one "
                     "figure that says the whole ingest has stopped.")
        size = Metric("weewx_evo_live_bytes",
                      "What the live database takes on disk.")

        with closing(sqlite3.connect(f"file:{self.live}?mode=ro",
                                     uri=True)) as conn:
            held.add(conn.execute("SELECT COUNT(*) FROM packet").fetchone()[0])
            newest = conn.execute(
                "SELECT MAX(dateTime) FROM packet").fetchone()[0]
        if newest:
            age.add(now - float(newest))
        size.add(_bytes_of(self.live))
        return [held, age, size]

    def _archives(self, now: float) -> list[Metric]:
        """One line per series: how many records, and how old the newest is."""
        count = Metric("weewx_evo_archive_records",
                       "Records in an archive.")
        age = Metric("weewx_evo_newest_record_age_seconds",
                     "How long ago an archive last gained a record. More "
                     "than a couple of intervals means the archiver has "
                     "stopped, or nothing is arriving to archive.")
        size = Metric("weewx_evo_archive_bytes",
                      "What an archive takes on disk.")

        for name, where in sorted(self.archives.items()):
            if not Path(where).exists():
                continue
            with closing(sqlite3.connect(f"file:{where}?mode=ro",
                                         uri=True)) as conn:
                rows, newest = conn.execute(
                    "SELECT COUNT(*), MAX(dateTime) FROM archive").fetchone()
            count.add(rows or 0, archive=name)
            if newest:
                age.add(now - float(newest), archive=name)
            size.add(_bytes_of(Path(where)), archive=name)
        return [count, age, size]

    def _stations(self, now: float) -> list[Metric]:
        """Per station, because "something is arriving" is not the question.

        With one console the ingest metric above says everything. With ten,
        the useful figure is which of them has gone quiet -- and an average
        over all of them hides exactly that.
        """
        if self.live is None or not self.live.exists():
            return []
        heard = Metric("weewx_evo_station_last_seen_seconds",
                       "How long ago each station last sent a packet.")
        rate = Metric("weewx_evo_station_packets_per_minute",
                      "How often each station is reporting, over the last "
                      "fifteen minutes.")

        with closing(sqlite3.connect(f"file:{self.live}?mode=ro",
                                     uri=True)) as conn:
            columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(packet)")}
            directory = bool(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'sender_identity'").fetchone())
            if "sender" in columns and directory:
                latest = conn.execute(
                    "SELECT p.sender, COALESCE(NULLIF(s.label, ''), p.sender), "
                    "MAX(p.dateTime) FROM packet AS p LEFT JOIN sender_identity AS s "
                    "ON s.sender = p.sender GROUP BY p.sender")
                recent = conn.execute(
                    "SELECT p.sender, COALESCE(NULLIF(s.label, ''), p.sender), "
                    "COUNT(*) FROM packet AS p LEFT JOIN sender_identity AS s "
                    "ON s.sender = p.sender WHERE p.dateTime > ? GROUP BY p.sender",
                    (now - WINDOW,))
            else:
                # Rolling upgrade: the already-open service migrates the
                # table, but a read-only scrape may reach an older copy.
                latest = ((driver, placement.name_for(
                    self.stations, driver, identity), last)
                    for driver, identity, last in conn.execute(
                        "SELECT driver, identity, MAX(dateTime) FROM packet "
                        "GROUP BY driver, identity"))
                recent = ((driver, placement.name_for(
                    self.stations, driver, identity), seen)
                    for driver, identity, seen in conn.execute(
                        "SELECT driver, identity, COUNT(*) FROM packet "
                        "WHERE dateTime > ? GROUP BY driver, identity",
                        (now - WINDOW,)))

            for _sender, source, last in latest:
                if source:
                    heard.add(now - float(last or 0), station=source)
            # One grouped query over a window, not a count over the whole
            # retention period: this is answered every scrape.
            for _sender, source, seen in recent:
                if source:
                    rate.add(seen * 60.0 / WINDOW, station=source)
        return [heard, rate]

    def _sending(self, now: float) -> list[Metric]:
        """Exports and uploads, from what they wrote down about their last run.

        Read from `live_metadata` rather than from the runners: the settings
        page reads the same rows, and a metric that only worked while a
        runner was running would go quiet in the case it exists for.
        """
        if self.live is None or not self.live.exists() or not self.senders:
            return []
        from .db.live import LiveStore
        from .exports import record as export_record

        ok = Metric("weewx_evo_sender_ok",
                    "1 if an export or upload's last run succeeded.")
        when = Metric("weewx_evo_sender_last_run_seconds",
                      "How long ago it last ran at all.")
        failures = Metric("weewx_evo_sender_failures",
                          "How many runs in a row have failed. One is a "
                          "network; three is a password.")
        seconds = Metric("weewx_evo_sender_duration_seconds",
                         "How long its last run took.")

        with LiveStore(self.live) as store:
            for name in sorted(self.senders):
                entry = export_record.read(store, name)
                if not entry:
                    continue
                ok.add(1 if entry.get("ok") else 0, sender=name)
                if entry.get("when"):
                    when.add(now - float(entry["when"]), sender=name)
                failures.add(int(entry.get("failures") or 0), sender=name)
                if entry.get("seconds") is not None:
                    seconds.add(float(entry["seconds"]), sender=name)
        return [ok, when, failures, seconds]


def _bytes_of(path: Path) -> int:
    """A database and the two files that belong to it.

    The `-wal` counts: a station whose disk fills is filled by all three, and
    a figure that leaves it out is the one that looks fine until it is not.
    """
    total = 0
    for suffix in ("", "-wal", "-shm"):
        beside = Path(str(path) + suffix)
        try:
            total += beside.stat().st_size
        except OSError:
            pass
    return total


def descriptors_of_this_process() -> int | None:
    """Exposed for a test. `watchdog` owns the real one."""
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None

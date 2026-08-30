"""What is worth waking somebody for.

A closed list, and staying closed is the design. Every entry here is a thing
that means *this installation has stopped doing what it was doing*, and can
be established from two facts the process already has: what is in the live
database, and what the runners wrote down about their last attempt.

    station_silent   a console has not sent anything for too long
    battery          a transmitter is reporting a flat battery
    sending          an export or an upload has been failing for a while
    restarted        the watchdog restarted this process, and why
    heartbeat        the archiver's loop has stopped going round

**Nothing about the weather.** A frost warning is a matter of taste and a
threshold somebody wants to change without restarting anything, which is what
Grafana's alerting is for. Mixing the two would also mean the message that
says the station is dead arrives in the same inbox as the one that says it is
cold, and the first is the one that has to be noticed.

**And nothing that fails when somebody else's equipment is off.** Same rule
as `watchdog.py`, and for the same reason: a check that goes red when a
console is unplugged for the winter is a check people learn to ignore. So a
station that has *never* been heard from is not silent -- it is unconfigured,
and the settings page is where that belongs.

## Silence is measured against the station's own rhythm

A console uploading every sixteen seconds and one uploading every five
minutes cannot share a threshold. Six missed reports is late for the first
and a bad afternoon for the second, so the rule is a multiple of what that
station actually does, worked out from its own packets, with the configured
figure as a floor.
"""

from __future__ import annotations

import logging
import time
from itertools import pairwise
from typing import Any

from . import Event

log = logging.getLogger(__name__)

#: How many of a station's own intervals it may miss before it is silent.
#: Three, because two is one missed upload and a retry.
MISSED = 3.0

#: Where a station's rhythm cannot be worked out -- too few packets -- this
#: stands in. The archive interval, which every installation has.
DEFAULT_RHYTHM = 300.0

#: Fields a console uses to say a transmitter needs a new battery. Non-zero
#: means trouble in all of them, which is the convention every one of these
#: protocols follows.
BATTERY_FIELDS = ("txBatteryStatus", "outTempBatteryStatus",
                  "windBatteryStatus", "rainBatteryStatus",
                  "uvBatteryStatus", "inTempBatteryStatus",
                  "referenceVoltage", "batteryStatus1", "batteryStatus2",
                  "batteryStatus3", "batteryStatus4", "batteryStatus5",
                  "batteryStatus6", "batteryStatus7", "batteryStatus8")

#: How many runs in a row an export or upload has to fail before it is worth
#: saying. One failure is a network; three is a password.
FAILURES = 3


def measured_rhythm(conn: Any, source: str, now: float) -> float | None:
    """The median gap between one station's packets, or None where there
    are too few to say.

    Split out from `rhythm` below so the live document can publish the same
    figure the alarms judge by. One measurement, two callers: a second median
    over the same packets would be two numbers disagreeing about one console,
    and the disagreement would be between the badge on a page and the message
    in somebody's inbox.

    None rather than a default, because the two callers want different things
    from "cannot say": the alarm wants a threshold it can still use, and the
    page wants to publish nothing rather than publish a constant dressed as a
    measurement.
    """
    try:
        rows = conn.execute(
            "SELECT dateTime FROM packet WHERE source = ? "
            "AND dateTime > ? ORDER BY dateTime DESC LIMIT 30",
            (source, now - 6 * 3600)).fetchall()
    except Exception:
        log.debug("could not measure the rhythm of %r", source, exc_info=True)
        return None

    stamps = [float(row[0]) for row in rows]
    if len(stamps) < 4:
        return None
    gaps = sorted(a - b for a, b in pairwise(stamps))
    return max(1.0, gaps[len(gaps) // 2])


def rhythm(live: Any, source: str, now: float) -> float:
    """How often this station usually sends, in seconds.

    Measured rather than configured. A console reporting every sixteen
    seconds and one reporting every five minutes both exist, often on the
    same installation, and a single threshold is wrong for one of them.

    The median gap rather than the mean: a station that was off for an hour
    this morning would otherwise look like one that reports hourly, and would
    then be given an hour of silence before anybody heard about it.
    """
    found = measured_rhythm(live.conn, source, now)
    return DEFAULT_RHYTHM if found is None else found


def stations_silent(live: Any, stations: Any, floor: float = 900.0,
                    now: float | None = None) -> dict[str, Event]:
    """Configured stations that have stopped sending.

    Only configured ones. A stranger that turns up and goes away again is
    what the sightings list is for, and alerting on it would mean the
    neighbour's console reaching this network at the wrong moment wakes
    somebody up.
    """
    now = time.time() if now is None else now
    found: dict[str, Event] = {}
    names = [one.name for one in getattr(stations, "all", list)()]
    if not names:
        return found

    try:
        marks = ",".join("?" * len(names))
        rows = live.conn.execute(
            f"SELECT source, MAX(dateTime) FROM packet "
            f"WHERE source IN ({marks}) GROUP BY source", names).fetchall()
    except Exception:
        log.debug("could not read when stations were last heard", exc_info=True)
        return found

    heard = {row[0]: float(row[1] or 0) for row in rows}
    for name in names:
        last = heard.get(name, 0.0)
        if not last:
            # Never heard from at all. That is a station somebody has just
            # added, or one whose token is wrong, and both belong on the
            # settings page rather than in somebody's night.
            continue
        allowed = max(floor, rhythm(live, name, now) * MISSED)
        quiet = now - last
        if quiet <= allowed:
            continue
        found[f"station_silent:{name}"] = Event(
            kind="station_silent", subject=name,
            text=(f"{name} has sent nothing for {_spell(quiet)} "
                  f"(it usually reports every {_spell(allowed / MISSED)})"),
            since=last + allowed, severity="warning")
    return found


def batteries_flat(live: Any, stations: Any,
                   now: float | None = None) -> dict[str, Event]:
    """Transmitters reporting a flat battery, from the newest packet each.

    The newest packet rather than the archive, because a console reports this
    in every packet and the archive record is an average -- and an average of
    a status flag is not a status.
    """
    now = time.time() if now is None else now
    found: dict[str, Event] = {}
    names = [one.name for one in getattr(stations, "all", list)()]
    if not names:
        return found

    for name in names:
        try:
            packets = list(live.packets(now - 3600, now, sources=[name]))
        except Exception:
            log.debug("could not read packets for %r", name, exc_info=True)
            continue
        if not packets:
            continue
        newest = packets[-1].record()
        flat = sorted(field for field in BATTERY_FIELDS
                      if _flat(newest.get(field)))
        if not flat:
            continue
        found[f"battery:{name}"] = Event(
            kind="battery", subject=name,
            text=(f"{name} reports a flat battery: {', '.join(flat)}"),
            since=float(newest.get("dateTime") or now), severity="warning")
    return found


def sending_failing(live: Any, names: Any = None,
                    now: float | None = None) -> dict[str, Event]:
    """Exports and uploads that keep being refused.

    Read from `live_metadata`, which is where the runners write what their
    last attempt did -- the settings page reads the same rows. A command that
    asked the runners directly would only work while they are running, and
    the case this is for is the one where something has stopped.
    """
    from ..exports import record as export_record

    now = time.time() if now is None else now
    found: dict[str, Event] = {}
    for name in sorted(names or []):
        entry = export_record.read(live, name)
        if not entry or entry.get("ok"):
            continue
        failures = int(entry.get("failures") or 1)
        if failures < FAILURES:
            # One failure is a network having a moment. Three in a row is
            # something somebody has to change.
            continue
        error = str(entry.get("error") or "").strip() or "refused"
        found[f"sending:{name}"] = Event(
            kind="sending", subject=name,
            text=f"{name} has failed {failures} times: {error[:160]}",
            since=float(entry.get("since") or entry.get("when") or now),
            severity="warning")
    return found


def process_unwell(dog: Any, now: float | None = None) -> dict[str, Event]:
    """What the watchdog knows: a restart, and a loop that has stopped.

    The restart is reported *after* the fact, because a process that is about
    to end cannot wait for an SMTP handshake. The watchdog writes the time
    down before it acts -- that write is what this reads on the way back up.
    """
    now = time.time() if now is None else now
    found: dict[str, Event] = {}
    if dog is None:
        return found

    try:
        last = float(dog.last_restart() or 0)
    except Exception:
        last = 0.0
    # Only a recent one. An installation that restarted in March does not
    # need telling in August, and the log has it either way.
    if last and now - last < 3600:
        found["restarted"] = Event(
            kind="restarted", subject="",
            text=("weewx-evo restarted itself because something was wrong "
                  "that a restart fixes. The log says which."),
            since=last, severity="warning")

    try:
        symptoms = [one for one in dog.symptoms() if "loop" in one]
    except Exception:
        symptoms = []
    if symptoms:
        found["heartbeat"] = Event(
            kind="heartbeat", subject="", text="; ".join(symptoms),
            since=now, severity="critical")
    return found


def everything(live: Any, stations: Any = None, dog: Any = None,
               senders: Any = None, floor: float = 900.0,
               now: float | None = None) -> dict[str, Event]:
    """Every symptom, right now. Anything that raises is skipped, not fatal.

    A check that throws must not take the others with it: the one that still
    works is the one that says the station has gone quiet, and that is the
    message worth having.
    """
    now = time.time() if now is None else now
    found: dict[str, Event] = {}
    for what in (
        lambda: stations_silent(live, stations, floor, now) if stations else {},
        lambda: batteries_flat(live, stations, now) if stations else {},
        lambda: sending_failing(live, senders, now),
        lambda: process_unwell(dog, now),
    ):
        try:
            found.update(what())
        except Exception:
            log.exception("a notification check failed; carrying on")
    return found


def _flat(value: Any) -> bool:
    """Whether a battery field is saying what it says when it is flat."""
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _spell(seconds: float) -> str:
    """A duration somebody reads on a phone at four in the morning."""
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    if seconds < 5400:
        return f"{seconds / 60:.0f} minutes"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 86400:.1f} days"

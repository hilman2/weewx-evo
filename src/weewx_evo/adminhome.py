"""The overview: the chain, and where it is stuck.

The settings page used to open on a form. That was right when there were a
dozen settings and one of everything; it stopped being right somewhere around
the second archive. Somebody arriving at this page almost never wants to
change a value. They want to know whether it is working -- and if it is not,
which link in the chain stopped.

So the page is the chain, in the order things move through it:

    stations -> live table -> archives -> feeds -> exports and uploads

Each one says the number that matters and how old it is, and links to where
it is configured. A gap shows up as a link that is stale while the one before
it is fresh, which is exactly how you find the stuck component.

## Nothing is asked of a running process

Every number here is read off a file or a database, never off an object in
memory. That is not tidiness: the settings page may be its own process
(`weewx-evo admin`), and in a split deployment the archiver is on another
machine. A dashboard that only worked when it shared a process with the
listener would be a dashboard that stops working exactly when somebody has
gone to the trouble of splitting things up.

Where a number cannot be read, the page says so rather than showing zero. A
zero is a fact about the weather station; "not reachable from here" is a fact
about the deployment, and the two must not look the same.

## Age, not timestamps

`1787917500` is not an answer to "is it working". Everything is rendered as
"12 s ago", and the thresholds are comparisons rather than clocks: an archive
is behind when it is older than *the packets*, not when it is older than some
number of minutes. A station that has been switched off makes both old, and
that is not the archiver's fault.
"""

from __future__ import annotations

import html
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import adminarchives
from . import archives as archive_defs
from . import config as config_file
from . import stations as station_defs

log = logging.getLogger(__name__)

NEWLINE = "\n"

#: How far behind the archive may fall before it is worth saying. Three
#: intervals: one is normal (the interval has not closed), two is a slow
#: machine, three is something wrong.
BEHIND_INTERVALS = 3

#: How many intervals may pile up unarchived before that is a symptom rather
#: than a busy minute.
PENDING_LIMIT = 5


def ago(when: float | None) -> str:
    """How long ago, in words. The only time format on this page."""
    if not when:
        return "never"
    gap = max(0, int(time.time() - when))
    if gap < 90:
        return f"{gap} s ago"
    if gap < 5400:
        return f"{gap // 60} min ago"
    if gap < 172800:
        return f"{gap // 3600} h ago"
    return f"{gap // 86400} d ago"


@dataclass
class Link:
    """One step in the chain, as the page shows it."""

    name: str
    detail: str = ""
    when: float | None = None
    #: Set when this step cannot be read from here at all -- a split
    #: deployment, a database this process has no path to. Distinct from
    #: "nothing has happened yet", which is a fact about the station.
    unreachable: str = ""
    href: str = ""


@dataclass
class State:
    """Everything the overview knows, gathered once."""

    stations: list[Link] = field(default_factory=list)
    live: Link | None = None
    archives: list[Link] = field(default_factory=list)
    feeds: list[Link] = field(default_factory=list)
    exports: list[Link] = field(default_factory=list)
    uploads: list[Link] = field(default_factory=list)
    forecasts: list[Link] = field(default_factory=list)
    #: What is wrong, in the order somebody should deal with it.
    concerns: list[str] = field(default_factory=list)
    #: Numbers the concern rules need, kept rather than recomputed.
    newest_packet: float | None = None
    newest_record: float | None = None
    pending: int = 0
    interval: int = 300
    strangers: int = 0


# -- reading the state -------------------------------------------------


def _base(admin: Any) -> Path:
    return Path(admin.path).parent


def _resolve(admin: Any, where: str | None, fallback: str) -> Path:
    """A configured path, against the settings file rather than the cwd.

    The same rule everything else here follows. Read from the wrong
    directory, a container answers about a file inside its own image.
    """
    path = Path(str(where or fallback))
    return path if path.is_absolute() else _base(admin) / path


def _live_state(admin: Any, state: State) -> None:
    current = admin.config()
    path = _resolve(admin, config_file.get(current, "live_db"), "data/live.sdb")
    if not path.exists():
        state.live = Link("Live table", unreachable=f"no database at {path}",
                          href="./core")
        return
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        state.live = Link("Live table", unreachable=str(exc), href="./core")
        return
    try:
        count, newest = conn.execute(
            "SELECT count(*), max(dateTime) FROM packet").fetchone()
        state.pending = conn.execute(
            "SELECT count(DISTINCT stop) FROM pending").fetchone()[0]
        sources = [row[0] for row in conn.execute(
            "SELECT DISTINCT source FROM packet"
            " WHERE dateTime > ? ORDER BY source",
            (time.time() - 86400,))]
    except sqlite3.Error as exc:
        state.live = Link("Live table", unreachable=str(exc), href="./core")
        return
    finally:
        conn.close()

    state.newest_packet = newest
    size = path.stat().st_size / 1e6
    state.live = Link("Live table",
                      f"{count:,} packets, {size:.1f} MB, "
                      f"{state.pending} interval(s) waiting",
                      when=newest, href="./stations")

    announced = station_defs.load(_base(admin) / station_defs.FILENAME)
    known = {one.name for one in announced}
    state.strangers = len([one for one in sources if one not in known])
    for one in announced:
        last = _last_from(path, one.name)
        state.stations.append(Link(one.name, f"into {one.archive}", when=last,
                                   href="./stations"))
    if not announced and sources:
        state.stations.append(Link(
            f"{len(sources)} source(s), none announced",
            "they are writing under whatever identity their driver read",
            href="./stations"))


def _last_from(path: Path, source: str) -> float | None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT max(dateTime) FROM packet WHERE source = ?",
            (source,)).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _archive_state(admin: Any, state: State) -> None:
    register = adminarchives.load(admin)
    for one in register.all():
        path = _resolve(admin, one.file, "data/weewx.sdb")
        if not path.exists():
            state.archives.append(Link(
                one.title, unreachable=f"no file at {path} yet",
                href="./archives"))
            continue
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            count, newest = conn.execute(
                "SELECT count(*), max(dateTime) FROM archive").fetchone()
            conn.close()
        except sqlite3.Error as exc:
            state.archives.append(Link(one.title, unreachable=str(exc),
                                       href="./archives"))
            continue
        size = path.stat().st_size / 1e6
        state.archives.append(Link(
            one.title, f"{count:,} records, {size:.1f} MB", when=newest,
            href="./archives"))
        if newest and (state.newest_record is None
                       or newest > state.newest_record):
            state.newest_record = newest
    state.concerns.extend(
        f"Archive {name!r}: {said}"
        for name, said in register.concerns().items())


def _newest_file(where: Path) -> tuple[int, float | None]:
    """How many files a directory holds and when one was last written."""
    if not where.is_dir():
        return 0, None
    newest, count = None, 0
    for path in where.rglob("*"):
        if not path.is_file():
            continue
        count += 1
        try:
            when = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or when > newest:
            newest = when
    return count, newest


def _feed_state(admin: Any, state: State) -> None:
    current = admin.config()
    root = _resolve(admin, config_file.get(current, "feeds_dir"), "data/feeds")
    configured = current.get("feeds") or {}
    for name, settings in sorted(configured.items()):
        if not isinstance(settings, dict):
            continue
        if settings.get("enabled") is False:
            state.feeds.append(Link(name, "switched off", href=f"./feed:{name}"))
            continue
        where = str(settings.get("destination") or "").strip()
        directory = _resolve(admin, where, "") if where else root / name
        count, newest = _newest_file(directory)
        if not count:
            state.feeds.append(Link(
                name, unreachable=f"nothing written to {directory} yet",
                href=f"./feed:{name}"))
            continue
        reads = str(settings.get("archive") or archive_defs.DEFAULT)
        detail = f"{count} file(s)"
        if reads != archive_defs.DEFAULT:
            detail += f", from {reads}"
        state.feeds.append(Link(name, detail, when=newest,
                                href=f"./feed:{name}"))


def _sent_state(admin: Any, state: State) -> None:
    """Exports and uploads: both are 'did it leave the machine'."""
    current = admin.config()
    for name, settings in sorted((current.get("exports") or {}).items()):
        if not isinstance(settings, dict):
            continue
        if settings.get("enabled") is False:
            state.exports.append(Link(name, "switched off",
                                      href=f"./export:{name}"))
            continue
        # The tracker is written after a successful send, so its mtime is
        # when something last actually went out. Nothing else on disk knows.
        tracker = _resolve(admin, settings.get("state"),
                           f"data/exports/{name}.json")
        when = tracker.stat().st_mtime if tracker.exists() else None
        kind = str(settings.get("kind") or "")
        state.exports.append(Link(name, kind, when=when,
                                  href=f"./export:{name}"))

    progress = _resolve(admin, config_file.get(current, "archive_db"),
                        "data/weewx.sdb").parent / "uploads.json"
    through: dict[str, Any] = {}
    if progress.exists():
        try:
            import json

            through = (json.loads(progress.read_text(encoding="utf-8"))
                       .get("through") or {})
        except (OSError, ValueError):
            through = {}
    for name, settings in sorted((current.get("uploads") or {}).items()):
        if not isinstance(settings, dict):
            continue
        if settings.get("enabled") is False:
            state.uploads.append(Link(name, "switched off",
                                      href=f"./upload:{name}"))
            continue
        when = through.get(name)
        state.uploads.append(Link(name, str(settings.get("kind") or ""),
                                  when=when or None,
                                  href=f"./upload:{name}"))


def _forecast_state(admin: Any, state: State) -> None:
    current = admin.config()
    configured = current.get("forecasts") or {}
    if not configured:
        return
    path = _resolve(admin, config_file.get(current, "forecast_db"),
                    "data/forecast.sdb")
    if not path.exists():
        for name in sorted(configured):
            state.forecasts.append(Link(name, unreachable="not fetched yet",
                                        href=f"./forecast:{name}"))
        return
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return
    try:
        for name in sorted(configured):
            row = conn.execute(
                "SELECT max(fetched) FROM hour WHERE source = ?",
                (name,)).fetchone()
            when = row[0] if row else None
            state.forecasts.append(Link(name, "", when=when,
                                        href=f"./forecast:{name}"))
    except sqlite3.Error:
        log.debug("could not read the forecast state", exc_info=True)
    finally:
        conn.close()


def _judge(admin: Any, state: State) -> None:
    """What is wrong. Comparisons, not clocks.

    Every rule here compares two things this installation knows about itself.
    "The archive is older than ten minutes" would fire on a station that is
    switched off, which is not a fault. "The archive is older than the
    packets" fires only when packets are arriving and not being archived,
    which always is.
    """
    current = admin.config()
    state.interval = int(config_file.get(current, "interval") or 300)

    if not config_file.get(current, "token"):
        state.concerns.append(
            "No upload token is set, so anything that can reach the listener "
            "can write to the measurement series.")

    if state.newest_packet and state.newest_record is not None:
        behind = state.newest_packet - state.newest_record
        if behind > state.interval * BEHIND_INTERVALS:
            state.concerns.append(
                f"Readings are arriving but the archive is {ago(state.newest_record)}"
                f", {int(behind // 60)} min behind the newest packet. The "
                "archiver is not keeping up, or it is not running.")

    if state.pending > PENDING_LIMIT:
        state.concerns.append(
            f"{state.pending} interval(s) are waiting to be archived. One or "
            "two is an interval that has not closed; this many is a backlog.")

    if state.strangers:
        state.concerns.append(
            f"{state.strangers} source(s) are uploading that no station "
            "answers for. Their readings are in the live table and are not "
            "reaching any archive.")

    for one in state.archives:
        if one.unreachable:
            state.concerns.append(f"Archive {one.name!r}: {one.unreachable}")


def read(admin: Any) -> State:
    """Everything, gathered once. A failure in one part does not stop it."""
    state = State()
    for step in (_live_state, _archive_state, _feed_state, _sent_state,
                 _forecast_state):
        try:
            step(admin, state)
        except Exception:
            # A dashboard that shows nothing because one number could not be
            # read is worse than one with a gap in it. The gap is visible.
            log.exception("could not read part of the overview")
    try:
        _judge(admin, state)
    except Exception:
        log.exception("could not work out what is wrong")
    return state


# -- the page ----------------------------------------------------------


def nav(admin: Any, active: str) -> list[str]:
    current = " aria-current='page'" if active == "overview" else ""
    state = read(admin)
    mark = ""
    if state.concerns:
        mark = (f' <span class="warn" title="something needs looking at">'
                f'{len(state.concerns)}</span>')
    return [f'<a class="home" href="./overview"{current}>Overview{mark}</a>']


def _row(one: Link) -> str:
    if one.unreachable:
        when = f'<span class="note">{html.escape(one.unreachable)}</span>'
    else:
        when = html.escape(ago(one.when))
    detail = f'<span class="note">{html.escape(one.detail)}</span>' \
        if one.detail else ""
    name = html.escape(one.name)
    if one.href:
        name = f'<a href="{html.escape(one.href)}">{name}</a>'
    return f'''
    <tr><td>{name}</td><td>{detail}</td><td class="when">{when}</td></tr>'''


def _card(title: str, links: list[Link], empty: str, more: str = "") -> str:
    if not links:
        body = f'<p class="navempty">{html.escape(empty)}</p>'
    else:
        body = (f'<table class="chain">{NEWLINE.join(_row(o) for o in links)}'
                "</table>")
    tail = f'<p class="cardlink">{more}</p>' if more else ""
    return f'''
<section class="card">
  <h3>{html.escape(title)}</h3>
  {body}{tail}
</section>'''


def overview(admin: Any, message: str = "", error: str = "") -> str:
    state = read(admin)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    said = f'<p class="ok">{html.escape(message)}</p>' if message else ""

    trouble = ""
    if state.concerns:
        items = NEWLINE.join(f"<li>{html.escape(one)}</li>"
                             for one in state.concerns)
        trouble = f'''
<section class="banner warn">
  <h3>{len(state.concerns)} thing(s) to look at</h3>
  <ul>{items}</ul>
</section>'''

    live = [state.live] if state.live else []
    return f'''
<h2>Overview</h2>
{problem}{said}{trouble}
<p class="lede">Readings move left to right. A step that is old while the one
   before it is fresh is the one that stopped.</p>
<div class="cards">
{_card("Arriving", state.stations,
       "No station announced yet.",
       '<a href="./new-station">Add a station</a>')}
{_card("Held", live, "No live table here.")}
{_card("Archived", state.archives, "No archive.",
       '<a href="./archives">Archives</a>')}
{_card("Produced", state.feeds,
       "No feed is configured, so nothing is being written.",
       '<a href="./new-feed">Add a feed</a>')}
{_card("Sent", state.exports, "No export is configured.",
       '<a href="./new-export">Add an export</a>')}
{_card("Posted", state.uploads, "No upload is configured.",
       '<a href="./new-upload">Add an upload</a>')}
{_card("Forecast", state.forecasts, "No forecast is configured.",
       '<a href="./new-forecast">Add a forecast</a>')}
</div>
'''

"""The overview: what needs action, then the three data stages.

The settings page used to open on a form. That was right when there were a
dozen settings and one of everything; it stopped being right somewhere around
the second archive. Somebody arriving at this page almost never wants to
change a value. They want to know whether it is working -- and if it is not,
which link in the chain stopped.

So the page puts problems first, then the stable process the operator owns:

    intake -> places -> publishing

Each stage says what exists, how old its newest result is, and links to the
page that changes or diagnoses it. The archiver appears only through the data
it writes and any lag it leaves; it is never an object to configure here.

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
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import adminarchives, placement, series, units
from . import archives as archive_defs
from . import config as config_file
from . import language as language_defs
from . import stations as station_defs
from .exports import record as export_record

log = logging.getLogger(__name__)

NEWLINE = "\n"

#: How far behind the archive may fall before it is worth saying. Three
#: intervals: one is normal (the interval has not closed), two is a slow
#: machine, three is something wrong.
BEHIND_INTERVALS = 3

#: How many intervals may pile up unarchived before that is a symptom rather
#: than a busy minute.
PENDING_LIMIT = 5

#: How recently something must have uploaded to count as a stranger rather
#: than as history. A console announced under a new name leaves its old
#: packets behind for the whole retention period, and those are not a console
#: arriving unannounced -- they are the same console, before it was named.
STRANGER_WINDOW = 3600.0


#: How many hours of history the little charts show. A day: long enough
#: that a gap overnight is visible, short enough that each bar is an hour and
#: needs no axis.
HOURS = 24


def sparkline(counts: list[int], label: str) -> str:
    """A day of hourly counts, as bars. Inline SVG, no script.

    A number is a moment and this page is about whether something is still
    working -- and "it stopped at four this morning" is a different fact
    from "it is not working now", which a single figure cannot tell you.

    Drawn rather than charted: no axis, no grid, no legend. It is a shape,
    and the shape is the answer.
    """
    if not counts or not any(counts):
        return ""
    top = max(counts)
    wide, high, gap = 3.0, 22.0, 1.0
    bars = []
    for n, count in enumerate(counts):
        # A zero hour draws nothing, which is the point: a gap is a gap.
        if not count:
            continue
        length = max(1.5, high * count / top)
        bars.append(f'<rect x="{n * (wide + gap):.1f}" '
                    f'y="{high - length:.1f}" width="{wide:.1f}" '
                    f'height="{length:.1f}" rx="1"/>')
    width = len(counts) * (wide + gap)
    # `preserveAspectRatio="none"` so it stretches to the card rather than
    # being scaled to fit and centred -- the default left a hundred-pixel
    # strip in the middle of a three-hundred-pixel card. Bars have no aspect
    # ratio worth preserving: the height is the count and the width is time.
    return (f'<svg class="spark" viewBox="0 0 {width:.0f} {high:.0f}" '
            f'preserveAspectRatio="none" height="{high:.0f}" role="img" '
            f'aria-label="{html.escape(label)}">{"".join(bars)}</svg>')


def _hourly(conn: Any, table: str, column: str = "dateTime") -> list[int]:
    """How many rows fell in each of the last 24 hours, oldest first."""
    now = int(time.time())
    start = now - HOURS * 3600
    counts = [0] * HOURS
    try:
        rows = conn.execute(
            f"SELECT ({column} - ?) / 3600, count(*) FROM {table}"
            f" WHERE {column} > ? GROUP BY 1", (start, start))
    except sqlite3.Error:
        return []
    for bucket, count in rows:
        if 0 <= int(bucket) < HOURS:
            counts[int(bucket)] = count
    return counts


def ago(when: float | None, lang: Any = None) -> str:
    """How long ago, in words. The only time format on this page."""
    lang = lang if lang is not None else language_defs.get("en")
    if not when:
        return lang.say("never")
    gap = max(0, int(time.time() - when))
    if gap < 90:
        return lang.fill("{n} s ago", n=gap)
    if gap < 5400:
        return lang.fill("{n} min ago", n=gap // 60)
    if gap < 172800:
        return lang.fill("{n} h ago", n=gap // 3600)
    return lang.fill("{n} d ago", n=gap // 86400)


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
    #: Hourly counts for the last day, oldest first. Empty where there is
    #: nothing countable -- an export has no rows, only a last time.
    history: list[int] = field(default_factory=list)
    #: Whether `unreachable` is something wrong rather than something not
    #: started. "waiting for its first run" and "530 login incorrect" are
    #: both text in the same field, and only one of them is a problem.
    wrong: bool = False


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
    #: The settings or diagnostic page that can resolve each concern.
    #: Kept beside ``concerns`` so callers that inspect the messages remain
    #: independent of their presentation.
    concern_hrefs: list[str] = field(default_factory=list)
    #: Numbers the concern rules need, kept rather than recomputed.
    newest_packet: float | None = None
    newest_record: float | None = None
    pending: int = 0
    interval: int = 300
    strangers: int = 0
    newest_stranger: float | None = None


def _concern(state: State, said: str, href: str) -> None:
    """Add one actionable problem without hiding its plain-text form."""
    state.concerns.append(said)
    state.concern_hrefs.append(href)


# -- reading the state -------------------------------------------------


def _base(admin: Any) -> Path:
    return Path(admin.path).parent


def _setting(admin: Any, name: str, fallback: str) -> Path:
    """A configured path, as the process that writes it sees it.

    Through `config.resolved_path`, so the environment wins. A container sets
    `WEEWX_EVO_LIVE`, and reading the file alone gave `/data/data/live.sdb`
    on the running instance -- a page reporting confidently about a file that
    does not exist.
    """
    return config_file.resolved_path(admin.config(), name, _base(admin),
                                     fallback)


def _under(admin: Any, where: str | None, fallback: str) -> Path:
    """A path that is not a setting: a feed's destination, an archive's file."""
    path = Path(str(where or fallback))
    return path if path.is_absolute() else _base(admin) / path


def _default_archive_path(admin: Any) -> Path:
    """The archive declared as default in archives.toml."""
    archive = adminarchives.load(admin).get(None)
    return _under(admin, archive.file, "data/weewx.sdb")


def _selected_by(archive: Any, station: Any) -> bool:
    """Whether this place selects this announced station's live ID.

    ``None`` means all and an empty tuple means none. Keeping that test in
    one place prevents an empty selection from turning truthily into the old
    implicit default.
    """
    from .db.live import sender_id

    return archive.selects(sender_id(station.driver, station.identity))


class _ReadOnlyMeta:
    """Just enough of a store for `export_record.read`, and closable.

    Opened read-only, once per request, and closed on the way out. Not once
    per export: a page with six of them would open six connections and hand
    none of them back, which is the leak that took the VPS out -- three
    unrelated errors at once because the process had run out of descriptors.
    """

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def get_meta(self, name: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM live_metadata WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            log.debug("could not close the export record reader",
                      exc_info=True)


def _live_store(admin: Any) -> Any:
    path = _setting(admin, "live_db", "data/live.sdb")
    if not path.exists():
        return None
    try:
        return _ReadOnlyMeta(
            sqlite3.connect(f"file:{path}?mode=ro", uri=True))
    except sqlite3.Error:
        log.debug("could not open %s to read the export records", path,
                  exc_info=True)
        return None


def _live_state(admin: Any, state: State) -> None:
    lang = admin.language
    path = _setting(admin, "live_db", "data/live.sdb")
    if not path.exists():
        state.live = Link(lang.say("Live data"), href="./live",
                          unreachable=lang.fill("no database at {path}",
                                                path=path))
        return
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        state.live = Link(lang.say("Live data"), unreachable=str(exc),
                          href="./live")
        return
    try:
        count, newest = conn.execute(
            "SELECT count(*), max(dateTime) FROM packet").fetchone()
        state.pending = conn.execute(
            "SELECT count(DISTINCT stop) FROM pending").fetchone()[0]
        # Recently, not "in the last day". A console announced under a new
        # name leaves its old packets behind, and they stay for the whole
        # retention period -- so a day's window reported a stranger that had
        # stopped uploading sixteen hours earlier, and would have gone on
        # reporting it for a fortnight. A stranger is something arriving
        # now.
        heard = conn.execute(
            "SELECT driver, identity, max(dateTime) FROM packet"
            " WHERE dateTime > ? GROUP BY driver, identity ORDER BY driver, identity",
            (time.time() - STRANGER_WINDOW,)).fetchall()
        history = _hourly(conn, "packet")
    except sqlite3.Error as exc:
        state.live = Link(lang.say("Live data"), unreachable=str(exc),
                          href="./live")
        return
    finally:
        conn.close()

    state.newest_packet = newest
    size = path.stat().st_size / 1e6
    # Middle dots and short words: three columns in a card this wide have
    # room for a phrase, not a sentence.
    detail = " · ".join((lang.fill("{n} packets", n=f"{count:,}"),
                         f"{size:.1f} MB",
                         lang.fill("{n} waiting", n=state.pending)))
    state.live = Link(lang.say("Live data"), detail,
                      when=newest, href="./live", history=history)

    announced = station_defs.load(_base(admin) / station_defs.FILENAME)
    # Resolved through the register rather than read out of the table: the
    # name is not stored, so an adopted console is recognised here from the
    # first packet it ever sent rather than from the next one.
    sources = [(placement.name_for(announced, driver, identity), when)
               for driver, identity, when in heard]
    from .db.live import sender_id
    places_for_selection: list[Any] = []
    try:
        from . import adminarchives

        places_for_selection = adminarchives.load(admin).all()
    except Exception:
        log.debug("could not read sender selections", exc_info=True)
    strangers = [
        (name, when) for (driver, identity, when), (name, _same_when)
        in zip(heard, sources, strict=True)
        if not any(place.selects(sender_id(driver, identity))
                   for place in places_for_selection)]
    state.strangers = len(strangers)
    state.newest_stranger = max((w for _n, w in strangers), default=None)
    # Through the console page's own reader and the places register: a
    # console adopted from a stranger is named after the identity its
    # hardware sent, and the archive is a key. Both were readable on their
    # own pages and raw here.
    from . import adminstations

    places = places_for_selection
    for one in announced:
        last = _last_from(path, one.driver, one.identity)
        selected = [place.title for place in places
                    if _selected_by(place, one)]
        detail = (lang.fill("Used by {places}", places=", ".join(selected))
                  if selected else lang.say("Not assigned"))
        state.stations.append(Link(
            adminstations._readable(one.name),
            detail,
            when=last, href="./senders"))
    if not announced and sources:
        state.stations.append(Link(
            lang.fill("{n} unregistered sender(s)", n=len(sources)),
            lang.say("Not assigned"),
            href="./senders"))


def _last_from(path: Path, driver: str, identity: str) -> float | None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT max(dateTime) FROM packet WHERE driver = ? AND identity = ?",
            (driver, identity)).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


@dataclass
class Series:
    """One place, as every page that asks about places sees it.

    One pass and one shape, because the overview and the archives page want
    the same handful of numbers about the same file, and two implementations
    of "how many records" is two chances for the two pages to print
    different figures about it.
    """

    archive: Any                       # archives.Archive
    path: Path
    exists: bool = False
    count: int = 0
    newest: float | None = None
    size: float = 0.0
    #: "metricwx", "us", or empty where nothing has been recorded. A fact,
    #: and the fact behind the failure that already shipped: 68.2 printed on
    #: a page that said Celsius, and nothing anywhere said which unit the
    #: file held. Read the way `series.Reader` reads it, from the oldest
    #: record: a second answer to that question is how the page and the
    #: charts come to disagree about the same file.
    system: str = ""
    history: list[int] = field(default_factory=list)
    #: Set when the file cannot be read at all, as distinct from holding
    #: nothing yet. "no records" is a fact about the weather station;
    #: "no such table" is a fact about the file.
    unreachable: str = ""


def archives_state(admin: Any, register: Any = None) -> list[Series]:
    """Every place, read once.

    One read-only connection per place, opened and closed. Never kept on
    `admin`: that object lives as long as the process, and a map of open
    handles hanging off it is the same leak under a nicer name -- the one
    the store had against the live table, one connection per answered
    upload, until the watchdog was built to notice it.

    `contextlib.closing` as well as `with`: the context manager on a
    connection commits and leaves the connection *open*. And the close has
    to be a `finally` rather than a line after the statements, because the
    first statement raises on a file that exists with no `archive` table --
    which is exactly the state a place is in between being added and its
    first record, on a page somebody reloads after every save. One leaked
    descriptor per reload per empty place.

    `register` is passed in by a caller that already has one, so the archives
    page does not read and parse `archives.toml` twice per request.
    """
    register = register if register is not None else adminarchives.load(admin)
    found: list[Series] = []
    for one in register.all():
        path = _under(admin, one.file, "data/weewx.sdb")
        row = Series(archive=one, path=path, exists=path.exists())
        if not row.exists:
            found.append(row)
            continue
        try:
            row.size = path.stat().st_size / 1e6
        except OSError:
            pass
        try:
            with closing(sqlite3.connect(f"file:{path}?mode=ro",
                                         uri=True)) as conn:
                row.count, row.newest = conn.execute(
                    "SELECT count(*), max(dateTime) FROM archive").fetchone()
                if row.count:
                    # `series.Reader.system`, and not a query of this page's
                    # own. Every renderer takes the system from the *oldest*
                    # record, "which is what WeeWX's manager does"; reading
                    # the newest one here made this page print `metricwx`
                    # for a file every chart was converting as `us` -- on
                    # the one database where the question is interesting,
                    # which is the one whose station changed system.
                    row.system = units.name(
                        series.Reader(conn).system).lower()
                row.history = _hourly(conn, "archive")
        except (sqlite3.Error, ValueError, TypeError) as exc:
            # Not just `sqlite3.Error`: SQLite is dynamically typed, so a
            # `usUnits` holding 'US' raises out of `int()` here, and this
            # function answers both the overview and the archives page --
            # the two pages somebody would use to find that out.
            row.unreachable = str(exc)
        found.append(row)
    return found


def _archive_state(admin: Any, state: State) -> None:
    lang = admin.language
    register = adminarchives.load(admin)
    for row in archives_state(admin, register):
        one = row.archive
        if not row.exists:
            state.archives.append(Link(
                one.title, href="./places",
                unreachable=lang.fill("no file at {path} yet", path=row.path)))
            continue
        if row.unreachable:
            state.archives.append(Link(one.title, unreachable=row.unreachable,
                                       href="./places"))
            continue
        records = (lang.fill("{n} record", n=1) if row.count == 1
                   else lang.fill("{n} records", n=f"{row.count:,}"))
        state.archives.append(Link(
            one.title, f"{records} · {row.size:.1f} MB",
            when=row.newest, href="./places", history=row.history))
        if row.newest and (state.newest_record is None
                           or row.newest > state.newest_record):
            state.newest_record = row.newest
    for name, said in register.concerns().items():
        _concern(state, lang.fill("Place {name}: {why}",
                                  name=repr(name), why=said), "./places")


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
    root = _setting(admin, "feeds_dir", "data/feeds")
    configured = current.get("feeds") or {}
    try:
        register = adminarchives.load(admin)
        implicit = register.default_name()
    except LookupError:
        implicit = ""
    except Exception:
        log.debug("could not read the places for the feed cards", exc_info=True)
        implicit = ""
    for name, settings in sorted(configured.items()):
        if not isinstance(settings, dict):
            continue
        if settings.get("enabled") is False:
            state.feeds.append(Link(name, "switched off", href=f"./feed:{name}"))
            continue
        where = str(settings.get("destination") or "").strip()
        directory = _under(admin, where, "") if where else root / name
        count, newest = _newest_file(directory)
        if not count:
            state.feeds.append(Link(
                name, unreachable=f"nothing written to {directory} yet",
                href=f"./feed:{name}"))
            continue
        reads = str(settings.get("archive") or implicit).strip()
        detail = f"{count} file(s)"
        if not reads:
            detail += ", no place selected"
        elif reads != archive_defs.DEFAULT:
            detail += f", from {reads}"
        state.feeds.append(Link(name, detail, when=newest,
                                href=f"./feed:{name}"))


def _export_records(admin: Any, names: list[str]) -> dict[str, dict]:
    """What each export last did, read in one go and the file closed after.

    One connection for the page rather than one per export, and handed back
    either way: this runs on every request.
    """
    store = _live_store(admin)
    if store is None:
        return {}
    try:
        found = {}
        for name in names:
            entry = export_record.read(store, name)
            if entry:
                found[name] = entry
        return found
    finally:
        store.close()


def _sent_state(admin: Any, state: State) -> None:
    """Exports and uploads: both are 'did it leave the machine'."""
    current = admin.config()
    noted_by = _export_records(admin, list(current.get("exports") or {}))
    for name, settings in sorted((current.get("exports") or {}).items()):
        if not isinstance(settings, dict):
            continue
        if settings.get("enabled") is False:
            state.exports.append(Link(name, "switched off",
                                      href=f"./export:{name}"))
            continue
        kind = str(settings.get("kind") or "")
        detail = kind
        trouble = ""
        # What the runner wrote down after its last run, which is the only
        # answer there is about an export that publishes somewhere this
        # process cannot look at. Before it existed the page said "not
        # recorded here" about every FTP and rsync export -- honest, and no
        # use to somebody asking whether their upload is working.
        noted = noted_by.get(name)
        when = float(noted["when"]) if noted and noted.get("when") else None
        if noted:
            said = export_record.summary(noted)
            if not noted.get("ok"):
                trouble = said or "the last run failed"
            elif said:
                detail = f"{kind}, {said}"
        elif kind == "local":
            # Nothing written down yet, but a local export publishes into a
            # directory on this machine: the newest file in it is when
            # something last went out.
            where = str(settings.get("directory") or "").strip()
            if where:
                _count, when = _newest_file(_under(admin, where, ""))
        if when is None and kind:
            # Never run since this was recorded, which is not the same as
            # never run. Say what it is waiting for instead.
            waits = str(settings.get("trigger") or "feed")
            source = str(settings.get("source") or "").strip()
            detail = f"{kind}, on the {source} feed" if (
                waits == "feed" and source) else f"{kind}, on {waits}"
        state.exports.append(Link(name, detail, when=when,
                                  href=f"./export:{name}",
                                  wrong=bool(trouble),
                                  unreachable=trouble or (
                                      "" if when is not None
                                      else "waiting for its first run")))

    try:
        progress = _default_archive_path(admin).parent / "uploads.json"
    except Exception:
        log.debug("could not locate upload progress", exc_info=True)
        progress = _base(admin) / "uploads.json"
    through: dict[str, Any] = {}
    if progress.exists():
        try:
            import json

            through = (json.loads(progress.read_text(encoding="utf-8"))
                       .get("through") or {})
        except (OSError, ValueError):
            through = {}
    configured = {name: one for name, one
                  in (current.get("uploads") or {}).items()
                  if isinstance(one, dict)}
    for name, settings in sorted(configured.items()):
        if settings.get("enabled") is False:
            state.uploads.append(Link(name, "switched off",
                                      href=f"./upload:{name}"))
            continue
        when = through.get(name)
        state.uploads.append(Link(name, str(settings.get("kind") or ""),
                                  when=when or None,
                                  href=f"./upload:{name}"))
    # An upload nobody configured but something is running: `live.json` into
    # a directory this machine serves is set up on its own, from the export
    # that publishes the pages. It posts every ten seconds, and a page
    # claiming "no upload is configured" while that happens is wrong about
    # the thing it exists to report.
    for name in sorted(set(through) - set(configured)):
        state.uploads.append(Link(name, "set up automatically",
                                  when=through[name] or None,
                                  href="./core"))
    _live_readings(admin, current, state)


def _live_readings(admin: Any, current: dict, state: State) -> None:
    """The live file, dated from itself.

    `live.json` is rewritten every few seconds, so its own mtime is exactly
    when the readings last went out. Nothing has to be recorded for this,
    which matters: the upload keeps its position in memory on purpose --

        it moves every few seconds, and writing a file that often to record
        something nobody needs after a restart is how an SD card wears out

    -- and making it write one so that this page could read it would be
    trading a real cost for a cosmetic one. The file it already writes
    answers the same question.

    Only the local case. An upload that POSTs to somebody else's webspace
    leaves nothing here to look at, and it has its own row from the progress
    file when it has sent anything.
    """
    if any(one.name == "live readings" for one in state.uploads):
        return
    made = _implied_live(admin)
    if not made:
        return
    settings = next(iter(made.values()))

    newest = None
    for directory in settings.get("directories") or []:
        found = _under(admin, str(directory), "") / "live.json"
        try:
            when = found.stat().st_mtime
        except OSError:
            continue
        if newest is None or when > newest:
            newest = when

    # What it actually does, all of it. This said "live.json in <one
    # directory>" while the same upload was also posting to a web host --
    # which is the half somebody had configured on purpose, and the half
    # they came to this page to see.
    where = []
    if settings.get("url"):
        from urllib.parse import urlsplit

        where.append(f"posts to {urlsplit(str(settings['url'])).netloc}")
    count = len(settings.get("directories") or [])
    if count:
        where.append(f"writes live.json into {count} "
                     f"{'directory' if count == 1 else 'directories'}")
    state.uploads.append(Link("live readings", ", and ".join(where),
                              when=newest, href="./publishing"))


def _implied_live(admin: Any) -> dict:
    """The live upload the exports imply, as the service builds it.

    Asked of the same function rather than worked out again here. This page
    said one thing and the service did another for exactly as long as there
    were two readings of it.
    """
    try:
        from .cli import DEFAULT_FEEDS, live_readings_locally

        cfg = _AsSettings(admin)
        configured = cfg.config.get("feeds") or DEFAULT_FEEDS
        registry = adminarchives.load(admin)
        try:
            implicit = registry.default_name()
        except LookupError:
            implicit = ""
        # `live_readings_locally` deliberately has no process-global fallback:
        # the admin process has no CLI namespace to resolve. Hand it the same
        # place choice the feed scheduler would make from these files.
        schedule = {
            name: {
                "archive": str(settings.get("archive") or implicit).strip()
            }
            for name, settings in configured.items()
            if isinstance(settings, dict) and settings.get("kind")
        }
        return live_readings_locally(cfg, {}, schedule=schedule)
    except Exception:
        log.debug("could not work out the implied live upload", exc_info=True)
        return {}


class _AsSettings:
    """Enough of `Settings` for the function above: a config and a get."""

    def __init__(self, admin: Any) -> None:
        self.config = admin.config()

    def get(self, name: str, default: Any = None) -> Any:
        from . import config as config_file

        found = config_file.get(self.config, name)
        return default if found is None else found


def _forecast_state(admin: Any, state: State) -> None:
    current = admin.config()
    # "forecast", singular. The other three sections are plural and this one
    # is not, which is a thing to read off `cli.configured_forecasts` rather
    # than to assume: assuming it cost a card that said "no forecast is
    # configured" on an installation fetching one every hour.
    configured = current.get("forecast") or {}
    if not configured:
        return
    # One installation-wide store beside the configuration. Its rows carry
    # the place name; choosing an archive file here would make the cache move
    # when a place is added, removed or reordered.
    from .forecast import shared_store_path

    try:
        path = shared_store_path(admin.path)
    except Exception:
        log.debug("could not locate the forecast store", exc_info=True)
        return
    # Which series there are, so a card can say which place a forecast is
    # for. A sole custom-named place is also the implicit place; literal
    # "default" is not a substitute for resolving the registry.
    try:
        register = adminarchives.load(admin)
        places = {one.name: one.title for one in register.all()}
        try:
            implicit = register.default_name()
        except LookupError:
            implicit = ""
    except Exception:
        log.debug("could not read the places for the forecast cards",
                  exc_info=True)
        places, implicit = {}, ""

    if not path.exists():
        for name in sorted(configured):
            settings = configured.get(name) or {}
            archive = str((settings.get("archive") if isinstance(settings, dict)
                           else "") or implicit).strip()
            why = "not fetched yet" if archive else "no place selected"
            state.forecasts.append(Link(name, unreachable=why,
                                        href=f"./forecast:{name}"))
        return
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return
    try:

        for name in sorted(configured):
            # Keyed on the entry's own name now, and on the series it is
            # for. It used to be keyed on the *provider*, so two entries of
            # one kind shared a row and this had to guess the row back from
            # `kind or name`; the runner writes the entry name, so the guess
            # is gone.
            settings = configured.get(name) or {}
            archive = str((settings.get("archive") if isinstance(settings, dict)
                           else "") or implicit).strip()
            if not archive:
                state.forecasts.append(Link(
                    name, unreachable="no place selected",
                    href=f"./forecast:{name}"))
                continue
            row = conn.execute(
                "SELECT fetched, hours, days FROM run "
                "WHERE archive = ? AND source = ?",
                (archive, name)).fetchone()
            # The name somebody gave the place, not the key. "8 days for
            # default" names a row in a file; the card is read by whoever
            # called it Kirchdorf an der Amper.
            where = (f" for {places.get(archive, archive)}"
                     if len(places) > 1 else "")
            if row is None:
                state.forecasts.append(Link(
                    name, unreachable=f"configured{where}, not fetched yet",
                    href=f"./forecast:{name}"))
                continue
            fetched, hours, days = row
            state.forecasts.append(Link(
                name, f"{hours or 0} hours, {days or 0} days{where}",
                when=fetched, href=f"./forecast:{name}"))
    except sqlite3.Error:
        log.exception("could not read the forecast state")
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
    from .options import parse_duration

    current = admin.config()
    # A duration, not a number: the file says `interval = "5m"`, which is the
    # whole point of the duration kind. `int()` on it raised, this function
    # stopped at its first line, and the page reported nothing wrong about an
    # installation -- a dashboard silenced by a format it writes itself.
    raw = config_file.get(current, "interval")
    try:
        state.interval = int(parse_duration(str(raw))) if raw else 300
    except Exception:
        # A value this page cannot read is not a reason to stop reading the
        # rest. The default is what the archiver would use anyway.
        state.interval = 300

    if not config_file.get(current, "token"):
        _concern(state,
            "No upload token is set. Listener writes are unauthenticated.",
            "./core")

    if state.newest_packet and state.newest_record is not None:
        behind = state.newest_packet - state.newest_record
        if behind > state.interval * BEHIND_INTERVALS:
            _concern(state,
                f"Readings are arriving, but stored data is "
                f"{int(behind // 60)} min behind the newest packet.", "./live")

    if state.pending > PENDING_LIMIT:
        _concern(state,
            f"{state.pending} intervals are waiting to be archived.",
            "./live")

    if state.strangers:
        sender = "sender" if state.strangers == 1 else "senders"
        _concern(state,
            f"{state.strangers} {sender} uploaded "
            f"{ago(state.newest_stranger)} and are selected by no place.",
            "./senders")

    for one in state.archives:
        if one.unreachable:
            _concern(state, f"Place {one.name!r}: {one.unreachable}",
                     "./places")

    for one in state.exports:
        if one.wrong:
            _concern(state, f"Export {one.name!r}: {one.unreachable}",
                     one.href or "./publishing")

    for said, where in _senders_placing_nothing(admin):
        _concern(state, said, where)


def _senders_placing_nothing(admin: Any) -> list[tuple[str, str]]:
    """Additional senders that are uploading into nothing.

    Two primaries in one place used to be the thing worth saying here, and it
    cannot be configured any more: a place holds one primary sender ID.

    What replaced it is the cost of that: a sender other than the primary
    writes only the columns somebody has given it, so one nobody has been to
    the Fields page about is arriving, being stored in the live journal, and
    reaching no column at all. That is recoverable -- place the fields, run a
    rebuild, and the whole retention period follows -- but only by somebody
    who knows it is happening.

    Deliberately narrow, because a note standing beside every row says
    nothing: only senders that have actually sent, that a place selects, that
    are not its primary, and that have no placement of any kind.
    """
    try:
        archives = adminarchives.load(admin).all()
        plans = placement.load(placement.path_for(Path(admin.path).parent))
    except Exception:
        return []

    said = []
    for archive in archives:
        choices = adminarchives.sender_choices(admin, archive)
        primary = archive.primary_sender(choices)
        placed = {one.station for one in plans.takes
                  if one.archive == archive.name and one.station and one.fields}
        idle = sorted(
            one.label for one in choices
            if (archive.selects(one.sender) and one.sender != primary
                and one.first_seen > 0 and one.sender not in placed))
        if idle:
            sender = "sender is" if len(idle) == 1 else "senders are"
            said.append((
                (f"In place {archive.name!r}, {len(idle)} additional {sender} "
                 f"uploading into no column: {', '.join(idle)}. Give their "
                 "readings columns under Fields, or nothing they send is kept."),
                f"./places/{archive.name}/fields"))
    return said


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
        said = html.escape(admin.say("something needs looking at"))
        mark = (f' <span class="warn" title="{said}">'
                f'{len(state.concerns)}</span>')
    return [(f'<a class="home" href="./overview"{current}>'
             f'{html.escape(admin.say("Overview"))}{mark}</a>')]


def _short(text: str, keep: int = 34) -> str:
    """From the end, which is the half of a path that identifies it."""
    return text if len(text) <= keep else "…" + text[-(keep - 1):]


def _flow_row(one: Link, kind: str = "", lang: Any = None) -> str:
    """One compact status row in a stage."""
    lang = lang if lang is not None else language_defs.get("en")
    label = (f'<span class="chip">{html.escape(lang.say(kind))}</span>'
             if kind else "")
    whole = html.escape(one.name)
    name = f'<span class="title" title="{whole}">{whole}</span>'
    if one.href:
        name = (f'<a class="title" href="{html.escape(one.href)}" '
                f'title="{whole}">{whole}</a>')
    detail = (f'<span class="note">{html.escape(one.detail)}</span>'
              if one.detail else "")
    status = ""
    if one.unreachable:
        tone = "warn when" if one.wrong else "note when"
        status = (f'<span class="{tone}" title="{html.escape(one.unreachable)}">'
                  f'{html.escape(_short(one.unreachable))}</span>')
    elif one.when is not None:
        status = f'<span class="when">{html.escape(ago(one.when, lang))}</span>'
    return f"<li>{label}{name}{detail}{status}</li>"


def _stage(title: str, summary: str, href: str, rows: list[tuple[str, Link]],
           empty: str, lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    items = (NEWLINE.join(_flow_row(one, kind, lang) for kind, one in rows)
             if rows else
             f'<li class="none">{html.escape(lang.say(empty))}</li>')
    said = html.escape(lang.say(title))
    open_it = html.escape(lang.fill("Open {stage}", stage=lang.say(title)))
    return f'''
<section class="overview-stage flow" aria-labelledby="stage-{title.lower()}">
  <div class="made">
    <h3 class="title" id="stage-{title.lower()}">{said}</h3>
    <span class="note">{html.escape(summary)}</span>
    <a class="aside" href="{html.escape(href)}"
       aria-label="{open_it}">{html.escape(lang.say("Open"))}</a>
  </div>
  <ul class="sends plain">{items}</ul>
</section>'''


def _count(amount: int, singular: str, lang: Any = None) -> str:
    """"3 senders", in the reader's language.

    Two keys per noun rather than a stem and an "s". German makes some
    plurals with an umlaut and some with nothing at all, and a language that
    inflects the number as well has nowhere else to say so.
    """
    lang = lang if lang is not None else language_defs.get("en")
    if amount == 1:
        return lang.fill("{n} " + singular, n=amount)
    return lang.fill("{n} " + singular + "s", n=amount)


def _collection(name: str, links: list[Link], href: str,
                lang: Any = None) -> Link:
    """Summarise an inventory without copying it onto the overview."""
    lang = lang if lang is not None else language_defs.get("en")
    failed = [one for one in links if one.wrong]
    newest = max((one.when for one in links if one.when is not None),
                 default=None)
    detail = (_count(len(links), "configured item", lang) if links
              else lang.say("Not configured"))
    return Link(lang.say(name), detail, when=newest,
                unreachable=(_count(len(failed), "failure", lang)
                             if failed else ""),
                href=href, wrong=bool(failed))


def _attention(state: State, lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    if not state.concerns:
        return ""
    rows = []
    for index, concern in enumerate(state.concerns):
        href = (state.concern_hrefs[index]
                if index < len(state.concern_hrefs) else "./overview")
        about = html.escape(lang.fill("Review: {what}", what=concern))
        rows.append(
            f'<li><span>{html.escape(concern)}</span>'
            f'<a href="{html.escape(href)}" aria-label="{about}">'
            f'{html.escape(lang.say("Review"))}</a></li>')
    return f'''
<section class="overview-attention banner warn" aria-labelledby="attention-title">
  <h3 id="attention-title">{html.escape(lang.say("Needs attention"))}
      <span class="count">{len(rows)}</span></h3>
  <ul class="attention-list">{NEWLINE.join(rows)}</ul>
</section>'''


def overview(admin: Any, message: str = "", error: str = "") -> str:
    say = admin.say
    lang = admin.language
    state = read(admin)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    # The banner above the page says it. Printing it a second time in the
    # body was two "Saved." one under the other, which reads as two things
    # having happened.
    said = ""

    attention = _attention(state, lang)

    intake_rows = [("Sender", one) for one in state.stations]
    if state.live:
        intake_rows.append(("Live", state.live))
    intake_summary = _count(len(state.stations), "sender", lang)
    if state.newest_packet is not None:
        intake_summary += " · " + lang.fill(
            "last reading {when}", when=ago(state.newest_packet, lang))

    place_summary = _count(len(state.archives), "place", lang)
    if state.newest_record is not None:
        place_summary += " · " + lang.fill(
            "last record {when}", when=ago(state.newest_record, lang))

    configured_notify = admin.config().get("notify") or {}
    notify_count = sum(1 for one in configured_notify.values()
                       if isinstance(one, dict))
    publishing_rows = [
        ("", _collection("Feeds", state.feeds, "./publishing", lang)),
        ("", _collection("Exports", state.exports, "./publishing", lang)),
        ("", _collection("Uploads", state.uploads, "./publishing", lang)),
        ("", Link(say("Notifications"),
                  _count(notify_count, "configured item", lang)
                  if notify_count else say("Not configured"),
                  href="./publishing")),
        ("", _collection("Forecasts", state.forecasts, "./publishing", lang)),
    ]
    publishing_count = (len(state.feeds) + len(state.exports)
                        + len(state.uploads) + notify_count
                        + len(state.forecasts))
    return f'''
<div class="page-head">
  <h2>{html.escape(say("Overview"))}</h2>
  <a class="small-action" href="./setup">{html.escape(say("Setup"))}</a>
</div>
{problem}{said}{attention}
<div class="overview-stages">
{_stage("Intake", intake_summary, "./senders", intake_rows,
        "No senders.", lang)}
{_stage("Places", place_summary, "./places",
        [("Place", one) for one in state.archives], "No places.", lang)}
{_stage("Publishing", _count(publishing_count, "configured item", lang),
        "./publishing", publishing_rows, "Not configured.", lang)}
</div>
'''

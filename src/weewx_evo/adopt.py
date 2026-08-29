"""Taking over from a WeeWX installation: finding one, and reading it.

Somebody trying this out has fifteen years of readings and a website they
have been looking at every morning. Asking them to type their station's
coordinates again -- and their FTP password, and their chart definitions --
is asking them to do work a computer can do, and to do it accurately.

**Two situations, and the second is the common one.** Nobody installs a
rewrite of their weather software onto the machine that is recording their
weather. So this looks for a local installation *and* takes everything by
upload, and the pages that use it offer both.

    find()          a weewx.conf on this machine, at the usual addresses
    read(path)      what is in one: station, database, skins, uploads
    charts_in()     the plots, which are in the *skins* and not in weewx.conf
    adopt_archive() the database, which needs no conversion at all

**The database is the part that turns out to be free.** A weewx.sdb holds
`archive` and one `archive_day_*` per reading, which is exactly what this
program reads and writes -- that is the one rule this whole rewrite is built
on, and here it pays for itself: taking over an archive is copying a file,
not migrating one. Measured on a real one: 2280 records, 134 columns, opened
and read without a single change.

MySQL and Postgres are the other half and are not free, because there the
readings are in somebody else's server. `dumps.py` is that half.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Where a weewx.conf is, in the order the WeeWX documentation puts them.
#: `$WEEWX_CONFIG` first because a container sets it and because somebody
#: who has set it means it.
LOOKS_IN = (
    "/etc/weewx/weewx.conf",
    "/home/weewx/weewx.conf",
    "~/weewx-data/weewx.conf",
    "/opt/weewx/weewx.conf",
    "/usr/share/weewx/weewx.conf",
    "./weewx.conf",
)

#: What an archive database has to hold before this will believe it is one.
#: `archive` alone is not enough -- half the world has a table of that name.
WANTS = ("archive",)


@dataclass
class Found:
    """One WeeWX installation, as much of it as could be read."""

    conf: Path | None = None
    #: Everything `weewxconf.convert` understood, as our settings.
    settings: dict[str, Any] = field(default_factory=dict)
    #: (report, skin, html_root) for each skin it renders.
    skins: list[tuple[str, str, str]] = field(default_factory=list)
    #: FTP and rsync, as exports, switched off.
    exports: dict[str, dict] = field(default_factory=dict)
    #: Where its archive is, if it could be worked out and is a file here.
    archive: Path | None = None
    #: What it is on, when it is not SQLite: "mysql" or "postgres".
    elsewhere: str = ""
    #: Where its skins are, for reading the charts out of them.
    skin_root: Path | None = None
    #: What was read, in plain words, for the page to show.
    notes: list[str] = field(default_factory=list)
    #: What could not be, likewise.
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether anything came out of it.

        The settings, not the path. A file that arrived by upload has no
        path at all -- which is the ordinary case, since nobody installs
        this on the machine recording their weather -- and requiring one
        made every upload report "that did not read as a weewx.conf" while
        holding nine settings out of it.
        """
        return bool(self.settings)

    def records(self) -> int:
        """How many archive records its database holds. 0 if unreadable."""
        if self.archive is None:
            return 0
        return count_records(self.archive)


def find(also: str = "") -> Path | None:
    """A weewx.conf on this machine, or None.

    Tried in order and the first readable one wins. `$WEEWX_CONFIG` before
    the list because a container sets it, and somebody who has set it has
    said which installation they mean.
    """
    candidates = []
    if also:
        candidates.append(also)
    from_env = os.environ.get("WEEWX_CONFIG")
    if from_env:
        candidates.append(from_env)
    candidates.extend(LOOKS_IN)

    for one in candidates:
        try:
            path = Path(one).expanduser()
        except (OSError, RuntimeError):
            continue
        if path.is_file() and os.access(path, os.R_OK):
            return path
    return None


def read(conf_path: str | Path, text: str = "") -> Found:
    """Everything a weewx.conf says, in our terms.

    `text` is for a file that arrived by upload rather than being on this
    machine, which is the ordinary case: nobody installs this onto the
    machine that is recording their weather.
    """
    from . import weewxconf

    found = Found()
    try:
        if text:
            conf = weewxconf.parse(text)
            found.conf = Path(conf_path) if conf_path else None
        else:
            found.conf = Path(conf_path)
            conf = weewxconf.read(found.conf)
    except Exception as exc:
        found.problems.append(f"could not read it: {exc}")
        return found

    result = weewxconf.convert(conf)
    found.settings = dict(result.values)
    found.skins = list(getattr(result, "skins", []))
    found.exports = dict(getattr(result, "exports", {}))
    found.notes = list(result.taken)
    found.problems.extend(result.warnings)

    _locate_archive(found, conf)
    _locate_skins(found, conf)
    return found


def _locate_archive(found: Found, conf: dict[str, Any]) -> None:
    """Where its readings are, and whether they are reachable from here."""
    databases = conf.get("Databases")
    binding = ((conf.get("DataBindings") or {}).get("wx_binding") or {})
    wanted = str(binding.get("database") or "archive_sqlite").strip()
    section = (databases or {}).get(wanted) or {}

    kind = str(section.get("database_type") or "").strip().lower()
    if kind in ("mysql", "postgres", "postgresql"):
        found.elsewhere = "postgres" if kind.startswith("postgres") else "mysql"
        found.notes.append(
            f"its readings are in {found.elsewhere}, not in a file -- a dump "
            f"is the way to bring them over")
        return

    name = str(section.get("database_name") or "weewx.sdb").strip()
    root = str(conf.get("WEEWX_ROOT") or "").strip()
    sqlite_root = str(
        ((conf.get("DatabaseTypes") or {}).get("SQLite") or {})
        .get("SQLITE_ROOT") or "").strip()

    tries = []
    if Path(name).is_absolute():
        tries.append(Path(name))
    else:
        for base in (sqlite_root, root, str(found.conf.parent) if found.conf
                     else ""):
            if base:
                tries.append(Path(base) / name)
        # `SQLITE_ROOT` is usually `%(WEEWX_ROOT)s/archive`, and our parser
        # does not expand that, so the two obvious places are tried plainly.
        if root:
            tries.append(Path(root) / "archive" / name)

    for one in tries:
        if is_archive(one):
            found.archive = one
            found.notes.append(f"its archive is {one} ({count_records(one)} "
                               f"records)")
            return
    found.problems.append(
        f"could not find its archive: looked for {name} in "
        f"{', '.join(str(t.parent) for t in tries[:3]) or 'nowhere obvious'}")


def _locate_skins(found: Found, conf: dict[str, Any]) -> None:
    """Where the skins are, because that is where the charts are."""
    reports = conf.get("StdReport") or {}
    root = str(reports.get("SKIN_ROOT") or "skins").strip()
    base = str(conf.get("WEEWX_ROOT") or "").strip()
    tries = [Path(root)]
    if base:
        tries.insert(0, Path(base) / root)
    if found.conf is not None:
        tries.append(found.conf.parent / root)
    for one in tries:
        if one.is_dir():
            found.skin_root = one
            return


def _clear(where: Path) -> None:
    """A database and the journals SQLite leaves beside it.

    All three, because two of them outlive the first. A `-wal` left from an
    earlier attempt describes a file that is not there any more, and SQLite
    refuses to open the new one -- which reads as "that is not an archive"
    and is nothing of the sort. That happened here.
    """
    for name in (where.name, where.name + "-wal", where.name + "-shm"):
        where.with_name(name).unlink(missing_ok=True)


def _backup(source: Path, into: Path) -> None:
    """A consistent copy of a database somebody else may be writing to.

    Read-only on the source: this must not be the thing that creates a
    journal beside WeeWX's file, or checkpoints one, or takes a write lock
    on a station that is recording.
    """
    reader = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True,
                             timeout=30)
    try:
        writer = sqlite3.connect(into)
        try:
            reader.backup(writer)
        finally:
            writer.close()
    finally:
        reader.close()


def is_archive(path: str | Path) -> bool:
    """Whether that file is a WeeWX archive we can read.

    Opened and asked, not guessed from the name. A file called weewx.sdb
    that is somebody's photo library should say so here rather than three
    steps later.
    """
    path = Path(path)
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not all(one in names for one in WANTS):
            return False
        # And the columns that make it a weather archive rather than a table
        # that happens to be called `archive`.
        columns = {d[0] for d in conn.execute(
            "SELECT * FROM archive LIMIT 0").description}
        return {"dateTime", "usUnits", "interval"} <= columns
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def count_records(path: str | Path) -> int:
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro",
                               uri=True)
    except sqlite3.Error:
        return 0
    try:
        return int(conn.execute("SELECT COUNT(*) FROM archive").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def span_of(path: str | Path) -> tuple[int, int]:
    """First and last timestamp in it, or (0, 0)."""
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro",
                               uri=True)
    except sqlite3.Error:
        return 0, 0
    try:
        row = conn.execute(
            "SELECT MIN(dateTime), MAX(dateTime) FROM archive").fetchone()
        return (int(row[0] or 0), int(row[1] or 0)) if row else (0, 0)
    except sqlite3.Error:
        return 0, 0
    finally:
        conn.close()


def adopt_archive(source: str | Path, into: str | Path,
                  copy: bool = True) -> str:
    """Put an existing archive where this installation will read it.

    Copied rather than moved or pointed at, and that is the whole safety of
    this: the original stays exactly where WeeWX is still writing it. Two
    programs writing one SQLite file is the way to lose both.

    **Through SQLite's own backup, not `shutil.copyfile`.** A running
    station's database is in WAL mode -- ours sets it, and the mode is
    stored in the file, so a database this program has ever opened stays in
    it. In WAL mode the committed rows live in the `-wal` sidecar until a
    checkpoint folds them back, and a file copy takes only the main file.

    Measured, and worse than losing the last few readings: a database with
    150 rows written and not yet checkpointed copies as a 4 KB header, and
    the copy answers `no such table: archive`. The backup API reads through
    the WAL and produced all 150.

    It also does the right thing while the other program is writing, which
    `copyfile` cannot promise at all: SQLite takes the copy transaction by
    transaction and starts over if the source moves under it.

    Returns what happened, or raises with a usable message.
    """
    source, into = Path(source), Path(into)
    if not is_archive(source):
        raise ValueError(f"{source} is not a WeeWX archive database")
    if into.exists():
        raise ValueError(
            f"there is already an archive at {into}. Move it aside first -- "
            f"this will not write over readings that are already here")

    into.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        # Beside the target and renamed, so a copy interrupted half way
        # leaves nothing that looks like an archive.
        staging = into.with_suffix(into.suffix + ".part")
        _clear(staging)
        _backup(source, staging)
        # The journals belong to the name they were made under. Renaming the
        # database and leaving them gives the next reader a WAL that
        # describes a file which is no longer there.
        staging.replace(into)
        for extra in ("-wal", "-shm"):
            staging.with_name(staging.name + extra).unlink(missing_ok=True)
    else:
        Path(source).replace(into)

    from time import localtime, strftime

    first, last = span_of(into)
    when = ""
    if first and last:
        when = (f", {strftime('%Y-%m-%d', localtime(first))} to "
                f"{strftime('%Y-%m-%d', localtime(last))}")
    return f"{count_records(into)} records{when}"


def charts_in(skin_root: Path | None, skins: list[tuple[str, str, str]]):
    """The charts out of each skin this installation renders.

    In the skins, not in weewx.conf: measured on a shipped WeeWX, its
    weewx.conf holds no `[ImageGenerator]` at all and every skin holds one
    (Horizon holds five). weewx.conf only says which skin a report uses --
    and may override parts of it, which is why the report's own section is
    laid over the skin's.

    Yields (report, skin, PlotSet) for each one that could be read.
    """
    from . import plots as plot_defs
    from . import weewxconf

    if skin_root is None:
        return
    for report, skin, _html_root in skins:
        conf_path = Path(skin_root) / skin / "skin.conf"
        if not conf_path.is_file():
            continue
        try:
            conf = weewxconf.read(conf_path)
            section = conf.get("ImageGenerator")
            if not isinstance(section, dict):
                continue
            got = plot_defs.from_image_generator(section)
            charts = got.plots if hasattr(got, "plots") else got
        except Exception:
            log.debug("could not read the charts in %s", conf_path,
                      exc_info=True)
            continue
        if len(charts):
            yield report, skin, charts

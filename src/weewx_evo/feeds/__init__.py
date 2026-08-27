"""Feeds: what gets produced.

A driver brings readings in. A **feed** turns them into something -- a CSV, a
JSON document, a chart, a whole website, a monthly PDF. An **export** takes
what a feed produced and moves it somewhere: FTP, rsync, a copy to a mounted
share. See `weewx_evo.exports`.

The split matters and WeeWX does not make it. There, a "skin" renders files
*and* the FTP upload is configured inside the same section, so producing a
site for two destinations means running the renderer twice, and uploading the
same directory two ways means saying so in two places. Here:

    feed  -> a directory of files
    export -> that directory, sent somewhere

One feed, three exports. Or three feeds into one directory and a single
export. Neither knows about the other; the directory is the whole interface,
in the same way the live table is the whole interface between the listener
and the archiver.

## One directory per feed

Ours live here, one folder each, the way drivers live in `ingest/plugins`:

    feeds/
      jsongenerator/        the time series everything else is built on
      diagnostic/           draws whatever JSON is on disk, and finds fault
        vendor/             its own uPlot, MIT, fifty kilobytes

A feed that grows templates, stylesheets or a JavaScript bundle keeps them
beside its code rather than in a shared pile, and a feed that is deleted takes
its assets with it. Feeds somebody else wrote are installed separately, as
drivers are -- see `ingest/userdrivers.py` for the same arrangement.

A feed says what it produces and where it put it:

    class MyFeed:
        def produce(self, archive, into: Path) -> Produced:
            ...

        @staticmethod
        def options():        # the admin page builds a form from this
            return [...]

Nothing is implemented yet. This file exists so that the name is settled and
the shape is on record: the exports are built and they need something to
point at, and whoever writes the first feed is not inventing the interface as
well.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: When a feed runs.
#:
#: `record` is the common case: a new archive record landed, produce again.
#: `schedule` is for what is not tied to one record -- a monthly summary, a
#: nightly export. `packet` is for something wanting every reading as it
#: arrives, which is what a live display wants.
#:
#: A feed class sets the one it was written for. The operator can move it
#: between `record` and `schedule`, because that is a question about this
#: installation: hourly charts on a slow machine, a summary once a night.
#: `packet` is not offered as a choice -- a feed that wants every reading is
#: built for it and one that is not would only run oftener without producing
#: anything new.
TRIGGERS = ("record", "packet", "schedule")

#: What an operator may choose between, with what to call it.
CHOOSABLE_TRIGGERS = (
    ("record", "with the archive, whenever a record lands"),
    ("schedule", "on its own clock"),
)

#: The archive a feed with no `archive` set reads from. Matches
#: `stations.DEFAULT_ARCHIVE`: a station writes into an archive and a feed
#: reads out of one, so they have to agree about the name.
DEFAULT_ARCHIVE = "default"

ENTRY_POINT_GROUP = "weewx_evo.feeds"

log = logging.getLogger(__name__)


@dataclass
class Produced:
    """What one run of a feed made.

    The list of files matters to the exports: an export that knows which
    files changed sends those, and one that does not sends everything every
    time. Over a phone connection that is the difference between a feed that
    can run every five minutes and one that cannot.
    """

    directory: Path
    files: list[Path] = field(default_factory=list)
    #: Anything the feed wants to say afterwards, for the log and the page.
    note: str = ""

    @property
    def count(self) -> int:
        return len(self.files)


def kinds() -> list[str]:
    """The kinds of feed that can be configured.

    A kind is what a feed *is* -- JSON, a diagnostic page, a Cheetah skin.
    A name is one configured instance of it. Two Cheetah feeds rendering two
    different skins are two names of one kind, which is how a station shows
    Belchertown and a phone layout at the same time. WeeWX arranges this the
    same way, with named sections under `[StdReport]`.
    """
    load()
    return sorted(_FEEDS)


def names() -> list[str]:
    """Kept for anything still asking. See `kinds`."""
    return kinds()


def describe(kind: str) -> str:
    """One line about a kind of feed, for a form that offers it."""
    load()
    return DESCRIPTIONS.get(kind, "")


def factory_for(kind: str) -> Any:
    """The class behind a kind, loading the registry first."""
    load()
    return _FEEDS.get(kind)


#: Registered feeds, by name. Filled the way drivers are: from what ships
#: here, then from entry points.
_FEEDS: dict[str, Any] = {}
_LOADED = False

#: What each one is, in a few words. The dropdown that offers them is a list
#: of names otherwise, and "json" does not say what is in it.
DESCRIPTIONS: dict[str, str] = {}

#: What ships. Named here rather than discovered by walking the package: a
#: half-written feed in the directory should not appear in a form.
BUNDLED = (
    ("json", "weewx_evo.feeds.jsongenerator", "JSONGenerator",
     "the time series everything else draws from"),
    ("diagnostic", "weewx_evo.feeds.diagnostic", "Diagnostic",
     "one page that draws whatever JSON is on disk"),
    ("cheetah", "weewx_evo.feeds.cheetah", "CheetahFeed",
     "a skin written for WeeWX, rendered unchanged"),
    ("images", "weewx_evo.feeds.imagegenerator", "ImageGenerator",
     "the same charts as PNG files, for a page or a forum post"),
    ("realtime", "weewx_evo.feeds.realtime", "RealtimeFeed",
     "one line of current conditions, in Cumulus's realtime.txt format"),
)


def load() -> None:
    """Pull in the feeds. A broken one is reported, never fatal.

    Same arrangement as the drivers: one feed that will not import must not
    cost the others. A station whose diagnostic page is broken should still
    be writing its time series.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    from importlib import import_module

    for name, module_name, attribute, what in BUNDLED:
        try:
            module = import_module(module_name)
            register(name, getattr(module, attribute), what)
        except Exception:
            log.exception("the feed %r could not be loaded; leaving it out",
                          name)

    from importlib.metadata import entry_points

    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            register(entry.name, entry.load())
        except Exception:
            log.exception("the feed %r could not be loaded; leaving it out",
                          entry.name)


def register(name: str, feed: Any, description: str = "") -> None:
    _FEEDS[name] = feed
    if description:
        DESCRIPTIONS[name] = description


def get(name: str) -> Any:
    load()
    return _FEEDS.get(name)


@runtime_checkable
class Feed(Protocol):
    """Readings out, as files."""

    #: What sets this feed going. See TRIGGERS.
    trigger: str

    def produce(self, archive: Any, into: Path) -> Produced:
        """Write this feed's files into `into` and say which they are.

        `archive` is a read-only view: a feed reports history, it does not
        write it. Whatever this raises is logged and does not stop the next
        feed -- a broken template must not cost the upload of everything else.
        """
        ...


def archive_names() -> list[tuple[str, str]]:
    """The archives a feed can read from, for the settings page.

    Taken from `stations.toml`, because that is where an archive gets named:
    a station says which one it writes into, and this says which one a feed
    reads out of. Two lists of archive names would be one list and one way of
    getting it wrong.
    """
    from .. import stations

    try:
        register = stations.load(stations.path_for(_config_dir()))
        found = register.archives()
    except Exception:
        log.debug("could not read the archives", exc_info=True)
        found = [DEFAULT_ARCHIVE]
    return [(one, one) for one in found]


def _config_dir() -> Path:
    """Where the configuration lives, as the running process sees it."""
    from .. import settings as settings_module

    running = settings_module.running()
    where = getattr(running, "path", None) if running else None
    return Path(where).parent if where else Path(".")


def schedule_options() -> list:
    """When a feed runs and what it reads. Added to every feed's page.

    Separate from a feed's own settings because it is the same question for
    all of them, and because the answer used to be "whenever a record lands"
    with no way to say otherwise. `realtime` declared `packet` and got the
    archive interval anyway, which is the opposite of what that file is for.
    """
    from ..options import Group, Option

    return [
        Group("When it runs",
              "A feed produces files. This says what sets it going and which "
              "measurement series it reads.", (
                  Option("trigger", "Produce", kind="choice", default="record",
                         choices=CHOOSABLE_TRIGGERS,
                         help="With the archive is right for anything built "
                              "out of archive records: there is nothing new "
                              "to draw before the next one. Its own clock is "
                              "for what does not follow the records -- a "
                              "nightly summary, or expensive charts on a "
                              "machine that should not redraw them every "
                              "five minutes."),
                  Option("every", "How often", kind="duration", default="1h",
                         help="Only when it runs on its own clock. Rounded to "
                              "the clock, so an hourly feed produces on the "
                              "hour rather than an hour after the service "
                              "started."),
                  Option("archive", "Reads from", kind="choice",
                         default=DEFAULT_ARCHIVE,
                         choices=((DEFAULT_ARCHIVE, DEFAULT_ARCHIVE),),
                         choices_from=archive_names,
                         help="Which measurement series this feed reports on. "
                              "With one archive there is nothing to choose; "
                              "with a station at each of two sites, this is "
                              "which site the page is about."),
              ), prefix=""),
    ]

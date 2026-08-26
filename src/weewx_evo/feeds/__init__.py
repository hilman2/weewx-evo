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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: When a feed runs.
#:
#: `record` is the common case: a new archive record landed, produce again.
#: `schedule` is for what is not tied to one record -- a monthly summary, a
#: nightly export. `packet` is for something wanting every reading as it
#: arrives, which is what a live display wants.
TRIGGERS = ("record", "packet", "schedule")

ENTRY_POINT_GROUP = "weewx_evo.feeds"


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


def names() -> list[str]:
    """The feeds that exist.

    Empty until the first one is written. It is a function rather than a list
    so that an export's dropdown fills itself the moment a feed appears --
    the export does not have to be told, and nobody has to restart anything.
    """
    return sorted(_FEEDS)


#: Registered feeds, by name. Filled the way drivers are: from entry points
#: and from what ships here.
_FEEDS: dict[str, Any] = {}


def register(name: str, feed: Any) -> None:
    _FEEDS[name] = feed


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

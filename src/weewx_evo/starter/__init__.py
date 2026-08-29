"""What a station has before anybody has configured anything.

A fresh installation used to be a settings page with nothing on it: no
charts, so no feed had anything to draw; no skin, so nothing was published;
no forecast. Every one of those is a decision somebody has to make before
seeing a single page, and none of them is a decision they have information
for yet.

So there are defaults, and they are chosen rather than empty:

    plots.toml     the Seasons set, 100 charts over four spans. Not
                   invented -- it is what WeeWX has drawn since 2010, so an
                   arrival from WeeWX sees the charts they know and an
                   arrival from nowhere gets a set that fifteen years of
                   stations found sufficient.
    feeds          the JSON series everything else is built on, and `deck`,
                   so there is a website rather than a directory of numbers.

**A chart for a sensor this station does not have costs nothing.** The feeds
skip a chart with no data and say how many they skipped, so the set can be
generous. That is the whole reason it can be the same set for everybody.

**Nothing here overwrites anything.** Every function checks first and reports
what it did. An installation that has a `plots.toml` keeps it, including one
that has deleted every chart in it -- an empty file is an answer, and putting
a hundred charts back into it would be this module arguing with a person.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent

#: The feeds a station gets when its configuration names none.
#:
#: `deck` is here and `diagnostic` is not. The diagnostic page draws what is
#: on the disk and is for working out why something is missing; the first
#: thing a new station should have is a website, and being handed a
#: troubleshooting page instead reads as though something is already wrong.
FEEDS = {
    "json": {"kind": "json"},
    "site": {"kind": "cheetah", "skin": "deck"},
}


#: Written into the file this module lays down, and looked for afterwards.
#: A chart set nobody has touched is not a decision -- it is what was here
#: when they arrived -- so an import may replace it whole. Once somebody has
#: edited the file the marker goes with the rewrite, and after that an
#: import adds to their charts rather than replacing them.
#:
#: The alternative was to compare against the shipped file, which would call
#: a set "untouched" if somebody deleted a chart and added it back, and
#: "touched" the day the shipped set changes under them.
MARK = "# weewx-evo:starter-charts"


def plots_file() -> Path:
    """The starter charts, as they ship."""
    return HERE / "plots.toml"


def is_starter(where: Path) -> bool:
    """Whether that plots.toml is still the one this module laid down.

    Read from the top of the file: `plots.save()` writes its own header, so
    a file somebody has saved through the settings page has lost the marker
    by the time this is asked.
    """
    where = Path(where)
    if not where.exists():
        # Nothing there at all, so nothing to preserve. Reached because a
        # caller asks this *before* the file is laid down -- and answering
        # False there made an import into a fresh installation collide with
        # a starter set that was written a moment later.
        return True
    try:
        with where.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(MARK):
                    return True
                if not line.startswith("#") and line.strip():
                    return False
    except OSError:
        return False
    return False


def install_plots(where: Path) -> str:
    """Put the starter charts at `where` if there is nothing there.

    Returns what happened, for a caller that wants to say it. Empty means
    the file was already there and was left alone.
    """
    where = Path(where)
    if where.exists():
        return ""
    source = plots_file()
    if not source.is_file():
        log.debug("no starter charts at %s", source)
        return ""
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
        # Marked as it is written rather than shipped marked, so the file in
        # the repository stays a plain plots.toml that anybody can read.
        text = source.read_text(encoding="utf-8")
        where.write_text(MARK + "\n" + text, encoding="utf-8")
    except OSError as exc:
        log.warning("could not write the starter charts to %s: %s", where, exc)
        return ""

    from .. import plots as plot_defs

    try:
        count = len(plot_defs.load(where))
    except Exception:
        count = 0
    return (f"{count} charts to start with, in {where.name}. They are the "
            f"Seasons set; a chart whose readings this station does not have "
            f"is skipped when the feeds run.")


def missing(settings: Any) -> list[str]:
    """What a fresh installation still has to be told, in the order it matters.

    Used by the overview and by the wizard, so the two cannot disagree about
    what is outstanding -- which is what happens when a checklist is written
    twice.
    """
    out = []
    if not settings.get("token"):
        out.append("token")
    if not (settings.get("station.name") or "").strip():
        out.append("place")
    if settings.get("station.latitude") in (None, "", 0):
        out.append("place")
    return list(dict.fromkeys(out))

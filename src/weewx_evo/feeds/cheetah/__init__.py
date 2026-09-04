"""The Cheetah feed: a skin written for WeeWX, rendered here.

The point of this file, and the reason for the tag layer underneath it:
somebody who has used a skin for eight years keeps using it. Not ported, not
adapted -- the same directory of templates, unchanged.

Cheetah is a text templating engine, and it does not limit what a skin can be.
The Horizon skin is 882 lines of templates driving 1640 lines of JavaScript
and a chart library. What limited a skin was never the engine; it was that the
only structured data available was whatever could be squeezed through a tag,
one page at a time. That is what `tags.py` and the JSON feed are for.

## Cheetah is this feed's dependency, not the core's

The core needs nothing outside the standard library, and that stays true.
Cheetah is imported here and nowhere else, so a station whose Cheetah broke on
a new Python loses a website and keeps recording. It is the first thing to
break on a new Python, which is exactly why it is kept at arm's length.

## Loudly, not silently

A skin that renders at 95% is worse than one that does not render at all: the
page looks right, one number is missing or wrong, and it reads as our bug.
Every tag a template asked for and did not get is counted, and the feed says
so after every run. `weewx-evo feeds check <skin>` renders a skin and reports
nothing else.

## What a template is

Arbitrary Python, compiled and run. Installing a skin from the internet is
running somebody's code, exactly as installing a driver is. That is worth
knowing before it is worth arguing about: it is said here, in the settings
page, and in the install command.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ... import language as language_module
from ... import series as series_module
from ... import units, weewxconf
from ...options import Group, Option
from ...series import Reader
from ...tags import Tags
from .. import Produced, archive_names

log = logging.getLogger(__name__)

#: How the spans a summary is generated over are named, and how the file that
#: comes out of one is dated. WeeWX's, so a skin's `[[SummaryByMonth]]`
#: produces `NOAA-2026-08.txt` here too.
SUMMARIES = {
    "SummaryByDay": ("day", "%Y-%m-%d"),
    "SummaryByMonth": ("month", "%Y-%m"),
    "SummaryByYear": ("year", "%Y"),
}

#: Turning the rendered text into bytes. `html_entities` is WeeWX's default
#: and the safest: it writes plain ASCII with everything else as an entity, so
#: a page survives a web server that says nothing about its encoding.
ENCODINGS = ("html_entities", "utf8", "strict_ascii", "normalized_ascii")

#: Files a skin ships that are not templates: stylesheets, fonts, a chart
#: library. Copied as they are.
COPY_SUFFIXES = (".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg",
                 ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map", ".webp",
                 ".txt", ".json", ".xml", ".webmanifest")


class CheetahFeed:
    """Renders one skin."""

    trigger = "record"

    def __init__(self, reader: Reader, skin: Path, tags: Tags,
                 encoding: str = "html_entities",
                 copy_static: bool = True,
                 stale_ok: bool = True,
                 language: str = "",
                 derived: Sequence[str] = (),
                 extras: dict[str, Any] | None = None,
                 broker: dict[str, Any] | None = None) -> None:
        self.reader = reader
        #: The skin's own directory, holding skin.conf and the templates.
        self.skin = Path(skin)
        self.tags = tags
        self.encoding = encoding
        self.copy_static = copy_static
        #: What to put in the skin's own `[Extras]`, over whatever it says
        #: itself. WeeWX has this under `[StdReport][[Report]][[[Extras]]]`
        #: and it is not a nicety: a skin's Extras are where its author put
        #: the things an operator is meant to change, and editing the skin
        #: to change them means losing it at the next update.
        self.extras = dict(extras or {})
        #: What a browser needs to reach the MQTT broker, from the upload
        #: that already knows it. Empty when no MQTT upload is configured,
        #: and then a skin's own settings stand as they are.
        self.broker = dict(broker or {})
        #: What the operator set on the skin's own settings page, going into
        #: `[DisplayOptions]` over what the skin says. Empty for a skin that
        #: declares no options, which is every skin from outside.
        self.display: dict[str, Any] = {}
        #: Which of the skin's translations to run it in. Empty means what
        #: the skin itself says, which is usually English.
        self.language = str(language or "").strip()
        #: Readings this installation works out rather than reads off the
        #: hardware. A skin says so on the page, and it should: a dewpoint
        #: out of a formula and one off a sensor are different claims.
        self.derived = tuple(derived)
        #: Honour a template's `stale_age`. A year page built from daily
        #: averages says the same thing at ten past as at ten o'clock.
        self.stale_ok = stale_ok
        self.rendered = 0
        #: Every pass together, for the one line the runner logs. `rendered`
        #: stays per pass, because `_scope` resets it and the sweep reads it.
        self.rendered_all = 0
        self.skipped = 0
        self.failed: list[tuple[str, str]] = []
        #: Which "SummaryBy" files exist, for `$SummaryByMonth` in a template.
        self.summaries: dict[str, list[str]] = {}
        #: What the skin's own Python contributed. Built once per run: an
        #: extension may walk the whole archive, and doing that for every
        #: page of a forty-page skin is forty times too often.
        self.contributed: list[Any] = []
        #: The plain values at the top of skin.conf, for `$SKIN_NAME`.
        self.skin_values: dict[str, Any] = {}
        #: Whether the skin decides which units it is shown in. False once
        #: the operator has picked a system on the feed's own page.
        self.skin_units = True
        #: When the skin last changed. Filled on the first page of a run
        #: and cleared at the start of the next, so an edit is picked up
        #: without stat-ing the whole skin forty times per run.
        self._skin_mtime: float | None = None
        #: Which series this feed reads, by name. `$archives.<name>` for
        #: this one hands back `self.tags` rather than a second connection
        #: to the file already open.
        self.archive: str = ""
        #: Every place this feed shows, in the order pages present them.
        #: One dict each: name, label, code, colour, url, its own settings,
        #: its file, and -- filled by `_bind` at the top of a run -- its
        #: reader, its Tags and the span its own archive covers.
        #:
        #: A plain dict and not a dataclass, because a template walks it and
        #: Cheetah's NameMapper tries `obj[name]` before the attribute:
        #: anything mapping-shaped has to *be* a mapping. That is the trap
        #: that made `$obs.label` hand back the string "label".
        #:
        #: Empty on every installation with one series, and that is the gate
        #: everything else hangs off: no site pass, no subdirectory, no new
        #: tag with anything in it.
        self.places: list[dict[str, Any]] = []
        #: Which pass is being rendered: "place" or "site".
        self.scope = "place"
        #: The roster entry of the place being rendered, or None on a site
        #: page. Set by `_scope` and read by `_search_list`.
        self.here: dict[str, Any] | None = None
        #: What the pass being rendered covers. Read instead of
        #: `self.reader.span()` so that one place's empty archive does not
        #: decide another place's pages.
        self.span: tuple[int, int] | None = None
        #: Every Tags this run built, so the skin's words reach all of them
        #: and one report covers the page.
        self.every_tags: list[Tags] = [tags]
        #: What each pass wrote and how it went, for a sweep that consults
        #: its own failures rather than somebody else's.
        self.passes: list[tuple[str, Path, list[Path], list]] = []
        #: What the site is called, when it is more than one place. Empty
        #: means the installation's own `station.name` -- which is not
        #: `$station.location` on a site page, because under `Placed` that
        #: is the *default place's* label, and an overview headed
        #: "Kirchdorf" listing four places is the forty-months lie again.
        self.site_title = ""
        #: Which of the skin's pages each place gets. Empty means all of
        #: them, which is what one place has always had.
        self.place_pages: tuple[str, ...] = ()
        #: How many places the sidebar shows before it folds them away.
        self.places_fold = 6
        #: Which places this instance was told to show, in that order. Empty
        #: means every one it was handed.
        self.shown: tuple[str, ...] = ()
        #: Whether this feed was told to publish one place. Read instead of
        #: the list above rather than alongside it: two settings that can
        #: each decide how many places there are would otherwise say
        #: something neither of them says alone -- a list naming two under a
        #: switch that says one -- and nothing on the published site could
        #: show which of the two had won.
        self.solo = False
        #: Whether the *installation* keeps more than one series, as opposed
        #: to how many this feed shows. They are different questions and the
        #: chart files answer the first one: the JSON feed writes a
        #: subdirectory per place whenever the registry has several, and it
        #: has no way of knowing that a skin was narrowed to one of them.
        #:
        #: Narrowed without this, a Deck showing one place of two looked for
        #: the flat manifest, found one listing no plots, and rendered every
        #: chart grid empty -- with no message, because the file was there.
        self.many_series = False
        #: The forecast store, when this station keeps one. Opened once for
        #: the feed and shared by every place: the rows name the series they
        #: are for, so one file answers all of them.
        self.forecast_store: Any = None
        #: What building another place's tags needs. Kept rather than closed
        #: over, because they are built *after* the skin's configuration has
        #: been read, and that happens in `produce`.
        self._settings: Any = None
        self._spoken: Any = None
        self._plots: Any = ()
        self._extra_groups: dict[str, str] = {}

    def narrow(self) -> None:
        """Keep only the places this instance was told to show.

        In the operator's order, and this feed's own place first whatever
        they said: a site whose overview links to places but not to the one
        its own pages are built from would publish an archive nothing on it
        can reach. Put first and kept rather than refused, because a
        hand-edited file has to stay fixable from the page it is edited on.

        A name that is not a place is dropped and said once. Silently
        keeping it would mean a directory nothing writes and a link that
        404s on somebody else's web host.
        """
        # Remembered before the list is cut: what the chart feed did is
        # decided by the registry, not by this skin's own narrowing.
        self.many_series = self.many_series or len(self.places) > 1
        if self.solo:
            # Told on its own page that this feed is about one place, so the
            # list is not consulted at all. Keeping the entry rather than
            # emptying the list outright, because it carries that place's
            # colour, its code and its own settings; `_home()` is the
            # stand-in for a feed whose place was not among those handed in.
            self.places = [one for one in self.places
                           if one["name"] == self.archive]
            return
        if not self.shown or not self.places:
            return
        by_name = {one["name"]: one for one in self.places}
        unknown = [name for name in self.shown if name not in by_name]
        if unknown:
            log.warning("%s is set to show %s, which %s not a series here; "
                        "left out", self.skin.name, ", ".join(unknown),
                        "are" if len(unknown) > 1 else "is")
        picked = [by_name[name] for name in self.shown if name in by_name]
        home = by_name.get(self.archive)
        if home is not None:
            if home in picked:
                picked.remove(home)
            picked.insert(0, home)
        self.places = picked

    @property
    def several(self) -> bool:
        """Whether this feed shows more than one place.

        The gate for every difference in this file, and it is *how many this
        feed renders* rather than `Register.several()`. A one-entry
        `archives.toml` is `overriding()` -- the settings page correctly says
        `station.*` has moved -- and is not several, and that is the case
        nothing would otherwise be tested at.
        """
        return len(self.places) > 1

    @property
    def archive_files(self) -> dict[str, Path]:
        return {one["name"]: one["file"] for one in self.places}

    # -- the feed ---------------------------------------------------------

    def produce(self, into: Path, now: float | None = None) -> Produced:
        """Every place this feed shows, one pass each, into one directory.

        A loop around what this already did. The alternative -- one whole
        `CheetahFeed` per place -- shares nothing, *including* the things
        that have to be shared: the skin's configuration, the moment the run
        is for, the one scan of the skin's timestamps and the tally of
        unanswered tags. Each of those would then have to be handed back one
        at a time, which is more places to get it wrong rather than fewer.
        One instance shares everything by default and has to name what
        resets, and that list is short: it is exactly what this function
        resets today, and it lives in `_scope` where it reads in one screen.

        With one place there is one pass, into the directory it was given,
        and nothing below behaves differently.
        """
        started = time.time()
        into = Path(into)
        into.mkdir(parents=True, exist_ok=True)
        # Asked again this run, and once for the run rather than once per
        # place: a forty-page skin already stats its own directory once, and
        # three places must not make that three.
        self._skin_mtime = None
        self.passes = []
        self.rendered_all = 0

        conf = self._skin_conf()
        if conf is None:
            return Produced(directory=into,
                            note=f"no skin.conf in {self.skin}")

        # Every other place, open for the length of this run and closed by
        # the context manager on the way out.
        #
        # `$archives.<name>` used to open a connection on demand and never
        # close it, and the runner rebuilds this feed every pass -- four
        # places at five minutes is about eleven hundred descriptors a day.
        # That is the shape of the incident that took an instance down at
        # 477 of them, and it surfaces as a feed unable to read plots.toml,
        # nowhere near the leak.
        wanted = {one["name"] for one in self.places
                  if one["name"] != self.archive}
        with series_module.opened(self.archive_files, wanted=wanted) as opened:
            # This feed's own is already open, on the runner's thread and for
            # this pass. `series.opened` never sees it, so nothing here closes
            # a connection the runner still owns.
            if self.archive:
                opened[self.archive] = self.reader
            files = self._run(conf, into, opened)

        swept = self._sweep_all() + self._orphans(into)

        note = (f"{self.rendered_all} page(s) in {time.time() - started:.2f}s"
                + (f", {self.skipped} still fresh" if self.skipped else "")
                + (f", {len(self.failed)} failed" if self.failed else "")
                + (f", {swept} removed" if swept else ""))
        if self.several:
            note += f"; {len(self.passes)} pass(es)"
        # Every series the run touched, not just this one. A page built out
        # of another place put all of its unanswered tags in that place's own
        # tally, where nothing ever printed them -- so an overview naming a
        # reading no station records looked perfect.
        count, unanswered = self.report()
        if count:
            # The whole reason this is worth building rather than guessing at:
            # a list of what a skin asked for and did not get.
            log.warning("%s: %s", self.skin.name, unanswered)
            note += f"; {count} tag(s) unanswered"
        log.info("%s: %s", self.skin.name, note)
        return Produced(directory=into, files=files, note=note)

    def _run(self, conf: dict[str, Any], into: Path,
             readers: dict[str, Any]) -> list[Path]:
        """The passes, in order, with every reader already open."""
        self._bind(readers)

        # The skin's own words and units first, its own code second. The
        # other way round, an extension is handed a formatter that has not
        # been told what the skin shows things in, and every number it
        # works out comes back in the unit the archive holds -- a chart
        # captioned in Fahrenheit on a page that says Celsius everywhere
        # else, with nothing anywhere saying why.
        self._extras(conf)

        files: list[Path] = []
        if self.several:
            # The pages about the site rather than about one place, at the
            # root. Rendered through this feed's own place, which is the one
            # it reads; an overview reaches the others by name.
            files += self._scope(conf, "site", into, self._home())
        for place in self.places or [self._home()]:
            files += self._scope(
                conf, "place",
                into / place["name"] if self.several else into, place)

        if self.copy_static:
            # Once, at the root. Eight copies of a charting library is eight
            # megabytes up the FTP link every time an asset changes.
            files += self._copy(conf, into)
        return files

    # -- the places -------------------------------------------------------

    def _language(self) -> Any:
        """The language this feed renders in, for a second place's forecast."""
        return self._spoken

    def _home(self) -> dict[str, Any]:
        """This feed's own place, or a stand-in where it shows only one."""
        for one in self.places:
            if one["name"] == self.archive:
                return one
        return {"name": self.archive, "label": "", "code": "", "color": "",
                "url": "", "settings": self._settings, "file": None,
                "reader": self.reader, "tags": self.tags,
                "covers": self.reader.span(), "has_data": True,
                "path": "", "here": False}

    def _bind(self, readers: dict[str, Any]) -> None:
        """Give every place its reader, its tags and its span, before a page.

        Before, because two things need it and both are per page: the place
        switcher on `month-2026-05.html` has to know which places *have* a
        May 2026 before it writes a link into a directory this run may never
        create, and a place with no records at all must not get one.
        """
        home = None
        for one in self.places:
            one["reader"] = readers.get(one["name"])
            one["covers"] = one["reader"].span() if one["reader"] else None
            one["has_data"] = one["covers"] is not None
            if one["name"] == self.archive:
                home = one

        # One moment for every place. Without it "today" is a different
        # calendar day per place the moment one console is behind, and an
        # overview compares Tuesday with Wednesday in adjacent columns.
        #
        # At one place this is that reader's own last record, which is
        # exactly what `Tags.__init__` works out for itself -- so a
        # single-place page is unchanged to the second.
        seen = [one["covers"][1] for one in self.places if one["covers"]]
        when = max(seen) if seen else self.tags.when

        for one in self.places:
            if one is home:
                # The feed's own place keeps the tags it was built with. The
                # runner builds this feed with that place's settings already
                # wrapped in `archives.Placed`, so they are the same object
                # this loop would make -- and it has to be the *same* one,
                # because `_extras` configures it and every other place
                # shares its dictionaries by reference.
                one["tags"] = self.tags
            elif one["reader"] is None:
                # Stays None, and is not given somebody else's tags. Handing
                # back another place's readings under this place's heading is
                # the exact failure archives exist to prevent, and an empty
                # Tags cannot be built without a connection to nothing. Every
                # reader guards on `has_data`; `$archives.<that name>` records
                # a named miss and answers `Unknown`, as it does today.
                one["tags"] = None
            else:
                one["tags"] = _tags_for(
                    one["settings"] or self._settings, one["reader"],
                    plots=self._plots, extra_groups=self._extra_groups,
                    when=when, like=self.tags)
                # Its own forecast, out of the one file, keyed on its own
                # name. Sharing the store rather than opening a second: the
                # rows are what separate the places, not the file.
                if self.forecast_store is not None:
                    _install_forecast(one["tags"], one["settings"],
                                      self._language(), archive=one["name"],
                                      store=self.forecast_store)
        self.tags.when = when

        by_name = {one["name"]: one["tags"] for one in self.places
                   if one["tags"] is not None}
        for one in by_name.values():
            # `$archives.<name>` is now a lookup into readers this run opened
            # and this run closes, not an opener. That is the whole of the
            # leak fix -- and it makes `$archives.<this place>` the *same*
            # object `$day` comes out of, so the two cannot disagree.
            one.open_archive = by_name.get
            one.archive_names = tuple(by_name)
            # One tally for the run.
            one.missing = self.tags.missing
        self.every_tags = list(dict.fromkeys(
            [self.tags, *by_name.values()]))

    def _scope(self, conf: dict[str, Any], scope: str, into: Path,
               place: dict[str, Any]) -> list[Path]:
        """One pass over the generator tree, for one place or for the site.

        Everything a run counts is reset here and nowhere else, and the
        reason is the forty-months bug in its other shape. There, a span was
        bound above the pages that varied it, so forty archived months all
        printed August under correct headings. A place bound above the pass
        that varies it has the identical shape and the identical symptom: it
        renders, it is plausible, and nothing on the page can tell.

        `summaries` is not bookkeeping either: it is the month list a
        template loops over to build its own archive menu, so a place that
        leaks it publishes its neighbour's months as its own.
        """
        if place["tags"] is None:
            log.info("%s: %s has no records yet, so no pages for it",
                     self.skin.name, place["name"])
            return []
        self.scope = scope
        self.here = place
        self.tags = place["tags"]
        self.reader = place["reader"]
        self.span = place["covers"]
        self.rendered = self.skipped = 0
        self.failed = []
        self.summaries = {name: [] for name in SUMMARIES}
        # Rebuilt per pass, not once per run. A skin's extensions capture the
        # reader and the tags when they are constructed, and Deck's rain tags
        # walk the whole archive there for the last rain and the longest dry
        # spell. Built once, every place's pages print the home place's rain.
        self.contributed = self._extensions(conf)

        into.mkdir(parents=True, exist_ok=True)
        made: list[Path] = []
        section = conf.get("CheetahGenerator") or conf.get("FileGenerator")
        if isinstance(section, dict):
            made += self._generate(section, "", into, conf)
        elif scope == "place":
            log.warning("%s has no [CheetahGenerator]; nothing to render",
                        self.skin)
        self.rendered_all += self.rendered
        self.passes.append((scope if scope == "site" else place["name"],
                            into, made, list(self.failed)))
        return made

    def _sweep_all(self) -> int:
        """Each pass sweeps its own directory, on its own failures.

        One broken template anywhere used to sweep nothing anywhere. With
        places that means one bad page at one site leaving every stale page
        at every other -- and the site that broke is the one nobody is
        looking at.
        """
        removed = 0
        for _label, where, made, failed in self.passes:
            removed += self._sweep(where, made, failed)
        return removed

    def _orphans(self, into: Path) -> int:
        """A place this feed no longer shows keeps publishing until told.

        The same charter as `_sweep`, one level down: `.html` only, `NOAA/`
        and `day-archive/` left alone, the directory removed only when it
        ends up empty, and every removal named.

        Only for a name that *is* a place -- one this run was handed and did
        not render, which is what unticking a place on the settings page
        produces. Never for an arbitrary directory at the root: guessing that
        an unknown one used to be a place is how a feed deletes somebody's
        photographs.

        The limit that follows is real and is worth writing down: a place
        deleted from `archives.toml` outright is no longer a name this feed
        is handed, so its directory stays. The Archives page says so when it
        removes one; this cannot, because by then there is nothing left to
        recognise it by.
        """
        if not self.several or any(failed for *_rest, failed in self.passes):
            return 0
        written = {where.name for _label, where, _made, _failed in self.passes}
        removed = 0
        for one in self.places:
            if one["name"] in written:
                continue
            where = into / one["name"]
            if not where.is_dir():
                continue
            gone = []
            for path in where.glob("*.html"):
                try:
                    path.unlink()
                    gone.append(path.name)
                except OSError as exc:
                    log.warning("could not remove %s: %s", path, exc)
            if gone:
                log.info("%s: %s is no longer shown; removed %d page(s)",
                         self.skin.name, one["name"], len(gone))
                removed += len(gone)
            try:
                where.rmdir()
            except OSError:
                # Something else is in there -- NOAA reports, a person's own
                # file. Left alone, on purpose.
                pass
        return removed

    # -- the other series -------------------------------------------------

    def _reach(self, readers: dict[str, Any]) -> None:
        """Give every series' tags to every series' tags.

        Three things are shared on purpose, and each of them was wrong
        before:

        - **The skin's configuration.** `_extras` and `_units` had run over
          this feed's own tags alone, so `$archives.x.day.outTemp.max` beside
          `$day.outTemp.max` came out of a different `Target`: different
          decimals, different unit, different language, on one line of one
          table, with every number correct.
        - **The moment.** Each series defaulted `when` to its *own* last
          record, so with one console an hour behind, "today" was Tuesday in
          one column and Wednesday in the next.
        - **The tally.** One list, so one report covers the page.

        Sharing the objects rather than copying them is what makes the first
        of those true for good: `_extras` runs once, over `self.tags`, and
        every series is looking at the same dictionaries.
        """
        if not self.places:
            return
        built: dict[str, Any] = {self.archive: self.tags}
        for name, (_where, placed) in sorted(self.places.items()):
            if name in built:
                continue
            reader = readers.get(name)
            if reader is None:
                # Configured but not written yet, which is the ordinary
                # state of a place somebody added five minutes ago. Left
                # out, so `$archives.<name>` reports it as unanswered.
                continue
            built[name] = _tags_for(placed or self._settings, reader,
                                    plots=self._plots,
                                    extra_groups=self._extra_groups,
                                    like=self.tags)
        # The run's moment: the newest record anywhere. At one series this
        # is that reader's own last record, which is what it already was.
        latest = [one.when for one in built.values()]
        when = max(latest) if latest else self.tags.when
        names = tuple(sorted(built))
        for one in built.values():
            one.when = when
            one.open_archive = built.get
            one.archive_names = names

    def report(self) -> tuple[int, str]:
        """How many tags went unanswered across every series, and which.

        Worded exactly as `Tags.report`, and at one series it *is*
        `Tags.report` -- a page's log line must not change because the code
        behind it learned to count a second place.
        """
        asked = 0
        seen: dict[str, int] = {}
        counted: set[int] = set()
        for one in self._every_tags():
            asked += one.asked
            # By identity: `_bind` gives every place the *same* dict, so
            # adding each up would multiply every miss by the number of
            # places and report four hundred unanswered tags on a page that
            # had a hundred.
            if id(one.missing) in counted:
                continue
            counted.add(id(one.missing))
            for tag, count in one.missing.items():
                seen[tag] = seen.get(tag, 0) + count
        if not seen:
            return (0, f"{asked} tag(s), all answered")
        worst = sorted(seen.items(), key=lambda kv: -kv[1])
        named = ", ".join(f"{name} ({count})" for name, count in worst[:8])
        more = "" if len(worst) <= 8 else f", and {len(worst) - 8} more"
        said = f"{asked} tag(s), {len(seen)} not answered: {named}{more}"
        return (len(seen), said)

    def _every_tags(self) -> list[Tags]:
        """Every tag layer this run built, this feed's own first."""
        return self.every_tags or [self.tags]

    # -- reading the skin -------------------------------------------------

    def _skin_conf(self) -> dict[str, Any] | None:
        """The skin's configuration, in the language it is being run in.

        A WeeWX skin keeps its translations in `lang/de.conf` and so on, and
        those files are not word lists: they are whole skin configurations,
        carrying the unit system, the labels, the compass points and the
        texts together. `lang = de` in skin.conf selects one.

        The language file goes *under* skin.conf, which is WeeWX's order and
        the sensible one: the translation supplies everything, and anything
        the skin's author said explicitly still wins.
        """
        path = self.skin / "skin.conf"
        if not path.is_file():
            return None
        try:
            conf = weewxconf.read(path)
        except OSError as exc:
            log.error("could not read %s: %s", path, exc)
            return None

        code = self.language or str(conf.get("lang") or "").strip()
        if not code:
            return weewxconf.reparent(conf)
        spoken = _language_conf(self.skin / "lang", code)
        if not spoken:
            log.info("%s has no translation for %r; running it as written",
                     self.skin.name, code)
            return weewxconf.reparent(conf)
        merged = _merge(spoken, conf)
        merged["lang"] = code
        _apply_unit_system(merged)
        log.info("%s is being rendered in %r", self.skin.name, code)
        # Once, at the end: every merge above built plain dictionaries, and
        # a section without its parent breaks inheritance silently.
        return weewxconf.reparent(merged)

    def _extras(self, conf: dict[str, Any]) -> None:
        """Carry the skin's own settings and words into the tags.

        `[Extras]` is where a skin keeps whatever its author invented, and a
        template reads it as `$Extras.something`. `[Labels]` and `[Units]`
        are what things are called. All of it belongs to the skin, in the
        skin's language.
        """
        # Every place, not just this feed's own. Otherwise a page prints one
        # place's numbers with another place's words -- and only the words
        # would be wrong, which is the sort of thing that survives a review.
        # `_tags_for` shares the dictionaries, so in the ordinary case these
        # loops write the same object several times and cost nothing.
        every = self._every_tags()
        labels = conf.get("Labels")
        if isinstance(labels, dict):
            generic = labels.get("Generic")
            source = generic if isinstance(generic, dict) else labels
            words = {k: str(v) for k, v in source.items()
                     if isinstance(v, str)}
            for tags in every:
                tags.labels.update(words)
        almanac = conf.get("Almanac")
        if isinstance(almanac, dict) and almanac.get("moon_phases"):
            phases = almanac["moon_phases"]
            named = tuple(phases if isinstance(phases, list) else [phases])
            for tags in every:
                tags.moon_phases = named
        texts = conf.get("Texts")
        if isinstance(texts, dict):
            said = {k: str(v) for k, v in texts.items()
                    if isinstance(v, str)}
            for tags in every:
                tags.text.update(said)
        for name, into in (("Extras", "extras"),
                           ("DisplayOptions", "display")):
            found = conf.get(name)
            if isinstance(found, dict):
                for tags in every:
                    getattr(tags, into).update(found)
        # What the operator set on the skin's own page, over what the skin
        # says itself. A skin of ours declares those as `Option`s; one from
        # outside declares none and this does nothing.
        if self.display:
            block = conf.setdefault("DisplayOptions", {})
            if isinstance(block, dict):
                block.update(self.display)
            for tags in every:
                tags.display.update(self.display)
        # The broker, from the upload that already knows it. Before the
        # operator's own settings below, so anything they said by hand still
        # wins -- see `_broker_extras`.
        if self.broker:
            self._broker_extras(conf)
        # The operator's own, last: they are the reason this setting exists.
        if self.extras:
            for tags in every:
                tags.extras.update(self.extras)
            block = conf.setdefault("Extras", {})
            if isinstance(block, dict):
                block.update(self.extras)
        block = conf.get("Units")
        if isinstance(block, dict):
            self._units(block)
        language = conf.get("lang") or conf.get("Language")
        if isinstance(language, str):
            for tags in every:
                tags.language = language
        # Whatever the skin wrote at the top of its own file, `$SKIN_NAME`
        # and `$SKIN_VERSION` among them. A page prints them in its footer,
        # and only the skin knows what they say.
        self.skin_values = {k: v for k, v in conf.items()
                            if not isinstance(v, dict)}

    # -- walking the generator sections -----------------------------------

    def _extensions(self, conf: dict[str, Any]) -> list[Any]:
        """Run the skin's own Python, if it ships any.

        `search_list_extensions` names classes; each is handed the generator
        and asked what it wants to add. weewx-wdc ships eight of them and
        without them not one of its pages renders -- so a skin that brings
        code is not an edge case, it is the second one anybody tries.

        One failure costs that extension's names and nothing else. Half a
        page is worse than a named gap, and the tag report lists what was
        missing either way.
        """
        wanted = conf.get("CheetahGenerator", {}).get(
            "search_list_extensions") if isinstance(
                conf.get("CheetahGenerator"), dict) else None
        wanted = [str(x).strip() for x in _as_list(wanted) if str(x).strip()]
        if not wanted:
            return []

        from ... import skinkit

        # A skin from outside expects `import weewx` to work. The ones that
        # ship import from `skinkit` by name and this does nothing for
        # them, which is the difference between a skin we carry and one
        # somebody downloaded.
        if any(not name.startswith("weewx_evo.") for name in wanted):
            skinkit.install_weewx_names()
        span = self.span or self.reader.span()
        timespan = (skinkit.TimeSpan(span[0], span[1]) if span
                    else skinkit.TimeSpan(0, 0))
        generator = skinkit.Generator(conf, {}, self.reader,
                                      self.tags.target, self.tags,
                                      language=self.language,
                                      derived=self.derived,
                                      skin_dir=str(self.skin))
        lookup = generator.db_binder

        found: list[Any] = []
        for name in wanted:
            try:
                extension = self._one_extension(name, generator)
                if extension is None:
                    continue
                # Whatever it hands back, in the order it handed it back.
                # Not only dictionaries: an extension that does not override
                # `get_extension_list` returns itself, and then its methods
                # are the tags. Taking dictionaries alone dropped every one
                # of those, and the page said "'Unknown' object is not
                # iterable" without saying why.
                found.extend(extension.get_extension_list(timespan, lookup))
            except Exception as exc:
                # Named, and then left out. An extension that raises should
                # cost its own names rather than the whole site, and the
                # message says which one so it can be reported upstream.
                log.warning("the skin's %s did not run: %s: %s", name,
                            type(exc).__name__, exc)
                log.debug("%s", name, exc_info=True)
        if found:
            log.info("%s: %d thing(s) from its own code", self.skin.name,
                     len(found))
        return found

    def _one_extension(self, name: str, generator: Any) -> Any:
        """Import and build one, from wherever the skin keeps its code."""
        import importlib
        import importlib.util

        module_name, _, attribute = name.rpartition(".")
        if not module_name or not attribute:
            log.warning("%r does not name a class", name)
            return None

        module = None
        # `user.weewx_wdc` is where WeeWX puts a skin's code. A skin
        # installed here keeps it beside itself, which is the arrangement
        # that survives being copied to another machine.
        for where in (self.skin / "bin", self.skin.parent.parent / "bin",
                      self.skin, self.skin.parent):
            path = where / Path(*module_name.split(".")).with_suffix(".py")
            if not path.is_file():
                continue
            spec = importlib.util.spec_from_file_location(
                f"weewx_evo_skin_{self.skin.name}_{module_name}", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            break
        if module is None:
            try:
                module = importlib.import_module(module_name)
            except ImportError as exc:
                log.warning("%s: the skin's %s is not where it says: %s",
                            self.skin.name, module_name, exc)
                return None

        thing = getattr(module, attribute, None)
        if thing is None:
            log.warning("%s has no %s", module_name, attribute)
            return None
        return thing(generator)

    def _broker_extras(self, conf: dict[str, Any]) -> None:
        """Fill in a skin's MQTT settings from the configured upload.

        This is the point of it: without it the broker is configured twice --
        once as an upload, and once again in the skin's own `[Extras]`. Two
        places holding the same host, the same credentials and, worst of all,
        the same topic. A typo in the second one gives a page that renders
        perfectly and never updates, with nothing in any log to say why.

        Only where the skin has not been told already. A skin that names its
        own broker means it, and an operator who typed one into the feed's
        settings meant that too -- both come after this.

        The names are the ones weewx-wdc used, because Deck inherited them
        and any skin written against that convention gets this for free.
        """
        block = conf.setdefault("Extras", {})
        if not isinstance(block, dict):
            return
        mqtt = block.get("mqtt")
        mqtt = dict(mqtt) if isinstance(mqtt, dict) else {}

        # A skin that already says it is enabled has been configured by hand.
        # Leave all of it alone rather than filling in half from each place,
        # which is the arrangement nobody can debug.
        if _true(mqtt.get("mqtt_websockets_enabled")):
            log.debug("%s names its own broker; leaving it alone",
                      self.skin.name)
            return

        # Everything, not only what is empty. A skin that ships with the
        # switch off writes placeholders beside it -- Deck says `localhost`
        # and `9001` -- and those are not a configuration, they are what a
        # setting looks like before anybody has set it. Filling in only the
        # blanks would leave the placeholder host beside the real topic,
        # which connects to nothing and says nothing.
        mqtt.update({
            "mqtt_websockets_enabled": 1,
            "mqtt_websockets_host": self.broker.get("host", ""),
            "mqtt_websockets_port": self.broker.get("port", 9001),
            "mqtt_websockets_topic": self.broker.get("topic", "weather/loop"),
            "mqtt_websockets_ssl": 1 if self.broker.get("tls") else 0,
            "mqtt_websockets_path": self.broker.get("path", ""),
            "mqtt_websockets_username": self.broker.get("username", ""),
            "mqtt_websockets_password": self.broker.get("password", ""),
        })

        block["mqtt"] = mqtt
        self.tags.extras.setdefault("mqtt", {})
        if isinstance(self.tags.extras.get("mqtt"), dict):
            self.tags.extras["mqtt"] = mqtt
        log.info("%s: live updates from the %s broker at %s:%s, topic %s",
                 self.skin.name, "encrypted" if self.broker.get("tls") else "plain",
                 mqtt["mqtt_websockets_host"], mqtt["mqtt_websockets_port"],
                 mqtt["mqtt_websockets_topic"])

    def _units(self, block: dict[str, Any]) -> None:
        """Take the skin's own units, decimals and words.

        This is most of what makes a page look like itself. A skin that has
        printed one decimal of pressure in millibars for eight years keeps
        doing it here, because the numbers come from its file rather than
        from our defaults.

        The unit *groups* are the one part the operator can take back: a
        skin written for Fahrenheit still has to be publishable in Celsius,
        and picking a system on the feed's page is how that is said.
        """
        target = self.tags.target
        groups = block.get("Groups")
        if isinstance(groups, dict) and self.skin_units:
            for group, unit in groups.items():
                unit = str(unit)
                if group not in units.SYSTEMS[units.US]:
                    log.debug("%s names %r, which is not a unit group",
                              self.skin.name, group)
                    continue
                if (not units.can_convert(units.SYSTEMS[units.US][group],
                                          unit)
                        and unit != units.SYSTEMS[units.US][group]):
                    # Named and skipped rather than raised: one bad line in
                    # a skin should cost that line, not the whole site.
                    log.warning("%s wants %s in %r, which it cannot be shown "
                                "in; leaving it alone",
                                self.skin.name, group, unit)
                    continue
                target.overrides[group] = unit

        for key, into in (("StringFormats", target.formats),
                          ("Labels", target.labels),
                          ("TimeFormats", target.time_formats),
                          ("DeltaTimeFormats", target.deltatime_formats)):
            found = block.get(key)
            if isinstance(found, dict):
                into.update(found)

        ordinates = block.get("Ordinates")
        if isinstance(ordinates, dict):
            points = ordinates.get("directions")
            if isinstance(points, (list, tuple)) and len(points) > 1:
                target.ordinals = tuple(str(p) for p in points)
        if target.ordinals and not (
                isinstance(ordinates, dict)
                and ordinates.get("directions")):
            # The skin did not name its own, so it will fall back to the
            # English ones written into its code -- while everything we
            # print uses the station's language. A skin that reads a
            # bearing back out of that list then looks up "NO" among N,
            # NNE, NE and raises. Written in so that both sides agree.
            block.setdefault("Ordinates", {})["directions"] = list(
                target.ordinals)

        degree = block.get("DegreeDays")
        if isinstance(degree, dict):
            for reading, key in (("heatdeg", "heating_base"),
                                 ("cooldeg", "cooling_base"),
                                 ("growdeg", "growing_base")):
                said = degree.get(key)
                # Written as a pair, "65, degree_F": the number alone would
                # not say whether it meant Fahrenheit or Celsius, and the
                # two are eighteen degrees apart.
                if isinstance(said, (list, tuple)) and len(said) >= 2:
                    try:
                        # On every place: `target` is one shared object for
                        # the run, so its overrides and formats are applied
                        # once above, but these are read off each Tags.
                        for tags in self._every_tags():
                            tags.degree_day_bases[reading] = (
                                float(said[0]), str(said[1]))
                    except (TypeError, ValueError):
                        log.warning("%s: %s = %r is not a temperature",
                                    self.skin.name, key, said)

    def _generate(self, section: dict[str, Any], name: str, into: Path,
                  conf: dict[str, Any],
                  inherited: dict[str, Any] | None = None) -> list[Path]:
        """One `[CheetahGenerator]` section and everything under it.

        Options inherit downwards, as everywhere in a WeeWX configuration: an
        `encoding` on the generator applies to every template in it unless one
        says otherwise. Getting that wrong produces a site where half the
        pages are in the wrong character set.
        """
        settled = {**(inherited or {}),
                   **{k: v for k, v in section.items()
                      if not isinstance(v, dict)}}
        made: list[Path] = []

        for key, value in section.items():
            if not isinstance(value, dict):
                continue
            deeper = dict(settled)
            if key in SUMMARIES and "summarize_by" not in value:
                # `[[SummaryByMonth]]` means one file per month without
                # having to say so.
                deeper["summarize_by"] = key
            made += self._generate(value, key, into, conf, deeper)

        if "template" in settled:
            made += self._render(settled, name, into)
        return made

    def _render(self, options: dict[str, Any], name: str,
                into: Path) -> list[Path]:
        """One template, over one span or over many."""
        # Which pass this section belongs to. One inherited word, so
        # `[[Site]] scope = site` covers everything under it and a skin that
        # says nothing gets what it has always had. A skin with no `[[Site]]`
        # section is still multi-place: its pages are rendered once per place
        # and its site simply has no overview.
        wanted = str(options.get("scope") or "place").strip().lower()
        if wanted == "solo":
            # Rendered only where this feed shows one place. The mirror of
            # `site`, and it exists for the pair a site may have exactly one
            # of: the web app manifest and the offline page. A `scope = site`
            # section is not rendered at all at one place -- it cannot be, or
            # the overview would be written over that place's own index -- so
            # the pair has to exist twice, and without this word the
            # place-scoped copy is also written N times on a site that
            # already has the one at its root. Under one origin two manifests
            # give a browser competing install identities, and nothing links
            # the extra copies anyway.
            if self.several or self.scope != "place":
                return []
        elif wanted != self.scope:
            return []

        # Which pages a place gets, where the operator has narrowed them. The
        # skin names its own pages, one word per section, inherited -- so the
        # core learns nothing about any particular skin, and a skin from
        # outside that names none is untouched. Five places with every page
        # each is what goes up the FTP link every run.
        page_tag = str(options.get("place_page") or "").strip()
        if page_tag and self.place_pages and page_tag not in self.place_pages:
            return []

        template = self.skin / str(options["template"])
        if not template.is_file():
            log.warning("no such template: %s", template)
            self.failed.append((str(options["template"]), "not found"))
            return []

        span = self.span
        if span is None:
            return []
        summarize = str(options.get("summarize_by") or "").strip()
        if self.scope == "site" and summarize in SUMMARIES:
            # A site summary page would be frozen by the finished-month rule
            # below the moment this place's month ended, while another
            # place's month was still moving -- it would work, and then
            # quietly stop, which is the worst of the three behaviours
            # available. Named rather than rendered.
            log.warning("%s: %s summarises a span and is marked "
                        "scope = site; a site page cannot summarise a span "
                        "that means something different at each place. "
                        "Leaving it out.", self.skin.name, name)
            return []
        encoding = str(options.get("encoding")
                       or self.encoding).strip().lower().replace("-", "")

        made: list[Path] = []
        for start, stop in self._spans(span, summarize):
            # A summary file is named after the start of its span and a
            # to-date file after the end, because one is "August" and the
            # other is "as of now".
            stamp = start if summarize in SUMMARIES else stop
            # A section may say what its file is called. WeeWX takes the name
            # from the template and nothing else, which cannot express the one
            # thing a site of several places needs: the root's `index.html`
            # and each place's `index.html` are different pages, and two
            # templates in one skin directory cannot both be called
            # `index.html.tmpl`. Given a name it is used as written, dated the
            # same way a template name is so a summary can still name itself.
            named = str(options.get("filename") or "").strip()
            relative = Path(str(options["template"])).parent / (
                time.strftime(named, time.localtime(stamp)) if named
                else _filename(template.name, stamp))
            target = into / relative

            if summarize in SUMMARIES:
                dated = time.strftime(SUMMARIES[summarize][1],
                                      time.localtime(start))
                if dated not in self.summaries[summarize]:
                    self.summaries[summarize].append(dated)
                # A month that has already been written and is over cannot
                # change. Rewriting every one of them every archive interval
                # is how a station with ten years of history spends a minute
                # of every five on the past.
                if target.exists() and stop <= span[1] and start < span[1] \
                        and not (start <= span[1] <= stop):
                    self.skipped += 1
                    made.append(target)
                    continue

            if self._fresh(target, options, template):
                self.skipped += 1
                made.append(target)
                continue

            written = self._one(template, target, (start, stop), name,
                                relative, encoding, options,
                                summarize=summarize)
            if written is not None:
                made.append(written)
        return made

    def _spans(self, span: tuple[int, int],
               summarize: str) -> list[tuple[int, int]]:
        if summarize in SUMMARIES:
            unit = SUMMARIES[summarize][0]
            return list(self.reader.buckets(span[0], span[1], unit))
        return [(span[0], span[1])]

    def _sweep(self, into: Path, made: list[Path],
               failed: list | None = None) -> int:
        """Remove pages this skin no longer produces.

        A template that is deleted leaves its page behind, and the export
        keeps sending it: `about.html` was served for hours after the file
        that made it was gone, still carrying the previous version of the
        whole skin.

        Only `.html` at the top level of the output -- what this feed
        writes. Not the assets, not `NOAA/`, not `day-archive/`, and
        nothing a person put there themselves.

        Not at all after a failed page: a template that raises produces
        nothing this run, and its page must not be swept away for that.

        `failed` says *whose* failures decide. Left out it is this feed's
        own, which is what it has always been; `_sweep_all` hands in each
        pass's, because one broken template at one place must not leave every
        stale page standing at all the others.
        """
        if self.failed if failed is None else failed:
            return 0
        keep = {path.resolve() for path in made}
        removed = []
        for path in into.glob("*.html"):
            if path.resolve() in keep:
                continue
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as exc:
                log.warning("could not remove %s: %s", path, exc)
        if removed:
            # Said out loud. A file vanishing without a word is what makes
            # somebody stop trusting a tool.
            log.info("%s: removed %d page(s) no longer in the skin: %s",
                     self.skin.name, len(removed), ", ".join(sorted(removed)))
        return len(removed)

    def _fresh(self, target: Path, options: dict[str, Any],
               template: Path | None = None) -> bool:
        """Whether this file is young enough to leave alone.

        Two questions, and the second one is the one that bites. Is the
        page younger than its `stale_age` -- and is it younger than the
        things it was built from?

        Without the second, editing a template does nothing: the page is
        still "fresh" and is skipped, for hours, on a site where every
        other page updated. That was real, and it is why `make` has
        compared timestamps since 1976.
        """
        if not self.stale_ok:
            return False
        try:
            stale = int(float(str(options.get("stale_age")).strip()))
        except (TypeError, ValueError):
            return False
        try:
            written = target.stat().st_mtime
        except OSError:
            return False
        if time.time() - written >= stale:
            return False
        return written >= self._skin_changed(template)

    def _skin_changed(self, template: Path | None = None) -> float:
        """When the skin last changed: its newest template or config file.

        Computed once per run -- a forty-page skin would otherwise stat the
        same directory forty times.

        Every include counts, not only the ones this page uses. A page
        cannot easily say which those are (a skin may compute one:
        `#include $get_celestial_icon($body, 'rise')`), and rebuilding a
        page because a sibling's include moved costs one render. Not
        rebuilding it costs a page that is quietly out of date.
        """
        if self._skin_mtime is None:
            newest = 0.0
            for path in self.skin.rglob("*"):
                if path.suffix in (".tmpl", ".inc", ".conf", ".py"):
                    try:
                        newest = max(newest, path.stat().st_mtime)
                    except OSError:
                        continue
            self._skin_mtime = newest
        if template is not None:
            try:
                return max(self._skin_mtime, template.stat().st_mtime)
            except OSError:
                pass
        return self._skin_mtime

    # -- one page ---------------------------------------------------------

    def _one(self, template: Path, target: Path, span: tuple[int, int],
             page: str, relative: Path, encoding: str,
             options: dict[str, Any], summarize: str = "") -> Path | None:
        try:
            import Cheetah.Template
        except ImportError:
            log.error("this feed needs Cheetah3, which is not installed: "
                      "pip install CheetahTemplate3")
            self.failed.append((template.name, "Cheetah3 is not installed"))
            return None

        _teach_cheetah()
        _CURRENT.skin = self.skin
        _CURRENT.tags = self.tags
        try:
            # `file=`, not `source=`: that is what makes an include an
            # include, and an include is its own compilation unit with its
            # own imports.
            rendered = Cheetah.Template.Template(
                file=str(template),
                searchList=self._search_list(span, page, relative,
                                             encoding,
                                             summarize)).respond()
        except Exception as exc:
            # One template, not the site. A skin with one broken page should
            # still publish the other forty.
            log.error("%s: %s: %s", template.name, type(exc).__name__, exc)
            # The traceback at debug: a one-line message says which page
            # broke, and the line inside the skin that did it is the next
            # question every single time.
            log.debug("%s failed", template.name, exc_info=True)
            self.failed.append((template.name, f"{type(exc).__name__}: {exc}"))
            return None

        try:
            data = _encode(str(rendered), encoding)
        except Exception as exc:
            log.error("%s could not be written as %s: %s", template.name,
                      encoding, exc)
            self.failed.append((template.name, str(exc)))
            return None

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            partial.write_bytes(data)
            partial.replace(target)
        except OSError as exc:
            log.error("could not write %s: %s", target, exc)
            self.failed.append((template.name, str(exc)))
            return None

        self.rendered += 1
        return target

    def _search_list(self, span: tuple[int, int], page: str, relative: Path,
                     encoding: str, summarize: str = "") -> list[Any]:
        """What `$something` is looked up in, in order.

        The tags go last on purpose. Anything before them can answer first,
        and the tag layer answers everything -- an unknown name comes back as
        a counted miss rather than falling through, which is what makes the
        report at the end complete.
        """
        from ...tags import Span

        start = time.localtime(span[0])
        about = {
            "month_name": time.strftime("%b", start),
            "year_name": start[0],
            "encoding": encoding,
            "page": page,
            "filename": relative.as_posix(),
        }
        # Which places there are, which one this page is for, and how to
        # reach the others. In `about` rather than in `[Extras]`: every key
        # under Extras becomes a top-level tag and Extras is searched
        # *before* the tag layer, which is how a section called `forecast`
        # once shadowed `$forecast` itself and turned every `$forecast.days`
        # into "cannot find 'days'". `about` is first in the list below, so
        # it also wins over the Deck option of the same name arriving through
        # `[DisplayOptions]`.
        #
        # Every one of them is *always* defined, empty rather than absent:
        # `$varExists` is true for anything the tag layer sees, so a name
        # that is only sometimes set is a trap rather than a convenience.
        about.update(self._about(span))
        # A "SummaryBy" template lists its own siblings: `#for $m in
        # $SummaryByMonth`.
        summaries = {name: list(dates)
                     for name, dates in self.summaries.items()}
        # The span this page is for. A month page's `$month` is that month,
        # not the current one -- and that took a rewrite to be true.
        #
        # `$month` came from the tag layer, where it means "the month we are
        # in", so every page in a `SummaryByMonth` run printed the same
        # figures: forty archived months, all showing August, all identical.
        # The heading said `05/2026` while the numbers beside it were
        # August's, and nothing on the page could tell.
        #
        # So a summary page gets its own span under the name its template
        # asks for. Only that one name: `$year` on a month page still means
        # the year, which is what a month page comparing itself to its year
        # needs.
        here = {"timespan": Span(self.tags, span, page or "current"),
                "start": span[0], "stop": span[1]}
        if summarize in SUMMARIES:
            named = SUMMARIES[summarize][0]
            here[named] = Span(self.tags, span, named)
        # The skin's own sections, flat. A template says `$observations`
        # rather than `$DisplayOptions.observations`, because WeeWX puts the
        # contents of those sections into the search list directly. Before
        # the tags, so a skin can name something the tag layer also has.
        # The skin's own code before its own sections, and both before the
        # tags: an extension is written to add names, and a name it adds
        # must not be swallowed by the layer that answers everything.
        return [about, summaries, here, *self.contributed,
                self.skin_values, dict(self.tags.display),
                dict(self.tags.extras), self.tags]

    def _about(self, span: tuple[int, int]) -> dict[str, Any]:
        """The places, as a page sees them.

        Empty everywhere at one place, so every guarded include renders
        nothing and a single-place site is unchanged.
        """
        if not self.several:
            base = str(self.tags.extras.get("base_path") or "/")
            return {
                "places": [], "places_here": [], "here_place": None,
                # Whether the *installation* keeps several series, which is
                # a different question from how many this feed shows -- and
                # it is the one the chart files answer. The JSON feed writes
                # a subdirectory per place whenever the registry has
                # several, and cannot know a skin was narrowed to one.
                "many_series": self.many_series,
                "charts_place": self.archive if self.many_series else "",
                # Which of the skin's pages are being written. A skin builds
                # its own menu and cannot ask the generator what it skipped,
                # so it has to be told: narrowed without this, every entry
                # the filter removed stayed in the sidebar as a link to a
                # file nobody wrote -- twenty dead links on a two-place site,
                # five on a one-place one, from a setting offered precisely
                # to the operator about to push it all over FTP.
                #
                # Empty means all of them, which is what it means everywhere
                # else, so a skin that ignores this is unaffected.
                "place_pages": list(self.place_pages),
                "scope": self.scope, "place_prefix": "",
                "place_path": lambda path="": _joined(base, path),
                "live_file": lambda: str(
                    self.tags.extras.get("live_push_file") or "live.json"),
                "site_title": self.site_title or self._station_name(),
                "open_places": True,
            }
        here = self.here if self.scope == "place" else None
        prefix = f"{here['name']}/" if here else ""
        # `base_path` is read the way a skin's own `get_base_path` reads it:
        # one lookup, one fallback. The test asserts on a rendered page that
        # `$place_path(path='x')` is `$get_base_path(path=$place_prefix+'x')`,
        # so the two cannot drift apart unnoticed.
        base = str(self.tags.extras.get("base_path") or "/")
        return {
            "many_series": True,
            "charts_place": here["name"] if here else "",
            "place_pages": list(self.place_pages),
            "places": [_shown(one, here) for one in self.places],
            # Those whose own archive covers *this page's* span. Computed
            # per page and only here: it is what stops the switcher on
            # `month-2026-05.html` offering a May 2026 that another place
            # does not have -- and the same test decides whether that place's
            # file was written at all.
            "places_here": [_shown(one, here) for one in self.places
                            if one["has_data"] and _overlaps(one["covers"],
                                                             span)],
            "here_place": _shown(here, here) if here else None,
            "scope": self.scope,
            "place_prefix": prefix,
            "place_path": lambda path="", _p=prefix, _b=base: _joined(
                _b, f"{_p}{path}"),
            # `live_push_file` is "live.json", relative. From
            # `/nordfeld/index.html` a browser resolves that to
            # `/nordfeld/live.json`, which does not exist -- live values dead
            # on every place page, reading as a live-values bug and having
            # nothing whatever to do with live values. Not made absolute
            # unconditionally, because that would change the one-place output
            # for no reader at all.
            "live_file": lambda _b=base: _joined(
                _b, str(self.tags.extras.get("live_push_file")
                        or "live.json")),
            "site_title": self.site_title or self._station_name(),
            "open_places": len(self.places) <= self.places_fold,
        }

    def _station_name(self) -> str:
        """The selected place's title when the feed has no site title."""
        try:
            return str(self._settings.get("station.name") or "")
        except Exception:
            return ""

    # -- everything that is not a template --------------------------------

    def _copy(self, conf: dict[str, Any], into: Path) -> list[Path]:
        """Stylesheets, fonts, a chart library. Copied as they are.

        WeeWX names them in `[CopyGenerator]`. A skin that names none still
        has them, so anything alongside the templates that is plainly not one
        is copied too -- a missing stylesheet is a site that looks broken and
        gives no clue why.
        """
        wanted: list[Path] = []
        section = conf.get("CopyGenerator")
        if isinstance(section, dict):
            for key in ("copy_once", "copy_always"):
                named = section.get(key)
                if not named:
                    continue
                for pattern in (named if isinstance(named, list) else [named]):
                    for found in sorted(self.skin.glob(str(pattern).strip())):
                        if found.is_dir():
                            # A directory named in `copy_once` means all of
                            # it. weewx-wdc names `dist/assets`, which is
                            # where its typefaces live -- skipped, the page
                            # loads and asks the browser for four fonts
                            # that are not there.
                            wanted += sorted(x for x in found.rglob("*")
                                             if x.is_file())
                        else:
                            wanted.append(found)
        if not wanted:
            wanted = [p for p in self.skin.rglob("*")
                      if p.is_file() and p.suffix.lower() in COPY_SUFFIXES]

        made: list[Path] = []
        for source in wanted:
            if not source.is_file() or source.name == "skin.conf":
                continue
            try:
                relative = source.relative_to(self.skin)
            except ValueError:
                continue
            target = into / relative
            try:
                if target.exists() and \
                        target.stat().st_mtime >= source.stat().st_mtime \
                        and target.stat().st_size == source.stat().st_size:
                    made.append(target)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                made.append(target)
            except OSError as exc:
                log.warning("could not copy %s: %s", relative, exc)
        return made

    # -- what the settings page asks for ----------------------------------

    @staticmethod
    def skin_options(skin: str, skins_dir: Any = None,
                     settings: Any = None) -> list:
        """What the chosen skin lets an operator set, for the feed's page.

        `settings` is this feed's own section, so a group can say what this
        instance will actually publish rather than what the skin can do in
        general.

        A skin of ours ships an `options.py` next to its templates, the way
        a driver ships one next to its parser. One entry there makes the
        form field, the validation and the `--explain` line at once.

        A skin from outside has none, and its settings stay in its own
        `skin.conf` -- where its author put them, and where its own
        documentation says they are.
        """
        return skin_options(skin, skins_dir, settings)

    @staticmethod
    def options() -> list:
        from ...options import installed_skins

        return [
            *_shows_group(),
            Group("Live updates",
                  "A skin that can show live readings subscribes to an MQTT "
                  "broker from the visitor's browser. Which broker, the "
                  "topic and whether it is encrypted all come from the "
                  "upload chosen here -- so the broker is set up once, on "
                  "its own page, and not a second time in the skin.", (
                      Option("live_from", "Take live updates from",
                             kind="choice", default="",
                             choices=(("", "the only MQTT upload there is"),
                                      ("off", "-- nothing; leave the skin alone --")),
                             choices_from=_mqtt_upload_choices,
                             help="Only matters with more than one MQTT "
                                  "upload -- a station publishing to one "
                                  "broker for Home Assistant and another "
                                  "for its website. A skin that names its "
                                  "own broker in skin.conf keeps it either "
                                  "way."),
                  )),
            Group("The skin", "Which one, and where it comes from.", (
                Option("enabled", "Render it", kind="bool", default=True),
                Option("skin", "Skin", kind="choice", default="",
                       choices=(("", "-- none chosen --"),),
                       choices_from=installed_skins,
                       help="A directory of Cheetah templates written for "
                            "WeeWX. Point the skins directory below at an "
                            "existing installation and its skins appear "
                            "here."),
                Option("skins_dir", "Skins directory", kind="path",
                       default="skins",
                       help="Where skins are looked for. A WeeWX "
                            "installation keeps them in `skins`; that "
                            "directory can be used directly."),
                Option("charts_path", "Where the chart files are",
                       placeholder="/json/",
                       help="The address a browser reaches this station's "
                            "chart files at, which is where the `json` feed "
                            "publishes to. A skin that draws its charts from "
                            "those files has to be told: they are a separate "
                            "export from these pages, possibly to a different "
                            "host, so nothing here can work it out. Empty "
                            "leaves whatever the skin says, which for the "
                            "bundled one is `/json/` -- what the built-in web "
                            "server serves a local export named `json` at."),
                Option("units_other_path",
                       "Address of the same site in other units",
                       placeholder="/wdc-us/",
                       help="For a station publishing twice, once in each "
                            "system: a second feed of the same skin with a "
                            "different `Show readings in`, into a directory "
                            "of its own. Given this, the pages grow a switch "
                            "between the two and remember which one somebody "
                            "chose. Left empty there is no switch, which is "
                            "right for a station that publishes once."),
                Option("units_other_label", "What to call those units",
                       placeholder="°F",
                       help="What the switch says for the other side. Two or "
                            "three characters: it sits in the header beside "
                            "the light and dark toggle."),
                Option("extras", "The skin's own settings", kind="list",
                       advanced=True,
                       help="One `name = value` per line, put into the "
                            "skin's [Extras] over whatever it says itself. "
                            "That is where a skin's author puts the things "
                            "an operator is meant to change, and editing "
                            "the skin to change them loses it at the next "
                            "update. weewx-wdc needs `base_path = /wdc/` "
                            "here if it is published anywhere but the root "
                            "of a site, or its stylesheet and its charts "
                            "are looked for in the wrong place."),
                Option("lang", "Language", kind="choice", default="",
                       choices=(("", "As the skin says"),),
                       choices_from=_skin_languages,
                       help="A WeeWX skin keeps its translations in its own "
                            "lang directory, and those files carry the unit "
                            "system, the labels and the points of the "
                            "compass along with the words. The list is what "
                            "the chosen skin has."),
                Option("destination", "Directory", default="",
                       advanced=True,
                       help="Under the feed output directory. Empty means a "
                            "directory named after this feed."),
            )),
            Group("Units", "What the pages show, if not what the skin says.",
                  (
                Option("units", "Show readings in", kind="choice", default="",
                       choices=(("", "As the skin asks"), ("US", "US"),
                                ("METRIC", "Metric (km/h, cm)"),
                                ("METRICWX", "Metric (m/s, mm)")),
                       help="A skin names its own units, and left alone it "
                            "keeps them -- that is what makes an existing "
                            "skin look like itself. Choosing here overrides "
                            "the skin, for a page written in Fahrenheit that "
                            "should read in Celsius."),
            )),
            Group("How", "", (
                Option("encoding", "Write the pages as", kind="choice",
                       default="html_entities",
                       choices=(("html_entities",
                                 "HTML entities -- plain ASCII, safest"),
                                ("utf8", "UTF-8"),
                                ("strict_ascii",
                                 "ASCII, dropping anything else"),
                                ("normalized_ascii",
                                 "ASCII, with accents stripped")),
                       help="WeeWX's default is HTML entities, and it is the "
                            "one that survives a web server that says "
                            "nothing about its encoding."),
                Option("copy_static", "Copy stylesheets and images",
                       kind="bool", default=True,
                       help="A skin's own CSS, fonts and scripts. Off only "
                            "if something else puts them there."),
                Option("stale_ok", "Honour a template's stale_age",
                       kind="bool", default=True, advanced=True,
                       help="A skin marks pages that do not need rewriting "
                            "every interval. Off renders everything every "
                            "time, which is slower and never wrong."),
            )),
        ]


# -- small things ----------------------------------------------------------

def mqtt_uploads(settings: Any) -> list[tuple[str, dict]]:
    """The configured MQTT uploads, by name."""
    section = settings.config.get("uploads") or {}
    return [(name, dict(found)) for name, found in sorted(section.items())
            if isinstance(found, dict)
            and str(found.get("kind", "")).strip() == "mqtt"]


def _mqtt_upload_choices() -> list[tuple[str, str]]:
    """The MQTT uploads there are, for the dropdown on this feed's page."""
    from ...settings import running

    settings = running()
    if settings is None:
        return []
    return [(name, f"the {name} broker") for name, _ in mqtt_uploads(settings)]


def _broker(settings: Any, chosen: str = "") -> dict[str, Any]:
    """What a browser needs to reach the configured MQTT broker.

    Read from the upload rather than from a second block of settings on this
    feed's page. That is the whole point: a station that publishes to a
    broker has already said where it is, what the topic is called and whether
    it is encrypted. Asking again here is how the two drift apart -- and the
    way they drift is a topic that does not match, which shows up as a page
    that renders perfectly and never updates.

    `chosen` names one, for a station with more than one broker -- Home
    Assistant on the local one and the website on a public one is an ordinary
    arrangement. Left empty with several configured, none is used and it says
    so: guessing which of two brokers a page should subscribe to is the sort
    of quiet choice that is wrong half the time and never looked at.
    """
    if str(chosen).strip().lower() == "off":
        return {}
    try:
        from ...cli import build_upload
    except Exception:  # pragma: no cover - only in a stripped install
        return {}

    found = mqtt_uploads(settings)
    if not found:
        return {}
    if chosen:
        found = [(name, conf) for name, conf in found if name == chosen]
        if not found:
            log.warning("this feed takes its live updates from the upload %r, "
                        "and there is no such MQTT upload. The skin's own "
                        "settings stand.", chosen)
            return {}
    elif len(found) > 1:
        log.warning("there are %d MQTT uploads (%s) and this feed does not "
                    "say which one its skin should subscribe to. Choose one "
                    "under 'Live updates' on the feed's page; until then the "
                    "skin's own settings stand.",
                    len(found), ", ".join(name for name, _ in found))
        return {}

    name, configured = found[0]
    try:
        browser = build_upload(name, dict(configured)).browser()
    except Exception:
        # A broker that cannot be built is the upload's problem to report,
        # not this feed's to fail on. The skin's own settings then stand.
        log.debug("could not read the mqtt upload %r for the skin", name,
                  exc_info=True)
        return {}
    if browser:
        log.debug("live updates for the skin come from the %r upload", name)
    return browser


def _true(value: Any) -> bool:
    """Whether a skin setting means yes. ConfigObj hands back strings."""
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _settings_block(value: Any) -> dict[str, Any]:
    """A skin's `[Extras]` overrides, written either way.

    A configuration file writes them as a table:

        feeds.wdc.extras.base_path = "/wdc/"

    and the settings page has one field, so it writes them as lines:

        base_path = /wdc/
    """
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    # A list too, because the option declares `kind="list"` and that is what
    # a hand-written file naturally holds:
    #
    #     extras = ["base_path = /wdc/", "charts_path = /wdc/json/"]
    #
    # Without this it went through `str()`, so the one "line" was the repr of
    # the list and every setting in it was silently dropped -- pages asking
    # for /assets/deck.css while being served under /wdc/, with the skin
    # rendering perfectly and looking unstyled.
    lines = value if isinstance(value, (list, tuple)) \
        else str(value).splitlines()
    out: dict[str, Any] = {}
    for line in lines:
        key, sep, said = str(line).partition("=")
        if sep and key.strip():
            out[key.strip()] = said.strip()
    return out


def _as_list(value: Any) -> list:
    """One name or several, as a configuration file may spell either."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return list(str(value).split(","))


#: Which skin is being rendered on this thread. Thread-local rather than
#: global because two feeds may render two skins at once, and rather than
#: an argument because the thing that needs it is inside Cheetah.
_CURRENT = threading.local()


def _teach_cheetah() -> None:
    """Tell Cheetah where a skin is, instead of moving the process into it.

    Cheetah resolves `#include "layout/head.inc"` with `serverSidePath`,
    which is `abspath()` -- against the process's *current directory*. WeeWX
    gets away with that by doing `os.chdir` into the skin from inside its
    report thread, because nothing else in the process uses a relative path.
    Here a listener is answering hardware on other threads, and a directory
    that moves under them is the fault that happens once a month and cannot
    be reproduced.

    So `serverSidePath` is replaced, once, on Cheetah's own class. Three
    things were tried before this one and each failed on something real:

    - Splicing each included file into the text of the one that includes it.
      Cheetah compiles an include as its *own unit*, so each part keeps its
      own imports; glued together, one file's `#from datetime import
      datetime` and another's `#import datetime` are the same name twice and
      whichever loses takes the page down.
    - Rewriting every `#include` to an absolute path in a mirrored copy.
      That works only for paths written as literals, and a skin may compute
      one: weewx-wdc has `#include $get_celestial_icon($body, 'rise')`.
    - Subclassing Template and overriding the method there. Cheetah compiles
      an include against the class of the template that includes it, and a
      *subclass* gets its body compiled into `writeBody` rather than
      `respond` -- so the include ran, wrote nothing, and printed `None`
      into the page where its content should have been.

    Patching the class Cheetah itself instantiates is the one that works,
    and this feed is the only thing in the process that uses Cheetah.
    """
    import Cheetah.Template

    if getattr(Cheetah.Template.Template, "_weewx_evo_taught", False):
        return
    original = Cheetah.Template.Template.serverSidePath

    def serverSidePath(self: Any, path: Any = None,  # noqa: N802
                       **kwargs: Any) -> Any:
        skin = getattr(_CURRENT, "skin", None)
        if skin is not None and path and not os.path.isabs(str(path)):
            here = Path(skin) / str(path)
            if here.exists():
                return os.path.normpath(str(here))
        return original(self, path, **kwargs)

    Cheetah.Template.Template.serverSidePath = serverSidePath

    # `$varExists('x')` asks whether a name is there. The tag layer counts
    # every name it cannot answer, and reports the list at the end -- so a
    # template that politely checks first was filling that report with
    # things that were never missing. Twenty-eight of them on a page with
    # nothing wrong with it, which makes the report worth ignoring, which
    # is the same as not having one.
    asked = Cheetah.Template.Template.varExists

    def varExists(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
        tags = getattr(_CURRENT, "tags", None)
        if tags is None:
            return asked(self, *args, **kwargs)
        tags.counting = False
        try:
            return asked(self, *args, **kwargs)
        finally:
            tags.counting = True

    Cheetah.Template.Template.varExists = varExists
    Cheetah.Template.Template._weewx_evo_taught = True


def _find(name: str, base: Path, skin: Path) -> Path | None:
    candidate = Path(name)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    for where in (base / candidate, skin / candidate):
        if where.is_file():
            return where
    return None


#: What a language file is called, where a skin ships more than the code.
#: Only the ones WeeWX's own skins carry; anything else is offered by its
#: code, which is what the file is named anyway.
LANGUAGE_NAMES = {
    "ca": "Catalan", "cz": "Czech", "de": "German", "en": "English",
    "en_AU": "English (Australia)", "en_CA": "English (Canada)",
    "en_GB": "English (United Kingdom)", "en_NZ": "English (New Zealand)",
    "es": "Spanish", "fi": "Finnish", "fr": "French", "gr": "Greek",
    "it": "Italian", "nl": "Dutch", "no": "Norwegian", "th": "Thai",
    "zh": "Chinese", "zh_CN": "Chinese (simplified)",
}


def _skin_languages() -> list[tuple[str, str]]:
    """Which translations the chosen skin has, for the dropdown.

    Read off the skin rather than listed here: a skin somebody wrote last
    week with one extra language should offer it without anything being
    told.
    """
    from ...options import running_config

    current = running_config()
    out: list[tuple[str, str]] = []
    for settings in (current.get("feeds") or {}).values():
        if not isinstance(settings, dict) or settings.get("kind") != "cheetah":
            continue
        skins = Path(str(settings.get("skins_dir") or "skins"))
        chosen = str(settings.get("skin") or "").strip()
        where = (skins / chosen / "lang") if chosen else None
        if where is None or not where.is_dir():
            continue
        for path in sorted(where.glob("*.conf")):
            code = path.stem
            said = LANGUAGE_NAMES.get(code, code)
            if (code, said) not in out:
                out.append((code, said))
    return out


def _language_conf(where: Path, code: str) -> dict[str, Any]:
    """A skin's translation, read from its `lang` directory.

    `de_AT` reads `de.conf` and then `de_AT.conf` over it, so a regional
    file only has to carry what it says differently. Any encoding suffix --
    `de_AT.utf8` -- is dropped first. WeeWX's arrangement exactly, because
    the files are WeeWX's.
    """
    if not where.is_dir():
        return {}
    country = str(code).split(".")[0]
    parts = country.split("_")
    wanted = [parts[0]] if len(parts) == 1 else [parts[0], country]

    found: dict[str, Any] = {}
    for name in wanted:
        path = where / f"{name}.conf"
        if not path.is_file():
            continue
        try:
            found = _merge(found, weewxconf.read(path))
        except OSError as exc:
            log.warning("could not read %s: %s", path, exc)
    return found


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """`over` on top of `base`, section by section.

    Deep, because a skin that names one label must not lose the other
    hundred the translation supplied.
    """
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _apply_unit_system(conf: dict[str, Any]) -> None:
    """Honour `unit_system = metricwx` at the top of a skin or a translation.

    It is a shorthand for a whole `[Units][[Groups]]` section, and the
    German translations of every WeeWX skin start with it -- somebody
    reading German almost certainly wants millimetres. Written underneath
    the groups the skin names itself, which stay.
    """
    name = str(conf.get("unit_system") or "").strip()
    if not name:
        return
    try:
        system = units.system_from(name)
    except (KeyError, ValueError):
        log.warning("unit_system = %r is not one this knows", name)
        return
    block = conf.setdefault("Units", {})
    if not isinstance(block, dict):
        return
    groups = block.setdefault("Groups", {})
    if not isinstance(groups, dict):
        return
    for group, unit in units.SYSTEMS.get(system, {}).items():
        groups.setdefault(group, unit)


def _filename(template: str, when: float) -> str:
    """`index.html.tmpl` becomes `index.html`; `NOAA-%Y-%m.txt.tmpl` a month.

    The date comes from the span, so a summary names itself.
    """
    name = template.removesuffix(".tmpl")
    return time.strftime(name, time.localtime(when))


def _joined(base: str, path: str) -> str:
    """A path under the site's own root, however the root was written."""
    root = base if base.endswith("/") else base + "/"
    return f"{root}{str(path).lstrip('/')}"


def _overlaps(covers: tuple[int, int] | None,
              span: tuple[int, int] | None) -> bool:
    """Whether a place's archive reaches into the span a page is about."""
    if covers is None or span is None:
        return False
    return covers[0] <= span[1] and covers[1] >= span[0]


def _shown(one: dict[str, Any] | None,
           here: dict[str, Any] | None) -> dict[str, Any]:
    """One place, as a template sees it.

    A plain dict, and every value a string or a number: Cheetah's NameMapper
    tries `obj[name]` before it tries an attribute, so anything that looks
    like a mapping has to be one. That is the trap `$obs.label` fell into,
    where a class with a `__getitem__` handed back the string "label".

    `tags` is in here on purpose -- it is how an overview asks a place for
    its readings -- and it is the one value that is not a plain type.
    """
    if one is None:
        return {}
    return {
        "name": one["name"],
        "label": one["label"] or one["name"],
        "code": one["code"],
        "color": one["color"],
        "url": one["url"],
        "path": f"{one['name']}/",
        "here": bool(here is not None and one["name"] == here["name"]),
        "has_data": bool(one["has_data"]),
        "start": one["covers"][0] if one["covers"] else 0,
        "stop": one["covers"][1] if one["covers"] else 0,
        "tags": one["tags"],
    }


def _encode(text: str, encoding: str) -> bytes:
    """The rendered page as bytes, the way the skin asked for."""
    if encoding == "html_entities":
        return text.encode("ascii", "xmlcharrefreplace")
    if encoding == "strict_ascii":
        return text.encode("ascii", "ignore")
    if encoding == "normalized_ascii":
        return unicodedata.normalize("NFD", text).encode("ascii", "ignore")
    return text.encode(encoding or "utf8")


def _listed(value: Any) -> list[str]:
    """A list option, however the file spelled it."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(one) for one in value]
    return [one for one in str(value).replace(",", " ").split() if one]


def _shows_group() -> list[Group]:
    """How many places this feed is about, or nothing to ask.

    Left out entirely where the installation keeps one series, which is
    every installation that has not asked for a second: a choice between one
    place and several, on a station that has one, is a question with one
    answer. The precedent is the bundled skin, which leaves out its three
    groups about places the same way.

    Asked from inside the form builder, the way the dropdowns are, so it
    sees the file the page is being built for rather than whichever one was
    current when this module was imported.

    It belongs to the feed and not to a skin because `narrow()` is what
    reads it: a skin from outside is narrowed by it without shipping an
    `options.py`, and the chart feed -- whose layout follows the registry
    and must not follow this -- never shows it.
    """
    try:
        several = len(archive_names()) > 1
    except Exception:
        # Wrong in the safe direction: a switch that is shown and does
        # nothing is a question somebody can answer, one that is hidden and
        # needed cannot be found at all.
        log.debug("could not count the places for the feed", exc_info=True)
        several = True
    if not several:
        return []
    return [
        Group("Places",
              "A site can publish one place or several. This is the one "
              "question that decides the shape of what goes out, so it is "
              "asked before anything about pages or charts.", (
                  Option("shows", "This feed publishes", kind="choice",
                         default="many",
                         choices=(("many", "Several places"),
                                  ("one", "Only the place chosen above")),
                         help="Several publishes an overview at the root "
                              "and each place in a folder of its own. Only "
                              "the one publishes the way a station with a "
                              "single series always has: index.html, "
                              "week.html and the rest at the root, no "
                              "overview and no folders -- which is how two "
                              "places are published as two separate sites, "
                              "one feed and one export each. A list of "
                              "places further down is then not read at "
                              "all."),
              ), prefix=""),
    ]


def _roster(archives: Any, settings: Any) -> list[dict[str, Any]]:
    """Every place this feed shows, in the order pages present them.

    Handed in rather than worked out here: which files there are is the
    runner's knowledge, and a tag layer that opened databases would be one
    that can open the wrong one.

    Kept, not opened. They are opened at the top of `produce` and closed at
    the bottom of it -- a connection opened on demand inside a render is one
    nothing closes, and the runner rebuilds this feed every pass.

    Three shapes are accepted, because two of them are already in the tree
    and one of those is what `skins/overview` and the end-to-end test are
    written against:

        {name: path}
        {name: (path, that place's own settings)}
        [Archive, ...]              -- the register's own objects

    The second is what an installation with two places sends today: each
    series' own settings, so each keeps its own coordinates. Given this
    page's instead, the readings would be right and the sun wrong by minutes.
    """
    if not archives:
        return []
    out: list[dict[str, Any]] = []
    if isinstance(archives, dict):
        for name, value in archives.items():
            if isinstance(value, tuple):
                where, mine = Path(value[0]), value[1]
            else:
                where, mine = Path(value), settings
            out.append(_place(str(name), where, mine))
    else:
        for one in archives:
            out.append(_place(one.name, Path(one.file), settings,
                              label=one.label, code=one.code,
                              color=one.color, url=one.url))
    return out


def _place(name: str, where: Path, mine: Any, label: str = "",
           code: str = "", color: str = "", url: str = "") -> dict[str, Any]:
    """One entry, with the fields `_bind` fills left empty."""
    return {
        "name": name, "file": where, "settings": mine,
        # What to print. Read off the place's own settings where the caller
        # did not say, which is what `archives.Placed` answers `station.name`
        # with -- so a place always has a name to print even when the
        # register was not handed in whole.
        "label": label or _said(mine, "station.name"),
        "code": code, "color": color,
        "url": url or _said(mine, "station.url"),
        "reader": None, "tags": None, "covers": None, "has_data": False,
    }


def _said(settings: Any, name: str) -> str:
    try:
        return str(settings.get(name) or "")
    except Exception:
        return ""


def _tags_for(settings: Any, reader: Reader, plots: Any = (),
              extra_groups: dict[str, str] | None = None,
              target: units.Target | None = None, language: str = "",
              when: float | None = None, like: Tags | None = None) -> Tags:
    """One series' tag layer.

    Two callers: the feed's own, built here, and every other place, built in
    `CheetahFeed._reach` once the skin's configuration has been read.

    `like` is what makes the second of those right. The skin's units,
    decimals, labels, translated strings, moon phases, `[Extras]`,
    `[DisplayOptions]` and degree-day bases are *shared objects*, not copies:
    `_extras` and `_units` run once, over the feed's own tags, and every
    place is then looking at the same dictionaries. Copied instead, the two
    would have to be kept in step by hand, and the failure is a page that
    renders perfectly with one column in Fahrenheit to one decimal and the
    next in Celsius to two.
    """
    tags = Tags(
        reader=reader,
        when=when,
        target=target if like is None else like.target,
        unit_system=reader.system,
        extra_groups=extra_groups,
        station={
            "location": settings.get("station.name") or "",
            "latitude": settings.get("station.latitude"),
            "longitude": settings.get("station.longitude"),
            "altitude": settings.get("station.altitude"),
            "station_url": settings.get("station.url") or "",
            # What the readings come from. WeeWX prints one name in a
            # footer because it runs one driver; here any number deliver at
            # once, so the honest answer is the station's own name and not a
            # protocol picked from among several.
            "hardware": str(settings.get("station.name") or ""),
            "version": _version(),
            # Who is rendering. A skin that prints a version wants to say
            # whose: deck's footer read "WeeWX version 0.0.1", which is the
            # name of a different program and a version number that is not
            # its. A skin running under WeeWX itself gets WeeWX's own value
            # for this, so the line is right either way.
            "software": f"weewx-evo {_version()}",
        },
        rain_year_start=int(settings.get("station.rain_year_start") or 1),
    )
    tags.plots = plots
    tags.language = language or (like.language if like else "en")
    if like is not None:
        tags.labels = like.labels
        tags.text = like.text
        tags.extras = like.extras
        tags.display = like.display
        tags.moon_phases = like.moon_phases
        tags.degree_day_bases = like.degree_day_bases
        tags.rain_year_start = like.rain_year_start
        tags.week_start = like.week_start
    return tags


def from_settings(settings: Any, reader: Reader,
                  plots: Any = (), prefix: str = "feeds.cheetah",
                  extra_groups: dict[str, str] | None = None,
                  archives: Any = None,
                  archive: str = "",
                  forecast_path: str | Path | None = None) -> CheetahFeed:
    """Build the feed, and the tag layer it renders through.

    The tags are built here rather than handed in because they carry the
    skin's own units, words and formats, and two skins in one process must
    not share them.
    """
    def option(name: str, fallback: Any = None) -> Any:
        found = settings.get(f"{prefix}.{name}")
        return fallback if found is None else found

    # What the archive holds, read from the archive. A station that was set
    # up in Fahrenheit and never said so anywhere still gets Fahrenheit out
    # of its own records.
    stored = reader.system
    # The station's language, unless this feed was pointed at another --
    # which is how a site gets published twice, once in each.
    spoken = language_module.get(option("lang") or settings.get("language"))
    chosen = str(option("units") or "").strip()
    try:
        target = units.Target(chosen or spoken.unit_system or stored,
                              language=spoken)
    except ValueError as exc:
        log.error("%s -- showing the readings as stored instead", exc)
        target, chosen = units.Target(stored, language=spoken), ""

    tags = _tags_for(settings, reader, plots=plots,
                     extra_groups=extra_groups, target=target,
                     language=spoken.code)

    places = _roster(archives, settings)
    tags.moon_phases = spoken.moon_phases()
    forecast_store = _install_forecast(
        tags, settings, spoken, archive=archive, path=forecast_path)

    skins = Path(str(option("skins_dir") or "skins"))
    skin = str(option("skin") or "").strip()
    where = skins / skin if skin else skins
    if skin and not (where / "skin.conf").is_file():
        # Not in the directory this feed points at. One of the shipped ones
        # then, which is what a fresh installation has and no `skins_dir`
        # of its own.
        from ...skins import bundled

        where = bundled().get(skin, where)

    feed = CheetahFeed(
        reader=reader,
        skin=where,
        tags=tags,
        encoding=str(option("encoding") or "html_entities"),
        copy_static=option("copy_static") is not False,
        stale_ok=option("stale_ok") is not False,
        language=spoken.code,
        derived=_derived(settings),
        extras=_extras(option("extras"), option("charts_path"),
                       option("units_other_path"),
                       option("units_other_label"),
                       option("units")),
        broker=_broker(settings, str(option("live_from") or "")),
    )
    # An explicit choice on the feed's page beats what the skin asked for.
    # Left empty, the skin decides, which is the point of running it at all.
    feed.skin_units = not chosen
    feed.archive = str(archive or option("archive")
                       or settings.get("archive") or "")
    #: The forecast, open for the life of this feed. Kept so the other
    #: places' tags can share it -- four places must not open one file four
    #: times -- and so `produce` can close it.
    feed.forecast_store = forecast_store
    feed.places = places
    feed._settings = settings
    feed._spoken = spoken
    feed._plots = plots
    feed._extra_groups = dict(extra_groups or {})
    # What the operator narrowed this instance to, from the skin's own
    # options. A skin that declares none leaves every one of these empty and
    # behaves exactly as it did.
    feed.site_title = str(option("site_title") or "").strip()
    feed.place_pages = tuple(
        one.strip() for one in _listed(option("place_pages")) if one.strip())
    try:
        feed.places_fold = int(option("places_fold") or 6)
    except (TypeError, ValueError):
        feed.places_fold = 6
    feed.shown = tuple(
        one.strip() for one in _listed(option("places")) if one.strip())
    # The feed's own switch, not the skin's, so a skin from outside is
    # narrowed by it too. Read as a word rather than a truth value: "many"
    # is the default and the state every existing feed is already in, so
    # nothing that is not this word can turn a published site into one.
    feed.solo = str(option("shows") or "").strip() == "one"
    feed.narrow()
    feed.display = _display(settings, prefix, skin, skins)
    return feed


def skin_options(skin: str, skins_dir: Any = None,
                 settings: Any = None) -> list[Group]:
    """What the named skin lets an operator set, or nothing.

    A skin of ours ships an `options.py` next to its templates, the way a
    driver ships one next to its parser. The admin page asks for it by name
    and builds a form; nothing else has to know the skin exists.

    A skin from outside has no such file, and its settings stay in its own
    `skin.conf` -- which is where its author put them and where its
    documentation says they are.
    """
    if not skin:
        return []
    where = Path(str(skins_dir or "skins")) / skin
    if not (where / "options.py").is_file():
        from ...skins import bundled

        found = bundled().get(skin)
        if found is None or not (found / "options.py").is_file():
            return []
        module_name = f"weewx_evo.skins.{skin}.options"
    else:
        module_name = None

    try:
        if module_name:
            import importlib

            module = importlib.import_module(module_name)
        else:
            module = _module_from(where / "options.py", f"skin_{skin}_options")
        try:
            return list(module.groups(settings))
        except TypeError:
            # A skin from outside, whose `groups()` takes nothing. Its
            # settings do not depend on how many places there are, so
            # there is nothing to hand it.
            return list(module.groups())
    except Exception as exc:  # a skin's own file, so anything can be in it
        log.warning("could not read the settings of skin %r: %s", skin, exc)
        return []


def _module_from(path: Path, name: str) -> Any:
    """Load one file as a module, without it having to be on the path."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _display(settings: Any, prefix: str, skin: str,
             skins_dir: Any) -> dict[str, Any]:
    """The skin's own settings, as the operator set them.

    Only the ones actually set. A value left alone must fall through to what
    `skin.conf` says, and writing the schema default over it replaces the
    skin's own choice with ours -- the same trap as a default in argparse,
    in a different place.

    `get` alone cannot tell the two apart: it answers with the default and
    looks like an answer. `source` is what knows, and it has to be asked
    after the `get` that filled it in.

    What that cost, before `source` was consulted: `outTemp_stat_tile_color`
    came back as the boolean False, went into `[DisplayOptions]` as a
    boolean where the skin had written the string "False", and the template
    put nothing at all in `color_temperature: ,`. One comma, and every page
    lost its whole configuration block -- the theme, the translations, the
    charts. It rendered fine locally, where the test settings answer None
    for anything not set, and only broke where the real ones answer with a
    default.
    """
    found: dict[str, Any] = {}
    for group in skin_options(skin, skins_dir):
        for option in group.options:
            name = f"{prefix}.{option.name}"
            value = settings.get(name)
            if settings.source(name) == "default":
                continue
            if value is not None and value != "":
                found[option.name] = value
    return found


#: What to call a unit system on a switch, when nobody said. Short, because
#: it goes in a header beside the light and dark toggle.
UNIT_MARKS = {"US": "\u00b0F", "METRIC": "\u00b0C", "METRICWX": "\u00b0C"}


def _extras(block: Any, charts_path: Any, other_path: Any = None,
            other_label: Any = None, own_units: Any = None) -> dict[str, Any]:
    """The skin's own settings, plus the ones this page asks for by name.

    All of these are free text in the block as well, and would work there --
    but nobody found `charts_path` when it was only that. They are facts
    about the deployment: where a *different* export landed, and whether this
    station publishes a second set of pages in other units. That is the
    operator's to know and not the skin author's, so each gets a field with a
    label and a help line. A value typed there wins over one in the skin.
    """
    found = _settings_block(block)
    said = str(charts_path or "").strip()
    if said:
        found["charts_path"] = said

    where = str(other_path or "").strip()
    if where:
        found["units_other_path"] = where
        found["units_other_label"] = (str(other_label or "").strip()
                                      or _other_mark(own_units))
        # What this side is called, so the switch can show both and say
        # which one is showing. Worked out rather than asked for: a page
        # already knows what it is written in.
        found["units_own_label"] = UNIT_MARKS.get(
            units.name(units.system_from(own_units or "METRICWX")), "")
    return found


def _other_mark(own_units: Any) -> str:
    """A guess at what the other side is called, from what this side is.

    Two systems in practice: somebody publishing in Celsius has the second
    set in Fahrenheit. A station doing something else says so in the field.
    """
    here = units.name(units.system_from(own_units or "METRICWX"))
    return UNIT_MARKS["METRICWX"] if here == "US" else UNIT_MARKS["US"]


def _derived(settings: Any) -> tuple[str, ...]:
    """Readings this installation computes instead of reading.

    `[derive]` in the configuration, with the same defaults the archiver
    runs on -- so the page agrees with what actually happened to the record.
    """
    from ...derive import DEFAULTS

    how = dict(DEFAULTS)
    how.update(getattr(settings, "config", {}).get("derive") or {})
    return tuple(sorted(name for name, choice in how.items()
                        if choice in ("software", "prefer_hardware")))


def _install_forecast(tags: Any, settings: Any, spoken: Any,
                      archive: str = "", store: Any = None,
                      path: str | Path | None = None) -> Any:
    """Give the skin `$forecast` for one series, if this station fetches one.

    Opened here rather than in `tags.py` for two reasons. A station with no
    forecast configured should not open a database it has no rows in -- and
    the tag layer has no business knowing the forecast package exists, the
    same way it has no business knowing about the exports.

    The file not being there is the ordinary case and is not an error: a
    template asking `#if $forecast` gets a no and renders around it.

    One file holds every series' forecast and the rows name the series they
    are for, so `archive` is what makes `$forecast` this page's rather than
    the neighbour's. A place with no source configured gets no rows and
    `#if $forecast` is a no -- never the neighbour's forecast under its
    heading, which is the whole reason the rows carry the name.

    `store` is handed in when the caller already has one open: a run that
    renders four places must not open the same file four times and leave
    four handles behind. Returns the store it used, or None.
    """
    if store is None:
        path = Path(path) if path is not None else _placed_forecast_path(settings)
        if path is None or not path.exists():
            return None
    try:
        from ...forecast.store import ForecastStore
        from ...forecast.tags import install

        made = store if store is not None else ForecastStore(path)
        install(tags, made, spoken,
                archive=_forecast_archive(settings, archive))
        return made
    except Exception:
        # A forecast nobody can read must not take a page down. The skin
        # asking for it gets a miss, which the report names.
        log.warning("could not open the forecast; the pages will render "
                    "without it", exc_info=True)
        return store


def _placed_forecast_path(settings: Any) -> Path | None:
    """Find an existing-layout cache from a placed archive, if that is all.

    The normal CLI passes the installation-wide path explicitly. Direct
    renderer users do not have the archive registry, but a ``Placed`` view
    still exposes the archive it belongs to. That is a safe compatibility
    fallback; the old central ``archive_db`` value is intentionally ignored.
    """
    from ...forecast import store_path

    archive = getattr(settings, "archive", None)
    archive_file = getattr(archive, "file", None)
    if not archive_file:
        return None
    configured = getattr(settings, "_path", None)
    base = Path(configured).parent if configured is not None else None
    return store_path(archive_file, base)


def _forecast_archive(settings: Any, named: str = "") -> str:
    """The exact placed series, with ``default`` only for legacy callers."""
    archive = getattr(settings, "archive", None)
    return (str(named or getattr(archive, "name", "")).strip()
            or forecast_default_archive())


def forecast_default_archive() -> str:
    """What a series is called when nobody said, from the store that owns it."""
    from ...forecast.store import DEFAULT_ARCHIVE

    return DEFAULT_ARCHIVE


def _version() -> str:
    from ... import __version__

    return __version__

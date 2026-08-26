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
import re
import shutil
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any

from ... import language as language_module
from ... import units, weewxconf
from ...options import Group, Option
from ...series import Reader
from ...tags import Tags
from .. import Produced

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
                 language: str = "") -> None:
        self.reader = reader
        #: The skin's own directory, holding skin.conf and the templates.
        self.skin = Path(skin)
        self.tags = tags
        self.encoding = encoding
        self.copy_static = copy_static
        #: Which of the skin's translations to run it in. Empty means what
        #: the skin itself says, which is usually English.
        self.language = str(language or "").strip()
        #: Honour a template's `stale_age`. A year page built from daily
        #: averages says the same thing at ten past as at ten o'clock.
        self.stale_ok = stale_ok
        self.rendered = 0
        self.skipped = 0
        self.failed: list[tuple[str, str]] = []
        #: Which "SummaryBy" files exist, for `$SummaryByMonth` in a template.
        self.summaries: dict[str, list[str]] = {}
        #: The plain values at the top of skin.conf, for `$SKIN_NAME`.
        self.skin_values: dict[str, Any] = {}
        #: Where the prepared templates live -- the skin's own, with their
        #: includes made absolute. Made on the first run and refreshed only
        #: where a file has changed, so a station rewrites nothing per
        #: interval.
        self.work: Path = Path(tempfile.gettempdir()) / _work_name(self.skin)
        #: Whether the skin decides which units it is shown in. False once
        #: the operator has picked a system on the feed's own page.
        self.skin_units = True

    # -- the feed ---------------------------------------------------------

    def produce(self, into: Path, now: float | None = None) -> Produced:
        started = time.time()
        into = Path(into)
        into.mkdir(parents=True, exist_ok=True)
        self.rendered = self.skipped = 0
        self.failed = []
        self.summaries = {name: [] for name in SUMMARIES}

        prepare(self.skin, self.work)
        conf = self._skin_conf()
        if conf is None:
            return Produced(directory=into,
                            note=f"no skin.conf in {self.skin}")

        files: list[Path] = []
        section = conf.get("CheetahGenerator") or conf.get("FileGenerator")
        if isinstance(section, dict):
            self._extras(conf)
            files += self._generate(section, "", into, conf)
        else:
            log.warning("%s has no [CheetahGenerator]; nothing to render",
                        self.skin)

        if self.copy_static:
            files += self._copy(conf, into)

        note = (f"{self.rendered} page(s) in {time.time() - started:.2f}s"
                + (f", {self.skipped} still fresh" if self.skipped else "")
                + (f", {len(self.failed)} failed" if self.failed else ""))
        missing = self.tags.report()
        if self.tags.missing:
            # The whole reason this is worth building rather than guessing at:
            # a list of what a skin asked for and did not get.
            log.warning("%s: %s", self.skin.name, missing)
            note += f"; {len(self.tags.missing)} tag(s) unanswered"
        log.info("%s: %s", self.skin.name, note)
        return Produced(directory=into, files=files, note=note)

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
            return conf
        spoken = _language_conf(self.skin / "lang", code)
        if not spoken:
            log.info("%s has no translation for %r; running it as written",
                     self.skin.name, code)
            return conf
        merged = _merge(spoken, conf)
        merged["lang"] = code
        _apply_unit_system(merged)
        log.info("%s is being rendered in %r", self.skin.name, code)
        return merged

    def _extras(self, conf: dict[str, Any]) -> None:
        """Carry the skin's own settings and words into the tags.

        `[Extras]` is where a skin keeps whatever its author invented, and a
        template reads it as `$Extras.something`. `[Labels]` and `[Units]`
        are what things are called. All of it belongs to the skin, in the
        skin's language.
        """
        labels = conf.get("Labels")
        if isinstance(labels, dict):
            generic = labels.get("Generic")
            source = generic if isinstance(generic, dict) else labels
            self.tags.labels.update({k: str(v) for k, v in source.items()
                                     if isinstance(v, str)})
        almanac = conf.get("Almanac")
        if isinstance(almanac, dict) and almanac.get("moon_phases"):
            phases = almanac["moon_phases"]
            self.tags.moon_phases = tuple(phases if isinstance(phases, list)
                                          else [phases])
        texts = conf.get("Texts")
        if isinstance(texts, dict):
            self.tags.text.update({k: str(v) for k, v in texts.items()
                                   if isinstance(v, str)})
        for name, into in (("Extras", "extras"),
                           ("DisplayOptions", "display")):
            found = conf.get(name)
            if isinstance(found, dict):
                getattr(self.tags, into).update(found)
        block = conf.get("Units")
        if isinstance(block, dict):
            self._units(block)
        language = conf.get("lang") or conf.get("Language")
        if isinstance(language, str):
            self.tags.language = language
        # Whatever the skin wrote at the top of its own file, `$SKIN_NAME`
        # and `$SKIN_VERSION` among them. A page prints them in its footer,
        # and only the skin knows what they say.
        self.skin_values = {k: v for k, v in conf.items()
                            if not isinstance(v, dict)}

    # -- walking the generator sections -----------------------------------

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
                if not units.can_convert(units.SYSTEMS[units.US][group],
                                         unit)                         and unit != units.SYSTEMS[units.US][group]:
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
                        self.tags.degree_day_bases[reading] = (
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
        template = self.skin / str(options["template"])
        if not template.is_file():
            log.warning("no such template: %s", template)
            self.failed.append((str(options["template"]), "not found"))
            return []

        span = self.reader.span()
        if span is None:
            return []
        summarize = str(options.get("summarize_by") or "").strip()
        encoding = str(options.get("encoding")
                       or self.encoding).strip().lower().replace("-", "")

        made: list[Path] = []
        for start, stop in self._spans(span, summarize):
            # A summary file is named after the start of its span and a
            # to-date file after the end, because one is "August" and the
            # other is "as of now".
            stamp = start if summarize in SUMMARIES else stop
            relative = Path(str(options["template"])).parent / _filename(
                template.name, stamp)
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

            if self._fresh(target, options):
                self.skipped += 1
                made.append(target)
                continue

            written = self._one(template, target, (start, stop), name,
                                relative, encoding, options)
            if written is not None:
                made.append(written)
        return made

    def _spans(self, span: tuple[int, int],
               summarize: str) -> list[tuple[int, int]]:
        if summarize in SUMMARIES:
            unit = SUMMARIES[summarize][0]
            return list(self.reader.buckets(span[0], span[1], unit))
        return [(span[0], span[1])]

    def _fresh(self, target: Path, options: dict[str, Any]) -> bool:
        """Whether this file is young enough to leave alone."""
        if not self.stale_ok:
            return False
        try:
            stale = int(float(str(options.get("stale_age")).strip()))
        except (TypeError, ValueError):
            return False
        try:
            return time.time() - target.stat().st_mtime < stale
        except OSError:
            return False

    # -- one page ---------------------------------------------------------

    def _one(self, template: Path, target: Path, span: tuple[int, int],
             page: str, relative: Path, encoding: str,
             options: dict[str, Any]) -> Path | None:
        try:
            import Cheetah.Template
        except ImportError:
            log.error("this feed needs Cheetah3, which is not installed: "
                      "pip install CheetahTemplate3")
            self.failed.append((template.name, "Cheetah3 is not installed"))
            return None

        try:
            # From the prepared copy, so Cheetah does its own including and
            # each part keeps its own imports. `file=` rather than
            # `source=`: that is what makes an include an include.
            prepared = self.work / template.relative_to(self.skin)
            rendered = Cheetah.Template.Template(
                file=str(prepared),
                searchList=self._search_list(span, page, relative,
                                             encoding)).respond()
        except Exception as exc:
            # One template, not the site. A skin with one broken page should
            # still publish the other forty.
            log.error("%s: %s: %s", template.name, type(exc).__name__, exc)
            self.failed.append((template.name, f"{type(exc).__name__}: {exc}"))
            return None

        try:
            data = _encode(str(rendered), encoding)
        except Exception as exc:  # noqa: BLE001
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
                     encoding: str) -> list[Any]:
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
        # A "SummaryBy" template lists its own siblings: `#for $m in
        # $SummaryByMonth`.
        summaries = {name: list(dates)
                     for name, dates in self.summaries.items()}
        # The span this page is for. A month page's `$month` is that month,
        # not the current one.
        here = {"timespan": Span(self.tags, span, page or "current"),
                "start": span[0], "stop": span[1]}
        # The skin's own sections, flat. A template says `$observations`
        # rather than `$DisplayOptions.observations`, because WeeWX puts the
        # contents of those sections into the search list directly. Before
        # the tags, so a skin can name something the tag layer also has.
        return [about, summaries, here, self.skin_values,
                dict(self.tags.display), dict(self.tags.extras), self.tags]

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
                    wanted += sorted(self.skin.glob(str(pattern)))
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
    def options() -> list:
        from ...options import installed_skins

        return [
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

#: `#include "titlebar.inc"`, in either of the two spellings a skin uses.
_INCLUDE = re.compile(r'^([ \t]*)#include\s+(raw\s+)?"([^"]+)"[ \t]*$',
                      re.MULTILINE)

#: A template that includes itself, or two that include each other. Ten is
#: far past any real nesting and stops the recursion being a hang.
MAX_INCLUDE_DEPTH = 10

#: Where preparing starts. Anything one of these includes is prepared too,
#: whatever it is called -- wdc includes `icons/wdc.svg`, and an SVG in a
#: template is still template source. Everything a skin ships that nothing
#: includes stays where it is and is published from there.
TEMPLATE_SUFFIXES = (".tmpl", ".inc")


def prepare(skin: Path, work: Path) -> Path:
    """A copy of the skin's templates whose includes point at each other.

    Cheetah resolves `#include "layout/head.inc"` against the process's
    *current directory*, so a skin only works if something has changed into
    its directory first. WeeWX does exactly that -- `os.chdir` from inside
    the report thread -- and it gets away with it because nothing else in
    the process uses a relative path. Here a listener is answering hardware
    on other threads, and a directory that moves under them is the fault
    that happens once a month and cannot be reproduced.

    So the paths are made absolute instead, in a copy. The obvious cheaper
    thing -- splicing each included file into the text of the one that
    includes it -- was what this did first, and it is wrong: Cheetah
    compiles an include as its *own unit*, so each part keeps its own
    imports. Glued together, one file's `#from datetime import datetime`
    and another's `#import datetime` are the same name twice, and whichever
    loses takes the page down with `module 'datetime' has no attribute
    'now'`. Measured: two files that render correctly through Cheetah's own
    include raise a TypeError spliced.
    """
    work.mkdir(parents=True, exist_ok=True)
    done: set[Path] = set()
    for source in sorted(skin.rglob("*")):
        if source.is_file() and source.suffix.lower() in TEMPLATE_SUFFIXES:
            _prepare_one(source, skin, work, done)
    return work


def _prepare_one(source: Path, skin: Path, work: Path,
                 done: set[Path], depth: int = 0) -> None:
    """One file, and then whatever it includes."""
    if source in done or depth > MAX_INCLUDE_DEPTH:
        return
    done.add(source)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.debug("not preparing %s: %s", source, exc)
        return

    target = work / source.relative_to(skin)
    try:
        if not (target.is_file()
                and target.stat().st_mtime >= source.stat().st_mtime):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                _absolute_includes(text, source.parent, skin, work),
                encoding="utf-8")
    except OSError as exc:
        log.warning("could not prepare %s: %s", source, exc)
        return

    for match in _INCLUDE.finditer(text):
        if match.group(2):
            # `raw` is read from the skin itself and never rewritten.
            continue
        found = _find(match.group(3), source.parent, skin)
        if found is not None and _inside(found, skin):
            _prepare_one(found, skin, work, done, depth + 1)


def _inside(path: Path, skin: Path) -> bool:
    """Whether a file is part of the skin, so a copy of it makes sense."""
    try:
        path.relative_to(skin)
    except ValueError:
        return False
    return True


def _absolute_includes(text: str, base: Path, skin: Path, work: Path) -> str:
    """Point every `#include` at a full path, so no directory has to move."""
    def rewrite(match: re.Match) -> str:
        indent, raw, name = match.group(1), match.group(2), match.group(3)
        found = _find(name, base, skin)
        if found is None:
            log.warning("%s includes %r, which is not there", base, name)
            # Left as it was, so Cheetah reports it against the real line
            # rather than this rendering a page with a hole in it.
            return match.group(0)
        if raw:
            # Raw means "do not parse this", so it comes from the skin
            # itself: there is nothing in it for us to have rewritten.
            return f'{indent}#include raw "{found.as_posix()}"'
        here = work / found.relative_to(skin)
        return f'{indent}#include "{here.as_posix()}"'

    return _INCLUDE.sub(rewrite, text)


def _work_name(skin: Path) -> str:
    """A directory name that says which skin it belongs to.

    Readable, then eight hex characters of the whole path: two skins called
    Seasons in two installations must not share a working directory.
    """
    import hashlib

    text = str(skin)
    name = "".join(c if c.isalnum() else "-" for c in skin.name)[:32]
    stamp = hashlib.sha1(text.encode()).hexdigest()[:8]  # noqa: S324
    return f"weewx-evo-skin-{name or 'skin'}-{stamp}"


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
    name = template[:-5] if template.endswith(".tmpl") else template
    return time.strftime(name, time.localtime(when))


def _encode(text: str, encoding: str) -> bytes:
    """The rendered page as bytes, the way the skin asked for."""
    if encoding == "html_entities":
        return text.encode("ascii", "xmlcharrefreplace")
    if encoding == "strict_ascii":
        return text.encode("ascii", "ignore")
    if encoding == "normalized_ascii":
        return unicodedata.normalize("NFD", text).encode("ascii", "ignore")
    return text.encode(encoding or "utf8")


def from_settings(settings: Any, reader: Reader,
                  plots: Any = (), prefix: str = "feeds.cheetah",
                  extra_groups: dict[str, str] | None = None) -> CheetahFeed:
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

    tags = Tags(
        reader=reader,
        target=target,
        unit_system=stored,
        extra_groups=extra_groups,
        station={
            "location": settings.get("station.name") or "",
            "latitude": settings.get("station.latitude"),
            "longitude": settings.get("station.longitude"),
            "altitude": settings.get("station.altitude"),
            "station_url": settings.get("station.url") or "",
            # What the readings come from. WeeWX prints it in a footer, and
            # here it is whichever driver the listener is running.
            "hardware": settings.get("driver") or "",
            "version": _version(),
        },
        rain_year_start=int(settings.get("station.rain_year_start") or 1),
    )
    tags.plots = plots
    tags.language = spoken.code
    tags.moon_phases = spoken.moon_phases()

    skins = Path(str(option("skins_dir") or "skins"))
    skin = str(option("skin") or "").strip()
    feed = CheetahFeed(
        reader=reader,
        skin=skins / skin if skin else skins,
        tags=tags,
        encoding=str(option("encoding") or "html_entities"),
        copy_static=option("copy_static") is not False,
        stale_ok=option("stale_ok") is not False,
        language=spoken.code,
    )
    # An explicit choice on the feed's page beats what the skin asked for.
    # Left empty, the skin decides, which is the point of running it at all.
    feed.skin_units = not chosen
    return feed


def _version() -> str:
    from ... import __version__

    return __version__

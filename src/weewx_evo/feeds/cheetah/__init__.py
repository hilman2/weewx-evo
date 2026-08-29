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

    # -- the feed ---------------------------------------------------------

    def produce(self, into: Path, now: float | None = None) -> Produced:
        started = time.time()
        into = Path(into)
        into.mkdir(parents=True, exist_ok=True)
        self.rendered = self.skipped = 0
        self.failed = []
        # Asked again this run: a template edited between two runs has to
        # be seen, and stat-ing the skin once per run is the price.
        self._skin_mtime = None
        self.summaries = {name: [] for name in SUMMARIES}

        conf = self._skin_conf()
        if conf is None:
            return Produced(directory=into,
                            note=f"no skin.conf in {self.skin}")

        # The skin's own words and units first, its own code second. The
        # other way round, an extension is handed a formatter that has not
        # been told what the skin shows things in, and every number it
        # works out comes back in the unit the archive holds -- a chart
        # captioned in Fahrenheit on a page that says Celsius everywhere
        # else, with nothing anywhere saying why.
        self._extras(conf)
        self.contributed = self._extensions(conf)

        files: list[Path] = []
        section = conf.get("CheetahGenerator") or conf.get("FileGenerator")
        if isinstance(section, dict):
            files += self._generate(section, "", into, conf)
        else:
            log.warning("%s has no [CheetahGenerator]; nothing to render",
                        self.skin)

        if self.copy_static:
            files += self._copy(conf, into)

        swept = self._sweep(into, files)

        note = (f"{self.rendered} page(s) in {time.time() - started:.2f}s"
                + (f", {self.skipped} still fresh" if self.skipped else "")
                + (f", {len(self.failed)} failed" if self.failed else "")
                + (f", {swept} removed" if swept else ""))
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
        # What the operator set on the skin's own page, over what the skin
        # says itself. A skin of ours declares those as `Option`s; one from
        # outside declares none and this does nothing.
        if self.display:
            block = conf.setdefault("DisplayOptions", {})
            if isinstance(block, dict):
                block.update(self.display)
            self.tags.display.update(self.display)
        # The broker, from the upload that already knows it. Before the
        # operator's own settings below, so anything they said by hand still
        # wins -- see `_broker_extras`.
        if self.broker:
            self._broker_extras(conf)
        # The operator's own, last: they are the reason this setting exists.
        if self.extras:
            self.tags.extras.update(self.extras)
            block = conf.setdefault("Extras", {})
            if isinstance(block, dict):
                block.update(self.extras)
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
        span = self.reader.span()
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

    def _sweep(self, into: Path, made: list[Path]) -> int:
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
        """
        if self.failed:
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
    def skin_options(skin: str, skins_dir: Any = None) -> list:
        """What the chosen skin lets an operator set, for the feed's page.

        A skin of ours ships an `options.py` next to its templates, the way
        a driver ships one next to its parser. One entry there makes the
        form field, the validation and the `--explain` line at once.

        A skin from outside has none, and its settings stay in its own
        `skin.conf` -- where its author put them, and where its own
        documentation says they are.
        """
        return skin_options(skin, skins_dir)

    @staticmethod
    def options() -> list:
        from ...options import installed_skins

        return [
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
    out: dict[str, Any] = {}
    for line in str(value).splitlines():
        key, sep, said = line.partition("=")
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
    tags.language = spoken.code
    tags.moon_phases = spoken.moon_phases()
    _install_forecast(tags, settings, spoken)

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
    feed.display = _display(settings, prefix, skin, skins)
    return feed


def skin_options(skin: str, skins_dir: Any = None) -> list[Group]:
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


def _install_forecast(tags: Any, settings: Any, spoken: Any) -> None:
    """Give the skin `$forecast`, if this station fetches one.

    Opened here rather than in `tags.py` for two reasons. A station with no
    forecast configured should not open a database it has no rows in -- and
    the tag layer has no business knowing the forecast package exists, the
    same way it has no business knowing about the exports.

    The file not being there is the ordinary case and is not an error: a
    template asking `#if $forecast` gets a no and renders around it.
    """
    archive = str(settings.get("archive_db") or "data/weewx.sdb")
    path = Path(archive).parent / "forecast.sdb"
    if not path.exists():
        return
    try:
        from ...forecast.store import ForecastStore
        from ...forecast.tags import install

        install(tags, ForecastStore(path), spoken)
    except Exception:
        # A forecast nobody can read must not take a page down. The skin
        # asking for it gets a miss, which the report names.
        log.warning("could not open the forecast at %s; the pages will render "
                    "without it", path, exc_info=True)


def _version() -> str:
    from ... import __version__

    return __version__

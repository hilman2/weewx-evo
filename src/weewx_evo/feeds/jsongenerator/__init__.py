"""The JSON feed: time series as data, for anything that draws.

The feed that ships with weewx-evo and cannot be removed, because everything
else is built on it. A chart in a browser, a page rendered from a template, an
export pushed to a static host, an image generator if one is ever written --
all of them want the same thing, which is a reading over a span at some
resolution, with its unit and its label attached. Producing that once and
writing it to a file means nobody has to reinvent it, and nobody has to
reimplement pulling series out of a database.

That reinvention is not hypothetical. Every JavaScript skin for WeeWX --
Belchertown, wdc, jas and the rest -- carries its own copy of the same idea,
its own chart configuration format and its own bugs in it. None of them share
anything. This exists so that a skin can be a skin.

## What it writes

One file per plot, plus a manifest:

    <destination>/daytempdew.json
    <destination>/weekrain.json
    <destination>/index.json

Each file is one chart's worth of data. The manifest says what exists, so a
client can lay out its page before fetching anything and never asks for a
sensor this station does not have.

Where a station keeps several archives and this feed is told which places to
write for, the directory is the facet:

    <destination>/index.json          the site manifest: comparisons only
    <destination>/daycmpoutTemp.json  a chart whose lines name their places
    <destination>/nordfeld/index.json one place's manifest
    <destination>/nordfeld/daytemp.json

A chart that names no place is the same chart wherever it is drawn, so it is
drawn once per place out of that place's own archive. A chart whose lines name
places is drawn once, at the top. Nothing about that is written into
`plots.toml`: a hundred plots stay a hundred entries and become a hundred
files per place, and the day somebody adds a place no file needs editing.

With one place there is no subdirectory and no new key anywhere -- that is the
layout above, unchanged.

## The shape

    {
      "name": "daytempdew",
      "generated": 1755950000,
      "start": 1755863600, "stop": 1755950000,
      "unit": "degree_C", "unit_label": "\\u00b0C",
      "yscale": [10, 25, 5],
      "daynight": {"first": "night", "transitions": [...], "twilight": [...]},
      "series": [
        {"obs_type": "outTemp", "label": "Outside Temperature",
         "plot_type": "line", "color": "#4282b4",
         "time": [...], "values": [...]}
      ]
    }

Series are two parallel arrays rather than a list of pairs: roughly 30%
smaller on the wire, and the shape every charting library wants.

The readings are converted on the way out. A console that reports Fahrenheit
and a site published in Celsius is the ordinary case, and the archive keeps
what the station wrote.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from ... import chartdata, units
from ...options import Group, Option
from ...plots import Plot, PlotSet
from ...series import Reader
from .. import Produced, archive_names

log = logging.getLogger(__name__)

#: Written into every file, so a client can tell whether it is looking at
#: something it understands. Raised only when the shape changes in a way that
#: would break a reader, not when a key is added.
FORMAT = 1

#: How many decimals. Three is well past any weather sensor's resolution and
#: takes about a third off the size of the file. Defined where the rounding
#: happens; named here because the settings page offers it.
ROUNDING = chartdata.ROUNDING


class JSONGenerator:
    """Turns plot definitions into JSON files."""

    #: A new archive record means new data. Everything a plot draws comes out
    #: of the archive, so there is nothing to redo in between.
    trigger = "record"

    def __init__(self, reader: Reader, plots: PlotSet,
                 target: units.Target | None = None,
                 latitude: float | None = None, longitude: float | None = None,
                 unit_system: int = units.US,
                 extra_groups: dict[str, str] | None = None,
                 rounding: int | None = ROUNDING,
                 indent: int | None = None,
                 labels: dict[str, str] | None = None,
                 spans: tuple[str, ...] = (),
                 manifest: bool = True,
                 twilight: bool = True,
                 rewrite_unchanged: bool = False,
                 archives: dict | None = None,
                 archive: str = "",
                 places: dict | None = None,
                 shown: tuple[str, ...] = ()) -> None:
        self.reader = reader
        self.plots = plots
        self.target = target or units.Target(unit_system)
        self.latitude = latitude
        self.longitude = longitude
        #: What the archive holds. Not what to show: see `target`.
        self.unit_system = unit_system
        #: What a driver contributed about its own fields.
        self.extra_groups = dict(extra_groups or {})
        self.rounding = rounding
        self.indent = indent
        #: Names for readings, when a plot does not give one. Left empty by
        #: default: a client that speaks German should not be handed English.
        self.labels = dict(labels if labels is not None
                           else getattr(plots, "labels", {}) or {})
        #: The other archives, by name, for a plot that draws more than one
        #: place. Paths rather than readers: a connection held across the
        #: feed's whole life is a descriptor kept for the 99% of the time
        #: nothing is being drawn, which is the shape of the leak that took
        #: an instance down at 477 of them.
        self.archives = dict(archives or {})
        #: Which archive `reader` is. Not decoration: a comparison chart's
        #: home line carries a blank `series`, so without this it is the one
        #: line on the chart with no colour, no title and no place -- and it
        #: is the page's own place.
        self.archive = str(archive or "")
        #: What each place is called and drawn in, as `chartdata.Place`. From
        #: `archives.toml`, so the PNG, the JSON and Grafana draw one place in
        #: one colour.
        self.places = dict(places or {})
        #: The places that get a directory of their own this run. Empty is
        #: the flat layout, which is every single-series station and is
        #: today's output byte for byte. The same shape as `spans`, and for
        #: the same reason: it narrows what a run produces without any other
        #: feed having to know.
        self.shown = tuple(shown)
        #: Open only while `produce` runs.
        self._readers: dict = {}
        #: Which groups to produce. Empty means all of them.
        self.spans = tuple(spans)
        self.manifest = manifest
        self.twilight = twilight
        #: Rewriting a file whose data is identical costs an upload of it.
        self.rewrite_unchanged = rewrite_unchanged
        self.written = 0
        self.skipped = 0
        self.unchanged = 0

    # -- the feed ---------------------------------------------------------

    def produce(self, into: Path, now: float | None = None) -> Produced:
        """Write every plot. The other series are opened for this run only."""
        from ... import series as series_module
        from ...plots import series_named

        # Every archive a plot names, plus every place this run writes a
        # directory for. Not the feed's own: `self.reader` is already open,
        # handed in by the runner, and opening it again by name would be a
        # second connection to a file we are already reading.
        wanted = series_named(self.plots) | set(self.shown)
        wanted.discard(self.archive)
        with series_module.opened(self.archives, wanted) as readers:
            if self.archive:
                readers[self.archive] = self.reader
            self._readers = readers
            try:
                return self._produce(into, now)
            finally:
                self._readers = {}

    def _produce(self, into: Path, now: float | None = None) -> Produced:
        """Write every plot, and the manifest. Returns what was made."""
        started = time.time()
        into = Path(into)
        into.mkdir(parents=True, exist_ok=True)

        generated = self._generated(now)
        if generated is None:
            log.info("nothing in the archive yet, so nothing to draw")
            return Produced(directory=into, note="the archive is empty")

        files: list[Path] = []
        self.written = self.skipped = self.unchanged = 0

        if not self.shown:
            # One archive, or a feed nobody told about places: today's path,
            # flat filenames and a manifest with no `archives` key.
            files += self._pass(into, generated, list(self.plots),
                                self.reader, self.archive)
            note = self._note(started)
            log.info("wrote %s", note)
            return Produced(directory=into, files=files, note=note)

        # A chart that names a place is drawn once, out of the archives it
        # names, at the top. A chart that names none is drawn once per place,
        # out of THAT place's archive -- because a blank `series` has always
        # meant "the archive this chart is being drawn for", and a per-place
        # pass is that sentence with a different archive handed in.
        comparisons = [p for p in self.plots if p.names_a_place()]
        own = [p for p in self.plots if not p.names_a_place()]

        files += self._pass(into, generated, comparisons,
                            self.reader, self.archive, roster=True)
        for name in self.shown:
            source = (self.reader if name and name == self.archive
                      else self._readers.get(name))
            if source is None:
                # An archive configured for a place that has not written a
                # record yet. Named and skipped: a directory that is not
                # there is a page that says so, and an empty one is a page
                # full of charts of nothing.
                log.info("no archive open for the place %r, so it gets no "
                         "charts this run", name)
                continue
            files += self._pass(into / name, generated, own, source, name)

        note = self._note(started)
        log.info("wrote %s", note)
        return Produced(directory=into, files=files, note=note)

    def _generated(self, now: float | None) -> int | None:
        """The moment every chart in this run stops at, or None if nothing.

        One stop for the whole run, not one per pass. Two charts on one page
        whose x-axes end an hour apart is the thing a comparison must not do,
        and sub-day buckets step from the span *start*, so two places given
        spans a second apart come back on grids a second offset for the whole
        chart. `_same()` ignores `generated`, so taking the latest costs no
        uploads.
        """
        newest = None
        seen: list[int] = []
        for one in (self.reader, *self._readers.values()):
            # By identity: `_readers[self.archive]` IS `self.reader`, so the
            # home archive would otherwise be asked for its span twice on
            # every produce.
            if id(one) in seen:
                continue
            seen.append(id(one))
            span = one.span()
            if span and (newest is None or span[1] > newest):
                newest = span[1]
        if newest is None:
            return None
        return int(now if now is not None else newest)

    def _pass(self, into: Path, generated: int, plots: list[Plot],
              reader: Reader, place: str,
              roster: bool = False) -> list[Path]:
        """One directory: its charts and its own manifest.

        `roster` is the root of a site with several places, the only manifest
        that lists them -- a place's own directory has one place in it and
        saying so again would be a key every reader has to learn to ignore.
        """
        into.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        manifest: list[dict[str, Any]] = []

        for plot in plots:
            if self.spans and plot.span not in self.spans:
                continue
            try:
                payload = self.build(plot, generated, reader=reader,
                                     place=place)
            except Exception:
                # One broken plot must not cost the other ninety-nine. A
                # station with a sensor that stopped reporting should still
                # get its temperature chart.
                log.exception("could not build the plot %r", plot.name)
                continue
            if payload is None:
                self.skipped += 1
                continue

            path = into / f"{plot.name}.json"
            try:
                if self._same(path, payload):
                    self.unchanged += 1
                else:
                    self._write(path, payload)
                    files.append(path)
                    self.written += 1
            except OSError as exc:
                log.error("could not write %s: %s", path, exc)
                continue
            entry = {
                "name": plot.name,
                "group": plot.span,
                "title": plot.title or ", ".join(
                    s["label"] for s in payload["series"] if s["label"]),
                "unit_label": payload["unit_label"],
                "obs_types": [s["obs_type"] for s in payload["series"]],
            }
            # Never in `name`. A manifest name is span-prefixed and a page
            # matches `data-only` against either the name or the span plus
            # the name; a place folded into the string breaks that match and
            # with it every hand-listed chart on every page.
            if payload.get("places"):
                entry["archives"] = list(payload["places"])
            manifest.append(entry)

        if not self.manifest:
            return files

        index = into / "index.json"
        listing: dict[str, Any] = {
            "format": FORMAT,
            "generated": generated,
            # The spans of the plots written into THIS directory, not of the
            # whole set. A compare page lays a grid out per span, and a root
            # manifest advertising `year` when no comparison covers a year
            # is an empty grid on a published page. With one place the two
            # are the same list, so nothing moves there.
            "spans": PlotSet(plots).spans(),
            "plots": manifest,
        }
        if roster:
            listing["archives"] = self._roster()
        try:
            # Held to the same rule as the plots: an unchanged manifest that
            # gets rewritten every interval is one file an export uploads
            # every interval for nothing.
            if not self._same(index, listing):
                self._write(index, listing)
                files.append(index)
        except OSError as exc:
            log.error("could not write %s: %s", index, exc)
        return files

    def _roster(self) -> list[dict[str, Any]]:
        """The places this run wrote a directory for, in that order.

        Their names, labels, codes and colours, so a page can draw a legend
        and a switcher without a second file. `shown` decides the order,
        because that is the order the operator put them in.
        """
        out = []
        for name in self.shown:
            known = self.places.get(name)
            out.append({
                "name": name,
                "label": getattr(known, "title", "") or name,
                "code": getattr(known, "code", "") or "",
                "color": getattr(known, "color", "") or "",
                "path": f"{name}/",
            })
        return out

    def _note(self, started: float) -> str:
        return (f"{self.written} plot(s) in {time.time() - started:.2f}s"
                + (f", {self.unchanged} unchanged" if self.unchanged else "")
                + (f", {self.skipped} with no data" if self.skipped else ""))

    def _same(self, path: Path, payload: dict) -> bool:
        """Whether the file already there says the same thing.

        Everything but the timestamp: a file written a minute ago holding the
        same readings is the same file, and rewriting it makes an export think
        it changed.
        """
        if self.rewrite_unchanged or not path.exists():
            return False
        try:
            with open(path, encoding="utf-8") as fp:
                existing = json.load(fp)
        except (OSError, ValueError):
            return False
        return {k: v for k, v in existing.items() if k != "generated"} \
            == {k: v for k, v in payload.items() if k != "generated"}

    def _write(self, path: Path, payload: dict) -> None:
        """One file, written beside and moved into place.

        A client polling this while it is half written should get the old one,
        not half of the new one.
        """
        partial = path.with_suffix(".json.part")
        with open(partial, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=self.indent, ensure_ascii=False,
                      separators=(",", ":") if self.indent is None else None)
        partial.replace(path)

    # -- one plot ---------------------------------------------------------

    def build(self, plot: Plot, generated: float,
              reader: Reader | None = None,
              place: str = "") -> dict[str, Any] | None:
        """One plot's payload, or None if there is nothing in it.

        The numbers come from `chartdata`, which the image feed reads too.
        Working them out here as well is how two renderers of the same plot
        come to disagree in the third decimal place.

        `reader` and `place` are which archive this pass is drawing for. They
        default to the feed's own, which is every station with one place.
        """
        source = reader or self.reader
        # What the archive THIS pass reads holds. `self.unit_system` is the
        # feed's own archive's, and a per-place pass is handed a different
        # one: the north field's console may still be sending Fahrenheit
        # while the home archive is metric, and converting its records out
        # of the home archive's system is a silent thirty degrees on that
        # place's own pages.
        held = (self.unit_system if source is self.reader
                else source.system)
        chart = chartdata.build(
            plot, source, generated, target=self.target,
            unit_system=held, extra_groups=self.extra_groups,
            labels=self.labels, rounding=self.rounding,
            latitude=self.latitude, longitude=self.longitude,
            twilight=self.twilight, readers=self._readers,
            places=self.places, place=place or self.archive)
        if chart is None:
            return None
        return _document(chart, generated)

    # -- what the admin page asks for -------------------------------------

    @staticmethod
    def options() -> list:
        """The settings one of these offers.

        Bare names, and the page supplies the prefix -- the same arrangement
        an export has, and the reason a station can run two of these with
        different settings.
        """
        def unit_choice(group: str, *offered: str) -> tuple:
            # The name, and how it is printed after a number -- unless those
            # are the same word, which for mmHg they are.
            out = []
            for unit in offered:
                shown = units.label(unit).strip()
                out.append((unit, unit if shown in ("", unit)
                            else f"{unit}   {shown}"))
            return tuple(out)

        return [
            Group("Writing", "Where the files go and what is in them.", (
                Option("enabled", "Produce the JSON",
                       kind="bool", default=True,
                       help="Off only if nothing reads it. Every other "
                            "feed that draws a chart does."),
                Option("destination", "Directory",
                       default="json",
                       help="Under the feed output directory. A "
                            "subdirectory rather than the top level, so "
                            "the data does not sit among the pages."),
                Option("manifest", "Write index.json",
                       kind="bool", default=True,
                       help="A list of what exists, so a client can lay "
                            "out its page before fetching anything and "
                            "never asks for a sensor this station does "
                            "not have."),
                Option("rewrite_unchanged",
                       "Rewrite files that have not changed",
                       kind="bool", default=False,
                       help="A year of daily averages says the same thing "
                            "at ten past as it did at ten o'clock. Left "
                            "off, a file whose data is identical is not "
                            "touched -- which matters if an export sends "
                            "everything that changed, over a connection "
                            "somebody pays for by the megabyte."),
                Option("rounding", "Decimals", kind="int",
                       default=ROUNDING, minimum=0, maximum=9,
                       help="Three is already finer than any weather "
                            "sensor and takes about a third off the size "
                            "of every file. Raise it only for something "
                            "that is not weather."),
                Option("indent", "Indent the files",
                       kind="int", default=0, minimum=0, maximum=8,
                       advanced=True,
                       help="0 writes them as small as possible, which is "
                            "what you want on a live site. 2 makes them "
                            "readable while you are working out why a "
                            "chart looks wrong."),
                # A list and not a text box: `choices_from` is read for a
                # choice and for a list, and nowhere else. Declared as text
                # it rendered as a free-typed field whose only suggestion
                # was the empty string -- the archive names were built,
                # handed over and thrown away, and the one thing an operator
                # needs here is the list of names they may type.
                Option("places", "Only these places", kind="list",
                       advanced=True, closed=True,
                       choices_from=archive_names,
                       help="One per row. Empty writes a directory of "
                            "charts for every place, which is the safe "
                            "side: a directory nothing links to costs disk, "
                            "and a directory a page links to and that is "
                            "not there is a broken page. Narrow it where a "
                            "metered link makes a hundred files per place "
                            "worth thinking about. Not the same setting as "
                            "a skin's: that says which places a site shows, "
                            "this says which a chart directory covers."),
                Option("spans", "Only these groups",
                       default="",
                       advanced=True,
                       suggestions=(("", "all of them"),
                                    ("day,week", "just the short ones")),
                       help="Comma separated, matching the group a chart "
                            "is in. Empty produces all of them. A year "
                            "chart over a decade of records is the "
                            "expensive one; leaving it out is how a small "
                            "machine keeps up."),
            )),
            Group("Units", "What the readings are shown in.", (
                Option("units", "Unit system",
                       kind="choice", default="METRICWX",
                       choices=tuple((units.NAMES[k], v) for k, v
                                     in units.DESCRIPTIONS.items()),
                       help="What the files are written in, whatever the "
                            "archive holds. A console that reports "
                            "Fahrenheit and a site in Celsius is the "
                            "ordinary case: the archive keeps what the "
                            "station wrote and the conversion happens on "
                            "the way out."),
                Option("unit.group_temperature", "Temperature",
                       kind="choice", default="",
                       choices=(("", "-- as the system above --"),)
                       + unit_choice("group_temperature", "degree_C",
                                     "degree_F", "degree_K"),
                       help="Overrides the system for this one group. "
                            "Which is how somebody ends up with degrees "
                            "Celsius and inches of mercury on one page, "
                            "because that is what their readers expect."),
                Option("unit.group_pressure", "Pressure",
                       kind="choice", default="",
                       choices=(("", "-- as the system above --"),)
                       + unit_choice("group_pressure", "mbar", "hPa",
                                     "inHg", "mmHg", "kPa")),
                Option("unit.group_rain", "Rain",
                       kind="choice", default="",
                       choices=(("", "-- as the system above --"),)
                       + unit_choice("group_rain", "mm", "cm", "inch")),
                Option("unit.group_speed", "Wind speed",
                       kind="choice", default="",
                       choices=(("", "-- as the system above --"),)
                       + unit_choice("group_speed", "meter_per_second",
                                     "km_per_hour", "mile_per_hour",
                                     "knot")),
                Option("unit.group_altitude", "Height",
                       kind="choice", default="",
                       choices=(("", "-- as the system above --"),)
                       + unit_choice("group_altitude", "meter", "foot"),
                       advanced=True),
                Option("unit.group_distance", "Distance",
                       kind="choice", default="",
                       choices=(("", "-- as the system above --"),)
                       + unit_choice("group_distance", "km", "mile"),
                       advanced=True),
            )),
            Group("Night", "What a chart needs to shade darkness.", (
                Option("twilight", "Include dawn and dusk",
                       kind="bool", default=True,
                       help="Dusk is not an edge: the light fades over "
                            "the half hour of civil twilight, and over "
                            "far longer at high latitude in summer. With "
                            "this on, a chart can draw the real thing "
                            "instead of a step. Costs a few hundred bytes "
                            "per file."),
            )),
        ]


# -- trimming --------------------------------------------------------------

def _document(chart: chartdata.Chart, generated: float) -> dict[str, Any]:
    """A chart as the document a client reads.

    Only the shape lives here. Anything that decides a *number* belongs in
    `chartdata`, where the other renderer can reach it too.
    """
    series = []
    for line in chart.lines:
        entry: dict[str, Any] = {
            "obs_type": line.obs_type,
            "label": line.label,
            "plot_type": line.plot_type,
            "color": line.color,
        }
        # The chart's own unit is stated once at the top; a line repeats it
        # only when it disagrees, which is a plot with two units in it. Two
        # details are kept exactly as they were, deliberately: a line with no
        # unit still carries the key, and the key sits here rather than at
        # the end. Both would be small improvements, and an improvement
        # smuggled into a move is one nobody can check -- and the second one
        # would make every file on every station count as changed and go up
        # the wire once for nothing.
        if line.unit != chart.unit:
            entry["unit"] = line.unit
        if line.series:
            entry["series"] = line.series
        if line.series and line.stored_unit and line.stored_unit != line.unit:
            # What a page would print as "Nordfeld records in degrees F and
            # was converted". Twenty bytes. No skin reads it yet, and that is
            # the point of writing it: a document that carries the unit its
            # numbers were stored in can answer the question later without
            # every published file having to be produced again.
            #
            # Only on a line that names a place. Every station that publishes
            # in a unit its console does not send has a line disagreeing with
            # its archive -- that is the ordinary case and the document says
            # its unit at the top. Written unconditionally it would be a new
            # key in most files on most stations, for a sentence only a
            # comparison can print.
            entry["stored_unit"] = line.stored_unit
        entry["time"] = line.time
        entry["values"] = line.values
        if line.fill_color:
            entry["fill_color"] = line.fill_color
        if line.aggregate_type:
            entry["aggregate_type"] = line.aggregate_type
            entry["aggregate_interval"] = line.aggregate_interval
        if line.directions is not None:
            entry["directions"] = line.directions
        if line.bar_width is not None:
            entry["bar_width"] = line.bar_width
        if line.plot_type == "vector":
            entry["vector_x"] = line.vector_x
            entry["vector_y"] = line.vector_y
            if line.vector_rotate is not None:
                # Negated on the way out, as the ImageGenerator has it: a
                # client draws where y grows downwards, and without the
                # minus the arrows come out mirrored against the PNG of the
                # same data.
                entry["vector_rotate"] = -line.vector_rotate
            entry["rose_label"] = "N"
        if line.marker:
            entry["marker"] = line.marker
            if line.marker_size is not None:
                entry["marker_size"] = line.marker_size
        if line.width is not None:
            entry["width"] = line.width
        series.append(entry)

    payload: dict[str, Any] = {
        "name": chart.name,
        "format": FORMAT,
        "generated": int(generated),
        "start": chart.start,
        "stop": chart.stop,
        "asked": list(chart.asked),
        "unit": chart.unit,
        "unit_label": chart.unit_label,
        "series": series,
    }
    # Always a title, because whoever draws this has nowhere else to get
    # one. A plot that names itself keeps its name; one that does not is
    # called after what is in it, which is the same fallback the manifest
    # uses -- and two different answers to "what is this chart called" is
    # how a page and its index stop agreeing.
    payload["title"] = chart.title or ", ".join(
        one["label"] for one in series if one.get("label"))
    if any(v is not None for v in chart.yscale):
        payload["yscale"] = list(chart.yscale)
    if chart.daynight:
        payload["daynight"] = chart.daynight
    # What makes a chart a comparison: more than one place in it. No separate
    # marking, and nothing is written on a chart that draws one place -- so a
    # single-series station's files are byte-identical and `_same` reports
    # nothing changed.
    if len(chart.places) > 1:
        payload["places"] = list(chart.places)
        payload["note"] = chart.note
    return payload


def from_settings(settings: Any, reader: Reader, plots: PlotSet,
                  extra_groups: dict[str, str] | None = None,
                  prefix: str = "feeds.json",
                  archives: dict | None = None,
                  archive: str = "",
                  places: dict | None = None,
                  shown: tuple[str, ...] = ()) -> JSONGenerator:
    """Build the generator from the configuration.

    `prefix` names the configured feed, so two of them can be set up
    differently -- one in metric for a site, one in US units for somebody
    else's uploader -- without either knowing about the other.
    """
    def option(name: str, fallback: Any = None) -> Any:
        found = settings.get(f"{prefix}.{name}")
        return fallback if found is None else found

    # What the archive holds, read from the archive. `station.units` is not
    # an option this program declares anywhere -- it was read here and
    # nowhere else, so every installation converted as though its records
    # were in US units. A German station writing metricwx had every chart
    # off by a Fahrenheit-to-Celsius conversion, and nothing said so because
    # each number was internally consistent. The image and Cheetah feeds
    # both ask the reader; so does this one now.
    stored = reader.system
    indent = int(option("indent") or 0)

    # A group named on its own wins over the system. Somebody wanting Celsius
    # and inches of mercury on one page is not confused; that is what their
    # readers expect.
    overrides = {}
    for group in ("group_temperature", "group_pressure", "group_rain",
                  "group_speed", "group_altitude", "group_distance"):
        chosen = (option(f"unit.{group}") or "").strip()
        if chosen:
            overrides[group] = chosen
    # The station's language, or this feed's own. A chart published as a file
    # carries the name of every reading in it, and that name is read by
    # somebody: on a German station these files said "Outside Temperature"
    # because nothing here ever passed a language along.
    from ... import language as language_module

    spoken = language_module.get(option("lang") or settings.get("language"))
    try:
        target = units.Target(option("units") or "METRICWX",
                              overrides, language=spoken)
    except ValueError as exc:
        # A unit a group cannot be shown in. Named, and then ignored, rather
        # than stopping a station from producing anything at all.
        log.error("%s -- the overrides are being ignored", exc)
        target = units.Target(option("units") or "METRICWX",
                              language=spoken)

    spans = tuple(s.strip() for s
                  in str(option("spans") or "").split(",")
                  if s.strip())
    # Narrowed by the setting, and only ever narrowed: a name nobody handed
    # in is a directory the pages would link to and that would not be there.
    narrowed = _names(option("places"))
    if narrowed:
        kept = tuple(one for one in shown if one in narrowed)
        unknown = [one for one in narrowed if one not in shown]
        if kept:
            shown = kept
        elif shown:
            # An empty intersection is a typo, and it must not be obeyed: `()`
            # is the flag for "one place, today's flat layout", so a narrowing
            # that matches nothing would silently remove every place directory
            # and 404 every place page -- the opposite of narrowing, under a
            # setting whose empty value means "every place". Ignored and said
            # out loud instead.
            log.error("the places setting names %s, and this feed was handed "
                      "%s; ignoring it and writing every place",
                      ", ".join(narrowed) or "nothing", ", ".join(shown))
        if unknown and kept:
            log.warning("the places setting names %s, which this feed was "
                        "not handed; writing %s",
                        ", ".join(unknown), ", ".join(shown))

    return JSONGenerator(
        reader=reader,
        plots=plots,
        target=target,
        latitude=_number(settings.get("station.latitude")),
        longitude=_number(settings.get("station.longitude")),
        unit_system=stored,
        extra_groups=extra_groups,
        rounding=int(option("rounding") or ROUNDING),
        indent=indent or None,
        spans=spans,
        manifest=_truth(option("manifest"), True),
        twilight=_truth(option("twilight"), True),
        rewrite_unchanged=_truth(
            option("rewrite_unchanged"), False),
        archives=archives,
        archive=archive,
        places=places,
        shown=shown,
    )


def _names(value: Any) -> tuple[str, ...]:
    """The names in a list setting, however it came to be written.

    A `kind="list"` option arrives as a list from the settings page and as a
    line-per-entry string from `render`, but this file is meant to be edited
    by hand and the help text asked for commas for as long as it was a text
    box. Splitting on both is one line and saves a setting that matches
    nothing -- which here would take every place directory away.
    """
    if isinstance(value, (list, tuple)):
        items = [str(one) for one in value]
    else:
        items = [part for row in str(value or "").splitlines()
                 for part in row.split(",")]
    return tuple(one.strip() for one in items if one.strip())


def _truth(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

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
from .. import Produced

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
                 rewrite_unchanged: bool = False) -> None:
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
        """Write every plot, and the manifest. Returns what was made."""
        started = time.time()
        into = Path(into)
        into.mkdir(parents=True, exist_ok=True)

        span = self.reader.span()
        if span is None:
            log.info("nothing in the archive yet, so nothing to draw")
            return Produced(directory=into, note="the archive is empty")
        generated = int(now if now is not None else span[1])

        files: list[Path] = []
        manifest: list[dict[str, Any]] = []
        self.written = self.skipped = self.unchanged = 0

        for plot in self.plots:
            if self.spans and plot.span not in self.spans:
                continue
            try:
                payload = self.build(plot, generated)
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
            manifest.append({
                "name": plot.name,
                "group": plot.span,
                "title": plot.title or ", ".join(
                    s["label"] for s in payload["series"] if s["label"]),
                "unit_label": payload["unit_label"],
                "obs_types": [s["obs_type"] for s in payload["series"]],
            })

        if not self.manifest:
            note = self._note(started)
            log.info("wrote %s", note)
            return Produced(directory=into, files=files, note=note)

        index = into / "index.json"
        listing = {
            "format": FORMAT,
            "generated": generated,
            "spans": self.plots.spans(),
            "plots": manifest,
        }
        try:
            # Held to the same rule as the plots: an unchanged manifest that
            # gets rewritten every interval is one file an export uploads
            # every interval for nothing.
            if not self._same(index, listing):
                self._write(index, listing)
                files.append(index)
        except OSError as exc:
            log.error("could not write %s: %s", index, exc)

        note = self._note(started)
        log.info("wrote %s", note)
        return Produced(directory=into, files=files, note=note)

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

    def build(self, plot: Plot, generated: float) -> dict[str, Any] | None:
        """One plot's payload, or None if there is nothing in it.

        The numbers come from `chartdata`, which the image feed reads too.
        Working them out here as well is how two renderers of the same plot
        come to disagree in the third decimal place.
        """
        chart = chartdata.build(
            plot, self.reader, generated, target=self.target,
            unit_system=self.unit_system, extra_groups=self.extra_groups,
            labels=self.labels, rounding=self.rounding,
            latitude=self.latitude, longitude=self.longitude,
            twilight=self.twilight)
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
    if chart.title:
        payload["title"] = chart.title
    if any(v is not None for v in chart.yscale):
        payload["yscale"] = list(chart.yscale)
    if chart.daynight:
        payload["daynight"] = chart.daynight
    return payload


def from_settings(settings: Any, reader: Reader, plots: PlotSet,
                  extra_groups: dict[str, str] | None = None,
                  prefix: str = "feeds.json") -> JSONGenerator:
    """Build the generator from the configuration.

    `prefix` names the configured feed, so two of them can be set up
    differently -- one in metric for a site, one in US units for somebody
    else's uploader -- without either knowing about the other.
    """
    def option(name: str, fallback: Any = None) -> Any:
        found = settings.get(f"{prefix}.{name}")
        return fallback if found is None else found

    stored = units.system_from(settings.get("station.units") or units.US)
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
    try:
        target = units.Target(option("units") or "METRICWX",
                              overrides)
    except ValueError as exc:
        # A unit a group cannot be shown in. Named, and then ignored, rather
        # than stopping a station from producing anything at all.
        log.error("%s -- the overrides are being ignored", exc)
        target = units.Target(option("units") or "METRICWX")

    spans = tuple(s.strip() for s
                  in str(option("spans") or "").split(",")
                  if s.strip())

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
    )


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

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

from ... import sun, units
from ...options import Group, Option, Schema
from ...plots import Plot, PlotSet
from ...series import Reader, Series, VECTORS
from .. import Produced

log = logging.getLogger(__name__)

#: Written into every file, so a client can tell whether it is looking at
#: something it understands. Raised only when the shape changes in a way that
#: would break a reader, not when a key is added.
FORMAT = 1

#: How many decimals. Three is well past any weather sensor's resolution and
#: takes about a third off the size of the file.
ROUNDING = 3

#: A run of readings this many times the usual spacing apart is a gap in the
#: data rather than its rhythm. Judged from the readings themselves, because
#: ten minutes between them is a break for a station reporting every eight
#: seconds and business as usual for one reporting every ten.
GAP_FACTOR = 3.0

#: How far back `skip_if_empty` looks. A sensor with nothing over its span is
#: one this station does not have.
SPAN_LENGTHS = {
    "hour": 3600, "day": 86400, "week": 604800,
    "month": 2592000, "year": 31536000,
}


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

        Every line is fetched, converted, and trimmed of the points that carry
        nothing. A plot where every line came back empty is not written at
        all: the shipped set covers sensors most stations do not have, and a
        hundred files of nulls help nobody.
        """
        stop = int(generated)
        start = stop - int(plot.time_length)

        entries = []
        covered_from, covered_to = start, stop
        for line in plot.drawn:
            entry = self._line(line, start, stop, plot.skip_if_empty)
            if entry is None:
                continue
            # A bucket is drawn as what it covers, and the last one of a
            # daily chart covers the whole of today -- so it ends at
            # tomorrow's midnight, after the moment the file was written.
            # The span has to hold what is in it or the last bar falls off
            # the edge of the chart.
            reach = entry.pop("_reach", None)
            if reach:
                covered_from = min(covered_from, reach[0])
                covered_to = max(covered_to, reach[1])
            entries.append(entry)

        # One axis, so one unit: the first line that has one decides. WeeWX
        # refuses outright to draw two units together. This reports the first
        # and leaves the rest on the lines, so a client can at least see the
        # disagreement rather than being told the plot is impossible.
        unit = next((e["unit"] for e in entries if e.get("unit")), "")
        unit_label = units.label(unit).strip()
        for entry in entries:
            if entry.get("unit") == unit:
                entry.pop("unit", None)

        if not entries:
            return None

        payload: dict[str, Any] = {
            "name": plot.name,
            "format": FORMAT,
            "generated": int(generated),
            "start": int(covered_from),
            "stop": int(covered_to),
            "asked": [start, stop],
            "unit": unit,
            "unit_label": unit_label,
            "series": entries,
        }
        if plot.title:
            payload["title"] = plot.title
        if any(v is not None for v in plot.yscale):
            payload["yscale"] = list(plot.yscale)

        if plot.show_daynight:
            try:
                bands = sun.day_night(start, stop, self.latitude,
                                      self.longitude)
                if bands:
                    if not self.twilight:
                        bands.pop("twilight", None)
                    payload["daynight"] = bands
            except Exception as exc:  # noqa: BLE001
                # Shading is decorative and must never break a report. But a
                # silent failure here once hid a real bug, so say something.
                log.warning("could not work out day and night for %r: %s",
                            plot.name, exc)
        return payload

    def _line(self, line: Any, start: int, stop: int,
              skip_if_empty: str = "") -> dict[str, Any] | None:
        """One reading, fetched and made ready to write.

        None where this station does not have the sensor at all. A sensor it
        does have but which reported nothing over this span comes back as a
        series with no points: the client keeps its layout, and the gap is
        visible as a gap rather than as a chart that quietly disappeared.
        """
        series = self.reader.series(line.obs, start, stop,
                                    aggregate=line.aggregate or None,
                                    interval=line.interval)
        if not len(series) or series.empty:
            if not self._exists(line.obs, start, stop, skip_if_empty):
                return None
            series = Series(obs_type=line.obs, aggregate=line.aggregate or None,
                            interval=line.interval,
                            directions=[] if series.directions is not None
                            else None)

        values, unit, _group = self.target.convert(
            series.values, line.obs, self.unit_system,
            aggregate=line.aggregate or None, extra=self.extra_groups)

        entry: dict[str, Any] = {
            "obs_type": line.obs,
            "label": line.label or self.labels.get(line.obs, ""),
            "plot_type": line.kind,
            "color": line.color,
            "unit": unit,
            "time": [int(t) for t in series.time],
            "values": _round(values, self.rounding),
        }
        if line.fill_color:
            entry["fill_color"] = line.fill_color
        if line.aggregate:
            entry["aggregate_type"] = line.aggregate
            entry["aggregate_interval"] = line.interval
        if series.directions is not None:
            # One decimal is already finer than any wind vane.
            entry["directions"] = _round(series.directions, 1)
        if line.kind == "bar":
            # In seconds, so a client can size the bars. A month of daily
            # bars is not a month of equal ones -- the change to summer time
            # makes one of them an hour shorter.
            entry["bar_width"] = [int(b - a) for a, b
                                  in zip(series.start, series.stop)]
        if line.kind == "vector":
            entry["vector_x"], entry["vector_y"] = _components(
                entry["values"], entry.get("directions"), self.rounding)
            if line.rotate is not None:
                # Negated, as the ImageGenerator has it. Without the minus the
                # arrows come out mirrored against the PNG of the same data.
                entry["vector_rotate"] = -float(line.rotate)
            entry["rose_label"] = "N"
        if line.marker:
            entry["marker"] = line.marker
            if line.marker_size is not None:
                entry["marker_size"] = line.marker_size
        if line.width is not None:
            entry["width"] = line.width

        _drop_empty(entry, line.gap_fraction, stop - start,
                    aggregated=bool(line.aggregate))
        if series.start and series.stop:
            entry["_reach"] = (int(min(series.start)), int(max(series.stop)))
        return entry

    def _exists(self, obs_type: str, start: int, stop: int,
                skip_if_empty: str) -> bool:
        """Whether this station has this sensor at all.

        The difference between a reading that is missing today and one that
        has never existed. WeeWX's `skip_if_empty = year` says exactly this,
        and it is why the shipped Seasons plot set does not litter a
        two-sensor station with ninety files of nulls.
        """
        if not skip_if_empty:
            return True
        length = SPAN_LENGTHS.get(skip_if_empty)
        if length is None:
            # `plot`, or anything unrecognised: the plot's own span, which is
            # the one just looked at and found empty.
            return False
        try:
            return bool(self.reader.aggregate(
                _column(obs_type), stop - length, stop, "not_null"))
        except Exception:  # noqa: BLE001
            return True

    # -- what the admin page asks for -------------------------------------

    @staticmethod
    def options() -> Schema:
        """The settings this feed offers, for the admin page and the file."""
        def unit_choice(group: str, *units_offered: str) -> tuple:
            # The name, and how it is printed after a number -- unless those
            # are the same word, which for mmHg they are.
            out = []
            for unit in units_offered:
                shown = units.label(unit).strip()
                out.append((unit, unit if shown in ("", unit)
                            else f"{unit}   {shown}"))
            return tuple(out)

        return Schema(
            "feeds.json",
            "JSON",
            (
                Group("Writing", "Where the files go and what is in them.", (
                    Option("feeds.json.enabled", "Produce the JSON",
                           kind="bool", default=True,
                           help="Off only if nothing reads it. Every other "
                                "feed that draws a chart does."),
                    Option("feeds.json.destination", "Directory",
                           default="json",
                           help="Under the feed output directory. A "
                                "subdirectory rather than the top level, so "
                                "the data does not sit among the pages."),
                    Option("feeds.json.manifest", "Write index.json",
                           kind="bool", default=True,
                           help="A list of what exists, so a client can lay "
                                "out its page before fetching anything and "
                                "never asks for a sensor this station does "
                                "not have."),
                    Option("feeds.json.rewrite_unchanged",
                           "Rewrite files that have not changed",
                           kind="bool", default=False,
                           help="A year of daily averages says the same thing "
                                "at ten past as it did at ten o'clock. Left "
                                "off, a file whose data is identical is not "
                                "touched -- which matters if an export sends "
                                "everything that changed, over a connection "
                                "somebody pays for by the megabyte."),
                    Option("feeds.json.rounding", "Decimals", kind="int",
                           default=ROUNDING, minimum=0, maximum=9,
                           help="Three is already finer than any weather "
                                "sensor and takes about a third off the size "
                                "of every file. Raise it only for something "
                                "that is not weather."),
                    Option("feeds.json.indent", "Indent the files",
                           kind="int", default=0, minimum=0, maximum=8,
                           advanced=True,
                           help="0 writes them as small as possible, which is "
                                "what you want on a live site. 2 makes them "
                                "readable while you are working out why a "
                                "chart looks wrong."),
                    Option("feeds.json.spans", "Only these groups",
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
                    Option("feeds.json.units", "Unit system",
                           kind="choice", default="METRICWX",
                           choices=tuple((units.NAMES[k], v) for k, v
                                         in units.DESCRIPTIONS.items()),
                           help="What the files are written in, whatever the "
                                "archive holds. A console that reports "
                                "Fahrenheit and a site in Celsius is the "
                                "ordinary case: the archive keeps what the "
                                "station wrote and the conversion happens on "
                                "the way out."),
                    Option("feeds.json.unit.group_temperature", "Temperature",
                           kind="choice", default="",
                           choices=(("", "-- as the system above --"),)
                           + unit_choice("group_temperature", "degree_C",
                                         "degree_F", "degree_K"),
                           help="Overrides the system for this one group. "
                                "Which is how somebody ends up with degrees "
                                "Celsius and inches of mercury on one page, "
                                "because that is what their readers expect."),
                    Option("feeds.json.unit.group_pressure", "Pressure",
                           kind="choice", default="",
                           choices=(("", "-- as the system above --"),)
                           + unit_choice("group_pressure", "mbar", "hPa",
                                         "inHg", "mmHg", "kPa")),
                    Option("feeds.json.unit.group_rain", "Rain",
                           kind="choice", default="",
                           choices=(("", "-- as the system above --"),)
                           + unit_choice("group_rain", "mm", "cm", "inch")),
                    Option("feeds.json.unit.group_speed", "Wind speed",
                           kind="choice", default="",
                           choices=(("", "-- as the system above --"),)
                           + unit_choice("group_speed", "meter_per_second",
                                         "km_per_hour", "mile_per_hour",
                                         "knot")),
                    Option("feeds.json.unit.group_altitude", "Height",
                           kind="choice", default="",
                           choices=(("", "-- as the system above --"),)
                           + unit_choice("group_altitude", "meter", "foot"),
                           advanced=True),
                    Option("feeds.json.unit.group_distance", "Distance",
                           kind="choice", default="",
                           choices=(("", "-- as the system above --"),)
                           + unit_choice("group_distance", "km", "mile"),
                           advanced=True),
                )),
                Group("Night", "What a chart needs to shade darkness.", (
                    Option("feeds.json.twilight", "Include dawn and dusk",
                           kind="bool", default=True,
                           help="Dusk is not an edge: the light fades over "
                                "the half hour of civil twilight, and over "
                                "far longer at high latitude in summer. With "
                                "this on, a chart can draw the real thing "
                                "instead of a step. Costs a few hundred bytes "
                                "per file."),
                )),
            ),
            help="The time series every other feed is built on: one file per "
                 "chart, plus a manifest of what exists.",
            kind="feed")


# -- trimming --------------------------------------------------------------

def _column(obs_type: str) -> str:
    """The column behind a reading, for asking whether it exists.

    `windvec` is not a column; the speed it is made of is.
    """
    return VECTORS[obs_type][0] if obs_type in VECTORS else obs_type


def _round(values: list, places: int | None) -> list:
    """Round a sequence, leaving the gaps in the data alone."""
    if places is None:
        return list(values)
    return [v if not isinstance(v, float) else round(v, places)
            for v in values]


def _components(magnitudes: list, directions: list | None,
                places: int | None) -> tuple[list, list]:
    """A vector series split into how far east and how far north.

    A chart drawing arrows scales and offsets the components; handing them
    over saves rebuilding them from magnitude and bearing at the far end, and
    saves getting the sign of the rotation wrong while doing it.
    """
    import math

    east: list[Any] = []
    north: list[Any] = []
    for i, magnitude in enumerate(magnitudes):
        direction = directions[i] if directions and i < len(directions) else None
        if magnitude is None or direction is None:
            east.append(None if magnitude is None else 0.0)
            north.append(None if magnitude is None else 0.0)
            continue
        angle = math.radians(90.0 - direction)
        east.append(magnitude * math.cos(angle))
        north.append(magnitude * math.sin(angle))
    return _round(east, places), _round(north, places)


def _drop_empty(entry: dict[str, Any], gap_fraction: float | None,
                span: float, aggregated: bool = False) -> None:
    """Leave out the points that carry nothing, keeping real gaps visible.

    A sensor reporting every ten minutes fills one archive record in ten, and
    the rest hold null for it. Sent as they are, a client draws a line broken
    in hundreds of places and the file is far larger than the data in it.

    What counts as a gap comes from the readings' own rhythm rather than the
    width of the chart. `gap_fraction` still wins where a plot sets it, for
    anyone who wants the ImageGenerator's fixed threshold.
    """
    times, values = entry["time"], entry["values"]
    if len(times) != len(values):
        return
    kept = [i for i, v in enumerate(values) if v is not None]
    if not kept or len(kept) == len(values):
        return

    threshold = None
    if gap_fraction and span and not aggregated:
        # WeeWX's own measure, and it belongs only to a series of raw
        # readings. On an aggregated one the bucket *is* the spacing, so a
        # threshold of a twentieth of the span marks every daily bar on a week
        # chart as a break in the data.
        threshold = float(gap_fraction) * float(span)
    if threshold is None and len(kept) >= 3:
        spacings = sorted(times[b] - times[a] for a, b in zip(kept, kept[1:]))
        usual = spacings[len(spacings) // 2]
        if usual > 0:
            threshold = GAP_FACTOR * usual

    keep: list[int] = []
    for position, i in enumerate(kept):
        if position and threshold is not None:
            previous = kept[position - 1]
            middle = previous + (i - previous) // 2
            # `middle` is only a real point between the two when they are not
            # already neighbours. Without this it lands back on `previous`,
            # and the series comes out with every timestamp twice.
            if times[i] - times[previous] >= threshold and middle > previous:
                # Long enough to be a break in the readings rather than their
                # rhythm. One null says so; the rest of the run is noise.
                keep.append(middle)
        keep.append(i)

    if len(keep) == len(values):
        return
    entry["time"] = [times[i] for i in keep]
    entry["values"] = [values[i] for i in keep]
    for extra in ("directions", "bar_width", "vector_x", "vector_y"):
        sequence = entry.get(extra)
        if isinstance(sequence, list) and len(sequence) == len(values):
            entry[extra] = [sequence[i] for i in keep]


def from_settings(settings: Any, reader: Reader, plots: PlotSet,
                  extra_groups: dict[str, str] | None = None) -> JSONGenerator:
    """Build the generator from the configuration."""
    stored = units.system_from(settings.get("station.units") or units.US)
    indent = int(settings.get("feeds.json.indent") or 0)

    # A group named on its own wins over the system. Somebody wanting Celsius
    # and inches of mercury on one page is not confused; that is what their
    # readers expect.
    overrides = {}
    for group in ("group_temperature", "group_pressure", "group_rain",
                  "group_speed", "group_altitude", "group_distance"):
        chosen = (settings.get(f"feeds.json.unit.{group}") or "").strip()
        if chosen:
            overrides[group] = chosen
    try:
        target = units.Target(settings.get("feeds.json.units") or "METRICWX",
                              overrides)
    except ValueError as exc:
        # A unit a group cannot be shown in. Named, and then ignored, rather
        # than stopping a station from producing anything at all.
        log.error("%s -- the overrides are being ignored", exc)
        target = units.Target(settings.get("feeds.json.units") or "METRICWX")

    spans = tuple(s.strip() for s
                  in str(settings.get("feeds.json.spans") or "").split(",")
                  if s.strip())

    return JSONGenerator(
        reader=reader,
        plots=plots,
        target=target,
        latitude=_number(settings.get("station.latitude")),
        longitude=_number(settings.get("station.longitude")),
        unit_system=stored,
        extra_groups=extra_groups,
        rounding=int(settings.get("feeds.json.rounding") or ROUNDING),
        indent=indent or None,
        spans=spans,
        manifest=_truth(settings.get("feeds.json.manifest"), True),
        twilight=_truth(settings.get("feeds.json.twilight"), True),
        rewrite_unchanged=_truth(
            settings.get("feeds.json.rewrite_unchanged"), False),
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

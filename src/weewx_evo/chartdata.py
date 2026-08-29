"""One plot's data, ready to draw. The layer under every chart renderer.

A `Plot` from `plots.toml` says which readings, over how long, aggregated how.
Turning that into numbers means asking `series.py`, converting into what the
page shows, deciding what counts as a gap and what counts as a sensor this
station has never had. None of that is drawing.

So it lives here, and the renderers are customers:

    chartdata.build(plot, ...)  ->  Chart
      jsongenerator             writes it as JSON
      imagegenerator            draws it as a PNG

That is the whole reason this module exists. WeeWX has the same arithmetic in
`ImageGenerator` and again in whatever writes JSON, and the two disagree in
the third decimal place -- which is a bug nobody finds, because each of them
is right on its own. Here there is one answer and two ways of showing it.

A `Chart` is deliberately plain: lists of numbers, a unit, a colour. It is
close to the JSON document because that document is the honest shape of the
data, not because JSON is privileged.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from . import sun, units
from .plots import Plot
from .series import VECTORS, Reader, Series

log = logging.getLogger(__name__)

#: How many decimals. Three is well past any weather sensor's resolution and
#: takes about a third off the size of a JSON file.
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


@dataclass
class Line:
    """One reading, fetched and converted. What a renderer draws."""

    obs_type: str
    label: str = ""
    plot_type: str = "line"
    color: str = ""
    fill_color: str = ""
    unit: str | None = None
    time: list[int] = field(default_factory=list)
    values: list[Any] = field(default_factory=list)
    #: Compass degrees, for the wind vectors. None for everything else.
    directions: list[Any] | None = None
    #: How wide each bar is, in seconds. A month of daily bars is not a month
    #: of equal ones: the change to summer time makes one of them shorter.
    bar_width: list[int] | None = None
    #: A vector series split into how far east and how far north.
    vector_x: list[Any] | None = None
    vector_y: list[Any] | None = None
    #: How far to turn the arrows, in degrees, positive anticlockwise. A
    #: skin sets it so that a chart reads with north up the page even where
    #: the plot is drawn sideways.
    vector_rotate: float | None = None
    aggregate_type: str = ""
    aggregate_interval: Any = None
    marker: str = ""
    marker_size: int | None = None
    width: float | None = None
    #: The earliest and latest moment this line covers, buckets included.
    reach: tuple[int, int] | None = None
    #: Which archive it came from, where a chart draws more than one. Empty
    #: for every line of every single-series station, so nothing downstream
    #: has to learn about archives to keep working.
    series: str = ""

    @property
    def empty(self) -> bool:
        return not any(v is not None for v in self.values)


@dataclass
class Chart:
    """One plot, with its data. What both renderers are handed."""

    name: str
    #: What was asked for, and what the data actually covers. They differ
    #: because a bucket is drawn as the whole of what it covers: the last bar
    #: of a daily chart runs to tomorrow's midnight, after the moment the
    #: file was written.
    asked: tuple[int, int] = (0, 0)
    start: int = 0
    stop: int = 0
    #: One axis, so one unit. The first line that has one decides.
    unit: str = ""
    unit_label: str = ""
    title: str = ""
    lines: list[Line] = field(default_factory=list)
    yscale: list[Any] = field(default_factory=lambda: [None, None, None])
    #: Sunrise, sunset and twilight over the span, for shading the night.
    daynight: dict[str, Any] | None = None

    @property
    def empty(self) -> bool:
        return all(line.empty for line in self.lines)


def build(plot: Plot, reader: Reader, generated: float,
          target: units.Target | None = None,
          unit_system: int = units.US,
          extra_groups: dict[str, str] | None = None,
          labels: dict[str, str] | None = None,
          rounding: int | None = ROUNDING,
          latitude: float | None = None, longitude: float | None = None,
          twilight: bool = True,
          readers: dict[str, Reader] | None = None) -> Chart | None:
    """One plot's data, or None if this station has none of its readings.

    Every line is fetched, converted, and trimmed of the points that carry
    nothing. A plot where every line came back missing is not built at all:
    the shipped set covers sensors most stations do not have, and a hundred
    charts of nulls help nobody.

    `readers` is how a chart draws more than one place: archive name to a
    reader for it, and a line naming one is read from there. A line naming
    an archive that is not in the map is *left out* rather than read from
    the default -- silently drawing the wrong location's temperature under
    another location's label is the one outcome worse than an empty chart.
    """
    target = target or units.Target(unit_system)
    labels = dict(labels or {})
    stop = int(generated)
    start = stop - int(plot.time_length)

    readers = readers or {}
    lines: list[Line] = []
    covered_from, covered_to = start, stop
    for definition in plot.drawn:
        wanted = getattr(definition, "series", "") or ""
        source = reader
        if wanted:
            source = readers.get(wanted)
            if source is None:
                log.warning("plot %r line %r asks for series %r, which is not "
                            "configured; left out", plot.name,
                            definition.obs, wanted)
                continue
        line = _line(definition, source, start, stop, target, unit_system,
                     extra_groups or {}, labels, rounding, plot.skip_if_empty)
        if line is None:
            continue
        line.series = wanted
        if line.reach:
            covered_from = min(covered_from, line.reach[0])
            covered_to = max(covered_to, line.reach[1])
        lines.append(line)

    if not lines:
        return None

    # One axis, so one unit. WeeWX refuses outright to draw two units
    # together; this reports the first and leaves the rest on the lines, so
    # whoever draws it can at least see the disagreement.
    unit = next((line.unit for line in lines if line.unit), "") or ""

    chart = Chart(
        name=plot.name,
        asked=(start, stop),
        start=int(covered_from),
        stop=int(covered_to),
        unit=unit,
        unit_label=units.label(unit).strip(),
        title=plot.title,
        lines=lines,
        yscale=list(plot.yscale),
    )

    if plot.show_daynight:
        try:
            bands = sun.day_night(start, stop, latitude, longitude)
            if bands:
                if not twilight:
                    bands.pop("twilight", None)
                chart.daynight = bands
        except Exception as exc:
            # Shading is decorative and must never break a report. But a
            # silent failure here once hid a real bug, so say something.
            log.warning("could not work out day and night for %r: %s",
                        plot.name, exc)
    return chart


def _line(definition: Any, reader: Reader, start: int, stop: int,
          target: units.Target, unit_system: int,
          extra_groups: dict[str, str], labels: dict[str, str],
          rounding: int | None, skip_if_empty: str) -> Line | None:
    """One reading, fetched and made ready to draw.

    None where this station does not have the sensor at all. A sensor it does
    have but which reported nothing over this span comes back as a line with
    no points: the chart keeps its layout, and the gap is visible as a gap
    rather than as a chart that quietly disappeared.
    """
    series = reader.series(definition.obs, start, stop,
                           aggregate=definition.aggregate or None,
                           interval=definition.interval)
    if not len(series) or series.empty:
        if not _exists(reader, definition.obs, stop, skip_if_empty):
            return None
        series = Series(obs_type=definition.obs,
                        aggregate=definition.aggregate or None,
                        interval=definition.interval,
                        directions=[] if series.directions is not None
                        else None)

    values, unit, _group = target.convert(
        series.values, definition.obs, unit_system,
        aggregate=definition.aggregate or None, extra=extra_groups)

    line = Line(
        obs_type=definition.obs,
        # The plot's own name, then the skin's, then what the core calls the
        # reading in the language the page is written in. Never nothing: a
        # chart published as a file has to say what is in it, because the
        # thing drawing it has no other source. The image generator already
        # ended on `obs_label`; the JSON did not, so every series in every
        # published file came out unnamed and a page built from them showed
        # "outTemp".
        label=(definition.label or labels.get(definition.obs, "")
               or units.obs_label(definition.obs,
                                  getattr(target, "language", None))),
        plot_type=definition.kind,
        color=definition.color,
        fill_color=definition.fill_color,
        unit=unit,
        time=[int(t) for t in series.time],
        values=round_all(values, rounding),
        aggregate_type=definition.aggregate or "",
        aggregate_interval=definition.interval,
        marker=definition.marker,
        marker_size=definition.marker_size,
        width=definition.width,
    )
    if series.directions is not None:
        # One decimal is already finer than any wind vane.
        line.directions = round_all(series.directions, 1)
    if definition.kind == "bar":
        line.bar_width = [int(b - a) for a, b
                          in zip(series.start, series.stop, strict=True)]
    if definition.kind == "vector":
        line.vector_x, line.vector_y = components(
            line.values, line.directions, rounding)
        if definition.rotate is not None:
            # As the plot defines it, positive anticlockwise, which is what
            # WeeWX's `vector_rotate` means. Not negated: the negation
            # belongs to the JSON document, whose readers draw in screen
            # coordinates where y grows downwards, and burying it here made
            # every arrow on a rotated chart point the opposite way.
            line.vector_rotate = float(definition.rotate)

    drop_empty(line, definition.gap_fraction, stop - start,
               aggregated=bool(definition.aggregate))
    if series.start and series.stop:
        line.reach = (int(min(series.start)), int(max(series.stop)))
    return line


def _exists(reader: Reader, obs_type: str, stop: int,
            skip_if_empty: str) -> bool:
    """Whether this station has this sensor at all.

    The difference between a reading that is missing today and one that has
    never existed. WeeWX's `skip_if_empty = year` says exactly this, and it is
    why the shipped Seasons plot set does not litter a two-sensor station with
    ninety files of nulls.
    """
    if not skip_if_empty:
        return True
    length = SPAN_LENGTHS.get(skip_if_empty)
    if length is None:
        # `plot`, or anything unrecognised: the plot's own span, which is the
        # one just looked at and found empty.
        return False
    try:
        return bool(reader.aggregate(column_of(obs_type), stop - length, stop,
                                     "not_null"))
    except Exception:
        return True


def column_of(obs_type: str) -> str:
    """The column behind a reading, for asking whether it exists.

    `windvec` is not a column; the speed it is made of is.
    """
    return VECTORS[obs_type][0] if obs_type in VECTORS else obs_type


def round_all(values: list, places: int | None) -> list:
    """Round a sequence, leaving the gaps in the data alone."""
    if places is None:
        return list(values)
    return [v if not isinstance(v, float) else round(v, places)
            for v in values]


def components(magnitudes: list, directions: list | None,
               places: int | None) -> tuple[list, list]:
    """A vector series split into how far east and how far north.

    A chart drawing arrows scales and offsets the components; working them out
    once here saves rebuilding them from magnitude and bearing at the far end,
    and saves getting the sign of the rotation wrong while doing it.
    """
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
    return round_all(east, places), round_all(north, places)


def drop_empty(line: Line, gap_fraction: float | None, span: float,
               aggregated: bool = False) -> None:
    """Leave out the points that carry nothing, keeping real gaps visible.

    A sensor reporting every ten minutes fills one archive record in ten, and
    the rest hold null for it. Drawn as they are, the line is broken in
    hundreds of places and a JSON file is far larger than the data in it.

    What counts as a gap comes from the readings' own rhythm rather than the
    width of the chart. `gap_fraction` still wins where a plot sets it, for
    anyone who wants the ImageGenerator's fixed threshold.
    """
    times, values = line.time, line.values
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
        spacings = sorted(times[b] - times[a] for a, b in pairwise(kept))
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
    line.time = [times[i] for i in keep]
    line.values = [values[i] for i in keep]
    for name in ("directions", "bar_width", "vector_x", "vector_y"):
        sequence = getattr(line, name)
        if isinstance(sequence, list) and len(sequence) == len(values):
            setattr(line, name, [sequence[i] for i in keep])

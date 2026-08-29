"""Charts as PNG files.

The reason this exists rather than only the JSON feed: a picture can be
pasted into a forum post, mailed, or put in a page by a skin that has been
doing exactly that for eight years. `<img src="daytempdew.png">` works
everywhere and needs nothing running.

What it draws comes from `plots.toml`, and the numbers come from
`chartdata.py` -- the same module the JSON feed reads. That is deliberate:
WeeWX works the same arithmetic out twice, once in its ImageGenerator and
once in whatever writes JSON, and the two disagree in the third decimal
place. Here there is one answer.

It does not look like WeeWX's. A boxed grey chart with a hard border is what
2009 looked like. This draws on white with a hairline grid, no frame, and the
area under a line fading out, so the data is the only thing with contrast.

**Pillow.** The one dependency, and only this feed has it. It is imported
where it is used, so a station drawing no pictures never loads it, and a
station without it gets a message saying which package to install rather
than a stack trace.

**Twice the pixels.** A chart is written at `scale` times its stated size and
a page shows it at the stated size. On a phone or any modern laptop that is
the difference between a crisp chart and a smeared one, and it costs about
three times the bytes of a file nobody can read anyway. A skin that sizes its
images in CSS -- Seasons does -- gets this for free.
"""

from __future__ import annotations

import logging
import math
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

from ... import chartdata, units
from ... import language as language_module
from ...options import Group, Option
from ...plots import PlotSet
from ...series import Reader
from .. import Produced
from . import canvas as drawing
from . import theme as theming

log = logging.getLogger(__name__)

#: What a chart is, in logical pixels, before `scale`. WeeWX's Seasons uses
#: 500x180 and its stylesheet is written for it, so a skin brought over
#: unchanged lines up without anybody measuring anything.
WIDTH = 500
HEIGHT = 180

#: How many actual pixels per logical one.
SCALE = 2


class ImageGenerator:
    """Turns plot definitions into PNG files."""

    #: A new archive record means new data. Everything a chart draws comes
    #: out of the archive, so there is nothing to redo in between.
    trigger = "record"

    def __init__(self, reader: Reader, plots: PlotSet,
                 target: units.Target | None = None,
                 latitude: float | None = None,
                 longitude: float | None = None,
                 unit_system: int = units.US,
                 extra_groups: dict[str, str] | None = None,
                 labels: dict[str, str] | None = None,
                 width: int = WIDTH, height: int = HEIGHT,
                 scale: int = SCALE,
                 look: theming.Theme | None = None,
                 spans: tuple[str, ...] = (),
                 titles: bool = True, twilight: bool = True,
                 rose_label: str = "",
                 language: Any = None,
                 archives: dict | None = None) -> None:
        self.reader = reader
        self.plots = plots
        self.target = target or units.Target(unit_system)
        self.latitude = latitude
        self.longitude = longitude
        #: What the archive holds. Not what to show: see `target`.
        self.unit_system = unit_system
        self.extra_groups = dict(extra_groups or {})
        self.labels = dict(labels if labels is not None
                           else getattr(plots, "labels", {}) or {})
        self.width = int(width)
        self.height = int(height)
        self.scale = max(1, int(scale))
        self.look = look or theming.Theme()
        #: Which groups to draw. Empty means all of them.
        self.spans = tuple(spans)
        #: Whether a chart says what it is. The heading and the legend are
        #: one line, so this is both.
        self.titles = titles
        self.twilight = twilight
        #: What language the chart is written in. A chart is read by
        #: somebody even where no skin is involved.
        self.language = language
        #: The letter in the middle of the compass rose. North is not N in
        #: every language.
        self.rose_label = str(
            rose_label
            or (language.compass()[0] if language is not None else "N"))
        self.written = 0
        self.skipped = 0
        self.failed: list[tuple[str, str]] = []
        #: The other archives, by name, for a plot that draws more than one
        #: place. Paths rather than readers: a connection held across the
        #: feed's whole life is a descriptor kept for the 99% of the time
        #: nothing is being drawn.
        self.archives = dict(archives or {})
        #: Open only while `produce` runs.
        self._readers: dict = {}

    # -- the feed ---------------------------------------------------------

    def produce(self, into: Path, now: float | None = None) -> Produced:
        """Draw every chart. The other series are opened for this run only."""
        from ... import series as series_module
        from ...plots import series_named

        with series_module.opened(self.archives,
                                  series_named(self.plots)) as readers:
            self._readers = readers
            try:
                return self._produce(into, now)
            finally:
                self._readers = {}

    def _produce(self, into: Path, now: float | None = None) -> Produced:
        started = time.time()
        into = Path(into)
        into.mkdir(parents=True, exist_ok=True)
        self.written = self.skipped = 0
        self.failed = []

        try:
            import PIL  # noqa: F401
        except ImportError:
            note = ("Pillow is not installed, so no charts were drawn. "
                    "Install it with: pip install Pillow")
            log.error("%s", note)
            return Produced(directory=into, note=note)

        generated = float(now if now is not None else time.time())
        files: list[Path] = []
        for plot in self.plots:
            if self.spans and plot.span not in self.spans:
                continue
            try:
                image = self.build(plot, generated)
            except Exception as exc:
                # One broken chart must not cost the other ninety-nine. A
                # station with a sensor that stopped reporting should still
                # get its temperature chart.
                log.exception("could not draw %r", plot.name)
                self.failed.append((plot.name, f"{type(exc).__name__}: {exc}"))
                continue
            if image is None:
                self.skipped += 1
                continue

            path = into / f"{plot.name}.png"
            try:
                partial = path.with_name(path.name + ".part")
                image.save(partial, "PNG", optimize=True)
                partial.replace(path)
            except OSError as exc:
                log.error("could not write %s: %s", path, exc)
                self.failed.append((plot.name, str(exc)))
                continue
            files.append(path)
            self.written += 1

        note = (f"{self.written} chart(s) in "
                f"{time.time() - started:.2f}s"
                + (f", {self.skipped} with no data" if self.skipped else "")
                + (f", {len(self.failed)} failed" if self.failed else ""))
        log.info("%s", note)
        return Produced(directory=into, files=files, note=note)

    def build(self, plot: Any, generated: float) -> Any:
        """One chart as an image, or None if there is nothing in it."""
        chart = chartdata.build(
            plot, self.reader, generated, target=self.target,
            unit_system=self.unit_system, extra_groups=self.extra_groups,
            labels=self.labels, latitude=self.latitude,
            longitude=self.longitude, twilight=self.twilight,
            readers=self._readers)
        if chart is None or chart.empty:
            return None
        return self.draw(chart)

    # -- drawing ----------------------------------------------------------

    def draw(self, chart: chartdata.Chart) -> Any:
        look = theming.resolve(self.look).scaled(self.scale)
        width = self.width * self.scale
        height = self.height * self.scale
        sheet = drawing.Canvas(width, height, look)

        heading = self._heading(chart)
        box = drawing.Box(
            left=look.pad_left,
            top=look.pad_top + (look.heading_height if heading else 0),
            right=width - look.pad_right,
            bottom=height - look.pad_bottom)
        if box.width <= 0 or box.height <= 0:
            return None

        low, high = self._range(chart)
        ticks = drawing.nice_ticks(low, high, look.y_ticks)
        if len(ticks) > 1:
            # The axis is stretched to the outermost gridline, so the top one
            # is not drawn on the very edge with half of it cut off.
            low = min(low, ticks[0])
            high = max(high, ticks[-1])

        self._shade_night(sheet, chart, box, look)
        self._grid(sheet, chart, box, look, ticks, low, high)

        for line in chart.lines:
            if not line.time:
                continue
            try:
                self._draw_line(sheet, line, chart, box, low, high, look)
            except Exception:
                log.exception("could not draw %s in %s", line.obs_type,
                              chart.name)

        # The bottom rule, over the data: a line drawn to the axis should
        # stop at it rather than at a paler version of it.
        sheet.rectangle(box.left, box.bottom, box.right,
                        box.bottom + max(1.0, self.scale * 0.5), look.axis)

        if heading:
            self._draw_heading(sheet, heading, box, look)
        if chart.unit_label:
            sheet.text(width - look.pad_right, look.pad_top * 0.7,
                       chart.unit_label, look.faint_text, look.unit_size, "rt")
        return sheet.finish()

    def _heading(self, chart: chartdata.Chart) -> list[tuple[str, str]]:
        """What the chart says it is: a name and a colour for each line.

        Heading and legend are the same thing, which is why there is one of
        them. A chart of two readings is headed by their two names in their
        two colours, and a reader has both the title and the key in one
        line -- which is what WeeWX's `top_label` always was.

        A plot with a title of its own overrides the lot: "Rain (hourly
        total)" says more than "Rain" twice.
        """
        if not self.titles:
            return []
        if chart.title:
            return [(chart.title, "")]
        out: list[tuple[str, str]] = []
        for i, line in enumerate(chart.lines):
            if not line.time:
                continue
            # The reading's own name where the plot did not give one. WeeWX
            # falls back to `[Labels] [[Generic]]`; without something here a
            # page of thirty charts has thirty blank headings, which is what
            # it looked like.
            said = line.label or units.obs_label(line.obs_type,
                                                 self.language)
            if said and said not in [name for name, _c in out]:
                out.append((said, line.color or self.look.color(i)))
        return out

    def _draw_heading(self, sheet: drawing.Canvas,
                      heading: list[tuple[str, str]], box: drawing.Box,
                      look: theming.Theme) -> None:
        y = look.pad_top + look.heading_height * 0.4
        x = box.left
        swatch = look.title_size * 0.75
        for said, color in heading:
            if color:
                sheet.rectangle(x, y - swatch * 0.2, x + swatch,
                                y + swatch * 0.2, color)
                x += swatch * 1.45
            sheet.text(x, y, said, look.title_text, look.title_size, "lm",
                       bold=True)
            x += sheet.measure(said, look.title_size, bold=True)[0]
            x += swatch * 1.6
            if x > box.right:
                # Out of room. The rest are on the chart in their own
                # colours, which is more use than a heading running off it.
                break

    def _range(self, chart: chartdata.Chart) -> tuple[float, float]:
        """What the value axis covers.

        The data, then whatever the plot fixed. A fixed axis is how two
        charts of different things stay comparable, so it wins outright.
        """
        values = [v for line in chart.lines for v in line.values
                  if v is not None]
        # Arrows hang from a zero line, and that line has to be in the
        # middle: an axis running 0 to 6 puts every arrow on the floor with
        # the southerly half of them drawn off the bottom of the chart.
        if any(line.plot_type == "vector" for line in chart.lines):
            biggest = max((abs(v) for v in values), default=1.0) or 1.0
            return -biggest * 1.15, biggest * 1.15
        # A bar chart starts at zero. A bar that starts at 4.2 is a lie about
        # its own length, and rainfall is the usual case.
        if any(line.plot_type == "bar" for line in chart.lines):
            values.append(0.0)
        if not values:
            low, high = 0.0, 1.0
        else:
            low, high = min(values), max(values)
        if high - low < 1e-9:
            # A flat line still needs an axis to sit in the middle of.
            low, high = low - 0.5, high + 0.5
        else:
            margin = (high - low) * 0.06
            low, high = low - margin, high + margin

        fixed = [*list(chart.yscale), None, None, None]
        if fixed[0] is not None:
            low = float(fixed[0])
        if fixed[1] is not None:
            high = float(fixed[1])
        return (low, high) if high > low else (low, low + 1.0)

    def _grid(self, sheet: drawing.Canvas, chart: chartdata.Chart,
              box: drawing.Box, look: theming.Theme, ticks: list[float],
              low: float, high: float) -> None:
        step = (ticks[1] - ticks[0]) if len(ticks) > 1 else (high - low)
        hairline = max(1.0, self.scale * 0.5)
        for value in ticks:
            y = self._y(value, box, low, high)
            sheet.rectangle(box.left, y, box.right, y + hairline, look.grid)
            sheet.text(box.left - look.font_size * 0.5, y,
                       drawing.label_for(value, step),
                       look.faint_text, look.font_size, "rm")

        for when, said in drawing.time_ticks(chart.start, chart.stop,
                                             language=self.language):
            if not (chart.start <= when <= chart.stop):
                continue
            x = self._x(when, box, chart)
            sheet.rectangle(x, box.top, x + hairline, box.bottom,
                            look.grid, 0.6)
            sheet.text(x, box.bottom + look.font_size * 0.4, said,
                       look.faint_text, look.font_size, "mt")

    def _shade_night(self, sheet: drawing.Canvas, chart: chartdata.Chart,
                     box: drawing.Box, look: theming.Theme) -> None:
        """Shade the hours of darkness, and soften the two edges.

        `sun.day_night` gives which side of the horizon the span starts on
        and every crossing inside it, not a list of night bands -- a
        crossing is a fact and a band is a way of drawing one. Turning the
        one into the other is this renderer's job.

        The edges are not edges. Night painted as a rectangle stops dead at
        sunrise, and a chart of a day is mostly showing the half hour either
        side of that. So the twilight the almanac worked out is washed back
        to the page across its own real length, which is a minute in the
        tropics and an hour in Norway, and neither is a fixed number of
        pixels.
        """
        if not chart.daynight:
            return

        state = chart.daynight.get("first")
        edges = ([chart.start, *list(chart.daynight.get("transitions") or ()), chart.stop])
        for begin, end in pairwise(edges):
            if state == "night":
                self._band(sheet, chart, box, begin, end, look.night)
            state = "day" if state == "night" else "night"

        for band in chart.daynight.get("twilight") or ():
            # Dawn runs from the start of civil twilight to sunrise, getting
            # lighter, so the page colour comes in from the right. Dusk is
            # the other way round.
            self._fade(sheet, chart, box, band.get("from"), band.get("to"),
                       look.background,
                       towards_right=band.get("dir") != "dusk")

    def _band(self, sheet: drawing.Canvas, chart: chartdata.Chart,
              box: drawing.Box, begin: Any, end: Any, color: str) -> None:
        span = self._within(chart, begin, end)
        if span is None:
            return
        sheet.rectangle(self._x(span[0], box, chart), box.top,
                        self._x(span[1], box, chart), box.bottom, color)

    def _fade(self, sheet: drawing.Canvas, chart: chartdata.Chart,
              box: drawing.Box, begin: Any, end: Any, color: str,
              towards_right: bool) -> None:
        span = self._within(chart, begin, end)
        if span is None:
            return
        sheet.fade_across(self._x(span[0], box, chart), box.top,
                          self._x(span[1], box, chart), box.bottom,
                          color, towards_right)

    @staticmethod
    def _within(chart: chartdata.Chart, begin: Any,
                end: Any) -> tuple[float, float] | None:
        """A stretch of time clipped to the chart, or None if it misses it."""
        try:
            begin = max(float(begin), chart.start)
            end = min(float(end), chart.stop)
        except (TypeError, ValueError):
            return None
        return (begin, end) if end > begin else None

    def _draw_line(self, sheet: drawing.Canvas, line: chartdata.Line,
                   chart: chartdata.Chart, box: drawing.Box,
                   low: float, high: float, look: theming.Theme) -> None:
        color = line.color or look.color(chart.lines.index(line))
        if line.plot_type == "bar":
            self._draw_bars(sheet, line, chart, box, low, high, look, color)
            return
        if line.plot_type == "vector":
            self._draw_vectors(sheet, line, chart, box, low, high, look, color)
            return

        width = (line.width * self.scale) if line.width else look.line_width
        # Each run of readings between gaps is its own stroke. Joining across
        # a gap draws a straight line through the hours the station was off,
        # which reads as data.
        for run in self._runs(line, chart, box, low, high):
            if look.fill_opacity > 0 and len(run) > 1:
                sheet.fade_under(run, box.bottom, color, look.fill_opacity)
            sheet.line(run, color, width)
            if line.marker:
                radius = ((line.marker_size or 2) * self.scale) / 2.0
                for x, y in run:
                    sheet.dot(x, y, radius, color)

    def _runs(self, line: chartdata.Line, chart: chartdata.Chart,
              box: drawing.Box, low: float,
              high: float) -> list[list[tuple[float, float]]]:
        runs: list[list[tuple[float, float]]] = []
        current: list[tuple[float, float]] = []
        for when, value in zip(line.time, line.values, strict=True):
            if value is None:
                if len(current) > 1:
                    runs.append(current)
                current = []
                continue
            current.append((self._x(when, box, chart),
                            self._y(value, box, low, high)))
        if len(current) > 1:
            runs.append(current)
        elif len(current) == 1:
            # A single reading is still worth a mark. Without this a station
            # that has reported once today draws nothing at all.
            runs.append(current + current)
        return runs

    def _draw_bars(self, sheet: drawing.Canvas, line: chartdata.Line,
                   chart: chartdata.Chart, box: drawing.Box, low: float,
                   high: float, look: theming.Theme, color: str) -> None:
        fill = line.fill_color or color
        baseline = self._y(max(0.0, low), box, low, high)
        for i, (when, value) in enumerate(zip(line.time, line.values, strict=True)):
            if value is None:
                continue
            seconds = (line.bar_width[i]
                       if line.bar_width and i < len(line.bar_width) else 0)
            # A bar covers the bucket that *ends* at its timestamp.
            begin = when - seconds if seconds else when
            x0 = self._x(begin, box, chart)
            x1 = self._x(when, box, chart)
            gap = (x1 - x0) * look.bar_gap / 2.0
            x0, x1 = x0 + gap, x1 - gap
            if x1 - x0 < 1.0:
                # Narrower than a pixel: still drawn, or a year of daily rain
                # comes out blank.
                x1 = x0 + 1.0
            y = self._y(value, box, low, high)
            top, bottom = min(y, baseline), max(y, baseline)
            sheet.rectangle(x0, top, x1, bottom, fill, look.bar_opacity)

    def _draw_vectors(self, sheet: drawing.Canvas, line: chartdata.Line,
                      chart: chartdata.Chart, box: drawing.Box, low: float,
                      high: float, look: theming.Theme, color: str) -> None:
        """Wind as arrows hanging from a zero line.

        The line the arrows start from is where zero is, so a reader can see
        which way the wind blew and how hard in one glance.
        """
        middle = self._y(max(low, min(high, 0.0)), box, low, high)
        sheet.rectangle(box.left, middle, box.right,
                        middle + max(1.0, self.scale * 0.5), look.axis, 0.5)

        if high <= low:
            return
        # Pixels per unit, taken from the value axis, and the same for both
        # directions. From the axis so an arrow reaching the 1 gridline is
        # one metre a second; the same both ways so a north-easterly points
        # north-east instead of being stretched by the width of the chart.
        per_unit = box.height / (high - low)
        rotate = math.radians(line.vector_rotate or 0.0)
        step = max(1, len(line.time) // 48)
        drawn = None

        for i in range(0, len(line.time), step):
            east = line.vector_x[i] if line.vector_x else None
            north = line.vector_y[i] if line.vector_y else None
            if east is None or north is None:
                continue
            x = self._x(line.time[i], box, chart)
            tip = _turned(x, middle, east * per_unit, north * per_unit, rotate)
            sheet.line([(x, middle), tip], color, look.line_width * 0.8)
            self._arrow_head(sheet, (x, middle), tip, color, look)
            drawn = True

        if drawn:
            self._draw_rose(sheet, box, look, color, rotate)

    def _draw_rose(self, sheet: drawing.Canvas, box: drawing.Box,
                   look: theming.Theme, color: str, rotate: float) -> None:
        """A compass rose, so an arrow means something.

        Without it a vector chart is a field of arrows with no key: nothing
        on it says which way is north, and a plot may rotate them -- WeeWX's
        own default turns them ninety degrees. The rose turns with them, so
        the letter always points where north is on that chart.
        """
        size = look.rose_size
        centre_x = box.left + size * 0.75
        centre_y = box.bottom - size * 0.75
        reach = size * 0.5

        # A pure northerly, put through the same turn as every arrow on the
        # chart. Drawn that way rather than rotated on its own so that the
        # two cannot come apart: a rose pointing somewhere the data does not
        # is worse than no rose, because it is believed.
        tip = _turned(centre_x, centre_y, 0.0, reach, rotate)
        tail = (2 * centre_x - tip[0], 2 * centre_y - tip[1])
        sheet.line([tail, tip], color, look.line_width * 0.8, 0.9)
        self._arrow_head(sheet, tail, tip, color, look)
        # The middle is filled with the page before the ring goes on it.
        # WeeWX draws the letter straight over the shaft, and at this size
        # the two are hard to tell apart.
        ring = size * 0.3
        sheet.dot(centre_x, centre_y, ring, look.background)
        sheet.circle(centre_x, centre_y, ring, color, look.line_width * 0.7)
        sheet.text(centre_x, centre_y + look.font_size * 0.05,
                   self.rose_label, look.text,
                   max(6, int(look.font_size * 0.8)), "mm", bold=True)

    def _arrow_head(self, sheet: drawing.Canvas, tail: tuple[float, float],
                    tip: tuple[float, float], color: str,
                    look: theming.Theme) -> None:
        dx, dy = tip[0] - tail[0], tip[1] - tail[1]
        length = math.hypot(dx, dy)
        if length < 1.0:
            return
        size = min(length * 0.4, look.line_width * 2.5)
        angle = math.atan2(dy, dx)
        sheet.polygon([
            tip,
            (tip[0] - size * math.cos(angle - 0.4),
             tip[1] - size * math.sin(angle - 0.4)),
            (tip[0] - size * math.cos(angle + 0.4),
             tip[1] - size * math.sin(angle + 0.4)),
        ], color)

    # -- where a value lands ----------------------------------------------

    def _x(self, when: float, box: drawing.Box,
           chart: chartdata.Chart) -> float:
        span = chart.stop - chart.start
        if span <= 0:
            return box.left
        return box.left + box.width * (when - chart.start) / span

    def _y(self, value: float, box: drawing.Box, low: float,
           high: float) -> float:
        span = high - low
        if span <= 0:
            return box.bottom
        return box.bottom - box.height * (value - low) / span

    # -- what the admin page asks for -------------------------------------

    @staticmethod
    def options() -> list:
        return [
            Group("The picture", "How big, and how sharp.", (
                Option("enabled", "Draw the charts", kind="bool",
                       default=True),
                Option("width", "Width", kind="int", default=WIDTH,
                       minimum=120, maximum=4000, unit="px",
                       help="The size a page shows it at. WeeWX's Seasons "
                            "skin is written for 500, and its stylesheet "
                            "sizes the images itself."),
                Option("height", "Height", kind="int", default=HEIGHT,
                       minimum=80, maximum=3000, unit="px"),
                Option("scale", "Pixels per point", kind="choice",
                       default=str(SCALE),
                       choices=(("1", "1x -- exactly the size above"),
                                ("2", "2x -- sharp on a phone (recommended)"),
                                ("3", "3x")),
                       help="The file is written this many times larger and "
                            "shown at the size above. On any modern display "
                            "that is the difference between a crisp chart "
                            "and a smeared one. A skin that sizes its images "
                            "in CSS gets it without any change."),
            )),
            Group("What is on it", "", (
                Option("titles", "Head each chart with what it shows",
                       kind="bool", default=True,
                       help="The plot's own title, or the names of the "
                            "readings in it, each in its own colour. That "
                            "is the legend as well: a chart of two readings "
                            "is headed by both names in both colours."),
                Option("heading_size", "Heading size", kind="int",
                       default=13, minimum=6, maximum=40, unit="pt",
                       advanced=True,
                       help="At twice the pixels a chart is written at "
                            "twice this. 13 comes out at 26, which is what "
                            "reads on a page that shows the chart at a "
                            "third of its width."),
                Option("twilight", "Shade twilight as well as night",
                       kind="bool", default=True, advanced=True),
                Option("rose_label", "North, on a wind chart", default="N",
                       advanced=True,
                       help="The letter in the compass rose. Wind charts "
                            "draw one so an arrow means something; N is "
                            "north in most languages and not in all."),
                Option("spans", "Only these groups", kind="list",
                       help="One per line: day, week, month, year. Empty "
                            "draws every group there is."),
            )),
            Group("Colours", "", (
                Option("background", "Background", default="#ffffff",
                       help="A page with a dark background wants a chart "
                            "drawn on one."),
                Option("grid", "Gridlines", default="#e9ecef"),
                Option("text", "Labels", default="#495057"),
                Option("night", "Night", default="#eceff3",
                       help="Only on charts that ask for it, and only where "
                            "the station's latitude and longitude are set."),
                Option("fill_opacity", "Fade under a line", kind="float",
                       default=0.16, minimum=0.0, maximum=1.0,
                       help="0 draws the line alone. Much above 0.3 and two "
                            "lines on one chart turn into mud."),
            )),
        ]


def from_settings(settings: Any, reader: Reader, plots: PlotSet,
                  extra_groups: dict[str, str] | None = None,
                  prefix: str = "feeds.images",
                  archives: dict | None = None) -> ImageGenerator:
    """Build the generator from the configuration.

    `prefix` names the configured feed, so two of them can be set up
    differently -- one small and light for a page, one large and dark for a
    forum post -- without either knowing about the other.
    """
    def option(name: str, fallback: Any = None) -> Any:
        found = settings.get(f"{prefix}.{name}")
        return fallback if found is None else found

    # One setting for the whole station: a chart, a skin and the settings
    # page are all read by the same person.
    spoken = language_module.get(settings.get("language"))

    look = theming.Theme(
        background=str(option("background") or "#ffffff"),
        surround=str(option("background") or "#ffffff"),
        grid=str(option("grid") or "#e9ecef"),
        text=str(option("text") or "#495057"),
        night=str(option("night") or "#eceff3"),
        fill_opacity=float(option("fill_opacity", 0.16)),
        title_size=int(option("heading_size", 13)),
    )

    spans = option("spans") or ()
    if isinstance(spans, str):
        spans = [s.strip() for s in spans.replace(",", "\n").splitlines()]

    return ImageGenerator(
        reader=reader,
        plots=plots,
        target=_target(settings, option, spoken),
        latitude=_number(settings.get("station.latitude")),
        longitude=_number(settings.get("station.longitude")),
        unit_system=reader.system,
        extra_groups=extra_groups,
        labels=getattr(plots, "labels", {}),
        width=int(option("width", WIDTH)),
        height=int(option("height", HEIGHT)),
        scale=int(option("scale", SCALE)),
        look=look,
        spans=tuple(s for s in spans if s),
        titles=option("titles") is not False,
        twilight=option("twilight") is not False,
        rose_label=str(option("rose_label") or ""),
        language=spoken,
        archives=archives,
    )


def _target(settings: Any, option: Any, spoken: Any) -> units.Target:
    overrides = {}
    for group in ("group_temperature", "group_pressure", "group_rain",
                  "group_speed", "group_altitude", "group_distance"):
        chosen = str(option(f"unit.{group}") or "").strip()
        if chosen:
            overrides[group] = chosen
    wanted = option("units") or spoken.unit_system or "METRICWX"
    try:
        return units.Target(wanted, overrides, language=spoken)
    except ValueError as exc:
        # A unit a group cannot be shown in. Named, and then ignored, rather
        # than stopping a station from drawing anything at all.
        log.error("%s -- the overrides are being ignored", exc)
        return units.Target(wanted, language=spoken)


def _turned(x: float, y: float, east: float, north: float,
            rotate: float) -> tuple[float, float]:
    """Where an arrow of this much east and this much north ends up.

    In screen pixels, from a point. Two turns of the handle, and both are
    easy to get backwards, so they happen here once:

    - `rotate` is WeeWX's `vector_rotate`, positive anticlockwise, applied
      to the value before anything is drawn. A skin sets it to ninety, and
      with the sign the wrong way round every arrow on the chart points
      exactly opposite to the PNG WeeWX would have drawn.
    - Screen y grows downwards and north does not.
    """
    if rotate:
        east, north = (east * math.cos(rotate) - north * math.sin(rotate),
                       east * math.sin(rotate) + north * math.cos(rotate))
    return x + east, y - north


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

"""Drawing one chart. Axes, grid, lines, bars, arrows, labels.

Pillow draws with hard pixels: a diagonal line comes out as a staircase and
no option turns that off. So the geometry is drawn several times larger and
scaled down, which is what antialiasing is. The *text* is not: it is drawn
afterwards at the final size, because FreeType already renders it smoothly
and scaling smooth text down only blurs it.

That is the whole trick, and it is why this file keeps two images and a list
of labels to draw later rather than one image and a straight sequence of
calls.
"""

from __future__ import annotations

import datetime
import math
import time
from dataclasses import dataclass
from typing import Any

from . import theme as theming

#: How much larger the geometry is drawn before being scaled back. Two is
#: enough for lines this thin; three costs 2.25x the memory for a difference
#: nobody sees.
SUPERSAMPLE = 2

#: Tick steps for a value axis, as the mantissa of a round number. Anything
#: else produces gridlines at 0.7 and 1.4, which are numbers no reader wants.
NICE_STEPS = (1.0, 2.0, 2.5, 5.0, 10.0)

#: Tick steps for a time axis, in seconds, with the one that is not a fixed
#: number of seconds -- months and years -- handled separately.
TIME_STEPS = (
    (300, "%H:%M"), (900, "%H:%M"), (1800, "%H:%M"),
    (3600, "%H:%M"), (2 * 3600, "%H:%M"), (3 * 3600, "%H:%M"),
    (6 * 3600, "%H:%M"), (12 * 3600, "%H:%M"),
    (86400, "%d"), (2 * 86400, "%d"), (7 * 86400, "%d %b"),
)


@dataclass
class Box:
    """The rectangle the data is drawn in, in final pixels."""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


class Canvas:
    """One chart being drawn.

    Coordinates are given in final pixels throughout. Geometry is scaled up
    on the way to the oversampled image; text is kept for the end.
    """

    def __init__(self, width: int, height: int,
                 look: theming.Theme | None = None) -> None:
        from PIL import Image, ImageDraw

        self.width = int(width)
        self.height = int(height)
        self.theme = theming.resolve(look or theming.Theme())
        self.big = Image.new(
            "RGB", (self.width * SUPERSAMPLE, self.height * SUPERSAMPLE),
            theming.rgba(self.theme.background)[:3])
        self.draw = ImageDraw.Draw(self.big, "RGBA")
        #: Text is drawn after the image is scaled back down, so it is kept
        #: here until then: (x, y, text, colour, size, anchor, bold).
        self.labels: list[tuple] = []
        self._fonts: dict[tuple[str, int], Any] = {}

    # -- geometry, on the oversampled image -------------------------------

    def _s(self, value: float) -> float:
        return value * SUPERSAMPLE

    def rectangle(self, x0: float, y0: float, x1: float, y1: float,
                  color: str, opacity: float = 1.0) -> None:
        if x1 <= x0 or y1 <= y0:
            return
        self.draw.rectangle(
            [self._s(x0), self._s(y0), self._s(x1), self._s(y1)],
            fill=theming.rgba(color, opacity))

    def line(self, points: list[tuple[float, float]], color: str,
             width: float, opacity: float = 1.0) -> None:
        if len(points) < 2:
            return
        self.draw.line(
            [(self._s(x), self._s(y)) for x, y in points],
            fill=theming.rgba(color, opacity),
            width=max(1, int(round(self._s(width)))), joint="curve")

    def polygon(self, points: list[tuple[float, float]], color: str,
                opacity: float = 1.0) -> None:
        if len(points) < 3:
            return
        self.draw.polygon([(self._s(x), self._s(y)) for x, y in points],
                          fill=theming.rgba(color, opacity))

    def dot(self, x: float, y: float, radius: float, color: str,
            opacity: float = 1.0) -> None:
        r = self._s(radius)
        self.draw.ellipse([self._s(x) - r, self._s(y) - r,
                           self._s(x) + r, self._s(y) + r],
                          fill=theming.rgba(color, opacity))

    def fade_under(self, points: list[tuple[float, float]], baseline: float,
                   color: str, opacity: float) -> None:
        """The area under a line, fading out towards the bottom.

        A flat wash of colour under every line turns a two-line chart into
        mud. Fading it means the line itself stays the darkest thing on the
        chart, which is where a reader's eye should go.

        Drawn as horizontal slices rather than with a gradient image: the
        shape is bounded by the data, so it has to be clipped to it anyway,
        and slicing does both at once.
        """
        if len(points) < 2 or opacity <= 0:
            return
        top = min(y for _x, y in points)
        depth = baseline - top
        if depth <= 0:
            return

        from PIL import Image, ImageChops, ImageDraw

        # Only the rectangle the fill actually covers. Building it at the
        # size of the whole chart was the single slowest thing here: a
        # hundred charts spent most of a minute multiplying transparent
        # pixels by other transparent pixels.
        x0 = math.floor(self._s(min(x for x, _y in points)))
        x1 = math.ceil(self._s(max(x for x, _y in points)))
        y0 = math.floor(self._s(top))
        y1 = math.ceil(self._s(baseline))
        w, h = max(1, x1 - x0), max(1, y1 - y0)

        shape = Image.new("L", (w, h), 0)
        ImageDraw.Draw(shape).polygon(
            [(self._s(x) - x0, self._s(y) - y0) for x, y in points]
            + [(self._s(points[-1][0]) - x0, h), (self._s(points[0][0]) - x0, h)],
            fill=255)

        # A single column of the gradient, stretched. Painting it as strips
        # costs one draw call per strip and looks no different.
        column = Image.new("L", (1, h))
        column.putdata([
            int(round(255 * opacity * (1.0 - i / max(1, h - 1)) ** 1.4))
            for i in range(h)])
        self.big.paste(theming.rgba(color)[:3], (x0, y0),
                       ImageChops.multiply(shape, column.resize((w, h))))

    # -- text, kept for the end -------------------------------------------

    def text(self, x: float, y: float, said: str, color: str = "",
             size: int | None = None, anchor: str = "lt",
             bold: bool = False) -> None:
        if not said:
            return
        self.labels.append((x, y, str(said), color or self.theme.text,
                            size or self.theme.font_size, anchor, bold))

    def measure(self, said: str, size: int | None = None,
                bold: bool = False) -> tuple[float, float]:
        """How wide and tall a piece of text will be, in final pixels."""
        font = self._font(size or self.theme.font_size, bold)
        if font is None:
            return len(said) * 6.0, 11.0
        box = font.getbbox(str(said))
        return box[2] - box[0], box[3] - box[1]

    def _font(self, size: int, bold: bool) -> Any:
        key = ("b" if bold else "r", size)
        if key not in self._fonts:
            from PIL import ImageFont

            path = self.theme.bold_path if bold else self.theme.font_path
            try:
                self._fonts[key] = ImageFont.truetype(path, size) if path \
                    else ImageFont.load_default()
            except Exception:  # noqa: BLE001
                self._fonts[key] = ImageFont.load_default()
        return self._fonts[key]

    # -- the finished picture ---------------------------------------------

    def finish(self) -> Any:
        """Scale the geometry down and put the text on top."""
        from PIL import Image, ImageDraw

        image = self.big.resize((self.width, self.height), Image.LANCZOS)
        painter = ImageDraw.Draw(image)
        for x, y, said, color, size, anchor, bold in self.labels:
            painter.text((x, y), said, font=self._font(size, bold),
                         fill=theming.rgba(color)[:3], anchor=anchor)
        return image


# -- working out where things go -------------------------------------------

def nice_ticks(low: float, high: float, wanted: int = 4) -> list[float]:
    """Gridline positions a reader would have chosen.

    Round numbers, and a step out of 1, 2, 2.5 or 5 times a power of ten. The
    count is a wish rather than a promise: five gridlines at 0.7 apart are
    worse than four at 1.
    """
    if not (high > low):
        return [low]
    rough = (high - low) / max(1, wanted)
    power = math.floor(math.log10(rough))
    base = 10.0 ** power
    step = next((m * base for m in NICE_STEPS if m * base >= rough),
                NICE_STEPS[-1] * base)

    first = math.ceil(low / step) * step
    ticks = []
    value = first
    # A float step accumulates: 0.1 added ten times is not 1.0, and the
    # label then reads 0.9999999999999999. Counted from the start instead.
    for i in range(int((high - low) / step) + 2):
        value = first + i * step
        if value > high + step * 1e-6:
            break
        ticks.append(round(value, 10))
    return ticks or [low, high]


def time_ticks(start: float, stop: float,
               wanted: int = 6) -> list[tuple[float, str]]:
    """Where to label the time axis, and what to write there.

    Local time, on round boundaries. A day chart gets whole hours, a year
    chart whole months -- and a month is not a fixed number of seconds, so
    those are stepped through the calendar rather than added.
    """
    span = stop - start
    if span <= 0:
        return []

    rough = span / max(1, wanted)
    for seconds, shape in TIME_STEPS:
        if seconds >= rough:
            return _fixed_ticks(start, stop, seconds, shape)

    # Months and years. Stepped through the calendar, because adding
    # 2592000 seconds twelve times lands in the middle of December.
    months = max(1, int(round(rough / (30 * 86400))))
    if months >= 12:
        return _calendar_ticks(start, stop, years=max(1, months // 12))
    for step in (1, 2, 3, 6):
        if step >= months:
            return _calendar_ticks(start, stop, months=step)
    return _calendar_ticks(start, stop, years=1)


def _fixed_ticks(start: float, stop: float, step: int,
                 shape: str) -> list[tuple[float, str]]:
    out = []
    # Aligned to local midnight rather than to the epoch: a six-hour tick
    # should land on 00, 06, 12, 18 in the reader's own day, and a zone
    # offset by half an hour would otherwise put it at 06:30.
    midnight = _midnight(start)
    first = midnight + math.ceil((start - midnight) / step) * step
    when = first
    while when <= stop:
        out.append((when, time.strftime(shape, time.localtime(when))))
        when += step
    return out


def _calendar_ticks(start: float, stop: float, months: int = 0,
                    years: int = 0) -> list[tuple[float, str]]:
    out = []
    first = datetime.datetime.fromtimestamp(start).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    if years:
        first = first.replace(month=1)
    if first.timestamp() < start:
        first = _step_calendar(first, months, years)
    when = first
    shape = "%Y" if years else "%b"
    while when.timestamp() <= stop:
        out.append((when.timestamp(), when.strftime(shape)))
        when = _step_calendar(when, months, years)
    return out


def _step_calendar(when: datetime.datetime, months: int,
                   years: int) -> datetime.datetime:
    if years:
        return when.replace(year=when.year + years)
    total = when.month - 1 + months
    return when.replace(year=when.year + total // 12, month=total % 12 + 1)


def _midnight(when: float) -> float:
    return datetime.datetime.fromtimestamp(when).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()


def label_for(value: float, step: float) -> str:
    """A tick's number, with only the decimals the step needs.

    A step of 5 wants "15", not "15.0". A step of 0.2 wants "15.2".
    """
    if step >= 1:
        return f"{value:.0f}"
    places = max(0, min(4, int(math.ceil(-math.log10(step)))))
    return f"{value:.{places}f}"

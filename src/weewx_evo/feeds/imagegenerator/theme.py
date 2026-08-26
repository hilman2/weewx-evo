"""What a chart looks like. Colours, spacing, type.

Separate from the drawing because these are the decisions a person has an
opinion about, and none of them should be buried in a loop that computes tick
positions.

The look is deliberately not WeeWX's. WeeWX draws a boxed chart with a grey
background, a hard border and a bitmap-ish label -- it has looked like that
since 2009 and it looks it. What is here instead: white ground, a hairline
grid that stays out of the way, no box, and the area under a line fading out.
The data is the only thing with real contrast.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any

log = logging.getLogger(__name__)

#: Where a TrueType face might be, in the order worth trying. Pillow's own
#: fallback is a bitmap font at one fixed size, which no amount of scaling
#: makes look deliberate -- so it is worth hunting for a real one. DejaVu
#: ships with Pillow's wheels and with nearly every Linux; the rest are for
#: the machines where it does not.
FONT_CANDIDATES = (
    "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
FONT_CANDIDATES_BOLD = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)

#: The line colours, in the order they are handed out. Picked to stay apart
#: for the common kinds of colour blindness: nothing relies on telling red
#: from green, and each pair differs in lightness as well as in hue.
PALETTE = (
    "#d1495b",  # temperature, and the first of anything
    "#2e86ab",  # its companion -- dew point beside temperature
    "#4f9d69",
    "#e08b2a",
    "#7b6cd9",
    "#3aa8a0",
    "#b5486f",
    "#8a8f98",
)


@dataclass
class Theme:
    """Every colour and measurement one chart is drawn with.

    Sizes are in logical pixels. The renderer multiplies them by its scale,
    so a chart drawn at 2x is the same chart, not a chart with thicker lines.
    """

    background: str = "#ffffff"
    #: The area outside the axes. The same as the background: a chart with no
    #: frame around it sits on a page instead of being pasted onto it.
    surround: str = "#ffffff"
    grid: str = "#e9ecef"
    #: The line along the bottom. There is no box: one edge is enough to say
    #: where the data stops.
    axis: str = "#ced4da"
    text: str = "#495057"
    faint_text: str = "#868e96"
    title_text: str = "#212529"
    #: Night, when a chart shades it. Barely there on purpose -- it is
    #: context, not content.
    night: str = "#eceff3"
    twilight: str = "#f4f6f8"

    palette: tuple[str, ...] = PALETTE

    #: Room for the labels. Left is wider because a y label sits there.
    pad_left: int = 42
    pad_right: int = 12
    pad_top: int = 10
    pad_bottom: int = 24
    #: The band at the top holding the heading and the legend. They are one
    #: line: what a chart shows *is* its heading, and writing it twice wastes
    #: the room the data wants.
    heading_height: int = 20

    line_width: float = 1.4
    #: How far the fill under a line fades. 0 draws no fill at all.
    fill_opacity: float = 0.16
    bar_opacity: float = 0.75
    #: A gap between bars, as a fraction of the bar's own width.
    bar_gap: float = 0.15

    #: Sizes in logical points, so a 2x file gets twice these. The numbers
    #: are what the Horizon skin settled on for a 1000-pixel chart: axis 19,
    #: unit 22, heading 26. Smaller than that and a chart shown at a third
    #: of its width -- which is what a page of thumbnails does -- has
    #: labels nobody can read.
    font_size: int = 10
    unit_size: int = 11
    title_size: int = 13
    #: About how many gridlines. The tick chooser lands near this, never on
    #: it exactly: the numbers matter more than the count.
    y_ticks: int = 4

    #: Filled in by `resolve`, so a caller never has to.
    font_path: str = ""
    bold_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def color(self, position: int) -> str:
        return self.palette[position % len(self.palette)]

    def scaled(self, factor: float) -> "Theme":
        """The same theme in a bigger coordinate system.

        Everything with a size grows; nothing with a colour changes. This is
        what makes a 2x image the same picture rather than a picture with
        hairline text on it.
        """
        if factor == 1:
            return self

        def up(value: Any) -> Any:
            return type(value)(round(value * factor)) if isinstance(value, int) \
                else value * factor

        return replace(
            self,
            pad_left=up(self.pad_left), pad_right=up(self.pad_right),
            pad_top=up(self.pad_top), pad_bottom=up(self.pad_bottom),
            heading_height=up(self.heading_height),
            line_width=self.line_width * factor,
            font_size=max(1, int(round(self.font_size * factor))),
            unit_size=max(1, int(round(self.unit_size * factor))),
            title_size=max(1, int(round(self.title_size * factor))),
        )


def resolve(theme: Theme) -> Theme:
    """Find a real typeface, once, and remember where it was.

    Looked up here rather than at every draw: a hundred charts is a hundred
    font loads otherwise, and on a Raspberry Pi that is measurable.
    """
    if theme.font_path or theme.bold_path:
        return theme
    found = replace(theme,
                    font_path=_first_readable(FONT_CANDIDATES),
                    bold_path=_first_readable(FONT_CANDIDATES_BOLD))
    if not found.font_path:
        # Worth saying out loud. Without a typeface Pillow draws every label
        # at one fixed size, so a chart at twice the pixels gets type half
        # the height it should -- which reads as a bad design decision
        # rather than as a missing package, and nothing else reports it.
        log.warning(
            "no TrueType font was found, so the chart labels will be small "
            "and all one size. Install one -- 'apt install fonts-dejavu-core' "
            "on Debian and Ubuntu -- or put one beside the skin.")
    return found


def _first_readable(candidates: tuple[str, ...]) -> str:
    from pathlib import Path

    for name in candidates:
        if "/" not in name and "\\" not in name:
            # A bare name is for Pillow's own search path, which covers the
            # fonts that ship in its wheels. Whether it works can only be
            # found out by asking it.
            try:
                from PIL import ImageFont

                ImageFont.truetype(name, 10)
                return name
            except Exception:  # noqa: BLE001
                continue
        if Path(name).is_file():
            return name
    return ""


def rgba(color: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    """`#rrggbb` and an opacity as the four numbers Pillow wants.

    A short `#rgb` is accepted because skins are full of them, and a name
    Pillow knows is passed through to it.
    """
    text = str(color or "").strip()
    alpha = max(0, min(255, int(round(opacity * 255))))
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        if len(digits) == 8:
            # `#rrggbbaa`. The opacity asked for still applies on top, so a
            # translucent colour under a fill stays translucent.
            r, g, b, a = (int(digits[i:i + 2], 16) for i in (0, 2, 4, 6))
            return r, g, b, int(round(a * opacity))
        if len(digits) == 6:
            r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
            return r, g, b, alpha
    if text:
        try:
            from PIL import ImageColor

            r, g, b = ImageColor.getrgb(text)[:3]
            return r, g, b, alpha
        except Exception:  # noqa: BLE001
            pass
    return 0, 0, 0, alpha

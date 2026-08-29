"""One picture for one sky, for a panel that cannot read our files.

The core names the weather and stops there (`forecast/codes.py`): `symbol()`
answers `partly-cloudy-night`, not a filename. Which file that is belongs to
whoever draws the page, and a mapping in the core would make every other icon
set unusable. Deck holds its half in `includes/forecast-icon.inc`; this is
Grafana's.

The set is Deck's own, which is IBM's Carbon icons under Apache 2.0 -- the
same eighteen files, copied rather than referenced. Grafana runs in its own
container and cannot see into ours, so the pictures have to be somewhere it
can serve them from: `provision()` writes them beside the dashboards, and the
compose file mounts that into Grafana's `public/img`.

**A colour has to go into the file.** Carbon's icons carry no `fill`, so they
inherit one -- which is exactly right where Deck embeds them in its markup
and `var(--accent)` reaches them, and useless here, where Grafana loads each
one through an `<img>` and nothing of ours is in scope. An icon left as it
comes is black: invisible on Grafana's dark theme, which is the default, on a
panel that renders perfectly and tests green. That fault has been paid for
once already, in Deck's forecast section.

So the colour is written in, and it is written in **by meaning**: sun amber,
rain blue, snow pale, thunder violet. Two things at once -- a forecast row
readable at a glance, and a set of mid-tone saturated colours that hold on
both of Grafana's grounds, which a single neutral cannot do.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..forecast import codes

log = logging.getLogger(__name__)

#: Where the icons are copied from. Deck's set, because it is here and it is
#: good; the licence travels with it in the skin's own README.
SOURCE = (Path(__file__).resolve().parent.parent / "skins" / "deck"
          / "includes" / "icons")

#: Symbol to file, Deck's mapping exactly. Kept as a table rather than
#: computed from the name: several symbols share a picture on purpose
#: (`rain` and `heavy-rain` are one drawing), and a rule that derived the
#: file from the symbol would need those exceptions written out anyway.
FILES: dict[str, str] = {
    "clear": "forecast/CL.svg",
    "clear-night": "moon.svg",
    "mostly-clear": "forecast/FW.svg",
    "mostly-clear-night": "forecast/B1.svg",
    "partly-cloudy": "forecast/SC.svg",
    "partly-cloudy-night": "forecast/B2.svg",
    "overcast": "forecast/OV.svg",
    "fog": "forecast/fog.svg",
    "drizzle": "forecast/rain-drop.svg",
    "freezing-drizzle": "forecast/sleet.svg",
    "freezing-rain": "forecast/sleet.svg",
    "rain": "forecast/rain.svg",
    "heavy-rain": "forecast/rain.svg",
    "showers": "forecast/rain--scattered.svg",
    "heavy-showers": "forecast/rain--scattered.svg",
    "snow": "forecast/snow.svg",
    "heavy-snow": "forecast/snow.svg",
    "snow-showers": "forecast/snow--scattered.svg",
    "thunderstorm": "forecast/thunderstorm--scattered.svg",
    "thunderstorm-hail": "forecast/thunderstorm.svg",
    "unknown": "forecast/BK.svg",
}

#: What each sky is coloured. Mid-tone and saturated so the same file works
#: on Grafana's dark theme and its light one -- a pale icon vanishes on
#: white, a dark one vanishes on near-black, and Grafana cannot serve a
#: different file per theme.
COLOURS: dict[str, str] = {
    "clear": "#f0a63a",
    "mostly-clear": "#f0b45e",
    "clear-night": "#7a80c8",
    "mostly-clear-night": "#7a80c8",
    "partly-cloudy-night": "#7f86ba",
    "partly-cloudy": "#8b93a3",
    "overcast": "#78808e",
    "fog": "#96a0ab",
    "drizzle": "#5aa8e0",
    "rain": "#3c8fd4",
    "heavy-rain": "#2a76bd",
    "showers": "#4a9be0",
    "heavy-showers": "#2f80c8",
    "freezing-drizzle": "#5cc0d2",
    "freezing-rain": "#4aacc0",
    "snow": "#7cbfe4",
    "heavy-snow": "#5aa8d6",
    "snow-showers": "#8ccaea",
    "thunderstorm": "#9b7ede",
    "thunderstorm-hail": "#8257d0",
    "unknown": "#8b93a3",
}

#: Where the icons live once Grafana can see them. Grafana serves anything
#: under its own `public/` at this prefix, so a compose file that mounts the
#: provisioned `icons/` there makes every one of these resolve.
URL = "public/img/weewx-evo"

#: The three symbols that only exist after dark. `codes.NIGHT` decides
#: them; named here so nothing has to know both places.
NIGHT_SYMBOLS = tuple(sorted(codes.NIGHT.values()))

_SVG_OPEN = re.compile(r"<svg\b", re.IGNORECASE)
_HAS_FILL = re.compile(r"<svg\b[^>]*\bfill\s*=", re.IGNORECASE | re.DOTALL)


def file_for(symbol: str) -> str:
    """The file this symbol draws as, or the unknown one."""
    return FILES.get(symbol) or FILES["unknown"]


def url_for(symbol: str) -> str:
    """What a panel puts in a cell to get this picture."""
    return f"{URL}/{name_for(symbol)}"


def name_for(symbol: str) -> str:
    """The flat filename, because the copy has no subdirectories.

    `forecast/CL.svg` and `moon.svg` come from two places in the skin and go
    into one directory here: a mount is one line in a compose file, and a
    tree of them is three.
    """
    return f"{symbol}.svg"


def coloured(text: str, colour: str) -> str:
    """The same SVG with a colour on it.

    On the root element rather than each shape. Carbon's files carry a
    `.cls-1 { fill: none }` rule for the transparent bounding rectangle, and
    a stylesheet beats a presentation attribute -- so the rectangle stays
    invisible and everything else takes the colour.
    """
    if _HAS_FILL.search(text):
        # A file that states its own colour means it, the way Deck's brand
        # mark does. Nothing here overrules that.
        return text
    return _SVG_OPEN.sub(f'<svg fill="{colour}"', text, count=1)


def written(out: str | Path) -> list[Path]:
    """Copy every icon into `out`, coloured. Returns what was written.

    One file per symbol rather than per source file, even where two symbols
    share a drawing: `rain` and `heavy-rain` are the same picture in two
    different blues, and a panel asks by symbol.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for symbol in sorted(FILES):
        source = SOURCE / FILES[symbol]
        if not source.exists():
            log.warning("no icon file for %s at %s", symbol, source)
            continue
        colour = COLOURS.get(symbol) or COLOURS["unknown"]
        path = out / name_for(symbol)
        path.write_text(coloured(source.read_text(encoding="utf-8"), colour),
                        encoding="utf-8")
        made.append(path)
    return made


def mappings(night: bool = False) -> list[dict]:
    """Grafana value mappings from a WMO code to a picture and a word.

    One entry per code the core knows, and Grafana's table draws the mapped
    text as an image when the cell is set to. The words go in the same
    mapping so a tooltip and a screen reader get "Light rain" rather than a
    filename, in whatever language the station is set to.

    Every code, not every symbol: the mapping is looked up by the value in
    the field, and that value is the code.
    """
    out: dict[str, dict] = {}
    for code in sorted(codes.CODES):
        symbol = codes.symbol(code, night=night)
        out[str(float(code))] = {"text": url_for(symbol),
                                 "index": len(out)}
        # The code arrives from InfluxDB as a float, and Grafana matches the
        # mapping against the value as it displays it. Both spellings, so a
        # datasource that answers `61` and one that answers `61.0` both hit.
        out[str(code)] = {"text": url_for(symbol), "index": len(out)}
    return [{"type": "value", "options": out}]


def words(language: object = None) -> list[dict]:
    """The same codes mapped to what to call them, for a text cell."""
    out: dict[str, dict] = {}
    for code in sorted(codes.CODES):
        said = codes.text(code, language)
        for spelling in (str(float(code)), str(code)):
            out[spelling] = {"text": said, "index": len(out)}
    return [{"type": "value", "options": out}]

"""WMO present-weather codes, and what to call them.

Every source here speaks a different dialect of "what the weather is doing":
Open-Meteo publishes a reduced WMO 4677 set, DWD publishes the full one, the
American NWS publishes English phrases and an icon name. They are translated
into WMO codes on the way in, so everything downstream has one vocabulary.

Why WMO rather than a set of our own: it is what the sources already use, it
is documented, and a code that means "moderate drizzle" cannot be quietly
reinterpreted the way a string can. A page can decide it does not care and
group everything into six pictures; the code is still there underneath.

**The words are English here and translated in `language.py`**, the same
arrangement as the moon phases and the points of the compass. That is
deliberate: a station is read by the people who live near it.

**The symbols are a name, not a picture.** `partly-cloudy-day` and nothing
else. Which file that is belongs to whoever draws the page -- a skin brings
its own icons, and mapping to a specific set here would make that skin's
icons unusable.
"""

from __future__ import annotations

#: code -> (English text, symbol name, whether it is the night variant)
#:
#: Transcribed from WMO 4677 as Open-Meteo reduced it, which is the set every
#: modern API converged on. Codes not listed fall back to the nearest tens.
CODES: dict[int, tuple[str, str]] = {
    0: ("Clear sky", "clear"),
    1: ("Mainly clear", "mostly-clear"),
    2: ("Partly cloudy", "partly-cloudy"),
    3: ("Overcast", "overcast"),
    45: ("Fog", "fog"),
    48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "drizzle"),
    53: ("Drizzle", "drizzle"),
    55: ("Heavy drizzle", "drizzle"),
    56: ("Light freezing drizzle", "freezing-drizzle"),
    57: ("Freezing drizzle", "freezing-drizzle"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "heavy-rain"),
    66: ("Light freezing rain", "freezing-rain"),
    67: ("Freezing rain", "freezing-rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "heavy-snow"),
    77: ("Snow grains", "snow"),
    80: ("Light rain showers", "showers"),
    81: ("Rain showers", "showers"),
    82: ("Violent rain showers", "heavy-showers"),
    85: ("Light snow showers", "snow-showers"),
    86: ("Snow showers", "snow-showers"),
    95: ("Thunderstorm", "thunderstorm"),
    96: ("Thunderstorm with light hail", "thunderstorm-hail"),
    99: ("Thunderstorm with hail", "thunderstorm-hail"),
}

#: Symbols that mean something different after dark. A clear night is not a
#: sun, and a page that draws one looks broken rather than wrong.
NIGHT = {"clear": "clear-night", "mostly-clear": "mostly-clear-night",
         "partly-cloudy": "partly-cloudy-night"}


def text(code: int | None, language: object = None) -> str:
    """What to call this code, in the language the station is set to."""
    if code is None:
        return ""
    said, _symbol = CODES.get(int(code)) or _nearest(int(code))
    if language is not None:
        translate = getattr(language, "weather", None)
        if translate is not None:
            return translate(int(code), said)
    return said


def symbol(code: int | None, night: bool = False) -> str:
    """A name for the picture, not the picture itself."""
    if code is None:
        return ""
    _said, name = CODES.get(int(code)) or _nearest(int(code))
    return NIGHT.get(name, name) if night else name


def _nearest(code: int) -> tuple[str, str]:
    """The closest code we do know about.

    DWD publishes the full WMO table, which has codes Open-Meteo's reduced
    set never uses -- 63 is in both, 62 is only in DWD's. Falling back to the
    nearest lower entry in the same ten is how a real code becomes a real
    word instead of an empty string on a page.
    """
    for candidate in range(code, max(code - 10, -1), -1):
        if candidate in CODES:
            return CODES[candidate]
    return ("", "unknown")


def is_wet(code: int | None) -> bool:
    """Whether this code means something is falling out of the sky."""
    return code is not None and int(code) >= 51


def is_severe(code: int | None) -> bool:
    """Thunder, hail, freezing, or heavy anything."""
    if code is None:
        return False
    code = int(code)
    return code >= 95 or code in (56, 57, 65, 66, 67, 75, 82, 86)

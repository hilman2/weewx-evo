"""Cumulus `realtime.txt`, and APRS `wxnow.txt`.

Two text files, seventy-odd values between them, and an amount of software
that reads them out of all proportion to what they are. `realtime.txt` is
what Cumulus wrote, and Weather34, Meteotemplate, the Saratoga scripts and
WeatherDisplay all read it; `wxnow.txt` is what every APRS daemon on a
Raspberry Pi picks up. Neither is documented anywhere authoritative, both are
positional, and a field in the wrong place is a wrong reading rather than an
error.

So this is transcribed from Cumulus's own field list, in order, with the
separators it uses -- and the point of it is exactly that: a feed nobody has
to think about, that opens a shelf of existing software to a station that has
none of it.

Three things worth knowing.

**It is one line, and it is written whole.** A page reading the file while it
is being written gets half a line, and half a line of positional data parses
as something else entirely. It is written beside and renamed, the same as
everything else here that publishes.

**The units are Cumulus's, not ours.** Cumulus writes whatever its own
settings say and puts no unit in the file -- the reader is expected to be
configured to match. That is a genuinely bad design and it is not ours to
fix: a consumer configured for Celsius must get Celsius. So the unit system
is a setting on this feed, and it defaults to what the station publishes in.

**Every field is filled, or the line is short.** Cumulus has no way to say
"no reading" -- the position must hold something. So an absent value becomes
`0`, which is a lie, and the only alternative is a line the reader cannot
parse at all. `wxnow.txt` at least has dots for it, and uses them.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from ... import units
from ...uploads import Readings
from .. import Produced

log = logging.getLogger(__name__)

#: Cumulus's field order for `realtime.txt`. Positional: the reader counts
#: spaces, so a field moved is every field after it moved too.
#:
#: (our reading, unit for it, decimals). `None` for the unit means it is not
#: a converted quantity -- a bearing, a percentage, an index.
FIELDS: tuple[tuple[str, str | None, int], ...] = (
    ("outTemp", "temperature", 1),
    ("outHumidity", None, 0),
    ("dewpoint", "temperature", 1),
    ("windSpeed", "speed", 1),
    ("windGust", "speed", 1),
    ("windDir", None, 0),
    ("rainRate", "rainrate", 1),
    ("dayRain", "rain", 1),
    ("barometer", "pressure", 1),
)


class RealtimeFeed:
    """Writes `realtime.txt`, and `wxnow.txt` beside it."""

    label = "Cumulus realtime.txt"
    summary = ("One line of current conditions, in the format Weather34, "
               "Meteotemplate and the Saratoga scripts all read.")
    #: Every packet, not every record. The whole value of this file is that
    #: it is current: a consumer polling it every ten seconds and getting a
    #: five-minute-old reading would be better served by the JSON feed.
    trigger = "packet"

    def __init__(self, reader: Any, unit_system: int = units.US,
                 target: units.Target | None = None,
                 station: str = "", wxnow: bool = True,
                 filename: str = "realtime.txt") -> None:
        self.reader = reader
        self.unit_system = unit_system
        # Cumulus puts no unit in the file, so the reader has to be
        # configured to match. Defaulting to what the station publishes in is
        # the least surprising choice; a consumer that wants something else
        # says so here.
        self.target = target or units.Target(unit_system)
        self.station = station
        self.wxnow = bool(wxnow)
        self.filename = filename or "realtime.txt"

    # -- the values ------------------------------------------------------

    def _unit(self, kind: str | None) -> str | None:
        if kind is None:
            return None
        return self.target.unit(f"group_{kind}")

    def _value(self, readings: Readings, obs: str, kind: str | None,
               places: int) -> str:
        value = readings.get(obs, self._unit(kind))
        if value is None:
            # Cumulus has no way to say "no reading": the position must hold
            # something or every field after it shifts. A zero is a lie, and
            # the alternative is a line no reader can parse. See the module
            # docstring -- this is the format's fault, not a choice.
            return "0"
        return f"{value:.{places}f}"

    def line(self, record: dict, now: float | None = None) -> str:
        """One `realtime.txt` line.

        The first two fields are the date and the time, in Cumulus's own
        formats: `dd/mm/yy` and `HH:MM:SS`, both local. Not ISO, not with a
        four-digit year -- readers parse them positionally and by length.
        """
        readings = Readings(record)
        when = time.localtime(now if now is not None else readings.ts)
        parts = [time.strftime("%d/%m/%y", when), time.strftime("%H:%M:%S", when)]
        parts += [self._value(readings, obs, kind, places)
                  for obs, kind, places in FIELDS]

        # The unit letters Cumulus writes so a reader can at least check.
        # They are not a conversion -- see the module docstring.
        temp_unit = "C" if (self._unit("temperature") or "").endswith("C") else "F"
        speed = self._unit("speed") or ""
        wind_unit = {"meter_per_second": "m/s", "km_per_hour": "km/h",
                     "knot": "kts"}.get(speed, "mph")
        rain_unit = "mm" if (self._unit("rain") or "") == "mm" else "in"
        pressure = self._unit("pressure") or ""
        pressure_unit = "in" if pressure == "inHg" else (
            "mm" if pressure == "mmHg" else "hPa")

        parts += [
            # Cumulus writes a wind bearing as a compass word here.
            _compass(readings.get("windDir", None)),
            self._value(readings, "windSpeed", "speed", 1),   # 10-minute average
            self._value(readings, "windGust", "speed", 1),    # today's high gust
            self._value(readings, "outTemp", "temperature", 1),   # today's high
            self._value(readings, "outTemp", "temperature", 1),   # today's low
            temp_unit, wind_unit, rain_unit, pressure_unit,
            self.station or "weewx-evo",
        ]
        return " ".join(parts)

    def wxnow_line(self, record: dict) -> str:
        """`wxnow.txt`, which every APRS daemon reads.

        Fixed width, US customary throughout, and -- unlike Cumulus -- with
        a way to say "no reading": dots of the field's own width. Used, since
        it exists.
        """
        readings = Readings(record)
        when = time.strftime("%b %d %Y %H:%M", time.localtime(readings.ts))

        def whole(obs: str, unit: str | None, width: int,
                  scale: float = 1.0) -> str:
            value = readings.get(obs, unit)
            if value is None:
                return "." * width
            return f"{int(value * scale + 0.5):0{width}d}"

        line = (f"{whole('windDir', 'degree_compass', 3)}"
                f"/{whole('windSpeed', 'mile_per_hour', 3)}"
                f"g{whole('windGust', 'mile_per_hour', 3)}"
                f"t{whole('outTemp', 'degree_F', 3)}")
        # Rain in hundredths of an inch, which is what APRS means by `r`.
        line += (f"r{whole('hourRain', 'inch', 3, 100)}"
                 f"P{whole('dayRain', 'inch', 3, 100)}")
        humidity = readings.get("outHumidity", "percent")
        line += ("h.." if humidity is None
                 else f"h{int(humidity + 0.5) % 100:02d}")
        pressure = readings.get("barometer", "mbar")
        line += ("b....." if pressure is None
                 else f"b{int(pressure * 10.0 + 0.5):05d}")
        return f"{when}\n{line}\n"

    # -- producing -------------------------------------------------------

    def produce(self, into: Path, now: float | None = None) -> Produced:
        into = Path(into)
        into.mkdir(parents=True, exist_ok=True)
        record = self._latest()
        if record is None:
            return Produced(directory=into, note="nothing has arrived yet")

        files = []
        files.append(_write(into / self.filename,
                            self.line(record, now) + "\n"))
        if self.wxnow:
            files.append(_write(into / "wxnow.txt", self.wxnow_line(record)))
        return Produced(directory=into, files=[f.relative_to(into) for f in files],
                        note=f"{len(files)} file(s)")

    def _latest(self) -> dict | None:
        """The most recent reading there is.

        A live packet where there is one, because that is the whole point of
        this file; the last archive record otherwise, so a station whose
        listener is on another machine still publishes something.
        """
        for how in ("packet", "record"):
            getter = getattr(self.reader, how, None) or getattr(
                self.reader, "latest", None)
            if getter is None:
                continue
            try:
                found = getter() if callable(getter) else getter
            except Exception:
                # A reader that has no live table raises rather than
                # answering, and falling through to the archive record is
                # exactly the intent -- see the docstring.
                log.debug("no %s available from the reader", how, exc_info=True)
                continue
            if isinstance(found, dict) and found:
                return found
        return None

    @staticmethod
    def options() -> list:
        from ...options import Group, Option

        return [
            Group("What is written", "", (
                Option("filename", "File name", default="realtime.txt",
                       help="Some consumers expect a different name. The "
                            "content is the same either way."),
                Option("wxnow", "Also write wxnow.txt", kind="bool",
                       default=True,
                       help="What an APRS daemon on the same machine reads. "
                            "Costs one more small file."),
                Option("station", "Station name", advanced=True,
                       help="Written in the last field. Empty means "
                            "'weewx-evo'."),
            )),
            Group("Units",
                  "Cumulus puts no unit in the file: whoever reads it has to "
                  "be configured to match. That is the format's design and "
                  "not ours to fix, so this has to agree with the consumer.",
                  (
                      Option("units", "Write the values in", kind="choice",
                             default="",
                             choices=(("", "what the station publishes in"),
                                      ("US", "US -- °F, inHg, mph, in"),
                                      ("METRIC", "Metric -- °C, hPa, km/h, mm"),
                                      ("METRICWX", "Metric WX -- °C, hPa, m/s, mm"))),
                  )),
        ]


#: The sixteen points, as Cumulus writes them. English, and not translated:
#: this is a machine-readable file, and a consumer parsing it expects `NNW`.
POINTS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
          "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def _compass(bearing: float | None) -> str:
    if bearing is None:
        return "---"
    return POINTS[int((bearing % 360) / 22.5 + 0.5) % 16]


def _write(path: Path, text: str) -> Path:
    """Beside, then renamed.

    A consumer reading this while it is being written gets half a line, and
    half a line of positional data parses as something else rather than
    failing. A rename is atomic on any filesystem a station runs on.
    """
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(text, encoding="utf-8", newline="\n")
    partial.replace(path)
    return path

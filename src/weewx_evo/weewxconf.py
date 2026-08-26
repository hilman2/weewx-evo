"""Reading weewx.conf.

Read, never written. That is the whole policy and it is worth being explicit
about, because the temptation goes the other way.

The database is shared: the same file, the same meaning, WeeWX able to pick it
up again afterwards. That is the promise this project makes and the reason it
exists. The configuration is not shared, and should not be:

  * Two programs writing one file destroy each other's comments and ordering.
    weewx.conf is full of comments that took years to accumulate and are the
    only documentation many installations have.
  * Most of weewx.conf is about things weewx-evo does not do -- report
    generation, skins, the service list, RESTful uploads. Rewriting a file
    while understanding half of it is how settings quietly disappear.
  * weewx-evo has settings WeeWX has no place for. Written into weewx.conf
    they would be noise to WeeWX and lost on its next upgrade.

So: weewx.conf is imported, and it can go on being the source of the settings
both systems share. Change the altitude there and both follow. Everything
weewx-evo adds lives in its own file, and WeeWX never sees it.

The format is ConfigObj: INI with nesting by bracket depth. Parsed here rather
than with the library, because the parts that matter are a hundred lines and a
weather station should not gain a dependency for reading one file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SECTION = re.compile(r"^(\[+)([^\]]+)(\]+)\s*(?:#.*)?$")
_ENTRY = re.compile(r"^([^=]+?)\s*=\s*(.*)$")


def parse(text: str) -> dict[str, Any]:
    """A weewx.conf as nested dictionaries.

    Values stay strings, or become lists of strings where the file has commas.
    Types are the caller's business: `altitude = 440, meter` is a length and a
    unit, and only something that knows what altitude means can say so.
    """
    root: dict[str, Any] = {}
    stack: list[dict[str, Any]] = [root]

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        section = _SECTION.match(line)
        if section:
            opening, name, closing = section.groups()
            depth = len(opening)
            if depth != len(closing):
                continue  # malformed; ConfigObj would refuse, we skip
            # Bracket depth is nesting depth: [a] is 1, [[b]] is 2.
            del stack[depth:]
            while len(stack) < depth:
                stack.append(stack[-1].setdefault("__orphan__", {}))
            parent = stack[depth - 1]
            node = parent.get(name.strip())
            if not isinstance(node, dict):
                node = {}
                parent[name.strip()] = node
            stack.append(node)
            continue

        entry = _ENTRY.match(line)
        if entry:
            key, value = entry.groups()
            # A quoted key is how a name with spaces in it is written, and
            # a `[Texts]` section is nothing but those:
            #
            #     "Current Conditions" = "Aktuelle Werte"
            #
            # ConfigObj takes the quotes off and so must this, or every
            # translated string in every skin is filed under a name no
            # template ever asks for -- which is a page that renders
            # perfectly and is entirely in English.
            stack[-1][_key(key)] = _value(value)

    root.pop("__orphan__", None)
    return root


def _splits(text: str) -> bool:
    """Whether a value is a list rather than one quoted string.

    `chart_line_colors = "#4282b4", "#b44242"` starts and ends with a quote
    and is still five values. Only a comma outside the quotes decides.
    """
    quote = ""
    for char in text:
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == ",":
            return True
    return False


def _split_outside(text: str) -> list[str]:
    """Split on commas that are not inside quotes."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _key(text: str) -> str:
    """A key as it is meant, with any quotes around it taken off."""
    name = text.strip()
    if len(name) > 1 and name[0] == name[-1] and name[0] in "\"'":
        return name[1:-1]
    return name


def _value(text: str) -> Any:
    """One right-hand side. Quotes off, commas into a list."""
    text = text.strip()
    # A comment after a value, but not a '#' inside quotes.
    if text and text[0] not in "\"'":
        text = text.split("#")[0].strip()
    if (len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'"
            and not _splits(text)):
        return text[1:-1]
    if _splits(text):
        parts = [p.strip().strip("\"'") for p in _split_outside(text)]
        return [p for p in parts if p != ""]
    return text


def read(path: str | Path) -> dict[str, Any]:
    return parse(Path(path).read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Turning it into weewx-evo settings.
# ---------------------------------------------------------------------------

#: Everything below is about *what a setting means*, not where it sits. A
#: WeeWX altitude is a length and a unit; an archive interval is seconds; a
#: driver name is a Python path that has to become a driver name we know.
FEET_PER_METRE = 3.280839895


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _altitude_metres(value: Any) -> float | None:
    """WeeWX writes `altitude = 440, meter`. Either unit, always metres out."""
    if isinstance(value, (list, tuple)):
        amount, unit = (list(value) + ["meter"])[:2]
    else:
        amount, unit = value, "meter"
    metres = _number(amount)
    if metres is None:
        return None
    if str(unit).strip().lower().startswith("foot"):
        metres /= FEET_PER_METRE
    return round(metres, 2)


def _truth(value: Any) -> bool | None:
    if value is None:
        return None
    return str(value).strip().lower() in ("true", "yes", "1", "on")


class Import:
    """The result of reading a weewx.conf: settings, and what was left."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        #: Sections that were understood, for the report.
        self.taken: list[str] = []
        #: Sections deliberately ignored, with why.
        self.ignored: list[tuple[str, str]] = []
        #: Things that looked important and could not be translated.
        self.warnings: list[str] = []

    def take(self, dotted: str, value: Any, note: str) -> None:
        if value is None or value == "":
            return
        self.values[dotted] = value
        self.taken.append(f"{note} -> {dotted} = {value!r}")


def convert(conf: dict[str, Any], driver_names: set[str] | None = None) -> Import:
    """weewx.conf into weewx-evo settings, with a report of what happened."""
    result = Import()
    driver_names = driver_names or set()

    station = conf.get("Station", {})
    result.take("station.name", station.get("location"), "[Station] location")
    result.take("station.latitude", _number(station.get("latitude")),
                "[Station] latitude")
    result.take("station.longitude", _number(station.get("longitude")),
                "[Station] longitude")
    result.take("station.altitude", _altitude_metres(station.get("altitude")),
                "[Station] altitude")

    archive = conf.get("StdArchive", {})
    interval = _number(archive.get("archive_interval"))
    if interval:
        result.take("interval", int(interval), "[StdArchive] archive_interval")
    hilo = _truth(archive.get("loop_hilo"))
    if hilo is not None:
        result.take("loop_hilo", hilo, "[StdArchive] loop_hilo")

    _databases(conf, result)
    _driver(conf, station, driver_names, result)
    _accumulators(conf, result)
    _not_ours(conf, result)
    return result


def _databases(conf: dict[str, Any], result: Import) -> None:
    """Find the SQLite file behind the archive binding."""
    bindings = conf.get("DataBindings", {})
    databases = conf.get("Databases", {})
    types = conf.get("DatabaseTypes", {})

    binding = bindings.get("wx_binding", {})
    name = binding.get("database")
    if not name:
        return
    database = databases.get(name, {})
    if str(database.get("database_type", "")).lower() != "sqlite":
        result.warnings.append(
            f"The archive binding uses {database.get('database_type')!r}, not "
            "SQLite. weewx-evo reads SQLite only for now, so the database path "
            "has not been imported.")
        return

    filename = database.get("database_name")
    root = types.get("SQLite", {}).get("SQLITE_ROOT", "")
    weewx_root = conf.get("WEEWX_ROOT", "")
    if filename:
        path = filename
        if root:
            root = root.replace("%(WEEWX_ROOT)s", str(weewx_root))
            # Joined as text, not with Path: weewx.conf is usually written on
            # the machine that runs it, and importing it on Windows should not
            # turn a Unix path into one with backslashes in it.
            path = root.rstrip("/\\") + "/" + str(filename).lstrip("/\\")
        result.take("archive_db", path, f"[Databases][[{name}]] database_name")

    table = binding.get("table_name")
    if table and table != "archive":
        result.warnings.append(
            f"The archive table is called {table!r}, not 'archive'. Pass "
            "--table when running weewx-evo.")


def _driver(conf: dict[str, Any], station: dict[str, Any],
            driver_names: set[str], result: Import) -> None:
    """Work out which driver is in use, and bring its settings across."""
    kind = str(station.get("station_type", "")).strip()
    if not kind:
        return
    section = conf.get(kind, {})
    module = str(section.get("driver", "")).strip()

    # 'user.ecowitt.driver' -> 'ecowitt'. The last part that names something
    # installed wins, which is how a driver keeps its identity across the two
    # systems without a translation table.
    guess = None
    for part in reversed(module.split(".")):
        if part in driver_names:
            guess = part
            break
    if guess is None and kind.lower() in driver_names:
        guess = kind.lower()

    if guess is None:
        result.warnings.append(
            f"[Station] station_type is {kind!r} using {module or 'an unnamed driver'}. "
            "No driver of that name is installed here, so its settings were not "
            "imported. Install it, or set the driver by hand.")
        return

    result.take("driver", guess, f"[Station] station_type = {kind}")

    port = _number(section.get("port"))
    if port:
        result.take("port", int(port), f"[{kind}] port")
    if section.get("address"):
        result.take("host", section["address"], f"[{kind}] address")

    # The driver's own settings, kept under its name. Anything not a section
    # is a plain setting; sections are field maps and station lists.
    carried: dict[str, Any] = {}
    for key, value in section.items():
        if key in ("driver", "port", "address"):
            continue
        carried[key] = value
    if carried:
        result.values[f"drivers.{guess}"] = carried
        result.taken.append(
            f"[{kind}] {len(carried)} driver setting(s) -> drivers.{guess}")


def _accumulators(conf: dict[str, Any], result: Import) -> None:
    """Carry over how observations are aggregated, if it was customised.

    This is the one part of weewx.conf that changes recorded numbers rather
    than behaviour: an extractor decides whether a field is averaged or summed
    over an interval. Getting it wrong is not visible until a month of rain
    turns out to be a monthly average.
    """
    accum = conf.get("Accumulator", {})
    custom = {name: settings for name, settings in accum.items()
              if isinstance(settings, dict)}
    if custom:
        result.values["accumulator"] = custom
        result.taken.append(f"[Accumulator] {len(custom)} custom type(s)")


#: Sections that belong to parts of WeeWX weewx-evo does not have. Named so
#: the report can say "not imported, and here is why" rather than saying
#: nothing, which reads as "lost".
_NOT_OURS = {
    "StdReport": "report generation, which weewx-evo does not do (yet)",
    "StdRESTful": "uploads to weather services, not yet in weewx-evo",
    "StdWXCalculate": "derived readings, computed differently here",
    "StdQC": "quality control, not yet in weewx-evo",
    "Engine": "the WeeWX service list, which has no counterpart",
    "StdTimeSynch": "console clock syncing, which is the driver's business here",
    "StdCalibrate": "corrections, not yet in weewx-evo",
    "StdConvert": "unit conversion on the way in, done by drivers here",
    "StdPrint": "printing packets to the log",
    "StdLoopStore": "superseded: weewx-evo keeps every packet by design",
}


def _not_ours(conf: dict[str, Any], result: Import) -> None:
    for name, why in _NOT_OURS.items():
        if name in conf:
            result.ignored.append((name, why))


def report(result: Import, source: str) -> str:
    """What the import did, as something a person reads before trusting it."""
    lines = [f"Read {source}", ""]

    if result.values:
        lines.append(f"Imported {len(result.taken)} setting(s):")
        lines.extend(f"  {line}" for line in result.taken)
    else:
        lines.append("Nothing was imported. Is this a weewx.conf?")
    lines.append("")

    if result.ignored:
        lines.append("Not imported, because weewx-evo has no counterpart:")
        for name, why in result.ignored:
            lines.append(f"  [{name}] -- {why}")
        lines.append("")

    if result.warnings:
        lines.append("Worth looking at:")
        for warning in result.warnings:
            lines.append(f"  {warning}")
        lines.append("")

    lines.append("weewx.conf itself has not been touched and will not be. Change")
    lines.append("a shared setting there and import again, or set it here -- what")
    lines.append("is set here wins.")
    return "\n".join(lines)

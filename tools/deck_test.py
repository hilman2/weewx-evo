"""Nothing of the old skin is left in what the new one produces.

The Deck skin was Carbon web components loaded from a CDN, a 1.7 MB React
bundle whose source is not in this repository, and a megabyte of Plotly for
one chart. All of that is gone; this is the test that says so, and keeps
saying so.

It renders the skin against the reference database and reads the pages
back. Every check here is something that was actually wrong at some point
during the rewrite, which is the only kind of check worth having:

  * A `<script>` or `<link>` pointing anywhere but at this station. The
    console errors that started the whole rewrite were five versions of
    `bx-tooltip` arriving from IBM's CDN, two of them defining the same
    element.
  * A Carbon class or element. `bx--col-sm-4 bx--col-md-8` is a tile
    saying how wide it is at five breakpoints; there were 233 of them.
  * An attribute only the old bundle read -- `data-nivo-props`,
    `data-combinedkeys`, `calendar-diagram-clim-wrap`.
  * A date written the American way on a page that is not in English.
    `%x` is answered out of the process locale, and the image sets none.
  * A reading in the wrong unit. A skin that adds up rain itself hands the
    total to a `ValueHelper` and expects it to convert.
  * A chart element with nothing in it, or a tab pointing at a panel that
    does not exist.

Run:

    python tools/deck_test.py [reference/weewx.sdb]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from itertools import pairwise
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

os.environ.setdefault("TZ", "Europe/Berlin")
if hasattr(time, "tzset"):
    time.tzset()

from weewx_evo.feeds import cheetah  # noqa: E402
from weewx_evo.series import Reader  # noqa: E402

#: Anything the browser fetches on its own while loading the page. A link
#: somebody may click is not that -- the footer credits weewx-evo on GitHub
#: and always will.
FOREIGN = re.compile(
    r"""<(?:script|link|img|iframe|source)\b[^>]*?"""
    r"""(?:src|href)\s*=\s*["'](?:https?:)?//(?!www\.w3\.org)""",
    re.IGNORECASE | re.DOTALL)

#: What the old skin left behind, and what each one means.
LEFTOVERS = (
    (re.compile(r"\bbx--[a-z]"), "a Carbon grid or type class"),
    (re.compile(r"<(?:bx|cds|dds)-"), "a Carbon web component"),
    (re.compile(r"data-nivo-props"), "the old chart bundle's props"),
    (re.compile(r"data-combinedkeys"), "the old chart bundle's series list"),
    (re.compile(r"calendar-diagram-clim-wrap"), "the old calendar element"),
    (re.compile(r"weewxWdcConfig"), "the old configuration global"),
    (re.compile(r"dist/main\.(?:js|css)"), "the old bundle"),
    (re.compile(r"plotly", re.IGNORECASE), "Plotly"),
    (re.compile(r"s81c\.com|cdnjs\.cloudflare"), "a CDN"),
    (re.compile(r'class="[a-z]+"-'), "a half-converted element"),
)

#: `08/27/26`. Correct on an English page, wrong on any other.
US_DATE = re.compile(r"\b\d{2}/\d{2}/\d{2}\b")

#: `1.11 in`, `68.0°F`: US units on a page asked for in metric.
US_UNITS = re.compile(r"\d\s?(?:in|inHg|°F|mph)\b")


class Settings:
    """The narrow thing `cheetah.from_settings` reads."""

    def __init__(self, values: dict) -> None:
        self.values = values
        self.config: dict = {}

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def source(self, key: str) -> str:
        return "the configuration file" if key in self.values else "default"


def render(database: Path, into: Path, language: str = "de") -> object:
    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    feed = cheetah.from_settings(Settings({
        "language": language,
        "station.latitude": 48.4596,
        "station.longitude": 11.6539,
        "station.altitude": 440.0,
        "station.name": "Kirchdorf an der Amper",
        "feeds.deck.skin": "deck",
        "feeds.deck.extras": {"base_path": "/"},
    }), Reader(conn), (), prefix="feeds.deck")
    feed.produce(into)
    return feed



def with_forecast(database: Path, into: Path, language: str = "de") -> tuple:
    """Render the front page with a forecast stored beside the archive.

    The section is Deck's whole answer to a configured forecast, and until
    now it answered nothing: what was there spoke to weewx-forecast and
    weewx-DWD, neither of which can be installed here, so every branch was
    unreachable and the section never appeared at all.

    Returns (the page, what the feed failed to render).
    """
    import shutil
    import time

    from weewx_evo.forecast import Day, Moment, Reading, Warning
    from weewx_evo.forecast.store import ForecastStore

    beside = into / "data"
    beside.mkdir(parents=True, exist_ok=True)
    # Copied rather than pointed at: the forecast has to sit beside the
    # archive, and the reference database is read-only and shared.
    archive = beside / "weewx.sdb"
    shutil.copy(database, archive)

    now = int(time.time())
    midnight = now - (now % 86400)
    store = ForecastStore(beside / "forecast.sdb")
    store.store(Reading(
        source="open-meteo", issued=now - 3600,
        hours=[Moment(dateTime=midnight + h * 3600, usUnits=17,
                      outTemp=12.0 + h % 9, windSpeed=3.0,
                      rainProbability=float((h * 7) % 100),
                      code=[0, 2, 61, 95][h % 4])
               for h in range(48)],
        days=[Day(dateTime=midnight + d * 86400, usUnits=17,
                  tempMax=21.0 + d, tempMin=9.0 + d, windMax=4.0 + d,
                  rainProbability=float(d * 11 % 100),
                  code=[0, 3, 61, 71, 95, 45, 80][d % 7],
                  sunrise=midnight + d * 86400 + 21600,
                  sunset=midnight + d * 86400 + 72000)
              for d in range(7)],
        warnings=[Warning(identifier="w1", event="Sturmboeen",
                          severity="Severe", starts=now - 1800,
                          ends=now + 7200, issued=now - 3600,
                          headline="Amtliche Warnung vor Sturmboeen",
                          description="Sturmboeen um 70 km/h.",
                          instruction="Achten Sie auf herabfallende Aeste.",
                          area="Landkreis Freising", source="open-meteo",
                          kind="wind")]), fetched=now)

    pages = into / "pages"
    conn = sqlite3.connect(f"file:{archive}?mode=ro", uri=True)
    try:
        feed = cheetah.from_settings(Settings({
            "language": language,
            "archive_db": str(archive),
            "station.latitude": 48.4596,
            "station.longitude": 11.6539,
            "station.altitude": 440.0,
            "station.name": "Kirchdorf an der Amper",
            "feeds.deck.skin": "deck",
            "feeds.deck.extras": {"base_path": "/"},
        }), Reader(conn), (), prefix="feeds.deck")
        feed.produce(pages)
    finally:
        conn.close()
    page = pages / "index.html"
    if not page.is_file():
        # The front page not being written at all is what a broken tag in the
        # forecast section looks like: `feed.failed` names it, and reading a
        # file that was never written would hide that behind a traceback.
        return "", feed.failed or [("index.html.tmpl", "it was not written")]
    return page.read_text(encoding="utf-8", errors="replace"), feed.failed


def check_forecast(database: Path, out: Path) -> list[str]:
    """What a configured forecast puts on the page."""
    import re as _re

    problems: list[str] = []
    page, failed = with_forecast(database, out / "forecast")
    for name, why in failed:
        problems.append(f"with a forecast, {name} did not render: {why}")
    if problems:
        return problems

    for needle, what in (
        ('data-test="forecast-days"', "the daily strip"),
        ('data-test="forecast-hours"', "the hourly strip"),
        ('class="forecast-warnings"', "the warnings"),
        ("forecast-issued", "when the model ran"),
    ):
        if needle not in page:
            problems.append(f"the forecast section has no {what}")

    days = _re.findall(r'<li class="forecast-day">', page)
    if len(days) != 7:
        problems.append(f"{len(days)} day card(s), wanted 7")

    # The symbol reaches an icon. A card with `data-symbol` and no `<svg>`
    # after it is the mapping in `forecast-icon.inc` having fallen behind the
    # names `forecast/codes.py` produces.
    for match in _re.finditer(r'data-symbol="([^"]*)"(.{0,400})', page, _re.DOTALL):
        if not match.group(1):
            problems.append("a forecast card has no symbol at all")
        elif "<svg" not in match.group(2):
            problems.append(f"no icon for the symbol {match.group(1)!r}")

    # Written in the language the page is in, both the skin's words and the
    # weather itself. `codes.text` asks the language module and takes the
    # English when it has no answer, so an untranslated table shows up as an
    # English sky on a German page.
    for said in ("Heute", "Klarer Himmel", "Mehr"):
        if said not in page:
            problems.append(f"the forecast does not say {said!r} in German")
    for said in ("Clear sky", "Overcast", "Thunderstorm"):
        if said in page:
            problems.append(f"the forecast still says {said!r} in English")

    # And the units the page is written in, not the ones the source sent.
    if _re.search(r'class="forecast-day__max">[\d.]+&#176;F', page):
        problems.append("the forecast is in Fahrenheit on a metric page")

    return problems


def main(argv: list[str]) -> int:
    database = Path(argv[1] if len(argv) > 1 else "reference/weewx.sdb")
    if not database.is_file():
        print(f"no such database: {database}")
        print("see the README for how to fetch a reference database")
        return 2

    out = Path(tempfile.mkdtemp(prefix="deck-test-"))
    failures: list[str] = []
    try:
        feed = render(database, out)

        for name, why in feed.failed:
            failures.append(f"{name} did not render: {why}")

        failures += check_forecast(database, out)

        pages = sorted(out.glob("*.html"))
        if len(pages) < 5:
            failures.append(f"only {len(pages)} page(s) rendered")

        for page in pages:
            text = page.read_text(encoding="utf-8", errors="replace")
            where = page.name

            for match in FOREIGN.finditer(text):
                line = text[match.start():match.start() + 90]
                failures.append(f"{where}: fetches from another host: {line}")

            for pattern, what in LEFTOVERS:
                found = pattern.search(text)
                if found:
                    failures.append(f"{where}: {what} is still here: "
                                    f"{text[found.start():found.start() + 60]!r}")

            for match in US_DATE.finditer(text):
                around = text[max(0, match.start() - 60):match.end() + 10]
                failures.append(f"{where}: American date on a German page: "
                                f"{' '.join(around.split())[-70:]}")

            for match in US_UNITS.finditer(text):
                around = text[max(0, match.start() - 50):match.end() + 5]
                failures.append(f"{where}: US unit on a metric page: "
                                f"{' '.join(around.split())[-60:]}")

            failures.extend(check_charts(where, text))
            failures.extend(check_tabs(where, text))

        # Every asset the pages ask for has to be there. A stylesheet that
        # 404s leaves an unstyled page, which is the one failure a person
        # notices immediately and a test never does.
        for page in pages:
            text = page.read_text(encoding="utf-8", errors="replace")
            for asset in re.findall(r'(?:src|href)="([^":]+\.(?:js|css))"',
                                    text):
                if not (out / asset.lstrip("/")).is_file():
                    failures.append(f"{page.name}: {asset} was never copied")

        failures.extend(check_climatology(database))
        failures.extend(check_span_shapes(database))

        note = getattr(feed, "tags", None)
        missing = getattr(note, "missing", {}) if note else {}
        if missing:
            failures.append("tags with no answer: "
                            + ", ".join(sorted(missing)))
    finally:
        shutil.rmtree(out, ignore_errors=True)

    for one in failures[:40]:
        print("  FAIL", one)
    if len(failures) > 40:
        print(f"  ... and {len(failures) - 40} more")

    print(f"\n{'FAIL' if failures else 'PASS'} ({len(failures)} failure(s))")
    return 1 if failures else 0


#: Thresholds that contain one another, loosest first. A count further
#: down the list can never be larger than one above it.
NESTED = (
    ("summerDays", "hotDays", "desertDays"),
    ("rainDays", "heavyRainDays", "veryHeavyRainDays"),
)


def check_climatology(database: Path) -> list[str]:
    """The counted days, checked against each other.

    Not against the weather -- against arithmetic. Three rain days and
    four heavy rain days is a fault whatever fell out of the sky.
    """
    import sqlite3

    from weewx_evo import language, skinkit, units
    from weewx_evo.series import Reader
    from weewx_evo.skins.deck.tags import StatsUtil
    from weewx_evo.tags import Tags

    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    reader = Reader(conn)
    target = units.Target("METRICWX", language=language.get("de"))
    tags = Tags(reader=reader, target=target, unit_system=reader.system,
                station={})
    generator = skinkit.Generator({"DisplayOptions": {}, "Labels": {}}, {},
                                  reader, target, tags, language="de")
    stats = StatsUtil(generator)
    span = reader.span()
    if not span:
        return []

    out = []
    counted = {}
    every = sorted({name for row in NESTED for name in row}
                   | {"tropicalNights", "stormDays", "iceDays", "frostDays",
                      "snowDays", "thunderDays", "heatingDays"})
    for name in every:
        try:
            counted[name] = stats.get_climatological_day(name, span[0], span[1])
        except Exception as exc:  # a count that raises is the finding
            out.append(f"{name} could not be counted: "
                       f"{type(exc).__name__}: {exc}")
            continue
        if counted[name] is None:
            out.append(f"{name} counted nothing at all (None, not zero)")
        elif counted[name] < 0:
            out.append(f"{name} counted {counted[name]} days")

        try:
            said = stats.get_climatological_day_description(name)
        except Exception as exc:
            out.append(f"{name} has no description: "
                       f"{type(exc).__name__}: {exc}")
            continue
        if not said:
            out.append(f"{name} has an empty description")

    for row in NESTED:
        for looser, tighter in pairwise(row):
            if looser in counted and tighter in counted:
                if (counted[looser] is not None and counted[tighter] is not None
                        and counted[tighter] > counted[looser]):
                    out.append(
                        f"{tighter} ({counted[tighter]}) is a stricter "
                        f"threshold than {looser} ({counted[looser]}) and "
                        "cannot be counted more often")

    # A frost day is a night below zero; an ice day is a whole day below
    # zero, so every ice day is a frost day too.
    if counted.get("iceDays") and counted.get("frostDays") is not None:
        if counted["iceDays"] > counted["frostDays"]:
            out.append(f"iceDays ({counted['iceDays']}) exceeds frostDays "
                       f"({counted['frostDays']}), which cannot happen")
    return out


def check_span_shapes(database: Path) -> list[str]:
    """A day grid for a year, a month grid for the whole archive.

    Both are built from the same call, and which one comes out is decided
    by how long the span is. A station recording since 2016 must not get
    eleven stacked year calendars on its all-time page.
    """
    import json as _json
    import sqlite3

    from weewx_evo import language, skinkit, units
    from weewx_evo.series import Reader
    from weewx_evo.skins.deck.tags import StatsUtil
    from weewx_evo.tags import Tags

    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    reader = Reader(conn)
    target = units.Target("METRICWX", language=language.get("de"))
    tags = Tags(reader=reader, target=target, unit_system=reader.system,
                station={})
    generator = skinkit.Generator({"DisplayOptions": {}, "Labels": {}}, {},
                                  reader, target, tags, language="de")
    stats = StatsUtil(generator)
    span = reader.span()
    if not span:
        return []

    out = []
    stop = span[1]

    # A year and a bit: still a square per day.
    short = _json.loads(stats.get_calendar_chart(
        "rain", "sum", stop - 300 * 86400, stop))
    if short.get("kind") != "calendar":
        out.append(f"300 days should be a day calendar, got "
                   f"{short.get('kind')!r}")

    # Ten years: months by years, and no more than a screen of rows.
    long = _json.loads(stats.get_calendar_chart(
        "rain", "sum", stop - 3650 * 86400, stop))
    if long.get("kind") != "matrix":
        out.append(f"ten years should be a month grid, got "
                   f"{long.get('kind')!r}")
    else:
        years = long.get("years") or []
        if len(years) > 12:
            out.append(f"ten years came out as {len(years)} rows")
        for column, row, _value in long.get("data") or []:
            if not 0 <= column <= 11:
                out.append(f"a month index outside 0-11: {column}")
                break
            if not 0 <= row < max(1, len(years)):
                out.append(f"a year index outside the years: {row}")
                break
        if len(long.get("months") or []) != 12:
            out.append("the month grid does not have twelve column names")
    return out


def check_charts(where: str, text: str) -> list[str]:
    """Every chart has a shape the drawing code can use."""
    out = []
    specs = re.findall(r"data-chart='([^']*)'", text)
    if "index.html" in where and not specs:
        failures = "the front page has no charts at all"
        out.append(f"{where}: {failures}")

    for raw in specs:
        try:
            spec = json.loads(raw.replace("&#34;", '"'))
        except ValueError as exc:
            out.append(f"{where}: a chart's data is not JSON: {exc}")
            continue

        kind = spec.get("kind")
        if kind in (None, ""):
            out.append(f"{where}: a chart does not say what kind it is")
        if kind in ("line", "bar", "vector"):
            series = spec.get("series") or []
            if not series:
                out.append(f"{where}: a {kind} chart has no series")
            for one in series:
                if not one.get("data"):
                    out.append(f"{where}: a series has no data: "
                               f"{one.get('label')!r}")
                elif isinstance(one["data"], str) and \
                        f"var {one['data']} =" not in text:
                    out.append(f"{where}: {one['data']} is named by a chart "
                               "and never written")
        if kind == "windrose" and not spec.get("bands"):
            out.append(f"{where}: the wind rose has no bands")
        if kind == "calendar" and not spec.get("data"):
            out.append(f"{where}: a calendar has no days in it")
    return out


def check_tabs(where: str, text: str) -> list[str]:
    """Every tab points at a panel that exists."""
    out = []
    for controls in re.findall(r'role="tab"[^>]*aria-controls="([^"]+)"',
                               text):
        if f'id="{controls}"' not in text:
            out.append(f"{where}: a tab points at {controls!r}, "
                       "which is not on the page")
    for tab in re.findall(r"<button[^>]*role=\"tab\"[^>]*>", text):
        if "aria-controls" not in tab:
            out.append(f"{where}: a tab controls nothing: {tab[:60]}")
    return out


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""The dashboards themselves.

Five, and each answers a different question. That is the design: a dashboard
that tries to answer two is a wall of panels somebody scrolls past, which is
the commonest way a Grafana installation ends up unused.

    now           is everything alright? -- the screen on the wall
    location      one station, in full
    compare       one reading, every station, which is why Grafana is here
    charts-*      every plot in `plots.toml`, one dashboard per span
    operations    who has stopped talking

**Three seconds, thirty seconds, five minutes.** The top row is numbers big
enough to read from across the room. Under it, the charts that explain them.
Below that, collapsed, the detail somebody opens twice a year. A reader who
wanted the first row never scrolls; a reader who wanted the third never had
to wonder where it was.

**Almost no words of its own.** A panel showing `outTemp` is titled by
`words.obs`, which is `units.obs_label` with the station's language behind
it -- so a German station reads "Außentemperatur" without a single string in
this file. What is left is in `words.py`, and untranslated keys fall back to
English rather than to nothing.

**The location list comes from the data.** A dashboard variable asking
InfluxDB which `location` tags exist means a console added next month appears
in the picker on its own -- which is what makes one dashboard serve n
consoles rather than n dashboards serving one each. The top row uses
Grafana's `repeat`, so five consoles lay themselves out.

**One dashboard per span, not one with a hundred panels.** The Seasons set is
a hundred charts over four spans; all of them on one page is a browser
opening a hundred queries. Split by span they are twenty-five each, and the
split is one somebody already made -- a day chart and a year chart of the
same reading are different questions.

**Operations needs no `/metrics`.** The one thing worth alerting on is a
station that has stopped, and that is a location whose newest point is old.
InfluxDB can answer it, so the panel exists now rather than after the
endpoint does.
"""

from __future__ import annotations

from typing import Any

from . import SCHEMA_VERSION, panels, stamp
from . import query_influx as flux
from .panels import FULL, HALF, THIRD, grid

#: The readings on the top row and the overview charts, with how each is
#: reduced to one number. Deliberately short: this is the page somebody opens
#: to see whether anything needs them, and a station's hundred columns belong
#: on the charts dashboards.
SUMMARY = (
    ("outTemp", "last"),
    ("outHumidity", "last"),
    ("windSpeed", "max"),
    ("rain", "sum"),
    ("barometer", "last"),
)

#: The charts on the detail page. Grouped the way somebody reads weather
#: rather than one reading per panel -- a temperature without its dewpoint is
#: half a sentence. The gust comes before the wind speed so the speed is drawn
#: on top of it: the gust is the envelope of the same measurement.
DETAIL = (
    (("outTemp", "", ""), ("dewpoint", "", ""), ("appTemp", "", "")),
    (("windGust", "max", ""), ("windSpeed", "", "")),
    (("windDir", "", ""),),
    (("rain", "sum", ""),),
    (("barometer", "", ""),),
    (("radiation", "", ""), ("UV", "", "")),
)

#: Opened twice a year, so the row starts collapsed.
INDOORS = (
    (("inTemp", "", ""), ("inHumidity", "", "")),
    (("txBatteryStatus", "max", ""),),
    (("rxCheckPercent", "", ""),),
)


class _Ids:
    """Panel ids, unique within a dashboard. Grafana needs them to be."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> int:
        self.n += 1
        return self.n


def _named(readings: tuple, words: Any) -> str:
    """A panel title out of the readings in it, in the station's language."""
    names = [words.obs(obs) for obs, _aggregate, _label in readings]
    return ", ".join(dict.fromkeys(names))


def _shell(uid: str, title: str, server: Any, panel_list: list[dict],
           variable: bool = False, span: str = "now-24h",
           readings: bool = False) -> dict:
    words = server.words
    board: dict = {
        "uid": uid,
        "title": title,
        "tags": ["weewx-evo"],
        "schemaVersion": SCHEMA_VERSION,
        "version": 1,
        "editable": True,
        "refresh": "1m",
        "time": {"from": span, "to": "now"},
        # Empty means the browser's own zone. An archive day boundary is
        # local midnight, and the browser is where the reader is.
        "timezone": "",
        "templating": {"list": []},
        "panels": panel_list,
    }
    if variable:
        board["templating"]["list"].append({
            "name": "location",
            "label": words.location,
            "type": "query",
            "datasource": server.reference(),
            # Asked of the data. A list written in here would be a second
            # place that has to learn about a new station.
            "query": flux.locations(server.bucket, server.measurement),
            "refresh": 1,
            "includeAll": False,
            "multi": False,
            "current": {},
            "options": [],
        })
    if readings:
        board["templating"]["list"].append({
            "name": "reading",
            "label": words.reading,
            "type": "custom",
            # The value is the column name and the label is the translation,
            # so the picker reads in German and the query stays valid.
            "query": ", ".join(f"{words.obs(obs)} : {obs}"
                               for obs, _how in SUMMARY),
            "current": {"text": words.obs(SUMMARY[0][0]),
                        "value": SUMMARY[0][0]},
            "options": [],
        })
    return board


def now(server: Any, weight: bool = False) -> dict:
    """Is everything alright. The screen on the wall.

    The top row is one tile per location, laid out by Grafana's `repeat`. The
    number is what somebody came for; the sparkline behind it is what stops
    the number being ambiguous -- 4 °C falling and 4 °C rising are different
    mornings, and a bare figure cannot say which.
    """
    words, ids = server.words, _Ids()
    panel_list: list[dict] = [
        panels.now(server, "outTemp", "$location", grid(0, 0, 6, 5),
                   where="$location", panel_id=ids(), repeat="location"),
    ]

    y = 5
    for index, (obs, _how) in enumerate(SUMMARY):
        title = (f"{words.obs(obs)} {words.today}" if obs == "rain"
                 else words.obs(obs))
        panel_list.append(panels.timeseries(
            server, [(obs, "sum" if obs == "rain" else "", "")], title,
            grid((index % 2) * HALF, y + (index // 2) * 8, HALF),
            where="", weight=weight, panel_id=ids()))
    y += ((len(SUMMARY) + 1) // 2) * 8

    panel_list.append(panels.text("", stamp(words), grid(0, y, FULL, 3),
                                  panel_id=ids()))
    return _shell("weewx-evo-now", words.title(words.now), server, panel_list,
                  variable=True)


def location(server: Any, weight: bool = False) -> dict:
    """One station, in full. The page somebody keeps open."""
    words, ids = server.words, _Ids()
    panel_list: list[dict] = []

    for index, (obs, how) in enumerate(SUMMARY):
        title = (f"{words.obs(obs)} {words.today}" if obs == "rain"
                 else words.obs(obs))
        panel_list.append(panels.now(
            server, obs, title, grid(index * 4, 0, 4, 4),
            where="${location}", panel_id=ids(), aggregate=how))

    y, column = 4, 0
    for readings in DETAIL:
        wide = FULL if readings[0][0] == "rain" else HALF
        title = (words.sun if readings[0][0] == "radiation"
                 else _named(readings, words))
        panel_list.append(panels.timeseries(
            server, list(readings), title, grid(column, y, wide),
            where="${location}", weight=weight, panel_id=ids()))
        if wide == FULL:
            y, column = y + 8, 0
        elif column == 0:
            column = HALF
        else:
            y, column = y + 8, 0
    if column:
        y += 8

    hidden = [
        panels.timeseries(
            server, list(readings), _named(readings, words),
            grid((index % 3) * THIRD, y + 1, THIRD), where="${location}",
            weight=weight, panel_id=ids())
        for index, readings in enumerate(INDOORS)
    ]
    panel_list.append(panels.row(words.indoors, y, ids(), collapsed=True,
                                 inside=hidden))

    return _shell("weewx-evo-location", words.title(words.one_location),
                  server, panel_list, variable=True)


def compare(server: Any, weight: bool = False) -> dict:
    """One reading, every location. The reason Grafana is here at all.

    A rendered page belongs to one archive, so this is the picture Deck
    cannot draw however well it is written -- not a shortcoming of the
    template language but of what a page is.
    """
    words, ids = server.words, _Ids()
    panel_list = [
        panels.timeseries(
            server, [("$reading", "", "")],
            f"$reading, {words.every_location}", grid(0, 0, FULL, 12),
            where="", weight=weight, panel_id=ids(),
            description=words.about_compare),
    ]
    y = 12
    for index, (obs, _how) in enumerate(SUMMARY[:4]):
        title = (f"{words.obs(obs)} {words.today}" if obs == "rain"
                 else words.obs(obs))
        panel_list.append(panels.timeseries(
            server, [(obs, "sum" if obs == "rain" else "", "")], title,
            grid((index % 2) * HALF, y + (index // 2) * 8, HALF),
            where="", weight=weight, panel_id=ids()))
    return _shell("weewx-evo-compare", words.title(words.compare), server,
                  panel_list, readings=True)


def charts(server: Any, plots: Any, weight: bool = False) -> dict[str, dict]:
    """Every plot in `plots.toml`, one dashboard per span.

    The set is generous on purpose -- a chart for a sensor this station does
    not have costs nothing, because the query returns nothing and the panel is
    empty rather than wrong. Same reasoning `starter/` gives for shipping a
    hundred of them.
    """
    words = server.words
    by_span: dict[str, list] = {}
    for plot in plots:
        by_span.setdefault(plot.span or "day", []).append(plot)

    boards: dict[str, dict] = {}
    for span, group in by_span.items():
        ids = _Ids()
        panel_list = [
            panels.panel(plot, server,
                         grid((index % 2) * HALF, (index // 2) * 8, HALF),
                         location="${location}", weight=weight,
                         panel_id=ids())
            for index, plot in enumerate(group)
        ]
        name = f"weewx-evo-charts-{span}"
        boards[name] = _shell(
            name, words.title(f"{words.charts} ({words.span(span)})"),
            server, panel_list, variable=True, span=_range_for(span))
    return boards


def _range_for(span: str) -> str:
    """A dashboard's picker, matched to the span its panels were made for."""
    return {"day": "now-24h", "week": "now-7d", "month": "now-30d",
            "year": "now-1y"}.get(span, "now-24h")


def operations(server: Any) -> dict:
    """Who has stopped talking, and what the batteries are doing.

    Deliberately narrow, for the same reason `watchdog.py` is: a panel that
    goes red when somebody else's hardware is switched off at night is a panel
    people learn to ignore.
    """
    words, ids = server.words, _Ids()
    panel_list = [
        panels.stat(
            words.last_seen,
            flux.last_seen(server.bucket, server.measurement),
            server, grid(0, 0, FULL, 5), unit="s", panel_id=ids(),
            description=words.about_last_seen,
            # An archive interval is five minutes, so a quarter of an hour is
            # three missed ones -- late enough to mean something, early
            # enough to still be this morning's problem.
            thresholds=[{"color": "green", "value": None},
                        {"color": "#E0B400", "value": 900},
                        {"color": "#E02F44", "value": 3600}]),
        panels.timeseries(
            server, [("txBatteryStatus", "max", "")],
            words.obs("txBatteryStatus"), grid(0, 5, HALF), where="",
            panel_id=ids(), description=words.about_battery),
        panels.timeseries(
            server, [("rxCheckPercent", "", "")], words.obs("rxCheckPercent"),
            grid(HALF, 5, HALF), where="", panel_id=ids()),
        panels.timeseries(
            server, [("interval", "max", "")], words.obs("interval"),
            grid(0, 13, FULL, 6), where="", panel_id=ids(),
            description=words.about_interval),
        panels.text("", stamp(words), grid(0, 19, FULL, 3), panel_id=ids()),
    ]
    return _shell("weewx-evo-operations", words.title(words.operations),
                  server, panel_list, span="now-7d")


def all_of(server: Any, plots: Any, weight: bool = False) -> dict[str, dict]:
    """Every dashboard for one server, by file name."""
    boards = {
        "weewx-evo-now": now(server, weight),
        "weewx-evo-location": location(server, weight),
        "weewx-evo-compare": compare(server, weight),
        "weewx-evo-operations": operations(server),
    }
    if plots is not None and len(plots):
        boards.update(charts(server, plots, weight))
    return boards

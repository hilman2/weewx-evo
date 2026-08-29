#!/usr/bin/env python3
"""What `weewx-evo grafana provision` writes, checked the way a reader would.

A dashboard is JSON, so almost anything wrong with one is still valid JSON.
These are the faults that survive a syntax check and show up as a page
somebody quietly stops opening:

**Panels on top of each other.** Grafana lays out by `gridPos`, and two
panels claiming the same cell overlap in the browser with no error anywhere.
The layout code that walks a column and wraps is exactly where that happens,
so every dashboard's grid is walked here cell by cell.

**A wind direction drawn as a line.** It goes 358, 359, 1, and the line falls
the full height of the panel. The reading is circular; `style.py` says points,
and this checks that it reached the JSON rather than merely being written
down.

**A freezing line at zero on a Fahrenheit axis.** It would sit off the bottom
of every chart between October and April, marking nothing.

**A token in a dashboard.** The datasource file holds the credentials and is
written 0600; a dashboard is copied around, pasted into issues and rendered
to PNG. Nothing secret may be in one.

**A German station reading "Outside Temperature".** One setting reaches every
renderer here, and a dashboard is read by the same people as the pages.

    python tools/grafana_test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import grafana, language, units
from weewx_evo import plots as plot_defs
from weewx_evo.grafana import dashboards, panels, style
from weewx_evo.grafana import query_influx as flux

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def truthy(what: str, got: object) -> None:
    check(what, bool(got), True)


UPLOADS = {
    "kirchdorf": {"kind": "influx", "url": "http://influxdb:8086",
                  "token": "write-token", "org": "acme", "bucket": "weewx",
                  "location": "kirchdorf", "unit_system": "metricwx"},
    "schuppen": {"kind": "influx", "url": "http://influxdb:8086",
                 "token": "write-token", "org": "acme", "bucket": "weewx",
                 "location": "schuppen", "unit_system": "metricwx"},
    # Not an InfluxDB upload. It must not become a datasource.
    "wu": {"kind": "wunderground", "station": "IBAYERN1", "password": "x"},
}

PLOTS = plot_defs.from_dict({"plot": [
    {"name": "daytempdew", "span": "day", "time_length": 97200,
     "line": [{"obs": "outTemp"}, {"obs": "dewpoint", "color": "#00ff00"}]},
    {"name": "dayrain", "span": "day", "time_length": 97200,
     "line": [{"obs": "rain", "kind": "bar", "aggregate": "sum",
               "interval": 3600}]},
    {"name": "daywinddir", "span": "day", "time_length": 97200,
     "line": [{"obs": "windDir"}]},
    {"name": "yearhilow", "span": "year", "time_length": 31536000,
     "line": [{"obs": "outTemp", "aggregate": "max"},
              {"obs": "outTemp", "aggregate": "min"}]},
]})


def servers(language_code: str = "en") -> list:
    return grafana.servers_from(UPLOADS, language.get(language_code))


# ---------------------------------------------------------------------------
# What becomes a datasource.
# ---------------------------------------------------------------------------

def test_one_datasource_per_server() -> None:
    """Two archives in one bucket are two tags, not two datasources.

    This is the whole shape the comparison dashboard stands on: a query that
    leaves the location filter out returns one series per location. Two
    datasources would make that impossible and nothing would say so.
    """
    found = servers()
    check("two uploads, one server", len(found), 1)
    check("both locations on it", sorted(found[0].locations),
          ["kirchdorf", "schuppen"])
    check("the weather service is not one", found[0].uploads,
          ["kirchdorf", "schuppen"])


def test_the_uid_is_stable() -> None:
    """A dashboard names its datasource by uid.

    One that changes between runs leaves every panel provisioned before it
    pointing at nothing -- and the panel says "datasource not found", which
    reads like Grafana's fault.
    """
    check("same inputs, same uid", servers()[0].uid, servers()[0].uid)
    other = grafana.servers_from(
        {"a": dict(UPLOADS["kirchdorf"], url="http://elsewhere:8086")})
    check("a different server, a different uid",
          other[0].uid != servers()[0].uid, True)


def test_no_secret_in_a_dashboard() -> None:
    """The datasource file holds the token. A dashboard is copied around."""
    out = Path(tempfile.mkdtemp())
    grafana.provision(out, UPLOADS, PLOTS, read_token="read-only-token")
    for path in (out / "dashboards").glob("*.json"):
        text = path.read_text(encoding="utf-8")
        check(f"no write token in {path.name}", "write-token" in text, False)
        check(f"no read token in {path.name}", "read-only-token" in text, False)

    written = (out / "datasources" / "weewx-evo.yaml").read_text(encoding="utf-8")
    check("the read token is used where one is given",
          "read-only-token" in written, True)
    check("and the write token is not", "write-token" in written, False)
    check("Flux, so an InfluxDB 2 bucket needs no DBRP mapping",
          "version: Flux" in written, True)


def test_the_upload_token_is_used_but_said() -> None:
    """It works out of the box, and the page says it has more rights than
    it needs. Silence there would be a write token in a container for ever.
    """
    out = Path(tempfile.mkdtemp())
    report = grafana.provision(out, UPLOADS, PLOTS)
    written = (out / "datasources" / "weewx-evo.yaml").read_text(encoding="utf-8")
    check("it works without a read token", "write-token" in written, True)
    truthy("and says so", [n for n in report.notes if "read" in n.lower()])


def test_nothing_configured_is_said_not_crashed() -> None:
    out = Path(tempfile.mkdtemp())
    report = grafana.provision(out, {"wu": UPLOADS["wu"]}, PLOTS)
    check("no files written", report.files, [])
    truthy("and a reason given", report.notes)


# ---------------------------------------------------------------------------
# The layout.
# ---------------------------------------------------------------------------

def cells(panel: dict) -> set[tuple[int, int]]:
    pos = panel["gridPos"]
    return {(pos["x"] + dx, pos["y"] + dy)
            for dx in range(pos["w"]) for dy in range(pos["h"])}


def test_no_panel_sits_on_another() -> None:
    """Grafana overlaps them silently. The eye finds it; no parser does."""
    for server in servers():
        for name, board in dashboards.all_of(server, PLOTS).items():
            taken: dict[tuple[int, int], str] = {}
            for panel in board["panels"]:
                if panel["type"] == "row":
                    continue
                for cell in cells(panel):
                    if cell in taken:
                        FAILURES.append(
                            f"{name}: {panel['title']!r} overlaps "
                            f"{taken[cell]!r} at {cell}")
                        break
                    taken[cell] = panel["title"]
            global CHECKS
            CHECKS += 1


def test_every_panel_has_an_id_and_a_home() -> None:
    for server in servers():
        for name, board in dashboards.all_of(server, PLOTS).items():
            ids = [p["id"] for p in board["panels"]]
            check(f"{name}: ids are unique", len(ids), len(set(ids)))
            for panel in board["panels"]:
                if panel["type"] == "text":
                    continue
                truthy(f"{name}: {panel.get('title')!r} has a query",
                       panel["type"] == "row" or panel.get("targets"))


def test_a_collapsed_row_keeps_its_panels_inside() -> None:
    """Grafana holds a collapsed row's panels within it and an expanded
    row's beside it. Put them in the wrong place and the row opens empty.
    """
    board = dashboards.location(servers()[0])
    rows = [p for p in board["panels"] if p["type"] == "row"]
    check("there is a collapsed row", len(rows), 1)
    check("and it is collapsed", rows[0]["collapsed"], True)
    truthy("with its panels inside it", rows[0]["panels"])


# ---------------------------------------------------------------------------
# The drawing decisions.
# ---------------------------------------------------------------------------

def only(board: dict, title_contains: str) -> dict:
    for panel in board["panels"]:
        if title_contains.lower() in str(panel.get("title", "")).lower():
            return panel
    raise AssertionError(f"no panel whose title has {title_contains!r}")


def test_wind_direction_is_points() -> None:
    """358, 359, 1 -- a line there falls the height of the panel."""
    board = dashboards.charts(servers()[0], PLOTS)["weewx-evo-charts-day"]
    custom = only(board, "wind direction")["fieldConfig"]["defaults"]["custom"]
    check("drawn as points", custom["drawStyle"], "points")
    check("not joined", custom["lineWidth"], 0)
    check("and the axis is the compass, not the data",
          (custom.get("axisSoftMin"), custom.get("axisSoftMax")), (0, 360))


def test_rain_is_bars_from_zero() -> None:
    board = dashboards.charts(servers()[0], PLOTS)["weewx-evo-charts-day"]
    defaults = only(board, "rain")["fieldConfig"]["defaults"]
    check("drawn as bars", defaults["custom"]["drawStyle"], "bars")
    check("from zero", defaults["min"], 0)


def test_humidity_is_a_percentage() -> None:
    """An automatic axis turns 60-65 % into a crisis."""
    board = dashboards.now(servers()[0])
    defaults = only(board, "humidity")["fieldConfig"]["defaults"]
    check("floor", defaults["min"], 0)
    check("ceiling", defaults["max"], 100)


def test_temperature_carries_its_own_colour_and_freezing() -> None:
    board = dashboards.now(servers()[0])
    defaults = only(board, "temperature")["fieldConfig"]["defaults"]
    check("the colour is the reading",
          defaults["color"]["mode"], "continuous-BlYlRd")
    steps = defaults["thresholds"]["steps"]
    check("freezing is marked", [s["value"] for s in steps], [None, 0])
    check("as a line", defaults["custom"]["thresholdsStyle"]["mode"], "line")


def test_freezing_follows_the_unit() -> None:
    """A page published in Fahrenheit freezes at 32."""
    american = style.for_obs("outTemp", units.US)
    check("Fahrenheit freezes at 32",
          [s["value"] for s in american["thresholds"]["steps"]], [None, 32])
    check("Celsius at zero",
          [s["value"] for s in
           style.for_obs("outTemp", units.METRICWX)["thresholds"]["steps"]],
          [None, 0])


def test_a_second_reading_is_not_painted_like_the_first() -> None:
    """A dewpoint under a temperature must not also get the gradient."""
    board = dashboards.charts(servers()[0], PLOTS)["weewx-evo-charts-day"]
    panel = only(board, "dew")
    refs = [o["matcher"]["options"] for o in panel["fieldConfig"]["overrides"]]
    check("the second series is overridden", "B" in refs, True)


def test_units_come_from_the_upload_not_the_plot() -> None:
    """The conversion already happened when the point was written."""
    metric = grafana.servers_from(UPLOADS)[0]
    american = grafana.servers_from(
        {"a": dict(UPLOADS["kirchdorf"], unit_system="us")})[0]
    check("a metricwx bucket says Celsius",
          panels.unit_for("outTemp", metric.system), "celsius")
    check("a US bucket says Fahrenheit",
          panels.unit_for("outTemp", american.system), "fahrenheit")


def test_an_unknown_unit_falls_back_to_a_suffix() -> None:
    """A guessed Grafana identifier prints itself on the axis.

    Centibars and decibels are real units on real stations and Grafana has
    no name for either, so they take our own label. Written against a
    reading that exists: the first version of this asked about
    `vapor_pressure`, which is not a column, and passed by measuring the
    empty answer a missing field gives.
    """
    for obs, wanted in (("soilMoist1", "suffix:cb"), ("noise", "suffix:dB")):
        check(f"{obs} keeps our label", panels.unit_for(obs, units.METRICWX),
              wanted)
    check("a reading nothing knows says nothing rather than guessing",
          panels.unit_for("nonesuch", units.METRICWX), "")


# ---------------------------------------------------------------------------
# The queries.
# ---------------------------------------------------------------------------

def test_a_query_names_everything_it_needs() -> None:
    query = flux.plain("weewx", "weather", "outTemp", "max", "kirchdorf")
    for wanted in ('from(bucket: "weewx")', '_measurement == "weather"',
                   '_field == "outTemp"', 'r.location == "kirchdorf"',
                   "fn: max", "v.timeRangeStart", "v.windowPeriod"):
        check(f"the query says {wanted}", wanted in query, True)


def test_leaving_the_location_out_is_the_comparison() -> None:
    every = flux.plain("weewx", "weather", "outTemp")
    check("no location filter", "r.location" in every, False)


def test_weighting_is_measured_not_assumed() -> None:
    """One archive interval means `mean()` *is* the weighted average.

    So the plain query is also the correct one, and the expensive form is
    kept for the database that actually needs it.
    """
    plain = flux.for_line("weewx", "weather", "outTemp", "", "", weight=False)
    check("unweighted by default", "_weight" in plain, False)

    weighted = flux.for_line("weewx", "weather", "outTemp", "", "", weight=True)
    for wanted in ("pivot(", "r.interval", "reduce(", "_weight", "_sum"):
        check(f"the weighted form uses {wanted}", wanted in weighted, True)

    # An extreme is exact whatever the interval did.
    for aggregate in ("max", "min"):
        check(f"{aggregate} needs no weighting",
              "_weight" in flux.for_line("weewx", "weather", "outTemp",
                                         aggregate, "", weight=True), False)


def test_a_query_hands_back_one_column() -> None:
    """Flux carries every column through, and Grafana draws each of them.

    Without this the weighted query drew its own `_sum` and `_weight` on the
    temperature axis -- 80 °C on a summer afternoon -- and every legend read
    `_product {_start="2026-08-28 12:22:52 +0000 UTC", _stop=...}`. Humidity
    was worse: the extra series sat far above the fixed 0-100 axis, so the
    real line flattened against the top and looked like a stuck sensor.

    Checking the words in the query would not have found it; only running it
    did. This is the cheap half of that lesson.
    """
    for query in (flux.plain("weewx", "weather", "outTemp"),
                  flux.plain("weewx", "weather", "outTemp", "max", "here"),
                  flux.weighted("weewx", "weather", "outTemp"),
                  flux.weighted("weewx", "weather", "outTemp", "here")):
        check("the query keeps one value and the location",
              '|> keep(columns: ["_time", "_value", "location"])' in query,
              True)
        # And it is the last thing before the yield, or the columns it drops
        # are put back by whatever follows.
        steps = [line.strip() for line in query.splitlines() if "|>" in line]
        check("nothing computes after the keep",
              steps[-2].startswith("|> keep"), True)


def test_a_location_is_escaped_into_flux() -> None:
    query = flux.plain("weewx", "weather", "outTemp", "", 'a "quoted" name')
    check("the quotes are escaped", '\\"quoted\\"' in query, True)


def test_a_grafana_variable_survives_the_escaping() -> None:
    """`${location}` has to reach Grafana intact to be substituted."""
    query = flux.plain("weewx", "weather", "outTemp", "", "${location}")
    check("the variable is intact", 'r.location == "${location}"' in query,
          True)


# ---------------------------------------------------------------------------
# The language.
# ---------------------------------------------------------------------------

def test_a_german_station_reads_german() -> None:
    german = dashboards.now(servers("de")[0])
    english = dashboards.now(servers("en")[0])
    check("the dashboard is named in German", german["title"], "Wetter: Jetzt")
    check("and in English otherwise", english["title"], "Weather: Now")

    titles = [p["title"] for p in german["panels"] if p.get("title")]
    truthy("a panel title is translated",
           any("temperatur" in t.lower() for t in titles))
    check("and nothing is left in English",
          any(t == "Outside Temperature" for t in titles), False)


def test_german_is_spelled_german() -> None:
    """Not "Aussentemperatur". It is a weather page, in a language."""
    said = servers("de")[0].words.obs("outTemp")
    check("with the letter it is spelled with", "ß" in said or "ä" in said,
          True)


def test_an_untranslated_word_stays_english() -> None:
    """A language with twelve of twenty words shows twelve, not nothing."""
    from weewx_evo.grafana.words import ENGLISH, Words

    class Half:
        def text(self, section, key, fallback=""):
            return "ÜBERSETZT" if key == "now" else fallback

    words = Words(Half())
    check("the translated one", words.now, "ÜBERSETZT")
    check("and the rest", words.compare, ENGLISH["compare"])


def test_an_unknown_word_is_refused() -> None:
    """An empty panel title reads as Grafana's fault rather than ours."""
    from weewx_evo.grafana.words import Words

    try:
        _ = Words().not_a_word
    except AttributeError as exc:
        check("it says where to add it", "words.ENGLISH" in str(exc), True)
    else:
        check("an unknown word raises", False, True)


def test_every_word_has_english() -> None:
    """The fallback that can be missing is not one."""
    from weewx_evo.grafana.words import ENGLISH

    for key, said in ENGLISH.items():
        truthy(f"{key} has English", said.strip())


# ---------------------------------------------------------------------------
# The files.
# ---------------------------------------------------------------------------

def test_what_is_written_is_json_grafana_can_read() -> None:
    out = Path(tempfile.mkdtemp())
    report = grafana.provision(out, UPLOADS, PLOTS, read_token="ro")
    truthy("files were written", report.files)
    truthy("panels were counted", report.panels)

    for path in (out / "dashboards").glob("*.json"):
        board = json.loads(path.read_text(encoding="utf-8"))
        for key in ("uid", "title", "schemaVersion", "panels", "time"):
            truthy(f"{path.name} has {key}", key in board)
        check(f"{path.name}: the uid is the file name",
              board["uid"], path.stem)

    provider = (out / "dashboards" / "weewx-evo.yaml").read_text(encoding="utf-8")
    check("the provider points where the compose file mounts them",
          grafana.CONTAINER_DASHBOARDS in provider, True)


def test_a_plot_set_becomes_one_dashboard_per_span() -> None:
    out = Path(tempfile.mkdtemp())
    grafana.provision(out, UPLOADS, PLOTS)
    names = {p.stem for p in (out / "dashboards").glob("*.json")}
    check("a dashboard for the day charts",
          "weewx-evo-charts-day" in names, True)
    check("and one for the year charts",
          "weewx-evo-charts-year" in names, True)


def main() -> int:
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
            except Exception as exc:  # a failing test is the finding
                FAILURES.append(f"{name} raised {type(exc).__name__}: {exc}")

    if FAILURES:
        print(f"{len(FAILURES)} of {CHECKS} checks failed:\n")
        for failure in FAILURES:
            print(f"  {failure}\n")
        return 1
    print(f"grafana: {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

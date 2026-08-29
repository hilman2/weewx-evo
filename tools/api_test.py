#!/usr/bin/env python3
"""The API, against the reader it is a shell over.

The check that matters is that every answer equals what `series.py` gives for
the same question. That is the whole design: a second implementation of "the
average temperature last week" is the fault `chartdata.py` describes -- two
answers, both right on their own, differing in the third decimal, and nobody
able to say which one is the station's.

So nothing here compares against a typed-in figure. It asks the API and asks
the reader, and the two have to agree.

Three more, all about a caller who is a program:

**A refusal says what to do.** `400` alone means reading the source. Every
error here names the field, the values it takes, or the endpoint that lists
them.

**A span that would answer with a million points is turned away**, with the
two parameters that make it answerable -- not left to time out, and not
handed a gigabyte of JSON.

**Every answer names its unit.** The archive keeps what the station wrote,
which may be Fahrenheit on a German station, and a number without a unit is
worse here than on a page: the reader is a program that will not notice.

The last part runs it through the real web server on loopback, because the
route into it is as much a part of this as the answers.

    python tools/api_test.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import units
from weewx_evo.api import MOST_POINTS, Api
from weewx_evo.db.archive import ArchiveStore
from weewx_evo.series import Reader

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def truthy(what: str, got: object) -> None:
    check(what, bool(got), True)


START = 1755648000
DAYS = 4
EVERY = 1800

_MADE: Path | None = None


def an_archive() -> Path:
    """One archive, built once. US units, so the conversion is exercised.

    A console in Germany reporting Fahrenheit into a page in Celsius is the
    ordinary case here, and an API that hands the raw figure to a program is
    the same fault as a page printing it.
    """
    global _MADE
    if _MADE is not None:
        return _MADE

    where = Path(tempfile.mkdtemp()) / "weewx.sdb"
    records = []
    stamp = START
    for index in range(DAYS * 86400 // EVERY):
        stamp += EVERY
        records.append({
            "dateTime": stamp, "usUnits": units.US,
            "interval": EVERY / 60.0,
            "outTemp": 50.0 + (index % 40),
            "outHumidity": 40.0 + (index % 50),
            "windSpeed": (index % 12) / 2.0,
            "barometer": 29.8 + (index % 20) / 100.0,
        })
    store = ArchiveStore(where)
    try:
        store.add_records(records)
        store.conn.commit()
    finally:
        store.close()
    _MADE = where
    return where


def an_api(**kw: object) -> Api:
    return Api({"default": an_archive()}, station_name="Kirchdorf", **kw)


def asked(api: Api, path: str, query: str = "") -> tuple[int, dict]:
    answer = api.answer(path, query)
    return answer.status, json.loads(answer.body)


def a_reader():
    """The same reader the feeds use, for comparing against."""
    conn = sqlite3.connect(f"file:{an_archive()}?mode=ro", uri=True)
    return closing(conn), Reader(conn)


# ---------------------------------------------------------------------------
# The one that matters: the same answer as `series.py`.
# ---------------------------------------------------------------------------

def test_a_series_is_what_the_reader_says() -> None:
    api = an_api()
    status, body = asked(
        api, "/api/v1/series",
        f"obs=outTemp&start={START}&stop={START + DAYS * 86400}"
        f"&aggregate=max&every=day")
    check("it answers", status, 200)

    holder, reader = a_reader()
    with holder:
        found = reader.series("outTemp", START, START + DAYS * 86400,
                              "max", "day")
    check("the same number of points", len(body["values"]), len(found.values))
    check("the same values", body["values"], found.values)
    check("and the same instants",
          body["time"], [int(one) for one in found.time])


def test_an_aggregate_is_what_the_reader_says() -> None:
    api = an_api()
    stop = START + DAYS * 86400
    for how in ("avg", "min", "max", "count"):
        _status, body = asked(api, "/api/v1/aggregate",
                              f"obs=outTemp&start={START}&stop={stop}&how={how}")
        holder, reader = a_reader()
        with holder:
            found = reader.aggregate("outTemp", START, stop, how)
        check(f"{how} matches the reader", body["value"], found)


def test_raw_records_are_the_records() -> None:
    """With no aggregate, the archive records themselves."""
    api = an_api()
    stop = START + 86400
    _status, body = asked(api, "/api/v1/series",
                          f"obs=outTemp&start={START}&stop={stop}")
    holder, reader = a_reader()
    with holder:
        found = reader.series("outTemp", START, stop)
    check("the same points", body["values"], found.values)
    check("and no aggregate named", body["aggregate"], None)


# ---------------------------------------------------------------------------
# Units.
# ---------------------------------------------------------------------------

def test_an_answer_names_its_unit() -> None:
    api = an_api()
    _status, body = asked(api, "/api/v1/series",
                          f"obs=outTemp&start={START}&stop={START + 86400}")
    check("the archive's own unit", body["unit"], "degree_F")
    truthy("with something to print", body["unit_label"])
    check("and what it measures", body["group"], "group_temperature")


def test_a_caller_can_ask_for_another_system() -> None:
    """A console reporting Fahrenheit and a client wanting Celsius is the
    ordinary case, and the conversion belongs on this side of the wire."""
    api = an_api()
    stop = START + 86400
    _status, raw = asked(api, "/api/v1/aggregate",
                         f"obs=outTemp&start={START}&stop={stop}&how=max")
    _status, wanted = asked(
        api, "/api/v1/aggregate",
        f"obs=outTemp&start={START}&stop={stop}&how=max&units=metricwx")

    check("the unit changed", (raw["unit"], wanted["unit"]),
          ("degree_F", "degree_C"))
    check("and the figure with it",
          round(wanted["value"], 6),
          round(float(units.convert(raw["value"], "degree_F", "degree_C")), 6))


def test_an_unknown_unit_system_is_named() -> None:
    api = an_api()
    status, body = asked(api, "/api/v1/aggregate",
                         f"obs=outTemp&start={START}&how=max&units=imperial")
    check("refused", status, 400)
    check("and the ones that exist are listed",
          "metricwx" in body["error"], True)


# ---------------------------------------------------------------------------
# What a caller gets wrong.
# ---------------------------------------------------------------------------

def test_a_span_too_large_is_turned_away_with_the_answer() -> None:
    """Ten years of five-minute records is a million points.

    Serialising them is a gigabyte and a process that dies rather than
    answers, so the request is refused -- and the refusal names the two
    parameters that make it answerable.
    """
    api = an_api()
    status, body = asked(api, "/api/v1/series",
                         f"obs=outTemp&start=-10y&stop={START + 86400}")
    check("refused", status, 400)
    check("and it says how to ask instead",
          "aggregate" in body["error"] and "every" in body["error"], True)

    # With buckets it is answerable, because the count is on the buckets.
    status, _body = asked(
        api, "/api/v1/series",
        f"obs=outTemp&start=-10y&stop={START + 86400}&aggregate=max&every=day")
    check("with buckets it is answered", status, 200)

    # But not into buckets so fine that it is the same problem again.
    status, body = asked(
        api, "/api/v1/series",
        f"obs=outTemp&start=-10y&stop={START + 86400}&aggregate=max&every=60")
    check("a minute of buckets over ten years is refused", status, 400)
    check("and it says why", str(MOST_POINTS) in body["error"], True)


def test_an_unknown_reading_names_where_to_look() -> None:
    api = an_api()
    status, body = asked(api, "/api/v1/series", "obs=nonesuch&start=-1d")
    check("refused", status, 400)
    check("and it points at /fields", "/fields" in body["error"], True)


def test_an_unknown_aggregate_lists_the_real_ones() -> None:
    api = an_api()
    status, body = asked(api, "/api/v1/series",
                         "obs=outTemp&start=-1d&aggregate=median")
    check("refused", status, 400)
    check("and lists them", "avg" in body["error"], True)


def test_a_missing_reading_is_asked_for() -> None:
    api = an_api()
    status, body = asked(api, "/api/v1/series", "start=-1d")
    check("refused", status, 400)
    check("by name", "obs" in body["error"], True)


def test_backwards_time_is_refused() -> None:
    api = an_api()
    status, body = asked(api, "/api/v1/aggregate",
                         f"obs=outTemp&start={START + 86400}&stop={START}"
                         f"&how=max")
    check("refused", status, 400)
    check("and says which way round", "before" in body["error"], True)


def test_a_time_can_be_written_three_ways() -> None:
    """A script has an epoch, a person has a date, a dashboard has -7d."""
    api = an_api()
    stop = START + 2 * 86400
    answers = []
    for start in (str(START), "2025-08-20T00:00:00", "-10000d"):
        status, body = asked(api, "/api/v1/aggregate",
                             f"obs=outTemp&start={start}&stop={stop}&how=count")
        answers.append((status, body.get("value")))
    check("all three are understood", [one[0] for one in answers], [200] * 3)

    status, body = asked(api, "/api/v1/aggregate",
                         "obs=outTemp&start=lunchtime&how=max")
    check("and something that is not a time is refused", status, 400)
    check("with the shapes that work", "-7d" in body["error"], True)

    # A digit too many is one keystroke away, and before the epoch it is not
    # a span. Left through it reaches time.localtime with a negative number.
    status, body = asked(api, "/api/v1/aggregate",
                         "obs=outTemp&start=-100000d&how=max")
    check("a span reaching before 1970 is refused", status, 400)
    check("and says so", "1970" in body["error"], True)


def test_an_unknown_endpoint_is_a_404() -> None:
    api = an_api()
    status, body = asked(api, "/api/v1/nonesuch")
    check("not found", status, 404)
    truthy("and it says so", body.get("error"))


# ---------------------------------------------------------------------------
# What it tells a client about itself.
# ---------------------------------------------------------------------------

def test_the_index_names_the_endpoints() -> None:
    """So somebody with the address can find the rest without the source."""
    _status, body = asked(an_api(), "/api/v1/")
    truthy("it names the endpoints", body.get("endpoints"))
    for wanted in ("/series", "/aggregate", "/fields", "/current"):
        check(f"{wanted} is listed", wanted in body["endpoints"], True)
    check("and the aggregates it takes", "avg" in body["aggregates"], True)


def test_fields_says_what_can_be_asked_for() -> None:
    _status, body = asked(an_api(), "/api/v1/fields")
    names = {one["name"] for one in body["fields"]}
    check("the readings are there", "outTemp" in names, True)
    check("and the bookkeeping is not",
          "usUnits" in names or "dateTime" in names, False)

    one = next(f for f in body["fields"] if f["name"] == "outTemp")
    check("with its unit", one["unit"], "degree_F")
    check("what it measures", one["group"], "group_temperature")
    truthy("something to print", one["label"])
    # Whether a long span is cheap. A client can use it to decide what to ask
    # for rather than finding out by waiting.
    check("and whether the summaries can answer it", one["daily"], True)


def test_current_is_the_newest_record() -> None:
    api = an_api()
    _status, body = asked(api, "/api/v1/current")
    holder, reader = a_reader()
    with holder:
        span = reader.span()
    check("the newest instant", body["dateTime"], span[1])
    truthy("with readings in it", body["record"])
    check("and nothing that is not one", "usUnits" in body["record"], False)


def test_archives_are_listed_with_their_span() -> None:
    _status, body = asked(an_api(), "/api/v1/archives")
    check("one archive", len(body["archives"]), 1)
    one = body["archives"][0]
    check("named", one["name"], "default")
    check("marked as the default", one["default"], True)
    check("with its units", one["units"], "US")
    truthy("and what it covers", one["first"] and one["last"])


def test_an_archive_that_is_not_there_is_named() -> None:
    status, body = asked(an_api(), "/api/v1/series",
                         "obs=outTemp&start=-1d&archive=nonesuch")
    check("refused", status, 400)
    check("and points at /archives", "/archives" in body["error"], True)


# ---------------------------------------------------------------------------
# The token.
# ---------------------------------------------------------------------------

def test_without_a_token_anybody_the_pages_reach_can_ask() -> None:
    check("answered", asked(an_api(), "/api/v1/")[0], 200)


def test_with_one_it_is_required_and_a_wrong_one_is_a_404() -> None:
    """404, not 401. Saying "wrong token" confirms there is something here to
    try tokens against -- the same rule as the listener."""
    api = an_api(token="s3cret")
    check("nothing without it", api.answer("/api/v1/").status, 404)
    check("nothing with the wrong one",
          api.answer("/api/v1/", "token=guess").status, 404)
    check("in the query", api.answer("/api/v1/", "token=s3cret").status, 200)
    check("or in a header",
          api.answer("/api/v1/", "", header_token="s3cret").status, 200)


def test_stations_do_not_give_away_their_identities() -> None:
    """An identity is what a console proves itself with, and this endpoint is
    reachable by anybody the web server answers."""

    class Station:
        name, driver, archive, role, indoor = "haus", "ecowitt", "default", "main", True
        identity = "evo-3f9a2c"

    class Stations:
        def all(self):
            return [Station()]

    api = Api({"default": an_archive()}, stations=Stations())
    _status, body = asked(api, "/api/v1/stations")
    check("the station is listed", body["stations"][0]["name"], "haus")
    check("and its identity is not",
          "identity" in json.dumps(body), False)


# ---------------------------------------------------------------------------
# Through the real server.
# ---------------------------------------------------------------------------

def test_it_answers_over_http() -> None:
    """The route in is as much a part of this as the answers.

    And a feed called `api` must not shadow it, which is why the API is
    matched before the feeds -- a feed can be called anything somebody types.
    """
    from weewx_evo.netaccess import Access
    from weewx_evo.webserver import Site, WebServer

    where = Path(tempfile.mkdtemp())
    (where / "api").mkdir()
    (where / "api" / "index.html").write_text("a feed called api",
                                              encoding="utf-8")
    site = Site({"api": where / "api"})
    server = WebServer(site, "127.0.0.1", 0, access=Access.parse("any"),
                       api=an_api())
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with urllib.request.urlopen(f"{base}/api/v1/", timeout=5) as answer:
            check("it answers", answer.status, 200)
            check("as JSON", answer.headers.get("Content-Type"),
                  "application/json; charset=utf-8")
            body = json.loads(answer.read())
        check("and it is the API, not the feed of that name",
              body.get("weewx_evo"), "v1")

        with urllib.request.urlopen(
                f"{base}/api/v1/aggregate?obs=outTemp&start={START}"
                f"&stop={START + 86400}&how=max", timeout=5) as answer:
            value = json.loads(answer.read())["value"]
        holder, reader = a_reader()
        with holder:
            found = reader.aggregate("outTemp", START, START + 86400, "max")
        check("with the reader's own number", value, found)

        # A bad request comes back as a status a client can act on, with a
        # body it can print.
        try:
            urllib.request.urlopen(f"{base}/api/v1/series?obs=nope&start=-1d",
                                   timeout=5)
        except urllib.error.HTTPError as exc:
            check("a bad request is a 400", exc.code, 400)
            truthy("with a reason in it", json.loads(exc.read()).get("error"))
        else:
            check("a bad request is refused", False, True)
    finally:
        server.stop()


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
    print(f"api: {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

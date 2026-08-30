#!/usr/bin/env python3
"""Archive records into InfluxDB, and back out as the same numbers.

Two halves, and the second is the one that matters.

**The line, built and read back.** Line protocol is a text format with four
separators and an escape rule, and every mistake in it answers HTTP 400 with
a message about a line number. The checks here are the four traps the module
docstring names -- a field that is an integer once and a float afterwards, a
NaN from a derived reading, a location with spaces in it, a record where
quality control left nothing -- because each of those rejects a whole batch
and none of them come up on the afternoon somebody sets this up.

**The numbers, round trip.** Records go in, line protocol comes out, it is
parsed back, and every value is compared against what `units.convert` says it
should be. That is the check with something at stake: this upload exists so
that Grafana can draw the same series the station's own pages draw, and a
conversion that quietly differs is exactly the fault `chartdata.py` describes
-- two renderers, both right on their own, disagreeing in the third decimal.

The server is real (loopback, an ephemeral port) rather than a stub, because
what is being checked in the second half is which HTTP answers mean "stop"
and which mean "Tuesday" -- and a stub that returns a number is a restatement
of the code under test.

    python tools/influx_test.py
"""

from __future__ import annotations

import http.server
import math
import os
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import units
from weewx_evo.uploads import Rejected
from weewx_evo.uploads.influx import BATCH, InfluxUpload

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def close_to(what: str, got: float | None, want: float, tol: float = 1e-9) -> None:
    global CHECKS
    CHECKS += 1
    if got is None or abs(got - want) > tol:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


# A record in US units. The archive keeps what the console wrote, and a
# console reporting Fahrenheit into a metric series is the ordinary case
# here -- so this is the record that exercises the conversion instead of
# skipping past it.
US_RECORD = {
    "dateTime": 1756308600,          # 2025-08-27 15:30:00 UTC
    "usUnits": units.US,
    "interval": 5,
    "outTemp": 68.2,                 # °F
    "outHumidity": 61.0,
    "barometer": 29.92,              # inHg
    "windSpeed": 4.0,                # mph
    "windDir": 315.0,
    "rain": 0.0,                     # inches -- zero rain is a measurement
    "radiation": 812.0,
}


# ---------------------------------------------------------------------------
# Reading a line back.
# ---------------------------------------------------------------------------

def parse(line: str) -> tuple[str, dict[str, str], dict[str, float], int]:
    """Line protocol back into its parts, honouring the escapes.

    Written out rather than split on the separators, because the whole point
    of the escaping checks below is that an unescaped split is wrong.
    """
    def split(text: str, on: str) -> list[str]:
        """Split on unescaped separators, leaving the escapes in place.

        Removing them here was this tool's own bug: the line is split three
        times over -- space, comma, equals -- and a parser that unescapes on
        the first pass hands the second one a bare comma in the middle of
        "Kirchdorf, an der Amper". The value came back as "Kirchdorf" and
        the check read like a fault in the escaping it was there to prove.
        """
        parts, current, escaped = [], [], False
        for char in text:
            if escaped:
                current.append(char)
                escaped = False
            elif char == "\\":
                current.append(char)
                escaped = True
            elif char in on:
                parts.append("".join(current))
                current = []
            else:
                current.append(char)
        parts.append("".join(current))
        return parts

    def unescape(text: str) -> str:
        out, escaped = [], False
        for char in text:
            if escaped:
                out.append(char)
                escaped = False
            elif char == "\\":
                escaped = True
            else:
                out.append(char)
        return "".join(out)

    head, fields_text, stamp = split(line, " ")

    head_parts = split(head, ",")
    measurement, tag_parts = unescape(head_parts[0]), head_parts[1:]
    tags = {}
    for part in tag_parts:
        name, value = split(part, "=")
        tags[unescape(name)] = unescape(value)

    fields = {}
    for part in split(fields_text, ","):
        name, value = split(part, "=")
        fields[unescape(name)] = float(value)
    return measurement, tags, fields, int(stamp)


def upload(**kw: object) -> InfluxUpload:
    settings: dict = {"url": "http://127.0.0.1:8086", "token": "t",
                      "org": "o", "bucket": "weewx"}
    settings.update(kw)
    return InfluxUpload(**settings)


# ---------------------------------------------------------------------------
# The line.
# ---------------------------------------------------------------------------

def test_readings_are_converted() -> None:
    """The round trip: every field, against `units.convert` directly.

    Not against typed-in figures. A transcription of the expected value is a
    second implementation of the conversion, and two of those is the problem
    this upload exists to avoid rather than an extra check on it.
    """
    one = upload(location="kirchdorf", unit_system="metricwx")
    measurement, tags, fields, stamp = parse(one.line(US_RECORD))

    check("measurement", measurement, "weather")
    check("the location is a tag", tags, {"location": "kirchdorf"})
    check("the timestamp is the record's, in seconds",
          stamp, US_RECORD["dateTime"])

    for name, raw in US_RECORD.items():
        if name in ("dateTime", "usUnits"):
            continue
        stored, _group = units.unit_of(name, units.US)
        wanted, _group = units.unit_of(name, units.METRICWX)
        expected = units.convert(float(raw), stored, wanted)
        close_to(f"{name} converted {stored} -> {wanted}",
                 fields.get(name), float(expected), tol=1e-6)


def test_every_value_is_a_float() -> None:
    """A field's type is fixed on first write, for the life of the bucket.

    `outTemp=20` in January refuses `outTemp=20.1` in February with a field
    type conflict, and the whole batch goes with it. So a whole number has to
    leave here looking like a float.
    """
    line = upload().line({"dateTime": 1756308600, "usUnits": units.METRICWX,
                          "interval": 5, "outTemp": 20, "outHumidity": 61})
    body = line.split(" ")[1]
    for part in body.split(","):
        name, value = part.split("=")
        check(f"{name} is written as a float", "." in value or "e" in value, True)


def test_nan_and_infinity_are_dropped() -> None:
    """One of them rejects the batch it is in, not just the point.

    `derive.py` can produce either -- a division by a wind speed of zero is
    the usual road -- and the record it came from is otherwise good.
    """
    record = {"dateTime": 1756308600, "usUnits": units.METRICWX, "interval": 5,
              "outTemp": 20.0, "windchill": float("nan"),
              "heatindex": float("inf")}
    _m, _t, fields, _s = parse(upload().line(record))
    check("the good reading is there", "outTemp" in fields, True)
    check("NaN is gone", "windchill" in fields, False)
    check("infinity is gone", "heatindex" in fields, False)
    check("nothing infinite survived",
          all(math.isfinite(v) for v in fields.values()), True)


def test_a_location_with_spaces() -> None:
    """"Kirchdorf an der Amper" is an ordinary name and three separators."""
    one = upload(location="Kirchdorf, an der Amper=1")
    line = one.line(US_RECORD)
    _m, tags, _f, _s = parse(line)
    check("the tag survives its own punctuation",
          tags["location"], "Kirchdorf, an der Amper=1")
    # And the raw line really is escaped rather than accidentally parseable.
    check("the space is escaped in the line", "\\ " in line, True)
    check("the comma is escaped in the line", "\\," in line, True)


def test_a_record_with_no_readings_is_no_line() -> None:
    """An interval where quality control dropped everything leaves one.

    A measurement with no fields is a syntax error at the far end, so the
    batch it sits in fails -- including the records around it that were fine.
    """
    check("nothing to say, nothing said",
          upload().line({"dateTime": 1756308600, "usUnits": units.METRICWX}),
          None)
    check("a record with no timestamp is refused",
          upload().line({"usUnits": units.METRICWX, "outTemp": 20.0}), None)

    body, count = upload().body([
        {"dateTime": 1756308600, "usUnits": units.METRICWX},
        {"dateTime": 1756308900, "usUnits": units.METRICWX, "outTemp": 20.0},
    ])
    check("the empty one is left out of the batch", count, 1)
    check("and the batch is one line", len(body.splitlines()), 1)


def test_interval_is_written() -> None:
    """Every average in this project is weighted by it.

    A Grafana query cannot weight by a number it was never given, so leaving
    it out would guarantee the disagreement this upload exists to avoid.
    """
    _m, _t, fields, _s = parse(upload().line(US_RECORD))
    check("interval is a field", "interval" in fields, True)
    check("and it is the record's", fields["interval"], 5.0)


def test_the_two_apis_write_to_different_paths() -> None:
    two = upload(api="v2", org="acme", bucket="weewx")
    one = upload(api="v1", bucket="weewx", username="u", password="p",
                 token="")
    check("v2 writes to the v2 endpoint",
          two._write_path().startswith("/api/v2/write?"), True)
    check("v1 writes to the v1 endpoint",
          one._write_path().startswith("/write?"), True)
    fields = dict(urllib.parse.parse_qsl(one._write_path().split("?", 1)[1]))
    check("v1 names the database", fields.get("db"), "weewx")
    check("v1 carries the credentials", (fields.get("u"), fields.get("p")),
          ("u", "p"))
    check("both ask for seconds", fields.get("precision"), "s")
    check("v2 sends the token",
          two._headers().get("Authorization"), "Token t")


def test_a_bad_address_is_refused_at_setup() -> None:
    for bad, why in (("", "no address"), ("influxdb:8086", "no scheme"),
                     ("ftp://influxdb", "not http")):
        try:
            upload(url=bad)
        except ValueError:
            check(f"{why} is refused", True, True)
        else:
            check(f"{why} is refused", False, True)
    try:
        InfluxUpload(url="http://h:8086", token="t", bucket="")
    except ValueError:
        check("no bucket is refused", True, True)
    else:
        check("no bucket is refused", False, True)


# ---------------------------------------------------------------------------
# The server. Which answers mean stop, and which mean Tuesday.
# ---------------------------------------------------------------------------

class Fake(http.server.BaseHTTPRequestHandler):
    """An InfluxDB that answers however the test asked it to."""

    status = 204
    message = ""
    seen: ClassVar[list[tuple[str, str, str]]] = []

    #: What a query answers with. InfluxDB returns annotated CSV, and the
    #: annotation lines are what a naive parser trips over.
    csv = ""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        Fake.seen.append((self.path, self.headers.get("Authorization", ""), body))
        if "/query" in self.path and Fake.status in (200, 204):
            payload = Fake.csv.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        payload = Fake.message.encode()
        self.send_response(Fake.status)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


def serving() -> tuple[http.server.ThreadingHTTPServer, str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def test_answers(url: str) -> None:
    one = upload(url=url, location="kirchdorf")

    Fake.status, Fake.message, Fake.seen = 204, "", []
    posted = one.post([US_RECORD])
    check("a 204 is a send", (posted.sent, posted.ok), (1, True))
    check("and it says how far it got", posted.through, US_RECORD["dateTime"])
    check("the body was line protocol",
          Fake.seen[0][2].startswith("weather,location=kirchdorf "), True)

    # A wrong token answers 401 for ever. Retrying it every five minutes for
    # a year is how an account gets locked.
    Fake.status, Fake.message = 401, "unauthorized"
    try:
        one.post([US_RECORD])
    except Rejected as exc:
        check("401 is permanent", exc.permanent, True)
    else:
        check("401 is permanent", False, True)

    # A missing bucket is a configuration error -- but a compose file brings
    # InfluxDB up and creates the bucket in its own time, so it is not
    # believed straight away. Same reasoning as live.php answering 404.
    Fake.status, Fake.message = 404, "bucket not found"
    try:
        one.post([US_RECORD])
    except Rejected as exc:
        check("404 is permanent", exc.permanent, True)
        check("but not believed immediately", exc.after > 0, True)
    else:
        check("404 is permanent", False, True)

    # A 400 is our line protocol, not their trouble. It must not switch the
    # upload off: the next record may be fine, and the message names the line.
    Fake.status, Fake.message = 400, "unable to parse: field type conflict"
    posted = one.post([US_RECORD])
    check("400 does not raise", posted.ok, False)
    check("400 is recorded with its reason",
          "field type conflict" in posted.failures[0][1], True)

    Fake.status, Fake.message = 503, "overloaded"
    posted = one.post([US_RECORD])
    check("503 is Tuesday, not permanent", posted.ok, False)


def test_check_writes_nothing(url: str) -> None:
    """`check` has to test the credentials without inventing a reading.

    A test point in somebody's measurement series is a made-up observation
    that outlives the afternoon it was written on.
    """
    Fake.status, Fake.message, Fake.seen = 204, "", []
    answer = upload(url=url, bucket="weewx").check()
    check("check says it worked", "accepted" in answer, True)
    check("check sent exactly one request", len(Fake.seen), 1)
    check("with an empty body", Fake.seen[0][2], "")

    Fake.status, Fake.message = 401, "unauthorized"
    check("and reports a refusal", "refused" in upload(url=url).check(), True)


def test_a_backfill_is_batched(url: str) -> None:
    """Fifteen years is 1.6 million points, and one POST is not the way.

    The catch-up limit on the other uploads protects somebody else's free
    service. Here the database is the operator's own, so the limit is high
    and the batching is what keeps a request a request.
    """
    Fake.status, Fake.message, Fake.seen = 204, "", []
    records = [dict(US_RECORD, dateTime=1756308600 + 300 * i)
               for i in range(BATCH + 250)]
    posted = upload(url=url).post(records)
    check("everything went", posted.sent, len(records))
    check("in more than one request", len(Fake.seen), 2)
    check("the first is a full batch",
          len(Fake.seen[0][2].splitlines()), BATCH)
    check("the second is the rest",
          len(Fake.seen[1][2].splitlines()), 250)
    check("and it reports the newest record",
          posted.through, records[-1]["dateTime"])


def test_a_permanent_refusal_stops_the_rest(url: str) -> None:
    """Nothing after it would work either, and each one is a round trip."""
    Fake.status, Fake.message, Fake.seen = 401, "unauthorized", []
    records = [dict(US_RECORD, dateTime=1756308600 + 300 * i)
               for i in range(BATCH * 2 + 10)]
    try:
        upload(url=url).post(records)
    except Rejected:
        pass
    check("it stopped at the first batch", len(Fake.seen), 1)


# ---------------------------------------------------------------------------
# Counting both ends.
# ---------------------------------------------------------------------------

#: What InfluxDB actually sends back, annotation lines and all. Written out
#: rather than shortened: the datatype and group rows above the header are
#: exactly what a parser that splits on commas and takes row two gets wrong.
COUNTS_CSV = """#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,dateTime:RFC3339,long
#group,false,false,true,true,false,false
#default,_result,,,,,
,result,table,_start,_stop,_time,_value
,_result,0,2026-08-20T00:00:00Z,2026-08-23T00:00:00Z,2026-08-20T00:00:00Z,288
,_result,0,2026-08-20T00:00:00Z,2026-08-23T00:00:00Z,2026-08-21T00:00:00Z,287
,_result,0,2026-08-20T00:00:00Z,2026-08-23T00:00:00Z,2026-08-22T00:00:00Z,0
"""


def test_counting_reads_the_annotated_csv(url: str) -> None:
    Fake.status, Fake.csv, Fake.seen = 200, COUNTS_CSV, []
    got = upload(url=url, location="kirchdorf").counts(
        1755648000, 1755907200, 86400, token="read-only")

    check("three windows", len(got), 3)
    check("the counts", sorted(got.values()), [0, 287, 288])
    check("an empty window is kept, not dropped",
          0 in got.values(), True)
    check("the keys are seconds, not nanoseconds",
          all(1_000_000_000 < k < 3_000_000_000 for k in got), True)
    check("oldest first", list(got) == sorted(got), True)

    path, authorization, flux = Fake.seen[0]
    check("it asked the query endpoint", "/api/v2/query" in path, True)
    check("with the token it was given", authorization, "Token read-only")
    check("counting the field every record has",
          '_field == "interval"' in flux, True)
    check("for this location only",
          'r.location == "kirchdorf"' in flux, True)
    check("stamped with the window start, not its end",
          'timeSrc: "_start"' in flux, True)
    check("and empty windows are asked for",
          "createEmpty: true" in flux, True)


def test_counting_with_a_write_token_says_so(url: str) -> None:
    """A 401 here is a missing permission, not an outage.

    The page tells the operator to give Grafana a read-only token, so the one
    in the configuration is a write token, and a write token cannot count.
    "InfluxDB answered 401" would send somebody to look at the network.
    """
    Fake.status, Fake.message = 401, "unauthorized"
    try:
        upload(url=url).counts(0, 86400)
    except Rejected as exc:
        check("it says a token that reads is needed",
              "cannot count" in str(exc), True)
        check("and does not retry it", exc.permanent, True)
    else:
        check("a write token is refused", False, True)


def test_counting_without_a_location_asks_for_all(url: str) -> None:
    Fake.status, Fake.csv, Fake.seen = 200, COUNTS_CSV, []
    upload(url=url, location="").counts(0, 86400)
    check("no location filter", "r.location" in Fake.seen[0][2], False)


def test_both_sides_cut_the_windows_in_the_same_place() -> None:
    """The comparison is worthless if the two group differently.

    A day grouped on local midnight against a window cut from the epoch
    compares one day with parts of two, and reports a drift on a database
    where nothing is wrong. Both sides do plain epoch arithmetic, and this
    checks it by giving them the same records.
    """
    import sqlite3

    from weewx_evo.cli import _archive_counts

    where = Path(tempfile.mkdtemp()) / "weewx.sdb"
    conn = sqlite3.connect(where)
    conn.execute("CREATE TABLE archive (dateTime INTEGER PRIMARY KEY, "
                 "usUnits INTEGER, interval INTEGER, outTemp REAL)")
    # Three days, one record an hour, and a gap on the middle day.
    day = 86400
    start = 1755648000            # a multiple of a day, so a window starts here
    stamps = []
    for offset in range(0, 3 * day, 3600):
        if day <= offset < 2 * day and (offset // 3600) % 2:
            continue              # every other hour of day two is missing
        stamps.append(start + offset)
    conn.executemany("INSERT INTO archive VALUES (?, 16, 60, 20.0)",
                     [(t,) for t in stamps])
    conn.commit()
    conn.close()

    got = _archive_counts(where, start, start + 3 * day, day)
    check("three windows", len(got), 3)
    check("the first day is whole", got[start], 24)
    check("the second is half", got[start + day], 12)
    check("the third is whole", got[start + 2 * day], 24)
    check("and the keys are window starts",
          all(k % day == 0 for k in got), True)

    # The other side has to cut on the same boundaries. Not the same figures:
    # the fixture and the recorded CSV are from different weeks, and it is
    # the *grid* they have to agree on. A day grouped on local midnight would
    # land on 1:00 or 2:00 here and every window would be off by one.
    server, url = serving()
    Fake.status, Fake.csv, Fake.seen = 200, COUNTS_CSV, []
    try:
        theirs = upload(url=url).counts(start, start + 3 * day, day)
    finally:
        server.shutdown()
        server.server_close()
    check("InfluxDB cuts on the same grid",
          all(k % day == 0 for k in theirs), True)
    check("and both are counting in the same width",
          {b - a for a, b in zip(sorted(theirs), sorted(theirs)[1:],
                                 strict=False)},
          {b - a for a, b in zip(sorted(got), sorted(got)[1:], strict=False)})


# ---------------------------------------------------------------------------
# After a rebuild.
# ---------------------------------------------------------------------------

#: One upload that holds a copy of the archive and one that does not. The
#: point of the pair: a rebuild has to reach the first and leave the second
#: alone, and only having one of them would pass either way.
#:
#: The InfluxDB address is a port nothing listens on. Nothing here posts --
#: the command winds a mark back, and sending is somebody else's turn.
A_COPY_AND_A_SERVICE = """archive_db = "weewx.sdb"
live_db = "live.sdb"
interval = "5m"

[uploads.influx]
kind = "influx"
url = "http://127.0.0.1:1"
token = "t"
org = "o"
bucket = "weewx"
location = "here"

[uploads.wu]
kind = "wunderground"
station = "IBAYERN1"
password = "p"
"""

def test_progress_only_moves_back_when_told() -> None:
    """`sent` never goes backwards, and `rewind` is the one caller that does.

    Both directions matter. A service that accepts a backfilled record from an
    hour ago has not un-accepted the current one, so `sent` refusing to move
    back is what stops the whole hour going again every turn -- and that same
    refusal is what leaves a corrected span unsent.
    """
    from weewx_evo.uploads.progress import Progress

    progress = Progress(Path(tempfile.mkdtemp()) / "uploads.json")
    progress.sent("influx", 2000)
    progress.sent("influx", 1000)
    check("sent does not move back", progress.through("influx"), 2000)

    check("rewind does", progress.rewind("influx", 1000), True)
    check("and says where it got to", progress.through("influx"), 1000)
    check("winding forward is not rewinding",
          progress.rewind("influx", 5000), False)
    check("so the mark is untouched", progress.through("influx"), 1000)

    # Survives the file, because the service that acts on it is another
    # process and may not start for an hour.
    progress.save()
    check("and it is written down",
          Progress(progress.path).through("influx"), 1000)


def test_a_rebuild_winds_back_the_copy_and_not_the_services() -> None:
    """The whole point, run for real through the command.

    Everything up to `stations.toml` was checked once before and nothing
    checked whether the driver ever saw it. So this builds an archive, runs
    `weewx-evo rebuild`, and reads the file the uploads keep.
    """
    import subprocess

    from weewx_evo.db.archive import ArchiveStore
    from weewx_evo.db.live import LiveStore, Packet
    from weewx_evo.uploads.progress import Progress

    where = Path(tempfile.mkdtemp())
    (where / "evo.toml").write_text(A_COPY_AND_A_SERVICE, encoding="utf-8")

    # The archive, made the way this program makes one. A hand-written
    # `CREATE TABLE archive` was the first version and is not enough: an
    # archive is also its daily summaries and their metadata table, and the
    # rebuild fails on the one nobody thought of.
    ArchiveStore(where / "weewx.sdb").close()

    # Packets to rebuild from. Two intervals' worth, so the rebuild has
    # something to do and reports a number.
    start = 1755648000
    with LiveStore(where / "live.sdb", interval_seconds=300) as live:
        for offset in range(0, 600, 30):
            live.add(Packet(dateTime=start + offset, usUnits=16,
                            data={"outTemp": 20.0 + offset / 100},
                            source="test", kind="loop"))

    marks = Progress(where / "uploads.json")
    for name in ("influx", "wu"):
        marks.sent(name, start + 10_000)
    marks.save()

    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).resolve().parent.parent / "src"),
         environment.get("PYTHONPATH", "")])
    environment["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run(
        [sys.executable, "-m", "weewx_evo.cli", "rebuild",
         "--config", "evo.toml", str(start - 1), str(start + 600)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=where, env=environment, check=False)
    check("the rebuild succeeds", done.returncode, 0)

    after = Progress(where / "uploads.json")
    check("the copy is wound back to the span",
          after.through("influx"), start - 1)
    check("the weather service is left alone",
          after.through("wu"), start + 10_000)
    check("and it says which, and why",
          "influx" in done.stdout and "copy" in done.stdout, True)


def test_no_resend_leaves_the_marks_alone() -> None:
    """A span rebuilt for a reason that does not change the numbers."""
    import subprocess

    from weewx_evo.db.archive import ArchiveStore
    from weewx_evo.db.live import LiveStore, Packet
    from weewx_evo.uploads.progress import Progress

    where = Path(tempfile.mkdtemp())
    (where / "evo.toml").write_text(
        A_COPY_AND_A_SERVICE.split("[uploads.wu]")[0], encoding="utf-8")
    ArchiveStore(where / "weewx.sdb").close()

    start = 1755648000
    with LiveStore(where / "live.sdb", interval_seconds=300) as live:
        for offset in range(0, 600, 30):
            live.add(Packet(dateTime=start + offset, usUnits=16,
                            data={"outTemp": 20.0}, source="test"))

    marks = Progress(where / "uploads.json")
    marks.sent("influx", start + 10_000)
    marks.save()

    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).resolve().parent.parent / "src"),
         environment.get("PYTHONPATH", "")])
    subprocess.run(
        [sys.executable, "-m", "weewx_evo.cli", "rebuild", "--no-resend",
         "--config", "evo.toml", str(start - 1), str(start + 600)],
        capture_output=True, text=True, cwd=where, env=environment,
        check=False)
    check("--no-resend leaves the mark",
          Progress(where / "uploads.json").through("influx"), start + 10_000)


# ---------------------------------------------------------------------------
# The forecast.
# ---------------------------------------------------------------------------

def a_store(tmp: Path, name: str = "forecast",
            archive: str = "default") -> object:
    """A forecast store with one run of hours and days in it, for one series."""
    from weewx_evo.forecast import Day, Moment, Reading
    from weewx_evo.forecast.store import ForecastStore

    base = 1756308600
    reading = Reading(
        source="openmeteo", issued=base,
        hours=[Moment(dateTime=base + 3600 * n, usUnits=units.METRICWX,
                        outTemp=10.0 + n, outHumidity=60.0,
                        windSpeed=3.0, code=61 if n % 2 else 0)
                 for n in range(6)],
        days=[Day(dateTime=base + 86400 * n, usUnits=units.METRICWX,
                  tempMax=18.0 + n, tempMin=6.0 + n, rain=1.5,
                  sunrise=base + 86400 * n + 21600,
                  sunset=base + 86400 * n + 72000, code=3)
              for n in range(3)])
    store = ForecastStore(tmp / f"{name}.sdb")
    store.store(reading, base, archive)
    return store


def test_the_forecast_is_its_own_measurement(tmp: Path) -> None:
    """A predicted `outTemp` and a measured one are two different things.

    In one measurement they are one series: a panel could not draw them
    apart, and nothing would stop an average being taken over the pair.
    """
    store = a_store(tmp)
    lines = upload(location="kirchdorf").forecast_lines(store)
    check("every hour and every day is a point", len(lines), 9)

    names = {parse(line)[0] for line in lines}
    check("all under one name", names, {"weather_forecast"})

    kinds = [parse(line)[1].get("kind") for line in lines]
    check("six hours", kinds.count("hour"), 6)
    check("three days", kinds.count("day"), 3)
    check("the source is a tag",
          {parse(line)[1].get("source") for line in lines}, {"openmeteo"})
    check("and the location comes along",
          {parse(line)[1].get("location") for line in lines}, {"kirchdorf"})
    store.close()


def test_a_forecast_point_carries_the_hour_it_describes(tmp: Path) -> None:
    """Not the hour it was downloaded.

    A forecast stamped with its fetch time is a line that ends at "now",
    which is the one thing a forecast is not.
    """
    store = a_store(tmp)
    lines = [line for line in upload().forecast_lines(store)
             if parse(line)[1].get("kind") == "hour"]
    stamps = sorted(parse(line)[3] for line in lines)
    check("the hours run forward from the first",
          stamps, [1756308600 + 3600 * n for n in range(6)])
    check("an hour apart", stamps[1] - stamps[0], 3600)
    store.close()


def test_a_forecast_is_converted_like_a_record(tmp: Path) -> None:
    """Same arithmetic, not a second copy of it.

    A source producing metric and a bucket set to US is the same problem as a
    Fahrenheit console and a Celsius page, and it has one answer here.
    """
    store = a_store(tmp)
    line = next(line for line in upload(unit_system="us").forecast_lines(store)
                if parse(line)[1].get("kind") == "hour")
    _m, _t, fields, _s = parse(line)
    wanted = units.convert(10.0, units.unit_of("outTemp", units.METRICWX)[0],
                           units.unit_of("outTemp", units.US)[0])
    close_to("the first hour, in Fahrenheit", fields.get("outTemp"),
             float(wanted), tol=1e-6)
    store.close()


def test_the_code_goes_too_so_an_icon_can_hang_on_it(tmp: Path) -> None:
    """The WMO code is what a panel turns into a picture.

    Written as a number like everything else: a field's type is fixed on
    first write, and a code arriving once as an integer refuses every later
    batch that has it as a float.
    """
    store = a_store(tmp)
    lines = [line for line in upload().forecast_lines(store)
             if parse(line)[1].get("kind") == "hour"]
    codes = [parse(line)[2].get("code") for line in lines]
    check("every hour has one", [c for c in codes if c is None], [])
    check("and they are the source's own", sorted(set(codes)), [0.0, 61.0])

    body = lines[0].split(" ")[1]
    for part in body.split(","):
        name, value = part.split("=")
        check(f"{name} is a float", "." in value or "e" in value, True)
    store.close()


def test_one_source_at_a_time(tmp: Path) -> None:
    """Two sources configured at once must not double every point."""
    from weewx_evo.forecast import Moment, Reading

    store = a_store(tmp, "two")
    base = 1756308600
    store.store(Reading(source="dwd", issued=base,
                        hours=[Moment(dateTime=base, usUnits=units.METRICWX,
                                        outTemp=9.0)]), base, "default")
    check("both are in the store", sorted(store.sources("default")),
          ["dwd", "openmeteo"])

    one = upload().forecast_lines(store, ("dwd",))
    check("asked for one, one comes back",
          {parse(line)[1].get("source") for line in one}, {"dwd"})
    check("and that is the whole of that source", len(one), 1)
    store.close()


def test_a_fetch_reaches_the_upload(url: str, tmp: Path) -> None:
    """The wiring, end to end: a source stores a run and points arrive.

    The fault this is here for has no symptom. `mirror_forecast` builds the
    callback and `build` hands it to every source, and a source that fetched
    without one looks exactly like a source that fetched with one -- right up
    until somebody asks Grafana for tomorrow and the panel is empty. That is
    the same hole the six push protocols sat in: every test checked as far as
    the file, none checked that the thing downstream ever saw it.
    """
    from weewx_evo import cli
    from weewx_evo.forecast import Moment, Reading
    from weewx_evo.forecast.runner import Scheduled
    from weewx_evo.forecast.store import ForecastStore

    base = 1756308600

    class Source:
        every = 3600

        def fetch(self, _place):
            return Reading(source="test", issued=base,
                           hours=[Moment(dateTime=base,
                                           usUnits=units.METRICWX,
                                           outTemp=11.0, code=3)])

    class Holder:
        uploads: ClassVar[list] = [
            type("S", (), {"name": "influx",
                           "upload": upload(url=url,
                                            location="kirchdorf")})()]

    Fake.status, Fake.message, Fake.seen = 204, "", []
    store = ForecastStore(tmp / "wired.sdb")
    source = Scheduled("test", Source(), None, store,
                       cli.mirror_forecast(Holder(), store))
    source.run()
    check("the run was stored", len(store.hours("default", "test")), 1)
    check("and it reached the database", len(Fake.seen), 1)
    check("as a forecast point",
          "weather_forecast" in Fake.seen[0][2], True)
    store.close()


def test_each_place_reaches_its_own_upload(url: str, tmp: Path) -> None:
    """Two places, two uploads, and neither gets the other's forecast.

    Everything an upload writes carries its own `location`. So a forecast
    sent through the wrong one is not merely surplus: it lands on the right
    place's measurement, with the right place's tags, on the same timestamps
    -- and InfluxDB keeps the last write. The panel shows one place's hours
    labelled as the other's, and nothing in the data says which happened.

    The reads were already keyed on the series when this was written. Only
    the sending was not, which is why it read as correct.
    """
    from weewx_evo import cli
    from weewx_evo.forecast import Moment, Reading
    from weewx_evo.forecast.runner import Scheduled
    from weewx_evo.forecast.store import ForecastStore

    base = 1756308600

    def source_of(temp: float) -> object:
        class Source:
            every = 3600

            def fetch(self, _place):
                # The same entry name for both, which the store allows on
                # purpose: somebody with two fields calls both of them
                # `here`. Tagged only by source, the two would be one series.
                return Reading(source="here", issued=base,
                               hours=[Moment(dateTime=base,
                                             usUnits=units.METRICWX,
                                             outTemp=temp, code=3)])
        return Source()

    def upload_for(place: str) -> object:
        return type("S", (), {"name": f"influx-{place}", "archive": place,
                              "upload": upload(url=url, location=place)})()

    class Holder:
        uploads: ClassVar[list] = [upload_for("default"),
                                   upload_for("nordfeld")]

    Fake.status, Fake.message, Fake.seen = 204, "", []
    store = ForecastStore(tmp / "two-places.sdb")
    try:
        for place, temp in (("default", 11.0), ("nordfeld", 4.0)):
            Scheduled("here", source_of(temp), None, store,
                      cli.mirror_forecast(Holder(), store),
                      archive=place).run()

        # Line by line rather than body by body: a body carrying two points
        # is the fault itself, and reading one body as one point turns a
        # measurable answer into an unpacking error that names nothing.
        points = [parse(line) for _, _, body in Fake.seen
                  for line in body.splitlines() if line.strip()]
        check("one point per place, and no more", len(points), 2)
        check("each under its own location",
              sorted(tags.get("location", "") for _, tags, _, _ in points),
              ["default", "nordfeld"])

        # And the numbers went with the labels rather than beside them.
        got = {tags.get("location"): fields.get("outTemp")
               for _, tags, fields, _ in points}
        check("the north's reading is the north's", got.get("nordfeld"), 4.0)
        check("and the default's is its own", got.get("default"), 11.0)
    finally:
        store.close()


def test_an_unreachable_database_does_not_stop_the_forecast(tmp: Path) -> None:
    """A source that fetched has done its job.

    The alternative is a forecast that stops updating because a database
    somewhere is down, which is a failure to avoid rather than one to add.
    """
    from weewx_evo import cli
    from weewx_evo.forecast import Moment, Reading
    from weewx_evo.forecast.runner import Scheduled
    from weewx_evo.forecast.store import ForecastStore

    base = 1756308600

    def refuse(*_a: object, **_k: object) -> int:
        raise OSError("connection refused")

    class Source:
        every = 3600

        def fetch(self, _place):
            return Reading(source="dead", issued=base,
                           hours=[Moment(dateTime=base,
                                           usUnits=units.METRICWX,
                                           outTemp=11.0)])

    class Broken:
        uploads: ClassVar[list] = [type("S", (), {
            "name": "influx",
            "upload": type("U", (), {"post_forecast": refuse})()})()]

    store = ForecastStore(tmp / "dead.sdb")
    source = Scheduled("dead", Source(), None, store,
                       cli.mirror_forecast(Broken(), store))
    source.run()
    check("the forecast was stored anyway",
          len(store.hours("default", "dead")), 1)
    check("the source is not blocked", source.blocked, "")
    check("nor counted as a failure", source.failures, 0)
    store.close()


def main() -> int:
    test_readings_are_converted()
    test_every_value_is_a_float()
    test_nan_and_infinity_are_dropped()
    test_a_location_with_spaces()
    test_a_record_with_no_readings_is_no_line()
    test_interval_is_written()
    test_the_two_apis_write_to_different_paths()
    test_a_bad_address_is_refused_at_setup()
    test_both_sides_cut_the_windows_in_the_same_place()
    test_progress_only_moves_back_when_told()
    test_a_rebuild_winds_back_the_copy_and_not_the_services()
    test_no_resend_leaves_the_marks_alone()

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        test_the_forecast_is_its_own_measurement(tmp)
        test_a_forecast_point_carries_the_hour_it_describes(tmp)
        test_a_forecast_is_converted_like_a_record(tmp)
        test_the_code_goes_too_so_an_icon_can_hang_on_it(tmp)
        test_one_source_at_a_time(tmp)
        test_an_unreachable_database_does_not_stop_the_forecast(tmp)

    server, url = serving()
    try:
        test_answers(url)
        test_check_writes_nothing(url)
        test_a_backfill_is_batched(url)
        test_a_permanent_refusal_stops_the_rest(url)
        test_counting_reads_the_annotated_csv(url)
        test_counting_with_a_write_token_says_so(url)
        test_counting_without_a_location_asks_for_all(url)
        with tempfile.TemporaryDirectory() as raw:
            test_a_fetch_reaches_the_upload(url, Path(raw))
        with tempfile.TemporaryDirectory() as raw:
            test_each_place_reaches_its_own_upload(url, Path(raw))
    finally:
        server.shutdown()
        server.server_close()

    if FAILURES:
        print(f"{len(FAILURES)} of {CHECKS} checks failed:\n")
        for failure in FAILURES:
            print(f"  {failure}\n")
        return 1
    print(f"influx: {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

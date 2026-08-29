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
import sys
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

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        Fake.seen.append((self.path, self.headers.get("Authorization", ""), body))
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


def main() -> int:
    test_readings_are_converted()
    test_every_value_is_a_float()
    test_nan_and_infinity_are_dropped()
    test_a_location_with_spaces()
    test_a_record_with_no_readings_is_no_line()
    test_interval_is_written()
    test_the_two_apis_write_to_different_paths()
    test_a_bad_address_is_refused_at_setup()

    server, url = serving()
    try:
        test_answers(url)
        test_check_writes_nothing(url)
        test_a_backfill_is_batched(url)
        test_a_permanent_refusal_stops_the_rest(url)
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

"""InfluxDB: the archive again, in something built to be asked questions.

Every other upload in this package sends readings to somebody else's weather
service. This one sends them to a database the operator runs, and the reason
is Grafana: a page rendered from a template belongs to *one* archive, and the
question that makes somebody install Grafana is "all five locations on one
axis".

**The tag is the archive, not the station.** A station is what uploads; an
archive is a measurement series for one place, and by the time a record
exists the stations that fed it have already been merged (`sources.py`) or
moved out of each other's way (`roles.py`). So a record has no station, and
tagging one on would be inventing a fact. Five locations are five archives,
which is exactly the axis Grafana is wanted for -- one upload per archive,
each with its own `location`.

**A second store is a second truth, and that is the real cost.** A record
corrected by a rebuild has to reach here too, or Grafana shows one number and
the station's own page shows another -- the mistake `chartdata.py` describes
one storey down, except now two *stores* disagree rather than two sums.
`weewx-evo upload check --compare` is the answer to "did it": it counts both
ends rather than trusting that every write landed.

Four traps, all of them the kind that answers 400 and looks like a network
problem:

**A field is one type for ever.** Write `outTemp=20` on a cold morning and
InfluxDB records an integer; write `20.1` an hour later and the whole batch
is refused with a field type conflict, for the rest of the bucket's life. So
every reading goes out as a float, including the ones that are whole numbers,
and `interval` with them.

**NaN and infinity are not numbers InfluxDB takes.** A derived reading can be
either -- a division by a wind speed of zero is the usual way -- and one of
them in a batch of five hundred rejects all five hundred. They are dropped
here, like any other absent reading.

**A station name has spaces in it.** "Kirchdorf an der Amper" is a perfectly
ordinary `location`, and a space is what separates the tags from the fields
in line protocol. Escaping is not decoration; see `_tag`.

**Units are not in the database, here no more than in SQLite.** A console
reporting Fahrenheit writes 68.2 and a Grafana axis says degrees Celsius --
the same fault that reached a published page twice through the live push. So
readings are converted on the way out, into a system that is *set* rather
than inherited: changing it later puts a step in the middle of the series
that nothing downstream can see.
"""

from __future__ import annotations

import datetime
import logging
import math
import time
import urllib.parse
from typing import Any

from .. import units
from . import BaseUpload, Posted, Readings, Rejected, request, when_options

log = logging.getLogger(__name__)


def _epoch(stamp: str) -> int:
    """An RFC 3339 timestamp as seconds. InfluxDB answers in nanoseconds.

    `fromisoformat` handles the nine-digit fraction from Python 3.11 on, and
    the trailing Z from 3.11 as well; both are older than this project.
    """
    return int(datetime.datetime.fromisoformat(stamp).timestamp())


#: Columns that describe the record rather than the weather. `interval` is
#: deliberately *not* here: an average weighted by it is what this project
#: computes everywhere else, and a Grafana query cannot weight by a number it
#: was never given.
NOT_A_READING = ("dateTime", "usUnits")

#: How many points go in one request. A backfill of fifteen years is around
#: 1.6 million of them, and one POST of that size is a memory figure rather
#: than a request. Five thousand is a few hundred kilobytes.
BATCH = 5000


def _escape(text: str, also: str = "") -> str:
    """Line protocol escaping for a measurement, tag or field name.

    Commas, equals signs and spaces are what separate the parts of a line, so
    each has to be escaped where it appears inside one. A backslash is left
    alone on purpose -- InfluxDB treats it as an escape character only before
    one of those, and doubling them here would put literal backslashes in the
    tag. The one that does break is a *trailing* backslash, which escapes the
    separator that follows it, so that one goes.
    """
    text = str(text).rstrip("\\")
    for char in "," + also:
        text = text.replace(char, "\\" + char)
    return text


def _tag(text: str) -> str:
    """A tag key or value: commas, equals signs and spaces all separate."""
    return _escape(text, "= ")


def _measurement(text: str) -> str:
    """A measurement name: a comma ends it, a space starts the fields."""
    return _escape(text, " ")


class InfluxUpload(BaseUpload):
    """Writes archive records into InfluxDB as line protocol."""

    label = "InfluxDB"
    summary = ("The archive in a time series database, so Grafana can ask it "
               "questions. One upload per archive.")

    #: The whole point of this one. Every other upload backfills against a
    #: free service's patience; this is the operator's own database, and
    #: fifteen years of it is the reason to have it.
    backfill = True
    catch_up_limit = 5000
    #: A point is replaced by its timestamp and tags, so a rebuilt span
    #: overwrites cleanly. The alternative is two stores that disagree about
    #: exactly the records somebody went to the trouble of correcting.
    resend_after_rebuild = True

    def __init__(self, url: str = "", api: str = "v2", token: str = "",
                 org: str = "", bucket: str = "", username: str = "",
                 password: str = "", measurement: str = "weather",
                 location: str = "", unit_system: str = "metricwx",
                 trigger: str = "record", every: int = 300,
                 catch_up: int = 5000, timeout: int = 30) -> None:
        self.url = str(url or "").strip().rstrip("/")
        self.api = str(api or "v2").strip().lower()
        self.token = str(token or "").strip()
        self.org = str(org or "").strip()
        self.bucket = str(bucket or "").strip()
        self.username = str(username or "").strip()
        self.password = str(password or "").strip()
        self.measurement = str(measurement or "weather").strip() or "weather"
        self.location = str(location or "").strip()
        self.trigger = trigger
        self.every = int(every)
        self.catch_up_limit = int(catch_up)
        self.timeout = int(timeout)

        self.system = {"us": units.US, "metric": units.METRIC,
                       "metricwx": units.METRICWX}.get(
                           str(unit_system or "metricwx").lower(),
                           units.METRICWX)

        if not self.url:
            raise ValueError("the address of the InfluxDB server is needed, "
                             "for example http://influxdb:8086")
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"{self.url!r} is not an http:// or https:// "
                             f"address")
        self.host = parsed.hostname
        self.port = parsed.port
        self.tls = parsed.scheme == "https"
        self.prefix = parsed.path.rstrip("/")

        if not self.bucket:
            raise ValueError("a bucket (InfluxDB 2) or database (InfluxDB 1) "
                             "is needed")
        if self.api == "v2" and not self.token:
            raise ValueError("an API token is needed for the InfluxDB 2 API")

    # -- the wire ---------------------------------------------------------

    def _write_path(self) -> str:
        """Where a write goes, which is the one thing the two APIs differ in.

        InfluxDB 1.8 also answers `/api/v2/write`, but only where somebody
        enabled the compatibility mapping, and a 404 there reads like a wrong
        bucket. So each version is asked in its own language.
        """
        if self.api == "v1":
            fields = {"db": self.bucket, "precision": "s"}
            if self.username:
                fields["u"] = self.username
                fields["p"] = self.password
            return f"{self.prefix}/write?{urllib.parse.urlencode(fields)}"
        fields = {"bucket": self.bucket, "precision": "s"}
        if self.org:
            fields["org"] = self.org
        return f"{self.prefix}/api/v2/write?{urllib.parse.urlencode(fields)}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        if self.api == "v2":
            headers["Authorization"] = f"Token {self.token}"
        elif self.token:
            # A 1.x server behind a proxy that wants a bearer token. Rare,
            # and free to allow.
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def _post(self, body: str) -> None:
        """One write. Raises `Rejected`, says nothing on success."""
        status, text = request(
            self.host, self._write_path(), method="POST",
            body=body.encode("utf-8"), headers=self._headers(),
            tls=self.tls, port=self.port, timeout=self.timeout)

        if status in (200, 204):
            return
        if status in (401, 403):
            raise Rejected(f"InfluxDB refused the credentials: {text[:160]}",
                           permanent=True)
        if status == 404:
            # A bucket that does not exist yet is a configuration error, but
            # not necessarily one that has happened *yet*: a compose file
            # brings InfluxDB up and creates the bucket in its own time. Same
            # reasoning as `live.php` answering 404 before its first export --
            # a wrong name answers 404 for ever, a missing one stops.
            raise Rejected(
                f"InfluxDB has no {'database' if self.api == 'v1' else 'bucket'} "
                f"{self.bucket!r}: {text[:160]}", permanent=True, after=3600)
        if status == 400:
            # Our line protocol, not their trouble. Worth the whole message:
            # InfluxDB names the offending line, and that is the only way to
            # find a field type conflict.
            raise Rejected(f"InfluxDB rejected the batch: {text[:400]}")
        if status == 413:
            raise Rejected(f"the batch was too large for InfluxDB ({len(body)} "
                           f"bytes); lower the catch-up limit")
        raise Rejected(f"InfluxDB answered {status}: {text[:160]}")

    # -- the readings -----------------------------------------------------

    def line(self, record: dict) -> str | None:
        """One record as one line of line protocol, or None if it holds none.

        A record with a timestamp and nothing else happens: an interval in
        which every reading failed quality control leaves one. Writing the
        measurement with no fields is a syntax error at the far end, so it is
        skipped here where the reason is known.
        """
        readings = Readings(record)
        if not readings.ts:
            return None

        fields: list[str] = []
        for name, raw in sorted(record.items()):
            if name in NOT_A_READING or raw is None:
                continue
            wanted, _group = units.unit_of(name, self.system)
            value = readings.get(name, wanted)
            if value is None:
                continue
            # NaN and infinity reject the whole batch, not just the point.
            # `derive.py` can produce either from a division by a zero wind
            # speed, and the record it came from is otherwise good.
            if not math.isfinite(value):
                continue
            # A float always, never an int. InfluxDB fixes a field's type on
            # first write, so `outTemp=20` in January is what refuses
            # `outTemp=20.1` in every month after it.
            fields.append(f"{_tag(name)}={float(value)}")

        if not fields:
            return None

        tags = ""
        if self.location:
            tags = f",location={_tag(self.location)}"
        return (f"{_measurement(self.measurement)}{tags} "
                f"{','.join(fields)} {readings.ts}")

    def body(self, records: list[dict]) -> tuple[str, int]:
        """A batch as text, and how many records went into it."""
        lines = [line for line in (self.line(r) for r in records) if line]
        return "\n".join(lines), len(lines)

    # -- the interface ----------------------------------------------------

    def post(self, records: list[dict]) -> Posted:
        result = Posted()
        started = time.monotonic()
        for start in range(0, len(records), BATCH):
            batch = records[start:start + BATCH]
            body, count = self.body(batch)
            if not count:
                result.skipped += len(batch)
                continue
            try:
                self._post(body)
            except Rejected as exc:
                if exc.permanent:
                    # Nothing here will work until somebody changes it, and
                    # the batches after this one would fail the same way.
                    raise
                result.failures.append((str(batch[0].get("dateTime")), str(exc)))
                break
            result.sent += count
            result.skipped += len(batch) - count
            result.through = int(batch[-1].get("dateTime") or 0)
        result.seconds = time.monotonic() - started
        return result

    def check(self) -> str:
        """Ask the server, write nothing.

        A write with an empty body: it goes through authentication and the
        bucket lookup and then has no points to store. That tests the three
        things that are actually wrong when this does not work -- the address,
        the credentials, the bucket -- without putting a made-up reading in
        somebody's measurement series, which is what a test point would be.
        """
        try:
            self._post("")
        except Rejected as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"could not reach {self.url}: {exc}"
        where = "database" if self.api == "v1" else "bucket"
        return (f"InfluxDB accepted the credentials and the {where} "
                f"{self.bucket!r}.")

    # -- counting what is there -------------------------------------------

    def counts(self, start: int, stop: int, every: int = 86400,
               token: str = "") -> dict[int, int]:
        """How many points this bucket holds per window, oldest first.

        The other half of "a second store is a second truth". Trusting that
        every write landed is how the two drift, and a drift nobody measured
        shows up as a Grafana chart that disagrees with the station's own
        page -- with no way to tell which one is wrong.

        Counted on `interval`, because that field is in every archive record
        this program writes. Counting on `outTemp` would count the records a
        thermometer was working for.

        Reading needs a token that reads. The upload's own is a write token
        if the operator followed the advice on the page, so `token` is here
        and a 401 says which one is missing rather than looking like an
        outage.
        """
        window = f"{max(60, int(every))}s"
        flux = "\n".join([
            f'from(bucket: "{self.bucket}")',
            f"  |> range(start: {int(start)}, stop: {int(stop)})",
            f'  |> filter(fn: (r) => r._measurement == "{self.measurement}")',
            '  |> filter(fn: (r) => r._field == "interval")',
            *([f'  |> filter(fn: (r) => r.location == "{self.location}")']
              if self.location else []),
            # timeSrc "_start" rather than the default: aggregateWindow
            # stamps a window with its *end*, and subtracting the width back
            # off is wrong for the last one, which the range cuts short.
            (f"  |> aggregateWindow(every: {window}, fn: count, "
             f'createEmpty: true, timeSrc: "_start")'),
            '  |> keep(columns: ["_time", "_value"])',
        ])

        path = f"{self.prefix}/api/v2/query"
        if self.org:
            path += f"?org={urllib.parse.quote(self.org)}"
        headers = {"Content-Type": "application/vnd.flux",
                   "Accept": "application/csv",
                   "Authorization": f"Token {token or self.token}"}
        status, text = request(self.host, path, method="POST",
                               body=flux.encode("utf-8"), headers=headers,
                               tls=self.tls, port=self.port,
                               timeout=self.timeout)
        if status in (401, 403):
            raise Rejected(
                "InfluxDB refused the token for reading. A write-only token "
                "cannot count; pass one that reads.", permanent=True)
        if status != 200:
            raise Rejected(f"InfluxDB answered {status}: {text[:200]}")

        found: dict[int, int] = {}
        header: list[str] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            cells = line.split(",")
            if len(cells) > 1 and cells[1] == "result":
                header = cells
                continue
            if not header:
                continue
            row = dict(zip(header, cells, strict=False))
            when, value = row.get("_time"), row.get("_value")
            if not when or value in (None, ""):
                continue
            stamp = _epoch(when)
            found[stamp] = found.get(stamp, 0) + int(float(value))
        return dict(sorted(found.items()))

    def status(self) -> dict[str, Any]:
        # No token, no password. Everything here is safe to print on a page.
        return {"url": self.url, "api": self.api, "bucket": self.bucket,
                "measurement": self.measurement, "location": self.location,
                "units": units.name(self.system)}

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("The server", "", (
                Option("url", "Address", kind="text", required=True,
                       placeholder="http://influxdb:8086",
                       help="Where InfluxDB answers. In the bundled compose "
                            "file this is http://influxdb:8086."),
                Option("api", "API version", kind="choice", default="v2",
                       choices=(("v2", "InfluxDB 2.x and 3.x"),
                                ("v1", "InfluxDB 1.x")),
                       help="2.x has been the default since 2020. 1.8 is "
                            "still common on small machines and speaks a "
                            "different write path."),
                Option("bucket", "Bucket or database", kind="text",
                       required=True, default="weewx",
                       help="Where the points go. The same one for every "
                            "archive: they are told apart by their location "
                            "tag, which is what lets a single query draw all "
                            "of them."),
                Option("org", "Organisation", kind="text", default="",
                       help="InfluxDB 2 only. What the bucket belongs to."),
                Option("token", "API token", kind="secret", default="",
                       help="InfluxDB 2: a token with write permission on "
                            "the bucket. A write-only token is enough, and "
                            "is the one to use."),
                Option("username", "Username", kind="text", default="",
                       advanced=True,
                       help="InfluxDB 1 only, and only where it has "
                            "authentication switched on."),
                Option("password", "Password", kind="secret", default="",
                       advanced=True, help="InfluxDB 1 only."),
            )),
            Group("What gets written", "", (
                Option("measurement", "Measurement", kind="text",
                       default="weather",
                       help="The table, in InfluxDB's language. Leave it "
                            "alone unless something else already writes "
                            "weather into this bucket."),
                Option("location", "Location tag", kind="text", default="",
                       placeholder="kirchdorf",
                       help="The tag every point carries, and what a Grafana "
                            "query groups by to draw several places on one "
                            "axis. Set one per archive. Two weewx-evo "
                            "installations writing into one bucket need "
                            "different ones or their readings merge."),
                Option("unit_system", "Units", kind="choice",
                       default="metricwx",
                       choices=(("metricwx", "Metric (mm of rain, m/s wind)"),
                                ("metric", "Metric (cm of rain, km/h wind)"),
                                ("us", "US (°F, inches, mph)")),
                       help="InfluxDB stores numbers without meaning, so this "
                            "decides what a Grafana axis is showing. Changing "
                            "it later puts a step in the middle of the series "
                            "that nothing downstream can see -- pick it once."),
            )),
            # A higher ceiling than the other uploads, and for a reason worth
            # writing down: theirs protects somebody else's free service from
            # a station that was offline for a week. This is the operator's
            # own database, and filling it with fifteen years of readings is
            # the point rather than the accident.
            *when_options(trigger="record", every=300, catch_up=5000,
                          catch_up_max=1_000_000),
            Group("How", "", (
                Option("timeout", "Give up after", kind="duration",
                       default=30, minimum=5, maximum=300, advanced=True),
            )),
        ]

"""Readings as an answer to a question, rather than as a file.

Every output this program has is a file. A feed writes a directory, an export
moves it, a page reads it. That works for the questions somebody thought of
in advance, and for nothing else -- a client with a question no plot answers
has no way in at all. Home Assistant, a phone app, a script, Grafana through
Infinity: all of them stop here.

`series.py` can already answer every one of those questions. What was missing
was a way to ask.

    GET /api/v1/                     what this answers
    GET /api/v1/archives             the measurement series there are
    GET /api/v1/fields               what is recorded, with units and groups
    GET /api/v1/current              the newest record
    GET /api/v1/series               a reading over a span
    GET /api/v1/aggregate            one number for one span

**It calls `series.py`, and that is the point.** A second implementation of
"the average temperature last week" is the fault `chartdata.py` describes:
two answers, both right on their own, differing in the third decimal, and
nobody able to say which is the station's. Everything here is a thin shell
over the same reader the feeds use.

## Read-only, and it says so

Nothing here writes. Not as a precaution -- it is what makes the decision
about who may reach it a simple one. A settings page can point the archive at
another file; this can tell you what the temperature was.

## Behind whatever the web server is behind

The [web server](Web-Server) already answers private networks only, and the
feeds it serves are the part meant to be read. The API is the same audience
and the same data in a different shape, so it inherits that, with an optional
token for an installation that publishes to the open internet.

## The limits are not politeness

**A span with no bucket size is refused past a point.** Ten years of
five-minute records is a million points; serialising them is a gigabyte of
JSON and a process that dies rather than answers. So a long span must say how
it wants to be cut, and the message says so rather than timing out.

**Every answer names its units.** The archive keeps what the station wrote,
which may be Fahrenheit on a German station -- a number without a unit is
the fault that reached a published page twice through the live push, and an
API is a worse place for it because the reader is a program.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import units
from .series import AGGREGATES, Reader

log = logging.getLogger(__name__)

VERSION = "v1"
PREFIX = f"/api/{VERSION}"

#: The most points one answer may carry. Past this the caller is asked to say
#: how it wants the span cut, rather than being handed a gigabyte or a
#: timeout. Ten thousand is more than any screen has pixels.
MOST_POINTS = 10_000

#: And the most a `current` or `fields` answer will walk. Cheap questions
#: stay cheap.
RECENT = 86400


@dataclass
class Answer:
    """One reply: a status, a content type and a body."""

    status: int = 200
    kind: str = "application/json; charset=utf-8"
    body: bytes = b""

    @classmethod
    def of(cls, payload: Any, status: int = 200) -> Answer:
        return cls(status=status,
                   body=json.dumps(payload, allow_nan=False,
                                   separators=(",", ":")).encode("utf-8"))

    @classmethod
    def wrong(cls, why: str, status: int = 400) -> Answer:
        # A reason, not a number. The caller is a program somebody is
        # writing, and "400" alone means reading this file.
        return cls.of({"error": why}, status=status)


class Api:
    """Answers the questions `series.py` can answer.

    Holds no connection. One is opened per request and closed with it: this
    is answering a browser or a script, the questions are seconds apart, and
    a pool of long-lived SQLite handles is the shape that once took an
    instance down with 477 descriptors.
    """

    def __init__(self, archives: dict[str, Path], default: str = "",
                 token: str = "", stations: Any = None,
                 station_name: str = "") -> None:
        self.archives = dict(archives)
        self.default = default or next(iter(self.archives), "")
        self.token = str(token or "")
        self.stations = stations
        self.station_name = station_name

    # -- routing ----------------------------------------------------------

    def handles(self, path: str) -> bool:
        return path == PREFIX or path.startswith(PREFIX + "/")

    def answer(self, path: str, query: str = "",
               header_token: str = "") -> Answer:
        if not self.allowed(query, header_token):
            # 404 rather than 401, the same as the listener: saying "wrong
            # token" confirms there is something here to try tokens against.
            return Answer.wrong("not found", status=404)

        rest = path[len(PREFIX):].strip("/")
        fields = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
        route = {
            "": self.index,
            "archives": self.archives_answer,
            "stations": self.stations_answer,
            "fields": self.fields_answer,
            "current": self.current,
            "series": self.series,
            "aggregate": self.aggregate,
        }.get(rest)
        if route is None:
            return Answer.wrong(f"no such endpoint: /{rest}", status=404)
        try:
            return route(fields)
        except Wrong as exc:
            return Answer.wrong(str(exc))
        except sqlite3.Error as exc:
            log.warning("api: %s", exc)
            return Answer.wrong("the archive could not be read", status=503)

    def allowed(self, query: str, header_token: str = "") -> bool:
        """Whether this request may be answered.

        The token may be in a header or in the query. A header is right for a
        script and wrong for a browser address bar, and both are people who
        will use this.
        """
        if not self.token:
            return True
        if header_token and header_token.strip() == self.token:
            return True
        fields = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
        return fields.get("token", "") == self.token

    # -- the endpoints ----------------------------------------------------

    def index(self, _fields: dict) -> Answer:
        """What this answers. So a person with the address can find the rest."""
        return Answer.of({
            "weewx_evo": VERSION,
            "station": self.station_name,
            "archives": sorted(self.archives),
            "endpoints": {
                "/archives": "the measurement series there are",
                "/stations": "the consoles that write into them",
                "/fields": "what is recorded: units, groups, spans",
                "/current": "the newest record",
                "/series": ("a reading over a span: obs, start, stop, "
                            "aggregate, every, units"),
                "/aggregate": "one number: obs, start, stop, how",
            },
            "aggregates": sorted(AGGREGATES),
        })

    def archives_answer(self, _fields: dict) -> Answer:
        out = []
        for name in sorted(self.archives):
            entry: dict[str, Any] = {"name": name, "default": name == self.default}
            with self._reader(name) as reader:
                span = reader.span()
                entry["units"] = units.name(reader.system)
                entry["first"] = span[0] if span else None
                entry["last"] = span[1] if span else None
            out.append(entry)
        return Answer.of({"archives": out})

    def stations_answer(self, _fields: dict) -> Answer:
        """The consoles, from `stations.toml`. No identities.

        An identity is what a console proves itself with, and this endpoint
        may be reachable by anybody the web server answers.
        """
        found = []
        for one in (getattr(self.stations, "all", list)() or []):
            found.append({
                "name": one.name,
                "driver": getattr(one, "driver", ""),
                "archive": getattr(one, "archive", ""),
                "role": getattr(one, "role", "main"),
                "indoor": bool(getattr(one, "indoor", True)),
            })
        return Answer.of({"stations": found})

    def fields_answer(self, fields: dict) -> Answer:
        """What is recorded, with what it measures and what it is in.

        The endpoint a client calls first: it can lay out its own page from
        this and then ask only for what the station actually has.
        """
        name = self._archive_named(fields)
        with self._reader(name) as reader:
            system = reader.system
            columns = sorted(reader.columns)
            out = []
            for obs in columns:
                if obs in ("dateTime", "usUnits"):
                    continue
                unit, group = units.unit_of(obs, system)
                out.append({
                    "name": obs,
                    "label": units.obs_label(obs),
                    "group": group,
                    "unit": unit,
                    "unit_label": units.label(unit) if unit else "",
                    # Whether it can be asked for cheaply over a long span.
                    "daily": reader.has_daily(obs),
                })
        return Answer.of({"archive": name, "units": units.name(system),
                          "fields": out})

    def current(self, fields: dict) -> Answer:
        """The newest record, converted if asked."""
        name = self._archive_named(fields)
        system = self._system(fields)
        with self._reader(name) as reader:
            span = reader.span()
            if span is None:
                return Answer.of({"archive": name, "record": None})
            record = _record_at(reader, span[1])
        if record is None:
            return Answer.of({"archive": name, "record": None})

        was = units.system_from(record.get("usUnits"), default=units.US)
        wanted = system or was
        out: dict[str, Any] = {}
        for obs, value in sorted(record.items()):
            if obs in ("dateTime", "usUnits") or value is None:
                continue
            out[obs] = _converted(obs, value, was, wanted)
        return Answer.of({
            "archive": name,
            "units": units.name(wanted),
            "dateTime": int(record.get("dateTime") or 0),
            "record": out,
        })

    def series(self, fields: dict) -> Answer:
        """A reading over a span. The endpoint this whole file is for."""
        name = self._archive_named(fields)
        obs = _needed(fields, "obs")
        start, stop = self._span(fields)
        aggregate = (fields.get("aggregate") or "").strip().lower() or None
        if aggregate and aggregate not in AGGREGATES:
            raise Wrong(f"{aggregate!r} is not an aggregate. One of: "
                        f"{', '.join(sorted(AGGREGATES))}")
        every = _every(fields.get("every"))
        system = self._system(fields)

        with self._reader(name) as reader:
            if obs not in reader.columns:
                raise Wrong(f"{obs!r} is not in this archive. /fields lists "
                            f"what is.")
            self._not_too_many(reader, start, stop, aggregate, every)
            found = reader.series(obs, start, stop, aggregate, every)
            was = reader.system

        wanted = system or was
        unit, group = units.unit_of(obs, wanted)
        stored, _group = units.unit_of(obs, was)
        values = [_convert(value, stored, unit) for value in found.values]

        payload: dict[str, Any] = {
            "archive": name, "obs": obs,
            "label": units.obs_label(obs),
            "group": group, "unit": unit,
            "unit_label": units.label(unit) if unit else "",
            "aggregate": found.aggregate, "every": found.interval,
            "start": int(start), "stop": int(stop),
            "time": [int(one) for one in found.time],
            "values": values,
        }
        if found.directions is not None:
            payload["directions"] = list(found.directions)
        return Answer.of(payload)

    def aggregate(self, fields: dict) -> Answer:
        """One number for one span."""
        name = self._archive_named(fields)
        obs = _needed(fields, "obs")
        start, stop = self._span(fields)
        how = (fields.get("how") or "avg").strip().lower()
        if how not in AGGREGATES:
            raise Wrong(f"{how!r} is not an aggregate. One of: "
                        f"{', '.join(sorted(AGGREGATES))}")
        system = self._system(fields)

        with self._reader(name) as reader:
            if obs not in reader.columns:
                raise Wrong(f"{obs!r} is not in this archive.")
            value = reader.aggregate(obs, start, stop, how)
            was = reader.system

        wanted = system or was
        unit, group = units.unit_of(obs, wanted)
        stored, _group = units.unit_of(obs, was)
        return Answer.of({
            "archive": name, "obs": obs, "how": how,
            "start": int(start), "stop": int(stop),
            "group": group, "unit": unit,
            "unit_label": units.label(unit) if unit else "",
            "value": _convert(value, stored, unit),
        })

    # -- the plumbing -----------------------------------------------------

    def _reader(self, name: str) -> Any:
        """A reader over one archive, and the connection closed with it."""
        return _Open(self.archives[name])

    def _archive_named(self, fields: dict) -> str:
        name = (fields.get("archive") or "").strip() or self.default
        if name not in self.archives:
            raise Wrong(f"no archive called {name!r}. /archives lists them.")
        return name

    def _system(self, fields: dict) -> int | None:
        """What the caller wants the numbers in, or None for the archive's."""
        wanted = (fields.get("units") or "").strip().lower()
        if not wanted:
            return None
        found = {"us": units.US, "metric": units.METRIC,
                 "metricwx": units.METRICWX}.get(wanted)
        if found is None:
            raise Wrong(f"{wanted!r} is not a unit system. One of: us, "
                        f"metric, metricwx.")
        return found

    def _span(self, fields: dict) -> tuple[float, float]:
        stop = _moment(fields.get("stop"), default=time.time())
        start = _moment(fields.get("start"), default=stop - 86400)
        if start >= stop:
            raise Wrong("start must be before stop")
        # Before the epoch is not a span, it is a typo -- `-100000d` is one
        # keystroke away from `-10000d`. Left through, it reaches
        # `time.localtime` with a negative number, which raises OSError on
        # Windows and gives the caller a dead connection instead of an
        # answer.
        if start < 0 or stop < 0:
            raise Wrong("no readings exist before 1970")
        return start, stop

    def _not_too_many(self, reader: Any, start: float, stop: float,
                      aggregate: str | None, every: Any) -> None:
        """Refuse a span that would answer with a million points.

        With an aggregate the caller has already said how the span is cut, so
        the arithmetic is on the buckets. Without one it is on the records,
        and that is the request that has to be turned away with a reason
        rather than left to time out.
        """
        if aggregate:
            wide = _seconds(every) or 86400
            if (stop - start) / max(wide, 1) > MOST_POINTS:
                raise Wrong(
                    f"that span cut into {every or 'day'} buckets is more "
                    f"than {MOST_POINTS} points. Ask for a wider bucket or a "
                    f"shorter span.")
            return

        interval = _archive_interval(reader) or 300
        if (stop - start) / interval > MOST_POINTS:
            raise Wrong(
                f"that span holds more than {MOST_POINTS} records. Add "
                f"`aggregate` and `every` to say how it should be cut, or "
                f"ask for less.")


class Wrong(Exception):
    """A request that cannot be answered, with the reason for the caller."""


class _Open:
    """A reader and the connection under it, closed together."""

    def __init__(self, where: Path) -> None:
        self.where = where

    def __enter__(self) -> Reader:
        self.conn = sqlite3.connect(f"file:{self.where}?mode=ro", uri=True)
        return Reader(self.conn)

    def __exit__(self, *exc: object) -> None:
        self.conn.close()


def _archive_interval(reader: Any) -> int | None:
    """The archive interval in seconds, from the newest record."""
    try:
        row = reader.conn.execute(
            "SELECT `interval` FROM archive ORDER BY dateTime DESC "
            "LIMIT 1").fetchone()
    except (sqlite3.Error, AttributeError):
        return None
    return int(float(row[0]) * 60) if row and row[0] else None


def _record_at(reader: Any, when: float) -> dict | None:
    """One record, by its timestamp, as a dictionary."""
    cursor = reader.conn.execute(
        "SELECT * FROM archive WHERE dateTime = ?", (int(when),))
    row = cursor.fetchone()
    if row is None:
        return None
    names = [one[0] for one in cursor.description]
    return dict(zip(names, row, strict=True))


def _needed(fields: dict, name: str) -> str:
    value = (fields.get(name) or "").strip()
    if not value:
        raise Wrong(f"{name} is needed")
    return value


def _moment(value: Any, default: float) -> float:
    """A timestamp, from seconds, an ISO date, or `-7d`.

    Three shapes because three sorts of caller: a script has an epoch, a
    person typing into a browser has a date, and a dashboard has "the last
    week".
    """
    text = str(value or "").strip()
    if not text:
        return default
    if text.lstrip("-+").isdigit():
        return float(text)
    if text.startswith("-") and text[-1] in "smhdwy":
        seconds = _seconds(text[1:])
        if seconds:
            return time.time() - seconds
    import datetime

    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise Wrong(f"{text!r} is not a time. Use seconds since the epoch, "
                    f"an ISO date like 2026-08-20, or a span back from now "
                    f"like -30m, -12h, -7d, -4w, -1y.") from exc
    if when.tzinfo is None:
        # Naive means local, because a day boundary here is local midnight
        # and that is what the whole archive is keyed on.
        when = when.astimezone()
    return when.timestamp()


def _every(value: Any) -> int | str | None:
    """A bucket size: seconds, `1h`, or a calendar word."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in ("hour", "day", "week", "month", "year"):
        return text
    seconds = _seconds(text)
    if not seconds:
        raise Wrong(f"{text!r} is not a bucket size. Use seconds, 1h, or one "
                    f"of hour, day, week, month, year.")
    return seconds


def _seconds(value: Any) -> int | None:
    """`90`, `15m`, `2h`, `7d` as seconds. None where it is not one."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in ("hour", "day", "week"):
        return {"hour": 3600, "day": 86400, "week": 604800}[text]
    if text in ("month", "year"):
        # Not a fixed number of seconds. The caller gets the calendar
        # arithmetic from `series.buckets`; this is only for the size check.
        return {"month": 2_592_000, "year": 31_536_000}[text]
    # A year is 365 days here and a month is 30. Both are only used to size
    # a request, never to cut a bucket -- `series.buckets` does the calendar
    # arithmetic, where a month really is a month.
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800,
             "y": 31_536_000}
    if text[-1] in scale and text[:-1].replace(".", "", 1).isdigit():
        return int(float(text[:-1]) * scale[text[-1]])
    if text.isdigit():
        return int(text)
    return None


def _convert(value: Any, stored: str | None, wanted: str | None) -> Any:
    if value is None or stored is None or wanted is None or stored == wanted:
        return value
    converted = units.convert(value, stored, wanted)
    return None if converted is None else float(converted)


def _converted(obs: str, value: Any, was: int, wanted: int) -> Any:
    stored, _group = units.unit_of(obs, was)
    unit, _group = units.unit_of(obs, wanted)
    return _convert(value, stored, unit)

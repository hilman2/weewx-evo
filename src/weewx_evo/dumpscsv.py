"""A CSV of readings, into the archive.

The format every other weather program can produce, and what somebody falls
back on when theirs is not supported: a spreadsheet exported from Weather
Display, a download from Weather Underground, a file a neighbour sent.

**The column names are the archive's, and nothing is guessed.** `temp`,
`temperature`, `outsideTemp` and `Outdoor Temperature` all obviously mean
`outTemp` to a person and a guess between them is a measurement written into
the wrong column -- which no later reading of the file can undo, and which
nothing downstream can notice. So a name the schema does not have is
*reported* and left out, and `--map` is how somebody says what it is.

Three things are read rather than guessed at, because they can be:

  * **Which column is the time.** From the usual names, and the file is
    refused if none of them is there. A CSV with no time is not a series of
    readings.
  * **What the times are.** Epoch seconds, ISO 8601, or a `--time-format`.
    Epoch and ISO are unambiguous; everything else is not, and `03/04/2024`
    is the fourth of March in one country and the third of April in another.
  * **Whether a value is a number.** An empty cell, `N/A`, `--` and `---`
    are all absent, and absent is None rather than zero. A station with no
    rain gauge and one in a drought must not come out the same.

**The interval comes from the timestamps, because it has to.** `interval` is
NOT NULL in the archive, and `INSERT OR IGNORE` -- which is what makes an
import idempotent -- treats a NOT NULL violation as something to ignore. So a
CSV without that column writes *nothing at all*, reports every row as read,
and leaves an archive exactly as empty as it found it. Nothing raises and
nothing is logged.

It is not a formality either: every average in this project is weighted by
it (`aggregate.py`), so a wrong one is a wrong mean rather than a missing
field. The gap between one row and the next is what the interval is, and a
file whose rows are five minutes apart says so in its own timestamps.

**Units are stated, not inferred.** `--units` is required to be thought
about, and its default is US because that is what an American export is and
the ones that are not usually say so somewhere a program cannot read. This
is the same fault the live push had twice: 68.2 published on a page written
in Celsius, and nothing on the page able to tell.
"""

from __future__ import annotations

import csv
import datetime
import itertools
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import units

log = logging.getLogger(__name__)

#: What a time column is called, in the files people actually have. Ordered:
#: an epoch column beats a formatted one where a file carries both, because
#: it needs no format and cannot be ambiguous.
TIME_NAMES = ("dateTime", "datetime", "timestamp", "epoch", "unixtime",
              "time", "date", "Date", "Datum", "date_time", "Date/Time",
              "observation_time")

#: Cells that mean "nothing was measured". Never a zero: see the docstring.
ABSENT = {"", "-", "--", "---", "n/a", "N/A", "na", "NA", "null", "NULL",
          "none", "None", "nan", "NaN", "?"}

#: How many records go to `add_records` at once.
BATCH = 20_000

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


@dataclass
class Found:
    """What a CSV turned out to hold."""

    rows: int = 0
    records: int = 0
    skipped: int = 0
    columns: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    time_column: str = ""
    first: int | None = None
    last: int | None = None
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        span = ""
        if self.first and self.last:
            been = (datetime.datetime.fromtimestamp(self.first),
                    datetime.datetime.fromtimestamp(self.last))
            span = f", {been[0]:%Y-%m-%d} to {been[1]:%Y-%m-%d}"
        return (f"{self.records} records from {self.rows} rows, "
                f"{len(self.columns)} readings{span}")


def _number(text: str) -> float | None:
    """A cell as a number, or None. Never a zero for something unreadable."""
    text = (text or "").strip()
    if text in ABSENT:
        return None
    # A comma is a decimal separator in one file and a thousands separator
    # in the next, and both are ordinary. The point decides: a number with
    # one means its commas are grouping, and a number without one means its
    # single comma is the decimal.
    if "," in text:
        if "." in text:
            text = text.replace(",", "")
        elif text.count(",") == 1:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _stamp(text: str, fmt: str | None = None) -> int | None:
    """A cell as Unix time, or None.

    Local time for anything but epoch seconds, because a weather CSV is
    written in the station's own zone and an archive day begins at local
    midnight. A file in UTC therefore needs its own column or a format with
    a zone in it -- said in the notes rather than guessed at.
    """
    text = (text or "").strip()
    if not text:
        return None
    if fmt:
        try:
            return int(datetime.datetime.strptime(text, fmt).timestamp())
        except ValueError:
            return None
    if text.isdigit() or (text[0] == "-" and text[1:].isdigit()):
        value = int(text)
        # Milliseconds, which is what a JavaScript export writes. A weather
        # reading from 1970 is not a thing, and one from the year 55000 is
        # not either, so the ambiguity is not real.
        return value // 1000 if value > 10_000_000_000 else value
    if _ISO.match(text):
        try:
            # `fromisoformat` takes the trailing Z itself since 3.11.
            return int(datetime.datetime.fromisoformat(text).timestamp())
        except ValueError:
            return None
    return None


def _time_column(header: list[str], asked: str | None = None) -> str:
    if asked:
        return asked if asked in header else ""
    for name in TIME_NAMES:
        if name in header:
            return name
    lowered = {one.lower(): one for one in header}
    for name in TIME_NAMES:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return ""


def _read(path: Path, delimiter: str, time_column: str | None,
          time_format: str | None, unit_system: str,
          columns: set[str] | None, found: Found,
          interval: float | None = None) -> Any:
    """Rows as records. Fills `found` as it goes.

    Records come out with an `interval`, worked out from the gap to the
    previous row where the file does not carry one. See the module
    docstring: without it nothing is written and nothing says so.
    """
    system = {"us": units.US, "metric": units.METRIC,
              "metricwx": units.METRICWX}.get(
                  str(unit_system or "us").lower(), units.US)

    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter or ",")
        try:
            header = [one.strip() for one in next(reader)]
        except StopIteration:
            found.notes.append("the file is empty")
            return

        when = _time_column(header, time_column)
        if not when:
            found.notes.append(
                f"no time column. Looked for {', '.join(TIME_NAMES[:6])}; "
                f"the file has {', '.join(header[:8])}. "
                f"--time-column names one.")
            return
        found.time_column = when
        at = header.index(when)

        # Which columns are readings this archive can hold. Reported rather
        # than mapped: guessing that `temp` is `outTemp` writes a
        # measurement into a column it does not belong in.
        known = columns if columns is not None else set(units.all_groups())
        wanted: list[tuple[int, str]] = []
        for index, name in enumerate(header):
            if index == at or not name:
                continue
            if name in known or name in ("usUnits", "interval"):
                wanted.append((index, name))
            else:
                found.ignored.append(name)
        found.columns = [name for _index, name in wanted]

        for row in reader:
            found.rows += 1
            if len(row) <= at:
                found.skipped += 1
                continue
            stamp = _stamp(row[at], time_format)
            if stamp is None:
                found.skipped += 1
                continue
            record: dict[str, Any] = {"dateTime": stamp, "usUnits": system}
            if interval is not None:
                record["interval"] = interval
            for index, name in wanted:
                if index >= len(row):
                    continue
                value = _number(row[index])
                if value is not None:
                    record[name] = value
            # `usUnits` in the file wins over the argument: a file that
            # states its own units knows better than a default.
            if "usUnits" in record:
                record["usUnits"] = int(record["usUnits"])
            found.first = (stamp if found.first is None
                           else min(found.first, stamp))
            found.last = (stamp if found.last is None
                          else max(found.last, stamp))
            yield record


def _with_intervals(records: Any, interval: float | None,
                    found: Found) -> Any:
    """Every record with an `interval`, in minutes.

    From the gap to the *previous* record, which is what an archive interval
    is: the span a record covers ends at its own timestamp. The first row has
    no previous one and takes the second's gap, because one record with no
    interval is one record silently not written.

    A gap that is not positive -- a duplicate timestamp, or rows out of order
    -- falls back to the commonest gap so far rather than to a guess: a file
    sorted newest-first would otherwise give every record a negative
    interval, and `weight_of` would refuse the lot.
    """
    held: list[dict] = []
    for record in records:
        held.append(record)
    if not held:
        return

    if interval is not None:
        for record in held:
            record.setdefault("interval", interval)
            yield record
        return

    stated = [one for one in held if one.get("interval") is not None]
    if len(stated) == len(held):
        # The file says so itself, which is the case for a WeeWX export.
        yield from held
        return

    order = sorted(held, key=lambda one: one["dateTime"])
    gaps = [b["dateTime"] - a["dateTime"]
            for a, b in itertools.pairwise(order)]
    positive = [gap for gap in gaps if gap > 0]
    usual = min(positive) if positive else 300
    if positive:
        counted: dict[int, int] = {}
        for gap in positive:
            counted[gap] = counted.get(gap, 0) + 1
        usual = max(counted, key=lambda gap: counted[gap])

    found.notes.append(
        f"the file states no interval, so it was taken from the gaps "
        f"between rows: {usual / 60:g} minutes. Every average is weighted "
        f"by it. --interval says otherwise.")

    previous: int | None = None
    for record in order:
        if record.get("interval") is None:
            gap = (record["dateTime"] - previous) if previous else 0
            record["interval"] = (gap if gap > 0 else usual) / 60.0
        previous = record["dateTime"]
        yield record


def inspect(path: str | Path, delimiter: str = ",",
            time_column: str | None = None, time_format: str | None = None,
            unit_system: str = "us", interval: float | None = None) -> Found:
    """What is in a CSV, without writing anything."""
    found = Found()
    read = _read(Path(path), delimiter, time_column, time_format,
                 unit_system, None, found)
    for _record in _with_intervals(read, interval, found):
        found.records += 1
    if found.ignored:
        found.notes.append(
            f"{len(found.ignored)} column(s) are not archive readings and "
            f"were left out: {', '.join(found.ignored[:8])}"
            + (" ..." if len(found.ignored) > 8 else ""))
    return found


def into(path: str | Path, archive: Any, delimiter: str = ",",
         time_column: str | None = None, time_format: str | None = None,
         unit_system: str = "us", replace: bool = False,
         interval: float | None = None) -> Found:
    """Read a CSV into an archive. Returns what was done.

    Sorted per batch, because `add_records` needs ascending time and a
    spreadsheet is as likely to be newest-first as oldest-first.
    """
    found = Found()
    columns = set(archive.schema.columns)
    batch: list[dict] = []
    read = _read(Path(path), delimiter, time_column, time_format,
                 unit_system, columns, found)
    for record in _with_intervals(read, interval, found):
        batch.append(record)
        if len(batch) >= BATCH:
            batch.sort(key=lambda one: one["dateTime"])
            found.records += archive.add_records(batch, replace=replace)
            batch = []
    if batch:
        batch.sort(key=lambda one: one["dateTime"])
        found.records += archive.add_records(batch, replace=replace)

    if found.ignored:
        found.notes.append(
            f"{len(found.ignored)} column(s) are not archive readings and "
            f"were left out: {', '.join(found.ignored[:8])}"
            + (" ..." if len(found.ignored) > 8 else ""))
    return found

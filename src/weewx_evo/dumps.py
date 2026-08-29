"""The other half of adoption: readings that are in somebody's SQL server.

`adopt.py` takes over a `weewx.sdb` by opening it, because it is the same
file this program already reads and writes. A MySQL or Postgres installation
has the same records in a place we cannot open, and that is the whole of the
difference.

**A dump, not a connection.** `mysqlclient` and `psycopg2` are dependencies,
and both need a compiler on a Raspberry Pi -- which is exactly what "standard
library only" is protecting. And the command is one every operator of such an
installation already knows:

    mysqldump weewx archive > weewx.sql
    pg_dump --table=archive weewx > weewx.sql

    weewx-evo import dump weewx.sql

The trade is one file the size of the readings, once. What it buys is that
this runs where the file is rather than where the server is, needs no
credentials, no network, no server version to be compatible with, and can be
tried on a copy without touching the running installation.

**Both dialects, because both are in the field.** They are not the same shape
at all:

  * **MySQL** writes `INSERT INTO archive VALUES (…),(…),(…)` -- thousands of
    tuples in one statement, quoted with `'`, escaped with a backslash, NULL
    as the bare word.
  * **Postgres** writes `COPY archive (dateTime, usUnits, …) FROM stdin;` and
    then tab-separated lines until a lone `\\.` -- NULL as `\\N`, and the tab,
    newline and backslash themselves escaped.

Read at the same time is the schema, because the schema is the point: this
project's one rule is that the columns come from the file rather than from a
list in the code, and an installation with its own soil probes has columns
nobody here has heard of. `CREATE TABLE archive (…)` says what they are, and
they are created in the destination as they are found.

**The interval has to be there, and it is filled in where it is not.**
`interval` is NOT NULL in the archive, and `INSERT OR IGNORE` -- which is
what makes an import idempotent -- treats a NOT NULL violation as something
to ignore. A dump made with `--no-create-info` and a column list that leaves
it out therefore writes *nothing at all*, reports every row as read, and
leaves the archive exactly as it found it. Nothing raises and nothing is
logged. So the gap between one record and the next is used, and said out
loud: every average in this project is weighted by that number
(`aggregate.py`), so a wrong one is a wrong mean rather than a missing field.

**What is not read: `archive_day_*`.** Every one of them is derivable from
`archive`, and `add_records` rebuilds them as it writes -- so importing them
would be copying a cache in order to overwrite it. It is also the one part
that could be *wrong* in the source, and carrying a wrong cache across is how
a fault outlives the installation it came from.
"""

from __future__ import annotations

import itertools
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: How many records are handed to `add_records` at once. Grouped by day
#: inside it anyway; this is only about how much is held in memory, and a
#: year of five-minute records is a hundred thousand of them.
BATCH = 20_000

#: Columns that are not readings and are handled by name.
KEYS = ("dateTime", "usUnits", "interval")

# Only as far as the opening bracket. Where the body *ends* is found by
# counting brackets rather than by looking for a keyword: `varchar(255)
# DEFAULT NULL` closes a bracket and is followed by DEFAULT, so a pattern
# that stops at the first `) DEFAULT` cuts the table off at its first sized
# column -- which on a real installation is wherever somebody put a note
# field, and every column after it is then unknown.
#
# The schema prefix is optional and `pg_dump` always writes one
# (`public.archive`). Without it the Postgres CREATE TABLE never matched at
# all, every column came back as text, and the import fell over on the first
# record with "argument must be int or float, not str".
_CREATE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[`\"']?\w+[`\"']?\.)?[`\"']?(?P<name>\w+)[`\"']?\s*\(",
    re.IGNORECASE)
_COLUMN = re.compile(r"^\s*[`\"']?(?P<name>\w+)[`\"']?\s+(?P<type>[\w()]+)")
_INSERT = re.compile(
    r"INSERT\s+(?:LOW_PRIORITY\s+|DELAYED\s+|HIGH_PRIORITY\s+|IGNORE\s+)*"
    r"INTO\s+[`\"']?(?P<name>\w+)[`\"']?\s*"
    r"(?:\((?P<columns>[^)]*)\)\s*)?VALUES\s*(?P<values>.*)",
    re.IGNORECASE | re.DOTALL)
_COPY = re.compile(
    r"COPY\s+(?:\w+\.)?[`\"']?(?P<name>\w+)[`\"']?\s*"
    r"\((?P<columns>[^)]*)\)\s+FROM\s+stdin", re.IGNORECASE)

#: What SQL types mean here. Everything a weather reading can be is a number;
#: the rest is carried as text so a column nobody anticipated survives.
_REAL = ("double", "float", "real", "decimal", "numeric")
_INT = ("int", "bigint", "smallint", "tinyint", "mediumint", "serial")


@dataclass
class Found:
    """What a dump turned out to hold, for the command to report."""

    dialect: str = ""
    table: str = ""
    columns: list[str] = field(default_factory=list)
    records: int = 0
    first: int | None = None
    last: int | None = None
    skipped: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        span = ""
        if self.first and self.last:
            import datetime
            been = (datetime.datetime.fromtimestamp(self.first),
                    datetime.datetime.fromtimestamp(self.last))
            span = f", {been[0]:%Y-%m-%d} to {been[1]:%Y-%m-%d}"
        return (f"{self.records} records, {len(self.columns)} columns"
                f"{span}")


# ---------------------------------------------------------------------------
# Reading values.
# ---------------------------------------------------------------------------

def _unquote_mysql(text: str) -> Any:
    """One MySQL literal. `NULL` is None, a quoted string is unescaped."""
    text = text.strip()
    if not text or text.upper() == "NULL":
        return None
    if text[0] in "'\"" and text[-1] == text[0]:
        body = text[1:-1]
        # MySQL's own escapes, in the order it writes them. `\\` last would
        # turn `\\n` into a newline, which is a real difference in a text
        # column somebody used for a note.
        out, at = [], 0
        while at < len(body):
            char = body[at]
            if char == "\\" and at + 1 < len(body):
                nxt = body[at + 1]
                out.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0",
                            "\\": "\\", "'": "'", '"': '"',
                            "Z": "\x1a"}.get(nxt, nxt))
                at += 2
                continue
            if char == text[0] and at + 1 < len(body) and body[at + 1] == char:
                out.append(char)   # doubled quote, the SQL standard's way
                at += 2
                continue
            out.append(char)
            at += 1
        return "".join(out)
    return text


def _split_tuples(values: str) -> Iterator[list[str]]:
    """The `(…),(…),(…)` of one INSERT, as lists of raw literals.

    Written by hand rather than with a regular expression because a string
    in the data can hold a comma, a bracket, or an escaped quote -- and a
    pattern that gets that right is longer than this and harder to be sure
    of. Weather records rarely have such a column; the ones that do are the
    interesting installations.
    """
    at, size = 0, len(values)
    while at < size:
        while at < size and values[at] in " \t\r\n,;":
            at += 1
        if at >= size or values[at] != "(":
            break
        at += 1
        parts: list[str] = []
        current: list[str] = []
        quote = ""
        while at < size:
            char = values[at]
            if quote:
                current.append(char)
                if char == "\\" and at + 1 < size:
                    current.append(values[at + 1])
                    at += 2
                    continue
                if char == quote:
                    quote = ""
                at += 1
                continue
            if char in "'\"":
                quote = char
                current.append(char)
                at += 1
                continue
            if char == ",":
                parts.append("".join(current))
                current = []
                at += 1
                continue
            if char == ")":
                parts.append("".join(current))
                at += 1
                break
            current.append(char)
            at += 1
        yield parts


def _unquote_copy(text: str) -> Any:
    r"""One Postgres COPY field. `\N` is NULL and the escapes are its own."""
    if text == r"\N":
        return None
    if "\\" not in text:
        return text
    out, at = [], 0
    while at < len(text):
        if text[at] == "\\" and at + 1 < len(text):
            nxt = text[at + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                        "b": "\b", "f": "\f", "v": "\v"}.get(nxt, nxt))
            at += 2
            continue
        out.append(text[at])
        at += 1
    return "".join(out)


def _typed(value: Any, kind: str) -> Any:
    """A literal as the column's type says. Text where it will not convert.

    Never a zero for something unreadable: a station with no rain gauge and
    one recording a drought must not come out the same, which is the same
    rule `uploads/__init__.py` states for the other direction.

    **A column with no type is read as a number if it looks like one.** A
    dump made with `--no-create-info` has no types at all, and a Postgres
    COPY block hands every field over as text -- so without this every
    reading arrives as a string and the archive refuses the first one.
    Text is what is left when it will not convert, which is what a note
    column is.
    """
    if value is None or value == "":
        return None
    kind = (kind or "").lower()
    try:
        if any(one in kind for one in _REAL):
            return float(value)
        if any(one in kind for one in _INT):
            # Through float first: MySQL writes an integer column's value as
            # `1.0` where a view or an older schema made it a double.
            return int(float(value))
    except (TypeError, ValueError):
        return None

    if kind or not isinstance(value, str):
        return value
    try:
        return float(value) if ("." in value or "e" in value.lower())             else int(value)
    except (TypeError, ValueError):
        return value


# ---------------------------------------------------------------------------
# Reading a dump.
# ---------------------------------------------------------------------------

class Dump:
    """One SQL dump, read a statement at a time.

    Streamed rather than loaded: fifteen years of five-minute records is
    around a gigabyte of text, and reading that into a list to parse it is a
    memory figure rather than a program.
    """

    def __init__(self, path: str | Path, table: str = "archive") -> None:
        self.path = Path(path)
        self.table = table
        self.dialect = ""
        #: Column name to SQL type, from the CREATE TABLE.
        self.types: dict[str, str] = {}
        #: The order the INSERTs use, where they do not name their columns.
        self.order: list[str] = []
        self.notes: list[str] = []

    # -- the schema -------------------------------------------------------

    def read_schema(self) -> dict[str, str]:
        """Columns and their types, from the dump's own CREATE TABLE.

        The one rule again: the schema comes from the file. An installation
        with its own soil probes has columns nobody here has heard of, and a
        list in this module would drop exactly those.
        """
        text = []
        with open(self.path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text.append(line)
                # The CREATE TABLE is near the top of both dialects' output,
                # and reading the whole file for it would defeat streaming.
                if len(text) > 5000:
                    break
        found = self._create_in("".join(text))
        if found:
            self.types = found
        return self.types

    def _create_in(self, text: str) -> dict[str, str]:
        for match in _CREATE.finditer(text):
            if match.group("name").lower() != self.table.lower():
                continue
            body = _bracketed(text, match.end() - 1)
            if body is None:
                continue
            out: dict[str, str] = {}
            for part in _split_columns(body):
                column = _COLUMN.match(part)
                if column is None:
                    continue
                name = column.group("name")
                if name.upper() in ("PRIMARY", "KEY", "UNIQUE", "INDEX",
                                    "CONSTRAINT", "FOREIGN"):
                    continue
                out[name] = column.group("type")
            return out
        return {}

    # -- the records ------------------------------------------------------

    def records(self) -> Iterator[dict[str, Any]]:
        """Every row of the table, as a record.

        Both dialects from one pass, because a dump does not say which it is
        in a way worth trusting -- the statements do.
        """
        if not self.types:
            self.read_schema()

        with open(self.path, encoding="utf-8", errors="replace") as handle:
            statement: list[str] = []
            copying: list[str] | None = None
            for line in handle:
                if copying is not None:
                    if line.startswith("\\."):
                        copying = None
                        continue
                    row = self._copy_row(copying, line.rstrip("\n"))
                    if row is not None:
                        yield row
                    continue

                stripped = line.strip()
                if not stripped or stripped.startswith("--"):
                    continue

                start = _COPY.search(line)
                if start is not None:
                    if start.group("name").lower() != self.table.lower():
                        # Somebody else's table. Skipped, and its body with
                        # it: without this the rows land in `archive`.
                        copying = None
                        for skip in handle:
                            if skip.startswith("\\."):
                                break
                        continue
                    self.dialect = self.dialect or "postgres"
                    copying = [one.strip().strip('"')
                               for one in start.group("columns").split(",")]
                    continue

                statement.append(line)
                if not stripped.endswith(";"):
                    continue
                text = "".join(statement)
                statement = []
                yield from self._insert_rows(text)

    def _insert_rows(self, text: str) -> Iterator[dict[str, Any]]:
        match = _INSERT.search(text)
        if match is None:
            return
        if match.group("name").lower() != self.table.lower():
            return
        self.dialect = self.dialect or "mysql"

        named = match.group("columns")
        if named:
            columns = [one.strip().strip("`\"'") for one in named.split(",")]
        else:
            # No column list, which is what `mysqldump` writes by default.
            # The order is the CREATE TABLE's, which is why the schema is
            # read first and why a dump without one cannot be read at all.
            columns = list(self.types)
            if not columns:
                self.notes.append(
                    "the INSERTs name no columns and there is no CREATE "
                    "TABLE to take the order from")
                return

        for parts in _split_tuples(match.group("values")):
            if len(parts) != len(columns):
                continue
            row: dict[str, Any] = {}
            for name, raw in zip(columns, parts, strict=True):
                value = _unquote_mysql(raw)
                row[name] = _typed(value, self.types.get(name, ""))
            yield row

    def _copy_row(self, columns: list[str], line: str) -> dict[str, Any] | None:
        parts = line.split("\t")
        if len(parts) != len(columns):
            return None
        row: dict[str, Any] = {}
        for name, raw in zip(columns, parts, strict=True):
            row[name] = _typed(_unquote_copy(raw), self.types.get(name, ""))
        return row


def _bracketed(text: str, at: int) -> str | None:
    """What is inside the bracket that opens at `at`.

    By counting, so a sized type or an expression inside the definition does
    not end it early. Quotes are followed too: a default value can hold a
    bracket, and one that does would otherwise unbalance the count for the
    rest of the file.
    """
    if at >= len(text) or text[at] != "(":
        return None
    depth, quote, start = 0, "", at + 1
    while at < len(text):
        char = text[at]
        if quote:
            if char == "\\" and at + 1 < len(text):
                at += 2
                continue
            if char == quote:
                quote = ""
            at += 1
            continue
        if char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start:at]
        at += 1
    return None


def _split_columns(body: str) -> list[str]:
    """A CREATE TABLE body into its column definitions.

    On commas that are not inside brackets: `DECIMAL(10,2)` has one, and
    splitting on it makes a column called `2)` that never matches anything.
    """
    out, current, depth = [], [], 0
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            out.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        out.append("".join(current))
    return out


# ---------------------------------------------------------------------------
# Writing them.
# ---------------------------------------------------------------------------

def inspect(path: str | Path, table: str = "archive") -> Found:
    """What is in a dump, without writing anything.

    The command somebody runs first. A dump of the wrong table, or of a
    database that is not a weather one, should be found out before a
    destination file exists.
    """
    dump = Dump(path, table)
    found = Found(table=table)
    found.columns = list(dump.read_schema())
    if not found.columns:
        found.notes.append(
            f"no CREATE TABLE for {table!r} in the first part of the file. "
            f"A dump of one table made with --no-create-info has none, and "
            f"then the column order is unknown.")

    for record in dump.records():
        stamp = record.get("dateTime")
        if stamp is None:
            found.skipped += 1
            continue
        found.records += 1
        stamp = int(stamp)
        found.first = stamp if found.first is None else min(found.first, stamp)
        found.last = stamp if found.last is None else max(found.last, stamp)
    found.dialect = dump.dialect or "unknown"
    found.notes.extend(dump.notes)
    return found


def into(path: str | Path, archive: Any, table: str = "archive",
         replace: bool = False, progress: Any = None,
         interval: float | None = None) -> Found:
    """Read a dump into an archive. Returns what was done.

    The daily summaries are built as it goes -- `add_records` does that, and
    it is why this hands them over in order rather than one at a time. A
    separate rebuild afterwards would be a second pass over everything just
    written, and forgetting it would leave a cache older than its data.
    """
    dump = Dump(path, table)
    found = Found(table=table)
    found.columns = list(dump.read_schema())

    missing = [name for name in found.columns
               if name not in archive.schema.columns]
    if missing:
        # Named rather than created silently: a column here is a decision
        # about the destination schema, and `weewx-evo columns --add` is
        # where that decision is made and said out loud.
        found.notes.append(
            f"{len(missing)} column(s) the archive does not have, so those "
            f"readings are dropped: {', '.join(missing[:8])}"
            + (" ..." if len(missing) > 8 else "")
            + ". `weewx-evo columns --add` creates them.")

    if "interval" not in found.columns:
        found.notes.append(
            "the dump has no `interval` column, so it was taken from the "
            "gaps between records. Every average is weighted by it. Without "
            "one nothing would have been written at all: `interval` is NOT "
            "NULL and `INSERT OR IGNORE` ignores exactly that.")

    keep = set(archive.schema.columns)
    batch: list[dict] = []
    for record in dump.records():
        stamp = record.get("dateTime")
        if stamp is None:
            found.skipped += 1
            continue
        stamp = int(stamp)
        found.first = stamp if found.first is None else min(found.first, stamp)
        found.last = stamp if found.last is None else max(found.last, stamp)
        batch.append({name: value for name, value in record.items()
                      if name in keep and value is not None})
        if len(batch) >= BATCH:
            found.records += _write(archive, batch, replace, interval)
            batch = []
            if progress is not None:
                progress(found.records)
    if batch:
        found.records += _write(archive, batch, replace, interval)
    found.dialect = dump.dialect or "unknown"
    found.notes.extend(dump.notes)
    return found


def _write(archive: Any, batch: list[dict], replace: bool,
           interval: float | None = None) -> int:
    """One batch, oldest first, every record with an interval.

    Sorted here rather than relied on: `add_records` says records must be in
    ascending time order, and a dump made with `--order-by-primary` off is
    in whatever order the rows sit on disk. Out of order, every record would
    start a new day and each day's summary would be written as many times as
    it has gaps -- the fault would be slowness, not wrongness, which is the
    kind nobody finds.
    """
    batch.sort(key=lambda one: one["dateTime"])
    _fill_intervals(batch, interval)
    return archive.add_records(batch, replace=replace)


def _fill_intervals(batch: list[dict], interval: float | None = None) -> None:
    """Give every record an `interval`, in minutes. In place, sorted.

    From the gap to the previous record, which is what an archive interval
    is: the span a record covers ends at its own timestamp. The first takes
    the commonest gap, because there is nothing before it.
    """
    missing = [one for one in batch if one.get("interval") is None]
    if not missing:
        return
    if interval is not None:
        for one in missing:
            one["interval"] = interval
        return

    gaps: dict[int, int] = {}
    for before, after in itertools.pairwise(batch):
        gap = after["dateTime"] - before["dateTime"]
        if gap > 0:
            gaps[gap] = gaps.get(gap, 0) + 1
    usual = max(gaps, key=lambda gap: gaps[gap]) if gaps else 300

    previous: int | None = None
    for one in batch:
        if one.get("interval") is None:
            gap = (one["dateTime"] - previous) if previous else 0
            one["interval"] = (gap if gap > 0 else usual) / 60.0
        previous = one["dateTime"]

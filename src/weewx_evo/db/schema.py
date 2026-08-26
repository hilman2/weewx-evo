"""What a WeeWX database actually looks like, read from the database itself.

WeeWX ships schema files, but they only ever seed a *new* database. After
that the schema lives in the file: installations add columns for sensors they
own, and an extension can add more at any time. Anything that reads a real
installation must ask the file, not the shipped list. This module does the
asking.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# The daily summary tables. Transcribed from weewx.manager.DaySummaryManager.
DAY_COLUMNS = {
    "scalar": ("dateTime", "min", "mintime", "max", "maxtime",
               "sum", "count", "wsum", "sumtime"),
    "vector": ("dateTime", "min", "mintime", "max", "maxtime",
               "sum", "count", "wsum", "sumtime",
               "max_dir", "xsum", "ysum", "dirsumtime", "squaresum", "wsquaresum"),
}

# The statistics tuple, in the order the accumulator classes expect. The
# daily tables carry `dateTime` as their key, so it is not part of the tuple.
STATS_COLUMNS = {kind: cols[1:] for kind, cols in DAY_COLUMNS.items()}

DAY_SUMMARY_VERSION = "4.0"


@dataclass(frozen=True, slots=True)
class Schema:
    """The shape of one WeeWX archive database."""

    table_name: str
    columns: tuple[str, ...]
    day_types: dict[str, str]  # observation type -> 'scalar' | 'vector'
    metadata: dict[str, str]

    @property
    def version(self) -> str | None:
        """The daily-summary version. 4.0 is current; anything below needs a patch.

        See weewx.manager.patch_sums: 4.2.0 read V2 sums as V1, and 4.3.0's fix
        left `dirsumtime` unweighted. A database at 1.0-3.0 carries the damage.
        """
        return self.metadata.get("Version")

    def has_column(self, name: str) -> bool:
        return name in self.columns


def _table_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in conn.execute(f"PRAGMA table_info({table})"))


def read(conn: sqlite3.Connection, table_name: str = "archive") -> Schema:
    """Read the schema of an existing archive database."""
    columns = _table_columns(conn, table_name)
    if not columns:
        raise ValueError(f"no table {table_name!r} in this database")

    prefix = f"{table_name}_day_"
    day_types: dict[str, str] = {}
    names = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE ? || '%'",
        (prefix,),
    ).fetchall()
    for (name,) in names:
        obs_type = name[len(prefix):]
        if obs_type == "_metadata":
            continue
        cols = _table_columns(conn, name)
        # A vector table is the scalar one plus the six wind columns. Deciding
        # by column count would break the day an extension adds one.
        day_types[obs_type] = "vector" if "xsum" in cols else "scalar"

    metadata: dict[str, str] = {}
    try:
        metadata = dict(conn.execute(f"SELECT name, value FROM {table_name}_day__metadata"))
    except sqlite3.OperationalError:
        # A database with no daily summaries at all. Legal: they are a cache.
        pass

    return Schema(table_name=table_name, columns=columns,
                  day_types=day_types, metadata=metadata)

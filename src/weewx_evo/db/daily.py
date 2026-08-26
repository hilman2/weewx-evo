"""Building the daily summaries.

The `archive_day_*` tables are a cache. Every number in them is derivable from
the `archive` table, and this module is the derivation. That property is worth
protecting: it means a crash, a late packet, or a corrected calibration costs a
recomputation and nothing else.

The weighting is the part that must not drift. Each record contributes
`60 * interval` seconds of weight, so an installation that changed its archive
interval still averages correctly across the change.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from ..aggregate import Accumulator, start_of_archive_day
from ..obstypes import DEFAULT_POLICY, Policy
from .schema import STATS_COLUMNS, Schema


class IntervalError(ValueError):
    """A record whose `interval` cannot be turned into a weight."""


def weight_of(record: dict) -> float:
    """The weight one archive record carries in a daily summary.

    WeeWX uses this for daily-summary version 2.0 and up; version 1.0 weighted
    every record equally, which is the bug `patch_sums` exists to repair.
    """
    if "interval" not in record:
        raise IntervalError("record has no 'interval'")
    interval = record["interval"]
    if interval is None or interval <= 0:
        raise IntervalError(f"non-positive 'interval': {interval!r}")
    return 60.0 * interval


def day_accumulator(sod_ts: int, unit_system: int | None = None,
                    policy: Policy = DEFAULT_POLICY) -> Accumulator:
    """An accumulator spanning one archive day, starting at `sod_ts`."""
    return Accumulator(sod_ts, sod_ts + 86400, unit_system=unit_system, policy=policy)


def build(records: Iterator[dict], policy: Policy = DEFAULT_POLICY,
          on_bad_interval: str = "skip") -> Iterator[tuple[int, Accumulator]]:
    """Fold archive records into one accumulator per day.

    Records must arrive in ascending time order -- the same order the archive
    table's primary key gives them. Each day is yielded once it is complete, so
    a decade of data does not have to fit in memory at once.

    `on_bad_interval` is 'skip' (WeeWX's behaviour: log and drop the record) or
    'raise'.
    """
    current_sod: int | None = None
    accum: Accumulator | None = None

    for record in records:
        sod = start_of_archive_day(record["dateTime"])
        if sod != current_sod:
            if accum is not None:
                yield current_sod, accum  # type: ignore[misc]
            current_sod, accum = sod, day_accumulator(sod, policy=policy)

        try:
            weight = weight_of(record)
        except IntervalError:
            if on_bad_interval == "raise":
                raise
            continue

        assert accum is not None
        accum.add_record(record, weight=weight)

    if accum is not None:
        yield current_sod, accum  # type: ignore[misc]


def read_day(conn: sqlite3.Connection, schema: Schema, obs_type: str,
             sod_ts: int) -> tuple | None:
    """Read one day's stored statistics for one observation type."""
    kind = schema.day_types[obs_type]
    cols = ", ".join(f'"{c}"' for c in STATS_COLUMNS[kind])
    row = conn.execute(
        f"SELECT {cols} FROM {schema.table_name}_day_{obs_type} WHERE dateTime = ?",
        (sod_ts,),
    ).fetchone()
    return tuple(row) if row else None


def read_records(conn: sqlite3.Connection, schema: Schema,
                 start: float | None = None, stop: float | None = None) -> Iterator[dict]:
    """Read archive records in time order, dropping the columns that are NULL.

    Dropping nulls matters: the accumulator distinguishes "no value" from
    "value of None", and a record padded out to all 134 columns would create
    daily-summary rows for sensors this station has never had.
    """
    where, params = "", []
    if start is not None:
        where, params = "WHERE dateTime > ?", [start]
        if stop is not None:
            where, params = "WHERE dateTime > ? AND dateTime <= ?", [start, stop]
    elif stop is not None:
        where, params = "WHERE dateTime <= ?", [stop]

    cursor = conn.execute(
        f"SELECT * FROM {schema.table_name} {where} ORDER BY dateTime", params
    )
    columns = [d[0] for d in cursor.description]
    for row in cursor:
        yield {col: val for col, val in zip(columns, row) if val is not None}

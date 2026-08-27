# Daily summaries

`db/daily.py`. The `archive_day_*` tables.

> **`archive_day_*` is a cache.** Every number in it is derivable from the
> `archive` table, and this module is the derivation.

That property is worth protecting: it means a crash, a late packet or a
corrected calibration cost a recomputation and nothing else.

One qualification, and it is the reason for the [live
table](Database-Live): with `loop_hilo = true`, LOOP extremes that are **not**
in the archive table go in as well. Rebuilding from the archive alone is
therefore correct, but duller.
→ [Aggregation](Aggregation#what-the-difference-test-checks)

## One table per observation

```
archive_day_outTemp      dateTime, min, mintime, max, maxtime,
                         sum, count, wsum, sumtime
archive_day_wind         … plus xsum, ysum, dirsumtime,
                         squaresum, wsquaresum, max_dir
archive_day__metadata    lastUpdate, Version, driver state
```

`dateTime` is the start of the local day (`start_of_archive_day`) and the
primary key. **Days are local days**, not blocks of 86400 seconds.

## The weighting

This is the part that must not drift.

```python
def weight_of(record) -> float:
    """60 * interval — seconds this record stands for."""
```

Every record contributes `60 * interval` seconds of weight. WeeWX has used this
since daily-summary version 2.0; version 1.0 weighted every record equally,
which is the bug `patch_sums` exists to repair.

That is exactly why old and new records average together correctly when an
installation's archive interval has changed.

`IntervalError` is raised when an `interval` cannot be turned into a weight.
`build(..., on_bad_interval="skip")` leaves such records out instead of letting
the whole derivation fail.

## The functions

| | |
|---|---|
| `weight_of(record)` | The weight of a record |
| `day_accumulator(sod_ts, unit_system, policy)` | An accumulator over exactly one archive day |
| `build(records, policy, on_bad_interval="skip")` | Fold archive records into one accumulator per day |
| `read_day(conn, schema, obs_type, sod_ts)` | Read a stored day row |
| `read_records(conn, schema, start, stop)` | Archive records in time order, without the NULL columns |

### `build` is a generator

Records have to arrive in ascending time order — the same order the archive
table's primary key delivers. Each day is yielded as soon as it is complete, so
that a decade of data does not have to go into memory as a whole.

### `read_records` leaves NULLs out

That is not an optimisation, it is correct: the accumulator distinguishes "no
value" from "value `None`". A record padded out to all 134 columns would create
daily-summary rows for sensors this station never had — rows full of zeroes for
readings that never existed.

## Which route when

| Situation | What happens |
|---|---|
| A new archive record | `ArchiveStore._apply_daily()` folds it into its day |
| Afterwards, with `loop_hilo` | `Archiver._sharpen_day()` lays the LOOP extremes over it |
| `rebuild <from> <to>` | `rebuild_day()` for every affected day, then sharpened again |
| A record is replaced | `_unapply_daily()`, then `_apply_daily()` — **only the sums** come back out |

Extremes are not reversible. A maximum does not remember what the second-highest
value was. Anyone who has to correct extremes needs `rebuild_day`.

## What they are good for in operation

`series.py` answers an aggregate from the daily summaries whenever the span
falls on whole local days: a month of daily maxima is 30 rows via the primary
key instead of a month of archive records.

And they are the *better* extremes — taken from the live packets, so a gust
between two archive records is in there. → [Series](Series)

<!-- covers
src/weewx_evo/db/daily.py
-->

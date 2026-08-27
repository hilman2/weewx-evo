# Archiver

`archiver.py` is the service that replaces WeeWX's `StdArchive`.

The difference is not *what* it computes, but **where it takes it from**. WeeWX
accumulates in memory as packets arrive and writes the result once at the end of
the interval. A restart in the middle loses the interval, and a late packet has
nowhere to go. Here the packets are already in the live table, so an archive
record is a function of a timespan — and that function can be run at any time,
any number of times, in any order, with the same result.

## `Built`

A computed interval, before it is written.

| Field | What it means |
|---|---|
| `stop` | End of the interval, the record's timestamp |
| `seconds` | Length of the interval |
| `record` | The archive record, as a `dict` |
| `accumulator` | The accumulator behind it, for sharpening the day's values |
| `packets` | How many packets went into it |
| `from_hardware` | Whether the console delivered an archive record itself |
| `provenance` | Which field came from which source → [Multiple-Sources](Multiple-Sources) |

## The path of an interval

```python
archiver = Archiver(live, archive, interval_seconds=300,
                    policy=DEFAULT_POLICY, loop_hilo=True, sources=policy)
built = archiver.build(stop)
archiver.store(built)
```

### `build(stop, seconds=None)`

1. Fetch the packets in `(stop - seconds, stop]`
2. Determine the winning source per field via `sources.apply()`
3. Feed an `Accumulator`
4. Pull out a record, apply `derive`

Returns `None` if no packet fell into the interval. **A gap in the data is a gap
in the archive** — inventing a record for it would be a claim about weather
nobody measured.

### `store(built, replace=False)`

The order matters:

1. The record goes in **first** and carries the sums.
2. The accumulator is folded in **afterwards** and touches only extremes.

The other way round, every sum would arrive twice.

### `_sharpen_day(built)`

This is WeeWX's `_updateHiLo`. Only extremes move: the accumulator's sums have
already reached the day by way of the archive record.

That puts the LOOP extremes into `archive_day_*` — a gust between two archive
records is kept. Can be turned off with `loop_hilo = false`, and then the daily
extremes are exactly reproducible from the archive alone.

## Modes of operation

### `process_due(now=None, grace=15, replace=False)`

Builds and stores every interval that has closed. Returns how many.

**Callable at any time and interruptible at any time**: an interval is only
struck from `pending` once its record is in the database.

`grace` holds an interval back for a few seconds after it ends, so that a merely
slow packet does not cause the record to be computed twice.

### `catch_up(since=None, until=None, replace=False)`

Builds every interval the live table covers. At startup, after an outage, and in
the difference test. Unlike `process_due`, this ignores the `pending` list and
works straight off the packets.

```bash
weewx-evo catchup
```

### `rebuild(start, stop)`

Recomputes every interval in `(start, stop]` and replaces what is there.
Afterwards the daily summaries of every affected day are rebuilt from the
archive table and then sharpened from the packets again.

```bash
weewx-evo rebuild <from> <to>
```

This is what makes a correction possible: change the calibration, rebuild, and
the statistics follow. The prerequisite is that the raw packets are still within
retention. → [Database-Live](Database-Live)

### `run(grace=15, poll=5.0, stop_when=None)`

The loop. A plain sleep loop, no scheduler: the work is idempotent and the
interval boundaries come from the packets, so a tick arriving late or not at all
changes nothing.

## What else the archiver sets off

After every record written:

- `feedrunner.Runner.record_written()` — sets a flag and returns.
  → [Feeds](Feeds)
- `exports.runner.Runner.record_written()` — likewise. → [Exports](Exports)

Both only set flags. **Nothing about an upload or a plot happens on the
archiver's thread**, because that would be a second per interval in which it is
not archiving.

Retention runs here too: `LiveStore.prune()` throws away packets older than the
retention period, writing them out as gzip NDJSON first if `spool` is set.

> Retention belongs to the **archiver**, not to the listener. Packets may only
> be dropped once they are in a record, and only that side knows.

## An archive record from the hardware

Some consoles deliver archive records themselves (`kind = "archive"`). The
accumulator is then not discarded but laid over it via `Accumulator.augment()`:
the console's record keeps its hardware-computed fields and gains the ones it
does not deliver. `from_hardware` remembers that this is what happened.

<!-- covers
src/weewx_evo/archiver.py
tools/roundtrip.py
-->

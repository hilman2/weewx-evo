# The live database

`db/live.py`. Every packet that ever arrived, kept for a while. This is the
store that replaces WeeWX's in-memory accumulator.

A packet is written here the moment it arrives, and nothing else happens to it.
Archive records are computed from this table **afterwards** — which is exactly
what makes them reproducible: the same packets always give the same record,
whether aggregated now, after a restart or a week later.

Its own file, so that size and retention have nothing to do with the archive.
The archive database stays small and easy to back up.

## Size

Measured on a console sending a packet every 8 s: around **11 MB per day**, so
about 80 MB at seven days of retention. A Vantage with a LOOP packet every 2 s
is four times that.

## The schema

```sql
CREATE TABLE IF NOT EXISTS packet (
    seq       INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    dateTime  INTEGER NOT NULL,
    …
);
```

| Column | What it means |
|---|---|
| `seq` | Sequential, the primary key |
| `dateTime` | The time of the reading, as the packet gives it |
| `usUnits` | Unit system, `1` / `16` / `17` → [Units](Units) |
| `data` | The readings, as JSON |
| `source` | Which station it came from → [Multiple-Sources](Multiple-Sources) |
| `kind` | `loop` or `archive` |
| `interval` | If the packet carries a span |
| `received` | Time of arrival, independent of the time of the reading |
| `raw` | The upload as it came off the wire — only for a while |

Alongside that, a `meta` table and a `pending` list.

## `Packet`

One reading, as it arrived, before anything was done to it.

```python
Packet(dateTime=1787734265, usUnits=1, data={"outTemp": 21.4},
       source="garden", kind="loop", interval=None,
       received=1787734266, raw=None)
```

| Method | What it means |
|---|---|
| `digest()` | A short hash of the payload, so a retransmission is not a new packet |
| `record()` | The packet as an observation record, ready for the accumulator |

## `LiveStore`

```python
store = LiveStore("data/live.sdb", interval_seconds=300, keep_raw_seconds=3600)
```

### Writing

| Method | What it means |
|---|---|
| `add(packet)` | One packet. Returns `False` if it was already there |
| `add_all(packets)` | Many in one transaction. Returns how many were new |

**Idempotent on `(source, kind, dateTime, payload)`.** A console retrying an
upload is not counted twice. This is not a flourish: Ecowitt devices retry when
no response comes, and a packet counted twice shifts every weighted mean of the
interval.

### Reading

| Method | What it means |
|---|---|
| `packets(start, stop, kind=None, with_raw=False)` | Every packet in `(start, stop]`, in time order |
| `raw_of(seq)` | A packet together with its raw upload, if it is still there |
| `span()` | First and last timestamp |
| `count()` | |

`with_raw` is **off by default**: the archiver runs over thousands of packets
and has no use for it, and that column is the big one.

### Intervals

| Method | What it means |
|---|---|
| `mark_pending(ts, seconds=None)` | Note that the interval around `ts` needs computing |
| `clear_pending(stop)` | |
| `due(now=None, grace=15)` | Intervals that have closed, oldest first |

`interval_stop(ts, seconds)` (a module function) says which interval a timestamp
belongs to. Intervals are **half-open at the start**: a packet exactly on a
boundary closes the interval that ends there, rather than opening the next one.
The same convention as in the [accumulator](Aggregation).

`grace` holds an interval back for a few seconds after it ends, so that a merely
slow packet does not cause a record to be computed twice.

### Tidying up

| Method | What it means |
|---|---|
| `forget_raw(before)` | Discard the raw uploads, keep the packets |
| `prune(before, archive_dir=None)` | Throw away packets older than `before`, optionally writing them out first |

`forget_raw` goes by **arrival time**, not by reading time: a packet that
arrived late should be allowed to keep its raw upload a while longer.

`prune` with `archive_dir` writes out every day leaving the table as gzip NDJSON
first (`_spool`). Nothing is deleted before the file has been written.

```bash
weewx-evo archive --spool /data/packets
```

### Connections

`conn()` opens its own connection **per thread** on first use. SQLite
connections are thread-bound — that was a real bug that would never have shown
up in a browser, and is now part of the design. → [Testing](Testing)

### Migration

`_migrate()` brings an older file up to date, **additively only**. This file is
a cache with a few days in it, so a migration going wrong would cost little —
but the packets are what makes a record reproducible, so nothing is taken away
regardless.

## Why this justifies the live table

The measurable case is in the [Testing](Testing) chapter: in a real database
there was an `outTemp` minimum of 17.6 °F and a maximum of 96.8 °F, eight
minutes apart, late one August evening. Both of them rubbish from a period of
rebuilding — and both permanently in the statistics, because the LOOP packets
are gone. `weectl database rebuild-daily` would remove them and take every
**real** LOOP extreme of the whole period with them.

As long as the packets are here, the two can be told apart.

<!-- covers
src/weewx_evo/db/live.py
-->

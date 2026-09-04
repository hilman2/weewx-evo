# The live database

`db/live.py`. Every reading that ever arrived, kept for a while. This is the
store that replaces WeeWX's in-memory accumulator.

A packet is written here the moment it arrives, and nothing else happens to it.
Archive records are computed from this table **afterwards** — which is exactly
what makes them reproducible: the same packets always give the same record,
whether aggregated now, after a restart or a week later.

Its own file, so that size and retention have nothing to do with the archive.
The archive database stays small and easy to back up.

## It is a sensor journal

`data` holds the readings under the names the console sent them with, and
`dialect` says which vocabulary that is. `mapping` refers to the versioned,
declarative JSON description needed to interpret it. Nothing here has been placed into an
archive column, and nothing has been left out — a field two drivers disagree
about, one no catalog knows, one you have deliberately placed nowhere, an
indoor temperature you do not want recorded: they are all in this table.

Which of them reaches an archive, and under which column, is read out of
`placement.toml` when the record is built → [Placements](Placements).

That is what makes a placement repairable. Change the line, rebuild the span,
and the archive follows — for as far back as the retention period reaches.

A packet from a collector, from the WeeWX shim or from any driver somebody
else wrote has no dialect: its names are already WeeWX's, which is what the
envelope promises → [Drivers](Drivers).

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
| `data` | The readings, as JSON, under the names the console used |
| `dialect` | Which vocabulary those names belong to; empty means WeeWX's |
| `mapping` | SHA-256 reference to its inert description in `dialect_mapping`; empty with no dialect |
| `driver` | Which plugin read it |
| `identity` | What the hardware calls itself: a PASSKEY, a serial, a station id |
| `sender` | Canonical, versioned ID derived from `driver` and `identity`; the key Places select |
| `kind` | `loop` or `archive` |
| `interval` | If the packet carries a span |
| `received` | Time of arrival, independent of the time of the reading |
| `raw` | The upload as it came off the wire — only for a while |

Alongside that are `live_metadata`, `pending`, `sender_identity` and
`dialect_mapping(digest, spec)`. A large console catalog can be 26 KiB; keeping
it once rather than on every packet preserves the journal's measured size.

There is no mutable display-name routing key. `sender` is derived from the
driver and hardware identity and stored with every packet. `sender_identity`
holds presentation metadata. Renaming or adopting a sender therefore does not
split its raw history. Archive membership is separate: each Place selects
canonical sender IDs from this database.

## `Packet`

One reading, as it arrived, before anything was done to it.

```python
Packet(dateTime=1787734265, usUnits=1, data={"tempf": 70.5},
       driver="ecowitt", identity="3178AB6B…", dialect="ecowitt",
       mapping={"version": 1, "fields": {"tempf": "outTemp"}, …},
       kind="loop", interval=None, received=1787734266, raw=None)
```

| Method | What it means |
|---|---|
| `digest()` | A short hash of the measurements, so a retransmission is not a new packet |
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
first (`_spool`). The mapping reference is expanded into its JSON description,
so the file remains self-contained. Nothing is deleted before the file has
been written.

```bash
weewx-evo archive --spool /data/packets
```

### Connections

`conn()` opens its own connection **per thread** on first use. SQLite
connections are thread-bound — that was a real bug that would never have shown
up in a browser, and is now part of the design. → [Testing](Testing)

### A row nothing can translate

A packet naming a dialect whose description is not stored is an old row or a
damaged one. It stays visible with its raw field names, and the archiver
reports and skips it: treating a coincidentally familiar name as `outTemp`
without knowing its scale or units would turn an honest gap into plausible
false history.

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

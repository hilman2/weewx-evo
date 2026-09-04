# The archive database

`db/archive.py`, `db/schema.py`, `db/wview.py`.

Everything here is written so that WeeWX 5 can pick the file back up afterwards
without noticing that anyone else was in it.

## The three rules

1. **Columns come from the file, never from a list in this code.** An
   installation with sensors we have never heard of keeps them.
2. **Readings the database has no column for are dropped, not created.**
   Creating a column changes the schema, and that is a decision a person makes —
   the wrong one mixes two sensors into a column nobody can separate afterwards.
3. **A dropped reading is reported**, once per field.

## `db/schema.py` — reading the schema from the file

WeeWX ships schema files, but those only set up a **new** database. After that
the schema lives in the file: installations add columns for sensors of their
own, and an extension can add more at any time. Anything reading a real
installation has to ask the file, not the shipped list.

```python
schema = db.schema.read(conn, table_name="archive")
```

```python
@dataclass
class Schema:
    table_name: str
    columns: tuple[str, ...]          # the columns of the archive table
    day_types: dict[str, str]         # obs_type -> scalar | vector
    metadata: dict[str, str]
```

| | |
|---|---|
| `version()` | The daily-summary version. `4.0` is current |
| `has_column(name)` | |

`DAY_COLUMNS` says which columns an `archive_day_*` table has, depending on
whether it is scalar or vector. → [Daily-Summaries](Daily-Summaries)

### The version check

`ArchiveStore._check_version()` **refuses** a database whose daily summaries
carry known-bad weights:

- WeeWX 4.2.0 read version-2 sums as version 1.
- The repair in 4.3.0 left `dirsumtime` unweighted.

Both are fixable, but by WeeWX, not from here: `weectl database
rebuild-daily`. Carrying on writing to such a file silently would mean mixing
wrong weights with right ones.

## `db/wview.py` — the starting schema

The schema WeeWX sets a new database up with, generated from
`weewx/schemas/wview_extended.py` (WeeWX 5.5.0), 113 observation columns.

It is used **only** to create a database that does not exist yet. Once a file is
there, its schema comes from the file.

## `ArchiveStore`

```python
with ArchiveStore("data/weewx.sdb", table_name="archive",
                  policy=DEFAULT_POLICY, create=True) as store:
    store.add_record(record)
```

### Reading

| Method | What it means |
|---|---|
| `last_timestamp()` | |
| `count()` | |
| `exists(ts)` | |
| `record(ts)` | One record |
| `days()` | Every archive day with records, in order |
| `get_meta(name)` | From the `archive_day__metadata` table |

### Writing

| Method | What it means |
|---|---|
| `add_record(record, replace=False, update_daily=True)` | Write a record and fold it into the daily summaries. `False` if one for that timestamp was already there |
| `add_records(records, replace=False)` | Many records, touching the daily summaries **once per day** |
| `set_meta(name, value)` | |

`add_records` is why catching up over months is bearable: WeeWX reads and
rewrites every daily-summary table of a day for **each individual** record. At
one record every five minutes you do not notice; on a catch-up over a year you
do.

`set_meta` also supports the isolated `ArchiveState` adapter. The production
Listener never opens an archive: sender identity is stored with each live
packet, and Place membership selects what the Archiver reads.
→ [Drivers](Drivers#driver-state), [Architecture](Architecture)

### Columns

| Method | What it means |
|---|---|
| `homeless()` | Fields dropped for want of a column, and how often — since process start |
| `add_column(name, sql_type="REAL")` | Give a reading somewhere to live. `False` if it already has one |

`_note_homeless()` says **once per field** that a reading has nowhere to go.
Once, not on every packet: a log writing the same line every eight seconds
becomes a log nobody reads.

WeeWX reads its schema from the file, so it picks up a column created here on
its own. **Back up first.**

```bash
weewx-evo columns          # what is missing
weewx-evo columns --add    # create them
```

### Daily summaries

| Method | What it means |
|---|---|
| `_apply_daily(record)` | Fold a record into its day |
| `_unapply_daily(record)` | Take its contribution back out |
| `_load_day(sod, unit_system)` | A day's accumulator, prepared with every type the database knows |
| `_store_day(sod, accum)` | |
| `rebuild_day(sod)` | Recompute a day from the archive table |

**`_unapply_daily` takes only the sums back out.** Extremes are not reversible —
a maximum does not remember what the second-highest value was. Anyone wanting to
correct extremes needs `rebuild_day`.

`_load_day` prepares types without a stored row as **empty** rather than leaving
them out. That is deliberate: WeeWX writes a row for every observation it knows,
and a missing row would be a difference WeeWX would notice.

`rebuild_day` is what makes a correction possible — and what dulls every LOOP
extreme of that day, because the packets are no longer counted in. The archiver
sharpens afterwards from the live table, as far as it reaches.
→ [Archiver](Archiver), [Daily-Summaries](Daily-Summaries)

## Checking that nothing slips

```bash
python tools/difftest.py reference/weewx.sdb    # the arithmetic
python tools/roundtrip.py reference/weewx.sdb   # the writing
```

`roundtrip.py` takes a copy of a real database, deletes the last N days from it
— archive records and daily summaries — and writes them back over the normal
write path, record by record, exactly as the archiver would on a catch-up. Every
row of every table is compared afterwards.

→ [Testing](Testing)

<!-- covers
src/weewx_evo/db/archive.py
src/weewx_evo/db/schema.py
src/weewx_evo/db/wview.py
-->

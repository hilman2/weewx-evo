# WeeWX compatibility

## The one rule

> An existing WeeWX database stays readable and writable — **by WeeWX itself**.
> Not "importable": the same file, the same meaning, and WeeWX 5 can carry on
> using it afterwards.

Everything else is negotiable. This is not.

## What is shared and what is not

| | |
|---|---|
| **The database** | Shared. The same file, the same meaning |
| **The configuration** | Not shared. `weewx.conf` is **read, never written** |

Two programs writing one configuration file destroy each other's comments.
`weewx.conf` is therefore only read. Its archive path, location and altitude
can seed the first `archives.toml` once; afterwards every place, including the
first, is read only from that file. Process settings such as the archive
interval may continue to fall back to `weewx.conf`.

## How the compatibility is achieved

### 1. The schema comes from the file

`db/schema.py` reads it from the open database, not from a list in the code. An
installation with sensors we have never heard of keeps them.

`db/wview.py` — the shipped starting schema — is used **only** to create a
database that does not exist yet.

→ [Database-Archive](Database-Archive)

### 2. The arithmetic is transcribed

`aggregate.py` is a transcription of `weewx.accum`, step by step in the same
order. `units.py` is a transcription of `weewx.units`, expression by expression.

A "cleaner" formula that rounds differently is a wrong formula here.

→ [Aggregation](Aggregation), [Units](Units)

### 3. The weighting is WeeWX's

Every record contributes `60 * interval` seconds of weight to the daily
summaries. That is version 2.0 and up; version 1.0 weighted equally, and that is
the bug `patch_sums` exists to repair.

→ [Daily-Summaries](Daily-Summaries)

### 4. The edge cases are WeeWX's

- A record exactly at midnight closes the **previous** day.
- A record exactly on an interval boundary closes the interval that ends there.
- Wind chill below 10 °C and above 4.8 km/h, otherwise the temperature itself.
- Heat index below 40 °F is the temperature.
- A speed without a direction is not a vector and is discarded.

### 5. Even the bugs are inherited

WeeWX's conversion table is **not self-inverse**: `mph → kph` uses 1.609344,
`kph → mph` uses 1000/1609.34. 52 pairs do not come back exactly.

`tools/unitcheck.py` checks that **our drift is their drift**, not that there is
none.

## What is checked

| Tool | What |
|---|---|
| `tools/difftest.py` | Recompute the daily summaries of a real database |
| `tools/roundtrip.py` | Rewrite part of one and check that nothing moves |
| `tools/unitcheck.py` | Every conversion against WeeWX |
| `tools/seriestest.py` | Fetch the same series from both and compare |
| `tools/derive_test.py` | The derived readings against what WeeWX wrote |
| `tools/suncheck.py` | Solar times against pyephem and against `weeutil.Sun` |

→ [Testing](Testing)

## What is refused

`ArchiveStore._check_version()` **will not open a database** whose daily
summaries carry known-bad weights:

- WeeWX 4.2.0 read version-2 sums as version 1.
- The repair in 4.3.0 left `dirsumtime` unweighted.

Both are fixable, but **by WeeWX**: `weectl database rebuild-daily`. Carrying on
writing to such a file silently would mean mixing wrong weights with right ones.

## Reading `weewx.conf`

`weewxconf.py`. A parser of our own, because `configobj` would be a dependency
and weewx-evo has none.

| Function | What it means |
|---|---|
| `parse(text)` | As nested dictionaries. Values stay strings |
| `read(path)` | |
| `convert(conf, driver_names)` | Into weewx-evo settings, with a report |
| `report(result, source)` | What the import did, to be read **before** trusting it |

**Types are the caller's business**: `altitude = 440, meter` is a length and a
unit, and only something that knows what `altitude` means can turn that into
metres.

`_splits()` decides whether a value is a list. The case that makes it hard:

```ini
chart_line_colors = "#4282b4", "#b44242"
```

That begins and ends with a quotation mark and is five values regardless. **Only
a comma outside the quotation marks decides.**

### What is taken over

```bash
weewx-evo config import /etc/weewx/weewx.conf
weewx-evo config import /etc/weewx/weewx.conf --write
weewx-evo config import /etc/weewx/weewx.conf --write --overwrite
```

| | |
|---|---|
| `[Station]` | Name, latitude, longitude and altitude, to write `[archives.default]` where there is none (`_altitude_metres` converts feet) |
| `[DataBindings]` / `[Databases]` | `_databases()` finds the SQLite file for it |
| `[StdArchive]` | Archive interval, `loop_hilo` |
| The driver | `_driver()` works out which one is in use and brings its settings along |
| `[Accumulator]` | `_accumulators()` — see below |

If `archives.toml` already exists, the first two rows do not update it. Place
and database settings have one owner and cannot silently change because a
legacy file or environment variable still contains another value.

### `[Accumulator]` is special

**It is the one part of `weewx.conf` that changes recorded numbers rather than
behaviour.** An extractor decides whether a field is averaged or summed over an
interval. Overlooking it means the same station records two different numbers in
two systems.

→ [Aggregation](Aggregation#obstypes)

### What is not taken over — and why

`_NOT_OURS` names each of them:

| Section | Reason |
|---|---|
| `[StdReport]` | Report generation, which weewx-evo does not (yet) do |
| `[StdRESTful]` | Uploads to weather services — see [Uploads](Uploads) |
| … | |

**Silence reads like "lost".** The report names what was left behind, and says
why.

## The plots

```bash
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf --write
```

Two pitfalls, both of them real:

- **WeeWX's suffixes are not ours.** There, `M` is a minute and `m` is a
  *month*. A file written for WeeWX is read by WeeWX's rules — and nothing is
  ever written back with an ambiguous suffix.
- **`skip_if_empty = year` is a timespan, not a boolean.** Read as a boolean,
  the Seasons set writes 100 files instead of 71.

→ [Plots](Plots#two-pitfalls-in-the-importer)

## What WeeWX can do and weewx-evo cannot

- **Reports and skins.** The generator side is out of scope. The JSON feed is
  the foundation a skin could be built on.
- **RESTful uploads** to weather services.
- **Pull drivers** for serial hardware — the interface is there
  (`listener.push()`), the drivers are not.

## What weewx-evo can do and WeeWX cannot

| | |
|---|---|
| A restart mid-interval costs nothing | There is no in-memory accumulator to lose |
| A late push packet lands in the right interval | It is placed by its timestamp, not by its arrival |
| Correction after the fact | As long as the raw packets are within retention |
| Several sources with no wrapper driver | Merged while the interval is built, field by field → [Multiple-Sources](Multiple-Sources) |
| Listener and archiver can run separately | With no code change |
| Anything without a column is **reported** | `weewx-evo columns` |
| Plot definitions do not belong to the renderer | → [Plots](Plots) |
| Feed and export are separate | → [Feeds](Feeds), [Exports](Exports) |

## One deliberate departure

**A mean here is always weighted by `interval`.** WeeWX weights that way in the
daily summaries, but uses a plain `AVG()` on the archive table — so in a database
whose archive interval has changed, WeeWX contradicts itself.

→ [Series](Series#one-deliberate-departure), which has the measurement.

## Running side by side

Both systems can feed the same station and keep their archives comparable record
by record. In practice that means a source passing the raw body on to two
destinations, each with a **pause of its own**, so that an outage of one does
not take the other with it.

Letting both **write** to the same database at the same time is a different
thing and is not provided for.

<!-- covers
src/weewx_evo/weewxconf.py
src/weewx_evo/db/wview.py
-->

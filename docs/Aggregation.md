# Aggregation

`aggregate.py` is the core: raw values in, statistics out. No state, no
database, no clock.

> **`aggregate.py` is a transcription of `weewx.accum`, not a
> reinterpretation.** Every step of the arithmetic is in the same order and the
> same form, because these numbers end up in `archive_day_*` tables that WeeWX
> has to carry on reading. A "cleaner" formula that rounds differently is a
> **wrong** formula here.

Before any change:

```bash
python tools/difftest.py reference/weewx.sdb
```

→ [Testing](Testing)

## Two deliberate departures from the original

1. **No global state.** WeeWX keeps the aggregation policy in a global
   `ChainMap` that modules mutate on import (`weewx.accum.accum_dict`). Here it
   is an ordinary object you pass around — which is exactly what makes the
   difference test against a real database possible, because two policies can
   exist at the same time. → [`obstypes.py`](#obstypes)
2. **No WeeWX imports.** The file stands on its own.

## The accumulators

Three classes, one per sort of observation.

### `FirstLast`

The minimal one. Remembers the first and the last value it saw. Computes
nothing, which is why it also works for strings.

`set_stats()` is deliberately a no-op: nothing this class holds survives a
round through the database.

### `Scalar`

Minimum, maximum and a **weighted** mean.

| Field | What it means |
|---|---|
| `min`, `mintime` | Lowest value and when |
| `max`, `maxtime` | Highest value and when |
| `sum`, `count` | Sum and count |
| `wsum`, `sumtime` | Weighted sum and total weight |

`wsum` and `sumtime` are what makes a mean over an arbitrary period possible at
all later on: the sum is weighted by how long each value stood. Records of
different interval lengths therefore average together correctly.
→ [Daily-Summaries](Daily-Summaries)

### `Vector`

For wind: the scalar statistics plus the vector sums.

| Field | What it means |
|---|---|
| `xsum`, `ysum` | East and north components, summed |
| `dirsumtime` | Weight that counts **only** for readings with a direction |
| `squaresum`, `wsquaresum` | For the root mean square (RMS) |
| `max_dir` | The direction at the highest value |

`xsum`/`ysum` are the reason a mean *direction* survives being averaged —
adding degrees would not do it. `dirsumtime` counts only readings with a
direction, because a calm with no vane contributes no direction.

Evaluating methods: `avg()`, `rms()`, `vec_avg()`, `vec_dir()`.

## `Accumulator`

Statistics for a set of observations over **one** timespan.

```python
acc = Accumulator(start, stop, policy=DEFAULT_POLICY)
acc.add_record({"dateTime": t, "usUnits": 1, "outTemp": 21.4}, weight=300)
record = acc.record()
```

The span is **half-open at the start**: a record falling exactly on `start`
belongs to the previous span. The same principle as
`start_of_archive_day()` — a record exactly at midnight closes the *previous*
day. WeeWX has always done it this way, and the daily summaries are indexed by
the result.

| Method | What it means |
|---|---|
| `add_record(record, add_hilo=True, weight=1)` | Fold in a record. Raises `ValueError` if it lies outside the span or has a different unit system — both are bugs in the caller, not data |
| `merge_hilo(other)` | Fold in another accumulator's extremes |
| `record()` | Pull out an archive record, stamped with the **end** of the span |
| `augment(record)` | Fill in what the record does not already carry. Existing values win — that is how a console's archive record keeps its hardware-computed fields and gains the missing ones |
| `set_stats(obs_type, tuple)` | Load statistics straight from storage, past the arithmetic. Without a tuple the type is merely created, empty — that is how a day gets a row for an observation that was never measured on it |

### Wind is taken up twice

`_add_wind()`: once as plain `windSpeed`, once as a vector. That is WeeWX's
behaviour and the reason `windSpeed` and `wind` statistics sit side by side in
the same database.

### `_merge_avg`

For `windSpeed`, merging uses the other accumulator's **mean** as its maximum.
The day's high should be the highest *sustained* wind, not the highest
instantaneous reading — that one is in `windGust`.

## `obstypes`

`obstypes.py` says **how** each observation aggregates.

```python
@dataclass
class ObsPolicy:
    accumulator: str   # scalar | vector | firstlast
    adder: str
    merger: str
    extractor: str
```

`Policy` is the policy of a whole installation. `overrides` mirrors the
`[Accumulator]` section of `weewx.conf`: a mapping from observation to the
fields that depart from the default.

> **The defaults are WeeWX's `DEFAULTS_INI` verbatim.** Changing a value here
> changes recorded history.

`DEFAULT_POLICY` is the instance used everywhere no other one was passed in.

`config import` brings an existing `[Accumulator]` section along — it is the one
part of `weewx.conf` that changes recorded numbers rather than behaviour.
→ [WeeWX-Compatibility](WeeWX-Compatibility)

## Helpers

| | |
|---|---|
| `to_float(x)` | WeeWX's `weeutil.to_float`: the string `'none'` is a null value, not an error |
| `_usable(val)` | As a float, or `None` if missing, unparseable or NaN |
| `start_of_archive_day(ts)` | The start of the day an archive record belongs to — midnight closes the previous day |

## What the difference test checks

`tools/difftest.py` rebuilds the daily summaries of a real database and compares
them with what WeeWX wrote into it. Two classes of column, two standards — and
the difference is the point:

- **Sums** (`sum`, `count`, `wsum`, `sumtime`, `xsum`, `ysum`, `dirsumtime`,
  `squaresum`, `wsquaresum`) come exclusively from archive records. They have to
  match **exactly**.
- **Extremes** are allowed to differ. With `loop_hilo = True`, WeeWX writes LOOP
  packets straight into the daily extremes, and those are finer than any archive
  record. A reconstruction can only be equal or **duller** — never sharper.
  Sharper would be a bug, and that is exactly what the test checks.

```
sum mismatches:            0
extremes sharper than DB:  0
extremes duller than DB:   189   (expected: LOOP highs/lows)
```

This asymmetry is the best argument for the live table, and it is measurable:
`roundtrip.py --packets` feeds the stored LOOP packets back in, and where they
cover the period, the number drops accordingly.

→ [Testing](Testing), [Database-Live](Database-Live)

<!-- covers
src/weewx_evo/aggregate.py
src/weewx_evo/obstypes.py
tools/difftest.py
-->

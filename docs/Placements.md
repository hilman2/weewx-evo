# Placements

Where each reading a console sends is written.

A console does not send `outTemp`. It sends `tempf`, or `outtemp`, or
`tf_ch1` — and something has to say which archive column each of those goes
into. That something is `placement.toml`, and it is read **when a record is
built**, not when the upload arrives.

That is the whole point of it. The live table holds what the sensor said
([The live database](Database-Live)); a placement is a decision about it, and a
decision you can change:

| | |
|---|---|
| change a line | the next record follows it |
| `weewx-evo rebuild` | so does every record still covered by the live table |

Before this, the naming happened at the front door and the reading arrived
already named. A field placed in the wrong column had no way back, because the
value under its own name was never stored.

## What a catalog cannot know

`tf_ch1` is a WN34 probe and every Ecowitt catalog agrees. Whether it is in the
compost heap, under the lawn or lying in the sun on a windowsill is known only
to whoever put it there — and usually not until they have watched the numbers
for a week.

So the settings page shows what arrives, under the names the hardware uses,
with what each one last carried. Open **Places → Fields** for the Place and
sender relationship.

## The file

Beside `evo.toml`, and editable by hand.

```toml
[[takes]]
archive = "default"
station = "v1/ecowitt/aabbcc"
dialect = "ecowitt"
[takes.fields]
"tf_ch1"        = "soilTemp1"
"soil_ec_temp1" = "extraTemp9"
"tempinf"       = "-"          # this console stands in the living room
```

| Key | What it means |
|---|---|
| `archive` | Which series the decisions are for. Absent: all of them. |
| `station` | Canonical sender ID. Absent: every sender selected by that Place; an all-arrivals selection also includes one nobody has announced. |
| `dialect` | Which catalog. Absent: all of them. |
| `unlisted` | `catalog` or `nowhere`. What happens to a reading with no line of its own. Default `catalog`. |
| `learned` | Set on a block worked out by inference. Yours are the ones without it. |
| `[takes.fields]` | Raw name → archive column, or `-` for nowhere. |

The narrowest scope wins, field by field, so a Place-wide decision can be
overruled for one sender without repeating the other thirty lines.

`-` and an absent line are different answers. An absent line means "whatever the
catalog says"; `-` means somebody decided this reading is written nowhere.

## `unlisted = "nowhere"`

Only what is listed is written. This is what an extra sender needs: without it
a sensor added to one next year would be placed by the catalog straight into the
main sender's column, silently.

Battery levels and signal strengths come through regardless. Those names already
carry their sensor, so two senders cannot collide on them, and an extra sender
whose battery nobody can see is worse than none.

## Guesses are written down

A raw name no catalog knows is noted the first time it arrives, together with
whatever the driver would make of it. Nothing acts on that by itself: it becomes
a block with `learned = true`, which you can read, change or delete.

That is what `infer_unknown` decides → [Settings A–Z](Settings-Reference).

| | |
|---|---|
| `off` | nothing is promoted. Unplaced names are still listed on the page. |
| `series` | a guess the driver is sure of, because it continues a numbered family it already knows |
| `all` | anything it can name at all |

A `learned` block never overwrites a decision of yours, so a better inference in
a later version cannot quietly undo one.

## `[groups]`

What a column measures, where neither the standard schema nor the driver says.

```toml
[groups]
"soilTemp9" = "group_temperature"
```

Without it a page prints a bare number beside readings it has converted
→ [Units](Units).

## What is not here

`indoor`, `role` and `channel` belong to the sender's membership in one
place and stay under that archive in `archives.toml` → [Stations and
Archives](Stations-and-Archives). They are applied on the same side as a
placement, so changing one and rebuilding works the same way. An explicit
field placement is more specific and wins over the role preset.

<!-- covers
src/weewx_evo/placement.py
src/weewx_evo/ingest/proposals.py
tools/placement_test.py
-->

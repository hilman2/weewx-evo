# Multiple sources

`sources.py`. Several stations, one record.

## Why this is hard in WeeWX

WeeWX knows exactly one `station_type`. Combining two stations there means
writing a driver that wraps drivers —
[weewx-metadriver](https://github.com/tkeffer/weewx-metadriver): worker threads
per child, a shared queue, a `source` key on every packet.

It works, and its limits follow from **where** it sits. A driver merges packets
as they arrive, and by that point the choice has already been made:

- Only the primary driver may deliver archive records.
- Only its clock is read.
- A child that has crashed stays dead.

`tools/multisource.py` checks exactly those three cases.

## How it works here

Here nothing wraps anything. Every source delivers on its own, its packets land
in the live table under its name, and the merge happens only **while the
interval is being built** — when every packet is available, origin and all.

That moves the question from "which driver is in charge" to "which source do I
believe for *this field* in *this interval*".

```
garden (Ecowitt)  ─┐
roof (Vantage)    ─┼─► live.packet (source, dateTime, data)
another one       ─┘        │
                            ▼  while the interval is built
                     sources.apply(packets, policy)
                            │
                            ▼
                     one archive record + provenance
```

## The configuration

```toml
[sources]
outTemp = "garden, roof"     # the garden is the record
"soil*" = "garden"           # only the garden has soil probes
"*"     = "roof, garden"     # everything else: the roof first
```

Also available as its own file (`--sources sources.toml`,
`WEEWX_EVO_SOURCES`). A policy covering a dozen fields is worth keeping apart
from the settings.

**Rules are checked in order, the first match decides.** So put the specific
ones before the general ones.

## The model

```python
@dataclass
class Rule:
    pattern: str            # field name or glob
    order: tuple[str, ...]  # sources, best first

    def matches(self, obs_type: str) -> bool: ...
```

```python
@dataclass
class Policy:
    rules: list[Rule]
    stale_after: int | None
```

| Method | What it means |
|---|---|
| `Policy.from_config(mapping, stale_after=None)` | From the `[sources]` section |
| `is_empty()` | |
| `order_for(obs_type)` | The preference list for a field, or `None` |
| `choose(obs_type, available)` | Which of the sources that *actually* had this field should deliver it |

**`available` is what decides.** It is the set of sources that carried the field
in *this* interval — not the set of configured ones. A station that has failed
does not win by standing at the front of the list.

`stale_after` lets a source drop back after that many seconds without a packet.

## The functions

| | |
|---|---|
| `sources_by_field(packets)` | Which source carried which field |
| `apply(packets, policy)` | Reduce the packets to the winning source per field |
| `replace_data(packet, data)` | A copy of a packet with different readings |

`apply()` returns the packets with their losing fields removed, plus a record of
which source each field came from. Packets left with nothing drop out. The
provenance record ends up in `Built.provenance`. → [Archiver](Archiver)

## The rule applies per field

Not per record. A station that measures temperature and rain but *cannot*
measure snow depth delivers its temperature and its rain; the snow depth comes
from whichever one has it.

## Sources are never averaged

Two thermometers reading 19 °C and 21 °C do not make 20 °C anywhere. They are
two readings of two places, and taking one of them is the only honest answer.
Anyone who wants both gives the second a column of its own —
→ [Database-Archive](Database-Archive#columns).

## What each source can be

Anything that delivers into the live table:

- A driver in the listener, with `source` on the packet
- A second listener on another port
- A pull driver via `listener.push()`
- Something else entirely posting the
  [JSON envelope](Drivers#the-envelope--the-only-driver-in-the-core) to
  `/<token>/json/`

The core knows no difference between them.

## Checking it

```bash
python tools/multisource.py
```

Checks the three cases the metadriver names as its own limits.

<!-- covers
src/weewx_evo/sources.py
tools/multisource.py
-->

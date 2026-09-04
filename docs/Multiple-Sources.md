# Multiple senders

Several senders can feed one Place. They stay separate in the live journal;
the Archiver applies that Place's membership, member roles and field mappings
when it builds an interval.

```
sender A ─┐
sender B ─┼─► live.packet (canonical sender ID, raw data)
sender C ─┘                         │
                                   ▼
                         Place membership
                         role + field mapping
                                   │
                                   ▼
                         one archive record
```

Nothing wraps the drivers and the Listener does not merge packets. A sender
may feed several Places; each Place can interpret the same raw packet
differently.

## The routing authority

- `archives.toml` selects canonical sender IDs for each Place.
- A member's `main` role keeps ordinary mapped readings in their standard
  columns.
- An `extra` role moves temperature, humidity and dew point to its numbered
  extra channel and keeps non-colliding housekeeping fields.
- `placement.toml` can keep, rename or drop individual fields for one
  Place/Sender/dialect relationship. Explicit mappings override the role
  preset.

This applies from the first Place. `stations.toml` supplies display metadata
and sender-specific clock tolerances, never an archive destination.
The Senders page diagnoses arrivals; it does not change this routing policy.

## Retired global source routing

The production Archiver no longer reads `[sources]`, `--sources` or
`WEEWX_EVO_SOURCES`. These forms are accepted only so startup can report that
they are obsolete and ignored. Sender display names never participate in
archive routing.

The former policy was a second answer to the same question: after a Place had
selected and mapped its senders, a global rule could silently discard one
sender's value for a field. It also applied identically to every Place. That
conflicts with Place-owned policy and with canonical sender IDs.

## Low-level library

`sources.py` remains available to code that explicitly constructs
`Archiver(..., sources=policy)`. It is not wired to configuration or service
startup.

```python
from weewx_evo.sources import Policy

policy = Policy.from_config({
    "outTemp": "source-a, source-b",
})
archiver = Archiver(live, archive, sources=policy)
```

`sources.apply()` returns packets with losing fields removed plus a provenance
map. `tools/multisource.py` tests this isolated API. Product tests must build
Archivers through `cli.build_archivers()` and expect no source policy.

<!-- covers
src/weewx_evo/sources.py
tools/multisource.py
-->

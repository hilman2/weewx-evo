# Stations and Archives

Stations and archives answer different questions:

- A **sender** is a source of packets. Its stable identity is the pair of
  driver and hardware identity: for example `ecowitt` plus a PASSKEY.
- An **archive** is the measurement series for one place. It owns the database
  file, coordinates, altitude, display name and the set of senders it reads.

The separation applies with the first archive. There is no single-archive mode
in which place settings belong to the process or to a station.

## The path of a reading

```text
driver/collector ─► listener ─► live.sdb ─► Place Archiver ─► archive database
                     canonical sender ID       selection
```

The listener writes every accepted packet to the shared live database under
the names and units the console sent. A live packet has a driver, an identity
and a dialect; it has no archive assignment.

When an interval closes, each archive reads the packets selected by its own
sender membership, applies its primary choice and Place-scoped mappings, and
writes its own record. The same packet can therefore be used by more than one
archive without being copied or relabelled on arrival.

This is also why changing a selection or placement is repairable: rebuild the
span while its packets are still in the live database.

## `stations.toml`: identities, not routes

`stations.toml` gives a recognised hardware identity a readable name and keeps
sender clock tolerances. It does not contain archive membership, an indoor
policy or a field map.

Renaming a station does not split the raw history: stored packets keep the
driver and hardware identity, and the name is resolved when they are read.

## `archives.toml`: every place, including the first

```toml
[archives.default]
file = "data/weewx.sdb"
label = "Kirchdorf an der Amper"
latitude = 48.4596
longitude = 11.6539
altitude = 440.0
primary = "v1/ecowitt/aabbcc"
[archives.default.members."v1/ecowitt/ddeeff"]
indoor = false

[archives.nordfeld]
file = "data/nordfeld.sdb"
label = "Nordfeld"
latitude = 48.4012
longitude = 11.6301
altitude = 452.0
primary = "v1/ecowitt/aabbcc"
```

Each table is one place and is the sole source for that place's settings. A
sender may appear in several tables. An empty `senders = []` deliberately
selects none. `senders = "*"` explicitly selects all arrivals, which is what a
Place written from the settings starts with.

`primary` is the one sender this place's series is taken from. It is placed by
the catalog: `outTemp` is `outTemp`. Every other selected sender writes only
the columns given to it under Fields, plus its own battery and signal levels
→ [Placements](Placements).

A place holds one primary, so two of them cannot be configured. Omit it and
the earliest sender the live database has heard becomes the primary, which is
what a single-console installation gets without setting anything.

`members` carries what is left of the per-sender relationship: `indoor`
decides whether room readings belong in this series. The same sender can
therefore be the primary of one place and an additional sender in another.
Both controls live on the Places page, including for the first and only
archive.

The database schema still comes from the file. An existing WeeWX database is
opened as it is, including custom columns, and remains usable by WeeWX.

## Migration from the old layout

If `archives.toml` does not yet exist, the old `archive_db` and `station.*`
values are copied once into `[archives.default]` and the file is written
atomically. After that, `archives.toml` is the only authority for place and
database settings. Changing the old values has no effect.

An old archive field in `stations.toml` is ignored and is not written back.
An old `indoor` value is copied once into the archive member policy. After the
canonical file is committed it is removed from a writable `stations.toml`; on a
read-only split mount it may remain as ignored legacy input. Sender records and
the Senders page expose none of it.

`role` and `channel` are not read anywhere, in either file. A member table
still carrying them is refused rather than ignored: read and skipped, the place
would keep working with a line in it that means nothing.
There is no fallback from an unknown archive name to `default`: selecting the
wrong place must fail instead of publishing or recording plausible data under
the wrong name.

## Several places

One listener and one live database are sufficient for any number of places.
Each archive has its own file and selection, while feeds may publish one or
several of them. Two senders can feed one archive, and one sender can feed two
archives.

Coordinates and altitude stay with the archive because sunrise, solar
radiation and pressure reduction are properties of the place, not of the box
that uploaded a packet. A forecast likewise names the archive whose
coordinates it uses.

A per-place timezone is not implemented. Daily summaries use the process
timezone, so archives in different timezones need separate archiver processes
with the appropriate `TZ`.

<!-- covers
src/weewx_evo/archives.py
src/weewx_evo/stations.py
src/weewx_evo/roles.py
src/weewx_evo/adopt.py
src/weewx_evo/collectors.py
-->

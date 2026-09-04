# Several places

A place is one measurement series with its own database file, coordinates,
altitude and name. Every installation has at least one place, and the first is
configured in exactly the same way as every later one: in `archives.toml`.

| | |
|---|---|
| **Sender** | A driver/collector identity that writes raw readings |
| **Place** | The series that selects and records readings |
| **Feed** | What builds files from a place |
| **Export** | What moves those files elsewhere |

## The first place

The settings page uses the same **Places** master/detail editor for one entry
and for many. The first entry is stored in `archives.toml`:

```toml
[archives.default]
file = "data/weewx.sdb"
label = "Kirchdorf an der Amper"
latitude = 48.4596
longitude = 11.6539
altitude = 440.0

primary = "v1/ecowitt/aabbcc"

[archives.default.members."v1/ecowitt/aabbcc"]
indoor = true
```

Position controls sunrise, sunset and solar calculations. Height is used for
pressure reduction. The file is the WeeWX-compatible archive database.

The member-table keys are canonical sender IDs from the live database. They
are both the explicit selection and the place-specific policy. The selection
belongs here even when there is only one archive.

## Adding another place

**Where you measure → Add a place.**

![The form for adding a place](images/wiki-2-add-place.png)

The label, file, coordinates, altitude, colour and sender selection are stored
on the new archive entry. A relative database path is resolved from the
configuration directory.

Two senders in one garden do not require two places. Select both on the same
Place, mark one as the primary readings and give the other's fields columns
under Fields. A second Place is for a second measurement series: another
location, or another interpretation of the same raw packets.

## Choosing senders

Senders write raw packets into `live.sdb`; they do not choose an archive.
Choose the senders on each Place instead:

- A canonical sender ID may be selected by any number of Places.
- `senders = []` selects none.
- `senders = "*"` accepts all arrivals, including one nobody has announced.
  A Place written from the settings starts this way.

The same sender can therefore feed two archives, for example a normal series
and one rebuilt with different placements. `stations.toml` contains identities
and console settings, never a place assignment.

An unannounced sender is still stored under its driver and hardware identity.
Adopting it adds a display name. Place selection continues to use its canonical
ID, so renaming cannot reroute history.

## The list

**Places** shows every entry and keeps General, Senders, Fields and Outputs in
one detail view.

![The places page with three places](images/wiki-3-places.png)

A duplicate chart colour is reported because it makes two series
indistinguishable. A configured reader naming an archive that does not exist is
an error; it never falls back to another place.

### Removing a place

Removing a place deletes its entry from `archives.toml`. Its database file and
the raw packets in `live.sdb` remain. Readers that still name the place must be
changed first.

Removing it does not reroute a sender. Senders have no archive assignment.

## Publishing several places to one site

One feed can publish several places. On its page, **Place** selects the series
its own pages use and **Also show these places** selects the complete site.

![The place list on a feed's page](images/wiki-5-feed-places.png)

With several places the root contains the overview and comparison pages; each
place's own pages sit in its directory. A feed narrowed to one place keeps the
flat one-place layout.

The overview has one row per place and no total row. Two temperatures do not
form one combined temperature. Comparison pages show the difference and name
both ends.

### Charts and forecasts

A chart line may name the archive it reads, so one chart can draw several
places on one axis. → [Plots](Plots)

A forecast names one archive and uses that place's coordinates. A place without
a configured forecast gets none, never another place's. → [Forecast](Forecast)

## Migration

If `archives.toml` is absent, the former central `archive_db` and `station.*`
values are copied once into `[archives.default]`. The file is then the only
place to change them. Adding a second archive performs no configuration move.

## Timezones

Daily summaries use the archiver process's local midnight. A per-place timezone
is not implemented; archives in different zones need archiver processes with
the appropriate `TZ`. → [Stations and Archives](Stations-and-Archives)

<!-- covers
src/weewx_evo/adminarchives.py
src/weewx_evo/adminstations.py
-->

<!-- watches
src/weewx_evo/archives.py
-->

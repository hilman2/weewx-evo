# Stations and Archives

**Built, as of the commit that added `archives.py`.** This began as a
design and is kept because the reasoning outlives the diff. Where it says
what something will do, it now does.

Two ideas, and the point is that they are separate:

* A **station** is a thing that uploads. It has an identity, it belongs to one
  driver, and it either gets configured to reach us or it turns up on its own.
* An **archive** is a measurement series for one *place*. It has a file, an
  altitude, a latitude and a longitude, and one or more stations write into it.

WeeWX has neither. It has `station_type`, singular, and one database. Every
multi-station arrangement there is a driver wrapping other drivers.

## Why stations have to be a thing

Today a console is adopted: the first one heard becomes the station, and the
Ecowitt driver keeps it in the database. It works, and the reasoning is in the
code — two consoles number their channels from one, so both would write into
`temp1f` and neither could be separated out afterwards.

It has three problems.

**It is per driver.** Ecowitt solved it. The Weather Underground driver did
not, and the next driver would solve it a third time.

**The Weather Underground identity is not safe to adopt.** An Ecowitt PASSKEY
comes from the hardware and cannot collide. A WU station ID is typed by a
person, so two stations can carry the same one, and then nothing downstream
can tell them apart.

**What arrives unannounced disappears.** A wrong PASSKEY is refused, a wrong
ID becomes a second source, an unrecognised upload falls to the default
driver. In all three cases the operator sees nothing.

The last one is worth a measurement. Two sources reporting the same field with
no policy configured, built into one archive record:

    garden reports 19.0, roof reports 21.0, same minute
    without sources.toml:      outTemp = 20.0
    with  outTemp = "garden":  outTemp = 19.0

Nobody measured 20.0. `sources.apply()` returns early on an empty policy, both
packets reach the accumulator, and it averages them — three lines below a
docstring that says why that is wrong. The default does the thing the function
forbids.

## Turning it around: announce, do not adopt

Instead of *recognise whatever arrives and resolve the conflicts afterwards*:
**take what has been announced.** Everything else becomes exception handling
rather than the normal path.

The axis is not who assigns the identity. It is **whether the operator can
enter anything on the device at all**:

| Device | can enter? | identity | route |
|---|---|---|---|
| WU console with custom server | yes | **we assign** the ID | **create** |
| Ecowitt | server and port yes, PASSKEY no | hardware | **create, then learn** |
| WeatherFlow Tempest | no, it broadcasts | serial in the packet | **adopt** |
| AcuRite Access, Ambient WS-2902 | no, only DNS redirection | `id=`, the MAC | **adopt** |

**Creating** means we state the values and the operator copies them onto the
device. **Adopting** means the device arrives on its own and we ask whether it
belongs here.

Both end in the same place: a station in a list, with a name and an identity.

### We assign the identity where we can

This is what makes the WU collision impossible rather than detectable. The
page shows `evo-3f9a2c` and the operator copies it. They do not choose it, so
they cannot choose it twice. Short and typable, because some firmware limits
the field; it is not a secret, the token is.

### Where the hardware brings its own, the wizard is the moment we learn it

"Switch the console to upload now." That is Ecowitt's adoption, but at the
moment the operator expects it, rather than at some point in service to
whichever console speaks first.

## One page, three lists

```
Stations
  Kirchdorf     WU        evo-3f9a2c       last seen 12 s ago
  Garden        Ecowitt   PASSKEY 4F2A...  last seen 8 s ago

Seen, not announced
  ID "Nachbarhaus"   WU        192.168.33.51   3 min   [adopt] [ignore]
  ST-00043210        Tempest   UDP broadcast   1 min   [adopt] [ignore]

> Ignored (2)
```

The second list is the real gain, and it catches more than broadcasters: the
DNS-redirected device, the console whose ID has a typo in it, the second
Ecowitt that would be adopted silently today. In every one of those the
information the operator needs is the same — something is here and does not
belong yet.

**Ignored** is a collapsed list, not a decision. Anything in it can still be
adopted. An entry that has not been seen for some days is dropped, so a
neighbour's console that appeared once does not sit there for ever.

`admin.py:135` already has `ADD_PAGES = ("new-export", "new-feed",
"new-upload", "new-forecast")`. A `new-station` is the same shape.

### Discovery belongs to the driver

Where a Tempest announces itself (UDP 50222, its own JSON) is protocol
knowledge. The core must not hold it, or there is weather protocol in
`listener.py` again. Same construction as `claims()`:

```python
def discover(self, seconds: float) -> list[Found]:
    """Devices announcing themselves. Empty for protocols that do not."""
```

The core asks when the page opens; drivers that have nothing to announce
return nothing.

### The case that stays

Hardware identifying itself with nothing at all. `interceptor` records the
same limit: *"cannot be told apart, which is a limit of the protocol"*. Only
the sender address is left, and it moves with DHCP. Adoptable, with a note
that it hangs on an address and wants a fixed one.

## What may reach the archive

**Already built, and already right.** `db/archive.py:8`:

> Observations the database has no column for are dropped, not added. Adding a
> column changes the schema under WeeWX's feet.

It is reported rather than silent: *"%r has no column in %s and is being
dropped at every archive interval."* This holds with a single console too. An
extra sensor lands in the live table, is visible in the kept raw upload, and
reaches the archive only when somebody runs `weewx-evo columns --add`.

It follows from the one rule: the schema comes from the file, and WeeWX has to
be able to read it afterwards.

**What is missing is where it is said.** Today you have to know the command.
It belongs on the station:

    Kirchdorf — 45 fields, 38 in the archive, 7 dropped   [add columns]

## Several archives

The reason: one weewx-evo on a VPS collecting from several fields, sites, or
whatever else. Each is its own series, and mixing them into one file would be
wrong — different altitude, different sensors, different sunrise.

**The architecture already carries it.** The listener and the archiver speak
only through the live table. So: one listener, one port, one live table, and
**N archivers**, each with its own file and its own set of stations. That is
`deploy/split.yml` one step further, with no new concept.

    stations (ingest)  --n:1-->  archives (series)

Several stations may write into one archive; that is the multi-source case
`sources.py` already resolves, per field and per interval. A station belongs
to one archive.

What is about a place follows the place. A [forecast](Forecast#a-forecast-is-for-a-place)
is an answer about a coordinate pair, so an entry names the series it is for and
a place with no entry has none — never its neighbour's.

### How WeeWX does it, and what that costs

Several instances. It is the documented answer, in the
[weewx-multi wiki page](https://github.com/weewx/weewx/wiki/weewx-multi), and
the example there is this exact case: a Davis at the house, an AcuRite in the
paddock. Per station it duplicates the configuration file, the database, the
report directory and the systemd unit, through the template unit
`weewx@.service`.

The drawback the page names is logging: *"By default, log entries for each
instance will be written to the same log file. This can make reading the log
file and troubleshooting difficult."*

The threads agree and go further. In [Trying to decide between multiple weewx
instances or expanding the weewx
database](https://groups.google.com/g/weewx-user/c/dUZ0OlEgQpg) the advice is
several instances, but really to take collection out of WeeWX altogether:
mqtt, telegraf, influxdb, Grafana on top. Several sites is treated as a case
WeeWX is not the tool for.

**The useful finding is an absence.** Altitude, latitude and sunrise do not
come up in any of those threads. Not because they do not matter, but because
the problem does not exist there: every instance has its own `weewx.conf` with
its own altitude. **WeeWX solves the `station.*` problem by duplicating
everything.**

|  | WeeWX | here |
|---|---|---|
| isolation boundary | the **process** | the **archive** |
| per site | config, database, reports, unit, process | a row |
| ports and tokens | one per instance | one |
| `station.*` | duplicated, therefore solved | **has to move to the archive** |
| logs | mixed, named as a drawback | one |

The trade is explicit: we pay for moving `station.*` once, and get one
listener, one token, one page and one live table. WeeWX avoids that work and
pays again at every further site.

### The work is not the second file

`archive_db` appears 16 times in 6 files. That part is small.

The measurement that matters is the other one: **altitude, latitude and
longitude appear about 50 times across 11 files.** "The station" is a global
today — one altitude, one coordinate pair. Sun position, moon phase, the
pressure reduction, evapotranspiration and every skin hang off it. With two
sites that assumption breaks silently: sunrise for field B is computed with
field A's coordinates, and it looks entirely plausible.

**But most of those 50 are not global reads.** `derive.py:703` already has

```python
class Station:
    """What the formulas need to know about where the station is."""
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
```

and `sun_position()`, `max_solar_rad()` and `sun.py` take coordinates as
parameters. The arithmetic is parameterised already. What changes is where the
values come from — the archive rather than one global setting — which is
roughly the 27 occurrences in `options.py`, `admin.py`, `cli.py` and
`weewxconf.py`, plus wherever `Station(...)` is constructed.

So the move is: **`station.altitude`, `station.latitude` and
`station.longitude` belong to the archive, not to the process.**

## Ecowitt, and why its adoption cannot stay

The Ecowitt driver keeps its own list of consoles and refuses everything else.
That is the right instinct and it is in the wrong place, which shows as soon
as there is more than one archive.

Two consoles at two sites, both uploading:

    stored packets:   1
    sources:          ['AAAA1111']
    on the sightings: ['AAAA1111']

`BBBB2222` is nowhere. `_mapper_for` returns `None` for a PASSKEY it does not
know, `packets()` returns an empty list, and the core never sees a packet at
all -- so the list that is supposed to catch everything unannounced catches
exactly the case it was built for last. The only trace is a log line.

The fix is to split what the driver is deciding:

| | belongs to |
|---|---|
| whether these readings are taken at all | **the core**, `stations.toml` |
| what its identity is (the PASSKEY) | the driver, which reads it off the wire |
| which field on this console is `soilMoist1` | **the driver**, and only it |

Ecowitt's `[stations]` is `{PASSKEY: (name, Mapper)}` today, and only the
`Mapper` is really its business. The name duplicates `stations.toml` and there
is nowhere in it to put an archive.

So the driver stops refusing. It produces packets for every console it can
read, with the PASSKEY as the source, and the core decides. An unannounced
console then appears on the page like any other stranger, which is what makes
two sites possible at all: two consoles, two stations, two archives.

The field map stays with the driver, keyed on the station name rather than on
the PASSKEY -- the name comes from the core, and the driver hangs its own
knowledge off it.

## Order of work

1. ~~**Stations as a concept in the core.**~~ `stations.py`.
2. ~~**`new-station` with a wizard.**~~ `adminstations.py`.
3. ~~**What reaches the archive, shown on the station.**~~ With a redacted
   snippet of the last raw upload beside it.
4. ~~**"Archive" as a field on the station.**~~ It was insurance and it paid:
   step 6 added a file and changed no rows.
5. ~~**The drivers follow.**~~ Ecowitt hands its PASSKEYs to the core, and
   what belongs to the console rather than to the protocol -- `indoor`,
   `model`, the field map -- moved onto the station.
6. ~~**`station.*` moves to the archive.**~~ `archives.py`, and a second
   archive is a row.

### What step 6 turned out to be

The 50 reads of `station.latitude` looked like the expensive part and were
not. `archives.Placed` wraps the settings, so a feed asks for
`station.altitude` by the name it has always used and gets the altitude of
the series it is producing. Nothing that formats or draws had to be told that
archives exist.

The expensive part was one line nobody had listed. `pending` was keyed on the
interval alone, so whichever archiver reached an interval first deleted the
row and the second never saw it: two sites, and the slower one silently stops
archiving. It is keyed on `(stop, archive)` now, and
`tools/archives_test.py` checks that before it checks anything else.

### And what step 6 left undone

An archive had every number a page needs and nothing a page needs to *show*
it beside another one. Three fields closed that: a colour, a short code and
a presentation order, all in `archives.toml` and all optional.

They are here rather than in a skin for the same reason plot definitions are:
[Deck](Deck), the image generator and [Grafana](Grafana) would otherwise
hold three copies of "what colour is the north field", and the day they
disagree the same place is one colour on a page and another in the picture
beside it.

Nothing has to be chosen. `Register.presented()` fills in a colour by
position in the file and a code from the label, deduplicated — and by
position in the *file*, not in the display order, because dragging a place up
a settings page must not repaint it. The values are never written back:
"nobody chose one" has to stay sayable, or the next release's palette reaches
no station that ever opened the page.

**A place's name is a directory at the root of a published site**, so
`why_not` refuses one that would collide with a page or an asset directory —
and refuses a name that is only digits, because `live.php` decodes the live
document into PHP, which has one array type, and `{"archives": {"0": …}}`
comes back out as a list with every lookup on the page finding nothing.

## Open

* Should a station be creatable with an identity typed by hand, for hardware
  that has not been heard from yet?
* How many days before an ignored entry is dropped. Fourteen today.
* Does an archive get its own timezone? **Not built, and the reason is
  that it is not a configuration change.** `archive_day_*` is keyed on
  local midnight, so a zone per archive means every aggregate has to be
  told which one -- `series.py`, `aggregate.py` and the day cache all read
  the process timezone today. Sites in different zones stay a real case.
* Whether an archive gets its own `sources.toml` policy. It is global now,
  which is harmless while two archives share no stations, and wrong the
  moment one does.

<!-- covers
src/weewx_evo/archives.py
src/weewx_evo/stations.py
src/weewx_evo/roles.py
src/weewx_evo/adopt.py
src/weewx_evo/collectors.py
-->

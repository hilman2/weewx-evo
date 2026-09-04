# Uploads

`uploads/`. How the readings themselves get to a weather service.

An [export](Exports) moves **files** — a feed wrote a directory, and something
has to get it onto a web host. An upload moves **readings**: an archive record,
reshaped into what Weather Underground or Windy or an APRS gateway wants, and
sent. No directory is involved, which is why it is not an export with an odd
source.

In WeeWX that sits in the core as `StdRESTful`, and it belongs there here too:
uploading to Weather Underground is not an extension for a weather station, it
is half the reason to run one. An extension is the tenth service; the shape here
is built so that the tenth is forty lines.

There are nine: `wunderground`, `pwsweather`, `wow`, `windy`, `weathercloud`,
`cwop`, `mqtt`, `webpush` and `influx`.

The last is not a weather service. It writes into a database the operator runs,
so that Grafana can be asked the question a rendered page cannot answer — see
[Grafana](Grafana).

## The interface

```python
class Upload(Protocol):
    def post(self, records: list[dict]) -> Posted:
        ...
```

`records` is **oldest first**. Usually it is one — the interval that has just
closed. It is a list because a connection that was away for ten minutes has two
options on coming back: send the newest value and pretend the others never
existed, or send them all.

Weather Underground, PWSweather and WOW take a timestamp with the reading and
accept the missed records. Making that the caller's business rather than every
service's means the service that cannot backfill says so once with
`backfill = False` and gets only the last one.

## Where the records come from

**Not handed over — read directly.** An upload is given nothing; it reads the
archive from wherever it last got to. That is the same rule as in the rest of
the system: the components talk through the database and not to each other. It
brings two things that are otherwise hard to get:

- **A restart costs nothing.** The upload knows where it was because the number
  is on disk — not because a process remembered something.
- **A connection that was away for twenty minutes** comes back and sends the
  twenty minutes, rather than the current value and a hole.

Progress is recorded in `uploads.json` next to the archive. It is a cache:
losing the file costs one duplicate post, and every service here overwrites a
timestamp it already has.

```python
progress.through("wu")   # the newest record WU accepted
```

## When an upload runs

| | |
|---|---|
| `record` | after every archive record — the default and almost always right |
| `live` | every few seconds, from the live table. Only MQTT offers it |
| `interval` | its own rhythm, for a service that wants less often (CWOP) |
| `manual` | only on `weewx-evo upload run` |

**Every upload runs in a thread of its own**, for the same reason as the
exports: a service that has stopped answering sits in its own timeout rather
than in the archiver's tick. Weather Underground is away for an hour now and
then, and an archive interval that arrives late because of it is our fault.

## A wrong password is said once

These services answer a wrong password with a cheerful HTTP 200 and the word
`INVALIDPASSWORDID` in the body. So the status code decides nothing, and the
body has to be read.

A `Rejected(permanent=True)` turns the upload off and writes **one** line to the
log. The alternative is the same line every five minutes for a year — and that
is how a log stops being read.

Which is why every upload has a `check()`, and the admin page a button for it:

```bash
weewx-evo upload check
weewx-evo upload check wu
```

## Units

**`units.py`, in one place.** Every one of these services dictates its units and
none agrees with the next: Weather Underground wants Fahrenheit and inches of
mercury, Windy Celsius and metres per second, APRS Fahrenheit and hundredths of
an inch. The archive holds what the station wrote.

The conversion happens in `Readings`, once, against the same table as everything
else. That was WeeWX's mistake with the two plot generators: both right in
themselves, disagreeing in the third decimal place, and nobody finds it.

## A missing value is missing, never zero

A station with no rain gauge sending `rainin=0.00` every five minutes is
indistinguishable from one in a drought — and Weather Underground keeps it
forever. `query()` leaves out whatever is `None`, which is why every reading
comes back as `None` rather than as a default.

CWOP cannot do that: the packet is positional, and a missing value is dots of
the same width. Both are followed rather than one of them being chosen.

## The services

### Ambient: Weather Underground, PWSweather, WOW

Weather Underground defined the protocol and the others copied it — apart from
the parameter names. Hence one module with three hosts rather than three nearly
identical files.

The formats are taken from `weewx.restx.AmbientThread`, field by field,
**widths included**: `humidity=061` and `windspeedmph=003.1` are what the
protocol defines, and the leading zeroes are not decoration. The test found that
(`tools/upload_test.py`), not the reading.

WOW renames both credentials (`siteid`, `siteAuthenticationKey`) and answers a
wrong password with HTTP 403 rather than a word in the body. Otherwise
identical.

### Windy

The only one here that does not speak Ambient: JSON in the body of a POST,
metric, and the key is in the path rather than in a parameter.

**The pressure is in pascals.** Not hectopascals, which every other service and
every barometer uses. `101325`, not `1013.25`. Sending the hectopascal value is
accepted and drawn as a vacuum.

Windy takes several observations in one request, so a backfill is one request
rather than twelve.

### Weathercloud

Metric, and every value is a whole number in tenths: 21.4 °C goes as `214`. No
timestamp in the protocol, so no backfilling — an older record would be
published as the current conditions.

### CWOP

No HTTP. A TCP socket, a login line and one line of ASCII in the TNC2 packet
format amateur radio has used since the nineties:

```
DW1234>APZEVO,TCPIP*:/271530z4823.15N/01142.30E_245/007g016t074r006p013P010b10128h61L512.weewx-evo
```

Every field has a fixed width, every missing field is dots of the same width,
and the whole thing is positional. A wrong width produces no error but a reading
in the wrong place — silently, forever.

The packet builder is therefore taken from `weewx.restx.CWOPThread` character by
character, including `h00` for 100 % humidity and the two different letters for
solar radiation above and below 1000 W/m². Those are not quirks to be tidied up,
that is the protocol.

The test compares the packet with the one WeeWX builds from the same record —
character by character.

Two decisions:

- **Ten minutes, not five.** CWOP asks for a report every five to ten minutes
  and means it. The default is ten, on its own rhythm rather than on the archive
  record.
- **`APZEVO` as the tocall.** `APWEE5` is assigned to WeeWX and is not ours.
  `APZ...` is the range the APRS specification sets aside for software without a
  registered identifier.

CWOP needs latitude and longitude — the packet **is** a position report. They
are filled in from the selected place, so that nobody types them twice.

### MQTT

Its own page: [MQTT](MQTT).

### InfluxDB

Its own page, because what reads it is: [Grafana](Grafana). `post(records)`
with an oldest-first list and a tracker is the shape a time series sink wants,
so fifteen years is `upload run --since 2010`.

### Live readings on a published page

`webpush`. A page sent by FTP shows figures as old as the last run. This posts
the current readings to a small PHP file the export carries up with it, which
writes `live.json` beside the pages; the page polls that.

The connection goes **out**, the same way the upload that put the pages there
did. Nothing is opened and nothing expires — which is the whole difference from
the usual answer, an MQTT broker at the station behind a port forward and a
certificate.

**There is nothing to set up.** The export already knows the address and the
directories, and the token is derived from the upload token, so
`live_readings_locally()` creates the upload itself. It is not in the list of
kinds to add by hand for that reason: as a menu entry it was a form of eight
empty fields, and the empty one that mattered was the units.

A `local` export needs none of the PHP: the built-in web server serves the
directory anyway, so `live.json` is written straight into it. **The page cannot
tell the difference** — it reads `live.json` either way.

## Configuration

```toml
[uploads.wu]
kind = "wunderground"
station = "IBAYERN123"
password = "..."

[uploads.windy]
kind = "windy"
api_key = "..."

[uploads.cwop]
kind = "cwop"
station = "DW1234"
# latitude and longitude come from this upload's place
```

Two accounts with the same service are two uploads with different names.

## Commands

```bash
weewx-evo upload list             # what there is and what is configured
weewx-evo upload check            # asks the services, sends nothing
weewx-evo upload run              # send now
weewx-evo upload run wu --again   # forget how far it got
```

## Checking it

```bash
python tools/upload_test.py
```

No network. Every check builds a request and looks at it. With WeeWX on the
path it additionally compares the Ambient query and the CWOP packet, parameter
by parameter, with what WeeWX builds from the same record:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && PYTHONPATH=/mnt/d/Git/weewx/src:src \
  python3 tools/upload_test.py'
```

→ [Exports](Exports) · [MQTT](MQTT) · [Feeds](Feeds)

<!-- covers
src/weewx_evo/uploads/__init__.py
src/weewx_evo/uploads/runner.py
src/weewx_evo/uploads/records.py
src/weewx_evo/uploads/progress.py
src/weewx_evo/uploads/ambient.py
src/weewx_evo/uploads/cwop.py
src/weewx_evo/uploads/windy.py
src/weewx_evo/uploads/weathercloud.py
src/weewx_evo/uploads/homeassistant.py
src/weewx_evo/uploads/webpush.py
src/weewx_evo/exports/livepush/__init__.py
-->

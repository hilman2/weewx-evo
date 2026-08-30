# Settings A–Z

Every core setting, as `options.core_options()` declares them. The environment
variable is always `WEEWX_EVO_` + the name in upper case, dots to underscores.
→ [Configuration](Configuration)

Generated versions of the same list:

```bash
weewx-evo config show --defaults    # commented TOML
weewx-evo serve --explain           # values with their origin
```

Key: **A** = advanced (behind a toggle on the admin page),
**R** = needs a restart, **!** = required.

## Station

*Where the readings come from, and where that is.*

**These four move.** With a second place they are read from `archives.toml`
instead, per place, and nothing here is read at all. The settings page marks
them. → [Several places](Places#the-settings-move)

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `station.name` | text | `weewx-evo` | | On the live page and in reports |
| `station.latitude` | float | — | | Decimal degrees, negative south of the equator. For sunrise and sunset and for the clear-sky radiation a solar sensor is measured against |
| `station.longitude` | float | — | | Decimal degrees, negative west of Greenwich |
| `station.altitude` | float | — | | Metres above sea level. This is what turns station pressure into the barometer value everybody compares. Take it from a map, not from the console: consoles are usually set to whatever made the display look right |

## Archive

*How readings become the record that stays.*

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `interval` | duration | `300` (60–3600) | R | How much time an archive record covers. Five minutes is usual. Changing it does not disturb the existing record — every record carries the span it stands for, so old and new average together correctly |
| `grace` | duration | `15` (0–300) | A | How long to wait after the end of an interval, so that a merely slow packet does not have the record computed twice |
| `loop_hilo` | bool | `true` | A | Individual packets may set the day's extremes, not only archive records. On by default, like WeeWX. Turned off, the daily highs and lows are exactly reproducible from the archive alone |

## Databases

*Two files: the record, and the packets behind it.*

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `plots_file` | path | `plots.toml` | R | Which plots there are. Its own file rather than a section: it is a list of many alike sets, and a set imported from an old skin is something you want to be able to diff |
| `archive_db` | path | `data/weewx.sdb` | R | The WeeWX database. Existing ones are used as they are — the schema comes from the file |
| `live_db` | path | `data/live.sdb` | R | Where packets sit until they are in records. Its own file, so that size and retention have nothing to do with the archive |
| `retention` | duration | `604800` (min 3600) | | How long raw packets stay. They are what makes a record reproducible: as long as they are there, a wrong calibration or a late packet can be corrected. Seven days is around 80 MB at one packet every eight seconds |
| `raw_retention` | duration | `3600` (0–86400) | A | How long the upload as it came off the wire sits next to the parsed packet. A debugging aid — the thing you attach to an issue about a sensor that cannot be placed. `0` keeps none |
| `spool` | path | — | A | A directory. Every day of packets leaving the live table is put there as gzip NDJSON first. Empty means: just drop them |

## Listener

*The port the hardware uploads to.*

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `host` | text | `0.0.0.0` | A R | Every interface. Narrow it when the machine is on more than one network |
| `port` | int | `8000` | R | Below 1024 needs root, which this service should not have |
| `token` | secret | — | ! | A path segment every upload has to carry. The only thing between the open internet and your record: hardware cannot send a header, so an unguessable path is the practical answer. Anyone who learns it can forge readings |
| `driver` | choice | `ecowitt` | | Which driver reads an upload whose path names none. The choices are what is installed |
| `udp_port` | int | `0` | A R | For hardware that broadcasts instead of posting. `0` turns it off. A datagram carries no path, so the port itself is the access control |

## Who is answered

*Bound to every interface; this is where it is decided who gets an answer.*

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `allow` | text | `private` | R | `private` = the local network (shed, console, laptop in the kitchen) and covers a reverse proxy, which always connects from a private address. `any` includes the open internet. Or list networks: `10.0.0.0/8, 192.168.1.50`. Loopback is always answered |
| `rate` | float | `10.0` | A | Requests per second per address. A console sends half of one at the fastest, so this only catches something that has gone wrong. What prevents token guessing is the separate limit on wrong ones. `0` turns it off |
| `behind_proxy` | bool | `false` | A | Then every request comes from the proxy's address, and a per-address limit would slow everyone down except whoever caused it. Limiting stays with the proxy, which is the only one able to do it |

→ [Security](Security)

## Settings page

*Its own port, its own token: it can do far more than an upload.*

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `admin.token` | secret | — | | **Never the same as the upload token.** Otherwise anything that can send a reading could also change what the station records. Empty turns the page off |
| `admin.port` | int | `8080` | R | |
| `admin.host` | text | `0.0.0.0` | A R | |
| `admin.allow` | text | `private` | | As above, and it is worth staying tighter. This page points the archive at files. To reach it from elsewhere without opening it up: `ssh -L 8080:localhost:8080 the-station` |
| `admin.rate` | float | `5.0` | A | Saving is two requests, and clicking through the tabs makes several a second. A limit that gets in the way is one that gets turned off |

## Website

*Serving what the feeds produced, on this machine.*

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `web.enabled` | bool | `false` | R | A small web server for what the feeds write. Enough to look at your own pages on the local network without installing nginx |
| `web.port` | int | `8081` | R | Its own port, separate from upload and settings page. Those two answer hardware and an operator; this one answers browsers |
| `web.default` | choice | — | | What sits at `/`; the others stay under `/<name>/`. Without it, `/` lists what there is. The choices are the `local` exports and whatever `[web.serve]` names directly |
| `web.allow` | text | `private` | | As elsewhere. A weather page is not a secret, but this machine still answers strangers |
| `web.host` | text | `0.0.0.0` | A R | |

→ [Web-Server](Web-Server)

## Running

*Where things go and how often they happen.*

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `table` | text | `archive` | A R | The table in the database. Only of interest to an installation that renamed it |
| `poll` | duration | `5` (1–300) | A | How often the archiver looks for closed intervals. The work is idempotent and the boundaries come from the packets, so a late or missed tick changes nothing |
| `driver_dir` | path | — | A R | Where drivers installed with `weewx-evo driver install` live. Empty means: next to the archive |
| `weewx_conf` | path | — | A | A `weewx.conf` to fall back to. Read, never written. Anything set here beats it |

## Driver: ecowitt

Prefix `drivers.ecowitt`. Declared in
`ingest/plugins/ecowitt/driver.py::EcowittDriver.options()`.

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `passkey` | secret | — | | The value the console sends first in every upload. Set here, the question is settled for good. Left empty, the first console heard is adopted and noted in the database — which works, but is lost with the database and afterwards leaves the station to whichever console speaks first |
| `model` | text | `Ecowitt` | A | Appears in logs. Cosmetic |
| `infer_unknown` | choice | `series` | | `off` = drop them · `series` = take them if they continue a known series, report the rest · `all` = take everything that can be named. A reading in the wrong column cannot be separated out afterwards |
| `report_file` | path | `/var/tmp/weewx-evo-ecowitt-report.txt` | | Where the first upload containing something unplaceable is written. The file already has the PASSKEY removed and is meant for pasting into an issue. Empty turns it off |
| `max_behind` | duration | `3600` | A | How old a console's timestamp may be. Beyond that, the arrival time is used |
| `max_ahead` | duration | `60` | A | And how far into the future. There are no readings from the future, so this only covers drift between two roughly correct clocks |

→ [Driver-Ecowitt](Driver-Ecowitt)

## Feed: json

Prefix `feeds.json`. Declared in
`feeds/jsongenerator/__init__.py::JSONGenerator.options()`.

| Name | Kind | Default | | What it means |
|---|---|---|---|---|
| `feeds.json.enabled` | bool | `true` | | Off only when nothing reads it. Every other feed that draws a plot does |
| `feeds.json.destination` | text | `json` | | Below the feed's output directory. A subdirectory, so that the data does not sit among the pages |
| `feeds.json.manifest` | bool | `true` | | Write `index.json`: a list of what there is, so that a client can lay out its page before fetching anything — and never asks for a sensor the station does not have |
| `feeds.json.rewrite_unchanged` | bool | `false` | | A year of daily means says the same thing at ten past as it did at ten. With this off, a file with identical content is not touched — which counts when an export sends everything that changed, over a line somebody pays for by the megabyte |
| `feeds.json.rounding` | int | `3` (0–9) | | Three is already finer than any weather sensor and takes about a third off the file size |
| `feeds.json.indent` | int | `0` (0–8) | A | `0` writes as small as possible. `2` makes them readable while you work out why a plot looks wrong |
| `feeds.json.spans` | list | — | A | Comma-separated, matching a plot's group. Empty produces all of them. A yearly plot over a decade is the expensive one; leaving it out is how a small machine keeps up |
| `feeds.json.units` | choice | `METRICWX` | | What the files are written in, whatever the archive holds |
| `feeds.json.unit.group_temperature` | choice | — | | Overrides the system for this one group — that is how somebody ends up with Celsius and inches of mercury on one page, because that is what their readers expect |
| `feeds.json.unit.group_pressure` | choice | — | | `mbar` `hPa` `inHg` `mmHg` `kPa` |
| `feeds.json.unit.group_rain` | choice | — | | `mm` `cm` `inch` |
| `feeds.json.unit.group_speed` | choice | — | | `meter_per_second` `km_per_hour` `mile_per_hour` `knot` |
| `feeds.json.unit.group_altitude` | choice | — | A | `meter` `foot` |
| `feeds.json.unit.group_distance` | choice | — | A | `km` `mile` |
| `feeds.json.twilight` | bool | `true` | | Twilight is not an edge: the light goes over the half hour of civil twilight, and at high latitudes in summer over far longer. With this, a plot can draw the real thing rather than a step. Costs a few hundred bytes per file |

→ [Feeds](Feeds), [Units](Units)

## Exports

Prefix `exports.<name>`. Declared in `exports/local.py`, `exports/ftp.py` and
`exports/rsync.py`. Common to all three:

| Name | Kind | Default | What it means |
|---|---|---|---|
| `kind` | choice | — | `local`, `ftp` or `rsync` |
| `directory` | text/path | see below | Where to. With shared hosting usually `/httpdocs` or `/public_html`, rarely the login directory |
| `source` | choice | — | Which feed this export sends |
| `directory_source` | path | — | Or a directory, when no feed is chosen |
| `delete` | bool | `false` | Removes files that are no longer produced. Only what this export put there itself — it keeps a record |
| `trigger` | choice | `feed` | `feed` · `record` · `interval` · `manual` |
| `every` | duration | `900` (60–86400) | Only with `interval`. Below the archive interval it would run with nothing new |
| `tracker` | path | — | Where it is noted what has already been sent. Empty means: next to the source directory. This is what stops everything going up every time; losing it costs one full run |

`local` only:

| Name | Kind | Default | What it means |
|---|---|---|---|
| `directory` | path | `data/site` **!** | A directory on this machine. Put under what the built-in web server serves, the feed is on the local network immediately. A directory nginx already serves, or a mounted share, works just as well |
| `link` | bool | `true` | **A** — Hard link rather than a copy. On one filesystem a link costs a directory entry instead of a second copy of every file. Falls back to copying on its own where the filesystem will not link |

For `ftp` and `rsync` additionally:

| Name | Kind | Default | What it means |
|---|---|---|---|
| `host` | text | — | The server. Not a URL, just the name |
| `user` | text | — | |
| `timeout` | duration | `30` (ftp) / `600` (rsync) | A dead host must not hold the next interval up |

FTP only:

| Name | Kind | Default | What it means |
|---|---|---|---|
| `password` | secret | — | |
| `port` | int | `21` | |
| `tls` | bool | `true` | FTPS. Off only when the host has no TLS — and then the password goes over the network as readable text |
| `passive` | bool | `true` | Almost always right. Active requires the server to connect back, which no home router allows |

rsync only:

| Name | Kind | Default | What it means |
|---|---|---|---|
| `port` | int | `22` | SSH port |
| `compress` | bool | `true` | Worth it for text, and a weather site is mostly text |
| `key` | path | — | Empty uses whatever SSH would take on its own. **There is no password option**: a password would have to be typed by a program, which puts it into a process list or a file. Public key in `authorized_keys` |
| `extra` | text | — | Further rsync arguments, passed through as they are. Split on spaces, so nothing with a space in it |

→ [Exports](Exports)

<!-- covers
src/weewx_evo/options.py
src/weewx_evo/ingest/plugins/ecowitt/driver.py
src/weewx_evo/feeds/jsongenerator/__init__.py
src/weewx_evo/exports/ftp.py
src/weewx_evo/exports/rsync.py
src/weewx_evo/exports/local.py
-->

<!-- watches
src/weewx_evo/options.py
src/weewx_evo/archives.py
-->

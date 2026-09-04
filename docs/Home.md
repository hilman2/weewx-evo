# weewx-evo

A rebuild of the WeeWX core. Python, no dependencies outside the standard
library, 3.11 and up.

## The one rule

> An existing WeeWX database stays readable and writable — **by WeeWX
> itself**. Not "importable": the same file, the same meaning, and WeeWX 5
> can carry on using it afterwards.

Everything else in this project is negotiable. This is not. Anyone changing a
line in [`aggregate.py`](Aggregation), [`db/archive.py`](Database-Archive) or
[`db/daily.py`](Daily-Summaries) runs
`python tools/difftest.py reference/weewx.sdb` before and after — see
[Testing](Testing).

Three things follow from it in practice:

| | |
|---|---|
| **The schema comes from the file** | Never from a list in the code. An installation with columns of its own keeps them. → [Database-Archive](Database-Archive) |
| **The arithmetic is transcribed** | `aggregate.py` is a transcription of `weewx.accum`, step by step. A "cleaner" formula that rounds differently is a wrong formula here. → [Aggregation](Aggregation) |
| **`archive_day_*` is a cache** | Everything in it is derivable from `archive`, and `rebuild_day` is the derivation. → [Daily-Summaries](Daily-Summaries) |

## The seams

```
Sources (push or pull, each its own process)
  └─ Listener: HTTP + UDP, token, driver plugins
      └─ live: every packet, with its origin, N days
          └─ Archiver: deterministic per timespan
              └─ archive (WeeWX-compatible, PK dateTime)
                  └─ archive_day_* (cache)
                      └─ series → feeds → exports
```

The components talk **only through the database**, never to each other. That
is why they run as three systemd units or as one process, with no code change.
It is not decoration, it is the property that makes `deploy/split.yml`
possible. → [Architecture](Architecture)

## Two halves, and you probably want the first

**The user guide** is about running a weather station: connecting a console,
publishing a site, being told when something breaks. It starts at
[Getting Started](Getting-Started) and each page links to the technical one
behind it, for when you want to know why.

**Everything below the line in the sidebar** is how this is built — the
arithmetic, the databases, the transcriptions from WeeWX. **None of it is
needed to run a station**, including by somebody who likes knowing how things
work. It is there for changing the code.

| I want to… | |
|---|---|
| get a station recording | [Getting Started](Getting-Started) · [Connecting a console](Connecting-a-console) |
| put it on the web | [Publishing a website](Publishing-a-website) · [Charts](Charts) |
| keep a second spot | [Several places](Places) |
| send it to Weather Underground, Windy, Grafana | [Sending readings on](Sending-readings-on) |
| hear about it when it breaks | [Alerts](Alerts) · [Sensor checks](Sensor-checks) |
| look a setting up | [Settings A–Z](Settings-Reference) · [Command line](CLI-Reference) |
| understand how it is put together | [Architecture](Architecture) · [WeeWX compatibility](WeeWX-Compatibility) |
| change the code | [Contributing](Contributing) · [Testing](Testing) · [Index](Index) |
| find a function | [API index](API-Index) |

## Licence

**GPL-3.0-or-later.** The Ecowitt driver goes back, by way of
[weewx-ecowitt](https://github.com/hilman2/weewx-ecowitt), to Werner Krenn's
`ecowittcustom` driver, which in turn goes back to Matthew Wall's
`interceptor` — both GPLv3, and that is the reason.

The uPlot in `feeds/diagnostic/vendor/` is MIT and has its own licence file
sitting next to it.

## The pages

### Ingest

| Page | What it covers |
|---|---|
| [Ingest-Listener](Ingest-Listener) | HTTP + UDP, tokens, rate limit, status page |
| [Drivers](Drivers) | The driver interface, bundled and third-party drivers |
| [Push drivers](Driver-Ecowitt) | The six built-in push protocols |
| [Uploads](Uploads) | The readings sent to a weather service |
| [MQTT](MQTT) | The in-house client, and what makes it necessary |
| [Forecast](Forecast) | Forecast and warnings, four sources |
| [Plugins](Plugins) | What lives outside the core, and the catalogue for it |
| [Multiple senders](Multiple-Sources) | Several senders, one Place record |

### Processing and storage

| Page | What it covers |
|---|---|
| [Database-Live](Database-Live) | The live table: every packet, for N days |
| [Archiver](Archiver) | Archive records out of timespans |
| [Aggregation](Aggregation) | The arithmetic — a transcription of `weewx.accum` |
| [Database-Archive](Database-Archive) | The WeeWX database, reading and writing |
| [Daily-Summaries](Daily-Summaries) | `archive_day_*` as a derivable cache |
| [Derived-Readings](Derived-Readings) | Dewpoint, wind chill, rain delta |
| [Quality](Quality) | Calibration and limits, before a reading reaches the archive |

### Output

| Page | What it covers |
|---|---|
| [Series](Series) | Series out of the archive — what every feed stands on |
| [Units](Units) | Units, groups, conversion, target system |
| [Sun](Sun) | Solar position, rise and set, twilight |
| [Plots](Plots) | Plot definitions and `plots.toml` |
| [Feeds](Feeds) | What gets produced — JSON feed, diagnostic page |
| [Exports](Exports) | How it gets somewhere else — FTP, rsync |
| [Web-Server](Web-Server) | Serving the feeds locally |
| [API](API) | The readings as an answer to a question |
| [Metrics](Metrics) | What the process is doing, for Prometheus |
| [Grafana](Grafana) | Dashboards for more than one console, through InfluxDB |
| [Notifications](Notifications) | Who hears about it when something stops |
| [Maintenance](Maintenance) | Backup, integrity, and reclaiming space |

### Operation

| Page | What it covers |
|---|---|
| [Configuration](Configuration) | The precedence, the option schema, `--explain` |
| [Settings-Reference](Settings-Reference) | Every core setting, in full |
| [CLI-Reference](CLI-Reference) | Every command, every flag |
| [Admin-Page](Admin-Page) | The settings page |
| [Security](Security) | Tokens, network boundary, rate limit |
| [Deployment](Deployment) | Docker, Caddy, the split arrangement |
| [Testing](Testing) | The tools in `tools/` and what each one checks |
| [WeeWX-Compatibility](WeeWX-Compatibility) | What is shared, what is not, `weewx.conf` |
| [Contributing](Contributing) | Writing style, conventions, pitfalls |

<!-- covers
README.md
CLAUDE.md
src/weewx_evo/__init__.py
src/weewx_evo/db/__init__.py
src/weewx_evo/ingest/__init__.py
pyproject.toml
LICENSE
-->

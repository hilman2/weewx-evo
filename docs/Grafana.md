# Grafana

`grafana/` and `uploads/influx.py`. Dashboards for an installation with more
than one console, generated out of what is already configured.

A rendered **page** belongs to one place. A published **site** may carry
several: [Deck](Deck) draws an overview of every place, a page for each of
them, and comparison charts across all of them, and an FTP export puts the
whole thing on a web host.

That is a narrowing of what this page used to say, and it is worth being
plain about. "All five locations on one axis" turned out to be answerable by
a template after all -- the obstacle was never Cheetah, it was that a chart
line could not name its own archive. It can (`series` in
[plots.toml](Plots)), so it does.

What is left for Grafana is the part that is still true, and it is the part
worth having: **a question nobody wrote a chart for.** A published page can
only answer what somebody defined in advance; Grafana answers what somebody
thinks of at the time, over any span, with any filter left off. So the split
stands, with a sharper edge: **Grafana is where questions are asked, Deck is
what gets published.**

```
weewx-evo ──influx upload──> InfluxDB <──reads── Grafana
                                ▲
                         one bucket, one
                         `location` tag per archive
```

## The InfluxDB upload

An ordinary [upload](Uploads), the ninth. It posts archive records as line
protocol, and the interface was already the right shape: `post(records)` takes
a list oldest first and the runner keeps a tracker, so fifteen years is
`weewx-evo upload run <name> --since 2010` rather than new machinery.

```toml
[uploads.influx-kirchdorf]
kind = "influx"
url = "http://influxdb:8086"
token = "..."            # write permission on the bucket is enough
org = "weewx-evo"
bucket = "weewx"
location = "kirchdorf"   # the tag every point carries
unit_system = "metricwx"
```

**The tag is the archive, not the station.** By the time a record exists the
stations that fed it have been merged ([sources](Multiple-Sources)) or moved
out of each other's way ([roles](Stations-and-Archives)), so a record has no
station and tagging one on would invent a fact. One upload per archive, each
with its own `location`, all into the same bucket — which is what lets a
single query draw all of them.

That holds for the [forecast](Forecast#a-forecast-is-for-a-place) too: an
upload sends the forecast of the series it is for and no other. Sending the
whole store through one upload would not be a fuller picture — every point
carries that upload's `location`, so a second place's hours land on the first
place's tags at the same timestamps, and InfluxDB keeps whichever arrived
last.

**The units are set, not inherited.** InfluxDB stores numbers without meaning.
Readings convert on the way out into the system named here, and changing it
later puts a step in the middle of the series that nothing downstream can see.
Pick it once.

### Four things line protocol punishes

Each answers HTTP 400 with a line number and looks like a network problem.

| | |
|---|---|
| A field is one type for ever | `outTemp=20` in January refuses `outTemp=20.1` in February, for the life of the bucket. Everything goes out as a float. |
| NaN and infinity | Rejected, and they take the whole batch with them. `derive.py` produces both from a division by a zero wind speed. |
| A location with spaces | "Kirchdorf an der Amper" is ordinary, and a space separates the tags from the fields. |
| A record with no readings | A measurement with no fields is a syntax error. An interval where quality control dropped everything leaves one. |

`interval` is written as a field. Every mean in this project is weighted by
it, and a query cannot weight by a number it was never given.

## Provisioning

```bash
weewx-evo grafana list                     # what would be written
weewx-evo grafana provision --out /data/grafana --read-token <ro>
```

**Nothing here is a second set of settings.** The uploads already say where
the server is, which bucket, which units and what each archive is called, so a
datasource is a restatement of one. Uploads pointing at the same bucket become
**one** datasource and their locations become the dashboard variable.

Written in the shape Grafana's file provisioning expects:

```
datasources/weewx-evo.yaml    one per server, not per archive
dashboards/weewx-evo.yaml     the provider
dashboards/*.json             the dashboards below
```

**Generated, never drawn by hand.** A dashboard checked into a repository is
wrong the first time somebody adds a sensor. These come out of
[`plots.toml`](Plots), the archive's schema and [`units`](Units), so a station
with a soil probe and four extra thermometers gets panels for them without
this code knowing they exist. The Seasons starter set becomes 129 panels.

**Grafana reads; the upload writes.** They want different tokens. The upload's
own is used where nothing else is given, and said, every time — a read-only
token is thirty seconds of work and this file ends up in a container.

### The dashboards

| | |
|---|---|
| `now` | Is everything alright. One tile per location, laid out by Grafana's `repeat`. |
| `location` | One station in full, chosen with a variable. |
| `compare` | One reading, every location. The reason for all of this. |
| `charts-day` … `-year` | Every plot in `plots.toml`, one dashboard per span. |
| `operations` | Who has stopped talking, and what the batteries are doing. |

Three seconds, thirty seconds, five minutes: the top row is numbers big enough
to read across a room, under it the charts that explain them, below that the
detail somebody opens twice a year.

**The location list comes from the data.** A dashboard variable asks InfluxDB
which `location` tags exist, so a console added next month appears in the
picker without anybody regenerating anything.

**`operations` needs no metrics endpoint.** A station that has stopped is a
location whose newest point is old, and InfluxDB can answer that.

## Where Grafana must not disagree

`query_influx.py` is the file that decides whether Grafana shows the same
numbers the station's own pages show. The fault it guards against is the one
[`chartdata.py`](Plots) describes one storey down: two renderers, both right
on their own, differing in the third decimal — except here they sit side by
side on one screen.

**Flux rather than InfluxQL.** An InfluxDB 2 bucket needs a DBRP mapping
before InfluxQL can see it, and the missing step reports itself as "no
measurements found". A weighted mean is not expressible in InfluxQL at all.

**The weighting is measured, not assumed.** `intervals_in()` reads the
archive. One interval throughout means `mean()` **is** the weighted average,
so the plain query is also the correct one; more than one and the expensive
form is used and the provisioning run says so. An extreme needs neither: the
largest reading in a window is the largest whether it stood for five minutes
or ten.

**Every query ends in `keep()`.** Flux carries each column through and Grafana
turns every one into a series named after all the others.

## How a weather chart differs from a server chart

`style.py`. Grafana's defaults were chosen for CPU graphs, and three of them
are not merely plain here but wrong:

| | |
|---|---|
| Wind direction | A line goes 358, 359, 1 and falls the height of the panel. Points, on an axis pinned to the compass. |
| Rain | An automatic axis makes 0.2 mm and 40 mm look the same. Bars, from zero. Not Grafana's `lengthmm` either: it carries SI prefixes, so half a millimetre is drawn as "500 µm". |
| Humidity | An automatic axis turns 60–65 % into a crisis. It is a percentage; it runs 0 to 100. |

And one that is not a correction: a temperature line coloured by its own value
reads without the axis. On a *single* figure the same gradient does the
opposite — one number always sits at one end of its own range — so a stat
panel gets absolute steps, converted into the unit the figure is printed in.
A page in Fahrenheit turns amber at 79, not at 26.

Style hangs on the **unit group**, so a driver's own fields are covered by
`units.contribute` rather than by a list here.

## Language

One `language` setting reaches every renderer, and a dashboard is read by the
same people as the pages. Panel titles come from `units.obs_label`, so the
hundred charts are translated without a single string in `dashboards.py`. What
is left — four dashboard names, two variable labels, a handful of words like
"today" — is in `grafana/words.py` and translated under `[dashboard]` in
`lang/<code>.toml`. Anything absent stays English.

`--language` overrides the configured one, so the same station can be
published twice.

## Two stores, two truths

A record corrected by a `rebuild` has to reach InfluxDB too, or Grafana shows
one number and the station's own page another. Trusting that every write
landed is how the two drift.

```bash
weewx-evo upload compare --days 30 --read-token <ro>
```

counts both ends per window and names the ones that differ. Both sides cut on
plain epoch multiples: grouping the archive by local midnight would compare
one day with parts of two and report a drift where nothing is wrong.

## Running it

`deploy/compose.grafana.yml` is an **overlay**, not a replacement:

```bash
docker compose -f compose.yml -f compose.grafana.yml up -d
```

InfluxDB wants half a gigabyte and Grafana a quarter. A station in a shed
shares its machine, and somebody with one console should not pay for a
comparison they will never draw.

Set `INFLUX_TOKEN`, `INFLUX_PASSWORD` and `GRAFANA_PASSWORD` in `.env`; there
is no default for the last one, because a Grafana on a home network with
admin/admin is a weather station somebody else can reconfigure.
`GRAFANA_ANONYMOUS=true` turns the screen in the hall into something anybody
in the house can read without a login.

Grafana reads the provisioning directory at start and rescans the dashboards
every minute. A changed dashboard needs no restart; a new datasource does.

## What this does not do

**Publish.** Grafana is a service, and the strength of the rest of this
program is that publishing needs nothing reachable: a feed writes files and an
[export](Exports) puts them on a web host. Grafana cannot be uploaded.

So the split is deliberate. **Grafana is where a question is asked; [Deck](Deck)
is what gets published.** An installation that wants dashboards on the open
internet puts Grafana behind a reverse proxy and uses its shared dashboards,
which needs a domain and a certificate — the two things the rest of this
program is built to avoid needing. An installation that wants its places
compared *on its own website* configures a Deck feed to show them and points
an export at it, which needs neither.

**A comparison plot is left out of the per-location dashboards**, and that is
not an omission. Every panel there is filtered to `${location}`, so a plot
whose lines name their own archives would draw all of them out of the one
location the reader picked: N identical curves under N different place names,
which is a wrong picture rather than a missing one. The `compare` dashboard
already asks that question the way the data can answer it — one reading,
every location, from the tag, with the filter left off.

Rendering panels to PNG through Grafana's render API and letting the FTP
export carry them was considered and **decided against**: it needs a
Chromium container to publish pictures of charts that Deck already draws from
the same data. Panels are still written so that each is legible on its own at
1200×500, because that is what a screen on a wall wants as well.

**Forecast icons.** The forecast lives in `forecast.sdb` and the upload writes
archive records, so there is nothing in the bucket to draw yet.

## Tests

```bash
python tools/influx_test.py     # line protocol, the answers, counting
python tools/grafana_test.py    # layout, units, queries, language, the command
```

`grafana_test.py` walks every dashboard's grid cell by cell, because Grafana
overlaps two panels claiming the same cell silently and no parser finds it. It
also checks that no token reaches a dashboard: the datasource file holds the
credentials and is written 0600, while a dashboard is copied around and
rendered to PNG.

→ [Uploads](Uploads) · [Plots](Plots) · [Deck](Deck) · [Deployment](Deployment)

<!-- covers
src/weewx_evo/grafana/__init__.py
src/weewx_evo/grafana/dashboards.py
src/weewx_evo/grafana/panels.py
src/weewx_evo/grafana/query_influx.py
src/weewx_evo/grafana/style.py
src/weewx_evo/grafana/words.py
src/weewx_evo/grafana/icons.py
src/weewx_evo/uploads/influx.py
deploy/compose.grafana.yml
-->

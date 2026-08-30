# Deck

`src/weewx_evo/skins/deck/`. The skin that ships with weewx-evo.

Deck began as [weewx-wdc](https://github.com/Daveiano/weewx-wdc) by David
Baetge (GPL v3) and is still mostly his work. `CHANGES.md` beside the skin
lists what is different; this page is what an operator sets.

## Running it

A skin is rendered by a [Cheetah feed](Feeds), so Deck is one entry under
`[feeds]`:

```toml
feeds.site.kind = "cheetah"
feeds.site.skin = "deck"
```

Nothing else is needed. The pages land in the feed's directory and an
[export](Exports) moves them wherever they are published.

Two of them are two entries, which is how one station publishes the same
readings twice — a German page and an English one, or metric and US:

```toml
feeds.de.kind = "cheetah"
feeds.de.skin = "deck"
feeds.en.kind  = "cheetah"
feeds.en.skin  = "deck"
feeds.en.lang  = "en"
feeds.en.units = "US"
```

## Several places on one site

An installation with more than one [archive](Stations-and-Archives) keeps
several measurement series, each for its own place. One Deck feed publishes
all of them as **one site**:

```
one place                   several places
/index.html                 /index.html            the overview
/week.html                  /compare.html          the comparisons
/…                          /compare-week.html
                            /kirchdorf/index.html  each place, the pages above
                            /nordfeld/index.html
```

One feed, one directory, one export, one `live.json`. Separate feeds could not
link to one another, and every skin setting would be written out once per
place — which is the WeeWX arrangement this project removed.

**With one place nothing changes.** No overview, no subdirectory, no
comparison pages, and the output is what it has always been, file for file.
The gate is how many places *this feed shows*: a one-entry `archives.toml`
makes the settings page correctly say that `station.*` has moved, and is
still one place.

### What the operator sets

| | |
|---|---|
| `feeds.<name>.places` | which archives this instance shows, in that order. Empty is every one of them. This feed's own place is always first, whatever the list says: a site linking to places but not to the one its own pages are built from would publish an archive nothing on it can reach |
| `feeds.<name>.site_title` | what to head the overview with. Empty is the installation's own `station.name` — **not** `$station.location`, which under `archives.Placed` is the *default place's* label, so an overview headed "Kirchdorf" listing four places is a lie the page cannot detect |
| `feeds.<name>.place_pages` | which of the pages below each place gets. Empty is all of them |
| `feeds.<name>.places_fold` | how many places the sidebar lists before folding them into one entry |

The rest — which readings the board shows, which are compared, what counts as
unusual — is in `[DisplayOptions]` beside every other Deck setting.

### The overview

Two questions, in that order: **is anything unusual**, and **what is it like
at each place right now**. The second is what people came for; the first is
printed above it because an anomaly you have to look for is one you miss.

The unusual list has a closed set of three rules — two places' current
readings far apart, a place quiet for longer than its own rhythm, a place
past its own year's record — and **renders nothing at all when there is
nothing**. A warning that stands everywhere is not one, and that is exactly
why a line here can be trusted.

The board is a table, one row per place. Places down the side is the only
layout where "which place is coldest" costs no work, and the only one that
still fits eight places on a screen. **No summary row**: two thermometers
reading 19 and 21 do not make 20 anywhere. The one cross-place figure on the
page is a *difference*, and it names both of its ends.

### Comparing

`compare.html` and one file per span. Above the charts, a table of figures —
one row per reading, one column per place, and a Spread column carrying the
difference and both places it is between. Below, one chart per reading with
every place on one axis, each in its own colour.

The chips at the top switch a place off on every chart at once, which is the
question actually being asked ("just the two gardens") rather than the same
legend click repeated four times. With scripting off every place is on every
chart, and the table above is complete either way — it is server-rendered,
it prints, and it is the answer; the charts are the *shape* of the answer.

The comparison charts are ordinary [plots](Plots) whose lines name their
archive, so the image generator draws the same overlays. They are generated
rather than typed:

```bash
weewx-evo plots compare --write
```

Four readings by four spans by four places is sixty-four lines in a file.

**A comparison chart shades no night.** `sun.day_night` takes one place, and
one place's darkness drawn under four places' lines is minutes wrong on
numbers that are right — the exact failure per-archive coordinates exist to
prevent.

## Where the charts come from

**`plots.toml`, not the skin.** The page writes an empty grid naming a span;
`assets/charts.js` asks the manifest the `json` feed wrote, builds a card per
plot and draws it, then asks again every minute.

That is the difference worth knowing about this fork. Upstream, a chart is
defined in the skin and queried while the page is written — so it is as old as
the last render, and the skin holds an opinion about what a chart contains
while [`plots.toml`](Plots) and the plot editor hold another.

Two settings follow from it:

| Setting | What it does |
|---|---|
| `Extras.charts_path` | Where the chart files are **as the browser sees them**. They are a separate export from the pages — possibly to a different host — so this cannot be worked out here. Default `/json/`, which is what the built-in web server serves a local export named `json` at. |
| `DisplayOptions.diagrams.<span>.plots` | Which plots that span shows, in that order. Empty means every plot the manifest has for it, which is the right default: a plot added in the settings appears without editing a skin. |

**The old way is still there**, one span at a time, for a station whose
charts are not in `plots.toml`:

```
[DisplayOptions]
    [[diagrams]]
        [[[week]]]
            source = observations
```

Then the `[[diagrams]]` section is read the way upstream reads it: an
observation list per span, with `label`, `color`, `aggregate_type`,
`aggregate_interval`, `curve`, `enableArea`, `areaOpacity`, `lineWidth` and
`markerValue`. Anything else named in upstream's wiki was a
[Nivo](https://nivo.rocks) option — `pointSize`, `yScaleOffset`,
`enableCrosshair` and the rest — and this skin draws with ECharts, which takes
none of them. They were removed rather than left to look configurable.

## The pages

| Page | Shown when |
|---|---|
| Today, Week, Month, Year | always |
| Yesterday | its entry under `[CheetahGenerator][[ToDate]]` is uncommented. Off by default |
| Celestial | always. Sun, moon and planets, from `sun.py`, `moon.py`, `planets.py` |
| Statistics | always |
| Sensor Status | its entry is uncommented too, and the archive holds something `sensor_stat_tile_observations` names |
| Computer Monitor | the same, for `computer_monitor_*`: what [weewx-cmon](https://github.com/matthewwall/weewx-cmon) records |
| Webcams / Externals | `[[externals]]` names at least one |
| A month or a year of the archive | one per month and year with records |
| Overview, Comparison | only when this feed shows more than one place |

With several places every row above is written once per place, into that
place's own directory, and a place with no records yet gets no directory and
nothing links to it — a link into a directory the feed did not write is a 404
on somebody's web host.

### Webcams and other externals

Anything with a URL: a camera still, a video, an embedded map.

```
[DisplayOptions]
    [[externals]]
        description = 'Shown at the top of the page.'
        [[[backyard]]]
            source = '<img src="https://example.org/current.jpg" />'
            title = 'The garden'
            description = 'Updated every five minutes.'
```

`source` is HTML and is written out as it stands, so it can be an `<img>`, a
`<video>` or an `<iframe>`. `Extras.open_radar_and_externals_modal` decides
whether clicking one opens it large.

### Sensor status

Signal strengths and battery levels, which every console reports and nothing
else on the site shows.

| Setting | What |
|---|---|
| `sensor_stat_tile_observations` | The tiles at the top |
| `sensor_diagram_observations` | Which of them get a chart |
| `sensor_table_observations` | Which go in the table |
| `sensor_battery_status` | Read as "ok / not ok" rather than as a number |
| `sensor_diagram_period` | `day`, `week`, `month` or `year` |

A reading named here that the archive has no column for is left out, so the
list can name everything a driver might report.

## The tiles

`stat_tile_observations` is the row of figures at the top of every span page;
`table_tile_observations` is the table under it. Both are lists of readings,
shown in the order they are named, and a reading with no data on that span is
skipped.

| Setting | What |
|---|---|
| `stat_tiles_show_min` / `_max` / `_sum` | Which extra figure a tile carries under the current one |
| `show_min_max_time_day` and its four siblings | Whether the time of the min and max is printed as well |
| `outTemp_stat_tile_color` | Colours the temperature tile by its value, between `_color_min` and `_color_max` |
| `stat_tile_winddir_ordinal` | `NNE` rather than `22°` |

### Gauges

Round dials for the current reading. `alternative` layout only.

```
[DisplayOptions]
    gauges_display = before      # or 'after' -- where they sit
    gauges_size = medium         # small, medium, large
    [[Gauges]]
        [[[outTemp]]]
            min = -20
            max = 40
```

`min` and `max` are the ends of the dial. Without them the gauge takes the
range from the data, which moves as the weather does.

### Stat tables

A table of aggregates on the statistics and year pages.

```
[DisplayOptions]
    [[stat_tables]]
        [[[tables_outtemp]]]
            observation = "outTemp"
            label = "Temperature"
            aggregate_types = "min", "avg", "max"
```

### Extended aggregates

`[[stat_tiles_xaggs]]` adds historical aggregates to a tile — the all-time max
for this day of the year, days above a threshold, and so on. It needs
[weewx-xaggs](https://github.com/tkeffer/weewx-xaggs), which weewx-evo does not
ship: with the extension absent the section is ignored rather than breaking the
page.

## Layout, theme and language

| Setting | What |
|---|---|
| `DisplayOptions.layout` | `alternative` (cards) or `classic` (closer to upstream's first design) |
| `DisplayOptions.default_theme` | `auto`, `light` or `dark`. `auto` follows the browser, and the switch in the header overrides it per visitor |
| `Extras.base_path` | The path the site is reached at, when it is not the root: `/weather/` |
| `Extras.logo_image` | A URL, if the mark in the header should be your own |
| `feeds.<name>.lang` | The language, from `lang/*.conf`. Deck ships de, en, fi, it and nl |

Language files are whole skin configurations rather than word lists — units,
labels, the points of the compass — and `skin.conf` overrides them, which is
[WeeWX's order](WeeWX-Compatibility) and is kept.

## Live readings

The station posts its current readings to `live.php`, which writes them beside
itself; the page reads that file every ten seconds. No broker, no port
forwarded, no certificate. It is set up by whichever [export](Exports)
publishes these pages — there is nothing to configure in the skin.

`Extras.live_push` switches the poller off for a site that does not want it.

## What this skin does not have

- **Nivo's chart options.** ECharts draws here. See above.
- **weewx-forecast and weewx-DWD.** The forecast section reads
  [`$forecast`](Forecast), which is weewx-evo's own and covers hours, days,
  warnings and the model run.
- **A `[[Rounding]]` section per table.** Decimal places come from the units
  the page is written in.

<!-- covers
src/weewx_evo/skins/deck/options.py
src/weewx_evo/skins/deck/tags.py
src/weewx_evo/skins/deck/skin.conf
src/weewx_evo/skins/__init__.py
src/weewx_evo/skins/deck/CHANGES.md
src/weewx_evo/skins/deck/README.md
-->

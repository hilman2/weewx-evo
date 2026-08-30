# Plots

`plots.py`, `adminplots.py`, `plots.toml`.

## Plot definitions belong to weewx-evo, not to a renderer

In WeeWX they sit in `[ImageGenerator]` inside a **skin**. Plots are a property
of the drawer there. Two drawers mean two copies of the same list — and the JSON
generator only exists because it reads the image generator's configuration
behind its back.

Here the definition comes first and the renderers are consumers.

| File | What |
|---|---|
| `plots.py` | The model (`Plot`, `Line`, `PlotSet`), reading and writing `plots.toml`, and the importer |
| `plots.toml` | Its own file, next to the configuration |
| `adminplots.py` | The pages for it — the only hand-written part of the admin interface |

**Why a file of its own:** settings are a few dozen named values; this is a list
of many alike sets with lists inside them. And a set imported from an old skin
is something you want to be able to diff and pass on.

## The model

### `Line` — one reading in a plot

| Field | What it means |
|---|---|
| `obs` | The reading |
| `label` | What it is called in the legend |
| `kind` | `line` · `bar` · `vector` |
| `color`, `fill_color` | |
| `width` | |
| `aggregate` | `avg` `min` `max` `sum` … or empty for the records themselves |
| `interval` | Bucket size: seconds or `hour` `day` `week` `month` `year` |
| `marker`, `marker_size` | |
| `gap_fraction` | The distance at which a gap is a gap |
| `rotate` | |
| `series` | Which [archive](Stations-and-Archives.md) this line reads. Empty is the one the chart is being drawn for, which is every line on every station with one series |
| `binding` | WeeWX's `data_binding`, carried through an import and back out again. Read by nothing here |

`series` is what "outTemp at all five locations on one axis" is: five lines,
one plot, each naming its own place. It is **not** `binding`, which sits
beside it and means something else — `wx_binding` names a *schema*, not a
place, and one field with two meanings holds until somebody names an archive
`wx_binding`.

Two consequences worth knowing:

- **A line naming an archive that is not configured is left out**, not read
  from the default. Silently drawing one location's temperature under another
  location's label is the one outcome worse than a chart with a line missing,
  and nothing on the page could show it.
- **A plot whose lines name places is filed once, for the site**; every other
  plot is drawn once per place. The directory is what says which, so nothing
  downstream needs a flag that could disagree with it.

`resolved(position)` returns the same line with the colours WeeWX would have
given it — `LINE_COLORS` and `FILL_COLORS`, in the same order.
`drawn_with(colors)` is the same thing with each place's own colour where it
has one, out of `archives.toml`. That is not taste: `resolved` cycles five
colours modulo the index *within one plot*, so the same place would come out
blue on the temperature chart and red on the humidity chart — and a legend
that says a place *is* a colour would then be lying on one of the two.

### `Plot` — one plot

| Field | What it means |
|---|---|
| `name` | Also the file name |
| `span` | The **group**: `day` `week` `month` `year`. For the manifest and the admin page |
| `time_length` | What actually decides how far back it reaches |
| `lines` | |
| `title` | |
| `show_daynight` | Shade the night → [Sun](Sun) |
| `yscale` | `[ymin, ymax, ystep]` |
| `skip_if_empty` | A **timespan**, not a boolean. See [below](#two-pitfalls-in-the-importer) |

`drawn()` returns the lines with their colours filled in. `uses()` says which
readings this plot needs. `places()` is the archives its lines name, in the
order they name them, and `names_a_place()` is the filing rule — deliberately
not "draws more than one place", because a single line reading the north field
produces the same numbers whichever place's page it is on and is therefore
written once.

### `PlotSet` — the plots there are

Plus `labels`: what the readings in them are called.

| Method | What it means |
|---|---|
| `get`, `add`, `remove` | |
| `by_span()` | Grouped, in the order the groups first appeared |
| `spans()` | How long each group covers, for the manifest. Taken from the longest plot in the group, because that is the group |
| `uses()` | Every reading needed |

## `plots.toml`

```toml
# The charts weewx-evo produces.
#
# Each [[plot]] is one chart; each [[plot.line]] is one reading in it.
# 'span' groups plots for the manifest and for the admin page;
# 'time_length' is what actually decides how far back it reaches.

[labels]
extraTemp3 = "Greenhouse"

[[plot]]
name = "daytempdew"
span = "day"
time_length = "27h"
show_daynight = true
ymin = 10
ymax = 25

  [[plot.line]]
  obs = "outTemp"
  label = "Outside temperature"

  [[plot.line]]
  obs = "dewpoint"

[[plot]]
name = "monthrain"
span = "month"
time_length = "30d"

  [[plot.line]]
  obs = "rain"
  kind = "bar"
  aggregate = "sum"
  interval = "day"
```

| Function | What it means |
|---|---|
| `load(path)` | Read. A file that is not there means no plots, not an error |
| `from_dict(raw)` | From already-parsed TOML |
| `save(path, plots, note)` | Write, with a `.bak` of the previous version |
| `render(plots, note)` | As TOML text somebody can edit |

`save()` writes **alongside and moves into place**, like the configuration: this
file decides what a page shows, and an interrupted write must not leave half of
one.

`labels` sits in the same file, because a name somebody gave eight years ago
("Greenhouse" for `extraTemp3`) should move house together with the plots.

## The importer

**Not a sideshow.** Once the definitions become independent, it is the whole
rest of the bridge to 15 years of maintained configurations.

```bash
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf --write
weewx-evo plots import … --write --replace
```

Reads, reports, and only writes on `--write`. Names what it left behind rather
than pretending it understood it.

```python
@dataclass
class Imported:
    plots: PlotSet
    drawing: set[str]   # options that describe an *image*
    unknown: set[str]   # options nobody here understands
    empty: list[str]    # sections that looked like plots and held nothing
```

`_is_drawing(key)` decides what describes an *image* and makes no sense here.
Three routes:

- `IMAGE_ONLY` — the list by name: `image_width`, `image_height`, `anti_alias`,
  `chart_background_color`, `chart_gridline_color` …
- `DRAWING_PREFIXES` — `image_`, `chart_`, `rose_`, `daynight_`,
  `axis_label_`, `top_label_`, `bottom_label_`, `unit_label_`, `x_label_`,
  `y_label_`
- anything with `_font` in it or ending in `_color`

**One exception:** `rose_label`. How the wind rose is labelled is *text*, and a
plot in a browser needs it just as much as a PNG does.

What gets sorted out this way is **named**, not silently discarded.

| Function | What it means |
|---|---|
| `from_image_generator(section, labels)` | Plots out of an `[ImageGenerator]` |
| `labels_from(conf)` | `[Labels] [[Generic]]` — worth taking along for its own sake |
| `_line_from(name, options)` | An `[[[[outTemp]]]]` subsection |
| `_color(value)` | A WeeWX colour as CSS understands it |

The structure in WeeWX is three levels deep: a group (`[[day_images]]`), a plot
(`[[[daytempdew]]]`), a line (`[[[[outTemp]]]]`). Options inherit downwards.

`_line_from` takes the section name as the reading, unless `data_type` says
otherwise — that is how WeeWX draws the same reading twice in one plot with two
aggregations.

`_color()` has to handle three spellings: `#RRGGBB`, `0xBBGGRR` and English
names. The first and the last are already CSS; **the middle one is byte-swapped**
and has to be reversed — exactly the sort of detail that colours a plot
plausibly wrong.

`_holds_plots()` tells a section that defines plots from one that merely holds
settings: a group like `[[day_images]]` has subsections that themselves have
subsections. A settings block like `[[Archive]]` carries scalars.

### Two pitfalls in the importer

Both of them real.

#### WeeWX's suffixes are not ours

There, `M` is a **minute** and `m` is a **month**. Here `m` is minutes, as
everywhere else.

A file written for WeeWX is read by **WeeWX's rules** (`_weewx_span`) — and
**nothing is ever written back with an ambiguous suffix**: `_normalise()` turns
`1w` into the word `week`, never a month into `1m`.

```python
_WEEWX_SUFFIX = {"M": 60, "h": 3600, "d": 86400,
                 "w": 604800, "m": NOMINAL["month"], "y": NOMINAL["year"]}
```

Anything unreadable returns the default rather than a guess — a wrongly guessed
interval is a plot that looks plausible and is wrong.

#### `skip_if_empty = year` is a timespan, not a boolean

Read as a boolean, the Seasons set writes **100 files instead of 71** — 29 of
them nothing but zeroes for sensors this station never had.

`_span_name()` reads it correctly. `true` is read as "the plot's own span",
which is the only reading that does anything.

## The admin pages

`adminplots.py`. **The only hand-written part of the admin interface.**

A plot does not fit the form generator the rest of the settings use, and forcing
it in would be worse than writing this: a setting is **one** named value, a plot
is a set with a list of sets inside it, and there are a hundred of them.

| Function | What it means |
|---|---|
| `path_for(admin)` | Where `plots.toml` lives: next to the configuration |
| `load(admin)`, `store(admin, charts, note)` | |
| `add(admin, name, span, obs)` | A new plot with one reading. Everything else on the next page |
| `remove(admin, name)` | |
| `save(admin, name, form, columns)` | Everything about a plot, out of its form |
| `bring_over(admin, source, replace, text="", origin=…)` | Import from a skin — from an uploaded file, from pasted text, or from a path |
| `nav(admin, active)` | The plots in the sidebar, grouped the way they are grouped |
| `edit`, `new`, `importer` | The three pages |

The choice lists are at the top of the file: `KINDS`, `USEFUL` (aggregates),
`INTERVALS`, `LENGTHS`, `EMPTY`. They are labelled in plain words — `"27h", "a
day and the night before it"` — because a choice showing seconds is one where
somebody has to do arithmetic.

`columns` comes from the **database**, not from a schema: a station whose driver
created columns of its own should be able to plot them.

### Three ways into the importer, and the order matters

1. **Upload a file.** The only one that works from anywhere: the skin is on the
   machine somebody is sitting at, not necessarily on the one this is running
   on. In a container there is **no path at all** from here that reaches the
   skin.
2. **Paste the text.** The whole file or just the `[ImageGenerator]` part.
3. **A path on this machine.** The least useful of the three, and therefore
   offered last. Anyone who has a path usually has a shell too — and then
   `weewx-evo plots import` is the better fit.

The uploaded file is read and **not kept**.

## Commands

```bash
weewx-evo plots list
weewx-evo plots show <name>
weewx-evo plots import <skin.conf> [--write] [--replace]
weewx-evo plots remove <name>
weewx-evo plots run [--into DIR] [--no-page]
```

→ [CLI-Reference](CLI-Reference#plots), [Feeds](Feeds)

<!-- covers
src/weewx_evo/plots.py
src/weewx_evo/adminplots.py
-->

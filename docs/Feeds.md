# Feeds

`feeds/`, `feedrunner.py`.

A driver brings readings in. A **feed** makes something out of them — a CSV, a
JSON document, a plot, a whole website, a monthly report. An
**[export](Exports)** takes what a feed produced and brings it somewhere else.

```
feed   → a directory full of files
export → that directory, sent somewhere
```

**The directory is the entire interface.** Exactly like the live table between
listener and archiver. One feed, three exports. Or three feeds into one
directory and one export. Neither knows about the other.

The settings page draws that arrangement: each feed with the exports carrying
it underneath, so which one moves what is a thing to look at rather than to
work out.

In WeeWX a "skin" renders files *and* the FTP upload is configured in the same
section. One page for two destinations means running the renderer twice.

## One folder per feed

Like drivers under `ingest/plugins/`:

```
feeds/
  jsongenerator/     the series everything else stands on
  diagnostic/        draws what is actually on disk
    vendor/          its own uPlot, MIT, 51 KB
  cheetah/           runs a WeeWX skin, unchanged -- see [Deck](Deck)
  imagegenerator/    the same charts as PNG
```

A feed that gains templates, stylesheets or a JS bundle keeps them next to its
code rather than in a shared heap; a deleted feed takes its assets with it.

## The interface

```python
class Feed(Protocol):
    trigger: str    # "record" | "packet" | "schedule"

    def produce(self, archive, into: Path) -> Produced:
        ...

    @staticmethod
    def options():   # the admin page builds a form out of this
        ...
```

```python
@dataclass
class Produced:
    directory: Path
    files: list[Path]
    note: str
```

**The file list is what counts for the exports.** An export that knows which
files changed sends those; one that does not sends everything every time. Over a
mobile connection that is the difference.

`archive` is a **read-only** view: a feed reports history, it does not write it.
Whatever it raises is logged and holds nothing up.

### One feed, several places

`Produced.directory` is still one directory, and that is deliberate. An
installation with more than one [archive](Stations-and-Archives) publishes
one *site*, and a site of several places is a tree inside that one directory:
an overview at the root and a subdirectory per place. One export moves it,
one upload writes its `live.json`, and nothing about `Produced` had to grow.

Two feeds would have been the other answer and it is the wrong one: neither
could link to the other, and every skin setting would be written out once per
place — the WeeWX arrangement this project removed.

Which places a feed shows is `feeds.<name>.places`; which archive it *reads*
is `feeds.<name>.archive`, singular, and stays what it was. The two are one
letter apart on purpose and do different jobs: `archive` gates
`record_written`, chooses the `Reader` and is the place the pages are wrapped
in. A feed that names places still reads one.

## The registry

| | |
|---|---|
| `TRIGGERS` | `("record", "packet", "schedule")` |
| `ENTRY_POINT_GROUP` | `"weewx_evo.feeds"` |
| `BUNDLED` | What ships with it, as `(name, module, class, description)` |
| `DESCRIPTIONS` | What each one is, in a few words |
| `load()` | Bring the feeds in |
| `names()` | The feeds there are |
| `get(name)` | |
| `describe(name)` | One line about a feed, for a form that offers it |
| `register(name, feed, description="")` | |

`names()` is a **function**, so that an export's choice list fills itself as soon
as a feed appears. The export does not have to be told, and nobody has to
restart anything.

`BUNDLED` is **named here** rather than found by walking the directory: a
half-finished feed in the folder should not turn up in a form. That is the
difference from the drivers, where every subdirectory is tried.

`load()` reports a broken feed but is **never fatal** — the same arrangement as
with the drivers. A station whose diagnostic page is broken should carry on
writing its series.

`DESCRIPTIONS` exists for the choice list: it would otherwise be a list of
names, and `"json"` does not say what is in it.

## The feed runner

`feedrunner.py`. Runs the feeds in order on a **thread of its own**.

A hundred plots are the best part of a second of reading and writing. Done where
the archiver runs, that is a second in which it is not archiving — every
interval, forever.

So the same arrangement as with the exports: **the archiver sets a flag and
returns**, and the work happens here.

**One thread for all feeds, not one per feed.** They are ordered: the diagnostic
page draws what the JSON feed wrote.

```python
runner = Runner(feeds, archive_path)
runner.start()
runner.record_written()    # from the archiver, returns immediately
```

| Method | What it means |
|---|---|
| `record_written()` | Sets a flag and returns |
| `run_once()` | Every feed, in order. Returns what happened |
| `status()` | For a status page |
| `start()`, `stop()` | |

`SETTLE = 2.0` — two seconds after the flag, so that several records in quick
succession make one run and not three.

After the run it calls `exports.runner.Runner.feed_produced(name, files)`. That
is the `feed` trigger. → [Exports](Exports)

The order comes from `cli.build_feeds()`: JSON first, because the diagnostic
page draws what it wrote. **That is the only dependency between two feeds at
all**, and it sits there rather than in either of them.

## The JSON feed

`feeds/jsongenerator/`. The feed that ships with it and cannot be removed,
because everything else stands on it.

A plot in a browser, a page rendered from a template, an export to a static
host, an image generator if one is ever written — they all want the same thing:
one reading over a span at a resolution, with its unit and its label.

> This reinvention is not hypothetical. Every JavaScript skin for WeeWX —
> Belchertown, wdc, jas and the rest — carries its own copy of the same idea,
> its own plot configuration format and its own bugs in it. None of them shares
> anything. This exists so that a skin can be a skin.

### What it writes

With one place, one flat directory — unchanged. With several:

```
<charts>/index.json            the site manifest: the comparison charts
<charts>/<plot>.json           a chart whose lines name their places
<charts>/<place>/index.json    that place's manifest
<charts>/<place>/<plot>.json   that place's charts
```

**The directory is the facet.** A place's page fetches its own directory and
finds only its own charts; a comparison page fetches the root and finds only
comparisons. Nothing carries a flag that could disagree with where the file
actually is.

Every key this adds is optional and written only when it has something to
say, and `format` stays 1: bumping it would make every chart file on every
station compare unequal exactly once, and the next export would upload the
whole directory for no reader.


```
<target>/daytempdew.json
<target>/weekrain.json
<target>/index.json          the manifest
```

The manifest says what there is, so that a client can lay out its page before
fetching anything — and never asks for a sensor this station does not have.

### The shape

```json
{
  "name": "daytempdew",
  "format": 1,
  "generated": 1755950000,
  "start": 1755863600, "stop": 1755950000,
  "asked": [1755863600, 1755950000],
  "unit": "degree_C", "unit_label": "°C",
  "yscale": [10, 25, 5],
  "daynight": {"first": "night", "transitions": [], "twilight": []},
  "series": [
    {"obs_type": "outTemp", "label": "Outside temperature",
     "plot_type": "line", "color": "#4282b4",
     "time": [], "values": []}
  ]
}
```

`format` is in every file so that a client knows whether it understands it.
Raised **only** when the shape changes in a way that breaks a reader — not when
a key is added.

`start`/`stop` are what the data **covers**, `asked` is what was requested. The
difference: a bucket is drawn as what it covers, and the last one of a day plot
covers the whole of today — so it ends at tomorrow's midnight, after the moment
the file was written. Without that, the last bar falls off the edge of the plot.

### One plot, one unit

The first line that has one decides. WeeWX flatly refuses to draw two units
together. Here the first is reported and the rest stays **on the lines**, so
that a client can at least see the disagreement rather than being told the plot
is impossible.

### What gets left out

| | |
|---|---|
| A plot in which every line came back empty | Is not written at all. The shipped set covers sensors most stations do not have, and a hundred files full of nulls help nobody |
| Points that carry nothing | `_drop_empty()`. A sensor reporting every ten minutes fills one archive record in ten, and the rest hold `null` for it. Sent like that, a client draws a line that looks half broken |
| Real gaps | Stay visible. `GAP_FACTOR = 3.0`: three times the usual spacing is a gap, not the rhythm. **Judged from the readings themselves**, because ten minutes is an outage for a station reporting every eight seconds and the normal case for one reporting every ten minutes |

`gap_fraction` from the plot definition — WeeWX's own fixed measure — still beats
that, but **only on an unaggregated series**. On an aggregated one the bucket
*is* the spacing, and a fraction of the plot width says nothing there.
| Sensors that never existed | `_exists()`. The difference between a reading that is missing today and one that never existed. WeeWX's `skip_if_empty = year` says exactly that |

### `_same()` — do not rewrite what is the same

A year of daily means says the same thing at ten past as it did at ten.
**Everything except the timestamp** is compared. That counts when an export
sends everything that changed.

Can be turned off with `feeds.json.rewrite_unchanged`.

### `_write()` — alongside and moved into place

A client fetching while a write is in progress should get the old file, not half
the new one.

### Vectors

`_components(magnitudes, directions, places)` breaks a vector series into "how
far east" and "how far north". A plot drawing arrows scales and shifts the
components; sending them along saves rebuilding them from magnitude and
direction at the far end — and saves getting it wrong.

### Settings

→ [Settings-Reference](Settings-Reference#feed-json)

```bash
weewx-evo plots run --into data/public_html
```

## The diagnostic feed

`feeds/diagnostic/`. **Deliberately stupid.**

It does not read the plot definitions, does not know what a plot is supposed to
look like, and has nothing to configure. It walks a directory, takes every JSON
file containing a series, draws it, and lists everything that looks wrong.

**That is the whole point.** Every other feed renders what it *meant*. This one
renders what is **actually on disk** — and thereby answers the question that
otherwise costs an afternoon: *is it the data or the template?*

| Method | What it means |
|---|---|
| `read()` | Every JSON file in the source directory, examined |
| `_examine(entry, payload)` | Pull out what is drawable, and note what is not |
| `render(found, now)` | The page |
| `_thinned(charts)` | The same plots, downsampled to something a browser can draw |

`draw_limit = 400` points per series. **The data in the page stays whole** —
only what is drawn is thinned. A hundred thousand points are a black rectangle
either way.

`BIG = 2_000_000` — from that file size on, it warns.

The uPlot in `vendor/` (MIT, 51 KB) sits with the feed, not in a shared heap: a
diagnostic page that needs a CDN fails exactly when you need it.

### Settings

| Name | Default | |
|---|---|---|
| `feeds.diagnostic.enabled` | `true` | A single, self-contained HTML file |
| `feeds.diagnostic.source` | `json` | Which directory gets drawn |
| `feeds.diagnostic.points` | `400` (50–20000) | Points per series in the plot |

## Writing a feed

```python
from pathlib import Path
from weewx_evo.feeds import Produced


class CsvFeed:
    trigger = "record"

    def produce(self, archive, into: Path) -> Produced:
        target = into / "latest.csv"
        target.write_text(…)
        return Produced(directory=into, files=[target], note="1 file")

    @staticmethod
    def options():
        return [...]
```

Register with `feeds.register(name, feed, description)` or as an entry point
under `weewx_evo.feeds`. A feed we maintain additionally goes into `BUNDLED`.

<!-- covers
src/weewx_evo/feeds/__init__.py
src/weewx_evo/feeds/jsongenerator/__init__.py
src/weewx_evo/feeds/diagnostic/__init__.py
src/weewx_evo/feeds/diagnostic/vendor/LICENSE
src/weewx_evo/feedrunner.py
src/weewx_evo/feeds/cheetah/__init__.py
src/weewx_evo/feeds/realtime/__init__.py
src/weewx_evo/tags.py
src/weewx_evo/skinkit.py
src/weewx_evo/schedule.py
-->

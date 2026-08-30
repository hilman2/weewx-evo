# Charts

Which charts there are, what goes on them, and where they come out.

**A chart is defined once and drawn by whoever asks.** In WeeWX the definitions
live inside a skin's `[ImageGenerator]`, so two renderers mean two copies of
the same list — and the JSON generator only exists because it reads the image
generator's configuration behind its back.

Here they are in `plots.toml`, and the renderers are customers: the JSON feed,
the PNG feed, Deck, and Grafana all draw the same list.

## What you get without doing anything

A fresh installation starts with the Seasons set — around a hundred charts,
the ones a WeeWX station has had for fifteen years. A chart whose readings this
station does not record is skipped rather than written full of nulls.

## Changing them

**Charts** on the settings page. One chart is a name, a timespan and the
readings on it; each reading can say its colour, its axis and how it
aggregates.

```bash
weewx-evo plots list
weewx-evo plots show daytemp
```

## Bringing your own from a skin

Fifteen years of a tuned `skin.conf` is worth more than a fresh start:

```bash
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf          # reports
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf --write  # writes
```

It reads, reports, and writes only on `--write`. **It names what it left
behind** — fonts, image sizes, background colours, everything describing a
*picture* rather than a chart — rather than pretending to have understood it.

→ [Plots](Plots#the-importer)

## Where they come out

| | |
|---|---|
| `json` feed | the numbers, for a page to draw in the browser |
| `images` feed | PNG, at twice the display size so a phone shows it sharp |
| Deck | draws the JSON with ECharts |
| Grafana | the same definitions become dashboard panels |

The arithmetic happens **once**, in one place, for all four. That is the point:
WeeWX computes the same average twice and the two disagree in the third
decimal, which nobody finds because each is right on its own.
→ [Plots](Plots)

## Several places on one chart

A chart line names the place it reads, so one chart can draw two places on one
axis — the garden and the allotment, same scale, same colours as everywhere
else. → [Several places](Places)

## Comparing periods

```bash
weewx-evo plots compare --write
```

Generates the overlay charts a comparison page draws: this week against last,
this year against the one before.

<!-- watches
src/weewx_evo/plots.py
src/weewx_evo/adminplots.py
src/weewx_evo/chartdata.py
src/weewx_evo/starter/plots.toml
-->

# Deck

The skin weewx-evo ships. Tiles, charts drawn in the browser, and a page
that works on a phone.

## Where it comes from

Deck began as **[weewx-wdc](https://github.com/Daveiano/weewx-wdc)** by
David Baetge, taken at release **v3.5.1**. The layout, the design, the
templates and the TypeScript are his work, and far more of what you see is
his than ours. Both projects are GPL v3, which is what makes this possible;
the copyright notices in the files it came with are his and stay.

It is ours from here on. That is a decision, not a drift: upstream went
quiet, and a skin a station renders every five minutes needs somebody who
will take a one-line fix. Before the split, the fixes found here went back
as pull requests. Nothing comes down from upstream now, and nothing here is
kept portable to it.

What that bought is the whole reason for doing it. A skin that has to stay
mergeable cannot call anything by our names, so it reaches WeeWX's way --
through a shim, through a binding lookup that resolves to the one database
we have, through `weewx.conf` sections that do not exist here. All of that
is gone. `tags.py` imports from `weewx_evo.skinkit` by name, and rendering
this skin never loads a module called `weewx`.

## What it needs

Cheetah, for the templates. Nothing else: the charts are drawn in the
browser from data written into the page, and everything they need --
`dist/`, the typefaces, the charting library -- ships with the skin.

`src/` holds the TypeScript and SCSS the files in `dist/` are built from.
Building them needs node and yarn, and nothing here does: a weather station
should not need a JavaScript toolchain to publish a page, so `dist/` is
checked in.

## Its settings

Three kinds, in three places, and the split is the point.

**The named values** -- forty of them, the ones somebody actually changes:
which readings get a tile, the layout, whether the wind rose counts in
Beaufort. Those are declared in `options.py`, which makes the form field on
the admin page, the validation, the comment in the written file and the
line in `--explain`, all from the one entry. There is no second place to
register one.

    weewx-evo serve --config evo.toml --explain

shows them under `Feed: <name>`, with where each came from.

**The sets with sets in them** -- the diagram definitions, the gauges, the
tables. A form generator does one named value at a time; a diagram is a set
of lines with a set of properties each. Those stay in `skin.conf`, for the
same reason plot definitions live in `plots.toml`.

**The words** -- labels, units, translations. Those are the skin's language
files under `lang/`, and choosing a language takes all of them at once.

An operator who sets nothing gets what `skin.conf` says, which is a working
site. Anything set through the settings goes on top of it, and survives an
update of the skin.

`base_path` is the one nearly every installation needs, and it is an
`[Extras]` value rather than a display option because the templates read it
as `$Extras.base_path`:

    feeds.<name>.extras.base_path = "/deck/"

Published anywhere but the root of a site without it, the skin looks for
its stylesheet and its charts at the root and finds nothing.

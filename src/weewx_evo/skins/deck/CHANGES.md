# What is different from weewx-wdc v3.5.1

GPL v3 asks that changed files carry a notice saying they were changed.
This is that notice.

It is no longer a list for sending upstream. Deck is ours from here on (see
`README.md`), and the entries below say what was wrong and how it showed,
because a fix without that is a line nobody dares touch later.

## Fixed

### `get_windrose_data` raises on an hour of dead calm

`vecdir` returns None for a null vector: with no wind there is no
direction, and that is right. `to_ordinal_compass` turns None into "N/A",
which the line above has already popped off `ordinals`. The loop only
skipped when the *speed* was None, and calm is 0.0, so
`ordinals.index("N/A")` raised and took the whole week page with it.

Now it skips when either is missing.

Reported upstream: https://github.com/Daveiano/weewx-wdc/issues/311

### The dead branch in the current-value tiles

`#if $skin_obs_binding != 'wx_binding'` had the same statement in both
arms, in `stat-tile.inc` and in `conditions-table.inc`. It went out with
the bindings.

## Made ours

### The tag layer is `weewx_evo.skinkit`, by name

`tags.py` (was `bin/user/weewx_wdc.py`) imports what it needs from
`weewx_evo.skinkit`. Rendering this skin never loads a module called
`weewx`; the shim that answers `import weewx` for a skin from outside is
not installed for it.

### The data bindings are gone

WeeWX addresses a second database through a binding name. There is one
archive here. `get_data_binding`, `get_data_binding_combined_diagram`,
`get_custom_data_binding_obs_key`, `[ObservationBindings]` and 218 uses of
`$data_binding=` across ten templates all resolved to the same database,
and said so through eight nested calls:

    #set $skin_obs_binding = $get_data_binding($skin_obs, $context)
    #set $alltime_tag = $alltime($data_binding=$skin_obs_binding) if ...
    #if $getattr($get_time_span_from_context($context,
        $day($data_binding=$skin_obs_binding), ...

is now

    #if $getattr($get_time_span_from_context($context,
        $day, $week, $month, $year, $alltime, $yesterday), ...

The variables that survived hold a timespan and are named for one.

### The settings that were read out of `weewx.conf`

Three lookups went through sections that do not exist here:

| was | is |
|---|---|
| `config_dict["StdReport"]["WdcReport"]["lang"]` | the one language setting, which decides it everywhere |
| `config_dict["StdWXCalculate"]["Calculations"]` | `[derive]`, which is what the archiver actually ran on |
| `config_dict["DeutscherWetterdienst"]["warning"]` | `[DisplayOptions][[dwd]][[[warning]]]` |

`generator.config_dict` is not read at all any more.

### Forty settings became `Option`s

`options.py` declares what `[DisplayOptions]` held as scalars: the layout,
which readings get a tile, the wind rose, the climatological days. Each one
makes its own form field on the admin page, its own validation and its own
`--explain` line. The diagram definitions stay in `skin.conf`, which is
where a set with sets in it belongs.

### Renamed to `deck`

Two skins called weewx-wdc, one of them changed, would be worse for
everybody than two names. `SKIN_NAME` says `Deck`.

## Left alone on purpose

The layout, the design, the TypeScript and the SCSS are as they were. The
`dist/` bundle is the one upstream built. What changed is how the skin
reaches the data, not what it draws.

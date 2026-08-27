<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
#import html
#import datetime
#set $diagrams_config = $DisplayOptions.get("diagrams", {})
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />

<link rel="stylesheet" href="$asset('assets/deck.css')" />

<link
  rel="icon"
  type="image/x-icon"
  href="$get_base_path(path='favicon.ico')"
/>
<meta
  name="description"
  content='Weewx $station.location - $gettext("Station Description")'
/>
<link rel="manifest" href="$get_base_path(path='manifest.json')" />
<link rel="apple-touch-icon" href="$get_base_path(path='icon-192x192.png')" />

## The theme, before the first pixel. Loaded with the rest of the scripts it
## would paint light and then flip, which is the flash everybody knows and
## nobody wants at six in the morning. Ten lines inline is the price.
<!--prettier-ignore-->
<script>
  (function () {
    var fallback = '$DisplayOptions.get("default_theme", "auto")';
    var chosen = null;
    try { chosen = localStorage.getItem("weewx_evo.deck.color-theme"); }
    catch (e) { /* private window: fall through to the default */ }
    var theme = chosen || (fallback === "auto" ? null : fallback);
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.setProperty(
      "color-scheme", theme || "light dark");
  })();
</script>
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#ffffff" />
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#161c24" />

<!--prettier-ignore-->
#set $diagramWindDirOrdinals = $to_int($to_bool($DisplayOptions.get('diagram_tile_winddir_ordinal', True)))
<script>
  /*prettier-ignore*/
  window.deckConfig = {
    diagramWindDirOrdinals: $diagramWindDirOrdinals,
    ordinalCompass: $get_ordinates,
    windRoseColors: $jsonize($DisplayOptions.get('windRose_colors', ["#f3cec9", "#e7a4b6", "#cd7eaf", "#a262a9", "#6f4d96", "#3d3b72"])),
    units: $unit.unit_type_dict,
    basePath: "$get_base_path()",
    /* Where the plot files are published. A separate export from the pages,
       so only the operator knows how the two sit on the host. */
    chartsPath: "$Extras.get('charts_path', '/json/')",
    /* How this skin draws a chart, for the tiles built in the browser.
       What a chart *holds* is in its file; this is the rest -- and the
       language above all, or a German page gets AM and PM in its tooltips. */
    chartSpec: {
      locale: "$get_locale()",
      format: "%.1f"
    },
    translations: {
      "Daily": "$gettext('Daily')",
      "Hourly": "$gettext('Hourly')",
      "Forecast_for": "$gettext('Forecast for')",
      "Forecast_from": "$gettext('Forecast from')",
      "Issued_on": "$gettext('Issued on')",
      "Station_name": "$gettext('Station name')",
      "POP": "$gettext('Probability of precipitation')",
      "obs_cloud_cover": "$gettext('Cloud cover')",
      "obs_sunshine_dur": "$gettext('Rel. Sunshine duration')",
      "obs_dew_point": "$obs.label['dewpoint']",
      "obs_barometer": "$obs.label['barometer']",
      "obs_wind_speed": "$gettext('Wind Speed')",
      "obs_precipitation": "$gettext('Precipitation')",
      "no_warnings": "$gettext('zur Zeit keine Warnungen')",
      "Verhaltenshinweise": "$gettext('Verhaltenshinweise')",
      "source": "$gettext('Source')",
      "Select_a_day": "$gettext('Select a day')",
      "Archive_day": "$gettext('Archive day')",
      "stats_helper_text": "$gettext('Choose a day to view a statistics page. You can also filter/search for a date by start typing, eg:')",
      "Format_is": "$gettext('Format is')",
    },
    locale: "$get_locale()",
    time: $datetime.datetime.now().timestamp(),
    defaultTheme: '$DisplayOptions.get("default_theme", "auto")',
    color_temperature: $to_int($to_bool($DisplayOptions.get("outTemp_stat_tile_color", "False"))),
    color_temperature_transparency: $DisplayOptions.get("outTemp_stat_tile_color_transparency", "0.35"),
    color_temperature_min: $DisplayOptions.get("outTemp_stat_tile_color_min", "-20"),
    color_temperature_max: $DisplayOptions.get("outTemp_stat_tile_color_max", "40"),
  };
</script>

## ECharts, then the page's own two files. `defer` on all three: they run
## in order, after the document is parsed, and none of them blocks the
## first paint. Local -- see vendor/echarts-LICENSE.txt.
<script src="$asset('vendor/echarts.min.js')" defer></script>
<script src="$asset('assets/charts.js')" defer></script>
<script src="$asset('assets/deck.js')" defer></script>

<script>
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register(
        "$get_base_path(path='service-worker.js')"
      );
    });
  }
</script>

## A skin may set its own chart heights. Kept because it is somebody's
## configuration, not ours to drop -- the default now comes from the
## stylesheet instead of from here.
<!--prettier-ignore-->
#if "heights" in $diagrams_config
<style>
  #if "alternative" in $diagrams_config.heights
    #if "height" in $diagrams_config.heights.alternative
      .chart { height: $diagrams_config.heights.alternative.height; }
    #end if
    #if "height_md" in $diagrams_config.heights.alternative
      @media (min-width: 42rem) {
        .chart { height: $diagrams_config.heights.alternative.height_md; }
      }
    #end if
    #if "height_lg" in $diagrams_config.heights.alternative
      @media (min-width: 66rem) {
        .chart { height: $diagrams_config.heights.alternative.height_lg; }
      }
    #end if
    #if "height_xlg" in $diagrams_config.heights.alternative
      @media (min-width: 82rem) {
        .chart { height: $diagrams_config.heights.alternative.height_xlg; }
      }
    #end if
    #if "height_max" in $diagrams_config.heights.alternative
      @media (min-width: 120rem) {
        .chart { height: $diagrams_config.heights.alternative.height_max; }
      }
    #end if
  #end if

  #if "classic" in $diagrams_config.heights
    #if "height" in $diagrams_config.heights.classic
      body.theme-classic .chart { height: $diagrams_config.heights.classic.height; }
    #end if
    #if "height_md" in $diagrams_config.heights.classic
      @media (min-width: 42rem) {
        body.theme-classic .chart { height: $diagrams_config.heights.classic.height_md; }
      }
    #end if
    #if "height_lg" in $diagrams_config.heights.classic
      @media (min-width: 66rem) {
        body.theme-classic .chart { height: $diagrams_config.heights.classic.height_lg; }
      }
    #end if
    #if "height_xlg" in $diagrams_config.heights.classic
      @media (min-width: 82rem) {
        body.theme-classic .chart { height: $diagrams_config.heights.classic.height_xlg; }
      }
    #end if
    #if "height_max" in $diagrams_config.heights.classic
      @media (min-width: 120rem) {
        body.theme-classic .chart { height: $diagrams_config.heights.classic.height_max; }
      }
    #end if
  #end if
</style>
#end if

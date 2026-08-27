#errorCatcher Echo
#encoding UTF-8
#from datetime import datetime, timedelta

#set $diagrams_config = $DisplayOptions.get("diagrams", {})
#set global $layout = 'alternative'
#set $gauges_display = $DisplayOptions.get('gauges_display', 'before')
#set $show_gauges = 'Gauges' in $DisplayOptions and $context in $DisplayOptions['Gauges']

#def render_gauges($gauge_config)
  #set $gauges_index = 0
  #for $gauge_obs in $gauge_config

    ## ValueError: start time (1654034700) is greater than stop time (1640991600)
    #set $alltime_tag = None if $use_parameter_year or $use_parameter_month else $alltime
    #set global $gauge_span = $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime_tag, $yesterday), $gauge_obs)

    #if $gauge_span.has_data
      #set global $gauges_index = $gauges_index
      #set global $partial_obs = $gauge_obs
      #include "includes/gauge-tile.inc"
      #set $gauges_index = $gauges_index + 1
    #end if
  #end for
#end def

#set $stat_tiles_xaggs_same_row = []
#set $stat_tiles_xaggs_extra_row = []
#if 'stat_tiles_xaggs' in $DisplayOptions
  #set $stat_tiles_xaggs = $DisplayOptions.stat_tiles_xaggs

  #for $xaggs in $stat_tiles_xaggs
    #if $context != "day" and ('avg_context' not in $stat_tiles_xaggs[$xaggs] or $context not in $stat_tiles_xaggs[$xaggs]['avg_context'])
      #continue
    #end if

    #set $xaggs_to_append = {'obs': $xaggs, **$stat_tiles_xaggs[$xaggs]}

    #if $context == "day"
      #silent $xaggs_to_append['aggregate_types'] = $list(filter(lambda aggregate_type: 'historical' in aggregate_type, $xaggs_to_append['aggregate_types']))
    #else
      #silent $xaggs_to_append['aggregate_types'] = $list(filter(lambda aggregate_type: 'historical' not in aggregate_type, $xaggs_to_append['aggregate_types']))
    #end if

    #if $to_bool($stat_tiles_xaggs[$xaggs]['show_extra_row']) is True
      #silent $stat_tiles_xaggs_extra_row.append($xaggs_to_append)
    #else
      #silent $stat_tiles_xaggs_same_row.append($xaggs_to_append)
    #end if
  #end for
#end if

#if os.path.exists("custom-content-top.inc") and $context == 'day' and not $daily_archive
  <div class="custom-content top">
      #include "custom-content-top.inc"
  </div>
#end if

#if $show_gauges and $gauges_display == 'before'
  <div class="grid">
    $render_gauges($DisplayOptions['Gauges'][$context])
  </div>
#end if

<div class="grid grid--tiles">
  #for $skin_obs in $DisplayOptions.get('stat_tile_observations')
    #if $skin_obs != 'windDir' and $skin_obs != 'windGustDir' and $skin_obs != 'rainRate'

      #set $show_sum = $get_show_sum($skin_obs)
      #set $show_min = $get_show_min($skin_obs)
      #set $show_max = $get_show_max($skin_obs)
      #set $use_day = $show_sum or $show_min or $show_max

      ## ValueError: start time (1654034700) is greater than stop time (1640991600)
      #set $alltime_tag = $alltime if $context == 'alltime' else None

      #if $context == 'day' and not $daily_archive and $use_day
        #set $stat_tile_check = $day
      #elif $context == 'day' and not $daily_archive and not $use_day
        #set $stat_tile_check = $current
      #else
        #set $stat_tile_check = $get_time_span_from_context($context, $day, $week, $month, $year, $alltime_tag, $yesterday)
      #end if

      #if $getattr($stat_tile_check, $skin_obs).has_data
        #set global $partial_obs = $skin_obs
        #include "includes/stat-tile.inc"
      #end if
    #end if
  #end for

  #if $stat_tiles_xaggs_same_row
    #set global $hide_xaggs_heading = False
    #for $stat_xaggs in $stat_tiles_xaggs_same_row
      #set global $stat_xaggs = $stat_xaggs
      #include "includes/stat-tile-xaggs.inc"
    #end for
  #end if
</div>

#if $show_gauges and $gauges_display == 'after'
  <div class="grid">
    $render_gauges($DisplayOptions['Gauges'][$context])
  </div>
#end if

#if $stat_tiles_xaggs_extra_row
#set global $hide_xaggs_heading = True
<header class="section-head">
  #if $context == 'day'
  <h2>$gettext("Historical values for today")</h2>
  #else
  <h2>$gettext("Historical values")</h2>
  #end if
</header>
<div class="grid grid--tiles">
  #for $stat_xaggs in $stat_tiles_xaggs_extra_row
    #set global $stat_xaggs = $stat_xaggs
    #include "includes/stat-tile-xaggs.inc"
  #end for
</div>
#end if

#if os.path.exists("custom-content-after-stat.inc") and $context == 'day' and not $daily_archive
  <div class="custom-content after-stat">
      #include "custom-content-after-stat.inc"
  </div>
#end if

#if $context == "day" and $daily_archive == False
#include "includes/forecast.inc"
#include "includes/externals.inc"
#end if

#include "includes/section-heading.inc"

#set $diagram_index = 0
#set $context_for_diagrams = $context if $context != 'yesterday' else 'day'
#set $diagram_context_config = $DisplayOptions.get("diagrams", {}).get($context_for_diagrams, {}).get('observations', {})
#if "combined_observations" in $diagrams_config
  #set $combined = $diagrams_config.combined_observations
#else
  #set $combined = {}
#end if

## Charts by name, out of `plots.toml`.
##
## The grid is left empty and filled by `assets/charts.js` from the manifest
## the `json` feed writes. The template cannot fill it: it does not know
## which plots exist, because `plots.toml` belongs to the installation and
## the charts are a separate export from these pages -- possibly to a
## different host. So the page says which span it wants and stops.
##
## What this replaces queried the database once per observation while the
## page was being written, so a chart was as old as the last render, and the
## skin held its own opinion about what a chart contains while `plots.toml`
## and the plot editor in the settings held another that nothing read.
##
## `diagram_source = observations` puts the old way back, one context at a
## time, for a station whose charts are not in `plots.toml` at all.
#set $diagram_source = $DisplayOptions.get("diagrams", {}).get($context_for_diagrams, {}).get('source', $Extras.get('diagram_source', 'plots'))
#if $diagram_source == 'plots'
  ## Named plots, in the order they are named. Empty means every plot the
  ## manifest has for this span, which is the right default: a station that
  ## adds one in the settings sees it without editing a skin.
  #set $only_plots = $DisplayOptions.get("diagrams", {}).get($context_for_diagrams, {}).get('plots', [])
  ## One name in the settings comes back as a string, not a list of one.
  #if isinstance($only_plots, str)
    #set $only_plots = [$only_plots]
  #end if
  #set $only_text = ", ".join($only_plots)
  ## The attributes sit on the grid itself, so the cards `charts.js` builds
  ## are its own children. Nested one deeper, the grid had a single item and
  ## laid out one chart per row -- four abreast became one, on a screen with
  ## room for three.
  <div class="grid grid--wide" data-plots="$context_for_diagrams"
       data-only="$only_text"></div>
#else
<div class="grid grid--wide">
#for $skin_obs in $diagram_context_config
  #if $skin_obs in $combined.keys()
    #set $combined_diagram = $combined[$skin_obs]
    #for $combined_obs in $combined_diagram.obs.keys()

      ## ValueError: start time (1654034700) is greater than stop time (1640991600)
      #set $alltime_tag = $alltime if $context == 'alltime' else None

      #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime_tag, $yesterday), $combined_diagram.obs[$combined_obs].observation).has_data or $combined_diagram.obs[$combined_obs].observation in $get_software_obs
        #set global $comb_obs = $skin_obs
        #set global $combined_diagram = $combined_diagram
        #set global $diagram_index = $diagram_index
        #include "includes/combined-diagram-tile.inc"
        #set $diagram_index = $diagram_index + 1
        #break
      #end if
    #end for
  #else
    #set $alltime_tag = $alltime if $context == 'alltime' else None
    #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime_tag, $yesterday), $skin_obs).has_data or (($skin_obs == 'windDir' or $skin_obs == 'windRose') and $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday), 'windSpeed').has_data or $skin_obs in $get_software_obs)
      #set global $partial_obs = $skin_obs
      #set global $diagram_index = $diagram_index
      #if $skin_obs == 'windRose'
        #include "includes/diagram-tile-wind-rose.inc"
      #else
        #include "includes/diagram-tile.inc"
      #end if
      #set $diagram_index = $diagram_index + 1
    #end if
  #end if
#end for
#end if
</div>

#if os.path.exists("custom-content-bottom.inc") and $context == 'day' and not $daily_archive
  <div class="custom-content bottom">
      #include "custom-content-bottom.inc"
  </div>
#end if

#if 'table_tile_observations' in $DisplayOptions
<div class="stack">
  #set global $table_obs = None
  #include "includes/data-table-tile.inc"
</div>
#end if

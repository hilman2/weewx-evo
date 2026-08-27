<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
#set $diagrams_config = $DisplayOptions.get("diagrams", {})
#set global $layout = 'classic'
#set $gauges_display = $DisplayOptions.get('gauges_display', 'before')
#set $show_gauges = 'Gauges' in $DisplayOptions and $context in $DisplayOptions['Gauges']

#def render_gauges($gauge_config)
  #set $gauges_index = 0
  #for $gauge_obs in $gauge_config

    ## ValueError: start time (1654034700) is greater than stop time (1640991600)
    #set $alltime_tag = None if $use_parameter_year or $use_parameter_month else $alltime

    #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime_tag, $yesterday), $gauge_obs).has_data
      #set global $gauges_index = $gauges_index
      #set global $partial_obs = $gauge_obs
      #include "includes/gauge-tile.inc"
      #set $gauges_index = $gauges_index + 1
    #end if
  #end for
#end def

#set $stat_tiles_xaggs_classic = []
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

    #silent $stat_tiles_xaggs_classic.append($xaggs_to_append)
  #end for
#end if

<!--prettier-ignore-->
<div>
  <div class="layout-col">
    #set global $stat_obs = $DisplayOptions.get('stat_tile_observations')
    #include 'includes/conditions-table.inc'

    <!--prettier-ignore-->
    #if $context == "day" and $daily_archive == False
    #include "includes/forecast.inc"
#include "includes/externals.inc"
    #end if

    <!--prettier-ignore-->
    #if $stat_tiles_xaggs_classic
    #set global $hide_xaggs_heading = True
    <!--prettier-ignore-->
    <header class="section-header" style="margin-top: 2rem;">
      #if $context == 'day'
      <h2>$gettext("Historical values for today")</h2>
      #else
      <h2>$gettext("Historical values")</h2>
      #end if
    </header>
    <!--prettier-ignore-->
    <div>
      #for $stat_xaggs in $stat_tiles_xaggs_classic
        #set global $stat_xaggs = $stat_xaggs
        #include "includes/stat-tile-xaggs.inc"
      #end for
    </div>
    #end if

    #if os.path.exists("custom-content-left.inc") and $context == 'day' and not $daily_archive
      <div class="custom-content left">
          #include "custom-content-left.inc"
      </div>
    #end if
  </div>


  <div class="layout-col">

    #if os.path.exists("custom-content-top.inc") and $context == 'day' and not $daily_archive
      <div class="custom-content top">
          #include "custom-content-top.inc"
      </div>
    #end if

    <!--prettier-ignore-->
    #if $show_gauges
    <!--prettier-ignore-->
    <div>
    $render_gauges($DisplayOptions['Gauges'][$context])
    </div>
    #end if

    <div>
    <!-- prettier-ignore -->
    #set $diagram_index = 0
    #set $context_for_diagrams = $context if $context != 'yesterday' else 'day'
    #set $diagram_context_config = $DisplayOptions.get("diagrams", {}).get($context_for_diagrams, {}).get('observations', {})
    #if "combined_observations" in $diagrams_config
      #set $combined = $diagrams_config.combined_observations
    #else
      #set $combined = {}
    #end if

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
        #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime_tag, $yesterday), $skin_obs).has_data or (($skin_obs == 'windDir' or $skin_obs == 'windRose') and $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday), 'windSpeed').has_data) or $skin_obs in $get_software_obs
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
    </div>

    #if os.path.exists("custom-content-bottom.inc") and $context == 'day' and not $daily_archive
      <div class="custom-content bottom">
          #include "custom-content-bottom.inc"
      </div>
    #end if
  </div>
</div>

#if 'table_tile_observations' in $DisplayOptions
<div>
  <!-- prettier-ignore -->
  #set global $table_obs = None
  #include "includes/data-table-tile.inc"
</div>
#end if

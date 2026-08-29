<!--prettier-ignore-->
#errorCatcher Echo
#import datetime
#import time

<!--prettier-ignore-->
#encoding UTF-8
## Input vars:
##   $combined_diagram - The diagrams config
##   $comb_obs - The skin observation (e.g. tempdew or temp_min_max_avg)
##   $context - The current context

#set $diagram_classes = "    "
#if $DisplayOptions.get('layout', 'alternative') == 'classic'
  #set $diagram_classes = "    "
#end if

#if $varExists('diagram_classes_custom')
  #set $diagram_classes = $diagram_classes_custom
#end if

#if $comb_obs == "climatogram_year" or $comb_obs == "climatogram_statistics"
  #set $diagram_classes = ""
#end if

<!--prettier-ignore-->
#set $combined_diagram_obs = {}
#for $combined_obs in $combined_diagram.obs.keys()
#silent $combined_diagram_obs.update({ $combined_obs: $combined_diagram.obs[$combined_obs].observation })
#end for

#set combined_obs_string = '-'.join($combined_diagram_obs.values())

#set $obs_icons = []
#for $combined_obs in $combined_diagram_obs.values()
  #set $obs_icon = $get_icon($combined_obs)
  #if $obs_icon is not None and $obs_icon not in $obs_icons and $obs_icon != 'none'
    #silent $obs_icons.append($obs_icon)
  #end if
#end for


<div class="$diagram_classes">
  <div class="card diagram-tile combined" data-test="$combined_obs_string">
    <div>
      <div>
        <!--prettier-ignore-->
        <p class="label">
          #set $icon = $get_icon($comb_obs, $use_combined_diagram_config=True, $context=$context)

          #if $icon != 'unset'
            #if $icon is not None and $icon != 'none'
              #if "includes/icons/" in $icon and '.svg' in $icon
                #include $icon
              #elif "includes/icons/" not in $icon
                <img src="$icon" alt="$obs.label[$partial_obs]" />
              #end if
            #else
              #for $icon in $obs_icons
                <span>
                  #include $icon
                </span>
              #end for
            #end if
          #end if

          $gettext($combined_diagram.label)
        </p>
        <!--prettier-ignore-->
        <div class="value">
          #set $chart_series = []
          #set $combined_index = 0

          #for $combined_obs in $combined_diagram_obs.keys()
            #set $series_observation = $combined_diagram_obs[$combined_obs]
            #set $series_name = $series_observation + 'Series' + str($diagram_index) + str($combined_index)
            #set $series_observation_key = $series_observation
            #silent $chart_series.append({
              "data": $series_name,
              "label": $obs.label[$series_observation] + " " + $gettext($get_aggregate_type($combined_obs, $context, combined=$combined_diagram.obs[$combined_obs]).capitalize()),
              "color": $get_color($comb_obs, $context, combined=True, combined_obs_key=$combined_obs, combined_obs=$series_observation),
              "unit": $get_unit_label($get_unit_for_obs($combined_obs, $series_observation_key, $context, combined=$combined_diagram, combined_key=$comb_obs)),
              "type": $get_diagram($series_observation_key, $context, combined_key=$comb_obs, combined_obs=$combined_obs),
            })

          #if $context == 'month' and $use_parameter_month
            #set $obs_context = $month
            #set $start_ts=$obs_context.start.raw
            #set $end_ts=$obs_context.end.raw
            #set $context_key = $context
          #else if $context == 'year' and $use_parameter_year
            #set $obs_context = $year
            #set $start_ts=$obs_context.start.raw
            #set $end_ts=$obs_context.end.raw
            #set $context_key = $context
          #else if $context == 'alltime'
            #set $obs_context = $alltime
            #set $start_ts=$obs_context.start.raw
            #set $end_ts=$obs_context.end.raw
            #set $context_key = $context
          #else if $context == 'yesterday'
            #set $obs_context = $yesterday
            #set $start_ts=$obs_context.start.raw
            #set $end_ts=$obs_context.end.raw
            #set $context_key = $context
          #else if $context == 'custom'
            #set $start_ts = $context_start_ts
            #set $end_ts = $context_end_ts
            #set $context_key = $get_context_key_from_time_span($start_ts, $end_ts)
          #else
            #set $obs_context = $span($hour_delta=$get_hour_delta($context), $boundary=$get_diagram_boundary($context))
            #set $start_ts=$obs_context.start.raw
            #set $end_ts=$obs_context.end.raw
            #set $context_key = $context
          #end if

          <script>
            /* prettier-ignore */
            var $series_name = $get_diagram_data($observation=$combined_obs, $observation_key=$series_observation_key, $context_key=$context_key, $start_ts=$start_ts, $end_ts=$end_ts, $alltime_start=$alltime.start.format('%d.%m.%Y'), alltime_end=$alltime.end.format('%d.%m.%Y'), combined=$combined_diagram, combined_key=$comb_obs);
          </script>

          <!--prettier-ignore-->
          #set $combined_index = $combined_index + 1
          #end for

          <div class="diagram combined" data-test="$comb_obs" data-chart='$get_chart($comb_obs, "", $context_key, $series=$chart_series, $combined_key=$comb_obs, $kind="line")'></div>
        </div>
      </div>
    </div>
  </div>
</div>

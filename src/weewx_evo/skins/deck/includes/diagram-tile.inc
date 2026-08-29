<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
#set diagram_classes = "    "
#if $DisplayOptions.get('layout', 'alternative') == 'classic'
  #set diagram_classes = "    "
#end if
#set $partial_obs_key = $partial_obs


<div class="$diagram_classes">
  <div class="card diagram-tile" data-test="$partial_obs">
    <div>
      <div>
        <!--prettier-ignore-->
        <p class="label">
          #set $icon = $get_icon($partial_obs_key, $use_diagram_config=True, $context=$context)
          #if $icon != 'none' and "includes/icons/" in $icon and '.svg' in $icon
            #include $icon
          #elif $icon != 'none' and "includes/icons/" not in $icon
            <img src="$icon" alt="$obs.label[$partial_obs]" />
          #end if
          $obs.label[$partial_obs]
        </p>
        <div class="value">
          <!--prettier-ignore-->
          #set $series_name = $partial_obs + 'Series' + str($diagram_index)

          <!--TODO: Implement custom context logic from combined-diagram-tile template-->
          <!--prettier-ignore-->
          #if $context == 'month' and $use_parameter_month
            #set $obs_context = $month
          #else if $context == 'year' and $use_parameter_year
            #set $obs_context = $year
          #else if $context == 'alltime'
            #set $obs_context = $alltime
          #else if $context == 'yesterday'
            #set $obs_context = $yesterday
          #else
            #set $obs_context = $span($hour_delta=$get_hour_delta($context), $boundary=$get_diagram_boundary($context))
          #end if

          <script>
            /* prettier-ignore */
            var $series_name = $get_diagram_data($observation=$partial_obs, $observation_key=$partial_obs_key, $context_key=$context, $start_ts=$obs_context.start.raw, $end_ts=$obs_context.end.raw, $alltime_start=$alltime.start.format('%d.%m.%Y'), alltime_end=$alltime.end.format('%d.%m.%Y'));
          </script>

          <!--prettier-ignore-->
          <div class="diagram" data-test="$partial_obs" data-chart='$get_chart($partial_obs, $series_name, $context, $observation_key=$partial_obs_key, $label=$obs.label[$partial_obs], $color=$get_color($partial_obs, $context), $unit=$get_unit_label($get_unit_for_obs($partial_obs, $partial_obs_key, $context)))'></div>
        </div>
      </div>
    </div>
  </div>
</div>

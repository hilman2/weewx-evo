#errorCatcher Echo
#encoding UTF-8
#set diagram_classes = "    "
#if $DisplayOptions.get('layout', 'alternative') == 'classic'
  #set diagram_classes = "    "
#end if

<div class="$diagram_classes">
  <div class="card diagram-tile" data-test="windrose">
    <div>
      <div>
        <p class="label">
          #set $icon = $get_icon("windDir", $use_diagram_config=True, $context=$context)
          #if $icon != 'none' and "includes/icons/" in $icon and '.svg' in $icon
            #include $icon
          #elif $icon != 'none' and "includes/icons/" not in $icon
            <img src="$icon" alt="$obs.label['windDir']" />
          #end if
          $obs.label["windDir"]
        </p>
        <div class="value">
          #set $series_name = $partial_obs + 'Series' + str($diagram_index)

          <!--prettier-ignore-->
          #if $context == 'month' and $use_parameter_month
            #set $rose_span = $month
          #else if $context == 'year' and $use_parameter_year
            #set $rose_span = $year
          #else
            #set $rose_span = $get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday)
          #end if

          <div class="diagram windrose" data-test="windrose" data-chart='$get_windrose_chart($rose_span.start.raw, $rose_span.end.raw, $context)'></div>
        </div>
      </div>
    </div>
  </div>
</div>

<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8

#set $layout = $DisplayOptions.get('layout', 'alternative')
#set $gauges_size = $DisplayOptions.get('gauges_size', "small")

#set $gauges_display = $DisplayOptions.get('gauges_display', 'before')
#set $diagram_classes = "    "
#if $layout == 'classic'
  #set $diagram_classes = "    "
#end if

#if $gauges_size == "medium" and $layout == 'alternative'
  #set $diagram_classes = "    "
#end if
#if $gauges_size == "large" and $layout == 'alternative'
  #set $diagram_classes = "    "
#end if
#if $gauges_size == "medium" and $layout == 'classic'
  #set $diagram_classes = "    "
#end if
#if $gauges_size == "large" and $layout == 'classic'
  #set $diagram_classes = "    "
#end if

#set $partial_obs_key = $partial_obs
#set $series_name = $partial_obs + 'GaugeSeries' + str($gauges_index)


<div class="$diagram_classes">
  <div
    class="card diagram-tile gauge"
    data-test="$series_name"
    data-observation="$partial_obs_key"
  >
    <div>
      <div>
        <!--prettier-ignore-->
        <div class="value">
          <!--prettier-ignore-->
          <script>
            // TODO: Implement custom context logic from combined-diagram-tile template
            var $series_name = {
                #if $context == 'day' and not $daily_archive
                  current: "$getattr($current, $partial_obs_key).nolabel('%.2f').replace(',','.')",
                #else
                  current: "$getattr($gauge_span, 'avg').nolabel('%.2f').replace(',','.')",
                #end if

                min: "$getattr($gauge_span, 'min').nolabel('%.2f').replace(',','.')",
                max: "$getattr($gauge_span, 'max').nolabel('%.2f').replace(',','.')",
                obs: '$partial_obs',
                unit: "$get_unit_label($get_unit_for_obs($partial_obs, $partial_obs_key, $context))",
                rounding: $get_rounding($partial_obs, $partial_obs_key),
                properties: $get_gauge_diagram_props($partial_obs, $context),
                label: "$obs.label[$partial_obs]",
                dayChange: false,
            }
          </script>
          <div class="diagram" data-value="$series_name"></div>
        </div>
      </div>
    </div>
  </div>
</div>

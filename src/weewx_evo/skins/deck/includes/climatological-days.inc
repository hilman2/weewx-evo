#errorCatcher Echo
#encoding UTF-8
#from datetime import datetime
#set $show_climatogram_year = $context == 'year' and $DisplayOptions.get("climatogram_enable_year_stats", False)
#set $show_climatogram_alltime = $context == 'alltime' and $DisplayOptions.get("climatogram_enable_stats", False)

#if $context == 'year'
  #set $year_rain_table = $year.dateTime.format('%Y')
  #set $most_days_with_rain = None if $most_days_with_rain is None or $year_rain_table not in $most_days_with_rain else $most_days_with_rain[$year_rain_table]
  #set $most_days_without_rain = None if $most_days_without_rain is None or $year_rain_table not in $most_days_without_rain else $most_days_without_rain[$year_rain_table]
#end if

#set $show_rain_stats_table = ($context == 'alltime' and $to_bool($DisplayOptions.get('show_last_rain', True))) or (($most_days_with_rain is not None and $to_bool($DisplayOptions.get('show_most_days_with_rain', 'True'))) or ($most_days_without_rain is not None and $to_bool($DisplayOptions.get('show_most_days_without_rain', 'True'))) or $to_bool($DisplayOptions.get('show_most_rain_within_one_day', 'True')))
#set $show_climatological_days_per_month = $to_bool($DisplayOptions.get('climatological_days_per_month', True))

<div class="tabs" role="tablist" value="table">
  <button type="button" role="tab" id="tab-table" aria-controls="panel-table" value="table">$gettext('Table')</button>
  #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday), 'rain').has_data
  <button type="button" role="tab"
    id="tab-diagram-rain"
    aria-controls="panel-diagram-rain"
    value="diagram-rain"
  >$obs.label.rain</button>
  #end if
  #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday), 'outTemp').has_data
  <button type="button" role="tab"
    id="tab-diagram-temp-avg"
    aria-controls="panel-diagram-temp-avg"
    value="diagram-temp-avg"
  >
    $gettext('Avg') $obs.label.outTemp
  </button>
  #end if
  #if $show_climatogram_year or $show_climatogram_alltime
  <button type="button" role="tab" id="tab-climatogram" aria-controls="panel-climatogram" value="climatogram"
    >$gettext('Climatogram')</button>
  #end if

  #if 'stat_tables' in $DisplayOptions
    #for $stat_table in $DisplayOptions.get('stat_tables')
      #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday), $DisplayOptions['stat_tables'][$stat_table]['observation']).has_data
        <button type="button" role="tab"
          id="tab-$stat_table"
          aria-controls="panel-$stat_table"
          value="$stat_table"
        >
          $gettext($DisplayOptions['stat_tables'][$stat_table]['label'])
        </button>
      #end if
    #end for
  #end if
</div>

<div class="bx-ce-demo-devenv--tab-panels">
  <div
    class="climatological-tile"
    id="panel-table"
    role="tabpanel"
    aria-labelledby="tab-table"
    hidden
  >
    <div class="table-scroll">
    <table data-sortable>
      <thead>
        <tr>
          <th
            >$gettext("Climatological day")</th>
          <th
            >$gettext("Number of days")</th>
          <th>
            <span class="hide-mobile">$gettext("Description")</span>
          </th>
        </tr>
      </thead>
      <tbody>
        #for $clim_day in $DisplayOptions.get('climatological_days')
        <tr data-test="$clim_day">
          <td>$gettext($clim_day)</td>
          <td>
            #set $time_span = $get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday)
            $get_climatological_day($clim_day, $time_span.start.raw, $time_span.end.raw)
          </td>
          <td>
            $get_climatological_day_description($clim_day)
          </td>
        </tr>
        #end for

        #if $context == 'alltime'
        ## Not a total of the rows above it -- the counts overlap, a
        ## desert day being a hot day and a summer day as well. This is
        ## the denominator: four rain days out of how many.
        <tr data-test="total-number" class="summary">
          <td
            ><strong
              >$gettext("Days in period")</strong
            ></td>
          <td>
            #set $start_dt = datetime.fromtimestamp($alltime.start.raw)
            #set $end_dt = datetime.fromtimestamp($latest.dateTime.raw)
            #set $delta = $end_dt - $start_dt
            $delta.days
          </td>
          <td></td>
        </tr>
        #end if
      </tbody>
    </table>
    </div>

    #if $show_climatological_days_per_month
      #include "includes/year-stats-table.inc"
    #end if
  </div>
  #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday), 'rain').has_data
  <div
    id="panel-diagram-rain"
    role="tabpanel"
    aria-labelledby="tab-diagram-rain"
    hidden
  >
    #if $show_rain_stats_table
    <section class="card factlist">
      <h3 class="factlist__title">$gettext('Rain Statistics')</h3>
      <dl>
        #if $context == 'alltime' and $to_bool($DisplayOptions.get('show_last_rain', True)) and $last_rain is not None
        <dt
            >$gettext("Last rain")</dt>
          <dd data-testid="last-rain">
            $last_rain.format("%x, %X") ($gettext("Time since last rain"): $time_since_last_rain.long_form)
          </dd>
        #end if
        #if $most_days_with_rain is not None and $to_bool($DisplayOptions.get('show_most_days_with_rain', True))
        <dt>
            $gettext("Most consecutive days with rain")
          </dt>
          <dd data-testid="most-days-with-rain">
            $most_days_with_rain.start.format('%x') -
            $most_days_with_rain.end.format('%x')
            ($most_days_with_rain.days_with_rain_delta.day.format("%.0f"),
            $gettext("Total"): $most_days_with_rain.amount)
          </dd>
        #end if
        #if $most_days_without_rain is not None and $to_bool($DisplayOptions.get('show_most_days_without_rain', True))
        <dt>
            $gettext("Most consecutive days without rain")
          </dt>
          <dd data-testid="most-days-without-rain">
            $most_days_without_rain.start.format('%x') -
            $most_days_without_rain.end.format('%x')
            ($most_days_without_rain.days_without_rain_delta.day.format("%.0f"))
          </dd>
        #end if
        #if $to_bool($DisplayOptions.get('show_most_rain_within_one_day', 'True'))
        <dt>
            $gettext("Most rain within one day")
          </dt>
          <dd data-testid="most-rain-day">
            #if $context == 'alltime'
              $alltime.rain.maxsum ($alltime.rain.maxsumtime)
            #end if
            #if $context == 'year'
              $year.rain.maxsum ($year.rain.maxsumtime)
            #end if
          </dd>
        #end if
      </dl>
    </section>
    #end if

    <!--prettier-ignore-->
    #set $obs_context = $get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday)
    <div class="card chart-card">
      <div class="card__head"><h3>$gettext('rainDays')</h3></div>
      <div class="diagram calendar" data-chart='$get_calendar_chart("rain", "sum", $obs_context.start.raw, $obs_context.end.raw, $gettext("rainDays"))'></div>
    </div>
  </div>
  #end if
  #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday), 'outTemp').has_data
  <div
    id="panel-diagram-temp-avg"
    role="tabpanel"
    aria-labelledby="tab-diagram-temp-avg"
    hidden
  >
    <!--prettier-ignore-->
    #set $obs_context = $get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday)
    <div class="card chart-card">
      <div class="card__head"><h3>$gettext('Avg') $obs.label.outTemp</h3></div>
      <div class="diagram calendar" data-chart='$get_calendar_chart("outTemp", "avg", $obs_context.start.raw, $obs_context.end.raw, $gettext("Avg"))'></div>
    </div>
  </div>
  #end if

  #if $show_climatogram_year or $show_climatogram_alltime
  <div
    id="panel-climatogram"
    role="tabpanel"
    aria-labelledby="tab-climatogram"
    hidden
  >
    #if $show_climatogram_year
      <div class="year">
        #set global $comb_obs = "climatogram_year"
        #set global $combined_diagram = $DisplayOptions.get("diagrams", {}).get("combined_observations", {}).get('climatogram_year', {})
        #set global $diagram_index = 9999
        #include "includes/combined-diagram-tile.inc"
      </div>
    #else if $show_climatogram_alltime
      <div class="alltime">
        #set global $comb_obs = "climatogram_statistics"
        #set global $combined_diagram = $DisplayOptions.get("diagrams", {}).get("combined_observations", {}).get('climatogram_statistics', {})
        #set global $diagram_index = 9999
        #include "includes/combined-diagram-tile.inc"
      </div>
    #end if
  </div>
  #end if

  #if 'stat_tables' in $DisplayOptions
    #for $stat_table in $DisplayOptions.get('stat_tables')
      #if $getattr($get_time_span_from_context($context, $day, $week, $month, $year, $alltime, $yesterday), $DisplayOptions['stat_tables'][$stat_table]['observation']).has_data
        <div
          id="panel-$stat_table"
          role="tabpanel"
          aria-labelledby="tab-$stat_table"
          class="climatological-day-table"
          hidden
        >
          #set global $stat_table_obs = $DisplayOptions['stat_tables'][$stat_table]['observation']
          #set global $stat_table_aggregate_types = $to_list($DisplayOptions['stat_tables'][$stat_table]['aggregate_types'])

          #include "includes/stat-table.inc"
        </div>
      #end if
    #end for
  #end if
</div>

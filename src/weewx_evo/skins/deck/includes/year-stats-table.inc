#errorCatcher Echo
#encoding UTF-8

#import calendar
#import datetime
#from weewx_evo.skinkit import startOfDay, startOfArchiveDay

#set $first_option = $DisplayOptions.get('climatological_days', [])[0].replace(' ', '_').lower()

<div class="tabs" role="tablist" value="$first_option">
  #for $clim_day in $DisplayOptions.get('climatological_days')
  #set $clim_day_class = $clim_day.replace(' ', '_').lower()
  <button type="button" role="tab"
    id="tab-$gettext($clim_day_class)"
    aria-controls="panel-$gettext($clim_day_class)"
    value="$gettext($clim_day_class)"
    >$gettext($clim_day)</button>
  #end for
</div>

<div class="bx-ce-demo-devenv--tab-panels">
  #for $clim_day in $DisplayOptions.get('climatological_days')
  #set $clim_day_class = $clim_day.replace(' ', '_').lower()
  <div
    class="climatological-day-table"
    id="panel-$clim_day_class"
    role="tabpanel"
    aria-labelledby="tab-$clim_day_class"
    hidden
  >
    #if $context == 'alltime'
      #set $archive_months = $SummaryByMonth
      #if len($SummaryByYear) == 0
        #set $SummaryByYear = $fake_get_report_years($alltime.start.format("%Y"), $latest.dateTime.format("%Y"))
      #end if
    #elif $context == 'year'
      #set $SummaryByYear = [str($year_name)]
      #set $archive_months = $filter_months($SummaryByMonth, $year_name)
    #end if

    #set $totals_per_month = {}
    #set $totals_per_year = {}

    <div class="table-scroll">
    <table data-sortable>
      <thead>
        <tr>
          #if $context == "alltime"
          <th>
            $gettext('Year')
          </th>
          #end if

          #for $month in range(1, 13)
            <th>
              $month_word($month)
            </th>
          #end for

          <th>
            $gettext('Total')
          </th>
        </tr>
      </thead>
      <tbody>
        #for $year in $SummaryByYear
        <tr>
          #if $context == "alltime"
          <td>$year</td>
          #end if

          #set $months_for_year = $filter_months($archive_months, $year)

          #for $month in range(1, 13)
            #if not $month in $totals_per_month
              #set $totals_per_month[$month] = []
            #end if
            #set $month_from_range = $year + '-' + str($month).zfill(2)

            #if $month_from_range in $months_for_year
              <td data-testid="$month_from_range">
                #set $time_span_start_ts = $startOfDay($datetime.datetime.strptime($month_from_range, "%Y-%m").replace(day=1).timestamp())
                #set $time_span_end_ts = $datetime.datetime.strptime($month_from_range, "%Y-%m").replace(day=$calendar.monthrange(int($year), int($month))[1], hour=23, minute=59).timestamp()

                #set $number_of_days = $get_climatological_day($clim_day, $time_span_start_ts, $time_span_end_ts)
                #set $totals_per_year[$year] = $number_of_days + $totals_per_year[$year] if $year in $totals_per_year else $number_of_days
                #silent $totals_per_month[$month].append($number_of_days)

                $number_of_days
              </td>
            #else
              <td>-</td>
            #end if
          #end for

          <td data-testid="year-$year">
            #if $year in $totals_per_year
              <strong>$totals_per_year[$year]</strong>
            #else
              <strong>-</strong>
            #end if
          </td>
        </tr>
        #end for
        #if $context == 'alltime'
          <tr data-test="total">
            <td>
              <strong>$gettext("Total")</strong>
            </td>
            #for $month in range(1, 13)
              #if $month in $totals_per_month
                <td data-testid="month-$month">
                  <strong>$sum($totals_per_month[$month])</strong>
                </td>
              #else
                <td>-</td>
              #end if
            #end for
            <td>
              <strong>
                $get_climatological_day($clim_day, $alltime.start.raw, $alltime.end.raw)
              </strong>
            </td>
          </tr>
          <tr data-test="average">
            <td>
              <strong>$gettext("Average")</strong>
            </td>
            #for $month in range(1, 13)
              #if $month in $totals_per_month and $len($totals_per_month[$month]) > 0
                <td data-testid="month-$month">
                  <strong>$round($sum($totals_per_month[$month]) / $len($totals_per_month[$month]), 1)</strong>
                </td>
              #else
                <td>-</td>
              #end if
            #end for

            #if $len($SummaryByYear) > 0
            <td>
              <strong>
                $round($get_climatological_day($clim_day, $alltime.start.raw, $alltime.end.raw) / $len($SummaryByYear), 1)
              </strong>
            </td>
            #else
            <td>-</td>
            #end if
          </tr>
        #end if
      </tbody>
    </table>
    </div>
  </div>
  #end for
</div>

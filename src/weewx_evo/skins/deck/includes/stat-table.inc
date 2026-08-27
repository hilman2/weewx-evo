#errorCatcher Echo
#encoding UTF-8

#import calendar
#import datetime
#from weewx_evo.skinkit import startOfDay, startOfArchiveDay

#if $context == 'alltime'
  #set $archive_months = $SummaryByMonth
  #if len($SummaryByYear) == 0
    #set $SummaryByYear = $fake_get_report_years($alltime.start.format("%Y"), $latest.dateTime.format("%Y"))
  #end if
#elif $context == 'year'
  #set $SummaryByYear = [str($year_name)]
  #set $archive_months = $filter_months($SummaryByMonth, $year_name)
#end if

#for $agg in $stat_table_aggregate_types
  <h3>
    $gettext($agg.capitalize()) $obs.label[$stat_table_obs]
  </h3>

  #set $per_month = {}
  #set $per_year = {}
  #set $per_all = []

  <div class="table-scroll">
  <table data-sortable class="year-obs-stat-table" data-testid="$agg-$stat_table_obs">
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
          $gettext($agg.capitalize())
        </th>
      </tr>
    </thead>
    <tbody>
      #for $year in $SummaryByYear
        #if not $year in $per_year
          #set $per_year[$year] = []
        #end if
        <tr>
          #if $context == "alltime"
            <td>$year</td>
          #end if

          #set $months_for_year = $filter_months($archive_months, $year)

          #for $month in range(1, 13)
            #if not $month in $per_month
              #set $per_month[$month] = []
            #end if

            #set $month_from_range = $year + '-' + str($month).zfill(2)
            #set $time_span_start_ts = $startOfDay($datetime.datetime.strptime($month_from_range, "%Y-%m").replace(day=1).timestamp())
            #set $time_span_end_ts = $datetime.datetime.strptime($month_from_range, "%Y-%m").replace(day=$calendar.monthrange(int($year), int($month))[1], hour=23, minute=59).timestamp()

            #if $month_from_range in $months_for_year
              #set $agg_for_value = $agg

              #if $stat_table_obs in $DisplayOptions.get('stat_tiles_show_sum', ['rain', 'ET', 'hail', 'snow', 'lightning_strike_count', 'windrun'])
                #set $agg_for_value = 'sum'
              #end if

              #set $stat_month = $get_stat_table_month_obs($time_span_start_ts, $time_span_end_ts)
              #set $raw_value = $getattr($getattr($stat_month, $stat_table_obs), $agg_for_value).raw

              #if $raw_value is not None
                #silent $per_month[$month].append($raw_value)
                #silent $per_year[$year].append($raw_value)
                #silent $per_all.append($raw_value)
              #end if

              <td data-testid="month-$month_from_range-$agg-$stat_table_obs">
                $getattr($getattr($stat_month, $stat_table_obs), $agg_for_value)
              </td>
            #else
              <td>-</td>
            #end if
          #end for

          <td>
            <!--prettier-ignore-->
            ## `in` is true as soon as the key exists, and the key is made
            ## before anything goes into it. The list can still be empty.
            #if $per_year.get($year)
              <strong data-testid="year-$year-$agg-$stat_table_obs">
                #if $agg == 'max'
                  $format_raw_value($max($per_year[$year]), $stat_table_obs)
                #elif $agg == 'min'
                  $format_raw_value($min($per_year[$year]), $stat_table_obs)
                #elif $agg == 'sum'
                  $format_raw_value($sum($per_year[$year]), $stat_table_obs)
                #elif $agg == 'avg'
                  $format_raw_value($sum($per_year[$year])/$len($per_year[$year]), $stat_table_obs)
                #end if
              </strong>
            #else
              <strong>-</strong>
            #end if
          </td>
        </tr>
      #end for
      #if $context == 'alltime'
        <tr class="summary">
          <td>
            <!--prettier-ignore-->
            #if $agg == 'sum'
              $gettext("Average per year")
            #else
              $gettext($agg.capitalize())
            #end if
          </td>

          #for $month in range(1, 13)
            #if $per_month[$month]
              <td data-testid="agg-month-$month-$agg-$stat_table_obs">
                #if $agg == 'max'
                  $format_raw_value($max($per_month[$month]), $stat_table_obs)
                #elif $agg == 'min'
                  $format_raw_value($min($per_month[$month]), $stat_table_obs)
                #elif $agg == 'sum'
                  ## Ten Mays added together is not a number anybody wants.
                  ## The mean of them is: how wet a May is here.
                  $format_raw_value($sum($per_month[$month])/$len($per_month[$month]), $stat_table_obs)
                #elif $agg == 'avg'
                  $format_raw_value($sum($per_month[$month])/$len($per_month[$month]), $stat_table_obs)
                #end if
              </td>
            #else
              <td>-</td>
            #end if
          #end for

          <td>
            <strong data-testid="total-$agg-$stat_table_obs">
              <!--prettier-ignore-->
              ## Nothing at all is possible: a reading the station has
              ## never recorded, or a rain gauge that has stayed dry.
              ## `min()` of an empty list raises, and it took the whole
              ## statistics page with it.
              #if not $per_all
                -
              #elif $agg == 'max'
                $format_raw_value($max($per_all), $stat_table_obs)
              #elif $agg == 'min'
                $format_raw_value($min($per_all), $stat_table_obs)
              #elif $agg == 'sum'
                ## The whole row is a mean now, so this is too: what a year
                ## brings, not what every year brought put together.
                $format_raw_value($sum($per_all)/$max(1, $len($per_year)), $stat_table_obs)
              #elif $agg == 'avg'
                $format_raw_value($sum($per_all)/$len($per_all), $stat_table_obs)
              #end if
            </strong>
          </td>
        </tr>
      #end if
    </tbody>
  </table>
  </div>
#end for
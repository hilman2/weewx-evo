<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
##
## The forecast, from weewx-evo's own `$forecast`.
##
## What was here before spoke to three things that are not in this program:
## weewx-forecast (Zambretti, `$forecast.weather_periods`), weewx-DWD (a JSON
## file on disk and a `$dwd_warning_has_warning` tag), and wdc's own iframe
## embedding. The first two are WeeWX extensions; a station running weewx-evo
## has neither, so every branch here was unreachable and the section never
## appeared at all -- on a station with a forecast configured and fetching.
##
## `$forecast` is the core's, and one source answers everything: hours, days,
## warnings, and when the model last ran. See `forecast/tags.py`.
##
## `forecast_settings`, not `forecast`. Every key under [Extras] becomes a
## top-level tag, and the extras are searched before the tag layer -- so a
## section called `forecast` shadows `$forecast` itself with a plain dict, and
## every `$forecast.days` on the page becomes "cannot find 'days'".
#set $conf = $Extras.get('forecast_settings', {})
#if not $to_bool($conf.get('enable', True)) or not $varExists('forecast')
#stop
#end if
##
## A named source, or all of them. Naming one is how a station that takes its
## numbers from one place and its warnings from another says which it means.
#set $named = $conf.get('source', '')
#if $named
#set $outlook = $getattr($forecast, $named)
#else
#set $outlook = $forecast
#end if
#if not $outlook
#stop
#end if
##
#set $day_count = $int($conf.get('days', 7))
#set $hour_count = $int($conf.get('hours', 24))
#set $show_hours = $to_bool($conf.get('show_hours', True))
#set $show_warnings = $to_bool($conf.get('show_warnings', True))
##
#set global $forecast_days = $outlook.days[:$day_count]
#set global $forecast_hours = $outlook.hours[:$hour_count]
#if $show_warnings
#set global $forecast_warnings = $outlook.active_warnings
#else
#set global $forecast_warnings = []
#end if

<!--prettier-ignore-->
#if $len($forecast_warnings) > 0
<div class="forecast-warnings">
  #for $warning in $forecast_warnings
  <div class="card warning warning--$warning.severity.lower()">
    <p class="warning__event">
      #include "includes/icons/lightning.svg"
      <span>$warning.event</span>
      <span class="warning__when">
        $warning.starts.format("%a %H:%M")#if $warning.ends# &ndash; $warning.ends.format("%a %H:%M")#end if#
      </span>
    </p>
    #if $warning.headline
    <p class="warning__headline">$warning.headline</p>
    #end if
    #if $warning.area
    <p class="warning__area">$warning.area</p>
    #end if
    #if $warning.description
    <details class="warning__more">
      <summary>$gettext("More")</summary>
      <p>$warning.description</p>
      #if $warning.instruction
      <p class="warning__instruction">$warning.instruction</p>
      #end if
    </details>
    #end if
  </div>
  #end for
</div>
#end if

<!--prettier-ignore-->
#if $len($forecast_days) > 0 or $len($forecast_hours) > 0
<div>
  <header class="section-header">
    <h2>$gettext($conf.get('heading', 'Forecast'))</h2>
  </header>
</div>

<div class="card forecast-tile">
  <!--prettier-ignore-->
  #if $len($forecast_days) > 0
  <ol class="forecast-list daily" data-test="forecast-days">
    #for $i, $day in $enumerate($forecast_days)
    <li class="forecast-day">
      <p class="forecast-day__name">
        #if $i == 0
        $gettext("Today")
        #else
        $day.dateTime.format("%a")
        #end if
      </p>
      #set global $forecast_symbol = $day.symbol
      #include "includes/forecast-icon.inc"
      <p class="forecast-day__text">$day.text</p>
      <p class="forecast-day__temps">
        <span class="forecast-day__max">$day.tempMax</span>
        <span class="forecast-day__min">$day.tempMin</span>
      </p>
      #if $day.rainProbability.raw is not None
      <p class="forecast-day__wet">
        #include "includes/icons/rain.svg"
        $day.rainProbability
      </p>
      #end if
      #if $day.windMax.raw is not None
      <p class="forecast-day__wind">
        #include "includes/icons/wind-gust.svg"
        $day.windMax
      </p>
      #end if
    </li>
    #end for
  </ol>
  #end if

  <!--prettier-ignore-->
  #if $show_hours and $len($forecast_hours) > 0
  <ol class="forecast-list hourly" data-test="forecast-hours">
    #for $hour in $forecast_hours
    <li class="forecast-hour">
      <p class="forecast-hour__time">$hour.dateTime.format("%H")</p>
      #set global $forecast_symbol = $hour.symbol
      #include "includes/forecast-icon.inc"
      <p class="forecast-hour__temp">$hour.outTemp</p>
      #if $hour.rainProbability.raw is not None
      <p class="forecast-hour__wet">$hour.rainProbability</p>
      #end if
    </li>
    #end for
  </ol>
  #end if

  <!--prettier-ignore-->
  <p class="forecast-issued">
    #if $outlook.issued
    $gettext("Model run") $outlook.issued.format("%a %H:%M")
    #else if $outlook.updated
    $gettext("Fetched") $outlook.updated.format("%a %H:%M")
    #end if
  </p>
</div>
#end if

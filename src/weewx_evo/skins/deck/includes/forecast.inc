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
## Built out of the skin's own pieces rather than new ones: `notice` for a
## warning, `card__body` and `card__foot` for the panel, `stat-label`,
## `stat-value` and `stat-detail` for the numbers. A section that invents its
## own vocabulary looks like a section somebody bolted on.
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
#set $hour_step = $max(1, $int($conf.get('hour_step', 3)))
#set $show_hours = $to_bool($conf.get('show_hours', True))
#set $show_warnings = $to_bool($conf.get('show_warnings', True))
##
#set global $forecast_days = $outlook.days[:$day_count]
#if $show_warnings
#set global $forecast_warnings = $outlook.active_warnings
#else
#set global $forecast_warnings = []
#end if

<!--prettier-ignore-->
#if $len($forecast_warnings) > 0
<div class="forecast-warnings">
  #for $warning in $forecast_warnings
  #set $grade = $warning.severity.lower()
  <div class="notice forecast-warning #if $grade in ('severe', 'extreme')#notice--bad#else#notice--warn#end if#">
    #include "includes/icons/lightning.svg"
    <div>
      <p class="notice__title">
        $warning.event
        <span class="forecast-warning__when">
          $warning.starts.format("%a %H:%M")#if $warning.ends# &ndash; $warning.ends.format("%a %H:%M")#end if#
        </span>
      </p>
      #if $warning.headline
      <p class="notice__body">$warning.headline</p>
      #end if
      #if $warning.area
      <p class="notice__body forecast-warning__area">$warning.area</p>
      #end if
      #if $warning.description
      <details class="notice__body forecast-warning__more">
        <summary>$gettext("More")</summary>
        <p>$warning.description</p>
        #if $warning.instruction
        <p class="forecast-warning__instruction">$warning.instruction</p>
        #end if
      </details>
      #end if
    </div>
  </div>
  #end for
</div>
#end if

<!--prettier-ignore-->
#if $len($forecast_days) > 0
<div>
  <header class="section-header">
    <h2>$gettext($conf.get('heading', 'Forecast'))</h2>
  </header>
</div>

<div class="card forecast-tile">
  <div class="card__body">
    ## The days are the choice, and the hours below are what was chosen.
    ## `role="tablist"` is not decoration: `assets/deck.js` already wires
    ## arrow keys, `aria-selected` and hiding the panels, so this needs no
    ## script of its own. Every day's hours are written out and all but one
    ## hidden -- seven short rows of markup, and nothing to fetch when
    ## somebody clicks.
    <!--prettier-ignore-->
    #if $len($forecast_days) > 0
    #if $show_hours
    <div class="forecast-list daily" role="tablist" value="0"
         aria-label="$gettext('Forecast')" data-test="forecast-days">
    #else
    <div class="forecast-list daily" data-test="forecast-days">
    #end if
      #for $i, $day in $enumerate($forecast_days)
      #if $show_hours
      <button type="button" class="forecast-day" role="tab" value="$i"
              id="fc-tab-$i" aria-controls="fc-hours-$i"
              aria-selected="#if $i == 0#true#else#false#end if#">
      #else
      <div class="forecast-day">
      #end if
        <p class="stat-label forecast-day__name">
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
          <span class="stat-value forecast-day__max">$day.tempMax</span>
          <span class="stat-label forecast-day__min">$day.tempMin</span>
        </p>
        #if $day.rainProbability.raw
        <p class="stat-detail forecast-day__wet">
          #include "includes/icons/rain.svg"
          $day.rainProbability
        </p>
        #end if
        #if $day.windMax.raw
        <p class="stat-detail forecast-day__wind">
          #include "includes/icons/wind-gust.svg"
          $day.windMax
        </p>
        #end if
      #if $show_hours
      </button>
      #else
      </div>
      #end if
      #end for
    </div>
    #end if

    <!--prettier-ignore-->
    #if $show_hours
    #for $i, $day in $enumerate($forecast_days)
    #set $slots = $day.hours($hour_step)
    <ol class="forecast-list hourly" role="tabpanel" id="fc-hours-$i"
        aria-labelledby="fc-tab-$i" data-test="forecast-hours"#if $i > 0# hidden#end if#>
      #if $len($slots) == 0
      <li class="forecast-hour forecast-hour--none">
        <p class="stat-detail">$gettext("No hourly detail for this day.")</p>
      </li>
      #end if
      #for $slot in $slots
      <li class="forecast-hour">
        <p class="stat-label forecast-hour__time">$slot.dateTime.format("%H")</p>
        #set global $forecast_symbol = $slot.symbol
        #include "includes/forecast-icon.inc"
        <p class="forecast-hour__temp">$slot.outTemp</p>
        ## Only when there is some. A dry afternoon printed "0%" twenty-four
        ## times under twenty-four identical clouds, which is a column of
        ## noise in the place a reader looks for the one hour that differs.
        #if $slot.rainProbability.raw
        <p class="stat-detail forecast-hour__wet">$slot.rainProbability</p>
        #end if
      </li>
      #end for
    </ol>
    #end for
    #end if
  </div>

  <!--prettier-ignore-->
  #if $outlook.issued or $outlook.updated
  <p class="card__foot forecast-issued">
    #if $outlook.issued
    $gettext("Model run") $outlook.issued.format("%a %H:%M")
    #else
    $gettext("Fetched") $outlook.updated.format("%a %H:%M")
    #end if
  </p>
  #end if
</div>
#end if

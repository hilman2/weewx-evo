<!--prettier-ignore-->
#encoding UTF-8
#errorCatcher Echo
#import datetime
#set $base_path = $Extras.get("base_path", "./")

## The page frame: a header, a side panel, and the link that skips both.
##
## What this replaced: 470 lines of <bx-header>, <bx-side-nav> and inline
## scripts, plus two <script type="module"> tags fetching Carbon web
## components from a CDN. The markup below is <header> and <nav>, which
## every browser has understood for a decade, and the behaviour is in
## assets/deck.js.

<a class="visually-hidden" href="#main">$gettext("Skip to content")</a>

<header class="header">
  <button
    class="icon-button header__menu"
    type="button"
    data-menu-toggle
    aria-expanded="false"
    aria-controls="sidenav"
    aria-label="$gettext('Menu')"
  >
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <path d="M4 6h24v2H4zm0 9h24v2H4zm0 9h24v2H4z" />
    </svg>
  </button>

  <a class="header__brand" href="$get_base_path(path='index.html')">
    <!--prettier-ignore-->
    #if 'logo_image' in $Extras
    <img class="logo" src="$Extras['logo_image']" alt="$gettext('Logo')" />
    #else
      #include "includes/icons/wdc.svg"
    #end if
    <span class="header__station">$station.location</span>
  </a>


  <div class="header__end">
    ## Whether the readings on this page are live, and how old they are.
    ## Only when a broker is configured: on a station without one it would
    ## be a permanent red badge saying nothing anybody can act on.
    #if $to_bool($Extras.get('live_push', 1))
    <div class="live-indicator live-indicator--waiting" id="live-indicator"
         role="status" aria-live="polite"
         title="$gettext('Waiting for the first reading.')">
      <span class="live-indicator__dot" aria-hidden="true"></span>
      <span class="live-indicator__label">$gettext('connecting')</span>
    </div>
    #end if
    <button
      class="icon-button"
      type="button"
      data-theme-toggle
      aria-label="$gettext('Switch theme')"
      title="$gettext('Switch theme')"
    >
      <svg class="theme-toggle__dark" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M13.5 5.41A15.08 15.08 0 0 0 25.1 23.61a11.11 11.11 0 0 1-7.98 3.39c-.14 0-.28.01-.42 0A11.09 11.09 0 0 1 13.5 5.41M14.98 3a1 1 0 0 0-.17.02A13.1 13.1 0 0 0 16.63 29c.16.01.33 0 .49 0a13.07 13.07 0 0 0 10.7-5.56 1.01 1.01 0 0 0-.78-1.56A13.08 13.08 0 0 1 15.89 4.38 1.01 1.01 0 0 0 14.98 3Z" />
      </svg>
      <svg class="theme-toggle__light" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M15 2h2v5h-2zM25 15h5v2h-5zM15 25h2v5h-2zM2 15h5v2H2zM6.85 5.37l3.5 3.51-1.41 1.41-3.51-3.5zM21.67 8.86l3.5-3.5 1.42 1.41-3.51 3.5zM23.15 21.67l3.5 3.5-1.41 1.42-3.5-3.51zM8.86 23.15l1.41 1.41-3.5 3.51-1.42-1.42z" />
        <path d="M16 10a6 6 0 1 0 6 6 6 6 0 0 0-6-6Zm0 10a4 4 0 1 1 4-4 4 4 0 0 1-4 4Z" />
      </svg>
    </button>
  </div>
</header>

<div class="scrim" hidden-until-found></div>

<div class="layout">
  <nav class="sidenav" id="sidenav" aria-label="$gettext('Sections')">
    <!--prettier-ignore-->
    ## The four periods. One page, five spans of time -- which is why they
    ## are grouped under what they show rather than sitting in the header
    ## as though they applied to whatever page you are on.
    <div class="sidenav__group">
      <p class="sidenav__title">$gettext("Conditions")</p>
      <a href="$get_base_path(path='index.html')">$gettext("Today")</a>
      <!--prettier-ignore-->
      #if $show_yesterday
      <a href="$get_base_path(path='yesterday.html')">$gettext("Yesterday")</a>
      #end if
      <a href="$get_base_path(path='week.html')">$gettext("Week")</a>
      <a href="$get_base_path(path='month.html')">$gettext("Month")</a>
      <a href="$get_base_path(path='year.html')">$gettext("Year")</a>
    </div>

    <div class="sidenav__group">
      <p class="sidenav__title">$gettext("Station")</p>

      <a href="$get_base_path(path='celestial.html')">
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path d="M16 12a4 4 0 1 0 4 4 4 4 0 0 0-4-4Zm0-9h2v5h-2zm-1 22h2v5h-2zM25 15h5v2h-5zM2 15h5v2H2zM6.85 5.37l3.5 3.51-1.41 1.41-3.51-3.5zM21.67 8.86l3.5-3.5 1.42 1.41-3.51 3.5zM23.15 21.67l3.5 3.5-1.41 1.42-3.5-3.51zM8.86 23.15l1.41 1.41-3.5 3.51-1.42-1.42z" />
        </svg>
        <span>$gettext("Celestial")</span>
      </a>

      <a href="$get_base_path(path='statistics.html')">
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path d="M4 2H2v26a2 2 0 0 0 2 2h26v-2H4Z" />
          <path d="M30 9h-7v2h3.59L21 16.59l-4.29-4.3a1 1 0 0 0-1.42 0L8 19.59 9.41 21 16 14.41l4.29 4.3a1 1 0 0 0 1.42 0L28 12.41V16h2Z" />
        </svg>
        <span>$gettext("Statistics")</span>
      </a>

      <!--prettier-ignore-->
      #if $show_sensor_page
      <a href="$get_base_path(path='sensor-status.html')">
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path d="M23 27h-2v-2a3 3 0 0 0-3-3h-4a3 3 0 0 0-3 3v2H9v-2a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5ZM16 4a6 6 0 1 0 6 6 6 6 0 0 0-6-6Zm0 10a4 4 0 1 1 4-4 4 4 0 0 1-4 4Z" />
        </svg>
        <span>$gettext("Sensor Status")</span>
      </a>
      #end if

      <!--prettier-ignore-->
      #if $show_cmon_page
      <a href="$get_base_path(path='computer-monitor.html')">
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path d="M26 6H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h6v4h-2v2h12v-2h-2v-4h6a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2Zm-8 20h-4v-4h4ZM6 20V8h20v12Z" />
        </svg>
        <span>$gettext("Computer Monitor")</span>
      </a>
      #end if

      <!--prettier-ignore-->
      #for $static_page in $get_static_pages()
      <a href="$get_base_path(path=$static_page['link'])">
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path d="M25.7 9.3l-7-7A1 1 0 0 0 18 2H8a2 2 0 0 0-2 2v24a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V10a1 1 0 0 0-.3-.7ZM18 4.4l5.6 5.6H18ZM24 28H8V4h8v6a2 2 0 0 0 2 2h6Z" />
        </svg>
        <span>$gettext($static_page['title'])</span>
      </a>
      #end for
    </div>

    <!--prettier-ignore-->
    #set $archive_months = $SummaryByMonth
    #if len($SummaryByYear) == 0
    #set $SummaryByYear = $fake_get_report_years($alltime.start.format("%Y"), $latest.dateTime.format("%Y"))
    #end if

    <div class="sidenav__group">
      <p class="sidenav__title">$gettext('Archive &amp; NOAA Reports')</p>

      ## <details> is a disclosure. It opens, it closes, it remembers
      ## nothing, and it needs no script -- which is the whole reason the
      ## Carbon menu it replaces had one.
      <details class="sidenav__years">
        <summary>$gettext("Years")</summary>
        <!--prettier-ignore-->
        #for $year in $SummaryByYear
        <a href="$get_base_path(path='year-' + $str(year) + '.html')">$year</a>
        #end for
      </details>

      <!--prettier-ignore-->
      #for $year in $SummaryByYear
      #set $months_for_year = $filter_months(archive_months, $year)
      #if len($months_for_year) > 0
      <details class="sidenav__years">
        <summary>$year</summary>
        <!--prettier-ignore-->
        #for $month in $months_for_year
        <a href="$get_base_path(path='month-' + $str(month) + '.html')">$spell($datetime.datetime.strptime($month, "%Y-%m"), "%B")</a>
        #end for
      </details>
      #end if
      #end for
    </div>
  </nav>

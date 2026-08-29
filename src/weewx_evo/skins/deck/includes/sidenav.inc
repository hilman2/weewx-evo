<!--prettier-ignore-->
#encoding UTF-8
#errorCatcher Echo
#import datetime
##
## The side panel.
##
## Three things about it are decisions rather than markup:
##
## **Which page you are on is decided here, not in the browser.** It used to
## be `markCurrent()` in deck.js, comparing `location.pathname` against every
## link once the page had loaded. The renderer knows which file it is writing
## -- `$filename` -- so the attribute goes into the file. One less thing for a
## script to do, one less frame in which the wrong entry looks current, and it
## still works with JavaScript switched off.
##
## **The archive is one entry, not one per year.** A station recording since
## 2016 had eleven disclosure triangles stacked under "Archive & NOAA
## Reports": ten years and a list of the years. They are inside one now, and
## the year being looked at is open, so a month page shows that year's months
## without anybody clicking.
##
## **Every entry carries an icon, or none does.** Four of ten had one, which
## reads as those four being more important rather than as six having been
## forgotten.
##
## The entries are a list walked by a loop rather than a `#def` called ten
## times. A `#def` here is not reachable: `#include` compiles as a unit of its
## own, and the call went to the tag layer instead -- three hundred `?
## 'nav_link'?` in one run, in markup nobody looks at twice.
#set $here = $filename.split("/")[-1]

#set $sections = []
#set $conditions = [("index.html", $gettext("Today"), "today")]
#if $show_yesterday
#silent $conditions.append(("yesterday.html", $gettext("Yesterday"), "yesterday"))
#end if
#silent $conditions.append(("week.html", $gettext("Week"), "week"))
#silent $conditions.append(("month.html", $gettext("Month"), "month"))
#silent $conditions.append(("year.html", $gettext("Year"), "year"))
#silent $sections.append(($gettext("Conditions"), $conditions))

#set $station_pages = [("celestial.html", $gettext("Celestial"), "celestial"),
                       ("statistics.html", $gettext("Statistics"), "statistics")]
#if $show_sensor_page
#silent $station_pages.append(("sensor-status.html", $gettext("Sensor Status"), "sensors"))
#end if
#if $show_cmon_page
#silent $station_pages.append(("computer-monitor.html", $gettext("Computer Monitor"), "monitor"))
#end if
#for $static_page in $get_static_pages()
#silent $station_pages.append(($static_page['link'], $gettext($static_page['title']), "page"))
#end for
#silent $sections.append(($gettext("Station"), $station_pages))

<nav class="sidenav" id="sidenav" aria-label="$gettext('Sections')">
  <!--prettier-ignore-->
  ## The spans of time are grouped under what they show rather than sitting in
  ## the header as though they applied to whatever page you are on.
  #for $title, $entries in $sections
  <div class="sidenav__group">
    <p class="sidenav__title">$title</p>
    <!--prettier-ignore-->
    #for $path, $label, $icon in $entries
    <a href="$get_base_path(path=$path)"#if $path == $here then ' aria-current="page"' else ''#>
      #include "includes/icons/nav-" + $icon + ".svg"
      <span>$label</span>
    </a>
    #end for
  </div>
  #end for

  <!--prettier-ignore-->
  #set $archive_months = $SummaryByMonth
  #if len($SummaryByYear) == 0
  #set $SummaryByYear = $fake_get_report_years($alltime.start.format("%Y"), $latest.dateTime.format("%Y"))
  #end if
  ## Which year this page belongs to, so its months are open on arrival.
  ## `month-2026-08.html` and `year-2026.html` both carry it after the dash.
  #set $here_year = ""
  #if $here.startswith("month-") or $here.startswith("year-")
  #set $here_year = $here.split("-")[1][:4]
  #end if

  <div class="sidenav__group">
    <p class="sidenav__title">$gettext("Archive")</p>

    ## <details> is a disclosure. It opens, it closes, it needs no script --
    ## which is the whole reason the Carbon menu it replaced had one.
    <details class="sidenav__archive"#if $here_year then " open" else ""#>
      <summary>
        #include "includes/icons/nav-archive.svg"
        <span>$gettext("Years and months")</span>
      </summary>

      <!--prettier-ignore-->
      #for $year in $SummaryByYear
      #set $months_for_year = $filter_months(archive_months, $year)
      #set $year_page = 'year-' + $str($year) + '.html'
      <div class="sidenav__year">
        <a href="$get_base_path(path=$year_page)"#if $year_page == $here then ' aria-current="page"' else ''#>$year</a>
        <!--prettier-ignore-->
        #if len($months_for_year) > 0
        <div class="sidenav__months">
          <!--prettier-ignore-->
          #for $month in $months_for_year
          #set $month_page = 'month-' + $str($month) + '.html'
          <a href="$get_base_path(path=$month_page)"#if $month_page == $here then ' aria-current="page"' else ''#>$spell($datetime.datetime.strptime($month, "%Y-%m"), "%b")</a>
          #end for
        </div>
        #end if
      </div>
      #end for
    </details>
  </div>
</nav>

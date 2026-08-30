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
## **The other places are one entry too, not one group per place.** Same
## `<details>` as the year archive, open at `places_fold` or fewer, and past
## that the summary carries the current place's name -- so eight places still
## leave the sidebar four lines tall. That problem was solved once already,
## when eleven stacked year disclosures became one.
##
## **A site page has no Conditions, Station or Archive group.** Those links
## would have to point at *a* place, and a nav entry that silently picks one
## for you is the forty-months shape: plausible, wrong, and nothing on the
## page can tell.
##
## The entries are a list walked by a loop rather than a `#def` called ten
## times. A `#def` here is not reachable: `#include` compiles as a unit of its
## own, and the call went to the tag layer instead -- three hundred `?
## 'nav_link'?` in one run, in markup nobody looks at twice.
#set $here = $filename.split("/")[-1]

## Which pages this run is writing. The third item of every entry below is
## the page's own word -- the same word `skin.conf` puts in `place_page` --
## so a narrowed run drops the entries whose files it did not write. A link
## into a page nobody wrote is a 404 on somebody else's web host, and the
## setting that produces it is the one offered to the operator who is about
## to publish over FTP.
## Written as a plain expression at each use and not as a `#def`. A `#def`
## in an include compiles as a method, and a `#set` in the same file is a
## local of `respond()` -- so the helper could not see the list and every
## page in the skin failed to render with "cannot find 'only'". The trap is
## the one already written down two paragraphs up, met from the other side.
#set $only = $place_pages

#set $sections = []
#set $conditions = []
#if (not $only or "today" in $only)
#silent $conditions.append(("index.html", $gettext("Today"), "today"))
#end if
#if $show_yesterday and (not $only or "yesterday" in $only)
#silent $conditions.append(("yesterday.html", $gettext("Yesterday"), "yesterday"))
#end if
#if (not $only or "week" in $only)
#silent $conditions.append(("week.html", $gettext("Week"), "week"))
#end if
#if (not $only or "month" in $only)
#silent $conditions.append(("month.html", $gettext("Month"), "month"))
#end if
#if (not $only or "year" in $only)
#silent $conditions.append(("year.html", $gettext("Year"), "year"))
#end if
#if len($conditions)
#silent $sections.append(($gettext("Conditions"), $conditions))
#end if

#set $station_pages = []
#if (not $only or "celestial" in $only)
#silent $station_pages.append(("celestial.html", $gettext("Celestial"), "celestial"))
#end if
#if (not $only or "statistics" in $only)
#silent $station_pages.append(("statistics.html", $gettext("Statistics"), "statistics"))
#end if
#if $show_sensor_page and (not $only or "sensors" in $only)
#silent $station_pages.append(("sensor-status.html", $gettext("Sensor Status"), "sensors"))
#end if
#if $show_cmon_page and (not $only or "monitor" in $only)
#silent $station_pages.append(("computer-monitor.html", $gettext("Computer Monitor"), "monitor"))
#end if
#for $static_page in $get_static_pages()
#silent $station_pages.append(($static_page['link'], $gettext($static_page['title']), "page"))
#end for
#if len($station_pages)
#silent $sections.append(($gettext("Station"), $station_pages))
#end if

#set $places_summary = $gettext("All places")
## The summary stands for the place whose page this is, so it carries that
## place's colour like every entry under it. Without the inline `--place` the
## one CSS rule that paints these icons falls back to the grey, and the fold
## reads as a tenth kind of thing above nine coloured ones. Empty on a site
## page, where the summary stands for all of them and no single colour is
## the honest answer.
#set $places_style = ''
#if $here_place
#set $places_summary = $here_place.label
#set $places_style = ' style="--place: ' + $here_place.color + '"'
#end if
<nav class="sidenav" id="sidenav" aria-label="$gettext('Sections')">
  ## Empty at one place, so nothing about the sidebar changes there.
  #if $places
  <div class="sidenav__group">
    <p class="sidenav__title">$gettext("Places")</p>
    <a href="$get_base_path(path='index.html')"#if $scope == 'site' and $here == 'index.html' then ' aria-current="page"' else ''#>
      #include "includes/icons/nav-overview.svg"
      <span>$gettext("Overview")</span>
    </a>
    <a href="$get_base_path(path='compare.html')"#if $here.startswith('compare') then ' aria-current="page"' else ''#>
      #include "includes/icons/nav-compare.svg"
      <span>$gettext("Comparison")</span>
    </a>

    <!--prettier-ignore-->
    ## Both classes: the archive's disclosure styling, plus the one rule that
    ## paints a place's icon in its own colour.
    <details class="sidenav__archive sidenav__places"#if $open_places then " open" else ""#>
      <summary$places_style>
        #include "includes/icons/nav-place.svg"
        <span>$places_summary</span>
      </summary>
      <!--prettier-ignore-->
      ## A place with no records has no directory, so it gets no link: a
      ## link into a directory the feed did not write is a 404 on somebody's
      ## published site.
      #for $p in $places
      #if $p.has_data
      <a href="$get_base_path(path=$p.path + 'index.html')" style="--place: $p.color"#if $p.here then ' aria-current="page"' else ''#>
        #include "includes/icons/nav-place.svg"
        <span>$p.label</span>
      </a>
      #end if
      #end for
    </details>
  </div>
  #end if
  ## Everything below is about one place, so a site page has none of it.
  #if $scope != 'site'
  <!--prettier-ignore-->
  ## The spans of time are grouped under what they show rather than sitting in
  ## the header as though they applied to whatever page you are on.
  #for $title, $entries in $sections
  <div class="sidenav__group">
    <p class="sidenav__title">$title</p>
    <!--prettier-ignore-->
    #for $path, $label, $icon in $entries
    <a href="$place_path(path=$path)"#if $path == $here then ' aria-current="page"' else ''#>
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

  #if (not $only or "archive" in $only)
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
        <a href="$place_path(path=$year_page)"#if $year_page == $here then ' aria-current="page"' else ''#>$year</a>
        <!--prettier-ignore-->
        #if len($months_for_year) > 0
        <div class="sidenav__months">
          <!--prettier-ignore-->
          #for $month in $months_for_year
          #set $month_page = 'month-' + $str($month) + '.html'
          <a href="$place_path(path=$month_page)"#if $month_page == $here then ' aria-current="page"' else ''#>$spell($datetime.datetime.strptime($month, "%Y-%m"), "%b")</a>
          #end for
        </div>
        #end if
      </div>
      #end for
    </details>
  </div>
  #end if
  #end if
</nav>

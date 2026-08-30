<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
##
## The board: one row per place, one column per reading.
##
## **This is the design decision of the overview.** A grid of cards is one
## place at a time -- five readings by four places is twenty cards, three
## screens, and no way to compare anything. Places down the side is the
## layout where the eye runs down a column, which is what a newspaper
## weather page has done for a century, and it is the only one that still
## fits eight places on one screen.
##
## Four things in here are decisions rather than markup:
##
## **`role=` is written unconditionally.** Redundant at full width, where the
## element names say it already. Load-bearing below 46rem, where the CSS sets
## `display: block` on the rows and the cells and some engines drop the
## implicit table roles along with it.
##
## **`data-no-scroll`, and no `.table-scroll` wrapper.** Sideways scrolling
## hides content behind a gesture nobody performs on a weather page, and the
## board is the one table here that must never be in a scroll box: it reflows
## to a card per place in CSS instead.
##
## **There is no badge inside any cell.** One `.board-age` per row instead.
## Anything written inside a `.board-cell` would sit in the subtree
## `live-status.js` observes, and paint -> mutation -> paint is the loop that
## locked the tab within a second of loading. One age per row makes it
## impossible by construction rather than guarded twice.
##
## **No summary row.** No mean, no total, no "all sites". The only
## cross-place figure anywhere on this page is a difference, in the unusual
## list, naming both of its ends. Two thermometers reading 19 and 21 do not
## make 20 anywhere.
#if $places
#set $board_obs = $DisplayOptions.get('board_observations', ['outTemp', 'outHumidity', 'windSpeed', 'rain', 'barometer'])
## One name in the settings comes back as a string, not a list of one.
#if isinstance($board_obs, str)
#set $board_obs = [$board_obs]
#end if

## A column no place has is dropped entirely: four em dashes in a column is
## a column of nothing, and it pushes the columns that mean something off
## the side of a phone.
##
## `.exists` -- does this place's archive have the column -- and not
## `.has_data`, which is "did anything land in it today". `UV` and
## `radiation` go null every night, so keyed on today's data the board would
## lose whole columns between the evening render and the morning one, and
## gain them back at sunrise. What a place records is a property of the
## place; what arrived today is a property of today.
#set $columns = []
#for $one in $board_obs
  #for $p in $places
    #if $p.has_data and $getattr($p.tags.day, $one).exists
      #silent $columns.append($one)
      #break
    #end if
  #end for
#end for

<table class="now-board" role="table" data-no-scroll>
  <thead>
    <tr role="row">
      <th scope="col" role="columnheader">$gettext("Place")</th>
      <!--prettier-ignore-->
      #for $one in $columns
      <th scope="col" role="columnheader" class="board-cell">$obs.label[$one]</th>
      #end for
      <th scope="col" role="columnheader" class="board-age">$gettext("Age")</th>
    </tr>
  </thead>
  <tbody>
    <!--prettier-ignore-->
    #for $p in $places
    #set $age = $place_age($p, $freshest)
    #set $age_flag = ''
    #if $age.state == 'stale'
    #set $age_flag = ' data-stale'
    #else if $age.state == 'silent'
    #set $age_flag = ' data-silent'
    #end if
    ## `never` gets no flag at all, and that is the fix rather than an
    ## omission. One attribute carried both states, and `live-status.js`
    ## left every row wearing it out of the "3 of 4 live" count on the
    ## reading that it meant "never written a record -- unconfigured". So a
    ## console dead since morning was not counted as dead: the badge
    ## everybody looks at said "1 of 1 live" in green. `data-silent` now
    ## means one thing on both sides -- a place that HAS records and has
    ## stopped -- which is the state `paintRowAges` itself sets and clears
    ## from the live document. A place that has never reported says so in
    ## words in the cell, and is not an alarm: the same rule `notify/`
    ## follows, because a check that goes red because somebody else's
    ## hardware was never plugged in is a check people stop reading.
    <tr role="row" style="--place: $p.color">
      <th scope="row" role="rowheader" class="board-place">
        <span class="place-dot" aria-hidden="true"></span>
        <span class="board-code">$p.code</span>
        ## No link into a directory the feed did not write. A place with no
        ## records has no pages, and a 404 on somebody's published site is
        ## worse than a name that is not yet a link.
        #if $p.has_data
        <a href="$get_base_path(path=$p.path + 'index.html')">$p.label</a>
        #else
        <span>$p.label</span>
        #end if
        ## The altitude is here on purpose: it is the *explanation* of the
        ## temperature spread the reader has just read two columns up, and
        ## the explanation belongs beside the anomaly.
        <span class="board-where">$p.tags.station.altitude &middot; $p.tags.station.latitude[0]&deg;&thinsp;$p.tags.station.latitude[1]&prime;&thinsp;$p.tags.station.latitude[2] $p.tags.station.longitude[0]&deg;&thinsp;$p.tags.station.longitude[1]&prime;&thinsp;$p.tags.station.longitude[2]</span>
      </th>

      #for $one in $columns
      #set $rounding = $str($get_rounding($one, $one))
      #if $p.has_data and not $getattr($p.tags.day, $one).exists
      ## Honest rather than blank, and honest rather than zero: a station
      ## carrying `role = extra` contributes temperature, humidity and
      ## dewpoint and nothing else, and a nought in the rain column would
      ## read as a dry afternoon. No `data-observation`, so nothing live
      ## writes into it either.
      <td class="board-cell" role="cell" data-label="$obs.label[$one]">
        <span class="board-now" title="$gettext('This place does not record this reading.')">&mdash;</span>
      </td>
      #else if not $p.has_data or not $getattr($p.tags.day, $one).has_data
      ## The column is there and nothing is in it today. Saying "does not
      ## record this reading" here would be a false statement about a sensor
      ## that has simply dropped out -- the same invention as "825 values
      ## from something else". Only what was measured: nothing today.
      <td class="board-cell" role="cell" data-label="$obs.label[$one]">
        <span class="board-now" title="$gettext('Nothing recorded here today.')">&mdash;</span>
      </td>
      #else
      <td class="board-cell" role="cell" data-label="$obs.label[$one]"
          data-observation="$one" data-archive="$p.name"
          data-unit="$get_unit_label($get_unit_for_obs($one, $one, 'day'))"
          data-rounding="$rounding">
        ## The same shape the stat tile uses, verbatim, so `live-poll.js`
        ## needs one more selector and no second way of finding a value.
        #if $get_show_sum($one)
        <span class="board-now"><span class="stat-title-obs-value"><span class="raw raw-sum">$getattr($p.tags.day, $one).sum.format("%." + $rounding + "f")</span></span></span>
        <span class="board-range">$gettext("Total")</span>
        #else
        <span class="board-now"><span class="stat-title-obs-value"><span class="raw">$getattr($p.tags.current, $one).format("%." + $rounding + "f")</span></span></span>
        ## Whole-day extremes come out of `archive_day_*`, which takes them
        ## from the live packets: a gust between two archive records is in
        ## this range and in no chart on this site. Without the sentence a
        ## reader comparing the two against each other has found what looks
        ## like a bug and is not one.
        <span class="board-range" title="$gettext('The high and low of the day, from the live readings rather than from the archive records.')"><span class="lo">$getattr($p.tags.day, $one).min.format("%." + $rounding + "f")</span> &hellip; <span class="hi">$getattr($p.tags.day, $one).max.format("%." + $rounding + "f")</span></span>
        #end if
      </td>
      #end if
      #end for

      ## The one live indicator on this table, and it is per row. Written
      ## server-side as well, so a page read with scripting off still says
      ## how old its numbers are instead of saying nothing at all.
      ## When this place last wrote, so a row the live document has stopped
      ## carrying ages from the render instead of freezing at "just now".
      <td class="board-age" role="cell" data-archive="$p.name" data-since="$p.stop" data-label="$gettext('Age')"$age_flag>
        #if $age.state == 'never'
        $gettext("no readings yet")
        #else if $age.word == 'just now'
        $gettext("just now")
        #else
        $age.count $gettext($age.word)
        #end if
      </td>
    </tr>
    #end for
  </tbody>
</table>
#end if

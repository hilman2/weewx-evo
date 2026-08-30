<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
##
## The whole of a comparison page. The four templates that use it are two
## lines each: `#set global $compare_span = 'week'` and this include.
##
## `#set global`, not `#attr` and not a `#def`. An `#include` compiles as a
## unit of its own: `#attr` does not reach into it, and a `#def` written in
## here is not callable from the file that included it -- the call falls
## through to the tag layer, which is where three hundred `?'nav_link'?` in
## one run came from. The skin already relies on `#set global` for exactly
## this, before `diagram-tile.inc`.
##
## Four files rather than four tabbed panels on one. Tabs load four times the
## charts for a reader looking at one quarter of them, and a span is worth
## having in the URL: deep-linkable, printable, back-button-able, and it
## needs no script at all.
#set $spans_shown = $DisplayOptions.get('compare_spans', ['day', 'week', 'month', 'year'])
#if isinstance($spans_shown, str)
#set $spans_shown = [$spans_shown]
#end if
## `global`, because `compare-figures.inc` reads it and an `#include` is a
## compilation unit of its own: a plain `#set` does not reach into one.
#set global $compare_obs = $DisplayOptions.get('compare_observations', ['outTemp', 'outHumidity', 'windSpeed', 'rain'])
#if isinstance($compare_obs, str)
#set global $compare_obs = [$compare_obs]
#end if
## Which file a span is published as. `day` is `compare.html` so the plain
## name is the one a person would guess and the one everything links to.
#set $span_files = {'day': 'compare.html', 'week': 'compare-week.html', 'month': 'compare-month.html', 'year': 'compare-year.html'}
#set $span_words = {'day': $gettext('Today'), 'week': $gettext('Week'), 'month': $gettext('Month'), 'year': $gettext('Year')}

<!DOCTYPE html>
<html lang="$lang">
  <head>
    #include "includes/html-head.inc"
    <title>$site_title - $gettext("Comparison")</title>
  </head>

  <body class="theme-$DisplayOptions.get('layout', 'alternative')" data-units="$page_unit_system()">
    #include "includes/ui-shell.inc"

    <main class="main" id="main">
      <div class="wrap">
        <header class="page-head">
          <h1>$gettext("Comparison")</h1>
          <h2>$span_words.get($compare_span, $compare_span)</h2>
          <!--prettier-ignore-->
          ## Links, not tabs. Nothing here needs a script and every span has
          ## its own address.
          <nav class="place-switch" aria-label="$gettext('Periods')">
            #for $one in $spans_shown
            #if $one in $span_files
            <a href="$get_base_path(path=$span_files[$one])"#if $one == $compare_span then ' aria-current="page"' else ''#>$span_words[$one]</a>
            #end if
            #end for
          </nav>
        </header>

        <!--prettier-ignore-->
        ## One press switches a place off on *every* chart on the page, which
        ## is the question actually being asked -- "just the two gardens" --
        ## rather than the same legend click repeated four times. Inert with
        ## scripting off, and then every place is on every chart, which is
        ## complete and correct.
        #if len($places) > 1
        <div class="chips" role="group" aria-label="$gettext('Places')">
          #for $p in $places
          <button type="button" class="chip" data-place-toggle="$p.name"
                  aria-pressed="true" style="--place: $p.color">
            <span class="place-dot" aria-hidden="true"></span><span>$p.label</span>
          </button>
          #end for
        </div>
        #end if

        #include "includes/compare-figures.inc"

        <!--prettier-ignore-->
        ## The charts, from the manifest at the **root** of the chart export.
        ## On a site of several places that directory holds nothing but
        ## comparison plots -- the directory is the facet, so there is no
        ## attribute here that could disagree with it.
        <div class="grid grid--wide" data-plots="$compare_span"></div>

    <!--prettier-ignore-->
    ## The frame is opened in two files and closed in one: `ui-shell.inc`
    ## opened `<div class="layout">`, this opened `<main>` and `.wrap`, and
    ## `footer.inc` closes all three. Copying only part of it gives HTML
    ## that is mis-nested in a way no text-level test sees.
    #include "includes/footer.inc"
  </body>
</html>

<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
##
## One chart, named rather than carried.
##
## The tile this replaces queried the database while the page was being
## written and put the whole series in a global variable beside it. Two
## things followed, and both were visible:
##
##   * the chart was as fresh as the last render, sitting under a live figure
##     that was seconds old;
##   * what a chart *is* -- which readings, what they are called, what colour,
##     line or bars -- was decided here in the skin, while `plots.toml` and
##     the plot editor in the settings decided something else that nothing on
##     this page ever read.
##
## Now the tile names a plot and stops. `assets/charts.js` fetches
## `<charts_path>/<name>.json`, draws it, and asks again every minute. That
## file is written by the `json` feed straight out of `plots.toml`, so there
## is one definition of a chart and the settings page edits the thing on the
## screen.
##
## The heading is left empty on purpose and filled from the file. A title
## rendered here would be the second answer to "what is this chart called",
## and on a site published over FTP this page cannot read the file anyway.
##
## `$plot_name` is the span and the plot run together, which is how the feed
## names its files: `day` + `tempdew` is `daytempdew.json`.
#set $plot_name = $context + $plot

<div>
  <div class="card diagram-tile" data-test="$plot">
    <div>
      <div>
        <p class="label" data-plot-title="$plot_name">&nbsp;</p>
        <div class="value">
          <!--prettier-ignore-->
          <div class="diagram" data-test="$plot" data-plot="$plot_name"
               data-chart='$get_plot_chart($context)'></div>
        </div>
      </div>
    </div>
  </div>
</div>

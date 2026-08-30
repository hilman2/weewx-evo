<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
##
## The figures, above the charts. One row per reading, one column per place,
## and one Spread column.
##
## **Server-rendered by Cheetah out of the tag layer, not refilled by a
## script.** That is not laziness: it works with scripting off, it prints,
## and it is the answer -- the charts below are the *shape* of the answer.
##
## **The Spread column is a difference and names both of its ends.** Never a
## mean, never a standard deviation, never a range printed as though it were
## a value. Two thermometers reading 19 and 21 do not make 20 anywhere, and
## this table is where somebody would be most tempted to write it down.
##
## **A difference has its own unit label.** `$difference_label` returns K
## where the page shows °C. The number is a straight subtraction and needs no
## conversion -- a 5 °C difference is 5 K -- but a column headed °C holding
## 4.2 names a temperature that does not exist.
#if $places and $compare_obs
#set $rows = $compare_rows($places, $compare_obs, $compare_span)
<div class="table-scroll">
<table class="compare-figures">
  <thead>
    <tr>
      <th scope="col">$gettext("Reading")</th>
      <!--prettier-ignore-->
      #for $p in $places
      <th scope="col" style="--place: $p.color">
        <span class="place-dot" aria-hidden="true"></span>$p.code
        <span class="visually-hidden">$p.label</span>
      </th>
      #end for
      <th scope="col">$gettext("Spread")</th>
    </tr>
  </thead>
  <tbody>
    <!--prettier-ignore-->
    #for $row in $rows
    #set $rounding = $str($get_rounding($row.obs, $row.obs))
    <tr>
      <th scope="row">
        $obs.label[$row.obs]
        ## Which aggregate this row is, said rather than assumed: a mean and
        ## a total are different questions and the column of numbers does
        ## not say which one it answered.
        #if $row.how == 'sum'
        <span class="compare-how" title="$gettext('Total')">&Sigma;</span>
        #else if $row.how == 'max'
        <span class="compare-how" title="$gettext('Max')">&and;</span>
        #else
        <span class="compare-how" title="$gettext('Avg')">&empty;</span>
        #end if
      </th>
      #for $cell in $row.cells
      <td class="compare-value">
        ## An em dash, never a nought. A nought is a measurement.
        #if not $cell.value
        &mdash;
        #else
        $cell.value.format("%." + $rounding + "f")
        #end if
      </td>
      #end for
      ## Empty, not zero, where fewer than two places have the reading:
      ## there is no spread between one place and itself.
      <td class="compare-spread">
        #if $row.spread is not None
        #set $gap = ("%." + $rounding + "f") % $row.spread
        <span class="compare-spread__figure">$gap$difference_label($row.unit)</span>
        ## Two ends, or none. Where every place read the same the difference
        ## is nought and the two ends are one place: "KIR-KIR" is not an
        ## answer to anything.
        #if $row.high.place.name != $row.low.place.name
        <span class="compare-spread__ends">$row.high.place.code&ndash;$row.low.place.code</span>
        #end if
        #end if
      </td>
    </tr>
    #end for
  </tbody>
</table>
</div>
#end if

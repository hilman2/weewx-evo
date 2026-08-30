<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
##
## What is not ordinary on this site right now. Nought to four lines.
##
## **When there is nothing, nothing is rendered** -- no wrapper, no heading,
## no "all normal". That is the whole reason a line here can be trusted: a
## warning that stands on every page every day is furniture, and the first
## thing anybody does with furniture is stop seeing it.
##
## The facts come from `$unusual` in `tags.py`, which applies three closed
## rules and never composes a sentence. The words are here, so they go
## through `$gettext` into `lang/*.conf` like every other string this skin
## prints -- the same split the core keeps between `codes.symbol()` naming
## the weather and the skin drawing it.
#if $unusual
#set $primary_round = $str($get_rounding($board_primary, $board_primary))
<ol class="unusual">
  #for $one in $unusual
  #if $one.kind == 'spread'
  ## Both ends named, always. Never a mean and never a range printed as if
  ## it were a value: two thermometers reading 19 and 21 do not make 20
  ## anywhere, and this is the one line on the site where somebody would be
  ## tempted to write it down.
  #set $gap = ("%." + $primary_round + "f") % $one.figure
  <li class="unusual--spread">
    <span class="unusual__figure">$gap$difference_label($one.unit)</span>
    <span>
      $gettext("apart"):
      <span class="unusual__place" style="--place: $one.high.color"><span class="place-dot" aria-hidden="true"></span>$one.high.label</span>
      $one.high_value.format("%." + $primary_round + "f"),
      <span class="unusual__place" style="--place: $one.low.color"><span class="place-dot" aria-hidden="true"></span>$one.low.label</span>
      $one.low_value.format("%." + $primary_round + "f")
    </span>
  </li>
  #else if $one.kind == 'silent'
  <li class="unusual--silent">
    <span class="unusual__figure">$one.age.count $gettext($one.age.word)</span>
    <span>
      <span class="unusual__place" style="--place: $one.place.color"><span class="place-dot" aria-hidden="true"></span>$one.place.label</span>
      $gettext("has stopped reporting")
    </span>
  </li>
  #else
  <li class="unusual--record">
    <span class="unusual__figure">$one.value.format("%." + $primary_round + "f")</span>
    <span>
      <span class="unusual__place" style="--place: $one.place.color"><span class="place-dot" aria-hidden="true"></span>$one.place.label</span>
      #if $one.way == 'high'
      $gettext("is the highest so far this year")
      #else
      $gettext("is the lowest so far this year")
      #end if
    </span>
  </li>
  #end if
  #end for
</ol>
#end if

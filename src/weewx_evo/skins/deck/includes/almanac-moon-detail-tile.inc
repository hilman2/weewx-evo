<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8

<div>
  <div class="card almanac-tile detail">
    <div>
      <div>
        <p class="label">$gettext("Moon")</p>
        <div class="stats">
          <div>
            <p class="label small">$gettext("Azimuth")</p>
            <p class="value">$("%.1f&deg;" % $almanac.moon.az)s</p>
          </div>
          <div>
            <p class="label small">$pgettext("Astronomical", "Altitude")</p>
            <p class="value">$("%.1f&deg;" % $almanac.moon.alt)</p>
          </div>
        </div>
        <div class="stats">
          <div>
            <p class="label small">$gettext("Right ascension")</p>
            <p class="value">$("%.1f&deg;" % $almanac.moon.ra)</p>
          </div>
          <div>
            <p class="label small">$gettext("Declination")</p>
            <p class="value">$("%.1f&deg;" % $almanac.moon.dec)</p>
          </div>
        </div>
        <!--prettier-ignore-->
        #if $almanac.next_full_moon.raw < $almanac.next_new_moon.raw
        <div class="stats">
          <div>
            <p class="label small">$gettext("Full moon")</p>
            <p class="value">$almanac.next_full_moon</p>
          </div>
          <div>
            <p class="label small">$gettext("New moon")</p>
            <p class="value">$almanac.next_new_moon</p>
          </div>
        </div>
        #else
        <div class="stats">
          <div>
            <p class="label small">$gettext("New moon")</p>
            <p class="value">$almanac.next_new_moon</p>
          </div>
          <div>
            <p class="label small">$gettext("Full moon")</p>
            <p class="value">$almanac.next_full_moon</p>
          </div>
        </div>
        #end if
        <div>
          <div>
            <p class="label small">$gettext("Phase")</p>
            <p class="value">$almanac.moon_phase</p>
            <p class="label small">$almanac.moon_fullness% $gettext("full")</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

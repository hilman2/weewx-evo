<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8

<div>
  <div class="card almanac-tile simple">
    <div>
      <div>
        <p class="label">
          <!--prettier-ignore-->
          $label_almanac
          #include "includes/pictograms/sun.svg"
        </p>
        <div>
          <div class="value">
            #include "includes/icons/sunrise.svg"
            <div class="value-col">
              <p class="label small">$gettext("Sunrise")</p>
              <p class="value">$almanac.sunrise</p>
            </div>
          </div>
          <div class="value">
            #include "includes/icons/sunset.svg"
            <div class="value-col">
              <p class="label small">$gettext("Sunset")</p>
              <p class="value">$almanac.sunset</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

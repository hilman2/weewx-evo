<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8

## Closes the <main> the page opened and the <div class="layout"> from
## ui-shell.inc. Every page includes both, in that order, so the frame is
## opened in one file and closed in one file rather than in fourteen.
    </div>
  </main>
</div>

<footer class="footer">
  <div class="wrap">
    <div class="row">
      <div>
        <p>
          $gettext("Uptime"): $station.uptime.long_form<br />
          $gettext("Server uptime"): $station.os_uptime.long_form<br />
          ## Whoever is rendering, by name. This read "WeeWX version 0.0.1",
          ## which is another program's name against this one's version.
          $gettext("Software"): $station.software $gettext("with")
          $station.hardware<br />
          $gettext("Skin"): $SKIN_NAME $SKIN_VERSION
        </p>
      </div>
      <div>
        <p>
          $pgettext("Geographical", "Altitude"): $station.altitude<br />
          $gettext("Latitude"): $station.latitude[0]&deg; $station.latitude[1]'
          $station.latitude[2]<br />
          $gettext("Longitude"): $station.longitude[0]&deg;
          $station.longitude[1]' $station.longitude[2]
        </p>
      </div>
      <div class="spacer"></div>
      <!--prettier-ignore-->
      #if 'github_link' in $Extras and $to_bool($Extras.github_link)
      <a
        class="icon-button"
        href="https://github.com/hilman2/weewx-evo"
        target="_blank"
        rel="noopener"
        aria-label="weewx-evo"
      >
        #include "includes/icons/github.svg"
      </a>
      #end if
    </div>
    <!--prettier-ignore-->
    <p class="muted" style="margin-top: var(--s-4)">
      $gettext("This station is controlled by <a target='_blank' href='https://github.com/hilman2/weewx-evo'>weewx-evo</a>, a weather software system written in Python.")
    </p>
  </div>
</footer>

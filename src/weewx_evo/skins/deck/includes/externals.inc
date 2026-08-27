<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
##
## A radar picture and whatever else the operator wants embedded.
##
## Nothing here needs an extension: it is HTML somebody put in `skin.conf`,
## and it lived inside the forecast include only because the forecast it used
## to sit beside came from the same place. They are separate things and are
## now separate files -- a station with no forecast can still show its radar.
##
#set $externals_list = []
#if 'externals' in $Extras and $len($Extras['externals']) > 0
  #for $external in $Extras['externals']
    #if $external == 'description'
      #continue
    #end if
    #if $to_bool($Extras['externals'][$external].show_on_front)
      #silent $externals_list.append($external)
    #end if
  #end for
#end if

#set $radar_externals_list = $externals_list
#if 'radar_html' in $Extras
  #set $radar_externals_list = ['radar'] + $externals_list
#end if

<!--prettier-ignore-->
#if $len($radar_externals_list) > 0
<div>
  <header class="section-header">
    <h2>$gettext($Extras.get("externals_heading", "Recent radar"))</h2>
  </header>
</div>

<div class="radar-container">
  #if $len($radar_externals_list) > 1
  <div class="tabs" role="tablist" value="$radar_externals_list[0]">
    #if 'radar_html' in $Extras
    <button type="button" role="tab" id="tab-radar" aria-controls="panel-radar" value="radar">
      $gettext("Recent radar")
    </button>
    #end if
    #for $external in $externals_list
    <button type="button" role="tab" id="tab-$external" aria-controls="panel-$external" value="$external">
      $Extras['externals'][$external].title
    </button>
    #end for
  </div>
  #end if

  <div class="bx-ce-demo-devenv--tab-panels">
    #if 'radar_html' in $Extras
    <div id="panel-radar" role="tabpanel" aria-labelledby="tab-radar">
      <div class="card tile-radar-forecast">
        $Extras.radar_html
      </div>
    </div>
    #end if
    #for $external in $externals_list
    <div id="panel-$external" role="tabpanel" aria-labelledby="tab-$external">
      <div class="card tile-radar-forecast">
        $Extras['externals'][$external].source
        <p style="margin-top: 0.25rem;">$Extras['externals'][$external].title_long</p>
      </div>
    </div>
    #end for
  </div>
</div>
#end if

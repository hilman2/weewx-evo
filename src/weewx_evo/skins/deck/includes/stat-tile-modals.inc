#errorCatcher Echo
#encoding UTF-8

#if $DisplayOptions.get('layout', 'alternative') == 'alternative' and 'stat_tile_links' in $DisplayOptions
  #for $skin_obs in $DisplayOptions.get('stat_tile_links')
    #set $render_modal = "stat_tile_links" in $DisplayOptions and $skin_obs in $DisplayOptions["stat_tile_links"] and $DisplayOptions["stat_tile_links"][$skin_obs]["open"] == "modal"
    #set $skin_obs_key = $skin_obs

    #if $render_modal
        <dialog id="modal-$skin_obs_key" size="lg" fullWidth>
        <div class="card__head">
            <button type="button" class="icon-button" data-dialog-close aria-label="Close" style="margin-inline-start:auto"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M24 9.4 22.6 8 16 14.6 9.4 8 8 9.4l6.6 6.6L8 22.6 9.4 24l6.6-6.6 6.6 6.6 1.4-1.4-6.6-6.6z"/></svg></button>
            <!-- <span class="muted">Label (Optional)</span> -->
            <h3>$obs.label[$skin_obs]</h3>
        </div>
        <div class="card__body">
            <iframe src='$DisplayOptions["stat_tile_links"][$skin_obs]["link"]' style="width: 100%; height: 100%; border: none;" ></iframe>
        </div>
        </dialog>

        <script type="text/javascript">
            document
                .querySelector(".stat-tile[data-observation='$skin_obs_key']")
                .addEventListener("click", () => {
                    document.getElementById("modal-$skin_obs_key").open = true;
                });
        </script>

        <style>
            .stat-tile[data-observation='$skin_obs_key'] {
                cursor: pointer;
            }
            #modal-$skin_obs_key cds-modal-body {
                min-height: 65vh;
                overflow: hidden;
            }
        </style>
    #end if
  #end for
#end if
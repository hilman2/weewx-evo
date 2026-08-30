#errorCatcher Echo
#encoding UTF-8
##
## The two live scripts and the words they print.
##
## In an include because three pages need them now -- the day page, the
## overview and, on a site of several places, whichever of them a reader
## opens first. One copy of the string list is one place to translate.
##
## `$live_file()` rather than the bare `live_push_file`: that setting is
## "live.json", relative, and from `/nordfeld/index.html` a browser resolves
## it to `/nordfeld/live.json`, which does not exist. Live values would be
## dead on every place page and it would read as a live-values bug. At one
## place `$live_file()` is that setting unchanged, so nothing moves.
## Live readings. The station POSTs them to live.php, which writes them
## beside itself; this reads that file. Nothing is opened anywhere for it --
## same web server as the page, same https, same origin.
#if $to_bool($Extras.get('live_push', 1))
    <script>
      window.deckLivePoll = {
        url: "$live_file()",
        every: $Extras.get('live_push_every', 15)
      };
      window.deckLiveStrings = {
        live: "$gettext('LIVE')",
        stale: "$gettext('LIVE')",
        offline: "$gettext('OFFLINE')",
        waiting: "…",
        connecting: "$gettext('connecting')",
        justNow: "$gettext('just now')",
        secondsAgo: "$gettext('s ago')",
        minutesAgo: "$gettext('min ago')",
        hoursAgo: "$gettext('h ago')",
        daysAgo: "$gettext('d ago')",
        liveSince: "$gettext('Updated')",
        lastSeen: "$gettext('Last live reading')",
        noBroker: "$gettext('No connection to the live feed.')",
        waitingFor: "$gettext('Waiting for the first reading.')",
        ## Everything below only exists on a page that carries places: the
        ## unit-mismatch state needs `data-units`, and the "3 of 4 live"
        ## count needs a board or a chip row. At one place none of it is
        ## emitted and the object is byte for byte what it was.
        ##
        ## Every key `live-status.js` asks for is here. A key it asks for and
        ## nothing emits does not fail -- it falls back to the JavaScript's
        ## English -- so a German site printed "1 of 2 live" and a badge
        ## reading "UNIT" beside "Alle Orte" and "meldet nichts mehr", and
        ## nothing anywhere reported it. `wrongUnit` (the badge word) and
        ## `wrongUnits` (its title) are two keys, not one.
        neverSent: "$gettext('The station does not publish this reading live.')"#if $places then ',' else ''#
        #if $places
        wrongUnit: "$gettext('UNIT')",
        wrongUnits: "$gettext('This console reports in other units than the page is written in.')",
        ofPlaces: "$gettext('of')",
        placesLive: "$gettext('live')",
        placesSilent: "$gettext('Nothing arriving from')",
        placesWrongUnit: "$gettext('Wrong units from')"
        #end if
      };
    </script>
    <script src="$asset('assets/live-poll.js')" defer></script>
    <script src="$asset('assets/live-status.js')" defer></script>
    #end if

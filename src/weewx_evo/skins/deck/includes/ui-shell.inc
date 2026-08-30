<!--prettier-ignore-->
#encoding UTF-8
#errorCatcher Echo
#import datetime
#set $base_path = $Extras.get("base_path", "./")

## The page frame: a header, a side panel, and the link that skips both.
##
## What this replaced: 470 lines of <bx-header>, <bx-side-nav> and inline
## scripts, plus two <script type="module"> tags fetching Carbon web
## components from a CDN. The markup below is <header> and <nav>, which
## every browser has understood for a decade, and the behaviour is in
## assets/deck.js.

<a class="visually-hidden" href="#main">$gettext("Skip to content")</a>

<header class="header">
  <button
    class="icon-button header__menu"
    type="button"
    data-menu-toggle
    aria-expanded="false"
    aria-controls="sidenav"
    aria-label="$gettext('Menu')"
  >
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <path d="M4 6h24v2H4zm0 9h24v2H4zm0 9h24v2H4z" />
    </svg>
  </button>

  <a class="header__brand" href="$get_base_path(path='index.html')">
    <!--prettier-ignore-->
    #if 'logo_image' in $Extras
    <img class="logo" src="$Extras['logo_image']" alt="$gettext('Logo')" />
    #else
      #include "includes/icons/deck.svg"
    #end if
    ## `$station.location` is *this place's* label once `Placed` is in the
    ## way, so a site page headed with it names one of the four sites it is
    ## listing. On a place page it is right and is what it has always been.
    <span class="header__station">#if $scope == 'site' then $site_title else $station.location#</span>
  </a>


  <div class="header__end">
    ## Whether the readings on this page are live, and how old they are.
    ## Only when a broker is configured: on a station without one it would
    ## be a permanent red badge saying nothing anybody can act on.
    #if $to_bool($Extras.get('live_push', 1))
    <div class="live-indicator live-indicator--waiting" id="live-indicator"
         role="status" aria-live="polite"
         title="$gettext('Waiting for the first reading.')">
      <span class="live-indicator__dot" aria-hidden="true"></span>
      <span class="live-indicator__label">$gettext('connecting')</span>
    </div>
    #end if
    ## A second set of these pages, in the other unit system. Only when one
    ## exists: a station publishing once has nothing to switch to, and a
    ## control that does nothing is worse than no control.
    ##
    ## A link, not a button. The other set is a different set of pages, so
    ## this is navigation -- and it works before any script has run, which a
    ## button toggling something would not.
    #if $Extras.get('units_other_path')
    <div class="unit-switch" role="group" aria-label="$gettext('Units')">
      <span class="unit-switch__here" aria-current="true">$Extras.get('units_own_label', '')</span>
      <a class="unit-switch__other"
         href="$Extras.units_other_path"
         data-units-switch="$Extras.get('units_other_label', '')"
         title="$gettext('Show this page in other units')"
        >$Extras.get('units_other_label', '')</a>
    </div>
    #end if
    <button
      class="icon-button"
      type="button"
      data-theme-toggle
      aria-label="$gettext('Switch theme')"
      title="$gettext('Switch theme')"
    >
      <svg class="theme-toggle__dark" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M13.5 5.41A15.08 15.08 0 0 0 25.1 23.61a11.11 11.11 0 0 1-7.98 3.39c-.14 0-.28.01-.42 0A11.09 11.09 0 0 1 13.5 5.41M14.98 3a1 1 0 0 0-.17.02A13.1 13.1 0 0 0 16.63 29c.16.01.33 0 .49 0a13.07 13.07 0 0 0 10.7-5.56 1.01 1.01 0 0 0-.78-1.56A13.08 13.08 0 0 1 15.89 4.38 1.01 1.01 0 0 0 14.98 3Z" />
      </svg>
      <svg class="theme-toggle__light" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M15 2h2v5h-2zM25 15h5v2h-5zM15 25h2v5h-2zM2 15h5v2H2zM6.85 5.37l3.5 3.51-1.41 1.41-3.51-3.5zM21.67 8.86l3.5-3.5 1.42 1.41-3.51 3.5zM23.15 21.67l3.5 3.5-1.41 1.42-3.5-3.51zM8.86 23.15l1.41 1.41-3.5 3.51-1.42-1.42z" />
        <path d="M16 10a6 6 0 1 0 6 6 6 6 0 0 0-6-6Zm0 10a4 4 0 1 1 4-4 4 4 0 0 1-4 4Z" />
      </svg>
    </button>
  </div>
</header>

<div class="scrim" hidden-until-found></div>

<div class="layout">
  #include "includes/sidenav.inc"

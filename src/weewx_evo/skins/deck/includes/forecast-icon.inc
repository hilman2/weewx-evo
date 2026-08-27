<!--prettier-ignore-->
#errorCatcher Echo
#encoding UTF-8
##
## One picture for one sky, from `$forecast_symbol`.
##
## The core names the weather and stops there on purpose: which file that is
## belongs to whoever draws the page, and mapping to one icon set in the core
## would make every other set unusable. This is Deck's half of that bargain.
##
## Spelled out rather than computed. A skin's icons are the part somebody
## replaces, and a chain they can read and edit beats a dictionary comprehension
## they have to work out first.
##
#set $symbol = $forecast_symbol
<span class="forecast-icon" data-symbol="$symbol">
#if $symbol == 'clear'
#include "includes/icons/forecast/CL.svg"
#else if $symbol == 'clear-night'
#include "includes/icons/moon.svg"
#else if $symbol == 'mostly-clear'
#include "includes/icons/forecast/FW.svg"
#else if $symbol == 'mostly-clear-night'
#include "includes/icons/forecast/B1.svg"
#else if $symbol == 'partly-cloudy'
#include "includes/icons/forecast/SC.svg"
#else if $symbol == 'partly-cloudy-night'
#include "includes/icons/forecast/B2.svg"
#else if $symbol == 'overcast'
#include "includes/icons/forecast/OV.svg"
#else if $symbol == 'fog'
#include "includes/icons/forecast/fog.svg"
#else if $symbol == 'drizzle'
#include "includes/icons/forecast/rain-drop.svg"
#else if $symbol == 'freezing-drizzle' or $symbol == 'freezing-rain'
#include "includes/icons/forecast/sleet.svg"
#else if $symbol == 'rain' or $symbol == 'heavy-rain'
#include "includes/icons/forecast/rain.svg"
#else if $symbol == 'showers' or $symbol == 'heavy-showers'
#include "includes/icons/forecast/rain--scattered.svg"
#else if $symbol == 'snow' or $symbol == 'heavy-snow'
#include "includes/icons/forecast/snow.svg"
#else if $symbol == 'snow-showers'
#include "includes/icons/forecast/snow--scattered.svg"
#else if $symbol == 'thunderstorm'
#include "includes/icons/forecast/thunderstorm--scattered.svg"
#else if $symbol == 'thunderstorm-hail'
#include "includes/icons/forecast/thunderstorm.svg"
#else
## An unknown code is a real one this skin has no picture for. A cloud says
## less than the right icon and a great deal more than an empty box.
#include "includes/icons/forecast/BK.svg"
#end if
</span>

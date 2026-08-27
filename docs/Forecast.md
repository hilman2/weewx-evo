# Forecast

`forecast/`. What is coming, from somebody who knows.

A weather station measures. A forecast is the other half of what people look at
a weather page for at all — and WeeWX has never had it in the core. Which is why
`weewx-DWD` exists, and why it has grown to ten data sources, two dependencies
outside the standard library, radar animation and pollen counts.

That growth is the argument for drawing a line here — not for not having it at
all.

## The line: three sources, and a fourth for America

| | |
|---|---|
| `open-meteo` | the world. No key, plain JSON, and it picks the best model for a place itself — ICON in Germany, ECMWF or GFS elsewhere. One source covers nearly everybody |
| `dwd` | Germany's own station forecast (MOSMIX). The point forecast for an actual place rather than a grid cell |
| `meteoalarm` | warnings for 38 European countries, in an Atom feed of CAP documents. The official aggregator |
| `dwd-warnings` | Germany's warnings in the DWD's own wording, which MeteoAlarm translates away |
| `nws` | the United States: warnings and a forecast in one API, with no key |

**Explicitly not included:** radar animation, map servers, pollen counts,
anything with a paid key. Each of those is a plugin's business, and the plugin
interface is the same one as for the [drivers](Drivers).

None of these sources needs an account.

## Where it goes: its own file, never the archive

That is this project's one rule, said again. `archive` is what WeeWX wrote and
has to carry on being able to read — a column with forecast temperatures in it
would be a lie that averages badly over years, and `archive_day_*` would happily
summarise the lie.

So: `forecast.sdb`, next to the archive, and everything about it is designed on
the basis that it is expendable.

- **Replaced, not accumulated.** A new run of a source deletes its previous one.
  Nobody wants yesterday's forecast for today, and keeping it turns a small file
  into a large one with no readers.
- **One table for the hours, one for the days, one for the warnings.** Not one
  wide one: a warning has nothing in common with a temperature, and a day is not
  an hour with different columns.
- **Deleting the file costs one download.** That is the definition of a cache
  and the reason nothing here needs a migration path.

Every row carries the name of its source, so two can run side by side and a page
can say which it means.

## Two kinds of failure, and they are not the same

**A failed fetch keeps the old forecast.** Not an empty one. A source that could
not be reached has told us nothing about the weather, and replacing yesterday's
good forecast with nothing turns a network hiccup into an empty page.

**An empty warnings feed is an answer.** MeteoAlarm delivers no entries when the
weather is calm, and that means: the warnings are over. So warnings are
**deliberately** replaced with nothing. Leaving an expired storm warning up on a
page is the one mistake here that could actually harm somebody.

The two are told apart by *where* they happen: an exception never reaches the
store, a successful fetch always does.

## The pitfalls of the sources

### Open-Meteo: the day stamp

Its day stamp is local midnight, expressed in UTC. The offset has to be
subtracted to get the actual moment. Without that a "day" in Berlin begins at
02:00, every daily figure hangs two hours off the wrong date — and it tips over
at the daylight-saving boundary.

`timeformat=unixtime` is used, because the default is local ISO strings with no
zone, and parsing those means knowing which zone the API settled on.

`timezone=auto` is still needed regardless: it decides where a day begins.

### MOSMIX: kelvin

`TTT` is `287.35`, not `14.2`. Every temperature in MOSMIX is absolute, and
reading one as Celsius gives a forecast of 287 degrees — which at least gets
noticed. Converted the wrong way round it would be −259.

The pressure is in pascals for the same reason, and the radiation in kJ/m² per
hour rather than in watts.

MOSMIX comes as KMZ: a zipped KML file, ISO-8859-1 encoded, around 350 kB per
station, with every value as a space-separated list. `zipfile` and `xml.etree`
are both in the standard library, so it only costs the code.

**A station identifier, not a coordinate.** MOSMIX is published per station, and
the nearest one is not derivable without the station list. So `check()` fetches
that list and names the five nearest — which is how somebody finds theirs.

### MeteoAlarm: a country feed is not a place

Germany's feed carries every warning for every district: 46 of them on an
ordinary morning. So a region has to be chosen, and nobody knows the region IDs
(`DE037`) by heart.

`check()` therefore lists what is in the feed right now, with names — which
makes the settings page's test button the way somebody finds their region,
rather than an afterthought of a validation detail.

Filtering goes by the area description **and** the ID, because "Kreis Plön" is
findable and `DE037` is not.

With no region, everything is kept. That is loud rather than quiet, and with a
warning that is the right direction: a page full of alerts for a whole country
gets noticed. A missing warning does not.

> **The old RSS feeds were switched off on 14 January 2026.** The Atom feeds
> carry the same data. Anything still pointing at `.../rss/...` has received
> nothing since — silently.

### NWS: a User-Agent is compulsory

`api.weather.gov` requires one that names the application, and answers 403
without it. That is unusual enough to be worth mentioning: the same request
works from a browser and not from a library, and that reads like a network
problem for an afternoon.

A point is also not a grid cell: everything goes through
`/points/{lat},{lon}` first. That mapping is stable for a fixed station, so it
is fetched once and remembered.

The forecast is prose — `"10 mph"`, `"Mostly Cloudy"` — and has to be parsed
back. That is lossy, and the reason Open-Meteo stays the default in America too.
What the NWS is indisputably best at is the warnings; the forecast is therefore
off by default.

## Weather codes

`codes.py`. Every source speaks a different dialect of "what the weather is
doing": Open-Meteo publishes a reduced WMO 4677 set, the DWD the full one, the
NWS English sentences. They are translated into WMO codes on the way in, so that
everything afterwards has one vocabulary.

**The words are English here and are translated in `language.py`** — the same
arrangement as with the moon phases and the compass points.

**The symbols are a name, not a picture.** `partly-cloudy-day` and nothing else.
Which file that is belongs to whoever draws the page: a skin brings its own
icons, and a mapping onto one particular set would make that skin's icons
unusable.

## What a skin can write

```
$forecast.now.outTemp                  the hour we are in
$forecast.now.text                     "Light rain"
$forecast.now.symbol                   "rain", for whatever icons
$forecast.hours[3].outTemp             four hours from now
$forecast.days[0].tempMax              today's maximum
$forecast.days[1].sunrise              tomorrow's sunrise
$forecast.warnings                     the official ones, worst first
$forecast.warning                      the worst one, or nothing
$forecast.updated                      when it was last fetched
$forecast.issued                       when the model ran
$forecast.ahead.days[0].tempMax        from the source called "ahead"
```

A forecast temperature comes back as the same `Value` as a measured one. So a
template formats both the same way, and `units.Target` converts both: a page in
Fahrenheit shows a metric forecast in Fahrenheit without knowing there are two
systems.

**A missing forecast is not an error.** On a station that started a minute ago
nothing has been fetched yet, and a template still has to render. Empty lists
and `Unknown` come back, and the miss is counted so that the feed can report it.

`$forecast.updated` and `$forecast.issued` are different questions: a page
saying "updated a minute ago" over a six-hour-old model run is lying politely.
Both numbers are there so that it does not have to.

## Configuration

Two sources is the ordinary arrangement, not the exception: one for the numbers
and one for the warnings, because no service does both well.

```toml
[forecast.ahead]
kind = "open-meteo"
days = 7

[forecast.warnings]
kind = "meteoalarm"
country = "germany"
region = "Kreis Freising"
minimum = "Moderate"
```

## Commands

```bash
weewx-evo forecast list             # what there is and what is configured
weewx-evo forecast check            # fetch once, store nothing
weewx-evo forecast run              # fetch now and store
weewx-evo forecast show --hours 12  # print what is stored
```

`check` does double duty: a MOSMIX source with no station identifier and a
MeteoAlarm source with no region both answer with the candidates rather than
with an error.

## Checking it

```bash
python tools/forecast_test.py
```

No network. Every fixture in it is a shortened copy of a real response — the
field names, the namespaces and the encodings are exactly what the services
send, because that is what parsing fails on.

→ [Units](Units) · [Feeds](Feeds) · [Uploads](Uploads)

"""What an operator can set on the Deck skin, and where the form comes from.

The skin has three kinds of setting and they live in three places, which is
not an accident.

**Named single values** -- forty of them, the ones somebody actually changes:
which readings get a tile, whether the wind rose counts in Beaufort, the
layout. Those are here, as `Option`s, and one entry makes the form field, the
validation, the comment in the written file and the line in `--explain` at
once. There is no second place to register one.

**Sets with sets in them** -- the diagram definitions, the gauges, the
tables. A form generator does one named value at a time, and a diagram is a
set of lines with a set of properties each. Those stay in `skin.conf`, for
the same reason plot definitions live in `plots.toml` rather than in the
settings.

**The words** -- labels, units, translations. Those belong to the skin's
language files, and an operator picking a language gets all of them at once.

An operator who sets nothing here gets what `skin.conf` says, which is a
working site. Anything set here goes on top of it.
"""

from ...options import Group, Option


def _archive_names():
    """Every measurement series this installation keeps, for a dropdown.

    Deferred rather than imported at the top: this file is also loaded
    straight off disk by `feeds.cheetah.skin_options`, and a skin's settings
    module has no business dragging the feed package in at import time.

    Called once per `all_schemas()`, from inside the form builder, so it sees
    the file the page is being built for. A list built outside that moment
    offers another file's places -- silently, because the value is then
    refused at startup as naming something that does not exist.
    """
    from ...feeds import archive_names

    return archive_names()

#: Readings a tile can be built for. Not a closed list -- a station with
#: `extraTemp9` names it and gets it -- but it is what the choice widget
#: offers, so the common case is clicking rather than typing.
COMMON = (
    "outTemp", "outHumidity", "barometer", "windSpeed", "windDir", "windGust",
    "windGustDir", "windrun", "rain", "rainRate", "snowDepth", "dewpoint",
    "windchill", "heatindex", "UV", "ET", "radiation", "appTemp", "cloudbase",
    "inTemp", "inHumidity", "pressure", "altimeter", "humidex",
    "lightning_strike_count",
)


#: The pages this skin publishes for a place, one word each. They are the
#: words `place_page` carries in `skin.conf`, and an operator narrowing a
#: five-place site to four pages picks from these.
PLACE_PAGES = (
    ("today", "Today"), ("yesterday", "Yesterday"), ("week", "Week"),
    ("month", "Month"), ("year", "Year"), ("statistics", "Statistics"),
    ("celestial", "Celestial"), ("sensors", "Sensor status"),
    ("monitor", "Computer monitor"),
    ("archive", "The month and year archive, and the NOAA reports"),
    ("app", "The offline page and the web app manifest"),
)


def _several() -> bool:
    """Whether this installation keeps more than one series.

    Asked the same way the dropdown asks it, from inside the form builder, so
    it sees the file the page is being built for.

    Wrong in the safe direction: where it cannot tell, it says yes and the
    settings appear. A setting that is shown and does nothing is a question
    somebody can answer; one that is hidden and needed cannot be found at
    all.
    """
    try:
        return len(_archive_names()) > 1
    except Exception:
        return True


def _shape(settings: dict | None) -> str:
    """What this feed will actually publish, in the addresses it will use.

    Read the way `CheetahFeed.narrow()` reads it, and for the same reason a
    place's colour is kept in `archives.toml` rather than in a skin: anything
    else here would be a second implementation of the rule that decides the
    published addresses, and the two would disagree on the day somebody
    changed one of them.

    The one sentence on this page that answers "what is this feed for". Two
    settings decide it, they sit far apart, and neither could say what the
    pair of them adds up to.
    """
    try:
        every = [name for name, _label in _archive_names()]
        home = str((settings or {}).get("archive") or "") or (
            every[0] if every else "")
        said = (settings or {}).get("places") or []
        if isinstance(said, str):
            said = [x.strip() for x in said.split(",") if x.strip()]
        shown = [str(x) for x in said if str(x) in every] or list(every)
        if home in shown:
            shown.remove(home)
        if home:
            shown.insert(0, home)
        if len(shown) < 2:
            return ("This feed publishes one place, at the root of its "
                    "directory: index.html, week.html, month.html and the "
                    "rest.")
        folders = ", ".join(f"/{one}/" for one in shown)
        return (f"As it stands this feed publishes {len(shown)} places: an "
                "overview and the comparison pages at the root of its "
                f"directory, then {folders}, each with the whole set of "
                "pages under it.")
    except Exception:
        # Rendered from inside form building, where an unguarded parse has
        # already taken a whole settings page down with a 500 -- and it was
        # the page holding the value that caused it.
        return ("This feed can carry several places: an overview at the "
                "root, comparison pages beside it, and each place in a "
                "folder of its own.")


def groups(settings: dict | None = None) -> list[Group]:
    """The skin's own settings, as the admin page and `--explain` see them.

    The three groups about places are left out where there is one, which is
    every installation that has not asked for a second. Ten settings about an
    overview, a board and comparison pages that do not exist is a settings
    page that grew for everybody so that a few could configure something --
    and two of the three groups do not even say what they are for.

    The precedent is on the archives page, which hides its own "Change" form
    until there is a file to change.
    """
    several = _several()
    return [
        *([Group("Also show these places",
              "This feed is about one place -- the one chosen under "
              "“Place” at the top of this page. It can carry the "
              "others as well. " + _shape(settings), (
            Option("places", "Places on this site", kind="list",
                   choices_from=_archive_names,
                   help="In this order, and the place at the top of this "
                        "page always comes first whether or not it is "
                        "ticked here. Empty means all of them, in the order "
                        "the places page lists. Leave it empty and add a "
                        "second place later, and this site starts showing "
                        "it."),
            Option("site_title", "What to call the site", kind="text",
                   help="The heading on the overview. Empty means the "
                        "station name from the settings -- not the name of "
                        "any one place, because an overview headed "
                        "\"Kirchdorf\" listing four places is a lie the "
                        "page cannot spot."),
            Option("place_pages", "Pages each place gets", kind="list",
                   choices=PLACE_PAGES, advanced=True,
                   help="Empty means all of them. Five places with every "
                        "page each is what goes up the FTP link every run."),
            Option("places_fold", "Fold the place list past", kind="int",
                   default=6, minimum=1, maximum=64, advanced=True,
                   unit="places",
                   help="Past this many, the side panel keeps them in a "
                        "closed disclosure so the sidebar stays four lines "
                        "tall."),
        ))] if several else []),


        *([Group("The overview page",
              "One row per place and one column per reading, at the root of "
              "the site. Rows rather than a grid of cards: places one under "
              "another is the layout where “where is it coldest” "
              "costs no work. There is no total row -- two thermometers "
              "reading 19 and 21 do not make 20 anywhere.", (
            Option("board_observations", "Columns", kind="list",
                   choices=tuple((n, n) for n in COMMON),
                   default=("outTemp", "outHumidity", "windSpeed", "rain",
                            "barometer"),
                   help="One column each, in this order. A column no place "
                        "records is left out rather than filled with "
                        "dashes."),
            Option("board_primary", "The reading everything else is about",
                   kind="choice", choices=tuple((n, n) for n in COMMON),
                   default="outTemp",
                   help="The one chart on the overview draws it, and the "
                        "spread rule below watches it."),
            Option("unusual_spread", "Say so when two places differ by",
                   kind="float", default=2.0, minimum=0.1,
                   help="In the unit the pages are shown in. A threshold "
                        "converted the wrong way is amber at 79 on a "
                        "Fahrenheit page and silent at 26."),
            Option("unusual_max", "At most this many lines", kind="int",
                   default=4, minimum=1, maximum=12, advanced=True,
                   help="Past four the list stops reading as news and "
                        "starts reading as a log."),
        ))] if several else []),


        *([Group("The comparison pages",
              "One page per period -- today, this week, this month, this "
              "year -- each putting the places side by side, figures above "
              "and charts below.", (
            Option("compare_spans", "Periods", kind="list",
                   choices=(("day", "Today"), ("week", "Week"),
                            ("month", "Month"), ("year", "Year")),
                   default=("day", "week", "month", "year"),
                   help="One page each. A period left out here still has "
                        "its charts; nothing links to them."),
            Option("compare_observations", "Readings", kind="list",
                   choices=tuple((n, n) for n in COMMON),
                   default=("outTemp", "outHumidity", "windSpeed", "rain"),
                   help="One row of the figures table and one chart each."),
        ))] if several else []),

        Group("Layout", "How a page is put together.", (
            Option("layout", "Layout", kind="choice", default="alternative",
                   choices=(("alternative", "Alternative -- tiles in a grid"),
                            ("classic", "Classic -- sections in a column")),
                   help="The alternative layout puts the current readings, "
                        "the gauges and the diagrams into one grid. The "
                        "classic one keeps the sections apart."),
            Option("default_theme", "Colours", kind="choice", default="auto",
                   choices=(("auto", "Follow the visitor's browser"),
                            ("light", "Light"), ("dark", "Dark")),
                   help="What a visitor sees before they choose. The page "
                        "has a switch either way, and remembers it."),
            Option("gauges_display", "Gauges", kind="choice",
                   default="before",
                   choices=(("before", "Above the diagrams"),
                            ("after", "Below the diagrams"),
                            ("none", "Not at all")),
                   help="Dials for the current readings."),
            Option("gauges_size", "Gauge size", kind="choice",
                   default="medium",
                   choices=(("small", "Small"), ("medium", "Medium"),
                            ("large", "Large"))),
        )),

        Group("Tiles", "Which readings get one, and what it says.", (
            Option("stat_tile_observations", "Readings with a tile",
                   kind="list", choices=tuple((n, n) for n in COMMON),
                   help="One tile each, in this order. A reading the "
                        "database does not have is skipped rather than "
                        "shown empty."),
            Option("table_tile_observations", "Readings in the table",
                   kind="list", choices=tuple((n, n) for n in COMMON),
                   advanced=True),
            Option("stat_tiles_show_min", "Show the minimum for",
                   kind="list", advanced=True,
                   help="A tile shows the maximum by default. These show the "
                        "minimum as well -- a temperature is interesting "
                        "both ways, a rain rate is not."),
            Option("stat_tiles_show_max", "Show only the maximum for",
                   kind="list", advanced=True),
            Option("stat_tiles_show_sum", "Show the total for",
                   kind="list", advanced=True,
                   help="Rain, evapotranspiration, wind run: the readings "
                        "where the total is the number that means "
                        "something."),
            Option("show_min_max_time_day", "Say when, on the day page",
                   kind="bool", default=False,
                   help="The time the day's high and low were reached, "
                        "under the value."),
            Option("show_min_max_time_yesterday", "Say when, yesterday",
                   kind="bool", default=False, advanced=True),
            Option("show_min_max_time_week", "Say when, on the week page",
                   kind="bool", default=False, advanced=True),
            Option("show_min_max_time_month", "Say when, on the month page",
                   kind="bool", default=False, advanced=True),
        )),

        Group("Temperature colour",
              "Tinting the temperature tile by how warm it is.", (
            Option("outTemp_stat_tile_color", "Tint the tile", kind="bool",
                   default=False),
            Option("outTemp_stat_tile_color_min", "Coldest", kind="int",
                   default=-20,
                   help="The temperature the coldest colour stands for, in "
                        "the unit the pages are shown in."),
            Option("outTemp_stat_tile_color_max", "Warmest", kind="int",
                   default=40),
            Option("outTemp_stat_tile_color_transparency", "Strength",
                   kind="float", default=0.35, advanced=True,
                   help="0 is no tint at all, 1 is the full colour."),
        )),

        Group("Wind", "", (
            Option("stat_tile_winddir_ordinal", "Compass points on tiles",
                   kind="bool", default=True,
                   help="NNW rather than 337 degrees."),
            Option("diagram_tile_winddir_ordinal",
                   "Compass points on diagrams", kind="bool", default=True),
            Option("windRose_show_beaufort", "Wind rose in Beaufort",
                   kind="bool", default=True,
                   help="Bands by force rather than by speed."),
            Option("windRose_legend_show_units", "Units in the wind rose key",
                   kind="bool", default=True, advanced=True),
            Option("windRose_colors", "Wind rose colours", kind="list",
                   advanced=True,
                   help="One colour per band, calmest first. Six of them by "
                        "default."),
        )),

        Group("Records and climatology",
              "The pages that count days rather than readings.", (
            Option("climatological_days", "Days to count", kind="list",
                   choices=(("rainDays", "Rain days"),
                            ("summerDays", "Summer days"),
                            ("hotDays", "Hot days"),
                            ("desertDays", "Desert days"),
                            ("tropicalNights", "Tropical nights"),
                            ("stormDays", "Storm days"),
                            ("iceDays", "Ice days"),
                            ("frostDays", "Frost days"),
                            ("snowDays", "Snow days"),
                            ("thunderDays", "Thunder days"),
                            ("heavyRainDays", "Heavy rain days (10 mm)"),
                            ("veryHeavyRainDays", "Very heavy rain (20 mm)"),
                            ("heatingDays", "Heating days")),
                   help="Named thresholds, counted per month and per year. "
                        "The thresholds are the German weather service's: a "
                        "rain day is 0.1 mm, a summer day is 25 C, a storm "
                        "day is a gust of 8 Beaufort. They overlap on "
                        "purpose -- a desert day is a hot day as well -- so "
                        "there is no total, and the last row is how many "
                        "days the period holds. A reading this station does "
                        "not record is left out rather than counted as "
                        "zero."),
            Option("climatological_days_per_month",
                   "Break them down by month", kind="bool", default=True),
            Option("climatogram_enable_stats", "Climatogram on the year page",
                   kind="bool", default=True, advanced=True),
            Option("climatogram_enable_year_stats",
                   "Climatogram on the statistics page", kind="bool",
                   default=True, advanced=True),
            Option("show_last_rain", "When it last rained", kind="bool",
                   default=True),
            Option("show_most_days_with_rain", "Longest wet spell",
                   kind="bool", default=True, advanced=True),
            Option("show_most_days_without_rain", "Longest dry spell",
                   kind="bool", default=True, advanced=True),
            Option("show_most_rain_within_one_day", "Wettest day",
                   kind="bool", default=True, advanced=True),
        )),

        Group("Sensor status",
              "The page about the hardware rather than the weather.", (
            Option("sensor_diagram_period", "Period", kind="choice",
                   default="week",
                   choices=(("day", "Day"), ("week", "Week"),
                            ("month", "Month"), ("year", "Year"))),
            Option("sensor_stat_tile_observations", "Readings with a tile",
                   kind="list", advanced=True),
            Option("sensor_diagram_observations", "Readings with a diagram",
                   kind="list", advanced=True),
            Option("sensor_table_observations", "Readings in the table",
                   kind="list", advanced=True),
            Option("sensor_battery_status", "Battery readings", kind="list",
                   advanced=True,
                   help="Shown as good or low rather than as a number."),
        )),

        Group("Computer monitor",
              "For a station that also records what the machine is doing.", (
            Option("computer_monitor_diagram_period", "Period", kind="choice",
                   default="week",
                   choices=(("day", "Day"), ("week", "Week"),
                            ("month", "Month"), ("year", "Year"))),
            Option("computer_monitor_stat_tile_observations",
                   "Readings with a tile", kind="list", advanced=True),
            Option("computer_monitor_diagram_observations",
                   "Readings with a diagram", kind="list", advanced=True),
            Option("computer_monitor_table_observations",
                   "Readings in the table", kind="list", advanced=True),
        )),
    ]

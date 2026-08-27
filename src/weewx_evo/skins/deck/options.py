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


def groups() -> list[Group]:
    """The skin's own settings, as the admin page and `--explain` see them."""
    return [
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

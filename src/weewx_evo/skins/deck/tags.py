#
"""The tags the Deck skin adds to a page.

A skin's own code: `$get_diagram_data(...)`, `$get_stat_tile(...)` and
the rest of what its templates ask for. Named in `skin.conf` under
`search_list_extensions`, handed the generator, and asked what it wants
to add.

Forked from weewx-wdc by David Baetge, GPL v3, and still mostly his
work. See README.md and CHANGES.md beside this file.

It imports from `weewx_evo.skinkit` by name. A skin from outside gets
WeeWX's names put into `sys.modules` for it; this one does not need
that, because it is ours.
"""

#
#    Copyright (c) 2023 David Baetge <david.baetge@gmail.com>,
#      Vince Skahan (last_rain and time_since_last_rain),
#      Pat O'Brien (Consecutive Days With/Without Rain)
#
#    Changed by the weewx-evo project. See CHANGES.md beside this file.
#
#    Distributed under the terms of the GNU Public License (GPLv3)
#
import calendar
import datetime
import json
import logging
import os
import sqlite3
import time

from weewx_evo import skinkit
from weewx_evo.skinkit import (
    ObsInfoHelper,
    SearchList,
    TimeSpan,
    UnitInfoHelper,
    ValueHelper,
    accumulateLeaves,
    beaufort,
    kph_to_knot,
    mph_to_knot,
    mps_to_knot,
    rounder,
    search_up,
    startOfArchiveDay,
    to_bool,
    to_int,
)
from weewx_evo.skinkit import (
    timespan_binder as TimespanBinder,  # noqa: N812 -- WeeWX's name
)

log = logging.getLogger(__name__)


def logdbg(msg):
    log.debug(msg)


def loginf(msg):
    log.info(msg)


def logerr(msg):
    log.error(msg)


class RainTags(SearchList):
    """ "
    Code for last_rain and time_since_last_rain is taken
    (and slightly modified) from
    https://github.com/vinceskahan/vds-weewx-lastrain-extension

    reused massively from wdSearchX3.py in weewx-wd 1.0 at Gary's suggestion

    some code also reused_from/stolen_from/insulting weewx station.py
    per Tom's suggestion

    Basic concpet of most_days_with_rain and most_days_without_rain is partially
    copied from https://github.com/poblabs/weewx-belchertown
    """

    def __init__(self, generator):
        SearchList.__init__(self, generator)

    def get_extension_list(self, timespan, db_lookup):
        """Returns a search list extension with datetime of last rain and secs since then.

        Parameters:
          timespan: An instance of weeutil.weeutil.TimeSpan. This will
                    hold the start and stop times of the domain of
                    valid times.

          db_lookup: This is a function that, given a data binding
                     as its only parameter, will return a database manager
                     object.

        Returns:
          last_rain:            A ValueHelper containing the datetime of the last rain
          time_since_last_rain: A ValueHelper containing the seconds since last rain
          most_days_with_rain:  A dict containing
            start                   A ValueHelper containing the datetime of the start of the period
            end                     A ValueHelper containing the datetime of the end of the period
            amount                  A ValueHelper containing the amount of rain in the period
            days_with_rain          The number of days with rain (raw int value)
            days_with_rain_delta    A ValueHelper containing the number of seconds in the period
          most_days_without_rain: A dict containing
            start                   A ValueHelper containing the datetime of the start of the period
            end                     A ValueHelper containing the datetime of the end of the period
            days_without_rain       The number of days without rain (raw int value)
            days_without_rain_delta A ValueHelper containing the number of seconds in the period
        """

        wx_manager = db_lookup()

        ##
        # Get date and time of last rain
        ##
        # Returns unix epoch of archive period of last rain
        ##
        # Result is returned as a ValueHelper so standard Weewx formatting
        # is available eg $last_rain.format("%d %m %Y")
        ##

        # Get ts for day of last rain from statsdb
        # Value returned is ts for midnight on the day the rain occurred
        #
        # `getSql` answers None where there is no such table -- an archive
        # whose daily summaries have not been built yet, which is every
        # freshly imported one. Reaching into that None threw, the whole
        # extension was dropped, and twelve pages then failed on tags it
        # would have supplied. One missing table cost half the site.
        try:
            _row = wx_manager.getSql(
                "SELECT MAX(dateTime) FROM archive_day_rain WHERE sum > 0")
        except sqlite3.Error:
            _row = None

        last_rain_ts = _row[0] if _row else None
        # The day table says which day it last rained. Ask the archive for
        # the record inside that day, so the answer is a time and not a
        # midnight. A database with no rain in it at all has neither.
        if last_rain_ts is not None:
            try:
                _row = wx_manager.getSql(
                    "SELECT MAX(dateTime) FROM archive "
                    "WHERE rain > 0 AND dateTime > ? AND dateTime <= ?",
                    (last_rain_ts, last_rain_ts + 86400),
                )
                last_rain_ts = _row[0]
            except sqlite3.Error:
                last_rain_ts = None

        # Wrap our ts in a ValueHelper
        last_rain_vt = (last_rain_ts, "unix_epoch", "group_time")
        last_rain_vh = ValueHelper(
            last_rain_vt, formatter=self.generator.formatter, converter=self.generator.converter
        )

        # next idea stolen with thanks from weewx station.py
        # note this is delta time from 'now' not the last weewx db time
        #  - weewx used time.time() but weewx-wd suggests timespan.stop()
        delta_time = time.time() - last_rain_ts if last_rain_ts else None

        # Wrap our ts in a ValueHelper
        delta_time_vt = (delta_time, "second", "group_deltatime")

        last_rain_delta_time_vh = ValueHelper(
            delta_time_vt,
            context="long_delta",
            formatter=self.generator.formatter,
            converter=self.generator.converter,
        )

        ##
        # Get date and value of most consecutive days with rain
        ##
        at_days_with_rain_total = 0
        at_days_with_rain_total_amount = 0
        at_days_without_rain_total = 0
        at_days_with_rain_output = []
        at_days_without_rain_output = []
        at_rain_query = wx_manager.genSql(
            "SELECT dateTime, sum FROM archive_day_rain WHERE count > 0;"
        )

        # Create empty list and append at_rain_query rows.
        rain_query_list = []
        years = []
        with_rain_period = None
        without_rain_period = None

        for row in at_rain_query:
            rain_query_list.append(row)
            # Get all years from records.
            year = datetime.datetime.fromtimestamp(row[0]).strftime("%Y")
            if year not in years:
                years.append(year)

        for index in range(len(rain_query_list)):
            row = rain_query_list[index]
            # Original MySQL way: CASE WHEN sum!=0 THEN @total+1 ELSE 0 END
            # pprint.pprint(row)
            if row[1] != 0:
                with_period_end = False
                at_days_with_rain_total += 1
                at_days_with_rain_total_amount = at_days_with_rain_total_amount + row[1]

                # Create rain period if not exists.
                if at_days_with_rain_total == 1:
                    with_rain_period = {
                        "start": row[0],
                        "end": row[0],
                        "days_with_rain": at_days_with_rain_total,
                        "amount": row[1],
                    }

                # Update period
                if at_days_with_rain_total > 1:
                    with_rain_period["end"] = row[0]
                    with_rain_period["days_with_rain"] = at_days_with_rain_total
                    with_rain_period["amount"] = at_days_with_rain_total_amount

            else:
                at_days_with_rain_total = 0
                at_days_with_rain_total_amount = 0
                with_period_end = True

            # Original MySQL way: CASE WHEN sum=0 THEN @total+1 ELSE 0 END
            if row[1] == 0:
                without_period_end = False
                at_days_without_rain_total += 1

                # Create rain period if not exists.
                if at_days_without_rain_total == 1:
                    without_rain_period = {
                        "start": row[0],
                        "end": row[0],
                        "days_without_rain": at_days_without_rain_total,
                    }

                # Update period
                if at_days_without_rain_total > 1:
                    without_rain_period["end"] = row[0]
                    without_rain_period["days_without_rain"] = at_days_without_rain_total
            else:
                at_days_without_rain_total = 0
                without_period_end = True

            # Rain period ended, append to output.
            if with_rain_period is not None and with_period_end is True:
                # Tranform raw amount value to ValueHelper.
                rain_vt = (with_rain_period["amount"], "inch", "group_rain")
                rain_vh = ValueHelper(
                    rain_vt, formatter=self.generator.formatter, converter=self.generator.converter
                )

                with_rain_period["amount"] = rain_vh

                # Transform raw days_with_rain value to ValueHelper.
                delta_time = with_rain_period["end"] - with_rain_period["start"] + 86400
                delta_time_vt = (delta_time, "second", "group_deltatime")
                delta_time_vh = ValueHelper(
                    delta_time_vt,
                    formatter=self.generator.formatter,
                    converter=self.generator.converter,
                )
                with_rain_period["days_with_rain_delta"] = delta_time_vh

                # Tranform raw start and end value to ValueHelper.
                start_vt = (with_rain_period["start"], "unix_epoch", "group_time")
                start_vh = ValueHelper(
                    start_vt, formatter=self.generator.formatter, converter=self.generator.converter
                )
                end_vt = (with_rain_period["end"], "unix_epoch", "group_time")
                end_vh = ValueHelper(
                    end_vt, formatter=self.generator.formatter, converter=self.generator.converter
                )

                with_rain_period["start"] = start_vh
                with_rain_period["end"] = end_vh

                at_days_with_rain_output.append(with_rain_period)
                with_rain_period = None

            # No rain period ended, append to output.
            if without_rain_period is not None and without_period_end is True:
                # Transform raw days_with_rain value to ValueHelper.
                delta_time = without_rain_period["end"] - without_rain_period["start"] + 86400
                delta_time_vt = (delta_time, "second", "group_deltatime")
                delta_time_vh = ValueHelper(
                    delta_time_vt,
                    formatter=self.generator.formatter,
                    converter=self.generator.converter,
                )
                without_rain_period["days_without_rain_delta"] = delta_time_vh

                # Tranform raw start and end value to ValueHelper.
                start_vt = (without_rain_period["start"], "unix_epoch", "group_time")
                start_vh = ValueHelper(
                    start_vt, formatter=self.generator.formatter, converter=self.generator.converter
                )
                end_vt = (without_rain_period["end"], "unix_epoch", "group_time")
                end_vh = ValueHelper(
                    end_vt, formatter=self.generator.formatter, converter=self.generator.converter
                )

                without_rain_period["start"] = start_vh
                without_rain_period["end"] = end_vh

                at_days_without_rain_output.append(without_rain_period)
                without_rain_period = None

        if len(at_days_with_rain_output) > 0:
            at_days_with_rain = max(at_days_with_rain_output, key=lambda x: x["days_with_rain"])

            # Add values for all years.
            for year in years:
                at_days_with_rain_output_per_year = list(
                    filter(
                        lambda x: (
                            datetime.datetime.fromtimestamp(x["start"].raw).strftime("%Y") == year
                        ),
                        at_days_with_rain_output,
                    )
                )

                if len(at_days_with_rain_output_per_year) > 0:
                    at_days_with_rain[year] = max(
                        at_days_with_rain_output_per_year, key=lambda x: x["days_with_rain"]
                    )
                else:
                    at_days_with_rain[year] = None

        else:
            at_days_with_rain = None

        if len(at_days_without_rain_output) > 0:
            at_days_without_rain = max(
                at_days_without_rain_output, key=lambda x: x["days_without_rain"]
            )

            # Add values for all years.
            for year in years:
                at_days_without_rain_output_per_year = list(
                    filter(
                        lambda x: (
                            datetime.datetime.fromtimestamp(x["start"].raw).strftime("%Y") == year
                        ),
                        at_days_without_rain_output,
                    )
                )

                if len(at_days_without_rain_output_per_year) > 0:
                    at_days_without_rain[year] = max(
                        at_days_without_rain_output_per_year, key=lambda x: x["days_without_rain"]
                    )
                else:
                    at_days_without_rain[year] = None
        else:
            at_days_without_rain = None

        search_list_extension = {
            "last_rain": last_rain_vh,
            "time_since_last_rain": last_rain_delta_time_vh,
            "most_days_with_rain": at_days_with_rain,
            "most_days_without_rain": at_days_without_rain,
        }

        return [search_list_extension]


class GeneralUtil(SearchList):
    def __init__(self, generator):
        SearchList.__init__(self, generator)
        self.skin_dict = generator.skin_dict

        try:
            time_format_dict = self.skin_dict["Units"]["TimeFormats"]
            to_date_dict = self.skin_dict["CheetahGenerator"]["ToDate"]
        except KeyError:
            time_format_dict = {}
            to_date_dict = {}

        self.time_format = time_format_dict
        self.generator_to_date = to_date_dict

    def format_raw_value(self, value, obs):
        """
        Returns a ValueHelper for a raw value and an obs type.

        Args:
            value (float): The value
            obs (string): The observation
        """
        target_unit_t = self.generator.converter.getTargetUnit(obs_type=obs)
        value_vt = (value, target_unit_t[0], target_unit_t[1])

        return ValueHelper(value_t=value_vt, formatter=self.generator.formatter)

    def get_software_obs(self):
        """
        Get the observations provided by software (weewx calculations), was
        added because the has_data check fails for GTS, seasonGDD or yearGDD.

        Returns:
            list: The software observations
        """
        return list(self.generator.derived)

    def spell(self, when, shape=None):
        """A moment, written the way this language writes one.

        `$spell($week.start.raw, $get_time_format_dict['week'])`.

        Python's `strftime` answers `%x`, `%X`, `%b` and `%B` out of the
        process locale, and the image sets none -- so a German page said
        `08/29/26` and `May`. This asks the language instead, which is
        where the words and the date order are.

        Takes a timestamp, a `datetime`, or one of our values.
        """
        import datetime as _datetime

        if hasattr(when, "raw"):
            when = when.raw
        if isinstance(when, _datetime.datetime):
            when = when.timestamp()
        if when is None:
            return ""

        shape = shape or self.get_time_format_dict.get("current", "%x %X")
        spoken = getattr(self.generator.target, "language", None)
        if spoken is not None:
            return spoken.spell(shape, float(when))
        return time.strftime(shape, time.localtime(float(when)))

    def month_word(self, month, long=False):
        """The short name of a month, in the page's language.

        `calendar.month_abbr` follows the process locale, which is unset in
        the shipped image -- so a German year table was headed Jan, Feb,
        Mar, May.
        """
        spoken = getattr(self.generator.target, "language", None)
        if spoken is not None:
            words = spoken.months(long=long)
            if 1 <= int(month) <= len(words):
                return words[int(month) - 1]
        import calendar

        return (calendar.month_name if long else calendar.month_abbr)[int(month)]

    def weekday_names(self):
        """The seven days, short, starting on Sunday.

        Sunday first because that is the order a calendar heat map indexes
        them in, whatever day it chooses to draw first.
        """
        spoken = getattr(self.generator.target, "language", None)
        words = list(spoken.days()) if spoken is not None else []
        if len(words) != 7:
            return ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
        # `language.days()` starts on Monday, the way `tm_wday` counts.
        return tuple([words[6]] + words[:6])

    def month_names(self):
        """The twelve months, short, in the page's language."""
        return tuple(self.month_word(n) for n in range(1, 13))

    def get_locale(self):
        """
        The locale the browser code formats dates and numbers in.

        One setting decides what language the pages are in, and this follows
        it. The bundle knows five; anything else gets the closest it has.

        Returns:
            str: A BCP 47 tag, eg `de-DE`
        """
        named = self.skin_dict["DisplayOptions"].get("date_time_locale")
        if named:
            return named
        known = {"de": "de-DE", "it": "it-IT", "nl": "nl-NL", "en": "en-US"}
        spoken = str(self.generator.language or "en").replace("_", "-")
        if spoken in ("en-GB", "en_GB"):
            return "en-GB"
        return known.get(spoken.split("-")[0], "en-US")

    def getValueHelper(self, value_vt):  # noqa: N802 -- WeeWX's name
        """
        Get a value helper for a value_vt.

        Args:
            value_vt (tuple): A value tuple

        Returns:
            obj: A value helper
        """
        value_vt = self.generator.converter.convert(value_vt)
        return ValueHelper(value_t=value_vt, formatter=self.generator.formatter)

    def get_base_path(self, *args, **kwargs):
        """
        Get the base path + a given path.

        Args:
            path (string): The path

        Returns:
            str: The base path
        """
        path = kwargs.get("path")
        base_path = self.skin_dict["Extras"].get("base_path", "/")

        if path is None or path == "/":
            return base_path

        return base_path + path

    def asset(self, path):
        """The base path plus a file, with a mark that changes when it does.

        Without one, a stylesheet is cached for as long as the web server
        says -- an hour here -- and a page served in that window has new
        markup and the old rules. It does not look like a caching problem: it
        looks like the design broke. Seven day tiles came out as native grey
        buttons because the HTML had become `<button>` and the CSS that
        strips a button back had not arrived yet.

        Eight characters of the file's own content. A version number would
        not do: the file changes far more often than the version does, and
        that is exactly the window this is for.
        """
        import hashlib
        import os.path

        base = self.get_base_path(path=path)
        try:
            found = os.path.join(self.generator.skin_dir, path)
            with open(found, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()[:8]
        except Exception:
            # A file this skin does not ship, or one it cannot read. The
            # link still has to work; it just goes unmarked.
            return base
        return f"{base}?v={digest}"

    def show_yesterday(self):
        if "yesterday" in self.generator_to_date:
            return True

        return False

    def get_context_key_from_time_span(self, start_ts, end_ts):
        """
        Get the context key from a given time span.

        Args:
            start_ts (int): The start timestamp
            end_ts (int): The end timestamp

        Returns:
            str: The context key
        """
        if start_ts == end_ts:
            return "day"

        if end_ts - start_ts <= 86400:
            return "day"

        # Up to 2 weeks.
        if end_ts - start_ts <= 1209600:
            return "week"

        # Up to 3 months.
        if end_ts - start_ts <= 8035200:
            return "month"

        if end_ts - start_ts <= 31536000:
            return "year"

        return "alltime"

    def show_sensor_page(self):
        if "sensor_status" in self.generator_to_date:
            return True

        return False

    def show_cmon_page(self):
        if "computer_monitor" in self.generator_to_date:
            return True

        return False

    def get_time_format_dict(self):
        return self.time_format

    def get_unit_label(self, unit):
        """
        Get the unit label for a given unit.
        @see https://www.weewx.com/docs/customizing.htm#units

        Args:
            unit (string): The unit

        Returns:
            string: The unit label
        """
        try:
            unit_label = self.generator.formatter.unit_label_dict[unit]
            if isinstance(unit_label, list):
                # Singular vs Plural label.
                if len(unit_label) == 2:
                    return unit_label[1]
                else:
                    return unit_label[0]
            else:
                return unit_label
        except KeyError:
            if unit is not None:
                return " " + unit
            else:
                return ""

    def get_unit_for_obs(
        self, observation, observation_key, context, combined=None, combined_key=None
    ):
        """
        Get the unit for a given observation.

        Args:
            observation (string): The observation
            observation_key (string): The observation key (e.g. outTemp), this
              is only different from observation if it's a custom observation
              from a custom data_biding.
            context (string): The context
            combined (dict): The combined config
            combined_key (string): The combined diagram key

        Returns:
            string: The unit
        """
        # Combined diagram.
        if combined is not None:
            try:
                unit = search_up(
                    self.skin_dict["DisplayOptions"]["diagrams"][context]["observations"][
                        combined_key
                    ]["obs"][observation],
                    "unit",
                    None,
                )
            except KeyError:
                unit = None

            if unit is not None:
                return unit

            try:
                unit = search_up(
                    self.skin_dict["DisplayOptions"]["diagrams"]["combined_observations"][
                        combined_key
                    ]["obs"][observation],
                    "unit",
                    None,
                )
            except KeyError:
                unit = None

            if unit is not None:
                return unit

        # Context.
        try:
            unit = self.skin_dict["DisplayOptions"]["diagrams"][context]["observations"][
                observation
            ]["unit"]
        except KeyError:
            unit = None

        if unit is not None:
            return unit

        try:
            return self.skin_dict["DisplayOptions"]["diagrams"][observation]["unit"]
        except KeyError:
            unit = self.generator.converter.getTargetUnit(obs_type=observation_key)
            return unit[0]

    def get_windrose_enabled(self):
        """
        Check if the windrose is enabled.

        Returns:
            bool: True if the windrose is enabled, False otherwise.
        """
        try:
            windrose_day_enabled = False
            if "windRose" in self.skin_dict["DisplayOptions"]["diagrams"]["day"]["observations"]:
                windrose_day_enabled = True
        except KeyError:
            windrose_day_enabled = False

        try:
            windrose_week_enabled = False
            if "windRose" in self.skin_dict["DisplayOptions"]["diagrams"]["week"]["observations"]:
                windrose_week_enabled = True
        except KeyError:
            windrose_week_enabled = False

        try:
            windrose_month_enabled = False
            if "windRose" in self.skin_dict["DisplayOptions"]["diagrams"]["month"]["observations"]:
                windrose_month_enabled = True
        except KeyError:
            windrose_month_enabled = False

        try:
            windrose_year_enabled = False
            if "windRose" in self.skin_dict["DisplayOptions"]["diagrams"]["year"]["observations"]:
                windrose_year_enabled = True
        except KeyError:
            windrose_year_enabled = False

        try:
            windrose_alltime_enabled = False
            if (
                "windRose"
                in self.skin_dict["DisplayOptions"]["diagrams"]["alltime"]["observations"]
            ):
                windrose_alltime_enabled = True
        except KeyError:
            windrose_alltime_enabled = False

        return (
            windrose_day_enabled
            or windrose_week_enabled
            or windrose_month_enabled
            or windrose_year_enabled
            or windrose_alltime_enabled
        )

    def get_icon(
        self, observation, use_diagram_config=False, use_combined_diagram_config=False, context=None
    ):
        """
        Returns an include path for an icon based on the observation
        # @see https://www.weewx.com/docs/customizing.htm#units
        # @see https://carbondesignsystem.com/guidelines/icons/library/

        Args:
            observation (string): The observation
            use_diagram_config (bool): Use the diagram config
            use_combined_diagram_config (bool): Use the combined diagram config
            context (string): The context

        Returns:
            str: An icon include path | 'none' | 'unset'
        """
        icon_path = "includes/icons/"

        if use_diagram_config and context is not None:
            try:
                icon = self.generator.skin_dict["DisplayOptions"]["diagrams"][context][
                    "observations"
                ][observation]["icon"]
            except KeyError:
                icon = False

            if icon or icon == "none":
                return icon

            try:
                icon = self.generator.skin_dict["DisplayOptions"]["diagrams"][observation]["icon"]
            except KeyError:
                icon = False

            if icon or icon == "none":
                return icon

        if use_combined_diagram_config and context is not None:
            try:
                icon = self.generator.skin_dict["DisplayOptions"]["diagrams"][context][
                    "observations"
                ][observation]["icon"]
            except KeyError:
                icon = False

            if icon and icon != "none":
                return icon

            if icon and icon == "none":
                return "unset"

            try:
                icon = self.generator.skin_dict["DisplayOptions"]["diagrams"][
                    "combined_observations"
                ][observation]["icon"]
            except KeyError:
                icon = False

            if icon and icon != "none":
                return icon

            if icon and icon == "none":
                return "unset"

        try:
            icon_config = self.generator.skin_dict["DisplayOptions"]["Icons"].get(observation, None)
        except KeyError:
            icon_config = None

        if icon_config is not None:
            return icon_config

        # Default icon set
        if observation == "outTemp" or observation == "inTemp":
            return icon_path + "temp.svg"

        elif observation == "outHumidity" or observation == "inHumidity":
            return icon_path + "humidity.svg"

        elif observation == "barometer" or observation == "pressure" or observation == "altimeter":
            return icon_path + "barometer.svg"

        elif (
            observation == "no2"
            or observation == "pm1_0"
            or observation == "pm2_5"
            or observation == "pm10_0"
        ):
            return icon_path + "mask.svg"

        elif observation == "windSpeed":
            return icon_path + "wind-speed.svg"

        elif observation == "windGust":
            return icon_path + "wind-gust.svg"

        elif observation == "windDir" or observation == "windGustDir":
            return icon_path + "wind-direction.svg"

        elif observation == "rain":
            return icon_path + "rain.svg"

        elif observation == "rainRate":
            return icon_path + "rain-rate.svg"

        elif observation == "dewpoint" or observation == "dewpoint1" or observation == "inDewpoint":
            return icon_path + "dew-point.svg"

        elif observation == "windchill":
            return icon_path + "wind-chill.svg"

        elif (
            observation == "heatindex"
            or observation == "heatindex1"
            or observation == "humidex"
            or observation == "humidex1"
        ):
            return icon_path + "heat-index.svg"

        elif observation == "UV":
            return icon_path + "uv.svg"

        elif observation == "ET":
            return icon_path + "et.svg"

        elif observation == "noise":
            return icon_path + "noise.svg"

        elif observation == "forecast":
            return icon_path + "forecast.svg"

        elif (
            observation == "radiation"
            or observation == "luminosity"
            or observation == "maxSolarRad"
            or observation == "sunshineDur"
        ):
            return icon_path + "radiation.svg"

        elif observation == "appTemp" or observation == "appTemp1":
            return icon_path + "app-temp.svg"

        elif observation == "cloudbase":
            return icon_path + "cloud-base.svg"

        elif observation == "snowDepth":
            return icon_path + "snow-depth.svg"

        elif observation == "snowMoisture":
            return icon_path + "snow-moist.svg"

        elif observation == "windrun":
            return icon_path + "wind-run.svg"

        elif observation == "snow" or observation == "snowRate":
            return icon_path + "snow.svg"

        elif observation == "hail" or observation == "hailRate":
            return icon_path + "hail.svg"

        elif observation == "cloudcover":
            return icon_path + "forecast/B2.svg"

        elif "leaf" in observation:
            return icon_path + "leaf.svg"

        elif "signal" in observation or observation == "rxCheckPercent":
            return icon_path + "signal.svg"

        elif "Voltage" in observation:
            return icon_path + "voltage.svg"

        elif "batterystatus" in observation.lower() or "batteryvoltage" in observation.lower():
            return icon_path + "battery.svg"

        elif "lightning" in observation:
            return icon_path + "lightning.svg"

        elif "soilMoist" in observation:
            return icon_path + "soil-moist.svg"

        elif "soilTemp" in observation:
            return icon_path + "soil-temp.svg"

        elif "Temp" in observation:
            return icon_path + "temp.svg"

        elif "Humid" in observation:
            return icon_path + "humidity.svg"

        return "none"

    def get_color(self, observation, context, *args, **kwargs):
        """
        Color settings for observations.

        Args:
            observation (string): The observation
            context (string): The context

        Returns:
            str: A color string
        """
        diagrams_config = self.skin_dict["DisplayOptions"]["diagrams"]

        combined = kwargs.get("combined", False)
        combined_obs = kwargs.get("combined_obs")
        combined_obs_key = kwargs.get("combined_obs_key")

        try:
            color = search_up(diagrams_config[context]["observations"][observation], "color", None)
            if color is not None:
                return color
        except KeyError:
            try:
                color = search_up(diagrams_config[context], "color", None)
                if color is not None:
                    return color
            except KeyError:
                color = None

        # For combined diagrams, observation = temp_min_max_avg
        # and combined_obs = outTemp, combined_obs_key = outTemp_max
        if combined and combined_obs_key is not None and combined_obs is not None:
            try:
                color = search_up(
                    diagrams_config[context]["observations"][combined_obs], "color", None
                )

                if color is not None:
                    return color
            except KeyError:
                color = None

            try:
                color = search_up(
                    diagrams_config["combined_observations"][observation]["obs"][combined_obs_key],
                    "color",
                    None,
                )

                if color is not None:
                    return color
            except KeyError:
                color = None

            try:
                color = diagrams_config[combined_obs]["color"]

                if color is not None:
                    return color
            except KeyError:
                color = None

        if color is not None:
            return color

        if observation in diagrams_config and "color" in diagrams_config[observation]:
            return diagrams_config[observation]["color"]

        if "humidity" in observation.lower():
            return "#0099CC"

        if observation == "barometer" or observation == "pressure" or observation == "altimeter":
            return "#666666"

        if observation == "dewpoint":
            return "#5F9EA0"

        if observation == "appTemp":
            return "#C41E3A"

        if observation == "windchill":
            return "#0099CC"

        if observation == "heatindex":
            return "#610000"

        if observation == "windSpeed":
            return "#ffc000"

        if observation == "windGust":
            return "#666666"

        if observation == "radiation":
            return "#ff8c00"

        if observation == "UV":
            return "#e61919"

        if observation == "cloudbase":
            return "#92b6f0"

        if observation == "ET":
            return "#E97451"

        if observation == "rain":
            return "#0198E1"

        if observation == "rainRate":
            return "#0a6794"

        if "temp" in observation.lower():
            return "#8B0000"

        return "#161616"

    @staticmethod
    def get_time_span_from_context(context, day, week, month, year, alltime, yesterday):
        """
        Get tag for use in templates.

        Args:
            context (string): The time range
            day: Daily TimeSpanBinder
            week: Weekly TimeSpanBinder
            month: Monthly TimeSpanBinder
            year: Yearly TimeSpanBinder
            alltime: Alltime TimeSpanBinder
            yesterday: Yesterday TimeSpanBinder

        Returns:
            obj: TimeSpanBinder
        """
        if context == "day":
            return day

        if context == "week":
            return week

        if context == "month":
            return month

        if context == "year":
            return year

        if context == "alltime":
            return alltime

        if context == "yesterday":
            return yesterday

    def get_static_pages(self):
        """
        Get static pages.

        Returns:
            list: Static pages array
        """
        try:
            static_templates = self.skin_dict["CheetahGenerator"]["Static"]
        except KeyError:
            static_templates = {}

        static_pages = []

        for static_page in static_templates:
            static_pages.append(
                {
                    "name": static_page,
                    "title": static_templates[static_page]["title"],
                    "link": static_templates[static_page]["template"].replace(".tmpl", ""),
                }
            )

        return static_pages

    def get_static_page_title(self, page):
        """
        Get static page title.

        Args:
            page (string): The page

        Returns:
            str: The page title
        """
        static_pages = self.get_static_pages()

        for static_page in static_pages:
            if static_page["name"] == page:
                return static_page["title"]

        return ""

    def get_ordinates(self):
        default_ordinate_names = [
            "N",
            "NNE",
            "NE",
            "ENE",
            "E",
            "ESE",
            "SE",
            "SSE",
            "S",
            "SSW",
            "SW",
            "WSW",
            "W",
            "WNW",
            "NW",
            "NNW",
            "N/A",
        ]
        try:
            ordinate_names = self.generator.skin_dict["Units"]["Ordinates"]["directions"]

        except KeyError:
            ordinate_names = default_ordinate_names

        return ordinate_names

    def dwd_warning_has_warning(self, region_key):
        """
        Check if a given warning is empty.

        Args:
            region_key (string): The region key

        Returns:
            bool: True if a warning exists, False otherwise.
        """
        if not os.path.exists("dwd/warn-" + region_key + ".json"):
            return False

        with open("dwd/warn-" + region_key + ".json") as warn_file:
            data = json.load(warn_file)

        if len(data) == 0:
            return False

        return True

    def get_dwd_warning_region_name(self, region_key):
        """
        Get the name of a given region.

        Args:
            region_key (string): The region key

        Returns:
            str: The region name
        """
        if not os.path.exists("dwd/warn-" + region_key + ".json"):
            return ""

        with open("dwd/warn-" + region_key + ".json") as warn_file:
            data = json.load(warn_file)

            return data[0]["regionName"]

    def get_dwd_warnings(self):
        """
        Get the configured warn regions.

        `[DisplayOptions][[dwd]][[[warning]]]`, holding `counties` and
        `cities` the way the weewx-DWD extension writes them, because the
        files this reads are that extension's output.
        """
        try:
            dwd_warnings = self.skin_dict["DisplayOptions"]["dwd"]["warning"]
            return {**dwd_warnings.get("counties", {}), **dwd_warnings.get("cities", {})}

        # todo Log info.
        except KeyError:
            return {}


class ArchiveUtil(SearchList):
    def __init__(self, generator):
        SearchList.__init__(self, generator)

    def get_extension_list(self, timespan, db_lookup):
        """Returns a search list extension with two additions.

        Parameters:
          timespan: An instance of weeutil.weeutil.TimeSpan. This will
                    hold the start and stop times of the domain of
                    valid times.

          db_lookup: This is a function that, given a data binding
                     as its only parameter, will return a database manager
                     object.
        """

        self.db_lookup = db_lookup

        search_list_extension = {
            "get_stat_table_month_obs": self.get_stat_table_month_obs,
            "get_day_archive_enabled": self.get_day_archive_enabled,
            "get_archive_days_array": self.get_archive_days_array,
            "filter_months": self.filter_months,
            "fake_get_report_years": self.fake_get_report_years,
        }

        return [search_list_extension]

    def get_stat_table_month_obs(self, start_ts, end_ts):
        """
        Returns a TimeSpanBinder a period.

        Args:
            start_ts (int): The start timestamp
            end_ts (int): The end timestamp
        """
        month_timespan = TimeSpan(start_ts, end_ts)
        month_timespan_binder = TimespanBinder(
            month_timespan,
            self.db_lookup,
            formatter=self.generator.formatter,
            converter=self.generator.converter,
        )
        return month_timespan_binder

    def get_day_archive_enabled(self):
        """
        Get day archive enabled.

        Returns:
            bool|string: Value of day template if day archive is enabled, False otherwise.
        """
        try:
            return self.generator.skin_dict["CheetahGenerator"]["SummaryByDay"]["summary_day"][
                "template"
            ]
        except KeyError:
            return False

    @staticmethod
    def get_archive_days_array(start_ts, end_ts, date_format):
        """
        Get an array of days between two timestamps.

        Args:
            start_ts (int): The start timestamp
            end_ts (int): The end timestamp
            date_format (string): The date format

        Returns:
            list: Array of days
        """
        days = []
        start_date = datetime.datetime.fromtimestamp(start_ts)
        end_date = datetime.datetime.fromtimestamp(end_ts)

        for n in range(int((end_date - start_date).days) + 1):
            days.append(
                {
                    "date": (start_date + datetime.timedelta(n)).strftime(date_format),
                    "timestamp": int(time.mktime((start_date + datetime.timedelta(n)).timetuple())),
                }
            )

        return days

    @staticmethod
    def filter_months(months, year):
        """
        Returns a filtered list of months

        Args:
            months (list): A list of months [2022-01, 2022-02]
            year (string): Year.

        Returns:
            str: A icon include string.
        """
        months_filtered = []

        for month in months:
            if str(year) in month:
                months_filtered.append(month)

        return months_filtered

    @staticmethod
    def fake_get_report_years(first, last):
        """
        Returns a fake $SummaryByYear tag.

        Strings, because that is what the real `$SummaryByYear` holds --
        `strftime("%Y")` of each year. This returned integers, and the
        templates that use it write `$year + '-' + str($month)`: on a
        station whose skin produces no SummaryBy pages, the whole
        statistics page died with "unsupported operand type(s) for +:
        'int' and 'str'". A stand-in has to have the shape of the thing it
        stands in for.

        Args:
            first (int): Year of first observation.
            last (int): Year of last observation

        Returns:
            list: ["2021", "2022"].
        """
        first_year = int(first)
        last_year = int(last)

        if first_year == last_year:
            return [str(last_year)]

        return [str(year) for year in range(first_year, last_year + 1)]


class CelestialUtil(SearchList):
    @staticmethod
    def get_celestial_icon(observation, prop):
        """
        Returns an include path for an icon based on the observation

        Args:
            observation (string): Sun, Moon
            prop (string): set, rise

        Returns:
            str: A icon include string.
        """
        if observation == "Sun":
            if prop is None:
                return "includes/pictograms/sun.svg"
            if prop == "rise":
                return "includes/icons/sunrise.svg"
            if prop == "set":
                return "includes/icons/sunset.svg"
            if prop == "transit":
                return "includes/icons/radiation.svg"

        if observation == "Moon":
            if prop is None:
                return "includes/pictograms/moon.svg"
            if prop == "rise":
                return "includes/icons/moonrise.svg"
            if prop == "set":
                return "includes/icons/moonset.svg"
            if prop == "transit":
                return "includes/icons/moon.svg"


class DiagramUtil(SearchList):
    def __init__(self, generator):
        SearchList.__init__(self, generator)
        self.obs = ObsInfoHelper(generator.skin_dict)
        self.unit = UnitInfoHelper(generator.formatter, generator.converter)
        self.skin_dict = generator.skin_dict
        self.general_util = GeneralUtil(generator)

    def get_diagram_data(
        self,
        observation,
        observation_key,
        context_key,
        start_ts,
        end_ts,
        alltime_start,
        alltime_end,
        combined=None,
        combined_key=None,
    ):
        """
        Get diagram data.

        Args:
            observation (string): The observation
            observation_key (string): The observation key
            context_key (string): The context key
            start_ts (int): The start timestamp
            end_ts (int): The end timestamp
            alltime_start (str): The alltime start (%d.%m.%Y)
            alltime_end (str): The alltime end (%d.%m.%Y)
            combined (dict|None): The combined obs dict
            combined_key (string|None): The combined key

        Returns:
            list: A list of diagram data
        """
        if combined is not None:
            aggregate_type = self.get_aggregate_type(
                observation, context_key, combined=combined["obs"][observation]
            )
        else:
            aggregate_type = self.get_aggregate_type(observation, context_key)

        if observation_key == "windDir":
            wobs = "wind"
        else:
            wobs = observation_key

        # Include any given config to the XType call.
        obs_props = self.get_diagram_props_obs(observation, context_key, combined_key=combined_key)
        if "aggregate_type" in obs_props:
            obs_props.pop("aggregate_type")
        if "aggregate_interval" in obs_props:
            obs_props.pop("aggregate_interval")
        if "observations" in obs_props:
            obs_props.pop("observations")

        obs_start_vt, obs_stop_vt, obs_vt = skinkit.get_series(
            wobs,
            TimeSpan(start_ts, end_ts),
            self.generator.db_manager,
            aggregate_type=aggregate_type,
            aggregate_interval=self.get_aggregate_interval(
                observation=observation,
                context=context_key,
                alltime_start=alltime_start,
                alltime_end=alltime_end,
                combined_key=combined_key,
            ),
            **obs_props,
        )

        unit_default = self.generator.converter.getTargetUnit(obs_type=observation_key)
        unit_configured = self.general_util.get_unit_for_obs(
            observation, observation_key, context_key, combined=combined, combined_key=combined_key
        )

        # Target unit conversion.
        if unit_default != unit_configured and unit_configured is not None:
            obs_vt = skinkit.Converter({obs_vt[2]: unit_configured}).convert(obs_vt)
        else:
            obs_vt = self.generator.converter.convert(obs_vt)

        # Round values.
        obs_vt = rounder(
            obs_vt,
            self.get_rounding(
                observation,
                observation_key,
                type="diagram",
                combined=combined,
                combined_key=combined_key,
                context=context_key,
            ),
        )

        return json.dumps(list(zip(obs_start_vt[0], obs_stop_vt[0], obs_vt[0], strict=True)))

    def get_diagram(self, observation, context_key, *args, **kwargs):
        """
        Choose between line and bar.

        Args:
            observation (string): The observation
            context_key (string): The context

        Returns:
            str: A diagram string
        """
        combined_key = kwargs.get("combined_key")
        combined_obs = kwargs.get("combined_obs")

        type = "line"
        if observation == "rain" or observation == "ET":
            type = "bar"

        try:
            type = self.skin_dict["DisplayOptions"]["diagrams"][observation]["type"]
        except KeyError:
            pass

        if combined_key is None:
            try:
                type = self.skin_dict["DisplayOptions"]["diagrams"][context_key]["observations"][
                    observation
                ]["type"]
            except KeyError:
                pass

        if combined_key is not None:
            try:
                type = self.skin_dict["DisplayOptions"]["diagrams"]["combined_observations"][
                    combined_key
                ]["obs"][combined_obs]["type"]
            except KeyError:
                pass

            try:
                type = self.skin_dict["DisplayOptions"]["diagrams"][context_key]["observations"][
                    combined_key
                ]["obs"][combined_obs]["type"]
            except KeyError:
                pass

        return type

    def get_aggregate_type(self, observation, context, *args, **kwargs):
        """
        aggregate_type for observations series.
        @see https://github.com/weewx/weewx/wiki/Tags-for-series#syntax

        @todo Rework/Fix use_defaults (currently used for tables)

        Args:
            observation (string): The observation
            context (string): The context

        Returns:
            string: aggregate_type
        """
        use_defaults = kwargs.get("use_defaults", False)
        combined = kwargs.get("combined")
        diagrams_config = self.skin_dict["DisplayOptions"]["diagrams"]

        try:
            aggregate_type = search_up(
                diagrams_config[context]["observations"][observation], "aggregate_type", None
            )
        except KeyError:
            aggregate_type = None

        if aggregate_type is not None:
            return aggregate_type

        if combined is not None and "aggregate_type" in combined and not use_defaults:
            return combined["aggregate_type"]

        if (
            not use_defaults
            and observation in diagrams_config
            and "aggregate_type" in diagrams_config[observation]
        ):
            return diagrams_config[observation]["aggregate_type"]

        if observation == "ET" or observation == "rain":
            return "sum"

        if observation == "UV" or observation == "windGust" or observation == "rainRate":
            return "max"

        if observation == "windDir":
            return "vecdir"

        return "avg"

    def get_aggregate_interval(self, observation, context, *args, **kwargs):
        """
        aggregate_interval for observations series.
        @see https://github.com/weewx/weewx/wiki/Tags-for-series#syntax

        Args:
            observation (string): The observation
            context (string): Day, week, month, year, alltime

        Returns:
            int: aggregate_interval
        """
        alltime_start = kwargs.get("alltime_start")
        alltime_end = kwargs.get("alltime_end")
        combined_key = kwargs.get("combined_key")

        if context == "yesterday":
            context = "day"

        # First, check combined obs.
        if combined_key is not None:
            try:
                aggregate_interval = self.generator.skin_dict["DisplayOptions"]["diagrams"][
                    context
                ]["observations"][combined_key]["obs"][observation]["aggregate_interval"]
                return aggregate_interval
            except KeyError:
                aggregate_interval = False

            try:
                aggregate_interval = self.generator.skin_dict["DisplayOptions"]["diagrams"][
                    context
                ]["observations"][combined_key]["aggregate_interval"]
                return aggregate_interval
            except KeyError:
                aggregate_interval = False

            try:
                aggregate_interval = self.generator.skin_dict["DisplayOptions"]["diagrams"][
                    "combined_observations"
                ][combined_key]["obs"][observation]["aggregate_interval"]
                return aggregate_interval
            except KeyError:
                aggregate_interval = False

            try:
                aggregate_interval = self.generator.skin_dict["DisplayOptions"]["diagrams"][
                    "combined_observations"
                ][combined_key]["aggregate_interval"]
                return aggregate_interval
            except KeyError:
                aggregate_interval = False

        # Check if something is configured via skin.conf.
        context_dict = self.generator.skin_dict["DisplayOptions"]["diagrams"].get(context, {})
        try:
            aggregate_interval = search_up(
                context_dict["observations"][observation], "aggregate_interval"
            )
        except KeyError:
            try:
                aggregate_interval = search_up(context_dict, "aggregate_interval", False)
            except (KeyError, AttributeError):
                aggregate_interval = False
        except AttributeError:
            aggregate_interval = False

        if aggregate_interval:
            return aggregate_interval

        # Then, use defaults. Anything a day or longer is named after the
        # calendar rather than counted in seconds, and that is two things
        # at once.
        #
        # It is what the bar means. Ten years cut into a hundred gives
        # buckets of 36.5 days: a bar that runs from the 3rd of one month
        # to the 8th of the next, next to one that does not line up with
        # it either. Nobody reads a chart in 36.5-day periods.
        #
        # And it is what the bar costs. `Reader.aggregate()` only reads the
        # daily summaries for spans that are whole days, so a 36.5-day
        # bucket falls through to the archive records -- ten thousand rows
        # read per bar, a million per chart, to produce a hundred numbers
        # the summary tables already hold. Measured on ten years: 1543
        # record queries and 2.1 seconds for one page.
        wide = observation in ("ET", "rain")

        if context == "day":
            return 7200 if wide else 1800          # 2 hours / 30 minutes

        if context == "week":
            return "day" if wide else 900 * 8      # 2 hours

        if context == "month":
            return "day" if wide else 900 * 24     # 6 hours

        if context == "year":
            return "month" if wide else "day"

        if context == "alltime":
            if alltime_start is None or alltime_end is None:
                # No span to judge by. A month is the safe guess: on a
                # young station it draws a few bars, on an old one it does
                # not draw thousands.
                return "year" if wide else "month"

            start_dt = datetime.datetime.strptime(alltime_start, "%d.%m.%Y")
            end_dt = datetime.datetime.strptime(alltime_end, "%d.%m.%Y")
            days = (end_dt - start_dt).days

            if days < 10:
                # A station set up this week. Daily bars would be four of
                # them, so this reads like a day chart instead.
                return 7200 if wide else 1800
            if wide:
                # Bars, so fewer of them: about twenty is the target.
                return "day" if days <= 60 else (
                    "month" if days <= 900 else "year")
            return "day" if days <= 400 else (
                "month" if days <= 3650 else "year")

    def get_chart(self, observation, series_name, context, **kwargs):
        """The whole chart, as JSON, for one `data-chart` attribute.

        What this replaced: ten `data-` attributes carrying Python `repr`
        into the page, which the browser turned back into objects with
        `JSON.parse(text.replace(/'/g, '"'))`. That works until a label
        has an apostrophe in it, and then the chart is gone and the console
        says "Unexpected token".

        One attribute, one `json.dumps`, and the series themselves stay in
        a global -- a day at five-minute resolution is 288 timestamps, and
        an attribute would carry every one of them through the HTML
        escaper.
        """
        props = self.get_diagram_props(observation, context)
        combined = kwargs.get("combined")
        combined_key = kwargs.get("combined_key")
        obs_key = kwargs.get("observation_key", observation)

        kind = kwargs.get("kind")
        if kind is None:
            kind = self.get_diagram(observation, context,
                                    combined_key=combined_key)
        if obs_key in ("windDir", "windGustDir"):
            kind = "vector"

        spec = {
            "kind": kind,
            "locale": self.general_util.get_locale(),
            "curve": props.get("curve"),
            "lineWidth": to_int(props.get("lineWidth", 2)),
            "area": to_bool(props.get("enableArea", False)),
            "areaOpacity": float(props.get("areaOpacity", 0.18) or 0.18),
            "bottomFormat": props.get("bottom_date_time_format"),
            "tooltipFormat": props.get("tooltip_date_time_format"),
            "format": "%." + str(self.get_rounding(observation, obs_key)) + "f",
            "series": [],
            "units": [],
        }
        if props.get("markerValue") not in (None, ""):
            spec["marker"] = float(props["markerValue"])
            spec["markerColor"] = props.get("markerColor")
        if kind == "vector":
            spec["ordinals"] = self.general_util.get_ordinates()[:16]

        for one in kwargs.get("series") or []:
            spec["series"].append({
                "label": one.get("label", ""),
                "color": one.get("color"),
                "data": one.get("data"),
                "axis": one.get("axis", 0),
                "type": one.get("type"),
            })
            spec["units"].append(one.get("unit", ""))
        if not spec["series"]:
            spec["series"] = [{
                "label": kwargs.get("label", ""),
                "color": kwargs.get("color"),
                "data": series_name,
                "axis": 0,
            }]
            spec["units"] = [kwargs.get("unit", "")]

        if kwargs.get("night"):
            spec["night"] = kwargs["night"]
        del combined
        return json.dumps(spec)

    def get_diagram_props(self, obs, context):
        """
        Get diagram props from skin.conf.

        Args:
            obs (string): Observation
            context (string): Day, week, month, year, alltime

        Returns:
            dict: Diagram props for d3.js.
        """
        if context == "yesterday":
            context = "day"

        diagrams_config = self.skin_dict["DisplayOptions"]["diagrams"]
        diagram_base_props = diagrams_config[self.get_diagram(obs, context)]

        try:
            diagram_context_props = accumulateLeaves(
                diagrams_config[context]["observations"][obs], max_level=3
            )
        except KeyError:
            try:
                diagram_context_props = accumulateLeaves(
                    diagrams_config[context]["observations"], max_level=2
                )
            except KeyError:
                diagram_context_props = {}

        if obs in diagrams_config:
            return {**diagram_base_props, **diagrams_config[obs], **diagram_context_props}
        elif obs in diagrams_config["combined_observations"]:
            if (
                context in diagrams_config
                and "observations" in diagrams_config[context]
                and obs in diagrams_config[context]["observations"]
            ):
                return {
                    **diagram_base_props,
                    **diagrams_config["combined_observations"][obs],
                    **diagram_context_props,
                }
            else:
                return {
                    **diagram_base_props,
                    **diagrams_config["combined_observations"][obs],
                }
        else:
            return {**diagram_base_props, **diagram_context_props}

    def get_diagram_props_obs(self, observation, context, *args, **kwargs):
        """
        Same as get_diagram_props, but for specific observations. Returns
        the values in [combined_observations][X][observations][obs]
        instead of [combined_observations][X].

        Args:
            observation (string): The observation
            context (string): Day, week, month, year, alltime

        Returns:
            dict: A dict of props
        """
        combined_key = kwargs.get("combined_key")

        if context == "yesterday":
            context = "day"

        # Most basic config.
        try:
            props = self.skin_dict["DisplayOptions"]["diagrams"][observation]
        except KeyError:
            props = {}

        # Context config.
        try:
            props_context = accumulateLeaves(
                self.skin_dict["DisplayOptions"]["diagrams"][context]["observations"][observation],
                3,
            )
        except KeyError:
            props_context = self.skin_dict["DisplayOptions"]["diagrams"][context]
        finally:
            props = {**props, **props_context}

        # Combined config.
        if combined_key is not None:
            try:
                combined_props = accumulateLeaves(
                    self.skin_dict["DisplayOptions"]["diagrams"]["combined_observations"][
                        combined_key
                    ]["obs"][observation],
                    3,
                )
            except KeyError:
                combined_props = self.skin_dict["DisplayOptions"]["diagrams"][
                    "combined_observations"
                ][combined_key]
            finally:
                props = {**props, **combined_props}

            try:
                props_context_obs = accumulateLeaves(
                    self.skin_dict["DisplayOptions"]["diagrams"][context]["observations"][
                        combined_key
                    ]["obs"][observation],
                    3,
                )
            except KeyError:
                try:
                    props_context_obs = self.skin_dict["DisplayOptions"]["diagrams"][context][
                        "observations"
                    ][combined_key]
                except KeyError:
                    props_context_obs = {}
            finally:
                props = {**props, **props_context_obs}

        return props

    def get_diagram_boundary(self, context):
        """
        boundary for observations series for diagrams.

        Args:
            context (string): Day, week, month, year, alltime

        Returns:
            string: None | 'midnight'
        """
        try:
            aggregate_interval_s = self.generator.skin_dict["DisplayOptions"]["diagrams"][context][
                "aggregate_interval"
            ]
            return "midnight" if (to_int(aggregate_interval_s) / 60 / 60) % 24 == 0 else None
        except KeyError:
            if context == "day":
                return None

            if context == "week":
                return None

            if context == "month":
                return None

            if context == "year" or context == "alltime":
                return "midnight"

    def get_rounding(
        self,
        observation,
        observation_key,
        type=None,
        context=None,
        combined=None,
        combined_key=None,
    ):
        """
        Rounding settings for observations.

        Args:
            observation (string): The observation
            observation_key (string): The observation key (e.g. outTemp), this
              is only different from observation if it's a custom observation
              from a custom data_biding.
            type (string): The type (table or diagram)
            context (string): The context
            combined (dict): The combined dict
            combined_key (string): The combined key

        Returns:
            int: A rounding
        """
        # Context.
        if context is not None:
            try:
                rounding = search_up(
                    self.generator.skin_dict["DisplayOptions"]["diagrams"][context]["observations"][
                        observation_key
                    ],
                    "rounding",
                    None,
                )
            except KeyError:
                rounding = None

            if rounding is not None:
                return int(rounding)

        # Combined context.
        if combined is not None and context is not None:
            # Combined diagram.
            try:
                rounding = search_up(
                    self.skin_dict["DisplayOptions"]["diagrams"][context]["observations"][
                        combined_key
                    ]["obs"][observation],
                    "rounding",
                    None,
                )
            except KeyError:
                rounding = None

            if rounding is not None:
                return int(rounding)

        # Combined obs.
        if combined is not None and "rounding" in combined["obs"][observation]:
            return int(combined["obs"][observation]["rounding"])

        # Combined general.
        if combined is not None and "rounding" in combined:
            return int(combined["rounding"])

        # Table specific.
        if type == "table":
            # DisplayOptions > tables > Rounding.
            try:
                rounding = self.skin_dict["DisplayOptions"]["tables"]["Rounding"][observation_key]
            except KeyError:
                rounding = None

            if rounding is not None:
                return int(rounding)

        # Diagram specific.
        if type == "diagram":
            # General Diagram options, e.g. DisplayOptions > diagrams > heatindex.
            try:
                rounding = self.skin_dict["DisplayOptions"]["diagrams"][observation_key]["rounding"]
            except KeyError:
                rounding = None

            if rounding is not None:
                return int(rounding)

            # DisplayOptions > diagrams > Rounding.
            try:
                rounding = self.skin_dict["DisplayOptions"]["diagrams"]["Rounding"][observation_key]
            except KeyError:
                rounding = None

            if rounding is not None:
                return int(rounding)

        # DisplayOptions > Rounding.
        try:
            rounding = self.skin_dict["DisplayOptions"]["Rounding"][observation_key]
        except KeyError:
            rounding = None

        unit = self.general_util.get_unit_for_obs(observation, observation_key, context)

        # Fallback to a simple string parsing of [[StringFormats]].
        if rounding is None:
            try:
                unit_string_format = self.skin_dict["Units"]["StringFormats"][unit]

                # Careful! Potential for bugs here.
                for c in unit_string_format:
                    if c.isdigit():
                        rounding = c
                        break
            except KeyError:
                rounding = None

        if rounding is not None:
            return int(rounding)

        # Default roundings.
        if context is None:
            context = "day"

        if observation == "UV" or observation == "cloudbase":
            return 0

        if observation == "ET" or observation == "rain":
            return 2

        if (
            observation == "pressure" or observation == "barometer" or observation == "altimeter"
        ) and self.unit.unit_type.pressure == "inHg":
            return 3

        if unit == "percent":
            return 0

        return 1

    @staticmethod
    def get_hour_delta(context):
        """
        Get delta for $span($hour_delta=$delta) call.

        Args:
            context (string): Day, week, month, year, alltime

        Returns:
            float: A delta
        """
        now_dt = datetime.datetime.now()

        hour_delta = 24

        if context == "week":
            hour_delta = 24 * 7

        if context == "month":
            hour_delta = 24 * 30  # monthrange(now_dt.year, now_dt.month)[1]

        if context == "year":
            days = 366 if calendar.isleap(now_dt.year) else 365
            hour_delta = 24 * days

        return hour_delta

    def get_gauge_diagram_props(self, obs, context):
        """
        Get gauge props from skin.conf.

        Args:
            obs (string): Observation
            context (string): Day, week, month, year, alltime

        Returns:
            dict: Diagram props for d3.js.
        """
        if context == "yesterday":
            context = "day"

        diagrams_config = self.skin_dict["DisplayOptions"]["Gauges"][context][obs]

        return accumulateLeaves(diagrams_config, max_level=2)

    def get_gauge_diagram_prop(self, obs, prop, context):
        """
        Get gauge prop from skin.conf.

        Args:
            obs (string): Observation
            prop (string): Prop
            context (string): Day, week, month, year, alltime

        Returns:
            sring|number: Diagram prop for d3.js.
        """
        if context == "yesterday":
            context = "day"

        diagrams_config = self.skin_dict["DisplayOptions"]["Gauges"][context][obs]

        value = search_up(diagrams_config, prop, None)

        return value

    def get_windrose_chart(self, start_ts, end_ts, context):
        """The wind rose, as JSON for one `data-chart` attribute.

        Sixteen compass points, one stacked band per speed range. This is
        the chart a megabyte of Plotly was loaded on every page for.
        """
        bands = self.get_windrose_data(start_ts, end_ts, context)
        colours = self.skin_dict["DisplayOptions"].get(
            "windRose_colors",
            ["#f3cec9", "#e7a4b6", "#cd7eaf", "#a262a9", "#6f4d96", "#3d3b72"])
        if isinstance(colours, str):
            colours = [colours]
        return json.dumps({
            "kind": "windrose",
            "locale": self.general_util.get_locale(),
            "ordinals": self.general_util.get_ordinates()[:16],
            "bands": [
                {"label": band.get("label", ""),
                 "color": colours[index % len(colours)],
                 "data": band.get("r", [])}
                for index, band in enumerate(bands)
            ],
        })

    def get_windrose_data(self, start_ts, end_ts, context):
        """
        Get data for rendering wind rose in JS.

        start_ts (Timestamp): Start timestamp
        end_ts (Timestamp): End timestamp
        context (string): One of day, week, month, year

        Returns:
            list: Windrose data.
        """
        try:
            show_beaufort = self.generator.skin_dict["DisplayOptions"]["windRose_show_beaufort"]
        except KeyError:
            show_beaufort = False

        try:
            show_legend_units = to_bool(
                self.generator.skin_dict["DisplayOptions"]["windRose_legend_show_units"]
            )
        except KeyError:
            show_legend_units = True

        db_manager = self.generator.db_manager

        ordinals = self.general_util.get_ordinates()
        windrose_data = []

        # Remove "N/A" from ordinals.
        if len(ordinals) == 17:
            ordinals.pop()

        # We use a scale of 6: <=BF1, BF2, ..., BF5, >=BF6.
        for i in range(6):
            name_prefix = "<= " if i == 0 else ">= " if i == 5 else ""

            if to_bool(show_beaufort):
                name = "Beaufort " + str(i + 1)
            else:
                # Bft 1 and lower
                if i == 0:
                    wind_upper_vt = self.generator.converter.convert(
                        (5, "km_per_hour", "group_speed")
                    )
                    name = ValueHelper(
                        value_t=wind_upper_vt, formatter=self.generator.formatter
                    ).format(add_label=show_legend_units)
                # Bft 2
                elif i == 1:
                    wind_lower_vt = self.generator.converter.convert(
                        (6, "km_per_hour", "group_speed")
                    )
                    wind_upper_vt = self.generator.converter.convert(
                        (11, "km_per_hour", "group_speed")
                    )
                    name = (
                        ValueHelper(
                            value_t=wind_lower_vt, formatter=self.generator.formatter
                        ).format(add_label=show_legend_units)
                        + " - "
                        + ValueHelper(
                            value_t=wind_upper_vt, formatter=self.generator.formatter
                        ).format(add_label=show_legend_units)
                    )
                # Bft 3
                elif i == 2:
                    wind_lower_vt = self.generator.converter.convert(
                        (12, "km_per_hour", "group_speed")
                    )
                    wind_upper_vt = self.generator.converter.convert(
                        (19, "km_per_hour", "group_speed")
                    )
                    name = (
                        ValueHelper(
                            value_t=wind_lower_vt, formatter=self.generator.formatter
                        ).format(add_label=show_legend_units)
                        + " - "
                        + ValueHelper(
                            value_t=wind_upper_vt, formatter=self.generator.formatter
                        ).format(add_label=show_legend_units)
                    )
                # Bft 4
                elif i == 3:
                    wind_lower_vt = self.generator.converter.convert(
                        (20, "km_per_hour", "group_speed")
                    )
                    wind_upper_vt = self.generator.converter.convert(
                        (28, "km_per_hour", "group_speed")
                    )
                    name = (
                        ValueHelper(
                            value_t=wind_lower_vt, formatter=self.generator.formatter
                        ).format(add_label=show_legend_units)
                        + " - "
                        + ValueHelper(
                            value_t=wind_upper_vt, formatter=self.generator.formatter
                        ).format(add_label=show_legend_units)
                    )
                # Bft 5
                elif i == 4:
                    wind_lower_vt = self.generator.converter.convert(
                        (29, "km_per_hour", "group_speed")
                    )
                    wind_upper_vt = self.generator.converter.convert(
                        (38, "km_per_hour", "group_speed")
                    )
                    name = (
                        ValueHelper(
                            value_t=wind_lower_vt, formatter=self.generator.formatter
                        ).format(add_label=show_legend_units)
                        + " - "
                        + ValueHelper(
                            value_t=wind_upper_vt, formatter=self.generator.formatter
                        ).format(add_label=show_legend_units)
                    )
                # Bft 6 and higher
                elif i == 5:
                    wind_lower_vt = self.generator.converter.convert(
                        (39, "km_per_hour", "group_speed")
                    )
                    name = ValueHelper(
                        value_t=wind_lower_vt, formatter=self.generator.formatter
                    ).format(add_label=show_legend_units)

            windrose_data.append({
                "r": [0] * len(ordinals),
                "label": name_prefix + name,
            })

        _windDir_start_vt, _windDir_stop_vt, windDir_vt = skinkit.get_series(
            "wind",
            TimeSpan(start_ts, end_ts),
            db_manager,
            aggregate_type="vecdir",
            aggregate_interval=self.get_aggregate_interval(observation="windDir", context=context),
        )

        _windSpeed_start_vt, _windSpeed_stop_vt, windSpeed_vt = skinkit.get_series(
            "windSpeed",
            TimeSpan(start_ts, end_ts),
            db_manager,
            aggregate_type="max",
            aggregate_interval=self.get_aggregate_interval(
                observation="windSpeed", context=context
            ),
        )

        # TODO: Gust speeds?
        for windSpeed, windDir in zip(windSpeed_vt[0], windDir_vt[0], strict=False):
            # CHANGED in this fork, see CHANGES.md: calm has a speed of
            # 0.0 and no direction at all, and 'N/A' has been popped off
            # `ordinals` above. Upstream: Daveiano/weewx-wdc#311
            if windSpeed is None or windDir is None:
                continue

            # Convert windSpeed to knots, get beaufort.
            windspeed_source_unit = windSpeed_vt[1]
            if windspeed_source_unit in ("km_per_hour", "km_per_hour2"):
                windSpeed_knots = kph_to_knot(windSpeed)
            elif windspeed_source_unit in ("mile_per_hour", "mile_per_hour2"):
                windSpeed_knots = mph_to_knot(windSpeed)
            elif windspeed_source_unit in ("meter_per_second", "meter_per_second2"):
                windSpeed_knots = mps_to_knot(windSpeed)
            else:
                windSpeed_knots = windSpeed

            windSpeed_beaufort = beaufort(windSpeed_knots)
            winddir_oridnal = self.generator.formatter.to_ordinal_compass(
                (windDir, windDir_vt[1], windDir_vt[2])
            )
            windrose_data_ordinal_index = ordinals.index(winddir_oridnal)

            # Add 1 (one part of total number of parts) to the direction and
            # beaufort matrix.
            if windSpeed_beaufort is None or windSpeed_beaufort <= 1:
                windrose_data[0]["r"][windrose_data_ordinal_index] += 1
            elif windSpeed_beaufort <= 5:
                windrose_data[windSpeed_beaufort - 1]["r"][windrose_data_ordinal_index] += 1
            else:
                windrose_data[5]["r"][windrose_data_ordinal_index] += 1

        # Calculate percentages.
        num_of_values = len(list(windSpeed_vt[0]))

        if num_of_values > 0:
            for index, data in enumerate(windrose_data):
                for p_index, percent in enumerate(data["r"]):
                    windrose_data[index]["r"][p_index] = round(
                        # todo: division by zero
                        (percent / num_of_values) * 100
                    )

        return windrose_data


class StatsUtil(SearchList):
    def __init__(self, generator):
        SearchList.__init__(self, generator)
        self.unit = UnitInfoHelper(generator.formatter, generator.converter)
        self.obs = ObsInfoHelper(generator.skin_dict)
        self.diagram_util = DiagramUtil(generator)
        self.general_util = GeneralUtil(generator)

        self.db_manager = self.generator.db_manager

    def get_show_min(self, observation):
        """
        Returns if the min stats should be shown.

        Args:
            observation (string): The observation

        Returns:
            bool: Show or hide min stat.
        """
        show_min = self.generator.skin_dict["DisplayOptions"].get(
            "stat_tiles_show_min",
            [
                "outTemp",
                "outHumidity",
                "barometer",
                "pressure",
                "altimeter",
                "snowDepth",
                "heatindex",
                "dewpoint",
                "windchill",
                "cloudbase",
                "appTemp",
            ],
        )

        if observation in show_min:
            return True

    def get_show_sum(self, observation):
        """
        Returns if the sum stats should be shown.

        Args:
            observation (string): The observation

        Returns:
            bool: Show or hide sum stat.
        """
        show_sum = self.generator.skin_dict["DisplayOptions"].get(
            "stat_tiles_show_sum", ["rain", "ET", "hail", "snow", "lightning_strike_count"]
        )

        if observation in show_sum:
            return True

    def get_show_max(self, observation):
        """
        Returns if the max stats should be shown.

        Args:
            observation (string): The observation

        Returns:
            bool: Show or hide max stat.
        """
        show_max = self.generator.skin_dict["DisplayOptions"].get(
            "stat_tiles_show_max", ["rainRate", "hailRate", "snowRate", "UV"]
        )

        if observation in show_max:
            return True

    @staticmethod
    def get_labels(prop, context):
        """
        Returns a label like "Todays Max" or "Monthly average".

        Args:
            prop (string): Min, Max, Sum
            context (string): Day, week, month, year, alltime

        Returns:
            string: A label.
        """
        if context == "alltime":
            return prop

        return prop + " " + context

    def has_column(self, name):
        """Whether the archive has this reading at all.

        A station with no snow gauge should not be shown a row of zeroes
        for snow days -- the same reason the plot importer refuses to write
        a chart for a sensor that was never installed.
        """
        reader = getattr(self.db_manager, "reader", None)
        columns = getattr(reader, "columns", None) or ()
        return name in columns

    def get_climatological_day(self, day, start_ts, end_ts):
        """
        Return number of days in period for day parameter.

        Args:
            day (string): Eg. rainDays, hotDays.
            start_ts (str): Start timestamp.
            end_ts (str): End timestamp

        Returns:
            int: Number of days.
        """
        outTemp_target_unit_vt = self.generator.converter.getTargetUnit("outTemp")
        windGust_target_unit_vt = self.generator.converter.getTargetUnit("windGust")
        freezing_point = 0.0 if outTemp_target_unit_vt[0] == "degree_C" else 32.0

        if day == "iceDays":
            _outTemp_max_start_vt, _outTemp_max_stop_vt, outTemp_max_vt = skinkit.get_series(
                "outTemp",
                TimeSpan(start_ts, end_ts),
                self.db_manager,
                aggregate_type="max",
                aggregate_interval="day",
            )

            days = filter(
                lambda outTemp: (
                    outTemp is not None
                    and self.generator.converter.convert(
                        (outTemp, outTemp_max_vt[1], outTemp_max_vt[2])
                    )[0]
                    < freezing_point
                ),
                outTemp_max_vt[0],
            )

            return len(list(days))

        if day == "frostDays":
            _outTemp_min_start_vt, _outTemp_min_stop_vt, outTemp_min_vt = skinkit.get_series(
                "outTemp",
                TimeSpan(start_ts, end_ts),
                self.db_manager,
                aggregate_type="min",
                aggregate_interval="day",
            )

            days = filter(
                lambda outTemp: (
                    outTemp is not None
                    and self.generator.converter.convert(
                        (outTemp, outTemp_min_vt[1], outTemp_min_vt[2])
                    )[0]
                    < freezing_point
                ),
                outTemp_min_vt[0],
            )

            return len(list(days))

        if day == "stormDays":
            _windGust_min_start_vt, _windGust_min_stop_vt, windGust_max_vt = skinkit.get_series(
                "windGust",
                TimeSpan(start_ts, end_ts),
                self.db_manager,
                aggregate_type="max",
                aggregate_interval="day",
            )

            # TODO: Programmatic conversion, WeeWX best practice?
            if windGust_target_unit_vt[0] in ("km_per_hour", "km_per_hour2"):
                value = 62.0
            if windGust_target_unit_vt[0] in ("mile_per_hour", "mile_per_hour2"):
                value = 38.5
            if windGust_target_unit_vt[0] in ("meter_per_second", "meter_per_second2"):
                value = 17.2
            if windGust_target_unit_vt[0] in ("knot"):
                value = 33.5

            days = filter(
                lambda windGust: (
                    windGust is not None
                    and self.generator.converter.convert(
                        (windGust, windGust_max_vt[1], windGust_max_vt[2])
                    )[0]
                    >= value
                ),
                windGust_max_vt[0],
            )

            return len(list(days))

        if day == "rainDays":
            _rain_sum_start_vt, _rain_sum_stop_vt, rain_sum_vt = skinkit.get_series(
                "rain",
                TimeSpan(start_ts, end_ts),
                self.db_manager,
                aggregate_type="sum",
                aggregate_interval="day",
            )

            # 0.1 mm, the German weather service's threshold, not "more
            # than nothing": one tip of a bucket with 0.254 mm resolution
            # is a quarter of a millimetre of dew, and counting it makes a
            # rain day out of a dry morning.
            floor = 0.1 if rain_sum_vt[1] == "mm" else 0.004
            days = filter(lambda rain: rain is not None and rain >= floor,
                          list(rain_sum_vt[0]))

            return len(list(days))

        if day in ("heavyRainDays", "veryHeavyRainDays"):
            _start_vt, _stop_vt, rain_sum_vt = skinkit.get_series(
                "rain", TimeSpan(start_ts, end_ts), self.db_manager,
                aggregate_type="sum", aggregate_interval="day")
            millimetres = 10.0 if day == "heavyRainDays" else 20.0
            floor = (millimetres if rain_sum_vt[1] == "mm"
                     else millimetres / 25.4)
            return len([one for one in rain_sum_vt[0]
                        if one is not None and one >= floor])

        if day == "snowDays":
            column = "snowDepth" if self.has_column("snowDepth") else "snow"
            if not self.has_column(column):
                return 0
            _start_vt, _stop_vt, snow_vt = skinkit.get_series(
                column, TimeSpan(start_ts, end_ts), self.db_manager,
                aggregate_type="max" if column == "snowDepth" else "sum",
                aggregate_interval="day")
            return len([one for one in snow_vt[0]
                        if one is not None and one > 0.0])

        if day == "thunderDays":
            if not self.has_column("lightning_strike_count"):
                return 0
            _start_vt, _stop_vt, strikes_vt = skinkit.get_series(
                "lightning_strike_count", TimeSpan(start_ts, end_ts),
                self.db_manager, aggregate_type="sum",
                aggregate_interval="day")
            return len([one for one in strikes_vt[0]
                        if one is not None and one > 0])

        if day == "heatingDays":
            # The day's mean below 15 C. That is the threshold a heating
            # degree day is counted from here, so it is the one that says
            # "a day the house wanted heating".
            _start_vt, _stop_vt, mean_vt = skinkit.get_series(
                "outTemp", TimeSpan(start_ts, end_ts), self.db_manager,
                aggregate_type="avg", aggregate_interval="day")
            value = 15.0 if outTemp_target_unit_vt[0] == "degree_C" else 59.0
            return len([one for one in mean_vt[0] if one is not None
                        and self.generator.converter.convert(
                            (one, mean_vt[1], mean_vt[2]))[0] < value])

        if (
            day == "hotDays"
            or day == "summerDays"
            or day == "desertDays"
            or day == "tropicalNights"
        ):
            if day == "tropicalNights":
                value = 20.0 if outTemp_target_unit_vt[0] == "degree_C" else 68.0
                aggregate_type = "min"
            if day == "summerDays":
                value = 25.0 if outTemp_target_unit_vt[0] == "degree_C" else 77.0
                aggregate_type = "max"
            if day == "hotDays":
                value = 30.0 if outTemp_target_unit_vt[0] == "degree_C" else 86.0
                aggregate_type = "max"
            if day == "desertDays":
                value = 35.0 if outTemp_target_unit_vt[0] == "degree_C" else 95.0
                aggregate_type = "max"

            _outTemp_start_vt, _outTemp_stop_vt, outTemp_vt = skinkit.get_series(
                "outTemp",
                TimeSpan(start_ts, end_ts),
                self.db_manager,
                aggregate_type=aggregate_type,
                aggregate_interval="day",
            )

            days = filter(
                lambda outTemp: (
                    outTemp is not None
                    and self.generator.converter.convert((outTemp, outTemp_vt[1], outTemp_vt[2]))[0]
                    >= value
                ),
                outTemp_vt[0],
            )

            return len(list(days))

    def get_climatological_day_description(self, day):
        """
        Return description of day.

        Args:
            day (string): Eg. rainDays, hotDays.

        Returns:
            string: Day description.
        """
        outTemp_target_unit_vt = self.generator.converter.getTargetUnit("outTemp")
        windGust_target_unit_vt = self.generator.converter.getTargetUnit("windGust")

        if day == "iceDays":
            value = "0" if outTemp_target_unit_vt[0] == "degree_C" else "32"

            return self.obs.label["outTemp"] + "<sub>max</sub> < " + value + self.unit.label.outTemp

        if day == "frostDays":
            value = "0" if outTemp_target_unit_vt[0] == "degree_C" else "32"

            return self.obs.label["outTemp"] + "<sub>min</sub> < " + value + self.unit.label.outTemp

        if day == "stormDays":
            # TODO: Programmatic conversion, WeeWX best practice?
            if windGust_target_unit_vt[0] == "km_per_hour":
                value = "62"
            if windGust_target_unit_vt[0] == "mile_per_hour":
                value = "38.5"
            if windGust_target_unit_vt[0] == "meter_per_second":
                value = "17.2"
            if windGust_target_unit_vt[0] == "knot":
                value = "33.5"

            return self.obs.label["windGust"] + " > " + value + self.unit.label.windGust

        if day == "rainDays":
            floor = "0.1" if self.unit.label.rain.strip() == "mm" else "0.004"
            return (self.obs.label["rain"] + " &ge; " + floor
                    + self.unit.label.rain)

        if day in ("heavyRainDays", "veryHeavyRainDays"):
            metric = self.unit.label.rain.strip() == "mm"
            if day == "heavyRainDays":
                floor = "10" if metric else "0.4"
            else:
                floor = "20" if metric else "0.8"
            return (self.obs.label["rain"] + " &ge; " + floor
                    + self.unit.label.rain)

        if day == "snowDays":
            column = "snowDepth" if self.has_column("snowDepth") else "snow"
            return self.obs.label[column] + " &gt; 0"

        if day == "thunderDays":
            return self.obs.label["lightning_strike_count"] + " &gt; 0"

        if day == "heatingDays":
            value = ("15" if outTemp_target_unit_vt[0] == "degree_C"
                     else "59")
            return (self.obs.label["outTemp"] + "<sub>&oslash;</sub> &lt; "
                    + value + self.unit.label.outTemp)

        if (
            day == "hotDays"
            or day == "summerDays"
            or day == "desertDays"
            or day == "tropicalNights"
        ):
            if day == "tropicalNights":
                value = "20" if outTemp_target_unit_vt[0] == "degree_C" else "68"
                aggregate_type = "min"
            if day == "summerDays":
                value = "25" if outTemp_target_unit_vt[0] == "degree_C" else "77"
                aggregate_type = "max"
            if day == "hotDays":
                value = "30" if outTemp_target_unit_vt[0] == "degree_C" else "86"
                aggregate_type = "max"
            if day == "desertDays":
                value = "35" if outTemp_target_unit_vt[0] == "degree_C" else "95"
                aggregate_type = "max"

            return (
                self.obs.label["outTemp"]
                + "<sub>"
                + aggregate_type
                + "</sub> ≥ "
                + value
                + self.unit.label.outTemp
            )

    @staticmethod
    def get_calendar_color(obs):
        """
        Returns a color for use in diagram.

        Args:
            obs (string): The observation

        Returns:
            string: Color string.
        """
        if obs == "rain":
            return ["#032c6a", "#02509d", "#1a72b7", "#4093c7", "#6bb0d7", "#9fcae3"][::-1]

        if obs == "outTemp":
            # Warming stripes colors
            # @see https://en.wikipedia.org/wiki/Warming_stripes
            return [
                "#032c6a",
                "#02509d",
                "#1a72b7",
                "#4093c7",
                "#6bb0d7",
                "#9fcae3",
                "#c6dcee",
                "#dfedf6",
                "#ffe1d2",
                "#fcbda3",
                "#fc9373",
                "#fa6a48",
                "#ee3829",
                "#cd1116",
                "#a6060d",
                "#660105",
            ]

    def get_calendar_chart(self, obs, aggregate_type, start_ts, end_ts,
                           heading=""):
        """The days, or the months, depending on how long the span is.

        Under about fourteen months: a square per day, which is what a
        year page is for -- you can see which days it rained.

        Longer: twelve columns of months, one row per year. The same
        question a day grid cannot answer at that size. Ten years of days
        is 3650 squares and 1480 pixels of stacked calendars; ten years of
        months is ten rows.

        The month grid is also the shape of the table underneath it, on
        purpose: the same numbers, once to read and once to see.
        """
        if end_ts - start_ts > 14 * 31 * 86400:
            return self.get_month_matrix(obs, aggregate_type,
                                         start_ts, end_ts, heading)

        found = self.get_calendar_data(obs, aggregate_type, start_ts, end_ts)
        rows = [[one["day"], one["value"]] for one in found
                if one.get("value") is not None]
        days = sorted(one[0] for one in rows)
        colours = self.get_calendar_color(obs)
        if isinstance(colours, str):
            colours = [colours]
        return json.dumps({
            "kind": "calendar",
            "locale": self.general_util.get_locale(),
            "heading": heading,
            "unit": getattr(self.unit.label, obs, ""),
            "format": "%." + str(self.diagram_util.get_rounding(obs, obs)) + "f",
            "colors": list(colours),
            "range": [days[0], days[-1]] if days else None,
            "data": rows,
            # The row and column labels. ECharts has its own English list
            # and no idea what language the page is in.
            "days": list(self.general_util.weekday_names()),
            "months": list(self.general_util.month_names()),
        })

    def get_month_matrix(self, obs, aggregate_type, start_ts, end_ts,
                         heading=""):
        """Months across, years down, as JSON for one `data-chart`.

        What a day grid turns into once the span is longer than a year or
        so. Twelve columns whatever happens, and one row per year, so a
        station recording since 2005 is twenty rows rather than seven
        thousand squares.
        """
        import datetime as _datetime

        _start_vt, _stop_vt, values_vt = skinkit.get_series(
            obs, TimeSpan(start_ts, end_ts), self.db_manager,
            aggregate_type=aggregate_type, aggregate_interval="month")

        rows = []
        years = []
        for when, value in zip(_start_vt[0], values_vt[0], strict=True):
            if value is None:
                continue
            moment = _datetime.datetime.fromtimestamp(when)
            year = str(moment.year)
            if year not in years:
                years.append(year)
            # [column, row, value] -- ECharts' heatmap on two category
            # axes, with the row filled in once the years are known.
            rows.append([moment.month - 1, year, round(float(value), 4)])

        years.sort()
        data = [[column, years.index(year), value]
                for column, year, value in rows]

        colours = self.get_calendar_color(obs)
        if isinstance(colours, str):
            colours = [colours]
        return json.dumps({
            "kind": "matrix",
            "locale": self.general_util.get_locale(),
            "heading": heading,
            "unit": getattr(self.unit.label, obs, ""),
            "format": "%." + str(self.diagram_util.get_rounding(obs, obs)) + "f",
            "colors": list(colours),
            "months": list(self.general_util.month_names()),
            "years": years,
            "data": data,
        })

    def get_calendar_data(self, obs, aggregate_type, start_ts, end_ts):
        """
        Returns array of calendar data for use in diagram.

        Args:
            obs (string): The observation
            aggregate_type (string): Min, max, avg.
            start_ts (int): Start timestamp.
            end_ts (int): End timestamp.

        Returns:
            list: Calendar data.
        """
        if obs == "rain":
            rain_start_vt, _rain_stop_vt, rain_vt = skinkit.get_series(
                "rain",
                TimeSpan(start_ts, end_ts),
                self.db_manager,
                aggregate_type=aggregate_type,
                aggregate_interval="day",
            )

            days = filter(
                lambda x: x[1] is not None and x[1] > 0.0,
                list(zip(rain_start_vt[0], rain_vt[0], strict=True)),
            )
            rain_days = []

            for day in days:
                day_dt = datetime.datetime.fromtimestamp(day[0])
                rain_target_unit_vt = self.generator.converter.convert(
                    (day[1], rain_vt[1], rain_vt[2])
                )
                rain_days.append(
                    {
                        "value": rounder(
                            rain_target_unit_vt[0], self.diagram_util.get_rounding("rain", "rain")
                        ),
                        "day": day_dt.strftime("%Y-%m-%d"),
                    }
                )

            return rain_days

        if obs == "outTemp":
            outTemp_start_vt, _outTemp_stop_vt, outTemp_vt = skinkit.get_series(
                "outTemp",
                TimeSpan(start_ts, end_ts),
                self.db_manager,
                aggregate_type=aggregate_type,
                aggregate_interval="day",
            )

            days = list(zip(outTemp_start_vt[0], outTemp_vt[0], strict=True))
            temp_days = []

            for day in days:
                if day[1] is not None:
                    day_dt = datetime.datetime.fromtimestamp(day[0])
                    outTemp_target_unit_vt = self.generator.converter.convert(
                        (day[1], outTemp_vt[1], outTemp_vt[2])
                    )
                    temp_days.append(
                        {
                            "value": rounder(
                                outTemp_target_unit_vt[0],
                                self.diagram_util.get_rounding("outTemp", "outTemp"),
                            ),
                            "day": day_dt.strftime("%Y-%m-%d"),
                        }
                    )

            return temp_days


class TableUtil(SearchList):
    def __init__(self, generator):
        SearchList.__init__(self, generator)
        self.unit = UnitInfoHelper(generator.formatter, generator.converter)
        self.obs = ObsInfoHelper(generator.skin_dict)
        self.diagram_util = DiagramUtil(generator)
        self.general_util = GeneralUtil(generator)

        self.db_manager = self.generator.db_manager

        self.table_obs = self.generator.skin_dict["DisplayOptions"].get(
            "table_tile_observations", {}
        )
        self.table_options = self.generator.skin_dict["DisplayOptions"].get("tables", {})

    def get_table_aggregate_interval(self, context):
        """
        aggregate_interval for observations series for tables.

        Args:
            context (string): Day, week, month, year, alltime

        Returns:
            int: aggregate_interval
        """
        if context == "yesterday":
            context = "day"

        try:
            return self.table_options[context]["aggregate_interval"]
        except KeyError:
            if context == "day":
                return 900 * 4  # 1 hours

            if context == "week":
                return 900 * 24  # 6 hours

            if context == "month":
                return 900 * 48  # 12 hours

            if context == "year" or context == "alltime":
                return 3600 * 24  # 1 day

    def get_table_boundary(self, context):
        """
        boundary for observations series for tables.

        Args:
            context (string): Day, week, month, year, alltime

        Returns:
            string: None | 'midnight'
        """
        if context == "yesterday":
            context = "day"

        try:
            aggregate_interval_s = to_int(self.table_options[context]["aggregate_interval"])
            return "midnight" if (aggregate_interval_s / 60 / 60) % 24 == 0 else None
        except KeyError:
            if context == "day":
                return None

            if context == "week":
                return None

            if context == "month":
                return None

            if context == "year" or context == "alltime":
                return "midnight"

    def get_table_headers(self, start_ts, end_ts, table_obs=None):
        """
        Returns tableheaders for use in carbon data table.

        Args:
            start_ts (Timestamp): Start timestamp.
            end_ts (Timestamp): End timestamp.
            table_obs (list, optional): List of observations to use. Defaults to None.

        Returns:
            list: Carbon data table headers.
        """
        carbon_headers = [
            {
                "title": "Time",
                "id": "time",
                "sortCycle": "tri-states-from-ascending",
            }
        ]

        obs = self.table_obs

        if table_obs:
            obs = table_obs

        for observation in obs:
            observation_key = observation
            db_manager = self.db_manager

            if db_manager.has_data(observation_key, TimeSpan(start_ts, end_ts)):
                carbon_header = {
                    "title": self.obs.label[observation],
                    "small": "in " + getattr(self.unit.label, observation_key),
                    "id": observation,
                    "sortCycle": "tri-states-from-ascending",
                }
                carbon_headers.append(carbon_header)

        return carbon_headers

    def get_table_rows(self, start_ts, end_ts, context, table_obs=None):
        """
        Returns table values for use in carbon data table.

        Args:
            start_ts (Timestamp): Start timestamp.
            end_ts (Timestamp): End timestamp.
            context (string): Day, week, month, year, alltime
            table_obs (list|None): List of observations to include in table.

        Returns:
            list: Carbon data table rows.
        """
        carbon_values = []
        # Rows by the moment they are for. The loop below fills one row per
        # timestamp across every observation, and it used to find that row
        # with a linear scan of everything written so far:
        #
        #     list(filter(lambda x: x["time"] == when.isoformat(), rows))
        #
        # Quadratic, and `isoformat()` was inside the lambda, so it ran
        # once per row *compared* rather than once per row wanted. On ten
        # years that is 86.6 million calls and 42 of the page's 67 seconds.
        # A dictionary makes it one lookup.
        by_time = {}

        # The aggregate_interval should be the multiple of a day for these contexts, so
        # we need to adjust the start and end timestamps to the start of the day.
        # This would otherwise generate table rows with different start timestamps, actually
        # it puts the windDir (wind) values sometimes in a new row.
        if context == "year" or context == "alltime":
            start_ts = startOfArchiveDay(start_ts)
            end_ts = startOfArchiveDay(end_ts)

        obs = self.table_obs

        if table_obs:
            obs = table_obs

        for observation in obs:
            observation_key = observation
            db_manager = self.db_manager

            if db_manager.has_data(observation_key, TimeSpan(start_ts, end_ts)):
                if observation_key == "windDir":
                    wobs = "wind"
                else:
                    wobs = observation_key

                series_start_vt, series_stop_vt, observation_vt = skinkit.get_series(
                    wobs,
                    TimeSpan(start_ts, end_ts),
                    db_manager,
                    aggregate_type=self.diagram_util.get_aggregate_type(
                        observation, context, use_defaults=True
                    ),
                    aggregate_interval=self.get_table_aggregate_interval(context=context),
                )

                for table_start_ts, table_stop_ts, table_data in zip(
                    series_start_vt[0],
                    series_stop_vt[0],
                    observation_vt[0],
                    strict=True,
                ):
                    if context == "alltime" or context == "year":
                        # We show the date only here, so we need the start of the day.
                        cs_time_dt = datetime.datetime.fromtimestamp(table_start_ts)
                    else:
                        cs_time_dt = datetime.datetime.fromtimestamp(table_stop_ts)

                    # Once per row, not once per comparison.
                    when = cs_time_dt.isoformat()

                    table_date_target_unit = self.generator.converter.convert(
                        (table_data, observation_vt[1], observation_vt[2])
                    )

                    table_data_rounded = rounder(
                        table_date_target_unit[0],
                        self.diagram_util.get_rounding(observation, observation, type="table"),
                    )

                    shown = table_data_rounded if table_data_rounded is not None else "-"

                    cs_item = by_time.get(when)
                    if cs_item is None:
                        cs_item = {"time": when, "id": table_start_ts}
                        by_time[when] = cs_item
                        carbon_values.append(cs_item)
                    # The row is the same object in both the dictionary and
                    # the list, so writing into it is enough.
                    cs_item[observation] = shown

        # Sort per time
        carbon_values.sort(key=lambda item: datetime.datetime.fromisoformat(item["time"]))

        return carbon_values

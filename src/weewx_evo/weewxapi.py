"""Enough of WeeWX's API for a skin's own Python to run.

A WeeWX skin may ship code. `search_list_extensions` in its `skin.conf`
names classes, each one is handed the generator and asked for a dictionary,
and the templates then use what came back. weewx-wdc ships eight of them and
2851 lines; Belchertown ships one and a thousand. Without this, those skins
do not render at all -- not "render with gaps", not at all -- so the promise
that an existing skin keeps working needs it.

What they import is not a small surface:

    weewx.cheetahgenerator.SearchList     the base class
    weewx.units.ValueHelper               a number that knows how to print
    weewx.units.ValueTuple                a number, its unit and its group
    weewx.units.UnitInfoHelper, ObsInfoHelper, Converter
    weewx.tags.TimespanBinder             $day, handed over as an object
    weewx.xtypes.get_series               a time series
    weewx.wxformulas.beaufort
    weeutil.weeutil.TimeSpan, rounder, to_bool, to_int, startOfDay
    weeutil.config.search_up, accumulateLeaves

So this module builds those names on top of what weewx-evo already has, and
puts them in `sys.modules` under WeeWX's names. It is a translation layer,
not a reimplementation: `ValueHelper` *is* our `Value`, `TimespanBinder` *is*
our `Span`, and `get_series` calls `series.Reader.series`.

## The line this does not cross

Only what a search list extension touches. Not the report engine, not the
database managers, not the driver API. An extension that reaches past this
gets an ImportError naming what it wanted, which is a message somebody can
act on -- better than a half-working object that returns wrong numbers.

## Installing over the real WeeWX

`install()` puts these in `sys.modules` whether or not WeeWX is installed,
and that is deliberate. An extension is handed *our* generator, with our
converter and our formatter; real WeeWX classes given those would fail in a
much more confusing way. A process that needs both is a process doing two
different things, and our own checking tools that compare against WeeWX
never load a skin.
"""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

from . import units
from .series import Reader

log = logging.getLogger(__name__)

#: Set once `install()` has run, so a second feed does not build it again.
_INSTALLED = False


# -- the pieces ------------------------------------------------------------

class ValueTuple(tuple):
    """A number, the unit it is in, and the group it belongs to.

    WeeWX's own, and a tuple on purpose: extensions unpack it, index it, and
    do arithmetic on it. The arithmetic keeps the unit, which is the point --
    two temperatures subtract to a temperature and refuse to add to a
    pressure.
    """

    def __new__(cls, *args: Any) -> "ValueTuple":
        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            args = tuple(args[0])
        while len(args) < 3:
            args = args + (None,)
        return super().__new__(cls, args[:3])

    @property
    def value(self) -> Any:
        return self[0]

    @property
    def unit(self) -> Any:
        return self[1]

    @property
    def group(self) -> Any:
        return self[2]

    def _arith(self, other: Any, how: Any) -> "ValueTuple":
        if isinstance(other, (tuple, list)):
            if other[1] != self[1] or other[2] != self[2]:
                raise TypeError(f"cannot combine {self[1]} and {other[1]}")
            other = other[0]
        if self[0] is None or other is None:
            return ValueTuple(None, self[1], self[2])
        return ValueTuple(how(self[0], other), self[1], self[2])

    def __add__(self, other: Any) -> "ValueTuple":  # type: ignore[override]
        return self._arith(other, lambda a, b: a + b)

    def __sub__(self, other: Any) -> "ValueTuple":
        return self._arith(other, lambda a, b: a - b)

    def __mul__(self, other: Any) -> "ValueTuple":  # type: ignore[override]
        return self._arith(other, lambda a, b: a * b)

    def __truediv__(self, other: Any) -> "ValueTuple":
        return self._arith(other, lambda a, b: a / b)


def _value_helper(tags_module: Any) -> type:
    """Build `ValueHelper` on top of our own `Value`.

    A closure because `tags` imports this module's neighbours, and importing
    it at the top would be a circle.
    """
    class ValueHelper(tags_module.Value):
        """WeeWX's ValueHelper. Ours, with WeeWX's constructor."""

        def __init__(self, value_t: Any = None, context: str = "current",
                     formatter: Any = None, converter: Any = None) -> None:
            value, unit, group = ValueTuple(value_t or (None, None, None))
            target = getattr(converter, "target", None) \
                or getattr(formatter, "target", None)
            super().__init__(value, unit, group, context, target)

        @property
        def value_t(self) -> ValueTuple:
            return ValueTuple(self.value, self.unit, self.group)

    return ValueHelper


class UnitInfoHelper:
    """`$unit.label.outTemp`, `$unit.unit_type.pressure`, `$unit.format.x`.

    WeeWX builds it from a formatter and a converter, and an extension does
    the same. Ours is built from a `units.Target`, which is what both of
    those are made of here.
    """

    def __init__(self, formatter: Any = None, converter: Any = None) -> None:
        target = getattr(converter, "target", None)             or getattr(formatter, "target", None) or units.Target()
        self.target = target
        self.label = _UnitLookup(target, "label")
        self.unit_type = _UnitLookup(target, "unit")
        self.format = _UnitLookup(target, "format")
        # WeeWX's older spellings, which some extensions still use.
        self.label_dict = self.label
        self.unit_type_dict = self.unit_type
        self.format_dict = self.format


class _UnitLookup(dict):
    """One of those three, by reading. A dict, because Cheetah subscripts it.

    Not a plain lookup table: a station has readings nobody listed, so the
    answer is worked out per name rather than filled in per name.
    """

    def __init__(self, target: units.Target, want: str) -> None:
        super().__init__()
        self.target = target
        self.want = want

    def __getattr__(self, obs_type: str) -> Any:
        if obs_type.startswith("_"):
            raise AttributeError(obs_type)
        return self[obs_type]

    def __missing__(self, obs_type: str) -> Any:
        unit, _group = self.target.for_obs(obs_type)
        if self.want == "unit":
            return unit or ""
        if self.want == "format":
            return self.target.format_for(unit) or "%s"
        return self.target.label_for(unit)


class ObsInfoHelper:
    """`$obs.label.outTemp` -- what a reading is called, from the skin.

    WeeWX builds it from the whole skin configuration and reads
    `[Labels][[Generic]]` out of it. An extension hands us the same thing.
    """

    def __init__(self, skin_dict: dict[str, Any] | None = None) -> None:
        labels = ((skin_dict or {}).get("Labels") or {})
        generic = labels.get("Generic")
        source = generic if isinstance(generic, dict) else labels
        self.label = _ObsLabels(
            {k: str(v) for k, v in source.items() if isinstance(v, str)})


class _ObsLabels(dict):
    """A reading's name, falling back to the reading's own name."""

    def __getattr__(self, obs_type: str) -> str:
        if obs_type.startswith("_"):
            raise AttributeError(obs_type)
        return self[obs_type]

    def __missing__(self, obs_type: str) -> str:
        return units.obs_label(obs_type)


def _timespan_binder(tags_module: Any) -> Any:
    """`TimespanBinder(timespan, db_lookup, formatter=..., converter=...)`.

    An extension builds one to hand a span back to a template -- weewx-wdc
    returns `$month` for a page about a particular month that way. WeeWX's
    constructor takes a formatter and a converter; ours takes the tag layer
    and works both of those out of it, so the extras are accepted and
    ignored rather than being a TypeError halfway down a page.
    """
    def build(timespan: Any, db_lookup: Any = None, context: str = "current",
              formatter: Any = None, converter: Any = None,
              **_options: Any) -> Any:
        manager = getattr(db_lookup, "manager", None)             or (db_lookup() if callable(db_lookup) else None)
        reader = getattr(manager, "reader", None)
        target = getattr(converter, "target", None)             or getattr(formatter, "target", None)
        tags = tags_module.Tags(reader, target=target,
                                unit_system=reader.system if reader
                                else units.US)
        return tags_module.Span(tags, (timespan[0], timespan[1]), context)

    return build


class SearchList:
    """What a skin's extension inherits from.

    `self.generator` is the only thing it is given, and what it asks that
    for is a converter, a formatter, the skin's configuration and a way to
    reach the database.
    """

    def __init__(self, generator: Any) -> None:
        self.generator = generator

    def get_extension_list(self, timespan: Any, db_lookup: Any) -> list:
        """What goes into the search list.

        `[self]` by default, which is WeeWX's own and not a detail: several
        extensions never override it, and every public method they have is
        then a tag. weewx-wdc's WdcGeneralUtil is one -- returning an empty
        list here cost eight of its pages, all with the same unhelpful
        "'Unknown' object is not iterable".
        """
        del timespan, db_lookup
        return [self]


class Reports(dict):
    """`config_dict["StdReport"]`, which answers for any report name.

    An extension reads its own section out of weewx.conf --
    `config_dict["StdReport"]["WdcReport"]` -- to find settings the operator
    put there. There is no weewx.conf here and no report called WdcReport;
    there is one feed running one skin, and its settings are the skin's own.
    So every name answers with those.

    Guessing the name instead would mean reading it out of the skin, and no
    skin says what the operator called its report. A dictionary that answers
    is the honest shape of "whatever you were going to call it, this is it".
    """

    def __init__(self, section: dict[str, Any]) -> None:
        super().__init__()
        self.section = section

    def __missing__(self, name: str) -> dict[str, Any]:
        del name
        return self.section


class Generator:
    """What an extension is handed. WeeWX calls this the report generator.

    Five attributes, which is what the extensions actually reach for:
    `converter` and `formatter` to turn numbers into text, `skin_dict` and
    `config_dict` to read their own settings out of, and `db_binder` to get
    at the archive.
    """

    def __init__(self, skin_dict: dict[str, Any],
                 config_dict: dict[str, Any], reader: Reader,
                 target: units.Target, tags: Any) -> None:
        self.skin_dict = skin_dict
        #: What weewx.conf would have been. `StdReport` answers for any
        #: report name with this skin's own settings; the rest is what the
        #: caller passed, which is the station's.
        self.config_dict = dict(config_dict or {})
        self.config_dict.setdefault("StdReport", Reports(skin_dict))
        self.reader = reader
        self.target = target
        self.tags = tags
        self.formatter = Formatter(skin_dict, target)
        self.converter = Converter(target)
        self.db_binder = DbBinder(reader)
        #: WeeWX puts the moment the report is for here, and an extension
        #: that wants "now" reads it rather than asking the clock -- which
        #: is what makes two pages of one run agree with each other.
        self.gen_ts = int(getattr(tags, "when", 0)) or None


class Formatter:
    """Turns a value tuple into text. WeeWX's `weewx.units.Formatter`."""

    def __init__(self, skin_dict: dict[str, Any] | None = None,
                 target: units.Target | None = None) -> None:
        self.skin_dict = skin_dict or {}
        self.target = target or units.Target()
        self.unit_label_dict = dict(self.target.labels)
        self.unit_format_dict = dict(self.target.formats)
        self.time_format_dict = dict(self.target.time_formats)
        # Never empty. An extension does `ordinate_names.index(direction)`
        # to turn a compass point back into a bearing, and an empty list
        # makes that a ValueError saying only "'N/A' is not in list".
        from .tags import COMPASS

        self.ordinate_names = list(self.target.ordinals or COMPASS)

    def toString(self, val_t: Any, context: str = "current",  # noqa: N802
                 addLabel: bool = True,  # noqa: N803
                 useThisFormat: Any = None,  # noqa: N803
                 None_string: Any = None,  # noqa: N803
                 localize: bool = True) -> str:
        from . import tags as tags_module

        value, unit, group = ValueTuple(val_t or (None, None, None))
        return tags_module.Value(value, unit, group, context,
                                 self.target).format(useThisFormat,
                                                     None_string, addLabel)

    def get_label_string(self, unit: Any, plural: bool = True) -> str:
        return self.target.label_for(unit, plural)

    def to_ordinal_compass(self, val_t: Any) -> str:
        from . import tags as tags_module

        value, unit, group = ValueTuple(val_t or (None, None, None))
        return tags_module.Value(value, unit, group, "current",
                                 self.target).ordinal_compass


class Converter:
    """Turns a value tuple into what the page shows it in.

    Built two ways, because WeeWX's is: from a `units.Target`, which is what
    the rest of this program passes around, or from a plain `{group: unit}`
    dictionary, which is what an extension writes when it wants one reading
    in one particular unit --

        weewx.units.Converter({obs_vt[2]: wanted}).convert(obs_vt)

    -- and weewx-wdc does exactly that, once per chart.
    """

    def __init__(self, target: Any = None) -> None:
        if isinstance(target, units.Target):
            self.target = target
        elif isinstance(target, dict):
            # A group-to-unit mapping, as WeeWX's own constructor takes.
            # Overrides on top of US: anything the mapping does not name
            # keeps whatever it already was.
            self.target = units.Target(units.US, {
                group: unit for group, unit in target.items()
                if group in units.SYSTEMS[units.US]})
        else:
            self.target = units.Target()
        self.group_unit_dict = {
            group: self.target.unit(group)
            for group in units.SYSTEMS.get(units.US, {})}

    def convert(self, val_t: Any) -> ValueTuple:
        """One value, or a whole series of them.

        A list as well as a number, because `get_series` hands back lists
        and an extension converts what it got: weewx-wdc does exactly that
        for every chart. Given a list, `units.convert` multiplies a list by
        a float and the page dies with "can't multiply sequence by non-int
        of type 'float'" -- seven pages of thirteen, and only on a station
        whose archive is not already in the unit the page shows.
        """
        value, unit, group = ValueTuple(val_t or (None, None, None))
        wanted = self.target.unit(group) or unit
        try:
            if isinstance(value, (list, tuple)):
                return ValueTuple(units.convert_all(list(value), unit,
                                                    wanted), wanted, group)
            return ValueTuple(units.convert(value, unit, wanted), wanted,
                              group)
        except ValueError:
            return ValueTuple(value, unit, group)

    def getTargetUnit(self, obs_type: str,  # noqa: N802
                      agg_type: Any = None) -> tuple[Any, Any]:
        return self.target.for_obs(obs_type, agg_type)


class DbBinder:
    """`db_lookup()` and what it returns.

    An extension calls `db_lookup()` with no arguments, or with a binding
    name it does not otherwise use, and gets something it runs SQL against.
    Three methods between all the ones that exist, so three are here.
    """

    def __init__(self, reader: Reader) -> None:
        self.reader = reader
        self.manager = Manager(reader)

    def get_manager(self, *_args: Any, **_kwargs: Any) -> "Manager":
        return self.manager

    def __call__(self, *_args: Any, **_kwargs: Any) -> "Manager":
        return self.manager


class Manager:
    """A database, as an extension expects to be handed one."""

    def __init__(self, reader: Reader) -> None:
        self.reader = reader
        self.table_name = reader.table
        self.connection = reader.conn

    @property
    def std_unit_system(self) -> int:
        return self.reader.system

    @property
    def firstGoodStamp(self) -> Any:  # noqa: N802
        found = self.reader.span()
        return found[0] if found else None

    @property
    def lastGoodStamp(self) -> Any:  # noqa: N802
        found = self.reader.span()
        return found[1] if found else None

    def getSql(self, sql: str,  # noqa: N802
               params: Any = ()) -> Any:
        """One row, or None. WeeWX's own name for it."""
        try:
            return self.reader.conn.execute(sql, params or ()).fetchone()
        except Exception as exc:  # noqa: BLE001
            log.debug("a skin's SQL did not run: %s -- %s", sql, exc)
            return None

    def genSql(self, sql: str, params: Any = ()) -> Any:  # noqa: N802
        try:
            yield from self.reader.conn.execute(sql, params or ())
        except Exception as exc:  # noqa: BLE001
            log.debug("a skin's SQL did not run: %s -- %s", sql, exc)

    def has_data(self, obs_type: str, timespan: Any) -> bool:
        try:
            start, stop = timespan[0], timespan[1]
            return bool(self.reader.aggregate(obs_type, start, stop,
                                              "not_null"))
        except Exception:  # noqa: BLE001
            return False

    def getAggregate(self, timespan: Any, obs_type: str,  # noqa: N802
                     aggregate_type: str, **_kwargs: Any) -> ValueTuple:
        value = self.reader.aggregate(obs_type, timespan[0], timespan[1],
                                      aggregate_type)
        unit, group = units.unit_of(obs_type, self.std_unit_system,
                                    aggregate_type)
        return ValueTuple(value, unit, group)


class TimeSpan(tuple):
    """A start and a stop. WeeWX's `weeutil.weeutil.TimeSpan`."""

    def __new__(cls, start: Any, stop: Any) -> "TimeSpan":
        return super().__new__(cls, (start, stop))

    @property
    def start(self) -> Any:
        return self[0]

    @property
    def stop(self) -> Any:
        return self[1]

    @property
    def length(self) -> Any:
        return self[1] - self[0]

    def includesArchiveTime(self, when: Any) -> bool:  # noqa: N802
        return self[0] < when <= self[1]

    def __str__(self) -> str:
        return f"[{self[0]} -> {self[1]}]"


# -- the small helpers -----------------------------------------------------

def search_up(section: Any, key: str, *default: Any) -> Any:
    """Look for a key here, then in the section above, and so on.

    A ConfigObj section knows its parent. Ours are plain dictionaries, so
    the walk stops at the first one -- which is right for a skin's own
    configuration, where everything a template reads has already been
    flattened by `accumulateLeaves`.
    """
    if isinstance(section, dict) and key in section:
        return section[key]
    parent = getattr(section, "parent", None)
    while isinstance(parent, dict):
        if key in parent:
            return parent[key]
        parent = getattr(parent, "parent", None)
    if default:
        return default[0]
    raise KeyError(key)


def accumulateLeaves(section: Any,  # noqa: N802
                     max_level: int = 99) -> dict[str, Any]:
    """Every scalar in a section and the ones above it, flattened.

    WeeWX walks upwards through ConfigObj's parents. A plain dictionary has
    none, so this returns the section's own scalars -- which is what a skin
    gets after the merging in `cheetah/__init__.py` has already happened.
    """
    del max_level
    if not isinstance(section, dict):
        return {}
    return {key: value for key, value in section.items()
            if not isinstance(value, dict)}


def rounder(value: Any, ndigits: Any) -> Any:
    """Round a number, or a sequence of them. WeeWX's own, and its shape.

    A *plain list* comes back for anything iterable, which is what WeeWX
    does and is not a detail. An extension rounds a whole value tuple --

        obs_vt = rounder(obs_vt, places)

    -- and a version that rebuilt the same type turned
    `ValueTuple(values, unit, group)` into `ValueTuple(<generator>, None,
    None)`. Every chart then had one point in it, made of the first
    timestamp, the second timestamp, and the entire list of values, and the
    page drew a flat line with `undefined` along the bottom.
    """
    if ndigits is None or value is None:
        return value
    if isinstance(value, (str, bytes)):
        return value
    if isinstance(value, float):
        return round(value, ndigits) if ndigits else int(value)
    try:
        return [rounder(x, ndigits) for x in value]
    except TypeError:
        pass
    try:
        return round(value, ndigits)
    except TypeError:
        return value


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "yes", "y", "1", "on"):
        return True
    if text in ("false", "no", "n", "0", "off", "none", ""):
        return False
    raise ValueError(f"{value!r} is not a boolean")


def to_int(value: Any) -> Any:
    # A boolean first: `int(float("False"))` raises, and `to_int(to_bool(x))`
    # is how a template turns a setting into a 0 or a 1.
    if isinstance(value, bool):
        return int(value)
    if value is None or str(value).strip().lower() in ("none", ""):
        return None
    return int(float(str(value).strip()))


def to_float(value: Any) -> Any:
    if isinstance(value, bool):
        return float(value)
    if value is None or str(value).strip().lower() in ("none", ""):
        return None
    return float(str(value).strip())


def option_as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def startOfDay(when: Any) -> int:  # noqa: N802
    """Local midnight of the day a moment falls in."""
    import datetime

    return int(datetime.datetime.fromtimestamp(when).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())


def startOfArchiveDay(when: Any) -> int:  # noqa: N802
    """The same, but a record stamped exactly at midnight belongs to the day
    before it -- an archive record covers the interval that *ends* at its
    timestamp."""
    return startOfDay(when - 1)


def archiveDaySpan(when: Any, days_ago: int = 0) -> TimeSpan:  # noqa: N802
    start = startOfArchiveDay(when)
    start = startOfDay(start - days_ago * 86400) if days_ago else start
    return TimeSpan(start, startOfDay(start + 86400 + 3600))


def beaufort(knots: Any) -> Any:
    """The Beaufort number for a wind speed in knots."""
    if knots is None:
        return None
    for number, top in enumerate((1, 3, 6, 10, 16, 21, 27, 33, 40, 47,
                                  55, 63)):
        if knots < top:
            return number
    return 12


def _install_modules() -> None:
    """Put the names in `sys.modules`, so `import weewx.units` finds them."""
    from . import tags as tags_module

    value_helper = _value_helper(tags_module)

    weewx = types.ModuleType("weewx")
    weewx.__path__ = []  # type: ignore[attr-defined]
    weewx.US = units.US
    weewx.METRIC = units.METRIC
    weewx.METRICWX = units.METRICWX
    weewx.debug = 0
    weewx.__version__ = "5.1.0"

    class UnknownType(ValueError):
        """A reading nothing knows about. WeeWX raises this by name."""

    class UnknownAggregation(ValueError):
        """An aggregate nothing knows how to work out."""

    class CannotCalculate(ValueError):
        """Known, but not from what is here."""

    weewx.UnknownType = UnknownType
    weewx.UnknownAggregation = UnknownAggregation
    weewx.CannotCalculate = CannotCalculate

    unit_module = types.ModuleType("weewx.units")
    unit_module.ValueTuple = ValueTuple
    unit_module.ValueHelper = value_helper
    unit_module.Converter = Converter
    unit_module.Formatter = Formatter
    unit_module.UnitInfoHelper = UnitInfoHelper
    unit_module.ObsInfoHelper = ObsInfoHelper
    unit_module.convert = lambda vt, to: Converter().convert(vt) \
        if to is None else ValueTuple(
            units.convert(ValueTuple(vt)[0], ValueTuple(vt)[1], to), to,
            ValueTuple(vt)[2])
    unit_module.convertStd = lambda vt, system: ValueTuple(vt)
    unit_module.getStandardUnitType = units.unit_of
    unit_module.obs_group_dict = dict(units.GROUPS)
    unit_module.std_groups = units.SYSTEMS
    unit_module.unit_constants = {"US": units.US, "METRIC": units.METRIC,
                                  "METRICWX": units.METRICWX}
    unit_module.mph_to_knot = lambda x: None if x is None else x * 0.868976242
    unit_module.kph_to_knot = lambda x: None if x is None else x * 0.539956803
    unit_module.mps_to_knot = lambda x: None if x is None else x * 1.94384449
    unit_module.SECS_PER_DAY = 86400

    tags_shim = types.ModuleType("weewx.tags")
    tags_shim.TimespanBinder = _timespan_binder(tags_module)

    cheetah = types.ModuleType("weewx.cheetahgenerator")
    cheetah.SearchList = SearchList

    formulas = types.ModuleType("weewx.wxformulas")
    formulas.beaufort = beaufort
    formulas.heating_degrees = lambda t, base: (
        None if t is None else max(base - t, 0))
    formulas.cooling_degrees = lambda t, base: (
        None if t is None else max(t - base, 0))

    xtypes = types.ModuleType("weewx.xtypes")
    xtypes.get_series = _get_series
    xtypes.get_aggregate = _get_aggregate

    weeutil = types.ModuleType("weeutil")
    weeutil.__path__ = []  # type: ignore[attr-defined]

    weeutil_weeutil = types.ModuleType("weeutil.weeutil")
    for name, thing in (("TimeSpan", TimeSpan), ("rounder", rounder),
                        ("to_bool", to_bool), ("to_int", to_int),
                        ("to_float", to_float),
                        ("option_as_list", option_as_list),
                        ("startOfDay", startOfDay),
                        ("startOfArchiveDay", startOfArchiveDay),
                        ("archiveDaySpan", archiveDaySpan)):
        setattr(weeutil_weeutil, name, thing)

    weeutil_config = types.ModuleType("weeutil.config")
    weeutil_config.search_up = search_up
    weeutil_config.accumulateLeaves = accumulateLeaves
    weeutil_config.deep_copy = lambda d: dict(d) if isinstance(d, dict) else d

    weeutil_logger = types.ModuleType("weeutil.logger")
    weeutil_logger.setup = lambda *a, **k: None

    for name, module in (("weewx", weewx), ("weewx.units", unit_module),
                         ("weewx.tags", tags_shim),
                         ("weewx.cheetahgenerator", cheetah),
                         ("weewx.wxformulas", formulas),
                         ("weewx.xtypes", xtypes),
                         ("weeutil", weeutil),
                         ("weeutil.weeutil", weeutil_weeutil),
                         ("weeutil.config", weeutil_config),
                         ("weeutil.logger", weeutil_logger)):
        sys.modules[name] = module
        if "." in name:
            parent, child = name.rsplit(".", 1)
            setattr(sys.modules[parent], child, module)


def _get_series(obs_type: str, timespan: Any, db_manager: Any,
                aggregate_type: Any = None, aggregate_interval: Any = None,
                **_kwargs: Any) -> tuple:
    """A time series, as `weewx.xtypes.get_series` gives one.

    Three value tuples: when each bucket starts, when it stops, and what is
    in it.
    """
    reader = getattr(db_manager, "reader", None)
    if reader is None:
        raise ValueError("get_series was handed something that is not a "
                         "database")
    found = reader.series(obs_type, timespan[0], timespan[1],
                          aggregate=aggregate_type,
                          interval=aggregate_interval)
    unit, group = units.unit_of(obs_type, reader.system, aggregate_type)
    starts = found.start or found.time
    stops = found.stop or found.time
    return (ValueTuple(list(starts), "unix_epoch", "group_time"),
            ValueTuple(list(stops), "unix_epoch", "group_time"),
            ValueTuple(list(found.values), unit, group))


def _get_aggregate(obs_type: str, timespan: Any, aggregate_type: str,
                   db_manager: Any, **_kwargs: Any) -> ValueTuple:
    reader = getattr(db_manager, "reader", None)
    if reader is None:
        raise ValueError("get_aggregate was handed something that is not a "
                         "database")
    value = reader.aggregate(obs_type, timespan[0], timespan[1],
                             aggregate_type)
    unit, group = units.unit_of(obs_type, reader.system, aggregate_type)
    return ValueTuple(value, unit, group)


def install() -> None:
    """Make `import weewx` work, once per process."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    if "weewx" in sys.modules:
        log.info("weewx is already imported in this process; a skin's own "
                 "code will use that rather than the compatibility layer")
        return
    _install_modules()
    log.debug("the WeeWX compatibility layer is in place")


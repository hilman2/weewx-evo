"""What a skin needs, and what a WeeWX skin thinks it needs.

Two things live here and they are not the same.

**The toolkit.** `SearchList`, `ValueHelper`, `TimeSpan`, a database an
extension can run SQL against, the small helpers every skin uses. These are
built on `tags`, `series` and `units` -- `ValueHelper` *is* our `Value`,
`TimespanBinder` *is* our `Span` -- and the skins that ship import them
straight from here, by name, like any other module.

**The shim.** `install_weewx_names()` puts those same objects into
`sys.modules` under WeeWX's names, so that a skin written for WeeWX --
Belchertown, or whatever somebody downloads tomorrow -- runs unaltered. It
is only called when a skin that needs it is loaded, and the skins that ship
never do: they import from here directly, because they are ours.

That split is the point. A skin from outside gets a translation layer and
keeps working; a skin from inside gets a normal import and no magic.
"""

from __future__ import annotations

import logging
import sys
import types
from collections.abc import Sequence
from typing import Any

from . import units
from .series import Reader
from .tags import COMPASS, Span, Value

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

    def __new__(cls, *args: Any) -> ValueTuple:
        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            args = tuple(args[0])
        while len(args) < 3:
            args = (*args, None)
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

    def _arith(self, other: Any, how: Any) -> ValueTuple:
        if isinstance(other, (tuple, list)):
            if other[1] != self[1] or other[2] != self[2]:
                raise TypeError(f"cannot combine {self[1]} and {other[1]}")
            other = other[0]
        if self[0] is None or other is None:
            return ValueTuple(None, self[1], self[2])
        return ValueTuple(how(self[0], other), self[1], self[2])

    def __add__(self, other: Any) -> ValueTuple:  # type: ignore[override]
        return self._arith(other, lambda a, b: a + b)

    def __sub__(self, other: Any) -> ValueTuple:
        return self._arith(other, lambda a, b: a - b)

    def __mul__(self, other: Any) -> ValueTuple:  # type: ignore[override]
        return self._arith(other, lambda a, b: a * b)

    def __truediv__(self, other: Any) -> ValueTuple:
        return self._arith(other, lambda a, b: a / b)


class ValueHelper(Value):
    """A number that knows how to print itself.

    Our `Value`, with the constructor a skin's code writes: a value
    tuple, a context, and the formatter and converter it was handed.
    """

    def __init__(self, value_t: Any = None, context: str = "current",
                 formatter: Any = None, converter: Any = None) -> None:
        value, unit, group = ValueTuple(value_t or (None, None, None))
        target = (getattr(converter, "target", None)
                  or getattr(formatter, "target", None))

        # Converted here, because that is where WeeWX does it: a skin adds
        # up rain in whatever the database stores and hands the total over
        # with a converter attached, expecting the printing to deal with
        # it. Our own tags convert at the source instead, so `Value.format`
        # prints what it is given -- right for those, and the reason a
        # skin's own total came out as `1.11 in` on a page in millimetres.
        wanted = target.unit(group) if (target and group) else None
        if wanted and unit and wanted != unit and value is not None:
            try:
                value = units.convert(value, unit, wanted)
                unit = wanted
            except (KeyError, TypeError, ValueError):
                pass

        super().__init__(value, unit, group, context, target)

    @property
    def value_t(self) -> ValueTuple:
        return ValueTuple(self.value, self.unit, self.group)


class UnitInfoHelper:
    """`$unit.label.outTemp`, `$unit.unit_type.pressure`, `$unit.format.x`.

    WeeWX builds it from a formatter and a converter, and an extension does
    the same. Ours is built from a `units.Target`, which is what both of
    those are made of here.
    """

    def __init__(self, formatter: Any = None, converter: Any = None) -> None:
        target = (getattr(converter, "target", None)
                  or getattr(formatter, "target", None)
                  or units.Target())
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


def timespan_binder(timespan: Any, db_lookup: Any = None,
                    context: str = "current", formatter: Any = None,
                    converter: Any = None, **_options: Any) -> Any:
    """A span, as a skin hands one back to a template.

    WeeWX's `TimespanBinder`, built from a formatter and a converter; ours
    is a `Span` built from the tag layer, and both of those are in the
    converter already. The extras are accepted and ignored rather than
    being a TypeError halfway down a page.
    """
    from .tags import Tags

    manager = (getattr(db_lookup, "manager", None)
               or (db_lookup() if callable(db_lookup) else None))
    reader = getattr(manager, "reader", None)
    target = (getattr(converter, "target", None)
              or getattr(formatter, "target", None))
    tags = Tags(reader, target=target,
                unit_system=reader.system if reader else units.US)
    return Span(tags, (timespan[0], timespan[1]), context)


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

    Two audiences, and they read different halves of it.

    A skin from outside reaches for what WeeWX gave it: `converter` and
    `formatter` to turn numbers into text, `skin_dict` and `config_dict` to
    read its settings out of, and `db_binder` to get at the archive through
    a binding name.

    A skin of ours has no bindings to look up and no `weewx.conf` to search:
    `db_manager` is the database, `language` is the language, `derived` is
    what was computed rather than measured. Same object, the short way.
    """

    def __init__(self, skin_dict: dict[str, Any],
                 config_dict: dict[str, Any], reader: Reader,
                 target: units.Target, tags: Any,
                 language: str | None = None,
                 derived: Sequence[str] = ()) -> None:
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
        #: The database. One archive, so no binding to resolve -- WeeWX's
        #: `db_binder.get_manager(search_up(config["StdReport"][report],
        #: "data_binding", "wx_binding"))` is four lookups to arrive here.
        self.db_manager = self.db_binder.manager
        #: What the pages are written in, as a POSIX code (`de`, `en_GB`).
        #: Empty when the operator has not chosen one.
        self.language = language or ""
        #: Readings this installation computes rather than reads off the
        #: hardware. A skin marks them, because a dewpoint that came out of
        #: a formula is a different claim than one off a sensor.
        self.derived = tuple(derived)
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
        # The built-in table underneath, the skin's own words on top. A
        # skin that names no `[Units][[Labels]]` at all is the normal case,
        # and with only the overrides here every chart was labelled
        # `degree_C` instead of the degree sign.
        self.unit_label_dict = {**units.LABELS, **self.target.labels}
        self.unit_format_dict = {**units.FORMATS, **self.target.formats}
        self.time_format_dict = dict(self.target.time_formats)
        # Never empty. An extension does `ordinate_names.index(direction)`
        # to turn a compass point back into a bearing, and an empty list
        # makes that a ValueError saying only "'N/A' is not in list".
        self.ordinate_names = list(self.target.ordinals or COMPASS)

    def toString(self, val_t: Any, context: str = "current",  # noqa: N802
                 addLabel: bool = True,
                 useThisFormat: Any = None,
                 None_string: Any = None,
                 localize: bool = True) -> str:
        del localize
        value, unit, group = ValueTuple(val_t or (None, None, None))
        return Value(value, unit, group, context, self.target).format(
            useThisFormat, None_string, addLabel)

    def get_label_string(self, unit: Any, plural: bool = True) -> str:
        return self.target.label_for(unit, plural)

    def to_ordinal_compass(self, val_t: Any) -> str:
        value, unit, group = ValueTuple(val_t or (None, None, None))
        return Value(value, unit, group, "current",
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

    def get_manager(self, *_args: Any, **_kwargs: Any) -> Manager:
        return self.manager

    def __call__(self, *_args: Any, **_kwargs: Any) -> Manager:
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
        except Exception as exc:
            log.debug("a skin's SQL did not run: %s -- %s", sql, exc)
            return None

    def genSql(self, sql: str, params: Any = ()) -> Any:  # noqa: N802
        try:
            yield from self.reader.conn.execute(sql, params or ())
        except Exception as exc:
            log.debug("a skin's SQL did not run: %s -- %s", sql, exc)

    def has_data(self, obs_type: str, timespan: Any) -> bool:
        try:
            start, stop = timespan[0], timespan[1]
            return bool(self.reader.aggregate(obs_type, start, stop,
                                              "not_null"))
        except Exception:
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

    def __new__(cls, start: Any, stop: Any) -> TimeSpan:
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

    A section knows its parent (`weewxconf.Section`), and the root is its
    own -- so the walk ends there, not by falling off.
    """
    node = section
    while isinstance(node, dict):
        if key in node:
            return node[key]
        parent = getattr(node, "parent", None)
        if parent is node or not isinstance(parent, dict):
            break
        node = parent
    if default:
        return default[0]
    raise KeyError(key)


def accumulateLeaves(section: Any,  # noqa: N802
                     max_level: int = 99) -> dict[str, Any]:
    """Every scalar in a section and in the ones above it, flattened.

    WeeWX's, transcribed. `max_level` counts how far up to go, so a skin can
    say "this observation and its context, not the whole file".

    What it is for: `[[[day]]]` sets `aggregate_interval` once and every
    observation under it inherits it, unless it names its own.
    """
    if not isinstance(section, dict):
        return {}
    own = {key: value for key, value in section.items()
           if not isinstance(value, dict)}
    parent = getattr(section, "parent", None)
    if max_level <= 0 or parent is section or not isinstance(parent, dict):
        return own
    merged = accumulateLeaves(parent, max_level - 1)
    merged.update(own)
    return merged


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


def mph_to_knot(value: Any) -> Any:
    """Miles an hour to knots. WeeWX's factor, not a recomputed one."""
    return None if value is None else value * 0.868976242


def kph_to_knot(value: Any) -> Any:
    return None if value is None else value * 0.539956803


def mps_to_knot(value: Any) -> Any:
    return None if value is None else value * 1.94384449


def get_series(obs_type: str, timespan: Any, db_manager: Any,
               aggregate_type: Any = None, aggregate_interval: Any = None,
               **_kwargs: Any) -> tuple:
    """A reading over a span, as three value tuples.

    When each bucket starts, when it stops, and what is in it. WeeWX's
    `xtypes.get_series`, which is what a skin's code calls it.
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


def get_aggregate(obs_type: str, timespan: Any, aggregate_type: str,
                  db_manager: Any, **_kwargs: Any) -> ValueTuple:
    """One number for one span."""
    reader = getattr(db_manager, "reader", None)
    if reader is None:
        raise ValueError("get_aggregate was handed something that is not a "
                         "database")
    value = reader.aggregate(obs_type, timespan[0], timespan[1],
                             aggregate_type)
    unit, group = units.unit_of(obs_type, reader.system, aggregate_type)
    return ValueTuple(value, unit, group)


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
    unit_module.ValueHelper = ValueHelper
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
    # The standard schema *and* what the drivers said, because a skin
    # extension reading this to decide how to draw a column has the same
    # problem the core does: `extraTemp9` is not in the standard schema and
    # only the driver knows it is a temperature.
    unit_module.obs_group_dict = units.all_groups()
    unit_module.std_groups = units.SYSTEMS
    unit_module.unit_constants = {"US": units.US, "METRIC": units.METRIC,
                                  "METRICWX": units.METRICWX}
    unit_module.mph_to_knot = mph_to_knot
    unit_module.kph_to_knot = kph_to_knot
    unit_module.mps_to_knot = mps_to_knot
    unit_module.SECS_PER_DAY = 86400

    tags_shim = types.ModuleType("weewx.tags")
    tags_shim.TimespanBinder = timespan_binder

    cheetah = types.ModuleType("weewx.cheetahgenerator")
    cheetah.SearchList = SearchList

    formulas = types.ModuleType("weewx.wxformulas")
    formulas.beaufort = beaufort
    formulas.heating_degrees = lambda t, base: (
        None if t is None else max(base - t, 0))
    formulas.cooling_degrees = lambda t, base: (
        None if t is None else max(t - base, 0))

    xtypes = types.ModuleType("weewx.xtypes")
    xtypes.get_series = get_series
    xtypes.get_aggregate = get_aggregate

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


def install_weewx_names() -> None:
    """Make `import weewx` work, once per process.

    For a skin written for WeeWX. The skins that ship here import from this
    module by name and never need it.
    """
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


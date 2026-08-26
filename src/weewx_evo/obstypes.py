"""How each observation type is aggregated.

WeeWX keeps this in a global `ChainMap` that modules mutate at import time
(`weewx.accum.accum_dict`). Here it is an ordinary object you pass around, so
two policies can exist at once -- which is what makes the differential test
against a real database possible.

The defaults below are WeeWX's `DEFAULTS_INI` verbatim. Changing a value here
changes recorded history, so they are transcribed, not reasoned about.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class ObsPolicy:
    """What to do with one observation type."""

    accumulator: str = "scalar"  # scalar | vector | firstlast
    adder: str = "add"           # add | add_wind | check_units | noop
    merger: str = "minmax"       # minmax | avg
    extractor: str = "avg"       # avg | sum | first | last | min | max | count | wind | noop


_DEFAULT = ObsPolicy()

# Transcribed from weewx/accum.py DEFAULTS_INI. Order is irrelevant; values are not.
_DEFAULTS: dict[str, ObsPolicy] = {
    "consBatteryVoltage": replace(_DEFAULT, extractor="last"),
    "dateTime": replace(_DEFAULT, adder="noop"),
    "dayET": replace(_DEFAULT, extractor="last"),
    "dayRain": replace(_DEFAULT, extractor="last"),
    "ET": replace(_DEFAULT, extractor="sum"),
    "hourRain": replace(_DEFAULT, extractor="last"),
    "rain": replace(_DEFAULT, extractor="sum"),
    "rain24": replace(_DEFAULT, extractor="last"),
    "monthET": replace(_DEFAULT, extractor="last"),
    "monthRain": replace(_DEFAULT, extractor="last"),
    "stormRain": replace(_DEFAULT, extractor="last"),
    "totalRain": replace(_DEFAULT, extractor="last"),
    "txBatteryStatus": replace(_DEFAULT, extractor="last"),
    "usUnits": replace(_DEFAULT, adder="check_units"),
    "wind": ObsPolicy(accumulator="vector", adder="add", merger="minmax", extractor="wind"),
    "windDir": replace(_DEFAULT, extractor="noop"),
    "windGust": replace(_DEFAULT, extractor="noop"),
    "windGustDir": replace(_DEFAULT, extractor="noop"),
    "windGust10": replace(_DEFAULT, extractor="last"),
    "windGustDir10": replace(_DEFAULT, extractor="last"),
    "windrun": replace(_DEFAULT, extractor="sum"),
    "windSpeed": ObsPolicy(accumulator="scalar", adder="add_wind", merger="avg", extractor="noop"),
    "windSpeed2": replace(_DEFAULT, extractor="last"),
    "windSpeed10": replace(_DEFAULT, extractor="last"),
    "yearET": replace(_DEFAULT, extractor="last"),
    "yearRain": replace(_DEFAULT, extractor="last"),
    "lightning_strike_count": replace(_DEFAULT, extractor="sum"),
}


class Policy:
    """The aggregation policy for a whole installation.

    `overrides` mirrors the `[Accumulator]` section of weewx.conf: a mapping of
    observation type to the fields that differ from the default.
    """

    __slots__ = ("_types",)

    def __init__(self, overrides: dict[str, dict[str, str]] | None = None) -> None:
        self._types = dict(_DEFAULTS)
        for obs_type, fields in (overrides or {}).items():
            base = self._types.get(obs_type, _DEFAULT)
            self._types[obs_type] = replace(base, **fields)

    def __getitem__(self, obs_type: str) -> ObsPolicy:
        return self._types.get(obs_type, _DEFAULT)


DEFAULT_POLICY = Policy()

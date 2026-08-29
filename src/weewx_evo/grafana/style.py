"""How a weather reading should be drawn, as against how Grafana draws it.

Grafana's defaults were chosen for server metrics: a line, an automatic
axis, a palette that hands out colours in the order series arrive. Three of
those are not merely plain on a weather dashboard, they are *wrong*, and each
one is the sort of wrong that looks like working software.

**A wind direction drawn as a line is a fence.** It goes 358, 359, 1 -- and
the line drops the full height of the panel, twice a minute on a gusty day.
The reading is circular and a line between two of its values means nothing.
So: points, never joined, on an axis pinned to 0-360 with the compass at the
ticks.

**Rain drawn as a line is a lie about the axis.** Grafana scales to the data,
so a day with 0.2 mm and a day with 40 mm produce identical-looking charts,
and a dry day produces a dramatic one out of sensor noise. Rain is bars, from
zero, always.

**Humidity on an automatic axis turns 60-65 % into a crisis.** It is a
percentage; it runs 0 to 100 whatever happened today.

And one that is not a correction but the reason to bother: **a temperature
line whose colour is the temperature reads without the axis.** Grafana has a
continuous blue-yellow-red mode and almost nobody uses it, because a CPU
temperature has no natural scale. Air temperature does -- everybody who looks
at this dashboard already knows what blue means.

## Style hangs on the unit group, not the name

`units.group_of` answers for the driver's own fields too (`units.contribute`),
so a station with a soil probe and four extra thermometers gets the
temperature treatment on all of them without this file learning their names.
The handful of exceptions below are genuinely about a particular reading --
a gust drawn behind the wind speed it belongs to -- and not about a family.
"""

from __future__ import annotations

from typing import Any

from .. import units

#: A palette chosen for weather and for both of Grafana's themes. Mid-toned
#: on purpose: a colour that sings on the dark theme is invisible on the
#: light one, and a dashboard is read on a phone in the garden as well as on
#: a monitor in a dark room.
COLORS = {
    "dewpoint": "#56A64B",     # green, the convention on every weather chart
    "humidity": "#37A2A6",     # teal, so it is not read as another temperature
    "pressure": "#8F3BB8",     # violet, and alone in that
    "wind": "#4A6FA5",         # muted blue
    "gust": "#A5B8D0",         # the same blue, stepped back behind it
    "rain": "#3274D9",
    "radiation": "#E0B400",    # the colour of the thing it measures
    "uv": "#B877D9",
    "battery": "#E02F44",
    "plain": "#5C7080",
}

#: Readings whose treatment is about that reading and not its family.
BY_NAME = {
    "dewpoint": {"color": COLORS["dewpoint"]},
    "windchill": {"color": COLORS["dewpoint"]},
    "heatindex": {"color": "#FF9830"},
    "appTemp": {"color": "#FF9830"},
    # Behind the wind speed rather than beside it: the gust is the envelope
    # of the same measurement, and two equal lines invite reading them as
    # two different winds.
    "windGust": {"color": COLORS["gust"], "fillOpacity": 30, "lineWidth": 0},
    "windSpeed": {"color": COLORS["wind"]},
    "UV": {"color": COLORS["uv"]},
    "radiation": {"color": COLORS["radiation"], "fillOpacity": 25},
}


def group_style(group: str | None, unit: str | None) -> dict:
    """The drawing rules for one unit group. See the module docstring."""
    if group == "group_temperature":
        return {
            "decimals": 1,
            # The colour *is* the reading. Grafana interpolates blue to red
            # across the values actually present, so a winter week and a
            # summer week both use the whole range rather than both being red.
            "color": {"mode": "continuous-BlYlRd"},
            "fillOpacity": 10,
            "lineWidth": 2,
            # Freezing, in whatever the axis is counting in. A gardener reads
            # this line before they read the numbers.
            "thresholds": _freezing(unit),
        }
    if group in ("group_percent", "group_humidity"):
        return {"decimals": 0, "min": 0, "max": 100,
                "color": {"mode": "fixed", "fixedColor": COLORS["humidity"]},
                "fillOpacity": 8, "lineWidth": 1}
    if group == "group_pressure":
        # A barometer moves through a few millibars in a day. A fill would be
        # a solid block with a wobble on top.
        return {"decimals": 1, "fillOpacity": 0, "lineWidth": 2,
                "color": {"mode": "fixed", "fixedColor": COLORS["pressure"]}}
    if group == "group_speed":
        return {"decimals": 1, "min": 0, "fillOpacity": 12, "lineWidth": 1,
                "color": {"mode": "fixed", "fixedColor": COLORS["wind"]}}
    if group == "group_direction":
        # See the module docstring. Points, and the compass on the axis.
        return {"decimals": 0, "min": 0, "max": 360, "drawStyle": "points",
                "pointSize": 4, "lineWidth": 0, "fillOpacity": 0,
                "spanNulls": False,
                "color": {"mode": "fixed", "fixedColor": COLORS["wind"]}}
    if group in ("group_rain", "group_rainrate"):
        return {"decimals": 1, "min": 0, "drawStyle": "bars",
                "fillOpacity": 80, "lineWidth": 0,
                "color": {"mode": "fixed", "fixedColor": COLORS["rain"]}}
    if group == "group_radiation":
        return {"decimals": 0, "min": 0, "fillOpacity": 25, "lineWidth": 1,
                "color": {"mode": "fixed", "fixedColor": COLORS["radiation"]}}
    if group == "group_uv":
        return {"decimals": 1, "min": 0, "fillOpacity": 15, "lineWidth": 1,
                "color": {"mode": "fixed", "fixedColor": COLORS["uv"]}}
    if group == "group_volt":
        return {"decimals": 2, "fillOpacity": 0, "lineWidth": 1,
                "color": {"mode": "fixed", "fixedColor": COLORS["battery"]}}
    return {"decimals": 1, "fillOpacity": 8, "lineWidth": 1,
            "color": {"mode": "fixed", "fixedColor": COLORS["plain"]}}


def _freezing(unit: str | None) -> dict | None:
    """Zero degrees, in the unit the axis is actually counting in.

    Written out rather than assumed to be 0: a page published in Fahrenheit
    freezes at 32, and a threshold line at 0 there sits off the bottom of
    every chart between October and April, marking nothing.
    """
    point = {"degree_C": 0, "degree_F": 32, "degree_K": 273.15}.get(unit or "")
    if point is None:
        return None
    return {"mode": "absolute",
            "steps": [{"color": "#3274D9", "value": None},
                      {"color": "transparent", "value": point}]}


#: A weather scale for a single figure, in degrees Celsius. Not the gradient:
#: `continuous-BlYlRd` colours a value by where it sits among the values on
#: screen, so one number is always at one end of its own range and 21.9 °C
#: was printed in the red of a heatwave. A stat panel needs absolute steps --
#: what the number means, not where it ranks.
TEMPERATURE_STEPS = ((None, "#3274D9"), (0, "#5794F2"), (10, "#37A2A6"),
                     (20, "#56A64B"), (26, "#E0B400"), (32, "#FF9830"),
                     (36, "#E02F44"))


def stat_thresholds(obs: str, system: int) -> dict:
    """The colour of one figure, in the unit the figure is printed in.

    Converted rather than assumed: the same scale on a Fahrenheit page has to
    turn amber at 79, not at 26, or a summer afternoon reads as freezing.
    """
    if units.group_of(obs) != "group_temperature":
        return {"mode": "absolute", "steps": [{"color": "text", "value": None}]}
    unit, _group = units.unit_of(obs, system)
    steps = []
    for point, color in TEMPERATURE_STEPS:
        if point is None:
            steps.append({"color": color, "value": None})
            continue
        value = units.convert(float(point), "degree_C", unit)
        steps.append({"color": color,
                      "value": round(float(value)) if value is not None
                      else point})
    return {"mode": "absolute", "steps": steps}


def for_obs(obs: str, system: int, extra: dict | None = None) -> dict:
    """Everything a panel needs to know about drawing one reading."""
    group = units.group_of(obs, extra=extra)
    unit, _group = units.unit_of(obs, system)
    style = dict(group_style(group, unit))
    style.update(BY_NAME.get(obs, {}))
    return style


def axis_for(obs: str, system: int) -> dict:
    """Extra axis settings a reading needs beyond a min and a max."""
    if units.group_of(obs) == "group_direction":
        # The compass at the ticks. Without this the axis counts 0, 50, 100
        # and the reader converts degrees to points in their head.
        return {"axisLabel": "", "axisSoftMin": 0, "axisSoftMax": 360}
    return {}


def field_config(obs: str, system: int, unit_id: str,
                 label: str = "") -> dict:
    """A Grafana `fieldConfig.defaults` for one reading, fully dressed."""
    style = for_obs(obs, system)
    custom = {
        "drawStyle": style.get("drawStyle", "line"),
        "lineWidth": style.get("lineWidth", 1),
        "fillOpacity": style.get("fillOpacity", 0),
        "pointSize": style.get("pointSize", 5),
        "showPoints": "always" if style.get("drawStyle") == "points" else "auto",
        # A gap in the readings is a gap. Joining across it draws a straight
        # line through the hours a station was off and reads as data.
        "spanNulls": False,
        "lineInterpolation": "smooth" if style.get("drawStyle") not in
                             ("bars", "points") else "linear",
        "gradientMode": "opacity" if style.get("fillOpacity", 0) else "none",
        "axisSoftMin": style.get("min"),
        "axisSoftMax": style.get("max"),
    }
    custom.update(axis_for(obs, system))

    defaults: dict[str, Any] = {
        "unit": unit_id,
        "decimals": style.get("decimals"),
        "color": style.get("color", {"mode": "palette-classic"}),
        "custom": {k: v for k, v in custom.items() if v is not None},
    }
    if style.get("min") is not None:
        defaults["min"] = style["min"]
    if style.get("max") is not None:
        defaults["max"] = style["max"]
    if style.get("thresholds"):
        defaults["thresholds"] = style["thresholds"]
        defaults["custom"]["thresholdsStyle"] = {"mode": "line"}
    if label:
        defaults["displayName"] = label
    return defaults


def describe(obs: str, system: int, words: Any = None) -> str:
    """The line under a panel's title, in the little `i`.

    Says what is measured and in what -- the two things somebody looking at
    an unfamiliar station's dashboard wants and cannot get from a legend
    reading `outTemp`. So it is translated: it is the sentence that exists
    for the reader who does not already know.
    """
    unit, _group = units.unit_of(obs, system)
    name = words.obs(obs) if words is not None else units.obs_label(obs)
    where = units.label(unit, plural=True).strip() if unit else ""
    return f"{name}, {where}." if where else f"{name}."

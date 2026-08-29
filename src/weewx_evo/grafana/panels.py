"""A plot definition, as a Grafana panel.

`plots.toml` belongs to weewx-evo and the renderers are consumers -- that is
the arrangement `plots.py` exists for, and Grafana joins Deck, the image
generator and the JSON feed as the fourth of them. A hundred charts that
fifteen years of WeeWX stations found sufficient become a hundred panels
without anybody typing a title.

How each one is *drawn* is `style.py`. This file is the assembly: targets,
overrides, grid, and the two things Grafana gets wrong about units.

**A guessed Grafana unit prints the raw string on the axis.** Grafana names
its units with its own identifiers (`celsius`, `velocityms`), and one that
does not exist is not an error -- the axis simply says `pressurevpd`. So only
identifiers that are certainly Grafana's are used, and everything else becomes
`suffix:<our own label>`, which is always right and never prettier than it
needs to be.

**The units are the upload's, not the plot's.** A feed converts on the way
out; here the conversion already happened when the point was written, so a
panel reading a bucket written in metricwx says degrees Celsius whatever the
plot asked for. Taking the plot's unit would put the right words under the
wrong numbers -- the same fault that reached a published page twice through
the live push.

**A panel is also a picture.** Every one of these has to survive being
rendered on its own at 1200x500 and put on a web page by FTP, because that is
how a Grafana chart reaches somebody who is not allowed into Grafana. So
nothing here depends on a hover, and the legend carries what the tooltip
would otherwise have to.
"""

from __future__ import annotations

from typing import Any

from .. import units
from . import query_influx as flux
from . import style

#: Our unit names against Grafana's own identifiers, and only where the
#: identifier is certain. Everything absent falls back to a suffix built from
#: `units.label`, which cannot be wrong.
GRAFANA_UNITS = {
    "degree_C": "celsius",
    "degree_F": "fahrenheit",
    "degree_K": "kelvin",
    "percent": "percent",
    "meter_per_second": "velocityms",
    "km_per_hour": "velocitykmh",
    "mile_per_hour": "velocitymph",
    "knot": "velocityknot",
    # Not `lengthmm` or `lengthcm`: those carry SI prefixes, so 0.5 mm of rain
    # is drawn as "500 µm" and a light shower reads like a laboratory result.
    # A weather page counts rain in millimetres at every depth.
    "meter": "lengthm",
    "km": "lengthkm",
    "inch": "lengthin",
    "foot": "lengthft",
    "mbar": "pressurembar",
    "hPa": "pressurehpa",
    "degree_compass": "degree",
    "second": "s",
    "minute": "m",
    "hour": "h",
    "volt": "volt",
    "watt": "watt",
}

#: Grafana's grid is 24 columns wide. A full-width panel, a half, a third.
FULL, HALF, THIRD = 24, 12, 8


def unit_for(obs: str, system: int) -> str:
    """What a panel's axis should say, in Grafana's language."""
    unit, _group = units.unit_of(obs, system)
    if unit is None:
        return ""
    known = GRAFANA_UNITS.get(unit)
    if known:
        return known
    label = units.label(unit, plural=False).strip()
    return f"suffix:{label}" if label else ""


def grid(x: int, y: int, width: int, height: int = 8) -> dict:
    return {"x": x, "y": y, "w": width, "h": height}


def _target(server: Any, obs: str, aggregate: str, where: str, weight: bool,
            ref: str) -> dict:
    return {
        "refId": ref,
        "query": flux.for_line(server.bucket, server.measurement, obs,
                               aggregate, where, weight),
        "datasource": server.reference(),
    }


def _override(ref: str, obs: str, system: int, label: str = "") -> dict:
    """A second reading in a panel, drawn its own way.

    The panel's defaults come from its first reading, so everything after it
    needs saying again. A dewpoint under a temperature is the ordinary case:
    same axis, same unit, and it must not also be painted with the
    temperature's blue-to-red gradient or the two become indistinguishable.
    """
    look = style.for_obs(obs, system)
    properties: list[dict] = [
        {"id": "color", "value": look.get(
            "color", {"mode": "fixed", "fixedColor": style.COLORS["plain"]})},
        {"id": "custom.drawStyle", "value": look.get("drawStyle", "line")},
        {"id": "custom.fillOpacity", "value": look.get("fillOpacity", 0)},
        {"id": "custom.lineWidth", "value": look.get("lineWidth", 1)},
    ]
    if label:
        properties.append({"id": "displayName", "value": label})
    return {"matcher": {"id": "byFrameRefID", "options": ref},
            "properties": properties}


def timeseries(server: Any, readings: list[tuple[str, str, str]], title: str,
               position: dict, where: str = "", weight: bool = False,
               panel_id: int = 1, description: str = "",
               time_from: str = "") -> dict:
    """One chart. `readings` is (obs, aggregate, label), first one leads.

    The first reading decides the axis, the unit and the colour mode, because
    a panel has one y-axis and the alternative -- two axes on a chart the size
    of a postcard -- is how a wind panel becomes unreadable.
    """
    if not readings:
        readings = [("outTemp", "", "")]
    lead, _lead_aggregate, lead_label = readings[0]

    targets, overrides = [], []
    for index, (obs, aggregate, label) in enumerate(readings):
        ref = chr(ord("A") + index)
        targets.append(_target(server, obs, aggregate, where, weight, ref))
        if index:
            overrides.append(_override(ref, obs, server.system, label))
        elif label:
            overrides.append({"matcher": {"id": "byFrameRefID", "options": ref},
                              "properties": [{"id": "displayName",
                                              "value": label}]})

    # With `keep` the only label left is the location, so a comparison names
    # its stations and a single-station panel names its reading -- rather
    # than both printing a Flux record.
    naming = ("${__field.labels.location}" if not where
              else (lead_label or server.words.obs(lead)))

    panel = {
        "id": panel_id,
        "type": "timeseries",
        "title": title,
        "description": (description
                        or style.describe(lead, server.system,
                                          server.words)),
        "datasource": server.reference(),
        "gridPos": position,
        "targets": targets,
        "fieldConfig": {
            "defaults": style.field_config(lead, server.system,
                                           unit_for(lead, server.system),
                                           naming),
            "overrides": overrides,
        },
        "options": {
            "legend": {
                # One series under a title that names it is a legend saying
                # the same word twice. Several, or several locations from one
                # query, and the legend is the only thing telling them apart.
                "showLegend": len(readings) > 1 or not where,
                "displayMode": "list",
                "placement": "bottom",
                "calcs": [],
            },
            "tooltip": {"mode": "multi" if len(readings) > 1 or not where
                        else "single", "sort": "none"},
        },
    }
    if time_from:
        panel["timeFrom"] = time_from
    return panel


def panel(plot: Any, server: Any, position: dict, location: str = "",
          weight: bool = False, panel_id: int = 1) -> dict:
    """One plot from `plots.toml`, as a panel.

    A plot's own colours are kept only where a single location is drawn. The
    same plot across five locations is five series out of one query, and
    pinning them all to the colour somebody chose for `outTemp` makes the
    comparison it exists for unreadable.
    """
    readings = [(line.obs, line.aggregate, line.label) for line in plot.lines]
    low, high = (list(plot.yscale) + [None, None, None])[:2]

    built = timeseries(
        server, readings, plot.title or _title(plot, server.words),
        position,
        where=location, weight=weight, panel_id=panel_id,
        # Each plot keeps the span it was defined for. Without this every
        # panel follows the dashboard's picker, and a set that carefully
        # distinguishes a day, a week, a month and a year shows four copies
        # of the same chart.
        time_from=f"{max(1, int(plot.time_length // 60))}m")

    defaults = built["fieldConfig"]["defaults"]
    # A fixed axis is how two charts stay comparable, and `plots.toml` is
    # where somebody said so.
    if low is not None:
        defaults["min"] = low
    if high is not None:
        defaults["max"] = high

    if location:
        for index, line in enumerate(plot.drawn):
            if not line.color:
                continue
            ref = chr(ord("A") + index)
            for override in built["fieldConfig"]["overrides"]:
                if override["matcher"]["options"] == ref:
                    override["properties"].append(
                        {"id": "color", "value": {"mode": "fixed",
                                                  "fixedColor": line.color}})
                    break
            else:
                defaults["color"] = {"mode": "fixed",
                                     "fixedColor": line.color}
    return built


def _title(plot: Any, words: Any = None) -> str:
    """A title from the readings, where the plot set gave none.

    The same fallback the JSON feed uses, so a chart is called the same thing
    wherever it is drawn -- and in the same language, which is why the plot's
    own label still wins: somebody who wrote one meant it.
    """
    names = [line.label or (words.obs(line.obs) if words is not None
                            else units.obs_label(line.obs))
             for line in plot.lines]
    return ", ".join(dict.fromkeys(names)) or plot.name


def now(server: Any, obs: str, title: str, position: dict, where: str = "",
        panel_id: int = 1, aggregate: str = "last",
        repeat: str = "") -> dict:
    """The reading as it stands, with its own last day behind it.

    The number is what somebody came for; the sparkline behind it is what
    stops the number being ambiguous -- 4 °C falling and 4 °C rising are
    different mornings, and a bare figure cannot say which.
    """
    look = style.for_obs(obs, server.system)
    panel = {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "description": style.describe(obs, server.system, server.words),
        "datasource": server.reference(),
        "gridPos": position,
        "targets": [_target(server, obs, "", where, False, "A")],
        "fieldConfig": {
            "defaults": {
                "unit": unit_for(obs, server.system),
                "decimals": look.get("decimals", 1),
                # Steps, not the gradient the chart uses. See `style.py`.
                "color": {"mode": "thresholds"},
                "thresholds": style.stat_thresholds(obs, server.system),
                "custom": {"fillOpacity": 20, "lineWidth": 1},
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": [aggregate], "fields": "",
                              "values": False},
            # The title already says which location and which reading. Adding
            # the series name printed "outTemp kirchdorf 21.9" across a tile
            # whose heading was "kirchdorf".
            "textMode": "value",
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "center",
        },
    }
    if repeat:
        # One panel definition, one per location, laid out by Grafana. A row
        # of these is what makes a five-console dashboard readable without
        # anybody maintaining five copies of it.
        panel["repeat"] = repeat
        panel["repeatDirection"] = "h"
    return panel


def row(title: str, y: int, panel_id: int, collapsed: bool = False,
        inside: list[dict] | None = None) -> dict:
    """A heading. Collapsed rows are how a long dashboard stays scannable.

    Grafana keeps a collapsed row's panels *inside* it and an expanded row's
    beside it, which is a real difference and not a detail: put them in the
    wrong place and the row is empty when opened.
    """
    return {
        "id": panel_id,
        "type": "row",
        "title": title,
        "gridPos": grid(0, y, FULL, 1),
        "collapsed": collapsed,
        "panels": list(inside or []) if collapsed else [],
    }


def text(title: str, body: str, position: dict, panel_id: int = 1) -> dict:
    """A note on the dashboard. Used to say what generated it, and when."""
    return {
        "id": panel_id,
        "type": "text",
        "title": title,
        "gridPos": position,
        "options": {"mode": "markdown", "content": body},
    }


def stat(title: str, query: str, server: Any, position: dict, unit: str = "",
         panel_id: int = 1, thresholds: list | None = None,
         description: str = "") -> dict:
    """A single number from a query written elsewhere. For operations."""
    steps = thresholds or [{"color": "green", "value": None}]
    return {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": server.reference(),
        "gridPos": position,
        "targets": [{"refId": "A", "query": query,
                     "datasource": server.reference()}],
        "fieldConfig": {
            "defaults": {"unit": unit,
                         "thresholds": {"mode": "absolute", "steps": steps},
                         "color": {"mode": "thresholds"}},
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                              "values": True},
            "textMode": "value_and_name",
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "auto",
        },
    }

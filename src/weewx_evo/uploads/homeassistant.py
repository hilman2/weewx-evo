"""Making the station appear in Home Assistant by itself.

Home Assistant will pick up MQTT topics on its own, but only if it is told
what they are: a retained JSON document per reading, on a topic under
`homeassistant/`, saying what the value means and where to find it. Publish
those once and the station shows up as a device with its sensors named,
graphed and unit-aware -- no YAML, no restart, nothing typed twice.

Without it, `weather/outTemp_C` is a string on a broker and Home Assistant
has no idea it is a temperature in Celsius.

This is a hundred lines because MQTT is already here. That is the whole
argument for it: the work was done for the skins, and this is the last step
of it for a different audience.

Two things that are decisions:

**Retained, always.** A discovery message that is not retained is seen only by
a Home Assistant that happened to be running at that second. Retained, it is
handed to one that starts tomorrow. This is the case retention exists for.

**Published once per connection, not per reading.** The definitions do not
change between readings, and re-sending forty documents every ten seconds to
say the same thing would be most of the traffic. They go again after a
reconnect, because a broker that was restarted without persistence has
forgotten them.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

#: What Home Assistant calls the kind of thing a reading is. It uses this to
#: pick an icon, a graph, and which unit conversions to offer -- so a wrong
#: one is not cosmetic: `pressure` on a temperature makes the history graph
#: unreadable.
#:
#: Matched longest first, so `windGust` beats `wind` and `soilTemp1` is a
#: temperature rather than falling through.
DEVICE_CLASS: tuple[tuple[str, str], ...] = (
    ("barometer", "atmospheric_pressure"),
    ("pressure", "atmospheric_pressure"),
    ("altimeter", "atmospheric_pressure"),
    ("outTemp", "temperature"),
    ("inTemp", "temperature"),
    ("dewpoint", "temperature"),
    ("inDewpoint", "temperature"),
    ("windchill", "temperature"),
    ("heatindex", "temperature"),
    ("appTemp", "temperature"),
    ("humidex", "temperature"),
    ("extraTemp", "temperature"),
    ("soilTemp", "temperature"),
    ("leafTemp", "temperature"),
    ("outHumidity", "humidity"),
    ("inHumidity", "humidity"),
    ("extraHumid", "humidity"),
    ("windSpeed", "wind_speed"),
    ("windGust", "wind_speed"),
    ("rainRate", "precipitation_intensity"),
    ("rain", "precipitation"),
    ("radiation", "irradiance"),
    ("illuminance", "illuminance"),
    ("pm2_5", "pm25"),
    ("pm10_0", "pm10"),
    ("co2", "carbon_dioxide"),
    ("consBatteryVoltage", "voltage"),
    ("supplyVoltage", "voltage"),
    ("rxCheckPercent", "signal_strength"),
)

#: Our unit names as Home Assistant writes them. A unit it does not recognise
#: makes the sensor a plain string, which is worse than useless: no graph, no
#: conversion, no statistics.
HA_UNIT: dict[str, str] = {
    "degree_C": "°C",
    "degree_F": "°F",
    "degree_K": "K",
    "percent": "%",
    "mbar": "hPa",          # the same thing, and hPa is what HA lists
    "hPa": "hPa",
    "inHg": "inHg",
    "mmHg": "mmHg",
    "kPa": "kPa",
    "meter_per_second": "m/s",
    "km_per_hour": "km/h",
    "mile_per_hour": "mph",
    "knot": "kn",
    "mm": "mm",
    "cm": "cm",
    "inch": "in",
    "mm_per_hour": "mm/h",
    "cm_per_hour": "cm/h",
    "inch_per_hour": "in/h",
    "watt_per_meter_squared": "W/m²",
    "lux": "lx",
    "microgram_per_meter_cubed": "µg/m³",
    "volt": "V",
    "degree_compass": "°",
    "uv_index": "UV index",
}

#: Readings that are a running total rather than a measurement. Home
#: Assistant graphs and sums these differently, and getting it wrong means a
#: daily rainfall chart that averages instead of adding.
TOTAL = ("dayRain", "rain24", "hourRain", "rainTotal", "dayET", "ET")

_WORDS = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|_")


def readable(obs: str) -> str:
    """`outTemp` as `Out temp`, which is what a person sees in a list."""
    words = [w for w in _WORDS.split(obs) if w]
    if not words:
        return obs
    return " ".join([words[0].capitalize(), *[w.lower() for w in words[1:]]])


def device_class(obs: str) -> str | None:
    for prefix, kind in DEVICE_CLASS:
        if obs.startswith(prefix):
            return kind
    return None


def discovery(obs: str, unit: str | None, topic: str, field: str,
              station: str, prefix: str = "homeassistant") -> tuple[str, str]:
    """One sensor definition, as (topic, payload).

    `field` is the name inside the JSON document -- `outTemp_C` -- while
    `obs` is the plain reading. Both are needed: the template reads the
    first, everything else is decided from the second.
    """
    ident = f"weewx_evo_{_slug(station)}"
    unique = f"{ident}_{obs}"
    payload: dict[str, object] = {
        "name": readable(obs),
        "state_topic": f"{topic}/loop",
        # Reading from the JSON document rather than the individual topic:
        # one subscription instead of forty, and it works whether or not the
        # individual topics are switched on.
        "value_template": "{{ value_json." + field + " | default('', true) }}",
        "unique_id": unique,
        "object_id": unique,
        "device": {
            "identifiers": [ident],
            "name": station or "weewx-evo",
            "manufacturer": "weewx-evo",
            "model": "Weather station",
        },
        # Without this a sensor that stops reporting keeps showing its last
        # value forever, which reads as a station that is fine.
        "expire_after": 3600,
    }
    kind = device_class(obs)
    if kind:
        payload["device_class"] = kind
    ha_unit = HA_UNIT.get(unit or "")
    if ha_unit:
        payload["unit_of_measurement"] = ha_unit
    # A wind bearing has a device class of its own in name only: Home
    # Assistant has no `wind_direction`, so it stays a plain number with a
    # degree sign, which is what it is.
    payload["state_class"] = "total_increasing" if obs in TOTAL else "measurement"
    if obs in TOTAL:
        # A daily total resets at midnight, and `total_increasing` is exactly
        # the class that expects that -- HA treats the drop as a new cycle
        # rather than as a negative reading.
        payload.pop("expire_after", None)
    return (f"{prefix}/sensor/{ident}/{obs}/config",
            json.dumps(payload, separators=(",", ":")))


def _slug(text: str) -> str:
    """A station name as something safe in a topic and an entity id."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return cleaned[:40] or "station"

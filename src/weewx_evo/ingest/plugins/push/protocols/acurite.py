#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The Acurite smartHUB and Access bridge.

Not a custom-server protocol. The bridge posts to Chaney's own servers and cannot be
told to post anywhere else, so getting these readings means answering for
hubapi.myacurite.com on your own network: a DNS entry, or a rule on the router. That
is a decision about your network rather than about this driver, and it is described
in docs/Hardware.md.

Two things make it unlike the rest.

    One request per sensor.  A frame carries `mt` for what kind of sensor it is and
    `sensor` for which one, then three or four readings. A station with a 5-in-1 and
    three towers sends four requests, each with `tempf` in it, each meaning something
    different. So everything that is not the 5-in-1 is qualified with what it is and
    which sensor it was, and waits to be placed. Nothing in the payload says whether a
    tower is on a wall or in a greenhouse.

    Two firmwares, two formats.  Bridges from July 2016 on send the Weather
    Underground shape this reads. Earlier ones send Chaney's own, where the readings
    are hex strings and the pressure has to be computed from seven calibration
    constants. That format is not read here. A bridge updates itself from Chaney on
    first contact, so a station still on it has been offline for nine years.

Field names and sample frames come from the interceptor driver by Matthew Wall.
"""

import logging

from .. import catalogs
from . import US, Protocol

log = logging.getLogger(__name__)

_catalog = catalogs.acurite

# What the bridge says instead of a number, and what that is worth as one.
BATTERY = {'normal': 0, 'low': 1}
# Signal strength arrives as bars, zero to four.
BARS = 25


class AcuriteBridge(Protocol):
    """An Acurite smartHUB or Access, pointed at this driver by a DNS entry."""

    name = 'acurite'
    label = 'Acurite'
    hardware = ('smartHUB and Access bridges, with a 5-in-1, towers, Pro sensors '
                'and the 899 rain gauge')

    # It posts to the Weather Underground endpoint, which it shares with hardware that
    # really is speaking that protocol. The `mt` parameter is what separates them, so
    # the path is not claimed and the payload decides.
    paths = ()

    settings = ()
    notes = (
        "A bridge cannot be told where to post. It goes to Chaney's servers, over "
        "plain HTTP on port 80, and there is no setting for it.",
        "So hubapi.myacurite.com has to resolve to %(address)s on your network. With "
        "dnsmasq:",
        "    address=/hubapi.myacurite.com/%(address)s",
        "Most routers can do the same under a name like 'local DNS'. A hosts file on "
        "this machine will not do: the entry has to be seen by the bridge.",
        "It posts to port 80, so redirect that rather than running WeeWX as root:",
        "    iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT "
        "--to-port %(port)s",
        "Once it is pointed here it no longer reaches Chaney, so the app and the "
        "website stop showing the station.",
    )

    # What Chaney's servers send, and what the bridge waits for. The timestamp is not
    # checked by the bridge, so a fixed one would do; it is filled in anyway because
    # there is no reason to send something untrue.
    answer = '{ "success": 1, "checkversion": "224" }'
    content_type = 'application/json'

    # The bridge, not the sensor. Every frame from one station carries the same id.
    identity = ('id',)

    metadata = frozenset([
        'id', 'sensor', 'mt', 'dateutc', 'action', 'realtime', 'rtfreq',
        'probe', 'check', 'water',
    ])

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    channels = _catalog.CHANNELS
    placement_unknown = _catalog.PLACEMENT_UNKNOWN

    units = US

    @classmethod
    def claims(cls, request, raw):
        """A message type and a bridge id together.

        No other protocol here sends `mt`, and nothing else sends it alongside the
        lowercase `id` that names the bridge. The uppercase ID of Weather Underground
        is a different parameter, and the two never appear together.
        """
        if 'mt' not in raw or 'id' not in raw:
            return 0
        if raw['mt'] in _catalog.STATION_TYPES or raw['mt'] in _catalog.SENSOR_TYPES:
            return 6
        # A sensor kind this driver has not met. Claimed rather than dropped, so that
        # it turns up in the report with its readings instead of vanishing.
        return 4

    @classmethod
    def readings(cls, request, raw):
        """Name each reading after the sensor it came from, unless it is the station.

        The 5-in-1 is the station and keeps the plain names. So does the bridge's own
        barometer, which rides along in every frame whatever sent it. Everything else
        becomes `<kind><sensor>_<name>`, which is ugly and is meant to be: it is what
        the user pastes into field_map_extensions after deciding where that sensor is,
        and it stays the same across restarts because the bridge keeps its numbers.
        """
        kind = raw.get('mt', '')
        named = {}
        for name, value in raw.items():
            if name == 'battery':
                value = BATTERY.get(value, value)
            elif name == 'rssi':
                value = _bars_to_percent(value)
            if (kind in _catalog.STATION_TYPES or name in cls.metadata
                    or name in _catalog.BRIDGE_READINGS):
                named[name] = value
            else:
                named['%s%s_%s' % (kind, raw.get('sensor', ''), name)] = value
        return named


def _bars_to_percent(value):
    """Signal strength as a percentage, from the nought to four bars the bridge sends."""
    try:
        return min(100, float(value) * BARS)
    except (TypeError, ValueError):
        return value

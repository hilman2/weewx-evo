#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The LaCrosse LW30x gateway.

Like the Acurite bridge, it posts to its maker's servers and cannot be told otherwise,
so reading it means answering for those on your own network. See docs/Hardware.md.

One request per sensor, two-letter parameter names, and a `ch` saying which channel
the sensor is on. Channel 1 is the station and everything above it is a sensor whose
placement only the user knows, so the readings are qualified with their channel and
the catalog puts channels two and up on the extra fields.

Half of what an LW30x sends has no established meaning. Those parameters are named in
the catalog's UNDOCUMENTED and kept out of the packet: a column of numbers nobody can
label is worse than no column.

The other LaCrosse gateway, the GW1000U, is not read here. It does not send name and
value pairs at all: it registers with the server, is told its serial number, its ping
interval and its display brightness, and then exchanges binary frames. That is a
protocol rather than a dialect, and it is not this one.

Field names, meanings, units and sample frames come from the interceptor driver by
Matthew Wall, which captured them from an LW301.
"""

import logging

from .. import catalogs
from . import METRICWX, Protocol

log = logging.getLogger(__name__)

_catalog = catalogs.lacrosse

# The base station reports about itself and has no channel.
BASE_STATION = 'c2'

# Parameters that say which sensor a frame came from rather than what it measured.
IDENTIFIERS = ('mac', 'id', 'rid', 'ch')


class LW30x(Protocol):
    """A LaCrosse LW301 or LW302 gateway, pointed here by a DNS entry."""

    name = 'lacrosse'
    label = 'LaCrosse LW30x'
    hardware = 'LW301 and LW302 gateways, with the wind, rain, UV and T/H sensors'

    paths = ()

    settings = ()
    notes = (
        "A gateway cannot be told where to post, so box.weatherdirect.com has to "
        "resolve to %(address)s on your network. With dnsmasq:",
        "    address=/box.weatherdirect.com/%(address)s",
        "It posts to port 80, so redirect that:",
        "    iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT "
        "--to-port %(port)s",
        "Once it is pointed here it no longer reaches its own servers.",
    )

    # The gateway does not check what it gets back. An empty 200 is what it sees from
    # its own servers as far as anybody has established.
    answer = ''
    content_type = 'text/plain'

    identity = ('mac',)

    # The undocumented parameters are in here, which is what keeps them out of the
    # packet: a column of numbers nobody can label is worse than no column. They are
    # still written to the report, so somebody with the hardware can work them out.
    metadata = frozenset(IDENTIFIERS + ('lost', 'reg', 'dateutc')
                         + _catalog.UNDOCUMENTED)

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    channels = _catalog.CHANNELS
    placement_unknown = _catalog.PLACEMENT_UNKNOWN
    scale = _catalog.SCALE

    # Celsius, metres per second, millibars. The rain arrives in inches and is
    # converted; see the catalog's SCALE.
    units = METRICWX

    # An LW30x has no daily counter. It sends the gauge's lifetime total, so that is
    # what StdDelta has to difference.
    rain_counter = 'totalRain'

    @classmethod
    def claims(cls, request, raw):
        """A MAC and a sensor type together.

        Nothing else here sends a lowercase `mac`, and the sensor types are a short
        list of two-character codes this gateway has always used.
        """
        if 'mac' not in raw or 'id' not in raw:
            return 0
        return 6 if raw['id'] in _catalog.SENSORS else 4

    @classmethod
    def readings(cls, request, raw):
        """Name each reading after the channel its sensor is on.

        The base station has no channel and needs none: there is one of it. Everything
        else does, because two temperature sensors on two channels both send `ot`, and
        without the channel the second would overwrite the first every eighteen
        seconds with nothing in the log to say so.
        """
        channel = raw.get('ch')
        named = {}
        for name, value in raw.items():
            if name in cls.metadata or name in _catalog.UNDOCUMENTED:
                named[name] = value
            elif channel:
                named['%s_ch%s' % (name, channel)] = value
            else:
                named[name] = value
        return named

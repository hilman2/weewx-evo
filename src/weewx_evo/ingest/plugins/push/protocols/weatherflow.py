#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The WeatherFlow UDP protocol.

The odd one out, in three ways.

    It broadcasts.  A Tempest hub sends JSON datagrams to the whole local network on
    port 50222. Nothing is posted, nothing is answered, and no server is configured
    anywhere: the hub does this whether or not anybody is listening. Which also means
    there is nothing to keep strangers out with, beyond the network itself.

    The readings are positional.  An observation is an array, and index 7 is the air
    temperature because index 7 is the air temperature. See catalogs/weatherflow.py.

    The rain is already a difference.  Every other protocol here sends running
    counters that StdDelta has to subtract. A Tempest sends the millimetres since its
    last report, which is what WeeWX means by 'rain'. Differencing it again would
    record almost no rain at all.

Because it needs a second port and a second transport, it is not switched on by
'protocols = auto'. Name it to open the socket.

Source: WeatherFlow Tempest UDP reference v171,
        https://weatherflow.github.io/Tempest/api/udp/v171/
"""

import logging
import time

from .. import catalogs, transport
from . import METRICWX, Protocol

log = logging.getLogger(__name__)

_catalog = catalogs.weatherflow

# The port a hub broadcasts on. Fixed in the hardware, so there is nothing to
# configure and nothing to get wrong.
PORT = 50222

# Message types that carry readings. Anything else is noise this driver ignores, and
# saying so here rather than in a chain of ifs keeps a firmware's new message type
# from being read as a broken observation.
OBSERVATIONS = ('obs_st', 'obs_air', 'obs_sky', 'rapid_wind', 'evt_strike')
STATUS = ('device_status', 'hub_status')


class WeatherFlow(Protocol):
    """WeatherFlow Tempest, and the AIR and SKY it replaced."""

    name = 'weatherflow'
    label = 'WeatherFlow'
    hardware = 'Tempest, and the AIR, SKY and hub that came before it'

    # A broadcast has no path and gets no answer. There is nobody to answer to.
    datagram = True
    default_port = PORT

    settings = ()
    notes = (
        "Nothing to set on the hub. It broadcasts whether or not anybody listens.",
        "The hub and this machine have to be on the same network segment. A "
        "broadcast does not cross a router.",
        "This driver has to be told to open the socket, because it is a second one. "
        "In weewx.conf, then restart:",
        "    [UltimatePush]\n        protocols = ecowitt, weatherflow",
    )

    # The hub, not the device. A station can have an AIR and a SKY on one hub, and
    # they are one station with two sensors rather than two stations.
    identity = ('hub_sn',)

    metadata = frozenset([
        'serial_number', 'hub_sn', 'type', 'firmware_revision', 'dateutc',
        'reset_flags', 'seq', 'fs', 'radio_stats', 'mqtt_stats', 'debug',
        'timestamp', 'obs', 'ob', 'evt',
    ])

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    scale = _catalog.SCALE

    units = METRICWX

    # A hub sends the millimetres since its last report, which is already what WeeWX
    # means by 'rain'. Differencing it again would record almost nothing.
    rain_counter = None

    @classmethod
    def claims(cls, request, raw):
        """A datagram whose JSON names a message type this protocol has.

        Nothing else on the network sends these, and no other protocol here sends
        JSON at all, so one look at the type settles it.
        """
        kind = raw.get('type')
        if not isinstance(kind, str):
            return 0
        if kind in OBSERVATIONS or kind in STATUS:
            return 5
        if 'serial_number' in raw and 'hub_sn' in raw:
            # A message type this driver has not met. Claimed, so that it is reported
            # rather than logged as an unrecognised protocol, and then dropped for
            # having nothing in it.
            return 3
        return 0

    @classmethod
    def readings(cls, request, raw):
        """Unpack an observation array into named readings.

        Positions beyond the layout are left alone rather than guessed at: WeatherFlow
        has appended readings to these arrays before, and a position nobody has named
        is not a reading, it is a number.
        """
        kind = raw.get('type')
        values = _values_of(raw, kind)
        if values is None:
            return _timestamped(dict(raw), raw.get('timestamp'))

        layout = _catalog.LAYOUTS.get(kind)
        if layout is None:
            return _timestamped({}, None)

        named = {}
        for position, value in enumerate(values):
            if position >= len(layout):
                log.debug("%s carries %d values and %d are named. Ignoring the rest.",
                          kind, len(values), len(layout))
                break
            named[layout[position]] = value

        if kind == 'evt_strike':
            # An event is one strike. Counting it makes the strike show up in the
            # same field the observations fill, so a station that sees the event and
            # the observation does not have to be read two ways.
            named['lightning_count'] = 1

        return _timestamped(named, named.pop('time_epoch', None))


def _values_of(raw, kind):
    """The array of readings in a message, whatever it is called in that message.

    Observations nest theirs one deeper, because a device may report several at once
    after a gap. The most recent is the last, and that is the one taken: an older one
    would be handed to WeeWX as though it had just been measured.
    """
    if kind in ('obs_st', 'obs_air', 'obs_sky'):
        batch = raw.get('obs')
        if not isinstance(batch, list) or not batch:
            return None
        latest = batch[-1]
        return latest if isinstance(latest, list) else None
    for key in ('ob', 'evt'):
        value = raw.get(key)
        if isinstance(value, list):
            return value
    return None


def _timestamped(named, epoch):
    """Put the device's own time where the rest of the driver looks for it.

    Every other protocol sends 'dateutc' as text, and the clock window that decides
    whether to believe it is written once, in transport. A hub sends an epoch, so it
    is written in that form and goes through the same check as everything else.
    """
    if epoch:
        try:
            named['dateutc'] = time.strftime(transport.DEVICE_TIME_FORMAT,
                                             time.gmtime(float(epoch)))
        except (TypeError, ValueError, OSError):
            pass
    return named

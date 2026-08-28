#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The Ecowitt protocol.

What a gateway or console sends when *Customized* is set to protocol *Ecowitt* in the
WSView app: a POST with an urlencoded form body, every reading in imperial units, the
station named by a PASSKEY derived from its own MAC address.

Ecowitt hardware is stricter than most about the answer. It wants the JSON below, and
an upload it cannot acknowledge is retried and eventually dropped.

The catalog is generated. See catalogs/ecowitt.py.
"""

from .. import catalogs
from . import US, Protocol

_catalog = catalogs.ecowitt


class Ecowitt(Protocol):
    """Ecowitt gateways and consoles, and the Froggit and Misol rebadges of them."""

    name = 'ecowitt'
    label = 'Ecowitt'
    hardware = ('GW1000, GW1100, GW1200, GW2000, GW3000, HP2551, HP2561, WS3800, '
                'WS3900, WS3910, WN1980 and their relatives')

    # The path is whatever the user typed into WSView, so this protocol claims none.
    paths = ()

    settings = (
        ('Protocol Type', 'Ecowitt'),
        ('Server IP / Hostname', '%(address)s'),
        ('Path', '%(path)s'),
        ('Port', '%(port)s'),
        ('Upload Interval', '60'),
    )
    notes = (
        "In the WSView Plus app: Device List, your console, then Weather Services. "
        "Page through to Customized and switch it on.",
        "Sixteen seconds is the shortest interval it allows. Sixty is plenty.",
        "Save it. The console uploads on its own from then on.",
    )

    answer = '{"errcode":"0","errmsg":"ok"}'
    content_type = 'application/json'

    identity = ('PASSKEY',)
    secret_kind = 'path'

    metadata = frozenset([
        'PASSKEY', 'stationtype', 'model', 'freq', 'dateutc', 'runtime', 'heap',
        'interval',
    ])

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    channels = _catalog.CHANNELS
    contested = _catalog.CONTESTED
    contested_with = _catalog.CONTESTED_WITH
    placement_unknown = _catalog.PLACEMENT_UNKNOWN

    units = US

    # A WH51 and a WH52 are documented with sixteen channels each, but the console
    # compatibility table gives them one pool of sixteen between them. So the same
    # channel number should never arrive from both, and if it does, one of the two
    # readings is about to overwrite the other.
    shared_channels = (('soilmoisture', 'soil_ec_hum'),)

    @classmethod
    def claims(cls, request, raw):
        """A PASSKEY, and a station type that is not Ambient's.

        Ambient hardware descends from the same Fine Offset design and also sends a
        PASSKEY, so the station type is what separates them. When there is none, this
        is still the better guess: Ambient consoles always send theirs.
        """
        if 'PASSKEY' not in raw:
            return 0
        station_type = raw.get('stationtype', '')
        if station_type.startswith('AMBWeather'):
            return 0
        return 3 if station_type else 2

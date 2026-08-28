#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The Ambient Weather protocol, as a console sends it to a custom server.

Ambient hardware descends from the same Fine Offset design as Ecowitt's, and it
shows: a PASSKEY built from the MAC address, a stationtype, imperial units, the same
POST of an urlencoded form. What differs is the vocabulary. Ambient says `soilhum1`
where Ecowitt says `soilmoisture1`, `battout` where Ecowitt says `wh65batt`,
`lightning_day` where Ecowitt says `lightning_num`, and it has `relay1` to `relay10`
and the AQIN indoor air module, which Ecowitt has no equivalent of.

That is why it is a protocol of its own rather than a dialect of Ecowitt's. Reading an
Ambient upload with the Ecowitt catalog does not fail loudly. It silently drops the
soil probes and the batteries, which is exactly the failure this driver exists to stop.

The two are told apart by the station type, which Ambient consoles always send and
which always begins with AMBWeather.

The catalog is generated. See catalogs/ambient.py and tools/import_ambient.py.
"""

from .. import catalogs
from . import US, Protocol

_catalog = catalogs.ambient


class Ambient(Protocol):
    """Ambient Weather consoles uploading to a custom server."""

    name = 'ambient'
    label = 'Ambient Weather'
    hardware = ('WS-2902, WS-5000, WS-1965 and the rest of the Ambient range with '
                "'Custom' upload in the awnet app")

    # The path is typed into the awnet app. Ambient's own default is /data/report/,
    # which is also Ecowitt's, so it cannot separate the two and is not claimed.
    paths = ()

    settings = (
        ('Protocol', 'Ambient'),
        ('Server IP / Hostname', '%(address)s'),
        ('Path', '%(path)s'),
        ('Port', '%(port)s'),
        ('Upload Interval', '60'),
    )
    notes = (
        "In the awnet app: your device, then Device Settings. The fields are under "
        "something called Customized Upload.",
    )

    # Ambient consoles are not fussy about the answer, and this is the one the
    # interceptor driver has been giving them for years.
    answer = 'success'
    content_type = 'text/plain'

    identity = ('PASSKEY',)
    secret_kind = 'path'

    metadata = frozenset([
        'PASSKEY', 'stationtype', 'model', 'dateutc', 'freq', 'interval',
    ])

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    channels = _catalog.CHANNELS
    contested = _catalog.CONTESTED
    contested_with = _catalog.CONTESTED_WITH
    placement_unknown = _catalog.PLACEMENT_UNKNOWN

    units = US

    # Names no Ecowitt console sends, for an upload that arrives without a station
    # type. Chosen because they are structural rather than optional: a console with
    # any soil probe or any outdoor array sends one of them.
    MARKERS = ('soilhum1', 'battout', 'battin', 'lightning_day')

    @classmethod
    def claims(cls, request, raw):
        """The station type settles it. Failing that, a name only Ambient uses."""
        if 'PASSKEY' not in raw:
            return 0
        if raw.get('stationtype', '').startswith('AMBWeather'):
            return 5
        if any(marker in raw for marker in cls.MARKERS):
            return 4
        return 0

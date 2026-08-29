#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The Weather Underground upload protocol.

A GET to /weatherstation/updateweatherstation.php, the readings in the query string,
the station named by ID and PASSWORD. It is the oldest of the protocols here and the
only one where the hardware can present a shared secret, because PASSWORD is part of
every upload.

The field list is in catalogs/wunderground.py, derived from the specification as
Weather Underground published it.

Three things about this protocol are traps, and all three come from real uploads
rather than from the specification:

    A device answers to more than the specification.  Fine Offset firmwares add
    weeklyrainin, windchillf, lowbatt, absbaromin and others. They are the same
    protocol on the same endpoint, so they are in the same catalog.

    There is a metric dialect.  The same hardware under 'Weather logger' or 'HP1001'
    firmware sends intemp, outtemp, absbaro, light in Celsius, hPa and lux. Different
    names, different units, same endpoint. See METRIC_FIELDS.

    baromin means two different things.  Sea-level pressure on most firmwares,
    station pressure on WH2600GEN_V2.2.5 and WH2650A_V1.2.1. Nothing in the payload
    distinguishes them, so it is contested and waits for the user.

Sources:
    the specification, wiki.wunderground.com/index.php/PWS_-_Upload_Protocol
    six captured uploads, from the interceptor driver by Matthew Wall
"""

import logging

from .. import catalogs, transport
from . import METRIC, METRICWX, US, Dialect, Protocol

log = logging.getLogger(__name__)

_catalog = catalogs.wunderground

# The endpoint, with and without the extension. Fine Offset firmwares have shipped
# both '.php' and '.asp', and some omit it. RapidFire uses the same path on a
# different host, which is the station's business and not ours.
PATHS = (
    '/weatherstation/updateweatherstation.php',
    '/weatherstation/updateweatherstation.asp',
    '/weatherstation/updateweatherstation',
)

# What the server says when it has taken the reading. Devices differ in how much they
# care: some check for this string, some only for a 200, and some retry until they
# see it. It costs nothing to be exact.
ANSWER = 'success'


class WeatherUnderground(Protocol):
    """Anything that speaks the Weather Underground PWS protocol."""

    name = 'wunderground'
    label = 'Weather Underground'
    hardware = ('Fine Offset Observer and its rebadges (Ambient WS-1000 series, '
                'Sainlogic, Misol), any Ecowitt console set to protocol '
                'Wunderground, Meteobridge, and weather software generally')

    paths = PATHS
    answer = ANSWER
    content_type = 'text/plain'

    settings = (
        ('Server', '%(address)s'),
        ('Port', '%(port)s'),
        ('ID', 'anything you like'),
        ('PASSWORD', 'anything you like'),
    )
    notes = (
        "Wherever your console or software sets its Weather Underground upload.",
        "The path cannot be changed. It is burned into the firmware, and this driver "
        "answers on it.",
        "Set 'password' in the driver section to the same PASSWORD and uploads "
        "without it are refused. This is the one protocol here whose hardware can "
        "carry a secret.",
    )

    identity = ('ID',)
    secret = 'PASSWORD'
    secret_kind = 'password'

    metadata = _catalog.METADATA

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    channels = _catalog.CHANNELS
    contested = _catalog.CONTESTED
    contested_with = _catalog.CONTESTED_WITH
    scale = _catalog.SCALE

    units = US

    # Fine Offset firmwares say this when a sensor has nothing to report. Without it
    # a missing outdoor temperature is recorded as -9999 degrees.
    absent = ('-9999', '-9999.0')

    # Which unit the metric dialect sends wind in. Set from the driver section; see
    # METRIC_WIND_CHOICES for why this cannot be worked out from a payload.
    metric_wind = 'kph'

    @classmethod
    def claims(cls, request, raw):
        """The endpoint settles it; failing that, ID and PASSWORD together.

        A device that speaks this protocol cannot be told to use another path, so the
        path is the strongest signal there is. But the driver may be behind a proxy
        that rewrites it, so the credentials are enough on their own.
        """
        if is_wu_path(request):
            return 5
        if 'ID' in raw and 'PASSWORD' in raw:
            return 3
        if raw.get('action') == 'updateraw':
            return 2
        return 0

    @classmethod
    def dialect(cls, raw):
        """Imperial or metric, decided on names alone."""
        if is_metric(raw):
            return cls.metric_dialect()
        return Dialect('wunderground', _catalog.FIELDS, _catalog.GROUPS,
                       _catalog.CHANNELS, _catalog.CONTESTED,
                       _catalog.CONTESTED_WITH, scale=_catalog.SCALE, units=US,
                       metadata=_catalog.METADATA, absent=cls.absent, prefix='wu_')

    @classmethod
    def metric_dialect(cls):
        """The Celsius-and-millimetres catalog, in whichever wind unit was chosen."""
        if cls.metric_wind == 'mps':
            # METRICWX already keeps rain in millimetres and wind in metres per
            # second, so the only conversion left is the UV irradiance.
            scale = {'UV': _catalog.METRIC_SCALE['UV']}
            units = METRICWX
        else:
            scale = _catalog.METRIC_SCALE
            units = METRIC
        return Dialect('wunderground/metric', _catalog.METRIC_FIELDS,
                       _catalog.METRIC_GROUPS,
                       contested_with=_catalog.CONTESTED_WITH, scale=scale,
                       units=units, metadata=_catalog.METADATA, absent=cls.absent,
                       prefix='wu_')

    @classmethod
    def settled_contested(cls, raw):
        """Contested fields this upload settles by saying which firmware sent it."""
        if raw.get('softwaretype') in _catalog.STATION_PRESSURE_FIRMWARE:
            return {'baromin': 'pressure'}
        return {}


def is_metric(raw):
    """Whether an upload is in the metric dialect.

    Decided on names, not on values. Every name in the metric dialect is absent from
    the imperial one and the other way round, so one of them settles it.
    """
    return any(name in raw for name in _catalog.METRIC_MARKERS)


def is_wu_path(request):
    """Whether a request went to the Weather Underground endpoint."""
    path = (getattr(request, 'path', '') or '').rstrip('/')
    return path in PATHS


def password_ok(raw, expected):
    """Whether an upload presents the password it was configured with.

    Compared in constant time, because the alternative lets somebody who can reach
    the port find it one character at a time. An empty `expected` means no password
    was configured, and anything is accepted.
    """
    if not expected:
        return True
    return transport.same_secret(raw.get('PASSWORD', ''), expected)

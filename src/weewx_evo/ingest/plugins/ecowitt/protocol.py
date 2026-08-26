#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Turn what the hardware sent into named readings.

Ecowitt gateways and consoles speak two protocols, and both end up here:

    Ecowitt   POST, an urlencoded form body
    Wunderground   GET, the same shape in the query string

So a single function handles both. Everything in this module is pure: text in, a
dictionary out, no sockets, no clock, no configuration. That is what makes the field
work testable from a captured payload.
"""

import logging
import re
import time
import urllib.parse

log = logging.getLogger(__name__)

# Fields that identify the device rather than measure anything.
METADATA = frozenset([
    'PASSKEY', 'stationtype', 'model', 'freq', 'dateutc', 'ID', 'PASSWORD',
    'action', 'realtime', 'rtfreq', 'softwaretype', 'runtime', 'heap', 'interval',
])

# How the device stamps its own time.
DEVICE_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'


def parse(text):
    """Split a payload into raw name/value pairs.

    Works for both protocols, because a urlencoded body and a query string are the same
    thing. Returns a dict of strings, in the order they arrived.
    """
    if not text:
        return {}
    if text.startswith('?'):
        text = text[1:]
    return dict(urllib.parse.parse_qsl(text, keep_blank_values=False))


# How far behind ours a console's clock may be before its timestamp is ignored. A
# console with an internet connection sets its clock by NTP, so a stamp a few minutes
# old is a late upload rather than a wrong clock: a relay, a queue, a network that was
# down for a while. WeeWX puts such a packet in the interval its timestamp falls in,
# and weewx.loopstore works the record out again if that interval has been written
# already. An hour is well past any delay worth keeping and well short of the years a
# console with no clock at all reports.
MAX_BEHIND = 3600
# And how far ahead. There is no such thing as a reading from the future, so this only
# has to cover the drift between two clocks that are both roughly right.
MAX_AHEAD = 60


def device_time(raw, now=None, max_behind=MAX_BEHIND, max_ahead=MAX_AHEAD):
    """Return the timestamp the device sent, or None if it is not usable.

    Consoles are frequently wrong about the time, sometimes by years, and a record
    stamped in 2015 is worse than no record at all. But one that is merely late is
    worth keeping, and the window is asymmetric for that reason: a reading can be
    delayed, it cannot arrive early.
    """
    stamp = raw.get('dateutc')
    if not stamp or stamp == 'now':
        return None
    try:
        parsed = time.strptime(stamp, DEVICE_TIME_FORMAT)
    except ValueError:
        log.debug("Cannot read device time '%s'", stamp)
        return None
    # The device sends UTC. calendar.timegm would be the obvious call, but this keeps
    # the module free of one more import.
    seconds = _timegm(parsed)
    if now is None:
        now = time.time()
    behind = now - seconds
    if behind > max_behind or -behind > max_ahead:
        log.warning("Device time %s is %s %s than ours, past what %s allows. Using "
                    "ours.", stamp, _how_far(abs(behind)),
                    "behind" if behind > 0 else "ahead",
                    "max_behind" if behind > 0 else "max_ahead")
        return None
    return seconds


def _how_far(seconds):
    """A span of time in whatever unit reads best."""
    if seconds < 120:
        return "%.0f seconds" % seconds
    if seconds < 7200:
        return "%.0f minutes" % (seconds / 60.0)
    if seconds < 172800:
        return "%.1f hours" % (seconds / 3600.0)
    return "%.0f days" % (seconds / 86400.0)


def _timegm(parsed):
    """Seconds since the epoch for a struct_time that is already UTC."""
    import calendar
    return calendar.timegm(parsed)


def numbers(raw):
    """Split raw values into the numeric ones and the rest.

    Returns (readings, text), where readings holds everything that could be read as a
    number, and text holds identifiers, model names and anything else that could not.
    A value the hardware sends as an empty field, or as one of its several ways of
    saying "no reading", becomes None rather than being dropped, because a gap is a
    fact about the sensor.
    """
    readings = {}
    text = {}
    for name, value in raw.items():
        if name in METADATA:
            text[name] = value
            continue
        if value in ('', '--', '--.-', '-', 'None', 'null'):
            readings[name] = None
            continue
        try:
            readings[name] = float(value)
        except (TypeError, ValueError):
            text[name] = value
    return readings, text


# Values that identify a station rather than describe the weather.
SECRETS = ('PASSKEY', 'ID', 'PASSWORD', 'key', 'stationkey')


def redact(text):
    """Replace the values that identify a station, leaving the readings alone.

    A payload is going to be pasted into an issue tracker, and the PASSKEY is what
    Ecowitt's servers use to recognise a station. Everything else in there is weather.
    """
    for name in SECRETS:
        text = re.sub(r'(^|[?&])%s=[^&]*' % re.escape(name),
                      r'\g<1>%s=X' % name, text)
    return text


def station_id(text):
    """What identifies the console that sent this.

    The PASSKEY for the Ecowitt protocol, the station ID for Weather Underground.
    Read without parsing the rest, because this runs before anything else and decides
    whether the upload is answered at all.

    Returns an empty string for hardware that identifies itself with neither. Those
    cannot be told apart, which is a limit of the protocol rather than a decision
    made here.
    """
    for name in ('PASSKEY', 'ID'):
        match = re.search(r'(^|[?&])%s=([^&]+)' % name, text or '')
        if match:
            return match.group(2)
    return ''

#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Leave a report where somebody can find it.

When a station sends something the driver does not know, the useful thing is the raw
upload. Getting hold of it should not mean reconfiguring the console and waiting for
an interval, so the driver writes it out itself the first time it sees a field it
cannot place.

The result is one file, ready to paste into an issue, with the station's PASSKEY
already replaced.
"""

import logging
import os
import time

from . import VERSION, infer, transport

log = logging.getLogger(__name__)

DEFAULT_PATH = '/var/tmp/weewx-ultimate-push-report.txt'

TEMPLATE = """weewx-ultimate-push %(version)s, %(when)s

Protocol: %(protocol)s

This station sent %(count)d field(s) the driver could not place on its own. Paste
this whole file into an issue at
https://github.com/hilman2/weewx-ultimate-push/issues/new

Everything that names the station has been replaced already. The rest is weather.

---- what the station sent ----

%(payload)s

---- what the driver made of it ----

%(findings)s
"""


def write(payload, guesses, waiting, path=DEFAULT_PATH, protocol='unknown'):
    """Write a report, and return the path. Returns None if it could not be written."""
    lines = infer.report(guesses)
    for raw, elsewhere in sorted(waiting.items()):
        lines.append("%-24s waiting for a placement (would be %s)" % (raw, elsewhere))
    if not lines:
        return None

    text = TEMPLATE % {
        'version': VERSION,
        'protocol': protocol,
        'when': time.strftime('%Y-%m-%d %H:%M:%S'),
        'count': len(lines),
        'payload': transport.redact(payload),
        'findings': '\n'.join(lines),
    }
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(path, 'w', encoding='utf-8') as fd:
            fd.write(text)
    except OSError as e:
        log.warning("Cannot write the report to %s: %s", path, e)
        return None
    return path

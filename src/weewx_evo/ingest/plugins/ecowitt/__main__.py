#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Listen once, and say what the hardware is sending.

Run this before wiring anything up, or when a sensor is missing from the reports:

    python -m user.ecowitt --port 8000

It waits for one upload, then prints what arrived, what the driver could not place,
the commands that would give the readings somewhere to live, and which of those fields
already hold somebody else's history. Nothing is changed, and WeeWX does not have to be
stopped as long as this uses a different port.
"""

import argparse
import logging
import sys
import time

from . import VERSION, catalog, columns, infer
from .mapping import Mapper, placement_note

try:
    from weewx.listener import HTTPListener
except ImportError:
    from user.listener import HTTPListener

ECOWITT_RESPONSE = '{"errcode":"0","errmsg":"ok"}'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m user.ecowitt', description=__doc__)
    parser.add_argument('--port', default=8000, help="Port to listen on. Default 8000.")
    parser.add_argument('--address', default='', help="Address to bind to.")
    parser.add_argument('--path', help="Accept this path only.")
    parser.add_argument('--samples', type=int, default=1,
                        help="How many uploads to wait for. Default 1.")
    parser.add_argument('--timeout', type=int, default=300,
                        help="Seconds to wait before giving up. Default 300.")
    parser.add_argument('--config', default='/etc/weewx/weewx.conf',
                        help="Path to weewx.conf, for the database check and for the "
                             "commands printed at the end.")
    parser.add_argument('--infer-unknown', default='all',
                        choices=['off', 'series', 'all'],
                        help="Default 'all' here, so that everything gets a proposal.")
    parser.add_argument('--no-database', action='store_true',
                        help="Skip looking at the database. Faster, and one section "
                             "less when setting up from scratch.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    print("weewx-ecowitt %s. Listening on %s:%s. Point the console here."
          % (VERSION, args.address or '*', args.port))

    mapper = Mapper(infer_unknown=args.infer_unknown)
    packet = {}
    guesses = []
    seen = 0

    listener = HTTPListener(port=args.port, address=args.address, path=args.path,
                            response=ECOWITT_RESPONSE, content_type='application/json')
    try:
        while seen < args.samples:
            request = listener.get(timeout=args.timeout)
            if request is None:
                print("Nothing arrived in %d seconds." % args.timeout, file=sys.stderr)
                return 1
            print("\n%s" % request)
            one, fresh = mapper.to_packet(request.text)
            packet.update(one)
            guesses.extend(fresh)
            seen += 1
    finally:
        listener.close()

    _report(packet, guesses, mapper, args.config)
    _decisions(mapper)
    if not args.no_database:
        _check_history(packet, args.config)
    return 0


def _decisions(mapper):
    """Print the configuration block for everything that is waiting on the user."""
    waiting = sorted(mapper.warned & set(mapper.undecided))
    if not waiting:
        return
    print("\n%d fields are not being written, because where they go is your call and"
          "\nnot the hardware's. Paste this into your driver section and uncomment the"
          "\nline you want:\n" % len(waiting))
    print("    [[field_map_extensions]]")
    for raw in waiting:
        print("        # %s" % raw)
        print("        #%s = %s        # this driver" % (raw, mapper.fields.get(raw)))
        print("        #%s = %s        # %s"
              % (raw, mapper.undecided[raw], catalog.CONTESTED_WITH))
    print("\nAnything else is allowed too. A WN34 on a pool lead is not a soil"
          "\ntemperature, so somewhere in extraTemp is often what you want. The"
          "\ntemperature fields your schema already has:")
    print("    " + ', '.join(sorted(_free_temperature_fields())))


def _free_temperature_fields():
    """WeeWX fields a temperature reading could reasonably go to."""
    try:
        known = columns.schema_fields()
    except ImportError:
        return set()
    return {f for f in known if f.startswith(('extraTemp', 'soilTemp', 'leafTemp'))}


def _report(packet, guesses, mapper, config):
    readings = {f: v for f, v in packet.items() if f != 'dateTime'}
    print("\n%d readings" % len(readings))
    for field, value in sorted(readings.items()):
        print("  %-26s %s" % (field, value))

    if guesses:
        print("\n%d fields were not in the catalog" % len(guesses))
        for line in infer.report(guesses):
            print("  " + line)
        flagged = {g.raw for g in guesses if placement_note(g.raw)}
        if flagged:
            print("\n  Placement of these is a convention, not a reading. Say where "
                  "they\n  really are with field_map_extensions: %s"
                  % ' '.join(sorted(flagged)))

    try:
        wanted = columns.missing(packet, mapper.wanted_groups())
    except ImportError:
        print("\nWeeWX is not importable here, so the columns cannot be worked out.",
              file=sys.stderr)
        return

    if not wanted:
        print("\nEvery reading has a column already.")
        return
    print("\n%d readings have nowhere to live. They will show up in reports as current"
          "\nconditions and be gone at the next archive interval. To keep them:\n"
          % len(wanted))
    for command in columns.commands(wanted, config):
        print("  " + command)
    print("\nBack up the database first. Adding a column rewrites the table.")


def _check_history(packet, config):
    """Say which of these fields already hold readings, and why that matters."""
    try:
        used = columns.occupied(config)
    except Exception as e:
        print("\nCannot read the database (%s). Skipping the history check." % e,
              file=sys.stderr)
        return

    clashes = {field: used[field] for field in packet if field in used}
    if not clashes:
        print("\nNo field this driver writes to has a history yet.")
        return

    print("\n%d of these fields already hold readings:\n" % len(clashes))
    for field, (count, last) in sorted(clashes.items()):
        when = time.strftime('%Y-%m-%d', time.localtime(last)) if last else '?'
        print("  %-26s %9d values, last %s" % (field, count, when))
    print("\nIf those came from the same sensor, there is nothing to do. If they came"
          "\nfrom a different one, this driver is about to write a second series into"
          "\nthe same column, and afterwards the two cannot be told apart. Give it a"
          "\nfield of its own under [[field_map_extensions]].")


if __name__ == '__main__':
    sys.exit(main())

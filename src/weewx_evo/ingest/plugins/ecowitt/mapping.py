#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""From named readings to a WeeWX packet.

This is where the catalog, the user's own mapping and the inference meet. It stays
free of WeeWX imports so that it can be tested with nothing but a captured payload:
the unit groups it wants registered come back as data, and the driver does the
registering.
"""

import logging
import re

from . import catalog, infer, protocol

log = logging.getLogger(__name__)

# What to do about a field the catalog does not cover.
# Sensors that share one pool of channel numbers, so channel 3 is one channel with
# either probe in it. If both ever arrive for the same number, that is worth saying.
SHARED_CHANNELS = [
    ('soilmoisture', 'soil_ec_hum'),
]

OFF = 'off'          # drop it, the way every other driver does
SERIES = 'series'    # take it when it continues a series and its placement is not
                     # in question, report the rest
ALL = 'all'          # take whatever can be named, including from rules
MODES = (OFF, SERIES, ALL)


class Mapper:
    """Turns raw readings into a WeeWX packet.

    Args:
        extensions (dict): Raw field -> WeeWX field, overriding the catalog. This is
            the user's own mapping, from the configuration file.
        infer_unknown (str): 'off', 'series' or 'all'. See above. Default 'series',
            i.e. accept what can be derived and merely report what was guessed.
        max_behind (int): How many seconds behind ours a console's clock may be
            before its timestamp is ignored and the arrival time used instead.
        max_ahead (int): The same, for a clock that is fast.
        fields, groups, channels, contested (dict): The catalog to work from.
            Defaults to the one that ships with the driver. Passing them is for
            tests, so that they do not have to change every time the catalog does.
    """

    def __init__(self, extensions=None, infer_unknown=SERIES,
                 fields=None, groups=None, channels=None, contested=None,
                 max_behind=protocol.MAX_BEHIND, max_ahead=protocol.MAX_AHEAD):
        if infer_unknown not in MODES:
            raise ValueError("infer_unknown must be one of %s, not '%s'"
                             % (', '.join(MODES), infer_unknown))
        self.mode = infer_unknown
        # How far the console's own clock may be out before its timestamp is dropped
        # in favour of the arrival time.
        self.max_behind = max_behind
        self.max_ahead = max_ahead
        self.fields = dict(catalog.FIELDS if fields is None else fields)
        self.extensions = dict(extensions or {})
        self.fields.update(self.extensions)
        # Fields another driver puts somewhere else. Until the user says which
        # placement they want, these are not written: either answer can be the one
        # that continues an existing series, and the wrong one cannot be undone.
        self.undecided = dict(catalog.CONTESTED if contested is None else contested)
        for raw in self.extensions:
            # Naming a field yourself is the decision. That settles it.
            self.undecided.pop(raw, None)
        self.groups = dict(catalog.GROUPS if groups is None else groups)
        self.inferrer = infer.Inferrer(
            self.fields, self.groups,
            catalog.CHANNELS if channels is None else channels)
        # Every unmapped field is looked at once. After that it is either part of the
        # mapping or a known refusal, and either way it does not need saying again.
        self.seen = {}
        self.ignored = set()
        self.warned = set()

    def to_packet(self, text, now=None):
        """Return (packet, guesses) for one payload.

        The packet is ready for WeeWX apart from its unit system, which the caller
        sets, because that is a decision about the whole driver rather than about one
        reading. Guesses are the fields that were not in the mapping, whether or not
        they made it into the packet.
        """
        raw = protocol.parse(text)
        readings, _ = protocol.numbers(raw)

        self._check_shared_channels(readings)

        packet = {}
        fresh = []
        for name, value in readings.items():
            if name in self.undecided:
                self._say_undecided(name)
                continue
            field = self.fields.get(name)
            if field is None:
                field = self._unmapped(name, fresh)
                if field is None:
                    continue
            packet[field] = value

        stamp = protocol.device_time(raw, now=now, max_behind=self.max_behind,
                                    max_ahead=self.max_ahead)
        packet['dateTime'] = int(stamp if stamp is not None
                                 else (now if now is not None else _now()))
        return packet, fresh

    def _say_undecided(self, name):
        """Say once that a field is waiting for a decision, and what settles it."""
        if name in self.warned:
            return
        self.warned.add(name)
        log.warning(
            "'%s' is not being written, because drivers disagree about where it goes. "
            "The wrong choice mixes two sensors into one column, and afterwards they "
            "cannot be separated. Add one of these under [[field_map_extensions]]: "
            "'%s = %s' for this driver's placement, or '%s = %s' if your history came "
            "from %s.",
            name, name, self.fields.get(name, '?'),
            name, self.undecided[name], catalog.CONTESTED_WITH)

    def _check_shared_channels(self, readings):
        """Warn if two sensors turn out to be writing the same field after all.

        A WH51 and a WH52 are documented with sixteen channels each, but the console
        compatibility table gives them one pool of sixteen between them, so the same
        channel number should never arrive from both. If it does, the assumption is
        wrong and one of the readings is about to overwrite the other.
        """
        for first, second in SHARED_CHANNELS:
            for name in readings:
                if not name.startswith(first):
                    continue
                twin = second + name[len(first):]
                if twin in readings and (name, twin) not in self.warned:
                    self.warned.add((name, twin))
                    log.warning("Both '%s' and '%s' arrived, and they map to the same "
                                "field. One will overwrite the other. Give one of them "
                                "a field of its own in field_map_extensions.",
                                name, twin)

    def _unmapped(self, name, fresh):
        """Decide what happens to a field that is not in the mapping."""
        if name in self.ignored:
            return None
        if name in self.seen:
            return self.seen[name].field

        guess = self.inferrer.guess(name)
        if guess is None:
            log.info("No idea what '%s' is. Left out.", name)
            self.ignored.add(name)
            return None

        fresh.append(guess)
        note = placement_note(name)
        take = self.mode == ALL or (self.mode == SERIES and guess.certain and not note)
        if not take:
            if note and guess.certain:
                # The channel is derived, but where its family lands is a convention,
                # and the field it would take may already hold a different sensor's
                # history. Two series in one column cannot be separated afterwards.
                log.info("New channel '%s' would go to '%s'. Which sensor that is, and "
                         "whether that field is free, only you know. Add "
                         "'%s = %s' under [[field_map_extensions]] to accept it.%s",
                         name, guess.field, name, guess.field, note)
            else:
                log.info("New field '%s' looks like %s (%s), but it was only guessed. "
                         "Left out. Add it to field_map_extensions to keep it.",
                         name, guess.group or 'unknown', guess.why)
            self.ignored.add(name)
            return None

        log.info("New field '%s' -> '%s' (%s), %s.%s", name, guess.field,
                 guess.group or 'no group', guess.why, placement_note(name) or '')
        self.seen[name] = guess
        if guess.group:
            self.groups[guess.field] = guess.group
        return guess.field

    def wanted_groups(self):
        """Unit groups the packet needs, for the caller to register with WeeWX."""
        return dict(self.groups)


def placement_note(raw):
    """Say so when the field name claims more than the hardware does.

    A WN34 reports on tf_chN whether it is a probe in a bed or a lead in a pool, and
    the catalog has to call it something. Whoever installed it is the only one who
    knows, so the moment a new channel turns up is the moment to say that.
    """
    for prefix, note in catalog.PLACEMENT_UNKNOWN.items():
        if re.match(re.escape(prefix) + r'\d', raw):
            return " Placement is a convention, not a reading: " + note
    return None


def _now():
    import time
    return time.time()

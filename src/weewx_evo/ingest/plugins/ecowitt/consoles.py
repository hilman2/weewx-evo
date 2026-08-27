#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Which consoles this driver accepts.

A listener answers whatever reaches its port. Anyone who knows the address can point
a console at it, and Ecowitt hardware announces itself with a PASSKEY derived from
its own MAC address. Two consoles both number their channels from one, so a second
one writing into the same fields would mix two sensors into a column, and nothing
afterwards can separate them.

So the driver accepts exactly the consoles it knows about, and the first one it ever
hears is remembered. Anything else is refused until somebody says it belongs.

Working it out from the readings instead cannot be made to work. There is no rule
that survives a restart, a console added years later, and two consoles uploading at
different intervals. A station sending every eight seconds against one sending every
sixty owns every field for a minute before anyone knows the second one exists.

Where it is remembered, in order of preference:

1.  The configuration, as `passkey` or under `[stations]`. Nothing is stored, and
    the answer moves with the configuration.
2.  The database, in the same metadata table WeeWX keeps `lastUpdate` in, under the
    same key and in the same format. This is the right place: it sits with the
    readings it protects, it is in every backup of them, and it moves with them. A
    database handed back and forth between WeeWX and weewx-evo keeps knowing which
    console it belongs to.
3.  A text file, when there is no database to ask. Better than nothing, and enough
    to keep a restart from handing the station to whichever console speaks first.
"""

import logging
import os

log = logging.getLogger(__name__)

FILENAME = 'ecowitt-consoles.txt'
# The key under which the list lives in the daily summary metadata table.
METADATA_KEY = 'ecowitt_consoles'

HEADER = """# Consoles this driver answers to, one PASSKEY per line.
#
# This file is the fallback. Normally the list lives in the archive's metadata
# table, beside lastUpdate, so that it travels with the readings it protects --
# a backup of the database is a backup of this.
#
# To add a console, do not edit this. Give it a name and a field map under
# [stations] in the configuration, so that its channels go somewhere of their own.
#
# To replace a console, delete its line and restart: the next one to upload is
# adopted. To do without any of this, set 'passkey' in the driver section.
"""


def path_for(weewx_root=None, configured=None, sqlite_root=None):
    """Where to keep the fallback file.

    Beside the database, because that is a directory the service writes to as
    itself, and the one people back up. Under a package installation the
    configuration directory belongs to root and the driver cannot write there.
    """
    if configured:
        return configured
    for directory in (sqlite_root, weewx_root):
        if directory and os.path.isdir(directory) and os.access(directory, os.W_OK):
            return os.path.join(directory, FILENAME)
    return os.path.join('/var/tmp', 'weewx-' + FILENAME)


class Store:
    """Reads and writes the list, from the database if there is one.

    The database is asked first and written first. The file is used when there is no
    binding to open, which is the case in tests and when running the driver directly.
    """

    def __init__(self, path, state=None, config_dict=None, binding='wx_binding'):
        """
        Args:
            path: the fallback file.
            state: a weewx-evo driver state -- get/set/delete on strings, and
                nothing else. The core decides what backs it; normally the
                archive's metadata table.
            config_dict, binding: a WeeWX configuration instead, for this driver
                running under WeeWX. Either works; the state wins.
        """
        self.path = path
        self.state = state
        self.config_dict = config_dict
        self.binding = binding
        self.where = 'file'

    def read(self):
        """Every PASSKEY on record, and where it was found."""
        stored = self._from_database()
        if stored is not None:
            self.where = 'database'
            return stored
        return _read_file(self.path)

    def add(self, passkey, note=''):
        """Record a PASSKEY. Returns where it went, or None if it went nowhere."""
        known = self.read()
        if passkey in known:
            return self.where
        known.append(passkey)
        if self._to_database(known):
            return 'database'
        if _write_file(self.path, passkey, note):
            return self.path
        return None

    def _manager(self):
        """Something that can read and write the archive's metadata, or None.

        Two shapes are accepted because the driver runs in two places. Under
        weewx-evo an ArchiveStore is handed in; under WeeWX a configuration is,
        and the manager is opened from it. Both end up writing the same key in
        the same table.
        """
        if self.state is not None:
            return _StateMetadata(self.state)
        if not self.config_dict:
            return None
        try:
            import weewx.manager
            return weewx.manager.open_manager_with_config(self.config_dict,
                                                          self.binding)
        except Exception as e:
            log.debug("No database to keep the console list in (%s). Using %s.",
                      e, self.path)
            return None

    def _from_database(self):
        manager = self._manager()
        if manager is None:
            return None
        try:
            with manager:
                stored = manager._read_metadata(METADATA_KEY)
        except Exception as e:
            log.debug("Cannot read the console list from the database: %s", e)
            return None
        return [k for k in (stored or '').split(',') if k.strip()]

    def _to_database(self, known):
        manager = self._manager()
        if manager is None:
            return False
        try:
            with manager:
                manager._write_metadata(METADATA_KEY, ','.join(known))
        except Exception as e:
            log.warning("Cannot record the console list in the database: %s", e)
            return False
        return True


class _StateMetadata:
    """A weewx-evo driver state, shaped like the WeeWX manager Store expects.

    The state is get/set/delete on strings and nothing more -- there is no way
    from here to the archive itself. This makes it look like a manager so the
    rest of this module, which is shared with the WeeWX build of the driver,
    does not have to know which one it is talking to.
    """

    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def _read_metadata(self, key):
        return self.state.get(key)

    def _write_metadata(self, key, value):
        self.state.set(key, value)


def _read_file(path):
    try:
        with open(path, encoding='utf-8') as fd:
            return [line.split('#')[0].strip() for line in fd
                    if line.split('#')[0].strip()]
    except OSError:
        return []


def _write_file(path, passkey, note=''):
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        fresh = not os.path.exists(path)
        with open(path, 'a', encoding='utf-8') as fd:
            if fresh:
                fd.write(HEADER)
            fd.write('%s%s\n' % (passkey, ('    # %s' % note) if note else ''))
    except OSError as e:
        log.error("Cannot record the console in %s: %s. It will have to be learned "
                  "again after a restart, or set 'passkey' in the driver section.",
                  path, e)
        return False
    return True


# Kept for anything that used the plain functions.
read = _read_file

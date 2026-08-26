#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Which database columns a station actually needs.

A reading only survives the archive interval if the table has a column for it. The
standard schema has 113 of them, and Ecowitt hardware can fill four times that, so
something has to give.

Two ways to handle it. Ship a schema with every field anyone might own, which is what
the alternatives do, and carry four hundred columns for the twelve sensors in the
garden. Or look at what the hardware actually sends and add those.

This does the second. It needs a payload, not a catalog, which is why it lives next to
the listener rather than in the installer.
"""

# Types by unit group, for the columns we have to create. REAL for anything measured,
# INTEGER for anything counted.
COUNTED = frozenset([
    'group_count', 'group_time', 'group_boolean', 'group_data',
])


def schema_fields():
    """The fields the standard schema already has.

    weewx-evo carries the same wview_extended table WeeWX seeds a database
    with, so this answers identically without needing WeeWX installed.
    """
    from ....db.wview import ARCHIVE_TABLE
    return {name for name, _type in ARCHIVE_TABLE}


def missing(packet, groups, known=None):
    """Return the columns a packet needs and the database does not have.

    Args:
        packet (dict): A loop packet, i.e. what the driver produced.
        groups (dict): WeeWX field -> unit group, for choosing a column type.
        known (set): Fields the database already has. Defaults to the standard schema.

    Returns:
        A list of (field, sql_type), sorted, without the bookkeeping fields.
    """
    if known is None:
        known = schema_fields()
    wanted = []
    for field in sorted(packet):
        if field in ('dateTime', 'usUnits', 'interval') or field in known:
            continue
        sql_type = 'INTEGER' if groups.get(field) in COUNTED else 'REAL'
        wanted.append((field, sql_type))
    return wanted


def commands(wanted, config='/etc/weewx/weewx.conf'):
    """Render the columns as the commands that create them.

    Unchanged from the WeeWX build of this driver: a database is often shared
    with a WeeWX installation, and these are the commands that work there.
    """
    return ["weectl database add-column %s --type %s --config=%s -y" % (field, sql, config)
            for field, sql in wanted]


def evo_commands(wanted, archive=None):
    """The same, for weewx-evo, which adds columns itself."""
    where = (' --archive %s' % archive) if archive else ''
    return ["weewx-evo columns --add%s    # adds %s (%s)" % (where, field, sql)
            for field, sql in wanted]


def occupied(archive):
    """Return {field: (count, last timestamp)} for archive columns that hold data.

    This is what stands between a driver change and a ruined series. If a field this
    driver writes to already has history, that history came from somewhere else, and
    the two are about to be mixed in one column.

    One pass over the table, so it takes a moment on a large database.

    Args:
        archive: a weewx_evo.db.archive.ArchiveStore, or a path to one.
    """
    from ....db.archive import ArchiveStore

    close_after = not isinstance(archive, ArchiveStore)
    store = ArchiveStore(archive, create=False) if close_after else archive
    try:
        fields = [f for f in store.schema.columns
                  if f not in ('dateTime', 'usUnits', 'interval')]
        if not fields:
            return {}
        counts = ', '.join('COUNT("%s"), MAX(CASE WHEN "%s" IS NOT NULL THEN dateTime END)'
                           % (f, f) for f in fields)
        row = store.conn.execute(
            "SELECT %s FROM %s" % (counts, store.table_name)).fetchone()
    finally:
        if close_after:
            store.close()

    used = {}
    for index, field in enumerate(fields):
        count, last = row[index * 2], row[index * 2 + 1]
        if count:
            used[field] = (count, last)
    return used

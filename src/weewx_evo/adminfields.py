"""Where each reading a station sends ends up, and what is already there.

Placing a field is the one decision here that cannot be taken back. A reading
put in a column that already holds another sensor's history mixes two series,
and nothing afterwards can separate them -- not a later correction, not a
rebuild, because the two are the same number in the same row.

Until now the loop for making that decision was: read a log line, edit
`stations.toml`, restart, wait for an upload, read the log again. And the one
thing you need in order to decide -- **whether that column already holds
somebody else's readings** -- is the one thing a log line cannot tell you.

So this page shows the decision with everything it needs:

    raw          what the hardware calls it
    value        what it last sent, so a wrong guess is visible
    goes to      a chooser, the fields that measure the same thing first
    column       whether the archive has one
    holds        how many earlier values are in it
    who          which other station fills it

## History is only a warning when it is somebody else's

The first version said "column holds 4,526 earlier values" beside every
single row, in orange, on an installation with one station that had been
writing those columns for a year. That is the opposite of the point: a
warning that stands beside everything says nothing, and the one row where it
mattered would have read exactly like the other thirty-four.

So the question is not "does this column hold anything" but **whose**. Two
facts the file already knows answer it: the newest record in the archive, and
the newest record in which this column was not null. If they are the same
record, the column is being filled right now -- by this station, since
`holders()` has already spoken for any other. Then the count is a
confirmation, not a warning, and it says so in a different colour.

## The archive is the namespace, not the installation

Upstream this is one question, because there is one database. Here a station
writes into an archive, and two stations in *different* archives filling
`soilTemp1` is not a collision -- it is two places, which is the whole reason
archives exist. So every question here is asked of one archive:

    does the column exist?          in this archive's file
    what does it already hold?      in this archive's file
    who else writes it?             among the stations of this archive

A station that moves to another archive takes its answers with it, which is
why `concerns()` re-checks on that move and not only on a placement.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from . import adminarchives
from . import archives as archive_defs
from . import stations as station_defs
from .db.archive import ArchiveStore

log = logging.getLogger(__name__)

NEWLINE = "\n"

#: Placed nowhere on purpose. The other half of a collision decision: somebody
#: looked at two stations both filling one column and said which of them
#: should have it, and this is the one that should not.
NOWHERE = "-"

#: How far back from the newest record a column may have been written and
#: still count as one being filled now. Not a wall clock: both ends come out
#: of the same file, so a station that has been offline for a week compares
#: the same way as one uploading this minute.
FRESH = 3600.0

#: How far past the end of the schema a numbered family is offered. The
#: standard schema stops at eight extra temperatures because that was enough
#: when it was written; a gateway with three probes, two indoor sensors and a
#: soil array runs out in an afternoon.
UPTO = 16


class Placement:
    """One raw field, and everything needed to decide where it goes."""

    __slots__ = ("column", "field", "group", "holder", "holds", "last",
                 "mine", "nowhere", "raw", "value", "why")

    def __init__(self, raw: str, value: Any = None, field: str = "",
                 group: str = "", column: bool = False, holds: int = 0,
                 holder: str = "", why: str = "", nowhere: bool = False,
                 mine: bool = False, last: int | None = None) -> None:
        self.raw = raw
        self.value = value
        self.field = field
        self.group = group
        #: Whether the archive this station writes into has such a column.
        self.column = column
        #: How many readings are in it already, from whatever wrote them.
        self.holds = holds
        #: Another station of the same archive that fills it, if any.
        self.holder = holder
        #: Whether the newest reading in that column arrived with the newest
        #: record -- so the history in it is this station's own.
        self.mine = mine
        #: When the column was last written, which is what makes the warning
        #: actionable: "4,526 values, last in March 2024" names the sensor
        #: that used to be there.
        self.last = last
        self.why = why
        self.nowhere = nowhere

    @property
    def state(self) -> str:
        """One word for what is true, which decides how the row reads."""
        if self.nowhere:
            return "nowhere"
        if not self.field:
            return "unplaced"
        if self.holder:
            return "taken"
        if not self.column:
            return "nocolumn"
        if self.holds and self.mine:
            return "mine"
        if self.holds:
            return "occupied"
        return "ready"


def archive_of(admin: Any, station: Any) -> archive_defs.Archive:
    return adminarchives.load(admin).get(getattr(station, "archive", None))


def _store(admin: Any, archive: archive_defs.Archive) -> ArchiveStore | None:
    where = Path(archive.file)
    if not where.is_absolute():
        where = Path(admin.path).parent / where
    if not where.exists():
        return None
    try:
        return ArchiveStore(where)
    except Exception:
        log.debug("could not open %s", where, exc_info=True)
        return None


def _stations(admin: Any) -> list:
    return list(station_defs.load(
        Path(admin.path).parent / station_defs.FILENAME))


def holders(admin: Any, archive_name: str) -> dict[str, tuple[str, str]]:
    """{field: (station, raw)} for every field a station of this archive fills.

    Only this archive's. Two stations writing `soilTemp1` into two different
    files are two places, not a collision, and saying otherwise would be a
    warning nobody should act on.
    """
    found: dict[str, tuple[str, str]] = {}
    for one in _stations(admin):
        if getattr(one, "archive", archive_defs.DEFAULT) != archive_name:
            continue
        for raw, field in (getattr(one, "field_map", None) or {}).items():
            if field and field != NOWHERE:
                found[field] = (one.name, raw)
    return found


def placements(admin: Any, station: Any, sent: dict[str, Any],
               catalog: dict[str, str] | None = None) -> list[Placement]:
    """One `Placement` per raw field this station last sent.

    Only what it has actually sent. A catalog is five hundred names long, and
    the answer to "where does my reading go" is not helped by four hundred
    and fifty rows about sensors nobody owns.
    """
    archive = archive_of(admin, station)
    store = _store(admin, archive)
    occupied: dict[str, tuple[int, Any]] = {}
    columns: set[str] = set()
    newest: int | None = None
    if store is not None:
        try:
            occupied = store.occupied()
            columns = set(store.schema.columns)
            newest = store.last_timestamp()
        finally:
            store.close()

    placed = dict(getattr(station, "field_map", None) or {})
    taken = holders(admin, getattr(station, "archive", archive_defs.DEFAULT))
    catalog = catalog or {}
    groups = _groups_of(admin)

    rows = []
    for raw in sorted(sent):
        field = placed.get(raw, catalog.get(raw, ""))
        nowhere = field == NOWHERE
        if nowhere:
            field = ""
        holder = ""
        if field:
            who = taken.get(field)
            # Somebody else's, where somebody else is another station or
            # another raw field of this one. A column takes one answer.
            if who and (who[0] != station.name or who[1] != raw):
                holder = f"{who[0]}/{who[1]}"
        holds, last = occupied.get(field, (0, None)) if field else (0, None)
        rows.append(Placement(
            raw=raw, value=sent.get(raw), field=field,
            group=groups.get(field, "") if field else "",
            column=bool(field) and field in columns,
            holds=holds, holder=holder, nowhere=nowhere, last=last,
            mine=bool(last and newest and last >= newest - FRESH)))
    return rows


def candidates(admin: Any, station: Any) -> dict[str, Any]:
    """Where a reading could go in this station's archive, and what is there.

    One call for the whole table rather than one per row: the answer is the
    same for every row.
    """
    archive = archive_of(admin, station)
    store = _store(admin, archive)
    columns: list[str] = []
    occupied: dict[str, tuple[int, Any]] = {}
    if store is not None:
        try:
            columns = sorted(store.schema.columns)
            occupied = store.occupied()
        finally:
            store.close()
    return {
        "archive": archive,
        "columns": columns,
        "occupied": occupied,
        "holders": holders(admin, getattr(station, "archive",
                                          archive_defs.DEFAULT)),
        "offered": _offered(columns),
    }


def _offered(columns: list[str]) -> list[str]:
    """The columns, plus the next few of every numbered family.

    `extraTemp12` is offered on a database whose schema stops at eight, and
    the row says it has no column yet. That is the point of offering it: the
    column is one button away, and the alternative is somebody discovering
    the limit by having a reading silently dropped.
    """
    import re

    # A family is a series the hardware can have more of than the schema
    # does: extraTemp1 to extraTemp8. `pm2_5` and `co2` end in a digit and
    # are not, which is what the completeness test below is for -- a base
    # whose numbers are not 1..n is a name that happens to have a digit in
    # it, and offering `pm2_6` as a home for a reading is worse than
    # offering nothing.
    seen: dict[str, set[int]] = {}
    for name in columns:
        match = re.match(r"^(.*?[A-Za-z_])(\d+)$", name)
        if match:
            seen.setdefault(match.group(1), set()).add(int(match.group(2)))

    extra = []
    for base, numbers in seen.items():
        highest = max(numbers)
        if len(numbers) < 2 or numbers != set(range(1, highest + 1)):
            continue
        extra.extend(f"{base}{n}" for n in range(highest + 1, UPTO + 1))
    return sorted(set(columns) | set(extra))


# -- writing the decision ----------------------------------------------


def place(admin: Any, station_name: str, raw: str, field: str) -> str:
    """Put one raw field somewhere, for one station. Returns an error or "".

    Written to `stations.toml`, where the field map already lives: two
    consoles both number their channels from one, so which sensor `tf_ch1`
    is has always been a property of the station rather than of the driver.
    """
    where = Path(admin.path).parent / station_defs.FILENAME
    register = station_defs.load(where)
    station = register.by_name(station_name)
    if station is None:
        return f"There is no station called {station_name!r}."
    field = (field or "").strip()
    if field and field != NOWHERE and not field.replace("_", "").isalnum():
        return f"{field!r} is not a usable column name."

    mapped = dict(getattr(station, "field_map", None) or {})
    if field:
        mapped[raw] = field
    else:
        # An empty choice means "whatever the catalog says", which is the
        # absence of a decision rather than a decision to write nothing.
        mapped.pop(raw, None)

    from dataclasses import replace as _replace

    # In place, the way `adminstations.configure` does it: the register is a
    # list and the station is frozen, so the changed one takes its position.
    register.stations[register.stations.index(station)] = _replace(
        station, field_map=mapped)
    try:
        station_defs.save(where, register, f"{station_name}: {raw}")
    except Exception as exc:
        log.exception("could not write the field map")
        return f"Could not write {where}: {exc}"
    return ""


def add_column(admin: Any, station: Any, field: str,
               counted: bool = False) -> str:
    """Give a reading somewhere to live, in this station's archive.

    Not in "the" archive: with two of them the column belongs in the file
    this station writes to, and creating it in the other one would leave the
    reading being dropped exactly as before while the page said it was fixed.
    """
    if not field or not field.replace("_", "").isalnum():
        return f"{field!r} is not a usable column name."
    archive = archive_of(admin, station)
    store = _store(admin, archive)
    if store is None:
        return (f"The archive {archive.name!r} has no file at "
                f"{archive.file} yet, so there is nothing to add a column to.")
    try:
        made = store.add_column(field, "INTEGER" if counted else "REAL")
    except Exception as exc:
        log.exception("could not add the column %r", field)
        return f"Could not add {field!r}: {exc}"
    finally:
        store.close()
    if not made:
        return f"{archive.title} already has a {field!r} column."
    log.info("added column %r to %s", field, archive.file)
    return ""


# -- the table ---------------------------------------------------------


SAYS = {
    "nowhere": ('<span class="note">nowhere, on purpose</span>', ""),
    "unplaced": ('<span class="note">not written</span>', ""),
    "ready": ('<span class="ok">column ready, still empty</span>', ""),
}


def _on(when: int | None) -> str:
    """The date a column was last written, for the warning to be actionable.

    No `%-d`: it is a glibc extension, and this renders on Windows too.
    """
    if not when:
        return ""
    import datetime

    stamp = datetime.datetime.fromtimestamp(when)
    return f"{stamp.day} {stamp:%b %Y}"


def _status(one: Placement, archive: archive_defs.Archive,
            read_only: bool) -> str:
    if one.state in SAYS:
        return SAYS[one.state][0]
    if one.state == "taken":
        return (f'<span class="warn">{html.escape(one.holder)} '
                "fills this column</span>")
    if one.state == "mine":
        # Not a warning. The column holds this station's own history, which
        # is what a working installation looks like, and orange beside every
        # row is how the one row that matters gets missed.
        # A tick and the count. Thirty-five rows saying "writing here" is
        # the same wall of repeated text the orange warning was, only green.
        return f'<span class="ok">✓ {one.holds:,} values</span>'
    if one.state == "occupied":
        # This one is the warning the page exists for: readings in the
        # column, none of them from the record this station just wrote.
        #
        # What it says is what was measured, and no more. "from something
        # else" would be a guess: a sensor whose battery died stops filling
        # its column too, and it is the same sensor. The date is the fact,
        # and whoever reads it knows which of the two it is.
        return (f'<span class="warn">{one.holds:,} values, none since '
                f'{html.escape(_on(one.last)) or "unknown"}</span>')
    # No column. The button is the point of the row.
    if read_only:
        return ('<span class="bad">no column</span>'
                '<br><span class="note">this page is read-only</span>')
    # Which archive is the column heading above, not four words on every
    # such row: "Create it in Kirchdorf an der Amper" wrapped to two lines
    # and pushed the row it belongs to twice as tall as its neighbours.
    return (f'<span class="bad">no column</span>'
            f'<br><button class="quiet" type="submit" name="addcolumn"'
            f' value="{html.escape(one.field)}"'
            f' title="Adds it to {html.escape(archive.title)}">'
            "Add it</button>")


def _chooser(one: Placement, offered: list[str], groups: dict[str, str],
             holders_here: dict[str, tuple[str, str]],
             station: str = "") -> str:
    """Where this reading could go.

    The ones that measure the same thing first: a wind speed offered as a
    home for a temperature is worse than no suggestion, because somebody
    will pick it.
    """
    fits, others = [], []
    for name in offered:
        (fits if one.group and groups.get(name) == one.group
         else others).append(name)

    def option(name: str) -> str:
        note = ""
        who = holders_here.get(name)
        # Not against itself. Every row said "pressure -- kirchdorf/baromabsin"
        # about the placement it was already showing, so a station's own
        # settled choices all read as collisions with somebody.
        if who and who != (station, one.raw):
            note = (f" — {who[1]}" if who[0] == station
                    else f" — {who[0]}")
        selected = " selected" if name == one.field else ""
        return (f'<option value="{html.escape(name)}"{selected}>'
                f"{html.escape(name)}{html.escape(note)}</option>")

    groups_html = ""
    if fits:
        groups_html += ('<optgroup label="Measures the same thing">'
                        + "".join(option(n) for n in fits) + "</optgroup>")
    groups_html += ('<optgroup label="Everything else">'
                    + "".join(option(n) for n in others) + "</optgroup>")
    settled = one.field or one.nowhere
    return (f'<select name="place:{html.escape(one.raw)}">'
            f'<option value=""{"" if settled else " selected"}>'
            "— wherever the catalog puts it —</option>"
            f'<option value="{NOWHERE}"{" selected" if one.nowhere else ""}>'
            "— nowhere —</option>"
            + groups_html + "</select>")


#: The states that are waiting for somebody, in the order they are worth
#: looking at. A reading with nowhere to go is losing data every interval; a
#: column with older history in it is the one placement that cannot be taken
#: back; a contested column is two stations overwriting each other. The rest
#: of the table is working and does not need reading.
WANTED = ("nocolumn", "taken", "occupied", "unplaced")


def table(admin: Any, station: Any, sent: dict[str, Any],
          catalog: dict[str, str] | None = None) -> str:
    """The whole thing, as one form per station.

    Split, not sorted alphabetically. A gateway sends between thirty and
    ninety readings and nearly all of them are going exactly where they
    should; the four that are not were scattered through them by name, so
    finding them meant reading every row. They are their own list now, and
    the rest folds away behind a line saying how many there are.
    """
    rows = placements(admin, station, sent, catalog)
    if not rows:
        return ""
    context = candidates(admin, station)
    archive = context["archive"]
    groups = _groups_of(admin)
    offered = context["offered"]
    here = context["holders"]

    def row(one: Placement) -> str:
        value = ('<span class="note">no reading</span>' if one.value is None
                 else html.escape(str(one.value)))
        return f'''
      <tr>
        <td class="mono">{html.escape(one.raw)}</td>
        <td class="mono">{value}</td>
        <td>{_chooser(one, offered, groups, here, station.name)}</td>
        <td class="note">{html.escape(measures(one.group))}</td>
        <td>{_status(one, archive, admin.read_only)}</td>
      </tr>'''

    def grid(some: list[Placement]) -> str:
        return f'''
    <table class="stations fields">
      <thead><tr><th>Sends</th><th>Last value</th><th>Goes to</th>
                 <th>Measures</th><th>In {html.escape(archive.title)}</th>
      </tr></thead>
      <tbody>{NEWLINE.join(row(one) for one in some)}</tbody>
    </table>'''

    waiting = [one for one in rows if one.state in WANTED]
    waiting.sort(key=lambda one: (WANTED.index(one.state), one.raw))
    settled = [one for one in rows if one.state not in WANTED]

    parts = []
    if waiting:
        parts.append('<p class="lede">'
                     f"{len(waiting)} of these need a decision.</p>")
        parts.append(grid(waiting))
    if settled:
        word = ("reading is" if len(settled) == 1 else "readings are")
        # Shut by default when there is something waiting, open when there is
        # not: with nothing to decide, the fold would be the whole table.
        opened = "" if waiting else " open"
        parts.append(
            f'<details class="settled"{opened}><summary>{len(settled)} '
            f"{word} going where they should</summary>{grid(settled)}"
            "</details>")

    save = ""
    if not admin.read_only:
        save = ('<p><button type="submit">Save these placements</button>'
                '<span class="hint">Written to stations.toml. It takes '
                "effect on the next upload; nothing restarts.</span></p>")
    return f'''
  <form method="post" action="./stations/{html.escape(station.name)}/fields">
    {"".join(parts)}
    {save}
  </form>'''


def measures(group: str) -> str:
    """`group_pressure` reads as `pressure`.

    The prefix is how the unit table namespaces its keys; on a page it is
    five characters of noise on every row.
    """
    return group[6:].replace("_", " ") if group.startswith("group_") else group


def _groups_of(admin: Any) -> dict[str, str]:
    """What each archive field measures, for sorting the chooser.

    `all_groups()`, not `GROUPS`: the second is the standard schema alone, so
    everything a driver names for itself -- `eventRain`, `maxdailygust`, the
    lightning count -- came back with no group. Those are precisely the
    fields somebody opens this page to place, and with no group the chooser
    cannot put the ones measuring the same thing first for any of them.
    """
    try:
        from . import units

        return units.all_groups()
    except Exception:
        log.debug("could not read the unit groups", exc_info=True)
        return {}

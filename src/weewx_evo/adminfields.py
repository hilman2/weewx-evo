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

#: How far past the end of the schema a numbered family is offered. The
#: standard schema stops at eight extra temperatures because that was enough
#: when it was written; a gateway with three probes, two indoor sensors and a
#: soil array runs out in an afternoon.
UPTO = 16


class Placement:
    """One raw field, and everything needed to decide where it goes."""

    __slots__ = ("column", "field", "group", "holder", "holds", "nowhere",
                 "raw", "value", "why")

    def __init__(self, raw: str, value: Any = None, field: str = "",
                 group: str = "", column: bool = False, holds: int = 0,
                 holder: str = "", why: str = "",
                 nowhere: bool = False) -> None:
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
    if store is not None:
        try:
            occupied = store.occupied()
            columns = set(store.schema.columns)
        finally:
            store.close()

    mine = dict(getattr(station, "field_map", None) or {})
    taken = holders(admin, getattr(station, "archive", archive_defs.DEFAULT))
    catalog = catalog or {}

    rows = []
    for raw in sorted(sent):
        field = mine.get(raw, catalog.get(raw, ""))
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
        rows.append(Placement(
            raw=raw, value=sent.get(raw), field=field,
            column=bool(field) and field in columns,
            holds=occupied.get(field, (0, None))[0] if field else 0,
            holder=holder, nowhere=nowhere))
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
    "ready": ('<span class="ok">column ready</span>', ""),
}


def _status(one: Placement, archive: archive_defs.Archive,
            read_only: bool) -> str:
    if one.state in SAYS:
        return SAYS[one.state][0]
    if one.state == "taken":
        return (f'<span class="warn">{html.escape(one.holder)} '
                "fills this column</span>")
    if one.state == "occupied":
        return (f'<span class="warn">column holds {one.holds:,} '
                "earlier values</span>")
    # No column. The button is the point of the row.
    if read_only:
        return ('<span class="bad">no column</span>'
                '<br><span class="note">this page is read-only</span>')
    return (f'<span class="bad">no column</span>'
            f'<br><button class="quiet" type="submit" name="addcolumn"'
            f' value="{html.escape(one.field)}">Create it in '
            f"{html.escape(archive.title)}</button>")


def _chooser(one: Placement, offered: list[str], groups: dict[str, str],
             holders_here: dict[str, tuple[str, str]]) -> str:
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
        if who:
            note = f" — {who[0]}/{who[1]}"
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


def table(admin: Any, station: Any, sent: dict[str, Any],
          catalog: dict[str, str] | None = None) -> str:
    """The whole thing, as one form per station."""
    rows = placements(admin, station, sent, catalog)
    if not rows:
        return ""
    context = candidates(admin, station)
    archive = context["archive"]
    groups = _groups_of(admin)
    offered = context["offered"]
    here = context["holders"]

    body = []
    for one in rows:
        value = ('<span class="note">no reading</span>' if one.value is None
                 else html.escape(str(one.value)))
        chooser = _chooser(one, offered, groups, here)
        body.append(f'''
      <tr>
        <td class="mono">{html.escape(one.raw)}</td>
        <td class="mono">{value}</td>
        <td>{chooser}</td>
        <td class="note">{html.escape(one.group or "")}</td>
        <td>{_status(one, archive, admin.read_only)}</td>
      </tr>''')

    save = ""
    if not admin.read_only:
        save = ('<p><button type="submit">Save these placements</button>'
                '<span class="hint">Written to stations.toml. It takes '
                "effect on the next upload; nothing restarts.</span></p>")
    return f'''
  <form method="post" action="./stations/{html.escape(station.name)}/fields">
    <table class="stations fields">
      <thead><tr><th>Sends</th><th>Last value</th><th>Goes to</th>
                 <th>Measures</th><th>In {html.escape(archive.title)}</th>
      </tr></thead>
      <tbody>{NEWLINE.join(body)}</tbody>
    </table>
    {save}
  </form>'''


def _groups_of(admin: Any) -> dict[str, str]:
    """What each archive field measures, for sorting the chooser."""
    try:
        from . import units

        return dict(units.GROUPS)
    except Exception:
        log.debug("could not read the unit groups", exc_info=True)
        return {}

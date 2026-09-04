"""Where each reading a station sends ends up, and what is already there.

Placing a field is the one decision here that cannot be taken back. A reading
put in a column that already holds another sensor's history mixes two series,
and nothing afterwards can separate them -- not a later correction, not a
rebuild, because the two are the same number in the same row.

Until now the loop for making that decision was: read a log line, edit a
mapping, restart, wait for an upload, read the log again. And the one
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

Upstream this is one question, because there is one database. Here an archive
selects stations, and two archives filling
`soilTemp1` is not a collision -- it is two places, which is the whole reason
archives exist. So every question here is asked of one archive:

    does the column exist?          in this archive's file
    what does it already hold?      in this archive's file
    who else writes it?             among the stations of this archive

A station may be selected by several archives. Each gets its own answer.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from . import adminarchives, placement
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


def _sender_of(station: Any) -> str:
    """Canonical sender ID from a station-like object or the ID itself."""
    from .db.live import sender_id, sender_parts

    if isinstance(station, str):
        sender_parts(station)
        return station
    return sender_id(station.driver, station.identity)


def archives_of(admin: Any, station: Any) -> list[archive_defs.Archive]:
    """Every place that selects this live sender, in register order.

    ``None`` is the broad selection and an empty tuple selects nobody. The
    distinction belongs to the archive file; a station never supplies a
    fallback archive of its own.
    """
    sender = _sender_of(station)
    return [one for one in adminarchives.load(admin).all()
            if one.selects(sender)]


def archive_of(admin: Any, station: Any,
               archive_name: str | None = None) -> archive_defs.Archive:
    """The explicitly named place, or the sole place selecting this station.

    Refusing an ambiguous lookup is important here: saving a placement or
    adding a column to an arbitrary one of two databases cannot be repaired
    from the live journal afterwards.
    """
    choices = archives_of(admin, station)
    if archive_name not in (None, ""):
        for one in choices:
            if one.name == archive_name:
                return one
        raise LookupError(
            f"Place {archive_name!r} does not select this sender.")
    if len(choices) == 1:
        return choices[0]
    if not choices:
        raise LookupError("No place selects this sender.")
    raise LookupError(
        "More than one place selects this sender; name one.")


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


def holders(admin: Any, archive_name: str,
            dialect: str | None = None) -> dict[str, tuple[tuple[str, str], ...]]:
    """Every ``(station, raw)`` that fills each field in one place.

    Only this archive's. Two stations writing `soilTemp1` into two different
    files are two places, not a collision, and saying otherwise would be a
    warning nobody should act on. With a dialect, this is the effective map
    for that dialect. Without one, all dialect-specific maps are considered;
    passing ``""`` therefore still means the actual empty dialect rather than
    accidentally hiding every named one.
    """
    found: dict[str, set[tuple[str, str]]] = {}
    plans = _placements(admin)
    archive = adminarchives.load(admin).get(archive_name)
    selected = [one.sender for one in
                adminarchives.sender_choices(admin, archive)
                if archive.selects(one.sender)]
    for sender in selected:
        dialects = {dialect} if dialect is not None else {""}
        if dialect is None:
            dialects.update(scope.dialect for scope in plans.takes
                            if (not scope.archive or
                                scope.archive == archive_name)
                            and (not scope.station or
                                 scope.station == sender)
                            and scope.dialect)
        for actual in dialects:
            for raw, field in plans.extensions(
                    archive_name, sender, actual).items():
                if field and field != NOWHERE:
                    found.setdefault(field, set()).add((sender, raw))
    return {field: tuple(sorted(owners))
            for field, owners in sorted(found.items())}


def _placements(admin: Any) -> Any:
    """This installation's placements. Empty where the file cannot be read.

    Empty rather than fatal: with no decisions every reading goes where its
    catalog says, which is what an installation that has never opened this
    page does. A page that would not render is worse -- it is the page the
    decision is made on.
    """
    try:
        return placement.load(placement.path_for(Path(admin.path).parent))
    except Exception:
        log.exception("could not read the placements")
        return placement.Placements()


def placements(admin: Any, station: Any, sent: dict[str, Any],
               catalog: dict[str, str] | None = None,
               dialect: str = "", archive_name: str | None = None
               ) -> list[Placement]:
    """One `Placement` per raw field this station last sent.

    Only what it has actually sent. A catalog is five hundred names long, and
    the answer to "where does my reading go" is not helped by four hundred
    and fifty rows about sensors nobody owns.
    """
    archive = archive_of(admin, station, archive_name)
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

    sender = _sender_of(station)
    placed = _placements(admin).extensions(archive.name, sender, dialect)
    taken = holders(admin, archive.name, dialect)
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
            who = next((owner for owner in taken.get(field, ())
                        if owner != (sender, raw)), None)
            # Somebody else's, where somebody else is another station or
            # another raw field of this one. A column takes one answer.
            if who and (who[0] != sender or who[1] != raw):
                labels = {one.sender: one.label for one in
                          adminarchives.sender_choices(admin, archive)}
                holder = f"{labels.get(who[0], who[0])}/{who[1]}"
        holds, last = occupied.get(field, (0, None)) if field else (0, None)
        rows.append(Placement(
            raw=raw, value=sent.get(raw), field=field,
            group=groups.get(field, "") if field else "",
            column=bool(field) and field in columns,
            holds=holds, holder=holder, nowhere=nowhere, last=last,
            mine=bool(last and newest and last >= newest - FRESH)))
    return rows


def candidates(admin: Any, station: Any,
               archive_name: str | None = None,
               dialect: str = "") -> dict[str, Any]:
    """Where a reading could go in this station's archive, and what is there.

    One call for the whole table rather than one per row: the answer is the
    same for every row.
    """
    archive = archive_of(admin, station, archive_name)
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
        "holders": holders(admin, archive.name, dialect),
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


def place(admin: Any, station_name: str, raw: str, field: str,
          dialect: str = "", archive_name: str | None = None) -> str:
    """Put one raw field somewhere, for one station. Returns an error or "".

    Written to `placement.toml`, scoped to this archive, this station and the
    catalog its packets were stored with.

    Not to `stations.toml`, where the field map used to live. Two reasons,
    and the second is what forced the move: a placement has to be expressible
    for a console *nobody has announced*, which has no row there at all --
    and with one archive that console's readings are taken. And a field map
    cannot name a dialect, while a Weather Underground console speaks two.

    It takes effect when the next record is built, including for readings
    already in the live table: the reader re-reads this file, which is the
    whole reason the decision is on that side. Before, it was written to a
    file `configure_drivers` had read once at startup, and reached nothing at
    all until somebody restarted the service.
    """
    if admin.read_only:
        return "This settings page was started read-only."
    try:
        sender = _sender_of(station_name)
        station = station_name
    except ValueError:
        where = Path(admin.path).parent / station_defs.FILENAME
        register = station_defs.load(where)
        station = register.by_name(station_name)
        if station is None:
            return f"There is no sender called {station_name!r}."
        sender = _sender_of(station)
    try:
        archive = archive_of(admin, station, archive_name)
    except (KeyError, LookupError) as exc:
        return str(exc.args[0] if exc.args else exc)
    field = (field or "").strip()
    if field and field != NOWHERE and not field.replace("_", "").isalnum():
        return f"{field!r} is not a usable column name."

    path = placement.path_for(Path(admin.path).parent)
    try:
        plans = placement.load(path)
    except Exception as exc:
        log.exception("could not read the placements")
        return f"Could not read {path}: {exc}"
    # An empty choice means "whatever the catalog says", which is the absence
    # of a decision rather than a decision to write nothing. `decide` removes
    # the line for it.
    plans.decide(archive.name, sender, dialect, raw, field)
    try:
        placement.save(path, plans, f"{sender}: {raw}")
    except Exception as exc:
        log.exception("could not write the placements")
        return f"Could not write {path}: {exc}"
    return ""


def save_for_place(admin: Any, place_name: str, sender_id: str,
                   form: dict[str, Any]) -> str:
    """Save one Place-to-Sender mapping without station or driver state."""
    if admin.read_only:
        return "This settings page was started read-only."
    try:
        sender = _sender_of(sender_id)
        archive = archive_of(admin, sender, place_name)
    except (KeyError, LookupError, ValueError) as exc:
        return str(exc.args[0] if exc.args else exc)

    dialect = str(form.get("dialect") or "")
    wanted = str(form.get("addcolumn") or "").strip()
    # Validate every destination before changing placement.toml. Otherwise a
    # forged add-column value could make the request report failure after its
    # field decisions had already been committed.
    if wanted and not wanted.replace("_", "").isalnum():
        return f"{wanted!r} is not a usable column name."
    decisions: list[tuple[str, str]] = []
    for key, value in sorted(form.items()):
        if not str(key).startswith("place:"):
            continue
        raw = str(key)[6:]
        field = str(value or "").strip()
        if field and field != NOWHERE and not field.replace("_", "").isalnum():
            return f"{field!r} is not a usable column name."
        decisions.append((raw, field))

    if decisions:
        path = placement.path_for(Path(admin.path).parent)
        try:
            plans = placement.load(path)
            for raw, field in decisions:
                plans.decide(archive.name, sender, dialect, raw, field)
            placement.save(path, plans, f"{archive.name} / {sender}")
        except Exception as exc:
            log.exception("could not write the placements")
            return f"Could not write {path}: {exc}"

    if wanted:
        return add_column(admin, sender, wanted, archive_name=archive.name)
    return ""


def add_column(admin: Any, station: Any, field: str,
               counted: bool = False,
               archive_name: str | None = None) -> str:
    """Give a reading somewhere to live, in this station's archive.

    Not in "the" archive: with two of them the column belongs in the file
    this station writes to, and creating it in the other one would leave the
    reading being dropped exactly as before while the page said it was fixed.
    """
    if admin.read_only:
        return "This settings page was started read-only."
    if not field or not field.replace("_", "").isalnum():
        return f"{field!r} is not a usable column name."
    try:
        archive = archive_of(admin, station, archive_name)
    except (KeyError, LookupError) as exc:
        return str(exc.args[0] if exc.args else exc)
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
    "nowhere": ('<span class="note">Ignored</span>', ""),
    "unplaced": ('<span class="note">Not assigned</span>', ""),
    "ready": ('<span class="ok">Ready</span>', ""),
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
        return (f'<span class="warn">Used by {html.escape(one.holder)}'
                "</span>")
    if one.state == "mine":
        # Not a warning. The column holds this station's own history, which
        # is what a working installation looks like, and orange beside every
        # row is how the one row that matters gets missed.
        # A tick and the count. Thirty-five rows saying "writing here" is
        # the same wall of repeated text the orange warning was, only green.
        return f'<span class="ok">✓ {one.holds:,}</span>'
    if one.state == "occupied":
        # This one is the warning the page exists for: readings in the
        # column, none of them from the record this station just wrote.
        #
        # What it says is what was measured, and no more. "from something
        # else" would be a guess: a sensor whose battery died stops filling
        # its column too, and it is the same sensor. The date is the fact,
        # and whoever reads it knows which of the two it is.
        return (f'<span class="warn">{one.holds:,}; last '
                f'{html.escape(_on(one.last)) or "unknown"}</span>')
    # No column. The button is the point of the row.
    if read_only:
        return '<span class="bad">Column missing</span>'
    # Which archive is the column heading above, not four words on every
    # such row: "Create it in Kirchdorf an der Amper" wrapped to two lines
    # and pushed the row it belongs to twice as tall as its neighbours.
    return (f'<span class="bad">Column missing</span>'
            f'<br><button class="quiet" type="submit" name="addcolumn"'
            f' value="{html.escape(one.field)}"'
            f' title="Adds it to {html.escape(archive.title)}">'
            "Add column</button>")


def _chooser(one: Placement, offered: list[str], groups: dict[str, str],
             holders_here: dict[str, tuple[tuple[str, str], ...]],
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
        who = next((owner for owner in holders_here.get(name, ())
                    if owner != (station, one.raw)), None)
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
            "Use catalog mapping</option>"
            f'<option value="{NOWHERE}"{" selected" if one.nowhere else ""}>'
            "Ignore</option>"
            + groups_html + "</select>")


#: The states that are waiting for somebody, in the order they are worth
#: looking at. A reading with nowhere to go is losing data every interval; a
#: column with older history in it is the one placement that cannot be taken
#: back; a contested column is two stations overwriting each other. The rest
#: of the table is working and does not need reading.
WANTED = ("nocolumn", "taken", "occupied", "unplaced")


def sparkline(points: list, width: int = 90, height: int = 18) -> str:
    """The last few hours of one raw reading, as a curve beside its value.

    A number says what a sensor reads now; it does not say what the sensor
    *is*. `tf_ch1` following the outdoor temperature is a probe in the sun,
    `tf_ch1` flat at 21.2 all night is one indoors -- and that is the whole
    of the decision this table exists for.

    Empty for anything with fewer than two points. One point is not a shape,
    and drawing a flat line through it would say "this reading never moves",
    which is a claim about the sensor rather than about how long it has been
    watched.

    Inline SVG with no script and no library: this page is served by the
    station itself, often over a link somebody is tethering.
    """
    if len(points) < 2:
        return ""
    values = [value for _when, value in points]
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    last = len(values) - 1
    steps = " ".join(
        f"{at / last * width:.1f},{height - (value - low) / span * (height - 2) - 1:.1f}"
        for at, value in enumerate(values))
    # The range in the title, so the curve is readable rather than decorative:
    # a shape with no numbers on it cannot say whether it is a sensor in the
    # sun or one that has drifted a tenth of a degree.
    span_text = f"{low:g} to {high:g} over the last few hours"
    return (f'<svg class="trace" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" aria-hidden="true">'
            f'<title>{html.escape(span_text)}</title>'
            f'<polyline points="{steps}" fill="none" stroke="currentColor" '
            'stroke-width="1" /></svg>')


def table(admin: Any, station: Any, sent: dict[str, Any],
          catalog: dict[str, str] | None = None, dialect: str = "",
          series: dict[str, list] | None = None) -> str:
    """One independently scoped form per place that selects this station.

    A station can feed more than one place. Rendering and posting a form for
    each one keeps both the database inspection and the saved placement
    scoped to the place; there is no implicit default to pick the wrong one.
    """
    return "".join(_table_for_archive(
        admin, station, sent, catalog, dialect, series, archive)
        for archive in archives_of(admin, station))


def table_for_place(admin: Any, sender: Any, place_name: str,
                    sent: dict[str, Any],
                    catalog: dict[str, str] | None = None,
                    dialect: str = "",
                    series: dict[str, list] | None = None) -> str:
    """One mapping editor for an explicit Place-to-Sender relationship."""
    try:
        archive = archive_of(admin, sender, place_name)
    except (KeyError, LookupError, ValueError):
        return ""
    return _table_for_archive(
        admin, sender, sent, catalog, dialect, series, archive)


def _table_for_archive(admin: Any, station: Any, sent: dict[str, Any],
                       catalog: dict[str, str] | None, dialect: str,
                       series: dict[str, list] | None,
                       archive: archive_defs.Archive) -> str:
    """The field table for one explicit ``(place, station, dialect)`` scope.

    Split, not sorted alphabetically. A gateway sends between thirty and
    ninety readings and nearly all of them are going exactly where they
    should; the four that are not were scattered through them by name, so
    finding them meant reading every row. They are their own list now, and
    the rest folds away behind a line saying how many there are.
    """
    rows = placements(admin, station, sent, catalog, dialect, archive.name)
    series = series or {}
    if not rows:
        return ""
    context = candidates(admin, station, archive.name, dialect)
    groups = _groups_of(admin)
    offered = context["offered"]
    here = context["holders"]

    def row(one: Placement) -> str:
        value = ('<span class="note">no reading</span>' if one.value is None
                 else html.escape(str(one.value)))
        return f'''
      <tr>
        <td class="mono">{html.escape(one.raw)}</td>
        <td class="mono">{value}{sparkline(series.get(one.raw) or [])}</td>
        <td>{_chooser(one, offered, groups, here, _sender_of(station))}</td>
        <td class="note">{html.escape(measures(one.group))}</td>
        <td>{_status(one, archive, admin.read_only)}</td>
      </tr>'''

    def grid(some: list[Placement]) -> str:
        return f'''
    <table class="stations fields">
      <thead><tr><th>Sender field</th><th>Latest reading</th><th>Archive field</th>
                 <th>Measurement</th><th>Status</th>
      </tr></thead>
      <tbody>{NEWLINE.join(row(one) for one in some)}</tbody>
    </table>'''

    waiting = [one for one in rows if one.state in WANTED]
    waiting.sort(key=lambda one: (WANTED.index(one.state), one.raw))
    settled = [one for one in rows if one.state not in WANTED]

    parts = []
    if waiting:
        parts.append(f'<p class="warn">{len(waiting)} need attention.</p>')
        parts.append(grid(waiting))
    if settled:
        word = "field" if len(settled) == 1 else "fields"
        # Shut by default when there is something waiting, open when there is
        # not: with nothing to decide, the fold would be the whole table.
        opened = "" if waiting else " open"
        parts.append(
            f'<details class="settled"{opened}><summary>{len(settled)} mapped '
            f"{word}</summary>{grid(settled)}"
            "</details>")

    save = ""
    if not admin.read_only:
        save = ('<div class="place-save actions">'
                '<button type="submit">Save field mappings</button></div>')
    sender = _sender_of(station)
    sender_label = str(getattr(station, "label", "")
                       or getattr(station, "name", "") or sender)
    return f'''
  <section class="place-section place-field-scope"
           id="place-fields-{html.escape(archive.name)}-{html.escape(sender)}">
    <header><span class="note">Place · Sender</span>
      <h4>{html.escape(archive.title)} · {html.escape(sender_label)}</h4>
      <code>{html.escape(sender)}</code></header>
  <form method="post" action="./places/{html.escape(archive.name)}/fields">
    <input type="hidden" name="archive" value="{html.escape(archive.name)}">
    <input type="hidden" name="sender" value="{html.escape(sender)}">
    <input type="hidden" name="dialect" value="{html.escape(dialect)}">
    {"".join(parts)}
    {save}
  </form>
  </section>'''


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

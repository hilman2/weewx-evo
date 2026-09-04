"""Read-only diagnostics for the live journal.

The page shows stored rows and executes only the inert dialect descriptions
stored beside them.  It does not import a collector driver or consult
``stations.toml`` to reinterpret data after ingest.
"""

from __future__ import annotations

import html
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import adminstations, placement
from . import archives as archive_defs
from .db.live import Packet, SenderIdentity, sender_id

log = logging.getLogger(__name__)

#: Rows a refresh carries. A console reporting every eight seconds fills this
#: in four minutes, which is more than anybody reads at once.
SHOWN = 30

#: How far back the console summary counts. Bounded so that a table holding a
#: week answers as fast as one holding an hour.
WINDOW = 3600


def _sql_name(value: str) -> str:
    """One SQLite identifier, quoted as data rather than syntax."""
    return '"' + str(value).replace('"', '""') + '"'


def feed(admin: Any, limit: int = SHOWN, before: int | None = None,
         after: int | None = None) -> dict:
    """Rows of the live table, with every column it has.

    Three ways in, and they are the page's three needs rather than three
    shapes of the same request:

        neither     the newest `limit` rows, and the summary. What a page
                    opens with.
        after=seq   only what has arrived since -- usually nothing, once in a
                    while one row. What the poll asks, every few seconds.
        before=seq  the `limit` rows older than that. What scrolling asks.

    Paged on `seq` rather than on an offset. A table this one is being
    written to while somebody reads it: with `LIMIT ... OFFSET`, a row
    arriving between two scrolls shifts everything down one, and the reader
    silently sees a row twice and never sees another.

    Returns `{"now", "columns", "rows", "senders", "held", "span", "more",
    "reason"}`. `reason` is set and the rest empty where the table cannot be
    read -- a split installation keeps the live database on the machine with
    the listener, and "nothing is arriving" about a database this process
    cannot see is a worse answer than saying it cannot see it.
    """
    now = time.time()
    where = adminstations.live_db(admin)
    if where is None:
        return _nothing(now, "no live database here")

    try:
        conn = sqlite3.connect(f"file:{Path(where).as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        log.debug("could not open the live journal", exc_info=True)
        return _nothing(now, "live journal cannot be opened")
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(packet)")]
        if not columns:
            return _nothing(now, "there is no packet table in that file")
        # SQLite schema names are data too. Doubling quotes keeps a locally
        # modified database from turning a column name into SQL syntax.
        named = ", ".join(_sql_name(one) for one in columns)
        if after is not None:
            # Oldest first here, so that prepending them in order leaves the
            # newest at the top. Capped like any other page: a browser left
            # open through an outage must not ask for a day of packets on the
            # first refresh after it.
            rows = conn.execute(
                f"SELECT {named} FROM packet WHERE seq > ?"
                " ORDER BY seq DESC LIMIT ?", (after, limit)).fetchall()
        elif before is not None:
            rows = conn.execute(
                f"SELECT {named} FROM packet WHERE seq < ?"
                " ORDER BY seq DESC LIMIT ?", (before, limit)).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {named} FROM packet ORDER BY seq DESC LIMIT ?",
                (limit,)).fetchall()
        held, first, last = conn.execute(
            "SELECT count(*), min(dateTime), max(dateTime) FROM packet"
        ).fetchone()
        has_sender = "sender" in columns
        sender_column = "sender, " if has_sender else ""
        heard = conn.execute(
            f"SELECT {sender_column}driver, identity, MAX(dateTime), COUNT(*)"
            " FROM packet WHERE dateTime > ?"
            f" GROUP BY {sender_column}driver, identity",
            (now - WINDOW,)).fetchall()
        directory = _directory(conn)
        mappings = _mappings(conn, rows, columns)
    except sqlite3.Error:
        log.debug("could not read the live journal", exc_info=True)
        return _nothing(now, "live journal cannot be read")
    finally:
        conn.close()

    labels = {one.sender: one for one in directory.senders()}
    placers = _placers(admin, directory)
    out = []
    for row in rows:
        one = dict(zip(columns, row, strict=True))
        if "data" in one:
            one["data"] = _readings(one["data"])
        one["age"] = round(now - (one.get("dateTime") or 0), 1)
        canonical = str(one.get("sender") or sender_id(
            one.get("driver", ""), one.get("identity", "")))
        identity = labels.get(canonical)
        one["sender_name"] = (identity.label if identity and identity.label
                              else canonical)
        one["canonical_sender"] = canonical
        one["mapping_spec"] = mappings.get(one.get("mapping"))
        out.append(one)

    for one in out:
        if isinstance(one.get("data"), dict):
            selected = [(archive, placer) for archive, placer in placers
                        if archive.selects(one["canonical_sender"])]
            by_place = {archive.title: _goes_to(placer, one)
                        for archive, placer in selected}
            one["places"] = [archive.title for archive, _placer in selected]
            one["goes_to_by_place"] = by_place
            one["mapping_available"] = (not one.get("dialect")
                                        or one.get("mapping_spec") is not None)
            # Kept as a compatibility summary for narrow API callers. It is
            # populated only when the answer is unambiguous.
            one["goes_to"] = (next(iter(by_place.values()))
                              if len(by_place) == 1 else {})
            # The declarative catalog can be large. It is execution input on
            # the server, not another copy of the diagnostic response.
            one.pop("mapping_spec", None)

    return {
        "now": now,
        "columns": columns,
        "rows": out,
        "held": held,
        "span": [first, last],
        # Whether asking again with `before` would return anything. A short
        # page is the end of the table; the page stops asking rather than
        # sending a request per scroll for ever.
        "more": len(rows) == limit,
        "senders": _senders(directory, heard, now, placers),
        "reason": "",
    }


def _nothing(now: float, reason: str) -> dict:
    return {"now": now, "columns": [], "rows": [], "held": 0,
            "span": [None, None], "more": False, "senders": [],
            "reason": reason}


def _readings(data: Any) -> Any:
    """The `data` column as an object, or the text where it is not one.

    Not silently emptied. A row whose JSON will not parse is exactly the row
    somebody is looking for, and showing it as no readings at all would hide
    it on the page that exists to find it.
    """
    try:
        found = json.loads(data)
    except (TypeError, ValueError):
        return {"(unreadable)": str(data)[:200]}
    return found if isinstance(found, dict) else {"(not an object)": found}


class _SenderDirectory:
    """A request-local, read-only snapshot of live sender metadata."""

    def __init__(self, values: list[SenderIdentity]) -> None:
        self.values = values

    def senders(self) -> list[SenderIdentity]:
        return list(self.values)


def _directory(conn: sqlite3.Connection) -> _SenderDirectory:
    """Sender names from live itself; never from listener configuration."""
    try:
        rows = conn.execute(
            "SELECT sender, driver, identity, COALESCE(label, '')"
            " FROM sender_identity").fetchall()
    except sqlite3.Error:
        # An old journal remains diagnosable without being migrated by this
        # read-only page. It simply has no saved presentation names yet.
        rows = [(sender_id(driver, identity), driver, identity, "")
                for driver, identity in conn.execute(
                    "SELECT DISTINCT driver, identity FROM packet")]
    return _SenderDirectory([
        SenderIdentity(str(sender), str(driver), str(identity), str(label or ""))
        for sender, driver, identity, label in rows])


def _mappings(conn: sqlite3.Connection, rows: list[tuple],
              columns: list[str]) -> dict[Any, dict[str, Any]]:
    """Referenced inert mapping specs for just this page of rows."""
    if "mapping" not in columns:
        return {}
    import hashlib

    at = columns.index("mapping")
    references = {row[at] for row in rows if row[at]}
    found: dict[Any, dict[str, Any]] = {}
    digests = [one for one in references
               if isinstance(one, str) and not one.startswith("{")]
    encoded: dict[str, str] = {}
    if digests:
        marks = ",".join("?" for _one in digests)
        try:
            encoded = {str(digest): str(spec) for digest, spec in conn.execute(
                f"SELECT digest, spec FROM dialect_mapping WHERE digest IN ({marks})",
                digests)}
        except sqlite3.Error:
            encoded = {}
    for reference in references:
        inline = isinstance(reference, str) and reference.startswith("{")
        raw = reference if inline else encoded.get(reference)
        if not isinstance(raw, str) or len(raw.encode()) > 128 * 1024:
            continue
        if not inline and hashlib.sha256(raw.encode()).hexdigest() != reference:
            continue
        try:
            spec = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if _valid_mapping(spec):
            found[reference] = spec
    return found


def _valid_mapping(spec: Any) -> bool:
    """Enough structural validation to label a stored description usable."""
    if not isinstance(spec, dict) or spec.get("version") != 1:
        return False
    if type(spec.get("usUnits")) is not int or spec["usUnits"] not in (1, 16, 17):
        return False
    fields = spec.get("fields")
    if not isinstance(fields, dict) or not all(
            isinstance(raw, str) and isinstance(target, str)
            for raw, target in fields.items()):
        return False
    for key in ("metadata", "contested"):
        value = spec.get(key, [])
        if not isinstance(value, list) or not all(isinstance(one, str)
                                                  for one in value):
            return False
    scale = spec.get("scale", {})
    groups = spec.get("groups", {})
    absent = spec.get("absent", [])
    return (isinstance(scale, dict)
            and all(isinstance(raw, str)
                    and type(factor) in (int, float)
                    for raw, factor in scale.items())
            and isinstance(groups, dict)
            and all(isinstance(field, str) and isinstance(group, str)
                    for field, group in groups.items())
            and isinstance(absent, list)
            and all(type(value) in (str, int, float) for value in absent))


def _senders(directory: _SenderDirectory, heard: list, now: float,
             placers: list[tuple[Any, Any]]) -> list[dict]:
    """One status row per sender heard in the bounded summary window."""
    labels = {one.sender: one for one in directory.senders()}
    found = []
    for row in heard:
        if len(row) == 5:
            canonical, driver, identity, last, count = row
        else:
            driver, identity, last, count = row
            canonical = sender_id(driver, identity)
        canonical = str(canonical or sender_id(driver, identity))
        entry = labels.get(canonical)
        used = [archive.title for archive, _placer in placers
                if archive.selects(canonical)]
        found.append({
            "sender": canonical,
            "name": entry.label if entry and entry.label else canonical,
            "named": bool(entry and entry.label),
            "driver": driver,
            "identity": identity,
            "age": round(now - (last or 0), 1),
            "packets": count,
            "places": used,
        })
    found.sort(key=lambda one: str(one["name"]).casefold())
    return found


def _placers(admin: Any, directory: _SenderDirectory) -> list[tuple[Any, Any]]:
    """Place-specific interpreters built without migrating or loading drivers."""
    directory_path = Path(admin.path).parent
    archive_path = directory_path / archive_defs.FILENAME
    if not archive_path.exists():
        return []
    try:
        archives = archive_defs.Register.load(archive_path)
        plans = placement.load(placement.path_for(directory_path))
    except Exception:
        log.debug("could not read Place mappings for live diagnostics",
                  exc_info=True)
        return []
    return [(archive, placement.Placer(archive, plans, directory=directory))
            for archive in archives.all()]


def _goes_to(placer: Any, row: dict) -> dict[str, str]:
    """Raw name -> the archive column it reaches, for one row.

    **One placement per raw name**, on a packet holding only that name. The
    first version placed the whole row once and matched each column back to a
    raw name by its *value* -- which is wrong the moment two sensors read the
    same, and two thermometers in one garden read the same all day. Measured:
    a console sending `tempf=66.6` and `tf_ch1=66.6` had the contested
    `tf_ch1` reported as reaching `outTemp`, on the page where that decision
    is made.
    """
    found = {}
    for name, value in row["data"].items():
        try:
            got = placer.place(Packet(
                dateTime=int(row.get("dateTime") or 0),
                usUnits=int(row.get("usUnits") or 1), data={name: value},
                driver=row.get("driver", "") or "",
                identity=row.get("identity", "") or "",
                sender=row.get("canonical_sender", "") or "",
                dialect=row.get("dialect"),
                mapping=row.get("mapping_spec")))
        except Exception:
            log.debug("could not place %r", name, exc_info=True)
            continue
        placed = got.data if got is not None else {}
        # Exactly one column, or none. The placer does not derive here, so
        # more than one would be something new -- and saying nothing is the
        # honest answer to a question this cannot answer.
        if len(placed) == 1:
            found[name] = next(iter(placed))
    return found


def nav(admin: Any, active: str) -> list[str]:
    current = " aria-current='page'" if active == "live" else ""
    return [f'<a href="./live"{current}>Live journal</a>']


def overview(admin: Any, message: str = "", error: str = "") -> str:
    """Read-only journal rows and a bounded status summary."""
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
  <h2>Live journal</h2>
  {problem}
  <p class="note"><strong>Read-only diagnosis.</strong> Stored packets, newest first.</p>
  <div id="livestate" class="note">reading…</div>
  <h3>Senders in the last hour</h3>
  <div id="livesenders"></div>
  <h3>Packets</h3>
  <div class="scroller"><div id="liverows"></div></div>
  <script>{_SCRIPT}</script>'''


#: No framework and no library: this page is served by the station itself,
#: often over a link somebody is tethering. `textContent` throughout rather
#: than innerHTML with values in it -- a console names its own fields, and
#: both the names and the values reach this table.
_SCRIPT = """
(function () {
  var state = document.getElementById('livestate');
  var rowsBox = document.getElementById('liverows');
  var who = document.getElementById('livesenders');
  var open = {};

  // Every cell keeps the whole value in its tooltip. What is shortened here
  // is only what is *shown*: an identity is 32 hex characters and a raw
  // upload is a kilobyte, and either at full width pushes the columns
  // somebody is reading off the screen.
  function cell(tr, text, cls, cut) {
    var td = document.createElement('td');
    var full = text === null || text === undefined ? '' : String(text);
    td.textContent = cut ? short(full, cut) : full;
    if (cut && full.length > cut) { td.title = full; }
    if (cls) { td.className = cls; }
    tr.appendChild(td);
    return td;
  }

  // Which column takes whatever width is left over. Named rather than
  // positional: the columns come from the schema, and this page exists to
  // survive that changing.
  var STRETCH = 'raw';

  function table(head) {
    var t = document.createElement('table');
    // Its own class. `stations fields` is a form layout with five hard
    // column widths in it, and twelve columns in that fold to one character
    // per line with the headings stacked on top of each other.
    t.className = 'rows';
    var tr = document.createElement('tr');
    // Something has to take the slack, or a wide window puts a hand's width
    // between every pair of columns. The last one in the list where the
    // named one is not there -- a readings table has no `raw`.
    var takes = head.indexOf(STRETCH) >= 0 ? STRETCH : head[head.length - 1];
    head.forEach(function (name) {
      var th = document.createElement('th');
      th.textContent = name;
      if (name === takes) { th.className = 'stretch'; }
      tr.appendChild(th);
    });
    var thead = document.createElement('thead');
    thead.appendChild(tr);
    t.appendChild(thead);
    t.appendChild(document.createElement('tbody'));
    return t;
  }

  function senders(rows) {
    who.textContent = '';
    if (!rows.length) { who.textContent = 'None'; return; }
    var t = table(['sender', 'input', 'status', 'used by', 'in the hour']);
    rows.forEach(function (one) {
      var tr = document.createElement('tr');
      cell(tr, one.name + (one.named ? '' : ' (unnamed)'), '', 28);
      cell(tr, one.driver + ' / ' + one.identity, '', 32);
      cell(tr, one.age.toFixed(0) + ' s ago');
      cell(tr, (one.places || []).join(', ') || 'not assigned', '', 32);
      cell(tr, one.packets);
      t.querySelector('tbody').appendChild(tr);
    });
    who.appendChild(t);
  }

  function short(value, cut) {
    var text = String(value);
    return text.length > cut ? text.slice(0, cut) + '\\u2026' : text;
  }

  //: How much of each column is shown before it is cut. Only the ones that
  //: are long and rarely the question -- everything else is its full value,
  //: because this page exists to show what is in the table.
  var CUT = {identity: 20, digest: 10, raw: 90};

  function readings(row) {
    var names = Object.keys(row.data || {}).sort();
    var t = table(['raw field', 'value', 'Place / archive field']);
    var body = t.querySelector('tbody');
    names.forEach(function (name) {
      var tr = document.createElement('tr');
      cell(tr, name);
      cell(tr, row.data[name], '', 40);
      var places = Object.keys(row.goes_to_by_place || {});
      var routes = places.map(function (place) {
        var to = row.goes_to_by_place[place][name];
        return place + ': ' + (to || 'not used');
      });
      var text = routes.join(' · ');
      if (!places.length) { text = 'not assigned'; }
      if (row.mapping_available === false) { text = 'mapping unavailable'; }
      cell(tr, text, routes.length ? '' : 'note', 80);
      body.appendChild(tr);
    });
    return t;
  }

  function heading(data) {
    var span = '';
    if (data.span[0] && data.span[1] > data.span[0]) {
      span = ', ' + ((data.span[1] - data.span[0]) / 3600).toFixed(1)
        + ' h of them';
    }
    state.textContent = data.held.toLocaleString() + ' packet(s) in the table'
      + span + (held.length ? ', showing ' + held.length + ', newest '
        + held[0].age.toFixed(0) + ' s ago' : '')
      + (more ? '' : ' \\u00b7 that is all of them');
  }

  function rowFor(row) {
    var tr = document.createElement('tr');
    columns.forEach(function (name) {
      if (name === 'data') {
        var n = Object.keys(row.data || {}).length;
        var td = cell(tr, (open[row.seq] ? '\\u25be ' : '\\u25b8 ')
                      + n + ' reading' + (n === 1 ? '' : 's'), 'open');
        td.title = open[row.seq] ? 'hide them' : 'show them';
        td.addEventListener('click', function () {
          open[row.seq] = !open[row.seq];
          redraw();
        });
      } else {
        cell(tr, row[name], '', CUT[name]);
      }
    });
      cell(tr, row.sender_name);
      cell(tr, row.age.toFixed(0) + ' s');
    return tr;
  }

  // The whole table, from what has been loaded. Redrawn rather than patched:
  // the rows are a list this holds, and rebuilding thirty of them is cheaper
  // than keeping the DOM and the list in step -- which is the kind of
  // bookkeeping that goes wrong once and then reads as a lost packet.
  function redraw() {
    rowsBox.textContent = '';
    if (!columns.length) { return; }
    var t = table(columns.concat(['sender name', 'age']));
    var body = t.querySelector('tbody');
    held.forEach(function (row) {
      body.appendChild(rowFor(row));
      if (open[row.seq]) {
        var wide = document.createElement('tr');
        var td = document.createElement('td');
        td.colSpan = columns.length + 2;
        td.className = 'wide';
        td.appendChild(readings(row));
        wide.appendChild(td);
        body.appendChild(wide);
      }
    });
    rowsBox.appendChild(t);
  }

  var held = [];
  var columns = [];
  var more = true;
  var asking = false;

  function ask(query) {
    if (asking) { return Promise.resolve(null); }
    asking = true;
    return fetch('./live.json' + (query || ''), {cache: 'no-store'})
      .then(function (r) { return r.json(); })
      .then(function (data) {
        asking = false;
        if (data.reason) { state.textContent = data.reason; return null; }
        columns = data.columns;
        senders(data.senders);
        return data;
      })
      .catch(function () {
        asking = false;
        state.textContent = 'cannot reach the live journal';
        return null;
      });
  }

  function first() {
    ask('').then(function (data) {
      if (!data) { return; }
      held = data.rows;
      more = data.more;
      redraw();
      heading(data);
    });
  }

  // What has arrived since the newest row on the page, prepended. Not the
  // first page again: that would throw away everything scrolling had
  // loaded, every three seconds, and put the reader back at the top.
  function poll() {
    if (!held.length) { first(); return; }
    ask('?after=' + held[0].seq).then(function (data) {
      if (!data) { return; }
      if (data.rows.length) { held = data.rows.concat(held); redraw(); }
      heading(data);
    });
  }

  // And the page before the oldest row, appended. `seq` rather than an
  // offset: this table is being written to while somebody reads it, and
  // with an offset a row arriving between two scrolls shifts everything
  // down one -- so the reader sees a row twice and never sees another.
  function older() {
    if (!more || !held.length) { return; }
    ask('?before=' + held[held.length - 1].seq).then(function (data) {
      if (!data) { return; }
      held = held.concat(data.rows);
      more = data.more;
      redraw();
      heading(data);
    });
  }

  addEventListener('scroll', function () {
    // Within a screen of the bottom. Asking at the very end means the reader
    // watches a gap while it loads, which on a phone is most of a second.
    var left = document.body.scrollHeight - innerHeight - scrollY;
    if (left < innerHeight) { older(); }
  }, {passive: true});

  first();
  // Slower than a console reports, on purpose: this is a page somebody
  // leaves open, and each refresh is a query and a placement per reading.
  setInterval(poll, 3000);
}());
"""

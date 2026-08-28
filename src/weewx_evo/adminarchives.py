"""The archives page: one row per place this installation keeps readings for.

Hand-written for the same reason the stations page is. The form generator
takes one named value at a time, and an archive is a set of them -- a file,
a label and three numbers -- repeated per row.

The page has one job the settings page cannot do: it is where the second
archive comes from, and adding it is the moment `station.altitude` stops
being a global. So it writes both rows the first time, and it says on the
settings page that those fields have moved.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from . import archives as archive_defs
from . import config as config_file
from . import stations as station_defs

log = logging.getLogger(__name__)

NEWLINE = "\n"


def path_for(admin: Any) -> Path:
    """Beside the configuration file, like stations.toml and plots.toml."""
    return Path(admin.path).parent / archive_defs.FILENAME


def settings_of(admin: Any) -> Any:
    """The saved settings, as something the register can read.

    Not the running `Settings`: this page reads the file it writes, and the
    running one belongs to whichever process is listening. What it needs is
    the seven values the default archive is made of.
    """
    current = admin.config()

    class Saved:
        def get(self, name: str, default: Any = None) -> Any:
            # `resolved`, not `get`: a container sets WEEWX_EVO_ARCHIVE, and
            # reading the file alone had this page reporting about
            # /data/archive/weewx.sdb while the archiver wrote /data/weewx.sdb.
            value = config_file.resolved(current, name)
            return default if value in (None, "") else value

    return Saved()


def load(admin: Any) -> archive_defs.Register:
    return archive_defs.Register.load(path_for(admin), settings_of(admin))


def store(admin: Any, register: archive_defs.Register) -> str:
    """Write them. Returns an error, or empty if it worked."""
    if admin.read_only:
        return "This settings page was started read-only."
    try:
        register.save(path_for(admin))
    except Exception as exc:
        log.exception("could not write the archives")
        return f"Could not write {path_for(admin)}: {exc}"
    return ""


def _number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def from_form(form: dict, name: str = "") -> archive_defs.Archive:
    return archive_defs.Archive(
        name=str(name or form.get("name") or "").strip().lower(),
        file=str(form.get("file") or "").strip(),
        label=str(form.get("label") or "").strip(),
        latitude=_number(form.get("latitude")),
        longitude=_number(form.get("longitude")),
        altitude=_number(form.get("altitude")),
        url=str(form.get("url") or "").strip(),
        rain_year_start=int(_number(form.get("rain_year_start")) or 1),
    )


# -- what the operator does --------------------------------------------


def create(admin: Any, form: dict) -> tuple[archive_defs.Archive | None, str]:
    """Add an archive. Returns (what was added, error)."""
    register = load(admin)
    wanted = from_form(form)
    if not wanted.file and wanted.name:
        # Offered rather than demanded: somebody adding a second site should
        # not have to invent a path, and this is the one every other file
        # here would have chosen anyway.
        wanted = _with(wanted, file=f"data/{wanted.name}.sdb")
    problem = register.why_not(wanted)
    if problem:
        return None, problem
    register.add(wanted)
    error = store(admin, register)
    return (None, error) if error else (wanted, "")


def configure(admin: Any, name: str, form: dict) -> str:
    """Change one archive in place."""
    register = load(admin)
    if not any(one.name == name for one in register.all()):
        return f"There is no archive called {name!r}."
    wanted = from_form(form, name=name)
    problem = register.why_not(wanted, replacing=name)
    if problem:
        return problem
    register.replace(name, wanted)
    return store(admin, register)


def remove(admin: Any, name: str) -> str:
    """Take one off the list. The file stays where it is."""
    register = load(admin)
    stations = station_defs.load(
        Path(admin.path).parent / station_defs.FILENAME)
    using = [one.name for one in stations if one.archive == name]
    if using:
        # Refused rather than orphaned: a station pointing at an archive that
        # is gone falls back to the default, which silently mixes one site's
        # readings into another's series. That is the exact failure all of
        # this exists to prevent.
        return (f"{', '.join(sorted(using))} still write into {name!r}. "
                "Point them somewhere else first.")
    try:
        if not register.remove(name):
            return f"There is no archive called {name!r}."
    except ValueError as exc:
        return str(exc)
    return store(admin, register)


def _with(archive: archive_defs.Archive, **changes: Any) -> archive_defs.Archive:
    return archive_defs.Archive(**{**archive.as_dict(), "name": archive.name,
                                   **changes})


# -- the page ----------------------------------------------------------


def nav(admin: Any, active: str) -> list[str]:
    register = load(admin)
    out = ['<p class="navhead">Archives</p>']
    here = active in ("archives", "new-archive")
    current = " aria-current='page'" if here else ""
    # The count carries a mark when something is wrong, because the one thing
    # that can be wrong here is invisible everywhere else: the readings stay
    # right and only the day boundaries move.
    trouble = register.concerns()
    mark = ""
    if trouble:
        mark = ' <span class="warn" title="something needs looking at">!</span>'
    out.append(f'<a href="./archives"{current}>Series{mark}'
               f'<span class="count">{len(register)}</span></a>')
    return out


def _place(one: archive_defs.Archive) -> str:
    bits = []
    if one.latitude is not None and one.longitude is not None:
        bits.append(f"{one.latitude:.4f}, {one.longitude:.4f}")
    if one.altitude is not None:
        bits.append(f"{one.altitude:g} m")
    if not bits:
        return ('<span class="note">no coordinates, so sunrise and the '
                "pressure reduction fall back to the settings</span>")
    return html.escape(" &middot; ".join(bits)).replace("&amp;middot;", "&middot;")


def _size(path: Path) -> str:
    try:
        return f"{path.stat().st_size / 1e6:.1f} MB"
    except OSError:
        return "not written yet"


def overview(admin: Any, message: str = "", error: str = "") -> str:
    register = load(admin)
    stations = station_defs.load(
        Path(admin.path).parent / station_defs.FILENAME)
    base = Path(admin.path).parent
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    # The banner above the page says it. Printing it a second time in the
    # body was two "Saved." one under the other, which reads as two things
    # having happened.
    said = ""

    add = ""
    if not admin.read_only:
        add = ('<div class="actions">'
               '<a class="button" href="./new-archive">Add an archive</a>'
               "</div>")
    trouble = register.concerns()
    rows = []
    for one in register.all():
        writing = sorted(s.name for s in stations if s.archive == one.name)
        where = Path(one.file)
        if not where.is_absolute():
            where = base / where
        who = (", ".join(html.escape(n) for n in writing) if writing
               else '<span class="note">nothing writes into it yet</span>')
        removable = ""
        if not admin.read_only and one.name != archive_defs.DEFAULT:
            removable = f'''
        <form method="post" action="./archives/{html.escape(one.name)}/remove">
          <button class="quiet" type="submit">Remove</button>
        </form>'''
        said = trouble.get(one.name, "")
        concern = (f'<br><span class="warn">{html.escape(said)}</span>'
                   if said else "")
        rows.append(f'''
    <tr>
      <td><strong>{html.escape(one.title)}</strong>
          <br><span class="note">{html.escape(one.name)}</span></td>
      <td><code>{html.escape(one.file)}</code>
          <br><span class="note">{_size(where)}</span></td>
      <td>{_place(one)}{concern}</td>
      <td>{who}</td>
      <td>{removable}</td>
    </tr>''')

    note = ""
    if register.overriding():
        note = ('<p class="note">These are what the pages print and what the '
                "formulas use. While this list exists, the station name, "
                "coordinates and altitude on the System page are not read.</p>")
    else:
        note = ('<p class="note">One series, described by the settings. '
                "Adding a second writes both into "
                f"<code>{html.escape(str(path_for(admin)))}</code>, and the "
                "station name, coordinates and altitude move here.</p>")

    return f'''
<h2>Archives</h2>
{problem}{said}
<p class="lede">An archive is a measurement series for one place: its own
   file, its own altitude and its own coordinates. Stations write into one;
   feeds read out of one.</p>
{add}
{note}
<table class="stations">
  <tr><th>Place</th><th>File</th><th>Where it is</th>
      <th>Written by</th><th></th></tr>
  {NEWLINE.join(rows)}
</table>
'''


def _field(name: str, label: str, value: Any = "", hint: str = "",
           kind: str = "text") -> str:
    shown = "" if value is None else html.escape(str(value))
    note = f'<p class="hint">{hint}</p>' if hint else ""
    return f'''
  <p>
    <label for="a-{name}">{label}</label>
    <input id="a-{name}" name="{name}" type="{kind}" value="{shown}">
    {note}
  </p>'''


def new(admin: Any, error: str = "", form: dict | None = None) -> str:
    form = form or {}
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<h2>Add an archive</h2>
{problem}
<p>A second series, for a second place. It gets its own file, so nothing
   about the first one changes -- and its own altitude and coordinates,
   because sunrise and the pressure reduction are computed from them.</p>
<form method="post" action="./archives/add">
  {_field("name", "Name", form.get("name", ""),
          "Lower case, no spaces. It is what a station and a feed point at.")}
  {_field("label", "What to call it", form.get("label", ""),
          "Printed on the pages built from this series.")}
  {_field("file", "File", form.get("file", ""),
          "Left empty, it becomes data/&lt;name&gt;.sdb beside the others.")}
  {_field("latitude", "Latitude", form.get("latitude", ""))}
  {_field("longitude", "Longitude", form.get("longitude", ""))}
  {_field("altitude", "Altitude", form.get("altitude", ""),
          "Metres above sea level. The pressure reduction depends on it.")}
  <p><button type="submit">Add it</button></p>
</form>
'''

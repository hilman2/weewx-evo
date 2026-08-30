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


#: The four steps a reading takes, in order, and the page each one is on.
#: Named here rather than per page so the four cannot drift apart, and so
#: adding a fifth is one edit.
CHAIN = (("stations", "Consoles", "./stations"),
         ("archives", "Places", "./archives"),
         ("feeds", "Feeds", "./publishing"),
         ("exports", "Exports", "./publishing"))

#: What each of the four does, in one sentence. This is the only place in the
#: settings where the words feed and export are defined at all -- every page
#: used them as though the reader had met them before, and a reader who has
#: not cannot tell which of the two puts anything online.
CHAIN_SAID = ("A console sends readings. A place keeps them, for one spot. A "
              "feed builds pages out of one place. An export puts the pages "
              "online.")


def chain(admin: Any, step: str) -> str:
    """Where this page sits in the run of it, marked.

    On every page in the chain, not only the ones somebody thought needed it.
    The complaint this answers is "nicht nachvollziehbar was überhaupt für
    was ist": the settings knew the whole arrangement -- which console writes
    where, which feed reads what -- and said it nowhere, so each page read as
    a heap of fields belonging to nothing.

    `step` names the entry to mark, not a page: two of the four link to the
    same page, because feeds and exports live on one.
    """
    label = "Places"
    try:
        if not load(admin).several():
            # One place has nothing to tell apart, so the page is about the
            # spot the console stands at and the word never appears. It
            # arrives with the second one, which is when it means something.
            label = "Where you measure"
    except Exception:
        log.debug("could not count the places for the chain", exc_info=True)
    out = []
    for name, said, href in CHAIN:
        if name == "archives":
            said = label
        if name == step:
            out.append(f'<span class="on" aria-current="step">'
                       f"{html.escape(said)}</span>")
        else:
            out.append(f'<a href="{href}">{html.escape(said)}</a>')
    return ('<nav class="chain" aria-label="Where this sits">'
            + "".join(out) + "</nav>")


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


def _hex6(value: Any) -> str:
    """A colour as `#rrggbb`, or empty.

    `#abc` is legal CSS and legal in the file, and it is what a person types.
    Normalised on the way in so that "does another place already use this
    colour" is a string comparison -- `#abc` and `#aabbcc` are one colour and
    would otherwise pass that check and then be indistinguishable on the
    comparison chart, which is the one thing the check is for.
    """
    text = str(value or "").strip()
    if len(text) == 4 and text.startswith("#"):
        return "#" + "".join(c * 2 for c in text[1:]).lower()
    return text.lower() if text.startswith("#") else text


def from_form(form: dict, name: str = "") -> archive_defs.Archive:
    """An archive from what a form sent.

    Every field `Archive` has, because `configure` replaces the whole record:
    one left out here is one silently cleared on the next save. That is how
    `url` and `rain_year_start` came to be readable by this function and
    rendered by nothing -- and adding the colour, the code and the order
    without adding them here would have lost all three on the first edit.
    """
    return archive_defs.Archive(
        name=str(name or form.get("name") or "").strip().lower(),
        file=str(form.get("file") or "").strip(),
        label=str(form.get("label") or "").strip(),
        latitude=_number(form.get("latitude")),
        longitude=_number(form.get("longitude")),
        altitude=_number(form.get("altitude")),
        url=str(form.get("url") or "").strip(),
        rain_year_start=int(_number(form.get("rain_year_start")) or 1),
        color=_hex6(form.get("color")),
        code=str(form.get("code") or "").strip(),
        order=int(_number(form.get("order")) or 0),
    )


# -- what the operator does --------------------------------------------


def _slug(said: str) -> str:
    """A folder name out of what somebody called the place.

    Typed by hand until now, in a box directly under another box also
    labelled Name: one wanting "Nordfeld" and the other wanting `nordfeld`,
    with three lines of rules under it about directories and pages a skin
    writes. Nobody outside this program has a reason to care which characters
    are allowed, so it is worked out and shown rather than asked for.
    """
    out = []
    for char in said.strip().lower():
        if char.isalnum() and char.isascii():
            out.append(char)
        elif char in " -_":
            out.append("-")
        else:
            # The umlauts, because this is a German-speaking product's most
            # likely place name and "dachterrasse-sd" for "Süd" is not a name
            # anybody would recognise as theirs.
            out.append({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.get(
                char, ""))
    return "-".join(x for x in "".join(out).split("-") if x)[:64]


def create(admin: Any, form: dict) -> tuple[archive_defs.Archive | None, str]:
    """Add an archive. Returns (what was added, error)."""
    register = load(admin)
    wanted = from_form(form)
    if not wanted.name and wanted.label:
        wanted = _with(wanted, name=_slug(wanted.label))
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


#: Which setting each of a place's fields is, while the settings still *are*
#: the one place. Written back through `write_settings`, the same path the
#: core page uses, so `--explain` and the file's comments stay right.
AS_SETTINGS = {"label": "station.name", "latitude": "station.latitude",
               "longitude": "station.longitude", "altitude": "station.altitude",
               "url": "station.url",
               "rain_year_start": "station.rain_year_start",
               "file": "archive_db"}


def configure_only(admin: Any, form: dict) -> str:
    """Change the one place, while it is still the settings themselves.

    The page that used to be here was a disclosure whose whole content was a
    paragraph saying this is not where you change it -- and on every
    installation that ships, that was the only control on the page. The
    fields belong on the page whose heading names them.

    Writes `station.*` into the configuration file and **not**
    `archives.toml`: the moment that file exists, `overriding()` is true and
    the settings stop being read. That switch belongs to adding a second
    place and to nothing else, or a save here would quietly move where seven
    values are read from.
    """
    wanted = from_form(form, name=archive_defs.DEFAULT)
    values: dict[str, Any] = {}
    for field, dotted in AS_SETTINGS.items():
        got = getattr(wanted, field)
        # A number nobody typed is not zero. `None` clears the setting, and
        # clearing latitude is how a page loses sunrise; empty means "leave
        # it as it was", which is what an empty box has always meant here.
        if got is None or got == "":
            continue
        values[dotted] = got
    return admin.write_settings(values, note="the place")


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


def title_for(admin: Any) -> str:
    """What this page is called, which depends on how many places there are.

    Two names for one page, on purpose. One place has nothing to tell apart,
    so the page is about the spot the console stands at and never says the
    word "place" at all. The word arrives with the second one, because that
    is the first moment it means something.
    """
    try:
        return "Places" if load(admin).several() else "Where you measure"
    except Exception:
        log.debug("could not count the places", exc_info=True)
        return "Places"


def nav(admin: Any, active: str, opened: str = "") -> list[str]:
    register = load(admin)
    here = active in ("archives", "new-archive")
    current = " aria-current='page'" if here else ""
    if not register.several():
        # No sub-heading, and no count. A heading over a single link is a
        # third word for one destination; a count of 1 invites the reader to
        # go looking for the others, and there are none.
        return [f'<a href="./archives"{current}>Where you measure</a>']
    # A count of faults is a different shape from a count of things, not the
    # same shape in another colour: the two sat in the same slot, and the
    # one thing that can be wrong here is invisible everywhere else -- the
    # readings stay right and only the day boundaries move.
    trouble = register.concerns()
    mark = ""
    if trouble:
        mark = (f'<span class="alarm">{len(trouble)}'
                '<span class="sr"> need looking at</span></span>')
    out = [(f'<a href="./archives"{current}>Places{mark}'
            f'<span class="count">{len(register)}</span></a>')]
    # Named children, each in its own colour. Until now a second place
    # changed the shape of every published page and changed the sidebar by
    # one digit.
    for one in register.presented():
        on = (" aria-current='page'"
              if here and opened == one.name else "")
        out.append(
            f'<a class="sub" href="./archives?open={html.escape(one.name)}'
            f'#open-{html.escape(one.name)}"{on}>'
            f'<span class="swatch" style="--c: {html.escape(one.color)}"'
            ' aria-hidden="true"></span>'
            f"{html.escape(one.title)}</a>")
    return out



def _place(one: archive_defs.Archive) -> str:
    bits = []
    if one.latitude is not None and one.longitude is not None:
        bits.append(f"{one.latitude:.4f}, {one.longitude:.4f}")
    if one.altitude is not None:
        bits.append(f"{one.altitude:g} m")
    if not bits:
        return ""
    return html.escape(" &middot; ".join(bits)).replace("&amp;middot;",
                                                        "&middot;")


#: The one note that is a consequence rather than a fault, named here because
#: it is also the note most likely to be true of every row -- and a note true
#: of every row is printed once above the table instead. A warning standing
#: beside all thirty-four rows is what made the one row that mattered read
#: like the other thirty-three.
NO_COORDINATES = ("has no coordinates, so sunrise and the pressure reduction "
                  "fall back to the settings")


def adminstations_readable(name: str) -> str:
    """A console's name as the console page prints it.

    Imported through a function rather than at the top: `adminstations`
    reaches back here for the chain, and a circle at import time is a
    settings page that will not start.
    """
    try:
        from . import adminstations

        return adminstations._readable(name)
    except Exception:
        log.debug("could not read the console name", exc_info=True)
        return name


def _swatch(colour: str, said: str) -> str:
    return (f'<span class="swatch" style="--c: {html.escape(colour)}" '
            f'title="{html.escape(said)}"></span>')


def _field(prefix: str, name: str, label: str, value: Any = "",
           hint: str = "", kind: str = "text", extra: str = "") -> str:
    """One box of the archive form.

    `prefix` is in the id and nowhere else. N rows on one page means N of
    every id, and a duplicate id is a `<label for>` that focuses another
    place's box -- which on a page where every row has a field called
    "Latitude" is a mistake nobody would notice they were making.
    """
    shown = "" if value is None else html.escape(str(value))
    note = f'<span class="hint">{hint}</span>' if hint else ""
    return f'''
  <label for="a-{prefix}-{name}">{label}
    <input id="a-{prefix}-{name}" name="{name}" type="{kind}"
           value="{shown}"{extra}>
    {note}
  </label>'''


def _colour_field(prefix: str, chosen: str, would_be: str) -> str:
    """The palette, as a row of ticks, plus whatever the file already holds.

    The checked palette and not a free hex box. A free box is how somebody
    picks `#f0f0f0`, which is invisible on the light theme, or `#111`, which
    is invisible on the dark one -- and the place is then a line on a
    comparison chart nobody can see for half the day. The eight offered are
    mid-lightness on purpose and read on both grounds.

    "Whatever it would be given" is one of the answers rather than the
    absence of one: `presented()` hands out a colour by position, and a place
    that never chose one has to be able to go back to that. Its swatch shows
    the colour that *would* be drawn, because the word "none" says nothing
    about what the chart will look like.

    A colour in the file that is not one of the eight is offered as well, and
    checked, and said to come from the file. Rendering only the palette would
    quietly change a hand-picked colour the first time anybody saved anything
    else in the row.
    """
    out = ['<div class="palette">']
    entries = [("", would_be, "picked for it")]
    entries += [(one, one, one) for one in archive_defs.PLACE_COLORS]
    if chosen and chosen not in archive_defs.PLACE_COLORS:
        entries.append((chosen, chosen, "as written in the file"))
    for value, shown, said in entries:
        ticked = " checked" if chosen == value else ""
        out.append(
            f'<label title="{html.escape(said)}">'
            f'<input type="radio" name="color" value="{html.escape(value)}"'
            f'{ticked}>{_swatch(shown or "var(--dim)", said)}</label>')
    out.append("</div>")
    # A fieldset and a legend, never an outer `<label>` around the lot. A
    # label with no `for` takes the first labelable thing inside it as its
    # control -- here the "picked for it" radio -- so clicking the word
    # "Colour", or anywhere in the hint under the palette, threw away a
    # hand-picked colour with no submit and nothing said. Nested labels are
    # not legal either, and that is what let the shape grow.
    return (f'<fieldset class="colourfield" id="a-{prefix}-color">'
            "<legend>Colour</legend>" + "".join(out)
            + '<span class="hint">Its line on a comparison chart, the rule '
              "down its row on an overview, its chip in a sidebar. The same "
              "colour in every renderer, which is why it is kept here and "
              "not in a skin.</span></fieldset>")


def _form_fields(prefix: str, values: dict[str, Any], would_be: str) -> str:
    """Every field an archive has, in one place.

    One renderer for the add form and for each row's edit form, because the
    two disagreeing is exactly how `url` and `rain_year_start` came to be
    readable by `from_form` and rendered by neither of them. `configure`
    replaces the whole record from what was posted, so a field this does not
    draw is a field the next save clears.
    """
    return f'''
  {_field(prefix, "label", "What to call it", values.get("label", ""),
          "Printed on every page built from this series.")}
  {_field(prefix, "code", "Short code", values.get("code", ""),
          "Up to four letters or digits, for a chip beside a value and a "
          "legend where the label will not fit. Left empty, one is made "
          "from the label.", extra=' size="6" maxlength="4"')}
  {_colour_field(prefix, str(values.get("color") or ""), would_be)}
  {_field(prefix, "file", "File", values.get("file", ""),
          "A relative name counts against the configuration file, not "
          "against the directory the service happened to start in.")}
  {_field(prefix, "latitude", "Latitude", values.get("latitude", ""),
          "Decimal degrees. A comma is fine.")}
  {_field(prefix, "longitude", "Longitude", values.get("longitude", ""))}
  {_field(prefix, "altitude", "Altitude", values.get("altitude", ""),
          "Metres above sea level. The pressure reduction depends on it.")}
  {_field(prefix, "url", "Address its pages are served at",
          values.get("url", ""),
          "Printed by a skin that links to itself. Empty is fine.")}
  {_field(prefix, "rain_year_start", "Rain year starts in month",
          values.get("rain_year_start", "") or 1,
          "1 is January. Some regions count rain from October.",
          kind="number", extra=' min="1" max="12"')}
  {_field(prefix, "order", "Where it comes in a list",
          values.get("order", "") or 0,
          "Lowest first; places that agree keep the file's order. It does "
          "not move the default series, which everything naming nothing "
          "still gets.", kind="number")}'''


def _values_of(one: archive_defs.Archive) -> dict[str, Any]:
    """What the form shows for a place, as strings a box can hold."""
    values = dict(one.as_dict())
    for key in ("latitude", "longitude", "altitude"):
        values[key] = "" if values[key] is None else f"{values[key]:g}"
    return values


def _file_note(row: Any) -> str:
    """What the file column says under the path. Facts, not judgements.

    `row` cannot be None while the rows and the state come from the same
    register, which they do. Guarded rather than indexed anyway, and with
    nothing rather than a sentence: the cost of being wrong about that is
    this whole page answering 500, on the page somebody opens to find out
    what is wrong.
    """
    if row is None:
        return ""
    if not row.exists:
        return "not written yet"
    if row.unreachable:
        return f"cannot be read: {row.unreachable}"
    if not row.count:
        return "no records yet"
    bits = [f"{row.size:.1f} MB", f"{row.count:,} records"]
    if row.system:
        # A fact, not a problem -- and the fact behind the failure that has
        # already shipped once: 68.2 printed on a page that said Celsius,
        # with nothing anywhere saying which unit the file held.
        bits.append(row.system)
    return " &middot; ".join(bits)


def _feeds_adrift(admin: Any, known: set[str]) -> list[str]:
    """Feeds pointing at a place that is not on the list.

    Worth its own line because `Register.get()` never raises: an unknown name
    logs a warning nobody reads and falls back to the default, so the feed
    goes on publishing -- one place's readings under another place's heading,
    with every page rendering and nothing failing.
    """
    out = []
    for name, settings in sorted((admin.config().get("feeds") or {}).items()):
        if not isinstance(settings, dict):
            continue
        wanted = str(settings.get("archive") or "").strip()
        if wanted and wanted not in known:
            out.append(f"The feed {name} reads {wanted}, which is not one of "
                       "these. It is publishing the default series under "
                       "that name.")
    return out


def _sun_check(one: archive_defs.Archive) -> str:
    """Today's sunrise and sunset, from the numbers in the boxes above.

    The one check a person can actually run on a latitude. Nobody knows
    whether 48.4596 is right, and everybody knows whether the sun came up at
    a quarter past six -- so a transposed pair or a dropped minus sign shows
    up here and nowhere else on the page.
    """
    if one.latitude is None or one.longitude is None:
        return ""
    try:
        import time as clock

        from . import sun as sun_module

        # Keyed on local midnight, which is what `events` takes: a day here
        # is the sun's day, and anchoring it to `now` pairs one morning's
        # sunrise with the previous evening's sunset.
        today = sun_module.local_midnight(clock.time())
        found = sun_module.events(today, one.latitude, one.longitude)
        rise, sets = found.get("sunrise"), found.get("sunset")
        if rise is None or sets is None:
            # Inside the arctic circle in the right week there is no sunrise
            # to print, and that is an answer rather than a failure.
            return "the sun neither rises nor sets there today"
        return ("sunrise today "
                + clock.strftime("%H:%M", clock.localtime(rise))
                + ", sunset " + clock.strftime("%H:%M", clock.localtime(sets))
                + " -- worked out from the numbers above")
    except Exception:
        log.debug("could not work out sunrise for the place", exc_info=True)
        return ""


def _map_link(one: archive_defs.Archive) -> str:
    """Somewhere to look, because a pair of decimals is not checkable."""
    if one.latitude is None or one.longitude is None:
        return ""
    at = f"{one.latitude:.4f}/{one.longitude:.4f}"
    return (f'<a href="https://www.openstreetmap.org/?mlat={one.latitude:.4f}'
            f'&amp;mlon={one.longitude:.4f}#map=13/{at}" '
            'rel="noreferrer">See it on a map</a>')


def _what_reads_it(admin: Any) -> str:
    """Who sends into this place, and what is built out of it.

    The settings knew all of it and said it nowhere, so a page of coordinates
    gave no hint of what depends on them -- which is a page people edit
    nervously or not at all.
    """
    rows = []
    try:
        stations = station_defs.load(
            Path(admin.path).parent / station_defs.FILENAME)
        # Every console, not the ones naming this place: with one place
        # nothing is filtered and every packet reaches it, which is the rule
        # that keeps an installation that never heard of places working.
        sending = sorted(one.name for one in stations)
        if sending:
            rows.append(("Consoles sending", ", ".join(
                f'<a href="./stations">{html.escape(name)}</a>'
                for name in sending)))
        else:
            rows.append(("Consoles sending",
                         ('<span class="note">none yet. </span>'
                          '<a href="./stations">Set one up</a>')))
    except Exception:
        log.debug("could not list the consoles", exc_info=True)

    try:
        config = admin.config()
        feeds = sorted((config.get("feeds") or {}).keys())
        if feeds:
            rows.append(("Pages built from it", ", ".join(
                f'<a href="./feed:{html.escape(name)}">{html.escape(name)}</a>'
                for name in feeds)))
        casts = sorted((config.get("forecast") or {}).keys())
        if casts:
            rows.append(("Forecast for it", ", ".join(
                f'<a href="./forecast:{html.escape(name)}">'
                f'{html.escape(name)}</a>' for name in casts)))
    except Exception:
        log.debug("could not list what reads the place", exc_info=True)

    if not rows:
        return ""
    body = "".join(f"<dt>{name}</dt><dd>{said}</dd>" for name, said in rows)
    return f'<h3>What reads this</h3>\n<dl class="facts">{body}</dl>'


def _the_one_place(admin: Any, register: archive_defs.Register,
                   error: str, form: dict) -> str:
    """The page while the settings still *are* the one place.

    What stood here was a disclosure whose entire content was a paragraph
    saying this is not where you change it, pointing at a group inside a long
    settings page under a different name. On every installation that ships,
    that was the only control on the page: the page named after the spot
    could say everything about it except what it was.

    The fields are here now and write `station.*` through `configure_only`.
    Which file they land in is the one thing that must not move -- see the
    note there.
    """
    one = register.get(archive_defs.DEFAULT)
    values = _values_of(one)
    if form.get("latitude") is not None:
        # A refused save coming back. Retyping a form because one field was
        # wrong is how people give up on a settings page.
        values.update({k: v for k, v in form.items() if k in values})
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""

    row = None
    try:
        from . import adminhome

        for found in adminhome.archives_state(admin, register):
            if found.archive.name == one.name:
                row = found
    except Exception:
        log.debug("could not read the state of the place", exc_info=True)

    where = " &middot; ".join(x for x in (_map_link(one), _sun_check(one)) if x)
    kept = _file_note(row)

    save = ""
    if not admin.read_only:
        save = ('<div class="actions"><button type="submit">Save</button>'
                '<span class="hint">Written to the configuration file. The '
                "recorder picks the position up when it next restarts."
                "</span></div>")

    add = ""
    if not admin.read_only:
        add = '''
<section class="group">
  <h3>A second place</h3>
  <p class="lede">A second spot with readings of its own: the allotment, a
     field, a roof across town. It gets its own position and its own height,
     so its sunrise and its barometer are worked out for where it actually
     is. Two consoles in <em>one</em> garden do not need this -- they both
     feed this one already.</p>
  <p class="note">Your published pages then move into a folder per place.
     You are shown the new addresses before anything is written.</p>
  <div class="actions">
    <a class="button quiet" href="./new-archive">Add a second place</a>
  </div>
</section>'''

    check = f'<p class="check">{where}</p>' if where else ""
    note = f'<p class="note">{kept}</p>' if kept else ""
    return f'''
<h2>Where you measure</h2>
{chain(admin, "archives")}
<p class="lede">{CHAIN_SAID}</p>
{problem}
<form method="post" action="./archives/{html.escape(one.name)}/set">
<section class="group">
  <h3>{html.escape(one.title)}</h3>
  <p class="lede">One spot, and every page is about it. Its position is what
     sunrise, sunset and the night bands on a chart are worked out from. Its
     height is what turns the pressure inside the console into the barometer
     reading everyone compares.</p>
  {_field("one", "label", "Name", values.get("label", ""),
          "The heading on every page built from these readings.")}
  {_field("one", "latitude", "Latitude", values.get("latitude", ""),
          "Decimal degrees, negative south of the equator. A comma is fine.")}
  {_field("one", "longitude", "Longitude", values.get("longitude", ""),
          "Decimal degrees, negative west of Greenwich.")}
  {_field("one", "altitude", "Height above sea level",
          values.get("altitude", ""),
          "In metres, and off a map rather than off the console -- a console "
          "is usually set to whatever made its display read right. A hundred "
          "metres out moves the barometer by about 12 hPa.")}
  {check}
  {_field("one", "rain_year_start", "Rain year starts in month",
          values.get("rain_year_start", "") or 1,
          "1 is January, which is what nearly everywhere counts from. "
          "October where a wet year is what people mean.",
          kind="number", extra=' min="1" max="12"')}
  {_field("one", "url", "Address its pages are served at",
          values.get("url", ""),
          "A skin prints it in its footer, and a weather service asks for it "
          "when you register. Empty is fine.")}
  <details class="more">
    <summary>Where the readings are kept</summary>
    {_field("one", "file", "Readings file", values.get("file", ""),
            "A plain name sits beside the configuration file, not beside "
            "wherever the service happened to start.")}
    {note}
  </details>
  {save}
</section>
</form>
{_what_reads_it(admin)}
{add}
'''


def overview(admin: Any, message: str = "", error: str = "",
             form: dict | None = None) -> str:
    form = form or {}
    register = load(admin)
    if not register.several():
        # A different page, not a one-row version of this one. With one place
        # there is nothing to compare, nothing to tell apart, and no folder
        # names -- so the table, the colours, the codes and the order are not
        # drawn at all, and the fields somebody actually came for are.
        return _the_one_place(admin, register, error, form)
    stations = station_defs.load(
        Path(admin.path).parent / station_defs.FILENAME)
    # Imported here rather than at the top: `adminhome` imports this module,
    # and two modules importing each other at import time is a circle.
    from . import adminhome

    state = {row.archive.name: row
             for row in adminhome.archives_state(admin, register)}
    presented = {one.name: one for one in register.presented()}
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    # The banner above the page says it. Printing it a second time in the
    # body was two "Saved." one under the other, which reads as two things
    # having happened.
    said = ""
    opened = str(form.get("_open") or "")

    add = ""
    if not admin.read_only:
        add = ('<div class="actions">'
               '<a class="button" href="./new-archive">Add a place</a>'
               "</div>")
    trouble = register.concerns()
    # Which colours two places share. Warned about rather than refused: two
    # of them may be published on pages nobody ever sees together, and
    # refusing would be this page deciding that on their behalf.
    shared: dict[str, list[str]] = {}
    for one in register.presented():
        shared.setdefault(one.color.lower(), []).append(one.title)

    ordered = register.ordered()
    gathered = []
    #: note -> how many rows carry it, so one true of every row can be lifted
    #: above the table instead of standing beside all of them.
    counted: dict[str, int] = {}
    for one in ordered:
        notes = [] if _place(one) else [NO_COORDINATES]
        for text in notes:
            counted[text] = counted.get(text, 0) + 1
        gathered.append((one, notes))
    everywhere = [text for text, count in counted.items()
                  if count == len(ordered) and len(ordered) > 1]

    rows = []
    for one, notes in gathered:
        shows = presented.get(one.name, one)
        row = state.get(one.name)
        writing = sorted(s.name for s in stations if s.archive == one.name)
        # Through the console page's own reader: a console adopted from a
        # stranger is named after the identity its hardware sent, and a
        # twenty-digit string as the only thing in a cell reads as a fault.
        who = ", ".join(html.escape(adminstations_readable(n))
                        for n in writing)
        if not writing:
            if one.name == archive_defs.DEFAULT:
                # Never for the default place. With one archive nothing is
                # filtered and every packet reaches it, which is the rule
                # that keeps an installation that never heard of stations
                # working.
                who = '<span class="note">everything not spoken for</span>'
            else:
                who = ('<span class="warn">Nothing writes into it, so its '
                       "pages render and stay empty.</span> "
                       '<a href="./stations">Point a console at it</a>')
        aside = "".join(f'<br><span class="note">{html.escape(text)}</span>'
                        for text in notes if text not in everywhere)
        concern = trouble.get(one.name, "")
        if concern:
            aside += f'<br><span class="warn">{html.escape(concern)}</span>'
        fold = _fold(admin, one, register, opened, form)
        # Only where a site actually publishes into a directory of that
        # name. A feed writes `into / place` when it shows more than one
        # place and into the root otherwise, so on every installation
        # shipping today this said a URL that answers 404.
        # The folder its pages go in, said as a folder. The sentence it
        # replaces -- "published at /x/ by a site that shows more than one
        # place" -- carried the condition and left the reader to work out
        # whether it applied to them.
        where = f" &middot; folder /{html.escape(one.name)}/"
        rows.append(f'''
    <tr>
      <td>{_swatch(shows.color, shows.color)}<span
          class="chip">{html.escape(shows.code)}</span>
          <strong>{html.escape(one.title)}</strong>
          <br><span class="note">{html.escape(one.name)}{where}</span></td>
      <td><code>{html.escape(one.file)}</code>
          <br><span class="note">{_file_note(row)}</span></td>
      <td>{_place(one)}{aside}</td>
      <td>{who}</td>
    </tr>''' + (f'''
    <tr class="foldrow"><td colspan="4">{fold}</td></tr>''' if fold else ""))

    note = ('<p class="note">Each place has its own position and its own '
            "height, so its sunrise and its barometer are worked out for "
            "where it actually is. Your pages are published one folder per "
            "place; the folder is the short name under each heading.</p>")

    # Said once, above the table. A fact about the installation is not a fact
    # about a place, and standing beside every row it is furniture -- which
    # is what made the one row that mattered read like the others.
    above = "".join(f'<p class="note">Every place here {html.escape(text)}.'
                    "</p>" for text in everywhere)
    above += "".join(f'<p class="warn">{html.escape(text)}</p>'
                     for text in _feeds_adrift(admin, set(register.names())))
    above += _colour_clash(register)

    return f'''
<h2>Places</h2>
{chain(admin, "archives")}
<p class="lede">{CHAIN_SAID}</p>
{problem}{said}
{add}
{note}{above}
<table class="stations places">
  <tr><th>Place</th><th>Readings kept in</th><th>Position</th>
      <th>Consoles sending</th></tr>
  {NEWLINE.join(rows)}
</table>
'''


def _colour_clash(register: archive_defs.Register) -> str:
    """Which two places are drawn the same, said once, with the fix as a link.

    Per row it was two warnings that are one warning, each written from the
    other place's point of view -- and three places sharing a colour produced
    six sentences saying one thing. Warned about rather than refused: two of
    them may be published on pages nobody ever sees together, and refusing
    would be this page deciding that on their behalf.
    """
    shared: dict[str, list[Any]] = {}
    for one in register.presented():
        shared.setdefault(one.color.lower(), []).append(one)
    out = []
    for group in shared.values():
        if len(group) < 2:
            continue
        names = ", ".join(html.escape(one.title) for one in group)
        last = group[-1]
        out.append(
            f'<p class="warn">{names} are drawn in the same colour. On a '
            "chart with both on it the two lines cannot be told apart. "
            f'<a href="./archives?open={html.escape(last.name)}'
            f'#open-{html.escape(last.name)}">Give '
            f'{html.escape(last.title)} another colour</a>.</p>')
    return "".join(out)


def _fold(admin: Any, one: archive_defs.Archive,
          register: archive_defs.Register, opened: str, form: dict) -> str:
    """The change-this-place form, behind a triangle.

    Sibling forms, never nested. HTML has no nested forms: the browser drops
    the inner one and keeps its `</form>`, so the outer one closes early and
    Save ends up belonging to no form at all -- which is what happened on
    every export, feed, upload and forecast page, with every tag present and
    every one closed in the output.

    Closed unless this is the row somebody was sent to. Everything behind the
    triangle is a rare decision and everything in the row is a frequent fact;
    a refused save reopens the row it came from, or the correction would be
    behind a triangle on a page that says something is wrong.

    No form at all while the settings are still the one series. `Register`
    seeds itself with them before it changes anything, so a Save here would
    write `archives.toml` -- and from that moment `overriding()` is true,
    `station.name`, the coordinates and the altitude are read out of the new
    file, and the System page marks all seven as moved. The note two rows
    above says that happens when a *second* series is added, and it is the
    only switch there should be: a button labelled "Change" must not be a
    second one nobody was told about.
    """
    if admin.read_only:
        return ""
    if not register.overriding():
        # The page is named from the schemas, the way the navigation does
        # it. A link typed here would keep working right up to the day the
        # core schema is renamed, and then send somebody to the overview
        # with no hint that it meant to go anywhere else.
        system = next((s.name for s in getattr(admin, "schemas", None) or ()
                       if getattr(s, "kind", "") == "core"), "core")
        return f"""
  <details id="open-{html.escape(one.name)}">
    <summary>Change {html.escape(one.title)}</summary>
    <p class="note">This series <em>is</em> the settings. Its name,
       coordinates, altitude and file are on the
       <a href="./{html.escape(system)}#g-station">System</a> page, and that
       is where they are read from until there is a second series. Its
       colour, its short code and its order have nothing to tell apart
       yet.</p>
  </details>"""
    here = opened == one.name
    values = _values_of(one)
    # What was typed, where a refused save is coming back -- and only for
    # this row, because a form belongs to the row it was posted from.
    if here and form.get("file") is not None:
        values.update({k: v for k, v in form.items() if k in values})
    would_be = next((p.color for p in register.presented()
                     if p.name == one.name), "")
    removable = ""
    if one.name != archive_defs.DEFAULT:
        removable = f'''
    <form method="post" action="./archives/{html.escape(one.name)}/remove">
      <span class="hint">Takes it off the list. The file stays where it is:
         what is in it cannot be rebuilt from anywhere else.</span>
      <button class="quiet" type="submit">Remove</button>
    </form>'''
    return f'''
  <details id="open-{html.escape(one.name)}"{" open" if here else ""}>
    <summary>Change {html.escape(one.title)}</summary>
    <form method="post" action="./archives/{html.escape(one.name)}/set"
          class="props">
      <span class="hint">The name stays
         <code>{html.escape(one.name)}</code>: it is what a station and a
         feed point at, and the directory a site showing more than one place
         publishes it in. Renaming it
         would leave both naming something gone, and a station naming a place
         that is not there falls back to the default -- which mixes one
         place's readings into another's series. Add one under the name you
         want and move the stations across.</span>
      {_form_fields(one.name, values, would_be)}
      <button type="submit">Save</button>
    </form>
    {removable}
  </details>'''


def new(admin: Any, error: str = "", form: dict | None = None) -> str:
    form = form or {}
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    register = load(admin)
    # What the next place would be given if it chose nothing. `presented()`
    # hands colours out by position in the file, so this is the one after the
    # last of them.
    colours = archive_defs.PLACE_COLORS
    would_be = colours[len(register.all()) % len(colours)]
    first = ""
    try:
        first = register.get(archive_defs.DEFAULT).title
    except Exception:
        log.debug("could not name the first place", exc_info=True)
    return f'''
{problem}
<p class="lede">A second spot with readings of its own. It gets its own
   position and its own height, so its sunrise and its barometer are worked
   out for where it actually is -- and its own file, so nothing about
   {html.escape(first) if first else "the first one"} changes.</p>
<section class="group">
  <h3>What this does to your pages</h3>
  <p class="lede">Until now everything published was about one spot and sat
     at the root of the site. From the moment there are two, a feed showing
     both writes an overview at the root and puts each place in a folder
     named after it. A feed you leave pointed at one place goes on
     publishing exactly as it does today.</p>
</section>
<form method="post" action="./archives/add" class="props">
  {_field("new", "label", "What to call it", form.get("label", ""),
          "The heading on every page about it: the allotment, Nordfeld, the "
          "roof. The folder name is made from this.")}
  {_field("new", "latitude", "Latitude", form.get("latitude", ""),
          "Decimal degrees, negative south of the equator. A comma is fine.")}
  {_field("new", "longitude", "Longitude", form.get("longitude", ""))}
  {_field("new", "altitude", "Height above sea level",
          form.get("altitude", ""),
          "In metres, and off a map rather than off the console. It is what "
          "turns the pressure inside the box into a barometer reading.")}
  {_colour_field("new", str(form.get("color") or ""), would_be)}
  <details class="more">
    <summary>Name, file and the rest</summary>
    {_field("new", "name", "Folder name", form.get("name", ""),
            "Lower case, no spaces. It is what a console and a feed point "
            "at, and the folder its pages are published in. Left empty it "
            "is made from the name above.")}
    {_field("new", "file", "Readings file", form.get("file", ""),
            "Left empty it becomes data/&lt;folder name&gt;.sdb beside the "
            "others.")}
    {_field("new", "code", "Short code", form.get("code", ""),
            "Up to four letters, for a legend where the full name will not "
            "fit. Left empty, one is made from the name.",
            extra=' size="6" maxlength="4"')}
    {_field("new", "url", "Address its pages are served at",
            form.get("url", ""), "Empty is fine.")}
    {_field("new", "rain_year_start", "Rain year starts in month",
            form.get("rain_year_start", "") or 1,
            "1 is January.", kind="number", extra=' min="1" max="12"')}
    {_field("new", "order", "Where it comes in a list",
            form.get("order", "") or 0,
            "Lowest first. It does not move the first place, which "
            "everything naming nothing still gets.", kind="number")}
  </details>
  <div class="actions"><button type="submit">Add it</button></div>
</form>
'''

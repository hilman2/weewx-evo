"""The archives page: one row per place this installation keeps readings for.

Hand-written for the same reason the stations page is. The form generator
takes one named value at a time, and an archive is a set of them -- a file,
a label and three numbers -- repeated per row.

This is the only page that writes place settings. An installation with no
file yet gets one row written from the settings; one and several archives
then use the same storage and the same edit path.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import archives as archive_defs
from . import config as config_file
from . import language as language_defs

log = logging.getLogger(__name__)

NEWLINE = "\n"

#: Place-owned fields exposed to settings search. The labels are the same
#: nouns used by the editor; persistence remains defined by ``Archive``.
SEARCH_FIELDS = (
    ("label", "Name"),
    ("latitude", "Latitude"),
    ("longitude", "Longitude"),
    ("altitude", "Altitude"),
    ("rain_year_start", "Rain year starts in month"),
    ("senders", "Senders"),
    ("fields", "Field mappings"),
    ("url", "Published address"),
    ("file", "Archive file"),
    ("code", "Short code"),
    ("color", "Colour"),
    ("order", "List position"),
)


#: The four steps a reading takes, in order, and the page each one is on.
#: Named here rather than per page so the four cannot drift apart, and so
#: adding a fifth is one edit.
CHAIN = (("stations", "Senders", "./senders"),
         ("archives", "Places", "./places"),
         ("feeds", "Feeds", "./publishing"),
         ("exports", "Exports", "./publishing"))

#: What each of the four does, in one sentence. This is the only place in the
#: settings where the words feed and export are defined at all -- every page
#: used them as though the reader had met them before, and a reader who has
#: not cannot tell which of the two puts anything online.
CHAIN_SAID = ("Senders write live readings. Places select and archive them. "
              "Publishing reads from places.")


def chain(admin: Any, step: str) -> str:
    """The stable data path, with the current step marked."""
    say = admin.say
    out = []
    for name, said, href in CHAIN:
        if name == "archives":
            href = "./places"
        word = html.escape(say(said))
        if name == step:
            out.append(f'<span class="on" aria-current="step">{word}</span>')
        else:
            out.append(f'<a href="{href}">{word}</a>')
    where = html.escape(say("Where this sits"))
    return f'<nav class="chain" aria-label="{where}">' + "".join(out) + "</nav>"


def path_for(admin: Any) -> Path:
    """Beside the configuration file, like stations.toml and plots.toml."""
    return Path(admin.path).parent / archive_defs.FILENAME


@dataclass(frozen=True, slots=True)
class SenderChoice:
    """A live sender ID and its presentation-only label."""

    sender: str
    label: str
    driver: str
    identity: str
    #: Named the same as `db.live.SenderIdentity.first_seen`, because
    #: `Archive.primary_sender` reads it off whichever of the two it is given.
    #: 0 for a sender the journal has never heard.
    first_seen: float = 0.0

    @property
    def name(self) -> str:
        """Compatibility label for read-only sender diagnostics."""
        return self.label


def sender_choices(admin: Any, archive: archive_defs.Archive | None = None
                   ) -> list[SenderChoice]:
    """Senders observed in live, plus configured ones no longer retained.

    Nothing here reads ``stations.toml``. The label is metadata written by
    the listener and never becomes the selection value.
    """
    from .db.live import LiveStore, sender_parts

    found: dict[str, SenderChoice] = {}
    where = config_file.resolved_path(
        admin.config(), "live_db", Path(admin.path).parent, "data/live.sdb")
    if where.exists():
        try:
            with LiveStore(where) as live:
                for one in live.senders():
                    label = str(one.label or one.identity or one.driver)
                    found[one.sender] = SenderChoice(
                        one.sender, label, one.driver, one.identity,
                        one.first_seen)
        except Exception:
            log.debug("could not list live senders", exc_info=True)

    configured = (() if archive is None else
                  (archive.members if archive.senders is None
                   else archive.senders))
    for sender in configured:
        if sender in found:
            continue
        try:
            driver, identity = sender_parts(sender)
        except ValueError:
            # A canonical archive cannot contain this, but keeping the page
            # renderable is more useful than turning a hand edit into a 500.
            log.warning("configured sender ID is invalid: %r", sender)
            continue
        found[sender] = SenderChoice(
            sender, identity or driver, driver, identity)
    return sorted(found.values(), key=lambda one: (
        one.label.casefold(), one.driver.casefold(), one.identity.casefold()))


def settings_of(admin: Any) -> Any:
    """The saved settings, for writing out the first place.

    Not the running `Settings`: this page reads the file it writes, and the
    running one belongs to whichever process is listening. A present
    `archives.toml` never consults this view.
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
    # With no file yet, the settings are the one place and are written out.
    # This page owns the editable configuration directory, which is why it
    # may hand the saved settings over and the Archiver may not.
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


_UNSET = object()


def _members_from_form(
        form: dict[str, Any], current_senders: tuple[str, ...] | None,
        current: dict[str, Any], *, new: bool = False,
        current_primary: str = ""
        ) -> tuple[tuple[str, ...] | None,
                   dict[str, archive_defs.MemberPolicy], str]:
    """One form's sender selection, policies and primary as one atomic answer."""
    if "_members" not in form:
        if new:
            return (), {}, ""
        return current_senders, dict(current), current_primary

    from .db.live import sender_parts

    prefix = "sender:"
    posted = []
    for key in form:
        if not str(key).startswith(prefix):
            continue
        sender = str(key)[len(prefix):]
        sender_parts(sender)
        if sender not in posted:
            posted.append(sender)
    broad = "all-senders" in form
    selected = None if broad else tuple(posted)

    # Only selected senders have stored policy in explicit mode. Broad mode
    # may hold overrides for every row the UI knows about; an unseen sender
    # is still selected and gets the ordinary defaults.
    made: dict[str, archive_defs.MemberPolicy] = {}
    for sender in posted:
        marker = f"member-policy:{sender}"
        indoor_key = f"member-indoor:{sender}"
        if marker not in form and indoor_key not in form:
            # A sender checked while JavaScript is unavailable has disabled
            # policy controls. Keep what was stored for it, or start it on the
            # ordinary defaults; a second save may refine it.
            made[sender] = current.get(sender, archive_defs.MemberPolicy())
            continue
        made[sender] = archive_defs.MemberPolicy(indoor=indoor_key in form)

    primary = str(form.get("member-primary") or "").strip()
    if primary:
        sender_parts(primary)
    # A primary that is no longer selected is not an error and not kept: it
    # is what unticking the primary row means. Written empty, the place falls
    # back to its earliest remaining sender, which is the same rule that
    # answers it for a place nobody has opened yet.
    if primary and selected is not None and primary not in selected:
        primary = ""
    return selected, made, primary


def from_form(form: dict, name: str = "", senders: Any = _UNSET,
              members: dict[str, Any] | None = None,
              primary: str = "") -> archive_defs.Archive:
    """An archive from what a form sent.

    Every field `Archive` has, because `configure` replaces the whole record:
    one left out here is one silently cleared on the next save. That is how
    `url` and `rain_year_start` came to be readable by this function and
    rendered by nothing -- and adding the colour, the code and the order
    without adding them here would have lost all three on the first edit.
    """
    selected, policies, chosen = _members_from_form(
        form, () if senders is _UNSET else senders, members or {},
        new=senders is _UNSET, current_primary=primary)
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
        stations=selected,
        members=policies,
        primary=chosen,
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
    """Add a place. Returns (what was added, error)."""
    register = load(admin)
    try:
        wanted = from_form(form)
    except ValueError as exc:
        return None, str(exc)
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


def configure(admin: Any, name: str, form: dict) -> str:
    """Change one archive in place."""
    register = load(admin)
    current = next((one for one in register.all() if one.name == name), None)
    if current is None:
        return f"There is no archive called {name!r}."
    try:
        wanted = from_form(form, name=name, senders=current.senders,
                           members=current.members, primary=current.primary)
    except ValueError as exc:
        return str(exc)
    values = wanted.as_dict()
    for field_name, _read_as in archive_defs.FIELDS:
        if field_name not in form:
            values[field_name] = getattr(current, field_name)
    wanted = archive_defs.Archive(name=name, **values)
    problem = register.why_not(wanted, replacing=name)
    if problem:
        return problem
    register.replace(name, wanted)
    return store(admin, register)


def remove(admin: Any, name: str) -> str:
    """Take one off the list. The file stays where it is."""
    register = load(admin)
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
    """One name at every installation size."""
    return admin.say("Places")


def nav(admin: Any, active: str, opened: str = "") -> list[str]:
    register = load(admin)
    here = active in ("archives", "places", "new-archive", "new-place")
    current = " aria-current='page'" if here else ""
    trouble = register.concerns()
    mark = ""
    if trouble:
        said = html.escape(admin.say("need looking at"))
        mark = (f'<span class="alarm">{len(trouble)}'
                f'<span class="sr"> {said}</span></span>')
    return [(f'<a href="./places"{current}>{html.escape(admin.say("Places"))}'
             f'{mark}<span class="count">{len(register)}</span></a>')]



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
                  "are unavailable")


def _swatch(colour: str, said: str) -> str:
    # A hand-edited file has not passed the form validator. Keep its value
    # out of an inline declaration unless it is exactly the colour syntax the
    # Place model accepts; HTML escaping does not make arbitrary CSS safe.
    safe = (colour if re.fullmatch(
        r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", colour) else "")
    return (f'<span class="swatch" style="--c: {safe}" '
            f'title="{html.escape(said)}"></span>')


def _field(prefix: str, name: str, label: str, value: Any = "",
           hint: str = "", kind: str = "text", extra: str = "",
           say: Any = None) -> str:
    """One box of the archive form.

    `prefix` is in the id and nowhere else. N rows on one page means N of
    every id, and a duplicate id is a `<label for>` that focuses another
    place's box -- which on a page where every row has a field called
    "Latitude" is a mistake nobody would notice they were making.
    """
    say = say or str
    shown = "" if value is None else html.escape(str(value))
    hint = html.escape(say(hint)) if hint else ""
    note = f'<span class="hint">{hint}</span>' if hint else ""
    label = html.escape(say(label))
    return f'''
  <label for="a-{prefix}-{name}">{label}
    <input id="a-{prefix}-{name}" name="{name}" type="{kind}"
           value="{shown}"{extra}>
    {note}
  </label>'''


def _member_fields(admin: Any, archive: archive_defs.Archive) -> str:
    """Live sender selection, the primary among them, and per-place policy.

    The primary is a radio group across the rows rather than a per-row
    choice. It is the only shape in which "two of them" cannot be typed:
    exactly one is the browser's own behaviour, with no script, no rejected
    save and no warning to write. A select per row let anybody set every
    sender to primary, and the archiver then accumulated all of them into the
    same columns -- which for rain is a sum.
    """
    say = admin.say
    choices = sender_choices(admin, archive)
    primary = archive.primary_sender(choices)
    # A radio with one option is a question with one answer. The single
    # console every installation starts as is not asked it, the same way a
    # single-place site is not offered the place switches.
    alone = len([one for one in choices if archive.selects(one.sender)]) < 2

    rows = []
    for one in choices:
        sender = one.sender
        policy = archive.policy_for(sender)
        safe = html.escape(sender, quote=True)
        is_primary = sender == primary
        checked = archive.selects(sender)
        detail = one.driver + (f" · {one.identity}" if one.identity else "")
        role = html.escape(say("Primary readings"))
        if alone and is_primary:
            only = html.escape(say(
                "The only sender here, so this place takes its series "
                "from it."))
            role_field = (f'<p class="place-member-role">{role}'
                          f'<span class="hint">{only}</span></p>')
        else:
            role_field = f'''<label class="tick place-member-role">
          <input name="member-primary" type="radio" value="{safe}"
                 data-place-member-primary{" checked" if is_primary else ""}>
          {role}</label>'''
        rows.append(f'''
    <article class="place-member{' is-selected' if checked else ''}"
             data-place-member>
      <label class="place-member-pick tick">
        <input name="sender:{safe}" type="checkbox" value="1"
               data-place-member-select{" checked" if checked else ""}>
        <span><strong>{html.escape(one.label)}</strong>
          <small>{html.escape(detail)}</small>
          <code>{safe}</code></span>
      </label>
      <fieldset class="place-member-policy" data-place-member-policy
                {"" if checked else "disabled hidden"}>
        <legend class="sr">{html.escape(admin.language.fill(
          "Settings for {sender}", sender=one.label))}</legend>
        <input type="hidden" name="member-policy:{safe}" value="1">
        {role_field}
        <label class="tick"><input name="member-indoor:{safe}"
                   type="checkbox" value="1"
                   {"checked" if policy.indoor else ""}>
          {html.escape(say("Indoor readings"))}</label>
        <p class="place-member-extra-note" data-place-member-extra-note
           {"hidden" if is_primary else ""}>{html.escape(say(
           "Writes only what it has been given a column under Fields. "
           "Nothing is guessed for it: a second sender may be a full weather "
           "station, a soil probe or one thermometer, and the protocol does "
           "not say which."))}</p>
      </fieldset>
    </article>''')
    body = (NEWLINE.join(rows) if rows else
            f'<p class="note">{html.escape(say("No senders received yet."))}'
            "</p>")
    return f'''
  <input type="hidden" name="_members" value="1">
  <section class="place-section place-members"
           id="place-members-{html.escape(archive.name)}">
    <header><h4>{html.escape(say("Senders"))}</h4></header>
    <label class="place-broad tick">
      <input name="all-senders" type="checkbox" value="1"
             {"checked" if archive.senders is None else ""}>
      {html.escape(say("Include new senders automatically"))}
    </label>
    <div class="place-member-list">{body}</div>
  </section>
  <script>
  (() => {{
    const section = document.getElementById(
      'place-members-{archive.name}');
    if (!section) return;
    // Which row is primary is the radio group's own state, so nothing here
    // decides it. All this does is keep each row's note in step with it.
    const syncNotes = () => {{
      section.querySelectorAll('[data-place-member]').forEach(row => {{
        const pick = row.querySelector('[data-place-member-primary]');
        const note = row.querySelector('[data-place-member-extra-note]');
        if (note) note.hidden = !pick || pick.checked;
      }});
    }};
    const sync = row => {{
      const selected = row.querySelector('[data-place-member-select]').checked;
      const policy = row.querySelector('[data-place-member-policy]');
      row.classList.toggle('is-selected', selected);
      policy.hidden = !selected;
      // Disabling the fieldset takes its radio out of the group, so a row
      // unticked while it was primary leaves the group with nothing chosen.
      // That is the intended reading of unticking it: the place falls back
      // to its earliest remaining sender.
      policy.disabled = !selected;
      syncNotes();
    }};
    section.querySelectorAll('[data-place-member]').forEach(row => {{
      const pick = row.querySelector('[data-place-member-select]');
      pick.addEventListener('change', () => {{
        const broad = section.querySelector('[name="all-senders"]');
        if (!pick.checked && broad) broad.checked = false;
        sync(row);
      }});
      const primary = row.querySelector('[data-place-member-primary]');
      if (primary) primary.addEventListener('change', syncNotes);
      sync(row);
    }});
    const broad = section.querySelector('[name="all-senders"]');
    if (broad) broad.addEventListener('change', () => {{
      if (!broad.checked) return;
      section.querySelectorAll('[data-place-member]').forEach(row => {{
        row.querySelector('[data-place-member-select]').checked = true;
        sync(row);
      }});
    }});
  }})();
  </script>'''


def _colour_field(prefix: str, chosen: str, would_be: str,
                  say: Any = None) -> str:
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
    say = say or str
    out = ['<div class="palette">']
    entries = [("", would_be, say("picked for it"))]
    entries += [(one, one, one) for one in archive_defs.PLACE_COLORS]
    if chosen and chosen not in archive_defs.PLACE_COLORS:
        entries.append((chosen, chosen, say("as written in the file")))
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
            f'<legend>{html.escape(say("Colour"))}</legend>'
            + "".join(out) + "</fieldset>")


def _form_fields(prefix: str, values: dict[str, Any], would_be: str,
                 members: str = "", say: Any = None) -> str:
    """Every field an archive has, in one place.

    One renderer for the add form and for each row's edit form, because the
    two disagreeing is exactly how `url` and `rain_year_start` came to be
    readable by `from_form` and rendered by neither of them. `configure`
    replaces the whole record from what was posted, so a field this does not
    draw is a field the next save clears.
    """
    return f'''
  {_field(prefix, "label", "What to call it", values.get("label", ""),
          "Printed on every page built from this series.", say=say)}
  {members}
  {_field(prefix, "code", "Short code", values.get("code", ""),
          "Up to four letters or digits, for a chip beside a value and a "
          "legend where the label will not fit. Left empty, one is made "
          "from the label.", extra=' size="6" maxlength="4"', say=say)}
  {_colour_field(prefix, str(values.get("color") or ""), would_be, say)}
  {_field(prefix, "file", "File", values.get("file", ""),
          "A relative name counts against the configuration file, not "
          "against the directory the service happened to start in.", say=say)}
  {_field(prefix, "latitude", "Latitude", values.get("latitude", ""),
          "Decimal degrees. A comma is fine.", say=say)}
  {_field(prefix, "longitude", "Longitude", values.get("longitude", ""),
          say=say)}
  {_field(prefix, "altitude", "Altitude", values.get("altitude", ""),
          "Metres above sea level. The pressure reduction depends on it.",
          say=say)}
  {_field(prefix, "url", "Address its pages are served at",
          values.get("url", ""),
          "Printed by a skin that links to itself. Empty is fine.", say=say)}
  {_field(prefix, "rain_year_start", "Rain year starts in month",
          values.get("rain_year_start", "") or 1,
          "1 is January. Some regions count rain from October.",
          kind="number", extra=' min="1" max="12"', say=say)}
  {_field(prefix, "order", "Where it comes in a list",
          values.get("order", "") or 0,
          "Lowest first; places that agree keep the file's order.",
          kind="number", say=say)}'''


def _values_of(one: archive_defs.Archive) -> dict[str, Any]:
    """What the form shows for a place, as strings a box can hold."""
    values = dict(one.as_dict())
    for key in ("latitude", "longitude", "altitude"):
        values[key] = "" if values[key] is None else f"{values[key]:g}"
    return values


def _file_note(row: Any, lang: Any = None) -> str:
    """What the file column says under the path. Facts, not judgements.

    `row` cannot be None while the rows and the state come from the same
    register, which they do. Guarded rather than indexed anyway, and with
    nothing rather than a sentence: the cost of being wrong about that is
    this whole page answering 500, on the page somebody opens to find out
    what is wrong.
    """
    lang = lang if lang is not None else language_defs.get("en")
    if row is None:
        return ""
    if not row.exists:
        return lang.say("not written yet")
    if row.unreachable:
        # SQLite files are input, not markup. In particular, a malformed
        # ``usUnits`` value can appear verbatim in the ValueError kept here.
        return lang.fill("cannot be read: {why}",
                         why=html.escape(str(row.unreachable)))
    if not row.count:
        return lang.say("no records yet")
    bits = [f"{row.size:.1f} MB",
            lang.fill("{n} records", n=f"{row.count:,}")]
    if row.system:
        # A fact, not a problem -- and the fact behind the failure that has
        # already shipped once: 68.2 printed on a page that said Celsius,
        # with nothing anywhere saying which unit the file held.
        bits.append(html.escape(str(row.system)))
    return " &middot; ".join(bits)


def _feeds_adrift(admin: Any, known: set[str]) -> list[str]:
    """Feeds pointing at a place that is not on the list.

    Worth its own line because `Register.get()` now refuses an unknown name:
    the feed will not run until its selection is corrected.
    """
    out = []
    for name, settings in sorted((admin.config().get("feeds") or {}).items()):
        if not isinstance(settings, dict):
            continue
        wanted = str(settings.get("archive") or "").strip()
        if wanted and wanted not in known:
            out.append(admin.language.fill(
                "The feed {feed} reads {place}, which is not one of these. "
                "It will not run.", feed=name, place=wanted))
    return out


def _sun_check(one: archive_defs.Archive, lang: Any = None) -> str:
    """Today's sunrise and sunset, from the numbers in the boxes above.

    The one check a person can actually run on a latitude. Nobody knows
    whether 48.4596 is right, and everybody knows whether the sun came up at
    a quarter past six -- so a transposed pair or a dropped minus sign shows
    up here and nowhere else on the page.
    """
    lang = lang if lang is not None else language_defs.get("en")
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
            return lang.say("No sunrise or sunset today")
        return lang.fill(
            "Sunrise {rise} · sunset {set}",
            rise=clock.strftime("%H:%M", clock.localtime(rise)),
            set=clock.strftime("%H:%M", clock.localtime(sets)))
    except Exception:
        log.debug("could not work out sunrise for the place", exc_info=True)
        return ""


def _map_link(one: archive_defs.Archive, say: Any = None) -> str:
    """Somewhere to look, because a pair of decimals is not checkable."""
    say = say or str
    if one.latitude is None or one.longitude is None:
        return ""
    at = f"{one.latitude:.4f}/{one.longitude:.4f}"
    return (f'<a href="https://www.openstreetmap.org/?mlat={one.latitude:.4f}'
            f'&amp;mlon={one.longitude:.4f}#map=13/{at}" '
            f'rel="noreferrer">{html.escape(say("Open map"))}</a>')


def _what_reads_it(admin: Any, archive: archive_defs.Archive) -> str:
    """Explicitly configured consumers of one place."""
    say = admin.say
    rows: list[tuple[str, str]] = []
    try:
        config = admin.config()
        default = load(admin).default_name()
        for section, label, route in (
                ("feeds", "Feeds", "feed"),
                ("uploads", "Weather services", "upload"),
                ("forecast", "Forecasts", "forecast")):
            found = []
            for name, settings in sorted((config.get(section) or {}).items()):
                if not isinstance(settings, dict):
                    continue
                selected = str(settings.get("archive") or default).strip()
                if selected == archive.name:
                    found.append(
                        f'<a href="./{route}:{html.escape(str(name))}">'
                        f'{html.escape(str(name))}</a>')
            if found:
                rows.append((label, ", ".join(found)))
    except Exception:
        log.debug("could not list what reads the place", exc_info=True)

    manage = (f'<p><a href="./publishing">'
              f'{html.escape(say("Open publishing"))}</a></p>')
    if not rows:
        return (f'<p class="note">{html.escape(say("No explicit outputs."))}'
                "</p>" + manage)
    body = "".join(f"<dt>{html.escape(say(name))}</dt><dd>{said}</dd>"
                   for name, said in rows)
    return f'<dl class="facts">{body}</dl>{manage}'


def _colour_clash(register: archive_defs.Register, lang: Any = None) -> str:
    """Which two places are drawn the same, said once, with the fix as a link.

    Per row it was two warnings that are one warning, each written from the
    other place's point of view -- and three places sharing a colour produced
    six sentences saying one thing. Warned about rather than refused: two of
    them may be published on pages nobody ever sees together, and refusing
    would be this page deciding that on their behalf.
    """
    lang = lang if lang is not None else language_defs.get("en")
    shared: dict[str, list[Any]] = {}
    for one in register.presented():
        shared.setdefault(one.color.lower(), []).append(one)
    out = []
    for group in shared.values():
        if len(group) < 2:
            continue
        names = ", ".join(html.escape(one.title) for one in group)
        last = group[-1]
        where = (f"./places?open={html.escape(last.name)}"
                 f"#place-detail-{html.escape(last.name)}")
        change = lang.fill("Change {place}", place=html.escape(last.title))
        said = lang.fill("{places} use the same colour.", places=names)
        out.append(f'<p class="warn">{said} '
                   f'<a href="{where}">{change}</a>.</p>')
    return "".join(out)


def _field_mappings(admin: Any, archive: archive_defs.Archive) -> str:
    """Mapping editors for every sender selected by this Place."""
    say = admin.say
    try:
        from . import adminfields, adminstations, placement

        plans = placement.load(placement.path_for(Path(admin.path).parent))
    except Exception:
        log.debug("could not list field mappings", exc_info=True)
        return (f'<p class="note">'
                f'{html.escape(say("Field mappings unavailable."))}</p>')

    selected = [one for one in sender_choices(admin, archive)
                if archive.selects(one.sender)]
    if not selected:
        return (f'<p class="note">'
                f'{html.escape(say("Select a sender first."))}</p>')

    out = []
    for sender in selected:
        encoded = quote(sender.sender, safe="")
        anchor = quote(f"sender-{sender.sender}", safe="")
        diagnostic = (f'<a href="./senders?open={encoded}#{anchor}">'
                      f'{html.escape(say("View sender data"))}</a>')
        rendered = []
        seen: set[str] = set()
        found = adminstations.what_it_sends(admin, sender)
        if found and found.get("mapping") and found.get("values"):
            dialect = str(found.get("dialect") or "")
            series = found.get("series")
            if series is None:
                series = adminstations.recent_series(
                    admin, sender, set(found.get("values") or {}))
            rendered.append(adminfields.table_for_place(
                admin, sender, archive.name, found.get("values") or {},
                found.get("catalog"), dialect, series))
            seen.add(dialect)

        # An offline sender remains editable from its saved raw names. A
        # vocabulary is kept separate because the same raw name can mean a
        # different archive field in another protocol.
        dialects: dict[str, set[str]] = {}
        for scope in plans.takes:
            if (scope.archive == archive.name
                    and scope.station == sender.sender and scope.fields):
                dialects.setdefault(scope.dialect, set()).update(scope.fields)
        for dialect, raw_names in sorted(dialects.items()):
            if dialect in seen:
                continue
            rendered.append(adminfields.table_for_place(
                admin, sender, archive.name,
                dict.fromkeys(sorted(raw_names)), {}, dialect, {}))

        if not rendered:
            status = say("Mapping metadata unavailable."
                         if found and not found.get("mapping")
                         else "No readings yet.")
            rendered.append(
                f'<div class="place-member"><strong>{html.escape(sender.label)}'
                f'</strong><p class="note">{html.escape(status)}</p>'
                f"{diagnostic}</div>")
        else:
            rendered.append(f'<p class="place-field-link">{diagnostic}</p>')
        out.extend(rendered)
    return NEWLINE.join(out)


def _place_detail(admin: Any, register: archive_defs.Register,
                  archive: archive_defs.Archive, state: Any,
                  error: str, form: dict[str, Any]) -> str:
    """The one stable detail editor used for every place count."""
    say = admin.say
    lang = admin.language
    values = _values_of(archive)
    if str(form.get("_open") or "") == archive.name:
        values.update({key: value for key, value in form.items()
                       if key in values})
    shown = next((one for one in register.presented()
                  if one.name == archive.name), archive)
    position = " &middot; ".join(
        part for part in (_map_link(archive, say), _sun_check(archive, lang))
        if part)
    file_note = _file_note(state, lang)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""

    save = ""
    remove = ""
    if not admin.read_only:
        save = f'''
      <div class="place-save actions">
        <button type="submit">{html.escape(say("Save changes"))}</button>
      </div>'''
        if archive.name != archive_defs.DEFAULT:
            remove = f'''
      <form method="post" action="./places/{html.escape(archive.name)}/remove"
            class="place-remove">
        <button class="quiet" type="submit">
          {html.escape(say("Remove place"))}</button>
      </form>'''

    where = f'<p class="check">{position}</p>' if position else ""
    kept = f'<p class="note">{file_note}</p>' if file_note else ""
    return f'''
  <article class="place-detail" id="place-detail-{html.escape(archive.name)}">
    <header class="place-detail-head">
      <div>{_swatch(shown.color, shown.color)}
        <span class="chip">{html.escape(shown.code)}</span>
        <h3>{html.escape(archive.title)}</h3>
        <code>{html.escape(archive.name)}</code>
      </div>
    </header>
    <nav class="place-tabs" aria-label="{html.escape(say("Place settings"))}">
      <a class="place-tab" href="#place-general-{html.escape(archive.name)}"
         >{html.escape(say("General"))}</a>
      <a class="place-tab" href="#place-members-{html.escape(archive.name)}"
         >{html.escape(say("Senders"))}</a>
      <a class="place-tab" href="#place-fields-{html.escape(archive.name)}"
         >{html.escape(say("Fields"))}</a>
      <a class="place-tab" href="#place-outputs-{html.escape(archive.name)}"
         >{html.escape(say("Outputs"))}</a>
    </nav>
    {problem}
    <form method="post" action="./places/{html.escape(archive.name)}/set"
          class="props place-form">
      <section class="place-section" id="place-general-{html.escape(archive.name)}">
        <header><h4>{html.escape(say("General"))}</h4></header>
        {_field(archive.name, "label", "Name", values.get("label", ""),
                say=say)}
        <div class="place-coordinates">
          {_field(archive.name, "latitude", "Latitude",
                  values.get("latitude", ""), say=say)}
          {_field(archive.name, "longitude", "Longitude",
                  values.get("longitude", ""), say=say)}
          {_field(archive.name, "altitude", "Altitude in metres",
                  values.get("altitude", ""), say=say)}
        </div>
        {where}
        {_field(archive.name, "rain_year_start", "Rain year starts in month",
                values.get("rain_year_start", "") or 1,
                kind="number", extra=' min="1" max="12"', say=say)}
        <details class="more">
          <summary>{html.escape(say("Advanced"))}</summary>
          {_field(archive.name, "code", "Short code", values.get("code", ""),
                  extra=' size="6" maxlength="4"', say=say)}
          {_colour_field(archive.name, str(values.get("color") or ""),
                         shown.color, say)}
          {_field(archive.name, "file", "Archive file", values.get("file", ""),
                  say=say)}
          {kept}
          {_field(archive.name, "url", "Published address",
                  values.get("url", ""), say=say)}
          {_field(archive.name, "order", "List position",
                  values.get("order", "") or 0, kind="number", say=say)}
        </details>
      </section>
      {_member_fields(admin, archive)}
      {save}
    </form>
      <section class="place-section" id="place-fields-{html.escape(archive.name)}">
        <header><h4>{html.escape(say("Field mappings"))}</h4></header>
        {_field_mappings(admin, archive)}
      </section>
      <section class="place-section" id="place-outputs-{html.escape(archive.name)}">
        <header><h4>{html.escape(say("Outputs"))}</h4></header>
        {_what_reads_it(admin, archive)}
      </section>
    {remove}
  </article>'''


def _interval_note(admin: Any) -> str:
    """Say what one record covers here, and where that is changed.

    It is an installation-wide setting and lives with the other core options,
    under a link named after the program. So it is one of the few settings
    somebody comes to *this* page looking for and does not find: a person
    thinking about their archive thinks about how long a record is.

    It is not per place, and the reason is one line in `db/live.py`:
    `mark_pending` works out one interval boundary and enters it for every
    archive. A boundary per place would mean the listener reading each place's
    interval to decide where a packet's interval ends -- the same "work out
    which archive this belongs to at the front door" that the comment there
    refuses, for the same reason: getting it wrong loses readings with no
    trace.
    """
    from .options import parse_duration

    try:
        # A duration, not a number: the file says `interval = "5m"` as often
        # as it says 300.
        raw = config_file.get(admin.config(), "interval")
        seconds = int(parse_duration(str(raw))) if raw else 300
    except Exception:
        # An unreadable value is the settings page's own problem to show. A
        # note about it must not take the Places page down with it.
        return ""
    lang = admin.language
    shown = (lang.fill("{n} min", n=seconds // 60) if seconds % 60 == 0
             else lang.fill("{n} seconds", n=seconds))
    # `f-interval`, not `interval`: the form builder prefixes every control's
    # id. Named without it the link still opens the page and simply does not
    # jump, which is the sort of thing nobody reports.
    # The value goes in as plain text and the link comes after the full stop.
    # A tag in the middle of a sentence splits it into runs, and a run
    # between two of them is one no translator was ever offered.
    said = html.escape(lang.fill(
        "One archive record covers {span}, for every place.", span=shown))
    change = html.escape(lang.say("Change it"))
    return (f'<p class="note">{said} '
            f'<a href="./core#f-interval">{change}</a>.</p>')


def overview(admin: Any, message: str = "", error: str = "",
             form: dict | None = None) -> str:
    """A master/detail editor with the same shape for one or many places."""
    form = form or {}
    register = load(admin)
    ordered = register.ordered()
    opened = str(form.get("_open") or "")
    selected = next((one for one in ordered if one.name == opened), ordered[0])

    state: dict[str, Any] = {}
    try:
        from . import adminhome

        state = {row.archive.name: row
                 for row in adminhome.archives_state(admin, register)}
    except Exception:
        log.debug("could not read place state", exc_info=True)

    say = admin.say
    lang = admin.language
    shown = {one.name: one for one in register.presented()}
    concerns = register.concerns()
    choices = []
    for one in ordered:
        display = shown.get(one.name, one)
        # Two keys, not a stem and an "s": a language that does not build a
        # plural that way has nowhere to put its own.
        senders = (say("All senders") if one.senders is None else
                   lang.fill("{n} sender", n=1) if len(one.senders) == 1 else
                   lang.fill("{n} senders", n=len(one.senders)))
        warning = ""
        if one.senders == ():
            warning = f'<span class="warn">{html.escape(say("No sender"))}</span>'
        elif concerns.get(one.name):
            warning = (f'<span class="warn">'
                       f'{html.escape(say("Needs attention"))}</span>')
        file_state = _file_note(state.get(one.name), lang)
        active = one.name == selected.name
        choices.append(f'''
      <a class="place-choice{' is-active' if active else ''}"
         href="./places?open={quote(one.name)}#place-detail-{html.escape(one.name)}"
         {"aria-current='page'" if active else ""}>
        <span>{_swatch(display.color, display.color)}
          <strong>{html.escape(one.title)}</strong></span>
        <small>{html.escape(senders)}</small>
        <small>{file_state}</small>{warning}
      </a>''')

    add = ""
    if not admin.read_only:
        add = (f'<a class="button" href="./new-place">'
               f'{html.escape(say("Add place"))}</a>')
    notices = "".join(
        f'<p class="warn">{html.escape(text)}</p>'
        for text in _feeds_adrift(admin, set(register.names())))
    notices += _colour_clash(register, lang)
    places = html.escape(say("Places"))
    return f'''
<h2>{places}</h2>
{_interval_note(admin)}
{notices}
<div class="place-shell">
  <aside class="place-list" aria-label="{places}">
    <header><h3>{places}</h3>{add}</header>
    <nav>{NEWLINE.join(choices)}</nav>
  </aside>
  {_place_detail(admin, register, selected, state.get(selected.name),
                 error, form)}
</div>'''


def new(admin: Any, error: str = "", form: dict | None = None) -> str:
    form = form or {}
    say = admin.say
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    register = load(admin)
    # What the next place would be given if it chose nothing. `presented()`
    # hands colours out by position in the file, so this is the one after the
    # last of them.
    colours = archive_defs.PLACE_COLORS
    would_be = colours[len(register.all()) % len(colours)]
    members = _member_fields(
        admin, archive_defs.Archive("", "", stations=(), members={}))
    return f'''
{problem}
<form method="post" action="./places/add"
      class="props place-detail place-form">
  <section class="place-section" id="place-general-new">
    <header><h3>{html.escape(say("General"))}</h3></header>
    {_field("new", "label", "Name", form.get("label", ""), say=say)}
    <div class="place-coordinates">
      {_field("new", "latitude", "Latitude", form.get("latitude", ""),
              say=say)}
      {_field("new", "longitude", "Longitude", form.get("longitude", ""),
              say=say)}
      {_field("new", "altitude", "Altitude in metres",
              form.get("altitude", ""), say=say)}
    </div>
    {_field("new", "rain_year_start", "Rain year starts in month",
            form.get("rain_year_start", "") or 1,
            kind="number", extra=' min="1" max="12"', say=say)}
  </section>
  {members}
  <section class="place-section">
    <details class="more">
      <summary>{html.escape(say("Advanced"))}</summary>
      {_field("new", "name", "Internal name", form.get("name", ""),
              "Generated from the name when empty.", say=say)}
      {_field("new", "file", "Archive file", form.get("file", ""),
              "Generated from the name when empty.", say=say)}
      {_field("new", "code", "Short code", form.get("code", ""),
            extra=' size="6" maxlength="4"', say=say)}
      {_colour_field("new", str(form.get("color") or ""), would_be, say)}
      {_field("new", "url", "Published address", form.get("url", ""), say=say)}
      {_field("new", "order", "List position", form.get("order", "") or 0,
              kind="number", say=say)}
    </details>
  </section>
  <div class="place-save actions">
    <a class="button quiet" href="./places">{html.escape(say("Cancel"))}</a>
    <button type="submit">{html.escape(say("Add place"))}</button>
  </div>
</form>
'''

"""Admin UI for the senders known to the live journal.

A sender is the stable ``driver + hardware identity`` data stream.  This
page may give that stream a presentation name and show whether it is alive.
Places alone decide whether and how they use it; no archive, role, channel or
indoor policy is written here.
"""

from __future__ import annotations

import html
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import language as language_defs
from . import placement
from . import stations as station_defs

log = logging.getLogger(__name__)

NEWLINE = "\n"

def setups() -> dict[str, Any]:
    """What each installed driver says about pointing hardware at it.

    Asked of the drivers rather than listed here, and that is the whole of
    the fix: this page carried a hand-written table of three, so the four
    protocols that were not on it could not be set up from the page at all.
    It had also drifted from what the protocols say -- Ambient was turned
    away with "has no server field" while `protocols/ambient.py` lists five,
    Server IP and Port among them.

    Ordered so that hardware which can be told where to upload comes first:
    that is the list somebody is looking at, and the rest is the harder
    arrangement rather than the usual one.
    """
    from .ingest import drivers as driver_defs

    found = {}
    for name in driver_defs.names():
        said = driver_defs.setup_of(driver_defs.DEFAULT.get(name))
        if said is not None and (said.label or said.hardware):
            found[name] = said
    return dict(sorted(found.items(), key=lambda one: not one[1].tellable))


def tellable() -> dict[str, Any]:
    """The ones whose hardware has a field to type an address into."""
    return {name: one for name, one in setups().items() if one.tellable}


def learns_its_identity(driver: str) -> bool:
    """Whether this hardware carries a name of its own we have to read.

    Where it does not, the identity is handed out here and typed in, which
    is the better arrangement: one somebody chooses can be chosen twice.
    """
    said = setups().get(driver)
    return bool(said is not None and said.identity)

#: What a station carries until its console has uploaded once.
#: A placeholder rather than an empty string: the identity has to
#: stay unique, or two consoles being set up at once would collide
#: on "" and the second would be refused for no visible reason.
AWAITING = "awaiting:"


# -- what the admin object does -------------------------------------------

def path_for(admin: Any) -> Path:
    """Where stations.toml lives: beside the configuration, like plots.toml."""
    return station_defs.path_for(Path(admin.path).parent)


def load(admin: Any) -> station_defs.Register:
    return station_defs.load(path_for(admin))


def store(admin: Any, register: station_defs.Register, note: str = "") -> str:
    """Write them. Returns an error, or empty if it worked."""
    if admin.read_only:
        return "This settings page was started read-only."
    try:
        station_defs.save(path_for(admin), register, note)
    except Exception as exc:
        log.exception("could not write the stations")
        return f"Could not write {path_for(admin)}: {exc}"
    return ""


def live_db(admin: Any) -> Path | None:
    """Where the live database is, as this process can reach it.

    Three ways it can be written and all three turn up. The environment wins,
    because that is the order everything else uses and a container sets
    `WEEWX_EVO_LIVE`. A path in the file may be relative, and relative to the
    file rather than to whatever directory the settings page was started in --
    which is what made this page say a station had never been heard from while
    the database beside it held four hundred of its packets.
    """
    from . import config as config_file

    found = config_file.resolved_path(admin.config(), "live_db",
                                      Path(admin.path).parent, "data/live.sdb")
    return found if found.exists() else None


def sightings_for(admin: Any):
    """The strangers, out of the live database.

    Read-only here and opened per request. The listener holds its own copy and
    writes it; this only ever shows what is there, so two readers cannot
    disagree about anything that matters.
    """
    from .db.live import LiveStore
    from .ingest.sightings import Sightings

    where = live_db(admin)
    if where is None:
        return Sightings(None)
    try:
        return Sightings(LiveStore(where))
    except Exception:
        log.debug("could not read the sightings", exc_info=True)
        return Sightings(None)


def _close_sightings(seen: Any) -> None:
    """Flush a page's short-lived view and give its database handle back."""
    try:
        seen.close()
    finally:
        store = getattr(seen, "store", None)
        close = getattr(store, "close", None)
        if callable(close):
            close()


def last_seen(admin: Any, names: list[str]) -> dict[str, int]:
    """When each station last had a packet stored.

    Asked of the live table rather than kept in the file. The table already
    knows, and a second answer would only be one that can be wrong.
    """
    if not names:
        return {}
    where = live_db(admin)
    if where is None:
        return {}
    register = load(admin)
    try:
        import sqlite3
        db = sqlite3.connect(f"file:{where}?mode=ro", uri=True)
        try:
            rows = db.execute(
                "SELECT driver, identity, MAX(dateTime) FROM packet"
                " GROUP BY driver, identity").fetchall()
            # Keyed back to names here rather than in the query: the
            # table records the pair a console uploads with, and the
            # name it answers to is a lookup that changes.
            found = {}
            for driver, identity, when in rows:
                name = placement.name_for(register, driver, identity)
                if name in names:
                    found[name] = int(when or 0)
            return found
        finally:
            db.close()
    except Exception:
        log.debug("could not read when stations were last seen", exc_info=True)
        return {}


# -- changing things ------------------------------------------------------

def _readable(name: str) -> str:
    """A console's name, or a plain word for it where the name is a MAC.

    Adopting a stranger takes the name from the identity the hardware sent,
    so a console that was never renamed is listed as
    `00000000000000000000`. That is not wrong -- it is what the console
    calls itself -- but as the first column of the first table it reads as a
    fault in the software, and it is the same string as the identity two
    columns along.
    """
    stripped = name.replace(":", "").replace("-", "")
    if len(stripped) >= 12 and all(c in "0123456789abcdefABCDEF"
                                   for c in stripped):
        return f"unnamed sender ({name[-4:]})"
    return name


def _sender_problem(problem: str) -> str:
    """Translate legacy domain wording at the UI boundary."""
    return (str(problem)
            .replace("a station", "a sender")
            .replace("station called", "sender called")
            .replace("Station ", "Sender ")
            .replace("console", "sender"))


def adopt(admin: Any, driver: str, identity: str, name: str) -> str:
    """Take a stranger into the register. Returns an error, or empty."""
    register = load(admin)
    station = station_defs.Station(
        name=(name or "").strip().lower(), driver=driver, identity=identity,
        learnt=True)
    problem = register.why_not(station)
    if problem:
        return _sender_problem(problem)
    register.stations.append(station)
    error = store(admin, register, f"{station.name} adopted")
    if error:
        return error
    # Out of the sightings, because it is not a stranger any more. Leaving it
    # there would show the same console in two lists at once.
    seen = sightings_for(admin)
    try:
        seen.forget(driver, identity)
    finally:
        _close_sightings(seen)
    return ""


def announce(admin: Any, name: str, driver: str) -> tuple:
    """Create a station. Returns (station, error).

    Two shapes, and which one depends on where the identity comes from.
    Where we hand it out it goes straight onto the station and the operator
    copies it onto the console. Where the hardware carries its own -- an
    Ecowitt PASSKEY -- the station is created waiting for it, and `learn()`
    fills it in from the first upload that has nowhere else to go.
    """
    register = load(admin)
    waiting = learns_its_identity(driver)
    identity = "" if waiting else register.identity_for(driver)
    station = station_defs.Station(
        name=(name or "").strip().lower(), driver=driver,
        identity=identity or f"{AWAITING}{name}".strip(),
        learnt=waiting)
    problem = register.why_not(station)
    if problem:
        return None, _sender_problem(problem)
    register.stations.append(station)
    error = store(admin, register, f"{station.name} announced")
    return (None, error) if error else (station, "")


def learn(admin: Any, name: str) -> tuple:
    """Give a waiting station the identity off the wire. Returns (found, error).

    The wizard's other half, for hardware that will not be told what to call
    itself. The operator has just set the console to upload here and is
    standing in front of it, which is the one moment adoption is a decision
    somebody is making rather than something happening to them.

    The newest sighting on that driver wins. With one console being set up
    there is one, and asking somebody to pick from a list of one is a worse
    page than showing what was found.
    """
    register = load(admin)
    station = register.by_name(name)
    if station is None:
        return None, f"There is no sender called {name!r}."
    if not station.identity.startswith(AWAITING):
        return station, ""          # already learnt; nothing to do

    seen = sightings_for(admin)
    try:
        waiting = [one for one in seen.waiting()
                   if one.driver == station.driver and one.identity]
    finally:
        _close_sightings(seen)
    if not waiting:
        return None, ""             # nothing has arrived yet, which is normal

    from dataclasses import replace as _replace

    found = waiting[0]
    filled = _replace(station, identity=found.identity, learnt=True)
    problem = register.why_not(filled, replacing=station.name)
    if problem:
        return None, _sender_problem(problem)
    register.stations[register.stations.index(station)] = filled
    error = store(admin, register, f"{station.name} learnt its identity")
    if error:
        return None, error
    seen = sightings_for(admin)
    try:
        seen.forget(found.driver, found.identity)
    finally:
        _close_sightings(seen)
    return filled, ""


def _clock_field(form: dict, name: str, current: float | None) -> float | None:
    """One clock tolerance off the form, or None to follow the settings.

    Empty means "whatever the settings say", which is what nearly every
    console wants and what keeps a later change to that figure reaching all
    of them. A field absent from the form is left alone rather than cleared:
    a partial POST must not silently drop what somebody set last week.
    """
    if name not in form:
        return current
    typed = str(form.get(name) or "").strip()
    if not typed:
        return None
    from .options import Invalid, parse_duration

    try:
        return float(parse_duration(typed, name))
    except (Invalid, ValueError) as exc:
        raise ValueError(f"{typed!r} is not a length of time: {exc}") from exc


def configure(admin: Any, name: str, form: dict) -> str:
    """Change settings intrinsic to one console. Returns an error, or empty."""
    from dataclasses import replace as _replace

    register = load(admin)
    station = register.by_name(name)
    if station is None:
        return f"There is no sender called {name!r}."

    try:
        behind = _clock_field(form, "max_behind", station.max_behind)
        ahead = _clock_field(form, "max_ahead", station.max_ahead)
    except ValueError as exc:
        return str(exc)

    changed = _replace(station, max_behind=behind, max_ahead=ahead)
    if changed == station:
        return ""
    register.stations[register.stations.index(station)] = changed
    return store(admin, register, f"{name} changed")


def remove(admin: Any, name: str) -> str:
    register = load(admin)
    if register.remove(name) is None:
        return f"There is no sender called {name!r}."
    return store(admin, register, f"{name} removed")


def ignore(admin: Any, driver: str, identity: str, on: bool = True) -> str:
    seen = sightings_for(admin)
    try:
        if not seen.ignore(driver, identity, on):
            return "That sender is not on the list any more."
        return ""
    finally:
        _close_sightings(seen)


# -- the page -------------------------------------------------------------

def nav(admin: Any, active: str) -> list[str]:
    register = load(admin)
    out: list[str] = []
    here = active in ("senders", "stations", "new-sender", "new-station")
    current = " aria-current='page'" if here else ""
    out.append(f'<a href="./senders"{current}>'
               f'{html.escape(admin.say("Senders"))}'
               f'<span class="count">{len(register)}</span></a>')
    if not len(register):
        out.append(f'<p class="navempty">{html.escape(admin.say("None"))}</p>')
    return out


def _ago(when: int, lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    if not when:
        return lang.say("never")
    gap = max(0, int(time.time()) - when)
    if gap < 90:
        return lang.fill("{n} s ago", n=gap)
    if gap < 5400:
        return lang.fill("{n} min ago", n=gap // 60)
    if gap < 172800:
        return lang.fill("{n} h ago", n=gap // 3600)
    return lang.fill("{n} days ago", n=gap // 86400)


def _sender_id(one: Any) -> str:
    """The immutable selection key for one named sender."""
    from .db.live import sender_id

    return sender_id(one.driver, one.identity)


def _sender_anchor(sender: str) -> str:
    """The literal DOM id used by Place -> Sender links."""
    return f"sender-{sender}"


def _place_href(name: str) -> str:
    """Open the sender membership section of one Place."""
    encoded = quote(str(name), safe="")
    return f"./places?open={encoded}#place-members-{encoded}"


def _places(admin: Any) -> list[Any]:
    """Place configuration for presentation; an unreadable file is empty."""
    from . import adminarchives

    try:
        return list(adminarchives.load(admin).all())
    except Exception:
        log.debug("could not read the places for the sender page", exc_info=True)
        return []


def _used_by(places: list[Any], sender: str) -> list[Any]:
    return [one for one in places if one.selects(sender)]


def _place_cell(places: list[Any], sender: str, say: Any = None) -> str:
    """Places using this sender, and the one configuration action."""
    say = say or str
    used = _used_by(places, sender)
    links = ", ".join(
        f'<a href="{html.escape(_place_href(one.name), quote=True)}">'
        f'{html.escape(one.title)}</a>' for one in used)
    if links:
        action = html.escape(_place_href(used[0].name), quote=True)
        return (f'{links}<br><a class="note" href="{action}">'
                f'{html.escape(say("Change assignment"))}</a>')
    if places:
        action = html.escape(_place_href(places[0].name), quote=True)
        return (f'<span class="warn">{html.escape(say("Not assigned"))}</span>'
                f'<br><a href="{action}">'
                f'{html.escape(say("Assign to a Place"))}</a>')
    return f'<a href="./places">{html.escape(say("Create a Place"))}</a>'


def _technical_identity(driver: str, identity: str, sender: str,
                        say: Any = None) -> str:
    """Driver identity first; canonical key folded underneath it."""
    say = say or str
    return f'''
      <span>{html.escape(driver)}</span>
      <code>{html.escape(identity or say("(none)"))}</code>
      <details class="technical-id">
        <summary>{html.escape(say("Technical ID"))}</summary>
        <code>{html.escape(sender)}</code>
      </details>'''


def _sender_status(when: int, waiting: bool = False, lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    if when:
        fresh = max(0, int(time.time()) - when) < 10 * 60
        state = (f'<span class="ok">{html.escape(lang.say("Receiving"))}</span>'
                 if fresh else
                 f'<span class="warn">{html.escape(lang.say("Stale"))}</span>')
        return (f'{state}<br><span class="note">'
                f"{html.escape(_ago(when, lang))}</span>")
    if waiting:
        return (f'<span class="warn">'
                f'{html.escape(lang.say("Waiting for first data"))}</span>')
    return f'<span class="note">{html.escape(lang.say("No data"))}</span>'


def overview(admin: Any, message: str = "", error: str = "") -> str:
    """Named, newly discovered and ignored live senders."""
    from . import adminarchives

    say = admin.say
    lang = admin.language
    chain = adminarchives.chain(admin, "stations")
    register = load(admin)
    seen = sightings_for(admin)
    when = last_seen(admin, [one.name for one in register])
    places = _places(admin)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""

    rows = []
    for one in sorted(register, key=lambda s: s.name):
        waiting = one.identity.startswith(AWAITING)
        sender = _sender_id(one)
        diagnostic = _what_it_sends_html(admin, one)
        if waiting:
            identity = (f'<a href="./new-sender?learn={quote(one.name, safe="")}">'
                        f'{html.escape(say("Connection settings"))}</a>')
        else:
            identity = _technical_identity(one.driver, one.identity, sender,
                                           say)
        anchor = html.escape(_sender_anchor(sender), quote=True)
        detail = (f'''
    <tr class="sendsrow" data-sender-detail="{html.escape(sender, quote=True)}">
      <td colspan="5">{diagnostic}</td>
    </tr>''' if diagnostic else "")
        rows.append(f'''
    <tr id="{anchor}" data-sender="{html.escape(sender, quote=True)}">
      <td><strong>{html.escape(_readable(one.name))}</strong>
          {f'<br><span class="note">{html.escape(one.note)}</span>' if one.note else ""}</td>
      <td>{identity}</td>
      <td>{_sender_status(when.get(one.name, 0), waiting, lang)}</td>
      <td>{_place_cell(places, sender, say)}</td>
      <td class="act">
        <form method="post" action="./senders/{html.escape(one.name)}/remove"
              class="inline">
          <button type="submit" class="quiet">
            {html.escape(say("Remove name"))}</button></form></td>
    </tr>{detail}''')
    announced = f'''
  <table class="stations">
    <thead><tr><th>{html.escape(say("Name"))}</th>
               <th>{html.escape(say("Identity"))}</th>
               <th>{html.escape(say("Status"))}</th>
               <th>{html.escape(say("Used by"))}</th><th></th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>''' if rows else (
      f'<p class="note">{html.escape(say("No named senders."))}</p>')

    add = ""
    if not admin.read_only:
        add = ('<div class="actions">'
               '<a class="button" href="./new-sender">'
               f'{html.escape(say("Add sender"))}</a>'
               "</div>")
    try:
        waiting = _waiting(admin, seen, register, places)
        folded = _folded(seen, lang)
    finally:
        _close_sightings(seen)
    return f'''
<h2>{html.escape(say("Senders"))}</h2>
{chain}
{problem}{add}
<section class="group">
  {announced}
</section>
{waiting}
{folded}
<script>
(function () {{
  var wanted = new URLSearchParams(location.search).get('open');
  if (!wanted) return;
  var row = Array.prototype.find.call(
    document.querySelectorAll('[data-sender]'),
    function (one) {{ return one.getAttribute('data-sender') === wanted; }});
  if (!row) return;
  var detail = Array.prototype.find.call(
    document.querySelectorAll('[data-sender-detail]'),
    function (one) {{ return one.getAttribute('data-sender-detail') === wanted; }});
  if (detail) {{
    var fold = detail.querySelector('details');
    if (fold) fold.open = true;
  }}
  row.scrollIntoView({{block: 'center'}});
}}());
</script>'''


def _waiting(admin: Any, seen: Any, register: Any, places: list[Any]) -> str:
    """Senders observed in live but not named yet."""
    say = admin.say
    lang = admin.language
    waiting = seen.waiting()
    if not waiting:
        return ""

    rows = []
    for one in waiting:
        from .db.live import sender_id

        sender = sender_id(one.driver, one.identity)
        fields = ", ".join(one.fields[:6])
        suggested = (one.identity or one.peer or "sender").lower()
        suggested = "".join(c if c.isalnum() else "-" for c in suggested)[:20]
        anchor = html.escape(_sender_anchor(sender), quote=True)
        rows.append(f'''
    <tr id="{anchor}" data-sender="{html.escape(sender, quote=True)}">
      <td>{_technical_identity(one.driver, one.identity, sender, say)}</td>
      <td>{_sender_status(one.last_seen, lang=lang)}</td>
      <td>{_place_cell(places, sender, say)}</td>
      <td><span class="note">{html.escape(fields)}</span></td>
      <td>
        <form method="post" action="./senders/adopt" class="inline">
          <input type="hidden" name="driver" value="{html.escape(one.driver)}">
          <input type="hidden" name="identity" value="{html.escape(one.identity)}">
          <input type="text" name="name" required
                 placeholder="{html.escape(say("sender name"))}"
                 value="{html.escape(suggested)}" autocomplete="off"
                 spellcheck="false">
          <button type="submit">{html.escape(say("Save name"))}</button>
        </form>
        <form method="post" action="./senders/ignore" class="inline">
          <input type="hidden" name="driver" value="{html.escape(one.driver)}">
          <input type="hidden" name="identity" value="{html.escape(one.identity)}">
          <button type="submit" class="quiet">
            {html.escape(say("Ignore"))}</button>
        </form>
      </td>
    </tr>''')

    return f'''
<section class="group">
  <h3>{html.escape(say("New senders"))}
    <span class="count">{len(waiting)}</span></h3>
  <table class="stations">
    <thead><tr><th>{html.escape(say("Identity"))}</th>
               <th>{html.escape(say("Status"))}</th>
               <th>{html.escape(say("Used by"))}</th>
               <th>{html.escape(say("Fields"))}</th>
               <th>{html.escape(say("Name"))}</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>'''


def _folded(seen: Any, lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    folded = seen.ignored()
    if not folded:
        return ""
    rows = []
    for one in folded:
        identity = html.escape(one.identity or lang.say("(none)"))
        rows.append(f'''
    <tr>
      <td>{html.escape(one.driver)} <code>{identity}</code></td>
      <td><span class="note">
        {html.escape(_ago(one.last_seen, lang))}</span></td>
      <td>
        <form method="post" action="./senders/unignore" class="inline">
          <input type="hidden" name="driver" value="{html.escape(one.driver)}">
          <input type="hidden" name="identity" value="{html.escape(one.identity)}">
          <button type="submit" class="quiet">
            {html.escape(lang.say("Restore"))}</button>
        </form>
      </td>
    </tr>''')
    return f'''
<section class="group">
  <details>
    <summary><h3>{html.escape(lang.say("Ignored"))}
      <span class="count">{len(folded)}</span></h3></summary>
    <table class="stations">
      <thead><tr><th>{html.escape(lang.say("Identity"))}</th>
                 <th>{html.escape(lang.say("Last seen"))}</th>
                 <th></th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </details>
</section>'''


def new(admin: Any, error: str = "", form: dict | None = None,
        made: Any = None) -> str:
    """Register a sender whose hardware can be pointed at the listener."""
    form = form or {}
    if made is not None:
        return _what_to_enter(admin, made)

    say = admin.say
    offered = tellable()
    chosen = form.get("driver") or ("wunderground" if "wunderground" in offered
                                    else next(iter(offered), ""))
    options = NEWLINE.join(
        f'<option value="{html.escape(kind)}"'
        f'{" selected" if chosen == kind else ""}>'
        f"{html.escape(say(one.label))}</option>"
        for kind, one in offered.items())
    explained = "".join(
        f"<li><strong>{html.escape(say(one.label))}</strong>: "
        f"{html.escape(say(one.hardware))}</li>"
        for one in offered.values())
    # Named rather than described in general terms. "Hardware that cannot be
    # told where to upload" leaves somebody holding an AcuRite bridge to work
    # out which sentence is about them; the protocols say what they are, and
    # each of them carries the steps for pointing DNS at us.
    host, port, _guessed = _where_consoles_reach_us(admin)
    token = admin.config().get("token") or ""
    adopting = "".join(
        f'<details class="kind"><summary>{html.escape(say(one.label))}: '
        f'{html.escape(say(one.hardware))}</summary><ol class="steps">'
        + "".join(_step(fill(say(note), host, port, token, name))
                  for note in one.notes)
        + "</ol></details>"
        for name, one in setups().items() if not one.tellable)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    other = ""
    if adopting:
        other = (f"<details><summary>{html.escape(say('Other hardware'))}"
                 f"</summary>{adopting}</details>")

    return f'''
<section class="group">
  <h3>{html.escape(say("Add sender"))}</h3>
  {problem}
  <form method="post" action="./new-sender">
    <div class="field">
      <label for="s-name">{html.escape(say("Name"))}</label>
      <input type="text" id="s-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="garden" autocomplete="off" spellcheck="false">
      <p class="help">{html.escape(say(
         "Lowercase letters, digits, - and _."))}</p>
    </div>
    <div class="field">
      <label for="s-driver">{html.escape(say("Protocol"))}</label>
      <select id="s-driver" name="driver">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions">
      <button type="submit">{html.escape(say("Continue"))}</button></div>
  </form>
  {other}
</section>'''


def _driver_options(driver: str, wanted: tuple[str, ...]) -> list[Any]:
    """This driver's own options, in the order its step asked for them."""
    from .ingest import drivers as driver_defs

    one = driver_defs.DEFAULT.get(driver)
    if one is None:
        return []
    describe = getattr(type(one), "options", None)
    if describe is None:
        return []
    try:
        groups = describe() or ()
    except Exception:
        log.exception("driver %r could not describe its options", driver)
        return []
    by_name = {getattr(o, "name", ""): o
               for group in groups for o in getattr(group, "options", ()) or ()}
    return [by_name[name] for name in wanted if name in by_name]


def _settings_step(admin: Any, station: Any, step: Any) -> str:
    """The half of a setup that is entered here rather than into the hardware.

    Hardware that is asked rather than heard has nothing to type into: a
    PurpleAir sensor answers whoever reaches it, so the whole of setting one
    up is telling us its address. That was a form on the settings page,
    reached from another menu, with nothing on this page to say it existed.

    It posts to the driver's own settings route, which is where the parsing,
    the validation and the writing already are. A second path to the same
    file is a second set of rules for what a valid value is, and the two
    would be found to disagree by somebody whose sensor stopped polling.
    """
    from . import admin as admin_defs

    options = _driver_options(station.driver, step.settings)
    if not options:
        return ""
    values = admin.config()
    prefix = f"drivers.{station.driver}."
    fields = "".join(
        admin_defs.field(one, values.get(prefix + one.name,
                                         values.get(one.name)),
                         "", "", admin.language)
        for one in options)
    return f'''
  <form method="post" action="./{html.escape(station.driver)}">
    {fields}
    <input type="hidden" name="_back" value="{html.escape(station.name)}">
    <div class="actions"><button type="submit">
      {html.escape(admin.say("Save"))}</button></div>
  </form>'''


def _what_to_enter(admin: Any, station: Any) -> str:
    """The point of the whole wizard: what to do, in the order it is done."""
    from .ingest import drivers as driver_defs

    say = admin.say
    lang = admin.language
    token = admin.config().get("token") or ""
    host, port, guessed = _where_consoles_reach_us(admin)

    waiting = station.identity.startswith(AWAITING)
    # Said out loud where it was worked out rather than told. A guessed
    # address is right on a home network and wrong behind anything -- a
    # published container port, a reverse proxy -- and the wrong one looks
    # exactly like the right one. Somebody types it into a console, nothing
    # arrives, and there is nothing anywhere to suspect.
    caveat = "" if not guessed else (
        '<p class="help warn">' + html.escape(say(
            "This address is what this machine sees of itself. Behind a "
            "reverse proxy or a published container port it is not the one a "
            "device can reach -- set 'Address consoles reach it at' under "
            "Listener, and this will say that instead.")) + "</p>")

    said = setups().get(station.driver)
    driver = driver_defs.DEFAULT.get(station.driver)
    steps = driver_defs.steps_of(driver) if driver is not None else ()

    if waiting:
        # The step that checks rather than instructs. The operator is standing
        # at the console, so this is the moment to read its identity off the
        # wire -- rather than at some point in service, to whichever console
        # happens to speak first.
        how = html.escape(lang.fill(
            "This sender names itself with a {field} of its own and cannot "
            "be told what to call itself, so press that once it is sending. "
            "The first upload from {kind} hardware this installation does "
            "not know yet becomes {name}.",
            field=said.identity if said else say("name"),
            kind=say(said.label) if said else station.driver,
            name=station.name))
        listening = f'''
  <form method="post" action="./senders/{html.escape(station.name)}/learn">
    <div class="actions"><button type="submit">
      {html.escape(say("It is uploading now"))}</button></div>
  </form>
  <p class="help">{how}</p>'''
    else:
        listening = f'''
  <p class="help">{html.escape(say("Waiting for the first upload. Return to"))}
     <a href="./senders">{html.escape(say("Senders"))}</a>
     {html.escape(say("to check its status."))}</p>'''

    def _stage(step: Any, last: bool) -> str:
        """One numbered stage. Whatever it has, in the order it has it."""
        rows = "".join(
            f"<tr><th>{html.escape(say(label))}</th><td><code>"
            f"{html.escape(fill(value, host, port, token, station.driver, station.identity))}"
            "</code></td></tr>"
            for label, value in step.enter)
        told = "".join(_step(fill(say(one), host, port, token,
                                  station.driver, station.identity))
                       for one in step.notes)
        parts = [f"<h4>{html.escape(say(step.title))}</h4>"]
        if step.explain:
            parts.append(f'<p class="help">{html.escape(say(step.explain))}</p>')
        if rows:
            parts.append(f'<table class="stations enter">{rows}</table>')
        if told:
            parts.append(f'<ol class="steps">{told}</ol>')
        if step.settings:
            parts.append(_settings_step(admin, station, step))
        # The caveat about a guessed address belongs against the step that
        # prints one, not at the foot of the page: by the time somebody has
        # scrolled past three steps they have already typed it in.
        if rows and caveat:
            parts.append(caveat)
        if step.listens and last:
            parts.append(listening)
        return f'<li class="stage">{"".join(parts)}</li>'

    if steps:
        stages = "".join(_stage(one, n == len(steps) - 1)
                         for n, one in enumerate(steps))
        body = f'<ol class="wizard">{stages}</ol>'
    else:
        # A driver that is not installed here. The address is all that can be
        # stated, and stating it is better than the blank this used to be.
        where = (f"{_base(host, port)}/{token}/{station.driver}/" if token
                 else f"{_base(host, port)}/{station.driver}/")
        missing = _step(say("This driver is not installed here, so there are "
                            "no instructions for it."))
        body = (f'<table class="stations enter"><tr>'
                f'<th>{html.escape(say("Address"))}</th>'
                f"<td><code>{html.escape(where)}</code></td></tr></table>"
                f'<ol class="steps">{missing}</ol>' + caveat)

    if not steps:
        body += listening

    return f'''
<section class="group">
  <h3>{html.escape(lang.fill("Connect {name}", name=station.name))}</h3>
  <p class="ok">{html.escape(say("Sender created"))}</p>
  {body}
</section>'''


def _step(note: str) -> str:
    """One instruction, as a step. An indented line is a command to copy.

    Upstream indents them by four spaces, which is how a `dnsmasq` line and
    an `iptables` line are told apart from the sentence around them. Run
    together as prose they are unusable: the whole value of an AcuRite page
    is that the two lines can be copied.
    """
    if note.startswith("    "):
        return (f'<li><pre class="cmd"><code>'
                f'{html.escape(note.strip())}</code></pre></li>')
    return f"<li>{html.escape(note)}</li>"


def fill(text: str, host: str, port: str, token: str,
         driver: str = "", identity: str = "") -> str:
    """Put this installation's answers into a driver's placeholders.

    Replaced rather than `%`-formatted. A driver is free to write a note
    with a bare `%` in it -- an iptables rule, a percentage -- and `%`
    formatting would raise on it and take the whole page with it, at the
    moment somebody is trying to connect their first console. An unknown
    placeholder is left standing instead, which is visible and harmless.

    `driver` and `identity` are optional because the same notes are shown
    before there is a station: hardware that has to be adopted is pointed
    here by DNS, and that has to be readable on the page somebody is on when
    they find out their bridge cannot be told an address.
    """
    path = f"/{token}/{driver}/" if token else f"/{driver}/"
    for name, value in (("address", host),
                        ("port", str(port)),
                        ("base", _base(host, port)),
                        ("path", path),
                        ("identity", identity),
                        ("token", token or "(no token set)")):
        text = text.replace(f"%({name})s", value)
    return text


def _base(host: str, port: str) -> str:
    """`http://host`, `https://host` or `http://host:1234`.

    The port is left off where the scheme already says it. `:80` after a
    hostname is not wrong and it is one more thing to mistype into a
    console's little screen.
    """
    scheme = "https" if str(port) == "443" else "http"
    if str(port) in ("80", "443"):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _where_consoles_reach_us(admin: Any) -> tuple[str, str, bool]:
    """The address to type into a console. (host, port, was it guessed)

    **This process cannot know it.** The listener binds one address; what a
    console has to send to depends on port publishing, NAT and any reverse
    proxy in front -- all of them outside this program. Asked of a socket, a
    container answers with its bridge address and the port it binds, and the
    page then prints something like `172.28.0.2:8000` with complete
    confidence. It looks exactly like a real answer, the operator types it
    into their console, and nothing ever arrives.

    So it is a setting first, `reachable_at`, and only a guess where nobody
    said. The guess is right on the ordinary home network, which is why it
    stays -- but the caller is told it *is* a guess, because a wrong address
    that says nothing about itself is the whole of this failure.
    """
    said = str(admin.config().get("reachable_at") or "").strip()
    if said:
        from urllib.parse import urlsplit

        parsed = urlsplit(said if "//" in said else f"//{said}")
        if parsed.hostname:
            # The scheme decides the port where the address does not say
            # one: that is what a browser does with the same string, and an
            # operator who typed an https address means 443.
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            return parsed.hostname, str(port), False
        log.warning("reachable_at is %r, which has no hostname in it; "
                    "falling back to this machine's own address", said)

    host = str(admin.config().get("host") or "")
    if host in ("", "0.0.0.0", "::"):
        host = _own_address()
    return host, str(admin.config().get("port") or 8000), True


def _own_address() -> str:
    """An address a console on the same network can reach.

    The listener binds to everything, so the configured host says nothing
    about where to point hardware. Asked of a socket rather than of the
    hostname: a machine with several interfaces answers with the one that
    would carry the traffic.
    """
    import socket

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.168.1.1", 9))
            return probe.getsockname()[0]
        finally:
            probe.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "this machine's address"


def what_it_sends(admin: Any, station: Any) -> dict:
    """Latest raw readings for one sender, described only by stored data.

    Driver code is an ingest concern.  Once a packet is in the journal this
    page uses its persisted dialect mapping, just like the archive side.  A
    missing or damaged mapping stays visible as such; the UI never loads a
    plugin to guess what the listener meant.
    """
    where = live_db(admin)
    if where is None:
        return {}
    try:
        import sqlite3
        db = sqlite3.connect(f"file:{where}?mode=ro", uri=True)
    except Exception:
        log.debug("could not open the live table", exc_info=True)
        return {}
    try:
        row = db.execute(
            "SELECT p.data, p.raw, p.dateTime, p.dialect, p.mapping, m.spec "
            "FROM packet AS p LEFT JOIN dialect_mapping AS m "
            "ON m.digest = p.mapping "
            "WHERE p.driver = ? AND p.identity = ? "
            "ORDER BY p.dateTime DESC LIMIT 1",
            (station.driver, station.identity)).fetchone()
    except Exception:
        log.debug("could not read what %r sends", station.name, exc_info=True)
        return {}
    finally:
        db.close()
    if row is None:
        return {}

    import json as _json

    try:
        values = _json.loads(row[0]) or {}
    except (TypeError, ValueError):
        return {}
    if not isinstance(values, dict):
        return {}

    spec = _stored_mapping(row[4], row[5])
    values = _measurements(values, spec)
    sent = sorted(values)
    return {
        "sent": sent,
        "values": values,
        "raw": row[1] or "",
        "when": int(row[2] or 0),
        "dialect": row[3] or "",
        "catalog": _catalog_of(spec, values),
        "mapping": bool(spec) or row[3] in (None, ""),
    }


def _stored_mapping(reference: Any, encoded: Any) -> dict[str, Any]:
    """A packet's inert mapping object, accepting the brief inline format."""
    import hashlib
    import json as _json

    raw = encoded
    if raw is None and isinstance(reference, str) and reference.startswith("{"):
        raw = reference
    if not isinstance(raw, str) or len(raw.encode()) > 128 * 1024:
        return {}
    if encoded is not None and reference:
        if hashlib.sha256(raw.encode()).hexdigest() != reference:
            return {}
    try:
        found = _json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(found, dict) or found.get("version") != 1:
        return {}
    fields = found.get("fields")
    metadata = found.get("metadata", [])
    contested = found.get("contested", [])
    absent = found.get("absent", [])
    if not isinstance(fields, dict):
        return {}
    if not all(isinstance(key, str) and isinstance(value, str)
               for key, value in fields.items()):
        return {}
    if not all(isinstance(one, str) for one in metadata):
        return {}
    if not all(isinstance(one, str) for one in contested):
        return {}
    if not isinstance(absent, list):
        return {}
    return found


#: How far back the little curve beside each raw name reaches, and how many
#: points it is drawn from. Six hours is long enough to tell a probe in the
#: sun from one indoors, which is the question the curve is there to answer.
SERIES_WINDOW = 6 * 3600
SERIES_POINTS = 120


def recent_series(admin: Any, station: Any,
                  fields: set[str] | None = None) -> dict[str, list]:
    """The last few hours of each raw reading, thinned to a drawable number.

    A last value says what a sensor reads now. It does not say what it *is*,
    and that is the decision this page is for: `tf_ch1` following the outdoor
    temperature is a probe in the sun, `tf_ch1` flat at 21.2 all night is one
    indoors. One packet cannot show either.

    Thinned in SQL rather than read and sampled. A console reporting every
    eight seconds puts 2,700 rows with sixty fields each into six hours, and
    this is a page somebody leaves open -- decoding all of that per refresh
    is how a settings page becomes the reason the archiver is late.
    """
    where = live_db(admin)
    if where is None:
        return {}
    import json as _json
    import sqlite3

    since = time.time() - SERIES_WINDOW
    try:
        db = sqlite3.connect(f"file:{where}?mode=ro", uri=True)
    except Exception:
        return {}
    try:
        found = db.execute(
            "SELECT count(*), min(seq) FROM packet"
            " WHERE driver = ? AND identity = ? AND dateTime > ?",
            (station.driver, station.identity, since)).fetchone()
        held, first = (found or (0, None))
        if not held or first is None:
            return {}
        step = max(1, held // SERIES_POINTS)
        rows = db.execute(
            "SELECT dateTime, data FROM packet"
            " WHERE driver = ? AND identity = ? AND dateTime > ?"
            "   AND (seq - ?) % ? = 0 ORDER BY dateTime",
            (station.driver, station.identity, since, first, step)).fetchall()
    except Exception:
        log.debug("could not read what %r has been sending", station.name,
                  exc_info=True)
        return {}
    finally:
        db.close()

    series: dict[str, list] = {}
    for when, raw in rows:
        try:
            data = _json.loads(raw)
        except (TypeError, ValueError):
            continue
        for name, value in data.items():
            if fields is not None and name not in fields:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                # Not a measurement: `stationtype`, `model`, a firmware
                # string. There is no curve to draw for those and the row
                # beside them says so by having none.
                continue
            series.setdefault(name, []).append((int(when), number))
    return series


def _measurements(values: dict[str, Any],
                  spec: dict[str, Any]) -> dict[str, Any]:
    """Numeric observations, using only the mapping persisted at ingest."""
    metadata = set(spec.get("metadata") or ())
    absent = tuple(spec.get("absent") or ())
    found: dict[str, Any] = {}
    for name, value in values.items():
        if name in metadata:
            continue
        if isinstance(value, str) and value.strip() in absent:
            continue
        try:
            float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        found[str(name)] = value
    return found


def _catalog_of(spec: dict[str, Any],
                readings: dict[str, Any] | None = None) -> dict[str, str]:
    """Uncontested raw-to-field descriptions stored with this packet."""
    contested = set(spec.get("contested") or ())
    fields = spec.get("fields") or {}
    present = set(readings or fields)
    return {str(raw): str(field) for raw, field in fields.items()
            if raw in present and raw not in contested}


def _what_it_sends_html(admin: Any, station: Any) -> str:
    """Read-only sender diagnostics; Place configuration stays elsewhere."""
    say = admin.say
    found = what_it_sends(admin, station)
    if not found:
        return ""

    summary = admin.language.fill("Latest readings ({n})",
                                  n=len(found["sent"]))
    if found.get("dialect"):
        summary += f" · {found['dialect']}"
    if not found.get("mapping"):
        summary += " · " + say("mapping unavailable")

    readings = "".join(
        f'<tr><td class="mono">{html.escape(name)}</td>'
        f'<td class="mono">{html.escape(str(found["values"][name]))}</td>'
        f'<td class="note">{html.escape(found["catalog"].get(name, ""))}</td></tr>'
        for name in found["sent"])
    table = f'''
    <table class="stations sender-readings">
      <thead><tr><th>{html.escape(say("Raw field"))}</th>
                 <th>{html.escape(say("Latest value"))}</th>
                 <th>{html.escape(say("Stored description"))}</th></tr></thead>
      <tbody>{readings}</tbody>
    </table>''' if readings else ""

    raw = ""
    if found["raw"]:
        raw = f'''
    <label>{html.escape(say("Redacted upload"))}</label>
    <textarea class="rawupload" rows="4" readonly
              onclick="this.select()">{html.escape(found["raw"])}</textarea>'''

    return f'''
  <details class="sends">
    <summary>{html.escape(summary)}</summary>
    {table}{raw}{_properties(admin, station)}
  </details>'''


def _properties(admin: Any, station: Any) -> str:
    """What is true of this console, where what it changes is visible.

    They used to sit in the overview row, which put four controls beside
    every station on a page whose job is to say whether the readings are
    arriving. Changing any of them is rare; reading the row is not.

    Its own form rather than one save for the whole fold: placements belong
    to a place, while these tolerances belong to the console's clock.
    """
    if admin.read_only:
        return ""
    return f'''
    <form method="post" action="./senders/{html.escape(station.name)}/set"
          class="props">
      {_clock_fields(station, admin.say)}
      <button type="submit" class="quiet">
        {html.escape(admin.say("Save clock"))}</button>
    </form>'''


def _clock_fields(station: Any, say: Any = None) -> str:
    """This console's clock, folded away because almost none needs it.

    It was a per-protocol setting, which put one figure on every console
    speaking that protocol: an old display drifting a quarter of an hour a
    week and a GW2000 keeping NTP got the same tolerance, and the generous
    one the old display needs is generous for the new one too.

    Empty means the configured figure, and it stays empty on purpose --
    writing the default onto each station would freeze it, so a later change
    to the setting would reach every console except the ones already listed.
    """
    say = say or str
    behind = "" if station.max_behind is None else f"{station.max_behind:g}"
    ahead = "" if station.max_ahead is None else f"{station.max_ahead:g}"
    opened = " open" if (behind or ahead) else ""
    default = html.escape(say("as configured"))
    return f'''
      <details class="clock"{opened}>
        <summary>{html.escape(say("Sender clock"))}</summary>
        <p class="hint">{html.escape(say(
          "Allowed timestamp drift. Empty uses the global setting."))}</p>
        <label>{html.escape(say("behind"))}
          <input type="text" name="max_behind" value="{html.escape(behind)}"
                 placeholder="{default}" size="10"></label>
        <label>{html.escape(say("ahead"))}
          <input type="text" name="max_ahead" value="{html.escape(ahead)}"
                 placeholder="{default}" size="10"></label>
      </details>'''

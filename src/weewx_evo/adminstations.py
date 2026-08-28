"""The stations page.

Handwritten, like `adminplots.py` and for the same reason: the form generator
does one named value at a time, and this is a list of things with a list of
strangers beside it.

Three lists on one page. What is announced, what has turned up and has not
been announced, and what has been folded away. The second is the one that
earns the page: today a console nobody has announced is invisible. A wrong
identity becomes a second source and gets averaged into the first, an
unrecognised upload falls to the default driver, and neither leaves a trace
anywhere somebody looks.

**Two ways in, one list out.** Where the operator can enter something on the
device we state the values and they copy them across. Where they cannot -- an
Ambient WS-2902 has no server field, an AcuRite Access is reached by pointing
DNS at it -- the device turns up on its own and gets adopted from the second
list. Both end as a row in the first.
"""

from __future__ import annotations

import html
import logging
import time
from pathlib import Path
from typing import Any

from . import stations as station_defs

log = logging.getLogger(__name__)

NEWLINE = "\n"

#: Drivers whose hardware is told where to upload, so we can state an identity
#: and the operator copies it over. Anything else has to be adopted: its
#: identity comes off the wire and cannot be chosen.
TELLABLE = {
    "ecowitt": (
        "Ecowitt",
        ("A GW1000, GW2000, HP2551 or anything else set to the Ecowitt "
         "protocol. Server, port and path are yours to set; the identity is "
         "not, so it is read off the first upload."),
    ),
    "wunderground": (
        "Weather Underground protocol",
        ("Almost any console with a Custom Server field: Ambient, Froggit, "
         "Sainlogic, La Crosse gateways, and Ecowitt hardware set to the WU "
         "protocol."),
    ),
    "json": (
        "weewx-evo envelope",
        ("A collector you run yourself, or a WeeWX driver through "
         "weewx-evo weewx-driver."),
    ),
}

#: Drivers whose hardware carries its own identity, so we cannot hand one out
#: and have to read it off the first upload instead. The console can still be
#: told where to send, which is what separates these from hardware that has to
#: be adopted outright.
LEARNS_ITS_IDENTITY = frozenset({"ecowitt"})

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
    import os

    where = os.environ.get("WEEWX_EVO_LIVE") or admin.config().get("live_db")
    if not where:
        where = "live.sdb"
    found = Path(str(where))
    if not found.is_absolute():
        found = Path(admin.path).parent / found
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
    try:
        import sqlite3
        db = sqlite3.connect(f"file:{where}?mode=ro", uri=True)
        try:
            marks = ",".join("?" * len(names))
            rows = db.execute(
                f"SELECT source, MAX(dateTime) FROM packet "
                f"WHERE source IN ({marks}) GROUP BY source", names)
            return {row[0]: int(row[1] or 0) for row in rows}
        finally:
            db.close()
    except Exception:
        log.debug("could not read when stations were last seen", exc_info=True)
        return {}


# -- changing things ------------------------------------------------------

def adopt(admin: Any, driver: str, identity: str, name: str,
          archive: str = "") -> str:
    """Take a stranger into the register. Returns an error, or empty."""
    register = load(admin)
    station = station_defs.Station(
        name=(name or "").strip().lower(), driver=driver, identity=identity,
        archive=(archive or station_defs.DEFAULT_ARCHIVE).strip(),
        learnt=True)
    problem = register.why_not(station)
    if problem:
        return problem
    register.stations.append(station)
    error = store(admin, register, f"{station.name} adopted")
    if error:
        return error
    # Out of the sightings, because it is not a stranger any more. Leaving it
    # there would show the same console in two lists at once.
    seen = sightings_for(admin)
    seen.forget(driver, identity)
    return ""


def announce(admin: Any, name: str, driver: str, archive: str = "") -> tuple:
    """Create a station. Returns (station, error).

    Two shapes, and which one depends on where the identity comes from.
    Where we hand it out it goes straight onto the station and the operator
    copies it onto the console. Where the hardware carries its own -- an
    Ecowitt PASSKEY -- the station is created waiting for it, and `learn()`
    fills it in from the first upload that has nowhere else to go.
    """
    register = load(admin)
    waiting = driver in LEARNS_ITS_IDENTITY
    identity = "" if waiting else register.identity_for(driver)
    station = station_defs.Station(
        name=(name or "").strip().lower(), driver=driver,
        identity=identity or f"{AWAITING}{name}".strip(),
        archive=(archive or station_defs.DEFAULT_ARCHIVE).strip(),
        learnt=waiting)
    problem = register.why_not(station)
    if problem:
        return None, problem
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
        return None, f"There is no station called {name!r}."
    if not station.identity.startswith(AWAITING):
        return station, ""          # already learnt; nothing to do

    waiting = [one for one in sightings_for(admin).waiting()
               if one.driver == station.driver and one.identity]
    if not waiting:
        return None, ""             # nothing has arrived yet, which is normal

    from dataclasses import replace as _replace

    found = waiting[0]
    filled = _replace(station, identity=found.identity, learnt=True)
    problem = register.why_not(filled, replacing=station.name)
    if problem:
        return None, problem
    register.stations[register.stations.index(station)] = filled
    error = store(admin, register, f"{station.name} learnt its identity")
    if error:
        return None, error
    sightings_for(admin).forget(found.driver, found.identity)
    return filled, ""


def configure(admin: Any, name: str, form: dict) -> str:
    """Change what is true of one console. Returns an error, or empty.

    Only what the page can send. A form arriving without a checkbox means it
    was unticked, not that the field was left out -- which is why `indoor` is
    read as presence rather than as a value, the same way the settings page
    handles every other boolean.
    """
    from dataclasses import replace as _replace

    register = load(admin)
    station = register.by_name(name)
    if station is None:
        return f"There is no station called {name!r}."
    changed = _replace(station,
                       indoor=bool(form.get("indoor")),
                       archive=str(form.get("archive") or station.archive))
    if changed == station:
        return ""
    register.stations[register.stations.index(station)] = changed
    return store(admin, register, f"{name} changed")


def remove(admin: Any, name: str) -> str:
    register = load(admin)
    if register.remove(name) is None:
        return f"There is no station called {name!r}."
    return store(admin, register, f"{name} removed")


def ignore(admin: Any, driver: str, identity: str, on: bool = True) -> str:
    seen = sightings_for(admin)
    if not seen.ignore(driver, identity, on):
        return "That console is not on the list any more."
    return ""


# -- the page -------------------------------------------------------------

def nav(admin: Any, active: str) -> list[str]:
    register = load(admin)
    out = ['<p class="navhead">Stations</p>']
    if not len(register):
        out.append('<p class="navempty">None yet. A station is a console '
                   'that uploads: it gets a name, an identity and the '
                   'archive it writes into.</p>')
    current = " aria-current='page'" if active == "stations" else ""
    out.append(f'<a href="./stations"{current}>Consoles'
               f'<span class="count">{len(register)}</span></a>')
    if not admin.read_only:
        current = " aria-current='page'" if active == "new-station" else ""
        out.append(f'<a class="add" href="./new-station"{current}>'
                   "+ Add a station</a>")
    return out


def _ago(when: int) -> str:
    if not when:
        return "never"
    gap = max(0, int(time.time()) - when)
    if gap < 90:
        return f"{gap} s ago"
    if gap < 5400:
        return f"{gap // 60} min ago"
    if gap < 172800:
        return f"{gap // 3600} h ago"
    return f"{gap // 86400} days ago"


def overview(admin: Any, message: str = "", error: str = "") -> str:
    """The three lists."""
    register = load(admin)
    seen = sightings_for(admin)
    when = last_seen(admin, [one.name for one in register])
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    said = f'<p class="ok">{html.escape(message)}</p>' if message else ""

    rows = []
    for one in sorted(register, key=lambda s: s.name):
        waiting = one.identity.startswith(AWAITING)
        if waiting:
            shown = ('<span class="note">waiting for its first upload</span>'
                     f'<br><a href="./new-station?learn='
                     f'{html.escape(one.name)}">what to enter</a>')
        else:
            mark = ("read off the hardware" if one.learnt
                    else "copied onto the console")
            shown = (f'<code>{html.escape(one.identity)}</code>'
                     f'<br><span class="note">{mark}</span>')
        rows.append(f'''
    <tr>
      <td><strong>{html.escape(one.name)}</strong>
          {f'<br><span class="note">{html.escape(one.note)}</span>' if one.note else ""}</td>
      <td>{html.escape(one.driver)}</td>
      <td>{shown}</td>
      <td>{html.escape(one.archive)}</td>
      <td>{html.escape(_ago(when.get(one.name, 0)))}</td>
      <td>
        <form method="post" action="./stations/{html.escape(one.name)}/set"
              class="inline">
          <label class="tick" title="Record the room the console stands in">
            <input type="checkbox" name="indoor" value="1"
                   {"checked" if one.indoor else ""}> indoor
          </label>
          <button type="submit" class="quiet">Save</button>
        </form>
        <form method="post" action="./stations/{html.escape(one.name)}/remove"
              class="inline">
          <button type="submit" class="quiet">Remove</button></form></td>
    </tr>
    <tr class="sendsrow"><td colspan="6">{_what_it_sends_html(admin, one)}</td></tr>''')
    announced = f'''
  <table class="stations">
    <thead><tr><th>Name</th><th>Driver</th><th>Identity</th><th>Archive</th>
               <th>Last reading</th><th></th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>''' if rows else (
        '<p class="lede">None announced yet. Readings still arrive and are '
        'recorded under whatever identity the hardware sends; announcing a '
        'console gives it a name and an archive.</p>')

    return f'''
<section class="group">
  <h3>Stations</h3>
  <p class="lede">A station is a console that uploads. It has a name, an
     identity that tells its packets apart, and the archive it writes into.
     Two consoles measuring one garden are two stations in one archive; two
     sites are two archives.</p>
  {said}{problem}
  {announced}
</section>
{_waiting(seen, register)}
{_folded(seen)}'''


def _waiting(seen: Any, register: Any) -> str:
    """Consoles that have uploaded and are not announced."""
    waiting = seen.waiting()
    if not waiting:
        return '''
<section class="group">
  <h3>Seen, not announced</h3>
  <p class="lede">Nothing unaccounted for. Anything that uploads without being
     announced appears here rather than being dropped in silence: hardware
     that announces itself, a device reached by pointing DNS at us, or a
     console whose identity has a typo in it.</p>
</section>'''

    rows = []
    for one in waiting:
        fields = ", ".join(one.fields[:6])
        suggested = (one.identity or one.peer or "console").lower()
        suggested = "".join(c if c.isalnum() else "-" for c in suggested)[:20]
        rows.append(f'''
    <tr>
      <td><code>{html.escape(one.identity or "(no identity)")}</code>
          <br><span class="note">from {html.escape(one.peer or "?")}</span></td>
      <td>{html.escape(one.driver)}</td>
      <td>{one.packets} packet(s)<br>
          <span class="note">{html.escape(_ago(one.last_seen))}</span></td>
      <td><span class="note">{html.escape(fields)}</span></td>
      <td>
        <form method="post" action="./stations/adopt" class="inline">
          <input type="hidden" name="driver" value="{html.escape(one.driver)}">
          <input type="hidden" name="identity" value="{html.escape(one.identity)}">
          <input type="text" name="name" required placeholder="a name"
                 value="{html.escape(suggested)}" autocomplete="off"
                 spellcheck="false">
          <button type="submit">Adopt</button>
        </form>
        <form method="post" action="./stations/ignore" class="inline">
          <input type="hidden" name="driver" value="{html.escape(one.driver)}">
          <input type="hidden" name="identity" value="{html.escape(one.identity)}">
          <button type="submit" class="quiet">Ignore</button>
        </form>
      </td>
    </tr>''')

    return f'''
<section class="group">
  <h3>Seen, not announced<span class="count">{len(waiting)}</span></h3>
  <p class="lede">These uploaded and are not in the list above. Their readings
     are being recorded under the identity the hardware sends. Adopting one
     gives it a name and an archive; ignoring folds it away without losing
     it.</p>
  <table class="stations">
    <thead><tr><th>Identity</th><th>Driver</th><th>Seen</th>
               <th>Sends</th><th></th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>'''


def _folded(seen: Any) -> str:
    folded = seen.ignored()
    if not folded:
        return ""
    rows = []
    for one in folded:
        rows.append(f'''
    <tr>
      <td><code>{html.escape(one.identity or "(no identity)")}</code></td>
      <td>{html.escape(one.driver)}</td>
      <td><span class="note">{html.escape(_ago(one.last_seen))}</span></td>
      <td>
        <form method="post" action="./stations/unignore" class="inline">
          <input type="hidden" name="driver" value="{html.escape(one.driver)}">
          <input type="hidden" name="identity" value="{html.escape(one.identity)}">
          <button type="submit" class="quiet">Bring back</button>
        </form>
      </td>
    </tr>''')
    return f'''
<section class="group">
  <details>
    <summary><h3>Ignored<span class="count">{len(folded)}</span></h3></summary>
    <p class="lede">Folded away, not decided. Any of these can still be
       adopted. One that stops uploading is forgotten after a fortnight, so a
       neighbour's console seen once does not stay here.</p>
    <table class="stations">
      <thead><tr><th>Identity</th><th>Driver</th><th>Last seen</th><th></th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </details>
</section>'''


def new(admin: Any, error: str = "", form: dict | None = None,
        made: Any = None) -> str:
    """Announce a console we can state the values for."""
    form = form or {}
    if made is not None:
        return _what_to_enter(admin, made)

    register = load(admin)
    chosen = form.get("driver") or "wunderground"
    options = NEWLINE.join(
        f'<option value="{html.escape(kind)}"'
        f'{" selected" if chosen == kind else ""}>{html.escape(label)}</option>'
        for kind, (label, _why) in TELLABLE.items())
    explained = "".join(
        f"<li><strong>{html.escape(label)}</strong>: {html.escape(why)}</li>"
        for _kind, (label, why) in TELLABLE.items())
    archives = NEWLINE.join(
        f'<option value="{html.escape(one)}">{html.escape(one)}</option>'
        for one in register.archives())
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""

    return f'''
<section class="group">
  <h3>Add a station</h3>
  <p class="lede">For hardware you can point at this server. Fill this in and
     the next page states exactly what to type into the console, including an
     identity that is handed out here so it cannot be used twice.</p>
  <p class="lede">Hardware that cannot be told where to upload is not added
     here. An Ambient WS-2902 has no server field and an AcuRite Access is
     reached by pointing DNS at it; those turn up on their own and are adopted
     from <a href="./stations">the stations page</a>.</p>
  {problem}
  <form method="post" action="./new-station">
    <div class="field">
      <label for="s-name">Name</label>
      <input type="text" id="s-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="garden" autocomplete="off" spellcheck="false">
      <p class="help">Lowercase letters, digits, - and _. This is what the
         readings are recorded under, and what <code>sources.toml</code>
         writes its rules against.</p>
    </div>
    <div class="field">
      <label for="s-driver">Protocol</label>
      <select id="s-driver" name="driver">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="field">
      <label for="s-archive">Archive</label>
      <select id="s-archive" name="archive">{archives}</select>
      <p class="help">The measurement series it writes into. One place, one
         archive.</p>
    </div>
    <div class="actions"><button type="submit">Create</button></div>
  </form>
</section>'''


def _what_to_enter(admin: Any, station: Any) -> str:
    """The point of the whole wizard: what to type into the console."""
    host = admin.config().get("host") or ""
    port = admin.config().get("port") or 8000
    token = admin.config().get("token") or ""
    if host in ("", "0.0.0.0", "::"):
        host = _own_address()

    waiting = station.identity.startswith(AWAITING)

    if station.driver == "ecowitt":
        rows = [
            ("Protocol", "Ecowitt"),
            ("Server / Hostname", host),
            ("Port", str(port)),
            ("Path", f"/{token}/ecowitt/" if token else "/ecowitt/"),
            ("Upload Interval", "16 or 60 seconds"),
        ]
        note = ("Ecowitt consoles take a path, so the token goes there rather "
                "than into a password field. The console names itself with a "
                "PASSKEY of its own, which is why there is nothing to type for "
                "an identity: it is read off the first upload.")
    elif station.driver == "wunderground":
        rows = [
            ("Protocol", "Wunderground"),
            ("Server / Hostname", host),
            ("Port", str(port)),
            ("Path", "/weatherstation/updateweatherstation.php"),
            ("Station ID", station.identity),
            ("Station Key / Password", token or "(no token set)"),
        ]
        note = ("The ID is the one handed out for this station. The password "
                "is the upload token: these consoles have no field for a path, "
                "so that is where it goes.")
    else:
        rows = [
            ("Address", f"http://{host}:{port}/{token}/json/"),
            ("Source", station.identity),
        ]
        note = ("Post the envelope to that address, with `source` set to the "
                "identity. `weewx-evo weewx-driver run` does it for a WeeWX "
                "driver.")

    table = "".join(
        f'<tr><th>{html.escape(label)}</th>'
        f'<td><code>{html.escape(str(value))}</code></td></tr>'
        for label, value in rows)

    if waiting:
        # The other half of the wizard. The operator is standing at the
        # console, so this is the moment to read its identity off the wire --
        # rather than at some point in service, to whichever console happens
        # to speak first.
        after = f'''
  <form method="post" action="./stations/{html.escape(station.name)}/learn">
    <div class="actions"><button type="submit">It is uploading now</button></div>
  </form>
  <p class="lede">This console names itself and cannot be told what to call
     itself, so press that once it is sending. The first upload from an
     Ecowitt console this installation does not know yet becomes
     <strong>{html.escape(station.name)}</strong>.</p>'''
    else:
        after = '''
  <p class="lede">The first upload appears on
     <a href="./stations">the stations page</a> as a reading under this name.
     Until then the console is not sending, or is not reaching this
     address.</p>'''

    return f'''
<section class="group">
  <h3>Enter this into the console</h3>
  <p class="ok">Station <strong>{html.escape(station.name)}</strong> is
     announced. It has not sent anything yet.</p>
  <table class="stations enter">{table}</table>
  <p class="help">{html.escape(note)}</p>
  {after}
</section>'''


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
    """What arrives from one station, and what the archive can hold.

    The point of this is the last column. A console gains a sensor and the
    reading turns up in every upload, is stored in the live table, and is
    dropped at every archive interval because nothing made a column for it.
    The archive says so in the log -- once per name per run, into a file
    nobody is tailing -- and the driver writes a report to `/var/tmp`.
    Neither is anywhere somebody looks.

    So it is asked here, of the same live table the readings are in, and it
    comes with the upload that produced it. That upload is already redacted:
    the driver takes its own secrets out (`redact`) before it is stored, which
    it does precisely so this can be handed to somebody else.
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
            "SELECT data, raw, dateTime FROM packet WHERE source = ? "
            "ORDER BY dateTime DESC LIMIT 1", (station.name,)).fetchone()
    except Exception:
        log.debug("could not read what %r sends", station.name, exc_info=True)
        return {}
    finally:
        db.close()
    if row is None:
        return {}

    import json as _json

    try:
        sent = sorted(_json.loads(row[0]) or {})
    except ValueError:
        return {}
    known = admin.columns()
    # An empty schema means the archive could not be read, not that every
    # field is homeless. Saying "45 dropped" there would be a false alarm on
    # a page whose whole job is telling the truth about what is stored.
    homeless = sorted(set(sent) - known) if known else []
    return {
        "sent": sent,
        "stored": sorted(set(sent) & known) if known else sent,
        "homeless": homeless,
        "raw": row[1] or "",
        "when": int(row[2] or 0),
    }


def _what_it_sends_html(admin: Any, station: Any) -> str:
    """One folded row per station: the fields, and the upload behind them."""
    found = what_it_sends(admin, station)
    if not found:
        return ""

    homeless = found["homeless"]
    summary = (f"{len(found['sent'])} fields, {len(found['stored'])} in the "
               f"archive")
    if homeless:
        summary += f", {len(homeless)} with nowhere to go"

    missing = ""
    if homeless:
        names = ", ".join(html.escape(one) for one in homeless)
        missing = f'''
    <p class="err">No column for: <code>{names}</code>. These arrive and are
       dropped at every archive interval. <code>weewx-evo columns --add</code>
       creates them; back the database up first.</p>'''

    raw = ""
    if found["raw"]:
        # Already redacted by the driver, which is why it can be shown at all
        # and why it is worth showing: this is what an issue about a new
        # sensor needs, and the alternative is asking somebody to reconfigure
        # a console and wait for an interval.
        raw = f'''
    <p class="help">The last upload, with whatever the driver calls secret
       already removed. This is what to paste into an issue about a sensor
       nothing here recognises.</p>
    <textarea class="rawupload" rows="4" readonly
              onclick="this.select()">{html.escape(found["raw"])}</textarea>'''

    return f'''
  <details class="sends">
    <summary>{html.escape(summary)}</summary>{missing}{raw}
  </details>'''

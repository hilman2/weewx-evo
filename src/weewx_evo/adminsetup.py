"""The setup wizard: from an empty directory to a station recording.

What a first run used to be: a settings page with nothing on it and eleven
links, every one of them a decision the operator has no information for yet.
The two questions that actually matter come first here, and everything else
follows from the answers.

    Is this a new station, or one moving over from WeeWX?

**Both halves are the point.** A new station needs a place, a token and a
console. One moving over has fifteen years of readings, a website it has
been looking at every morning, and an FTP password nobody remembers -- and
asking for those again is asking somebody to do accurately what a computer
can do exactly.

**Nobody installs this onto the machine that is recording their weather.**
So taking over is by *upload* first and by reading the disk second: a
weewx.conf and a weewx.sdb are files, and a browser can send a file. The
local search runs anyway, because somebody trying it out on the same machine
should not have to hunt for paths they already have.

**Reopenable, and that is not a nicety.** Somebody sets up the station and
comes back a week later to add the FTP account. A wizard that only exists
before the first save is a wizard people work around.

What it does not do: run anything. It writes settings and copies a file, and
the service picks them up. A wizard that started a service would have to
have opinions about how the service is supervised, and that is the
operator's business.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: The steps, in order. Each is a page; each knows whether it is done.
#: One list, because the progress bar and the router both need it and two
#: lists is how one of them ends up short.
STEPS = ("start", "place", "readings", "publish", "done")

TITLES = {
    "start": "Where the readings come from",
    "place": "Where the station is",
    "readings": "Charts and the archive",
    "publish": "Publishing",
    "done": "Ready",
}


def state(admin: Any) -> dict[str, Any]:
    """What is already answered, so a reopened wizard skips what is done."""
    from . import adopt

    cfg = admin.config()

    def said(dotted: str) -> Any:
        from . import config as config_file

        return config_file.get(cfg, dotted)

    stations = []
    try:
        from . import adminstations

        stations = list(adminstations.load(admin))
    except Exception:
        log.debug("could not read the stations", exc_info=True)

    archive = None
    try:
        from . import config as config_file

        archive = config_file.resolved_path(cfg, "archive_db",
                                            Path(admin.path).parent,
                                            "data/weewx.sdb")
    except Exception:
        log.debug("could not work out where the archive is", exc_info=True)

    charts = 0
    try:
        from . import adminplots

        charts = len(adminplots.load(admin))
    except Exception:
        log.debug("could not read the charts", exc_info=True)

    return {
        "token": bool(said("token")),
        "name": str(said("station.name") or "").strip(),
        "latitude": said("station.latitude"),
        "longitude": said("station.longitude"),
        "altitude": said("station.altitude"),
        "stations": stations,
        "charts": charts,
        "archive": archive,
        "records": adopt.count_records(archive) if archive
        and archive.exists() else 0,
        # A local WeeWX, if there is one. Looked for every time the page is
        # opened rather than remembered: somebody may install WeeWX after
        # first seeing this, and a remembered "no" would be wrong for ever.
        "weewx": adopt.find(),
        "feeds": list((cfg.get("feeds") or {}).keys()),
        "exports": list((cfg.get("exports") or {}).keys()),
        "forecast": list((cfg.get("forecast") or {}).keys()),
    }


def done_with(admin: Any, step: str) -> bool:
    """Whether that step has been answered."""
    now = state(admin)
    if step == "start":
        # Answered by there being anything at all: a station, an archive with
        # records, or a name. Somebody who has done any of it is past this.
        return bool(now["stations"] or now["records"] or now["name"])
    if step == "place":
        return bool(now["name"] and now["latitude"] is not None)
    if step == "readings":
        return bool(now["charts"])
    if step == "publish":
        return bool(now["exports"])
    return True


# -- the pages ------------------------------------------------------------

def page(admin: Any, step: str = "", error: str = "",
         form: dict | None = None, said: str = "") -> str:
    """One step of the wizard."""
    step = step if step in STEPS else "start"
    now = state(admin)
    body = {
        "start": _start,
        "place": _place,
        "readings": _readings,
        "publish": _publish,
        "done": _done,
    }[step](admin, now, form or {})

    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    told = f'<p class="ok">{html.escape(said)}</p>' if said else ""
    return f"""
<section class="group setup">
  {_progress(admin, step)}
  <h3>{html.escape(TITLES[step])}</h3>
  {problem}{told}
  {body}
</section>"""


def _progress(admin: Any, active: str) -> str:
    """Which step this is, and which are behind it.

    Every step reachable, including the ones already done. A wizard that
    only goes forwards is one somebody has to start over to correct a typo.
    """
    out = []
    for one in STEPS:
        if one == "done":
            continue
        classes = ["step"]
        if one == active:
            classes.append("here")
        elif done_with(admin, one):
            classes.append("did")
        out.append(
            f'<a class="{" ".join(classes)}" href="./setup/{one}">'
            f"{html.escape(TITLES[one])}</a>")
    return f'<nav class="steps">{"".join(out)}</nav>'


def _start(admin: Any, now: dict, form: dict) -> str:
    """New, or moving over. The question the rest of it hangs on."""
    weewx = now["weewx"]
    found = ""
    if weewx is not None:
        found = f"""
    <div class="field found">
      <p><strong>A WeeWX installation is on this machine.</strong>
         <code>{html.escape(str(weewx))}</code></p>
      <p class="help">Its station, coordinates, archive interval, skins and
         upload accounts can be read straight out of it. Nothing of WeeWX's
         is changed: the archive is copied, not moved, so it goes on
         recording while this is set up.</p>
      <form method="post" action="./setup/adopt">
        <input type="hidden" name="conf" value="{html.escape(str(weewx))}">
        <button type="submit">Read this installation</button>
      </form>
    </div>"""

    return f"""
  <p class="lede">Two ways in. Neither of them asks for anything twice.</p>
  {found}

  <div class="field">
    <h4>Moving over from WeeWX</h4>
    <p class="help">Send its <code>weewx.conf</code>. The station's name and
       coordinates, its archive interval, which skins it renders and its FTP
       or rsync account all come out of that one file. Its readings come
       next, as a file of their own.</p>
    <form method="post" action="./setup/adopt" enctype="multipart/form-data">
      <label>weewx.conf
        <input type="file" name="upload" accept=".conf,.txt,text/plain">
      </label>
      <div class="actions"><button type="submit">Read it</button></div>
    </form>
  </div>

  <div class="field">
    <h4>A new station</h4>
    <p class="help">Nothing to bring over. There are already
       {now["charts"]} charts and a website; what is missing is where the
       station is and which console it is.</p>
    <div class="actions">
      <a class="button" href="./setup/place">Start here</a>
    </div>
  </div>"""


def _place(admin: Any, now: dict, form: dict) -> str:
    """Name and coordinates. Everything astronomical hangs off these."""
    def value(field: str, fallback: Any = "") -> str:
        got = form.get(field, now.get(field, fallback))
        return html.escape("" if got is None else str(got))

    return f"""
  <p class="lede">The name goes at the top of every page. The coordinates
     decide sunrise, sunset, the moon and every twilight band on a chart --
     which is why they are asked for rather than guessed: a sunrise computed
     for the wrong field is wrong by minutes and looks entirely correct.</p>
  <form method="post" action="./setup/place">
    <div class="field">
      <label for="s-name">Name</label>
      <input type="text" id="s-name" name="name" required
             value="{value('name')}" placeholder="Kirchdorf an der Amper">
    </div>
    <div class="row">
      <div class="field">
        <label for="s-lat">Latitude</label>
        <input type="text" id="s-lat" name="latitude" required
               value="{value('latitude')}" placeholder="48.3858">
      </div>
      <div class="field">
        <label for="s-lon">Longitude</label>
        <input type="text" id="s-lon" name="longitude" required
               value="{value('longitude')}" placeholder="11.7050">
      </div>
      <div class="field">
        <label for="s-alt">Altitude</label>
        <input type="text" id="s-alt" name="altitude"
               value="{value('altitude')}" placeholder="440">
        <p class="help">Metres. Used for pressure at sea level.</p>
      </div>
    </div>
    <div class="field">
      <label class="tick">
        <input type="checkbox" name="forecast" value="1"
               {"checked" if not now["forecast"] else ""}>
        Fetch a forecast for this place
      </label>
      <p class="help">Open-Meteo. Free, no account, and it needs nothing
         beyond the coordinates above.</p>
    </div>
    <div class="actions"><button type="submit">Save and carry on</button></div>
  </form>"""


def _readings(admin: Any, now: dict, form: dict) -> str:
    """Charts and the archive: what a station arriving from WeeWX brings."""
    records = now["records"]
    archive = now["archive"]
    holding = ""
    if records:
        holding = f"""
    <p class="ok">This installation already has an archive:
       {records} records in <code>{html.escape(str(archive))}</code>.</p>"""
    return f"""
  <p class="lede">Charts are definitions, not pictures: the feeds draw
     whichever of them the readings support and skip the rest. There are
     {now["charts"]} of them now.</p>
  {holding}

  <div class="field">
    <h4>Charts from a skin</h4>
    <p class="help">A WeeWX skin keeps its charts in its own
       <code>skin.conf</code>, under <code>[ImageGenerator]</code> -- not in
       weewx.conf. Send that file and its charts come over as they are.</p>
    <form method="post" action="./setup/charts" enctype="multipart/form-data">
      <label>skin.conf
        <input type="file" name="upload" accept=".conf,.txt,text/plain">
      </label>
      <label class="tick">
        <input type="checkbox" name="replace" value="1" checked>
        Replace the charts that are here now
      </label>
      <div class="actions"><button type="submit">Import them</button></div>
    </form>
  </div>

  <div class="field">
    <h4>An existing archive</h4>
    <p class="help">A WeeWX <code>weewx.sdb</code> needs no conversion: it
       holds exactly the tables this program reads and writes. It is copied
       rather than moved, so the installation it came from goes on recording
       from it.</p>
    {_archive_form(admin, now)}
  </div>

  <div class="actions">
    <a class="button" href="./setup/publish">Carry on</a>
  </div>"""


def _archive_form(admin: Any, now: dict) -> str:
    """How an archive gets here: a path on this machine, or an upload.

    Both, because both happen. Somebody trying this out beside their WeeWX
    has a path; somebody on a different machine has a file. An archive is
    tens or hundreds of megabytes, so the upload is written straight to disk
    rather than held in memory -- see `admin.py`, where the limit for this
    one form is raised for exactly that reason.
    """
    if now["records"]:
        return ('<p class="help">There are readings here already, so this is '
                "left alone. Move the file aside first if you mean to "
                "replace it -- nothing here will write over readings.</p>")
    weewx = now["weewx"]
    suggested = ""
    if weewx is not None:
        from . import adopt

        found = adopt.read(weewx)
        if found.archive is not None:
            suggested = html.escape(str(found.archive))
    return f"""
    <form method="post" action="./setup/archive">
      <label>Path on this machine
        <input type="text" name="source" value="{suggested}"
               placeholder="/var/lib/weewx/weewx.sdb">
      </label>
      <div class="actions"><button type="submit">Copy it here</button></div>
    </form>
    <form method="post" action="./setup/archive"
          enctype="multipart/form-data" class="upload">
      <label>or send the file
        <input type="file" name="upload" accept=".sdb,.db,.sqlite">
      </label>
      <div class="actions"><button type="submit">Upload it</button></div>
    </form>"""


def _publish(admin: Any, now: dict, form: dict) -> str:
    """Where the pages go. Optional, and it says so."""
    return f"""
  <p class="lede">A feed writes files; an export moves them somewhere. This
     station already produces {len(now["feeds"])} feed(s). Where they go is
     the last thing, and it can wait -- the pages are served on this machine
     either way.</p>

  <form method="post" action="./setup/publish">
    <div class="field">
      <label for="p-host">FTP server</label>
      <input type="text" id="p-host" name="host"
             placeholder="ftp.example.org">
      <p class="help">Leave empty to skip this. Everything below is only
         asked because this is filled in.</p>
    </div>
    <div class="row">
      <div class="field">
        <label for="p-user">User</label>
        <input type="text" id="p-user" name="user" autocomplete="off">
      </div>
      <div class="field">
        <label for="p-pass">Password</label>
        <input type="password" id="p-pass" name="password"
               autocomplete="new-password">
      </div>
      <div class="field">
        <label for="p-dir">Directory</label>
        <input type="text" id="p-dir" name="directory" placeholder="/">
      </div>
    </div>
    <div class="field">
      <label for="p-url">Address the pages are served at</label>
      <input type="text" id="p-url" name="live_push_url"
             placeholder="https://example.org/">
      <p class="help">With one, the published pages show live readings: a
         small PHP file goes up with them and the station posts to it every
         few seconds. Nothing is opened; the connection goes outwards, like
         the upload itself. Leave it empty and the pages are as new as the
         last upload.</p>
    </div>
    <div class="actions">
      <button type="submit">Save</button>
      <a class="button quiet" href="./setup/done">Skip this</a>
    </div>
  </form>"""


def _done(admin: Any, now: dict, form: dict) -> str:
    """What is set up, and the one thing that is left."""
    stations = now["stations"]
    rows = []
    rows.append(("Place", now["name"] or "not set yet",
                 bool(now["name"])))
    rows.append((f"{now['charts']} charts", "ready", bool(now["charts"])))
    rows.append((f"{len(now['feeds'])} feed(s)",
                 ", ".join(now["feeds"]) or "none", bool(now["feeds"])))
    if now["records"]:
        rows.append((f"{now['records']} records", "carried over", True))
    rows.append((f"{len(now['exports'])} export(s)",
                 ", ".join(now["exports"]) or "publishing on this machine "
                 "only", True))
    rows.append(("Console",
                 ", ".join(one.name for one in stations) or "none yet",
                 bool(stations)))

    listed = "".join(
        f'<tr class="{"ok" if ok else "todo"}"><th>{html.escape(str(what))}'
        f"</th><td>{html.escape(str(said))}</td></tr>"
        for what, said, ok in rows)

    left = ""
    if not stations:
        left = """
    <div class="field">
      <h4>One thing left</h4>
      <p class="help">A console has to be announced before its readings are
         recorded under a name. That is the Stations page: it hands out an
         identity to type into the console, or adopts one that has already
         started uploading.</p>
      <div class="actions">
        <a class="button" href="./new-station">Add a station</a>
      </div>
    </div>"""

    return f"""
  <table class="summary">{listed}</table>
  {left}
  <p class="help">This wizard can be reopened at any time from the overview.
     Nothing here is a one-off: every one of these is also its own settings
     page.</p>"""

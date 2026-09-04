"""The add-on page: what is installed, what exists, and what would help here.

The core ships no driver. So the first thing a fresh installation needs is a
way to get one, and until this page there were two: a command on the machine,
or a URL pasted from a repository somebody had to find first.

Three sections, in the order they are useful:

    Suggested   what the catalogue says would read what is arriving unread.
                Empty on an installation that is working, which is the point:
                a list that is always there is one nobody reads.
    Installed   what this interpreter can actually load, with what each
                provides -- read from the entry points rather than from the
                catalogue, because what a package says it does and what it
                registers are two different facts and the second is the one
                that matters.
    Available   the catalogue, minus what is installed.

**Nothing is installed without a name from the catalogue.** The form sends a
package name, `addons.install` looks it up, and the URL comes from the entry.
A field naming a git URL of its own gets the same answer as a typo.

**And a restart is said, not done.** Entry points are read once per process,
so an add-on installed while the service runs is there and doing nothing
until it comes back. The wizard has the same rule for the same reason: how
the service is supervised is the operator's business.
"""

from __future__ import annotations

import html
import logging
from typing import Any

from . import addons

log = logging.getLogger(__name__)

NEWLINE = "\n"

#: What a catalogue entry's `kind` is called on this page. Only one entry is
#: in here and it is the whole of point 4: a package that hosts a WeeWX
#: driver is filed as `collector` because it runs as its own process, and
#: that is a fact about us. What somebody installing it gets is a driver --
#: for hardware on a serial port instead of hardware on the wifi, which is
#: not a difference they chose and not one they can act on. The catalogue
#: keeps its own word so that a station and the shop agree on what a package
#: is; the column says what it means.
SAID = {"collector": "driver"}


def nav(admin: Any, active: str) -> list[str]:
    """This page's entry in the System section."""
    say = admin.say
    here = ' aria-current="page"' if active == "addons" else ""
    return [f'<a href="./addons"{here}>{html.escape(say("Add-ons"))}</a>']


def _rows(plugins: list, installed: dict, admin: Any, suggested: bool = False
          ) -> str:
    """One table row per add-on, with what it is and a button."""
    say = admin.say
    out = []
    for one in plugins:
        have = one.name in installed
        button = ""
        if not admin.read_only:
            verb = "Remove" if have else "Install"
            style = ' class="quiet"' if have else ""
            # The verb in the path, not in a hidden field: that is how
            # every other action on this site is addressed, and the check in
            # `adminpage.py` is on it -- a second action sharing the save
            # form's action is the shape that took out every publishing page
            # once.
            button = (
                f'<form method="post" '
                f'action="./addons/{"remove" if have else "install"}">'
                f'<input type="hidden" name="package" '
                f'value="{html.escape(one.name)}">'
                f'<button type="submit"{style}>{html.escape(say(verb))}'
                f"</button></form>")
        kind = html.escape(say(SAID.get(one.kind, one.kind) or "add-on"))
        note = ""
        if suggested:
            # Why it is being suggested, in the row. A list of add-ons with
            # no reason attached is a shop; this is an answer to something
            # that is happening on the machine right now.
            note = (f'<p class="help">'
                    f'{html.escape(say("Reads an upload arriving here that nothing can read."))}'
                    f"</p>")
        # The boxes it reads, named the way a box is named. Somebody looking
        # for an add-on knows what is on their pole and nothing else -- and
        # one entry here covers the thirteen drivers WeeWX ships, so the row
        # that answers "does it do my Vantage" said Vantage nowhere. Not
        # translated: they are model names.
        boxes = ""
        if one.hardware:
            boxes = (f'<p class="help hardware">'
                     f'{html.escape(", ".join(one.hardware))}</p>')
        out.append(f'''
  <tr>
    <td><strong>{html.escape(one.name)}</strong>
        <p class="help">{html.escape(say(one.summary))}</p>{boxes}{note}</td>
    <td>{kind}</td>
    <td><a href="{html.escape(one.repository)}" rel="noreferrer noopener"
           target="_blank">{html.escape(say("Source"))}</a></td>
    <td>{button}</td>
  </tr>''')
    return "".join(out)


def _installed_rows(installed: dict, admin: Any, newer: dict) -> str:
    """What is here, what each registers, and what a newer one would be."""
    say, lang = admin.say, admin.language
    out = []
    for one in installed.values():
        provides = ", ".join(one.names) or say("nothing on its own")
        version = html.escape(one.version)
        buttons = ""
        if not admin.read_only:
            if one.package in newer:
                # Installing again is what updating is: the same route, the
                # same tarball, and pip replaces what is there. A separate
                # verb would be a second path doing the same thing.
                buttons += (
                    f'<form method="post" action="./addons/install">'
                    f'<input type="hidden" name="package" '
                    f'value="{html.escape(one.package)}">'
                    f'<button type="submit">'
                    f'{html.escape(say("Update"))}</button></form>')
            buttons += (
                f'<form method="post" action="./addons/remove">'
                f'<input type="hidden" name="package" '
                f'value="{html.escape(one.package)}">'
                f'<button type="submit" class="quiet">'
                f'{html.escape(say("Remove"))}</button></form>')
        if one.package in newer:
            version += ('<span class="hint">' + html.escape(lang.fill(
                "{version} is available", version=newer[one.package]))
                + "</span>")
        out.append(f'''
  <tr>
    <td><strong>{html.escape(one.package)}</strong></td>
    <td>{version}</td>
    <td>{html.escape(provides)}</td>
    <td>{buttons}</td>
  </tr>''')
    return "".join(out)


def overview(admin: Any, message: str = "", error: str = "") -> str:
    """The page."""
    say, lang = admin.say, admin.language
    have = addons.installed()
    offered = addons.offered()
    newer = addons.updatable()
    suggested = [one for one in addons.wanted_by_sightings(admin)
                 if one.name not in have]

    banner = ""
    if error:
        banner = f'<div class="banner bad">{html.escape(error)}</div>'
    elif message:
        banner = f'<div class="banner">{html.escape(message)}</div>'


    top = ""
    if suggested:
        top = f'''
<section class="group">
  <h3>{html.escape(say("Suggested for this station"))}</h3>
  <p class="lede">{html.escape(say(
      "Something is uploading here that nothing installed can read. The "
      "add-on list says these would."))}</p>
  <table class="stations">{_rows(suggested, have, admin, suggested=True)}</table>
</section>'''

    if not offered:
        # Offline, or GitHub was unreachable, and nothing was cached. Said
        # rather than shown as an empty list: an empty shop reads as "there
        # are none", and `driver install` still takes a local file.
        listing = f'''
<section class="group">
  <h3>{html.escape(say("Available"))}</h3>
  <p class="help">{html.escape(say(
      "The add-on list could not be fetched and none is cached here. A "
      "station with no way out can still install one from a file: "
      "weewx-evo driver install /path/to/it"))}</p>
</section>'''
    else:
        # A library is in the list so that it may be installed and never
        # offered: installing `weewx-evo-push-common` on its own registers
        # nothing and answers on no endpoint, and a shelf with a thing on it
        # that does nothing when chosen is a shelf somebody has to be warned
        # about. It arrives as a dependency of whatever needed it.
        rest = [one for one in offered
                if one.name not in have and one.kind != "library"]
        listing = f'''
<section class="group">
  <h3>{html.escape(say("Available"))}</h3>
  <p class="lede">{html.escape(lang.fill(
      "{n} add-on(s) in the list. The core ships none of them.",
      n=len(offered)))}</p>
  <p class="help">{html.escape(lang.fill(
      "Installed into {where}, which is in the data directory rather than "
      "with the program: what is installed here outlives an upgrade, and in "
      "a container it outlives the container.",
      where=str(addons.directory())))}</p>
  <table class="stations">
    <tr><th>{html.escape(say("Add-on"))}</th>
        <th>{html.escape(say("Kind"))}</th>
        <th>{html.escape(say("Where"))}</th><th></th></tr>
    {_rows(rest, have, admin)}
  </table>
</section>'''

    here = ""
    if have:
        here = f'''
<section class="group">
  <h3>{html.escape(say("Installed"))}</h3>
  <table class="stations">
    <tr><th>{html.escape(say("Package"))}</th>
        <th>{html.escape(say("Version"))}</th>
        <th>{html.escape(say("Provides"))}</th><th></th></tr>
    {_installed_rows(have, admin, newer)}
  </table>
</section>'''
    else:
        here = f'''
<section class="group">
  <h3>{html.escape(say("Installed"))}</h3>
  <p class="help">{html.escape(say(
      "None. A fresh installation can receive nothing until a driver is "
      "installed, which is deliberate: most stations are one console, and "
      "one is what they should have to install."))}</p>
</section>'''

    return f"{banner}{top}{here}{listing}"


def act(admin: Any, action: str, form: dict) -> str:
    """Install or remove one. Returns "" or what went wrong.

    `action` is the last path segment rather than a form field, which is how
    every action on this site is addressed: a path is whatever a browser
    resolved a relative link to, and the verb is what the button said.

    The package name is checked against the catalogue by `addons.install`,
    which is where that check belongs: the command line reaches the same
    function, and a rule enforced on one route only is a rule with a way past
    it.
    """
    package = str(form.get("package") or "").strip()
    if action == "remove":
        return addons.remove(package)
    if action == "install":
        return addons.install(package)
    return f"Unknown add-on action {action!r}."

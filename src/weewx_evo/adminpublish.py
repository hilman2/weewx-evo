"""Publishing: what gets made, and where each of those goes.

A feed makes files. An export moves them. Those are two different things and
the settings page was right to keep the settings apart -- but it also kept
the *listing* apart, so the sidebar had "Feed: wdc" under one heading and
"Export: wdc" under another and nothing anywhere said that the second
publishes the first. The operator held the connection in their head.

Here it is on the screen. One block per feed, its exports indented under it,
in the order the files actually move:

    wdc          a WeeWX skin        40 files      38 s ago
      -> wdc     into /data/wdc      local          8 s ago

An export that names no feed gets its own block at the end rather than being
hidden: it is configured and it runs, and a page that only showed the tidy
cases would be a page you cannot trust when something is untidy.

## Why this is not the overview

The overview answers "is it working". This answers "what is set up, and how
does it fit together" -- and every row is a link to the form that changes it.
They read the same files and say different things about them.

## The sidebar this replaces

One entry per configured thing, so it grew with the installation: three
feeds, five exports and an upload made nine links under four headings. The
sections are fixed now and the instances live on their section's page, which
is what stops the navigation growing without bound.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from . import adminhome
from . import config as config_file

log = logging.getLogger(__name__)

NEWLINE = "\n"

#: What each feed kind is, in the words somebody choosing one would use.
KINDS = {
    "json": "the time series everything else is built on",
    "images": "charts as PNG files",
    "cheetah": "a WeeWX skin, rendered",
    "diagnostic": "a page showing what is on disk",
    "realtime": "a small file, rewritten every reading",
}


def _rows_for(admin: Any) -> tuple[dict, dict, dict]:
    current = admin.config()
    feeds = {n: s for n, s in (current.get("feeds") or {}).items()
             if isinstance(s, dict)}
    exports = {n: s for n, s in (current.get("exports") or {}).items()
               if isinstance(s, dict)}
    uploads = {n: s for n, s in (current.get("uploads") or {}).items()
               if isinstance(s, dict)}
    return feeds, exports, uploads


def _short(where: str, keep: int = 34) -> str:
    """A path somebody can read at a glance, from the end.

    The end is the part that identifies it. A published directory is
    `/var/www/html/weather` or a temp path forty characters deep, and the
    left-hand half of either is the same on every row -- so it is what goes.
    The full text stays in the title attribute.
    """
    text = str(where or "")
    if len(text) <= keep:
        return text
    return "…" + text[-(keep - 1):]


def _where(admin: Any, settings: dict) -> str:
    """Where an export puts things, in one short phrase."""
    kind = str(settings.get("kind") or "")
    if kind == "local":
        return str(settings.get("directory") or "a directory")
    if kind == "ftp":
        host = str(settings.get("host") or "")
        return f"{host}{settings.get('directory') or ''}" if host else "FTP"
    if kind == "rsync":
        host = str(settings.get("host") or "")
        return f"{host}:{settings.get('directory') or ''}" if host else "rsync"
    return kind or "somewhere"


def _age(admin: Any, state: adminhome.State, name: str,
         which: str) -> tuple[str, str]:
    """(what it says, extra class) for one thing's age."""
    links = {"feed": state.feeds, "export": state.exports,
             "upload": state.uploads}[which]
    for one in links:
        if one.name == name:
            if one.unreachable:
                return one.unreachable, "note when"
            return adminhome.ago(one.when), "when"
    return "", "note when"


def _chip(text: str, tone: str = "") -> str:
    return f'<span class="chip {tone}">{html.escape(text)}</span>'


def _export_row(admin: Any, state: adminhome.State, name: str,
                settings: dict) -> str:
    said, tone = _age(admin, state, name, "export")
    off = settings.get("enabled") is False
    return f'''
      <li>
        <span class="arrow" aria-hidden="true">&rarr;</span>
        <a href="./export:{html.escape(name)}">{html.escape(name)}</a>
        <span class="note" title="{html.escape(_where(admin, settings))}"
              >into {html.escape(_short(_where(admin, settings)))}</span>
        {_chip(str(settings.get("kind") or ""))}
        <span class="{tone}">{"switched off" if off else html.escape(said)}</span>
      </li>'''


def _block(admin: Any, state: adminhome.State, name: str, settings: dict,
           exports: list[tuple[str, dict]]) -> str:
    kind = str(settings.get("kind") or "")
    said, tone = _age(admin, state, name, "feed")
    off = settings.get("enabled") is False
    reads = str(settings.get("archive") or "").strip()
    where = _chip(f"from {reads}") if reads and reads != "default" else ""
    sent = NEWLINE.join(_export_row(admin, state, n, s) for n, s in exports)
    if not exports:
        sent = ('<li class="none">Nothing publishes this yet. '
                '<a href="./new-export">Add an export</a></li>')
    # "nothing written yet" is a long sentence naming a long path, and on
    # this page it is one row among many. The path goes in the title.
    shown = _short(said, 40) if tone == "note" else said
    return f'''
  <section class="flow">
    <div class="made">
      <a class="title" href="./feed:{html.escape(name)}">{html.escape(name)}</a>
      <span class="note">{html.escape(KINDS.get(kind, kind))}</span>
      {where}
      <span class="{tone}" title="{html.escape(said)}"
        >{"switched off" if off else html.escape(shown)}</span>
    </div>
    <ul class="sends">{sent}</ul>
  </section>'''


def overview(admin: Any, message: str = "", error: str = "") -> str:
    feeds, exports, uploads = _rows_for(admin)
    state = adminhome.read(admin)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    said = f'<p class="ok">{html.escape(message)}</p>' if message else ""

    by_feed: dict[str, list] = {name: [] for name in feeds}
    homeless = []
    for name, settings in sorted(exports.items()):
        source = str(settings.get("source") or "").strip()
        if source in by_feed:
            by_feed[source].append((name, settings))
        else:
            homeless.append((name, settings))

    blocks = [_block(admin, state, name, settings, by_feed[name])
              for name, settings in sorted(feeds.items())]
    if not blocks:
        blocks = [('<p class="navempty">No feed is configured, so nothing '
                   'is being written. <a href="./new-feed">Add a feed</a>.'
                   "</p>")]

    loose = ""
    if homeless:
        rows = NEWLINE.join(_export_row(admin, state, n, s)
                            for n, s in homeless)
        loose = f'''
  <section class="flow loose">
    <div class="made"><span class="title">Not tied to a feed</span>
      <span class="note aside">these run on the archive record or on their
      own clock</span></div>
    <ul class="sends">{rows}</ul>
  </section>'''

    posted = ""
    rows = []
    for name, settings in sorted(uploads.items()):
        age, tone = _age(admin, state, name, "upload")
        off = settings.get("enabled") is False
        rows.append(f'''
      <li>
        <a href="./upload:{html.escape(name)}">{html.escape(name)}</a>
        {_chip(str(settings.get("kind") or ""))}
        <span class="{tone}">{"switched off" if off
                              else html.escape(age)}</span>
      </li>''')
    automatic = [one for one in state.uploads
                 if one.name not in uploads]
    for one in automatic:
        rows.append(f'''
      <li><span class="title">{html.escape(one.name)}</span>
        <span class="note">{html.escape(one.detail)}</span>
        <span class="when">{html.escape(adminhome.ago(one.when))}</span></li>''')
    if rows:
        posted = f'''
  <h3 class="sectionhead">Posted to services</h3>
  <p class="lede">An upload sends readings rather than files, so it does not
     wait for a feed. It reads the archive itself.</p>
  <section class="flow">
    <ul class="sends plain">{NEWLINE.join(rows)}</ul>
  </section>'''
    else:
        posted = '''
  <h3 class="sectionhead">Posted to services</h3>
  <p class="navempty">None yet. An upload sends the readings to a weather
     service: Weather Underground, Windy, CWOP, or an MQTT broker.
     <a href="./new-upload">Add an upload</a>.</p>'''

    return f'''
<h2>Publishing</h2>
{problem}{said}
<p class="lede">A feed makes files. An export moves them. They are shown
   together because that is how they run: an export set to "when the feed
   above has finished" starts the moment its feed stops writing.</p>
<div class="actions">
  <a class="button" href="./new-feed">Add a feed</a>
  <a class="button quiet" href="./new-export">Add an export</a>
</div>
{NEWLINE.join(blocks)}
{loose}
{posted}
'''


def nav(admin: Any, active: str) -> list[str]:
    feeds, exports, _uploads = _rows_for(admin)
    current = " aria-current='page'" if active == "publishing" else ""
    # A count of both, because the point of the page is that they are one
    # arrangement. Two numbers under two headings is what it replaces.
    count = f"{len(feeds)}&thinsp;/&thinsp;{len(exports)}"
    return [(f'<a href="./publishing"{current}>Publishing'
             f'<span class="count">{count}</span></a>')]


def feeds_dir(admin: Any) -> Path:
    return config_file.resolved_path(admin.config(), "feeds_dir",
                                     Path(admin.path).parent, "data/feeds")

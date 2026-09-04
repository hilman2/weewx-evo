"""Publishing: the complete output inventory.

A feed makes files. An export moves them. Those are two different things and
the settings page was right to keep the settings apart -- but it also kept
the *listing* apart, so the sidebar had "Feed: wdc" under one heading and
"Export: wdc" under another and nothing anywhere said that the second
publishes the first. The operator held the connection in their head.

The page lists each configured object exactly once, in five fixed sections:

    feeds -> exports
    uploads
    notifications
    forecasts

The connection stays visible in both directions: a feed names its destinations
and a destination names every feed it carries. An incomplete connection stays
in the inventory and says what is missing.

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
from . import language as language_defs

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


def _rows_for(admin: Any) -> tuple[dict, dict, dict, dict, dict]:
    current = admin.config()
    feeds = {n: s for n, s in (current.get("feeds") or {}).items()
             if isinstance(s, dict)}
    exports = {n: s for n, s in (current.get("exports") or {}).items()
               if isinstance(s, dict)}
    uploads = {n: s for n, s in (current.get("uploads") or {}).items()
               if isinstance(s, dict)}
    notifications = {n: s for n, s in (current.get("notify") or {}).items()
                     if isinstance(s, dict)}
    forecasts = {n: s for n, s in (current.get("forecast") or {}).items()
                 if isinstance(s, dict)}
    return feeds, exports, uploads, notifications, forecasts


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


def _first(said: str, keep: int = 58) -> str:
    """A sentence somebody can read at a glance, from the *start*.

    The other way round from `_short`, and the difference matters: on a path
    the end identifies it, and in "cannot reach example.invalid: [Errno -2]
    Name or service not known" the beginning is the whole of what to do next.
    Cut from the front, that row read "…ame or service not known".
    """
    text = " ".join(str(said or "").split())
    if len(text) <= keep:
        return text
    return text[:keep - 1].rstrip(" ,;:") + "…"


def _where(admin: Any, settings: dict) -> str:
    """Where an export puts things, in one short phrase."""
    say = admin.say
    kind = str(settings.get("kind") or "")
    if kind == "local":
        return str(settings.get("directory") or say("a directory"))
    if kind == "ftp":
        host = str(settings.get("host") or "")
        return f"{host}{settings.get('directory') or ''}" if host else "FTP"
    if kind == "rsync":
        host = str(settings.get("host") or "")
        return f"{host}:{settings.get('directory') or ''}" if host else "rsync"
    return kind or say("somewhere")


def _age(admin: Any, state: adminhome.State, name: str,
         which: str) -> tuple[str, str]:
    """(what it says, extra class) for one thing's age."""
    links = {"feed": state.feeds, "export": state.exports,
             "upload": state.uploads, "forecast": state.forecasts}[which]
    for one in links:
        if one.name == name:
            if one.unreachable:
                # A refused login and "has not run yet" are both text in one
                # field, and reading the same as each other is how the first
                # gets missed on a page full of the second.
                return one.unreachable, "warn when" if one.wrong else "note when"
            return adminhome.ago(one.when, admin.language), "when"
    return "", "note when"


def _chip(text: str, tone: str = "", say: Any = None) -> str:
    say = say or str
    return f'<span class="chip {tone}">{html.escape(say(text))}</span>'


def _carried(settings: dict) -> list[tuple[str, str]]:
    """The further feeds an export takes along, as (feed, sub-path).

    Read by the runner's own parser, because two readings of one line is how
    a page comes to show something the process is not doing. Unlike the
    runner, this keeps a name nothing matches: the page is where somebody
    finds out they typed it wrong.
    """
    from .exports import runner as export_runner

    return export_runner.named(settings)


def _status(said: str, tone: str, off: bool = False,
            from_end: bool = False, lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    if off:
        return f'<span class="note when">{html.escape(lang.say("Off"))}</span>'
    if not said:
        return ""
    # Compared against the translated word, because that is what `ago`
    # returned: an English comparison here left a German page printing
    # "nie" where every other row says "Not run".
    shown = (lang.say("Not run") if said == lang.say("never") else
             _short(said, 42) if from_end else _first(said))
    return (f'<span class="{tone}" title="{html.escape(said)}">'
            f'{html.escape(shown)}</span>')


def _feed_names(settings: dict) -> list[str]:
    """Every feed an export sends, once and in configured order."""
    names = []
    source = str(settings.get("source") or "").strip()
    if source:
        names.append(source)
    for feed, _into in _carried(settings):
        if feed not in names:
            names.append(feed)
    return names


def _links(names: list[str], kind: str) -> str:
    return ", ".join(
        f'<a href="./{kind}:{html.escape(name)}">{html.escape(name)}</a>'
        for name in names)


def _place_html(name: str, labels: dict[str, str], lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    if not name:
        return (f'<span class="note warn">'
                f'{html.escape(lang.say("No place selected"))}</span>')
    label = labels.get(name, name)
    return (f'<span class="note">{html.escape(lang.say("Place:"))} '
            f'<a href="./places">{html.escape(label)}</a></span>')


def _feed_row(admin: Any, state: adminhome.State, name: str,
              settings: dict, destinations: list[str], place: str,
              place_labels: dict[str, str]) -> str:
    say, lang = admin.say, admin.language
    kind = str(settings.get("kind") or "")
    said, tone = _age(admin, state, name, "feed")
    sends = (f'<span class="note">{html.escape(say("Destinations:"))} '
             f'{_links(destinations, "export")}</span>' if destinations
             else f'<span class="note">'
                  f'{html.escape(say("No destination"))}</span>')
    return f'''
      <li>
        <a class="title" href="./feed:{html.escape(name)}">{html.escape(name)}</a>
        {_chip(kind)}
        <span class="note">{html.escape(say(KINDS.get(kind, kind)))}</span>
        {_place_html(place, place_labels, lang)}{sends}
        {_status(said, tone, settings.get("enabled") is False,
                 from_end=True, lang=lang)}
      </li>'''


def _export_row(admin: Any, state: adminhome.State, name: str,
                settings: dict) -> str:
    say, lang = admin.say, admin.language
    said, tone = _age(admin, state, name, "export")
    where = _where(admin, settings)
    sources = _feed_names(settings)
    trigger = str(settings.get("trigger") or "feed")
    if sources:
        from_where = (f'<span class="note">{html.escape(say("Feeds:"))} '
                      f'{_links(sources, "feed")}</span>')
    elif trigger == "feed":
        from_where = (f'<span class="note warn">'
                      f'{html.escape(say("No feed selected"))}</span>')
    else:
        from_where = (f'<span class="note">{html.escape(say("Trigger:"))} '
                      f"{html.escape(say(trigger))}</span>")
    return f'''
      <li>
        <a class="title" href="./export:{html.escape(name)}">{html.escape(name)}</a>
        {_chip(str(settings.get("kind") or ""))}
        {from_where}
        <span class="note" title="{html.escape(where)}"
              >{html.escape(say("To:"))} {html.escape(_short(where))}</span>
        {_status(said, tone, settings.get("enabled") is False, lang=lang)}
      </li>'''


def _upload_row(admin: Any, state: adminhome.State, name: str,
                settings: dict, place: str,
                place_labels: dict[str, str]) -> str:
    lang = admin.language
    said, tone = _age(admin, state, name, "upload")
    return f'''
      <li>
        <a class="title" href="./upload:{html.escape(name)}">{html.escape(name)}</a>
        {_chip(str(settings.get("kind") or ""))}
        {_place_html(place, place_labels, lang)}
        {_status(said, tone, settings.get("enabled") is False, lang=lang)}
      </li>'''


def _notification_row(name: str, settings: dict, lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    off = settings.get("enabled") is False
    said = (f'<span class="note when">{html.escape(lang.say("Off"))}</span>'
            if off else "")
    return f'''
      <li>
        <a class="title" href="./notify:{html.escape(name)}">{html.escape(name)}</a>
        {_chip(str(settings.get("kind") or ""))}
        {said}
      </li>'''


def _forecast_row(admin: Any, state: adminhome.State, name: str,
                  settings: dict, place: str,
                  place_labels: dict[str, str]) -> str:
    lang = admin.language
    said, tone = _age(admin, state, name, "forecast")
    return f'''
      <li>
        <a class="title" href="./forecast:{html.escape(name)}">{html.escape(name)}</a>
        {_chip(str(settings.get("kind") or ""))}
        {_place_html(place, place_labels, lang)}
        {_status(said, tone, settings.get("enabled") is False, lang=lang)}
      </li>'''


def _section(name: str, add_href: str, add_label: str,
             rows: list[str], empty: str, lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    body = NEWLINE.join(rows) if rows else (
        f'<li class="none">{html.escape(lang.say(empty))}</li>')
    # The fragment keeps the English, the way `admin.anchor` does: it is a
    # link, and one that moves with the language stops working for everybody
    # who bookmarked it.
    ident = name.lower().replace(" ", "-")
    add = html.escape(lang.fill("Add {what}", what=lang.say(name).lower()))
    return f'''
<section class="publishing-section flow" aria-labelledby="publishing-{ident}">
  <div class="made">
    <h3 class="title" id="publishing-{ident}">
      {html.escape(lang.say(name))}</h3>
    <span class="note">{len(rows)}</span>
    <a class="aside" href="{html.escape(add_href)}"
       aria-label="{add}">{html.escape(lang.say(add_label))}</a>
  </div>
  <ul class="sends plain">{body}</ul>
</section>'''


def overview(admin: Any, message: str = "", error: str = "") -> str:
    say, lang = admin.say, admin.language
    feeds, exports, uploads, notifications, forecasts = _rows_for(admin)
    state = adminhome.read(admin)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    # The banner above the page says it. Printing it a second time in the
    # body was two "Saved." one under the other, which reads as two things
    # having happened.
    said = ""

    place_labels: dict[str, str] = {}
    implicit_place = ""
    try:
        # Kept local: adminarchives imports adminhome, which this module also
        # imports, and doing this at module load would make a cycle.
        from . import adminarchives

        register = adminarchives.load(admin)
        place_labels = {one.name: one.title for one in register.all()}
        implicit_place = register.default_name()
    except LookupError:
        pass
    except Exception:
        log.debug("could not name places on the publishing page",
                  exc_info=True)

    by_feed: dict[str, list[str]] = {name: [] for name in feeds}
    for name, settings in sorted(exports.items()):
        for feed in _feed_names(settings):
            if feed in by_feed:
                by_feed[feed].append(name)

    feed_rows = [
        _feed_row(
            admin, state, name, settings, by_feed[name],
            str(settings.get("archive") or implicit_place).strip(),
            place_labels)
        for name, settings in sorted(feeds.items())]
    export_rows = [
        _export_row(admin, state, name, settings)
        for name, settings in sorted(exports.items())]
    upload_rows = [
        _upload_row(
            admin, state, name, settings,
            str(settings.get("archive") or implicit_place).strip(),
            place_labels)
        for name, settings in sorted(uploads.items())]
    automatic = [one for one in state.uploads
                 if one.name not in uploads]
    for one in automatic:
        last = (adminhome.ago(one.when, lang) if one.when is not None
                else say("Not run"))
        upload_rows.append(f'''
      <li><span class="title">{html.escape(one.name)}</span>
        <span class="chip">{html.escape(say("Automatic"))}</span>
        <span class="note">{html.escape(one.detail)}</span>
        <span class="when">{html.escape(last)}</span></li>''')
    notification_rows = [
        _notification_row(name, settings, lang)
        for name, settings in sorted(notifications.items())]
    forecast_rows = [
        _forecast_row(
            admin, state, name, settings,
            str(settings.get("archive") or implicit_place).strip(),
            place_labels)
        for name, settings in sorted(forecasts.items())]

    return f'''
<h2>{html.escape(say("Publishing"))}</h2>
{problem}{said}
<div class="actions lead">
  <a class="button" href="./new-feed">{html.escape(say("New feed"))}</a>
  <a class="button quiet" href="./charts">{html.escape(say("Charts"))}</a>
  <a class="button quiet" href="./new-export">
    {html.escape(say("New export"))}</a>
  <a class="button quiet" href="./new-upload">
    {html.escape(say("New upload"))}</a>
  <a class="button quiet" href="./new-notify">
    {html.escape(say("New notification"))}</a>
  <a class="button quiet" href="./new-forecast">
    {html.escape(say("New forecast"))}</a>
</div>
{_section("Feeds", "./new-feed", "Add", feed_rows, "No feeds.", lang)}
{_section("Exports", "./new-export", "Add", export_rows, "No exports.", lang)}
{_section("Uploads", "./new-upload", "Add", upload_rows, "No uploads.", lang)}
{_section("Notifications", "./new-notify", "Add", notification_rows,
          "No notifications.", lang)}
{_section("Forecasts", "./new-forecast", "Add", forecast_rows,
          "No forecasts.", lang)}
'''


def nav(admin: Any, active: str) -> list[str]:
    current = " aria-current='page'" if active == "publishing" else ""
    return [(f'<a href="./publishing"{current}>'
             f'{html.escape(admin.say("Publishing"))}</a>')]


def feeds_dir(admin: Any) -> Path:
    return config_file.resolved_path(admin.config(), "feeds_dir",
                                     Path(admin.path).parent, "data/feeds")


def context(admin: Any, active: str) -> str:
    """Where the thing being edited sits in the chain, above its form.

    The Publishing page knows that the `wdc` export publishes the `wdc`
    feed. On the export's own form that was nowhere: a page of FTP settings
    with no hint of what it sends or where those files come from. Somebody
    changing the directory had to hold the arrangement in their head or open
    a second tab.

    One line, both directions, both ends links. Nothing else changes about
    the form.
    """
    if ":" not in active:
        return ""
    say, lang = admin.say, admin.language
    kind, _, name = active.partition(":")
    feeds, exports, uploads, notifications, forecasts = _rows_for(admin)

    if kind == "feed" and name in feeds:
        publishes = [n for n, one in sorted(exports.items())
                     if str(one.get("source") or "") == name]
        if not publishes:
            return _band(
                html.escape(say("Nothing publishes this yet.")),
                f'<a href="./new-export">'
                f'{html.escape(say("Add an export"))}</a>')
        links = ", ".join(
            f'<a href="./export:{html.escape(n)}">{html.escape(n)}</a>'
            for n in publishes)
        return _band(html.escape(say("Published by")) + " " + links, "")

    if kind == "export" and name in exports:
        source = str(exports[name].get("source") or "").strip()
        full = _where(admin, exports[name])
        target = (f'<span title="{html.escape(full)}">'
                  f"{html.escape(_short(full, 44))}</span>")
        into = html.escape(say("into")) + " " + target
        carried = [feed for feed, _into in _carried(exports[name])]
        if source and source in feeds:
            def link(one: str) -> str:
                return (f'<a href="./feed:{html.escape(one)}">'
                        f"{html.escape(one)}</a>")

            named = [link(source)] + [link(one) for one in carried]
            # Named in full rather than "and 2 more": which feeds go up
            # together is the whole of what this export is, and it decides
            # when it runs -- it waits for every one of them.
            joined = (named[0] if len(named) == 1
                      else (", ".join(named[:-1]) + " "
                            + html.escape(say("and")) + " " + named[-1]))
            word = html.escape(say("feed" if len(named) == 1 else "feeds"))
            return _band(f"{html.escape(say('Publishes the'))} {joined} "
                         f"{word}", into)
        return _band(html.escape(say("Not tied to a feed")), into)

    if kind == "upload" and name in uploads:
        reads = str(uploads[name].get("archive") or "").strip()
        where = html.escape(say("the default place"))
        if reads:
            where = f'<a href="./places">{html.escape(reads)}</a>'
        return _band(f"{html.escape(say('Sends readings from'))} {where}",
                     html.escape(say("it does not wait for a feed")))

    if kind == "notify" and name in notifications:
        channel = str(notifications[name].get("kind") or "")
        return _band(html.escape(say("Operational notifications")),
                     html.escape(say(channel)))
    if kind == "forecast" and name in forecasts:
        reads = str(forecasts[name].get("archive") or "").strip()
        where = (f'<a href="./places">{html.escape(reads)}</a>'
                 if reads else html.escape(say("the default place")))
        return _band(f"{html.escape(lang.say('Forecast for'))} {where}", "")
    return ""


def _band(said: str, aside: str) -> str:
    extra = f'<span class="note aside">{aside}</span>' if aside else ""
    return f'''
<section class="flow context">
  <div class="made"><span class="note">{said}</span>{extra}</div>
</section>'''

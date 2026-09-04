"""The small, read-only index for operational and advanced settings.

The primary navigation stays about tasks.  Collector, driver and process
settings are still reachable, but they do not compete with Senders and Places
for the first level of the interface.  This page does not start or control a
service; in particular, the Archiver is only observable through each Place.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Iterable
from typing import Any

log = logging.getLogger(__name__)


def _row(href: str, title: str, detail: str = "", count: int | None = None,
         *, readonly: bool = False, say: Any = None) -> str:
    say = say or str
    title = say(title)
    detail = say(detail) if detail else ""
    meta = []
    if count is not None:
        meta.append(f"{count}")
    if readonly:
        meta.append(say("read-only"))
    aside = (f'<span class="system-row-meta">{html.escape(" · ".join(meta))}</span>'
             if meta else "")
    said = (f'<span class="system-row-detail">{html.escape(detail)}</span>'
            if detail else "")
    return (
        f'<a class="system-row" href="{html.escape(href)}">'
        f'<span><strong>{html.escape(title)}</strong>{said}</span>{aside}</a>'
    )


def _instances(schemas: Iterable[Any], kind: str, sort: bool = True) -> list[Any]:
    found = [schema for schema in schemas if schema.kind == kind]
    return sorted(found, key=lambda schema: schema.label.casefold()) if sort else found


def _instance_rows(schemas: list[Any], empty: str, say: Any = None) -> str:
    say = say or str
    if not schemas:
        return f'<p class="system-empty">{html.escape(say(empty))}</p>'
    return "".join(_row(f"./{schema.name}", schema.label, say=say)
                   for schema in schemas)


def _driver_rows(collectors: list[Any], drivers: list[Any],
                 say: Any = None) -> str:
    """Everything that brings readings in, as one list.

    Two panels before, and the split was ours rather than the reader's: a
    driver that listens on HTTP and one that asks a USB console every minute
    are one thing to somebody with a weather station. What differs is where
    the process runs, and that is worth saying on the row where it is true --
    a driver somebody has to start on another machine is not a setting they
    can save here.
    """
    say = say or str
    if not collectors and not drivers:
        return (f'<p class="system-empty">'
                f'{html.escape(say("No driver settings."))}</p>')

    # "Driver: shed (weewx-driver)" under a heading that already says Drivers
    # is the word twice, and the half in front of the colon is built in
    # `all_schemas`, where there is no language -- so on a German page it was
    # the one English word in the panel. The name is the whole of it here.
    def said(schema: Any) -> str:
        return schema.label.split(": ", 1)[-1]

    out = []
    for schema in collectors:
        # Named for what it is rather than for how it is wired: "runs where
        # the hardware is" is the whole of what a reader needs from the
        # distinction, and it is the half that costs them something.
        out.append(_row(f"./{schema.name}", said(schema),
                        "Runs where the hardware is", say=say))
    for schema in drivers:
        out.append(_row(f"./{schema.name}", said(schema), say=say))
    return "".join(out)


def _addon_rows(admin: Any, say: Any = None) -> str:
    """What is installed, or the sentence a fresh installation needs.

    Its own panel rather than a line under Data flow: what a machine has
    installed is not part of how readings move through it, and the panel it
    was in reads as a list of the station's own data.

    And the empty state is the one that matters. weewx-evo ships no driver,
    so a new installation has nothing that can read an upload -- and a page
    that says "None configured." leaves somebody looking for a setting they
    have not got. This says what to do instead.
    """
    say = say or str
    try:
        from . import addons

        have = addons.installed()
    except Exception:
        log.debug("could not list the add-ons", exc_info=True)
        return ""
    if not have:
        # Built outside the f-string: a line break inside a replacement field
        # needs Python 3.12, and this runs on 3.11.
        empty = say("None. This installation can receive nothing until a "
                    "driver is installed.")
        return f'<p class="system-empty">{html.escape(empty)}</p>'
    return "".join(
        _row("./addons", one.package,
             ", ".join(one.names) or say("a dependency"), say=say)
        for one in have.values())


def overview(admin: Any, message: str = "", error: str = "") -> str:
    say = admin.say
    schemas = list(admin.schemas)
    collectors = _instances(schemas, "collector")
    drivers = _instances(schemas, "driver")
    # Declared order, not alphabetical. Collectors and drivers are named by
    # the operator and there can be any number, so a sort is the only order
    # they have; these are two fixed entries, and the one holding the archive
    # interval belongs at the top of the panel somebody came here to find.
    core = _instances(schemas, "core", sort=False)

    return f'''
<div class="page-head">
  <h2>{html.escape(say("System"))}</h2>
</div>
<div class="system-grid">
  <section class="system-panel">
    <h3>{html.escape(say("Data flow"))}</h3>
    {_row("./senders", "Senders", "Identity and latest readings", say=say)}
    {_row("./places", "Places", "Archive status and configuration", say=say)}
    {_row("./live", "Live database", "Incoming packets", readonly=True,
          say=say)}
    {_row("./quality", "Sensor checks", "Global acceptance rules", say=say)}
  </section>
  <section class="system-panel">
    <div class="system-panel-head"><h3>{html.escape(say("Drivers"))}</h3>
      <a class="small-action" href="./new-collector">
        {html.escape(say("Add"))}</a></div>
    {_driver_rows(collectors, drivers, say)}
  </section>
  <section class="system-panel">
    <h3 class="system-central">
      {html.escape(say("Installation-wide settings"))}</h3>
    {_instance_rows(core, "No installation settings.", say)}
  </section>
  <section class="system-panel">
    <div class="system-panel-head"><h3>{html.escape(say("Add-ons"))}</h3>
      <a class="small-action" href="./addons">
        {html.escape(say("Manage"))}</a></div>
    {_addon_rows(admin, say)}
  </section>
</div>
<section class="system-panel service-boundary">
  <h3>{html.escape(say("Archiver"))}</h3>
  <div class="system-static-row">
    <span>{html.escape(say("Service status is shown on each Place."))}</span>
    <span class="status neutral">{html.escape(say("No controls"))}</span>
  </div>
</section>'''

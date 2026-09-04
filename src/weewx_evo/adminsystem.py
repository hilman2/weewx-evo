"""The small, read-only index for operational and advanced settings.

The primary navigation stays about tasks.  Collector, driver and process
settings are still reachable, but they do not compete with Senders and Places
for the first level of the interface.  This page does not start or control a
service; in particular, the Archiver is only observable through each Place.
"""

from __future__ import annotations

import html
from collections.abc import Iterable
from typing import Any


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
    {_row("./addons", "Add-ons", "Drivers and everything else not shipped",
          say=say)}
  </section>
  <section class="system-panel">
    <div class="system-panel-head"><h3>{html.escape(say("Collectors"))}</h3>
      <a class="small-action" href="./new-collector">
        {html.escape(say("Add"))}</a></div>
    {_instance_rows(collectors, "None configured.", say)}
  </section>
  <section class="system-panel">
    <h3>{html.escape(say("Drivers"))}</h3>
    {_instance_rows(drivers, "No driver settings.", say)}
  </section>
  <section class="system-panel">
    <h3 class="system-central">
      {html.escape(say("Installation-wide settings"))}</h3>
    {_instance_rows(core, "No installation settings.", say)}
  </section>
</div>
<section class="system-panel service-boundary">
  <h3>{html.escape(say("Archiver"))}</h3>
  <div class="system-static-row">
    <span>{html.escape(say("Service status is shown on each Place."))}</span>
    <span class="status neutral">{html.escape(say("No controls"))}</span>
  </div>
</section>'''

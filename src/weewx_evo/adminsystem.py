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
         *, readonly: bool = False) -> str:
    meta = []
    if count is not None:
        meta.append(f"{count}")
    if readonly:
        meta.append("read-only")
    aside = (f'<span class="system-row-meta">{html.escape(" · ".join(meta))}</span>'
             if meta else "")
    said = (f'<span class="system-row-detail">{html.escape(detail)}</span>'
            if detail else "")
    return (
        f'<a class="system-row" href="{html.escape(href)}">'
        f'<span><strong>{html.escape(title)}</strong>{said}</span>{aside}</a>'
    )


def _instances(schemas: Iterable[Any], kind: str) -> list[Any]:
    return sorted((schema for schema in schemas if schema.kind == kind),
                  key=lambda schema: schema.label.casefold())


def _instance_rows(schemas: list[Any], empty: str) -> str:
    if not schemas:
        return f'<p class="system-empty">{html.escape(empty)}</p>'
    return "".join(_row(f"./{schema.name}", schema.label) for schema in schemas)


def overview(admin: Any, message: str = "", error: str = "") -> str:
    schemas = list(admin.schemas)
    collectors = _instances(schemas, "collector")
    drivers = _instances(schemas, "driver")
    core = _instances(schemas, "core")

    return f'''
<div class="page-head">
  <h2>System</h2>
</div>
<div class="system-grid">
  <section class="system-panel">
    <h3>Data flow</h3>
    {_row("./senders", "Senders", "Identity and latest readings")}
    {_row("./places", "Places", "Archive status and configuration")}
    {_row("./live", "Live database", "Incoming packets", readonly=True)}
    {_row("./quality", "Sensor checks", "Global acceptance rules")}
  </section>
  <section class="system-panel">
    <div class="system-panel-head"><h3>Collectors</h3>
      <a class="small-action" href="./new-collector">Add</a></div>
    {_instance_rows(collectors, "None configured.")}
  </section>
  <section class="system-panel">
    <h3>Drivers</h3>
    {_instance_rows(drivers, "No driver settings.")}
  </section>
  <section class="system-panel">
    <h3>Installation</h3>
    {_instance_rows(core, "No installation settings.")}
  </section>
</div>
<section class="system-panel service-boundary">
  <h3>Archiver</h3>
  <div class="system-static-row">
    <span>Service status is shown on each Place.</span>
    <span class="status neutral">No controls</span>
  </div>
</section>'''

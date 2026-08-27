"""The diagnostic feed: draw whatever JSON is there, and say what is wrong.

Deliberately stupid. It does not read the plot definitions, does not know what
a chart is supposed to look like, and has nothing to configure. It walks a
directory, takes every JSON file that has a series in it, draws it, and lists
everything that looks wrong.

That is the whole point. Every other feed renders what it *meant* to produce;
this one renders what actually landed on disk. When a chart on the real site
is empty, the question is whether the data is missing or the template is
wrong, and this answers it in one page.

## Self-contained on purpose

The data is written into the page rather than fetched. One file, no requests,
opens from `file://`, survives being copied to a laptop or attached to a bug
report. uPlot goes in with it -- fifty kilobytes, and then the page works on a
machine that has never had a network.

## What it checks

The things that produce a chart which is technically valid and silently wrong:
parallel arrays of different lengths, timestamps that go backwards, points
outside the span the file claims, a series that is all nulls, a unit on one
line that disagrees with the axis. None of those raise anything anywhere else;
they just draw badly.
"""

from __future__ import annotations

import html
import json
import logging
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

from ...options import Group, Option
from .. import Produced

log = logging.getLogger(__name__)

VENDOR = Path(__file__).parent / "vendor"

#: Files bigger than this are listed but not drawn. A diagnostic page that
#: takes a minute to open is one nobody opens.
BIG = 2_000_000


class Diagnostic:
    """Renders every series file it finds, with its faults listed."""

    trigger = "record"

    def __init__(self, source: Path, title: str = "weewx-evo",
                 draw_limit: int = 400) -> None:
        #: Where to look. Normally what the JSON feed just wrote.
        self.source = Path(source)
        self.title = title
        #: Beyond this many points a series is thinned for drawing. The data
        #: in the page stays whole; only the chart is sampled, because a
        #: hundred thousand points is a black rectangle either way.
        self.draw_limit = draw_limit

    def produce(self, into: Path, now: float | None = None) -> Produced:
        into = Path(into)
        into.mkdir(parents=True, exist_ok=True)

        found = self.read()
        page = self.render(found, now or time.time())
        path = into / "index.html"
        # Written beside and moved into place, like every other file this
        # project writes. Not only so a browser never reads half a page: an
        # export that hard links the result would otherwise be linking the
        # very file being rewritten, and the published page would change
        # underneath whoever is reading it.
        partial = path.with_name(path.name + ".part")
        partial.write_text(page, encoding="utf-8")
        partial.replace(path)

        faults = sum(len(f["faults"]) for f in found)
        note = (f"{len(found)} file(s), {sum(1 for f in found if f['charts'])}"
                f" drawable, {faults} thing(s) to look at")
        log.info("diagnostic page: %s", note)
        return Produced(directory=into, files=[path], note=note)

    # -- reading -----------------------------------------------------------

    def read(self) -> list[dict[str, Any]]:
        """Every JSON file in the source directory, examined."""
        out = []
        if not self.source.is_dir():
            return out
        for path in sorted(self.source.glob("*.json")):
            entry: dict[str, Any] = {
                "name": path.name,
                "size": path.stat().st_size,
                "faults": [],
                "charts": [],
                "raw": None,
                "meta": {},
            }
            try:
                text = path.read_text(encoding="utf-8")
                payload = json.loads(text)
            except (OSError, ValueError) as exc:
                entry["faults"].append(f"could not be read: {exc}")
                out.append(entry)
                continue

            entry["raw"] = payload
            if entry["size"] > BIG:
                entry["faults"].append(
                    f"{entry['size'] / 1e6:.1f} MB -- listed but not drawn")
                out.append(entry)
                continue

            if isinstance(payload, dict) and "series" in payload:
                self._examine(entry, payload)
            elif isinstance(payload, dict) and "plots" in payload:
                entry["meta"]["kind"] = "manifest"
                entry["meta"]["plots"] = len(payload.get("plots") or [])
            else:
                entry["meta"]["kind"] = "not a series file"
            out.append(entry)
        return out

    def _examine(self, entry: dict[str, Any], payload: dict) -> None:
        """Pull out what can be drawn, and note what cannot."""
        faults = entry["faults"]
        start = payload.get("start")
        stop = payload.get("stop")
        unit = payload.get("unit")
        entry["meta"] = {
            "kind": "series",
            "span": _span(start, stop),
            "unit": unit,
            "unit_label": payload.get("unit_label"),
            "generated": payload.get("generated"),
            "daynight": bool(payload.get("daynight")),
            "format": payload.get("format"),
        }
        if payload.get("daynight"):
            bands = payload["daynight"]
            entry["meta"]["transitions"] = len(bands.get("transitions") or [])

        series = payload.get("series")
        if not isinstance(series, list) or not series:
            faults.append("no series in it")
            return

        for line in series:
            name = line.get("obs_type", "?")
            times = line.get("time")
            values = line.get("values")
            if not isinstance(times, list) or not isinstance(values, list):
                faults.append(f"{name}: time or values is not a list")
                continue
            if len(times) != len(values):
                faults.append(f"{name}: {len(times)} timestamps against "
                              f"{len(values)} values")
                continue
            if not times:
                faults.append(f"{name}: nothing in it")
                continue

            # The faults that draw a chart rather than raising anything.
            if all(v is None for v in values):
                faults.append(f"{name}: every value is null")
            if any(b <= a for a, b in pairwise(times)):
                faults.append(f"{name}: the timestamps do not always go "
                              f"forwards")
            if start is not None and stop is not None:
                outside = sum(1 for t in times if t < start or t > stop)
                if outside:
                    faults.append(f"{name}: {outside} point(s) outside the "
                                  f"span the file claims")
            if line.get("unit") and unit and line["unit"] != unit:
                faults.append(f"{name}: in {line['unit']} while the axis says "
                              f"{unit}")
            for parallel in ("directions", "bar_width", "vector_x", "vector_y"):
                other = line.get(parallel)
                if isinstance(other, list) and len(other) != len(values):
                    faults.append(f"{name}: {parallel} has {len(other)} "
                                  f"entries against {len(values)} values")

            entry["charts"].append({
                "label": line.get("label") or name,
                "obs": name,
                "kind": line.get("plot_type", "line"),
                "color": line.get("color") or "",
                "aggregate": line.get("aggregate_type") or "",
                "interval": line.get("aggregate_interval"),
                "n": len(values),
                "nulls": sum(1 for v in values if v is None),
                "time": times,
                "values": values,
            })

    # -- writing -----------------------------------------------------------

    def render(self, found: list[dict[str, Any]], now: float) -> str:
        drawable = [f for f in found if f["charts"]]
        faults = sum(len(f["faults"]) for f in found)
        total = sum(f["size"] for f in found)

        blocks = []
        for entry in found:
            blocks.append(self._block(entry))

        payload = json.dumps(
            [{"name": e["name"],
              "daynight": (e["raw"] or {}).get("daynight"),
              "charts": [
                  {k: v for k, v in c.items()
                   if k in ("label", "obs", "kind", "color", "time", "values")}
                  for c in self._thinned(e["charts"])]}
             for e in found if e["charts"]],
            separators=(",", ":"), ensure_ascii=False)

        return _PAGE.format(
            title=html.escape(self.title),
            uplot_css=_read(VENDOR / "uPlot.min.css"),
            uplot_js=_read(VENDOR / "uPlot.iife.min.js"),
            when=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            source=html.escape(str(self.source)),
            counts=(f"{len(found)} file(s), {len(drawable)} with series, "
                    f"{total / 1024:.0f} KB"),
            faults=faults,
            fault_class="bad" if faults else "good",
            blocks="\n".join(blocks),
            data=payload,
        )

    def _thinned(self, charts: list[dict]) -> list[dict]:
        """The same charts, sampled down to something a browser can draw."""
        out = []
        for chart in charts:
            step = max(1, len(chart["values"]) // self.draw_limit)
            if step == 1:
                out.append(chart)
                continue
            thinned = dict(chart)
            thinned["time"] = chart["time"][::step]
            thinned["values"] = chart["values"][::step]
            out.append(thinned)
        return out

    def _block(self, entry: dict[str, Any]) -> str:
        meta = entry["meta"]
        bits = [f"{entry['size'] / 1024:.1f} KB"]
        if meta.get("kind") and meta["kind"] != "series":
            bits.append(meta["kind"])
        if meta.get("span"):
            bits.append(meta["span"])
        if meta.get("unit"):
            bits.append(str(meta["unit"]))
        if meta.get("daynight"):
            bits.append(f"{meta.get('transitions', 0)} day/night crossing(s)")
        if meta.get("plots") is not None:
            bits.append(f"{meta['plots']} plot(s) listed")

        rows = []
        for chart in entry["charts"]:
            note = []
            if chart["aggregate"]:
                note.append(f"{chart['aggregate']} per {chart['interval']}")
            if chart["nulls"]:
                note.append(f"{chart['nulls']} null")
            rows.append(
                f'<tr><td><span class="swatch" style="background:'
                f'{html.escape(chart["color"] or "#888")}"></span>'
                f'{html.escape(chart["obs"])}</td>'
                f'<td>{html.escape(chart["kind"])}</td>'
                f'<td class="n">{chart["n"]}</td>'
                f'<td>{html.escape(", ".join(note))}</td></tr>')

        faults = "".join(
            f'<li>{html.escape(f)}</li>' for f in entry["faults"])
        raw = html.escape(json.dumps(entry["raw"], indent=1, ensure_ascii=False)
                          [:200000]) if entry["raw"] is not None else ""

        return _BLOCK.format(
            name=html.escape(entry["name"]),
            slug=html.escape(entry["name"].replace(".", "-")),
            bits=html.escape(" &middot; ".join(bits)).replace(
                "&amp;middot;", "&middot;"),
            chart=(f'<div class="chart" data-file='
                   f'"{html.escape(entry["name"])}"></div>')
            if entry["charts"] else "",
            table=("<table><thead><tr><th>reading</th><th>as</th>"
                   "<th class='n'>points</th><th></th></tr></thead><tbody>"
                   + "".join(rows) + "</tbody></table>") if rows else "",
            faults=(f'<ul class="faults">{faults}</ul>' if faults else ""),
            fault_count=len(entry["faults"]),
            fault_class="bad" if entry["faults"] else "good",
            raw=raw,
        )

    @staticmethod
    def options() -> list:
        """The settings one of these offers. Bare names; the page prefixes."""
        from ...options import defined_feeds

        return [
            Group("Diagnostics",
                  "One page that draws whatever JSON is on disk.", (
                      Option("enabled", "Produce the page", kind="bool",
                             default=True,
                             help="A single self-contained HTML file that "
                                  "draws every series file and lists what "
                                  "looks wrong in them. Costs one file and "
                                  "answers 'is it the data or the template' "
                                  "without a second thought."),
                      Option("source", "Draw what this feed wrote",
                             kind="choice", default="json",
                             choices=(("", "-- a directory instead --"),),
                             choices_from=defined_feeds,
                             help="Which feed's output to read. Normally the "
                                  "JSON one."),
                      Option("destination", "Directory", default="",
                             advanced=True,
                             help="Under the feed output directory. Empty "
                                  "means a directory named after this feed."),
                      Option("points", "Points drawn per series", kind="int",
                             default=400, minimum=50, maximum=20000,
                             advanced=True,
                             help="The chart is sampled down to this; the "
                                  "data in the page stays whole. A hundred "
                                  "thousand points is a black rectangle "
                                  "either way."),
                  )),
        ]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        log.error("the diagnostic page needs %s, which is not there", path)
        return ""


def _span(start: Any, stop: Any) -> str:
    if not isinstance(start, (int, float)) or not isinstance(stop, (int, float)):
        return ""
    length = stop - start
    for seconds, name in ((31536000, "year"), (2592000, "month"),
                          (604800, "week"), (86400, "day"), (3600, "hour")):
        if length >= seconds * 0.9:
            return f"{length / seconds:.0f} {name}(s)"
    return f"{length:.0f}s"


def from_settings(settings: Any, source: Path,
                  prefix: str = "feeds.diagnostic") -> Diagnostic:
    """Build the page from the configuration.

    `prefix` names the configured feed. Two of them can draw two different
    directories -- one per data set -- without either knowing about the
    other.
    """
    points = settings.get(f"{prefix}.points")
    return Diagnostic(
        source=source,
        title=str(settings.get("station.name") or "weewx-evo"),
        draw_limit=int(points or 400),
    )


_BLOCK = """
<section id="{slug}">
  <h2>{name} <span class="pill {fault_class}">{fault_count}</span></h2>
  <p class="bits">{bits}</p>
  {faults}
  {chart}
  {table}
  <details><summary>the file itself</summary><pre>{raw}</pre></details>
</section>
"""

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} &mdash; diagnostics</title>
<style>{uplot_css}</style>
<style>
  :root {{ --bg:#fbfaf8; --panel:#fff; --line:#e5e1da; --ink:#1d1b18;
          --dim:#6f6a62; --accent:#2f6f4e; --bad:#a8321f; --good:#2f6f4e; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#17161a; --panel:#1f1e23; --line:#322f38; --ink:#eceaf0;
            --dim:#9a94a3; --accent:#79c79b; --bad:#e8836f; --good:#79c79b; }}
  }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .wrap {{ max-width:64rem; margin:0 auto; padding:2rem 1.25rem 6rem; }}
  header {{ border-bottom:1px solid var(--line); padding-bottom:1rem;
           margin-bottom:1.5rem; }}
  h1 {{ font-size:1.15rem; margin:0 0 .35rem; font-weight:600; }}
  h2 {{ font-size:.95rem; margin:0 0 .2rem; font-weight:600;
       font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
  .sub, .bits {{ color:var(--dim); font-size:.8125rem; margin:0 0 .75rem; }}
  section {{ background:var(--panel); border:1px solid var(--line);
            border-radius:.5rem; padding:1rem 1.1rem; margin-bottom:.9rem; }}
  .chart {{ margin:.5rem 0 .75rem; }}
  table {{ border-collapse:collapse; width:100%; font-size:.8125rem; }}
  th {{ text-align:left; color:var(--dim); font-weight:500;
       border-bottom:1px solid var(--line); padding:.25rem .5rem .25rem 0; }}
  td {{ padding:.25rem .5rem .25rem 0; border-bottom:1px solid var(--line);
       color:var(--dim); }}
  td:first-child {{ color:var(--ink);
       font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
  .n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .swatch {{ display:inline-block; width:.6rem; height:.6rem;
            border-radius:.15rem; margin-right:.4rem; vertical-align:middle; }}
  .pill {{ font-size:.6875rem; padding:.05rem .4rem; border-radius:1rem;
          vertical-align:middle; font-family:system-ui,sans-serif; }}
  .pill.good {{ background:color-mix(in srgb, var(--good) 15%, transparent);
               color:var(--good); }}
  .pill.bad {{ background:color-mix(in srgb, var(--bad) 18%, transparent);
              color:var(--bad); }}
  .faults {{ margin:.4rem 0 .8rem; padding-left:1.1rem; color:var(--bad);
            font-size:.8125rem; }}
  details {{ margin-top:.6rem; }}
  summary {{ cursor:pointer; color:var(--dim); font-size:.8125rem; }}
  pre {{ overflow-x:auto; background:var(--bg); border:1px solid var(--line);
        border-radius:.35rem; padding:.6rem; font-size:.75rem;
        max-height:24rem; }}
  .u-legend {{ font-size:.75rem; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{title} &mdash; what is actually on disk</h1>
  <p class="sub">{counts} in <code>{source}</code>, read {when}.
     <span class="pill {fault_class}">{faults} thing(s) to look at</span></p>
</header>
{blocks}
</div>
<script>{uplot_js}</script>
<script>
const DATA = {data};

// Deliberately plain: one chart per file, every series in it, no styling
// decisions beyond the colours the file already carries. This page is here to
// show what the data is, not to look like the site.
function draw(host, entry) {{
  const charts = entry.charts.filter(c => c.time.length);
  if (!charts.length) return;

  // One shared time axis. The series in a file are drawn over the same span,
  // so the union of their timestamps is the x axis; anything a series has no
  // value at becomes a gap, which is what it is.
  const stamps = [...new Set(charts.flatMap(c => c.time))].sort((a, b) => a - b);
  const index = new Map(stamps.map((t, i) => [t, i]));
  const columns = [stamps];
  for (const c of charts) {{
    const column = new Array(stamps.length).fill(null);
    c.time.forEach((t, i) => {{ column[index.get(t)] = c.values[i]; }});
    columns.push(column);
  }}

  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const grid = dark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.07)';
  const ink = dark ? '#9a94a3' : '#6f6a62';

  // Night, from the file's own day/night data. Drawn here because a
  // temperature curve is hard to read without it -- and because seeing the
  // bands land where dusk actually was is the only check on that data there
  // is.
  const bands = entry.daynight;
  const shade = (u) => {{
    if (!bands || !bands.transitions || !bands.transitions.length) return;
    const ctx = u.ctx;
    const edges = [u.scales.x.min, ...bands.transitions, u.scales.x.max];
    // 'first' says which side of the horizon the span opens on; every
    // crossing after that flips it.
    let night = bands.first === 'night';
    ctx.save();
    ctx.fillStyle = dark ? 'rgba(255,255,255,.045)' : 'rgba(0,0,0,.045)';
    for (let i = 0; i < edges.length - 1; i++) {{
      if (night) {{
        const a = u.valToPos(Math.max(edges[i], u.scales.x.min), 'x', true);
        const b = u.valToPos(Math.min(edges[i + 1], u.scales.x.max), 'x', true);
        ctx.fillRect(a, u.bbox.top, b - a, u.bbox.height);
      }}
      night = !night;
    }}
    ctx.restore();
  }};

  // uPlot groups thousands by locale, so 1016 mbar comes out as "1.016" on a
  // German machine and reads as one point nought one six. A pressure axis
  // must not do that.
  const plain = (u, splits) => splits.map(v =>
    v == null ? '' : (Math.abs(v) >= 1000
      ? v.toFixed(Math.abs(v) % 1 ? 1 : 0)
      : String(+v.toFixed(3))));

  const opts = {{
    width: host.clientWidth || 800,
    height: 200,
    cursor: {{ y: false }},
    legend: {{ live: true }},
    hooks: {{ drawClear: [shade] }},
    axes: [
      {{ stroke: ink, grid: {{ stroke: grid }}, ticks: {{ stroke: grid }} }},
      {{ stroke: ink, grid: {{ stroke: grid }}, ticks: {{ stroke: grid }},
         values: plain }},
    ],
    series: [
      {{}},
      ...charts.map(c => ({{
        label: c.label || c.obs,
        stroke: c.color || '#4282b4',
        width: 1.5,
        // A bar series is drawn as steps rather than as bars: this is a
        // diagnostic, and the shape of the data matters more than the shape
        // of the chart.
        paths: c.kind === 'bar' ? uPlot.paths.stepped({{align: 1}}) : undefined,
        points: {{ show: stamps.length < 40 }},
        spanGaps: false,
      }})),
    ],
  }};
  const plot = new uPlot(opts, columns, host);
  addEventListener('resize', () => plot.setSize(
    {{ width: host.clientWidth, height: 200 }}));
}}

for (const entry of DATA) {{
  const host = document.querySelector(
    '.chart[data-file="' + CSS.escape(entry.name) + '"]');
  if (host) {{
    try {{ draw(host, entry); }}
    catch (e) {{
      // A file this page cannot draw is itself a finding. Say so where the
      // chart would have been rather than failing silently in the console.
      host.innerHTML = '<p class="faults">could not be drawn: '
        + String(e) + '</p>';
    }}
  }}
}}
</script>
</body>
</html>
"""

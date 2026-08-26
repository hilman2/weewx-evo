"""The charts, in the settings page.

Plots do not fit the form generator the rest of the settings use, and forcing
them into it would be worse than writing this. A setting is one named value;
a plot is a record with a list of records inside it, and there are a hundred
of them. So this is the one part of the page written by hand.

What it has to be better at than a text editor, or there is no point:

  * showing which readings a chart draws without opening the file
  * adding a reading with the aggregation that suits the span, chosen from
    what the database actually has rather than typed from memory
  * saying, before you save, that `outTmep` is not a column
  * bringing a hundred charts over from an old skin in one go

The file stays authoritative and hand-editable. This writes the same TOML a
person would.
"""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any

from . import plots as plot_defs
from .options import format_duration, parse_duration
from .series import AGGREGATES

log = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z][a-z0-9_-]*$")

#: What a line can be drawn as, and what that means.
KINDS = (("line", "line -- a value at each moment"),
         ("bar", "bar -- a total per bucket"),
         ("vector", "vector -- an arrow per reading, for wind"))

#: The aggregates worth offering. The full list in `series.AGGREGATES` has
#: several that only make sense to a program.
USEFUL = (("", "none -- the archive records themselves"),
          ("avg", "average"), ("min", "lowest"), ("max", "highest"),
          ("sum", "total"), ("count", "how many readings"),
          ("rms", "root mean square"), ("vecavg", "vector average (wind)"),
          ("vecdir", "vector direction (wind)"),
          ("gustdir", "direction of the strongest gust"),
          ("first", "first"), ("last", "last"),
          ("mintime", "when the lowest was"),
          ("maxtime", "when the highest was"),
          ("diff", "change across the bucket"),
          ("tderiv", "rate of change"))

#: Bucket sizes, largest first where they are calendar units.
INTERVALS = (("", "one bucket per record"),
             ("hour", "hourly"), ("day", "daily"), ("week", "weekly"),
             ("month", "monthly"), ("year", "yearly"),
             ("900", "every 15 minutes"), ("1800", "every half hour"),
             ("10800", "every 3 hours"), ("21600", "every 6 hours"))

#: How far back a chart reaches. Named, because "97200" is not a decision
#: anybody makes on purpose.
LENGTHS = (("27h", "a day and the night before it"),
           ("48h", "two days"), ("7d", "a week"), ("30d", "a month"),
           ("90d", "three months"), ("365d", "a year"), ("1825d", "five years"))

#: When to leave a chart out entirely.
EMPTY = (("", "always produce it"),
         ("day", "not if there is nothing in a day"),
         ("week", "not if there is nothing in a week"),
         ("month", "not if there is nothing in a month"),
         ("year", "not if there is nothing in a year -- this station has no "
                  "such sensor"))


# -- what the admin object does -------------------------------------------

def path_for(admin: Any) -> Path:
    """Where plots.toml lives: beside the configuration."""
    return Path(admin.path).parent / "plots.toml"


def load(admin: Any) -> plot_defs.PlotSet:
    return plot_defs.load(path_for(admin))


def store(admin: Any, charts: plot_defs.PlotSet, note: str = "") -> str:
    """Write them. Returns an error, or empty if it worked."""
    if admin.read_only:
        return "This settings page was started read-only."
    try:
        plot_defs.save(path_for(admin), charts, note)
    except Exception as exc:  # noqa: BLE001
        log.exception("could not write the plots")
        return f"Could not write {path_for(admin)}: {exc}"
    return ""


def add(admin: Any, name: str, span: str, obs: str) -> str:
    """A new chart with one reading in it. Everything else on the next page."""
    name = (name or "").strip().lower()
    if not NAME.match(name):
        return ("A name may hold lowercase letters, digits, - and _, and must "
                "start with a letter. It becomes the filename.")
    charts = load(admin)
    if charts.get(name):
        return f"There is already a chart called {name!r}."
    span = (span or "day").strip().lower()
    obs = (obs or "").strip()
    if not obs:
        return "Say which reading to draw. One is enough to start with."

    charts.add(plot_defs.Plot(
        name=name, span=span,
        time_length=plot_defs.SPANS.get(span, 97200),
        lines=[plot_defs.Line(obs=obs)],
        # A day chart is the only one narrow enough for the shading to mean
        # anything; on a year of daily averages it is a grey smear.
        show_daynight=span == "day",
        skip_if_empty="year"))
    return store(admin, charts)


def remove(admin: Any, name: str) -> str:
    charts = load(admin)
    if not charts.remove(name):
        return f"There is no chart called {name!r}."
    return store(admin, charts)


def save(admin: Any, name: str, form: dict[str, Any],
         columns: set[str]) -> dict[str, str]:
    """Everything about one chart, from its form. Errors keyed by field."""
    charts = load(admin)
    plot = charts.get(name)
    if plot is None:
        return {"": f"There is no chart called {name!r}."}

    errors: dict[str, str] = {}
    span = (form.get("span") or plot.span).strip().lower()
    try:
        length = parse_duration((form.get("time_length") or "27h").strip())
    except Exception:
        errors["time_length"] = ("Not a length of time. Try 27h, 7d or 365d."
                                 " A bare number is seconds.")
        length = plot.time_length

    yscale: list[Any] = []
    for key in ("ymin", "ymax", "ystep"):
        raw = (form.get(key) or "").strip()
        if not raw:
            yscale.append(None)
            continue
        try:
            yscale.append(float(raw))
        except ValueError:
            errors[key] = f"{raw!r} is not a number."
            yscale.append(None)
    if yscale[0] is not None and yscale[1] is not None \
            and yscale[0] >= yscale[1]:
        errors["ymax"] = "The top of the axis has to be above the bottom."

    lines = []
    for index in range(_count(form)):
        obs = (form.get(f"line{index}_obs") or "").strip()
        if not obs or form.get(f"line{index}_delete"):
            continue
        if obs not in columns and obs not in plot_defs_vectors():
            # Named, not refused. A column can appear later -- a sensor
            # arrives, a driver starts sending a field -- and a chart written
            # ahead of it should not be impossible to save.
            errors[f"line{index}_obs"] = (
                f"The archive has no column called {obs!r}. Saved anyway; the "
                "chart will be empty until something writes one.")
        aggregate = (form.get(f"line{index}_aggregate") or "").strip()
        if aggregate and aggregate not in AGGREGATES:
            errors[f"line{index}_aggregate"] = f"{aggregate!r} is not an aggregate."
            aggregate = ""
        interval = (form.get(f"line{index}_interval") or "").strip()
        lines.append(plot_defs.Line(
            obs=obs,
            label=(form.get(f"line{index}_label") or "").strip(),
            kind=(form.get(f"line{index}_kind") or "line").strip(),
            color=(form.get(f"line{index}_color") or "").strip(),
            aggregate=aggregate,
            interval=plot_defs._interval(interval) if interval else None,
        ))

    new_obs = (form.get("new_obs") or "").strip()
    if new_obs:
        lines.append(plot_defs.Line(obs=new_obs))

    if not lines:
        errors[""] = "A chart needs at least one reading in it."
        return errors
    # Everything that is only a warning still saves. Only a refusal stops it.
    hard = {k for k in errors if k in ("", "time_length", "ymax", "ymin",
                                       "ystep")}
    if hard:
        return errors

    plot.span = span
    plot.time_length = length
    plot.title = (form.get("title") or "").strip()
    plot.show_daynight = bool(form.get("show_daynight"))
    plot.skip_if_empty = (form.get("skip_if_empty") or "").strip()
    plot.yscale = yscale
    plot.lines = lines

    problem = store(admin, charts)
    if problem:
        return {"": problem}
    return {k: v for k, v in errors.items()}


def plot_defs_vectors() -> set[str]:
    from .series import VECTORS

    return set(VECTORS)


def _count(form: dict[str, Any]) -> int:
    """How many line rows the form carried."""
    highest = -1
    for key in form:
        match = re.match(r"^line(\d+)_", key)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def bring_over(admin: Any, source: str, replace: bool,
               text: str = "", origin: str = "the uploaded file") -> tuple[str, str]:
    """Import from a WeeWX skin. Returns (message, error).

    From a file that was uploaded, from text that was pasted, or from a path
    on this machine. The path is the least useful of the three and is offered
    last: run weewx-evo in a container and the skin is in a different one,
    with no path that reaches it from here.
    """
    from . import weewxconf

    source = (source or "").strip()
    text = text or ""
    if text.strip():
        where = origin
        try:
            conf = weewxconf.parse(text)
        except Exception as exc:  # noqa: BLE001
            return "", f"That could not be read as a skin.conf: {exc}"
    elif source:
        where = source
        try:
            conf = weewxconf.read(source)
        except OSError as exc:
            return "", f"Cannot read {source}: {exc}"
    else:
        return "", ("Choose a file, paste one in, or give a path on this "
                    "machine.")

    section = conf.get("ImageGenerator")
    if not isinstance(section, dict):
        inside = [k for k, v in conf.items()
                  if isinstance(v, dict) and "ImageGenerator" in v]
        if inside:
            return "", (f"No [ImageGenerator] at the top of {where}. It is "
                        f"inside: {', '.join(inside)}.")
        return "", (f"No [ImageGenerator] section in {where}. Charts live in "
                    "a skin's own skin.conf, not in weewx.conf.")

    found = plot_defs.from_image_generator(section,
                                           plot_defs.labels_from(conf))
    if not len(found.plots):
        return "", f"Nothing that looked like a chart in {where}."

    charts = found.plots if replace else load(admin)
    added = kept = 0
    if not replace:
        for plot in found.plots:
            if charts.get(plot.name) is None:
                charts.add(plot)
                added += 1
            else:
                kept += 1
        charts.labels.update({k: v for k, v in found.plots.labels.items()
                              if k not in charts.labels})
    else:
        added = len(charts)

    problem = store(admin, charts, f"Imported from {where}.")
    if problem:
        return "", problem

    said = f"Took {added} chart(s) from {where}."
    if kept:
        said += f" {kept} were already here and were left alone."
    if found.drawing:
        said += (f" {len(found.drawing)} option(s) about drawing a picture "
                 "were left behind.")
    return said, ""


# -- rendering -------------------------------------------------------------

def nav(admin: Any, active: str) -> list[str]:
    """The charts, in the sidebar, grouped the way they are grouped."""
    charts = load(admin)
    out = ['<p class="navhead">Charts</p>']
    if not len(charts):
        out.append('<p class="navempty">None yet. Add one, or bring a whole '
                   'set over from an existing WeeWX skin.</p>')

    groups = charts.by_span()
    # An imported Seasons skin is a hundred charts. Flat, that is a sidebar
    # nobody can find anything in; collapsed, it is four lines. The group
    # holding the chart being edited opens itself, so following a link never
    # loses your place.
    for span in sorted(groups):
        group = groups[span]
        holding = any(f"plot:{p.name}" == active for p in group)
        out.append(f'<details class="navgroup"{" open" if holding else ""}>')
        out.append(f'<summary>{html.escape(span)}'
                   f'<span class="count">{len(group)}</span></summary>')
        for plot in group:
            key = f"plot:{plot.name}"
            current = " aria-current='page'" if key == active else ""
            out.append(f'<a class="sub" href="./{html.escape(key)}"{current}>'
                       f"{html.escape(plot.name)}</a>")
        out.append("</details>")

    if not admin.read_only:
        current = " aria-current='page'" if active == "new-plot" else ""
        out.append(f'<a class="add" href="./new-plot"{current}>+ Add a chart</a>')
        current = " aria-current='page'" if active == "import-plots" else ""
        out.append(f'<a class="add" href="./import-plots"{current}>'
                   "+ Import from a skin</a>")
    return out


def _select(name: str, options: tuple, value: Any, extra: str = "") -> str:
    rows = []
    seen = False
    for key, label in options:
        chosen = str(key) == str(value if value is not None else "")
        seen = seen or chosen
        rows.append(f'<option value="{html.escape(str(key))}"'
                    f'{" selected" if chosen else ""}>'
                    f"{html.escape(str(label))}</option>")
    if not seen and value not in (None, ""):
        # Whatever is in the file, even if this page would not have offered
        # it. Losing somebody's hand-written setting by rendering a form is
        # the worst thing a settings page can do.
        rows.insert(0, f'<option value="{html.escape(str(value))}" selected>'
                       f"{html.escape(str(value))} (from the file)</option>")
    return (f'<select name="{html.escape(name)}" {extra}>'
            + "".join(rows) + "</select>")


def edit(admin: Any, name: str, columns: set[str], errors: dict[str, str],
         form: dict[str, Any] | None = None) -> str:
    """One chart's page."""
    charts = load(admin)
    plot = charts.get(name)
    if plot is None:
        return ('<section class="group"><h3>Not here</h3>'
                f'<p class="lede">There is no chart called '
                f'{html.escape(name)}.</p></section>')

    def err(key: str) -> str:
        return (f'<p class="err">{html.escape(errors[key])}</p>'
                if key in errors else "")

    spans = tuple((s, s) for s in sorted(
        set(plot_defs.SPANS) | {p.span for p in charts}))
    known = sorted(columns | plot_defs_vectors())
    datalist = ("<datalist id='readings'>"
                + "".join(f'<option value="{html.escape(c)}">' for c in known)
                + "</datalist>")

    rows = []
    for index, line in enumerate(plot.lines):
        prefix = f"line{index}"
        rows.append(f'''
    <fieldset class="line">
      <legend>{html.escape(line.obs)}</legend>
      <div class="row">
        <label>Reading
          <input name="{prefix}_obs" list="readings"
                 value="{html.escape(line.obs)}" required>
        </label>
        <label>Called
          <input name="{prefix}_label" value="{html.escape(line.label)}"
                 placeholder="{html.escape(charts.labels.get(line.obs, line.obs))}">
        </label>
        <label>Drawn as
          {_select(f"{prefix}_kind", KINDS, line.kind)}
        </label>
        <label>Colour
          <input type="color" name="{prefix}_color"
                 value="{html.escape(line.resolved(index).color or '#4282b4')}">
        </label>
      </div>
      <div class="row">
        <label>Reduced by
          {_select(f"{prefix}_aggregate", USEFUL, line.aggregate)}
        </label>
        <label>Per
          {_select(f"{prefix}_interval", INTERVALS,
                   "" if line.interval is None else line.interval)}
        </label>
        <label class="tick">
          <input type="checkbox" name="{prefix}_delete" value="1">
          Remove this reading
        </label>
      </div>
      {err(f"{prefix}_obs")}{err(f"{prefix}_aggregate")}
    </fieldset>''')

    checked = " checked" if plot.show_daynight else ""
    return f'''
<section class="group">
  <h3>{html.escape(plot.name)}</h3>
  <p class="lede">Written as <code>{html.escape(plot.name)}.json</code>, and
     drawn by whatever reads it.</p>
  <form method="post" action="./plot:{html.escape(plot.name)}">
  {datalist}
  <div class="row">
    <label>Group
      {_select("span", spans, plot.span)}
      <span class="hint">Only for grouping and for the manifest. The length
        below is what decides how far back it reaches.</span>
    </label>
    <label>Reaches back
      <input name="time_length" list="lengths"
             value="{html.escape(format_duration(plot.time_length))}">
      <datalist id="lengths">
        {"".join(f'<option value="{v}">{html.escape(l)}</option>'
                 for v, l in LENGTHS)}
      </datalist>
      <span class="hint">27h on a day chart, so last night is still on it.</span>
      {err("time_length")}
    </label>
    <label>Title
      <input name="title" value="{html.escape(plot.title)}"
             placeholder="built from the readings">
    </label>
  </div>
  <div class="row">
    <label>Leave out when empty
      {_select("skip_if_empty", EMPTY, plot.skip_if_empty)}
      <span class="hint">A sensor with nothing in a year is one this station
        does not have; one with nothing today is having a bad day. The first
        should vanish, the second should stay.</span>
    </label>
    <label class="tick">
      <input type="checkbox" name="show_daynight" value="1"{checked}>
      Shade the hours of darkness
      <span class="hint">Worth it on a day or a week. On a year it is a grey
        smear.</span>
    </label>
  </div>
  <div class="row narrow">
    <label>Axis from
      <input name="ymin" value="{_num(plot.yscale[0])}" placeholder="auto">
      {err("ymin")}
    </label>
    <label>to
      <input name="ymax" value="{_num(plot.yscale[1])}" placeholder="auto">
      {err("ymax")}
    </label>
    <label>smallest step
      <input name="ystep" value="{_num(plot.yscale[2])}" placeholder="auto">
      <span class="hint">Fixing an axis is how two charts stay comparable.</span>
      {err("ystep")}
    </label>
  </div>

  <h4>Readings</h4>
  {"".join(rows)}

  <fieldset class="line add">
    <legend>Add one</legend>
    <div class="row">
      <label>Reading
        <input name="new_obs" list="readings" placeholder="outTemp">
        <span class="hint">{len(known)} to choose from, taken from the
          archive itself.</span>
      </label>
    </div>
  </fieldset>

  <div class="actions"><button type="submit">Save</button></div>
  </form>
</section>

<section class="group danger">
  <h3>Remove</h3>
  <p class="lede">Takes {html.escape(plot.name)} out of plots.toml. Files it
     has already written are left where they are.</p>
  <form method="post" action="./plot:{html.escape(plot.name)}/remove"
        onsubmit="return confirm('Remove the chart {html.escape(plot.name)}?')">
    <div class="actions"><button class="warn" type="submit">Remove</button></div>
  </form>
</section>'''


def new(admin: Any, columns: set[str], error: str = "",
        form: dict[str, Any] | None = None) -> str:
    """The add-a-chart form. Three fields; the rest waits."""
    form = form or {}
    known = sorted(columns | plot_defs_vectors())
    spans = tuple((s, f"{s} -- {format_duration(v)}")
                  for s, v in plot_defs.SPANS.items())
    return f'''
<section class="group">
  <h3>Add a chart</h3>
  <p class="lede">A name, how far back, and one reading. Everything else is on
     the page that appears next -- asking for twelve settings before there is
     anything to save them in is how a form loses what somebody typed.</p>
  {f'<p class="err">{html.escape(error)}</p>' if error else ""}
  <form method="post" action="./new-plot">
    <datalist id="readings">
      {"".join(f'<option value="{html.escape(c)}">' for c in known)}
    </datalist>
    <div class="row">
      <label>Name
        <input name="name" required pattern="[a-z][a-z0-9_-]*"
               value="{html.escape(str(form.get("name", "")))}"
               placeholder="daytempdew">
        <span class="hint">Lowercase. It becomes the filename.</span>
      </label>
      <label>Group
        {_select("span", spans, form.get("span", "day"))}
      </label>
      <label>First reading
        <input name="obs" list="readings" required
               value="{html.escape(str(form.get("obs", "")))}"
               placeholder="outTemp">
        <span class="hint">{len(known)} in this archive.</span>
      </label>
    </div>
    <div class="actions"><button type="submit">Add it</button></div>
  </form>
</section>'''


def importer(admin: Any, message: str = "", error: str = "",
             form: dict[str, Any] | None = None) -> str:
    """The bring-it-over-from-WeeWX form.

    Three ways in, and the order matters. A file is the one that works from
    anywhere: the skin is on the machine somebody is sitting at, not
    necessarily on the machine this is running on. Run weewx-evo in a
    container and there is no path from here that reaches the skin at all.
    """
    form = form or {}
    return f'''
<section class="group">
  <h3>Import from a WeeWX skin</h3>
  <p class="lede">Reads an <code>[ImageGenerator]</code> section and makes the
     same charts. Everything about drawing a picture is left behind, and it
     says what it left. Nothing is overwritten unless you ask.</p>
  {f'<p class="err">{html.escape(error)}</p>' if error else ""}
  {f'<p class="ok">{html.escape(message)}</p>' if message else ""}

  <form method="post" action="./import-plots" enctype="multipart/form-data">
    <fieldset class="line">
      <legend>A file</legend>
      <div class="row">
        <label>skin.conf
          <input type="file" name="upload" accept=".conf,.txt,text/plain">
          <span class="hint">Usually <code>skins/Seasons/skin.conf</code> in a
            WeeWX installation. It is read here and not kept.</span>
        </label>
      </div>
    </fieldset>

    <fieldset class="line">
      <legend>Or paste it</legend>
      <div class="row">
        <label>The text of a skin.conf
          <textarea name="pasted" rows="8" spellcheck="false"
                    placeholder="[ImageGenerator]&#10;    [[day_images]]&#10;        [[[daytempdew]]]&#10;            [[[[outTemp]]]]&#10;            [[[[dewpoint]]]]"
                    >{html.escape(str(form.get("pasted", "")))}</textarea>
          <span class="hint">The whole file, or just the
            <code>[ImageGenerator]</code> part of it.</span>
        </label>
      </div>
    </fieldset>

    <details>
      <summary>Or a path on the machine this is running on</summary>
      <div class="row">
        <label>Path
          <input name="source" value="{html.escape(str(form.get("source", "")))}"
                 placeholder="/etc/weewx/skins/Seasons/skin.conf">
          <span class="hint">Only useful where weewx-evo and WeeWX share a
            filesystem. In a container they do not.</span>
        </label>
      </div>
    </details>

    <div class="row">
      <label class="tick">
        <input type="checkbox" name="replace" value="1">
        Replace everything
        <span class="hint">Off, it adds what is not already here and leaves
          charts you have changed alone.</span>
      </label>
    </div>
    <div class="actions"><button type="submit">Read it</button></div>
  </form>
</section>'''


def _num(value: Any) -> str:
    return "" if value is None else html.escape(f"{value:g}")

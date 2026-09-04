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

NEWLINE = "\n"

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
         ("year", ("not if there is nothing in a year -- this station has no "
                  "such sensor")))


# -- what the admin object does -------------------------------------------

def path_for(admin: Any) -> Path:
    """Where plots.toml lives: beside the configuration."""
    return Path(admin.path).parent / "plots.toml"


def load(admin: Any) -> plot_defs.PlotSet:
    """The charts, laying the starter set down on a first run.

    Here as well as in `cli.load_plots`, because these are the two ways a
    station first has charts and neither one goes through the other: `serve`
    reads them to run the feeds, and this page reads them to show them. A
    fresh installation that had only ever opened the settings page saw an
    empty Charts page and a website with nothing on it.
    """
    where = path_for(admin)
    if not where.exists() and not getattr(admin, "read_only", False):
        from . import starter

        said = starter.install_plots(where)
        if said:
            log.info("%s", said)
    return plot_defs.load(where)


def store(admin: Any, charts: plot_defs.PlotSet, note: str = "") -> str:
    """Write them. Returns an error, or empty if it worked."""
    if admin.read_only:
        return "This settings page was started read-only."
    try:
        plot_defs.save(path_for(admin), charts, note)
    except Exception as exc:
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


def compare(admin: Any, form: dict[str, Any]) -> tuple[str, str]:
    """One chart per reading, drawing every place at once. (said, error)

    The overlay is what makes a site of several places worth having, and
    until this it existed only as `weewx-evo plots compare --write`. An
    operator who does everything on these pages -- adds a second archive,
    points the feed at both, ticks four readings under Comparisons -- got a
    manifest with no plots in it and four comparison pages that drew nothing
    and said nothing about why.

    Generated rather than typed for the reason `plots import` exists: four
    readings by four spans by four places is sixty-four lines, and asking
    somebody to write those into a file is the arrangement this project
    removed.
    """
    from . import archives as archive_defs

    register = archive_defs.Register.load(
        Path(admin.path).parent / archive_defs.FILENAME, admin.config())
    places = [one.name for one in register.ordered()]
    if len(places) < 2:
        # Said rather than done: somebody who pressed this wants a
        # comparison, and "there is one place" is the answer to why there is
        # not one.
        return "", ("A comparison needs two places to compare. Add another "
                    "on the Archives page.")

    readings = [one.strip() for one
                in str(form.get("obs") or "").replace(",", " ").split()
                if one.strip()]
    spans = [one.strip() for one
             in str(form.get("span") or "").replace(",", " ").split()
             if one.strip()]
    if not readings or not spans:
        return "", "Say which readings and which spans to compare."

    charts = load(admin)
    written, replaced = plot_defs.comparisons(
        places, readings, spans, existing=charts)
    made = len(written) - len(charts) + len(replaced)
    error = store(admin, written)
    if error:
        return "", error
    return (f"{made} comparison chart(s) across {', '.join(places)}"
            + (f"; {len(replaced)} replaced" if replaced else "")
            + ". The feeds draw them on their next run.", "")


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

    choices = series_choices(admin)
    known = known_series(choices=choices)
    # One place's columns per place, read once. A line reading somewhere else
    # has to be checked against *that* file: a sensor only the second site
    # has would otherwise be reported as a column that does not exist, which
    # reads as a typo on the one line where the reading is real.
    held: dict[str, set[str]] = {"": columns}

    def columns_of(place: str) -> set[str]:
        if place not in held:
            held[place] = admin.columns(place)
        return held[place]

    lines = []
    for index in range(_count(form)):
        obs = (form.get(f"line{index}_obs") or "").strip()
        if not obs or form.get(f"line{index}_delete"):
            continue
        aggregate = (form.get(f"line{index}_aggregate") or "").strip()
        if aggregate and aggregate not in AGGREGATES:
            errors[f"line{index}_aggregate"] = f"{aggregate!r} is not an aggregate."
            aggregate = ""
        interval = (form.get(f"line{index}_interval") or "").strip()
        # Which place this line reads. Refused rather than warned about, and
        # this is the one field here where that is right: a chart naming a
        # column that does not exist yet draws nothing and says so, but a
        # chart naming an archive that does not exist would quietly fall
        # back to this one -- one location's temperature under another
        # location's label, and nothing on the page could show it.
        # Carried over when the form did not render the picker at all. It is
        # not rendered when there is one series to choose from -- and also
        # when `series_choices` could not find out, which is every reason
        # `archives.toml` might not be readable for a moment. The line's own
        # place would then be posted as empty and written as empty: two
        # lines reading two places become two identical lines reading one,
        # the page says saved, and nothing anywhere says otherwise. Every
        # other field the form does not show is carried the same way, three
        # lines below; this one was left out of that, and it is the field
        # this whole feature adds.
        if f"line{index}_series" not in form:
            series = getattr(plot.lines[index], "series", "") \
                if index < len(plot.lines) else ""
        else:
            series = (form.get(f"line{index}_series") or "").strip()
        if series and series not in known:
            errors[f"line{index}_series"] = (
                f"There is no series called {series!r}. "
                f"There is: {', '.join(sorted(known)) or 'one'}.")
            series = ""
        # Checked after the series, because which file has the column
        # depends on which place the line reads. Named, not refused: a
        # column can appear later -- a sensor arrives, a driver starts
        # sending a field -- and a chart written ahead of it should not be
        # impossible to save.
        theirs = columns_of(series)
        # A place whose file has not been written yet answers with no
        # columns at all, and "no columns" is not "not this one": every line
        # pointed at a place added this morning would be told its reading is
        # a typo. The chart's own archive goes on warning on an empty set,
        # because that is what it did before there were places.
        if ((theirs or not series) and obs not in theirs
                and obs not in plot_defs_vectors()):
            where = f"{series} has" if series else "The archive has"
            errors[f"line{index}_obs"] = (
                f"{where} no column called {obs!r}. Saved anyway; the "
                "chart will be empty until something writes one.")
        # Everything the form does not render, carried over from the line
        # that row was rendered from. `Line` has fourteen fields and this
        # page shows seven; rebuilding it from the seven threw the rest away
        # on every save. The shipped set puts `width` and `gap_fraction` on
        # every line of all hundred charts, so opening any of them and
        # pressing Save already lost them -- silently, and only visible as a
        # slightly different picture a week later. A form index is a line
        # index because `edit()` renders `enumerate(plot.lines)`; a deleted
        # row shortens the list on the way out, not on the way in.
        was = plot.lines[index] if index < len(plot.lines) else plot_defs.Line("")
        lines.append(plot_defs.Line(
            obs=obs,
            label=(form.get(f"line{index}_label") or "").strip(),
            kind=(form.get(f"line{index}_kind") or "line").strip(),
            color=_colour_from(form, index),
            aggregate=aggregate,
            series=series,
            interval=plot_defs._interval(interval) if interval else None,
            fill_color=was.fill_color,
            width=was.width,
            marker=was.marker,
            marker_size=was.marker_size,
            gap_fraction=was.gap_fraction,
            rotate=was.rotate,
            binding=was.binding,
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
    return dict(errors.items())


def plot_defs_vectors() -> set[str]:
    from .series import VECTORS

    return set(VECTORS)


def _colour_field(name: str, line: Any, index: int) -> str:
    """A colour, and the ability not to have one.

    `<input type="color">` always submits something, so rendering the
    *resolved* colour into it froze WeeWX's positional palette onto every
    line of every shipped chart the first time anybody pressed Save. That is
    not a cosmetic loss: "no colour of its own" is what lets a line take its
    place's colour on a comparison chart, and once frozen the same place
    comes out blue on one chart and red on the next.

    So the swatch shows what will be drawn -- which is the useful thing to
    look at -- and a separate tick says whether that is a choice. Unticked
    sends nothing, which is exactly "no colour of its own"; a checkbox and a
    same-named hidden field would send two values and which one arrives
    depends on the parser, which is why closed alternatives use a `<select>`.

    The tick is a `<label>` of its own, so the caption above cannot be one:
    a label may not contain a label, and an outer one with no `for` takes
    the first labelable thing inside it -- so clicking "its own" would fire
    at the colour input as well. The caller wraps this in a fieldset.
    """
    own = bool(line.color)
    shown = line.color or line.resolved(index).color or "#4282b4"
    return (
        f'<span class="colourpick">'
        f'<input type="color" name="{name}" value="{html.escape(shown)}">'
        f'<label class="tick"><input type="checkbox" name="{name}_own"'
        f' value="1"{" checked" if own else ""}> its own</label>'
        f'</span>')


def _colour_from(form: dict[str, Any], index: int) -> str:
    """The colour this line chose, or empty where it chose none."""
    if not form.get(f"line{index}_color_own"):
        return ""
    return (form.get(f"line{index}_color") or "").strip()


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
        except Exception as exc:
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

    # An untouched starter set is replaced whether or not the box is
    # ticked. Those charts are not a decision anybody made -- they were
    # here on arrival -- and half of them share names with what a WeeWX
    # skin brings, so an import that "added" to them added nothing and
    # said so cheerfully.
    from . import starter

    if not replace and starter.is_starter(path_for(admin)):
        replace = True

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
    """One entry. The charts themselves are on its page.

    They used to be four collapsed groups plus two "add" links, which was
    already the tidied version of a hundred flat entries. One line is the
    version that does not grow at all -- and a hundred charts want a page
    with room for their spans and their lines, not a sidebar.
    """
    charts = load(admin)
    here = (active in ("charts", "new-plot", "import-plots")
            or active.startswith("plot:"))
    current = " aria-current='page'" if here else ""
    return [(f'<a href="./charts"{current}>Charts'
             f'<span class="count">{len(charts)}</span></a>')]


def _compare_button(admin: Any) -> str:
    """Generate the overlays, from a form of its own.

    Its **own** `<form>`, outside anything else on the page. Nested forms do
    not exist in HTML: the browser drops the inner one and keeps its
    `</form>`, closing the outer early, and Save then belongs to no form --
    with every tag present and closed in the output.

    Offered only where there is something to compare. A button that answers
    "there is one place" is a button that teaches people not to press
    buttons.
    """
    from . import archives as archive_defs

    try:
        register = archive_defs.Register.load(
            Path(admin.path).parent / archive_defs.FILENAME, admin.config())
        if len(register.all()) < 2:
            return ""
    except Exception:
        return ""
    return (
        '<form method="post" action="./compare-plots" class="inline">'
        '<input type="hidden" name="obs" '
        'value="outTemp,outHumidity,windSpeed,rain">'
        '<input type="hidden" name="span" value="day,week,month,year">'
        '<button class="button quiet" type="submit" '
        'title="One chart per reading, drawing every place on one axis">'
        "Generate comparisons</button></form>")


def overview(admin: Any, message: str = "", error: str = "") -> str:
    """Every chart, grouped by the span it covers.

    A hundred charts was four collapsed groups in the sidebar, which was the
    tidied version of a hundred flat links. Neither had room to say what a
    chart draws -- and "outTemp, dewpoint" beside the name is the difference
    between finding one and opening six.
    """
    charts = load(admin)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    # The banner above the page says it. Printing it a second time in the
    # body was two "Saved." one under the other, which reads as two things
    # having happened.
    said = ""

    add = ""
    if not admin.read_only:
        add = ('<div class="actions">'
               '<a class="button" href="./new-plot">Add a chart</a>'
               '<a class="button quiet" href="./import-plots">'
               "Import from a skin</a>"
               + _compare_button(admin) + "</div>")

    if not len(charts):
        return f'''
<h2>Charts</h2>
{problem}{said}
<p class="lede">Definitions shared by all feeds.</p>
{add}
<p class="navempty">None yet. Add one, or bring a whole set over from an
   existing WeeWX skin -- the importer reads a skin.conf and reports what it
   could not take.</p>
'''

    groups = charts.by_span()
    # The same strip the long forms have. Ninety-two charts in four blocks
    # is a page somebody scrolls past three times to reach the fourth.
    jump = "".join(
        f'<a href="#span-{html.escape(span)}">{html.escape(span)}'
        f'<span class="count">{len(groups[span])}</span></a>'
        for span in sorted(groups))
    blocks = [f'<nav class="jump" aria-label="Spans">{jump}</nav>']
    for span in sorted(groups):
        rows = []
        for plot in groups[span]:
            drawn = ", ".join(line.obs for line in plot.lines[:4])
            if len(plot.lines) > 4:
                drawn += f", and {len(plot.lines) - 4} more"
            # Which of a hundred charts go to the site rather than under
            # each place, without opening a hundred charts. Asked of
            # `names_a_place()` because that is the question the feed asks;
            # counting the places instead missed the whole class of chart
            # that names one place on one line -- a site chart with no mark
            # on it, which is the one this exists to show.
            mark = ('<span class="chip" title="'
                    + html.escape(", ".join(plot.places()))
                    + '">site chart</span>' if plot.names_a_place() else "")
            rows.append(f'''
      <li>
        <a href="./plot:{html.escape(plot.name)}">{html.escape(plot.name)}</a>
        {mark}
        <span class="note">{html.escape(drawn)}</span>
      </li>''')
        blocks.append(f'''
  <section class="flow" id="span-{html.escape(span)}">
    <div class="made"><span class="title">{html.escape(span)}</span>
      <span class="note aside">{len(groups[span])} chart(s)</span></div>
    <ul class="sends plain">{NEWLINE.join(rows)}</ul>
  </section>''')

    return f'''
<h2>Charts</h2>
{problem}{said}
<p class="lede">Definitions shared by all feeds.</p>
{add}
{NEWLINE.join(blocks)}
'''



def series_choices(admin: Any = None) -> list[tuple[str, str, str]]:
    """Every place a line can read: its name, what to call it, its colour.

    Empty where there is one. With a single series there is nothing to
    choose between, the picker is not drawn, and a saved value would be a
    setting nobody could see.

    Read once per page and handed down, never asked per line. It parses
    `archives.toml`, and `_series_field` used to call it once per row while
    `save` called it twice: an eight-line chart was eight reads of that file
    to draw and sixteen to save it.
    """
    try:
        from . import adminarchives

        registry = adminarchives.load(admin)
        if registry is None or not registry.several():
            return []
        # `presented`, so the colour and the short code are filled in the
        # same way every renderer fills them. A swatch here showing one
        # colour and the chart drawing another would be worse than no
        # swatch: the whole point of it is that the two agree.
        return [(one.name, one.title, one.color)
                for one in registry.presented()]
    except Exception:
        log.debug("could not list the archives", exc_info=True)
        return []


def known_series(admin: Any = None,
                 choices: list[tuple[str, str, str]] | None = None) -> set[str]:
    """The archives configured, by name. Empty where there is one."""
    found = series_choices(admin) if choices is None else choices
    return {name for name, _title, _colour in found}


def _series_field(name: str, chosen: str, admin: Any = None,
                  choices: list[tuple[str, str, str]] | None = None,
                  say: Any = None) -> str:
    """Where this line reads from. Nothing at all with one archive.

    A picker on every line of every chart on every single-series station is
    a field a hundred people have to work out is not theirs, and that is the
    ordinary case.

    The swatch beside it is what ties this to the Archives page. Without it
    the colour chosen for a place and the line drawn from that place are two
    unrelated facts on two pages, and the wrong line gets the wrong colour
    with everything looking right on both.

    The third argument stays the `Admin`, and the read-once list
    arrives by name beside it. Putting the list in that slot was
    positionally compatible and semantically not: the only caller
    outside this file passes an `Admin`, `if not choices` is false for
    one, and the next line iterated it.
    """
    if choices is None:
        choices = series_choices(admin)
    if not choices:
        return ""
    say = say or (admin.say if admin is not None else str)
    colours = {one: colour for one, _title, colour in choices}
    own = html.escape(say("This chart's own"))
    options = [f'<option value="">{own}</option>']
    options += [
        f'<option value="{html.escape(one)}"'
        f'{" selected" if chosen == one else ""}>'
        f"{html.escape(title)} ({html.escape(one)})</option>"
        for one, title, _colour in choices]
    swatch = ""
    if chosen and chosen in colours:
        title = say("the colour {place} is drawn in")
        swatch = (f'<span class="swatch" style="--c: '
                  f'{html.escape(colours[chosen])}" title="'
                  f'{html.escape(title.replace("{place}", chosen))}"></span>')
    return (f'<label>{html.escape(say("Place"))}\n'
            f'  {swatch}<select name="{html.escape(name)}">'
            f'{"".join(options)}</select>\n</label>')


def _select(name: str, options: tuple, value: Any, extra: str = "",
            say: Any = None) -> str:
    say = say or str
    rows = []
    seen = False
    for key, label in options:
        chosen = str(key) == str(value if value is not None else "")
        seen = seen or chosen
        rows.append(f'<option value="{html.escape(str(key))}"'
                    f'{" selected" if chosen else ""}>'
                    f"{html.escape(say(str(label)))}</option>")
    if not seen and value not in (None, ""):
        # Whatever is in the file, even if this page would not have offered
        # it. Losing somebody's hand-written setting by rendering a form is
        # the worst thing a settings page can do.
        rows.insert(0, f'<option value="{html.escape(str(value))}" selected>'
                       f'{html.escape(str(value))} '
                       f'{html.escape(say("(from the file)"))}</option>')
    return (f'<select name="{html.escape(name)}" {extra}>'
            + "".join(rows) + "</select>")


def _places_band(plot: Any, titles: dict[str, str], say: Any = None) -> str:
    """Said once, above the rows, and only when it is true.

    A chart becomes a site chart the moment one line names a place, and a
    dropdown eight rows down is not where somebody finds that out.

    `plot.names_a_place()` and `plot.places()`, never a rule of this page's
    own. That method *is* the filing rule -- it is what both feeds ask
    (`comparisons = [p for p in self.plots if p.names_a_place()]`) -- and it
    is deliberately not "draws more than one place": one line reading the
    north field produces the same numbers on every place's page, so it is
    written once too. A second implementation here disagreed with it on
    exactly that chart, and said so in a sentence stated as fact.
    """
    if not plot.names_a_place():
        return ""
    say = say or str
    named = [titles.get(one, one) for one in plot.places()]
    if any(not line.series for line in plot.lines):
        named.append(say("this chart's own place"))
    return ('<p class="note">'
            + html.escape(say("Draws from")) + " "
            + html.escape(", ".join(named)) + ". "
            + html.escape(say(
                "A chart that names a place at all is written once, for the "
                "site, rather than once under each place: the numbers in it "
                "do not change from one place's pages to another's."))
            + "</p>")


def edit(admin: Any, name: str, columns: set[str], errors: dict[str, str],
         form: dict[str, Any] | None = None) -> str:
    """One chart's page."""
    say = admin.say
    charts = load(admin)
    plot = charts.get(name)
    if plot is None:
        return ('<section class="group">'
                f'<h3>{html.escape(say("Not here"))}</h3>'
                '<p class="lede">'
                + html.escape(admin.language.fill(
                    "There is no chart called {name}.", name=name))
                + "</p></section>")

    def err(key: str) -> str:
        return (f'<p class="err">{html.escape(errors[key])}</p>'
                if key in errors else "")

    spans = tuple((s, s) for s in sorted(
        set(plot_defs.SPANS) | {p.span for p in charts}))
    known = sorted(columns | plot_defs_vectors())
    datalist = ("<datalist id='readings'>"
                + "".join(f'<option value="{html.escape(c)}">' for c in known)
                + "</datalist>")

    choices = series_choices(admin)
    titles = {name_: title for name_, title, _colour in choices}
    # One readings list per place a line actually names, read once each. A
    # sensor only the second site has is not a typo, and offering the
    # default archive's columns beside a line that reads somewhere else is
    # how it comes to look like one.
    for place in sorted({line.series for line in plot.lines if line.series}):
        if place not in titles:
            continue
        theirs = sorted(admin.columns(place) | plot_defs_vectors())
        datalist += (f"<datalist id='readings-{html.escape(place)}'>"
                     + "".join(f'<option value="{html.escape(c)}">'
                               for c in theirs) + "</datalist>")

    rows = []
    for index, line in enumerate(plot.lines):
        prefix = f"line{index}"
        # The place in the legend. A comparison chart is `outTemp` five
        # times, and without this it is five identical legends.
        legend = html.escape(line.obs)
        if line.series in titles:
            legend += " &mdash; " + html.escape(titles[line.series])
        offers = ("readings-" + line.series if line.series in titles
                  else "readings")
        rows.append(f'''
    <fieldset class="line">
      <legend>{legend}</legend>
      <div class="row">
        <label>{html.escape(say("Reading"))}
          <input name="{prefix}_obs" list="{html.escape(offers)}"
                 value="{html.escape(line.obs)}" required>
        </label>
        <label>{html.escape(say("Called"))}
          <input name="{prefix}_label" value="{html.escape(line.label)}"
                 placeholder="{html.escape(charts.labels.get(line.obs, line.obs))}">
        </label>
        <label>{html.escape(say("Drawn as"))}
          {_select(f"{prefix}_kind", KINDS, line.kind, say=say)}
        </label>
        <fieldset class="colourfield">
          <legend>{html.escape(say("Colour"))}</legend>
          {_colour_field(f"{prefix}_color", line, index)}
        </fieldset>
      </div>
      <div class="row">
        <label>{html.escape(say("Reduced by"))}
          {_select(f"{prefix}_aggregate", USEFUL, line.aggregate, say=say)}
        </label>
        <label>{html.escape(say("Per"))}
          {_select(f"{prefix}_interval", INTERVALS,
                   "" if line.interval is None else line.interval, say=say)}
        </label>
        {_series_field(f"{prefix}_series", line.series, choices=choices,
                       say=say)}
        <label class="tick">
          <input type="checkbox" name="{prefix}_delete" value="1">
          {html.escape(say("Remove this reading"))}
        </label>
      </div>
      {err(f"{prefix}_obs")}{err(f"{prefix}_aggregate")}{err(f"{prefix}_series")}
    </fieldset>''')

    checked = " checked" if plot.show_daynight else ""
    return f'''
<section class="group">
  <h3>{html.escape(plot.name)}</h3>
  <p class="lede">{html.escape(say("Output:"))}
     <code>{html.escape(plot.name)}.json</code>.</p>
  <form method="post" action="./plot:{html.escape(plot.name)}">
  {datalist}
  <div class="row">
    <label>{html.escape(say("Group"))}
      {_select("span", spans, plot.span, say=say)}
      <span class="hint">{html.escape(say(
        "Only for grouping and for the manifest. The length below is what "
        "decides how far back it reaches."))}</span>
    </label>
    <label>{html.escape(say("Reaches back"))}
      <input name="time_length" list="lengths"
             value="{html.escape(format_duration(plot.time_length))}">
      <datalist id="lengths">
        {"".join(f'<option value="{v}">{html.escape(say(said))}</option>'
                 for v, said in LENGTHS)}
      </datalist>
      <span class="hint">{html.escape(say(
        "27h on a day chart, so last night is still on it."))}</span>
      {err("time_length")}
    </label>
    <label>{html.escape(say("Title"))}
      <input name="title" value="{html.escape(plot.title)}"
             placeholder="{html.escape(say("built from the readings"))}">
    </label>
  </div>
  <div class="row">
    <label>{html.escape(say("Leave out when empty"))}
      {_select("skip_if_empty", EMPTY, plot.skip_if_empty, say=say)}
      <span class="hint">{html.escape(say(
        "A sensor with nothing in a year is one this station does not have; "
        "one with nothing today is having a bad day. The first should "
        "vanish, the second should stay."))}</span>
    </label>
    <label class="tick">
      <input type="checkbox" name="show_daynight" value="1"{checked}>
      {html.escape(say("Shade the hours of darkness"))}
      <span class="hint">{html.escape(say(
        "Worth it on a day or a week. On a year it is a grey smear."))}</span>
    </label>
  </div>
  <div class="row narrow">
    <label>{html.escape(say("Axis from"))}
      <input name="ymin" value="{_num(plot.yscale[0])}"
             placeholder="{html.escape(say("auto"))}">
      {err("ymin")}
    </label>
    <label>{html.escape(say("to"))}
      <input name="ymax" value="{_num(plot.yscale[1])}"
             placeholder="{html.escape(say("auto"))}">
      {err("ymax")}
    </label>
    <label>{html.escape(say("smallest step"))}
      <input name="ystep" value="{_num(plot.yscale[2])}"
             placeholder="{html.escape(say("auto"))}">
      <span class="hint">{html.escape(say(
        "Fixing an axis is how two charts stay comparable."))}</span>
      {err("ystep")}
    </label>
  </div>

  <h4>{html.escape(say("Readings"))}</h4>
  {_places_band(plot, titles, say=say)}
  {"".join(rows)}

  <fieldset class="line add">
    <legend>{html.escape(say("Add one"))}</legend>
    <div class="row">
      <label>{html.escape(say("Reading"))}
        <input name="new_obs" list="readings" placeholder="outTemp">
        <span class="hint">{html.escape(admin.language.fill(
          "{n} to choose from, taken from the archive itself.",
          n=len(known)))}</span>
      </label>
    </div>
  </fieldset>

  <div class="actions">
    <button type="submit">{html.escape(say("Save"))}</button></div>
  </form>
</section>

<section class="group danger">
  <h3>{html.escape(say("Remove"))}</h3>
  <p class="lede">{html.escape(say(
    "Removes the definition. Existing files remain."))}</p>
  <form method="post" action="./plot:{html.escape(plot.name)}/remove"
        onsubmit="return confirm('{html.escape(admin.language.fill(
            "Remove the chart {name}?", name=plot.name))}')">
    <div class="actions"><button class="warn" type="submit">
      {html.escape(say("Remove"))}</button></div>
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
  <p class="lede">Name, time span and first reading.</p>
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
  <p class="lede">Imports <code>[ImageGenerator]</code> from
     <code>skin.conf</code>. Existing charts remain unless Replace is selected.</p>
  {f'<p class="err">{html.escape(error)}</p>' if error else ""}

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
                    placeholder="[ImageGenerator]&#10;"
                                "    [[day_images]]&#10;"
                                "        [[[daytempdew]]]&#10;"
                                "            [[[[outTemp]]]]&#10;"
                                "            [[[[dewpoint]]]]"
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

"""What to chart: plot definitions, owned by weewx-evo.

A plot is a name, a span of time, and the readings to draw in it. That is all
it is, and nothing here knows about pixels, fonts or file formats. The JSON
feed turns a plot into data; an image generator, if one is ever written, turns
the same plot into a picture. Neither owns the definition.

That is the difference from WeeWX, where plots live inside `[ImageGenerator]`
in a skin. There, charting is a property of the renderer: two renderers means
two copies of the same list of charts, and the JSON one exists only by reading
the picture one's configuration behind its back. Here the definition comes
first and the renderers are consumers.

## Where they live

Their own file, `plots.toml`, beside the configuration. Not in it: settings
are a few dozen named values and this is a list of many similar records with
lists inside them. Mixing the two makes both harder to read, and a plot set
imported from an old skin is something you want to be able to diff, keep in
version control, or hand to somebody else on its own.

    [[plot]]
    name = "daytempdew"
    span = "day"
    time_length = "27h"
    show_daynight = true

      [[plot.line]]
      obs = "outTemp"

      [[plot.line]]
      obs = "dewpoint"

## Coming from WeeWX

`from_image_generator()` reads an `[ImageGenerator]` section out of a skin.conf
or weewx.conf and produces the same plots. Everything about *drawing* --
fonts, image sizes, background colors, anti-aliasing -- is dropped, and the
importer says so rather than pretending it understood. What survives is what a
chart actually is: which readings, over how long, aggregated how, in what
color.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .options import parse_duration

log = logging.getLogger(__name__)

#: How a line is drawn. The renderer decides what that means; `vector` is the
#: arrow-per-reading plot WeeWX draws for wind.
KINDS = ("line", "bar", "vector")

#: The families of plot WeeWX ships, and the time each covers. A span is only
#: a name for grouping -- nothing stops a plot called `fortnight`.
SPANS = {
    "day": 97200,      # 27 hours, so the chart still shows last night
    "week": 604800,
    "month": 2592000,
    "year": 31536000,
}

#: Colors WeeWX gives successive lines when a plot does not name its own.
#: Kept so an imported plot without explicit colors comes out looking the
#: same as its PNG did.
LINE_COLORS = ("#4282b4", "#b44242", "#42b442", "#42b4b4", "#b442b4")
FILL_COLORS = ("#72b2c4", "#c47272", "#72c472", "#72c4c4", "#c472c4")

#: Options in an [ImageGenerator] section that describe a picture and nothing
#: else. Dropped on import, and named in the report so the operator can see
#: what was left rather than wondering.
IMAGE_ONLY = {
    "image_width", "image_height", "image_background_color", "anti_alias",
    "chart_background_color", "chart_gridline_color",
    "top_label_font_path", "top_label_font_size",
    "unit_label_font_path", "unit_label_font_size", "unit_label_font_color",
    "bottom_label_font_path", "bottom_label_font_size",
    "bottom_label_font_color", "bottom_label_offset",
    "axis_label_font_path", "axis_label_font_size", "axis_label_font_color",
    "rose_label_font_path", "rose_label_font_size", "rose_label_font_color",
    "daynight_day_color", "daynight_night_color", "daynight_edge_color",
    "x_label_format", "bottom_label_format", "line_type", "image_root",
    "y_label_side", "x_nticks",
}


@dataclass
class Line:
    """One reading drawn in one plot."""

    #: What to read out of the archive.
    obs: str
    #: What to call it in a legend. Empty means the renderer decides -- for
    #: JSON that is the reading's own name, which a client can translate.
    label: str = ""
    kind: str = "line"
    color: str = ""
    fill_color: str = ""
    width: float | None = None
    #: How to reduce each bucket. Empty means none: the archive records
    #: themselves, which is what a day plot wants.
    aggregate: str = ""
    #: Bucket size, in seconds or as 'hour'/'day'/'month'/'year'.
    interval: int | str | None = None
    marker: str = ""
    marker_size: int | None = None
    #: What counts as a break in the readings rather than their rhythm.
    #: None lets the feed work it out from the spacing, which is better than
    #: a fixed fraction of the plot width.
    gap_fraction: float | None = None
    #: Vector plots only, in degrees, positive clockwise.
    rotate: float | None = None
    #: Which archive this line reads, where there is more than one. Empty
    #: is the one the chart is being drawn for, which is every line on
    #: every station with a single series.
    #:
    #: This is what "outTemp at all five locations on one axis" is: five
    #: lines, one plot, each naming its own place. `archives.py` gives n
    #: independent series and until now nothing could put two on one chart --
    #: so the question that makes somebody install Grafana was one our own
    #: pages could not answer either.
    #:
    #: Not `binding`, which is beside it and means WeeWX's `data_binding`:
    #: `wx_binding` there names a *schema*, not a place. One field with two
    #: meanings holds until somebody names an archive `wx_binding`.
    series: str = ""
    #: WeeWX's `data_binding`, carried through an import and back out again.
    #: Nothing here reads it.
    binding: str = ""

    def resolved(self, position: int = 0, place: str = "") -> Line:
        """The same line with the colors WeeWX would have given it.

        `place` is what `archives.toml` says the archive this line reads is
        drawn in. It stands between the line's own colour and the positional
        palette, and that order is the whole rule: somebody who typed a
        colour meant it, a place that has one has to look the same on every
        chart it appears on, and the palette is what is left.

        Positional colour cannot do a place's job, and this is not taste.
        `position` counts *within one plot*, so a place is the second colour
        on a chart drawing two places and the first on a chart drawing only
        it -- and a legend chip that says a place IS a colour would then be
        lying on one of the two.
        """
        if self.color and (self.kind != "bar" or self.fill_color):
            return self
        return replace(
            self,
            color=(self.color or place
                   or LINE_COLORS[position % len(LINE_COLORS)]),
            # Deliberately not taken from the place: a bar's fill is the pale
            # twin of its line colour, and deriving one from an arbitrary hex
            # is arithmetic in a colour space nobody can check by looking. A
            # bar chart across places is written by hand, and by somebody who
            # then types both.
            fill_color=(self.fill_color
                         or (FILL_COLORS[position % len(FILL_COLORS)]
                             if self.kind == "bar" else "")))


@dataclass
class Plot:
    """One chart."""

    name: str
    #: Which family it belongs to. Only for grouping and for the manifest;
    #: `time_length` is what actually decides the span.
    span: str = "day"
    #: How far back it reaches, in seconds.
    time_length: int = 97200
    lines: list[Line] = field(default_factory=list)
    #: A title. Empty means the renderer builds one from the line labels.
    title: str = ""
    #: Shade the hours of darkness. Only worth it on plots wide enough to
    #: show individual days.
    show_daynight: bool = False
    #: [low, high, smallest tick]. Any of them None to work it out from the
    #: data. Fixing an axis is how two plots stay comparable.
    yscale: list[Any] = field(default_factory=lambda: [None, None, None])
    #: Leave out a reading that has nothing over this span. A span rather
    #: than a yes or no, because WeeWX writes `skip_if_empty = year` and means
    #: it: a sensor with nothing in a year is one this station does not have,
    #: while a sensor with nothing today is one that is having a bad day. The
    #: first should vanish; the second should stay on the chart so the page
    #: does not rearrange itself. Empty means never leave anything out.
    skip_if_empty: str = ""

    def __post_init__(self) -> None:
        self.lines = [ln if isinstance(ln, Line) else Line(**ln)
                      for ln in self.lines]

    @property
    def drawn(self) -> list[Line]:
        """The lines with their colors filled in."""
        return self.drawn_with({})

    def drawn_with(self, colors: dict[str, str]) -> list[Line]:
        """The same, with each place's own colour where it has one.

        `colors` is archive name -> hex, out of `archives.toml`, and the
        empty string is the archive the chart is being drawn *for* -- a
        comparison chart's home line carries a blank `series`, and without
        an entry for it that line is the one on the chart drawn from the
        positional palette while every other is drawn in its place's colour.

        An empty map is the single-series case and every caller that has not
        been told about places, and then this is `drawn` exactly -- byte for
        byte, including the repeat past the fifth line. That matters:
        stepping the palette past a collision would change the colours of
        every existing plot with six lines in it, in a change about places.
        """
        if not colors:
            return [line.resolved(i) for i, line in enumerate(self.lines)]

        out: list[Line] = []
        taken: set[str] = set()
        for position, line in enumerate(self.lines):
            wanted = colors.get(line.series or "", "")
            if wanted and wanted in taken:
                # Two lines of one place -- a plot mixing readings AND
                # places. The place's colour is already on the chart, so the
                # second falls back to the palette rather than being drawn
                # twice in the same hue: two identical lines is a chart that
                # cannot be read and cannot be complained about, because
                # nothing about it looks wrong.
                wanted = ""
            became = line.resolved(position, wanted)
            taken.add(became.color)
            out.append(became)
        return out

    def uses(self) -> set[str]:
        """Which readings this plot needs."""
        return {line.obs for line in self.lines}

    def places(self) -> list[str]:
        """The archives this chart names, in the order its lines do.

        A list and not a set: it decides a legend's order and the sentence
        under a chart, and a set would put them in a different order on
        every process.
        """
        out: list[str] = []
        for line in self.lines:
            named = getattr(line, "series", "")
            if named and named not in out:
                out.append(str(named))
        return out

    def names_a_place(self) -> bool:
        """Whether any reading here says which archive it comes from.

        The whole of the filing rule, and it is deliberately not "draws more
        than one place". A chart with a single line reading the north field
        produces the same numbers whichever place's page it is on, so it is
        written once; writing it under every place would be N identical
        documents that change together, N uploads, and N chances for them to
        disagree after a partial export.
        """
        return any(getattr(line, "series", "") for line in self.lines)


def series_named(plots: Any) -> set[str]:
    """Every archive the charts in this set ask for, by name.

    So a feed opens the files something actually uses and no others. Empty
    for every station that has never written a `series` into `plots.toml`,
    which is the ordinary case and costs it nothing.
    """
    out: set[str] = set()
    for plot in getattr(plots, "plots", ()) or ():
        # Through `Plot.places()`, so the set and the list cannot disagree
        # about what "names a place" means. `tools/` builds bare stand-ins
        # for this function, hence the getattr.
        out.update(getattr(plot, "places", list)())
    return out


class PlotSet:
    """The plots there are, and what the readings in them are called."""

    def __init__(self, plots: Iterable[Plot] = (),
                 labels: dict[str, str] | None = None,
                 implied: Iterable[str] = ()) -> None:
        self.plots: list[Plot] = list(plots)
        #: obs_type -> what to call it in a legend. Not a translation table:
        #: whatever the station's operator wants it to say, in their language.
        self.labels: dict[str, str] = dict(labels or {})
        #: Which of them are not in the file but were worked out from the
        #: places (`implied`). Named so `plots list` can say which lines it
        #: is printing that nothing wrote, and so nothing that saves the set
        #: can put them in the file by accident.
        self.implied: tuple[str, ...] = tuple(implied)

    def __len__(self) -> int:
        return len(self.plots)

    def __iter__(self):
        return iter(self.plots)

    def get(self, name: str) -> Plot | None:
        for plot in self.plots:
            if plot.name == name:
                return plot
        return None

    def add(self, plot: Plot) -> None:
        if self.get(plot.name):
            raise ValueError(f"there is already a plot called {plot.name!r}")
        self.plots.append(plot)

    def remove(self, name: str) -> bool:
        before = len(self.plots)
        self.plots = [p for p in self.plots if p.name != name]
        return len(self.plots) != before

    def by_span(self) -> dict[str, list[Plot]]:
        """Grouped, in the order the spans were first seen."""
        out: dict[str, list[Plot]] = {}
        for plot in self.plots:
            out.setdefault(plot.span, []).append(plot)
        return out

    def spans(self) -> dict[str, int]:
        """How long each span covers, for the manifest.

        A client laying out its own periods needs this. Taken from the
        longest plot in the group, because that is what the group is.
        """
        out: dict[str, int] = {}
        for plot in self.plots:
            out[plot.span] = max(out.get(plot.span, 0), plot.time_length)
        return out

    def uses(self) -> set[str]:
        return set().union(*(p.uses() for p in self.plots)) if self.plots else set()


# -- reading and writing plots.toml ----------------------------------------

def load(path: str | Path) -> PlotSet:
    """Read plots.toml. A file that is not there means no plots, not an error."""
    import tomllib

    path = Path(path)
    if not path.exists():
        return PlotSet()
    with open(path, "rb") as fp:
        raw = tomllib.load(fp)
    return from_dict(raw)


def from_dict(raw: dict[str, Any]) -> PlotSet:
    """Plots out of already-parsed TOML."""
    plots = []
    for entry in raw.get("plot", []) or []:
        try:
            plots.append(_plot_from(entry))
        except (TypeError, ValueError) as exc:
            log.warning("skipping a plot in the file: %s", exc)
    return PlotSet(plots, raw.get("labels") or {})


def _plot_from(entry: dict[str, Any]) -> Plot:
    lines = []
    for raw_line in entry.get("line", []) or []:
        obs = str(raw_line.get("obs") or "").strip()
        if not obs:
            continue
        lines.append(Line(
            obs=obs,
            label=str(raw_line.get("label", "")),
            kind=str(raw_line.get("kind", "line")),
            color=str(raw_line.get("color", "")),
            fill_color=str(raw_line.get("fill_color", "")),
            width=_float(raw_line.get("width")),
            aggregate=str(raw_line.get("aggregate", "")),
            interval=_interval(raw_line.get("interval")),
            marker=str(raw_line.get("marker", "")),
            marker_size=_int(raw_line.get("marker_size")),
            gap_fraction=_float(raw_line.get("gap_fraction")),
            rotate=_float(raw_line.get("rotate")),
            series=str(raw_line.get("series", "")),
            binding=str(raw_line.get("binding", "")),
        ))

    name = str(entry.get("name") or "").strip()
    if not name:
        raise ValueError("a plot without a name")
    span = str(entry.get("span") or "day")
    length = entry.get("time_length")
    return Plot(
        name=name,
        span=span,
        time_length=(_seconds(length) if length is not None
                     else SPANS.get(span, 97200)),
        lines=lines,
        title=str(entry.get("title", "")),
        show_daynight=bool(entry.get("show_daynight", False)),
        yscale=[_float(entry.get("ymin")), _float(entry.get("ymax")),
                _float(entry.get("ystep"))],
        skip_if_empty=_span_name(entry.get("skip_if_empty")),
    )


def save(path: str | Path, plots: PlotSet, note: str = "") -> Path:
    """Write plots.toml, keeping the previous one.

    Written beside and moved into place, like the configuration: this file
    decides what a site shows, and an interrupted write must not leave half
    of it.
    """
    import shutil
    import tomllib

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render(plots, note)

    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(text, encoding="utf-8")
    with open(partial, "rb") as fp:
        tomllib.load(fp)  # what was written, not what we meant to write
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    partial.replace(path)
    return path


def render(plots: PlotSet, note: str = "") -> str:
    """The plots as a TOML file somebody can edit."""
    lines = [
        "# The charts weewx-evo produces.",
        "#",
        "# Each [[plot]] is one chart; each [[plot.line]] is one reading in it.",
        "# 'span' groups plots for the manifest and for the admin page;",
        "# 'time_length' is what actually decides how far back it reaches",
        "# (a number of seconds, or 27h, 7d, and so on).",
        "#",
        "# Leave 'aggregate' out for the archive records themselves. Set it to",
        "# min, max, avg or sum with an 'interval' of 'day' for the coarser",
        "# plots -- a year of five-minute readings is not a chart, it is a",
        "# hundred thousand points drawn on top of each other.",
    ]
    if note:
        lines += ["#", *[f"# {line}" for line in note.splitlines()]]
    lines.append("")

    if plots.labels:
        lines.append("# What each reading is called in a legend. A feed that")
        lines.append("# has no name for one leaves it to the client, which")
        lines.append("# knows what language its reader speaks.")
        lines.append("[labels]")
        for obs in sorted(plots.labels):
            lines.append(f"{obs} = {_toml(plots.labels[obs])}")
        lines.append("")

    for plot in plots:
        lines.append("[[plot]]")
        lines.append(f"name = {_toml(plot.name)}")
        lines.append(f"span = {_toml(plot.span)}")
        lines.append(f"time_length = {_toml(_duration(plot.time_length))}")
        if plot.title:
            lines.append(f"title = {_toml(plot.title)}")
        if plot.show_daynight:
            lines.append("show_daynight = true")
        if plot.skip_if_empty:
            lines.append(f"skip_if_empty = {_toml(plot.skip_if_empty)}")
        # Three named values rather than one array: TOML has no null, and an
        # axis where only the bottom is fixed is the common case.
        for key, value in zip(("ymin", "ymax", "ystep"), plot.yscale, strict=True):
            if value is not None:
                lines.append(f"{key} = {_toml(value)}")
        lines.append("")
        for line in plot.lines:
            lines.append("  [[plot.line]]")
            lines.append(f"  obs = {_toml(line.obs)}")
            for key, value in (("label", line.label), ("kind", line.kind),
                               ("color", line.color),
                               ("fill_color", line.fill_color),
                               ("aggregate", line.aggregate),
                               ("marker", line.marker),
                               ("series", line.series),
                               ("binding", line.binding)):
                if value and not (key == "kind" and value == "line"):
                    lines.append(f"  {key} = {_toml(value)}")
            if line.interval is not None:
                lines.append(f"  interval = {_toml(line.interval)}")
            for key, value in (("width", line.width),
                               ("marker_size", line.marker_size),
                               ("gap_fraction", line.gap_fraction),
                               ("rotate", line.rotate)):
                if value is not None:
                    lines.append(f"  {key} = {_toml(value)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


#: How a comparison chart reduces each span. A year of five-minute readings
#: is not a chart, it is a hundred thousand points drawn over each other --
#: and N places multiplies that by N. These are the buckets the shipped
#: Seasons set already uses for its own week, month and year plots, so a
#: comparison and the per-place chart beside it are reduced the same way.
COMPARE_BUCKETS: dict[str, tuple[str, int | str | None]] = {
    "day": ("", None),
    "week": ("avg", "hour"),
    "month": ("avg", 10800),
    "year": ("avg", "day"),
}

#: What "cmp" separates in a generated name. Not a hyphen or a dot: a
#: manifest name is span-prefixed and a page matches `data-only` against
#: either the name or the span plus the name, so a character that is not a
#: letter or a digit in the middle of a name matches on one path and not the
#: other.
GENERATED = "cmp"

#: Readings that wrap, and the aggregate that means something for each. A
#: direction is not a quantity: `min`, `max` and `avg` all answer with a
#: number that is not in the data.
CIRCULAR = {"windDir": "vecdir", "windGustDir": "gustdir"}


def comparisons(places: list[str], observations: list[str],
                spans: list[str], existing: PlotSet | None = None,
                labels: dict[str, str] | None = None
                ) -> tuple[PlotSet, list[str]]:
    """One chart per (span, reading), one line per place.

    Generated rather than typed. Four readings by four spans by four places
    is sixty-four lines, and asking somebody to write those into a file by
    hand is the WeeWX arrangement this project removed -- the same argument
    that made `plots import` part of the work rather than a convenience.

    Returns `(plots, replaced)`. `plots` is the **whole set to write**:
    everything in `existing`, in its own order, with each generated chart put
    where the one it replaces stood and the rest appended in the order
    (span, reading) were asked for. `replaced` is the names of the existing
    plots the generated ones stood in for, so a caller can print them and
    write nothing until somebody says `--write`.

    Rewritten only where the name is one this function makes -- a span, then
    `cmp`, then a reading -- **and** every line of the plot already names a
    place. An overlay somebody wrote and edited is left exactly as it is, and
    a generated name whose plot is no longer all-places is left alone too:
    it keeps its place in the file, no chart is added under that name, and
    the log says which.

    Fewer than two places produces nothing. One place's chart of one place is
    the chart that is already there, and filing it as a comparison would give
    a single-series station a `series` key in its files and a place name over
    its own line -- output that must not change where there is one place.
    """
    kept = list(existing.plots) if existing is not None else []
    words = dict(existing.labels) if existing is not None else {}
    words.update(labels or {})

    if len(places) < 2:
        log.info("a comparison needs two places to compare and there %s %d; "
                 "nothing generated",
                 "is" if len(places) == 1 else "are", len(places))
        return PlotSet(kept, words), []

    known = set(SPANS) | set(spans)
    mine = {plot.name: position for position, plot in enumerate(kept)
            if _is_generated(plot, known)}

    replaced: list[str] = []
    for span in spans:
        for obs in observations:
            plot = _comparison(span, obs, places)
            standing = next((p for p in kept if p.name == plot.name), None)
            if standing is not None and plot.name not in mine:
                # A plot of this name that is not one of ours: somebody put a
                # home line in it, or wrote it themselves. Never overwritten,
                # and not added twice either -- a second [[plot]] under one
                # name is a file where the winner depends on the reader.
                log.warning("%r is already in the file and does not draw "
                            "places only, so it is left as it is",
                            plot.name)
                continue
            if standing is not None:
                kept[mine[plot.name]] = plot
                replaced.append(plot.name)
            else:
                kept.append(plot)
    return PlotSet(kept, words), replaced


#: What a site of several places compares when nobody has said otherwise.
#: The same four the bundled skin puts in the table above the charts, so the
#: figures and the shapes under them are about the same readings. A chart for
#: a sensor this station does not have is skipped when the feeds run, so a
#: list that is too long costs nothing and a list that is too short leaves a
#: page empty.
COMPARE_READINGS = ("outTemp", "outHumidity", "windSpeed", "rain")


def implied(existing: PlotSet, places: list[str],
            observations: Iterable[str] = (),
            spans: Iterable[str] = ()) -> PlotSet:
    """The set to draw with, with the missing comparison charts filled in.

    Worked out rather than written, and this is the difference from
    `comparisons()`: nothing reaches `plots.toml`. The same reasoning as
    `Register.presented()`, which fills in a colour nobody chose without
    saving it -- write these into the file and a later release's set, with
    another reading in it or a better bucket, reaches no installation that
    ever had two places. It also means there is nothing to migrate and
    nothing to remember: two places, and the charts are there.

    A name already in the file is left exactly as it is, never replaced. That
    is what `plots compare --write` is for: it puts them in the file, and
    from then on they are the operator's -- edited axes, a title, a line
    removed, all of it kept.

    Fewer than two places adds nothing. One place compared with itself is the
    chart that is already there.

    Returns a new set; `existing` is not touched. The names it added are in
    `.implied` on the result.
    """
    kept = list(existing.plots)
    if len(places) < 2:
        return PlotSet(kept, existing.labels)

    have = {plot.name for plot in kept}
    added: list[str] = []
    for span in tuple(spans) or tuple(COMPARE_BUCKETS):
        for obs in tuple(observations) or COMPARE_READINGS:
            plot = _comparison(span, obs, places)
            if plot.name in have:
                continue
            kept.append(plot)
            added.append(plot.name)
    return PlotSet(kept, existing.labels, added)


def _is_generated(plot: Plot, spans: set[str]) -> bool:
    """Whether this plot is one `comparisons()` wrote and may rewrite."""
    head, sep, tail = plot.name.partition(GENERATED)
    if not sep or not tail or head not in spans:
        return False
    # And every line names a place. This is the half that matters: the name
    # is a convention and a person can type it, but a plot all of whose lines
    # name a place is one nothing else produces.
    return bool(plot.lines) and all(line.series for line in plot.lines)


def _comparison(span: str, obs: str, places: list[str]) -> Plot:
    """One reading at every place, over one span."""
    from . import units

    aggregate, interval = COMPARE_BUCKETS.get(span, ("avg", "day"))
    if units.group_of(obs) == "group_rain":
        # A total, not a level: `avg` over an hour of rain counters is a
        # number nobody wants, and left un-aggregated a day chart draws the
        # increments between records.
        aggregate, interval = "sum", interval or "hour"

    circular = obs in CIRCULAR
    if circular and aggregate:
        # Never `avg`: the arithmetic mean of 359 and 1 is 180, which is the
        # opposite direction. `vecdir` is where the air actually went over
        # the bucket, weighted by how hard it blew, and `gustdir` is the
        # direction of the hardest gust in it. Over a day there is no bucket
        # and the records are drawn as they are, which is what the shipped
        # windDir plot does.
        aggregate = CIRCULAR[obs]
    return Plot(
        name=f"{span}{GENERATED}{obs}",
        span=span,
        time_length=SPANS.get(span, SPANS["day"]),
        # 0 to 360 fixed, because 358, 359, 1 is a fall through the whole
        # height of a chart whose axis was fitted to the data. It is the same
        # correction `grafana/style.py` carries, and the rest of it -- points
        # rather than a connected line -- is the renderer's, because nothing
        # in a plot definition can say it.
        yscale=([0.0, 360.0, 45.0] if circular else [None, None, None]),
        # Never shaded: a comparison has no single sun, and `chartdata`
        # refuses it anyway. Never `skip_if_empty` either: a reading one
        # place does not have is a line to leave out with a reason, and
        # deleting the chart for it takes the comparison away from the two
        # places that do have it.
        lines=[Line(obs=obs, series=name, aggregate=aggregate,
                    interval=interval) for name in places],
    )

# -- bringing plots over from WeeWX ----------------------------------------

@dataclass
class Imported:
    """What an import found, and what it did not take."""

    plots: PlotSet = field(default_factory=PlotSet)
    #: Options that describe a picture. Named rather than silently dropped.
    drawing: set[str] = field(default_factory=set)
    #: Options nothing here understands at all.
    unknown: set[str] = field(default_factory=set)
    #: Sections that looked like plot groups but held nothing.
    empty: list[str] = field(default_factory=list)

    def report(self, source: str) -> str:
        """What happened, as something to read before trusting it."""
        out = [f"Read {len(self.plots)} plot(s) from {source}"
               + (f", and {len(self.plots.labels)} label(s)."
                  if self.plots.labels else ".")]
        groups = self.plots.by_span()
        for span in sorted(groups):
            names = ", ".join(p.name for p in groups[span])
            out.append(f"  {span}: {len(groups[span])} -- {names}")
        if self.empty:
            out.append("")
            out.append("Skipped, because they defined no lines:")
            out.append("  " + ", ".join(self.empty))
        if self.drawing:
            out.append("")
            out.append("Left behind, because they describe a picture and this")
            out.append("produces data:")
            out.append("  " + ", ".join(sorted(self.drawing)))
        if self.unknown:
            out.append("")
            out.append("Not understood, and so not carried over:")
            out.append("  " + ", ".join(sorted(self.unknown)))
        return "\n".join(out)


def labels_from(conf: dict[str, Any]) -> dict[str, str]:
    """What a WeeWX skin calls each reading: `[Labels] [[Generic]]`.

    Worth carrying across on its own. Somebody who renamed `extraTemp3` to
    "Greenhouse" eight years ago should not have to remember which one it was.
    """
    labels = conf.get("Labels")
    if not isinstance(labels, dict):
        return {}
    generic = labels.get("Generic")
    source = generic if isinstance(generic, dict) else labels
    return {key: str(value).strip().strip("\"'")
            for key, value in source.items()
            if isinstance(value, str) and value.strip()}


def from_image_generator(section: dict[str, Any],
                         labels: dict[str, str] | None = None) -> Imported:
    """Plots out of a WeeWX `[ImageGenerator]` section.

    The structure there is three deep: a group of plots (`[[day_images]]`), a
    plot (`[[[daytempdew]]]`), and a line (`[[[[outTemp]]]]`). Options
    inherit downwards, so a `time_length` on the group applies to every plot
    in it unless the plot says otherwise -- that is `accumulateLeaves` in
    WeeWX, and getting it wrong produces plots that all cover one day.
    """
    result = Imported()
    result.plots.labels.update(labels or {})
    top = {k: v for k, v in section.items() if not isinstance(v, dict)}
    _note_options(top, result)

    for group_name, group in section.items():
        if not isinstance(group, dict) or not _holds_plots(group):
            continue
        span = _span_of(group_name)
        group_options = {**top,
                         **{k: v for k, v in group.items()
                            if not isinstance(v, dict)}}
        _note_options(group_options, result)

        for plot_name, definition in group.items():
            if not isinstance(definition, dict):
                continue
            options = {**group_options,
                       **{k: v for k, v in definition.items()
                          if not isinstance(v, dict)}}
            lines = []
            for line_name, line_def in definition.items():
                if not isinstance(line_def, dict):
                    continue
                lines.append(_line_from(line_name, {**options, **line_def}))
            if not lines:
                result.empty.append(plot_name)
                continue
            result.plots.add(Plot(
                name=plot_name,
                span=span,
                time_length=_weewx_span(options.get("time_length"),
                                        SPANS.get(span, 97200)),
                lines=lines,
                title=str(options.get("title", "")),
                show_daynight=_truth(options.get("show_daynight")),
                yscale=_yscale(options.get("yscale")),
                skip_if_empty=_span_name(options.get("skip_if_empty")),
            ))
    return result


#: The image width a line width is understood against. WeeWX's classic size,
#: and what a plot definition means by "3 pixels".
REFERENCE_WIDTH = 500.0


def _scaled(value: Any, image_width: Any) -> float | None:
    """A pixel measurement, taken off the image it was written for.

    A skin drawing at 1000 wide and asking for a 3-pixel line means a thin
    one. Read as 3 pixels of a 500-wide chart and then doubled for a
    high-resolution file, the same number comes out four times too heavy --
    which is what a day plot looked like: a smear rather than a line.

    So the number is carried across as a fraction of the width it was
    written against. Nothing else about the image survives the import, and
    this does not either: it is folded into the line and the image size is
    still left behind.
    """
    number = _float(value)
    if number is None:
        return None
    written_for = _float(image_width)
    if not written_for or written_for <= 0:
        return number
    return round(number * REFERENCE_WIDTH / written_for, 3)


def _line_from(name: str, options: dict[str, Any]) -> Line:
    """One `[[[[outTemp]]]]` subsection.

    The section name is the reading unless `data_type` says otherwise, which
    is how WeeWX draws the same reading twice in one plot with two different
    aggregations.
    """
    kind = str(options.get("plot_type", "line")).strip().strip("'\"").lower()
    kind = kind if kind in KINDS else "line"
    # 'none' is how a skin turns off an aggregation it inherited from the
    # group above it. Carried across as no aggregation, not as an aggregate
    # called none.
    aggregate = str(options.get("aggregate_type", "")).strip().strip("'\"").lower()
    if aggregate in ("none", "null"):
        aggregate = ""
    marker = str(options.get("marker_type", "")).strip().strip("'\"")
    return Line(
        obs=str(options.get("data_type") or name),
        label=str(options.get("label", "")),
        kind=kind,
        color=_color(options.get("color")),
        fill_color=_color(options.get("fill_color")),
        width=_scaled(options.get("width"), options.get("image_width")),
        aggregate=aggregate,
        interval=(_normalise(_weewx_span(options.get("aggregate_interval")))
                  if aggregate else None),
        marker="" if marker in ("none", "") else marker,
        marker_size=(_int(_scaled(options.get("marker_size"),
                                  options.get("image_width")))
                     if marker not in ("none", "") else None),
        gap_fraction=_float(options.get("line_gap_fraction")),
        # Inherited from the top of the section by every line, and meaningless
        # on all but one kind. Kept only where it does something.
        rotate=_float(options.get("vector_rotate")) if kind == "vector" else None,
        binding=str(options.get("data_binding", "")),
    )


def _note_options(options: dict[str, Any], result: Imported) -> None:
    """File away which options were about drawing and which were a mystery."""
    understood = {
        "time_length", "aggregate_type", "aggregate_interval", "plot_type",
        "color", "fill_color", "width", "label", "marker_type", "marker_size",
        "line_gap_fraction", "vector_rotate", "data_type", "data_binding",
        "yscale", "show_daynight", "skip_if_empty", "title", "y_nticks",
        "rose_label", "chart_line_colors", "chart_fill_colors", "stale_age",
        "log_success", "summarize_by", "aggregate", "unit",
    }
    for key in options:
        if key in understood:
            continue
        result.drawing.add(key) if _is_drawing(key) else result.unknown.add(key)


#: Prefixes that mean an option is about drawing a picture. Matched by shape
#: rather than by name: skins invent their own, and `rose_line_width` from one
#: nobody here has seen should be reported as left behind, not as a mystery.
DRAWING_PREFIXES = ("image_", "chart_", "rose_", "daynight_", "axis_label_",
                    "top_label_", "bottom_label_", "unit_label_", "x_label_",
                    "y_label_")


def _is_drawing(key: str) -> bool:
    """Whether an option describes a picture rather than what is in it."""
    if key in IMAGE_ONLY:
        return True
    if key == "rose_label":
        # The one exception: what the compass rose is labelled is text, and a
        # chart in a browser needs it as much as a PNG does.
        return False
    return (key.startswith(DRAWING_PREFIXES)
            or "_font" in key or key.endswith("_color"))


def _holds_plots(section: dict[str, Any]) -> bool:
    """Whether this section defines plots rather than merely holding settings.

    A group such as `[[day_images]]` has subsections that themselves have
    subsections: one per line. A settings block like `[[Archive]]` carries
    scalars only, so counting subsections alone would take it for a group.
    """
    return any(isinstance(v, dict) and any(isinstance(w, dict)
                                           for w in v.values())
               for v in section.values())


def _span_of(group_name: str) -> str:
    """`day_images` -> `day`. Anything else keeps its own name."""
    name = group_name.strip()
    for suffix in ("_images", "_plots", "_charts"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


# -- small conversions -----------------------------------------------------

def _seconds(value: Any, default: int = 97200) -> int:
    """A duration from whatever a file offered: 86400, '27h', 27.0."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return parse_duration(str(value).strip())
    except Exception:
        # WeeWX also takes 'day', 'week' and so on for a length.
        return NOMINAL.get(str(value).strip().lower(), default)


#: What WeeWX calls a nominal span. A month is not 30 days there; it is a
#: twelfth of 365.25 of them, which is what makes a year of monthly plots come
#: out with twelve buckets.
NOMINAL = {
    "hour": 3600, "day": 86400, "week": 604800,
    "month": int(365.25 / 12 * 86400), "year": int(365.25 * 86400),
}

#: WeeWX's duration suffixes, which are **not** weewx-evo's. There, a capital
#: M is a minute and a lowercase m is a *month*; here, as everywhere else in
#: this project, m is minutes. Both are defensible and they cannot both apply
#: to the same string, so: a file written for WeeWX is read by WeeWX's rules,
#: and nothing is ever written back with an ambiguous suffix. See `_normalise`.
_WEEWX_SUFFIX = {
    "M": 60, "h": 3600, "d": 86400, "w": 604800,
    "m": NOMINAL["month"], "y": NOMINAL["year"],
}


def _weewx_span(value: Any, default: int | None = None) -> int | None:
    """A duration written the way WeeWX writes them: 27h, 1w, 3d, 120M.

    Bare numbers are seconds, and the words 'hour' through 'year' are their
    own spans. Anything unreadable gives the default rather than a guess --
    an interval quietly turned into a day is a year plot with 365 points
    where it should have 52.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().strip("\"'")
    if not text:
        return default
    if text.lower() in NOMINAL:
        return NOMINAL[text.lower()]
    suffix = text[-1]
    if suffix in _WEEWX_SUFFIX:
        try:
            return int(float(text[:-1]) * _WEEWX_SUFFIX[suffix])
        except ValueError:
            return default
    try:
        return int(float(text))
    except ValueError:
        return default


def _normalise(seconds: int | None) -> int | str | None:
    """A span as a name where it is exactly one, and seconds otherwise.

    So an imported `1w` is stored as "week" rather than 604800, and `3h` as
    10800. Never as "1m": that means a month to WeeWX and a minute here, and a
    file that can be read two ways will eventually be read the wrong one.
    """
    if seconds is None:
        return None
    for word, length in NOMINAL.items():
        if seconds == length:
            return word
    return seconds


def _interval(value: Any) -> int | str | None:
    """An aggregation interval out of plots.toml, our rules.

    The calendar names stay names: a day is not always 86400 seconds, and the
    series reader treats the word and the number differently on purpose.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in NOMINAL:
            return text
        try:
            return parse_duration(text)
        except Exception:
            log.warning("%r is not an interval; ignoring it", value)
            return None
    return int(value)


def _color(value: Any) -> str:
    """A WeeWX color as CSS understands it.

    WeeWX takes '#RRGGBB', '0xBBGGRR' and English names. The first and last
    are already CSS; the middle one is byte-swapped and has to be turned
    around, which is the kind of thing that produces a blue chart where the
    PNG was red.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip().strip("\"'")
    if text.lower().startswith("0x"):
        try:
            bgr = int(text, 16)
            return f"#{bgr & 0xFF:02x}{(bgr >> 8) & 0xFF:02x}{(bgr >> 16) & 0xFF:02x}"
        except ValueError:
            return text
    return text


def _yscale(value: Any) -> list[Any]:
    """`None, None, 0.5` into [None, None, 0.5]."""
    if value is None:
        return [None, None, None]
    parts = value if isinstance(value, (list, tuple)) else [value]
    out: list[Any] = []
    for part in list(parts)[:3]:
        text = str(part).strip().strip("\"'")
        if text.lower() in ("none", ""):
            out.append(None)
        else:
            out.append(_float(text))
    while len(out) < 3:
        out.append(None)
    return out


def _span_name(value: object) -> str:
    """`skip_if_empty` as a span name, or empty for off.

    WeeWX accepts a boolean or a span there. `true` is taken to mean the
    plot's own span, which is the only reading of it that does anything.
    """
    if value is None or value is False:
        return ""
    if value is True:
        return "plot"
    text = str(value).strip().strip("\"'").lower()
    if text in ("", "false", "no", "0", "off", "none"):
        return ""
    if text in ("true", "yes", "1", "on"):
        return "plot"
    return text if text in NOMINAL else "plot"


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().strip("\"'").lower() in ("true", "yes", "1", "on")


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip().strip("\"'"))
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _float(value)
    return None if number is None else int(number)


def _duration(seconds: int) -> str:
    from .options import format_duration

    return format_duration(seconds)


def _toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'

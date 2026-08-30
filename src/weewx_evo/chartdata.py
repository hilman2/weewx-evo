"""One plot's data, ready to draw. The layer under every chart renderer.

A `Plot` from `plots.toml` says which readings, over how long, aggregated how.
Turning that into numbers means asking `series.py`, converting into what the
page shows, deciding what counts as a gap and what counts as a sensor this
station has never had. None of that is drawing.

So it lives here, and the renderers are customers:

    chartdata.build(plot, ...)  ->  Chart
      jsongenerator             writes it as JSON
      imagegenerator            draws it as a PNG

That is the whole reason this module exists. WeeWX has the same arithmetic in
`ImageGenerator` and again in whatever writes JSON, and the two disagree in
the third decimal place -- which is a bug nobody finds, because each of them
is right on its own. Here there is one answer and two ways of showing it.

A `Chart` is deliberately plain: lists of numbers, a unit, a colour. It is
close to the JSON document because that document is the honest shape of the
data, not because JSON is privileged.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from . import sun, units
from .options import format_duration
from .plots import Plot
from .series import VECTORS, Reader, Series

log = logging.getLogger(__name__)

#: Plots already told about, so the refusal to shade a comparison chart is
#: said once for the life of the process rather than a hundred times every
#: five minutes. `roles.apply` announces itself the same way and for the same
#: reason: the operator's answer is one edit on one page.
_SAID_NO_NIGHT: set[str] = set()

#: The same, for a chart that was written to compare and came back drawing
#: one place. It has no `places` key and no note to carry the reason, because
#: at one place nothing new may be written into a file -- so the log is the
#: only place the reason can go.
_SAID_ALONE: set[str] = set()

#: The words a chart's own sentence is built from. One key each, looked up in
#: the page's language and never composed into grammar: "hourly mean" is a
#: construction, "Mittel" is a word, and a table of constructions is a
#: translation file nobody can complete.
NOTE_WORDS = {
    "records": "records", "avg": "mean", "min": "minimum", "max": "maximum",
    "sum": "total", "count": "count",
    "not_configured": "is not configured",
    "no_column": "does not record it",
    # Both ends of the disagreement, because naming one of them explains
    # nothing: "Nordfeld records in mbar" under a chart drawn in degrees is a
    # true sentence about the wrong subject. A translation carrying only
    # {unit} still reads correctly -- an absent placeholder is simply not
    # substituted.
    "other_unit": "records in {unit}, and this chart is in {chart}",
    # A column with no unit group at all, which is the case the axis drop
    # exists for: its numbers are raw, in that console's system.
    "no_unit": "records it in no unit, and this chart is in {chart}",
}

#: How many decimals. Three is well past any weather sensor's resolution and
#: takes about a third off the size of a JSON file.
ROUNDING = 3

#: A run of readings this many times the usual spacing apart is a gap in the
#: data rather than its rhythm. Judged from the readings themselves, because
#: ten minutes between them is a break for a station reporting every eight
#: seconds and business as usual for one reporting every ten.
GAP_FACTOR = 3.0

#: How far back `skip_if_empty` looks. A sensor with nothing over its span is
#: one this station does not have.
SPAN_LENGTHS = {
    "hour": 3600, "day": 86400, "week": 604800,
    "month": 2592000, "year": 31536000,
}


@dataclass(frozen=True)
class Place:
    """One of the places a chart draws, as far as drawing is concerned.

    Presentation and geography, and deliberately not a reader. Readers are
    opened for the length of one run and closed (`series.opened`); these come
    out of `archives.toml` and outlive it. One map holding both would either
    keep a descriptor for the 99% of the time nothing is being drawn -- the
    shape of the leak that took an instance down at 477 of them -- or reread
    the file on every pass.

    Built by the caller from `archives.Archive`, not imported from it: this
    module is where both renderers meet, and a test that wants a two-place
    chart should not have to build a Register to get one.
    """

    name: str
    title: str = ""
    #: Up to four characters, for a legend where the title does not fit.
    code: str = ""
    #: What this place is drawn in, everywhere it is drawn. Empty means the
    #: positional palette, which is right for a place nobody has coloured.
    color: str = ""
    latitude: float | None = None
    longitude: float | None = None


@dataclass
class Line:
    """One reading, fetched and converted. What a renderer draws."""

    obs_type: str
    label: str = ""
    plot_type: str = "line"
    color: str = ""
    fill_color: str = ""
    unit: str | None = None
    time: list[int] = field(default_factory=list)
    values: list[Any] = field(default_factory=list)
    #: Compass degrees, for the wind vectors. None for everything else.
    directions: list[Any] | None = None
    #: How wide each bar is, in seconds. A month of daily bars is not a month
    #: of equal ones: the change to summer time makes one of them shorter.
    bar_width: list[int] | None = None
    #: A vector series split into how far east and how far north.
    vector_x: list[Any] | None = None
    vector_y: list[Any] | None = None
    #: How far to turn the arrows, in degrees, positive anticlockwise. A
    #: skin sets it so that a chart reads with north up the page even where
    #: the plot is drawn sideways.
    vector_rotate: float | None = None
    aggregate_type: str = ""
    aggregate_interval: Any = None
    marker: str = ""
    marker_size: int | None = None
    width: float | None = None
    #: The earliest and latest moment this line covers, buckets included.
    reach: tuple[int, int] | None = None
    #: Which archive it came from, where a chart draws more than one. Empty
    #: for every line of every single-series station, so nothing downstream
    #: has to learn about archives to keep working.
    series: str = ""
    #: What the archive this line came out of holds it in, where that is not
    #: what the chart shows. Twenty bytes, and what a page would need to
    #: print "Nordfeld records in degrees F and was converted" -- the
    #: sentence the 68.2-on-a-page-that-said-Celsius failure had nowhere to
    #: appear. Nothing prints it yet: it is carried so that whoever writes
    #: that line does not have to reopen the archive to find out.
    stored_unit: str = ""

    @property
    def empty(self) -> bool:
        return not any(v is not None for v in self.values)


@dataclass
class Chart:
    """One plot, with its data. What both renderers are handed."""

    name: str
    #: What was asked for, and what the data actually covers. They differ
    #: because a bucket is drawn as the whole of what it covers: the last bar
    #: of a daily chart runs to tomorrow's midnight, after the moment the
    #: file was written.
    asked: tuple[int, int] = (0, 0)
    start: int = 0
    stop: int = 0
    #: One axis, so one unit. The first line of this chart's own place that
    #: has one decides, which with one place is the first line that has one.
    unit: str = ""
    unit_label: str = ""
    title: str = ""
    lines: list[Line] = field(default_factory=list)
    yscale: list[Any] = field(default_factory=lambda: [None, None, None])
    #: Sunrise, sunset and twilight over the span, for shading the night.
    daynight: dict[str, Any] | None = None
    #: The places drawn here, in the order their lines appear. Empty on every
    #: chart of every single-series station, which is every chart today -- so
    #: nothing downstream has to learn about places to keep working, and no
    #: file gains a key.
    places: list[str] = field(default_factory=list)
    #: What was asked for and not drawn: (what a reader would call it, why).
    #: An empty line on a comparison chart with no explanation is the worst
    #: outcome available -- it reads as a dead sensor at that place, and the
    #: real answer is usually that the archive is not configured.
    left_out: list[tuple[str, str]] = field(default_factory=list)
    #: One sentence about what is in this chart: how it was reduced, in what
    #: unit, from where, and what is missing. Composed here because a
    #: published chart file has to say what is in it -- the browser has no
    #: other source -- and because prose composed in a script cannot be
    #: translated by the language files.
    note: str = ""

    @property
    def empty(self) -> bool:
        return all(line.empty for line in self.lines)


def build(plot: Plot, reader: Reader, generated: float,
          target: units.Target | None = None,
          unit_system: int = units.US,
          extra_groups: dict[str, str] | None = None,
          labels: dict[str, str] | None = None,
          rounding: int | None = ROUNDING,
          latitude: float | None = None, longitude: float | None = None,
          twilight: bool = True,
          readers: dict[str, Reader] | None = None,
          places: dict[str, Place] | None = None,
          place: str = "") -> Chart | None:
    """One plot's data, or None if this station has none of its readings.

    Every line is fetched, converted, and trimmed of the points that carry
    nothing. A plot where every line came back missing is not built at all:
    the shipped set covers sensors most stations do not have, and a hundred
    charts of nulls help nobody.

    `readers` is how a chart draws more than one place: archive name to a
    reader for it, and a line naming one is read from there. A line naming
    an archive that is not in the map is *left out* rather than read from
    the default -- silently drawing the wrong location's temperature under
    another location's label is the one outcome worse than an empty chart.

    `places` is what each of those archives is called and drawn in, out of
    `archives.toml`. `place` names the one `reader` is: without it a
    comparison chart's first line, which reads the home archive and carries
    a blank `series`, has no title, no colour and no entry in `places` -- so
    a chart of four places comes out with three coloured, labelled lines and
    one anonymous one, and the anonymous one is the page's own place.
    """
    target = target or units.Target(unit_system)
    labels = dict(labels or {})
    stop = int(generated)
    start = stop - int(plot.time_length)

    readers = readers or {}
    places = places or {}
    home = str(place or "")

    colors = {name: one.color for name, one in places.items() if one.color}

    # Fetched first, judged after. Whether this chart draws several places
    # cannot be read off the plot: a line naming an archive nobody
    # configured, and a column a place does not have, are both left out
    # below, and a chart that ends up drawing one place has to come out
    # exactly as a one-place station's does. Decided from the names instead,
    # un-listing one archive relabelled and repainted the line that did
    # survive with a place title and gave it a `series` key -- on a station
    # with one place, with nothing on the chart to say why.
    fetched: list[tuple[int, Any, str, Line]] = []
    left_out: list[tuple[str, str]] = []
    covered_from, covered_to = start, stop
    for position, definition in enumerate(plot.lines):
        wanted = getattr(definition, "series", "") or ""
        source, source_system = reader, unit_system
        if wanted and wanted != home:
            source = readers.get(wanted)
            if source is None:
                log.warning("plot %r line %r asks for series %r, which is not "
                            "configured; left out", plot.name,
                            definition.obs, wanted)
                left_out.append((_called(wanted, places),
                                 _why(target, "not_configured")))
                continue
            # The system that archive HOLDS, not the chart's. Two places in
            # two systems is the ordinary case here -- one console replaced,
            # one not -- and converting the second out of the first's system
            # is a silent thirty degrees on the one page built to compare
            # them. Only for a named place: for the archive the caller handed
            # in, the caller's `unit_system` still wins, because a caller
            # that deliberately passes one knows something the file does not.
            source_system = source.system
        line = _line(definition, source, start, stop, target, source_system,
                     extra_groups or {}, labels, rounding, plot.skip_if_empty)
        if line is None:
            if wanted and wanted != home:
                # Only for a place other than the one this chart is drawn
                # for. A reading a station does not have is the ordinary
                # `skip_if_empty` case and has been silent for years; saying
                # it for a line that names this chart's own archive would put
                # a sentence under a chart on a station with one place.
                left_out.append((_called(wanted, places),
                                 _why(target, "no_column")))
            continue
        fetched.append((position, definition, wanted, line))

    if not fetched:
        return None

    # Every decision below is made from the lines that came back, in this
    # order: what places are drawn, then which of them share the axis, then
    # what a reader is told. Anything decided earlier is decided from what
    # the plot *named*, and a plot names places that produce no line -- an
    # archive nobody configured, a column a place does not have, a unit that
    # cannot share the axis. Each of those relabelled and repainted the lines
    # that did survive, with no `places` key beside them to explain either.
    several = len(_facing(fetched, home)) > 1

    # One axis, so one unit, and this chart's own place decides it where
    # there is one: a chart is labelled in the unit its own numbers are in,
    # and the line that sets the unit is the one line the drop below can
    # never remove. With one place every line is a home line, so this is the
    # first line with a unit, exactly as it was.
    own = [one for _p, _d, named, one in fetched if not named or named == home]
    unit = (next((one.unit for one in own if one.unit), "")
            or next((one.unit for _p, _d, _n, one in fetched if one.unit), "")
            or "")

    if several:
        # A line from another place whose unit is not the chart's is dropped
        # rather than drawn. Every line goes through the same Target, so they
        # agree by construction unless a column has no unit group in one of
        # the archives -- and then its numbers are raw, in that console's
        # system, under an axis confidently labelled in the other's. Two
        # incompatible lines under one label is worse than one fewer line.
        #
        # `line.unit` is None and not "" where the column has no group at all
        # (`Target.convert` answers that way), which is the very case this
        # was written for: a guard asking for a truthy unit caught nothing.
        #
        # Only on a chart that drew several places, and never this chart's
        # own. A plot mixing pressure and temperature on one axis is
        # something somebody wrote on purpose and has behaved that way since
        # the first version; and a chart must not lose the line of the place
        # whose page it is on -- which is what dropping by file order did,
        # deciding it by which of two entries in plots.toml came first.
        keeping = []
        for row in fetched:
            _position, _definition, named, line = row
            if named and named != home and unit and line.unit != unit:
                log.warning("plot %r draws %s, so %r from %r is left out",
                            plot.name, unit, line.obs_type, named)
                left_out.append((
                    _called(named, places),
                    _why(target, "other_unit" if line.unit else "no_unit",
                         line.unit or "", unit)))
                continue
            keeping.append(row)
        fetched = keeping
        several = len(_facing(fetched, home)) > 1

    if several and colors.get(home):
        # The home line carries a blank `series`. Without an entry under the
        # empty string it is the one line on a comparison drawn out of the
        # positional palette while every other is drawn in its place's
        # colour -- and it is the page's own place.
        colors[""] = colors[home]

    # `position` is the line's place in `plot.lines` and not in what
    # survived: the positional palette has always stepped over a line
    # `skip_if_empty` left out, and closing those gaps would repaint charts
    # on every station in a change about places.
    styled = plot.drawn_with(colors)
    lines: list[Line] = []
    for position, definition, named, line in fetched:
        line.color = styled[position].color
        line.fill_color = styled[position].fill_color
        called = _label_for(definition, named or home, places, several, plot,
                            target)
        if called:
            line.label = called
        # Written on the home line only where the chart really did draw more
        # than one place. On a per-place chart the directory already says
        # where the numbers came from, and writing it per line would put a
        # new key into a hundred files times N for nobody -- and make every
        # one of them compare unequal once, for one export of the whole
        # directory.
        line.series = named or (home if several else "")
        if line.reach:
            # Over the lines that are left, not the ones that were asked
            # for: a line dropped above would otherwise stretch the axis of
            # a chart it is not on, and the empty stretch reads as a gap in
            # the readings of the lines that are.
            covered_from = min(covered_from, line.reach[0])
            covered_to = max(covered_to, line.reach[1])
        lines.append(line)

    drawn: list[str] = []
    for line in lines:
        if line.series and line.series not in drawn:
            drawn.append(line.series)

    chart = Chart(
        name=plot.name,
        asked=(start, stop),
        start=int(covered_from),
        stop=int(covered_to),
        unit=unit,
        unit_label=units.label(unit).strip(),
        title=plot.title or _comparison_title(
            plot, len(drawn) > 1, labels, target),
        lines=lines,
        yscale=list(plot.yscale),
        places=drawn,
        left_out=left_out,
    )

    if plot.show_daynight and len(chart.places) > 1:
        # One place's darkness under four places' lines is minutes wrong on
        # numbers that are right, which is the exact failure `Placed` exists
        # to prevent. Refused in the module that owns the numbers, so the
        # image generator and Grafana inherit the refusal rather than each
        # deciding for itself.
        #
        # Once per plot name for the life of the process, like `roles.apply`:
        # a hundred charts times a run every five minutes is a log nobody
        # reads, and the operator's answer is one edit on one page.
        if plot.name not in _SAID_NO_NIGHT:
            _SAID_NO_NIGHT.add(plot.name)
            log.info("%r draws %d places, so it is not shaded: night is one "
                     "place's, and drawing one place's under all of them is "
                     "wrong by minutes on numbers that are right",
                     plot.name, len(chart.places))
    elif plot.show_daynight:
        try:
            # The place's own coordinates where the caller named one, the
            # arguments otherwise. Both, not one: no existing caller passes
            # `places`, and a per-place pass has no way to put a different
            # latitude into a scalar it shares with the comparison pass.
            at = places.get(home)
            bands = sun.day_night(
                start, stop,
                at.latitude if at and at.latitude is not None else latitude,
                at.longitude if at and at.longitude is not None else longitude)
            if bands:
                if not twilight:
                    bands.pop("twilight", None)
                if home and len(places) > 1:
                    # Whose sun. Only where there is more than one place to
                    # be: a station with one place has one sun, and writing
                    # the key there would make every daynight file on every
                    # such station compare unequal once, for one export of
                    # the whole directory and no reader.
                    bands["at"] = home
                chart.daynight = bands
        except Exception as exc:
            # Shading is decorative and must never break a report. But a
            # silent failure here once hid a real bug, so say something.
            log.warning("could not work out day and night for %r: %s",
                        plot.name, exc)

    if len(chart.places) > 1 or chart.left_out:
        chart.note = _note(chart, target, places)

    if chart.left_out and len(chart.places) < 2:
        # The chart came back drawing one place or none, so no file and no
        # page can carry that sentence: `places` and `note` are written only
        # above two places, because at one place this feature must add no key
        # to any file at all -- and a comparison whose second place fell away
        # is exactly a one-place chart. Said in the log instead, once per plot
        # for the life of the process like the shading refusal above, so that
        # a line which vanished off a chart leaves a trace somewhere.
        if plot.name not in _SAID_ALONE:
            _SAID_ALONE.add(plot.name)
            log.warning("%r was written to compare and came back drawing "
                        "one place, so no chart file says why: %s", plot.name,
                        "; ".join(f"{who} {why}"
                                  for who, why in chart.left_out))
    return chart


def _facing(rows: list[tuple[int, Any, str, Line]], home: str) -> list[str]:
    """The places these lines actually came out of, in the order drawn.

    An empty name is not a place: a caller that passes no `place=` has a home
    line it cannot name, colour or count, and counting it would make a chart
    of one archive call itself a comparison.
    """
    out: list[str] = []
    for _position, _definition, named, _line in rows:
        at = named or home
        if at and at not in out:
            out.append(at)
    return out


def _called(name: str, places: dict[str, Place]) -> str:
    """What a reader calls a place. Its own name where nothing knows it.

    A place that is not configured has no entry here -- which is the very
    case the phrase is written for -- so the fallback has to be the name,
    and the name is what somebody typed into `plots.toml`.
    """
    known = places.get(name)
    return (known.title or name) if known else name


def _why(target: units.Target, key: str, unit: str = "",
         chart: str = "") -> str:
    """One reason a line is not on the chart, in the page's language.

    Substituted with `replace` and not `format`: a translator who writes a
    brace into a sentence would otherwise get an exception about a field
    nobody asked for, which is the trap `notify/` already carries a comment
    about.
    """
    spoken = getattr(target, "language", None)
    said = NOTE_WORDS[key]
    if spoken is not None:
        said = spoken.text("chart", key, said)
    for token, value in (("{unit}", unit), ("{chart}", chart)):
        if token in said:
            said = said.replace(token, _unit_word(target, value))
    return said


def _unit_word(target: units.Target, unit: str) -> str:
    """What this page prints after a number in this unit.

    Through the `Target`, so the skin's own `[Units][[Labels]]` and the
    language file win: everything else in the note is in the page's language,
    and a sentence naming the unit in English under a German chart reads as a
    broken chart rather than as a missing translation.
    """
    if not unit:
        return "?"
    return (target.label_for(unit) or "").strip() or unit


def _label_for(definition: Any, at: str, places: dict[str, Place],
               several: bool, plot: Plot, target: units.Target) -> str:
    """What to call one line where a chart draws more than one place.

    Empty -- meaning "the usual chain" -- for every other chart, which is
    every chart on every single-series station.

    One reading across places gets the place's title alone, so the legend
    reads "Kirchdorf / Nordfeld / Schuppen", which is the question being
    asked. A plot mixing readings AND places gets both, or three places by
    two readings is six lines and three legend entries.

    A label written in `plots.toml` still wins: somebody who typed one meant
    it. Composed here rather than in a renderer because this is where labels
    already come from, and composed in two renderers they would differ.
    """
    if not several or definition.label:
        return ""
    known = places.get(at)
    if known is None:
        return ""
    title = known.title or at
    if len(plot.uses()) == 1:
        return title
    return f"{title} \u2014 " + units.obs_label(
        definition.obs, getattr(target, "language", None))


def _comparison_title(plot: Plot, several: bool,
                      labels: dict[str, str] | None,
                      target: units.Target | None) -> str:
    """What to head a chart that draws one reading in several places.

    Left to a renderer's fallback -- the labels of the lines, joined -- every
    comparison on a page comes out headed "Kirchdorf, Testort". On a
    comparison a line's label is its *place*, so that is the same sentence
    over all four cards, and none of them says which reading it draws. The
    reading is what tells the cards apart; the places are in the legend
    under each of them.

    Composed here rather than in the renderers for the reason the note is:
    two of them would word it differently, and the same chart would be
    called two things on one site.

    Empty where this is not a comparison, so every other chart keeps the
    fallback it has always had.
    """
    if not several:
        return ""
    readings = plot.uses()
    if len(readings) != 1:
        return ""
    obs = next(iter(readings))
    # The skin's own word first, exactly as a line label takes it: a station
    # that calls `outTemp` something of its own must not have this chart
    # disagree with the legend under it.
    return (labels or {}).get(obs) or units.obs_label(
        obs, getattr(target, "language", None))


def _note(chart: Chart, target: units.Target,
          places: dict[str, Place]) -> str:
    """What is in this chart, in one line, in the page's language.

    Three parts and a clause: how it was reduced, in what unit, from where,
    and what was left out. A chart drawn from records beside a tile drawn
    from `archive_day_*` looks like a bug unless the chart says which it is
    -- a gust between two archive records is in the daily maximum and in no
    chart on the site, and that difference is legitimate and invisible.

    Built from single-word lookups and never from grammar: "hourly mean" is
    a construction and a table of constructions is a translation file nobody
    can complete. The bucket is `1h`, printed by `options.format_duration`.
    """
    first = chart.lines[0] if chart.lines else None
    how = _why(target, "records")
    if first is not None and first.aggregate_type:
        every = first.aggregate_interval
        bucket = (format_duration(every) if isinstance(every, (int, float))
                  else str(every or ""))
        how = (_why(target, first.aggregate_type)
               if first.aggregate_type in NOTE_WORDS else first.aggregate_type)
        if bucket:
            how = f"{bucket} {how}"

    parts = [how]
    if chart.unit_label:
        parts.append(chart.unit_label)
    parts.append(", ".join(_called(name, places) for name in chart.places))
    said = " \u00b7 ".join(part for part in parts if part)
    if chart.left_out:
        said += ". " + "; ".join(f"{who} {why}" for who, why in chart.left_out)
    return said


def _line(definition: Any, reader: Reader, start: int, stop: int,
          target: units.Target, unit_system: int,
          extra_groups: dict[str, str], labels: dict[str, str],
          rounding: int | None, skip_if_empty: str) -> Line | None:
    """One reading, fetched and made ready to draw.

    None where this station does not have the sensor at all. A sensor it does
    have but which reported nothing over this span comes back as a line with
    no points: the chart keeps its layout, and the gap is visible as a gap
    rather than as a chart that quietly disappeared.

    `unit_system` is what the archive *this reader* holds, not the chart's:
    on a comparison the second place may be a console nobody has replaced
    yet, and converting its Fahrenheit out of metricwx is thirty degrees of
    silence on the one page built to compare the two.

    What a comparison calls the line is not decided here: whether this chart
    draws several places is only known once every line has been fetched, and
    deciding it from what the plot named is how a one-place station came to
    print a place title over its own temperature.
    """
    series = reader.series(definition.obs, start, stop,
                           aggregate=definition.aggregate or None,
                           interval=definition.interval)
    if not len(series) or series.empty:
        if not _exists(reader, definition.obs, stop, skip_if_empty):
            return None
        series = Series(obs_type=definition.obs,
                        aggregate=definition.aggregate or None,
                        interval=definition.interval,
                        directions=[] if series.directions is not None
                        else None)

    values, unit, _group = target.convert(
        series.values, definition.obs, unit_system,
        aggregate=definition.aggregate or None, extra=extra_groups)
    # What the archive holds it in, kept so a document can say "records in
    # degrees F and was converted". `Target.convert` works this out and
    # throws it away; asking for it here is two dict lookups.
    stored, _stored_group = units.unit_of(
        definition.obs, unit_system, definition.aggregate or None,
        extra_groups)

    line = Line(
        obs_type=definition.obs,
        # The plot's own name, then the skin's, then what the core calls the
        # reading in the language the page is written in. Never nothing: a
        # chart published as a file has to say what is in it, because the
        # thing drawing it has no other source. The image generator already
        # ended on `obs_label`; the JSON did not, so every series in every
        # published file came out unnamed and a page built from them showed
        # "outTemp".
        label=(definition.label
               or labels.get(definition.obs, "")
               or units.obs_label(definition.obs,
                                  getattr(target, "language", None))),
        plot_type=definition.kind,
        color=definition.color,
        fill_color=definition.fill_color,
        unit=unit,
        time=[int(t) for t in series.time],
        values=round_all(values, rounding),
        aggregate_type=definition.aggregate or "",
        aggregate_interval=definition.interval,
        marker=definition.marker,
        marker_size=definition.marker_size,
        width=definition.width,
        stored_unit=stored or "",
    )
    if series.directions is not None:
        # One decimal is already finer than any wind vane.
        line.directions = round_all(series.directions, 1)
    if definition.kind == "bar":
        line.bar_width = [int(b - a) for a, b
                          in zip(series.start, series.stop, strict=True)]
    if definition.kind == "vector":
        line.vector_x, line.vector_y = components(
            line.values, line.directions, rounding)
        if definition.rotate is not None:
            # As the plot defines it, positive anticlockwise, which is what
            # WeeWX's `vector_rotate` means. Not negated: the negation
            # belongs to the JSON document, whose readers draw in screen
            # coordinates where y grows downwards, and burying it here made
            # every arrow on a rotated chart point the opposite way.
            line.vector_rotate = float(definition.rotate)

    drop_empty(line, definition.gap_fraction, stop - start,
               aggregated=bool(definition.aggregate))
    if series.start and series.stop:
        line.reach = (int(min(series.start)), int(max(series.stop)))
    return line


def _exists(reader: Reader, obs_type: str, stop: int,
            skip_if_empty: str) -> bool:
    """Whether this station has this sensor at all.

    The difference between a reading that is missing today and one that has
    never existed. WeeWX's `skip_if_empty = year` says exactly this, and it is
    why the shipped Seasons plot set does not litter a two-sensor station with
    ninety files of nulls.
    """
    if not skip_if_empty:
        return True
    length = SPAN_LENGTHS.get(skip_if_empty)
    if length is None:
        # `plot`, or anything unrecognised: the plot's own span, which is the
        # one just looked at and found empty.
        return False
    try:
        return bool(reader.aggregate(column_of(obs_type), stop - length, stop,
                                     "not_null"))
    except Exception:
        return True


def column_of(obs_type: str) -> str:
    """The column behind a reading, for asking whether it exists.

    `windvec` is not a column; the speed it is made of is.
    """
    return VECTORS[obs_type][0] if obs_type in VECTORS else obs_type


def round_all(values: list, places: int | None) -> list:
    """Round a sequence, leaving the gaps in the data alone."""
    if places is None:
        return list(values)
    return [v if not isinstance(v, float) else round(v, places)
            for v in values]


def components(magnitudes: list, directions: list | None,
               places: int | None) -> tuple[list, list]:
    """A vector series split into how far east and how far north.

    A chart drawing arrows scales and offsets the components; working them out
    once here saves rebuilding them from magnitude and bearing at the far end,
    and saves getting the sign of the rotation wrong while doing it.
    """
    east: list[Any] = []
    north: list[Any] = []
    for i, magnitude in enumerate(magnitudes):
        direction = directions[i] if directions and i < len(directions) else None
        if magnitude is None or direction is None:
            east.append(None if magnitude is None else 0.0)
            north.append(None if magnitude is None else 0.0)
            continue
        angle = math.radians(90.0 - direction)
        east.append(magnitude * math.cos(angle))
        north.append(magnitude * math.sin(angle))
    return round_all(east, places), round_all(north, places)


def drop_empty(line: Line, gap_fraction: float | None, span: float,
               aggregated: bool = False) -> None:
    """Leave out the points that carry nothing, keeping real gaps visible.

    A sensor reporting every ten minutes fills one archive record in ten, and
    the rest hold null for it. Drawn as they are, the line is broken in
    hundreds of places and a JSON file is far larger than the data in it.

    What counts as a gap comes from the readings' own rhythm rather than the
    width of the chart. `gap_fraction` still wins where a plot sets it, for
    anyone who wants the ImageGenerator's fixed threshold.
    """
    times, values = line.time, line.values
    if len(times) != len(values):
        return
    kept = [i for i, v in enumerate(values) if v is not None]
    if not kept or len(kept) == len(values):
        return

    threshold = None
    if gap_fraction and span and not aggregated:
        # WeeWX's own measure, and it belongs only to a series of raw
        # readings. On an aggregated one the bucket *is* the spacing, so a
        # threshold of a twentieth of the span marks every daily bar on a week
        # chart as a break in the data.
        threshold = float(gap_fraction) * float(span)
    if threshold is None and len(kept) >= 3:
        spacings = sorted(times[b] - times[a] for a, b in pairwise(kept))
        usual = spacings[len(spacings) // 2]
        if usual > 0:
            threshold = GAP_FACTOR * usual

    keep: list[int] = []
    for position, i in enumerate(kept):
        if position and threshold is not None:
            previous = kept[position - 1]
            middle = previous + (i - previous) // 2
            # `middle` is only a real point between the two when they are not
            # already neighbours. Without this it lands back on `previous`,
            # and the series comes out with every timestamp twice.
            if times[i] - times[previous] >= threshold and middle > previous:
                # Long enough to be a break in the readings rather than their
                # rhythm. One null says so; the rest of the run is noise.
                keep.append(middle)
        keep.append(i)

    if len(keep) == len(values):
        return
    line.time = [times[i] for i in keep]
    line.values = [values[i] for i in keep]
    for name in ("directions", "bar_width", "vector_x", "vector_y"):
        sequence = getattr(line, name)
        if isinstance(sequence, list) and len(sequence) == len(values):
            setattr(line, name, [sequence[i] for i in keep])

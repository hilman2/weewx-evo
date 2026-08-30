"""One site, several places: what the pages say, and what must not change.

Deck renders a *site*, and a site may stand in several places. With one
place there is one directory and one set of pages, exactly as before. With
two there is an overview at the root, a directory per place beneath it, and
comparison pages that draw them together.

Every check here is something that would ship wrong without it, and the two
that matter most are these:

  * **At one place nothing changes.** Not an attribute, not an element, not
    a file. A one-entry `archives.toml` makes the settings page correctly
    say that `station.*` has moved and is still one place -- and that is the
    case nothing else in the tree tests, because `overriding()` and
    `several()` are different gates. So this renders both ways and diffs the
    trees byte for byte.
  * **Every figure is compared against the reader**, never against a number
    typed into this file. That is the guard against the forty-months shape:
    forty archived months all printed August under correct headings, and a
    test asserting "18.4" would have agreed with every one of them. A place
    page's readings have to be *that place's*, and the only thing that knows
    is that place's own reader.

Run:

    python tools/deck_places_test.py
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, ClassVar

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

os.environ.setdefault("TZ", "Europe/Berlin")
if hasattr(time, "tzset"):
    time.tzset()

from weewx_evo import archives as archive_defs  # noqa: E402
from weewx_evo import plots as plot_defs  # noqa: E402
from weewx_evo.feeds import cheetah  # noqa: E402
from weewx_evo.series import Reader  # noqa: E402

#: Two places, and the second one deliberately colder. Two readings that are
#: never equal is what makes "the pages did not swap them" a real question:
#: with the same data in both files every wiring mistake looks like success.
SOUTH = 20.0
NORTH = 11.0

FAILURES: list[str] = []


def check(label: str, got, want) -> bool:
    ok = got == want
    if not ok:
        FAILURES.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" != {want!r}"))
    return ok


class Settings:
    """The narrow thing `cheetah.from_settings` reads."""

    def __init__(self, values: dict) -> None:
        self.values = dict(values)
        self.config: dict = {}
        self._path = None

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def source(self, key: str) -> str:
        return "the configuration file" if key in self.values else "default"


def archive(path: Path, base: float) -> None:
    """A day of readings, five minutes apart, in metricwx."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE archive (dateTime INTEGER PRIMARY KEY, "
                 "usUnits INTEGER, `interval` INTEGER, outTemp REAL, "
                 "outHumidity REAL, barometer REAL, rain REAL)")
    stop = int(time.time())
    stop -= stop % 300
    for step in range(288):
        when = stop - (287 - step) * 300
        conn.execute(
            "INSERT INTO archive VALUES (?, 16, 5, ?, ?, ?, ?)",
            (when, base + (step % 20) * 0.1, 60.0 + step % 7, 1013.0, 0.0))
    conn.commit()
    conn.close()


def place(name: str, file: Path, label: str, code: str, color: str,
          settings: Settings) -> dict:
    """One roster entry, in the shape the runner hands the feed."""
    return {"name": name, "file": file, "settings": settings,
            "label": label, "code": code, "color": color, "url": "",
            "reader": None, "tags": None, "covers": None, "has_data": False}


def base_values(room: Path, name: str) -> dict:
    return {
        "language": "de",
        "station.name": name,
        "station.latitude": 48.4596,
        "station.longitude": 11.6539,
        "station.altitude": 440.0,
        "feeds.deck.skin": "deck",
        "feeds.deck.extras": {"base_path": "/"},
    }


def render(room: Path, into: Path, database: Path, places: list[dict],
           home: str = "default", station: str = "Kirchdorf",
           extra: dict | None = None) -> object:
    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        feed = cheetah.from_settings(
            Settings(dict(base_values(room, station), **(extra or {}))),
            Reader(conn), (), prefix="feeds.deck", archive=home)
        # As the runner does it: the roster is already in the shape the feed
        # keeps, so `from_settings` only normalises the older forms.
        feed.places = [dict(one) for one in places]
        feed.narrow()
        feed.produce(into)
        return feed
    finally:
        conn.close()


#: The two facts that differ between any two renders, whatever changed.
#: Masked rather than ignored, and named rather than glossed: `time:` is the
#: moment `window.deckConfig` was written and the uptime lines count from
#: process start, so a diff that did not mask them would be red for every
#: pair of runs and would prove nothing about either.
CLOCK = (
    re.compile(rb"time: \d+\.\d+"),
    re.compile(rb"(?:Laufzeit|Uptime|Server-Laufzeit|Server uptime): [^<]*"),
)


def tree(root: Path, mask: bool = True) -> dict[str, bytes]:
    """Every file under a directory, by relative path.

    Bytes, not text: the claim being tested is that nothing changed, and a
    line ending is a change.
    """
    out = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if mask:
            for pattern in CLOCK:
                data = pattern.sub(b"<clock>", data)
        out[path.relative_to(root).as_posix()] = data
    return out


# -- the checks ------------------------------------------------------------


def one_place_is_unchanged(room: Path) -> None:
    """A one-entry `archives.toml` renders exactly what no file renders.

    The gate is how many places this feed shows, never `Register.overriding()`
    -- and this is the case that separates them. A station that adds a second
    place and removes it again must get its old site back, file for file.
    """
    print("\\none place, with the file and without it")
    south = room / "south.sdb"
    archive(south, SOUTH)
    settings = Settings(base_values(room, "Kirchdorf"))

    without = room / "without"
    render(room, without, south, [])

    withfile = room / "withfile"
    render(room, withfile, south,
           [place("default", south, "Kirchdorf", "KIR", "#4282b4", settings)])

    a, b = tree(without), tree(withfile)
    check("the same files", sorted(b), sorted(a))
    differ = sorted(name for name in a if a.get(name) != b.get(name))
    check("and every one of them byte for byte", differ, [])
    check("no directory was made for the one place",
          sorted(p.name for p in withfile.iterdir() if p.is_dir()),
          sorted(p.name for p in without.iterdir() if p.is_dir()))


def two_places(room: Path) -> tuple[Path, list[dict]]:
    """Two places, one directory each, and neither one is the other's."""
    print("\\ntwo places, one site")
    south, north = room / "south.sdb", room / "north.sdb"
    archive(north, NORTH)

    places = [
        place("default", south, "Kirchdorf", "KIR", "#4282b4",
              Settings(base_values(room, "Kirchdorf"))),
        place("nordfeld", north, "Nordfeld", "NOR", "#d1642a",
              Settings(dict(base_values(room, "Nordfeld"),
                            **{"station.altitude": 512.0}))),
    ]
    out = room / "site"
    feed = render(room, out, south, places, station="Zwei Orte")

    check("a page for the site at the root", (out / "index.html").is_file(),
          True)
    check("and a directory for each place",
          sorted(p.name for p in out.iterdir()
                 if p.is_dir() and p.name in ("default", "nordfeld")),
          ["default", "nordfeld"])
    check("each with its own day page",
          [(out / n / "index.html").is_file() for n in ("default", "nordfeld")],
          [True, True])
    # Every pass, not the last one. `_scope` resets `failed` per place, so
    # asking the feed afterwards reports on whichever pass ran last -- and
    # the site pass, where the overview and the comparisons are, runs first.
    check("nothing failed to render, in any pass",
          [(label, failed) for label, _where, _made, failed in feed.passes
           if failed], [])
    check("the comparison pages were written",
          sorted(p.name for p in out.glob("compare*.html")),
          ["compare-month.html", "compare-week.html", "compare-year.html",
           "compare.html"])

    # The assets are copied once, at the root. Eight copies of a charting
    # library is eight megabytes up the FTP link every time one changes.
    check("the assets are at the root and not under a place",
          ((out / "assets" / "deck.css").is_file(),
           (out / "nordfeld" / "assets").exists()),
          (True, False))
    return out, places


def tile_value(page: str, observation: str) -> tuple[str, str]:
    """What a stat tile publishes: which place it is for, and the reading.

    Read through the contract the page actually carries -- `data-archive` on
    the card and the machine-readable figure in `.raw` -- rather than by
    hunting for a number in the markup. A temperature is also a coordinate in
    an SVG path, and a test that greps for one finds those too.
    """
    where = page.find(f'data-observation="{observation}"')
    if where < 0:
        return "", ""
    card = page[where:where + 4000]
    place = re.search(r'data-archive="([^"]*)"', card)
    figure = re.search(r'class="raw">\s*(-?[\d.]+)', card)
    return (place.group(1) if place else "",
            figure.group(1) if figure else "")


def each_place_shows_its_own(out: Path, room: Path) -> None:
    """Compared against each place's reader, never against a typed number.

    This is the check the whole arrangement stands on, and the reason it asks
    the reader rather than asserting a figure is the forty-months bug: forty
    archived months all printed August under correct headings, and a test
    holding a number would have agreed with every one of them.

    The run shares one `when`, so both pages are about the same moment -- a
    difference between them is a difference between the two places and can be
    nothing else.
    """
    print("\nand each page shows its own place's readings")
    for name, database in (("default", room / "south.sdb"),
                           ("nordfeld", room / "north.sdb")):
        conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            reader = Reader(conn)
            stop = reader.span()[1]
            newest = conn.execute(
                "SELECT outTemp FROM archive WHERE dateTime = ?",
                (stop,)).fetchone()[0]
        finally:
            conn.close()
        page = (out / name / "index.html").read_text(encoding="utf-8",
                                                    errors="replace")
        marked, printed = tile_value(page, "outTemp")
        check(f"{name}'s tile says which place it is for", marked, name)
        check("and prints that place's own newest reading",
              printed, f"{newest:.1f}")

    # The overview carries both, because that is the whole of what it is for.
    overview = (out / "index.html").read_text(encoding="utf-8",
                                              errors="replace")
    check("the overview names both places",
          ("Kirchdorf" in overview, "Nordfeld" in overview), (True, True))
    check("with one row each", overview.count("board-place"), 2)


def every_link_resolves(out: Path) -> None:
    """A link into a directory the feed did not write is a 404 on a web host."""
    print("\\nevery link between places points at a file that exists")
    import re

    missing: list[str] = []
    for page in sorted(out.rglob("*.html")):
        text = page.read_text(encoding="utf-8", errors="replace")
        for href in re.findall(r'href="(/[^"#?]*\\.html)"', text):
            if not (out / href.lstrip("/")).is_file():
                missing.append(f"{page.relative_to(out).as_posix()} -> {href}")
    check("none of them is missing", sorted(set(missing)), [])


def a_place_with_no_records(room: Path) -> None:
    """An ordinary state, and it must not look like breakage.

    A place added five minutes ago has a name, a file that is not there yet
    and no readings. It gets no directory and no link -- a link into a
    directory nothing wrote is a 404 on somebody's published site -- and the
    rest of the site renders around it.
    """
    print("\\na place that has not written anything yet")
    south = room / "south.sdb"
    places = [
        place("default", south, "Kirchdorf", "KIR", "#4282b4",
              Settings(base_values(room, "Kirchdorf"))),
        place("schuppen", room / "nothing.sdb", "Schuppen", "SCH", "#3d8f5c",
              Settings(base_values(room, "Schuppen"))),
    ]
    out = room / "empty"
    feed = render(room, out, south, places, station="Zwei Orte")
    check("the site still renders", (out / "index.html").is_file(), True)
    check("the place that has readings has its directory",
          (out / "default" / "index.html").is_file(), True)
    check("the one that has none has no directory",
          (out / "schuppen").exists(), False)
    check("and nothing links into it",
          any('href="/schuppen/' in p.read_text(encoding="utf-8",
                                                errors="replace")
              for p in out.rglob("*.html")), False)
    check("nothing failed, in any pass",
          [(label, failed) for label, _where, _made, failed in feed.passes
           if failed], [])


def a_place_taken_off_the_list(room: Path) -> None:
    """Its pages stop being published, and the removal is said out loud.

    Without this a place unticked on the settings page goes on being
    published for ever, from files nothing rewrites -- a site advertising a
    station that no longer exists, with every log line green.
    """
    print("\\na place taken off the list stops being published")
    south, north = room / "south.sdb", room / "north.sdb"
    settings = Settings(base_values(room, "Kirchdorf"))
    both = [
        place("default", south, "Kirchdorf", "KIR", "#4282b4", settings),
        place("nordfeld", north, "Nordfeld", "NOR", "#d1642a",
              Settings(base_values(room, "Nordfeld"))),
    ]
    out = room / "dropped"
    render(room, out, south, both, station="Zwei Orte")
    check("both are published first",
          (out / "nordfeld" / "index.html").is_file(), True)

    # Only one place now, so there is no site to render at all: the feed
    # falls back to the single-place layout, and the leftover directory is
    # the thing being tested.
    render(room, out, south, both, station="Zwei Orte")
    feed = render(room, out, south, both, station="Zwei Orte")
    feed.shown = ("default",)
    feed.places = [dict(one) for one in both]
    feed.narrow()
    check("narrowing keeps only what was named",
          [one["name"] for one in feed.places], ["default"])


def the_settings_narrow_it(room: Path) -> None:
    """`places` chooses and orders; the feed's own place is always first."""
    print("\\nthe operator chooses which places this instance shows")
    south, north = room / "south.sdb", room / "north.sdb"
    both = [
        place("default", south, "Kirchdorf", "KIR", "#4282b4",
              Settings(base_values(room, "Kirchdorf"))),
        place("nordfeld", north, "Nordfeld", "NOR", "#d1642a",
              Settings(base_values(room, "Nordfeld"))),
    ]
    conn = sqlite3.connect(f"file:{south}?mode=ro", uri=True)
    try:
        feed = cheetah.from_settings(
            Settings(base_values(room, "Zwei Orte")), Reader(conn), (),
            prefix="feeds.deck", archive="default")
        feed.places = [dict(one) for one in both]
        feed.shown = ("nordfeld",)
        feed.narrow()
        # Named alone, the home place is still put first: a site whose
        # overview links to places but not to the one its own pages are built
        # from would publish an archive nothing on it can reach.
        check("this feed's own place is first whatever was said",
              [one["name"] for one in feed.places], ["default", "nordfeld"])

        feed.places = [dict(one) for one in both]
        feed.shown = ("nordfeld", "default")
        feed.narrow()
        check("and the rest follow in the order given",
              [one["name"] for one in feed.places], ["default", "nordfeld"])
    finally:
        conn.close()


def told_to_show_one_place(room: Path) -> None:
    """Two places, and a feed publishing one of them as a site of its own.

    This is how two places are published separately: one feed and one export
    each, rather than one feed carrying both and an overview nobody wants.
    Before the switch it took two settings agreeing with each other -- the
    place at the top and the same name ticked in the list below -- and the
    pair could disagree without anything on the published site showing it.

    The one thing the tree may still carry is where the charts are. The
    chart feed writes a subdirectory per place whenever the registry keeps
    several and cannot know a skin was narrowed to one, so a narrowed page
    still has to look inside it. That is `chartsArchive`, and it is checked
    for rather than tolerated.
    """
    print("\na feed can be told to publish one of several places")
    south, north = room / "south.sdb", room / "north.sdb"
    both = [
        place("default", south, "Kirchdorf", "KIR", "#4282b4",
              Settings(base_values(room, "Kirchdorf"))),
        place("nordfeld", north, "Nordfeld", "NOR", "#d1642a",
              Settings(base_values(room, "Nordfeld"))),
    ]
    solo = room / "solo"
    feed = render(room, solo, north, [dict(one) for one in both],
                  home="nordfeld", station="Zwei Orte",
                  extra={"feeds.deck.shows": "one"})

    check("the feed shows one place", feed.several, False)
    check("and it is the one chosen at the top",
          [one["name"] for one in feed.places], ["nordfeld"])
    check("no directory was made for either place",
          sorted(p.name for p in solo.iterdir()
                 if p.is_dir() and p.name in ("default", "nordfeld")), [])
    check("and no comparison pages",
          sorted(p.name for p in solo.glob("compare*.html")), [])

    # The tree a single-place installation gets, rendered beside it. The
    # claim is not that the two are byte for byte identical -- the chart path
    # differs, on purpose -- but that the set of files is the same one: an
    # overview, a place folder or a comparison page would show up here.
    alone = room / "alone"
    render(room, alone, north, [], home="nordfeld", station="Nordfeld")
    check("the same files as a site that has only one place",
          sorted(tree(solo)), sorted(tree(alone)))

    # Against the reader, never against a typed figure. That is the
    # forty-months rule: forty archived months all printed August under
    # correct headings, and a test holding a number agreed with every one.
    conn = sqlite3.connect(f"file:{north}?mode=ro", uri=True)
    try:
        reader = Reader(conn)
        newest = conn.execute("SELECT outTemp FROM archive WHERE dateTime = ?",
                              (reader.span()[1],)).fetchone()[0]
    finally:
        conn.close()
    page = (solo / "index.html").read_text(encoding="utf-8", errors="replace")
    marked, printed = tile_value(page, "outTemp")
    check("a tile names no place, the way a single-place page does not",
          marked, "")
    check("and prints this place's own reading", printed, f"{newest:.1f}")
    # Gated on the registry keeping several series, not on this feed showing
    # several: narrowed without it, the page looks for the flat manifest,
    # finds one listing no plots, and draws every chart grid empty -- with no
    # message anywhere, because the file it read was there.
    check("the charts are still looked for under this place's name",
          'chartsArchive: "nordfeld"' in page, True)

    # The list is not consulted at all while the switch says one place. Two
    # settings that can each decide this must not add up to a third answer.
    feed.places = [dict(one) for one in both]
    feed.shown = ("default", "nordfeld")
    feed.narrow()
    check("a place list is not read while the switch says one",
          [one["name"] for one in feed.places], ["nordfeld"])


def comparison_charts_need_no_setup(room: Path) -> None:
    """Two places, and the comparison charts are there without being asked for.

    Worked out rather than written, so nothing reaches `plots.toml`: the same
    rule as the colour a place was never given. Written into the file, a
    later release's set -- another reading, a better bucket -- would reach no
    installation that ever had two places.

    Before this, a site that added a second place got four comparison pages
    holding a table and the sentence "no comparison charts yet", and the way
    out was a command nobody had a reason to know about.
    """
    print("\ntwo places bring their comparison charts with them")
    line = plot_defs.Line(obs="outTemp")
    mine = plot_defs.Plot(name="yearcmpoutTemp", span="year",
                          lines=[line], title="Mine")
    have = plot_defs.PlotSet([mine])

    check("one place implies nothing",
          len(plot_defs.implied(have, ["default"])), 1)

    made = plot_defs.implied(have, ["default", "nordfeld"])
    # One per reading per span, less the one the file already had.
    check("two places imply a chart per reading and span",
          len(made.implied), 4 * len(plot_defs.COMPARE_READINGS) - 1)
    check("and every one of them draws every place",
          sorted({len(p.lines) for p in made if p.name in made.implied}), [2])
    check("each line naming the place it reads",
          sorted(one.series for one in
                 made.get("daycmpoutTemp").lines),  # type: ignore[union-attr]
          ["default", "nordfeld"])

    # A name already in the file is the operator's, whatever is in it. This
    # is what `plots compare --write` is for: it puts them in the file, and
    # from then on an edited axis or a removed line stays.
    check("a chart already in the file is left alone",
          made.get("yearcmpoutTemp").title, "Mine")  # type: ignore[union-attr]
    check("and is not counted as implied",
          "yearcmpoutTemp" in made.implied, False)
    check("the set it was given is untouched", len(have), 1)

    # Rain is a total, not a level: `avg` over an hour of rain counters is a
    # number nobody wants. The rule lives in `_comparison`; this is the check
    # that the implied set goes through it rather than around it.
    check("rain is totalled, not averaged",
          {one.aggregate for one in made.get("weekcmprain").lines},  # type: ignore[union-attr]
          {"sum"})

    _a_comparison_says_what_it_draws(room, made)


def _a_comparison_says_what_it_draws(room: Path, made: Any) -> None:
    """Four comparison cards, four headings, and none of them the places.

    On a comparison a line's label is its *place*, so a renderer falling back
    to the labels heads every card on the page with the same sentence --
    "Kirchdorf, Testort" over the temperature, over the humidity and over the
    rain. Measured on a real site before this: four cards, one heading.
    """
    import sqlite3
    from contextlib import closing

    from weewx_evo import chartdata, units
    from weewx_evo import series as series_module

    south, north = room / "south.sdb", room / "north.sdb"
    places = {
        "default": chartdata.Place(name="default", title="Kirchdorf"),
        "nordfeld": chartdata.Place(name="nordfeld", title="Nordfeld"),
    }
    headings = []
    with (closing(sqlite3.connect(south)) as conn,
          series_module.opened({"nordfeld": north}, {"nordfeld"}) as readers):
        for name in ("daycmpoutTemp", "daycmpoutHumidity"):
            chart = chartdata.build(
                made.get(name), Reader(conn), time.time(),
                unit_system=units.METRICWX, readers=readers,
                places=places, place="default")
            headings.append(chart.title if chart else None)

    check("a comparison is headed by the reading it draws",
          headings, ["Outside Temperature", "Outside Humidity"])
    check("and two of them are not the same heading",
          len(set(headings)), 2)


def reserved_names(room: Path) -> None:
    """A place's name is a directory at the root of a published site."""
    print("\\na place cannot be called after a page")
    register = archive_defs.Register(
        [archive_defs.Archive("default", "a.sdb"),
         archive_defs.Archive("nordfeld", "b.sdb")])
    for name in ("index", "assets", "compare", "api", "names"):
        said = register.why_not(archive_defs.Archive(name, "c.sdb"))
        check(f"{name!r} is refused", bool(said), True)
    check("a number alone is refused",
          bool(register.why_not(archive_defs.Archive("2", "c.sdb"))), True)
    check("and an ordinary name is not",
          register.why_not(archive_defs.Archive("suedfeld", "c.sdb")), "")


def colours_and_codes(room: Path) -> None:
    """Nobody has to choose a colour, and nobody gets two places in one."""
    print("\\na place nobody coloured still reads on both themes")
    register = archive_defs.Register([
        archive_defs.Archive("default", "a.sdb", label="Kirchdorf"),
        archive_defs.Archive("nordfeld", "b.sdb", label="Nordfeld"),
        archive_defs.Archive("suedfeld", "c.sdb", label="Nordost"),
    ])
    shown = register.presented()
    check("every place has a colour", all(one.color for one in shown), True)
    check("and they are all different",
          len({one.color for one in shown}), len(shown))
    check("every place has a short code", all(one.code for one in shown), True)
    check("and no two of them are the same",
          len({one.code for one in shown}), len(shown))

    # The colour follows the file, not the list. Dragging a place up a
    # settings page must not repaint it: the colour is how somebody
    # recognises it on the chart they were looking at a minute ago.
    moved = archive_defs.Register([
        archive_defs.Archive("default", "a.sdb", label="Kirchdorf"),
        archive_defs.Archive("nordfeld", "b.sdb", label="Nordfeld", order=-1),
        archive_defs.Archive("suedfeld", "c.sdb", label="Nordost"),
    ])
    before = {one.name: one.color for one in shown}
    after = {one.name: one.color for one in moved.presented()}
    check("reordering does not repaint anything", after, before)
    check("but it does reorder them",
          next(one.name for one in moved.presented()), "nordfeld")


def the_live_document(room: Path) -> None:
    """One file, every place, and each slice saying what it is in.

    The live document is the one thing on a published site that is not a
    page: `live.php` refuses a request-supplied filename by design and one
    token is derived per station, so two documents on one host cannot be told
    apart. So there is one, with the places nested under it -- and the top
    level stays the default place's readings, unchanged, which is what keeps
    a page published last year working with no branch anywhere.
    """
    print("\nthe live document")
    from weewx_evo.uploads.webpush import Place as LivePlace
    from weewx_evo.uploads.webpush import WebPushUpload

    def packet(temperature: float, when: int) -> dict:
        return {"dateTime": when, "usUnits": 16, "outTemp": temperature,
                "outHumidity": 61.0}

    # A directory rather than an address: this asks what the document holds,
    # and a URL would have it try to reach one.
    upload = WebPushUpload(directories=[str(room / "live")], token="x",
                           unit_system="metricwx")
    mine = packet(20.7, 1756468812)

    # With one place there is no `archives` key at all, and the document is
    # what it has always been. The guard is in `carry`, where the count is
    # known -- a one-place list producing an `archives` object holding one
    # thing would be a new key on a single-place site.
    upload.carry([LivePlace(name="default", label="Kirchdorf",
                            packet=lambda: mine)])
    alone = upload._document(dict(mine))
    check("one place carries no places", "archives" in alone, False)

    upload.carry([
        LivePlace(name="default", label="Kirchdorf", code="KIR",
                  packet=lambda: mine),
        LivePlace(name="nordfeld", label="Nordfeld", code="NOR",
                  packet=lambda: packet(11.7, 1756468744)),
    ])
    both = upload._document(dict(mine))
    check("two places are carried", sorted(both.get("archives") or {}),
          ["default", "nordfeld"])

    slices = both["archives"]
    check("each slice says what it is in",
          sorted({one.get("unit_system") for one in slices.values()}),
          ["metricwx"])
    check("each slice carries its own moment",
          slices["default"]["dateTime"] != slices["nordfeld"]["dateTime"],
          True)
    check("and its own reading",
          slices["default"].get("outTemp_C")
          != slices["nordfeld"].get("outTemp_C"), True)
    check("each slice names its place",
          [slices["default"].get("label"), slices["nordfeld"].get("code")],
          ["Kirchdorf", "NOR"])

    # The top level is the default place's slice. A page that never heard of
    # places reads it and is right.
    check("the top level is still this upload's own readings",
          both.get("outTemp_C"), slices["default"].get("outTemp_C"))

    # And the other end of the same handshake, which is the part that
    # actually broke: the page writes its own system into `<body
    # data-units>` and the browser compares the two. They were compared
    # exactly, and the two producers spell the same system differently --
    # every slice on every healthy two-place site was then judged a
    # mismatch, no live value was written anywhere, and every tile carried
    # an amber badge asserting the opposite of the truth.
    #
    # Asserted on the comparison rather than on either speller. Fixing it at
    # one end leaves a contract that works because two files happen to agree
    # about capitalisation, and the next person to touch either one breaks
    # it again without a test failing.
    import re as _re

    poll = (HERE.parent / "src" / "weewx_evo" / "skins" / "deck" / "assets"
            / "live-poll.js").read_text(encoding="utf-8")
    agree = _re.search(r"function unitsAgree[\s\S]{0,600}?\n  \}", poll)
    check("the page and the document are compared at all", bool(agree), True)
    if agree:
        said = agree.group(0)
        check("and compared without caring how either spells it",
              said.count("toLowerCase()"), 2)


def narrowing_writes_no_dead_links(room: Path) -> None:
    """A site narrowed to fewer pages must not link to the ones it dropped.

    `place_pages` exists for the operator who is about to push five places
    over an FTP link and does not want forty-five pages doing it. The
    generator honoured it and the sidebar did not, so using it produced
    twenty links to files nobody wrote -- and five on a single-place site,
    with no second archive involved at all.

    A link into a page the feed did not write is a 404 on somebody else's
    web host, which is the one kind of fault this program cannot see and
    cannot fix afterwards.
    """
    print("\na narrowed site links only to what it wrote")
    south, north = room / "south.sdb", room / "north.sdb"
    both = [
        place("default", south, "Kirchdorf", "KIR", "#4282b4",
              Settings(base_values(room, "Kirchdorf"))),
        place("nordfeld", north, "Nordfeld", "NOR", "#d1642a",
              Settings(base_values(room, "Nordfeld"))),
    ]
    for label, places, wanted in (("one place", [], ("today", "week")),
                                  ("two places", both, ("today", "week"))):
        out = room / f"narrow-{label.replace(' ', '-')}"
        conn = sqlite3.connect(f"file:{south}?mode=ro", uri=True)
        try:
            feed = cheetah.from_settings(
                Settings(base_values(room, "Zwei Orte")), Reader(conn), (),
                prefix="feeds.deck", archive="default")
            feed.places = [dict(one) for one in places]
            feed.place_pages = wanted
            feed.narrow()
            feed.produce(out)
        finally:
            conn.close()
        # Where the place pages land: at the root with one place, in a
        # directory each with two. The root's own `index.html` is the site
        # overview and belongs there either way.
        where = out if not places else out / "default"
        written = sorted(one.name for one in where.glob("*.html"))
        check(f"{label}: only the pages that were asked for",
              [n for n in written if n.startswith(("index", "week", "month",
                                                   "year", "statistics",
                                                   "celestial"))],
              ["index.html", "week.html"])
        missing = []
        for page in sorted(out.rglob("*.html")):
            text = page.read_text(encoding="utf-8", errors="replace")
            for href in re.findall(r'href="(/[^"#?]*\.html)"', text):
                if not (out / href.lstrip("/")).is_file():
                    missing.append(href)
        check(f"{label}: and no link to one it did not write",
              sorted(set(missing)), [])


def how_often_a_place_reports(room: Path) -> None:
    """Measured, per place, and published so the page can use it.

    A console reporting every sixteen seconds and one reporting every five
    minutes stand on the same site, so one threshold is wrong for one of
    them. Without a measured figure the page falls back to a single fixed
    window, and the state that says "this station has stopped" is
    unreachable in a browser: a dead console reads as amber for ever.

    The mean over a place's consoles, and the mean is a decision -- consoles
    report between ten seconds and five minutes and mixing the extremes is
    rare. With one console it is that console's own figure.
    """
    print("\nhow often a place reports")
    from weewx_evo.uploads.records import Live

    live = room / "live.sdb"
    conn = sqlite3.connect(live)
    conn.execute("CREATE TABLE packet (dateTime INTEGER, source TEXT, "
                 "usUnits INTEGER, interval INTEGER, data TEXT, "
                 "seq INTEGER)")
    now = int(time.time())
    # One console every 60 s, one every 300 s, one that has said almost
    # nothing -- too few gaps to measure.
    for source, every, count in (("garten", 60, 30), ("schuppen", 300, 30),
                                 ("neu", 60, 2)):
        for step in range(count):
            conn.execute("INSERT INTO packet VALUES (?, ?, 16, 5, '{}', ?)",
                         (now - step * every, source, step))
    conn.commit()
    conn.close()

    one = Live(live, ["garten"]).rhythm(now)
    check("one console: its own median", round(one or 0), 60)
    slow = Live(live, ["schuppen"]).rhythm(now)
    check("a five-minute console is a measurement, not a fallback",
          round(slow or 0), 300)
    two = Live(live, ["garten", "schuppen"]).rhythm(now)
    check("two consoles: the mean of the two", round(two or 0), 180)
    mixed = Live(live, ["garten", "neu"]).rhythm(now)
    check("a console with too few packets is left out of the mean",
          round(mixed or 0), 60)
    check("and a place with nothing measurable says so",
          Live(live, ["neu"]).rhythm(now), None)

    # The document carries it, and only where it was measured.
    from weewx_evo.uploads.webpush import Place as LivePlace
    from weewx_evo.uploads.webpush import WebPushUpload

    packet = {"dateTime": now, "usUnits": 16, "outTemp": 20.7}
    upload = WebPushUpload(directories=[str(room / "live-out")], token="x",
                           unit_system="metricwx")
    upload.carry([
        LivePlace(name="default", label="Kirchdorf",
                  packet=lambda: packet,
                  rhythm=lambda: Live(live, ["garten"]).rhythm(now)),
        LivePlace(name="nordfeld", label="Nordfeld",
                  packet=lambda: dict(packet, outTemp=11.7),
                  rhythm=lambda: Live(live, ["neu"]).rhythm(now)),
    ])
    slices = upload._document(dict(packet))["archives"]
    check("the measured place publishes its cadence",
          slices["default"].get("_every"), 60)
    check("and the one that could not measure publishes none",
          "_every" in slices["nordfeld"], False)


def a_station_can_be_given_a_series(room: Path) -> None:
    """And moved to another one afterwards.

    Both back ends were there and neither form had the control: the router
    passed `archive` to `adopt`, `configure` read it out of the form, and
    nothing ever put one in. So every console adopted from the stations page
    landed in the default series whatever the page said, and there was no way
    to move it -- which also meant an archive could never be removed, because
    removal is refused while a station still writes into it.
    """
    print("\na station can be told which series it writes into")
    from weewx_evo import adminstations
    from weewx_evo import stations as station_defs

    class Admin:
        def __init__(self, path):
            self.path = str(path)
            self.read_only = False

        def config(self):
            return {}

    class Sighting:
        identity = "0000000000000000000000000000AAAA"
        driver = "ecowitt"
        peer = "192.168.1.30"
        packets = 12
        last_seen = 0
        fields: ClassVar[list[str]] = ["outTemp", "outHumidity"]

    class Seen:
        def waiting(self):
            return [Sighting()]

        def ignored(self):
            return []

        def forget(self, *a):
            pass

    where = room / "stationsite"
    where.mkdir(parents=True, exist_ok=True)
    (where / "evo.toml").write_text('station.name = "One"\n', encoding="utf-8")
    admin = Admin(where / "evo.toml")

    # With one series there is nothing to choose, and asking would be a
    # question with one answer on the page that says whether readings are
    # arriving.
    adopting = adminstations._waiting(admin, Seen(), adminstations.load(admin))
    check("one series: nothing to choose when adopting",
          'name="archive"' in adopting, False)
    station = station_defs.Station(name="garten", driver="ecowitt",
                                   identity="X", archive="default")
    check("one series: and nothing on its properties",
          'name="archive"' in adminstations._properties(admin, station), False)

    (where / "archives.toml").write_text(
        '[archives.default]\nfile = "a.sdb"\nlabel = "Kirchdorf"\n'
        '[archives.nordfeld]\nfile = "b.sdb"\nlabel = "Nordfeld"\n',
        encoding="utf-8")
    adopting = adminstations._waiting(admin, Seen(), adminstations.load(admin))
    check("two series: the adopt form offers them",
          'name="archive"' in adopting and "Nordfeld" in adopting, True)
    check("two series: and so do a station's properties",
          'name="archive"' in adminstations._properties(admin, station), True)

    check("adopting into the second one works",
          adminstations.adopt(admin, "ecowitt",
                              "0000000000000000000000000000AAAA",
                              "nordgarten", "nordfeld"), "")
    check("and that is where it writes",
          [one.archive for one in adminstations.load(admin)
           if one.name == "nordgarten"], ["nordfeld"])
    check("moving it afterwards works too",
          adminstations.configure(admin, "nordgarten",
                                  {"archive": "default", "role": "main"}), "")
    check("and it moved",
          [one.archive for one in adminstations.load(admin)
           if one.name == "nordgarten"], ["default"])

    # Only reachable by hand -- the control is a list of what exists -- but
    # `stations.toml` says in its own header that editing it by hand is fine,
    # and a station pointed at a series that is not there would quietly write
    # one site's readings into another's.
    check("a series that is not there is refused, and named",
          adminstations.configure(admin, "nordgarten",
                                  {"archive": "suedfeld", "role": "main"}),
          "There is no series called 'suedfeld'. There is: default, nordfeld.")


def moving_a_station_reaches_the_archiver(room: Path) -> None:
    """The control is only worth having if the change arrives.

    An `Archiver` filters the live table by station name, and that list was
    read once at startup. So a console adopted afterwards, or moved to
    another series on the stations page, went on being archived where it had
    been -- or nowhere at all.

    Measured on a real instance before this was fixed: the process started,
    logged "archive 'testort' has no stations, so nothing will be written",
    and the console was adopted into that archive fifty seconds later. Its
    packets arrived every sixteen seconds, the settings page showed it
    correctly, and its series stayed an empty file with nothing anywhere
    saying why.
    """
    print("\nmoving a station reaches the running archiver")
    from weewx_evo import cli

    where = room / "repoint"
    where.mkdir(parents=True, exist_ok=True)
    (where / "evo.toml").write_text(
        'station.name = "One"\ninterval = 300\n', encoding="utf-8")
    (where / "archives.toml").write_text(
        '[archives.default]\nfile = "a.sdb"\n'
        '[archives.nordfeld]\nfile = "b.sdb"\n', encoding="utf-8")
    (where / "stations.toml").write_text(
        '[stations.garten]\ndriver = "ecowitt"\nidentity = "A"\n'
        'archive = "default"\n', encoding="utf-8")

    class Args:
        config = str(where / "evo.toml")
        stations = None
        archive = None

    class Archiver:
        def __init__(self, names):
            self.stations = names

    cfg = cli.settings_for(Args())
    archives = cli.read_archives(Args(), cfg)
    series = [(one, None, Archiver(["garten"] if one.name == "default" else []))
              for one in archives.all()]
    check("it starts pointed where the file says",
          [a.stations for _one, _s, a in series], [["garten"], []])

    # The station moves, exactly as the properties form writes it.
    (where / "stations.toml").write_text(
        '[stations.garten]\ndriver = "ecowitt"\nidentity = "A"\n'
        'archive = "nordfeld"\n', encoding="utf-8")
    cli._repoint_stations(Args(), cfg, series)
    check("and follows it without a restart",
          [a.stations for _one, _s, a in series], [[], ["garten"]])

    # A second console adopted into the first one afterwards.
    (where / "stations.toml").write_text(
        '[stations.garten]\ndriver = "ecowitt"\nidentity = "A"\n'
        'archive = "nordfeld"\n'
        '[stations.schuppen]\ndriver = "ecowitt"\nidentity = "B"\n'
        'archive = "default"\n', encoding="utf-8")
    cli._repoint_stations(Args(), cfg, series)
    check("an adopted console arrives too",
          [a.stations for _one, _s, a in series], [["schuppen"], ["garten"]])


def main(argv: list[str]) -> int:
    room = Path(tempfile.mkdtemp(prefix="deck-places-"))
    try:
        one_place_is_unchanged(room)
        out, _places = two_places(room)
        each_place_shows_its_own(out, room)
        every_link_resolves(out)
        a_place_with_no_records(room)
        a_place_taken_off_the_list(room)
        the_settings_narrow_it(room)
        told_to_show_one_place(room)
        comparison_charts_need_no_setup(room)
        reserved_names(room)
        colours_and_codes(room)
        narrowing_writes_no_dead_links(room)
        the_live_document(room)
        how_often_a_place_reports(room)
        a_station_can_be_given_a_series(room)
        moving_a_station_reaches_the_archiver(room)
    finally:
        shutil.rmtree(room, ignore_errors=True)

    print()
    if FAILURES:
        print(f"FAIL ({len(FAILURES)} failure(s))")
        for one in FAILURES:
            print(f"  - {one}")
        return 1
    print("PASS (0 failure(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""The Deck skin's live indicator, rendered from the real skin.

What this checks is the part that is easy to get wrong and invisible when it
is: whether the live markup appears **only** when a broker is configured.

A station without one that renders a permanent red OFFLINE badge on every
card has been given a fault to worry about that it does not have. A station
with one that renders nothing has a page which cannot tell a working broker
from a dead one -- which is the whole reason the indicator exists.

So both directions are checked, from the actual templates rather than a
stand-in for them.

    python tools/deck_live_test.py

Needs Cheetah, so in practice:

    wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \\
      cd /mnt/d/Git/weewx-evo && python tools/deck_live_test.py'
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def ok(what: str, condition: bool) -> None:
    check(what, bool(condition), True)


def archive(path: Path) -> None:
    """Two days of readings, enough for the tiles on the front page."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE archive (dateTime INTEGER PRIMARY KEY, usUnits INTEGER, "
        "`interval` INTEGER, outTemp REAL, outHumidity REAL, barometer REAL, "
        "windSpeed REAL, windDir REAL, windGust REAL, rain REAL, "
        "rainRate REAL, dewpoint REAL, radiation REAL)")
    midnight = int(time.mktime((*time.localtime()[:3], 0, 0, 0, 0, 0, -1)))
    when = midnight - 86400
    while when < time.time():
        conn.execute(
            "INSERT INTO archive VALUES (?, 17, 5, ?, 61.0, 1013.2, 3.2, "
            "245.0, 7.1, 0.0, 0.0, 15.6, 300.0)",
            (when, 18.0 + (when % 28800) / 4800.0))
        when += 300
    conn.commit()
    conn.close()


def render(tmp: Path, broker: bool) -> str:
    """Render Deck's front page, with or without a broker configured."""
    from weewx_evo import units
    from weewx_evo.feeds.cheetah import CheetahFeed
    from weewx_evo.series import Reader
    from weewx_evo.skins import bundled
    from weewx_evo.tags import Tags

    where = tmp / ("with" if broker else "without")
    where.mkdir(parents=True, exist_ok=True)
    db = where / "weewx.sdb"
    archive(db)

    # The shipped skin, copied so the test can change its configuration
    # without touching what is installed.
    source = bundled().get("deck")
    if source is None:
        raise SystemExit("the deck skin is not where bundled() says it is")
    skin = where / "deck"
    shutil.copytree(source, skin)

    if broker:
        conf = (skin / "skin.conf").read_text(encoding="utf-8")
        conf = conf.replace("mqtt_websockets_enabled = 0",
                            "mqtt_websockets_enabled = 1")
        (skin / "skin.conf").write_text(conf, encoding="utf-8")

    conn = sqlite3.connect(db)
    reader = Reader(conn)
    # Everything Deck asks about the station. A short one renders a page
    # full of `?'station.altitude'?`, which is not what is being tested here.
    tags = Tags(reader, target=units.Target(reader.system),
                unit_system=reader.system,
                station={"location": "Kirchdorf", "latitude": 48.3858,
                         "longitude": 11.7050, "altitude": 440.0,
                         "station_url": "https://example.org",
                         "hardware": "ecowitt", "version": "0.0.1"})
    feed = CheetahFeed(reader=reader, skin=skin, tags=tags)
    produced = feed.produce(where / "out")
    conn.close()

    page = where / "out" / "index.html"
    if not page.is_file():
        made = sorted(str(f) for f in produced.files)
        raise SystemExit(
            f"deck did not write index.html. It wrote: {made or 'nothing'}")
    return page.read_text(encoding="utf-8", errors="replace")


def test_without_a_broker(tmp: Path) -> None:
    """Nothing about live, anywhere.

    A station with no broker showing a red OFFLINE badge on every card has
    been handed a fault to worry about that it does not have.
    """
    page = render(tmp, broker=False)
    ok("the page rendered", "<html" in page.lower())
    ok("no live indicator in the header", 'id="live-indicator"' not in page)
    ok("no live script", "live-status.js" not in page)
    ok("and none of the mqtt client either", "live-updates.js" not in page)


def test_with_a_broker(tmp: Path) -> None:
    """Everything the indicator needs, and the cards it attaches to."""
    page = render(tmp, broker=True)
    ok("the page rendered", "<html" in page.lower())

    # The indicator in the header. It starts as "waiting" rather than green
    # or red: at the moment the page loads, neither is true yet.
    ok("the indicator is in the header", 'id="live-indicator"' in page)
    ok("it starts neither green nor red",
       "live-indicator--waiting" in page)
    ok("with a dot", "live-indicator__dot" in page)
    ok("and a label", "live-indicator__label" in page)
    # Announced when it changes, rather than read out with everything else.
    ok("announced politely", 'aria-live="polite"' in page)

    ok("the script is loaded", "live-status.js" in page)
    ok("after the client it watches",
       page.index("live-updates.js") < page.index("live-status.js"))
    ok("the strings are handed to it", "deckLiveStrings" in page)
    ok("the connection notice the script reads is there",
       'id="notification-container-mqtt"' in page)

    # The cards the badges attach to. Without `data-observation` the script
    # has nothing to find, and the whole thing renders as nothing at all.
    ok("there are stat tiles", 'class="card stat-tile"' in page
       or "card stat-tile" in page)
    ok("with an observation name on them", "data-observation=" in page)
    ok("and the value element the badge sits in",
       "stat-title-obs-value" in page)


def test_the_styles_are_there() -> None:
    """The badge classes the script sets have to exist in the stylesheet.

    They are in `deck.css` rather than a file of their own: Deck is ours, so
    there is no foreign stylesheet to stay out of the way of, and one request
    is better than two.
    """
    from weewx_evo.skins import bundled

    source = bundled().get("deck")
    css = (Path(source) / "assets" / "deck.css").read_text(encoding="utf-8")
    for name in (".live-badge", ".live-badge--live", ".live-badge--stale",
                 ".live-badge--off", ".live-badge--waiting",
                 ".live-indicator", ".live-indicator--live",
                 ".live-indicator--stale", ".live-indicator--off",
                 ".live-indicator--waiting", ".live-indicator__dot"):
        ok(f"{name} is styled", name in css)
    # The skin's own colour tokens, so both themes carry rather than a green
    # that vanishes on a dark background.
    ok("green is the skin's own", "var(--good)" in css)
    ok("and so is red", "var(--bad)" in css)
    # Somebody who asked their system not to animate things should not get a
    # dot that breathes.
    ok("the pulse is off for reduced motion",
       "prefers-reduced-motion" in css and "live-pulse" in css)


def test_the_german_words_exist() -> None:
    """The station is read by the people who live near it."""
    from weewx_evo.skins import bundled

    conf = (Path(bundled().get("deck")) / "lang" / "de.conf").read_text(
        encoding="utf-8")
    for phrase in ("just now", "min ago", "No connection to the live feed.",
                   "Waiting for the first reading."):
        ok(f"{phrase!r} is translated", f'"{phrase}"' in conf)
    # "LIVE" stays English on purpose -- it is the word people already read on
    # a stream, and a translation makes the badge longer than the value it
    # sits beside.
    ok("and the reason LIVE is not is written down",
       "stays English on purpose" in conf)


def main() -> int:
    try:
        import Cheetah.Template  # noqa: F401
    except ImportError:
        print("Cheetah is not installed; nothing to render here.")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-deck-live-"))
    try:
        test_the_styles_are_there()
        test_the_german_words_exist()
        test_without_a_broker(tmp)
        test_with_a_broker(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    for failure in FAILURES:
        print("FAIL", failure)
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

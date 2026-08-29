#!/usr/bin/env python3
"""What in the deck skin nothing uses any more.

Deck is a fork of weewx-wdc, which draws with Nivo and React. This one draws
with ECharts and Cheetah, so a fair amount came across that nothing reads:
settings the templates never ask for, CSS for markup that is not produced,
functions nobody calls.

Dead code in a skin is not free. Somebody reading it to change something has
to work out which half is live, and the answer is not in the file.

Three questions, each asked of what is actually there rather than of a list:

    a setting in skin.conf     is its name anywhere in the templates, the
                               JavaScript, tags.py or the core?
    a class in deck.css        does any rendered page carry it, or does the
                               JavaScript add it?
    a function in tags.py      is it called from a template or from another
                               function?

The last two need the pages rendered, so this needs Cheetah:

    wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \\
      cd /mnt/d/Git/weewx-evo && python tools/deck_dead_test.py'

It reports rather than fails on anything it finds under the allowance below:
a skin gains a class for a state that only appears on somebody's phone, and a
test that goes red for that is a test that gets ignored.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: Classes that exist for a state nothing here produces: a browser's own
#: pseudo-elements, and what the service worker adds when a page is opened
#: offline. Named so that the count below means something.
EXPECTED = frozenset({
    "offline",          # service-worker.js, when the network is gone
    "no-js",            # removed by the first script that runs
})

#: Settings nothing here reads on purpose. `generator_list` is WeeWX's own
#: way of being told which generators to run: this skin renders through
#: `feeds/cheetah`, which does not ask, but somebody running deck under WeeWX
#: itself needs the line. It is the interface to the other program, not a
#: leftover of it.
KEPT = frozenset({"[Generators] generator_list"})

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def skin_dir() -> Path:
    from weewx_evo.skins import bundled

    return Path(bundled()["deck"])


def sources(skin: Path, suffixes: tuple[str, ...]) -> str:
    """Every file of these kinds, as one string. Vendored code left out.

    Cheetah's own comment lines are dropped. A note saying which extension a
    tag used to come from names that tag, and a name mentioned in a comment
    is exactly what this is looking for: `dwd_warning_has_warning` counted as
    live because the note explaining its removal spelled it out.
    """
    out = []
    for path in sorted(skin.rglob("*")):
        if path.suffix not in suffixes or "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix in (".tmpl", ".inc"):
            text = "\n".join(line for line in text.splitlines()
                             if not line.lstrip().startswith("##"))
        out.append(text)
    return "\n".join(out)


def settings_nothing_reads(skin: Path) -> list[str]:
    """Keys in skin.conf that no template, script or module asks for."""
    read_by = sources(skin, (".tmpl", ".inc", ".js", ".py"))
    core = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in (ROOT / "src" / "weewx_evo").rglob("*.py")
        if "__pycache__" not in p.parts)

    section, dead = "", []
    for line in (skin / "skin.conf").read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text.startswith("[") and text.endswith("]"):
            section = text.strip("[]")
            continue
        if not text or text.startswith("#") or "=" not in text:
            continue
        name = text.split("=", 1)[0].strip()
        if name in ("SKIN_NAME", "SKIN_VERSION"):
            continue
        if name not in read_by and name not in core:
            if f"[{section}] {name}" not in KEPT:
                dead.append(f"[{section}] {name}")
    return dead


def render_every_page(skin: Path, work: Path) -> str:
    """Every page the skin produces, as one string of HTML."""
    from weewx_evo import units
    from weewx_evo.feeds.cheetah import CheetahFeed
    from weewx_evo.series import Reader
    from weewx_evo.tags import Tags

    db = work / "weewx.sdb"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE archive (dateTime INTEGER PRIMARY KEY, usUnits INTEGER, "
        "`interval` INTEGER, outTemp REAL, outHumidity REAL, barometer REAL, "
        "windSpeed REAL, windDir REAL, windGust REAL, rain REAL, "
        "rainRate REAL, dewpoint REAL, radiation REAL, UV REAL)")
    now = int(time.time())
    when = now - 400 * 86400          # over a year, so the year pages fill
    while when < now:
        conn.execute(
            "INSERT INTO archive VALUES (?, 17, 5, ?, 61.0, 1013.2, 3.2, "
            "245.0, 7.1, 0.2, 0.4, 15.6, 300.0, 4.0)",
            (when, 18.0 + (when % 28800) / 4800.0))
        when += 1800
    conn.commit()

    copied = work / "deck"
    shutil.copytree(skin, copied)
    reader = Reader(conn)
    tags = Tags(reader, target=units.Target(reader.system),
                unit_system=reader.system,
                station={"location": "Kirchdorf", "latitude": 48.3858,
                         "longitude": 11.7050, "altitude": 440.0,
                         "station_url": "https://example.org",
                         "hardware": "ecowitt", "version": "0.0.1"})
    feed = CheetahFeed(reader=reader, skin=copied, tags=tags)
    produced = feed.produce(work / "out")
    conn.close()

    pages = [p for p in produced.files if p.suffix in (".html", ".json")]
    if not pages:
        raise SystemExit("the skin produced no pages")
    print(f"  rendered {len(pages)} page(s)")
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in pages)


def classes_nothing_carries(skin: Path, html: str) -> list[str]:
    """Class selectors in deck.css that no page and no script produces."""
    css = (skin / "assets" / "deck.css").read_text(encoding="utf-8")
    # Only class names, and only ones written plainly. A skin's CSS also
    # holds attribute and element selectors, and those are not what goes
    # stale when markup is dropped.
    found = set(re.findall(r"\.([a-zA-Z][\w-]{2,})", css))
    scripts = sources(skin, (".js",))
    templates = sources(skin, (".tmpl", ".inc"))

    # Class names a template builds by hand: `class="stat-tile-wrap-$obs"`
    # makes one per observation, and the CSS names a few of them. Whether
    # this run happened to have `appTemp` in its data says nothing about
    # whether the rule is live.
    grown = tuple(re.findall(r'class="([\w-]+?)-\$', templates))

    dead = []
    for name in sorted(found):
        if name in EXPECTED:
            continue
        # In a page, added by a script, or written in a template (which
        # covers markup only produced on a page this run did not build).
        if (f'"{name}"' in html or f"'{name}'" in html
                or f" {name} " in html or f'="{name}"' in html
                or name in scripts or name in templates):
            continue
        if any(name.startswith(f"{prefix}-") for prefix in grown):
            continue
        dead.append(name)
    return dead


def functions_nobody_calls(skin: Path) -> list[str]:
    """Methods in tags.py that no template and no other method calls."""
    source = (skin / "tags.py").read_text(encoding="utf-8")
    templates = sources(skin, (".tmpl", ".inc"))
    names = re.findall(r"^    def ([a-z][\w]*)\(", source, re.MULTILINE)

    dead = []
    for name in names:
        if name.startswith("_"):
            continue
        # Called from a template, or from somewhere else in the module. The
        # definition itself is one occurrence, so two are needed.
        if f"${name}" in templates or f"{name}(" in templates:
            continue
        if source.count(f"{name}(") > 1 or f"self.{name}" in source:
            continue
        dead.append(name)
    return dead


def main() -> int:
    skin = skin_dir()
    print(f"deck at {skin}")

    print("\nsettings in skin.conf that nothing reads")
    dead_settings = settings_nothing_reads(skin)
    for one in dead_settings:
        print(f"    {one}")
    check("none left", len(dead_settings), 0)

    try:
        import Cheetah.Template  # noqa: F401
    except ImportError:
        print("\nCheetah is not installed; the rendered checks are skipped.")
        print("\n" + ("FAIL" if failures else "PASS")
              + f" ({failures} failure(s))")
        return 1 if failures else 0

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        html = render_every_page(skin, Path(raw))

    print("\nclasses in deck.css that no page carries and no script adds")
    dead_css = classes_nothing_carries(skin, html)
    for one in dead_css:
        print(f"    .{one}")
    check("none left", len(dead_css), 0)

    print("\nfunctions in tags.py that nothing calls")
    dead_code = functions_nobody_calls(skin)
    for one in dead_code:
        print(f"    {one}()")
    check("none left", len(dead_code), 0)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("nothing in the skin is there for a reason that has gone")
    return 0


if __name__ == "__main__":
    sys.exit(main())

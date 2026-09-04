#!/usr/bin/env python3
"""Every form, with one of everything configured, run in a browser.

A field that only applies for some values of another has to fold away. The
machinery for it was built long ago -- `Option.when`, `data-when` in the
renderer, a script that acts on it -- and in the core nothing used it: six
pages printed "Only used with 'on its own schedule'" under a field that
stayed visible for the three other choices above it.

`adminpage.py` checks this too, but only for the pages that exist while it
walks them, and at that point it has configured feeds and nothing else. So
the InfluxDB credentials and the MQTT options -- the two forms with the most
conditions in them -- were never looked at. This builds one of every kind
first, which is the whole difference.

Two questions per page, and the second is the one that needs a browser:

  * on load, is each conditional field shown exactly when its condition
    holds?
  * and does it react? A form that is right on load and frozen afterwards is
    wrong the moment somebody uses it. The first version of the script read
    `source.value`, which for a checkbox is "1" ticked or not -- so every
    field hanging on a switch would have stayed visible forever, with the
    markup looking perfectly correct.

    python tools/conditional_test.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import admin as admin_module  # noqa: E402
from weewx_evo.admin import ADD_PAGES, OWN_PAGES, Admin  # noqa: E402
from weewx_evo.cli import all_schemas  # noqa: E402
from weewx_evo.ratelimit import Limits  # noqa: E402

TOKEN = "abcdefghij123456"

#: One of every kind, so every form is built. Named for what they are, so a
#: failure says which page it was on.
CONFIGURED = """
[feeds.pages]
kind = "cheetah"
[feeds.charts]
kind = "json"
[exports.ftp_up]
kind = "ftp"
source = "pages"
[exports.local_here]
kind = "local"
source = "pages"
[exports.rsync_away]
kind = "rsync"
source = "pages"
[uploads.wu]
kind = "wunderground"
[uploads.influx]
kind = "influx"
[uploads.mqtt]
kind = "mqtt"
[forecasts.hourly]
kind = "openmeteo"
[notify.mail]
kind = "email"
[collectors.shed]
kind = "mqtt"
"""

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def no_javascript() -> str:
    """A node with jsdom, or a word saying why not."""
    if shutil.which("node") is None:
        return "there is no node on PATH"
    found = subprocess.run(["node", "-e", "require('jsdom')"],
                           capture_output=True, text=True, check=False)
    return "" if found.returncode == 0 else "node is there but jsdom is not"


def an_installation(work: Path) -> Admin:
    (work / "data").mkdir(exist_ok=True)
    path = work / "evo.toml"
    path.write_text(
        f'token = "{TOKEN}"\n'
        f'live_db = "{(work / "data" / "live.sdb").as_posix()}"\n'
        f'archive_db = "{(work / "data" / "weewx.sdb").as_posix()}"\n'
        f'feeds_dir = "{(work / "data" / "feeds").as_posix()}"\n'
        '[station]\nname = "Kirchdorf"\n'
        "latitude = 48.4012\nlongitude = 11.6301\naltitude = 440.0\n"
        + CONFIGURED, encoding="utf-8")
    return Admin(path, lambda: all_schemas(path), TOKEN,
                 limits=Limits(rate=0, failures=0))


def rendered(admin: Admin, name: str) -> str:
    try:
        page = admin_module.page(admin, name)
    except Exception as exc:
        return f"PAGE RAISED: {exc}"
    return page.decode("utf-8", "replace") if isinstance(page, bytes) else page


def as_a_browser_sees_it(tmp: Path, name: str, html: str) -> dict | None:
    where = tmp / f"{name.replace(':', '-')}.html"
    where.write_text(html, encoding="utf-8")
    script = ROOT / "tools" / "admin_conditional_test.js"
    done = subprocess.run(["node", str(script), str(where)],
                          capture_output=True, text=True, timeout=60,
                          check=False)
    if done.returncode != 0 or not done.stdout.strip():
        check(f"{name}: the page runs", "",
              done.stderr.strip()[:200] or "no output")
        return None
    return json.loads(done.stdout)


def main() -> int:
    missing = no_javascript()
    if missing:
        # Said rather than passed over: this measures a script, and without
        # a DOM to run it in there is nothing here that means anything.
        print(f"one of everything, and what each form shows\n\n  {missing}")
        print("\n  SKIP")
        return 0

    print("one of everything, and what each form shows")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        pages = ([one.name for one in admin.schemas]
                 + list(ADD_PAGES) + list(OWN_PAGES))

        seen, folded, reacting = 0, 0, 0
        for name in dict.fromkeys(pages):
            html = rendered(admin, name)
            if html.startswith("PAGE RAISED"):
                check(f"{name} renders", html, "")
                continue
            if "data-when" not in html:
                continue
            found = as_a_browser_sees_it(work, name, html)
            if found is None:
                continue

            print(f"\n  {name}")
            for one in found["before"]:
                seen += 1
                if not one["sourceHere"]:
                    # Nothing to depend on: it must stay visible. Hiding a
                    # setting for a reason nobody can see is the worse way
                    # to be wrong.
                    check(f"    {one['name']}: no source, so shown",
                          one["hidden"], False)
                    continue
                holds = one["sourceValue"] in one["wanted"]
                folded += one["hidden"]
                check(f"    {one['name']} with {one['on']}="
                      f"{one['sourceValue']!r}",
                      "hidden" if one["hidden"] else "shown",
                      "shown" if holds else "hidden")

            moved = [(a, b) for a, b in zip(found["before"], found["after"],
                                            strict=True)
                     if a["on"] in found["flipped"]]
            if moved:
                changed = any(a["hidden"] != b["hidden"] for a, b in moved)
                reacting += changed
                check("    and it follows the field it depends on",
                      changed, True)

        print()
        # The counts, so a run that quietly stops measuring is visible. A
        # page that lost its conditions renders perfectly and passes every
        # check above by having nothing to check.
        check("conditional fields were found at all", seen > 0, True)
        check("some of them were folded away", folded > 0, True)
        check("and some reacted to a change", reacting > 0, True)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("every form shows what applies, and only while it applies")
    return 0


if __name__ == "__main__":
    sys.exit(main())

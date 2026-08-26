"""Several feeds at once, each configured its own way.

A station shows one theme on the web and another on a phone, and publishes
its data twice in two unit systems. WeeWX arranges that with named sections
under `[StdReport]`; here a feed is a named instance of a kind, the way an
export already was.

The thing that would break silently: two feeds sharing a directory, or one
reading the other's settings. Both would look right on the first run and
wrong on the second.

    python tools/feeds_test.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ.setdefault("TZ", "Europe/Berlin")
try:
    time.tzset()
except AttributeError:  # pragma: no cover - Windows
    pass


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" != {want!r}"))
    return ok


def archive(path: Path) -> None:
    """A database with two readings and a day of them."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE archive (dateTime INTEGER PRIMARY KEY, "
                 "usUnits INTEGER, `interval` INTEGER, outTemp REAL, "
                 "rain REAL)")
    start = int(time.time()) - 86400
    start -= start % 300
    for i in range(288):
        conn.execute("INSERT INTO archive VALUES (?, 1, 5, ?, ?)",
                     (start + i * 300, 50.0 + i / 10.0, 0.01))
    conn.commit()
    conn.close()


def main() -> int:
    from weewx_evo import plots as plot_defs
    from weewx_evo.cli import (build_feeds, configured_feeds, feed_dirs,
                               settings_for)
    from weewx_evo.feedrunner import Runner

    failures = 0
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-feeds-"))
    try:
        db = tmp / "weewx.sdb"
        archive(db)
        config = tmp / "evo.toml"
        config.write_text(f'''
station.name = "Two of everything"
station.units = "US"
archive_db = "{db.as_posix()}"
feeds_dir = "{(tmp / "feeds").as_posix()}"

feeds.metric.kind = "json"
feeds.metric.units = "METRICWX"

feeds.imperial.kind = "json"
feeds.imperial.units = "US"

feeds.page.kind = "diagnostic"
feeds.page.source = "metric"

feeds.theme.kind = "cheetah"
feeds.theme.skin = "Tiny"
feeds.theme.skins_dir = "{(tmp / "skins").as_posix()}"
feeds.theme.encoding = "utf8"
''', encoding="utf-8")

        # A skin is a directory of templates, and a feed of this kind runs
        # one. Two of them side by side is the case WeeWX cannot do without
        # running its whole report cycle twice.
        skin = tmp / "skins" / "Tiny"
        skin.mkdir(parents=True)
        (skin / "skin.conf").write_text(
            "[CheetahGenerator]\n"
            "    [[ToDate]]\n"
            "        [[[index]]]\n"
            "            template = index.html.tmpl\n",
            encoding="utf-8")
        (skin / "index.html.tmpl").write_text(
            "temp=$current.outTemp\n", encoding="utf-8")

        charts = plot_defs.PlotSet([
            plot_defs.Plot("daytemp", "day", 86400,
                           [plot_defs.Line("outTemp")]),
        ])
        plot_defs.save(tmp / "plots.toml", charts)

        args = argparse.Namespace(config=config, weewx_conf=None)
        cfg = settings_for(args)

        print("four feeds, three kinds")
        found = configured_feeds(args)
        failures += not check("all four are configured", sorted(found),
                              ["imperial", "metric", "page", "theme"])
        failures += not check("two of them are the same kind",
                              sorted(f["kind"] for f in found.values()),
                              ["cheetah", "diagnostic", "json", "json"])

        print("\neach writes its own directory")
        where = feed_dirs(cfg, args)
        failures += not check("four directories, no two the same",
                              len(set(where.values())), 4)
        failures += not check("named after the feed",
                              where["metric"].name, "metric")

        print("\nand each reads its own settings")
        runner = Runner(build_feeds(args, cfg, charts), archive_path=db)
        note = runner.run_once()
        failures += not check("all four ran", note.count(":"), 4)

        metric = json.loads((where["metric"] / "daytemp.json")
                            .read_text(encoding="utf-8"))
        imperial = json.loads((where["imperial"] / "daytemp.json")
                              .read_text(encoding="utf-8"))
        failures += not check("one in Celsius", metric["unit"], "degree_C")
        failures += not check("one in Fahrenheit", imperial["unit"],
                              "degree_F")
        # The same reading, so the numbers have to be the same temperature.
        c = metric["series"][0]["values"][0]
        f = imperial["series"][0]["values"][0]
        failures += not check("and they are the same reading",
                              round(c * 1.8 + 32.0, 2), round(f, 2))

        print("\nthe one that reads another runs after it")
        page = where["page"] / "index.html"
        failures += not check("the page was written", page.exists(), True)
        failures += not check("and drew what the metric feed wrote",
                              "daytemp.json" in page.read_text(
                                  encoding="utf-8"), True)

        print("\nthe skin ran too, on the same database")
        rendered = where["theme"] / "index.html"
        failures += not check("its page was written", rendered.exists(),
                              True)
        page_text = rendered.read_text(encoding="utf-8")
        failures += not check("with a reading in it",
                              page_text.startswith("temp="), True)
        # Stored in Fahrenheit, and nobody overruled it: this feed was
        # told nothing and the skin says nothing, so the archive's own
        # unit stands.
        failures += not check("in what the archive holds",
                              "°F" in page_text, True)

        print("\nand a file that names no feeds still gets some")
        bare = tmp / "bare.toml"
        bare.write_text(f'archive_db = "{db.as_posix()}"\n', encoding="utf-8")
        # A fresh resolver, or the first configuration is still cached.
        from weewx_evo import settings as settings_state

        settings_state.forget_running()
        plain = configured_feeds(argparse.Namespace(config=bare,
                                                    weewx_conf=None))
        failures += not check("the two that ship", sorted(plain),
                              ["diagnostic", "json"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

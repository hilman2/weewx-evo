#!/usr/bin/env python3
"""Every test in this repository, one after another, one exit code.

There are thirty-odd test tools here. Each says PASS or a count on its own,
which is the right thing when you are working on the part it covers and the
wrong thing when you want to know whether the repository is sound: thirty
commands, thirty scrollbacks, and the one that failed is somewhere in the
middle.

    python tools/runtests.py            # everything that can run here
    python tools/runtests.py --list     # what would run, and why not
    python tools/runtests.py units sun  # only the ones whose names match

What a run needs is not the same for every test, and this says so rather than
failing. Three things can be missing:

  * **Cheetah and Pillow.** A skin is written in Cheetah and a chart is drawn
    with Pillow; without them those feeds cannot run at all.
  * **WeeWX itself.** Six of these compare our arithmetic against WeeWX's by
    importing both and running them side by side. That is the point of them,
    so without WeeWX they are skipped rather than approximated.
  * **`reference/weewx.sdb`.** A real archive, which is not in the repository
    because it is somebody's actual measurements. See the README for pulling
    one.

Anything skipped is named, with what would make it run. A test suite that
quietly covers half of what you think it covers is worse than one that covers
half and says so -- and `docker/run.sh` exists precisely so that none of the
three is ever missing.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

#: The timezone the day tables are keyed on. Not decoration: `archive_day_*`
#: is keyed on local midnight, and read in the wrong zone the comparison pairs
#: one day with another. That produced 27 failures once, none of them real.
ZONE = "Europe/Berlin"


@dataclass
class Test:
    """One test tool, and what it needs before it can say anything."""

    name: str
    command: list[str]
    why: str
    #: Modules that must import, or the run means nothing.
    needs: tuple[str, ...] = ()
    #: True when it reads `reference/weewx.sdb`.
    needs_reference: bool = False
    #: Minutes, roughly. Only used to warn before a long one.
    slow: bool = False


def database() -> Path:
    return ROOT / "reference" / "weewx.sdb"


def tests() -> list[Test]:
    """Everything, in the order a failure is most usefully found in.

    The arithmetic first: if `aggregate.py` is wrong, every test after it is
    wrong too and reading their output is a waste of an afternoon.
    """
    db = str(database())
    return [
        # -- the arithmetic, and the file it writes ----------------------
        Test("difftest", ["difftest.py", db],
             "the day statistics, recomputed and compared with WeeWX's own",
             needs_reference=True),
        Test("roundtrip", ["roundtrip.py", db],
             "writing into a real archive and reading it back",
             needs_reference=True),
        Test("derive", ["derive_test.py", db],
             "the derived readings against what WeeWX wrote",
             needs_reference=True),

        # -- the transcriptions, against WeeWX itself --------------------
        Test("units", ["unitcheck.py"],
             "all 147 conversions against WeeWX, at nine values each",
             needs=("weewx",)),
        Test("series", ["seriestest.py", db, ZONE],
             "get_series, span by span, against WeeWX's",
             needs=("weewx",), needs_reference=True),
        Test("tags", ["tagcheck.py", db, ZONE],
             "$day.outTemp.max and the rest, against WeeWX's answers",
             needs=("weewx", "Cheetah"), needs_reference=True),
        Test("sun", ["suncheck.py"],
             "sunrise and declination against pyephem",
             needs=("ephem",)),
        Test("moon", ["mooncheck.py"],
             "moonrise, phase and the seasons against pyephem",
             needs=("ephem",)),
        Test("planets", ["planetcheck.py"],
             "the planets against pyephem, over forty years",
             needs=("ephem",), slow=True),

        # -- the parts that stand on their own ---------------------------
        Test("settings", ["settings_test.py"],
             "the five places a setting comes from, in order"),
        Test("admin", ["adminpage.py"],
             "the settings page: every form, and what a partial POST does"),
        Test("netaccess", ["netaccess_test.py"],
             "who gets an answer and who gets a 404"),
        Test("ratelimit", ["ratelimit_test.py"],
             "ten a second, five bad tokens a minute"),
        Test("web", ["web_test.py"],
             "the built-in server"),
        Test("smoke", ["smoke.py"],
             "listener, archiver and database together"),
        Test("multisource", ["multisource.py"],
             "two stations into one series"),
        Test("driverinstall", ["driverinstall.py"],
             "installing a driver from outside the repository"),
        Test("export", ["export_test.py"],
             "FTP and rsync, against servers started for the test"),
        Test("uploads", ["upload_test.py"],
             "Weather Underground and the rest, against WeeWX's own strings"),
        Test("mqtt", ["mqtt_test.py"],
             "the MQTT client, against a broker started for the test"),
        Test("realtime", ["realtime_test.py"],
             "the realtime files, field by field"),
        Test("forecast", ["forecast_test.py"],
             "Open-Meteo, DWD, MeteoAlarm and NWS, from recorded responses"),
        Test("feedtiming", ["feedtiming_test.py"],
             "every trigger a feed declares is one the runner acts on"),
        Test("watchdog", ["watchdog_test.py"],
             "it restarts for what a restart fixes, and not more often"),
        Test("livedb", ["livedb_test.py"],
             "the live table hands a descriptor back when its thread ends"),
        Test("adminsearch", ["adminsearch_test.py"],
             "a word finds its setting, and the link lands on it"),
        Test("adminhome", ["adminhome_test.py"],
             "the overview says what is wrong, and only when something is"),
        Test("archives", ["archives_test.py"],
             "two places, two series, and neither one is the other's"),
        Test("stations", ["stations_test.py"],
             "announced consoles, strangers noticed, neither guessed at"),
        Test("shim", ["shim_test.py"],
             "a WeeWX driver, run in its own process, delivering to us",
             needs=("weewx",)),
        Test("wunderground", ["wunderground_test.py"],
             "the WU protocol, against our own upload of the same protocol"),

        # -- what a page comes out as ------------------------------------
        Test("feeds", ["feeds_test.py"],
             "several feeds at once, each configured its own way"),
        Test("cheetah", ["cheetah_test.py"],
             "a WeeWX skin, run unchanged",
             needs=("Cheetah",)),
        Test("images", ["image_test.py"],
             "the charts, drawn",
             needs=("PIL",)),
        Test("deck", ["deck_test.py", db],
             "the bundled skin",
             needs=("Cheetah",), needs_reference=True),
        Test("deck-live", ["deck_live_test.py"],
             "live readings: the document, live.php, and the page run in jsdom",
             needs=("Cheetah",)),

        # -- the driver's own suite --------------------------------------
        Test("push", ["-m", "pytest", "tests/push", "-q"],
             "the six push protocols' own suite, 135 tests",
             needs=("pytest",)),

        # -- and the check that finds what no test does -------------------
        Test("ruff", ["-m", "ruff", "check", "src/", "tools/", "tests/"],
             "a call in a branch nothing walks through",
             needs=("ruff",)),
    ]


@dataclass
class Result:
    test: Test
    status: str            # "pass", "fail", "skip"
    seconds: float = 0.0
    reason: str = ""
    output: list[str] = field(default_factory=list)


def importable(module: str) -> bool:
    """Whether the test's own interpreter can import it.

    Asked in a subprocess rather than here: `weewx` in particular pulls in a
    great deal on import, and a test runner that has half of WeeWX loaded is
    a test runner that can make a test pass for the wrong reason.
    """
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True, cwd=ROOT, check=False).returncode == 0


def missing(test: Test, have: dict[str, bool], reference: bool) -> str:
    for module in test.needs:
        if not have.get(module, False):
            return {
                "weewx": "WeeWX is not importable -- there is nothing to "
                         "compare against. PYTHONPATH=/path/to/weewx/src",
                "Cheetah": "Cheetah is not installed (pip install CT3)",
                "PIL": "Pillow is not installed (pip install Pillow)",
                "ephem": "pyephem is not installed (pip install ephem)",
                "pytest": "pytest is not installed",
                "ruff": "ruff is not installed",
            }.get(module, f"{module} is not importable")
    if test.needs_reference and not reference:
        return (f"{database()} is not there. It holds real measurements, so "
                f"it is not in the repository; see the README.")
    return ""


def run(test: Test) -> Result:
    command = [sys.executable]
    if test.command[0].endswith(".py"):
        command.append(str(TOOLS / test.command[0]))
        command += test.command[1:]
    else:
        command += test.command

    environment = dict(os.environ)
    # Every one of these keys its day boundaries on local midnight. Left to
    # the machine, the same test passes here and fails on a server in UTC.
    environment.setdefault("TZ", ZONE)
    environment["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(ROOT / "src"), environment.get("PYTHONPATH", "")) if p)

    started = time.monotonic()
    # check=False on purpose: a non-zero exit is the finding, not an accident,
    # and raising here would end the run at the first failing test.
    finished = subprocess.run(command, cwd=ROOT, env=environment,
                              capture_output=True, text=True,
                              errors="replace", check=False)
    seconds = time.monotonic() - started
    output = (finished.stdout + finished.stderr).splitlines()
    return Result(test, "pass" if finished.returncode == 0 else "fail",
                  seconds, "", output)


def report(results: list[Result]) -> int:
    passed = [r for r in results if r.status == "pass"]
    failed = [r for r in results if r.status == "fail"]
    skipped = [r for r in results if r.status == "skip"]

    print()
    print("=" * 72)
    for result in results:
        mark = {"pass": "ok  ", "fail": "FAIL", "skip": "--  "}[result.status]
        timing = f"{result.seconds:6.1f}s" if result.seconds else "       "
        print(f"  {mark}  {result.test.name:<14} {timing}  "
              f"{result.reason or result.test.why}")
    print("=" * 72)

    if failed:
        print()
        for result in failed:
            print(f"--- {result.test.name} " + "-" * (68 - len(result.test.name)))
            # The tail, not the whole thing: these tools print a line per
            # check and the useful part is always at the end.
            for line in result.output[-30:]:
                print(f"    {line}")
            print()

    total = len(passed) + len(failed)
    print(f"{len(passed)}/{total} passed"
          + (f", {len(failed)} failed" if failed else "")
          + (f", {len(skipped)} skipped" if skipped else ""))
    if skipped:
        print()
        print("Skipped, and what would run them:")
        for result in skipped:
            print(f"  {result.test.name:<14} {result.reason}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("only", nargs="*",
                        help="run only tests whose names contain one of these")
    parser.add_argument("--list", action="store_true",
                        help="say what would run, and skip nothing quietly")
    parser.add_argument("--skip-slow", action="store_true",
                        help="leave out the ones that take minutes")
    args = parser.parse_args()

    wanted = tests()
    if args.only:
        wanted = [t for t in wanted
                  if any(word.lower() in t.name.lower() for word in args.only)]
        if not wanted:
            print(f"Nothing matches {' '.join(args.only)}. There is: "
                  + ", ".join(t.name for t in tests()), file=sys.stderr)
            return 2
    if args.skip_slow:
        wanted = [t for t in wanted if not t.slow]

    # Asked once each. Starting an interpreter thirty times to ask the same
    # six questions is most of the run for a suite that fails early.
    modules = sorted({m for t in wanted for m in t.needs})
    have = {m: importable(m) for m in modules}
    reference = database().exists()

    if args.list:
        for test in wanted:
            reason = missing(test, have, reference)
            print(f"  {'--' if reason else 'ok'}  {test.name:<14} "
                  f"{reason or test.why}")
        return 0

    print(f"{len(wanted)} test(s), in {ROOT}")
    if shutil.which("php") is None:
        # Said once, up front. `live.php` runs on somebody else's web host,
        # and "it looked fine to me" is not a test of it.
        print("  note: no php on PATH, so live.php is checked in Docker or "
              "not at all")
    print()

    results: list[Result] = []
    for test in wanted:
        reason = missing(test, have, reference)
        if reason:
            print(f"--   {test.name:<14} skipped: {reason.splitlines()[0]}")
            results.append(Result(test, "skip", 0.0, reason))
            continue
        print(f"     {test.name:<14} ...", end="", flush=True)
        result = run(test)
        print(f"\r  {'ok  ' if result.status == 'pass' else 'FAIL'} "
              f"{test.name:<14} {result.seconds:6.1f}s")
        results.append(result)

    return report(results)


if __name__ == "__main__":
    sys.exit(main())

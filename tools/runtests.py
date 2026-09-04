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
    because it is somebody's actual measurements. The wiki page Testing says
    how to pull one.

Anything skipped is named, with what would make it run. A test suite that
quietly covers half of what you think it covers is worse than one that covers
half and says so -- and `docker/run.sh` exists precisely so that none of the
three is ever missing.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

#: The timezone the day tables are keyed on. Not decoration: `archive_day_*`
#: is keyed on local midnight, and read in the wrong zone the comparison pairs
#: one day with another. That produced 27 failures once, none of them real.
ZONE = "Europe/Berlin"

# Windows' C runtime does not understand IANA names in ``TZ``.  It accepts
# them as a fixed standard-time abbreviation, which shifts every summer day
# boundary by one hour.  The POSIX spelling carries the same Berlin DST rules
# and is understood there; Unix gets the clearer IANA name.
ZONE_ENV = "CET-1CEST,M3.5.0,M10.5.0/3" if os.name == "nt" else ZONE


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


def _jobs() -> int:
    """How many to run at once by default.

    Capped rather than one per core. Half of these start a real process, bind
    a port and wait on a clock, so they are not CPU-bound and the machine is
    not the limit -- but a container given two cores and told to run sixteen
    `serve` processes measures the scheduler rather than the code.
    """
    return max(1, min(8, (os.cpu_count() or 2)))


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
        # The one rule, in the direction the others do not go: a database
        # *we* wrote, opened and written into by WeeWX itself.
        Test("stillweewx", ["stillweewx_test.py"],
             "a database written here is one WeeWX can carry on using",
             needs=("weewx",)),

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
        Test("setup", ["setup_test.py"],
             "an empty directory to a configured station, by forms alone"),
        Test("consolesetup", ["console_setup_test.py"],
             "the page asks each driver how its hardware is pointed here",
             needs=("weewx_evo_ecowitt", "weewx_evo_ambient",
                    "weewx_evo_wunderground", "weewx_evo_acurite",
                    "weewx_evo_lacrosse", "weewx_evo_weatherflow")),
        Test("admin", ["adminpage.py"],
             "the settings page: every form, and what a partial POST does"),
        Test("resilience", ["resilience_test.py"],
             "a failure inside a handler is answered, not dropped"),
        Test("netaccess", ["netaccess_test.py"],
             "who gets an answer and who gets a 404"),
        Test("ratelimit", ["ratelimit_test.py"],
             "ten a second, five bad tokens a minute"),
        Test("tokenless", ["tokenless_test.py"],
             "hardware with no field for a token, and everything that has one"),
        Test("wizard", ["wizard_test.py"],
             "one guided setup per driver, derived from what it already says"),
        Test("addons", ["addons_test.py"],
             "an add-on is installed by name, and only a name from the list"),
        Test("addonpath", ["addonpath_test.py"],
             "what is installed outlives the process that installed it"),
        Test("web", ["web_test.py"],
             "the built-in server"),
        Test("smoke", ["smoke.py"],
             "listener, archiver and database together",
             needs=("weewx_evo_ecowitt",)),
        Test("multisource", ["multisource.py"],
             "isolated source policy and Place-owned runtime routing"),
        Test("driverinstall", ["driverinstall.py"],
             "installing a driver from outside the repository"),
        Test("export", ["export_test.py"],
             "FTP and rsync, against servers started for the test"),
        Test("uploads", ["upload_test.py"],
             "Weather Underground and the rest, against WeeWX's own strings"),
        Test("mqtt", ["mqtt_test.py"],
             "the MQTT client, against a broker started for the test"),
        Test("metrics", ["metrics_test.py"],
             "what the process publishes about itself, and what it must not"),
        Test("api", ["api_test.py"],
             "every answer against the reader it is a shell over"),
        Test("maintenance", ["maintenance_test.py"],
             "a copy of a database being written to, and whether it is sound",
             slow=True),
        Test("notify", ["notify_test.py"],
             "who hears about it, how often, and when it is over"),
        Test("import", ["import_test.py"],
             "a MySQL or Postgres dump, and a CSV, into the archive"),
        Test("quality", ["quality_test.py"],
             "calibration and limits, and where a spike must not reach"),
        Test("influx", ["influx_test.py"],
             "the archive as line protocol, and which answers mean stop"),
        Test("grafana", ["grafana_test.py"],
             "the generated dashboards: layout, units, queries, language"),
        Test("realtime", ["realtime_test.py"],
             "the realtime files, field by field"),
        Test("forecast", ["forecast_test.py"],
             "Open-Meteo, DWD, MeteoAlarm and NWS, from recorded responses"),
        Test("feedtiming", ["feedtiming_test.py"],
             "every trigger a feed declares is one the runner acts on"),
        Test("schedule", ["schedule_test.py"],
             "an interval runs on the hour's grid, not from when it started"),
        Test("watchdog", ["watchdog_test.py"],
             "it restarts for what a restart fixes, and not more often"),
        Test("polling", ["polling_test.py"],
             "hardware that has to be asked arrives like one that pushes"),
        Test("unread", ["unread_test.py"],
             "an upload nothing can read is seen rather than only logged"),
        Test("catalogue", ["catalogue_test.py"],
             "which add-on reads what turned up, and offline is a state"),
        Test("livedb", ["livedb_test.py"],
             "the live table hands a descriptor back when its thread ends"),
        Test("livesource", ["livesource_test.py"],
             "which console a live reading comes from"),
        Test("roles", ["roles_test.py"],
             "a second station is moved aside, and one notices nothing"),
        Test("placement", ["placement_test.py"],
             "the read side gives what the write side gave, on real payloads",
             needs=("weewx_evo_ecowitt", "weewx_evo_ambient",
                    "weewx_evo_wunderground", "weewx_evo_acurite",
                    "weewx_evo_lacrosse", "weewx_evo_weatherflow")),
        Test("unitgroup", ["unitgroup_test.py"],
             "when a driver and the schema disagree about what a column is"),
        Test("adminfields", ["adminfields_test.py"],
             "a reading can be placed, and what is already there is said",
             needs=("weewx_evo_ecowitt",)),
        Test("adminlive", ["adminlive_test.py"],
             "the live table's own rows, and where each reading goes"),
        Test("adminsearch", ["adminsearch_test.py"],
             "a word finds its setting, and the link lands on it"),
        Test("adminlang", ["adminlang_test.py"],
             "how much of the settings page asks for its words"),
        Test("conditional", ["conditional_test.py"],
             "every form shows what applies, and only while it applies"),
        Test("adminwords", ["adminwords_test.py"],
             "the interface says driver, and never our word for the split"),
        Test("driverflow", ["driverflow_test.py"],
             "one entry, one form and one list, whatever the hardware is",
             needs=("weewx_evo_ecowitt",)),
        Test("adminhome", ["adminhome_test.py"],
             "the overview says what is wrong, and only when something is"),
        Test("archives", ["archives_test.py"],
             "two places, two series, and neither one is the other's",
             needs=("weewx_evo_ecowitt", "weewx_evo_wunderground")),
        # Slow on purpose: a real serve, a simulator uploading
        # throughout, and two archive intervals to wait for. It
        # covers the half archives_test does not -- feeds,
        # exports, and what a page can see.
        Test("archives-e2e", ["archives_e2e.py"],
             "two archives, from the console to the published file",
             slow=True),
        Test("stations", ["stations_test.py"],
             "announced consoles, strangers noticed, neither guessed at",
             needs=("weewx_evo_wunderground",)),
        Test("restart", ["restart_test.py"],
             "a restart re-does nothing, and the site is up meanwhile",
             slow=True),
        Test("driverprocess", ["driverprocess_test.py"],
             "a driver on this machine is started and kept alive here"),
        Test("collector", ["collector_test.py"],
             "a collector is a station: its own name, its own rules"),
        # Running a WeeWX driver is an add-on, and its seven tests went with
        # it -- the shim, the stand-ins, and the three simulated devices that
        # compare our stand-in against WeeWX's own code field for field. They
        # run in weewx-evo-weewx-driver, beside the code they measure.
        Test("wunderground", ["wunderground_test.py"],
             "the WU protocol, against our own upload of the same protocol",
             needs=("weewx_evo_wunderground",)),

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
        Test("deck-dead", ["deck_dead_test.py"],
             "nothing in the skin is left from the fork it came from",
             needs=("Cheetah",)),
        Test("deck-live", ["deck_live_test.py"],
             "live readings: the document, live.php, and the page run in jsdom",
             needs=("Cheetah",)),
        Test("deck-places", ["deck_places_test.py"],
             "one site, several places -- and one place unchanged",
             needs=("Cheetah",)),

        # The protocols' own suite moved out with them. It tests
        # `protocols/` and `catalogs/`, which are byte-identical to
        # weewx-ultimate-push, and it belongs beside them: run there, a fix
        # to a field placement is one diff in one repository.

        # -- and the check that finds what no test does -------------------
        Test("ruff", ["-m", "ruff", "check", "src/", "tools/"],
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


def _add_on(module: str) -> str:
    """What to install, for a test that needs a driver the core does not ship.

    The core ships none, so a run on a machine with no add-on installed skips
    these rather than failing -- that machine is a valid installation, and it
    is exactly what a fresh one looks like. The Docker image installs them,
    which is where they are actually measured.
    """
    if not module.startswith("weewx_evo_"):
        return ""
    package = module.replace("_", "-")
    return (f"{package} is not installed. It is an add-on, not part of the "
            f"core: pip install git+https://github.com/weewx-evo/{package}")


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
            }.get(module, _add_on(module) or f"{module} is not importable")
    if test.needs_reference and not reference:
        return (f"{database()} is not there. It holds real measurements, so "
                f"it is not in the repository; the wiki page Testing says "
                f"how to pull one.")
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
    environment["TZ"] = ZONE_ENV
    environment["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(ROOT / "src"), environment.get("PYTHONPATH", "")) if p)

    # pytest's default is one shared ``pytest-of-<user>`` directory. Two test
    # runners (or two agents) can then inspect or clean the same numbered
    # children at once; on Windows the loser sees PermissionError before a
    # test has even started. Give this invocation a private, exact root.
    pytest_root = None
    if test.name == "push":
        pytest_root = tempfile.mkdtemp(prefix="weewx-evo-pytest-")
        command.append(f"--basetemp={pytest_root}")

    started = time.monotonic()
    # check=False on purpose: a non-zero exit is the finding, not an accident,
    # and raising here would end the run at the first failing test.
    try:
        finished = subprocess.run(command, cwd=ROOT, env=environment,
                                  capture_output=True, text=True,
                                  errors="replace", check=False)
    finally:
        if pytest_root is not None:
            shutil.rmtree(pytest_root, ignore_errors=True)
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
    parser.add_argument("--jobs", "-j", type=int, default=_jobs(),
                        help="how many to run at once (1 runs them in order, "
                             "which is what to do when reading a failure)")
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

    results: dict[str, Result] = {}
    running = []
    for test in wanted:
        reason = missing(test, have, reference)
        if reason:
            print(f"--   {test.name:<14} skipped: {reason.splitlines()[0]}")
            results[test.name] = Result(test, "skip", 0.0, reason)
        else:
            running.append(test)

    # Longest first. With workers of unequal length the tail is whatever
    # started last, so a ninety-second test picked up at the end costs ninety
    # seconds nobody is using -- measured at 13 minutes for a suite whose
    # longest test is 97 seconds.
    running.sort(key=lambda t: (not t.slow, t.name))

    if args.jobs == 1:
        for test in running:
            print(f"     {test.name:<14} ...", end="", flush=True)
            result = run(test)
            print(f"\r  {'ok  ' if result.status == 'pass' else 'FAIL'} "
                  f"{test.name:<14} {result.seconds:6.1f}s")
            results[test.name] = result
    else:
        # Each test already keeps its state in a temporary directory of its
        # own -- that is the rule this suite is written to -- so they do not
        # need to be told about each other. What they do share is the clock:
        # several starting a real `serve` at once take longer each, which is
        # why the report prints wall-clock per test and the total separately.
        print(f"  running {args.jobs} at a time\n")
        started = time.monotonic()
        with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            pending = {pool.submit(run, one): one for one in running}
            for done in cf.as_completed(pending):
                result = done.result()
                results[result.test.name] = result
                print(f"  {'ok  ' if result.status == 'pass' else 'FAIL'} "
                      f"{result.test.name:<14} {result.seconds:6.1f}s")
        print(f"\n  {time.monotonic() - started:.0f}s of wall clock")

    # Reported in the order the list declares, whatever order they finished
    # in: that order is "where a failure is most usefully found", and it is
    # the only thing making two runs comparable.
    return report([results[t.name] for t in wanted if t.name in results])


if __name__ == "__main__":
    sys.exit(main())

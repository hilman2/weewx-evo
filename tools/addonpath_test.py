#!/usr/bin/env python3
"""An add-on installed from the page is still there after a restart.

The whole point of a shop is that what you install stays installed. In a
container it would not: site-packages is in the image, so `docker compose up`
takes it away again -- with the console still uploading and nothing reading
it, which is the worst way to find out.

So an add-on goes into the data directory, which is a volume on every
deployment here, and the core puts that directory on `sys.path` before it
walks the entry points.

What is measured is the part that cannot be reasoned about: a package
installed into a directory, and a **fresh interpreter** finding it. Same
process would prove nothing -- `sys.path` is already what this one made it.

    python tools/addonpath_test.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import addons  # noqa: E402

failures = 0

#: A package with an entry point, built where the test can see it. Not a real
#: add-on: what is being measured is the path and the entry point, and a real
#: one would make this a test of somebody's network.
PACKAGE = {
    "pyproject.toml": """
[project]
name = "weewx-evo-fromthetest"
version = "0.1.0"
requires-python = ">=3.11"

[project.entry-points."weewx_evo.drivers"]
fromthetest = "weewx_evo_fromthetest:Driver"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
""",
    "src/weewx_evo_fromthetest/__init__.py": '''
"""A driver that exists to be found."""


class Driver:
    def packets(self, body, meta):
        return []
''',
}


def check(what: str, got: object, want: object) -> None:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1


def _write(where: Path) -> Path:
    source = where / "package"
    for name, text in PACKAGE.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return source


def _in_a_fresh_interpreter(data: Path) -> dict:
    """Ask a new process what it can see. The whole point is that it is new."""
    script = textwrap.dedent("""
        import json, sys
        sys.path.insert(0, %r)
        from weewx_evo import addons
        from weewx_evo.ingest import drivers

        registry = drivers.Registry()
        names = registry.names()
        print(json.dumps({
            "names": names,
            "installed": sorted(addons.installed()),
            "on_path": str(addons.on_path() or ""),
        }))
    """) % str(ROOT / "src")
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True,
        env={**os.environ, "WEEWX_EVO_ADDON_DIR": str(data / "addons")},
        check=False)
    if done.returncode != 0:
        return {"error": done.stderr.strip().splitlines()[-1:]}
    return json.loads(done.stdout.strip().splitlines()[-1])


def it_survives_a_restart() -> None:
    print("\ninstalled into the data directory")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        data = Path(raw)
        source = _write(data)
        into = data / "addons"
        os.environ["WEEWX_EVO_ADDON_DIR"] = str(into)
        try:
            check("nothing there yet",
                  "fromthetest" in _in_a_fresh_interpreter(data)["names"],
                  False)

            # `--no-build-isolation`, because the test run has no network:
            # with isolation pip fetches setuptools into a throwaway
            # environment, and there is nowhere to fetch it from. It is
            # installed here, which is what isolation would have got anyway.
            done = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet",
                 "--no-build-isolation", "--upgrade", "--no-deps",
                 "--target", str(into), str(source)],
                capture_output=True, text=True, check=False)
            if done.returncode != 0:
                # Not a failure of what is being measured. pip needs a build
                # backend to make a package at all, and a machine without one
                # cannot answer this question either way.
                print("  --   pip could not build the test package here, so "
                      "there is nothing to install")
                print(f"       {done.stderr.strip().splitlines()[-1:]}")
                return

            # A new process. The one that installed it has whatever
            # `sys.path` it made for itself, so it can prove nothing.
            found = _in_a_fresh_interpreter(data)
            check("a fresh interpreter finds the driver",
                  "fromthetest" in found.get("names", []), True)
            check("and knows which package it came from",
                  "weewx-evo-fromthetest" in found.get("installed", []), True)
            check("because the data directory is on the path",
                  found.get("on_path", "").endswith("addons"), True)

            # And taking it away again, which pip cannot do for a `--target`
            # install -- it knows nothing about a directory it wrote into
            # once. The record it left is what says which files were its.
            check("removing it says nothing went wrong",
                  addons.remove("weewx-evo-fromthetest"), "")
            after = _in_a_fresh_interpreter(data)
            check("and then a fresh interpreter does not find it",
                  "fromthetest" in after.get("names", []), False)
            check("with nothing of it left behind",
                  sorted(p.name for p in into.glob("weewx_evo_fromthetest*")),
                  [])
        finally:
            os.environ.pop("WEEWX_EVO_ADDON_DIR", None)


def the_path_is_added_once() -> None:
    """A path added twice is searched twice, on every import, forever."""
    print("\nadding it is idempotent")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        where = Path(raw) / "addons"
        where.mkdir()
        os.environ["WEEWX_EVO_ADDON_DIR"] = str(where)
        addons._on_path = None
        try:
            before = list(sys.path)
            for _ in range(3):
                addons.on_path()
            added = [one for one in sys.path if one not in before]
            check("added exactly once", len(added), 1)
            # Appended rather than prepended: an add-on must not be able to
            # shadow a core module by being installed under its name.
            check("and at the end, so nothing here can be shadowed",
                  sys.path[-1], added[0])
        finally:
            for one in [p for p in sys.path if p not in before]:
                sys.path.remove(one)
            addons._on_path = None
            os.environ.pop("WEEWX_EVO_ADDON_DIR", None)


def a_missing_directory_is_not_an_error() -> None:
    """A station that has installed nothing is the ordinary first-run state."""
    print("\nwith no add-on directory at all")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        os.environ["WEEWX_EVO_ADDON_DIR"] = str(Path(raw) / "nope")
        addons._on_path = None
        try:
            check("nothing is added", addons.on_path(), None)
        finally:
            addons._on_path = None
            os.environ.pop("WEEWX_EVO_ADDON_DIR", None)


def main() -> int:
    it_survives_a_restart()
    the_path_is_added_once()
    a_missing_directory_is_not_an_error()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("what is installed outlives the process that installed it")
    return 0


if __name__ == "__main__":
    sys.exit(main())

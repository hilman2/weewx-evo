"""Install a third-party driver, load it, and take an upload with it.

Two directories, two different things:

  * `plugins/` holds the drivers that ship with weewx-evo. They are ours, they
    are in the repository, and they are released with the core.
  * A separate directory holds drivers somebody else wrote. They are installed
    with `weewx-evo driver install`, they live outside the package so an
    upgrade cannot touch them, and nothing in there can be mistaken for
    something we maintain.

This exercises the second one end to end: build a small driver, install it from
a directory and from a zip, load it beside the bundled ones, and check that an
upload routed to it comes out as a packet.

    python tools/driverinstall.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.db.live import LiveStore
from weewx_evo.ingest import userdrivers
from weewx_evo.ingest.drivers import Registry
from weewx_evo.ingest.listener import HttpListener, Ingest

# A whole driver. This is the entire contract: a package with load(registry),
# and an object with packets(). Nothing is inherited, nothing is registered
# anywhere else, and the core learns of it only through the entry point.
DRIVER = '''
"""A driver for a fictional station that posts one line of numbers."""

from weewx_evo.db.live import Packet
from weewx_evo.units import METRICWX


class TinyDriver:
    """Reads "t=21.4;h=55;p=1013" and nothing else."""

    response = (b"thanks\\n", "text/plain")

    NAMES = {"t": "outTemp", "h": "outHumidity", "p": "barometer"}

    def packets(self, body, meta):
        data = {}
        for pair in body.decode().strip().split(";"):
            if "=" not in pair:
                continue
            key, _, value = pair.partition("=")
            name = self.NAMES.get(key.strip())
            if name:
                data[name] = float(value)
        if not data:
            return []
        return [Packet(dateTime=int(meta["received"]), usUnits=METRICWX,
                       data=data, source="tiny", kind="loop")]

    def status(self):
        return {"reads": "t=;h=;p="}


def load(registry):
    registry.register("tiny", TinyDriver(), replace=True)
    return True
'''


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


def make_source(root: Path) -> Path:
    """A driver package on disk, as somebody would publish it."""
    package = root / "tinystation"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(DRIVER, encoding="utf-8")
    (package / "README.md").write_text("# tinystation\n", encoding="utf-8")
    return package


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-driver-"))
    failures = 0
    try:
        source = make_source(tmp / "published")
        where = tmp / "userdrivers"

        print("installing from a directory")
        name, notable = userdrivers.install(str(source), where)
        failures += not check("installed as", name, "tinystation")
        failures += not check("landed in the user directory",
                              (where / "tinystation" / "__init__.py").exists(), True)
        failures += not check("origin recorded",
                              (where / "tinystation" / ".origin").read_text().strip(),
                              str(source))
        failures += not check("not in the package",
                              (Path(__file__).parent.parent / "src" / "weewx_evo"
                               / "ingest" / "plugins" / "tinystation").exists(), False)

        print("\ninstalling twice needs --force")
        try:
            userdrivers.install(str(source), where)
            failures += not check("second install", "allowed", "refused")
        except userdrivers.InstallError as exc:
            failures += not check("second install refused", "already installed" in str(exc),
                                  True)
        userdrivers.install(str(source), where, force=True)
        failures += not check("with --force", "replaced", "replaced")

        print("\nthe code is read before it is trusted")
        # Not a sandbox and not claimed to be one. A driver runs in this
        # process and can import whatever it likes; this only makes sure the
        # operator sees what it reaches for before it does.
        failures += not check("nothing notable in a plain driver", notable, {})
        risky = tmp / "risky" / "sneaky"
        risky.mkdir(parents=True)
        (risky / "__init__.py").write_text(
            "import sqlite3\nimport subprocess\n\n"
            "def load(registry):\n    return True\n", encoding="utf-8")
        _n, found = userdrivers.install(str(risky), where, name="sneaky")
        failures += not check("sqlite3 reported", any("sqlite3" in k for k in found), True)
        failures += not check("subprocess reported",
                              any("subprocess" in k for k in found), True)
        userdrivers.remove("sneaky", where)

        print("\ninstalling from a zip")
        archive = tmp / "tinystation.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for path in source.rglob("*"):
                zf.write(path, Path("tinystation-1.0") / path.relative_to(source.parent)
                         .relative_to("tinystation").parent / path.name
                         if False else Path("tinystation-1.0/tinystation") / path.name)
        name, _ = userdrivers.install(str(archive), where, name="fromzip")
        failures += not check("installed from zip as", name, "fromzip")

        print("\nlisting")
        rows = dict(userdrivers.installed(where))
        failures += not check("two installed", sorted(rows), ["fromzip", "tinystation"])

        print("\nloading, beside the bundled drivers")
        registry = Registry()
        loaded = userdrivers.load(registry, where)
        failures += not check("user drivers loaded", sorted(loaded),
                              ["fromzip", "tinystation"])
        registry.load()  # the bundled ones too
        names = registry.names()
        failures += not check("tiny is registered", "tiny" in names, True)
        failures += not check("ecowitt is still there", "ecowitt" in names, True)

        print("\ntaking an upload with it")
        live = LiveStore(tmp / "live.sdb", interval_seconds=60)
        ingest = Ingest(live, token="t", registry=registry)
        http = HttpListener(ingest, "127.0.0.1", 0)
        http.start()
        try:
            import urllib.request
            request = urllib.request.Request(
                f"http://127.0.0.1:{http.port}/t/tiny/", data=b"t=21.4;h=55;p=1013")
            with urllib.request.urlopen(request, timeout=5) as response:
                answer = response.read().decode().strip()
            failures += not check("the driver's own reply", answer, "thanks")
            failures += not check("one packet stored", live.count(), 1)
            packet = next(live.packets(0, time.time() + 10))
            failures += not check("field names mapped", sorted(packet.data),
                                  ["barometer", "outHumidity", "outTemp"])
            failures += not check("source is the driver's", packet.source, "tiny")
        finally:
            http.stop()
            live.close()

        print("\nremoving")
        failures += not check("removed", userdrivers.remove("fromzip", where), True)
        failures += not check("gone", (where / "fromzip").exists(), False)
        failures += not check("removing again", userdrivers.remove("fromzip", where),
                              False)

        print("\na driver cannot reach the databases")
        # A driver gets a state -- get, set, delete on strings -- and not the
        # archive store. Writing records and altering the schema are the core's
        # to do; handing a driver the means would make that our bug to explain.
        from weewx_evo.db.archive import ArchiveStore
        from weewx_evo.ingest import state as state_module

        archive = ArchiveStore(tmp / "archive.sdb")
        given = state_module.for_driver("test", archive)
        failures += not check("state is the archive's metadata",
                              type(given).__name__, "ArchiveState")
        failures += not check("its whole surface",
                              sorted(m for m in dir(given) if not m.startswith("_")),
                              ["delete", "get", "set"])
        for forbidden in ("add_record", "conn", "rebuild_day", "add_column", "schema"):
            failures += not check(f"no {forbidden}", hasattr(given, forbidden), False)
        given.set("test_key", "kept")
        failures += not check("it does persist", archive.get_meta("test_key"), "kept")
        archive.close()

        print("\na zip that writes outside its directory is refused")
        evil = tmp / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../../escaped.py", "print('hello')")
        try:
            userdrivers.install(str(evil), where)
            failures += not check("path traversal", "allowed", "refused")
        except userdrivers.InstallError as exc:
            failures += not check("path traversal refused",
                                  "outside" in str(exc) or "no driver" in str(exc), True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

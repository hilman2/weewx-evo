"""Check where a value comes from, and that everything asks the same thing.

Five places a setting can be, one stated order, one resolver. The order is
easy to state and easy to get subtly wrong, which is why it is pinned here
rather than described in a comment.

The part worth testing hardest is the one that looks like a detail: an
argument that was not given must not beat the configuration file. Get that
wrong and the admin page appears to do nothing, with no error anywhere.

    python tools/settings_test.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import options as option_defs  # noqa: E402
from weewx_evo.settings import Settings  # noqa: E402


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


CORE = option_defs.Schema(name="core", label="core",
                          groups=tuple(option_defs.core_options()))


def args_with(**kwargs) -> argparse.Namespace:
    """A namespace where everything not named is None, as argparse leaves it."""
    blank = {name.replace(".", "_"): None for _g, o in CORE for name in [o.name]}
    blank.update({"archive": None, "live": None, "retention_days": None,
                  "raw_minutes": None})
    blank.update(kwargs)
    return argparse.Namespace(**blank)


def main() -> int:
    failures = 0
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-settings-"))
    saved_env = dict(os.environ)
    try:
        path = tmp / "evo.toml"
        path.write_text(
            'station.name = "From the file"\n'
            'interval = "5m"\n'
            'port = 8100\n',
            encoding="utf-8")

        print("the order, strongest first")
        from weewx_evo import config as config_file

        config = config_file.read(path)

        base = Settings(CORE, config=config, args=args_with(), path=path)
        failures += not check("the file beats the default",
                              base.get("interval"), 300)
        failures += not check("and says so", base.source("interval"),
                              "the configuration file")
        failures += not check("what the file omits is the default",
                              base.get("grace"), 15)
        failures += not check("and says that too", base.source("grace"), "default")

        os.environ["WEEWX_EVO_INTERVAL"] = "10m"
        env = Settings(CORE, config=config, args=args_with(), path=path)
        failures += not check("the environment beats the file",
                              env.get("interval"), 600)
        failures += not check("and says so", env.source("interval"),
                              "$WEEWX_EVO_INTERVAL")

        cli = Settings(CORE, config=config, args=args_with(interval="1m"), path=path)
        failures += not check("the command line beats both", cli.get("interval"), 60)
        failures += not check("and says so", cli.source("interval"), "command line")

        print("\nan argument that was not given changes nothing")
        # The one that matters. If argparse's default reached here, the file
        # would never win and the admin page would appear to do nothing.
        quiet = Settings(CORE, config=config, args=args_with(), path=path)
        failures += not check("the file still wins", quiet.get("port"), 8100)

        del os.environ["WEEWX_EVO_INTERVAL"]

        print("\nolder environment names still work")
        os.environ["WEEWX_EVO_RETENTION_DAYS"] = "3"
        old = Settings(CORE, config=config, args=args_with(), path=path)
        failures += not check("days become seconds", old.get("retention"), 259200)
        os.environ["WEEWX_EVO_RETENTION"] = "86400"
        both = Settings(CORE, config=config, args=args_with(), path=path)
        failures += not check("and the current name wins", both.get("retention"),
                              86400)
        del os.environ["WEEWX_EVO_RETENTION_DAYS"]
        del os.environ["WEEWX_EVO_RETENTION"]

        print("\nweewx.conf fills what nothing else set")
        shared = Settings(CORE, config={}, args=args_with(),
                          weewx={"station.altitude": 440.0, "interval": 60},
                          path=path)
        failures += not check("altitude from there", shared.get("station.altitude"),
                              440.0)
        failures += not check("and it says which", shared.source("station.altitude"),
                              "weewx.conf")
        over = Settings(CORE, config=config, args=args_with(),
                        weewx={"interval": 60}, path=path)
        failures += not check("but the file still wins over it",
                              over.get("interval"), 300)

        print("\na bad value falls back rather than crashing")
        broken = Settings(CORE, config={"station": {"latitude": "not a number"}},
                          args=args_with(), path=path)
        failures += not check("the default is used",
                              broken.get("station.latitude"), None)

        print("\na driver sees only its own corner")
        driver_schema = option_defs.Schema(
            name="d", label="d",
            groups=(option_defs.Group("x", options=(
                option_defs.Option("passkey", "Passkey", kind="secret"),
            ), prefix="drivers.ecowitt"),))
        whole = Settings(CORE, config={
            "token": "the-upload-token",
            "drivers": {"ecowitt": {"passkey": "ABC123"}},
        }, args=args_with(), path=path)
        corner = whole.view("drivers.ecowitt", driver_schema)
        failures += not check("it reads its own setting",
                              corner.get("passkey"), "ABC123")
        failures += not check("the upload token is not in its schema",
                              corner.schema.option("token"), None)
        failures += not check("so asking for it gets nothing",
                              corner.get("token"), None)

        print("\nreloading picks up a change")
        live = Settings(CORE, config=config_file.read(path), args=args_with(),
                        path=path)
        failures += not check("before", live.get("port"), 8100)
        failures += not check("nothing changed yet", live.reload(), False)
        path.write_text('station.name = "From the file"\nport = 8200\n',
                        encoding="utf-8")
        failures += not check("something changed", live.reload(), True)
        failures += not check("and the new value is there", live.get("port"), 8200)
        failures += not check("what the file dropped went back to its default",
                              live.get("interval"), 300)
        print("\na changed setting either applies or restarts")
        # Not folklore, and not a list anybody maintains: the schema says
        # which options a running process cannot apply, and the loop asks
        # it. An option added tomorrow is covered by the same answer.
        watched = tmp / "watched.toml"
        watched.write_text('station.name = "A"\n'
                           + 'port = 8000\n', encoding="utf-8")
        live = Settings(CORE, config=config_file.read(watched),
                        args=args_with(), path=watched)

        watched.write_text('station.name = "B"\n'
                           + 'port = 8000\n', encoding="utf-8")
        live.reload()
        failures += not check("a name is applied where it stands",
                              live.needs_restart(), [])
        failures += not check("and it did change", live.get("station.name"),
                              "B")

        watched.write_text('station.name = "B"\n'
                           + 'port = 9000\n', encoding="utf-8")
        live.reload()
        failures += not check("a bound port asks for a restart, by name",
                              live.needs_restart(), ["Port"])

        live.reload()
        failures += not check("and nothing new means nothing to do",
                              live.needs_restart(), [])
        print("\nevery setting the page can write, the process can read")
        # These are two different lists and they drifted apart once. The
        # settings page grew a page of its own for the web server; the
        # resolver kept building from the first list only, and the server
        # started with no host to bind to and would not come up.
        from weewx_evo.cli import all_schemas, settings_for

        resolver = settings_for(args_with())
        unreadable = []
        for schema in all_schemas():
            if schema.kind != "core":
                continue
            for _group, option in schema:
                if option.default is None:
                    continue
                if resolver.get(option.name) is None:
                    unreadable.append(option.name)
        failures += not check("nothing the core declares is unreadable",
                              unreadable, [])

        print("\na driver gets its options in the shape it declared them")
        # A driver declares kind="duration" and the file holds "4h". Handed
        # the string, `int("4h")` raises at startup, the exception is caught,
        # and the driver runs on its default. Nothing in a log reads as a
        # wrong setting, and the option silently does nothing.
        from weewx_evo.ingest import drivers as driver_registry

        registry = driver_registry.DEFAULT
        registry.load()
        built = registry.configure("ecowitt", {"max_behind": "4h",
                                               "max_ahead": "5m"})
        failures += not check("a duration arrives as seconds",
                              getattr(built, "max_behind", None), 14400)
        failures += not check("and so does the other one",
                              getattr(built, "max_ahead", None), 300)

        # And a value nothing can read must not take the station down with
        # it: the driver falls back to its own default and keeps recording.
        built = registry.configure("ecowitt", {"max_behind": "gestern"})
        failures += not check("an unreadable one falls back",
                              getattr(built, "max_behind", None), 3600)
        failures += not check("rather than leaving no driver at all",
                              built is not None, True)

    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

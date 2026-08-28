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
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from weewx_evo import options as option_defs  # noqa: E402
from weewx_evo.settings import Settings  # noqa: E402


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


CORE = option_defs.Schema(name="core", label="core",
                          groups=tuple(option_defs.core_options()))


#: An export pointed at a feed by the name the operator gave it.
EXPORT_CONFIG = """
feeds.theme.kind = "json"
exports.theme.kind = "local"
exports.theme.source = "theme"
exports.theme.directory = "WHERE"
"""

#: Two feeds the operator named. Neither name is a kind, which is the whole
#: point: a list that reads the kinds back cannot offer either of them.
TINY_CONFIG = """
feeds.theme.kind = "cheetah"
feeds.theme.skin = "Seasons"
feeds.metric.kind = "json"
"""


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


        print("\nand the page says so, rather than saving into the void")
        # The rest of this file proves the order is right. This proves the
        # operator is told: the page writes the file, the environment beats
        # the file, so without a word on the field a save changes nothing
        # and looks like it worked. `deploy/compose.yml` shipped
        # WEEWX_EVO_INTERVAL with a default of 300 for exactly this reason,
        # which made the archive interval unsettable on the page.
        from weewx_evo.admin import field, overridden

        interval = next(o for g in CORE.groups for o in g.options
                        if o.name == "interval")
        port = next(o for g in CORE.groups for o in g.options
                    if o.name == "port")
        failures += not check("the field knows what beats it",
                              overridden(interval), "WEEWX_EVO_INTERVAL")
        failures += not check("and a field nothing beats says nothing",
                              overridden(port), "")
        failures += not check("the page shows it on the field",
                              "WEEWX_EVO_INTERVAL" in field(interval, 300), True)

        del os.environ["WEEWX_EVO_INTERVAL"]
        failures += not check("and stops once it is unset",
                              overridden(interval), "")

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
                            'port = 8000\n', encoding="utf-8")
        live = Settings(CORE, config=config_file.read(watched),
                        args=args_with(), path=watched)

        watched.write_text('station.name = "B"\n'
                            'port = 8000\n', encoding="utf-8")
        live.reload()
        failures += not check("a name is applied where it stands",
                              live.needs_restart(), [])
        failures += not check("and it did change", live.get("station.name"),
                              "B")

        watched.write_text('station.name = "B"\n'
                            'port = 9000\n', encoding="utf-8")
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

        print("\na dropdown reads the running settings, not the file again")
        # The path arrives in the environment in a container, so nothing
        # sets it on the command line. A list built by re-reading the file
        # from a CLI argument came back empty there, and an export aimed
        # at a feed the operator had configured was refused at startup as
        # one that did not exist. Nothing said so anywhere.
        named = tmp / "named.toml"
        named.write_text(TINY_CONFIG, encoding="utf-8")
        os.environ["WEEWX_EVO_CONFIG"] = str(named)

        import weewx_evo.cli as cli
        from weewx_evo import settings as settings_state

        settings_state.forget_running()
        option_defs.building_for(None)
        # As `serve` does it: argparse takes the path from the environment,
        # so the namespace carries it and nothing was typed.
        running = cli.settings_for(args_with(config=named))
        failures += not check("the file was found at all",
                              ((running.config.get("feeds") or {})
                               .get("theme") or {}).get("skin"), "Seasons")
        offered = [name for name, _label in option_defs.defined_feeds()]
        failures += not check("and both feeds can be pointed at",
                              offered, ["metric", "theme"])
        settings_state.forget_running()
        print("\nand the same is true of the real entry point")
        # This has to be a subprocess, and it has to be `python -m
        # weewx_evo.cli`. That is how the container starts, and it is the
        # only way the fault appears: cli.py then runs as `__main__`, so
        # a later `from .cli import ...` loads the file a second time
        # under its package name and reads that copy's empty globals.
        # Importing cli and calling into it, as the checks above do,
        # loads it once and cannot see this at all.
        export_config = tmp / "export.toml"
        export_config.write_text(
            EXPORT_CONFIG.replace("WHERE", (tmp / "out").as_posix()),
            encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "weewx_evo.cli", "export", "check",
             "theme"],
            capture_output=True, text=True, check=False,
            env={**os.environ,
                 "WEEWX_EVO_CONFIG": str(export_config),
                 "PYTHONPATH": str(SRC)})
        said = result.stdout + result.stderr
        failures += not check("the export was built",
                              "must be one of" not in said, True)
        failures += not check("and it named its own directory",
                              str(tmp / "out") in said, True)

        print("\na setting that holds a whole block survives a rewrite")
        # A skin's [Extras] is a table of whatever its author invented. The
        # schema calls it a list, because that is how the form offers it --
        # one `name = value` per line -- and in the file it may be a table.
        # Both have to come back unchanged.
        #
        # Two things went wrong here at once, and the second hid the first:
        # the value went through Option.parse and came out as
        # ["{'base_path': '/wdc/'}"] -- a Python dict repr inside a string
        # inside a list -- and the leftovers pass wrote every key under it a
        # second time. Two copies of one dotted path is a file tomllib
        # refuses, so the admin page could not save at all.
        nested = tmp / "nested.toml"
        nested.write_text(
            'archive_db = "x.sdb"\n'
            'token = "t"\n'
            'feeds.wdc.kind = "cheetah"\n'
            'feeds.wdc.extras.base_path = "/wdc/"\n'
            'feeds.wdc.extras.deeper.still = 3\n',
            encoding="utf-8")

        from weewx_evo.cli import all_schemas

        before = config_file.read(nested)
        schemas = all_schemas(nested)
        rendered = config_file.render(before, schemas)

        # The check that would have caught it: valid TOML at all.
        try:
            tomllib.loads(rendered)
            failures += not check("what is written parses", True, True)
        except Exception as exc:
            failures += not check(f"what is written parses ({exc})",
                                  False, True)

        # Once, not twice.
        failures += not check(
            "the block is written once",
            rendered.count("feeds.wdc.extras.base_path"), 1)
        failures += not check(
            "and not as a mangled list",
            "[\"{'" in rendered, False)

        # And it comes back the same.
        config_file.write(nested, before, schemas, backup=False)
        after = config_file.read(nested)
        failures += not check("the block came back",
                              config_file.get(after, "feeds.wdc.extras"),
                              {"base_path": "/wdc/", "deeper": {"still": 3}})
        failures += not check("with the rest of the feed",
                              config_file.get(after, "feeds.wdc.kind"),
                              "cheetah")

        # -- a relative path means the file it was written in ------------
        #
        # Two readers of one setting resolved it two different ways: the
        # settings page against the configuration file, the service against
        # whatever directory it happened to start in. `archive_db =
        # "weewx.sdb"` therefore named two different files, and the page's
        # offer to add a column added it to the one the service was not
        # writing -- while saying it had worked.
        print("\na relative path is relative to the file it is written in")
        elsewhere = tmp / "station"
        elsewhere.mkdir(exist_ok=True)
        (elsewhere / "evo.toml").write_text(
            'token = "abcdefghij123456"\narchive_db = "weewx.sdb"\n',
            encoding="utf-8")
        placed = Settings(CORE, config_file.read(elsewhere / "evo.toml"),
                          args_with(), path=elsewhere / "evo.toml")
        failures += not check("against the file, not the cwd",
                              placed.get("archive_db"),
                              str(elsewhere / "weewx.sdb"))
        # The default is a relative path too, and it is read before parse()
        # ever runs -- so it needs the same treatment or `data/weewx.sdb`
        # still means whatever directory the process was started in.
        failures += not check("and so is the default",
                              Path(placed.get("live_db")).parent.parent,
                              elsewhere)

        # The command line is the exception, and the obvious one: a path
        # somebody just typed means the directory they typed it in.
        typed = Settings(CORE, config_file.read(elsewhere / "evo.toml"),
                         args_with(archive="typed.sdb"),
                         path=elsewhere / "evo.toml")
        failures += not check("but a typed one is left alone",
                              typed.get("archive_db"), "typed.sdb")
        # An absolute path is nobody's business but its own.
        (elsewhere / "abs.toml").write_text(
            'token = "abcdefghij123456"\n'
            f'archive_db = "{(tmp / "far.sdb").as_posix()}"\n',
            encoding="utf-8")
        far = Settings(CORE, config_file.read(elsewhere / "abs.toml"),
                       args_with(), path=elsewhere / "abs.toml")
        failures += not check("and an absolute one untouched",
                              Path(far.get("archive_db")).name, "far.sdb")

    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

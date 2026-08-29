"""The command line.

Three services and a few operations on the databases. Every service can run on
its own or all of them can run in one process, because they talk through the
database and never through each other.

    weewx-evo serve      # listener + archiver, one process
    weewx-evo listen     # the listener alone
    weewx-evo archive    # the archiver alone
    weewx-evo catchup    # build every interval the live table covers
    weewx-evo rebuild    # work a time span out again
    weewx-evo status
    weewx-evo columns    # readings that have nowhere to live
    weewx-evo driver     # list, install and remove third-party drivers
    weewx-evo url        # the live view address, token and all
    weewx-evo config     # show, change, check and import settings
    weewx-evo admin      # the settings page, on its own port
    weewx-evo export     # move what a feed produced somewhere
    weewx-evo upload     # send the readings to a weather service
    weewx-evo forecast   # what somebody who knows says is coming
    weewx-evo web        # serve what a feed produced
    weewx-evo plots      # the charts, and the JSON behind them
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import api as api_module
from . import archives as archives_module
from . import collectors, maintenance, units, watchdog, weewxconf
from . import config as config_file
from . import exports as export_registry
from . import feedrunner as feed_runner
from . import forecast as forecast_registry
from . import notify as notify_registry
from . import options as option_defs
from . import plots as plot_defs
from . import settings as settings_state
from . import stations as stations_module
from . import uploads as upload_registry
from .admin import Admin, AdminServer
from .archiver import Archiver
from .db.archive import ArchiveStore
from .db.live import LiveStore
from .derive import from_settings as deriver_from
from .exports import livepush
from .exports import record as export_record
from .exports import runner as export_runner
from .forecast import Place as ForecastPlace
from .forecast import codes as forecast_codes
from .forecast import runner as forecast_runner
from .forecast.store import ForecastStore
from .ingest import drivers, userdrivers
from .ingest import state as state_module
from .ingest.listener import HttpListener, Ingest, UdpListener
from .netaccess import Access, warn_if_open
from .ratelimit import Limits, announce
from .settings import Settings
from .settings import load as load_settings
from .sources import Policy as SourcePolicy
from .uploads import records as upload_records
from .uploads import runner as upload_runner
from .uploads.progress import Progress
from .webserver import WebServer, site_from

log = logging.getLogger("weewx_evo")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"WEEWX_EVO_{name}", default)


def add_archive_arg(parser: argparse.ArgumentParser) -> None:
    """Which series a single-shot command works on.

    `--series` rather than `--archive`, because `--archive` is already the
    path to a database file. Two meanings for one flag -- a path here, a name
    there -- is the sort of thing that works until somebody has an archive
    called `data`.

    `default=None` like everything else here: argparse cannot tell "not
    given" from "given the default", and naming the default here would beat
    the configuration file the same way an environment variable does.
    """
    parser.add_argument("--series", default=None,
                        help="which measurement series to work on, by name "
                             "from archives.toml. The default one unless "
                             "there is more than one.")


def add_common(parser: argparse.ArgumentParser) -> None:
    # No defaults here, deliberately. argparse cannot tell "not given" from
    # "given the default", and a default set here would beat the
    # configuration file -- which would make the admin page appear to do
    # nothing. Defaults live in the schema; see settings.py for the order.
    parser.add_argument("--live", type=Path, default=None,
                        help="the live packet database")
    parser.add_argument("--archive", type=Path, default=None,
                        help="the WeeWX archive database")
    parser.add_argument("--interval", default=None,
                        help="archive interval, e.g. 5m (default: 5m)")
    parser.add_argument("--table", default=None)
    parser.add_argument("--sources", type=Path, default=(
        Path(env("SOURCES")) if env("SOURCES") else None),
        help="TOML file saying which station wins for which field")
    parser.add_argument("--quality", type=Path, default=(
        Path(env("QUALITY")) if env("QUALITY") else None),
        help="TOML file with the calibration and the limits "
             "(default: quality.toml beside the configuration)")
    parser.add_argument("--weewx-conf", type=Path, default=(
        Path(env("WEEWX_CONF")) if env("WEEWX_CONF") else None),
        help="a weewx.conf to fall back on for the settings both systems "
             "share. Read, never written.")
    parser.add_argument("--driver-dir", type=Path, default=None,
                        help="where third-party drivers live "
                             "(default: beside the archive database)")
    parser.add_argument("--config", type=Path, default=(
        Path(env("CONFIG")) if env("CONFIG") else None),
        help="TOML file with [drivers.<name>] and [sources] sections")


def _add_driver_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--driver-dir", type=Path, default=None,
                        help="where third-party drivers live "
                             "(default: beside the archive database)")
    parser.add_argument("--archive", type=Path,
                        default=Path(env("ARCHIVE", "data/weewx.sdb")),
                        help="used to find the default driver directory")


def add_listen_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--udp-port", type=int, default=None,
                        help="0 disables the UDP listener")
    parser.add_argument("--token", default=None,
                        help="required path segment; without it anyone can write")
    parser.add_argument("--driver", default=None,
                        help="driver for uploads whose path does not name one")
    parser.add_argument("--rate", type=float, default=None,
                        help="requests a second per address (default: 10). A "
                             "console at its fastest sends 0.5. 0 switches it off.")
    parser.add_argument("--behind-proxy", action="store_true", default=None,
                        help="every request then arrives from the proxy, so "
                             "limiting per address would slow down everyone "
                             "except whoever is doing it. Limit in the proxy.")
    parser.add_argument("--allow", default=None,
                        help="which addresses get an answer: 'private' (the "
                             "default), 'any', or a comma-separated list of "
                             "addresses and networks. Bound to everything "
                             "either way; this decides who is answered.")


def add_archive_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--grace", default=None,
                        help="how long to wait after an interval closes")
    parser.add_argument("--poll", type=float, default=None)
    parser.add_argument("--retention-days", type=float, default=None,
                        help="how long to keep packets, in days")
    parser.add_argument("--spool", type=Path, default=None,
                        help="write packets out as gzipped NDJSON before dropping them")
    parser.add_argument("--raw-minutes", type=float, default=None,
                        help="how long to keep the raw uploads for debugging; "
                             "0 does not keep them at all")


def settings_for(args: argparse.Namespace) -> Settings:
    """The process's settings, resolved once.

    Once, not once per caller. With each component resolving for itself, a
    file rewritten between two of them would hand two different
    configurations to one running system, and that is a bug nobody can
    reproduce afterwards.

    Held in `settings.py`, not here. This file is also `__main__`, so its
    globals exist twice as soon as anything imports it by name -- see the
    note there.
    """
    found = settings_state.running()
    if found is not None:
        return found
    resolved = _resolve(args)
    settings_state.set_running(resolved, args)
    return resolved


def _resolve(args: argparse.Namespace) -> Settings:
    """Command line, environment, file, weewx.conf, defaults. See settings.py."""
    # Everything the core declares, not just what the first page shows.
    # These two are separate pages on the settings page and one schema here:
    # splitting the page must not change what the process can read, and it
    # did once -- the web server lost its defaults and would not bind.
    core = option_defs.Schema(
        name="core", label="weewx-evo",
        groups=tuple(option_defs.core_options())
        + tuple(option_defs.website_options()))
    resolved = load_settings(core, getattr(args, "config", None), args,
                             getattr(args, "weewx_conf", None))
    # Two arguments name a unit rather than a setting, so they are folded in
    # here rather than pretending the schema has them.
    days = getattr(args, "retention_days", None)
    if days is not None:
        resolved.config.setdefault("retention", int(days * 86400))
    minutes = getattr(args, "raw_minutes", None)
    if minutes is not None:
        resolved.config.setdefault("raw_retention", int(minutes * 60))
    return resolved


def read_config(path: Path | None) -> dict:
    """The whole configuration file, or an empty one.

    A file that is not there yet is not an error: a first start has nothing to
    read, and the settings page is how it comes into being.
    """
    if path is None:
        return {}
    return config_file.read(path)


def configure_drivers(cfg: Settings, archive: Any = None) -> None:
    """Hand each driver its options, and somewhere to keep its own state.

    Until this runs the drivers are unconfigured instances -- enough to accept
    an upload, not enough to know which console they belong to.

    What a driver gets is a `state`: get, set and delete on strings. Not the
    archive store. A driver has no business writing records or altering the
    schema, and handing it the means would make that our bug to explain. Where
    the state actually lives is the core's decision -- the archive's metadata
    table when there is one, a file when there is not.
    """
    driver_dir = cfg.get("driver_dir")
    if driver_dir:
        os.environ[userdrivers.ENV_VAR] = str(driver_dir)

    section = cfg.config.get("drivers", {})
    # Canonical names only. An alias shares its driver's instance, and
    # configuring it separately would build a second one.
    for name in drivers.DEFAULT.canonical_names():
        # A driver's own corner of the settings, resolved the same way
        # everything else is. It never sees the rest -- not the upload token,
        # not the database paths, not another driver's console list.
        options = dict(section.get(name, {}))
        # The field maps come from the stations, not from the driver's own
        # section. Two consoles both number their channels from one, so the
        # map belongs to the console; it is handed to the driver because only
        # the driver knows what `tf_ch1` means before it is parsed.
        maps = station_field_maps(cfg, name)
        instance = drivers.DEFAULT.get(name)
        if maps and _accepts(instance, "stations"):
            options.setdefault("stations", maps)
        # How to read an upload used to be asked once per protocol, so six
        # protocols were six forms carrying the same three fields -- and on
        # a running installation not one of them was ever filled in. What
        # they describe is either a policy of the whole installation or a
        # property of one console, and neither is a property of a protocol.
        # Offered here to any driver that takes them, the same way `state`
        # and `stations` are.
        for shared in ("infer_unknown", "max_behind", "max_ahead"):
            if not _accepts(instance, shared):
                continue
            if shared in options:
                # Left in the file from when this was asked per protocol. It
                # still works -- deciding otherwise would change how uploads
                # are read without anybody asking -- but it no longer appears
                # on any page, and a setting that is in force and invisible
                # is the worst of the three possible states. So it is said
                # once, at the start, with where the setting lives now.
                log.info("drivers.%s.%s = %r is still in %s and still "
                         "applies. This is asked once now, under %s in the "
                         "settings, or per console on the stations page. "
                         "Delete the line to follow it.",
                         name, shared, options[shared],
                         getattr(cfg, "_path", "the configuration file"),
                         shared)
                continue
            options[shared] = cfg.get(shared)
        factory_only = not options and archive is None
        if factory_only:
            continue
        # Only offer state to a driver that asks for it.
        driver = drivers.DEFAULT.get(name)
        if _accepts(driver, "state"):
            options["state"] = state_module.for_driver(
                name, archive,
                path=None if archive is not None
                else Path(cfg.get("live_db")).parent / f"{name}.state.json")
        if not options:
            continue
        if drivers.DEFAULT.configure(name, options) is not None:
            also = drivers.DEFAULT.aliases_of(name)
            settings = ", ".join(k for k in options if k != "state")
            log.info("driver %r configured (%s)%s", name, settings or "state only",
                     f", also serving {', '.join(also)}" if also else "")

    # A configured collector gets an endpoint under its own name, so its
    # packets arrive as that driver rather than as `json`. That pair --
    # driver and identity -- is what `stations.by_identity` matches on, and
    # without it two collectors would be the same driver and their consoles
    # could not be told apart. Registered from the *configuration*: the
    # collector itself is another process and possibly another machine, and
    # nothing of it is imported here.
    collectors.register_names(drivers.DEFAULT, cfg)

    install_driver_groups()


def station_field_maps(cfg: Settings, driver: str) -> dict:
    """Per-console field maps for one driver, out of `stations.toml`.

    In the shape the driver already takes them -- keyed by a name, each with a
    passkey and its own extensions -- so nothing about the driver changes. All
    that moves is where the answer comes from: a console's own field names sat
    under `[drivers.ecowitt.stations]`, which is a second place to describe a
    console after `stations.toml` was built to be the first.
    """
    # `_path` rather than a public one: Settings keeps the file it was
    # read from and nothing else needed it until now.
    where = getattr(cfg, "_path", None)
    if not where:
        return {}
    try:
        register = stations_module.load(
            stations_module.path_for(Path(where).parent))
    except Exception:
        log.debug("could not read the stations for %r", driver, exc_info=True)
        return {}

    made = {}
    for one in register:
        if one.driver != driver:
            continue
        # A console with nothing of its own said about it needs no entry.
        # With one, the entry carries everything that is true of the box
        # rather than of the protocol -- its field names and its clock.
        settings = {}
        if one.field_map:
            settings["field_map_extensions"] = dict(one.field_map)
        if one.max_behind is not None:
            settings["max_behind"] = one.max_behind
        if one.max_ahead is not None:
            settings["max_ahead"] = one.max_ahead
        if settings:
            made[one.name] = {"passkey": one.identity, **settings}
    return made


def install_driver_groups() -> None:
    """Tell the core what the drivers call their own fields.

    Without this a station's own columns -- `extraTemp9`, `soilEC1`, the
    signal strength of every sensor -- have no unit group, so nothing
    converts them and nothing prints a unit after them. The number is right
    and it is in whatever the console sent, on a page where everything beside
    it is in the units the page asked for.

    Recorded in `units` rather than handed to each renderer. It was handed
    once, and the ten places that never got it were the MQTT document, the
    live document, the realtime files, every upload, the WeeWX compatibility
    layer, and the two commands that render without a listener.
    """
    groups = drivers.DEFAULT.unit_groups()
    units.contribute(groups)
    if groups:
        log.debug("%d field(s) named by the drivers", len(groups))


def _accepts(driver: Any, keyword: str) -> bool:
    """Whether a driver's constructor takes this keyword."""
    import inspect

    if driver is None:
        return False
    try:
        return keyword in inspect.signature(type(driver).__init__).parameters
    except (TypeError, ValueError):
        return False


def stations_path(args: argparse.Namespace, cfg: Settings) -> Path:
    """Where stations.toml lives: beside the configuration, like plots.toml.

    Not beside the database. Both are usually the same directory, but this is
    a file a person edits and diffs, so it belongs with the others of that
    kind -- and the settings page looks for it there.
    """
    if getattr(args, "config", None):
        return stations_module.path_for(Path(args.config).parent)
    return stations_module.path_for(Path(cfg.get("live_db")).parent)


def archives_path(args: argparse.Namespace, cfg: Settings) -> Path:
    """Where archives.toml lives: beside stations.toml, for the same reason."""
    if getattr(args, "config", None):
        base = Path(args.config).parent
    else:
        base = Path(cfg.get("live_db")).parent
    return base / archives_module.FILENAME


def read_archives(args: argparse.Namespace,
                  cfg: Settings) -> archives_module.Register:
    """Every measurement series this installation keeps.

    A missing file is one archive, described by the settings, which is every
    installation that has not asked for a second one. Nothing to migrate: the
    file appears when somebody adds the second, and the page writes the first
    into it at the same moment.
    """
    where = archives_path(args, cfg)
    register = archives_module.Register.load(where, cfg)
    if register.several():
        log.info("%d archive(s) in %s: %s", len(register), where,
                 ", ".join(register.names()))
    # Said at info even for one archive: a container without TZ set runs on
    # UTC, and a station in Germany then gets days that begin at two in the
    # morning. Nothing fails, no reading is wrong, and every daily maximum is
    # for the wrong day -- which is exactly the sort of thing that goes
    # unnoticed for a year.
    for name, said in register.concerns().items():
        log.warning("archive %r: %s", name, said)
    return register


def open_archive(archive: archives_module.Archive, cfg: Settings,
                 base: Path | None = None) -> ArchiveStore:
    """The store for one series.

    Relative paths resolve against the configuration file, the same as every
    other path this program is handed. An archive named in `archives.toml`
    would otherwise land wherever the process happened to be started from.
    """
    where = Path(archive.file)
    if not where.is_absolute() and base is not None:
        where = base / where
    return ArchiveStore(where, table_name=cfg.get("table"))


def build_archivers(args: argparse.Namespace, cfg: Settings, live: LiveStore,
                    archives: archives_module.Register,
                    stations: Any) -> list[tuple[Any, ArchiveStore, Archiver]]:
    """One archiver per series, each with its own place and its own stations.

    The three numbers come off the archive rather than out of the settings,
    which is the whole point of there being archives: sunrise for the north
    field computed with the south field's coordinates is wrong by seconds and
    looks entirely correct.

    With a single archive nothing is filtered. That is not a shortcut -- it is
    what every installation did before stations existed, and an unannounced
    sensor must go on reaching the series it has been reaching for a year.
    """
    base = Path(args.config).parent if getattr(args, "config", None) else None
    sources = read_sources(cfg, args.sources)
    quality = read_quality(args, cfg)
    several = archives.several()
    built = []
    for archive in archives.all():
        store = open_archive(archive, cfg, base)
        mine = None
        if several:
            mine = sorted(one.name for one in stations.for_archive(archive.name))
            if not mine:
                log.warning("archive %r has no stations, so nothing will be "
                            "written to %s", archive.name, archive.file)
        built.append((archive, store, Archiver(
            live, store,
            interval_seconds=cfg.get("interval"),
            loop_hilo=cfg.get("loop_hilo"),
            sources=sources,
            deriver=deriver_from(cfg, archive),
            name=archive.name,
            stations=mine,
            quality=quality)))
    return built


def read_stations(args: argparse.Namespace, cfg: Settings,
                  live: object | None = None) -> tuple:
    """The announced consoles, and where strangers get noted.

    Two halves stored two ways, on purpose. `stations.toml` is decided by a
    person and belongs beside the other files somebody edits and diffs.
    Sightings are observed, change every few seconds and go stale, so they sit
    in the live database next to the readings that produced them.

    A missing file is an installation that has not announced anything yet.
    That is every existing one, and it keeps working: packets go on carrying
    whatever identity their driver read off the hardware.
    """
    from .ingest.sightings import Sightings

    where = stations_path(args, cfg)
    register = stations_module.load(where)
    if len(register):
        log.info("%d station(s) announced in %s: %s", len(register), where,
                 ", ".join(sorted(one.name for one in register)))
    return register, Sightings(live)


def read_quality(args: argparse.Namespace, cfg: Settings) -> Any:
    """The calibration and the limits, from `quality.toml`.

    Its own file rather than a section in the settings, for the reason
    `plots.toml` is one: this is many alike entries with tables inside them,
    and an operator who has worked out what their soil probe does wants to
    diff it and hand it on.

    Absent means no rules, which is what almost every installation runs.
    """
    from . import quality as quality_module

    named = getattr(args, "quality", None) or cfg.get("quality_file")         or "quality.toml"
    path = Path(named)
    if not path.is_absolute():
        # Against the configuration file, like every other relative path that
        # is not typed on the command line.
        base = Path(args.config).parent if getattr(args, "config", None) else Path()
        if not getattr(args, "quality", None):
            path = base / path
    policy = quality_module.load(path)
    if policy:
        log.info("quality: %d limit(s) and %d calibration(s) from %s",
                 len(policy.limits),
                 sum(len(x) for x in policy.calibration.values()), path)
    return policy


def read_sources(cfg: Settings, path: Path | None = None) -> SourcePolicy:
    """Which station wins for which field.

    Normally a [sources] section in the configuration file, beside everything
    else. A separate file is still accepted, because a policy for a dozen
    fields is worth keeping apart from the settings nobody touches.

        [sources]
        outTemp = "garden, roof"     # the garden is the temperature series
        "soil*" = "garden"           # only the garden has probes
        "*"     = "roof, garden"     # everything else: the roof first

    Patterns are checked in file order, so put the specific ones first. An
    empty policy means every packet contributes everything it carries, which
    is what a single station wants and what WeeWX has always done.
    """
    if path is not None:
        section = config_file.read(path).get("sources", {})
        where = str(path)
    else:
        section = cfg.config.get("sources", {})
        where = "the configuration file"
    if not isinstance(section, dict) or not section:
        return SourcePolicy()
    policy = SourcePolicy.from_config({k: str(v) for k, v in section.items()})
    log.info("source policy: %d rule(s) from %s", len(policy.rules), where)
    return policy


def open_stores(args: argparse.Namespace) -> tuple[LiveStore, ArchiveStore]:
    cfg = settings_for(args)
    live = LiveStore(cfg.get("live_db"), interval_seconds=cfg.get("interval"),
                     keep_raw_seconds=cfg.get("raw_retention"))
    archive = ArchiveStore(cfg.get("archive_db"), table_name=cfg.get("table"))
    return live, archive


def make_archiver(args: argparse.Namespace) -> tuple[LiveStore, ArchiveStore, Archiver]:
    """One archiver, for the series `--archive` named or for the default.

    The single-shot commands work on one at a time. Catching up or rebuilding
    every series at once would be the sort of thing somebody runs on a
    Saturday and cannot stop halfway.
    """
    cfg = settings_for(args)
    live = LiveStore(cfg.get("live_db"), interval_seconds=cfg.get("interval"),
                     keep_raw_seconds=cfg.get("raw_retention"))
    announced, _sightings = read_stations(args, cfg, live)
    registry = read_archives(args, cfg)
    live.archives = registry.names()

    wanted = getattr(args, "series", None) or archives_module.DEFAULT
    if wanted not in registry.names():
        print(f"no series called {wanted!r}. There is: "
              f"{', '.join(registry.names())}", file=sys.stderr)
        raise SystemExit(2)
    for archive_def, store, archiver in build_archivers(
            args, cfg, live, registry, announced):
        if archive_def.name == wanted:
            return live, store, archiver
    raise SystemExit(2)  # unreachable: the name was checked above


def start_watchdog(cfg: Any, live: Any,
                   on_unwell: Callable[[str], None], *runners: Any,
                   heartbeat: bool = True) -> Any:
    """The watchdog, where this installation asked for one.

    Built here rather than in each command because all three long-running
    ones want it and they want it identically. The one thing that differs is
    what stopping means: `serve` and `archive` set their loop's event, the
    listener shuts its server down.
    """
    if not cfg.get("watchdog"):
        return None
    dog = watchdog.Watchdog(live, on_unwell,
                            cooldown=cfg.get("watchdog_cooldown"),
                            heartbeat=heartbeat,
                            threads=watchdog.threads_of(*runners))
    dog.start()
    log.info("watchdog watching; it will not restart more than once every "
             "%.0f min", cfg.get("watchdog_cooldown") / 60)
    return dog


def cmd_listen(args: argparse.Namespace) -> int:
    cfg = settings_for(args)
    live = LiveStore(cfg.get("live_db"), interval_seconds=cfg.get("interval"),
                     keep_raw_seconds=cfg.get("raw_retention"))
    # The listener alone does not open the archive, so a driver that keeps
    # state there falls back to its file. Say so rather than let it surprise.
    configure_drivers(cfg, None)
    try:
        access = Access.parse(cfg.get("allow"))
    except ValueError as exc:
        print(f"--allow: {exc}", file=sys.stderr)
        return 1
    warn_if_open(access, "The listener")
    limits = Limits(rate=cfg.get("rate"), behind_proxy=cfg.get("behind_proxy"))
    announce(limits, "The listener")
    announced, sightings = read_stations(args, cfg, live)
    # The listener writes the live table, and every archive reads it. It has
    # to mark all of them pending, so it needs their names even though it
    # opens none of them.
    live.archives = read_archives(args, cfg).names()
    ingest = Ingest(live, token=cfg.get("token"),
                    default_driver=cfg.get("driver"),
                    access=access, limits=limits,
                    stations=announced, sightings=sightings)
    if cfg.get("token") is None:
        log.warning("no token set: anything that can reach this port can write "
                    "to the measurement series")

    http = HttpListener(ingest, cfg.get("host"), cfg.get("port"))
    log.info("HTTP on %s:%s, answering %s, driver %s (available: %s)",
             cfg.get("host"), cfg.get("port"), access, cfg.get("driver"),
             ", ".join(drivers.names()))
    udp = None
    if cfg.get("udp_port"):
        udp = UdpListener(ingest, cfg.get("host"), cfg.get("udp_port"))
        udp.start()
        log.info("UDP on %s:%s", cfg.get("host"), cfg.get("udp_port"))

    # No heartbeat here: this process sits in serve_forever, and the last
    # time it did anything is a fact about the console rather than about
    # itself. The descriptor and thread checks are the ones that apply --
    # and a leaked connection per upload is exactly this process's failure.
    dog = start_watchdog(cfg, live, lambda why: http.stop(), udp,
                         heartbeat=False)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        if dog is not None:
            dog.stop()
        http.stop()
        if udp:
            udp.stop()
        live.close()
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    cfg = settings_for(args)
    live = LiveStore(cfg.get("live_db"), interval_seconds=cfg.get("interval"),
                     keep_raw_seconds=cfg.get("raw_retention"))
    announced, _sightings = read_stations(args, cfg, live)
    registry = read_archives(args, cfg)
    series = build_archivers(args, cfg, live, registry, announced)
    # Every archive is still marked pending, whichever ones this process
    # works: another process is doing the rest, and an interval nobody marked
    # is one nobody builds.
    live.archives = registry.names()

    wanted = getattr(args, "series", None)
    if wanted:
        # One process, one place. This is how two sites in two timezones
        # work: the day boundary comes from the process clock, so each gets
        # its own archiver with its own TZ, both reading this one live table.
        series = [one for one in series if one[0].name == wanted]
        if not series:
            print(f"no series called {wanted!r}. There is: "
                  f"{', '.join(registry.names())}", file=sys.stderr)
            return 2
    stopping = threading.Event()

    def handle(signum: int, frame: object) -> None:
        log.info("signal %s, finishing the current tick", signum)
        stopping.set()

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)

    for archive_def, _store, _archiver in series:
        log.info("archiving every %ds into %s (%s)", cfg.get("interval"),
                 archive_def.file, archive_def.name)

    runner = None
    # The feeds. This process has the archive, so in a split deployment it is
    # the one that can produce anything at all -- the listener never sees the
    # history.
    feeds = start_feeds(args, cfg)

    # An export pointed at a feed has to be told where that feed writes.
    # Without this every one of them is left out at startup with "no feed and
    # no directory set", which reads like the export is wrong when it is not.
    scheduled = build_schedule(args, cfg)
    if scheduled:
        # How each run went, written where the settings page can read it. It
        # is a different process, so "not recorded here" was the only honest
        # answer it had about an FTP export -- true, and no use to anybody
        # asking whether their upload is working.
        runner = export_runner.Runner(
            scheduled,
            note=lambda name, result, error: export_record.write(
                live, name, result, error))
        runner.start()
        if feeds is not None:
            # An export set to run when its feed finishes is waiting for
            # exactly this. Wired here because it is the one place that has
            # both, and neither has to know about the other.
            feeds.on_produced = runner.feed_produced

    # The uploads. Their own threads, for the same reason as the exports: a
    # weather service that has stopped answering must sit in its own timeout
    # rather than in the archiver's tick.
    uploader = None
    scheduled_uploads = build_upload_schedule(args, cfg)
    if scheduled_uploads:
        uploader = upload_runner.Runner(scheduled_uploads)
        uploader.start()

    forecaster = forecast_store = None
    if configured_forecasts(args):
        forecast_store = ForecastStore(forecast_db(args, cfg))
        scheduled_forecasts = build_forecast_schedule(
            args, cfg, forecast_store, uploader)
        if scheduled_forecasts:
            forecaster = forecast_runner.Runner(scheduled_forecasts,
                                                forecast_store)
            forecaster.start()

    dog = start_watchdog(cfg, live, lambda why: stopping.set(),
                         feeds, runner, uploader, forecaster)
    last_prune = 0.0
    try:
        while not stopping.is_set():
            try:
                if dog is not None:
                    # Said here rather than at the top of the loop: this is
                    # past the settings reload, so a config that takes a
                    # while to read cannot look like a stopped loop.
                    dog.beats()

                for archive_def, _store, archiver in series:
                    n = archiver.process_due(grace=cfg.get("grace"))
                    if not n:
                        continue
                    log.info("archived %d interval(s) into %s", n,
                             archive_def.name)
                    if feeds is not None:
                        # Sets a flag and returns, like the exports. The work
                        # happens elsewhere.
                        feeds.record_written(archive_def.name)
                    if runner is not None:
                        # Sets a flag and returns. Nothing about an upload
                        # happens on this thread.
                        runner.record_written()
                    if uploader is not None:
                        uploader.record_written()
                # The raw uploads go first and far more often: they are a
                # debugging copy with an hour's life, not part of the series.
                forgotten = live.forget_raw(time.time() - cfg.get("raw_retention"))
                if forgotten:
                    log.debug("forgot %d raw upload(s)", forgotten)
                if cfg.get("retention") and time.time() - last_prune > 3600:
                    dropped = live.prune(
                        time.time() - cfg.get("retention"), archive_dir=args.spool)
                    if dropped:
                        log.info("dropped %d packet(s) past retention", dropped)
                    last_prune = time.time()
            except Exception:
                log.exception("archiver tick failed; carrying on")
            stopping.wait(cfg.get("poll"))
    finally:
        if runner is not None:
            runner.stop()
        if uploader is not None:
            uploader.stop()
        if forecaster is not None:
            forecaster.stop()
        if forecast_store is not None:
            forecast_store.close()
        live.close()
        for _archive_def, store, _archiver in series:
            store.close()
    return 0


def cmd_upload_list(args: argparse.Namespace) -> int:
    upload_registry.DEFAULT.load()
    print(f"services available: {', '.join(upload_registry.kinds())}")
    print()

    entries = configured_uploads(args)
    if not entries:
        print("None configured. An upload sends the readings themselves to a")
        print("weather service, which is different from an export -- that")
        print("moves the files a feed produced.")
        print()
        print("  [uploads.wu]")
        print('  kind = "wunderground"')
        print('  station = "IBAYERN123"')
        print('  password = "..."')
        return 0

    print(f"configured ({len(entries)}):")
    for name, settings in sorted(entries.items()):
        kind = settings.get("kind", "?")
        who = (settings.get("station") or settings.get("wid")
               or settings.get("host") or "?")
        trigger = settings.get("trigger", "record")
        when = ("after every record" if trigger == "record"
                else "only when asked" if trigger == "manual"
                else f"every {option_defs.format_duration(settings.get('every', 900))}")
        print(f"  {name:<16} {kind:<14} {who}")
        print(f"  {'':<16} {when}")
    return 0


def cmd_upload_check(args: argparse.Namespace) -> int:
    """Ask each service whether it accepts the account.

    Worth more than the equivalent for an export: these services answer a
    wrong password with HTTP 200 and a word in the body, so a rejected upload
    looks exactly like a working one until somebody goes and looks at the map.
    """
    entries = configured_uploads(args)
    if args.name:
        entries = {k: v for k, v in entries.items() if k == args.name}
        if not entries:
            print(f"No upload called {args.name!r}.", file=sys.stderr)
            return 1
    if not entries:
        print("None configured.")
        return 0

    cfg = settings_for(args)
    problems = 0
    for name, settings in sorted(entries.items()):
        settings = dict(settings)
        if str(settings.get("kind", "")) == "cwop":
            settings.setdefault("latitude", cfg.get("station.latitude"))
            settings.setdefault("longitude", cfg.get("station.longitude"))
        try:
            upload = build_upload(name, settings)
        except ValueError as exc:
            print(f"  {name}: {exc}")
            problems += 1
            continue
        try:
            print(f"  {name}: {upload.check()}")
        except Exception as exc:
            print(f"  {name}: {type(exc).__name__}: {exc}")
            problems += 1
        finally:
            close = getattr(upload, "close", None)
            if close is not None:
                close()
    return 1 if problems else 0


def _archive_counts(archive: Path, start: int, stop: int,
                    every: int) -> dict[int, int]:
    """Records per window, keyed the same way InfluxDB keys them.

    Plain epoch arithmetic, not calendar days: `aggregateWindow` cuts on
    multiples of the width from the epoch, so grouping the archive by local
    midnight here would compare one day with a piece of two.
    """
    import sqlite3

    connection = sqlite3.connect(f"file:{archive}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT dateTime / ? * ?, COUNT(*) FROM archive "
            "WHERE dateTime >= ? AND dateTime < ? GROUP BY 1 ORDER BY 1",
            (every, every, start, stop)).fetchall()
    finally:
        connection.close()
    return {int(when): int(count) for when, count in rows}


def cmd_upload_compare(args: argparse.Namespace) -> int:
    """Count both ends, and say where they differ.

    A second store is a second truth. Trusting that every write landed is how
    the two drift apart, and a drift nobody measured shows up as a Grafana
    chart that disagrees with the station's own page -- with nothing to say
    which of them is right.
    """
    cfg = settings_for(args)
    archive = Path(cfg.get("archive_db") or "")
    if not archive.exists():
        print(f"No archive at {archive}.", file=sys.stderr)
        return 1

    entries = {name: settings for name, settings in configured_uploads(args).items()
               if str(settings.get("kind", "")) == "influx"
               and (not args.name or name == args.name)}
    if not entries:
        print("No InfluxDB upload is configured; there is nothing to compare.",
              file=sys.stderr)
        return 1

    every = int(args.window)
    stop = int(time.time())
    start = stop - int(args.days) * 86400
    here = _archive_counts(archive, start, stop, every)

    problems = 0
    for name, settings in sorted(entries.items()):
        try:
            upload = build_upload(name, dict(settings))
            there = upload.counts(start, stop, every,
                                  token=args.read_token or "")
        except Exception as exc:
            print(f"  {name}: {exc}")
            problems += 1
            continue

        windows = sorted(set(here) | set(there))
        missing = [(w, here.get(w, 0), there.get(w, 0)) for w in windows
                   if here.get(w, 0) != there.get(w, 0)]
        print(f"  {name}: archive {sum(here.values())}, "
              f"InfluxDB {sum(there.values())}")
        if not missing:
            print("    every window agrees")
            continue
        problems += 1
        for when, mine, theirs in missing[:12]:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(when))
            print(f"    {stamp}  archive {mine:5}  InfluxDB {theirs:5}  "
                  f"{theirs - mine:+}")
        if len(missing) > 12:
            print(f"    and {len(missing) - 12} more window(s)")
        print(f"    To fill them: weewx-evo upload run {name} --since "
              f"{time.strftime('%Y-%m-%d', time.localtime(missing[0][0]))}")
    return 1 if problems else 0


def cmd_upload_run(args: argparse.Namespace) -> int:
    """Send now, whatever the trigger says."""
    entries = configured_uploads(args)
    if args.name:
        entries = {k: v for k, v in entries.items() if k == args.name}
        if not entries:
            print(f"No upload called {args.name!r}.", file=sys.stderr)
            return 1
    if not entries:
        print("None configured.")
        return 0

    cfg = settings_for(args)
    scheduled = build_upload_schedule(args, cfg)
    if args.name:
        scheduled = [s for s in scheduled if s.name == args.name]
    if args.again:
        # Forget where each one got to, so the next run sends again. For a
        # service that lost a reading and will take it back.
        for entry in scheduled:
            entry.progress.forget(entry.name)

    problems = 0
    for entry in scheduled:
        entry.run()
        print(f"  {entry.name}: {entry.last_summary}")
        if entry.failures or entry.blocked:
            problems += 1
        close = getattr(entry.upload, "close", None)
        if close is not None:
            close()
    return 1 if problems else 0


def cmd_forecast_list(args: argparse.Namespace) -> int:
    forecast_registry.DEFAULT.load()
    print(f"sources available: {', '.join(forecast_registry.kinds())}")
    print()

    entries = configured_forecasts(args)
    if not entries:
        print("None configured. A forecast is the other half of what people")
        print("look at a weather page for. One source covers almost")
        print("everybody:")
        print()
        print("  [forecast.ahead]")
        print('  kind = "open-meteo"')
        print()
        print("Warnings are a second source, because no service does both")
        print("well -- meteoalarm in Europe, nws in the United States.")
        return 0

    print(f"configured ({len(entries)}):")
    for name, settings in sorted(entries.items()):
        kind = settings.get("kind", "?")
        every = option_defs.format_duration(settings.get("every") or 3600)
        print(f"  {name:<16} {kind:<14} every {every}")
    return 0


def cmd_forecast_check(args: argparse.Namespace) -> int:
    """Fetch once and say what came back.

    This is also how somebody finds a DWD station id or a MeteoAlarm region:
    a source that needs one and has not been given one lists the candidates
    rather than refusing.
    """
    entries = configured_forecasts(args)
    if args.name:
        entries = {k: v for k, v in entries.items() if k == args.name}
        if not entries:
            print(f"No forecast source called {args.name!r}.", file=sys.stderr)
            return 1
    if not entries:
        print("None configured.")
        return 0

    cfg = settings_for(args)
    place = forecast_place(cfg)
    problems = 0
    for name, settings in sorted(entries.items()):
        try:
            source = build_forecast_source(name, dict(settings))
        except ValueError as exc:
            print(f"  {name}: {exc}")
            problems += 1
            continue
        try:
            said = source.check(place)
        except Exception as exc:
            said = f"{type(exc).__name__}: {exc}"
            problems += 1
        first, *rest = said.split("\n")
        print(f"  {name}: {first}")
        for line in rest:
            print(f"    {line}")
    return 1 if problems else 0


def cmd_forecast_run(args: argparse.Namespace) -> int:
    """Fetch now and store, whatever the schedule says."""
    cfg = settings_for(args)
    store = ForecastStore(forecast_db(args, cfg))
    try:
        scheduled = build_forecast_schedule(args, cfg, store)
        if args.name:
            scheduled = [s for s in scheduled if s.name == args.name]
        if not scheduled:
            print("None configured." if not args.name
                  else f"No forecast source called {args.name!r}.")
            return 0 if not args.name else 1
        problems = 0
        for entry in scheduled:
            entry.run()
            print(f"  {entry.name}: {entry.last_summary}")
            if entry.failures or entry.blocked:
                problems += 1
        return 1 if problems else 0
    finally:
        store.close()


def cmd_forecast_show(args: argparse.Namespace) -> int:
    """Print what is stored, which is what a page would draw."""
    cfg = settings_for(args)
    path = forecast_db(args, cfg)
    if not path.exists():
        print("Nothing fetched yet. Run `weewx-evo forecast run`.")
        return 0
    store = ForecastStore(path)
    try:
        target = units.Target(units.system_from(cfg.get("units") or "METRICWX"))
        for source in store.sources():
            run = store.run(source) or {}
            when = time.strftime("%Y-%m-%d %H:%M",
                                 time.localtime(run.get("fetched") or 0))
            print(f"{source} -- fetched {when}"
                  f"{', ' + run['note'] if run.get('note') else ''}")

            for warning in store.warnings(source)[:10]:
                starts = time.strftime("%a %H:%M",
                                       time.localtime(warning.starts))
                print(f"  ! {warning.severity:<9} {warning.event} "
                      f"from {starts}  {warning.area[:40]}")

            for day in store.days(source)[:7]:
                when = time.strftime("%a %d %b", time.localtime(day.dateTime))
                low = _shown(day.tempMin, "outTemp", day.usUnits, target)
                high = _shown(day.tempMax, "outTemp", day.usUnits, target)
                said = forecast_codes.text(day.code)
                print(f"  {when}  {low:>7} .. {high:>7}   {said}")

            if args.hours:
                now = int(time.time())
                for hour in store.hours(source, start=now)[:args.hours]:
                    when = time.strftime("%a %H:%M",
                                         time.localtime(hour.dateTime))
                    temp = _shown(hour.outTemp, "outTemp", hour.usUnits, target)
                    said = forecast_codes.text(hour.code)
                    print(f"    {when}  {temp:>7}   {said}")
            print()
        return 0
    finally:
        store.close()


def _shown(value: float | None, obs: str, system: int, target: Any) -> str:
    """One forecast number in the unit the station publishes in."""
    if value is None:
        return "--"
    converted, unit, _group = target.convert([value], obs, system)
    if not converted or converted[0] is None:
        return "--"
    return units.formatted(converted[0], unit, with_label=True)


def cmd_serve(args: argparse.Namespace) -> int:
    """Listener and archiver in one process, for a small machine.

    They still speak only through the database. Splitting them into two
    services later is a change to the unit files, not to the code.
    """
    cfg = settings_for(args)
    if args.explain:
        print(f"Settings for {args.config or '(no configuration file)'}")
        print()
        # Everything that is not the core: each driver, feed and export the
        # file names. They are named instances, so the core schema cannot
        # list them and only the file knows how many there are.
        others = [schema for schema in all_schemas(
            Path(args.config) if args.config else None)
            if schema.kind != "core"]
        for line in cfg.explain(others):
            print(line)
        return 0

    live = LiveStore(cfg.get("live_db"), interval_seconds=cfg.get("interval"),
                     keep_raw_seconds=cfg.get("raw_retention"))
    announced, sightings = read_stations(args, cfg, live)
    registry = read_archives(args, cfg)
    series = build_archivers(args, cfg, live, registry, announced)
    # Every archive marks its own pending intervals, so the table has to know
    # who is reading it before the first packet lands.
    live.archives = registry.names()
    # The first one is the default, and it is what anything wanting "the
    # archive" without saying which gets: the drivers' state, the status
    # command, a feed that names nothing.
    archive = series[0][1]
    configure_drivers(cfg, archive)
    try:
        access = Access.parse(cfg.get("allow"))
    except ValueError as exc:
        print(f"--allow: {exc}", file=sys.stderr)
        return 1
    warn_if_open(access, "The listener")
    limits = Limits(rate=cfg.get("rate"), behind_proxy=cfg.get("behind_proxy"))
    announce(limits, "The listener")
    ingest = Ingest(live, token=cfg.get("token"),
                    default_driver=cfg.get("driver"),
                    access=access, limits=limits,
                    stations=announced, sightings=sightings)
    if cfg.get("token") is None:
        log.warning("no token set: anything that can reach this port can write "
                    "to the measurement series")

    http = HttpListener(ingest, cfg.get("host"), cfg.get("port"))
    http.start()
    log.info("HTTP on %s:%s, answering %s, driver %s (available: %s)",
             cfg.get("host"), cfg.get("port"), access, cfg.get("driver"),
             ", ".join(drivers.names()))

    # The settings page, if it has been given a token of its own. Silence
    # rather than a default token: a configuration editor that comes up
    # reachable without anyone asking for it is not a thing to ship.
    admin_server = None
    admin_token = cfg.get("admin.token")
    if admin_token and args.config:
        if admin_token == cfg.get("token"):
            log.error("the admin token is the same as the upload token, so the "
                      "settings page is not being started. Anything that can "
                      "send a reading could otherwise change the configuration.")
        else:
            admin_access = Access.parse(cfg.get("admin.allow"))
            warn_if_open(admin_access, "The settings page")
            admin_limits = Limits(rate=cfg.get("admin.rate"),
                                  behind_proxy=cfg.get("behind_proxy"))
            announce(admin_limits, "The settings page")
            admin_server = AdminServer(
                Admin(args.config,
                      lambda: all_schemas(args.config), admin_token,
                      access=admin_access, limits=admin_limits),
                cfg.get("admin.host"), cfg.get("admin.port"))
            admin_server.start()
            log.info("settings page on %s:%s, answering %s",
                     admin_server.host, admin_server.port, admin_access)
    elif admin_token and not args.config:
        log.warning("WEEWX_EVO_ADMIN_TOKEN is set but no --config, so there is "
                    "no file for the settings page to edit.")

    udp = None
    if cfg.get("udp_port"):
        udp = UdpListener(ingest, cfg.get("host"), cfg.get("udp_port"))
        udp.start()
        log.info("UDP on %s:%s", cfg.get("host"), cfg.get("udp_port"))

    for archive_def, _store, archiver in series:
        caught = archiver.catch_up()
        if caught:
            log.info("caught up %d interval(s) from the live table into %s",
                     caught, archive_def.name)

    # The feeds. On their own thread for the same reason the exports are:
    # a hundred charts is most of a second, and a second here is a second the
    # archiver is not archiving. What they produce is a directory of files;
    # who moves it anywhere is an export's business.
    feeds = start_feeds(args, cfg)
    if feeds is not None:
        # Once at startup, so a restart does not leave yesterday's pages
        # up until the next record lands a minute later.
        feeds.record_written()
        # And every reading, for a feed that asked for one. `realtime.txt` is
        # polled every ten seconds by the scripts that read it, so producing
        # it on the archive record made it as old as the interval -- which is
        # the one thing that file is not supposed to be.
        ingest.on_packets = feeds.packet_stored


    # The local web server for whatever the feeds produced. Its own port:
    # the listener answers hardware behind a token and this answers browsers,
    # and one port for two audiences means the stricter rule has to lose.
    # Declared out here because the watchdog is handed to it further down,
    # and an installation with the web server switched off reached that line
    # and stopped `serve` from starting at all.
    web = metrics = None
    if cfg.get("web.enabled"):
        site = site_from(cfg)
        metrics = build_metrics(args, cfg, live=live)
        web = WebServer(site, cfg.get("web.host"), cfg.get("web.port"),
                        access=Access.parse(cfg.get("web.allow")),
                        api=build_api(args, cfg, announced),
                        metrics=metrics)
        web.start()
        log.info("serving %d feed(s) on %s:%s%s", len(site.feeds),
                 web.host, web.port,
                 f", {site.default} at /" if site.default else "")

    # The exports, each in its own thread. Not in this loop: an FTP host that
    # has stopped answering sits in a connect for its timeout, and thirty
    # seconds of that here is thirty seconds the archiver is not archiving.
    runner = None
    # An export pointed at a feed has to be told where that feed writes.
    # Without this every one of them is left out at startup with "no feed and
    # no directory set", which reads like the export is wrong when it is not.
    scheduled = build_schedule(args, cfg)
    if scheduled:
        # How each run went, written where the settings page can read it. It
        # is a different process, so "not recorded here" was the only honest
        # answer it had about an FTP export -- true, and no use to anybody
        # asking whether their upload is working.
        runner = export_runner.Runner(
            scheduled,
            note=lambda name, result, error: export_record.write(
                live, name, result, error))
        runner.start()
        if feeds is not None:
            # An export set to run when its feed finishes is waiting for
            # exactly this. Wired here because it is the one place that has
            # both, and neither has to know about the other.
            feeds.on_produced = runner.feed_produced

    # The uploads, each in its own thread as well. An export moves the files
    # a feed produced; an upload sends the readings to a weather service.
    # Neither knows about the other, and both stay off this loop.
    uploader = None
    scheduled_uploads = build_upload_schedule(args, cfg)
    if scheduled_uploads:
        uploader = upload_runner.Runner(scheduled_uploads)
        uploader.start()

    # The forecast. Its own database and its own threads: a 350 kB MOSMIX
    # file over somebody else's connection has no business on this loop, and
    # a predicted temperature has no business in the archive.
    forecaster = forecast_store = None
    if configured_forecasts(args):
        forecast_store = ForecastStore(forecast_db(args, cfg))
        scheduled_forecasts = build_forecast_schedule(
            args, cfg, forecast_store, uploader)
        if scheduled_forecasts:
            forecaster = forecast_runner.Runner(scheduled_forecasts,
                                                forecast_store)
            forecaster.start()

    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())

    watcher = _Watcher(getattr(args, "config", None))
    # Set when only a fresh process can carry on: a setting that cannot be
    # applied to a running one, or the watchdog finding this one unwell. The
    # supervisor brings it back -- `restart: unless-stopped` in compose,
    # `Restart=always` in a unit file.
    restarting = False

    def restart_for(why: str) -> None:
        nonlocal restarting
        restarting = True
        stopping.set()

    dog = start_watchdog(cfg, live, restart_for,
                         feeds, runner, uploader, forecaster)

    # After the watchdog, because it reads two things only the watchdog
    # knows: whether this process restarted itself, and whether the archiver
    # loop is still going round. Its own thread and its own schedule -- the
    # symptom it exists for is this loop having stopped, and a check that
    # runs when a record is written cannot report that no record was written.
    if metrics is not None:
        # Made before the watchdog because the web server starts first, and
        # given it here: the thread and heartbeat figures are the watchdog's.
        metrics.dog = dog
    notifier = build_notify_runner(args, cfg, live, announced, dog)
    if notifier is not None:
        notifier.start()

    last_prune = 0.0
    try:
        while not stopping.is_set():
            try:
                if watcher.changed() and cfg.reload():
                    hard = cfg.needs_restart()
                    if hard:
                        # Some settings cannot be applied to a running
                        # process: a port already bound, a database already
                        # open. Rather than leaving them to take effect at
                        # some restart nobody remembers to do, this one
                        # restarts itself. Docker and systemd both bring it
                        # back; a station is deaf for a second and correct
                        # afterwards, which is the better of the two.
                        log.info("restarting: %s changed, and %s cannot be "
                                 "applied while running",
                                 ", ".join(hard),
                                 "they" if len(hard) > 1 else "it")
                        restarting = True
                        stopping.set()
                        continue
                    apply_live(args, cfg, web, runner, uploader, forecaster,
                               feeds, notifier)

                if dog is not None:
                    dog.beats()

                for archive_def, _store, archiver in series:
                    n = archiver.process_due(grace=cfg.get("grace"))
                    if not n:
                        continue
                    log.info("archived %d interval(s) into %s", n,
                             archive_def.name)
                    if feeds is not None:
                        # Sets a flag and returns, like the exports below. The
                        # work happens on their own thread. The name goes with
                        # it so a feed reading the north field is not produced
                        # because the south field wrote a record.
                        feeds.record_written(archive_def.name)
                    if runner is not None:
                        # Sets a flag and returns. Nothing about an upload
                        # happens on this thread.
                        runner.record_written()
                # The raw uploads go first and far more often: they are a
                # debugging copy with an hour's life, not part of the series.
                forgotten = live.forget_raw(time.time() - cfg.get("raw_retention"))
                if forgotten:
                    log.debug("forgot %d raw upload(s)", forgotten)
                if cfg.get("retention") and time.time() - last_prune > 3600:
                    dropped = live.prune(
                        time.time() - cfg.get("retention"), archive_dir=args.spool)
                    if dropped:
                        log.info("dropped %d packet(s) past retention", dropped)
                    last_prune = time.time()
            except Exception:
                log.exception("archiver tick failed; carrying on")
            stopping.wait(cfg.get("poll"))
    finally:
        log.info("stopping")
        if dog is not None:
            dog.stop()
        if feeds is not None:
            feeds.stop()
        if runner is not None:
            runner.stop()
        if uploader is not None:
            uploader.stop()
        if notifier is not None:
            notifier.stop()
            notifier.close()
        if forecaster is not None:
            forecaster.stop()
        if forecast_store is not None:
            forecast_store.close()
        if web is not None:
            web.stop()
        http.stop()
        if admin_server:
            admin_server.stop()
        if udp:
            udp.stop()
        live.close()
        for _archive_def, store, _archiver in series:
            store.close()
        if restarting:
            log.info("stopped so a new process can pick up the change."
                     " If nothing brings this back, the supervisor is"
                     " missing.")
    return 0


def cmd_catchup(args: argparse.Namespace) -> int:
    live, archive, archiver = make_archiver(args)
    try:
        n = archiver.catch_up(replace=args.replace)
        print(f"built {n} interval(s)")
    finally:
        live.close()
        archive.close()
    return 0


def _resend_rebuilt(args: argparse.Namespace, start: int) -> list[str]:
    """Wind the uploads that hold a copy back to `start`.

    A rebuild changes the numbers under timestamps an upload has already
    passed, and `Progress.sent` never moves backwards -- so without this the
    copy keeps exactly the figures the rebuild was run to correct, and
    `upload compare` still says both ends agree because it counts points
    rather than reading them.

    The list is the channel, not a call: this is a command and the uploads
    belong to a service that may not be running. Rewound here, sent by
    whoever runs next. Same arrangement as the live table between the
    listener and the archiver.

    Asked of the class, not of an instance. Building one needs credentials
    that may be wrong, and whether a service replaces a point or files a
    second one is a fact about the service.
    """
    cfg = settings_for(args)
    base = Path(getattr(args, "config", None) or ".").parent
    archive = Path(cfg.get("archive_db") or "data/weewx.sdb")
    if not archive.is_absolute():
        archive = base / archive

    progress = Progress(archive.parent / "uploads.json")
    rewound = []
    for name, settings in sorted(configured_uploads(args).items()):
        factory = upload_registry.DEFAULT.factory_for(
            str(settings.get("kind", "")).strip())
        if not getattr(factory, "resend_after_rebuild", False):
            continue
        if progress.rewind(name, int(start)):
            rewound.append(name)
    if rewound:
        progress.save()
    return rewound


def cmd_rebuild(args: argparse.Namespace) -> int:
    live, archive, archiver = make_archiver(args)
    try:
        n = archiver.rebuild(args.start, args.stop)
        print(f"rebuilt {n} interval(s) and their days")
    finally:
        live.close()
        archive.close()

    if not n or getattr(args, "resend", True) is False:
        return 0
    rewound = _resend_rebuilt(args, args.start)
    if rewound:
        print(f"  {', '.join(rewound)}: wound back to the start of the span. "
              f"They hold a copy of these records and would otherwise keep "
              f"the old numbers.")
        print("  Send now with: weewx-evo upload run")
    return 0


def cmd_derive(args: argparse.Namespace) -> int:
    """Fill in derived readings on records that are already in the archive.

    A calculator that arrives late leaves a hole behind it: this station has
    a year of weather and evapotranspiration only since the version that
    could work it out. WeeWX calls the same thing `--calc-missing`.

    The records are walked forward in time, not at random, and that is not
    tidiness. Evapotranspiration needs the hour behind it and the rain rate a
    quarter of one; walking in order fills those windows exactly as they
    filled when the readings were new, so a backfilled value is the value
    that would have been recorded at the time.

    What is *not* re-derived: `rain`. The archive holds the fall for each
    interval, while the deriver makes that by subtracting one running total
    from the one before it. Running it over archive records would take the
    difference between two intervals of rain and call the result rain.
    """
    import time as clock

    from . import derive as derive_module
    from .aggregate import start_of_archive_day

    cfg = settings_for(args)
    live, archive = open_stores(args)
    try:
        deriver = derive_module.from_settings(cfg)
        # A backfill is exactly the case where the hardware is not there to
        # ask, so nothing waits on it.
        deriver.how = {name: ("software" if args.replace else how)
                       for name, how in deriver.how.items()}
        # See the docstring: the archive's `rain` is not a running total.
        # Set rather than removed -- an absent name falls back to
        # `prefer_hardware`, which computes it whenever the record has none,
        # so taking the key out turns the thing on.
        deriver.how["rain"] = "hardware"
        # Clearing a direction because the wind was calm removes a reading
        # that is already recorded. Right, and still a deletion, so it is
        # asked for rather than assumed.
        deriver.calm_wind_null = bool(args.calm)

        known = set(archive.schema.columns)
        start = args.start if args.start is not None else 0
        stop = args.stop if args.stop is not None else int(clock.time())

        cursor = archive.conn.execute(
            f"SELECT * FROM {archive.table_name} "
            f"WHERE dateTime > ? AND dateTime <= ? ORDER BY dateTime",
            (start, stop))
        columns = [one[0] for one in cursor.description]

        touched: dict[str, int] = {}
        days: set[int] = set()
        changed = 0
        for row in cursor.fetchall():
            record = {name: value for name, value in zip(columns, row,
                                                         strict=True)
                      if value is not None}
            before = dict(record)
            deriver.apply(record)

            # Only what the archive can hold, and only what actually moved.
            wanted = {name: value for name, value in record.items()
                      if name in known and before.get(name) != value}
            if not wanted:
                continue
            for name in wanted:
                touched[name] = touched.get(name, 0) + 1
            if not args.dry_run:
                archive.add_record({**before, **wanted}, replace=True,
                                   update_daily=False)
                days.add(start_of_archive_day(int(record["dateTime"])))
            changed += 1

        if not touched:
            print("nothing to fill in.")
            return 0

        for name, count in sorted(touched.items(), key=lambda x: -x[1]):
            print(f"  {name:22} {count}")
        print(f"{changed} record(s)"
              + (" would change" if args.dry_run else " changed"))

        # The day summaries hold maxima, and a maximum does not remember the
        # runner-up: the only honest way to correct a day is to build it
        # again from the records.
        for sod in sorted(days):
            archive.rebuild_day(sod)
        if days:
            print(f"{len(days)} day summary(ies) rebuilt")
    finally:
        live.close()
        archive.close()
    return 0


def _collector_settings(args: argparse.Namespace) -> dict:
    """One collector's settings out of the configuration file.

    `--collector shed` instead of six arguments. The point is not brevity: a
    collector configured in the file has a page on the settings site, and a
    collector configured in a unit file has whatever somebody typed there
    once. An argument that is also given still wins -- that is the ordering
    everything else here follows.
    """
    name = getattr(args, "collector", None)
    if not name:
        return {}
    cfg = settings_for(args)
    found = collectors.settings_for(cfg, name)
    if not found:
        known = ", ".join(collectors.configured(cfg)) or "none"
        raise SystemExit(
            f"no collector named {name!r} in the configuration "
            f"(there is: {known})")
    return found


def _shim_config(args: argparse.Namespace) -> dict:
    """The weewx.conf a WeeWX driver is configured by.

    Its own file, not ours. A WeeWX driver reads its settings out of the
    section named after it, and those settings are the ones that were already
    working -- serial port, station model, sensor map. Copying them into our
    file would mean maintaining a second place for them and getting the
    translation wrong for the drivers nobody here can test.
    """
    from .ingest import weewxshim

    # An argument beats the collector's own setting beats the usual place.
    # Same order as everything else: what somebody just typed wins for this
    # run, and the file is what the settings page writes.
    from_file = _collector_settings(args).get("conf")
    path = args.conf or from_file or "/etc/weewx/weewx.conf"
    if not Path(path).exists():
        raise SystemExit(f"no weewx.conf at {path}. Say where it is with --conf.")
    return weewxshim.read_config(path)


def _shim_options(args: argparse.Namespace) -> dict:
    """What to build the shim with: the collector's settings under arguments.

    Gathered in one place because three commands take them and a collector
    whose `driver_file` reached `check` but not `run` would look configured
    and record nothing.
    """
    one = _collector_settings(args)
    name = getattr(args, "collector", None)

    def pick(argument: str, key: str, default=None):
        given = getattr(args, argument, None)
        return given if given not in (None, "", 0) else one.get(key, default)

    return {
        "module_name": pick("driver", "driver") or None,
        "driver_file": pick("driver_file", "driver_file") or None,
        "source": pick("source", "source") or None,
        "catchup_seconds": int(pick("catchup", "catchup", 0) or 0),
        "batch_seconds": float(pick("batch", "batch", 5.0) or 5.0),
        # The endpoint, and the reason a collector is named at all. Packets
        # arriving at `/<token>/shed/` are recorded as driver `shed`, which
        # is what a station is matched on together with its identity. An
        # ad-hoc run has no name and goes in as an envelope.
        "as_driver": name or "json",
    }


def cmd_weewx_driver_list(args: argparse.Namespace) -> int:
    """What this weewx.conf asks for, and whether it can be built."""
    from .ingest import weewxnames, weewxshim

    if weewxnames.installed():
        import weewx
        version = f"WeeWX {getattr(weewx, '__version__', 'unknown')}"
    else:
        # Not an error any more. What a driver imports is a handful of
        # constants and two exceptions, and `weewxnames` has them -- so the
        # thing to say is which one it will run against, since that decides
        # what a later failure means.
        version = "no WeeWX installed; drivers run against the stand-in"

    config_dict = _shim_config(args)
    print(version)
    station = (config_dict.get("Station") or {}).get("station_type", "?")
    print(f"station_type: {station}")
    try:
        module = args.driver or weewxshim.driver_module_name(config_dict)
    except ValueError as exc:
        print(f"  {exc}", file=sys.stderr)
        return 1
    print(f"driver:       {module}")

    section = config_dict.get(station) or {}
    settings = [k for k in section if k != "driver"]
    if settings:
        print(f"its settings: {', '.join(sorted(settings))}")
    return 0


#: What a driver imports to reach hardware, and what to install for it. The
#: import name and the package name differ for every one of them, which is
#: why this table exists rather than a sentence saying to install it.
_HARDWARE_LIBS = {
    "usb": "pyusb",            # fousb, te923, ws28xx, wmr300
    "serial": "pyserial",      # vantage, ws23xx, ultimeter, ws1, cc3000
    "hid": "hidapi",           # some builds of the HID drivers
    "ftdi": "pylibftdi",
}


def cmd_weewx_driver_check(args: argparse.Namespace) -> int:
    """Build the driver, take a few packets, deliver nothing.

    The question this answers is the one worth asking before a service is
    installed: does this driver, this configuration and this hardware work
    together at all. It writes nothing and needs no listener, so it is also
    what to run when something has stopped arriving.
    """
    from .ingest import weewxshim

    config_dict = _shim_config(args)
    chosen = _shim_options(args)
    try:
        found = weewxshim.probe(config_dict, chosen["module_name"],
                                count=args.count, source=chosen["source"],
                                driver_file=chosen["driver_file"])
    except Exception as exc:
        print(f"the driver could not be run: {exc}", file=sys.stderr)
        # A driver talks to hardware, and the library for that is the one
        # thing no stand-in can supply. Naming the package is the difference
        # between a minute and an afternoon, and the module name is not it:
        # `import usb` is pyusb, and nobody guesses that.
        wanted = getattr(exc, "name", None)
        if isinstance(exc, ModuleNotFoundError) and wanted in _HARDWARE_LIBS:
            print(f"\nThat is the library it uses to reach the hardware. "
                  f"Install it with:\n\n    pip install "
                  f"{_HARDWARE_LIBS[wanted]}\n", file=sys.stderr)
        log.debug("driver probe failed", exc_info=True)
        return 1

    print(f"driver:           {found['driver']}")
    print(f"source name:      {found['source']}")
    print(f"archive interval: {found['archive_interval']}s")
    print(f"callbacks bound:  {found['callbacks']}")
    if found["standing_in"]:
        print(f"running against:  a stand-in for "
              f"{', '.join(found['standing_in'])}")
    if getattr(args, "collector", None):
        print(f"delivers as:      {args.collector}  "
              f"(announce a station with driver = {args.collector!r})")
    # WeeWX asks this as `record_generation`; here it is a fact about the
    # console rather than a choice, because the archiver builds every record
    # anyway and takes the console's where there is one.
    if found.get("logs_its_own"):
        print("keeps its own log: yes -- `catchup` can fill an outage")
    else:
        print("keeps its own log: no -- `catchup` has nothing to fetch")
    print(f"packets:          {found['packets']}")
    print(f"usUnits:          {found['usUnits']}")
    print(f"fields ({len(found['fields'])}): {', '.join(found['fields'])}")
    if found["sample"]:
        print("\nfirst packet, first few fields:")
        for name, value in found["sample"].items():
            print(f"  {name:<20} {value}")
    if not found["packets"]:
        print("\nThe driver built but produced nothing. For hardware that is "
              "usually\nthe wrong port or a console that is asleep.")
        return 1
    return 0


def _mqtt_settings(args: argparse.Namespace, cfg: Settings) -> dict:
    """One collector's settings, from the file and the arguments.

    Named collector first, because that is the one with a page. The
    arguments are for trying a broker out before writing anything down.
    """
    from . import collectors

    found: dict = {}
    name = getattr(args, "collector", None)
    if name:
        configured = collectors.configured(cfg)
        if name not in configured:
            raise SystemExit(
                f"No collector called {name!r} in the configuration.\n"
                f"Configured: {', '.join(sorted(configured)) or '(none)'}")
        found = dict(configured[name])
        if str(found.get("kind", "")) != "mqtt":
            raise SystemExit(
                f"Collector {name!r} is a {found.get('kind')!r}, not an MQTT "
                f"one. `weewx-evo weewx-driver run --collector {name}` is "
                f"probably what was meant.")

    for key in ("host", "port", "topic", "username", "password", "tls",
                "client_id", "unit_system", "bundle"):
        value = getattr(args, key, None)
        if value is not None:
            found[key] = value

    if not found.get("host"):
        raise SystemExit("No broker. --host, or a collector in the "
                         "configuration file.")

    # A named collector delivers under its own name, so the packets can be
    # told from another collector's. See `collectors.py`.
    found["as_driver"] = name or "json"
    found["source"] = found.get("source") or name or "mqtt"
    return found


def _mqtt_subscription(args: argparse.Namespace, cfg: Settings,
                       dry_run: bool = False):
    from .ingest import mqttsub

    settings = _mqtt_settings(args, cfg)
    # The map is a section of its own in the file, because a dozen topic
    # names in a settings form is a textarea and a textarea is not a setting.
    field_map = settings.pop("map", None) or settings.pop("field_map", None)
    settings.pop("kind", None)
    return mqttsub.Subscription(
        field_map=field_map or {},
        listener_host=getattr(args, "host_listener", None) or "127.0.0.1",
        listener_port=(getattr(args, "listener_port", None)
                       or cfg.get("port") or 8000),
        token=cfg.get("token"), dry_run=dry_run,
        **{k: v for k, v in settings.items()
           if k in ("host", "port", "topic", "username", "password", "tls",
                    "client_id", "unit_system", "source", "bundle",
                    "as_driver")})


def cmd_mqtt_check(args: argparse.Namespace) -> int:
    """Subscribe, print what arrives, deliver nothing.

    The command somebody runs first, and the reason it exists: a broker
    publishes topics nobody wrote down, and the map cannot be written until
    they are known. So this prints what it could not place as well as what it
    could -- an unmapped topic is the output, not an error.
    """
    cfg = settings_for(args)
    sub = _mqtt_subscription(args, cfg, dry_run=True)

    print(f"Subscribing to {sub.topic} at {sub.host}:{sub.port} ...")
    try:
        sub.connect()
    except Exception as exc:
        print(f"Could not: {exc}", file=sys.stderr)
        return 1

    until = time.time() + max(1, int(getattr(args, "seconds", 10)))
    try:
        while time.time() < until:
            sub.client.pump(0.5)
            if sub.due():
                sub.flush()
        sub.flush()
    finally:
        sub._drop()

    print(f"\n{sub.messages} message(s), {sub.packets} packet(s) they would "
          f"have made.")
    for packet in sub.sent[:5]:
        readings = ", ".join(f"{k}={v}" for k, v in sorted(packet.data.items()))
        print(f"  {packet.dateTime}  {readings}")
    if sub.unmapped:
        print("\nNothing named these, so they were dropped:")
        for topic, count in sorted(sub.unmapped.items(), key=lambda r: -r[1]):
            print(f"  {topic}  ({count})")
        print("\nName the ones that are readings under [collectors.<name>.map],")
        print("as topic-or-key = archive field. For example:")
        print('  map = { temperature = "outTemp", humidity = "outHumidity" }')
    elif not sub.messages:
        print("\nNothing arrived. The topic filter may not match anything "
              "the broker publishes; try --topic '#'.")
    return 0


def cmd_mqtt_run(args: argparse.Namespace) -> int:
    """Subscribe and deliver, until stopped.

    Its own process, like the WeeWX shim and for the same reason: a broker
    that stops answering, or a reconnect that goes wrong, must not be able to
    stop the archiver.
    """
    import signal

    cfg = settings_for(args)
    if not cfg.get("token"):
        print("No upload token is set, so the listener would refuse every",
              file=sys.stderr)
        print("packet and this would run and deliver nothing.", file=sys.stderr)
        return 1

    sub = _mqtt_subscription(args, cfg, dry_run=getattr(args, "dry_run", False))

    def bye(_signum, _frame):
        sub.stop()

    signal.signal(signal.SIGINT, bye)
    signal.signal(signal.SIGTERM, bye)
    sub.run()

    said = sub.status()
    log.info("mqtt collector stopped: %d message(s), %d packet(s)",
             said["messages"], said["packets"])
    return 0


def cmd_weewx_driver_run(args: argparse.Namespace) -> int:
    """Run the driver and deliver what it produces to the listener.

    This is the long-running form, meant for a service file. It stays in its
    own process on purpose: that is the whole reason a WeeWX driver is safe to
    run here, and putting it inside `serve` would give back exactly what the
    arrangement buys.
    """
    import signal

    from .ingest import weewxshim

    cfg = settings_for(args)
    config_dict = _shim_config(args)
    # From the settings, and deliberately not from a --token argument the way
    # `url` and `listen` take one. Those are typed and over in a second; this
    # is a service that runs for months, and an argument would put the token
    # in /proc/<pid>/cmdline, where `ps` prints it for every user on the
    # machine. WEEWX_EVO_TOKEN in the unit's EnvironmentFile, or the
    # configuration file.
    token = cfg.get("token")
    port = args.port or cfg.get("port") or 8000
    host = args.host or "127.0.0.1"

    if not token:
        print("No upload token is set, so the listener would refuse every",
              file=sys.stderr)
        print("packet and this would run and deliver nothing.", file=sys.stderr)
        print(file=sys.stderr)
        print("  WEEWX_EVO_TOKEN=...  in the environment, or `token` in the",
              file=sys.stderr)
        print("  configuration file. Not an argument: it would show up in ps.",
              file=sys.stderr)
        return 1

    chosen = _shim_options(args)
    shim = weewxshim.Shim(
        config_dict, chosen["module_name"], source=chosen["source"],
        host=host, port=port, token=token,
        batch_seconds=chosen["batch_seconds"],
        catchup_seconds=chosen["catchup_seconds"], dry_run=args.dry_run,
        driver_file=chosen["driver_file"], as_driver=chosen["as_driver"])

    def bye(_signum, _frame):
        # The generator blocks on the hardware, so the flag is read between
        # packets. A console that has gone quiet still needs the second
        # signal, which is the supervisor's job and not ours.
        shim.stop()

    signal.signal(signal.SIGINT, bye)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, bye)

    where = "nowhere (--dry-run)" if args.dry_run else f"{host}:{port}"
    print(f"running {shim.module_name}, delivering to {where}")
    sent = shim.run(limit=args.limit)
    print(f"{sent} packet(s) delivered in {shim.delivered_batches} batch(es)")
    if shim.dropped:
        print(f"{shim.dropped} packet(s) dropped while the listener was "
              f"unreachable", file=sys.stderr)
    return 0


def cmd_columns(args: argparse.Namespace) -> int:
    """Readings that the archive has no column for.

    A reading only survives the archive interval if the table has a column for
    it. The standard schema has 113; Ecowitt hardware can fill four times that.

    Where each one belongs, and whether it is counted or measured, is the
    driver's knowledge -- weewx-ecowitt keeps a catalog of it. So the drivers
    are asked first, and only what no driver claims falls back to the live
    table with REAL assumed.

    Nothing is created without --add. Which column a reading belongs in is a
    decision, and the wrong one mixes two sensors into a column that nothing
    afterwards can separate. For a closer look at what hardware is sending,
    the driver has its own tool: `python -m user.ecowitt`.
    """
    live, archive = open_stores(args)
    try:
        known = set(archive.schema.columns)
        wanted: dict[str, str] = {}
        counts: dict[str, int] = {}

        # What the drivers know they need, with the types they know are right.
        for name in drivers.names():
            driver = drivers.get(name)
            ask = getattr(driver, "missing_columns", None)
            if ask is None:
                continue
            try:
                for field, sql_type in ask(known):
                    wanted[field] = sql_type
            except Exception:
                log.exception("driver %r could not work its columns out", name)

        # And what has actually arrived, which is the authority on what is
        # being lost right now.
        first, last = live.span()
        if first is not None:
            for packet in live.packets(first - 1, last):
                for field in packet.data:
                    counts[field] = counts.get(field, 0) + 1
                    if field not in known:
                        wanted.setdefault(field, "REAL")

        if not wanted:
            print(f"{len(counts)} field(s) arriving. Every reading has a column.")
            return 0

        print(f"{len(wanted)} reading(s) have nowhere to live.")
        print("They show up as current conditions and are gone at the next"
              " archive interval.")
        print()
        for field, sql_type in sorted(wanted.items()):
            seen = f"{counts[field]:>7} packet(s)" if field in counts else "  from driver"
            print(f"  {field:<28} {seen}   {sql_type}")

        if not args.add:
            print()
            print("To keep them:")
            print(f"  weewx-evo columns --add --archive {args.archive}")
            print()
            print("Back the database up first: adding a column rewrites the table.")
            print("Check where each one belongs before you do. A reading in the")
            print("wrong column cannot be separated out again afterwards.")
            return 0

        added = sum(archive.add_column(f, t) for f, t in sorted(wanted.items()))
        print()
        print(f"Added {added} column(s).")
    finally:
        live.close()
        archive.close()
    return 0


def cmd_driver_list(args: argparse.Namespace) -> int:
    where = driver_directory(args)
    from .ingest.plugins import bundled

    print(f"bundled with weewx-evo ({len(bundled())}):")
    for name in bundled():
        print(f"  {name}")

    rows = userdrivers.installed(where)
    print()
    print(f"installed in {where} ({len(rows)}):")
    for name, origin in rows:
        print(f"  {name:<24} {origin}")
    if not rows:
        print("  (none)")

    loaded = drivers.names()
    print()
    print(f"registered and ready: {', '.join(loaded)}")
    return 0


def cmd_driver_install(args: argparse.Namespace) -> int:
    where = driver_directory(args)
    try:
        name, notable = userdrivers.install(args.source, where, name=args.name,
                                            force=args.force)
    except userdrivers.InstallError as exc:
        print(f"Not installed: {exc}", file=sys.stderr)
        return 1
    print(f"Installed {name!r} into {where}.")

    if notable:
        print()
        print("What this driver's code reaches for:")
        for note, files in sorted(notable.items()):
            print(f"  {note}")
            print(f"      {', '.join(files[:4])}"
                  + (f" and {len(files) - 4} more" if len(files) > 4 else ""))
        print()
        print("None of that is forbidden and a driver may well need it. It is here")
        print("because a driver runs inside this process: the interface it is given")
        print("keeps it away from the archive, but nothing stops code going around")
        print("an interface. Read it before you point hardware at it.")
        print()
        print("If you would rather not have to: run `weewx-evo listen` and")
        print("`weewx-evo archive` as separate services under different users. The")
        print("listener never opens the archive, so a driver in it cannot write")
        print("there whatever it tries.")

    print()
    print(f"To use it, put it in the path a console uploads to (/<token>/{name}/)")
    print(f"or set it as the default with --driver {name}.")
    return 0


def cmd_driver_remove(args: argparse.Namespace) -> int:
    where = driver_directory(args)
    if not userdrivers.remove(args.name, where):
        print(f"{args.name!r} is not installed in {where}.", file=sys.stderr)
        return 1
    print(f"Removed {args.name!r} from {where}.")
    return 0


def local_addresses() -> list[tuple[str, str]]:
    """Addresses this machine can be reached on, as (address, what it is).

    Only what can be worked out without asking anything: the loopback, and
    whatever address the routing table would use to leave the machine. That
    second one is found by opening a UDP socket towards a public address --
    no packet is sent and nothing has to be reachable, the kernel just says
    which interface it would use.
    """
    import socket

    found = [("127.0.0.1", "loopback")]
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))   # TEST-NET-1, routable to nowhere
        address = probe.getsockname()[0]
        if address and address != "127.0.0.1":
            found.insert(0, (address, "this machine"))
    except OSError:
        pass
    finally:
        probe.close()

    try:
        name = socket.gethostname()
        if name and name not in {a for a, _ in found}:
            found.append((name, "hostname"))
    except OSError:
        pass
    return found


def cmd_url(args: argparse.Namespace) -> int:
    """Print the addresses of the live view and the upload endpoint.

    The token is a path segment, so an address without it is useless and an
    address with it is the whole key. That is the point of this command: the
    two are always needed together, and typing a 48-character token by hand is
    how it ends up in a chat log.
    """
    cfg = settings_for(args)
    token = args.token or cfg.get("token")
    if not token:
        print("No token is set, so the listener accepts uploads from anyone who",
              file=sys.stderr)
        print("can reach it and there is nothing to put in a path.", file=sys.stderr)
        print("Set one with --token or WEEWX_EVO_TOKEN.", file=sys.stderr)
        return 1

    port = args.port or cfg.get("port")
    public = args.public or env("PUBLIC_URL")
    driver = args.driver or cfg.get("driver")

    places: list[tuple[str, str]] = []
    if public:
        places.append((public.rstrip("/"), "public"))
    for address, what in local_addresses():
        host = f"[{address}]" if ":" in address else address
        places.append((f"http://{host}:{port}", what))

    live = [(f"{base}/{token}/live", what) for base, what in places]
    upload = [(f"{base}/{token}/{driver}/", what) for base, what in places]
    width = max(len(url) for url, _ in live + upload)

    for heading, rows in (("Live view", live),
                          ("Where the hardware uploads", upload)):
        print(heading)
        for url, what in rows:
            print(f"  {url:<{width}}  {what}")
        print()

    if not public:
        print("Behind a reverse proxy the outside address is not something this")
        print("can work out. Set WEEWX_EVO_PUBLIC_URL or pass --public.")

    if args.qr:
        _qr(f"{places[0][0]}/{token}/live")
    return 0


def _qr(text: str) -> None:
    """A QR code in the terminal, for typing the address into a phone.

    Hand-rolled rather than a dependency: this is one convenience in one
    command, and a weather station that runs for years should not gain a
    package for it. Falls back to saying so if the encoder is not there.
    """
    try:
        import qrcode
    except ImportError:
        print()
        print("(--qr needs the 'qrcode' package, which weewx-evo does not require)",
              file=sys.stderr)
        return
    code = qrcode.QRCode(border=1)
    code.add_data(text)
    print()
    code.print_ascii(invert=True)


def driver_directory(args: argparse.Namespace) -> Path:
    """Where third-party drivers live, resolved like everything else.

    The command line first, then the setting, then beside the archive. The
    driver commands take no --config of their own, so a bare `weewx-evo
    driver list` still finds them next to the database.
    """
    if getattr(args, "driver_dir", None):
        return Path(args.driver_dir)
    archive = getattr(args, "archive", None)
    if getattr(args, "config", None):
        cfg = settings_for(args)
        configured = cfg.get("driver_dir")
        if configured:
            return Path(configured)
        archive = archive or cfg.get("archive_db")
    return userdrivers.directory(None, archive)


def all_schemas(config_path: Path | None = None) -> list[option_defs.Schema]:
    """Every configurable thing there is: the core, then each driver.

    Drivers are asked, not enumerated. One that gains a setting gains a form
    field and a commented line in the configuration file, and nothing here
    changes.
    """
    if config_path is None:
        args = settings_state.running_args()
        config_path = getattr(args, "config", None) if args else None
    # The dropdowns are built later, from inside the renderer, and by then
    # nothing has told them which file they describe.
    option_defs.building_for(config_path)

    schemas = [option_defs.Schema(
        name="core", label="weewx-evo", kind="core",
        help="The station, the archive, and the port hardware uploads to.",
        groups=tuple(option_defs.core_options()))]

    for name in drivers.DEFAULT.canonical_names():
        driver = drivers.get(name)
        if driver is None:
            continue
        schema = option_defs.schema_of(
            type(driver), name=name, label=f"Driver: {name}", kind="driver")
        if schema is None:
            continue
        # A driver's settings live under its own name, so two drivers with a
        # setting of the same name do not collide.
        schema.groups = tuple(
            replace_group(group, f"drivers.{name}") for group in schema.groups)
        schemas.append(schema)

    # The built-in web server. Its own page rather than three fields on the
    # core one: "where does what I made end up" is the question people
    # arrive with.
    schemas.append(option_defs.Schema(
        name="website", label="Website", kind="core",
        help="Where what the exports published can be read.",
        groups=tuple(option_defs.website_options())))

    # One page per configured feed, named by the operator. Two JSON feeds in
    # two unit systems are two entries, not one shared form -- the same
    # arrangement the exports have, and the reason a station can publish two
    # themes at once.
    configured = config_file.read(config_path) if config_path else {}
    if not (configured.get("feeds") or {}):
        # A file that names none gets the two that ship, so the page shows
        # what the station is actually producing rather than nothing.
        configured = dict(configured, feeds=dict(DEFAULT_FEEDS))

    from . import feeds as feed_registry

    for name, settings in sorted((configured.get("feeds") or {}).items()):
        if not isinstance(settings, dict):
            continue
        kind = str(settings.get("kind", "")).strip()
        factory = feed_registry.factory_for(kind)
        if factory is None:
            continue
        # When it runs and which archive it reads, on every feed's page. The
        # same question for all of them, so it is asked in one place rather
        # than left to each feed to remember.
        groups = list(feed_registry.schedule_options())
        groups += list(factory.options()) if hasattr(factory, "options") else []
        # A skin declares its own settings, and they belong on the page of
        # the feed that runs it -- there is no separate skin page, because a
        # skin is only ever configured through the feed it belongs to.
        if hasattr(factory, "skin_options"):
            groups += factory.skin_options(str(settings.get("skin") or ""),
                                           settings.get("skins_dir"))
        schemas.append(option_defs.Schema(
            name=f"feed:{name}", label=f"Feed: {name} ({kind})", kind="feed",
            help=feed_registry.describe(kind),
            groups=tuple(replace_group(group, f"feeds.{name}")
                         for group in groups)))

    # One page per configured export, named by the operator: two FTP exports
    # to two hosts are two entries, not one shared form.
    #
    # The path is a parameter rather than something found in a global. The
    # admin page knows which file it edits, and reading a different one would
    # show pages for exports that are not in it.
    for name, settings in sorted((configured.get("exports") or {}).items()):
        if not isinstance(settings, dict):
            continue
        kind = str(settings.get("kind", "")).strip()
        factory = export_registry.DEFAULT.factory_for(kind)
        if factory is None:
            continue
        schema = option_defs.schema_of(
            factory, name=f"export:{name}",
            label=f"Export: {name} ({kind})", kind="export")
        if schema is None:
            continue
        schema.groups = tuple(
            replace_group(group, f"exports.{name}") for group in schema.groups)
        schemas.append(schema)

    # One page per configured upload. Two Weather Underground accounts -- a
    # main station and a spare -- are two entries, the same as everywhere
    # else here.
    for name, settings in sorted((configured.get("uploads") or {}).items()):
        if not isinstance(settings, dict):
            continue
        kind = str(settings.get("kind", "")).strip()
        factory = upload_registry.DEFAULT.factory_for(kind)
        if factory is None:
            continue
        schema = option_defs.schema_of(
            factory, name=f"upload:{name}",
            label=f"Upload: {name} ({kind})", kind="upload")
        if schema is None:
            continue
        schema.groups = tuple(
            replace_group(group, f"uploads.{name}") for group in schema.groups)
        schemas.append(schema)

    # One page per configured notification channel. Two of them is the
    # arrangement to aim for rather than the exception: a message about the
    # network, sent over the network, is the alert most likely to be the one
    # that does not arrive.
    for name, settings in sorted((configured.get("notify") or {}).items()):
        if not isinstance(settings, dict):
            continue
        kind = str(settings.get("kind", "")).strip()
        factory = notify_registry.DEFAULT.factory_for(kind)
        if factory is None:
            continue
        schema = option_defs.schema_of(
            factory, name=f"notify:{name}",
            label=f"Notify: {name} ({kind})", kind="notify")
        if schema is None:
            continue
        schema.groups = tuple(
            replace_group(group, f"notify.{name}") for group in schema.groups)
        schemas.append(schema)

    # One page per configured collector. A collector is a *process*, not
    # something this one runs -- it is where the hardware is, possibly on
    # another machine -- so its page configures it and does not start it.
    # It is here at all because a collector that lives only in a unit file
    # has no name anywhere, and the name is what a station is matched on.
    for name, settings in sorted(
            collectors.configured(configured).items()):
        kind = str(settings.get("kind", "")).strip()
        if kind not in collectors.KINDS:
            continue
        schemas.append(option_defs.Schema(
            name=f"collector:{name}", label=f"Collector: {name} ({kind})",
            kind="collector", help=collectors.describe(kind),
            groups=tuple(replace_group(group, f"collectors.{name}")
                         for group in collectors.options(kind))))

    # One page per configured forecast source. Two of them is the ordinary
    # arrangement rather than the exception: a model for the numbers and a
    # warning service for the alerts, because no source does both well.
    for name, settings in sorted((configured.get("forecast") or {}).items()):
        if not isinstance(settings, dict):
            continue
        kind = str(settings.get("kind", "")).strip()
        factory = forecast_registry.DEFAULT.factory_for(kind)
        if factory is None:
            continue
        schema = option_defs.schema_of(
            factory, name=f"forecast:{name}",
            label=f"Forecast: {name} ({kind})", kind="forecast")
        if schema is None:
            continue
        schema.groups = tuple(
            replace_group(group, f"forecast.{name}") for group in schema.groups)
        schemas.append(schema)
    return schemas


def replace_group(group: option_defs.Group, prefix: str) -> option_defs.Group:
    from dataclasses import replace as _replace

    return _replace(group, prefix=prefix)


def cmd_config_show(args: argparse.Namespace) -> int:
    """Print the configuration as it stands, commented."""
    current = config_file.read(args.config) if args.config else {}
    schemas = all_schemas()
    if args.defaults:
        for schema in schemas:
            config_file.apply(current, schema,
                              {o.name: o.default for _g, o in schema
                               if o.default is not None})
    print(config_file.render(current, schemas), end="")
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    """Set one value, checked against the schema that owns it."""
    if not args.config:
        print("Say which file with --config.", file=sys.stderr)
        return 1
    current = config_file.read(args.config)
    schemas = all_schemas()

    for schema in schemas:
        for group, option in schema:
            dotted = f"{group.prefix}.{option.name}" if group.prefix else option.name
            if dotted != args.name and option.name != args.name:
                continue
            try:
                value = option.parse(args.value)
            except option_defs.Invalid as exc:
                print(f"{exc}", file=sys.stderr)
                return 1
            config_file.put(current, dotted, value)
            config_file.write(args.config, current, schemas)
            shown = "(set)" if option.kind == "secret" else repr(value)
            print(f"{dotted} = {shown}")
            if option.restart:
                print("This takes effect when the service restarts.")
            return 0

    print(f"No setting called {args.name!r}. 'weewx-evo config show' lists them.",
          file=sys.stderr)
    return 1


def cmd_config_check(args: argparse.Namespace) -> int:
    """Check every value against its schema and say what is wrong."""
    current = config_file.read(args.config) if args.config else {}
    problems = 0
    for schema in all_schemas():
        values = config_file.values_for(current, schema)
        _parsed, errors = schema.parse(values)
        for name, message in errors.items():
            print(f"  {schema.label}: {message}   ({name})")
            problems += 1
    if problems:
        print()
        print(f"{problems} problem(s).")
        return 1
    print("The configuration is valid.")
    return 0


def cmd_config_import(args: argparse.Namespace) -> int:
    """Read a weewx.conf and write what it says into our own file."""
    try:
        conf = weewxconf.read(args.weewx_conf)
    except OSError as exc:
        print(f"Cannot read {args.weewx_conf}: {exc}", file=sys.stderr)
        return 1

    result = weewxconf.convert(conf, driver_names=set(drivers.names()))
    print(weewxconf.report(result, str(args.weewx_conf)))

    if not args.write:
        print()
        print("Nothing was written. Add --write to keep these settings.")
        return 0
    if not args.config:
        print("Say where to write with --config.", file=sys.stderr)
        return 1

    current = config_file.read(args.config)
    for dotted, value in result.values.items():
        if not args.overwrite and config_file.get(current, dotted) is not None:
            print(f"  kept existing {dotted}")
            continue
        config_file.put(current, dotted, value)
    written = config_file.write(args.config, current, all_schemas())
    print()
    print(f"Written to {written}.")
    return 0


def cmd_admin(args: argparse.Namespace) -> int:
    """Serve the settings page.

    Its own port and its own token, deliberately. An upload endpoint can at
    worst put a wrong reading in the record; this can point the archive
    somewhere else entirely. Sharing a token between the two would make the
    weaker one the strength of both.

    Bound to localhost unless told otherwise, for the same reason. Reaching it
    from another machine is what SSH forwarding is for:

        ssh -L 8080:localhost:8080 the-station
    """
    if not args.config:
        print("Say which configuration file with --config.", file=sys.stderr)
        return 1
    cfg = settings_for(args)
    # The eleventh place. Nothing configures a driver here, so without this
    # the field table has no unit group for anything only a driver names --
    # `eventRain`, `maxdailygust`, the lightning count -- and the chooser
    # cannot put the fields that measure the same thing first for exactly
    # the readings somebody came to this page to place.
    install_driver_groups()
    token = getattr(args, "admin_token", None) or cfg.get("admin.token")
    if not token:
        import secrets
        token = secrets.token_urlsafe(24)
        print("No admin token was set, so one was made for this run:")
        print()
        print(f"  WEEWX_EVO_ADMIN_TOKEN={token}")
        print()
        print("Put that in the environment to keep the address stable across")
        print("restarts. It is not the upload token and must not be the same.")
        print()

    if token and token == cfg.get("token"):
        print("The admin token is the same as the upload token. Anything that",
              file=sys.stderr)
        print("can send a reading could then change the configuration.",
              file=sys.stderr)
        return 1

    try:
        # The settings page has its own boundary, not the listener's. It can
        # point the archive at another file; an upload cannot.
        access = Access.parse(args.allow or cfg.get("admin.allow"))
    except ValueError as exc:
        print(f"--allow: {exc}", file=sys.stderr)
        return 1
    warn_if_open(access, "The settings page")

    limits = Limits(
        rate=args.rate if args.rate is not None else cfg.get("admin.rate"),
        behind_proxy=bool(cfg.get("behind_proxy")))
    announce(limits, "The settings page")
    admin = Admin(args.config, lambda: all_schemas(args.config), token,
                  read_only=args.read_only, access=access, limits=limits)
    server = AdminServer(admin, args.host or cfg.get("admin.host"),
                         args.port or cfg.get("admin.port"))

    print(f"Settings for {args.config}")
    print()
    for address, what in local_addresses():
        host = f"[{address}]" if ":" in address else address
        print(f"  http://{host}:{server.port}/{token}/    {what}")
    print()
    print(f"Answering {access}.")
    if access.everyone:
        print("That includes the open internet. Only the token is in the way.")
    print()
    print("Ctrl-C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.stop()
    return 0


def configured_exports(args: argparse.Namespace) -> dict[str, dict]:
    """What the configuration file says about exports, by name."""
    cfg = settings_for(args)
    section = cfg.config.get("exports") or {}
    return {name: dict(settings) for name, settings in section.items()
            if isinstance(settings, dict)}


def configured_uploads(args: argparse.Namespace) -> dict[str, dict]:
    """What the configuration file says about uploads, by name."""
    cfg = settings_for(args)
    section = cfg.config.get("uploads") or {}
    return {name: dict(settings) for name, settings in section.items()
            if isinstance(settings, dict)}


def build_upload(name: str, settings: dict) -> object:
    """Make one upload from its settings. Raises with a usable message."""
    kind = str(settings.pop("kind", "")).strip()
    if not kind:
        raise ValueError(f"upload {name!r} does not say what kind it is. "
                         f'Add kind = "wunderground" or one of: '
                         f"{', '.join(upload_registry.kinds())}.")
    factory = upload_registry.DEFAULT.factory_for(kind)
    if factory is None:
        raise ValueError(f"upload {name!r} is of kind {kind!r}, which is not "
                         f"one of: {', '.join(upload_registry.kinds())}")
    schema = option_defs.schema_of(factory, name=kind, label=kind)
    if schema is not None:
        parsed, errors = schema.parse(settings, only_present=True)
        if errors:
            first = next(iter(errors.values()))
            raise ValueError(f"upload {name!r}: {first}")
        settings = parsed
    # Settings *about* an upload rather than *for* it. Both say where its
    # readings come from and are the runner's to act on; no upload takes
    # either, and every one of the eight raises TypeError when handed one.
    #
    # Which means `archive` was on every upload's page and unusable on all
    # of them: filling it in got "unexpected keyword argument 'archive'" and
    # the upload was skipped, said once at warning and never again. Adding
    # `live_source` reproduced it within the hour, which is why this is a
    # list and not an `if`.
    for elsewhere in ("archive", "live_source"):
        settings.pop(elsewhere, None)
    return factory(**settings)


def build_upload_schedule(args: argparse.Namespace, cfg: Settings) -> list:
    """What the uploads are, right now.

    They read the archive themselves rather than being handed a record: the
    components here talk through the database, and it is what makes a restart
    cost nothing and a catch-up possible at all.
    """
    configured = dict(configured_uploads(args))
    configured.update(live_readings_locally(cfg, configured, args))
    if not configured:
        return []
    base = Path(getattr(args, "config", None) or ".").parent
    archive = Path(cfg.get("archive_db") or "data/weewx.sdb")
    if not archive.is_absolute():
        archive = base / archive
    # Beside the archive, not in it. Losing this file costs one repeated
    # post, which every one of these services treats as an overwrite.
    progress = Progress(archive.parent / "uploads.json")
    records = upload_records.source(archive)

    # The live table, for an upload set to publish every packet. Absent in a
    # split deployment where this process has the archive and another has the
    # packets -- those uploads then publish on the archive record instead,
    # which is late rather than nothing.
    live_db = Path(cfg.get("live_db") or "data/live.sdb")
    if not live_db.is_absolute():
        live_db = base / live_db
    packets = upload_records.live_source(live_db) if live_db.exists() else None

    # One reader per series, for an installation with more than one. An
    # upload is a station registered with a weather service, and that station
    # stands in one place.
    registry = read_archives(args, cfg)
    by_archive: dict[str, Any] = {}
    if registry.several():
        for one in registry.all():
            where = Path(one.file)
            if not where.is_absolute():
                where = base / where
            by_archive[one.name] = upload_records.source(where)

    def with_station(name: str, settings: dict) -> object:
        # Two settings that belong to the station rather than to a service,
        # filled in here so nobody types them twice -- and only when the
        # upload did not say its own.
        kind = str(settings.get("kind", ""))
        # The place this upload reports from. Its coordinates go out with
        # every CWOP packet, so a second site sending the first one's
        # position puts a station on the map in the wrong field.
        place = archives_module.placed(cfg, registry.get(
            settings.get("archive"))) if registry.several() else cfg
        if kind == "cwop":
            # The packet is a position report; without one there is nothing
            # to send.
            settings.setdefault("latitude", place.get("station.latitude"))
            settings.setdefault("longitude", place.get("station.longitude"))
        if kind == "mqtt" and not settings.get("station"):
            # What Home Assistant calls the device.
            settings["station"] = place.get("station.name") or ""
        if kind == "webpush":
            # Where the pages are and what the token is: both already known
            # to the export that publishes them. Asking again here is how
            # the two drift apart, and a token that does not match shows up
            # as a page that renders perfectly and never updates.
            from .uploads.webpush import WebPushUpload

            where, token, directories, system = WebPushUpload.from_exports(cfg)
            if not settings.get("unit_system") and system:
                # The units the pages are written in. Without this an upload
                # added by hand for a web host published whatever the station
                # sends -- Fahrenheit from an Ecowitt, into pages in Celsius,
                # with nothing on either side able to notice. The local ones
                # have always had it; this is the same figure, from the same
                # function.
                settings["unit_system"] = system
            if not settings.get("url") and where:
                settings["url"] = where
                settings["_inferred"] = True
            if not settings.get("token") and token:
                settings["token"] = token
            # Local exports publish into directories this machine serves.
            # There is no script there and nothing to post to: the file is
            # written where the server will hand it out.
            if not settings.get("directories") and directories:
                settings["directories"] = directories
                settings["_inferred"] = True
            # Beside the settings, not beside whatever directory this process
            # started in -- the same rule the exports follow. In a container
            # the second reading points inside the image, where the file is
            # written and nobody serves it.
            written = settings.get("directories") or []
            if isinstance(written, str):
                written = [written]
            settings["directories"] = [
                one if Path(one).is_absolute() else str(base / one)
                for one in (str(w).strip() for w in written) if one]
        return build_upload(name, settings)

    # Which consoles belong to which series, so a live upload for one site
    # publishes that site's readings. The live table holds the whole
    # installation; only the archive is per series.
    # Which consoles belong to which series, and which of them is the main
    # one. Both are needed: the first says whose readings this site may
    # publish at all, the second which of them it prefers.
    consoles: dict[str, list[str]] = {}
    main_consoles: dict[str, list[str]] = {}
    register, _sightings = read_stations(args, cfg)
    for one in registry.all():
        mine = list(register.for_archive(one.name))
        if registry.several():
            consoles[one.name] = sorted(station.name for station in mine)
        # The main ones even with a single archive: a station with a shed
        # sensor has the same question, and it is the commoner case.
        main_consoles[one.name] = sorted(
            station.name for station in mine
            if getattr(station, "role", "main") == "main")

    return upload_runner.build(configured, with_station, progress, records,
                               packets, by_archive=by_archive,
                               consoles=consoles,
                               main_consoles=main_consoles)


def live_readings_locally(cfg: Settings,
                          configured: dict[str, dict],
                          args: argparse.Namespace | None = None
                          ) -> dict[str, dict]:
    """The live upload an export has already asked for, with nothing to fill in.

    An export saying "live readings" has said everything there is to say. A
    local one knows the directory; one publishing to a web host knows the
    address, because it was typed into "Address the pages are served at" --
    and the token is derived from the station's own. Making somebody add an
    upload with no settings in it is a step that answers no question, and the
    step they take instead is to add one and leave every field empty, which
    is how a station sending Fahrenheit came to publish Fahrenheit into pages
    written in Celsius.

    **The address is the decision, not the checkbox.** This used to cover
    directories only, on the grounds that posting somewhere goes out over
    somebody else's network and should not start because a switch defaulted
    on. That is right, and the switch is not what starts it: `live_push_url`
    is empty until a person types a domain into it. With one there, the
    intent is on the record.

    Grouped by the units the pages are rendered in, because that is what the
    numbers have to match. A station reporting Fahrenheit and a page showing
    Celsius is the ordinary case here, not an odd one -- and the page has no
    way to tell that 82.8 is not what it was about to print. Two sites in
    different units are two uploads, which costs a second file of a kilobyte.

    One added by hand still wins: this stands aside as soon as there is a
    webpush upload of any kind in the file.
    """
    if any(str(one.get("kind", "")) == "webpush" for one in configured.values()):
        return {}

    section = cfg.config.get("exports") or {}
    # Which series each export publishes, by way of the feed it sends. An
    # export moves a feed's directory, and the feed names the archive it
    # reads -- so that is the site those pages are of, and the site whose
    # consoles their live readings should come from.
    #
    # Without this both sites were handed one document taken from whichever
    # console reported last: a north-field page showing the south field's
    # temperature beside its own archive's, and nothing able to notice.
    per_feed = feed_schedule(args) if args is not None else {}

    def series_of(export: dict) -> str:
        feed = str(export.get("source") or "").strip()
        return str((per_feed.get(feed) or {}).get("archive")
                   or archives_module.DEFAULT)

    grouped: dict[tuple[str, str], list[str]] = {}
    posted: dict[tuple[str, str], str] = {}
    for _name, export in sorted(section.items()):
        if not isinstance(export, dict) or not export.get("live_push", True):
            continue
        system = livepush.rendered_units(cfg, export)
        where_from = (system, series_of(export))
        if export.get("kind") == "local":
            where = str(export.get("directory") or "").strip()
            if where:
                grouped.setdefault(where_from, []).append(where)
            continue
        # Anything else publishes to a host, and only with an address on it.
        address = str(export.get("live_push_url") or "").strip()
        if address:
            posted.setdefault(where_from, livepush.url_for(address))

    if not grouped and not posted:
        return {}

    made: dict[tuple[str, str], dict] = {}
    for key in sorted(set(grouped) | set(posted)):
        system, series = key
        settings: dict = {"kind": "webpush", "unit_system": system,
                          "archive": series, "_inferred": True}
        if grouped.get(key):
            settings["directories"] = grouped[key]
        if posted.get(key):
            settings["url"] = posted[key]
        made[key] = settings
    if len(made) == 1:
        return {"live": next(iter(made.values()))}

    # More than one document, so each is named for what makes it different --
    # and only for that. An installation with one archive and two sets of
    # units keeps the names it had (`live-us`), because the series is not
    # what distinguishes them and putting it in would rename a file nobody
    # asked to be renamed.
    systems = {system for system, _ in made}
    several = len({series for _, series in made}) > 1

    def named(system: str, series: str) -> str:
        if not several:
            return f"live-{system.lower() or 'stored'}"
        if len(systems) == 1:
            return f"live-{series}"
        return f"live-{series}-{system.lower() or 'stored'}"

    return {named(system, series): settings
            for (system, series), settings in made.items()}


def configured_forecasts(args: argparse.Namespace) -> dict[str, dict]:
    """What the configuration file says about forecast sources, by name."""
    cfg = settings_for(args)
    section = cfg.config.get("forecast") or {}
    return {name: dict(settings) for name, settings in section.items()
            if isinstance(settings, dict)}


def forecast_db(args: argparse.Namespace, cfg: Settings) -> Path:
    """Where the forecast is kept. Beside the archive, never in it."""
    base = Path(getattr(args, "config", None) or ".").parent
    archive = Path(cfg.get("archive_db") or "data/weewx.sdb")
    if not archive.is_absolute():
        archive = base / archive
    return archive.parent / "forecast.sdb"


def forecast_place(cfg: Settings) -> ForecastPlace:
    """Where the station is, which is what a forecast is for."""
    return ForecastPlace(
        latitude=float(cfg.get("station.latitude") or 0.0),
        longitude=float(cfg.get("station.longitude") or 0.0),
        altitude=cfg.get("station.altitude"),
        name=str(cfg.get("station.name") or ""))


def build_forecast_source(name: str, settings: dict) -> object:
    """Make one forecast source. Raises with a usable message."""
    kind = str(settings.pop("kind", "")).strip()
    if not kind:
        raise ValueError(f"forecast source {name!r} does not say what kind it "
                         f'is. Add kind = "open-meteo" or one of: '
                         f"{', '.join(forecast_registry.kinds())}.")
    factory = forecast_registry.DEFAULT.factory_for(kind)
    if factory is None:
        raise ValueError(f"forecast source {name!r} is of kind {kind!r}, which "
                         f"is not one of: "
                         f"{', '.join(forecast_registry.kinds())}")
    schema = option_defs.schema_of(factory, name=kind, label=kind)
    if schema is not None:
        parsed, errors = schema.parse(settings, only_present=True)
        if errors:
            first = next(iter(errors.values()))
            raise ValueError(f"forecast source {name!r}: {first}")
        settings = parsed
    return factory(**settings)


def mirror_forecast(uploader: Any, store: Any) -> Callable[[str], None]:
    """A callback that copies a fresh forecast into every InfluxDB upload.

    Only InfluxDB. Every other upload in that package sends readings to a
    weather service that has its own forecast and no interest in ours; this
    one writes to a database the operator runs, and a Grafana panel showing
    the next three days beside the last three is the reason it exists.

    On the forecast thread rather than a new one. That thread is asleep for
    an hour at a time, and a database that stops answering holds up one
    source's next fetch and nothing else.
    """
    def send(name: str) -> None:
        if uploader is None or store is None:
            return
        for scheduled in getattr(uploader, "uploads", []):
            upload = getattr(scheduled, "upload", None)
            if not hasattr(upload, "post_forecast"):
                continue
            try:
                points = upload.post_forecast(store, (name,))
                log.info("forecast %s: %d point(s) to upload %s",
                         name, points, scheduled.name)
            except Exception as exc:
                log.warning("forecast %s could not reach upload %s: %s",
                            name, scheduled.name, exc)
    return send


def build_forecast_schedule(args: argparse.Namespace, cfg: Settings,
                            store: Any, uploader: Any = None) -> list:
    """What the forecast sources are, right now."""
    configured = configured_forecasts(args)
    if not configured:
        return []
    return forecast_runner.build(configured, build_forecast_source,
                                 forecast_place(cfg), store,
                                 mirror_forecast(uploader, store))


def apply_live(args: argparse.Namespace, cfg: Settings, web: Any,
               runner: Any, uploader: Any = None,
               forecaster: Any = None, feeds: Any = None,
               notifier: Any = None) -> None:
    """Apply a changed configuration to a running process.

    Everything that can be rebuilt in place, in one function. Scattering
    these across the loop is how three of them came to be missing: nothing
    listed what had to be nudged, so nothing said when one was forgotten.

    Anything that cannot be rebuilt here belongs marked `restart` in the
    schema, and the loop restarts the process for it.
    """
    if notifier is not None:
        # The fifth. A channel added on the settings page has to start
        # speaking without a restart, and one removed has to stop -- and
        # `replace` rather than three assignments, for the reason written
        # down at `exports/runner.replace`.
        fresh = build_notify_runner(args, cfg, notifier.live,
                                    notifier.stations, notifier.dog)
        names = sorted(one.name for one in (fresh.channels if fresh else []))
        if names != sorted(one.name for one in notifier.channels):
            notifier.replace(fresh.channels if fresh else [])
            log.info("%d notification channel(s) running", len(names))

    if runner is not None:
        fresh = build_schedule(args, cfg)
        if _differs(fresh, runner):
            # An export added on the settings page joins the running set.
            # `replace`, not stop-assign-start: the stop flag, the wake-up
            # events and the thread list belong together, and doing two of
            # the three left every new thread ending the moment it started.
            runner.replace(fresh)
            log.info("%d export(s) running", len(fresh))

    if feeds is not None:
        # The fourth. A feed deleted on the settings page went on being
        # produced and a new one was not produced at all, both silently,
        # until a restart -- which is the failure this function's own
        # docstring warns about, arriving in the one place it had missed.
        charts = load_plots(args, cfg)
        if len(charts):
            made = build_feeds(args, cfg, charts)
            if [n for n, _b, _i in made] != [n for n, _b, _i in feeds.feeds]:
                feeds.replace(made, feed_schedule(args))
                log.info("%d feed(s) producing", len(made))

    if uploader is not None:
        fresh = build_upload_schedule(args, cfg)
        if _uploads_differ(fresh, uploader):
            # An upload added on the settings page joins the running set.
            uploader.replace(fresh)
            log.info("%d upload(s) running", len(fresh))

    if forecaster is not None:
        fresh = build_forecast_schedule(args, cfg, forecaster.store, uploader)
        before = [(s.name, type(s.source).__name__, s.every)
                  for s in forecaster.sources]
        after = [(s.name, type(s.source).__name__, s.every) for s in fresh]
        if before != after:
            forecaster.replace(fresh)
            log.info("%d forecast source(s) running", len(fresh))

    if web is not None and web.site.update(
            served_directories(args, cfg),
            str(cfg.get("web.default") or ""),
            str(cfg.get("station.name") or "")):
        log.info("serving %d feed(s)%s", len(web.site.feeds),
                 f", {web.site.default} at /" if web.site.default
                 else ", listing them at /")

    # The charts are read on every feed run, so nothing is needed for them
    # here. If that ever changes, this is where it goes.


def _uploads_differ(fresh: list, uploader: Any) -> bool:
    """Whether the uploads have actually changed.

    Compared on what would change behaviour rather than on identity: writing
    the file for an unrelated setting must not tear down a connection that is
    working.
    """
    def shape(entries: list) -> list:
        return [(s.name, type(s.upload).__name__, s.trigger, s.every,
                 sorted(s.upload.status().items())) for s in entries]

    return shape(uploader.uploads if uploader is not None else []) != shape(fresh)


def _differs(fresh: list, runner: Any) -> bool:
    """Whether the exports have actually changed.

    Restarting their threads costs nothing much, but doing it on every write
    to the file would interrupt an upload in progress for no reason.
    """
    def shape(one: Any) -> tuple:
        # `extra` is in here because adding a second feed to an export is a
        # change to what it sends, and without it the running one would keep
        # sending only the first until somebody restarted.
        return (one.name, str(one.source), getattr(one.export, "trigger", ""),
                one.feed, one.extra)

    before = [shape(s) for s in (runner.exports if runner is not None else [])]
    return before != [shape(s) for s in fresh]


def build_schedule(args: argparse.Namespace, cfg: Settings) -> list:
    """What the exports are, right now.

    An export pointed at a feed has to be told where that feed writes, or it
    is left out at startup with "no feed and no directory set" -- which reads
    like the export is wrong when it is not.
    """
    where = feed_dirs(cfg, args)
    configured = {name: resolve_paths(args, settings)
                  for name, settings in configured_exports(args).items()}
    # What `live.php`'s token is derived from. The station's upload token is
    # the one persistent secret every installation already has, so there is
    # nothing extra to generate, store or lose -- see `exports.livepush`.
    token = str(cfg.get("token") or "")
    return export_runner.build(
        configured,
        lambda name, settings: build_export(name, settings, token),
        lambda settings: export_registry.source_for(settings, where.get),
        # And where the *other* feeds an export carries write, by name. An
        # export sends a skin and the charts it draws from, and those are two
        # feeds writing two directories.
        feeds=where)


def resolve_paths(args: argparse.Namespace, settings: dict) -> dict:
    """Make an export's own paths absolute, against the configuration file.

    The same rule as plots.toml: a relative path means "beside the settings",
    not "beside whatever directory this process happens to have started in".
    In a container that second reading points inside the image, where a
    published site is served by nobody and kept by nothing.
    """
    base = Path(getattr(args, "config", None) or ".").parent
    out = dict(settings)
    for key in ("directory", "directory_source", "tracker"):
        where = str(out.get(key) or "").strip()
        if where and not Path(where).is_absolute():
            # Only for the kinds where it is a path on this machine. An FTP
            # export's `directory` is on the far side and means nothing here.
            if key != "directory" or out.get("kind") == "local":
                out[key] = str(base / where)
    return out


def build_export(name: str, settings: dict, upload_token: str = "") -> object:
    """Make one export from its settings. Raises with a usable message.

    `upload_token` is what `live.php`'s token is derived from. It belongs to
    the station rather than to any one export, so it is filled in here instead
    of being typed into every export -- and only when the export did not say
    its own.
    """
    kind = str(settings.pop("kind", "")).strip()
    if not kind:
        raise ValueError(f"export {name!r} does not say what kind it is. "
                         f"Add kind = \"ftp\" or kind = \"rsync\".")
    factory = export_registry.DEFAULT.factory_for(kind)
    if factory is None:
        raise ValueError(f"export {name!r} is of kind {kind!r}, which is not "
                         f"one of: {', '.join(export_registry.kinds())}")
    schema = option_defs.schema_of(factory, name=kind, label=kind)
    if schema is not None:
        parsed, errors = schema.parse(settings, only_present=True)
        if errors:
            first = next(iter(errors.values()))
            raise ValueError(f"export {name!r}: {first}")
        settings = parsed
    if upload_token and not settings.get("upload_token"):
        settings["upload_token"] = upload_token
    return factory(**settings)


def cmd_export_list(args: argparse.Namespace) -> int:
    export_registry.DEFAULT.load()
    print(f"kinds available: {', '.join(export_registry.kinds())}")
    print()

    entries = configured_exports(args)
    if not entries:
        print("None configured. An export moves what a feed produced:")
        print()
        print("  [exports.website]")
        print('  kind = "rsync"')
        print('  source = "data/public_html"')
        print('  host = "example.org"')
        print('  user = "weather"')
        print('  directory = "/var/www/weather"')
        return 0

    print(f"configured ({len(entries)}):")
    for name, settings in sorted(entries.items()):
        kind = settings.get("kind", "?")
        where = settings.get("host", "?")
        source = (settings.get("source") or settings.get("directory_source")
                  or "(nothing)")
        trigger = settings.get("trigger", "record")
        when = ("after every record" if trigger == "record"
                else "only when asked" if trigger == "manual"
                else f"every {option_defs.format_duration(settings.get('every', 900))}")
        print(f"  {name:<16} {kind:<7} {source} -> {where}")
        print(f"  {'':<16} {when}")
    return 0


def cmd_export_check(args: argparse.Namespace) -> int:
    """Try each destination without sending anything."""
    entries = configured_exports(args)
    if args.name:
        entries = {k: v for k, v in entries.items() if k == args.name}
        if not entries:
            print(f"No export called {args.name!r}.", file=sys.stderr)
            return 1
    if not entries:
        print("None configured.")
        return 0

    problems = 0
    for name, settings in sorted(entries.items()):
        try:
            export = build_export(name, dict(settings))
        except ValueError as exc:
            print(f"  {name}: {exc}")
            problems += 1
            continue
        try:
            print(f"  {name}: {export.check()}")
        except Exception as exc:
            print(f"  {name}: {exc}")
            problems += 1
    return 1 if problems else 0


def cmd_export_run(args: argparse.Namespace) -> int:
    """Send. This is what a feed would call when it has produced something."""
    entries = configured_exports(args)
    if args.name:
        entries = {k: v for k, v in entries.items() if k == args.name}
        if not entries:
            print(f"No export called {args.name!r}.", file=sys.stderr)
            return 1
    if not entries:
        print("None configured.")
        return 0

    failed = 0
    for name, settings in sorted(entries.items()):
        # A feed, or a directory. The schema cannot say "one of these two",
        # so it is resolved here where both are visible.
        source = args.source or export_registry.source_for(settings)
        if not source:
            print(f"  {name}: no feed and no directory is set. There are no "
                  f"feeds yet, so set a directory.")
            failed += 1
            continue
        try:
            export = build_export(name, dict(settings))
        except ValueError as exc:
            print(f"  {name}: {exc}")
            failed += 1
            continue

        if args.all:
            # Forget what was sent, so everything goes again. For the time
            # somebody changes a template that does not change a timestamp.
            tracker = getattr(export, "_tracker_for", None)
            if tracker is not None:
                tracker(Path(source)).reset()

        try:
            result = export.send(Path(source))
        except Exception as exc:
            print(f"  {name}: {exc}")
            failed += 1
            continue

        print(f"  {name}: {result.summary()}"
              + (f" -- {result.note}" if result.note else ""))
        for path, why in result.failures[:5]:
            print(f"      {path}: {why}")
        if result.failures:
            failed += 1
    return 1 if failed else 0


def cmd_web(args: argparse.Namespace) -> int:
    """Serve the feeds, and nothing else.

    Separate from `serve` for the same reason `listen` is: a machine that only
    shows the pages does not have to be the one recording them.
    """
    cfg = settings_for(args)
    site = site_from(cfg)
    api = build_api(args, cfg)
    # A station with the API switched on and no feed yet has something to
    # serve: the readings themselves. Refusing to start there would mean the
    # one endpoint that needs no files is unreachable until somebody
    # configures a feed that writes some.
    metrics = build_metrics(args, cfg)
    if not site.feeds and api is None and metrics is None:
        print("Nothing to serve. A feed produces files; until one exists, "
              "point this at a directory:")
        print()
        print("  [web.serve]")
        print('  website = "data/public_html"')
        return 1

    try:
        access = Access.parse(args.allow or cfg.get("web.allow"))
    except ValueError as exc:
        print(f"--allow: {exc}", file=sys.stderr)
        return 1

    server = WebServer(site, args.host or cfg.get("web.host"),
                       args.port or cfg.get("web.port"), access=access,
                       api=api, metrics=metrics)
    if api is not None:
        print(f"Answering questions at /api/{api_module.VERSION}/"
              + (" (token required)" if api.token else ""))
    print(f"Serving {len(site.feeds)} feed(s):")
    for name in sorted(site.feeds):
        at = "/" if name == site.default else f"/{name}/"
        print(f"  {at:<20} {site.feeds[name]}")
    print()
    for address, what in local_addresses():
        host = f"[{address}]" if ":" in address else address
        print(f"  http://{host}:{server.port}/    {what}")
    print()
    print(f"Answering {access}. Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.stop()
    return 0


def plots_path(args: argparse.Namespace, cfg: Settings) -> Path:
    """Where plots.toml lives: beside the configuration unless told otherwise."""
    named = getattr(args, "plots", None) or cfg.get("plots_file") or "plots.toml"
    path = Path(named)
    if not path.is_absolute() and getattr(args, "config", None):
        beside = Path(args.config).parent / path
        # Only if it is actually there, so a fresh install still writes the
        # obvious place rather than somewhere under the config directory that
        # nobody looked in.
        if beside.exists() or not path.exists():
            return beside
    return path


def load_plots(args: argparse.Namespace, cfg: Settings) -> plot_defs.PlotSet:
    """The charts, laying the starter set down on a first run.

    A station with no charts has no feed with anything to draw, so the whole
    publishing half of this program sits there doing nothing while every
    page reports success. The starter set is what WeeWX's Seasons skin
    draws, and a chart for a sensor this station does not have is skipped
    when the feeds run.

    Only when the file is absent. A file that exists and is empty is an
    answer somebody gave, and putting a hundred charts back into it would be
    this function arguing with them.
    """
    where = plots_path(args, cfg)
    if not where.exists():
        from . import starter

        said = starter.install_plots(where)
        if said:
            log.info("%s", said)
    return plot_defs.load(where)


#: What a station gets when nothing has been configured. Named the same as
#: their kinds, so an existing file that says `feeds.json.units` keeps
#: meaning what it meant.
#: `deck` rather than `diagnostic`. The diagnostic page draws what is on the
#: disk and is for working out why something is missing; the first thing a
#: new station should have is a website, and being handed a troubleshooting
#: page instead reads as though something is already wrong.
def _default_feeds() -> dict[str, dict]:
    from . import starter

    return {name: dict(one) for name, one in starter.FEEDS.items()}


DEFAULT_FEEDS = _default_feeds()


def configured_feeds(args: argparse.Namespace) -> dict[str, dict]:
    """What the configuration says about feeds, by name.

    A name is one configured feed; `kind` says what it is. Two Cheetah feeds
    rendering two skins are two names of one kind, and each writes its own
    directory -- which is how a station publishes two themes at once.

    A file that names none gets the two that ship, because a station with no
    charts at all is not a useful default.
    """
    cfg = settings_for(args)
    section = cfg.config.get("feeds") or {}
    found = {name: dict(settings) for name, settings in section.items()
             if isinstance(settings, dict) and settings.get("kind")}
    return found or {name: dict(settings)
                     for name, settings in DEFAULT_FEEDS.items()}


def feed_dirs(cfg: Settings,
              args: argparse.Namespace | None = None) -> dict[str, Path]:
    """Where each feed writes, by name.

    One place, because two things need the answer and they must agree: the
    feed runner, which writes there, and an export, which sends what is
    there. Working it out twice is how an export ends up publishing an empty
    directory that nothing ever filled.
    """
    root = Path(cfg.get("feeds_dir") or "data/feeds")
    out: dict[str, Path] = {}
    for name, settings in (configured_feeds(args).items() if args is not None
                           else DEFAULT_FEEDS.items()):
        where = str(settings.get("destination") or "").strip()
        # Its own directory under the root, named after the feed. A feed that
        # wrote into the root would be published together with every other
        # feed by one export -- a second copy of everything.
        out[name] = root / (where or name)
    return out


def feed_schedule(args: argparse.Namespace) -> dict:
    """When each configured feed runs, and which archive it reads.

    Read here rather than asked of the feed class, because it is the
    operator's answer and not the author's. A feed declares the trigger it
    was written for; this is where that can be overridden for one
    installation -- hourly charts on a slow machine, a summary once a night.

    A feed that says nothing runs on the archive record, which is what every
    feed did when there was no choice.
    """
    from . import feeds as feed_registry
    from .options import parse_duration

    out: dict[str, dict] = {}
    for name, settings in (configured_feeds(args) or {}).items():
        if not isinstance(settings, dict):
            continue
        factory = feed_registry.factory_for(str(settings.get("kind", "")))
        # The class's own trigger is the default: `realtime` is written for
        # every reading and should not have to be configured into it.
        declared = getattr(factory, "trigger", "record") if factory else "record"
        wanted = str(settings.get("trigger") or declared)
        if wanted not in feed_registry.TRIGGERS:
            log.warning("the feed %r asks to run on %r, which is not one of "
                        "%s; running it with the archive", name, wanted,
                        ", ".join(feed_registry.TRIGGERS))
            wanted = "record"
        every = 0.0
        if wanted == "schedule":
            try:
                every = float(parse_duration(settings.get("every") or "1h"))
            except Exception:
                log.warning("the feed %r has an unreadable schedule %r; "
                            "using an hour", name, settings.get("every"))
                every = 3600.0
        out[name] = {
            "trigger": wanted,
            "every": every,
            "archive": str(settings.get("archive")
                           or feed_registry.DEFAULT_ARCHIVE),
        }
    return out


def build_feeds(args: argparse.Namespace, cfg: Settings,
                charts: plot_defs.PlotSet) -> list:
    """The feeds this configuration asks for, in the order they run.

    Ordered by dependence: anything reading what another feed wrote runs
    after it. Today that is the diagnostic page, which draws whatever JSON is
    on disk, and the ordering is here rather than inside either of them.
    """

    where = feed_dirs(cfg, args)
    configured = configured_feeds(args)
    registry = read_archives(args, cfg)

    def rank(item: tuple[str, dict]) -> tuple[int, str]:
        # A feed that reads another one goes second.
        return (1 if item[1].get("source") in configured else 0, item[0])

    made: list = []
    for name, settings in sorted(configured.items(), key=rank):
        kind = str(settings.get("kind", "")).strip()
        if settings.get("enabled") is False:
            continue
        # The settings as this feed's archive sees them: same names, the
        # right place. A page for the north field prints the north field's
        # altitude and works out its own sunrise, without any feed having
        # been told that there is more than one series.
        placed = archives_module.placed(
            cfg, registry.get(settings.get("archive")))             if registry.several() else cfg
        if kind == "json":
            made.append((name, _json_feed(placed, name, charts, args),
                         where[name]))
        elif kind == "images":
            made.append((name, _image_feed(placed, name, args), where[name]))
        elif kind == "cheetah":
            made.append((name, _cheetah_feed(placed, name, args), where[name]))
        elif kind == "diagnostic":
            reads = str(settings.get("source") or "json")
            made.append((name, _diagnostic_feed(cfg, name,
                                                where.get(reads, where[name])),
                         where[name]))
        else:
            log.warning("feed %s is of kind %r, which nothing here knows how "
                        "to build; leaving it out", name, kind)
    return made


def _archive_files(cfg: Settings, args: argparse.Namespace) -> dict[str, Path]:
    """Where each configured archive's file is, by name.

    For a chart that draws several places on one axis. Just the paths: the
    feed opens the ones its own plots name, for the length of one run.
    Empty where there is one series, which is every station that has not
    written a second one down.
    """
    registry = read_archives(args, cfg)
    if not registry.several():
        return {}
    base = Path(args.config).parent if getattr(args, "config", None) else None
    out: dict[str, Path] = {}
    for one in registry.all():
        where = Path(one.file)
        if not where.is_absolute() and base is not None:
            where = base / where
        out[one.name] = where
    return out


def _json_feed(cfg: Settings, name: str, charts: plot_defs.PlotSet,
               args: argparse.Namespace):
    from .feeds import jsongenerator

    return lambda reader: jsongenerator.from_settings(
        cfg, reader, load_plots(args, cfg), prefix=f"feeds.{name}",
        archives=_archive_files(cfg, args))


def _image_feed(cfg: Settings, name: str, args: argparse.Namespace):
    from .feeds import imagegenerator

    return lambda reader: imagegenerator.from_settings(
        cfg, reader, load_plots(args, cfg), prefix=f"feeds.{name}",
        archives=_archive_files(cfg, args))


def _cheetah_feed(cfg: Settings, name: str, args: argparse.Namespace):
    """One skin, and the other series it may name.

    A page reads one archive -- its own -- and that is the whole point of
    archives being separate. `$archives.<name>` is the deliberate way past
    it, for an overview page showing several sites at once, and this is what
    puts the other files within reach.

    Each comes with its own settings, wrapped in `archives.Placed`, so
    `$archives.nordfeld` has the north field's coordinates. Given this
    page's, its readings would be right and its sunrise wrong by minutes.
    """
    from .feeds import cheetah

    registry = read_archives(args, cfg)
    others: dict[str, Any] = {}
    if registry.several():
        base = Path(args.config).parent if getattr(args, "config", None) else None
        for one in registry.all():
            where = Path(one.file)
            if not where.is_absolute() and base is not None:
                where = base / where
            others[one.name] = (where, archives_module.placed(cfg, one))

    return lambda reader: cheetah.from_settings(
        cfg, reader, load_plots(args, cfg), prefix=f"feeds.{name}",
        archives=others)


def _diagnostic_feed(cfg: Settings, name: str, reads: Path):
    from .feeds import diagnostic

    return lambda _reader: diagnostic.from_settings(cfg, reads,
                                                    prefix=f"feeds.{name}")


class _Watcher:
    """Notices that the configuration file has been written.

    `Settings.reload()` was built for exactly this and nothing called it, so
    a setting changed on the admin page did nothing at all until somebody
    restarted -- with no message anywhere saying so. Checking a timestamp
    once a tick costs a stat.
    """

    def __init__(self, path: Any) -> None:
        self.path = Path(path) if path else None
        self.seen = self._stamp()

    def _stamp(self) -> float:
        try:
            return self.path.stat().st_mtime if self.path else 0.0
        except OSError:
            return 0.0

    def changed(self) -> bool:
        now = self._stamp()
        if now == self.seen:
            return False
        self.seen = now
        return True

def served_directories(args: argparse.Namespace,
                       cfg: Settings) -> dict[str, Path]:
    """What the built-in server hands out, by name.

    The local exports, plus anything named directly. The same answer
    `site_from` works out, taken from the settings object so it follows a
    reload rather than re-reading the file a second time.
    """
    out: dict[str, Path] = {}
    for name, options in sorted((cfg.config.get("exports") or {}).items()):
        if isinstance(options, dict) and options.get("kind") == "local":
            where = str(options.get("directory", "")).strip()
            if where:
                # The same path the export publishes to, worked out the same
                # way. Two readings of one relative path is a server looking
                # in a directory nothing writes to.
                out[name] = Path(resolve_paths(args, options)["directory"])
    for name, where in ((cfg.config.get("web", {}) or {}).get("serve") or {}).items():
        if isinstance(where, str) and where.strip():
            out[name] = Path(where)
    return out

def cmd_plots_list(args: argparse.Namespace) -> int:
    """What charts exist."""
    cfg = settings_for(args)
    path = plots_path(args, cfg)
    charts = plot_defs.load(path)
    if not len(charts):
        print(f"No plots in {path}.")
        print()
        print("Bring some over from an existing WeeWX skin:")
        print("  weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf")
        return 0

    print(f"{len(charts)} plot(s) in {path}")
    for span, group in sorted(charts.by_span().items()):
        print()
        print(f"  {span}  ({len(group)})")
        for plot in group:
            readings = ", ".join(
                f"{line.obs}" + (f"/{line.aggregate}" if line.aggregate else "")
                for line in plot.lines)
            print(f"    {plot.name:<22} {readings}")
    if charts.labels:
        print()
        print(f"  {len(charts.labels)} label(s) for readings")
    return 0

def cmd_plots_show(args: argparse.Namespace) -> int:
    """One chart, in full."""
    cfg = settings_for(args)
    charts = load_plots(args, cfg)
    plot = charts.get(args.name)
    if plot is None:
        print(f"There is no plot called {args.name!r}.", file=sys.stderr)
        if len(charts):
            print("There is: " + ", ".join(p.name for p in charts),
                  file=sys.stderr)
        return 1

    print(f"{plot.name}   ({plot.span}, "
          f"{option_defs.format_duration(plot.time_length)} back)")
    if plot.title:
        print(f"  title: {plot.title}")
    if plot.show_daynight:
        print("  night is shaded")
    if plot.skip_if_empty:
        print(f"  left out where there is nothing over a {plot.skip_if_empty}")
    if any(v is not None for v in plot.yscale):
        low, high, step = plot.yscale
        print(f"  y axis: {low if low is not None else 'auto'}"
              f" to {high if high is not None else 'auto'}"
              f", step {step if step is not None else 'auto'}")
    print()
    for line in plot.drawn:
        bits = [f"{line.kind}", f"color {line.color}"]
        if line.aggregate:
            bits.append(f"{line.aggregate} per {line.interval}")
        if line.label or charts.labels.get(line.obs):
            bits.append(f"labelled {line.label or charts.labels[line.obs]!r}")
        print(f"  {line.obs:<16} {', '.join(bits)}")
    return 0

def cmd_plots_import(args: argparse.Namespace) -> int:
    """Take the plots out of a WeeWX skin.conf or weewx.conf.

    Read, reported, and only written when asked. An import that silently
    replaced a set of charts somebody had tuned would be worse than no import.
    """
    try:
        conf = weewxconf.read(args.source)
    except OSError as exc:
        print(f"Cannot read {args.source}: {exc}", file=sys.stderr)
        return 1

    section = conf.get("ImageGenerator")
    if not isinstance(section, dict):
        # A weewx.conf holds the skins by name rather than the plots
        # themselves; say where to look rather than "nothing found".
        print(f"No [ImageGenerator] section in {args.source}.", file=sys.stderr)
        skins = [k for k, v in conf.items()
                 if isinstance(v, dict) and "ImageGenerator" in v]
        if skins:
            print("  It is in: " + ", ".join(skins), file=sys.stderr)
        else:
            print("  Plots live in a skin's skin.conf, not in weewx.conf --"
                  " try skins/Seasons/skin.conf.", file=sys.stderr)
        return 1

    result = plot_defs.from_image_generator(section, plot_defs.labels_from(conf))
    print(result.report(str(args.source)))

    if not args.write:
        print()
        print("Nothing was changed. Keep them with --write.")
        return 0

    cfg = settings_for(args)
    path = plots_path(args, cfg)
    existing = plot_defs.load(path)
    if len(existing) and not args.replace:
        kept = 0
        for plot in result.plots:
            if existing.get(plot.name) is None:
                existing.add(plot)
            else:
                kept += 1
        existing.labels.update(
            {k: v for k, v in result.plots.labels.items()
             if k not in existing.labels})
        written = existing
        print()
        print(f"Added to the {len(existing) - len(result.plots) + kept} already"
              f" there; {kept} kept as they were."
              " Use --replace to start from nothing instead.")
    else:
        written = result.plots

    plot_defs.save(path, written, f"Imported from {args.source}.")
    print(f"Written to {path}.")
    return 0

def cmd_plots_remove(args: argparse.Namespace) -> int:
    """Delete a chart."""
    cfg = settings_for(args)
    path = plots_path(args, cfg)
    charts = plot_defs.load(path)
    if not charts.remove(args.name):
        print(f"There is no plot called {args.name!r}.", file=sys.stderr)
        return 1
    plot_defs.save(path, charts)
    print(f"Removed {args.name} from {path}.")
    return 0

def cmd_plots_run(args: argparse.Namespace) -> int:
    """Produce the JSON now, and say what came out."""
    import sqlite3

    from .feeds import jsongenerator
    from .series import Reader

    cfg = settings_for(args)
    # This renders without starting a listener, so nothing has configured the
    # drivers -- and a chart of a column only the driver can name would come
    # out unconverted and unlabelled. Their field names cost nothing to ask
    # for and are the same whether the driver is configured or not.
    install_driver_groups()
    charts = load_plots(args, cfg)
    if not len(charts):
        print("No plots are defined. See `weewx-evo plots import`.",
              file=sys.stderr)
        return 1

    archive = Path(cfg.get("archive_db"))
    if not archive.exists():
        print(f"No archive at {archive}.", file=sys.stderr)
        return 1

    connection = sqlite3.connect(f"file:{archive}?mode=ro", uri=True)
    try:
        generator = jsongenerator.from_settings(cfg, Reader(connection), charts)
        into = Path(args.into or (Path(cfg.get("feeds_dir") or "data/feeds")
                                  / "json"))
        made = generator.produce(into)
    finally:
        connection.close()

    print(f"{made.note or 'nothing'}")
    print(f"  into {made.directory}")
    if made.files:
        total = sum(f.stat().st_size for f in made.files if f.exists())
        print(f"  {len(made.files)} file(s), {total / 1024:.1f} KB")

    if args.page:
        # The diagnostic page, beside the data. One file that draws all of it
        # and lists what looks wrong -- worth the second it costs, because the
        # alternative is reading JSON by eye.
        from .feeds import diagnostic

        page = diagnostic.from_settings(cfg, made.directory)
        drawn = page.produce(made.directory.parent)
        print()
        print(f"  {drawn.note}")
        print(f"  {drawn.files[0] if drawn.files else drawn.directory}")
    return 0


def start_feeds(args: argparse.Namespace,
                cfg: Settings) -> feed_runner.Runner | None:
    """Start the feed runner, or say why there is nothing to run.

    One function for both loops. They had their own copies once and only one
    of them ever told the runner that a record had landed, so the feeds never
    produced anything and nothing said why.
    """
    charts = load_plots(args, cfg)
    if not len(charts):
        log.info("no charts are defined in %s, so no feeds are running. "
                 "Bring some over with `weewx-evo plots import`.",
                 plots_path(args, cfg))
        return None
    # `feeds.json.enabled` is from when there was exactly one feed and it was
    # called `json`. It still turns off a feed of that name, and it must not
    # decide anything for an installation whose feeds are called something
    # else -- two archives means two JSON feeds with two names, and neither
    # of them is this one.
    if (configured_feeds(args).get("json") or {}) and \
            cfg.get("feeds.json.enabled") is False:
        log.info("the JSON feed is switched off, so no feeds are running")
        return None

    registry = read_archives(args, cfg)
    base = Path(args.config).parent if getattr(args, "config", None) else None
    paths = {}
    for archive in registry.all():
        where = Path(archive.file)
        if not where.is_absolute() and base is not None:
            where = base / where
        paths[archive.name] = where

    runner = feed_runner.Runner(build_feeds(args, cfg, charts),
                                archive_path=paths[archives_module.DEFAULT],
                                schedule=feed_schedule(args),
                                archives=paths)
    runner.start()
    # Every feed's directory, not `where["json"]`. That indexed a feed by
    # name on the assumption there was one called `json`, so an installation
    # with two of them -- which is what two archives look like -- raised
    # KeyError here and the service did not start at all. The line is a log
    # message; it took the whole process with it.
    where = feed_dirs(cfg, args)
    written = ", ".join(f"{name} -> {path}"
                        for name, path in sorted(where.items())) or "nowhere"
    log.info("%d chart(s) from %s, written to %s", len(charts),
             plots_path(args, cfg), written)
    return runner


def _archive_rows(archive: Path, since: int, limit: int = 0) -> list[dict]:
    """Records out of the archive, oldest first."""
    import sqlite3

    connection = sqlite3.connect(f"file:{archive}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM archive WHERE dateTime >= ? ORDER BY dateTime"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [dict(row) for row in connection.execute(sql, (since,))]
    finally:
        connection.close()


def configured_notify(args: argparse.Namespace) -> dict[str, dict]:
    """What the configuration file says about notification channels."""
    cfg = settings_for(args)
    section = cfg.config.get("notify") or {}
    return {name: dict(settings) for name, settings in section.items()
            if isinstance(settings, dict)}


def build_channel(name: str, settings: dict) -> object:
    """One channel from its settings. Raises with a usable message."""
    kind = str(settings.pop("kind", "")).strip()
    if not kind:
        raise ValueError(f"channel {name!r} does not say what kind it is. "
                         f'Add kind = "email" or one of: '
                         f"{', '.join(notify_registry.kinds())}.")
    factory = notify_registry.DEFAULT.factory_for(kind)
    if factory is None:
        raise ValueError(f"channel {name!r} is of kind {kind!r}, which is not "
                         f"one of: {', '.join(notify_registry.kinds())}")
    schema = option_defs.schema_of(factory, name=kind, label=kind)
    if schema is not None:
        parsed, errors = schema.parse(settings, only_present=True)
        if errors:
            first = next(iter(errors.values()))
            raise ValueError(f"channel {name!r}: {first}")
        settings = parsed
    return factory(**settings)


def build_metrics(args: argparse.Namespace, cfg: Settings, dog: Any = None,
                  live: Any = None) -> Any:
    """What the process is doing, or None where it is switched off."""
    if not cfg.get("metrics.enabled"):
        return None
    from .metrics import Metrics

    base = Path(args.config).parent if getattr(args, "config", None) else None
    where: dict[str, Path] = {}
    for archive in read_archives(args, cfg).all():
        path = Path(archive.file)
        if not path.is_absolute() and base is not None:
            path = base / path
        where[archive.name] = path

    live_db = Path(cfg.get("live_db") or "data/live.sdb")
    if not live_db.is_absolute() and base is not None:
        live_db = base / live_db

    return Metrics(live=live_db, archives=where, dog=dog,
                   senders=sorted(set(configured_uploads(args))
                                  | set(configured_exports(args))),
                   station_name=str(cfg.get("station.name") or ""))


def build_api(args: argparse.Namespace, cfg: Settings,
              stations: Any = None) -> Any:
    """The read-only API, or None where it is switched off.

    Every archive, by name, so a client can ask about any of them -- the same
    list the dashboards and the feeds work from. Read-only throughout: it
    holds paths and opens each of them for the length of one request.
    """
    if not cfg.get("api.enabled"):
        return None
    from .api import Api

    base = Path(args.config).parent if getattr(args, "config", None) else None
    where: dict[str, Path] = {}
    for archive in read_archives(args, cfg).all():
        path = Path(archive.file)
        if not path.is_absolute() and base is not None:
            path = base / path
        where[archive.name] = path
    if not where:
        return None
    return Api(where, default=archives_module.DEFAULT,
               token=str(cfg.get("api.token") or ""),
               stations=stations,
               station_name=str(cfg.get("station.name") or ""))


def build_notify_runner(args: argparse.Namespace, cfg: Settings, live: Any,
                        stations: Any = None, dog: Any = None) -> Any:
    """The notification runner, or None where nothing is configured.

    What it watches for failures is the exports and the uploads, because
    those are the two that write to `live_metadata` when a run goes wrong. A
    feed is not among them: a feed that fails writes nothing anywhere yet,
    and claiming to watch it would be worse than not watching it.
    """
    from .notify import Timing
    from .notify import runner as notify_runner

    entries = configured_notify(args)
    if not entries:
        return None

    channels = []
    for name, settings in sorted(entries.items()):
        settings = dict(settings)
        after = float(settings.pop("after", None)
                      or notify_registry.DEFAULT_AFTER)
        repeat = float(settings.pop("repeat", None)
                       or notify_registry.DEFAULT_REPEAT)
        try:
            channel = build_channel(name, settings)
        except ValueError as exc:
            # Said once and skipped. A channel with a typo in it must not
            # stop the others, and the others are the point.
            log.warning("notifications: %s", exc)
            continue
        channels.append(notify_runner.Channel(
            name=name, channel=channel,
            timing=Timing(after=after, repeat=repeat)))

    if not channels:
        return None
    senders = sorted(set(configured_uploads(args))
                     | set(configured_exports(args)))
    return notify_runner.Runner(
        channels, live=live, stations=stations, dog=dog, senders=senders,
        station_name=str(cfg.get("station.name") or ""))


def _databases(args: argparse.Namespace, cfg: Settings) -> list[tuple[str, Path]]:
    """Every database this installation keeps, by name.

    The archives first, because those are the ones that cannot be rebuilt.
    The live table and the forecast are here too and are named as what they
    are -- both are replaceable, and somebody deciding what to copy nightly
    should be told which is which rather than left to guess from a filename.
    """
    found: list[tuple[str, Path]] = []
    base = Path(args.config).parent if getattr(args, "config", None) else None

    seen: set[Path] = set()
    for archive in read_archives(args, cfg).all():
        # Relative against the configuration file, the same rule as
        # `open_archive` -- an archive named in archives.toml would otherwise
        # be backed up from wherever the command was typed.
        where = Path(archive.file)
        if not where.is_absolute() and base is not None:
            where = base / where
        if where not in seen:
            seen.add(where)
            found.append((f"archive:{archive.name}", where))
    return found


def cmd_backup(args: argparse.Namespace) -> int:
    """Copy the archive safely, while the station carries on.

    `sqlite3.Connection.backup`, not a file copy. See maintenance.py: with
    WAL on, the file on disk is not the database, and a copy of it opens
    perfectly while missing everything since the last checkpoint.
    """
    cfg = settings_for(args)
    into = Path(args.into) if args.into else None
    problems = 0

    for name, where in _databases(args, cfg):
        if not where.exists():
            print(f"  {name}: no database at {where}")
            problems += 1
            continue

        target = into or where.parent / "backups"
        tight = maintenance.enough_room(where, target)
        if tight:
            # Asked before rather than found out during. A copy that fills
            # the disk can stop the archiver writing.
            print(f"  {name}: not enough room -- {tight}")
            problems += 1
            continue

        copy = maintenance.backup(where, into=target, keep=args.keep)
        if not copy.ok:
            print(f"  {name}: {copy.summary()}")
            problems += 1
            continue
        maintenance.owner_readable_only(copy.path)

        # The check people skip, and the only one that matters: a backup
        # nobody has opened is a hope.
        wrong = maintenance.restorable(copy.path)
        if wrong:
            print(f"  {name}: written, but it does not read back -- {wrong}")
            problems += 1
            continue
        print(f"  {name}: {copy.path}")
        print(f"    {copy.summary()}, opens and holds records")
        for gone in copy.removed:
            print(f"    removed {gone.name}")
    return 1 if problems else 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Is the file sound, and do the summaries still follow from the records?

    Two questions, and the second is ours. `archive_day_*` is a cache: all of
    it is derivable from `archive`, and a day that no longer follows can be
    repaired with `rebuild`. Nothing here writes.
    """
    cfg = settings_for(args)
    problems = 0

    for name, where in _databases(args, cfg):
        verdict = maintenance.verify(where, days=args.days, deep=args.deep)
        print(f"  {name}: {verdict.summary()}")
        if verdict.problems:
            problems += 1
            for said in verdict.problems[:6]:
                print(f"    {said}")
        if verdict.days:
            problems += 1
            print(f"    {len(verdict.days)} day(s) whose summaries do not "
                  f"follow from the records:")
            for start in verdict.days[:6]:
                stamp = time.strftime("%Y-%m-%d", time.localtime(start))
                print(f"      {stamp}   weewx-evo rebuild {start} "
                      f"{start + 86400}")
        if verdict.ok:
            print("    sound, and the summaries follow")
    return 1 if problems else 0


def cmd_vacuum(args: argparse.Namespace) -> int:
    """Rewrite a database without its free pages."""
    cfg = settings_for(args)
    for name, where in _databases(args, cfg):
        if not where.exists():
            continue
        room = maintenance.space(where)
        if room["free"] < args.least * 1_048_576 and not args.force:
            print(f"  {name}: {room['free'] / 1_048_576:.1f} MB to reclaim, "
                  f"which is under the {args.least} MB threshold. --force "
                  f"to do it anyway.")
            continue
        before, after = maintenance.vacuum(where)
        print(f"  {name}: {before / 1_048_576:.1f} MB -> "
              f"{after / 1_048_576:.1f} MB")
    return 0


def cmd_notify_list(args: argparse.Namespace) -> int:
    """What is configured, and what could be."""
    entries = configured_notify(args)
    print("Available:")
    for kind in notify_registry.kinds():
        print(f"  {kind:10} {notify_registry.describe(kind)}")
    print()
    if not entries:
        print("None configured. Nothing will tell you when a station stops.")
        return 0

    print("Configured:")
    for name, settings in sorted(entries.items()):
        print(f"  {name:16} {settings.get('kind', '?')}")
    if len(entries) < 2:
        # Said rather than enforced. It is the operator's network and their
        # judgement, and refusing to run with one channel would be wrong for
        # the installation that only wants one.
        print()
        print("  Only one channel. A message about the network, sent over "
              "the network,")
        print("  is the alert most likely to be the one that does not arrive.")
    return 0


def cmd_notify_check(args: argparse.Namespace) -> int:
    """Send a test message through each channel."""
    entries = configured_notify(args)
    if args.name:
        entries = {k: v for k, v in entries.items() if k == args.name}
        if not entries:
            print(f"No channel called {args.name!r}.", file=sys.stderr)
            return 1
    if not entries:
        print("None configured.")
        return 0

    problems = 0
    for name, settings in sorted(entries.items()):
        try:
            channel = build_channel(name, dict(settings))
        except ValueError as exc:
            print(f"  {name}: {exc}")
            problems += 1
            continue
        try:
            print(f"  {name}: {channel.check()}")
        finally:
            closing = getattr(channel, "close", None)
            if closing is not None:
                closing()
    return 1 if problems else 0


def cmd_notify_status(args: argparse.Namespace) -> int:
    """What is wrong right now, whether or not anybody has been told."""
    cfg = settings_for(args)
    live_db = Path(cfg.get("live_db") or "data/live.sdb")
    if not live_db.is_absolute():
        base = (Path(args.config).parent
                if getattr(args, "config", None) else Path())
        live_db = base / live_db
    if not live_db.exists():
        print(f"No live database at {live_db}.", file=sys.stderr)
        return 1

    from .notify import Memory
    from .notify import rules as notify_rules

    stations, _sightings = read_stations(args, cfg)
    senders = sorted(set(configured_uploads(args))
                     | set(configured_exports(args)))
    with LiveStore(live_db) as live:
        seen = notify_rules.everything(live, stations, None, senders)
        memory = Memory(live)

    if not seen:
        print("Nothing is wrong.")
        return 0

    now = time.time()
    for key in sorted(seen):
        event = seen[key]
        standing = memory.standing.get(key)
        held = now - (standing.since if standing else event.since or now)
        told = "told" if standing and standing.told else "not told yet"
        print(f"  {event.text}")
        print(f"    for {held / 60:.0f} min, {told}")
    return 1


def cmd_quality_suggest(args: argparse.Namespace) -> int:
    """Work rules out of what this station has actually recorded.

    Nobody can type a plausible ceiling for `soilMoist3` out of their head,
    and a guessed limit throws away readings. So the figures come off the
    station: the archive for the floors and ceilings, because it has years and
    knows how cold it gets, and the live table for the spike and stuck rules,
    because only it has the packet-to-packet steps those are about. Suggesting
    a spike rule from five-minute records gives one several times too tight --
    the weather has five minutes to move between them.
    """
    from . import quality as quality_module

    cfg = settings_for(args)
    install_driver_groups()
    archive = Path(cfg.get("archive_db") or "")
    if not archive.exists():
        print(f"No archive at {archive}.", file=sys.stderr)
        return 1

    since = int(time.time()) - int(args.days) * 86400
    rows = _archive_rows(archive, since)
    if not rows:
        print(f"No records in the last {args.days} days.", file=sys.stderr)
        return 1

    system = units.system_from(args.units or "metricwx", default=units.METRICWX)
    wide = quality_module.watch(rows, system=system)

    close: dict[str, Any] = {}
    live_db = Path(cfg.get("live_db") or "")
    if live_db.exists():
        with LiveStore(live_db) as live:
            first, last = live.span()
            if first and last:
                packets = [p.record() for p in live.packets(first - 1, last)]
                close = quality_module.watch(packets, system=system)
    if not close:
        print("# No live packets. The spike figures below therefore come from "
              "archive\n# records and are several times too tight, and there "
              "are no stuck rules\n# at all: neither can be worked out from "
              "five-minute records.",
              file=sys.stderr)

    seen = quality_module.merge(wide, close)
    wanted = set(args.fields.split(",")) if args.fields else None

    print(f'# Written by `weewx-evo quality suggest` from {len(rows)} '
          f'record(s)')
    print(f"# over {args.days} days, and {len(close)} reading(s) of live "
          f"packets.")
    print("#")
    print("# Read it, then keep the lines you agree with. Every figure has "
          "room in")
    print("# it, but a station that has not seen a cold winter yet has not "
          "seen its")
    print("# own floor either.")
    print()
    print(f'unit_system = "{units.name(system).lower()}"')
    for obs in sorted(seen):
        if wanted is not None and obs not in wanted:
            continue
        print()
        print(seen[obs].as_toml())
    return 0


def cmd_quality_check(args: argparse.Namespace) -> int:
    """Run the configured rules over what is stored, and change nothing.

    The answer to "what would this cost me". A limit set too tightly is the
    expensive mistake here, and the only way to see it before it happens is
    to run it over readings that are already known to be good.
    """
    from . import quality as quality_module

    cfg = settings_for(args)
    install_driver_groups()
    policy = read_quality(args, cfg)
    if not policy:
        print("No rules are configured. See `weewx-evo quality suggest`.",
              file=sys.stderr)
        return 1

    archive = Path(cfg.get("archive_db") or "")
    since = int(time.time()) - int(args.days) * 86400
    rows = _archive_rows(archive, since) if archive.exists() else []
    if not rows:
        print(f"No records in the last {args.days} days.", file=sys.stderr)
        return 1

    checker = quality_module.Check(policy)
    verdicts: list[Any] = []
    for row in rows:
        when = float(row.get("dateTime") or 0)
        system = units.system_from(row.get("usUnits"), default=units.METRICWX)
        corrected = checker.calibrate(row, "", system)
        _kept, said = checker.check(corrected, when, "", system)
        verdicts.extend(said)

    print(f"{len(rows)} record(s) over {args.days} days.")
    if not verdicts:
        print("  Nothing would be refused.")
        return 0

    print(f"  {len(verdicts)} reading(s) would be refused:")
    for obs, count in sorted(checker.dropped.items(), key=lambda x: -x[1]):
        share = 100.0 * count / len(rows)
        print(f"    {obs:22} {count:6}  ({share:.1f}% of records)")

    print()
    print("  The first few, in full:")
    for verdict in verdicts[:8]:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(verdict.when))
        print(f"    {stamp}  {verdict}")

    # A rule refusing a large share of a station's own history is a rule
    # about the rule, not about the sensor.
    worst = max(checker.dropped.values())
    if worst > len(rows) * 0.05:
        print()
        print("  More than one record in twenty is refused. That is usually "
              "a limit set\n  too tightly rather than a sensor at fault.")
        return 1
    return 0


def _grafana_out(args: argparse.Namespace, cfg: Any) -> Path:
    """Where the provisioning files go.

    A path typed on the command line counts against the directory it was
    typed in; the default counts against the configuration file. Same rule as
    `Settings.get`, and it exists because the two disagreed once already: a
    relative `archive_db` named one file for the settings page and another
    for the service.
    """
    if getattr(args, "out", None):
        return Path(args.out)
    base = getattr(cfg, "_path", None)
    return (Path(base).parent if base else Path(".")) / "grafana"


def _grafana_servers(args: argparse.Namespace, cfg: Any) -> list:
    from . import grafana, language

    return grafana.servers_from(
        dict(configured_uploads(args)),
        language.get(getattr(args, "language", None) or cfg.get("language")))


def cmd_grafana_list(args: argparse.Namespace) -> int:
    """What would be provisioned, without writing anything."""
    from .grafana import dashboards

    cfg = settings_for(args)
    install_driver_groups()
    servers = _grafana_servers(args, cfg)
    if not servers:
        print("No InfluxDB upload is configured, so there is nothing to "
              "point Grafana at.\n"
              'Add one: [uploads.<name>] with kind = "influx".',
              file=sys.stderr)
        return 1

    charts = load_plots(args, cfg)
    for server in servers:
        print(f"{server.name}  {server.url}")
        print(f"  bucket      {server.bucket}"
              + (f"  org {server.org}" if server.org else ""))
        print(f"  uploads     {', '.join(server.uploads)}")
        print(f"  locations   {', '.join(server.locations) or '(none named)'}")
        print(f"  units       {units.name(server.system)}")
        for name, board in sorted(dashboards.all_of(server, charts).items()):
            drawn = [p for p in board["panels"] if p["type"] != "row"]
            print(f"  {name:28} {board['title']}  ({len(drawn)} panels)")
    return 0


def cmd_grafana_provision(args: argparse.Namespace) -> int:
    """Write the datasource and the dashboards Grafana reads at start."""
    from . import grafana, language

    cfg = settings_for(args)
    # Rendered without a listener, so nothing has configured the drivers --
    # and a panel for a column only the driver can name would come out
    # unlabelled and in the wrong unit. Same call, same reason, as `plots run`.
    install_driver_groups()

    archive = Path(cfg.get("archive_db") or "")
    report = grafana.provision(
        _grafana_out(args, cfg),
        dict(configured_uploads(args)),
        load_plots(args, cfg),
        archive=archive if archive and archive.exists() else None,
        read_token=getattr(args, "read_token", "") or "",
        language=language.get(getattr(args, "language", None)
                              or cfg.get("language")),
        # A forecast dashboard where no source is configured is a page of
        # empty panels, and nothing on it can say why.
        forecasts=bool(configured_forecasts(args)))

    for note in report.notes:
        print(f"note: {note}")
    if not report.files:
        return 1

    print(report.summary())
    for path in report.files:
        print(f"  {path}")
    print("\nGrafana reads these at start and rescans the dashboards every "
          "minute.\nA new datasource needs a restart; changed dashboards do "
          "not.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = settings_for(args)
    live_path = Path(cfg.get("live_db"))
    live = LiveStore(cfg.get("live_db"), interval_seconds=cfg.get("interval"),
                     keep_raw_seconds=cfg.get("raw_retention"))
    registry = read_archives(args, cfg)
    base = Path(args.config).parent if getattr(args, "config", None) else None
    opened = []
    try:
        first, last = live.span()
        series = {}
        for one in registry.all():
            store = open_archive(one, cfg, base)
            opened.append(store)
            where = Path(one.file)
            if not where.is_absolute() and base is not None:
                where = base / where
            series[one.name] = {
                "path": str(where),
                "records": store.count(),
                "newest": store.last_timestamp(),
                "columns": len(store.schema.columns),
                "daily_tables": len(store.schema.day_types),
                "summary_version": store.schema.version,
                "size_mb": round(where.stat().st_size / 1e6, 1)
                if where.exists() else 0.0,
                # Per series, because that is how the live table now counts
                # them: an interval one archive has taken and another has
                # not is not the same number twice.
                "pending_intervals": len(live.due(grace=0, archive=one.name)),
            }
        report = {
            "live": {
                "path": str(live_path),
                "packets": live.count(),
                "oldest": first,
                "newest": last,
                "pending_intervals": len(live.due(grace=0)),
                "size_mb": round(live_path.stat().st_size / 1e6, 1),
            },
            "drivers": drivers.names(),
            # The default one under its old name, so anything reading this
            # output goes on working, and every one of them under "archives".
            "archive": series[archives_module.DEFAULT],
            "archives": series,
        }
        print(json.dumps(report, indent=2))
    finally:
        live.close()
        for store in opened:
            store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="weewx-evo", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log-level", default=env("LOG_LEVEL", "INFO"))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="listener and archiver in one process")
    add_common(p), add_listen_args(p), add_archive_args(p)
    p.add_argument("--explain", action="store_true",
                   help="print every setting and where it came from, then stop")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("listen", help="the listener alone")
    add_common(p), add_listen_args(p)
    p.set_defaults(func=cmd_listen)

    p = sub.add_parser("archive", help="the archiver alone")
    add_common(p), add_archive_args(p)
    add_archive_arg(p)
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("catchup", help="build every interval the live table covers")
    add_common(p)
    add_archive_arg(p)
    p.add_argument("--replace", action="store_true",
                   help="overwrite records that are already there")
    p.set_defaults(func=cmd_catchup)

    p = sub.add_parser("rebuild", help="work a time span out again")
    add_common(p)
    add_archive_arg(p)
    p.add_argument("start", type=int, help="unix timestamp, exclusive")
    p.add_argument("stop", type=int, help="unix timestamp, inclusive")
    p.add_argument("--no-resend", dest="resend", action="store_false",
                   help="leave the uploads that hold a copy of the archive "
                        "where they are. Without this they are wound back to "
                        "the start of the span, so the corrected records "
                        "reach them.")
    p.set_defaults(func=cmd_rebuild)

    p = sub.add_parser("derive",
                       help="work out derived readings on stored records")
    add_common(p)
    p.add_argument("--start", type=int, default=None,
                   help="unix timestamp, exclusive. The whole archive by "
                        "default.")
    p.add_argument("--stop", type=int, default=None,
                   help="unix timestamp, inclusive. Now by default.")
    p.add_argument("--replace", action="store_true",
                   help="work out every derived reading again, including "
                        "ones already there. Without this only the empty "
                        "ones are filled, which is what a calculator that "
                        "arrived late needs.")
    p.add_argument("--calm", action="store_true",
                   help="also clear wind directions on records where the "
                        "wind was zero. A direction with no wind behind it "
                        "is not a reading, but removing one already stored "
                        "is a deletion, so it is asked for.")
    p.add_argument("--dry-run", action="store_true",
                   help="say what would change and change nothing.")
    p.set_defaults(func=cmd_derive)

    # A WeeWX driver, run in its own process. Its own subcommand rather than
    # an option on `listen`, because that is the arrangement: the driver is
    # somewhere else, and what reaches the listener is an ordinary upload.
    p = sub.add_parser("weewx-driver",
                       help="run a WeeWX driver and deliver what it produces")
    shim_sub = p.add_subparsers(dest="shim_command", required=True)

    def add_shim_common(q):
        add_common(q)
        q.add_argument("--collector", default=None,
                       help="a collector named in the configuration file. Its "
                            "settings are used, and -- the part that matters "
                            "-- its packets arrive under its own name, so a "
                            "station can be announced for it.")
        q.add_argument("--conf", default=None,
                       help="the weewx.conf the driver is configured by. "
                            "/etc/weewx/weewx.conf by default.")
        q.add_argument("--driver", default=None,
                       help="the driver module, if not the one [Station] "
                            "names. For example weewx.drivers.vantage.")
        q.add_argument("--driver-file", default=None,
                       help="load the driver from this file rather than from "
                            "an installed WeeWX. A driver is one file, and "
                            "what it imports is stood in for -- so one USB "
                            "console no longer means installing all of WeeWX.")
        q.add_argument("--source", default=None,
                       help="what to record these readings under. The "
                            "driver's own hardware name by default.")

    q = shim_sub.add_parser("list", help="what the weewx.conf asks for")
    add_shim_common(q)
    q.set_defaults(func=cmd_weewx_driver_list)

    q = shim_sub.add_parser("check", help="build it, take a few packets, "
                                          "deliver nothing")
    add_shim_common(q)
    q.add_argument("--count", type=int, default=3,
                   help="how many packets to wait for")
    q.set_defaults(func=cmd_weewx_driver_check)

    q = shim_sub.add_parser("run", help="deliver to the listener, until stopped")
    add_shim_common(q)
    q.add_argument("--host", default=None,
                   help="the listener's address. Loopback by default, which "
                        "is where it is when both run on one machine.")
    q.add_argument("--port", type=int, default=None,
                   help="the listener's port")
    q.add_argument("--batch", type=float, default=5.0,
                   help="seconds of packets per delivery. One request per "
                        "loop packet is a round trip every two seconds for "
                        "readings that are aggregated at the end of the "
                        "interval anyway.")
    q.add_argument("--catchup", type=int, default=None,
                   help="seconds of the console's own logged records to "
                        "fetch at startup, for hardware that keeps them. "
                        "This is how an outage becomes a filled gap instead "
                        "of a lost one.")
    q.add_argument("--limit", type=int, default=None,
                   help="stop after this many packets. For trying it out.")
    q.add_argument("--dry-run", action="store_true",
                   help="run the driver and deliver nothing.")
    q.set_defaults(func=cmd_weewx_driver_run)

    p = sub.add_parser("mqtt", help="subscribe to a broker and deliver what "
                                    "it publishes")
    mqtt_sub = p.add_subparsers(dest="mqtt_command", required=True)

    def add_mqtt_common(q):
        add_common(q)
        q.add_argument("--collector", default=None,
                       help="a collector named in the configuration file. Its "
                            "settings are used, and its packets arrive under "
                            "its own name, so a station can be announced "
                            "for it.")
        # None everywhere, so a value here does not silently outrank the
        # configuration file. Same trap as anywhere else in this parser.
        q.add_argument("--broker", dest="host", default=None,
                       help="where the broker is")
        q.add_argument("--port", type=int, default=None,
                       help="the broker's port. 1883, or 8883 with --tls.")
        q.add_argument("--topic", default=None,
                       help="what to subscribe to. `#` is everything.")
        q.add_argument("--username", default=None)
        q.add_argument("--tls", action="store_const", const=True, default=None)

    q = mqtt_sub.add_parser("check", help="subscribe, print what arrives, "
                                         "deliver nothing")
    add_mqtt_common(q)
    q.add_argument("--seconds", type=int, default=10,
                   help="how long to listen for")
    q.set_defaults(func=cmd_mqtt_check)

    q = mqtt_sub.add_parser("run", help="deliver to the listener, until stopped")
    add_mqtt_common(q)
    q.add_argument("--listener", dest="host_listener", default=None,
                   help="the listener's address. Loopback by default.")
    q.add_argument("--listener-port", type=int, default=None,
                   help="the listener's port")
    q.add_argument("--dry-run", action="store_true",
                   help="subscribe and deliver nothing")
    q.set_defaults(func=cmd_mqtt_run)

    p = sub.add_parser("columns", help="readings that have nowhere to live")
    add_common(p)
    p.add_argument("--add", action="store_true",
                   help="create the missing columns; back the database up first")
    p.set_defaults(func=cmd_columns)

    p = sub.add_parser("driver", help="list, install and remove drivers")
    driver_sub = p.add_subparsers(dest="driver_command", required=True)

    q = driver_sub.add_parser("list", help="what is bundled and what is installed")
    _add_driver_dir(q)
    q.set_defaults(func=cmd_driver_list)

    q = driver_sub.add_parser("install", help="install from a repository, zip or path")
    _add_driver_dir(q)
    q.add_argument("source", help="a git URL, a zip URL, a .zip file, or a directory")
    q.add_argument("--name", help="install it under this name instead")
    q.add_argument("--force", action="store_true", help="replace an existing one")
    q.set_defaults(func=cmd_driver_install)

    q = driver_sub.add_parser("remove", help="delete an installed driver")
    _add_driver_dir(q)
    q.add_argument("name")
    q.set_defaults(func=cmd_driver_remove)

    p = sub.add_parser("url", help="the live view and upload addresses, with the token")
    p.add_argument("--config", type=Path, default=(
        Path(env("CONFIG")) if env("CONFIG") else None))
    p.add_argument("--token", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--driver", default=None,
                   help="which driver the upload address should name")
    p.add_argument("--public", default=None,
                   help="the outside address, e.g. https://weather.example.org")
    p.add_argument("--qr", action="store_true", help="also print a QR code")
    p.set_defaults(func=cmd_url)

    p = sub.add_parser("config", help="show, change, check and import settings")
    config_sub = p.add_subparsers(dest="config_command", required=True)

    q = config_sub.add_parser("show", help="print the configuration, commented")
    q.add_argument("--config", type=Path, default=(
        Path(env("CONFIG")) if env("CONFIG") else None))
    q.add_argument("--defaults", action="store_true",
                   help="fill in every default, to see what there is")
    q.set_defaults(func=cmd_config_show)

    q = config_sub.add_parser("set", help="change one setting")
    q.add_argument("--config", type=Path, default=(
        Path(env("CONFIG")) if env("CONFIG") else None))
    q.add_argument("name")
    q.add_argument("value")
    q.set_defaults(func=cmd_config_set)

    q = config_sub.add_parser("check", help="say what is wrong with it")
    q.add_argument("--config", type=Path, default=(
        Path(env("CONFIG")) if env("CONFIG") else None))
    q.set_defaults(func=cmd_config_check)

    q = config_sub.add_parser("import", help="read settings out of a weewx.conf")
    q.add_argument("weewx_conf", type=Path)
    q.add_argument("--config", type=Path, default=(
        Path(env("CONFIG")) if env("CONFIG") else None))
    q.add_argument("--write", action="store_true", help="actually write them")
    q.add_argument("--overwrite", action="store_true",
                   help="replace settings that are already set here")
    q.set_defaults(func=cmd_config_import)

    p = sub.add_parser("admin", help="serve the settings page")
    p.add_argument("--config", type=Path, default=(
        Path(env("CONFIG")) if env("CONFIG") else None),
        help="the configuration file this page edits")
    p.add_argument("--host", default=None,
                   help="bound to everything; --allow decides who is answered")
    p.add_argument("--allow", default=None,
                   help="which addresses get an answer: 'private' (the default, "
                        "meaning the local network), 'any', or a list")
    p.add_argument("--port", type=int, default=None)
    # `dest`, because an argument reaches the settings under the option name
    # with the dots turned into underscores -- and the option here is
    # `admin.token`. Without it `--token` set the *upload* token instead, so
    # the one flag whose help says "never the upload one" was the upload one,
    # and the command then refused to start because the two now matched.
    p.add_argument("--token", dest="admin_token", default=None,
                   help="its own token, never the upload one")
    p.add_argument("--rate", type=float, default=None,
                   help="requests a second per address (default: 5)")
    p.add_argument("--behind-proxy", action="store_true", default=None,
                   help="leave rate limiting to the proxy in front")
    p.add_argument("--read-only", action="store_true",
                   help="show the settings but refuse to save")
    p.set_defaults(func=cmd_admin)

    p = sub.add_parser("export", help="move what a feed produced somewhere")
    export_sub = p.add_subparsers(dest="export_command", required=True)

    q = export_sub.add_parser("list", help="what is available and configured")
    add_common(q)
    q.set_defaults(func=cmd_export_list)

    q = export_sub.add_parser("check", help="try the destination, send nothing")
    add_common(q)
    q.add_argument("name", nargs="?", help="just this one")
    q.set_defaults(func=cmd_export_check)

    q = export_sub.add_parser("run", help="send")
    add_common(q)
    q.add_argument("name", nargs="?", help="just this one")
    q.add_argument("--source", type=Path, help="override the source directory")
    q.add_argument("--all", action="store_true",
                   help="send everything, not only what changed")
    q.set_defaults(func=cmd_export_run)

    p = sub.add_parser("upload", help="send the readings to a weather service")
    upload_sub = p.add_subparsers(dest="upload_command", required=True)

    q = upload_sub.add_parser("list", help="what is available and configured")
    add_common(q)
    q.set_defaults(func=cmd_upload_list)

    q = upload_sub.add_parser("check", help="ask the service, publish nothing")
    add_common(q)
    q.add_argument("name", nargs="?", help="just this one")
    q.set_defaults(func=cmd_upload_check)

    q = upload_sub.add_parser(
        "compare", help="count the archive against an InfluxDB upload")
    add_common(q)
    q.add_argument("name", nargs="?", help="just this one")
    q.add_argument("--days", type=int, default=30,
                   help="how far back to look (default: 30)")
    q.add_argument("--window", type=int, default=86400,
                   help="the window to count in, in seconds (default: a day)")
    q.add_argument("--read-token", default=None,
                   help="a token that reads. The upload's own is a write "
                        "token where the advice on the page was followed, "
                        "and a write token cannot count.")
    q.set_defaults(func=cmd_upload_compare)

    q = upload_sub.add_parser("run", help="send now")
    add_common(q)
    q.add_argument("name", nargs="?", help="just this one")
    q.add_argument("--again", action="store_true",
                   help="forget how far it got, so the last records go again")
    q.set_defaults(func=cmd_upload_run)

    p = sub.add_parser("forecast", help="what is coming, from somebody who knows")
    forecast_sub = p.add_subparsers(dest="forecast_command", required=True)

    q = forecast_sub.add_parser("list", help="what is available and configured")
    add_common(q)
    q.set_defaults(func=cmd_forecast_list)

    q = forecast_sub.add_parser(
        "check", help="fetch once and say what came back, storing nothing")
    add_common(q)
    q.add_argument("name", nargs="?", help="just this one")
    q.set_defaults(func=cmd_forecast_check)

    q = forecast_sub.add_parser("run", help="fetch now and store")
    add_common(q)
    q.add_argument("name", nargs="?", help="just this one")
    q.set_defaults(func=cmd_forecast_run)

    q = forecast_sub.add_parser("show", help="print what is stored")
    add_common(q)
    q.add_argument("--hours", type=int, default=0,
                   help="also print this many hours")
    q.set_defaults(func=cmd_forecast_show)

    p = sub.add_parser("web", help="serve what the feeds produced")
    add_common(p)
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--allow", default=None,
                   help="which addresses get an answer (default: private)")
    p.set_defaults(func=cmd_web)

    p = sub.add_parser("plots", help="the charts, and the JSON behind them")
    plots_sub = p.add_subparsers(dest="plots_command", required=True)

    q = plots_sub.add_parser("list", help="what charts exist")
    add_common(q)
    q.add_argument("--plots", default=None, help="a different plots.toml")
    q.set_defaults(func=cmd_plots_list)

    q = plots_sub.add_parser("show", help="one chart, in full")
    add_common(q)
    q.add_argument("name")
    q.add_argument("--plots", default=None)
    q.set_defaults(func=cmd_plots_show)

    q = plots_sub.add_parser(
        "import", help="take the charts out of a WeeWX skin")
    add_common(q)
    q.add_argument("source", help="a skin.conf holding an [ImageGenerator]")
    q.add_argument("--write", action="store_true",
                   help="keep them; without this it only says what it found")
    q.add_argument("--replace", action="store_true",
                   help="start from nothing instead of adding to what is there")
    q.add_argument("--plots", default=None)
    q.set_defaults(func=cmd_plots_import)

    q = plots_sub.add_parser("remove", help="delete a chart")
    add_common(q)
    q.add_argument("name")
    q.add_argument("--plots", default=None)
    q.set_defaults(func=cmd_plots_remove)

    q = plots_sub.add_parser("run", help="write the JSON now")
    add_common(q)
    q.add_argument("--into", default=None, help="where to write it")
    q.add_argument("--no-page", dest="page", action="store_false",
                   help="skip the diagnostic page that draws it all")
    q.add_argument("--plots", default=None)
    q.set_defaults(func=cmd_plots_run)

    p = sub.add_parser("backup", help="copy the archive, safely, while it runs")
    add_common(p)
    p.add_argument("--into", type=Path, default=None,
                   help="where to put it (default: backups/ beside the "
                        "database)")
    p.add_argument("--keep", type=int, default=7,
                   help="how many to keep (default: 7, zero keeps all)")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("verify",
                       help="is it sound, and do the summaries follow?")
    add_common(p)
    p.add_argument("--days", type=int, default=0,
                   help="only the most recent days (default: all of them)")
    p.add_argument("--deep", action="store_true",
                   help="walk every index as well. Minutes on a large file.")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("vacuum", help="reclaim the space a deletion left")
    add_common(p)
    p.add_argument("--least", type=int, default=10,
                   help="skip unless this many MB would come back "
                        "(default: 10)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_vacuum)

    p = sub.add_parser("notify",
                       help="who hears about it when something stops")
    notify_sub = p.add_subparsers(dest="notify_command", required=True)

    q = notify_sub.add_parser("list",
                              help="what is configured, and what could be")
    add_common(q)
    q.set_defaults(func=cmd_notify_list)

    q = notify_sub.add_parser("check", help="send a test message")
    add_common(q)
    q.add_argument("name", nargs="?", help="just this one")
    q.set_defaults(func=cmd_notify_check)

    q = notify_sub.add_parser("status",
                              help="what is wrong right now, told or not")
    add_common(q)
    q.set_defaults(func=cmd_notify_status)

    p = sub.add_parser("quality", help="calibration and limits")
    quality_sub = p.add_subparsers(dest="quality_command", required=True)

    q = quality_sub.add_parser(
        "suggest", help="rules worked out from what this station recorded")
    add_common(q)
    q.add_argument("--days", type=int, default=365,
                   help="how much history to look at (default: a year)")
    q.add_argument("--units", default=None,
                   help="what system to write the figures in "
                        "(metricwx, metric, us; default: metricwx)")
    q.add_argument("--fields", default=None,
                   help="only these readings, comma separated")
    q.set_defaults(func=cmd_quality_suggest)

    q = quality_sub.add_parser(
        "check", help="what the configured rules would refuse")
    add_common(q)
    q.add_argument("--days", type=int, default=30,
                   help="how much history to run them over (default: 30)")
    q.set_defaults(func=cmd_quality_check)

    p = sub.add_parser("grafana", help="dashboards for the InfluxDB uploads")
    grafana_sub = p.add_subparsers(dest="grafana_command", required=True)

    q = grafana_sub.add_parser("list", help="what would be provisioned")
    add_common(q)
    q.add_argument("--plots", default=None, help="a different plots.toml")
    q.add_argument("--language", default=None,
                   help="write the dashboards in this language instead of "
                        "the configured one, so the same station can be "
                        "published twice")
    q.set_defaults(func=cmd_grafana_list)

    q = grafana_sub.add_parser(
        "provision", help="write the datasource and dashboard files")
    add_common(q)
    q.add_argument("--out", type=Path, default=None,
                   help="where to write them (default: grafana/ beside the "
                        "configuration file). The compose file mounts this "
                        "into Grafana.")
    q.add_argument("--read-token", default=None,
                   help="an InfluxDB token that only reads. Without one the "
                        "upload's own token is used, which can also write.")
    q.add_argument("--plots", default=None)
    q.add_argument("--language", default=None)
    q.set_defaults(func=cmd_grafana_provision)

    p = sub.add_parser("status", help="what is in the two databases")
    add_common(p)
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

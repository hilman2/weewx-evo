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
from pathlib import Path
from typing import Any

from . import config as config_file
from . import exports as export_registry
from . import feedrunner as feed_runner
from . import options as option_defs
from . import plots as plot_defs
from . import settings as settings_state
from . import uploads as upload_registry
from . import weewxconf
from .admin import Admin, AdminServer
from .archiver import Archiver
from .db.archive import ArchiveStore
from .db.live import LiveStore
from .derive import from_settings as deriver_from
from .exports import runner as export_runner
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


def _accepts(driver: Any, keyword: str) -> bool:
    """Whether a driver's constructor takes this keyword."""
    import inspect

    if driver is None:
        return False
    try:
        return keyword in inspect.signature(type(driver).__init__).parameters
    except (TypeError, ValueError):
        return False


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
    cfg = settings_for(args)
    live, archive = open_stores(args)
    return live, archive, Archiver(live, archive,
                                   interval_seconds=cfg.get("interval"),
                                   loop_hilo=cfg.get("loop_hilo"),
                                   sources=read_sources(cfg, args.sources),
                                   deriver=deriver_from(cfg))


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
    ingest = Ingest(live, token=cfg.get("token"),
                    default_driver=cfg.get("driver"),
                    access=access, limits=limits)
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

    try:
        http.serve_forever()
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        http.stop()
        if udp:
            udp.stop()
        live.close()
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    cfg = settings_for(args)
    live, archive, archiver = make_archiver(args)
    stopping = threading.Event()

    def handle(signum: int, frame: object) -> None:
        log.info("signal %s, finishing the current tick", signum)
        stopping.set()

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)

    log.info("archiving every %ds into %s", cfg.get("interval"),
             cfg.get("archive_db"))

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
        runner = export_runner.Runner(scheduled)
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
    last_prune = 0.0
    try:
        while not stopping.is_set():
            try:
                n = archiver.process_due(grace=cfg.get("grace"))
                if n:
                    log.info("archived %d interval(s)", n)
                    if feeds is not None:
                        # Sets a flag and returns, like the exports. The work
                        # happens elsewhere.
                        feeds.record_written()
                    if runner is not None:
                        # Sets a flag and returns. Nothing about an upload
                        # happens on this thread.
                        runner.record_written()
                    if uploader is not None:
                        uploader.record_written()
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
        live.close()
        archive.close()
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
    archive = ArchiveStore(cfg.get("archive_db"), table_name=cfg.get("table"))
    archiver = Archiver(live, archive, interval_seconds=cfg.get("interval"),
                        loop_hilo=cfg.get("loop_hilo"),
                        sources=read_sources(cfg, args.sources),
                        deriver=deriver_from(cfg))
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
                    access=access, limits=limits)
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

    caught = archiver.catch_up()
    if caught:
        log.info("caught up %d interval(s) from the live table", caught)

    # The feeds. On their own thread for the same reason the exports are:
    # a hundred charts is most of a second, and a second here is a second the
    # archiver is not archiving. What they produce is a directory of files;
    # who moves it anywhere is an export's business.
    feeds = start_feeds(args, cfg)
    if feeds is not None:
        # Once at startup, so a restart does not leave yesterday's pages
        # up until the next record lands a minute later.
        feeds.record_written()


    # The local web server for whatever the feeds produced. Its own port:
    # the listener answers hardware behind a token and this answers browsers,
    # and one port for two audiences means the stricter rule has to lose.
    web = None
    if cfg.get("web.enabled"):
        site = site_from(cfg)
        web = WebServer(site, cfg.get("web.host"), cfg.get("web.port"),
                        access=Access.parse(cfg.get("web.allow")))
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
        runner = export_runner.Runner(scheduled)
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

    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())

    watcher = _Watcher(getattr(args, "config", None))
    # Set when a setting changed that only a fresh process can apply.
    # The supervisor brings it back: `restart: unless-stopped` in
    # compose, `Restart=always` in a unit file.
    restarting = False
    # Set when a setting changed that only a fresh process can apply. The
    # supervisor brings it back: `restart: unless-stopped` in compose,
    # `Restart=always` in a unit file.
    restarting = False
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
                    apply_live(args, cfg, web, runner, uploader)

                n = archiver.process_due(grace=cfg.get("grace"))
                if n:
                    log.info("archived %d interval(s)", n)
                    if feeds is not None:
                        # Sets a flag and returns, like the exports below. The
                        # work happens on their own thread.
                        feeds.record_written()
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
        if feeds is not None:
            feeds.stop()
        if runner is not None:
            runner.stop()
        if uploader is not None:
            uploader.stop()
        if web is not None:
            web.stop()
        http.stop()
        if admin_server:
            admin_server.stop()
        if udp:
            udp.stop()
        live.close()
        archive.close()
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


def cmd_rebuild(args: argparse.Namespace) -> int:
    live, archive, archiver = make_archiver(args)
    try:
        n = archiver.rebuild(args.start, args.stop)
        print(f"rebuilt {n} interval(s) and their days")
    finally:
        live.close()
        archive.close()
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
        groups = list(factory.options()) if hasattr(factory, "options") else []
        # A skin declares its own settings, and they belong on the page of
        # the feed that runs it -- there is no separate skin page, because a
        # skin is only ever configured through the feed it belongs to.
        if hasattr(factory, "skin_options"):
            groups += factory.skin_options(str(settings.get("skin") or ""),
                                           settings.get("skins_dir"))
        if not groups:
            continue
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
    token = args.token or cfg.get("admin.token")
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
    return factory(**settings)


def build_upload_schedule(args: argparse.Namespace, cfg: Settings) -> list:
    """What the uploads are, right now.

    They read the archive themselves rather than being handed a record: the
    components here talk through the database, and it is what makes a restart
    cost nothing and a catch-up possible at all.
    """
    configured = configured_uploads(args)
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

    def with_station(name: str, settings: dict) -> object:
        # CWOP needs a position and almost nobody wants to type it twice.
        # Filled in from the station rather than required, and only when the
        # upload did not say its own.
        if str(settings.get("kind", "")) == "cwop":
            settings.setdefault("latitude", cfg.get("station.latitude"))
            settings.setdefault("longitude", cfg.get("station.longitude"))
        return build_upload(name, settings)

    return upload_runner.build(configured, with_station, progress, records,
                               packets)


def apply_live(args: argparse.Namespace, cfg: Settings, web: Any,
               runner: Any, uploader: Any = None) -> None:
    """Apply a changed configuration to a running process.

    Everything that can be rebuilt in place, in one function. Scattering
    these across the loop is how three of them came to be missing: nothing
    listed what had to be nudged, so nothing said when one was forgotten.

    Anything that cannot be rebuilt here belongs marked `restart` in the
    schema, and the loop restarts the process for it.
    """
    if runner is not None:
        fresh = build_schedule(args, cfg)
        if _differs(fresh, runner):
            # An export added on the settings page joins the running set.
            runner.stop()
            runner.exports = fresh
            runner.start()
            log.info("%d export(s) running", len(fresh))

    if uploader is not None:
        fresh = build_upload_schedule(args, cfg)
        if _uploads_differ(fresh, uploader):
            # An upload added on the settings page joins the running set.
            uploader.replace(fresh)
            log.info("%d upload(s) running", len(fresh))

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
    before = [(s.name, str(s.source), getattr(s.export, "trigger", ""),
               s.feed) for s in (runner.exports if runner is not None else [])]
    after = [(s.name, str(s.source), getattr(s.export, "trigger", ""), s.feed)
             for s in fresh]
    return before != after


def build_schedule(args: argparse.Namespace, cfg: Settings) -> list:
    """What the exports are, right now.

    An export pointed at a feed has to be told where that feed writes, or it
    is left out at startup with "no feed and no directory set" -- which reads
    like the export is wrong when it is not.
    """
    where = feed_dirs(cfg, args)
    configured = {name: resolve_paths(args, settings)
                  for name, settings in configured_exports(args).items()}
    return export_runner.build(
        configured, build_export,
        lambda settings: export_registry.source_for(settings, where.get))


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


def build_export(name: str, settings: dict) -> object:
    """Make one export from its settings. Raises with a usable message."""
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
    if not site.feeds:
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
                       args.port or cfg.get("web.port"), access=access)
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
    return plot_defs.load(plots_path(args, cfg))


#: What a station gets when nothing has been configured. Named the same as
#: their kinds, so an existing file that says `feeds.json.units` keeps
#: meaning what it meant.
DEFAULT_FEEDS = {
    "json": {"kind": "json"},
    "diagnostic": {"kind": "diagnostic", "source": "json"},
}


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


def build_feeds(args: argparse.Namespace, cfg: Settings,
                charts: plot_defs.PlotSet) -> list:
    """The feeds this configuration asks for, in the order they run.

    Ordered by dependence: anything reading what another feed wrote runs
    after it. Today that is the diagnostic page, which draws whatever JSON is
    on disk, and the ordering is here rather than inside either of them.
    """

    where = feed_dirs(cfg, args)
    configured = configured_feeds(args)

    def rank(item: tuple[str, dict]) -> tuple[int, str]:
        # A feed that reads another one goes second.
        return (1 if item[1].get("source") in configured else 0, item[0])

    made: list = []
    for name, settings in sorted(configured.items(), key=rank):
        kind = str(settings.get("kind", "")).strip()
        if settings.get("enabled") is False:
            continue
        if kind == "json":
            made.append((name, _json_feed(cfg, name, charts, args),
                         where[name]))
        elif kind == "images":
            made.append((name, _image_feed(cfg, name, args), where[name]))
        elif kind == "cheetah":
            made.append((name, _cheetah_feed(cfg, name, args), where[name]))
        elif kind == "diagnostic":
            reads = str(settings.get("source") or "json")
            made.append((name, _diagnostic_feed(cfg, name,
                                                where.get(reads, where[name])),
                         where[name]))
        else:
            log.warning("feed %s is of kind %r, which nothing here knows how "
                        "to build; leaving it out", name, kind)
    return made


def _json_feed(cfg: Settings, name: str, charts: plot_defs.PlotSet,
               args: argparse.Namespace):
    from .feeds import jsongenerator

    return lambda reader: jsongenerator.from_settings(
        cfg, reader, load_plots(args, cfg), prefix=f"feeds.{name}")


def _image_feed(cfg: Settings, name: str, args: argparse.Namespace):
    from .feeds import imagegenerator

    return lambda reader: imagegenerator.from_settings(
        cfg, reader, load_plots(args, cfg), prefix=f"feeds.{name}")


def _cheetah_feed(cfg: Settings, name: str, args: argparse.Namespace):
    from .feeds import cheetah

    return lambda reader: cheetah.from_settings(
        cfg, reader, load_plots(args, cfg), prefix=f"feeds.{name}")


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
    if cfg.get("feeds.json.enabled") is False:
        log.info("the JSON feed is switched off, so no feeds are running")
        return None

    runner = feed_runner.Runner(build_feeds(args, cfg, charts),
                                archive_path=Path(cfg.get("archive_db")))
    runner.start()
    where = feed_dirs(cfg, args)
    log.info("%d chart(s) from %s, written to %s", len(charts),
             plots_path(args, cfg), where["json"])
    return runner


def cmd_status(args: argparse.Namespace) -> int:
    cfg = settings_for(args)
    live_path = Path(cfg.get("live_db"))
    archive_path = Path(cfg.get("archive_db"))
    live, archive = open_stores(args)
    try:
        first, last = live.span()
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
            "archive": {
                "path": str(archive_path),
                "records": archive.count(),
                "newest": archive.last_timestamp(),
                "columns": len(archive.schema.columns),
                "daily_tables": len(archive.schema.day_types),
                "summary_version": archive.schema.version,
                "size_mb": round(archive_path.stat().st_size / 1e6, 1),
            },
        }
        print(json.dumps(report, indent=2))
    finally:
        live.close()
        archive.close()
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
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("catchup", help="build every interval the live table covers")
    add_common(p)
    p.add_argument("--replace", action="store_true",
                   help="overwrite records that are already there")
    p.set_defaults(func=cmd_catchup)

    p = sub.add_parser("rebuild", help="work a time span out again")
    add_common(p)
    p.add_argument("start", type=int, help="unix timestamp, exclusive")
    p.add_argument("stop", type=int, help="unix timestamp, inclusive")
    p.set_defaults(func=cmd_rebuild)

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
    p.add_argument("--token", default=None,
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

    q = upload_sub.add_parser("run", help="send now")
    add_common(q)
    q.add_argument("name", nargs="?", help="just this one")
    q.add_argument("--again", action="store_true",
                   help="forget how far it got, so the last records go again")
    q.set_defaults(func=cmd_upload_run)

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

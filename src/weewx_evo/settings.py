"""Where a value actually comes from.

There are up to five places a setting can be, and without a stated order they
fight. This is the order, strongest first:

  1. **A command-line argument.** Somebody typed it just now, for this run.
  2. **The environment.** How a container is configured, and how a systemd
     unit overrides one thing without editing a file.
  3. **The configuration file.** What the admin page writes, and what a person
     edits. The normal place for a setting to live.
  4. **weewx.conf**, if one was named. The settings both systems share --
     latitude, altitude, the archive interval -- can go on living there, so
     changing the altitude in one place changes it for both.
  5. **The default** the component declared.

Every layer is optional and each one only covers what it actually says. A
value absent from the file is not "empty", it is "the layer below decides",
which is why the file the admin page writes contains only what has been set.

## One resolver, asked by everything

Nothing reads the file for itself. `Settings` is built once for the process
and passed around, so every component sees the same answer to the same
question at the same moment. That matters more than it sounds: with each
component resolving on its own, a file rewritten between two of them gives
two different configurations to one running system, and the resulting bug is
one nobody can reproduce.

Drivers get a `view()` -- their own corner of the settings and nothing else.
A driver has no business reading the upload token, and the way to make sure
of that is not to hand it over. Same reasoning as `ingest.state`: the narrow
thing, so the wide thing cannot be reached by accident.

## Why this is not a service

The next thought is a settings daemon, or a socket, that components query.
That would be a mistake here, and the reason is not effort:

  * The file already is what a daemon would be, minus the ways a daemon
    fails. It is written atomically, it survives restarts in the right order,
    it can be read with `cat` at three in the morning, and it cannot be down.
  * The processes that would query it -- listener, archiver -- already
    coordinate through the database and are deliberately unable to talk to
    each other. Adding a channel between them would undo the property that
    lets them be split across machines or run as one.
  * A station in a shed does not need another process that can fail to come
    back. It needs one fewer.

What a service would genuinely offer is settings changing without a restart,
and that needs no daemon: `reload()` rebuilds this object from the file, and
anything holding it sees the new values. What cannot be changed while running
says so on the admin page, which is honest about the difference rather than
pretending everything is live.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import config as config_file
from .options import Invalid, Schema

log = logging.getLogger(__name__)


#: Command-line names that differ from the setting they carry. Written out
#: rather than guessed at: `--archive` is a path and `archive_db` is a
#: setting, and a rule that turned one into the other would also turn
#: `--allow` into something.
ARGUMENT_NAMES = {
    "archive": "archive_db",
    "live": "live_db",
    "retention_days": None,   # a duration in days, handled below
    "raw_minutes": None,      # likewise, in minutes
}

#: Older environment variable names, with the factor that turns their unit
#: into the setting's. Kept working: a container that has been running for
#: months should not stop because a name got tidier, and the day somebody
#: renames a variable is the day they find out how many places used it.
ENV_ALIASES: dict[str, list[tuple[str, float]]] = {
    "live_db": [("WEEWX_EVO_LIVE", 1.0)],
    "archive_db": [("WEEWX_EVO_ARCHIVE", 1.0)],
    "retention": [("WEEWX_EVO_RETENTION_DAYS", 86400.0)],
    "raw_retention": [("WEEWX_EVO_RAW_MINUTES", 60.0)],
}


class Settings:
    """One resolved view of the configuration."""

    def __init__(self, schema: Schema, config: dict[str, Any] | None = None,
                 args: Any = None, weewx: dict[str, Any] | None = None,
                 prefix: str = "", path: str | Path | None = None) -> None:
        self.schema = schema
        self.config = config or {}
        self.args = args
        self.weewx = weewx or {}
        self.prefix = prefix
        self._path = Path(path) if path else None
        self._sources: dict[str, str] = {}
        #: What changed on the last reload. Empty until one happens. Per
        #: instance: as a class attribute every Settings in the process
        #: shared one list.
        self.changed: list[str] = []

    # -- resolution ------------------------------------------------------

    def get(self, name: str, default: Any = None) -> Any:
        """The value of one setting, and remember where it came from."""
        option = self.schema.option(name)

        raw, source = self._raw(name)
        if raw is None:
            self._sources[name] = "default"
            if option is None:
                return default
            return self._anchor(option, option.default, "default")

        self._sources[name] = source
        if option is None:
            return raw
        try:
            return self._anchor(option, option.parse(raw), source)
        except Invalid as exc:
            log.warning("%s (from %s): %s. Using the default instead.",
                        name, source, exc)
            return option.default

    def _anchor(self, option: Any, value: Any, source: str) -> Any:
        """A relative path from the file, against the file.

        Two readers of one setting were resolving it two different ways: the
        settings page against the configuration file, the service against
        whatever directory it was started in. So `archive_db = "weewx.sdb"`
        named two files, and the page offering to add a column added it to
        the one the service was not writing -- and said it had worked.

        The command line is the exception, and it is the obvious one: a path
        somebody just typed means the directory they typed it in.
        """
        if (option.kind != "path" or not value
                or source == "command line" or self._path is None):
            return value
        found = Path(str(value))
        if found.is_absolute():
            return value
        return str(self._path.parent / found)

    def _raw(self, name: str) -> tuple[Any, str]:
        # 1. the command line
        if self.args is not None:
            value = self._from_args(name)
            if value is not None:
                return value, "command line"

        # 2. the environment
        for env_name, scale in self._env_names(name):
            raw = os.environ.get(env_name)
            if raw:
                if scale != 1:
                    try:
                        return float(raw) * scale, f"${env_name}"
                    except ValueError:
                        log.warning("$%s is %r, which is not a number", env_name, raw)
                        continue
                return raw, f"${env_name}"

        # 3. the configuration file
        dotted = f"{self.prefix}.{name}" if self.prefix else name
        value = config_file.get(self.config, dotted)
        if value is not None:
            return value, "the configuration file"

        # 4. weewx.conf, for the settings both systems share
        if name in self.weewx:
            return self.weewx[name], "weewx.conf"

        return None, "default"

    def _env_names(self, name: str) -> list[tuple[str, float]]:
        """The environment variables that can carry this setting, best first.

        Each with the factor that turns its unit into the setting's. The
        aliases exist because names were given to environment variables before
        they were given to settings, and a running installation should not
        break because a name got tidier.
        """
        primary = "WEEWX_EVO_" + name.replace(".", "_").upper()
        return [(primary, 1.0), *ENV_ALIASES.get(name, [])]

    def _from_args(self, name: str) -> Any:
        """The command-line value, if one was actually given.

        Arguments default to None so that "not given" and "given the default"
        are different things. Without that, a default in argparse would beat
        the configuration file, and the admin page would appear to do nothing.
        """
        for argument, setting in ARGUMENT_NAMES.items():
            if setting == name:
                return getattr(self.args, argument, None)
        return getattr(self.args, name.replace(".", "_"), None)

    def source(self, name: str) -> str:
        """Where the last-read value of this setting came from."""
        return self._sources.get(name, "unknown")

    def all(self) -> dict[str, Any]:
        return {option.name: self.get(option.name) for _g, option in self.schema}

    # -- the narrow view -------------------------------------------------

    def view(self, prefix: str, schema: Schema) -> Settings:
        """One component's corner of the settings, and nothing else.

        A driver gets this rather than the whole thing. It can read what
        belongs to it and cannot reach the upload token, the database paths,
        or another driver's console list -- not because it is asked not to,
        but because it was never handed them.

        The same reasoning as `ingest.state`: give the narrow thing, and the
        wide thing cannot be reached by accident or on purpose.
        """
        return Settings(schema, config=self.config, args=None,
                        weewx={}, prefix=prefix)

    # -- reloading -------------------------------------------------------

    def reload(self, path: str | Path | None = None) -> bool:
        """Re-read the file. Returns whether anything actually changed.

        This is what a settings service would be for, without the service.
        Anything holding this object sees the new values; anything that
        latched a value at startup does not, which is why an option that
        cannot be changed while running is marked `restart` and the admin page
        says so.
        """
        if path is None:
            path = self._path
        # Cleared first. Leaving the previous answer standing means the next
        # caller asks "what changed" and is told about something from a
        # minute ago.
        self.changed = []
        if path is None:
            return False
        fresh = config_file.read(path)
        if fresh == self.config:
            return False
        before = {name: self.get(name) for name in
                  (o.name for _g, o in self.schema)}
        self.config = fresh
        self._path = Path(path)
        changed = [name for name, was in before.items() if self.get(name) != was]
        # Kept, because the caller needs to know *which*: some settings can be
        # applied while running and some cannot, and the difference is in the
        # schema rather than in anybody's memory.
        self.changed = changed
        if changed:
            log.info("configuration reloaded; changed: %s", ", ".join(changed))
        return bool(changed)

    def needs_restart(self) -> list[str]:
        """Which of the settings that just changed cannot be applied live.

        The schema already says so, one option at a time. Nothing else has to
        keep a list, and an option added tomorrow is covered by the same
        answer.
        """
        return [option.label for _group, option in self.schema
                if option.restart and option.name in self.changed]

    def explain(self, extra: Sequence[Any] = ()) -> list[str]:
        """One line per setting, saying what it is and where it came from.

        `extra` is the schemas that are not the core's -- one per driver,
        feed and export, because those are named instances and the core
        schema cannot know how many there are. Left out, the command shows
        two dozen settings and silently omits the forty a skin has, which
        reads as "there are no others".
        """
        rows: list[tuple[str, Any, str] | None] = [
            (option.name, option, "") for _group, option in self.schema]
        for schema in extra:
            found = [(f"{group.prefix}.{option.name}"
                      if group.prefix else option.name, option)
                     for group in getattr(schema, "groups", ())
                     for option in getattr(group, "options", ())]
            if not found:
                continue
            rows.append(None)
            rows.append(("", None, str(getattr(schema, "label", ""))))
            rows.extend((name, option, "") for name, option in found)

        # One column width for the whole listing. A feed's settings carry
        # their instance name and are half again as long as the core's, and
        # a fixed width puts every one of those lines out of true.
        width = max((len(name) for name, option, _ in
                     (r for r in rows if r) if option), default=22)
        lines = []
        for row in rows:
            if row is None:
                lines.append("")
                continue
            name, option, heading = row
            if option is None:
                lines.append(f"  {heading}")
                continue
            lines.append(self._line(option, name, width))
        return lines

    def _line(self, option: Any, name: str, width: int = 22) -> str:
        value = self.get(name)
        if value is None and name != option.name:
            # Not in the file, so what the schema says it would be.
            value = option.default
        shown = "(set)" if option.kind == "secret" and value else repr(value)
        return f"  {name:<{width}} {shown:<28} {self.source(name)}"


def load(schema: Schema, config_path: str | Path | None = None,
         args: Any = None, weewx_conf: str | Path | None = None,
         prefix: str = "") -> Settings:
    """Build a Settings from the places there are.

    A missing configuration file is not an error: a first start has nothing to
    read, and everything falls through to the defaults.
    """
    config = config_file.read(config_path) if config_path else {}

    shared: dict[str, Any] = {}
    if weewx_conf:
        from . import weewxconf

        try:
            imported = weewxconf.convert(weewxconf.read(weewx_conf))
            shared = imported.values
            log.info("weewx.conf at %s supplies %d setting(s) that are not set "
                     "here", weewx_conf, len(shared))
        except OSError as exc:
            log.warning("cannot read %s: %s", weewx_conf, exc)

    return Settings(schema, config=config, args=args, weewx=shared,
                    prefix=prefix, path=config_path)


# -- the one instance this process resolved ------------------------------

#: Here, and deliberately not in `cli.py`.
#:
#: `cli.py` is also `__main__`: the container runs `python -m
#: weewx_evo.cli`. A later `from .cli import _RESOLVED` then imports the
#: same file a *second* time under its package name, and that copy's
#: globals are empty forever. Everything that read them saw None and
#: quietly fell back to a default -- a dropdown listed the feeds that
#: ship instead of the ones configured, and an export aimed at a feed the
#: operator had named was refused at startup as one that did not exist.
#: Nothing anywhere said why. This module is only ever imported, so there
#: is one of it.
_RUNNING: Any = None
_RUNNING_ARGS: Any = None


def running() -> Any:
    """The settings this process resolved, or None before it has."""
    return _RUNNING


def running_args() -> Any:
    """The arguments this run was given. Which file, above all."""
    return _RUNNING_ARGS


def set_running(settings: Any, args: Any = None) -> None:
    global _RUNNING, _RUNNING_ARGS
    _RUNNING = settings
    _RUNNING_ARGS = args


def forget_running() -> None:
    """Start over. For a test that resolves twice in one process."""
    set_running(None, None)

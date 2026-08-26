"""Where a driver keeps what it has to remember.

A driver sometimes needs to remember something across restarts. weewx-ecowitt
remembers which console it adopted, because the alternative is that the next
console to upload becomes the station and two sensors end up in one column.

The obvious thing is to hand the driver the archive store. That is too much.
A driver would then be able to write records, alter the schema, or rebuild the
daily summaries -- none of which it has any business doing, and all of which
would be its bug to cause and ours to explain. The core owns the databases;
a driver produces packets.

So it gets this instead: get, set, delete, on strings. Four methods and no way
to reach anything else. What it is backed by is the core's decision -- the
archive's metadata table when there is one, a file when there is not -- and a
driver cannot tell the difference.

Keys are not namespaced automatically, and that is deliberate. weewx-ecowitt
writes `ecowitt_consoles`, the same key WeeWX writes, so a database moved
between the two keeps knowing which console it belongs to. Prefixing would
silently break that. Name your keys after your driver instead.

## What this does not do

It does not stop a driver reaching the archive anyway. A driver runs in this
process, and Python has no sandbox: `import sqlite3` and a path is all it
takes, and no interface can prevent code from going around it. WeeWX has the
same property, as does every in-process plugin system.

So this is a contract, not a cage. It makes the right thing the easy thing and
the wrong thing a deliberate, visible act -- a driver that opens the database
itself is doing so on purpose, in code somebody can read.

The enforcement, where it is wanted, is outside the process and the
architecture already allows it:

  * **Split the services.** `weewx-evo listen` opens the live database and
    nothing else; `weewx-evo archive` opens the archive and listens to nothing.
    Run them as different users and the archive is not writable by the process
    the drivers are in. This is the only real answer, and it costs a unit file.
  * **Take the rights away.** The listener needs the live database and a port.
    systemd's `ReadOnlyPaths`, a read-only bind mount, or simply a user without
    write permission on the archive make the question moot.
  * **Read the driver.** `weewx-evo driver install` says what a driver imports
    before you trust it. It is a hint, not a guarantee -- obfuscated code will
    not show up -- but it catches the honest mistake and the lazy shortcut.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class State(Protocol):
    """Small persistent storage for one driver."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


class NoState:
    """For a driver that is handed nothing. Remembers within the process only."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        self._values[key] = value

    def delete(self, key: str) -> None:
        self._values.pop(key, None)


class ArchiveState:
    """Backed by the archive's metadata table.

    The right place for it: the table sits with the readings the state protects,
    it is in every backup of them, and it moves with them. If the database is
    gone, so is the series that needed protecting.

    The store is held privately. A driver receives this object, not the store,
    and there is no way through.
    """

    def __init__(self, archive: object, driver: str = "?") -> None:
        self._archive = archive
        self._driver = driver

    def get(self, key: str) -> str | None:
        try:
            return self._archive.get_meta(key)  # type: ignore[attr-defined]
        except Exception:
            log.exception("driver %r could not read %r", self._driver, key)
            return None

    def set(self, key: str, value: str) -> None:
        try:
            self._archive.set_meta(key, str(value))  # type: ignore[attr-defined]
        except Exception:
            log.exception("driver %r could not write %r", self._driver, key)

    def delete(self, key: str) -> None:
        self.set(key, "")


class FileState:
    """Backed by a JSON file, for when there is no database to ask.

    Used by the listener running on its own, and by tests. Worse than the
    database -- a rebuilt machine or a directory nobody backed up loses it --
    but better than forgetting on every restart.
    """

    def __init__(self, path: str | Path, driver: str = "?") -> None:
        self.path = Path(path)
        self._driver = driver

    def _read(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, values: dict[str, str]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Written beside and moved, so an interrupted write cannot leave a
            # half-file that reads as "nothing remembered".
            partial = self.path.with_suffix(".part")
            partial.write_text(json.dumps(values, indent=2, sort_keys=True),
                               encoding="utf-8")
            partial.replace(self.path)
        except OSError:
            log.exception("driver %r could not save its state to %s",
                          self._driver, self.path)

    def get(self, key: str) -> str | None:
        return self._read().get(key)

    def set(self, key: str, value: str) -> None:
        values = self._read()
        values[key] = str(value)
        self._write(values)

    def delete(self, key: str) -> None:
        values = self._read()
        if values.pop(key, None) is not None:
            self._write(values)


def for_driver(name: str, archive: object | None = None,
               path: str | Path | None = None) -> State:
    """The state a driver should be given, best backing first."""
    if archive is not None:
        return ArchiveState(archive, name)
    if path is not None:
        return FileState(path, name)
    return NoState()

"""Narrow persistent state for a driver.

A third-party driver can need private protocol state across restarts. It gets
only get, set and delete on strings, never a database handle. This state does
not select a Sender, map a field or route a packet to an archive.

The production Listener uses a JSON file beside the live database and never
opens an archive. The built-in push drivers do not use this interface for
identity: every packet carries a canonical Sender ID, and each Place selects
the IDs it needs after the Listener has written them.

`ArchiveState` remains available to isolated library callers that deliberately
pass an archive to `for_driver`. That compatibility adapter is not used as a
channel between the Listener and Archiver.

Keys are not namespaced automatically. Name them after the driver so two
plugins cannot overwrite one another's state.

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
    """Compatibility adapter backed by an explicitly supplied archive.

    The store is held privately. A driver receives this object, not the store,
    and there is no way through. The production Listener does not use it.
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
    """Backed by a JSON file; used by the production Listener and tests."""

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
    """Build state from the archive or path explicitly supplied by the caller."""
    if archive is not None:
        return ArchiveState(archive, name)
    if path is not None:
        return FileState(path, name)
    return NoState()

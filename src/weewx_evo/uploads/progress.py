"""How far each upload has got.

One number per upload: the timestamp of the newest archive record the service
accepted. Everything a catch-up needs follows from it -- what to send is what
is in the archive after that.

Kept as one JSON file, not in the archive database, for the same reasons as
`exports/tracker.py`: it is a cache, it can be read with `cat`, and losing it
costs one duplicate post rather than a gap. A duplicate is the safe direction
here: every service in this package is idempotent for a given timestamp, and
Weather Underground in particular simply overwrites.

Why a file at all, rather than starting from the newest record each time: a
connection that drops for twenty minutes is ordinary on a domestic line, and
an upload that comes back and posts only the current reading has quietly
punched a hole in somebody's rainfall total for the month.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class Progress:
    """The last record each upload got accepted, by upload name."""

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._through: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for name, ts in (raw.get("through") or {}).items():
            try:
                self._through[str(name)] = int(ts)
            except (TypeError, ValueError):
                continue

    def through(self, name: str) -> int:
        """The newest record this upload has sent, or 0 for never."""
        with self._lock:
            return self._through.get(name, 0)

    def sent(self, name: str, ts: int) -> None:
        """Note that everything up to `ts` has been accepted.

        Never moves backwards. A service that accepts a backfilled record from
        an hour ago has not un-accepted the current one, and letting the
        number go down would send the whole hour again on the next turn.
        """
        if not ts:
            return
        with self._lock:
            if ts > self._through.get(name, 0):
                self._through[name] = int(ts)

    def rewind(self, name: str, ts: int) -> bool:
        """Send everything after `ts` again. Says whether it changed anything.

        `sent` deliberately never moves backwards, and this is the one caller
        that has to. After a rebuild the records in a span are different
        numbers under the same timestamps, and an upload that has already
        passed them will never look at them again -- so a store that holds a
        copy keeps the figures the rebuild was run to correct.

        Only for an upload that says it can take it. A service that files a
        second reading for a timestamp rather than replacing the first would
        end up with both.
        """
        with self._lock:
            if self._through.get(name, 0) <= int(ts):
                return False
            self._through[name] = int(ts)
            return True

    def forget(self, name: str) -> None:
        """Start this upload again from nothing."""
        with self._lock:
            self._through.pop(name, None)

    def save(self) -> None:
        with self._lock:
            payload = {"through": dict(self._through)}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            partial = self.path.with_suffix(".part")
            partial.write_text(json.dumps(payload, separators=(",", ":")),
                               encoding="utf-8")
            partial.replace(self.path)
        except OSError:
            log.warning("could not save %s; an upload may repeat its last "
                        "record after a restart", self.path)

    def __len__(self) -> int:
        return len(self._through)

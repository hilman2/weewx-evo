"""What each export last did, where the settings page can read it.

An export to a directory on this machine can be dated by looking at the
directory: the newest file in it is when something last went out. An FTP or
rsync export publishes somewhere this process cannot look, so the page said
"not recorded here" -- honest, and no use at all to somebody asking whether
their upload is working.

The runner knows. It knows how many files went, how long it took and what the
host said if it refused. But the settings page is a different process, so the
answer has to be written down somewhere both can reach.

**The live database**, because that is already the one channel between the
parts of this program: the listener and the archiver coordinate through it and
nothing else, and the settings page opens it read-only to say when a station
was last heard from. One more row in `live_metadata` costs nothing and needs
no new file, no new directory and no new thing to configure.

What is stored is one line of JSON per export, replaced each run:

    {"when": 1787…, "ok": true, "sent": 9, "skipped": 33,
     "bytes": 943210, "seconds": 3.2, "note": "", "error": ""}

**Not a history.** How the last run went is what somebody wants to see, and a
growing log of every run in a database meant for a day of packets would be a
table nobody prunes. The log has the history.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

#: Under one prefix, so a name cannot collide with anything else kept here.
PREFIX = "export:"


def key(name: str) -> str:
    return f"{PREFIX}{name}"


def write(store: Any, name: str, result: Any = None,
          error: str = "", when: float | None = None) -> None:
    """Note how one run went. Never raises.

    Never raises, and that is deliberate: this is a note about an upload, and
    a database that will not take it is not a reason to stop uploading.
    """
    if store is None:
        return
    entry = {
        "when": int(when if when is not None else time.time()),
        "ok": not error and not (result.failures if result else []),
        "error": error[:300],
    }
    if result is not None:
        entry.update({
            "sent": int(getattr(result, "sent", 0)),
            "skipped": int(getattr(result, "skipped", 0)),
            "deleted": int(getattr(result, "deleted", 0)),
            "bytes": int(getattr(result, "bytes", 0)),
            "seconds": round(float(getattr(result, "seconds", 0.0)), 2),
            "note": str(getattr(result, "note", "") or "")[:200],
            # The first one is enough to act on, and the whole list of a
            # site's worth of failures does not belong in a metadata row.
            "failed": [name for name, _why in
                       (getattr(result, "failures", None) or [])][:5],
        })
    try:
        store.set_meta(key(name), json.dumps(entry, separators=(",", ":")))
    except Exception:
        log.debug("could not record how %s went", name, exc_info=True)


def read(store: Any, name: str) -> dict | None:
    """The last run of one export, or None if it has never run here."""
    if store is None:
        return None
    try:
        raw = store.get_meta(key(name))
    except Exception:
        log.debug("could not read the record for %s", name, exc_info=True)
        return None
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def summary(entry: dict | None) -> str:
    """One line for the page, in the words the log uses.

    The same shape as `Sent.summary()` on purpose: somebody comparing the
    page against the log should not have to translate between them.
    """
    if not entry:
        return ""
    if entry.get("error"):
        return str(entry["error"])
    parts = [f"{entry.get('sent', 0)} sent"]
    if entry.get("skipped"):
        parts.append(f"{entry['skipped']} unchanged")
    if entry.get("deleted"):
        parts.append(f"{entry['deleted']} removed")
    if entry.get("failed"):
        parts.append(f"{len(entry['failed'])} failed")
    return ", ".join(parts)

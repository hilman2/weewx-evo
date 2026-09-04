"""What add-ons exist, and which of them reads what turned up.

The core ships no driver. A fresh installation is a listener with a token and
nothing that can read a protocol, so the first thing that happens is an
upload arriving that nothing understands -- and the operator is left with a
log line and a list of repositories to compare it against.

This is the other end of that. `ingest/listener.py` keeps what arrived (see
`UNREAD` there); this says which add-on reads it.

## The core learns no protocol from this

The patterns are in the catalogue, not here. `plugins.toml` in
`weewx-evo/weewx-evo-plugins` carries a `detects` block per driver, read off
that protocol's own `claims()`, and this file does string comparison. Putting
them here would give the core back the protocol knowledge that moving the
drivers out was for.

    body      every one of these must appear
    not_body  none of these may appear
    path      any one of these, as a substring of the upload path

## Offline is a real state, not an error

A station on a network with no way out cannot fetch this, and that is the
one case where "install an add-on" has to work anyway: `weewx-evo driver
install` takes a local path. So a fetch that fails is not an error and not a
retry loop -- it leaves whatever was cached, and the page says the list may
be out of date rather than saying nothing.

The cache is a file beside the configuration. It is not authoritative and
nothing but this reads it: at worst it is a stale list of names, and the
thing it is compared against is on GitHub.
"""

from __future__ import annotations

import json
import logging
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Where the list lives. The raw file rather than the API: no token, no rate
#: limit worth worrying about, and what comes back is the file itself.
URL = ("https://raw.githubusercontent.com/weewx-evo/weewx-evo-plugins"
       "/main/plugins.toml")

FILENAME = "plugins.cache.toml"

#: How long a cached copy is used before this bothers to fetch again. A day:
#: the list changes when somebody publishes an add-on, which is not often,
#: and a station that asks GitHub every hour for a file that rarely moves is
#: rude for no gain.
STALE_AFTER = 86400

#: Long enough for a slow link, short enough that a settings page does not
#: sit on it. Nothing here is worth making somebody wait for.
TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class Plugin:
    """One entry of the catalogue."""

    name: str
    kind: str = ""
    provides: str = ""
    summary: str = ""
    repository: str = ""
    #: Which branch, tag or commit to install. Empty means the default
    #: branch. A catalogue entry that pins one is saying "this is the version
    #: that was tested", which `tested` claims and cannot enforce.
    ref: str = ""
    #: What the package's own pyproject declares, so an installation can tell
    #: whether what it has is current. In this file rather than fetched per
    #: add-on: it is pulled once a day anyway, which makes the check a string
    #: comparison instead of one request per package.
    version: str = ""
    licence: str = ""
    tested: str = ""
    author: str = ""
    detects: dict[str, Any] = field(default_factory=dict)

    def reads(self, body: str, path: str = "") -> int:
        """How well this add-on matches that upload. 0 is not at all.

        2 for the body, 1 for the path alone, and the difference decides the
        order rather than the answer -- see `matching`.

        A path on its own counts because the protocols that cannot be told to
        use another one are recognised by it: a Fine Offset console posts to
        `/weatherstation/updateweatherstation.php` and has no field to change
        that. But it is the weaker signal, and this is the case that shows
        why: an Acurite bridge is pointed at that same path with DNS, so its
        upload matches Weather Underground on the path and Acurite on the
        body. The body is the one that was actually sent.
        """
        rules = self.detects or {}
        if not rules:
            return 0
        wanted = [str(one) for one in rules.get("body") or ()]
        unwanted = [str(one) for one in rules.get("not_body") or ()]
        paths = [str(one) for one in rules.get("path") or ()]

        if any(one in body for one in unwanted):
            return 0
        if wanted and all(one in body for one in wanted):
            return 2
        return 1 if paths and any(one in path for one in paths) else 0


def matching(plugins: list[Plugin], body: str, path: str = "") -> list[Plugin]:
    """Every add-on that could read this, the strongest match first.

    Every, and not the best one. An Ecowitt custom upload and an Ambient one
    both carry a PASSKEY, and `not_body` separates those two -- but the next
    pair may not be separable in the bytes that were kept. Offering both and
    saying so beats installing the wrong one with nothing to say why.

    Ordered so that the one which matched on what was *sent* comes before one
    that matched only on where it was sent, and stably within that: the same
    upload has to produce the same list on two installations, or the same
    hardware gets different advice for no reason anybody can see.
    """
    scored = [(one.reads(body, path), n, one)
              for n, one in enumerate(plugins)]
    return [one for score, _n, one in
            sorted((s for s in scored if s[0]), key=lambda s: (-s[0], s[1]))]


def parse(text: str) -> list[Plugin]:
    """The catalogue out of its TOML. Empty where it cannot be read.

    Empty rather than raising: this is a convenience, and a settings page
    that will not render because GitHub served something odd is worse than
    one with no suggestions on it.
    """
    try:
        found = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        log.warning("the plugin catalogue is not readable TOML; ignoring it")
        return []

    out = []
    for entry in found.get("plugin") or ():
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        known = {name: entry.get(name, "") for name in
                 ("name", "kind", "provides", "summary", "repository",
                  "licence", "tested", "author", "ref", "version")}
        detects = entry.get("detects")
        out.append(Plugin(**{k: str(v) for k, v in known.items()},
                          detects=detects if isinstance(detects, dict) else {}))
    return out


def cached(where: Path) -> tuple[list[Plugin], float]:
    """What was last fetched, and when. Empty and 0 if there is nothing."""
    path = where / FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return parse(str(raw.get("text") or "")), float(raw.get("when") or 0)
    except (OSError, ValueError):
        return [], 0.0


def fetch(where: Path, url: str = "", timeout: float = TIMEOUT,
          force: bool = False) -> list[Plugin]:
    """The catalogue, from the network or from the last copy of it.

    Never raises and never blocks for long. A station with no way out keeps
    whatever it had, which may be nothing, and that is a supported state:
    `weewx-evo driver install` takes a local file.
    """
    have, when = cached(where)
    if have and not force and time.time() - when < STALE_AFTER:
        return have

    # Read here rather than bound as a default: a default is evaluated once,
    # when this module is imported, so nothing could point this anywhere else
    # afterwards -- including a test measuring what happens when the address
    # cannot be reached, which is the one behaviour that must not be assumed.
    url = url or URL
    try:
        request = urllib.request.Request(  # noqa: S310 - a constant https URL
            url, headers={"Accept": "text/plain"})
        with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
            text = answer.read().decode("utf-8", "replace")
    except Exception as exc:
        # Every way this fails is somebody else's network: no route, DNS,
        # a captive portal, GitHub being down. None of them is worth more
        # than a line, and none of them is a reason to have no page.
        log.info("could not refresh the plugin catalogue (%s); "
                 "using the %s copy", exc, "cached" if have else "empty")
        return have

    found = parse(text)
    if not found:
        # Fetched, and it was not a catalogue. Keep what worked before
        # rather than replacing it with the thing that did not parse.
        return have
    try:
        (where / FILENAME).write_text(
            json.dumps({"when": time.time(), "text": text}), encoding="utf-8")
    except OSError:
        log.debug("could not cache the plugin catalogue", exc_info=True)
    return found

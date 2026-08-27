"""Live readings on a page that is published somewhere else.

A site pushed to a web host over FTP shows readings as old as the last upload.
Making them live the usual way means an MQTT broker at the station, a port
forwarded through the router, and a certificate -- because a page served over
https cannot open an unencrypted websocket, and that certificate has to be on
a domain resolving to a home connection, and renewed. Three things to keep
working on somebody else's network.

This is one thing, and it needs nothing opened:

    weewx-evo  --POST-->  live.php  --writes-->  live.json  --read by--> page

`live.php` goes up with every export that has this switched on. The station
posts its current readings to it every few seconds; it writes them to a file
beside itself; the page reads that file. The connection is outbound, exactly
like the upload that put the pages there in the first place.

**Every web host runs PHP.** That is what the whole approach rests on: shared
hosting where FTP is the only way in still runs PHP, and has for twenty years.

**PHP runs when the station writes, not when somebody reads.** Six times a
minute rather than once per visitor -- the page fetches a static file. A
hundred people watching a storm cost nothing.

## The token

Derived, not typed. It is the SHA-256 of the station's upload token with a
fixed context string, cut to 32 characters, and it is written into
`live.token` beside `live.php` on every export.

Derived rather than stored because there is then nothing to lose, nothing to
migrate and nothing to forget: the same station always computes the same
token. And derived rather than *used directly* because the upload token is
the thing standing between the open internet and the measurement series --
this one ends up in a file on somebody else's web host, and it must not be
possible to work backwards from it.

If the upload token is ever changed, the derived one changes with it and the
next export writes the new one. Which is the right behaviour and worth
stating: nothing has to be updated by hand in two places.

## What is not here

No PHP beyond writing one file. It takes no path, no filename and no
directory from the request, because that is the mistake this kind of file
exists to make.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)

#: The file the station posts to, and the one the page reads.
SCRIPT = "live.php"
#: Not a password: the name of the file one is written into.
TOKEN_FILE = "live.token"  # noqa: S105
DATA_FILE = "live.json"
#: How old a reading may be before a page should say so rather than show it
#: as now. Written into the document, so the page does not have to be
#: configured too. Kept the same as the `STALE_AFTER` in `live.php`: the two
#: routes into that file must not disagree about when a reading goes stale,
#: or the same station reads live on one host and stale on another.
STALE_AFTER = 300

#: Mixed into the hash so the derived token cannot be confused with the
#: upload token itself, nor with anything else derived from it later.
CONTEXT = "weewx-evo/live-push/v1"


def token_for(upload_token: str) -> str:
    """The token for `live.php`, derived from the station's upload token.

    Same station, same token, always -- so there is nothing to store, nothing
    to migrate and nothing to lose. A hash rather than the token itself
    because this one is written to a file on somebody else's web host, and
    the upload token is what stands between the open internet and the
    measurement series.
    """
    if not upload_token:
        return ""
    digest = hashlib.sha256(f"{CONTEXT}:{upload_token}".encode())
    return digest.hexdigest()[:32]


def script() -> str:
    """The PHP, as it ships."""
    return (Path(__file__).parent / SCRIPT).read_text(encoding="utf-8")


def install(directory: Path, upload_token: str) -> list[Path]:
    """Put `live.php` and its token into a directory about to be exported.

    Returns what it wrote or refreshed, so an export can send those along
    with everything else -- and so a tracker that only sends what changed
    does not send them again every five minutes.

    Written into the feed's own output directory rather than handed to the
    export separately: the directory is the whole interface between a feed
    and an export, and putting these anywhere else would be a second one.
    """
    directory = Path(directory)
    secret = token_for(upload_token)
    if not secret:
        log.warning("live.php was not installed: the station has no upload "
                    "token to derive one from.")
        return []

    written = []
    directory.mkdir(parents=True, exist_ok=True)

    php = directory / SCRIPT
    wanted = script()
    # Only when it differs. Rewriting an identical file every five minutes
    # would change its timestamp, and an export comparing by timestamp would
    # send it every time.
    if not php.exists() or php.read_text(encoding="utf-8") != wanted:
        php.write_text(wanted, encoding="utf-8", newline="\n")
        written.append(php)

    token = directory / TOKEN_FILE
    if not token.exists() or token.read_text(encoding="utf-8").strip() != secret:
        token.write_text(secret + "\n", encoding="utf-8", newline="\n")
        written.append(token)
        log.info("live.php's token changed; the next export carries it")

    return written


def url_for(base: str) -> str:
    """Where the station should post, given where the pages are served.

    A convenience for the settings page, which knows the site's address and
    can then fill the upload's own in rather than asking for it twice.
    """
    base = (base or "").rstrip("/")
    return f"{base}/{SCRIPT}" if base else ""

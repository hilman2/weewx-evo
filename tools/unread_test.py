#!/usr/bin/env python3
"""An upload with the right token that nothing can read.

While the protocols shipped with the core this was survivable: a missing
driver meant somebody had mistyped a path, and a log line was enough. With
the drivers installed one at a time it is the ordinary first-run state --
console set up, token right, and nothing on any page.

So it is kept as a sighting: what arrived, from where, and enough of the body
that a catalogue can say which add-on reads it. What this measures is that
the sighting appears, that the console is not treated differently for it, and
that a wrong token still gets nothing at all.

    python tools/unread_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo.db.live import LiveStore  # noqa: E402
from weewx_evo.ingest import drivers  # noqa: E402
from weewx_evo.ingest.listener import UNREAD, UNREAD_BYTES, Ingest  # noqa: E402
from weewx_evo.ingest.sightings import Sightings  # noqa: E402

failures = 0

#: A real Ecowitt custom upload, which is what a station set up against an
#: installation with no Ecowitt add-on actually sends.
ECOWITT = (b"PASSKEY=34F5A1B2C3D4E5F6&stationtype=GW2000A_V3.1.5"
           b"&dateutc=2026-09-04+10:00:00&tempf=59.7&humidity=91"
           b"&baromrelin=29.92&windspeedmph=1.34&model=GW2000A")


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def an_ingest(work: Path, token: str | None = None) -> tuple[Ingest, LiveStore]:
    live = LiveStore(work / "live.sdb", interval_seconds=300)
    registry = drivers.Registry()
    # Nothing registered at all: the state a fresh installation is in once
    # the drivers are add-ons.
    registry._loaded = True
    return Ingest(live, token=token, registry=registry,
                  sightings=Sightings(live)), live


def it_is_seen_rather_than_only_logged() -> None:
    print("\nan upload nothing can read")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        ingest, live = an_ingest(work, token="abcdefghij123456")
        try:
            stored, why, _answer = ingest.submit(
                ECOWITT, "/abcdefghij123456/ecowitt/", "192.168.1.44")
            check("nothing was stored", stored, 0)
            check("and it says why", "no driver" in why, True)

            ingest.sightings.flush(force=True)
            seen = ingest.sightings.waiting()
            # Returning rather than indexing into an empty list: with the
            # sighting gone this should read as five failed checks, not as
            # one failure and a traceback that hides the other four.
            if not check("but it was seen", len(seen), 1):
                return
            one = seen[0]
            check("under a name no driver can collide with", one.driver, UNREAD)
            check("keyed on the path it came in on",
                  one.identity, "/abcdefghij123456/ecowitt/")
            check("with where it came from", one.peer, "192.168.1.44")

            # The point of keeping the body: something that knows the
            # protocols can recognise it. The core does not, and must not.
            opening = one.fields[0] if one.fields else ""
            check("and enough of the body to be recognised",
                  opening.startswith("PASSKEY="), True)
            check("capped", len(opening) <= UNREAD_BYTES, True)
        finally:
            live.close()


def a_second_upload_does_not_make_a_second_sighting() -> None:
    """A console uploads every sixteen seconds. This is one line, not 5400."""
    print("\nthe same console, again and again")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        ingest, live = an_ingest(work)
        try:
            for _ in range(5):
                ingest.submit(ECOWITT, "/ecowitt/", "192.168.1.44")
            ingest.sightings.flush(force=True)
            seen = ingest.sightings.waiting()
            check("one sighting", len(seen), 1)
            check("counting what arrived", seen[0].packets, 5)

            # A different path is different hardware as far as anything here
            # can tell: nothing parsed the body, so there is no serial number
            # to key on and the path is all there is.
            ingest.submit(b"ID=x&action=updateraw&tempf=41",
                          "/wunderground/", "192.168.1.55")
            ingest.sightings.flush(force=True)
            check("a different endpoint is a different one",
                  len(ingest.sightings.waiting()), 2)
        finally:
            live.close()


def the_console_is_told_the_same_thing_as_before() -> None:
    """A sighting is a convenience. It must not change the exchange.

    Hardware that gets an error stops uploading, and some of it backs off for
    an hour. Whatever this end does about a missing driver, the console has
    to hear what it heard before.
    """
    print("\nwhat the console hears")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        ingest, live = an_ingest(work)
        try:
            _stored, _why, answer = ingest.submit(ECOWITT, "/ecowitt/", "1.2.3.4")
            check("the default response, unchanged",
                  answer, drivers.DEFAULT_RESPONSE)
        finally:
            live.close()


def a_wrong_token_is_still_nothing() -> None:
    """The door is not opened by this.

    A sighting for every refused upload would be a list somebody could fill
    from the internet, and it would confirm that there is something here to
    guess at. The token is checked first and this is after it.
    """
    print("\nan upload without the token")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        ingest, live = an_ingest(work, token="abcdefghij123456")
        try:
            stored, why, _answer = ingest.submit(
                ECOWITT, "/wrong-token/ecowitt/", "8.8.8.8")
            check("refused", (stored, why), (0, "unauthorised"))
            ingest.sightings.flush(force=True)
            check("and nothing was recorded about it",
                  ingest.sightings.waiting(), [])
        finally:
            live.close()


def main() -> int:
    it_is_seen_rather_than_only_logged()
    a_second_upload_does_not_make_a_second_sighting()
    the_console_is_told_the_same_thing_as_before()
    a_wrong_token_is_still_nothing()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("an upload nothing reads is visible, and changes nothing else")
    return 0


if __name__ == "__main__":
    sys.exit(main())

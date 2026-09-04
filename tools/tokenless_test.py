#!/usr/bin/env python3
"""Hardware that cannot carry a token, and everything that still needs one.

An Acurite bridge and a LaCrosse gateway post to an address burned into their
firmware and are pointed here with a DNS entry. Neither protocol has a path to
put a token in, and neither has a password field. Measured before this
existed: both were refused, and because a refusal counts against the
wrong-token limit, a bridge uploading every eighteen seconds locked itself out
in under two minutes and stayed out.

So the door opens for exactly them, and the interesting half of this file is
everything it must *not* open for. The three conditions each get a test that
fails when it is removed:

    the network   a DNS redirect does not reach out of the local one
    a claim       a driver recognising it, never the default fallback
    no secret     said by the driver, so an Ecowitt cannot skip its token by
                  leaving it out of the path

The drivers here are made up rather than the installed ones. What is being
measured is that the core asks and does not know: it reads `Setup.secret` and
compares nothing of its own.

    python tools/tokenless_test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo.db.live import LiveStore, Packet  # noqa: E402
from weewx_evo.ingest import drivers  # noqa: E402
from weewx_evo.ingest.listener import HttpListener, Ingest  # noqa: E402
from weewx_evo.netaccess import Access  # noqa: E402
from weewx_evo.ratelimit import Limits  # noqa: E402

TOKEN = "s3cr3t-upload-token"

#: A console pointed here with DNS. Its marker is in the body because that is
#: the only thing it has: the path is its manufacturer's and it sends no name
#: anybody chose.
BRIDGE = b"id=24C86E5B&mt=5N1x31&windspeedmph=9&battery=normal"
#: The same shape of upload from hardware whose path is the operator's to
#: choose, so a token belongs in it.
TELLABLE = b"MYKEY=34F5&model=X1&tempf=59.7"

failures = 0


def check(what: str, got: object, want: object) -> None:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1


class _Bridge(drivers.BaseDriver):
    """A driver for hardware that can present nothing at all."""

    def claims(self, body: bytes, meta: dict) -> float:
        return 1.0 if b"&mt=" in body else 0.0

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        return [Packet(dateTime=meta.get("received", 0), usUnits=1,
                       source="bridge", identity="24C86E5B",
                       driver="bridge", data={"windSpeed": 9.0})]

    def setup(self) -> drivers.Setup:
        # Empty `secret` is the whole statement: this hardware has no field
        # for one. `fields` is empty for the same reason -- it cannot be told
        # where to post either.
        return drivers.Setup(label="Bridge", hardware="a bridge", secret="")


class _Console(drivers.BaseDriver):
    """A driver for hardware whose upload path is the operator's to choose."""

    def claims(self, body: bytes, meta: dict) -> float:
        return 1.0 if b"MYKEY=" in body else 0.0

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        return [Packet(dateTime=meta.get("received", 0), usUnits=1,
                       source="console", identity="34F5",
                       driver="console", data={"outTemp": 59.7})]

    def setup(self) -> drivers.Setup:
        return drivers.Setup(label="Console", hardware="a console",
                             fields=(("Path", "%(path)s"),), secret="path")


class _Quiet(drivers.BaseDriver):
    """Says nothing about itself, which is most drivers written elsewhere."""

    def claims(self, body: bytes, meta: dict) -> float:
        return 1.0 if b"QUIET" in body else 0.0

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        return [Packet(dateTime=meta.get("received", 0), usUnits=1,
                       source="quiet", identity="q", driver="quiet",
                       data={"outTemp": 1.0})]


def _registry() -> drivers.Registry:
    registry = drivers.Registry()
    registry.register("bridge", _Bridge())
    registry.register("console", _Console())
    registry.register("quiet", _Quiet())
    # Stop `load()` reaching for entry points: this measures these three.
    registry._loaded = True
    return registry


def _ingest(where: Path, **kw: object) -> tuple[Ingest, LiveStore]:
    live = LiveStore(where / "live.sdb")
    limits = kw.pop("limits", None) or Limits(rate=100, failures=5)
    return Ingest(live, token=TOKEN, registry=_registry(),
                  access=Access.parse("any"), limits=limits,
                  default_driver="quiet", **kw), live


def a_bridge_gets_in_and_a_console_does_not() -> None:
    """The two halves of the rule, on the same listener in the same second."""
    print("\nwith a token set, and neither upload carrying one")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        ingest, live = _ingest(Path(raw))
        stored, why, _ = ingest.submit(BRIDGE, "/weatherstation/update.php",
                                       peer="192.168.1.44")
        check("a bridge on the local network", (stored, why), (1, "ok"))

        stored, why, _ = ingest.submit(TELLABLE, "/data/report/",
                                       peer="192.168.1.45")
        # This is the one that matters. Hardware that *can* hold a token does
        # not get to skip it by leaving it out of the path.
        check("a console that could have carried one", (stored, why),
              (0, "unauthorised"))

        stored, why, _ = ingest.submit(TELLABLE, f"/{TOKEN}/console/",
                                       peer="192.168.1.45")
        check("and the same console with its token", (stored, why), (1, "ok"))
        live.close()


def outside_the_network_it_is_refused() -> None:
    """A DNS entry does not resolve out there, so the claim cannot be honest."""
    print("\nthe same upload from a public address")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        ingest, live = _ingest(Path(raw))
        # `access` is 'any' here on purpose: what shuts this is not what the
        # port was opened to, it is that the hardware could not be out there.
        got = [ingest.submit(BRIDGE, "/weatherstation/update.php",
                             peer="203.0.113.7")[1] for _ in range(6)]
        check("refused", sorted(set(got)), ["unauthorised"])
        # And spending the wrong-token allowance, which is what a refusal is
        # for: from out there this is a guess at the token, not a console.
        check("and it counted as wrong tokens",
              ingest.limits.has_attempts_left("203.0.113.7"), False)
        live.close()


def behind_a_proxy_the_door_is_shut() -> None:
    """Every request arrives from loopback, so nothing here can tell."""
    print("\nbehind a reverse proxy")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        ingest, live = _ingest(Path(raw),
                               limits=Limits(behind_proxy=True))
        stored, why, _ = ingest.submit(BRIDGE, "/weatherstation/update.php",
                                       peer="127.0.0.1")
        check("loopback is not evidence of anything", (stored, why),
              (0, "unauthorised"))
        live.close()

    # And without the proxy the very same request is taken, so what the test
    # above measures is the proxy setting and not the address.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        ingest, live = _ingest(Path(raw))
        stored, why, _ = ingest.submit(BRIDGE, "/weatherstation/update.php",
                                       peer="127.0.0.1")
        check("without one, the same request is taken", (stored, why),
              (1, "ok"))
        live.close()


def only_a_driver_that_says_so() -> None:
    """Never the default, and never a driver that said nothing about itself."""
    print("\nwhat no driver claims")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        ingest, live = _ingest(Path(raw))
        stored, why, _ = ingest.submit(b"hello there", "/whatever/",
                                       peer="192.168.1.44")
        # `default_driver` is 'quiet' and would have read this. The door is
        # not the default's to walk through.
        check("nothing recognises it", (stored, why), (0, "unauthorised"))

        stored, why, _ = ingest.submit(b"QUIET one", "/whatever/",
                                       peer="192.168.1.44")
        check("a driver that says nothing about its hardware",
              (stored, why), (0, "unauthorised"))
        live.close()

    # And with the bridge as the fallback, which is what somebody who owns one
    # would set. Without the claim being required, every unreadable upload on
    # the network would be recorded as coming from that bridge -- readings
    # from nowhere, under the name of a real sender.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        ingest, live = _ingest(Path(raw))
        ingest.default_driver = "bridge"
        stored, why, _ = ingest.submit(b"hello there", "/whatever/",
                                       peer="192.168.1.44")
        check("with the bridge as the fallback, still refused",
              (stored, why), (0, "unauthorised"))
        live.close()


def a_bridge_no_longer_locks_itself_out() -> None:
    """The measured symptom: five refusals a minute, one upload every 18s."""
    print("\nten uploads in a row, which used to be five and then silence")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        ingest, live = _ingest(Path(raw))
        got = [ingest.submit(BRIDGE, "/weatherstation/update.php",
                             peer="192.168.1.44")[1] for _ in range(10)]
        check("all accepted", sorted(set(got)), ["ok"])
        check("with attempts to spare",
              ingest.limits.has_attempts_left("192.168.1.44"), True)
        live.close()


def the_pages_still_want_the_token() -> None:
    """A status page is not hardware and has no excuse for not having one.

    Over real HTTP, because `do_GET` and `do_POST` take different routes to
    the same question and only one of them was changed.
    """
    print("\nthe diagnostic pages, over HTTP")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        ingest, live = _ingest(Path(raw))
        listener = HttpListener(ingest, "127.0.0.1", 0)
        listener.start()
        base = f"http://127.0.0.1:{listener.port}"

        def fetch(path: str) -> int:
            try:
                with urllib.request.urlopen(base + path, timeout=5) as answer:
                    return answer.status
            except urllib.error.HTTPError as exc:
                return exc.code

        check("/live without a token", fetch("/live"), 404)
        check("/status without a token", fetch("/status"), 404)
        check("/status with one", fetch(f"/{TOKEN}/status"), 200)

        def post(path: str, body: bytes) -> int:
            request = urllib.request.Request(base + path, data=body)
            try:
                with urllib.request.urlopen(request, timeout=5) as answer:
                    return answer.status
            except urllib.error.HTTPError as exc:
                return exc.code

        check("a bridge posting with no token", post("/x/", BRIDGE), 200)
        check("a console posting with no token", post("/x/", TELLABLE), 404)

        # It really was recorded, rather than answered politely and dropped:
        # the listener answers 200 to plenty it could not read.
        with urllib.request.urlopen(base + f"/{TOKEN}/status", timeout=5) as a:
            status = json.loads(a.read())
        check("and the bridge's packet is in the table",
              status.get("accepted"), 1)

        listener.stop()
        live.close()


def main() -> int:
    a_bridge_gets_in_and_a_console_does_not()
    outside_the_network_it_is_refused()
    behind_a_proxy_the_door_is_shut()
    only_a_driver_that_says_so()
    a_bridge_no_longer_locks_itself_out()
    the_pages_still_want_the_token()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("hardware that cannot carry a token gets in; everything else pays")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Check who gets an answer.

Both services bind to everything and answer only private networks. That is the
compromise the usual installation needs: a machine in a shed, a console on the
same wifi, a laptop in the kitchen -- and nothing from the open internet
unless somebody said so.

A peer address cannot be faked over TCP, so this can be tested for real by
driving the servers with a socket whose source address is something else. What
can be tested without another machine is the decision itself, which is where
the mistakes are: the ranges that get forgotten, and the IPv4-in-IPv6 form
that matches no IPv4 rule unless it is unwrapped.

    python tools/netaccess_test.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.admin import Admin, AdminServer
from weewx_evo.cli import all_schemas
from weewx_evo.db.live import LiveStore
from weewx_evo.ingest.listener import HttpListener, Ingest
from weewx_evo.netaccess import PRIVATE_ONLY, Access

TOKEN = "a-token"


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


def main() -> int:
    failures = 0

    print("what counts as private")
    for address, expected, why in [
        ("127.0.0.1", True, "loopback"),
        ("192.168.1.50", True, "the usual home network"),
        ("10.0.0.5", True, "RFC 1918"),
        ("172.16.0.1", True, "the range people forget"),
        ("172.32.0.1", False, "just outside it, which is public"),
        ("169.254.7.7", True, "link-local: two machines and a cable"),
        ("100.64.1.2", True, "carrier NAT, which is what Tailscale hands out"),
        ("::1", True, "IPv6 loopback"),
        ("fd00::1", True, "IPv6 unique local"),
        ("fe80::1", True, "IPv6 link-local"),
        ("::ffff:192.168.1.5", True, "IPv4 arriving on a dual-stack socket"),
        ("::ffff:8.8.8.8", False, "and the public one, likewise wrapped"),
        ("8.8.8.8", False, "the open internet"),
        ("203.0.113.9", False, "documentation range, still public"),
        ("2001:4860:4860::8888", False, "public IPv6"),
    ]:
        failures += not check(f"{address} -- {why}", PRIVATE_ONLY.allows(address),
                              expected)

    print("\nasking for more, on purpose")
    everyone = Access.parse("any")
    failures += not check("'any' lets the internet in", everyone.allows("8.8.8.8"),
                          True)
    listed = Access.parse("203.0.113.0/24, 198.51.100.7")
    failures += not check("a network in the list", listed.allows("203.0.113.9"), True)
    failures += not check("a single address in it", listed.allows("198.51.100.7"),
                          True)
    failures += not check("something else", listed.allows("8.8.8.8"), False)
    failures += not check("loopback, always", listed.allows("127.0.0.1"), True)
    failures += not check("it says what it does", str(listed),
                          "203.0.113.0/24, 198.51.100.7/32")

    print("\na typo is refused rather than guessed at")
    for bad in ("nonsense", "10.0.0.0/99", ""):
        try:
            Access.parse(bad) if bad else Access.parse("   ,  ")
            failures += not check(f"{bad!r}", "accepted", "refused")
        except ValueError:
            failures += not check(f"{bad!r} refused", True, True)

    print("\nthe servers ask before anything else")
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-net-"))
    try:
        live = LiveStore(tmp / "live.sdb", interval_seconds=60)
        # A policy that lets nothing but loopback through, then a request from
        # loopback -- which must still work, or the machine locks itself out.
        narrow = Access.parse("203.0.113.0/24")
        ingest = Ingest(live, token=TOKEN, access=narrow)
        http = HttpListener(ingest, "127.0.0.1", 0)
        http.start()
        try:
            url = f"http://127.0.0.1:{http.port}/{TOKEN}/live"
            with urllib.request.urlopen(url, timeout=5) as r:
                failures += not check("loopback is never locked out", r.status, 200)
        finally:
            http.stop()

        # And the other way: refuse everything, and see loopback refused too.
        shut = Access(networks=(), described="nothing")
        ingest = Ingest(live, token=TOKEN, access=shut)
        http = HttpListener(ingest, "127.0.0.1", 0)
        http.start()
        try:
            url = f"http://127.0.0.1:{http.port}/{TOKEN}/live"
            reason = ""
            try:
                urllib.request.urlopen(url, timeout=5)
                failures += not check("a closed policy refuses", "answered", "404")
            except urllib.error.HTTPError as exc:
                failures += not check("a closed policy refuses", exc.code, 404)
                reason = str(exc.reason)
            failures += not check("and counts it", ingest.refused_peers, 1)
            # The same 404 a wrong token gets. Saying "wrong network" would
            # tell somebody scanning that there is something here worth
            # finding the right network for.
            failures += not check("the reason is not given away",
                                  "network" in reason.lower(), False)
        finally:
            http.stop()

        print("\nthe settings page does the same")
        admin = Admin(tmp / "evo.toml", all_schemas(), TOKEN, access=shut)
        server = AdminServer(admin, "127.0.0.1", 0)
        server.start()
        try:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{server.port}/{TOKEN}/core", timeout=5)
                failures += not check("refused", "answered", "404")
            except urllib.error.HTTPError as exc:
                failures += not check("refused", exc.code, 404)
            failures += not check("and counts it", admin.refused_peers, 1)
        finally:
            server.stop()

        print("\nstatus says who is answered")
        ingest = Ingest(live, token=TOKEN)
        failures += not check("by default", ingest.status()["answers"],
                              "private networks")
        live.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

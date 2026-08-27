"""Check the two limits, and that they are not the same limit.

Requests that work get a generous allowance, because a console uploading every
eight seconds must never be told to slow down. Requests that fail get a tight
one, because the token is in the path and can therefore be guessed at.

Conflating the two gives you the worst of both: either a limit loose enough to
brute-force through, or one tight enough to lose measurements.

    python tools/ratelimit_test.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.db.live import LiveStore
from weewx_evo.ingest.listener import HttpListener, Ingest
from weewx_evo.netaccess import Access
from weewx_evo.ratelimit import Limiter, Limits

TOKEN = "the-real-token"


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


def main() -> int:
    failures = 0

    print("a bucket fills up again")
    # Driven with an explicit clock rather than sleeping: a test that waits
    # for real seconds is a test people stop running.
    limiter = Limiter(rate=10, burst=10)
    now = 1000.0
    allowed = sum(limiter.allow("a", now) for _ in range(15))
    failures += not check("ten through, five refused", allowed, 10)
    failures += not check("still refused a moment later",
                          limiter.allow("a", now + 0.05), False)
    failures += not check("one more after a tenth of a second",
                          limiter.allow("a", now + 0.15), True)
    failures += not check("and full again after a second and a half",
                          sum(limiter.allow("a", now + 1.6) for _ in range(10)), 10)

    print("\none address does not spend another's")
    limiter = Limiter(rate=1, burst=2)
    now = 2000.0
    for _ in range(5):
        limiter.allow("noisy", now)
    failures += not check("the quiet one is unaffected",
                          limiter.allow("quiet", now), True)

    print("\nthe table cannot grow without limit")
    limiter = Limiter(rate=1, burst=1, capacity=100)
    for i in range(500):
        limiter.allow(f"10.0.0.{i}", 3000.0)
    failures += not check("bounded", limiter.status()["tracking"], 100)

    print("\na real console is never told to slow down")
    limits = Limits()
    now = 4000.0
    # A Vantage: one packet every two seconds, for an hour.
    refused = 0
    for tick in range(1800):
        if not limits.requests.allow("192.168.1.50", now + tick * 2):
            refused += 1
    failures += not check("an hour of packets, none refused", refused, 0)
    # And a driver catching up after being offline: a burst all at once.
    burst = sum(limits.requests.allow("192.168.1.50", now + 3600) for _ in range(20))
    failures += not check("a catch-up burst mostly gets through", burst >= 10, True)

    print("\nwrong tokens run out quickly")
    limits = Limits()
    now = 5000.0
    guesses = sum(limits.failures.allow("203.0.113.9", now) for _ in range(20))
    failures += not check("five, and no more", guesses, 5)
    failures += not check("a minute later, one more",
                          limits.failures.allow("203.0.113.9", now + 61), True)

    print("\ngetting it right clears the record")
    limits = Limits()
    now = 6000.0
    for _ in range(4):
        limits.failures.allow("192.168.1.9", now)
    limits.succeeded("192.168.1.9")
    failures += not check("a full allowance again",
                          sum(limits.failures.allow("192.168.1.9", now)
                              for _ in range(5)), 5)

    print("\nbehind a proxy it does not pretend")
    proxied = Limits(behind_proxy=True)
    failures += not check("nothing is limited",
                          all(proxied.allow("172.28.0.1") for _ in range(1000)),
                          True)
    failures += not check("and it says why",
                          proxied.status()["why"],
                          "behind a proxy; rate limiting belongs there")

    print("\nthe listener refuses in the right way")
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-rate-"))
    try:
        live = LiveStore(tmp / "live.sdb", interval_seconds=60)
        ingest = Ingest(live, token=TOKEN, access=Access.parse("any"),
                        limits=Limits(rate=3))
        http = HttpListener(ingest, "127.0.0.1", 0)
        http.start()
        base = f"http://127.0.0.1:{http.port}"
        try:
            codes = []
            for _ in range(20):
                try:
                    with urllib.request.urlopen(f"{base}/{TOKEN}/live", timeout=5) as r:
                        codes.append(r.status)
                except urllib.error.HTTPError as exc:
                    codes.append(exc.code)
                    if exc.code == 429:
                        # A client being told to slow down is told by how much.
                        failures += not check("Retry-After is given",
                                              exc.headers.get("Retry-After"), "5")
                        break
            failures += not check("some got through", 200 in codes, True)
            failures += not check("then 429, not 404", 429 in codes, True)
        finally:
            http.stop()

        print("\nand a wrong token is refused as a 404, not a 429")
        # The difference matters: 429 says "there is something here, wait".
        ingest = Ingest(live, token=TOKEN, access=Access.parse("any"),
                        limits=Limits(rate=100))
        http = HttpListener(ingest, "127.0.0.1", 0)
        http.start()
        base = f"http://127.0.0.1:{http.port}"
        try:
            codes = []
            for _ in range(12):
                try:
                    urllib.request.urlopen(f"{base}/wrong-token/live", timeout=5)
                    codes.append(200)
                except urllib.error.HTTPError as exc:
                    codes.append(exc.code)
            failures += not check("always 404", set(codes), {404})
            # Each wrong token spends an attempt, so after a dozen there are
            # none left -- which is what stops a search, not the status code.
            failures += not check("the guesses were spent",
                                  ingest.limits.has_attempts_left("127.0.0.1"),
                                  False)
        finally:
            http.stop()
        live.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

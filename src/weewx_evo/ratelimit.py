"""How often one address may ask.

Two limits, because there are two different things to be afraid of and one
number cannot serve both.

**Requests that work** need a generous limit. A console uploads every eight
seconds; a Vantage sends a LOOP packet every two. Even a station with several
consoles and a driver catching up after an outage stays under one a second.
Ten is room to spare, and the only thing it stops is something that has gone
wrong -- a console stuck in a retry loop, a script left running. It is not a
security measure and is not meant as one.

**Requests that fail** need a tight one, and this is where the value is. The
token is the whole of the protection: it is in the path because hardware
cannot send a header, which also means it can be guessed at by anyone who can
reach the port. A 48-character token cannot realistically be found -- but a
short one somebody chose by hand can, and the cost of making that impossible
is a counter. Five wrong tokens a minute is more than any misconfigured
console produces and fewer than any search needs.

## The reverse proxy problem

Behind a proxy every request arrives from the proxy's address, so a limit per
address becomes a limit on the proxy: one attacker exhausts the budget for
everybody, and the attacker is not slowed down at all. There is no honest way
to fix that here -- `X-Forwarded-For` is a header anyone can write, and
trusting it without knowing the proxy is worse than not limiting.

So the limiter is told whether it is behind a proxy. If it is, it says so at
startup and leaves the rate limiting to the proxy, which is the only thing in
a position to do it correctly. Caddy, nginx and Traefik all can.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

log = logging.getLogger(__name__)


class Bucket:
    """One address's allowance. A token bucket, which is the simple one.

    Tokens accrue at `rate` a second up to `burst`, and each request spends
    one. That shape is right here: a console that has been offline and posts
    its backlog gets through on the burst, and something looping gets through
    at the rate.
    """

    __slots__ = ("last", "tokens")

    def __init__(self, burst: float, now: float) -> None:
        self.tokens = burst
        self.last = now

    def take(self, rate: float, burst: float, now: float) -> bool:
        self.tokens = min(burst, self.tokens + (now - self.last) * rate)
        self.last = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class Limiter:
    """A rate per address, with a bounded amount of memory.

    Bounded matters: one entry per address is fine on a home network and is a
    way to run a machine out of memory on a public one. The oldest entries go
    when the table is full, which is the right thing to lose -- an address
    that has not been seen for a while has its full allowance anyway.
    """

    def __init__(self, rate: float, burst: float | None = None,
                 capacity: int = 4096, name: str = "requests") -> None:
        self.rate = float(rate)
        self.burst = float(burst if burst is not None else max(rate * 2, 5))
        self.capacity = capacity
        self.name = name
        self.refused = 0
        self._buckets: OrderedDict[str, Bucket] = OrderedDict()
        self._lock = threading.Lock()
        self._told: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self.rate > 0

    def allow(self, key: str, now: float | None = None) -> bool:
        """Whether this address may make a request now."""
        if not self.enabled:
            return True
        now = now if now is not None else time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.capacity:
                    self._buckets.popitem(last=False)
                bucket = Bucket(self.burst, now)
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)

            if bucket.take(self.rate, self.burst, now):
                self._told.discard(key)
                return True

            self.refused += 1
            # Once per address per spell of being over, not once per request:
            # a log line for every refused request is a second flood.
            if key not in self._told:
                self._told.add(key)
                log.warning("%s from %s over the limit of %g/s; refusing until "
                            "it slows down", self.name, key, self.rate)
            return False

    def remaining(self, key: str, now: float | None = None) -> float:
        """How many requests this address has left, without spending one."""
        if not self.enabled:
            return float("inf")
        now = now if now is not None else time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return self.burst
            return min(self.burst, bucket.tokens + (now - bucket.last) * self.rate)

    def forget(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)
            self._told.discard(key)

    def status(self) -> dict:
        with self._lock:
            return {"rate_per_second": self.rate, "burst": self.burst,
                    "tracking": len(self._buckets), "refused": self.refused}


class Limits:
    """What a service uses: one limit for requests, a tighter one for failures."""

    #: A console at its fastest sends one packet every two seconds. Ten a
    #: second is two orders of magnitude of room, which is where a limit
    #: meant to catch a runaway belongs.
    DEFAULT_RATE = 10.0

    #: Wrong tokens. Five a minute is more than a misconfigured console
    #: produces and fewer than any search needs. This is the one that matters.
    DEFAULT_FAILURES = 5.0 / 60.0

    def __init__(self, rate: float = DEFAULT_RATE,
                 failures: float = DEFAULT_FAILURES,
                 behind_proxy: bool = False) -> None:
        self.behind_proxy = behind_proxy
        self.requests = Limiter(0 if behind_proxy else rate, name="requests")
        # A burst of five, so somebody who mistypes a token twice is not
        # locked out for a minute.
        self.failures = Limiter(0 if behind_proxy else failures, burst=5,
                                name="failed attempts")

    def allow(self, address: str) -> bool:
        return self.requests.allow(address)

    def has_attempts_left(self, address: str) -> bool:
        """Whether this address has any wrong guesses left.

        Asks without spending. The distinction is the whole of it: checking
        must be free, or every legitimate request would use up the allowance
        meant for wrong ones and a console would lock itself out in seconds.
        Only `failed()` spends.
        """
        if not self.failures.enabled:
            return True
        return self.failures.remaining(address) >= 1

    def failed(self, address: str) -> None:
        """A wrong token arrived from here. This is what spends an attempt."""
        self.failures.allow(address)

    def succeeded(self, address: str) -> None:
        """A request got through with the right token: forget its failures."""
        self.failures.forget(address)

    def status(self) -> dict:
        if self.behind_proxy:
            return {"limited": False,
                    "why": "behind a proxy; rate limiting belongs there"}
        return {"limited": True,
                "requests": self.requests.status(),
                "failures": self.failures.status()}


def announce(limits: Limits, what: str) -> None:
    """Say at startup what is being limited, and what is not."""
    if limits.behind_proxy:
        log.info("%s is behind a proxy, so it is not rate limiting. Every "
                 "request arrives from the proxy's address, and limiting that "
                 "would slow down everyone except the one doing it. Set a "
                 "limit in the proxy instead.", what)
        return
    log.info("%s allows %g request/s per address, and %g wrong token(s) a "
             "minute.", what, limits.requests.rate, limits.failures.rate * 60)

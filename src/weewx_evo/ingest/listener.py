"""The listener every push driver sits behind.

One process accepts HTTP and UDP, hands the bytes to a driver, and writes the
packets it gets back to the live table. Drivers do not open sockets, do not
check tokens, and do not touch the database -- which is the whole point: those
three are where push drivers go wrong, and doing them once is doing them once.

Which driver runs is decided by the path (`/<token>/ecowitt/`) or by
configuration. The drivers are plugins and this file knows none of them --
including what to answer with, which is protocol knowledge the driver owns.
See ingest/drivers.py.

It answers 200 to anything a driver accepted and 200 to most of what it could
not read. Weather consoles are not HTTP clients: they send requests with no
Host header and bare newlines for line endings, they ignore status codes, and
some of them stop uploading for an hour after a 4xx. Being strict with them
loses measurements and teaches nobody anything.
"""

from __future__ import annotations

import json
import logging
import socket
import socketserver
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from ..db.live import LiveStore, Packet
from ..netaccess import PRIVATE_ONLY, Access
from ..ratelimit import Limits
from . import drivers, statuspage

log = logging.getLogger(__name__)

MAX_BODY = 1 << 20  # 1 MB. No console sends more; anything that does is not one.
#: A kept upload is for reading, so it is capped well below MAX_BODY.
MAX_RAW = 8192


class Ingest:
    """What the listener does with an upload once it has one.

    Kept separate from the transports so the same object serves HTTP, UDP and
    the tests, and so a pull driver can be written against it directly.
    """

    def __init__(self, store: LiveStore, token: str | None = None,
                 default_driver: str = "ecowitt",
                 registry: drivers.Registry | None = None,
                 access: Access = PRIVATE_ONLY,
                 limits: Limits | None = None) -> None:
        self.store = store
        self.token = token
        self.default_driver = default_driver
        self.registry = registry or drivers.DEFAULT
        # Bound to everything, answering only what is on a private network. A
        # console is on the same wifi, and a reverse proxy connects from
        # loopback. Anything further away is a decision somebody makes.
        self.access = access
        self.refused_peers = 0
        # A generous limit on requests, a tight one on wrong tokens. The
        # second is the one that matters: the token is in the path, so it can
        # be guessed at by anyone who reaches the port.
        self.limits = limits or Limits()
        self.accepted = 0
        self.duplicates = 0
        self.rejected = 0
        self.last_packet: float | None = None
        self._lock = threading.Lock()

    def authorised(self, path: str) -> bool:
        """Whether a request path carries the token.

        The token is a path segment rather than a header because consoles
        cannot send headers. It is the only thing between the open internet and
        the measurement series, so a listener configured without one says so
        loudly at startup.
        """
        if self.token is None:
            return True
        return self.token in path.strip("/").split("/")

    def driver_for(self, path: str) -> str:
        """Pick a driver from the path, e.g. /<token>/json/ or /<token>/ecowitt/."""
        for segment in path.strip("/").split("/"):
            if self.registry.known(segment):
                return segment
        return self.default_driver

    def submit(self, body: bytes, path: str = "/",
               peer: str = "?") -> tuple[int, str, drivers.Response]:
        """Take one upload. Returns (packets stored, reason, what to answer with).

        The response comes from the driver. What a device needs to hear is part
        of its protocol -- an Ecowitt gateway wants a particular JSON object and
        backs off for an hour if it does not get it -- so the core repeats what
        the driver says rather than deciding for itself.
        """
        if not self.authorised(path):
            with self._lock:
                self.rejected += 1
            # Count the guess before reporting it. An address that keeps
            # trying runs out of attempts rather than out of patience.
            self.limits.failed(peer)
            log.warning("rejected upload from %s: bad or missing token", peer)
            return 0, "unauthorised", drivers.DEFAULT_RESPONSE
        self.limits.succeeded(peer)

        name = self.driver_for(path)
        driver = self.registry.get(name)
        if driver is None:
            log.warning("no driver named %r; known: %s",
                        name, ", ".join(self.registry.names()))
            return 0, f"no driver {name!r}", drivers.DEFAULT_RESPONSE

        response = drivers.response_of(driver)
        meta = {"received": int(time.time()), "source": peer}
        try:
            packets = driver.packets(body, meta)
        except Exception as exc:
            with self._lock:
                self.rejected += 1
            log.warning("the %s driver could not read an upload from %s: %s",
                        name, peer, exc)
            # Answer anyway. A console that gets an error stops uploading, and
            # the next measurement is worth more than the tidy status code.
            return 0, "unreadable", response

        # Keep the upload beside the packet for a while. What a driver could
        # not place is by definition not in the packet, so the parsed version
        # is the one thing that cannot show it -- and getting hold of a raw
        # upload otherwise means reconfiguring a console and waiting.
        raw = None
        if self.store.keep_raw_seconds and packets:
            raw = self._redacted(driver, body)

        stored = 0
        for packet in packets:
            if raw is not None and packet.raw is None:
                packet = replace(packet, raw=raw)
            if self.store.add(packet):
                stored += 1
            else:
                with self._lock:
                    self.duplicates += 1

        with self._lock:
            self.accepted += stored
            if stored:
                self.last_packet = time.time()
        return stored, "ok", response

    def _redacted(self, driver: object, body: bytes) -> str | None:
        """The upload as it arrived, with whatever the driver calls secret gone.

        Redaction is protocol knowledge: only the driver knows that Ecowitt's
        PASSKEY identifies the station and that everything else in the body is
        weather. So it is asked, and a driver that does not offer to redact has
        its uploads kept verbatim -- which is the honest default, because the
        alternative is guessing at what matters and getting it wrong.
        """
        try:
            text = body.decode("utf-8", "replace")
        except Exception:
            return None
        if len(text) > MAX_RAW:
            text = text[:MAX_RAW] + "...(truncated)"
        redact = getattr(driver, "redact", None)
        if redact is None:
            return text
        try:
            return str(redact(text))
        except Exception:
            log.exception("driver redaction failed; not keeping the raw upload")
            return None

    def status(self) -> dict:
        first, last = self.store.span()
        report: dict = {
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "rejected": self.rejected,
            "packets_held": self.store.count(),
            "oldest_packet": first,
            "newest_packet": last,
            "last_packet_at": self.last_packet,
            "answers": str(self.access),
            "refused_peers": self.refused_peers,
            "rate_limit": self.limits.status(),
        }
        # Whatever the drivers want to say for themselves -- which consoles
        # they answer to, what they refused. The core does not interpret it.
        by_driver = {}
        for name in self.registry.names():
            driver = self.registry.get(name)
            said = drivers.status_of(driver) if driver is not None else {}
            if said:
                by_driver[name] = said
        if by_driver:
            report["drivers"] = by_driver
        return report


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    ingest: Ingest  # set on the server class

    def log_message(self, fmt: str, *args: object) -> None:
        log.debug("%s %s", self.address_string(), fmt % args)

    def _has_token(self, path: str) -> bool:
        """Check the token and count a wrong one, in one place.

        Both matter and they were split before: `submit` counted a wrong
        token, the pages did not, so a search that only ever asked for
        /<guess>/live was never slowed down at all.
        """
        peer = self.client_address[0] if self.client_address else ""
        if self.ingest.authorised(path):
            self.ingest.limits.succeeded(peer)
            return True
        self.ingest.limits.failed(peer)
        return False

    def _permitted(self) -> bool:
        """Whether this peer is on a network we answer at all.

        Checked before the token, and refused with the same 404. Saying "wrong
        network" would tell somebody scanning that there is something here
        worth finding the right network for.
        """
        peer = self.client_address[0] if self.client_address else ""
        if not self.ingest.access.allows(peer):
            self.ingest.refused_peers += 1
            log.warning("refused %s: this listener answers %s",
                        peer, self.ingest.access)
            self._reply(404, b"not found")
            return False
        if not self.ingest.limits.has_attempts_left(peer):
            # Out of wrong guesses. The same 404 a wrong token gets: saying
            # "too many attempts" would confirm there is something to attempt.
            self._reply(404, b"not found")
            return False
        if not self.ingest.limits.allow(peer):
            # 429 here, not 404. This one is a real client being told to slow
            # down, and Retry-After is what tells it by how much.
            self._reply(429, b"slow down", "text/plain", {"Retry-After": "5"})
            return False
        return True

    def _reply(self, code: int, body: bytes, content_type: str = "text/plain",
               headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._permitted():
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(min(length, MAX_BODY)) if length else b""

        path = urlparse(self.path).path
        _stored, reason, response = self.ingest.submit(body, path,
                                                       self.client_address[0])
        if reason == "unauthorised":
            self._reply(404, b"not found")
            return
        self._reply(200, response[0], response[1])

    def do_GET(self) -> None:
        if not self._permitted():
            return
        parsed = urlparse(self.path)
        trimmed = parsed.path.rstrip("/")

        # Diagnostics, all behind the token. They sit on the upload path
        # because that path is the only thing keeping strangers out, and a page
        # showing what a station is measuring should not be easier to reach
        # than the endpoint that records it.
        for suffix, handler in (("/status", self._status),
                                ("/recent", self._recent),
                                ("/live", self._page)):
            if trimmed.endswith(suffix):
                if not self._has_token(parsed.path):
                    self._reply(404, b"not found")
                    return
                handler()
                return

        # Weather Underground protocol stations upload over GET, with the
        # readings in the query string.
        if parsed.query:
            _stored, reason, response = self.ingest.submit(
                parsed.query.encode(), parsed.path, self.client_address[0])
            if reason == "unauthorised":
                self._reply(404, b"not found")
                return
            self._reply(200, response[0], response[1])
            return

        # The bare token path is the page. Anything else says nothing.
        if self.ingest.token and trimmed.endswith("/" + self.ingest.token):
            self._page()
            return
        self._reply(200, b"weewx-evo\n")

    def _status(self) -> None:
        self._reply(200, json.dumps(self.ingest.status(), indent=2).encode(),
                    "application/json")

    def _recent(self) -> None:
        try:
            body = json.dumps(statuspage.recent(self.ingest.store, self.ingest)).encode()
        except Exception:
            log.exception("could not assemble the status data")
            self._reply(500, b'{"error":"unavailable"}', "application/json")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _page(self) -> None:
        self._reply(200, statuspage.render(), "text/html; charset=utf-8")


class HttpListener:
    """The HTTP half. Threaded, because a slow console must not block the others."""

    def __init__(self, ingest: Ingest, host: str = "0.0.0.0", port: int = 8000) -> None:
        handler = type("Handler", (_Handler,), {"ingest": ingest})
        self.server = ThreadingHTTPServer((host, port), handler)
        self.server.daemon_threads = True
        self.host, self.port = self.server.server_address[:2]

    def serve_forever(self) -> None:  # pragma: no cover - a loop
        log.info("listening for HTTP on %s:%s", self.host, self.port)
        self.server.serve_forever()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Datagram(socketserver.BaseRequestHandler):
    ingest: Ingest
    driver: str

    def handle(self) -> None:
        peer = self.client_address[0] if self.client_address else ""
        if not self.ingest.access.allows(peer):
            self.ingest.refused_peers += 1
            return
        if not self.ingest.limits.allow(peer):
            return
        body = self.request[0]
        # A datagram has no path to carry a token, so the driver is fixed at
        # configuration time and the port itself is the access control. Nothing
        # is sent back: there is nobody listening for a reply.
        self.ingest.submit(body, f"/{self.driver}/", self.client_address[0])


class UdpListener:
    """The UDP half, for hardware that broadcasts rather than posts."""

    def __init__(self, ingest: Ingest, host: str = "0.0.0.0", port: int = 8001,
                 driver: str = "json") -> None:
        handler = type("Datagram", (_Datagram,), {"ingest": ingest, "driver": driver})
        socketserver.UDPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingUDPServer((host, port), handler)
        self.server.max_packet_size = MAX_BODY
        self.host, self.port = self.server.server_address[:2]

    def serve_forever(self) -> None:  # pragma: no cover - a loop
        log.info("listening for UDP on %s:%s", self.host, self.port)
        self.server.serve_forever()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def push(packets: list[Packet], host: str = "127.0.0.1", port: int = 8000,
         token: str | None = None, timeout: float = 3.0) -> int:
    """Send packets to a listener. This is how a pull driver delivers.

    Going over the loopback rather than writing to the database directly is
    deliberate. It costs a millisecond and buys process isolation: a driver
    that wedges on a USB port, or crashes, takes nothing else with it -- and it
    does not have to be written in Python.
    """
    import urllib.request

    path = f"/{token}/json/" if token else "/json/"
    body = json.dumps([{
        "dateTime": p.dateTime, "usUnits": p.usUnits, "source": p.source,
        "kind": p.kind, "interval": p.interval, "data": p.data,
    } for p in packets]).encode()

    request = urllib.request.Request(
        f"http://{host}:{port}{path}", data=body,
        headers={"Content-Type": "application/json"})
    # The URL is built here out of a host and a port, three lines up.
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        response.read()
    return len(packets)


def resolve_bind(host: str) -> str:
    """Turn a bind address into something to print. Cosmetic only."""
    if host in ("", "0.0.0.0", "::"):
        return socket.gethostname()
    return host

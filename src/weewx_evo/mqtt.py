"""MQTT 3.1.1, over a socket, out of the standard library.

Why this file exists at all: MQTT is how a modern weather skin comes alive.
Belchertown, jas, weewx-wdc and Weather34 all take their live updates from an
MQTT broker over websockets, and a station without one renders those skins
perfectly and then sits frozen between archive intervals. Since the Cheetah
feed exists to run those skins unchanged, the broker is not an extra.

Why it is written here rather than installed: `paho-mqtt` is the obvious
answer and it is a dependency, and this core runs on the standard library.
That is not a slogan -- it is what makes `pip install weewx-evo` work on a
Raspberry Pi with no compiler and no network policy exception, and one
convenience library is not the thing to spend it on.

And the trade is smaller than it looks. MQTT 3.1.1 has been frozen since 2014,
the wire format is a byte layout rather than a negotiation, and what a weather
station needs is a fraction of it: connect, publish, subscribe, ping,
disconnect. What is deliberately absent:

  * **QoS 2.** Four packets to guarantee exactly-once delivery of a
    temperature that will be superseded in five minutes. QoS 1 is what every
    weather skin uses and duplicates are harmless when the payload carries
    its own timestamp.
  * **Session resumption.** A clean session every time. Anything worth
    resuming is in the archive, which is a better store than a broker's
    memory.
  * **MQTT 5.** Nothing here needs its properties, and brokers still speak
    3.1.1 in every deployment a station will meet.

The one thing this does take seriously is reconnecting. A domestic connection
drops, a broker restarts, a container gets rescheduled -- and an MQTT client
that gives up on the first of those is worse than no MQTT at all, because the
skin keeps showing whatever was true when it stopped.
"""

from __future__ import annotations

import logging
import socket
import ssl
import struct
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

# Packet types, in the top four bits of the first byte.
CONNECT, CONNACK = 1, 2
PUBLISH, PUBACK = 3, 4
SUBSCRIBE, SUBACK = 8, 9
UNSUBSCRIBE, UNSUBACK = 10, 11
PINGREQ, PINGRESP = 12, 13
DISCONNECT = 14

#: What CONNACK's second byte means. The wording is the specification's,
#: because it is what somebody will search for.
CONNACK_REASONS = {
    0: "connection accepted",
    1: "unacceptable protocol version",
    2: "identifier rejected",
    3: "server unavailable",
    4: "bad user name or password",
    5: "not authorised",
}

#: Codes where trying again is pointless. A wrong password does not become
#: right by being retried every thirty seconds for a year.
FATAL_CONNACK = (1, 4, 5)

DEFAULT_PORT = 1883
DEFAULT_TLS_PORT = 8883


class MqttError(Exception):
    """Anything that stopped a client from doing what was asked."""

    def __init__(self, message: str, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


# ---------------------------------------------------------------------------
# The wire format.
# ---------------------------------------------------------------------------

def encode_length(length: int) -> bytes:
    """MQTT's variable-length integer: seven bits a byte, top bit continues.

    Four bytes at most, so 268 435 455 is the largest packet. A weather
    reading is a few hundred bytes; the limit matters only as the reason the
    decoder can stop after four.
    """
    out = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length:
            byte |= 0x80
        out.append(byte)
        if not length:
            return bytes(out)


def encode_string(text: str) -> bytes:
    """A UTF-8 string with a two-byte length in front.

    Every string in MQTT is this shape -- topic, client id, user name -- and
    writing it once is what stops one of them being written subtly wrong.
    """
    raw = text.encode("utf-8")
    if len(raw) > 0xFFFF:
        raise MqttError(f"{text[:40]!r} is too long for MQTT", permanent=True)
    return struct.pack("!H", len(raw)) + raw


def decode_string(body: bytes, at: int = 0) -> tuple[str, int]:
    """A length-prefixed UTF-8 string out of a packet body.

    The other half of `encode_string`, and the one a broker needs: it reads
    what a client wrote. Returns the string and where the next field starts,
    because every MQTT body is a run of these and the caller has to walk it.

    A length that runs past the end is a malformed packet rather than a short
    string. Silently truncating it is how a topic filter becomes a shorter
    topic filter that matches something else.
    """
    if at + 2 > len(body):
        raise MqttError("packet ended where a string was expected")
    length = struct.unpack("!H", body[at:at + 2])[0]
    end = at + 2 + length
    if end > len(body):
        raise MqttError("a string in the packet claims to be longer than the "
                        "packet")
    return body[at + 2:end].decode("utf-8", "replace"), end


def topic_matches(filter_: str, topic: str) -> bool:
    """Whether an MQTT topic filter matches a topic name.

    Two wildcards, and the rules are not symmetric:

      `+`   exactly one level. `a/+/c` matches `a/b/c` and not `a/b/d/c`.
      `#`   this level and everything under it, and only at the end.
            `a/#` matches `a`, `a/b` and `a/b/c`.

    The case that catches people: `#` matches the parent as well as the
    children, so `weather/#` gets `weather` itself. And a filter starting
    with `+` or `#` must not match a topic starting with `$`, which is where
    brokers keep their own statistics -- a client subscribing to `#` should
    not be handed those.
    """
    if topic.startswith("$") and filter_[:1] in ("+", "#"):
        return False

    wanted = filter_.split("/")
    have = topic.split("/")
    for index, part in enumerate(wanted):
        if part == "#":
            # Only legal as the last level, and it takes everything from
            # here down -- including nothing, so `a/#` matches `a`.
            return index <= len(have)
        if index >= len(have):
            return False
        if part != "+" and part != have[index]:
            return False
    return len(wanted) == len(have)


class Reader:
    """Reads whole MQTT packets off a socket."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def _exactly(self, count: int) -> bytes:
        """`count` bytes, or an error. Never a short read.

        `recv` returning fewer bytes than asked is normal and is the bug that
        makes a hand-written protocol client work in testing and fail under
        load, once, unreproducibly.
        """
        chunks = []
        remaining = count
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise MqttError("the broker closed the connection")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def packet(self) -> tuple[int, int, bytes]:
        """The next packet as (type, flags, body)."""
        first = self._exactly(1)[0]
        length, multiplier = 0, 1
        for _ in range(4):
            byte = self._exactly(1)[0]
            length += (byte & 0x7F) * multiplier
            if not byte & 0x80:
                break
            multiplier *= 128
        else:
            raise MqttError("malformed packet length from the broker")
        return first >> 4, first & 0x0F, self._exactly(length) if length else b""


# ---------------------------------------------------------------------------
# The client.
# ---------------------------------------------------------------------------

class Client:
    """One connection to a broker.

    Not thread-safe for two publishers at once by accident: `publish` takes a
    lock, because two threads interleaving their bytes on one socket produces
    a stream the broker cannot parse and a connection that dies with no
    useful message.
    """

    def __init__(self, host: str, port: int | None = None,
                 client_id: str = "", username: str = "", password: str = "",
                 tls: bool = False, tls_verify: bool = True,
                 keepalive: int = 60, timeout: int = 20,
                 on_message: Callable[[str, bytes], None] | None = None) -> None:
        self.host = host
        self.tls = bool(tls)
        self.port = int(port or (DEFAULT_TLS_PORT if self.tls else DEFAULT_PORT))
        # A client id has to be unique on the broker: two clients sharing one
        # take turns kicking each other off, forever, and it looks like a
        # flapping network rather than a name collision.
        self.client_id = client_id or f"weewx-evo-{int(time.time()) & 0xFFFFFF:06x}"
        self.username = username
        self.password = password
        self.tls_verify = bool(tls_verify)
        self.keepalive = int(keepalive)
        self.timeout = int(timeout)
        self.on_message = on_message

        self._sock: socket.socket | None = None
        self._reader: Reader | None = None
        self._lock = threading.Lock()
        self._packet_id = 0
        self._last_sent = 0.0
        self._subscriptions: list[tuple[str, int]] = []

    # -- connecting ------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        """Open the connection and log in. Raises `MqttError`."""
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port),
                                            timeout=self.timeout)
        except OSError as exc:
            # A name that does not resolve is a typo, not an outage.
            permanent = isinstance(exc, socket.gaierror)
            raise MqttError(f"could not reach {self.host}:{self.port}: {exc}",
                            permanent=permanent) from exc
        if self.tls:
            context = ssl.create_default_context()
            if not self.tls_verify:
                # For a broker on the local network with a self-signed
                # certificate, which is most of them. Off is a setting and
                # says so; silently not verifying would be worse than plain.
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            try:
                sock = context.wrap_socket(sock, server_hostname=self.host)
            except ssl.SSLError as exc:
                sock.close()
                raise MqttError(f"TLS to {self.host} failed: {exc}") from exc

        self._sock = sock
        self._reader = Reader(sock)
        try:
            self._login()
        except Exception:
            self.close()
            raise
        # Anything subscribed before the drop is subscribed again. Without
        # this a reconnect looks successful and silently delivers nothing.
        for topic, qos in list(self._subscriptions):
            self._send_subscribe(topic, qos)
        log.info("MQTT connected to %s:%s as %s", self.host, self.port,
                 self.client_id)

    def _login(self) -> None:
        flags = 0x02          # clean session; see the module docstring
        payload = encode_string(self.client_id)
        if self.username:
            flags |= 0x80
            payload += encode_string(self.username)
            if self.password:
                flags |= 0x40
                payload += encode_string(self.password)
        variable = (encode_string("MQTT") + bytes([4, flags])
                    + struct.pack("!H", self.keepalive))
        self._write(CONNECT, 0, variable + payload)

        kind, _flags, body = self._read()
        if kind != CONNACK or len(body) < 2:
            raise MqttError(f"the broker answered CONNECT with {kind}, not CONNACK")
        code = body[1]
        if code:
            raise MqttError(
                f"{self.host} refused the connection: "
                f"{CONNACK_REASONS.get(code, f'code {code}')}",
                permanent=code in FATAL_CONNACK)

    def close(self) -> None:
        """Say goodbye if possible, then drop the socket either way."""
        sock, self._sock, self._reader = self._sock, None, None
        if sock is None:
            return
        try:
            sock.sendall(bytes([DISCONNECT << 4, 0]))
        except OSError:
            # Already gone. That is the ordinary case here and not worth a
            # line in anybody's log.
            pass
        try:
            sock.close()
        except OSError:
            pass

    # -- packets ---------------------------------------------------------

    def _write(self, kind: int, flags: int, body: bytes) -> None:
        sock = self._sock
        if sock is None:
            raise MqttError("not connected")
        header = bytes([(kind << 4) | flags]) + encode_length(len(body))
        try:
            sock.sendall(header + body)
        except OSError as exc:
            self.close()
            raise MqttError(f"sending to {self.host} failed: {exc}") from exc
        self._last_sent = time.monotonic()

    def _read(self) -> tuple[int, int, bytes]:
        reader = self._reader
        if reader is None:
            raise MqttError("not connected")
        try:
            return reader.packet()
        except (MqttError, OSError):
            # The connection is gone, and this is the only place that finds
            # out: `_write` cannot, because sending into a socket the far end
            # has closed succeeds into the kernel buffer and reports nothing.
            # Without dropping it here the client believes it is connected,
            # every later publish disappears, and the log stays quiet.
            self.close()
            raise

    def _next_id(self) -> int:
        # Packet ids are 1..65535 and zero is not allowed, which is the whole
        # reason this is not a plain counter.
        self._packet_id = self._packet_id % 65535 + 1
        return self._packet_id

    # -- publishing ------------------------------------------------------

    def publish(self, topic: str, payload: bytes | str, qos: int = 0,
                retain: bool = False) -> None:
        """Send one message.

        `retain` is what makes a broker hand the last known value to a browser
        that has just loaded the page. Without it a skin shows nothing until
        the next archive record -- which is up to five minutes of a blank
        dashboard, and reads as broken.
        """
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        if qos not in (0, 1):
            raise MqttError("only QoS 0 and 1 are implemented; see the module "
                            "docstring for why", permanent=True)
        with self._lock:
            if not self.connected:
                self.connect()
            body = encode_string(topic)
            packet_id = 0
            if qos:
                packet_id = self._next_id()
                body += struct.pack("!H", packet_id)
            flags = (qos << 1) | (1 if retain else 0)
            self._write(PUBLISH, flags, body + payload)
            if qos:
                self._await_puback(packet_id)

    def _await_puback(self, packet_id: int) -> None:
        """Wait for the broker to acknowledge, ignoring anything else.

        Anything else does arrive: a client that has also subscribed gets
        PUBLISH packets in the middle of this, and a broker sends PINGRESP
        whenever it feels like it. Treating the next packet as the PUBACK is
        the mistake that makes QoS 1 work until somebody subscribes.
        """
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            kind, flags, body = self._read()
            if kind == PUBACK and len(body) >= 2:
                if struct.unpack("!H", body[:2])[0] == packet_id:
                    return
            elif kind == PUBLISH:
                self._deliver(flags, body)
            elif kind == PINGRESP:
                continue
        raise MqttError(f"{self.host} did not acknowledge a QoS 1 message")

    # -- subscribing -----------------------------------------------------

    def subscribe(self, topic: str, qos: int = 0) -> None:
        """Ask for a topic, and remember it across reconnects."""
        with self._lock:
            if not self.connected:
                self.connect()
            if (topic, qos) not in self._subscriptions:
                self._subscriptions.append((topic, qos))
            self._send_subscribe(topic, qos)

    def _send_subscribe(self, topic: str, qos: int) -> None:
        # The flags on SUBSCRIBE are fixed at 0b0010 by the specification.
        # A broker that gets anything else closes the connection without
        # saying why, which is a long afternoon.
        body = struct.pack("!H", self._next_id()) + encode_string(topic) + bytes([qos])
        self._write(SUBSCRIBE, 0x02, body)

    def _deliver(self, flags: int, body: bytes) -> None:
        """Hand an incoming PUBLISH to whoever asked for it."""
        if len(body) < 2:
            return
        length = struct.unpack("!H", body[:2])[0]
        topic = body[2:2 + length].decode("utf-8", "replace")
        rest = body[2 + length:]
        qos = (flags >> 1) & 0x03
        if qos:
            packet_id, rest = struct.unpack("!H", rest[:2])[0], rest[2:]
            self._write(PUBACK, 0, struct.pack("!H", packet_id))
        if self.on_message is not None:
            try:
                self.on_message(topic, rest)
            except Exception:
                # A handler that raises must not take the connection with it.
                log.exception("the handler for %s raised; carrying on", topic)

    def pump(self, seconds: float) -> None:
        """Read for a while, delivering what arrives and answering pings.

        For a subscriber. A publisher never needs to call it: its own
        `publish` reads whatever is waiting while it looks for a PUBACK.
        """
        deadline = time.monotonic() + seconds
        if self._sock is None:
            raise MqttError("not connected")
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            # Read the socket each turn rather than once. Anything in this
            # loop may find the connection gone and close it, and carrying on
            # with the reference from before that raises `OSError: [10038]
            # not a socket` -- which reads like a Windows quirk and is this.
            sock = self._sock
            if sock is None:
                return
            sock.settimeout(max(0.1, min(left, 1.0)))
            try:
                kind, flags, body = self._read()
            except TimeoutError:
                self.ping_if_due()
                continue
            if kind == PUBLISH:
                self._deliver(flags, body)

    def ping_if_due(self) -> None:
        """Keep the connection alive when nothing has been published.

        A broker drops a client that has been silent for one and a half
        keepalive periods. A station publishing every five minutes with a
        sixty-second keepalive is exactly that client.
        """
        if not self.connected:
            return
        if time.monotonic() - self._last_sent < self.keepalive * 0.5:
            return
        with self._lock:
            try:
                self._write(PINGREQ, 0, b"")
            except MqttError:
                # The connection was already gone; the next publish reopens it.
                log.debug("MQTT ping failed; will reconnect on the next send")

    def __enter__(self) -> Client:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

"""An MQTT broker, so a station does not need a second program.

## Why this exists

Every skin that shows live readings subscribes to an MQTT broker from the
visitor's browser. Until now that meant: install Mosquitto, give it two
listeners -- 1883 for MQTT over TCP and 9001 for MQTT over websockets -- and
keep its configuration in step with ours. Three programs where there could be
two, and the broker configured in a file nothing else here can read.

The realisation that makes this reasonable is that we already speak the
protocol. `mqtt.py` builds and parses MQTT packets; a broker is the same bytes
with the roles reversed. What was genuinely missing was websockets, and that
is `websocket.py`.

So: `weewx-evo serve` can be the broker. Point the MQTT upload at `localhost`,
switch this on, and the page is live. An external broker stays a setting -- a
station that already runs Mosquitto, or publishes to one somewhere else, keeps
doing exactly that.

## Deliberately small

This is a broker for a weather station, not for a fleet. What it does not do,
and will not:

  * **QoS 2.** Four packets to deliver a temperature exactly once that is
    superseded in five minutes. A subscriber asking for it is answered with
    QoS 1, which the specification allows: the granted QoS may be lower than
    the one requested.
  * **Persistent sessions.** `clean_session = 0` is accepted and then treated
    as clean. Everything worth resuming is in the archive, which is a better
    store than a broker's memory, and a queue that survives restarts is most
    of the complexity of a real broker.
  * **Bridging, clustering, `$SYS`.** One station, one broker.

What it does do is the part that matters here: retained messages. A browser
that subscribes gets the last value immediately rather than a blank dashboard
until the next reading -- which is the single most common complaint about MQTT
weather pages.

## Who may connect

The same rule as everything else here: bound to `0.0.0.0`, answered only to
private networks unless somebody says otherwise. A broker reachable from the
open internet with no password is a machine anybody can publish rubbish into,
and the readings on the page come straight from it.

Two accounts, and they are not the same:

    publish     what the station's own upload uses. Full access.
    subscribe   what goes into a public web page. Read-only, and it may be
                anonymous -- a page is served to anybody, so a credential in
                it is a credential published.

A subscriber can never publish. That is not a setting: it is the difference
between somebody reading your weather and somebody writing it.
"""

from __future__ import annotations

import logging
import socket
import socketserver
import struct
import threading
import time
from dataclasses import dataclass, field

from .mqtt import (
    CONNACK,
    CONNECT,
    DISCONNECT,
    PINGREQ,
    PINGRESP,
    PUBACK,
    PUBLISH,
    SUBACK,
    SUBSCRIBE,
    UNSUBACK,
    UNSUBSCRIBE,
    MqttError,
    Reader,
    decode_string,
    encode_length,
    encode_string,
    topic_matches,
)
from .netaccess import Access
from .websocket import (
    BINARY,
    CLOSE,
    FrameReader,
    WebSocketError,
    close_frame,
    encode_frame,
    handshake_response,
)

log = logging.getLogger(__name__)

DEFAULT_PORT = 1883
DEFAULT_WEBSOCKET_PORT = 9001

#: CONNACK return codes, as the specification names them.
ACCEPTED = 0
BAD_VERSION = 1
BAD_IDENTIFIER = 2
BAD_CREDENTIALS = 4
NOT_AUTHORISED = 5

#: How long a connection may stay silent before it is dropped, when the client
#: asked for no keepalive of its own. A browser tab in the background stops
#: sending, and a socket nobody will ever hear from again is a file handle.
IDLE_SECONDS = 600


@dataclass
class Retained:
    """The last message on a topic, kept for whoever subscribes next.

    The reason the broker is worth having rather than merely possible: a page
    that opens a subscription gets the current conditions in the same second,
    instead of an empty dashboard until the next archive interval. Without
    this a skin looks broken for up to five minutes after every load.
    """

    payload: bytes
    qos: int


@dataclass
class Session:
    """One connected client."""

    identifier: str
    write: object
    #: Topic filter -> granted QoS.
    subscriptions: dict[str, int] = field(default_factory=dict)
    may_publish: bool = False
    peer: str = ""
    connected_at: float = field(default_factory=time.time)

    def wants(self, topic: str) -> int | None:
        """The highest QoS this session subscribed to `topic` at, or None.

        Highest, because two filters can both match -- `weather/#` and
        `weather/outTemp_C` -- and delivering twice would double every
        reading on the page.
        """
        best = None
        for filter_, qos in self.subscriptions.items():
            if topic_matches(filter_, topic):
                best = qos if best is None else max(best, qos)
        return best


class Broker:
    """The state: who is connected, who wants what, and what was last said."""

    def __init__(self, publish_password: str = "",
                 subscribe_password: str = "",
                 publish_user: str = "station",
                 subscribe_user: str = "") -> None:
        self.sessions: dict[str, Session] = {}
        self.retained: dict[str, Retained] = {}
        self.publish_user = publish_user
        self.publish_password = publish_password
        self.subscribe_user = subscribe_user
        self.subscribe_password = subscribe_password
        self._lock = threading.Lock()
        self.published = 0
        self.delivered = 0

    # -- who may do what -------------------------------------------------

    def authorise(self, user: str, password: str) -> tuple[bool, bool]:
        """(allowed, may_publish) for a set of credentials.

        A publisher password that is set and wrong is refused. A subscriber
        password that is not set means anonymous reading is allowed, which is
        what a public web page needs -- and reading is all it can do.
        """
        if self.publish_password and password == self.publish_password:
            if not self.publish_user or user == self.publish_user:
                return True, True
        if self.subscribe_password:
            if password == self.subscribe_password:
                return True, False
            return False, False
        if self.publish_password and not password:
            # No subscriber password set: anonymous is read-only.
            return True, False
        if self.publish_password:
            return False, False
        # Nothing configured at all. Everything is allowed, which is only
        # sane behind the private-network rule the listener applies.
        return True, True

    # -- sessions --------------------------------------------------------

    def join(self, session: Session) -> None:
        with self._lock:
            existing = self.sessions.get(session.identifier)
            if existing is not None:
                # Two clients with one id is the specification's own rule:
                # the newcomer wins and the old one is disconnected. It is
                # also the thing that looks like a flapping network when two
                # copies of a page share a generated id.
                log.info("MQTT: %r connected again from %s; dropping the "
                         "older connection", session.identifier, session.peer)
                _close_quietly(existing.write)
            self.sessions[session.identifier] = session

    def leave(self, session: Session) -> None:
        with self._lock:
            if self.sessions.get(session.identifier) is session:
                del self.sessions[session.identifier]

    # -- messages --------------------------------------------------------

    def publish(self, topic: str, payload: bytes, qos: int,
                retain: bool) -> int:
        """Deliver to whoever wants it. Returns how many got it."""
        with self._lock:
            if retain:
                if payload:
                    self.retained[topic] = Retained(payload, qos)
                else:
                    # An empty retained message means "forget this topic".
                    # Storing it instead would hand every new subscriber an
                    # empty string where a reading used to be.
                    self.retained.pop(topic, None)
            targets = [(s, s.wants(topic)) for s in self.sessions.values()]

        self.published += 1
        sent = 0
        for session, wanted in targets:
            if wanted is None:
                continue
            try:
                session.write(_publish_packet(topic, payload,
                                              min(qos, wanted)))
                sent += 1
            except Exception:
                # One subscriber whose socket has gone must not stop the
                # others being told. Its own thread will notice and clean up.
                log.debug("MQTT: could not deliver to %r",
                          session.identifier, exc_info=True)
        self.delivered += sent
        return sent

    def subscribe(self, session: Session, filters: list[tuple[str, int]]
                  ) -> tuple[list[int], list[tuple[str, Retained, int]]]:
        """Add subscriptions. Returns the QoS granted for each -- 0x80 where
        one was refused -- and what is retained for them.

        The retained messages are handed back rather than sent, because they
        have to go **after** the SUBACK. Sending them first is accepted by
        some clients and quietly dropped by others: a subscription is not
        established until the acknowledgement, so a message arriving before
        it belongs to nothing. Only the caller knows when the SUBACK has
        gone, so only the caller can send them.
        """
        granted = []
        deliver: list[tuple[str, Retained, int]] = []
        with self._lock:
            for filter_, qos in filters:
                if not filter_ or ("#" in filter_ and not filter_.endswith("#")):
                    # `#` is only legal as the last level. A filter that
                    # breaks that is refused rather than quietly reinterpreted.
                    granted.append(0x80)
                    continue
                # QoS 2 is granted as 1. The specification allows granting
                # less than was asked for, and this broker does not do 2.
                allowed = min(qos, 1)
                session.subscriptions[filter_] = allowed
                granted.append(allowed)
                for topic, held in self.retained.items():
                    if topic_matches(filter_, topic):
                        deliver.append((topic, held, allowed))

        return granted, deliver

    def send_retained(self, session: Session,
                      deliver: list[tuple[str, Retained, int]]) -> None:
        """What `subscribe` found, once the SUBACK has gone.

        Outside the broker's lock: writing to a slow socket must not hold up
        everybody else's publishing.
        """
        for topic, held, qos in deliver:
            try:
                session.write(_publish_packet(topic, held.payload,
                                              min(held.qos, qos), retain=True))
            except Exception:
                log.debug("MQTT: could not send a retained message to %r",
                          session.identifier, exc_info=True)

    def unsubscribe(self, session: Session, filters: list[str]) -> None:
        with self._lock:
            for filter_ in filters:
                session.subscriptions.pop(filter_, None)

    def status(self) -> dict:
        with self._lock:
            return {
                "clients": len(self.sessions),
                "subscriptions": sum(len(s.subscriptions)
                                     for s in self.sessions.values()),
                "retained": len(self.retained),
                "published": self.published,
                "delivered": self.delivered,
            }


# ---------------------------------------------------------------------------
# The wire.
# ---------------------------------------------------------------------------

def _packet(kind: int, flags: int, body: bytes) -> bytes:
    return bytes([(kind << 4) | flags]) + encode_length(len(body)) + body


def _publish_packet(topic: str, payload: bytes, qos: int,
                    retain: bool = False) -> bytes:
    body = encode_string(topic)
    if qos:
        # Packet ids only have to be unique per client and unacknowledged.
        # Nothing here waits for a PUBACK from a subscriber, so a fixed one
        # is honest rather than lazy: this broker does not resend.
        body += struct.pack("!H", 1)
    flags = (qos << 1) | (1 if retain else 0)
    return _packet(PUBLISH, flags, body + payload)


def _close_quietly(write: object) -> None:
    """Ask a connection to shut down, and do not care if it already has.

    Called on a socket that is being replaced or has gone. Every reason it
    could fail here is a reason it did not need doing.
    """
    try:
        write(None)          # the writers treat None as "shut down"
    except Exception:
        log.debug("a connection was already gone when closing it",
                  exc_info=True)


class _Connection:
    """One client, whatever it arrived over.

    TCP and websocket differ only in how bytes are framed, so the protocol is
    written once here and the two transports hand it whole packets.
    """

    def __init__(self, broker: Broker, peer: str, write, read) -> None:
        self.broker = broker
        self.peer = peer
        self.write = write
        self.read = read
        self.session: Session | None = None

    def run(self) -> None:
        try:
            self._connect()
            while True:
                packet = self.read()
                if packet is None:
                    return
                kind, flags, body = packet
                if kind == PUBLISH:
                    self._publish(flags, body)
                elif kind == SUBSCRIBE:
                    self._subscribe(body)
                elif kind == UNSUBSCRIBE:
                    self._unsubscribe(body)
                elif kind == PINGREQ:
                    self.write(_packet(PINGRESP, 0, b""))
                elif kind == DISCONNECT:
                    return
                elif kind == PUBACK:
                    continue          # nothing here waits for one
                else:
                    log.debug("MQTT: %s sent packet type %s, ignoring",
                              self.peer, kind)
        except (MqttError, WebSocketError, OSError) as exc:
            log.debug("MQTT: %s went away: %s", self.peer, exc)
        except Exception:
            log.exception("MQTT: %s broke the connection", self.peer)
        finally:
            if self.session is not None:
                self.broker.leave(self.session)
            _close_quietly(self.write)

    def _connect(self) -> None:
        packet = self.read()
        if packet is None:
            raise MqttError("closed before connecting")
        kind, _flags, body = packet
        if kind != CONNECT:
            raise MqttError(f"first packet was {kind}, not CONNECT")

        name, at = decode_string(body, 0)
        level = body[at]
        flags = body[at + 1]
        # Keepalive, in seconds. Zero means the client wants no timeout at
        # all, which is not a thing a broker should honour indefinitely.
        keepalive = struct.unpack("!H", body[at + 2:at + 4])[0]
        identifier, at = decode_string(body, at + 4)

        if name != "MQTT" or level not in (4, 5):
            self.write(_packet(CONNACK, 0, bytes([0, BAD_VERSION])))
            raise MqttError(f"{self.peer} speaks {name!r} version {level}")

        if flags & 0x04:          # a will, which is skipped over and dropped
            _, at = decode_string(body, at)
            _, at = decode_string(body, at)
        user = password = ""
        if flags & 0x80:
            user, at = decode_string(body, at)
        if flags & 0x40:
            password, at = decode_string(body, at)

        allowed, may_publish = self.broker.authorise(user, password)
        if not allowed:
            self.write(_packet(CONNACK, 0, bytes([0, BAD_CREDENTIALS])))
            log.warning("MQTT: refused %s -- wrong credentials", self.peer)
            raise MqttError("bad credentials")

        if not identifier:
            # A client may send an empty id and ask the broker to make one.
            identifier = f"anon-{int(time.time() * 1000) & 0xFFFFFF:06x}"

        self.session = Session(identifier=identifier, write=self.write,
                               may_publish=may_publish, peer=self.peer)
        self.broker.join(self.session)
        self.write(_packet(CONNACK, 0, bytes([0, ACCEPTED])))
        log.info("MQTT: %s connected as %r, %s", self.peer, identifier,
                 "may publish" if may_publish else "read-only")
        self._keepalive = keepalive or IDLE_SECONDS

    def _publish(self, flags: int, body: bytes) -> None:
        topic, at = decode_string(body, 0)
        qos = (flags >> 1) & 0x03
        packet_id = 0
        if qos:
            packet_id = struct.unpack("!H", body[at:at + 2])[0]
            at += 2
        payload = body[at:]

        if self.session is None or not self.session.may_publish:
            # Read-only, so the message is dropped -- and acknowledged
            # anyway, because a client that gets no PUBACK retries forever.
            # Saying no this way is quieter than closing the connection and
            # leaves the log the only place it shows.
            log.warning("MQTT: %r tried to publish to %r and may not",
                        self.session.identifier if self.session else "?", topic)
            if qos == 1:
                self.write(_packet(PUBACK, 0, struct.pack("!H", packet_id)))
            return

        self.broker.publish(topic, payload, qos, bool(flags & 1))
        if qos == 1:
            self.write(_packet(PUBACK, 0, struct.pack("!H", packet_id)))

    def _subscribe(self, body: bytes) -> None:
        packet_id = struct.unpack("!H", body[:2])[0]
        at = 2
        filters = []
        while at < len(body):
            filter_, at = decode_string(body, at)
            filters.append((filter_, body[at]))
            at += 1
        granted, retained = self.broker.subscribe(self.session, filters)
        # SUBACK first, then whatever was held. A subscription is not
        # established until the acknowledgement, and a message arriving
        # before it is one some clients discard.
        self.write(_packet(SUBACK, 0,
                           struct.pack("!H", packet_id) + bytes(granted)))
        self.broker.send_retained(self.session, retained)
        log.debug("MQTT: %r subscribed to %s", self.session.identifier,
                  ", ".join(f for f, _ in filters))

    def _unsubscribe(self, body: bytes) -> None:
        packet_id = struct.unpack("!H", body[:2])[0]
        at = 2
        filters = []
        while at < len(body):
            filter_, at = decode_string(body, at)
            filters.append(filter_)
        self.broker.unsubscribe(self.session, filters)
        self.write(_packet(UNSUBACK, 0, struct.pack("!H", packet_id)))


# ---------------------------------------------------------------------------
# The two listeners.
# ---------------------------------------------------------------------------

class _TcpHandler(socketserver.BaseRequestHandler):
    """MQTT over a plain socket. What the station's own upload connects to."""

    broker: Broker
    access: Access

    def handle(self) -> None:
        peer = self.client_address[0]
        if not self.access.allows(peer):
            log.debug("MQTT: refusing %s", peer)
            return
        self.request.settimeout(IDLE_SECONDS)
        reader = Reader(self.request)
        lock = threading.Lock()

        def write(data: bytes | None) -> None:
            if data is None:
                try:
                    self.request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                return
            # Two threads writing to one socket interleave their bytes and
            # produce a stream the client cannot parse. A publish arriving
            # while this client is being sent a retained message is exactly
            # that case.
            with lock:
                self.request.sendall(data)

        def read():
            try:
                return reader.packet()
            except MqttError:
                return None

        _Connection(self.broker, peer, write, read).run()


class _WebSocketHandler(socketserver.BaseRequestHandler):
    """MQTT inside a websocket. What a browser connects to."""

    broker: Broker
    access: Access

    def handle(self) -> None:
        peer = self.client_address[0]
        if not self.access.allows(peer):
            return
        self.request.settimeout(IDLE_SECONDS)
        if not self._upgrade():
            return

        frames = FrameReader(self.request)
        lock = threading.Lock()
        # MQTT packets and websocket messages are not the same size: a client
        # may put two packets in one frame, or split one across two.
        pending = bytearray()

        def write(data: bytes | None) -> None:
            if data is None:
                try:
                    with lock:
                        self.request.sendall(close_frame())
                    self.request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                return
            with lock:
                self.request.sendall(encode_frame(data, BINARY))

        def read():
            while True:
                found = _take_packet(pending)
                if found is not None:
                    return found
                opcode, payload = frames.message()
                if opcode == CLOSE:
                    return None
                pending.extend(payload)

        _Connection(self.broker, peer, write, read).run()

    def _upgrade(self) -> bool:
        """Read the HTTP request and answer the handshake."""
        raw = bytearray()
        while b"\r\n\r\n" not in raw:
            chunk = self.request.recv(4096)
            if not chunk:
                return False
            raw += chunk
            if len(raw) > 16384:
                return False

        head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        lines = head.split("\r\n")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            if name:
                headers[name.strip()] = value.strip()

        response = handshake_response(headers)
        if response is None:
            # Not an upgrade. Answering with something a person can read
            # matters: this port gets opened in a browser by everybody who
            # sets it up, and a blank page teaches them nothing.
            body = (b"<!doctype html><meta charset=utf-8>"
                    b"<title>weewx-evo MQTT</title>"
                    b"<p>This is the MQTT broker's websocket port. It is not "
                    b"a web page &mdash; a skin connects to it from the "
                    b"browser.")
            self.request.sendall(
                b"HTTP/1.1 426 Upgrade Required\r\n"
                b"Content-Type: text/html; charset=utf-8\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + body)
            return False
        self.request.sendall(response)
        return True


def _take_packet(buffer: bytearray) -> tuple[int, int, bytes] | None:
    """One whole MQTT packet out of a buffer, or None if it is not there yet.

    Websockets carry messages and MQTT carries packets, and the two do not
    line up: a client may put two packets in one frame or split one across
    several. Treating a frame as a packet works right up until it does not.
    """
    if len(buffer) < 2:
        return None
    length, multiplier, at = 0, 1, 1
    while True:
        if at >= len(buffer) or at > 4:
            return None
        byte = buffer[at]
        length += (byte & 0x7F) * multiplier
        at += 1
        if not byte & 0x80:
            break
        multiplier *= 128
    if len(buffer) < at + length:
        return None
    first = buffer[0]
    body = bytes(buffer[at:at + length])
    del buffer[:at + length]
    return first >> 4, first & 0x0F, body


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class BrokerServer:
    """The broker and its two listeners, started and stopped together."""

    def __init__(self, broker: Broker, host: str = "0.0.0.0",
                 port: int = DEFAULT_PORT,
                 websocket_port: int = DEFAULT_WEBSOCKET_PORT,
                 access: Access | None = None) -> None:
        self.broker = broker
        self.host = host
        self.access = access or Access.parse("private")
        self._servers: list[_Server] = []
        self._threads: list[threading.Thread] = []
        self.port = port
        self.websocket_port = websocket_port

    def start(self) -> None:
        for port, handler, what in (
                (self.port, _TcpHandler, "MQTT"),
                (self.websocket_port, _WebSocketHandler, "MQTT over websockets")):
            if not port:
                continue
            bound = type(handler.__name__, (handler,),
                         {"broker": self.broker, "access": self.access})
            server = _Server((self.host, port), bound)
            thread = threading.Thread(target=server.serve_forever,
                                      name=f"broker-{port}", daemon=True)
            thread.start()
            self._servers.append(server)
            self._threads.append(thread)
            log.info("%s on %s:%s, answering %s", what, self.host, port,
                     self.access)

    def stop(self) -> None:
        for server in self._servers:
            server.shutdown()
            server.server_close()
        for thread in self._threads:
            thread.join(timeout=2)
        self._servers, self._threads = [], []

    def status(self) -> dict:
        found = self.broker.status()
        found.update({"host": self.host, "port": self.port,
                      "websocket_port": self.websocket_port})
        return found

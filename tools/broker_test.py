#!/usr/bin/env python3
"""The built-in MQTT broker, driven by our own client and a real websocket.

Two halves, and the second is the one that matters.

**Against `mqtt.Client`.** The client was written first and tested against a
broker written for the test; this is the same protocol from the other side. If
the two agree, both are probably reading the specification the same way -- and
where they do not, one of them is wrong in a way that would only show up
against Mosquitto.

**Against a raw websocket.** Hand-built frames, masked the way a browser masks
them, because that is the transport a page actually uses and it is the half
that has never existed here before. A frame the wrong way round works with
every library and fails in Firefox.

    python tools/broker_test.py

No network beyond loopback, and the port is chosen by the operating system so
two runs never collide.
"""

from __future__ import annotations

import base64
import os
import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import websocket as ws
from weewx_evo.broker import Broker, BrokerServer
from weewx_evo.mqtt import Client, MqttError, topic_matches
from weewx_evo.netaccess import Access

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def ok(what: str, condition: bool) -> None:
    check(what, bool(condition), True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(condition, seconds: float = 5.0) -> bool:
    """Poll rather than sleep. A fixed sleep is a flaky test on a slow box."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return False


class Running:
    """A broker on loopback, stopped whatever happens."""

    def __init__(self, **kwargs) -> None:
        self.broker = Broker(**kwargs)
        self.port = free_port()
        self.ws_port = free_port()
        self.server = BrokerServer(self.broker, host="127.0.0.1",
                                   port=self.port,
                                   websocket_port=self.ws_port,
                                   access=Access.parse("private"))

    def __enter__(self) -> Running:
        self.server.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.stop()


# ---------------------------------------------------------------------------
# Topic filters.
# ---------------------------------------------------------------------------

def test_topic_matching() -> None:
    """The two wildcards, and the rules that are not symmetric."""
    ok("an exact name", topic_matches("weather/outTemp_C", "weather/outTemp_C"))
    ok("a different one does not", not topic_matches("weather/a", "weather/b"))

    # `+` is exactly one level.
    ok("+ takes one level", topic_matches("weather/+", "weather/outTemp_C"))
    ok("and not two", not topic_matches("weather/+", "weather/a/b"))
    ok("nor none", not topic_matches("weather/+", "weather"))
    ok("in the middle too", topic_matches("a/+/c", "a/b/c"))

    # `#` takes everything below -- including the parent itself, which is the
    # rule people get wrong.
    ok("# takes the children", topic_matches("weather/#", "weather/outTemp_C"))
    ok("and the grandchildren", topic_matches("weather/#", "weather/a/b/c"))
    ok("and the parent itself", topic_matches("weather/#", "weather"))
    ok("# alone takes everything", topic_matches("#", "anything/at/all"))

    # A leading wildcard must not reach the broker's own tree. A page
    # subscribing to `#` should not be handed a broker's statistics.
    ok("# does not reach $SYS", not topic_matches("#", "$SYS/broker/uptime"))
    ok("nor does +", not topic_matches("+/broker", "$SYS/broker"))
    ok("but naming it explicitly works",
       topic_matches("$SYS/broker", "$SYS/broker"))


# ---------------------------------------------------------------------------
# The websocket layer.
# ---------------------------------------------------------------------------

def test_handshake() -> None:
    """The example from RFC 6455 itself, so the constant is right."""
    check("the accept key", ws.accept_key("dGhlIHNhbXBsZSBub25jZQ=="),
          "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    response = ws.handshake_response({
        "Upgrade": "websocket",
        "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        "Sec-WebSocket-Protocol": "mqtt",
    })
    ok("it answers 101", response.startswith(b"HTTP/1.1 101"))
    ok("with the accept header", b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in response)
    # Browser MQTT libraries ask for the `mqtt` subprotocol and several refuse
    # a server that does not answer with it.
    ok("and echoes the subprotocol", b"Sec-WebSocket-Protocol: mqtt" in response)

    # A subprotocol nobody offered must not be claimed -- that is itself a
    # protocol error.
    plain = ws.handshake_response({"Upgrade": "websocket",
                                   "Sec-WebSocket-Key": "abc"})
    ok("nothing is claimed unasked", b"Sec-WebSocket-Protocol" not in plain)
    ok("a request that is not an upgrade is refused",
       ws.handshake_response({"Host": "x"}) is None)


def test_framing() -> None:
    """The three length forms, and the masking rule."""
    small = ws.encode_frame(b"hi", ws.BINARY)
    check("a short frame's header", small[:2], bytes([0x82, 2]))

    medium = ws.encode_frame(b"x" * 200, ws.BINARY)
    check("126 means a two-byte length", medium[1], 126)
    check("and it is big-endian", struct.unpack("!H", medium[2:4])[0], 200)

    large = ws.encode_frame(b"x" * 70000, ws.BINARY)
    check("127 means eight bytes", large[1], 127)
    check("also big-endian", struct.unpack("!Q", large[2:10])[0], 70000)

    # A server must never mask; a client always must. Getting it backwards
    # works against every library and fails in a browser.
    ok("a server frame is not masked", not (small[1] & 0x80))
    masked = ws.encode_frame(b"hi", ws.BINARY, mask=True)
    ok("a client frame is", bool(masked[1] & 0x80))
    check("and it unmasks back", _unmask(masked), b"hi")


def _unmask(frame: bytes) -> bytes:
    length = frame[1] & 0x7F
    key = frame[2:6]
    payload = frame[6:6 + length]
    return bytes(b ^ key[i % 4] for i, b in enumerate(payload))


# ---------------------------------------------------------------------------
# The broker, over TCP.
# ---------------------------------------------------------------------------

def test_publish_and_subscribe() -> None:
    with Running() as running:
        got: list[tuple[str, bytes]] = []
        listener = Client("127.0.0.1", running.port, client_id="reader",
                          on_message=lambda t, p: got.append((t, p)))
        listener.connect()
        listener.subscribe("weather/#")

        # A second client publishes, and a background thread reads for the
        # first -- which is how a subscriber actually works.
        stop = threading.Event()

        def pump():
            while not stop.is_set():
                try:
                    listener.pump(0.2)
                except Exception:
                    return

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()

        writer = Client("127.0.0.1", running.port, client_id="station")
        writer.connect()
        writer.publish("weather/outTemp_C", "21.4")
        writer.publish("weather/loop", '{"outTemp_C":21.4}', qos=1)
        writer.publish("other/thing", "not for you")

        ok("both matching messages arrived", wait_for(lambda: len(got) >= 2))
        stop.set()
        thread.join(timeout=2)
        writer.close()
        listener.close()

    topics = dict(got)
    check("the individual topic", topics.get("weather/outTemp_C"), b"21.4")
    check("the json document", topics.get("weather/loop"),
          b'{"outTemp_C":21.4}')
    ok("and nothing that did not match the filter",
       "other/thing" not in topics)


def test_retained() -> None:
    """The reason the broker is worth having rather than merely possible.

    A page that opens a subscription gets the current conditions in the same
    second, instead of an empty dashboard until the next reading.
    """
    with Running() as running:
        writer = Client("127.0.0.1", running.port, client_id="station")
        writer.connect()
        writer.publish("weather/loop", '{"outTemp_C":21.4}', retain=True)
        writer.publish("weather/nothing", "transient")   # not retained
        writer.close()

        got: list[tuple[str, bytes]] = []
        # Connecting afterwards: nothing is being published now, so anything
        # that arrives was held for this subscriber.
        listener = Client("127.0.0.1", running.port, client_id="late",
                          on_message=lambda t, p: got.append((t, p)))
        listener.connect()
        listener.subscribe("weather/#")
        listener.pump(1.0)
        listener.close()

    check("the retained message was waiting", [t for t, _ in got],
          ["weather/loop"])
    check("with its payload", got[0][1], b'{"outTemp_C":21.4}')


def test_retained_can_be_cleared() -> None:
    """An empty retained message means forget the topic.

    Storing it instead hands every new subscriber an empty string where a
    reading used to be, which a page renders as a blank tile.
    """
    with Running() as running:
        writer = Client("127.0.0.1", running.port, client_id="station")
        writer.connect()
        writer.publish("weather/loop", "21.4", retain=True)
        ok("it is held", wait_for(lambda: "weather/loop" in running.broker.retained))
        writer.publish("weather/loop", b"", retain=True)
        ok("and an empty one forgets it",
           wait_for(lambda: "weather/loop" not in running.broker.retained))
        writer.close()


def test_one_message_per_client() -> None:
    """Two filters that both match must not deliver twice.

    `weather/#` and `weather/outTemp_C` are both legitimate and a page can
    hold both. Delivering to each would double every reading on it.
    """
    with Running() as running:
        got: list[str] = []
        listener = Client("127.0.0.1", running.port, client_id="reader",
                          on_message=lambda t, _p: got.append(t))
        listener.connect()
        listener.subscribe("weather/#")
        listener.subscribe("weather/outTemp_C")

        writer = Client("127.0.0.1", running.port, client_id="station")
        writer.connect()
        writer.publish("weather/outTemp_C", "21.4")
        listener.pump(0.6)
        writer.close()
        listener.close()

    check("delivered once, not twice", got, ["weather/outTemp_C"])


def test_a_subscriber_may_not_publish() -> None:
    """The difference between reading your weather and writing it."""
    with Running(publish_password="secret",
                 subscribe_password="") as running:
        # The station: right password, may publish.
        writer = Client("127.0.0.1", running.port, client_id="station",
                        username="station", password="secret")
        writer.connect()
        writer.publish("weather/loop", "21.4", retain=True)
        writer.close()
        ok("the station's message was kept",
           wait_for(lambda: "weather/loop" in running.broker.retained))

        # A page: no password, read-only. It connects and reads.
        page = Client("127.0.0.1", running.port, client_id="page")
        page.connect()
        got: list[str] = []
        page.on_message = lambda t, _p: got.append(t)
        page.subscribe("weather/#")
        page.pump(0.6)
        ok("a page may read", got == ["weather/loop"])

        # And may not write. The publish is accepted at the socket level --
        # refusing it there would make the client retry forever -- and
        # dropped.
        page.publish("weather/loop", "999", retain=True)
        time.sleep(0.2)
        check("the reading was not overwritten",
              running.broker.retained["weather/loop"].payload, b"21.4")
        page.close()


def test_a_wrong_password_is_refused() -> None:
    with Running(publish_password="secret",
                 subscribe_password="readonly") as running:
        client = Client("127.0.0.1", running.port, client_id="x",
                        username="station", password="wrong")
        try:
            client.connect()
        except MqttError as exc:
            ok("it says the credentials are wrong",
               "user name or password" in str(exc))
            ok("and that retrying will not help", exc.permanent)
        else:
            FAILURES.append("the broker accepted a wrong password")
            client.close()


def test_one_id_at_a_time() -> None:
    """The specification's own rule: the newcomer wins.

    Also what looks like a flapping network when two copies of a page share
    a generated client id.
    """
    with Running() as running:
        first = Client("127.0.0.1", running.port, client_id="same")
        first.connect()
        ok("the first is registered",
           wait_for(lambda: "same" in running.broker.sessions))
        session = running.broker.sessions["same"]

        second = Client("127.0.0.1", running.port, client_id="same")
        second.connect()
        ok("the second replaced it",
           wait_for(lambda: running.broker.sessions.get("same") is not session))
        check("and there is still only one", len(running.broker.sessions), 1)
        second.close()


# ---------------------------------------------------------------------------
# The broker, over a websocket -- the half a browser uses.
# ---------------------------------------------------------------------------

class Browserish:
    """A websocket client built by hand, masking the way a browser does."""

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        self.sock.sendall(
            f"GET /mqtt HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Protocol: mqtt\r\n\r\n".encode("ascii"))
        raw = b""
        while b"\r\n\r\n" not in raw:
            raw += self.sock.recv(4096)
        self.head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        # Reading what the server sends, which is never masked.
        self.frames = ws.FrameReader(self.sock, expect_masked=False)
        # Anything the server sent after the handshake, in the same read.
        leftover = raw.split(b"\r\n\r\n", 1)[1]
        if leftover:
            self.frames._buffer.extend(leftover)

    def send(self, packet: bytes) -> None:
        # Masked, because a client must. A server that does not enforce that
        # is one a browser will still talk to; one that does not *accept* it
        # is one a browser cannot.
        self.sock.sendall(ws.encode_frame(packet, ws.BINARY, mask=True))

    def read(self, seconds: float = 2.0) -> bytes:
        self.sock.settimeout(seconds)
        _opcode, payload = self.frames.message()
        return payload

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _connect_packet(client_id: str) -> bytes:
    from weewx_evo.mqtt import encode_length, encode_string

    body = (encode_string("MQTT") + bytes([4, 0x02]) + struct.pack("!H", 60)
            + encode_string(client_id))
    return bytes([1 << 4]) + encode_length(len(body)) + body


def _subscribe_packet(topic: str) -> bytes:
    from weewx_evo.mqtt import encode_length, encode_string

    body = struct.pack("!H", 1) + encode_string(topic) + bytes([0])
    return bytes([(8 << 4) | 0x02]) + encode_length(len(body)) + body


def test_a_browser_can_subscribe() -> None:
    """The whole point: a page, over a websocket, getting a retained reading."""
    with Running() as running:
        writer = Client("127.0.0.1", running.port, client_id="station")
        writer.connect()
        writer.publish("weather/loop", '{"outTemp_C":21.4}', retain=True)
        ok("the station published",
           wait_for(lambda: "weather/loop" in running.broker.retained))

        page = Browserish(running.ws_port)
        ok("the handshake succeeded", page.head.startswith("HTTP/1.1 101"))
        ok("and named the subprotocol", "Sec-WebSocket-Protocol: mqtt" in page.head)

        page.send(_connect_packet("page"))
        connack = page.read()
        check("CONNACK came back", connack[0] >> 4, 2)
        check("and it was accepted", connack[-1], 0)

        page.send(_subscribe_packet("weather/#"))
        suback = page.read()
        check("SUBACK came back", suback[0] >> 4, 9)

        # The retained message follows on its own, without anything being
        # published now. That is what makes a page show conditions on load.
        message = page.read()
        check("a PUBLISH followed", message[0] >> 4, 3)
        ok("with the reading in it", b'{"outTemp_C":21.4}' in message)

        # And a live one arrives too.
        writer.publish("weather/loop", '{"outTemp_C":22.0}')
        live = page.read()
        ok("a live message arrives as well", b'{"outTemp_C":22.0}' in live)

        page.close()
        writer.close()


def test_the_websocket_port_says_what_it_is() -> None:
    """Somebody will open it in a browser. A blank page teaches nothing."""
    with Running() as running:
        sock = socket.create_connection(("127.0.0.1", running.ws_port),
                                        timeout=5)
        sock.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        answer = sock.recv(4096).decode("latin-1")
        sock.close()
    ok("it answers 426", answer.startswith("HTTP/1.1 426"))
    ok("and explains itself", "MQTT broker" in answer)


def test_two_packets_in_one_frame() -> None:
    """Websockets carry messages, MQTT carries packets, and they do not line up.

    A client may put two packets in one frame. Treating a frame as a packet
    works right up until a library batches, and then half the connection is
    silently lost.
    """
    with Running() as running:
        page = Browserish(running.ws_port)
        # CONNECT and SUBSCRIBE in a single websocket frame.
        page.send(_connect_packet("batched") + _subscribe_packet("weather/#"))
        connack = page.read()
        check("the first packet was read", connack[0] >> 4, 2)
        ok("and the second was too, from the same frame",
           wait_for(lambda: any(
               s.subscriptions for s in running.broker.sessions.values())))
        page.close()


def test_status() -> None:
    with Running() as running:
        client = Client("127.0.0.1", running.port, client_id="one")
        client.connect()
        client.subscribe("weather/#")
        client.publish("weather/loop", "21.4", retain=True)
        ok("it counts what happened",
           wait_for(lambda: running.broker.status()["published"] >= 1))
        found = running.server.status()
        check("one client", found["clients"], 1)
        check("one subscription", found["subscriptions"], 1)
        check("one retained topic", found["retained"], 1)
        ok("and it names its ports", found["port"] == running.port)
        client.close()


def test_the_whole_chain() -> None:
    """Station to our own broker to a browser, with nothing else installed.

    This is the case the broker exists for. Before it, the same picture
    needed Mosquitto in the middle with two listeners and its own
    configuration file -- a third program, configured in a place nothing here
    can read.
    """
    from weewx_evo.uploads.mqtt import MqttUpload

    with Running() as running:
        upload = MqttUpload(host="127.0.0.1", port=running.port,
                            topic="weather", individual=False,
                            websockets_port=running.ws_port)

        # What the skin is handed. The port is the websocket one, not the
        # MQTT one -- a browser cannot open the second.
        browser = upload.browser()
        check("the skin is pointed at the websocket port", browser["port"],
              running.ws_port)
        check("and at the topic the upload publishes", browser["topic"],
              "weather/loop")

        page = Browserish(running.ws_port)
        page.send(_connect_packet("page"))
        page.read()                                   # CONNACK
        page.send(_subscribe_packet(browser["topic"]))
        page.read()                                   # SUBACK

        # A real archive record, through the real upload.
        record = {"dateTime": 1756308600, "usUnits": 17, "outTemp": 21.4,
                  "outHumidity": 61.0, "windSpeed": 3.2}
        result = upload.post([record])
        ok("the upload published", result.sent >= 1)

        message = page.read()
        check("a PUBLISH reached the page", message[0] >> 4, 3)
        ok("carrying the reading", b'"outTemp_C":21.4' in message)
        ok("and its timestamp", b'"dateTime":1756308600' in message)

        page.close()
        upload.close()


def main() -> int:
    test_topic_matching()
    test_handshake()
    test_framing()
    test_publish_and_subscribe()
    test_retained()
    test_retained_can_be_cleared()
    test_one_message_per_client()
    test_a_subscriber_may_not_publish()
    test_a_wrong_password_is_refused()
    test_one_id_at_a_time()
    test_a_browser_can_subscribe()
    test_the_websocket_port_says_what_it_is()
    test_two_packets_in_one_frame()
    test_the_whole_chain()
    test_status()

    print()
    for failure in FAILURES:
        print("FAIL", failure)
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The MQTT client, against a broker written here.

A hand-written protocol client with no test is a promise, not code. So this
runs a broker on loopback -- enough of MQTT 3.1.1 to answer honestly -- and
checks what actually goes over the socket: the byte layout of CONNECT, that a
QoS 1 publish waits for its own PUBACK and not the next packet to arrive, that
a refused password is refused permanently, and that a dropped connection comes
back with its subscriptions intact.

The broker is deliberately strict. A broker that accepts whatever arrives
tests nothing: this one rejects a SUBSCRIBE whose fixed flags are not 0b0010,
because a real broker closes the connection without saying why and that is a
long afternoon.

    python tools/mqtt_test.py

No network, no state outside a temporary directory, and the port is chosen by
the operating system so two runs never collide.
"""

from __future__ import annotations

import json
import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.mqtt import Client, MqttError, encode_length, encode_string
from weewx_evo.uploads.mqtt import MqttUpload, topic_name

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def ok(what: str, condition: bool) -> None:
    check(what, bool(condition), True)


# ---------------------------------------------------------------------------
# A broker, just enough of one.
# ---------------------------------------------------------------------------

class Broker(threading.Thread):
    """MQTT 3.1.1, the parts a publisher and a subscriber touch."""

    def __init__(self, refuse: int = 0, drop_after: int = 0) -> None:
        super().__init__(daemon=True)
        #: A CONNACK return code to answer with. 4 is a bad password.
        self.refuse = refuse
        #: Close the connection after this many PUBLISH packets, to make the
        #: client reconnect. Zero never drops.
        self.drop_after = drop_after

        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]

        self.published: list[tuple[str, bytes, int, bool]] = []
        self.subscribed: list[str] = []
        self.connects: list[dict] = []
        self.pings = 0
        self.protocol_errors: list[str] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # -- reading ---------------------------------------------------------

    @staticmethod
    def _exactly(conn: socket.socket, count: int) -> bytes:
        chunks, left = [], count
        while left:
            chunk = conn.recv(left)
            if not chunk:
                raise ConnectionError("closed")
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)

    def _packet(self, conn: socket.socket) -> tuple[int, int, bytes]:
        first = self._exactly(conn, 1)[0]
        length, multiplier = 0, 1
        while True:
            byte = self._exactly(conn, 1)[0]
            length += (byte & 0x7F) * multiplier
            if not byte & 0x80:
                break
            multiplier *= 128
        return first >> 4, first & 0x0F, self._exactly(conn, length) if length else b""

    @staticmethod
    def _string(body: bytes, at: int) -> tuple[str, int]:
        length = struct.unpack("!H", body[at:at + 2])[0]
        return body[at + 2:at + 2 + length].decode("utf-8"), at + 2 + length

    # -- serving ---------------------------------------------------------

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        published = 0
        try:
            kind, _flags, body = self._packet(conn)
            if kind != 1:
                self.protocol_errors.append(f"first packet was {kind}, not CONNECT")
                return
            name, at = self._string(body, 0)
            level = body[at]
            flags = body[at + 1]
            keepalive = struct.unpack("!H", body[at + 2:at + 4])[0]
            client_id, at = self._string(body, at + 4)
            username = password = ""
            if flags & 0x80:
                username, at = self._string(body, at)
            if flags & 0x40:
                password, at = self._string(body, at)
            with self._lock:
                self.connects.append({
                    "name": name, "level": level, "flags": flags,
                    "keepalive": keepalive, "client_id": client_id,
                    "username": username, "password": password,
                })
            conn.sendall(bytes([2 << 4, 2, 0, self.refuse]))
            if self.refuse:
                return

            while not self._stop.is_set():
                kind, flags, body = self._packet(conn)
                if kind == 3:                                   # PUBLISH
                    topic, at = self._string(body, 0)
                    qos = (flags >> 1) & 0x03
                    packet_id = 0
                    if qos:
                        packet_id = struct.unpack("!H", body[at:at + 2])[0]
                        at += 2
                    with self._lock:
                        self.published.append(
                            (topic, body[at:], qos, bool(flags & 1)))
                    published += 1
                    if qos == 1:
                        if self.drop_after and published == self.drop_after:
                            # Drop *before* acknowledging, which is the case
                            # that matters: the client must not treat an
                            # unacknowledged publish as sent.
                            conn.close()
                            return
                        # A stray PUBLISH to the client first: a client that
                        # takes the next packet for its PUBACK fails here.
                        stray = encode_string("noise/x") + b"hello"
                        conn.sendall(bytes([3 << 4]) + encode_length(len(stray))
                                     + stray)
                        conn.sendall(bytes([4 << 4, 2]) + struct.pack("!H", packet_id))
                    elif self.drop_after and published == self.drop_after:
                        conn.close()
                        return
                elif kind == 8:                                 # SUBSCRIBE
                    if flags != 0x02:
                        self.protocol_errors.append(
                            f"SUBSCRIBE flags were {flags:#04x}, must be 0x02")
                        conn.close()
                        return
                    packet_id = struct.unpack("!H", body[:2])[0]
                    topic, at = self._string(body, 2)
                    with self._lock:
                        self.subscribed.append(topic)
                    conn.sendall(bytes([9 << 4, 3]) + struct.pack("!H", packet_id)
                                 + bytes([body[at]]))
                elif kind == 12:                                # PINGREQ
                    with self._lock:
                        self.pings += 1
                    conn.sendall(bytes([13 << 4, 0]))
                elif kind == 14:                                # DISCONNECT
                    return
        except (ConnectionError, OSError, IndexError, struct.error):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    # -- waiting ---------------------------------------------------------

    def until(self, condition, seconds: float = 5.0) -> bool:
        """Wait for the broker to have seen something. Never a fixed sleep.

        A sleep long enough on this machine today is too short on a loaded
        one, and the failure it produces looks like a protocol bug. This
        polls instead, so a slow machine is slow rather than wrong.
        """
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            with self._lock:
                if condition(self):
                    return True
            time.sleep(0.005)
        return False

    def messages(self, count: int, seconds: float = 5.0) -> bool:
        return self.until(lambda b: len(b.published) >= count, seconds)

    def stop(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# The checks.
# ---------------------------------------------------------------------------

def test_connect_bytes() -> None:
    """CONNECT is a byte layout. Every field is checked, not assumed."""
    broker = Broker()
    broker.start()
    try:
        client = Client("127.0.0.1", broker.port, client_id="station-1",
                        username="user", password="pw", keepalive=45)
        client.connect()
        client.close()
        ok("the connection arrived",
           broker.until(lambda b: len(b.connects) >= 1))
    finally:
        broker.stop()
    check("one connection arrived", len(broker.connects), 1)
    got = broker.connects[0]
    check("protocol name", got["name"], "MQTT")
    check("protocol level is 3.1.1", got["level"], 4)
    check("client id", got["client_id"], "station-1")
    check("user name", got["username"], "user")
    check("password", got["password"], "pw")
    check("keepalive", got["keepalive"], 45)
    # clean session (0x02) | password (0x40) | user name (0x80)
    check("connect flags", got["flags"], 0xC2)


def test_publish_and_retain() -> None:
    broker = Broker()
    broker.start()
    try:
        client = Client("127.0.0.1", broker.port)
        client.connect()
        client.publish("weather/outTemp_C", "21.4", retain=True)
        client.publish("weather/loop", '{"outTemp_C":21.4}', qos=1)
        ok("both messages arrived", broker.messages(2))
        client.close()
    finally:
        broker.stop()
    check("two messages arrived", len(broker.published), 2)
    topic, payload, qos, retain = broker.published[0]
    check("topic", topic, "weather/outTemp_C")
    check("payload", payload, b"21.4")
    check("retained", retain, True)
    check("QoS 0", qos, 0)
    topic, payload, qos, retain = broker.published[1]
    check("the JSON topic", topic, "weather/loop")
    check("QoS 1", qos, 1)
    check("no protocol errors", broker.protocol_errors, [])


def test_qos1_waits_for_its_own_puback() -> None:
    """The broker sends an unrelated PUBLISH before the PUBACK.

    A client that takes the next packet as its acknowledgement passes every
    simple test and then breaks the moment somebody also subscribes. This is
    that case, made to happen on purpose.
    """
    broker = Broker()
    broker.start()
    delivered: list[tuple[str, bytes]] = []
    try:
        client = Client("127.0.0.1", broker.port,
                        on_message=lambda t, p: delivered.append((t, p)))
        client.connect()
        client.publish("weather/loop", "x", qos=1)
        ok("the message arrived", broker.messages(1))
        client.close()
    finally:
        broker.stop()
    check("the publish completed", len(broker.published), 1)
    check("the stray message was delivered, not mistaken for the PUBACK",
          delivered, [("noise/x", b"hello")])


def test_a_bad_password_is_permanent() -> None:
    broker = Broker(refuse=4)
    broker.start()
    try:
        client = Client("127.0.0.1", broker.port, username="u", password="no")
        try:
            client.connect()
        except MqttError as exc:
            ok("a refused password says so", "bad user name or password" in str(exc))
            ok("and is marked permanent", exc.permanent)
        else:
            FAILURES.append("a refused connection was accepted")
    finally:
        broker.stop()


def test_reconnect_keeps_subscriptions() -> None:
    """A dropped connection comes back subscribed to what it had."""
    broker = Broker(drop_after=1)
    broker.start()
    try:
        client = Client("127.0.0.1", broker.port)
        client.connect()
        client.subscribe("commands/#", qos=1)
        try:
            client.publish("weather/x", "1", qos=1)   # dropped before PUBACK
        except MqttError:
            pass
        # The next publish reconnects, and the subscription must come with it.
        client.publish("weather/x", "2")
        ok("the second connection subscribed again",
           broker.until(lambda b: len(b.subscribed) >= 2))
        client.close()
    finally:
        broker.stop()
    check("subscribed twice: once, then again after the drop",
          broker.subscribed, ["commands/#", "commands/#"])
    check("two connections were made", len(broker.connects), 2)
    check("no protocol errors", broker.protocol_errors, [])


def test_length_encoding() -> None:
    """MQTT's variable-length integer, at every boundary."""
    check("0", encode_length(0), b"\x00")
    check("127", encode_length(127), b"\x7f")
    check("128", encode_length(128), b"\x80\x01")
    check("16383", encode_length(16383), b"\xff\x7f")
    check("16384", encode_length(16384), b"\x80\x80\x01")
    check("2097151", encode_length(2097151), b"\xff\xff\x7f")
    check("2097152", encode_length(2097152), b"\x80\x80\x80\x01")


def test_topic_names() -> None:
    """The names a skin subscribes to. These are not ours to change."""
    check("Celsius", topic_name("outTemp", "degree_C", True), "outTemp_C")
    check("Fahrenheit", topic_name("outTemp", "degree_F", True), "outTemp_F")
    check("miles per hour", topic_name("windSpeed", "mile_per_hour", True),
          "windSpeed_mph")
    check("metres per second", topic_name("windSpeed", "meter_per_second", True),
          "windSpeed_mps")
    # A bearing and a percentage carry no suffix, on purpose.
    check("a compass bearing has no suffix",
          topic_name("windDir", "degree_compass", True), "windDir")
    check("a percentage has no suffix",
          topic_name("outHumidity", "percent", True), "outHumidity")
    check("an unlisted unit keeps its name",
          topic_name("barometer", "mbar", True), "barometer_mbar")
    check("switched off, nothing is appended",
          topic_name("outTemp", "degree_C", False), "outTemp")


def test_the_upload_shapes_a_record() -> None:
    broker = Broker()
    broker.start()
    record = {"dateTime": 1756308600, "usUnits": 17, "interval": 5,
              "outTemp": 23.4, "outHumidity": 61.0, "windSpeed": 3.2,
              "windDir": 245.0, "barometer": 1013.2}
    try:
        upload = MqttUpload(host="127.0.0.1", port=broker.port,
                            unit_system="METRICWX")
        result = upload.post([record])
        ok("everything published arrived",
           broker.until(lambda b: any(t == "weather/loop"
                                      for t, _p, _q, _r in b.published)))
        upload.close()
    finally:
        broker.stop()
    ok("something was published", result.sent > 0)
    check("the record was marked sent", result.through, 1756308600)

    topics = {topic: payload for topic, payload, _q, _r in broker.published}
    ok("the JSON document went out", "weather/loop" in topics)
    ok("individual topics went out too", "weather/outTemp_C" in topics)
    check("temperature", topics["weather/outTemp_C"], b"23.4")
    check("a bearing has no unit suffix", "weather/windDir" in topics, True)
    ok("usUnits is not published", "weather/usUnits" not in topics)
    ok("interval is not published", "weather/interval" not in topics)

    document = json.loads(topics["weather/loop"])
    check("the document carries the timestamp", document["dateTime"], 1756308600)
    check("and the temperature under the same name", document["outTemp_C"], 23.4)
    ok("and not usUnits", "usUnits" not in document)


def test_the_upload_converts() -> None:
    """A US console and a metric broker: the archive keeps what arrived."""
    broker = Broker()
    broker.start()
    record = {"dateTime": 1756308600, "usUnits": 1, "outTemp": 74.12}
    try:
        upload = MqttUpload(host="127.0.0.1", port=broker.port,
                            unit_system="METRICWX", individual=True,
                            aggregate=False)
        upload.post([record])
        ok("the reading arrived",
           broker.until(lambda b: any(t == "weather/outTemp_C"
                                      for t, _p, _q, _r in b.published)))
        upload.close()
    finally:
        broker.stop()
    topics = {topic: payload for topic, payload, _q, _r in broker.published}
    ok("published in Celsius", "weather/outTemp_C" in topics)
    check("converted", round(float(topics["weather/outTemp_C"]), 1), 23.4)


def test_the_live_path(tmp: Path) -> None:
    """A packet reaches the broker without waiting for the archive record.

    This is the whole point of the live trigger. An archive record is a
    five-minute average that arrives five minutes late; a dashboard showing
    one is out of date for almost all of that. The packets are already in the
    live table, so the upload reads them there.
    """
    from weewx_evo.db.live import LiveStore, Packet
    from weewx_evo.uploads import records as upload_records
    from weewx_evo.uploads.progress import Progress
    from weewx_evo.uploads.runner import Scheduled

    db = tmp / "live.sdb"
    store = LiveStore(db)
    store.add(Packet(dateTime=1756308600, usUnits=17,
                     data={"outTemp": 21.0}, source="test"))
    store.close()

    broker = Broker()
    broker.start()
    packets = upload_records.live_source(db)
    try:
        upload = MqttUpload(host="127.0.0.1", port=broker.port,
                            trigger="live", every=1, aggregate=True,
                            individual=False)
        entry = Scheduled("live", upload, Progress(tmp / "progress.json"),
                          records=lambda _after, _limit: [],
                          packets=packets)
        ok("it knows it is live", entry.is_live)
        entry.run()
        ok("the first packet went", broker.until(
            lambda b: any(t == "weather/loop" for t, _p, _q, _r in b.published)))
        first = len(broker.published)

        # Nothing new: it must not republish the same packet every second.
        entry.run()
        check("an unchanged live table publishes nothing",
              len(broker.published), first)

        # A new packet, and it goes.
        store = LiveStore(db)
        store.add(Packet(dateTime=1756308660, usUnits=17,
                         data={"outTemp": 21.4}, source="test"))
        store.close()
        entry.run()
        ok("the next packet went too",
           broker.until(lambda b: len(b.published) > first))
        upload.close()
    finally:
        packets.close()
        broker.stop()

    latest = json.loads([p for t, p, _q, _r in broker.published
                         if t == "weather/loop"][-1])
    check("with the newer reading", latest["outTemp_C"], 21.4)
    check("and its own timestamp", latest["dateTime"], 1756308660)

    # The live path must not move the archive mark: the two are different
    # questions, and letting a packet answer the record one would make an
    # upload skip archive records it never sent.
    check("the archive progress is untouched",
          Progress(tmp / "progress.json").through("live"), 0)


def main() -> int:
    import tempfile

    test_length_encoding()
    test_topic_names()
    test_connect_bytes()
    test_publish_and_retain()
    test_qos1_waits_for_its_own_puback()
    test_a_bad_password_is_permanent()
    test_reconnect_keeps_subscriptions()
    test_the_upload_shapes_a_record()
    test_the_upload_converts()
    with tempfile.TemporaryDirectory() as tmp:
        test_the_live_path(Path(tmp))

    print()
    for failure in FAILURES:
        print("FAIL", failure)
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

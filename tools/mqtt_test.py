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
        #: The connection being served, so the broker can publish *to* the
        #: client. Every test until now only ever read from it.
        self._live: socket.socket | None = None
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
        self._live = conn
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
            self._live = None
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

    def deliver(self, topic: str, payload: bytes, qos: int = 0) -> bool:
        """Publish to the connected client. The direction a collector needs.

        Waits for a connection rather than assuming one: the subscriber
        connects on its own thread, and a test that publishes into nothing
        fails somewhere else entirely.
        """
        if not self.until(lambda b: b._live is not None, 5.0):
            return False
        body = encode_string(topic) + payload
        head = bytes([(3 << 4) | (qos << 1)]) + encode_length(len(body))
        try:
            self._live.sendall(head + body)
        except OSError:
            return False
        return True

    def stop(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# The checks.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# The other direction: a broker as a station.
# ---------------------------------------------------------------------------

def a_subscription(broker: Broker | None = None, **kw):
    """A subscription, delivering nothing.

    Without a broker for the checks that are about naming readings: those
    need no socket, and one they do not use is a port left open on every
    run.
    """
    from weewx_evo.ingest import mqttsub

    settings = {"host": "127.0.0.1", "topic": "#", "bundle": 0.0,
                "dry_run": True}
    if broker is not None:
        settings["port"] = broker.port
    settings.update(kw)
    return mqttsub.Subscription(**settings)


def test_a_json_document_becomes_one_packet() -> None:
    """Zigbee2MQTT's shape: one topic, several readings.

    The map is from key to archive field name, and a key nobody named is
    counted rather than guessed at. Which column a reading belongs in is the
    one decision that cannot be undone afterwards.
    """
    sub = a_subscription()
    sub.field_map = {"temperature": "outTemp", "humidity": "outHumidity"}
    sub.take("zigbee2mqtt/garten",
             b'{"temperature": 21.5, "humidity": 60, "linkquality": 84}')

    packet = sub.flush()
    check("one packet", packet is not None, True)
    check("with both named readings", sorted(packet.data),
          ["outHumidity", "outTemp"])
    check("the temperature", packet.data["outTemp"], 21.5)
    check("and the unnamed key is counted, not guessed at",
          "zigbee2mqtt/garten/linkquality" in sub.unmapped, True)


def test_one_topic_per_value_becomes_one_packet_too() -> None:
    """The other ordinary shape, and the reason for the bundle window.

    A packet per message would give an archive interval two records that each
    know half of what happened -- `outTemp` alone a second before
    `outHumidity` alone.
    """
    sub = a_subscription(bundle=5.0)
    sub.field_map = {"home/garden/temp": "outTemp",
                     "home/garden/hum": "outHumidity"}
    sub.take("home/garden/temp", b"21.5")
    check("nothing goes out yet", sub.due(), False)
    sub.take("home/garden/hum", b"60")

    packet = sub.flush()
    check("both readings in one packet", sorted(packet.data),
          ["outHumidity", "outTemp"])


def test_a_wildcard_in_the_map_matches_but_an_exact_name_wins() -> None:
    """A map with both `home/+/temp` and `home/shed/temp` means the specific
    one where it applies. Dictionary order is not somewhere to put that."""
    sub = a_subscription()
    sub.field_map = {"home/+/temp": "extraTemp1", "home/shed/temp": "outTemp"}

    check("the specific one wins", sub._named_by_topic("home/shed/temp"),
          "outTemp")
    check("and the wildcard covers the rest",
          sub._named_by_topic("home/garage/temp"), "extraTemp1")


def test_a_payload_that_says_when_keeps_its_own_time() -> None:
    """Timestamping on arrival is a different measurement, and it looks
    identical afterwards."""
    sub = a_subscription()
    sub.field_map = {"temperature": "outTemp"}
    sub.take("s", b'{"dateTime": 1756308600, "temperature": 21.5}')
    check("the payload's own time", sub.flush().dateTime, 1756308600)

    sub.take("s", b'{"temperature": 21.5}')
    stamped = sub.flush().dateTime
    check("and arrival where there is none",
          abs(stamped - int(time.time())) < 5, True)


def test_what_a_broker_publishes_that_is_not_a_number() -> None:
    """Strings, booleans and nulls all turn up on a broker."""
    from weewx_evo.ingest.mqttsub import _number

    check("a string number", _number("21.5"), 21.5)
    check("a boolean is a number", _number(True), 1.0)
    check("false too", _number(False), 0.0)
    check("null is nothing", _number(None), None)
    check("and a word is nothing", _number("ON"), None)
    check("nor an empty string", _number("  "), None)


def test_a_bare_number_on_an_unnamed_topic_is_dropped() -> None:
    """Counted and named in `check`, because the output somebody needs is
    the list of topics they have not written down yet."""
    sub = a_subscription()
    sub.take("home/somewhere/else", b"42")
    check("nothing was made of it", sub.flush(), None)
    check("but it is named", sub.unmapped.get("home/somewhere/else"), 1)


def test_it_subscribes_and_reads_what_the_broker_sends() -> None:
    """The whole way through, against a real socket.

    Not a mock: the thing being checked is that our own client, turned
    around, reads a PUBLISH the way a broker sends one.
    """
    broker = Broker()
    broker.start()
    try:
        sub = a_subscription(broker)
        sub.field_map = {"temperature": "outTemp"}
        sub.connect()
        check("it subscribed",
              broker.until(lambda b: b.subscribed == ["#"]), True)

        broker.deliver("zigbee2mqtt/garten", b'{"temperature": 19.25}')
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not sub.messages:
            sub.client.pump(0.1)
        check("the message arrived", sub.messages, 1)

        packet = sub.flush()
        check("and became a reading", packet.data.get("outTemp"), 19.25)
    finally:
        sub._drop()
        broker.stop()


def test_a_broker_that_refuses_permanently_is_not_retried() -> None:
    """Bad credentials do not become better by asking every thirty seconds
    for a week. The log line is the useful output."""
    broker = Broker(refuse=4)          # bad user name or password
    broker.start()
    try:
        sub = a_subscription(broker)
        started = time.monotonic()
        sub.run()
        check("it gave up rather than looping", time.monotonic() - started < 5,
              True)
        check("and said why", "refused" in sub.last_error.lower()
              or "password" in sub.last_error.lower(), True)
    finally:
        broker.stop()


def test_a_listener_that_is_not_there_drops_rather_than_queues() -> None:
    """A queue here would grow through an outage and then deliver an hour of
    stale readings. The next message is seconds away and says the same."""
    sub = a_subscription()
    sub.dry_run = False
    sub.listener_port = 1          # nothing listens here
    sub.token = "x" * 32
    sub.field_map = {"temperature": "outTemp"}
    sub.take("s", b'{"temperature": 21.5}')
    sub.flush()

    check("it said what happened", bool(sub.last_error), True)
    check("and held nothing back", sub._holding, {})


def test_the_collector_kinds_include_it() -> None:
    """A collector is a name at the listener and a page, whatever it fetches."""
    from weewx_evo import collectors

    check("mqtt is one", "mqtt" in collectors.kinds(), True)
    check("and it is described", bool(collectors.describe("mqtt")), True)


def test_every_option_has_a_default_it_would_accept() -> None:
    """A setting whose default fails its own validation is one nobody can
    save -- and rendering the page parses the value it is about to show, so
    the whole page answers 500."""
    from weewx_evo import options as option_defs
    from weewx_evo.ingest import mqttsub

    for option in mqttsub.options():
        schema = option_defs.Schema(
            name="mqtt", label="MQTT",
            groups=(option_defs.Group("", (option,)),))
        _parsed, errors = schema.parse({option.name: str(option.default)})
        check(f"{option.name} accepts its own default", errors, {})


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
                     data={"outTemp": 21.0}, identity="test"))
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
                         data={"outTemp": 21.4}, identity="test"))
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


def test_home_assistant_discovery() -> None:
    """The station appears in Home Assistant without anybody writing YAML.

    A wrong device class is not cosmetic: `pressure` on a temperature makes
    the history graph unreadable, and a unit Home Assistant does not know
    turns the sensor into a plain string with no graph at all.
    """
    broker = Broker()
    broker.start()
    record = {"dateTime": 1756308600, "usUnits": 17, "outTemp": 23.4,
              "outHumidity": 61.0, "barometer": 1013.2, "windSpeed": 3.2,
              "windDir": 245.0, "dayRain": 2.6, "radiation": 512.0}
    try:
        upload = MqttUpload(host="127.0.0.1", port=broker.port,
                            home_assistant=True, station="Kirchdorf",
                            individual=False, unit_system="METRICWX")
        upload.post([record])
        ok("the definitions went out", broker.until(
            lambda b: sum(1 for t, _p, _q, _r in b.published
                          if t.startswith("homeassistant/")) >= 7))
        first = sum(1 for t, _p, _q, _r in broker.published
                    if t.startswith("homeassistant/"))
        # Definitions do not change between readings. Re-sending them every
        # ten seconds would be most of the traffic.
        upload.post([dict(record, dateTime=1756308660)])
        ok("the second reading published", broker.until(
            lambda b: sum(1 for t, _p, _q, _r in b.published
                          if t == "weather/loop") >= 2))
        check("and did not repeat the definitions",
              sum(1 for t, _p, _q, _r in broker.published
                  if t.startswith("homeassistant/")), first)
        upload.close()
    finally:
        broker.stop()

    found = {t: json.loads(p) for t, p, _q, _r in broker.published
             if t.startswith("homeassistant/")}
    temp = found["homeassistant/sensor/weewx_evo_kirchdorf/outTemp/config"]
    check("the temperature is a temperature", temp["device_class"], "temperature")
    check("in a unit Home Assistant knows", temp["unit_of_measurement"], "°C")
    check("reading the JSON document", temp["state_topic"], "weather/loop")
    check("by the name it is published under",
          temp["value_template"], "{{ value_json.outTemp_C | default('', true) }}")
    check("named for a person", temp["name"], "Out temp")
    check("under one device", temp["device"]["name"], "Kirchdorf")

    bar = found["homeassistant/sensor/weewx_evo_kirchdorf/barometer/config"]
    # Millibars and hectopascals are the same thing, and hPa is the one Home
    # Assistant lists. Sending `mbar` makes it a string.
    check("pressure is atmospheric_pressure",
          bar["device_class"], "atmospheric_pressure")
    check("in hectopascals", bar["unit_of_measurement"], "hPa")

    wind = found["homeassistant/sensor/weewx_evo_kirchdorf/windSpeed/config"]
    check("wind speed", wind["device_class"], "wind_speed")
    check("in metres per second", wind["unit_of_measurement"], "m/s")

    # A bearing has no device class in Home Assistant, so it stays a number
    # with a degree sign rather than being given a wrong one.
    bearing = found["homeassistant/sensor/weewx_evo_kirchdorf/windDir/config"]
    ok("a bearing gets no device class", "device_class" not in bearing)
    check("but keeps its unit", bearing["unit_of_measurement"], "°")

    rain = found["homeassistant/sensor/weewx_evo_kirchdorf/dayRain/config"]
    # A daily total resets at midnight. As `measurement` the drop reads as a
    # negative rainfall; as `total_increasing` it reads as a new day.
    check("a daily total is a total", rain["state_class"], "total_increasing")
    ok("and does not expire", "expire_after" not in rain)

    every = [p for t, p, _q, _r in broker.published
             if t.startswith("homeassistant/")]
    ok("every definition is retained", all(
        r for t, _p, _q, r in broker.published if t.startswith("homeassistant/")))
    check("one per reading, and no more", len(every), 7)


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
    test_home_assistant_discovery()
    with tempfile.TemporaryDirectory() as tmp:
        test_the_live_path(Path(tmp))

    # The other direction: a broker as a station.
    test_a_json_document_becomes_one_packet()
    test_one_topic_per_value_becomes_one_packet_too()
    test_a_wildcard_in_the_map_matches_but_an_exact_name_wins()
    test_a_payload_that_says_when_keeps_its_own_time()
    test_what_a_broker_publishes_that_is_not_a_number()
    test_a_bare_number_on_an_unnamed_topic_is_dropped()
    test_it_subscribes_and_reads_what_the_broker_sends()
    test_a_broker_that_refuses_permanently_is_not_retried()
    test_a_listener_that_is_not_there_drops_rather_than_queues()
    test_the_collector_kinds_include_it()
    test_every_option_has_a_default_it_would_accept()

    print()
    for failure in FAILURES:
        print("FAIL", failure)
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

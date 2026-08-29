"""A broker as a station: subscribe, name the fields, deliver.

We have had a full MQTT client since the Cheetah feed needed one, and used it
only to publish. Turning it around opens Zigbee2MQTT, ESPHome, Home Assistant
and every hand-built ESP32 in one go -- which is the commonest shape of "one
more sensor", and the role mechanism that moves a second station's `outTemp`
into `extraTemp3` was built for exactly this.

**A broker is a collector, not a parser.** We go to it; it does not upload to
us. So this runs in its own process and delivers over loopback like the WeeWX
shim does, and for the same reason: a broker that stops answering, or a
reconnect loop that goes wrong, must not be able to stop the archiver. Same
bargain, same price -- one process.

Two shapes of publisher, and both are ordinary:

  * **One topic, a JSON document.** Zigbee2MQTT's `zigbee2mqtt/gartensensor`
    carries `{"temperature": 21.5, "humidity": 60}`. The map is from key to
    archive field name.
  * **One topic per value.** `home/garden/temp` carries `21.5`. The map is
    from topic to field name.

Both, because both are what people have. The map is checked against the
topic first and against the JSON keys second, so a configuration that names
either works and one that names both is not ambiguous.

**Readings are gathered before they are sent.** A packet per message would
mean one field per packet where a station publishes each value to its own
topic -- and a packet with `outTemp` alone, arriving a second before one with
`outHumidity` alone, gives an archive interval two records that each know
half of what happened. So messages inside `bundle` seconds become one packet.
A JSON document fills it in one message and the window costs nothing.

**Nothing is timestamped here unless it has to be.** A payload carrying its
own `dateTime` keeps it; otherwise the moment of arrival is used, which is a
different measurement and looks identical afterwards -- so the only defence
is that a broker delivers within seconds of publication, and this is written
down rather than assumed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from .. import units
from ..db.live import Packet
from ..mqtt import Client, MqttError, topic_matches

log = logging.getLogger(__name__)

#: How long readings are gathered before they go out as one packet. Two
#: seconds is longer than any broker takes to deliver a burst and shorter
#: than anything an archive interval notices.
BUNDLE = 2.0

#: How long to wait after a broker refuses or drops the connection. The
#: client reconnects on its own for the ordinary case; this is the outer
#: loop for the case where connecting itself failed.
RETRY = 30.0

#: Keys a payload may carry that are not readings.
NOT_A_READING = ("dateTime", "usUnits", "time", "timestamp", "last_seen")


def _number(value: Any) -> float | None:
    """A reading, or None. A broker publishes strings, booleans and nulls.

    Booleans are read as numbers on purpose: a battery flag published as
    `true` means the same as one published as `1`, and refusing it would drop
    the reading a `stations.toml` role was configured for.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Subscription:
    """One broker, one map, delivering packets.

    Not a driver class in `ingest/plugins/`: those are parsers, and the
    listener builds them to hand a body to. This is the other side of the
    seam -- it runs elsewhere and pushes in.
    """

    def __init__(self, host: str, port: int = 1883, topic: str = "",
                 field_map: dict[str, str] | None = None,
                 username: str = "", password: str = "",
                 client_id: str = "", tls: bool = False,
                 unit_system: str = "metricwx", source: str = "mqtt",
                 bundle: float = BUNDLE, as_driver: str = "json",
                 listener_host: str = "127.0.0.1", listener_port: int = 8000,
                 token: str | None = None, dry_run: bool = False) -> None:
        self.host = host
        self.port = port
        #: What to subscribe to. A wildcard is normal: `home/garden/+` is one
        #: subscription for every value a station publishes separately.
        self.topic = topic or "#"
        self.field_map = dict(field_map or {})
        self.username = username
        self.password = password
        self.client_id = client_id
        self.tls = tls
        self.system = {"us": units.US, "metric": units.METRIC,
                       "metricwx": units.METRICWX}.get(
                           str(unit_system or "metricwx").lower(),
                           units.METRICWX)
        self.source = source
        self.bundle = max(0.0, float(bundle))
        self.as_driver = as_driver
        self.listener_host = listener_host
        self.listener_port = listener_port
        self.token = token
        self.dry_run = dry_run

        self.client: Client | None = None
        self.stopping = threading.Event()
        #: What has arrived since the last packet went out, and when the
        #: oldest of it did.
        self._holding: dict[str, float] = {}
        self._since: float = 0.0
        self._stamp: int | None = None

        self.messages = 0
        self.packets = 0
        self.unmapped: dict[str, int] = {}
        self.last_error = ""
        self.sent: list[Packet] = []

    # -- naming the readings ----------------------------------------------

    def fields(self, topic: str, payload: bytes) -> dict[str, float]:
        """What one message says, as archive field names.

        The topic is tried first: a map naming `home/garden/temp` means the
        whole payload is that reading. Then the payload is read as JSON and
        its keys are mapped. A payload that is neither -- a bare number on a
        topic nobody named -- is counted and dropped, because guessing which
        column it belongs in is the one thing that cannot be undone.
        """
        text = payload.decode("utf-8", "replace").strip()

        named = self._named_by_topic(topic)
        if named:
            value = _number(text)
            if value is None:
                # A named topic carrying a document rather than a number:
                # fall through and read it as JSON.
                pass
            else:
                return {named: value}

        try:
            document = json.loads(text)
        except (TypeError, ValueError):
            document = None
        if not isinstance(document, dict):
            # A bare number is valid JSON, so this branch catches it as well
            # as unparseable text -- and both mean the same thing here: a
            # topic nobody named, carrying one value. Counted rather than
            # dropped silently, because that list is what `mqtt check` is
            # for: the topics somebody has yet to write down.
            if named is None:
                self.unmapped[topic] = self.unmapped.get(topic, 0) + 1
            return {}

        # A document may carry the moment it was measured. Kept when it does,
        # because the arrival time is a different measurement.
        stamp = document.get("dateTime")
        if stamp is not None:
            try:
                self._stamp = int(float(stamp))
            except (TypeError, ValueError):
                pass

        out: dict[str, float] = {}
        for key, raw in document.items():
            if key in NOT_A_READING:
                continue
            field = self.field_map.get(key)
            if field is None:
                # Also try the fully qualified name, so two sensors
                # publishing `temperature` can be told apart.
                field = self.field_map.get(f"{topic}/{key}")
            if field is None:
                self.unmapped[f"{topic}/{key}"] = (
                    self.unmapped.get(f"{topic}/{key}", 0) + 1)
                continue
            value = _number(raw)
            if value is not None:
                out[field] = value
        return out

    def _named_by_topic(self, topic: str) -> str | None:
        """The field a whole topic means, exact match then wildcard.

        Exact first: a map with both `home/+/temp` and `home/shed/temp` in it
        means the specific one where it applies, and dictionary order is not
        somewhere to put that decision.
        """
        if topic in self.field_map:
            return self.field_map[topic]
        for pattern, field in self.field_map.items():
            if ("+" in pattern or "#" in pattern) and topic_matches(pattern, topic):
                return field
        return None

    # -- gathering and delivering -----------------------------------------

    def take(self, topic: str, payload: bytes) -> None:
        """One message in. Held until the bundle window closes."""
        self.messages += 1
        found = self.fields(topic, payload)
        if not found:
            return
        if not self._holding:
            self._since = time.monotonic()
        self._holding.update(found)

    def due(self, now: float | None = None) -> bool:
        """Whether what is held should go out."""
        if not self._holding:
            return False
        now = time.monotonic() if now is None else now
        return now - self._since >= self.bundle

    def flush(self) -> Packet | None:
        """Send what is held, as one packet. None if there was nothing."""
        if not self._holding:
            return None
        data = dict(self._holding)
        stamp = self._stamp if self._stamp is not None else int(time.time())
        self._holding.clear()
        self._stamp = None

        packet = Packet(dateTime=stamp, usUnits=self.system, data=data,
                        source=self.source, kind="loop")
        self.packets += 1
        if self.dry_run:
            self.sent.append(packet)
            return packet
        self.deliver([packet])
        return packet

    def deliver(self, packets: list[Packet]) -> bool:
        """Hand packets to the listener. False means none got through."""
        from .listener import push

        if not packets:
            return True
        try:
            push(packets, self.listener_host, self.listener_port,
                 token=self.token, as_driver=self.as_driver)
        except Exception as exc:
            # Dropped rather than held. The next message is seconds away and
            # carries the same reading; a queue here would grow through an
            # outage and deliver an hour of stale values afterwards.
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("could not deliver to the listener: %s", exc)
            return False
        return True

    # -- the loop ---------------------------------------------------------

    def connect(self) -> None:
        """Open the connection and subscribe. Raises on a permanent refusal."""
        self.client = Client(self.host, self.port, username=self.username,
                             password=self.password,
                             client_id=self.client_id or "", tls=self.tls,
                             on_message=self.take)
        self.client.connect()
        self.client.subscribe(self.topic, qos=1)
        log.info("subscribed to %s at %s:%d", self.topic, self.host, self.port)

    def run(self) -> None:
        """Until stopped. Never raises for anything a retry could fix."""
        while not self.stopping.is_set():
            try:
                if self.client is None or not self.client.connected:
                    self.connect()
                self.client.pump(0.5)
                self.client.ping_if_due()
                if self.due():
                    self.flush()
            except MqttError as exc:
                self.last_error = str(exc)
                if exc.permanent:
                    # Bad credentials, a broker that refuses the client id.
                    # Asking again every 30 seconds for a week would not fix
                    # it and the log line is the useful output.
                    log.error("the broker refused us permanently: %s. Fix the "
                              "settings and start again.", exc)
                    return
                log.warning("broker trouble: %s. Trying again in %ds",
                            exc, RETRY)
                self._drop()
                self.stopping.wait(RETRY)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("mqtt collector: %s", exc, exc_info=True)
                self._drop()
                self.stopping.wait(RETRY)
        self._drop()

    def _drop(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                log.debug("closing the broker connection failed", exc_info=True)
            self.client = None

    def stop(self) -> None:
        self.stopping.set()

    def status(self) -> dict[str, Any]:
        """What it has done, for `mqtt check` and the settings page."""
        return {
            "broker": f"{self.host}:{self.port}",
            "topic": self.topic,
            "messages": self.messages,
            "packets": self.packets,
            "unmapped": dict(sorted(self.unmapped.items(),
                                    key=lambda row: -row[1])[:10]),
            "error": self.last_error,
        }


def options() -> list:
    """The settings a configured MQTT collector has.

    Declared rather than read, like every other setting here: the form, the
    validation, the file comment and the `--explain` line all come from this
    and there is no second place to add one.
    """
    from ..options import Option

    return [
        Option("host", "Broker", kind="text", default="",
               help="Where the broker is. A hostname or an address."),
        Option("port", "Port", kind="int", default=1883, minimum=1,
               maximum=65535),
        Option("topic", "Topic", kind="text", default="#",
               help="What to subscribe to. `zigbee2mqtt/#` for everything "
                    "Zigbee2MQTT publishes, or one topic for one sensor."),
        Option("username", "User", kind="text", default=""),
        Option("password", "Password", kind="secret", default=""),
        Option("tls", "TLS", kind="bool", default=False,
               help="Only where the broker offers it. A broker on the home "
                    "network usually does not."),
        Option("client_id", "Client id", kind="text", default="",
               help="Empty means one is made up. Two subscribers sharing an "
                    "id disconnect each other, endlessly."),
        Option("unit_system", "Units the broker publishes in", kind="choice",
               default="metricwx",
               choices=(("metricwx", "Celsius, mm, m/s"),
                        ("metric", "Celsius, cm, km/h"),
                        ("us", "Fahrenheit, inches, mph")),
               help="A broker states no units. Getting this wrong writes "
                    "Fahrenheit into a Celsius column, and nothing "
                    "downstream can tell."),
        Option("bundle", "Gather for", kind="duration", default=2,
               help="Readings arriving within this become one packet. A "
                    "station publishing each value to its own topic needs "
                    "it; one publishing a JSON document does not."),
    ]

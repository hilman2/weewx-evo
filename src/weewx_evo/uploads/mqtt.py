"""Publishing readings to an MQTT broker.

This is the one that makes a skin come alive. Belchertown, jas, weewx-wdc and
Weather34 all subscribe to a broker over websockets and redraw as messages
arrive; without one they render completely and then sit frozen until the next
page load. So the topic layout here is not ours to invent -- it is
`matthewwall/weewx-mqtt`'s, because that is what those skins were written
against and what eight years of installation instructions tell people to
configure.

That means, transcribed rather than improved:

  * The default topic is `weather`, and each reading goes to `weather/<name>`.
  * Names carry a unit suffix -- `outTemp_C`, `windSpeed_mph` -- from a
    reduction table where `degree_compass`, `percent` and `uv_index` are
    deliberately bare.
  * The same record also goes to `weather/loop` as one JSON document, because
    a browser opening one subscription is cheaper than forty.

Both at once is the default there and here. A skin uses one or the other and
nobody has to work out which.

**Retained, by default.** A retained message is handed to a browser the moment
it subscribes, so a page shows the current conditions immediately instead of a
blank dashboard until the next archive record. Without it a skin looks broken
for up to five minutes after every load, which is the single most common
complaint about MQTT weather dashboards.
"""

from __future__ import annotations

import json
import logging

from .. import units
from ..mqtt import Client, MqttError
from . import BaseUpload, Posted, Rejected, when_options
from .homeassistant import discovery

log = logging.getLogger(__name__)

#: Unit names shortened for a topic. Transcribed from `weewx-mqtt`'s
#: `UNIT_REDUCTIONS`: a skin subscribing to `weather/outTemp_C` needs that
#: exact name, and `degree_C` would be a different topic.
UNIT_SUFFIX: dict[str, str | None] = {
    "degree_F": "F",
    "degree_C": "C",
    "inch": "in",
    "mile_per_hour": "mph",
    "mile_per_hour2": "mph",
    "km_per_hour": "kph",
    "km_per_hour2": "kph",
    "knot": "knot",
    "knot2": "knot2",
    "meter_per_second": "mps",
    "meter_per_second2": "mps",
    # None means no suffix at all. A compass bearing in degrees and a
    # percentage have nothing to disambiguate, and `outHumidity_percent`
    # is not a topic any skin subscribes to.
    "degree_compass": None,
    "watt_per_meter_squared": "Wpm2",
    "uv_index": None,
    "percent": None,
    "unix_epoch": None,
}

#: Never published, whatever a record holds. `usUnits` is an implementation
#: detail of the archive and means nothing to a browser; the unit is in the
#: field name instead.
NEVER = frozenset({"usUnits", "interval"})


def topic_name(obs: str, unit: str | None, append_units: bool) -> str:
    """What a reading is called on the broker."""
    if not append_units or unit is None:
        return obs
    suffix = UNIT_SUFFIX.get(unit, unit)
    return obs if suffix is None else f"{obs}_{suffix}"


class MqttUpload(BaseUpload):
    """Publishes records to an MQTT broker."""

    label = "MQTT"
    summary = ("A broker, so a skin updates while somebody is looking at it. "
               "What Belchertown, jas and weewx-wdc take their live data from.")
    #: Backfilling to a broker is meaningless: a retained message is "what it
    #: is like now", and replaying an hour into it leaves the last one of the
    #: hour showing as current. The archive is where history lives.
    backfill = False

    def __init__(self, host: str = "", port: int | None = None,
                 topic: str = "weather", username: str = "", password: str = "",
                 tls: bool = False, tls_verify: bool = True,
                 client_id: str = "", unit_system: str = "",
                 append_units: bool = True, aggregate: bool = True,
                 individual: bool = True, retain: bool = True, qos: int = 0,
                 home_assistant: bool = False, discovery_prefix: str = "homeassistant",
                 station: str = "", websockets_host: str = "",
                 websockets_port: int | None = None, websockets_path: str = "",
                 websockets_tls: bool | None = None,
                 trigger: str = "live", every: int = 10,
                 catch_up: int = 0, timeout: int = 20,
                 keepalive: int = 60) -> None:
        if not host:
            raise ValueError("an MQTT broker host is needed")
        self.topic = (topic or "weather").strip("/")
        # Empty means "whatever the archive holds", which is the honest
        # default: converting by accident is how a skin ends up drawing
        # Fahrenheit on a page that says Celsius everywhere else.
        self.unit_system = units.system_from(unit_system) if unit_system else None
        self.append_units = bool(append_units)
        self.aggregate = bool(aggregate)
        self.individual = bool(individual)
        self.retain = bool(retain)
        self.qos = int(qos)
        self.home_assistant = bool(home_assistant)
        self.discovery_prefix = (discovery_prefix or "homeassistant").strip("/")
        # Named here so the device has a name in Home Assistant. Empty means
        # the station's own, filled in when the upload is built -- an upload
        # has no business reading the whole settings.
        self.station = station
        #: Which readings have been announced on this connection. Cleared on
        #: a reconnect: a broker restarted without persistence has forgotten
        #: the retained definitions, and a Home Assistant starting after that
        #: would find nothing.
        self._announced: set[str] = set()
        # How a *browser* reaches this same broker. Not the same address:
        # this client speaks MQTT over TCP, usually to localhost, while a
        # page speaks MQTT over websockets to whatever is publicly
        # reachable. Kept here rather than in the skin because everything
        # else about the broker is already here -- see `browser()`.
        self.websockets_host = str(websockets_host or "").strip()
        self.websockets_port = websockets_port
        self.websockets_path = str(websockets_path or "").strip()
        self.websockets_tls = websockets_tls
        self.trigger = trigger
        self.every = int(every)
        self.catch_up_limit = 0
        if not (self.aggregate or self.individual):
            raise ValueError("MQTT with neither a JSON topic nor individual "
                             "topics would publish nothing")
        self.client = Client(host=host, port=port, client_id=client_id,
                             username=username, password=password,
                             tls=tls, tls_verify=tls_verify,
                             keepalive=keepalive, timeout=timeout)

    # -- shaping ---------------------------------------------------------

    def message(self, record: dict) -> dict[str, object]:
        """A record as the names and values that go on the broker.

        Conversion happens here rather than per field so that one record is
        one unit system throughout. A document with `outTemp_C` beside
        `dewpoint_F` is not a bug anybody spots by reading it.
        """
        stored = units.system_from(record.get("usUnits"), default=units.US)
        wanted = self.unit_system or stored
        shaped: dict[str, object] = {}
        for obs, value in record.items():
            if obs in NEVER or value is None:
                continue
            if obs == "dateTime":
                shaped["dateTime"] = int(value)
                continue
            unit, _group = units.unit_of(obs, stored)
            target, _ = units.unit_of(obs, wanted)
            if unit and target and unit != target:
                converted = units.convert(value, unit, target)
                if converted is None:
                    continue
                value = float(converted)
            shaped[topic_name(obs, target or unit, self.append_units)] = value
        return shaped

    # -- sending ---------------------------------------------------------

    def _announce(self, record: dict, shaped: dict[str, object]) -> None:
        """Tell Home Assistant what these topics are. Once per connection."""
        stored = units.system_from(record.get("usUnits"), default=units.US)
        wanted = self.unit_system or stored
        for obs in record:
            if obs in NEVER or obs == "dateTime" or record[obs] is None:
                continue
            unit, _group = units.unit_of(obs, wanted)
            field = topic_name(obs, unit, self.append_units)
            if field not in shaped or obs in self._announced:
                continue
            where, payload = discovery(obs, unit, self.topic, field,
                                       self.station, self.discovery_prefix)
            # Always retained, whatever `retain` says for the readings: a
            # definition nobody kept is one only a Home Assistant that was
            # already running ever saw.
            self.client.publish(where, payload, qos=self.qos, retain=True)
            self._announced.add(obs)

    def _publish(self, record: dict) -> int:
        shaped = self.message(record)
        published = 0
        if self.home_assistant:
            if not self.client.connected:
                # Reconnecting clears what the broker was told, because it
                # may have been restarted in between.
                self._announced.clear()
            self._announce(record, shaped)
        if self.individual:
            for name, value in shaped.items():
                self.client.publish(f"{self.topic}/{name}", str(value),
                                    qos=self.qos, retain=self.retain)
                published += 1
        if self.aggregate:
            # `loop` is what the skins subscribe to, whatever produced it. The
            # name is theirs and predates the distinction between a live
            # packet and an archive record.
            self.client.publish(f"{self.topic}/loop",
                                json.dumps(shaped, separators=(",", ":")),
                                qos=self.qos, retain=self.retain)
            published += 1
        return published

    def post(self, records: list[dict]) -> Posted:
        result = Posted()
        record = records[-1]
        result.skipped = len(records) - 1
        try:
            result.sent = self._publish(record)
        except MqttError as exc:
            if exc.permanent:
                raise Rejected(str(exc), permanent=True) from exc
            result.failures.append((str(record.get("dateTime")), str(exc)))
            return result
        result.through = int(record.get("dateTime") or 0)
        return result

    def publish_packet(self, packet: dict) -> int:
        """One live packet, for the live path rather than the archive one.

        Separate from `post` because it is not a record and has no business
        moving the progress mark: the archive is what that counts.
        """
        try:
            return self._publish(packet)
        except MqttError as exc:
            log.debug("MQTT live publish failed: %s", exc)
            return 0

    def browser(self) -> dict[str, object]:
        """What a page needs to subscribe to this same broker.

        The reason this exists: without it the broker is configured twice --
        once here, and once again in every skin that shows live readings.
        Two places holding the same host, the same credentials and, worst of
        all, the same topic. A typo in the second one produces a page that
        renders perfectly and never updates, with nothing in any log.

        So the upload answers the question instead, and the skin is filled in
        from it. What a browser needs that this client does not is only the
        address: this one usually speaks TCP to localhost, a page speaks
        websockets to whatever is publicly reachable.

        Returns nothing when this upload does not publish the JSON document,
        because that is what a page subscribes to. Individual topics are for
        Home Assistant and Node-RED.
        """
        if not self.aggregate:
            return {}
        tls = self.client.tls if self.websockets_tls is None else self.websockets_tls
        port = self.websockets_port
        if not port:
            # 9001 is what Mosquitto's own documentation uses for a
            # websocket listener, and 443 is what a broker behind a reverse
            # proxy ends up on. Neither is a standard, so both are only a
            # starting point -- which is why the setting exists.
            port = 443 if tls else 9001
        return {
            "enabled": True,
            "host": self.websockets_host or self.client.host,
            "port": int(port),
            "path": self.websockets_path,
            "tls": bool(tls),
            "topic": f"{self.topic}/loop",
            # Deliberately not the username and password. A page is served to
            # anybody, and a credential in it is a credential published. A
            # broker that needs one for reading needs an anonymous read-only
            # user for this, which is a decision for whoever runs it.
            "username": "",
            "password": "",
        }

    def check(self) -> str:
        try:
            self.client.connect()
        except MqttError as exc:
            return f"could not connect: {exc}"
        try:
            self.client.publish(f"{self.topic}/status", "weewx-evo",
                                retain=False)
        except MqttError as exc:
            return f"connected, but publishing failed: {exc}"
        finally:
            self.client.close()
        where = "individual topics and a JSON document" if \
            (self.individual and self.aggregate) else \
            ("individual topics" if self.individual else "a JSON document")
        return (f"connected to {self.client.host}:{self.client.port} and "
                f"published to {self.topic}/ as {where}.")

    def status(self) -> dict:
        return {"host": self.client.host, "port": self.client.port,
                "topic": self.topic, "connected": self.client.connected}

    def close(self) -> None:
        self.client.close()

    # -- settings --------------------------------------------------------

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("The broker", "", (
                Option("host", "Host", required=True,
                       placeholder="mqtt.example.org",
                       help="The broker's name or address. A broker on this "
                            "machine is `localhost`."),
                Option("port", "Port", kind="int", minimum=1, maximum=65535,
                       advanced=True,
                       help="Empty means 1883, or 8883 when encrypted."),
                Option("username", "User"),
                Option("password", "Password", kind="secret"),
                Option("client_id", "Client name", advanced=True,
                       help="Must be unique on the broker. Two clients "
                            "sharing a name take turns disconnecting each "
                            "other, which looks like a flapping network. "
                            "Empty means one is made up."),
            )),
            Group("What is published", "", (
                Option("topic", "Topic", default="weather",
                       help="Readings go to `<topic>/outTemp_C` and the whole "
                            "record to `<topic>/loop`. Belchertown and most "
                            "other skins expect `weather`."),
                Option("unit_system", "Publish in", kind="choice", default="",
                       choices=(("", "whatever the station reports"),
                                ("US", "US -- °F, inHg, mph, in"),
                                ("METRIC", "Metric -- °C, mbar, km/h, cm"),
                                ("METRICWX", "Metric WX -- °C, mbar, m/s, mm")),
                       help="The topic names carry the unit, so changing this "
                            "renames them: a skin subscribed to outTemp_C "
                            "stops receiving anything when it becomes "
                            "outTemp_F."),
                Option("append_units", "Put the unit in the topic name",
                       kind="bool", default=True,
                       help="On. `outTemp_C` rather than `outTemp`. Every "
                            "skin that reads MQTT expects it this way; "
                            "turning it off is for a subscriber of your own."),
                Option("aggregate", "Publish the whole record as JSON",
                       kind="bool", default=True,
                       help="To `<topic>/loop`. This is what the skins use: "
                            "one subscription instead of forty."),
                Option("individual", "Publish each reading to its own topic",
                       kind="bool", default=True,
                       help="To `<topic>/outTemp_C` and so on. What Home "
                            "Assistant and Node-RED are usually pointed at."),
                Option("retain", "Keep the last value on the broker",
                       kind="bool", default=True,
                       help="On. A retained message is handed to a browser "
                            "the moment it subscribes, so a page shows the "
                            "conditions at once rather than a blank dashboard "
                            "until the next record."),
                Option("home_assistant", "Announce to Home Assistant",
                       kind="bool", default=False,
                       help="Publishes a definition for each reading under "
                            "`homeassistant/`, so the station appears as a "
                            "device with its sensors named and graphed. No "
                            "YAML and no restart. Needs the JSON document "
                            "above, which is on by default."),
                Option("discovery_prefix", "Home Assistant topic prefix",
                       default="homeassistant", advanced=True,
                       help="Only change this if Home Assistant's own MQTT "
                            "discovery prefix was changed."),
                Option("station", "Call the device", advanced=True,
                       help="The name Home Assistant shows. Empty means the "
                            "station name from the main settings."),
                Option("qos", "Delivery", kind="choice", default=0,
                       choices=((0, "at most once -- fastest, and enough"),
                                (1, "at least once -- may duplicate")),
                       advanced=True,
                       help="At most once is right for a reading that is "
                            "superseded in five minutes."),
            )),
            Group("How a browser reaches the same broker",
                  "A skin showing live readings subscribes from the visitor's "
                  "browser, which speaks websockets rather than plain MQTT "
                  "and reaches the broker from outside. Filled in from the "
                  "settings above where it can be; what it cannot guess is "
                  "the address. Any skin that shows live readings is "
                  "configured from this, so the broker is set up once.", (
                      Option("websockets_host", "Host a browser should use",
                             help="Empty means the same host as above. Set it "
                                  "when this station reaches the broker at "
                                  "localhost and a visitor cannot."),
                      Option("websockets_port", "Port", kind="int",
                             minimum=1, maximum=65535,
                             help="Empty means 9001, or 443 when encrypted. "
                                  "Neither is a standard -- 9001 is what "
                                  "Mosquitto's own documentation uses."),
                      Option("websockets_path", "Path", advanced=True,
                             placeholder="/mqtt",
                             help="Only for a broker behind a reverse proxy, "
                                  "which is where a websocket usually needs "
                                  "one."),
                      Option("websockets_tls", "Encrypted", kind="bool",
                             advanced=True,
                             help="Empty follows the setting below. A page "
                                  "served over https cannot open an "
                                  "unencrypted websocket, so this has to be "
                                  "on wherever the site is."),
                  )),
            Group("Encryption", "", (
                Option("tls", "Encrypt the connection", kind="bool",
                       default=False,
                       help="Off, because most brokers are on the same local "
                            "network as the station. On for anything crossing "
                            "the internet -- the password is otherwise sent "
                            "as readable text."),
                Option("tls_verify", "Check the certificate", kind="bool",
                       default=True, advanced=True,
                       help="Turn off only for a broker on your own network "
                            "with a self-signed certificate."),
            )),
            # `live` is offered here and nowhere else: a broker is the one
            # destination that wants every packet, and it is the whole reason
            # a skin redraws while somebody is looking at it.
            *when_options(trigger="live", every=10, live=True),
            Group("How", "", (
                Option("keepalive", "Keep the connection alive every",
                       kind="duration", default=60, minimum=10, maximum=3600,
                       advanced=True,
                       help="A broker drops a client that has been silent for "
                            "longer than one and a half times this."),
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True),
            )),
        ]

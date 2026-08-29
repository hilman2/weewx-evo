"""The broker that is already there.

An installation with MQTT configured has Home Assistant or Node-RED on the
other end of it, and both can turn a message into a phone notification better
than this program can. So this channel is deliberately thin: it publishes the
event and stops.

**Retained, and one topic per symptom.** A notification that arrives once and
is gone suits email; a broker is a place where state lives. Publishing
`notify/station_silent/schuppen` retained means anything subscribing later --
a dashboard, an automation restarted this morning -- learns immediately what
is currently wrong, without waiting for it to happen again.

The all-clear is then not another message but an **empty payload** on the
same topic, which is how a retained topic is cleared. A subscriber sees the
symptom appear and disappear rather than two messages it has to pair up
itself.

**Its own connection, not the upload's.** Sharing one would mean a broker
that has gone away takes the readings and the alarm about the readings with
it, and the second is the one that has to survive.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..mqtt import Client, MqttError
from . import BaseChannel, Event, NotifyError, when_options

log = logging.getLogger(__name__)

DEFAULT_TOPIC = "weewx-evo/notify"


class MqttChannel(BaseChannel):
    """Publishes one retained message per symptom."""

    label = "MQTT"
    summary = ("Publishes to a broker, retained, one topic per symptom. For "
               "an installation that already has Home Assistant or Node-RED.")

    def __init__(self, host: str = "", port: int = 0, topic: str = DEFAULT_TOPIC,
                 username: str = "", password: str = "", tls: bool = False,
                 tls_verify: bool = True, qos: int = 1, retain: bool = True,
                 timeout: int = 20, after: int = 1800,
                 repeat: int = 86400) -> None:
        self.host = str(host or "").strip()
        self.topic = str(topic or DEFAULT_TOPIC).strip("/") or DEFAULT_TOPIC
        self.qos = int(qos)
        self.retain = bool(retain)
        self.after = int(after)
        self.repeat = int(repeat)
        if not self.host:
            raise ValueError("the address of a broker is needed")

        self.client = Client(host=self.host, port=int(port) or None,
                             client_id=f"weewx-evo-notify-{int(time.time()) & 0xFFFF:04x}",
                             username=str(username or ""),
                             password=str(password or ""),
                             tls=bool(tls), tls_verify=bool(tls_verify),
                             timeout=int(timeout))

    def topic_for(self, event: Event) -> str:
        """One topic per symptom, so the retained state reads as a list."""
        parts = [self.topic, event.kind]
        if event.subject:
            # A station name can hold anything somebody typed. A slash in it
            # would silently make a level in the topic tree, and then two
            # stations could collide.
            parts.append(str(event.subject).replace("/", "_").replace("+", "_")
                         .replace("#", "_"))
        return "/".join(parts)

    def send(self, event: Event, station: str = "") -> None:
        payload = "" if event.over else json.dumps({
            "kind": event.kind,
            "who": event.subject,
            "station": station,
            "text": event.text,
            "severity": event.severity,
            "since": int(event.since or 0),
        }, sort_keys=True)

        try:
            if not self.client.connected:
                self.client.connect()
            self.client.publish(self.topic_for(event), payload, qos=self.qos,
                                retain=self.retain)
        except MqttError as exc:
            raise NotifyError(f"the broker refused it: {exc}") from exc
        except OSError as exc:
            raise NotifyError(
                f"could not reach {self.host}: {type(exc).__name__}: "
                f"{exc}") from exc

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            log.debug("could not close the notification broker connection",
                      exc_info=True)

    def status(self) -> dict[str, Any]:
        return {"host": self.host, "topic": self.topic,
                "connected": self.client.connected}

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("The broker", "", (
                Option("host", "Broker", kind="text", required=True,
                       placeholder="192.168.1.10"),
                Option("port", "Port", kind="int", default=0, minimum=0,
                       maximum=65535, advanced=True,
                       help="Zero means 1883, or 8883 with TLS."),
                Option("username", "Username", kind="text", default=""),
                Option("password", "Password", kind="secret", default=""),
                Option("tls", "Use TLS", kind="bool", default=False),
                Option("tls_verify", "Check the certificate", kind="bool",
                       default=True, advanced=True),
            )),
            Group("What it publishes", "", (
                Option("topic", "Topic", kind="text", default=DEFAULT_TOPIC,
                       help="The symptom and who it is about are added: "
                            "weewx-evo/notify/station_silent/schuppen."),
                Option("retain", "Keep the last message", kind="bool",
                       default=True,
                       help="So anything that subscribes later learns what is "
                            "wrong now. The all-clear is an empty payload on "
                            "the same topic, which is how a retained topic is "
                            "cleared."),
                # An alarm is worth a round trip, unlike a reading that is
                # superseded in five minutes -- so the default here is one
                # higher than the upload's.
                Option("qos", "Delivery", kind="choice", default=1,
                       choices=((0, "at most once"),
                                (1, "at least once -- may duplicate")),
                       advanced=True),
            )),
            *when_options(),
            Group("How", "", (
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True),
            )),
        ]

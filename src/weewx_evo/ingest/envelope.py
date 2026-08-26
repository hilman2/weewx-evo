"""weewx-evo's own envelope.

This is the contract, not a protocol. It is the shape a driver hands over when
it has finished its work, and the only format the core itself understands:

    {"dateTime": 1787734265, "usUnits": 1, "source": "vantage-1",
     "kind": "loop", "interval": null, "data": {"outTemp": 21.4}}

One object or a list of them. `data` may also be flattened into the object
itself, which is what a hand-written driver tends to produce.

Field names are WeeWX's and `usUnits` is a WeeWX unit constant, because
deciding both is the driver's job and it is already done by the time anything
reaches here. A pull driver in Go or shell has to produce nothing more than
this, which is the point of it being this small.
"""

from __future__ import annotations

import json

from ..db.live import Packet
from ..units import METRICWX
from .drivers import BaseDriver

RESERVED = frozenset({"dateTime", "usUnits", "source", "kind", "interval", "received"})


class EnvelopeDriver(BaseDriver):
    """Reads the envelope. The only driver that ships in the core."""

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        payload = json.loads(body)
        items = payload if isinstance(payload, list) else [payload]

        packets = []
        for item in items:
            data = item.get("data")
            if data is None:
                data = {k: v for k, v in item.items() if k not in RESERVED}
            packets.append(Packet(
                dateTime=int(item.get("dateTime") or meta["received"]),
                usUnits=int(item.get("usUnits", METRICWX)),
                data=data,
                source=str(item.get("source") or meta.get("source", "json"))[:64],
                kind=item.get("kind", "loop"),
                interval=item.get("interval"),
            ))
        return packets

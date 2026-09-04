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
from .drivers import BaseDriver, Setup

RESERVED = frozenset({"dateTime", "usUnits", "source", "kind", "interval", "received"})


class EnvelopeDriver(BaseDriver):
    """Reads the envelope. The only driver that ships in the core."""

    @staticmethod
    def setup() -> Setup:
        """One address and one name, which is the whole of the contract.

        The identity is handed out here rather than read off the wire: what a
        collector calls itself is `source` in the envelope it sends, so it
        carries whatever it is given -- and an identity somebody chooses for
        themselves can be chosen twice.
        """
        return Setup(
            label="weewx-evo envelope",
            hardware=("A collector you run yourself, or any WeeWX driver "
                      "through `weewx-evo weewx-driver run`."),
            fields=(("Address", "%(base)s%(path)s"),
                    ("source", "%(identity)s")),
            notes=(("Post the envelope to that address, one object or a list "
                    "of them, with `source` set to the identity."),
                   ("`weewx-evo weewx-driver run --conf /etc/weewx/weewx.conf`"
                    " does it for a WeeWX driver, and `weewx-evo collector "
                    "run --collector <name>` for one configured here.")),
            # The token is in the path, like every other protocol whose
            # address is ours to choose. Not a password: S106 reads the
            # keyword name, and what this says is which kind of secret the
            # hardware can carry.
            secret="path",  # noqa: S106
        )

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
                # The envelope's `source` is what this collector calls itself,
                # which is exactly what an identity is: the listener looks it
                # up in the station register like any PASSKEY, and an
                # unannounced one is known by it.
                identity=str(item.get("source") or meta.get("source", ""))[:64],
                # No dialect: these names are already WeeWX's. That is the
                # whole of the envelope contract, and it is why a collector in
                # Go or shell needs to know nothing about placement.
                kind=item.get("kind", "loop"),
                interval=item.get("interval"),
            ))
        return packets

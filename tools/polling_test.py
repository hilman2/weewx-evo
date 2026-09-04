#!/usr/bin/env python3
"""Hardware that has to be asked, and the one door it comes in through.

A PurpleAir sensor, a Davis AirLink and an Ecowitt gateway on its own API all
answer whoever asks and can be pointed at nothing. A listener that only ever
waits never sees them, so `Driver.start` lets a driver go and ask.

What this measures is that asking and being pushed at end in the same place.
Everything after the parse has to be identical -- the raw names, the dialect,
the redaction, the live table -- or a polled sensor is a second kind of
reading with a second set of bugs.

    python tools/polling_test.py
"""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo.db.live import LiveStore, Packet, sender_id  # noqa: E402
from weewx_evo.ingest import drivers  # noqa: E402
from weewx_evo.ingest.listener import Ingest  # noqa: E402

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


class Asks(drivers.BaseDriver):
    """A driver with nowhere to be pointed. It goes and looks instead."""

    name = "asks"

    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = False
        self.deliver = None
        self.asked = 0

    def start(self, deliver) -> None:
        # A real one starts a thread here and returns. Keeping the callable
        # is enough to show the wiring, and a test that started a thread
        # would be measuring the sleep.
        self.deliver = deliver
        self.started.set()

    def close(self) -> None:
        self.stopped = True

    def packets(self, body: bytes, meta: dict) -> list:
        self.asked += 1
        text = body.decode()
        readings = dict(one.split("=", 1) for one in text.split("&") if "=" in one)
        serial = readings.pop("serial", "aabb")
        return [Packet(dateTime=int(meta["received"]), usUnits=1,
                       data={k: float(v) for k, v in readings.items()},
                       identity=serial, dialect="asks")]

    def dialect_spec(self, readings: dict, dialect: str) -> drivers.DialectSpec:
        # Not `mapping` on the packet: `_store` replaces that unconditionally,
        # so that a driver cannot put a large unvalidated document in the
        # database by setting it while leaving the dialect empty. A polled
        # reading is held to exactly the same rule, which is the point.
        return drivers.DialectSpec(
            fields={"pm2_5_atm": "pm2_5", "humidity": "outHumidity"},
            usUnits=1)


class Refuses(drivers.BaseDriver):
    """One whose sensor is at an address nobody answers on."""

    name = "refuses"

    def start(self, deliver) -> None:
        raise OSError("no route to host")

    def packets(self, body: bytes, meta: dict) -> list:
        return []


def an_ingest(work: Path, *drivers_: object) -> tuple[Ingest, LiveStore]:
    live = LiveStore(work / "live.sdb", interval_seconds=300)
    registry = drivers.Registry()
    # Nothing else: `load()` would pull in the bundled tree, and the point
    # here is what one driver does.
    registry._loaded = True
    for one in drivers_:
        registry.register(one.name, one)
    return Ingest(live, token=None, registry=registry), live


def what_it_asks_for_is_stored_like_an_upload() -> None:
    print("\nasking ends where being pushed at ends")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        asks = Asks()
        ingest, live = an_ingest(work, asks)
        try:
            started = ingest.begin()
            check("the driver was started", started, ["asks"])
            check("and given something to deliver with",
                  asks.deliver is not None, True)

            stored = asks.deliver(b"serial=A1B2&pm2_5_atm=7.5&humidity=41")
            check("what it fetched was stored", stored, 1)

            rows = list(live.packets(0, 2_000_000_000))
            check("one packet in the table", len(rows), 1)
            one = rows[0]
            # The whole point: raw names, not columns. A polled reading is
            # placed on the read side exactly like a pushed one.
            check("under the name the sensor used",
                  one.data.get("pm2_5_atm"), 7.5)
            check("with its dialect", one.dialect, "asks")
            check("and its mapping", one.mapping is not None, True)
            check("recognised as the driver that asked",
                  one.sender_id, sender_id("asks", "A1B2"))

            ingest.finish()
            check("and it was stopped", asks.stopped, True)
        finally:
            live.close()


def a_sensor_that_will_not_answer_costs_only_itself() -> None:
    """The rule everywhere else on this path, measured here too."""
    print("\none that will not start")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        asks, refuses = Asks(), Refuses()
        ingest, live = an_ingest(work, refuses, asks)
        try:
            started = ingest.begin()
            check("the working one still started", started, ["asks"])
            check("the broken one did not", "refuses" in started, False)
            check("and the working one still delivers",
                  asks.deliver(b"serial=A1B2&pm2_5_atm=3.0"), 1)
        finally:
            live.close()


def a_driver_that_does_not_ask_is_untouched() -> None:
    """Every pushing driver, which is nearly all of them."""
    print("\na driver with no start() at all")

    class Waits(drivers.BaseDriver):
        name = "waits"

        def packets(self, body: bytes, meta: dict) -> list:
            return []

    with tempfile.TemporaryDirectory() as raw:
        ingest, live = an_ingest(Path(raw), Waits())
        try:
            # `BaseDriver.start` exists and does nothing, so it is named as
            # started. What matters is that nothing raised and nothing else
            # changed for it.
            check("begin() is survivable", ingest.begin(), ["waits"])
            ingest.finish()
            check("so is finish()", True, True)
        finally:
            live.close()


def nothing_polled_reaches_the_token_check() -> None:
    """A driver must not have to know the upload token to hand it back.

    `submit` guards the door: token, then rate limit, then the driver. A
    fetched reading crossed no network boundary this process did not open
    itself, so it takes neither -- and a driver that had to carry the token
    in order to deliver would be a secret travelling in a circle.
    """
    print("\nasking does not go through the door's locks")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        asks = Asks()
        live = LiveStore(work / "live.sdb", interval_seconds=300)
        registry = drivers.Registry()
        registry._loaded = True
        registry.register("asks", asks)
        # A token set, and never handed to the driver.
        ingest = Ingest(live, token="abcdefghij123456", registry=registry)
        try:
            ingest.begin()
            check("a fetched reading is stored with a token set",
                  asks.deliver(b"serial=A1B2&pm2_5_atm=5.0"), 1)
            # And the door is still locked for anything that did come over it.
            code, why, _answer = ingest.submit(
                b"pm2_5_atm=5.0", "/wrong-token/asks/", "1.2.3.4")
            check("while an upload without it is still refused",
                  (code, why), (0, "unauthorised"))
        finally:
            live.close()


def main() -> int:
    what_it_asks_for_is_stored_like_an_upload()
    a_sensor_that_will_not_answer_costs_only_itself()
    a_driver_that_does_not_ask_is_untouched()
    nothing_polled_reaches_the_token_check()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("what a driver asks for arrives the way a pushed reading does")
    return 0


if __name__ == "__main__":
    sys.exit(main())

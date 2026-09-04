"""Check that the page asks the drivers how to point hardware at us.

The stations page used to carry a hand-written table of three protocols. Six
were installed. So four of them -- Ambient, AcuRite, LaCrosse, WeatherFlow --
could not be set up from the page at all, and the table had drifted from what
the protocols say: it turned an Ambient console away with "has no server
field" while `protocols/ambient.py` lists five, Server IP and Port among them.

`drivers.Setup` and `drivers.setup_of` existed for exactly this and nothing
called them. What is measured here is that they are called now, and the shape
of the check matters more than the count: a test that names the six protocols
would pass just as well against a list written out by hand. So the driver that
proves it is one this repository does not have -- registered here, offered by
the page there.

    python tools/console_setup_test.py
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import adminstations
from weewx_evo.db.live import LiveStore
from weewx_evo.ingest import drivers
from weewx_evo.ingest.envelope import EnvelopeDriver
from weewx_evo.ingest.listener import Ingest, UdpListener
from weewx_evo.ingest.plugins.push import driver as push
from weewx_evo.netaccess import Access

#: Everything `adminstations.fill` can answer. A placeholder outside this is
#: printed to the operator as `%(whatever)s`.
FILLED = ("address", "port", "base", "path", "identity", "token")

#: Words that give away a note written for the upstream WeeWX extension. The
#: protocols are taken from `weewx-ultimate-push` unchanged, so some of their
#: instructions are about a file this installation does not have; `driver.py`
#: says those our way. This is the guard on that: upstream is free to reword,
#: and a note that stops matching its fragment there turns up here.
NOT_OURS = ("weewx.conf", "[UltimatePush]", "the driver section",
            "running WeeWX")

failures = 0


def check(label: str, got: object, want: object) -> None:
    global failures
    if got == want:
        print(f"  ok   {label}: {got!r}")
    else:
        failures += 1
        print(f"  FAIL {label}: {got!r} != {want!r}")


class Stranger:
    """A driver from outside this repository, with hardware to point at us.

    The whole mechanism is that a driver declares and the page renders. A
    check written against the six protocols in the tree cannot tell that
    apart from a list somebody typed, so the proof is a name nothing here
    knows.
    """

    @staticmethod
    def setup() -> drivers.Setup:
        return drivers.Setup(
            label="Stranger 9000",
            hardware="hardware this repository has never heard of",
            fields=(("Where", "%(base)s%(path)s"), ("Who", "%(identity)s")),
            notes=("Type it in and save.",),
        )

    def packets(self, body: bytes, meta: dict) -> list:
        return []


class Silent:
    """A driver that says nothing, which stays allowed."""

    def packets(self, body: bytes, meta: dict) -> list:
        return []


class Station:
    def __init__(self, name: str, driver: str, identity: str) -> None:
        self.name, self.driver, self.identity = name, driver, identity



class FakeAdmin:
    """Enough of the admin object for the two page functions."""

    def __init__(self, where: Path) -> None:
        self.path = where / "evo.toml"
        self._config = {"token": "a-token", "host": "192.168.1.20",
                        "port": 8000, "reachable_at": "weather.lan:8000"}

    def config(self):
        return self._config


def installed() -> None:
    """Every pushing protocol, plus the envelope, into the registry."""
    push.load(drivers.DEFAULT)
    drivers.DEFAULT.register("json", EnvelopeDriver(), replace=True)


def what_the_drivers_say() -> None:
    print("\nwhat each driver says about pointing hardware at it")

    said = adminstations.setups()
    check("every protocol answers, and the envelope with them",
          sorted(said), sorted(["acurite", "ambient", "ecowitt", "json",
                                "lacrosse", "weatherflow", "wunderground"]))

    # The drift that started this. Named on its own because it is the one
    # case where the hand-written table and the protocol disagreed rather
    # than the table merely being short.
    check("an Ambient console can be told an address",
          "ambient" in adminstations.tellable(), True)
    check("and the protocol is where that comes from",
          [label for label, _v in said["ambient"].fields],
          ["Protocol", "Server IP / Hostname", "Path", "Port",
           "Upload Interval"])

    check("a bridge that cannot be told one is not offered",
          [name for name in ("acurite", "lacrosse", "weatherflow")
           if name in adminstations.tellable()], [])
    # It still has to have a page's worth of instructions, because pointing
    # DNS at this machine is the only way in and it was written down nowhere.
    check("but it still says how it is reached",
          all(adminstations.setups()[name].notes
              for name in ("acurite", "lacrosse", "weatherflow")), True)


def where_the_identity_comes_from() -> None:
    print("\nwho names the station")

    # Structural, not a list: the identity field is ours to hand out exactly
    # where the hardware also lets somebody type it in.
    check("an Ecowitt console brings its own PASSKEY",
          adminstations.learns_its_identity("ecowitt"), True)
    check("so does an Ambient one",
          adminstations.learns_its_identity("ambient"), True)
    check("a Weather Underground ID is typed in, so we hand it out",
          adminstations.learns_its_identity("wunderground"), False)
    check("and so is the envelope's source",
          adminstations.learns_its_identity("json"), False)


def nothing_is_left_unanswered() -> None:
    print("\nwhat the page can fill in")

    # The upstream guard is asked of the taken protocols only. The envelope
    # driver is ours and names a weewx.conf on purpose: there it is an
    # argument to `weewx-evo weewx-driver run`, which reads one, rather than
    # a file this installation is being told to edit.
    taken = {one.name for one in push.protocol_defs.registry()}

    unknown, upstream = [], []
    for name, said in adminstations.setups().items():
        for text in [value for _l, value in said.fields] + list(said.notes):
            unknown += [f"{name}: %({one})s" for one in
                        re.findall(r"%\((\w+)\)s", text) if one not in FILLED]
            if name in taken:
                upstream += [f"{name}: {word}" for word in NOT_OURS
                             if word in text]

    check("no placeholder the page cannot answer", unknown, [])
    # The one that would be invisible: a note pointing at a weewx.conf reads
    # like an instruction, and somebody would go looking for the file.
    check("and no note sends anybody to a weewx.conf", upstream, [])


def a_stranger_is_offered() -> None:
    print("\na driver from outside the repository")

    drivers.DEFAULT.register("stranger", Stranger(), replace=True)
    drivers.DEFAULT.register("mute", Silent(), replace=True)
    try:
        said = adminstations.setups()
        check("it is offered", said.get("stranger") is not None, True)
        check("under its own label",
              said["stranger"].label, "Stranger 9000")
        check("and a driver that says nothing is left out rather than "
              "given an empty page", "mute" not in said, True)
    finally:
        for name in ("stranger", "mute"):
            drivers.DEFAULT._drivers.pop(name, None)


def what_to_type_in(where: Path) -> None:
    print("\nthe page that says what to type into the console")

    admin = FakeAdmin(where)
    for name, expect in (
        ("ecowitt", "/a-token/ecowitt/"),
        ("wunderground", "a-token"),
        ("json", "http://weather.lan:8000/a-token/json/"),
    ):
        station = Station("garden", name, "garden")
        page = adminstations._what_to_enter(admin, station)
        check(f"{name}: the address it was told to reach",
              "weather.lan" in page, True)
        check(f"{name}: and the value that only this installation knows",
              expect in page, True)
        check(f"{name}: nothing left as a placeholder",
              "%(" not in page, True)

    # The wizard's second half names the field rather than saying Ecowitt at
    # an Ambient console, which is what it did while the branch was written
    # out by hand.
    page = adminstations._what_to_enter(
        admin, Station("shed", "ambient", "awaiting:shed"))
    check("a waiting station is told what its console names itself with",
          "PASSKEY" in page and "Ambient Weather" in page, True)


def the_form_offers_them(where: Path) -> None:
    print("\nthe add-a-console form")

    page = adminstations.new(FakeAdmin(where))
    for name, said in adminstations.tellable().items():
        check(f"{name} is in the dropdown",
              f'value="{name}"' in page, True)
        check(f"and described as {said.label!r}", said.label in page, True)

    check("hardware that has to be adopted is named",
          "AcuRite" in page or "Acurite" in page, True)
    # The steps, not only the name: this is the page somebody is on when
    # they find out their bridge cannot be given an address.
    check("with the DNS line it needs", "hubapi.myacurite.com" in page, True)
    check("pointed at this machine", "weather.lan" in page, True)


def a_broadcast_finds_its_driver(where: Path) -> None:
    """A WeatherFlow datagram reaches the WeatherFlow driver.

    It did not. The UDP handler built a path out of its configured driver
    name, `driver_for` matches a known segment before it asks anybody, and
    the configured name is `json` -- so a hub's broadcast went to the
    envelope parser, which reads it as JSON quite happily and stores
    `serial_number`, `type` and `obs` as though they were measurements.
    """
    print("\na hub that broadcasts")

    live = LiveStore(where / "live.sdb", interval_seconds=60)
    try:
        ingest = Ingest(live, token=None, access=Access.parse("any"))
        listener = UdpListener(ingest, "127.0.0.1", 0, driver="json")
        # Without this `handle_request` waits for a datagram that may never
        # come, and a test that hangs reports nothing at all.
        listener.server.timeout = 0.5
        try:
            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sender.sendto(json.dumps({
                "serial_number": "ST-00057453", "type": "obs_st",
                "hub_sn": "HB-00027548",
                "obs": [[int(time.time()), 0.18, 0.22, 0.27, 144, 6,
                         1017.57, 22.37, 50.26, 328, 0.03, 3, 0.000000,
                         0, 0, 0, 2.410, 1]],
                "firmware_revision": 129,
            }).encode(), listener.server.server_address)
            sender.close()

            deadline = time.time() + 5
            seen = []
            while time.time() < deadline and not seen:
                listener.server.handle_request()
                seen = list(live.packets(0, int(time.time()) + 60))
        finally:
            listener.server.server_close()

        check("the broadcast is stored", len(seen), 1)
        if seen:
            check("read by the driver whose protocol it is",
                  seen[0].driver, "weatherflow")
            # Stored with the case the hub used. Folding is done where the
            # comparison is (`Station.matches`), so the journal keeps what
            # arrived rather than a normalised version of it.
            check("under the hub's own name", seen[0].identity, "HB-00027548")
            check("as measurements rather than as envelope keys",
                  "serial_number" in seen[0].data, False)
    finally:
        live.close()


def main() -> int:
    installed()
    where = Path(tempfile.mkdtemp(prefix="consolesetup-"))
    try:
        what_the_drivers_say()
        where_the_identity_comes_from()
        nothing_is_left_unanswered()
        a_stranger_is_offered()
        what_to_type_in(where)
        the_form_offers_them(where)
        a_broadcast_finds_its_driver(where)
    finally:
        shutil.rmtree(where, ignore_errors=True)

    print(f"\n{'FAILED' if failures else 'ok'}: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

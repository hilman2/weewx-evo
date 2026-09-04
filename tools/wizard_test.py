#!/usr/bin/env python3
"""One guided setup per driver, derived from what the driver already says.

The ingest pages had the two halves of setting up hardware in two places. An
Ecowitt is configured by typing an address into a console, and that was on
the sender page. A PurpleAir sensor is configured by telling *us* its
address, and that was a form on the settings page, under a different menu,
with nothing on the sender page to say it existed. Both are one piece of
hardware somebody is standing in front of.

So `steps_of` is one sequence covering both, and it is derived rather than
required: the protocols already say what to type in, what cannot be told
anything, and what has to be configured here. A driver written before this
existed gets a wizard without being touched, and one whose setup is genuinely
different says `steps()` and is left alone.

What is measured here is the deriving, and the rendering of what it derived.

    python tools/wizard_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import adminstations  # noqa: E402
from weewx_evo.ingest import drivers  # noqa: E402
from weewx_evo.options import Group, Option  # noqa: E402
from weewx_evo.stations import Station  # noqa: E402

failures = 0


def check(what: str, got: object, want: object) -> None:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1


class _Pushed(drivers.BaseDriver):
    """Hardware with a field to type an address into."""

    def packets(self, body: bytes, meta: dict) -> list:
        return []

    def setup(self) -> drivers.Setup:
        return drivers.Setup(
            label="Pushed", hardware="a console",
            fields=(("Server", "%(address)s"), ("Path", "%(path)s")),
            notes=("Open the app.",), secret="path")


class _Asked(drivers.BaseDriver):
    """Hardware that answers whoever reaches it, so we are told where it is.

    The case the pages had no place for. Nothing is typed into this: the
    whole of its setup is one address, entered here.
    """

    @classmethod
    def options(cls) -> tuple:
        return (Group("Sensor", "Where it lives.", (
            Option("host", "Address on the network", required=True),
            Option("every", "How often to ask", kind="int", default=60),
        )),)

    def packets(self, body: bytes, meta: dict) -> list:
        return []

    def setup(self) -> drivers.Setup:
        # No fields and no notes: there is nowhere to type anything.
        return drivers.Setup(label="Asked", hardware="a sensor")


class _Redirected(drivers.BaseDriver):
    """Hardware pointed here with DNS, which is instructions and nothing else."""

    def packets(self, body: bytes, meta: dict) -> list:
        return []

    def setup(self) -> drivers.Setup:
        return drivers.Setup(
            label="Redirected", hardware="a bridge",
            notes=("Point its domain at %(address)s.",
                   "    address=/example.com/%(address)s"))


class _OwnSequence(drivers.BaseDriver):
    """A driver whose setup does not fit the derived shape."""

    @classmethod
    def options(cls) -> tuple:
        return (Group("Account", "", (Option("key", "API key"),)),)

    def packets(self, body: bytes, meta: dict) -> list:
        return []

    def setup(self) -> drivers.Setup:
        return drivers.Setup(label="Own", hardware="a service",
                             notes=("Sign in first.",))

    def steps(self) -> tuple:
        return (drivers.Step(title="Sign in", notes=("Go to the website.",)),
                drivers.Step(title="Paste the key", settings=("key",)),
                drivers.Step(title="Wait for the first reading", listens=True))


class _Both(drivers.BaseDriver):
    """An account here, and something to switch on at the other end."""

    @classmethod
    def options(cls) -> tuple:
        return (Group("Account", "", (Option("key", "API key"),)),)

    def packets(self, body: bytes, meta: dict) -> list:
        return []

    def setup(self) -> drivers.Setup:
        return drivers.Setup(label="Both", hardware="a service",
                             fields=(("Webhook", "%(base)s"),), secret="path")


class _Silent(drivers.BaseDriver):
    """Says nothing at all, which is any driver written before this."""

    def packets(self, body: bytes, meta: dict) -> list:
        return []


class FakeAdmin:
    """Enough of the admin object for the page function."""

    def __init__(self, where: Path) -> None:
        self.path = where / "evo.toml"
        self._config = {"token": "a-token", "reachable_at": "weather.lan:8000",
                        "drivers.asked.host": "192.168.1.90"}

    def config(self) -> dict:
        return self._config

    @property
    def language(self):
        from weewx_evo import language as language_defs

        return language_defs.get("en")

    def say(self, english: str) -> str:
        return self.language.say(english)


def _titles(driver: object) -> list[str]:
    return [one.title for one in drivers.steps_of(driver)]


def the_sequence_comes_from_what_the_driver_says() -> None:
    print("\nthe derived sequence")
    check("hardware with a field to type into",
          _titles(_Pushed()),
          ["Enter this into the hardware", "Wait for the first reading"])

    # The one the pages had nowhere for. Settings first, because the rest
    # depends on it: nothing can be waited for until it knows where to ask.
    check("hardware that is asked rather than heard",
          _titles(_Asked()), ["Settings", "Wait for the first reading"])
    check("and its own settings are in the step",
          drivers.steps_of(_Asked())[0].settings, ("host", "every"))

    check("hardware pointed here with DNS",
          _titles(_Redirected()),
          ["Point the hardware here", "Wait for the first reading"])
    check("which says so rather than leaving somebody to work it out",
          "cannot be told" in drivers.steps_of(_Redirected())[0].explain, True)

    # A driver that says nothing still gets a sequence, because the last step
    # is about this end and not about the hardware.
    check("a driver that says nothing about itself",
          _titles(_Silent()), ["Wait for the first reading"])

    # Both halves, which is a cloud service: an account to configure here and
    # something to switch on over there. The order is not cosmetic -- what is
    # typed into the hardware can depend on what was configured here, never
    # the other way round.
    check("hardware with both, settings first",
          _titles(_Both()),
          ["Settings", "Enter this into the hardware",
           "Wait for the first reading"])


def a_driver_may_say_its_own() -> None:
    """Used unchanged. Half derived and half written is an order nobody chose."""
    print("\na driver with its own sequence")
    check("its steps, and only its steps",
          _titles(_OwnSequence()),
          ["Sign in", "Paste the key", "Wait for the first reading"])
    # It declares `notes` in its Setup and an option as well, and neither is
    # merged in: the derived "Settings" step is nowhere in the list above.
    check("nothing derived is added to it",
          [one.settings for one in drivers.steps_of(_OwnSequence())],
          [(), ("key",), ()])


def the_page_renders_what_was_derived(where: Path) -> None:
    print("\nthe page, for each sort of hardware")
    admin = FakeAdmin(where)
    registered = ("pushed", "asked", "redirected", "silent")
    drivers.DEFAULT.register("pushed", _Pushed(), replace=True)
    drivers.DEFAULT.register("asked", _Asked(), replace=True)
    drivers.DEFAULT.register("redirected", _Redirected(), replace=True)
    drivers.DEFAULT.register("silent", _Silent(), replace=True)
    try:
        page = adminstations._what_to_enter(
            admin, Station("garden", "pushed", "garden"))
        check("a console is told what to type",
              "weather.lan" in page and "/a-token/pushed/" in page, True)
        check("and nothing is left as a placeholder", "%(" not in page, True)

        # The measurement that matters. Before this, the sensor's address had
        # no field anywhere on the sender's own page.
        page = adminstations._what_to_enter(
            admin, Station("air", "asked", "air"))
        check("a sensor's address is asked for here",
              'name="host"' in page, True)
        check("with what is already configured in it",
              "192.168.1.90" in page, True)
        check("and it saves through the driver's own settings route",
              'action="./asked"' in page, True)

        page = adminstations._what_to_enter(
            admin, Station("bridge", "redirected", "bridge"))
        check("a bridge gets its DNS line, filled in",
              "address=/example.com/" in page and "%(" not in page, True)

        page = adminstations._what_to_enter(
            admin, Station("mystery", "silent", "mystery"))
        check("a silent driver still gets a page",
              "Wait for the first reading" in page, True)

        # The last step has to *do* the waiting, not only be titled it. A
        # sender whose hardware names itself is finished by reading that name
        # off the wire, and the button is the only way to it: without one the
        # sender stays "awaiting" for good, with a page that looks complete.
        page = adminstations._what_to_enter(
            admin, Station("shed", "pushed", "awaiting:shed"))
        check("a waiting sender gets the button that finishes it",
              "/senders/shed/learn" in page, True)
        page = adminstations._what_to_enter(
            admin, Station("garden", "pushed", "garden"))
        check("and one that does not is told what to watch",
              "Waiting for the first upload" in page, True)

        # Two forms on one page now: the settings step and the button that
        # finishes it. Nested forms do not exist in HTML -- the browser drops
        # the inner tag and keeps its closing one, which closes the outer form
        # early and leaves later buttons belonging to nothing. That took out
        # every publishing page once, and it renders as valid markup.
        page = adminstations._what_to_enter(
            admin, Station("air", "asked", "awaiting:air"))
        depth, worst = 0, 0
        for piece in page.split("<form")[1:]:
            depth += 1
            worst = max(worst, depth)
            depth -= piece.count("</form>")
        check("two forms, neither inside the other",
              (page.count("<form"), worst), (2, 1))

        # A driver that is not installed at all: the station exists, the page
        # must not be blank, and there is nothing to instruct.
        page = adminstations._what_to_enter(
            admin, Station("gone", "notinstalled", "gone"))
        check("an uninstalled driver says so",
              "not installed here" in page, True)
        check("and still prints the address",
              "/a-token/notinstalled/" in page, True)
    finally:
        for name in registered:
            drivers.DEFAULT._drivers.pop(name, None)


def main() -> int:
    the_sequence_comes_from_what_the_driver_says()
    a_driver_may_say_its_own()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        the_page_renders_what_was_derived(Path(raw))

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("every driver has a guided setup, and none of them had to write one")
    return 0


if __name__ == "__main__":
    sys.exit(main())

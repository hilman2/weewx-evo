#!/usr/bin/env python3
"""One way in, whatever the hardware is.

Said five times before it was done, so it is measured rather than described:
a Davis on a serial cable and an Ecowitt on the wifi are the same task to
somebody who has just unpacked one. Before this they were two menus, two
forms and two lists -- Senders in the navigation, "collectors" only through
System -- and finding the second one meant already knowing that this program
files hardware in two places.

What is asked here is the *shape*, because the wording was changed once
without the shape and that fixed nothing:

  * the navigation has one entry for it, and no page reachable only from
    somewhere else
  * one form offers both, so the choice a person makes is what their
    hardware is, not which sort of thing our code calls it
  * that one form, posted, configures either -- ending on the page that
    says what to do next
  * and one list afterwards shows both

    python tools/driverflow_test.py
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import admin as admin_module  # noqa: E402
from weewx_evo import adminstations  # noqa: E402
from weewx_evo.admin import Admin  # noqa: E402
from weewx_evo.cli import all_schemas  # noqa: E402
from weewx_evo.ingest import drivers as driver_defs  # noqa: E402
from weewx_evo.ratelimit import Limits  # noqa: E402

TOKEN = "abcdefghij123456"

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def rendered(page: object) -> str:
    """A page as text. `admin.page` answers bytes for some of them."""
    return (page.decode("utf-8", "replace") if isinstance(page, bytes)
            else str(page))


def visible(markup: object) -> str:
    """The text, without markup. What somebody actually reads."""
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", rendered(markup),
                  flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"<[^>]+>", " ", body)


def an_installation(work: Path) -> Admin:
    (work / "data").mkdir(exist_ok=True)
    path = work / "evo.toml"
    path.write_text(
        f'token = "{TOKEN}"\n'
        f'live_db = "{(work / "data" / "live.sdb").as_posix()}"\n'
        f'archive_db = "{(work / "data" / "weewx.sdb").as_posix()}"\n'
        '[station]\nname = "Kirchdorf"\n'
        "latitude = 48.4012\nlongitude = 11.6301\naltitude = 440.0\n",
        encoding="utf-8")
    driver_defs.DEFAULT.load()
    return Admin(path, lambda: all_schemas(path), TOKEN,
                 limits=Limits(rate=0, failures=0))


def the_navigation_has_one_entry(admin: Admin) -> None:
    print("\nthe navigation")
    page = rendered(admin_module.page(admin, "senders"))

    # The bar itself, not the body: what somebody scans before they know
    # which word this program uses. Matched on the class rather than on the
    # shape of the tag -- the first version of this looked for `<a href=`
    # and the class sits in front of it, so it measured nothing and said
    # "Drivers is missing" about a page that had it.
    bar = re.findall(r'<a class="primary-nav-link"[^>]*>([^<]*)</a>', page)
    named = [said.strip() for said in bar]
    check("Drivers is one of the five", "Drivers" in named, True)
    check("and Senders is not a second one for the same thing",
          "Senders" in named, False)


def one_form_offers_both(admin: Admin) -> None:
    """The choice is the hardware, not our word for how it is wired."""
    print("\nthe form")
    page = adminstations.new(admin)

    values = re.findall(r'<option value="([^"]*)"', page)
    check("a console that uploads is offered", "ecowitt" in values, True)

    fetched = [one for one in values if one.startswith(adminstations.RUNS)]
    check("and hardware that has to be fetched from, in the same menu",
          bool(fetched), True)
    # Named by the box, because that is what somebody has in their hand.
    # `runs:weewx-driver` on its own would be our word again.
    shown = visible(page)
    for box in ("Vantage", "FineOffsetUSB"):
        check(f"{box} is in it by name", box in shown, True)

    # And no second form: a page that still exists but is not linked from
    # here is the same fault one click further away.
    check("with one form to fill in", page.count("<form"), 1)


def the_form_configures_either(work: Path, admin: Admin) -> None:
    """Posted, it ends on the page that says what to do next."""
    print("\nwhat posting it does")

    chosen = [one for one in
              re.findall(r'<option value="([^"]*)"', adminstations.new(admin))
              if one.startswith(adminstations.RUNS) and "vantage" in one]
    check("the Vantage choice carries its kind and its hardware",
          bool(chosen), True)
    if not chosen:
        return

    fetching = adminstations.runs_elsewhere(chosen[0])
    check("which the page can read back", fetching is not None, True)
    if fetching is None:
        return
    kind, hardware = fetching
    check("as a kind that runs elsewhere", kind, "weewx-driver")
    check("and the driver module", hardware, "weewx.drivers.vantage")

    # Through `Admin`, which is what the route calls: a check that wrote the
    # file itself would prove nothing about the form.
    error = admin.add_collector("shed", kind, hardware)
    check("it can be created", error, "")

    admin.refresh()
    made = {one.name for one in admin.schemas}
    check("and its settings page exists", "collector:shed" in made, True)

    # The page it lands on is where somebody continues, so it has to carry
    # the one thing this arrangement costs them.
    shown = visible(admin_module.page(admin, "collector:shed"))
    check("saying where to start it", "Start it where the hardware is" in shown
          or "hardware is" in shown, True)
    check("and with what", "--collector shed" in shown, True)

    # A protocol still works the way it did. The point was to add a road,
    # not to move the one that was there.
    station, error = adminstations.announce(admin, "garden", "ecowitt")
    check("a console that uploads is unaffected", error, "")
    check("and is announced", station is not None, True)


def one_list_shows_both(admin: Admin) -> None:
    print("\nthe list afterwards")
    shown = visible(adminstations.overview(admin))
    check("the driver that runs elsewhere is on it", "shed" in shown, True)
    check("and the console that uploads", "garden" in shown, True)
    check("with the command for the one that needs it",
          "--collector shed" in shown, True)


def system_does_not_own_them(admin: Admin) -> None:
    """System may point at them. It must not be a second way to make one."""
    print("\nand System is not a second door")
    from weewx_evo import adminsystem

    page = adminsystem.overview(admin)
    check("no add link of its own", "new-collector" in page, False)
    check("but it says where they are", './senders' in page, True)


def main() -> int:
    print("one way in, whatever the hardware is")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        the_navigation_has_one_entry(admin)
        one_form_offers_both(admin)
        the_form_configures_either(work, admin)
        one_list_shows_both(admin)
        system_does_not_own_them(admin)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("hardware is hardware: one entry, one form, one list")
    return 0


if __name__ == "__main__":
    sys.exit(main())

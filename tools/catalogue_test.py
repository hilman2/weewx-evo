#!/usr/bin/env python3
"""Which add-on reads what turned up, and what happens when nobody can ask.

The core ships no driver, so the first thing a fresh installation sees is an
upload it cannot read. `listener._unread` keeps it; this is the half that
turns it into a name.

What matters here is that the core stays ignorant. The patterns live in the
catalogue, and everything below is string comparison against what that file
said -- so this measures the comparison and the two states the network can be
in, and never that weewx-evo knows what an Ecowitt upload looks like.

    python tools/catalogue_test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import catalogue  # noqa: E402

failures = 0

#: A catalogue in the shape the real one is in, written here so that this
#: measures the matching rather than whatever is on GitHub today.
CATALOGUE = """
version = 1

[[plugin]]
name = "weewx-evo-ecowitt"
kind = "driver"
provides = "ecowitt"
summary = "Ecowitt custom upload."
detects = { body = ["PASSKEY="], not_body = ["AMBWeather"] }

[[plugin]]
name = "weewx-evo-ambient"
kind = "driver"
provides = "ambient"
summary = "Ambient Weather."
detects = { body = ["PASSKEY=", "AMBWeather"] }

[[plugin]]
name = "weewx-evo-acurite"
kind = "driver"
provides = "acurite"
summary = "Acurite bridges."
detects = { body = ["mt=", "id="] }

[[plugin]]
name = "weewx-evo-wunderground"
kind = "driver"
provides = "wunderground"
summary = "Weather Underground."
detects = { body = ["action=updateraw"], path = ["/weatherstation/updateweatherstation.php"] }

[[plugin]]
name = "weewx-evo-sftp"
kind = "export"
provides = "sftp"
summary = "An export, which reads no uploads at all."

[[plugin]]
name = "weewx-evo-weewx-driver"
kind = "collector"
provides = "weewx-driver"
summary = "Any WeeWX driver, run in its own process."
hardware = ["Davis Vantage Pro, Pro2, Vue", "ADS WS1"]

[[plugin]]
name = "weewx-evo-onebox"
kind = "driver"
provides = "onebox"
summary = "An entry naming one box, written the way one is written."
hardware = "Peet Bros Ultimeter"
"""


#: How many entries the sample above has. Counted rather than typed: the
#: three checks below say "the copy came back whole", and a literal there
#: makes adding an entry to the sample look like a broken fallback.
ENTRIES = CATALOGUE.count("[[plugin]]")


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def reads(body: str, path: str = "") -> list[str]:
    return [one.provides for one
            in catalogue.matching(catalogue.parse(CATALOGUE), body, path)]


def what_sent_it_beats_where_it_was_sent() -> None:
    print("\nwhich add-on reads what")
    check("an Ecowitt custom upload",
          reads("PASSKEY=34F5&stationtype=GW2000A_V3&tempf=59.7", "/ecowitt/"),
          ["ecowitt"])
    # The same PASSKEY, and the thing that separates them is one word in the
    # station type. Without `not_body` this would answer both.
    check("an Ambient one, which also carries a PASSKEY",
          reads("PASSKEY=AABB&stationtype=AMBWeather_WS2902&tempf=59.7", "/d/"),
          ["ambient"])
    check("a console that can only post to the WU path",
          reads("ID=KXX&PASSWORD=x&action=updateraw&tempf=41",
                "/weatherstation/updateweatherstation.php"),
          ["wunderground"])

    # An Acurite bridge is pointed at the WU path with DNS, so it matches
    # Weather Underground on the path and Acurite on the body. Both are
    # offered, and the one that matched on what was actually sent is first.
    check("an Acurite bridge on the Weather Underground path",
          reads("id=24C86E&mt=5N1x31&sensor=02004&windspeedmph=9",
                "/weatherstation/updateweatherstation.php"),
          ["acurite", "wunderground"])

    check("something nothing recognises", reads("hello", "/x/"), [])
    check("and an export is never a candidate",
          "sftp" in reads("PASSKEY=1", "/ecowitt/"), False)


def the_order_is_the_same_everywhere() -> None:
    """The same upload has to give the same advice on two installations."""
    print("\nthe same answer twice")
    body, path = ("id=1&mt=x", "/weatherstation/updateweatherstation.php")
    first = reads(body, path)
    check("stable across calls", [reads(body, path) for _ in range(3)],
          [first, first, first])


def a_broken_catalogue_is_no_catalogue() -> None:
    """Not an exception. A settings page that will not render is worse."""
    print("\nwhat comes back is not a catalogue")
    check("unparseable TOML", catalogue.parse("this is not [ toml"), [])
    check("valid TOML that is not this", catalogue.parse("nothing = 1"), [])
    check("an entry with no name is skipped",
          [one.provides for one in catalogue.parse(
              '[[plugin]]\nprovides = "x"\n')], [])


def offline_keeps_what_it_had() -> None:
    """A station with no way out is a supported state, not an error.

    `weewx-evo driver install` takes a local path, so the network is not the
    only route in. What must not happen is a page that says nothing because
    GitHub could not be reached.
    """
    print("\nno way out")
    with tempfile.TemporaryDirectory() as raw:
        where = Path(raw)
        # Nothing cached and nothing reachable: empty, and no exception.
        check("with nothing cached, nothing and no error",
              catalogue.fetch(where, url="http://127.0.0.1:1/nope",
                              timeout=0.5), [])

        (where / catalogue.FILENAME).write_text(
            json.dumps({"when": time.time(), "text": CATALOGUE}),
            encoding="utf-8")
        got = catalogue.fetch(where, url="http://127.0.0.1:1/nope",
                              timeout=0.5)
        check("with a copy, the copy", [one.provides for one in got][:5],
              ["ecowitt", "ambient", "acurite", "wunderground", "sftp"])

        # And a fetch that succeeds but brings back something that is not a
        # catalogue must not replace a copy that worked.
        (where / catalogue.FILENAME).write_text(
            json.dumps({"when": 0, "text": CATALOGUE}), encoding="utf-8")
        kept = catalogue.fetch(where, url="http://127.0.0.1:1/nope",
                               timeout=0.5, force=True)
        check("a failed refresh keeps the last good one", len(kept), ENTRIES)


def a_fresh_copy_is_not_fetched_every_time() -> None:
    """The list changes when somebody publishes. That is not hourly."""
    print("\nhow often it asks")
    with tempfile.TemporaryDirectory() as raw:
        where = Path(raw)
        (where / catalogue.FILENAME).write_text(
            json.dumps({"when": time.time(), "text": CATALOGUE}),
            encoding="utf-8")
        # An unreachable URL: if it were asked, this would be empty.
        check("a copy from just now is used without asking",
              len(catalogue.fetch(where, url="http://127.0.0.1:1/nope",
                                  timeout=0.5)), ENTRIES)
        (where / catalogue.FILENAME).write_text(
            json.dumps({"when": time.time() - catalogue.STALE_AFTER - 1,
                        "text": CATALOGUE}), encoding="utf-8")
        # Stale, so it asks, fails, and falls back to the same copy.
        check("a stale one is still used when the asking fails",
              len(catalogue.fetch(where, url="http://127.0.0.1:1/nope",
                                  timeout=0.5)), ENTRIES)


def an_entry_names_the_boxes_it_reads() -> None:
    """Searchable by what is on the pole, which is all anybody knows.

    One entry covers the thirteen drivers WeeWX ships, so the row holding the
    answer to "does it do my Vantage" has to say Vantage. It is in the
    catalogue rather than worked out here: only the add-on knows what it
    reads, and a list in the core would be a second one to keep current.
    """
    found = {one.name: one for one in catalogue.parse(CATALOGUE)}

    shim = found["weewx-evo-weewx-driver"]
    check("the boxes are read off the entry", shim.hardware,
          ("Davis Vantage Pro, Pro2, Vue", "ADS WS1"))
    check("and a search for one of them finds it",
          any("Vantage" in one for one in shim.hardware), True)

    # A string is one name. Split into characters it would put twenty
    # entries in the row, and the row is what somebody reads.
    check("one box may be written as one string",
          found["weewx-evo-onebox"].hardware, ("Peet Bros Ultimeter",))

    # Optional, and an entry without it is not broken. Every entry that
    # existed before this field does without it.
    check("an entry that names none has none",
          found["weewx-evo-sftp"].hardware, ())


def main() -> int:
    what_sent_it_beats_where_it_was_sent()
    an_entry_names_the_boxes_it_reads()
    the_order_is_the_same_everywhere()
    a_broken_catalogue_is_no_catalogue()
    offline_keeps_what_it_had()
    a_fresh_copy_is_not_fetched_every_time()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("the catalogue says which add-on reads it, and the core does not know")
    return 0


if __name__ == "__main__":
    sys.exit(main())

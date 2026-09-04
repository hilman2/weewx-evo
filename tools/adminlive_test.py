#!/usr/bin/env python3
"""The live table in the settings page: the rows, as the table has them.

Every other page in the settings is an interpretation. This one is the
`packet` table, so the thing it has to get right is that it shows the table
rather than a view of it -- every column, from the schema, with the values as
stored.

Three things are checked, and the third is the one a browser would not show:

  * every column the table has comes back, read from the schema and not from
    a list, and the values are what is in it
  * each reading carries the archive column it reaches, out of the *same*
    placer the archiver builds records with. A contested one reaches nothing
    until somebody decides, which is the row this page is opened for.
  * a request opens no connection it does not close. This polls every three
    seconds and somebody leaves it open; a descriptor per refresh is the
    shape that took nine hours to show itself as three unrelated errors.

    python tools/adminlive_test.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import adminlive  # noqa: E402
from weewx_evo.admin import Admin  # noqa: E402
from weewx_evo.cli import all_schemas  # noqa: E402
from weewx_evo.db.archive import ArchiveStore  # noqa: E402
from weewx_evo.db.live import LiveStore, Packet, sender_id  # noqa: E402

failures = 0
TOKEN = "abcdefghij123456"

#: A real Ecowitt upload's names, trimmed. `tf_ch1` is contested on purpose:
#: two drivers disagree about where it goes, so nothing places it until
#: somebody says, and that is the row this page is for. `stationtype` is the
#: console talking about itself -- in the table like everything else.
SENT = {"tempf": "66.6", "humidity": "81", "baromrelin": "30.127",
        "tf_ch1": "66.6", "stationtype": "EasyWeatherPro_V5.2.7"}
MAPPING = {
    "version": 1,
    "fields": {"tempf": "outTemp", "humidity": "outHumidity",
               "baromrelin": "barometer", "tf_ch1": "extraTemp1"},
    "contested": ["tf_ch1"],
    "scale": {},
    "metadata": ["stationtype"],
    "absent": ["", "None", "-9999"],
    "groups": {},
    "usUnits": 1,
}
SENDER = sender_id("ecowitt", "AAAA")


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def an_installation(work: Path, placements: str = "") -> Admin:
    (work / "data").mkdir(exist_ok=True)
    (work / "evo.toml").write_text(
        f'token = "{TOKEN}"\n'
        f'archive_db = "{(work / "data" / "weewx.sdb").as_posix()}"\n'
        f'live_db = "{(work / "data" / "live.sdb").as_posix()}"\n',
        encoding="utf-8")
    (work / "stations.toml").write_text(
        '[stations.kirchdorf]\ndriver = "ecowitt"\n'
        'identity = "AAAA"\narchive = "default"\n', encoding="utf-8")
    placements = placements.replace('station = "kirchdorf"',
                                    f'station = "{SENDER}"')
    (work / "placement.toml").write_text(placements, encoding="utf-8")
    (work / "archives.toml").write_text(
        "[archives.default]\n"
        f'file = "{(work / "data" / "weewx.sdb").as_posix()}"\n'
        f'primary = "{SENDER}"\n\n'
        f'[archives.default.members."{SENDER}"]\n'
        'indoor = true\n',
        encoding="utf-8")
    ArchiveStore(work / "data" / "weewx.sdb").close()
    path = work / "evo.toml"
    return Admin(path, lambda: all_schemas(path), TOKEN)


def a_packet(live: LiveStore, when: int, data: dict) -> None:
    live.add(Packet(dateTime=when, usUnits=1, data=dict(data),
                    driver="ecowitt", identity="AAAA", dialect="ecowitt",
                    mapping=MAPPING))
    # The listener maintains presentation metadata in the live directory.
    # Diagnostics must not open stations.toml to recover it.
    live.conn.execute(
        "UPDATE sender_identity SET label = ? WHERE sender = ?",
        ("kirchdorf", SENDER))


def every_column_comes_back() -> None:
    """The table as it stands, not a view of it.

    Read from `PRAGMA table_info` rather than a list here: this table has
    gained columns twice, and a list would be a second schema that is wrong
    on exactly the run somebody is using this page to debug.
    """
    print("\nthe packet table, column for column")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        now = int(time.time())
        live = LiveStore(work / "data" / "live.sdb")
        for step in range(3):
            a_packet(live, now - step * 16, SENT)
        actual = [row[1] for row in
                  live.conn.execute("PRAGMA table_info(packet)")]
        live.close()

        found = adminlive.feed(admin)
        check("it read the table", found["reason"], "")
        check("every column the table has", found["columns"], actual)
        check("three rows", len(found["rows"]), 3)
        check("counted against the whole table", found["held"], 3)

        one = found["rows"][0]
        check("the pair the row is keyed on",
              (one["driver"], one["identity"]), ("ecowitt", "AAAA"))
        check("the vocabulary it is written in", one["dialect"], "ecowitt")
        check("its sequence number is there", one["seq"] > 0, True)
        check("the raw upload column, empty here", one["raw"], None)
        check("the readings, under the console's own names",
              sorted(one["data"]), sorted(SENT))
        check("with the values as stored", one["data"]["tempf"], "66.6")

        # Beside the row, not in it. A name is a lookup; freezing one into
        # the table is what used to split a series on a rename.
        check("the display name comes from live", one["sender_name"],
              "kirchdorf")
        check("but there is no such column",
              "sender_name" in found["columns"], False)
        check("the canonical sender is the stored selection key",
              one["canonical_sender"], SENDER)
        check("the Place assignment comes from archives.toml",
              one["places"], ["default"])


def where_each_reading_goes() -> None:
    """The one thing this page gives that `sqlite3` on the box cannot."""
    print("\nand the column each reading reaches")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        live = LiveStore(work / "data" / "live.sdb")
        a_packet(live, int(time.time()), SENT)
        live.close()

        goes = adminlive.feed(admin)["rows"][0]["goes_to"]
        check("a reading the catalog places", goes.get("tempf"), "outTemp")
        check("and one that needed a rule",
              goes.get("baromrelin"), "barometer")
        # Contested: two drivers disagree, so nothing writes it until
        # somebody decides. That is the row this page is opened for.
        check("a contested one reaches nothing", "tf_ch1" in goes, False)
        # Housekeeping is in the row like everything else -- this page shows
        # the table -- and it reaches no column, which is the truth.
        check("nor does what the console says about itself",
              "stationtype" in goes, False)


def a_decision_shows_up() -> None:
    """The page follows the file, because it uses the same placer.

    A second answer to "where does this go" is the mistake `chartdata.py`
    describes: both right on their own, differing in the one case somebody
    opened the page to look at.
    """
    print("\nafter a placement is written")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work, placements=(
            '[[takes]]\narchive = "default"\nstation = "kirchdorf"\n'
            '[takes.fields]\n"tf_ch1" = "soilTemp1"\n'))
        live = LiveStore(work / "data" / "live.sdb")
        a_packet(live, int(time.time()), SENT)
        live.close()

        goes = adminlive.feed(admin)["rows"][0]["goes_to"]
        check("the contested reading now names its column",
              goes.get("tf_ch1"), "soilTemp1")
        check("and the rest are where they were",
              goes.get("tempf"), "outTemp")


def a_row_that_will_not_parse_is_shown() -> None:
    """Not silently emptied -- that is the row somebody came here to find."""
    print("\na data column that is not JSON")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        live = LiveStore(work / "data" / "live.sdb")
        a_packet(live, int(time.time()), SENT)
        live.conn.execute("UPDATE packet SET data = ?", ("not json at all",))
        live.close()

        one = adminlive.feed(admin)["rows"][0]
        check("the row is still listed", one["seq"] > 0, True)
        check("and says the column could not be read",
              "(unreadable)" in one["data"], True)


def it_is_loaded_a_page_at_a_time() -> None:
    """Thirty rows to open with, the rest on scrolling.

    And paged on `seq`, not on an offset. This table is written to while
    somebody reads it: with `LIMIT ... OFFSET` a row arriving between two
    scrolls shifts everything down one, so the reader sees a row twice and
    never sees another -- silently, on the page they opened to find out what
    is actually there.
    """
    print("\na page at a time, while the table is being written to")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        now = int(time.time())
        live = LiveStore(work / "data" / "live.sdb")
        for step in range(70):
            a_packet(live, now - step * 16, SENT)
        live.close()

        first = adminlive.feed(admin, limit=30)
        check("thirty to open with", len(first["rows"]), 30)
        check("out of seventy", first["held"], 70)
        check("and it says there are more", first["more"], True)

        oldest = first["rows"][-1]["seq"]
        second = adminlive.feed(admin, limit=30, before=oldest)
        check("the next page is thirty more", len(second["rows"]), 30)
        check("all of them older", max(r["seq"] for r in second["rows"]),
              oldest - 1)
        seen = {r["seq"] for r in first["rows"]} | {
            r["seq"] for r in second["rows"]}
        check("with nothing shown twice", len(seen), 60)

        third = adminlive.feed(admin, limit=30,
                               before=second["rows"][-1]["seq"])
        check("and the last page is short", len(third["rows"]), 10)
        check("which is how the page knows to stop", third["more"], False)

        # A packet arrives between two scrolls. On an offset the reader would
        # now see one row twice and miss another; on `seq` the page below is
        # exactly the page below.
        live = LiveStore(work / "data" / "live.sdb")
        a_packet(live, now + 16, SENT)
        live.close()
        again = adminlive.feed(admin, limit=30, before=oldest)
        check("a packet arriving does not shift the page underneath",
              [r["seq"] for r in again["rows"]],
              [r["seq"] for r in second["rows"]])


def the_poll_asks_only_for_what_is_new() -> None:
    """So that scrolling is not undone every three seconds.

    Re-fetching the first page would throw away everything the reader had
    scrolled in, put them back at the top, and place thirty rows again --
    every three seconds, on a page meant to be left open.
    """
    print("\nthe refresh brings only what has arrived")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        now = int(time.time())
        live = LiveStore(work / "data" / "live.sdb")
        for step in range(5):
            a_packet(live, now - step * 16, SENT)
        live.close()

        first = adminlive.feed(admin)
        newest = first["rows"][0]["seq"]
        check("nothing new yet", adminlive.feed(admin, after=newest)["rows"], [])

        live = LiveStore(work / "data" / "live.sdb")
        a_packet(live, now + 16, SENT)
        a_packet(live, now + 32, SENT)
        live.close()

        fresh = adminlive.feed(admin, after=newest)
        check("two arrived", len(fresh["rows"]), 2)
        check("newest first, so they prepend in order",
              fresh["rows"][0]["seq"] > fresh["rows"][1]["seq"], True)
        check("and the summary comes with them", fresh["held"], 7)


def an_empty_table_says_so() -> None:
    """Not "nothing is arriving" about a database it cannot see.

    A split installation keeps the live table on the machine with the
    listener, and the two answers want different things done about them.
    """
    print("\nwith nothing to read")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        found = adminlive.feed(admin)
        check("no database is said as such",
              found["reason"], "no live database here")

        LiveStore(work / "data" / "live.sdb").close()
        found = adminlive.feed(admin)
        check("an empty one is not an error", found["reason"], "")
        check("its columns are still known", len(found["columns"]) > 5, True)
        check("and it holds nothing", found["rows"], [])


def nothing_is_left_open() -> None:
    """Polled every three seconds, on a page somebody leaves open."""
    print("\nthirty refreshes leave nothing behind")
    import gc
    import sqlite3

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        live = LiveStore(work / "data" / "live.sdb")
        a_packet(live, int(time.time()), SENT)
        live.close()

        for _ in range(30):
            adminlive.feed(admin)
        gc.collect()
        left = [o for o in gc.get_objects() if isinstance(o, sqlite3.Connection)]
        open_ones = [o for o in left if _still_open(o)]
        check("no connection is still open", len(open_ones), 0)


def no_listener_code_interprets_stored_rows() -> None:
    """The live DB is the boundary: stored mapping, not a running driver."""
    print("\nstored rows need neither station configuration nor a driver registry")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        live = LiveStore(work / "data" / "live.sdb")
        a_packet(live, int(time.time()), SENT)
        live.close()

        from weewx_evo import adminstations
        from weewx_evo.ingest import drivers

        old_load = adminstations.load
        old_driver_load = drivers.DEFAULT.load

        def forbidden(*_args, **_kwargs):
            raise AssertionError("listener configuration reached live diagnostics")

        adminstations.load = forbidden
        drivers.DEFAULT.load = forbidden
        try:
            found = adminlive.feed(admin)
        finally:
            adminstations.load = old_load
            drivers.DEFAULT.load = old_driver_load
        check("the row is still interpreted", found["reason"], "")
        check("its stored mapping still reaches the Place field",
              found["rows"][0]["goes_to"].get("tempf"), "outTemp")


def _still_open(conn: object) -> bool:
    try:
        conn.execute("SELECT 1")
    except Exception:
        return False
    return True


def the_page_renders() -> None:
    print("\nthe page itself")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        admin = an_installation(Path(raw))
        page = adminlive.overview(admin)
        check("it has somewhere to put the rows",
              'id="liverows"' in page, True)
        check("it is explicitly a read-only diagnosis",
              ("Live journal" in page, "Read-only diagnosis" in page),
              (True, True))
        check("it consistently names senders",
              'id="livesenders"' in page, True)
        # A console names its own fields and both the names and the values
        # reach this table, so nothing is written into the document as markup.
        check("and builds its rows without innerHTML",
              "innerHTML" in adminlive._SCRIPT, False)
        check("the sidebar names it", adminlive.nav(admin, "live"),
              ['<a href="./live" aria-current=\'page\'>Live journal</a>'])


def it_lays_out_as_a_table() -> None:
    """Asked of the computed style, which is what a browser actually applies.

    The fault this exists for: the table carried `class="stations fields"`,
    which is the placement form's layout -- `table-layout: fixed` with five
    hard column widths written for a five-column table. Twelve columns in
    that shared what was left, so every cell wrapped to one character per
    line and the twelve headings stacked on top of each other. The markup was
    correct, every test on it was green, and the page was unreadable.

    Neither the HTML nor the stylesheet alone decides that: only both
    together, which is why this asks jsdom rather than reading either.
    """
    print("\nas a browser lays it out")
    reason = _no_javascript()
    if reason:
        print(f"  --   skipped: {reason}")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        admin = an_installation(work)
        from weewx_evo.admin import page as render_page

        # The whole page, shell and stylesheet included. Rendering the
        # fragment alone would measure the markup, and the markup was
        # never the problem.
        where = work / "live.html"
        # `page` answers in bytes, because that is what the server
        # writes to the socket.
        where.write_bytes(render_page(admin, "live"))
        script = ROOT / "tools" / "live_page_test.js"
        got = subprocess.run(["node", str(script), str(where)],
                             capture_output=True, text=True, timeout=60,
                             check=False)
        if got.returncode != 0 or not got.stdout.strip():
            check("node could read the page", got.stderr.strip()[:200], "")
            return
        found = json.loads(got.stdout)

        check("it has its own class, not the form's",
              found["className"], "rows")
        check("laid out from its contents, not from five fixed widths",
              found["tableLayout"], "auto")
        check("and as wide as they are", found["tableWidth"], "max-content")
        # Both, so the browser takes whichever is larger. `max-content` on
        # its own leaves a wide screen empty on the right; `100%` on its own
        # squeezes twelve columns and puts the wrapping back.
        check("but never narrower than the space it is given",
              found["tableMinWidth"], "100%")
        check("and one column takes the slack",
              found["stretches"], ["raw"])
        # A database row is not a paragraph, so the page it sits on is not
        # capped at a reading width the way the forms are.
        check("on a page that is not capped at a reading width",
              found["mainMaxWidth"], "none")
        check("which is a state of its own, not the forms'",
              found["mainClass"], "full")
        check("no cell wraps", found["cellWhiteSpace"], "nowrap")
        check("nor does a heading", found["headWhiteSpace"], "nowrap")
        # The rule that did it, by name.
        check("and nothing breaks a value between its characters",
              found["cellOverflowWrap"] in ("", "normal"), True)
        # Which only works because there is somewhere to scroll it.
        check("there is somewhere to scroll it", found["scroller"], True)
        check("sideways", found["scrollerOverflowX"], "auto")


def _no_javascript() -> str:
    """A node with jsdom, or a word saying why not."""
    if shutil.which("node") is None:
        return "there is no node on PATH"
    found = subprocess.run(["node", "-e", "require('jsdom')"],
                           capture_output=True, text=True, check=False)
    if found.returncode != 0:
        return "node is there but jsdom is not (npm install -g jsdom)"
    return ""


def main() -> int:
    every_column_comes_back()
    where_each_reading_goes()
    a_decision_shows_up()
    a_row_that_will_not_parse_is_shown()
    it_is_loaded_a_page_at_a_time()
    the_poll_asks_only_for_what_is_new()
    an_empty_table_says_so()
    nothing_is_left_open()
    no_listener_code_interprets_stored_rows()
    the_page_renders()
    it_lays_out_as_a_table()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("the live table shows its rows, and where each reading goes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

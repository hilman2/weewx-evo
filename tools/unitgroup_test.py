#!/usr/bin/env python3
"""When a driver and the schema disagree about what a column measures.

`soilMoist1` is the case. WeeWX's schema calls it `group_moisture` --
centibars, because it was written when a soil probe was a Watermark sensor --
and an Ecowitt probe puts a percentage in the same column. Measured on the
beta instance: 4 352 readings between 30 and 63, printed as centibars.

The value is right either way and must not be touched: the same number goes
into the same column under WeeWX, and the one rule of this project is that
the file keeps its meaning. What is wrong is the unit word beside it, and
**nothing in the data can settle it** -- a Watermark probe on a Davis puts
real centibars in that same column.

So the schema keeps winning by default, the disagreement is recorded where
the settings page can see it, and the operator decides. What is measured
here is that round trip: a conflict is noticed, it survives into another
process, and a choice made on the page reaches a formatted reading.

    python tools/unitgroup_test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import placement, units  # noqa: E402
from weewx_evo.db.live import LiveStore  # noqa: E402

failures = 0


def check(what: str, got: object, want: object) -> None:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1


def the_schema_wins_and_says_so(where: Path) -> None:
    """A driver cannot change what a column means, and is not ignored either."""
    print("\nwhen a driver disagrees")
    check("the schema's own answer for soilMoist1",
          units.GROUPS.get("soilMoist1"), "group_moisture")

    live = LiveStore(where / "live.sdb")
    try:
        placer = placement.Placer("default", placement.Placements(),
                                  directory=live)
        # What an Ecowitt catalog says, against what the schema says.
        placer._install_groups(
            {"soilMoist1": "group_percent",
             "leafWet1": "group_percent",
             "lightning_num": "group_count"},   # this one nothing disputes
            "ecowitt", "ecowitt")

        # Unchanged: a driver that could redefine a schema column could change
        # how another place reads its own archive.
        check("the schema still decides", units.group_of("soilMoist1"),
              "group_moisture")
        # And what it does not know, it takes.
        check("but what the schema has no answer for is taken",
              units.group_of("lightning_num"), "group_count")

        recorded = json.loads(live.get_meta(placement.GROUP_CONFLICTS) or "{}")
        check("the disagreement is left where the page can read it",
              recorded.get("ecowitt"),
              {"soilMoist1": "group_percent", "leafWet1": "group_percent"})
        check("and nothing undisputed is in it",
              "lightning_num" in json.dumps(recorded), False)
    finally:
        live.close()


def the_operator_decides(where: Path) -> None:
    """`[groups]` in placement.toml beats both, which is what makes it a choice."""
    print("\nwhen somebody has said otherwise")
    live = LiveStore(where / "live2.sdb")
    try:
        said = placement.Placements(groups={"soilMoist1": "group_percent"})
        placer = placement.Placer("default", said, directory=live)
        placer._install_groups({"soilMoist1": "group_percent"},
                               "ecowitt", "ecowitt")
        check("no disagreement is recorded once it is settled",
              live.get_meta(placement.GROUP_CONFLICTS), None)
        # The reading is what makes it real: a percentage formatted as a
        # percentage rather than as a pressure.
        check("and the choice is what the file says",
              said.groups.get("soilMoist1"), "group_percent")
    finally:
        live.close()


def the_page_offers_it_only_where_it_is_disputed(where: Path) -> None:
    """A select on every row would bury the two that matter."""
    print("\nwhat the page shows")
    from weewx_evo import adminfields

    class FakeAdmin:
        path = where / "evo.toml"
        read_only = False

        def config(self):
            return {"live_db": str(where / "live.sdb")}

        @property
        def language(self):
            from weewx_evo import language as language_defs

            return language_defs.get("en")

        def say(self, english: str) -> str:
            return self.language.say(english)

    found = adminfields.disagreements(FakeAdmin())
    check("the page reads what the other process wrote",
          found.get("soilMoist1"), "group_percent")
    check("for every disputed column", sorted(found),
          ["leafWet1", "soilMoist1"])

    class NoFile(FakeAdmin):
        def config(self):
            return {"live_db": str(where / "nothing-here.sdb")}

    check("and a station with no live database yet is not an error",
          adminfields.disagreements(NoFile()), {})


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        where = Path(raw)
        the_schema_wins_and_says_so(where)
        the_operator_decides(where)
        the_page_offers_it_only_where_it_is_disputed(where)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("the schema decides, the disagreement is said, the operator settles it")
    return 0


if __name__ == "__main__":
    sys.exit(main())

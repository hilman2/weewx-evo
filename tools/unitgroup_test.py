#!/usr/bin/env python3
"""Who decides what a column measures, and it has to be one answer.

`soilMoist1` is the case. WeeWX's schema calls it `group_moisture` --
centibars, because it was written when a soil probe was a Watermark sensor --
and an Ecowitt probe puts a percentage in the same column. Six columns on the
beta instance disagree like that.

The value is right either way and must not be touched: the same number goes
into the same column under WeeWX, and the one rule of this project is that
the file keeps its meaning. What is at stake is the unit word beside it.

**The fault this exists for is that there were two answers.**
`units.group_of` asks the drivers before the schema, and says why -- a driver
knows its own fields and the core's table is the standard schema and nothing
else. `placement._install_groups` asked them in the opposite order. So a
settings page with the driver loaded printed "percent" while a record built
from the stored dialect was told "moisture", and neither could see the other.

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


def _fresh() -> None:
    """Forget what a driver contributed. Process-wide state, so it has to go."""
    units.contribute({})


def a_catalog_may_improve_on_the_schema(where: Path) -> None:
    """The order `units.group_of` documents, now in both places."""
    print("\na catalog against the standard schema")
    _fresh()
    check("the schema's own answer", units.GROUPS.get("soilMoist1"),
          "group_moisture")

    live = LiveStore(where / "one.sdb")
    try:
        placer = placement.Placer("default", placement.Placements(),
                                  directory=live)
        placer._install_groups(
            {"soilMoist1": "group_percent",      # the schema has an answer
             "lightning_num": "group_count"},    # it has none
            "ecowitt", "ecowitt")

        # The point of the change. Before it, this stayed group_moisture here
        # and became group_percent in any process that loaded the driver.
        check("the catalog wins over the schema",
              units.group_of("soilMoist1"), "group_percent")
        check("and takes what the schema does not know",
              units.group_of("lightning_num"), "group_count")
        check("with nothing recorded as a disagreement",
              live.get_meta(placement.GROUP_CONFLICTS), None)
    finally:
        live.close()
        _fresh()


def but_not_over_another_console(where: Path) -> None:
    """One console's data must not change how another place reads its own."""
    print("\na second catalog, disagreeing with the first")
    _fresh()
    live = LiveStore(where / "two.sdb")
    try:
        placer = placement.Placer("default", placement.Placements(),
                                  directory=live)
        placer._install_groups({"soilMoist1": "group_percent"},
                               "ecowitt", "ecowitt")
        placer._install_groups({"soilMoist1": "group_moisture"},
                               "davis", "vantage")

        check("the first one still holds",
              units.group_of("soilMoist1"), "group_percent")
        recorded = json.loads(live.get_meta(placement.GROUP_CONFLICTS) or "{}")
        check("and the second is recorded as a disagreement",
              recorded.get("davis"), {"soilMoist1": "group_moisture"})
        check("named by the driver that raised it, so the page can say which",
              sorted(recorded), ["davis"])
    finally:
        live.close()
        _fresh()


def and_never_over_the_operator(where: Path) -> None:
    """`[groups]` in placement.toml is the answer when consoles disagree."""
    print("\nwhen somebody has written it down")
    _fresh()
    live = LiveStore(where / "three.sdb")
    try:
        said = placement.Placements(groups={"soilMoist1": "group_moisture"})
        placer = placement.Placer("default", said, directory=live)
        placer._install_groups({"soilMoist1": "group_percent"},
                               "ecowitt", "ecowitt")

        # Not contributed, so `group_of` falls through to the schema -- which
        # is what the operator wrote. The line in the file is what makes this
        # settleable at all: nothing in the data can say which probe is in
        # the ground.
        check("the catalog does not overwrite it",
              units.contributed().get("soilMoist1"), None)
        recorded = json.loads(live.get_meta(placement.GROUP_CONFLICTS) or "{}")
        check("and it is recorded, so the page can offer the other answer",
              recorded.get("ecowitt"), {"soilMoist1": "group_percent"})
    finally:
        live.close()
        _fresh()


def the_page_reads_it(where: Path) -> None:
    """Another process. The live table is the only channel between them."""
    print("\nwhat the settings page can see")
    from weewx_evo import adminfields

    class FakeAdmin:
        path = where / "evo.toml"
        read_only = False

        def config(self):
            return {"live_db": str(where / "three.sdb")}

        @property
        def language(self):
            from weewx_evo import language as language_defs

            return language_defs.get("en")

        def say(self, english: str) -> str:
            return self.language.say(english)

    found = adminfields.disagreements(FakeAdmin())
    check("it reads what the other process wrote",
          found.get("soilMoist1"), "group_percent")

    class NoFile(FakeAdmin):
        def config(self):
            return {"live_db": str(where / "nothing-here.sdb")}

    check("and a station with no live database yet is not an error",
          adminfields.disagreements(NoFile()), {})


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        where = Path(raw)
        a_catalog_may_improve_on_the_schema(where)
        but_not_over_another_console(where)
        and_never_over_the_operator(where)
        the_page_reads_it(where)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("one order everywhere: the operator, then a driver, then the schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())

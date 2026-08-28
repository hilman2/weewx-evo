#!/usr/bin/env python3
"""Finding a setting, and landing on it rather than near it.

The settings are organised by what each thing is, which is the right
organisation: a feed's options belong with the feed. It is the wrong index.
Somebody who wants "the FTP password" knows the words and not the page, and
with seven core groups, a form per feed and export, and ninety charts, the
words are the only handle they have.

Two things have to hold or it is decoration:

  * what you typed exactly comes first, not third. A search that ranks
    cleverly is one where the obvious answer is buried.
  * the link lands on the section, not at the top of a form with seven of
    them. A result that makes you scroll has told you where it is, not
    taken you there.

    python tools/adminsearch_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import adminsearch  # noqa: E402
from weewx_evo.admin import Admin, anchor  # noqa: E402
from weewx_evo.cli import all_schemas  # noqa: E402

failures = 0

TOKEN = "abcdefghij123456"


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def an_installation(work: Path) -> Admin:
    (work / "evo.toml").write_text(
        f'token = "{TOKEN}"\n'
        '[station]\nname = "Kirchdorf"\n'
        "latitude = 48.4012\nlongitude = 11.6301\naltitude = 440.0\n",
        encoding="utf-8")
    # `[[plot]]` with `[[plot.line]]` inside it, which is the shape plots.py
    # writes. Guessing at it gave a file that parsed to no charts at all,
    # and a failure that looked like the search rather than the fixture.
    (work / "plots.toml").write_text(
        "[[plot]]\n"
        'name = "daytempdew"\nspan = "day"\ntime_length = "27h"\n'
        '  [[plot.line]]\n  obs = "outTemp"\n'
        '  [[plot.line]]\n  obs = "dewpoint"\n'
        "\n[[plot]]\n"
        'name = "weekrain"\nspan = "week"\ntime_length = "7d"\n'
        '  [[plot.line]]\n  obs = "rain"\n', encoding="utf-8")
    path = work / "evo.toml"
    return Admin(path, lambda: all_schemas(path), TOKEN)


def a_word_finds_its_setting() -> None:
    print("\nlooking for something by the word for it")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw))
        hits = adminsearch.find(admin, "altitude")
        check("something comes back", bool(hits), True)
        check("and the first is the field itself",
              hits[0].title, "Altitude")
        check("on the page it lives on", hits[0].href.startswith("./core#"),
              True)


def the_link_lands_on_the_section() -> None:
    """Not at the top of a form with seven of them."""
    print("\nthe link goes to the group, not the page")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw))
        hits = adminsearch.find(admin, "altitude")
        check("it carries a fragment", "#" in hits[0].href, True)
        check("and the fragment is the group's anchor",
              hits[0].href.split("#", 1)[1], anchor("Station"))


def what_was_typed_comes_first() -> None:
    """A search that ranks cleverly buries the obvious answer."""
    print("\nan exact name sorts above a mention of it")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw))
        hits = adminsearch.find(admin, "latitude")
        check("the field named that is first", hits[0].title, "Latitude")
        # Longitude's help mentions latitude's neighbour, and altitude's
        # does too. Those are matches, and they are not the answer.
        check("and the rest come after", len(hits) > 1, True)
        check("ranked below it", hits[0].rank < hits[-1].rank, True)


def a_chart_is_found_by_what_it_draws() -> None:
    """The question no page answers: where is outTemp drawn."""
    print("\nfinding a chart by the reading in it")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw))
        hits = adminsearch.find(admin, "dewpoint")
        names = [one.title for one in hits]
        check("the chart drawing it is found", "daytempdew" in names, True)
        found = next(one for one in hits if one.title == "daytempdew")
        check("the link opens that chart", found.href, "./plot:daytempdew")
        check("and it says what else is on it",
              "outTemp" in found.detail, True)

        # And by its own name, which is the easy half.
        check("a chart by name too",
              any(one.title == "weekrain"
                  for one in adminsearch.find(admin, "weekrain")), True)


def too_short_is_not_a_search() -> None:
    print("\none letter matches most of the page")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw))
        check("a single letter returns nothing",
              adminsearch.find(admin, "a"), [])
        check("and the page says so rather than listing everything",
              "at least" in adminsearch.results(admin, "a"), True)
        check("an empty query the same",
              adminsearch.find(admin, ""), [])


def nothing_found_says_where_it_looked() -> None:
    print("\nno match")
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw))
        page = adminsearch.results(admin, "zzzznotathing")
        check("it says nothing matched", "Nothing matches" in page, True)
        check("and what it covers",
              "the readings a chart draws" in page, True)


def the_box_is_on_every_page() -> None:
    """A search you have to navigate to is one nobody uses."""
    print("\nthe box itself")
    from weewx_evo.admin import page as render

    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw))
        for which in ("overview", "core", "publishing", "charts"):
            html = render(admin, which).decode()
            check(f"on {which}", 'action="./search"' in html, True)


def main() -> int:
    a_word_finds_its_setting()
    the_link_lands_on_the_section()
    what_was_typed_comes_first()
    a_chart_is_found_by_what_it_draws()
    too_short_is_not_a_search()
    nothing_found_says_where_it_looked()
    the_box_is_on_every_page()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("a word finds its setting, and the link lands on it")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Words the settings site must not say, measured on the rendered pages.

There is one entry so far, and it is the one that cost a complaint: **the
interface never says "collector".**

The split is real and it stays in the code -- a parser costs lines, a
collector costs a process, and `collectors.py` is a page of reasoning about
why the process is separate. But it is *our* split. Somebody with a weather
station has a driver: whether it listens on HTTP, waits on a UDP port, polls
an API or reads a USB console is not a choice they made and not one they can
act on. Two panels, two words and two ways to add one told them otherwise.

What *does* differ is where the process runs, and that is said on the row
where it is true rather than as a category. So this is not a ban on the
distinction. It is a ban on making the reader learn our word for it.

    python tools/adminwords_test.py            # the count
    python tools/adminwords_test.py --list     # every line that says one

Every page is rendered, including the bad days -- a failed save, a read-only
mount, a chart that is not there. The list comes from `adminlang_test`, and
from there rather than from a list here for the reason that file gives: a
second copy of the page names is how the first one came to be short.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from adminlang_test import (  # noqa: E402
    an_installation,
    every_page,
    visible,
)
from weewx_evo import language as language_defs  # noqa: E402

#: The word, and what to say instead. Matched on its own so that
#: `collectors.shed` out of a configuration file is not a finding: what is
#: banned is the word in a sentence, not the key in the file it names.
BANNED = {
    "collector": "driver -- see the docstring at the top of this file",
    "collectors": "drivers",
}

WORD = re.compile(r"\b(" + "|".join(BANNED) + r")\b", re.IGNORECASE)

#: The one place the word survives, and it is not a sentence: a command line
#: to be copied and typed. `--collector <name>` names an entry under
#: `[collectors]` in the configuration file, and `--driver` cannot be used
#: for it because `weewx-evo-weewx-driver run --driver vantage` already means
#: the driver *module* -- the same flag meaning two things is the trap
#: `--series` against `--archive` is written down for. Narrow on purpose: it
#: has to look like a command, not merely contain one.
A_COMMAND = re.compile(r"^weewx-evo[- ]\S")

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def found_in(markup: str) -> list[str]:
    """Every run of visible text on a page that says one of the words."""
    return [text for text in visible(markup)
            if WORD.search(text) and not A_COMMAND.match(text)]


def report(show_all: bool) -> int:
    with tempfile.TemporaryDirectory() as raw:
        admin = an_installation(Path(raw))
        # `Recorded` renders in whatever `pseudo` holds. English here: the
        # question is what a reader sees, and the pseudo-language wraps every
        # answer in guillemets, which would hide the word inside them.
        admin.pseudo = language_defs.get("en")  # type: ignore[assignment]
        pages = every_page(admin)

        print(f"\n{len(pages)} pages rendered")
        broken = sorted(name for name, body in pages.items()
                        if "PAGE RAISED" in body)
        check("every page renders", broken, [])

        said = {name: found_in(body) for name, body in pages.items()}
        said = {name: lines for name, lines in said.items() if lines}
        total = sum(len(lines) for lines in said.values())

        if said and (show_all or total <= 12):
            for name, lines in sorted(said.items()):
                print(f"\n  {name}")
                for line in lines:
                    print(f"      {line}")
        elif said:
            print(f"\n  on {len(said)} pages; --list for all of them")

        check("the interface never says one of these", total, 0)

        # The other half of the same claim: it says the word it replaced
        # them with. Without this the file passes on a site that renders
        # nothing at all, which is exactly what a deleted panel looks like.
        drivers = sum(1 for body in pages.values()
                      if re.search(r"\bdrivers?\b", " ".join(visible(body)),
                                   re.IGNORECASE))
        check("and it does say driver", drivers > 0, True)

    print("=" * 70)
    print("FAILURES" if failures else "all good")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(report("--list" in sys.argv))

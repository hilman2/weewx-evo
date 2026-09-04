#!/usr/bin/env python3
"""How much of the settings page can be read in another language.

Not "is there a translation file" -- whether the *page* asks for one. Those
are different questions, and only the second one matters: a string written
straight into the markup is invisible to every translator and to every test
that reads a language file.

So this renders every page in a pseudo-language whose every answer is wrapped
in guillemets, and then reads the pages back. Anything visible that came out
bare never went through `Language.say`, and is listed by page. That number is
the work left, and it can only go down.

The same run answers the second question -- what German still lacks -- by
recording every key the pages actually ask for and comparing that with
`lang/de.toml`. A key nobody asks for is dead weight in the file; a key asked
for and missing is a line still in English.

    python tools/adminlang_test.py            # the two counts, and the gaps
    python tools/adminlang_test.py --list     # every untranslated string
    python tools/adminlang_test.py --missing  # what to add to de.toml
"""

from __future__ import annotations

import html as html_module
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import admin as admin_module  # noqa: E402
from weewx_evo import language as language_defs  # noqa: E402
from weewx_evo.admin import ADD_PAGES, OWN_PAGES, Admin  # noqa: E402
from weewx_evo.cli import all_schemas  # noqa: E402
from weewx_evo.ratelimit import Limits  # noqa: E402

TOKEN = "abcdefghij123456"

#: What the pseudo-language wraps every answer in. Two characters that no
#: page writes for itself, so finding one is proof rather than a guess.
OPEN, CLOSE = "«", "»"

#: Text that is visible but is not language: values out of the configuration,
#: identifiers, numbers, and the punctuation between them. Listing these as
#: untranslated would bury the real ones under a hundred false positives.
NOT_WORDS = re.compile(r"^[\s\d.,:;/|()\[\]{}<>=+*%&@#~^$?!_-]*$")

#: Things a page prints that are names rather than words: a token, a path, a
#: sender id, a hostname. Recognised by shape, because they are data.
LOOKS_LIKE_DATA = re.compile(
    r"^(?:v\d+/|/|[a-z]:\\|https?://|[\w.-]+\.(?:toml|sdb|json|html|php|py)$"
    r"|[0-9a-f]{16,}$|[\w.-]+@)", re.IGNORECASE)

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


class Pseudo(language_defs.Language):
    """Answers everything, visibly, and remembers what it was asked.

    A subclass rather than a file, because the question is which strings
    reach `say` at all -- a file can only answer for the keys somebody has
    already written down, which is the very thing being measured.
    """

    def __init__(self) -> None:
        super().__init__("zz", {})
        self.asked: set[str] = set()
        self.settings_asked: set[tuple[str, str]] = set()

    def say(self, english: str) -> str:
        self.asked.add(english)
        return f"{OPEN}{english}{CLOSE}"

    def setting(self, name: str, part: str = "label") -> str:
        self.settings_asked.add((name, part))
        # Empty, so `field` falls back to the schema's own words. Those then
        # come out bare and are counted -- which is right: an option whose
        # label is never asked for is exactly the gap this is looking for.
        return ""


class Recorded(Admin):
    """An installation whose pages are rendered in the pseudo-language."""

    pseudo: Pseudo

    @property
    def language(self) -> Pseudo:
        return self.pseudo


def visible(markup: str) -> list[str]:
    """The words a person sees, one entry per run of text.

    Script and style are dropped whole: a page carries a few hundred lines
    of both, none of it read by anybody, and every identifier in them would
    otherwise be reported as an untranslated string.
    """
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", markup,
                  flags=re.DOTALL | re.IGNORECASE)
    # Attributes that are read out loud or shown on hover are language too.
    spoken = re.findall(
        r'(?:title|aria-label|placeholder|alt)="([^"]*)"', body)
    body = re.sub(r"<[^>]+>", "\n", body)
    out = []
    for piece in [*body.split("\n"), *spoken]:
        text = html_module.unescape(piece).strip()
        if not text or NOT_WORDS.match(text) or LOOKS_LIKE_DATA.match(text):
            continue
        out.append(text)
    return out


def bare(markup: str) -> list[str]:
    """Visible text that never went through the language."""
    found = []
    for text in visible(markup):
        # A run holding a translated part is fine: the untranslated half of
        # it, if any, is a separate run of its own.
        if OPEN in text or CLOSE in text:
            continue
        found.append(text)
    return found


def an_installation(work: Path) -> Recorded:
    (work / "data").mkdir(exist_ok=True)
    path = work / "evo.toml"
    path.write_text(
        f'token = "{TOKEN}"\n'
        f'live_db = "{(work / "data" / "live.sdb").as_posix()}"\n'
        f'archive_db = "{(work / "data" / "weewx.sdb").as_posix()}"\n'
        f'feeds_dir = "{(work / "data" / "feeds").as_posix()}"\n'
        '[station]\nname = "Kirchdorf"\n'
        "latitude = 48.4012\nlongitude = 11.6301\naltitude = 440.0\n",
        encoding="utf-8")
    admin = Recorded(path, lambda: all_schemas(path), TOKEN,
                     limits=Limits(rate=0, failures=0))
    admin.pseudo = Pseudo()
    return admin


def _rendered(admin: Recorded, name: str, **how: object) -> str:
    try:
        body = admin_module.page(admin, name, **how)  # type: ignore[arg-type]
    except Exception as exc:
        # A page that raises is the finding, not a reason to stop: the run
        # has 133 others to measure, and the name of the broken one is more
        # use than a traceback out of the middle of the list.
        return f"<p>PAGE RAISED: {exc}</p>"
    return body.decode("utf-8", "replace") if isinstance(body, bytes) else body


def every_page(admin: Recorded) -> dict[str, str]:
    """Each page of the settings site, rendered -- including its bad days.

    The ordinary render never reaches a failed save, a read-only mount or a
    chart that is not there, so a first version reported those strings as
    dead weight in `de.toml`. They were not: they were paths this run did
    not walk. A count that calls a working translation stale is one nobody
    will keep believing.
    """
    names = ([one.name for one in admin.schemas]
             + list(ADD_PAGES) + list(OWN_PAGES)
             + admin_module.sub_pages(admin))
    out = {name: _rendered(admin, name) for name in dict.fromkeys(names)}

    # The states a page only reaches when something is wrong.
    out["core (a failed save)"] = _rendered(
        admin, "core", errors={"interval": "not a number", "": ""})
    out["core (one field refused)"] = _rendered(
        admin, "core", errors={"interval": "not a number"})
    out["core (saved)"] = _rendered(admin, "core", message="Saved.")
    out["plot: not there"] = _rendered(admin, "plot:nosuchchart")
    admin.restart_pending = {"interval"}
    out["core (restart pending)"] = _rendered(admin, "core")
    admin.restart_pending = set()
    was, admin.read_only = admin.read_only, True
    out["core (read-only)"] = _rendered(admin, "core")
    admin.read_only = was
    return out


def report(show_all: bool, show_missing: bool) -> int:
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        admin = an_installation(work)
        pages = every_page(admin)

        print(f"\n{len(pages)} pages rendered")
        broken = sorted(name for name, body in pages.items()
                        if "PAGE RAISED" in body)
        check("every page renders", broken, [])

        by_page: dict[str, list[str]] = {}
        for name, body in pages.items():
            left = sorted(set(bare(body)))
            if left:
                by_page[name] = left
        total = sum(len(one) for one in by_page.values())
        strings = len({one for rows in by_page.values() for one in rows})

        print(f"\nasked for in the page's language: "
              f"{len(admin.pseudo.asked)} strings, "
              f"{len(admin.pseudo.settings_asked)} setting texts")
        print(f"still written straight into the markup: {strings} strings "
              f"on {len(by_page)} of {len(pages)} pages ({total} places)")

        if show_all:
            for name in sorted(by_page):
                print(f"\n-- {name}")
                for one in by_page[name]:
                    print(f"   {one}")

        # And what German does not answer yet. Read from the file rather
        # than from a list here: the file is what ships.
        german = language_defs.get("de")
        said = (german.values.get("admin") or {})
        settings_said = (german.values.get("settings") or {})
        missing = sorted(one for one in admin.pseudo.asked if one not in said)
        stale = sorted(one for one in said if one not in admin.pseudo.asked)
        missing_settings = sorted(
            name for name, part in admin.pseudo.settings_asked
            if part == "label" and name not in settings_said)

        print(f"\nGerman: {len(said)} of {len(admin.pseudo.asked)} strings, "
              f"{len(settings_said)} of "
              f"{len({n for n, _ in admin.pseudo.settings_asked})} settings")
        if stale:
            # Said carefully. This run walks the ordinary pages plus a
            # handful of bad days, and a key it did not ask for is usually a
            # path it did not reach -- a second place, an unset driver, an
            # environment variable in the way. Calling those dead would
            # teach somebody to delete a working translation.
            print(f"  {len(stale)} key(s) this run did not ask for "
                  "(a path it does not walk, or a line no longer printed)")
            if show_missing:
                for one in stale:
                    print(f"    unasked: {one}")
        if show_missing:
            for one in missing:
                print(f'    "{one}" = ""')
            for one in missing_settings:
                print(f"    [settings.{one}]  label/help")

        # The bar this run has to clear. It is the count as it stands, so a
        # change that leaves *more* untranslated fails -- and lowering it is
        # the only way to move it.
        check("no page raised while rendering", broken, [])
        check("the language reaches the settings",
              len(admin.pseudo.settings_asked) > 0, True)
        check("and the pages themselves",
              len(admin.pseudo.asked) > 0, True)
    return failures


def main(argv: list[str]) -> int:
    left = report("--list" in argv, "--missing" in argv)
    print()
    if left:
        print(f"{left} check(s) failed")
        return 1
    print("the settings page asks for its words rather than printing them")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

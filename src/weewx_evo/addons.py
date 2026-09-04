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

**The command line may install anything, and should.** Who publishes an
add-on is not ours to decide -- the catalogue says what *we* offer, not what
anybody is allowed to run. So `weewx-evo addon install --unlisted <spec>`
takes whatever pip takes, and the difference from the page is not a judgement
about the package: it is that a person on the machine typed it, and a form
field is not a person.

The flag is required rather than inferred from "not in the catalogue",
because inferring it would turn a mistyped catalogue name into an install of
whatever happens to have that name on PyPI.

## A new add-on needs a restart

Entry points are read once per process. Nothing here restarts anything -- the
same rule the setup wizard has, and for the same reason: how the service is
supervised is the operator's business. What this does is *say* so, because an
add-on installed and apparently doing nothing is the confusing state.
"""

from __future__ import annotations

import logging
import os
import shutil
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


#: Where an add-on installed here goes, under the data directory.
#:
#: Not site-packages, and that is the whole of what makes this work in a
#: container: site-packages is in the image, so an add-on installed there is
#: gone at the next `docker compose up` -- with the console still uploading
#: and nothing reading it, which is the worst way to find out. The data
#: directory is a volume on every deployment this ships, so what is installed
#: outlives the container that installed it.
#:
#: Beside `drivers/` and `weewx-drivers/`, which are there for the same
#: reason and were there first.
DIRECTORY = "addons"

#: Set to the directory this process has already put on `sys.path`, so that
#: repeated calls are free and a second one cannot add it twice.
_on_path: Path | None = None

#: What a container installs at build time, for a deployment that wants its
#: add-ons pinned in a file rather than clicked. Both work and neither is
#: required: this one is reproducible, the page is immediate, and an add-on
#: installed either way is found the same way.
BUILD_LIST = "deploy/addons.txt"

#: Where everything the catalogue lists lives, and the condition for being
#: listed at all. The page installs with one click and no further question,
#: and the only honest answer to "who stands behind that" is whoever can
#: write to the repository it came from.
#:
#: Not a rule about what may be run. `install_unlisted` takes anything.
ORGANISATION = "https://github.com/weewx-evo/"


def directory(archive: str | os.PathLike | None = None) -> Path:
    """Where add-ons installed from here live.

    `WEEWX_EVO_ADDON_DIR` first, because a container may want it somewhere
    else entirely; then beside the archive, which is where the data
    directory is.
    """
    from_env = os.environ.get("WEEWX_EVO_ADDON_DIR")
    if from_env:
        return Path(from_env).expanduser()
    if archive:
        return Path(archive).expanduser().parent / DIRECTORY
    return _data_directory() / DIRECTORY


def _data_directory() -> Path:
    """The data directory, from the running settings or as a guess."""
    from . import settings as settings_state

    running = settings_state.running()
    if running is not None:
        try:
            archive = running.get("archive_db")
            if archive:
                return Path(str(archive)).expanduser().parent
        except Exception:
            log.debug("could not read archive_db for the add-on directory",
                      exc_info=True)
    return Path("data")


def on_path(archive: str | os.PathLike | None = None) -> Path | None:
    """Put the add-on directory on `sys.path`. Returns it, or None.

    Called before the entry points are walked, which is the only moment it
    matters: `importlib.metadata` finds a distribution by looking along
    `sys.path` for its `.dist-info`, so an add-on installed into a directory
    nothing has added is installed and invisible.

    Idempotent, and it has to be: `Registry.load()` is called from several
    entry points and a path added twice is a path searched twice for every
    import for the life of the process.
    """
    global _on_path

    where = directory(archive)
    if _on_path == where:
        return where
    if not where.is_dir():
        return None
    text = str(where.resolve())
    if text not in sys.path:
        # Appended, not prepended: an add-on must not be able to shadow the
        # core's own modules by being installed under one of their names.
        sys.path.append(text)
    _on_path = where
    return where


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
    if not one.repository.startswith(ORGANISATION):
        # Everything the catalogue lists is in the organisation -- that is the
        # condition for being merged into it, because this is the route with
        # one click and no further question. A catalogue served from somewhere
        # it should not be cannot turn that click into an install of anything
        # else, and this is the line that makes that true rather than assumed.
        #
        # It is not a rule about what may be run: `install_unlisted` takes
        # whatever pip takes.
        return (f"{package!r} is in the list but does not live in the "
                f"weewx-evo organisation. Install it with "
                f"`weewx-evo addon install --unlisted` if you want it.")

    into = directory()
    try:
        into.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"could not make {into}: {exc}"

    # `--target` rather than site-packages, so it survives the container it
    # was installed from. `--upgrade` because pip refuses to overwrite a
    # directory that is already there, and reinstalling is what somebody
    # does when an add-on is broken.
    #
    # `--no-deps` because these depend on `weewx-evo`, which is the running
    # program rather than something to fetch. What they need of each other is
    # in the catalogue as its own entry -- push-common is listed and can be
    # installed on its own.
    command = [sys.executable, "-m", "pip", "install", "--upgrade",
               "--no-deps", "--target", str(into),
               f"{one.name} @ {archive_url(one)}"]
    problem = _run(command, runner, f"could not install {one.name}")
    if problem:
        return problem
    on_path()

    # What it needs and did not get, because `--no-deps` was passed. Fetched
    # here rather than left to pip, and the difference is the fence: pip
    # would resolve whatever a package asked for, from wherever it asked,
    # which is a way round the rule that what may be installed is what the
    # catalogue lists. So each dependency is looked up in the catalogue too,
    # and one that is not there is named rather than fetched.
    for name in _needs(one.name):
        if name in installed():
            continue
        if name not in listed:
            return (f"Installed, but it needs {name}, which is not in the "
                    f"add-on list. Install that by hand.")
        problem = install(name, where, runner)
        if problem:
            return f"Installed {one.name}, but {problem}"
    return ""


def install_unlisted(spec: str, where: Path | None = None,
                     runner: object = None) -> str:
    """Install anything pip takes. For the command line only.

    Who publishes an add-on is not ours to decide. The catalogue is what this
    installation *offers*, and offering is not permitting -- so a person on
    the machine can install a package from anywhere, and the settings page
    cannot, because a form field is not a person.

    `--no-deps` here too, and it costs something: a package that really needs
    another gets neither, and is told so rather than half-installed. The
    reason is the same as everywhere else here -- these depend on
    `weewx-evo`, which is the running program and not something pip can
    fetch, so a resolver would fail on every one of them.
    """
    spec = spec.strip()
    if not spec:
        return "Nothing to install."
    into = where or directory()
    try:
        into.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"could not make {into}: {exc}"

    before = set(installed())
    command = [sys.executable, "-m", "pip", "install", "--upgrade",
               "--no-deps", "--target", str(into), spec]
    problem = _run(command, runner, f"could not install {spec}")
    if problem:
        return problem
    on_path()

    # What arrived, rather than what was asked for: a spec can be a URL, a
    # path or a name with a version on it, and none of those is the package
    # name. The one thing that answers reliably is looking at what is there
    # now that was not there before.
    arrived = sorted(set(installed()) - before)
    if arrived:
        log.info("installed %s from %r", ", ".join(arrived), spec)
    return ""


def archive_url(one: object) -> str:
    """Where to fetch this add-on from, as something pip can take without git.

    A tarball rather than `git+https://`, and the reason is a station rather
    than a preference: `git+` makes pip shell out to git, and git is a build
    tool that has no business in a container that runs a weather station for
    years. Installing one add-on from the settings page then failed with
    "Cannot find command 'git'" -- on an image that was right to not have it.

    GitHub serves `/archive/<ref>.tar.gz` for a branch, a tag or a commit, so
    a catalogue entry can pin one by saying `ref`. Without one it is the
    default branch, which is what "install the current version" means.
    """
    ref = str(getattr(one, "ref", "") or "main")
    return f"{one.repository.rstrip('/')}/archive/{ref}.tar.gz"


def _needs(package: str) -> list[str]:
    """Which weewx-evo packages this one declares a dependency on.

    Only ours. Nothing in the catalogue depends on anything outside the
    standard library, which is the property that makes `--no-deps` safe: what
    is left to resolve is a short list of names this program already knows
    how to check.
    """
    wanted = []
    try:
        from importlib.metadata import distribution

        for raw in distribution(package).requires or ():
            if ";" in raw and "extra" in raw.split(";", 1)[1]:
                # An optional extra. Nobody asked for it.
                continue
            name = raw.split(";")[0].split("[")[0]
            for stop in ("<", ">", "=", "!", "~", " ", "("):
                name = name.split(stop)[0]
            name = name.strip()
            if name.startswith("weewx-evo-") and name != package:
                wanted.append(name)
    except Exception:
        log.debug("could not read what %r requires", package, exc_info=True)
    return wanted


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
    # The directory decides, not the registry. What can be taken away is what
    # is on disk here -- and this process may have been started before the
    # add-on was installed, in which case the entry points it read do not
    # have it and never will until it restarts.
    #
    # `pip uninstall` cannot undo a `--target` install: it knows nothing about
    # a directory it was told to write into once. So the files are removed
    # here, and from the record pip itself wrote -- `RECORD` in the
    # `.dist-info` lists every file that was put there, which is exactly the
    # question being asked and the only answer that cannot be a guess.
    where = directory(None)
    marker = _dist_info(where, package)
    if marker is None:
        if package in installed():
            return (f"{package!r} came with this installation rather than "
                    f"being installed here. In a container, take it out of "
                    f"deploy/addons.txt and rebuild.")
        return f"{package!r} is not installed here."
    try:
        _delete_recorded(where, marker)
    except OSError as exc:
        return f"could not remove {package}: {exc}"
    return ""


def _dist_info(where: Path, package: str) -> Path | None:
    """The `.dist-info` for this package under `where`, or None."""
    if not where.is_dir():
        return None
    # Distribution names are normalised in a directory name: `-` becomes `_`,
    # and case is folded. Comparing the raw name would miss every package
    # whose name has a dash in it, which is all of ours.
    wanted = package.replace("-", "_").lower()
    for entry in where.glob("*.dist-info"):
        if entry.name.split("-")[0].replace("-", "_").lower() == wanted:
            return entry
    return None


def _delete_recorded(where: Path, marker: Path) -> None:
    """Remove everything pip recorded for this distribution, then the record.

    Paths outside `where` are skipped rather than followed: a RECORD is a
    file in a directory this program writes to, and one that names
    `../../something` is either broken or malicious. Neither is a reason to
    delete anything.
    """
    record = marker / "RECORD"
    lines = (record.read_text(encoding="utf-8").splitlines()
             if record.exists() else [])
    root = where.resolve()
    directories: set[Path] = set()
    for line in lines:
        named = line.split(",")[0].strip()
        if not named:
            continue
        target = (where / named).resolve()
        if root not in target.parents and target != root:
            log.warning("%s records a path outside %s; leaving it alone",
                        marker.name, where)
            continue
        try:
            target.unlink()
        except IsADirectoryError:
            shutil.rmtree(target, ignore_errors=True)
        except FileNotFoundError:
            pass
        directories.add(target.parent)

    shutil.rmtree(marker, ignore_errors=True)
    # Empty directories, deepest first, so a package's own tree goes with it.
    for one in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        try:
            if one != root and one.is_dir() and not any(one.iterdir()):
                one.rmdir()
        except OSError:
            pass


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

"""Drivers somebody else wrote.

Bundled drivers live in `plugins/` and are ours. These are not: they are
installed by the person running the station, from a repository or a zip, and
they live outside the package so that upgrading weewx-evo cannot touch them --
and so that nothing installed here can be mistaken for something we maintain.

    weewx-evo driver install https://github.com/someone/weewx-evo-acurite
    weewx-evo driver install ./my-driver.zip
    weewx-evo driver list
    weewx-evo driver remove acurite

Where they go, first that is set:

    --driver-dir on the command line
    WEEWX_EVO_DRIVER_DIR in the environment
    <the archive database's directory>/drivers

The last one puts them beside the data, which is the directory the service can
write to and the one people back up.

A driver is a directory containing a package with `load(registry)`, at the top
level or in `driver.py`. That is the whole contract -- the same one the bundled
drivers meet.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from importlib import import_module, invalidate_caches
from pathlib import Path

log = logging.getLogger(__name__)

ENV_VAR = "WEEWX_EVO_DRIVER_DIR"
#: A file we drop beside an installed driver, recording where it came from.
ORIGIN_FILE = ".origin"


def directory(configured: str | os.PathLike | None = None,
              archive: str | os.PathLike | None = None) -> Path:
    """Where user drivers live."""
    if configured:
        return Path(configured).expanduser()
    from_env = os.environ.get(ENV_VAR)
    if from_env:
        return Path(from_env).expanduser()
    if archive:
        return Path(archive).expanduser().parent / "drivers"
    return Path("data/drivers")


def installed(where: Path | None = None) -> list[tuple[str, str]]:
    """The drivers installed, as (name, where it came from)."""
    where = where or directory()
    if not where.is_dir():
        return []
    out = []
    for entry in sorted(where.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "__")):
            continue
        origin = entry / ORIGIN_FILE
        out.append((entry.name,
                    origin.read_text(encoding="utf-8").strip()
                    if origin.exists() else "unknown"))
    return out


def load(registry, where: Path | None = None) -> list[str]:
    """Register every installed user driver. Returns the names that loaded."""
    where = where or directory()
    if not where.is_dir():
        return []

    # Put the directory itself on the path, so each driver is an ordinary
    # top-level package. Nothing is added to weewx_evo's own namespace: a
    # third-party driver must not be able to shadow a bundled one.
    if str(where) not in sys.path:
        sys.path.insert(0, str(where))
        invalidate_caches()

    loaded = []
    for name, _origin in installed(where):
        try:
            entry = _entry_point(name)
            if entry is None:
                log.warning("user driver %r has no load(); skipping", name)
                continue
            if entry(registry):
                loaded.append(name)
                log.info("user driver %r from %s", name, where / name)
        except Exception:
            log.exception("user driver %r failed to load; carrying on without it",
                          name)
    return loaded


def _entry_point(name: str):
    module = import_module(name)
    entry = getattr(module, "load", None)
    if entry is not None:
        return entry
    module = import_module(f"{name}.driver")
    return getattr(module, "load", None)


# -- installing ----------------------------------------------------------

class InstallError(Exception):
    """Anything that stopped a driver being installed."""


def install(source: str, where: Path | None = None, name: str | None = None,
            force: bool = False) -> tuple[str, dict[str, list[str]]]:
    """Install a driver from a git URL, a zip, or a directory.

    Returns its name and what its code reaches for -- see `inspect_source`.

    Nothing is executed during installation and nothing is imported: a driver
    is code that will run as this service, so the decision to trust it is the
    operator's and is made before this is called, not by this.
    """
    where = where or directory()
    where.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        staged = _fetch(source, Path(tmp))
        package = _find_package(staged)
        if package is None:
            raise InstallError(
                f"no driver found in {source}. Expected a directory with an "
                "__init__.py and a load(registry), either at the top level or "
                "in driver.py.")
        notable = inspect_source(package)

        target_name = name or package.name
        if not target_name.isidentifier():
            raise InstallError(f"{target_name!r} is not a usable package name")
        target = where / target_name

        if target.exists():
            if not force:
                raise InstallError(
                    f"{target_name!r} is already installed in {where}. "
                    "Pass --force to replace it.")
            shutil.rmtree(target)

        shutil.copytree(package, target,
                        ignore=shutil.ignore_patterns("__pycache__", ".git", "tests"))
        (target / ORIGIN_FILE).write_text(source + "\n", encoding="utf-8")

    return target_name, notable


def remove(name: str, where: Path | None = None) -> bool:
    """Delete an installed driver. Returns False if it was not there."""
    where = where or directory()
    target = where / name
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def _fetch(source: str, tmp: Path) -> Path:
    """Get the source into a directory we can look at."""
    if source.startswith(("http://", "https://", "git@")) and not source.endswith(".zip"):
        return _clone(source, tmp / "checkout")
    if source.startswith(("http://", "https://")):
        return _unzip(_download(source, tmp / "download.zip"), tmp / "unpacked")

    path = Path(source).expanduser()
    if not path.exists():
        raise InstallError(f"{source} does not exist")
    if path.is_dir():
        return path
    if zipfile.is_zipfile(path):
        return _unzip(path, tmp / "unpacked")
    raise InstallError(f"{source} is neither a directory nor a zip")


def _clone(url: str, into: Path) -> Path:
    if shutil.which("git") is None:
        raise InstallError(
            "git is not installed, so a repository cannot be cloned. Download the "
            "zip and install that instead.")
    try:
        subprocess.run(["git", "clone", "--depth", "1", url, str(into)],
                       check=True, capture_output=True, text=True, timeout=120)
    except subprocess.CalledProcessError as exc:
        raise InstallError(f"git clone failed: {exc.stderr.strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise InstallError("git clone timed out") from exc
    return into


def _download(url: str, to: Path) -> Path:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            to.write_bytes(response.read())
    except Exception as exc:
        raise InstallError(f"could not download {url}: {exc}") from exc
    if not zipfile.is_zipfile(to):
        raise InstallError(f"{url} is not a zip")
    return to


def _unzip(archive: Path, into: Path) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            # A zip may name any path it likes, including ones outside the
            # directory it is being unpacked into.
            destination = (into / member).resolve()
            if not str(destination).startswith(str(into.resolve())):
                raise InstallError(f"{archive} tries to write outside its directory")
        zf.extractall(into)
    return into


def _find_package(root: Path) -> Path | None:
    """The driver package inside a checkout or unpacked zip.

    Looked for at the top level, one level down (a zip usually wraps everything
    in a directory named after the release), and under src/ or bin/user/.
    """
    candidates = [root]
    for extra in ("src", "bin", "bin/user"):
        candidates.append(root / extra)
    children = [c for c in root.iterdir() if c.is_dir()] if root.is_dir() else []
    candidates.extend(children)
    for child in children:
        candidates.extend(c for c in child.iterdir() if c.is_dir())

    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if _is_driver(candidate):
            return candidate
        for child in sorted(candidate.iterdir()):
            if child.is_dir() and _is_driver(child):
                return child
    return None


#: Imports worth mentioning before somebody trusts a driver. None of these is
#: forbidden or even unusual -- a driver may well need a socket. The point is
#: that the operator sees them before the code runs as their service, not
#: afterwards.
NOTABLE = {
    "sqlite3": "opens databases directly, bypassing the core",
    "subprocess": "runs other programs",
    "socket": "opens its own network connections",
    "urllib": "makes network requests",
    "requests": "makes network requests",
    "httpx": "makes network requests",
    "shutil": "moves and deletes files",
    "ctypes": "calls into native code",
    "pickle": "deserialises objects, which can execute code",
    "eval": "evaluates code built at runtime",
    "exec": "executes code built at runtime",
    "__import__": "imports by name at runtime",
}


def inspect_source(package: Path) -> dict[str, list[str]]:
    """What a driver's code reaches for, as {note: [files]}.

    Read, not run. This is a hint and not a guarantee: it will not see through
    obfuscation and it cannot judge intent. It catches the honest mistake and
    the lazy shortcut, which is most of what there is to catch.
    """
    found: dict[str, list[str]] = {}
    for source in sorted(package.rglob("*.py")):
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for needle, note in NOTABLE.items():
            if needle in ("eval", "exec", "__import__"):
                hit = f"{needle}(" in text
            else:
                hit = (f"import {needle}" in text or f"from {needle}" in text)
            if hit:
                found.setdefault(f"{needle}: {note}", []).append(
                    str(source.relative_to(package)))
    return found


def _is_driver(path: Path) -> bool:
    """Whether a directory looks like a driver package.

    Read, not imported. Importing to find out would run the code before the
    operator has decided to install it.
    """
    if path.name.startswith((".", "__")) or not (path / "__init__.py").exists():
        return False
    for source in (path / "__init__.py", path / "driver.py"):
        if source.exists() and "def load(" in source.read_text(
                encoding="utf-8", errors="replace"):
            return True
    return False

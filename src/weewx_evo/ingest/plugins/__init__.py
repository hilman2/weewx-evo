"""The drivers that ship with weewx-evo.

One directory per driver, each a package with a `load(registry)` that registers
what it provides. Nothing here is enumerated by hand: every subdirectory is
tried, so adding a driver means adding a directory.

These are *ours* -- in the repository, maintained centrally, released with the
core. That is a deliberate choice and not a contradiction of the plugin
architecture: a driver in here plugs in through exactly the same interface a
stranger's does, and could be moved out without the core noticing. The
argument for keeping the important ones close is about maintenance, not about
coupling.

Drivers somebody else wrote live elsewhere and are installed with
`weewx-evo driver install`. See weewx_evo.ingest.userdrivers.
"""

from __future__ import annotations

import logging
import pkgutil
from importlib import import_module
from pathlib import Path

log = logging.getLogger(__name__)


def bundled() -> list[str]:
    """The driver packages in this directory."""
    here = Path(__file__).parent
    return sorted(
        module.name for module in pkgutil.iter_modules([str(here)])
        if module.ispkg
    )


def load(registry) -> list[str]:
    """Register every bundled driver. Returns the names that loaded.

    A driver that will not import is reported and skipped. It must not take the
    listener down with it: the other protocols still have measurements arriving,
    and losing all of them over one broken package is by far the worse outcome.
    """
    from ..envelope import EnvelopeDriver

    # The envelope is the core's own contract rather than a driver, so it is
    # always present and a plugin cannot displace it.
    registry.register("json", EnvelopeDriver(), replace=True)

    loaded = []
    for name in bundled():
        try:
            module = import_module(f"{__name__}.{name}")
            entry = getattr(module, "load", None)
            if entry is None:
                # A package with no load() is a driver whose entry point is in
                # a submodule named driver.py, which is the usual layout.
                module = import_module(f"{__name__}.{name}.driver")
                entry = getattr(module, "load", None)
            if entry is None:
                log.warning("bundled driver %r has no load(); skipping", name)
                continue
            if entry(registry):
                loaded.append(name)
        except Exception:
            log.exception("bundled driver %r failed to load; carrying on without it",
                          name)

    from .. import userdrivers
    loaded.extend(userdrivers.load(registry))
    return loaded

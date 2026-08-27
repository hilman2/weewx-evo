"""The skins weewx-evo ships.

One directory per skin, beside the code, the way drivers sit under
`ingest/plugins/`. A station that installs weewx-evo has them without
downloading anything, and `skins_dir` is for the ones that came from
somewhere else.

What is here is not ours in the sense that matters: `deck` is a fork of
weewx-wdc by David Baetge, GPL v3, and its own README says so.
"""

from __future__ import annotations

from pathlib import Path

#: Where they are. Beside this module, so an installation carries them
#: however it was installed -- from a checkout, a wheel or a container.
HERE = Path(__file__).resolve().parent


def bundled() -> dict[str, Path]:
    """The skins that ship, by name."""
    if not HERE.is_dir():
        return {}
    return {entry.name: entry for entry in sorted(HERE.iterdir())
            if (entry / "skin.conf").is_file()}

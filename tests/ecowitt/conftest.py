#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Make the driver importable, and hand the captured payloads to the tests.

The tests came across from weewx-ecowitt unchanged and import the driver as
`ecowitt`, which is what it is called in a WeeWX installation. Here it lives at
`weewx_evo.ingest.plugins.ecowitt`, so that name is aliased rather than the
tests being rewritten: they should keep matching the ones upstream, so a fix
made in either place is a fix that can be moved to the other.
"""

import os.path
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from weewx_evo.ingest.plugins import ecowitt as _ecowitt  # noqa: E402

sys.modules.setdefault("ecowitt", _ecowitt)
for _name in ("catalog", "columns", "driver", "infer",
              "mapping", "protocol", "report"):
    __import__(f"weewx_evo.ingest.plugins.ecowitt.{_name}")
    sys.modules.setdefault(f"ecowitt.{_name}",
                           sys.modules[f"weewx_evo.ingest.plugins.ecowitt.{_name}"])


@pytest.fixture
def payload():
    """Return a captured payload by name, e.g. payload('hp2561ae_pro')."""

    def _load(name):
        with open(os.path.join(HERE, "fixtures", name + ".txt"), encoding="utf-8") as fd:
            return fd.read().strip()

    return _load

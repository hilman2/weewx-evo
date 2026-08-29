#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Make the protocols importable, and hand the captured payloads to the tests.

These came across from weewx-ultimate-push with the code they test. There they
import the package as `ultimatepush`, because that is what it is called in a
WeeWX installation; here it lives at `weewx_evo.ingest.plugins.push`, so the
name is aliased rather than the tests rewritten.

That is the same arrangement `tests/ecowitt` had, and for the same reason:
`protocols/` and `catalogs/` import nothing, so a fix belongs in both repos
and should not have to be translated on the way.

Only the tests that need no WeeWX came over. The ones about columns, the
console list and the web interface test parts this program does differently --
the archive, `stations.toml`, and its own settings page -- and there is nothing
to be gained by keeping a second answer to those questions passing here.
"""

import os.path
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
if HERE not in sys.path:
    # So a test can import tests/push/helpers.py by name.
    sys.path.insert(0, HERE)

from weewx_evo.ingest.plugins import push as _push  # noqa: E402

if "ultimatepush" not in sys.modules:
    sys.modules["ultimatepush"] = _push
    # The upstream tests import `from ultimatepush import mapping` and
    # `from ultimatepush.protocols import ecowitt`. Registering the package
    # is not enough for the submodules: they have to be imported under the
    # alias too, or the first `from ultimatepush.x import y` looks for a
    # top-level `ultimatepush` on disk and does not find one.
    for _name in ("transport", "mapping", "infer", "report", "roles",
                  "protocols", "catalogs"):
        _module = __import__(f"weewx_evo.ingest.plugins.push.{_name}",
                             fromlist=[_name])
        sys.modules[f"ultimatepush.{_name}"] = _module
    for _name in ("acurite", "ambient", "ecowitt", "lacrosse", "weatherflow",
                  "wunderground"):
        for _package in ("protocols", "catalogs"):
            _module = __import__(
                f"weewx_evo.ingest.plugins.push.{_package}.{_name}",
                fromlist=[_name])
            sys.modules[f"ultimatepush.{_package}.{_name}"] = _module

# A `user` package, because upstream the modules live under it.
if "user" not in sys.modules:
    _user = types.ModuleType("user")
    _user.__path__ = []
    _user.ultimatepush = _push
    sys.modules["user"] = _user
    sys.modules["user.ultimatepush"] = _push


FIXTURES = os.path.join(HERE, "fixtures")


@pytest.fixture
def fixtures():
    """Where the captured payloads are."""
    return FIXTURES


@pytest.fixture
def payload():
    """A captured payload by name: 'hp2561ae_pro', or 'wunderground/metric'.

    The `.txt` is added here rather than written at every call site, which is
    how it is upstream.
    """
    def read(name):
        path = os.path.join(FIXTURES, *name.split("/")) + ".txt"
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    return read

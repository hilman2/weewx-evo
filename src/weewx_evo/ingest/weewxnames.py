"""Make `import weewx` work for a driver, with no WeeWX installed.

`weewxshim.py` runs a WeeWX driver unchanged. Until now that meant WeeWX had
to be on the disk, because the driver file says `import weewx` at the top --
so a station whose only reason to want WeeWX was one USB console had to
install the whole of it.

Measured across WeeWX's fourteen own drivers, that import is almost entirely
ceremony. What they actually reach for:

    weewx.drivers          13   the base classes, which a shim does not use
    weewx.WeeWxIOError     12   an exception, three lines
    weewx.wxformulas       11   one function of it, twelve lines
    weeutil.weeutil        10   to_bool, to_int, timestamp_to_string
    weeutil.logger         10   setup() and log_traceback()
    weewx.debug             9   the integer 0
    weewx.RetriesExceeded   8   another exception
    weewx.METRIC / US       7   the numbers 16 and 1, which are ours as well

fousb is the lightest of the fourteen: four names. So the whole of it comes
to this file, and the driver runs against it exactly as it does against the
real thing.

**Where WeeWX is installed, WeeWX wins.** Same rule as pyephem in `sun.py`:
somebody who has the real one gets the real one's behaviour, down to the
edges nobody has thought to write down. This fills in what is missing rather
than replacing what is there -- `install()` on a process that already has
WeeWX does nothing at all.

**And it never overwrites another stand-in.** `skinkit.py` puts modules under
these same names so that a WeeWX *skin* renders, and `sys.modules` is one
table for the process. Whichever ran second would silently take the other's
`weewx.units` away. So each name is claimed only if free, and what is already
there is left alone: two stand-ins for different halves of the same program
can share a process without either of them noticing.

What this is not: an implementation of WeeWX. A driver that wants
`weewx.engine`, `weewx.manager` or a real `weewx.units` gets an error naming
what it wanted, which is the thing to add -- not a polite answer that turns
into a wrong reading three layers down. Same reason `ShimEngine` has no
`__getattr__`.
"""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

log = logging.getLogger(__name__)

#: WeeWX's unit-system constants. Ours are the same numbers -- they are
#: WeeWX's, written into every archive ever made, which is the one rule.
US = 0x01
METRIC = 0x10
METRICWX = 0x11

#: The names this file can claim. Also what `describe()` reports on.
NAMES = ("weewx", "weewx.drivers", "weewx.wxformulas",
         "weeutil", "weeutil.weeutil", "weeutil.logger")


def installed() -> bool:
    """Is the real WeeWX importable? Then nothing here is needed."""
    import importlib.util

    if "weewx" in sys.modules:
        # Already imported, by us or by anybody. A stand-in has no file.
        return getattr(sys.modules["weewx"], "__file__", None) is not None
    try:
        return importlib.util.find_spec("weewx") is not None
    except (ImportError, ValueError):
        # A half-installed package, or one whose parent cannot be imported.
        # Either way there is nothing to find.
        return False


# -- the pieces ---------------------------------------------------------


def _weewx_module() -> types.ModuleType:
    weewx = types.ModuleType("weewx")
    # A package, so `import weewx.drivers` can work at all.
    weewx.__path__ = []  # type: ignore[attr-defined]
    weewx.__version__ = "5.1.0"
    weewx.debug = 0
    weewx.US, weewx.METRIC, weewx.METRICWX = US, METRIC, METRICWX

    class WeeWxIOError(IOError):
        """The console did not answer, or answered nonsense."""

    class WakeupError(WeeWxIOError):
        """It would not wake up."""

    class CRCError(WeeWxIOError):
        """It answered, and the answer did not check out."""

    class RetriesExceeded(WeeWxIOError):
        """It kept not answering."""

    class HardwareError(Exception):
        """The hardware is wrong for what was asked of it."""

    class UnknownArchiveType(HardwareError):
        """A record type this driver does not know."""

    class UnsupportedFeature(Exception):
        """This console cannot do that."""

    class ViolatedPrecondition(Exception):
        """Called in an order that cannot work."""

    class StopNow(Exception):
        """Stop the loop."""

    for cls in (WeeWxIOError, WakeupError, CRCError, RetriesExceeded,
                HardwareError, UnknownArchiveType, UnsupportedFeature,
                ViolatedPrecondition, StopNow):
        setattr(weewx, cls.__name__, cls)
    # ws1.py spells it `WeeWXIOError`. Upstream's own typo, and it is raised
    # on a read failure -- so with the name missing the driver would work
    # until the serial line hiccups, then fail on the line meant to report it.
    weewx.WeeWXIOError = WeeWxIOError

    def crc16(buf: bytes) -> int:
        """CCITT CRC-16. Only Vantage asks for it."""
        crc = 0
        for byte in buf:
            crc = ((crc << 8) & 0xFF00) ^ _CRC_TABLE[((crc >> 8) & 0xFF) ^ byte]
        return crc

    weewx.crc16 = crc16
    return weewx


def _drivers_module() -> types.ModuleType:
    """`weewx.drivers`: three base classes and nothing else.

    They are nearly empty, and so are WeeWX's. What its own hold is
    `genLoopPackets` raising NotImplementedError and a `closePort` that does
    nothing. A driver leaning on more than that is one to hear about from a
    traceback rather than to guess at.
    """
    drivers = types.ModuleType("weewx.drivers")
    drivers.__path__ = []  # type: ignore[attr-defined]

    class AbstractDevice:
        def genLoopPackets(self):  # noqa: N802 - WeeWX's name
            raise NotImplementedError("genLoopPackets")

        def genArchiveRecords(self, lastgood_ts):  # noqa: N802 - WeeWX's name
            raise NotImplementedError("genArchiveRecords")

        def getTime(self):  # noqa: N802 - WeeWX's name
            raise NotImplementedError("getTime")

        def setTime(self):  # noqa: N802 - WeeWX's name
            raise NotImplementedError("setTime")

        @property
        def hardware_name(self):
            return "Unknown"

        @property
        def archive_interval(self):
            raise NotImplementedError("archive_interval")

        def closePort(self):  # noqa: N802 - WeeWX's name
            pass

    class AbstractConfEditor:
        """Only used by `weectl station`, which is not run here."""

        @property
        def default_stanza(self):
            return ""

        def get_conf(self, orig_stanza=None):
            return orig_stanza or self.default_stanza

        def prompt_for_settings(self):
            return {}

        def modify_config(self, config_dict):
            pass

    class AbstractConfigurator:
        """Likewise: a driver's own command line."""

        @property
        def description(self):
            return "Configuration utility for a weewx device."

        @property
        def usage(self):
            return "%prog [config_file] [options] [-y] [--debug] [--help]"

        def configure(self, config_dict):
            pass

    drivers.AbstractDevice = AbstractDevice
    drivers.AbstractConfEditor = AbstractConfEditor
    drivers.AbstractConfigurator = AbstractConfigurator
    return drivers


def _wxformulas_module() -> types.ModuleType:
    formulas = types.ModuleType("weewx.wxformulas")

    def calculate_delta(newtotal, oldtotal, delta_key="rain"):
        """The increment between two running totals, or None.

        Transcribed, like everything else that touches a reading. A counter
        that went backwards gives None and not zero: zero is a measurement
        saying no rain fell, None says we do not know, and a counter reset
        makes the second one true.
        """
        if newtotal is not None and oldtotal is not None:
            if newtotal >= oldtotal:
                return newtotal - oldtotal
            log.info("'%s' counter reset detected: new=%s old=%s",
                     delta_key, newtotal, oldtotal)
            return None
        return None

    formulas.calculate_delta = calculate_delta
    formulas.calculate_rain = calculate_delta   # upstream's older name
    return formulas


def _weeutil_modules() -> tuple[types.ModuleType, ...]:
    import time

    weeutil = types.ModuleType("weeutil")
    weeutil.__path__ = []  # type: ignore[attr-defined]

    inner = types.ModuleType("weeutil.weeutil")

    def to_bool(value):
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ("true", "yes", "y", "1", "on"):
                return True
            if value.lower() in ("false", "no", "n", "0", "off", ""):
                return False
            raise ValueError(f"Unknown boolean specifier: '{value}'")
        return bool(value)

    def to_int(value):
        if value is None or (isinstance(value, str)
                             and value.strip().lower() == "none"):
            return None
        if isinstance(value, str) and "." in value:
            # WeeWX answers 5 to `to_int('5.0')`. A configuration written by
            # hand says 5.0 often enough, and `int('5.0')` raises.
            value = float(value)
        return int(value)

    def to_float(value):
        if value is None or (isinstance(value, str)
                             and value.strip().lower() == "none"):
            return None
        return float(value)

    def timestamp_to_string(ts, format_str="%Y-%m-%d %H:%M:%S %Z"):
        if ts is None:
            return "******* N/A *******     (    N/A   )"
        return f"{time.strftime(format_str, time.localtime(ts))} ({int(ts)})"

    def startOfDay(time_ts):  # noqa: N802 - WeeWX's name
        when = time.localtime(time_ts)
        return int(time.mktime((when.tm_year, when.tm_mon, when.tm_mday,
                                0, 0, 0, 0, 0, -1)))

    def y_or_n(prompt, noprompt=False, default=None):
        """A driver asking a terminal to be sure. There is none here."""
        raise RuntimeError(
            "the driver asked for confirmation on a terminal that is not "
            "there; run its own configurator under WeeWX for that")

    for name, thing in (("to_bool", to_bool), ("tobool", to_bool),
                        ("to_int", to_int), ("to_float", to_float),
                        ("timestamp_to_string", timestamp_to_string),
                        ("startOfDay", startOfDay), ("y_or_n", y_or_n)):
        setattr(inner, name, thing)

    logger = types.ModuleType("weeutil.logger")
    logger.setup = lambda *a, **k: None

    def log_traceback(log_fn, prefix=""):
        import traceback

        for line in traceback.format_exc().splitlines():
            log_fn(f"{prefix}{line}")

    logger.log_traceback = log_traceback
    return weeutil, inner, logger


# WeeWX's CRC-16 table, copied. Only Vantage needs it, and a table of
# constants is the one kind of code where retyping is worse than copying.
_CRC_TABLE = [
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5, 0x60c6, 0x70e7,
    0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef,
    0x1231, 0x0210, 0x3273, 0x2252, 0x52b5, 0x4294, 0x72f7, 0x62d6,
    0x9339, 0x8318, 0xb37b, 0xa35a, 0xd3bd, 0xc39c, 0xf3ff, 0xe3de,
    0x2462, 0x3443, 0x0420, 0x1401, 0x64e6, 0x74c7, 0x44a4, 0x5485,
    0xa56a, 0xb54b, 0x8528, 0x9509, 0xe5ee, 0xf5cf, 0xc5ac, 0xd58d,
    0x3653, 0x2672, 0x1611, 0x0630, 0x76d7, 0x66f6, 0x5695, 0x46b4,
    0xb75b, 0xa77a, 0x9719, 0x8738, 0xf7df, 0xe7fe, 0xd79d, 0xc7bc,
    0x48c4, 0x58e5, 0x6886, 0x78a7, 0x0840, 0x1861, 0x2802, 0x3823,
    0xc9cc, 0xd9ed, 0xe98e, 0xf9af, 0x8948, 0x9969, 0xa90a, 0xb92b,
    0x5af5, 0x4ad4, 0x7ab7, 0x6a96, 0x1a71, 0x0a50, 0x3a33, 0x2a12,
    0xdbfd, 0xcbdc, 0xfbbf, 0xeb9e, 0x9b79, 0x8b58, 0xbb3b, 0xab1a,
    0x6ca6, 0x7c87, 0x4ce4, 0x5cc5, 0x2c22, 0x3c03, 0x0c60, 0x1c41,
    0xedae, 0xfd8f, 0xcdec, 0xddcd, 0xad2a, 0xbd0b, 0x8d68, 0x9d49,
    0x7e97, 0x6eb6, 0x5ed5, 0x4ef4, 0x3e13, 0x2e32, 0x1e51, 0x0e70,
    0xff9f, 0xefbe, 0xdfdd, 0xcffc, 0xbf1b, 0xaf3a, 0x9f59, 0x8f78,
    0x9188, 0x81a9, 0xb1ca, 0xa1eb, 0xd10c, 0xc12d, 0xf14e, 0xe16f,
    0x1080, 0x00a1, 0x30c2, 0x20e3, 0x5004, 0x4025, 0x7046, 0x6067,
    0x83b9, 0x9398, 0xa3fb, 0xb3da, 0xc33d, 0xd31c, 0xe37f, 0xf35e,
    0x02b1, 0x1290, 0x22f3, 0x32d2, 0x4235, 0x5214, 0x6277, 0x7256,
    0xb5ea, 0xa5cb, 0x95a8, 0x8589, 0xf56e, 0xe54f, 0xd52c, 0xc50d,
    0x34e2, 0x24c3, 0x14a0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
    0xa7db, 0xb7fa, 0x8799, 0x97b8, 0xe75f, 0xf77e, 0xc71d, 0xd73c,
    0x26d3, 0x36f2, 0x0691, 0x16b0, 0x6657, 0x7676, 0x4615, 0x5634,
    0xd94c, 0xc96d, 0xf90e, 0xe92f, 0x99c8, 0x89e9, 0xb98a, 0xa9ab,
    0x5844, 0x4865, 0x7806, 0x6827, 0x18c0, 0x08e1, 0x3882, 0x28a3,
    0xcb7d, 0xdb5c, 0xeb3f, 0xfb1e, 0x8bf9, 0x9bd8, 0xabbb, 0xbb9a,
    0x4a75, 0x5a54, 0x6a37, 0x7a16, 0x0af1, 0x1ad0, 0x2ab3, 0x3a92,
    0xfd2e, 0xed0f, 0xdd6c, 0xcd4d, 0xbdaa, 0xad8b, 0x9de8, 0x8dc9,
    0x7c26, 0x6c07, 0x5c64, 0x4c45, 0x3ca2, 0x2c83, 0x1ce0, 0x0cc1,
    0xef1f, 0xff3e, 0xcf5d, 0xdf7c, 0xaf9b, 0xbfba, 0x8fd9, 0x9ff8,
    0x6e17, 0x7e36, 0x4e55, 0x5e74, 0x2e93, 0x3eb2, 0x0ed1, 0x1ef0,
]


# -- installing ---------------------------------------------------------


def install(force: bool = False) -> list[str]:
    """Claim the names a driver imports. Returns the ones this call claimed.

    Nothing is replaced. A name already in `sys.modules` belongs either to
    the real WeeWX or to `skinkit`, and in both cases what is there knows
    more than this does.
    """
    if not force and installed():
        log.debug("WeeWX is installed; the stand-in is not needed")
        return []

    weewx = _weewx_module()
    drivers = _drivers_module()
    formulas = _wxformulas_module()
    weeutil, weeutil_inner, weeutil_logger = _weeutil_modules()

    claimed = []
    for name, module in (("weewx", weewx),
                         ("weewx.drivers", drivers),
                         ("weewx.wxformulas", formulas),
                         ("weeutil", weeutil),
                         ("weeutil.weeutil", weeutil_inner),
                         ("weeutil.logger", weeutil_logger)):
        if name in sys.modules:
            continue
        sys.modules[name] = module
        claimed.append(name)
        if "." in name:
            parent, child = name.rsplit(".", 1)
            setattr(sys.modules[parent], child, module)

    if claimed:
        log.info("no WeeWX installed; standing in for %s", ", ".join(claimed))
    return claimed


def standing_in() -> list[str]:
    """Which of the names are ours rather than a package on the disk."""
    return [name for name in NAMES
            if name in sys.modules
            and getattr(sys.modules[name], "__file__", None) is None]


def describe() -> dict[str, Any]:
    """What is standing in, for `weewx-driver check` to print."""
    return {"weewx_installed": installed(), "standing_in": standing_in()}

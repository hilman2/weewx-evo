"""Uploads: readings out to a weather service.

An export moves *files* -- a feed wrote a directory, and something has to put
it on a web host. An upload moves *readings*: one archive record, turned into
whatever shape Weather Underground or Windy or an APRS gateway wants, and
posted. Nothing about it involves a directory, which is why it is not an
export with a strange source.

WeeWX has this in the core as `StdRESTful`, and so should we: uploading to
Weather Underground is not an add-on for a weather station, it is most of the
reason people run one. What is an add-on is the tenth service; the shape here
is built so that the tenth is forty lines.

An upload is any object with `post()`:

    class MyUpload:
        def post(self, records: list[dict]) -> Posted:
            ...

        @staticmethod
        def options():        # the admin page builds a form from this
            return [...]

`records` is oldest first. Usually it is one -- the interval that just closed.
It is a list because a connection that was down for ten minutes has two
choices when it comes back: send the newest and pretend the rest never
happened, or send them all. Weather Underground, PWSweather and WOW all take a
timestamp with the reading and will accept the ones that were missed. Making
that the caller's job rather than each service's means the service that cannot
backfill says so once, with `backfill = False`, and gets handed only the last.

The state that makes this work -- how far each upload has got -- is a file, for
the same reasons as `exports/tracker.py`: it survives a restart, it can be read
with `cat`, and losing it costs one duplicate post rather than a gap.
"""

from __future__ import annotations

import http.client
import logging
import socket
import ssl
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .. import units

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "weewx_evo.uploads"

#: Long enough for a service having a slow afternoon, short enough that a dead
#: one does not still be waiting when the next interval closes.
TIMEOUT = 20


@dataclass
class Posted:
    """What one run of an upload did."""

    sent: int = 0
    skipped: int = 0
    seconds: float = 0.0
    #: Records that failed, with why. One bad record does not abandon the
    #: rest: a service that rejects a reading from last Tuesday will still
    #: take the one from a minute ago.
    failures: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""
    #: The newest record timestamp this upload actually got accepted. The
    #: runner writes it down, and that is what makes a restart continue
    #: rather than start again.
    through: int | None = None

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        parts = [f"{self.sent} sent"]
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        parts.append(f"{self.seconds:.1f}s")
        if self.failures:
            parts.append(f"{len(self.failures)} FAILED")
        if self.note:
            parts.append(self.note)
        return ", ".join(parts)


class UploadError(Exception):
    """Something that stopped an upload before it posted anything.

    Configuration that cannot work, a host that does not resolve. Distinct
    from a record that was rejected, which goes in `Posted.failures`: one is
    "this will never work until somebody changes it", the other is "this one
    reading did not go".
    """


class Rejected(UploadError):
    """The service answered, and said no.

    Worth its own type because the answer decides what to do next. A 401 is
    permanent and retrying it every five minutes for a year is how an account
    gets blocked; a 503 is Tuesday.
    """

    def __init__(self, message: str, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


@runtime_checkable
class Upload(Protocol):
    """Readings out."""

    def post(self, records: list[dict]) -> Posted:
        """Send `records`, oldest first.

        Raising means nothing was sent and why. Individual records that were
        rejected go in `Posted.failures` instead.
        """
        ...


class BaseUpload:
    """Defaults for an upload. Only `post` has to be written."""

    #: Shown on the admin page and in `weewx-evo upload list`.
    label: str = "upload"
    #: One line for the form that offers the kinds.
    summary: str = ""
    #: Whether records missed while the service was unreachable are worth
    #: sending afterwards. True for anything that takes a timestamp with the
    #: reading. False for a service that only ever means "now" -- posting it
    #: a ten-minute-old wind speed as current is worse than posting nothing.
    backfill: bool = True
    #: At most this many records in one catch-up. A station that was offline
    #: for a week must not come back and fire two thousand requests at a free
    #: service; that is how an account stops working.
    catch_up_limit: int = 12
    #: What wakes it: "record" after every archive record, "interval" on its
    #: own clock, "manual" only when asked.
    trigger: str = "record"
    every: int = 900

    def post(self, records: list[dict]) -> Posted:
        raise NotImplementedError

    def check(self) -> str:
        """Try the service and say what happened, without posting readings.

        The admin page offers this as a button. Most of these services answer
        a wrong password with a cheerful 200 and the word `badauth` in the
        body, so finding out at setup time is worth a great deal more than
        finding out never.
        """
        return "This upload cannot be tested without posting something."

    def status(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        """Release anything held. Optional."""


# ---------------------------------------------------------------------------
# Reading a record in whatever unit a service asks for.
# ---------------------------------------------------------------------------

class Readings:
    """One archive record, readable in any unit.

    Every one of these services specifies its units and none of them agree:
    Weather Underground wants Fahrenheit and inches of mercury, Windy wants
    Celsius and metres per second, APRS wants Fahrenheit and hundredths of an
    inch. The archive holds whatever the station wrote.

    So the conversion happens here, once, against `units.py` -- rather than in
    each service with its own quiet arithmetic. That was WeeWX's mistake with
    the two chart generators: both were right on their own and they disagreed
    in the third decimal.
    """

    __slots__ = ("record", "system")

    def __init__(self, record: dict) -> None:
        self.record = record
        self.system = units.system_from(record.get("usUnits"), default=units.US)

    @property
    def ts(self) -> int:
        return int(self.record.get("dateTime") or 0)

    def __contains__(self, obs: str) -> bool:
        return self.record.get(obs) is not None

    def get(self, obs: str, unit: str | None = None) -> float | None:
        """A reading, converted. None when the station does not report it.

        None rather than a zero, always. A station with no rain gauge that
        posts `rain=0` every five minutes is indistinguishable from one in a
        drought, and the service keeps it forever.
        """
        value = self.record.get(obs)
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if unit is None:
            return value
        stored, _group = units.unit_of(obs, self.system)
        if stored is None or stored == unit:
            return value
        converted = units.convert(value, stored, unit)
        return None if converted is None else float(converted)

    def text(self, obs: str, unit: str | None = None,
             spec: str = ".1f") -> str | None:
        """A reading as the string that goes in a query, or None.

        `spec` is a format spec, not a number of decimals, because the width
        is part of these protocols: Weather Underground writes humidity as
        `061` and wind speed as `003.1`. Zero-padding looks like decoration
        and is not -- it is what the field is defined as.
        """
        value = self.get(obs, unit)
        if value is None:
            return None
        return format(value, spec)


# ---------------------------------------------------------------------------
# Talking to a service.
# ---------------------------------------------------------------------------

def request(host: str, path: str, method: str = "GET",
            body: bytes | None = None, headers: dict[str, str] | None = None,
            tls: bool = True, port: int | None = None,
            timeout: int = TIMEOUT, binary: bool = False) -> tuple[int, Any]:
    """One HTTP request. Returns the status and the body.

    Text by default, because everything in this package speaks text.
    `binary=True` returns the bytes instead, for a caller that is about to
    hand them to `zipfile` -- decoding a ZIP as UTF-8 and encoding it back
    does not round-trip, and the failure is a corrupt archive rather than an
    error anybody can read.

    `http.client` rather than anything installed, because the whole core runs
    on the standard library and one upload service is not the thing to break
    that for.

    Network trouble comes back as `Rejected`, not as whatever exception the
    socket layer felt like: a caller deciding whether to retry should not have
    to know the difference between `socket.gaierror` and `ssl.SSLError`.
    """
    conn_class = http.client.HTTPSConnection if tls else http.client.HTTPConnection
    kwargs: dict[str, Any] = {"timeout": timeout}
    if tls:
        kwargs["context"] = ssl.create_default_context()
    conn = conn_class(host, port, **kwargs)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        raw = response.read()
        if binary:
            return response.status, raw
        return response.status, raw.decode("utf-8", "replace").strip()
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        # A name that does not resolve is permanent enough to say so: it is
        # almost always a typo in the host, and retrying a typo forever is
        # how a log fills up with the same line.
        permanent = isinstance(exc, socket.gaierror)
        raise Rejected(f"{type(exc).__name__}: {exc}", permanent=permanent) from exc
    finally:
        conn.close()


def query(path: str, fields: dict[str, Any]) -> str:
    """A path with a query string, leaving out anything that is None.

    Leaving out is the point. Every one of these services treats a parameter
    that is present and empty differently from one that is absent, and
    several of them record the empty one as a zero.
    """
    present = {k: v for k, v in fields.items() if v is not None and v != ""}
    return f"{path}?{urllib.parse.urlencode(present)}"


# ---------------------------------------------------------------------------
# The registry.
# ---------------------------------------------------------------------------

class Registry:
    """The uploads this installation has.

    The same shape as the export and driver registries, and for the same
    reason: an upload holds configuration and a little state -- how far it has
    got -- and that has to survive between runs.
    """

    def __init__(self) -> None:
        self._uploads: dict[str, object] = {}
        self._factories: dict[str, Callable[..., object]] = {}
        self._loaded = False

    def register(self, name: str, upload: object, replace: bool = False) -> None:
        if name in self._uploads and not replace:
            raise ValueError(f"an upload named {name!r} is already registered")
        self._uploads[name] = upload

    def register_factory(self, name: str, factory: Callable[..., object]) -> None:
        self._factories[name] = factory

    def factory_for(self, kind: str) -> Callable[..., object] | None:
        self.load()
        return self._factories.get(kind)

    def get(self, name: str) -> object | None:
        self.load()
        return self._uploads.get(name)

    def known(self, name: str) -> bool:
        self.load()
        return name in self._uploads or name in self._factories

    def names(self) -> list[str]:
        self.load()
        return sorted(set(self._uploads) | set(self._factories))

    def kinds(self) -> list[str]:
        self.load()
        return sorted(self._factories)

    def describe(self, kind: str) -> str:
        factory = self.factory_for(kind)
        return getattr(factory, "summary", "") if factory else ""

    def load(self) -> None:
        """Pull in what is installed. A broken one is reported, never fatal."""
        if self._loaded:
            return
        self._loaded = True

        from importlib.metadata import entry_points

        for entry in entry_points(group=ENTRY_POINT_GROUP):
            try:
                loaded = entry.load()
                if isinstance(loaded, type):
                    self.register_factory(entry.name, loaded)
                else:
                    self.register(entry.name, loaded, replace=True)
                log.info("upload %r from %s", entry.name, entry.value)
            except Exception:
                log.exception("could not load the upload %r; carrying on", entry.name)

        from . import ambient, cwop, mqtt, weathercloud, webpush, windy

        # Three services, one protocol. Weather Underground defined it, the
        # other two copied it down to the parameter names -- so they are one
        # module with three hosts rather than three near-identical files.
        self.register_factory("wunderground", ambient.WundergroundUpload)
        self.register_factory("pwsweather", ambient.PwsWeatherUpload)
        self.register_factory("wow", ambient.WowUpload)
        self.register_factory("windy", windy.WindyUpload)
        self.register_factory("weathercloud", weathercloud.WeathercloudUpload)
        self.register_factory("cwop", cwop.CwopUpload)
        self.register_factory("mqtt", mqtt.MqttUpload)
        self.register_factory("webpush", webpush.WebPushUpload)


#: The registry the CLI and the admin page use.
DEFAULT = Registry()


def get(name: str) -> object | None:
    return DEFAULT.get(name)


def names() -> list[str]:
    return DEFAULT.names()


def kinds() -> list[str]:
    return DEFAULT.kinds()


def describe(kind: str) -> str:
    return DEFAULT.describe(kind)


def when_options(trigger: str = "record", every: int = 900,
                 catch_up: int = 12, live: bool = False) -> list:
    """The "when it runs" group, which every upload has the same.

    One copy, because four services with four subtly different wordings for
    the same three choices is how a settings page stops being readable. The
    defaults are arguments because CWOP asks for one report every ten minutes
    and means it, while the rest want one per archive record.
    """
    from ..options import Group, Option

    choices: tuple[tuple[str, str], ...] = (
        ("record", "after every archive record"),
        ("interval", "on its own schedule"),
        ("manual", "only when asked"),
    )
    if live:
        # Only offered where it means something. A weather service that takes
        # one reading every five minutes has no use for it, and offering it
        # there would be an invitation to get an account rate-limited.
        choices = (("live", "every few seconds, as readings arrive"),) + choices

    return [
        Group("When it runs", "", (
            Option("trigger", "Post", kind="choice", default=trigger,
                   choices=choices,
                   help="After every record is right for almost everything: "
                        "the service gets a reading as soon as one exists. "
                        "Its own schedule is for a service that asks for less "
                        "often than the archive interval."),
            Option("every", "Its own schedule", kind="duration",
                   default=every, minimum=60, maximum=86400,
                   help="Only used with 'on its own schedule'."),
            Option("catch_up", "Send up to this many missed records",
                   kind="int", default=catch_up, minimum=0, maximum=288,
                   advanced=True,
                   help="After a connection was down. Zero means send only "
                        "the newest. The limit exists so that a station "
                        "offline for a week does not come back and fire two "
                        "thousand requests at a free service."),
        )),
    ]

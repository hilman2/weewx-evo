"""The admin page.

A form built from whatever declares settings: the core, every driver, and in
time every feed. Nothing here knows what an Ecowitt is or what an archive
interval means -- it renders `Option` objects and writes back what comes out.
That is the whole design: a driver that gains a setting gains a field, and
this file does not change.

On its own port, behind its own token, and bound to localhost by default. It
is a great deal more dangerous than the upload endpoint: an upload can at
worst put a wrong temperature in the record, whereas this can point the
archive at a different file. The two therefore share nothing -- not the port,
not the token, not the reasoning about who may reach them.

Saving writes the configuration file and says which settings need a restart.
It does not restart anything: a process that can restart itself is a process
that can fail to come back, and on a machine in a shed that is the difference
between a wrong setting and a dead station.
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from . import (
    adminaddons,
    adminarchives,
    adminhome,
    adminlive,
    adminplots,
    adminpublish,
    adminquality,
    adminsearch,
    adminsetup,
    adminstations,
    adminsystem,
)
from . import archives as archive_defs
from . import config as config_file
from . import language as language_defs
from . import notify as notify_registry
from . import settings as settings_state
from .netaccess import PRIVATE_ONLY, Access
from .options import UNITS, Group, Invalid, Option, Schema, split_duration
from .ratelimit import Limits

log = logging.getLogger(__name__)

MAX_FORM = 1 << 18


def export_kinds() -> list[str]:
    """The kinds of export that can be added. Asked, not listed."""
    from . import exports

    return exports.kinds()


def feed_kinds() -> list[str]:
    """The kinds of feed that can be added. Asked, not listed."""
    from . import feeds

    return feeds.kinds()


def feed_kind_choices() -> list[tuple[str, str, str]]:
    """Each kind, and what it is for."""
    from . import feeds

    return [(kind, kind, feeds.describe(kind)) for kind in feeds.kinds()]


def export_kind_choices() -> list[tuple[str, str, str]]:
    """Each kind, what it is called, and what it is for.

    A dropdown reading `ftp / local / rsync` asks somebody to already know
    the answer. The point of the page is that they should not have to.
    """
    from . import exports

    out = []
    for kind in exports.kinds():
        factory = exports.DEFAULT.factory_for(kind)
        out.append((kind, getattr(factory, "label", kind),
                    getattr(factory, "summary", "")))
    return out

#: Set up from an export rather than chosen here. The live readings for this
#: station's own pages are not a service somebody signs up to: the address,
#: the token, the directories and the units all come from the export that
#: publishes those pages, so there is nothing to fill in and nothing to
#: choose. Offered here it was a form of eight empty fields, and the empty
#: one that mattered was the units -- a station sending Fahrenheit published
#: Fahrenheit into pages written in Celsius.
#:
#: A second web host, or the same readings in another unit system, is a line
#: in the file, which stays editable by hand.
NOT_CHOSEN = frozenset({"webpush"})


def upload_kinds() -> list[str]:
    """The kinds of upload that can be added. Asked, not listed.

    Not every kind that exists: see NOT_CHOSEN. The check on the way in uses
    this too, so the one left out cannot be reached by typing the URL either.
    """
    from . import uploads

    return [k for k in uploads.kinds() if k not in NOT_CHOSEN]




def upload_kind_choices() -> list[tuple[str, str, str]]:
    """Each service, what it is called, and what it is for.

    The same reasoning as the exports: a dropdown reading
    `ambient / cwop / mqtt` asks somebody to already know the answer.
    """
    from . import uploads

    out = []
    for kind in uploads.kinds():
        if kind in NOT_CHOSEN:
            continue
        factory = uploads.DEFAULT.factory_for(kind)
        out.append((kind, getattr(factory, "label", kind),
                    getattr(factory, "summary", "")))
    return out


def forecast_kinds() -> list[str]:
    """The forecast sources that can be added. Asked, not listed."""
    from . import forecast

    return forecast.kinds()


def forecast_kind_choices() -> list[tuple[str, str, str]]:
    from . import forecast

    out = []
    for kind in forecast.kinds():
        factory = forecast.DEFAULT.factory_for(kind)
        out.append((kind, getattr(factory, "label", kind),
                    getattr(factory, "summary", "")))
    return out


#: Prefix for the hidden field that says "this checkbox was on the form".
#: A browser sends nothing for an unticked box, which is indistinguishable
#: from a field that was never there -- and the two must mean different
#: things, or a partial request wipes what it did not mention.
MARKER = "__present__"

#: Prefix for the hidden field that says "the ordered picker was on the
#: form, and it had this many boxes". Same job as `MARKER`: the boxes are
#: named one per row, so the option's own name is sent by nothing at all and
#: "emptied" and "not part of this request" would otherwise look identical.
SLOTS = "__slots__"

#: A newline, for joining inside an f-string.
NEWLINE = chr(10)


#: The pages that create something, which are not schemas and so have to be
#: listed. One list, used by both the router and the renderer, because two
#: lists is how one of them ends up short.
ADD_PAGES = ("new-export", "new-feed", "new-upload", "new-forecast",
             "new-notify", "new-collector", "new-plot", "import-plots",
             "new-sender", "new-place", "new-station", "new-archive")

#: Pages that are neither a schema nor a form to create one. They render
#: themselves, the way the chart pages do.
#: Pages that render themselves. `setup` is the wizard, and it is
#: here rather than in ADD_PAGES because it is not adding one thing:
#: it is the path from an empty directory to a station recording.
OWN_PAGES = ("overview", "senders", "places", "system", "stations", "live",
             "archives", "publishing", "charts", "quality", "search",
             "setup", "addons")

#: What a POST to the stations page may ask for. Named rather than inferred
#: from the path: a path is whatever a browser resolved a relative link to,
#: and the verb is what the button actually said.
STATION_ACTIONS = frozenset({
    "adopt", "ignore", "unignore", "set", "learn", "remove",
})


def _a_row(given: list | None) -> int | None:
    """A `seq` out of a query string, or None.

    None for anything that is not a whole number, which is the same answer as
    not asking: the live page pages on `seq`, and a cursor somebody typed by
    hand should give them the newest rows rather than an error.
    """
    if not given:
        return None
    try:
        return int(str(given[0]))
    except (TypeError, ValueError):
        return None


#: A name for something the operator adds -- an export, later a feed. It ends
#: up as a TOML key and as part of a filename, so it is kept to what is safe
#: in both rather than escaped in two places.
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class Admin:
    """What the pages do, without the HTTP."""

    def __init__(self, path: Path, schemas: list[Schema] | Callable[[], list[Schema]],
                 token: str, read_only: bool = False,
                 access: Access = PRIVATE_ONLY,
                 limits: Limits | None = None) -> None:
        self.path = Path(path)
        # A callable, when the set of pages can change. Adding an export adds
        # a page, so the list cannot be settled once at startup.
        self._schema_source = schemas if callable(schemas) else (lambda: schemas)
        self._schemas: list[Schema] | None = None
        self.token = token
        self.read_only = read_only
        # Private networks only unless somebody says otherwise. This page can
        # point the archive at a different file: the laptop in the kitchen
        # should reach it, the open internet should not.
        self.access = access
        self.refused_peers = 0
        # Tighter than the listener's, but not by much. Saving is two
        # requests -- the POST and the redirect after it -- and somebody
        # clicking through the tabs makes several in a second. A limit that
        # gets in their way is one they will turn off, which helps nobody.
        # What stops a search is the failure limit, not this.
        self.limits = limits or Limits(rate=5.0)
        self.saved_at: float | None = None
        self.restart_pending: set[str] = set()
        self._lock = threading.Lock()

    @property
    def schemas(self) -> list[Schema]:
        if self._schemas is None:
            self._schemas = self._schema_source()
        return self._schemas

    def refresh(self) -> None:
        """Rebuild the list of pages. After anything is added or removed."""
        self._schemas = None

    def config(self) -> dict[str, Any]:
        return config_file.read(self.path)

    def values(self, schema: Schema) -> dict[str, Any]:
        return config_file.values_for(self.config(), schema)

    # -- what this page is written in ------------------------------------

    @property
    def language(self) -> Any:
        """The language every page of this settings site is written in.

        Read from the file rather than from `settings.running()`, because
        `weewx-evo admin` is its own process and there is no running one to
        ask. Re-read per page: somebody changing the language expects the
        page that comes back to be in it, and this is one small file read
        against a page that already reads several.
        """
        from . import language as language_defs

        return language_defs.get(config_file.get(self.config(), "language"))

    def say(self, english: str) -> str:
        """One piece of this page, in the operator's language.

        On `Admin` rather than imported per module, so nothing on the
        settings page reads the configuration for itself -- the same rule
        `Settings` follows. It is short because it ends up around several
        hundred strings, and a long name there would cost more than it says.
        """
        return self.language.say(english)

    # -- adding and removing ---------------------------------------------

    def write_settings(self, values: dict[str, Any], note: str = "") -> str:
        """Put several settings at once. Returns an error, or empty.

        For the wizard, which answers three or four at a time and would
        otherwise write the file once per field -- four rewrites where one
        will do, and four chances for the fourth to fail after the third
        succeeded.

        Dotted names, the same ones `--explain` prints. Nothing is validated
        here beyond being writable: the caller has already parsed what it
        asked for, and a second opinion in this method would be a second
        place for the rules to live.
        """
        if self.read_only:
            return "This settings page was started read-only."
        if not values:
            return ""
        with self._lock:
            current = self.config()
            for dotted, value in values.items():
                config_file.put(current, dotted, value)
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return f"Could not write {self.path}: {exc}"
        log.info("%d setting(s) written%s", len(values),
                 f" -- {note}" if note else "")
        self.refresh()
        return ""

    def add_export_settings(self, name: str, settings: dict[str, Any]) -> str:
        """Create an export with everything it needs, in one write.

        `add_export` takes a name and a kind and leaves the rest to the page
        that follows, which is right when a person is filling it in. The
        wizard and the weewx.conf import already hold every answer, and
        making them post the form afterwards would be theatre.

        A name that is taken is left alone rather than overwritten. Somebody
        who has already set up an export called `site` has said more about it
        than an import can know.
        """
        if self.read_only:
            return "This settings page was started read-only."
        name = (name or "").strip().lower()
        if not NAME.match(name):
            return f"{name!r} cannot be an export's name."
        with self._lock:
            current = self.config()
            if config_file.get(current, f"exports.{name}") is not None:
                return f"There is already an export called {name!r}."
            for key, value in settings.items():
                if value in (None, ""):
                    continue
                config_file.put(current, f"exports.{name}.{key}", value)
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def add_export(self, name: str, kind: str) -> str:
        """Create an export. Returns an error, or empty if it worked.

        Only the name and the kind: everything else is filled in on the page
        that appears afterwards. Asking for a host and a password before there
        is anything to save them in is how a form ends up losing what somebody
        typed.
        """
        if self.read_only:
            return "This admin page was started read-only."
        name = (name or "").strip().lower()
        if not NAME.match(name):
            return ("A name may hold lowercase letters, digits, - and _, and "
                    "must start with a letter. It becomes a heading and part "
                    "of a filename.")
        if kind not in export_kinds():
            return f"{kind!r} is not one of: {', '.join(export_kinds())}"

        with self._lock:
            current = self.config()
            if config_file.get(current, f"exports.{name}") is not None:
                return f"There is already an export called {name!r}."
            config_file.put(current, f"exports.{name}.kind", kind)
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def add_collector(self, name: str, kind: str, driver: str = "") -> str:
        """Create a collector. Returns an error, or empty if it worked.

        The name is checked against what the listener already answers to, and
        not only against other collectors. A collector called `ecowitt` would
        take a real driver's endpoint: the uploads would still arrive, be
        handed to the envelope parser, fail to parse, and look like a console
        that had stopped working.

        `driver` is the hardware, and it is asked for here rather than on the
        page after: which driver was chosen decides which fields that page
        has, so leaving it for later means arriving at a form that cannot ask
        anything yet. Empty is a collector configured from a `weewx.conf`,
        which is what an installation moving over already has.
        """
        from . import collectors as collector_defs

        if self.read_only:
            return "This admin page was started read-only."
        name = (name or "").strip().lower()
        if not NAME.match(name):
            return ("A name may hold lowercase letters, digits, - and _, and "
                    "must start with a letter. Its readings arrive under it, "
                    "so name it for where the console is.")
        if kind not in collector_defs.kinds():
            return (f"{kind!r} is not one of: "
                    f"{', '.join(collector_defs.kinds())}")

        taken = collector_defs.reserved()
        if name in taken:
            return (f"Something already answers to {name!r} -- it is a "
                    f"driver or the envelope endpoint. Its readings would be "
                    f"recorded under the wrong driver. Pick another name.")

        with self._lock:
            current = self.config()
            if config_file.get(current, f"collectors.{name}") is not None:
                return f"There is already a driver called {name!r}."
            config_file.put(current, f"collectors.{name}.kind", kind)
            if driver and kind == "weewx-driver":
                config_file.put(current, f"collectors.{name}.driver", driver)
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def remove_collector(self, name: str) -> str:
        """Take a collector out of the configuration.

        Nothing is stopped by this: the collector is another process, and
        very likely another machine. What it does is take the endpoint away,
        so a collector still running arrives as an unknown driver and is
        refused rather than recorded as something else.
        """
        if self.read_only:
            return "This admin page was started read-only."
        with self._lock:
            current = self.config()
            if config_file.get(current, f"collectors.{name}") is None:
                return f"There is no driver called {name!r}."
            (current.get("collectors") or {}).pop(name, None)
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def add_feed(self, name: str, kind: str) -> str:
        """Create a feed. Returns an error, or empty if it worked.

        Only the name and the kind. Everything else is on the page that
        appears afterwards, for the same reason an export works that way:
        asking for a dozen settings before there is anything to save them in
        is how a form loses what somebody typed.
        """
        if self.read_only:
            return "This admin page was started read-only."
        name = (name or "").strip().lower()
        if not NAME.match(name):
            return ("A name may hold lowercase letters, digits, - and _, and "
                    "must start with a letter. It becomes a heading and the "
                    "directory this feed writes into.")
        if kind not in feed_kinds():
            return f"{kind!r} is not one of: {', '.join(feed_kinds())}"

        with self._lock:
            current = self.config()
            if config_file.get(current, f"feeds.{name}") is not None:
                return f"There is already a feed called {name!r}."
            # A file that named no feeds was running the two that ship. Write
            # them down before adding a third, or adding one would silently
            # turn the other two off.
            if not (current.get("feeds") or {}):
                from .cli import DEFAULT_FEEDS

                for existing, settings in DEFAULT_FEEDS.items():
                    for key, value in settings.items():
                        config_file.put(current, f"feeds.{existing}.{key}",
                                        value)
            config_file.put(current, f"feeds.{name}.kind", kind)
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def remove_feed(self, name: str) -> str:
        """Delete a feed. What it already wrote is left where it is."""
        if self.read_only:
            return "This admin page was started read-only."
        with self._lock:
            current = self.config()
            section = current.get("feeds")
            if not isinstance(section, dict) or name not in section:
                return f"There is no feed called {name!r}."
            del section[name]
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def add_channel(self, name: str, kind: str) -> str:
        """Create a notification channel. Returns an error, or empty.

        Name and kind only, like an upload: asking for a server and a
        password before there is anything to save them in is how a form
        loses what somebody typed.
        """
        if self.read_only:
            return "This admin page was started read-only."
        name = (name or "").strip().lower()
        if not NAME.match(name):
            return ("A name may hold lowercase letters, digits, - and _, and "
                    "must start with a letter. It becomes a heading.")
        if kind not in notify_registry.kinds():
            return (f"{kind!r} is not one of: "
                    f"{', '.join(notify_registry.kinds())}")

        with self._lock:
            current = self.config()
            if config_file.get(current, f"notify.{name}") is not None:
                return f"There is already a channel called {name!r}."
            config_file.put(current, f"notify.{name}.kind", kind)
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def add_upload(self, name: str, kind: str) -> str:
        """Create an upload. Returns an error, or empty if it worked.

        Name and kind only, like an export: asking for a station id and a
        password before there is anything to save them in is how a form
        loses what somebody typed.
        """
        if self.read_only:
            return "This admin page was started read-only."
        name = (name or "").strip().lower()
        if not NAME.match(name):
            return ("A name may hold lowercase letters, digits, - and _, and "
                    "must start with a letter. It becomes a heading.")
        if kind not in upload_kinds():
            return f"{kind!r} is not one of: {', '.join(upload_kinds())}"

        with self._lock:
            current = self.config()
            if config_file.get(current, f"uploads.{name}") is not None:
                return f"There is already an upload called {name!r}."
            config_file.put(current, f"uploads.{name}.kind", kind)
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def remove_upload(self, name: str) -> str:
        """Delete an upload. Nothing is withdrawn from the service."""
        if self.read_only:
            return "This admin page was started read-only."
        with self._lock:
            current = self.config()
            section = current.get("uploads")
            if not isinstance(section, dict) or name not in section:
                return f"There is no upload called {name!r}."
            del section[name]
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def test_upload(self, name: str) -> str:
        """Try one service and say what it answered.

        Worth more here than anywhere else on this page: every one of these
        services answers a wrong password with a cheerful HTTP 200 and a word
        in the body, so an upload that is silently rejected looks exactly like
        one that is working.
        """
        settings = config_file.get(self.config(), f"uploads.{name}")
        if not isinstance(settings, dict):
            return f"There is no upload called {name!r}."
        try:
            from .cli import build_upload_for_place

            cfg = settings_state.running()
            if cfg is None or getattr(cfg, "_path", None) != self.path:
                core = next((schema for schema in self.schemas
                             if schema.name == "core"), None)
                if core is None:
                    raise ValueError("the core settings schema is unavailable")
                cfg = settings_state.Settings(
                    core, config=self.config(), path=self.path)
            upload = build_upload_for_place(name, settings, cfg)
        except Exception as exc:
            return str(exc)
        try:
            return upload.check()
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        finally:
            close = getattr(upload, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    log.debug("upload %s did not close cleanly", name)

    def add_forecast(self, name: str, kind: str) -> str:
        """Create a forecast source. Name and kind only, like the rest."""
        if self.read_only:
            return "This admin page was started read-only."
        name = (name or "").strip().lower()
        if not NAME.match(name):
            return ("A name may hold lowercase letters, digits, - and _, and "
                    "must start with a letter. It becomes a heading, and the "
                    "name a page asks for this source by.")
        if kind not in forecast_kinds():
            return f"{kind!r} is not one of: {', '.join(forecast_kinds())}"

        with self._lock:
            current = self.config()
            if config_file.get(current, f"forecast.{name}") is not None:
                return f"There is already a forecast source called {name!r}."
            config_file.put(current, f"forecast.{name}.kind", kind)
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def remove_forecast(self, name: str) -> str:
        """Delete a forecast source. What it fetched stays until it is pruned."""
        if self.read_only:
            return "This admin page was started read-only."
        with self._lock:
            current = self.config()
            section = current.get("forecast")
            if not isinstance(section, dict) or name not in section:
                return f"There is no forecast source called {name!r}."
            del section[name]
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def test_forecast(self, name: str) -> str:
        """Fetch once and say what came back, storing nothing.

        This button does double duty: a MOSMIX source with no station id and
        a MeteoAlarm source with no region both answer with the candidates
        rather than an error, which is how somebody finds theirs.
        """
        current = self.config()
        settings = config_file.get(current, f"forecast.{name}")
        if not isinstance(settings, dict):
            return f"There is no forecast source called {name!r}."
        try:
            from .cli import build_forecast_source
            from .forecast import Place

            source = build_forecast_source(name, dict(settings))
            register = adminarchives.load(self)
            archive = register.get(str(settings.get("archive") or "") or None)
            place = Place(
                latitude=float(archive.latitude or 0.0),
                longitude=float(archive.longitude or 0.0),
                altitude=archive.altitude,
                name=archive.title)
        except Exception as exc:
            return str(exc)
        try:
            return source.check(place)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"

    def remove_export(self, name: str) -> str:
        """Delete an export from the configuration. Nothing at the far end."""
        if self.read_only:
            return "This admin page was started read-only."
        with self._lock:
            current = self.config()
            section = current.get("exports")
            if not isinstance(section, dict) or name not in section:
                return f"There is no export called {name!r}."
            del section[name]
            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                return f"Could not write {self.path}: {exc}"
        self.refresh()
        return ""

    def columns(self, archive: str = "") -> set[str]:
        """The readings one place's archive has a column for.

        Asked of the database rather than of a schema: a station whose driver
        added its own columns should be able to chart them, and nothing here
        knows what those are called.

        `archive` names a place. Empty asks `archives.toml` for its declared
        default. The central configuration is never a second database path.
        """
        import sqlite3

        try:
            where = adminarchives.load(self).get(archive or None).file
        except Exception:
            log.debug("could not resolve the archive %r", archive,
                      exc_info=True)
            return set()
        path = Path(where)
        if not path.is_absolute():
            path = self.path.parent / path
        if not path.exists():
            return set()
        try:
            # `closing` as well as `with`: the context manager on a
            # connection commits the transaction and leaves the connection
            # open. This is called on every render of the charts page.
            with closing(sqlite3.connect(f"file:{path}?mode=ro",
                                         uri=True)) as conn:
                return {row[1] for row in conn.execute("PRAGMA table_info(archive)")
                        if row[1] not in ("dateTime", "usUnits", "interval")}
        except Exception:
            log.debug("could not read the archive columns", exc_info=True)
            return set()

    def test_export(self, name: str) -> str:
        """Try one export's destination and say what happened."""
        settings = config_file.get(self.config(), f"exports.{name}")
        if not isinstance(settings, dict):
            return f"There is no export called {name!r}."
        try:
            from .cli import build_export

            export = build_export(name, dict(settings))
        except Exception as exc:
            return str(exc)
        try:
            return export.check()
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"

    def save(self, schema: Schema, form: dict[str, Any]) -> dict[str, str]:
        """Check a form and write it. Returns what was wrong, empty if nothing.

        Everything is validated before anything is written. A form that
        applies the half it understood and reports the rest leaves a
        configuration nobody can reason about.
        """
        if self.read_only:
            return {"": "This admin page was started read-only."}

        form = rejoined(schema, form)
        parsed, errors = schema.parse(form, only_present=True)
        if errors:
            return errors
        for _group, option in schema:
            if option.kind != "list" or f"{SLOTS}{option.name}" not in form:
                continue
            if str(form.get(option.name) or "").strip():
                continue
            if option.default in (None, ""):
                # An option whose real value is not in this file at all. A
                # skin declares `stat_tile_observations` so the page can
                # offer the readings, and the thirty-five it actually shows
                # are in its own `skin.conf` -- the schema has no default
                # because there is nothing here to default to.
                #
                # The picker therefore renders empty on a page nobody has
                # ever saved, and writing that emptiness down turned "the
                # skin decides" into "show nothing": open the feed's page,
                # change the one setting you came for, press Save, and every
                # tile on every page is gone. Measured: eight tiles became
                # none.
                #
                # So an empty control here means what an empty box has always
                # meant -- nothing said. The cost is that such a list cannot
                # be emptied from the page, which is exactly what was true
                # before this control existed.
                continue
            # Every box emptied means an empty list, and `Option.parse`
            # cannot say that: an empty string comes back as the option's
            # default, `Schema.parse` drops a None, and `apply` then leaves
            # the file exactly as it was -- so a list could be added to and
            # never emptied. Said here and not in the parser, where it would
            # change what an empty box means for every option there is.
            parsed[option.name] = []

        with self._lock:
            current = self.config()
            before = config_file.values_for(current, schema)
            config_file.apply(current, schema, parsed)

            try:
                config_file.write(self.path, current, self.schemas)
            except Exception as exc:
                log.exception("could not write the configuration")
                return {"": f"Could not write {self.path}: {exc}"}

            import time
            self.saved_at = time.time()
            for _group, option in schema:
                # Only settings this form actually carried. `parse` was asked
                # for what was present, so everything else is missing from
                # `parsed` rather than changed to nothing -- and comparing
                # against it marked every restart-needing setting on the page
                # every time anything at all was saved. One save of the
                # station name claimed a dozen of them.
                if not option.restart or option.name not in parsed:
                    continue
                if before.get(option.name) != parsed[option.name]:
                    self.restart_pending.add(option.label)
        return {}


# -- rendering -----------------------------------------------------------

def rejoined(schema: Schema, form: dict[str, Any]) -> dict[str, Any]:
    """One value per option, out of the fields the wire actually carried.

    Three controls send something other than the option's own name: a
    duration sends an amount and a unit, a checkbox sends a hidden marker
    beside a box that sends nothing when it is unticked, and the ordered
    picker sends one box per row plus a count.

    Both the save and the re-render of a refused form have to put them back
    the same way, which is why this is a function and not a loop inside
    `Admin.save`. `page()` restores what was typed with
    `values.update(... if k in values)`, and the picker posts
    `places__slot0`, never `places`: nothing matched, so a refused save
    re-rendered the stored value and everything typed into the picker was
    gone. Retyping a form because one field was wrong is how people give up.
    """
    form = dict(form)
    for _group, option in schema:
        if option.kind == "duration":
            # A number and a unit in two fields. Put back together before
            # anything looks at them, so everything downstream sees one
            # duration and not two halves.
            amount = form.get(f"{option.name}__amount")
            unit = form.get(f"{option.name}__unit", "s")
            if amount is not None and str(amount).strip():
                form[option.name] = f"{str(amount).strip()}{unit}"
            continue
        if option.kind == "list" and f"{SLOTS}{option.name}" in form:
            # One box per row, in row order. Put back together here rather
            # than in `Option.parse`, so the parser goes on taking exactly
            # one string and the wire format stays this file's business.
            # Same split as `duration`, for the same reason.
            try:
                count = int(str(form[f"{SLOTS}{option.name}"]) or 0)
            except ValueError:
                count = 0
            picked = [str(form.get(f"{option.name}__slot{n}", "")).strip()
                      for n in range(count)]
            form[option.name] = NEWLINE.join(one for one in picked if one)
            continue
        if option.kind != "bool":
            continue
        # An unticked checkbox sends nothing at all, so the form carries a
        # hidden marker for each one. Present marker, absent box means off;
        # no marker at all means the field was not part of this request and
        # must be left alone.
        if f"{MARKER}{option.name}" in form:
            form.setdefault(option.name, "")
    return form


def overridden(option: Option) -> str:
    """The environment variable outranking this setting, if there is one.

    The order is argument, environment, file, weewx.conf, default, and this
    page writes the file. So a variable set in the deployment wins, and the
    page would otherwise accept a value, store it, and change nothing: no
    error, no warning, and a field that keeps showing what was typed while
    the process goes on using something else.

    Read straight from the environment rather than through a Settings
    instance. The page edits a file it is given the path to and holds no
    resolved settings, and building some here would answer for this process
    rather than for the one doing the archiving.
    """
    import os

    from .settings import ENV_ALIASES

    primary = "WEEWX_EVO_" + option.name.replace(".", "_").upper()
    for env_name in [primary, *[n for n, _ in ENV_ALIASES.get(option.name, ())]]:
        if os.environ.get(env_name):
            return env_name
    return ""


#: How many empty boxes are offered past what is already chosen. Three, so
#: adding one needs no script at all -- and the page still works for somebody
#: with JavaScript off, which is the whole reason the buttons only reorder.
SPARE_SLOTS = 3


def slots(option: Option, shown: Any, lang: Any = None) -> str:
    """A list of choices, in an order that is the value's order.

    Every candidate gets a row, ticked or not. What stood here was three
    empty boxes with the choices printed under them as grey text -- so a
    site with twelve places offered three, said nothing about the other
    nine, and the only way to the fourth was to save and come back. Somebody
    with a console on twelve fields had to save four times to describe their
    own installation, and nothing on the page said that would work.

    A tick sends the row, an empty tick sends nothing, and `rejoined` drops
    the gaps -- so the order is the row order and no name is repeated.
    Never a repeated name: `_form` collapses `parse_qs` with `{k: v[-1]}`,
    so `places=a&places=b` arrives as `"b"` and four picks of five are lost
    with no error anywhere. Closed alternatives therefore use a `<select>`.

    Three free rows at the end, because not every list is closed: a station
    with `extraTemp9` names it and gets it, and the tile list says so in its
    own help. A value already saved that is not among the candidates keeps
    its row and is marked, never dropped -- one unreadable file must not
    silently take a place off a published site.

    The row order *is* the value order, which is what
    `stat_tile_observations` has claimed in its own help since it was
    written ("One tile each, in this order") and could not deliver from a
    textarea.
    """
    lang = lang if lang is not None else language_defs.get("en")
    name = html.escape(option.name)
    # The text through `say`, never the value: a row is `Desert days` over
    # `desertDays`, and only the first of those is a word.
    available = [(str(value), lang.say(str(text)))
                 for value, text in option.options()]
    known = {value for value, _text in available}
    labels = dict(available)
    chosen = [line.strip() for line in str(shown or "").splitlines()
              if line.strip()]

    # Picked first, in the order they were picked; then everything else, in
    # the order the candidates came. Ticking one puts it last, which is what
    # a list read top to bottom implies.
    rows: list[tuple[str, str, bool]] = []
    for one in chosen:
        rows.append((one, labels.get(one, one), True))
    rows += [(value, text, False) for value, text in available
             if value not in chosen]

    out = []
    # Load-bearing. Empty every box and the option's own name is sent by
    # nothing, and `parse(only_present=True)` reads that as "not part of this
    # request" rather than as "cleared". This says the control was here, and
    # `Admin.save` turns "here, and empty" into an empty list.
    spare = 0 if option.closed else SPARE_SLOTS
    out.append(f'<input type="hidden" name="{SLOTS}{name}" '
               f'value="{len(rows) + spare}">')

    out.append(f'<ul class="picks" data-list="{name}">')
    for n, (value, text, ticked) in enumerate(rows):
        # The label carries the box, so the whole row is the target. A row
        # of twelve places is a row of twelve small squares otherwise.
        note = ""
        if value not in known:
            unoffered = html.escape(lang.say("not one of the ones offered"))
            note = f'<span class="alt">{unoffered}</span>'
        said = html.escape(text)
        if text != value:
            said += f' <span class="alt">{html.escape(value)}</span>'
        up = html.escape(lang.say("Move up"))
        down = html.escape(lang.say("Move down"))
        out.append(
            f'<li><label><input type="checkbox" class="pick"'
            f' name="{name}__slot{n}" value="{html.escape(value)}"'
            f'{" checked" if ticked else ""}>'
            f"<span>{said}</span></label>{note}"
            f'<button type="button" class="quiet lift" aria-label="{up}">'
            "&#9650;</button>"
            f'<button type="button" class="quiet drop" aria-label="{down}">'
            "&#9660;</button></li>")

    # Free rows, for a list that is not closed. None at all on a closed one:
    # a place that is not on the list is refused at startup, so a box to
    # type one into is a box that can only be filled in wrongly.
    label = html.escape(lang.setting(option.name, "label") or option.label)
    free = html.escape(lang.say("something not in the list"))
    for n in range(0 if option.closed else SPARE_SLOTS):
        at = len(rows) + n
        first = f' id="f-{name}"' if not rows and n == 0 else ""
        out.append(
            f'<li class="free"><input class="slot"{first}'
            f' name="{name}__slot{at}" value="" autocomplete="off"'
            f' spellcheck="false" placeholder="{free}"'
            f' aria-label="{label} {at + 1}"></li>')
    out.append("</ul>")
    if not option.closed:
        # One button, any number of rows. Three spare boxes is three per
        # save, and somebody describing twelve of anything had to save four
        # times to do it -- with nothing on the page saying that would work.
        more = html.escape(lang.say("+ another line"))
        out.append('<button type="button" class="quiet more" '
                   f'data-list="{name}">{more}</button>')
    hint = html.escape(lang.say(
        "Ticked ones are used, top to bottom. The arrows move a row."))
    out.append(f'<p class="hint">{hint}</p>')
    return "\n".join(out)


def field(option: Option, value: Any, error: str = "",
          moved: str = "", lang: Any = None) -> str:
    """One setting as a form field.

    `moved` names the file that has taken this setting over, if one has.
    Today that is only `archives.toml`: adding a second series moves the
    station name, the coordinates and the altitude onto the archive, and a
    field that keeps accepting a value nothing reads is the same failure as
    an environment variable quietly winning.

    `lang` is passed in rather than read here, and rather than kept in a
    module global. The listener answers on a thread per request; a global
    "the language being rendered" is two people on one station seeing each
    other's. English when nothing is given, which is what a narrow caller
    and every test wants.
    """
    lang = lang if lang is not None else language_defs.get("en")
    name = html.escape(option.name)
    shown = option.render(value)
    label = html.escape(lang.setting(option.name, "label") or option.label)
    # What this field depends on, for a script to fold it away. Stated on the
    # field rather than acted on here: the form is rendered once and the value
    # it depends on changes while somebody types, so the renderer cannot know.
    # Without the script every field is visible, which is the safe direction --
    # see `Option.when`.
    depends = ""
    if option.when is not None:
        on, values = option.when
        depends = (f' data-when="{html.escape(str(on))}"'
                   f' data-when-is="{html.escape(" ".join(str(v) for v in values))}"')
    out = [f'<div class="field{" bad" if error else ""}"{depends}>']
    out.append(f'<label for="f-{name}">{label}')
    if option.required:
        said = html.escape(lang.say("required"))
        out.append(f'<span class="req" title="{said}">*</span>')
    out.append("</label>")

    if option.kind == "bool":
        checked = " checked" if value else ""
        out.append(f'<input type="hidden" name="__present__{name}" value="1">')
        out.append(f'<label class="switch"><input type="checkbox" id="f-{name}" '
                   f'name="{name}" value="1"{checked}><span></span>'
                   f'<em>{lang.say("on") if value else lang.say("off")}</em></label>')
    elif option.kind == "duration":
        # A number and a unit, not a string somebody has to know the syntax
        # for. "300" in a box labelled "interval" is a question about units
        # that a form should not be asking.
        #
        # Parsed inside a try, because a page has to be able to show a value
        # it disagrees with. Two options shipped a default below their own
        # minimum, `parse` raised while rendering the field, and the whole
        # settings page answered 500 -- so the figure that caused it could
        # not be corrected from the page either. Whatever is in the file is
        # what somebody has to see in order to change it.
        try:
            seconds = option.parse(value) if value else option.default
        except Invalid:
            log.warning("%s holds %r, which it will not accept. Showing it "
                        "as it stands so it can be corrected.",
                        option.name, value or option.default)
            seconds = value if isinstance(value, (int, float)) else 0
        amount, unit = split_duration(seconds)
        units = "".join(
            f'<option value="{code}"{" selected" if code == unit else ""}>'
            f"{html.escape(lang.say(word))}</option>" for code, word in UNITS)
        said = html.escape(lang.say("unit"))
        out.append('<div class="pair">')
        out.append(f'<input type="number" id="f-{name}" name="{name}__amount" '
                   f'value="{amount}" min="0" step="1" inputmode="numeric">')
        out.append(f'<select name="{name}__unit" aria-label="{said}">'
                   f"{units}</select>")
        out.append("</div>")
    elif option.kind == "choice":
        available = option.options()
        if not available:
            none = html.escape(lang.say("nothing installed to choose from"))
            out.append(f'<input type="text" id="f-{name}" name="{name}" '
                       f'value="{html.escape(str(shown))}" '
                       f'placeholder="{none}">')
        else:
            out.append(f'<select id="f-{name}" name="{name}">')
            # Everything through `str`. A choice is usually a word, but MQTT
            # offers quality-of-service as 0, 1 and 2, and `html.escape` on an
            # int raises -- which took the settings page of any MQTT upload
            # with it, and with it the whole connection.
            # The text through `say`, the value never. A choice reads as a
            # sentence half the time ("the local network", "this machine
            # only"); the other half it is a name somebody invented, and
            # `say` hands those straight back.
            available = [(str(choice), lang.say(str(text)))
                         for choice, text in available]
            known = {choice for choice, _ in available}
            if shown and str(shown) not in known:
                # A value naming something no longer installed. Kept and
                # marked, rather than silently swapped for the first entry.
                gone = html.escape(lang.say("(not installed)"))
                out.append(f'<option value="{html.escape(str(shown))}" '
                           f'selected>{html.escape(str(shown))} '
                           f"{gone}</option>")
            for choice, text in available:
                selected = " selected" if str(shown) == choice else ""
                out.append(f'<option value="{html.escape(choice)}"{selected}>'
                           f'{html.escape(text)}</option>')
            out.append("</select>")
    elif option.kind == "list" and option.options():
        out.append(slots(option, shown, lang))
    elif option.kind == "list":
        out.append(f'<textarea id="f-{name}" name="{name}" rows="4" '
                   f'placeholder="{html.escape(lang.say(option.placeholder))}">'
                   f'{html.escape(str(shown))}</textarea>')
    else:
        kinds = {"int": "number", "float": "number", "secret": "password"}
        step = ' step="any"' if option.kind == "float" else ""
        limits = ""
        if option.minimum is not None and option.kind in ("int", "float"):
            limits += f' min="{option.minimum}"'
        if option.maximum is not None and option.kind in ("int", "float"):
            limits += f' max="{option.maximum}"'
        placeholder = lang.say(option.placeholder) if option.placeholder else (
            lang.say("unset") if option.default is None else "")
        # Suggestions rather than a dropdown, where the usual answers are
        # worth one click but an unusual one must still be typeable. `allow`
        # is the case: "private", "any", or a list nobody can enumerate. So
        # is a serial port, which is why this asks the machine as well.
        suggestions = option.offered()
        listed = f' list="l-{name}"' if suggestions else ""
        out.append(f'<input type="{kinds.get(option.kind, "text")}" id="f-{name}" '
                   f'name="{name}" value="{html.escape(str(shown))}"'
                   f'{step}{limits}{listed} placeholder="{html.escape(placeholder)}" '
                   f'autocomplete="off" spellcheck="false">')
        if suggestions:
            out.append(f'<datalist id="l-{name}">')
            for value_, text in suggestions:
                out.append(f'<option value="{html.escape(str(value_))}">'
                           f"{html.escape(lang.say(str(text)))}</option>")
            out.append("</datalist>")

    if option.unit:
        # Through `say` as well: most of these are a symbol that reads the
        # same everywhere, but a few are words ("days", "per second").
        out.append(f'<span class="unit">'
                   f"{html.escape(lang.say(option.unit))}</span>")
    if option.kind == "choice" and option.options():
        # What else could go here. A dropdown shows one thing at a time, and
        # knowing the alternatives without opening it is worth a line.
        # `str` again, and for the same reason as above: a choice is not
        # always a word. MQTT's quality of service is 0, 1 and 2.
        others = ", ".join(str(c) for c, _ in option.options()
                           if c not in ("", None) and str(c) != str(shown))
        if others:
            out.append(f'<p class="alt">{html.escape(lang.say("or:"))} {html.escape(others)}</p>')
    if error:
        out.append(f'<p class="err">{html.escape(error)}</p>')
    if option.help:
        out.append(f'<p class="help">'
                   f'{html.escape(lang.setting(option.name, "help") or option.help)}'
                   "</p>")
    beaten = overridden(option)
    if beaten:
        out.append(
            '<p class="err">' + lang.fill(
                "Saving this changes nothing while {var} is set in the "
                "environment: that outranks the configuration file. Unset "
                "it, or change it where it is set.",
                var=f"<code>{html.escape(beaten)}</code>") + "</p>")
    if moved:
        out.append(
            '<p class="err">' + lang.fill(
                "This is set per place since the second one was added, on "
                "the {link} page. Nothing reads it here.",
                link=f'<a href="./places">{html.escape(lang.say("Places"))}</a>')
            + "</p>")
    if option.restart:
        out.append('<p class="note">'
                   + html.escape(lang.say("Restarts the service when saved."))
                   + "</p>")
    out.append("</div>")
    return "\n".join(out)


def anchor(label: str) -> str:
    """A fragment name from a group label. Stable, because it is a link."""
    return "g-" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def group_html(group: Group, values: dict[str, Any],
               errors: dict[str, str], moved: str = "",
               moved_names: frozenset[str] = frozenset(),
               lang: Any = None) -> str:
    lang = lang if lang is not None else language_defs.get("en")
    plain = [o for o in group.options if not o.advanced]
    advanced = [o for o in group.options if o.advanced]
    # The anchor keeps the English. It is a link -- `#g-archive` is in the
    # address bar, in a bookmark and in whatever anybody pasted into a
    # message -- and a fragment that moves when somebody switches language
    # is one that stops working for everybody who saved it.
    out = [f'<section class="group" id="{html.escape(anchor(group.label))}">']
    out.append(f"<h3>{html.escape(lang.say(group.label))}</h3>")
    if group.help:
        out.append(f'<p class="lede">{html.escape(lang.say(group.help))}</p>')
    for option in plain:
        out.append(field(option, values.get(option.name),
                         errors.get(option.name),
                         moved if option.name in moved_names else "", lang))
    if advanced:
        # Hidden, not omitted: a setting nobody can find is one that gets
        # found by reading the source, which is worse than a longer page.
        shown = any(errors.get(o.name) for o in advanced)
        out.append(f'<details{" open" if shown else ""}>')
        out.append("<summary>" + html.escape(lang.fill(
            "{n} more, rarely needed", n=len(advanced))) + "</summary>")
        for option in advanced:
            out.append(field(option, values.get(option.name),
                             errors.get(option.name),
                             moved if option.name in moved_names else "", lang))
        out.append("</details>")
    out.append("</section>")
    return "\n".join(out)


def _kind_options(kinds: list[tuple[str, str, str]], chosen: str,
                  say: Any) -> tuple[str, str]:
    """The dropdown and the list under it, for every "add one" page.

    Six pages built these two the same way. The words in them come out of a
    registry rather than out of the markup, so each of the six had to
    remember to hand them to the language -- and one that forgets renders a
    page that is translated except for the part that says what the choices
    mean.
    """
    options = NEWLINE.join(
        f'<option value="{html.escape(kind)}"'
        f'{" selected" if chosen == kind else ""}>'
        f"{html.escape(say(label))}</option>"
        for kind, label, _summary in kinds)
    # The select holds the names; this holds what they mean. A dropdown
    # cannot carry a sentence, and the sentence is the part that helps.
    explained = "".join(
        f"<li><strong>{html.escape(say(label))}</strong>: "
        f"{html.escape(say(summary))}</li>"
        for _kind, label, summary in kinds if summary)
    return options, explained


def new_export_page(admin: Admin, error: str = "", form: dict | None = None) -> str:
    """The form that creates one. Two fields, and nothing else yet."""
    form = form or {}
    say = admin.say
    kinds = export_kind_choices()
    # Local first and chosen by default: it is the one that needs nothing
    # else installed and the one somebody adding their first export wants.
    kinds.sort(key=lambda row: row[0] != "local")
    chosen = form.get("kind") or kinds[0][0]
    options, explained = _kind_options(kinds, str(chosen), say)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<section class="group">
  <p class="lede">{html.escape(say(
     "Send files produced by a feed to a destination."))}</p>
  {problem}
  <form method="post" action="./new-export">
    <div class="field">
      <label for="f-name">{html.escape(say("Name"))}</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="site" autocomplete="off" spellcheck="false">
      <p class="help">{html.escape(say(
         "Lowercase letters, digits, - and _."))}</p>
    </div>
    <div class="field">
      <label for="f-kind">{html.escape(say("Destination"))}</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions">
      <button type="submit">{html.escape(say("Continue"))}</button>
      <a class="button quiet" href="./publishing">
        {html.escape(say("Cancel"))}</a></div>
  </form>
</section>'''


def notify_kind_choices() -> list[tuple[str, str, str]]:
    """The channels there are, from the registry rather than from a list."""
    out = []
    for kind in notify_registry.kinds():
        factory = notify_registry.DEFAULT.factory_for(kind)
        out.append((kind, getattr(factory, "label", kind),
                    notify_registry.describe(kind)))
    return out


def new_notify_page(admin: Admin, error: str = "",
                    form: dict | None = None) -> str:
    """The form that creates one. A name and a way of reaching somebody."""
    form = form or {}
    say = admin.say
    kinds = notify_kind_choices()
    # Email first: everybody has an address, and it is the one that needs
    # nothing installed anywhere.
    kinds.sort(key=lambda row: row[0] != "email")
    chosen = form.get("kind") or (kinds[0][0] if kinds else "")
    options, explained = _kind_options(kinds, str(chosen), say)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<section class="group">
  <p class="lede">{html.escape(say(
     "Send operational alerts through this channel."))}</p>
  {problem}
  <form method="post" action="./new-notify">
    <div class="field">
      <label for="f-name">{html.escape(say("Name"))}</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="mail" autocomplete="off" spellcheck="false">
      <p class="help">{html.escape(say(
         "Lowercase letters, digits, - and _."))}</p>
    </div>
    <div class="field">
      <label for="f-kind">{html.escape(say("How"))}</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions">
      <button class="button" type="submit">
        {html.escape(say("Continue"))}</button>
      <a class="button quiet" href="./publishing">
        {html.escape(say("Cancel"))}</a>
    </div>
  </form>
</section>
'''


def new_upload_page(admin: Admin, error: str = "",
                    form: dict | None = None) -> str:
    """The form that creates one. A name and a service."""
    form = form or {}
    say = admin.say
    kinds = upload_kind_choices()
    # Weather Underground first: it is what most people mean by publishing
    # their readings, and it is the one they came here to set up.
    kinds.sort(key=lambda row: row[0] != "wunderground")
    chosen = form.get("kind") or (kinds[0][0] if kinds else "")
    options, explained = _kind_options(kinds, str(chosen), say)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<section class="group">
  <p class="lede">{html.escape(say(
     "Send readings from a Place to a weather service."))}</p>
  {problem}
  <form method="post" action="./new-upload">
    <div class="field">
      <label for="f-name">{html.escape(say("Name"))}</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="wu" autocomplete="off" spellcheck="false">
      <p class="help">{html.escape(say(
         "Lowercase letters, digits, - and _."))}</p>
    </div>
    <div class="field">
      <label for="f-kind">{html.escape(say("Service"))}</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions">
      <button type="submit">{html.escape(say("Continue"))}</button>
      <a class="button quiet" href="./publishing">
        {html.escape(say("Cancel"))}</a></div>
  </form>
</section>'''


def new_forecast_page(admin: Admin, error: str = "",
                      form: dict | None = None) -> str:
    """A name and a source. The rest waits."""
    form = form or {}
    say = admin.say
    kinds = forecast_kind_choices()
    # Open-Meteo first and chosen by default: it needs no account, covers
    # anywhere, and is the one somebody adding their first forecast wants.
    kinds.sort(key=lambda row: row[0] != "open-meteo")
    chosen = form.get("kind") or (kinds[0][0] if kinds else "")
    options, explained = _kind_options(kinds, str(chosen), say)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<section class="group">
  <p class="lede">{html.escape(say("Add forecast data for a Place."))}</p>
  {problem}
  <form method="post" action="./new-forecast">
    <div class="field">
      <label for="f-name">{html.escape(say("Name"))}</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="ahead" autocomplete="off" spellcheck="false">
      <p class="help">{html.escape(say(
         "Lowercase letters, digits, - and _."))}</p>
    </div>
    <div class="field">
      <label for="f-kind">{html.escape(say("Source"))}</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions">
      <button type="submit">{html.escape(say("Continue"))}</button>
      <a class="button quiet" href="./publishing">
        {html.escape(say("Cancel"))}</a></div>
  </form>
</section>'''


def new_collector_page(admin: Admin, error: str = "",
                       form: dict | None = None) -> str:
    """A driver that runs elsewhere: a name and what it runs.

    The page says what happens next, because most of it happens elsewhere.
    Everything else on this site configures something this process runs;
    this is a process somebody else has to start, possibly on another
    machine, and creating one here does nothing visible at all. Without the
    three steps written down, the page reads as a form that had no effect.

    The name is the field that matters and the page says so, because it is
    not cosmetic here the way a feed's name is. Its packets arrive under it,
    and a station is matched on the pair (driver, identity) -- so the name
    typed here is the one to put on the Stations page, and two consoles
    reporting the same model are told apart by nothing else.

    The word "collector" is not on this page, or on any other. It is a real
    distinction and it stays in the code, but it is ours: somebody with a
    weather station has a driver, whether it listens on HTTP or asks a USB
    console every minute. What differs is where the process runs, and that
    is what the page says instead -- because that is the half that costs
    them something.
    """
    from . import collectors as collector_defs

    form = form or {}
    say = admin.say
    chosen = form.get("kind") or "weewx-driver"
    options = NEWLINE.join(
        f'<option value="{html.escape(kind)}"'
        f'{" selected" if chosen == kind else ""}>'
        f"{html.escape(say(one.label))}</option>"
        for kind, one in collector_defs.kinds().items())
    # Both kinds, from the same table the menu is built from. Written out by
    # hand, this list described the WeeWX driver and never mentioned the
    # broker -- so half of what the menu offered was unexplained, and the
    # command printed above it was the wrong one for that half.
    started = html.escape(say("Started with"))
    explained = "".join(
        f"<li><strong>{html.escape(say(one.label))}</strong>: "
        f"{html.escape(say(one.reads))} {started} "
        f"<code>weewx-evo {html.escape(one.command)}</code>.</li>"
        for one in collector_defs.kinds().values())
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""

    # What each kind wants decided before its own page exists. The kind
    # supplies it: choosing a WeeWX driver decides which fields that driver's
    # page has, and the list of drivers belongs to the add-on that runs them.
    picking = []
    for kind, one in collector_defs.kinds().items():
        choice = getattr(one, "choosing", None)
        if choice is None:
            continue
        picked = str(form.get(choice.name, ""))
        try:
            offered = list(choice.options(picked))
        except Exception:
            # A kind that cannot list what it offers must not take the page
            # with it: everything else on it still works, and the empty
            # dropdown is visible where a 500 is not.
            log.exception("the collector kind %r could not list its choices",
                          kind)
            offered = []
        picking.append(f'''
    <div class="field" data-when="kind" data-when-is="{html.escape(kind)}">
      <label for="f-{html.escape(choice.name)}">
        {html.escape(say(choice.label))}</label>
      <select id="f-{html.escape(choice.name)}"
              name="{html.escape(choice.name)}">{NEWLINE.join(
          f'<option value="{html.escape(str(value))}"'
          f'{" selected" if picked == str(value) else ""}>'
          f"{html.escape(say(str(label)))}</option>"
          for value, label in offered)}</select>
      <p class="help">{html.escape(say(choice.help))}</p>
    </div>''')
    chosen_fields = "".join(picking)

    return f'''
<section class="group">
  <p class="lede">{html.escape(say(
     "A driver for hardware that has to be read rather than heard: a "
     "cable, a USB port, a radio. It gets a process of its own, which "
     "weewx-evo starts and keeps running."))}
  </p>
  <ol class="steps">
    <li>{html.escape(say("Name the driver and choose what it runs."))}</li>
    <li>{html.escape(say("Set its hardware or broker options."))}</li>
    <li>{html.escape(say("Save it. weewx-evo starts it."))}</li>
  </ol>
  {problem}
  <form method="post" action="./new-collector">
    <div class="field">
      <label for="f-name">{html.escape(say("Name"))}</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="shed" autocomplete="off" spellcheck="false">
      <p class="help">{html.escape(say(
         "Lowercase letters, digits, - and _."))}</p>
    </div>
    <div class="field">
      <label for="f-kind">{html.escape(say("What it runs"))}</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    {chosen_fields}
    <div class="actions">
      <button type="submit">{html.escape(say("Continue"))}</button>
      <a class="button quiet" href="./system">
        {html.escape(say("Cancel"))}</a></div>
  </form>
</section>'''


def _collector_note(schema: Any, lang: Any = None) -> str:
    """How to start this driver, at the top of its own page.

    Every other page on this site configures something this process runs, so
    saving is the end of it. This one is a process somebody has to start
    somewhere else -- and its page, generated from the schema like all the
    others, said so nowhere: `Schema.help` is written into the configuration
    file as a comment and never rendered. Landing here after creating one
    meant a form with no hint that anything further was required.
    """
    from . import collectors as collector_defs

    lang = lang if lang is not None else language_defs.get("en")
    name = schema.name.split(":", 1)[-1]
    kind = ""
    for group in schema.groups:
        for option in group.options:
            if option.name == "kind":
                kind = str(option.default)
    where = lang.fill(
        "Its data appears under {link}.",
        link=f'<a href="./senders">{html.escape(lang.say("Drivers"))}</a>')
    return f'''
<section class="group">
  <h3>{html.escape(lang.say("Starting it"))}</h3>
  <p><code>{html.escape(collector_defs.start_command(kind, name))}</code></p>
  <p class="help">{where}</p>
</section>'''


def new_feed_page(admin: Admin, error: str = "",
                  form: dict | None = None) -> str:
    """Two fields: a name and a kind. The rest waits."""
    form = form or {}
    say = admin.say
    kinds = feed_kind_choices()
    chosen = form.get("kind") or (kinds[0][0] if kinds else "")
    options, explained = _kind_options(kinds, str(chosen), say)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<section class="group">
  <p class="lede">{html.escape(say(
     "Generate files from one or more Places."))}</p>
  {problem}
  <form method="post" action="./new-feed">
    <div class="field">
      <label for="f-name">{html.escape(say("Name"))}</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="metric" autocomplete="off" spellcheck="false">
      <p class="help">{html.escape(say(
         "Lowercase letters, digits, - and _."))}</p>
    </div>
    <div class="field">
      <label for="f-kind">{html.escape(say("Kind"))}</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions">
      <button type="submit">{html.escape(say("Continue"))}</button>
      <a class="button quiet" href="./publishing">
        {html.escape(say("Cancel"))}</a></div>
  </form>
</section>'''


def _where_it_lands(admin: Admin, name: str) -> str:
    """For a local export: the address its files end up at.

    Shown on the export's own page, because that is where somebody has just
    typed a directory and is wondering what to do with it.
    """
    config = admin.config()
    settings = (config.get("exports") or {}).get(name)
    if not isinstance(settings, dict) or settings.get("kind") != "local":
        return ""

    lang = admin.language
    say = admin.say
    web = config.get("web", {}) or {}
    directory = str(settings.get("directory") or "")
    # As typed, and as it actually lands. A relative path is resolved against
    # the configuration file, so `data/json` beside `/data/evo.toml` is
    # `/data/data/json` -- correct, surprising, and worth showing rather than
    # leaving somebody to find out from a 404.
    resolved = ""
    if directory and not Path(directory).is_absolute():
        resolved = str((Path(admin.path).parent / directory).resolve())
    heading = html.escape(say("Where it lands"))
    if not web.get("enabled"):
        unset = say("-- no directory set --")
        # The path goes in as text and the link comes last. A tag in the
        # middle of a sentence cuts it into runs, and the run between two of
        # them is one no translator is ever shown.
        offer = html.escape(lang.fill(
            "In {directory} on this machine. Point a web server at it, or",
            directory=resolved or directory or unset))
        turn = html.escape(say("turn the built-in one on"))
        ready = html.escape(say("and it is readable straight away."))
        return f'''
<section class="group">
  <h3>{heading}</h3>
  <p class="lede">{offer} <a href="./website">{turn}</a> {ready}</p>
</section>'''

    port = web.get("port", 8081)
    path = "/" if web.get("default") == name else f"/{html.escape(name)}/"
    host = _addresses()[0][0]
    address = f"http://{html.escape(host)}:{port}{path}"
    typed = ""
    if resolved:
        typed = " " + lang.fill(
            "(you wrote {directory}, which is relative to the settings file)",
            directory=directory)
    served = html.escape(lang.fill(
        "In {directory}{typed}, and the built-in server hands it out at",
        directory=resolved or directory, typed=typed))
    named = html.escape(say("The name in the address is this export's name."))
    return f'''
<section class="group">
  <h3>{heading}</h3>
  <p class="lede">{served} <a href="{address}">{address}</a>. {named}</p>
</section>'''


def website_summary(admin: Admin) -> str:
    """What the built-in server hands out, and at which address.

    The question this page exists to answer. Without it somebody sets a
    directory, saves, and has nowhere to click: the address is not written
    down anywhere, and neither is the fact that the path comes from the name
    of an export.
    """
    from .webserver import site_from

    config = admin.config()
    say = admin.say
    web = config.get("web", {}) or {}
    if not web.get("enabled"):
        return f'''
<section class="group">
  <h3>{html.escape(say("Nothing is being served"))}</h3>
  <p class="lede">{html.escape(say(
     "Turn the server on above and whatever a local export published "
     "becomes readable in a browser. Until then the exports still run and "
     "still write their files."))}</p>
</section>'''

    class _View:
        def __init__(self, raw):
            self.config = raw

        def get(self, key):
            return config_file.get(self.config, key)

    site = site_from(_View(config))
    port = web.get("port", 8081)
    hosts = _addresses()

    if not site.feeds:
        at = f"http://{hosts[0][0]}:{port}/"
        idle = html.escape(admin.language.fill(
            "The server is on, at {address}, and there is nothing to hand "
            "out.", address=at))
        return f'''
<section class="group">
  <h3>{html.escape(say("Serving nothing yet"))}</h3>
  <p class="lede">{idle}</p>
  <p class="lede">{html.escape(say(
     "A feed writes into its own working directory. What puts it somewhere "
     "readable is an export of kind local: choose the feed, say which "
     "directory, and it appears here under the export's own name."))}</p>
  <div class="actions"><a class="button" href="./new-export">
     {html.escape(say("Add an export"))}</a></div>
</section>'''

    rows = []
    for name in sorted(site.feeds):
        where = site.feeds[name]
        try:
            count = sum(1 for f in where.rglob("*") if f.is_file())
        except OSError:
            count = 0
        path = "/" if name == site.default else f"/{name}/"
        links = " ".join(
            f'<a href="http://{html.escape(host)}:{port}{path}">'
            f"{html.escape(host)}:{port}{path}</a>"
            for host, _what in hosts[:2])
        rows.append(
            f"<tr><td>{html.escape(name)}</td>"
            f"<td>{links}</td>"
            f"<td class='n'>{count}</td>"
            f"<td><code>{html.escape(str(where))}</code></td></tr>")

    also = ""
    if site.default:
        said = html.escape(admin.language.fill(
            "{name} is also at the address itself, without a name after it.",
            name=site.default))
        also = f"<p class='lede'>{said}</p>"

    return f'''
<section class="group">
  <h3>{html.escape(say("What is being served"))}</h3>
  <p class="lede">{html.escape(say(
     "The name in the address is the name of the export that published it. "
     "Rename the export and the address follows."))}</p>
  {also}
  <table>
    <thead><tr><th>{html.escape(say("name"))}</th>
      <th>{html.escape(say("address"))}</th>
      <th class="n">{html.escape(say("files"))}</th>
      <th>{html.escape(say("from"))}</th></tr></thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table>
</section>'''


def _addresses() -> list[tuple[str, str]]:
    """Addresses this machine can be reached at, best guess first.

    The same list `weewx-evo url` prints. A page that says `0.0.0.0` has told
    somebody nothing they can type into a browser.
    """
    import socket

    found: list[tuple[str, str]] = []
    try:
        name = socket.gethostname()
        found.append((f"{name}.local", "this machine's name"))
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.2)
        try:
            # Nothing is sent. It only asks the routing table which address
            # this machine would use to reach the outside.
            probe.connect(("192.0.2.1", 9))
            found.insert(0, (probe.getsockname()[0], "on the local network"))
        finally:
            probe.close()
    except OSError:
        pass
    found.append(("127.0.0.1", "on this machine only"))
    return found


def sub_pages(admin: Admin) -> list[str]:
    """Pages whose name carries an instance, so no fixed list can hold them.

    `tools/adminpage.py` enumerates schemas + ADD_PAGES + OWN_PAGES, and
    `plot:<name>` is in none of the three. So the chart editor -- the page
    with a delete checkbox on every row, a Remove button of its own and now
    a colour control per line -- has never been through the check that asks
    which form each button landed in. That is the check that found Save
    belonging to no form on every export, feed, upload and forecast page,
    with every tag present and every one closed.

    Nothing calls this yet: the tool still builds its own list, so the chart
    editor is still unchecked. It is here rather than in the tool because
    the page names are this file's business, and a second list of them in
    `tools/` is how the first one came to be short.
    """
    try:
        from . import adminplots

        return [f"plot:{one.name}" for one in adminplots.load(admin)]
    except Exception:
        log.debug("could not list the charts for the page list", exc_info=True)
        return []


#: The five first-level tasks. "Drivers" and not "Senders": a driver that
#: runs in its own process was reachable only through System, so setting up a
#: Vantage meant knowing that this program files it somewhere else than the
#: Ecowitt on the wifi. They are one entry, one list and one way in now.
_PRIMARY_NAV = (
    ("overview", "Overview", "./overview"),
    ("senders", "Drivers", "./senders"),
    ("places", "Places", "./places"),
    ("publishing", "Publishing", "./publishing"),
    ("system", "System", "./system"),
)


def _primary_section(active: str, schema: Schema | None) -> str:
    """Return the first-level task containing *active*."""
    if active == "overview":
        return "overview"
    if active in ("senders", "stations", "new-sender", "new-station",
                  "new-collector"):
        return "senders"
    if active in ("places", "archives", "new-place", "new-archive"):
        return "places"
    if (active in ("publishing", "charts", "new-feed", "new-export",
                   "new-upload", "new-forecast", "new-notify", "new-plot",
                   "import-plots") or active.startswith("plot:")):
        return "publishing"
    if schema is not None:
        if schema.kind in ("feed", "export", "upload", "forecast", "notify"):
            return "publishing"
        if schema.name == "website":
            return "publishing"
        # A driver's own settings belong under Drivers, wherever the process
        # runs. Its page was in System because that is where the panel was,
        # and that is what made two ways in out of one thing.
        if schema.kind in ("collector", "driver"):
            return "senders"
    return "system"


def _primary_nav(active: str, schema: Schema | None, lang: Any = None) -> str:
    """Five stable destinations, independent of configured instance count."""
    lang = lang if lang is not None else language_defs.get("en")
    current = _primary_section(active, schema)
    links = []
    for key, label, href in _PRIMARY_NAV:
        here = ' aria-current="page"' if key == current else ""
        links.append(f'<a class="primary-nav-link" href="{href}"{here}>'
                     f'{html.escape(lang.say(label))}</a>')
    return "".join(links)


def _try_it(schema: Schema, lang: Any, lede: str, button: str) -> str:
    """The "try this before trusting it" section, for one kind of thing.

    Five kinds had this written out five times, and the words differ by one
    sentence and one button. Written out, the sixth one to be added is the
    one that misses the language.
    """
    return f'''
<section class="group">
  <h3>{html.escape(lang.say("Try it"))}</h3>
  <p class="lede">{html.escape(lang.say(lede))}</p>
  <form method="post" action="./{html.escape(schema.name)}/test">
    <div class="actions">
      <button type="submit">{html.escape(lang.say(button))}</button></div>
  </form>
</section>'''


def _removal(schema: Schema, lang: Any, lede: str, question: str) -> str:
    """The delete section. `question` is what the browser asks first.

    Escaped twice, in that order: the question is a JavaScript string inside
    an HTML attribute, so an apostrophe has to survive both. A German line
    with one in it -- or a feed somebody called `bob's` -- would otherwise
    close the string early and leave a button that does nothing.
    """
    name = schema.name.split(":", 1)[-1]
    asked = lang.fill(question, name=name)
    asked = html.escape(asked.replace(chr(92), chr(92) * 2)
                        .replace("'", chr(92) + "'"), quote=True)
    return f'''
<section class="group danger">
  <h3>{html.escape(lang.say("Remove"))}</h3>
  <p class="lede">{html.escape(lang.say(lede))}</p>
  <form method="post" action="./{html.escape(schema.name)}/remove"
        onsubmit="return confirm('{asked}')">
    <div class="actions"><button class="warn" type="submit">
      {html.escape(lang.say("Remove"))}</button></div>
  </form>
</section>'''


def page(admin: Admin, active: str, errors: dict[str, str] | None = None,
         message: str = "", form: dict[str, Any] | None = None) -> bytes:
    errors = errors or {}
    # Once per page, not once per field: `Admin.language` reads the file, and
    # a form with a hundred fields would read it a hundred times.
    lang = admin.language
    schema = next((s for s in admin.schemas if s.name == active), None)
    adding = schema is None and active in ADD_PAGES and active not in (
        "new-plot", "import-plots")
    charting = schema is None and (active in ("new-plot", "import-plots")
                                   or active.startswith("plot:"))
    standing = schema is None and active in OWN_PAGES
    if schema is None and not adding and not charting and not standing:
        # The overview, not the first form. Somebody arriving here almost
        # never wants to change a value; they want to know whether it is
        # working. The forms are one click away and always were.
        active, standing = "overview", True

    # After a failed save, show what was typed rather than what is stored --
    # retyping a form because one field was wrong is how people give up.
    values = dict(admin.values(schema)) if schema else {}
    if form and schema:
        # Through the same reassembly the save does. A duration and the
        # ordered picker post under names of their own, so matching the raw
        # form against `values` matched neither, and both came back as what
        # is stored rather than as what was typed.
        values.update({k: v for k, v in rejoined(schema, form).items()
                       if k in values})

    # The pages whose content is a wide table rather than a form. Named
    # here: deciding it from the rendered body would mean a page changing
    # width depending on how many stations somebody happens to have.
    #
    # Three states, not two. `wide` is still a reading width -- a table of
    # stations is read across, and 72rem is where a line stops being one.
    # The live table is a *database* table with twelve columns of its own
    # choosing, and capping it means empty screen on the right and a
    # scrollbar on the left at the same time. There is no reading-width
    # argument for a row of a database.
    wide = ""
    if active in ("stations", "senders", "overview", "archives", "places",
                  "system", "publishing"):
        wide = "wide"
    elif active == "live":
        wide = "full"

    # The primary navigation is a product map, not an inventory. Configured
    # feeds, collectors and drivers live on their section pages, so adding one
    # can never make the navigation longer or move another destination.
    nav = _primary_nav(active, schema, lang)

    if charting:
        if active == "new-plot":
            body = [adminplots.new(admin, admin.columns(),
                                   errors.get("", ""), form)]
        elif active == "import-plots":
            body = [adminplots.importer(admin, message, errors.get("", ""),
                                        form)]
        else:
            body = [adminplots.edit(admin, active.split(":", 1)[1],
                                    admin.columns(), errors, form)]
    elif active == "search":
        body = [adminsearch.results(admin, (form or {}).get("q", ""))]
    elif active == "setup" or active.startswith("setup/"):
        # The wizard, which renders its own step. `setup/place` and the rest
        # are one page with a step in the path rather than five pages: the
        # progress bar has to know where it is, and a page that does not
        # know cannot draw one.
        step = active.split("/", 1)[1] if "/" in active else ""
        body = [adminsetup.page(admin, step, errors.get("", ""), form,
                                said=message)]
    elif active in ("archives", "places"):
        # The one standing page that takes the form back. A refused save
        # re-renders the list, and without this everything typed into the
        # row is gone -- retyping a form because one field was wrong is how
        # people give up. The other five take no form yet and are not given
        # one they would ignore.
        body = [adminarchives.overview(admin, message, errors.get("", ""),
                                       form)]
    elif standing:
        pages = {"overview": adminhome,
                 "stations": adminstations, "senders": adminstations,
                 "publishing": adminpublish, "system": adminsystem,
                 "charts": adminplots, "quality": adminquality,
                 "live": adminlive, "addons": adminaddons}
        body = [pages[active].overview(admin, message, errors.get("", ""))]
    elif active in ("new-archive", "new-place"):
        body = [adminarchives.new(admin, errors.get("", ""), form)]
    elif active in ("new-station", "new-sender"):
        made = (form or {}).get("_made")
        if made is None and (form or {}).get("learn"):
            # Coming back to a station that is still waiting for its console.
            made = adminstations.load(admin).by_name(str(form["learn"]))
        body = [adminstations.new(admin, errors.get("", ""), form, made=made)]
    elif adding:
        maker = {"new-feed": new_feed_page, "new-upload": new_upload_page,
                 "new-export": new_export_page,
                 "new-collector": new_collector_page,
                 "new-notify": new_notify_page,
                 "new-forecast": new_forecast_page}[active]
        body = [maker(admin, errors.get("", ""), form)]
    else:
        # Place-owned settings live in archives.toml from the first Place.
        # The central schema keeps the old names for file compatibility, but
        # this form must never present a second authority for them.
        moved, moved_names = "", frozenset()
        try:
            adminarchives.load(admin)
            moved = str(adminarchives.path_for(admin))
            moved_names = frozenset(archive_defs.FROM_SETTINGS)
        except Exception:
            log.debug("could not read the archives for the settings page",
                      exc_info=True)
        jump = "".join(
            f'<a href="#{html.escape(anchor(g.label))}">'
            f"{html.escape(lang.say(g.label))}</a>" for g in schema.groups)
        # Where this thing sits in the chain, first. A page of FTP settings
        # with no hint of which feed it sends is one nobody can check
        # without opening a second tab.
        body = [adminpublish.context(admin, active)]
        if schema.kind == "collector":
            body.append(_collector_note(schema, lang))
        sections = html.escape(lang.say("Sections"))
        body.append(f'<nav class="jump" aria-label="{sections}">{jump}</nav>')
        body += [group_html(g, values, errors, moved, moved_names, lang)
                 for g in schema.groups]

    # An export gets two more buttons: try the destination, and delete it.
    # Testing is worth a great deal here -- a wrong password found now beats
    # one found at the next archive interval, in a log nobody is reading.
    extra = ""
    if schema is not None and schema.name == "website":
        extra = website_summary(admin)
    if schema is not None and schema.kind == "feed" and not admin.read_only:
        extra = _removal(schema, lang, "Existing files remain. "
                         "Linked exports stop.", "Remove the feed {name}?")

    if schema is not None and schema.kind == "forecast" and not admin.read_only:
        extra += _try_it(schema, lang, "Fetch once without storing.",
                         "Fetch once")
        extra += _removal(schema, lang, "Cached forecasts remain until "
                          "cleanup.", "Remove the forecast source {name}?")

    if schema is not None and schema.kind == "upload" and not admin.read_only:
        extra += _try_it(schema, lang, "Check the account without publishing.",
                         "Test the account")
        extra += _removal(schema, lang, "Already published readings remain.",
                          "Remove the upload {name}?")

    # Its own, because what removal means here is different: this is a
    # process this one does not run, so nothing is stopped. The route and
    # `remove_collector` were both here already and nothing called them --
    # one could be created from the page and only ever removed by editing
    # the file.
    if schema is not None and schema.kind == "collector" and not admin.read_only:
        extra += _removal(schema, lang, "Stops it and takes its endpoint "
                          "away. Readings already recorded stay.",
                          "Remove the driver {name}?")

    if schema is not None and schema.kind == "export" and not admin.read_only:
        extra += _where_it_lands(admin, schema.name.split(":", 1)[-1])
        extra += _try_it(schema, lang,
                         "Connects and looks, without sending anything.",
                         "Test the connection")
        extra += _removal(schema, lang, "Remote files remain.",
                          "Remove the export {name}?")

    banner = ""
    if errors and charting and "" not in errors:
        banner = ('<div class="banner warn">'
                  + html.escape(lang.say("Saved.")) + " "
                  + html.escape("; ".join(errors.values())) + "</div>")
    elif errors:
        general = errors.get("")
        if general:
            banner = f'<div class="banner bad">{html.escape(general)}</div>'
        else:
            # Named, not counted. The message is also printed beside each
            # field, but a settings page is long and "3 setting(s) need
            # looking at" leaves somebody scrolling for the red one.
            labels = {option.name:
                      lang.setting(option.name, "label") or option.label
                      for _group, option in (schema or ())}
            named = ", ".join(html.escape(labels.get(where, where))
                              for where in errors if where)
            banner = ('<div class="banner bad">'
                      + lang.fill("Nothing was saved. Look at {fields}.",
                                  fields=named) + "</div>")
    elif message:
        banner = f'<div class="banner ok">{html.escape(message)}</div>'

    restart = ""
    if admin.restart_pending:
        items = ", ".join(sorted(html.escape(x) for x in admin.restart_pending))
        # What it actually does, which is nothing: exports and uploads are
        # picked up while running, these are not. Saying "restarting" when
        # nothing restarts sends somebody looking for a service that is
        # already up, and the setting they changed still is not in effect.
        restart = ('<div class="banner warn">' + lang.fill(
            "Saved, and waiting for a restart to take effect: {settings}.",
            settings=items) + "</div>")

    # `standing` too: the stations page is a list of rows with a form on
    # each -- adopt, ignore, remove. Wrapped in the save form those are nested
    # forms, which HTML does not have: the browser drops the inner <form>,
    # keeps its </form>, and the outer one closes early. The buttons then
    # belong to no form at all, or to the wrong one. Same failure the exports
    # and feeds had, which is what `tools/admin_page_test.js` was written for.
    own_form = adding or charting or standing
    if charting:
        heading = (lang.say("Add a chart") if active == "new-plot"
                   else lang.say("Import charts") if active == "import-plots"
                   # The chart's own name, which is the operator's word.
                   else lang.fill("Chart: {name}",
                                  name=active.split(":", 1)[1]))
    else:
        # Named per page rather than "everything else is an export". Two more
        # add-pages arrived after this was written and both said "Add an
        # export" over a form that was nothing of the sort.
        headings = {"new-feed": "Add a feed", "new-export": "Add an export",
                    "new-upload": "Add an upload",
                    "new-collector": "Add a driver",
                    "new-forecast": "Add a forecast",
                    "new-notify": "Add a notification channel",
                    "new-station": "Add a driver",
                    "new-sender": "Add a driver",
                    "stations": "Drivers", "senders": "Drivers",
                    "live": "Live database",
                    "new-archive": "Add a place", "new-place": "Add a place",
                    "overview": "Overview", "system": "System",
                    "publishing": "Publishing",
                    "charts": "Charts", "quality": "Sensor checks",
                    "addons": "Add-ons",
                    "search": "Find a setting"}
        # The compatibility route and the canonical route render the same
        # Place list and therefore share its title.
        if active in ("archives", "places"):
            heading = adminarchives.title_for(admin)
        else:
            # A schema's label is the operator's own name for an instance
            # ("Feed: site") as often as it is one of ours, so it goes
            # through `say` too and simply comes back unchanged when nobody
            # has translated a name they invented.
            heading = lang.say(schema.label if schema
                               else headings.get(active, "Settings"))

    # The pages that render themselves write their own <h2>, and it carries
    # more than a name: "Publishing" with a line under it saying what a feed
    # and an export each do. Printing the shell's as well gave two headings,
    # the first of them a bare repetition of the second.
    return _PAGE.format(
        wide=wide,
        # The product name beside it is not translated: it is what the thing
        # is called, in every language, and on the tin.
        brand=html.escape(lang.say("Administration")),
        menu=html.escape(lang.say("Menu")),
        nav_label=html.escape(lang.say("Primary")),
        title=html.escape(heading),
        heading="" if standing else f"<h2>{html.escape(heading)}</h2>",
        find=adminsearch.box(lang=lang),
        body_form_open="" if own_form else f'<form method="post" action="./{html.escape(active)}">',
        body_form_close="" if own_form else "</form>",
        # After the save form closes, never inside it. `extra` is Try it and
        # Remove, and each of those is a form of its own -- and HTML has no
        # nested forms. A browser drops the inner `<form>` and keeps its
        # `</form>`, which closes the outer one early: the Save button then
        # belongs to no form at all and does nothing when clicked, while Try
        # it silently submits a save instead. Every export, feed, upload and
        # forecast page was like that. Reading the HTML as text cannot see
        # it -- every tag is there and every one is closed -- so
        # `tools/adminpage.py` parses the page and asks which form each
        # button ended up in.
        extra=extra,
        nav=nav,
        banner=banner + restart,
        body="\n".join(body),
        action=html.escape(schema.name if schema else active),
        readonly=('<p class="banner warn">'
                  + html.escape(lang.say("Read-only.")) + "</p>"
                  if admin.read_only else ""),
        save="" if admin.read_only or own_form else
             '<div class="savebar" data-savebar>'
             f'<button type="submit">{html.escape(lang.say("Save changes"))}'
             '</button><span class="save-state" aria-live="polite">'
             f'{html.escape(lang.say("No changes"))}</span>'
             '</div>',
        file=html.escape(str(admin.path)),
    ).encode("utf-8")


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title} - weewx-evo admin</title>
<style>
  :root {{
    --bg: #fbfaf8; --panel: #fff; --line: #e5e1da; --ink: #1d1b18;
    --dim: #6f6a62; --accent: #2f6f4e; --warn: #9a5b1e; --bad: #97321f;
    --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    /* The browser draws radios, checkboxes and number spinners itself, and
       it draws them light unless told. Eight light radios on the dark
       panel of the colour palette, which is the one control on that page. */
    color-scheme: light;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #17161a; --panel: #1f1e23; --line: #322f38; --ink: #eceaf0;
      --dim: #9a94a3; --accent: #79c79b; --warn: #e0a86a; --bad: #e08a76;
      color-scheme: dark;
      /* Consumed by the raw-upload box and defined nowhere, so it fell to
         its literal fallback on both themes. */
      --sunk: #00000033;
    }}
  }}
  /* Every link in the page body was the browser's own colour: #0000ee in
     light, #9e9eff in dark. The second is the one that gives a dark theme
     away -- a lilac link on a green-accented panel, on every card of the
     overview. Colour, not the browser's; underline only on hover, because
     "Add a feed" beside "Add an export" beside "Add an upload" underlined
     three times is a fence. */
  main a {{ color: var(--accent); text-decoration: none; }}
  main a:hover {{ text-decoration: underline; }}
  main a:focus-visible {{ outline: 2px solid var(--accent);
      outline-offset: 2px; border-radius: 3px; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  .shell {{ display: grid; grid-template-columns: 15rem 1fr; min-height: 100vh; }}
  @media (max-width: 48rem) {{
    .shell {{ grid-template-columns: 1fr; }}
    /* One column means the whole sidebar comes before the page. It is
       thirteen entries plus a search box, so on a phone the answer to
       "is it recording" was below eight hundred pixels of navigation.
       Capped and scrollable: the top of the page is on the first screen,
       and the navigation is still all there. */
    nav {{ max-height: 40vh; overflow-y: auto;
           border-right: 0; border-bottom: 1px solid var(--line); }}
  }}

  nav {{ background: var(--panel); border-right: 1px solid var(--line);
        padding: 1.25rem 1rem; }}
  nav h1 {{ font-size: 1rem; margin: 0 0 1.25rem; font-weight: 600; }}
  nav h1 small {{ display: block; color: var(--dim); font-weight: 400;
                 font-size: .75rem; margin-top: .15rem; }}
  .navhead {{ font-size: .6875rem; text-transform: uppercase; color: var(--dim);
             letter-spacing: .06em; margin: 1.25rem 0 .4rem; font-weight: 600; }}
  .navhead:first-of-type {{ margin-top: 0; }}
  .navempty {{ font-size: .75rem; color: var(--dim); margin: 0 0 .4rem; }}
  nav a {{ display: block; padding: .35rem .6rem; margin: 0 -.6rem;
          color: var(--ink); text-decoration: none; border-radius: .3rem;
          font-size: .875rem; }}
  nav a:hover {{ background: color-mix(in srgb, var(--ink) 6%, transparent); }}
  nav a[aria-current] {{ background: color-mix(in srgb, var(--accent) 15%, transparent);
                        font-weight: 600; }}

  /* 46rem is a reading measure, and most of these pages are forms and
     prose that want one. The station page is a table five columns wide, and
     holding it to a paragraph's width made every cell wrap: "LAST VALUE" ran
     into the heading beside it and a field name broke across two lines. */
  main {{ padding: 1.75rem 1.5rem 5rem; max-width: 46rem;
          /* A grid item's default minimum is its content, so a 32-character
             identity in a table made the whole page scroll sideways on a
             phone. */
          min-width: 0; }}
  main.wide {{ max-width: 72rem; }}
  /* And the live table, which is a database table rather than something to
     read across: it takes the window. Capped it would leave the screen empty
     on the right and scrolling on the left at the same time. */
  main.full {{ max-width: none; }}
  /* A table wider than the phone scrolls inside its own card. The page
     itself never does: a horizontal scrollbar on the body hides content
     behind a gesture nobody performs on a settings page. */
  section.group {{ overflow-x: auto; }}
  h2 {{ font-size: 1.375rem; margin: 0 0 1.25rem; letter-spacing: -.01em; }}
  h3 {{ font-size: .9375rem; margin: 0 0 .2rem; }}
  .lede {{ color: var(--dim); font-size: .875rem; margin: 0 0 1rem; }}

  .banner {{ padding: .7rem .9rem; border-radius: .4rem; margin-bottom: 1.25rem;
            font-size: .875rem; border: 1px solid; }}
  .banner.ok {{ border-color: var(--accent);
               background: color-mix(in srgb, var(--accent) 12%, transparent); }}
  .banner.bad {{ border-color: var(--bad);
                background: color-mix(in srgb, var(--bad) 12%, transparent); }}
  .banner.warn {{ border-color: var(--warn);
                 background: color-mix(in srgb, var(--warn) 12%, transparent); }}

  .group {{ background: var(--panel); border: 1px solid var(--line);
           border-radius: .5rem; padding: 1.1rem 1.2rem; margin-bottom: 1rem; }}
  .field {{ margin: 1.1rem 0 0; }}
  .field:first-of-type {{ margin-top: .9rem; }}
  .field.bad input, .field.bad select, .field.bad textarea {{
    border-color: var(--bad); }}
  label {{ display: block; font-size: .875rem; font-weight: 500;
          margin-bottom: .25rem; }}
  .req {{ color: var(--bad); margin-left: .15rem; }}
  input[type=text], input[type=number], input[type=password], select, textarea {{
    width: 100%; padding: .4rem .55rem; font: inherit; font-size: .875rem;
    color: var(--ink); background: var(--bg);
    border: 1px solid var(--line); border-radius: .3rem; }}
  textarea {{ font-family: var(--mono); font-size: .8125rem; resize: vertical; }}
  input:focus, select:focus, textarea:focus {{ outline: 2px solid var(--accent);
    outline-offset: -1px; }}
  .unit {{ font-size: .8125rem; color: var(--dim); margin-left: .4rem; }}
  .help {{ font-size: .8125rem; color: var(--dim); margin: .3rem 0 0; }}
  /* The boxes an add-on reads, under its summary. Set apart because it is a
     different kind of line: the summary is a sentence somebody wrote, this
     is a list of model names being scanned for one of them. */
  .help.hardware {{ font-size: .78125rem; margin-top: .2rem;
                   border-left: 2px solid var(--line); padding-left: .5rem; }}
  .alt {{ font-size: .78125rem; color: var(--dim); margin: .25rem 0 0;
         font-family: var(--mono); }}
  .pair {{ display: flex; gap: .5rem; }}
  .pair input {{ flex: 0 0 7rem; }}
  .pair select {{ flex: 1; }}
  .note {{ font-size: .78125rem; color: var(--warn); margin: .25rem 0 0; }}
  .err {{ font-size: .8125rem; color: var(--bad); margin: .3rem 0 0;
         font-weight: 500; }}

  .switch {{ display: inline-flex; align-items: center; gap: .5rem;
            font-weight: 400; cursor: pointer; }}
  .switch input {{ position: absolute; opacity: 0; width: 0; }}
  .switch span {{ width: 2.35rem; height: 1.3rem; border-radius: 1rem;
                 background: var(--line); position: relative; transition: .15s; }}
  .switch span::after {{ content: ""; position: absolute; top: .175rem;
    left: .2rem; width: .95rem; height: .95rem; border-radius: 50%;
    background: var(--panel); transition: .15s; }}
  .switch input:checked + span {{ background: var(--accent); }}
  .switch input:checked + span::after {{ transform: translateX(1.05rem); }}
  .switch input:focus-visible + span {{ outline: 2px solid var(--accent);
    outline-offset: 2px; }}
  .switch em {{ font-style: normal; font-size: .8125rem; color: var(--dim); }}

  details {{ margin-top: 1.1rem; border-top: 1px solid var(--line);
            padding-top: .6rem; }}
  summary {{ cursor: pointer; font-size: .8125rem; color: var(--dim); }}

  .actions {{ display: flex; align-items: center; gap: .9rem; flex-wrap: wrap;
             margin-top: 1.25rem; }}
  /* The chart pages. Written by hand rather than generated, because a plot
     is a record with a list inside it and the form generator does one named
     value at a time. */
  .navgroup {{ margin: 0 0 .1rem; }}
  .navgroup > summary {{ cursor: pointer; list-style: none; padding: .3rem .6rem;
      margin: 0 -.6rem; color: var(--dim); font-size: .8125rem;
      border-radius: .3rem; display: flex; justify-content: space-between; }}
  .navgroup > summary::-webkit-details-marker {{ display: none; }}
  .navgroup > summary:hover {{ background: color-mix(in srgb, var(--ink) 6%, transparent);
      color: var(--ink); }}
  form.find {{ margin: 0 0 1.25rem; }}
  form.find input {{ width: 100%; padding: .4rem .6rem; font-size: .8125rem;
      border: 1px solid var(--line); border-radius: .35rem;
      background: var(--bg); color: var(--ink); }}
  form.find input:focus {{ outline: 2px solid var(--accent);
      outline-offset: -1px; }}

  nav a .count {{ float: right; font-variant-numeric: tabular-nums;
                  font-size: .75rem; color: var(--dim); font-weight: 400;
                  margin-left: .5rem; }}
  nav a[aria-current] .count {{ color: var(--ink); }}
  .navgroup > summary .count {{ font-variant-numeric: tabular-nums;
      opacity: .65; }}
  .navgroup[open] > summary {{ color: var(--ink); font-weight: 500; }}
  nav a.sub {{ padding-left: 1.1rem; font-size: .8125rem; }}
  /* The drivers nobody uses. A line that says how many, and the same
     indentation as anything else nested under a section. */
  details.more > summary {{ padding: .35rem 0; font-size: .8125rem;
      color: var(--dim); cursor: pointer; list-style: none; }}
  details.more > summary::before {{ content: "+ "; }}
  /* U+2212, written as an escape: a hyphen is narrower than the "+" above
     it and the marker jumps sideways when the section opens. */
  details.more[open] > summary::before {{ content: "\u2212 "; }}
  details.more > summary::-webkit-details-marker {{ display: none; }}
  details.more > summary:hover {{ color: var(--ink); }}
  details.more > a {{ padding-left: 1.1rem; font-size: .8125rem; }}
  .row {{ display: flex; flex-wrap: wrap; gap: 1rem 1.4rem; margin-bottom: 1rem; }}
  .row > label {{ flex: 1 1 13rem; display: block; font-size: .8125rem;
      color: var(--dim); }}
  .row.narrow > label {{ flex: 0 1 9rem; }}
  .row > label > input:not([type=checkbox]), .row > label > select {{
      display: block; width: 100%; margin-top: .25rem; }}
  .row > label.tick {{ flex: 1 1 100%; color: var(--ink); }}
  .row > label.tick > input {{ margin-right: .4rem; }}
  .row input[type=color] {{ padding: 0; height: 2.1rem; width: 3rem;
      display: inline-block; }}
  /* A caption over a group of controls is a legend, never a label: a label
     with no `for` claims the first control inside it, so clicking the word
     would tick the first radio of a palette or open a colour picker. */
  fieldset.colourfield {{ border: 0; padding: 0; margin: 0; min-width: 0; }}
  fieldset.colourfield > legend {{ padding: 0; font-size: .8125rem;
      color: var(--dim); }}
  .row > fieldset.colourfield {{ flex: 1 1 13rem; }}
  .row > label > textarea {{ display: block; width: 100%; margin-top: .25rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: .8125rem; resize: vertical; }}
  .row > label > input[type=file] {{ display: block; margin-top: .35rem;
      font-size: .8125rem; }}
  details > summary {{ cursor: pointer; color: var(--dim); font-size: .8125rem;
      margin: .2rem 0 .6rem; }}
  ul.kinds {{ list-style: none; margin: .5rem 0 0; padding: 0;
      font-size: .8125rem; color: var(--dim); }}
  ul.kinds li {{ margin-bottom: .35rem; line-height: 1.5; }}
  ul.kinds strong {{ color: var(--ink); font-weight: 500; }}
  /* Numbered, unlike ul.kinds: these are in order and the order is the
     point -- the third step happens on another machine, and a reader who
     takes them for alternatives leaves the collector unstarted. */
  ol.steps {{ margin: .5rem 0 1rem; padding-left: 1.3rem;
      font-size: .8125rem; color: var(--dim); }}
  ol.steps li {{ margin-bottom: .35rem; line-height: 1.5; }}
  ol.steps strong {{ color: var(--ink); font-weight: 500; }}
  /* The stages of setting up one piece of hardware. Numbered on the outside
     so a stage that holds a form is still numbered: a marker inside a list
     item sits beside the first line of it, and the first line here is a
     heading with a table under it. */
  ol.wizard {{ margin: .8rem 0 0; padding-left: 1.6rem; }}
  ol.wizard > li.stage {{ margin-bottom: 1.4rem; padding-left: .3rem; }}
  ol.wizard > li.stage::marker {{ color: var(--dim); font-weight: 500; }}
  ol.wizard > li.stage > h4 {{ margin-top: 0; }}
  a.button {{ display: inline-block; text-decoration: none; }}
  .hint {{ display: block; color: var(--dim); font-size: .75rem;
      margin-top: .25rem; line-height: 1.4; }}
  fieldset.line {{ border: 1px solid var(--line); border-radius: .4rem;
      padding: .8rem 1rem .2rem; margin: 0 0 .8rem; }}
  fieldset.line > legend {{ font-size: .8125rem; padding: 0 .35rem;
      color: var(--ink);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  fieldset.line.add {{ border-style: dashed; }}
  h4 {{ font-size: .875rem; margin: 1.4rem 0 .6rem; }}
  .ok {{ font-size: .8125rem; color: var(--accent); margin: .3rem 0 .8rem; }}
  nav a.add {{ color: var(--dim); font-size: .8125rem; margin-top: .2rem; }}
  nav a.add:hover {{ color: var(--ink); }}
  .group.danger {{ border-color: color-mix(in srgb, var(--bad) 40%, var(--line)); }}
  button.warn {{ background: var(--bad); }}
  form + form {{ margin-top: 0; }}
  button {{ font: inherit; font-size: .875rem; font-weight: 500;
           padding: .45rem 1.2rem; border-radius: .3rem; cursor: pointer;
           color: #fff; background: var(--accent); border: 1px solid transparent; }}
  button:hover {{ filter: brightness(1.08); }}
  .hint {{ font-size: .8125rem; color: var(--dim); }}

  /* -- the overview -------------------------------------------------- */

  /* Wide enough for "12 345 packets, 45.6 MB" without wrapping, and as many
     across as the window allows. Not a breakpoint: the number of cards grows
     with what somebody has configured, and a fixed column count would be one
     more thing to keep in step with it. */
  .cards {{ display: grid; gap: 1rem; margin-top: 1.25rem;
            grid-template-columns: repeat(auto-fit, minmax(21rem, 1fr)); }}
  .card {{ border: 1px solid var(--line); border-radius: .5rem;
           padding: .85rem 1rem 1rem; background: var(--panel); }}
  .card h3 {{ margin: 0 0 .5rem; font-size: .8125rem; font-weight: 600;
              text-transform: uppercase; letter-spacing: .04em;
              color: var(--dim); }}
  .card .navempty {{ margin: 0; }}
  .cardlink {{ margin: .6rem 0 0; font-size: .8125rem; }}
  /* `table-layout: fixed` and a min-width of zero on the card: without
     both, one long path in one cell widened the table past the grid track
     and put a horizontal scrollbar under the whole page. */
  .card {{ min-width: 0; }}
  table.chain {{ width: 100%; border-collapse: collapse;
                 table-layout: fixed; }}
  table.chain td {{ padding: .3rem 0; vertical-align: baseline;
                    border-top: 1px solid var(--line); font-size: .875rem;
                    overflow-wrap: anywhere; }}
  table.chain tr:first-child td {{ border-top: 0; }}
  table.chain td:first-child {{ font-weight: 600; padding-right: .5rem;
                                width: 36%; overflow-wrap: normal;
                                text-overflow: ellipsis; overflow: hidden;
                                white-space: nowrap; }}
  /* With room for it, the name is worth more than the ellipsis: an archive
     called "Kirchdorf an der Amper" read "Kirchdorf an d..." on a card with
     four empty centimetres beside it. */
  main.wide table.chain td:first-child {{ width: 44%; }}
  /* The age is what the eye goes to, so it is aligned and monospaced: a
     column of "12 s ago" and "4 h ago" compares at a glance, the same
     strings ragged do not. */
  table.chain td.when {{ text-align: right; white-space: nowrap;
                         font-variant-numeric: tabular-nums;
                         color: var(--dim); font-size: .8125rem; }}
  /* The last day, as a shape. Faint, because it is context and not the
     number -- a glance should land on the age first. */
  tr.sparkrow td {{ border-top: 0; padding: 0 0 .35rem; }}
  svg.spark {{ display: block; width: 100%; height: 22px;
               fill: color-mix(in srgb, var(--accent) 55%, transparent); }}
  /* The same idea one row down: what one raw reading has done for the
     last few hours, beside its current value. A separate class from
     `.spark` above, which is full width and filled -- in a table cell
     that would stretch to the column and swallow the number. */
  svg.trace {{ display: inline-block; vertical-align: middle;
               margin-left: .5rem; color: var(--dim); opacity: .8; }}

  .banner.warn ul {{ margin: .4rem 0 0; padding-left: 1.1rem;
                     font-size: .875rem; }}
  .banner.warn li {{ margin: .25rem 0; }}
  nav a.home {{ font-weight: 600; margin-bottom: .5rem; }}

  /* -- long forms ----------------------------------------------------- */

  /* Seven groups of settings is a page four thousand pixels tall, and the
     only way to the seventh was scrolling past the other six. */
  nav.jump {{ display: flex; flex-wrap: wrap; gap: .3rem;
              margin: 0 0 1.25rem; padding-bottom: .9rem;
              border-bottom: 1px solid var(--line); }}
  /* `nav a` is the sidebar's rule and it applies here too -- this is a
     <nav> as well. Two of its declarations had to be undone: the negative
     side margin, which made each chip lap over the last letter of the one
     before it ("Statior", "Archiv"), and the panel background and border
     that put a white box around the whole strip. */
  nav.jump {{ background: none; border-right: 0; padding: 0; }}
  nav.jump a {{ flex: 0 0 auto; white-space: nowrap; margin: 0;
                font-size: .8125rem; padding: .25rem .6rem; border-radius: 1rem;
                color: var(--dim); text-decoration: none;
                border: 1px solid var(--line); background: var(--panel); }}
  nav.jump a:hover {{ color: var(--ink); border-color: var(--dim); }}
  .group, .flow {{ scroll-margin-top: 1rem; }}
  nav.jump a .count {{ float: none; margin-left: .35rem; }}

  /* And the Save button was at the bottom of all of it. Sticky rather than
     repeated: one button, always reachable, and it still belongs to the one
     form. */
  .savebar {{ position: sticky; bottom: 0; display: flex; align-items: center;
              gap: .75rem; margin: 1.5rem -1.5rem -5rem; padding: .8rem 1.5rem;
              background: color-mix(in srgb, var(--bg) 92%, transparent);
              backdrop-filter: blur(6px);
              border-top: 1px solid var(--line); }}
  .savebar .hint {{ font-size: .75rem; color: var(--dim); }}
  @media (max-width: 48rem) {{ .savebar {{ margin-left: -1rem;
                                           margin-right: -1rem; }} }}

  /* -- publishing: the flow ------------------------------------------ */

  /* Not a second `.actions` rule. There was one, 170 lines below the first,
     and its `margin: 0 0 1.25rem` reset the top margin on all 35 action
     bars -- so a row of buttons sat against the paragraph above it
     everywhere, and the rule that said otherwise looked correct. */
  .actions.lead {{ margin-top: 0; margin-bottom: 1.25rem; }}
  a.button {{ display: inline-block; padding: .4rem .8rem; border-radius: .35rem;
              background: var(--accent); color: #fff; text-decoration: none;
              font-size: .8125rem; font-weight: 600; }}
  a.button.quiet {{ background: transparent; color: var(--ink);
                    border: 1px solid var(--line); font-weight: 500; }}
  .sectionhead {{ margin: 2rem 0 .3rem; font-size: .8125rem;
                  text-transform: uppercase; letter-spacing: .04em;
                  color: var(--dim); }}
  /* One block per feed. The exports sit inside its border rather than
     beside it, because "inside" is the claim being made: this feed is what
     they publish. */
  .flow {{ border: 1px solid var(--line); border-radius: .5rem;
           background: var(--panel); margin-bottom: .75rem; }}
  .made {{ display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap;
           padding: .7rem .9rem; }}
  .made .title, .sends .title {{ font-weight: 600; font-size: .9375rem;
                                 color: var(--ink); text-decoration: none; }}
  .made a.title:hover {{ text-decoration: underline; }}
  /* The age goes to the right edge and stays on one line. `margin-left:
     auto` alone does not do it inside a wrapping flex row: the item wraps
     first and then has a whole line to itself. */
  /* The age goes to the right edge and stays on one line. Marked with a
     class rather than :last-child -- a block with no age has its
     description last, and that was being pushed to the right instead. */
  .made .when, .sends .when, .made .aside, .sends .aside {{
      margin-left: auto; color: var(--dim); font-size: .8125rem;
      white-space: nowrap; font-variant-numeric: tabular-nums;
      padding-left: 1rem; }}
  .made .aside, .sends .aside {{ white-space: normal; }}
  /* Something that went wrong, in the slot the age usually sits in. The
     rule above is more specific than `.warn` on its own, so without this a
     refused login was printed in the same grey as "10 s ago". */
  .made .when.warn, .sends .when.warn {{ color: var(--warn);
      white-space: normal; }}
  /* The context band: above the form, and marked as belonging to the page
     rather than to the settings under it. */
  .flow.context {{ margin-bottom: 1.25rem;
      background: color-mix(in srgb, var(--accent) 7%, transparent);
      border-color: color-mix(in srgb, var(--accent) 25%, transparent); }}
  .flow.context .made {{ padding: .55rem .9rem; }}
  .made .note, .sends .note {{ min-width: 0; overflow-wrap: anywhere; }}
  .sends {{ list-style: none; margin: 0; padding: 0;
            border-top: 1px solid var(--line); }}
  .sends li {{ display: flex; align-items: baseline; gap: .5rem;
               flex-wrap: wrap; padding: .5rem .9rem .5rem 1.6rem;
               font-size: .875rem; border-top: 1px solid var(--line); }}
  .sends li:first-child {{ border-top: 0; }}
  .sends.plain li {{ padding-left: .9rem; }}
  .sends li.none {{ color: var(--dim); font-size: .8125rem; }}
  .sends .arrow {{ position: absolute; margin-left: -.9rem; color: var(--dim); }}
  .sends li a {{ font-weight: 600; color: var(--ink); }}
  .chip {{ font-size: .6875rem; padding: .1rem .4rem; border-radius: .25rem;
           background: color-mix(in srgb, var(--ink) 8%, transparent);
           color: var(--dim); text-transform: uppercase;
           letter-spacing: .03em; }}
  .flow .note {{ font-size: .8125rem; color: var(--dim); }}

  /* -- the stations page ------------------------------------------- */
  /* A list of consoles rather than a form, so it is a table. Laid out
     rather than left to the browser: the identity is a 32-character hex
     string and, left to itself, it takes the width from every column that
     has something to say. */
  table.stations {{ width: 100%; border-collapse: collapse;
      font-size: .875rem; margin: .4rem 0 0; }}
  table.stations th {{ text-align: left; font-weight: 600; color: var(--dim);
      font-size: .75rem; text-transform: uppercase; letter-spacing: .04em;
      padding: 0 .6rem .4rem 0; white-space: nowrap; }}
  table.stations td {{ padding: .55rem .6rem .55rem 0; vertical-align: top;
      border-top: 1px solid var(--line); }}
  table.stations tr:first-child td {{ border-top: 0; }}
  table.stations td.act {{ text-align: right; white-space: nowrap; }}
  /* The identity is the widest thing here and the least often read. It
     breaks rather than pushing the columns somebody is looking at. */
  /* -- the live table ------------------------------------------------- */
  /* A database table, so it is laid out like one: as wide as its contents
     and scrolled sideways, never folded to fit.

     Its own class rather than `table.fields`, and that is the whole lesson.
     Sharing it put twelve columns into a `table-layout: fixed` with five
     hard widths written for a five-column form, so the last seven shared
     what was left and every cell wrapped to one character per line, with the
     headings stacked on top of each other. */
  .scroller {{ overflow-x: auto; margin: .4rem 0 0;
      /* So the columns keep their width instead of being squeezed by the
         page. The scrollbar is the honest answer to twelve columns. */
      max-width: 100%; }}
  /* As wide as its contents, and never narrower than the space it is in.
     `max-content` alone leaves a wide screen empty on the right; `100%`
     alone squeezes twelve columns into whatever there is and puts the
     wrapping back. Both, and the browser takes whichever is larger. */
  table.rows {{ width: max-content; min-width: 100%; table-layout: auto;
      border-collapse: collapse; font-size: .8125rem; }}
  table.rows th {{ text-align: left; font-weight: 600; color: var(--dim);
      font-size: .6875rem; text-transform: uppercase; letter-spacing: .04em;
      padding: 0 .9rem .4rem 0; white-space: nowrap; }}
  table.rows td {{ padding: .3rem .9rem .3rem 0; white-space: nowrap;
      border-top: 1px solid var(--line); font-family: var(--mono);
      vertical-align: top; }}
  /* The unfolded readings sit in a cell of the row above, so they must not
     inherit its single line. */
  /* One column takes the slack, so that widening the window widens the
     column with the most in it rather than stretching all twelve evenly and
     putting a hand's width between `seq` and `dateTime`. */
  table.rows th.stretch {{ width: 100%; }}
  table.rows td.wide {{ white-space: normal; padding: .2rem 0 .8rem 1.2rem; }}
  table.rows td.wide table.rows {{ font-size: .75rem; }}
  table.rows tr:hover td {{ background: var(--hover, rgba(127,127,127,.07)); }}
  table.rows td.note {{ font-family: inherit; color: var(--dim); }}
  table.rows td.open {{ cursor: pointer; text-decoration: underline dotted; }}

  /* The placement table. Wider than the station list it folds out of, and
     the chooser is the widest thing in it. */
  table.fields select {{ font-size: .8125rem; max-width: 22rem; width: 100%; }}
  table.fields td {{ vertical-align: top; }}
  table.fields td.mono {{ font-family: var(--mono); font-size: .8125rem;
                          overflow-wrap: anywhere; }}
  table.fields button.quiet {{ margin-top: .25rem; font-size: .75rem; }}
  /* The readings that are fine, folded away under a count. */
  details.settled {{ margin-top: .8rem; }}
  details.settled > summary {{ font-size: .8125rem; color: var(--dim);
      cursor: pointer; padding: .3rem 0; }}
  details.settled > summary:hover {{ color: var(--ink); }}
  /* Which measurement it is, for sorting the chooser. Narrow: it is context
     for the column beside it, not a column somebody reads down. */
  table.fields td:nth-child(4) {{ font-size: .75rem; }}
  /* Fixed, and in per cent. Left to the browser the status column took what
     it liked and the chooser got the remainder, which read "-- wherever the";
     given a minimum instead, the table grew wider than the card holding it.
     Shares of the card is the only one of the three that cannot do either. */
  table.fields {{ table-layout: fixed; width: 100%; }}
  table.fields th:nth-child(1) {{ width: 17%; }}
  table.fields th:nth-child(2) {{ width: 11%; }}
  table.fields th:nth-child(3) {{ width: 28%; }}
  table.fields th:nth-child(4) {{ width: 12%; }}
  /* `table.stations th` is nowrap, and in a fixed layout a nowrap heading
     does not widen its column -- it runs into the next one. */
  table.fields th {{ white-space: normal; }}
  table.fields td.mono {{ overflow-wrap: anywhere; }}
  table.fields .ok, table.fields .warn, table.fields .bad,
  table.fields .note {{ font-size: .75rem; }}

  /* The two settings of a station, at the top of its fold. A rule above and
     air below, so it does not read as the first row of the field table. */
  table.stations td form.props {{ display: flex; align-items: center; gap: .9rem;
      flex-wrap: wrap; margin: 0 0 .9rem; padding: .55rem .75rem;
      background: color-mix(in srgb, var(--ink) 3%, transparent);
      border-radius: 6px; }}
  table.stations td form.props select {{ font-size: .75rem; padding: .2rem .4rem; }}
  table.stations td form.props label.tick {{ margin-right: 0; display: inline-flex;
      align-items: center; gap: .35rem; }}
  table.stations td form.props button {{ margin-left: auto; }}
  /* The clock, folded away. It takes the whole width below the row so the
     bar above it stays one line. */
  table.stations td form.props > details.clock {{ flex: 1 0 100%;
      margin-top: .2rem; }}
  details.clock > summary {{ font-size: .75rem; color: var(--dim);
      cursor: pointer; }}
  details.clock > summary:hover {{ color: var(--ink); }}
  details.clock .hint {{ margin: .35rem 0; }}
  details.clock label {{ font-size: .75rem; color: var(--dim);
      margin-right: .9rem; }}
  /* Two settings, not one sentence: "indoor Its readings are" read as
     one line of prose with a dropdown in the middle of it. */
  table.stations td form.props > label.tick + label.tick {{
      padding-left: .9rem; border-left: 1px solid var(--line); }}

  table.stations code {{ font-family: var(--mono); font-size: .8125rem;
      word-break: break-all; }}
  table.stations .note {{ font-size: .75rem; color: var(--dim); }}
  /* Something that is wrong and would otherwise be invisible: the readings
     stay right, only the day boundaries move. */
  .warn {{ font-size: .75rem; color: var(--warn); }}
  nav .warn {{ font-weight: 700; }}
  table.stations td form {{ display: inline; margin: 0; }}
  table.stations input[type=text] {{ font-size: .8125rem; padding: .3rem .5rem;
      width: 9rem; }}
  label.tick {{ font-size: .75rem; color: var(--dim); margin-right: .5rem;
      white-space: nowrap; }}
  label.tick input {{ vertical-align: -1px; margin-right: .15rem; }}
  /* Remove and Ignore are not what anybody came to the page to press. */
  button.quiet {{ background: transparent; color: var(--dim);
      border-color: var(--line); padding: .3rem .8rem; }}
  button.quiet:hover {{ color: var(--bad); border-color: var(--bad);
      filter: none; }}
  table.stations.enter th {{ text-transform: none; letter-spacing: 0;
      font-size: .8125rem; padding-right: 1.2rem; white-space: nowrap; }}
  /* What a station sends, folded away under it. */
  tr.sendsrow td {{ border-top: 0; padding-top: 0; }}
  details.sends summary {{ font-size: .75rem; color: var(--dim);
      cursor: pointer; }}
  details.sends summary:hover {{ color: var(--ink); }}
  details.sends[open] summary {{ margin-bottom: .4rem; }}
  textarea.rawupload {{ width: 100%; font-family: var(--mono);
      font-size: .75rem; background: var(--sunk, #00000011);
      color: var(--dim); border: 1px solid var(--line); border-radius: .3rem;
      padding: .5rem; resize: vertical; }}

  /* The ordered picker. Every candidate is a row, ticked or not: three
     empty boxes with the choices printed underneath as grey text meant a
     site with twelve places offered three and said nothing about the rest.
     The whole row is the target -- twelve places is otherwise twelve small
     squares to hit. */
  ul.picks {{ list-style: none; margin: .35rem 0 .25rem; padding: 0;
      border: 1px solid var(--line); border-radius: .4rem;
      overflow: hidden; counter-reset: pick; }}
  /* Only the ticked rows are numbered, and the browser renumbers them as
     boxes are ticked. The order is the whole point of this control, and a
     list of twelve says nothing about it without the numbers. */
  ul.picks li:has(input:checked) {{ counter-increment: pick; }}
  ul.picks li:has(input:checked) label::after {{ content: counter(pick);
      margin-left: auto; padding-left: .5rem; color: var(--dim);
      font-size: .75rem; font-variant-numeric: tabular-nums; }}
  button.more {{ margin: .1rem 0 .25rem; font-size: .75rem; }}
  ul.picks li {{ display: flex; align-items: center; gap: .35rem;
      padding: .3rem .5rem; border-top: 1px solid var(--line); }}
  ul.picks li:first-child {{ border-top: 0; }}
  ul.picks li:hover {{ background: color-mix(in srgb, var(--ink) 4%,
      transparent); }}
  /* A ticked row is the answer; an unticked one is an offer. Weight rather
     than colour, so it survives a colour-blind reader and a printout. */
  ul.picks li:has(input:checked) {{ background: color-mix(in srgb,
      var(--accent) 8%, transparent); }}
  ul.picks li:has(input:checked) label > span {{ font-weight: 600; }}
  ul.picks label {{ display: flex; align-items: center; gap: .5rem;
      flex: 1 1 auto; min-width: 0; margin: 0; cursor: pointer;
      font-weight: 400; font-size: .875rem; }}
  ul.picks label > span {{ min-width: 0; overflow-wrap: anywhere; }}
  ul.picks input[type=checkbox] {{ flex: 0 0 auto; margin: 0;
      width: .95rem; height: .95rem; }}
  ul.picks input.slot {{ flex: 1 1 auto; min-width: 0; font-size: .8125rem; }}
  /* The free rows are for a list that is not closed. Set apart, or they
     read as the control failing to show what is available. */
  ul.picks li.free {{ background: color-mix(in srgb, var(--ink) 2%,
      transparent); }}
  ul.picks li.free + li.free {{ border-top-style: dotted; }}
  ul.picks button {{ padding: .1rem .4rem; line-height: 1; flex: 0 0 auto; }}
  ul.picks .alt {{ margin: 0; flex: 0 0 auto; }}

  /* A place's colour, wherever one is shown. A ring around it, so a colour
     close to the panel's own is still a shape rather than a hole. */
  .swatch {{ display: inline-block; width: .9rem; height: .9rem;
      border-radius: 50%; vertical-align: -2px; margin-right: .35rem;
      background: var(--c, var(--dim)); border: 1px solid var(--line); }}
  .palette {{ display: flex; flex-wrap: wrap; gap: .35rem; margin: .25rem 0; }}
  .palette label {{ display: inline-flex; align-items: center; gap: .25rem;
      font-size: .75rem; color: var(--dim); margin: 0;
      padding: .15rem .4rem; border: 1px solid var(--line);
      border-radius: 1rem; cursor: pointer; }}
  .palette label:has(input:checked) {{ border-color: var(--accent);
      color: var(--ink); }}
  .palette input {{ margin: 0; }}
  .colourpick {{ display: inline-flex; align-items: center; gap: .4rem; }}

  /* -- the chain ------------------------------------------------------ */

  /* Where this page sits in the run of it. The settings knew the whole
     arrangement -- which console writes where, which feed reads what -- and
     said it on no page, so each one read as a heap of fields belonging to
     nothing. Four steps and one sentence, at the top of every page in it. */
  nav.chain {{ display: flex; flex-wrap: wrap; align-items: center;
      gap: .15rem; margin: 0 0 .5rem; padding: 0; background: none;
      border-right: 0; font-size: .8125rem; }}
  nav.chain a, nav.chain .on {{ margin: 0; padding: .15rem .55rem;
      border-radius: 1rem; white-space: nowrap; }}
  nav.chain a {{ color: var(--dim); text-decoration: none; }}
  nav.chain a:hover {{ color: var(--ink); text-decoration: underline; }}
  /* The step you are on carries the weight. An arrow between them would be
     one more glyph to read; the marked one already says which way it runs,
     because the four are in order. */
  nav.chain .on {{ color: var(--ink); font-weight: 600;
      background: color-mix(in srgb, var(--accent) 14%, transparent); }}
  nav.chain a::after {{ content: "\\203a"; color: var(--line);
      margin-left: .55rem; }}
  nav.chain > :last-child::after {{ content: none; }}

  /* -- facts, checks and pills ---------------------------------------- */

  /* Read-only truth beside a form: what writes into this place, what reads
     out of it. A definition list, because that is what it is. */
  dl.facts {{ display: grid; grid-template-columns: minmax(7rem, auto) 1fr;
      gap: .3rem .9rem; margin: .5rem 0 0; font-size: .875rem; }}
  dl.facts dt {{ color: var(--dim); }}
  dl.facts dd {{ margin: 0; min-width: 0; overflow-wrap: anywhere; }}

  /* The one check a person can actually run on a latitude: nobody knows
     whether 48.4596 is right, everybody knows when the sun came up. */
  .check {{ margin: .4rem 0 0; font-size: .8125rem; color: var(--dim); }}

  /* A count of faults, beside a count of things. A different shape rather
     than the same shape in another colour -- the two sat in one slot in the
     sidebar with nothing but colour telling them apart. */
  nav a .alarm {{ float: right; margin-left: .4rem; font-size: .6875rem;
      font-weight: 700; min-width: 1.15rem; text-align: center;
      border-radius: 1rem; padding: 0 .3rem; color: var(--bg);
      background: var(--warn); font-variant-numeric: tabular-nums; }}
  /* For the half of a label that is only there to be read aloud. */
  .sr {{ position: absolute; width: 1px; height: 1px; overflow: hidden;
      clip-path: inset(50%); white-space: nowrap; }}
  /* A place in the sidebar, in its own colour. `nav a.sub` was in the
     stylesheet and emitted by nothing. */
  nav a.sub .swatch {{ width: .55rem; height: .55rem; margin-right: .45rem;
      vertical-align: 0; }}

  /* The edit form of a place, in a row under its own row. The generic
     `details` rule puts a line above every disclosure, and here that line
     fell between a place and its own form -- so the form read as a further
     entry in the list rather than as part of the one above it. */
  table.stations tr.foldrow > td {{ border-top: 0; padding-top: 0; }}
  table.stations tr.foldrow details {{ border-top: 0; margin-top: 0;
      padding-top: 0; }}
  /* Shares of the page, so one long path cannot take the width from the
     name beside it. Left to the browser, `data/dachterrasse.sdb` widened
     its column until "Dachterrasse" wrapped in the column before it. The
     same fix `table.fields` carries, for the same reason. */
  table.stations.places {{ table-layout: fixed; }}
  table.stations.places th:nth-child(1) {{ width: 26%; }}
  table.stations.places th:nth-child(2) {{ width: 22%; }}
  table.stations.places th:nth-child(3) {{ width: 26%; }}
  table.stations td code {{ word-break: normal; overflow-wrap: anywhere; }}

  /* -- application shell -------------------------------------------- */

  :root {{
    --nav-bg: #16272c; --nav-ink: #edf5f3; --nav-dim: #9eb4ae;
    --soft: #f2f5f5; --hover: #edf2f1; --on-accent: #fff;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --nav-bg: #0c171b; --nav-ink: #e9f5f1; --nav-dim: #91aaa3;
      --soft: #25242a; --hover: #29282e; --on-accent: #10241d;
    }}
  }}
  body {{ font-size: 14px; line-height: 1.5; }}
  .shell {{
    display: grid; grid-template-columns: 14rem minmax(0, 1fr);
    grid-template-rows: auto 1fr; grid-template-areas: "top top" "side content";
    min-height: 100vh;
  }}
  .topbar {{
    grid-area: top; position: sticky; top: 0; z-index: 20;
    min-height: 3.75rem; display: grid;
    grid-template-columns: 12rem minmax(8rem, 1fr) minmax(14rem, 22rem);
    align-items: center; gap: 1rem; padding: .55rem 1.1rem;
    color: var(--ink); background: var(--panel);
    border-bottom: 1px solid var(--line);
  }}
  .brand {{ color: var(--ink); text-decoration: none; font-weight: 600;
      letter-spacing: -.01em; }}
  .brand span {{ display: block; color: var(--dim); font-size: .6875rem;
      font-weight: 400; letter-spacing: .02em; }}
  .current-page {{ min-width: 0; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; color: var(--dim); font-size: .8125rem; }}
  .top-search {{ min-width: 0; }}
  .top-search form.find {{ margin: 0; }}
  .top-search form.find input {{ min-height: 2.35rem; background: var(--bg); }}
  .sidebar {{ grid-area: side; min-width: 0; padding: 1rem .75rem;
      background: var(--nav-bg); color: var(--nav-ink); }}
  nav.primary-nav {{ display: grid; gap: .25rem; padding: 0; margin: 0;
      max-height: none; overflow: visible; border: 0; background: transparent; }}
  nav.primary-nav a.primary-nav-link {{
    display: flex; align-items: center; min-height: 2.65rem;
    margin: 0; padding: .55rem .75rem; border-radius: .45rem;
    color: var(--nav-ink); font-size: .875rem; text-decoration: none;
  }}
  nav.primary-nav a.primary-nav-link:hover {{
    background: color-mix(in srgb, var(--nav-ink) 9%, transparent);
  }}
  nav.primary-nav a.primary-nav-link[aria-current] {{
    color: var(--nav-ink); font-weight: 600;
    background: color-mix(in srgb, var(--accent) 35%, var(--nav-bg));
  }}
  .mobile-navigation {{ display: none; }}
  main {{ grid-area: content; width: 100%; max-width: 50rem;
      margin: 0 auto; padding: 2rem clamp(1rem, 4vw, 2.75rem) 5rem; }}
  main.wide {{ max-width: 78rem; }}
  main.full {{ max-width: none; }}
  main > h2, .page-head h2 {{ font-size: 1.6rem; line-height: 1.2;
      letter-spacing: -.025em; font-weight: 600; }}
  .page-head {{ display: flex; align-items: flex-end; justify-content: space-between;
      gap: 1rem; margin: 0 0 1.5rem; }}
  .page-head h2 {{ margin: 0; }}
  .eyebrow {{ margin: 0 0 .25rem; color: var(--dim); font-size: .75rem; }}
  .group, .flow, .system-panel {{ border-radius: .65rem; }}
  .banner {{ border-radius: .55rem; }}
  button, a.button, .small-action {{ border-radius: .45rem; }}
  button, a.button {{ color: var(--on-accent); }}
  button.quiet, a.button.quiet {{ color: var(--ink); }}
  button:focus-visible, a.button:focus-visible,
  nav.primary-nav a:focus-visible, summary:focus-visible {{
    outline: 2px solid var(--accent); outline-offset: 2px;
  }}
  .savebar {{ margin-bottom: -5rem; border-top-color: var(--line); }}
  .savebar.is-dirty {{ background: color-mix(in srgb, var(--accent) 10%, var(--bg)); }}
  .save-state {{ color: var(--dim); font-size: .8125rem; }}

  /* Stable lists and details shared by the task pages. */
  .overview-attention, .inventory, .place-detail, .place-list,
  .system-panel {{ background: var(--panel); border: 1px solid var(--line); }}
  .overview-stages {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: .75rem; margin: 1rem 0 1.75rem; }}
  .overview-stage {{ min-width: 0; border: 1px solid var(--line);
      border-radius: .65rem; background: var(--panel); }}
  .overview-stage .made {{ min-height: 4.4rem; align-content: flex-start; }}
  .overview-stage .made h3 {{ margin: 0; }}
  .overview-stage .sends {{ border-top-color: var(--line); }}
  .overview-attention {{ border-radius: .65rem; overflow: hidden; }}
  .overview-attention > h3 {{ display: flex; align-items: center; gap: .5rem;
      margin: 0; padding: .7rem .9rem; font-size: .875rem; }}
  .overview-attention .count {{ min-width: 1.35rem; padding: 0 .35rem;
      border-radius: 1rem; text-align: center; color: var(--panel);
      background: var(--warn); font-size: .6875rem; }}
  .attention-list {{ list-style: none; margin: 0; padding: 0; }}
  .attention-list li, .inventory-row {{ display: flex;
      align-items: center; justify-content: space-between; gap: 1rem;
      min-height: 3.75rem; padding: .7rem .9rem; border-top: 1px solid var(--line); }}
  .attention-list a {{ flex: 0 0 auto; font-weight: 600; }}
  .inventory-row:first-child {{ border-top: 0; }}
  .inventory-section {{ margin: 0 0 1.75rem; }}
  .inventory-section > header, .system-panel-head {{ display: flex;
      align-items: center; justify-content: space-between; gap: 1rem; }}
  .status {{ display: inline-flex; align-items: center; gap: .35rem;
      white-space: nowrap; color: var(--dim); font-size: .75rem; }}
  .status::before {{ content: ""; width: .5rem; height: .5rem;
      border-radius: 50%; background: var(--accent); }}
  .status.warn::before {{ background: var(--warn); }}
  .status.bad::before {{ background: var(--bad); }}
  .status.neutral::before {{ background: var(--dim); }}

  .system-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem; }}
  .system-panel {{ min-width: 0; padding: 1rem 1.1rem; margin-bottom: 1rem; }}
  .system-panel h3 {{ margin: 0 0 .7rem; }}
  .system-panel-head h3 {{ margin: 0; }}
  /* The one panel people arrive at this page looking for and walk past:
     the archive interval is behind it. `--bad` rather than a literal red,
     so it stays readable on the dark ground -- an SVG-style hard colour
     here is the theme trap this project has been caught by before. */
  .system-central {{ color: var(--bad); font-weight: 700; }}
  .small-action {{ color: var(--accent); text-decoration: none;
      font-size: .8125rem; font-weight: 600; }}
  .system-row {{ display: flex; align-items: center; justify-content: space-between;
      gap: 1rem; min-height: 3rem; border-top: 1px solid var(--line);
      color: var(--ink); text-decoration: none; }}
  .system-row:first-of-type {{ border-top: 0; }}
  .system-row strong {{ display: block; font-weight: 600; }}
  .system-row-detail {{ display: block; color: var(--dim); font-size: .75rem; }}
  .system-row-meta {{ color: var(--dim); font-size: .75rem; white-space: nowrap; }}
  .system-empty {{ color: var(--dim); font-size: .8125rem; }}
  .service-boundary {{ margin-top: 0; }}
  .system-static-row {{ display: flex; align-items: center;
      justify-content: space-between; gap: 1rem; color: var(--dim); }}

  /* Places are always a master/detail task, including the first Place. */
  .place-shell {{ display: grid; grid-template-columns: minmax(15rem, 19rem)
      minmax(0, 1fr); gap: 1rem; align-items: start; }}
  .place-list {{ min-width: 0; border-radius: .65rem; overflow: hidden;
      position: sticky; top: 4.75rem; }}
  .place-list > header {{ display: flex; align-items: center;
      justify-content: space-between; gap: .75rem; padding: .8rem .9rem;
      border-bottom: 1px solid var(--line); }}
  .place-list > header h3 {{ margin: 0; font-size: .875rem; }}
  .place-list > header .button {{ padding: .25rem .55rem; }}
  .place-list nav {{ display: grid; margin: 0; padding: 0;
      border: 0; background: transparent; }}
  .place-choice {{ display: grid; grid-template-columns: minmax(0, 1fr) auto;
      gap: .1rem .6rem; margin: 0; padding: .7rem .9rem;
      border-top: 1px solid var(--line); color: var(--ink);
      text-decoration: none; }}
  .place-choice:first-child {{ border-top: 0; }}
  .place-choice:hover {{ background: var(--hover); }}
  .place-choice.is-active {{ box-shadow: inset .2rem 0 var(--accent);
      background: color-mix(in srgb, var(--accent) 8%, var(--panel)); }}
  .place-choice > span:first-child {{ min-width: 0; overflow-wrap: anywhere; }}
  .place-choice small {{ color: var(--dim); font-size: .72rem; }}
  .place-choice small:nth-of-type(2) {{ grid-column: 2; grid-row: 2;
      text-align: right; }}
  .place-choice .warn {{ grid-column: 1 / -1; }}
  .place-detail {{ min-width: 0; border-radius: .65rem; overflow: hidden; }}
  .place-detail-head {{ padding: 1rem 1.1rem; }}
  .place-detail-head > div {{ display: flex; align-items: baseline;
      gap: .5rem; flex-wrap: wrap; }}
  .place-detail-head h3 {{ margin: 0; font-size: 1.2rem; }}
  .place-detail-head code {{ margin-left: auto; color: var(--dim);
      font-size: .75rem; overflow-wrap: anywhere; }}
  nav.place-tabs {{ display: flex; gap: 0; margin: 0; padding: 0 .55rem;
      overflow-x: auto; border: 0; border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line); background: var(--soft); }}
  nav.place-tabs a.place-tab {{ flex: 0 0 auto; margin: 0; padding: .65rem .55rem;
      color: var(--dim); font-size: .75rem; text-decoration: none; }}
  nav.place-tabs a.place-tab:hover {{ color: var(--ink); }}
  .place-section {{ padding: 1rem 1.1rem; scroll-margin-top: 5rem; }}
  .place-section + .place-section {{ border-top: 1px solid var(--line); }}
  .place-section > header {{ display: flex; align-items: baseline;
      justify-content: space-between; gap: .75rem; margin-bottom: .75rem; }}
  .place-section > header h4, .place-section > header h3 {{ margin: 0;
      font-size: .875rem; }}
  .place-form {{ margin: 0; }}
  .place-form > .place-save {{ margin: 0; padding: .8rem 1.1rem;
      border-top: 1px solid var(--line); }}
  .place-coordinates {{ display: grid; grid-template-columns: repeat(3,
      minmax(0, 1fr)); gap: .75rem; }}
  .place-members {{ background: color-mix(in srgb, var(--soft) 55%, transparent); }}
  .place-member-list {{ display: grid; gap: .5rem; margin-top: .75rem; }}
  .place-member {{ border: 1px solid var(--line); border-radius: .5rem;
      background: var(--panel); }}
  .place-member-pick {{ display: flex; align-items: flex-start; gap: .6rem;
      margin: 0; padding: .65rem .75rem; white-space: normal; cursor: pointer; }}
  .place-member-pick > span {{ display: grid; min-width: 0; }}
  .place-member-pick strong {{ color: var(--ink); font-size: .875rem; }}
  .place-member-pick small, .place-member-pick code {{ color: var(--dim);
      font-size: .7rem; overflow-wrap: anywhere; }}
  .place-member-policy {{ display: grid; grid-template-columns: minmax(9rem, 1fr)
      minmax(7rem, .6fr) auto; align-items: end; gap: .75rem;
      margin: 0; padding: .65rem .75rem; border: 0;
      border-top: 1px solid var(--line); }}
  .place-member-policy > label {{ min-width: 0; margin: 0;
      color: var(--dim); font-size: .75rem; }}
  .place-member-policy select, .place-member-policy input[type=number] {{
      display: block; width: 100%; margin-top: .2rem; }}
  .place-member-policy > label.tick {{ align-self: center; color: var(--ink); }}
  .place-member-extra-note {{ grid-column: 1 / -1; margin: 0;
      color: var(--dim); font-size: .72rem; }}
  .place-field-scope {{ padding-left: 0; padding-right: 0; }}
  .place-field-scope > header, .place-field-scope > form {{ padding-left: 1.1rem;
      padding-right: 1.1rem; }}
  .place-field-scope + .place-field-scope {{ border-top: 1px dashed var(--line); }}
  .place-field-link {{ margin: .5rem 1.1rem 0; }}
  .place-remove {{ margin: 0; padding: .8rem 1.1rem;
      border-top: 1px solid var(--line); text-align: right; }}
  .publishing-section {{ overflow: hidden; }}
  .publishing-section + .publishing-section {{ margin-top: .75rem; }}

  /* Sender identity is diagnostic; Place use is the actionable column. */
  details.technical-id {{ margin-top: .25rem; padding-top: 0; border-top: 0; }}
  details.technical-id summary {{ font-size: .7rem; }}
  .sender-readings {{ margin-top: .65rem; }}

  footer {{ margin-top: 2rem; font-size: .75rem; color: var(--dim); }}
  footer code {{ font-family: var(--mono); }}

  @media (max-width: 48rem) {{
    .shell {{ grid-template-columns: minmax(0, 1fr);
        grid-template-rows: auto auto 1fr;
        grid-template-areas: "top" "mobile" "content"; }}
    .topbar {{ position: static; grid-template-columns: minmax(0, 1fr) auto;
        gap: .5rem 1rem; padding: .65rem 1rem; }}
    .top-search {{ grid-column: 1 / -1; }}
    .sidebar {{ display: none; }}
    .mobile-navigation {{ display: block; grid-area: mobile; margin: 0;
        padding: 0; border: 0; border-bottom: 1px solid var(--line);
        background: var(--panel); }}
    .mobile-navigation > summary {{ display: flex; align-items: center;
        justify-content: space-between; min-height: 2.75rem; margin: 0;
        padding: .55rem 1rem; color: var(--ink); font-size: .8125rem;
        list-style: none; }}
    .mobile-navigation > summary::-webkit-details-marker {{ display: none; }}
    .mobile-navigation > summary::after {{ content: "+"; color: var(--dim); }}
    .mobile-navigation[open] > summary::after {{ content: "\u2212"; }}
    .mobile-navigation nav.primary-nav {{ grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: .35rem; padding: .25rem .75rem .75rem; }}
    .mobile-navigation nav.primary-nav a.primary-nav-link {{ color: var(--ink);
        border: 1px solid var(--line); background: var(--bg); }}
    .mobile-navigation nav.primary-nav a.primary-nav-link[aria-current] {{
        color: var(--ink); background: color-mix(in srgb, var(--accent) 13%, var(--panel));
    }}
    main {{ max-width: none; padding: 1.5rem 1rem 4rem; }}
    .overview-stages, .system-grid, .place-shell {{ grid-template-columns: 1fr; }}
    .place-list {{ position: static; }}
    .place-list nav {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .place-choice:nth-child(2) {{ border-top: 0; }}
    .place-coordinates {{ grid-template-columns: 1fr; }}
    .place-member-policy {{ grid-template-columns: 1fr 1fr; }}
    .savebar {{ margin-left: -1rem; margin-right: -1rem; margin-bottom: -4rem; }}
  }}
  @media (max-width: 30rem) {{
    .current-page {{ text-align: right; }}
    .page-head, .inventory-section > header, .system-panel-head,
    .attention-list li, .inventory-row,
    .system-static-row {{ align-items: flex-start; flex-direction: column; }}
    .place-list nav, .place-member-policy {{ grid-template-columns: 1fr; }}
    .place-choice:nth-child(2) {{ border-top: 1px solid var(--line); }}
    .mobile-navigation nav.primary-nav {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="shell">
  <header class="topbar">
    <a class="brand" href="./overview">weewx-evo<span>{brand}</span></a>
    <span class="current-page">{title}</span>
    <div class="top-search">{find}</div>
  </header>
  <aside class="sidebar">
    <nav class="primary-nav" aria-label="{nav_label}">{nav}</nav>
  </aside>
  <details class="mobile-navigation">
    <summary>{menu} <span>{title}</span></summary>
    <nav class="primary-nav" aria-label="{nav_label}">{nav}</nav>
  </details>
  <main class="{wide}">
    {heading}
    {readonly}
    {banner}
    {body_form_open}
      {body}
      {save}
    {body_form_close}
    {extra}
    <footer><code>{file}</code></footer>
  </main>
</div>
<script>
(function () {{
  "use strict";
  // The switch says on or off beside itself, because a toggle with no label
  // is a control people have to test to understand.
  document.querySelectorAll(".switch input").forEach(function (box) {{
    box.addEventListener("change", function () {{
      var word = box.parentNode.querySelector("em");
      if (word) word.textContent = box.checked ? "on" : "off";
    }});
  }});

  // Moving a row in the ordered picker, in the DOM only. A submit button
  // here would be a second action sharing the save form's action, which is
  // the shape `tools/admin_page_test.js` refuses -- so these move rows and
  // the save carries the result. With scripting off the boxes are still
  // boxes and picking still works; only the reordering goes.
  document.querySelectorAll("ul.picks").forEach(function (list) {{
    // Renumbering the `name` attributes is what makes the order real: the
    // server reads `x__slot0`, `x__slot1` and so on, in that order, and a
    // row that moved without its name taking the new position would look
    // moved and save unmoved.
    function renumber() {{
      var field = list.getAttribute("data-list");
      [].forEach.call(list.querySelectorAll("input.pick, input.slot"),
                      function (box, n) {{
        box.name = field + "__slot" + n;
      }});
    }}
    list.addEventListener("click", function (event) {{
      var button = event.target.closest ? event.target.closest("button") : null;
      if (!button || !list.contains(button)) return;
      var row = button.parentNode;
      if (button.classList.contains("lift") && row.previousElementSibling) {{
        list.insertBefore(row, row.previousElementSibling);
      }} else if (button.classList.contains("drop")
                 && row.nextElementSibling) {{
        list.insertBefore(row.nextElementSibling, row);
      }} else {{
        return;
      }}
      renumber();
      var box = row.querySelector("input.pick, input.slot");
      if (box) box.focus();
    }});
  }});

  // One more free row. The hidden count has to grow with it, or the server
  // reads `__slots__` rows and the new one is past the end -- it would look
  // added and save as nothing.
  document.querySelectorAll("button.more").forEach(function (button) {{
    button.addEventListener("click", function () {{
      var field = button.getAttribute("data-list");
      var list = document.querySelector('ul.picks[data-list="' + field + '"]');
      var count = document.querySelector('input[name="__slots__' + field + '"]');
      if (!list || !count) return;
      var at = list.querySelectorAll("input.pick, input.slot").length;
      var row = document.createElement("li");
      row.className = "free";
      var box = document.createElement("input");
      box.className = "slot";
      box.name = field + "__slot" + at;
      box.placeholder = "something not in the list";
      box.autocomplete = "off";
      box.spellcheck = false;
      row.appendChild(box);
      list.appendChild(row);
      count.value = String(at + 1);
      box.focus();
    }});
  }});

  // A field that only applies for certain values of another. The renderer
  // marks it and this folds it away, so a form with nothing running shows
  // every field -- one too many is harmless, one too few is the failure.
  //
  // A hidden field still submits, and that is on purpose: a Vantage handed
  // both a port and a host ignores the one its type does not name, which is
  // exactly what a stanza written by hand has always done. Clearing it here
  // would throw away what somebody typed before they changed their mind.
  var conditional = document.querySelectorAll("[data-when]");
  if (conditional.length) {{
    var settle = function () {{
      conditional.forEach(function (field) {{
        var on = field.getAttribute("data-when");
        var wanted = (field.getAttribute("data-when-is") || "").split(" ");
        var source = document.querySelector('[name="' + on + '"]');
        // No such field on this form: show it. Guessing would hide a setting
        // for a reason nobody can see.
        field.hidden = !!source && wanted.indexOf(source.value) < 0;
      }});
    }};
    document.addEventListener("change", settle);
    document.addEventListener("input", settle);
    settle();
  }}

  // Keep the one save action visible, and make its state explicit. The
  // button remains usable without scripting; this only adds dirty-state and
  // the warning when a changed form is left behind.
  var savebar = document.querySelector("[data-savebar]");
  var dirty = false;
  if (savebar) {{
    var saveForm = savebar.closest("form");
    var saveState = savebar.querySelector(".save-state");
    var markDirty = function () {{
      dirty = true;
      savebar.classList.add("is-dirty");
      if (saveState) saveState.textContent = "Unsaved changes";
    }};
    if (saveForm) {{
      saveForm.addEventListener("input", markDirty);
      saveForm.addEventListener("change", markDirty);
      saveForm.addEventListener("submit", function () {{ dirty = false; }});
    }}
    window.addEventListener("beforeunload", function (event) {{
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    }});
  }}

  document.querySelectorAll(".mobile-navigation .primary-nav-link")
    .forEach(function (link) {{
      link.addEventListener("click", function () {{
        var menu = link.closest("details");
        if (menu) menu.open = false;
      }});
    }});
}})();
</script>
</body>
</html>
"""


def _form(content_type: str, body: bytes) -> dict[str, str]:
    """A posted form, whether it carries a file or not.

    Ordinary settings arrive urlencoded. The importer needs a file as well,
    which means multipart, and `cgi.FieldStorage` was removed in Python 3.13.
    The email parser does the same job and has not gone anywhere.

    A file comes back as its text under its own field name. Nothing here
    handles anything but text, and a skin.conf is text.
    """
    if not content_type.lower().startswith("multipart/form-data"):
        return {k: v[-1] for k, v in
                parse_qs(body.decode("utf-8", "replace"),
                         keep_blank_values=True).items()}

    from email.parser import BytesParser
    from email.policy import default as default_policy

    header = (f"Content-Type: {content_type}\r\n"
              "MIME-Version: 1.0\r\n\r\n").encode()
    try:
        message = BytesParser(policy=default_policy).parsebytes(header + body)
    except Exception:
        log.warning("a posted form could not be read", exc_info=True)
        return {}

    out: dict[str, str] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        # A file input that was left empty still posts, with no filename and
        # no content. It must not win over the field somebody did fill in.
        text = payload.decode("utf-8", "replace")
        if part.get_filename() and not text.strip():
            continue
        out[str(name)] = text
    return out


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    admin: Admin

    def log_message(self, fmt: str, *args: object) -> None:
        # BaseHTTPRequestHandler normally logs the complete request target.
        # The first segment here is the Admin credential, so formatting that
        # line would copy the token into every debug log and log collector.
        if fmt == '"%s" %s %s' and len(args) >= 3:
            method = str(args[0]).split(" ", 1)[0]
            log.debug("%s %s %s %s", self.address_string(), method,
                      args[1], args[2])
        else:
            log.debug("%s HTTP request", self.address_string())

    def _request_length(self) -> int:
        """A single non-negative HTTP Content-Length, or an error.

        ``read(-1)`` means "read until EOF", so treating a negative length as
        an integer turns one request into an unbounded worker. This server
        does not implement chunked request bodies either; accepting one would
        leave its chunks to be parsed as the next request on the connection.
        """
        if self.headers.get("Transfer-Encoding") is not None:
            raise ValueError("transfer encoding is not supported")
        values = self.headers.get_all("Content-Length", [])
        if len(values) > 1:
            raise ValueError("more than one content length")
        if not values:
            return 0
        raw = values[0].strip()
        if not raw or not raw.isascii() or not raw.isdecimal():
            raise ValueError("invalid content length")
        return int(raw)

    def handle_one_request(self) -> None:
        """Every request, with a net under it.

        Without this an unhandled exception anywhere in a handler drops the
        connection: the browser says the connection was reset, the log has a
        traceback nobody is looking at, and whoever was uploading fifteen
        years of readings has no idea whether any of it arrived.

        A page that cannot be built is a 500 with the reason in it. That is
        worth more than a tidy stack trace on a terminal somebody closed --
        and it is the same rule the listener follows for a console, where
        answering anything beats going quiet.

        Only for what was not already answered: `_reply` marks the response
        as sent, so a handler that failed *after* replying does not get a
        second set of headers written over the first.
        """
        self._answered = False
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            # The other end left. Ordinary, and nothing to report: a browser
            # that navigates away mid-request does this every time.
            self.close_connection = True
        except Exception as exc:
            log.exception("a request to the settings page failed")
            if not self._answered:
                try:
                    self._reply(500, _oops(exc), "text/html; charset=utf-8")
                except Exception:
                    self.close_connection = True

    def _authorised(self, path: str) -> bool:
        peer = self.client_address[0] if self.client_address else ""
        if self.admin.token in path.strip("/").split("/"):
            self.admin.limits.succeeded(peer)
            return True
        self.admin.limits.failed(peer)
        return False

    def _permitted(self) -> bool:
        """Whether this peer is on a network this page answers.

        Refused with 404, the same as a wrong token. A different reply would
        say there is something here.
        """
        peer = self.client_address[0] if self.client_address else ""
        if not self.admin.access.allows(peer):
            self.admin.refused_peers += 1
            log.warning("refused %s: the settings page answers %s",
                        peer, self.admin.access)
            self._reply(404, b"not found", "text/plain")
            return False
        if not self.admin.limits.has_attempts_left(peer):
            self._reply(404, b"not found", "text/plain")
            return False
        if not self.admin.limits.allow(peer):
            self._reply(429, b"slow down", "text/plain", {"Retry-After": "5"})
            return False
        return True

    def _reply(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8",
               headers: dict[str, str] | None = None) -> None:
        self._answered = True
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # This page changes what a station records. It has no business being
        # framed, sniffed, or sending its address anywhere.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'unsafe-inline'; script-src 'unsafe-inline'")
        self.send_header("Permissions-Policy",
                         "camera=(), microphone=(), geolocation=()")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _parts(self, path: str) -> list[str]:
        return [p for p in path.strip("/").split("/") if p != self.admin.token]

    def _which(self, path: str) -> str:
        parts = self._parts(path)
        names = {s.name for s in self.admin.schemas}
        for part in reversed(parts):
            # The "add" pages are not schemas, so they have to be named here.
            # A missing one does not 404: it falls through to the first
            # schema and renders the core settings under the heading somebody
            # clicked, which looks like the link is broken rather than the
            # list being short. `new-upload` and `new-forecast` were both
            # missing exactly that way.
            if part in names or part in ADD_PAGES or part in OWN_PAGES:
                # The wizard is one page with a step in the path, so the
                # step has to survive being routed. Without this every
                # `setup/<step>` came back as `setup` and rendered the first
                # one -- a progress bar you could click and that took you
                # nowhere.
                if part == "setup" and parts[-1] != "setup":
                    return f"setup/{parts[-1]}"
                return part
            if part.startswith("plot:"):
                return part
        # Nothing named, so: the overview. It used to be the first schema,
        # which put somebody who opened the bare URL into a form they had not
        # asked for.
        return "overview"

    def do_GET(self) -> None:
        if not self._permitted():
            return
        parsed = urlparse(self.path)
        if not self._authorised(parsed.path):
            self._reply(404, b"not found", "text/plain")
            return
        if parsed.path.rstrip("/").endswith("/schema.json"):
            body = json.dumps(_describe(self.admin), indent=2).encode()
            self._reply(200, body, "application/json")
            return
        if parsed.path.rstrip("/").endswith("/live.json"):
            # What the live page polls. Its own endpoint rather than the
            # page rebuilt every three seconds: the page is a hundred
            # kilobytes of shell around a table that changes.
            asked = parse_qs(parsed.query)
            body = json.dumps(adminlive.feed(
                self.admin,
                before=_a_row(asked.get("before")),
                after=_a_row(asked.get("after")))).encode()
            self._reply(200, body, "application/json")
            return
        # A save redirects here so that a reload does not save again. Saying
        # nothing on arrival is how a page that worked looks like one that
        # did not: the form comes back identical and there is no sign
        # anything happened.
        said = parse_qs(parsed.query)
        message = ("Saved." if "saved" in said
                   else "Removed." if "removed" in said else "")
        if said.get("done"):
            # An add-on. Named, and with the restart said out loud: entry
            # points are read once per process, so it is installed and doing
            # nothing until the service comes back, and "Saved." would let
            # somebody go looking for it on a page that cannot show it yet.
            message = (f"{said['done'][0]} is done. Restart weewx-evo for it "
                       f"to take effect.")
        # `?learn=name` reopens the wizard on a station still waiting for its
        # console, so the values to type in are one link away rather than
        # gone once the page was left.
        form = {"learn": said["learn"][0]} if said.get("learn") else None
        # The search reads its query from the URL, because a search result
        # you can link to and reload is worth more than a tidy POST.
        if said.get("q"):
            form = {"q": said["q"][0]}
        # `?open=<place>` unfolds one archive's row. A link from anywhere
        # else -- the search, the overview, a redirect after a save -- lands
        # on the row it is about rather than on a table of closed triangles.
        if said.get("open"):
            form = dict(form or {}, _open=said["open"][0])
        self._reply(200, page(self.admin, self._which(parsed.path),
                              message=message, form=form))

    def do_POST(self) -> None:
        if not self._permitted():
            # No body was consumed. Do not let it become another request on
            # this HTTP/1.1 connection after the refusal already sent.
            self.close_connection = True
            return
        parsed = urlparse(self.path)
        if not self._authorised(parsed.path):
            self.close_connection = True
            self._reply(404, b"not found", "text/plain",
                        {"Connection": "close"})
            return

        try:
            length = self._request_length()
        except ValueError:
            self.close_connection = True
            self._reply(400, b"invalid request body length", "text/plain",
                        {"Connection": "close"})
            return

        # An archive goes another way entirely, and has to branch before
        # both of the lines below it. `MAX_FORM` is a quarter of a megabyte
        # and a real archive is hundreds; `_form` decodes the body as text
        # and an archive is a SQLite file. So it is streamed to disk and
        # never becomes a `form` at all.
        if self._parts(parsed.path)[-2:] == ["setup", "upload-archive"]:
            self._take_archive(length)
            return

        # Refused, not truncated. Reading the first quarter of a megabyte of
        # an uploaded skin and importing whatever plots happened to fit is
        # the worst of the three possible outcomes.
        if length > MAX_FORM:
            # The body is intentionally not read. Close the connection so it
            # cannot be interpreted as a pipelined request after this reply.
            self.close_connection = True
            self._reply(413, b"that is larger than this page accepts",
                        "text/plain", {"Connection": "close"})
            return

        body = self.rfile.read(length) if length else b""
        form = _form(self.headers.get("Content-Type", ""), body)

        parts = self._parts(parsed.path)
        action = parts[-1] if parts else ""

        # The wizard. Its steps are `setup/<name>`, so the step is the last
        # segment and the one before it says which page we are on -- routed
        # here rather than in the big table below because every one of them
        # comes back to the wizard rather than to a settings page.
        if len(parts) >= 2 and parts[-2] == "setup":
            self._setup_step(action, form)
            return

        # Adding one. A name, a kind, and -- for a WeeWX driver -- which
        # hardware, because that is what decides the fields on the page it
        # redirects to.
        if action == "new-collector":
            error = self.admin.add_collector(form.get("name", ""),
                                             form.get("kind", ""),
                                             form.get("driver", ""))
            if error:
                self._reply(200, page(self.admin, "new-collector",
                                      errors={"": error}, form=form))
                return
            made = form["name"].strip().lower()
            self._redirect(f"./collector:{made}")
            return

        if (action == "remove" and len(parts) >= 2
                and parts[-2].startswith("collector:")):
            error = self.admin.remove_collector(parts[-2].split(":", 1)[1])
            if error:
                self._reply(200, page(self.admin, parts[-2],
                                      errors={"": error}))
                return
            self._redirect("./system?removed=1")
            return

        if action == "new-feed":
            error = self.admin.add_feed(form.get("name", ""),
                                        form.get("kind", ""))
            if error:
                self._reply(200, page(self.admin, "new-feed",
                                      errors={"": error}, form=form))
                return
            self._redirect(f"./feed:{form['name'].strip().lower()}")
            return

        if action == "remove" and len(parts) >= 2 \
                and parts[-2].startswith("feed:"):
            error = self.admin.remove_feed(parts[-2].split(":", 1)[1])
            if error:
                self._reply(200, page(self.admin, parts[-2],
                                      errors={"": error}))
                return
            self._redirect("./publishing?removed=1")
            return

        if action == "new-plot":
            error = adminplots.add(self.admin, form.get("name", ""),
                                   form.get("span", "day"),
                                   form.get("obs", ""))
            if error:
                self._reply(200, page(self.admin, "new-plot",
                                      errors={"": error}, form=form))
                return
            self._redirect(f"./plot:{form['name'].strip().lower()}")
            return

        if action == "compare-plots":
            said, error = adminplots.compare(self.admin, form)
            self._reply(200, page(self.admin, "charts",
                                  errors={"": error} if error else None,
                                  message=said))
            return

        if action == "import-plots":
            uploaded, pasted = form.get("upload", ""), form.get("pasted", "")
            said, error = adminplots.bring_over(
                self.admin, form.get("source", ""), bool(form.get("replace")),
                text=uploaded or pasted or "",
                origin="the uploaded file" if uploaded else "the pasted text")
            self._reply(200, page(self.admin, "import-plots",
                                  errors={"": error} if error else None,
                                  message=said, form=form))
            return

        if action == "remove" and len(parts) >= 2 \
                and parts[-2].startswith("plot:"):
            error = adminplots.remove(self.admin, parts[-2].split(":", 1)[1])
            if error:
                self._reply(200, page(self.admin, parts[-2],
                                      errors={"": error}))
                return
            self._redirect("./charts?removed=1")
            return

        if action.startswith("plot:"):
            name = action.split(":", 1)[1]
            errors = adminplots.save(self.admin, name, form,
                                     self.admin.columns())
            if errors and "" in errors:
                self._reply(200, page(self.admin, action, errors=errors,
                                      form=form))
                return
            # Warnings -- a column that does not exist yet -- are saved and
            # then shown, because they are about the future rather than the
            # form.
            if errors:
                self._reply(200, page(self.admin, action, errors=errors))
                return
            self._redirect(f"./{action}?saved=1")
            return

        # The stations page. Its own verbs, because adopting a stranger and
        # creating a station are not the same act: one takes an identity off
        # the wire, the other hands one out.
        #
        # The verb has to be one of them, not merely the word "stations"
        # somewhere in the path. Tested that way, any URL that had picked up
        # an extra segment sent every POST here -- a feed's Save button
        # included, which came back as "Unknown station action 'feed:wdc'"
        # on a page two clicks away from the one that caused it.
        if action in ("new-station", "new-sender") or (
                any(section in parts for section in ("stations", "senders"))
                and action in STATION_ACTIONS):
            self._station_action(action, parts, form)
            return

        if "quality" in parts:
            self._quality_action(action, form)
            return

        if "addons" in parts:
            # Redirect after it, like every other save here: pip took twenty
            # seconds and a reload would run it again. `done=` carries what
            # to say, because the message is about a package this process
            # cannot see yet -- entry points are read once.
            error = adminaddons.act(self.admin, action, form)
            if error:
                self._reply(200, page(self.admin, "addons",
                                      errors={"": error}))
                return
            self._redirect(f"./addons?done={quote(str(form.get('package', '')))}")
            return

        if action in ("new-archive", "new-place") or any(
                section in parts for section in ("archives", "places")):
            self._archive_action(action, parts, form)
            return

        if action in ("new-export", "new-upload", "new-forecast",
                      "new-notify"):
            add = {"new-export": self.admin.add_export,
                   "new-upload": self.admin.add_upload,
                   "new-forecast": self.admin.add_forecast,
                   "new-notify": self.admin.add_channel}[action]
            error = add(form.get("name", ""), form.get("kind", ""))
            if error:
                self._reply(200, page(self.admin, action,
                                      errors={"": error}, form=form))
                return
            name = form["name"].strip().lower()
            self._redirect(f"./{action.split('-', 1)[1]}:{name}")
            return

        # Testing or removing one. The name comes before the verb, and what
        # sort of thing it is comes before the name: `upload:wu/test` and
        # `export:site/test` are different buttons on different pages, and
        # sending both to the exports would delete the wrong entry.
        if action in ("test", "remove") and len(parts) >= 2:
            which = parts[-2]
            sort, _, name = which.partition(":")
            if sort == "upload":
                remove, test = self.admin.remove_upload, self.admin.test_upload
            elif sort == "forecast":
                remove, test = (self.admin.remove_forecast,
                                self.admin.test_forecast)
            else:
                remove, test = self.admin.remove_export, self.admin.test_export
            if action == "remove":
                error = remove(name)
                if error:
                    self._reply(200, page(self.admin, which, errors={"": error}))
                    return
                self._redirect("./publishing?removed=1")
                return
            self._reply(200, page(self.admin, which, message=test(name)))
            return

        which = self._which(parsed.path)
        schema = next((s for s in self.admin.schemas if s.name == which), None)
        if schema is None:
            self._reply(404, b"not found", "text/plain")
            return
        errors = self.admin.save(schema, form)
        if errors:
            self._reply(200, page(self.admin, which, errors=errors, form=form))
            return
        # A step of a sender's setup posts here, because this is where the
        # parsing and the writing already are. It goes back to the sequence
        # it came from rather than landing on a settings page nobody asked
        # for -- and it sends a name rather than a destination, so the only
        # place this can redirect to is one built here.
        back = str(form.get("_back") or "").strip()
        if back:
            self._redirect(f"./new-sender?learn={quote(back, safe='')}")
            return
        # Redirect after a save, so a reload does not save again.
        self._redirect(f"./{which}?saved=1")

    def _quality_action(self, action: str, form: dict) -> None:
        """Save the table, or fill it in from what the station recorded."""
        if action == "suggest":
            said = adminquality.suggest(self.admin)
            # `suggest` says both kinds of thing: "nothing to work them out
            # from" is not an error, it is the answer.
            if said and said.startswith("Could not"):
                self._reply(200, page(self.admin, "quality",
                                      errors={"": said}))
                return
            self._redirect("./quality?saved=1"
                           + (f"&said={quote(said)}" if said else ""))
            return

        errors = adminquality.save(self.admin, form)
        if errors:
            self._reply(200, page(self.admin, "quality", errors=errors,
                                  form=form))
            return
        self._redirect("./quality?saved=1")

    def _archive_action(self, action: str, parts: list, form: dict) -> None:
        """Add, change or remove a series. Redirects, like the stations do."""
        if action in ("new-archive", "new-place", "add"):
            made, error = adminarchives.create(self.admin, form)
            if error:
                self._reply(200, page(self.admin, "new-place",
                                      errors={"": error}, form=form))
                return
            log.info("archive %r added, keeping its readings in %s",
                     made.name, made.file)
            self._redirect("./places?saved=1")
            return

        name = parts[-2] if len(parts) >= 3 else ""
        if action == "fields" and name:
            from . import adminfields

            error = adminfields.save_for_place(
                self.admin, name, str(form.get("sender") or ""), form)
        elif action == "set" and name:
            error = adminarchives.configure(self.admin, name, form)
        elif action == "remove" and name:
            error = adminarchives.remove(self.admin, name)
        else:
            error = f"Unknown archive action {action!r}."

        if error:
            # With the form, and with the row it came from open. A refused
            # save that comes back as a table of closed triangles has lost
            # everything typed and does not say where.
            self._reply(200, page(self.admin, "places", errors={"": error},
                                  form=dict(form, _open=name)))
            return
        destination = (f"./places?saved=1&open={quote(name)}"
                       if name else "./places?saved=1")
        if action == "fields" and name:
            destination += f"#place-fields-{quote(name)}"
        self._redirect(destination)

    def _station_action(self, action: str, parts: list, form: dict) -> None:
        """Adopt, ignore, remove, or announce a new one.

        All of them end in a redirect rather than a rendered page. The browser
        would otherwise offer to repeat the POST on reload, and repeating
        "adopt" is a duplicate name error on a page that just worked.
        """
        if action in ("new-station", "new-sender"):
            # One form, two things it can be. A driver that runs where the
            # hardware is has no console to type an address into, so it is
            # configured here and started there -- and that is the whole of
            # the difference. It used to be a second page under a second
            # menu, which meant knowing our word for it before finding it.
            fetching = adminstations.runs_elsewhere(form.get("driver", ""))
            if fetching is not None:
                kind, hardware = fetching
                error = self.admin.add_collector(form.get("name", ""), kind,
                                                 hardware)
                if error:
                    self._reply(200, page(self.admin, "new-sender",
                                          errors={"": error}, form=form))
                    return
                made = form.get("name", "").strip().lower()
                self._redirect(f"./collector:{made}")
                return

            station, error = adminstations.announce(
                self.admin, form.get("name", ""), form.get("driver", ""))
            if error:
                self._reply(200, page(self.admin, "new-sender",
                                      errors={"": error}, form=form))
                return
            # Straight to what has to be typed into the console. That is the
            # point of the page, and it is the one screen somebody needs in
            # front of them while standing at the hardware.
            self._reply(200, page(self.admin, "new-sender",
                                  form={"_made": station}))
            return

        error = ""
        if action == "adopt":
            error = adminstations.adopt(
                self.admin, form.get("driver", ""), form.get("identity", ""),
                form.get("name", ""))
        elif action in ("ignore", "unignore"):
            error = adminstations.ignore(
                self.admin, form.get("driver", ""), form.get("identity", ""),
                on=(action == "ignore"))
        elif action == "set" and len(parts) >= 3:
            error = adminstations.configure(self.admin, parts[-2], form)
        elif action == "learn" and len(parts) >= 3:
            found, error = adminstations.learn(self.admin, parts[-2])
            if not error and found is None:
                # Nothing has uploaded yet. Not a failure: the console may
                # take a minute, and saying "no" would read as "wrong".
                self._reply(200, page(
                    self.admin, "senders",
                    errors={"": "Nothing new has uploaded yet. Give the "
                                "console a minute and press it again."}))
                return
        elif action == "remove" and len(parts) >= 3:
            error = adminstations.remove(self.admin, parts[-2])
        else:
            error = f"Unknown station action {action!r}."

        if error:
            self._reply(200, page(self.admin, "senders", errors={"": error}))
            return
        self._redirect("./senders?saved=1")

    def _redirect(self, where: str) -> None:
        """After a POST, to a page -- named from the token, not relatively.

        `./stations?saved=1` looks right and is not: a browser resolves it
        against the URL that was posted to, so from `/<token>/stations/garten/set`
        it lands on `/<token>/stations/garten/stations`. That still renders
        the stations page -- `_which` walks the segments backwards and finds
        the last name it knows -- so nothing looks wrong, and every link
        clicked from there inherits the extra segments.

        Which is how saving a station made the *feed* page unsaveable: its
        Save button posted to `/<token>/stations/garten/feed:wdc`, the router
        saw `stations` among the segments and sent it to the station handler,
        and the answer was "Unknown station action 'feed:wdc'". Two pages
        apart, one wrong redirect.

        Absolute under the token. The admin server owns the whole of its own
        port and Caddy forwards the token path unchanged, so there is no
        mount point to be relative to.
        """
        if where.startswith(("./", "../")):
            where = f"/{self.admin.token}/{where.lstrip('./')}"
        self._reply(303, b"", "text/plain", {"Location": where})

    # -- the wizard -------------------------------------------------------

    def _take_archive(self, length: int) -> None:
        """An uploaded archive, written to disk as it arrives.

        Not through `_form`, and that is the whole of why this exists. A
        multipart body is read into memory there and decoded as text; an
        archive is a SQLite file of tens or hundreds of megabytes, so doing
        it that way would mean holding all of it twice and then throwing
        away every byte above 0x7F.

        So the body is read in blocks and the file part is written straight
        through. The boundary is found by reading the first header block --
        the parts of multipart a station's own upload path never needs, and
        the reason this is fifty lines rather than three.

        **Nothing is written over.** The archive lands beside the settings
        under a `.part` name and is renamed only once it has been opened and
        found to be a real WeeWX archive. A truncated upload leaves a
        `.part` file and no archive, which is the right outcome: the failure
        is visible and nothing has replaced anything.
        """
        try:
            self._take_archive_inner(length)
        except Exception as exc:
            log.exception("an archive upload failed")
            self._reply(200, page(
                self.admin, "setup/readings",
                errors={"": f"That upload failed: "
                            f"{type(exc).__name__}: {exc}"}))

    def _take_archive_inner(self, length: int) -> None:
        from . import adopt

        ctype = self.headers.get("Content-Type", "")
        if not ctype.lower().startswith("multipart/form-data"):
            self._reply(400, b"send the file as a form upload", "text/plain")
            return
        boundary = ""
        for bit in ctype.split(";"):
            key, _, value = bit.strip().partition("=")
            if key.strip().lower() == "boundary":
                boundary = value.strip().strip('"')
        if not boundary:
            self._reply(400, b"no boundary in that upload", "text/plain")
            return

        archive = adminarchives.load(self.admin).get(None)
        where = Path(archive.file)
        if not where.is_absolute():
            where = Path(self.admin.path).parent / where
        if where.exists():
            self._reply(200, page(
                self.admin, "setup/readings",
                errors={"": (f"There is already an archive at {where}. Move "
                             f"it aside first -- nothing here writes over "
                             f"readings that are already stored.")}))
            return

        where.parent.mkdir(parents=True, exist_ok=True)
        staging = where.with_suffix(where.suffix + ".part")
        # An earlier attempt's journals describe a file that is gone, and
        # SQLite refuses to open the new one because of them -- which reads
        # as "that is not an archive" and is nothing of the sort.
        self._clear_sqlite_files(staging)
        try:
            written = self._stream_part(length, boundary, staging)
        except Exception as exc:
            log.exception("an uploaded archive could not be written")
            staging.unlink(missing_ok=True)
            self._reply(200, page(self.admin, "setup/readings",
                                  errors={"": f"That upload failed: {exc}"}))
            return

        if not written:
            staging.unlink(missing_ok=True)
            self._reply(200, page(self.admin, "setup/readings",
                                  errors={"": "Nothing arrived. Choose a "
                                              "file before sending it."}))
            return

        # Opened and asked, not trusted. A file named weewx.sdb that is not
        # one has to fail here rather than three steps later, with the whole
        # station configured around it.
        if not adopt.is_archive(staging):
            log.warning("an uploaded archive was refused: %d bytes at %s",
                        written, staging)
            self._clear_sqlite_files(staging)
            self._reply(200, page(
                self.admin, "setup/readings",
                errors={"": (
                    f"That is not a WeeWX archive: {written} bytes arrived, "
                    f"and there is no `archive` table with dateTime, usUnits "
                    f"and interval in it. If the station it came from is "
                    f"still running, the file may be almost empty: SQLite "
                    f"keeps recent readings in a `-wal` file beside it until "
                    f"a checkpoint. Stop WeeWX and copy it again, or give "
                    f"the path in the other form -- that route reads through "
                    f"the WAL.")}))
            return

        staging.replace(where)
        # SQLite leaves `-wal` and `-shm` beside a file it has opened, and
        # `is_archive` opens this one. Renaming the database and leaving
        # those two behind gives the next reader a journal that belongs to a
        # file that is no longer there.
        for extra in ("-wal", "-shm"):
            staging.with_name(staging.name + extra).unlink(missing_ok=True)
        first, last = adopt.span_of(where)
        when = ""
        if first and last:
            when = (f", {time.strftime('%Y-%m-%d', time.localtime(first))} "
                    f"to {time.strftime('%Y-%m-%d', time.localtime(last))}")

        said = (f"{adopt.count_records(where)} records carried over{when}. "
                f"The file WeeWX has is untouched -- this is a copy.")
        self._redirect(f"../setup/publish?said={quote(said)}")

    @staticmethod
    def _clear_sqlite_files(where: Path) -> None:
        """A rejected upload, and the journals SQLite left beside it."""
        for name in (where.name, where.name + "-wal", where.name + "-shm"):
            where.with_name(name).unlink(missing_ok=True)

    def _stream_part(self, length: int, boundary: str, into: Path) -> int:
        """Write the first file part of a multipart body to `into`.

        Blocks rather than lines: a SQLite file has no newlines to speak of,
        and `readline` on one is a single read of the whole thing.

        The trailing CRLF before the closing boundary belongs to the
        boundary and not to the file. Getting that wrong adds two bytes to
        every upload, which SQLite notices and nothing else does.
        """
        marker = f"--{boundary}".encode()
        end = b"\r\n" + marker
        block = 1 << 20

        left = length
        buffer = b""
        # Skip to the part's own headers, then past the blank line after
        # them. Only the first file part is taken: the wizard's form has one.
        while b"\r\n\r\n" not in buffer and left > 0:
            chunk = self.rfile.read(min(block, left))
            if not chunk:
                break
            left -= len(chunk)
            buffer += chunk
        _headers, _, buffer = buffer.partition(b"\r\n\r\n")

        written = 0
        with into.open("wb") as handle:
            while True:
                found = buffer.find(end)
                if found >= 0:
                    handle.write(buffer[:found])
                    written += found
                    break
                # Keep back as much as the boundary could straddle, so a
                # boundary split across two reads is still found.
                keep = len(end)
                if len(buffer) > keep:
                    handle.write(buffer[:-keep])
                    written += len(buffer) - keep
                    buffer = buffer[-keep:]
                if left <= 0:
                    handle.write(buffer)
                    written += len(buffer)
                    break
                chunk = self.rfile.read(min(block, left))
                if not chunk:
                    handle.write(buffer)
                    written += len(buffer)
                    break
                left -= len(chunk)
                buffer += chunk
        return written

    def _setup_step(self, step: str, form: dict) -> None:
        """One step of the wizard. Every one of them comes back to it.

        A step that fails re-renders its own page with the message rather
        than redirecting: the answer somebody typed is still in the form,
        and a redirect would lose it. A step that works redirects to the
        next one, so a reload does not repeat it.
        """
        handler = {
            "place": self._setup_place,
            "adopt": self._setup_adopt,
            "charts": self._setup_charts,
            "archive": self._setup_archive,
            "publish": self._setup_publish,
        }.get(step)
        if handler is None:
            self._redirect("../setup")
            return

        try:
            said, error, goto = handler(form)
        except Exception as exc:
            log.exception("the wizard step %r failed", step)
            said, error, goto = "", f"That did not work: {exc}", ""

        if error:
            self._reply(200, page(self.admin, f"setup/{step}",
                                  errors={"": error}, form=form))
            return
        where = goto or "done"
        # The message travels in the URL rather than in the session, because
        # there is no session: this page holds nothing between requests, and
        # a redirect that arrives with nothing to say looks like a step that
        # did nothing.

        tail = f"?said={quote(said)}" if said else ""
        self._redirect(f"../setup/{where}{tail}")

    def _setup_place(self, form: dict) -> tuple[str, str, str]:
        """Name and coordinates, and a forecast if it was asked for."""
        name = (form.get("name") or "").strip()
        if not name:
            return "", ("A place needs a name. It goes at the top of "
                        "every page."), ""

        values: dict[str, object] = {"label": name}
        for field, label in (("latitude", "Latitude"),
                             ("longitude", "Longitude"),
                             ("altitude", "Altitude")):
            raw = (form.get(field) or "").strip()
            if not raw:
                if field == "altitude":
                    continue
                return "", (f"{label} is needed: sunrise, sunset and every "
                            f"twilight band on a chart come from it."), ""
            try:
                values[field] = float(raw.replace(",", "."))
            except ValueError:
                return "", (f"{label} has to be a number in degrees, like "
                            f"48.3858. {raw!r} is not one."), ""

        register = adminarchives.load(self.admin)
        error = adminarchives.configure(
            self.admin, register.default_name(), values)
        if error:
            return "", error, ""

        said = f"{name} it is."
        if form.get("forecast"):
            # `open-meteo`, with the hyphen: the name comes from the
            # registry and not from memory, and getting it wrong here
            # produced a wizard that said it had set up a forecast and had
            # not -- the error came back as a string nobody read.
            made = self.admin.add_forecast("ahead", "open-meteo")
            said += (" A forecast is being fetched for it."
                     if not made else f" (the forecast: {made})")
        return said, "", "readings"

    def _setup_adopt(self, form: dict) -> tuple[str, str, str]:
        """A weewx.conf, uploaded or named, read into these settings.

        Nothing of WeeWX's is written to. What comes over is its answers --
        where the station is, how often it archives, which skins it renders
        and where it uploads -- and the uploads arrive switched off.
        """
        from . import adopt

        text = form.get("upload") or ""
        named = (form.get("conf") or "").strip()
        if not text and not named:
            return "", ("Send a weewx.conf or say where one is. Everything "
                        "this step does comes out of that one file."), ""

        found = adopt.read(named, text=text)
        if not found.usable:
            why = found.problems[0] if found.problems else "nothing in it"
            return "", f"That did not read as a weewx.conf: {why}", ""

        # `import.*` are notes about where its skins and pages were, not
        # settings of ours. Kept out of the file rather than written and
        # ignored.
        #
        # And `archive_db` is left out on purpose, which is the whole of
        # being non-invasive. A weewx.conf says where *WeeWX's* database is,
        # and writing that here would point this station at the file WeeWX
        # is recording into -- two programs writing one SQLite file, which
        # loses it. The path is offered as something to copy *from*, on the
        # next step, and never as somewhere to write.
        place_names = {
            "station.name", "station.latitude", "station.longitude",
            "station.altitude", "station.url", "station.rain_year_start",
        }
        skipped = {"archive_db", *place_names}
        values = {k: v for k, v in found.settings.items()
                  if not k.startswith("import.") and k not in skipped}
        error = self.admin.write_settings(values, "read from a weewx.conf")
        if error:
            return "", error, ""

        place_form = {}
        for old, new in (
                ("station.name", "label"),
                ("station.latitude", "latitude"),
                ("station.longitude", "longitude"),
                ("station.altitude", "altitude"),
                ("station.url", "url"),
                ("station.rain_year_start", "rain_year_start")):
            if old in found.settings:
                place_form[new] = found.settings[old]
        if place_form:
            register = adminarchives.load(self.admin)
            error = adminarchives.configure(
                self.admin, register.default_name(), place_form)
            if error:
                return "", error, ""

        said = [f"{len(values)} setting(s) taken"]
        if found.exports:
            for name, settings in found.exports.items():
                made = self.admin.add_export_settings(name, settings)
                if not made:
                    said.append(f"its {settings.get('kind')} account as "
                                f"{name!r}, switched off")
        if found.skins:
            said.append(", ".join(skin for _r, skin, _h in found.skins)
                        + " is what it renders")
        if found.archive is not None:
            said.append(f"its archive is at {found.archive} -- copy it on "
                        f"the next step; this station will not write to it")
        elif found.elsewhere:
            said.append(f"its readings are in {found.elsewhere}")
        return "; ".join(said), "", "readings"

    def _setup_charts(self, form: dict) -> tuple[str, str, str]:
        """A skin.conf, through the importer that already exists."""
        uploaded, pasted = form.get("upload", ""), form.get("pasted", "")
        said, error = adminplots.bring_over(
            self.admin, form.get("source", ""),
            replace=bool(form.get("replace")),
            text=uploaded or pasted or "",
            origin="the uploaded file" if uploaded else "the pasted text")
        return said, error, "readings"

    def _setup_archive(self, form: dict) -> tuple[str, str, str]:
        """An existing archive, copied into place.

        By path here. The upload is a different route entirely -- an archive
        is tens or hundreds of megabytes and cannot go through a form that
        decodes its body as text -- and lives in `_setup_upload`.
        """
        from . import adopt

        source = (form.get("source") or "").strip()
        if not source:
            return "", ("Say where the archive is, or send the file with the "
                        "other form."), ""

        archive = adminarchives.load(self.admin).get(None)
        where = Path(archive.file)
        if not where.is_absolute():
            where = Path(self.admin.path).parent / where
        try:
            said = adopt.adopt_archive(source, where)
        except ValueError as exc:
            return "", str(exc), ""
        except OSError as exc:
            return "", f"Could not copy it: {exc}", ""
        return (f"Carried over: {said}. WeeWX still has its own copy -- this "
                f"one is a copy, so nothing of its is touched."), "", "publish"

    def _setup_publish(self, form: dict) -> tuple[str, str, str]:
        """An FTP account, and the address its pages are served at."""
        host = (form.get("host") or "").strip()
        if not host:
            return "Nothing published from here yet.", "", "done"

        settings = {
            "kind": "ftp",
            "host": host,
            "user": (form.get("user") or "").strip(),
            "password": form.get("password") or "",
            "directory": (form.get("directory") or "/").strip(),
            # The pages, and the charts they draw from, in one export: a page
            # that arrives before its charts is the half-published site the
            # `feed` trigger exists to prevent.
            "source": "site",
            "also": ["json -> data/json"],
        }
        address = (form.get("live_push_url") or "").strip()
        if address:
            settings["live_push_url"] = address
        error = self.admin.add_export_settings("site", settings)
        if error:
            return "", error, ""
        said = f"Publishing to {host}."
        if address:
            said += (" The pages will show live readings: a small PHP file "
                     "goes up with them and this station posts to it.")
        return said, "", "done"

    def do_HEAD(self) -> None:
        self.do_GET()


def _oops(exc: Exception) -> bytes:
    """What a request that failed answers with.

    The message, not the traceback. Somebody looking at this page is not
    reading Python, and the line that matters -- what they were doing and
    what went wrong -- is the first line of it. The traceback is in the log
    for whoever wants it.

    No stylesheet and no template: this is what is left when the thing that
    builds pages is the thing that failed.
    """
    said = html.escape(f"{type(exc).__name__}: {exc}")
    return (f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>That did not work</title>
<style>
  body {{ font: 15px/1.6 system-ui, sans-serif; max-width: 40rem;
          margin: 4rem auto; padding: 0 1.25rem; }}
  code {{ background: #f4f4f5; padding: .15rem .35rem; border-radius: .2rem; }}
  p.said {{ background: #fff4f4; border-left: 3px solid #c33;
            padding: .75rem 1rem; }}
</style></head><body>
<h1>That did not work</h1>
<p class="said"><code>{said}</code></p>
<p>Nothing was changed by the request that failed. The settings page is
   still running &mdash; go back and try again, or take another route to
   the same thing.</p>
<p>The full traceback is in the log, which is where it is useful.</p>
</body></html>""").encode()


def _describe(admin: Admin) -> dict:
    """The whole schema as JSON, for anything that is not this page.

    A second interface to the same declaration -- an installer, a test, or an
    admin page somebody likes better than this one.
    """
    from dataclasses import asdict

    def described(option: Option) -> dict:
        out = asdict(option)
        # `choices_from` is a function, and the point of it is what it
        # returns. Resolved here so the JSON says what can actually be chosen
        # on this installation, which is what a caller wants to know.
        out.pop("choices_from", None)
        out["choices"] = [list(pair) for pair in option.options()]
        out["suggestions"] = [list(pair) for pair in option.suggestions]
        return out

    return {
        "file": str(admin.path),
        "components": [
            {"name": s.name, "label": s.label, "kind": s.kind, "help": s.help,
             "groups": [{"label": g.label, "help": g.help, "prefix": g.prefix,
                         "options": [described(o) for o in g.options]}
                        for g in s.groups]}
            for s in admin.schemas
        ],
    }


class AdminServer:
    """The admin page, on its own port."""

    def __init__(self, admin: Admin, host: str = "0.0.0.0",
                 port: int = 8080) -> None:
        handler = type("AdminHandler", (_Handler,), {"admin": admin})
        self.server = ThreadingHTTPServer((host, port), handler)
        self.server.daemon_threads = True
        self.host, self.port = self.server.server_address[:2]
        self.admin = admin

    def serve_forever(self) -> None:  # pragma: no cover - a loop
        self.server.serve_forever()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

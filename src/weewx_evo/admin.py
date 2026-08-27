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
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import adminplots, adminstations
from . import config as config_file
from .netaccess import PRIVATE_ONLY, Access
from .options import UNITS, Group, Option, Schema, split_duration
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

def upload_kinds() -> list[str]:
    """The kinds of upload that can be added. Asked, not listed."""
    from . import uploads

    return uploads.kinds()


def upload_kind_choices() -> list[tuple[str, str, str]]:
    """Each service, what it is called, and what it is for.

    The same reasoning as the exports: a dropdown reading
    `ambient / cwop / mqtt` asks somebody to already know the answer.
    """
    from . import uploads

    out = []
    for kind in uploads.kinds():
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

#: A newline, for joining inside an f-string.
NEWLINE = chr(10)


#: The pages that create something, which are not schemas and so have to be
#: listed. One list, used by both the router and the renderer, because two
#: lists is how one of them ends up short.
ADD_PAGES = ("new-export", "new-feed", "new-upload", "new-forecast",
             "new-plot", "import-plots", "new-station")

#: Pages that are neither a schema nor a form to create one. They render
#: themselves, the way the chart pages do.
OWN_PAGES = ("stations",)


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

    # -- adding and removing ---------------------------------------------

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
            from .cli import build_upload

            upload = build_upload(name, dict(settings))
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
            # Read from the file this page edits rather than from the running
            # settings. The two are the same in practice, and this way the
            # test button works on a configuration that has been changed and
            # not yet restarted -- which is exactly when somebody presses it.
            place = Place(
                latitude=float(config_file.get(current, "station.latitude") or 0.0),
                longitude=float(config_file.get(current, "station.longitude") or 0.0),
                altitude=config_file.get(current, "station.altitude"),
                name=str(config_file.get(current, "station.name") or ""))
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

    def columns(self) -> set[str]:
        """The readings the archive has a column for.

        Asked of the database rather than of a schema: a station whose driver
        added its own columns should be able to chart them, and nothing here
        knows what those are called.
        """
        import sqlite3

        archive = config_file.get(self.config(), "archive_db") or "data/weewx.sdb"
        path = Path(archive)
        if not path.is_absolute():
            path = self.path.parent / path
        if not path.exists():
            return set()
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
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

        # An unticked checkbox sends nothing at all, so the form carries a
        # hidden marker for each one. Present marker, absent box means off;
        # no marker at all means the field was not part of this request and
        # must be left alone.
        form = dict(form)
        for _group, option in schema:
            if option.kind == "duration":
                # The form sends a number and a unit in two fields. Put them
                # back together before anything looks at them, so everything
                # downstream sees one duration and not two halves.
                amount = form.get(f"{option.name}__amount")
                unit = form.get(f"{option.name}__unit", "s")
                if amount is not None and str(amount).strip():
                    form[option.name] = f"{str(amount).strip()}{unit}"
                continue
            if option.kind != "bool":
                continue
            if f"{MARKER}{option.name}" in form:
                form.setdefault(option.name, "")

        parsed, errors = schema.parse(form, only_present=True)
        if errors:
            return errors

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


def field(option: Option, value: Any, error: str = "") -> str:
    """One setting as a form field."""
    name = html.escape(option.name)
    shown = option.render(value)
    label = html.escape(option.label)
    out = [f'<div class="field{" bad" if error else ""}">']
    out.append(f'<label for="f-{name}">{label}')
    if option.required:
        out.append('<span class="req" title="required">*</span>')
    out.append("</label>")

    if option.kind == "bool":
        checked = " checked" if value else ""
        out.append(f'<input type="hidden" name="__present__{name}" value="1">')
        out.append(f'<label class="switch"><input type="checkbox" id="f-{name}" '
                   f'name="{name}" value="1"{checked}><span></span>'
                   f'<em>{"on" if value else "off"}</em></label>')
    elif option.kind == "duration":
        # A number and a unit, not a string somebody has to know the syntax
        # for. "300" in a box labelled "interval" is a question about units
        # that a form should not be asking.
        amount, unit = split_duration(option.parse(value) if value else option.default)
        units = "".join(
            f'<option value="{code}"{" selected" if code == unit else ""}>'
            f"{word}</option>" for code, word in UNITS)
        out.append('<div class="pair">')
        out.append(f'<input type="number" id="f-{name}" name="{name}__amount" '
                   f'value="{amount}" min="0" step="1" inputmode="numeric">')
        out.append(f'<select name="{name}__unit" aria-label="unit">{units}</select>')
        out.append("</div>")
    elif option.kind == "choice":
        available = option.options()
        if not available:
            out.append(f'<input type="text" id="f-{name}" name="{name}" '
                       f'value="{html.escape(str(shown))}" '
                       'placeholder="nothing installed to choose from">')
        else:
            out.append(f'<select id="f-{name}" name="{name}">')
            known = {choice for choice, _ in available}
            if shown and str(shown) not in known:
                # A value naming something no longer installed. Kept and
                # marked, rather than silently swapped for the first entry.
                out.append(f'<option value="{html.escape(str(shown))}" selected>'
                           f"{html.escape(str(shown))} (not installed)</option>")
            for choice, text in available:
                selected = " selected" if str(shown) == choice else ""
                out.append(f'<option value="{html.escape(choice)}"{selected}>'
                           f'{html.escape(text)}</option>')
            out.append("</select>")
    elif option.kind == "list":
        out.append(f'<textarea id="f-{name}" name="{name}" rows="4" '
                   f'placeholder="{html.escape(option.placeholder)}">'
                   f'{html.escape(str(shown))}</textarea>')
    else:
        kinds = {"int": "number", "float": "number", "secret": "password"}
        step = ' step="any"' if option.kind == "float" else ""
        limits = ""
        if option.minimum is not None and option.kind in ("int", "float"):
            limits += f' min="{option.minimum}"'
        if option.maximum is not None and option.kind in ("int", "float"):
            limits += f' max="{option.maximum}"'
        placeholder = option.placeholder or (
            "unset" if option.default is None else "")
        # Suggestions rather than a dropdown, where the usual answers are
        # worth one click but an unusual one must still be typeable. `allow`
        # is the case: "private", "any", or a list nobody can enumerate.
        listed = f' list="l-{name}"' if option.suggestions else ""
        out.append(f'<input type="{kinds.get(option.kind, "text")}" id="f-{name}" '
                   f'name="{name}" value="{html.escape(str(shown))}"'
                   f'{step}{limits}{listed} placeholder="{html.escape(placeholder)}" '
                   f'autocomplete="off" spellcheck="false">')
        if option.suggestions:
            out.append(f'<datalist id="l-{name}">')
            for value_, text in option.suggestions:
                out.append(f'<option value="{html.escape(value_)}">'
                           f"{html.escape(text)}</option>")
            out.append("</datalist>")

    if option.unit:
        out.append(f'<span class="unit">{html.escape(option.unit)}</span>')
    if option.kind == "choice" and option.options():
        # What else could go here. A dropdown shows one thing at a time, and
        # knowing the alternatives without opening it is worth a line.
        others = ", ".join(c for c, _ in option.options() if c and c != str(shown))
        if others:
            out.append(f'<p class="alt">or: {html.escape(others)}</p>')
    if error:
        out.append(f'<p class="err">{html.escape(error)}</p>')
    if option.help:
        out.append(f'<p class="help">{html.escape(option.help)}</p>')
    beaten = overridden(option)
    if beaten:
        out.append(
            f'<p class="err">Saving this changes nothing while '
            f'<code>{html.escape(beaten)}</code> is set in the environment: '
            f'that outranks the configuration file. Unset it, or change it '
            f'where it is set.</p>')
    if option.restart:
        out.append('<p class="note">Restarts the service when saved.</p>')
    out.append("</div>")
    return "\n".join(out)


def group_html(group: Group, values: dict[str, Any],
               errors: dict[str, str]) -> str:
    plain = [o for o in group.options if not o.advanced]
    advanced = [o for o in group.options if o.advanced]
    out = ['<section class="group">']
    out.append(f"<h3>{html.escape(group.label)}</h3>")
    if group.help:
        out.append(f'<p class="lede">{html.escape(group.help)}</p>')
    for option in plain:
        out.append(field(option, values.get(option.name), errors.get(option.name)))
    if advanced:
        # Hidden, not omitted: a setting nobody can find is one that gets
        # found by reading the source, which is worse than a longer page.
        shown = any(errors.get(o.name) for o in advanced)
        out.append(f'<details{" open" if shown else ""}>')
        out.append(f"<summary>{len(advanced)} more, rarely needed</summary>")
        for option in advanced:
            out.append(field(option, values.get(option.name),
                             errors.get(option.name)))
        out.append("</details>")
    out.append("</section>")
    return "\n".join(out)


def new_export_page(admin: Admin, error: str = "", form: dict | None = None) -> str:
    """The form that creates one. Two fields, and nothing else yet."""
    form = form or {}
    kinds = export_kind_choices()
    # Local first and chosen by default: it is the one that needs nothing
    # else installed and the one somebody adding their first export wants.
    kinds.sort(key=lambda row: row[0] != "local")
    chosen = form.get("kind") or kinds[0][0]
    options = NEWLINE.join(
        f'<option value="{html.escape(kind)}"'
        f'{" selected" if chosen == kind else ""}>{html.escape(label)}</option>'
        for kind, label, _summary in kinds)
    # The select holds the names; this holds what they mean. A dropdown
    # cannot carry a sentence, and the sentence is the part that helps.
    explained = "".join(
        f"<li><strong>{html.escape(label)}</strong>: {html.escape(summary)}</li>"
        for _kind, label, summary in kinds if summary)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<section class="group">
  <h3>Add an export</h3>
  <p class="lede">A feed writes into its own working directory. An export is
     what puts those files somewhere anybody can read them. Give it a name
     and a destination; the rest is on the page that appears next.</p>
  {problem}
  <form method="post" action="./new-export">
    <div class="field">
      <label for="f-name">Name</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="site" autocomplete="off" spellcheck="false">
      <p class="help">Lowercase letters, digits, - and _. It becomes a
         heading here, and for a local export it becomes the address the
         files appear at, so keep it short: <code>site</code>,
         <code>backup</code>, <code>hoster</code>.</p>
    </div>
    <div class="field">
      <label for="f-kind">Destination</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions"><button type="submit">Create</button></div>
  </form>
</section>'''


def new_upload_page(admin: Admin, error: str = "",
                    form: dict | None = None) -> str:
    """The form that creates one. A name and a service."""
    form = form or {}
    kinds = upload_kind_choices()
    # Weather Underground first: it is what most people mean by publishing
    # their readings, and it is the one they came here to set up.
    kinds.sort(key=lambda row: row[0] != "wunderground")
    chosen = form.get("kind") or (kinds[0][0] if kinds else "")
    options = NEWLINE.join(
        f'<option value="{html.escape(kind)}"'
        f'{" selected" if chosen == kind else ""}>{html.escape(label)}</option>'
        for kind, label, _summary in kinds)
    explained = "".join(
        f"<li><strong>{html.escape(label)}</strong>: {html.escape(summary)}</li>"
        for _kind, label, summary in kinds if summary)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<section class="group">
  <h3>Add an upload</h3>
  <p class="lede">An export moves the files a feed produced. An upload sends
     the readings themselves to a weather service, so they appear on its map
     alongside everybody else\'s. Give it a name and a service; the account
     details are on the page that appears next.</p>
  {problem}
  <form method="post" action="./new-upload">
    <div class="field">
      <label for="f-name">Name</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="wu" autocomplete="off" spellcheck="false">
      <p class="help">Lowercase letters, digits, - and _. It becomes a
         heading here and nothing else, so <code>wu</code> or
         <code>windy</code> is enough. Two accounts on the same service are
         two uploads with different names.</p>
    </div>
    <div class="field">
      <label for="f-kind">Service</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions"><button type="submit">Create</button></div>
  </form>
</section>'''


def new_forecast_page(admin: Admin, error: str = "",
                      form: dict | None = None) -> str:
    """A name and a source. The rest waits."""
    form = form or {}
    kinds = forecast_kind_choices()
    # Open-Meteo first and chosen by default: it needs no account, covers
    # anywhere, and is the one somebody adding their first forecast wants.
    kinds.sort(key=lambda row: row[0] != "open-meteo")
    chosen = form.get("kind") or (kinds[0][0] if kinds else "")
    options = NEWLINE.join(
        f'<option value="{html.escape(kind)}"'
        f'{" selected" if chosen == kind else ""}>{html.escape(label)}</option>'
        for kind, label, _summary in kinds)
    explained = "".join(
        f"<li><strong>{html.escape(label)}</strong>: {html.escape(summary)}</li>"
        for _kind, label, summary in kinds if summary)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<section class="group">
  <h3>Add a forecast</h3>
  <p class="lede">The station measures what is happening. A forecast is the
     other half of what people look at a weather page for. Two sources is the
     usual arrangement rather than the exception: one for the numbers and one
     for the warnings, because no service does both well.</p>
  <p class="lede">Everything here is free and needs no account. Nothing is
     ever written into the archive -- forecasts live in their own file, and
     deleting it costs one download.</p>
  {problem}
  <form method="post" action="./new-forecast">
    <div class="field">
      <label for="f-name">Name</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="ahead" autocomplete="off" spellcheck="false">
      <p class="help">Lowercase letters, digits, - and _. A page asks for a
         forecast by this name, so keep it short: <code>ahead</code>,
         <code>warnings</code>.</p>
    </div>
    <div class="field">
      <label for="f-kind">Source</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions"><button type="submit">Create</button></div>
  </form>
</section>'''


def new_feed_page(admin: Admin, error: str = "",
                  form: dict | None = None) -> str:
    """Two fields: a name and a kind. The rest waits."""
    form = form or {}
    kinds = feed_kind_choices()
    chosen = form.get("kind") or (kinds[0][0] if kinds else "")
    options = NEWLINE.join(
        f'<option value="{html.escape(kind)}"'
        f'{" selected" if chosen == kind else ""}>{html.escape(label)}</option>'
        for kind, label, _summary in kinds)
    explained = "".join(
        f"<li><strong>{html.escape(label)}</strong>: {html.escape(summary)}</li>"
        for _kind, label, summary in kinds if summary)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f'''
<section class="group">
  <h3>Add a feed</h3>
  <p class="lede">A feed turns the readings into files. Several of one kind
     is normal: two sets of JSON in two unit systems, or two themes side by
     side. Each writes its own directory and has its own settings.</p>
  {problem}
  <form method="post" action="./new-feed">
    <div class="field">
      <label for="f-name">Name</label>
      <input type="text" id="f-name" name="name" required
             value="{html.escape(str(form.get("name", "")))}"
             placeholder="metric" autocomplete="off" spellcheck="false">
      <p class="help">Lowercase letters, digits, - and _. It becomes the
         directory this feed writes into, and what an export points at.</p>
    </div>
    <div class="field">
      <label for="f-kind">Kind</label>
      <select id="f-kind" name="kind">{options}</select>
      <ul class="kinds">{explained}</ul>
    </div>
    <div class="actions"><button type="submit">Create</button></div>
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

    web = config.get("web", {}) or {}
    directory = str(settings.get("directory") or "")
    # As typed, and as it actually lands. A relative path is resolved against
    # the configuration file, so `data/json` beside `/data/evo.toml` is
    # `/data/data/json` -- correct, surprising, and worth showing rather than
    # leaving somebody to find out from a 404.
    resolved = ""
    if directory and not Path(directory).is_absolute():
        resolved = str((Path(admin.path).parent / directory).resolve())
    if not web.get("enabled"):
        return f'''
<section class="group">
  <h3>Where it lands</h3>
  <p class="lede">In
     <code>{html.escape(resolved or directory or "-- no directory set --")}</code>
     on this machine. Point a web server at it, or
     <a href="./website">turn the built-in one on</a> and it is readable
     straight away.</p>
</section>'''

    port = web.get("port", 8081)
    path = "/" if web.get("default") == name else f"/{html.escape(name)}/"
    host = _addresses()[0][0]
    return f'''
<section class="group">
  <h3>Where it lands</h3>
  <p class="lede">In <code>{html.escape(resolved or directory)}</code>
     {f'(you wrote <code>{html.escape(directory)}</code>, which is'
      f' relative to the settings file)' if resolved else ''},
     and the built-in server hands it out at
     <a href="http://{html.escape(host)}:{port}{path}">http://{html.escape(host)}:{port}{path}</a>.
     The name in the address is this export's name.</p>
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
    web = config.get("web", {}) or {}
    if not web.get("enabled"):
        return '''
<section class="group">
  <h3>Nothing is being served</h3>
  <p class="lede">Turn the server on above and whatever a local export
     published becomes readable in a browser. Until then the exports still
     run and still write their files.</p>
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
        return f'''
<section class="group">
  <h3>Serving nothing yet</h3>
  <p class="lede">The server is on, at
     <code>http://{html.escape(hosts[0][0])}:{port}/</code>, and there is
     nothing to hand out.</p>
  <p class="lede">A feed writes into its own working directory. What puts it
     somewhere readable is an <strong>export</strong> of kind
     <em>local</em>: choose the feed, say which directory, and it appears
     here under the export's own name.</p>
  <div class="actions"><a class="button" href="./new-export">Add an
     export</a></div>
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
        also = (f"<p class='lede'><code>{html.escape(site.default)}</code> is "
                "also at the address itself, without a name after it.</p>")

    return f'''
<section class="group">
  <h3>What is being served</h3>
  <p class="lede">The name in the address is the name of the export that
     published it. Rename the export and the address follows.</p>
  {also}
  <table>
    <thead><tr><th>name</th><th>address</th><th class="n">files</th>
      <th>from</th></tr></thead>
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


def page(admin: Admin, active: str, errors: dict[str, str] | None = None,
         message: str = "", form: dict[str, Any] | None = None) -> bytes:
    errors = errors or {}
    schema = next((s for s in admin.schemas if s.name == active), None)
    adding = schema is None and active in ADD_PAGES and active not in (
        "new-plot", "import-plots")
    charting = schema is None and (active in ("new-plot", "import-plots")
                                   or active.startswith("plot:"))
    standing = schema is None and active in OWN_PAGES
    if schema is None and not adding and not charting and not standing:
        schema = admin.schemas[0]
        active = schema.name

    # After a failed save, show what was typed rather than what is stored --
    # retyping a form because one field was wrong is how people give up.
    values = dict(admin.values(schema)) if schema else {}
    if form and schema:
        values.update({k: v for k, v in form.items() if k in values})

    nav = []
    # Feeds and exports are two different things and the page says so: a feed
    # makes files, an export moves them. See weewx_evo.feeds.
    empty = {
        "feed": "None yet. A feed produces something from the readings: a "
                "CSV, a JSON document, a chart, a whole website.",
        "export": "None yet. An export moves what a feed produced: FTP, "
                  "rsync, a copy to a mounted share.",
        "upload": "None yet. An upload sends the readings to a weather "
                  "service: Weather Underground, Windy, CWOP, an MQTT "
                  "broker.",
        "forecast": "None yet. A forecast says what is coming, and a warning "
                    "service says when it matters. Both are free and need no "
                    "account.",
    }
    for kind, heading in (("core", "System"), ("stations", ""),
                          ("driver", "Drivers"),
                          ("feed", "Feeds"), ("charts", ""),
                          ("export", "Exports"), ("upload", "Uploads"),
                          ("forecast", "Forecast")):
        if kind == "charts":
            nav.extend(adminplots.nav(admin, active))
            continue
        if kind == "stations":
            # Before the drivers, because it is the first thing set up: a
            # driver reads a protocol, a station is the console itself.
            nav.extend(adminstations.nav(admin, active))
            continue
        rows = [s for s in admin.schemas if s.kind == kind]
        if not rows and kind not in empty:
            continue
        nav.append(f'<p class="navhead">{heading}</p>')
        if not rows:
            nav.append(f'<p class="navempty">{html.escape(empty[kind])}</p>')
        for s in rows:
            current = " aria-current='page'" if s.name == active else ""
            nav.append(f'<a href="./{html.escape(s.name)}"{current}>'
                       f"{html.escape(s.label)}</a>")
        if kind == "feed" and not admin.read_only:
            current = " aria-current='page'" if active == "new-feed" else ""
            nav.append(f'<a class="add" href="./new-feed"{current}>'
                       "+ Add a feed</a>")
        if kind == "export" and not admin.read_only:
            current = " aria-current='page'" if active == "new-export" else ""
            nav.append(f'<a class="add" href="./new-export"{current}>'
                       "+ Add an export</a>")
        if kind == "upload" and not admin.read_only:
            current = " aria-current='page'" if active == "new-upload" else ""
            nav.append(f'<a class="add" href="./new-upload"{current}>'
                       "+ Add an upload</a>")
        if kind == "forecast" and not admin.read_only:
            current = " aria-current='page'" if active == "new-forecast" else ""
            nav.append(f'<a class="add" href="./new-forecast"{current}>'
                       "+ Add a forecast</a>")

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
    elif standing:
        body = [adminstations.overview(admin, message, errors.get("", ""))]
    elif active == "new-station":
        body = [adminstations.new(admin, errors.get("", ""), form,
                                  made=(form or {}).get("_made"))]
    elif adding:
        maker = {"new-feed": new_feed_page, "new-upload": new_upload_page,
                 "new-export": new_export_page,
                 "new-forecast": new_forecast_page}[active]
        body = [maker(admin, errors.get("", ""), form)]
    else:
        body = [group_html(g, values, errors) for g in schema.groups]

    # An export gets two more buttons: try the destination, and delete it.
    # Testing is worth a great deal here -- a wrong password found now beats
    # one found at the next archive interval, in a log nobody is reading.
    extra = ""
    if schema is not None and schema.name == "website":
        extra = website_summary(admin)
    if schema is not None and schema.kind == "feed" and not admin.read_only:
        name = schema.name.split(":", 1)[-1]
        extra = f'''
<section class="group danger">
  <h3>Remove</h3>
  <p class="lede">Takes {html.escape(name)} out of the configuration. The
     files it has already written are left where they are, and any export
     pointed at it stops running rather than sending an empty directory.</p>
  <form method="post" action="./{html.escape(schema.name)}/remove"
        onsubmit="return confirm('Remove the feed {html.escape(name)}?')">
    <div class="actions"><button class="warn" type="submit">Remove</button></div>
  </form>
</section>'''

    if schema is not None and schema.kind == "forecast" and not admin.read_only:
        name = schema.name.split(":", 1)[-1]
        extra += f'''
<section class="group">
  <h3>Try it</h3>
  <p class="lede">Fetches once and shows what came back, without storing
     anything. A source that needs a station id or a region and has not been
     given one answers with the ones nearest to this station, which is how to
     find yours.</p>
  <form method="post" action="./{html.escape(schema.name)}/test">
    <div class="actions"><button type="submit">Fetch once</button></div>
  </form>
</section>
<section class="group danger">
  <h3>Remove</h3>
  <p class="lede">Takes {html.escape(name)} out of the configuration. What it
     already fetched stays in the forecast file until it is next tidied.</p>
  <form method="post" action="./{html.escape(schema.name)}/remove"
        onsubmit="return confirm(\'Remove the forecast source {html.escape(name)}?\')">
    <div class="actions"><button class="warn" type="submit">Remove</button></div>
  </form>
</section>'''

    if schema is not None and schema.kind == "upload" and not admin.read_only:
        name = schema.name.split(":", 1)[-1]
        extra += f'''
<section class="group">
  <h3>Try it</h3>
  <p class="lede">Checks that the service accepts the account, without
     publishing a reading. Worth doing: most of these answer a wrong password
     with a cheerful "OK" and a word in the body, so an upload that is being
     silently rejected looks exactly like one that is working.</p>
  <form method="post" action="./{html.escape(schema.name)}/test">
    <div class="actions"><button type="submit">Test the account</button></div>
  </form>
</section>
<section class="group danger">
  <h3>Remove</h3>
  <p class="lede">Takes {html.escape(name)} out of the configuration. The
     readings already published stay where they are; this only stops sending
     more.</p>
  <form method="post" action="./{html.escape(schema.name)}/remove"
        onsubmit="return confirm(\'Remove the upload {html.escape(name)}?\')">
    <div class="actions"><button class="warn" type="submit">Remove</button></div>
  </form>
</section>'''

    if schema is not None and schema.kind == "export" and not admin.read_only:
        name = schema.name.split(":", 1)[-1]
        extra += _where_it_lands(admin, name)
        extra += f'''
<section class="group">
  <h3>Try it</h3>
  <p class="lede">Connects and looks, without sending anything.</p>
  <form method="post" action="./{html.escape(schema.name)}/test">
    <div class="actions"><button type="submit">Test the connection</button></div>
  </form>
</section>
<section class="group danger">
  <h3>Remove</h3>
  <p class="lede">Takes {html.escape(name)} out of the configuration. Nothing
     is deleted at the far end.</p>
  <form method="post" action="./{html.escape(schema.name)}/remove"
        onsubmit="return confirm('Remove the export {html.escape(name)}?')">
    <div class="actions"><button class="warn" type="submit">Remove</button></div>
  </form>
</section>'''

    banner = ""
    if errors and charting and "" not in errors:
        banner = ('<div class="banner warn">Saved. '
                  + html.escape("; ".join(errors.values())) + "</div>")
    elif errors:
        general = errors.get("")
        if general:
            banner = f'<div class="banner bad">{html.escape(general)}</div>'
        else:
            # Named, not counted. The message is also printed beside each
            # field, but a settings page is long and "3 setting(s) need
            # looking at" leaves somebody scrolling for the red one.
            labels = {option.name: option.label
                      for _group, option in (schema or ())}
            named = ", ".join(html.escape(labels.get(where, where))
                              for where in errors if where)
            banner = ('<div class="banner bad">Nothing was saved. Look at '
                      f'{named}.</div>')
    elif message:
        banner = f'<div class="banner ok">{html.escape(message)}</div>'

    restart = ""
    if admin.restart_pending:
        items = ", ".join(sorted(html.escape(x) for x in admin.restart_pending))
        # What it actually does, which is nothing: exports and uploads are
        # picked up while running, these are not. Saying "restarting" when
        # nothing restarts sends somebody looking for a service that is
        # already up, and the setting they changed still is not in effect.
        restart = ('<div class="banner warn">Saved, and waiting for a '
                   f"restart to take effect: {items}.</div>")

    own_form = adding or charting
    if charting:
        heading = ("Add a chart" if active == "new-plot"
                   else "Import charts" if active == "import-plots"
                   else f"Chart: {active.split(':', 1)[1]}")
    else:
        # Named per page rather than "everything else is an export". Two more
        # add-pages arrived after this was written and both said "Add an
        # export" over a form that was nothing of the sort.
        headings = {"new-feed": "Add a feed", "new-export": "Add an export",
                    "new-upload": "Add an upload",
                    "new-forecast": "Add a forecast",
                    "new-station": "Add a station", "stations": "Stations"}
        heading = schema.label if schema else headings.get(active, "Settings")

    return _PAGE.format(
        title=html.escape(heading),
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
        nav="\n".join(nav),
        banner=banner + restart,
        body="\n".join(body),
        action=html.escape(schema.name if schema else active),
        readonly=("<p class='lede'>Started read-only: nothing can be saved.</p>"
                  if admin.read_only else ""),
        save="" if admin.read_only or own_form else
             '<div class="actions"><button type="submit">Save</button>'
             '<span class="hint">Written to the configuration file. '
             'The previous version is kept as .bak.</span></div>',
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
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #17161a; --panel: #1f1e23; --line: #322f38; --ink: #eceaf0;
      --dim: #9a94a3; --accent: #79c79b; --warn: #e0a86a; --bad: #e08a76;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  .shell {{ display: grid; grid-template-columns: 15rem 1fr; min-height: 100vh; }}
  @media (max-width: 48rem) {{ .shell {{ grid-template-columns: 1fr; }} }}

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

  main {{ padding: 1.75rem 1.5rem 5rem; max-width: 46rem; }}
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
  .navgroup > summary .count {{ font-variant-numeric: tabular-nums;
      opacity: .65; }}
  .navgroup[open] > summary {{ color: var(--ink); font-weight: 500; }}
  nav a.sub {{ padding-left: 1.1rem; font-size: .8125rem; }}
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
  footer {{ margin-top: 2rem; font-size: .75rem; color: var(--dim); }}
  footer code {{ font-family: var(--mono); }}
</style>
</head>
<body>
<div class="shell">
  <nav>
    <h1>weewx-evo<small>settings</small></h1>
    {nav}
  </nav>
  <main>
    <h2>{title}</h2>
    {readonly}
    {banner}
    {body_form_open}
      {body}
      {save}
    {body_form_close}
    {extra}
    <footer>
      Written to <code>{file}</code>, which stays editable by hand.
      Every setting on this page comes from the component that owns it.
    </footer>
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
        log.debug("%s %s", self.address_string(), fmt % args)

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
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # This page changes what a station records. It has no business being
        # framed, sniffed, or sending its address anywhere.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
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
                return part
            if part.startswith("plot:"):
                return part
        return self.admin.schemas[0].name

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
        # A save redirects here so that a reload does not save again. Saying
        # nothing on arrival is how a page that worked looks like one that
        # did not: the form comes back identical and there is no sign
        # anything happened.
        said = parse_qs(parsed.query)
        message = ("Saved." if "saved" in said
                   else "Removed." if "removed" in said else "")
        self._reply(200, page(self.admin, self._which(parsed.path),
                              message=message))

    def do_POST(self) -> None:
        if not self._permitted():
            return
        parsed = urlparse(self.path)
        if not self._authorised(parsed.path):
            self._reply(404, b"not found", "text/plain")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0

        # Refused, not truncated. Reading the first quarter of a megabyte of
        # an uploaded skin and importing whatever plots happened to fit is
        # the worst of the three possible outcomes.
        if length > MAX_FORM:
            self._reply(413, b"that is larger than this page accepts",
                        "text/plain")
            return

        body = self.rfile.read(length) if length else b""
        form = _form(self.headers.get("Content-Type", ""), body)

        parts = self._parts(parsed.path)
        action = parts[-1] if parts else ""

        # Adding one. Two fields; everything else waits for the page that
        # appears next.
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
            self._redirect("./new-feed?removed=1")
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
            self._redirect("./new-plot?removed=1")
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
        if action == "new-station" or "stations" in parts:
            self._station_action(action, parts, form)
            return

        if action in ("new-export", "new-upload", "new-forecast"):
            add = {"new-export": self.admin.add_export,
                   "new-upload": self.admin.add_upload,
                   "new-forecast": self.admin.add_forecast}[action]
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
                self._redirect("./core?removed=1")
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
        # Redirect after a save, so a reload does not save again.
        self._redirect(f"./{which}?saved=1")

    def _station_action(self, action: str, parts: list, form: dict) -> None:
        """Adopt, ignore, remove, or announce a new one.

        All of them end in a redirect rather than a rendered page. The browser
        would otherwise offer to repeat the POST on reload, and repeating
        "adopt" is a duplicate name error on a page that just worked.
        """
        if action == "new-station":
            station, error = adminstations.announce(
                self.admin, form.get("name", ""), form.get("driver", ""),
                form.get("archive", ""))
            if error:
                self._reply(200, page(self.admin, "new-station",
                                      errors={"": error}, form=form))
                return
            # Straight to what has to be typed into the console. That is the
            # point of the page, and it is the one screen somebody needs in
            # front of them while standing at the hardware.
            self._reply(200, page(self.admin, "new-station",
                                  form={"_made": station}))
            return

        error = ""
        if action == "adopt":
            error = adminstations.adopt(
                self.admin, form.get("driver", ""), form.get("identity", ""),
                form.get("name", ""), form.get("archive", ""))
        elif action in ("ignore", "unignore"):
            error = adminstations.ignore(
                self.admin, form.get("driver", ""), form.get("identity", ""),
                on=(action == "ignore"))
        elif action == "remove" and len(parts) >= 3:
            error = adminstations.remove(self.admin, parts[-2])
        else:
            error = f"Unknown station action {action!r}."

        if error:
            self._reply(200, page(self.admin, "stations", errors={"": error}))
            return
        self._redirect("./stations?saved=1")

    def _redirect(self, where: str) -> None:
        self._reply(303, b"", "text/plain", {"Location": where})

    def do_HEAD(self) -> None:
        self.do_GET()


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

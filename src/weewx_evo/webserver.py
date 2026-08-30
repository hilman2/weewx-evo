"""Serving what the feeds produced.

A feed writes a directory of files. Something has to hand them to a browser,
and on a station in a shed that something should not have to be nginx. This
is the small local answer:

    /              the feeds there are, or one of them if it is the default
    /<feedname>/   that feed's files
    /<feedname>/…  anything under it

Anyone who wants a real web server puts one in front, or uses an export to
push the files somewhere that already has one. This exists so that a station
is useful the minute a feed produces something, without a second package and
a second configuration file.

Deliberately not the same server as the listener or the settings page. The
listener answers hardware and is behind a token; this answers browsers and is
meant to be open on the local network. Putting them on one port would mean one
set of rules for two audiences, and the stricter one would have to lose.

## What it will not do

No symlinks followed out of a feed, and no path that resolves above the feed's
own directory. A feed's directory is generated from a template, and a template
that can be made to write `../../etc` is a template somebody will eventually
write by accident. That check is the whole of the protection here.

A directory with no index page *is* listed. Refusing one was the first
instinct and it was wrong: a feed that writes seventy JSON files and no
`index.html` answered 404 at its own address, which reads as "nothing here"
and is the opposite of true. These files are published on purpose. What
protects them is the boundary above, not silence about what they are called.
"""

from __future__ import annotations

import html
import logging
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .netaccess import PRIVATE_ONLY, Access
from .ratelimit import Limits

log = logging.getLogger(__name__)

#: Tried in order when a directory is asked for.
INDEXES = ("index.html", "index.htm")

#: A newline, for joining inside an f-string.
NEWLINE = chr(10)

#: Files worth telling a browser to keep. A weather site rewrites its pages
#: every interval, so those must not be cached; the things around them --
#: fonts, stylesheets, images -- change when somebody changes the template.
CACHE_SECONDS = {
    ".css": 3600, ".js": 3600, ".woff": 86400, ".woff2": 86400,
    ".ttf": 86400, ".ico": 86400, ".svg": 3600,
}


class Site:
    """Which feeds are served, and from where."""

    def __init__(self, feeds: dict[str, Path], default: str = "",
                 title: str = "weewx-evo") -> None:
        #: name -> directory. Whatever produced them is not this file's
        #: business: a feed, or a directory somebody fills by hand.
        self.feeds = {name: Path(where).resolve()
                      for name, where in feeds.items()}
        self.default = default if default in self.feeds else ""
        self.title = title
        self.served = 0
        self.refused = 0

    def update(self, feeds: dict[str, Path], default: str = "",
               title: str = "") -> bool:
        """Serve something else from now on. Returns whether anything moved.

        The handler holds this object, so replacing its contents is how a
        changed setting takes effect without a restart. What cannot change
        this way is the port and the address it is bound to, and those are
        the two marked as needing one.
        """
        fresh = {name: Path(where).resolve() for name, where in feeds.items()}
        wanted = default if default in fresh else ""
        if fresh == self.feeds and wanted == self.default \
                and (not title or title == self.title):
            return False
        self.feeds = fresh
        self.default = wanted
        if title:
            self.title = title
        return True

    def resolve(self, feed: str, rest: str) -> Path | None:
        """The file for a request, or None if there is not one to serve.

        The check that matters is the last one: the resolved path has to be
        inside the feed's directory. `..` in a URL, a symlink pointing out, an
        encoded separator -- all of them end up here, and all of them fail the
        same way.
        """
        root = self.feeds.get(feed)
        if root is None:
            return None

        relative = unquote(rest).lstrip("/")
        if "\0" in relative:
            return None
        try:
            target = (root / relative).resolve()
        except (OSError, ValueError):
            return None

        # Inside the feed, or nowhere. `is_relative_to` follows the resolved
        # path, so a symlink out of the directory fails here too.
        if not (target == root or target.is_relative_to(root)):
            log.warning("refused a request for %s: it resolves outside %s",
                        relative, root)
            self.refused += 1
            return None

        if target.is_dir():
            for name in INDEXES:
                candidate = target / name
                if candidate.is_file():
                    return candidate
            # No index page. The caller lists it rather than pretending the
            # directory is not there.
            return target
        return target if target.is_file() else None


def listing_page(site: Site, directory: Path, path: str) -> bytes:
    """What is in a directory that has no index page of its own.

    Deliberately plain. This is not a page anybody designed; it is an answer
    to "what is actually in here", which is the question somebody has when
    they typed the address by hand.
    """
    rows = []
    try:
        entries = sorted(directory.iterdir(),
                         key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        entries = []

    for entry in entries:
        if entry.name.endswith((".part", ".tmp")) or entry.name.startswith("."):
            continue
        name = entry.name + ("/" if entry.is_dir() else "")
        try:
            size = ("" if entry.is_dir()
                    else f"{entry.stat().st_size / 1024:.1f} KB")
            when = time.strftime("%Y-%m-%d %H:%M",
                                 time.localtime(entry.stat().st_mtime))
        except OSError:
            size = when = ""
        rows.append(f'<li><a href="{html.escape(name)}">{html.escape(name)}</a>'
                    f"<span>{html.escape(size)}"
                    f"{'  &middot;  ' if size and when else ''}"
                    f"{html.escape(when)}</span></li>")

    if not rows:
        rows.append('<li class="empty">This directory is empty.</li>')

    up = ""
    if path.strip("/").count("/") >= 1:
        up = '<li><a href="../">../</a><span>up one</span></li>'

    return _INDEX.format(
        title=html.escape(f"{site.title} {path}"),
        items=up + NEWLINE.join(rows)).encode("utf-8")


def index_page(site: Site) -> bytes:
    """The list of feeds, when none of them is the default."""
    rows = []
    for name in sorted(site.feeds):
        where = site.feeds[name]
        try:
            count = sum(1 for p in where.rglob("*") if p.is_file())
            newest = max((p.stat().st_mtime for p in where.rglob("*")
                          if p.is_file()), default=0)
        except OSError:
            count, newest = 0, 0
        when = (time.strftime("%Y-%m-%d %H:%M", time.localtime(newest))
                if newest else "nothing yet")
        rows.append(
            f'<li><a href="/{html.escape(name)}/">{html.escape(name)}</a>'
            f'<span>{count} file(s), last written {html.escape(when)}</span></li>')

    if not rows:
        rows.append('<li class="empty">No feeds are configured yet. A feed '
                    'produces something from the readings: a page, a CSV, a '
                    'chart.</li>')

    return _INDEX.format(title=html.escape(site.title),
                         items="\n".join(rows)).encode("utf-8")


_INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg:#fbfaf8; --panel:#fff; --line:#e5e1da; --ink:#1d1b18;
          --dim:#6f6a62; --accent:#2f6f4e; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#17161a; --panel:#1f1e23; --line:#322f38; --ink:#eceaf0;
            --dim:#9a94a3; --accent:#79c79b; }}
  }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .wrap {{ max-width:38rem; margin:0 auto; padding:3rem 1.25rem; }}
  h1 {{ font-size:1.25rem; margin:0 0 1.5rem; font-weight:600; }}
  ul {{ list-style:none; margin:0; padding:0; }}
  li {{ background:var(--panel); border:1px solid var(--line);
       border-radius:.5rem; margin-bottom:.6rem; }}
  li a {{ display:block; padding:.9rem 1rem; color:var(--ink);
         text-decoration:none; font-weight:500; }}
  li a:hover {{ color:var(--accent); }}
  li span {{ display:block; padding:0 1rem .8rem; color:var(--dim);
            font-size:.8125rem; margin-top:-.5rem; }}
  li.empty {{ padding:.9rem 1rem; color:var(--dim); font-size:.875rem; }}
  footer {{ margin-top:2rem; color:var(--dim); font-size:.75rem; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <ul>
{items}
  </ul>
  <footer>Served by weewx-evo.</footer>
</div>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    site: Site
    access: Access
    limits: Limits
    #: The readings as an answer to a question, where one is configured.
    #: Served from here rather than from its own port because it is the same
    #: audience and the same data in another shape: what the feeds publish,
    #: for a client that has a question no plot answers.
    api: Any = None
    #: What the process is doing, for Prometheus. At `/metrics`, because that
    #: is where every scraper looks by default and a different path is a
    #: line of configuration on the other machine for nothing.
    metrics: Any = None

    def log_message(self, fmt: str, *args: object) -> None:
        log.debug("%s %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        self._serve(body=True)

    def do_HEAD(self) -> None:
        self._serve(body=False)

    def _serve(self, body: bool) -> None:
        peer = self.client_address[0] if self.client_address else ""
        if not self.access.allows(peer) or not self.limits.allow(peer):
            self._head(404, 0, "text/plain")
            if body:
                self.wfile.write(b"not found")
            return

        parsed = urlparse(self.path)
        path = parsed.path

        # Before the feeds, because a feed called `api` must not shadow it --
        # and a feed can be called anything somebody types.
        if self.api is not None and self.api.handles(path):
            self._api(parsed.query, body)
            return

        if self.metrics is not None and path.rstrip("/") == "/metrics":
            self._metrics(body)
            return

        parts = [p for p in path.split("/") if p]

        # The root: the default feed's index, or the list of feeds.
        if not parts:
            if self.site.default:
                self._file(self.site.default, "/", body)
                return
            page = index_page(self.site)
            self._head(200, len(page), "text/html; charset=utf-8")
            if body:
                self.wfile.write(page)
            return

        # A feed by name, or -- when one is rooted at / -- a path inside it.
        # Trying the feed name first means a default feed with a directory
        # called like another feed does not shadow it.
        if parts[0] in self.site.feeds:
            self._file(parts[0], "/".join(parts[1:]), body)
            return
        if self.site.default:
            self._file(self.site.default, "/".join(parts), body)
            return

        self._not_found(body)

    def _api(self, query: str, body: bool) -> None:
        """One API answer. Never cached: it is a question about now."""
        answer = self.api.answer(
            urlparse(self.path).path, query,
            header_token=self.headers.get("X-Token", ""))
        self._head(answer.status, len(answer.body), answer.kind)
        if body:
            self.wfile.write(answer.body)

    def _metrics(self, body: bool) -> None:
        """One scrape. Never cached: it is a question about this second."""
        try:
            text = self.metrics.render().encode("utf-8")
        except Exception:
            log.exception("could not render the metrics")
            # 500 rather than an empty 200: a scraper reading zero samples
            # cannot tell "nothing is wrong" from "nothing was measured".
            self._head(500, 0, "text/plain; charset=utf-8")
            return
        self._head(200, len(text),
                   "text/plain; version=0.0.4; charset=utf-8")
        if body:
            self.wfile.write(text)

    def _file(self, feed: str, rest: str, body: bool) -> None:
        target = self.site.resolve(feed, rest)
        if target is None:
            self._not_found(body)
            return

        if target.is_dir():
            # The request's own path, not one rebuilt from the parts: the
            # trailing slash is the whole question here, and rebuilding it
            # loses exactly that and redirects the address to itself.
            path = urlparse(self.path).path
            if not path.endswith("/"):
                # So that relative links in the listing resolve against this
                # directory rather than against its parent.
                self._reply_redirect(path + "/")
                return
            page = listing_page(self.site, target, path)
            self._head(200, len(page), "text/html; charset=utf-8")
            if body:
                self.wfile.write(page)
            return

        try:
            size = target.stat().st_size
            mtime = target.stat().st_mtime
        except OSError:
            self._not_found(body)
            return

        kind, _ = mimetypes.guess_type(str(target))
        kind = kind or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript",
                                                "application/json"):
            kind += "; charset=utf-8"

        # Not modified, if the browser already has it. A weather page reloaded
        # every minute is mostly the same fonts and stylesheets over again.
        since = self.headers.get("If-Modified-Since")
        stamp = self.date_time_string(int(mtime))
        if since == stamp:
            self._head(304, 0, kind, mtime=stamp,
                       cache=CACHE_SECONDS.get(target.suffix.lower()))
            return

        self._head(200, size, kind, mtime=stamp,
                   cache=CACHE_SECONDS.get(target.suffix.lower()))
        self.site.served += 1
        if not body:
            return
        try:
            with open(target, "rb") as fp:
                while chunk := fp.read(65536):
                    self.wfile.write(chunk)
        except (OSError, BrokenPipeError, ConnectionResetError):
            # A browser that navigated away mid-download. Ordinary.
            pass

    def _reply_redirect(self, where: str) -> None:
        self.send_response(301)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _not_found(self, body: bool) -> None:
        page = b"<h1>404</h1><p>Nothing here.</p>"
        self._head(404, len(page), "text/html; charset=utf-8")
        if body:
            self.wfile.write(page)

    def _head(self, code: int, length: int, kind: str,
              mtime: str = "", cache: int | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(length))
        if mtime:
            self.send_header("Last-Modified", mtime)
        # A page is rewritten every archive interval, so it must never be
        # cached; the things around it change when a template does.
        self.send_header("Cache-Control",
                         f"public, max-age={cache}" if cache else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()


class WebServer:
    """The local web server for the feeds."""

    def __init__(self, site: Site, host: str = "0.0.0.0", port: int = 8081,
                 access: Access = PRIVATE_ONLY,
                 limits: Limits | None = None, api: Any = None,
                 metrics: Any = None) -> None:
        handler = type("SiteHandler", (_Handler,), {
            "site": site, "access": access, "api": api, "metrics": metrics,
            # Generous: a page load is a dozen requests for its stylesheet,
            # its fonts and its images, and a limit that gets in the way of
            # that is one that makes the site look broken.
            "limits": limits or Limits(rate=60.0, failures=0),
        })
        self.server = ThreadingHTTPServer((host, port), handler)
        self.server.daemon_threads = True
        self.host, self.port = self.server.server_address[:2]
        self.site = site
        #: The same object the handler holds. Kept here so a reload can put
        #: a new series into it: the map is built once at startup, and a
        #: place added on the settings page was answered with a 404 by the
        #: one part of this program whose job is to say what series exist.
        self.api = api

    def serve_forever(self) -> None:  # pragma: no cover - a loop
        self.server.serve_forever()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _beside(settings: object, where: str) -> Path:
    """A path from the configuration, made absolute against that file.

    A relative path in a settings file means "beside the settings", not
    "beside whatever directory this process started in". The export that
    fills the directory uses the same rule, and the two have to agree or the
    server hands out an empty one.
    """
    path = Path(where)
    if path.is_absolute():
        return path
    base = getattr(settings, "_path", None)
    return Path(base).parent / path if base else path


def site_from(settings: object, feeds: dict[str, Path] | None = None) -> Site:
    """What this server hands out, and under which names.

    Mostly the local exports: an export named `site` publishing to a
    directory appears at `/site/`. That is the whole configuration -- you say
    where an export puts things, and it is served from there. Nobody has to
    say the same path twice.

    `[web.serve]` still names directories directly, for something this did
    not produce: a hand-written page, a directory another program fills.
    """
    config = getattr(settings, "config", {}) or {}
    configured = config.get("web", {}) or {}
    served = dict(feeds or {})

    for name, options in sorted((config.get("exports") or {}).items()):
        if not isinstance(options, dict):
            continue
        if str(options.get("kind", "")).strip() != "local":
            continue
        where = str(options.get("directory", "")).strip()
        if where:
            served[name] = _beside(settings, where)

    # Named directly, and last, so an entry here wins over an export of the
    # same name. Somebody who wrote a path down meant it.
    for name, where in (configured.get("serve") or {}).items():
        if isinstance(where, str) and where.strip():
            served[name] = _beside(settings, where)

    return Site(served,
                default=str(configured.get("default", "")),
                title=str(settings.get("station.name") or "weewx-evo"))

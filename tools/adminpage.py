"""Drive the settings page: render it, save through it, break it on purpose.

The page is generated from what components declare about themselves, so what
this really tests is that declaration -> form -> validation -> file works
end to end, for every kind of setting there is.

    python tools/adminpage.py

Nothing outside a temporary directory is touched.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import admin as admin_module
from weewx_evo import config as config_file
from weewx_evo.admin import ADD_PAGES, MARKER, OWN_PAGES, Admin, AdminServer
from weewx_evo.cli import all_schemas
from weewx_evo.ratelimit import Limits

TOKEN = "admin-token-for-the-test"


def the_hardware_form(base: str, path: Path) -> int:
    """Choosing hardware, and what the driver's own fields do when saved.

    The failure this is for is the one that leaves no trace: the page renders,
    it answers 303, it says saved, and the value is not in the file -- so the
    collector runs with the driver's default and nothing anywhere says the
    setting was ignored.

    A driver file of its own rather than one out of an installed WeeWX,
    because whether WeeWX is installed is a different question from whether
    the form works, and this test is run on machines that do not have it.
    """
    from weewx_evo import collectors as collector_defs
    from weewx_evo.ingest import weewxdrivers

    print("\nthe hardware form: a driver's own settings, chosen and saved")
    bad = 0

    # Where the settings page will look. A relative Place archive path counts
    # against the file it is written in; it is no longer a core setting.
    where = weewxdrivers.directory(beside=path.parent / "data" / "weewx.sdb")
    where.mkdir(parents=True, exist_ok=True)
    (where / "faux.py").write_text(FAUX_DRIVER, encoding="utf-8")

    found = weewxdrivers.available(where)
    module = "weewx.drivers.faux"
    bad += not check("the driver is offered",
                     module in [one.module for one in found], True)

    # Chosen while creating it, because which driver it is decides which
    # fields the page after has. Left to that page, somebody arrives at a
    # form that cannot ask anything yet.
    code, _ = post(f"{base}/{TOKEN}/new-collector",
                   {"name": "attic", "kind": "weewx-driver",
                    "driver": module})
    bad += not check("a collector can be created with hardware chosen",
                     code, 303)

    code, rendered = get(f"{base}/{TOKEN}/collector:attic")
    bad += not check("its page renders", code, 200)
    # The driver's own option and default, neither of which is written down in
    # this program.
    bad += not check("the driver's own option is on it",
                     'name="settings.port"' in rendered, True)
    bad += not check("with the default the driver gives it",
                     "/dev/faux0" in rendered, True)
    advanced = re.search(
        r'<details[^>]*>.*?name="settings\.baudrate".*?</details>',
        rendered, re.DOTALL)
    bad += not check("the advanced driver options are folded away",
                     advanced is not None, True)
    # Port or host, never both, because the driver says so in its own editor.
    bad += not check("and the conditional one is marked as conditional",
                     'data-when="settings.type"' in rendered, True)

    code, _ = post(f"{base}/{TOKEN}/collector:attic",
                   {"kind": "weewx-driver", "driver": module,
                    "conf": "", "driver_file": "",
                    "source": "attic-console", "catchup": "0", "batch": "5",
                    "settings.port": "/dev/ttyUSB7",
                    "settings.type": "serial",
                    "settings.source": "the driver's own idea of source",
                    "settings.model": "Faux 2000", "settings.timeout": "9"})
    bad += not check("its settings save", code, 303)

    written = config_file.read(path)
    settings = collector_defs.driver_settings(written, "attic")
    bad += not check("the driver's own setting is in the file",
                     settings.get("port"), "/dev/ttyUSB7")
    # The collision, measured: the driver has an option called `source` and
    # so do we. Both were sent, both were saved, and neither took the other's
    # value. Without the prefix they are one field in the form, one of the
    # two wins, and both settings get whatever that was.
    bad += not check("the collector's own source is untouched",
                     (collector_defs.settings_for(written, "attic")
                      .get("source")), "attic-console")
    bad += not check("and the driver's option of the same name is its own",
                     settings.get("source"),
                     "the driver's own idea of source")

    # And the whole reason for the prefix: the driver is built from it.
    one = weewxdrivers.by_module(module, where)
    built = weewxdrivers.config_dict_for(one, settings)
    bad += not check("and it reaches the driver",
                     built["Faux"]["port"], "/dev/ttyUSB7")
    bad += not check("with what was not chosen left at the driver's default",
                     built["Faux"]["baudrate"], "19200")
    return bad


#: A driver in the shape WeeWX's own are in, for the form to be read out of.
#: Not one of WeeWX's: this test runs where WeeWX is not installed, and a
#: fixture that is only there sometimes is a check that only runs sometimes.
FAUX_DRIVER = '''"""A driver that exists to be read, never run."""
DRIVER_NAME = 'Faux'
DRIVER_VERSION = '1.0'


def loader(config_dict, engine):
    raise NotImplementedError("this one is only ever read")


class FauxConfEditor:
    @property
    def default_stanza(self):
        return """
[Faux]
    # This section is for the Faux console.

    # Connection type: serial or ethernet
    type = serial

    # Where the console is plugged in
    port = /dev/faux0

    # The address of the console
    host = 1.2.3.4

    ####################################################
    # The rest of this section rarely needs attention.
    ####################################################

    # Serial baud rate
    baudrate = 19200

    # How long to wait, in seconds
    timeout = 4

    # The station model
    model = Faux 1000

    # What this driver happens to call the thing it reads. A name the
    # collector uses too, which is the collision the prefix is for.
    source = the console

    # The driver to use:
    driver = weewx.drivers.faux
"""

    def prompt_for_settings(self):
        settings = dict()
        settings['type'] = self._prompt('type', 'serial', ['serial', 'ethernet'])
        if settings['type'] == 'serial':
            settings['port'] = self._prompt('port', '/dev/faux0')
        else:
            settings['host'] = self._prompt('host')
        return settings


def confeditor_loader():
    return FauxConfEditor()
'''


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


def get_with_headers(url: str) -> tuple[int, str, dict[str, str]]:
    """GET a page and retain the response headers as part of its contract."""
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            headers = {key.lower(): value for key, value in r.headers.items()}
            return r.status, r.read().decode("utf-8", "replace"), headers
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        return exc.code, "", headers


def get(url: str) -> tuple[int, str]:
    code, body, _headers = get_with_headers(url)
    return code, body


def post(url: str, form: dict) -> tuple[int, str]:
    data = urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(url, data=data)
    try:
        # A save answers 303 so that a reload does not save again. Follow it
        # only when asked, so the redirect itself can be checked.
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        _NoRedirect.last = exc.headers.get("Location", "")
        return exc.code, exc.read().decode("utf-8", "replace")


def _location(_body: str) -> str:
    """The Location of the last redirect `post` saw.

    Kept on the handler rather than returned, so `post` keeps the two-value
    shape every other caller here is written against.
    """
    return _NoRedirect.last


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    last = ""

    def redirect_request(self, *_args, **_kwargs):
        return None


SKIN = b"""[ImageGenerator]
    image_width = 1000
    width = 3
    chart_line_colors = "#4282b4", "#b44242"
    show_daynight = true
    skip_if_empty = year
    aggregate_type = none

    [[day_images]]
        time_length = 27h
        [[[daytempdew]]]
            [[[[outTemp]]]]
            [[[[dewpoint]]]]
        [[[dayrain]]]
            plot_type = bar
            [[[[rain]]]]
                aggregate_type = sum
                aggregate_interval = 1h
                label = Rain (hourly total)

    [[year_images]]
        time_length = 365d
        [[[yearrain]]]
            plot_type = bar
            [[[[rain]]]]
                aggregate_type = sum
                aggregate_interval = 1w
"""


def multipart(fields: dict, files: dict) -> tuple[str, bytes]:
    """A form the way a browser posts one with a file in it."""
    boundary = "----weewxevotest"
    out = []
    for key, value in fields.items():
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                   f'name="{key}"\r\n\r\n{value}\r\n'.encode())
    for key, (name, data) in files.items():
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                   f'name="{key}"; filename="{name}"\r\n'
                   "Content-Type: text/plain\r\n\r\n".encode()
                   + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(out)


def upload(url: str, fields: dict, files: dict) -> str:
    ctype, body = multipart(fields, files)
    request = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(request, timeout=20) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.read().decode("utf-8", "replace")


def said(html: str, kind: str = "ok") -> str:
    """What the page told the operator, wherever it put it.

    Two places once: a banner at the top and the same words again in the
    body, so a save said "Saved." twice, one under the other. There is one
    now, and this asks the question the test means -- did the page say it --
    rather than the one it happened to be written against.
    """
    for pattern in (f'<p class="{kind}">([^<]*)',
                    f'<div class="banner {kind}">([^<]*)'):
        found = re.search(pattern, html)
        if found:
            return found.group(1).strip()
    return ""



@lru_cache(maxsize=1)
def _no_javascript() -> str:
    """A node with jsdom, or a word saying why not."""
    if shutil.which("node") is None:
        return "there is no node on PATH"
    found = subprocess.run(["node", "-e", "require('jsdom')"],
                           capture_output=True, text=True, check=False)
    if found.returncode != 0:
        return "node is there but jsdom is not (npm install -g jsdom)"
    return ""


def _buttons_without_javascript(rendered: str) -> dict:
    """Parse the form ownership rules this test needs with the stdlib.

    In HTML, a nested ``<form>`` start tag is ignored, while its closing tag
    still closes the open form. That is the browser rule behind the regression
    this check guards; a plain stack of balanced source tags would miss it.
    """
    from html.parser import HTMLParser

    class Wiring(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.current: tuple[str | None, str | None] | None = None
            self.forms: list[str | None] = []
            self.form_ids: dict[str, str | None] = {}
            self.buttons: list[dict[str, object]] = []
            self.fields: list[dict[str, object]] = []
            self.open_buttons: list[dict[str, object]] = []

        @staticmethod
        def attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
            return {key: value or "" for key, value in attrs}

        def owner(self, attrs: dict[str, str]) -> tuple[str, str | None] | None:
            explicit = attrs.get("form")
            if explicit:
                return "id", explicit
            if self.current is not None:
                return "action", self.current[1]
            return None

        def handle_starttag(self, tag: str,
                            attrs: list[tuple[str, str | None]]) -> None:
            values = self.attributes(attrs)
            if tag == "form":
                # Browsers ignore a form start inside an already-open form.
                if self.current is None:
                    action = values.get("action")
                    ident = values.get("id") or None
                    self.current = ident, action
                    self.forms.append(action)
                    if ident:
                        self.form_ids[ident] = action
                return

            is_button = tag == "button" or (
                tag == "input" and values.get("type", "").lower() == "submit")
            if is_button:
                button = {"owner": self.owner(values), "text": []}
                self.buttons.append(button)
                if tag == "button":
                    self.open_buttons.append(button)

            if tag in ("input", "select", "textarea") and values.get("name"):
                self.fields.append({"name": values["name"],
                                    "owner": self.owner(values)})

        def handle_endtag(self, tag: str) -> None:
            if tag == "form":
                self.current = None
            elif tag == "button" and self.open_buttons:
                self.open_buttons.pop()

        def handle_data(self, data: str) -> None:
            if self.open_buttons:
                self.open_buttons[-1]["text"].append(data)

        def action(self, owner: object) -> str | None:
            if owner is None:
                return None
            kind, value = owner
            return self.form_ids.get(value) if kind == "id" else value

        def result(self) -> dict:
            buttons = [{
                "label": "".join(one["text"]).strip(),
                "action": self.action(one["owner"]),
            } for one in self.buttons]
            return {
                "forms": self.forms,
                "buttons": buttons,
                "orphans": [one["label"] for one in buttons
                            if one["action"] is None],
                "strandedFields": [one["name"] for one in self.fields
                                   if self.action(one["owner"]) is None],
            }

    parser = Wiring()
    parser.feed(rendered)
    parser.close()
    return parser.result()


def _buttons(tmp: Path, name: str, rendered: str) -> dict:
    """What a browser makes of the page: which form each control is in."""
    if _no_javascript():
        return _buttons_without_javascript(rendered)
    where = tmp / f"page-{name.replace(':', '-')}.html"
    where.write_text(rendered, encoding="utf-8")
    script = Path(__file__).resolve().parent / "admin_page_test.js"
    finished = subprocess.run(["node", str(script), str(where)],
                              capture_output=True, text=True, timeout=60,
                              check=False)
    if finished.returncode != 0 or not finished.stdout.strip():
        raise RuntimeError(f"could not parse {name}: "
                           f"{finished.stderr.strip()[:300]}")
    return json.loads(finished.stdout)


def _primary_links(rendered: str) -> list[list[str]]:
    """The destinations in each desktop/mobile copy of the primary nav."""
    sections = re.findall(
        r'<nav class="primary-nav" aria-label="Primary">(.*?)</nav>',
        rendered, flags=re.DOTALL)
    return [re.findall(r'href="([^"]+)"', section) for section in sections]


def _primary_current(rendered: str) -> list[str]:
    """The selected destination in each copy of the primary nav."""
    sections = re.findall(
        r'<nav class="primary-nav" aria-label="Primary">(.*?)</nav>',
        rendered, flags=re.DOTALL)
    return [match.group(1) for section in sections
            if (match := re.search(
                r'href="([^"]+)"[^>]*aria-current="page"', section))]


def drivers_seen() -> list[str]:
    """Which drivers are installed, whatever they declare.

    Asked of the registry rather than of the settings pages: a driver with
    nothing to configure has no page, and that is not the same as absent.
    """
    from weewx_evo.ingest import drivers as driver_registry

    driver_registry.DEFAULT.load()
    return list(driver_registry.DEFAULT.canonical_names())


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-admin-"))
    failures = 0
    try:
        path = tmp / "evo.toml"
        # The page knows which file it edits, so the schemas do too.
        schemas = lambda: all_schemas(path)  # noqa: E731
        # Rate limiting off: this drives the page far faster than a person
        # can, and it is tools/ratelimit_test.py that tests the limit.
        admin = Admin(path, schemas, TOKEN, limits=Limits(rate=0, failures=0))
        server = AdminServer(admin, "127.0.0.1", 0)
        server.start()
        base = f"http://127.0.0.1:{server.port}"
        print(f"admin on {base}, config in {path}")

        print("\nwhat declares settings")
        names = [s.name for s in admin.schemas]
        failures += not check("the core does", "core" in names, True)
        # Not "and the ecowitt driver": the six that ship declare nothing
        # now, and the mechanism is checked below with a driver written for
        # the purpose -- which is the case that matters, since a driver from
        # outside the repository is the one that has settings of its own.
        failures += not check("and it knows the drivers",
                              "ecowitt" in drivers_seen(), True)
        kinds = {s.kind for s in admin.schemas} | {"driver"}
        # Every kind the page groups by has to be represented, or a whole
        # heading in the sidebar is quietly empty. Exports appear only once
        # one is configured, so they are not expected here.
        failures += not check("the core, the drivers and the feeds",
                              {"core", "driver", "feed"} <= kinds, True)
        # One page per configured feed, named `feed:<name>`. A file that
        # names none is running the two that ship, and the page shows those.
        failures += not check("the JSON feed among them",
                              "feed:json" in names, True)

        print("\nno token, no page")
        for where in ("/", "/core", "/wrong-token/core", "/schema.json"):
            code, _ = get(base + where)
            failures += not check(f"GET {where}", code, 404)

        print("\nthe root is the overview, not a form")
        code, html, response_headers = get_with_headers(f"{base}/{TOKEN}/")
        failures += not check("it loads", code, 200)
        # Arriving on a form was right when there were a dozen settings and
        # one of everything. Somebody opening this almost never wants to
        # change a value; they want to know whether it is working.
        failures += not check("it is the overview",
                              "<h2>Overview</h2>" in html, True)
        failures += not check("and not the Core form",
                              'name="interval__amount"' in html, False)

        print("\nthe admin response is not embeddable or reusable")
        expected_headers = {
            "cache-control": "no-store",
            "x-frame-options": "DENY",
            "x-content-type-options": "nosniff",
            "referrer-policy": "no-referrer",
            "content-security-policy": (
                "default-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'; "
                "connect-src 'self'; img-src 'self' data:; "
                "style-src 'unsafe-inline'; script-src 'unsafe-inline'"),
            "permissions-policy": "camera=(), microphone=(), geolocation=()",
        }
        failures += not check(
            "every security header has the intended value",
            {name: response_headers.get(name) for name in expected_headers},
            expected_headers)

        print("\nthe page renders every kind of field")
        code, html = get(f"{base}/{TOKEN}/core")
        failures += not check("it loads", code, 200)
        for needle, what in (
            ('name="port"', "a number"),
            ('type="password"', "a secret"),
            ('class="switch"', "a switch for booleans"),
            ('name="interval__amount"', "a duration as a number"),
            ('name="interval__unit"', "with a unit beside it"),
            (">minutes<", "and the units spelled out"),
            # Feeds and exports had a sidebar heading each, and one entry
            # per configured thing under them, so the navigation grew with
            # the installation. They share one entry now and the instances
            # are on its page -- but the way in still has to exist before
            # anything is configured, which is what this checks.
            ("./publishing", "a way to feeds and exports, before there are any"),
        ):
            failures += not check(what, needle in html, True)

        core = next(s for s in admin.schemas if s.name == "core")
        core_names = {option.name for group in core.groups
                      for option in group.options}
        place_names = {
            "archive_db", "station.name", "station.latitude",
            "station.longitude", "station.altitude", "station.url",
            "station.rain_year_start",
        }
        failures += not check("the core schema owns no Place values",
                              sorted(core_names & place_names), [])
        failures += not check(
            "the core form exposes no Place values",
            (bool(re.search(r'name="station\.', html)),
             'name="archive_db"' in html),
            (False, False))

        primary = ["./overview", "./senders", "./places",
                   "./publishing", "./system"]
        failures += not check("desktop and mobile have five fixed destinations",
                              _primary_links(html), [primary, primary])

        print("\nand Publishing contains its tools")
        code, publishing = get(f"{base}/{TOKEN}/publishing")
        failures += not check("the page loads", code, 200)
        for needle, what in (
            ('aria-labelledby="publishing-feeds"', "it inventories feeds"),
            ('aria-labelledby="publishing-exports"', "it inventories exports"),
            ('aria-labelledby="publishing-uploads"', "it inventories uploads"),
            ('aria-labelledby="publishing-notifications"',
             "it inventories notifications"),
            ('aria-labelledby="publishing-forecasts"',
             "it inventories forecasts"),
            ('href="./new-feed"', "it offers to add a feed"),
            ('href="./new-export"', "it offers to add an export"),
            ('href="./new-forecast"', "it offers to add a forecast"),
            ('href="./charts"', "it links to charts"),
        ):
            failures += not check(what, needle in publishing, True)

        print("\nand Charts belongs to Publishing")
        code, charts = get(f"{base}/{TOKEN}/charts")
        failures += not check("the page loads", code, 200)
        failures += not check("its own page offers both ways in",
                              "./new-plot" in charts
                              and "./import-plots" in charts, True)
        failures += not check("Publishing is selected while Charts is open",
                              _primary_current(charts),
                              ["./publishing", "./publishing"])
        failures += not check("Charts is not a sixth primary destination",
                              any("./charts" in links
                                  for links in _primary_links(charts)), False)

        print("\nwhat can be chosen is offered, not typed")
        # The point of a settings page over the command line: you can see the
        # options without reading the documentation first.
        failures += not check("the driver is a dropdown",
                              'id="f-driver"' in html and "<select" in html, True)
        failures += not check("listing what is installed",
                              ">ecowitt<" in html, True)
        failures += not check("who is answered has suggestions",
                              'list="l-allow"' in html, True)
        failures += not check("including the bounded and broad choices",
                              ('<option value="private"' in html,
                               '<option value="any"' in html), (True, True))
        failures += not check("and the alternatives are visible without opening it",
                              'class="alt"' in html, True)
        failures += not check("no secret is rendered back",
                              "admin-token-for-the-test" in html.replace(
                                  f"./{TOKEN}", ""), False)

        print("\nPlace values save through the Place route")
        code, _ = post(f"{base}/{TOKEN}/places/default/set", {
            "label": "Kirchdorf",
            "latitude": "48.4596",
            "longitude": "11.6539",
            "altitude": "440",
            "rain_year_start": "10",
        })
        failures += not check("saving the default Place redirects", code, 303)
        places_path = path.parent / "archives.toml"
        failures += not check("the Place file is there", places_path.exists(), True)
        placed = config_file.read(places_path)
        default_place = (placed.get("archives") or {}).get("default") or {}
        failures += not check(
            "the Place values are in archives.toml",
            (default_place.get("label"), default_place.get("latitude"),
             default_place.get("longitude"), default_place.get("altitude"),
             default_place.get("rain_year_start")),
            ("Kirchdorf", 48.4596, 11.6539, 440.0, 10))
        code, _ = post(f"{base}/{TOKEN}/new-place", {"label": "Roof"})
        failures += not check("a Place is created on the canonical route",
                              code, 303)
        placed = config_file.read(places_path)
        failures += not check("the new Place also lands in archives.toml",
                              config_file.get(placed, "archives.roof.label"),
                              "Roof")

        print("\nsaving Core writes only Core values")
        code, _ = post(f"{base}/{TOKEN}/core", {
            # Old forms or bookmarks cannot restore the former authority.
            "station.name": "Wrong authority",
            "station.latitude": "1",
            "archive_db": "wrong.sdb",
            "interval__amount": "5", "interval__unit": "m",
            "grace__amount": "15", "grace__unit": "s",
            "loop_hilo": "1",
            "live_db": "data/live.sdb",
            "retention__amount": "7", "retention__unit": "d",
            "raw_retention__amount": "1", "raw_retention__unit": "h",
            "host": "127.0.0.1",
            "port": "8000",
            "rate": "12.5",
            "token": "an-upload-token",
            "driver": "ecowitt",
            "udp_port": "0",
        })
        failures += not check("it redirects rather than re-saving", code, 303)
        failures += not check("the file is there", path.exists(), True)

        written = config_file.read(path)
        failures += not check("a string", config_file.get(written, "host"),
                              "127.0.0.1")
        failures += not check("a float", config_file.get(written, "rate"), 12.5)
        failures += not check("a duration, written readably",
                              config_file.get(written, "interval"), "5m")
        failures += not check("a boolean",
                              config_file.get(written, "loop_hilo"), True)
        failures += not check("an int", config_file.get(written, "port"), 8000)
        failures += not check(
            "legacy Place fields were ignored",
            (config_file.get(written, "station.name"),
             config_file.get(written, "station.latitude"),
             config_file.get(written, "archive_db")),
            (None, None, None))
        still_placed = config_file.read(places_path)
        failures += not check(
            "and Core did not change the Place",
            config_file.get(still_placed, "archives.default.label"),
            "Kirchdorf")

        print("\nand it comes back as the right types")
        values = config_file.values_for(written, core)
        parsed, errors = core.parse(values)
        failures += not check("no complaints on a round trip", errors, {})
        failures += not check("the duration is seconds again", parsed["interval"], 300)

        print("\nbad values are refused, and nothing is written")
        before = path.read_text(encoding="utf-8")
        code, html = post(f"{base}/{TOKEN}/core", {
            "interval__amount": "1", "interval__unit": "s",
            "port": "70000",
            "token": "an-upload-token",
        })
        failures += not check("it stays on the page", code, 200)
        failures += not check("and says what is wrong",
                              "cannot be above 65535" in html, True)
        failures += not check("for every field, not just the first",
                              "cannot be below" in html, True)
        failures += not check("the file is untouched",
                              path.read_text(encoding="utf-8"), before)

        print("\na required setting left empty is refused")
        code, html = post(f"{base}/{TOKEN}/core", {"token": "", "port": "8000"})
        failures += not check("says so", "is required" in html, True)

        print("\nsecrets are never sent back to the browser")
        code, html = get(f"{base}/{TOKEN}/core")
        failures += not check("the token is not in the page",
                              "an-upload-token" in html, False)
        failures += not check("but the field shows it is set",
                              "type=\"password\"" in html and "value=\"" in html, True)
        # Dots came back means "leave it alone", not "set it to dots".
        post(f"{base}/{TOKEN}/core", {"token": "•" * 12, "port": "8000"})
        again = config_file.read(path)
        failures += not check("saving the mask keeps the secret",
                              config_file.get(again, "token"), "an-upload-token")

        print("\na driver that declares settings gets a page of its own")
        # A driver of this test's own rather than one of the six that ship.
        # None of those declares anything any more: what they used to ask --
        # what to do with a field name the catalog does not have, and how far
        # a console's clock may be out -- is a policy of the installation and
        # a property of a console, so it moved to the core and to
        # stations.toml. The mechanism is unchanged, and it is what a driver
        # from outside the repository hangs on, so it is checked with one.
        from weewx_evo.ingest import drivers as driver_registry
        from weewx_evo.options import Group, Option

        class _Probe:
            @staticmethod
            def options():
                return [Group("Its own", "", (
                    Option("depth", "How deep the probe is", kind="choice",
                           default="shallow",
                           choices=(("shallow", "in the top soil"),
                                    ("deep", "under the frost line"))),
                ), prefix="drivers.probe")]

            def __init__(self, depth="shallow", **ignored):
                self.depth = depth

            def packets(self, body, meta):
                return []

        driver_registry.DEFAULT.register("probe", _Probe(), replace=True)
        # The pages are built once and kept; a driver registered after that
        # has no page until the list is rebuilt. Which is also what the
        # running service does after installing one.
        admin.refresh()
        code, html = get(f"{base}/{TOKEN}/probe")
        failures += not check("it loads", code, 200)
        failures += not check("with what the driver declared",
                              "depth" in html, True)
        failures += not check("including its choices",
                              "under the frost line" in html, True)
        post(f"{base}/{TOKEN}/probe", {"depth": "deep"})
        saved = config_file.read(path)
        failures += not check("saved under the driver's name",
                              config_file.get(saved, "drivers.probe.depth"),
                              "deep")
        failures += not check("the core's settings are untouched",
                              config_file.get(saved, "host"), "127.0.0.1")

        print("\nand the six protocols that ship declare nothing")
        # Six arrived at once, so this was six pages carrying the same three
        # fields, not one of which describes a protocol.
        theirs = [one.name for one in admin.schemas
                  if one.kind == "driver" and one.name != "probe"]
        failures += not check("no page for any of them", theirs, [])

        # A sender, so the senders page has rows with buttons on them.
        # An empty table renders no forms and would pass the check below
        # without testing anything.
        code, rendered = post(f"{base}/{TOKEN}/new-sender",
                              {"name": "garden", "driver": "wunderground"})
        failures += not check("a sender is created on the canonical route",
                              (code, "garden" in rendered), (200, True))

        print("\nthe way to add one is always there")
        # "Add an upload" was inside the "none yet" branch, so it vanished
        # the moment an upload existed -- and the live one sets itself up
        # from a local export. On a station publishing anything at all there
        # was then no way from this page to Weather Underground or any of the
        # others, which reads as the feature being missing entirely.
        for page, wanted in (("publishing", ("./new-feed", "./new-export",
                                             "./new-upload")),
                             ("senders", ("./new-sender",)),
                             ("places", ("./new-place",)),
                             ("charts", ("./new-plot",))):
            _code, rendered = get(f"{base}/{TOKEN}/{page}")
            for link in wanted:
                failures += not check(f"{page} offers {link}",
                                      f'href="{link}"' in rendered, True)

        # And one heading per page. The shell prints the page's name; seven
        # of these printed it again directly underneath.
        for page in ("new-feed", "new-export", "new-upload", "new-sender",
                     "new-place", "new-forecast", "new-plot"):
            _code, rendered = get(f"{base}/{TOKEN}/{page}")
            failures += not check(f"{page} says its name once",
                                  rendered.count("<h2>"), 1)

        print("\nevery button on every page is wired to something")
        # Read as text this page was perfect: every tag present, every one
        # closed. The nesting was wrong, and only a parser that follows the
        # HTML rules sees what that costs. Try it and Remove were rendered
        # inside the save form; HTML has no nested forms, so a browser drops
        # the inner `<form>` and keeps its `</form>`, closing the outer one
        # early. Save then belonged to no form and did nothing at all, and
        # Try it quietly submitted a save. Every export, feed, upload and
        # forecast page was like that, and none of the other checks here
        # noticed.
        why = _no_javascript()
        if why:
            print(f"  -- stdlib HTMLParser fallback: {why}")
            broken = _buttons_without_javascript(
                '<form action="./save"><form action="./test">'
                '<button>Test the connection</button></form>'
                '<input name="later"></form>')
            failures += not check(
                "the fallback applies browser rules to nested forms",
                (broken["buttons"][0]["action"], broken["strandedFields"]),
                ("./save", ["later"]))
        # OWN_PAGES too. The senders page renders a form per row -- adopt,
        # ignore, remove -- and was left out of this list when it was added,
        # so it shipped with all three inside the save form and Remove doing
        # nothing. Plus pages whose names carry an instance.
        pages = ([s.name for s in admin.schemas]
                 + list(ADD_PAGES) + list(OWN_PAGES)
                 + admin_module.sub_pages(admin))
        for where in pages:
            code, rendered = get(f"{base}/{TOKEN}/{where}")
            if code != 200:
                failures += not check(f"{where} loads", code, 200)
                continue
            seen = _buttons(tmp, where, rendered)
            failures += not check(f"{where}: no button belongs to nothing",
                                  seen["orphans"], [])
            failures += not check(f"{where}: no field goes nowhere",
                                  seen["strandedFields"], [])
            # An add-page has one button and it submits the page. What must
            # never happen is a second action sharing the first one's form.
            for button in seen["buttons"]:
                if button["label"] not in ("Test the connection",
                                           "Fetch once", "Send one now",
                                           "Remove"):
                    continue
                failures += not check(
                    f"{where}: {button['label']!r} posts somewhere of its own",
                    (button["action"] or "").endswith(("/test", "/remove")),
                    True)

        print("\nthe schema is available as data")
        code, raw = get(f"{base}/{TOKEN}/schema.json")
        failures += not check("as JSON", code, 200)
        described = json.loads(raw)
        failures += not check("every component is in it",
                              len(described["components"]), len(admin.schemas))

        print("\nread-only means read-only")
        locked = Admin(path, schemas, TOKEN, read_only=True,
                       limits=Limits(rate=0, failures=0))
        locked_server = AdminServer(locked, "127.0.0.1", 0)
        locked_server.start()
        try:
            code, html = post(f"http://127.0.0.1:{locked_server.port}/{TOKEN}/core",
                              {"host": "changed", "token": "x"})
            failures += not check("refused", "read-only" in html, True)
            failures += not check("and nothing changed",
                                  config_file.get(config_file.read(path),
                                                  "host"), "127.0.0.1")
        finally:
            locked_server.stop()

        print("\nan export can be added from the page")
        # The page writes structure, not only values: without this an export
        # can only be created by editing the file, which defeats the point of
        # having a page at all.
        code, html_ = get(f"{base}/{TOKEN}/new-export")
        failures += not check("the form is there", code, 200)
        failures += not check("with the kinds", "rsync" in html_ and "ftp" in html_,
                              True)

        code, _ = post(f"{base}/{TOKEN}/new-export",
                       {"name": "website", "kind": "rsync"})
        failures += not check("creating redirects to it", code, 303)
        made = config_file.read(path)
        failures += not check("it is in the file",
                              config_file.get(made, "exports.website.kind"), "rsync")

        print("\nand gets a page of its own")
        code, html_ = get(f"{base}/{TOKEN}/export:website")
        failures += not check("it loads", code, 200)
        failures += not check("with what rsync declared",
                              "authorized_keys" in html_, True)
        # An export sends what a feed produced, so the source is a feed list.
        failures += not check("the source is a feed list",
                              'id="f-source"' in html_ and "<select" in html_, True)
        failures += not check("a way to try it", "Test the connection" in html_,
                              True)
        failures += not check("and a way to remove it", "Remove" in html_, True)

        print("\nits settings save under its own name")
        post(f"{base}/{TOKEN}/export:website",
             # No feed exists yet, so the directory is what is filled in.
             {"host": "example.org", "user": "weather",
              "directory": "/var/www", "source": "",
              "directory_source": "data/public_html"})
        saved = config_file.read(path)
        failures += not check("host", config_file.get(saved, "exports.website.host"),
                              "example.org")
        failures += not check("the kind is untouched",
                              config_file.get(saved, "exports.website.kind"),
                              "rsync")
        failures += not check("and the core is untouched",
                              config_file.get(saved, "host"), "127.0.0.1")

        print("\na second one does not disturb the first")
        post(f"{base}/{TOKEN}/new-export", {"name": "hoster", "kind": "ftp"})
        both = config_file.read(path)
        failures += not check("both are there",
                              sorted(both.get("exports", {})), ["hoster", "website"])
        failures += not check("the first kept its host",
                              config_file.get(both, "exports.website.host"),
                              "example.org")

        print("\nbad names are refused")
        for bad, why in [("", "empty"), ("Website", "capitals"),
                         ("2fast", "leading digit"), ("a/b", "a slash"),
                         ("website", "already taken")]:
            code, html_ = post(f"{base}/{TOKEN}/new-export",
                               {"name": bad, "kind": "ftp"})
            refused = code == 200 and ("may hold" in html_ or "already" in html_)
            failures += not check(f"{why}", refused, True)

        print("\ntesting says what happened, without sending")
        code, html_ = post(f"{base}/{TOKEN}/export:website/test", {})
        failures += not check("it answers", code, 200)
        failures += not check("with something to act on",
                              "rsync" in html_.lower() or "resolve" in html_.lower(),
                              True)

        print("\nremoving takes it out of the file")
        code, _ = post(f"{base}/{TOKEN}/export:hoster/remove", {})
        failures += not check("it redirects", code, 303)
        after = config_file.read(path)
        failures += not check("gone", sorted(after.get("exports", {})), ["website"])
        failures += not check("the other one stayed",
                              config_file.get(after, "exports.website.host"),
                              "example.org")

        print("\nan upload can be added the same way")
        code, html_ = get(f"{base}/{TOKEN}/new-upload")
        failures += not check("the form is there", code, 200)
        failures += not check("and the heading says what it is",
                              "<title>Add an upload" in html_
                              or ">Add an upload<" in html_, True)
        failures += not check("with the services",
                              "Weather Underground" in html_ and "CWOP" in html_,
                              True)

        code, _ = post(f"{base}/{TOKEN}/new-upload",
                       {"name": "wu", "kind": "wunderground"})
        failures += not check("creating redirects to it", code, 303)
        made = config_file.read(path)
        failures += not check("it is in the file",
                              config_file.get(made, "uploads.wu.kind"),
                              "wunderground")

        print("\nand gets a page with the service's own fields")
        code, html_ = get(f"{base}/{TOKEN}/upload:wu")
        failures += not check("it loads", code, 200)
        failures += not check("with the station id field",
                              'name="station"' in html_, True)
        failures += not check("and the key as a password field",
                              'type="password"' in html_, True)
        # Publishing the inside of somebody's house is a decision, so it is a
        # setting and it is off. A page that does not offer it would be
        # making the decision for them.
        failures += not check("indoor readings are offered and off",
                              "indoor temperature" in html_.lower(), True)
        failures += not check("a way to try it", "Test the account" in html_, True)
        failures += not check("and a way to remove it", "Remove" in html_, True)

        print("\nits settings save under its own name")
        post(f"{base}/{TOKEN}/upload:wu",
             {"station": "IBAYERN123", "password": "s3cret",
              "trigger": "record"})
        saved = config_file.read(path)
        failures += not check("station",
                              config_file.get(saved, "uploads.wu.station"),
                              "IBAYERN123")
        failures += not check("password",
                              config_file.get(saved, "uploads.wu.password"),
                              "s3cret")
        failures += not check("the export is untouched",
                              config_file.get(saved, "exports.website.host"),
                              "example.org")

        print("\ntwo services live side by side")
        post(f"{base}/{TOKEN}/new-upload", {"name": "windy", "kind": "windy"})
        both = config_file.read(path)
        failures += not check("both are there",
                              sorted(both.get("uploads", {})), ["windy", "wu"])
        failures += not check("the first kept its station",
                              config_file.get(both, "uploads.wu.station"),
                              "IBAYERN123")

        print("\nremoving an upload does not touch the exports")
        # The route carries what sort of thing it is as well as the name.
        # Without that, `upload:wu/remove` reaches the exports and deletes
        # whatever happens to share the name -- or nothing, silently.
        code, _ = post(f"{base}/{TOKEN}/upload:windy/remove", {})
        failures += not check("it redirects", code, 303)
        after = config_file.read(path)
        failures += not check("gone", sorted(after.get("uploads", {})), ["wu"])
        failures += not check("the export is still there",
                              config_file.get(after, "exports.website.host"),
                              "example.org")

        print("\na forecast source is added the same way")
        code, html_ = get(f"{base}/{TOKEN}/new-forecast")
        failures += not check("the form is there", code, 200)
        # The heading used to say "Add an export" on every add-page that was
        # not the feed one -- over a form that was nothing of the sort.
        failures += not check("and the heading says what it is",
                              "<title>Add a forecast" in html_
                              or ">Add a forecast<" in html_, True)
        failures += not check("with the sources",
                              "Open-Meteo" in html_ and "MeteoAlarm" in html_,
                              True)
        code, _ = post(f"{base}/{TOKEN}/new-forecast",
                       {"name": "ahead", "kind": "open-meteo"})
        failures += not check("creating redirects to it", code, 303)
        made = config_file.read(path)
        failures += not check("it is in the file",
                              config_file.get(made, "forecast.ahead.kind"),
                              "open-meteo")

        print("\nand gets a page with that source's own fields")
        code, html_ = get(f"{base}/{TOKEN}/forecast:ahead")
        failures += not check("it loads", code, 200)
        failures += not check("with the model choice", 'name="model"' in html_,
                              True)
        failures += not check("and how far ahead", 'name="days"' in html_, True)
        failures += not check("a way to fetch once", "Fetch once" in html_, True)
        # And the one question that is not the source's own: a forecast
        # is an answer about a coordinate pair, so it belongs to a series.
        # Asked here because a setting nobody can reach from the page is
        # one that gets typed into the file by hand or not at all.
        failures += not check("and which series it is for",
                              'name="archive"' in html_, True)

        print("\na warning source is a second entry, not a setting")
        # No service does both the numbers and the warnings well, so two
        # sources is the ordinary arrangement here rather than the exception.
        post(f"{base}/{TOKEN}/new-forecast",
             {"name": "warnings", "kind": "meteoalarm"})
        both = config_file.read(path)
        failures += not check("both are there",
                              sorted(both.get("forecast", {})),
                              ["ahead", "warnings"])
        code, html_ = get(f"{base}/{TOKEN}/forecast:warnings")
        failures += not check("with the country list",
                              "united-kingdom" in html_, True)

        print("\nits settings save under its own name")
        post(f"{base}/{TOKEN}/forecast:ahead",
             {"days": "10", "model": "icon_seamless",
              "archive": "default"})
        saved = config_file.read(path)
        failures += not check("days",
                              config_file.get(saved, "forecast.ahead.days"), 10)
        # The series reaches the file under this entry's own
        # name. A value that never arrives where something reads
        # it is the failure this whole page has had twice, and
        # both times the page said "saved".
        failures += not check(
            "and the series it is for",
            config_file.get(saved, "forecast.ahead.archive"),
            "default")
        failures += not check("the other source is untouched",
                              config_file.get(saved, "forecast.warnings.kind"),
                              "meteoalarm")
        failures += not check("and so is the upload",
                              config_file.get(saved, "uploads.wu.station"),
                              "IBAYERN123")

        print("\nremoving one leaves the uploads and exports alone")
        code, _ = post(f"{base}/{TOKEN}/forecast:warnings/remove", {})
        failures += not check("it redirects", code, 303)
        after = config_file.read(path)
        failures += not check("gone", sorted(after.get("forecast", {})),
                              ["ahead"])
        failures += not check("the upload is still there",
                              config_file.get(after, "uploads.wu.station"),
                              "IBAYERN123")
        failures += not check("and the export",
                              config_file.get(after, "exports.website.host"),
                              "example.org")

        print("\nthe previous version is kept")
        failures += not check("as .bak",
                              path.with_suffix(".toml.bak").exists(), True)

        print("\nfeeds are added the way exports are")
        # Several of one kind is the normal case: two sets of JSON in two
        # unit systems, or two themes side by side. Each writes its own
        # directory and has its own settings.
        code, _ = post(f"{base}/{TOKEN}/new-feed",
                       {"name": "metric", "kind": "json"})
        failures += not check("it redirects to the new page", code, 303)

        after = config_file.read(path).get("feeds") or {}
        # The two that ship were running unnamed. Adding a third has to
        # write them down first, or it silently turns them off.
        from weewx_evo import starter

        failures += not check("the shipped ones were written down",
                              sorted(after),
                              sorted([*starter.FEEDS, "metric"]))

        post(f"{base}/{TOKEN}/new-feed", {"name": "imperial",
                                          "kind": "json"})
        again = config_file.read(path).get("feeds") or {}
        failures += not check("two of one kind is fine",
                              sorted(k for k, v in again.items()
                                     if v.get("kind") == "json"),
                              ["imperial", "json", "metric"])

        _, html_said = post(f"{base}/{TOKEN}/new-feed",
                            {"name": "metric", "kind": "json"})
        failures += not check("but not the same name twice",
                              "already a feed" in html_said, True)
        _, html_said = post(f"{base}/{TOKEN}/new-feed",
                            {"name": "x", "kind": "sorcery"})
        failures += not check("nor a kind nothing provides",
                              "is not one of" in html_said, True)

        print("\n  and each gets its own page and its own settings")
        admin.refresh()
        pages = [s.name for s in admin.schemas if s.kind == "feed"]
        failures += not check("a page each", sorted(pages),
                              sorted(f"feed:{one}" for one in
                                     [*starter.FEEDS, "imperial", "metric"]))

        one = next(s for s in admin.schemas if s.name == "feed:metric")
        errors = admin.save(one, {"units": "METRICWX", "rounding": "2",
                                  "enabled": "1",
                                  MARKER + "enabled": "1"})
        failures += not check("saved without complaint", errors, {})
        stored = config_file.read(path)
        failures += not check("under its own name",
                              config_file.get(stored,
                                              "feeds.metric.units"),
                              "METRICWX")
        failures += not check("and the other one is untouched",
                              config_file.get(stored,
                                              "feeds.imperial.units"),
                              None)

        code, _ = post(f"{base}/{TOKEN}/feed:imperial/remove", {})
        failures += not check("removing one", code, 303)
        failures += not check("leaves the rest",
                              sorted(config_file.read(path)["feeds"]),
                              sorted([*starter.FEEDS, "metric"]))
        print("\na choice that offers 'none' can be set back to it")
        # Every dropdown with an empty entry was one way: an empty value
        # parsed to the option's default, so the old choice stayed. Nobody
        # could undo picking one, on any page, for any setting.
        from weewx_evo.options import Invalid

        offering_none = Option("example", "Example", kind="choice",
                               choices=(("", "-- none --"), ("a", "A")))
        failures += not check("empty is the empty choice, not the default",
                              offering_none.parse(""), "")
        failures += not check("and a real one still parses",
                              offering_none.parse("a"), "a")
        try:
            offering_none.parse("nonsense")
            failures += not check("a wrong one is refused", "accepted", "refused")
        except Invalid as exc:
            failures += not check("a wrong one is named by its label",
                                  "-- none --" in str(exc), True)

        without_none = Option("other", "Other", kind="choice", default="a",
                              choices=(("a", "A"), ("b", "B")))
        failures += not check("a choice with no empty entry still defaults",
                              without_none.parse(""), "a")

        print("\ncharts come in from a file, or pasted, or from a path")
        # The path is the one that does not work in a container: the skin is
        # in a different one. So the page takes a file and takes pasted text,
        # and this drives both the way a browser would.
        from weewx_evo import plots as plot_defs

        where = f"{base}/{TOKEN}/import-plots"
        html = upload(where, {}, {"upload": ("skin.conf", SKIN)})
        message = said(html)
        failures += not check("an uploaded file is read", "3 chart(s)" in message,
                              True)
        failures += not check("and it says where they came from",
                              "uploaded file" in message, True)
        charts = plot_defs.load(path.parent / "plots.toml")
        failures += not check("three charts landed", len(charts), 3)

        # WeeWX's suffixes are not ours: there, 1w is a week and 1h an hour.
        # Read by our rules 1w would be a day, and a year of weekly rainfall
        # would come out with 365 bars instead of 52.
        year = charts.get("yearrain")
        failures += not check("a weekly total stayed weekly",
                              year.lines[0].interval if year else None, "week")
        failures += not check("and the bar is still a bar",
                              year.lines[0].kind if year else None, "bar")
        day = charts.get("dayrain")
        # Three pixels on a 1000-wide chart is a thin line. Taken as three
        # pixels of a 500-wide one and then doubled for a sharp file, the
        # same number comes out four times too heavy -- a smear rather than
        # a line, which is what a day plot looked like.
        failures += not check("an hourly one stayed hourly",
                              day.lines[0].interval if day else None, "hour")
        failures += not check("skip_if_empty is a span, not a yes or no",
                              day.skip_if_empty if day else None, "year")

        failures += not check("a line width is read off its own image",
                              day.lines[0].width if day else None, 1.5)

        print("\n  and importing again does not double them")
        html = upload(where, {}, {"upload": ("skin.conf", SKIN)})
        failures += not check("nothing added the second time",
                              len(plot_defs.load(path.parent / "plots.toml")), 3)
        failures += not check("and it says so",
                              "left alone" in said(html), True)

        print("\n  pasted text works the same way")
        (path.parent / "plots.toml").unlink()
        html = upload(where, {"pasted": SKIN.decode()}, {})
        failures += not check("read", "3 chart(s)" in said(html), True)
        failures += not check("and named as pasted, not as a file",
                              "pasted text" in said(html), True)

        print("\n  and what is not a skin.conf is refused, not half-imported")
        html = upload(where, {}, {"upload": ("notes.txt", b"milk\nbread\n")})
        failures += not check("named", "No [ImageGenerator]" in said(html, "err"),
                              True)
        failures += not check("nothing was written",
                              len(plot_defs.load(path.parent / "plots.toml")), 3)

        html = upload(where, {"pasted": "", "source": ""}, {"upload": ("", b"")})
        failures += not check("an empty form says what to do",
                              "Choose a file" in said(html, "err"), True)

        # Last, because it makes sixteen of everything, and every
        # list this test checks before here would be counting them.
        print("\na save sends the browser to a page, not one level below it")
        # `./senders?saved=1` looks right and is not: a browser resolves it
        # against the URL that was posted to, so saving a sender's
        # properties would land on `/<token>/senders/<name>/senders`. That
        # renders the senders page -- `_which` reads the segments backwards
        # and finds the last name it knows -- so nothing looks wrong, and
        # every link clicked from there keeps the extra segments.
        #
        # Which made the *feed* page unsaveable two clicks later: its Save
        # posted to `/<token>/senders/<name>/feed:wdc`, the router saw
        # `senders` among the segments, and the answer was "Unknown station
        # action 'feed:wdc'".
        # A second sender to save. Announced rather than assumed: a check that
        # posts to a name nobody created measures the error path instead of
        # the redirect.
        post(f"{base}/{TOKEN}/new-sender",
             {"name": "kitchen", "driver": "wunderground"})
        code, body = post(f"{base}/{TOKEN}/senders/kitchen/set", {})
        where = _location(body) or ""
        failures += not check("a sender save redirects", code, 303)
        failures += not check("to an absolute page under the token",
                              where.startswith(f"/{TOKEN}/senders"), True)
        failures += not check("and not one level deeper",
                              "/senders/kitchen/senders" in where, False)

        # And the guard behind it: the router asks what the verb is, not
        # whether a word appears in the path. Somebody with the old deep URL
        # in a bookmark has to be able to save too.
        code, body = post(f"{base}/{TOKEN}/senders/kitchen/feed:site",
                          {"enabled": "1"})
        failures += not check("a schema save works from any path", code, 303)
        failures += not check("and does not fall into the sender handler",
                              "Unknown station action" in body, False)

        print("\nevery kind can be made, and its page comes up")
        # The whole of what somebody does first: click add, choose a kind,
        # land on its settings. Two upload kinds shipped a default of ten
        # seconds under a minimum of sixty, so `field` raised while rendering
        # the very page the redirect goes to. A 500 on the first thing
        # anybody tries -- and the figure that caused it could not be
        # corrected from the page either.
        from weewx_evo import collectors as collector_defs
        from weewx_evo import exports as export_registry
        from weewx_evo import feeds as feed_registry
        from weewx_evo import notify as notify_registry
        from weewx_evo.admin import upload_kinds

        for what, kinds in (
                # `upload_kinds`, not every kind that exists: the live push
                # to this installation's own pages is set up by the export that
                # publishes them, so it is not offered here. Checked below.
                ("upload", sorted(upload_kinds())),
                ("export", sorted(export_registry.DEFAULT.kinds())),
                ("notify", sorted(notify_registry.kinds())),
                ("collector", sorted(collector_defs.KINDS)),
                ("feed", sorted(feed_registry.kinds()))):
            for kind in kinds:
                name = f"t{what[0]}{kind}".replace("-", "").replace("_", "")
                code, _body = post(f"{base}/{TOKEN}/new-{what}",
                                   {"name": name, "kind": kind})
                failures += not check(f"a {kind} {what} is made", code, 303)
                code, rendered = get(f"{base}/{TOKEN}/{what}:{name}")
                failures += not check(f"{kind} {what}: its page renders",
                                      code, 200)
                failures += not check(f"{kind} {what}: with a form on it",
                                      "<form" in rendered, True)

        # The quality page is written by hand rather than generated, so it
        # gets its own walk: render it, fill it in from the archive, and
        # render it again. The suggestion is the button the page exists for,
        # and it writes a file.
        code, rendered = get(f"{base}/{TOKEN}/quality")
        failures += not check("the quality page renders", code, 200)
        failures += not check("with a table on it", "<table" in rendered, True)

        code, _body = post(f"{base}/{TOKEN}/quality/suggest", {})
        failures += not check("its suggestions can be taken", code, 303)
        code, rendered = get(f"{base}/{TOKEN}/quality")
        failures += not check("and the page still renders after", code, 200)

        # And the rules it wrote must not refuse the readings they came
        # from. A page whose one button produces a rule that throws away
        # measurements is worse than no page -- measured once on a real
        # archive, a ceiling two seconds above a lightning timestamp refused
        # 36% of the records it was derived from.
        #
        # Asked of the dry run the page prints rather than of the word
        # "refuse", which is in its help text either way.
        code, rendered = get(f"{base}/{TOKEN}/quality")
        failures += not check(
            "the rules it wrote refuse nothing",
            "would refuse nothing" in rendered
            or "record(s), these rules would refuse" not in rendered, True)

        # And the one that is not offered cannot be reached by typing the URL
        # either. It was, and what people made was an upload with every field
        # empty -- including the units, so readings stored in Fahrenheit
        # published Fahrenheit into pages written in Celsius.
        code, rendered = post(f"{base}/{TOKEN}/new-upload",
                              {"name": "byhand", "kind": "webpush"})
        failures += not check("the live push is not one to add by hand",
                              code, 200)
        failures += not check("and it says what the choices are",
                              "is not one of" in rendered, True)

        # A collector's name is not cosmetic the way a feed's is: it is the
        # endpoint its packets arrive at, and a sender is matched on the
        # pair (driver, identity). One called `ecowitt` would take a real
        # driver's endpoint, and its uploads would go to the envelope parser,
        # fail there, and look like a console that had stopped.
        print("\na collector cannot take a name something already answers to")
        code, rendered = post(f"{base}/{TOKEN}/new-collector",
                              {"name": "json", "kind": "weewx-driver"})
        failures += not check("a reserved name is refused", code, 200)
        failures += not check("and it says why",
                              "already answers to" in rendered, True)

        # And the settings really reach the file, which is the whole point of
        # the page: `--collector shed` reads them back.
        print("\nwhat its page saves is what the collector runs with")
        post(f"{base}/{TOKEN}/new-collector",
             {"name": "shed", "kind": "weewx-driver"})
        # The form posts short names -- the page knows from its own path
        # which section they belong to. Sending `collectors.shed.conf` saved
        # nothing and looked like the page not working.
        code, _ = post(f"{base}/{TOKEN}/collector:shed",
                       {"kind": "weewx-driver",
                        "conf": "/etc/weewx/shed.conf",
                        "driver_file": "/opt/fousb.py",
                        "source": "WH1080 (USB)",
                        "catchup": "0", "batch": "5"})
        failures += not check("its settings save", code, 303)

        # `config_file` is imported at the top. Importing it again here
        # would make the name local to this whole function, and the earlier
        # uses of it -- three hundred lines up -- would fail on a variable
        # that is not assigned yet.
        from weewx_evo import collectors as saved_defs

        written = saved_defs.configured(config_file.read(path))
        failures += not check("and are in the file", "shed" in written, True)
        failures += not check("with the driver file it was given",
                              (written.get("shed") or {}).get("driver_file"),
                              "/opt/fousb.py")

        failures += the_hardware_form(base, path)

        print("\nthe collector page offers every registered kind")
        code, rendered = get(f"{base}/{TOKEN}/new-collector")
        failures += not check("the add page renders", code, 200)
        for kind in saved_defs.KINDS:
            failures += not check(f"{kind}: offered as a selectable value",
                                  f'<option value="{kind}"' in rendered, True)

        # And its own page says how to start it, because nothing else does:
        # the schema's help becomes a comment in the configuration file and
        # is never rendered, so landing here after creating one was a form
        # with no hint that a process somewhere else had to be started.
        code, rendered = get(f"{base}/{TOKEN}/collector:shed")
        failures += not check("its own page says how to start it",
                              "weewx-evo weewx-driver run --collector shed"
                              in rendered, True)

        # A collector could be created from the page and only ever removed
        # by editing the file: `remove_collector` and its route were both
        # here, and nothing rendered a button that called them.
        print("\nand it can be taken away again")
        failures += not check("its page offers a way to remove it",
                              "collector:shed/remove" in rendered, True)
        code, _ = post(f"{base}/{TOKEN}/collector:shed/remove", {})
        failures += not check("removing it redirects", code, 303)
        failures += not check(
            "and the file no longer has it",
            "shed" in saved_defs.configured(config_file.read(path)), False)


        server.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

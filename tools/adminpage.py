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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import config as config_file
from weewx_evo.admin import ADD_PAGES, MARKER, OWN_PAGES, Admin, AdminServer
from weewx_evo.cli import all_schemas
from weewx_evo.ratelimit import Limits

TOKEN = "admin-token-for-the-test"


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


def get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


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
        return exc.code, exc.read().decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
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



def _no_javascript() -> str:
    """A node with jsdom, or a word saying why not."""
    if shutil.which("node") is None:
        return "there is no node on PATH"
    found = subprocess.run(["node", "-e", "require('jsdom')"],
                           capture_output=True, text=True, check=False)
    if found.returncode != 0:
        return "node is there but jsdom is not (npm install -g jsdom)"
    return ""


def _buttons(tmp: Path, name: str, rendered: str) -> dict:
    """What a browser makes of the page: which form each control is in."""
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
        code, html = get(f"{base}/{TOKEN}/")
        failures += not check("it loads", code, 200)
        # Arriving on a form was right when there were a dozen settings and
        # one of everything. Somebody opening this almost never wants to
        # change a value; they want to know whether it is working.
        failures += not check("it is the overview",
                              "<h2>Overview</h2>" in html, True)
        failures += not check("and not the first form",
                              'name="station.latitude"' in html, False)

        print("\nthe page renders every kind of field")
        code, html = get(f"{base}/{TOKEN}/core")
        failures += not check("it loads", code, 200)
        for needle, what in (
            ('name="station.latitude"', "a number"),
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

        print("\nand that way leads to both, named as the two things they are")
        code, publishing = get(f"{base}/{TOKEN}/publishing")
        failures += not check("the page loads", code, 200)
        for needle, what in (
            ("A feed makes files", "it says what a feed is"),
            ("An export moves them", "and what an export is"),
            ("./new-feed", "and offers to add one of each"),
            ("./new-export", "the other one too"),
        ):
            failures += not check(what, needle in publishing, True)

        print("\nand the charts are one entry, not a hundred")
        code, charts = get(f"{base}/{TOKEN}/charts")
        failures += not check("the page loads", code, 200)
        # The sidebar used to hold them, first flat and then in collapsed
        # groups. Neither had room to say what a chart draws, which is what
        # you are actually looking for.
        failures += not check("its own page offers both ways in",
                              "./new-plot" in charts
                              and "./import-plots" in charts, True)
        failures += not check("and the sidebar has one link to it",
                              html.count('href="./charts"'), 1)

        print("\nwhat can be chosen is offered, not typed")
        # The point of a settings page over the command line: you can see the
        # options without reading the documentation first.
        failures += not check("the driver is a dropdown",
                              'id="f-driver"' in html and "<select" in html, True)
        failures += not check("listing what is installed",
                              ">ecowitt<" in html, True)
        failures += not check("who is answered has suggestions",
                              'list="l-allow"' in html, True)
        failures += not check("naming the usual ones",
                              "the local network" in html, True)
        failures += not check("and the alternatives are visible without opening it",
                              'class="alt"' in html, True)
        failures += not check("no secret is rendered back",
                              "admin-token-for-the-test" in html.replace(
                                  f"./{TOKEN}", ""), False)

        print("\nsaving writes the file")
        code, _ = post(f"{base}/{TOKEN}/core", {
            "station.name": "Kirchdorf",
            "station.latitude": "48.4596",
            "station.longitude": "11.6539",
            "station.altitude": "440",
            "interval__amount": "5", "interval__unit": "m",
            "grace__amount": "15", "grace__unit": "s",
            "loop_hilo": "1",
            "archive_db": "data/weewx.sdb",
            "live_db": "data/live.sdb",
            "retention__amount": "7", "retention__unit": "d",
            "raw_retention__amount": "1", "raw_retention__unit": "h",
            "host": "0.0.0.0",
            "port": "8000",
            "token": "an-upload-token",
            "driver": "ecowitt",
            "udp_port": "0",
        })
        failures += not check("it redirects rather than re-saving", code, 303)
        failures += not check("the file is there", path.exists(), True)

        written = config_file.read(path)
        failures += not check("a string", config_file.get(written, "station.name"),
                              "Kirchdorf")
        failures += not check("a float",
                              config_file.get(written, "station.latitude"), 48.4596)
        failures += not check("a duration, written readably",
                              config_file.get(written, "interval"), "5m")
        failures += not check("a boolean",
                              config_file.get(written, "loop_hilo"), True)
        failures += not check("an int", config_file.get(written, "port"), 8000)

        print("\nand it comes back as the right types")
        core = next(s for s in admin.schemas if s.name == "core")
        values = config_file.values_for(written, core)
        parsed, errors = core.parse(values)
        failures += not check("no complaints on a round trip", errors, {})
        failures += not check("the duration is seconds again", parsed["interval"], 300)

        print("\nbad values are refused, and nothing is written")
        before = path.read_text(encoding="utf-8")
        code, html = post(f"{base}/{TOKEN}/core", {
            "station.latitude": "999",
            "interval__amount": "1", "interval__unit": "s",
            "port": "70000",
            "token": "an-upload-token",
        })
        failures += not check("it stays on the page", code, 200)
        failures += not check("and says what is wrong",
                              "cannot be above 90" in html, True)
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
                              config_file.get(saved, "station.name"), "Kirchdorf")

        print("\nand the six protocols that ship declare nothing")
        # Six arrived at once, so this was six pages carrying the same three
        # fields, not one of which describes a protocol.
        theirs = [one.name for one in admin.schemas
                  if one.kind == "driver" and one.name != "probe"]
        failures += not check("no page for any of them", theirs, [])

        # A station, so the stations page has rows with buttons on them.
        # An empty table renders no forms and would pass the check below
        # without testing anything.
        from weewx_evo import stations as station_defs
        register = station_defs.Register()
        register.add(station_defs.Station("garden", "wunderground",
                                          "evo-abc123"))
        station_defs.save(station_defs.path_for(path.parent), register)

        print("\nthe way to add one is always there")
        # "Add an upload" was inside the "none yet" branch, so it vanished
        # the moment an upload existed -- and the live one sets itself up
        # from a local export. On a station publishing anything at all there
        # was then no way from this page to Weather Underground or any of the
        # others, which reads as the feature being missing entirely.
        for page, wanted in (("publishing", ("./new-feed", "./new-export",
                                             "./new-upload")),
                             ("stations", ("./new-station",)),
                             ("charts", ("./new-plot",))):
            _code, rendered = get(f"{base}/{TOKEN}/{page}")
            for link in wanted:
                failures += not check(f"{page} offers {link}",
                                      f'href="{link}"' in rendered, True)

        # And one heading per page. The shell prints the page's name; seven
        # of these printed it again directly underneath.
        for page in ("new-feed", "new-export", "new-upload", "new-station",
                     "new-archive", "new-forecast", "new-plot"):
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
            print(f"  -- skipped: {why}")
        else:
            # OWN_PAGES too. The stations page renders a form per row --
            # adopt, ignore, remove -- and was left out of this list when it
            # was added, so it shipped with all three inside the save form
            # and Remove doing nothing. That is the failure this check exists
            # for, missed because the list of pages was short.
            pages = ([s.name for s in admin.schemas]
                     + list(ADD_PAGES) + list(OWN_PAGES))
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
                # An add-page has one button and it submits the page: that
                # is the page. What must never happen is a *second* action
                # sharing the first one's form, because then it is not a
                # second action at all -- Try it and Remove each need an
                # address of their own.
                for button in seen["buttons"]:
                    if button["label"] not in ("Test the connection",
                                               "Fetch once", "Send one now",
                                               "Remove"):
                        continue
                    failures += not check(
                        f"{where}: {button['label']!r} posts somewhere of "
                        f"its own",
                        (button["action"] or "").endswith(
                            ("/test", "/remove")), True)

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
                              {"station.name": "changed", "token": "x"})
            failures += not check("refused", "read-only" in html, True)
            failures += not check("and nothing changed",
                                  config_file.get(config_file.read(path),
                                                  "station.name"), "Kirchdorf")
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
        # An export sends what a feed produced, so the source is a list of
        # feeds -- and says so when there are none rather than showing an
        # empty dropdown.
        failures += not check("the source is a feed list",
                              'id="f-source"' in html_ and "<select" in html_, True)
        failures += not check("saying what to do while there are none",
                              "a directory instead" in html_, True)
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
                              config_file.get(saved, "station.name"), "Kirchdorf")

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
        # Nothing here needs an account, and the page says so -- that is the
        # difference between this and every commercial forecast API.
        failures += not check("and says nothing needs an account",
                              "needs no account" in html_, True)

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
             {"days": "10", "model": "icon_seamless"})
        saved = config_file.read(path)
        failures += not check("days",
                              config_file.get(saved, "forecast.ahead.days"), 10)
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
        failures += not check("the shipped ones were written down",
                              sorted(after), ["diagnostic", "json",
                                              "metric"])

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
                              ["feed:diagnostic", "feed:imperial",
                               "feed:json", "feed:metric"])

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
                              ["diagnostic", "json", "metric"])
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

        server.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

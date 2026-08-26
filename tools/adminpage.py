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
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import config as config_file  # noqa: E402
from weewx_evo.admin import Admin, AdminServer  # noqa: E402
from weewx_evo.ratelimit import Limits  # noqa: E402
from weewx_evo.cli import all_schemas  # noqa: E402

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
    image_width = 500
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
    found = re.search(f'<p class="{kind}">([^<]*)', html)
    return found.group(1) if found else ""


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
        failures += not check("and the ecowitt driver", "ecowitt" in names, True)
        kinds = {s.kind for s in admin.schemas}
        # Every kind the page groups by has to be represented, or a whole
        # heading in the sidebar is quietly empty. Exports appear only once
        # one is configured, so they are not expected here.
        failures += not check("the core, the drivers and the feeds",
                              {"core", "driver", "feed"} <= kinds, True)
        failures += not check("the JSON feed among them",
                              "feeds.json" in names, True)

        print("\nno token, no page")
        for where in ("/", "/core", "/wrong-token/core", "/schema.json"):
            code, _ = get(base + where)
            failures += not check(f"GET {where}", code, 404)

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
            ("Feeds", "a place for feeds, before there are any"),
            ("Exports", "and one for exports, which are a different thing"),
        ):
            failures += not check(what, needle in html, True)

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

        print("\nthe driver's own settings are a page of their own")
        code, html = get(f"{base}/{TOKEN}/ecowitt")
        failures += not check("it loads", code, 200)
        failures += not check("with what the driver declared",
                              "infer_unknown" in html, True)
        failures += not check("including its choices",
                              "continue a known series" in html, True)
        post(f"{base}/{TOKEN}/ecowitt", {"infer_unknown": "all",
                                         "model": "HP2561AE Pro"})
        saved = config_file.read(path)
        failures += not check("saved under the driver's name",
                              config_file.get(saved, "drivers.ecowitt.infer_unknown"),
                              "all")
        failures += not check("the core's settings are untouched",
                              config_file.get(saved, "station.name"), "Kirchdorf")

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

        print("\nthe previous version is kept")
        failures += not check("as .bak",
                              path.with_suffix(".toml.bak").exists(), True)

        print("\na choice that offers 'none' can be set back to it")
        # Every dropdown with an empty entry was one way: an empty value
        # parsed to the option's default, so the old choice stayed. Nobody
        # could undo picking one, on any page, for any setting.
        from weewx_evo.options import Invalid, Option

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
        failures += not check("an hourly one stayed hourly",
                              day.lines[0].interval if day else None, "hour")
        failures += not check("skip_if_empty is a span, not a yes or no",
                              day.skip_if_empty if day else None, "year")

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

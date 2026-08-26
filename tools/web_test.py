"""Serve some files and try to get out of the directory.

Two things are being checked. The routing -- feeds at /<name>/, one of them
optionally at / -- and the boundary, which is the part that would matter if it
were wrong. A feed's directory is written from a template, and a template that
can be made to write `../../etc` is one somebody eventually writes by accident.

    python tools/web_test.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.netaccess import Access  # noqa: E402
from weewx_evo.webserver import Site, WebServer  # noqa: E402


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


def main() -> int:
    failures = 0
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-web-"))
    try:
        site_dir = tmp / "public_html"
        (site_dir / "css").mkdir(parents=True)
        (site_dir / "index.html").write_text("<h1>21.4</h1>", encoding="utf-8")
        (site_dir / "css" / "a.css").write_text("body{}", encoding="utf-8")
        other = tmp / "archive"
        other.mkdir()
        (other / "index.html").write_text("<h1>archive</h1>", encoding="utf-8")
        # Something outside any feed, to try to reach.
        (tmp / "secret.toml").write_text('token = "not yours"', encoding="utf-8")

        site = Site({"website": site_dir, "archive": other},
                    title="Kirchdorf")
        server = WebServer(site, "127.0.0.1", 0, access=Access.parse("any"))
        server.start()
        base = f"http://127.0.0.1:{server.port}"
        time.sleep(0.1)

        def get(path: str) -> tuple[int, str]:
            try:
                with urllib.request.urlopen(base + path, timeout=5) as r:
                    return r.status, r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                return exc.code, ""

        try:
            print("with no default, / lists the feeds")
            code, body = get("/")
            failures += not check("it loads", code, 200)
            failures += not check("both are listed",
                                  "website" in body and "archive" in body, True)
            failures += not check("with the station's name", "Kirchdorf" in body,
                                  True)

            print("\nand each feed is under its own name")
            failures += not check("a feed's index", get("/website/")[1],
                                  "<h1>21.4</h1>")
            failures += not check("without the slash too", get("/website")[0], 200)
            failures += not check("a file under it", get("/website/css/a.css")[1],
                                  "body{}")
            failures += not check("the other feed", get("/archive/")[1],
                                  "<h1>archive</h1>")
            failures += not check("something that is not a feed",
                                  get("/nothing/")[0], 404)

            print("\na directory of files is listed, not refused")
            # A feed that writes seventy JSON files and no index.html
            # answered 404 at its own address. That reads as "nothing
            # here" and is the opposite of true.
            (site_dir / "data").mkdir()
            for name in ("index.json", "daytempdew.json"):
                (site_dir / "data" / name).write_text(
                    "{}", encoding="utf-8")
            code, body = get("/website/data/")
            failures += not check("it answers", code, 200)
            failures += not check(
                "and names what is in it",
                "daytempdew.json" in body and "index.json" in body, True)
            failures += not check("the files themselves still work",
                                  get("/website/data/index.json")[1], "{}")
            failures += not check("one that is not there is still 404",
                                  get("/website/data/nope.json")[0], 404)
            print("\nnothing gets out of a feed's directory")
            # Every shape of it. All must fail the same way, and the file
            # outside must never appear in a body.
            for path in ("/website/../secret.toml",
                         "/website/../../secret.toml",
                         "/website/css/../../secret.toml",
                         "/website/%2e%2e/secret.toml",
                         "/website/....//secret.toml"):
                code, body = get(path)
                escaped = "not yours" in body
                failures += not check(f"{path}", code == 404 and not escaped, True)

            print("\ncontent types are right")
            with urllib.request.urlopen(base + "/website/css/a.css") as r:
                failures += not check("css", r.headers.get("Content-Type"),
                                      "text/css; charset=utf-8")
            with urllib.request.urlopen(base + "/website/") as r:
                failures += not check("html", r.headers.get("Content-Type"),
                                      "text/html; charset=utf-8")
                # A page is rewritten every archive interval. Told to cache it,
                # a browser shows yesterday's weather.
                failures += not check("a page is never cached",
                                      r.headers.get("Cache-Control"), "no-cache")
            with urllib.request.urlopen(base + "/website/css/a.css") as r:
                failures += not check("but a stylesheet is",
                                      "max-age" in (r.headers.get("Cache-Control") or ""),
                                      True)
                stamp = r.headers.get("Last-Modified")

            print("\nand a browser that already has it is told so")
            request = urllib.request.Request(base + "/website/css/a.css")
            request.add_header("If-Modified-Since", stamp)
            try:
                with urllib.request.urlopen(request, timeout=5) as r:
                    failures += not check("304", r.status, 304)
            except urllib.error.HTTPError as exc:
                failures += not check("304", exc.code, 304)
        finally:
            server.stop()

        print("\none feed can be rooted at /")
        rooted = Site({"website": site_dir, "archive": other},
                      default="website")
        server = WebServer(rooted, "127.0.0.1", 0, access=Access.parse("any"))
        server.start()
        base = f"http://127.0.0.1:{server.port}"
        time.sleep(0.1)
        try:
            failures += not check("/ is that feed", get("/")[1], "<h1>21.4</h1>")
            failures += not check("its files are directly under /",
                                  get("/css/a.css")[1], "body{}")
            failures += not check("the others keep their names",
                                  get("/archive/")[1], "<h1>archive</h1>")
            failures += not check("and so does it",
                                  get("/website/")[1], "<h1>21.4</h1>")
            print("\n  the boundary still holds")
            code, body = get("/../secret.toml")
            failures += not check("nothing above it", code == 404
                                  or "not yours" not in body, True)
        finally:
            server.stop()

        print("\na changed setting takes effect without a restart")
        # The web server reads what it serves once, at startup. Changing
        # it on the settings page wrote the file and nothing told the
        # running server, so the page kept showing the old thing and said
        # nothing about needing a restart.
        live = Site({"website": site_dir, "archive": other},
                    default="website", title="Kirchdorf")
        server = WebServer(live, "127.0.0.1", 0, access=Access.parse("any"))
        server.start()
        base = f"http://127.0.0.1:{server.port}"
        time.sleep(0.1)
        try:
            failures += not check("/ is the default feed", get("/")[1],
                                  "<h1>21.4</h1>")

            # What the serve loop does when the file changes.
            moved = live.update({"website": site_dir, "archive": other},
                                default="")
            failures += not check("the site says it moved", moved, True)
            code, body = get("/")
            failures += not check("/ now lists them", "archive" in body
                                  and "website" in body, True)
            failures += not check("and the feeds still answer",
                                  get("/website/")[1], "<h1>21.4</h1>")

            live.update({"archive": other}, default="archive")
            failures += not check("one can be taken away",
                                  get("/website/")[0], 404)
            failures += not check("and another rooted at /",
                                  get("/")[1], "<h1>archive</h1>")

            failures += not check("nothing changed means nothing moved",
                                  live.update({"archive": other},
                                              default="archive"), False)
        finally:
            server.stop()
        print("\na feed that does not exist is named, not guessed")
        empty = Site({"website": site_dir}, default="nosuchfeed")
        failures += not check("an unknown default is ignored", empty.default, "")

        print("\nand who is answered is decided as everywhere else")
        shut = Site({"website": site_dir})
        server = WebServer(shut, "127.0.0.1", 0,
                           access=Access(networks=(), described="nothing"))
        server.start()
        base = f"http://127.0.0.1:{server.port}"
        time.sleep(0.1)
        try:
            failures += not check("refused", get("/")[0], 404)
        finally:
            server.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Deck's live readings: the push path, end to end.

Deck takes live readings one way. The station POSTs them to the `live.php`
that ships with the skin; that writes them beside itself; the page reads that
file. No broker, no port forwarded, no certificate.

MQTT is still in weewx-evo -- Home Assistant needs it, and so do Belchertown,
jas and weewx-wdc, which are written against it. Deck does not, and this
checks that it really does not: a 46 kB broker client for a path the skin will
never take is the sort of thing that is nobody's fault and never gets removed.

What is checked:

  * The document the upload sends, and that its names match the ones the cards
    carry. A mismatch there is a page that renders perfectly and never
    updates, with nothing in any log.
  * `live.php` itself, under a real PHP where there is one: the token, the
    method, the size limit, and that it writes atomically.
  * The same file without a web host: for a directory the built-in server
    hands out, the station writes `live.json` into it directly. No script, no
    token, no posting to ourselves over the network -- and the page cannot
    tell the two routes apart, which is what makes a local station live with
    no change to the skin.
  * The rendered page: the poller and the badges, and no MQTT.

    python tools/deck_live_test.py

Needs Cheetah, so in practice:

    wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \\
      cd /mnt/d/Git/weewx-evo && python tools/deck_live_test.py'

The PHP half runs under a local `php` where there is one, and under
`php:8-cli-alpine` in Docker otherwise. Skipped with a word where there is neither.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def ok(what: str, condition: bool) -> None:
    check(what, bool(condition), True)


def archive(path: Path) -> None:
    """Two days of readings, enough for the tiles on the front page."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE archive (dateTime INTEGER PRIMARY KEY, usUnits INTEGER, "
        "`interval` INTEGER, outTemp REAL, outHumidity REAL, barometer REAL, "
        "windSpeed REAL, windDir REAL, windGust REAL, rain REAL, "
        "rainRate REAL, dewpoint REAL, radiation REAL)")
    midnight = int(time.mktime((*time.localtime()[:3], 0, 0, 0, 0, 0, -1)))
    when = midnight - 86400
    while when < time.time():
        conn.execute(
            "INSERT INTO archive VALUES (?, 17, 5, ?, 61.0, 1013.2, 3.2, "
            "245.0, 7.1, 0.0, 0.0, 15.6, 300.0)",
            (when, 18.0 + (when % 28800) / 4800.0))
        when += 300
    conn.commit()
    conn.close()


def render(tmp: Path, live_push: bool = True) -> str:
    """Render Deck's front page, as text."""
    return rendered(tmp, live_push).read_text(encoding="utf-8", errors="replace")


def rendered(tmp: Path, live_push: bool = True, name: str = "") -> Path:
    """Render Deck's front page. Returns where it was written.

    `name` gives a run its own directory. Two renders into one is a second
    `CREATE TABLE archive`, which is an error nobody reads as "this test
    asked for the page twice".
    """
    from weewx_evo import units
    from weewx_evo.feeds.cheetah import CheetahFeed
    from weewx_evo.series import Reader
    from weewx_evo.skins import bundled
    from weewx_evo.tags import Tags

    where = tmp / (name or ("push" if live_push else "quiet"))
    if where.exists():
        return where / "out" / "index.html"
    where.mkdir(parents=True, exist_ok=True)
    db = where / "weewx.sdb"
    archive(db)

    source = bundled().get("deck")
    if source is None:
        raise SystemExit("the deck skin is not where bundled() says it is")
    skin = where / "deck"
    shutil.copytree(source, skin)

    if not live_push:
        conf = (skin / "skin.conf").read_text(encoding="utf-8")
        conf = conf.replace("live_push = 1", "live_push = 0")
        (skin / "skin.conf").write_text(conf, encoding="utf-8")

    conn = sqlite3.connect(db)
    reader = Reader(conn)
    # Everything Deck asks about the station. A short one renders a page full
    # of `?'station.altitude'?`, which is not what is being tested here.
    tags = Tags(reader, target=units.Target(reader.system),
                unit_system=reader.system,
                station={"location": "Kirchdorf", "latitude": 48.3858,
                         "longitude": 11.7050, "altitude": 440.0,
                         "station_url": "https://example.org",
                         "hardware": "ecowitt", "version": "0.0.1"})
    feed = CheetahFeed(reader=reader, skin=skin, tags=tags)
    produced = feed.produce(where / "out")
    conn.close()

    page = where / "out" / "index.html"
    if not page.is_file():
        made = sorted(str(f) for f in produced.files)
        raise SystemExit(f"deck did not write index.html. It wrote: {made}")
    return page


# ---------------------------------------------------------------------------
# The skin no longer speaks MQTT.
# ---------------------------------------------------------------------------

def test_no_mqtt_left() -> None:
    """A broker client for a path this skin will not take is dead weight."""
    from weewx_evo.skins import bundled

    skin = Path(bundled()["deck"])
    ok("the 46 kB bundle is gone",
       not (skin / "assets" / "live-updates.js").exists())

    for name in ("skin.conf", "index.html.tmpl", "includes/ui-shell.inc"):
        text = (skin / name).read_text(encoding="utf-8")
        ok(f"no mqtt in {name}", "mqtt" not in text.lower())

    ok("the poller ships with the skin",
       (skin / "assets" / "live-poll.js").is_file())
    # live.php is not the skin's: it goes up with every export that carries
    # it, so every skin gets the same one and none has to bring its own.
    ok("and live.php is not, because it is the core's",
       not (skin / "live.php").exists())


# ---------------------------------------------------------------------------
# What the station sends.
# ---------------------------------------------------------------------------

RECORD = {
    "dateTime": 1756308600, "usUnits": 17, "interval": 5,
    "outTemp": 23.4, "outHumidity": 61.0, "barometer": 1013.2,
    "windSpeed": 3.2, "windDir": 245.0,
}


def test_the_document() -> None:
    from weewx_evo.uploads.webpush import WebPushUpload

    upload = WebPushUpload(url="https://example.org/w/live.php", token="t")
    document = upload.document(RECORD)

    # The same names the cards carry, which is the whole contract between the
    # two halves. A mismatch is a page that renders and never updates.
    check("temperature", document["outTemp_C"], 23.4)
    check("humidity has no unit suffix", document["outHumidity"], 61.0)
    check("nor does a bearing", document["windDir"], 245.0)
    check("the timestamp survives", document["dateTime"], 1756308600)
    ok("usUnits is not sent", "usUnits" not in document)
    ok("nor the interval", "interval" not in document)

    # Converted on the way out, like everything else here.
    imperial = WebPushUpload(url="https://example.org/w/live.php", token="t",
                             unit_system="US")
    check("in US units", round(imperial.document(RECORD)["outTemp_F"], 1), 74.1)


def test_it_needs_a_token() -> None:
    from weewx_evo.uploads.webpush import WebPushUpload

    try:
        WebPushUpload(url="https://example.org/live.php")
    except ValueError as exc:
        # Without one, anybody who finds the address writes the weather.
        ok("it says why", "token" in str(exc))
    else:
        FAILURES.append("the upload accepted no token")

    try:
        WebPushUpload(url="ftp://example.org/live.php", token="t")
    except ValueError as exc:
        ok("and that it wants http", "http" in str(exc))
    else:
        FAILURES.append("the upload accepted an ftp address")


# ---------------------------------------------------------------------------
# The same file, without a web host.
# ---------------------------------------------------------------------------

def test_the_local_way(tmp: Path) -> None:
    """A directory this machine serves needs no PHP and no posting.

    The point of it: `live.php` exists to get a reading onto a host we can
    only reach by uploading files. When the destination is a directory the
    built-in server already hands out, that is a round trip over the network
    to ourselves for a file we could just write. The page cannot tell -- it
    reads `live.json` either way -- so the skin needs no change at all.
    """
    from weewx_evo.exports.livepush import DATA_FILE, STALE_AFTER
    from weewx_evo.uploads.webpush import WebPushUpload

    where = tmp / "site"
    upload = WebPushUpload(directories=[str(where)])

    # No token: there is nobody to prove anything to. Requiring one here
    # would be theatre, and theatre in a settings page is a field somebody
    # has to fill in before the thing works.
    check("nothing is posted", upload.url, "")
    check("and no host", upload.host, "")

    result = upload.post([dict(RECORD)])
    check("one reading went out", result.sent, 1)
    check("and nothing failed", result.failures, [])

    written = where / DATA_FILE
    ok("the file is there", written.is_file())
    document = json.loads(written.read_text(encoding="utf-8"))

    # The same document, to the field: a page reading one route reads the
    # other. That is the whole reason for writing it here rather than
    # inventing a second shape.
    check("the same names", document["outTemp_C"], 23.4)
    check("the same timestamp", document["dateTime"], 1756308600)
    ok("stamped as received", isinstance(document.get("_received"), int))
    check("and told when it goes stale", document["_stale_after"], STALE_AFTER)

    # Nothing half-written is ever visible: a browser that reads the file
    # mid-write gets a parse error, and a page that blanks now and then is
    # the sort of fault nobody can reproduce.
    upload.post([dict(RECORD, dateTime=RECORD["dateTime"] + 10)])
    ok("no leftovers beside it",
       sorted(q.name for q in where.iterdir()) == [DATA_FILE])
    again = json.loads(written.read_text(encoding="utf-8"))
    check("and it was replaced", again["dateTime"], RECORD["dateTime"] + 10)

    # One or the other is enough, but neither is not.
    try:
        WebPushUpload()
    except ValueError as exc:
        ok("it says what is missing",
           "directory" in str(exc) and "live.php" in str(exc))
    else:
        FAILURES.append("the upload accepted neither a directory nor a url")

    # Several, because a station can serve several sites and one of them
    # being live while the rest go stale is nobody's reading of the setting.
    two = tmp / "two"
    both = WebPushUpload(directories=[str(two / "a"), str(two / "b")])
    both.post([dict(RECORD)])
    ok("each served directory gets the file",
       (two / "a" / DATA_FILE).is_file() and (two / "b" / DATA_FILE).is_file())

    # And one failing does not take the other with it: a skin on a full disk
    # must not stop the live readings on the site beside it.
    mixed = WebPushUpload(directories=["/nope/nowhere/at/all", str(two / "c")])
    result = mixed.post([dict(RECORD)])
    check("the good one still went", result.sent, 1)
    ok("and the bad one is reported", len(result.failures) == 1)
    ok("the file is there", (two / "c" / DATA_FILE).is_file())


def test_a_local_export_carries_no_php(tmp: Path) -> None:
    """The switch is the same one; what it does is not.

    A local export with live readings on must not copy `live.php` anywhere.
    The built-in server hands out files; it does not run PHP, so the script
    would sit in the published directory doing nothing but showing its own
    source to anybody who asked for it.
    """
    from weewx_evo.exports.livepush import SCRIPT, TOKEN_FILE
    from weewx_evo.exports.local import LocalExport

    feed = tmp / "feed"
    feed.mkdir()
    (feed / "index.html").write_text("<html></html>", encoding="utf-8")

    export = LocalExport(directory=str(tmp / "published"),
                         live_push=True, upload_token="secret")
    check("nothing was put in", export.prepare(feed), [])
    ok("no script", not (feed / SCRIPT).exists())
    ok("no token file", not (feed / TOKEN_FILE).exists())

    # And it is on by default, because it costs one small file and the
    # alternative is a local page showing readings five minutes old.
    check("on by default", LocalExport(directory=str(tmp / "p2")).live_push,
          True)


def test_the_directory_fills_in_by_itself() -> None:
    """From the local export, the way the address comes from a remote one.

    Typing the same path twice is how the two drift apart, and the way they
    drift is a file written where nothing serves it.
    """
    from weewx_evo.uploads.webpush import WebPushUpload

    exports = {
        "site": {"kind": "local", "directory": "data/site",
                 "live_push": True},
        "wdc": {"kind": "local", "directory": "data/wdc", "live_push": True},
        "host": {"kind": "ftp", "live_push": True,
                 "live_push_url": "https://example.org/wetter"},
    }

    class FakeSettings:
        def __init__(self) -> None:
            self.config = {"exports": exports}

        def get(self, name: str) -> object:
            return "upload-token" if name == "token" else None

    url, token, directories = WebPushUpload.from_exports(FakeSettings())
    check("the web host", url, "https://example.org/wetter/live.php")
    check("every local directory", directories, ["data/site", "data/wdc"])
    ok("and a token for the first", len(token) == 32)

    # Switched off means switched off, for both.
    exports["site"]["live_push"] = False
    exports["wdc"]["live_push"] = False
    exports["host"]["live_push"] = False
    url, _token, directories = WebPushUpload.from_exports(FakeSettings())
    check("nothing when it is off", (url, directories), ("", []))


def test_a_local_site_is_live_with_nothing_configured() -> None:
    """A local export saying "live readings" is the whole configuration.

    There is no address to choose, no token to derive and nothing leaves the
    machine. An upload with no settings in it would be a step that answers no
    question, so the schedule grows one by itself.

    And only for directories: an upload that posts somewhere goes out over
    somebody else's network, and a checkbox defaulting to on is not a reason
    to start doing that.
    """
    from weewx_evo.cli import live_readings_locally

    class FakeSettings:
        def __init__(self, exports: dict, feeds: dict | None = None) -> None:
            self.config = {"exports": exports, "feeds": feeds or {}}

        def get(self, name: str) -> object:
            return {"token": "upload-token", "language": "en"}.get(name)

    local = FakeSettings({"site": {"kind": "local", "directory": "data/site",
                                   "live_push": True}})
    made = live_readings_locally(local, {})
    check("one upload appears", sorted(made), ["live"])
    check("of the right kind", made["live"]["kind"], "webpush")
    check("pointed at the served directory",
          made["live"]["directories"], ["data/site"])
    ok("and marked as not typed by anyone", made["live"]["_inferred"])

    # Switched off is switched off.
    off = FakeSettings({"site": {"kind": "local", "directory": "data/site",
                                 "live_push": False}})
    check("nothing when the export says no", live_readings_locally(off, {}), {})

    # A web host is not started on its own.
    away = FakeSettings({"host": {"kind": "ftp", "live_push": True,
                                  "live_push_url": "https://example.org/w"}})
    check("and nothing is posted anywhere unasked",
          live_readings_locally(away, {}), {})

    # One that was configured on purpose is left alone, whatever it says.
    check("an upload that exists is not doubled",
          live_readings_locally(local, {"mine": {"kind": "webpush"}}), {})

    # The units the pages are written in, not the ones the station reports.
    # A station on Fahrenheit publishing a page in Celsius is the ordinary
    # case, and the page has no way to tell that 82.8 is not what it was
    # about to print.
    two = FakeSettings(
        {"metric": {"kind": "local", "directory": "data/metric",
                    "source": "deck"},
         "imperial": {"kind": "local", "directory": "data/imperial",
                      "source": "seasons"}},
        {"deck": {"units": "METRICWX"}, "seasons": {"units": "US"}})
    made = live_readings_locally(two, {})
    check("two unit systems are two uploads", sorted(made),
          ["live-metricwx", "live-us"])
    check("each with its own directory",
          made["live-us"]["directories"], ["data/imperial"])
    check("and its own units",
          made["live-metricwx"]["unit_system"], "METRICWX")

    # And the language decides where the feed did not say.
    class German(FakeSettings):
        def get(self, name: str) -> object:
            return {"token": "t", "language": "de"}.get(name)

    spoken = German({"site": {"kind": "local", "directory": "data/site",
                              "source": "deck"}}, {"deck": {}})
    check("the language settles it when the feed does not",
          live_readings_locally(spoken, {})["live"]["unit_system"], "METRICWX")


# ---------------------------------------------------------------------------
# live.php itself.
# ---------------------------------------------------------------------------

#: A PHP to run `live.php` under. Local first; a container otherwise, because
#: this file runs on somebody else's web host and "it looked fine to me" is
#: not a test. The image is small and cached after the first pull.
PHP_IMAGE = "php:8-cli-alpine"


#: Worked out once. Pulling an image is slow and asking twice whether it is
#: there is how a test prints the same line twice and looks broken.
_RUNNER: list[str] | str | None = "unknown"


def php_runner() -> list[str] | None:
    """How to run PHP here, or None if there is no way to.

    Returns the command prefix. The container form mounts the script's
    directory, so the two behave the same: `live.php` writes beside itself
    either way.
    """
    global _RUNNER
    if _RUNNER != "unknown":
        return _RUNNER

    _RUNNER = _find_php()
    return _RUNNER


def _find_php() -> list[str] | None:
    if shutil.which("php"):
        return ["php"]
    if shutil.which("docker"):
        found = subprocess.run(["docker", "image", "inspect", PHP_IMAGE],
                               capture_output=True, timeout=60, check=False)
        if found.returncode != 0:
            print(f"pulling {PHP_IMAGE} to run live.php ...")
            pulled = subprocess.run(["docker", "pull", "-q", PHP_IMAGE],
                                    capture_output=True, timeout=600,
                                    check=False)
            if pulled.returncode != 0:
                return None
        return ["docker"]
    return None


def php_available() -> bool:
    return php_runner() is not None


def run_php(script: Path, method: str, body: bytes = b"",
            token: str = "") -> str:
    """Run live.php, faking a request.

    Enough of a request for what this script does, and it means the checks
    need no web server. The body arrives on stdin, which is what
    `php://input` reads under the CLI.
    """
    runner = php_runner()
    if runner is None:
        return ""
    code = (f"$_SERVER['REQUEST_METHOD']={method!r};"
            f"$_SERVER['HTTP_X_WEEWX_TOKEN']={token!r};"
            f"require '/w/{script.name}';")

    if runner == ["php"]:
        command = ["php", "-r", code.replace("/w/", str(script.parent) + "/")]
        cwd = str(script.parent)
    else:
        # `-i` so php://input has a stdin to read. The directory is mounted
        # read-write because writing beside itself is the thing being
        # tested.
        command = ["docker", "run", "--rm", "-i",
                   "-v", f"{script.parent.resolve()}:/w", "-w", "/w",
                   PHP_IMAGE, "php", "-r", code]
        cwd = None

    done = subprocess.run(command, input=body, capture_output=True,
                          cwd=cwd, timeout=120, check=False)
    return done.stdout.decode("utf-8", "replace")


def test_php_syntax() -> None:
    """`php -l`, so a typo is caught here and not on somebody's web host."""
    from weewx_evo.exports import livepush

    runner = php_runner()
    if runner is None:
        return
    script = Path(livepush.__file__).parent / livepush.SCRIPT
    if runner == ["php"]:
        command = ["php", "-l", str(script)]
    else:
        command = ["docker", "run", "--rm",
                   "-v", f"{script.parent.resolve()}:/w", "-w", "/w",
                   PHP_IMAGE, "php", "-l", livepush.SCRIPT]
    done = subprocess.run(command, capture_output=True, timeout=120,
                          check=False)
    ok("live.php parses", done.returncode == 0)
    if done.returncode != 0:
        FAILURES.append(done.stdout.decode("utf-8", "replace")[:400])


def test_live_php(tmp: Path) -> None:
    from weewx_evo.exports import livepush

    if not php_available():
        print("no php and no docker; skipping the live.php checks.")
        return

    where = tmp / "php"
    where.mkdir(parents=True, exist_ok=True)
    script = where / livepush.SCRIPT
    script.write_text(livepush.script(), encoding="utf-8")

    body = json.dumps({"dateTime": 1756308600, "outTemp_C": 21.4}).encode()

    # No token file: it says so rather than accepting anything.
    ok("with no token configured it refuses",
       "No token" in run_php(script, "POST", body, token="secret"))

    (where / "live.token").write_text("secret\n", encoding="utf-8")

    # A wrong token is a 404, on purpose: saying "wrong token" would confirm
    # there is a right one.
    ok("a wrong token is not found",
       "Not found" in run_php(script, "POST", body, token="wrong"))
    ok("and nothing was written", not (where / "live.json").exists())

    ok("a GET before anything was pushed says so",
       "nothing has been" in run_php(script, "GET", token="secret"))

    ok("the right token is accepted",
       run_php(script, "POST", body, token="secret").startswith("ok "))
    ok("and it wrote the file", (where / "live.json").is_file())

    stored = json.loads((where / "live.json").read_text(encoding="utf-8"))
    check("the reading is in it", stored["outTemp_C"], 21.4)
    check("and its own timestamp", stored["dateTime"], 1756308600)
    # Stamped on arrival as well: the station's clock says when the reading is
    # from, this says when it got here, and a page needs both to decide
    # whether to call itself live.
    ok("stamped on arrival", stored.get("_received", 0) > 1700000000)
    ok("with how long it stays fresh", stored.get("_stale_after", 0) > 0)

    # Written beside and renamed: half a JSON document is a parse error in
    # every browser, which shows up as a page that blanks once in a while.
    ok("nothing partial is left", not list(where.glob("*.part")))

    got = run_php(script, "GET", token="secret")
    check("a GET returns what was stored", json.loads(got)["outTemp_C"], 21.4)

    ok("nonsense is refused",
       "not JSON" in run_php(script, "POST", b"nonsense", token="secret"))
    ok("an oversized body is refused",
       "Too big" in run_php(script, "POST",
                            b'{"x":"' + b"y" * 70000 + b'"}', token="secret"))
    ok("anything else is refused",
       "POST to write" in run_php(script, "DELETE", token="secret"))


# ---------------------------------------------------------------------------
# The rendered page.
# ---------------------------------------------------------------------------

def test_the_page(tmp: Path) -> None:
    page = render(tmp, live_push=True)
    ok("it rendered", "<html" in page.lower())

    ok("the poller is loaded", "live-poll.js" in page)
    ok("and the badges", "live-status.js" in page)
    ok("with where to read from", "deckLivePoll" in page)
    ok("and live.json named", "live.json" in page)

    # Nothing of the broker path.
    ok("no mqtt client", "live-updates.js" not in page)
    ok("nor its globals", "mqtt_host" not in page)

    ok("the indicator is in the header", 'id="live-indicator"' in page)
    ok("it starts neither green nor red", "live-indicator--waiting" in page)

    # The cards the badges attach to. Without `data-observation` the poller
    # has nothing to find and the whole thing renders as nothing at all.
    ok("there are stat tiles", "card stat-tile" in page)
    ok("with an observation name", "data-observation=" in page)
    ok("and the value element", "stat-title-obs-value" in page)


def test_the_page_without_it(tmp: Path) -> None:
    """Switched off, nothing about live appears at all.

    A station that does not push, showing a permanent red badge on every
    card, has been handed a fault it does not have.
    """
    page = render(tmp, live_push=False)
    ok("it rendered", "<html" in page.lower())
    ok("no poller", "live-poll.js" not in page)
    ok("no badges", "live-status.js" not in page)
    ok("no indicator", 'id="live-indicator"' not in page)


def test_the_styles_are_there() -> None:
    from weewx_evo.skins import bundled

    css = (Path(bundled()["deck"]) / "assets" / "deck.css").read_text(
        encoding="utf-8")
    for name in (".live-badge", ".live-badge--live", ".live-badge--stale",
                 ".live-badge--off", ".live-badge--waiting",
                 ".live-indicator", ".live-indicator--live",
                 ".live-indicator--stale", ".live-indicator--off",
                 ".live-indicator--waiting", ".live-indicator__dot"):
        ok(f"{name} is styled", name in css)
    # The skin's own tokens, so both themes carry rather than a green that
    # vanishes on a dark background.
    ok("green is the skin's own", "var(--good)" in css)
    ok("and so is red", "var(--bad)" in css)
    ok("the pulse is off for reduced motion",
       "prefers-reduced-motion" in css and "live-pulse" in css)


def test_the_german_words_exist() -> None:
    from weewx_evo.skins import bundled

    conf = (Path(bundled()["deck"]) / "lang" / "de.conf").read_text(
        encoding="utf-8")
    for phrase in ("just now", "min ago", "No connection to the live feed.",
                   "Waiting for the first reading."):
        ok(f"{phrase!r} is translated", f'"{phrase}"' in conf)
    ok("and the reason LIVE is not is written down",
       "stays English on purpose" in conf)


# ---------------------------------------------------------------------------
# The page, running.
# ---------------------------------------------------------------------------

class Hung(Exception):
    """The page did not settle, or would not run at all."""


#: How the page is actually run. Everything else here reads what Deck wrote;
#: this executes it, because the fault that put it here cannot be read.
NODE_SCRIPT = Path(__file__).resolve().parent / "deck_page_test.js"


def can_run_javascript() -> str:
    """A node with jsdom, or a word saying why not."""
    if shutil.which("node") is None:
        return "there is no node on PATH"
    found = subprocess.run(["node", "-e", "require('jsdom')"],
                           capture_output=True, text=True, check=False)
    if found.returncode != 0:
        return "node is there but jsdom is not (npm install -g jsdom)"
    return ""


def run_page(page: Path, live: dict | None = None) -> dict:
    """Load the page in jsdom, let it live for a few seconds, report."""
    command = ["node", str(NODE_SCRIPT), str(page), str(page.parent / "assets")]
    if live is not None:
        document = page.parent / "sent.json"
        document.write_text(json.dumps(live), encoding="utf-8")
        command.append(str(document))

    try:
        finished = subprocess.run(command, capture_output=True, text=True,
                                  timeout=60, check=False)
    except subprocess.TimeoutExpired:
        # Not an error in the harness: it is the finding. A page whose
        # scripts never yield never lets the timer that reports fire either,
        # so the run stops exactly the way the browser tab does.
        raise Hung("the page never finished loading. Something in its "
                   "JavaScript does not yield -- a browser calls this "
                   "'page unresponsive'.") from None
    if finished.returncode != 0 or not finished.stdout.strip():
        raise Hung(f"the page could not be run: "
                   f"{finished.stderr.strip()[:400]}")
    return json.loads(finished.stdout)


def test_the_page_does_not_lock_up(tmp: Path) -> None:
    """The one fault reading the HTML cannot find.

    The badges were painted into the element a MutationObserver was watching.
    Every paint was a mutation, every mutation a paint, and the tab stopped
    responding about a second after it loaded. The page was correct, every
    test passed, and the only symptom was a browser saying the page is not
    responding.

    Two things are checked, because either alone can be got round. A badge
    must not be inside the watched element, and the observer must not be
    running away.
    """
    page = rendered(tmp, live_push=True, name="running")
    result = run_page(page)

    ok("the page ran", not result["problems"])
    if result["problems"]:
        for problem in result["problems"]:
            FAILURES.append(f"    {problem}")

    ok("there are cards to badge", result["cards"] > 0)
    check("every card got a badge", result["badges"], result["cards"])
    ok("no badge sits in the watched element",
       not result["badgeInWatchedElement"])

    # A page that settles calls the observer a handful of times. One that is
    # running away calls it as fast as the machine allows -- tens of thousands
    # in four seconds, and that is being generous about the machine.
    ok(f"the observer settles ({result['observerCallbacks']} callbacks in "
       f"{result['seconds']:.1f}s)",
       result["observerCallbacks"] < 200)


def test_the_page_shows_what_was_pushed(tmp: Path) -> None:
    """And the other half: a live document reaches the cards.

    Reading the file is not the point. Putting the number on the page is, and
    between the two sit the names -- `outTemp_C` in the document against
    `outTemp` on the card. A mismatch there renders perfectly and never
    updates, with nothing in any log.
    """
    page = rendered(tmp, live_push=True, name="running")
    document = {"dateTime": int(time.time()), "outTemp_C": 27.5,
                "outHumidity": 44.0, "barometer_mbar": 1008.3,
                "_received": int(time.time()), "_stale_after": 300}
    result = run_page(page, live=document)

    ok("the page asked for the file", result["fetches"] > 0)
    shown = {row["obs"]: row["shown"] for row in result["values"]}
    check("the pushed temperature is on the card",
          shown.get("outTemp"), "27.5")
    # Whole numbers: the card carries `data-rounding="0"` for humidity, and
    # the page rounds the way the skin says rather than the way the document
    # happens to be written.
    check("and the humidity, at the skin's own rounding",
          shown.get("outHumidity"), "44")

    # Green, not red: the document is seconds old.
    ok("the badges say live", "live-badge--live" in result["badgeStates"])
    ok("and none says otherwise", "live-badge--off" not in result["badgeStates"])
    ok("it still does not run away", result["observerCallbacks"] < 200)


def main() -> int:
    global CHECKS

    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-deck-live-"))
    try:
        # Everything that does not need a renderer. Most of this file is
        # about `live.php` and the document sent to it, and neither has
        # anything to do with Cheetah -- so a machine without it still checks
        # the part that runs on somebody else's web host.
        test_no_mqtt_left()
        test_the_document()
        test_it_needs_a_token()
        test_the_local_way(tmp)
        test_a_local_export_carries_no_php(tmp)
        test_the_directory_fills_in_by_itself()
        test_a_local_site_is_live_with_nothing_configured()
        test_php_syntax()
        test_live_php(tmp)
        test_the_styles_are_there()
        test_the_german_words_exist()

        try:
            import Cheetah.Template  # noqa: F401
        except ImportError:
            print("Cheetah is not installed; the rendering checks are "
                  "skipped.")
        else:
            test_the_page(tmp)
            test_the_page_without_it(tmp)

            why = can_run_javascript()
            if why:
                print(f"the page is not run: {why}. "
                      f"docker/run.sh has both.")
            else:
                for one in (test_the_page_does_not_lock_up,
                            test_the_page_shows_what_was_pushed):
                    try:
                        one(tmp)
                    except Hung as exc:
                        CHECKS += 1
                        FAILURES.append(one.__name__ + chr(10) + "    " + str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    for failure in FAILURES:
        print("FAIL", failure)
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

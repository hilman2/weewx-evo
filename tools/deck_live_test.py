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
    """Render Deck's front page."""
    from weewx_evo import units
    from weewx_evo.feeds.cheetah import CheetahFeed
    from weewx_evo.series import Reader
    from weewx_evo.skins import bundled
    from weewx_evo.tags import Tags

    where = tmp / ("push" if live_push else "quiet")
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
    return page.read_text(encoding="utf-8", errors="replace")


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


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-deck-live-"))
    try:
        # Everything that does not need a renderer. Most of this file is
        # about `live.php` and the document sent to it, and neither has
        # anything to do with Cheetah -- so a machine without it still checks
        # the part that runs on somebody else's web host.
        test_no_mqtt_left()
        test_the_document()
        test_it_needs_a_token()
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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    for failure in FAILURES:
        print("FAIL", failure)
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

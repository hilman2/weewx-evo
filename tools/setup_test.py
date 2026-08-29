#!/usr/bin/env python3
"""The setup wizard, walked the way a person walks it.

An empty directory, the settings page, and nothing but forms. No
configuration written by hand, no path poked at from the side: if a step
cannot be done by posting the form that is on the page, it cannot be done.

Both ways through, because they are different problems:

    a new station      a place, a forecast, somewhere to publish
    one moving over    a weewx.conf, a skin's charts, an existing archive

The second is the one that has to be right. Somebody with fifteen years of
readings is deciding whether to trust this, and the answer has to be that
nothing of theirs was touched: the archive is copied, the FTP account
arrives switched off, and their weewx.conf is opened for reading.

    python tools/setup_test.py

No network beyond loopback, no WeeWX needed. The weewx.conf and skin.conf
this posts are written here rather than found, so the test says the same
thing on a machine that has never had WeeWX.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import config as config_file  # noqa: E402
from weewx_evo.admin import Admin, AdminServer  # noqa: E402
from weewx_evo.cli import all_schemas  # noqa: E402
from weewx_evo.ratelimit import Limits  # noqa: E402

TOKEN = "setup-token-for-the-walkthrough"

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a, **_k):
        return None


def get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def post(url: str, form: dict) -> tuple[int, str, str]:
    """Returns (status, body, what the redirect said)."""
    data = urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(url, data=data)
    try:
        with urllib.request.build_opener(NoRedirect).open(request,
                                                          timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace"), _said(r)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), _said(exc)


def _said(response) -> str:
    """What a redirect carried in `?said=`.

    The wizard has no session -- this page holds nothing between requests --
    so a step that worked says so in the URL it redirects to.
    """
    where = response.headers.get("Location") or ""
    if "said=" not in where:
        return ""
    return urllib.parse.unquote(where.split("said=", 1)[1])


def upload(url: str, fields: dict, files: dict) -> tuple[int, str, str]:
    """A form with a file in it, the way a browser sends one."""
    boundary = "----weewxevosetup"
    out = []
    for key, value in fields.items():
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                   f'name="{key}"\r\n\r\n{value}\r\n'.encode())
    for key, (name, data) in files.items():
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                   f'name="{key}"; filename="{name}"\r\n'
                   "Content-Type: application/octet-stream\r\n\r\n".encode()
                   + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        url, data=b"".join(out),
        headers={"Content-Type":
                 f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request,
                                                          timeout=180) as r:
            return r.status, r.read().decode("utf-8", "replace"), _said(r)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), _said(exc)


def problem(html: str) -> str:
    found = re.search(r'<p class="err">([^<]*)', html)
    return found.group(1).strip() if found else ""


#: A weewx.conf, written here rather than found. Enough of one to be read:
#: a station, a database, a report and an FTP account.
WEEWX_CONF = """
WEEWX_ROOT = /var/lib/weewx

[Station]
    location = "Kirchdorf an der Amper"
    latitude = 48.3858
    longitude = 11.7050
    altitude = 440, meter
    station_type = Simulator

[StdArchive]
    archive_interval = 300
    record_generation = hardware
    loop_hilo = True

[DataBindings]
    [[wx_binding]]
        database = archive_sqlite

[Databases]
    [[archive_sqlite]]
        database_name = weewx.sdb
        database_type = SQLite

[DatabaseTypes]
    [[SQLite]]
        SQLITE_ROOT = /var/lib/weewx/archive
        driver = weedb.sqlite

[StdReport]
    SKIN_ROOT = skins
    HTML_ROOT = public_html

    [[SeasonsReport]]
        skin = Seasons
        enable = true

    [[FTP]]
        skin = Ftp
        enable = true
        user = weatheruser
        password = hunter2
        server = ftp.example.org
        path = /weather

    [[RSYNC]]
        skin = Rsync
        enable = false
        server = replace_me
"""

#: A skin.conf with three charts in it, which is all the importer needs.
SKIN_CONF = b"""[ImageGenerator]
    image_width = 500

    [[day_images]]
        time_length = 27h
        [[[daytempdew]]]
            [[[[outTemp]]]]
            [[[[dewpoint]]]]
        [[[daywind]]]
            [[[[windSpeed]]]]

    [[year_images]]
        time_length = 365d
        [[[yearrain]]]
            plot_type = bar
            [[[[rain]]]]
                aggregate_type = sum
                aggregate_interval = 1w
"""


def an_archive(where: Path, records: int = 60) -> bytes:
    """A real WeeWX archive, as bytes, for the upload step."""
    conn = sqlite3.connect(where)
    conn.execute(
        "CREATE TABLE archive (dateTime INTEGER NOT NULL UNIQUE PRIMARY KEY, "
        "usUnits INTEGER NOT NULL, `interval` INTEGER NOT NULL, "
        "outTemp REAL, outHumidity REAL, barometer REAL)")
    start = int(time.mktime((2026, 5, 14, 0, 0, 0, 0, 0, -1)))
    conn.executemany(
        "INSERT INTO archive VALUES (?, 1, 5, ?, ?, ?)",
        [(start + n * 300, 55.0 + n * 0.1, 60.0, 29.9) for n in range(records)])
    conn.commit()
    conn.close()
    return where.read_bytes()


def a_fresh_station(base: str, path: Path) -> None:
    """The new-station way: a place, a forecast, and what follows."""
    print("\na new station, from an empty directory")

    code, html = get(f"{base}/setup")
    check("the wizard opens", code, 200)
    check("and offers both ways in",
          "Moving over from WeeWX" in html and "A new station" in html, True)
    # The promise this whole page rests on has to be on it, not in a
    # docstring somebody will not read.
    check("it says nothing of WeeWX's is written to",
          "Nothing of WeeWX's is written to" in html, True)
    check("and that only one of them should run",
          "Run one of them, not both" in html, True)

    print("\n  the place")
    code, html, said = post(f"{base}/setup/place", {
        "name": "Kirchdorf an der Amper", "latitude": "48.3858",
        "longitude": "11.7050", "altitude": "440", "forecast": "1"})
    check("it saves", code, 303)
    check("and says so", bool(said), True)

    written = config_file.read(path)
    check("the name is in the file",
          config_file.get(written, "station.name"), "Kirchdorf an der Amper")
    check("and the coordinates",
          config_file.get(written, "station.latitude"), 48.3858)
    check("a forecast was set up too",
          config_file.get(written, "forecast.ahead.kind"), "open-meteo")

    print("\n  what it refuses")
    code, html, _ = post(f"{base}/setup/place", {"name": "", "latitude": "1"})
    check("a station with no name", "needs a name" in problem(html), True)
    code, html, _ = post(f"{base}/setup/place",
                         {"name": "x", "latitude": "north"})
    check("and coordinates that are not numbers",
          "number in degrees" in problem(html), True)

    print("\n  publishing")
    code, _html, said = post(f"{base}/setup/publish", {
        "host": "ftp.example.org", "user": "weather", "password": "hunter2",
        "directory": "/www", "live_push_url": "https://example.org/"})
    check("the account saves", code, 303)
    written = config_file.read(path)
    check("as an export", config_file.get(written, "exports.site.kind"), "ftp")
    check("with its host",
          config_file.get(written, "exports.site.host"), "ftp.example.org")
    # The pages and the charts they draw from go in one export. Two would
    # publish a page before its charts, which is the half-published site the
    # `feed` trigger exists to prevent.
    check("carrying the charts with the pages",
          config_file.get(written, "exports.site.also"),
          ["json -> data/json"])
    check("and the live address",
          config_file.get(written, "exports.site.live_push_url"),
          "https://example.org/")


def moving_over(base: str, path: Path, work: Path) -> None:
    """The other way: a weewx.conf, a skin's charts, and an archive."""
    print("\nmoving over from WeeWX")

    print("\n  its weewx.conf")
    code, html, said = upload(f"{base}/setup/adopt", {},
                              {"upload": ("weewx.conf",
                                          WEEWX_CONF.encode())})
    check("it is read", code, 303)
    check("and it says what it took", "setting(s) taken" in said, True)

    written = config_file.read(path)
    check("the station's name",
          config_file.get(written, "station.name"), "Kirchdorf an der Amper")
    check("its altitude, in metres",
          config_file.get(written, "station.altitude"), 440.0)
    check("its archive interval",
          config_file.get(written, "interval"), "5m")

    # The FTP account, and switched off. Two programs publishing into one
    # directory give a site made of halves, so the moment to start is when
    # somebody has looked at it -- not the moment they ran an import.
    check("its FTP account came over",
          config_file.get(written, "exports.ftp.host"), "ftp.example.org")
    check("with the user", config_file.get(written, "exports.ftp.user"),
          "weatheruser")
    check("switched off", config_file.get(written, "exports.ftp.enabled"),
          False)
    check("and rsync, which said replace_me, was left out",
          config_file.get(written, "exports.rsync"), None)

    print("\n  its charts")
    before = len(_charts(path))
    code, html, said = upload(f"{base}/setup/charts", {},
                              {"upload": ("skin.conf", SKIN_CONF)})
    check("the skin is read", code, 303)
    check("and its charts land", len(_charts(path)), 3)
    check("replacing the starter set", before > 3, True)

    print("\n  its archive")
    source = work / "theirs.sdb"
    data = an_archive(source)
    code, html, said = upload(f"{base}/setup/upload-archive", {},
                              {"upload": ("weewx.sdb", data)})
    check("it is taken", code, 303)
    check("and counted", "60 records" in said, True)
    check("with a word about the original",
          "untouched" in said or "copy" in said, True)

    where = config_file.resolved_path(config_file.read(path), "archive_db",
                                      path.parent, "data/weewx.sdb")
    check("the file is here", where.is_file(), True)
    check("byte for byte", where.read_bytes()[:100] == data[:100], True)
    check("and theirs is where it was", source.is_file(), True)

    print("\n  and it will not write over readings")
    code, html, _said = upload(f"{base}/setup/upload-archive", {},
                               {"upload": ("weewx.sdb", data)})
    check("a second upload is refused",
          "already an archive" in problem(html), True)

    print("\n  what is not an archive is refused, not half-taken")
    where.unlink()
    for extra in ("-wal", "-shm"):
        where.with_name(where.name + extra).unlink(missing_ok=True)
    code, html, _said = upload(f"{base}/setup/upload-archive", {},
                               {"upload": ("notes.txt", b"milk\nbread\n")})
    check("named for what it is",
          "not a WeeWX archive" in problem(html), True)
    check("and nothing was left behind", where.exists(), False)


def _charts(path: Path) -> list:
    from weewx_evo import plots as plot_defs

    return list(plot_defs.load(path.parent / "plots.toml"))


def the_wizard_reopens(base: str) -> None:
    """It is not a one-off, and the steps behind you are reachable."""
    print("\nit can be reopened, and gone back through")
    code, html = get(f"{base}/setup/place")
    check("a step opens on its own", code, 200)
    check("with what was answered still in it",
          "Kirchdorf an der Amper" in html, True)
    code, html = get(f"{base}/setup/done")
    check("the last page says what is set up", code, 200)
    check("and names the one thing left",
          "One thing left" in html or "Add a station" in html, True)


def what_ships() -> None:
    """The files a fresh clone needs, asked of git rather than of the disk.

    `starter/plots.toml` was ignored for a year: the pattern was written for
    the running installation's file, has no slash, and a pattern without a
    slash matches at every level. Here the file exists and everything works;
    a clone got a wizard that configured no charts, and said nothing, because
    `is_starter()` answers True for a file that is not there -- correct for
    an installation, and identical to this.

    So: ask the index, not the filesystem. That is the only question that
    distinguishes the two.
    """
    print("\n  what a fresh clone gets")
    repo = Path(__file__).resolve().parent.parent
    if not (repo / ".git").exists():
        # A tarball or an installed copy. There is no index to ask, and that
        # is not a failure.
        print("    not a checkout, nothing to ask")
        return
    # The repo is mounted into the test container and owned by somebody else,
    # which git refuses to read from by default. Saying so here rather than
    # skipping: a check that goes quiet on the machine built to run it is the
    # thing this file exists to catch.
    listed = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "ls-files", "--", "src/"],
        cwd=repo, check=False, capture_output=True, text=True)
    if listed.returncode != 0:
        check(f"    git can read the index ({listed.stderr.strip()[:70]})",
              False, True)
        return
    tracked = set(listed.stdout.split())

    # Data files the code reads at runtime. Python modules are found by
    # import and would fail loudly; these fail quietly.
    here = sorted(str(one.relative_to(repo)).replace("\\", "/")
                  for one in (repo / "src").rglob("*")
                  if one.is_file() and one.suffix in (".toml", ".conf", ".css",
                                                      ".tmpl", ".inc", ".js",
                                                      ".php", ".svg", ".html")
                  and "__pycache__" not in one.parts)
    missing = [one for one in here if one not in tracked]
    for one in missing:
        print(f"    on the disk but not in the index: {one}")
    check(f"    all {len(here)} data files ship", len(missing), 0)


def main() -> int:
    print("the setup wizard, over the web only")

    work = Path(tempfile.mkdtemp(prefix="weewx-evo-setup-"))
    try:
        path = work / "evo.toml"
        admin = Admin(path, lambda: all_schemas(path), TOKEN,
                      limits=Limits(rate=0, failures=0))
        server = AdminServer(admin, "127.0.0.1", 0)
        server.start()
        base = f"http://127.0.0.1:{server.port}/{TOKEN}"
        print(f"  settings on {base}")
        print(f"  nothing in {work} but what the page writes")

        a_fresh_station(base, path)
        moving_over(base, path, work)
        the_wizard_reopens(base)
        what_ships()

        server.stop()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("an empty directory to a configured station, by forms alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())

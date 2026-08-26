"""Send files, for real, and check that the second run sends nothing.

The FTP half runs against a server started in this process, so the transfer
is actually tested rather than mocked: files land on disk, directories get
made, and the rename-into-place happens. `pyftpdlib` is not a dependency of
weewx-evo, so that part is skipped when it is absent and the rest still runs.

The rsync half checks the command that would be run rather than running it,
because a real rsync needs a server with a key on it. What matters there is
what is on the argument list -- the trailing slash, `--delete` being absent
unless asked, nothing going through a shell -- and that can be read.

    python tools/export_test.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.exports import walk  # noqa: E402
from weewx_evo.exports.ftp import FtpExport  # noqa: E402
from weewx_evo.exports.rsync import RsyncExport  # noqa: E402
from weewx_evo.exports.tracker import Fingerprint, Tracker  # noqa: E402


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


def make_site(root: Path) -> Path:
    """Something shaped like what a feed would produce."""
    site = root / "public_html"
    (site / "css").mkdir(parents=True)
    (site / "images").mkdir(parents=True)
    (site / "index.html").write_text("<h1>21.4 C</h1>", encoding="utf-8")
    (site / "week.html").write_text("<h1>week</h1>", encoding="utf-8")
    (site / "css" / "site.css").write_text("body{}", encoding="utf-8")
    (site / "images" / "temp.png").write_bytes(b"\x89PNG" + b"\0" * 900)
    (site / ".git").mkdir()
    (site / ".git" / "config").write_text("secret", encoding="utf-8")
    return site


def main() -> int:
    failures = 0
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-export-"))
    try:
        site = make_site(tmp)

        print("what gets walked")
        found = {p.as_posix() for p in walk(site)}
        failures += not check("the files", sorted(found),
                              ["css/site.css", "images/temp.png", "index.html",
                               "week.html"])
        failures += not check("and never .git",
                              any(".git" in p for p in found), False)

        print("\nthe record of what was sent")
        tracker = Tracker(tmp / "sent.json")
        files = walk(site)
        wanted, skipped = tracker.changed(site, files)
        failures += not check("everything, the first time", len(wanted), 4)
        failures += not check("nothing skipped", skipped, 0)
        for relative in files:
            tracker.record(site, relative)
        wanted, skipped = tracker.changed(site, files)
        failures += not check("nothing, the second time", len(wanted), 0)
        failures += not check("all skipped", skipped, 4)

        print("\na rewritten file with identical bytes is not sent again")
        # The case that matters: a template rewrites index.html every run with
        # the same content, and its timestamp moves. Comparing timestamps
        # alone would send the whole site every five minutes.
        time.sleep(0.01)
        (site / "index.html").write_text("<h1>21.4 C</h1>", encoding="utf-8")
        wanted, skipped = tracker.changed(site, files)
        failures += not check("still nothing", len(wanted), 0)

        print("\nand a changed one is")
        (site / "index.html").write_text("<h1>22.9 C</h1>", encoding="utf-8")
        wanted, _ = tracker.changed(site, files)
        failures += not check("just that one",
                              [p.as_posix() for p in wanted], ["index.html"])

        print("\na big file is compared by size and time, not content")
        big = site / "images" / "big.png"
        big.write_bytes(b"\0" * (300 * 1024))
        fingerprint = Fingerprint.of(big)
        failures += not check("no digest kept", fingerprint.digest, "")
        failures += not check("but a size", fingerprint.size, 300 * 1024)

        print("\nwhat gets deleted is only what we sent")
        (site / "week.html").unlink()
        gone = tracker.gone(walk(site))
        failures += not check("the one that vanished", gone, ["week.html"])

        failures += runner_tests(tmp)
        failures += ftp_tests(tmp, site)
        failures += rsync_tests(tmp, site)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


class FakeExport:
    """An export that records what it was asked to send, and when."""

    def __init__(self, trigger: str = "feed", every: int = 900,
                 slow: float = 0.0) -> None:
        self.trigger = trigger
        self.every = every
        self.slow = slow
        self.calls: list[object] = []

    def send(self, source, files=None):
        from weewx_evo.exports import Sent

        self.calls.append(files)
        if self.slow:
            time.sleep(self.slow)
        return Sent(sent=1)


def runner_tests(tmp: Path) -> int:
    """When each export runs, and that one cannot hold up another."""
    from weewx_evo.exports.runner import Runner, Scheduled

    print("\nwhen an export runs")
    failures = 0

    site = Scheduled("site", FakeExport("feed"), tmp, feed="website")
    csv = Scheduled("csv", FakeExport("feed"), tmp, feed="csvdump")
    backup = Scheduled("backup", FakeExport("record"), tmp)
    asked = Scheduled("asked", FakeExport("manual"), tmp)
    runner = Runner([site, csv, backup, asked])
    runner.start()
    try:
        time.sleep(0.2)
        # The point of coupling: the export that sends this feed runs, and
        # only that one. Two feeds writing two sites must not each trigger
        # both uploads.
        runner.feed_produced("website", [Path("index.html")])
        time.sleep(0.5)
        failures += not check("the feed's export ran", site.runs, 1)
        failures += not check("the other feed's did not", csv.runs, 0)
        failures += not check("nor the record one", backup.runs, 0)
        failures += not check("it was given what the feed wrote",
                              site.export.calls, [[Path("index.html")]])

        runner.record_written()
        time.sleep(0.5)
        failures += not check("a record runs the record one", backup.runs, 1)
        failures += not check("and not the feed ones", site.runs, 1)
        failures += not check("the manual one never runs by itself",
                              asked.runs, 0)
    finally:
        runner.stop()

    print("\n  a slow export cannot overlap itself")
    # Two FTP sessions writing the same files is how a site ends up half old
    # and half new. What prevents it is the one-thread-each arrangement and
    # not a check: the thread is inside send() and is not reading its own
    # trigger. What fires meanwhile is remembered and done afterwards.
    slow = Scheduled("slow", FakeExport("feed", slow=0.5), tmp, feed="website")
    runner = Runner([slow])
    runner.start()
    try:
        time.sleep(0.2)
        runner.feed_produced("website")
        time.sleep(0.2)
        failures += not check("it is running", slow.running, True)
        # Three more while it is busy. They collapse into one run afterwards:
        # nobody needs four uploads of a site that changed once.
        for _ in range(3):
            runner.feed_produced("website")
        time.sleep(1.2)
        failures += not check("it ran twice, not four times",
                              len(slow.export.calls), 2)
        failures += not check("and never two at once", slow.running, False)
    finally:
        runner.stop()

    print("\n  one that fails does not stop the others")
    class Broken(FakeExport):
        def send(self, source, files=None):
            raise RuntimeError("the host is down")

    broken = Scheduled("broken", Broken("feed"), tmp, feed="website")
    fine = Scheduled("fine", FakeExport("feed"), tmp, feed="website")
    runner = Runner([broken, fine])
    runner.start()
    try:
        time.sleep(0.2)
        runner.feed_produced("website")
        time.sleep(0.5)
        failures += not check("the broken one is counted", broken.failures, 1)
        failures += not check("and says why", broken.last_summary,
                              "the host is down")
        failures += not check("the other still ran", fine.runs, 1)
    finally:
        runner.stop()

    print("\n  coupled to a feed but pointed at a directory is refused")
    from weewx_evo.exports import runner as runner_module

    built = runner_module.build(
        {"wrong": {"kind": "ftp", "trigger": "feed",
                   "directory_source": str(tmp), "host": "h"}},
        lambda name, settings: FakeExport("feed"),
        lambda settings: tmp)
    failures += not check("it is left out rather than never running",
                          built, [])
    return failures


def ftp_tests(tmp: Path, site: Path) -> int:
    print("\nFTP, against a real server")
    try:
        from pyftpdlib.authorizers import DummyAuthorizer
        from pyftpdlib.handlers import FTPHandler
        from pyftpdlib.servers import FTPServer
    except ImportError:
        print("  -- skipped: pyftpdlib is not installed (pip install pyftpdlib)")
        return 0

    failures = 0
    served = tmp / "server"
    served.mkdir()

    authorizer = DummyAuthorizer()
    authorizer.add_user("weather", "secret", str(served), perm="elradfmwMT")
    handler = FTPHandler
    handler.authorizer = authorizer
    handler.banner = "test"
    server = FTPServer(("127.0.0.1", 0), handler)
    port = server.address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        export = FtpExport(host="127.0.0.1", port=port, user="weather",
                           password="secret", directory="/site", tls=False,
                           tracker=str(tmp / "ftp-sent.json"))

        # Four, not five: the tracker tests above deleted week.html and
        # added images/big.png.
        expected = len(walk(site))
        result = export.send(site)
        failures += not check("sent", result.sent, expected)
        failures += not check("no failures", result.failures, [])
        failures += not check("index.html arrived",
                              (served / "site" / "index.html").read_text(
                                  encoding="utf-8"), "<h1>22.9 C</h1>")
        failures += not check("in a subdirectory too",
                              (served / "site" / "css" / "site.css").exists(), True)
        failures += not check("and .git did not",
                              (served / "site" / ".git").exists(), False)
        failures += not check("nothing left half-uploaded",
                              list((served / "site").glob("*.uploading")), [])

        print("\n  the second run sends nothing")
        again = export.send(site)
        failures += not check("sent", again.sent, 0)
        failures += not check("skipped", again.skipped, expected)

        print("\n  a changed file goes on its own")
        (site / "index.html").write_text("<h1>23.5 C</h1>", encoding="utf-8")
        third = export.send(site)
        failures += not check("sent", third.sent, 1)
        failures += not check("and arrived",
                              (served / "site" / "index.html").read_text(
                                  encoding="utf-8"), "<h1>23.5 C</h1>")

        print("\n  deleting is off unless asked")
        (site / "css" / "site.css").unlink()
        export.send(site)
        failures += not check("still there", (served / "site" / "css" /
                                              "site.css").exists(), True)
        deleting = FtpExport(host="127.0.0.1", port=port, user="weather",
                             password="secret", directory="/site", tls=False,
                             delete=True, tracker=str(tmp / "ftp-sent.json"))
        removed = deleting.send(site)
        failures += not check("now removed", removed.deleted, 1)
        failures += not check("and gone", (served / "site" / "css" /
                                           "site.css").exists(), False)

        print("\n  check() says what it found")
        message = export.check()
        failures += not check("it connected", "Connected" in message, True)
        failures += not check("and warns about the encryption",
                              "unencrypted" in message, True)

        wrong = FtpExport(host="127.0.0.1", port=port, user="weather",
                          password="wrong", directory="/site", tls=False)
        failures += not check("a wrong password is reported",
                              "cannot reach" in wrong.check().lower()
                              or "530" in wrong.check(), True)
    finally:
        server.close_all()
    return failures


def rsync_tests(tmp: Path, site: Path) -> int:
    print("\nrsync, by reading the command it would run")
    failures = 0
    export = RsyncExport(host="example.org", user="weather",
                         directory="/var/www/weather", source=str(site))
    command = export._command(site, None)

    failures += not check("the binary", command[0], "rsync")
    failures += not check("archive mode", "--archive" in command, True)
    failures += not check("compressed", "--compress" in command, True)
    failures += not check("no --delete unless asked", "--delete" in command, False)
    # The trailing slash is the difference between copying the directory and
    # copying its contents. Without it the site nests inside itself.
    failures += not check("the source ends in a slash",
                          command[-2].endswith("/"), True)
    failures += not check("the target", command[-1],
                          "weather@example.org:/var/www/weather")
    ssh = command[command.index("-e") + 1]
    failures += not check("ssh never prompts", "BatchMode=yes" in ssh, True)
    failures += not check("and has a timeout", "ConnectTimeout" in ssh, True)

    print("\n  --delete when asked, and a key when given")
    export = RsyncExport(host="example.org", user="w", directory="/w",
                         source=str(site), delete=True, key="/keys/id_ed25519",
                         port=2222)
    command = export._command(site, None)
    failures += not check("--delete", "--delete" in command, True)
    ssh = command[command.index("-e") + 1]
    failures += not check("the key", "/keys/id_ed25519" in ssh, True)
    failures += not check("only that key", "IdentitiesOnly=yes" in ssh, True)
    failures += not check("the port", "-p 2222" in ssh, True)

    print("\n  nothing is interpolated into a shell")
    export = RsyncExport(host="example.org", user="w",
                         directory="/w; rm -rf /", source=str(site))
    command = export._command(site, None)
    failures += not check("the awkward path is one argument",
                          command[-1], "w@example.org:/w; rm -rf /")
    failures += not check("and it is a list, not a string",
                          isinstance(command, list), True)

    print("\n  counting what rsync said")
    result = export._read(
        ">f+++++++++ index.html\n"
        ">f..t...... css/site.css\n"
        "cd+++++++++ images/\n"
        "*deleting   old.html\n"
        ".f          unchanged.html\n")
    failures += not check("sent", result.sent, 2)
    failures += not check("deleted", result.deleted, 1)
    failures += not check("skipped", result.skipped, 2)

    print("\n  a missing rsync is said plainly")
    export = RsyncExport(host="example.org", user="w", directory="/w",
                         source=str(site), rsync="rsync-that-is-not-installed")
    failures += not check("check() says so",
                          "not installed" in export.check(), True)
    return failures


if __name__ == "__main__":
    raise SystemExit(main())

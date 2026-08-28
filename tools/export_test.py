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

from weewx_evo.exports import walk
from weewx_evo.exports.ftp import FtpExport
from weewx_evo.exports.rsync import RsyncExport
from weewx_evo.exports.tracker import Fingerprint, Tracker


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



def local_export(check) -> int:
    """Publishing to a directory, and the web server picking it up.

    The destination most stations actually use. Its failure modes are not
    FTP's: a hard link that quietly shares an inode, a delete that takes
    somebody else's file, a directory published into itself.
    """
    import shutil
    import tempfile
    import time
    import urllib.request
    from pathlib import Path

    from weewx_evo.exports import ExportError
    from weewx_evo.exports.local import LocalExport
    from weewx_evo.netaccess import Access
    from weewx_evo.webserver import WebServer, site_from

    failures = 0
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-local-"))
    try:
        source = tmp / "feed"
        (source / "css").mkdir(parents=True)
        (source / "index.html").write_text("<h1>21.4</h1>", encoding="utf-8")
        (source / "css" / "a.css").write_text("body{}", encoding="utf-8")
        (source / "data.json").write_text('{"a":1}', encoding="utf-8")
        site = tmp / "site"

        export = LocalExport(directory=str(site), source="json",
                             tracker=str(tmp / "sent.json"))

        print("\nit publishes what the feed wrote")
        result = export.send(source)
        failures += not check("three files", result.sent, 3)
        failures += not check("the structure is kept",
                              (site / "css" / "a.css").exists(), True)
        failures += not check("and the content arrives",
                              (site / "index.html").read_text(encoding="utf-8"),
                              "<h1>21.4</h1>")

        print("\nand does nothing at all the second time")
        result = export.send(source)
        failures += not check("nothing sent", result.sent, 0)
        failures += not check("everything skipped", result.skipped, 3)
        failures += not check("and it says so", result.note, "nothing had changed")

        print("\none changed file is one file")
        (source / "index.html").write_text("<h1>22.9</h1>", encoding="utf-8")
        result = export.send(source)
        failures += not check("sent", result.sent, 1)
        failures += not check("skipped", result.skipped, 2)
        failures += not check("the new content is out there",
                              (site / "index.html").read_text(encoding="utf-8"),
                              "<h1>22.9</h1>")

        print("\nwhat it did not put there is not its to delete")
        # The failure that cannot be undone: a directory holds a
        # hand-written page as well, and mirroring takes it away.
        (site / "by-hand.html").write_text("mine", encoding="utf-8")
        (source / "data.json").unlink()
        export.delete = True
        result = export.send(source)
        failures += not check("the feed's file went", (site / "data.json").exists(),
                              False)
        failures += not check("it was counted", result.deleted, 1)
        failures += not check("and the other one stayed",
                              (site / "by-hand.html").exists(), True)

        print("\nnothing half-written is ever published")
        # A feed writes beside and moves into place. The .part in between is
        # a file somebody is in the middle of writing, and publishing one
        # leaves half a page under a name nothing will overwrite.
        (source / "index.html.part").write_text("<h1>hal", encoding="utf-8")
        export.send(source)
        failures += not check("the half-written file stayed behind",
                              (site / "index.html.part").exists(), False)
        (source / "index.html.part").unlink()

        print("\nand a hard link is not renamed onto itself")
        # Rename between two hard links to one file is a no-op that reports
        # success. Done blindly, the partial survives every run for ever.
        again = LocalExport(directory=str(site), tracker=str(tmp / "t3.json"))
        again.send(source)
        again.send(source)
        failures += not check("no leftover partial",
                              sorted(f.name for f in site.rglob("*.part")), [])

        print("\ntwo exports into one directory do not eat each other")
        # A skin publishes its pages from one feed and its charts from
        # another, into the same directory, because <img src="x.png">
        # looks beside the page. Both remembered what they had sent in
        # one file named after the destination, so each saw the other's
        # files as ones its own feed no longer produces -- and deleted
        # them. They took turns: 70 sent, 13 removed; 13 sent, 70
        # removed. The published site never had both halves at once.
        pages = tmp / "feeds" / "pages"
        charts = tmp / "feeds" / "charts"
        together = tmp / "published"
        for where, name, text in ((pages, "index.html", "<h1>hi</h1>"),
                                  (charts, "day.png", "not really a png")):
            where.mkdir(parents=True, exist_ok=True)
            (where / name).write_text(text, encoding="utf-8")

        page_export = LocalExport(directory=str(together), delete=True)
        chart_export = LocalExport(directory=str(together), delete=True)
        # Twice each, alternating: the first run of either is a full
        # scan, and a full scan is where the deleting happens.
        for _round in range(2):
            page_export.send(pages)
            chart_export.send(charts)
        failures += not check("both halves are published",
                              sorted(f.name for f in together.iterdir()
                                     if f.is_file()),
                              ["day.png", "index.html"])
        failures += not check("and they kept separate records",
                              len({page_export._tracker_for(pages).path,
                                   chart_export._tracker_for(charts).path}),
                              2)

        print("\n  and an existing record is carried over, once")
        # The first version of this fix let both exports keep reading the
        # old shared file, so that nobody had to re-upload a site. That
        # is exactly what kept them eating each other. It is renamed
        # instead: the first to ask inherits the history, the second
        # starts empty, and an empty record deletes nothing.
        from weewx_evo.exports.local import _slug, _tracker_path

        legacy = tmp / "legacy"
        (legacy / "a").mkdir(parents=True, exist_ok=True)
        (legacy / "b").mkdir(parents=True, exist_ok=True)
        shared = legacy / f".sent-local-{_slug('/tmp/out')}.json"
        shared.write_text('{"files": {}}', encoding="utf-8")
        first = _tracker_path(legacy / "a", "/tmp/out", "local")
        failures += not check("the first one inherits it",
                              first.is_file(), True)
        second = _tracker_path(legacy / "b", "/tmp/out", "local")
        failures += not check("the second gets its own", second != first,
                              True)
        failures += not check("and it is empty", second.is_file(), False)
        failures += not check("the shared one is gone", shared.is_file(),
                              False)

        print("\nclearing up is what it does unasked")
        # Otherwise nothing ever does. A renamed chart leaves its file
        # behind for good, and a feed with dated filenames fills the disk
        # one file a day. Bounded by the record of what was sent, so what
        # this export did not put there is never touched.
        failures += not check("a local export mirrors by default",
                              LocalExport(directory=str(tmp)).delete, True)
        from weewx_evo.exports.rsync import RsyncExport

        # rsync is the exception, and not out of timidity: --delete
        # removes everything in the target that is not in the source,
        # with no record bounding it. In a mistyped directory that is the
        # directory.
        rsync_delete = next(
            o for g in RsyncExport.options() for o in g.options
            if o.name == "delete")
        failures += not check("rsync does not, because its is unbounded",
                              rsync_delete.default, False)
        print("\ndeleting is decided against the whole directory")
        # Given the handful of files a feed just wrote, everything else
        # looks gone. It is not: it is the rest of the site. Worse, the
        # record of what was sent forgets them too, so the next run sends
        # them all again and the one after deletes them again.
        mirror = LocalExport(directory=str(tmp / "mirror"), delete=True,
                             tracker=str(tmp / "t4.json"))
        (source / "one.json").write_text("{}", encoding="utf-8")
        (source / "two.json").write_text("{}", encoding="utf-8")
        mirror.send(source)
        before = sorted(f.name for f in (tmp / "mirror").rglob("*")
                        if f.is_file())
        partial = mirror.send(source, files=[Path("one.json")])
        after = sorted(f.name for f in (tmp / "mirror").rglob("*")
                       if f.is_file())
        failures += not check("a partial run deletes nothing",
                              partial.deleted, 0)
        failures += not check("and leaves the rest alone", after, before)

        # A full run still mirrors.
        (source / "two.json").unlink()
        gone = mirror.send(source)
        failures += not check("a full run still removes what went",
                              gone.deleted, 1)
        print("\nsome things are refused rather than attempted")
        try:
            LocalExport(directory=str(source),
                        tracker=str(tmp / "t2.json")).send(source)
            failures += not check("publishing into itself", "allowed", "refused")
        except ExportError as exc:
            failures += not check("publishing into itself",
                                  "source directory" in str(exc), True)
        try:
            LocalExport().send(source)
            failures += not check("with no destination", "allowed", "refused")
        except ExportError as exc:
            failures += not check("with no destination",
                                  "no directory" in str(exc), True)

        print("\nand it says whether it can write before it tries")
        said = export.check()
        failures += not check("names the directory", str(site.resolve()) in said,
                              True)
        failures += not check("and says it is writable", "writable" in said, True)

        print("\na relative directory means beside the settings file")
        # In a container the working directory is inside the image. A
        # local export writing "data/site" there publishes to a place
        # nothing serves and nothing keeps, and the web server reading
        # the same setting looks somewhere else again.
        import argparse

        from weewx_evo.cli import resolve_paths

        config = tmp / "etc" / "evo.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        fake_args = argparse.Namespace(config=config)
        made = resolve_paths(fake_args, {"kind": "local",
                                         "directory": "data/site"})
        failures += not check("resolved against the file",
                              made["directory"],
                              str(tmp / "etc" / "data" / "site"))
        kept = resolve_paths(fake_args, {"kind": "ftp",
                                         "directory": "/httpdocs"})
        failures += not check("but a remote directory is left alone",
                              kept["directory"], "/httpdocs")
        print("\nthe whole schedule is built, the way serve builds it")
        # The one check that would have caught it: `build_schedule` calls
        # `build_export` with the station's upload token, and nothing else in
        # this file walks that call. A signature that had never been given a
        # third argument reached a running instance, where every export said
        # "not usable" at startup and nothing else looked wrong.
        from weewx_evo.cli import build_schedule, settings_for

        schedule_config = tmp / "schedule" / "evo.toml"
        schedule_config.parent.mkdir(parents=True, exist_ok=True)
        # The directory both are pointed at has to exist: an export with
        # nothing to send is left out, and then this would pass for the
        # wrong reason.
        (schedule_config.parent / "data" / "work").mkdir(parents=True)
        schedule_config.write_text(
            'archive_db = "data/weewx.sdb"\n'
            'token = "station-upload-token"\n'
            '[exports.site]\n'
            'kind = "local"\n'
            'directory = "data/site"\n'
            'directory_source = "data/work"\n'
            'trigger = "manual"\n'
            '[exports.away]\n'
            'kind = "ftp"\n'
            'host = "ftp.example.org"\n'
            'user = "u"\n'
            'password = "p"\n'
            'directory = "/httpdocs"\n'
            'directory_source = "data/work"\n'
            'trigger = "manual"\n'
            'live_push_url = "https://example.org/wetter"\n',
            encoding="utf-8")
        schedule_args = argparse.Namespace(config=schedule_config)
        schedule = build_schedule(schedule_args, settings_for(schedule_args))
        failures += not check("both exports were built", len(schedule), 2)

        built_exports = {entry.name: entry.export for entry in schedule}
        failures += not check(
            "the token reached the one that carries live.php",
            getattr(built_exports.get("away"), "upload_token", None),
            "station-upload-token")
        failures += not check(
            "and the local one, which uses the same switch differently",
            getattr(built_exports.get("site"), "upload_token", None),
            "station-upload-token")


        print("\nthe web server serves what a local export published")
        # Nobody says the path twice: an export named `site` is at /site/.
        class Settings:
            def __init__(self, config):
                self.config = config

            def get(self, key):
                return {"station.name": "Kirchdorf"}.get(key)

        built = site_from(Settings({
            "exports": {
                "site": {"kind": "local", "directory": str(site)},
                "away": {"kind": "ftp", "host": "ftp.example.org"},
            },
            "web": {"default": "site"},
        }))
        failures += not check("the local export is served",
                              "site" in built.feeds, True)
        failures += not check("the FTP one is not", "away" in built.feeds, False)
        failures += not check("and it can be the default", built.default, "site")

        server = WebServer(built, "127.0.0.1", 0, access=Access.parse("any"))
        server.start()
        time.sleep(0.2)
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.port}/", timeout=5) as reply:
                body = reply.read().decode("utf-8", "replace")
            failures += not check("and it answers at /", body, "<h1>22.9</h1>")
        except Exception as exc:
            failures += not check("and it answers at /", str(exc), "no error")
        finally:
            server.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return failures


def feed_to_export(check) -> int:
    """A feed finishing is what starts an export set to wait for it.

    The link that was missing: the export runner has `feed_produced`, the
    feed runner writes the files, and for a while nothing joined the two. An
    export configured exactly as the settings page writes it sat waiting for
    a signal nobody sent, and said nothing about it.
    """
    import shutil
    import tempfile
    import time
    from pathlib import Path

    from weewx_evo import feedrunner
    from weewx_evo.exports import Sent
    from weewx_evo.exports import runner as export_runner

    failures = 0
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-chain-"))
    try:
        work = tmp / "work"
        work.mkdir()

        class Fake:
            """Stands in for a feed. Writes one file and says it did."""

            def produce(self, into, now=None):
                Path(into).mkdir(parents=True, exist_ok=True)
                written = Path(into) / "index.html"
                written.write_text("<h1>21.4</h1>", encoding="utf-8")
                from weewx_evo.feeds import Produced

                return Produced(directory=Path(into), files=[written],
                                note="one file")

        published: list[tuple[str, int]] = []

        class Destination:
            trigger = "feed"

            def send(self, source, files=None):
                # Like a real export: `None` means look at the directory.
                from weewx_evo.exports import walk

                sending = walk(Path(source), files)
                published.append((str(source), len(sending)))
                return Sent(sent=len(sending))

        scheduled = [export_runner.Scheduled(
            name="site", export=Destination(), source=work, feed="json")]
        exports = export_runner.Runner(scheduled)
        exports.start()

        feeds = feedrunner.Runner([("json", lambda _reader: Fake(), work)],
                                  archive_path=tmp / "nothing.sdb")
        feeds.on_produced = exports.feed_produced

        # No archive on disk, so run the feeds the way the loop would once
        # there is one.
        (tmp / "nothing.sdb").write_bytes(b"")
        feeds.run_once()

        for _ in range(50):
            if published:
                break
            time.sleep(0.1)
        exports.stop()

        # An export added to a station that has been running catches up.
        # Given only the feed's changed list it would send one file and
        # never the sixty-nine that changed before it existed.
        first = published[0][1] if published else 0
        failures += not check("the export ran", bool(published), True)
        if published:
            failures += not check("with the feed's directory",
                                  published[0][0], str(work))
            failures += not check("and the whole directory the first time",
                                  first, 1)

        # A file that was there before the export existed is still sent.
        (work / "older.json").write_text("{}", encoding="utf-8")
        scheduled[0].caught_up = False
        scheduled[0].changed = [Path("index.html")]
        published.clear()
        scheduled[0].run()
        failures += not check("a first run looks at everything",
                              published[0][1] if published else 0, 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return failures


def two_feeds_one_export(check) -> int:
    """A skin and the charts it draws from, published together.

    A skin is its pages *and* its diagrams, and those are two feeds writing
    two directories. Publishing one of them puts up a site whose charts are
    empty. Two exports to the same account move the files, but nothing holds
    the second until the first has finished -- so the pages can arrive before
    the charts they point at, which is the half-published site the `feed`
    trigger exists to prevent.

    So: one export, several feeds, each with where it lands, and it waits for
    all of them.
    """
    import tempfile
    import time
    from pathlib import Path

    from weewx_evo.exports import runner as export_runner
    from weewx_evo.exports.local import LocalExport

    failures = 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)
        pages, charts, target = work / "deck", work / "json", work / "site"
        pages.mkdir()
        charts.mkdir()
        (pages / "index.html").write_text("<p>21.4</p>", encoding="utf-8")
        (charts / "outTemp.json").write_text("[1,2,3]", encoding="utf-8")

        export = LocalExport(directory=str(target), delete=True,
                             live_push=False)
        made = export_runner.build(
            {"site": {"source": "deck", "also": ["json -> data/json"],
                      "trigger": "feed"}},
            lambda name, settings: export,
            lambda settings: pages,
            feeds={"deck": pages, "json": charts})
        failures += not check("one export", len(made), 1)
        one = made[0]
        failures += not check("waiting for both", list(one.feeds),
                              ["deck", "json"])

        now = time.monotonic()
        failures += not check("the skin alone is not enough",
                              one.due(now, "deck"), False)
        failures += not check("with the charts it goes",
                              one.due(now, "json"), True)

        one.run()
        landed = sorted(f.relative_to(target).as_posix()
                        for f in target.rglob("*") if f.is_file())
        failures += not check("both, each where it belongs", landed,
                              ["data/json/outTemp.json", "index.html"])

        # The failure this arrangement invites: one source walking the
        # destination and deleting what the other put there. Each keeps its
        # own record, so neither can see the other's files as gone.
        one.due(time.monotonic(), "deck")
        one.due(time.monotonic(), "json")
        one.run()
        still = sorted(f.relative_to(target).as_posix()
                       for f in target.rglob("*") if f.is_file())
        failures += not check("and a second run keeps both", still, landed)

        # A feed nobody configured is left out rather than waited for: an
        # export that waits for a name in an old line never runs again.
        stray = export_runner.build(
            {"site": {"source": "deck", "also": ["ghost -> x"],
                      "trigger": "feed"}},
            lambda name, settings: export,
            lambda settings: pages,
            feeds={"deck": pages})
        failures += not check("an unknown feed is not waited for",
                              list(stray[0].feeds), ["deck"])

        # And rsync, which deletes by comparing the far end with the source
        # rather than from a record -- so the other feed's path has to be
        # named to it, or the first source of every run removes it.
        from weewx_evo.exports.rsync import RsyncExport

        pushed = RsyncExport(host="h", directory="/var/www", delete=True,
                             live_push=False)
        line = pushed._command(pages, None, into="", protect=("data/json",))
        failures += not check("rsync is told to protect it",
                              "--filter=P /data/json/" in line, True)
        second = pushed._command(charts, None, into="data/json")
        failures += not check("and the second source lands under it",
                              second[-1].endswith(":/var/www/data/json"), True)
    return failures


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

    failures += local_export(check)
    failures += feed_to_export(check)
    failures += two_feeds_one_export(check)


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
        # The first run looks at the whole directory: an export added to a
        # station that has been going for a week has never sent any of it,
        # and the feed only ever names what changed this minute.
        failures += not check("the first run looks at everything",
                              site.export.calls, [None])

        runner.feed_produced("website", [Path("index.html")])
        time.sleep(0.5)
        failures += not check("and after that, what the feed wrote",
                              site.export.calls, [None, [Path("index.html")]])
        failures += not check("which is one more run", site.runs, 2)

        runner.record_written()
        time.sleep(0.5)
        failures += not check("a record runs the record one", backup.runs, 1)
        failures += not check("and not the feed ones", site.runs, 2)
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

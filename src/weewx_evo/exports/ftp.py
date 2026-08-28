"""FTP and FTPS.

Shared hosting still gives you FTP and often nothing else, so this exists and
has to work on the awkward end of it: servers that lose the connection halfway
through, that cannot make a directory that already exists without erroring,
that answer `MDTM` with nonsense, and that count a passive connection from a
different address as an attack.

Three decisions worth stating, because each one came from that:

**TLS by default, and a warning when it is off.** `FTP_TLS` is the same
protocol with the credentials not in clear text. Plain FTP sends the password
across the network as text, and on shared hosting that password is usually the
one for everything else on the account. It stays available -- some hosts still
have no TLS -- but it says so every time.

**Uploaded beside, then renamed.** A visitor loading a page while it is being
written gets half a page; a rename is atomic on any sane server. It costs one
extra command per file and removes a whole class of "the site looked broken
for a moment" that is otherwise impossible to reproduce.

**Nothing is deleted unless asked.** Removing files from somebody's web host
because they are no longer produced is the kind of helpfulness that eventually
removes something else.
"""

from __future__ import annotations

import ftplib
import logging
import time
from pathlib import Path
from typing import Any

from . import BaseExport, ExportError, Sent, also_option, live_push_options
from .local import _tracker_path, walk
from .tracker import Tracker

log = logging.getLogger(__name__)

#: Long enough for a slow host, short enough that a dead one does not hold up
#: the next archive interval.
TIMEOUT = 30


class FtpExport(BaseExport):
    """Sends a directory to an FTP server."""

    label = "FTP"
    #: One line for the form that offers the kinds. Somebody adding an
    #: export is choosing a destination, and "local" on its own is not a
    #: destination.
    summary = (
        "A web host over FTP. What shared hosting gives you, and the "
        "reason the record of what was already sent has to exist.")

    def __init__(self, host: str = "", user: str = "", password: str = "",
                 directory: str = "/", port: int = 21, tls: bool = True,
                 passive: bool = True, source: str = "",
                 live_push: bool = True, live_push_url: str = "",
                 upload_token: str = "",
                 delete: bool = False, tracker: str = "",
                 timeout: int = TIMEOUT,
                 directory_source: str = "",
                 trigger: str = "feed", every: int = 900) -> None:
        self.host = host.strip()
        # `live.php` and its token, sent with the pages. See
        # `exports.livepush` for what it is and why it is derived.
        self.live_push = bool(live_push)
        self.live_push_url = str(live_push_url or "").rstrip("/")
        self.upload_token = str(upload_token or "")
        self.user = user
        self.password = password
        self.directory = "/" + directory.strip("/") if directory.strip("/") else "/"
        self.port = int(port)
        self.tls = bool(tls)
        self.passive = bool(passive)
        # A feed name, or empty. The directory is where the files are
        # when no feed was chosen -- feeds do not exist yet.
        self.source = source
        self.directory_source = directory_source
        # When this runs. The runner reads it; the export itself
        # never decides when it happens.
        self.trigger = trigger
        self.every = int(every)
        self.delete = bool(delete)
        self.timeout = int(timeout)
        self._tracker_path = tracker
        #: One per (source, sub-path). See `_tracker_for` in local.py.
        self._trackers: dict[str, Tracker] = {}
        self._made: set[str] = set()

    # -- the export interface --------------------------------------------

    def send(self, source: Path, files: list[Path] | None = None,
             into: str = "", protect: tuple[str, ...] = ()) -> Sent:
        source = Path(source)
        if not self.host:
            raise ExportError("no host is set")
        if not source.is_dir():
            raise ExportError(f"{source} is not a directory")
        # Where this source lands, which is the account's directory unless a
        # second feed was pointed at a path under it.
        base = self._under(into)

        # `live.php` and its token first, so they are picked up like
        # any other file -- which means the record of what was
        # already sent stops them going again every five minutes.
        self.prepare(source)

        started = time.monotonic()
        result = Sent()
        tracker = self._tracker_for(source, into)

        candidates = walk(source, files)
        wanted, result.skipped = tracker.changed(source, candidates)
        if not wanted and not self.delete:
            result.seconds = time.monotonic() - started
            result.note = "nothing had changed"
            return result

        connection = self._connect()
        try:
            self._made.clear()
            for relative in wanted:
                try:
                    result.bytes += self._put(connection, source, relative,
                                              base)
                    tracker.record(source, relative)
                    result.sent += 1
                except (ftplib.all_errors, OSError) as exc:
                    # One file, not the run. A page nobody can read must not
                    # cost the upload of everything after it.
                    result.failures.append((relative.as_posix(), str(exc)))
                    log.warning("could not send %s: %s", relative, exc)

            if self.delete and files is None:
                # Only against a full listing, never against the changed
                # files a feed reported: everything it did not mention would
                # look gone, and this deletes from somebody's web host.
                result.deleted = self._remove(connection, tracker,
                                              candidates, base)
        finally:
            tracker.save()
            try:
                connection.quit()
            except Exception:
                connection.close()

        result.seconds = time.monotonic() - started
        return result

    def check(self) -> str:
        """Connect, look at the target directory, and say what happened."""
        if not self.host:
            return "No host is set."
        try:
            connection = self._connect()
        except ExportError as exc:
            return str(exc)
        try:
            connection.cwd(self.directory)
            listing = connection.nlst()
            how = "FTPS" if self.tls else "FTP, unencrypted"
            return (f"Connected over {how} to {self.host} as {self.user}. "
                    f"{self.directory} has {len(listing)} entries.")
        except ftplib.all_errors as exc:
            return (f"Connected to {self.host}, but {self.directory} could not "
                    f"be opened: {exc}")
        finally:
            try:
                connection.quit()
            except Exception:
                connection.close()

    def status(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "directory": self.directory,
            "encrypted": self.tls,
            "remembers": sum(len(t) for t in self._trackers.values()),
        }

    # -- the awkward parts -----------------------------------------------

    def _connect(self) -> ftplib.FTP:
        cls = ftplib.FTP_TLS if self.tls else ftplib.FTP
        if not self.tls:
            log.warning("sending to %s over plain FTP: the password crosses the "
                        "network as text. Turn on TLS if the host allows it.",
                        self.host)
        try:
            connection = cls(timeout=self.timeout)
            connection.connect(self.host, self.port)
            connection.login(self.user, self.password)
            if isinstance(connection, ftplib.FTP_TLS):
                # Without this the commands are encrypted and the files are
                # not, which is the worst of both and easy not to notice.
                connection.prot_p()
            connection.set_pasv(self.passive)
        except ftplib.all_errors as exc:
            raise ExportError(f"cannot reach {self.host}: {exc}") from exc
        return connection

    def _under(self, into: str) -> str:
        """The remote directory one source writes into."""
        trimmed = (into or "").strip("/")
        if not trimmed:
            return self.directory
        return f"{self.directory.rstrip('/')}/{trimmed}"

    def _put(self, connection: ftplib.FTP, source: Path, relative: Path,
             base: str = "") -> int:
        remote_dir = self._remote_dir(relative, base or self.directory)
        self._ensure(connection, remote_dir)

        target = f"{remote_dir}/{relative.name}".replace("//", "/")
        # Beside, then renamed: a visitor loading the page mid-upload would
        # otherwise get half of it.
        temporary = f"{target}.uploading"
        full = source / relative
        with open(full, "rb") as fp:
            connection.storbinary(f"STOR {temporary}", fp)
        try:
            connection.delete(target)
        except ftplib.all_errors:
            pass  # it was not there, which is the normal case
        connection.rename(temporary, target)
        return full.stat().st_size

    def _remote_dir(self, relative: Path, base: str = "") -> str:
        base = base or self.directory
        parent = relative.parent.as_posix()
        if parent in (".", ""):
            return base
        return f"{base.rstrip('/')}/{parent}"

    def _ensure(self, connection: ftplib.FTP, remote: str) -> None:
        """Make a directory and its parents, tolerating any that exist.

        `MKD` on an existing directory is an error on most servers and a
        success on some, so the error is what has to be tolerated -- and only
        after checking, because a real permission problem should still be
        heard.
        """
        if remote in self._made or remote == self.directory:
            self._made.add(remote)
            return
        parts = remote.strip("/").split("/")
        path = ""
        for part in parts:
            path = f"{path}/{part}"
            if path in self._made:
                continue
            try:
                connection.mkd(path)
            except ftplib.all_errors:
                # Either it exists, or we cannot make it. Ask.
                try:
                    connection.cwd(path)
                except ftplib.all_errors as exc:
                    raise ExportError(f"cannot make or enter {path}: {exc}") from exc
            self._made.add(path)

    def _remove(self, connection: ftplib.FTP, tracker: Tracker,
                present: list[Path], base: str = "") -> int:
        """Delete what we sent before and is no longer produced.

        Only ever files this export put there: the record says what those are,
        so nothing else on the account is at risk -- including the files of
        another feed this same export sends into a path beside this one,
        which has a record of its own.
        """
        removed = 0
        base = base or self.directory
        for name in tracker.gone(present):
            target = f"{base.rstrip('/')}/{name}"
            try:
                connection.delete(target)
                tracker.forget(Path(name))
                removed += 1
            except ftplib.all_errors as exc:
                log.debug("could not remove %s: %s", target, exc)
                tracker.forget(Path(name))
        return removed

    def _tracker_for(self, source: Path, into: str = "") -> Tracker:
        """One record per source and sub-path. See the note in local.py."""
        key = f"{source}\0{into}"
        found = self._trackers.get(key)
        if found is None:
            where = (Path(self._tracker_path)
                     if self._tracker_path and not into
                     else _tracker_path(
                         source, f"{self.host}-{self._under(into)}", "ftp"))
            found = Tracker(where)
            self._trackers[key] = found
        return found

    # -- what the admin page asks for ------------------------------------

    @staticmethod
    def options() -> list:
        from ..options import Group, Option
        from . import _feed_choices

        return [
            Group("Where it goes", "", (
                Option("host", "Server", required=True,
                       placeholder="ftp.example.org",
                       help="The FTP host. Not a URL -- just the name."),
                Option("user", "User", required=True),
                Option("password", "Password", kind="secret", required=True),
                Option("directory", "Directory", default="/",
                       placeholder="/httpdocs",
                       help="Where on the server the files go. On shared "
                            "hosting this is usually something like /httpdocs "
                            "or /public_html, and rarely the login directory."),
                Option("port", "Port", kind="int", default=21,
                       minimum=1, maximum=65535, advanced=True),
            )),
            Group("What is sent", "", (
                # Not required: a feed *or* a directory, and the schema
                # cannot say "one of these two". The export says so at run
                # time instead, which is where it can see both.
                Option("source", "Send what this feed produced",
                       kind="choice",
                       choices=(("", "-- a directory instead --"),),
                       choices_from=_feed_choices,
                       help="An export moves what a feed made. The list is the "
                            "feeds that exist; there are none yet, so choose "
                            "the directory below instead."),
                also_option(),
                Option("directory_source", "Or a directory", kind="path",
                       placeholder="data/public_html",
                       help="Used when no feed is chosen. Everything under it "
                            "is sent, keeping the structure."),
                *live_push_options(),
                Option("delete", "Remove files that are no longer produced",
                       kind="bool", default=True,
                       help="On, so that a renamed chart does not leave its "
                            "old file on the host for good. Only files this "
                            "export put there are ever removed: it keeps a "
                            "record of what it sent, and the rest of the "
                            "directory is not its to touch. Turn it off for "
                            "a host that holds a site somebody else also "
                            "writes to."),
            )),
            Group("When it runs", "", (
                Option("trigger", "Send", kind="choice", default="feed",
                       choices=(("feed", "when the feed above has finished"),
                                ("record", "after every archive record"),
                                ("interval", "on its own schedule"),
                                ("manual", "only when asked")),
                       help="Coupled to the feed is the right answer when "
                            "there is one: the export starts after the feed "
                            "has written its files, rather than while it is "
                            "still writing them. After every record is for an "
                            "export pointed at a directory something else "
                            "fills. Its own schedule is for a slow destination "
                            "or a site nobody needs a minute fresh."),
                Option("every", "Its own schedule", kind="duration",
                       default=900, minimum=60, maximum=86400,
                       help="Only used with 'on its own schedule'. Below the "
                            "archive interval it would run with nothing new "
                            "to send."),
            )),
            Group("How", "", (
                Option("tls", "Encrypt the connection", kind="bool",
                       default=True,
                       help="FTPS: the same protocol with the password not in "
                            "clear text. Turn it off only if the host has no "
                            "TLS, and know that the password then crosses the "
                            "network as readable text."),
                Option("passive", "Passive mode", kind="bool", default=True,
                       advanced=True,
                       help="Almost always right. Active mode needs the server "
                            "to open a connection back to you, which no "
                            "domestic router allows."),
                Option("timeout", "Give up after", kind="duration",
                       default=TIMEOUT, minimum=5, maximum=600, advanced=True,
                       help="A dead host must not hold up the next interval."),
                Option("tracker", "Remember what was sent in", kind="path",
                       advanced=True,
                       help="Empty means beside the source directory. This is "
                            "what stops every file being sent every time; "
                            "losing it costs one full upload."),
            )),
        ]


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text)[:40] or "host"

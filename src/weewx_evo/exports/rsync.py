"""rsync, over SSH.

Where FTP has to be told what changed, rsync works it out itself and sends
only the differing parts of the differing files. For a weather site that is
the difference between an upload of megabytes and one of kilobytes, which is
why this is the export to use when the far end allows it.

It shells out to `rsync` rather than reimplementing the protocol, and that is
not laziness. The delta algorithm is the entire value, it is decades old and
correct, and every host already has the binary.

Three things this is careful about:

**Keys, not passwords.** rsync over SSH with a password needs a program to
type it, which means the password is in a process list or a file. A key has
neither problem and is what SSH is for. There is no password option here, and
`check()` says so plainly if the key is not working.

**`--delete` is off and stays off unless asked.** It does what it says on
somebody else's server, and on a mistyped destination it says it about the
wrong directory.

**The destination is passed as arguments, never through a shell.** A path with
a space in it is ordinary; a path with a semicolon in it should be harmless.
Nothing here is interpolated into a command line.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import BaseExport, ExportError, Sent

log = logging.getLogger(__name__)

TIMEOUT = 600


class RsyncExport(BaseExport):
    """Sends a directory to a server with rsync over SSH."""

    label = "rsync"
    #: One line for the form that offers the kinds. Somebody adding an
    #: export is choosing a destination, and "local" on its own is not a
    #: destination.
    summary = (
        "A machine reachable over SSH. rsync works out what changed "
        "itself, which makes it the cheapest destination over a slow "
        "line.")

    def __init__(self, host: str = "", user: str = "", directory: str = "",
                 source: str = "", port: int = 22, key: str = "",
                 delete: bool = False, compress: bool = True,
                 timeout: int = TIMEOUT, extra: str = "",
                 rsync: str = "rsync", directory_source: str = "",
                 trigger: str = "feed", every: int = 900) -> None:
        self.host = host.strip()
        self.user = user.strip()
        self.directory = directory.strip()
        # A feed name, or empty. The directory is where the files are
        # when no feed was chosen -- feeds do not exist yet.
        self.source = source
        self.directory_source = directory_source
        # When this runs. The runner reads it; the export itself
        # never decides when it happens.
        self.trigger = trigger
        self.every = int(every)
        self.port = int(port)
        self.key = key.strip()
        self.delete = bool(delete)
        self.compress = bool(compress)
        self.timeout = int(timeout)
        self.extra = extra.strip()
        self.rsync = rsync or "rsync"
        self.last: str = ""

    # -- the export interface --------------------------------------------

    def send(self, source: Path, files: list[Path] | None = None) -> Sent:
        source = Path(source)
        if not self.host or not self.directory:
            raise ExportError("a host and a directory are both needed")
        if not source.is_dir():
            raise ExportError(f"{source} is not a directory")
        if shutil.which(self.rsync) is None:
            raise ExportError(
                f"{self.rsync} is not installed. On Debian and Ubuntu: "
                "apt install rsync. Use the FTP export instead if the far end "
                "has no SSH.")

        started = time.monotonic()
        command = self._command(source, files)
        log.debug("running %s", " ".join(command))
        try:
            finished = subprocess.run(command, capture_output=True, text=True,
                                      timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ExportError(
                f"rsync did not finish within {self.timeout}s") from exc

        result = self._read(finished.stdout)
        result.seconds = time.monotonic() - started
        self.last = (finished.stderr or finished.stdout or "").strip()[-2000:]

        if finished.returncode != 0:
            # 24 is "a file vanished while we were sending it", which happens
            # whenever a feed rewrites its output during an upload. It is not
            # an error: the next run sends the new one.
            if finished.returncode == 24:
                result.note = "a file changed while it was being sent"
            else:
                raise ExportError(
                    f"rsync failed ({finished.returncode}): "
                    f"{_first_line(finished.stderr) or 'no message'}")
        return result

    def check(self) -> str:
        """Do a dry run and report what would happen."""
        if not self.host or not self.directory:
            return "A host and a directory are both needed."
        if shutil.which(self.rsync) is None:
            return f"{self.rsync} is not installed on this machine."
        where = self.directory_source or self.source
        source = Path(where) if where else None
        if source is None or not source.is_dir():
            return f"The source {where or '(unset)'} is not a directory."

        command = self._command(source, None, dry_run=True)
        try:
            finished = subprocess.run(command, capture_output=True, text=True,
                                      timeout=60, check=False)
        except subprocess.TimeoutExpired:
            return "No answer within a minute. Wrong host, or a firewall."

        if finished.returncode == 0:
            would = self._read(finished.stdout)
            return (f"Reached {self._target()}. {would.sent} file(s) would be "
                    f"sent, {would.skipped} are already there.")

        message = _first_line(finished.stderr)
        if "Permission denied" in message or "publickey" in message:
            return (f"Reached {self.host}, but the key was refused. rsync here "
                    "uses SSH keys and never a password: put the public key in "
                    f"{self.user or 'the user'}'s authorized_keys on the server.")
        if "Could not resolve" in message or "Name or service" in message:
            return f"{self.host} does not resolve."
        return f"rsync said: {message}"

    def status(self) -> dict[str, Any]:
        return {"target": self._target(), "deletes": self.delete,
                "last_message": self.last[-200:]}

    # -- building the command --------------------------------------------

    def _target(self) -> str:
        who = f"{self.user}@" if self.user else ""
        return f"{who}{self.host}:{self.directory}"

    def _command(self, source: Path, files: list[Path] | None,
                 dry_run: bool = False) -> list[str]:
        """The argument list. Nothing goes through a shell."""
        command = [self.rsync, "--archive", "--itemize-changes",
                   "--out-format=%i %n"]
        if self.compress:
            command.append("--compress")
        if self.delete:
            command.append("--delete")
        if dry_run:
            command.append("--dry-run")

        ssh = ["ssh", "-p", str(self.port),
               # Batch mode: never prompt. A prompt in a service is a service
               # that hangs until somebody notices weeks later.
               "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=15"]
        if self.key:
            ssh += ["-i", self.key, "-o", "IdentitiesOnly=yes"]
        command += ["-e", " ".join(ssh)]

        if self.extra:
            command += self.extra.split()

        if files:
            # Send a named subset by listing it on stdin's behalf: relative
            # names under one source, which is exactly what a feed reports.
            for relative in files:
                command += ["--include", _pattern(relative)]
            command += ["--include", "*/", "--exclude", "*"]

        # The trailing slash is the difference between copying the directory
        # and copying its contents. Getting it wrong nests the site inside
        # itself, once, and then everybody remembers.
        command.append(f"{source}/")
        command.append(self._target())
        return command

    def _read(self, output: str) -> Sent:
        """Count what rsync said it did.

        `--itemize-changes` prefixes every line with a code. A leading `>`
        means it was transferred, `*deleting` means it was removed, and
        anything else is a directory or an unchanged file.
        """
        result = Sent()
        for line in output.splitlines():
            if not line.strip():
                continue
            if line.startswith("*deleting"):
                result.deleted += 1
            elif line.startswith(">"):
                result.sent += 1
            elif line[:1] in ("c", "."):
                result.skipped += 1
        return result

    # -- what the admin page asks for ------------------------------------

    @staticmethod
    def options() -> list:
        from ..options import Group, Option
        from . import _feed_choices

        return [
            Group("Where it goes", "", (
                Option("host", "Server", required=True,
                       placeholder="example.org"),
                Option("user", "User", required=True,
                       help="The account on the server."),
                Option("directory", "Directory", required=True,
                       placeholder="/var/www/weather",
                       help="Where the files go. Its contents are replaced by "
                            "the source directory's contents."),
                Option("port", "SSH port", kind="int", default=22,
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
                Option("directory_source", "Or a directory", kind="path",
                       placeholder="data/public_html",
                       help="Used when no feed is chosen. Everything under it "
                            "is sent, keeping the structure."),
                Option("delete", "Remove files that are no longer produced",
                       kind="bool", default=False,
                       help="rsync --delete. It does exactly what it says, on "
                            "somebody else's server, in whatever directory is "
                            "configured -- including a mistyped one. Off "
                            "unless you mean it."),
                Option("compress", "Compress in transit", kind="bool",
                       default=True,
                       help="Worth it for text, which a weather site mostly "
                            "is. Turn it off only on a fast local network."),
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
            Group("Getting in", "rsync here uses SSH keys, never passwords.", (
                Option("key", "Private key", kind="path",
                       placeholder="~/.ssh/id_ed25519",
                       help="Empty uses whatever SSH would use by itself. "
                            "There is no password option: a password would "
                            "have to be typed by a program, which puts it in "
                            "a process list or a file. Put the public key in "
                            "the server's authorized_keys instead."),
                Option("extra", "Extra rsync arguments", advanced=True,
                       placeholder="--chmod=D755,F644",
                       help="Passed through as they are. Split on spaces, so "
                            "nothing with a space in it."),
                Option("timeout", "Give up after", kind="duration",
                       default=TIMEOUT, minimum=30, maximum=7200,
                       advanced=True),
            )),
        ]


def _pattern(relative: Path) -> str:
    return "/" + relative.as_posix()


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""

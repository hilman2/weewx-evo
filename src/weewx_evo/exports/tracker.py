"""What has already been sent, so it is not sent again.

rsync works this out for itself. FTP cannot: the protocol has no reliable way
to ask what a file looks like at the other end. `MDTM` is optional, `SIZE` is
optional in ASCII mode, and shared hosting frequently answers both with
something invented. So the only dependable record is the one kept here.

That record is why an FTP export is usable at all. A weather site is a few
hundred files and almost all of them are identical from one run to the next --
the fonts, the stylesheet, the icons, the pages for months that have ended.
Sending everything every five minutes is how an upload takes longer than the
interval between uploads, and then two of them run at once.

Kept as one JSON file beside the source, not in the archive database. It is a
cache: losing it costs one full upload and nothing else, and that is a much
better failure than a database write on the path of every file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Files this size or smaller are compared by content rather than by
#: timestamp. Templated pages get rewritten every run with identical bytes,
#: and their timestamp changes every time; hashing a few kilobytes is far
#: cheaper than uploading them. Bigger files -- images, archives -- are
#: compared by size and time, because hashing them would cost more than the
#: occasional needless upload.
HASH_UNDER = 256 * 1024


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Enough to tell whether a file is the one already sent."""

    size: int
    mtime: int
    digest: str = ""

    def as_list(self) -> list:
        return [self.size, self.mtime, self.digest]

    @classmethod
    def of(cls, path: Path) -> Fingerprint:
        stat = path.stat()
        digest = ""
        if stat.st_size <= HASH_UNDER:
            hasher = hashlib.sha256()
            with open(path, "rb") as fp:
                for chunk in iter(lambda: fp.read(65536), b""):
                    hasher.update(chunk)
            digest = hasher.hexdigest()[:16]
        return cls(size=stat.st_size, mtime=int(stat.st_mtime), digest=digest)

    def same_as(self, other: Fingerprint) -> bool:
        """Whether these are the same file.

        With a digest, that decides on its own: a rewritten template with
        identical bytes is the same file even though its timestamp moved.
        Without one, size and time have to agree, which is the usual
        compromise and errs towards sending again.
        """
        if self.digest and other.digest:
            return self.digest == other.digest and self.size == other.size
        return self.size == other.size and self.mtime == other.mtime


class Tracker:
    """What one export has sent where."""

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._known: dict[str, Fingerprint] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for name, entry in raw.get("files", {}).items():
            try:
                size, mtime, digest = entry
                self._known[name] = Fingerprint(int(size), int(mtime), str(digest))
            except (TypeError, ValueError):
                continue

    def save(self) -> None:
        """Write the record out. Losing it costs one full upload."""
        with self._lock:
            payload = {"files": {name: fp.as_list()
                                 for name, fp in self._known.items()}}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            partial = self.path.with_suffix(".part")
            partial.write_text(json.dumps(payload, separators=(",", ":")),
                               encoding="utf-8")
            partial.replace(self.path)
        except OSError:
            log.warning("could not save %s; the next run will send everything "
                        "again", self.path)

    def changed(self, source: Path, files: list[Path]) -> tuple[list[Path], int]:
        """Which of these need sending, and how many did not.

        A file that cannot be read is treated as changed rather than skipped:
        it is better to try and fail loudly than to decide silently that a
        file nobody can stat is up to date.
        """
        needed, skipped = [], 0
        for relative in files:
            full = source / relative
            key = relative.as_posix()
            try:
                now = Fingerprint.of(full)
            except OSError:
                needed.append(relative)
                continue
            before = self._known.get(key)
            if before is not None and now.same_as(before):
                skipped += 1
                continue
            needed.append(relative)
        return needed, skipped

    def record(self, source: Path, relative: Path) -> None:
        """Note that this file has been sent, as it is now."""
        try:
            fingerprint = Fingerprint.of(source / relative)
        except OSError:
            return
        with self._lock:
            self._known[relative.as_posix()] = fingerprint

    def forget(self, relative: Path) -> None:
        with self._lock:
            self._known.pop(relative.as_posix(), None)

    def gone(self, present: list[Path]) -> list[str]:
        """What we have sent before and is no longer here.

        An export that removes files at the far end uses this. One that does
        not, ignores it -- deleting from somebody's web host is not a thing to
        do by default.
        """
        here = {p.as_posix() for p in present}
        with self._lock:
            return sorted(set(self._known) - here)

    def reset(self) -> None:
        """Forget everything, so the next run sends the lot."""
        with self._lock:
            self._known.clear()

    def __len__(self) -> int:
        return len(self._known)

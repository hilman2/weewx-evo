# Exports

`exports/`. How what a feed produced gets somewhere else.

A [feed](Feeds) writes files into a directory. An export takes that directory
and brings it where people can see it — a web host over FTP, a server over
rsync, a directory on this machine.

**The directory is the entire interface**: an export does not know what produced
the files, and a feed does not know where they go.

There are three: [`local`](#a-directory-on-this-machine), [`ftp`](#ftp-and-ftps)
and [`rsync`](#rsync-over-ssh).

## The interface

```python
class Export(Protocol):
    def send(self, source: Path, files: list[Path] | None = None) -> Sent:
        ...
```

`files` is what changed, when the caller knows. `None` means: work it out from
the directory.

**Raising means nothing was sent.**

### `BaseExport`

Only `send` has to be written.

| Method | What it means |
|---|---|
| `send(source, files)` | |
| `check()` | Try the destination and say what happened, without sending |
| `status()` | |
| `close()` | Optional |
| `options()` | The settings |

`check()` is the button on the admin page. Getting a wrong password or a wrong
path back straight away is worth a great deal — the alternative is waiting five
minutes for the next interval and then looking at a log.

### `Sent`

```python
@dataclass
class Sent:
    sent: int
    skipped: int
    deleted: int
    bytes: int
    seconds: float
    failures: list[tuple[str, str]]
    note: str
```

`ok()` and `summary()` for the status page and the log.

`ExportError` is something that stopped an export **before it sent anything**.

## The registry

The same shape as the driver registry, for the same reason: an export holds
configuration and a little state — what it has already sent — and that has to
survive between runs.

| Method | What it means |
|---|---|
| `register(name, export, replace=False)` | |
| `register_factory(name, factory)` | |
| `configure(name, options)` | |
| `factory_for(kind)` | The class behind a kind, loading the registry first |
| `get`, `known`, `names` | |
| `kinds()` | Which kinds there are, as opposed to which are configured |
| `load()` | Fetch what is installed. A broken one is reported, never fatal |

`factory_for()` is a method rather than a reach into `_factories`, because the
reach skips `load()` — and then nothing is registered yet, which looks like
"there is no such kind".

`ENTRY_POINT_GROUP = "weewx_evo.exports"`.

### `walk(source, files=None)`

Every file worth considering, as paths relative to `source`. Directories that
must **never** be uploaded are skipped here rather than in every export: a
`.git` inside a published site is a mistake everyone makes once, and one is
enough.

### `source_for(settings, feed_directory=None)`

Where an export's files are — from a feed name or a plain directory. A feed is
asked where it wrote; a directory is taken as it is.

## When an export runs

`exports/runner.py`. Four triggers:

| | |
|---|---|
| `feed` | when **its** feed has finished writing — the default, and the right one |
| `record` | after every archive record, for a directory something else fills |
| `interval` | its own rhythm (`every`), for a slow destination |
| `manual` | only on `weewx-evo export run` |

**`feed` is not convenience, it is order.** If feed and export both listen for
`record`, the export can start while the feed is still writing — half a page
uploaded, looks like a broken template, not reproducible.

An export with `feed` waits for **that particular** feed: two feeds writing two
sites must not each trigger both uploads.

### `Scheduled`

An export and when it is due.

| | |
|---|---|
| `trigger`, `every` | From the export |
| `feed` | Which one it waits for |
| `changed` | What the feed said it wrote. An export that gets this sends those files rather than walking the directory — faster, and the only way to be sure that a file just written is included |
| `due(now, fired)` | `fired` is what just happened: `"record"`, a feed name, or `""` |
| `run()` | Send and note what happened. **Never raises** |

### `Runner`

**Every export runs in a thread of its own.** Not for speed — there are two or
three of them and they are idle almost all the time — but so that an FTP host
that has stopped answering does not hold the archiver up for 30 seconds.

That also stops an export from overlapping itself: the thread is stuck in
`send()` and is not reading its own trigger. Whatever fires meanwhile is
remembered and run **once** afterwards (`skipped` counts along).

| Method | What it means |
|---|---|
| `record_written()` | From the archiver's thread, returns immediately: sets flags |
| `feed_produced(feed, files)` | A feed has finished. Wakes whatever sends it |
| `start()`, `stop()`, `status()` | |

`build(configured, make, source_of)` turns configuration into something the
runner can drive. **What cannot be built is reported and left out.** A
misconfigured export must not stop the others, and certainly not the station:
the readings are the point.

## Only send what has changed

This is the point at which an export becomes useful rather than a nuisance.

rsync can do it itself. **FTP cannot**: the protocol has no reliable way to ask
what a file looks like at the far end. `MDTM` is optional, `SIZE` is optional in
ASCII mode, and shared hosting regularly answers both with something made up.

Hence `exports/tracker.py`.

### `Fingerprint`

```python
@dataclass
class Fingerprint:
    size: int
    mtime: int
    digest: str
```

`HASH_UNDER = 256 * 1024` — small files are compared by their **content**, not
by their timestamp.

The case: a template rewrites `index.html` every run with identical bytes.
Compared by timestamp, the whole site would go up every five minutes.

`same_as(other)`: with a digest, the digest alone decides. Without one — for
large files — size and timestamp decide.

### `Tracker`

| Method | What it means |
|---|---|
| `changed(source, files)` | Which have to be sent, and how many do not |
| `record(source, relative)` | Note that this file was sent, as it is now |
| `forget(relative)` | |
| `gone(present)` | What we sent and is no longer there |
| `reset()` | Forget everything; the next run sends everything |
| `save()` | Write the record. Losing it costs **one** full upload |

**A file that cannot be read counts as changed**, not as skipped: better to try
and fail loudly than to decide silently that something is not going up.

`gone()` is used by an export that removes files at the destination. One that
does not, ignores it — **deleting from somebody's web host is not something you
start doing unasked.**

## A directory on this machine

`exports/local.py`. The third destination alongside FTP and rsync, and the one
most stations actually want: puts down what a feed produced, and the built-in
[web server](Web-Server) hands it to a browser.

### Why this is an export and not a setting on the web server

It **was** one: "serve this directory". An export is better for one reason: it
means there is **one place** where somebody asks "where does this end up". A
feed writes into its own working directory and knows nothing about publishing.
One export sends it to a web host, a second puts it under the local site, a
third copies it onto a mounted share. Three destinations, one idea, one page in
the settings.

### Why it copies rather than points

The web server could serve the feed's directory itself and save the copy. It
does not, for the same reason the FTP export exists: **a feed rewrites its
directory while it runs**, and a browser loading in the middle of that gets half
a page. What lands here is a whole set of files, or the previous one.

The copy is cheap. Only what changed moves, judged exactly as with FTP — and on
the same filesystem a **hard link** is used rather than a copy, so a hundred
published JSON files cost a hundred directory entries and no second copy of
anything. Where the filesystem will not link, it falls back to copying on its
own.

| Method | What it means |
|---|---|
| `send(source, files)` | |
| `_place(source, destination)` | **One file, atomically.** Written alongside and moved into place, so that a browser reading it right now gets one version or the other and never half of each |
| `_remove(target, tracker, present)` | Delete what this export put there and the feed no longer writes |
| `check()` | Whether it can be written to, and what is there now |

Two things `send()` refuses:

- **No directory set** → `ExportError`.
- **The destination is the source directory.** Publishing a directory into
  itself compared every file with itself and would then hard-link it over
  itself. Nothing good happens after that.

A file that cannot be written does **not cost the run**: it is noted as a
failure and the rest is published. One page that cannot be written must not cost
the publishing of everything after it.

## FTP and FTPS

`exports/ftp.py`. Shared hosting still gives you FTP and often nothing else, so
this exists and has to work at the unpleasant end: servers that lose the
connection mid-transfer, that cannot create a directory that already exists
without erroring, that answer `MDTM` with nonsense, and that treat a passive
connection from a different address as an attack.

| Method | What it means |
|---|---|
| `send(source, files)` | |
| `check()` | Connect, look into the target directory, report |
| `_ensure(connection, remote)` | Create a directory and its parents |
| `_remove(connection, tracker, present)` | Delete what we sent and is no longer produced |
| `_put(connection, source, relative)` | |

`_ensure()`: **`MKD` on an existing directory is an error on most servers and a
success on some** — so the error is what has to be tolerated, not the success.

`_remove()` deletes **only files this export put there**: the record says which
those are, so nothing else on the account is at risk.

`TIMEOUT = 30`.

## rsync over SSH

`exports/rsync.py`. Where FTP has to be told what changed, rsync works it out
itself and sends only the differing **parts** of the differing files. For a
weather site that is the difference between an upload of megabytes and one of
kilobytes.

It calls `rsync` rather than reimplementing the protocol — and that is not
laziness: the delta algorithm is the entire value, and reimplementing it would
mean reimplementing it worse.

| Method | What it means |
|---|---|
| `send(source, files)` | |
| `check()` | A dry run, and what it would do |
| `_command(source, files, dry_run)` | The argument list. **Nothing goes through a shell** |
| `_read(output)` | Count what rsync says it did |

`_read()` reads `--itemize-changes`: a leading `>` means transferred, `*deleting`
means removed, everything else is something else.

**There is no password option.** A password would have to be typed by a program,
which puts it into a process list or a file. Public key in `authorized_keys`.

`TIMEOUT = 600`.

## Configuration

```toml
[exports.site]
kind = "local"
directory = "data/site"
source = "json"
trigger = "feed"
link = true

[exports.webhost]
kind = "ftp"
host = "ftp.example.org"
user = "…"
password = "…"
directory = "/httpdocs"
directory_source = "data/public_html"
trigger = "feed"
source = "json"
tls = true
delete = false
```

→ [Settings-Reference](Settings-Reference#exports)

On the admin page: **creating an export asks only for a name and a kind.**
Everything else is filled in on the page that appears next. Asking for a host
and a password before it is clear what is being talked about is a form somebody
fills in without knowing what they are filling in.
→ [Admin-Page](Admin-Page)

## Commands

```bash
weewx-evo export list
weewx-evo export check [name]
weewx-evo export run [name] [--source DIR] [--all]
```

## Checking it

```bash
python tools/export_test.py
```

The FTP half runs against a server **in this process**, so the transfer is
really checked rather than mocked: files land on disk, directories come into
existence, the move-into-place happens. `pyftpdlib` is not a dependency of
weewx-evo, so that part is skipped when it is missing and the rest runs anyway.

`local_export()` checks the failure modes FTP does not have: a hard link
silently sharing an inode; a delete taking more with it than what this export
put there; a destination that is the source directory. And after that, that the
**web server really serves what the export published** — both halves of the
chain in one test.

`runner_tests()` checks when each export runs and **that one cannot hold another
up** — with a `FakeExport` that deliberately takes its time.

→ [Testing](Testing)

<!-- covers
src/weewx_evo/exports/__init__.py
src/weewx_evo/exports/ftp.py
src/weewx_evo/exports/rsync.py
src/weewx_evo/exports/local.py
src/weewx_evo/exports/runner.py
src/weewx_evo/exports/tracker.py
tools/export_test.py
-->

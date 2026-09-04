# Architecture

## The flow of data

```
   Hardware / other senders
        │  HTTP POST · HTTP GET (Wunderground) · UDP
        ▼
┌───────────────────────────────────────────────────────┐
│ Listener            ingest/listener.py                │
│  Socket, threads, body limit, token, network          │
│  boundary, rate limit — the core.                     │
│         │ body: bytes, meta: dict                     │
│         ▼                                             │
│  Driver             ingest/drivers.py, plugins/       │
│  Parsing, field names, units, the reply to the device │
└─────────┬─────────────────────────────────────────────┘
          │ list[Packet]
          ▼
   ┌──────────────┐   db/live.py
   │ live.sdb     │   append-only, idempotent, retention N days
   │  packet      │   driver + identity + dialect, raw field names
   └──────┬───────┘
          │  packets(start, stop)
          ▼
┌───────────────────────────────────────────────────────┐
│ Archiver            archiver.py, one per place        │
│  1. select canonical senders from archives.toml       │
│  2. placement.py: raw names to archive columns        │
│  3. apply this Place's member roles                    │
│  4. aggregate.py and derive.py                        │
│  5. write the record, then sharpen the day's extremes │
└─────────┬─────────────────────────────────────────────┘
          │ dict (one archive record)
          ▼
   ┌──────────────┐   db/archive.py
   │ place.sdb    │   archive        ← WeeWX-compatible, PK dateTime
   │ per place    │   archive_day_*  ← cache, derivable from archive
   └──────┬───────┘
          │  series.Reader
          ▼
   ┌──────────────┐   feeds/ + feedrunner.py
   │ Feeds        │   jsongenerator → JSON series
   │              │   diagnostic    → HTML diagnostic page
   └──────┬───────┘
          │  a directory
          ├───────────────► webserver.py (serve locally)
          ▼
   ┌──────────────┐   exports/
   │ Exports      │   ftp.py · rsync.py, each its own thread
   └──────────────┘
```

## The core rule of coupling

The components talk **only through the database**, never to each other. There
is no channel between listener and archiver, deliberately.

What that buys:

- **One process or three**, with no code change. `weewx-evo serve` starts both;
  `listen` and `archive` start one each. That is the difference between
  `deploy/compose.yml` and `deploy/split.yml` — and nothing else.
- **A restart mid-interval costs nothing.** There is no in-memory accumulator
  to lose it: the packets are already in the live table.
- **A late push packet lands in the right interval.** It is placed by its own
  timestamp, not by when it arrived.
- **Correctable after the fact.** As long as the raw data is still within
  retention, a wrong calibration can be taken back out with `weewx-evo rebuild`.
- **A driver cannot write to the archive** if the listener never mounted the
  file at all. → [Security](Security), [Deployment](Deployment)

Every stage is reproducible from the one before it. There is no transient state
that a number derives from.

Senders never route packets to an archive. The Listener stores each packet
under the canonical ID derived from driver and hardware identity. Every entry
in `archives.toml`, including the first, owns its database, location and sender
selection. The same sender may therefore feed several Places from the same
packets. `stations.toml` supplies display metadata and clock tolerances only.

## Core and driver

**The core owns the socket.** Threads, shutdown, body limits, token checks,
network boundary, rate limit, writing to the live table. That is the same for
every protocol, and it is where push drivers go wrong.

**The driver owns everything protocol-specific.** Parsing, field catalogs,
units, which device it answers, and **what the device has to hear back**. It
hands the listener raw readings and an inert, versioned `DialectSpec`.

```python
class MyDriver:
    response = (b'{"ok":true}', "application/json")   # what the device wants to hear

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        ...

    def dialect_spec(self, readings: dict, dialect: str) -> DialectSpec:
        ...
```

The listener validates and stores that description. The archiver interprets
it with core code and therefore loads no driver at all. The core knows no
weather protocol: if you want to write something about Ecowitt into
`listener.py`, `placement.py` or `archiver.py`, it belongs in the driver's
serialized catalog.
→ [Drivers](Drivers)

## Feeds and exports

Two different things, and WeeWX does not separate them:

- **Feed** = *what* gets produced. A CSV, a JSON document, a plot, a whole
  website, a monthly report. Writes into a directory.
- **Export** = *how* it gets somewhere else. FTP, rsync, a copy onto a mounted
  share.

The directory is the entire interface between them — exactly like the live
table between listener and archiver. One feed, three exports. Or three feeds
into one directory and one export. Neither knows about the other.

With WeeWX you configure the FTP upload *inside* the skin section. Two
destinations mean running the renderer twice.

→ [Feeds](Feeds), [Exports](Exports)

## Threads

Three places run concurrently, each for a named reason:

| Thread | Where | Why |
|---|---|---|
| HTTP handler | `listener.HttpListener` (`ThreadingHTTPServer`) | One slow console must not block the others |
| Feed runner | `feedrunner.Runner`, **one** thread for all feeds | 100 plots are the best part of a second, and a second there is a second the archiver is not archiving. One thread, because feeds are ordered |
| Export runner | `exports/runner.Runner`, **one thread per export** | An FTP host that has stopped answering sits 30 s in `connect` — and must hold up neither the archiver nor the other export while it does |

That also stops an export from overlapping itself: the thread is stuck in
`send()` and is not reading its own trigger. Whatever fires meanwhile is
remembered and run **once** afterwards.

SQLite connections are thread-bound. `LiveStore.conn()` therefore opens its own
connection per thread on first use — that was a real bug and is now part of the
design.

## Process models

### One process (the normal case)

```bash
weewx-evo serve
```

Listener, archiver, optionally the admin page, web server, feeds and exports in
one process. The right thing for a Pi Zero in a shed.

### Split (when a driver should not reach the archive)

```bash
weewx-evo listen     # holds the drivers, mounts only live.sdb
weewx-evo archive    # holds no drivers, mounts both files
```

The listener never opens the archive. A driver inside it does not *have* the
file. That is the only enforceable cage — in the same process `import sqlite3`
is enough. → `deploy/split.yml`, [Security](Security)

Two pitfalls, both recorded in the comments of `split.yml`:

- **Retention belongs to the archiver**, not to the listener. Packets may only
  be dropped once they are in a record, and only that side knows.
- **SQLite in WAL mode writes `-shm` and `-wal` next to the file — for reading
  too.** A read-only mounted *directory* is therefore not the same as a
  read-only file, and it fails. The route that works is a user without write
  permission on the archive.

## Why no settings service

The question keeps coming back, so here is the reasoning. The file **already
is** what a daemon would be, without the daemon's failure modes — written
atomically, survives restarts in the right order, readable with `cat`, cannot
be down. Listener and archiver coordinate deliberately **only** through the
database; a channel between them would undo the fact that you can split them or
put them together. What a service would really buy — changes without a restart
— `Settings.reload()` already does.

→ [Configuration](Configuration)

## Package layout

```
src/weewx_evo/
  __init__.py          The one rule, as a docstring
  cli.py               Every command, the only program
  settings.py          The precedence: argument > environment > file > weewx.conf > default
  options.py           Option / Group / Schema — the declaration model
  config.py            Read TOML and write it back with comments
  weewxconf.py         Read weewx.conf (never write it)

  aggregate.py         Transcription of weewx.accum
  obstypes.py          Which observation aggregates how
  archiver.py          Replaces StdArchive
  derive.py            Replaces StdWXCalculate
  sources.py           Optional low-level field arbitration API
  series.py            Replaces xtypes.get_series
  units.py             Transcription of weewx.units
  sun.py               Solar position, rise and set
  plots.py             Plot definitions and plots.toml

  db/
    schema.py          Read the schema from the file
    wview.py           The starting schema for a new file
    archive.py         The WeeWX database
    daily.py           Build archive_day_*
    live.py            The live table

  ingest/
    listener.py        HTTP + UDP
    drivers.py         Driver interface and registry
    envelope.py        The JSON envelope — the only driver in the core
    parsers.py         The older, function-based registry
    state.py           What a driver is allowed to remember
    statuspage.py      The live page behind the token
    userdrivers.py     Installing third-party drivers
    plugins/           Our drivers, one folder per driver
      ecowitt/

  feeds/
    __init__.py        The feed interface
    jsongenerator/     The series everything else stands on
    diagnostic/        Draws what is actually on disk
  feedrunner.py        Runs the feeds in order, own thread

  exports/
    __init__.py        Export interface and registry
    ftp.py  rsync.py   The two that are built
    runner.py          When each one runs
    tracker.py         What has already been sent

  admin.py             The settings page
  adminplots.py        The plot pages within it (hand-written)
  webserver.py         Serving the feeds
  netaccess.py         Who gets an answer
  ratelimit.py         Two limits: requests and failed attempts
```

<!-- covers
src/weewx_evo/__init__.py
deploy/split.yml
-->

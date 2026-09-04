# CLI reference

One program, `weewx-evo`, defined in `cli.py`. Three services and a few
operations on the databases. Every service runs on its own, or all of them in
one process, because they talk through the database and never to each other.

```
weewx-evo [--log-level LEVEL] <command> …
```

`--log-level` is global, default `INFO`, also via `WEEWX_EVO_LOG_LEVEL`.

## Common arguments

`add_common()` attaches these to almost every command:

| Argument | What it means |
|---|---|
| `--config PATH` | The TOML configuration. Also `WEEWX_EVO_CONFIG` |
| `--live PATH` | The live packet database |
| `--interval SPEC` | Archive interval, e.g. `5m` |
| `--table NAME` | The archive table |
| `--sources PATH` | Obsolete and ignored; accepted only to report the retired configuration. Also `WEEWX_EVO_SOURCES` |
| `--quality PATH` | Calibration and sensor limits; defaults beside the configuration |
| `--weewx-conf PATH` | A `weewx.conf` to fall back to. Also `WEEWX_EVO_WEEWX_CONF` |
| `--driver-dir PATH` | Where third-party drivers live |

**None of them has an argparse default.** That is not carelessness: argparse
cannot tell "not given" from "set to the default", and a default here would beat
the configuration file. The defaults live in the schema.
→ [Configuration](Configuration)

Archive paths and place settings are not common arguments. They come from
`archives.toml`, including for the first archive. Commands that operate on one
archive take `--series NAME` and refuse an ambiguous choice.

## Services

### `serve`

Listener and archiver in one process. For a small machine. They still talk only
through the database; splitting them later is a change to the unit files, not to
the code.

```bash
weewx-evo serve --config evo.toml
weewx-evo serve --config evo.toml --explain
```

In addition to `add_common`, `add_listen_args` and `add_archive_args`:

| Argument | What it means |
|---|---|
| `--explain` | Print every setting and where it came from, then stop |

`serve` also starts whatever is configured: the admin page (when `admin.token`
is set), the web server (when `web.enabled`), the feed runner and the export
runner.

### `listen`

The listener only. Never opens the archive — that is the point.

```bash
weewx-evo listen --config evo.toml
```

`add_listen_args()`:

| Argument | What it means |
|---|---|
| `--host` | Bind address |
| `--port` | HTTP port |
| `--udp-port` | `0` turns the UDP listener off |
| `--token` | The path segment. Without it anybody can write |
| `--driver` | Driver for uploads whose path names none |
| `--rate` | Requests per second per address. A console sends 0.5 at the fastest. `0` turns it off |
| `--behind-proxy` | Leave the rate limit to the proxy |
| `--allow` | Who gets an answer: `private` (default), `any`, or a list |

### `archive`

The archiver only. Holds no drivers, listens to nothing.

```bash
weewx-evo archive --config evo.toml --spool /data/packets
```

`add_archive_args()`:

| Argument | What it means |
|---|---|
| `--series NAME` | Run this archiver for the named entry in `archives.toml`; required when the file contains more than one |
| `--grace` | How long to wait after the end of an interval |
| `--poll` | How often to look, in seconds |
| `--retention-days` | How long packets stay, in days |
| `--spool PATH` | Write packets out as gzip NDJSON before discarding them |
| `--raw-minutes` | How long the raw uploads stay. `0` keeps none |

### `web`

Serving the feeds only. Separate from `serve` for the same reason as `listen`: a
machine that only shows pages need not be the one that records them.

```bash
weewx-evo web --config evo.toml --port 8081
```

| Argument | What it means |
|---|---|
| `--host`, `--port` | |
| `--allow` | Who gets an answer (default `private`) |

→ [Web-Server](Web-Server)

### `admin`

The settings page. Its own port and its own token, deliberately: an upload
endpoint can at worst write a wrong reading, this one can change a Place's
database and sender policy.

```bash
weewx-evo admin --config evo.toml
```

| Argument | What it means |
|---|---|
| `--config PATH` | The file this page edits |
| `--host`, `--port` | Default `0.0.0.0:8080` |
| `--allow` | `private` (default), `any`, or a list |
| `--token` | Its own token, never the upload token |
| `--rate` | Requests per second per address (default 5) |
| `--behind-proxy` | Leave the rate limit to the proxy |
| `--read-only` | Show the settings, refuse to save |

→ [Admin-Page](Admin-Page)

## On the databases

### `catchup`

Build every interval the live table covers. After an outage, or on the first
start against a filled live file.

```bash
weewx-evo catchup --config evo.toml
weewx-evo catchup --config evo.toml --replace
```

| Argument | What it means |
|---|---|
| `--series NAME` | The entry in `archives.toml`; required when more than one exists |
| `--replace` | Overwrite records that are already there |

### `rebuild`

Recompute a timespan and replace it. Afterwards the daily summaries of every
affected day are rebuilt from the archive table and then sharpened from the
packets again.

```bash
weewx-evo rebuild 1755000000 1755086400
```

| Argument | What it means |
|---|---|
| `start` | Unix timestamp, exclusive |
| `stop` | Unix timestamp, inclusive |
| `--series NAME` | The entry in `archives.toml`; required when more than one exists |

→ [Archiver](Archiver)

### `columns`

Readings the archive has no column for.

```bash
weewx-evo columns --config evo.toml
weewx-evo columns --config evo.toml --add
```

| Argument | What it means |
|---|---|
| `--series NAME` | The entry in `archives.toml`; required when more than one exists |
| `--add` | Create the missing columns. **Back the database up first** |

The default schema has 113 columns; push hardware can send more. The Place's
**Fields** tab shows every raw name and its archive column.

### `placement list`

What each sender sends, and which Place column it reaches.

```bash
weewx-evo placement list --config evo.toml
```

Reads `placement.toml` and the names noted as unplaced. Asks no hardware and
writes nothing. → [Placements](Placements)

### `placement accept`

Write down what inference has worked out about names no catalog knows.

```bash
weewx-evo placement accept --config evo.toml
weewx-evo placement accept --config evo.toml --write
```

| Argument | What it means |
|---|---|
| `--series NAME` | Write the decisions for one measurement series. Default: all |
| `--mode MODE` | `off`, `series` or `all`. Default: the configured `infer_unknown` |
| `--write` | Write `placement.toml`. Without it nothing is saved |

The lines are written with `learned = true` and never overwrite a decision of
yours. They take effect on the next record; `rebuild` applies them to what is
still in the live table.

### `status`

What is in the two databases.

```bash
weewx-evo status --config evo.toml
```

### `url`

The addresses of the live view and the upload endpoint, with the token.

```bash
weewx-evo url --config evo.toml
weewx-evo url --config evo.toml --qr
```

| Argument | What it means |
|---|---|
| `--config PATH` | |
| `--token`, `--port` | Override what is in the configuration |
| `--driver NAME` | Which driver the upload address should name |
| `--public URL` | The outside address, e.g. behind a reverse proxy. Also `WEEWX_EVO_PUBLIC_URL` |
| `--qr` | A QR code in the terminal as well |

The token is a path segment, so an address without it is useless and one with it
is the whole key. That is exactly why this command exists: the two always go
together.

The QR code is hand-rolled rather than a dependency — it is a convenience in one
command, and a weather station that runs for years should not gain a package for
it.

## `config`

```bash
weewx-evo config show   [--config PATH] [--defaults]
weewx-evo config set    [--config PATH] <name> <value>
weewx-evo config check  [--config PATH]
weewx-evo config import <weewx.conf> [--config PATH] [--write] [--overwrite]
```

| | |
|---|---|
| `show` | The configuration as it is, with comments. `--defaults` fills in every default, to see what there is |
| `set` | Set a value, checked against the schema that owns it |
| `check` | Check every value against its schema and say what is wrong |
| `import` | Read a `weewx.conf` and take it over. Without `--write` it only reports. `--overwrite` replaces what is already set here too |

→ [Configuration](Configuration), [WeeWX-Compatibility](WeeWX-Compatibility)

## `driver`

```bash
weewx-evo driver list
weewx-evo driver install <source> [--name NAME] [--force]
weewx-evo driver remove <name>
```

The source is a git URL, a zip URL, a `.zip` file or a directory. Installing
**runs nothing and imports nothing** — a driver is code that will later run as
the service, and the decision to install it comes before the first run.

`install` reads the code and reports what it reaches for: `sqlite3`,
`subprocess`, `socket`. A hint, not a guarantee.

These subcommands take `--driver-dir`, but no `--config`. A bare
`weewx-evo driver list` therefore carries on working.

→ [Drivers](Drivers)

## `plots`

```bash
weewx-evo plots list   [--plots PATH]
weewx-evo plots show   <name> [--plots PATH]
weewx-evo plots import <skin.conf> [--write] [--replace] [--plots PATH]
weewx-evo plots remove <name> [--plots PATH]
weewx-evo plots run    [--into DIR] [--no-page] [--plots PATH]
```

| | |
|---|---|
| `list` | Which plots there are |
| `show` | One of them in full |
| `import` | Fetch the plots out of a WeeWX skin. Read, reported, and only kept on `--write`. `--replace` starts from nothing rather than adding |
| `remove` | Delete one |
| `run` | Produce the JSON now and say what came out. `--no-page` leaves the diagnostic page out |

An import silently replacing a painstakingly tuned set of plots would be worse
than no import at all.

→ [Plots](Plots)

## `export`

```bash
weewx-evo export list  [--config PATH]
weewx-evo export check [name] [--config PATH]
weewx-evo export run   [name] [--source DIR] [--all]
```

| | |
|---|---|
| `list` | What is available and what is configured |
| `check` | Try the destination without sending anything. Getting a wrong password or a wrong path back straight away is worth a lot |
| `run` | Send. `--all` sends everything, not only what changed. `--source` overrides the source directory |

→ [Exports](Exports)

## Exit codes

`0` on success. An error is reported as a line on stdout and returns a non-zero
value — commands that check something (`config check`, `export check`) return
non-zero when something is wrong, so that they are usable in a script.

<!-- covers
src/weewx_evo/cli.py
src/weewx_evo/dumps.py
src/weewx_evo/dumpscsv.py
-->

<!-- watches
src/weewx_evo/cli.py
-->

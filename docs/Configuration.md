# Configuration

First things first: **nothing reads the configuration file for itself.** There
is one `Settings` instance per process, and everything asks it.

The reason is concrete: if every component resolves for itself, a file rewritten
between two resolutions can give a running system two different configurations.
`cli.settings_for()` therefore resolves **once** and remembers the result.

## The precedence

Five places, one fixed order, strongest first:

| | Where | What for |
|---|---|---|
| 1 | Command-line argument | Somebody just typed it, for this run |
| 2 | Environment variable | How a container is configured |
| 3 | Configuration file (TOML) | What the admin page writes, what a person edits |
| 4 | `weewx.conf` | Process settings both systems share, such as the archive interval |
| 5 | Default from the schema | |

Implemented in `settings.Settings.get()` — `settings.py:108`. Every resolution
remembers where the value came from; that is what `--explain` prints.

Making it visible:

```bash
weewx-evo serve --config evo.toml --explain
```

```
  interval        60             $WEEWX_EVO_INTERVAL
  grace           15             default
  live_db         data/live.sdb  default
```

This precedence applies to process settings. Place settings and archive files
come only from `archives.toml`.

## Environment variables

The name comes from the setting's name: dots to underscores, upper case, prefix
`WEEWX_EVO_`.

| Setting | Variable |
|---|---|
| `token` | `WEEWX_EVO_TOKEN` |
| `live_db` | `WEEWX_EVO_LIVE_DB` |
| `admin.port` | `WEEWX_EVO_ADMIN_PORT` |
| `feeds.json.units` | `WEEWX_EVO_FEEDS_JSON_UNITS` |

### Aliases

A few names existed for environment variables before they existed for settings.
They carry on working, with the factor that converts their unit into the
setting's (`settings.ENV_ALIASES`):

| Alias | Setting | Factor |
|---|---|---|
| `WEEWX_EVO_LIVE` | `live_db` | 1 |
| `WEEWX_EVO_ARCHIVE` | legacy `archive_db`, used only to create the first `archives.toml` | 1 |
| `WEEWX_EVO_RETENTION_DAYS` | `retention` | 86400 |
| `WEEWX_EVO_RAW_MINUTES` | `raw_retention` | 60 |

A running installation should not break because a name got tidier. The day
somebody renames a variable is the day they find out in how many places it was
used.

## The configuration file

TOML, because Python can read it with no dependency and a person can edit it
without learning anything. `evo.toml` is the one process-settings file, and the
admin page writes the same file a person would write. Repeated records live in
their own TOML files: places in `archives.toml`, console identities in
`stations.toml`, and plots in `plots.toml`.

Two things `config.py` watches for — both learned from configuration files that
went wrong in the field:

- **The file is rewritten, not patched.** Values come from the schema, comments
  from the `help` texts. That way the file explains itself, even years later
  when nobody remembers why something is set the way it is.
- **It is written alongside and then moved into place** (`config.write()`), plus
  a `.bak` of the previous version. An interrupted write cannot leave behind a
  file that is half a configuration.

Anything in the file that has no schema of its own is preserved across a rewrite
and reported as "unknown" (`config._unknown`).

### Example

```toml
# weewx-evo. Written by the settings page; safe to edit by hand.

interval = "5m"
token = "…"
infer_unknown = "series"

[admin]
token = "…"
port = 8080

[exports.webhost]
kind = "ftp"
host = "ftp.example.org"
trigger = "feed"
```

The place is a repeated record and therefore has its own file rather than an
`Option` block:

```toml
# archives.toml
[archives.default]
file = "data/weewx.sdb"
label = "Kirchdorf an der Amper"
latitude = 48.4596
longitude = 11.6539
altitude = 440.0

[archives.default.members."v1/ecowitt/a1b2c3"]
role = "main"
channel = 0
indoor = true
```

The member-table key is a canonical sender ID from the live database. It is
both the selection and this Place's policy for that sender. Field mappings are
scoped by Place and sender in `placement.toml`.

`stations.toml` assigns display names and clock tolerances to sender
identities. It contains no archive assignment, role, indoor policy or field
mapping.
`[sources]` and `--sources` are obsolete and ignored by the product runtime.

## Adding a setting

Into the schema, nowhere else. `options.py` for the core, `options()` on the
driver for a driver, `options()` on the feed for a feed:

```python
Option("infer_unknown", "Fields the catalog does not know",
       kind="choice", default="series",
       choices=(("off", "Drop them"), ("series", "…"), ("all", "…")),
       help="A reading put in the wrong column cannot be separated out afterwards.")
```

Out of it come, **on their own**:

- the form field on the admin page
- the validation (`Option.parse`)
- the comment in the written file
- the line in `--explain`
- the entry in `schema.json`

There is no second place an ordinary `Option` has to be entered. Repeated
records such as Places, senders and plots have their own declarations and
files.

## The declaration model

`options.py` holds three things:

| | |
|---|---|
| `Option` | One setting: name, label, `kind`, default, help, limits, choices |
| `Group` | Settings that belong together — becomes a section of the form |
| `Schema` | Everything a component can be configured with |

### `kind`

One of `text secret int float bool choice path duration list`. Each is a parser,
a check and a form field. A new `kind` means teaching it to parse, to check and
to render — all three, in one place each.

`secret` is `text` that is never rendered back: the admin page shows *whether*
one is set, not *which*. A token that has been displayed once is a token in a
screenshot.

`duration` is written the way people say it — `90`, `5m`, `2h`, `7d` — and held
in seconds. `format_duration()` picks the largest unit that divides evenly when
writing back: a retention of `604800` is a number nobody can check at a glance.

### Further fields on `Option`

| Field | What for |
|---|---|
| `choices_from` | Choices that depend on the installation rather than on the code — `installed_drivers()`, `defined_feeds()`, `published_names()`. A **function**, because the answer changes at runtime: adding a feed has to put it into the export's list, without a restart |
| `suggestions` | Values worth offering without forbidding others. The case for it is `allow`: "private", "any", or a list of networks nobody could enumerate |
| `advanced` | Hidden behind a toggle rather than left out — a hidden setting is one you find by reading source |
| `restart` | The change only takes effect after a restart |
| `required` | Empty is an error, not `None` |
| `minimum` / `maximum` | Range, checked in `_check_range` |
| `unit`, `placeholder` | Presentation only |

### Two pitfalls

**Arguments have no default in argparse.** `default=None`, always. argparse
cannot tell "not given" from "set to the default", and a default here beats the
configuration file — and then the admin page appears to do nothing, with no
error message anywhere. The comment for it is in `cli.add_common()`, and
`tools/settings_test.py` checks exactly that.

**A driver gets `view()`, not the whole thing.** Its corner of the settings and
nothing else:

```python
settings.view("drivers.example", schema)
```

A driver has no business with the upload token, and the way to make sure of that
is not to hand it over. The same logic as with
[`ingest/state.py`](Drivers#driver-state): give the narrow thing, and the wide
thing is out of reach.

## Reloading

```python
settings.reload()   # returns whether anything changed
```

That is what a settings service would buy, without the service. Everything the
object holds sees the new values; what demands a `restart` still demands one.

## weewx.conf

**Read, never written.** Two programs writing one file destroy each other's
comments.

The database is shared — the same file, the same meaning. The configuration is
not, and should not be. Process settings such as the archive interval may
nevertheless be read from `weewx.conf`:

```bash
weewx-evo serve --weewx-conf /etc/weewx/weewx.conf
```

Or permanently, as `weewx_conf` in our own file. Anything set here beats it.
Location, altitude and the archive path are different: if `archives.toml` is
absent, those old values are copied once into `[archives.default]`. Once the
file exists, they are never a runtime fallback.
→ [WeeWX-Compatibility](WeeWX-Compatibility)

## Commands

```bash
weewx-evo config show --config evo.toml            # print with comments
weewx-evo config show --config evo.toml --defaults # with every default
weewx-evo config set  --config evo.toml <name> <value>
weewx-evo config check --config evo.toml           # every value against its schema
weewx-evo config import /etc/weewx/weewx.conf [--write] [--overwrite]
```

→ [CLI-Reference](CLI-Reference), [Settings-Reference](Settings-Reference)

## The schema as JSON

```
GET http://<host>:8080/<admin-token>/schema.json
```

The same declaration as data — for an installer, a test, or an admin page
somebody likes better than this one.

<!-- covers
src/weewx_evo/settings.py
src/weewx_evo/options.py
src/weewx_evo/config.py
tools/settings_test.py
-->

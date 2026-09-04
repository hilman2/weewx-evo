# Drivers

`ingest/drivers.py`, `ingest/envelope.py`, `ingest/parsers.py`,
`ingest/state.py`, `ingest/userdrivers.py`, `addons.py`, `catalogue.py`.

## The seam

**The core owns the socket.** Threads, shutdown, body limits, IPv6, the token
check and writing to the live table. That is the same for every protocol, it is
where push drivers go wrong, and doing it once means doing it once.

**The driver owns everything else.** Parsing, units, which device it answers at
all, and **what that device has to hear back**.

**The naming is shared, and the seam is data.** A driver hands over the
readings under the names the hardware used, plus a versioned `DialectSpec`
that describes the field map, units, scale factors and metadata using JSON
values only. The listener stores both. When a record is built, core code
combines that inert description with what this archive decided
→ [Placements](Placements).

That split is a security boundary, not just an interface choice. The archive
process neither imports nor calls the driver that accepted an upload. A
mapping cannot name a module, callable or class, and unknown keys or versions
are rejected rather than guessed.

A driver whose names are already WeeWX's says so by leaving `dialect` and
`mapping` unset. That is every collector, the WeeWX shim and the envelope.

## The interface

```python
class Driver(Protocol):
    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        ...

    def dialect_spec(self, readings: dict, dialect: str) -> DialectSpec | None:
        ...   # optional when the names are already WeeWX's
```

`meta` carries `received` (arrival time, unix) and `source` (the peer address).

**Returning an empty list is normal and not an error**: consoles send probe
requests, heartbeats and uploads with no readings in them.

### `BaseDriver`

For a driver that only has to parse. Defaults for everything else.

```python
from weewx_evo.ingest.drivers import BaseDriver

class MyDriver(BaseDriver):
    response = (b'{"ok":true}', "application/json")

    def packets(self, body, meta):
        return [...]
```

| Attribute / method | What it means |
|---|---|
| `response` | `(bytes, content_type)` — what the device wants to hear |
| `packets(body, meta)` | The heart of it |
| `dialect_spec(readings, dialect)` | Inert, versioned JSON vocabulary for a raw dialect. Required when a packet sets `dialect` |
| `status()` | What should appear at `/status`. Optional |
| `close()` | Release what is held. Optional |
| `options()` | This driver's settings, as a list of `Group`s. Optional |
| `redact(raw)` | The upload with the secret parts removed. Optional |

Further optional hooks, as the Ecowitt implementation shows:
`hardware_name()`, `unit_groups()`, `missing_columns(known)`.

### `options()` declares the settings

A driver that gains a setting gains a form field, validation and a comment in
the written file — without anything changing anywhere else.

```python
@staticmethod
def options():
    from weewx_evo.options import Group, Option
    return [
        Group("Console", "Which hardware this driver answers to.", (
            Option("passkey", "Console PASSKEY", kind="secret", …),
        ), prefix="drivers.mine"),
    ]
```

→ [Configuration](Configuration)

### The declaration is applied, not merely documented

A driver says `kind="duration"` and would then be handed the string `"4h"`,
because that is what stands in the configuration file. **Every driver parsing
its values a second time itself is exactly what the option schema is there to
prevent** — and one that forgets gets a `ValueError` at startup, caught, and
then runs quietly on its default.

`drivers._parsed()` therefore applies the driver's declaration **once**, before
it is built. What the schema cannot make sense of is discarded rather than
passed on: the driver falls back to its own default and the station carries on
recording. **Said out loud**, because the setting then does not do what whoever
wrote it thinks.

## The registry

`drivers.Registry` holds **instances, not classes**, in the Listener. A driver
holds parser configuration and protocol state, which have to survive between
two uploads. Field placement is not driver state; each Place applies it after
reading the raw packet from the live database.

| Method | What it means |
|---|---|
| `register(name, driver, replace=False)` | A finished instance |
| `register_factory(name, factory, aliases=())` | Something to be built once its configuration is known |
| `configure(name, options)` | Build the factory with its options and install it |
| `_parsed(factory, options)` | The options in the shape the driver declared |
| `get(name)`, `known(name)`, `names()` | |
| `canonical_names()` | Names that are not an alias of another driver |
| `aliases_of(name)` | |
| `load()` | Fetch what is installed |
| `close()` | |

`aliases` are other names for the same driver — a second protocol it also reads.
Ecowitt has `wunderground` as an alias. Configuring one configures all: **two
instances of the same driver would adopt one station each and keep one state
each.** Which is why `canonical_names()` returns only the real ones.

`load()` reports a broken driver but is **never fatal**. A package that will not
import must not take the listener with it: the other protocols still have
readings coming in.

## Where drivers come from

### 1. Installed as a package — the ordinary way

Every driver is its own package on GitHub, listed in the catalogue, and
installed with pip. The core ships none: an installation that has not
installed one can receive nothing, which is deliberate. Most stations are
one console, and one is what they should have to install.

```bash
weewx-evo addon list                       # what is here and what exists
weewx-evo addon install weewx-evo-ecowitt
weewx-evo addon remove weewx-evo-ecowitt
```

The settings page does the same thing under System -> Add-ons, and puts what
would read an upload arriving here unread at the top of it.

A new one needs a restart. Entry points are read once per process, so an
add-on installed while the service runs is there and doing nothing until it
comes back; both the page and the command say so.

### 2. Dropped into `<data directory>/drivers/`

A driver that is not a package: a file or a directory, installed from a path
or a zip. Outside the package, so that an upgrade does not touch it and
nothing in there is taken for ours -- and it is the way in that needs no
network, which is the whole reason it stays.

```bash
weewx-evo driver install https://github.com/someone/weewx-evo-acurite
weewx-evo driver install ./driver.zip
weewx-evo driver install ./a-directory
weewx-evo driver list
weewx-evo driver remove acurite
```

`userdrivers.py`:

| Function | What it means |
|---|---|
| `directory(configured, archive)` | Where they live. `--driver-dir`, then `driver_dir`, then next to the archive. Also `WEEWX_EVO_DRIVER_DIR` |
| `installed(where)` | What is installed, as `(name, origin)` |
| `load(registry, where)` | Register each of them |
| `install(source, where, name, force)` | From a git URL, a zip or a directory |
| `remove(name, where)` | |
| `inspect_source(package)` | What the code reaches for, as `{hint: [files]}` |

Installing **runs nothing and imports nothing**. A driver is code that will
later run as a service, and the decision to install it comes before the first
run. `_is_driver()` too checks by reading, not by importing.

`_find_package()` looks for the package at the top, one level down (a zip
usually wraps everything in a directory named after the release), and under
`src/` and `bin/user/`.

The origin is recorded in `.origin` next to the package.

### 3. As an entry point

What the first way is, underneath. A package declares:

```toml
[project.entry-points."weewx_evo.drivers"]
mine = "my_package:MyDriver"
```

and `Registry.load()` finds it. Nothing else is needed, and nothing in the
core is edited: this is the contract, and it was here before the drivers
moved out to use it.

The other groups work the same way: `weewx_evo.collectors` for a sort of
collector, and `exports`, `feeds`, `forecast`, `notify`, `uploads`,
`parsers` for the rest.

## Can a driver run amok?

**In-process: yes, and it cannot be prevented.** A driver is Python in the same
interpreter, `import sqlite3` is enough, and no interface stops code from going
round it. WeeWX has the same property.

The layer in between is therefore a **contract, not a cage**. What it does is
make the right thing easy and the wrong thing a visible, deliberate act.

Enforcement happens outside the process:

| Means | Effect |
|---|---|
| `listen` and `archive` split (`deploy/split.yml`) | The listener never opens the archive. A driver inside it **does not have the file** |
| A separate user without write permission on the archive | Makes the question moot |
| `driver install` reads the code | Reports `sqlite3`, `subprocess`, `socket`. A hint, not a guarantee |

`NOTABLE` in `userdrivers.py` is that list. It does not see through obfuscation
and cannot judge intent — it catches the honest mistake and the lazy shortcut.

→ [Security](Security), [Deployment](Deployment)

## Driver state

`ingest/state.py`. A driver sometimes has to remember something across
restarts. This is private protocol state, not sender selection, field placement
or archive routing. The built-in push drivers identify every upload and leave
those decisions to the Place.

The production Listener gives a stateful third-party driver a JSON-backed store
beside the live database. It never gives that process an `ArchiveStore`.

```python
class State(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...
```

Three methods on strings. Nothing else.

| Implementation | Where it lives |
|---|---|
| `ArchiveState` | Optional adapter for a library caller that explicitly supplies an archive; not used by the production Listener |
| `FileState` | A JSON file beside the live database — the production Listener's persistent driver state |
| `NoState` | Remembers only within the process |

`for_driver(name, archive=None, path=None)` uses only the backing its caller
explicitly supplies. `ArchiveState` remains supported as an isolated library
adapter; it is not a channel between Listener and Archiver.
The driver sees the three string operations, not the backing object.

The same logic as with `Settings.view()`: **give the narrow thing, and the wide
thing is out of reach.**

## The envelope — the only driver in the core

`ingest/envelope.py`. This is the **contract, not a protocol**: the shape a
driver hands over when it is done, and the only format the core itself
understands.

```json
{"dateTime": 1787734265, "usUnits": 1, "source": "vantage-1",
 "kind": "loop", "interval": null, "data": {"outTemp": 21.4}}
```

One object or a list of them. `data` may also sit flat in the object itself,
which is what most senders do. `RESERVED` names the keys that are then not read
as readings.

Reachable at `/<token>/json/`, over UDP, and via `listener.push()`.

## Running a WeeWX driver

An add-on: **weewx-evo-weewx-driver**. Every driver written for WeeWX,
unchanged -- the fourteen in its own tree and the hundred beside them, for
hardware nobody here owns and nobody here can test. WeeWX does not have to be
installed.

```bash
weewx-evo addon install weewx-evo-weewx-driver
weewx-evo-weewx-driver hardware              # what is plugged in
weewx-evo-weewx-driver run --collector shed
```

Its own command rather than a subcommand of `weewx-evo`, because it runs
where the hardware is and that need not be where weewx-evo runs. It
contributes a sort of collector through `weewx_evo.collectors`, so the
settings page offers it once it is installed and does not mention it before.

How it works -- the stand-ins for the names a driver imports, the form read
out of the driver's own `confeditor`, and the three simulated devices that
compare our stand-in against WeeWX' own code field for field -- is in that
repository, next to the code it describes.

## `parsers.py`

The older, function-based registry: a parser gets bytes and returns packets. It
touches no database, opens no socket and does not know what time it is unless
the payload says so.

That is exactly what makes a protocol testable against a stored recording — and
recordings are the only honest check here, because consoles do not send what
their documentation says.

`parse_json` is the same envelope as above. New drivers should implement
`Driver` / `BaseDriver`; `parsers` remains for the function-based route.

## Writing a driver

```python
"""A driver for a station that posts one line of numbers."""

from weewx_evo.db.live import Packet
from weewx_evo.ingest.drivers import BaseDriver


class LineDriver(BaseDriver):
    response = (b"OK\n", "text/plain")

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        temp, humidity = body.decode().split(",")
        return [Packet(
            dateTime=int(meta["received"]),
            usUnits=1,
            data={"outTemp": float(temp), "outHumidity": float(humidity)},
            source="line",
            kind="loop",
        )]


def load(registry):
    registry.register("line", LineDriver())
```

`tools/driverinstall.py` builds exactly such a package on disk, installs it,
loads it and takes an upload with it — the test that a third-party driver hangs
off the same interface as a bundled one.

→ [Push drivers](Driver-Ecowitt), [Testing](Testing)

<!-- covers
src/weewx_evo/addons.py
src/weewx_evo/adminaddons.py
src/weewx_evo/catalogue.py
src/weewx_evo/ingest/drivers.py
src/weewx_evo/ingest/envelope.py
src/weewx_evo/ingest/parsers.py
src/weewx_evo/ingest/sightings.py
src/weewx_evo/ingest/state.py
src/weewx_evo/ingest/userdrivers.py
tools/addons_test.py
tools/driverinstall.py
tools/wizard_test.py
-->

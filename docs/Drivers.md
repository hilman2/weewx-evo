# Drivers

`ingest/drivers.py`, `ingest/envelope.py`, `ingest/parsers.py`,
`ingest/state.py`, `ingest/plugins/`, `ingest/userdrivers.py`.

## The seam

**The core owns the socket.** Threads, shutdown, body limits, IPv6, the token
check and writing to the live table. That is the same for every protocol, it is
where push drivers go wrong, and doing it once means doing it once.

**The driver owns everything else.** Parsing, field names, units, which device
it answers at all, and **what that device has to hear back**.

## The interface

```python
class Driver(Protocol):
    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        ...
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

`drivers.Registry` holds **instances, not classes**: a driver holds
configuration and state — which consoles it answers, which field mapping belongs
to which — and that has to survive between two uploads.

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

### 1. Bundled — `ingest/plugins/`

Ours. One subfolder per driver, each a package with a `load(registry)`.
**Nothing is listed by hand**: every subdirectory is tried, so adding a driver
means adding a directory.

```python
# ingest/plugins/__init__.py
def bundled() -> list[str]  # the driver packages in this directory
def load(registry) -> list[str]  # register each, return the names
```

Important drivers living here is a decision about **maintenance**, not about
coupling: a driver in the repo hangs off the same interface as one from outside
and could be pulled out without the core noticing.

### 2. Installed — `<data directory>/drivers/`

Third-party ones. They live **outside** the package, so that an upgrade does not
touch them and nothing in there is taken for ours.

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

```toml
[project.entry-points."weewx_evo.drivers"]
mine = "my_package:MyDriver"
```

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
restarts. The Ecowitt driver remembers which console it adopted — otherwise the
next console to upload becomes the station, and two sensors end up in one
column.

The obvious thing would be to give it the `ArchiveStore`. That is **too much**:
it could then write records, create columns and delete history.

```python
class State(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...
```

Three methods on strings. Nothing else.

| Implementation | Where it lives |
|---|---|
| `ArchiveState` | The archive's `metadata` table. The right place: it sits with the readings the state protects, is in every backup of them, and moves with them |
| `FileState` | A JSON file — for the listener on its own and for tests. Worse (a freshly set up machine loses it), but better than nothing |
| `NoState` | Remembers only within the process |

`for_driver(name, archive=None, path=None)` picks the best safeguard available.

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

## Running a WeeWX driver — `ingest/weewxshim.py`

WeeWX has fifteen years of drivers: fourteen in its own tree and around a
hundred outside it, for hardware nobody here owns and cannot test against.
They run unchanged.

```bash
weewx-evo weewx-driver check --conf /etc/weewx/weewx.conf   # build it, send nothing
weewx-evo weewx-driver run   --conf /etc/weewx/weewx.conf   # deliver
```

Its own process, delivering over `listener.push()` like any other collector.
That is the point rather than an implementation detail: in WeeWX the driver
lives inside the engine, so a serial port that stops answering stops
everything. Here it can wedge, crash or leak and the listener and archiver
carry on — and it does not have to be on the same machine. `deploy/weewx-driver.service`
is a unit file for it.

**Where it taps in.** WeeWX's engine puts a loop packet through four groups of
services before the accumulator sees it:

```
genLoopPackets()
  -> prep     StdTimeSynch
  -> process  StdConvert, StdCalibrate, StdQC, StdWXCalculate
  -> xtype    StdWXXTypes, StdPressureCooker, StdRainRater, StdDelta
  -> archive  StdArchive
```

None of it is reproduced, because running it would run it twice: `units.py`
is StdConvert, `derive.py` is StdWXCalculate and the four xtype services,
`archiver.py` is StdArchive. The raw packet is what is taken. (StdCalibrate
and StdQC have no counterpart here yet.)

The shapes already match — a loop packet is `{dateTime, usUnits, …readings}`
and the envelope is that plus `source`, `kind` and `interval`. Two keys move
out and the rest is `data`. That is not luck: the field names and the
`usUnits` constants are WeeWX's, because keeping a WeeWX database readable
meant adopting them.

**What a driver may ask of the engine** is one method, `bind`. Measured over
WeeWX's fourteen own drivers, exactly one — Vantage — touches the engine at
all, because it is a driver and a service at once. Its events are really
dispatched, including `END_ARCHIVE_PERIOD`: Vantage accumulates the loop gust
across packets and clears it only there, so a shim that skipped it would
report a gust that never falls, with nothing about the numbers looking wrong.

Hardware that keeps its own records can be asked for them at startup with
`--catchup`, delivered as `kind="archive"`, which the archiver already prefers
over what it accumulated. That is what turns an outage into a filled gap.

### With no WeeWX installed — `ingest/weewxnames.py`

A driver is one file, and what it imports at the top is nearly nothing.
Counted across the fourteen drivers in WeeWX's tree:

| | uses it | what it is |
|---|---|---|
| `weewx.drivers` | 13 | three base classes, nearly empty |
| `weewx.WeeWxIOError` | 12 | an exception |
| `weewx.wxformulas` | 11 | one function of it, twelve lines |
| `weeutil.weeutil` | 10 | `to_bool`, `to_int`, `timestamp_to_string` |
| `weewx.METRIC` / `US` | 7 | the numbers 16 and 1, which are ours too |

`weewxnames.py` is all of it, so a driver runs with WeeWX nowhere on the
machine. Point at the file:

```bash
weewx-evo weewx-driver check --conf ./vantage.conf \
    --driver-file ~/weewx/src/weewx/drivers/vantage.py
```

**All thirteen drivers in WeeWX's tree import against it**, from fousb at
four names to Vantage at twenty. `tools/standin_test.py` measures that in a
process where `import weewx` raises, and decodes a stored fousb record on top
of it.

Vantage — every Davis station — needed three pieces the lighter drivers did
not, and each was its whole reason not to run: `weewx.engine`, because it is
a driver *and* a service and inherits `StdService`; `weewx.crc16`, which has
to be a module because it is imported as `from weewx.crc16 import crc16`; and
`weewx.units` for `ValueTuple`, `convert` and `GenWithConvert`. The
conversion constants come from our own `units.py` rather than being retyped —
0.0295299875 against 0.02953 is the fourth decimal of every pressure reading,
and nothing about the number would look wrong.

Three things about it:

- **Where WeeWX is installed, WeeWX wins.** Same rule as pyephem: whoever has
  the real one gets its behaviour, edges included. This fills in what is
  missing rather than replacing what is there.
- **A name is claimed only if free.** `skinkit.py` puts modules under these
  same names so a WeeWX *skin* renders, and `sys.modules` is one table per
  process — whichever ran second would take the other's away.
- **The hardware library is still needed.** `import usb` is pyusb, `import
  serial` is pyserial, and no stand-in can supply either: one that did would
  give a driver that builds and reads nothing. `check` names the package.

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

→ [Driver-Ecowitt](Driver-Ecowitt), [Testing](Testing)

<!-- covers
src/weewx_evo/ingest/drivers.py
src/weewx_evo/ingest/envelope.py
src/weewx_evo/ingest/parsers.py
src/weewx_evo/ingest/state.py
src/weewx_evo/ingest/userdrivers.py
src/weewx_evo/ingest/plugins/__init__.py
tools/driverinstall.py
-->

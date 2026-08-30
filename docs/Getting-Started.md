# Getting started

## Requirements

Python 3.11 or newer. Nothing else — weewx-evo has no dependencies outside the
standard library, and that is deliberate: a weather station runs for years
without anyone looking at it, and every dependency is something that can break
in that time.

Optional, only for sharper solar times: `pyephem`. → [Sun](Sun)

## Installing

```bash
git clone https://github.com/hilman2/weewx-evo
cd weewx-evo
pip install -e .
```

That gives you the `weewx-evo` command. Without installing works too:

```bash
PYTHONPATH=src python -m weewx_evo.cli --help
```

## The shortest path to running data

### 1. Set a token

The token is a path segment every upload has to carry. It is the only thing
between the open internet and your record — hardware cannot send headers, so an
unguessable path is the practical answer.

```bash
python -c "import secrets; print(secrets.token_hex(24))"
```

### 2. Create a configuration file

```bash
weewx-evo config set --config evo.toml token <the-token-from-just-now>
weewx-evo config set --config evo.toml station.name "Kirchdorf an der Amper"
weewx-evo config set --config evo.toml station.latitude 48.4596
weewx-evo config set --config evo.toml station.longitude 11.6539
weewx-evo config set --config evo.toml station.altitude 440
```

`config set` checks every value against the schema that owns it. A typo in the
name or a latitude of 95 comes straight back, not at startup.

Or write the lot at once — the file is TOML and meant for people:

```toml
# evo.toml
token = "…"
interval = "5m"

[station]
name = "Kirchdorf an der Amper"
latitude = 48.4596
longitude = 11.6539
altitude = 440.0
```

### 3. Start it

```bash
weewx-evo serve --config evo.toml
```

That starts the listener and the archiver in one process. The first start
creates `data/live.sdb` and `data/weewx.sdb` — the latter with the same schema
WeeWX creates for a new database (`wview_extended`, 113 columns).

### 4. Find the address

```bash
weewx-evo url --config evo.toml --qr
```

Prints the upload address and the live view, both with the token, and on
request a QR code so you do not have to type it into a phone. The token is in
the path, so an address without it is useless and one with it is the whole key
— which is why this command exists: the two belong together.

### 5. Point the console at it

With Ecowitt hardware: *Weather Services → Customized*, protocol "Ecowitt", host
the machine's IP, port 8000, path `/<token>/ecowitt/`.

### 6. Check that something is arriving

In a browser: `http://<host>:8000/<token>/live` — the status page. It exists for
exactly one question, the one you keep asking while setting things up: *is
anything coming in?* Without it the answer would be SSH, `docker exec` and a
hand-written SQL query.

On the command line:

```bash
weewx-evo status --config evo.toml
```

## Using an existing WeeWX database

This is the real case. Point weewx-evo at the file you have:

```bash
weewx-evo config set --config evo.toml archive_db /etc/weewx/archive/weewx.sdb
```

The schema is **read from the file**, not from a list in the code. An
installation with columns of its own keeps them. WeeWX can carry on using the
same file afterwards. → [WeeWX-Compatibility](WeeWX-Compatibility)

**Back it up first.** Not by copying, but:

```bash
sqlite3 weewx.sdb "VACUUM INTO 'backup.sdb'"
```

`cp` on a database that is being written to, together with a half-copied WAL,
gives you a torn state.

### Taking the settings from weewx.conf

```bash
weewx-evo config import /etc/weewx/weewx.conf --config evo.toml
weewx-evo config import /etc/weewx/weewx.conf --config evo.toml --write
```

Without `--write` it only reports. The report also names what was **not**
taken over, and why — silence reads like "lost".
→ [WeeWX-Compatibility](WeeWX-Compatibility)

### Taking the plots from a skin

```bash
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf --write
```

→ [Plots](Plots)

## Anything without a column gets reported

A reading survives the archive interval only if the table has a column for it.
The default schema has 113; Ecowitt hardware fills four times that.

```bash
weewx-evo columns --config evo.toml
```

```
44 field(s) arriving, 8 with nowhere to live.

  dayRain           2831 packet(s), e.g. 0.012      -> REAL
  lightning_num     2831 packet(s), e.g. 0.0        -> INTEGER
  ...
```

Nothing is created on its own: where a reading belongs is a decision, and the
wrong one mixes two sensors into a column nobody can separate afterwards.
`--add` creates them — **back up first**.

## The settings page

```bash
weewx-evo config set --config evo.toml admin.token <a-different-token>
weewx-evo admin --config evo.toml
```

Then `http://<host>:8080/<admin-token>/`. Its own port, its own token: an upload
can at worst write a wrong reading, the admin page can point the archive at a
different file. The same token for both is refused.
→ [Admin-Page](Admin-Page), [Security](Security)

Reaching it from elsewhere without opening it up:

```bash
ssh -L 8080:localhost:8080 the-station
```

## Where a value came from

```bash
weewx-evo serve --config evo.toml --explain
```

```
  station.name    'Kirchdorf an der Amper'   the configuration file
  interval        60                         $WEEWX_EVO_INTERVAL
  station.altitude 440.0                     weewx.conf
  grace           15                         default
```

One line per setting, with its origin. Then the program stops.
→ [Configuration](Configuration)

## A page of your own on the local network

Three lines, and the plots are in a browser:

```toml
[exports.site]
kind = "local"
directory = "data/site"
source = "json"

[web]
enabled = true
default = "site"
```

A [`local` export](Exports#a-directory-on-this-machine) puts down what the
[JSON feed](Feeds) produced, and the built-in [web server](Web-Server) serves it
at `http://<host>:8081/`. The name of the export **is** the address — nobody has
to write the same path down twice.

## Next steps

- Produce plots and JSON → [Plots](Plots), [Feeds](Feeds)
- Push it to a web host → [Exports](Exports)
- Run it in a container → [Deployment](Deployment)
- Add a second sensor → [Multiple-Sources](Multiple-Sources)
- Record a second spot → [Several places](Places)

<!-- covers
README.md
-->

<!-- watches
src/weewx_evo/cli.py
src/weewx_evo/options.py
-->

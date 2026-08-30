# Deployment

`deploy/`.

## The container

`deploy/Dockerfile`:

```dockerfile
FROM python:3.13-slim
```

> weewx-evo has no dependencies outside the standard library, so there is
> nothing to install and nothing to pin. That is worth keeping: a weather
> station runs for years without anyone looking at it, and every dependency is
> something that can break in that time.

Two things about it are not formalities:

### The time zone is part of the data

```dockerfile
ENV TZ=Europe/Berlin
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
```

**The archive's day boundary is local time.** The container's time zone is
therefore part of the data, not a display setting. A container in UTC writes
`archive_day_*` rows sitting on different midnights than a WeeWX instance next
to it — and the two cannot be compared afterwards.

### Unprivileged

```dockerfile
RUN useradd --system --uid 1001 --create-home weewx && \
    mkdir -p /data && chown weewx:weewx /data
USER weewx
```

The process is reachable from the internet through a reverse proxy and has no
reason to own the files it writes, beyond writing them.

```dockerfile
ENTRYPOINT ["python", "-m", "weewx_evo.cli"]
CMD ["serve"]
```

## One process — `deploy/compose.yml`

```yaml
services:
  weewx-evo:
    mem_limit: 256m
    ports:
      - "127.0.0.1:3041:8000"   # uploads and live view
      - "127.0.0.1:3042:8080"   # the settings page
    volumes:
      - /opt/weewx-evo/data:/data
    command: ["serve", "--spool", "/data/packets"]
```

| Decision | Reason |
|---|---|
| `mem_limit: 256m` | The host has no swap and runs other things in earnest. An unlimited container here would take one of them into the OOM killer |
| `127.0.0.1:…` | **Localhost only.** The reverse proxy is the only way in |
| Two ports | Two tokens, two services → [Security](Security) |
| `logging: journald` | There is no syslog in a container, and the host reads its logs with `journalctl`. `docker logs` carries on working |

### The environment

```yaml
environment:
  - TZ=Europe/Berlin
  - WEEWX_EVO_LIVE=/data/live.sdb
  - WEEWX_EVO_ARCHIVE=/data/weewx.sdb
  - WEEWX_EVO_INTERVAL=60
  - WEEWX_EVO_DRIVER=ecowitt
  - WEEWX_EVO_DRIVER_DIR=/data/drivers
  - WEEWX_EVO_RETENTION_DAYS=7
  - WEEWX_EVO_PUBLIC_URL=…
  - WEEWX_EVO_CONFIG=/data/evo.toml
  - WEEWX_EVO_ALLOW=private
  - WEEWX_EVO_ADMIN_ALLOW=private
  - WEEWX_EVO_ADMIN_HOST=0.0.0.0
  - WEEWX_EVO_TOKEN=${WEEWX_EVO_TOKEN:?set WEEWX_EVO_TOKEN in .env}
  - WEEWX_EVO_ADMIN_TOKEN=${WEEWX_EVO_ADMIN_TOKEN:?set WEEWX_EVO_ADMIN_TOKEN in .env}
```

The `:?` form makes Compose **abort** when a token is missing, rather than start
without one.

**The tokens live in `deploy/.env`, which is not in the repo.**

`WEEWX_EVO_ADMIN_HOST=0.0.0.0` applies **inside** the container, so that the
proxy can reach it. What keeps it private is the port binding above and the
token — not the bind address.

`ALLOW=private` stays the default: Caddy connects from the Docker bridge
network, which is private. So the reverse proxy carries on working while nothing
reaches the container directly.

### Health check

```yaml
test: ["CMD", "python", "-c",
       "import os,urllib.request as u; u.urlopen('http://127.0.0.1:8000/'+os.environ['WEEWX_EVO_TOKEN']+'/status', timeout=5).read()"]
```

The status endpoint sits behind the token, so the check carries it.

## Split — `deploy/split.yml`

```bash
docker compose -f compose.yml -f split.yml up -d
```

The answer to "can a driver be stopped from writing to the archive".

**In-process it cannot.** A driver is Python in the same interpreter, `import
sqlite3` is enough. What stops it is **not having the file**.

| Service | What it has |
|---|---|
| `weewx-evo` (listener) | The drivers. Mounts the live database read-write and the archive **not at all**. A driver in it can try whatever it likes |
| `weewx-evo-archiver` | No drivers, listens to nothing, mounts both. Reads packets, writes records |

They **never** talk to each other. The live database is the entire interface —
which is what makes splitting them a change to this file and to no line of code.

```yaml
weewx-evo:
  command: ["listen"]
  environment:
    - WEEWX_EVO_LIVE=/data/live.sdb
    # No WEEWX_EVO_ARCHIVE.
    - WEEWX_EVO_STATE_DIR=/data
  read_only: true
  tmpfs: [/tmp]
  security_opt: [no-new-privileges:true]
  cap_drop: [ALL]
```

Without `WEEWX_EVO_ARCHIVE`, a driver that wants to remember something gets a
**file** in `/data` instead of the archive's metadata table.
→ [Drivers](Drivers#driver-state)

The archiver has **no ports**. Nothing reaches it from outside, and it reaches
nothing.

### Two pitfalls in the split

Both are recorded as comments in the file:

- **Retention belongs to the archiver, not to the listener.** Packets may only
  be dropped once they are in a record, and only that side knows.
- **SQLite in WAL mode writes `-shm` and `-wal` next to the file — for reading
  too.** Mounting the directory read-only is therefore **not** the same as
  mounting the file read-only, and the former fails. The route that works is a
  user without write permission on the archive.

## The reverse proxy

`deploy/weewx-evo.caddy` is **in `.gitignore`** — the file contains the real
token paths. The structure:

```caddyfile
station.example.org {
	# Uploads and the live view.
	handle /<upload-token>/* {
		reverse_proxy 127.0.0.1:3041
	}

	# The settings page.
	handle /<admin-token>/* {
		reverse_proxy 127.0.0.1:3042
	}

	# A bare GET says the service is running, and nothing else.
	@root {
		method GET
		path /
	}
	handle @root {
		respond "weewx-evo" 200
	}

	handle {
		respond 404
	}
}
```

Two token paths, two ports, and they are deliberately **not the same secret**.
An upload can at worst write a wrong reading; the settings page can point the
archive at a different file.

The `handle` block at the bottom matters: **anything without a token is a 404.**
Answering an upload we discarded with a 200 would tell a misconfigured console
it had been heard.

## Rolling it out

**The target host runs production services.**

- Touch only your own Compose project, always name containers explicitly.
- **No `docker system prune`, no global `down`.**
- Caddy: `caddy validate` **before** every `reload`, then check the production
  services.
- **`rsync --delete` takes `deploy/.env` with it** — always `--exclude ".env"`.

```bash
wsl -d Ubuntu -- bash -lc 'rsync -az --delete --exclude ".env" \
  --exclude "__pycache__" -e /mnt/c/Windows/System32/OpenSSH/ssh.exe \
  /mnt/d/Git/weewx-evo/src <host>:/opt/weewx-evo/'
ssh <host> 'cd /opt/weewx-evo/deploy && docker compose build -q && \
  docker compose up -d weewx-evo'
```

Windows has no native rsync — hence WSL Ubuntu, and because WSL does not know
the Windows SSH keys, `ssh.exe` as the transport.

## systemd instead of Docker

Three units, the same split:

```ini
# weewx-evo-listen.service
[Service]
User=weewx
Environment=WEEWX_EVO_CONFIG=/etc/weewx-evo/evo.toml
ExecStart=/usr/local/bin/weewx-evo listen
Restart=always
```

```ini
# weewx-evo-archive.service
ExecStart=/usr/local/bin/weewx-evo archive --spool /var/lib/weewx-evo/packets
```

```ini
# weewx-evo-admin.service
ExecStart=/usr/local/bin/weewx-evo admin
```

Or a single one with `serve`. **With no code change** — that is the point of the
split.

The user the listener runs as should have no write permission on the archive.
That is the enforcement that actually counts.

## Backing up

```bash
sqlite3 /data/weewx.sdb "VACUUM INTO '/backup/weewx-$(date +%F).sdb'"
```

Not `cp`. The database is being written to alongside, and a copied WAL is a torn
state.

The live database does **not** have to be backed up: it is a cache with a few
days in it. What it holds that is not yet in a record would be lost — minutes,
not years.

What is backed up **with** the archive: the driver state, because it sits in the
metadata table. Which is exactly why it sits there.

<!-- covers
deploy/Dockerfile
deploy/compose.yml
deploy/split.yml
-->

<!-- watches
deploy/
-->

# Deployment

`deploy/`.

## Der Container

`deploy/Dockerfile`:

```dockerfile
FROM python:3.13-slim
```

> weewx-evo hat keine Abhängigkeiten außerhalb der Standardbibliothek, es gibt
> also nichts zu installieren und nichts zu pinnen. Das ist es wert, so zu
> bleiben: eine Wetterstation läuft jahrelang, ohne dass jemand hinschaut, und
> jede Abhängigkeit ist etwas, das in dieser Zeit kaputtgehen kann.

Zwei Dinge daran sind keine Formalitäten:

### Die Zeitzone ist Teil der Daten

```dockerfile
ENV TZ=Europe/Berlin
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
```

**Die Tagesgrenze des Archivs ist lokale Zeit.** Die Zeitzone des Containers ist
damit Teil der Daten, keine Anzeigeeinstellung. Ein Container in UTC schreibt
`archive_day_*`-Zeilen, die auf anderen Mitternächten sitzen als die einer
WeeWX-Instanz daneben — und die beiden lassen sich danach nicht mehr
vergleichen.

### Unprivilegiert

```dockerfile
RUN useradd --system --uid 1001 --create-home weewx && \
    mkdir -p /data && chown weewx:weewx /data
USER weewx
```

Der Prozess ist durch einen Reverse Proxy vom Internet erreichbar und hat keinen
Grund, die Dateien zu besitzen, die er schreibt, über das Schreiben hinaus.

```dockerfile
ENTRYPOINT ["python", "-m", "weewx_evo.cli"]
CMD ["serve"]
```

## Ein Prozess — `deploy/compose.yml`

```yaml
services:
  weewx-evo:
    mem_limit: 256m
    ports:
      - "127.0.0.1:3041:8000"   # Uploads und Live-Ansicht
      - "127.0.0.1:3042:8080"   # die Einstellungsseite
    volumes:
      - /opt/weewx-evo/data:/data
    command: ["serve", "--spool", "/data/packets"]
```

| Entscheidung | Grund |
|---|---|
| `mem_limit: 256m` | Der Host hat keinen Swap und lässt anderes ernsthaft laufen. Ein unbegrenzter Container hier nähme eines davon in den OOM-Killer |
| `127.0.0.1:…` | **Nur localhost.** Der Reverse Proxy ist der einzige Weg hinein |
| Zwei Ports | Zwei Tokens, zwei Dienste → [Security](Security) |
| `logging: journald` | Es gibt kein syslog in einem Container, und der Host liest seine Logs mit `journalctl`. `docker logs` funktioniert weiterhin |

### Die Umgebung

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

Die `:?`-Form lässt Compose **abbrechen**, wenn ein Token fehlt, statt ohne
eines zu starten.

**Die Tokens leben in `deploy/.env`, das nicht im Repo ist.**

`WEEWX_EVO_ADMIN_HOST=0.0.0.0` gilt **innerhalb** des Containers, damit der Proxy
ihn erreicht. Was ihn privat hält, ist die Port-Bindung oben und das Token —
nicht die Bindeadresse.

`ALLOW=private` bleibt der Default: Caddy verbindet aus dem Docker-Bridge-Netz,
das privat ist. Der Reverse Proxy funktioniert also weiter, während nichts den
Container direkt erreicht.

### Healthcheck

```yaml
test: ["CMD", "python", "-c",
       "import os,urllib.request as u; u.urlopen('http://127.0.0.1:8000/'+os.environ['WEEWX_EVO_TOKEN']+'/status', timeout=5).read()"]
```

Der Status-Endpunkt sitzt hinter dem Token, der Check trägt es also mit.

## Getrennt — `deploy/split.yml`

```bash
docker compose -f compose.yml -f split.yml up -d
```

Die Antwort auf „kann ein Treiber davon abgehalten werden, ins Archiv zu
schreiben".

**Im Prozess kann er es nicht.** Ein Treiber ist Python im selben Interpreter,
`import sqlite3` genügt. Was ihn abhält, ist, **die Datei nicht zu haben**.

| Dienst | Was er hat |
|---|---|
| `weewx-evo` (Listener) | Die Treiber. Mountet die Live-Datenbank read-write und das Archiv **gar nicht**. Ein Treiber darin kann versuchen, was er will |
| `weewx-evo-archiver` | Keine Treiber, hört auf nichts, mountet beides. Liest Pakete, schreibt Sätze |

Sie reden **nie** miteinander. Die Live-Datenbank ist die ganze Schnittstelle —
das ist, was das Aufteilen zu einer Änderung an dieser Datei und an keiner Zeile
Code macht.

```yaml
weewx-evo:
  command: ["listen"]
  environment:
    - WEEWX_EVO_LIVE=/data/live.sdb
    # Kein WEEWX_EVO_ARCHIVE.
    - WEEWX_EVO_STATE_DIR=/data
  read_only: true
  tmpfs: [/tmp]
  security_opt: [no-new-privileges:true]
  cap_drop: [ALL]
```

Ohne `WEEWX_EVO_ARCHIVE` bekommt ein Treiber, der sich etwas merken will, eine
**Datei** in `/data` statt der Metadaten-Tabelle des Archivs.
→ [Drivers](Drivers#treiber-zustand)

Der Archiver hat **keine Ports**. Nichts erreicht ihn von außen, und er erreicht
nichts.

### Zwei Fallen im Split

Beide stehen als Kommentar in der Datei:

- **Retention gehört zum Archiver, nicht zum Listener.** Pakete dürfen erst
  fallen, wenn sie in einem Satz stehen, und nur diese Seite weiß das.
- **SQLite im WAL-Modus schreibt `-shm` und `-wal` neben die Datei — auch zum
  Lesen.** Das Verzeichnis read-only zu mounten ist deshalb **nicht** dasselbe
  wie die Datei read-only zu mounten, und Ersteres schlägt fehl. Der wirksame
  Weg ist ein Benutzer ohne Schreibrecht aufs Archiv.

## Der Reverse Proxy

`deploy/weewx-evo.caddy` ist **in `.gitignore`** — die Datei enthält die echten
Token-Pfade. Die Struktur:

```caddyfile
station.example.org {
	# Uploads und die Live-Ansicht.
	handle /<upload-token>/* {
		reverse_proxy 127.0.0.1:3041
	}

	# Die Einstellungsseite.
	handle /<admin-token>/* {
		reverse_proxy 127.0.0.1:3042
	}

	# Ein blankes GET sagt, dass der Dienst läuft, und sonst nichts.
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

Zwei Token-Pfade, zwei Ports, und sie sind absichtlich **nicht dasselbe
Geheimnis**. Ein Upload kann schlimmstenfalls einen falschen Messwert schreiben;
die Einstellungsseite kann das Archiv auf eine andere Datei zeigen lassen.

Der `handle`-Block ganz unten ist wichtig: **alles ohne Token ist ein 404.**
Einem Upload, den wir verworfen haben, mit 200 zu antworten, würde einer
falsch konfigurierten Konsole sagen, sie sei gehört worden.

## Ausrollen

**Auf dem Zielhost laufen produktive Dienste.**

- Nur das eigene Compose-Projekt anfassen, Container immer beim Namen nennen.
- **Kein `docker system prune`, kein globales `down`.**
- Caddy: `caddy validate` **vor** jedem `reload`, danach die Produktivdienste
  prüfen.
- **`rsync --delete` nimmt `deploy/.env` mit** — immer `--exclude ".env"`.

```bash
wsl -d Ubuntu -- bash -lc 'rsync -az --delete --exclude ".env" \
  --exclude "__pycache__" -e /mnt/c/Windows/System32/OpenSSH/ssh.exe \
  /mnt/d/Git/weewx-evo/src <host>:/opt/weewx-evo/'
ssh <host> 'cd /opt/weewx-evo/deploy && docker compose build -q && \
  docker compose up -d weewx-evo'
```

Windows hat kein natives rsync — deshalb WSL Ubuntu, und weil WSL die
Windows-SSH-Keys nicht kennt, `ssh.exe` als Transport.

## systemd statt Docker

Drei Units, dieselbe Aufteilung:

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

Oder eine einzige mit `serve`. **Ohne Codeänderung** — das ist der Punkt der
Trennung.

Der Benutzer, unter dem der Listener läuft, sollte kein Schreibrecht auf das
Archiv haben. Das ist die Durchsetzung, die tatsächlich zählt.

## Sichern

```bash
sqlite3 /data/weewx.sdb "VACUUM INTO '/backup/weewx-$(date +%F).sdb'"
```

Nicht `cp`. Die Datenbank wird nebenher beschrieben, und ein kopiertes WAL ist
ein zerrissener Zustand.

Die Live-Datenbank muss **nicht** gesichert werden: sie ist ein Cache mit ein
paar Tagen darin. Was sie enthält und noch nicht in einem Satz steht, wäre
verloren — Minuten, nicht Jahre.

Was **mit** dem Archiv gesichert wird: der Treiberzustand, weil er in der
Metadaten-Tabelle sitzt. Genau deshalb sitzt er dort.

<!-- covers
deploy/Dockerfile
deploy/compose.yml
deploy/split.yml
-->

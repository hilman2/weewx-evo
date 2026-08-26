# Mitarbeiten

## Die eine Regel

> Eine bestehende WeeWX-Datenbank bleibt lesbar und schreibbar — **für WeeWX
> selbst**.

Bevor du an `aggregate.py`, `db/archive.py` oder `db/daily.py` etwas änderst:

```bash
python tools/difftest.py reference/weewx.sdb
```

Der Test rechnet die Tagesstatistiken einer echten Datenbank nach und vergleicht
sie mit dem, was WeeWX hineingeschrieben hat. Vorher **und** nachher laufen
lassen.

## Schreibstil im Code

**Englisch**, wie im weewx-Fork. Kommentare sagen **warum**, nicht was.

Eine Zeile, die erklärt, welcher Fehler ohne sie passiert, ist mehr wert als
drei, die den Code nacherzählen.

Gut:

```python
# 429 here, not 404: this one is a real client being told to slow down
```

Nicht gut:

```python
# increment the counter
```

Was hier gut ankommt, ist die **Begründung an der Entscheidung**. Nicht der
Ablauf, sondern warum es dieser Ablauf ist und nicht der naheliegende andere.

Die Modul-Docstrings sind der Ort für die längere Fassung. Sie sind die Quelle,
aus der dieses Wiki geschrieben ist.

## Wohin was gehört

| Wenn du schreiben willst über… | dann gehört es nach… |
|---|---|
| Ein Wetterprotokoll | den Treiber, nie in `listener.py` oder `archiver.py` |
| Eine neue Einstellung | ins Schema (`options.py` oder `options()` am Bauteil), sonst nirgends |
| Wie eine Größe aggregiert wird | `obstypes.py` |
| Eine Umrechnung | `units.py` — als **Transkription**, nicht nachgerechnet |
| Was erzeugt wird | einen Feed unter `feeds/<name>/` |
| Wohin es geschickt wird | einen Export unter `exports/` |
| Was gezeichnet wird | `plots.toml`, nie in einen Renderer |

## Die Fallen, die schon zugeschnappt sind

Diese Liste ist nicht theoretisch. Jeder Punkt war ein Fehler.

### argparse-Defaults schlagen die Konfigurationsdatei

```python
parser.add_argument("--interval", default=None)   # immer None
```

argparse kann „nicht angegeben" nicht von „auf den Default gesetzt"
unterscheiden. Ein Default hier schlägt die Konfigurationsdatei, und dann tut die
Admin-Seite scheinbar nichts, **ohne Fehlermeldung irgendwo**. Defaults leben im
Schema. → `tools/settings_test.py`

### Ein Teil-POST setzt alles andere zurück

Ein Formular, das nur eine Gruppe schickt, darf den Rest nicht auf Default
setzen. `MARKER = "__present__"` ist, wie das erkannt wird. Im Browser fällt es
nie auf. → `tools/adminpage.py`

### SQLite-Verbindungen sind thread-gebunden

`LiveStore.conn()` öffnet je Thread eine. Wer eine Verbindung durchreicht, baut
einen Fehler, der erst unter Last auftritt.

### Prüfen muss kostenlos sein

`has_attempts_left()` fragt, `failed()` zahlt. Wer beides vermengt, sperrt eine
Konsole nach fünf **gültigen** Uploads aus. → `tools/ratelimit_test.py`

### Eine „sauberere" Konstante ist eine falsche Konstante

`units.py` ist eine Transkription. WeeWX' Tabelle ist nicht selbstinvers, und das
ist **absichtlich geerbt**. Der Test prüft, dass unsere Drift ihre Drift ist.
→ `tools/unitcheck.py`

### `"5m"` kommt als String zurück

Ein Roundtrip durch Formular und Datei muss eine `duration` als Sekunden
zurückgeben, nicht als den String, der hineinging.

### WeeWX' Zeitsuffixe sind nicht unsere

`M` ist dort eine Minute, `m` ein **Monat**. Beim Lesen einer WeeWX-Datei gelten
WeeWX' Regeln (`_weewx_span`); zurückgeschrieben wird nie mit einem mehrdeutigen
Suffix.

### pyephem rechnet Refraktion selbst

`horizon = -0.833` zählt sie doppelt. Richtig ist `pressure = 0`,
`horizon = "-0:34"`, Oberrand. → [Sun](Sun)

## Eine Einstellung hinzufügen

Ins Schema, sonst nirgends:

```python
Option("infer_unknown", "Fields the catalog does not know",
       kind="choice", default="series",
       choices=(("off", "Drop them"), ("series", "…"), ("all", "…")),
       help="A reading put in the wrong column cannot be separated out afterwards.")
```

Daraus entstehen von selbst: das Formularfeld, die Validierung, der Kommentar in
der geschriebenen Datei, die Zeile in `--explain` und der Eintrag in
`schema.json`.

Ein neues `kind` bedeutet: **parsen, prüfen und rendern beibringen** — alle
drei, an je einer Stelle.

→ [Configuration](Configuration)

## Einen Treiber hinzufügen

Ein Verzeichnis unter `ingest/plugins/<name>/` mit einem `load(registry)`.
Nichts wird von Hand aufgezählt.

Wenn es kein Treiber ist, den wir pflegen: `weewx-evo driver install` und
außerhalb des Pakets lassen.

→ [Drivers](Drivers)

## Einen Feed hinzufügen

Ein Verzeichnis unter `feeds/<name>/` mit einer `produce(archive, into)` und
einer `options()`. Assets — Templates, Stylesheets, ein JS-Bundle — liegen
**daneben**, nicht in einem gemeinsamen Haufen.

→ [Feeds](Feeds)

## Was ein Test hier wert ist

Die Tests, die etwas gefunden haben, prüfen alle dasselbe Muster: **eine
Annahme, die im Browser nie auffällt.**

Wer etwas hinzufügt, sucht diese Sorte Fall — nicht den, der ohnehin auffiele.

Alle Tests laufen ohne Netz und ohne Zustand außerhalb eines
Temp-Verzeichnisses. → [Testing](Testing)

## Dev-Tooling

**Immer WSL Ubuntu**, nie Windows-Python:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && python -m pytest tests/ecowitt -q'
```

Die Default-WSL-Distro ist `docker-desktop` und hat kein Python — deshalb immer
explizit `-d Ubuntu`. Venvs liegen unter `~/venvs/<project>` innerhalb WSL, nicht
im Repo auf `/mnt/d` (NTFS-Long-Path-Bug).

```bash
ruff check src tools tests    # line-length 100
```

## Dieses Wiki pflegen

Jede Seite deklariert am Ende, welche Dateien sie abdeckt:

```markdown
<!-- covers
src/weewx_evo/aggregate.py
src/weewx_evo/obstypes.py
-->
```

Daraus baut `tools/docsindex.py` den [Index](Index) und den
[API-Index](API-Index) — und markiert die Seiten, deren Code sich seit der
letzten Überarbeitung geändert hat.

```bash
python tools/docsindex.py            # Index und API-Index neu schreiben
python tools/docsindex.py --check    # Exit 1, wenn eine Seite hinterherhinkt
```

Wer Code ändert, sieht mit `--check`, welche Seite fällig ist. Wer eine Seite
überarbeitet, lässt danach `docsindex.py` laufen, damit die Markierung
verschwindet.

**Neue Datei angelegt?** `--check` meldet sie als nicht abgedeckt. Entweder in
den `covers`-Block einer bestehenden Seite oder in eine neue Seite.

## GitHub-Kommunikation

Für Issue-Bodies, PR-Beschreibungen, Review-Antworten und Commit-Messages gilt
der Schreibstil aus dem Skill `github-writing`: kurze Sätze, keine Em-Dashes,
nicht defensiv, keine erfundenen Fragen.

Sag, was ist. Frag, was du wissen willst. Hör auf.

<!-- covers
CLAUDE.md
.gitignore
-->

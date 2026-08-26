# Die Archiv-Datenbank

`db/archive.py`, `db/schema.py`, `db/wview.py`.

Alles hier ist so geschrieben, dass WeeWX 5 die Datei danach wieder aufnehmen
kann, ohne zu merken, dass jemand anders darin war.

## Die drei Regeln

1. **Spalten kommen aus der Datei, nie aus einer Liste in diesem Code.** Eine
   Anlage mit Sensoren, von denen wir nie gehört haben, behält sie.
2. **Messwerte, für die die Datenbank keine Spalte hat, werden fallen gelassen,
   nicht angelegt.** Eine Spalte anzulegen ändert das Schema, und das ist eine
   Entscheidung, die ein Mensch trifft — die falsche mischt zwei Sensoren in
   eine Spalte, die danach niemand mehr trennt.
3. **Ein weggefallener Messwert wird gemeldet**, einmal je Feld.

## `db/schema.py` — das Schema aus der Datei lesen

WeeWX liefert Schemadateien aus, aber die setzen nur eine **neue** Datenbank
auf. Danach lebt das Schema in der Datei: Anlagen fügen Spalten für ihre eigenen
Sensoren hinzu, und eine Erweiterung kann jederzeit mehr hinzufügen. Alles, was
eine echte Anlage liest, muss die Datei fragen, nicht die ausgelieferte Liste.

```python
schema = db.schema.read(conn, table_name="archive")
```

```python
@dataclass
class Schema:
    table_name: str
    columns: tuple[str, ...]          # die Spalten der archive-Tabelle
    day_types: dict[str, str]         # obs_type -> scalar | vector
    metadata: dict[str, str]
```

| | |
|---|---|
| `version()` | Die Version der Tagesstatistiken. `4.0` ist aktuell |
| `has_column(name)` | |

`DAY_COLUMNS` sagt, welche Spalten eine `archive_day_*`-Tabelle hat, je nachdem
ob sie skalar oder vektoriell ist. → [Daily-Summaries](Daily-Summaries)

### Die Versionsprüfung

`ArchiveStore._check_version()` **verweigert** eine Datenbank, deren
Tagesstatistiken bekannt fehlerhafte Gewichte tragen:

- WeeWX 4.2.0 las Version-2-Summen als Version 1.
- Die Reparatur in 4.3.0 ließ `dirsumtime` ungewichtet.

Beides ist behebbar, aber von WeeWX, nicht von hier: `weectl database
rebuild-daily`. Eine solche Datei stillschweigend weiterzuschreiben hieße,
falsche Gewichte mit richtigen zu mischen.

## `db/wview.py` — das Startschema

Das Schema, mit dem WeeWX eine neue Datenbank aufsetzt, generiert aus
`weewx/schemas/wview_extended.py` (WeeWX 5.5.0), 113 Beobachtungsspalten.

Es wird **nur** benutzt, um eine Datenbank anzulegen, die noch nicht existiert.
Sobald eine Datei da ist, kommt ihr Schema aus der Datei.

## `ArchiveStore`

```python
with ArchiveStore("data/weewx.sdb", table_name="archive",
                  policy=DEFAULT_POLICY, create=True) as store:
    store.add_record(record)
```

### Lesen

| Methode | Bedeutung |
|---|---|
| `last_timestamp()` | |
| `count()` | |
| `exists(ts)` | |
| `record(ts)` | Ein Satz |
| `days()` | Jeder Archivtag mit Sätzen, in Reihenfolge |
| `get_meta(name)` | Aus der `archive_day__metadata`-Tabelle |

### Schreiben

| Methode | Bedeutung |
|---|---|
| `add_record(record, replace=False, update_daily=True)` | Einen Satz schreiben und in die Tagesstatistiken einfalten. `False`, wenn schon einer für diesen Zeitstempel da war |
| `add_records(records, replace=False)` | Viele Sätze, wobei die Tagesstatistiken **je Tag einmal** angefasst werden |
| `set_meta(name, value)` | |

`add_records` ist der Grund, warum ein Aufholen über Monate erträglich ist:
WeeWX liest und schreibt sämtliche Tagesstatistik-Tabellen eines Tages für
**jeden einzelnen** Satz neu. Bei einem Satz alle fünf Minuten fällt das nicht
auf; bei einem Catch-up über ein Jahr schon.

`set_meta` ist auch der Ort, an dem Treiber ihren Zustand ablegen: weewx-ecowitt
hält seine Konsolenliste hier, unter demselben Schlüssel, unter dem WeeWX sie
schreibt — eine geteilte Datenbank behält dadurch dieselbe Station.
→ [Drivers](Drivers#treiber-zustand)

### Spalten

| Methode | Bedeutung |
|---|---|
| `homeless()` | Felder, die mangels Spalte fallen gelassen wurden, und wie oft — seit Prozessstart |
| `add_column(name, sql_type="REAL")` | Einem Messwert einen Platz geben. `False`, wenn er schon einen hat |

`_note_homeless()` sagt **einmal je Feld**, dass ein Messwert nirgendwo hin kann.
Einmal, nicht bei jedem Paket: ein Log, das alle acht Sekunden dieselbe Zeile
schreibt, wird zu einem Log, das niemand liest.

WeeWX liest sein Schema aus der Datei, eine hier angelegte Spalte nimmt es also
von selbst auf. **Vorher sichern.**

```bash
weewx-evo columns          # was fehlt
weewx-evo columns --add    # anlegen
```

### Tagesstatistiken

| Methode | Bedeutung |
|---|---|
| `_apply_daily(record)` | Einen Satz in seinen Tag einfalten |
| `_unapply_daily(record)` | Seinen Beitrag wieder herausnehmen |
| `_load_day(sod, unit_system)` | Der Akkumulator eines Tages, mit jedem Typ vorbereitet, den die Datenbank kennt |
| `_store_day(sod, accum)` | |
| `rebuild_day(sod)` | Einen Tag aus der Archivtabelle neu rechnen |

**`_unapply_daily` nimmt nur die Summen heraus.** Extreme sind nicht umkehrbar —
ein Maximum erinnert sich nicht daran, was der zweithöchste Wert war. Wer
Extreme korrigieren will, braucht `rebuild_day`.

`_load_day` bereitet Typen ohne gespeicherte Zeile **leer** vor, statt sie
wegzulassen. Das ist Absicht: WeeWX schreibt für jede Größe eine Zeile, die es
kennt, und eine fehlende Zeile wäre ein Unterschied, den WeeWX bemerken würde.

`rebuild_day` ist, was eine Korrektur möglich macht — und was jedes LOOP-Extrem
dieses Tages stumpf macht, weil die Pakete nicht mehr eingerechnet werden. Der
Archiver schärft danach aus der Live-Tabelle nach, soweit sie reicht.
→ [Archiver](Archiver), [Daily-Summaries](Daily-Summaries)

## Prüfen, dass nichts verrutscht

```bash
python tools/difftest.py reference/weewx.sdb    # die Arithmetik
python tools/roundtrip.py reference/weewx.sdb   # das Schreiben
```

`roundtrip.py` nimmt eine Kopie einer echten Datenbank, löscht die letzten N
Tage daraus — Archivsätze und Tagesstatistiken — und schreibt sie über den
normalen Schreibpfad zurück, Satz für Satz, genau wie der Archiver es bei einem
Catch-up täte. Verglichen wird danach jede Zeile jeder Tabelle.

→ [Testing](Testing)

<!-- covers
src/weewx_evo/db/archive.py
src/weewx_evo/db/schema.py
src/weewx_evo/db/wview.py
-->

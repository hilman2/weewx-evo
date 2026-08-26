# Treiber: Ecowitt

`ingest/plugins/ecowitt/`. Vollständig aus
[weewx-ecowitt](https://github.com/hilman2/weewx-ecowitt) übernommen, samt
seiner 59 Tests. Version `0.3.1`.

Nur `driver.py` ist neu — das ist das Stück, das WeeWX kannte und jetzt
weewx-evo kennt. Alles andere ist unverändert.

> **Fixes sollten zwischen beiden Repos wandern können.** Halte die Abweichung
> klein und die Testdateien unverändert.

## Die Dateien

| Datei | Zeilen | Was |
|---|---|---|
| `catalog.py` | 1074 | Was die Hardware sendet und wohin es in WeeWX gehört. **Generiert, nicht von Hand editieren** |
| `protocol.py` | 165 | Aus dem Gesendeten benannte Messwerte machen. Rein: Text rein, Dict raus |
| `mapping.py` | 207 | Katalog, eigene Abbildung und Inferenz treffen sich hier |
| `infer.py` | 200 | Was mit einem Feld geschieht, das niemand abgebildet hat |
| `consoles.py` | 215 | Welchen Konsolen dieser Treiber antwortet |
| `columns.py` | 110 | Welche Datenbankspalten eine Station wirklich braucht |
| `report.py` | 69 | Einen Bericht dort hinterlassen, wo ihn jemand findet |
| `driver.py` | 384 | Das weewx-evo-Ende. Bewusst dünn |
| `__main__.py` | 174 | Einmal lauschen und sagen, was die Hardware sendet |

## `protocol.py` — zwei Protokolle, eine Funktion

Ecowitt-Gateways sprechen zwei Protokolle, und beide landen hier:

- **Ecowitt POST** — ein urlencodierter Formularkörper
- **Wunderground GET** — dieselbe Form im Query-String

Ein urlencodierter Body und ein Query-String sind dasselbe, also reicht eine
Funktion.

| Funktion | Bedeutung |
|---|---|
| `parse(text)` | In rohe Name/Wert-Paare zerlegen, in Ankunftsreihenfolge |
| `device_time(raw, now, max_behind, max_ahead)` | Der Zeitstempel des Geräts, oder `None` |
| `numbers(raw)` | `(readings, text)` — was als Zahl lesbar war und was nicht |
| `redact(text)` | Die Werte ersetzen, die eine Station identifizieren |
| `station_id(text)` | Was die Konsole identifiziert, ohne den Rest zu parsen |

Alles hier ist **rein**: Text rein, Dictionary raus, keine Sockets, keine Uhr,
keine Konfiguration. Das ist, was die Feldarbeit von einer gespeicherten
Aufzeichnung aus testbar macht.

### Die Uhr der Konsole

`MAX_BEHIND = 3600`, `MAX_AHEAD = 60`.

Konsolen liegen häufig falsch, manchmal um Jahre, und ein Satz, der auf 2015
gestempelt ist, ist schlimmer als gar kein Satz. Ein Zeitstempel, der bloß
verspätet ist, ist dagegen genau der Fall, für den es die Live-Tabelle gibt.
Darum die zwei Grenzen und nicht eine.

Es gibt keine Messwerte aus der Zukunft, `max_ahead` deckt also nur Drift
zwischen zwei ungefähr richtigen Uhren ab.

### Redaktion

`SECRETS = ("PASSKEY", "ID", "PASSWORD", "key", "stationkey")`

Eine Nutzlast landet früher oder später in einem Issue-Tracker, und der PASSKEY
ist, woran Ecowitts Server eine Station erkennen. Alles andere darin sind
Messwerte.

## `catalog.py` — der Feldkatalog

Generiert von `tools/import_catalog.py` aus dem `ecowittcustom`-Treiber von
Werner Krenn, der selbst vom `interceptor`-Treiber von Matthew Wall abstammt.
Beide GPLv3, dieser also auch.

> **Nicht von Hand editieren.** Stattdessen das Werkzeug erneut laufen lassen,
> damit das nächste Update stromaufwärts eine Änderung an einer Datei bleibt.

| Konstante | Was |
|---|---|
| `FIELDS` | Rohname → WeeWX-Feld |
| `GROUPS` | WeeWX-Feld → Einheitengruppe |
| `CHANNELS` | Welche Sensorfamilie wie viele Kanäle hat |
| `PLACEMENT_UNKNOWN` | Felder, bei denen der Name mehr behauptet als die Hardware weiß |
| `CONTESTED` | Felder, über die zwei Treiber uneinig sind |
| `CONTESTED_WITH` | Mit wem — `ecowittcustom` |

### `PLACEMENT_UNKNOWN`

Ein WN34 meldet auf `tf_chN`, ob es eine Sonde in einem Beet oder eine Leitung
in einem Pool ist, und der Katalog muss es irgendwie nennen. Wer es installiert
hat, ist der Einzige, der es weiß — also sagt der Treiber es und rät nicht.

## `infer.py` — unbekannte Felder

Ecowitt bringt neue Sensoren schneller heraus, als Treiber aktualisiert werden,
und das übliche Ergebnis ist, dass die Messwerte ankommen und weggeworfen
werden. Ein HP2561 sendet `tf_ch1`, `lightning_num` und sechs `soil_ec_*`-Felder,
und ein Treiber, der sie nicht kennt, loggt „unrecognized parameter".

Zwei Dinge lassen sich über ein unbekanntes Feld sagen:

1. **Es setzt eine bekannte Serie fort.** Der Katalog kennt `temp1` bis `temp8`;
   `temp9` gehört sichtbar dazu. `_learn_series()` findet diese Familien im
   Katalog selbst: ein Stamm und ein Suffix, deren Mitglieder alle auf Ziele mit
   einem gemeinsamen Stamm und Suffix zeigen, mit gleichbleibendem Index-Offset.
2. **Sein Name sagt etwas.** `RULES` ist die Liste: `rssi$` → `group_db`,
   `_sig$` → `group_count`, `batt` → `group_count`, `_time$` → `group_time`.

```python
@dataclass
class Guess:
    raw: str      # der Name der Hardware
    field: str    # das WeeWX-Feld
    group: str    # die Einheitengruppe
    unit: str
    certain: bool
    why: str
```

`report(guesses)` rendert sie als das, was ein Mensch braucht, um zu handeln.

### Die drei Modi

| `infer_unknown` | Verhalten |
|---|---|
| `off` | Fallen lassen |
| `series` | **Default.** Nehmen, wenn sie eine bekannte Serie fortsetzen; den Rest melden |
| `all` | Alles nehmen, was benennbar ist |

`series` ist die vernünftige Vorgabe: ein Kanal, den die Hardware dazubekommt,
braucht kein Release, und was bloß am Namen erkennbar ist, wird gemeldet statt
geraten. **Ein Messwert in der falschen Spalte lässt sich danach nicht wieder
heraustrennen.**

## `mapping.py` — wo alles zusammenkommt

`Mapper.to_packet(text, now)` gibt `(packet, guesses)` zurück. Das Paket ist
fertig für WeeWX bis auf sein Einheitensystem, das der Aufrufer setzt — das ist
eine Entscheidung über den ganzen Treiber, nicht über einen Upload.

Das Modul hält sich frei von WeeWX-Importen, damit es mit nichts als einer
aufgezeichneten Nutzlast testbar ist: die Einheitengruppen, die es registriert
haben will, kommen als **Daten** zurück, und der Treiber registriert sie.

`_check_shared_channels()` warnt, wenn zwei Sensoren doch dasselbe Feld
beschreiben. Ein WH51 und ein WH52 sind mit je sechzehn Kanälen dokumentiert,
aber die Kompatibilitätstabelle der Konsole gibt ihnen einen gemeinsamen
Satz — `SHARED_CHANNELS = [("soilmoisture", "soil_ec_hum")]`.

`_say_undecided()` sagt **einmal**, dass ein Feld auf eine Entscheidung wartet,
und was sie erledigt.

## `consoles.py` — welchen Konsolen geantwortet wird

Ein Listener antwortet allem, was seinen Port erreicht. Wer die Adresse kennt,
kann eine Konsole darauf zeigen lassen, und Ecowitt-Hardware kündigt sich mit
einem PASSKEY an, der aus ihrer MAC-Adresse abgeleitet ist.

**Zwei Konsolen nummerieren ihre Kanäle beide ab eins.** Eine zweite, die in
dieselben Felder schreibt, würde zwei Sensoren in eine Spalte mischen, und
danach kann nichts sie mehr trennen.

`Store` liest und schreibt die Liste. **Die Datenbank wird zuerst gefragt und
zuerst geschrieben**; die Datei (`ecowitt-consoles.txt`) ist der Fallback, für
Tests und wenn der Treiber direkt läuft.

Der Schlüssel in der Metadaten-Tabelle ist `ecowitt_consoles` — **derselbe, den
WeeWX benutzt**. Eine geteilte Datenbank behält dadurch dieselbe Station, egal
welches der beiden Systeme sie gerade aufzeichnet.

`_StateMetadata` lässt einen weewx-evo-`State` wie einen WeeWX-Manager aussehen,
damit `Store` unverändert bleiben kann. Der Zustand ist `get`/`set`/`delete` auf
Strings und sonst nichts — es gibt von dort keinen Weg zum Archiv.
→ [Drivers](Drivers#treiber-zustand)

`path_for()` legt die Fallback-Datei **neben die Datenbank**: das ist ein
Verzeichnis, in das der Dienst als er selbst schreibt, und das, was Leute
sichern. Bei einer Paketinstallation gehört das Konfigurationsverzeichnis root.

## `columns.py` — was in die Datenbank passt

Ein Messwert überlebt das Archivintervall nur, wenn die Tabelle eine Spalte für
ihn hat. Das Standardschema hat 113, Ecowitt-Hardware kann das Vierfache füllen.

Zwei Wege, damit umzugehen. Ein Schema mit jedem denkbaren Feld ausliefern — was
die Alternativen tun, und was vierhundert Spalten für die zwölf Sensoren
bedeutet, die jemand tatsächlich hat. Oder sagen, was fehlt, und den Menschen
entscheiden lassen.

| Funktion | Bedeutung |
|---|---|
| `schema_fields()` | Was das Standardschema schon hat |
| `missing(packet, groups, known)` | Welche Spalten ein Paket braucht und die Datenbank nicht hat |
| `commands(wanted, config)` | Als `weectl`-Kommandos — unverändert aus dem WeeWX-Bau, weil eine Datenbank oft geteilt wird |
| `evo_commands(wanted, archive)` | Dasselbe für weewx-evo |
| `occupied(archive)` | `{Feld: (Anzahl, letzter Zeitstempel)}` für Spalten, die Daten halten |

**`occupied()` ist das, was zwischen einer Treiberänderung und einer ruinierten
Messreihe steht.** Hält ein Feld, in das dieser Treiber schreiben will, schon
Historie, dann kam die von woanders — und zwei Quellen in einer Spalte sind
danach nicht mehr trennbar.

## `driver.py` — das weewx-evo-Ende

Bewusst dünn, genauso wie `driver.py` im WeeWX-Bau dünn ist. Der Socket gehört
dem Kern-Listener, das Protokoll `protocol.py`, die Feldnamen `catalog.py`, die
Konsolenliste `consoles.py`.

```python
ECOWITT_RESPONSE = (b'{"errcode":"0","errmsg":"ok"}', "application/json")
ALIASES = ("wunderground",)
```

| Methode | Bedeutung |
|---|---|
| `packets(body, meta)` | Die Schnittstelle |
| `options()` | Die Einstellungen → [Settings-Reference](Settings-Reference#treiber-ecowitt) |
| `redact(raw)` | Der Upload mit ersetztem PASSKEY |
| `status()` | |
| `unit_groups()` | Welche Gruppe zu welchem Feld gehört — die des Katalogs plus was die Mapper seither gelernt haben |
| `missing_columns(known)` | Was diese Station braucht und die Datenbank nicht hat |
| `hardware_name()` | |

### Adoption

`_adopt()` merkt sich die erste je gehörte Konsole und antwortet ihr von da an.
`_suggest_passkey()` weist dann auf die Einstellung hin, die nicht davon
abhängt, dass eine Datei überlebt: eine kopierte Datenbank, eine neu aufgesetzte
Maschine oder ein Verzeichnis, das niemand gesichert hat, lässt sie zurück.

`_refuse()` weist eine unbekannte Konsole ab. `_maybe_report()` schreibt beim
**ersten Mal**, dass etwas nicht platziert werden kann, den Upload heraus —
sonst an einen Rohupload zu kommen hieße, die Konsole umzukonfigurieren und ein
Intervall zu warten.

## `__main__.py` — vor dem Verkabeln

```bash
python -m weewx_evo.ingest.plugins.ecowitt --port 8000
```

Wartet auf **einen** Upload und druckt dann:

- was ankam
- was der Treiber nicht platzieren konnte
- die Kommandos, die diesen Messwerten einen Platz gäben
- **welche dieser Felder schon die Historie von jemand anderem halten**

Nichts wird verändert. Vor dem Verkabeln laufen lassen, oder wenn ein Sensor in
den Berichten fehlt.

## Die Tests

59 Tests, unverändert übernommen:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && python -m pytest tests/ecowitt -q'
```

| Datei | Was |
|---|---|
| `test_protocol.py` | Beide Protokolle, Zeitstempel, Redaktion |
| `test_mapping.py` | Katalog, Erweiterungen, Inferenz |
| `test_infer.py` | Serienerkennung und die Namensregeln |
| `test_consoles.py` | Adoption, Ablehnung, Datei und Datenbank |
| `test_columns.py` | Was fehlt, was besetzt ist |
| `test_report.py` | Der Bericht |
| `test_resilience.py` | Was passiert, wenn die Nutzlast Unfug ist |
| `fixtures/hp2561ae_pro.txt` | Eine echte Aufzeichnung |

**Aufzeichnungen sind die einzige ehrliche Prüfung**, weil Konsolen nicht das
senden, was ihre Dokumentation sagt.

<!-- covers
src/weewx_evo/ingest/plugins/ecowitt/__init__.py
src/weewx_evo/ingest/plugins/ecowitt/driver.py
src/weewx_evo/ingest/plugins/ecowitt/protocol.py
src/weewx_evo/ingest/plugins/ecowitt/mapping.py
src/weewx_evo/ingest/plugins/ecowitt/infer.py
src/weewx_evo/ingest/plugins/ecowitt/catalog.py
src/weewx_evo/ingest/plugins/ecowitt/consoles.py
src/weewx_evo/ingest/plugins/ecowitt/columns.py
src/weewx_evo/ingest/plugins/ecowitt/report.py
src/weewx_evo/ingest/plugins/ecowitt/__main__.py
tests/ecowitt/test_protocol.py
tests/ecowitt/test_mapping.py
tests/ecowitt/test_infer.py
tests/ecowitt/test_consoles.py
tests/ecowitt/test_columns.py
tests/ecowitt/test_report.py
tests/ecowitt/test_resilience.py
tests/ecowitt/conftest.py
-->

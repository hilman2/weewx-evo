# Mehrere Quellen

`sources.py`. Mehrere Stationen, eine Messreihe.

## Warum das bei WeeWX schwer ist

WeeWX kennt genau einen `station_type`. Zwei Stationen zu kombinieren heißt dort
also, einen Treiber zu schreiben, der Treiber umschließt —
[weewx-metadriver](https://github.com/tkeffer/weewx-metadriver): Worker-Threads
je Kind, eine gemeinsame Queue, ein `source`-Schlüssel an jedem Paket.

Er funktioniert, und seine Grenzen folgen daraus, **wo** er sitzt. Ein Treiber
führt Pakete zusammen, während sie ankommen, und zu diesem Zeitpunkt ist die
Wahl schon getroffen:

- Nur der primäre Treiber darf Archivsätze liefern.
- Nur seine Uhr wird gelesen.
- Ein abgestürztes Kind bleibt tot.

`tools/multisource.py` prüft genau diese drei Fälle.

## Wie es hier geht

Hier umschließt nichts irgendwas. Jede Quelle liefert selbst ein, ihre Pakete
landen mit ihrem Namen in der Live-Tabelle, und zusammengeführt wird erst **beim
Aufbau des Intervalls** — wenn alle Pakete samt Herkunft vorliegen.

Damit verschiebt sich die Frage von „welcher Treiber hat das Sagen" zu „welcher
Quelle glaube ich für *dieses Feld* in *diesem Intervall*".

```
garten (Ecowitt)  ─┐
dach (Vantage)    ─┼─► live.packet (source, dateTime, data)
weiteres          ─┘        │
                            ▼  beim Bau des Intervalls
                     sources.apply(packets, policy)
                            │
                            ▼
                     ein Archivsatz + provenance
```

## Die Konfiguration

```toml
[sources]
outTemp = "garten, dach"     # der Garten ist die Messreihe
"soil*" = "garten"           # nur der Garten hat Bodensonden
"*"     = "dach, garten"     # alles andere: zuerst das Dach
```

Auch als eigene Datei (`--sources sources.toml`, `WEEWX_EVO_SOURCES`). Eine
Politik für ein Dutzend Felder ist es wert, getrennt von den Einstellungen
gehalten zu werden.

**Regeln werden der Reihe nach geprüft, die erste passende entscheidet.** Also
die spezifischen vor die allgemeinen.

## Das Modell

```python
@dataclass
class Rule:
    pattern: str            # Feldname oder Glob
    order: tuple[str, ...]  # Quellen, beste zuerst

    def matches(self, obs_type: str) -> bool: ...
```

```python
@dataclass
class Policy:
    rules: list[Rule]
    stale_after: int | None
```

| Methode | Bedeutung |
|---|---|
| `Policy.from_config(mapping, stale_after=None)` | Aus dem `[sources]`-Abschnitt |
| `is_empty()` | |
| `order_for(obs_type)` | Die Präferenzliste für ein Feld, oder `None` |
| `choose(obs_type, available)` | Welche der Quellen, die dieses Feld *tatsächlich* hatten, liefern soll |

**`available` ist entscheidend.** Es ist die Menge der Quellen, die das Feld in
*diesem* Intervall getragen haben — nicht die Menge der konfigurierten. Eine
Station, die ausgefallen ist, gewinnt nicht dadurch, dass sie in der Liste
vorne steht.

`stale_after` lässt eine Quelle nach so vielen Sekunden ohne Paket zurückfallen.

## Die Funktionen

| | |
|---|---|
| `sources_by_field(packets)` | Welche Quelle welches Feld getragen hat |
| `apply(packets, policy)` | Die Pakete auf die gewinnende Quelle je Feld eindampfen |
| `replace_data(packet, data)` | Eine Kopie eines Pakets mit anderen Messwerten |

`apply()` gibt die Pakete zurück, deren verlierende Felder entfernt wurden, plus
eine Aufzeichnung, aus welcher Quelle jedes Feld kam. Pakete, denen nichts
bleibt, fallen weg. Das Herkunftsprotokoll landet in `Built.provenance`.
→ [Archiver](Archiver)

## Die Regel gilt je Feld

Nicht je Datensatz. Eine Station, die Temperatur und Regen misst, aber
Schneehöhe nicht messen *kann*, liefert ihre Temperatur und ihren Regen; die
Schneehöhe kommt von dem, der sie hat.

## Gemittelt wird über Quellen nie

Zwei Thermometer mit 19 °C und 21 °C ergeben nirgends 20 °C. Es sind zwei
Messungen zweier Orte, und eine davon zu nehmen ist die einzige ehrliche
Antwort. Wer beide will, gibt der zweiten eine eigene Spalte —
→ [Database-Archive](Database-Archive#spalten).

## Was jede Quelle sein kann

Alles, was in die Live-Tabelle einliefert:

- Ein Treiber im Listener, mit `source` am Paket
- Ein zweiter Listener auf einem anderen Port
- Ein Pull-Treiber über `listener.push()`
- Etwas völlig anderes, das den [JSON-Umschlag](Drivers#der-umschlag--der-einzige-treiber-im-kern)
  auf `/<token>/json/` postet

Der Kern kennt keinen Unterschied zwischen ihnen.

## Prüfen

```bash
python tools/multisource.py
```

Prüft die drei Fälle, die der Metatreiber als seine Grenzen nennt.

<!-- covers
src/weewx_evo/sources.py
tools/multisource.py
-->

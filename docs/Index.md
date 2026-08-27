# Datei-Index

Welche Datei zu welcher Wiki-Seite gehört, und wo die Seite dem Code
hinterherhinkt.

**Erzeugt:** 2026-08-27 10:40 · `python tools/docsindex.py`

Diese Seite wird erzeugt. Von Hand geändert wird sie beim nächsten Lauf
überschrieben — die Zuordnung steht in den `covers`-Blöcken am Ende jeder
Wiki-Seite.

## Legende

| | |
|---|---|
| ✅ | Die Seite ist neuer als jede Datei, die sie abdeckt |
| ⚠️ | Eine abgedeckte Datei wurde **nach** der Seite geändert — ansehen |
| — | Die Seite deckt keine Datei ab (Glossar, Navigation) |

„⚠️" heißt *prüfen*, nicht *falsch*. Wer nachgesehen hat und nichts ändern
musste, hakt es ab:

```bash
python tools/docsindex.py --accept <Seite>.md
```

## Stand

| | |
|---|---|
| Wiki-Seiten | 33 |
| Abgedeckte Dateien | 88 von 140 |
| Seiten zu prüfen | 21 |
| Dateien ohne Seite | 52 |

## Zu prüfen

| Seite | Geändert seit der Seite | Datei zuletzt | Seite zuletzt |
|---|---|---|---|
| ⚠️ [Feeds](Feeds) | `src/weewx_evo/feeds/__init__.py`, `src/weewx_evo/feeds/jsongenerator/__init__.py`, `src/weewx_evo/feeds/diagnostic/__init__.py` (+1) | 2026-08-27 10:35 | 2026-08-26 16:02 |
| ⚠️ [Die Einstellungsseite](Admin-Page) | `tools/adminpage.py`, `src/weewx_evo/admin.py` | 2026-08-27 10:33 | 2026-08-26 16:01 |
| ⚠️ [Abgeleitete Messwerte](Derived-Readings) | `tools/derive_test.py`, `src/weewx_evo/derive.py` | 2026-08-27 10:33 | 2026-08-26 15:46 |
| ⚠️ [Einheiten](Units) | `tools/unitcheck.py`, `src/weewx_evo/units.py` | 2026-08-27 10:33 | 2026-08-26 16:07 |
| ⚠️ [CLI-Referenz](CLI-Reference) | `src/weewx_evo/cli.py` | 2026-08-27 10:33 | 2026-08-26 15:39 |
| ⚠️ [Erste Schritte](Getting-Started) | `README.md` | 2026-08-27 10:33 | 2026-08-26 16:03 |
| ⚠️ [Zeitreihen](Series) | `src/weewx_evo/series.py`, `tools/seriestest.py` | 2026-08-27 10:29 | 2026-08-26 16:06 |
| ⚠️ [Mitarbeiten](Contributing) | `CLAUDE.md`, `src/weewx_evo/aggregate.py` | 2026-08-26 23:59 | 2026-08-26 15:55 |
| ⚠️ [Konfiguration](Configuration) | `src/weewx_evo/options.py`, `tools/settings_test.py`, `src/weewx_evo/settings.py` (+1) | 2026-08-26 23:56 | 2026-08-26 16:03 |
| ⚠️ [Einstellungen A–Z](Settings-Reference) | `src/weewx_evo/options.py`, `src/weewx_evo/feeds/jsongenerator/__init__.py`, `src/weewx_evo/exports/local.py` (+2) | 2026-08-26 23:56 | 2026-08-26 16:02 |
| ⚠️ [Tagesstatistiken](Daily-Summaries) | `src/weewx_evo/db/daily.py` | 2026-08-26 23:56 | 2026-08-26 15:42 |
| ⚠️ [Diagramme](Plots) | `src/weewx_evo/plots.py`, `src/weewx_evo/adminplots.py` | 2026-08-26 23:56 | 2026-08-26 16:01 |
| ⚠️ [Sonne](Sun) | `tools/suncheck.py`, `src/weewx_evo/sun.py` | 2026-08-26 23:55 | 2026-08-26 15:48 |
| ⚠️ [Archiver](Archiver) | `tools/roundtrip.py`, `src/weewx_evo/archiver.py` | 2026-08-26 23:54 | 2026-08-26 15:41 |
| ⚠️ [Aggregation](Aggregation) | `tools/difftest.py`, `src/weewx_evo/aggregate.py` | 2026-08-26 23:54 | 2026-08-26 15:40 |
| ⚠️ [Listener](Ingest-Listener) | `src/weewx_evo/ingest/statuspage.py`, `src/weewx_evo/ingest/listener.py`, `tools/netaccess_test.py` (+1) | 2026-08-26 23:53 | 2026-08-26 15:43 |
| ⚠️ [Exports](Exports) | `src/weewx_evo/exports/local.py`, `tools/export_test.py`, `src/weewx_evo/exports/runner.py` (+3) | 2026-08-26 23:53 | 2026-08-26 16:04 |
| ⚠️ [Mehrere Quellen](Multiple-Sources) | `src/weewx_evo/sources.py`, `tools/multisource.py` | 2026-08-26 23:47 | 2026-08-26 15:45 |
| ⚠️ [Web-Server](Web-Server) | `tools/web_test.py`, `src/weewx_evo/webserver.py` | 2026-08-26 23:43 | 2026-08-26 16:02 |
| ⚠️ [Sicherheit](Security) | `src/weewx_evo/netaccess.py`, `src/weewx_evo/ratelimit.py` | 2026-08-26 23:43 | 2026-08-26 15:52 |
| ⚠️ [Deployment](Deployment) | `deploy/Dockerfile`, `deploy/compose.yml` | 2026-08-26 20:40 | 2026-08-26 15:55 |

## Seiten

| | Seite | Dateien | Code zuletzt | Seite zuletzt |
|---|---|---|---|---|
| ⚠️ | [Abgeleitete Messwerte](Derived-Readings) | 2 | 2026-08-27 10:33 | 2026-08-26 15:46 |
| ⚠️ | [Aggregation](Aggregation) | 3 | 2026-08-26 23:54 | 2026-08-26 15:40 |
| ✅ | [Architektur](Architecture) | 2 | 2026-08-26 12:01 | 2026-08-26 15:36 |
| ⚠️ | [Archiver](Archiver) | 2 | 2026-08-26 23:54 | 2026-08-26 15:41 |
| ⚠️ | [CLI-Referenz](CLI-Reference) | 1 | 2026-08-27 10:33 | 2026-08-26 15:39 |
| ⚠️ | [Deployment](Deployment) | 3 | 2026-08-26 20:40 | 2026-08-26 15:55 |
| ⚠️ | [Diagramme](Plots) | 2 | 2026-08-26 23:56 | 2026-08-26 16:01 |
| ✅ | [Die Archiv-Datenbank](Database-Archive) | 3 | 2026-08-26 23:53 | 2026-08-27 10:33 |
| ⚠️ | [Die Einstellungsseite](Admin-Page) | 2 | 2026-08-27 10:33 | 2026-08-26 16:01 |
| ✅ | [Die Live-Datenbank](Database-Live) | 1 | 2026-08-26 12:25 | 2026-08-26 15:41 |
| ⚠️ | [Einheiten](Units) | 2 | 2026-08-27 10:33 | 2026-08-26 16:07 |
| ⚠️ | [Einstellungen A–Z](Settings-Reference) | 6 | 2026-08-26 23:56 | 2026-08-26 16:02 |
| ⚠️ | [Erste Schritte](Getting-Started) | 1 | 2026-08-27 10:33 | 2026-08-26 16:03 |
| ⚠️ | [Exports](Exports) | 7 | 2026-08-26 23:53 | 2026-08-26 16:04 |
| ⚠️ | [Feeds](Feeds) | 5 | 2026-08-27 10:35 | 2026-08-26 16:02 |
| — | [Glossar](Glossary) | — | — | 2026-08-26 15:56 |
| ⚠️ | [Konfiguration](Configuration) | 4 | 2026-08-26 23:56 | 2026-08-26 16:03 |
| ⚠️ | [Listener](Ingest-Listener) | 4 | 2026-08-26 23:53 | 2026-08-26 15:43 |
| ⚠️ | [Mehrere Quellen](Multiple-Sources) | 2 | 2026-08-26 23:47 | 2026-08-26 15:45 |
| ⚠️ | [Mitarbeiten](Contributing) | 4 | 2026-08-26 23:59 | 2026-08-26 15:55 |
| — | [MQTT](MQTT) | — | — | 2026-08-27 10:39 |
| ⚠️ | [Sicherheit](Security) | 2 | 2026-08-26 23:43 | 2026-08-26 15:52 |
| ⚠️ | [Sonne](Sun) | 2 | 2026-08-26 23:55 | 2026-08-26 15:48 |
| ⚠️ | [Tagesstatistiken](Daily-Summaries) | 1 | 2026-08-26 23:56 | 2026-08-26 15:42 |
| ✅ | [Testing](Testing) | 17 | 2026-08-27 10:33 | 2026-08-27 10:40 |
| ✅ | [Treiber](Drivers) | 7 | 2026-08-26 23:56 | 2026-08-27 10:33 |
| ✅ | [Treiber: Ecowitt](Driver-Ecowitt) | 18 | 2026-08-26 23:43 | 2026-08-27 10:33 |
| — | [Uploads](Uploads) | — | — | 2026-08-27 10:38 |
| — | [Vorhersage](Forecast) | — | — | 2026-08-27 10:40 |
| ⚠️ | [Web-Server](Web-Server) | 2 | 2026-08-26 23:43 | 2026-08-26 16:02 |
| ✅ | [weewx-evo](Home) | 7 | 2026-08-27 10:33 | 2026-08-27 10:40 |
| ✅ | [WeeWX-Kompatibilität](WeeWX-Compatibility) | 2 | 2026-08-26 23:53 | 2026-08-27 10:40 |
| ⚠️ | [Zeitreihen](Series) | 2 | 2026-08-27 10:29 | 2026-08-26 16:06 |

## Dateien

| Datei | Zeilen | Wiki-Seite | Zuletzt geändert |
|---|---|---|---|
| `src/weewx_evo/__init__.py` | 8 | [Architektur](Architecture) · [weewx-evo](Home) | 2026-08-26 10:53 |
| `src/weewx_evo/admin.py` | 1756 | ⚠️ [Die Einstellungsseite](Admin-Page) | 2026-08-27 10:33 |
| `src/weewx_evo/adminplots.py` | 622 | ⚠️ [Diagramme](Plots) | 2026-08-26 23:54 |
| `src/weewx_evo/aggregate.py` | 497 | ⚠️ [Aggregation](Aggregation) · [Mitarbeiten](Contributing) | 2026-08-26 23:43 |
| `src/weewx_evo/archiver.py` | 281 | ⚠️ [Archiver](Archiver) | 2026-08-26 23:15 |
| `src/weewx_evo/chartdata.py` | 366 | **keine** | 2026-08-26 23:45 |
| `src/weewx_evo/cli.py` | 2621 | ⚠️ [CLI-Referenz](CLI-Reference) | 2026-08-27 10:33 |
| `src/weewx_evo/config.py` | 243 | ⚠️ [Konfiguration](Configuration) | 2026-08-26 23:47 |
| `src/weewx_evo/db/__init__.py` | 0 | [weewx-evo](Home) | 2026-08-26 10:58 |
| `src/weewx_evo/db/archive.py` | 409 | [Die Archiv-Datenbank](Database-Archive) | 2026-08-26 23:45 |
| `src/weewx_evo/db/daily.py` | 116 | ⚠️ [Tagesstatistiken](Daily-Summaries) | 2026-08-26 23:56 |
| `src/weewx_evo/db/live.py` | 352 | [Die Live-Datenbank](Database-Live) | 2026-08-26 12:25 |
| `src/weewx_evo/db/schema.py` | 86 | [Die Archiv-Datenbank](Database-Archive) | 2026-08-26 10:57 |
| `src/weewx_evo/db/wview.py` | 137 | [Die Archiv-Datenbank](Database-Archive) · [WeeWX-Kompatibilität](WeeWX-Compatibility) | 2026-08-26 23:53 |
| `src/weewx_evo/derive.py` | 744 | ⚠️ [Abgeleitete Messwerte](Derived-Readings) | 2026-08-27 10:33 |
| `src/weewx_evo/exports/__init__.py` | 289 | ⚠️ [Exports](Exports) | 2026-08-26 18:55 |
| `src/weewx_evo/exports/ftp.py` | 355 | ⚠️ [Exports](Exports) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 19:39 |
| `src/weewx_evo/exports/local.py` | 366 | ⚠️ [Exports](Exports) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 23:53 |
| `src/weewx_evo/exports/rsync.py` | 313 | ⚠️ [Exports](Exports) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 16:14 |
| `src/weewx_evo/exports/runner.py` | 280 | ⚠️ [Exports](Exports) | 2026-08-26 23:43 |
| `src/weewx_evo/exports/tracker.py` | 165 | [Exports](Exports) | 2026-08-26 13:31 |
| `src/weewx_evo/feedrunner.py` | 156 | ⚠️ [Feeds](Feeds) | 2026-08-26 23:43 |
| `src/weewx_evo/feeds/__init__.py` | 203 | ⚠️ [Feeds](Feeds) | 2026-08-27 10:35 |
| `src/weewx_evo/feeds/cheetah/__init__.py` | 1334 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/feeds/diagnostic/__init__.py` | 551 | ⚠️ [Feeds](Feeds) | 2026-08-26 23:53 |
| `src/weewx_evo/feeds/diagnostic/vendor/LICENSE` | 21 | [Feeds](Feeds) | 2026-08-26 15:12 |
| `src/weewx_evo/feeds/imagegenerator/__init__.py` | 728 | **keine** | 2026-08-26 23:47 |
| `src/weewx_evo/feeds/imagegenerator/canvas.py` | 410 | **keine** | 2026-08-26 23:47 |
| `src/weewx_evo/feeds/imagegenerator/theme.py` | 225 | **keine** | 2026-08-26 23:56 |
| `src/weewx_evo/feeds/jsongenerator/__init__.py` | 527 | ⚠️ [Feeds](Feeds) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 23:54 |
| `src/weewx_evo/feeds/realtime/__init__.py` | 273 | **keine** | 2026-08-27 10:35 |
| `src/weewx_evo/forecast/__init__.py` | 370 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/codes.py` | 110 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/dwd.py` | 487 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/meteoalarm.py` | 267 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/nws.py` | 308 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/openmeteo.py` | 282 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/runner.py` | 218 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/store.py` | 297 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/tags.py` | 394 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/ingest/__init__.py` | 0 | [weewx-evo](Home) | 2026-08-26 11:20 |
| `src/weewx_evo/ingest/drivers.py` | 286 | [Treiber](Drivers) | 2026-08-26 23:43 |
| `src/weewx_evo/ingest/envelope.py` | 49 | [Treiber](Drivers) | 2026-08-26 11:39 |
| `src/weewx_evo/ingest/listener.py` | 437 | ⚠️ [Listener](Ingest-Listener) | 2026-08-26 23:51 |
| `src/weewx_evo/ingest/parsers.py` | 133 | [Treiber](Drivers) | 2026-08-26 11:23 |
| `src/weewx_evo/ingest/plugins/__init__.py` | 71 | [Treiber](Drivers) | 2026-08-26 11:50 |
| `src/weewx_evo/ingest/plugins/ecowitt/__init__.py` | 8 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/__main__.py` | 174 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/catalog.py` | 1074 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/columns.py` | 110 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:52 |
| `src/weewx_evo/ingest/plugins/ecowitt/consoles.py` | 215 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:57 |
| `src/weewx_evo/ingest/plugins/ecowitt/driver.py` | 384 | [Treiber: Ecowitt](Driver-Ecowitt) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 12:43 |
| `src/weewx_evo/ingest/plugins/ecowitt/infer.py` | 200 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `src/weewx_evo/ingest/plugins/ecowitt/mapping.py` | 207 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/protocol.py` | 164 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `src/weewx_evo/ingest/plugins/ecowitt/report.py` | 69 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/state.py` | 170 | [Treiber](Drivers) | 2026-08-26 12:00 |
| `src/weewx_evo/ingest/statuspage.py` | 471 | ⚠️ [Listener](Ingest-Listener) | 2026-08-26 23:53 |
| `src/weewx_evo/ingest/userdrivers.py` | 321 | [Treiber](Drivers) | 2026-08-26 23:56 |
| `src/weewx_evo/lang/de.toml` | 128 | **keine** | 2026-08-27 01:05 |
| `src/weewx_evo/language.py` | 282 | **keine** | 2026-08-27 01:31 |
| `src/weewx_evo/moon.py` | 569 | **keine** | 2026-08-26 20:42 |
| `src/weewx_evo/mqtt.py` | 444 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/netaccess.py` | 123 | ⚠️ [Sicherheit](Security) | 2026-08-26 23:43 |
| `src/weewx_evo/obstypes.py` | 80 | [Aggregation](Aggregation) · [Mitarbeiten](Contributing) | 2026-08-26 10:54 |
| `src/weewx_evo/options.py` | 767 | ⚠️ [Konfiguration](Configuration) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 23:56 |
| `src/weewx_evo/planets.py` | 625 | **keine** | 2026-08-26 23:56 |
| `src/weewx_evo/plots.py` | 805 | ⚠️ [Diagramme](Plots) | 2026-08-26 23:56 |
| `src/weewx_evo/ratelimit.py` | 205 | ⚠️ [Sicherheit](Security) | 2026-08-26 23:43 |
| `src/weewx_evo/series.py` | 1066 | ⚠️ [Zeitreihen](Series) | 2026-08-27 10:29 |
| `src/weewx_evo/settings.py` | 363 | ⚠️ [Konfiguration](Configuration) | 2026-08-26 23:55 |
| `src/weewx_evo/skinkit.py` | 814 | **keine** | 2026-08-27 01:11 |
| `src/weewx_evo/skins/__init__.py` | 26 | **keine** | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/CHANGES.md` | 88 | **keine** | 2026-08-26 23:26 |
| `src/weewx_evo/skins/deck/LICENSE` | 674 | **keine** | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/options.py` | 203 | **keine** | 2026-08-27 01:54 |
| `src/weewx_evo/skins/deck/README.md` | 72 | **keine** | 2026-08-26 23:26 |
| `src/weewx_evo/skins/deck/tags.py` | 3188 | **keine** | 2026-08-27 10:11 |
| `src/weewx_evo/sources.py` | 165 | ⚠️ [Mehrere Quellen](Multiple-Sources) | 2026-08-26 23:47 |
| `src/weewx_evo/sun.py` | 675 | ⚠️ [Sonne](Sun) | 2026-08-26 23:47 |
| `src/weewx_evo/tags.py` | 1758 | **keine** | 2026-08-27 01:07 |
| `src/weewx_evo/units.py` | 1101 | ⚠️ [Einheiten](Units) | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/__init__.py` | 437 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/ambient.py` | 312 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/cwop.py` | 296 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/homeassistant.py` | 181 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/mqtt.py` | 362 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/progress.py` | 87 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/records.py` | 229 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/runner.py` | 342 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/weathercloud.py` | 164 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/windy.py` | 155 | **keine** | 2026-08-27 10:33 |
| `src/weewx_evo/vsop87.py` | 2381 | **keine** | 2026-08-26 23:48 |
| `src/weewx_evo/webserver.py` | 460 | ⚠️ [Web-Server](Web-Server) | 2026-08-26 23:43 |
| `src/weewx_evo/weewxconf.py` | 441 | [WeeWX-Kompatibilität](WeeWX-Compatibility) | 2026-08-26 23:47 |
| `tools/adminpage.py` | 676 | ⚠️ [Die Einstellungsseite](Admin-Page) · [Testing](Testing) | 2026-08-27 10:33 |
| `tools/cheetah_test.py` | 753 | **keine** | 2026-08-27 02:21 |
| `tools/deck_test.py` | 378 | **keine** | 2026-08-27 08:38 |
| `tools/derive_test.py` | 386 | ⚠️ [Abgeleitete Messwerte](Derived-Readings) · [Testing](Testing) | 2026-08-27 10:33 |
| `tools/difftest.py` | 133 | ⚠️ [Aggregation](Aggregation) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/driverinstall.py` | 225 | [Treiber](Drivers) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/export_test.py` | 745 | ⚠️ [Exports](Exports) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/feeds_test.py` | 185 | **keine** | 2026-08-26 23:15 |
| `tools/forecast_test.py` | 686 | **keine** | 2026-08-27 10:33 |
| `tools/image_test.py` | 392 | **keine** | 2026-08-26 23:47 |
| `tools/mooncheck.py` | 208 | **keine** | 2026-08-26 23:43 |
| `tools/mqtt_test.py` | 597 | **keine** | 2026-08-27 10:33 |
| `tools/multisource.py` | 166 | ⚠️ [Mehrere Quellen](Multiple-Sources) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/netaccess_test.py` | 156 | ⚠️ [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/planetcheck.py` | 295 | **keine** | 2026-08-26 23:56 |
| `tools/ratelimit_test.py` | 168 | ⚠️ [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/realtime_test.py` | 201 | **keine** | 2026-08-27 10:37 |
| `tools/roundtrip.py` | 239 | ⚠️ [Archiver](Archiver) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/scaletest.py` | 302 | **keine** | 2026-08-27 10:29 |
| `tools/seriestest.py` | 375 | ⚠️ [Zeitreihen](Series) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/settings_test.py` | 301 | ⚠️ [Konfiguration](Configuration) · [Testing](Testing) | 2026-08-26 23:55 |
| `tools/smoke.py` | 256 | [Testing](Testing) | 2026-08-26 23:43 |
| `tools/suncheck.py` | 243 | ⚠️ [Sonne](Sun) · [Testing](Testing) | 2026-08-26 23:55 |
| `tools/tagcheck.py` | 343 | **keine** | 2026-08-26 23:56 |
| `tools/unitcheck.py` | 217 | ⚠️ [Testing](Testing) · [Einheiten](Units) | 2026-08-27 10:33 |
| `tools/upload_test.py` | 303 | **keine** | 2026-08-27 10:33 |
| `tools/vsop87trim.py` | 282 | **keine** | 2026-08-26 23:48 |
| `tools/web_test.py` | 219 | ⚠️ [Testing](Testing) · [Web-Server](Web-Server) | 2026-08-26 23:43 |
| `tests/ecowitt/conftest.py` | 43 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:51 |
| `tests/ecowitt/fixtures/README.md` | 12 | [Testing](Testing) | 2026-08-26 11:48 |
| `tests/ecowitt/test_columns.py` | 65 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `tests/ecowitt/test_consoles.py` | 284 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `tests/ecowitt/test_infer.py` | 107 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_mapping.py` | 289 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `tests/ecowitt/test_protocol.py` | 124 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_report.py` | 53 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `tests/ecowitt/test_resilience.py` | 115 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `deploy/compose.yml` | 86 | ⚠️ [Deployment](Deployment) | 2026-08-26 16:17 |
| `deploy/Dockerfile` | 56 | ⚠️ [Deployment](Deployment) | 2026-08-26 20:40 |
| `deploy/split.yml` | 75 | [Architektur](Architecture) · [Deployment](Deployment) | 2026-08-26 12:01 |
| `README.md` | 382 | ⚠️ [Erste Schritte](Getting-Started) · [weewx-evo](Home) | 2026-08-27 10:33 |
| `CLAUDE.md` | 725 | ⚠️ [Mitarbeiten](Contributing) · [weewx-evo](Home) | 2026-08-26 23:59 |
| `pyproject.toml` | 134 | [weewx-evo](Home) · [Testing](Testing) | 2026-08-27 10:33 |
| `.gitignore` | 43 | [Mitarbeiten](Contributing) | 2026-08-26 15:38 |
| `LICENSE` | 674 | [weewx-evo](Home) | 2026-08-26 15:37 |

## Ohne Seite

Diese Dateien nennt kein `covers`-Block. Entweder gehören sie in
eine bestehende Seite, oder es fehlt eine.

| Datei | Zuletzt geändert |
|---|---|
| `src/weewx_evo/chartdata.py` | 2026-08-26 23:45 |
| `src/weewx_evo/feeds/cheetah/__init__.py` | 2026-08-27 10:33 |
| `src/weewx_evo/feeds/imagegenerator/__init__.py` | 2026-08-26 23:47 |
| `src/weewx_evo/feeds/imagegenerator/canvas.py` | 2026-08-26 23:47 |
| `src/weewx_evo/feeds/imagegenerator/theme.py` | 2026-08-26 23:56 |
| `src/weewx_evo/feeds/realtime/__init__.py` | 2026-08-27 10:35 |
| `src/weewx_evo/forecast/__init__.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/codes.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/dwd.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/meteoalarm.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/nws.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/openmeteo.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/runner.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/store.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/tags.py` | 2026-08-27 10:33 |
| `src/weewx_evo/lang/de.toml` | 2026-08-27 01:05 |
| `src/weewx_evo/language.py` | 2026-08-27 01:31 |
| `src/weewx_evo/moon.py` | 2026-08-26 20:42 |
| `src/weewx_evo/mqtt.py` | 2026-08-27 10:33 |
| `src/weewx_evo/planets.py` | 2026-08-26 23:56 |
| `src/weewx_evo/skinkit.py` | 2026-08-27 01:11 |
| `src/weewx_evo/skins/__init__.py` | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/CHANGES.md` | 2026-08-26 23:26 |
| `src/weewx_evo/skins/deck/LICENSE` | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/options.py` | 2026-08-27 01:54 |
| `src/weewx_evo/skins/deck/README.md` | 2026-08-26 23:26 |
| `src/weewx_evo/skins/deck/tags.py` | 2026-08-27 10:11 |
| `src/weewx_evo/tags.py` | 2026-08-27 01:07 |
| `src/weewx_evo/uploads/__init__.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/ambient.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/cwop.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/homeassistant.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/mqtt.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/progress.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/records.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/runner.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/weathercloud.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/windy.py` | 2026-08-27 10:33 |
| `src/weewx_evo/vsop87.py` | 2026-08-26 23:48 |
| `tools/cheetah_test.py` | 2026-08-27 02:21 |
| `tools/deck_test.py` | 2026-08-27 08:38 |
| `tools/feeds_test.py` | 2026-08-26 23:15 |
| `tools/forecast_test.py` | 2026-08-27 10:33 |
| `tools/image_test.py` | 2026-08-26 23:47 |
| `tools/mooncheck.py` | 2026-08-26 23:43 |
| `tools/mqtt_test.py` | 2026-08-27 10:33 |
| `tools/planetcheck.py` | 2026-08-26 23:56 |
| `tools/realtime_test.py` | 2026-08-27 10:37 |
| `tools/scaletest.py` | 2026-08-27 10:29 |
| `tools/tagcheck.py` | 2026-08-26 23:56 |
| `tools/upload_test.py` | 2026-08-27 10:33 |
| `tools/vsop87trim.py` | 2026-08-26 23:48 |

---

Erzeugt von `tools/docsindex.py`. Siehe [Mitarbeiten](Contributing).

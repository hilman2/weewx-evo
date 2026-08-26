# Datei-Index

Welche Datei zu welcher Wiki-Seite gehört, und wo die Seite dem Code
hinterherhinkt.

**Erzeugt:** 2026-08-26 15:58 · `python tools/docsindex.py`

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
| Wiki-Seiten | 32 |
| Abgedeckte Dateien | 83 von 87 |
| Seiten zu prüfen | 8 |
| Dateien ohne Seite | 4 |

## Zu prüfen

| Seite | Geändert seit der Seite | Datei zuletzt | Seite zuletzt |
|---|---|---|---|
| ⚠️ [Exports](Exports) | `src/weewx_evo/exports/__init__.py` | 2026-08-26 15:58 | 2026-08-26 15:50 |
| ⚠️ [Konfiguration](Configuration) | `src/weewx_evo/options.py`, `tools/settings_test.py` | 2026-08-26 15:55 | 2026-08-26 15:37 |
| ⚠️ [Feeds](Feeds) | `src/weewx_evo/feeds/__init__.py` | 2026-08-26 15:55 | 2026-08-26 15:49 |
| ⚠️ [Einstellungen A–Z](Settings-Reference) | `src/weewx_evo/options.py` | 2026-08-26 15:55 | 2026-08-26 15:39 |
| ⚠️ [Die Einstellungsseite](Admin-Page) | `tools/adminpage.py`, `src/weewx_evo/admin.py` | 2026-08-26 15:53 | 2026-08-26 15:51 |
| ⚠️ [Diagramme](Plots) | `src/weewx_evo/adminplots.py` | 2026-08-26 15:52 | 2026-08-26 15:48 |
| ⚠️ [Erste Schritte](Getting-Started) | `README.md` | 2026-08-26 15:40 | 2026-08-26 15:36 |
| ⚠️ [weewx-evo](Home) | `README.md`, `pyproject.toml` | 2026-08-26 15:40 | 2026-08-26 15:34 |

## Seiten

| | Seite | Dateien | Code zuletzt | Seite zuletzt |
|---|---|---|---|---|
| — | [_Footer](_Footer) | — | — | 2026-08-26 15:33 |
| — | [_Sidebar](_Sidebar) | — | — | 2026-08-26 15:34 |
| ✅ | [Abgeleitete Messwerte](Derived-Readings) | 2 | 2026-08-26 14:18 | 2026-08-26 15:46 |
| ✅ | [Aggregation](Aggregation) | 3 | 2026-08-26 11:10 | 2026-08-26 15:40 |
| ✅ | [Architektur](Architecture) | 2 | 2026-08-26 12:01 | 2026-08-26 15:36 |
| ✅ | [Archiver](Archiver) | 2 | 2026-08-26 14:09 | 2026-08-26 15:41 |
| ✅ | [CLI-Referenz](CLI-Reference) | 1 | 2026-08-26 15:25 | 2026-08-26 15:39 |
| ✅ | [Deployment](Deployment) | 3 | 2026-08-26 15:38 | 2026-08-26 15:55 |
| ⚠️ | [Diagramme](Plots) | 2 | 2026-08-26 15:52 | 2026-08-26 15:48 |
| ✅ | [Die Archiv-Datenbank](Database-Archive) | 3 | 2026-08-26 11:48 | 2026-08-26 15:42 |
| ⚠️ | [Die Einstellungsseite](Admin-Page) | 2 | 2026-08-26 15:53 | 2026-08-26 15:51 |
| ✅ | [Die Live-Datenbank](Database-Live) | 1 | 2026-08-26 12:25 | 2026-08-26 15:41 |
| ✅ | [Einheiten](Units) | 2 | 2026-08-26 14:48 | 2026-08-26 15:47 |
| ⚠️ | [Einstellungen A–Z](Settings-Reference) | 5 | 2026-08-26 15:55 | 2026-08-26 15:39 |
| ⚠️ | [Erste Schritte](Getting-Started) | 1 | 2026-08-26 15:40 | 2026-08-26 15:36 |
| ⚠️ | [Exports](Exports) | 6 | 2026-08-26 15:58 | 2026-08-26 15:50 |
| ⚠️ | [Feeds](Feeds) | 4 | 2026-08-26 15:55 | 2026-08-26 15:49 |
| — | [Glossar](Glossary) | — | — | 2026-08-26 15:56 |
| ⚠️ | [Konfiguration](Configuration) | 4 | 2026-08-26 15:55 | 2026-08-26 15:37 |
| ✅ | [Listener](Ingest-Listener) | 4 | 2026-08-26 13:10 | 2026-08-26 15:43 |
| ✅ | [Mehrere Quellen](Multiple-Sources) | 2 | 2026-08-26 11:29 | 2026-08-26 15:45 |
| ✅ | [Mitarbeiten](Contributing) | 4 | 2026-08-26 15:38 | 2026-08-26 15:55 |
| ✅ | [Sicherheit](Security) | 2 | 2026-08-26 13:09 | 2026-08-26 15:52 |
| ✅ | [Sonne](Sun) | 2 | 2026-08-26 15:05 | 2026-08-26 15:48 |
| ✅ | [Tagesstatistiken](Daily-Summaries) | 1 | 2026-08-26 10:58 | 2026-08-26 15:42 |
| ✅ | [Testing](Testing) | 17 | 2026-08-26 15:53 | 2026-08-26 15:54 |
| ✅ | [Treiber](Drivers) | 7 | 2026-08-26 15:43 | 2026-08-26 15:44 |
| ✅ | [Treiber: Ecowitt](Driver-Ecowitt) | 18 | 2026-08-26 12:43 | 2026-08-26 15:45 |
| ✅ | [Web-Server](Web-Server) | 2 | 2026-08-26 14:19 | 2026-08-26 15:51 |
| ⚠️ | [weewx-evo](Home) | 4 | 2026-08-26 15:40 | 2026-08-26 15:34 |
| ✅ | [WeeWX-Kompatibilität](WeeWX-Compatibility) | 2 | 2026-08-26 14:52 | 2026-08-26 15:53 |
| ✅ | [Zeitreihen](Series) | 2 | 2026-08-26 14:57 | 2026-08-26 15:47 |

## Dateien

| Datei | Zeilen | Wiki-Seite | Zuletzt geändert |
|---|---|---|---|
| `src/weewx_evo/__init__.py` | 8 | [Architektur](Architecture) · [weewx-evo](Home) | 2026-08-26 10:53 |
| `src/weewx_evo/admin.py` | 1033 | ⚠️ [Die Einstellungsseite](Admin-Page) | 2026-08-26 15:52 |
| `src/weewx_evo/adminplots.py` | 618 | ⚠️ [Diagramme](Plots) | 2026-08-26 15:52 |
| `src/weewx_evo/aggregate.py` | 482 | [Aggregation](Aggregation) · [Mitarbeiten](Contributing) | 2026-08-26 11:10 |
| `src/weewx_evo/archiver.py` | 281 | [Archiver](Archiver) | 2026-08-26 14:09 |
| `src/weewx_evo/cli.py` | 1717 | [CLI-Referenz](CLI-Reference) | 2026-08-26 15:25 |
| `src/weewx_evo/config.py` | 243 | [Konfiguration](Configuration) | 2026-08-26 12:43 |
| `src/weewx_evo/db/__init__.py` | 0 | **keine** | 2026-08-26 10:58 |
| `src/weewx_evo/db/archive.py` | 409 | [Die Archiv-Datenbank](Database-Archive) | 2026-08-26 11:48 |
| `src/weewx_evo/db/daily.py` | 115 | [Tagesstatistiken](Daily-Summaries) | 2026-08-26 10:58 |
| `src/weewx_evo/db/live.py` | 352 | [Die Live-Datenbank](Database-Live) | 2026-08-26 12:25 |
| `src/weewx_evo/db/schema.py` | 86 | [Die Archiv-Datenbank](Database-Archive) | 2026-08-26 10:57 |
| `src/weewx_evo/db/wview.py` | 135 | [Die Archiv-Datenbank](Database-Archive) · [WeeWX-Kompatibilität](WeeWX-Compatibility) | 2026-08-26 11:03 |
| `src/weewx_evo/derive.py` | 577 | [Abgeleitete Messwerte](Derived-Readings) | 2026-08-26 14:18 |
| `src/weewx_evo/exports/__init__.py` | 285 | ⚠️ [Exports](Exports) | 2026-08-26 15:58 |
| `src/weewx_evo/exports/ftp.py` | 341 | [Exports](Exports) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 14:00 |
| `src/weewx_evo/exports/local.py` | 280 | **keine** | 2026-08-26 15:57 |
| `src/weewx_evo/exports/rsync.py` | 306 | [Exports](Exports) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 14:00 |
| `src/weewx_evo/exports/runner.py` | 256 | [Exports](Exports) | 2026-08-26 14:00 |
| `src/weewx_evo/exports/tracker.py` | 165 | [Exports](Exports) | 2026-08-26 13:31 |
| `src/weewx_evo/feedrunner.py` | 132 | [Feeds](Feeds) | 2026-08-26 15:25 |
| `src/weewx_evo/feeds/__init__.py` | 184 | ⚠️ [Feeds](Feeds) | 2026-08-26 15:55 |
| `src/weewx_evo/feeds/diagnostic/__init__.py` | 533 | [Feeds](Feeds) | 2026-08-26 15:17 |
| `src/weewx_evo/feeds/diagnostic/vendor/LICENSE` | 21 | **keine** | 2026-08-26 15:12 |
| `src/weewx_evo/feeds/jsongenerator/__init__.py` | 689 | [Feeds](Feeds) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 15:27 |
| `src/weewx_evo/ingest/__init__.py` | 0 | **keine** | 2026-08-26 11:20 |
| `src/weewx_evo/ingest/drivers.py` | 286 | [Treiber](Drivers) | 2026-08-26 15:43 |
| `src/weewx_evo/ingest/envelope.py` | 49 | [Treiber](Drivers) | 2026-08-26 11:39 |
| `src/weewx_evo/ingest/listener.py` | 437 | [Listener](Ingest-Listener) | 2026-08-26 13:10 |
| `src/weewx_evo/ingest/parsers.py` | 133 | [Treiber](Drivers) | 2026-08-26 11:23 |
| `src/weewx_evo/ingest/plugins/__init__.py` | 71 | [Treiber](Drivers) | 2026-08-26 11:50 |
| `src/weewx_evo/ingest/plugins/ecowitt/__init__.py` | 8 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/__main__.py` | 174 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/catalog.py` | 1074 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/columns.py` | 110 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:52 |
| `src/weewx_evo/ingest/plugins/ecowitt/consoles.py` | 215 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:57 |
| `src/weewx_evo/ingest/plugins/ecowitt/driver.py` | 384 | [Treiber: Ecowitt](Driver-Ecowitt) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 12:43 |
| `src/weewx_evo/ingest/plugins/ecowitt/infer.py` | 200 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/mapping.py` | 207 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/protocol.py` | 165 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/report.py` | 69 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/state.py` | 170 | [Treiber](Drivers) | 2026-08-26 12:00 |
| `src/weewx_evo/ingest/statuspage.py` | 471 | [Listener](Ingest-Listener) | 2026-08-26 12:27 |
| `src/weewx_evo/ingest/userdrivers.py` | 310 | [Treiber](Drivers) | 2026-08-26 12:00 |
| `src/weewx_evo/netaccess.py` | 123 | [Sicherheit](Security) | 2026-08-26 12:57 |
| `src/weewx_evo/obstypes.py` | 80 | [Aggregation](Aggregation) · [Mitarbeiten](Contributing) | 2026-08-26 10:54 |
| `src/weewx_evo/options.py` | 560 | ⚠️ [Konfiguration](Configuration) · [Einstellungen A–Z](Settings-Reference) | 2026-08-26 15:55 |
| `src/weewx_evo/plots.py` | 777 | [Diagramme](Plots) | 2026-08-26 15:45 |
| `src/weewx_evo/ratelimit.py` | 205 | [Sicherheit](Security) | 2026-08-26 13:09 |
| `src/weewx_evo/series.py` | 750 | [Zeitreihen](Series) | 2026-08-26 14:56 |
| `src/weewx_evo/settings.py` | 264 | [Konfiguration](Configuration) | 2026-08-26 13:17 |
| `src/weewx_evo/sources.py` | 165 | [Mehrere Quellen](Multiple-Sources) | 2026-08-26 11:28 |
| `src/weewx_evo/sun.py` | 369 | [Sonne](Sun) | 2026-08-26 15:05 |
| `src/weewx_evo/units.py` | 901 | [Einheiten](Units) | 2026-08-26 14:47 |
| `src/weewx_evo/webserver.py` | 333 | [Web-Server](Web-Server) | 2026-08-26 14:17 |
| `src/weewx_evo/weewxconf.py` | 375 | [WeeWX-Kompatibilität](WeeWX-Compatibility) | 2026-08-26 14:52 |
| `tools/adminpage.py` | 452 | ⚠️ [Die Einstellungsseite](Admin-Page) · [Testing](Testing) | 2026-08-26 15:53 |
| `tools/derive_test.py` | 264 | [Abgeleitete Messwerte](Derived-Readings) · [Testing](Testing) | 2026-08-26 14:16 |
| `tools/difftest.py` | 131 | [Aggregation](Aggregation) · [Testing](Testing) | 2026-08-26 10:58 |
| `tools/driverinstall.py` | 225 | [Treiber](Drivers) · [Testing](Testing) | 2026-08-26 12:01 |
| `tools/export_test.py` | 375 | [Exports](Exports) · [Testing](Testing) | 2026-08-26 14:01 |
| `tools/multisource.py` | 166 | [Mehrere Quellen](Multiple-Sources) · [Testing](Testing) | 2026-08-26 11:29 |
| `tools/netaccess_test.py` | 156 | [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 13:00 |
| `tools/ratelimit_test.py` | 168 | [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 13:09 |
| `tools/roundtrip.py` | 238 | [Archiver](Archiver) · [Testing](Testing) | 2026-08-26 11:15 |
| `tools/seriestest.py` | 365 | [Zeitreihen](Series) · [Testing](Testing) | 2026-08-26 14:57 |
| `tools/settings_test.py` | 186 | ⚠️ [Konfiguration](Configuration) · [Testing](Testing) | 2026-08-26 15:43 |
| `tools/smoke.py` | 247 | [Testing](Testing) | 2026-08-26 12:27 |
| `tools/suncheck.py` | 241 | [Sonne](Sun) · [Testing](Testing) | 2026-08-26 15:05 |
| `tools/unitcheck.py` | 175 | [Testing](Testing) · [Einheiten](Units) | 2026-08-26 14:48 |
| `tools/web_test.py` | 166 | [Testing](Testing) · [Web-Server](Web-Server) | 2026-08-26 14:19 |
| `tests/ecowitt/conftest.py` | 43 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:51 |
| `tests/ecowitt/fixtures/README.md` | 12 | [Testing](Testing) | 2026-08-26 11:48 |
| `tests/ecowitt/test_columns.py` | 65 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_consoles.py` | 283 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_infer.py` | 107 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_mapping.py` | 290 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_protocol.py` | 124 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_report.py` | 52 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_resilience.py` | 114 | [Treiber: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `deploy/Dockerfile` | 30 | [Deployment](Deployment) | 2026-08-26 11:53 |
| `deploy/compose.yml` | 80 | [Deployment](Deployment) | 2026-08-26 15:38 |
| `deploy/split.yml` | 75 | [Architektur](Architecture) · [Deployment](Deployment) | 2026-08-26 12:01 |
| `README.md` | 350 | ⚠️ [Erste Schritte](Getting-Started) · [weewx-evo](Home) | 2026-08-26 15:40 |
| `CLAUDE.md` | 436 | [Mitarbeiten](Contributing) · [weewx-evo](Home) | 2026-08-26 15:28 |
| `pyproject.toml` | 41 | ⚠️ [weewx-evo](Home) · [Testing](Testing) | 2026-08-26 15:37 |
| `.gitignore` | 43 | [Mitarbeiten](Contributing) | 2026-08-26 15:38 |

## Ohne Seite

Diese Dateien nennt kein `covers`-Block. Entweder gehören sie in
eine bestehende Seite, oder es fehlt eine.

| Datei | Zuletzt geändert |
|---|---|
| `src/weewx_evo/db/__init__.py` | 2026-08-26 10:58 |
| `src/weewx_evo/exports/local.py` | 2026-08-26 15:57 |
| `src/weewx_evo/feeds/diagnostic/vendor/LICENSE` | 2026-08-26 15:12 |
| `src/weewx_evo/ingest/__init__.py` | 2026-08-26 11:20 |

---

Erzeugt von `tools/docsindex.py`. Siehe [Mitarbeiten](Contributing).

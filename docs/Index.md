# File index

Which file belongs to which wiki page, and where the page is behind
the code.

**Generated:** 2026-08-27 11:31 · `python tools/docsindex.py`

This page is generated. Edited by hand, it is overwritten on the next
run — the mapping lives in the `covers` blocks at the end of every wiki
page.

## Key

| | |
|---|---|
| ✅ | The page is newer than every file it covers |
| ⚠️ | A covered file was changed **after** the page — worth a look |
| — | The page covers no file (glossary, navigation) |

"⚠️" means *look*, not *wrong*. Anyone who has looked and had nothing
to change ticks it off:

```bash
python tools/docsindex.py --accept <page>.md
```

## Where things stand

| | |
|---|---|
| Wiki pages | 34 |
| Files covered | 88 of 144 |
| Pages to look at | 3 |
| Files with no page | 56 |

## To look at

| Page | Changed since the page | File last | Page last |
|---|---|---|---|
| ⚠️ [CLI reference](CLI-Reference) | `src/weewx_evo/cli.py` | 2026-08-27 11:29 | 2026-08-27 11:15 |
| ⚠️ [Configuration](Configuration) | `src/weewx_evo/options.py` | 2026-08-27 11:29 | 2026-08-27 11:07 |
| ⚠️ [Settings A–Z](Settings-Reference) | `src/weewx_evo/options.py` | 2026-08-27 11:29 | 2026-08-27 11:16 |

## Pages

| | Page | Files | Code last | Page last |
|---|---|---|---|---|
| ✅ | [Aggregation](Aggregation) | 3 | 2026-08-26 23:54 | 2026-08-27 11:02 |
| ✅ | [Architecture](Architecture) | 2 | 2026-08-26 12:01 | 2026-08-27 11:00 |
| ✅ | [Archiver](Archiver) | 2 | 2026-08-26 23:54 | 2026-08-27 11:02 |
| ⚠️ | [CLI reference](CLI-Reference) | 1 | 2026-08-27 11:29 | 2026-08-27 11:15 |
| ⚠️ | [Configuration](Configuration) | 4 | 2026-08-27 11:29 | 2026-08-27 11:07 |
| ✅ | [Contributing](Contributing) | 4 | 2026-08-26 23:59 | 2026-08-27 11:07 |
| ✅ | [Daily summaries](Daily-Summaries) | 1 | 2026-08-26 23:56 | 2026-08-27 11:03 |
| ✅ | [Deployment](Deployment) | 3 | 2026-08-26 20:40 | 2026-08-27 11:08 |
| ✅ | [Derived readings](Derived-Readings) | 2 | 2026-08-27 10:33 | 2026-08-27 11:03 |
| ✅ | [Driver: Ecowitt](Driver-Ecowitt) | 18 | 2026-08-26 23:43 | 2026-08-27 11:14 |
| ✅ | [Drivers](Drivers) | 7 | 2026-08-26 23:56 | 2026-08-27 11:06 |
| ✅ | [Exports](Exports) | 7 | 2026-08-26 23:53 | 2026-08-27 11:11 |
| ✅ | [Feeds](Feeds) | 5 | 2026-08-27 10:35 | 2026-08-27 11:10 |
| — | [Forecast](Forecast) | — | — | 2026-08-27 11:13 |
| ✅ | [Getting started](Getting-Started) | 1 | 2026-08-27 10:55 | 2026-08-27 10:58 |
| — | [Glossary](Glossary) | — | — | 2026-08-27 11:00 |
| ✅ | [Listener](Ingest-Listener) | 4 | 2026-08-26 23:53 | 2026-08-27 11:01 |
| — | [MQTT](MQTT) | — | — | 2026-08-27 11:31 |
| ✅ | [Multiple sources](Multiple-Sources) | 2 | 2026-08-26 23:47 | 2026-08-27 11:01 |
| ✅ | [Plots](Plots) | 2 | 2026-08-26 23:56 | 2026-08-27 11:09 |
| — | [Plugins](Plugins) | — | — | 2026-08-27 11:19 |
| ✅ | [Security](Security) | 2 | 2026-08-26 23:43 | 2026-08-27 11:08 |
| ✅ | [Series](Series) | 2 | 2026-08-27 10:29 | 2026-08-27 11:04 |
| ⚠️ | [Settings A–Z](Settings-Reference) | 6 | 2026-08-27 11:29 | 2026-08-27 11:16 |
| ✅ | [Sun](Sun) | 2 | 2026-08-26 23:55 | 2026-08-27 11:05 |
| ✅ | [Testing](Testing) | 17 | 2026-08-27 10:33 | 2026-08-27 11:31 |
| ✅ | [The archive database](Database-Archive) | 3 | 2026-08-26 23:53 | 2026-08-27 11:03 |
| ✅ | [The live database](Database-Live) | 1 | 2026-08-26 12:25 | 2026-08-27 11:01 |
| ✅ | [The settings page](Admin-Page) | 2 | 2026-08-27 10:33 | 2026-08-27 11:06 |
| ✅ | [Units](Units) | 2 | 2026-08-27 10:33 | 2026-08-27 11:04 |
| — | [Uploads](Uploads) | — | — | 2026-08-27 11:11 |
| ✅ | [Web server](Web-Server) | 2 | 2026-08-26 23:43 | 2026-08-27 11:05 |
| ✅ | [WeeWX compatibility](WeeWX-Compatibility) | 2 | 2026-08-26 23:53 | 2026-08-27 11:15 |
| ✅ | [weewx-evo](Home) | 7 | 2026-08-27 10:55 | 2026-08-27 10:57 |

## Files

| File | Lines | Wiki page | Last changed |
|---|---|---|---|
| `src/weewx_evo/__init__.py` | 8 | [Architecture](Architecture) · [weewx-evo](Home) | 2026-08-26 10:53 |
| `src/weewx_evo/admin.py` | 1756 | [The settings page](Admin-Page) | 2026-08-27 10:33 |
| `src/weewx_evo/adminplots.py` | 622 | [Plots](Plots) | 2026-08-26 23:54 |
| `src/weewx_evo/aggregate.py` | 497 | [Aggregation](Aggregation) · [Contributing](Contributing) | 2026-08-26 23:43 |
| `src/weewx_evo/archiver.py` | 281 | [Archiver](Archiver) | 2026-08-26 23:15 |
| `src/weewx_evo/broker.py` | 696 | **none** | 2026-08-27 11:27 |
| `src/weewx_evo/chartdata.py` | 366 | **none** | 2026-08-26 23:45 |
| `src/weewx_evo/cli.py` | 2648 | ⚠️ [CLI reference](CLI-Reference) | 2026-08-27 11:29 |
| `src/weewx_evo/config.py` | 243 | [Configuration](Configuration) | 2026-08-26 23:47 |
| `src/weewx_evo/db/__init__.py` | 0 | [weewx-evo](Home) | 2026-08-26 10:58 |
| `src/weewx_evo/db/archive.py` | 409 | [The archive database](Database-Archive) | 2026-08-26 23:45 |
| `src/weewx_evo/db/daily.py` | 116 | [Daily summaries](Daily-Summaries) | 2026-08-26 23:56 |
| `src/weewx_evo/db/live.py` | 352 | [The live database](Database-Live) | 2026-08-26 12:25 |
| `src/weewx_evo/db/schema.py` | 86 | [The archive database](Database-Archive) | 2026-08-26 10:57 |
| `src/weewx_evo/db/wview.py` | 137 | [The archive database](Database-Archive) · [WeeWX compatibility](WeeWX-Compatibility) | 2026-08-26 23:53 |
| `src/weewx_evo/derive.py` | 744 | [Derived readings](Derived-Readings) | 2026-08-27 10:33 |
| `src/weewx_evo/exports/__init__.py` | 289 | [Exports](Exports) | 2026-08-26 18:55 |
| `src/weewx_evo/exports/ftp.py` | 355 | [Exports](Exports) · [Settings A–Z](Settings-Reference) | 2026-08-26 19:39 |
| `src/weewx_evo/exports/local.py` | 366 | [Exports](Exports) · [Settings A–Z](Settings-Reference) | 2026-08-26 23:53 |
| `src/weewx_evo/exports/rsync.py` | 313 | [Exports](Exports) · [Settings A–Z](Settings-Reference) | 2026-08-26 16:14 |
| `src/weewx_evo/exports/runner.py` | 280 | [Exports](Exports) | 2026-08-26 23:43 |
| `src/weewx_evo/exports/tracker.py` | 165 | [Exports](Exports) | 2026-08-26 13:31 |
| `src/weewx_evo/feedrunner.py` | 156 | [Feeds](Feeds) | 2026-08-26 23:43 |
| `src/weewx_evo/feeds/__init__.py` | 203 | [Feeds](Feeds) | 2026-08-27 10:35 |
| `src/weewx_evo/feeds/cheetah/__init__.py` | 1497 | **none** | 2026-08-27 11:13 |
| `src/weewx_evo/feeds/diagnostic/__init__.py` | 551 | [Feeds](Feeds) | 2026-08-26 23:53 |
| `src/weewx_evo/feeds/diagnostic/vendor/LICENSE` | 21 | [Feeds](Feeds) | 2026-08-26 15:12 |
| `src/weewx_evo/feeds/imagegenerator/__init__.py` | 728 | **none** | 2026-08-26 23:47 |
| `src/weewx_evo/feeds/imagegenerator/canvas.py` | 410 | **none** | 2026-08-26 23:47 |
| `src/weewx_evo/feeds/imagegenerator/theme.py` | 225 | **none** | 2026-08-26 23:56 |
| `src/weewx_evo/feeds/jsongenerator/__init__.py` | 527 | [Feeds](Feeds) · [Settings A–Z](Settings-Reference) | 2026-08-26 23:54 |
| `src/weewx_evo/feeds/realtime/__init__.py` | 273 | **none** | 2026-08-27 10:35 |
| `src/weewx_evo/forecast/__init__.py` | 370 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/codes.py` | 110 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/dwd.py` | 487 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/meteoalarm.py` | 267 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/nws.py` | 308 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/openmeteo.py` | 282 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/runner.py` | 218 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/store.py` | 297 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/tags.py` | 394 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/ingest/__init__.py` | 0 | [weewx-evo](Home) | 2026-08-26 11:20 |
| `src/weewx_evo/ingest/drivers.py` | 286 | [Drivers](Drivers) | 2026-08-26 23:43 |
| `src/weewx_evo/ingest/envelope.py` | 49 | [Drivers](Drivers) | 2026-08-26 11:39 |
| `src/weewx_evo/ingest/listener.py` | 437 | [Listener](Ingest-Listener) | 2026-08-26 23:51 |
| `src/weewx_evo/ingest/parsers.py` | 133 | [Drivers](Drivers) | 2026-08-26 11:23 |
| `src/weewx_evo/ingest/plugins/__init__.py` | 71 | [Drivers](Drivers) | 2026-08-26 11:50 |
| `src/weewx_evo/ingest/plugins/ecowitt/__init__.py` | 8 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/__main__.py` | 174 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/catalog.py` | 1074 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/columns.py` | 110 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:52 |
| `src/weewx_evo/ingest/plugins/ecowitt/consoles.py` | 215 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:57 |
| `src/weewx_evo/ingest/plugins/ecowitt/driver.py` | 384 | [Driver: Ecowitt](Driver-Ecowitt) · [Settings A–Z](Settings-Reference) | 2026-08-26 12:43 |
| `src/weewx_evo/ingest/plugins/ecowitt/infer.py` | 200 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `src/weewx_evo/ingest/plugins/ecowitt/mapping.py` | 207 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/plugins/ecowitt/protocol.py` | 164 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `src/weewx_evo/ingest/plugins/ecowitt/report.py` | 69 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `src/weewx_evo/ingest/state.py` | 170 | [Drivers](Drivers) | 2026-08-26 12:00 |
| `src/weewx_evo/ingest/statuspage.py` | 471 | [Listener](Ingest-Listener) | 2026-08-26 23:53 |
| `src/weewx_evo/ingest/userdrivers.py` | 321 | [Drivers](Drivers) | 2026-08-26 23:56 |
| `src/weewx_evo/lang/de.toml` | 128 | **none** | 2026-08-27 01:05 |
| `src/weewx_evo/language.py` | 282 | **none** | 2026-08-27 01:31 |
| `src/weewx_evo/moon.py` | 569 | **none** | 2026-08-26 20:42 |
| `src/weewx_evo/mqtt.py` | 503 | **none** | 2026-08-27 11:27 |
| `src/weewx_evo/netaccess.py` | 123 | [Security](Security) | 2026-08-26 23:43 |
| `src/weewx_evo/obstypes.py` | 80 | [Aggregation](Aggregation) · [Contributing](Contributing) | 2026-08-26 10:54 |
| `src/weewx_evo/options.py` | 813 | ⚠️ [Configuration](Configuration) · [Settings A–Z](Settings-Reference) | 2026-08-27 11:29 |
| `src/weewx_evo/planets.py` | 625 | **none** | 2026-08-26 23:56 |
| `src/weewx_evo/plots.py` | 805 | [Plots](Plots) | 2026-08-26 23:56 |
| `src/weewx_evo/ratelimit.py` | 205 | [Security](Security) | 2026-08-26 23:43 |
| `src/weewx_evo/series.py` | 1066 | [Series](Series) | 2026-08-27 10:29 |
| `src/weewx_evo/settings.py` | 363 | [Configuration](Configuration) | 2026-08-26 23:55 |
| `src/weewx_evo/skinkit.py` | 814 | **none** | 2026-08-27 01:11 |
| `src/weewx_evo/skins/__init__.py` | 26 | **none** | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/CHANGES.md` | 88 | **none** | 2026-08-26 23:26 |
| `src/weewx_evo/skins/deck/LICENSE` | 674 | **none** | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/options.py` | 203 | **none** | 2026-08-27 01:54 |
| `src/weewx_evo/skins/deck/README.md` | 72 | **none** | 2026-08-26 23:26 |
| `src/weewx_evo/skins/deck/tags.py` | 3188 | **none** | 2026-08-27 10:11 |
| `src/weewx_evo/sources.py` | 165 | [Multiple sources](Multiple-Sources) | 2026-08-26 23:47 |
| `src/weewx_evo/sun.py` | 675 | [Sun](Sun) | 2026-08-26 23:47 |
| `src/weewx_evo/tags.py` | 1758 | **none** | 2026-08-27 01:07 |
| `src/weewx_evo/units.py` | 1101 | [Units](Units) | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/__init__.py` | 437 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/ambient.py` | 312 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/cwop.py` | 296 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/homeassistant.py` | 181 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/mqtt.py` | 445 | **none** | 2026-08-27 11:09 |
| `src/weewx_evo/uploads/progress.py` | 87 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/records.py` | 229 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/runner.py` | 342 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/weathercloud.py` | 164 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/windy.py` | 155 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/vsop87.py` | 2381 | **none** | 2026-08-26 23:48 |
| `src/weewx_evo/webserver.py` | 460 | [Web server](Web-Server) | 2026-08-26 23:43 |
| `src/weewx_evo/websocket.py` | 238 | **none** | 2026-08-27 11:27 |
| `src/weewx_evo/weewxconf.py` | 441 | [WeeWX compatibility](WeeWX-Compatibility) | 2026-08-26 23:47 |
| `tools/adminpage.py` | 676 | [The settings page](Admin-Page) · [Testing](Testing) | 2026-08-27 10:33 |
| `tools/broker_test.py` | 575 | **none** | 2026-08-27 11:30 |
| `tools/cheetah_test.py` | 753 | **none** | 2026-08-27 02:21 |
| `tools/deck_live_test.py` | 323 | **none** | 2026-08-27 11:11 |
| `tools/deck_test.py` | 378 | **none** | 2026-08-27 08:38 |
| `tools/derive_test.py` | 386 | [Derived readings](Derived-Readings) · [Testing](Testing) | 2026-08-27 10:33 |
| `tools/difftest.py` | 133 | [Aggregation](Aggregation) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/driverinstall.py` | 225 | [Drivers](Drivers) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/export_test.py` | 745 | [Exports](Exports) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/feeds_test.py` | 185 | **none** | 2026-08-26 23:15 |
| `tools/forecast_test.py` | 686 | **none** | 2026-08-27 10:33 |
| `tools/image_test.py` | 392 | **none** | 2026-08-26 23:47 |
| `tools/mooncheck.py` | 208 | **none** | 2026-08-26 23:43 |
| `tools/mqtt_test.py` | 597 | **none** | 2026-08-27 10:33 |
| `tools/multisource.py` | 166 | [Multiple sources](Multiple-Sources) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/netaccess_test.py` | 156 | [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/planetcheck.py` | 295 | **none** | 2026-08-26 23:56 |
| `tools/ratelimit_test.py` | 168 | [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/realtime_test.py` | 201 | **none** | 2026-08-27 10:37 |
| `tools/roundtrip.py` | 239 | [Archiver](Archiver) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/scaletest.py` | 302 | **none** | 2026-08-27 10:29 |
| `tools/seriestest.py` | 375 | [Series](Series) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/settings_test.py` | 301 | [Configuration](Configuration) · [Testing](Testing) | 2026-08-26 23:55 |
| `tools/smoke.py` | 256 | [Testing](Testing) | 2026-08-26 23:43 |
| `tools/suncheck.py` | 243 | [Sun](Sun) · [Testing](Testing) | 2026-08-26 23:55 |
| `tools/tagcheck.py` | 343 | **none** | 2026-08-26 23:56 |
| `tools/unitcheck.py` | 217 | [Testing](Testing) · [Units](Units) | 2026-08-27 10:33 |
| `tools/upload_test.py` | 303 | **none** | 2026-08-27 10:33 |
| `tools/vsop87trim.py` | 282 | **none** | 2026-08-26 23:48 |
| `tools/web_test.py` | 219 | [Testing](Testing) · [Web server](Web-Server) | 2026-08-26 23:43 |
| `tests/ecowitt/conftest.py` | 43 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:51 |
| `tests/ecowitt/fixtures/README.md` | 12 | [Testing](Testing) | 2026-08-26 11:48 |
| `tests/ecowitt/test_columns.py` | 65 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `tests/ecowitt/test_consoles.py` | 284 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `tests/ecowitt/test_infer.py` | 107 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_mapping.py` | 289 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `tests/ecowitt/test_protocol.py` | 124 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 11:48 |
| `tests/ecowitt/test_report.py` | 53 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `tests/ecowitt/test_resilience.py` | 115 | [Driver: Ecowitt](Driver-Ecowitt) | 2026-08-26 23:43 |
| `deploy/compose.yml` | 86 | [Deployment](Deployment) | 2026-08-26 16:17 |
| `deploy/Dockerfile` | 56 | [Deployment](Deployment) | 2026-08-26 20:40 |
| `deploy/split.yml` | 75 | [Architecture](Architecture) · [Deployment](Deployment) | 2026-08-26 12:01 |
| `README.md` | 421 | [Getting started](Getting-Started) · [weewx-evo](Home) | 2026-08-27 10:55 |
| `CLAUDE.md` | 725 | [Contributing](Contributing) · [weewx-evo](Home) | 2026-08-26 23:59 |
| `pyproject.toml` | 134 | [weewx-evo](Home) · [Testing](Testing) | 2026-08-27 10:33 |
| `.gitignore` | 43 | [Contributing](Contributing) | 2026-08-26 15:38 |
| `LICENSE` | 674 | [weewx-evo](Home) | 2026-08-26 15:37 |

## With no page

No `covers` block names these files. Either they belong in an
existing page, or one is missing.

| File | Last changed |
|---|---|
| `src/weewx_evo/broker.py` | 2026-08-27 11:27 |
| `src/weewx_evo/chartdata.py` | 2026-08-26 23:45 |
| `src/weewx_evo/feeds/cheetah/__init__.py` | 2026-08-27 11:13 |
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
| `src/weewx_evo/mqtt.py` | 2026-08-27 11:27 |
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
| `src/weewx_evo/uploads/mqtt.py` | 2026-08-27 11:09 |
| `src/weewx_evo/uploads/progress.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/records.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/runner.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/weathercloud.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/windy.py` | 2026-08-27 10:33 |
| `src/weewx_evo/vsop87.py` | 2026-08-26 23:48 |
| `src/weewx_evo/websocket.py` | 2026-08-27 11:27 |
| `tools/broker_test.py` | 2026-08-27 11:30 |
| `tools/cheetah_test.py` | 2026-08-27 02:21 |
| `tools/deck_live_test.py` | 2026-08-27 11:11 |
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

Generated by `tools/docsindex.py`. See [Contributing](Contributing).

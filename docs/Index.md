# File index

Which file belongs to which wiki page, and where the page is behind
the code.

**Generated:** 2026-08-30 09:58 · `python tools/docsindex.py`

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
| Wiki pages | 43 |
| Files covered | 71 of 239 |
| Pages to look at | 22 |
| Files with no page | 168 |

## To look at

| Page | Changed since the page | File last | Page last |
|---|---|---|---|
| ⚠️ [Contributing](Contributing) | `.gitignore`, `CLAUDE.md` | 2026-08-30 09:58 | 2026-08-27 11:07 |
| ⚠️ [Feeds](Feeds) | `src/weewx_evo/feeds/jsongenerator/__init__.py`, `src/weewx_evo/feeds/__init__.py` | 2026-08-30 09:47 | 2026-08-29 21:07 |
| ⚠️ [Settings A–Z](Settings-Reference) | `src/weewx_evo/feeds/jsongenerator/__init__.py`, `src/weewx_evo/options.py`, `src/weewx_evo/exports/ftp.py` (+2) | 2026-08-30 09:47 | 2026-08-27 11:16 |
| ⚠️ [The settings page](Admin-Page) | `src/weewx_evo/admin.py`, `tools/adminpage.py` | 2026-08-30 09:46 | 2026-08-27 11:06 |
| ⚠️ [Configuration](Configuration) | `src/weewx_evo/options.py`, `src/weewx_evo/settings.py`, `tools/settings_test.py` (+1) | 2026-08-30 09:45 | 2026-08-27 11:07 |
| ⚠️ [CLI reference](CLI-Reference) | `src/weewx_evo/cli.py` | 2026-08-30 06:51 | 2026-08-27 11:15 |
| ⚠️ [Testing](Testing) | `tools/adminpage.py`, `tools/export_test.py`, `tools/settings_test.py` (+4) | 2026-08-30 06:12 | 2026-08-27 11:56 |
| ⚠️ [Plots](Plots) | `src/weewx_evo/adminplots.py` | 2026-08-30 05:54 | 2026-08-29 21:07 |
| ⚠️ [Web server](Web-Server) | `src/weewx_evo/webserver.py` | 2026-08-29 19:04 | 2026-08-27 11:05 |
| ⚠️ [Derived readings](Derived-Readings) | `src/weewx_evo/derive.py`, `tools/derive_test.py` | 2026-08-29 19:04 | 2026-08-27 11:03 |
| ⚠️ [Series](Series) | `src/weewx_evo/series.py` | 2026-08-29 17:25 | 2026-08-27 11:04 |
| ⚠️ [Units](Units) | `src/weewx_evo/units.py`, `tools/unitcheck.py` | 2026-08-29 15:29 | 2026-08-27 11:04 |
| ⚠️ [Archiver](Archiver) | `src/weewx_evo/archiver.py` | 2026-08-29 14:55 | 2026-08-27 11:02 |
| ⚠️ [Listener](Ingest-Listener) | `src/weewx_evo/ingest/listener.py` | 2026-08-29 14:31 | 2026-08-27 11:01 |
| ⚠️ [WeeWX compatibility](WeeWX-Compatibility) | `src/weewx_evo/weewxconf.py` | 2026-08-29 12:47 | 2026-08-27 11:15 |
| ⚠️ [Exports](Exports) | `src/weewx_evo/exports/runner.py`, `tools/export_test.py`, `src/weewx_evo/exports/ftp.py` (+3) | 2026-08-28 22:56 | 2026-08-27 11:11 |
| ⚠️ [The archive database](Database-Archive) | `src/weewx_evo/db/archive.py` | 2026-08-28 17:59 | 2026-08-27 11:03 |
| ⚠️ [The live database](Database-Live) | `src/weewx_evo/db/live.py` | 2026-08-28 13:12 | 2026-08-27 11:01 |
| ⚠️ [Architecture](Architecture) | `deploy/split.yml` | 2026-08-27 23:39 | 2026-08-27 11:00 |
| ⚠️ [Deployment](Deployment) | `deploy/split.yml`, `deploy/compose.yml` | 2026-08-27 23:39 | 2026-08-27 11:08 |
| ⚠️ [Getting started](Getting-Started) | `README.md` | 2026-08-27 13:06 | 2026-08-27 10:58 |
| ⚠️ [Security](Security) | `src/weewx_evo/netaccess.py` | 2026-08-27 11:41 | 2026-08-27 11:08 |

## Pages

| | Page | Files | Code last | Page last |
|---|---|---|---|---|
| ✅ | [Aggregation](Aggregation) | 3 | 2026-08-26 23:54 | 2026-08-27 11:02 |
| — | [API](API) | — | — | 2026-08-29 16:22 |
| ⚠️ | [Architecture](Architecture) | 2 | 2026-08-27 23:39 | 2026-08-27 11:00 |
| ⚠️ | [Archiver](Archiver) | 2 | 2026-08-29 14:55 | 2026-08-27 11:02 |
| ⚠️ | [CLI reference](CLI-Reference) | 1 | 2026-08-30 06:51 | 2026-08-27 11:15 |
| ⚠️ | [Configuration](Configuration) | 4 | 2026-08-30 09:45 | 2026-08-27 11:07 |
| ⚠️ | [Contributing](Contributing) | 4 | 2026-08-30 09:58 | 2026-08-27 11:07 |
| ✅ | [Daily summaries](Daily-Summaries) | 1 | 2026-08-26 23:56 | 2026-08-27 11:03 |
| — | [Deck](Deck) | — | — | 2026-08-29 21:06 |
| ⚠️ | [Deployment](Deployment) | 3 | 2026-08-27 23:39 | 2026-08-27 11:08 |
| ⚠️ | [Derived readings](Derived-Readings) | 2 | 2026-08-29 19:04 | 2026-08-27 11:03 |
| ✅ | [Driver: Ecowitt](Driver-Ecowitt) | — | 1970-01-01 01:00 | 2026-08-27 11:14 |
| ✅ | [Drivers](Drivers) | 7 | 2026-08-27 21:22 | 2026-08-29 08:23 |
| ⚠️ | [Exports](Exports) | 7 | 2026-08-28 22:56 | 2026-08-27 11:11 |
| ⚠️ | [Feeds](Feeds) | 5 | 2026-08-30 09:47 | 2026-08-29 21:07 |
| — | [Forecast](Forecast) | — | — | 2026-08-30 04:38 |
| ⚠️ | [Getting started](Getting-Started) | 1 | 2026-08-27 13:06 | 2026-08-27 10:58 |
| — | [Glossary](Glossary) | — | — | 2026-08-27 11:00 |
| — | [Grafana](Grafana) | — | — | 2026-08-30 04:47 |
| ⚠️ | [Listener](Ingest-Listener) | 4 | 2026-08-29 14:31 | 2026-08-27 11:01 |
| — | [Maintenance](Maintenance) | — | — | 2026-08-29 16:10 |
| — | [Metrics](Metrics) | — | — | 2026-08-29 16:32 |
| — | [MQTT](MQTT) | — | — | 2026-08-27 11:56 |
| ✅ | [Multiple sources](Multiple-Sources) | 2 | 2026-08-26 23:47 | 2026-08-27 11:01 |
| — | [Notifications](Notifications) | — | — | 2026-08-29 15:38 |
| ⚠️ | [Plots](Plots) | 2 | 2026-08-30 05:54 | 2026-08-29 21:07 |
| — | [Plugins](Plugins) | — | — | 2026-08-27 11:19 |
| — | [Quality control](Quality) | — | — | 2026-08-29 15:10 |
| ⚠️ | [Security](Security) | 2 | 2026-08-27 11:41 | 2026-08-27 11:08 |
| ⚠️ | [Series](Series) | 2 | 2026-08-29 17:25 | 2026-08-27 11:04 |
| ⚠️ | [Settings A–Z](Settings-Reference) | 5 | 2026-08-30 09:47 | 2026-08-27 11:16 |
| ✅ | [Several places](Places) | 2 | 2026-08-30 07:22 | 2026-08-30 09:57 |
| — | [Stations and Archives](Stations-and-Archives) | — | — | 2026-08-30 04:38 |
| ✅ | [Sun](Sun) | 2 | 2026-08-26 23:55 | 2026-08-27 11:05 |
| ⚠️ | [Testing](Testing) | 16 | 2026-08-30 06:12 | 2026-08-27 11:56 |
| ⚠️ | [The archive database](Database-Archive) | 3 | 2026-08-28 17:59 | 2026-08-27 11:03 |
| ⚠️ | [The live database](Database-Live) | 1 | 2026-08-28 13:12 | 2026-08-27 11:01 |
| ⚠️ | [The settings page](Admin-Page) | 2 | 2026-08-30 09:46 | 2026-08-27 11:06 |
| ⚠️ | [Units](Units) | 2 | 2026-08-29 15:29 | 2026-08-27 11:04 |
| — | [Uploads](Uploads) | — | — | 2026-08-29 14:46 |
| ⚠️ | [Web server](Web-Server) | 2 | 2026-08-29 19:04 | 2026-08-27 11:05 |
| ⚠️ | [WeeWX compatibility](WeeWX-Compatibility) | 2 | 2026-08-29 12:47 | 2026-08-27 11:15 |
| ✅ | [weewx-evo](Home) | 7 | 2026-08-30 04:48 | 2026-08-30 09:58 |

## Files

| File | Lines | Wiki page | Last changed |
|---|---|---|---|
| `src/weewx_evo/__init__.py` | 8 | [Architecture](Architecture) · [weewx-evo](Home) | 2026-08-26 10:53 |
| `src/weewx_evo/admin.py` | 3809 | ⚠️ [The settings page](Admin-Page) | 2026-08-30 09:46 |
| `src/weewx_evo/adminarchives.py` | 1047 | [Several places](Places) | 2026-08-30 06:30 |
| `src/weewx_evo/adminfields.py` | 554 | **none** | 2026-08-28 19:00 |
| `src/weewx_evo/adminhome.py` | 984 | **none** | 2026-08-30 09:37 |
| `src/weewx_evo/adminplots.py` | 1016 | ⚠️ [Plots](Plots) | 2026-08-30 05:54 |
| `src/weewx_evo/adminpublish.py` | 418 | **none** | 2026-08-30 07:02 |
| `src/weewx_evo/adminquality.py` | 431 | **none** | 2026-08-30 05:52 |
| `src/weewx_evo/adminsearch.py` | 177 | **none** | 2026-08-28 16:48 |
| `src/weewx_evo/adminsetup.py` | 468 | **none** | 2026-08-30 06:40 |
| `src/weewx_evo/adminstations.py` | 1125 | [Several places](Places) | 2026-08-30 07:22 |
| `src/weewx_evo/adopt.py` | 400 | **none** | 2026-08-29 14:31 |
| `src/weewx_evo/aggregate.py` | 497 | [Aggregation](Aggregation) · [Contributing](Contributing) | 2026-08-26 23:43 |
| `src/weewx_evo/api.py` | 524 | **none** | 2026-08-29 16:19 |
| `src/weewx_evo/archiver.py` | 374 | ⚠️ [Archiver](Archiver) | 2026-08-29 14:55 |
| `src/weewx_evo/archives.py` | 688 | **none** | 2026-08-30 03:14 |
| `src/weewx_evo/chartdata.py` | 796 | **none** | 2026-08-29 20:45 |
| `src/weewx_evo/cli.py` | 5530 | ⚠️ [CLI reference](CLI-Reference) | 2026-08-30 06:51 |
| `src/weewx_evo/collectors.py` | 233 | **none** | 2026-08-29 17:20 |
| `src/weewx_evo/config.py` | 319 | ⚠️ [Configuration](Configuration) | 2026-08-28 14:31 |
| `src/weewx_evo/db/__init__.py` | 0 | [weewx-evo](Home) | 2026-08-26 10:58 |
| `src/weewx_evo/db/archive.py` | 445 | ⚠️ [The archive database](Database-Archive) | 2026-08-28 17:59 |
| `src/weewx_evo/db/daily.py` | 116 | [Daily summaries](Daily-Summaries) | 2026-08-26 23:56 |
| `src/weewx_evo/db/live.py` | 450 | ⚠️ [The live database](Database-Live) | 2026-08-28 13:12 |
| `src/weewx_evo/db/schema.py` | 86 | [The archive database](Database-Archive) | 2026-08-26 10:57 |
| `src/weewx_evo/db/wview.py` | 137 | [The archive database](Database-Archive) · [WeeWX compatibility](WeeWX-Compatibility) | 2026-08-26 23:53 |
| `src/weewx_evo/derive.py` | 1169 | ⚠️ [Derived readings](Derived-Readings) | 2026-08-29 19:04 |
| `src/weewx_evo/dumps.py` | 613 | **none** | 2026-08-29 17:58 |
| `src/weewx_evo/dumpscsv.py` | 417 | **none** | 2026-08-29 18:01 |
| `src/weewx_evo/exports/__init__.py` | 408 | ⚠️ [Exports](Exports) | 2026-08-28 20:17 |
| `src/weewx_evo/exports/ftp.py` | 399 | ⚠️ [Exports](Exports) · [Settings A–Z](Settings-Reference) | 2026-08-28 21:54 |
| `src/weewx_evo/exports/livepush/__init__.py` | 199 | **none** | 2026-08-29 19:04 |
| `src/weewx_evo/exports/local.py` | 414 | ⚠️ [Exports](Exports) · [Settings A–Z](Settings-Reference) | 2026-08-28 21:54 |
| `src/weewx_evo/exports/record.py` | 131 | **none** | 2026-08-29 15:25 |
| `src/weewx_evo/exports/rsync.py` | 351 | ⚠️ [Exports](Exports) · [Settings A–Z](Settings-Reference) | 2026-08-28 21:54 |
| `src/weewx_evo/exports/runner.py` | 509 | ⚠️ [Exports](Exports) | 2026-08-28 22:56 |
| `src/weewx_evo/exports/tracker.py` | 165 | [Exports](Exports) | 2026-08-26 13:31 |
| `src/weewx_evo/feedrunner.py` | 347 | [Feeds](Feeds) | 2026-08-29 19:04 |
| `src/weewx_evo/feeds/__init__.py` | 351 | ⚠️ [Feeds](Feeds) | 2026-08-30 05:53 |
| `src/weewx_evo/feeds/cheetah/__init__.py` | 2441 | **none** | 2026-08-30 06:51 |
| `src/weewx_evo/feeds/diagnostic/__init__.py` | 557 | [Feeds](Feeds) | 2026-08-29 19:04 |
| `src/weewx_evo/feeds/diagnostic/vendor/LICENSE` | 21 | [Feeds](Feeds) | 2026-08-26 15:12 |
| `src/weewx_evo/feeds/imagegenerator/__init__.py` | 821 | **none** | 2026-08-29 19:04 |
| `src/weewx_evo/feeds/imagegenerator/canvas.py` | 410 | **none** | 2026-08-26 23:47 |
| `src/weewx_evo/feeds/imagegenerator/theme.py` | 225 | **none** | 2026-08-26 23:56 |
| `src/weewx_evo/feeds/jsongenerator/__init__.py` | 816 | ⚠️ [Feeds](Feeds) · [Settings A–Z](Settings-Reference) | 2026-08-30 09:47 |
| `src/weewx_evo/feeds/realtime/__init__.py` | 273 | **none** | 2026-08-27 10:35 |
| `src/weewx_evo/forecast/__init__.py` | 420 | **none** | 2026-08-30 05:54 |
| `src/weewx_evo/forecast/codes.py` | 110 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/dwd.py` | 487 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/meteoalarm.py` | 267 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/nws.py` | 308 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/openmeteo.py` | 291 | **none** | 2026-08-27 19:38 |
| `src/weewx_evo/forecast/runner.py` | 324 | **none** | 2026-08-30 04:43 |
| `src/weewx_evo/forecast/store.py` | 482 | **none** | 2026-08-30 03:15 |
| `src/weewx_evo/forecast/tags.py` | 511 | **none** | 2026-08-30 03:11 |
| `src/weewx_evo/grafana/__init__.py` | 333 | **none** | 2026-08-29 17:03 |
| `src/weewx_evo/grafana/dashboards.py` | 405 | **none** | 2026-08-29 19:50 |
| `src/weewx_evo/grafana/icons.py` | 201 | **none** | 2026-08-29 17:10 |
| `src/weewx_evo/grafana/panels.py` | 501 | **none** | 2026-08-29 17:03 |
| `src/weewx_evo/grafana/query_influx.py` | 330 | **none** | 2026-08-29 17:02 |
| `src/weewx_evo/grafana/style.py` | 240 | **none** | 2026-08-29 14:34 |
| `src/weewx_evo/grafana/words.py` | 130 | **none** | 2026-08-29 17:02 |
| `src/weewx_evo/ingest/__init__.py` | 0 | [weewx-evo](Home) | 2026-08-26 11:20 |
| `src/weewx_evo/ingest/drivers.py` | 377 | [Drivers](Drivers) | 2026-08-27 21:22 |
| `src/weewx_evo/ingest/envelope.py` | 49 | [Drivers](Drivers) | 2026-08-26 11:39 |
| `src/weewx_evo/ingest/listener.py` | 643 | ⚠️ [Listener](Ingest-Listener) | 2026-08-29 14:31 |
| `src/weewx_evo/ingest/mqttsub.py` | 374 | **none** | 2026-08-29 17:19 |
| `src/weewx_evo/ingest/parsers.py` | 133 | [Drivers](Drivers) | 2026-08-26 11:23 |
| `src/weewx_evo/ingest/plugins/__init__.py` | 71 | [Drivers](Drivers) | 2026-08-26 11:50 |
| `src/weewx_evo/ingest/plugins/push/__init__.py` | 13 | **none** | 2026-08-28 17:33 |
| `src/weewx_evo/ingest/plugins/push/catalogs/__init__.py` | 31 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/acurite.py` | 88 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/ambient.py` | 308 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/ecowitt.py` | 1074 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/lacrosse.py` | 98 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/weatherflow.py` | 169 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/wunderground.py` | 316 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/driver.py` | 381 | **none** | 2026-08-28 20:00 |
| `src/weewx_evo/ingest/plugins/push/infer.py` | 204 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/mapping.py` | 245 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/__init__.py` | 296 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/acurite.py` | 143 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/ambient.py` | 90 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/ecowitt.py` | 88 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/lacrosse.py` | 121 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/weatherflow.py` | 178 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/wunderground.py` | 186 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/report.py` | 72 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/roles.py` | 94 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/transport.py` | 201 | **none** | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/sightings.py` | 243 | **none** | 2026-08-27 23:12 |
| `src/weewx_evo/ingest/state.py` | 170 | [Drivers](Drivers) | 2026-08-26 12:00 |
| `src/weewx_evo/ingest/statuspage.py` | 471 | [Listener](Ingest-Listener) | 2026-08-26 23:53 |
| `src/weewx_evo/ingest/userdrivers.py` | 321 | [Drivers](Drivers) | 2026-08-26 23:56 |
| `src/weewx_evo/ingest/weewxnames.py` | 613 | **none** | 2026-08-29 04:59 |
| `src/weewx_evo/ingest/weewxshim.py` | 601 | **none** | 2026-08-29 10:06 |
| `src/weewx_evo/lang/de.toml` | 228 | **none** | 2026-08-29 20:49 |
| `src/weewx_evo/language.py` | 314 | **none** | 2026-08-29 14:34 |
| `src/weewx_evo/maintenance.py` | 511 | **none** | 2026-08-29 15:59 |
| `src/weewx_evo/metrics.py` | 307 | **none** | 2026-08-29 16:28 |
| `src/weewx_evo/moon.py` | 569 | **none** | 2026-08-26 20:42 |
| `src/weewx_evo/mqtt.py` | 503 | **none** | 2026-08-27 11:27 |
| `src/weewx_evo/netaccess.py` | 138 | ⚠️ [Security](Security) | 2026-08-27 11:41 |
| `src/weewx_evo/notify/__init__.py` | 380 | **none** | 2026-08-29 15:27 |
| `src/weewx_evo/notify/mqtt.py` | 151 | **none** | 2026-08-29 15:24 |
| `src/weewx_evo/notify/rules.py` | 301 | **none** | 2026-08-29 22:43 |
| `src/weewx_evo/notify/runner.py` | 176 | **none** | 2026-08-29 15:26 |
| `src/weewx_evo/notify/smtp.py` | 161 | **none** | 2026-08-29 15:27 |
| `src/weewx_evo/notify/webhook.py` | 224 | **none** | 2026-08-29 15:36 |
| `src/weewx_evo/obstypes.py` | 80 | [Aggregation](Aggregation) · [Contributing](Contributing) | 2026-08-26 10:54 |
| `src/weewx_evo/options.py` | 868 | ⚠️ [Configuration](Configuration) · [Settings A–Z](Settings-Reference) | 2026-08-30 09:45 |
| `src/weewx_evo/planets.py` | 625 | **none** | 2026-08-26 23:56 |
| `src/weewx_evo/plots.py` | 1059 | [Plots](Plots) | 2026-08-29 20:08 |
| `src/weewx_evo/quality.py` | 747 | **none** | 2026-08-29 16:49 |
| `src/weewx_evo/ratelimit.py` | 205 | [Security](Security) | 2026-08-26 23:43 |
| `src/weewx_evo/roles.py` | 164 | **none** | 2026-08-28 18:19 |
| `src/weewx_evo/schedule.py` | 74 | **none** | 2026-08-28 22:42 |
| `src/weewx_evo/series.py` | 1116 | ⚠️ [Series](Series) | 2026-08-29 17:25 |
| `src/weewx_evo/settings.py` | 399 | ⚠️ [Configuration](Configuration) | 2026-08-28 20:00 |
| `src/weewx_evo/skinkit.py` | 825 | **none** | 2026-08-27 19:38 |
| `src/weewx_evo/skins/__init__.py` | 26 | **none** | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/CHANGES.md` | 138 | **none** | 2026-08-29 19:23 |
| `src/weewx_evo/skins/deck/LICENSE` | 674 | **none** | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/README.md` | 98 | **none** | 2026-08-29 19:23 |
| `src/weewx_evo/skins/deck/options.py` | 380 | **none** | 2026-08-30 09:46 |
| `src/weewx_evo/skins/deck/tags.py` | 3453 | **none** | 2026-08-29 21:57 |
| `src/weewx_evo/sources.py` | 165 | [Multiple sources](Multiple-Sources) | 2026-08-26 23:47 |
| `src/weewx_evo/starter/__init__.py` | 142 | **none** | 2026-08-29 13:34 |
| `src/weewx_evo/starter/plots.toml` | 2146 | **none** | 2026-08-29 14:31 |
| `src/weewx_evo/stations.py` | 482 | **none** | 2026-08-28 20:00 |
| `src/weewx_evo/sun.py` | 675 | [Sun](Sun) | 2026-08-26 23:47 |
| `src/weewx_evo/tags.py` | 1879 | **none** | 2026-08-29 19:04 |
| `src/weewx_evo/units.py` | 1174 | ⚠️ [Units](Units) | 2026-08-29 15:29 |
| `src/weewx_evo/uploads/__init__.py` | 518 | **none** | 2026-08-30 05:54 |
| `src/weewx_evo/uploads/ambient.py` | 312 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/cwop.py` | 304 | **none** | 2026-08-27 13:03 |
| `src/weewx_evo/uploads/homeassistant.py` | 181 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/influx.py` | 568 | **none** | 2026-08-30 05:54 |
| `src/weewx_evo/uploads/mqtt.py` | 445 | **none** | 2026-08-27 11:09 |
| `src/weewx_evo/uploads/progress.py` | 106 | **none** | 2026-08-29 14:48 |
| `src/weewx_evo/uploads/records.py` | 545 | **none** | 2026-08-29 22:44 |
| `src/weewx_evo/uploads/runner.py` | 599 | **none** | 2026-08-30 04:44 |
| `src/weewx_evo/uploads/weathercloud.py` | 164 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/webpush.py` | 717 | **none** | 2026-08-29 22:45 |
| `src/weewx_evo/uploads/windy.py` | 155 | **none** | 2026-08-27 10:33 |
| `src/weewx_evo/vsop87.py` | 2381 | **none** | 2026-08-26 23:48 |
| `src/weewx_evo/watchdog.py` | 302 | **none** | 2026-08-28 13:02 |
| `src/weewx_evo/webserver.py` | 512 | ⚠️ [Web server](Web-Server) | 2026-08-29 19:04 |
| `src/weewx_evo/weewxconf.py` | 544 | ⚠️ [WeeWX compatibility](WeeWX-Compatibility) | 2026-08-29 12:47 |
| `tools/adminfields_test.py` | 499 | **none** | 2026-08-28 20:00 |
| `tools/adminhome_test.py` | 706 | **none** | 2026-08-30 07:12 |
| `tools/adminpage.py` | 1086 | ⚠️ [The settings page](Admin-Page) · [Testing](Testing) | 2026-08-30 06:12 |
| `tools/adminsearch_test.py` | 176 | **none** | 2026-08-28 16:50 |
| `tools/alldrivers_test.py` | 344 | **none** | 2026-08-29 05:23 |
| `tools/api_test.py` | 471 | **none** | 2026-08-29 16:19 |
| `tools/archives_e2e.py` | 667 | **none** | 2026-08-29 21:04 |
| `tools/archives_test.py` | 1024 | **none** | 2026-08-29 21:03 |
| `tools/cheetah_test.py` | 753 | **none** | 2026-08-29 15:29 |
| `tools/collector_test.py` | 182 | **none** | 2026-08-29 10:11 |
| `tools/deck_dead_test.py` | 261 | **none** | 2026-08-29 01:55 |
| `tools/deck_live_test.py` | 1032 | **none** | 2026-08-29 00:18 |
| `tools/deck_places_test.py` | 851 | **none** | 2026-08-30 01:45 |
| `tools/deck_test.py` | 840 | **none** | 2026-08-30 03:17 |
| `tools/derive_test.py` | 521 | ⚠️ [Derived readings](Derived-Readings) · [Testing](Testing) | 2026-08-27 19:38 |
| `tools/difftest.py` | 133 | [Aggregation](Aggregation) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/driverinstall.py` | 225 | [Drivers](Drivers) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/driversim.py` | 266 | **none** | 2026-08-29 05:23 |
| `tools/ecowittsim.py` | 254 | **none** | 2026-08-29 23:16 |
| `tools/export_test.py` | 1068 | ⚠️ [Exports](Exports) · [Testing](Testing) | 2026-08-28 22:09 |
| `tools/feeds_test.py` | 191 | **none** | 2026-08-29 13:25 |
| `tools/feedtiming_test.py` | 187 | **none** | 2026-08-28 22:27 |
| `tools/forecast_test.py` | 840 | **none** | 2026-08-30 03:19 |
| `tools/fousb_test.py` | 287 | **none** | 2026-08-29 05:23 |
| `tools/fousbsim.py` | 245 | **none** | 2026-08-29 08:23 |
| `tools/grafana_test.py` | 836 | **none** | 2026-08-29 17:14 |
| `tools/image_test.py` | 392 | **none** | 2026-08-29 15:29 |
| `tools/import_test.py` | 751 | **none** | 2026-08-29 18:00 |
| `tools/influx_test.py` | 1026 | **none** | 2026-08-30 04:46 |
| `tools/livedb_test.py` | 234 | **none** | 2026-08-28 12:34 |
| `tools/livesource_test.py` | 192 | **none** | 2026-08-29 11:53 |
| `tools/maintenance_test.py` | 510 | **none** | 2026-08-29 17:08 |
| `tools/metrics_test.py` | 424 | **none** | 2026-08-29 16:31 |
| `tools/mooncheck.py` | 208 | **none** | 2026-08-26 23:43 |
| `tools/mqtt_test.py` | 823 | **none** | 2026-08-29 17:19 |
| `tools/multisource.py` | 166 | [Multiple sources](Multiple-Sources) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/netaccess_test.py` | 156 | [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/notify_test.py` | 685 | **none** | 2026-08-29 15:36 |
| `tools/planetcheck.py` | 295 | **none** | 2026-08-26 23:56 |
| `tools/quality_test.py` | 778 | **none** | 2026-08-29 18:06 |
| `tools/ratelimit_test.py` | 168 | [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/realtime_test.py` | 201 | **none** | 2026-08-27 10:37 |
| `tools/resilience_test.py` | 300 | **none** | 2026-08-29 14:31 |
| `tools/roles_test.py` | 237 | **none** | 2026-08-28 18:22 |
| `tools/roundtrip.py` | 239 | [Archiver](Archiver) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/runtests.py` | 411 | **none** | 2026-08-29 21:05 |
| `tools/scaletest.py` | 302 | **none** | 2026-08-27 10:29 |
| `tools/schedule_test.py` | 234 | **none** | 2026-08-28 22:58 |
| `tools/sdr_test.py` | 312 | **none** | 2026-08-29 05:23 |
| `tools/sdrsim.py` | 148 | **none** | 2026-08-29 08:23 |
| `tools/seriestest.py` | 375 | [Series](Series) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/settings_test.py` | 441 | ⚠️ [Configuration](Configuration) · [Testing](Testing) | 2026-08-28 20:00 |
| `tools/setup_test.py` | 450 | **none** | 2026-08-30 06:40 |
| `tools/shim_test.py` | 406 | **none** | 2026-08-27 20:28 |
| `tools/smoke.py` | 312 | ⚠️ [Testing](Testing) | 2026-08-27 14:15 |
| `tools/standin_test.py` | 557 | **none** | 2026-08-29 08:22 |
| `tools/stations_test.py` | 435 | **none** | 2026-08-28 02:50 |
| `tools/stillweewx_test.py` | 472 | **none** | 2026-08-29 13:18 |
| `tools/suncheck.py` | 243 | [Sun](Sun) · [Testing](Testing) | 2026-08-26 23:55 |
| `tools/tagcheck.py` | 343 | **none** | 2026-08-26 23:56 |
| `tools/unitcheck.py` | 247 | ⚠️ [Testing](Testing) · [Units](Units) | 2026-08-27 13:03 |
| `tools/upload_test.py` | 377 | **none** | 2026-08-28 22:36 |
| `tools/vantage_test.py` | 317 | **none** | 2026-08-29 05:23 |
| `tools/vantagesim.py` | 401 | **none** | 2026-08-29 08:23 |
| `tools/vsop87trim.py` | 282 | **none** | 2026-08-26 23:48 |
| `tools/watchdog_test.py` | 381 | **none** | 2026-08-28 14:16 |
| `tools/web_test.py` | 219 | [Testing](Testing) · [Web server](Web-Server) | 2026-08-26 23:43 |
| `tools/wunderground_test.py` | 253 | **none** | 2026-08-28 17:43 |
| `tests/push/conftest.py` | 88 | **none** | 2026-08-28 17:39 |
| `tests/push/fixtures/README.md` | 12 | **none** | 2026-08-28 17:37 |
| `tests/push/helpers.py` | 70 | **none** | 2026-08-28 17:37 |
| `tests/push/test_ambient.py` | 110 | **none** | 2026-08-28 17:37 |
| `tests/push/test_bridges.py` | 169 | **none** | 2026-08-28 17:37 |
| `tests/push/test_infer.py` | 108 | **none** | 2026-08-28 17:37 |
| `tests/push/test_mapping.py` | 292 | **none** | 2026-08-28 17:37 |
| `tests/push/test_protocols.py` | 149 | **none** | 2026-08-28 17:37 |
| `tests/push/test_report.py` | 52 | **none** | 2026-08-28 17:37 |
| `tests/push/test_transport.py` | 124 | **none** | 2026-08-28 17:37 |
| `tests/push/test_weatherflow.py` | 207 | **none** | 2026-08-28 17:37 |
| `tests/push/test_wunderground.py` | 248 | **none** | 2026-08-28 17:37 |
| `deploy/Dockerfile` | 56 | [Deployment](Deployment) | 2026-08-26 20:40 |
| `deploy/compose.grafana.yml` | 120 | **none** | 2026-08-29 17:13 |
| `deploy/compose.yml` | 93 | ⚠️ [Deployment](Deployment) | 2026-08-27 23:38 |
| `deploy/split.yml` | 78 | ⚠️ [Architecture](Architecture) · [Deployment](Deployment) | 2026-08-27 23:39 |
| `README.md` | 458 | ⚠️ [Getting started](Getting-Started) · [weewx-evo](Home) | 2026-08-27 13:06 |
| `CLAUDE.md` | 2417 | ⚠️ [Contributing](Contributing) · [weewx-evo](Home) | 2026-08-30 04:48 |
| `pyproject.toml` | 147 | ⚠️ [weewx-evo](Home) · [Testing](Testing) | 2026-08-28 17:40 |
| `.gitignore` | 61 | ⚠️ [Contributing](Contributing) | 2026-08-30 09:58 |
| `LICENSE` | 674 | [weewx-evo](Home) | 2026-08-26 15:37 |

## With no page

No `covers` block names these files. Either they belong in an
existing page, or one is missing.

| File | Last changed |
|---|---|
| `src/weewx_evo/adminfields.py` | 2026-08-28 19:00 |
| `src/weewx_evo/adminhome.py` | 2026-08-30 09:37 |
| `src/weewx_evo/adminpublish.py` | 2026-08-30 07:02 |
| `src/weewx_evo/adminquality.py` | 2026-08-30 05:52 |
| `src/weewx_evo/adminsearch.py` | 2026-08-28 16:48 |
| `src/weewx_evo/adminsetup.py` | 2026-08-30 06:40 |
| `src/weewx_evo/adopt.py` | 2026-08-29 14:31 |
| `src/weewx_evo/api.py` | 2026-08-29 16:19 |
| `src/weewx_evo/archives.py` | 2026-08-30 03:14 |
| `src/weewx_evo/chartdata.py` | 2026-08-29 20:45 |
| `src/weewx_evo/collectors.py` | 2026-08-29 17:20 |
| `src/weewx_evo/dumps.py` | 2026-08-29 17:58 |
| `src/weewx_evo/dumpscsv.py` | 2026-08-29 18:01 |
| `src/weewx_evo/exports/livepush/__init__.py` | 2026-08-29 19:04 |
| `src/weewx_evo/exports/record.py` | 2026-08-29 15:25 |
| `src/weewx_evo/feeds/cheetah/__init__.py` | 2026-08-30 06:51 |
| `src/weewx_evo/feeds/imagegenerator/__init__.py` | 2026-08-29 19:04 |
| `src/weewx_evo/feeds/imagegenerator/canvas.py` | 2026-08-26 23:47 |
| `src/weewx_evo/feeds/imagegenerator/theme.py` | 2026-08-26 23:56 |
| `src/weewx_evo/feeds/realtime/__init__.py` | 2026-08-27 10:35 |
| `src/weewx_evo/forecast/__init__.py` | 2026-08-30 05:54 |
| `src/weewx_evo/forecast/codes.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/dwd.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/meteoalarm.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/nws.py` | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/openmeteo.py` | 2026-08-27 19:38 |
| `src/weewx_evo/forecast/runner.py` | 2026-08-30 04:43 |
| `src/weewx_evo/forecast/store.py` | 2026-08-30 03:15 |
| `src/weewx_evo/forecast/tags.py` | 2026-08-30 03:11 |
| `src/weewx_evo/grafana/__init__.py` | 2026-08-29 17:03 |
| `src/weewx_evo/grafana/dashboards.py` | 2026-08-29 19:50 |
| `src/weewx_evo/grafana/icons.py` | 2026-08-29 17:10 |
| `src/weewx_evo/grafana/panels.py` | 2026-08-29 17:03 |
| `src/weewx_evo/grafana/query_influx.py` | 2026-08-29 17:02 |
| `src/weewx_evo/grafana/style.py` | 2026-08-29 14:34 |
| `src/weewx_evo/grafana/words.py` | 2026-08-29 17:02 |
| `src/weewx_evo/ingest/mqttsub.py` | 2026-08-29 17:19 |
| `src/weewx_evo/ingest/plugins/push/__init__.py` | 2026-08-28 17:33 |
| `src/weewx_evo/ingest/plugins/push/catalogs/__init__.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/acurite.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/ambient.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/ecowitt.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/lacrosse.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/weatherflow.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/wunderground.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/driver.py` | 2026-08-28 20:00 |
| `src/weewx_evo/ingest/plugins/push/infer.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/mapping.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/__init__.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/acurite.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/ambient.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/ecowitt.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/lacrosse.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/weatherflow.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/wunderground.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/report.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/roles.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/transport.py` | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/sightings.py` | 2026-08-27 23:12 |
| `src/weewx_evo/ingest/weewxnames.py` | 2026-08-29 04:59 |
| `src/weewx_evo/ingest/weewxshim.py` | 2026-08-29 10:06 |
| `src/weewx_evo/lang/de.toml` | 2026-08-29 20:49 |
| `src/weewx_evo/language.py` | 2026-08-29 14:34 |
| `src/weewx_evo/maintenance.py` | 2026-08-29 15:59 |
| `src/weewx_evo/metrics.py` | 2026-08-29 16:28 |
| `src/weewx_evo/moon.py` | 2026-08-26 20:42 |
| `src/weewx_evo/mqtt.py` | 2026-08-27 11:27 |
| `src/weewx_evo/notify/__init__.py` | 2026-08-29 15:27 |
| `src/weewx_evo/notify/mqtt.py` | 2026-08-29 15:24 |
| `src/weewx_evo/notify/rules.py` | 2026-08-29 22:43 |
| `src/weewx_evo/notify/runner.py` | 2026-08-29 15:26 |
| `src/weewx_evo/notify/smtp.py` | 2026-08-29 15:27 |
| `src/weewx_evo/notify/webhook.py` | 2026-08-29 15:36 |
| `src/weewx_evo/planets.py` | 2026-08-26 23:56 |
| `src/weewx_evo/quality.py` | 2026-08-29 16:49 |
| `src/weewx_evo/roles.py` | 2026-08-28 18:19 |
| `src/weewx_evo/schedule.py` | 2026-08-28 22:42 |
| `src/weewx_evo/skinkit.py` | 2026-08-27 19:38 |
| `src/weewx_evo/skins/__init__.py` | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/CHANGES.md` | 2026-08-29 19:23 |
| `src/weewx_evo/skins/deck/LICENSE` | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/README.md` | 2026-08-29 19:23 |
| `src/weewx_evo/skins/deck/options.py` | 2026-08-30 09:46 |
| `src/weewx_evo/skins/deck/tags.py` | 2026-08-29 21:57 |
| `src/weewx_evo/starter/__init__.py` | 2026-08-29 13:34 |
| `src/weewx_evo/starter/plots.toml` | 2026-08-29 14:31 |
| `src/weewx_evo/stations.py` | 2026-08-28 20:00 |
| `src/weewx_evo/tags.py` | 2026-08-29 19:04 |
| `src/weewx_evo/uploads/__init__.py` | 2026-08-30 05:54 |
| `src/weewx_evo/uploads/ambient.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/cwop.py` | 2026-08-27 13:03 |
| `src/weewx_evo/uploads/homeassistant.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/influx.py` | 2026-08-30 05:54 |
| `src/weewx_evo/uploads/mqtt.py` | 2026-08-27 11:09 |
| `src/weewx_evo/uploads/progress.py` | 2026-08-29 14:48 |
| `src/weewx_evo/uploads/records.py` | 2026-08-29 22:44 |
| `src/weewx_evo/uploads/runner.py` | 2026-08-30 04:44 |
| `src/weewx_evo/uploads/weathercloud.py` | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/webpush.py` | 2026-08-29 22:45 |
| `src/weewx_evo/uploads/windy.py` | 2026-08-27 10:33 |
| `src/weewx_evo/vsop87.py` | 2026-08-26 23:48 |
| `src/weewx_evo/watchdog.py` | 2026-08-28 13:02 |
| `tools/adminfields_test.py` | 2026-08-28 20:00 |
| `tools/adminhome_test.py` | 2026-08-30 07:12 |
| `tools/adminsearch_test.py` | 2026-08-28 16:50 |
| `tools/alldrivers_test.py` | 2026-08-29 05:23 |
| `tools/api_test.py` | 2026-08-29 16:19 |
| `tools/archives_e2e.py` | 2026-08-29 21:04 |
| `tools/archives_test.py` | 2026-08-29 21:03 |
| `tools/cheetah_test.py` | 2026-08-29 15:29 |
| `tools/collector_test.py` | 2026-08-29 10:11 |
| `tools/deck_dead_test.py` | 2026-08-29 01:55 |
| `tools/deck_live_test.py` | 2026-08-29 00:18 |
| `tools/deck_places_test.py` | 2026-08-30 01:45 |
| `tools/deck_test.py` | 2026-08-30 03:17 |
| `tools/driversim.py` | 2026-08-29 05:23 |
| `tools/ecowittsim.py` | 2026-08-29 23:16 |
| `tools/feeds_test.py` | 2026-08-29 13:25 |
| `tools/feedtiming_test.py` | 2026-08-28 22:27 |
| `tools/forecast_test.py` | 2026-08-30 03:19 |
| `tools/fousb_test.py` | 2026-08-29 05:23 |
| `tools/fousbsim.py` | 2026-08-29 08:23 |
| `tools/grafana_test.py` | 2026-08-29 17:14 |
| `tools/image_test.py` | 2026-08-29 15:29 |
| `tools/import_test.py` | 2026-08-29 18:00 |
| `tools/influx_test.py` | 2026-08-30 04:46 |
| `tools/livedb_test.py` | 2026-08-28 12:34 |
| `tools/livesource_test.py` | 2026-08-29 11:53 |
| `tools/maintenance_test.py` | 2026-08-29 17:08 |
| `tools/metrics_test.py` | 2026-08-29 16:31 |
| `tools/mooncheck.py` | 2026-08-26 23:43 |
| `tools/mqtt_test.py` | 2026-08-29 17:19 |
| `tools/notify_test.py` | 2026-08-29 15:36 |
| `tools/planetcheck.py` | 2026-08-26 23:56 |
| `tools/quality_test.py` | 2026-08-29 18:06 |
| `tools/realtime_test.py` | 2026-08-27 10:37 |
| `tools/resilience_test.py` | 2026-08-29 14:31 |
| `tools/roles_test.py` | 2026-08-28 18:22 |
| `tools/runtests.py` | 2026-08-29 21:05 |
| `tools/scaletest.py` | 2026-08-27 10:29 |
| `tools/schedule_test.py` | 2026-08-28 22:58 |
| `tools/sdr_test.py` | 2026-08-29 05:23 |
| `tools/sdrsim.py` | 2026-08-29 08:23 |
| `tools/setup_test.py` | 2026-08-30 06:40 |
| `tools/shim_test.py` | 2026-08-27 20:28 |
| `tools/standin_test.py` | 2026-08-29 08:22 |
| `tools/stations_test.py` | 2026-08-28 02:50 |
| `tools/stillweewx_test.py` | 2026-08-29 13:18 |
| `tools/tagcheck.py` | 2026-08-26 23:56 |
| `tools/upload_test.py` | 2026-08-28 22:36 |
| `tools/vantage_test.py` | 2026-08-29 05:23 |
| `tools/vantagesim.py` | 2026-08-29 08:23 |
| `tools/vsop87trim.py` | 2026-08-26 23:48 |
| `tools/watchdog_test.py` | 2026-08-28 14:16 |
| `tools/wunderground_test.py` | 2026-08-28 17:43 |
| `tests/push/conftest.py` | 2026-08-28 17:39 |
| `tests/push/fixtures/README.md` | 2026-08-28 17:37 |
| `tests/push/helpers.py` | 2026-08-28 17:37 |
| `tests/push/test_ambient.py` | 2026-08-28 17:37 |
| `tests/push/test_bridges.py` | 2026-08-28 17:37 |
| `tests/push/test_infer.py` | 2026-08-28 17:37 |
| `tests/push/test_mapping.py` | 2026-08-28 17:37 |
| `tests/push/test_protocols.py` | 2026-08-28 17:37 |
| `tests/push/test_report.py` | 2026-08-28 17:37 |
| `tests/push/test_transport.py` | 2026-08-28 17:37 |
| `tests/push/test_weatherflow.py` | 2026-08-28 17:37 |
| `tests/push/test_wunderground.py` | 2026-08-28 17:37 |
| `deploy/compose.grafana.yml` | 2026-08-29 17:13 |

## Broken references

A `covers` block names a file that does not exist.

| Page | Named |
|---|---|
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/__init__.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/driver.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/protocol.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/mapping.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/infer.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/catalog.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/consoles.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/columns.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/report.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `src/weewx_evo/ingest/plugins/ecowitt/__main__.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `tests/ecowitt/test_protocol.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `tests/ecowitt/test_mapping.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `tests/ecowitt/test_infer.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `tests/ecowitt/test_consoles.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `tests/ecowitt/test_columns.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `tests/ecowitt/test_report.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `tests/ecowitt/test_resilience.py` |
| [Driver: Ecowitt](Driver-Ecowitt) | `tests/ecowitt/conftest.py` |
| [Settings A–Z](Settings-Reference) | `src/weewx_evo/ingest/plugins/ecowitt/driver.py` |
| [Testing](Testing) | `tests/ecowitt/fixtures/README.md` |

---

Generated by `tools/docsindex.py`. See [Contributing](Contributing).

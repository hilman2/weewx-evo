# File index

Which file belongs to which wiki page, and where the page is behind
the code.

**Generated:** 2026-09-04 08:13 · `python tools/docsindex.py`

This page is generated. Edited by hand, it is overwritten on the next
run — the mapping lives in the `covers` blocks at the end of every wiki
page.

## Key

| | |
|---|---|
| ✅ | The page is newer than every file it covers or watches |
| ⚠️ | A covered file was changed **after** the page — worth a look |
| — | The page covers and watches nothing (glossary, navigation) |

"⚠️" means *look*, not *wrong*. Anyone who has looked and had nothing
to change ticks it off:

```bash
python tools/docsindex.py --accept <page>.md
```

## Where things stand

| | |
|---|---|
| Wiki pages | 53 |
| Files covered | 247 of 249 |
| Pages to look at | 26 |
| Files with no page | 5 |

## To look at

| Page | Changed since the page | File last | Page last |
|---|---|---|---|
| ⚠️ [Testing](Testing) | `tools/deck_places_test.py`, `tools/stations_test.py`, `tools/archives_test.py` (+17) | 2026-09-04 08:13 | 2026-09-04 02:15 |
| ⚠️ [Placements](Placements) | `tools/placement_test.py`, `src/weewx_evo/placement.py` | 2026-09-04 08:11 | 2026-09-04 02:02 |
| ⚠️ [The settings page](Admin-Page) | `tools/adminlive_test.py`, `src/weewx_evo/admin.py`, `tools/adminpage.py` (+2) | 2026-09-04 08:00 | 2026-09-04 02:42 |
| ⚠️ [Sending readings on](Sending-readings-on) | `src/weewx_evo/uploads/records.py`, `src/weewx_evo/uploads/runner.py`, `src/weewx_evo/uploads/__init__.py` | 2026-09-04 07:59 | 2026-08-30 12:26 |
| ⚠️ [Uploads](Uploads) | `src/weewx_evo/uploads/records.py`, `src/weewx_evo/uploads/runner.py` | 2026-09-04 07:59 | 2026-09-04 00:42 |
| ⚠️ [Connecting a console](Connecting-a-console) | `src/weewx_evo/stations.py`, `src/weewx_evo/ingest/listener.py` | 2026-09-04 07:57 | 2026-09-04 02:13 |
| ⚠️ [Contributing](Contributing) | `.gitignore` | 2026-09-04 07:38 | 2026-09-04 02:09 |
| ⚠️ [Publishing a website](Publishing-a-website) | `src/weewx_evo/adminpublish.py`, `src/weewx_evo/feeds/__init__.py`, `src/weewx_evo/feeds/cheetah/__init__.py` (+1) | 2026-09-04 02:42 | 2026-08-30 12:26 |
| ⚠️ [Listener](Ingest-Listener) | `src/weewx_evo/ingest/listener.py` | 2026-09-04 02:34 | 2026-09-04 00:50 |
| ⚠️ [Quality control](Quality) | `src/weewx_evo/adminquality.py`, `src/weewx_evo/quality.py` | 2026-09-04 02:07 | 2026-09-04 02:05 |
| ⚠️ [Sensor checks](Sensor-checks) | `src/weewx_evo/adminquality.py`, `src/weewx_evo/quality.py` | 2026-09-04 02:07 | 2026-09-04 02:05 |
| ⚠️ [Charts](Charts) | `src/weewx_evo/adminplots.py`, `src/weewx_evo/plots.py`, `src/weewx_evo/chartdata.py` | 2026-09-04 02:05 | 2026-08-30 12:26 |
| ⚠️ [Plots](Plots) | `src/weewx_evo/adminplots.py` | 2026-09-04 02:05 | 2026-09-04 00:17 |
| ⚠️ [Alerts](Alerts) | `src/weewx_evo/notify/rules.py`, `src/weewx_evo/notify/runner.py` | 2026-09-04 01:09 | 2026-08-30 12:26 |
| ⚠️ [Notifications](Notifications) | `src/weewx_evo/notify/rules.py`, `src/weewx_evo/notify/runner.py` | 2026-09-04 01:09 | 2026-08-30 11:51 |
| ⚠️ [Metrics](Metrics) | `src/weewx_evo/metrics.py` | 2026-09-04 01:09 | 2026-08-30 11:51 |
| ⚠️ [Feeds](Feeds) | `src/weewx_evo/feeds/__init__.py`, `src/weewx_evo/feeds/cheetah/__init__.py`, `src/weewx_evo/feedrunner.py` | 2026-09-04 00:50 | 2026-08-30 12:22 |
| ⚠️ [API](API) | `src/weewx_evo/api.py` | 2026-09-04 00:50 | 2026-09-04 00:37 |
| ⚠️ [Derived readings](Derived-Readings) | `src/weewx_evo/derive.py`, `tools/derive_test.py` | 2026-09-04 00:46 | 2026-08-27 11:03 |
| ⚠️ [MQTT](MQTT) | `src/weewx_evo/ingest/mqttsub.py` | 2026-09-04 00:40 | 2026-08-30 11:51 |
| ⚠️ [Forecast](Forecast) | `src/weewx_evo/forecast/__init__.py` | 2026-09-04 00:38 | 2026-09-04 00:33 |
| ⚠️ [Weather forecast](Weather-forecast) | `src/weewx_evo/forecast/__init__.py`, `src/weewx_evo/forecast/store.py` | 2026-09-04 00:38 | 2026-09-04 00:16 |
| ⚠️ [Web server](Web-Server) | `src/weewx_evo/webserver.py` | 2026-08-30 11:51 | 2026-08-27 11:05 |
| ⚠️ [Series](Series) | `src/weewx_evo/series.py` | 2026-08-29 17:25 | 2026-08-27 11:04 |
| ⚠️ [Exports](Exports) | `src/weewx_evo/exports/runner.py`, `tools/export_test.py`, `src/weewx_evo/exports/ftp.py` (+3) | 2026-08-28 22:56 | 2026-08-27 11:11 |
| ⚠️ [Security](Security) | `src/weewx_evo/netaccess.py` | 2026-08-27 11:41 | 2026-08-27 11:08 |

## Pages

| | Page | Files | Code last | Page last |
|---|---|---|---|---|
| — | [Admin and architecture review — 2026-09-04](Admin-Review-2026-09-04) | — | — | 2026-09-04 02:44 |
| ✅ | [Aggregation](Aggregation) | 3 | 2026-08-26 23:54 | 2026-08-27 11:02 |
| ⚠️ | [Alerts](Alerts) | 7w | 2026-09-04 01:09 | 2026-08-30 12:26 |
| ⚠️ | [API](API) | 1 | 2026-09-04 00:50 | 2026-09-04 00:37 |
| ✅ | [Architecture](Architecture) | 2 | 2026-09-04 00:29 | 2026-09-04 02:01 |
| ✅ | [Archiver](Archiver) | 2 | 2026-09-04 02:07 | 2026-09-04 02:15 |
| ✅ | [Backups](Backups) | 1w | 2026-08-29 15:59 | 2026-08-30 12:26 |
| ⚠️ | [Charts](Charts) | 4w | 2026-09-04 02:05 | 2026-08-30 12:26 |
| ✅ | [CLI reference](CLI-Reference) | 3 +1w | 2026-09-04 08:00 | 2026-09-04 08:09 |
| ✅ | [Configuration](Configuration) | 4 | 2026-09-04 02:02 | 2026-09-04 08:00 |
| ⚠️ | [Connecting a console](Connecting-a-console) | 40w | 2026-09-04 07:57 | 2026-09-04 02:13 |
| ⚠️ | [Contributing](Contributing) | 5 +20w | 2026-09-04 07:38 | 2026-09-04 02:09 |
| ✅ | [Daily summaries](Daily-Summaries) | 1 | 2026-08-26 23:56 | 2026-08-27 11:03 |
| ✅ | [Deck](Deck) | 6 | 2026-08-30 14:53 | 2026-09-04 00:18 |
| ✅ | [Deployment](Deployment) | 3 +9w | 2026-09-04 00:29 | 2026-09-04 08:10 |
| ⚠️ | [Derived readings](Derived-Readings) | 2 | 2026-09-04 00:46 | 2026-08-27 11:03 |
| ✅ | [Drivers](Drivers) | 32 | 2026-09-04 02:11 | 2026-09-04 02:14 |
| ⚠️ | [Exports](Exports) | 7 | 2026-08-28 22:56 | 2026-08-27 11:11 |
| ⚠️ | [Feeds](Feeds) | 10 | 2026-09-04 00:50 | 2026-08-30 12:22 |
| ⚠️ | [Forecast](Forecast) | 9 | 2026-09-04 00:38 | 2026-09-04 00:33 |
| ✅ | [Getting started](Getting-Started) | 1 +2w | 2026-09-04 08:00 | 2026-09-04 08:10 |
| — | [Glossary](Glossary) | — | — | 2026-09-04 02:11 |
| ✅ | [Grafana](Grafana) | 9 | 2026-08-30 11:51 | 2026-09-04 01:52 |
| ⚠️ | [Listener](Ingest-Listener) | 4 | 2026-09-04 02:34 | 2026-09-04 00:50 |
| ✅ | [Maintenance](Maintenance) | 1 | 2026-08-29 15:59 | 2026-08-30 11:51 |
| ⚠️ | [Metrics](Metrics) | 1 | 2026-09-04 01:09 | 2026-08-30 11:51 |
| ⚠️ | [MQTT](MQTT) | 4 | 2026-09-04 00:40 | 2026-08-30 11:51 |
| ✅ | [Multiple senders](Multiple-Sources) | 2 | 2026-09-04 02:02 | 2026-09-04 02:14 |
| ⚠️ | [Notifications](Notifications) | 6 | 2026-09-04 01:09 | 2026-08-30 11:51 |
| ⚠️ | [Placements](Placements) | 3 | 2026-09-04 08:11 | 2026-09-04 02:02 |
| ⚠️ | [Plots](Plots) | 8 | 2026-09-04 02:05 | 2026-09-04 00:17 |
| — | [Plugins](Plugins) | — | — | 2026-09-03 22:26 |
| ⚠️ | [Publishing a website](Publishing-a-website) | 22w | 2026-09-04 02:42 | 2026-08-30 12:26 |
| ✅ | [Push drivers](Driver-Ecowitt) | 11 | 2026-08-28 17:39 | 2026-09-04 02:09 |
| ⚠️ | [Quality control](Quality) | 2 | 2026-09-04 02:07 | 2026-09-04 02:05 |
| ⚠️ | [Security](Security) | 2 | 2026-08-27 11:41 | 2026-08-27 11:08 |
| ⚠️ | [Sending readings on](Sending-readings-on) | 12w | 2026-09-04 07:59 | 2026-08-30 12:26 |
| ⚠️ | [Sensor checks](Sensor-checks) | 2w | 2026-09-04 02:07 | 2026-09-04 02:05 |
| ⚠️ | [Series](Series) | 2 | 2026-08-29 17:25 | 2026-08-27 11:04 |
| ✅ | [Settings A–Z](Settings-Reference) | 5 +2w | 2026-09-04 07:53 | 2026-09-04 08:10 |
| ✅ | [Several places](Places) | 2 +1w | 2026-09-04 07:59 | 2026-09-04 08:10 |
| ✅ | [Stations and Archives](Stations-and-Archives) | 5 | 2026-09-04 07:57 | 2026-09-04 08:10 |
| ✅ | [Sun](Sun) | 5 | 2026-08-26 23:56 | 2026-08-30 11:51 |
| ⚠️ | [Testing](Testing) | 73 | 2026-09-04 08:13 | 2026-09-04 02:15 |
| ✅ | [The archive database](Database-Archive) | 3 | 2026-09-03 23:25 | 2026-09-04 02:11 |
| ✅ | [The live database](Database-Live) | 1 | 2026-09-04 07:52 | 2026-09-04 08:10 |
| ⚠️ | [The settings page](Admin-Page) | 10 | 2026-09-04 08:00 | 2026-09-04 02:42 |
| ✅ | [Units](Units) | 2 | 2026-08-29 15:29 | 2026-08-30 11:51 |
| ⚠️ | [Uploads](Uploads) | 11 | 2026-09-04 07:59 | 2026-09-04 00:42 |
| ⚠️ | [Weather forecast](Weather-forecast) | 9w | 2026-09-04 00:38 | 2026-09-04 00:16 |
| ⚠️ | [Web server](Web-Server) | 2 | 2026-08-30 11:51 | 2026-08-27 11:05 |
| ✅ | [WeeWX compatibility](WeeWX-Compatibility) | 2 | 2026-08-29 12:47 | 2026-09-04 08:10 |
| ✅ | [weewx-evo](Home) | 7 | 2026-09-04 02:01 | 2026-09-04 02:13 |

## Files

| File | Lines | Wiki page | Last changed |
|---|---|---|---|
| `src/weewx_evo/__init__.py` | 8 | [Architecture](Architecture) · [weewx-evo](Home) | 2026-08-26 10:53 |
| `src/weewx_evo/admin.py` | 4314 | ⚠️ [The settings page](Admin-Page) | 2026-09-04 07:36 |
| `src/weewx_evo/adminarchives.py` | 1123 | [Several places](Places) | 2026-09-04 07:59 |
| `src/weewx_evo/adminfields.py` | 774 | [The settings page](Admin-Page) | 2026-09-04 01:52 |
| `src/weewx_evo/adminhome.py` | 1087 | [The settings page](Admin-Page) | 2026-09-04 02:42 |
| `src/weewx_evo/adminlive.py` | 609 | [The settings page](Admin-Page) | 2026-09-04 01:45 |
| `src/weewx_evo/adminplots.py` | 1009 | ⚠️ [Plots](Plots) | 2026-09-04 02:05 |
| `src/weewx_evo/adminpublish.py` | 450 | [The settings page](Admin-Page) | 2026-09-04 02:42 |
| `src/weewx_evo/adminquality.py` | 483 | ⚠️ [Quality control](Quality) | 2026-09-04 02:07 |
| `src/weewx_evo/adminsearch.py` | 228 | ⚠️ [The settings page](Admin-Page) | 2026-09-04 07:34 |
| `src/weewx_evo/adminsetup.py` | 426 | [The settings page](Admin-Page) | 2026-09-04 02:05 |
| `src/weewx_evo/adminstations.py` | 1138 | [Several places](Places) | 2026-09-04 01:52 |
| `src/weewx_evo/adminsystem.py` | 82 | ⚠️ [The settings page](Admin-Page) | 2026-09-04 07:34 |
| `src/weewx_evo/adopt.py` | 400 | [Stations and Archives](Stations-and-Archives) | 2026-08-29 14:31 |
| `src/weewx_evo/aggregate.py` | 497 | [Aggregation](Aggregation) · [Contributing](Contributing) | 2026-08-26 23:43 |
| `src/weewx_evo/api.py` | 529 | ⚠️ [API](API) | 2026-09-04 00:50 |
| `src/weewx_evo/archiver.py` | 543 | [Archiver](Archiver) | 2026-09-04 02:07 |
| `src/weewx_evo/archives.py` | 924 | [Stations and Archives](Stations-and-Archives) | 2026-09-04 07:53 |
| `src/weewx_evo/chartdata.py` | 829 | [Plots](Plots) | 2026-08-30 14:53 |
| `src/weewx_evo/cli.py` | 6459 | [CLI reference](CLI-Reference) | 2026-09-04 08:00 |
| `src/weewx_evo/collectors.py` | 452 | [Stations and Archives](Stations-and-Archives) | 2026-09-04 00:40 |
| `src/weewx_evo/config.py` | 324 | [Configuration](Configuration) | 2026-08-30 14:53 |
| `src/weewx_evo/db/__init__.py` | 0 | [weewx-evo](Home) | 2026-08-26 10:58 |
| `src/weewx_evo/db/archive.py` | 481 | [The archive database](Database-Archive) | 2026-09-03 23:25 |
| `src/weewx_evo/db/daily.py` | 116 | [Daily summaries](Daily-Summaries) | 2026-08-26 23:56 |
| `src/weewx_evo/db/live.py` | 705 | [The live database](Database-Live) | 2026-09-04 07:52 |
| `src/weewx_evo/db/schema.py` | 86 | [The archive database](Database-Archive) | 2026-08-26 10:57 |
| `src/weewx_evo/db/wview.py` | 137 | [The archive database](Database-Archive) · [WeeWX compatibility](WeeWX-Compatibility) | 2026-08-26 23:53 |
| `src/weewx_evo/derive.py` | 1160 | ⚠️ [Derived readings](Derived-Readings) | 2026-09-04 00:46 |
| `src/weewx_evo/dumps.py` | 613 | [CLI reference](CLI-Reference) | 2026-08-29 17:58 |
| `src/weewx_evo/dumpscsv.py` | 417 | [CLI reference](CLI-Reference) | 2026-08-29 18:01 |
| `src/weewx_evo/exports/__init__.py` | 408 | ⚠️ [Exports](Exports) | 2026-08-28 20:17 |
| `src/weewx_evo/exports/ftp.py` | 399 | ⚠️ [Exports](Exports) · [Settings A–Z](Settings-Reference) | 2026-08-28 21:54 |
| `src/weewx_evo/exports/livepush/__init__.py` | 199 | [Uploads](Uploads) | 2026-08-30 11:51 |
| `src/weewx_evo/exports/local.py` | 414 | ⚠️ [Exports](Exports) · [Settings A–Z](Settings-Reference) | 2026-08-28 21:54 |
| `src/weewx_evo/exports/record.py` | 131 | [Notifications](Notifications) | 2026-08-29 15:25 |
| `src/weewx_evo/exports/rsync.py` | 351 | ⚠️ [Exports](Exports) · [Settings A–Z](Settings-Reference) | 2026-08-28 21:54 |
| `src/weewx_evo/exports/runner.py` | 509 | ⚠️ [Exports](Exports) | 2026-08-28 22:56 |
| `src/weewx_evo/exports/tracker.py` | 165 | [Exports](Exports) | 2026-08-26 13:31 |
| `src/weewx_evo/feedrunner.py` | 358 | ⚠️ [Feeds](Feeds) | 2026-09-04 00:35 |
| `src/weewx_evo/feeds/__init__.py` | 372 | ⚠️ [Feeds](Feeds) | 2026-09-04 00:50 |
| `src/weewx_evo/feeds/cheetah/__init__.py` | 2534 | ⚠️ [Feeds](Feeds) | 2026-09-04 00:37 |
| `src/weewx_evo/feeds/diagnostic/__init__.py` | 557 | [Feeds](Feeds) | 2026-08-30 11:51 |
| `src/weewx_evo/feeds/diagnostic/vendor/LICENSE` | 21 | [Feeds](Feeds) | 2026-08-26 15:12 |
| `src/weewx_evo/feeds/imagegenerator/__init__.py` | 821 | [Plots](Plots) | 2026-08-30 11:51 |
| `src/weewx_evo/feeds/imagegenerator/canvas.py` | 410 | [Plots](Plots) | 2026-08-26 23:47 |
| `src/weewx_evo/feeds/imagegenerator/theme.py` | 225 | [Plots](Plots) | 2026-08-26 23:56 |
| `src/weewx_evo/feeds/jsongenerator/__init__.py` | 816 | [Feeds](Feeds) · [Settings A–Z](Settings-Reference) | 2026-08-30 11:51 |
| `src/weewx_evo/feeds/realtime/__init__.py` | 273 | [Feeds](Feeds) | 2026-08-27 10:35 |
| `src/weewx_evo/forecast/__init__.py` | 440 | ⚠️ [Forecast](Forecast) | 2026-09-04 00:38 |
| `src/weewx_evo/forecast/codes.py` | 110 | [Forecast](Forecast) | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/dwd.py` | 487 | [Forecast](Forecast) | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/meteoalarm.py` | 267 | [Forecast](Forecast) | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/nws.py` | 308 | [Forecast](Forecast) | 2026-08-27 10:33 |
| `src/weewx_evo/forecast/openmeteo.py` | 291 | [Forecast](Forecast) | 2026-08-27 19:38 |
| `src/weewx_evo/forecast/runner.py` | 324 | [Forecast](Forecast) | 2026-08-30 11:51 |
| `src/weewx_evo/forecast/store.py` | 481 | [Forecast](Forecast) | 2026-09-04 00:33 |
| `src/weewx_evo/forecast/tags.py` | 511 | [Forecast](Forecast) | 2026-08-30 11:51 |
| `src/weewx_evo/grafana/__init__.py` | 333 | [Grafana](Grafana) | 2026-08-29 17:03 |
| `src/weewx_evo/grafana/dashboards.py` | 405 | [Grafana](Grafana) | 2026-08-30 11:51 |
| `src/weewx_evo/grafana/icons.py` | 201 | [Grafana](Grafana) | 2026-08-29 17:10 |
| `src/weewx_evo/grafana/panels.py` | 501 | [Grafana](Grafana) | 2026-08-29 17:03 |
| `src/weewx_evo/grafana/query_influx.py` | 330 | [Grafana](Grafana) | 2026-08-29 17:02 |
| `src/weewx_evo/grafana/style.py` | 240 | [Grafana](Grafana) | 2026-08-29 14:34 |
| `src/weewx_evo/grafana/words.py` | 130 | [Grafana](Grafana) | 2026-08-29 17:02 |
| `src/weewx_evo/ingest/__init__.py` | 0 | [weewx-evo](Home) | 2026-08-26 11:20 |
| `src/weewx_evo/ingest/drivers.py` | 729 | [Drivers](Drivers) | 2026-09-04 02:02 |
| `src/weewx_evo/ingest/envelope.py` | 83 | [Drivers](Drivers) | 2026-09-03 23:25 |
| `src/weewx_evo/ingest/listener.py` | 764 | ⚠️ [Listener](Ingest-Listener) | 2026-09-04 02:34 |
| `src/weewx_evo/ingest/mqttsub.py` | 374 | ⚠️ [MQTT](MQTT) | 2026-09-04 00:40 |
| `src/weewx_evo/ingest/parsers.py` | 136 | [Drivers](Drivers) | 2026-09-03 23:25 |
| `src/weewx_evo/ingest/plugins/__init__.py` | 71 | [Drivers](Drivers) | 2026-08-26 11:50 |
| `src/weewx_evo/ingest/plugins/push/__init__.py` | 13 | [Drivers](Drivers) | 2026-08-28 17:33 |
| `src/weewx_evo/ingest/plugins/push/catalogs/__init__.py` | 31 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/acurite.py` | 88 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/ambient.py` | 308 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/ecowitt.py` | 1074 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/lacrosse.py` | 98 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/weatherflow.py` | 169 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/catalogs/wunderground.py` | 316 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/driver.py` | 637 | [Drivers](Drivers) | 2026-09-04 02:02 |
| `src/weewx_evo/ingest/plugins/push/infer.py` | 204 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/mapping.py` | 245 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/__init__.py` | 296 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/acurite.py` | 143 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/ambient.py` | 90 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/ecowitt.py` | 88 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/lacrosse.py` | 121 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/weatherflow.py` | 178 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/protocols/wunderground.py` | 186 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/report.py` | 72 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/roles.py` | 94 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/plugins/push/transport.py` | 201 | [Drivers](Drivers) | 2026-08-28 17:09 |
| `src/weewx_evo/ingest/proposals.py` | 233 | [Placements](Placements) | 2026-09-03 23:23 |
| `src/weewx_evo/ingest/sightings.py` | 243 | [Drivers](Drivers) | 2026-08-27 23:12 |
| `src/weewx_evo/ingest/state.py` | 157 | [Drivers](Drivers) | 2026-09-04 02:11 |
| `src/weewx_evo/ingest/statuspage.py` | 498 | [Listener](Ingest-Listener) | 2026-09-03 23:25 |
| `src/weewx_evo/ingest/userdrivers.py` | 321 | [Drivers](Drivers) | 2026-08-26 23:56 |
| `src/weewx_evo/ingest/weewxdrivers.py` | 910 | [Drivers](Drivers) | 2026-08-30 19:19 |
| `src/weewx_evo/ingest/weewxnames.py` | 613 | [Drivers](Drivers) | 2026-08-29 04:59 |
| `src/weewx_evo/ingest/weewxshim.py` | 601 | [Drivers](Drivers) | 2026-09-03 23:25 |
| `src/weewx_evo/lang/de.toml` | 228 | **none** | 2026-08-30 11:51 |
| `src/weewx_evo/language.py` | 314 | **none** | 2026-08-29 14:34 |
| `src/weewx_evo/maintenance.py` | 511 | [Maintenance](Maintenance) | 2026-08-29 15:59 |
| `src/weewx_evo/metrics.py` | 340 | ⚠️ [Metrics](Metrics) | 2026-09-04 01:09 |
| `src/weewx_evo/moon.py` | 569 | [Sun](Sun) | 2026-08-26 20:42 |
| `src/weewx_evo/mqtt.py` | 503 | [MQTT](MQTT) | 2026-08-27 11:27 |
| `src/weewx_evo/netaccess.py` | 138 | ⚠️ [Security](Security) | 2026-08-27 11:41 |
| `src/weewx_evo/notify/__init__.py` | 380 | [Notifications](Notifications) | 2026-08-29 15:27 |
| `src/weewx_evo/notify/mqtt.py` | 151 | [MQTT](MQTT) | 2026-08-29 15:24 |
| `src/weewx_evo/notify/rules.py` | 347 | ⚠️ [Notifications](Notifications) | 2026-09-04 01:09 |
| `src/weewx_evo/notify/runner.py` | 180 | ⚠️ [Notifications](Notifications) | 2026-09-03 23:25 |
| `src/weewx_evo/notify/smtp.py` | 161 | [Notifications](Notifications) | 2026-08-29 15:27 |
| `src/weewx_evo/notify/webhook.py` | 224 | [Notifications](Notifications) | 2026-08-29 15:36 |
| `src/weewx_evo/obstypes.py` | 80 | [Aggregation](Aggregation) · [Contributing](Contributing) | 2026-08-26 10:54 |
| `src/weewx_evo/options.py` | 877 | [Configuration](Configuration) · [Settings A–Z](Settings-Reference) | 2026-09-04 02:02 |
| `src/weewx_evo/placement.py` | 899 | ⚠️ [Placements](Placements) | 2026-09-04 07:56 |
| `src/weewx_evo/planets.py` | 625 | [Sun](Sun) | 2026-08-26 23:56 |
| `src/weewx_evo/plots.py` | 1114 | [Plots](Plots) | 2026-08-30 14:53 |
| `src/weewx_evo/quality.py` | 848 | ⚠️ [Quality control](Quality) | 2026-09-04 02:07 |
| `src/weewx_evo/ratelimit.py` | 205 | [Security](Security) | 2026-08-26 23:43 |
| `src/weewx_evo/roles.py` | 149 | [Stations and Archives](Stations-and-Archives) | 2026-09-04 02:33 |
| `src/weewx_evo/schedule.py` | 74 | [Feeds](Feeds) | 2026-08-28 22:42 |
| `src/weewx_evo/series.py` | 1116 | ⚠️ [Series](Series) | 2026-08-29 17:25 |
| `src/weewx_evo/settings.py` | 396 | [Configuration](Configuration) | 2026-09-04 00:45 |
| `src/weewx_evo/skinkit.py` | 825 | [Feeds](Feeds) | 2026-08-27 19:38 |
| `src/weewx_evo/skins/__init__.py` | 26 | [Deck](Deck) | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/CHANGES.md` | 138 | [Deck](Deck) | 2026-08-30 11:51 |
| `src/weewx_evo/skins/deck/LICENSE` | 674 | **none** | 2026-08-26 22:35 |
| `src/weewx_evo/skins/deck/README.md` | 98 | [Deck](Deck) | 2026-08-30 11:51 |
| `src/weewx_evo/skins/deck/options.py` | 392 | [Deck](Deck) | 2026-08-30 14:53 |
| `src/weewx_evo/skins/deck/tags.py` | 3453 | [Deck](Deck) | 2026-08-30 11:51 |
| `src/weewx_evo/sources.py` | 165 | [Multiple senders](Multiple-Sources) | 2026-08-26 23:47 |
| `src/weewx_evo/starter/__init__.py` | 142 | [Plots](Plots) | 2026-08-29 13:34 |
| `src/weewx_evo/starter/plots.toml` | 2146 | [Plots](Plots) | 2026-08-29 14:31 |
| `src/weewx_evo/stations.py` | 415 | [Stations and Archives](Stations-and-Archives) | 2026-09-04 07:57 |
| `src/weewx_evo/sun.py` | 675 | [Sun](Sun) | 2026-08-26 23:47 |
| `src/weewx_evo/tags.py` | 1879 | [Feeds](Feeds) | 2026-08-30 11:51 |
| `src/weewx_evo/units.py` | 1174 | [Units](Units) | 2026-08-29 15:29 |
| `src/weewx_evo/uploads/__init__.py` | 529 | [Uploads](Uploads) | 2026-09-04 00:38 |
| `src/weewx_evo/uploads/ambient.py` | 312 | [Uploads](Uploads) | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/cwop.py` | 304 | [Uploads](Uploads) | 2026-08-27 13:03 |
| `src/weewx_evo/uploads/homeassistant.py` | 181 | [Uploads](Uploads) | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/influx.py` | 568 | [Grafana](Grafana) | 2026-08-30 11:51 |
| `src/weewx_evo/uploads/mqtt.py` | 445 | [MQTT](MQTT) | 2026-08-27 11:09 |
| `src/weewx_evo/uploads/progress.py` | 106 | [Uploads](Uploads) | 2026-08-29 14:48 |
| `src/weewx_evo/uploads/records.py` | 828 | ⚠️ [Uploads](Uploads) | 2026-09-04 07:59 |
| `src/weewx_evo/uploads/runner.py` | 609 | ⚠️ [Uploads](Uploads) | 2026-09-04 01:15 |
| `src/weewx_evo/uploads/weathercloud.py` | 164 | [Uploads](Uploads) | 2026-08-27 10:33 |
| `src/weewx_evo/uploads/webpush.py` | 717 | [Uploads](Uploads) | 2026-08-30 11:51 |
| `src/weewx_evo/uploads/windy.py` | 155 | [Uploads](Uploads) | 2026-08-27 10:33 |
| `src/weewx_evo/vsop87.py` | 2381 | [Sun](Sun) | 2026-08-26 23:48 |
| `src/weewx_evo/watchdog.py` | 302 | **none** | 2026-08-28 13:02 |
| `src/weewx_evo/webserver.py` | 512 | ⚠️ [Web server](Web-Server) | 2026-08-30 11:51 |
| `src/weewx_evo/weewxconf.py` | 544 | [WeeWX compatibility](WeeWX-Compatibility) | 2026-08-29 12:47 |
| `tools/adminfields_test.py` | 725 | ⚠️ [Testing](Testing) | 2026-09-04 08:11 |
| `tools/adminhome_test.py` | 912 | ⚠️ [Testing](Testing) | 2026-09-04 08:12 |
| `tools/adminlive_test.py` | 504 | ⚠️ [The settings page](Admin-Page) | 2026-09-04 08:00 |
| `tools/adminpage.py` | 1455 | ⚠️ [The settings page](Admin-Page) · [Testing](Testing) | 2026-09-04 07:34 |
| `tools/adminsearch_test.py` | 177 | [Testing](Testing) | 2026-09-04 02:02 |
| `tools/alldrivers_test.py` | 344 | [Testing](Testing) | 2026-08-29 05:23 |
| `tools/api_test.py` | 495 | [Testing](Testing) | 2026-09-04 00:52 |
| `tools/archives_e2e.py` | 709 | ⚠️ [Testing](Testing) | 2026-09-04 08:08 |
| `tools/archives_test.py` | 1343 | ⚠️ [Testing](Testing) | 2026-09-04 08:13 |
| `tools/cheetah_test.py` | 753 | [Testing](Testing) | 2026-08-29 15:29 |
| `tools/collector_test.py` | 236 | ⚠️ [Testing](Testing) | 2026-09-04 07:34 |
| `tools/console_setup_test.py` | 316 | **none** | 2026-09-03 23:23 |
| `tools/deck_dead_test.py` | 261 | [Testing](Testing) | 2026-08-29 01:55 |
| `tools/deck_live_test.py` | 1056 | ⚠️ [Testing](Testing) | 2026-09-04 07:30 |
| `tools/deck_places_test.py` | 1057 | ⚠️ [Testing](Testing) | 2026-09-04 08:13 |
| `tools/deck_test.py` | 864 | [Testing](Testing) | 2026-09-04 00:34 |
| `tools/derive_test.py` | 521 | ⚠️ [Derived readings](Derived-Readings) · [Testing](Testing) | 2026-08-27 19:38 |
| `tools/difftest.py` | 133 | [Aggregation](Aggregation) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/driverinstall.py` | 225 | [Drivers](Drivers) · [Testing](Testing) | 2026-09-03 23:25 |
| `tools/driversim.py` | 266 | [Testing](Testing) | 2026-08-29 05:23 |
| `tools/ecowittsim.py` | 254 | [Testing](Testing) | 2026-08-30 11:51 |
| `tools/export_test.py` | 1068 | ⚠️ [Exports](Exports) · [Testing](Testing) | 2026-08-28 22:09 |
| `tools/feeds_test.py` | 201 | ⚠️ [Testing](Testing) | 2026-09-04 02:27 |
| `tools/feedtiming_test.py` | 337 | ⚠️ [Testing](Testing) | 2026-09-04 08:00 |
| `tools/forecast_test.py` | 840 | [Testing](Testing) | 2026-08-30 11:51 |
| `tools/fousb_test.py` | 287 | [Testing](Testing) | 2026-08-29 05:23 |
| `tools/fousbsim.py` | 245 | [Testing](Testing) | 2026-08-29 08:23 |
| `tools/grafana_test.py` | 836 | [Testing](Testing) | 2026-08-29 17:14 |
| `tools/image_test.py` | 392 | [Testing](Testing) | 2026-08-29 15:29 |
| `tools/import_test.py` | 751 | [Testing](Testing) | 2026-08-29 18:00 |
| `tools/influx_test.py` | 1026 | [Testing](Testing) | 2026-09-03 23:25 |
| `tools/livedb_test.py` | 318 | ⚠️ [Testing](Testing) | 2026-09-04 08:11 |
| `tools/livesource_test.py` | 371 | ⚠️ [Testing](Testing) | 2026-09-04 08:05 |
| `tools/maintenance_test.py` | 510 | [Testing](Testing) | 2026-08-29 17:08 |
| `tools/metrics_test.py` | 428 | ⚠️ [Testing](Testing) | 2026-09-04 02:25 |
| `tools/mooncheck.py` | 208 | [Testing](Testing) | 2026-08-26 23:43 |
| `tools/mqtt_test.py` | 823 | [Testing](Testing) | 2026-09-03 23:25 |
| `tools/multisource.py` | 262 | [Multiple senders](Multiple-Sources) · [Testing](Testing) | 2026-09-04 02:02 |
| `tools/netaccess_test.py` | 156 | [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/notify_test.py` | 690 | [Testing](Testing) | 2026-09-03 23:25 |
| `tools/placement_test.py` | 1198 | ⚠️ [Placements](Placements) | 2026-09-04 08:11 |
| `tools/planetcheck.py` | 295 | [Testing](Testing) | 2026-08-26 23:56 |
| `tools/quality_test.py` | 1085 | ⚠️ [Testing](Testing) | 2026-09-04 08:08 |
| `tools/ratelimit_test.py` | 168 | [Listener](Ingest-Listener) · [Testing](Testing) | 2026-08-26 23:43 |
| `tools/realtime_test.py` | 201 | [Testing](Testing) | 2026-08-27 10:37 |
| `tools/resilience_test.py` | 474 | ⚠️ [Testing](Testing) | 2026-09-04 07:37 |
| `tools/restart_test.py` | 287 | [Testing](Testing) | 2026-09-03 23:25 |
| `tools/roles_test.py` | 323 | ⚠️ [Testing](Testing) | 2026-09-04 08:06 |
| `tools/roundtrip.py` | 239 | [Archiver](Archiver) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/runtests.py` | 488 | ⚠️ [Testing](Testing) | 2026-09-04 02:31 |
| `tools/scaletest.py` | 302 | [Testing](Testing) | 2026-08-27 10:29 |
| `tools/schedule_test.py` | 234 | [Testing](Testing) | 2026-08-28 22:58 |
| `tools/sdr_test.py` | 312 | [Testing](Testing) | 2026-08-29 05:23 |
| `tools/sdrsim.py` | 148 | [Testing](Testing) | 2026-08-29 08:23 |
| `tools/seriestest.py` | 375 | [Series](Series) · [Testing](Testing) | 2026-08-26 23:54 |
| `tools/settings_test.py` | 430 | [Configuration](Configuration) · [Testing](Testing) | 2026-09-04 00:22 |
| `tools/setup_test.py` | 467 | [Testing](Testing) | 2026-09-04 02:07 |
| `tools/shim_test.py` | 411 | [Testing](Testing) | 2026-09-03 23:25 |
| `tools/smoke.py` | 321 | [Testing](Testing) | 2026-09-03 23:25 |
| `tools/standin_test.py` | 557 | [Testing](Testing) | 2026-08-29 08:22 |
| `tools/stations_test.py` | 613 | ⚠️ [Testing](Testing) | 2026-09-04 08:13 |
| `tools/stillweewx_test.py` | 472 | [Testing](Testing) | 2026-08-29 13:18 |
| `tools/suncheck.py` | 243 | [Sun](Sun) · [Testing](Testing) | 2026-08-26 23:55 |
| `tools/tagcheck.py` | 343 | [Testing](Testing) | 2026-08-26 23:56 |
| `tools/unitcheck.py` | 247 | [Testing](Testing) · [Units](Units) | 2026-08-27 13:03 |
| `tools/upload_test.py` | 411 | ⚠️ [Testing](Testing) | 2026-09-04 07:34 |
| `tools/vantage_test.py` | 317 | [Testing](Testing) | 2026-08-29 05:23 |
| `tools/vantagesim.py` | 401 | [Testing](Testing) | 2026-08-29 08:23 |
| `tools/vsop87trim.py` | 282 | [Testing](Testing) | 2026-08-26 23:48 |
| `tools/watchdog_test.py` | 386 | ⚠️ [Testing](Testing) | 2026-09-04 02:27 |
| `tools/web_test.py` | 219 | [Testing](Testing) · [Web server](Web-Server) | 2026-08-26 23:43 |
| `tools/weewxdrivers_test.py` | 495 | [Testing](Testing) | 2026-08-30 19:19 |
| `tools/wunderground_test.py` | 314 | [Testing](Testing) | 2026-09-04 01:18 |
| `tests/push/conftest.py` | 88 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:39 |
| `tests/push/fixtures/README.md` | 12 | [Testing](Testing) | 2026-08-28 17:37 |
| `tests/push/helpers.py` | 70 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `tests/push/test_ambient.py` | 110 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `tests/push/test_bridges.py` | 169 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `tests/push/test_infer.py` | 108 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `tests/push/test_mapping.py` | 292 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `tests/push/test_protocols.py` | 149 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `tests/push/test_report.py` | 52 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `tests/push/test_transport.py` | 124 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `tests/push/test_weatherflow.py` | 207 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `tests/push/test_wunderground.py` | 248 | [Push drivers](Driver-Ecowitt) | 2026-08-28 17:37 |
| `deploy/Dockerfile` | 56 | [Deployment](Deployment) | 2026-08-26 20:40 |
| `deploy/compose.grafana.yml` | 120 | [Grafana](Grafana) | 2026-08-29 17:13 |
| `deploy/compose.yml` | 96 | [Deployment](Deployment) | 2026-09-04 00:29 |
| `deploy/split.yml` | 88 | [Architecture](Architecture) · [Deployment](Deployment) | 2026-09-04 00:29 |
| `README.md` | 140 | [Getting started](Getting-Started) · [weewx-evo](Home) | 2026-09-04 02:01 |
| `CLAUDE.md` | 2760 | [Contributing](Contributing) · [weewx-evo](Home) | 2026-09-03 20:49 |
| `pyproject.toml` | 147 | [weewx-evo](Home) · [Testing](Testing) | 2026-08-28 17:40 |
| `.gitignore` | 74 | ⚠️ [Contributing](Contributing) | 2026-09-04 07:38 |
| `LICENSE` | 674 | [weewx-evo](Home) | 2026-08-26 15:37 |

## With no page

No `covers` block names these files. Either they belong in an
existing page, or one is missing.

| File | Last changed |
|---|---|
| `src/weewx_evo/lang/de.toml` | 2026-08-30 11:51 |
| `src/weewx_evo/language.py` | 2026-08-29 14:34 |
| `src/weewx_evo/skins/deck/LICENSE` | 2026-08-26 22:35 |
| `src/weewx_evo/watchdog.py` | 2026-08-28 13:02 |
| `tools/console_setup_test.py` | 2026-09-03 23:23 |

---

Generated by `tools/docsindex.py`. See [Contributing](Contributing).

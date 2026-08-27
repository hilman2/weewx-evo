# API-Index

Jede öffentliche Klasse, Funktion und Methode, ihre Datei und die
Wiki-Seite, die sie beschreibt.

**Erzeugt:** 2026-08-27 10:56 · `python tools/docsindex.py`

Private Namen (`_foo`) fehlen, `__init__` ist dabei. Wer einen Namen
sucht, benutzt die Suche des Browsers.

## `src/weewx_evo/admin.py`

[Die Einstellungsseite](Admin-Page) · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `export_kinds` | 45 | The kinds of export that can be added. Asked, not listed. |
| f | `feed_kinds` | 52 | The kinds of feed that can be added. Asked, not listed. |
| f | `feed_kind_choices` | 59 | Each kind, and what it is for. |
| f | `export_kind_choices` | 66 | Each kind, what it is called, and what it is for. A dropdown reading `ftp / local / rsync` asks somebody to a… |
| f | `upload_kinds` | 81 | The kinds of upload that can be added. Asked, not listed. |
| f | `upload_kind_choices` | 88 | Each service, what it is called, and what it is for. The same reasoning as the exports: a dropdown reading `a… |
| f | `forecast_kinds` | 104 | The forecast sources that can be added. Asked, not listed. |
| f | `forecast_kind_choices` | 111 |  |
| **C** | `Admin` | 145 | What the pages do, without the HTTP. |
| · | &nbsp;&nbsp;`Admin.__init__` | 148 |  |
| · | &nbsp;&nbsp;`Admin.schemas` | 175 |  |
| · | &nbsp;&nbsp;`Admin.refresh` | 180 | Rebuild the list of pages. After anything is added or removed. |
| · | &nbsp;&nbsp;`Admin.config` | 184 |  |
| · | &nbsp;&nbsp;`Admin.values` | 187 |  |
| · | &nbsp;&nbsp;`Admin.add_export` | 192 | Create an export. Returns an error, or empty if it worked. Only the name and the kind: ev… |
| · | &nbsp;&nbsp;`Admin.add_feed` | 223 | Create a feed. Returns an error, or empty if it worked. Only the name and the kind. Every… |
| · | &nbsp;&nbsp;`Admin.remove_feed` | 264 | Delete a feed. What it already wrote is left where it is. |
| · | &nbsp;&nbsp;`Admin.add_upload` | 281 | Create an upload. Returns an error, or empty if it worked. Name and kind only, like an ex… |
| · | &nbsp;&nbsp;`Admin.remove_upload` | 310 | Delete an upload. Nothing is withdrawn from the service. |
| · | &nbsp;&nbsp;`Admin.test_upload` | 327 | Try one service and say what it answered. Worth more here than anywhere else on this page… |
| · | &nbsp;&nbsp;`Admin.add_forecast` | 356 | Create a forecast source. Name and kind only, like the rest. |
| · | &nbsp;&nbsp;`Admin.remove_forecast` | 381 | Delete a forecast source. What it fetched stays until it is pruned. |
| · | &nbsp;&nbsp;`Admin.test_forecast` | 398 | Fetch once and say what came back, storing nothing. This button does double duty: a MOSMI… |
| · | &nbsp;&nbsp;`Admin.remove_export` | 430 | Delete an export from the configuration. Nothing at the far end. |
| · | &nbsp;&nbsp;`Admin.columns` | 447 | The readings the archive has a column for. Asked of the database rather than of a schema:… |
| · | &nbsp;&nbsp;`Admin.test_export` | 470 | Try one export's destination and say what happened. |
| · | &nbsp;&nbsp;`Admin.save` | 486 | Check a form and write it. Returns what was wrong, empty if nothing. Everything is valida… |
| f | `field` | 541 | One setting as a form field. |
| f | `group_html` | 637 |  |
| f | `new_export_page` | 661 | The form that creates one. Two fields, and nothing else yet. |
| f | `new_upload_page` | 707 | The form that creates one. A name and a service. |
| f | `new_forecast_page` | 753 | A name and a source. The rest waits. |
| f | `new_feed_page` | 801 | Two fields: a name and a kind. The rest waits. |
| f | `website_summary` | 887 | What the built-in server hands out, and at which address. The question this page exists to answer. Without it… |
| f | `page` | 1003 |  |
| **C** | `AdminServer` | 1735 | The admin page, on its own port. |
| · | &nbsp;&nbsp;`AdminServer.__init__` | 1738 |  |
| · | &nbsp;&nbsp;`AdminServer.serve_forever` | 1746 |  |
| · | &nbsp;&nbsp;`AdminServer.start` | 1749 |  |
| · | &nbsp;&nbsp;`AdminServer.stop` | 1754 |  |

## `src/weewx_evo/adminplots.py`

[Diagramme](Plots) · zuletzt geändert 2026-08-26 23:54

| | Name | Zeile | |
|---|---|---|---|
| f | `path_for` | 79 | Where plots.toml lives: beside the configuration. |
| f | `load` | 84 |  |
| f | `store` | 88 | Write them. Returns an error, or empty if it worked. |
| f | `add` | 100 | A new chart with one reading in it. Everything else on the next page. |
| f | `remove` | 125 |  |
| f | `save` | 132 | Everything about one chart, from its form. Errors keyed by field. |
| f | `plot_defs_vectors` | 217 |  |
| f | `bring_over` | 233 | Import from a WeeWX skin. Returns (message, error). From a file that was uploaded, from text that was pasted,… |
| f | `nav` | 306 | The charts, in the sidebar, grouped the way they are grouped. |
| f | `edit` | 360 | One chart's page. |
| f | `new` | 508 | The add-a-chart form. Three fields; the rest waits. |
| f | `importer` | 548 | The bring-it-over-from-WeeWX form. Three ways in, and the order matters. A file is the one that works from an… |

## `src/weewx_evo/aggregate.py`

[Aggregation](Aggregation) · zuletzt geändert 2026-08-26 23:43

| | Name | Zeile | |
|---|---|---|---|
| f | `to_float` | 26 | WeeWX's weeutil.to_float: the string 'none' is a null, not an error. |
| f | `start_of_archive_day` | 45 | The start of the day an archive record belongs to. A record stamped exactly at midnight closes the *previous*… |
| **C** | `FirstLast` | 58 | Minimal accumulator. Remembers the first and last value it saw. Suitable for strings, which is why it does no… |
| · | &nbsp;&nbsp;`FirstLast.__init__` | 67 |  |
| · | &nbsp;&nbsp;`FirstLast.set_stats` | 73 | A no-op: nothing this class holds survives a database round trip. |
| · | &nbsp;&nbsp;`FirstLast.stats_tuple` | 76 |  |
| · | &nbsp;&nbsp;`FirstLast.merge_hilo` | 79 |  |
| · | &nbsp;&nbsp;`FirstLast.merge_sum` | 89 | A no-op. There is no sum to merge. |
| · | &nbsp;&nbsp;`FirstLast.add_hilo` | 92 |  |
| · | &nbsp;&nbsp;`FirstLast.add_sum` | 102 | A no-op. There is no sum to add to. |
| · | &nbsp;&nbsp;`FirstLast.avg` | 106 |  |
| **C** | `Scalar` | 110 | Statistics for a scalar observation: min, max, and a weighted mean. `wsum` and `sumtime` are what make an ave… |
| · | &nbsp;&nbsp;`Scalar.__init__` | 120 |  |
| · | &nbsp;&nbsp;`Scalar.set_stats` | 124 |  |
| · | &nbsp;&nbsp;`Scalar.stats_tuple` | 130 |  |
| · | &nbsp;&nbsp;`Scalar.merge_hilo` | 134 |  |
| · | &nbsp;&nbsp;`Scalar.merge_sum` | 145 |  |
| · | &nbsp;&nbsp;`Scalar.add_hilo` | 151 |  |
| · | &nbsp;&nbsp;`Scalar.add_sum` | 163 |  |
| · | &nbsp;&nbsp;`Scalar.avg` | 173 |  |
| **C** | `Vector` | 177 | Statistics for wind: scalar stats plus the vector sums. `xsum`/`ysum` accumulate the east and north component… |
| · | &nbsp;&nbsp;`Vector.__init__` | 207 |  |
| · | &nbsp;&nbsp;`Vector.set_stats` | 212 |  |
| · | &nbsp;&nbsp;`Vector.stats_tuple` | 220 |  |
| · | &nbsp;&nbsp;`Vector.merge_hilo` | 226 |  |
| · | &nbsp;&nbsp;`Vector.merge_sum` | 241 |  |
| · | &nbsp;&nbsp;`Vector.add_hilo` | 252 |  |
| · | &nbsp;&nbsp;`Vector.add_sum` | 267 |  |
| · | &nbsp;&nbsp;`Vector.avg` | 285 |  |
| · | &nbsp;&nbsp;`Vector.rms` | 289 |  |
| · | &nbsp;&nbsp;`Vector.vec_avg` | 293 |  |
| · | &nbsp;&nbsp;`Vector.vec_dir` | 299 |  |
| **C** | `Accumulator` | 313 | Statistics for a set of observation types over one span of time. Feed it records with `add_record`, then read… |
| · | &nbsp;&nbsp;`Accumulator.__init__` | 323 |  |
| · | &nbsp;&nbsp;`Accumulator.includes` | 340 |  |
| · | &nbsp;&nbsp;`Accumulator.is_empty` | 344 |  |
| · | &nbsp;&nbsp;`Accumulator.add_record` | 347 | Fold one record into the statistics. Raises ValueError if the record falls outside the sp… |
| · | &nbsp;&nbsp;`Accumulator.merge_hilo` | 371 | Fold another accumulator's highs and lows into this one. |
| · | &nbsp;&nbsp;`Accumulator.record` | 383 | Extract an archive record. It is stamped at the end of the span. |
| · | &nbsp;&nbsp;`Accumulator.augment` | 387 | Fill in whatever the record does not already carry. Values already present win. That is h… |
| · | &nbsp;&nbsp;`Accumulator.set_stats` | 399 | Load statistics straight from storage, bypassing the arithmetic. With no tuple the type i… |

## `src/weewx_evo/archiver.py`

[Archiver](Archiver) · zuletzt geändert 2026-08-26 23:15

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Built` | 42 | One archive interval, worked out. |
| **C** | `Archiver` | 57 | Turns live packets into archive records and daily summaries. |
| · | &nbsp;&nbsp;`Archiver.__init__` | 60 |  |
| · | &nbsp;&nbsp;`Archiver.build` | 83 | Work out the record for the interval ending at `stop`. Returns None if no packet fell in… |
| · | &nbsp;&nbsp;`Archiver.store` | 146 | Write one built interval, then let its LOOP packets sharpen the day. The order matters. T… |
| · | &nbsp;&nbsp;`Archiver.process_due` | 174 | Build and store every interval that has closed. Returns how many. Safe to call at any mom… |
| · | &nbsp;&nbsp;`Archiver.catch_up` | 199 | Build every interval covered by the live table. Used at startup, after downtime, and by t… |
| · | &nbsp;&nbsp;`Archiver.rebuild` | 227 | Work out every interval in (start, stop] again, replacing what is there. The daily summar… |
| · | &nbsp;&nbsp;`Archiver.run` | 266 | Poll for closed intervals until told to stop. A plain sleep loop rather than a scheduler.… |

## `src/weewx_evo/chartdata.py`

**keine Seite** · zuletzt geändert 2026-08-26 23:45

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Line` | 57 | One reading, fetched and converted. What a renderer draws. |
| · | &nbsp;&nbsp;`Line.empty` | 89 |  |
| **C** | `Chart` | 94 | One plot, with its data. What both renderers are handed. |
| · | &nbsp;&nbsp;`Chart.empty` | 115 |  |
| f | `build` | 119 | One plot's data, or None if this station has none of its readings. Every line is fetched, converted, and trim… |
| f | `column_of` | 275 | The column behind a reading, for asking whether it exists. `windvec` is not a column; the speed it is made of… |
| f | `round_all` | 283 | Round a sequence, leaving the gaps in the data alone. |
| f | `components` | 291 | A vector series split into how far east and how far north. A chart drawing arrows scales and offsets the comp… |
| f | `drop_empty` | 313 | Leave out the points that carry nothing, keeping real gaps visible. A sensor reporting every ten minutes fill… |

## `src/weewx_evo/cli.py`

[CLI-Referenz](CLI-Reference) · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `env` | 73 |  |
| f | `add_common` | 77 |  |
| f | `add_listen_args` | 113 |  |
| f | `add_archive_args` | 136 |  |
| f | `settings_for` | 149 | The process's settings, resolved once. Once, not once per caller. With each component resolving for itself, a… |
| f | `read_config` | 192 | The whole configuration file, or an empty one. A file that is not there yet is not an error: a first start ha… |
| f | `configure_drivers` | 203 | Hand each driver its options, and somewhere to keep its own state. Until this runs the drivers are unconfigur… |
| f | `read_sources` | 258 | Which station wins for which field. Normally a [sources] section in the configuration file, beside everything… |
| f | `open_stores` | 287 |  |
| f | `make_archiver` | 295 |  |
| f | `cmd_listen` | 305 |  |
| f | `cmd_archive` | 349 |  |
| f | `cmd_upload_list` | 447 |  |
| f | `cmd_upload_check` | 478 | Ask each service whether it accepts the account. Worth more than the equivalent for an export: these services… |
| f | `cmd_upload_run` | 520 | Send now, whatever the trigger says. |
| f | `cmd_forecast_list` | 554 |  |
| f | `cmd_forecast_check` | 580 | Fetch once and say what came back. This is also how somebody finds a DWD station id or a MeteoAlarm region: a… |
| f | `cmd_forecast_run` | 619 | Fetch now and store, whatever the schedule says. |
| f | `cmd_forecast_show` | 642 | Print what is stored, which is what a page would draw. |
| f | `cmd_serve` | 696 | Listener and archiver in one process, for a small machine. They still speak only through the database. Splitt… |
| f | `cmd_catchup` | 934 |  |
| f | `cmd_rebuild` | 945 |  |
| f | `cmd_columns` | 956 | Readings that the archive has no column for. A reading only survives the archive interval if the table has a… |
| f | `cmd_driver_list` | 1031 |  |
| f | `cmd_driver_install` | 1053 |  |
| f | `cmd_driver_remove` | 1087 |  |
| f | `local_addresses` | 1096 | Addresses this machine can be reached on, as (address, what it is). Only what can be worked out without askin… |
| f | `cmd_url` | 1128 | Print the addresses of the live view and the upload endpoint. The token is a path segment, so an address with… |
| f | `driver_directory` | 1196 | Where third-party drivers live, resolved like everything else. The command line first, then the setting, then… |
| f | `all_schemas` | 1215 | Every configurable thing there is: the core, then each driver. Drivers are asked, not enumerated. One that ga… |
| f | `replace_group` | 1352 |  |
| f | `cmd_config_show` | 1358 | Print the configuration as it stands, commented. |
| f | `cmd_config_set` | 1371 | Set one value, checked against the schema that owns it. |
| f | `cmd_config_check` | 1402 | Check every value against its schema and say what is wrong. |
| f | `cmd_config_import` | 1420 | Read a weewx.conf and write what it says into our own file. |
| f | `cmd_admin` | 1451 | Serve the settings page. Its own port and its own token, deliberately. An upload endpoint can at worst put a… |
| f | `configured_exports` | 1526 | What the configuration file says about exports, by name. |
| f | `configured_uploads` | 1534 | What the configuration file says about uploads, by name. |
| f | `build_upload` | 1542 | Make one upload from its settings. Raises with a usable message. |
| f | `build_upload_schedule` | 1563 | What the uploads are, right now. They read the archive themselves rather than being handed a record: the comp… |
| f | `configured_forecasts` | 1610 | What the configuration file says about forecast sources, by name. |
| f | `forecast_db` | 1618 | Where the forecast is kept. Beside the archive, never in it. |
| f | `forecast_place` | 1627 | Where the station is, which is what a forecast is for. |
| f | `build_forecast_source` | 1636 | Make one forecast source. Raises with a usable message. |
| f | `build_forecast_schedule` | 1658 | What the forecast sources are, right now. |
| f | `apply_live` | 1668 | Apply a changed configuration to a running process. Everything that can be rebuilt in place, in one function.… |
| f | `build_schedule` | 1744 | What the exports are, right now. An export pointed at a feed has to be told where that feed writes, or it is… |
| f | `resolve_paths` | 1759 | Make an export's own paths absolute, against the configuration file. The same rule as plots.toml: a relative… |
| f | `build_export` | 1779 | Make one export from its settings. Raises with a usable message. |
| f | `cmd_export_list` | 1799 |  |
| f | `cmd_export_check` | 1831 | Try each destination without sending anything. |
| f | `cmd_export_run` | 1859 | Send. This is what a feed would call when it has produced something. |
| f | `cmd_web` | 1911 | Serve the feeds, and nothing else. Separate from `serve` for the same reason `listen` is: a machine that only… |
| f | `plots_path` | 1954 | Where plots.toml lives: beside the configuration unless told otherwise. |
| f | `load_plots` | 1968 |  |
| f | `configured_feeds` | 1981 | What the configuration says about feeds, by name. A name is one configured feed; `kind` says what it is. Two… |
| f | `feed_dirs` | 1999 | Where each feed writes, by name. One place, because two things need the answer and they must agree: the feed… |
| f | `build_feeds` | 2020 | The feeds this configuration asks for, in the order they run. Ordered by dependence: anything reading what an… |
| f | `served_directories` | 2114 | What the built-in server hands out, by name. The local exports, plus anything named directly. The same answer… |
| f | `cmd_plots_list` | 2136 | What charts exist. |
| f | `cmd_plots_show` | 2162 | One chart, in full. |
| f | `cmd_plots_import` | 2197 | Take the plots out of a WeeWX skin.conf or weewx.conf. Read, reported, and only written when asked. An import… |
| f | `cmd_plots_remove` | 2256 | Delete a chart. |
| f | `cmd_plots_run` | 2268 | Produce the JSON now, and say what came out. |
| f | `start_feeds` | 2316 | Start the feed runner, or say why there is nothing to run. One function for both loops. They had their own co… |
| f | `cmd_status` | 2343 |  |
| f | `main` | 2377 |  |

## `src/weewx_evo/config.py`

[Konfiguration](Configuration) · zuletzt geändert 2026-08-26 23:47

| | Name | Zeile | |
|---|---|---|---|
| f | `read` | 33 | The configuration file, or an empty one if it is not there yet. |
| f | `get` | 42 | A value by its dotted name: get(cfg, 'station.latitude'). |
| f | `put` | 52 | Set a value by its dotted name, making the sections on the way. |
| f | `values_for` | 65 | What this schema's settings currently are, defaults filled in. |
| f | `apply` | 77 | Write a schema's settings into the configuration. |
| f | `write` | 89 | Write the configuration out, commented, and keep the previous one. Written beside and moved into place, so an… |
| f | `render` | 114 | The configuration as a commented TOML file. |

## `src/weewx_evo/db/archive.py`

[Die Archiv-Datenbank](Database-Archive) · zuletzt geändert 2026-08-26 23:45

| | Name | Zeile | |
|---|---|---|---|
| **C** | `ArchiveStore` | 32 | A WeeWX archive database, open for reading and writing. |
| · | &nbsp;&nbsp;`ArchiveStore.__init__` | 35 |  |
| · | &nbsp;&nbsp;`ArchiveStore.close` | 57 |  |
| · | &nbsp;&nbsp;`ArchiveStore.reload_schema` | 66 | Re-read the schema. Needed after anything alters the tables. |
| · | &nbsp;&nbsp;`ArchiveStore.last_timestamp` | 116 |  |
| · | &nbsp;&nbsp;`ArchiveStore.count` | 119 |  |
| · | &nbsp;&nbsp;`ArchiveStore.exists` | 122 |  |
| · | &nbsp;&nbsp;`ArchiveStore.record` | 127 |  |
| · | &nbsp;&nbsp;`ArchiveStore.add_record` | 139 | Write one archive record and fold it into the daily summaries. Returns False if a record… |
| · | &nbsp;&nbsp;`ArchiveStore.homeless` | 198 | Fields dropped for want of a column, and how often, since startup. |
| · | &nbsp;&nbsp;`ArchiveStore.add_column` | 202 | Give a reading somewhere to live. Returns False if it already has one. WeeWX reads its sc… |
| · | &nbsp;&nbsp;`ArchiveStore.add_records` | 225 | Write many records, touching each day's summaries once. WeeWX reads and rewrites all of a… |
| · | &nbsp;&nbsp;`ArchiveStore.rebuild_day` | 342 | Recompute one day's summaries from the archive table. This is what makes a correction pos… |
| · | &nbsp;&nbsp;`ArchiveStore.days` | 377 | Every archive day that has records, in order. |
| · | &nbsp;&nbsp;`ArchiveStore.set_meta` | 390 | Write one metadata row. The table WeeWX keeps `lastUpdate` in. Drivers use this too: weew… |
| · | &nbsp;&nbsp;`ArchiveStore.get_meta` | 405 |  |

## `src/weewx_evo/db/daily.py`

[Tagesstatistiken](Daily-Summaries) · zuletzt geändert 2026-08-26 23:56

| | Name | Zeile | |
|---|---|---|---|
| **C** | `IntervalError` | 23 | A record whose `interval` cannot be turned into a weight. |
| f | `weight_of` | 27 | The weight one archive record carries in a daily summary. WeeWX uses this for daily-summary version 2.0 and u… |
| f | `day_accumulator` | 41 | An accumulator spanning one archive day, starting at `sod_ts`. |
| f | `build` | 47 | Fold archive records into one accumulator per day. Records must arrive in ascending time order -- the same or… |
| f | `read_day` | 83 | Read one day's stored statistics for one observation type. |
| f | `read_records` | 95 | Read archive records in time order, dropping the columns that are NULL. Dropping nulls matters: the accumulat… |

## `src/weewx_evo/db/live.py`

[Die Live-Datenbank](Database-Live) · zuletzt geändert 2026-08-26 12:25

| | Name | Zeile | |
|---|---|---|---|
| f | `interval_stop` | 67 | The end of the archive interval a timestamp belongs to. Intervals are half-open at the start, so a packet sta… |
| **C** | `Packet` | 77 | One reading as it arrived, before anything was done to it. |
| · | &nbsp;&nbsp;`Packet.digest` | 98 | A short hash of the payload, so a retransmission is not a new packet. |
| · | &nbsp;&nbsp;`Packet.record` | 103 | The packet as an observation record, ready for the accumulator. |
| **C** | `LiveStore` | 113 | The live packet database. |
| · | &nbsp;&nbsp;`LiveStore.__init__` | 116 |  |
| · | &nbsp;&nbsp;`LiveStore.conn` | 160 | This thread's connection, opened on first use. |
| · | &nbsp;&nbsp;`LiveStore.close` | 168 |  |
| · | &nbsp;&nbsp;`LiveStore.add` | 188 | Store one packet. Returns False if it was already there. Storing is idempotent on (source… |
| · | &nbsp;&nbsp;`LiveStore.add_all` | 210 | Store many packets in one transaction. Returns how many were new. |
| · | &nbsp;&nbsp;`LiveStore.mark_pending` | 216 | Note that the interval containing `ts` needs working out. |
| · | &nbsp;&nbsp;`LiveStore.clear_pending` | 225 |  |
| · | &nbsp;&nbsp;`LiveStore.due` | 230 | Intervals that have ended and can be worked out, oldest first. `grace` holds an interval… |
| · | &nbsp;&nbsp;`LiveStore.packets` | 246 | Every packet in (start, stop], in time order. `with_raw` reads the original upload too. O… |
| · | &nbsp;&nbsp;`LiveStore.forget_raw` | 269 | Drop the raw uploads of packets received before `before`. The packets themselves stay. On… |
| · | &nbsp;&nbsp;`LiveStore.raw_of` | 281 | One packet by its sequence number, with its raw upload if still held. |
| · | &nbsp;&nbsp;`LiveStore.span` | 292 |  |
| · | &nbsp;&nbsp;`LiveStore.count` | 295 |  |
| · | &nbsp;&nbsp;`LiveStore.get_meta` | 298 |  |
| · | &nbsp;&nbsp;`LiveStore.set_meta` | 304 |  |
| · | &nbsp;&nbsp;`LiveStore.prune` | 311 | Drop packets older than `before`, optionally writing them out first. With `archive_dir` s… |

## `src/weewx_evo/db/schema.py`

[Die Archiv-Datenbank](Database-Archive) · zuletzt geändert 2026-08-26 10:57

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Schema` | 32 | The shape of one WeeWX archive database. |
| · | &nbsp;&nbsp;`Schema.version` | 41 | The daily-summary version. 4.0 is current; anything below needs a patch. See weewx.manage… |
| · | &nbsp;&nbsp;`Schema.has_column` | 49 |  |
| f | `read` | 57 | Read the schema of an existing archive database. |

## `src/weewx_evo/derive.py`

[Abgeleitete Messwerte](Derived-Readings) · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `dewpoint_c` | 125 | Dew point in Celsius, by the Magnus formula WeeWX uses. |
| f | `windchill_c` | 142 | Wind chill, Celsius, from the Environment Canada formula. Only defined below 10 degrees and above 4.8 km/h. O… |
| f | `heatindex_f` | 156 | Heat index, Fahrenheit, Rothfusz with the two adjustments. Below 40 F there is no heat index and the temperat… |
| f | `humidex_c` | 182 | Humidex, Celsius. Below 21 degrees it is the temperature. |
| f | `apptemp_c` | 195 | Apparent temperature, the Australian BOM formula. |
| f | `altimeter_inhg` | 204 | Altimeter setting from station pressure, the aaASOS algorithm. |
| f | `cloudbase_ft` | 212 | Height of the cloud base, feet, from the spread. |
| f | `sun_position` | 228 | The sun's elevation in degrees, and Earth's distance in AU. pyephem when it is installed, and NOAA's algorith… |
| f | `max_solar_rad` | 310 | Clear-sky radiation, W/m2, Ryan-Stolzenbach (MIT, 1972). What a solar sensor would read with no cloud above i… |
| f | `windrun` | 344 | Distance the wind covered, in the same length unit as the speed. Speed times time. The unit follows the speed… |
| f | `delta` | 355 | How much a running total went up by. Three cases that are not errors and must not be treated as one: * No pre… |
| f | `sat_vapor_pressure_mbar` | 381 | The most water vapour the air could hold, in millibars. Magnus, with the coefficients WeeWX uses in `dewpoint… |
| f | `vapor_pressure_mbar` | 392 | What the moisture actually in the air is worth, in millibars. |
| f | `absolute_humidity` | 397 | Grams of water per cubic metre. The number a greenhouse, a cellar or a museum cares about: relative humidity… |
| f | `mixing_ratio` | 410 | Grams of water per kilogram of dry air. Conserved when air rises or is heated, which is why meteorology uses… |
| f | `sunshine_seconds` | 425 | How much of this interval was sunshine. All or nothing per interval, which is what every implementation of th… |
| **C** | `Station` | 455 | What the formulas need to know about where the station is. |
| · | &nbsp;&nbsp;`Station.altitude_ft` | 463 |  |
| **C** | `Deriver` | 470 | Fills in the readings that follow from other readings. Holds one piece of state: the last value of each runni… |
| · | &nbsp;&nbsp;`Deriver.wanted` | 489 | Whether to work this one out for this record. |
| · | &nbsp;&nbsp;`Deriver.apply` | 499 | Add what is missing. The record is modified and returned. Order matters: dew point before… |
| · | &nbsp;&nbsp;`Deriver.forget` | 662 | Drop the running totals. The next packet takes no delta. |
| f | `from_settings` | 708 | Build one from the resolved configuration. |

## `src/weewx_evo/exports/__init__.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 18:55

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Sent` | 49 | What one run of an export did. |
| · | &nbsp;&nbsp;`Sent.ok` | 63 |  |
| · | &nbsp;&nbsp;`Sent.summary` | 66 |  |
| **C** | `ExportError` | 80 | Something that stopped an export before it sent anything. |
| **C** | `Export` | 85 | Files out. |
| · | &nbsp;&nbsp;`Export.send` | 88 | Send `source` to wherever this export sends things. `files` is what changed, when the cal… |
| **C** | `BaseExport` | 101 | Defaults for an export. Only `send` has to be written. |
| · | &nbsp;&nbsp;`BaseExport.send` | 107 |  |
| · | &nbsp;&nbsp;`BaseExport.check` | 110 | Try the destination and say what happened, without sending. The admin page offers this as… |
| · | &nbsp;&nbsp;`BaseExport.status` | 119 |  |
| · | &nbsp;&nbsp;`BaseExport.close` | 122 | Release anything held. Optional. |
| **C** | `Registry` | 126 | The exports this installation has. The same shape as the driver registry, and for the same reason: an export… |
| · | &nbsp;&nbsp;`Registry.__init__` | 134 |  |
| · | &nbsp;&nbsp;`Registry.register` | 139 |  |
| · | &nbsp;&nbsp;`Registry.register_factory` | 144 |  |
| · | &nbsp;&nbsp;`Registry.configure` | 147 |  |
| · | &nbsp;&nbsp;`Registry.factory_for` | 159 | The class behind a kind, loading the registry first. A method rather than reaching into `… |
| · | &nbsp;&nbsp;`Registry.get` | 169 |  |
| · | &nbsp;&nbsp;`Registry.known` | 173 |  |
| · | &nbsp;&nbsp;`Registry.names` | 177 |  |
| · | &nbsp;&nbsp;`Registry.kinds` | 181 | The kinds available, as opposed to the ones configured. |
| · | &nbsp;&nbsp;`Registry.load` | 186 | Pull in what is installed. A broken one is reported, never fatal. |
| f | `get` | 219 |  |
| f | `names` | 223 |  |
| f | `kinds` | 227 |  |
| f | `source_for` | 243 | Where an export's files are, from a feed name or a plain directory. A feed is asked where it wrote; a directo… |
| f | `walk` | 264 | Every file to consider, as paths relative to `source`. Directories that should never be uploaded are skipped… |

## `src/weewx_evo/exports/ftp.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 19:39

| | Name | Zeile | |
|---|---|---|---|
| **C** | `FtpExport` | 46 | Sends a directory to an FTP server. |
| · | &nbsp;&nbsp;`FtpExport.__init__` | 57 |  |
| · | &nbsp;&nbsp;`FtpExport.send` | 87 |  |
| · | &nbsp;&nbsp;`FtpExport.check` | 134 | Connect, look at the target directory, and say what happened. |
| · | &nbsp;&nbsp;`FtpExport.status` | 157 |  |
| · | &nbsp;&nbsp;`FtpExport.options` | 267 |  |

## `src/weewx_evo/exports/local.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 23:53

| | Name | Zeile | |
|---|---|---|---|
| **C** | `LocalExport` | 44 | Copies what a feed produced into a directory on this machine. |
| · | &nbsp;&nbsp;`LocalExport.__init__` | 56 |  |
| · | &nbsp;&nbsp;`LocalExport.send` | 94 |  |
| · | &nbsp;&nbsp;`LocalExport.check` | 217 | Whether this can be written to, and what is there now. |
| · | &nbsp;&nbsp;`LocalExport.status` | 241 |  |
| · | &nbsp;&nbsp;`LocalExport.options` | 253 |  |

## `src/weewx_evo/exports/rsync.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 16:14

| | Name | Zeile | |
|---|---|---|---|
| **C** | `RsyncExport` | 44 | Sends a directory to a server with rsync over SSH. |
| · | &nbsp;&nbsp;`RsyncExport.__init__` | 56 |  |
| · | &nbsp;&nbsp;`RsyncExport.send` | 84 |  |
| · | &nbsp;&nbsp;`RsyncExport.check` | 122 | Do a dry run and report what would happen. |
| · | &nbsp;&nbsp;`RsyncExport.status` | 154 |  |
| · | &nbsp;&nbsp;`RsyncExport.options` | 224 |  |

## `src/weewx_evo/exports/runner.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 23:43

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Scheduled` | 46 | One export, and when it is next due. |
| · | &nbsp;&nbsp;`Scheduled.__init__` | 64 |  |
| · | &nbsp;&nbsp;`Scheduled.trigger` | 90 |  |
| · | &nbsp;&nbsp;`Scheduled.every` | 94 |  |
| · | &nbsp;&nbsp;`Scheduled.due` | 97 | `fired` is what just happened: "record", a feed name, or "". |
| · | &nbsp;&nbsp;`Scheduled.run` | 107 | Send, and remember what happened. Never raises. |
| **C** | `Runner` | 139 | Keeps the exports going, one thread each. |
| · | &nbsp;&nbsp;`Runner.__init__` | 142 |  |
| · | &nbsp;&nbsp;`Runner.start` | 150 |  |
| · | &nbsp;&nbsp;`Runner.record_written` | 167 | A new archive record landed. Called from the archiver's thread and returns at once: it se… |
| · | &nbsp;&nbsp;`Runner.feed_produced` | 178 | A feed has finished writing. Wake whatever sends it. This is the trigger to prefer where… |
| · | &nbsp;&nbsp;`Runner.stop` | 192 |  |
| · | &nbsp;&nbsp;`Runner.status` | 237 |  |
| f | `build` | 251 | Turn configuration into things the runner can run. Anything that cannot be built is reported and left out. A… |

## `src/weewx_evo/exports/tracker.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 13:31

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Fingerprint` | 41 | Enough to tell whether a file is the one already sent. |
| · | &nbsp;&nbsp;`Fingerprint.as_list` | 48 |  |
| · | &nbsp;&nbsp;`Fingerprint.of` | 52 |  |
| · | &nbsp;&nbsp;`Fingerprint.same_as` | 63 | Whether these are the same file. With a digest, that decides on its own: a rewritten temp… |
| **C** | `Tracker` | 76 | What one export has sent where. |
| · | &nbsp;&nbsp;`Tracker.__init__` | 79 |  |
| · | &nbsp;&nbsp;`Tracker.save` | 97 | Write the record out. Losing it costs one full upload. |
| · | &nbsp;&nbsp;`Tracker.changed` | 112 | Which of these need sending, and how many did not. A file that cannot be read is treated… |
| · | &nbsp;&nbsp;`Tracker.record` | 135 | Note that this file has been sent, as it is now. |
| · | &nbsp;&nbsp;`Tracker.forget` | 144 |  |
| · | &nbsp;&nbsp;`Tracker.gone` | 148 | What we have sent before and is no longer here. An export that removes files at the far e… |
| · | &nbsp;&nbsp;`Tracker.reset` | 159 | Forget everything, so the next run sends the lot. |

## `src/weewx_evo/feedrunner.py`

[Feeds](Feeds) · zuletzt geändert 2026-08-26 23:43

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Runner` | 37 | Produces every feed, in order, whenever a record lands. |
| · | &nbsp;&nbsp;`Runner.__init__` | 40 |  |
| · | &nbsp;&nbsp;`Runner.record_written` | 63 | Called by the archiver. Sets a flag and returns. |
| · | &nbsp;&nbsp;`Runner.start` | 67 |  |
| · | &nbsp;&nbsp;`Runner.stop` | 72 |  |
| · | &nbsp;&nbsp;`Runner.run_once` | 92 | Every feed, in order. Returns what happened, for a status page. |
| · | &nbsp;&nbsp;`Runner.status` | 149 |  |

## `src/weewx_evo/feeds/__init__.py`

[Feeds](Feeds) · zuletzt geändert 2026-08-27 10:35

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Produced` | 72 | What one run of a feed made. The list of files matters to the exports: an export that knows which files chang… |
| · | &nbsp;&nbsp;`Produced.count` | 87 |  |
| f | `kinds` | 91 | The kinds of feed that can be configured. A kind is what a feed *is* -- JSON, a diagnostic page, a Cheetah sk… |
| f | `names` | 104 | Kept for anything still asking. See `kinds`. |
| f | `describe` | 109 | One line about a kind of feed, for a form that offers it. |
| f | `factory_for` | 115 | The class behind a kind, loading the registry first. |
| f | `load` | 146 | Pull in the feeds. A broken one is reported, never fatal. Same arrangement as the drivers: one feed that will… |
| f | `register` | 178 |  |
| f | `get` | 184 |  |
| **C** | `Feed` | 190 | Readings out, as files. |
| · | &nbsp;&nbsp;`Feed.produce` | 196 | Write this feed's files into `into` and say which they are. `archive` is a read-only view… |

## `src/weewx_evo/feeds/cheetah/__init__.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `CheetahFeed` | 78 | Renders one skin. |
| · | &nbsp;&nbsp;`CheetahFeed.__init__` | 83 |  |
| · | &nbsp;&nbsp;`CheetahFeed.produce` | 137 |  |
| · | &nbsp;&nbsp;`CheetahFeed.skin_options` | 786 | What the chosen skin lets an operator set, for the feed's page. A skin of ours ships an `… |
| · | &nbsp;&nbsp;`CheetahFeed.options` | 800 |  |
| f | `from_settings` | 1127 | Build the feed, and the tag layer it renders through. The tags are built here rather than handed in because t… |
| f | `skin_options` | 1207 | What the named skin lets an operator set, or nothing. A skin of ours ships an `options.py` next to its templa… |

## `src/weewx_evo/feeds/diagnostic/__init__.py`

[Feeds](Feeds) · zuletzt geändert 2026-08-26 23:53

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Diagnostic` | 51 | Renders every series file it finds, with its faults listed. |
| · | &nbsp;&nbsp;`Diagnostic.__init__` | 56 |  |
| · | &nbsp;&nbsp;`Diagnostic.produce` | 66 |  |
| · | &nbsp;&nbsp;`Diagnostic.read` | 90 | Every JSON file in the source directory, examined. |
| · | &nbsp;&nbsp;`Diagnostic.render` | 203 |  |
| · | &nbsp;&nbsp;`Diagnostic.options` | 302 | The settings one of these offers. Bare names; the page prefixes. |
| f | `from_settings` | 356 | Build the page from the configuration. `prefix` names the configured feed. Two of them can draw two different… |

## `src/weewx_evo/feeds/imagegenerator/__init__.py`

**keine Seite** · zuletzt geändert 2026-08-26 23:47

| | Name | Zeile | |
|---|---|---|---|
| **C** | `ImageGenerator` | 60 | Turns plot definitions into PNG files. |
| · | &nbsp;&nbsp;`ImageGenerator.__init__` | 67 |  |
| · | &nbsp;&nbsp;`ImageGenerator.produce` | 115 |  |
| · | &nbsp;&nbsp;`ImageGenerator.build` | 167 | One chart as an image, or None if there is nothing in it. |
| · | &nbsp;&nbsp;`ImageGenerator.draw` | 180 |  |
| · | &nbsp;&nbsp;`ImageGenerator.options` | 571 |  |
| f | `from_settings` | 636 | Build the generator from the configuration. `prefix` names the configured feed, so two of them can be set up… |

## `src/weewx_evo/feeds/imagegenerator/canvas.py`

**keine Seite** · zuletzt geändert 2026-08-26 23:47

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Box` | 44 | The rectangle the data is drawn in, in final pixels. |
| · | &nbsp;&nbsp;`Box.width` | 53 |  |
| · | &nbsp;&nbsp;`Box.height` | 57 |  |
| **C** | `Canvas` | 61 | One chart being drawn. Coordinates are given in final pixels throughout. Geometry is scaled up on the way to… |
| · | &nbsp;&nbsp;`Canvas.__init__` | 68 |  |
| · | &nbsp;&nbsp;`Canvas.rectangle` | 89 |  |
| · | &nbsp;&nbsp;`Canvas.line` | 97 |  |
| · | &nbsp;&nbsp;`Canvas.polygon` | 106 |  |
| · | &nbsp;&nbsp;`Canvas.dot` | 113 |  |
| · | &nbsp;&nbsp;`Canvas.circle` | 120 | A ring, not a disc. |
| · | &nbsp;&nbsp;`Canvas.fade_under` | 129 | The area under a line, fading out towards the bottom. A flat wash of colour under every l… |
| · | &nbsp;&nbsp;`Canvas.fade_across` | 175 | Wash a colour across a band, fading it out as it goes. For dawn and dusk. Night drawn as… |
| · | &nbsp;&nbsp;`Canvas.text` | 208 |  |
| · | &nbsp;&nbsp;`Canvas.measure` | 216 | How wide and tall a piece of text will be, in final pixels. |
| · | &nbsp;&nbsp;`Canvas.finish` | 240 | Scale the geometry down and put the text on top. |
| f | `nice_ticks` | 272 | Gridline positions a reader would have chosen. Round numbers, and a step out of 1, 2, 2.5 or 5 times a power… |
| f | `time_ticks` | 300 | Where to label the time axis, and what to write there. Local time, on round boundaries. A day chart gets whol… |
| f | `label_for` | 402 | A tick's number, with only the decimals the step needs. A step of 5 wants "15", not "15.0". A step of 0.2 wan… |

## `src/weewx_evo/feeds/imagegenerator/theme.py`

**keine Seite** · zuletzt geändert 2026-08-26 23:56

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Theme` | 62 | Every colour and measurement one chart is drawn with. Sizes are in logical pixels. The renderer multiplies th… |
| · | &nbsp;&nbsp;`Theme.color` | 124 |  |
| · | &nbsp;&nbsp;`Theme.scaled` | 127 | The same theme in a bigger coordinate system. Everything with a size grows; nothing with… |
| f | `resolve` | 154 | Find a real typeface, once, and remember where it was. Looked up here rather than at every draw: a hundred ch… |
| f | `rgba` | 197 | `#rrggbb` and an opacity as the four numbers Pillow wants. A short `#rgb` is accepted because skins are full… |

## `src/weewx_evo/feeds/jsongenerator/__init__.py`

[Feeds](Feeds) · zuletzt geändert 2026-08-26 23:54

| | Name | Zeile | |
|---|---|---|---|
| **C** | `JSONGenerator` | 79 | Turns plot definitions into JSON files. |
| · | &nbsp;&nbsp;`JSONGenerator.__init__` | 86 |  |
| · | &nbsp;&nbsp;`JSONGenerator.produce` | 125 | Write every plot, and the manifest. Returns what was made. |
| · | &nbsp;&nbsp;`JSONGenerator.build` | 238 | One plot's payload, or None if there is nothing in it. The numbers come from `chartdata`,… |
| · | &nbsp;&nbsp;`JSONGenerator.options` | 258 | The settings one of these offers. Bare names, and the page supplies the prefix -- the sam… |
| f | `from_settings` | 459 | Build the generator from the configuration. `prefix` names the configured feed, so two of them can be set up… |

## `src/weewx_evo/feeds/realtime/__init__.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:35

| | Name | Zeile | |
|---|---|---|---|
| **C** | `RealtimeFeed` | 66 | Writes `realtime.txt`, and `wxnow.txt` beside it. |
| · | &nbsp;&nbsp;`RealtimeFeed.__init__` | 77 |  |
| · | &nbsp;&nbsp;`RealtimeFeed.line` | 110 | One `realtime.txt` line. The first two fields are the date and the time, in Cumulus's own… |
| · | &nbsp;&nbsp;`RealtimeFeed.wxnow_line` | 146 | `wxnow.txt`, which every APRS daemon reads. Fixed width, US customary throughout, and --… |
| · | &nbsp;&nbsp;`RealtimeFeed.produce` | 180 |  |
| · | &nbsp;&nbsp;`RealtimeFeed.options` | 220 |  |

## `src/weewx_evo/forecast/__init__.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Place` | 62 | Where the forecast is for. |
| **C** | `Moment` | 76 | The forecast for one hour. Field names are the archive's, deliberately: `outTemp` here means the same thing i… |
| · | &nbsp;&nbsp;`Moment.values` | 112 | The readings that are actually present, by name. |
| **C** | `Day` | 119 | The forecast for one day, as a source summarised it. Not derived from the hours. A source's own daily summary… |
| · | &nbsp;&nbsp;`Day.values` | 145 |  |
| **C** | `Warning` | 151 | One official warning. Modelled on CAP, because every European and American warning service publishes CAP and… |
| · | &nbsp;&nbsp;`Warning.rank` | 182 | How serious, as a number, so warnings can be sorted. |
| **C** | `Reading` | 189 | Everything one source returned in one fetch. |
| · | &nbsp;&nbsp;`Reading.empty` | 204 |  |
| · | &nbsp;&nbsp;`Reading.summary` | 207 |  |
| **C** | `ForecastError` | 222 | Something that stopped a source from answering. |
| · | &nbsp;&nbsp;`ForecastError.__init__` | 225 |  |
| **C** | `Source` | 231 | Somewhere a forecast comes from. |
| · | &nbsp;&nbsp;`Source.fetch` | 234 |  |
| **C** | `BaseSource` | 238 | Defaults for a source. Only `fetch` has to be written. |
| · | &nbsp;&nbsp;`BaseSource.fetch` | 251 |  |
| · | &nbsp;&nbsp;`BaseSource.check` | 254 | Fetch once and say what came back, for the settings page. |
| · | &nbsp;&nbsp;`BaseSource.close` | 264 | Release anything held. Optional. |
| f | `parse_xml` | 275 | Parse XML from a weather service, with a size limit in front. `xml.etree` rather than `defusedxml`, which is… |
| **C** | `Registry` | 317 | The forecast sources this installation has. |
| · | &nbsp;&nbsp;`Registry.__init__` | 320 |  |
| · | &nbsp;&nbsp;`Registry.register_factory` | 324 |  |
| · | &nbsp;&nbsp;`Registry.factory_for` | 327 |  |
| · | &nbsp;&nbsp;`Registry.kinds` | 331 |  |
| · | &nbsp;&nbsp;`Registry.describe` | 335 |  |
| · | &nbsp;&nbsp;`Registry.load` | 339 |  |
| f | `kinds` | 365 |  |
| f | `describe` | 369 |  |

## `src/weewx_evo/forecast/codes.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `text` | 66 | What to call this code, in the language the station is set to. |
| f | `symbol` | 78 | A name for the picture, not the picture itself. |
| f | `is_wet` | 100 | Whether this code means something is falling out of the sky. |
| f | `is_severe` | 105 | Thunder, hail, freezing, or heavy anything. |

## `src/weewx_evo/forecast/dwd.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Mosmix` | 83 | A point forecast for one DWD station. |
| · | &nbsp;&nbsp;`Mosmix.__init__` | 93 |  |
| · | &nbsp;&nbsp;`Mosmix.fetch` | 122 |  |
| · | &nbsp;&nbsp;`Mosmix.read` | 130 | Turn one MOSMIX document into hours. Separate so a test can run it. |
| · | &nbsp;&nbsp;`Mosmix.nearest` | 184 | The station ids nearest to a point, from the DWD's own listing. The directory index is th… |
| · | &nbsp;&nbsp;`Mosmix.check` | 232 |  |
| · | &nbsp;&nbsp;`Mosmix.options` | 255 |  |
| **C** | `DwdWarnings` | 279 | Warnings straight from the DWD, in their own words. |
| · | &nbsp;&nbsp;`DwdWarnings.__init__` | 292 |  |
| · | &nbsp;&nbsp;`DwdWarnings.fetch` | 317 |  |
| · | &nbsp;&nbsp;`DwdWarnings.read` | 327 | One CAP document. It carries several areas per alert. |
| · | &nbsp;&nbsp;`DwdWarnings.check` | 375 |  |
| · | &nbsp;&nbsp;`DwdWarnings.options` | 396 |  |

## `src/weewx_evo/forecast/meteoalarm.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `parse_time` | 68 | A CAP timestamp as unix time. Zero when absent or unparseable. CAP writes `2026-08-27T06:00:00+00:00`, and so… |
| **C** | `MeteoAlarm` | 91 | Warnings from meteoalarm.org. |
| · | &nbsp;&nbsp;`MeteoAlarm.__init__` | 102 |  |
| · | &nbsp;&nbsp;`MeteoAlarm.fetch` | 133 |  |
| · | &nbsp;&nbsp;`MeteoAlarm.entries` | 144 | Every warning in the feed, before any filtering. Public because `check` uses it to show w… |
| · | &nbsp;&nbsp;`MeteoAlarm.check` | 191 | Fetch, and list the regions -- which is how somebody finds theirs. |
| · | &nbsp;&nbsp;`MeteoAlarm.options` | 217 |  |

## `src/weewx_evo/forecast/nws.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `code_for` | 87 | A WMO code for an NWS phrase, or None if it says nothing about weather. Longest match wins, so "Chance Rain S… |
| f | `speed` | 102 | `"10 mph"` or `"5 to 10 mph"` as metres per second. A range becomes its upper end, which is what a forecast o… |
| **C** | `NationalWeatherService` | 118 | Forecasts and alerts from api.weather.gov. |
| · | &nbsp;&nbsp;`NationalWeatherService.__init__` | 127 |  |
| · | &nbsp;&nbsp;`NationalWeatherService.grid` | 165 | The hourly-forecast path for this point, looked up once. Remembered because it does not c… |
| · | &nbsp;&nbsp;`NationalWeatherService.fetch` | 184 |  |
| · | &nbsp;&nbsp;`NationalWeatherService.read_alerts` | 194 |  |
| · | &nbsp;&nbsp;`NationalWeatherService.read_forecast` | 226 |  |
| · | &nbsp;&nbsp;`NationalWeatherService.check` | 254 |  |
| · | &nbsp;&nbsp;`NationalWeatherService.options` | 271 |  |

## `src/weewx_evo/forecast/openmeteo.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `OpenMeteo` | 94 | A forecast from open-meteo.com. |
| · | &nbsp;&nbsp;`OpenMeteo.__init__` | 105 |  |
| · | &nbsp;&nbsp;`OpenMeteo.path` | 117 |  |
| · | &nbsp;&nbsp;`OpenMeteo.fetch` | 144 |  |
| · | &nbsp;&nbsp;`OpenMeteo.read` | 165 | Turn one response into hours and days. Separate from `fetch` so a test can hand it a save… |
| · | &nbsp;&nbsp;`OpenMeteo.check` | 228 |  |
| · | &nbsp;&nbsp;`OpenMeteo.options` | 245 |  |

## `src/weewx_evo/forecast/runner.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Scheduled` | 47 | One source, and when it is next due. |
| · | &nbsp;&nbsp;`Scheduled.__init__` | 64 |  |
| · | &nbsp;&nbsp;`Scheduled.every` | 82 |  |
| · | &nbsp;&nbsp;`Scheduled.due` | 85 |  |
| · | &nbsp;&nbsp;`Scheduled.run` | 88 | Fetch and store. Never raises. |
| **C** | `Runner` | 120 | Keeps the forecast sources going, one thread each. |
| · | &nbsp;&nbsp;`Runner.__init__` | 123 |  |
| · | &nbsp;&nbsp;`Runner.start` | 130 |  |
| · | &nbsp;&nbsp;`Runner.stop` | 139 |  |
| · | &nbsp;&nbsp;`Runner.replace` | 151 | Swap in a new set, after the configuration changed. |
| · | &nbsp;&nbsp;`Runner.status` | 188 |  |
| f | `build` | 201 | Turn configuration into things the runner can run. Anything that cannot be built is reported and left out. A… |

## `src/weewx_evo/forecast/store.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `ForecastStore` | 53 | The forecast database, open for reading and writing. |
| · | &nbsp;&nbsp;`ForecastStore.__init__` | 56 |  |
| · | &nbsp;&nbsp;`ForecastStore.conn` | 66 | This thread's connection, opened on first use. The poller writes on its own thread and a… |
| · | &nbsp;&nbsp;`ForecastStore.close` | 85 |  |
| · | &nbsp;&nbsp;`ForecastStore.store` | 125 | Replace everything this source had with what it just returned. In one transaction: a page… |
| · | &nbsp;&nbsp;`ForecastStore.forget` | 190 | Everything from one source, gone. For an unconfigured source. |
| · | &nbsp;&nbsp;`ForecastStore.prune` | 197 | Drop hours and warnings that are in the past. A forecast is only ever about the future, s… |
| · | &nbsp;&nbsp;`ForecastStore.sources` | 216 |  |
| · | &nbsp;&nbsp;`ForecastStore.run` | 220 | When this source last answered, and with how much. |
| · | &nbsp;&nbsp;`ForecastStore.hours` | 230 | The hourly forecast, in time order. |
| · | &nbsp;&nbsp;`ForecastStore.days` | 238 |  |
| · | &nbsp;&nbsp;`ForecastStore.warnings` | 245 | Warnings, most severe first. `active_at` keeps only what covers that instant. A warning t… |

## `src/weewx_evo/forecast/tags.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Entry` | 46 | One hour or one day, as a template sees it. Attribute lookup does the binding, the same way the rest of the t… |
| · | &nbsp;&nbsp;`Entry.__init__` | 57 |  |
| · | &nbsp;&nbsp;`Entry.dateTime` | 65 |  |
| · | &nbsp;&nbsp;`Entry.code` | 70 | The raw WMO code, for a template that wants to switch on it. |
| · | &nbsp;&nbsp;`Entry.text` | 75 | What the weather is doing, in the station's language. |
| · | &nbsp;&nbsp;`Entry.symbol` | 80 | A name for the picture, not the picture. Which file that is belongs to whoever draws the… |
| · | &nbsp;&nbsp;`Entry.wet` | 90 |  |
| · | &nbsp;&nbsp;`Entry.severe` | 94 |  |
| **C** | `WarningTag` | 153 | One official warning, as a template sees it. |
| · | &nbsp;&nbsp;`WarningTag.__init__` | 158 |  |
| · | &nbsp;&nbsp;`WarningTag.starts` | 163 |  |
| · | &nbsp;&nbsp;`WarningTag.ends` | 168 |  |
| · | &nbsp;&nbsp;`WarningTag.active` | 173 | Whether it covers this moment. A warning that has not started is real and worth showing -… |
| **C** | `SourceTag` | 197 | One forecast source. `$forecast.ahead`, or `$forecast` for all of them. |
| · | &nbsp;&nbsp;`SourceTag.__init__` | 202 |  |
| · | &nbsp;&nbsp;`SourceTag.hours` | 215 | From this hour forward. The past is not a forecast. |
| · | &nbsp;&nbsp;`SourceTag.days` | 222 | From today forward, today first. |
| · | &nbsp;&nbsp;`SourceTag.now` | 233 | The hour we are in. The hour whose stamp is at or just before now -- not the nearest, whi… |
| · | &nbsp;&nbsp;`SourceTag.today` | 252 |  |
| · | &nbsp;&nbsp;`SourceTag.tomorrow` | 257 |  |
| · | &nbsp;&nbsp;`SourceTag.warnings` | 271 | Every warning stored, worst first. |
| · | &nbsp;&nbsp;`SourceTag.warning` | 281 | The worst one, for a page with room for a single banner. |
| · | &nbsp;&nbsp;`SourceTag.active_warnings` | 287 | Only what covers this moment. |
| · | &nbsp;&nbsp;`SourceTag.updated` | 298 | When the source last answered. Which is not when the model ran -- see `issued`. A page th… |
| · | &nbsp;&nbsp;`SourceTag.issued` | 312 | When the model behind this forecast actually ran. |
| · | &nbsp;&nbsp;`SourceTag.exists` | 321 |  |
| · | &nbsp;&nbsp;`SourceTag.sources` | 325 |  |
| f | `install` | 379 | Give a `Tags` object its `$forecast`. Called by whatever built the tags and knows where the forecast database… |

## `src/weewx_evo/ingest/drivers.py`

[Treiber](Drivers) · zuletzt geändert 2026-08-26 23:43

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Driver` | 57 | Bytes in, finished packets out. |
| · | &nbsp;&nbsp;`Driver.packets` | 60 | Turn one upload into packets. `meta` carries `received` (arrival time, unix) and `source`… |
| **C** | `BaseDriver` | 74 | A driver that only needs to parse. Defaults for everything else. |
| · | &nbsp;&nbsp;`BaseDriver.packets` | 80 |  |
| · | &nbsp;&nbsp;`BaseDriver.status` | 83 | Whatever the driver wants reported at /status. Optional. |
| · | &nbsp;&nbsp;`BaseDriver.close` | 87 | Release anything held. Optional. |
| f | `response_of` | 91 | What to answer an upload to this driver with. |
| f | `status_of` | 96 |  |
| **C** | `Registry` | 154 | The drivers this installation has. Instances, not classes: a driver holds configuration and state -- which co… |
| · | &nbsp;&nbsp;`Registry.__init__` | 162 |  |
| · | &nbsp;&nbsp;`Registry.register` | 168 |  |
| · | &nbsp;&nbsp;`Registry.register_factory` | 175 | Register something to be built when its configuration is known. `aliases` are other names… |
| · | &nbsp;&nbsp;`Registry.configure` | 189 | Build a registered factory with its options, and install the result. |
| · | &nbsp;&nbsp;`Registry.get` | 205 |  |
| · | &nbsp;&nbsp;`Registry.known` | 209 |  |
| · | &nbsp;&nbsp;`Registry.names` | 213 |  |
| · | &nbsp;&nbsp;`Registry.canonical_names` | 217 | Names that are not an alias of another driver. Configuring an alias would build a second… |
| · | &nbsp;&nbsp;`Registry.aliases_of` | 227 |  |
| · | &nbsp;&nbsp;`Registry.close` | 230 |  |
| · | &nbsp;&nbsp;`Registry.load` | 239 | Pull in what is installed. A broken plugin is reported, never fatal. One package failing… |
| f | `register` | 273 |  |
| f | `get` | 277 |  |
| f | `known` | 281 |  |
| f | `names` | 285 |  |

## `src/weewx_evo/ingest/envelope.py`

[Treiber](Drivers) · zuletzt geändert 2026-08-26 11:39

| | Name | Zeile | |
|---|---|---|---|
| **C** | `EnvelopeDriver` | 29 | Reads the envelope. The only driver that ships in the core. |
| · | &nbsp;&nbsp;`EnvelopeDriver.packets` | 32 |  |

## `src/weewx_evo/ingest/listener.py`

[Listener](Ingest-Listener) · zuletzt geändert 2026-08-26 23:51

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Ingest` | 44 | What the listener does with an upload once it has one. Kept separate from the transports so the same object s… |
| · | &nbsp;&nbsp;`Ingest.__init__` | 51 |  |
| · | &nbsp;&nbsp;`Ingest.authorised` | 75 | Whether a request path carries the token. The token is a path segment rather than a heade… |
| · | &nbsp;&nbsp;`Ingest.driver_for` | 87 | Pick a driver from the path, e.g. /<token>/json/ or /<token>/ecowitt/. |
| · | &nbsp;&nbsp;`Ingest.submit` | 94 | Take one upload. Returns (packets stored, reason, what to answer with). The response come… |
| · | &nbsp;&nbsp;`Ingest.status` | 181 |  |
| **C** | `HttpListener` | 341 | The HTTP half. Threaded, because a slow console must not block the others. |
| · | &nbsp;&nbsp;`HttpListener.__init__` | 344 |  |
| · | &nbsp;&nbsp;`HttpListener.serve_forever` | 350 |  |
| · | &nbsp;&nbsp;`HttpListener.start` | 354 |  |
| · | &nbsp;&nbsp;`HttpListener.stop` | 359 |  |
| **C** | `UdpListener` | 382 | The UDP half, for hardware that broadcasts rather than posts. |
| · | &nbsp;&nbsp;`UdpListener.__init__` | 385 |  |
| · | &nbsp;&nbsp;`UdpListener.serve_forever` | 393 |  |
| · | &nbsp;&nbsp;`UdpListener.start` | 397 |  |
| · | &nbsp;&nbsp;`UdpListener.stop` | 402 |  |
| f | `push` | 407 | Send packets to a listener. This is how a pull driver delivers. Going over the loopback rather than writing t… |
| f | `resolve_bind` | 433 | Turn a bind address into something to print. Cosmetic only. |

## `src/weewx_evo/ingest/parsers.py`

[Treiber](Drivers) · zuletzt geändert 2026-08-26 11:23

| | Name | Zeile | |
|---|---|---|---|
| f | `register` | 50 | Make a parser available under `name`. |
| f | `parse_json` | 57 | weewx-evo's own envelope. This is the contract every driver can rely on. One object or a list of them: {"date… |
| f | `get` | 121 |  |
| f | `names` | 126 |  |
| f | `known` | 131 |  |

## `src/weewx_evo/ingest/plugins/__init__.py`

[Treiber](Drivers) · zuletzt geändert 2026-08-26 11:50

| | Name | Zeile | |
|---|---|---|---|
| f | `bundled` | 28 | The driver packages in this directory. |
| f | `load` | 37 | Register every bundled driver. Returns the names that loaded. A driver that will not import is reported and s… |

## `src/weewx_evo/ingest/plugins/ecowitt/__main__.py`

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 11:48

| | Name | Zeile | |
|---|---|---|---|
| f | `main` | 34 |  |

## `src/weewx_evo/ingest/plugins/ecowitt/columns.py`

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 11:52

| | Name | Zeile | |
|---|---|---|---|
| f | `schema_fields` | 27 | The fields the standard schema already has. weewx-evo carries the same wview_extended table WeeWX seeds a dat… |
| f | `missing` | 37 | Return the columns a packet needs and the database does not have. Args: packet (dict): A loop packet, i.e. wh… |
| f | `commands` | 59 | Render the columns as the commands that create them. Unchanged from the WeeWX build of this driver: a databas… |
| f | `evo_commands` | 69 | The same, for weewx-evo, which adds columns itself. |
| f | `occupied` | 76 | Return {field: (count, last timestamp)} for archive columns that hold data. This is what stands between a dri… |

## `src/weewx_evo/ingest/plugins/ecowitt/consoles.py`

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 11:57

| | Name | Zeile | |
|---|---|---|---|
| f | `path_for` | 58 | Where to keep the fallback file. Beside the database, because that is a directory the service writes to as it… |
| **C** | `Store` | 73 | Reads and writes the list, from the database if there is one. The database is asked first and written first.… |
| · | &nbsp;&nbsp;`Store.__init__` | 80 | Args: path: the fallback file. state: a weewx-evo driver state -- get/set/delete on strin… |
| · | &nbsp;&nbsp;`Store.read` | 96 | Every PASSKEY on record, and where it was found. |
| · | &nbsp;&nbsp;`Store.add` | 104 | Record a PASSKEY. Returns where it went, or None if it went nowhere. |

## `src/weewx_evo/ingest/plugins/ecowitt/driver.py`

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 12:43

| | Name | Zeile | |
|---|---|---|---|
| **C** | `EcowittDriver` | 58 | Receives uploads from Ecowitt hardware and turns them into packets. |
| · | &nbsp;&nbsp;`EcowittDriver.__init__` | 63 |  |
| · | &nbsp;&nbsp;`EcowittDriver.hardware_name` | 110 |  |
| · | &nbsp;&nbsp;`EcowittDriver.options` | 114 | What this driver can be configured with. Declared rather than documented: the command lin… |
| · | &nbsp;&nbsp;`EcowittDriver.packets` | 174 |  |
| · | &nbsp;&nbsp;`EcowittDriver.redact` | 199 | The upload with the PASSKEY replaced. The PASSKEY is what identifies the station and what… |
| · | &nbsp;&nbsp;`EcowittDriver.status` | 208 |  |
| · | &nbsp;&nbsp;`EcowittDriver.unit_groups` | 221 | Which unit group each field belongs to. The catalog's, plus whatever the mappers have inf… |
| · | &nbsp;&nbsp;`EcowittDriver.missing_columns` | 233 | Columns this station's readings need and the database does not have. A reading only survi… |
| f | `load` | 375 | Register the driver. Called by the plugin loader. |

## `src/weewx_evo/ingest/plugins/ecowitt/infer.py`

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 23:43

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Guess` | 70 | One proposal for a field the catalog does not cover. Attributes: raw (str): The name the hardware used. field… |
| · | &nbsp;&nbsp;`Guess.__init__` | 86 |  |
| **C** | `Inferrer` | 109 | Works out where an unmapped field belongs, from the catalog and from its name. Args: fields (dict): Raw field… |
| · | &nbsp;&nbsp;`Inferrer.__init__` | 120 |  |
| · | &nbsp;&nbsp;`Inferrer.guess` | 157 | Return a Guess for an unmapped field, or None if nothing can be said. |
| f | `report` | 193 | Render guesses as the lines a person needs in order to act on them. |

## `src/weewx_evo/ingest/plugins/ecowitt/mapping.py`

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 11:48

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Mapper` | 35 | Turns raw readings into a WeeWX packet. Args: extensions (dict): Raw field -> WeeWX field, overriding the cat… |
| · | &nbsp;&nbsp;`Mapper.__init__` | 51 |  |
| · | &nbsp;&nbsp;`Mapper.to_packet` | 82 | Return (packet, guesses) for one payload. The packet is ready for WeeWX apart from its un… |
| · | &nbsp;&nbsp;`Mapper.wanted_groups` | 187 | Unit groups the packet needs, for the caller to register with WeeWX. |
| f | `placement_note` | 192 | Say so when the field name claims more than the hardware does. A WN34 reports on tf_chN whether it is a probe… |

## `src/weewx_evo/ingest/plugins/ecowitt/protocol.py`

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 23:43

| | Name | Zeile | |
|---|---|---|---|
| f | `parse` | 35 | Split a payload into raw name/value pairs. Works for both protocols, because a urlencoded body and a query st… |
| f | `device_time` | 60 | Return the timestamp the device sent, or None if it is not usable. Consoles are frequently wrong about the ti… |
| f | `numbers` | 108 | Split raw values into the numeric ones and the rest. Returns (readings, text), where readings holds everythin… |
| f | `redact` | 137 | Replace the values that identify a station, leaving the readings alone. A payload is going to be pasted into… |
| f | `station_id` | 149 | What identifies the console that sent this. The PASSKEY for the Ecowitt protocol, the station ID for Weather… |

## `src/weewx_evo/ingest/plugins/ecowitt/report.py`

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 11:48

| | Name | Zeile | |
|---|---|---|---|
| f | `write` | 45 | Write a report, and return the path. Returns None if it could not be written. |

## `src/weewx_evo/ingest/state.py`

[Treiber](Drivers) · zuletzt geändert 2026-08-26 12:00

| | Name | Zeile | |
|---|---|---|---|
| **C** | `State` | 60 | Small persistent storage for one driver. |
| · | &nbsp;&nbsp;`State.get` | 63 |  |
| · | &nbsp;&nbsp;`State.set` | 65 |  |
| · | &nbsp;&nbsp;`State.delete` | 67 |  |
| **C** | `NoState` | 70 | For a driver that is handed nothing. Remembers within the process only. |
| · | &nbsp;&nbsp;`NoState.__init__` | 73 |  |
| · | &nbsp;&nbsp;`NoState.get` | 76 |  |
| · | &nbsp;&nbsp;`NoState.set` | 79 |  |
| · | &nbsp;&nbsp;`NoState.delete` | 82 |  |
| **C** | `ArchiveState` | 86 | Backed by the archive's metadata table. The right place for it: the table sits with the readings the state pr… |
| · | &nbsp;&nbsp;`ArchiveState.__init__` | 97 |  |
| · | &nbsp;&nbsp;`ArchiveState.get` | 101 |  |
| · | &nbsp;&nbsp;`ArchiveState.set` | 108 |  |
| · | &nbsp;&nbsp;`ArchiveState.delete` | 114 |  |
| **C** | `FileState` | 118 | Backed by a JSON file, for when there is no database to ask. Used by the listener running on its own, and by… |
| · | &nbsp;&nbsp;`FileState.__init__` | 126 |  |
| · | &nbsp;&nbsp;`FileState.get` | 149 |  |
| · | &nbsp;&nbsp;`FileState.set` | 152 |  |
| · | &nbsp;&nbsp;`FileState.delete` | 157 |  |
| f | `for_driver` | 163 | The state a driver should be given, best backing first. |

## `src/weewx_evo/ingest/statuspage.py`

[Listener](Ingest-Listener) · zuletzt geändert 2026-08-26 23:53

| | Name | Zeile | |
|---|---|---|---|
| f | `short_source` | 45 |  |
| f | `recent` | 51 | What the page needs: the last few packets, and how things are going. |
| f | `render` | 99 | The page itself. One file, no dependencies. |

## `src/weewx_evo/ingest/userdrivers.py`

[Treiber](Drivers) · zuletzt geändert 2026-08-26 23:56

| | Name | Zeile | |
|---|---|---|---|
| f | `directory` | 46 | Where user drivers live. |
| f | `installed` | 59 | The drivers installed, as (name, where it came from). |
| f | `load` | 75 | Register every installed user driver. Returns the names that loaded. |
| **C** | `InstallError` | 115 | Anything that stopped a driver being installed. |
| f | `install` | 119 | Install a driver from a git URL, a zip, or a directory. Returns its name and what its code reaches for -- see… |
| f | `remove` | 161 | Delete an installed driver. Returns False if it was not there. |
| f | `inspect_source` | 285 | What a driver's code reaches for, as {note: [files]}. Read, not run. This is a hint and not a guarantee: it w… |

## `src/weewx_evo/language.py`

**keine Seite** · zuletzt geändert 2026-08-27 01:31

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Language` | 79 | One language, and what to say in it. Every lookup falls back to English rather than to the key: a translation… |
| · | &nbsp;&nbsp;`Language.__init__` | 89 |  |
| · | &nbsp;&nbsp;`Language.name` | 95 |  |
| · | &nbsp;&nbsp;`Language.unit_system` | 99 | What a page in this language is read in, unless told otherwise. Empty for English, becaus… |
| · | &nbsp;&nbsp;`Language.obs` | 107 | What a reading is called. Empty where this language has no word. Empty rather than the En… |
| · | &nbsp;&nbsp;`Language.moon_phases` | 126 |  |
| · | &nbsp;&nbsp;`Language.compass` | 129 |  |
| · | &nbsp;&nbsp;`Language.months` | 132 |  |
| · | &nbsp;&nbsp;`Language.days` | 135 |  |
| · | &nbsp;&nbsp;`Language.date_shape` | 138 | This language's `%x`, `%X` or `%c`, as a plain strftime format. Empty where the language… |
| · | &nbsp;&nbsp;`Language.spell` | 150 | A moment, written out in this language. Two substitutions before `strftime` gets it, both… |
| · | &nbsp;&nbsp;`Language.unit_labels` | 182 | The words inside a unit, where this language has different ones. Only the ones that diffe… |
| f | `get` | 214 | The language for a code, or English. `de_AT` reads `de.toml` and then `de_AT.toml` over it, the same way a sk… |
| f | `languages` | 242 | Every language there is a file for, as (code, name). English is always first and always there, because it is… |
| f | `forget` | 257 | Drop what has been read. For a test that changes a file. |

## `src/weewx_evo/moon.py`

**keine Seite** · zuletzt geändert 2026-08-26 20:42

| | Name | Zeile | |
|---|---|---|---|
| f | `julian_centuries` | 179 | Julian centuries since J2000.0, which every series below is in. |
| f | `position` | 184 | The moon's apparent longitude, latitude and distance. Degrees, degrees, and kilometres. Meeus 47, with the fu… |
| f | `equatorial` | 251 | The moon's right ascension, declination and horizontal parallax. Degrees throughout. The parallax is what mak… |
| f | `hour_angle` | 275 | How far the moon is past the meridian, in degrees, -180 to 180. Zero at culmination. This is what a transit i… |
| f | `altitude` | 288 | How high the moon is, in degrees, from where somebody is standing. Topocentric: the parallax is taken off, be… |
| f | `horizon_for` | 309 | The altitude of the moon's *centre* when its upper limb is rising. Negative, and not a constant: the disc is… |
| f | `events` | 328 | The next rising, setting and culmination after a moment. The next one, not "today's". The moon rises about fi… |
| f | `phase_event` | 411 | When the moon is next (or was last) at a given point in its cycle. `phase` is 0 for new, 0.25 for the first q… |

## `src/weewx_evo/mqtt.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `MqttError` | 75 | Anything that stopped a client from doing what was asked. |
| · | &nbsp;&nbsp;`MqttError.__init__` | 78 |  |
| f | `encode_length` | 87 | MQTT's variable-length integer: seven bits a byte, top bit continues. Four bytes at most, so 268 435 455 is t… |
| f | `encode_string` | 105 | A UTF-8 string with a two-byte length in front. Every string in MQTT is this shape -- topic, client id, user… |
| **C** | `Reader` | 117 | Reads whole MQTT packets off a socket. |
| · | &nbsp;&nbsp;`Reader.__init__` | 120 |  |
| · | &nbsp;&nbsp;`Reader.packet` | 140 | The next packet as (type, flags, body). |
| **C** | `Client` | 159 | One connection to a broker. Not thread-safe for two publishers at once by accident: `publish` takes a lock, b… |
| · | &nbsp;&nbsp;`Client.__init__` | 168 |  |
| · | &nbsp;&nbsp;`Client.connected` | 197 |  |
| · | &nbsp;&nbsp;`Client.connect` | 200 | Open the connection and log in. Raises `MqttError`. |
| · | &nbsp;&nbsp;`Client.close` | 262 | Say goodbye if possible, then drop the socket either way. |
| · | &nbsp;&nbsp;`Client.publish` | 315 | Send one message. `retain` is what makes a broker hand the last known value to a browser… |
| · | &nbsp;&nbsp;`Client.subscribe` | 364 | Ask for a topic, and remember it across reconnects. |
| · | &nbsp;&nbsp;`Client.pump` | 398 | Read for a while, delivering what arrives and answering pings. For a subscriber. A publis… |
| · | &nbsp;&nbsp;`Client.ping_if_due` | 421 | Keep the connection alive when nothing has been published. A broker drops a client that h… |

## `src/weewx_evo/netaccess.py`

[Sicherheit](Security) · zuletzt geändert 2026-08-26 23:43

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Access` | 53 | Which addresses are answered. |
| · | &nbsp;&nbsp;`Access.__init__` | 58 |  |
| · | &nbsp;&nbsp;`Access.parse` | 65 | From 'private' (the default), 'any', or a list of addresses. A list may hold networks (`1… |
| · | &nbsp;&nbsp;`Access.allows` | 94 |  |
| f | `warn_if_open` | 119 | Say so, once, at startup, when a service answers the whole internet. |

## `src/weewx_evo/obstypes.py`

[Aggregation](Aggregation) · zuletzt geändert 2026-08-26 10:54

| | Name | Zeile | |
|---|---|---|---|
| **C** | `ObsPolicy` | 18 | What to do with one observation type. |
| **C** | `Policy` | 61 | The aggregation policy for a whole installation. `overrides` mirrors the `[Accumulator]` section of weewx.con… |
| · | &nbsp;&nbsp;`Policy.__init__` | 70 |  |

## `src/weewx_evo/options.py`

[Konfiguration](Configuration) · zuletzt geändert 2026-08-26 23:56

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Invalid` | 51 | A value that a setting cannot take, with a reason a person can act on. |
| **C** | `Option` | 56 | One setting. |
| · | &nbsp;&nbsp;`Option.options` | 95 | The choices, asking the installation if that is where they are. A failure here is not fat… |
| · | &nbsp;&nbsp;`Option.parse` | 110 | Turn what arrived into the value this setting holds. Raises Invalid with a message meant… |
| · | &nbsp;&nbsp;`Option.render` | 196 | The value as the form should show it. Secrets never come back. |
| f | `parse_duration` | 207 | Seconds from '90', '5m', '2h', '7d'. A bare number is seconds. |
| f | `format_duration` | 216 | The other way, choosing the largest unit that stays whole. |
| f | `split_duration` | 231 | Seconds as (amount, unit), in the largest unit that stays whole. 604800 becomes (7, "d"), not (604800, "s").… |
| **C** | `Group` | 247 | Settings that belong together, and become one section of the form. |
| **C** | `Schema` | 259 | Everything one component can be configured with. |
| · | &nbsp;&nbsp;`Schema.option` | 274 |  |
| · | &nbsp;&nbsp;`Schema.defaults` | 280 |  |
| · | &nbsp;&nbsp;`Schema.parse` | 284 | Check a whole form's worth at once. Returns the parsed settings and, separately, what was… |
| f | `schema_of` | 327 | Ask a component to describe itself, if it can. |
| f | `installed_drivers` | 348 | The drivers this installation actually has. Asked at render time, not listed here: installing a driver should… |
| f | `installed_skins` | 360 | The Cheetah skins that are there, for the dropdown that offers them. Read from the directory a feed points at… |
| f | `published_names` | 392 | What the built-in web server has to hand out. The local exports, by name: an export is where somebody said a… |
| f | `building_for` | 417 | Say which file the forms about to be built describe. A dropdown that lists the exports has to read them from… |
| f | `available_languages` | 473 | Every language there is a file for. English is built in. |
| f | `running_config` | 480 | What the configuration says, for a list that has to name reality. The same answer `_current_config` works out… |
| f | `defined_feeds` | 489 | The feeds that exist, by the names the operator gave them. Names, not kinds. Two sets of JSON in two unit sys… |
| f | `website_options` | 516 | The built-in web server. Its own page, because "where does what I made end up" is the question people actuall… |
| f | `core_options` | 562 | What weewx-evo itself is configured with. |

## `src/weewx_evo/planets.py`

**keine Seite** · zuletzt geändert 2026-08-26 23:56

| | Name | Zeile | |
|---|---|---|---|
| f | `heliocentric` | 131 | Where a planet is as seen from the sun. Longitude and latitude in degrees, distance in astronomical units, in… |
| f | `position` | 142 | A planet's apparent longitude, latitude and distance. Degrees, degrees, and astronomical units, seen from the… |
| f | `equatorial` | 153 | A planet's apparent right ascension, declination and distance. Degrees, degrees, astronomical units. The obli… |
| f | `hour_angle` | 167 | How far past the meridian a planet is, in degrees, -180 to 180. Zero at culmination, which is the meridian cr… |
| f | `altitude` | 179 | How high a planet is, in degrees, from where somebody is standing. |
| f | `horizontal` | 187 | A planet's altitude and azimuth in degrees, from a place. Azimuth from north through east, the way a compass… |
| f | `horizon_for` | 198 | The altitude of a planet's centre when it is taken to be rising. Just the refraction. The moon needs a figure… |
| f | `events` | 209 | The next rising, setting and culmination of a planet after a moment. The next one, not "today's" -- the same… |

## `src/weewx_evo/plots.py`

[Diagramme](Plots) · zuletzt geändert 2026-08-26 23:56

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Line` | 94 | One reading drawn in one plot. |
| · | &nbsp;&nbsp;`Line.resolved` | 122 | The same line with the colors WeeWX would have given it. |
| **C** | `Plot` | 135 | One chart. |
| · | &nbsp;&nbsp;`Plot.drawn` | 166 | The lines with their colors filled in. |
| · | &nbsp;&nbsp;`Plot.uses` | 170 | Which readings this plot needs. |
| **C** | `PlotSet` | 175 | The plots there are, and what the readings in them are called. |
| · | &nbsp;&nbsp;`PlotSet.__init__` | 178 |  |
| · | &nbsp;&nbsp;`PlotSet.get` | 191 |  |
| · | &nbsp;&nbsp;`PlotSet.add` | 197 |  |
| · | &nbsp;&nbsp;`PlotSet.remove` | 202 |  |
| · | &nbsp;&nbsp;`PlotSet.by_span` | 207 | Grouped, in the order the spans were first seen. |
| · | &nbsp;&nbsp;`PlotSet.spans` | 214 | How long each span covers, for the manifest. A client laying out its own periods needs th… |
| · | &nbsp;&nbsp;`PlotSet.uses` | 225 |  |
| f | `load` | 231 | Read plots.toml. A file that is not there means no plots, not an error. |
| f | `from_dict` | 243 | Plots out of already-parsed TOML. |
| f | `save` | 295 | Write plots.toml, keeping the previous one. Written beside and moved into place, like the configuration: this… |
| f | `render` | 319 | The plots as a TOML file somebody can edit. |
| **C** | `Imported` | 390 | What an import found, and what it did not take. |
| · | &nbsp;&nbsp;`Imported.report` | 401 | What happened, as something to read before trusting it. |
| f | `labels_from` | 426 | What a WeeWX skin calls each reading: `[Labels] [[Generic]]`. Worth carrying across on its own. Somebody who… |
| f | `from_image_generator` | 442 | Plots out of a WeeWX `[ImageGenerator]` section. The structure there is three deep: a group of plots (`[[day_… |

## `src/weewx_evo/ratelimit.py`

[Sicherheit](Security) · zuletzt geändert 2026-08-26 23:43

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Bucket` | 44 | One address's allowance. A token bucket, which is the simple one. Tokens accrue at `rate` a second up to `bur… |
| · | &nbsp;&nbsp;`Bucket.__init__` | 55 |  |
| · | &nbsp;&nbsp;`Bucket.take` | 59 |  |
| **C** | `Limiter` | 68 | A rate per address, with a bounded amount of memory. Bounded matters: one entry per address is fine on a home… |
| · | &nbsp;&nbsp;`Limiter.__init__` | 77 |  |
| · | &nbsp;&nbsp;`Limiter.enabled` | 89 |  |
| · | &nbsp;&nbsp;`Limiter.allow` | 92 | Whether this address may make a request now. |
| · | &nbsp;&nbsp;`Limiter.remaining` | 120 | How many requests this address has left, without spending one. |
| · | &nbsp;&nbsp;`Limiter.forget` | 131 |  |
| · | &nbsp;&nbsp;`Limiter.status` | 136 |  |
| **C** | `Limits` | 142 | What a service uses: one limit for requests, a tighter one for failures. |
| · | &nbsp;&nbsp;`Limits.__init__` | 154 |  |
| · | &nbsp;&nbsp;`Limits.allow` | 164 |  |
| · | &nbsp;&nbsp;`Limits.has_attempts_left` | 167 | Whether this address has any wrong guesses left. Asks without spending. The distinction i… |
| · | &nbsp;&nbsp;`Limits.failed` | 179 | A wrong token arrived from here. This is what spends an attempt. |
| · | &nbsp;&nbsp;`Limits.succeeded` | 183 | A request got through with the right token: forget its failures. |
| · | &nbsp;&nbsp;`Limits.status` | 187 |  |
| f | `announce` | 196 | Say at startup what is being limited, and what is not. |

## `src/weewx_evo/series.py`

[Zeitreihen](Series) · zuletzt geändert 2026-08-27 10:29

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Series` | 97 | One reading over one span. Two parallel arrays rather than a list of pairs: about 30% smaller once it is JSON… |
| · | &nbsp;&nbsp;`Series.empty` | 124 | Whether there is anything to draw. An all-null series is not. |
| · | &nbsp;&nbsp;`Series.rounded` | 128 | Round the values in place and return self. Three decimals is well past any weather sensor… |
| **C** | `Reader` | 145 | Reads series from one archive database. Holds a connection and nothing else -- no cache, and so nothing that… |
| · | &nbsp;&nbsp;`Reader.__init__` | 152 |  |
| · | &nbsp;&nbsp;`Reader.columns` | 163 | The readings the archive table has a column for. |
| · | &nbsp;&nbsp;`Reader.system` | 172 | Which unit system the archive holds. US, METRIC or METRICWX. Taken from the first record,… |
| · | &nbsp;&nbsp;`Reader.has_daily` | 186 | Whether there is a daily summary table for this reading. |
| · | &nbsp;&nbsp;`Reader.span` | 198 | The first and last record in the archive, or None if it is empty. Two queries, not one, a… |
| · | &nbsp;&nbsp;`Reader.series` | 226 | A reading over a span. With no aggregate, the archive records themselves. With one, the s… |
| · | &nbsp;&nbsp;`Reader.aggregate` | 265 | One number for one span. Answered from the daily summaries when the span is whole days an… |
| · | &nbsp;&nbsp;`Reader.degree_days` | 296 | Heating, cooling and growing degree days over a span. Not a column and never was: a count… |
| · | &nbsp;&nbsp;`Reader.vector` | 407 | One wind vector for one span, as (magnitude, bearing). `avg` and `sum` add the readings a… |
| · | &nbsp;&nbsp;`Reader.buckets` | 770 | The buckets a span is cut into, as (begin, end) pairs. Days, months and years are whole c… |
| f | `is_midnight` | 870 | Whether a timestamp falls exactly on a local midnight. The daily summaries are keyed by these, so this is the… |

## `src/weewx_evo/settings.py`

[Konfiguration](Configuration) · zuletzt geändert 2026-08-26 23:55

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Settings` | 93 | One resolved view of the configuration. |
| · | &nbsp;&nbsp;`Settings.__init__` | 96 |  |
| · | &nbsp;&nbsp;`Settings.get` | 113 | The value of one setting, and remember where it came from. |
| · | &nbsp;&nbsp;`Settings.source` | 186 | Where the last-read value of this setting came from. |
| · | &nbsp;&nbsp;`Settings.all` | 190 |  |
| · | &nbsp;&nbsp;`Settings.view` | 195 | One component's corner of the settings, and nothing else. A driver gets this rather than… |
| · | &nbsp;&nbsp;`Settings.reload` | 211 | Re-read the file. Returns whether anything actually changed. This is what a settings serv… |
| · | &nbsp;&nbsp;`Settings.needs_restart` | 244 | Which of the settings that just changed cannot be applied live. The schema already says s… |
| · | &nbsp;&nbsp;`Settings.explain` | 254 | One line per setting, saying what it is and where it came from. `extra` is the schemas th… |
| f | `load` | 302 | Build a Settings from the places there are. A missing configuration file is not an error: a first start has n… |
| f | `running` | 345 | The settings this process resolved, or None before it has. |
| f | `running_args` | 350 | The arguments this run was given. Which file, above all. |
| f | `set_running` | 355 |  |
| f | `forget_running` | 361 | Start over. For a test that resolves twice in one process. |

## `src/weewx_evo/skinkit.py`

**keine Seite** · zuletzt geändert 2026-08-27 01:11

| | Name | Zeile | |
|---|---|---|---|
| **C** | `ValueTuple` | 41 | A number, the unit it is in, and the group it belongs to. WeeWX's own, and a tuple on purpose: extensions unp… |
| · | &nbsp;&nbsp;`ValueTuple.value` | 58 |  |
| · | &nbsp;&nbsp;`ValueTuple.unit` | 62 |  |
| · | &nbsp;&nbsp;`ValueTuple.group` | 66 |  |
| **C** | `ValueHelper` | 91 | A number that knows how to print itself. Our `Value`, with the constructor a skin's code writes: a value tupl… |
| · | &nbsp;&nbsp;`ValueHelper.__init__` | 98 |  |
| · | &nbsp;&nbsp;`ValueHelper.value_t` | 121 |  |
| **C** | `UnitInfoHelper` | 125 | `$unit.label.outTemp`, `$unit.unit_type.pressure`, `$unit.format.x`. WeeWX builds it from a formatter and a c… |
| · | &nbsp;&nbsp;`UnitInfoHelper.__init__` | 133 |  |
| **C** | `ObsInfoHelper` | 173 | `$obs.label.outTemp` -- what a reading is called, from the skin. WeeWX builds it from the whole skin configur… |
| · | &nbsp;&nbsp;`ObsInfoHelper.__init__` | 180 |  |
| f | `timespan_binder` | 200 | A span, as a skin hands one back to a template. WeeWX's `TimespanBinder`, built from a formatter and a conver… |
| **C** | `SearchList` | 222 | What a skin's extension inherits from. `self.generator` is the only thing it is given, and what it asks that… |
| · | &nbsp;&nbsp;`SearchList.__init__` | 230 |  |
| · | &nbsp;&nbsp;`SearchList.get_extension_list` | 233 | What goes into the search list. `[self]` by default, which is WeeWX's own and not a detai… |
| **C** | `Reports` | 246 | `config_dict["StdReport"]`, which answers for any report name. An extension reads its own section out of weew… |
| · | &nbsp;&nbsp;`Reports.__init__` | 260 |  |
| **C** | `Generator` | 269 | What an extension is handed. WeeWX calls this the report generator. Two audiences, and they read different ha… |
| · | &nbsp;&nbsp;`Generator.__init__` | 284 |  |
| **C** | `Formatter` | 318 | Turns a value tuple into text. WeeWX's `weewx.units.Formatter`. |
| · | &nbsp;&nbsp;`Formatter.__init__` | 321 |  |
| · | &nbsp;&nbsp;`Formatter.toString` | 337 |  |
| · | &nbsp;&nbsp;`Formatter.get_label_string` | 347 |  |
| · | &nbsp;&nbsp;`Formatter.to_ordinal_compass` | 350 |  |
| **C** | `Converter` | 356 | Turns a value tuple into what the page shows it in. Built two ways, because WeeWX's is: from a `units.Target`… |
| · | &nbsp;&nbsp;`Converter.__init__` | 369 |  |
| · | &nbsp;&nbsp;`Converter.convert` | 385 | One value, or a whole series of them. A list as well as a number, because `get_series` ha… |
| · | &nbsp;&nbsp;`Converter.getTargetUnit` | 406 |  |
| **C** | `DbBinder` | 411 | `db_lookup()` and what it returns. An extension calls `db_lookup()` with no arguments, or with a binding name… |
| · | &nbsp;&nbsp;`DbBinder.__init__` | 419 |  |
| · | &nbsp;&nbsp;`DbBinder.get_manager` | 423 |  |
| **C** | `Manager` | 430 | A database, as an extension expects to be handed one. |
| · | &nbsp;&nbsp;`Manager.__init__` | 433 |  |
| · | &nbsp;&nbsp;`Manager.std_unit_system` | 439 |  |
| · | &nbsp;&nbsp;`Manager.firstGoodStamp` | 443 |  |
| · | &nbsp;&nbsp;`Manager.lastGoodStamp` | 448 |  |
| · | &nbsp;&nbsp;`Manager.getSql` | 452 | One row, or None. WeeWX's own name for it. |
| · | &nbsp;&nbsp;`Manager.genSql` | 461 |  |
| · | &nbsp;&nbsp;`Manager.has_data` | 467 |  |
| · | &nbsp;&nbsp;`Manager.getAggregate` | 475 |  |
| **C** | `TimeSpan` | 484 | A start and a stop. WeeWX's `weeutil.weeutil.TimeSpan`. |
| · | &nbsp;&nbsp;`TimeSpan.start` | 491 |  |
| · | &nbsp;&nbsp;`TimeSpan.stop` | 495 |  |
| · | &nbsp;&nbsp;`TimeSpan.length` | 499 |  |
| · | &nbsp;&nbsp;`TimeSpan.includesArchiveTime` | 502 |  |
| f | `search_up` | 511 | Look for a key here, then in the section above, and so on. A section knows its parent (`weewxconf.Section`),… |
| f | `accumulateLeaves` | 530 | Every scalar in a section and in the ones above it, flattened. WeeWX's, transcribed. `max_level` counts how f… |
| f | `rounder` | 552 | Round a number, or a sequence of them. WeeWX's own, and its shape. A *plain list* comes back for anything ite… |
| f | `to_bool` | 582 |  |
| f | `to_int` | 593 |  |
| f | `to_float` | 603 |  |
| f | `option_as_list` | 611 |  |
| f | `startOfDay` | 619 | Local midnight of the day a moment falls in. |
| f | `startOfArchiveDay` | 627 | The same, but a record stamped exactly at midnight belongs to the day before it -- an archive record covers t… |
| f | `archiveDaySpan` | 634 |  |
| f | `mph_to_knot` | 640 | Miles an hour to knots. WeeWX's factor, not a recomputed one. |
| f | `kph_to_knot` | 645 |  |
| f | `mps_to_knot` | 649 |  |
| f | `get_series` | 653 | A reading over a span, as three value tuples. When each bucket starts, when it stops, and what is in it. WeeW… |
| f | `get_aggregate` | 676 | One number for one span. |
| f | `beaufort` | 689 | The Beaufort number for a wind speed in knots. |
| f | `install_weewx_names` | 798 | Make `import weewx` work, once per process. For a skin written for WeeWX. The skins that ship here import fro… |

## `src/weewx_evo/skins/__init__.py`

**keine Seite** · zuletzt geändert 2026-08-26 22:35

| | Name | Zeile | |
|---|---|---|---|
| f | `bundled` | 21 | The skins that ship, by name. |

## `src/weewx_evo/skins/deck/options.py`

**keine Seite** · zuletzt geändert 2026-08-27 01:54

| | Name | Zeile | |
|---|---|---|---|
| f | `groups` | 39 | The skin's own settings, as the admin page and `--explain` see them. |

## `src/weewx_evo/skins/deck/tags.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:11

| | Name | Zeile | |
|---|---|---|---|
| f | `logdbg` | 60 |  |
| f | `loginf` | 64 |  |
| f | `logerr` | 68 |  |
| **C** | `RainTags` | 72 | " Code for last_rain and time_since_last_rain is taken (and slightly modified) from https://github.com/vinces… |
| · | &nbsp;&nbsp;`RainTags.__init__` | 87 |  |
| · | &nbsp;&nbsp;`RainTags.get_extension_list` | 90 | Returns a search list extension with datetime of last rain and secs since then. Parameter… |
| **C** | `GeneralUtil` | 377 |  |
| · | &nbsp;&nbsp;`GeneralUtil.__init__` | 378 |  |
| · | &nbsp;&nbsp;`GeneralUtil.format_raw_value` | 392 | Returns a ValueHelper for a raw value and an obs type. Args: value (float): The value obs… |
| · | &nbsp;&nbsp;`GeneralUtil.get_software_obs` | 405 | Get the observations provided by software (weewx calculations), was added because the has… |
| · | &nbsp;&nbsp;`GeneralUtil.spell` | 415 | A moment, written the way this language writes one. `$spell($week.start.raw, $get_time_fo… |
| · | &nbsp;&nbsp;`GeneralUtil.month_word` | 442 | The short name of a month, in the page's language. `calendar.month_abbr` follows the proc… |
| · | &nbsp;&nbsp;`GeneralUtil.weekday_names` | 458 | The seven days, short, starting on Sunday. Sunday first because that is the order a calen… |
| · | &nbsp;&nbsp;`GeneralUtil.month_names` | 471 | The twelve months, short, in the page's language. |
| · | &nbsp;&nbsp;`GeneralUtil.get_locale` | 475 | The locale the browser code formats dates and numbers in. One setting decides what langua… |
| · | &nbsp;&nbsp;`GeneralUtil.getValueHelper` | 494 | Get a value helper for a value_vt. Args: value_vt (tuple): A value tuple Returns: obj: A… |
| · | &nbsp;&nbsp;`GeneralUtil.get_base_path` | 507 | Get the base path + a given path. Args: path (string): The path Returns: str: The base pa… |
| · | &nbsp;&nbsp;`GeneralUtil.show_yesterday` | 525 |  |
| · | &nbsp;&nbsp;`GeneralUtil.get_context_key_from_time_span` | 531 | Get the context key from a given time span. Args: start_ts (int): The start timestamp end… |
| · | &nbsp;&nbsp;`GeneralUtil.show_sensor_page` | 561 |  |
| · | &nbsp;&nbsp;`GeneralUtil.show_cmon_page` | 567 |  |
| · | &nbsp;&nbsp;`GeneralUtil.get_time_format_dict` | 573 |  |
| · | &nbsp;&nbsp;`GeneralUtil.get_unit_label` | 576 | Get the unit label for a given unit. @see https://www.weewx.com/docs/customizing.htm#unit… |
| · | &nbsp;&nbsp;`GeneralUtil.get_unit_for_obs` | 603 | Get the unit for a given observation. Args: observation (string): The observation observa… |
| · | &nbsp;&nbsp;`GeneralUtil.get_windrose_enabled` | 668 | Check if the windrose is enabled. Returns: bool: True if the windrose is enabled, False o… |
| · | &nbsp;&nbsp;`GeneralUtil.get_icon` | 721 | Returns an include path for an icon based on the observation # @see https://www.weewx.com… |
| · | &nbsp;&nbsp;`GeneralUtil.get_color` | 914 | Color settings for observations. Args: observation (string): The observation context (str… |
| · | &nbsp;&nbsp;`GeneralUtil.get_time_span_from_context` | 1030 | Get tag for use in templates. Args: context (string): The time range day: Daily TimeSpanB… |
| · | &nbsp;&nbsp;`GeneralUtil.get_static_pages` | 1064 | Get static pages. Returns: list: Static pages array |
| · | &nbsp;&nbsp;`GeneralUtil.get_static_page_title` | 1089 | Get static page title. Args: page (string): The page Returns: str: The page title |
| · | &nbsp;&nbsp;`GeneralUtil.get_ordinates` | 1107 |  |
| · | &nbsp;&nbsp;`GeneralUtil.dwd_warning_has_warning` | 1135 | Check if a given warning is empty. Args: region_key (string): The region key Returns: boo… |
| · | &nbsp;&nbsp;`GeneralUtil.get_dwd_warning_region_name` | 1156 | Get the name of a given region. Args: region_key (string): The region key Returns: str: T… |
| · | &nbsp;&nbsp;`GeneralUtil.get_dwd_warnings` | 1174 | Get the configured warn regions. `[DisplayOptions][[dwd]][[[warning]]]`, holding `countie… |
| **C** | `ArchiveUtil` | 1191 |  |
| · | &nbsp;&nbsp;`ArchiveUtil.__init__` | 1192 |  |
| · | &nbsp;&nbsp;`ArchiveUtil.get_extension_list` | 1195 | Returns a search list extension with two additions. Parameters: timespan: An instance of… |
| · | &nbsp;&nbsp;`ArchiveUtil.get_stat_table_month_obs` | 1220 | Returns a TimeSpanBinder a period. Args: start_ts (int): The start timestamp end_ts (int)… |
| · | &nbsp;&nbsp;`ArchiveUtil.get_day_archive_enabled` | 1237 | Get day archive enabled. Returns: bool|string: Value of day template if day archive is en… |
| · | &nbsp;&nbsp;`ArchiveUtil.get_archive_days_array` | 1252 | Get an array of days between two timestamps. Args: start_ts (int): The start timestamp en… |
| · | &nbsp;&nbsp;`ArchiveUtil.filter_months` | 1279 | Returns a filtered list of months Args: months (list): A list of months [2022-01, 2022-02… |
| · | &nbsp;&nbsp;`ArchiveUtil.fake_get_report_years` | 1299 | Returns a fake $SummaryByYear tag. Strings, because that is what the real `$SummaryByYear… |
| **C** | `CelestialUtil` | 1327 |  |
| · | &nbsp;&nbsp;`CelestialUtil.get_celestial_icon` | 1329 | Returns an include path for an icon based on the observation Args: observation (string):… |
| **C** | `DiagramUtil` | 1361 |  |
| · | &nbsp;&nbsp;`DiagramUtil.__init__` | 1362 |  |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram_data` | 1369 | Get diagram data. Args: observation (string): The observation observation_key (string): T… |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram` | 1460 | Choose between line and bar. Args: observation (string): The observation context_key (str… |
| · | &nbsp;&nbsp;`DiagramUtil.get_aggregate_type` | 1508 | aggregate_type for observations series. @see https://github.com/weewx/weewx/wiki/Tags-for… |
| · | &nbsp;&nbsp;`DiagramUtil.get_aggregate_interval` | 1557 | aggregate_interval for observations series. @see https://github.com/weewx/weewx/wiki/Tags… |
| · | &nbsp;&nbsp;`DiagramUtil.get_chart` | 1678 | The whole chart, as JSON, for one `data-chart` attribute. What this replaced: ten `data-`… |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram_props` | 1746 | Get diagram props from skin.conf. Args: obs (string): Observation context (string): Day,… |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram_props_obs` | 1796 | Same as get_diagram_props, but for specific observations. Returns the values in [combined… |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram_boundary` | 1866 | boundary for observations series for diagrams. Args: context (string): Day, week, month,… |
| · | &nbsp;&nbsp;`DiagramUtil.get_rounding` | 1894 | Rounding settings for observations. Args: observation (string): The observation observati… |
| · | &nbsp;&nbsp;`DiagramUtil.get_hour_delta` | 2036 | Get delta for $span($hour_delta=$delta) call. Args: context (string): Day, week, month, y… |
| · | &nbsp;&nbsp;`DiagramUtil.get_gauge_diagram_props` | 2062 | Get gauge props from skin.conf. Args: obs (string): Observation context (string): Day, we… |
| · | &nbsp;&nbsp;`DiagramUtil.get_gauge_diagram_prop` | 2080 | Get gauge prop from skin.conf. Args: obs (string): Observation prop (string): Prop contex… |
| · | &nbsp;&nbsp;`DiagramUtil.get_windrose_chart` | 2101 | The wind rose, as JSON for one `data-chart` attribute. Sixteen compass points, one stacke… |
| · | &nbsp;&nbsp;`DiagramUtil.get_windrose_data` | 2125 | Get data for rendering wind rose in JS. start_ts (Timestamp): Start timestamp end_ts (Tim… |
| **C** | `StatsUtil` | 2320 |  |
| · | &nbsp;&nbsp;`StatsUtil.__init__` | 2321 |  |
| · | &nbsp;&nbsp;`StatsUtil.get_show_min` | 2330 | Returns if the min stats should be shown. Args: observation (string): The observation Ret… |
| · | &nbsp;&nbsp;`StatsUtil.get_show_sum` | 2360 | Returns if the sum stats should be shown. Args: observation (string): The observation Ret… |
| · | &nbsp;&nbsp;`StatsUtil.get_show_max` | 2377 | Returns if the max stats should be shown. Args: observation (string): The observation Ret… |
| · | &nbsp;&nbsp;`StatsUtil.get_labels` | 2395 | Returns a label like "Todays Max" or "Monthly average". Args: prop (string): Min, Max, Su… |
| · | &nbsp;&nbsp;`StatsUtil.has_column` | 2411 | Whether the archive has this reading at all. A station with no snow gauge should not be s… |
| · | &nbsp;&nbsp;`StatsUtil.get_climatological_day` | 2422 | Return number of days in period for day parameter. Args: day (string): Eg. rainDays, hotD… |
| · | &nbsp;&nbsp;`StatsUtil.get_climatological_day_description` | 2614 | Return description of day. Args: day (string): Eg. rainDays, hotDays. Returns: string: Da… |
| · | &nbsp;&nbsp;`StatsUtil.get_calendar_color` | 2706 | Returns a color for use in diagram. Args: obs (string): The observation Returns: string:… |
| · | &nbsp;&nbsp;`StatsUtil.get_calendar_chart` | 2741 | The days, or the months, depending on how long the span is. Under about fourteen months:… |
| · | &nbsp;&nbsp;`StatsUtil.get_month_matrix` | 2782 | Months across, years down, as JSON for one `data-chart`. What a day grid turns into once… |
| · | &nbsp;&nbsp;`StatsUtil.get_calendar_data` | 2829 | Returns array of calendar data for use in diagram. Args: obs (string): The observation ag… |
| **C** | `TableUtil` | 2904 |  |
| · | &nbsp;&nbsp;`TableUtil.__init__` | 2905 |  |
| · | &nbsp;&nbsp;`TableUtil.get_table_aggregate_interval` | 2919 | aggregate_interval for observations series for tables. Args: context (string): Day, week,… |
| · | &nbsp;&nbsp;`TableUtil.get_table_boundary` | 2947 | boundary for observations series for tables. Args: context (string): Day, week, month, ye… |
| · | &nbsp;&nbsp;`TableUtil.get_table_headers` | 2976 | Returns tableheaders for use in carbon data table. Args: start_ts (Timestamp): Start time… |
| · | &nbsp;&nbsp;`TableUtil.get_table_rows` | 3016 | Returns table values for use in carbon data table. Args: start_ts (Timestamp): Start time… |
| **C** | `ForecastUtil` | 3116 |  |
| · | &nbsp;&nbsp;`ForecastUtil.__init__` | 3117 |  |
| · | &nbsp;&nbsp;`ForecastUtil.get_day_icon` | 3133 | Returns the icon for the day (summary) or a single period. Args: summary (dict): The summ… |

## `src/weewx_evo/sources.py`

[Mehrere Quellen](Multiple-Sources) · zuletzt geändert 2026-08-26 23:47

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Rule` | 41 | Which sources may supply a field, best first. |
| · | &nbsp;&nbsp;`Rule.matches` | 47 |  |
| **C** | `Policy` | 52 | Which source wins for which field. Rules are checked in order and the first matching pattern decides, so put… |
| · | &nbsp;&nbsp;`Policy.from_config` | 75 |  |
| · | &nbsp;&nbsp;`Policy.is_empty` | 84 |  |
| · | &nbsp;&nbsp;`Policy.order_for` | 87 | The preference list for one field, or None if no rule covers it. |
| · | &nbsp;&nbsp;`Policy.choose` | 94 | Which of the sources that actually have this field should supply it. `available` is the s… |
| f | `sources_by_field` | 117 | Which sources carried which field, across a list of packets. |
| f | `apply` | 126 | Thin the packets down to the winning source for each field. Returns the packets with losing fields removed, a… |
| f | `replace_data` | 161 | A copy of a packet carrying different observations. |

## `src/weewx_evo/sun.py`

[Sonne](Sun) · zuletzt geändert 2026-08-26 23:47

| | Name | Zeile | |
|---|---|---|---|
| f | `solar` | 54 | The sun's declination, the equation of time, and Earth's distance. Declination in degrees, the equation of ti… |
| f | `solar_longitude` | 108 | Where the sun is along the ecliptic, in degrees. Zero at the vernal equinox, ninety at the June solstice, and… |
| f | `season` | 157 | When an equinox or a solstice falls, as a timestamp. `which` is 0 for the March equinox, 1 for the June solst… |
| f | `delta_t` | 211 | Terrestrial Time minus UTC, in seconds. NASA's own polynomial fit, for 2005 onwards and for the couple of dec… |
| f | `equatorial` | 223 | The sun's right ascension and declination, in degrees. From the same apparent longitude the declination comes… |
| f | `position` | 243 | The sun's elevation in degrees, and Earth's distance in AU. |
| f | `solar_noon` | 275 | The moment the sun is highest, on the sun's day containing `when`. Two corrections to clock noon: how far eas… |
| f | `crossings` | 296 | When the sun passes an elevation on the way up and on the way down. Both times are around the solar noon near… |
| f | `events` | 353 | Sunrise, sunset and the civil twilight around them, for one day. Uses pyephem where it is installed: it accou… |
| f | `day_night` | 425 | What a chart needs to shade the hours of darkness. Returns which of day or night the span begins in, every cr… |
| f | `rising_setting` | 489 | The next rising, setting and transit after a given moment. Anchored at an instant rather than at a day, becau… |
| f | `moon_age` | 590 | Days since the last new moon, 0 to 29.53. From the phase series in `moon.py`, which lands within ten seconds… |
| f | `moon_fullness` | 604 | How much of the disc is lit, as a percentage. Not the fraction of the cycle: the moon is half lit a quarter o… |
| f | `moon_phase` | 634 | Which of the eight phases, and its name. The quarters are moments and the crescents are stretches, so the eig… |
| f | `moon_events` | 645 | When the moon rises, sets and is highest, for one local day. Worked out here now, from Meeus's series in `moo… |
| f | `local_midnight` | 660 | The start of the local day a timestamp falls in. |
| f | `describe` | 666 | One day's sun, as a line somebody reads. For the CLI. |

## `src/weewx_evo/tags.py`

**keine Seite** · zuletzt geändert 2026-08-27 01:07

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Missing` | 145 | A tag nothing here can answer. An AttributeError, because that is what tells Cheetah to leave the text alone.… |
| **C** | `Value` | 156 | One number, and everything needed to print it. WeeWX calls this a ValueHelper. `str()` of it is the formatted… |
| · | &nbsp;&nbsp;`Value.__init__` | 166 |  |
| · | &nbsp;&nbsp;`Value.format` | 185 | The value as text. `format_string` is a printf format for a number and a strftime format… |
| · | &nbsp;&nbsp;`Value.toString` | 240 |  |
| · | &nbsp;&nbsp;`Value.formatted` | 247 | The value with no label. `$day.outTemp.max.formatted`. |
| · | &nbsp;&nbsp;`Value.nolabel` | 251 |  |
| · | &nbsp;&nbsp;`Value.string` | 255 |  |
| · | &nbsp;&nbsp;`Value.long_form` | 258 | A length of time in words. "5 hours, 12 minutes, 3 seconds". What `$almanac.sun.visible`… |
| · | &nbsp;&nbsp;`Value.raw` | 292 | The number itself, unformatted. What a JSON document wants. |
| · | &nbsp;&nbsp;`Value.round` | 296 |  |
| · | &nbsp;&nbsp;`Value.ordinal_compass` | 302 | A bearing as a point of the compass. `$day.wind.vecdir`. The skin's own words where it ha… |
| · | &nbsp;&nbsp;`Value.json` | 317 |  |
| · | &nbsp;&nbsp;`Value.convert` | 324 | The same reading in another unit. `$day.outTemp.max.degree_C`. |
| · | &nbsp;&nbsp;`Value.exists` | 348 |  |
| · | &nbsp;&nbsp;`Value.has_data` | 352 |  |
| **C** | `Unknown` | 362 | A reading nothing knows about. Printed as WeeWX prints it, so a template that mentions a sensor this station… |
| · | &nbsp;&nbsp;`Unknown.__init__` | 372 |  |
| · | &nbsp;&nbsp;`Unknown.exists` | 388 |  |
| · | &nbsp;&nbsp;`Unknown.has_data` | 392 |  |
| **C** | `Aggregate` | 398 | A span, a reading, and a question. `$day.outTemp.max`. Nothing has been asked of the database yet: a template… |
| · | &nbsp;&nbsp;`Aggregate.__init__` | 408 |  |
| · | &nbsp;&nbsp;`Aggregate.answer` | 424 | Ask, and wrap the answer so a template can print it. |
| **C** | `Reading` | 438 | A span and a reading. `$day.outTemp`. Prints as the reading over that span, which for a template is almost al… |
| · | &nbsp;&nbsp;`Reading.__init__` | 448 |  |
| · | &nbsp;&nbsp;`Reading.series` | 464 | The same series every feed uses, for a template that draws itself. |
| **C** | `Span` | 476 | A stretch of time. `$day`, `$week`, `$month`, `$span(hour_delta=6)`. Any attribute is a reading, which is wha… |
| · | &nbsp;&nbsp;`Span.__init__` | 485 |  |
| · | &nbsp;&nbsp;`Span.check_for_data` | 496 | `#if $recent.check_for_data($obs)` -- is there anything to draw? A template with the read… |
| · | &nbsp;&nbsp;`Span.start` | 507 |  |
| · | &nbsp;&nbsp;`Span.end` | 514 |  |
| · | &nbsp;&nbsp;`Span.length` | 521 |  |
| · | &nbsp;&nbsp;`Span.hours` | 527 |  |
| · | &nbsp;&nbsp;`Span.days` | 531 |  |
| · | &nbsp;&nbsp;`Span.months` | 535 |  |
| · | &nbsp;&nbsp;`Span.years` | 539 |  |
| · | &nbsp;&nbsp;`Span.spans` | 542 |  |
| **C** | `Current` | 558 | The latest reading of everything. `$current.outTemp`. One record, not a span. A template printing `$current.b… |
| · | &nbsp;&nbsp;`Current.__init__` | 568 |  |
| **C** | `Station` | 607 | `$station.location`, `$station.latitude_f`. Where the station is and what it is called. Every one of these co… |
| · | &nbsp;&nbsp;`Station.__init__` | 617 |  |
| **C** | `Labels` | 660 | `$obs.label.outTemp` -- what a reading is called, in words. Deliberately *not* dict-like. Cheetah tries `obj[… |
| · | &nbsp;&nbsp;`Labels.__init__` | 671 |  |
| · | &nbsp;&nbsp;`Labels.label` | 676 |  |
| **C** | `UnitInfo` | 702 | `$unit.label.outTemp`, `$unit.unit_type.rain`. What a reading is shown in, asked about rather than printed. A… |
| · | &nbsp;&nbsp;`UnitInfo.__init__` | 712 |  |
| · | &nbsp;&nbsp;`UnitInfo.label` | 716 |  |
| · | &nbsp;&nbsp;`UnitInfo.unit_type` | 720 |  |
| · | &nbsp;&nbsp;`UnitInfo.format` | 724 |  |
| · | &nbsp;&nbsp;`UnitInfo.unit_type_dict` | 728 | `$unit.unit_type_dict.outTemp` -- WeeWX's older spelling. |
| · | &nbsp;&nbsp;`UnitInfo.label_dict` | 733 |  |
| · | &nbsp;&nbsp;`UnitInfo.format_dict` | 737 |  |
| **C** | `Almanac` | 772 | `$almanac.sunrise`, `$almanac.moon_phase`, `$almanac.moon.rise`. What is in the sky, for the day the page is… |
| · | &nbsp;&nbsp;`Almanac.__init__` | 789 |  |
| · | &nbsp;&nbsp;`Almanac.hasExtras` | 806 | Whether the harder questions can be answered at all. Always, now. In WeeWX this asks "is… |
| · | &nbsp;&nbsp;`Almanac.sunrise` | 831 |  |
| · | &nbsp;&nbsp;`Almanac.sunset` | 835 |  |
| · | &nbsp;&nbsp;`Almanac.sun` | 839 |  |
| · | &nbsp;&nbsp;`Almanac.moon` | 843 |  |
| · | &nbsp;&nbsp;`Almanac.moon_phase` | 849 |  |
| · | &nbsp;&nbsp;`Almanac.moon_index` | 858 |  |
| · | &nbsp;&nbsp;`Almanac.moon_fullness` | 862 |  |
| · | &nbsp;&nbsp;`Almanac.moon_age` | 866 |  |
| **C** | `Body` | 898 | One thing in the sky. `$almanac.sun.rise`, `$almanac.moon.transit`. |
| · | &nbsp;&nbsp;`Body.__init__` | 903 |  |
| · | &nbsp;&nbsp;`Body.visible_change` | 954 | How much longer the body is up today than it was `days_ago`. The number behind "three min… |
| **C** | `Tags` | 1165 | Everything a template can name, and a record of what it could not. One of these per render. It holds the data… |
| · | &nbsp;&nbsp;`Tags.__init__` | 1173 |  |
| · | &nbsp;&nbsp;`Tags.missed` | 1232 |  |
| · | &nbsp;&nbsp;`Tags.report` | 1241 | What a skin asked for and did not get, for the log and the page. |
| · | &nbsp;&nbsp;`Tags.units_of` | 1253 |  |
| · | &nbsp;&nbsp;`Tags.exists` | 1257 |  |
| · | &nbsp;&nbsp;`Tags.has_data` | 1271 |  |
| · | &nbsp;&nbsp;`Tags.shown` | 1279 | A number worked out in one unit, wrapped in what to show it in. Everything the database a… |
| · | &nbsp;&nbsp;`Tags.answer` | 1296 | The one place a tag becomes a database query. |
| · | &nbsp;&nbsp;`Tags.Extras` | 1336 | `$Extras.something` -- whatever the skin's author invented. |
| · | &nbsp;&nbsp;`Tags.DisplayOptions` | 1341 | `$DisplayOptions.get('...')` -- what the skin shows and hides. |
| · | &nbsp;&nbsp;`Tags.lang` | 1346 | Which language the skin is being rendered in. |
| · | &nbsp;&nbsp;`Tags.to_list` | 1351 | `$to_list($DisplayOptions.get('x'))`. A configuration file gives one string where there i… |
| · | &nbsp;&nbsp;`Tags.getattr` | 1365 | `$getattr($current, $x)` -- a reading whose name is in a variable. A template walking a l… |
| · | &nbsp;&nbsp;`Tags.getobs` | 1378 | `$getobs($plot_name)` -- which readings a chart draws. A template asks so that it can say… |
| · | &nbsp;&nbsp;`Tags.to_bool` | 1390 |  |
| · | &nbsp;&nbsp;`Tags.to_int` | 1396 |  |
| · | &nbsp;&nbsp;`Tags.to_float` | 1411 |  |
| · | &nbsp;&nbsp;`Tags.jsonize` | 1415 |  |
| · | &nbsp;&nbsp;`Tags.rnd` | 1421 |  |
| · | &nbsp;&nbsp;`Tags.season` | 1425 | The meteorological season this moment is in. Three months at a time, starting in December… |
| · | &nbsp;&nbsp;`Tags.almanac` | 1441 |  |
| · | &nbsp;&nbsp;`Tags.station` | 1447 |  |
| · | &nbsp;&nbsp;`Tags.obs` | 1451 |  |
| · | &nbsp;&nbsp;`Tags.unit` | 1455 |  |
| · | &nbsp;&nbsp;`Tags.gettext` | 1458 | `$gettext("Outside Temperature")`. Whatever the skin's own language files say, and the te… |
| · | &nbsp;&nbsp;`Tags.pgettext` | 1467 |  |
| · | &nbsp;&nbsp;`Tags.current` | 1471 |  |
| · | &nbsp;&nbsp;`Tags.latest` | 1477 |  |
| · | &nbsp;&nbsp;`Tags.hour` | 1495 |  |
| · | &nbsp;&nbsp;`Tags.hours_ago` | 1498 |  |
| · | &nbsp;&nbsp;`Tags.day` | 1503 |  |
| · | &nbsp;&nbsp;`Tags.days_ago` | 1506 |  |
| · | &nbsp;&nbsp;`Tags.yesterday` | 1511 |  |
| · | &nbsp;&nbsp;`Tags.week` | 1515 |  |
| · | &nbsp;&nbsp;`Tags.weeks_ago` | 1518 |  |
| · | &nbsp;&nbsp;`Tags.month` | 1524 |  |
| · | &nbsp;&nbsp;`Tags.months_ago` | 1527 |  |
| · | &nbsp;&nbsp;`Tags.year` | 1532 |  |
| · | &nbsp;&nbsp;`Tags.years_ago` | 1535 |  |
| · | &nbsp;&nbsp;`Tags.rainyear` | 1540 | The year as a rain gauge counts it, which need not start in January. |
| · | &nbsp;&nbsp;`Tags.alltime` | 1546 | Everything there is, rounded out to whole days. Not the first and last record: that span… |
| · | &nbsp;&nbsp;`Tags.span` | 1561 | `$span($hour_delta=6)` -- a stretch ending now. |
| · | &nbsp;&nbsp;`Tags.trend` | 1578 | `$trend.barometer`, and `$trend($time_delta=7200).barometer`. Both spellings, because tem… |
| **C** | `Trend` | 1612 | How much a reading has moved. `$trend.barometer`. The difference between now and a few hours ago, which is wh… |
| · | &nbsp;&nbsp;`Trend.__init__` | 1621 |  |
| **C** | `Section` | 1654 | A block of a skin's own configuration. `$Extras`, `$DisplayOptions`. A real dictionary, deliberately. Cheetah… |

## `src/weewx_evo/units.py`

[Einheiten](Units) · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `name` | 52 |  |
| f | `system_from` | 56 | A unit system from whatever a configuration file offered. Accepts the number or the name, because both appear… |
| f | `CtoK` | 88 |  |
| f | `KtoC` | 92 |  |
| f | `CtoF` | 96 |  |
| f | `FtoC` | 100 |  |
| f | `KtoF` | 104 |  |
| f | `FtoK` | 108 |  |
| f | `FtoE` | 114 |  |
| f | `EtoF` | 118 |  |
| f | `CtoE` | 122 |  |
| f | `EtoC` | 126 |  |
| f | `mps_to_mph` | 130 |  |
| f | `kph_to_mph` | 134 |  |
| f | `mps_to_knot` | 138 |  |
| f | `kph_to_knot` | 142 |  |
| f | `mph_to_knot` | 146 |  |
| f | `dublin_to_epoch` | 155 |  |
| f | `epoch_to_dublin` | 159 |  |
| f | `obs_label` | 397 | What to call a reading on a chart, when nothing else says. A skin's own name wins wherever there is one. This… |
| f | `group_of` | 893 | Which group a reading belongs to, or None if nothing knows. `extra` is what a driver contributed. It wins ove… |
| f | `unit_of` | 911 | The unit a reading is stored in, and its group. This is the unit as it sits in the database -- what the recor… |
| f | `convert` | 924 | One value from one unit to another. None stays None: a gap in the readings is not zero degrees. An unknown co… |
| f | `convert_all` | 941 | A whole series, converted. The gaps stay gaps. |
| f | `can_convert` | 954 | Whether that conversion exists, without doing it. |
| f | `label` | 961 | What to print after the number, including its leading space. A few units have a singular and a plural ('1 day… |
| f | `formatted` | 975 | A value as a person would read it. Not used by the JSON feed -- a machine reading it wants the number -- but… |
| **C** | `Target` | 991 | What to show readings in, whatever the database holds them in. A console in Germany reporting Fahrenheit and… |
| · | &nbsp;&nbsp;`Target.__init__` | 1016 |  |
| · | &nbsp;&nbsp;`Target.format_for` | 1055 | The printf format for a unit, the skin's if it named one. |
| · | &nbsp;&nbsp;`Target.label_for` | 1061 | What to print after the number, the skin's word if it has one. |
| · | &nbsp;&nbsp;`Target.unit` | 1072 | The unit this group is shown in. |
| · | &nbsp;&nbsp;`Target.for_obs` | 1080 | The unit and group a reading should be shown in. |
| · | &nbsp;&nbsp;`Target.convert` | 1086 | A series out of the database and into what it should be shown in. Returns the values, the… |

## `src/weewx_evo/uploads/__init__.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Posted` | 60 | What one run of an upload did. |
| · | &nbsp;&nbsp;`Posted.ok` | 77 |  |
| · | &nbsp;&nbsp;`Posted.summary` | 80 |  |
| **C** | `UploadError` | 92 | Something that stopped an upload before it posted anything. Configuration that cannot work, a host that does… |
| **C** | `Rejected` | 102 | The service answered, and said no. Worth its own type because the answer decides what to do next. A 401 is pe… |
| · | &nbsp;&nbsp;`Rejected.__init__` | 110 |  |
| **C** | `Upload` | 116 | Readings out. |
| · | &nbsp;&nbsp;`Upload.post` | 119 | Send `records`, oldest first. Raising means nothing was sent and why. Individual records… |
| **C** | `BaseUpload` | 128 | Defaults for an upload. Only `post` has to be written. |
| · | &nbsp;&nbsp;`BaseUpload.post` | 149 |  |
| · | &nbsp;&nbsp;`BaseUpload.check` | 152 | Try the service and say what happened, without posting readings. The admin page offers th… |
| · | &nbsp;&nbsp;`BaseUpload.status` | 162 |  |
| · | &nbsp;&nbsp;`BaseUpload.close` | 165 | Release anything held. Optional. |
| **C** | `Readings` | 173 | One archive record, readable in any unit. Every one of these services specifies its units and none of them ag… |
| · | &nbsp;&nbsp;`Readings.__init__` | 189 |  |
| · | &nbsp;&nbsp;`Readings.ts` | 194 |  |
| · | &nbsp;&nbsp;`Readings.get` | 200 | A reading, converted. None when the station does not report it. None rather than a zero,… |
| · | &nbsp;&nbsp;`Readings.text` | 222 | A reading as the string that goes in a query, or None. `spec` is a format spec, not a num… |
| f | `request` | 241 | One HTTP request. Returns the status and the body. Text by default, because everything in this package speaks… |
| f | `query` | 283 | A path with a query string, leaving out anything that is None. Leaving out is the point. Every one of these s… |
| **C** | `Registry` | 298 | The uploads this installation has. The same shape as the export and driver registries, and for the same reaso… |
| · | &nbsp;&nbsp;`Registry.__init__` | 306 |  |
| · | &nbsp;&nbsp;`Registry.register` | 311 |  |
| · | &nbsp;&nbsp;`Registry.register_factory` | 316 |  |
| · | &nbsp;&nbsp;`Registry.factory_for` | 319 |  |
| · | &nbsp;&nbsp;`Registry.get` | 323 |  |
| · | &nbsp;&nbsp;`Registry.known` | 327 |  |
| · | &nbsp;&nbsp;`Registry.names` | 331 |  |
| · | &nbsp;&nbsp;`Registry.kinds` | 335 |  |
| · | &nbsp;&nbsp;`Registry.describe` | 339 |  |
| · | &nbsp;&nbsp;`Registry.load` | 343 | Pull in what is installed. A broken one is reported, never fatal. |
| f | `get` | 380 |  |
| f | `names` | 384 |  |
| f | `kinds` | 388 |  |
| f | `describe` | 392 |  |
| f | `when_options` | 396 | The "when it runs" group, which every upload has the same. One copy, because four services with four subtly d… |

## `src/weewx_evo/uploads/ambient.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `AmbientUpload` | 103 | Posts records using the Ambient protocol. |
| · | &nbsp;&nbsp;`AmbientUpload.__init__` | 118 |  |
| · | &nbsp;&nbsp;`AmbientUpload.post` | 171 |  |
| · | &nbsp;&nbsp;`AmbientUpload.check` | 191 | Post nothing and see whether the credentials are accepted. These services have no endpoin… |
| · | &nbsp;&nbsp;`AmbientUpload.status` | 207 |  |
| **C** | `WundergroundUpload` | 240 | Weather Underground. |
| · | &nbsp;&nbsp;`WundergroundUpload.options` | 250 |  |
| **C** | `PwsWeatherUpload` | 259 | PWSweather, from AerisWeather. |
| · | &nbsp;&nbsp;`PwsWeatherUpload.options` | 269 |  |
| **C** | `WowUpload` | 276 | The Met Office's Weather Observations Website. The same protocol with both credentials renamed and a bad logi… |
| · | &nbsp;&nbsp;`WowUpload.options` | 308 |  |

## `src/weewx_evo/uploads/cwop.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `latlon` | 57 | Decimal degrees as APRS writes them: `4823.15N`, `01142.30E`. Degrees and decimal minutes, zero-padded to two… |
| **C** | `CwopUpload` | 71 | Posts records to APRS-IS for CWOP. |
| · | &nbsp;&nbsp;`CwopUpload.__init__` | 80 |  |
| · | &nbsp;&nbsp;`CwopUpload.login` | 121 |  |
| · | &nbsp;&nbsp;`CwopUpload.packet` | 124 | The TNC2 packet. Fixed width throughout -- see the module docstring. Everything is US cus… |
| · | &nbsp;&nbsp;`CwopUpload.post` | 206 |  |
| · | &nbsp;&nbsp;`CwopUpload.check` | 219 | Connect and log in, without sending a packet. APRS-IS has no way to validate a reading, s… |
| · | &nbsp;&nbsp;`CwopUpload.status` | 236 |  |
| · | &nbsp;&nbsp;`CwopUpload.options` | 241 |  |

## `src/weewx_evo/uploads/homeassistant.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `readable` | 115 | `outTemp` as `Out temp`, which is what a person sees in a list. |
| f | `device_class` | 123 |  |
| f | `discovery` | 130 | One sensor definition, as (topic, payload). `field` is the name inside the JSON document -- `outTemp_C` -- wh… |

## `src/weewx_evo/uploads/mqtt.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| f | `topic_name` | 73 | What a reading is called on the broker. |
| **C** | `MqttUpload` | 81 | Publishes records to an MQTT broker. |
| · | &nbsp;&nbsp;`MqttUpload.__init__` | 92 |  |
| · | &nbsp;&nbsp;`MqttUpload.message` | 138 | A record as the names and values that go on the broker. Conversion happens here rather th… |
| · | &nbsp;&nbsp;`MqttUpload.post` | 209 |  |
| · | &nbsp;&nbsp;`MqttUpload.publish_packet` | 223 | One live packet, for the live path rather than the archive one. Separate from `post` beca… |
| · | &nbsp;&nbsp;`MqttUpload.check` | 235 |  |
| · | &nbsp;&nbsp;`MqttUpload.status` | 253 |  |
| · | &nbsp;&nbsp;`MqttUpload.close` | 257 |  |
| · | &nbsp;&nbsp;`MqttUpload.options` | 263 |  |

## `src/weewx_evo/uploads/progress.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Progress` | 30 | The last record each upload got accepted, by upload name. |
| · | &nbsp;&nbsp;`Progress.__init__` | 33 |  |
| · | &nbsp;&nbsp;`Progress.through` | 50 | The newest record this upload has sent, or 0 for never. |
| · | &nbsp;&nbsp;`Progress.sent` | 55 | Note that everything up to `ts` has been accepted. Never moves backwards. A service that… |
| · | &nbsp;&nbsp;`Progress.forget` | 68 | Start this upload again from nothing. |
| · | &nbsp;&nbsp;`Progress.save` | 73 |  |

## `src/weewx_evo/uploads/records.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Archive` | 39 | Read-only access to the archive, one connection per thread. |
| · | &nbsp;&nbsp;`Archive.__init__` | 42 |  |
| · | &nbsp;&nbsp;`Archive.close` | 58 |  |
| · | &nbsp;&nbsp;`Archive.after` | 64 | Up to `limit` records newer than `ts`, oldest first. `ts` of 0 means "the newest one", no… |
| · | &nbsp;&nbsp;`Archive.augment` | 85 | Add the rain totals these services ask for. Leaves the record alone if the database has n… |
| f | `source` | 147 | A `records(after, limit)` callable over an archive file. What the runner wants, without the runner knowing th… |
| **C** | `Live` | 156 | Read-only access to the live packets, one connection per thread. Why this exists beside `Archive`: an archive… |
| · | &nbsp;&nbsp;`Live.__init__` | 172 |  |
| · | &nbsp;&nbsp;`Live.after` | 188 | The newest packets after `ts`, oldest first. `limit` is honoured but a live publisher wan… |
| · | &nbsp;&nbsp;`Live.close` | 218 |  |
| f | `live_source` | 227 | A `records(after, limit)` callable over the live table. |

## `src/weewx_evo/uploads/runner.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Scheduled` | 54 | One upload, and when it is next due. |
| · | &nbsp;&nbsp;`Scheduled.__init__` | 73 |  |
| · | &nbsp;&nbsp;`Scheduled.trigger` | 105 |  |
| · | &nbsp;&nbsp;`Scheduled.every` | 109 |  |
| · | &nbsp;&nbsp;`Scheduled.is_live` | 113 |  |
| · | &nbsp;&nbsp;`Scheduled.due` | 116 |  |
| · | &nbsp;&nbsp;`Scheduled.pending` | 123 | The records this upload still owes, oldest first. Empty when it is up to date, which is t… |
| · | &nbsp;&nbsp;`Scheduled.run` | 152 | Send whatever is owed, and remember what happened. Never raises. |
| **C** | `Runner` | 199 | Keeps the uploads going, one thread each. |
| · | &nbsp;&nbsp;`Runner.__init__` | 202 |  |
| · | &nbsp;&nbsp;`Runner.start` | 208 |  |
| · | &nbsp;&nbsp;`Runner.replace` | 225 | Swap in a new set, after the configuration changed. A method rather than three assignment… |
| · | &nbsp;&nbsp;`Runner.record_written` | 239 | A new archive record landed. Called from the archiver's thread and returns at once: it se… |
| · | &nbsp;&nbsp;`Runner.stop` | 256 |  |
| · | &nbsp;&nbsp;`Runner.status` | 310 |  |
| f | `build` | 324 | Turn configuration into things the runner can run. Anything that cannot be built is reported and left out. A… |

## `src/weewx_evo/uploads/weathercloud.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `WeathercloudUpload` | 55 | Posts records to Weathercloud. |
| · | &nbsp;&nbsp;`WeathercloudUpload.__init__` | 66 |  |
| · | &nbsp;&nbsp;`WeathercloudUpload.post` | 113 |  |
| · | &nbsp;&nbsp;`WeathercloudUpload.check` | 130 |  |
| · | &nbsp;&nbsp;`WeathercloudUpload.status` | 140 |  |
| · | &nbsp;&nbsp;`WeathercloudUpload.options` | 144 |  |

## `src/weewx_evo/uploads/windy.py`

**keine Seite** · zuletzt geändert 2026-08-27 10:33

| | Name | Zeile | |
|---|---|---|---|
| **C** | `WindyUpload` | 48 | Posts records to Windy. |
| · | &nbsp;&nbsp;`WindyUpload.__init__` | 55 |  |
| · | &nbsp;&nbsp;`WindyUpload.post` | 109 |  |
| · | &nbsp;&nbsp;`WindyUpload.check` | 120 |  |
| · | &nbsp;&nbsp;`WindyUpload.status` | 130 |  |
| · | &nbsp;&nbsp;`WindyUpload.options` | 135 |  |

## `src/weewx_evo/webserver.py`

[Web-Server](Web-Server) · zuletzt geändert 2026-08-26 23:43

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Site` | 66 | Which feeds are served, and from where. |
| · | &nbsp;&nbsp;`Site.__init__` | 69 |  |
| · | &nbsp;&nbsp;`Site.update` | 80 | Serve something else from now on. Returns whether anything moved. The handler holds this… |
| · | &nbsp;&nbsp;`Site.resolve` | 100 | The file for a request, or None if there is not one to serve. The check that matters is t… |
| f | `listing_page` | 139 | What is in a directory that has no index page of its own. Deliberately plain. This is not a page anybody desi… |
| f | `index_page` | 181 | The list of feeds, when none of them is the default. |
| **C** | `WebServer` | 382 | The local web server for the feeds. |
| · | &nbsp;&nbsp;`WebServer.__init__` | 385 |  |
| · | &nbsp;&nbsp;`WebServer.serve_forever` | 400 |  |
| · | &nbsp;&nbsp;`WebServer.start` | 403 |  |
| · | &nbsp;&nbsp;`WebServer.stop` | 408 |  |
| f | `site_from` | 428 | What this server hands out, and under which names. Mostly the local exports: an export named `site` publishin… |

## `src/weewx_evo/weewxconf.py`

[WeeWX-Kompatibilität](WeeWX-Compatibility) · zuletzt geändert 2026-08-26 23:47

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Section` | 38 | A dictionary that knows the section above it. ConfigObj sections do, and a WeeWX skin leans on it harder than… |
| · | &nbsp;&nbsp;`Section.__init__` | 55 |  |
| · | &nbsp;&nbsp;`Section.scalars` | 60 |  |
| · | &nbsp;&nbsp;`Section.sections` | 65 |  |
| f | `reparent` | 69 | Turn nested dictionaries into sections and tie the chain. Called once on the finished skin configuration, aft… |
| f | `parse` | 87 | A weewx.conf as nested dictionaries. Values stay strings, or become lists of strings where the file has comma… |
| f | `read` | 201 |  |
| **C** | `Import` | 242 | The result of reading a weewx.conf: settings, and what was left. |
| · | &nbsp;&nbsp;`Import.__init__` | 245 |  |
| · | &nbsp;&nbsp;`Import.take` | 254 |  |
| f | `convert` | 261 | weewx.conf into weewx-evo settings, with a report of what happened. |
| f | `report` | 415 | What the import did, as something a person reads before trusting it. |

---

Erzeugt von `tools/docsindex.py`. Siehe [Datei-Index](Index).

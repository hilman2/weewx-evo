# API-Index

Jede öffentliche Klasse, Funktion und Methode, ihre Datei und die
Wiki-Seite, die sie beschreibt.

**Erzeugt:** 2026-08-26 16:07 · `python tools/docsindex.py`

Private Namen (`_foo`) fehlen, `__init__` ist dabei. Wer einen Namen
sucht, benutzt die Suche des Browsers.

## `src/weewx_evo/admin.py`

[Die Einstellungsseite](Admin-Page) · zuletzt geändert 2026-08-26 15:52

| | Name | Zeile | |
|---|---|---|---|
| f | `export_kinds` | 45 | The kinds of export that can be added. Asked, not listed. |
| **C** | `Admin` | 64 | What the pages do, without the HTTP. |
| · | &nbsp;&nbsp;`Admin.__init__` | 67 |  |
| · | &nbsp;&nbsp;`Admin.schemas` | 94 |  |
| · | &nbsp;&nbsp;`Admin.refresh` | 99 | Rebuild the list of pages. After anything is added or removed. |
| · | &nbsp;&nbsp;`Admin.config` | 103 |  |
| · | &nbsp;&nbsp;`Admin.values` | 106 |  |
| · | &nbsp;&nbsp;`Admin.add_export` | 111 | Create an export. Returns an error, or empty if it worked. Only the name and the kind: ev… |
| · | &nbsp;&nbsp;`Admin.remove_export` | 142 | Delete an export from the configuration. Nothing at the far end. |
| · | &nbsp;&nbsp;`Admin.columns` | 159 | The readings the archive has a column for. Asked of the database rather than of a schema:… |
| · | &nbsp;&nbsp;`Admin.test_export` | 182 | Try one export's destination and say what happened. |
| · | &nbsp;&nbsp;`Admin.save` | 198 | Check a form and write it. Returns what was wrong, empty if nothing. Everything is valida… |
| f | `field` | 253 | One setting as a form field. |
| f | `group_html` | 349 |  |
| f | `new_export_page` | 373 | The form that creates one. Two fields, and nothing else yet. |
| f | `page` | 410 |  |
| **C** | `AdminServer` | 1012 | The admin page, on its own port. |
| · | &nbsp;&nbsp;`AdminServer.__init__` | 1015 |  |
| · | &nbsp;&nbsp;`AdminServer.serve_forever` | 1023 |  |
| · | &nbsp;&nbsp;`AdminServer.start` | 1026 |  |
| · | &nbsp;&nbsp;`AdminServer.stop` | 1031 |  |

## `src/weewx_evo/adminplots.py`

[Diagramme](Plots) · zuletzt geändert 2026-08-26 15:52

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

[Aggregation](Aggregation) · zuletzt geändert 2026-08-26 11:10

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
| · | &nbsp;&nbsp;`Vector.__init__` | 192 |  |
| · | &nbsp;&nbsp;`Vector.set_stats` | 197 |  |
| · | &nbsp;&nbsp;`Vector.stats_tuple` | 205 |  |
| · | &nbsp;&nbsp;`Vector.merge_hilo` | 211 |  |
| · | &nbsp;&nbsp;`Vector.merge_sum` | 226 |  |
| · | &nbsp;&nbsp;`Vector.add_hilo` | 237 |  |
| · | &nbsp;&nbsp;`Vector.add_sum` | 252 |  |
| · | &nbsp;&nbsp;`Vector.avg` | 270 |  |
| · | &nbsp;&nbsp;`Vector.rms` | 274 |  |
| · | &nbsp;&nbsp;`Vector.vec_avg` | 278 |  |
| · | &nbsp;&nbsp;`Vector.vec_dir` | 284 |  |
| **C** | `Accumulator` | 298 | Statistics for a set of observation types over one span of time. Feed it records with `add_record`, then read… |
| · | &nbsp;&nbsp;`Accumulator.__init__` | 308 |  |
| · | &nbsp;&nbsp;`Accumulator.includes` | 325 |  |
| · | &nbsp;&nbsp;`Accumulator.is_empty` | 329 |  |
| · | &nbsp;&nbsp;`Accumulator.add_record` | 332 | Fold one record into the statistics. Raises ValueError if the record falls outside the sp… |
| · | &nbsp;&nbsp;`Accumulator.merge_hilo` | 356 | Fold another accumulator's highs and lows into this one. |
| · | &nbsp;&nbsp;`Accumulator.record` | 368 | Extract an archive record. It is stamped at the end of the span. |
| · | &nbsp;&nbsp;`Accumulator.augment` | 372 | Fill in whatever the record does not already carry. Values already present win. That is h… |
| · | &nbsp;&nbsp;`Accumulator.set_stats` | 384 | Load statistics straight from storage, bypassing the arithmetic. With no tuple the type i… |

## `src/weewx_evo/archiver.py`

[Archiver](Archiver) · zuletzt geändert 2026-08-26 14:09

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

## `src/weewx_evo/cli.py`

[CLI-Referenz](CLI-Reference) · zuletzt geändert 2026-08-26 15:25

| | Name | Zeile | |
|---|---|---|---|
| f | `env` | 61 |  |
| f | `add_common` | 65 |  |
| f | `add_listen_args` | 101 |  |
| f | `add_archive_args` | 124 |  |
| f | `settings_for` | 143 | The process's settings, resolved once. Once, not once per caller. With each component resolving for itself, a… |
| f | `read_config` | 177 | The whole configuration file, or an empty one. A file that is not there yet is not an error: a first start ha… |
| f | `configure_drivers` | 188 | Hand each driver its options, and somewhere to keep its own state. Until this runs the drivers are unconfigur… |
| f | `read_sources` | 243 | Which station wins for which field. Normally a [sources] section in the configuration file, beside everything… |
| f | `open_stores` | 272 |  |
| f | `make_archiver` | 280 |  |
| f | `cmd_listen` | 290 |  |
| f | `cmd_archive` | 334 |  |
| f | `cmd_serve` | 393 | Listener and archiver in one process, for a small machine. They still speak only through the database. Splitt… |
| f | `cmd_catchup` | 557 |  |
| f | `cmd_rebuild` | 568 |  |
| f | `cmd_columns` | 579 | Readings that the archive has no column for. A reading only survives the archive interval if the table has a… |
| f | `cmd_driver_list` | 654 |  |
| f | `cmd_driver_install` | 676 |  |
| f | `cmd_driver_remove` | 710 |  |
| f | `local_addresses` | 719 | Addresses this machine can be reached on, as (address, what it is). Only what can be worked out without askin… |
| f | `cmd_url` | 751 | Print the addresses of the live view and the upload endpoint. The token is a path segment, so an address with… |
| f | `driver_directory` | 819 | Where third-party drivers live, resolved like everything else. The command line first, then the setting, then… |
| f | `all_schemas` | 838 | Every configurable thing there is: the core, then each driver. Drivers are asked, not enumerated. One that ga… |
| f | `replace_group` | 901 |  |
| f | `cmd_config_show` | 907 | Print the configuration as it stands, commented. |
| f | `cmd_config_set` | 920 | Set one value, checked against the schema that owns it. |
| f | `cmd_config_check` | 951 | Check every value against its schema and say what is wrong. |
| f | `cmd_config_import` | 969 | Read a weewx.conf and write what it says into our own file. |
| f | `cmd_admin` | 1000 | Serve the settings page. Its own port and its own token, deliberately. An upload endpoint can at worst put a… |
| f | `configured_exports` | 1075 | What the configuration file says about exports, by name. |
| f | `build_export` | 1083 | Make one export from its settings. Raises with a usable message. |
| f | `cmd_export_list` | 1103 |  |
| f | `cmd_export_check` | 1135 | Try each destination without sending anything. |
| f | `cmd_export_run` | 1163 | Send. This is what a feed would call when it has produced something. |
| f | `cmd_web` | 1215 | Serve the feeds, and nothing else. Separate from `serve` for the same reason `listen` is: a machine that only… |
| f | `plots_path` | 1258 | Where plots.toml lives: beside the configuration unless told otherwise. |
| f | `load_plots` | 1272 |  |
| f | `build_feeds` | 1276 | The feeds this configuration asks for, in the order they run. The JSON first, because the diagnostic page dra… |
| f | `cmd_plots_list` | 1298 | What charts exist. |
| f | `cmd_plots_show` | 1325 | One chart, in full. |
| f | `cmd_plots_import` | 1361 | Take the plots out of a WeeWX skin.conf or weewx.conf. Read, reported, and only written when asked. An import… |
| f | `cmd_plots_remove` | 1421 | Delete a chart. |
| f | `cmd_plots_run` | 1434 | Produce the JSON now, and say what came out. |
| f | `cmd_status` | 1482 |  |
| f | `main` | 1516 |  |

## `src/weewx_evo/config.py`

[Konfiguration](Configuration) · zuletzt geändert 2026-08-26 12:43

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

[Die Archiv-Datenbank](Database-Archive) · zuletzt geändert 2026-08-26 11:48

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

[Tagesstatistiken](Daily-Summaries) · zuletzt geändert 2026-08-26 10:58

| | Name | Zeile | |
|---|---|---|---|
| **C** | `IntervalError` | 23 | A record whose `interval` cannot be turned into a weight. |
| f | `weight_of` | 27 | The weight one archive record carries in a daily summary. WeeWX uses this for daily-summary version 2.0 and u… |
| f | `day_accumulator` | 41 | An accumulator spanning one archive day, starting at `sod_ts`. |
| f | `build` | 47 | Fold archive records into one accumulator per day. Records must arrive in ascending time order -- the same or… |
| f | `read_day` | 82 | Read one day's stored statistics for one observation type. |
| f | `read_records` | 94 | Read archive records in time order, dropping the columns that are NULL. Dropping nulls matters: the accumulat… |

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

[Abgeleitete Messwerte](Derived-Readings) · zuletzt geändert 2026-08-26 14:18

| | Name | Zeile | |
|---|---|---|---|
| f | `dewpoint_c` | 108 | Dew point in Celsius, by the Magnus formula WeeWX uses. |
| f | `windchill_c` | 125 | Wind chill, Celsius, from the Environment Canada formula. Only defined below 10 degrees and above 4.8 km/h. O… |
| f | `heatindex_f` | 139 | Heat index, Fahrenheit, Rothfusz with the two adjustments. Below 40 F there is no heat index and the temperat… |
| f | `humidex_c` | 165 | Humidex, Celsius. Below 21 degrees it is the temperature. |
| f | `apptemp_c` | 178 | Apparent temperature, the Australian BOM formula. |
| f | `altimeter_inhg` | 187 | Altimeter setting from station pressure, the aaASOS algorithm. |
| f | `cloudbase_ft` | 195 | Height of the cloud base, feet, from the spread. |
| f | `sun_position` | 211 | The sun's elevation in degrees, and Earth's distance in AU. pyephem when it is installed, and NOAA's algorith… |
| f | `max_solar_rad` | 293 | Clear-sky radiation, W/m2, Ryan-Stolzenbach (MIT, 1972). What a solar sensor would read with no cloud above i… |
| f | `windrun` | 327 | Distance the wind covered, in the same length unit as the speed. Speed times time. The unit follows the speed… |
| f | `delta` | 338 | How much a running total went up by. Three cases that are not errors and must not be treated as one: * No pre… |
| **C** | `Station` | 369 | What the formulas need to know about where the station is. |
| · | &nbsp;&nbsp;`Station.altitude_ft` | 377 |  |
| **C** | `Deriver` | 384 | Fills in the readings that follow from other readings. Holds one piece of state: the last value of each runni… |
| · | &nbsp;&nbsp;`Deriver.wanted` | 398 | Whether to work this one out for this record. |
| · | &nbsp;&nbsp;`Deriver.apply` | 408 | Add what is missing. The record is modified and returned. Order matters: dew point before… |
| · | &nbsp;&nbsp;`Deriver.forget` | 516 | Drop the running totals. The next packet takes no delta. |
| f | `from_settings` | 562 | Build one from the resolved configuration. |

## `src/weewx_evo/exports/__init__.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 15:58

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
| f | `source_for` | 245 | Where an export's files are, from a feed name or a plain directory. A feed is asked where it wrote; a directo… |
| f | `walk` | 266 | Every file to consider, as paths relative to `source`. Directories that should never be uploaded are skipped… |

## `src/weewx_evo/exports/ftp.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 14:00

| | Name | Zeile | |
|---|---|---|---|
| **C** | `FtpExport` | 45 | Sends a directory to an FTP server. |
| · | &nbsp;&nbsp;`FtpExport.__init__` | 50 |  |
| · | &nbsp;&nbsp;`FtpExport.send` | 80 |  |
| · | &nbsp;&nbsp;`FtpExport.check` | 124 | Connect, look at the target directory, and say what happened. |
| · | &nbsp;&nbsp;`FtpExport.status` | 147 |  |
| · | &nbsp;&nbsp;`FtpExport.options` | 256 |  |

## `src/weewx_evo/exports/local.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 15:58

| | Name | Zeile | |
|---|---|---|---|
| **C** | `LocalExport` | 44 | Copies what a feed produced into a directory on this machine. |
| · | &nbsp;&nbsp;`LocalExport.__init__` | 49 |  |
| · | &nbsp;&nbsp;`LocalExport.send` | 83 |  |
| · | &nbsp;&nbsp;`LocalExport.check` | 188 | Whether this can be written to, and what is there now. |
| · | &nbsp;&nbsp;`LocalExport.status` | 212 |  |
| · | &nbsp;&nbsp;`LocalExport.options` | 224 |  |

## `src/weewx_evo/exports/rsync.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 14:00

| | Name | Zeile | |
|---|---|---|---|
| **C** | `RsyncExport` | 44 | Sends a directory to a server with rsync over SSH. |
| · | &nbsp;&nbsp;`RsyncExport.__init__` | 49 |  |
| · | &nbsp;&nbsp;`RsyncExport.send` | 77 |  |
| · | &nbsp;&nbsp;`RsyncExport.check` | 115 | Do a dry run and report what would happen. |
| · | &nbsp;&nbsp;`RsyncExport.status` | 147 |  |
| · | &nbsp;&nbsp;`RsyncExport.options` | 217 |  |

## `src/weewx_evo/exports/runner.py`

[Exports](Exports) · zuletzt geändert 2026-08-26 14:00

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Scheduled` | 45 | One export, and when it is next due. |
| · | &nbsp;&nbsp;`Scheduled.__init__` | 51 |  |
| · | &nbsp;&nbsp;`Scheduled.trigger` | 72 |  |
| · | &nbsp;&nbsp;`Scheduled.every` | 76 |  |
| · | &nbsp;&nbsp;`Scheduled.due` | 79 | `fired` is what just happened: "record", a feed name, or "". |
| · | &nbsp;&nbsp;`Scheduled.run` | 89 | Send, and remember what happened. Never raises. |
| **C** | `Runner` | 115 | Keeps the exports going, one thread each. |
| · | &nbsp;&nbsp;`Runner.__init__` | 118 |  |
| · | &nbsp;&nbsp;`Runner.start` | 126 |  |
| · | &nbsp;&nbsp;`Runner.record_written` | 143 | A new archive record landed. Called from the archiver's thread and returns at once: it se… |
| · | &nbsp;&nbsp;`Runner.feed_produced` | 154 | A feed has finished writing. Wake whatever sends it. This is the trigger to prefer where… |
| · | &nbsp;&nbsp;`Runner.stop` | 168 |  |
| · | &nbsp;&nbsp;`Runner.status` | 213 |  |
| f | `build` | 227 | Turn configuration into things the runner can run. Anything that cannot be built is reported and left out. A… |

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

[Feeds](Feeds) · zuletzt geändert 2026-08-26 15:25

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Runner` | 36 | Produces every feed, in order, whenever a record lands. |
| · | &nbsp;&nbsp;`Runner.__init__` | 39 |  |
| · | &nbsp;&nbsp;`Runner.record_written` | 53 | Called by the archiver. Sets a flag and returns. |
| · | &nbsp;&nbsp;`Runner.start` | 57 |  |
| · | &nbsp;&nbsp;`Runner.stop` | 62 |  |
| · | &nbsp;&nbsp;`Runner.run_once` | 82 | Every feed, in order. Returns what happened, for a status page. |
| · | &nbsp;&nbsp;`Runner.status` | 125 |  |

## `src/weewx_evo/feeds/__init__.py`

[Feeds](Feeds) · zuletzt geändert 2026-08-26 15:55

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Produced` | 72 | What one run of a feed made. The list of files matters to the exports: an export that knows which files chang… |
| · | &nbsp;&nbsp;`Produced.count` | 87 |  |
| f | `names` | 91 | The feeds that exist. A function rather than a list, so that an export's dropdown fills itself the moment a f… |
| f | `describe` | 102 | One line about a feed, for a form that offers it. |
| f | `load` | 127 | Pull in the feeds. A broken one is reported, never fatal. Same arrangement as the drivers: one feed that will… |
| f | `register` | 159 |  |
| f | `get` | 165 |  |
| **C** | `Feed` | 171 | Readings out, as files. |
| · | &nbsp;&nbsp;`Feed.produce` | 177 | Write this feed's files into `into` and say which they are. `archive` is a read-only view… |

## `src/weewx_evo/feeds/diagnostic/__init__.py`

[Feeds](Feeds) · zuletzt geändert 2026-08-26 15:17

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Diagnostic` | 50 | Renders every series file it finds, with its faults listed. |
| · | &nbsp;&nbsp;`Diagnostic.__init__` | 55 |  |
| · | &nbsp;&nbsp;`Diagnostic.produce` | 65 |  |
| · | &nbsp;&nbsp;`Diagnostic.read` | 82 | Every JSON file in the source directory, examined. |
| · | &nbsp;&nbsp;`Diagnostic.render` | 195 |  |
| · | &nbsp;&nbsp;`Diagnostic.options` | 293 |  |
| f | `from_settings` | 346 |  |

## `src/weewx_evo/feeds/jsongenerator/__init__.py`

[Feeds](Feeds) · zuletzt geändert 2026-08-26 16:00

| | Name | Zeile | |
|---|---|---|---|
| **C** | `JSONGenerator` | 91 | Turns plot definitions into JSON files. |
| · | &nbsp;&nbsp;`JSONGenerator.__init__` | 98 |  |
| · | &nbsp;&nbsp;`JSONGenerator.produce` | 137 | Write every plot, and the manifest. Returns what was made. |
| · | &nbsp;&nbsp;`JSONGenerator.build` | 250 | One plot's payload, or None if there is nothing in it. Every line is fetched, converted,… |
| · | &nbsp;&nbsp;`JSONGenerator.options` | 415 | The settings this feed offers, for the admin page and the file. |
| f | `from_settings` | 640 | Build the generator from the configuration. |

## `src/weewx_evo/ingest/drivers.py`

[Treiber](Drivers) · zuletzt geändert 2026-08-26 15:43

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

[Listener](Ingest-Listener) · zuletzt geändert 2026-08-26 13:10

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Ingest` | 45 | What the listener does with an upload once it has one. Kept separate from the transports so the same object s… |
| · | &nbsp;&nbsp;`Ingest.__init__` | 52 |  |
| · | &nbsp;&nbsp;`Ingest.authorised` | 76 | Whether a request path carries the token. The token is a path segment rather than a heade… |
| · | &nbsp;&nbsp;`Ingest.driver_for` | 88 | Pick a driver from the path, e.g. /<token>/json/ or /<token>/ecowitt/. |
| · | &nbsp;&nbsp;`Ingest.submit` | 95 | Take one upload. Returns (packets stored, reason, what to answer with). The response come… |
| · | &nbsp;&nbsp;`Ingest.status` | 182 |  |
| **C** | `HttpListener` | 342 | The HTTP half. Threaded, because a slow console must not block the others. |
| · | &nbsp;&nbsp;`HttpListener.__init__` | 345 |  |
| · | &nbsp;&nbsp;`HttpListener.serve_forever` | 351 |  |
| · | &nbsp;&nbsp;`HttpListener.start` | 355 |  |
| · | &nbsp;&nbsp;`HttpListener.stop` | 360 |  |
| **C** | `UdpListener` | 383 | The UDP half, for hardware that broadcasts rather than posts. |
| · | &nbsp;&nbsp;`UdpListener.__init__` | 386 |  |
| · | &nbsp;&nbsp;`UdpListener.serve_forever` | 394 |  |
| · | &nbsp;&nbsp;`UdpListener.start` | 398 |  |
| · | &nbsp;&nbsp;`UdpListener.stop` | 403 |  |
| f | `push` | 408 | Send packets to a listener. This is how a pull driver delivers. Going over the loopback rather than writing t… |
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

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 11:48

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

[Treiber: Ecowitt](Driver-Ecowitt) · zuletzt geändert 2026-08-26 11:48

| | Name | Zeile | |
|---|---|---|---|
| f | `parse` | 35 | Split a payload into raw name/value pairs. Works for both protocols, because a urlencoded body and a query st… |
| f | `device_time` | 61 | Return the timestamp the device sent, or None if it is not usable. Consoles are frequently wrong about the ti… |
| f | `numbers` | 109 | Split raw values into the numeric ones and the rest. Returns (readings, text), where readings holds everythin… |
| f | `redact` | 138 | Replace the values that identify a station, leaving the readings alone. A payload is going to be pasted into… |
| f | `station_id` | 150 | What identifies the console that sent this. The PASSKEY for the Ecowitt protocol, the station ID for Weather… |

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

[Listener](Ingest-Listener) · zuletzt geändert 2026-08-26 12:27

| | Name | Zeile | |
|---|---|---|---|
| f | `short_source` | 46 |  |
| f | `recent` | 52 | What the page needs: the last few packets, and how things are going. |
| f | `render` | 100 | The page itself. One file, no dependencies. |

## `src/weewx_evo/ingest/userdrivers.py`

[Treiber](Drivers) · zuletzt geändert 2026-08-26 12:00

| | Name | Zeile | |
|---|---|---|---|
| f | `directory` | 46 | Where user drivers live. |
| f | `installed` | 59 | The drivers installed, as (name, where it came from). |
| f | `load` | 75 | Register every installed user driver. Returns the names that loaded. |
| **C** | `InstallError` | 115 | Anything that stopped a driver being installed. |
| f | `install` | 119 | Install a driver from a git URL, a zip, or a directory. Returns its name and what its code reaches for -- see… |
| f | `remove` | 161 | Delete an installed driver. Returns False if it was not there. |
| f | `inspect_source` | 274 | What a driver's code reaches for, as {note: [files]}. Read, not run. This is a hint and not a guarantee: it w… |

## `src/weewx_evo/netaccess.py`

[Sicherheit](Security) · zuletzt geändert 2026-08-26 12:57

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

[Konfiguration](Configuration) · zuletzt geändert 2026-08-26 15:59

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Invalid` | 51 | A value that a setting cannot take, with a reason a person can act on. |
| **C** | `Option` | 56 | One setting. |
| · | &nbsp;&nbsp;`Option.options` | 95 | The choices, asking the installation if that is where they are. A failure here is not fat… |
| · | &nbsp;&nbsp;`Option.parse` | 110 | Turn what arrived into the value this setting holds. Raises Invalid with a message meant… |
| · | &nbsp;&nbsp;`Option.render` | 177 | The value as the form should show it. Secrets never come back. |
| f | `parse_duration` | 188 | Seconds from '90', '5m', '2h', '7d'. A bare number is seconds. |
| f | `format_duration` | 197 | The other way, choosing the largest unit that stays whole. |
| f | `split_duration` | 212 | Seconds as (amount, unit), in the largest unit that stays whole. 604800 becomes (7, "d"), not (604800, "s").… |
| **C** | `Group` | 228 | Settings that belong together, and become one section of the form. |
| **C** | `Schema` | 240 | Everything one component can be configured with. |
| · | &nbsp;&nbsp;`Schema.option` | 255 |  |
| · | &nbsp;&nbsp;`Schema.defaults` | 261 |  |
| · | &nbsp;&nbsp;`Schema.parse` | 265 | Check a whole form's worth at once. Returns the parsed settings and, separately, what was… |
| f | `schema_of` | 308 | Ask a component to describe itself, if it can. |
| f | `installed_drivers` | 329 | The drivers this installation actually has. Asked at render time, not listed here: installing a driver should… |
| f | `published_names` | 341 | What the built-in web server has to hand out. The local exports, by name: an export is where somebody said a… |
| f | `defined_feeds` | 376 | The feeds that exist, for an export to point at. An export can only send what something produced, so the list… |
| f | `core_options` | 389 | What weewx-evo itself is configured with. |

## `src/weewx_evo/plots.py`

[Diagramme](Plots) · zuletzt geändert 2026-08-26 15:45

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Line` | 93 | One reading drawn in one plot. |
| · | &nbsp;&nbsp;`Line.resolved` | 121 | The same line with the colors WeeWX would have given it. |
| **C** | `Plot` | 134 | One chart. |
| · | &nbsp;&nbsp;`Plot.drawn` | 165 | The lines with their colors filled in. |
| · | &nbsp;&nbsp;`Plot.uses` | 169 | Which readings this plot needs. |
| **C** | `PlotSet` | 174 | The plots there are, and what the readings in them are called. |
| · | &nbsp;&nbsp;`PlotSet.__init__` | 177 |  |
| · | &nbsp;&nbsp;`PlotSet.get` | 190 |  |
| · | &nbsp;&nbsp;`PlotSet.add` | 196 |  |
| · | &nbsp;&nbsp;`PlotSet.remove` | 201 |  |
| · | &nbsp;&nbsp;`PlotSet.by_span` | 206 | Grouped, in the order the spans were first seen. |
| · | &nbsp;&nbsp;`PlotSet.spans` | 213 | How long each span covers, for the manifest. A client laying out its own periods needs th… |
| · | &nbsp;&nbsp;`PlotSet.uses` | 224 |  |
| f | `load` | 230 | Read plots.toml. A file that is not there means no plots, not an error. |
| f | `from_dict` | 242 | Plots out of already-parsed TOML. |
| f | `save` | 294 | Write plots.toml, keeping the previous one. Written beside and moved into place, like the configuration: this… |
| f | `render` | 318 | The plots as a TOML file somebody can edit. |
| **C** | `Imported` | 389 | What an import found, and what it did not take. |
| · | &nbsp;&nbsp;`Imported.report` | 400 | What happened, as something to read before trusting it. |
| f | `labels_from` | 425 | What a WeeWX skin calls each reading: `[Labels] [[Generic]]`. Worth carrying across on its own. Somebody who… |
| f | `from_image_generator` | 441 | Plots out of a WeeWX `[ImageGenerator]` section. The structure there is three deep: a group of plots (`[[day_… |

## `src/weewx_evo/ratelimit.py`

[Sicherheit](Security) · zuletzt geändert 2026-08-26 13:09

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

[Zeitreihen](Series) · zuletzt geändert 2026-08-26 16:06

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Series` | 87 | One reading over one span. Two parallel arrays rather than a list of pairs: about 30% smaller once it is JSON… |
| · | &nbsp;&nbsp;`Series.empty` | 114 | Whether there is anything to draw. An all-null series is not. |
| · | &nbsp;&nbsp;`Series.rounded` | 118 | Round the values in place and return self. Three decimals is well past any weather sensor… |
| **C** | `Reader` | 135 | Reads series from one archive database. Holds a connection and nothing else -- no cache, and so nothing that… |
| · | &nbsp;&nbsp;`Reader.__init__` | 142 |  |
| · | &nbsp;&nbsp;`Reader.columns` | 152 | The readings the archive table has a column for. |
| · | &nbsp;&nbsp;`Reader.has_daily` | 160 | Whether there is a daily summary table for this reading. |
| · | &nbsp;&nbsp;`Reader.span` | 172 | The first and last record in the archive, or None if it is empty. |
| · | &nbsp;&nbsp;`Reader.series` | 183 | A reading over a span. With no aggregate, the archive records themselves. With one, the s… |
| · | &nbsp;&nbsp;`Reader.aggregate` | 214 | One number for one span. Answered from the daily summaries when the span is whole days an… |
| · | &nbsp;&nbsp;`Reader.vector` | 299 | One wind vector for one span, as (magnitude, bearing). `avg` and `sum` add the readings a… |
| · | &nbsp;&nbsp;`Reader.buckets` | 602 | The buckets a span is cut into, as (begin, end) pairs. Days, months and years are whole c… |
| f | `is_midnight` | 696 | Whether a timestamp falls exactly on a local midnight. The daily summaries are keyed by these, so this is the… |

## `src/weewx_evo/settings.py`

[Konfiguration](Configuration) · zuletzt geändert 2026-08-26 13:17

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Settings` | 92 | One resolved view of the configuration. |
| · | &nbsp;&nbsp;`Settings.__init__` | 95 |  |
| · | &nbsp;&nbsp;`Settings.get` | 108 | The value of one setting, and remember where it came from. |
| · | &nbsp;&nbsp;`Settings.source` | 181 | Where the last-read value of this setting came from. |
| · | &nbsp;&nbsp;`Settings.all` | 185 |  |
| · | &nbsp;&nbsp;`Settings.view` | 190 | One component's corner of the settings, and nothing else. A driver gets this rather than… |
| · | &nbsp;&nbsp;`Settings.reload` | 206 | Re-read the file. Returns whether anything actually changed. This is what a settings serv… |
| · | &nbsp;&nbsp;`Settings.explain` | 231 | One line per setting, saying what it is and where it came from. |
| f | `load` | 241 | Build a Settings from the places there are. A missing configuration file is not an error: a first start has n… |

## `src/weewx_evo/sources.py`

[Mehrere Quellen](Multiple-Sources) · zuletzt geändert 2026-08-26 11:28

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

[Sonne](Sun) · zuletzt geändert 2026-08-26 15:05

| | Name | Zeile | |
|---|---|---|---|
| f | `solar` | 54 | The sun's declination, the equation of time, and Earth's distance. Declination in degrees, the equation of ti… |
| f | `position` | 108 | The sun's elevation in degrees, and Earth's distance in AU. |
| f | `solar_noon` | 140 | The moment the sun is highest, on the sun's day containing `when`. Two corrections to clock noon: how far eas… |
| f | `crossings` | 161 | When the sun passes an elevation on the way up and on the way down. Both times are around the solar noon near… |
| f | `events` | 218 | Sunrise, sunset and the civil twilight around them, for one day. Uses pyephem where it is installed: it accou… |
| f | `day_night` | 290 | What a chart needs to shade the hours of darkness. Returns which of day or night the span begins in, every cr… |
| f | `local_midnight` | 354 | The start of the local day a timestamp falls in. |
| f | `describe` | 360 | One day's sun, as a line somebody reads. For the CLI. |

## `src/weewx_evo/units.py`

[Einheiten](Units) · zuletzt geändert 2026-08-26 16:06

| | Name | Zeile | |
|---|---|---|---|
| f | `name` | 51 |  |
| f | `system_from` | 55 | A unit system from whatever a configuration file offered. Accepts the number or the name, because both appear… |
| f | `CtoK` | 87 |  |
| f | `KtoC` | 91 |  |
| f | `CtoF` | 95 |  |
| f | `FtoC` | 99 |  |
| f | `KtoF` | 103 |  |
| f | `FtoK` | 107 |  |
| f | `FtoE` | 113 |  |
| f | `EtoF` | 117 |  |
| f | `CtoE` | 121 |  |
| f | `EtoC` | 125 |  |
| f | `mps_to_mph` | 129 |  |
| f | `kph_to_mph` | 133 |  |
| f | `mps_to_knot` | 137 |  |
| f | `kph_to_knot` | 141 |  |
| f | `mph_to_knot` | 145 |  |
| f | `dublin_to_epoch` | 154 |  |
| f | `epoch_to_dublin` | 158 |  |
| f | `group_of` | 746 | Which group a reading belongs to, or None if nothing knows. `extra` is what a driver contributed. It wins ove… |
| f | `unit_of` | 764 | The unit a reading is stored in, and its group. This is the unit as it sits in the database -- what the recor… |
| f | `convert` | 777 | One value from one unit to another. None stays None: a gap in the readings is not zero degrees. An unknown co… |
| f | `convert_all` | 794 | A whole series, converted. The gaps stay gaps. |
| f | `can_convert` | 807 | Whether that conversion exists, without doing it. |
| f | `label` | 814 | What to print after the number, including its leading space. A few units have a singular and a plural ('1 day… |
| f | `formatted` | 828 | A value as a person would read it. Not used by the JSON feed -- a machine reading it wants the number -- but… |
| **C** | `Target` | 844 | What to show readings in, whatever the database holds them in. A console in Germany reporting Fahrenheit and… |
| · | &nbsp;&nbsp;`Target.__init__` | 860 |  |
| · | &nbsp;&nbsp;`Target.unit` | 872 | The unit this group is shown in. |
| · | &nbsp;&nbsp;`Target.for_obs` | 880 | The unit and group a reading should be shown in. |
| · | &nbsp;&nbsp;`Target.convert` | 886 | A series out of the database and into what it should be shown in. Returns the values, the… |

## `src/weewx_evo/webserver.py`

[Web-Server](Web-Server) · zuletzt geändert 2026-08-26 15:59

| | Name | Zeile | |
|---|---|---|---|
| **C** | `Site` | 58 | Which feeds are served, and from where. |
| · | &nbsp;&nbsp;`Site.__init__` | 61 |  |
| · | &nbsp;&nbsp;`Site.resolve` | 72 | The file for a request, or None if there is not one to serve. The check that matters is t… |
| f | `index_page` | 109 | The list of feeds, when none of them is the default. |
| **C** | `WebServer` | 288 | The local web server for the feeds. |
| · | &nbsp;&nbsp;`WebServer.__init__` | 291 |  |
| · | &nbsp;&nbsp;`WebServer.serve_forever` | 306 |  |
| · | &nbsp;&nbsp;`WebServer.start` | 309 |  |
| · | &nbsp;&nbsp;`WebServer.stop` | 314 |  |
| f | `site_from` | 319 | What this server hands out, and under which names. Mostly the local exports: an export named `site` publishin… |

## `src/weewx_evo/weewxconf.py`

[WeeWX-Kompatibilität](WeeWX-Compatibility) · zuletzt geändert 2026-08-26 14:52

| | Name | Zeile | |
|---|---|---|---|
| f | `parse` | 38 | A weewx.conf as nested dictionaries. Values stay strings, or become lists of strings where the file has comma… |
| f | `read` | 135 |  |
| **C** | `Import` | 176 | The result of reading a weewx.conf: settings, and what was left. |
| · | &nbsp;&nbsp;`Import.__init__` | 179 |  |
| · | &nbsp;&nbsp;`Import.take` | 188 |  |
| f | `convert` | 195 | weewx.conf into weewx-evo settings, with a report of what happened. |
| f | `report` | 349 | What the import did, as something a person reads before trusting it. |

---

Erzeugt von `tools/docsindex.py`. Siehe [Datei-Index](Index).

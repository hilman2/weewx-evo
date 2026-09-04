# API-Index

Every public class, function and method, its file, and the wiki page
that describes it.

**Generated:** 2026-09-04 14:52 · `python tools/docsindex.py`

Private names (`_foo`) are left out, `__init__` is included. To find a
name, use the browser's search.

## `src/weewx_evo/addons.py`

[Drivers](Drivers) · last changed 2026-09-04 14:35

| | Name | Line | |
|---|---|---|---|
| **C** | `Installed` | 63 | One add-on that is on this machine. |
| · | &nbsp;&nbsp;`Installed.names` | 74 |  |
| f | `installed` | 78 | Every weewx-evo add-on this interpreter can see, by package name. Found through the entry points rather than… |
| f | `offered` | 130 | The catalogue, from the network or the last copy of it. |
| f | `install` | 135 | Install one add-on by name. Returns "" on success, else what went wrong. The name must be in the catalogue, a… |
| f | `remove` | 160 | Uninstall one add-on. Same rule: it has to be one we know about. What it leaves behind is deliberately not ti… |
| f | `unread_sightings` | 202 | Uploads that arrived and that no installed driver could read. One place, because two things ask: the overview… |
| f | `wanted_by_sightings` | 234 | Add-ons the catalogue says would read what has turned up unread. The other half of what the overview reports:… |

## `src/weewx_evo/admin.py`

[The settings page](Admin-Page) · last changed 2026-09-04 14:42

| | Name | Line | |
|---|---|---|---|
| f | `export_kinds` | 63 | The kinds of export that can be added. Asked, not listed. |
| f | `feed_kinds` | 70 | The kinds of feed that can be added. Asked, not listed. |
| f | `feed_kind_choices` | 77 | Each kind, and what it is for. |
| f | `export_kind_choices` | 84 | Each kind, what it is called, and what it is for. A dropdown reading `ftp / local / rsync` asks somebody to a… |
| f | `upload_kinds` | 112 | The kinds of upload that can be added. Asked, not listed. Not every kind that exists: see NOT_CHOSEN. The che… |
| f | `upload_kind_choices` | 125 | Each service, what it is called, and what it is for. The same reasoning as the exports: a dropdown reading `a… |
| f | `forecast_kinds` | 143 | The forecast sources that can be added. Asked, not listed. |
| f | `forecast_kind_choices` | 150 |  |
| **C** | `Admin` | 222 | What the pages do, without the HTTP. |
| · | &nbsp;&nbsp;`Admin.__init__` | 225 |  |
| · | &nbsp;&nbsp;`Admin.schemas` | 252 |  |
| · | &nbsp;&nbsp;`Admin.refresh` | 257 | Rebuild the list of pages. After anything is added or removed. |
| · | &nbsp;&nbsp;`Admin.config` | 261 |  |
| · | &nbsp;&nbsp;`Admin.values` | 264 |  |
| · | &nbsp;&nbsp;`Admin.language` | 270 | The language every page of this settings site is written in. Read from the file rather th… |
| · | &nbsp;&nbsp;`Admin.say` | 283 | One piece of this page, in the operator's language. On `Admin` rather than imported per m… |
| · | &nbsp;&nbsp;`Admin.write_settings` | 295 | Put several settings at once. Returns an error, or empty. For the wizard, which answers t… |
| · | &nbsp;&nbsp;`Admin.add_export_settings` | 326 | Create an export with everything it needs, in one write. `add_export` takes a name and a… |
| · | &nbsp;&nbsp;`Admin.add_export` | 359 | Create an export. Returns an error, or empty if it worked. Only the name and the kind: ev… |
| · | &nbsp;&nbsp;`Admin.add_collector` | 390 | Create a collector. Returns an error, or empty if it worked. The name is checked against… |
| · | &nbsp;&nbsp;`Admin.remove_collector` | 439 | Take a collector out of the configuration. Nothing is stopped by this: the collector is a… |
| · | &nbsp;&nbsp;`Admin.add_feed` | 462 | Create a feed. Returns an error, or empty if it worked. Only the name and the kind. Every… |
| · | &nbsp;&nbsp;`Admin.remove_feed` | 503 | Delete a feed. What it already wrote is left where it is. |
| · | &nbsp;&nbsp;`Admin.add_channel` | 520 | Create a notification channel. Returns an error, or empty. Name and kind only, like an up… |
| · | &nbsp;&nbsp;`Admin.add_upload` | 550 | Create an upload. Returns an error, or empty if it worked. Name and kind only, like an ex… |
| · | &nbsp;&nbsp;`Admin.remove_upload` | 579 | Delete an upload. Nothing is withdrawn from the service. |
| · | &nbsp;&nbsp;`Admin.test_upload` | 596 | Try one service and say what it answered. Worth more here than anywhere else on this page… |
| · | &nbsp;&nbsp;`Admin.add_forecast` | 633 | Create a forecast source. Name and kind only, like the rest. |
| · | &nbsp;&nbsp;`Admin.remove_forecast` | 658 | Delete a forecast source. What it fetched stays until it is pruned. |
| · | &nbsp;&nbsp;`Admin.test_forecast` | 675 | Fetch once and say what came back, storing nothing. This button does double duty: a MOSMI… |
| · | &nbsp;&nbsp;`Admin.remove_export` | 705 | Delete an export from the configuration. Nothing at the far end. |
| · | &nbsp;&nbsp;`Admin.columns` | 722 | The readings one place's archive has a column for. Asked of the database rather than of a… |
| · | &nbsp;&nbsp;`Admin.test_export` | 757 | Try one export's destination and say what happened. |
| · | &nbsp;&nbsp;`Admin.save` | 773 | Check a form and write it. Returns what was wrong, empty if nothing. Everything is valida… |
| f | `rejoined` | 848 | One value per option, out of the fields the wire actually carried. Three controls send something other than t… |
| f | `overridden` | 899 | The environment variable outranking this setting, if there is one. The order is argument, environment, file,… |
| f | `slots` | 930 | A list of choices, in an order that is the value's order. Every candidate gets a row, ticked or not. What sto… |
| f | `field` | 1036 | One setting as a form field. `moved` names the file that has taken this setting over, if one has. Today that… |
| f | `anchor` | 1216 | A fragment name from a group label. Stable, because it is a link. |
| f | `group_html` | 1221 |  |
| f | `new_export_page` | 1280 | The form that creates one. Two fields, and nothing else yet. |
| f | `notify_kind_choices` | 1318 | The channels there are, from the registry rather than from a list. |
| f | `new_notify_page` | 1328 | The form that creates one. A name and a way of reaching somebody. |
| f | `new_upload_page` | 1370 | The form that creates one. A name and a service. |
| f | `new_forecast_page` | 1409 | A name and a source. The rest waits. |
| f | `new_collector_page` | 1447 | A collector: a name and what it runs. The page says what happens next, because most of it happens elsewhere.… |
| f | `new_feed_page` | 1581 | Two fields: a name and a kind. The rest waits. |
| f | `website_summary` | 1676 | What the built-in server hands out, and at which address. The question this page exists to answer. Without it… |
| f | `sub_pages` | 1900 | Pages whose name carries an instance, so no fixed list can hold them. `tools/adminpage.py` enumerates schemas… |
| f | `page` | 2008 |  |
| **C** | `AdminServer` | 4484 | The admin page, on its own port. |
| · | &nbsp;&nbsp;`AdminServer.__init__` | 4487 |  |
| · | &nbsp;&nbsp;`AdminServer.serve_forever` | 4495 |  |
| · | &nbsp;&nbsp;`AdminServer.start` | 4498 |  |
| · | &nbsp;&nbsp;`AdminServer.stop` | 4503 |  |

## `src/weewx_evo/adminaddons.py`

[Drivers](Drivers) · last changed 2026-09-04 14:42

| | Name | Line | |
|---|---|---|---|
| f | `nav` | 42 | This page's entry in the System section. |
| f | `overview` | 117 | The page. |
| f | `act` | 195 | Install or remove one. Returns "" or what went wrong. `action` is the last path segment rather than a form fi… |

## `src/weewx_evo/adminarchives.py`

[Several places](Places) · last changed 2026-09-04 10:42

| | Name | Line | |
|---|---|---|---|
| f | `chain` | 64 | The stable data path, with the current step marked. |
| f | `path_for` | 80 | Beside the configuration file, like stations.toml and plots.toml. |
| **C** | `SenderChoice` | 86 | A live sender ID and its presentation-only label. |
| · | &nbsp;&nbsp;`SenderChoice.name` | 99 | Compatibility label for read-only sender diagnostics. |
| f | `sender_choices` | 104 | Senders observed in live, plus configured ones no longer retained. Nothing here reads ``stations.toml``. The… |
| f | `settings_of` | 146 | The saved settings, for writing out the first place. Not the running `Settings`: this page reads the file it… |
| f | `load` | 166 |  |
| f | `store` | 173 | Write them. Returns an error, or empty if it worked. |
| f | `from_form` | 266 | An archive from what a form sent. Every field `Archive` has, because `configure` replaces the whole record: o… |
| f | `create` | 325 | Add a place. Returns (what was added, error). |
| f | `configure` | 347 | Change one archive in place. |
| f | `remove` | 370 | Take one off the list. The file stays where it is. |
| f | `title_for` | 389 | One name at every installation size. |
| f | `nav` | 394 |  |
| f | `overview` | 1059 | A master/detail editor with the same shape for one or many places. |
| f | `new` | 1130 |  |

## `src/weewx_evo/adminfields.py`

[The settings page](Admin-Page) · last changed 2026-09-04 10:42

| | Name | Line | |
|---|---|---|---|
| **C** | `Placement` | 86 | One raw field, and everything needed to decide where it goes. |
| · | &nbsp;&nbsp;`Placement.__init__` | 92 |  |
| · | &nbsp;&nbsp;`Placement.state` | 117 | One word for what is true, which decides how the row reads. |
| f | `archives_of` | 144 | Every place that selects this live sender, in register order. ``None`` is the broad selection and an empty tu… |
| f | `archive_of` | 156 | The explicitly named place, or the sole place selecting this station. Refusing an ambiguous lookup is importa… |
| f | `holders` | 192 | Every ``(station, raw)`` that fills each field in one place. Only this archive's. Two stations writing `soilT… |
| f | `placements` | 242 | One `Placement` per raw field this station last sent. Only what it has actually sent. A catalog is five hundr… |
| f | `candidates` | 297 | Where a reading could go in this station's archive, and what is there. One call for the whole table rather th… |
| f | `place` | 358 | Put one raw field somewhere, for one station. Returns an error or "". Written to `placement.toml`, scoped to… |
| f | `save_for_place` | 415 | Save one Place-to-Sender mapping without station or driver state. |
| f | `add_column` | 459 | Give a reading somewhere to live, in this station's archive. Not in "the" archive: with two of them the colum… |
| f | `sparkline` | 617 | The last few hours of one raw reading, as a curve beside its value. A number says what a sensor reads now; it… |
| f | `table` | 653 | One independently scoped form per place that selects this station. A station can feed more than one place. Re… |
| f | `table_for_place` | 667 | One mapping editor for an explicit Place-to-Sender relationship. |
| f | `measures` | 772 | `group_pressure` reads as `pressure`. The prefix is how the unit table namespaces its keys; on a page it is f… |

## `src/weewx_evo/adminhome.py`

[The settings page](Admin-Page) · last changed 2026-09-04 14:29

| | Name | Line | |
|---|---|---|---|
| f | `sparkline` | 83 | A day of hourly counts, as bars. Inline SVG, no script. A number is a moment and this page is about whether s… |
| f | `ago` | 133 | How long ago, in words. The only time format on this page. |
| **C** | `Link` | 149 | One step in the chain, as the page shows it. |
| **C** | `State` | 170 | Everything the overview knows, gathered once. |
| **C** | `Series` | 392 | One place, as every page that asks about places sees it. One pass and one shape, because the overview and the… |
| f | `archives_state` | 421 | Every place, read once. One read-only connection per place, opened and closed. Never kept on `admin`: that ob… |
| f | `read` | 1005 | Everything, gathered once. A failure in one part does not stop it. |
| f | `nav` | 1026 |  |
| f | `overview` | 1134 |  |

## `src/weewx_evo/adminlive.py`

[The settings page](Admin-Page) · last changed 2026-09-04 10:42

| | Name | Line | |
|---|---|---|---|
| f | `feed` | 38 | Rows of the live table, with every column it has. Three ways in, and they are the page's three needs rather t… |
| f | `nav` | 357 |  |
| f | `overview` | 363 | Read-only journal rows and a bounded status summary. |

## `src/weewx_evo/adminplots.py`

[Plots](Plots) · last changed 2026-09-04 10:42

| | Name | Line | |
|---|---|---|---|
| f | `path_for` | 81 | Where plots.toml lives: beside the configuration. |
| f | `load` | 86 | The charts, laying the starter set down on a first run. Here as well as in `cli.load_plots`, because these ar… |
| f | `store` | 105 | Write them. Returns an error, or empty if it worked. |
| f | `add` | 117 | A new chart with one reading in it. Everything else on the next page. |
| f | `compare` | 142 | One chart per reading, drawing every place at once. (said, error) The overlay is what makes a site of several… |
| f | `remove` | 190 |  |
| f | `save` | 197 | Everything about one chart, from its form. Errors keyed by field. |
| f | `plot_defs_vectors` | 349 |  |
| f | `bring_over` | 406 | Import from a WeeWX skin. Returns (message, error). From a file that was uploaded, from text that was pasted,… |
| f | `nav` | 489 | One entry. The charts themselves are on its page. They used to be four collapsed groups plus two "add" links,… |
| f | `overview` | 537 | Every chart, grouped by the span it covers. A hundred charts was four collapsed groups in the sidebar, which… |
| f | `series_choices` | 627 | Every place a line can read: its name, what to call it, its colour. Empty where there is one. With a single s… |
| f | `known_series` | 656 | The archives configured, by name. Empty where there is one. |
| f | `edit` | 759 | One chart's page. |
| f | `new` | 946 | The add-a-chart form. Three fields; the rest waits. |
| f | `importer` | 992 | The bring-it-over-from-WeeWX form. Three ways in, and the order matters. A file is the one that works from an… |

## `src/weewx_evo/adminpublish.py`

[The settings page](Admin-Page) · last changed 2026-09-04 10:42

| | Name | Line | |
|---|---|---|---|
| f | `overview` | 307 |  |
| f | `nav` | 399 |  |
| f | `feeds_dir` | 405 |  |
| f | `context` | 410 | Where the thing being edited sits in the chain, above its form. The Publishing page knows that the `wdc` expo… |

## `src/weewx_evo/adminquality.py`

[Quality control](Quality) · last changed 2026-09-04 10:42

| | Name | Line | |
|---|---|---|---|
| f | `path_for` | 77 | Beside the configuration, like `plots.toml`. |
| f | `load` | 85 |  |
| f | `store` | 89 | Write the file. Returns an error, or empty. Written beside and renamed, so a page saved while the archiver is… |
| f | `as_toml` | 108 | The policy as the file a person would have written. |
| f | `survey` | 160 | What the readings have been, and what the rules would refuse. One pass over every series, because the page ne… |
| f | `measured` | 206 | What each reading has been, from the archives. The figure beside the box. Without it the page is a text edito… |
| f | `save` | 268 | Take the whole table back. Returns errors by field name. |
| f | `suggest` | 306 | Fill the table in from what the station has recorded. The button that makes this page worth having. It never… |
| f | `clear` | 332 | Drop one reading's rule. |
| f | `nav` | 345 | One entry, with how many readings have a rule. |
| f | `overview` | 358 |  |

## `src/weewx_evo/adminsearch.py`

[The settings page](Admin-Page) · last changed 2026-09-04 10:42

| | Name | Line | |
|---|---|---|---|
| **C** | `Hit` | 46 | One thing found, and how to reach it. |
| · | &nbsp;&nbsp;`Hit.__init__` | 51 |  |
| f | `find` | 71 | Everything matching, best first. |
| f | `box` | 194 | The search field. On every page, because that is the point of it. |
| f | `results` | 207 |  |

## `src/weewx_evo/adminsetup.py`

[The settings page](Admin-Page) · last changed 2026-09-04 10:42

| | Name | Line | |
|---|---|---|---|
| f | `state` | 55 | What is already answered, so a reopened wizard skips what is done. |
| f | `done_with` | 115 | Whether that step has been answered. |
| f | `page` | 133 | One step of the wizard. |

## `src/weewx_evo/adminstations.py`

[Several places](Places) · last changed 2026-09-04 13:29

| | Name | Line | |
|---|---|---|---|
| f | `setups` | 26 | What each installed driver says about pointing hardware at it. Asked of the drivers rather than listed here,… |
| f | `tellable` | 50 | The ones whose hardware has a field to type an address into. |
| f | `learns_its_identity` | 55 | Whether this hardware carries a name of its own we have to read. Where it does not, the identity is handed ou… |
| f | `path_for` | 73 | Where stations.toml lives: beside the configuration, like plots.toml. |
| f | `load` | 78 |  |
| f | `store` | 82 | Write them. Returns an error, or empty if it worked. |
| f | `live_db` | 94 | Where the live database is, as this process can reach it. Three ways it can be written and all three turn up.… |
| f | `sightings_for` | 111 | The strangers, out of the live database. Read-only here and opened per request. The listener holds its own co… |
| f | `last_seen` | 142 | When each station last had a packet stored. Asked of the live table rather than kept in the file. The table a… |
| f | `adopt` | 205 | Take a stranger into the register. Returns an error, or empty. |
| f | `announce` | 228 | Create a station. Returns (station, error). Two shapes, and which one depends on where the identity comes fro… |
| f | `learn` | 252 | Give a waiting station the identity off the wire. Returns (found, error). The wizard's other half, for hardwa… |
| f | `configure` | 320 | Change settings intrinsic to one console. Returns an error, or empty. |
| f | `remove` | 342 |  |
| f | `ignore` | 349 |  |
| f | `nav` | 361 |  |
| f | `overview` | 468 | Named, newly discovered and ignored live senders. |
| f | `new` | 654 | Register a sender whose hardware can be pointed at the listener. |
| f | `fill` | 892 | Put this installation's answers into a driver's placeholders. Replaced rather than `%`-formatted. A driver is… |
| f | `what_it_sends` | 991 | Latest raw readings for one sender, described only by stored data. Driver code is an ingest concern. Once a p… |
| f | `recent_series` | 1091 | The last few hours of each raw reading, thinned to a drawable number. A last value says what a sensor reads n… |

## `src/weewx_evo/adminsystem.py`

[The settings page](Admin-Page) · last changed 2026-09-04 14:31

| | Name | Line | |
|---|---|---|---|
| f | `overview` | 49 |  |

## `src/weewx_evo/adopt.py`

[Stations and Archives](Stations-and-Archives) · last changed 2026-08-29 14:31

| | Name | Line | |
|---|---|---|---|
| **C** | `Found` | 58 | One WeeWX installation, as much of it as could be read. |
| · | &nbsp;&nbsp;`Found.usable` | 80 | Whether anything came out of it. The settings, not the path. A file that arrived by uploa… |
| · | &nbsp;&nbsp;`Found.records` | 91 | How many archive records its database holds. 0 if unreadable. |
| f | `find` | 98 | A weewx.conf on this machine, or None. Tried in order and the first readable one wins. `$WEEWX_CONFIG` before… |
| f | `read` | 123 | Everything a weewx.conf says, in our terms. `text` is for a file that arrived by upload rather than being on… |
| f | `is_archive` | 248 | Whether that file is a WeeWX archive we can read. Opened and asked, not guessed from the name. A file called… |
| f | `count_records` | 278 |  |
| f | `span_of` | 292 | First and last timestamp in it, or (0, 0). |
| f | `adopt_archive` | 309 | Put an existing archive where this installation will read it. Copied rather than moved or pointed at, and tha… |
| f | `charts_in` | 368 | The charts out of each skin this installation renders. In the skins, not in weewx.conf: measured on a shipped… |

## `src/weewx_evo/aggregate.py`

[Aggregation](Aggregation) · last changed 2026-08-26 23:43

| | Name | Line | |
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

## `src/weewx_evo/api.py`

[API](API) · last changed 2026-09-04 00:50

| | Name | Line | |
|---|---|---|---|
| **C** | `Answer` | 81 | One reply: a status, a content type and a body. |
| · | &nbsp;&nbsp;`Answer.of` | 89 |  |
| · | &nbsp;&nbsp;`Answer.wrong` | 95 |  |
| **C** | `Api` | 101 | Answers the questions `series.py` can answer. Holds no connection. One is opened per request and closed with… |
| · | &nbsp;&nbsp;`Api.__init__` | 110 |  |
| · | &nbsp;&nbsp;`Api.handles` | 125 |  |
| · | &nbsp;&nbsp;`Api.answer` | 128 |  |
| · | &nbsp;&nbsp;`Api.allowed` | 156 | Whether this request may be answered. The token may be in a header or in the query. A hea… |
| · | &nbsp;&nbsp;`Api.index` | 172 | What this answers. So a person with the address can find the rest. |
| · | &nbsp;&nbsp;`Api.archives_answer` | 190 |  |
| · | &nbsp;&nbsp;`Api.stations_answer` | 202 | The consoles, from `stations.toml`. No identities. An identity is what a console proves i… |
| · | &nbsp;&nbsp;`Api.fields_answer` | 216 | What is recorded, with what it measures and what it is in. The endpoint a client calls fi… |
| · | &nbsp;&nbsp;`Api.current` | 243 | The newest record, converted if asked. |
| · | &nbsp;&nbsp;`Api.series` | 269 | A reading over a span. The endpoint this whole file is for. |
| · | &nbsp;&nbsp;`Api.aggregate` | 308 | One number for one span. |
| **C** | `Wrong` | 404 | A request that cannot be answered, with the reason for the caller. |

## `src/weewx_evo/archiver.py`

[Archiver](Archiver) · last changed 2026-09-04 02:07

| | Name | Line | |
|---|---|---|---|
| **C** | `Built` | 93 | One archive interval, worked out. |
| **C** | `Archiver` | 113 | Turns live packets into archive records and daily summaries. |
| · | &nbsp;&nbsp;`Archiver.__init__` | 116 |  |
| · | &nbsp;&nbsp;`Archiver.build` | 177 | Work out the record for the interval ending at `stop`. Returns None if no packet fell in… |
| · | &nbsp;&nbsp;`Archiver.store` | 386 | Write one built interval, then let its LOOP packets sharpen the day. The order matters. T… |
| · | &nbsp;&nbsp;`Archiver.process_due` | 418 | Build and store every interval that has closed. Returns how many. Safe to call at any mom… |
| · | &nbsp;&nbsp;`Archiver.catch_up` | 444 | Build every interval covered by the live table that is not archived. Used at startup, aft… |
| · | &nbsp;&nbsp;`Archiver.rebuild` | 489 | Work out every interval in (start, stop] again, replacing what is there. The daily summar… |
| · | &nbsp;&nbsp;`Archiver.run` | 528 | Poll for closed intervals until told to stop. A plain sleep loop rather than a scheduler.… |

## `src/weewx_evo/archives.py`

[Stations and Archives](Stations-and-Archives) · last changed 2026-09-04 09:03

| | Name | Line | |
|---|---|---|---|
| **C** | `MemberPolicy` | 73 | How one archive treats one of the senders it selects. Whether a sender is the primary one is not here: that i… |
| · | &nbsp;&nbsp;`MemberPolicy.from_dict` | 92 | One strictly checked policy from TOML values. |
| **C** | `Archive` | 108 | One measurement series, and what is true of the place it measures. |
| · | &nbsp;&nbsp;`Archive.title` | 212 | What to print. The label if there is one, else the name. |
| · | &nbsp;&nbsp;`Archive.place` | 216 | The three numbers, in the shape `derive.Station` wants them. |
| · | &nbsp;&nbsp;`Archive.as_dict` | 221 |  |
| · | &nbsp;&nbsp;`Archive.policy_for` | 226 | How this archive treats one sender; defaults are intentionally plain. |
| · | &nbsp;&nbsp;`Archive.primary_sender` | 230 | Which sender this series is taken from, or `""` if it has none. `known` is the live sende… |
| · | &nbsp;&nbsp;`Archive.role_of` | 266 | `roles.MAIN` for the sender this series comes from, else `roles.EXTRA`. `primary` short-c… |
| · | &nbsp;&nbsp;`Archive.senders` | 290 | Canonical live sender IDs selected by this place. ``None`` is the explicit broad selectio… |
| · | &nbsp;&nbsp;`Archive.selects` | 300 | Whether this place reads one canonical sender ID. |
| f | `from_settings` | 472 | The one place an installation's `station.*` settings describe. Read only where there is no `archives.toml` ye… |
| f | `timezone_gap` | 504 | Hours between this place's sun and the clock this process keeps. None when the archive has no longitude, beca… |
| f | `timezone_concern` | 526 | Why this archive's days may not be its days, or an empty string. Said rather than fixed. The fix is to run th… |
| **C** | `Register` | 545 | Every archive, and which file each one is. Re-read when the file changes, for the same reason the station reg… |
| · | &nbsp;&nbsp;`Register.__init__` | 553 |  |
| · | &nbsp;&nbsp;`Register.load` | 563 | Read the list without consulting listener configuration. A present file is the whole answ… |
| · | &nbsp;&nbsp;`Register.refresh` | 589 | Re-read if the file has changed. True when something did. |
| · | &nbsp;&nbsp;`Register.all` | 622 | Every archive the file names, in storage order. |
| · | &nbsp;&nbsp;`Register.names` | 626 |  |
| · | &nbsp;&nbsp;`Register.default_name` | 629 | The unambiguous implicit name, or a clear refusal. A literal `[archives.default]` is an e… |
| · | &nbsp;&nbsp;`Register.get` | 644 | One archive by exact name. `None` is accepted only through `default_name`; an unknown non… |
| · | &nbsp;&nbsp;`Register.ordered` | 657 | Every place, in the order pages present them. Separate from `all()` on purpose, and the d… |
| · | &nbsp;&nbsp;`Register.presented` | 667 | The same list with a colour and a short code filled in. For renderers, never for saving.… |
| · | &nbsp;&nbsp;`Register.several` | 692 | Whether anything has to be told apart in the presentation. |
| · | &nbsp;&nbsp;`Register.overriding` | 696 | Compatibility answer: a loaded register always comes from the file. |
| · | &nbsp;&nbsp;`Register.concerns` | 700 | What is wrong with this arrangement, by archive name. Empty is the ordinary answer. It ex… |
| · | &nbsp;&nbsp;`Register.add` | 716 |  |
| · | &nbsp;&nbsp;`Register.replace` | 723 |  |
| · | &nbsp;&nbsp;`Register.remove` | 730 | Take an archive off the list. The file is left where it is. Deliberately not deleted. It… |
| · | &nbsp;&nbsp;`Register.why_not` | 743 | Why this archive cannot be added, or an empty string. |
| · | &nbsp;&nbsp;`Register.render` | 807 |  |
| · | &nbsp;&nbsp;`Register.save` | 851 | Write the file, atomically. Same as the station register. |
| **C** | `Placed` | 946 | The settings as one archive sees them. Everything that formats or draws a page reads `station.latitude` and i… |
| · | &nbsp;&nbsp;`Placed.__init__` | 984 |  |
| · | &nbsp;&nbsp;`Placed.get` | 988 |  |
| f | `placed` | 1006 | The settings for one archive; a place is required. |

## `src/weewx_evo/catalogue.py`

[Drivers](Drivers) · last changed 2026-09-04 14:34

| | Name | Line | |
|---|---|---|---|
| **C** | `Plugin` | 69 | One entry of the catalogue. |
| · | &nbsp;&nbsp;`Plugin.reads` | 82 | How well this add-on matches that upload. 0 is not at all. 2 for the body, 1 for the path… |
| f | `matching` | 110 | Every add-on that could read this, the strongest match first. Every, and not the best one. An Ecowitt custom… |
| f | `parse` | 129 | The catalogue out of its TOML. Empty where it cannot be read. Empty rather than raising: this is a convenienc… |
| f | `cached` | 155 | What was last fetched, and when. Empty and 0 if there is nothing. |
| f | `fetch` | 165 | The catalogue, from the network or from the last copy of it. Never raises and never blocks for long. A statio… |

## `src/weewx_evo/chartdata.py`

[Plots](Plots) · last changed 2026-09-04 09:03

| | Name | Line | |
|---|---|---|---|
| **C** | `Place` | 90 | One of the places a chart draws, as far as drawing is concerned. Presentation and geography, and deliberately… |
| **C** | `Line` | 117 | One reading, fetched and converted. What a renderer draws. |
| · | &nbsp;&nbsp;`Line.empty` | 160 |  |
| **C** | `Chart` | 165 | One plot, with its data. What both renderers are handed. |
| · | &nbsp;&nbsp;`Chart.empty` | 203 |  |
| f | `build` | 207 | One plot's data, or None if this station has none of its readings. Every line is fetched, converted, and trim… |
| f | `column_of` | 738 | The column behind a reading, for asking whether it exists. `windvec` is not a column; the speed it is made of… |
| f | `round_all` | 746 | Round a sequence, leaving the gaps in the data alone. |
| f | `components` | 754 | A vector series split into how far east and how far north. A chart drawing arrows scales and offsets the comp… |
| f | `drop_empty` | 776 | Leave out the points that carry nothing, keeping real gaps visible. A sensor reporting every ten minutes fill… |

## `src/weewx_evo/cli.py`

[CLI reference](CLI-Reference) · last changed 2026-09-04 14:32

| | Name | Line | |
|---|---|---|---|
| f | `env` | 81 |  |
| f | `add_archive_arg` | 85 | Which series a single-shot command works on. The database path belongs to its entry in archives.toml. Command… |
| f | `add_common` | 101 |  |
| f | `add_listen_args` | 140 |  |
| f | `add_archive_args` | 163 |  |
| f | `settings_for` | 176 | The process's settings, resolved once. Once, not once per caller. With each component resolving for itself, a… |
| f | `read_config` | 219 | The whole configuration file, or an empty one. A file that is not there yet is not an error: a first start ha… |
| f | `configure_drivers` | 230 | Hand each driver its options, and somewhere to keep its own state. Until this runs the drivers are unconfigur… |
| f | `sender_clock_settings` | 318 | Per-sender clock tolerances for one driver, out of `stations.toml`. These are front-door policy: a timestamp… |
| f | `install_driver_groups` | 354 | Tell the core what the drivers call their own fields. Without this a station's own columns -- `extraTemp9`, `… |
| f | `stations_path` | 394 | Where stations.toml lives: beside the configuration, like plots.toml. Not beside the database. Both are usual… |
| f | `archives_path` | 406 | Where archives.toml lives: beside stations.toml, for the same reason. |
| f | `placement_path` | 415 | Where placement.toml lives: beside stations.toml, for the same reason. |
| f | `read_placements` | 424 | Where each console's readings go. A missing file is "wherever the catalog says". |
| f | `build_placer` | 441 | One archive's placer. |
| f | `status_placer` | 448 | A placer for the listener's headline, or none when none is implicit. Placement is not part of ingest: the lis… |
| f | `read_archives` | 466 | Every measurement series this installation keeps. With no file, `Register.load` writes the central archive se… |
| f | `selected_archive` | 489 | One exact archive, or a short command-line error. An omitted name means the registry's declared default. An u… |
| f | `archive_path_of` | 510 | An archive path, relative to the configuration that names it. |
| f | `open_archive` | 518 | The store for one series. Relative paths resolve against the configuration file, the same as every other path… |
| f | `build_archivers` | 532 | One archiver per series, selected only through live sender ids. The three numbers come off the archive rather… |
| f | `archive_senders` | 576 | Which canonical live senders write one series. None means explicit *. This answer comes only from the archive… |
| f | `archive_stations` | 592 | Temporary consumer alias; archive runtime uses ``archive_senders``. |
| f | `read_stations` | 597 | The announced consoles, and where strangers get noted. Two halves stored two ways, on purpose. `stations.toml… |
| f | `quality_path` | 620 | Where `quality.toml` lives: beside the configuration unless told. Its own function because the watcher needs… |
| f | `read_quality` | 640 | The calibration and the limits, from `quality.toml`. Its own file rather than a section in the settings, for… |
| f | `read_sources` | 661 | Read the retired source-policy format for tools and compatibility. Production archivers do not call this. Pla… |
| f | `warn_obsolete_sources` | 691 | Say when retired global source routing is present; never interpret it. |
| f | `open_stores` | 708 |  |
| f | `make_archiver` | 727 | One archiver, for the series `--series` names or for the default. The single-shot commands work on one at a t… |
| f | `start_watchdog` | 753 | The watchdog, where this installation asked for one. Built here rather than in each command because all three… |
| f | `cmd_listen` | 775 |  |
| f | `cmd_archive` | 844 |  |
| f | `cmd_upload_list` | 974 |  |
| f | `cmd_upload_check` | 1005 | Ask each service whether it accepts the account. Worth more than the equivalent for an export: these services… |
| f | `cmd_upload_compare` | 1065 | Count both ends, and say where they differ. A second store is a second truth. Trusting that every write lande… |
| f | `cmd_upload_run` | 1129 | Send now, whatever the trigger says. |
| f | `cmd_forecast_list` | 1163 |  |
| f | `cmd_forecast_check` | 1189 | Fetch once and say what came back. This is also how somebody finds a DWD station id or a MeteoAlarm region: a… |
| f | `cmd_forecast_run` | 1244 | Fetch now and store, whatever the schedule says. |
| f | `cmd_forecast_show` | 1267 | Print what is stored, which is what a page would draw. |
| f | `cmd_serve` | 1331 | Listener and archiver in one process, for a small machine. They still speak only through the database. Splitt… |
| f | `cmd_catchup` | 1682 |  |
| f | `cmd_rebuild` | 1730 |  |
| f | `cmd_derive` | 1750 | Fill in derived readings on records that are already in the archive. A calculator that arrives late leaves a… |
| f | `cmd_mqtt_check` | 1937 | Subscribe, print what arrives, deliver nothing. The command somebody runs first, and the reason it exists: a… |
| f | `cmd_mqtt_run` | 1983 | Subscribe and deliver, until stopped. Its own process, like the WeeWX shim and for the same reason: a broker… |
| f | `cmd_import_dump` | 2014 | Read a MySQL or Postgres dump into the archive. `--dry-run` first, always, and the command says so: this writ… |
| f | `cmd_import_csv` | 2072 | Read a CSV of readings into the archive. The format every other weather program can produce, and the one some… |
| f | `cmd_columns` | 2126 | Readings that the archive has no column for. A reading only survives the archive interval if the table has a… |
| f | `cmd_driver_list` | 2218 |  |
| f | `cmd_driver_install` | 2250 |  |
| f | `cmd_driver_remove` | 2284 |  |
| f | `cmd_addon_list` | 2293 | What is installed here, and what the catalogue offers. Both, because the useful question on a fresh machine i… |
| f | `cmd_addon_install` | 2325 |  |
| f | `cmd_addon_remove` | 2341 |  |
| f | `local_addresses` | 2354 | Addresses this machine can be reached on, as (address, what it is). Only what can be worked out without askin… |
| f | `cmd_url` | 2386 | Print the addresses of the live view and the upload endpoint. The token is a path segment, so an address with… |
| f | `driver_directory` | 2454 | Where third-party drivers live, resolved like everything else. The command line first, then the setting, then… |
| f | `all_schemas` | 2471 | Every configurable thing there is: the core, then each driver. Drivers are asked, not enumerated. One that ga… |
| f | `replace_group` | 2669 |  |
| f | `cmd_config_show` | 2675 | Print the configuration as it stands, commented. |
| f | `cmd_config_set` | 2688 | Set one value, checked against the schema that owns it. |
| f | `cmd_config_check` | 2719 | Check every value against its schema and say what is wrong. |
| f | `cmd_config_import` | 2830 | Read a weewx.conf and write what it says into our own file. |
| f | `cmd_admin` | 2875 | Serve the settings page. Its own port and its own token, deliberately. An upload endpoint can at worst put a… |
| f | `configured_exports` | 2956 | What the configuration file says about exports, by name. |
| f | `configured_uploads` | 2964 | What the configuration file says about uploads, by name. |
| f | `build_upload` | 2972 | Make one upload from its settings. Raises with a usable message. |
| f | `build_upload_for_place` | 3009 | Make one upload with the settings owned by its Place. The scheduler, the command-line check and the admin-pag… |
| f | `build_upload_schedule` | 3066 | What the uploads are, right now. They read the archive themselves rather than being handed a record: the comp… |
| f | `live_readings_locally` | 3171 | The live upload an export has already asked for, with nothing to fill in. An export saying "live readings" ha… |
| f | `configured_forecasts` | 3291 | What the configuration file says about forecast sources, by name. |
| f | `forecast_db` | 3299 | The installation's shared forecast store, beside its configuration. |
| f | `forecast_place` | 3310 | Where a forecast is for. `cfg` is the settings **as one archive sees them** where there is more than one -- `… |
| f | `build_forecast_source` | 3327 | Make one forecast source. Raises with a usable message. |
| f | `mirror_forecast` | 3349 | A callback that copies a fresh forecast into every InfluxDB upload. Only InfluxDB. Every other upload in that… |
| f | `build_forecast_schedule` | 3394 | What the forecast sources are, right now, and which series each is for. One entry, one archive. Not one sourc… |
| f | `apply_live` | 3433 | Apply a changed configuration to a running process. Everything that can be rebuilt in place, in one function.… |
| f | `build_schedule` | 3566 | What the exports are, right now. An export pointed at a feed has to be told where that feed writes, or it is… |
| f | `resolve_paths` | 3590 | Make an export's own paths absolute, against the configuration file. The same rule as plots.toml: a relative… |
| f | `build_export` | 3610 | Make one export from its settings. Raises with a usable message. `upload_token` is what `live.php`'s token is… |
| f | `cmd_export_list` | 3638 |  |
| f | `cmd_export_check` | 3670 | Try each destination without sending anything. |
| f | `cmd_export_run` | 3698 | Send. This is what a feed would call when it has produced something. |
| f | `cmd_web` | 3750 | Serve the feeds, and nothing else. Separate from `serve` for the same reason `listen` is: a machine that only… |
| f | `plots_path` | 3804 | Where plots.toml lives: beside the configuration unless told otherwise. |
| f | `load_plots` | 3818 | The charts, laying the starter set down on a first run. A station with no charts has no feed with anything to… |
| f | `configured_feeds` | 3873 | What the configuration says about feeds, by name. A name is one configured feed; `kind` says what it is. Two… |
| f | `feed_dirs` | 3891 | Where each feed writes, by name. One place, because two things need the answer and they must agree: the feed… |
| f | `feed_schedule` | 3912 | When each configured feed runs, and which archive it reads. Read here rather than asked of the feed class, be… |
| f | `build_feeds` | 3975 | The feeds this configuration asks for, in the order they run. Ordered by dependence: anything reading what an… |
| f | `served_directories` | 4409 | What the built-in server hands out, by name. The local exports, plus anything named directly. The same answer… |
| f | `cmd_plots_list` | 4431 | What charts exist. Through `load_plots`, so this is the set the feeds draw and not just the file: a site of s… |
| f | `cmd_plots_show` | 4477 | One chart, in full. |
| f | `cmd_plots_import` | 4512 | Take the plots out of a WeeWX skin.conf or weewx.conf. Read, reported, and only written when asked. An import… |
| f | `cmd_plots_compare` | 4571 | One chart per reading per span, drawing every place on one axis. Read, reported, and only written when asked… |
| f | `cmd_plots_remove` | 4634 | Delete a chart. |
| f | `cmd_plots_run` | 4646 | Produce the JSON now, and say what came out. |
| f | `start_feeds` | 4705 | Start the feed runner, or say why there is nothing to run. One function for both loops. They had their own co… |
| f | `configured_notify` | 4781 | What the configuration file says about notification channels. |
| f | `build_channel` | 4789 | One channel from its settings. Raises with a usable message. |
| f | `build_metrics` | 4810 | What the process is doing, or None where it is switched off. |
| f | `build_api` | 4841 | The read-only API, or None where it is switched off. Every archive, by name, so a client can ask about any of… |
| f | `build_notify_runner` | 4870 | The notification runner, or None where nothing is configured. What it watches for failures is the exports and… |
| f | `cmd_backup` | 4951 | Copy the archive safely, while the station carries on. `sqlite3.Connection.backup`, not a file copy. See main… |
| f | `cmd_verify` | 4998 | Is the file sound, and do the summaries still follow from the records? Two questions, and the second is ours.… |
| f | `cmd_vacuum` | 5028 | Rewrite a database without its free pages. |
| f | `cmd_notify_list` | 5046 | What is configured, and what could be. |
| f | `cmd_notify_check` | 5071 | Send a test message through each channel. |
| f | `cmd_notify_status` | 5100 | What is wrong right now, whether or not anybody has been told. |
| f | `cmd_placement_list` | 5136 | What each console sends, and which column it reaches. Reads the two files and the proposals; asks no hardware… |
| f | `cmd_placement_accept` | 5200 | Turn what inference worked out into lines somebody can read. Nothing is written without `--write`, for the re… |
| f | `cmd_quality_suggest` | 5241 | Work rules out of what this station has actually recorded. Nobody can type a plausible ceiling for `soilMoist… |
| f | `cmd_quality_check` | 5321 | Run the configured rules over what is stored, and change nothing. The answer to "what would this cost me". A… |
| f | `cmd_grafana_list` | 5406 | What would be provisioned, without writing anything. |
| f | `cmd_grafana_provision` | 5434 | Write the datasource and the dashboards Grafana reads at start. |
| f | `cmd_status` | 5472 |  |
| f | `main` | 5526 |  |

## `src/weewx_evo/collectors.py`

[Stations and Archives](Stations-and-Archives) · last changed 2026-09-04 14:21

| | Name | Line | |
|---|---|---|---|
| **C** | `Choice` | 51 | Something to pick while a collector of one kind is being created. Asked on the "add" page rather than on the… |
| **C** | `Kind` | 73 | One sort of collector: what it is called, what it reads, how to run it. The command is in here rather than on… |
| f | `kinds` | 108 | What a collector can be here: the core's own, and what is installed. Asked rather than listed, for the reason… |
| f | `reserved` | 161 | Names already spoken for, so a new collector cannot take one. |
| f | `configured` | 175 | The collectors in the configuration, by name. `Settings.config` is the parsed file, which is where every othe… |
| f | `describe` | 191 | What a collector is, and -- given its name -- how it is started. Named, it says the command, because the sett… |
| f | `start_command` | 214 | What to type where the hardware is, for this kind of collector. |
| f | `register_names` | 225 | Give each configured collector its own endpoint at the listener. The parser behind every one of them is the e… |
| f | `options` | 258 | One collector's settings, for its page. Per kind, because they have almost nothing in common: a WeeWX driver… |
| f | `settings_for` | 329 | One collector's settings, or {} if there is no such collector. |
| f | `driver_settings` | 334 | What was chosen for the driver itself, under its own prefix. Separate from the collector's own settings becau… |
| f | `endpoint` | 346 | The path a collector delivers to, without the token. |

## `src/weewx_evo/config.py`

[Configuration](Configuration) · last changed 2026-08-30 14:53

| | Name | Line | |
|---|---|---|---|
| f | `read` | 33 | The configuration file, or an empty one if it is not there yet. |
| f | `get` | 42 | A value by its dotted name: get(cfg, 'station.latitude'). |
| f | `resolved` | 52 | A value the way the running process resolves it: environment first. `get()` reads the file, which is what the… |
| f | `resolved_path` | 79 | The same, as a path, against the settings file rather than the cwd. Relative to the file and not to whatever… |
| f | `put` | 92 | Set a value by its dotted name, making the sections on the way. |
| f | `values_for` | 105 | What this schema's settings currently are, defaults filled in. |
| f | `apply` | 117 | Write a schema's settings into the configuration. |
| f | `write` | 129 | Write the configuration out, commented, and keep the previous one. Written beside and moved into place, so an… |
| f | `render` | 154 | The configuration as a commented TOML file. |

## `src/weewx_evo/db/archive.py`

[The archive database](Database-Archive) · last changed 2026-09-03 23:25

| | Name | Line | |
|---|---|---|---|
| **C** | `ArchiveStore` | 33 | A WeeWX archive database, open for reading and writing. |
| · | &nbsp;&nbsp;`ArchiveStore.__init__` | 36 |  |
| · | &nbsp;&nbsp;`ArchiveStore.close` | 58 |  |
| · | &nbsp;&nbsp;`ArchiveStore.reload_schema` | 67 | Re-read the schema. Needed after anything alters the tables. |
| · | &nbsp;&nbsp;`ArchiveStore.last_timestamp` | 117 |  |
| · | &nbsp;&nbsp;`ArchiveStore.count` | 120 |  |
| · | &nbsp;&nbsp;`ArchiveStore.exists` | 123 |  |
| · | &nbsp;&nbsp;`ArchiveStore.record` | 128 |  |
| · | &nbsp;&nbsp;`ArchiveStore.add_record` | 175 | Write one archive record and fold it into the daily summaries. Returns False if a record… |
| · | &nbsp;&nbsp;`ArchiveStore.homeless` | 234 | Fields dropped for want of a column, and how often, since startup. |
| · | &nbsp;&nbsp;`ArchiveStore.occupied` | 238 | {column: (how many readings, when the last one was)}, for the columns that hold anything… |
| · | &nbsp;&nbsp;`ArchiveStore.add_column` | 274 | Give a reading somewhere to live. Returns False if it already has one. WeeWX reads its sc… |
| · | &nbsp;&nbsp;`ArchiveStore.add_records` | 297 | Write many records, touching each day's summaries once. WeeWX reads and rewrites all of a… |
| · | &nbsp;&nbsp;`ArchiveStore.rebuild_day` | 414 | Recompute one day's summaries from the archive table. This is what makes a correction pos… |
| · | &nbsp;&nbsp;`ArchiveStore.days` | 449 | Every archive day that has records, in order. |
| · | &nbsp;&nbsp;`ArchiveStore.set_meta` | 462 | Write one metadata row. The table WeeWX keeps `lastUpdate` in. Drivers use this too: weew… |
| · | &nbsp;&nbsp;`ArchiveStore.get_meta` | 477 |  |

## `src/weewx_evo/db/daily.py`

[Daily summaries](Daily-Summaries) · last changed 2026-08-26 23:56

| | Name | Line | |
|---|---|---|---|
| **C** | `IntervalError` | 23 | A record whose `interval` cannot be turned into a weight. |
| f | `weight_of` | 27 | The weight one archive record carries in a daily summary. WeeWX uses this for daily-summary version 2.0 and u… |
| f | `day_accumulator` | 41 | An accumulator spanning one archive day, starting at `sod_ts`. |
| f | `build` | 47 | Fold archive records into one accumulator per day. Records must arrive in ascending time order -- the same or… |
| f | `read_day` | 83 | Read one day's stored statistics for one observation type. |
| f | `read_records` | 95 | Read archive records in time order, dropping the columns that are NULL. Dropping nulls matters: the accumulat… |

## `src/weewx_evo/db/live.py`

[The live database](Database-Live) · last changed 2026-09-04 09:03

| | Name | Line | |
|---|---|---|---|
| f | `sender_id` | 66 | The stable, reversible id for one driver/hardware-identity pair. |
| f | `sender_parts` | 78 | Decode a canonical sender id, rejecting aliases and bad UTF-8. |
| f | `interval_stop` | 181 | The end of the archive interval a timestamp belongs to. Intervals are half-open at the start, so a packet sta… |
| **C** | `Packet` | 191 | One reading as it arrived, before anything was done to it. |
| · | &nbsp;&nbsp;`Packet.sender_id` | 250 | This packet's canonical sender, including for old constructors. |
| · | &nbsp;&nbsp;`Packet.digest` | 254 | A short hash of the measurements, so a retransmission is not a new packet. |
| · | &nbsp;&nbsp;`Packet.record` | 262 | The packet as an observation record, ready for the accumulator. |
| **C** | `SenderIdentity` | 273 | One sender known to the live journal, with optional display metadata. |
| **C** | `LiveStore` | 302 | The live packet database. |
| · | &nbsp;&nbsp;`LiveStore.__init__` | 305 |  |
| · | &nbsp;&nbsp;`LiveStore.conn` | 376 | This thread's connection, opened on first use. |
| · | &nbsp;&nbsp;`LiveStore.close` | 384 |  |
| · | &nbsp;&nbsp;`LiveStore.add` | 404 | Store one packet. Returns False if it was already there. Storing is idempotent on (driver… |
| · | &nbsp;&nbsp;`LiveStore.add_all` | 497 | Store many packets in one transaction. Returns how many were new. |
| · | &nbsp;&nbsp;`LiveStore.mark_pending` | 503 | Note that the interval containing `ts` needs working out. Marked for every archive rather… |
| · | &nbsp;&nbsp;`LiveStore.clear_pending` | 522 | One archive is done with this interval. The others are not. |
| · | &nbsp;&nbsp;`LiveStore.due` | 529 | Intervals that have ended and can be worked out, oldest first. `grace` holds an interval… |
| · | &nbsp;&nbsp;`LiveStore.packets` | 551 | Every packet in (start, stop], in time order. `with_raw` reads the original upload too. O… |
| · | &nbsp;&nbsp;`LiveStore.forget_raw` | 612 | Drop the raw uploads of packets received before `before`. The packets themselves stay. On… |
| · | &nbsp;&nbsp;`LiveStore.raw_of` | 624 | One packet by its sequence number, with its raw upload if still held. |
| · | &nbsp;&nbsp;`LiveStore.span` | 642 |  |
| · | &nbsp;&nbsp;`LiveStore.count` | 645 |  |
| · | &nbsp;&nbsp;`LiveStore.get_meta` | 648 |  |
| · | &nbsp;&nbsp;`LiveStore.set_meta` | 654 |  |
| · | &nbsp;&nbsp;`LiveStore.senders` | 661 | Every canonical sender observed here, with optional UI label. |
| · | &nbsp;&nbsp;`LiveStore.sync_sender_labels` | 671 | Replace listener-owned display labels without changing any id. The station file is a list… |
| · | &nbsp;&nbsp;`LiveStore.prune` | 699 | Drop packets older than `before`, optionally writing them out first. With `archive_dir` s… |

## `src/weewx_evo/db/schema.py`

[The archive database](Database-Archive) · last changed 2026-08-26 10:57

| | Name | Line | |
|---|---|---|---|
| **C** | `Schema` | 32 | The shape of one WeeWX archive database. |
| · | &nbsp;&nbsp;`Schema.version` | 41 | The daily-summary version. 4.0 is current; anything below needs a patch. See weewx.manage… |
| · | &nbsp;&nbsp;`Schema.has_column` | 49 |  |
| f | `read` | 57 | Read the schema of an existing archive database. |

## `src/weewx_evo/derive.py`

[Derived readings](Derived-Readings) · last changed 2026-09-04 00:46

| | Name | Line | |
|---|---|---|---|
| f | `dewpoint_c` | 139 | Dew point in Celsius, by the Magnus formula WeeWX uses. |
| f | `windchill_c` | 156 | Wind chill, Celsius, from the Environment Canada formula. Only defined below 10 degrees and above 4.8 km/h. O… |
| f | `heatindex_f` | 170 | Heat index, Fahrenheit, Rothfusz with the two adjustments. Below 40 F there is no heat index and the temperat… |
| f | `humidex_c` | 196 | Humidex, Celsius. Below 21 degrees it is the temperature. |
| f | `apptemp_c` | 209 | Apparent temperature, the Australian BOM formula. |
| f | `altimeter_inhg` | 218 | Altimeter setting from station pressure, the aaASOS algorithm. |
| f | `cloudbase_ft` | 226 | Height of the cloud base, feet, from the spread. |
| f | `sun_position` | 242 | The sun's elevation in degrees, and Earth's distance in AU. pyephem when it is installed, and NOAA's algorith… |
| f | `max_solar_rad` | 324 | Clear-sky radiation, W/m2, Ryan-Stolzenbach (MIT, 1972). What a solar sensor would read with no cloud above i… |
| f | `windrun` | 358 | Distance the wind covered, in the same length unit as the speed. Speed times time. The unit follows the speed… |
| f | `delta` | 369 | How much a running total went up by. Three cases that are not errors and must not be treated as one: * No pre… |
| f | `sun_radiation` | 440 | Radiation at the top of the atmosphere, in MJ per square metre per hour. What would arrive with no air in the… |
| f | `longwave_radiation` | 465 | What the ground radiates back to the sky, in MJ per square metre per day. `rs` against `rso` is a measure of… |
| f | `sealevel_pressure_mbar` | 500 | Station pressure reduced to sea level. wview's, by way of WeeWX. What a barometer reads. Without the reductio… |
| f | `station_pressure_mbar` | 515 | Sea-level pressure brought back down to the station. **This one is not WeeWX's.** Theirs goes through Davis's… |
| f | `beaufort_number` | 535 | The Beaufort force for a wind speed, 0 to 12. WeeWX has begun calling this type deprecated in favour of a `be… |
| f | `evapotranspiration_mm` | 553 | Reference evapotranspiration over one hour, in millimetres. How much water a short green crop would use, give… |
| f | `sat_vapor_pressure_mbar` | 629 | The most water vapour the air could hold, in millibars. Magnus, with the coefficients WeeWX uses in `dewpoint… |
| f | `vapor_pressure_mbar` | 640 | What the moisture actually in the air is worth, in millibars. |
| f | `absolute_humidity` | 645 | Grams of water per cubic metre. The number a greenhouse, a cellar or a museum cares about: relative humidity… |
| f | `mixing_ratio` | 658 | Grams of water per kilogram of dry air. Conserved when air rises or is heated, which is why meteorology uses… |
| f | `sunshine_seconds` | 673 | How much of this interval was sunshine. All or nothing per interval, which is what every implementation of th… |
| **C** | `Station` | 703 | What the formulas need to know about where the station is. |
| · | &nbsp;&nbsp;`Station.altitude_ft` | 711 |  |
| **C** | `Deriver` | 718 | Fills in the readings that follow from other readings. Holds one piece of state: the last value of each runni… |
| · | &nbsp;&nbsp;`Deriver.wanted` | 758 | Whether to work this one out for this record. |
| · | &nbsp;&nbsp;`Deriver.apply` | 768 | Add what is missing. The record is modified and returned. Order matters: dew point before… |
| · | &nbsp;&nbsp;`Deriver.forget` | 1049 | Drop what was remembered. The next packet starts from nothing. |
| f | `from_settings` | 1107 | Build one from the resolved configuration. `place` is the archive being written, when there is more than one.… |

## `src/weewx_evo/dumps.py`

[CLI reference](CLI-Reference) · last changed 2026-08-29 17:58

| | Name | Line | |
|---|---|---|---|
| **C** | `Found` | 108 | What a dump turned out to hold, for the command to report. |
| · | &nbsp;&nbsp;`Found.summary` | 120 |  |
| **C** | `Dump` | 273 | One SQL dump, read a statement at a time. Streamed rather than loaded: fifteen years of five-minute records i… |
| · | &nbsp;&nbsp;`Dump.__init__` | 281 |  |
| · | &nbsp;&nbsp;`Dump.read_schema` | 293 | Columns and their types, from the dump's own CREATE TABLE. The one rule again: the schema… |
| · | &nbsp;&nbsp;`Dump.records` | 335 | Every row of the table, as a record. Both dialects from one pass, because a dump does not… |
| f | `inspect` | 483 | What is in a dump, without writing anything. The command somebody runs first. A dump of the wrong table, or o… |
| f | `into` | 513 | Read a dump into an archive. Returns what was done. The daily summaries are built as it goes -- `add_records`… |

## `src/weewx_evo/dumpscsv.py`

[CLI reference](CLI-Reference) · last changed 2026-08-29 18:01

| | Name | Line | |
|---|---|---|---|
| **C** | `Found` | 122 | What a CSV turned out to hold. |
| · | &nbsp;&nbsp;`Found.summary` | 135 |  |
| f | `parse_map` | 212 | `--map` as a dictionary. `"Temperature=outTemp,Humidity=outHumidity"`. A column name can hold a space and a s… |
| f | `inspect` | 367 | What is in a CSV, without writing anything. |
| f | `into` | 386 | Read a CSV into an archive. Returns what was done. Sorted per batch, because `add_records` needs ascending ti… |

## `src/weewx_evo/exports/__init__.py`

[Exports](Exports) · last changed 2026-08-28 20:17

| | Name | Line | |
|---|---|---|---|
| **C** | `Sent` | 49 | What one run of an export did. |
| · | &nbsp;&nbsp;`Sent.ok` | 63 |  |
| · | &nbsp;&nbsp;`Sent.summary` | 66 |  |
| **C** | `ExportError` | 80 | Something that stopped an export before it sent anything. |
| **C** | `Export` | 85 | Files out. |
| · | &nbsp;&nbsp;`Export.send` | 88 | Send `source` to wherever this export sends things. `files` is what changed, when the cal… |
| **C** | `BaseExport` | 113 | Defaults for an export. Only `send` has to be written. |
| · | &nbsp;&nbsp;`BaseExport.send` | 126 |  |
| · | &nbsp;&nbsp;`BaseExport.prepare` | 130 | Put anything the destination needs into the directory first. Today that is `live.php` and… |
| · | &nbsp;&nbsp;`BaseExport.check` | 151 | Try the destination and say what happened, without sending. The admin page offers this as… |
| · | &nbsp;&nbsp;`BaseExport.status` | 160 |  |
| · | &nbsp;&nbsp;`BaseExport.close` | 163 | Release anything held. Optional. |
| **C** | `Registry` | 167 | The exports this installation has. The same shape as the driver registry, and for the same reason: an export… |
| · | &nbsp;&nbsp;`Registry.__init__` | 175 |  |
| · | &nbsp;&nbsp;`Registry.register` | 180 |  |
| · | &nbsp;&nbsp;`Registry.register_factory` | 185 |  |
| · | &nbsp;&nbsp;`Registry.configure` | 188 |  |
| · | &nbsp;&nbsp;`Registry.factory_for` | 200 | The class behind a kind, loading the registry first. A method rather than reaching into `… |
| · | &nbsp;&nbsp;`Registry.get` | 210 |  |
| · | &nbsp;&nbsp;`Registry.known` | 214 |  |
| · | &nbsp;&nbsp;`Registry.names` | 218 |  |
| · | &nbsp;&nbsp;`Registry.kinds` | 222 | The kinds available, as opposed to the ones configured. |
| · | &nbsp;&nbsp;`Registry.load` | 227 | Pull in what is installed. A broken one is reported, never fatal. |
| f | `get` | 260 |  |
| f | `names` | 264 |  |
| f | `kinds` | 268 |  |
| f | `also_option` | 284 | Further feeds this export carries, each with where it lands. A skin is its pages *and* the charts they draw f… |
| f | `live_push_options` | 311 | The "live readings" settings, which every export has the same. One copy, because three exports with three sub… |
| f | `source_for` | 362 | Where an export's files are, from a feed name or a plain directory. A feed is asked where it wrote; a directo… |
| f | `walk` | 383 | Every file to consider, as paths relative to `source`. Directories that should never be uploaded are skipped… |

## `src/weewx_evo/exports/ftp.py`

[Exports](Exports) · last changed 2026-08-28 21:54

| | Name | Line | |
|---|---|---|---|
| **C** | `FtpExport` | 46 | Sends a directory to an FTP server. |
| · | &nbsp;&nbsp;`FtpExport.__init__` | 57 |  |
| · | &nbsp;&nbsp;`FtpExport.send` | 101 |  |
| · | &nbsp;&nbsp;`FtpExport.check` | 159 | Connect, look at the target directory, and say what happened. |
| · | &nbsp;&nbsp;`FtpExport.status` | 182 |  |
| · | &nbsp;&nbsp;`FtpExport.options` | 309 |  |

## `src/weewx_evo/exports/livepush/__init__.py`

[Uploads](Uploads) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| f | `token_for` | 96 | The token for `live.php`, derived from the station's upload token. Same station, same token, always -- so the… |
| f | `script` | 111 | The PHP, as it ships. |
| f | `install` | 116 | Put `live.php` and its token into a directory about to be exported. Returns what it wrote or refreshed, so an… |
| f | `url_for` | 155 | Where the station should post, given where the pages are served. A convenience for the settings page, which k… |
| f | `rendered_units` | 165 | Which units the pages one export publishes are written in. The same three steps the Cheetah feed takes, in th… |

## `src/weewx_evo/exports/local.py`

[Exports](Exports) · last changed 2026-08-28 21:54

| | Name | Line | |
|---|---|---|---|
| **C** | `LocalExport` | 44 | Copies what a feed produced into a directory on this machine. |
| · | &nbsp;&nbsp;`LocalExport.__init__` | 56 |  |
| · | &nbsp;&nbsp;`LocalExport.send` | 109 |  |
| · | &nbsp;&nbsp;`LocalExport.prepare` | 174 | Nothing. A directory this machine serves needs no `live.php`. The script exists to get a… |
| · | &nbsp;&nbsp;`LocalExport.check` | 263 | Whether this can be written to, and what is there now. |
| · | &nbsp;&nbsp;`LocalExport.status` | 287 |  |
| · | &nbsp;&nbsp;`LocalExport.options` | 299 |  |

## `src/weewx_evo/exports/record.py`

[Notifications](Notifications) · last changed 2026-08-29 15:25

| | Name | Line | |
|---|---|---|---|
| f | `key` | 47 |  |
| f | `write` | 51 | Note how one run went. Never raises. Never raises, and that is deliberate: this is a note about an upload, an… |
| f | `read` | 96 | The last run of one export, or None if it has never run here. |
| f | `summary` | 114 | One line for the page, in the words the log uses. The same shape as `Sent.summary()` on purpose: somebody com… |

## `src/weewx_evo/exports/rsync.py`

[Exports](Exports) · last changed 2026-08-28 21:54

| | Name | Line | |
|---|---|---|---|
| **C** | `RsyncExport` | 44 | Sends a directory to a server with rsync over SSH. |
| · | &nbsp;&nbsp;`RsyncExport.__init__` | 56 |  |
| · | &nbsp;&nbsp;`RsyncExport.send` | 97 |  |
| · | &nbsp;&nbsp;`RsyncExport.check` | 141 | Do a dry run and report what would happen. |
| · | &nbsp;&nbsp;`RsyncExport.status` | 173 |  |
| · | &nbsp;&nbsp;`RsyncExport.options` | 260 |  |

## `src/weewx_evo/exports/runner.py`

[Exports](Exports) · last changed 2026-08-28 22:56

| | Name | Line | |
|---|---|---|---|
| **C** | `Scheduled` | 61 | One export, and when it is next due. |
| · | &nbsp;&nbsp;`Scheduled.__init__` | 83 |  |
| · | &nbsp;&nbsp;`Scheduled.trigger` | 142 |  |
| · | &nbsp;&nbsp;`Scheduled.every` | 146 |  |
| · | &nbsp;&nbsp;`Scheduled.feeds` | 150 | Every feed this export waits for, the main one first. |
| · | &nbsp;&nbsp;`Scheduled.due` | 155 | `fired` is what just happened: "record", a feed name, or "". |
| · | &nbsp;&nbsp;`Scheduled.next_run` | 190 | When this is next due on the wall clock, for the loop to wait. Now, until the first turn… |
| · | &nbsp;&nbsp;`Scheduled.run` | 200 | Send, and remember what happened. Never raises. |
| **C** | `Runner` | 248 | Keeps the exports going, one thread each. |
| · | &nbsp;&nbsp;`Runner.__init__` | 251 |  |
| · | &nbsp;&nbsp;`Runner.replace` | 265 | Swap in a new set, after the configuration changed. A method rather than three assignment… |
| · | &nbsp;&nbsp;`Runner.start` | 294 |  |
| · | &nbsp;&nbsp;`Runner.record_written` | 316 | A new archive record landed. Called from the archiver's thread and returns at once: it se… |
| · | &nbsp;&nbsp;`Runner.feed_produced` | 327 | A feed has finished writing. Wake whatever sends it. This is the trigger to prefer where… |
| · | &nbsp;&nbsp;`Runner.stop` | 351 |  |
| · | &nbsp;&nbsp;`Runner.status` | 399 |  |
| f | `named` | 413 | The further feeds an export names, as (feed, sub-path). Written one per line, because that is how every list… |
| f | `also` | 446 | The ones that exist, as (feed, directory, sub-path). A feed nobody has configured is named and left out rathe… |
| f | `build` | 473 | Turn configuration into things the runner can run. Anything that cannot be built is reported and left out. A… |

## `src/weewx_evo/exports/tracker.py`

[Exports](Exports) · last changed 2026-08-26 13:31

| | Name | Line | |
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

[Feeds](Feeds) · last changed 2026-09-04 00:35

| | Name | Line | |
|---|---|---|---|
| **C** | `Runner` | 40 | Produces feeds, in order, when whatever each one waits for happens. Three things can set a feed going, and un… |
| · | &nbsp;&nbsp;`Runner.__init__` | 49 |  |
| · | &nbsp;&nbsp;`Runner.record_written` | 100 | Called by the archiver. Notes which series, and returns. `archive` is which series wrote.… |
| · | &nbsp;&nbsp;`Runner.packet_stored` | 122 | Called by the listener for every reading that lands. Only wakes feeds that asked for it.… |
| · | &nbsp;&nbsp;`Runner.replace` | 132 | Swap in a new set, after the configuration changed. A feed deleted on the settings page k… |
| · | &nbsp;&nbsp;`Runner.start` | 169 |  |
| · | &nbsp;&nbsp;`Runner.stop` | 174 |  |
| · | &nbsp;&nbsp;`Runner.archive_for` | 232 | Which series this feed reads, or empty when none is implicit. |
| · | &nbsp;&nbsp;`Runner.path_for` | 236 | The exact file behind that feed's series, if it still exists. An unknown name is never re… |
| · | &nbsp;&nbsp;`Runner.due_now` | 245 | Whether this feed runs on this pass. |
| · | &nbsp;&nbsp;`Runner.run_once` | 267 | The feeds this pass is for, in order. Returns what happened. `because` says what woke the… |
| · | &nbsp;&nbsp;`Runner.status` | 351 |  |

## `src/weewx_evo/feeds/__init__.py`

[Feeds](Feeds) · last changed 2026-09-04 00:50

| | Name | Line | |
|---|---|---|---|
| **C** | `Produced` | 89 | What one run of a feed made. The list of files matters to the exports: an export that knows which files chang… |
| · | &nbsp;&nbsp;`Produced.count` | 104 |  |
| f | `kinds` | 108 | The kinds of feed that can be configured. A kind is what a feed *is* -- JSON, a diagnostic page, a Cheetah sk… |
| f | `names` | 121 | Kept for anything still asking. See `kinds`. |
| f | `describe` | 126 | One line about a kind of feed, for a form that offers it. |
| f | `factory_for` | 132 | The class behind a kind, loading the registry first. |
| f | `load` | 163 | Pull in the feeds. A broken one is reported, never fatal. Same arrangement as the drivers: one feed that will… |
| f | `register` | 195 |  |
| f | `get` | 201 |  |
| **C** | `Feed` | 207 | Readings out, as files. |
| · | &nbsp;&nbsp;`Feed.produce` | 213 | Write this feed's files into `into` and say which they are. `archive` is a read-only view… |
| f | `archive_names` | 223 | The archives a feed can read from, for the settings page. From `archives.toml`, which is where an archive is… |
| f | `default_archive_name` | 245 | The implicit place while this schema is being built. A sole custom-named place is just as unambiguous as ``de… |
| f | `schedule_options` | 323 | When a feed runs and what it reads. Added to every feed's page. Separate from a feed's own settings because i… |

## `src/weewx_evo/feeds/cheetah/__init__.py`

[Feeds](Feeds) · last changed 2026-09-04 00:37

| | Name | Line | |
|---|---|---|---|
| **C** | `CheetahFeed` | 79 | Renders one skin. |
| · | &nbsp;&nbsp;`CheetahFeed.__init__` | 84 |  |
| · | &nbsp;&nbsp;`CheetahFeed.narrow` | 219 | Keep only the places this instance was told to show. In the operator's order, and this fe… |
| · | &nbsp;&nbsp;`CheetahFeed.several` | 261 | Whether this feed shows more than one place. The gate for every difference in this file,… |
| · | &nbsp;&nbsp;`CheetahFeed.archive_files` | 273 |  |
| · | &nbsp;&nbsp;`CheetahFeed.produce` | 278 | Every place this feed shows, one pass each, into one directory. A loop around what this a… |
| · | &nbsp;&nbsp;`CheetahFeed.report` | 622 | How many tags went unanswered across every series, and which. Worded exactly as `Tags.rep… |
| · | &nbsp;&nbsp;`CheetahFeed.skin_options` | 1501 | What the chosen skin lets an operator set, for the feed's page. `settings` is this feed's… |
| · | &nbsp;&nbsp;`CheetahFeed.options` | 1520 |  |
| f | `mqtt_uploads` | 1647 | The configured MQTT uploads, by name. |
| f | `from_settings` | 2205 | Build the feed, and the tag layer it renders through. The tags are built here rather than handed in because t… |
| f | `skin_options` | 2307 | What the named skin lets an operator set, or nothing. A skin of ours ships an `options.py` next to its templa… |
| f | `forecast_default_archive` | 2524 | What a series is called when nobody said, from the store that owns it. |

## `src/weewx_evo/feeds/diagnostic/__init__.py`

[Feeds](Feeds) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| **C** | `Diagnostic` | 51 | Renders every series file it finds, with its faults listed. |
| · | &nbsp;&nbsp;`Diagnostic.__init__` | 56 |  |
| · | &nbsp;&nbsp;`Diagnostic.produce` | 66 |  |
| · | &nbsp;&nbsp;`Diagnostic.read` | 90 | Every JSON file in the source directory, examined. |
| · | &nbsp;&nbsp;`Diagnostic.render` | 209 |  |
| · | &nbsp;&nbsp;`Diagnostic.options` | 308 | The settings one of these offers. Bare names; the page prefixes. |
| f | `from_settings` | 362 | Build the page from the configuration. `prefix` names the configured feed. Two of them can draw two different… |

## `src/weewx_evo/feeds/imagegenerator/__init__.py`

[Plots](Plots) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| **C** | `ImageGenerator` | 60 | Turns plot definitions into PNG files. |
| · | &nbsp;&nbsp;`ImageGenerator.__init__` | 67 |  |
| · | &nbsp;&nbsp;`ImageGenerator.produce` | 137 | Draw every chart. The other series are opened for this run only. |
| · | &nbsp;&nbsp;`ImageGenerator.build` | 236 | One chart as an image, or None if there is nothing in it. `reader` and `place` are which… |
| · | &nbsp;&nbsp;`ImageGenerator.draw` | 265 |  |
| · | &nbsp;&nbsp;`ImageGenerator.options` | 656 |  |
| f | `from_settings` | 721 | Build the generator from the configuration. `prefix` names the configured feed, so two of them can be set up… |

## `src/weewx_evo/feeds/imagegenerator/canvas.py`

[Plots](Plots) · last changed 2026-08-26 23:47

| | Name | Line | |
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

[Plots](Plots) · last changed 2026-08-26 23:56

| | Name | Line | |
|---|---|---|---|
| **C** | `Theme` | 62 | Every colour and measurement one chart is drawn with. Sizes are in logical pixels. The renderer multiplies th… |
| · | &nbsp;&nbsp;`Theme.color` | 124 |  |
| · | &nbsp;&nbsp;`Theme.scaled` | 127 | The same theme in a bigger coordinate system. Everything with a size grows; nothing with… |
| f | `resolve` | 154 | Find a real typeface, once, and remember where it was. Looked up here rather than at every draw: a hundred ch… |
| f | `rgba` | 197 | `#rrggbb` and an opacity as the four numbers Pillow wants. A short `#rgb` is accepted because skins are full… |

## `src/weewx_evo/feeds/jsongenerator/__init__.py`

[Feeds](Feeds) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| **C** | `JSONGenerator` | 96 | Turns plot definitions into JSON files. |
| · | &nbsp;&nbsp;`JSONGenerator.__init__` | 103 |  |
| · | &nbsp;&nbsp;`JSONGenerator.produce` | 169 | Write every plot. The other series are opened for this run only. |
| · | &nbsp;&nbsp;`JSONGenerator.build` | 404 | One plot's payload, or None if there is nothing in it. The numbers come from `chartdata`,… |
| · | &nbsp;&nbsp;`JSONGenerator.options` | 439 | The settings one of these offers. Bare names, and the page supplies the prefix -- the sam… |
| f | `from_settings` | 686 | Build the generator from the configuration. `prefix` names the configured feed, so two of them can be set up… |

## `src/weewx_evo/feeds/realtime/__init__.py`

[Feeds](Feeds) · last changed 2026-08-27 10:35

| | Name | Line | |
|---|---|---|---|
| **C** | `RealtimeFeed` | 66 | Writes `realtime.txt`, and `wxnow.txt` beside it. |
| · | &nbsp;&nbsp;`RealtimeFeed.__init__` | 77 |  |
| · | &nbsp;&nbsp;`RealtimeFeed.line` | 110 | One `realtime.txt` line. The first two fields are the date and the time, in Cumulus's own… |
| · | &nbsp;&nbsp;`RealtimeFeed.wxnow_line` | 146 | `wxnow.txt`, which every APRS daemon reads. Fixed width, US customary throughout, and --… |
| · | &nbsp;&nbsp;`RealtimeFeed.produce` | 180 |  |
| · | &nbsp;&nbsp;`RealtimeFeed.options` | 220 |  |

## `src/weewx_evo/forecast/__init__.py`

[Forecast](Forecast) · last changed 2026-09-04 00:38

| | Name | Line | |
|---|---|---|---|
| **C** | `Place` | 67 | Where the forecast is for. |
| **C** | `Moment` | 81 | The forecast for one hour. Field names are the archive's, deliberately: `outTemp` here means the same thing i… |
| · | &nbsp;&nbsp;`Moment.values` | 117 | The readings that are actually present, by name. |
| **C** | `Day` | 124 | The forecast for one day, as a source summarised it. Not derived from the hours. A source's own daily summary… |
| · | &nbsp;&nbsp;`Day.values` | 150 |  |
| **C** | `Warning` | 156 | One official warning. Modelled on CAP, because every European and American warning service publishes CAP and… |
| · | &nbsp;&nbsp;`Warning.rank` | 187 | How serious, as a number, so warnings can be sorted. |
| **C** | `Reading` | 194 | Everything one source returned in one fetch. |
| · | &nbsp;&nbsp;`Reading.empty` | 209 |  |
| · | &nbsp;&nbsp;`Reading.summary` | 212 |  |
| f | `place_options` | 227 | Which series a forecast is for. Added to every source's page. Separate from a source's own settings because i… |
| f | `shared_store_path` | 260 | The installation's one forecast store, beside its configuration. The rows carry their archive name, so this i… |
| f | `store_path` | 274 | Compatibility fallback: a forecast beside one archive file. New runtime callers use :func:`shared_store_path`… |
| **C** | `ForecastError` | 292 | Something that stopped a source from answering. |
| · | &nbsp;&nbsp;`ForecastError.__init__` | 295 |  |
| **C** | `Source` | 301 | Somewhere a forecast comes from. |
| · | &nbsp;&nbsp;`Source.fetch` | 304 |  |
| **C** | `BaseSource` | 308 | Defaults for a source. Only `fetch` has to be written. |
| · | &nbsp;&nbsp;`BaseSource.fetch` | 321 |  |
| · | &nbsp;&nbsp;`BaseSource.check` | 324 | Fetch once and say what came back, for the settings page. |
| · | &nbsp;&nbsp;`BaseSource.close` | 334 | Release anything held. Optional. |
| f | `parse_xml` | 345 | Parse XML from a weather service, with a size limit in front. `xml.etree` rather than `defusedxml`, which is… |
| **C** | `Registry` | 387 | The forecast sources this installation has. |
| · | &nbsp;&nbsp;`Registry.__init__` | 390 |  |
| · | &nbsp;&nbsp;`Registry.register_factory` | 394 |  |
| · | &nbsp;&nbsp;`Registry.factory_for` | 397 |  |
| · | &nbsp;&nbsp;`Registry.kinds` | 401 |  |
| · | &nbsp;&nbsp;`Registry.describe` | 405 |  |
| · | &nbsp;&nbsp;`Registry.load` | 409 |  |
| f | `kinds` | 435 |  |
| f | `describe` | 439 |  |

## `src/weewx_evo/forecast/codes.py`

[Forecast](Forecast) · last changed 2026-08-27 10:33

| | Name | Line | |
|---|---|---|---|
| f | `text` | 66 | What to call this code, in the language the station is set to. |
| f | `symbol` | 78 | A name for the picture, not the picture itself. |
| f | `is_wet` | 100 | Whether this code means something is falling out of the sky. |
| f | `is_severe` | 105 | Thunder, hail, freezing, or heavy anything. |

## `src/weewx_evo/forecast/dwd.py`

[Forecast](Forecast) · last changed 2026-08-27 10:33

| | Name | Line | |
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

[Forecast](Forecast) · last changed 2026-08-27 10:33

| | Name | Line | |
|---|---|---|---|
| f | `parse_time` | 68 | A CAP timestamp as unix time. Zero when absent or unparseable. CAP writes `2026-08-27T06:00:00+00:00`, and so… |
| **C** | `MeteoAlarm` | 91 | Warnings from meteoalarm.org. |
| · | &nbsp;&nbsp;`MeteoAlarm.__init__` | 102 |  |
| · | &nbsp;&nbsp;`MeteoAlarm.fetch` | 133 |  |
| · | &nbsp;&nbsp;`MeteoAlarm.entries` | 144 | Every warning in the feed, before any filtering. Public because `check` uses it to show w… |
| · | &nbsp;&nbsp;`MeteoAlarm.check` | 191 | Fetch, and list the regions -- which is how somebody finds theirs. |
| · | &nbsp;&nbsp;`MeteoAlarm.options` | 217 |  |

## `src/weewx_evo/forecast/nws.py`

[Forecast](Forecast) · last changed 2026-08-27 10:33

| | Name | Line | |
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

[Forecast](Forecast) · last changed 2026-08-27 19:38

| | Name | Line | |
|---|---|---|---|
| **C** | `OpenMeteo` | 94 | A forecast from open-meteo.com. |
| · | &nbsp;&nbsp;`OpenMeteo.__init__` | 105 |  |
| · | &nbsp;&nbsp;`OpenMeteo.path` | 117 |  |
| · | &nbsp;&nbsp;`OpenMeteo.fetch` | 144 |  |
| · | &nbsp;&nbsp;`OpenMeteo.read` | 165 | Turn one response into hours and days. Separate from `fetch` so a test can hand it a save… |
| · | &nbsp;&nbsp;`OpenMeteo.check` | 237 |  |
| · | &nbsp;&nbsp;`OpenMeteo.options` | 254 |  |

## `src/weewx_evo/forecast/runner.py`

[Forecast](Forecast) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| **C** | `Scheduled` | 53 | One source, and when it is next due. |
| · | &nbsp;&nbsp;`Scheduled.__init__` | 73 |  |
| · | &nbsp;&nbsp;`Scheduled.every` | 105 |  |
| · | &nbsp;&nbsp;`Scheduled.due` | 108 |  |
| · | &nbsp;&nbsp;`Scheduled.next_run` | 122 |  |
| · | &nbsp;&nbsp;`Scheduled.run` | 125 | Fetch and store. Never raises. |
| **C** | `Runner` | 184 | Keeps the forecast sources going, one thread each. |
| · | &nbsp;&nbsp;`Runner.__init__` | 187 |  |
| · | &nbsp;&nbsp;`Runner.start` | 196 |  |
| · | &nbsp;&nbsp;`Runner.stop` | 205 |  |
| · | &nbsp;&nbsp;`Runner.replace` | 217 | Swap in a new set, after the configuration changed. |
| · | &nbsp;&nbsp;`Runner.status` | 283 |  |
| f | `build` | 297 | Turn configuration into things the runner can run. Anything that cannot be built is reported and left out. A… |

## `src/weewx_evo/forecast/store.py`

[Forecast](Forecast) · last changed 2026-09-04 00:33

| | Name | Line | |
|---|---|---|---|
| **C** | `ForecastStore` | 73 | The forecast database, open for reading and writing. |
| · | &nbsp;&nbsp;`ForecastStore.__init__` | 76 |  |
| · | &nbsp;&nbsp;`ForecastStore.conn` | 87 | This thread's connection, opened on first use. The poller writes on its own thread and a… |
| · | &nbsp;&nbsp;`ForecastStore.close` | 106 |  |
| · | &nbsp;&nbsp;`ForecastStore.store` | 249 | Replace everything this source had, for this series, with what it just returned. `archive… |
| · | &nbsp;&nbsp;`ForecastStore.forget` | 328 | Everything one source had for one series, gone. |
| · | &nbsp;&nbsp;`ForecastStore.keep` | 337 | Everything not in `known`, gone. Pairs of (archive, source). Two things end up here. A so… |
| · | &nbsp;&nbsp;`ForecastStore.archives` | 366 | Which series this file holds a forecast for. |
| · | &nbsp;&nbsp;`ForecastStore.prune` | 371 | Drop hours and warnings that are in the past. A forecast is only ever about the future, s… |
| · | &nbsp;&nbsp;`ForecastStore.sources` | 390 |  |
| · | &nbsp;&nbsp;`ForecastStore.run` | 395 | When this source last answered for this series, and with how much. |
| · | &nbsp;&nbsp;`ForecastStore.hours` | 405 | The hourly forecast for one series, in time order. |
| · | &nbsp;&nbsp;`ForecastStore.days` | 414 |  |
| · | &nbsp;&nbsp;`ForecastStore.warnings` | 422 | Warnings, most severe first. `active_at` keeps only what covers that instant. A warning t… |

## `src/weewx_evo/forecast/tags.py`

[Forecast](Forecast) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| **C** | `Entry` | 53 | One hour or one day, as a template sees it. Attribute lookup does the binding, the same way the rest of the t… |
| · | &nbsp;&nbsp;`Entry.__init__` | 64 |  |
| · | &nbsp;&nbsp;`Entry.hours` | 75 | The hours inside this day, one entry per `step` of them. What a page does with it: seven… |
| · | &nbsp;&nbsp;`Entry.dateTime` | 100 |  |
| · | &nbsp;&nbsp;`Entry.code` | 105 | The raw WMO code, for a template that wants to switch on it. |
| · | &nbsp;&nbsp;`Entry.text` | 110 | What the weather is doing, in the station's language. |
| · | &nbsp;&nbsp;`Entry.symbol` | 115 | A name for the picture, not the picture. Which file that is belongs to whoever draws the… |
| · | &nbsp;&nbsp;`Entry.wet` | 125 |  |
| · | &nbsp;&nbsp;`Entry.severe` | 129 |  |
| **C** | `WarningTag` | 228 | One official warning, as a template sees it. |
| · | &nbsp;&nbsp;`WarningTag.__init__` | 233 |  |
| · | &nbsp;&nbsp;`WarningTag.starts` | 238 |  |
| · | &nbsp;&nbsp;`WarningTag.ends` | 243 |  |
| · | &nbsp;&nbsp;`WarningTag.active` | 248 | Whether it covers this moment. A warning that has not started is real and worth showing -… |
| **C** | `SourceTag` | 272 | One forecast source. `$forecast.ahead`, or `$forecast` for all of them. |
| · | &nbsp;&nbsp;`SourceTag.__init__` | 277 |  |
| · | &nbsp;&nbsp;`SourceTag.hours` | 296 | From this hour forward. The past is not a forecast. |
| · | &nbsp;&nbsp;`SourceTag.days` | 303 | From today forward, today first. |
| · | &nbsp;&nbsp;`SourceTag.every` | 316 | From this hour forward, one entry per `step` hours. |
| · | &nbsp;&nbsp;`SourceTag.between` | 320 | The hours in a span, one entry per `step` of them. |
| · | &nbsp;&nbsp;`SourceTag.now` | 341 | The hour we are in. The hour whose stamp is at or just before now -- not the nearest, whi… |
| · | &nbsp;&nbsp;`SourceTag.today` | 360 |  |
| · | &nbsp;&nbsp;`SourceTag.tomorrow` | 365 |  |
| · | &nbsp;&nbsp;`SourceTag.warnings` | 379 | Every warning stored, worst first. |
| · | &nbsp;&nbsp;`SourceTag.warning` | 389 | The worst one, for a page with room for a single banner. |
| · | &nbsp;&nbsp;`SourceTag.active_warnings` | 395 | Only what covers this moment. |
| · | &nbsp;&nbsp;`SourceTag.updated` | 407 | When the source last answered. Which is not when the model ran -- see `issued`. A page th… |
| · | &nbsp;&nbsp;`SourceTag.issued` | 421 | When the model behind this forecast actually ran. |
| · | &nbsp;&nbsp;`SourceTag.exists` | 430 |  |
| · | &nbsp;&nbsp;`SourceTag.sources` | 434 |  |
| f | `install` | 489 | Give a `Tags` object its `$forecast`, for one measurement series. Called by whatever built the tags and knows… |

## `src/weewx_evo/grafana/__init__.py`

[Grafana](Grafana) · last changed 2026-08-29 17:03

| | Name | Line | |
|---|---|---|---|
| **C** | `Server` | 63 | One InfluxDB, with the locations that write into it. |
| · | &nbsp;&nbsp;`Server.uid` | 85 | A stable identifier. Stable is the requirement, not pretty. A dashboard refers to its dat… |
| · | &nbsp;&nbsp;`Server.name` | 96 |  |
| · | &nbsp;&nbsp;`Server.reference` | 99 |  |
| f | `servers_from` | 103 | The InfluxDB servers among the configured uploads. Grouped by where they point. Two uploads writing different… |
| f | `datasource_yaml` | 147 | The datasource provisioning file. Hand-written YAML rather than a library: this is four keys deep, the core h… |
| f | `provider_yaml` | 186 | Tells Grafana where the dashboard files are. |
| **C** | `Written` | 214 | What a provisioning run did, so the command can report it. |
| · | &nbsp;&nbsp;`Written.summary` | 223 |  |
| f | `provision` | 229 | Write everything Grafana needs into `out`. Nothing is started and nothing is asked of Grafana: these are file… |
| f | `stamp` | 330 | A line for the generated dashboards, so their origin is on the page. |

## `src/weewx_evo/grafana/dashboards.py`

[Grafana](Grafana) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| f | `now` | 151 | Is everything alright. The screen on the wall. The top row is one tile per location, laid out by Grafana's `r… |
| f | `location` | 181 | One station, in full. The page somebody keeps open. |
| f | `compare` | 224 | One reading, every location. The reason Grafana is here at all. A rendered page belongs to one archive, so th… |
| f | `charts` | 251 | Every plot in `plots.toml`, one dashboard per span. The set is generous on purpose -- a chart for a sensor th… |
| f | `operations` | 299 | Who has stopped talking, and what the batteries are doing. Deliberately narrow, for the same reason `watchdog… |
| f | `forecast` | 336 | What is coming, beside what has been. Its own dashboard rather than a row on the location one. A forecast is… |
| f | `all_of` | 392 | Every dashboard for one server, by file name. |

## `src/weewx_evo/grafana/icons.py`

[Grafana](Grafana) · last changed 2026-08-29 17:10

| | Name | Line | |
|---|---|---|---|
| f | `file_for` | 113 | The file this symbol draws as, or the unknown one. |
| f | `url_for` | 118 | What a panel puts in a cell to get this picture. |
| f | `name_for` | 123 | The flat filename, because the copy has no subdirectories. `forecast/CL.svg` and `moon.svg` come from two pla… |
| f | `coloured` | 133 | The same SVG with a colour on it. On the root element rather than each shape. Carbon's files carry a `.cls-1… |
| f | `written` | 148 | Copy every icon into `out`, coloured. Returns what was written. One file per symbol rather than per source fi… |
| f | `mappings` | 171 | Grafana value mappings from a WMO code to a picture and a word. One entry per code the core knows, and Grafan… |
| f | `words` | 194 | The same codes mapped to what to call them, for a text cell. |

## `src/weewx_evo/grafana/panels.py`

[Grafana](Grafana) · last changed 2026-08-29 17:03

| | Name | Line | |
|---|---|---|---|
| f | `unit_for` | 74 | What a panel's axis should say, in Grafana's language. |
| f | `grid` | 86 |  |
| f | `timeseries` | 122 | One chart. `readings` is (obs, aggregate, label), first one leads. The first reading decides the axis, the un… |
| f | `panel` | 188 | One plot from `plots.toml`, as a panel. A plot's own colours are kept only where a single location is drawn.… |
| f | `now` | 248 | The reading as it stands, with its own last day behind it. The number is what somebody came for; the sparklin… |
| f | `row` | 298 | A heading. Collapsed rows are how a long dashboard stays scannable. Grafana keeps a collapsed row's panels *i… |
| f | `text` | 316 | A note on the dashboard. Used to say what generated it, and when. |
| f | `stat` | 327 | A single number from a query written elsewhere. For operations. |
| f | `forecast_week` | 358 | The days ahead, as a table with a picture per row. A table rather than a row of stat panels. Seven stats are… |
| f | `forecast_line` | 444 | One reading measured and forecast, on one axis. Two targets in one panel, which is the whole reason both live… |

## `src/weewx_evo/grafana/query_influx.py`

[Grafana](Grafana) · last changed 2026-08-29 17:02

| | Name | Line | |
|---|---|---|---|
| f | `escape` | 79 | A string inside a Flux literal. Flux takes double quotes and backslash escapes. A location called `Kirchdorf… |
| f | `intervals_in` | 88 | The distinct archive intervals in a database, oldest usage first. Measured rather than assumed. One interval… |
| f | `plain` | 130 | One reading, aggregated the ordinary way. |
| f | `weighted` | 142 | A mean weighted by `interval`, which is what this project computes. Only for a database whose archive interva… |
| f | `for_line` | 199 | The query for one line of a plot. `weight` comes from the archive, not from an opinion: see `intervals_in`. A… |
| f | `last_seen` | 213 | How long ago each location last wrote anything. The one operational question that needs no `/metrics` endpoin… |
| f | `locations` | 233 | The locations there are, for a dashboard variable. Read from the data rather than written into the dashboard:… |
| f | `forecast_days` | 258 | One row per day, the named fields side by side. `pivot` rather than several queries joined in the panel: a ta… |
| f | `forecast_hours` | 294 | One reading over the coming hours, as a line. Drawn beside the measured one on the same axis, which is the wh… |
| f | `forecast_sources` | 323 | Which forecast sources have written, for a dashboard variable. |

## `src/weewx_evo/grafana/style.py`

[Grafana](Grafana) · last changed 2026-08-29 14:34

| | Name | Line | |
|---|---|---|---|
| f | `group_style` | 76 | The drawing rules for one unit group. See the module docstring. |
| f | `stat_thresholds` | 151 | The colour of one figure, in the unit the figure is printed in. Converted rather than assumed: the same scale… |
| f | `for_obs` | 172 | Everything a panel needs to know about drawing one reading. |
| f | `axis_for` | 181 | Extra axis settings a reading needs beyond a min and a max. |
| f | `field_config` | 190 | A Grafana `fieldConfig.defaults` for one reading, fully dressed. |
| f | `describe` | 229 | The line under a panel's title, in the little `i`. Says what is measured and in what -- the two things somebo… |

## `src/weewx_evo/grafana/words.py`

[Grafana](Grafana) · last changed 2026-08-29 17:02

| | Name | Line | |
|---|---|---|---|
| **C** | `Words` | 89 | The dashboard vocabulary for one language. A mapping rather than a function so a caller reads `w.now` instead… |
| · | &nbsp;&nbsp;`Words.__init__` | 99 |  |
| · | &nbsp;&nbsp;`Words.obs` | 119 | A reading's name, translated. The commonest word on a dashboard. |
| · | &nbsp;&nbsp;`Words.span` | 124 | A chart span, translated where this language has the word. |
| · | &nbsp;&nbsp;`Words.title` | 128 | A dashboard title: the product, then what this one answers. |

## `src/weewx_evo/ingest/drivers.py`

[Drivers](Drivers) · last changed 2026-09-04 13:39

| | Name | Line | |
|---|---|---|---|
| **C** | `Driver` | 67 | Bytes in, finished packets out. |
| · | &nbsp;&nbsp;`Driver.packets` | 70 | Turn one upload into packets. `meta` carries `received` (arrival time, unix) and `source`… |
| · | &nbsp;&nbsp;`Driver.dialect_spec` | 83 | Describe a dialect using JSON data only. Optional. |
| **C** | `BaseDriver` | 88 | A driver that only needs to parse. Defaults for everything else. |
| · | &nbsp;&nbsp;`BaseDriver.packets` | 94 |  |
| · | &nbsp;&nbsp;`BaseDriver.claims` | 97 | How sure this driver is that the upload is its protocol. Asked only when the path did not… |
| · | &nbsp;&nbsp;`BaseDriver.dialect_spec` | 123 | A serializable account of `dialect`, or None for WeeWX names. Called by the listener, whi… |
| · | &nbsp;&nbsp;`BaseDriver.status` | 133 | Whatever the driver wants reported at /status. Optional. |
| · | &nbsp;&nbsp;`BaseDriver.start` | 137 | Begin whatever this driver runs on its own. Optional. For hardware with nowhere to type a… |
| · | &nbsp;&nbsp;`BaseDriver.close` | 170 | Release anything held, and stop anything `start` began. Optional. |
| · | &nbsp;&nbsp;`BaseDriver.place` | 173 | Propose names for the listener's settings page. Optional. This compatibility hook runs on… |
| f | `valid_dialect_name` | 213 | Whether a driver-supplied dialect is safe to retain and diagnose. |
| **C** | `DialectSpec` | 220 | A driver's vocabulary in the only form the archiver accepts. Every value is a JSON primitive, list or object.… |
| · | &nbsp;&nbsp;`DialectSpec.from_dict` | 298 |  |
| · | &nbsp;&nbsp;`DialectSpec.as_dict` | 316 | A stable object containing JSON values and nothing executable. |
| **C** | `Placed` | 359 | One packet's readings, in archive column names. |
| f | `dialect_spec_of` | 373 | The validated JSON description to persist beside one raw packet. A driver may put one on the packet itself or… |
| f | `place_with` | 407 | Ask a driver for listener-side proposals, or None if it cannot. This must stay out of the archive path: calli… |
| **C** | `Setup` | 428 | How somebody points a console at this driver. What the Senders page needs in order to offer a piece of hardwa… |
| · | &nbsp;&nbsp;`Setup.tellable` | 476 | Whether this hardware can be told where to upload. |
| f | `setup_of` | 481 | How to point hardware at this driver, or None if it does not say. Optional, like `status` and `unit_groups`.… |
| **C** | `Step` | 503 | One stage of getting a piece of hardware recording here. A `Setup` says what somebody types into a console. T… |
| f | `option_names` | 537 | Every setting this driver declares, in the order it declares them. |
| f | `steps_of` | 557 | How this driver is set up, guided. Its own answer, or one derived. Derived rather than required, for the reas… |
| f | `response_of` | 606 | What to answer an upload to this driver with. |
| f | `status_of` | 611 |  |
| f | `groups_of` | 622 | Which unit group each of this driver's fields belongs to. Optional, like `status`. A driver that reports noth… |
| **C** | `Registry` | 690 | The drivers this installation has. Instances, not classes: a driver holds parser configuration and protocol s… |
| · | &nbsp;&nbsp;`Registry.__init__` | 698 |  |
| · | &nbsp;&nbsp;`Registry.register` | 704 |  |
| · | &nbsp;&nbsp;`Registry.register_factory` | 711 | Register something to be built when its configuration is known. `aliases` are other names… |
| · | &nbsp;&nbsp;`Registry.configure` | 725 | Build a registered factory with its options, and install the result. |
| · | &nbsp;&nbsp;`Registry.get` | 741 |  |
| · | &nbsp;&nbsp;`Registry.known` | 745 |  |
| · | &nbsp;&nbsp;`Registry.names` | 749 |  |
| · | &nbsp;&nbsp;`Registry.canonical_names` | 753 | Names that are not an alias of another driver. Configuring an alias would build a second… |
| · | &nbsp;&nbsp;`Registry.aliases_of` | 763 |  |
| · | &nbsp;&nbsp;`Registry.claimant` | 766 | Which driver recognises this upload, or None. Canonical names only and sorted, so two dri… |
| · | &nbsp;&nbsp;`Registry.unit_groups` | 793 | What every driver here says about its own fields, in one table. Canonical names only: an… |
| · | &nbsp;&nbsp;`Registry.close` | 810 |  |
| · | &nbsp;&nbsp;`Registry.load` | 819 | Pull in what is installed. A broken plugin is reported, never fatal. One package failing… |
| f | `register` | 861 |  |
| f | `get` | 865 |  |
| f | `known` | 869 |  |
| f | `names` | 873 |  |

## `src/weewx_evo/ingest/envelope.py`

[Drivers](Drivers) · last changed 2026-09-03 23:25

| | Name | Line | |
|---|---|---|---|
| **C** | `EnvelopeDriver` | 29 | Reads the envelope. The only driver that ships in the core. |
| · | &nbsp;&nbsp;`EnvelopeDriver.setup` | 33 | One address and one name, which is the whole of the contract. The identity is handed out… |
| · | &nbsp;&nbsp;`EnvelopeDriver.packets` | 59 |  |

## `src/weewx_evo/ingest/listener.py`

[Listener](Ingest-Listener) · last changed 2026-09-04 13:15

| | Name | Line | |
|---|---|---|---|
| **C** | `Ingest` | 69 | What the listener does with an upload once it has one. Kept separate from the transports so the same object s… |
| · | &nbsp;&nbsp;`Ingest.__init__` | 76 |  |
| · | &nbsp;&nbsp;`Ingest.authorised` | 146 | Whether this upload may be recorded. Three ways, one of them not a token. The token is a… |
| · | &nbsp;&nbsp;`Ingest.own_network` | 182 | Whether this address could be a console on the same network as us. Not `self.access`, whi… |
| · | &nbsp;&nbsp;`Ingest.takes_without_token` | 202 | Which driver may take this upload without one. Empty for none. Three protocols here can p… |
| · | &nbsp;&nbsp;`Ingest.driver_for` | 247 | Which driver reads this upload. The path first, because a console that can be told one ha… |
| · | &nbsp;&nbsp;`Ingest.submit` | 276 | Take one upload. Returns (packets stored, reason, what to answer with). The response come… |
| · | &nbsp;&nbsp;`Ingest.begin` | 372 | Let every driver start whatever it runs on its own. Hardware with nowhere to type an addr… |
| · | &nbsp;&nbsp;`Ingest.finish` | 399 | Stop what `begin` started. Safe to call without it. |
| · | &nbsp;&nbsp;`Ingest.fetched` | 410 | One answer a driver asked for, stored as though it had arrived. The same door an upload c… |
| · | &nbsp;&nbsp;`Ingest.status` | 595 |  |
| **C** | `HttpListener` | 869 | The HTTP half. Threaded, because a slow console must not block the others. |
| · | &nbsp;&nbsp;`HttpListener.__init__` | 872 |  |
| · | &nbsp;&nbsp;`HttpListener.serve_forever` | 878 |  |
| · | &nbsp;&nbsp;`HttpListener.start` | 882 |  |
| · | &nbsp;&nbsp;`HttpListener.stop` | 887 |  |
| **C** | `UdpListener` | 918 | The UDP half, for hardware that broadcasts rather than posts. |
| · | &nbsp;&nbsp;`UdpListener.__init__` | 921 |  |
| · | &nbsp;&nbsp;`UdpListener.serve_forever` | 929 |  |
| · | &nbsp;&nbsp;`UdpListener.start` | 933 |  |
| · | &nbsp;&nbsp;`UdpListener.stop` | 938 |  |
| f | `push` | 943 | Send packets to a listener. This is how a pull driver delivers. Going over the loopback rather than writing t… |
| f | `resolve_bind` | 983 | Turn a bind address into something to print. Cosmetic only. |

## `src/weewx_evo/ingest/mqttsub.py`

[MQTT](MQTT) · last changed 2026-09-04 00:40

| | Name | Line | |
|---|---|---|---|
| **C** | `Subscription` | 86 | One broker, one map, delivering packets. Not a driver class in `ingest/plugins/`: those are parsers, and the… |
| · | &nbsp;&nbsp;`Subscription.__init__` | 94 |  |
| · | &nbsp;&nbsp;`Subscription.fields` | 140 | What one message says, as archive field names. The topic is tried first: a map naming `ho… |
| · | &nbsp;&nbsp;`Subscription.take` | 218 | One message in. Held until the bundle window closes. |
| · | &nbsp;&nbsp;`Subscription.due` | 228 | Whether what is held should go out. |
| · | &nbsp;&nbsp;`Subscription.flush` | 235 | Send what is held, as one packet. None if there was nothing. |
| · | &nbsp;&nbsp;`Subscription.deliver` | 253 | Hand packets to the listener. False means none got through. |
| · | &nbsp;&nbsp;`Subscription.connect` | 273 | Open the connection and subscribe. Raises on a permanent refusal. |
| · | &nbsp;&nbsp;`Subscription.run` | 283 | Until stopped. Never raises for anything a retry could fix. |
| · | &nbsp;&nbsp;`Subscription.stop` | 321 |  |
| · | &nbsp;&nbsp;`Subscription.status` | 324 | What it has done, for `mqtt check` and the settings page. |
| f | `options` | 337 | The settings a configured MQTT collector has. Declared rather than read, like every other setting here: the f… |

## `src/weewx_evo/ingest/parsers.py`

[Drivers](Drivers) · last changed 2026-09-03 23:25

| | Name | Line | |
|---|---|---|---|
| f | `register` | 50 | Make a parser available under `name`. |
| f | `parse_json` | 57 | weewx-evo's own envelope. This is the contract every driver can rely on. One object or a list of them: {"date… |
| f | `get` | 124 |  |
| f | `names` | 129 |  |
| f | `known` | 134 |  |

## `src/weewx_evo/ingest/proposals.py`

[Placements](Placements) · last changed 2026-09-03 23:23

| | Name | Line | |
|---|---|---|---|
| **C** | `Proposal` | 56 | One raw name, and where it would go if nobody said otherwise. |
| · | &nbsp;&nbsp;`Proposal.key` | 83 |  |
| **C** | `Proposals` | 88 | Every raw name seen, and what was guessed about it. |
| · | &nbsp;&nbsp;`Proposals.load` | 104 |  |
| · | &nbsp;&nbsp;`Proposals.flush` | 131 | Write them back, if there is anything to write. |
| · | &nbsp;&nbsp;`Proposals.saw` | 153 | Note the raw names in one packet. Returns how many were new. Returns 0 without asking the… |
| · | &nbsp;&nbsp;`Proposals.all` | 228 | Every proposal, newest first. |
| · | &nbsp;&nbsp;`Proposals.for_station` | 232 |  |

## `src/weewx_evo/ingest/sightings.py`

[Drivers](Drivers) · last changed 2026-08-27 23:12

| | Name | Line | |
|---|---|---|---|
| **C** | `Sighting` | 59 | Something that uploaded and is not a station. |
| · | &nbsp;&nbsp;`Sighting.key` | 77 |  |
| **C** | `Sightings` | 81 | The list, kept in the live database. Held in memory and written back rarely. The store is passed in rather th… |
| · | &nbsp;&nbsp;`Sightings.__init__` | 89 |  |
| · | &nbsp;&nbsp;`Sightings.load` | 100 |  |
| · | &nbsp;&nbsp;`Sightings.flush` | 125 | Write the list back, if there is anything to write. |
| · | &nbsp;&nbsp;`Sightings.saw` | 145 | Note that something uploaded. Returns the sighting. Called for uploads that did not match… |
| · | &nbsp;&nbsp;`Sightings.waiting` | 187 | Seen and not folded away, most recent first. |
| · | &nbsp;&nbsp;`Sightings.ignored` | 192 |  |
| · | &nbsp;&nbsp;`Sightings.find` | 196 |  |
| · | &nbsp;&nbsp;`Sightings.ignore` | 199 |  |
| · | &nbsp;&nbsp;`Sightings.forget` | 208 | Drop one outright. Adopting is the other way it leaves the list. |
| · | &nbsp;&nbsp;`Sightings.expire` | 216 | Drop what has not been seen for a while. Returns how many went. Ignored and waiting alike… |
| · | &nbsp;&nbsp;`Sightings.close` | 242 |  |

## `src/weewx_evo/ingest/state.py`

[Drivers](Drivers) · last changed 2026-09-04 02:11

| | Name | Line | |
|---|---|---|---|
| **C** | `State` | 56 | Small persistent storage for one driver. |
| · | &nbsp;&nbsp;`State.get` | 59 |  |
| · | &nbsp;&nbsp;`State.set` | 61 |  |
| · | &nbsp;&nbsp;`State.delete` | 63 |  |
| **C** | `NoState` | 66 | For a driver that is handed nothing. Remembers within the process only. |
| · | &nbsp;&nbsp;`NoState.__init__` | 69 |  |
| · | &nbsp;&nbsp;`NoState.get` | 72 |  |
| · | &nbsp;&nbsp;`NoState.set` | 75 |  |
| · | &nbsp;&nbsp;`NoState.delete` | 78 |  |
| **C** | `ArchiveState` | 82 | Compatibility adapter backed by an explicitly supplied archive. The store is held privately. A driver receive… |
| · | &nbsp;&nbsp;`ArchiveState.__init__` | 89 |  |
| · | &nbsp;&nbsp;`ArchiveState.get` | 93 |  |
| · | &nbsp;&nbsp;`ArchiveState.set` | 100 |  |
| · | &nbsp;&nbsp;`ArchiveState.delete` | 106 |  |
| **C** | `FileState` | 110 | Backed by a JSON file; used by the production Listener and tests. |
| · | &nbsp;&nbsp;`FileState.__init__` | 113 |  |
| · | &nbsp;&nbsp;`FileState.get` | 136 |  |
| · | &nbsp;&nbsp;`FileState.set` | 139 |  |
| · | &nbsp;&nbsp;`FileState.delete` | 144 |  |
| f | `for_driver` | 150 | Build state from the archive or path explicitly supplied by the caller. |

## `src/weewx_evo/ingest/statuspage.py`

[Listener](Ingest-Listener) · last changed 2026-09-03 23:25

| | Name | Line | |
|---|---|---|---|
| f | `short_source` | 45 |  |
| f | `recent` | 67 | What the page needs: the last few packets, and how things are going. |
| f | `render` | 126 | The page itself. One file, no dependencies. |

## `src/weewx_evo/ingest/userdrivers.py`

[Drivers](Drivers) · last changed 2026-08-26 23:56

| | Name | Line | |
|---|---|---|---|
| f | `directory` | 46 | Where user drivers live. |
| f | `installed` | 59 | The drivers installed, as (name, where it came from). |
| f | `load` | 75 | Register every installed user driver. Returns the names that loaded. |
| **C** | `InstallError` | 115 | Anything that stopped a driver being installed. |
| f | `install` | 119 | Install a driver from a git URL, a zip, or a directory. Returns its name and what its code reaches for -- see… |
| f | `remove` | 161 | Delete an installed driver. Returns False if it was not there. |
| f | `inspect_source` | 285 | What a driver's code reaches for, as {note: [files]}. Read, not run. This is a hint and not a guarantee: it w… |

## `src/weewx_evo/language.py`

**no page** · last changed 2026-09-04 09:21

| | Name | Line | |
|---|---|---|---|
| **C** | `Language` | 79 | One language, and what to say in it. Every lookup falls back to English rather than to the key: a translation… |
| · | &nbsp;&nbsp;`Language.__init__` | 89 |  |
| · | &nbsp;&nbsp;`Language.name` | 95 |  |
| · | &nbsp;&nbsp;`Language.unit_system` | 99 | What a page in this language is read in, unless told otherwise. Empty for English, becaus… |
| · | &nbsp;&nbsp;`Language.obs` | 107 | What a reading is called. Empty where this language has no word. Empty rather than the En… |
| · | &nbsp;&nbsp;`Language.weather` | 126 | What the sky is doing, for a WMO code. `forecast/codes.py` asks this and takes the Englis… |
| · | &nbsp;&nbsp;`Language.moon_phases` | 142 |  |
| · | &nbsp;&nbsp;`Language.compass` | 145 |  |
| · | &nbsp;&nbsp;`Language.months` | 148 |  |
| · | &nbsp;&nbsp;`Language.days` | 151 |  |
| · | &nbsp;&nbsp;`Language.date_shape` | 154 | This language's `%x`, `%X` or `%c`, as a plain strftime format. Empty where the language… |
| · | &nbsp;&nbsp;`Language.spell` | 166 | A moment, written out in this language. Two substitutions before `strftime` gets it, both… |
| · | &nbsp;&nbsp;`Language.unit_labels` | 198 | The words inside a unit, where this language has different ones. Only the ones that diffe… |
| · | &nbsp;&nbsp;`Language.text` | 211 | One word out of any section, or `fallback`. The escape hatch for everything that is neith… |
| · | &nbsp;&nbsp;`Language.say` | 227 | One piece of the settings page, in this language. Keyed on the English itself. That is th… |
| · | &nbsp;&nbsp;`Language.fill` | 246 | One piece of the page that has a number or a name in it. `say("{n} more, rarely needed").… |
| · | &nbsp;&nbsp;`Language.setting` | 269 | The label or help text of one setting, or empty. Keyed on the setting's own name (`interv… |
| f | `get` | 307 | The language for a code, or English. `de_AT` reads `de.toml` and then `de_AT.toml` over it, the same way a sk… |
| f | `languages` | 335 | Every language there is a file for, as (code, name). English is always first and always there, because it is… |
| f | `forget` | 350 | Drop what has been read. For a test that changes a file. |

## `src/weewx_evo/maintenance.py`

[Maintenance](Maintenance) · last changed 2026-08-29 15:59

| | Name | Line | |
|---|---|---|---|
| **C** | `Copied` | 80 | What one backup did. |
| · | &nbsp;&nbsp;`Copied.ok` | 91 |  |
| · | &nbsp;&nbsp;`Copied.summary` | 94 |  |
| **C** | `Verdict` | 103 | What a verification found. |
| · | &nbsp;&nbsp;`Verdict.ok` | 117 |  |
| · | &nbsp;&nbsp;`Verdict.summary` | 120 |  |
| f | `backup` | 135 | Copy a database safely, while it is being written to. `sqlite3.Connection.backup`, not a file copy. See the m… |
| f | `prune_backups` | 186 | Remove all but the newest `keep`. Zero keeps everything. By name, not by modification time: the name carries… |
| f | `restorable` | 206 | Open a backup and see whether it is one. Empty means it is. The check people skip, and the only one that matt… |
| f | `verify` | 235 | Ask whether the file is sound and whether the summaries still follow. `days` limits the second question to th… |
| f | `vacuum` | 433 | Rewrite the file without its free pages. Returns (before, after). Worth doing after a column is dropped or a… |
| f | `checkpoint` | 447 | Fold the write-ahead log back into the database. Returns pages moved. What makes the file on disk *be* the da… |
| f | `space` | 458 | What the file costs, and what a vacuum would give back. |
| f | `disk_free` | 478 | Room where the backups go. A backup that fills the disk is worse than none: it takes the station down with it. |
| f | `enough_room` | 487 | Whether a backup will fit. Empty means it will. Asked before rather than found out during. A copy that runs o… |
| f | `owner_readable_only` | 505 | A backup holds everything the database holds. Same rule as the datasource file the Grafana provisioning write… |

## `src/weewx_evo/metrics.py`

[Metrics](Metrics) · last changed 2026-09-04 01:09

| | Name | Line | |
|---|---|---|---|
| **C** | `Metric` | 61 | One figure, with what it means. |
| · | &nbsp;&nbsp;`Metric.add` | 69 |  |
| · | &nbsp;&nbsp;`Metric.render` | 72 |  |
| **C** | `Metrics` | 99 | Everything the process knows about itself, on demand. Holds no connection, for the reason `api.py` holds none… |
| · | &nbsp;&nbsp;`Metrics.__init__` | 107 |  |
| · | &nbsp;&nbsp;`Metrics.render` | 125 |  |
| f | `descriptors_of_this_process` | 335 | Exposed for a test. `watchdog` owns the real one. |

## `src/weewx_evo/moon.py`

[Sun](Sun) · last changed 2026-08-26 20:42

| | Name | Line | |
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

[MQTT](MQTT) · last changed 2026-08-27 11:27

| | Name | Line | |
|---|---|---|---|
| **C** | `MqttError` | 75 | Anything that stopped a client from doing what was asked. |
| · | &nbsp;&nbsp;`MqttError.__init__` | 78 |  |
| f | `encode_length` | 87 | MQTT's variable-length integer: seven bits a byte, top bit continues. Four bytes at most, so 268 435 455 is t… |
| f | `encode_string` | 105 | A UTF-8 string with a two-byte length in front. Every string in MQTT is this shape -- topic, client id, user… |
| f | `decode_string` | 117 | A length-prefixed UTF-8 string out of a packet body. The other half of `encode_string`, and the one a broker… |
| f | `topic_matches` | 138 | Whether an MQTT topic filter matches a topic name. Two wildcards, and the rules are not symmetric: `+` exactl… |
| **C** | `Reader` | 170 | Reads whole MQTT packets off a socket. |
| · | &nbsp;&nbsp;`Reader.__init__` | 173 |  |
| · | &nbsp;&nbsp;`Reader.packet` | 193 | The next packet as (type, flags, body). |
| **C** | `Client` | 212 | One connection to a broker. Not thread-safe for two publishers at once by accident: `publish` takes a lock, b… |
| · | &nbsp;&nbsp;`Client.__init__` | 221 |  |
| · | &nbsp;&nbsp;`Client.connected` | 250 |  |
| · | &nbsp;&nbsp;`Client.connect` | 253 | Open the connection and log in. Raises `MqttError`. |
| · | &nbsp;&nbsp;`Client.close` | 315 | Say goodbye if possible, then drop the socket either way. |
| · | &nbsp;&nbsp;`Client.publish` | 368 | Send one message. `retain` is what makes a broker hand the last known value to a browser… |
| · | &nbsp;&nbsp;`Client.subscribe` | 417 | Ask for a topic, and remember it across reconnects. |
| · | &nbsp;&nbsp;`Client.pump` | 451 | Read for a while, delivering what arrives and answering pings. For a subscriber. A publis… |
| · | &nbsp;&nbsp;`Client.ping_if_due` | 480 | Keep the connection alive when nothing has been published. A broker drops a client that h… |

## `src/weewx_evo/netaccess.py`

[Security](Security) · last changed 2026-08-27 11:41

| | Name | Line | |
|---|---|---|---|
| **C** | `Access` | 53 | Which addresses are answered. |
| · | &nbsp;&nbsp;`Access.__init__` | 58 |  |
| · | &nbsp;&nbsp;`Access.parse` | 65 | From 'private' (the default), 'any', or a list of addresses. A list may hold networks (`1… |
| · | &nbsp;&nbsp;`Access.allows` | 106 |  |
| f | `warn_if_open` | 134 | Say so, once, at startup, when a service answers the whole internet. |

## `src/weewx_evo/notify/__init__.py`

[Notifications](Notifications) · last changed 2026-08-29 15:27

| | Name | Line | |
|---|---|---|---|
| **C** | `Event` | 101 | Something worth telling somebody about. |
| · | &nbsp;&nbsp;`Event.key` | 119 |  |
| · | &nbsp;&nbsp;`Event.subject_line` | 122 |  |
| · | &nbsp;&nbsp;`Event.body` | 128 |  |
| **C** | `Channel` | 140 | Somewhere a message goes. |
| · | &nbsp;&nbsp;`Channel.send` | 143 |  |
| **C** | `BaseChannel` | 147 | Defaults for a channel. Only `send` has to be written. |
| · | &nbsp;&nbsp;`BaseChannel.send` | 156 |  |
| · | &nbsp;&nbsp;`BaseChannel.check` | 159 | Send a test message and say what happened. |
| · | &nbsp;&nbsp;`BaseChannel.close` | 169 | Release anything held. Optional. |
| **C** | `NotifyError` | 173 | A channel that could not deliver. |
| **C** | `Standing` | 182 | One symptom that is currently true, and what has been sent about it. |
| **C** | `Memory` | 194 | What is wrong now, and since when, across restarts. In the live database, because the settings page is anothe… |
| · | &nbsp;&nbsp;`Memory.__init__` | 202 |  |
| · | &nbsp;&nbsp;`Memory.save` | 229 |  |
| **C** | `Timing` | 248 | How long a symptom holds before it is said, and how often after. |
| f | `decide` | 255 | What to send, given what is wrong and what has already been said. The whole flapping question is in here, and… |
| **C** | `Registry` | 306 | The channels this installation has. Same shape as the others. |
| · | &nbsp;&nbsp;`Registry.__init__` | 309 |  |
| · | &nbsp;&nbsp;`Registry.register_factory` | 313 |  |
| · | &nbsp;&nbsp;`Registry.factory_for` | 316 |  |
| · | &nbsp;&nbsp;`Registry.kinds` | 320 |  |
| · | &nbsp;&nbsp;`Registry.describe` | 324 |  |
| · | &nbsp;&nbsp;`Registry.load` | 328 |  |
| f | `kinds` | 354 |  |
| f | `describe` | 358 |  |
| f | `when_options` | 362 | The timing group, which every channel shares. |

## `src/weewx_evo/notify/mqtt.py`

[MQTT](MQTT) · last changed 2026-08-29 15:24

| | Name | Line | |
|---|---|---|---|
| **C** | `MqttChannel` | 39 | Publishes one retained message per symptom. |
| · | &nbsp;&nbsp;`MqttChannel.__init__` | 46 |  |
| · | &nbsp;&nbsp;`MqttChannel.topic_for` | 67 | One topic per symptom, so the retained state reads as a list. |
| · | &nbsp;&nbsp;`MqttChannel.send` | 78 |  |
| · | &nbsp;&nbsp;`MqttChannel.close` | 100 |  |
| · | &nbsp;&nbsp;`MqttChannel.status` | 107 |  |
| · | &nbsp;&nbsp;`MqttChannel.options` | 112 |  |

## `src/weewx_evo/notify/rules.py`

[Notifications](Notifications) · last changed 2026-09-04 01:09

| | Name | Line | |
|---|---|---|---|
| f | `measured_rhythm` | 97 | The median gap between one console's packets, or None where there are too few to say. Split out from `rhythm`… |
| f | `rhythm` | 130 | How often this station usually sends, in seconds. Measured rather than configured. A console reporting every… |
| f | `stations_silent` | 145 | Configured stations that have stopped sending. Only configured ones. A stranger that turns up and goes away a… |
| f | `batteries_flat` | 194 | Transmitters reporting a flat battery, from the newest packet each. The newest packet rather than the archive… |
| f | `sending_failing` | 239 | Exports and uploads that keep being refused. Read from `live_metadata`, which is where the runners write what… |
| f | `process_unwell` | 270 | What the watchdog knows: a restart, and a loop that has stopped. The restart is reported *after* the fact, be… |
| f | `everything` | 306 | Every symptom, right now. Anything that raises is skipped, not fatal. A check that throws must not take the o… |

## `src/weewx_evo/notify/runner.py`

[Notifications](Notifications) · last changed 2026-09-03 23:25

| | Name | Line | |
|---|---|---|---|
| **C** | `Channel` | 43 | One configured channel, with its own timing. |
| **C** | `Runner` | 51 | Watches for symptoms and tells the channels about them. |
| · | &nbsp;&nbsp;`Runner.__init__` | 54 |  |
| · | &nbsp;&nbsp;`Runner.replace` | 79 | Swap in a new set after the configuration changed. A method rather than assignments at th… |
| · | &nbsp;&nbsp;`Runner.start` | 93 |  |
| · | &nbsp;&nbsp;`Runner.stop` | 104 |  |
| · | &nbsp;&nbsp;`Runner.alive` | 110 |  |
| · | &nbsp;&nbsp;`Runner.once` | 124 | One pass: look, decide, send. Returns what was sent. |
| · | &nbsp;&nbsp;`Runner.close` | 173 |  |

## `src/weewx_evo/notify/smtp.py`

[Notifications](Notifications) · last changed 2026-08-29 15:27

| | Name | Line | |
|---|---|---|---|
| **C** | `EmailChannel` | 32 | Sends one message per event. |
| · | &nbsp;&nbsp;`EmailChannel.__init__` | 39 |  |
| · | &nbsp;&nbsp;`EmailChannel.send` | 65 |  |
| · | &nbsp;&nbsp;`EmailChannel.status` | 118 |  |
| · | &nbsp;&nbsp;`EmailChannel.options` | 123 |  |

## `src/weewx_evo/notify/webhook.py`

[Notifications](Notifications) · last changed 2026-08-29 15:36

| | Name | Line | |
|---|---|---|---|
| **C** | `WebhookChannel` | 61 | Posts one request per event. |
| · | &nbsp;&nbsp;`WebhookChannel.__init__` | 68 |  |
| · | &nbsp;&nbsp;`WebhookChannel.body_for` | 89 | The template with this event in it. Every value goes in as JSON, so a quotation mark in a… |
| · | &nbsp;&nbsp;`WebhookChannel.send` | 115 |  |
| · | &nbsp;&nbsp;`WebhookChannel.status` | 138 |  |
| · | &nbsp;&nbsp;`WebhookChannel.options` | 144 |  |

## `src/weewx_evo/obstypes.py`

[Aggregation](Aggregation) · last changed 2026-08-26 10:54

| | Name | Line | |
|---|---|---|---|
| **C** | `ObsPolicy` | 18 | What to do with one observation type. |
| **C** | `Policy` | 61 | The aggregation policy for a whole installation. `overrides` mirrors the `[Accumulator]` section of weewx.con… |
| · | &nbsp;&nbsp;`Policy.__init__` | 70 |  |

## `src/weewx_evo/options.py`

[Configuration](Configuration) · last changed 2026-09-04 13:16

| | Name | Line | |
|---|---|---|---|
| **C** | `Invalid` | 51 | A value that a setting cannot take, with a reason a person can act on. |
| **C** | `Option` | 56 | One setting. |
| · | &nbsp;&nbsp;`Option.options` | 120 | The choices, asking the installation if that is where they are. A failure here is not fat… |
| · | &nbsp;&nbsp;`Option.offered` | 135 | The suggestions, asking the machine where that is where they are. Same shape and same fai… |
| · | &nbsp;&nbsp;`Option.parse` | 150 | Turn what arrived into the value this setting holds. Raises Invalid with a message meant… |
| · | &nbsp;&nbsp;`Option.render` | 236 | The value as the form should show it. Secrets never come back. |
| f | `parse_duration` | 247 | Seconds from '90', '5m', '2h', '7d'. A bare number is seconds. |
| f | `format_duration` | 256 | The other way, choosing the largest unit that stays whole. A string that is already a duration comes back as… |
| f | `split_duration` | 288 | Seconds as (amount, unit), in the largest unit that stays whole. 604800 becomes (7, "d"), not (604800, "s").… |
| **C** | `Group` | 304 | Settings that belong together, and become one section of the form. |
| **C** | `Schema` | 316 | Everything one component can be configured with. |
| · | &nbsp;&nbsp;`Schema.option` | 331 |  |
| · | &nbsp;&nbsp;`Schema.defaults` | 337 |  |
| · | &nbsp;&nbsp;`Schema.parse` | 341 | Check a whole form's worth at once. Returns the parsed settings and, separately, what was… |
| f | `schema_of` | 384 | Ask a component to describe itself, if it can. |
| f | `installed_drivers` | 405 | The drivers this installation actually has. Asked at render time, not listed here: installing a driver should… |
| f | `installed_skins` | 417 | The Cheetah skins that are there, for the dropdown that offers them. Read from the directory a feed points at… |
| f | `published_names` | 449 | What the built-in web server has to hand out. The local exports, by name: an export is where somebody said a… |
| f | `building_for` | 474 | Say which file the forms about to be built describe. A dropdown that lists the exports has to read them from… |
| f | `available_languages` | 530 | Every language there is a file for. English is built in. |
| f | `running_config` | 537 | What the configuration says, for a list that has to name reality. The same answer `_current_config` works out… |
| f | `defined_feeds` | 546 | The feeds that exist, by the names the operator gave them. Names, not kinds. Two sets of JSON in two unit sys… |
| f | `website_options` | 573 | The built-in web server. Its own page, because "where does what I made end up" is the question people actuall… |
| f | `core_options` | 639 | What weewx-evo itself is configured with. |

## `src/weewx_evo/placement.py`

[Placements](Placements) · last changed 2026-09-04 09:03

| | Name | Line | |
|---|---|---|---|
| **C** | `Takes` | 78 | One scope, and what it says about the readings in it. `archive` is required, and a scope without one never ma… |
| · | &nbsp;&nbsp;`Takes.covers` | 106 |  |
| · | &nbsp;&nbsp;`Takes.score` | 112 | How specific this scope is. Higher wins. |
| **C** | `Placements` | 118 | Every placement this installation has decided or been told. |
| · | &nbsp;&nbsp;`Placements.matching` | 135 | Every scope that covers this console, least specific first. At equal specificity a learne… |
| · | &nbsp;&nbsp;`Placements.extensions` | 144 | The placements for one console, merged. Raw name -> column or `-`. |
| · | &nbsp;&nbsp;`Placements.unlisted` | 151 | What happens to a reading with no line, for one console. |
| · | &nbsp;&nbsp;`Placements.snapshot` | 159 | A copy that will not change under a build. `Takes` is frozen and `decide` replaces rather… |
| · | &nbsp;&nbsp;`Placements.decide` | 171 | Say where one raw reading goes. An empty column forgets the decision. A learned decision… |
| · | &nbsp;&nbsp;`Placements.set_unlisted` | 199 | Whether unlisted readings follow the catalog or are dropped. |
| · | &nbsp;&nbsp;`Placements.refresh` | 215 | Re-read the file if it has changed. True when it did. The same discipline as `stations.Re… |
| **C** | `Placer` | 263 | Journal packets as WeeWX-named packets, for one archive. A pure lookup. The inferrer is off, so a raw name th… |
| · | &nbsp;&nbsp;`Placer.__init__` | 271 |  |
| · | &nbsp;&nbsp;`Placer.role_of` | 324 | Whether this place takes its series from `sender`. A `Placer` built from a bare archive n… |
| · | &nbsp;&nbsp;`Placer.refresh` | 335 | Freeze current place policy and live sender metadata for a build. |
| · | &nbsp;&nbsp;`Placer.station_of` | 349 | Display metadata for this packet, or None for an unknown sender. |
| · | &nbsp;&nbsp;`Placer.announced` | 353 |  |
| · | &nbsp;&nbsp;`Placer.sender_of` | 356 | The immutable member key used for every archive decision. |
| · | &nbsp;&nbsp;`Placer.name_of` | 360 | Friendly UI name, falling back to the canonical sender id. |
| · | &nbsp;&nbsp;`Placer.named` | 364 | What to call the console behind a (driver, identity) pair. An unannounced one is shown by… |
| · | &nbsp;&nbsp;`Placer.identities` | 375 | Compatibility lookup for non-archive readers during migration. Archive code selects sende… |
| · | &nbsp;&nbsp;`Placer.selected_senders` | 391 | This place's live-db selection, optionally narrowed by role. A broad ``senders = "*"`` re… |
| · | &nbsp;&nbsp;`Placer.selected_main_senders` | 416 | Concrete main-sender addresses for live publishing. |
| · | &nbsp;&nbsp;`Placer.place` | 425 | One journal packet in this archive's column names, or None. None means the packet said no… |
| · | &nbsp;&nbsp;`Placer.replace` | 583 | Take up a changed file. Both halves and the cache go together. A caller that swapped the… |
| · | &nbsp;&nbsp;`Placer.dropped` | 603 | Readings this archive had nowhere to put, by name and count. |
| f | `promote` | 608 | Write down what inference has worked out. Returns what it added. This is the whole of the migration from a gu… |
| f | `name_for` | 662 | What to call a console, for anything that has no `Placer`. The table records the pair; a name is a lookup, an… |
| f | `path_for` | 786 |  |
| f | `load` | 790 | Read placement.toml. A missing file is an installation with none yet. |
| f | `from_dict` | 804 |  |
| f | `save` | 839 | Write placement.toml, keeping the previous one. Written beside and moved into place, like `stations.toml` and… |
| f | `render` | 863 | The placements as a TOML file somebody can edit. |

## `src/weewx_evo/planets.py`

[Sun](Sun) · last changed 2026-08-26 23:56

| | Name | Line | |
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

[Plots](Plots) · last changed 2026-08-30 14:53

| | Name | Line | |
|---|---|---|---|
| **C** | `Line` | 94 | One reading drawn in one plot. |
| · | &nbsp;&nbsp;`Line.resolved` | 137 | The same line with the colors WeeWX would have given it. `place` is what `archives.toml`… |
| **C** | `Plot` | 169 | One chart. |
| · | &nbsp;&nbsp;`Plot.drawn` | 200 | The lines with their colors filled in. |
| · | &nbsp;&nbsp;`Plot.drawn_with` | 204 | The same, with each place's own colour where it has one. `colors` is archive name -> hex,… |
| · | &nbsp;&nbsp;`Plot.uses` | 239 | Which readings this plot needs. |
| · | &nbsp;&nbsp;`Plot.places` | 243 | The archives this chart names, in the order its lines do. A list and not a set: it decide… |
| · | &nbsp;&nbsp;`Plot.names_a_place` | 257 | Whether any reading here says which archive it comes from. The whole of the filing rule,… |
| f | `series_named` | 270 | Every archive the charts in this set ask for, by name. So a feed opens the files something actually uses and… |
| **C** | `PlotSet` | 286 | The plots there are, and what the readings in them are called. |
| · | &nbsp;&nbsp;`PlotSet.__init__` | 289 |  |
| · | &nbsp;&nbsp;`PlotSet.get` | 308 |  |
| · | &nbsp;&nbsp;`PlotSet.add` | 314 |  |
| · | &nbsp;&nbsp;`PlotSet.remove` | 319 |  |
| · | &nbsp;&nbsp;`PlotSet.by_span` | 324 | Grouped, in the order the spans were first seen. |
| · | &nbsp;&nbsp;`PlotSet.spans` | 331 | How long each span covers, for the manifest. A client laying out its own periods needs th… |
| · | &nbsp;&nbsp;`PlotSet.uses` | 342 |  |
| f | `load` | 348 | Read plots.toml. A file that is not there means no plots, not an error. |
| f | `from_dict` | 360 | Plots out of already-parsed TOML. |
| f | `save` | 413 | Write plots.toml, keeping the previous one. Written beside and moved into place, like the configuration: this… |
| f | `render` | 437 | The plots as a TOML file somebody can edit. |
| f | `comparisons` | 531 | One chart per (span, reading), one line per place. Generated rather than typed. Four readings by four spans b… |
| f | `implied` | 606 | The set to draw with, with the missing comparison charts filled in. Worked out rather than written, and this… |
| **C** | `Imported` | 699 | What an import found, and what it did not take. |
| · | &nbsp;&nbsp;`Imported.report` | 710 | What happened, as something to read before trusting it. |
| f | `labels_from` | 735 | What a WeeWX skin calls each reading: `[Labels] [[Generic]]`. Worth carrying across on its own. Somebody who… |
| f | `from_image_generator` | 751 | Plots out of a WeeWX `[ImageGenerator]` section. The structure there is three deep: a group of plots (`[[day_… |

## `src/weewx_evo/quality.py`

[Quality control](Quality) · last changed 2026-09-04 02:07

| | Name | Line | |
|---|---|---|---|
| **C** | `Rule` | 115 | What one reading has to satisfy. |
| · | &nbsp;&nbsp;`Rule.empty` | 131 |  |
| **C** | `Adjust` | 137 | A correction applied before anything is checked. |
| · | &nbsp;&nbsp;`Adjust.empty` | 143 |  |
| **C** | `Verdict` | 151 | One reading that did not get through, and why. |
| **C** | `Policy` | 166 | The rules an installation runs, from `quality.toml`. |
| · | &nbsp;&nbsp;`Policy.adjust_for` | 206 | The correction for one reading from one canonical sender, if any. A sender's own entry wi… |
| f | `sender_for` | 232 | The canonical calibration key carried by a packet. A placer may bind a retained pre-journal row to its modern… |
| f | `load` | 247 | Read `quality.toml`. A file that is not there means no rules. Not an error, and not a warning either. Most in… |
| f | `from_dict` | 261 | A policy out of already-parsed TOML. |
| **C** | `Check` | 323 | Runs a policy over packets in time order. One of these per span, made fresh. That is what keeps `archiver.bui… |
| · | &nbsp;&nbsp;`Check.__init__` | 340 |  |
| · | &nbsp;&nbsp;`Check.calibrate` | 351 | Apply the corrections. Never drops anything. `system` is the packet's, so an offset writt… |
| · | &nbsp;&nbsp;`Check.check` | 381 | The readings that survived, and one verdict per one that did not. |
| · | &nbsp;&nbsp;`Check.context` | 469 | Feed in the readings before the span, without judging them. The spike and stuck rules nee… |
| · | &nbsp;&nbsp;`Check.summary` | 498 |  |
| **C** | `Seen` | 577 | What one reading has actually done. The basis for a suggestion. |
| · | &nbsp;&nbsp;`Seen.varies` | 592 | Whether this reading actually moves. Against its own size, not against a fixed figure: a… |
| · | &nbsp;&nbsp;`Seen.rule` | 605 | A rule with room in it, inside what physics allows. Never tighter than what has been seen… |
| · | &nbsp;&nbsp;`Seen.resolution` | 662 | The smallest step this sensor makes, as far as can be told. |
| · | &nbsp;&nbsp;`Seen.as_toml` | 670 |  |
| f | `watch` | 687 | Measure what each reading has done, over records in time order. Fed the archive for the limits and the live t… |
| f | `merge` | 752 | The floors and ceilings from one measurement, the rest from another. The archive knows how cold it gets; the… |
| f | `across` | 773 | One measurement out of several series, widest reading wins. There is one `quality.toml` and every archiver ge… |

## `src/weewx_evo/ratelimit.py`

[Security](Security) · last changed 2026-08-26 23:43

| | Name | Line | |
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

## `src/weewx_evo/roles.py`

[Stations and Archives](Stations-and-Archives) · last changed 2026-09-04 09:03

| | Name | Line | |
|---|---|---|---|
| f | `keeps` | 77 | Whether an additional sender may write this column unplaced. |

## `src/weewx_evo/schedule.py`

[Feeds](Feeds) · last changed 2026-08-28 22:42

| | Name | Line | |
|---|---|---|---|
| f | `into_hour` | 35 | How far into the local hour a moment is, in seconds. |
| f | `next_slot` | 41 | The next time on the grid `every` makes, counted from the hour. Always in the future, never `now` itself: a c… |
| f | `wait_for` | 63 | How long to sleep, in the sizes a loop that must also stop can use. Capped, because the thread waiting on thi… |

## `src/weewx_evo/series.py`

[Series](Series) · last changed 2026-08-29 17:25

| | Name | Line | |
|---|---|---|---|
| **C** | `Series` | 99 | One reading over one span. Two parallel arrays rather than a list of pairs: about 30% smaller once it is JSON… |
| · | &nbsp;&nbsp;`Series.empty` | 126 | Whether there is anything to draw. An all-null series is not. |
| · | &nbsp;&nbsp;`Series.rounded` | 130 | Round the values in place and return self. Three decimals is well past any weather sensor… |
| **C** | `Reader` | 147 | Reads series from one archive database. Holds a connection and nothing else -- no cache, and so nothing that… |
| · | &nbsp;&nbsp;`Reader.__init__` | 154 |  |
| · | &nbsp;&nbsp;`Reader.columns` | 165 | The readings the archive table has a column for. |
| · | &nbsp;&nbsp;`Reader.system` | 174 | Which unit system the archive holds. US, METRIC or METRICWX. Taken from the first record,… |
| · | &nbsp;&nbsp;`Reader.has_daily` | 188 | Whether there is a daily summary table for this reading. |
| · | &nbsp;&nbsp;`Reader.span` | 200 | The first and last record in the archive, or None if it is empty. Two queries, not one, a… |
| · | &nbsp;&nbsp;`Reader.series` | 228 | A reading over a span. With no aggregate, the archive records themselves. With one, the s… |
| · | &nbsp;&nbsp;`Reader.aggregate` | 267 | One number for one span. Answered from the daily summaries when the span is whole days an… |
| · | &nbsp;&nbsp;`Reader.degree_days` | 298 | Heating, cooling and growing degree days over a span. Not a column and never was: a count… |
| · | &nbsp;&nbsp;`Reader.vector` | 409 | One wind vector for one span, as (magnitude, bearing). `avg` and `sum` add the readings a… |
| · | &nbsp;&nbsp;`Reader.buckets` | 772 | The buckets a span is cut into, as (begin, end) pairs. Days, months and years are whole c… |
| f | `is_midnight` | 872 | Whether a timestamp falls exactly on a local midnight. The daily summaries are keyed by these, so this is the… |
| f | `opened` | 1072 | Readers for the named archives, closed on the way out. For a chart that draws several places on one axis. Ope… |

## `src/weewx_evo/settings.py`

[Configuration](Configuration) · last changed 2026-09-04 00:45

| | Name | Line | |
|---|---|---|---|
| **C** | `Settings` | 91 | One resolved view of the configuration. |
| · | &nbsp;&nbsp;`Settings.__init__` | 94 |  |
| · | &nbsp;&nbsp;`Settings.get` | 111 | The value of one setting, and remember where it came from. |
| · | &nbsp;&nbsp;`Settings.source` | 205 | Where the last-read value of this setting came from. |
| · | &nbsp;&nbsp;`Settings.all` | 209 |  |
| · | &nbsp;&nbsp;`Settings.view` | 214 | One component's corner of the settings, and nothing else. A driver gets this rather than… |
| · | &nbsp;&nbsp;`Settings.reload` | 230 | Re-read the file. Returns whether the file is different. This is what a settings service… |
| · | &nbsp;&nbsp;`Settings.needs_restart` | 277 | Which of the settings that just changed cannot be applied live. The schema already says s… |
| · | &nbsp;&nbsp;`Settings.explain` | 287 | One line per setting, saying what it is and where it came from. `extra` is the schemas th… |
| f | `load` | 335 | Build a Settings from the places there are. A missing configuration file is not an error: a first start has n… |
| f | `running` | 378 | The settings this process resolved, or None before it has. |
| f | `running_args` | 383 | The arguments this run was given. Which file, above all. |
| f | `set_running` | 388 |  |
| f | `forget_running` | 394 | Start over. For a test that resolves twice in one process. |

## `src/weewx_evo/skinkit.py`

[Feeds](Feeds) · last changed 2026-08-27 19:38

| | Name | Line | |
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
| **C** | `Formatter` | 325 | Turns a value tuple into text. WeeWX's `weewx.units.Formatter`. |
| · | &nbsp;&nbsp;`Formatter.__init__` | 328 |  |
| · | &nbsp;&nbsp;`Formatter.toString` | 344 |  |
| · | &nbsp;&nbsp;`Formatter.get_label_string` | 354 |  |
| · | &nbsp;&nbsp;`Formatter.to_ordinal_compass` | 357 |  |
| **C** | `Converter` | 363 | Turns a value tuple into what the page shows it in. Built two ways, because WeeWX's is: from a `units.Target`… |
| · | &nbsp;&nbsp;`Converter.__init__` | 376 |  |
| · | &nbsp;&nbsp;`Converter.convert` | 392 | One value, or a whole series of them. A list as well as a number, because `get_series` ha… |
| · | &nbsp;&nbsp;`Converter.getTargetUnit` | 413 |  |
| **C** | `DbBinder` | 418 | `db_lookup()` and what it returns. An extension calls `db_lookup()` with no arguments, or with a binding name… |
| · | &nbsp;&nbsp;`DbBinder.__init__` | 426 |  |
| · | &nbsp;&nbsp;`DbBinder.get_manager` | 430 |  |
| **C** | `Manager` | 437 | A database, as an extension expects to be handed one. |
| · | &nbsp;&nbsp;`Manager.__init__` | 440 |  |
| · | &nbsp;&nbsp;`Manager.std_unit_system` | 446 |  |
| · | &nbsp;&nbsp;`Manager.firstGoodStamp` | 450 |  |
| · | &nbsp;&nbsp;`Manager.lastGoodStamp` | 455 |  |
| · | &nbsp;&nbsp;`Manager.getSql` | 459 | One row, or None. WeeWX's own name for it. |
| · | &nbsp;&nbsp;`Manager.genSql` | 468 |  |
| · | &nbsp;&nbsp;`Manager.has_data` | 474 |  |
| · | &nbsp;&nbsp;`Manager.getAggregate` | 482 |  |
| **C** | `TimeSpan` | 491 | A start and a stop. WeeWX's `weeutil.weeutil.TimeSpan`. |
| · | &nbsp;&nbsp;`TimeSpan.start` | 498 |  |
| · | &nbsp;&nbsp;`TimeSpan.stop` | 502 |  |
| · | &nbsp;&nbsp;`TimeSpan.length` | 506 |  |
| · | &nbsp;&nbsp;`TimeSpan.includesArchiveTime` | 509 |  |
| f | `search_up` | 518 | Look for a key here, then in the section above, and so on. A section knows its parent (`weewxconf.Section`),… |
| f | `accumulateLeaves` | 537 | Every scalar in a section and in the ones above it, flattened. WeeWX's, transcribed. `max_level` counts how f… |
| f | `rounder` | 559 | Round a number, or a sequence of them. WeeWX's own, and its shape. A *plain list* comes back for anything ite… |
| f | `to_bool` | 589 |  |
| f | `to_int` | 600 |  |
| f | `to_float` | 610 |  |
| f | `option_as_list` | 618 |  |
| f | `startOfDay` | 626 | Local midnight of the day a moment falls in. |
| f | `startOfArchiveDay` | 634 | The same, but a record stamped exactly at midnight belongs to the day before it -- an archive record covers t… |
| f | `archiveDaySpan` | 641 |  |
| f | `mph_to_knot` | 647 | Miles an hour to knots. WeeWX's factor, not a recomputed one. |
| f | `kph_to_knot` | 652 |  |
| f | `mps_to_knot` | 656 |  |
| f | `get_series` | 660 | A reading over a span, as three value tuples. When each bucket starts, when it stops, and what is in it. WeeW… |
| f | `get_aggregate` | 683 | One number for one span. |
| f | `beaufort` | 696 | The Beaufort number for a wind speed in knots. |
| f | `install_weewx_names` | 809 | Make `import weewx` work, once per process. For a skin written for WeeWX. The skins that ship here import fro… |

## `src/weewx_evo/skins/__init__.py`

[Deck](Deck) · last changed 2026-08-26 22:35

| | Name | Line | |
|---|---|---|---|
| f | `bundled` | 21 | The skins that ship, by name. |

## `src/weewx_evo/skins/deck/options.py`

[Deck](Deck) · last changed 2026-08-30 14:53

| | Name | Line | |
|---|---|---|---|
| f | `groups` | 141 | The skin's own settings, as the admin page and `--explain` see them. The three groups about places are left o… |

## `src/weewx_evo/skins/deck/tags.py`

[Deck](Deck) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| f | `logdbg` | 58 |  |
| f | `loginf` | 62 |  |
| f | `logerr` | 66 |  |
| **C** | `RainTags` | 70 | " Code for last_rain and time_since_last_rain is taken (and slightly modified) from https://github.com/vinces… |
| · | &nbsp;&nbsp;`RainTags.__init__` | 85 |  |
| · | &nbsp;&nbsp;`RainTags.get_extension_list` | 88 | Returns a search list extension with datetime of last rain and secs since then. Parameter… |
| **C** | `GeneralUtil` | 375 |  |
| · | &nbsp;&nbsp;`GeneralUtil.__init__` | 376 |  |
| · | &nbsp;&nbsp;`GeneralUtil.format_raw_value` | 390 | Returns a ValueHelper for a raw value and an obs type. Args: value (float): The value obs… |
| · | &nbsp;&nbsp;`GeneralUtil.get_software_obs` | 403 | Get the observations provided by software (weewx calculations), was added because the has… |
| · | &nbsp;&nbsp;`GeneralUtil.spell` | 413 | A moment, written the way this language writes one. `$spell($week.start.raw, $get_time_fo… |
| · | &nbsp;&nbsp;`GeneralUtil.month_word` | 440 | The short name of a month, in the page's language. `calendar.month_abbr` follows the proc… |
| · | &nbsp;&nbsp;`GeneralUtil.weekday_names` | 456 | The seven days, short, starting on Sunday. Sunday first because that is the order a calen… |
| · | &nbsp;&nbsp;`GeneralUtil.month_names` | 469 | The twelve months, short, in the page's language. |
| · | &nbsp;&nbsp;`GeneralUtil.get_locale` | 473 | The locale the browser code formats dates and numbers in. One setting decides what langua… |
| · | &nbsp;&nbsp;`GeneralUtil.getValueHelper` | 492 | Get a value helper for a value_vt. Args: value_vt (tuple): A value tuple Returns: obj: A… |
| · | &nbsp;&nbsp;`GeneralUtil.get_base_path` | 505 | Get the base path + a given path. Args: path (string): The path Returns: str: The base pa… |
| · | &nbsp;&nbsp;`GeneralUtil.asset` | 523 | The base path plus a file, with a mark that changes when it does. Without one, a styleshe… |
| · | &nbsp;&nbsp;`GeneralUtil.show_yesterday` | 551 |  |
| · | &nbsp;&nbsp;`GeneralUtil.get_context_key_from_time_span` | 557 | Get the context key from a given time span. Args: start_ts (int): The start timestamp end… |
| · | &nbsp;&nbsp;`GeneralUtil.show_sensor_page` | 587 |  |
| · | &nbsp;&nbsp;`GeneralUtil.show_cmon_page` | 593 |  |
| · | &nbsp;&nbsp;`GeneralUtil.get_time_format_dict` | 599 |  |
| · | &nbsp;&nbsp;`GeneralUtil.get_unit_label` | 602 | Get the unit label for a given unit. @see https://www.weewx.com/docs/customizing.htm#unit… |
| · | &nbsp;&nbsp;`GeneralUtil.difference_label` | 629 | The unit a *difference* between two readings is in. Two thermometers 4.2 apart are 4.2 ke… |
| · | &nbsp;&nbsp;`GeneralUtil.get_unit_for_obs` | 648 | Get the unit for a given observation. Args: observation (string): The observation observa… |
| · | &nbsp;&nbsp;`GeneralUtil.get_icon` | 713 | Returns an include path for an icon based on the observation # @see https://www.weewx.com… |
| · | &nbsp;&nbsp;`GeneralUtil.get_color` | 906 | Color settings for observations. Args: observation (string): The observation context (str… |
| · | &nbsp;&nbsp;`GeneralUtil.get_time_span_from_context` | 1022 | Get tag for use in templates. Args: context (string): The time range day: Daily TimeSpanB… |
| · | &nbsp;&nbsp;`GeneralUtil.get_static_pages` | 1056 | Get static pages. Returns: list: Static pages array |
| · | &nbsp;&nbsp;`GeneralUtil.get_static_page_title` | 1081 | Get static page title. Args: page (string): The page Returns: str: The page title |
| · | &nbsp;&nbsp;`GeneralUtil.get_ordinates` | 1099 |  |
| **C** | `ArchiveUtil` | 1127 |  |
| · | &nbsp;&nbsp;`ArchiveUtil.__init__` | 1128 |  |
| · | &nbsp;&nbsp;`ArchiveUtil.get_extension_list` | 1131 | Returns a search list extension with two additions. Parameters: timespan: An instance of… |
| · | &nbsp;&nbsp;`ArchiveUtil.get_stat_table_month_obs` | 1156 | Returns a TimeSpanBinder a period. Args: start_ts (int): The start timestamp end_ts (int)… |
| · | &nbsp;&nbsp;`ArchiveUtil.get_day_archive_enabled` | 1173 | Get day archive enabled. Returns: bool|string: Value of day template if day archive is en… |
| · | &nbsp;&nbsp;`ArchiveUtil.get_archive_days_array` | 1188 | Get an array of days between two timestamps. Args: start_ts (int): The start timestamp en… |
| · | &nbsp;&nbsp;`ArchiveUtil.filter_months` | 1215 | Returns a filtered list of months Args: months (list): A list of months [2022-01, 2022-02… |
| · | &nbsp;&nbsp;`ArchiveUtil.fake_get_report_years` | 1235 | Returns a fake $SummaryByYear tag. Strings, because that is what the real `$SummaryByYear… |
| **C** | `CelestialUtil` | 1263 |  |
| · | &nbsp;&nbsp;`CelestialUtil.get_celestial_icon` | 1265 | Returns an include path for an icon based on the observation Args: observation (string):… |
| **C** | `DiagramUtil` | 1297 |  |
| · | &nbsp;&nbsp;`DiagramUtil.__init__` | 1298 |  |
| · | &nbsp;&nbsp;`DiagramUtil.snap_to_clock` | 1306 | Put an aggregated window on the clock instead of on "now". `get_series` buckets from the… |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram_data` | 1355 | Get diagram data. Args: observation (string): The observation observation_key (string): T… |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram` | 1449 | Choose between line and bar. Args: observation (string): The observation context_key (str… |
| · | &nbsp;&nbsp;`DiagramUtil.get_aggregate_type` | 1497 | aggregate_type for observations series. @see https://github.com/weewx/weewx/wiki/Tags-for… |
| · | &nbsp;&nbsp;`DiagramUtil.get_aggregate_interval` | 1546 | aggregate_interval for observations series. @see https://github.com/weewx/weewx/wiki/Tags… |
| · | &nbsp;&nbsp;`DiagramUtil.get_chart` | 1667 | The whole chart, as JSON, for one `data-chart` attribute. What this replaced: ten `data-`… |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram_props` | 1735 | Get diagram props from skin.conf. Args: obs (string): Observation context (string): Day,… |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram_props_obs` | 1785 | Same as get_diagram_props, but for specific observations. Returns the values in [combined… |
| · | &nbsp;&nbsp;`DiagramUtil.get_diagram_boundary` | 1855 | boundary for observations series for diagrams. Args: context (string): Day, week, month,… |
| · | &nbsp;&nbsp;`DiagramUtil.get_rounding` | 1883 | Rounding settings for observations. Args: observation (string): The observation observati… |
| · | &nbsp;&nbsp;`DiagramUtil.get_hour_delta` | 2025 | Get delta for $span($hour_delta=$delta) call. Args: context (string): Day, week, month, y… |
| · | &nbsp;&nbsp;`DiagramUtil.get_gauge_diagram_props` | 2051 | Get gauge props from skin.conf. Args: obs (string): Observation context (string): Day, we… |
| · | &nbsp;&nbsp;`DiagramUtil.get_gauge_diagram_prop` | 2069 | Get gauge prop from skin.conf. Args: obs (string): Observation prop (string): Prop contex… |
| · | &nbsp;&nbsp;`DiagramUtil.get_windrose_chart` | 2090 | The wind rose, as JSON for one `data-chart` attribute. Sixteen compass points, one stacke… |
| · | &nbsp;&nbsp;`DiagramUtil.get_windrose_data` | 2114 | Get data for rendering wind rose in JS. start_ts (Timestamp): Start timestamp end_ts (Tim… |
| **C** | `StatsUtil` | 2309 |  |
| · | &nbsp;&nbsp;`StatsUtil.__init__` | 2310 |  |
| · | &nbsp;&nbsp;`StatsUtil.get_show_min` | 2319 | Returns if the min stats should be shown. Args: observation (string): The observation Ret… |
| · | &nbsp;&nbsp;`StatsUtil.get_show_sum` | 2349 | Returns if the sum stats should be shown. Args: observation (string): The observation Ret… |
| · | &nbsp;&nbsp;`StatsUtil.get_show_max` | 2366 | Returns if the max stats should be shown. Args: observation (string): The observation Ret… |
| · | &nbsp;&nbsp;`StatsUtil.get_labels` | 2384 | Returns a label like "Todays Max" or "Monthly average". Args: prop (string): Min, Max, Su… |
| · | &nbsp;&nbsp;`StatsUtil.has_column` | 2400 | Whether the archive has this reading at all. A station with no snow gauge should not be s… |
| · | &nbsp;&nbsp;`StatsUtil.get_climatological_day` | 2411 | Return number of days in period for day parameter. Args: day (string): Eg. rainDays, hotD… |
| · | &nbsp;&nbsp;`StatsUtil.get_climatological_day_description` | 2603 | Return description of day. Args: day (string): Eg. rainDays, hotDays. Returns: string: Da… |
| · | &nbsp;&nbsp;`StatsUtil.get_calendar_color` | 2695 | Returns a color for use in diagram. Args: obs (string): The observation Returns: string:… |
| · | &nbsp;&nbsp;`StatsUtil.get_calendar_chart` | 2730 | The days, or the months, depending on how long the span is. Under about fourteen months:… |
| · | &nbsp;&nbsp;`StatsUtil.get_month_matrix` | 2771 | Months across, years down, as JSON for one `data-chart`. What a day grid turns into once… |
| · | &nbsp;&nbsp;`StatsUtil.get_calendar_data` | 2818 | Returns array of calendar data for use in diagram. Args: obs (string): The observation ag… |
| **C** | `TableUtil` | 2893 |  |
| · | &nbsp;&nbsp;`TableUtil.__init__` | 2894 |  |
| · | &nbsp;&nbsp;`TableUtil.get_table_aggregate_interval` | 2908 | aggregate_interval for observations series for tables. Args: context (string): Day, week,… |
| · | &nbsp;&nbsp;`TableUtil.get_table_boundary` | 2936 | boundary for observations series for tables. Args: context (string): Day, week, month, ye… |
| · | &nbsp;&nbsp;`TableUtil.get_table_headers` | 2965 | Returns tableheaders for use in carbon data table. Args: start_ts (Timestamp): Start time… |
| · | &nbsp;&nbsp;`TableUtil.get_table_rows` | 3005 | Returns table values for use in carbon data table. Args: start_ts (Timestamp): Start time… |
| **C** | `PlacesUtil` | 3105 | What a site of several places asks, and one archive never had to. Every method here takes the roster -- `$pla… |
| · | &nbsp;&nbsp;`PlacesUtil.__init__` | 3130 |  |
| · | &nbsp;&nbsp;`PlacesUtil.place_age` | 3142 | How long ago this place last wrote a record, and what that means. Facts, not a sentence:… |
| · | &nbsp;&nbsp;`PlacesUtil.place_cadence` | 3185 | How far apart this place's records are, in seconds, measured. The archive's own `interval… |
| · | &nbsp;&nbsp;`PlacesUtil.unusual_list` | 3221 | The nothing-to-four things on this site that are not ordinary. A closed list of three rul… |
| · | &nbsp;&nbsp;`PlacesUtil.compare_rows` | 3353 | One row per reading, one cell per place, with both ends of the spread named. **Which aggr… |
| · | &nbsp;&nbsp;`PlacesUtil.page_unit_system` | 3435 | The unit system this page was rendered in, by name. Written onto `<body>` so `live-poll.j… |

## `src/weewx_evo/sources.py`

[Multiple senders](Multiple-Sources) · last changed 2026-08-26 23:47

| | Name | Line | |
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

## `src/weewx_evo/starter/__init__.py`

[Plots](Plots) · last changed 2026-08-29 13:34

| | Name | Line | |
|---|---|---|---|
| f | `plots_file` | 63 | The starter charts, as they ship. |
| f | `is_starter` | 68 | Whether that plots.toml is still the one this module laid down. Read from the top of the file: `plots.save()`… |
| f | `install_plots` | 94 | Put the starter charts at `where` if there is nothing there. Returns what happened, for a caller that wants t… |
| f | `missing` | 128 | What a fresh installation still has to be told, in the order it matters. Used by the overview and by the wiza… |

## `src/weewx_evo/stations.py`

[Stations and Archives](Stations-and-Archives) · last changed 2026-09-04 07:57

| | Name | Line | |
|---|---|---|---|
| **C** | `Station` | 61 | One console, announced. |
| · | &nbsp;&nbsp;`Station.matches` | 94 | Whether an upload belongs to this station. The identity is compared without regard to cas… |
| **C** | `Register` | 106 | The stations this installation has. Held as a list rather than keyed by identity: two drivers may legitimatel… |
| · | &nbsp;&nbsp;`Register.refresh` | 121 | Re-read the file if it has changed. True when it did. The settings page writes this file… |
| · | &nbsp;&nbsp;`Register.by_name` | 177 |  |
| · | &nbsp;&nbsp;`Register.by_identity` | 183 | Which station an upload belongs to, or None if it is a stranger. |
| · | &nbsp;&nbsp;`Register.drivers` | 190 |  |
| · | &nbsp;&nbsp;`Register.identities_for` | 193 |  |
| · | &nbsp;&nbsp;`Register.add` | 199 | Announce a station. Raises if the name or the identity is taken. Refused rather than merg… |
| · | &nbsp;&nbsp;`Register.why_not` | 212 | Why this station cannot be added, or an empty string. Separate from `add` because the pag… |
| · | &nbsp;&nbsp;`Register.remove` | 233 |  |
| · | &nbsp;&nbsp;`Register.rename` | 239 | Rename a station, keeping everything else. Packets are stored under driver and identity,… |
| · | &nbsp;&nbsp;`Register.identity_for` | 256 | An identity nobody else here has. Handed out rather than chosen, which is the whole point… |
| f | `path_for` | 277 |  |
| f | `load` | 281 | Read stations.toml. A missing file is an installation with none yet. |
| f | `from_dict` | 321 |  |
| f | `save` | 352 | Write stations.toml, keeping the previous one. Written beside and moved into place, like the configuration an… |
| f | `render` | 376 | The stations as a TOML file somebody can edit. |

## `src/weewx_evo/sun.py`

[Sun](Sun) · last changed 2026-08-26 23:47

| | Name | Line | |
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

[Feeds](Feeds) · last changed 2026-08-30 11:51

| | Name | Line | |
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
| · | &nbsp;&nbsp;`Tags.missed` | 1240 |  |
| · | &nbsp;&nbsp;`Tags.report` | 1249 | What a skin asked for and did not get, for the log and the page. |
| · | &nbsp;&nbsp;`Tags.units_of` | 1261 |  |
| · | &nbsp;&nbsp;`Tags.exists` | 1265 |  |
| · | &nbsp;&nbsp;`Tags.has_data` | 1279 |  |
| · | &nbsp;&nbsp;`Tags.shown` | 1287 | A number worked out in one unit, wrapped in what to show it in. Everything the database a… |
| · | &nbsp;&nbsp;`Tags.answer` | 1304 | The one place a tag becomes a database query. |
| · | &nbsp;&nbsp;`Tags.Extras` | 1344 | `$Extras.something` -- whatever the skin's author invented. |
| · | &nbsp;&nbsp;`Tags.DisplayOptions` | 1349 | `$DisplayOptions.get('...')` -- what the skin shows and hides. |
| · | &nbsp;&nbsp;`Tags.lang` | 1354 | Which language the skin is being rendered in. |
| · | &nbsp;&nbsp;`Tags.to_list` | 1359 | `$to_list($DisplayOptions.get('x'))`. A configuration file gives one string where there i… |
| · | &nbsp;&nbsp;`Tags.getattr` | 1373 | `$getattr($current, $x)` -- a reading whose name is in a variable. A template walking a l… |
| · | &nbsp;&nbsp;`Tags.getobs` | 1386 | `$getobs($plot_name)` -- which readings a chart draws. A template asks so that it can say… |
| · | &nbsp;&nbsp;`Tags.to_bool` | 1398 |  |
| · | &nbsp;&nbsp;`Tags.to_int` | 1404 |  |
| · | &nbsp;&nbsp;`Tags.to_float` | 1419 |  |
| · | &nbsp;&nbsp;`Tags.jsonize` | 1423 |  |
| · | &nbsp;&nbsp;`Tags.rnd` | 1429 |  |
| · | &nbsp;&nbsp;`Tags.season` | 1433 | The meteorological season this moment is in. Three months at a time, starting in December… |
| · | &nbsp;&nbsp;`Tags.almanac` | 1449 |  |
| · | &nbsp;&nbsp;`Tags.station` | 1455 |  |
| · | &nbsp;&nbsp;`Tags.obs` | 1459 |  |
| · | &nbsp;&nbsp;`Tags.unit` | 1463 |  |
| · | &nbsp;&nbsp;`Tags.gettext` | 1466 | `$gettext("Outside Temperature")`. Whatever the skin's own language files say, and the te… |
| · | &nbsp;&nbsp;`Tags.pgettext` | 1475 |  |
| · | &nbsp;&nbsp;`Tags.current` | 1479 |  |
| · | &nbsp;&nbsp;`Tags.latest` | 1485 |  |
| · | &nbsp;&nbsp;`Tags.hour` | 1503 |  |
| · | &nbsp;&nbsp;`Tags.hours_ago` | 1506 |  |
| · | &nbsp;&nbsp;`Tags.day` | 1511 |  |
| · | &nbsp;&nbsp;`Tags.days_ago` | 1514 |  |
| · | &nbsp;&nbsp;`Tags.yesterday` | 1519 |  |
| · | &nbsp;&nbsp;`Tags.week` | 1523 |  |
| · | &nbsp;&nbsp;`Tags.weeks_ago` | 1526 |  |
| · | &nbsp;&nbsp;`Tags.month` | 1532 |  |
| · | &nbsp;&nbsp;`Tags.months_ago` | 1535 |  |
| · | &nbsp;&nbsp;`Tags.year` | 1540 |  |
| · | &nbsp;&nbsp;`Tags.years_ago` | 1543 |  |
| · | &nbsp;&nbsp;`Tags.rainyear` | 1548 | The year as a rain gauge counts it, which need not start in January. |
| · | &nbsp;&nbsp;`Tags.alltime` | 1554 | Everything there is, rounded out to whole days. Not the first and last record: that span… |
| · | &nbsp;&nbsp;`Tags.span` | 1569 | `$span($hour_delta=6)` -- a stretch ending now. |
| · | &nbsp;&nbsp;`Tags.trend` | 1586 | `$trend.barometer`, and `$trend($time_delta=7200).barometer`. Both spellings, because tem… |
| · | &nbsp;&nbsp;`Tags.archives` | 1597 | The other measurement series, by name. `$archives.nordfeld`. A property rather than somet… |
| **C** | `Archives` | 1635 | The other measurement series, by name. `$archives.nordfeld.day...` What an overview page is made of. Everythi… |
| · | &nbsp;&nbsp;`Archives.__init__` | 1662 |  |
| · | &nbsp;&nbsp;`Archives.names` | 1722 | Which series there are, for a page that lists them. |
| **C** | `Trend` | 1733 | How much a reading has moved. `$trend.barometer`. The difference between now and a few hours ago, which is wh… |
| · | &nbsp;&nbsp;`Trend.__init__` | 1742 |  |
| **C** | `Section` | 1775 | A block of a skin's own configuration. `$Extras`, `$DisplayOptions`. A real dictionary, deliberately. Cheetah… |

## `src/weewx_evo/units.py`

[Units](Units) · last changed 2026-08-29 15:29

| | Name | Line | |
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
| f | `contribute` | 931 | Record what the drivers say about their own fields. Replaces rather than adds to. It is called with the whole… |
| f | `contributed` | 943 | What the drivers said. A copy: this is not somewhere to write. |
| f | `all_groups` | 948 | Every reading this process can name a group for. The standard schema with the drivers' own on top, which is t… |
| f | `group_of` | 963 | Which group a reading belongs to, or None if nothing knows. Asked in order: what this call was handed, then w… |
| f | `unit_of` | 984 | The unit a reading is stored in, and its group. This is the unit as it sits in the database -- what the recor… |
| f | `convert` | 997 | One value from one unit to another. None stays None: a gap in the readings is not zero degrees. An unknown co… |
| f | `convert_all` | 1014 | A whole series, converted. The gaps stay gaps. |
| f | `can_convert` | 1027 | Whether that conversion exists, without doing it. |
| f | `label` | 1034 | What to print after the number, including its leading space. A few units have a singular and a plural ('1 day… |
| f | `formatted` | 1048 | A value as a person would read it. Not used by the JSON feed -- a machine reading it wants the number -- but… |
| **C** | `Target` | 1064 | What to show readings in, whatever the database holds them in. A console in Germany reporting Fahrenheit and… |
| · | &nbsp;&nbsp;`Target.__init__` | 1089 |  |
| · | &nbsp;&nbsp;`Target.format_for` | 1128 | The printf format for a unit, the skin's if it named one. |
| · | &nbsp;&nbsp;`Target.label_for` | 1134 | What to print after the number, the skin's word if it has one. |
| · | &nbsp;&nbsp;`Target.unit` | 1145 | The unit this group is shown in. |
| · | &nbsp;&nbsp;`Target.for_obs` | 1153 | The unit and group a reading should be shown in. |
| · | &nbsp;&nbsp;`Target.convert` | 1159 | A series out of the database and into what it should be shown in. Returns the values, the… |

## `src/weewx_evo/uploads/__init__.py`

[Uploads](Uploads) · last changed 2026-09-04 00:38

| | Name | Line | |
|---|---|---|---|
| **C** | `Posted` | 79 | What one run of an upload did. |
| · | &nbsp;&nbsp;`Posted.ok` | 96 |  |
| · | &nbsp;&nbsp;`Posted.summary` | 99 |  |
| **C** | `UploadError` | 111 | Something that stopped an upload before it posted anything. Configuration that cannot work, a host that does… |
| **C** | `Rejected` | 121 | The service answered, and said no. Worth its own type because the answer decides what to do next. A 401 is pe… |
| · | &nbsp;&nbsp;`Rejected.__init__` | 129 |  |
| **C** | `Upload` | 149 | Readings out. |
| · | &nbsp;&nbsp;`Upload.post` | 152 | Send `records`, oldest first. Raising means nothing was sent and why. Individual records… |
| **C** | `BaseUpload` | 161 | Defaults for an upload. Only `post` has to be written. |
| · | &nbsp;&nbsp;`BaseUpload.post` | 189 |  |
| · | &nbsp;&nbsp;`BaseUpload.check` | 192 | Try the service and say what happened, without posting readings. The admin page offers th… |
| · | &nbsp;&nbsp;`BaseUpload.status` | 202 |  |
| · | &nbsp;&nbsp;`BaseUpload.close` | 205 | Release anything held. Optional. |
| **C** | `Readings` | 213 | One archive record, readable in any unit. Every one of these services specifies its units and none of them ag… |
| · | &nbsp;&nbsp;`Readings.__init__` | 229 |  |
| · | &nbsp;&nbsp;`Readings.ts` | 234 |  |
| · | &nbsp;&nbsp;`Readings.get` | 240 | A reading, converted. None when the station does not report it. None rather than a zero,… |
| · | &nbsp;&nbsp;`Readings.text` | 262 | A reading as the string that goes in a query, or None. `spec` is a format spec, not a num… |
| f | `request` | 281 | One HTTP request. Returns the status and the body. Text by default, because everything in this package speaks… |
| f | `query` | 323 | A path with a query string, leaving out anything that is None. Leaving out is the point. Every one of these s… |
| **C** | `Registry` | 338 | The uploads this installation has. The same shape as the export and driver registries, and for the same reaso… |
| · | &nbsp;&nbsp;`Registry.__init__` | 346 |  |
| · | &nbsp;&nbsp;`Registry.register` | 351 |  |
| · | &nbsp;&nbsp;`Registry.register_factory` | 356 |  |
| · | &nbsp;&nbsp;`Registry.factory_for` | 359 |  |
| · | &nbsp;&nbsp;`Registry.get` | 363 |  |
| · | &nbsp;&nbsp;`Registry.known` | 367 |  |
| · | &nbsp;&nbsp;`Registry.names` | 371 |  |
| · | &nbsp;&nbsp;`Registry.kinds` | 375 |  |
| · | &nbsp;&nbsp;`Registry.describe` | 379 |  |
| · | &nbsp;&nbsp;`Registry.load` | 383 | Pull in what is installed. A broken one is reported, never fatal. |
| f | `get` | 425 |  |
| f | `names` | 429 |  |
| f | `kinds` | 433 |  |
| f | `describe` | 437 |  |
| f | `when_options` | 441 | The "when it runs" group, which every upload has the same. One copy, because four services with four subtly d… |

## `src/weewx_evo/uploads/ambient.py`

[Uploads](Uploads) · last changed 2026-08-27 10:33

| | Name | Line | |
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

[Uploads](Uploads) · last changed 2026-08-27 13:03

| | Name | Line | |
|---|---|---|---|
| f | `latlon` | 57 | Decimal degrees as APRS writes them: `4823.15N`, `01142.30E`. Degrees and decimal minutes, zero-padded to two… |
| **C** | `CwopUpload` | 71 | Posts records to APRS-IS for CWOP. |
| · | &nbsp;&nbsp;`CwopUpload.__init__` | 80 |  |
| · | &nbsp;&nbsp;`CwopUpload.login` | 121 |  |
| · | &nbsp;&nbsp;`CwopUpload.packet` | 124 | The TNC2 packet. Fixed width throughout -- see the module docstring. Everything is US cus… |
| · | &nbsp;&nbsp;`CwopUpload.post` | 214 |  |
| · | &nbsp;&nbsp;`CwopUpload.check` | 227 | Connect and log in, without sending a packet. APRS-IS has no way to validate a reading, s… |
| · | &nbsp;&nbsp;`CwopUpload.status` | 244 |  |
| · | &nbsp;&nbsp;`CwopUpload.options` | 249 |  |

## `src/weewx_evo/uploads/homeassistant.py`

[Uploads](Uploads) · last changed 2026-08-27 10:33

| | Name | Line | |
|---|---|---|---|
| f | `readable` | 115 | `outTemp` as `Out temp`, which is what a person sees in a list. |
| f | `device_class` | 123 |  |
| f | `discovery` | 130 | One sensor definition, as (topic, payload). `field` is the name inside the JSON document -- `outTemp_C` -- wh… |

## `src/weewx_evo/uploads/influx.py`

[Grafana](Grafana) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| **C** | `InfluxUpload` | 131 | Writes archive records into InfluxDB as line protocol. |
| · | &nbsp;&nbsp;`InfluxUpload.__init__` | 148 |  |
| · | &nbsp;&nbsp;`InfluxUpload.line` | 254 | One record as one line of line protocol, or None if it holds none. A record with a timest… |
| · | &nbsp;&nbsp;`InfluxUpload.body` | 293 | A batch as text, and how many records went into it. |
| · | &nbsp;&nbsp;`InfluxUpload.post` | 300 |  |
| · | &nbsp;&nbsp;`InfluxUpload.check` | 324 | Ask the server, write nothing. A write with an empty body: it goes through authentication… |
| · | &nbsp;&nbsp;`InfluxUpload.counts` | 345 | How many points this bucket holds per window, oldest first. The other half of "a second s… |
| · | &nbsp;&nbsp;`InfluxUpload.status` | 415 |  |
| · | &nbsp;&nbsp;`InfluxUpload.forecast_lines` | 423 | The hours and the days of every configured source, as lines. Written under `<measurement>… |
| · | &nbsp;&nbsp;`InfluxUpload.post_forecast` | 485 | Send the current forecast. Returns how many points went. Called after a source has fetche… |
| · | &nbsp;&nbsp;`InfluxUpload.options` | 499 |  |

## `src/weewx_evo/uploads/mqtt.py`

[MQTT](MQTT) · last changed 2026-08-27 11:09

| | Name | Line | |
|---|---|---|---|
| f | `topic_name` | 73 | What a reading is called on the broker. |
| **C** | `MqttUpload` | 81 | Publishes records to an MQTT broker. |
| · | &nbsp;&nbsp;`MqttUpload.__init__` | 92 |  |
| · | &nbsp;&nbsp;`MqttUpload.message` | 150 | A record as the names and values that go on the broker. Conversion happens here rather th… |
| · | &nbsp;&nbsp;`MqttUpload.post` | 221 |  |
| · | &nbsp;&nbsp;`MqttUpload.publish_packet` | 235 | One live packet, for the live path rather than the archive one. Separate from `post` beca… |
| · | &nbsp;&nbsp;`MqttUpload.browser` | 247 | What a page needs to subscribe to this same broker. The reason this exists: without it th… |
| · | &nbsp;&nbsp;`MqttUpload.check` | 290 |  |
| · | &nbsp;&nbsp;`MqttUpload.status` | 308 |  |
| · | &nbsp;&nbsp;`MqttUpload.close` | 312 |  |
| · | &nbsp;&nbsp;`MqttUpload.options` | 318 |  |

## `src/weewx_evo/uploads/progress.py`

[Uploads](Uploads) · last changed 2026-08-29 14:48

| | Name | Line | |
|---|---|---|---|
| **C** | `Progress` | 30 | The last record each upload got accepted, by upload name. |
| · | &nbsp;&nbsp;`Progress.__init__` | 33 |  |
| · | &nbsp;&nbsp;`Progress.through` | 50 | The newest record this upload has sent, or 0 for never. |
| · | &nbsp;&nbsp;`Progress.sent` | 55 | Note that everything up to `ts` has been accepted. Never moves backwards. A service that… |
| · | &nbsp;&nbsp;`Progress.rewind` | 68 | Send everything after `ts` again. Says whether it changed anything. `sent` deliberately n… |
| · | &nbsp;&nbsp;`Progress.forget` | 87 | Start this upload again from nothing. |
| · | &nbsp;&nbsp;`Progress.save` | 92 |  |

## `src/weewx_evo/uploads/records.py`

[Uploads](Uploads) · last changed 2026-09-04 07:59

| | Name | Line | |
|---|---|---|---|
| **C** | `Archive` | 75 | Read-only access to the archive, one connection per thread. |
| · | &nbsp;&nbsp;`Archive.__init__` | 78 |  |
| · | &nbsp;&nbsp;`Archive.close` | 95 |  |
| · | &nbsp;&nbsp;`Archive.after` | 101 | Up to `limit` records newer than `ts`, oldest first. `ts` of 0 means "the newest one", no… |
| · | &nbsp;&nbsp;`Archive.augment` | 122 | Add the rain totals these services ask for. Leaves the record alone if the database has n… |
| f | `source` | 184 | A `records(after, limit)` callable over an archive file. What the runner wants, without the runner knowing th… |
| **C** | `Live` | 193 | Read-only access to the live packets, one connection per thread. Why this exists beside `Archive`: an archive… |
| · | &nbsp;&nbsp;`Live.__init__` | 249 |  |
| · | &nbsp;&nbsp;`Live.for_sources` | 298 | The same table, seen through one site's consoles. |
| · | &nbsp;&nbsp;`Live.rhythm` | 373 | How often this place's consoles report, in seconds, or None. The mean over the consoles t… |
| · | &nbsp;&nbsp;`Live.after` | 536 | The newest packets after `ts`, oldest first. `limit` is honoured but a live publisher wan… |
| · | &nbsp;&nbsp;`Live.close` | 817 |  |
| f | `live_source` | 826 | A `records(after, limit)` callable over the live table. |

## `src/weewx_evo/uploads/runner.py`

[Uploads](Uploads) · last changed 2026-09-04 01:15

| | Name | Line | |
|---|---|---|---|
| **C** | `Scheduled` | 67 | One upload, and when it is next due. |
| · | &nbsp;&nbsp;`Scheduled.__init__` | 92 |  |
| · | &nbsp;&nbsp;`Scheduled.trigger` | 146 |  |
| · | &nbsp;&nbsp;`Scheduled.every` | 150 |  |
| · | &nbsp;&nbsp;`Scheduled.is_live` | 154 |  |
| · | &nbsp;&nbsp;`Scheduled.due` | 157 |  |
| · | &nbsp;&nbsp;`Scheduled.next_run` | 174 | When this is next due on the wall clock, for the loop to wait. Worked out rather than rea… |
| · | &nbsp;&nbsp;`Scheduled.pending` | 197 | The records this upload still owes, oldest first. Empty when it is up to date, which is t… |
| · | &nbsp;&nbsp;`Scheduled.run` | 226 | Send whatever is owed, and remember what happened. Never raises. |
| **C** | `Runner` | 332 | Keeps the uploads going, one thread each. |
| · | &nbsp;&nbsp;`Runner.__init__` | 335 |  |
| · | &nbsp;&nbsp;`Runner.start` | 341 |  |
| · | &nbsp;&nbsp;`Runner.replace` | 358 | Swap in a new set, after the configuration changed. A method rather than three assignment… |
| · | &nbsp;&nbsp;`Runner.record_written` | 372 | A new archive record landed. Called from the archiver's thread and returns at once: it se… |
| · | &nbsp;&nbsp;`Runner.stop` | 389 |  |
| · | &nbsp;&nbsp;`Runner.status` | 444 |  |
| f | `build` | 458 | Turn configuration into things the runner can run. Anything that cannot be built is reported and left out. A… |

## `src/weewx_evo/uploads/weathercloud.py`

[Uploads](Uploads) · last changed 2026-08-27 10:33

| | Name | Line | |
|---|---|---|---|
| **C** | `WeathercloudUpload` | 55 | Posts records to Weathercloud. |
| · | &nbsp;&nbsp;`WeathercloudUpload.__init__` | 66 |  |
| · | &nbsp;&nbsp;`WeathercloudUpload.post` | 113 |  |
| · | &nbsp;&nbsp;`WeathercloudUpload.check` | 130 |  |
| · | &nbsp;&nbsp;`WeathercloudUpload.status` | 140 |  |
| · | &nbsp;&nbsp;`WeathercloudUpload.options` | 144 |  |

## `src/weewx_evo/uploads/webpush.py`

[Uploads](Uploads) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| **C** | `Place` | 67 | One measurement series this document carries, and how to read it. Callables, not readers. This module has no… |
| **C** | `WebPushUpload` | 98 | Posts the current readings to a `live.php` on the web host. |
| · | &nbsp;&nbsp;`WebPushUpload.__init__` | 120 |  |
| · | &nbsp;&nbsp;`WebPushUpload.document` | 193 | The record as the names and values that go into the file. Deliberately the same shape as… |
| · | &nbsp;&nbsp;`WebPushUpload.carry` | 218 | The other series this one document is to carry. A method rather than a constructor argume… |
| · | &nbsp;&nbsp;`WebPushUpload.post` | 512 |  |
| · | &nbsp;&nbsp;`WebPushUpload.check` | 545 |  |
| · | &nbsp;&nbsp;`WebPushUpload.status` | 590 |  |
| · | &nbsp;&nbsp;`WebPushUpload.from_exports` | 602 | Where to send, from the exports that asked for live readings. Four things come back: the… |
| · | &nbsp;&nbsp;`WebPushUpload.options` | 658 |  |

## `src/weewx_evo/uploads/windy.py`

[Uploads](Uploads) · last changed 2026-08-27 10:33

| | Name | Line | |
|---|---|---|---|
| **C** | `WindyUpload` | 48 | Posts records to Windy. |
| · | &nbsp;&nbsp;`WindyUpload.__init__` | 55 |  |
| · | &nbsp;&nbsp;`WindyUpload.post` | 109 |  |
| · | &nbsp;&nbsp;`WindyUpload.check` | 120 |  |
| · | &nbsp;&nbsp;`WindyUpload.status` | 130 |  |
| · | &nbsp;&nbsp;`WindyUpload.options` | 135 |  |

## `src/weewx_evo/watchdog.py`

**no page** · last changed 2026-08-28 13:02

| | Name | Line | |
|---|---|---|---|
| **C** | `Unwell` | 86 | What a check raises when a restart is the answer. The message is what goes in the log and it is the only expl… |
| f | `descriptors_open` | 94 | How many files this process has open, or None where nobody will say. `/proc` is Linux. That covers the contai… |
| f | `descriptor_limit` | 107 |  |
| **C** | `Watchdog` | 118 | Watches from its own thread, because it cannot watch from inside. A check that runs in the loop it is checkin… |
| · | &nbsp;&nbsp;`Watchdog.__init__` | 126 |  |
| · | &nbsp;&nbsp;`Watchdog.start` | 159 |  |
| · | &nbsp;&nbsp;`Watchdog.stop` | 164 |  |
| · | &nbsp;&nbsp;`Watchdog.beats` | 169 | Called by the loop being watched, every time round. |
| · | &nbsp;&nbsp;`Watchdog.symptoms` | 190 | Everything wrong right now that a new process would fix. |
| · | &nbsp;&nbsp;`Watchdog.check` | 221 | One pass. Returns True if it asked for a restart. |
| · | &nbsp;&nbsp;`Watchdog.last_restart` | 251 |  |
| · | &nbsp;&nbsp;`Watchdog.remember_restart` | 263 | Write the time down, and say whether it stuck. Read back rather than trusted. The failure… |
| f | `threads_of` | 279 | Name each runner's threads and whether they are alive. Takes the runners rather than their threads, because t… |

## `src/weewx_evo/webserver.py`

[Web server](Web-Server) · last changed 2026-08-30 11:51

| | Name | Line | |
|---|---|---|---|
| **C** | `Site` | 67 | Which feeds are served, and from where. |
| · | &nbsp;&nbsp;`Site.__init__` | 70 |  |
| · | &nbsp;&nbsp;`Site.update` | 81 | Serve something else from now on. Returns whether anything moved. The handler holds this… |
| · | &nbsp;&nbsp;`Site.resolve` | 101 | The file for a request, or None if there is not one to serve. The check that matters is t… |
| f | `listing_page` | 140 | What is in a directory that has no index page of its own. Deliberately plain. This is not a page anybody desi… |
| f | `index_page` | 182 | The list of feeds, when none of them is the default. |
| **C** | `WebServer` | 428 | The local web server for the feeds. |
| · | &nbsp;&nbsp;`WebServer.__init__` | 431 |  |
| · | &nbsp;&nbsp;`WebServer.serve_forever` | 452 |  |
| · | &nbsp;&nbsp;`WebServer.start` | 455 |  |
| · | &nbsp;&nbsp;`WebServer.stop` | 460 |  |
| f | `site_from` | 480 | What this server hands out, and under which names. Mostly the local exports: an export named `site` publishin… |

## `src/weewx_evo/weewxconf.py`

[WeeWX compatibility](WeeWX-Compatibility) · last changed 2026-08-29 12:47

| | Name | Line | |
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
| · | &nbsp;&nbsp;`Import.take` | 262 |  |
| f | `convert` | 269 | weewx.conf into weewx-evo settings, with a report of what happened. |
| f | `report` | 518 | What the import did, as something a person reads before trusting it. |

---

Generated by `tools/docsindex.py`. See [File index](Index).

# Glossary

Terms as they are meant in this project. Where WeeWX has a different name for
the same thing, it is given alongside.

---

**Accumulator** — `aggregate.Accumulator`. Statistics for a set of observations
over **one** timespan. Raw values in, one archive record out. A transcription
of `weewx.accum`. → [Aggregation](Aggregation)

**Aggregate** — One number for a span: `avg`, `min`, `max`, `sum`, `count`,
`first`, `last`, `rms`, `vecavg`, `vecdir` and the time variants of those.
→ [Series](Series)

**`archive_day_*`** — The daily summaries. One table per observation. **A
cache**: everything in it is derivable from `archive`.
→ [Daily-Summaries](Daily-Summaries)

**Archive record** — A row in the `archive` table. Covers `interval` minutes
and is stamped with the **end** of that span.

**Archiver** — The service that builds archive records out of timespans.
Replaces WeeWX's `StdArchive`. → [Archiver](Archiver)

**Catch-up** — Build every interval the live table covers.
`weewx-evo catchup`.

**Channel** — With Ecowitt: a sensor position, `ch1` through `ch8`. Two
consoles both number from one — hence the console list.
→ [Driver-Ecowitt](Driver-Ecowitt)

**Console** — The box that sends the readings. What the settings page calls a
station in the file and a console on the page: one row in `stations.toml`, one
identity, and the place its readings belong to.
→ [Several places](Places#pointing-a-console-at-a-place)

**Deriver** — What adds dewpoint, wind chill and the rain delta. Replaces
WeeWX's `StdWXCalculate`. → [Derived-Readings](Derived-Readings)

**`dirsumtime`** — Weight that counts only for wind readings that had a
direction. A calm with no vane contributes no direction.

**Export** — **How** something gets somewhere else: FTP, rsync, a copy. Takes a
directory. → [Exports](Exports)

**Feed** — **What** gets produced: a CSV, a JSON document, a website, a monthly
report. Writes into a directory. → [Feeds](Feeds)

**Fingerprint** — Size, timestamp and, for small files, a hash. What an FTP
export decides with, on whether a file has already been sent.
→ [Exports](Exports#only-send-what-has-changed)

**Grace** — How long to wait after the end of an interval before computing the
record. Default 15 s. So that a merely slow packet does not trigger two
computations.

**Homeless** — A reading the archive table has no column for. Reported, never
created silently. `weewx-evo columns`.

**Interval** — How much time one archive record covers. Default 5 minutes.
**Half-open at the start**: a packet exactly on the boundary closes the interval
that ends there.

**Kind** — Two meanings. (1) The type of a setting: `text secret int float bool
choice path duration list`. (2) The sort of a packet: `loop` or `archive`.

**Live table** — `packet` in `live.sdb`. Every packet that ever arrived, for N
days. Replaces WeeWX's in-memory accumulator.
→ [Database-Live](Database-Live)

**LOOP packet** — WeeWX's name for a single reading, as opposed to an archive
record. Here `kind = "loop"`.

**`loop_hilo`** — Whether individual packets may set the day's extremes. On by
default, like WeeWX. Turned off, the daily extremes are exactly reproducible
from the archive.

**Manifest** — `index.json`. What the JSON feed produced, so a client can lay
out its page before fetching anything.

**`maxSolarRad`** — What a solar sensor would read under a cloudless sky. Held
against a measured value, it says how cloudy it was.

**Option** — A declared setting. Out of it come the form field, the validation,
the file comment and the `--explain` line. → [Configuration](Configuration)

**Packet** — One reading, as it arrived, before anything was done to it.
`db.live.Packet`.

**PASSKEY** — What Ecowitt hardware identifies itself with, derived from its MAC
address. Redacted before anything is stored that somebody might pass on.

**Place** — One spot whose weather is kept: its own coordinates, its own
height above sea level, its own file of readings. Sunrise and the barometer
reduction are worked out from them, so each place has its own. One entry in
`archives.toml`, which is why the code calls it an archive.
→ [Several places](Places)

**Plot** — A plot **definition**: a name, a timespan, and the readings in it.
Belongs to weewx-evo, not to a renderer. → [Plots](Plots)

**Policy** — Two meanings. (1) `obstypes.Policy`: how each observation
aggregates. (2) `sources.Policy`: which source wins for which field.

**Provenance** — Which field of an archive record came from which source.
→ [Multiple-Sources](Multiple-Sources)

**Retention** — How long packets stay in the live table. Default 7 days. As long
as they are there, a record can be corrected.

**Roundtrip** — A value that goes through the form, the file and back. The place
where `"5m"` can come back as a string instead of 300.

**Schema** — Two meanings. (1) `db.schema.Schema`: the shape of an archive
database, **read from the file**. (2) `options.Schema`: everything a component
can be configured with.

**`skip_if_empty`** — A **timespan**, not a boolean. Says over what period a
sensor must have reported nothing for a plot not to be produced at all.

**Source** — A station. Attached to every packet. Several sources are merged
**while the interval is being built**, field by field.

**Span** — Two meanings. (1) The group a plot belongs to: `day`, `week`,
`month`, `year`. (2) A timespan in general. `time_length` is what actually
decides how far a plot reaches back.

**Spool** — Writing packets out as gzip NDJSON before they leave the live table.

**`sumtime`** — The total weight in an accumulator. Together with `wsum` it
makes an average over any period possible.

**Target** — `units.Target`. What readings are **shown** in, independently of
what the database holds. → [Units](Units)

**Token** — A path segment. Two of them: one for uploads, one for the settings
page, **never the same**. → [Security](Security)

**Tracker** — What an FTP export remembers so that it does not send everything
every time. → [Exports](Exports)

**Trigger** — When an export runs: `feed`, `record`, `interval`, `manual`.
`feed` is the default and the right one.

**Unit group** — `group_temperature`, `group_pressure`, `group_rain` and so on.
Which unit a group has depends on the system. → [Units](Units)

**Unit system** — `US` (1), `METRIC` (16), `METRICWX` (17). Stored per record in
`usUnits`.

**`usUnits`** — The column that says which unit system a record is in.

**View** — `Settings.view(prefix, schema)`. The corner of the settings that
belongs to one component, and nothing else. A driver gets that, not the whole
thing.

**`wsum`** — The weighted sum: every value times the time it stood.

**`xsum` / `ysum`** — East and north components of the summed wind vectors. How
a mean direction survives being averaged.

<!-- covers
-->

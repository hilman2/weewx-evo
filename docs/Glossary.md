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

**Channel** — With Ecowitt: a sensor position, `ch1` through `ch8`.
→ [Push drivers](Driver-Ecowitt)

**Console** — The physical box that sends readings. It may be one sender, or a
gateway for several sensors.

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
`archives.toml`, including the first; that entry also selects its senders and
names the one its readings come from.
This is why the code calls it an archive.
→ [Several places](Places)

**Sender** — The stable source of raw packets: a canonical ID made from driver
and hardware identity. Drivers and collectors write under this ID in
`live.sdb`; Places select it. Its display name never controls routing.
→ [Stations and Archives](Stations-and-Archives)

**Plot** — A plot **definition**: a name, a timespan, and the readings in it.
Belongs to weewx-evo, not to a renderer. → [Plots](Plots)

**Policy** — Two meanings. (1) `obstypes.Policy`: how each observation
aggregates. (2) `sources.Policy`: optional low-level field arbitration, not
loaded by the configured Archiver.

**Provenance** — Which field came from which sender when the optional
`sources.Policy` API is used.
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

**Source** — Legacy wording in `sources.py`. Product configuration uses the
canonical **Sender** ID and Place membership instead.

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

**Placement** — Which archive column one raw reading is written into. Decided
in `placement.toml` and applied when a record is built, so changing one and
rebuilding moves the readings already stored → [Placements](Placements).

**Dialect** — A catalog: the same protocol with different field names, or the
same names in different units. Fine Offset firmwares speak Weather Underground
in Fahrenheit and inches, or in Celsius and millimetres, on one endpoint. One
protocol, two dialects. Recorded on every packet, because a raw name means
nothing without it.

**Identity** — What a console calls itself: a PASSKEY, a serial, a station id.
Together with the driver that read it, this is how a packet is recognised — the
pair determines its canonical Sender ID. A readable label is presentation
metadata and never changes routing.

**View** — `Settings.view(prefix, schema)`. The corner of the settings that
belongs to one component, and nothing else. A driver gets that, not the whole
thing.

**`wsum`** — The weighted sum: every value times the time it stood.

**`xsum` / `ysum`** — East and north components of the summed wind vectors. How
a mean direction survives being averaged.

<!-- covers
-->

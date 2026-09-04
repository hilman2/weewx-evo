# Testing

All tests run **without a network** and **without state outside a temp
directory**.

## Everything at once

```bash
python tools/difftest.py reference/weewx.sdb    # the arithmetic
python tools/roundtrip.py reference/weewx.sdb   # the writing
python tools/derive_test.py reference/weewx.sdb # the derived readings
python tools/seriestest.py reference/weewx.sdb  # the series (needs WeeWX)
python tools/unitcheck.py                       # every conversion
python tools/suncheck.py                        # sunrise and sunset
python tools/smoke.py                           # all of it together
python tools/multisource.py                     # several stations
python tools/driverinstall.py                   # third-party drivers
python tools/adminpage.py                       # the settings page
python tools/netaccess_test.py                  # who gets an answer
python tools/ratelimit_test.py                  # the two limits
python tools/settings_test.py                   # the precedence
python tools/export_test.py                     # FTP and rsync
python tools/web_test.py                        # routing and the directory boundary
```

Plus the six built-in push protocols:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && python -m pytest tests/push -q'
```

## What a test is worth here

The tests that found something all check the same pattern: **an assumption that
never shows up in a browser.**

| What was found | Where |
|---|---|
| A partial POST resetting everything else to the default | `adminpage.py` |
| A roundtrip in which `"5m"` comes back as a string instead of 300 | `adminpage.py` |
| SQLite connections are thread-bound | `smoke.py` |
| A console locking itself out after five **valid** uploads | `ratelimit_test.py` |
| Three transcription errors in the knot factors | `unitcheck.py` |
| pyephem counting refraction twice when given `horizon` | `suncheck.py` |
| `skip_if_empty = year` read as a boolean: 100 files instead of 71 | the plot importer |

Anyone adding one should look for **that sort of case**.

## The tools one by one

### `difftest.py` — the acceptance test

**The acceptance test for the whole project.** If weewx-evo's arithmetic cannot
reproduce the daily summaries of a database WeeWX wrote itself, then nothing
built on it is trustworthy, and no amount of good architecture makes up for it.

```bash
python tools/difftest.py reference/weewx.sdb
```

Two classes of column, two standards:

```python
SUM_COLUMNS     = {"sum", "count", "wsum", "sumtime", "xsum", "ysum",
                   "dirsumtime", "squaresum", "wsquaresum"}
EXTREME_COLUMNS = {"min", "mintime", "max", "maxtime", "max_dir"}
```

- **Sums** come exclusively from archive records and have to match **exactly**.
- **Extremes** may differ — but only **duller**, never sharper. Sharper would be
  a bug, and that is exactly what the test checks.

```
sum mismatches:            0
extremes sharper than DB:  0
extremes duller than DB:   189   (expected: LOOP highs/lows)
```

→ [Aggregation](Aggregation)

### `roundtrip.py` — the writing

`difftest` checks the arithmetic. This checks the **writing**: a copy of a real
database, the last N days deleted — archive records and daily summaries — and
written back over the **normal write path**, record by record, exactly as the
archiver would on a catch-up.

```bash
python tools/roundtrip.py reference/weewx.sdb --days 3
python tools/roundtrip.py reference/weewx.sdb --days 3 --packets
```

`--packets` feeds the stored LOOP packets back in (`feed_packets()`). Where they
cover the period, the number of dull extremes drops accordingly: **109 → 89 at
76 % coverage.**

That is the measurable evidence for the [live table](Database-Live).

`Tally` counts differences and keeps the first few of each kind to show.

### `derive_test.py` — the derived readings

The reference database has years of records in which WeeWX computed dewpoint,
heat index and the rest from readings that are **in the same row**. A test
oracle nobody had to write.

Plus `rain_tests()` (the one that is a measurement), `policy_tests()` (the three
policies) and `edge_tests()` (the edges of the domains).

→ [Derived-Readings](Derived-Readings)

### `seriestest.py` — the series

Asks **WeeWX and weewx-evo for the same series** and compares.

```python
TOLERANCE = 1e-06
```

94 comparisons, 19,957 points, 0 failures, 8 known departures — all eight of
them the [deliberate departure](Series#one-deliberate-departure) on the weighted
mean.

Needs an installed WeeWX.

### `unitcheck.py` — the units

All 147 conversions against WeeWX, at nine values:

```python
SAMPLES = (0.0, 1.0, -1.0, 7.5, 100.0, -40.0, 1013.25, 0.001, 98765.4321)
```

Plus groups, systems, labels and formats.

The failure mode this guards against is a **quiet** one: a factor that is out in
the fourth decimal place produces a plot that looks right and differs from
WeeWX's plot of the same day.

→ [Units](Units)

### `suncheck.py` — the sun

Six places from Tromsø to Ushuaia, five days including the four turning points
of the year, against pyephem **and** against `weeutil.Sun`.

```python
TOLERANCE = 60.0    # seconds
LOOSE     = 600.0
```

→ [Sun](Sun)

### `smoke.py` — all of it together

Starts a listener, posts **real** Ecowitt uploads at it, lets the archiver work
out the intervals and checks what landed.

This is the test that catches the bugs the individual tests cannot:

- a parser whose field names do not match the schema
- an archiver writing a record with no `interval`
- a listener answering before it has stored anything

`post()` returns both the body **and** the content type. Both count: the gateway
checks both.

### `archives_e2e.py` — two Places end to end

Starts the configured services with two Places and three canonical senders.
It checks that Place membership and an `extra` member route the packets into
the intended databases without station-owned archive assignments.

### `multisource.py` — routing boundary

Checks the retained low-level `sources.Policy` API, then builds the product
Archivers and proves that they use only Place membership, role and mapping.

→ [Multiple-Sources](Multiple-Sources)

### `driverinstall.py` — third-party drivers

Builds a driver package on disk the way somebody would publish one, installs it,
loads it and takes an upload with it.

The test that a third-party driver hangs off **the same interface** as a bundled
one.

→ [Drivers](Drivers)

### `adminpage.py` — the settings page

Renders the page, saves through it and breaks it on purpose. What is checked is
the chain **declaration → form → validation → file**, for every kind of setting
there is.

`multipart()` and `upload()` post a form the way a browser posts one with a file
in it — `SKIN` is a small `[ImageGenerator]` section. That checks the plot
importer over the real route as well, not over a detour round it.

→ [Admin-Page](Admin-Page)

### `netaccess_test.py` — who gets an answer

Drives both servers with a socket whose source address really is different. **A
peer address cannot be forged over TCP**, so this is really checkable and not
mocked.

### `ratelimit_test.py` — the two limits

And **that they are not the same limit**. Mixing the two gives you the worst of
both: either a limit loose enough to guess through, or one so tight that a
console locks itself out.

→ [Security](Security)

### `settings_test.py` — the precedence

Five places, one fixed order, one resolver. The order is easy to state and easy
to get subtly wrong, so it is nailed down here rather than described in a
comment.

**The part that is checked hardest is the one that looks like a detail**: an
argument that was *not* given must not beat the configuration file.

`args_with(**kwargs)` builds a namespace in which everything unnamed is `None` —
the way argparse leaves it.

### `export_test.py` — FTP and rsync

The FTP half runs against a server **in this process**: files land on disk,
directories come into existence, the move-into-place happens. No mock.

`pyftpdlib` is not a dependency of weewx-evo, so that part is skipped when it is
missing and the rest runs anyway.

The rsync half checks the command line — nothing goes through a shell.

`local_export()` checks the failure modes FTP does not have: a hard link
silently sharing an inode; a delete taking more with it than what this export
put there; a destination that is the source directory. And after that, that the
**web server really serves what the export published** — both halves of the
chain in one test.

`runner_tests()` uses a deliberately slow `FakeExport` to check when each export
runs and that one cannot hold another up.

→ [Exports](Exports)

### `web_test.py` — routing and the boundary

Serves a few files and tries to get out of the directory.

→ [Web-Server](Web-Server)

## What goes out

```bash
python tools/upload_test.py     # what goes to a weather service
python tools/mqtt_test.py       # the MQTT client, against a broker of our own
python tools/forecast_test.py   # the forecast sources and their store
python tools/realtime_test.py   # realtime.txt and wxnow.txt
python tools/deck_live_test.py  # the live display in the Deck skin
```

`deck_live_test.py` needs Cheetah and renders the real skin, with and without a
broker. Both are checked: that the live display appears **only** when one is
configured. A station with no broker showing a red OFFLINE on every card has
been given a fault it does not have.

None of these touches the network. `upload_test.py` and `forecast_test.py` build
requests and look at them; `mqtt_test.py` starts a broker on loopback.

`upload_test.py` additionally compares against WeeWX when it is importable — the
Ambient query parameter by parameter and the CWOP packet character by character.
Both are transcriptions, and a transcription is either identical or a bug:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && PYTHONPATH=/mnt/d/Git/weewx/src:src \
  python3 tools/upload_test.py'
```

## The driver tests

135 tests under `tests/push/`, covering all six built-in push protocols.

```bash
python -m pytest tests/push -q
```

They belong here now and are allowed to grow: the driver is core, not a mirrored
foreign repo.

→ [Push drivers](Driver-Ecowitt#the-tests)

## The reference data

`reference/` is in `.gitignore` — real readings, several megabytes.

Pulling a fresh copy:

```bash
ssh <host> 'docker exec weewx python3 -c "
import sqlite3
for s in [\"weewx.sdb\", \"weewx-loop.sdb\"]:
    c = sqlite3.connect(\"/data/archive/\" + s)
    c.execute(\"VACUUM INTO ?\", (\"/data/snap-\" + s,)); c.close()"'
scp <host>:/opt/weewx/data/snap-weewx.sdb reference/weewx.sdb
ssh <host> 'rm -f /opt/weewx/data/snap-*.sdb'
```

**`VACUUM INTO` rather than `cp`**: the database is being written to alongside,
and a copied WAL is a torn state.

## Dev tooling

All Python dev tools run in **WSL Ubuntu**, never with Windows Python:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && ruff check src tools tests'
```

The default WSL distro is `docker-desktop` and has no Python — hence always an
explicit `-d Ubuntu`.

Venvs live under `~/venvs/<project>` **inside** WSL, not in the repo on `/mnt/d`
(NTFS long-path bug).

<!-- covers
tools/difftest.py
tools/roundtrip.py
tools/derive_test.py
tools/seriestest.py
tools/unitcheck.py
tools/suncheck.py
tools/smoke.py
tools/multisource.py
tools/driverinstall.py
tools/adminpage.py
tools/netaccess_test.py
tools/ratelimit_test.py
tools/settings_test.py
tools/export_test.py
tools/web_test.py
tests/push/fixtures/README.md
pyproject.toml
tools/adminfields_test.py
tools/adminhome_test.py
tools/adminsearch_test.py
tools/alldrivers_test.py
tools/api_test.py
tools/archives_e2e.py
tools/archives_test.py
tools/cheetah_test.py
tools/collector_test.py
tools/weewxdrivers_test.py
tools/restart_test.py
tools/deck_dead_test.py
tools/deck_live_test.py
tools/deck_places_test.py
tools/deck_test.py
tools/docsindex.py
tools/driversim.py
tools/ecowittsim.py
tools/feeds_test.py
tools/feedtiming_test.py
tools/forecast_test.py
tools/fousb_test.py
tools/fousbsim.py
tools/grafana_test.py
tools/image_test.py
tools/import_test.py
tools/influx_test.py
tools/livedb_test.py
tools/livesource_test.py
tools/maintenance_test.py
tools/metrics_test.py
tools/mooncheck.py
tools/mqtt_test.py
tools/notify_test.py
tools/planetcheck.py
tools/quality_test.py
tools/realtime_test.py
tools/resilience_test.py
tools/roles_test.py
tools/runtests.py
tools/scaletest.py
tools/schedule_test.py
tools/sdr_test.py
tools/sdrsim.py
tools/setup_test.py
tools/shim_test.py
tools/standin_test.py
tools/stations_test.py
tools/stillweewx_test.py
tools/tagcheck.py
tools/upload_test.py
tools/vantage_test.py
tools/vantagesim.py
tools/vsop87trim.py
tools/watchdog_test.py
tools/wunderground_test.py
-->

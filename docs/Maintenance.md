# Maintenance

`maintenance.py`. Copying the archive, asking whether it is sound, and
reclaiming space.

```bash
weewx-evo backup            # a copy, while the station carries on
weewx-evo verify            # is it sound, and do the summaries follow?
weewx-evo vacuum            # reclaim what a deletion left
```

## `cp` is the trap

An archive is opened in WAL mode, so at any moment part of it is in
`weewx.sdb-wal` and not in `weewx.sdb`.

- Copying the file **alone** takes a database missing everything written
  since the last checkpoint.
- Copying all **three** files with `cp` takes them at three different
  instants, which is worse because the result opens.

Both fail the same way: silently, and only when somebody restores.

Measured in `tools/maintenance_test.py`: fifty records, copied both ways.
`sqlite3.Connection.backup` holds all fifty. `shutil.copy` holds none — and
depending on whether the schema is still in the log, it either opens empty or
does not open at all.

`backup` uses the SQLite backup API, which copies pages under a read lock and
retries the ones that change underneath it. **It works while the archiver is
writing**, which is the point: a backup nobody has to stop the station for.

Every copy is **opened before it is believed**. A backup nobody has opened is
a hope.

```
backups/weewx-20260829-041500.sdb
```

Named by the moment it was taken, which sorts chronologically as text — and
that is what `--keep` prunes by. Not by modification time: a file copied to
another disk keeps its name and gets a new timestamp, so pruning by time
would throw away the oldest *data* rather than the oldest backup.

## Verify asks two questions

```
PRAGMA quick_check          is the file sound?
archive vs archive_day_*    do the summaries still follow from the records?
```

The second is ours and the more useful. [`archive_day_*`](Daily-Summaries) is
a cache: all of it is derivable from `archive`, and `rebuild_day` is the
derivation. A day that no longer follows can be repaired —

```bash
weewx-evo verify
#   archive:default: 2280 record(s), 7 day(s) checked, 1 day(s) out of step
#     2026-08-20   weewx-evo rebuild 1787176800 1787263200
weewx-evo rebuild 1787176800 1787263200
```

— which is not true of anything in `archive` itself.

**Nothing is written.** `rebuild` is the command that changes something. A
check that repaired as it went would mean nobody ever found out how often it
was needed.

### Two things it has to know, or it cries wolf

A check that fires on every healthy installation is the same as no check.

**A stored extreme *sharper* than the records is right.** The daily summaries
take their highs and lows from LOOP packets, so a gust between two archive
records is in the summary and nowhere else — `difftest` counts 189 of those on
the reference database. Only the other direction is a fault: a summary
*duller* than the records it summarises means a record that never reached it.

**An empty row the rebuild adds is not damage.** Our rebuild primes every
reading the schema knows, so a day WeeWX left out of `archive_day_eventRain`
entirely comes back with an empty row. `roundtrip` counts 266 of them.

`--deep` walks every index as well (`integrity_check` rather than
`quick_check`). Minutes on a large file, so it is asked for rather than
assumed. `--days` limits the summary comparison to the most recent ones:
fifteen years is five and a half thousand rebuilds, and somebody checking
after a crash wants an answer this afternoon.

## Vacuum

Rewrites the file without its free pages. Worth doing after a column is
dropped or a long span deleted, and not otherwise — it rewrites the whole
database and needs room for a second copy while it does. `--least` skips
unless that many megabytes would come back.

`checkpoint()` folds the write-ahead log back into the database, which is what
makes the file on disk *be* the database again. Useful before copying one by
hand; `backup` does not need it.

## No schedule

These are commands. A backup that runs itself needs a retention policy, a
destination with room on it, and an answer to what happens when the disk
fills — and getting that wrong quietly is worse than a person remembering to
type it.

For an installation that wants one, a cron entry or a systemd timer:

```
15 4 * * *  cd /opt/weewx-evo && docker compose exec -T weewx-evo \
              weewx-evo backup --keep 14
```

`backup` refuses before it starts where there is not room, because a copy that
fills the disk can stop the archiver writing.

## Every connection is closed

`with sqlite3.connect(...)` commits the transaction and leaves the connection
**open**. Every connection in this module is wrapped in `contextlib.closing`
as well.

On Windows the held handle stops a finished copy being renamed, which is how
this was found. On Linux it is a leaked descriptor — the fault that once took
an instance down with 477 of them, three subsystems reporting errors and none
of them anywhere near the leak.

→ [Database-Archive](Database-Archive) · [Daily-Summaries](Daily-Summaries) · [Deployment](Deployment) · [Notifications](Notifications)

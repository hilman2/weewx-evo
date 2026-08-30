# Backups

Copying fifteen years of readings somewhere safe, and finding out whether they
are still sound.

## Do not use `cp`

The archive runs in WAL mode, so part of it is in `weewx.sdb-wal` and not in
`weewx.sdb`. Copying the file alone gives you a database missing everything
since the last checkpoint. Copying all three with `cp` is **worse**, because
the result opens.

Measured, fifty records, both ways: the proper copy has all fifty, `cp` has
none — and depending on whether the schema was still in the log, the copy comes
up empty or not at all. Either way it fails quietly, and the person who finds
out is the one restoring it.

```bash
weewx-evo backup /backup/weewx-$(date +%F).sdb
```

**It runs while the archiver is writing.** That is the point: no stopping the
station to make a copy.

**Every copy is opened before it is believed.** A backup nobody opened is a
hope.

It also refuses to start if there is not enough room — a copy that fills the
disk can stop the archiver recording, which is a cure worse than the disease.

## Is it still sound

```bash
weewx-evo verify
```

Two questions: whether SQLite thinks the file is intact, and whether the daily
summaries still follow from the records. The second is the one that is ours,
and a day that no longer follows is repairable:

```bash
weewx-evo rebuild <from> <to>
```

**`verify` writes nothing.** A check that quietly repairs on the way past
prevents anyone from ever learning how often it was needed.

It knows two things that would otherwise make it shout at every healthy
station. A stored extreme *sharper* than the records is correct — a gust
between two archive records lives in the daily summary and nowhere else. And an
empty row the rebuild *creates* is not damage.

## Reclaiming space

```bash
weewx-evo compact
```

After deleting a long stretch. SQLite does not hand the space back on its own.

## No schedule

These are commands, not a cron job that ships switched on. A backup that starts
itself needs a retention rule, a destination with room, and an answer to what
happens when the disk fills — and getting that quietly wrong is worse than
somebody remembering to type it.

→ [Maintenance](Maintenance), [Deployment](Deployment#backing-up)

<!-- watches
src/weewx_evo/maintenance.py
-->

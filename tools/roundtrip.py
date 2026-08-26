"""Rewrite part of a real database and check that nothing moved.

`difftest.py` checks the arithmetic. This checks the writing: it takes a copy
of a real database, deletes the last N days from it -- archive records and
daily summaries alike -- and puts them back through the normal write path, one
record at a time, exactly as the archiver would during a live catch-up.

    python tools/roundtrip.py reference/weewx.sdb --days 3

The deletion is the point. Anything that merely appends would pass while
quietly relying on state that a fresh installation does not have.

Three standards, because three kinds of column mean different things:

  * The archive table must come back byte for byte. It is the record of what
    was measured, and rewriting it may not change it.
  * Daily-summary sums must match exactly. They derive from archive records
    alone, so a difference is an arithmetic error.
  * Daily-summary extremes may come back duller. With `loop_hilo = True` the
    stored highs and lows include LOOP packets, which no longer exist. Duller
    is the expected loss; sharper would be a bug.

Pass `--packets reference/weewx-loop.sdb` to feed the LOOP packets back in as
well. Where they cover the period, the extremes must then come back exactly --
which is the whole argument for keeping them.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.aggregate import start_of_archive_day  # noqa: E402
from weewx_evo.db import schema as schema_mod  # noqa: E402
from weewx_evo.db.archive import ArchiveStore  # noqa: E402

SUM_COLUMNS = frozenset({"sum", "count", "wsum", "sumtime",
                         "xsum", "ysum", "dirsumtime", "squaresum", "wsquaresum"})


def table_rows(conn: sqlite3.Connection, table: str) -> dict:
    cursor = conn.execute(f"SELECT * FROM {table} ORDER BY dateTime")
    cols = [d[0] for d in cursor.description]
    return {row[0]: dict(zip(cols, row)) for row in cursor}


class Tally:
    """Counts differences, keeping the first few of each kind to show."""

    def __init__(self, limit: int = 6) -> None:
        self.limit = limit
        self.counts: dict[str, int] = {}
        self.examples: dict[str, list[str]] = {}

    def note(self, kind: str, detail: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        seen = self.examples.setdefault(kind, [])
        if len(seen) < self.limit:
            seen.append(detail)

    def count(self, kind: str) -> int:
        return self.counts.get(kind, 0)


def compare(before: dict, after: dict, table: str, is_daily: bool, tally: Tally) -> None:
    for key in sorted(set(before) | set(after)):
        if key not in after:
            tally.note("missing row", f"{table}: row {key} vanished")
            continue
        if key not in before:
            # An all-empty row is not a difference in the data. WeeWX writes
            # one for every observation it knows about on every day it touches,
            # so a table added later -- a new sensor, `weectl database
            # add-column` -- has no row for the days before it existed. Writing
            # those days again fills the gap with exactly the empty row WeeWX
            # itself would write. A row with actual statistics is another
            # matter and stays a failure.
            row = after[key]
            if row.get("count") == 0 and row.get("min") is None and row.get("max") is None:
                tally.note("empty row filled in", f"{table}: empty row {key} added")
            else:
                tally.note("extra row", f"{table}: row {key} appeared")
            continue
        for col, want in before[key].items():
            got = after[key].get(col)
            if want == got:
                continue
            where = f"{table}.{col} @ {key}: was {want!r}, now {got!r}"
            if not is_daily or col in SUM_COLUMNS:
                tally.note("archive" if not is_daily else "sum", where)
            elif col in ("min", "max") and want is not None and got is not None:
                sharper = (col == "min" and got < want) or (col == "max" and got > want)
                tally.note("sharper extreme" if sharper else "duller extreme", where)
            else:
                # A timestamp moving with its extreme, or an extreme that is
                # now absent because no archive record carried the value.
                tally.note("duller extreme", where)


def feed_packets(store: ArchiveStore, packet_db: Path, after: int) -> int:
    """Fold stored LOOP packets into the daily highs and lows.

    This is WeeWX's `_updateHiLo`, done afterwards from storage instead of
    live from memory. The packets go through one accumulator per archive
    interval and only that accumulator's extremes are merged into the day --
    the sums arrived with the archive record already.

    The interval boundaries come from the archive records themselves. Each
    record carries the span it stands for in `interval`, and an installation
    that changed its archive interval has both lengths in one table.
    """
    import json

    from weewx_evo.aggregate import Accumulator

    conn = sqlite3.connect(f"file:{packet_db}?mode=ro", uri=True)
    packets = conn.execute(
        "SELECT dateTime, usUnits, data FROM packets WHERE dateTime > ? ORDER BY dateTime",
        (after,),
    ).fetchall()
    conn.close()
    if not packets:
        return 0

    spans = store.conn.execute(
        f"SELECT dateTime, interval, usUnits FROM {store.table_name}"
        " WHERE dateTime > ? ORDER BY dateTime", (after,),
    ).fetchall()

    fed, at = 0, 0
    for stop, interval, units in spans:
        start = stop - int((interval or 0) * 60)
        accum = Accumulator(start, stop, policy=store.policy)
        n = 0
        while at < len(packets) and packets[at][0] <= start:
            at += 1  # a packet before this record's span; no record claims it
        while at < len(packets) and packets[at][0] <= stop:
            ts, packet_units, data = packets[at]
            record = json.loads(data)
            record["dateTime"] = ts
            record["usUnits"] = packet_units
            accum.add_record(record, weight=1)
            n += 1
            at += 1
        if not n:
            continue

        sod = start_of_archive_day(stop)
        day = store._load_day(sod, units)
        day.merge_hilo(accum)
        with store.conn:
            store._store_day(sod, day)
        fed += n
    return fed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("database", type=Path)
    parser.add_argument("--days", type=int, default=3, help="how many days to rewrite")
    parser.add_argument("--table", default="archive")
    parser.add_argument("--packets", type=Path, help="a weewx-loop.sdb to feed back in")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "roundtrip.sdb"
        shutil.copy(args.database, work)

        conn = sqlite3.connect(work)
        schema = schema_mod.read(conn, args.table)
        before = {args.table: table_rows(conn, args.table)}
        for obs_type in schema.day_types:
            before[f"{args.table}_day_{obs_type}"] = table_rows(
                conn, f"{args.table}_day_{obs_type}")

        last_ts = conn.execute(f"SELECT max(dateTime) FROM {args.table}").fetchone()[0]
        cutoff = start_of_archive_day(last_ts) - (args.days - 1) * 86400

        cursor = conn.execute(
            f"SELECT * FROM {args.table} WHERE dateTime > ? ORDER BY dateTime", (cutoff,))
        cols = [d[0] for d in cursor.description]
        records = [{c: v for c, v in zip(cols, row) if v is not None} for row in cursor]

        print(f"{args.database}")
        print(f"  rewriting {len(records)} records from {args.days} day(s) after {cutoff}")

        conn.execute(f"DELETE FROM {args.table} WHERE dateTime > ?", (cutoff,))
        for obs_type in schema.day_types:
            conn.execute(
                f"DELETE FROM {args.table}_day_{obs_type} WHERE dateTime >= ?", (cutoff,))
        conn.commit()
        conn.close()

        with ArchiveStore(work, table_name=args.table) as store:
            written = store.add_records(records)
            print(f"  wrote {written} records back")
            if args.packets:
                n = feed_packets(store, args.packets, cutoff)
                print(f"  folded in {n} LOOP packets from {args.packets}")

        conn = sqlite3.connect(work)
        tally = Tally()
        for table, snapshot in before.items():
            compare(snapshot, table_rows(conn, table), table,
                    is_daily=table != args.table, tally=tally)
        conn.close()

    print()
    print(f"  archive table differences: {tally.count('archive')}")
    print(f"  daily sum differences:     {tally.count('sum')}")
    print(f"  extremes sharper:          {tally.count('sharper extreme')}")
    print(f"  extremes duller:           {tally.count('duller extreme')}"
          "   (expected: LOOP highs/lows)")
    for kind in ("missing row", "extra row", "empty row filled in"):
        if tally.count(kind):
            print(f"  {kind}: {tally.count(kind)}")

    fatal = ("archive", "sum", "sharper extreme", "missing row", "extra row")
    failed = any(tally.count(k) for k in fatal)
    for kind in fatal:
        if tally.count(kind):
            print(f"\n{kind.upper()}  ({tally.count(kind)})")
            for line in tally.examples[kind]:
                print(f"  {line}")

    print("\n" + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

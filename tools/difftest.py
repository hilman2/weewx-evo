"""Rebuild a real database's daily summaries and compare them to what is stored.

This is the acceptance test for the whole project. If weewx-evo's arithmetic
cannot reproduce the daily summaries of a database WeeWX itself wrote, nothing
built on top of it is trustworthy, and no amount of architecture makes up for it.

    python tools/difftest.py reference/weewx.sdb

Two classes of column are checked differently, and the difference is the point:

  * Sums (sum, count, wsum, sumtime, xsum, ysum, dirsumtime, squaresum,
    wsquaresum) come only from archive records. They must match.

  * Extremes (min, max, and their timestamps) may legitimately differ. With
    `loop_hilo = True` WeeWX folds LOOP packets straight into the daily highs
    and lows, so a stored extreme can be sharper than any archive record. A
    rebuild can only ever be equal or duller -- never sharper. Sharper means a
    real bug, and that is what this test reports.

That asymmetry is the strongest argument for keeping raw packets: today those
extremes cannot be recomputed. `weectl database rebuild-daily` silently blunts
them, and nobody notices because there is nothing left to compare against.
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.db import daily, schema as schema_mod  # noqa: E402

SUM_COLUMNS = frozenset({"sum", "count", "wsum", "sumtime",
                         "xsum", "ysum", "dirsumtime", "squaresum", "wsquaresum"})
EXTREME_COLUMNS = frozenset({"min", "mintime", "max", "maxtime", "max_dir"})


def close_enough(a, b, rel_tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=1e-12)
    return a == b


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("database", type=Path)
    parser.add_argument("--table", default="archive")
    parser.add_argument("--rel-tol", type=float, default=1e-9,
                        help="relative tolerance for sums (default: 1e-9)")
    parser.add_argument("--show", type=int, default=20, help="how many differences to print")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    schema = schema_mod.read(conn, args.table)

    n_records = conn.execute(f"SELECT count(*) FROM {args.table}").fetchone()[0]
    print(f"{args.database}")
    print(f"  {n_records} records, {len(schema.columns)} columns, "
          f"{len(schema.day_types)} daily tables, summary version {schema.version}")
    vectors = [t for t, k in schema.day_types.items() if k == "vector"]
    print(f"  vector types: {', '.join(vectors) or 'none'}")
    print()

    checked = exact = 0
    sum_diffs: list[str] = []
    sharper: list[str] = []
    blunter = 0
    missing_days: list[str] = []

    for sod_ts, accum in daily.build(daily.read_records(conn, schema)):
        for obs_type in accum:
            if obs_type not in schema.day_types:
                # An observation with no daily table. WeeWX ignores these too:
                # the tables are created when the database is, not on the fly.
                continue
            kind = schema.day_types[obs_type]
            stored = daily.read_day(conn, schema, obs_type, sod_ts)
            if stored is None:
                missing_days.append(f"{obs_type} @ {sod_ts}")
                continue

            computed = accum[obs_type].stats_tuple()
            for col, want, got in zip(schema_mod.STATS_COLUMNS[kind], stored, computed):
                checked += 1
                if close_enough(want, got, args.rel_tol):
                    exact += 1
                    continue
                where = f"{obs_type}.{col} @ {sod_ts}"
                if col in SUM_COLUMNS:
                    sum_diffs.append(f"{where}: stored={want!r} computed={got!r}")
                elif col in EXTREME_COLUMNS:
                    # Is the rebuild claiming a sharper extreme than the stored
                    # one? That cannot come from missing LOOP data.
                    is_sharper = (
                        (col == "min" and want is not None and got is not None and got < want)
                        or (col == "max" and want is not None and got is not None and got > want)
                    )
                    if is_sharper:
                        sharper.append(f"{where}: stored={want!r} computed={got!r}")
                    else:
                        blunter += 1

    print(f"checked {checked} values across {len(schema.day_types)} types")
    print(f"  identical:                 {exact} ({100 * exact / max(checked, 1):.3f} %)")
    print(f"  sum mismatches:            {len(sum_diffs)}")
    print(f"  extremes sharper than DB:  {len(sharper)}")
    print(f"  extremes duller than DB:   {blunter}   (expected: LOOP highs/lows)")
    if missing_days:
        print(f"  days with no stored row:   {len(missing_days)}")

    for label, items in (("SUM MISMATCH", sum_diffs), ("SHARPER EXTREME", sharper)):
        if not items:
            continue
        print(f"\n{label}  ({len(items)}, showing {min(args.show, len(items))})")
        for line in items[:args.show]:
            print(f"  {line}")

    failed = bool(sum_diffs or sharper)
    print("\n" + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

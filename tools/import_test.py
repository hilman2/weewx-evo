#!/usr/bin/env python3
"""Readings that live in somebody else's database, brought here.

`adopt.py` takes over a `weewx.sdb` by opening it -- the same file, no
conversion. MySQL and Postgres are the other half, and this is what checks
it: a dump written the way `mysqldump` and `pg_dump` write one, read into a
real archive, and every record compared against what went in.

The three faults this is shaped around, because each is silent:

  * **A wrong column order.** `mysqldump` writes no column list by default,
    so the order is the `CREATE TABLE`'s. Read in the wrong order every
    reading lands in the wrong column, every number is plausible, and the
    charts look like a station somewhere else.
  * **A cache older than its data.** An import writes into `archive`; the
    daily summaries are derived from it. Written and not rebuilt, every
    query that goes through `archive_day_*` -- which is most of them --
    answers about the readings that were there before.
  * **A zero where nothing was measured.** A station with no rain gauge and
    one in a drought must not come out the same.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import dumps, dumpscsv, units  # noqa: E402
from weewx_evo.db.archive import ArchiveStore  # noqa: E402

CHECKS = 0
FAILURES: list[str] = []


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")
        print(f"  FAIL {what}: {got!r} != {want!r}")
    else:
        print(f"  ok   {what}: {got!r}")


#: What goes into every fixture. Four records, one with a hole in it, and a
#: column the destination archive does not have.
RECORDS = [
    {"dateTime": 1756308600, "usUnits": 1, "interval": 5,
     "outTemp": 62.1, "outHumidity": 71.0, "rain": 0.0, "soilTemp5": 9.9},
    {"dateTime": 1756308900, "usUnits": 1, "interval": 5,
     "outTemp": 62.6, "outHumidity": None, "rain": 0.02, "soilTemp5": 9.9},
    {"dateTime": 1756309200, "usUnits": 1, "interval": 5,
     "outTemp": 63.0, "outHumidity": 69.0, "rain": 0.0, "soilTemp5": 10.1},
    {"dateTime": 1756309500, "usUnits": 1, "interval": 5,
     "outTemp": 63.4, "outHumidity": 68.0, "rain": None, "soilTemp5": 10.2},
]

COLUMNS = ("dateTime", "usUnits", "interval", "outTemp", "outHumidity",
           "rain", "soilTemp5")


def mysql_dump(path: Path, named: bool = False) -> Path:
    """A file the shape `mysqldump` writes.

    Including the parts that trip a parser: a comment header, another
    table's rows, a string with a comma and an escaped quote in it, and all
    four records in one INSERT.
    """
    def literal(value: object) -> str:
        return "NULL" if value is None else repr(value)

    rows = ",".join(
        "(" + ",".join(literal(row.get(name)) for name in COLUMNS) + ")"
        for row in RECORDS)
    columns = ("(" + ",".join(f"`{one}`" for one in COLUMNS) + ") "
               if named else "")

    path.write_text(f"""-- MySQL dump 10.13  Distrib 8.0.35
--
-- Host: localhost    Database: weewx
-- ------------------------------------------------------
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;

DROP TABLE IF EXISTS `archive`;
CREATE TABLE `archive` (
  `dateTime` int(11) NOT NULL,
  `usUnits` int(11) NOT NULL,
  `interval` int(11) NOT NULL,
  `outTemp` double DEFAULT NULL,
  `outHumidity` double DEFAULT NULL,
  `rain` double DEFAULT NULL,
  `soilTemp5` double DEFAULT NULL,
  PRIMARY KEY (`dateTime`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS `archive_day_outTemp`;
CREATE TABLE `archive_day_outTemp` (
  `dateTime` int(11) NOT NULL,
  `min` double DEFAULT NULL,
  `max` double DEFAULT NULL,
  PRIMARY KEY (`dateTime`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

LOCK TABLES `archive` WRITE;
INSERT INTO `archive` {columns}VALUES {rows};
UNLOCK TABLES;

LOCK TABLES `archive_day_outTemp` WRITE;
INSERT INTO `archive_day_outTemp` VALUES (1756252800,55.0,999.0);
UNLOCK TABLES;
""", encoding="utf-8")
    return path


def postgres_dump(path: Path) -> Path:
    """A file the shape `pg_dump` writes: COPY blocks, tabs, backslash-N."""
    def cell(value: object) -> str:
        return "\\N" if value is None else str(value)

    rows = "\n".join(
        "\t".join(cell(row.get(name)) for name in COLUMNS)
        for row in RECORDS)

    path.write_text(f"""--
-- PostgreSQL database dump
--

SET statement_timeout = 0;

CREATE TABLE public.archive (
    "dateTime" integer NOT NULL,
    "usUnits" integer NOT NULL,
    "interval" integer NOT NULL,
    "outTemp" double precision,
    "outHumidity" double precision,
    rain double precision,
    "soilTemp5" double precision
);

CREATE TABLE public.archive_day_outTemp (
    "dateTime" integer NOT NULL,
    min double precision,
    max double precision
);

COPY public.archive_day_outTemp ("dateTime", min, max) FROM stdin;
1756252800\t55.0\t999.0
\\.

COPY public.archive ({", ".join(f'"{one}"' for one in COLUMNS)}) FROM stdin;
{rows}
\\.

--
-- PostgreSQL database dump complete
--
""", encoding="utf-8")
    return path


def an_archive(path: Path) -> ArchiveStore:
    """An archive with one record in it, and no `soilTemp5` column.

    Missing on purpose: a real installation has columns this one does not,
    and what happens to those readings is the question. Built by writing a
    record rather than by hand, so the summary tables and the metadata are
    the ones this program makes -- an archive assembled with CREATE TABLE
    here would be testing a shape nothing produces.

    The seed record is a year earlier than the fixtures, so it is a day of
    its own and cannot be mistaken for one of them.
    """
    store = ArchiveStore(path)
    store.add_record({"dateTime": 1724772600, "usUnits": 1, "interval": 5,
                      "outTemp": 50.0, "outHumidity": 80.0, "rain": 0.0})
    store.conn.commit()
    return store


# ---------------------------------------------------------------------------
# The dumps.
# ---------------------------------------------------------------------------

def test_a_mysql_dump_is_read(tmp: Path) -> None:
    print("\na mysqldump, read into an archive")
    source = mysql_dump(tmp / "mysql.sql")

    found = dumps.inspect(source)
    check("it is recognised", found.dialect, "mysql")
    check("all four records", found.records, 4)
    check("and the columns come from the CREATE TABLE",
          found.columns, list(COLUMNS))
    check("the first and last are right",
          (found.first, found.last), (1756308600, 1756309500))

    store = an_archive(tmp / "one.sdb")
    try:
        written = dumps.into(source, store)
        check("every record was written", written.records, 4)
        check("and the one column the archive has not is named",
              any("soilTemp5" in note for note in written.notes), True)

        rows = list(store.conn.execute(
            "SELECT dateTime, outTemp, outHumidity, rain FROM archive "
            "ORDER BY dateTime"))
        check("four rows, after the one it was seeded with",
          len(rows), 5)
        check("the temperatures came through in order",
              [row[1] for row in rows[1:]], [62.1, 62.6, 63.0, 63.4])
        check("a NULL humidity is absent, not zero", rows[2][2], None)
        check("and a real zero is a zero", rows[1][3], 0.0)
    finally:
        store.close()


def test_the_column_order_comes_from_the_create_table(tmp: Path) -> None:
    """`mysqldump` writes no column list by default.

    Read in the wrong order every reading lands in the wrong column, every
    number is plausible, and the charts look like a station somewhere else.
    """
    print("\nan INSERT that names no columns")
    unnamed = mysql_dump(tmp / "unnamed.sql", named=False)
    named = mysql_dump(tmp / "named.sql", named=True)

    check("the unnamed dump really has no column list",
          "INSERT INTO `archive` VALUES" in unnamed.read_text(encoding="utf-8"),
          True)

    one = list(dumps.Dump(unnamed).records())
    two = list(dumps.Dump(named).records())
    check("both read the same records", one, two)
    check("and the temperature is a temperature",
          [r["outTemp"] for r in one], [62.1, 62.6, 63.0, 63.4])


def test_a_postgres_dump_is_read(tmp: Path) -> None:
    print("\na pg_dump, read into an archive")
    source = postgres_dump(tmp / "pg.sql")

    found = dumps.inspect(source)
    check("it is recognised", found.dialect, "postgres")
    check("all four records", found.records, 4)

    store = an_archive(tmp / "two.sdb")
    try:
        written = dumps.into(source, store)
        check("every record was written", written.records, 4)
        rows = list(store.conn.execute(
            "SELECT dateTime, outTemp, outHumidity FROM archive "
            "ORDER BY dateTime"))
        check("the temperatures came through",
              [row[1] for row in rows[1:]], [62.1, 62.6, 63.0, 63.4])
        check("and backslash-N is absent, not the text",
              rows[2][2], None)
    finally:
        store.close()


def test_another_table_s_rows_do_not_land_in_the_archive(tmp: Path) -> None:
    """Both fixtures carry an `archive_day_outTemp` with a maximum of 999.

    A parser that takes every COPY block, or every INSERT, puts that row in
    `archive` -- and 999 degrees is then the station's record high for ever.
    """
    print("\nrows belonging to another table")
    for name, make in (("mysql", mysql_dump), ("postgres", postgres_dump)):
        source = make(tmp / f"other-{name}.sql")
        stamps = [r["dateTime"] for r in dumps.Dump(source).records()]
        check(f"{name}: only the archive's own rows",
              sorted(stamps), [1756308600, 1756308900, 1756309200, 1756309500])
        check(f"{name}: and the summary row is not among them",
              1756252800 in stamps, False)


def test_the_daily_summaries_are_built_as_it_goes(tmp: Path) -> None:
    """The trap named in the plan.

    An import writes into `archive`, and the summaries are derived from it.
    Written and not rebuilt, every query that goes through `archive_day_*`
    answers about the readings that were there before -- which is most
    queries, and nothing complains.
    """
    print("\nthe cache must not be older than the data")
    source = mysql_dump(tmp / "daily.sql")
    store = an_archive(tmp / "three.sdb")
    try:
        dumps.into(source, store)
        rows = list(store.conn.execute(
            "SELECT dateTime, count, min, max FROM archive_day_outTemp "
            "WHERE count > 1 ORDER BY dateTime DESC"))
        check("the imported day was summarised", len(rows), 1)
        check("with every record in it", rows[0][1], 4)
        check("the lowest is the lowest", rows[0][2], 62.1)
        check("and the highest is the highest", rows[0][3], 63.4)
    finally:
        store.close()


def test_a_second_run_writes_nothing_unless_asked(tmp: Path) -> None:
    """Off by default: an import that silently replaced measurements would
    be the one operation here that cannot be undone."""
    print("\nrunning it twice")
    source = mysql_dump(tmp / "twice.sql")
    store = an_archive(tmp / "four.sdb")
    try:
        first = dumps.into(source, store)
        second = dumps.into(source, store)
        check("the first run wrote them", first.records, 4)
        check("the second wrote nothing", second.records, 0)
        check("and there are still four, plus the seed",
              store.conn.execute(
                  "SELECT COUNT(*) FROM archive").fetchone()[0], 5)
    finally:
        store.close()


def test_a_string_with_a_comma_in_it(tmp: Path) -> None:
    """A tuple is split on commas, and a comma can be inside a string.

    Rare in weather data and exactly the installation somebody has: a text
    column for the station's own notes.
    """
    print("\na string with a comma and a quote in it")
    path = tmp / "text.sql"
    path.write_text(
        "CREATE TABLE `archive` (\n"
        "  `dateTime` int(11) NOT NULL,\n"
        "  `usUnits` int(11) NOT NULL,\n"
        "  `note` varchar(255) DEFAULT NULL,\n"
        "  `outTemp` double DEFAULT NULL\n"
        ") ENGINE=InnoDB;\n"
        "INSERT INTO `archive` VALUES "
        "(1756308600,1,'hail, then rain',62.1),"
        "(1756308900,1,'it\\'s clear',62.6);\n",
        encoding="utf-8")

    rows = list(dumps.Dump(path).records())
    check("both records", len(rows), 2)
    check("the comma stayed inside the string", rows[0]["note"],
          "hail, then rain")
    check("and the temperature after it is right", rows[0]["outTemp"], 62.1)
    check("an escaped quote came through", rows[1]["note"], "it's clear")
    check("and so did the number after it", rows[1]["outTemp"], 62.6)


# ---------------------------------------------------------------------------
# CSV.
# ---------------------------------------------------------------------------

def test_a_csv_is_read(tmp: Path) -> None:
    print("\na CSV of readings")
    path = tmp / "readings.csv"
    path.write_text(
        "dateTime,outTemp,outHumidity,rain,Wind Chill\n"
        "1756308600,62.1,71,0.0,60.0\n"
        "1756308900,62.6,,0.02,60.5\n"
        "1756309200,63.0,69,N/A,61.0\n",
        encoding="utf-8")

    found = dumpscsv.inspect(path)
    check("three records", found.records, 3)
    check("the time column was found", found.time_column, "dateTime")
    check("a column that is not a reading is left out",
          "Wind Chill" in found.ignored, True)
    check("and said out loud",
          any("Wind Chill" in note for note in found.notes), True)

    store = an_archive(tmp / "csv.sdb")
    try:
        written = dumpscsv.into(path, store)
        check("every row was written", written.records, 3)
        rows = list(store.conn.execute(
            "SELECT outTemp, outHumidity, rain FROM archive "
            "WHERE dateTime > 1756000000 ORDER BY dateTime"))
        check("the temperatures", [row[0] for row in rows], [62.1, 62.6, 63.0])
        check("an empty cell is absent, not zero", rows[1][1], None)
        check("and so is N/A", rows[2][2], None)
    finally:
        store.close()


def test_a_csv_says_what_units_it_is_in(tmp: Path) -> None:
    """A CSV states no units, and getting it wrong writes Fahrenheit into a
    Celsius column. The same fault the live push had twice."""
    print("\nunits are stated, not inferred")
    path = tmp / "units.csv"
    path.write_text("dateTime,outTemp\n1756308600,20.1\n", encoding="utf-8")

    for asked, wanted in (("us", units.US), ("metric", units.METRIC),
                          ("metricwx", units.METRICWX)):
        store = an_archive(tmp / f"u-{asked}.sdb")
        try:
            dumpscsv.into(path, store, unit_system=asked)
            # Past the seed record, which is US whatever this asks for.
            got = store.conn.execute(
                "SELECT usUnits FROM archive WHERE dateTime > 1756000000"
            ).fetchone()[0]
            check(f"--units {asked}", got, wanted)
        finally:
            store.close()


def test_the_times_a_csv_can_carry(tmp: Path) -> None:
    """Epoch and ISO are unambiguous. Everything else needs saying."""
    print("\nreading the time")
    check("epoch seconds", dumpscsv._stamp("1756308600"), 1756308600)
    check("milliseconds are noticed",
          dumpscsv._stamp("1756308600000"), 1756308600)
    check("ISO with a T", dumpscsv._stamp("2026-08-27T18:30:00") is not None,
          True)
    check("ISO with a space", dumpscsv._stamp("2026-08-27 18:30:00") is not None,
          True)
    check("a European date needs a format",
          dumpscsv._stamp("27.08.2026 18:30"), None)
    check("and then it works",
          dumpscsv._stamp("27.08.2026 18:30", "%d.%m.%Y %H:%M") is not None,
          True)


def test_a_csv_with_no_time_column_is_refused(tmp: Path) -> None:
    """A CSV with no time is not a series of readings, and inventing one
    would date every record to the moment of the import."""
    print("\na CSV with no time in it")
    path = tmp / "notime.csv"
    path.write_text("outTemp,outHumidity\n62.1,71\n", encoding="utf-8")

    found = dumpscsv.inspect(path)
    check("nothing was read", found.records, 0)
    check("and the answer says what to do",
          any("--time-column" in note for note in found.notes), True)


def test_a_german_spreadsheet(tmp: Path) -> None:
    """Semicolons and comma decimals, which is what Excel writes here."""
    print("\na semicolon-separated file with comma decimals")
    path = tmp / "de.csv"
    path.write_text(
        "dateTime;outTemp;outHumidity\n"
        "1756308600;20,1;71\n"
        "1756308900;20,6;70\n",
        encoding="utf-8")

    store = an_archive(tmp / "de.sdb")
    try:
        written = dumpscsv.into(path, store, delimiter=";",
                                unit_system="metricwx")
        check("both rows", written.records, 2)
        rows = list(store.conn.execute(
            "SELECT outTemp FROM archive WHERE dateTime > 1756000000 "
            "ORDER BY dateTime"))
        check("the comma decimal was read", [row[0] for row in rows],
              [20.1, 20.6])
    finally:
        store.close()

    check("but a thousands separator is not a decimal point",
          dumpscsv._number("1,234.5"), 1234.5)


def test_rows_out_of_order_still_summarise(tmp: Path) -> None:
    """A spreadsheet is as likely to be newest-first as oldest-first, and
    `add_records` needs ascending time."""
    print("\nnewest first")
    path = tmp / "backwards.csv"
    path.write_text(
        "dateTime,outTemp\n"
        "1756309200,63.0\n"
        "1756308900,62.6\n"
        "1756308600,62.1\n",
        encoding="utf-8")

    store = an_archive(tmp / "back.sdb")
    try:
        dumpscsv.into(path, store)
        rows = list(store.conn.execute(
            "SELECT dateTime, count, min, max FROM archive_day_outTemp "
            "WHERE count > 1"))
        check("one day, summarised once", len(rows), 1)
        check("with all three records", rows[0][1], 3)
        check("the lowest is the lowest", rows[0][2], 62.1)
        check("and the highest is the highest", rows[0][3], 63.0)
    finally:
        store.close()


def test_a_dump_with_no_interval_still_writes(tmp: Path) -> None:
    """The silent one.

    `interval` is NOT NULL in the archive, and `INSERT OR IGNORE` -- which is
    what makes an import idempotent -- treats a NOT NULL violation as
    something to ignore. So a dump without that column wrote nothing at all,
    reported every row as read, and left the archive as it found it. Nothing
    raised and nothing was logged.
    """
    print("\na dump with no interval column")
    path = tmp / "nointerval.sql"
    path.write_text(
        "CREATE TABLE `archive` (\n"
        "  `dateTime` int(11) NOT NULL,\n"
        "  `usUnits` int(11) NOT NULL,\n"
        "  `outTemp` double DEFAULT NULL\n"
        ") ENGINE=InnoDB;\n"
        "INSERT INTO `archive` VALUES "
        "(1756308600,1,62.1),(1756308900,1,62.6),(1756309200,1,63.0);\n",
        encoding="utf-8")

    store = an_archive(tmp / "nointerval.sdb")
    try:
        found = dumps.into(path, store)
        check("every record was written", found.records, 3)
        check("and they are really there",
              store.conn.execute(
                  "SELECT COUNT(*) FROM archive WHERE dateTime > 1756000000"
              ).fetchone()[0], 3)
        check("the interval came from the gaps",
              [row[0] for row in store.conn.execute(
                  'SELECT "interval" FROM archive '
                  "WHERE dateTime > 1756000000")], [5, 5, 5])
        check("and it is said out loud",
              any("interval" in note for note in found.notes), True)

        # Which matters because every average is weighted by it.
        summary = store.conn.execute(
            "SELECT count, wsum, sumtime FROM archive_day_outTemp "
            "WHERE count = 3").fetchone()
        check("the day was summarised", summary is not None, True)
        check("with time behind it, not zero", summary[2] > 0, True)
    finally:
        store.close()


def test_a_csv_with_no_interval_still_writes(tmp: Path) -> None:
    """The same fault on the other importer. A CSV almost never has one."""
    print("\na CSV with no interval column")
    path = tmp / "nointerval.csv"
    path.write_text(
        "dateTime,outTemp\n"
        "1756308600,62.1\n1756308900,62.6\n1756309200,63.0\n",
        encoding="utf-8")

    store = an_archive(tmp / "csvnointerval.sdb")
    try:
        found = dumpscsv.into(path, store)
        check("every row was written", found.records, 3)
        check("and they are really there",
              store.conn.execute(
                  "SELECT COUNT(*) FROM archive WHERE dateTime > 1756000000"
              ).fetchone()[0], 3)
        check("five minutes, from the timestamps",
              [row[0] for row in store.conn.execute(
                  'SELECT "interval" FROM archive '
                  "WHERE dateTime > 1756000000")], [5, 5, 5])
        check("said out loud", any("interval" in note for note in found.notes),
              True)
    finally:
        store.close()


def test_an_interval_can_be_stated(tmp: Path) -> None:
    """A file whose rows are hourly averages of five-minute readings has an
    interval nothing in it can show."""
    print("\nstating the interval")
    path = tmp / "stated.csv"
    path.write_text(
        "dateTime,outTemp\n1756308600,62.1\n1756312200,62.6\n",
        encoding="utf-8")

    store = an_archive(tmp / "stated.sdb")
    try:
        dumpscsv.into(path, store, interval=5)
        check("the stated one wins over the gaps",
              [row[0] for row in store.conn.execute(
                  'SELECT "interval" FROM archive '
                  "WHERE dateTime > 1756000000")], [5, 5])
    finally:
        store.close()


def test_a_file_that_states_its_own_interval_keeps_it(tmp: Path) -> None:
    """A WeeWX export has the column, and it is the truth about that
    installation rather than something to work out again."""
    print("\na file that states its own")
    path = tmp / "own.csv"
    path.write_text(
        "dateTime,interval,outTemp\n"
        "1756308600,15,62.1\n1756309500,15,62.6\n",
        encoding="utf-8")

    store = an_archive(tmp / "own.sdb")
    try:
        found = dumpscsv.into(path, store)
        check("the file's own interval stands",
              [row[0] for row in store.conn.execute(
                  'SELECT "interval" FROM archive '
                  "WHERE dateTime > 1756000000")], [15, 15])
        check("and nothing is said about working one out",
              any("gaps between rows" in note for note in found.notes), False)
    finally:
        store.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        test_a_mysql_dump_is_read(tmp)
        test_the_column_order_comes_from_the_create_table(tmp)
        test_a_postgres_dump_is_read(tmp)
        test_another_table_s_rows_do_not_land_in_the_archive(tmp)
        test_the_daily_summaries_are_built_as_it_goes(tmp)
        test_a_second_run_writes_nothing_unless_asked(tmp)
        test_a_string_with_a_comma_in_it(tmp)
        test_a_csv_is_read(tmp)
        test_a_csv_says_what_units_it_is_in(tmp)
        test_the_times_a_csv_can_carry(tmp)
        test_a_csv_with_no_time_column_is_refused(tmp)
        test_a_german_spreadsheet(tmp)
        test_rows_out_of_order_still_summarise(tmp)
        test_a_dump_with_no_interval_still_writes(tmp)
        test_a_csv_with_no_interval_still_writes(tmp)
        test_an_interval_can_be_stated(tmp)
        test_a_file_that_states_its_own_interval_keeps_it(tmp)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} of {CHECKS} checks failed:\n")
        for failure in FAILURES:
            print(f"  {failure}\n")
        return 1
    print(f"import: {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

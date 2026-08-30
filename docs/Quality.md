# Quality control

`quality.py` and `quality.toml`. Calibration, and the limits a reading has to
survive before it reaches the archive.

WeeWX has `StdCalibrate` and `StdQC`; this had neither, and `weewxconf.py`
said so at the top of every import. With one console that is a blemish. With
ten it is why an archive holds rubbish after a year:

- a sensor with a flat battery reports −40
- a rain gauge being flushed reports 300 mm/h
- a radio sensor at the edge of its range repeats one figure for a quarter of
  an hour

All three go into `archive`, and `archive` is the one thing here that cannot
be rebuilt from anything else.

Nothing is configured by default. Most installations never write a
`quality.toml`, and the ones that do are answering a problem they have met.

## Where it runs

In the [archiver](Archiver), on each packet, before [deriving](Derived-Readings):

```
live packets ── calibrate ── check ── derive ── accumulate ── record
```

**Per packet, not on the finished record.** A spike that reaches the
accumulator has already set the interval's minimum and pulled its mean, and
nothing takes either back out. Measured on a real archive: ten packets with
one reading of −41 give a mean of 13.6 and a daily low of −41 without rules,
and 20.45 and 20.1 with them.

**Before deriving,** because the dew point is computed from the temperature.
A reading corrected afterwards leaves a dew point belonging to a number
nothing recorded.

**In the archiver rather than the listener,** because the [live
table](Database-Live) keeps the raw reading. A limit set too tightly is
repairable for as long as the retention lasts: change the rule, `rebuild`,
and the archive and its daily summaries follow. Applied on the way in, the
original would be gone and the mistake permanent.

## The file

```toml
unit_system = "metricwx"     # what the figures below are written in

[limits.outTemp]
minimum = -30
maximum = 45
spike = 5          # degrees per minute
stuck = 40         # identical readings in a row
resolution = 0.1   # what the sensor can tell apart

[calibrate.everywhere.outHumidity]
offset = 2.0

[calibrate.schuppen.outTemp]
offset = -0.4
```

Its own file rather than a section in the settings, for the reason
[`plots.toml`](Plots) is one: many alike entries with tables inside them, and
an operator who has worked out what their soil probe does wants to diff it
and hand it on.

### Calibrate first, then check

The other order tests an uncorrected reading against corrected limits, so a
thermometer with a 0.4 K offset fails at its own ceiling.

Calibration is **per station**, because that is what it is about: two
thermometers in one garden disagree by a few tenths, and which of them is
*the* series is a decision somebody made. `[calibrate.everywhere]` applies to
all of them; a station's own entry wins.

### What each rule costs when it is wrong

| | |
|---|---|
| `minimum`, `maximum` | The reading is impossible. The cheapest rule and the one that catches a flat battery. |
| `spike` | It changed faster than the weather can. Not applied to rain and the other counters: a cloudburst is a step change and so is a gauge being emptied. |
| `stuck` | It has not moved for so long that the sensor has died. Needs `resolution`, or every calm night is a dead thermometer. |

`stuck = 40` means: forty the same, and the forty-first is refused. A reading
that differs ends the spell whatever the counter says — without that, a
refused packet is never remembered, the counter stays high, and every real
reading after a stuck spell is refused as stuck, for ever.

Readings that **wrap** get no spike rule. The difference between 359° and 1°
is two degrees, not 358, and the check measures the short way round.

### A limit is a number in a unit

−50 written in Celsius has to be −58 for a console reporting Fahrenheit, and
the file says which system it is written in so the same file behaves the same
way on both.

A **span** converts differently from a point: a 5 K jump is 9 Fahrenheit
degrees, not 41. Converting a spike rule the wrong way turns it into a limit
at the freezing point, and an offset of +0.4 K into a correction of +33.

## Working the rules out

Nobody can type a plausible ceiling for `soilMoist3` out of their head.

```bash
weewx-evo quality suggest --days 365 > quality.toml
weewx-evo quality check
```

The settings page does the same thing behind one button, and prints what the
rules as they stand would have refused before any of them is saved.

![The sensor checks page, one row per reading](images/wiki-8-quality.png)

`suggest` measures the station: the archive for the floors and ceilings,
because it has years and knows how cold it gets, and the live table for the
spike and stuck rules, because only it has the packet-to-packet steps those
are about. A spike rule worked out from five-minute records is several times
too tight — the weather has five minutes to move between them — so where
there are no live packets it says so rather than printing figures that look
reasonable.

Three things it knows beyond what it has seen:

- **What physics allows.** Four years of data still put the floor for wind
  speed at −2 and the ceiling for humidity at 114, because the room added
  below the lowest reading is right for a temperature and wrong for anything
  that cannot go negative. The bounds are by unit group, so a driver's own
  fields are covered by `units.contribute`.
- **Which readings wrap**, as above.
- **What a resolution is.** Measured as the smallest change ever seen, capped
  at a hundredth of the range: a wind speed going 0, 2, 4, 1, 3 has a smallest
  change of 2, and taking that as the resolution makes every ordinary step
  count as unchanged.

`check` runs the configured rules over stored records and changes nothing. It
calls it a fault of the rule when more than one record in twenty is refused —
that is usually a limit set too tightly rather than a sensor at fault.

## A dropped reading is dropped, not zeroed

Zero is a measurement. A gauge reporting 0.0 because its reading was refused
cannot be told from a dry afternoon, ever. So the field is absent, and absent
is what everything else here already handles.

Nothing is dropped in silence. The count is on `Built.dropped` and in the log:
a silent drop looks exactly like a broken sensor, which is the thing this is
meant to help find.

## Determinism

`build` is a function of a time span and has to stay one, or a `rebuild`
would differ from the original silently and only where a rule fired.

So the checker is made **fresh per span** and seeded from the packets before
it. Fresh, so nothing carries between calls. Seeded, because the spike and
stuck rules need a previous reading and the first packet of an interval has
none — without the run-up, every interval boundary is a hole a spike walks
through.

The run-up **judges as well as remembers**. Taking every earlier reading as
read made an outlier the value the next one was compared against, so the
first real reading was a spike from −41, and so was the one after it: one bad
packet switched a station off for good.

## Tests

```bash
python tools/quality_test.py
```

The check that matters builds a real archive twice over, with rules and
without, and compares the record *and* the daily summary. The round trip —
suggest rules from a station's own history, then run them over that history
and refuse nothing — is what found the unit-system variable being shadowed by
a loop variable in `watch`, which recorded a wind speed of 4 as 1.79.

→ [Archiver](Archiver) · [Derived-Readings](Derived-Readings) · [Units](Units) · [Database-Live](Database-Live)

<!-- covers
src/weewx_evo/quality.py
src/weewx_evo/adminquality.py
-->

# weewx-evo

A rebuild of the WeeWX core. Python, no dependencies outside the standard
library, 3.11 and up.

It records the weather from one console or from ten, keeps it in a database
WeeWX itself can carry on using, and publishes it — as a website, as charts, to
a weather service, to Grafana.

**Documentation is in the [wiki](https://github.com/hilman2/weewx-evo/wiki).**

## The one rule

An existing WeeWX database stays readable and writable — **by WeeWX itself**.
Not "importable": the same file, the same meaning, and WeeWX 5 can carry on
using it afterwards.

Everything else here is negotiable. This is not, and it is what the test suite
spends most of its time on: the daily statistics of a real database are
recomputed and compared against what WeeWX wrote into it.

## Install

```bash
git clone https://github.com/hilman2/weewx-evo
cd weewx-evo
pip install -e .
```

That gives you the `weewx-evo` command. Without installing works too:

```bash
PYTHONPATH=src python -m weewx_evo.cli --help
```

## Set it up

A token, a configuration file, and the service:

```bash
python -c "import secrets; print(secrets.token_hex(24))"    # the token

weewx-evo config set --config evo.toml token <the-token>
weewx-evo config set --config evo.toml station.name "Kirchdorf an der Amper"
weewx-evo config set --config evo.toml station.latitude 48.4596
weewx-evo config set --config evo.toml station.longitude 11.6539
weewx-evo config set --config evo.toml station.altitude 440

weewx-evo serve --config evo.toml
```

Then point the console at `http://<host>:8000/<token>/ecowitt/` and everything
else is done on the settings page:

```bash
weewx-evo config set --config evo.toml admin.token <a-different-token>
weewx-evo admin --config evo.toml
```

→ [Getting started](https://github.com/hilman2/weewx-evo/wiki/Getting-Started),
[Several places](https://github.com/hilman2/weewx-evo/wiki/Places),
[Deployment](https://github.com/hilman2/weewx-evo/wiki/Deployment)

## What it does

| | |
|---|---|
| Takes readings from six push protocols, any WeeWX driver, or a collector of your own | [Drivers](https://github.com/hilman2/weewx-evo/wiki/Drivers) |
| Records the weather at more than one spot, each with its own coordinates | [Several places](https://github.com/hilman2/weewx-evo/wiki/Places) |
| Publishes a website, charts as JSON or PNG, and NOAA reports | [Feeds](https://github.com/hilman2/weewx-evo/wiki/Feeds), [Deck](https://github.com/hilman2/weewx-evo/wiki/Deck) |
| Sends them on by FTP or rsync, only what changed | [Exports](https://github.com/hilman2/weewx-evo/wiki/Exports) |
| Posts to Weather Underground, Windy, CWOP, MQTT, InfluxDB and others | [Uploads](https://github.com/hilman2/weewx-evo/wiki/Uploads) |
| Fetches a forecast per place, from Open-Meteo, DWD, MeteoAlarm or NWS | [Forecast](https://github.com/hilman2/weewx-evo/wiki/Forecast) |
| Refuses a reading a flat battery or a hosed-down rain gauge produced | [Quality control](https://github.com/hilman2/weewx-evo/wiki/Quality) |
| Says something when a console goes quiet or an upload starts failing | [Notifications](https://github.com/hilman2/weewx-evo/wiki/Notifications) |
| Answers questions over HTTP, in whatever unit the caller asks for | [API](https://github.com/hilman2/weewx-evo/wiki/API) |

Every stage is reproducible from the one before it. There is no in-memory
accumulator a restart would lose: a late packet lands in the right interval, and
a wrong calibration can be corrected afterwards for as long as the raw packets
are still in retention.
→ [Architecture](https://github.com/hilman2/weewx-evo/wiki/Architecture)

## Tests

```bash
docker/run.sh          # or docker\run.ps1
docker/run.sh --list   # what would run, and what would be skipped
docker/run.sh units    # just that one
```

Around a minute, no network. The image carries WeeWX 5.1, pyephem, Cheetah and
Pillow on purpose: **a test that cannot compare against the thing it was
transcribed from is not a test.** The unit conversions, the series, the daily
statistics, the almanac and thirteen WeeWX drivers are each checked against
WeeWX's own answers.

→ [Testing](https://github.com/hilman2/weewx-evo/wiki/Testing),
[Contributing](https://github.com/hilman2/weewx-evo/wiki/Contributing)

## Licence

**GPL-3.0-or-later**, and that is not a free choice. `aggregate.py` and
`units.py` are transcriptions from WeeWX, expression by expression: the daily
statistics arithmetic from `weewx.accum`, the unit conversions from
`weewx.units`. That makes this a derived work, and WeeWX is GPL v3.

It is deliberate rather than a corner we were backed into. A "cleaner"
recomputed conversion is a chart that differs from WeeWX in the third decimal,
and not doing that is the whole promise of this project.

WeeWX: Copyright (c) Tom Keffer and contributors, <https://weewx.com>.

### Bundled

- The **Deck** skin began as [weewx-wdc](https://github.com/Daveiano/weewx-wdc)
  by David Baetge, GPL v3. `CHANGES.md` beside the skin lists what differs.
- The **Ecowitt driver** goes back to
  [weewx-ecowitt](https://github.com/hilman2/weewx-ecowitt) — the catalogue, the
  protocol and its tests. It is developed further here.
- [**uPlot**](https://github.com/leeoniya/uPlot) 1.6.32, MIT, unchanged, under
  `feeds/diagnostic/vendor/`. The diagnostic feed draws with it, so that page
  works on a station with no way out to the internet. (Deck draws with ECharts,
  which it fetches itself.)

Nothing else. The core runs on the standard library, and pyephem is used where
it is installed without ever being required.

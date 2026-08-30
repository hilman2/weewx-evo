# Metrics

`metrics.py`. What the process is doing, in the format Prometheus reads.

```toml
metrics.enabled = true
```

Served from the [web server](Web-Server) at `/metrics`, off by default.
Everything in it was already measured — the [watchdog](Deployment) counts
descriptors and threads, the export runners write how their last run went into
`live_metadata`, the live table knows when each station was last heard from.
None of it was anywhere a monitoring system could see.

## The weather is not in here

This is the decision the rest follows from.

Prometheus is built for a value that is scraped, kept for weeks and reasoned
about as a rate. A weather reading is kept for fifteen years, has to be
backfilled when a console catches up, and is a measurement rather than a
counter. Put it here and the result is a second, worse archive that silently
disagrees with the first.

**Prometheus gets the process. [Grafana](Grafana) gets the weather**, out of
the archive or out of InfluxDB. `tools/metrics_test.py` greps the samples for
temperature and rain, because this is the sort of line somebody adds meaning
well.

## What is published

| | |
|---|---|
| `weewx_evo_up` | Always 1. Its **absence** is the alarm. |
| `weewx_evo_uptime_seconds` | |
| `weewx_evo_open_descriptors`, `_descriptor_limit` | Rising steadily is a leak. |
| `weewx_evo_runner_alive{runner}` | A runner that has died does not restart itself. |
| `weewx_evo_live_packets`, `_live_bytes` | |
| `weewx_evo_newest_packet_age_seconds` | The one figure that says the whole ingest has stopped. |
| `weewx_evo_archive_records{archive}`, `_archive_bytes{archive}` | |
| `weewx_evo_newest_record_age_seconds{archive}` | More than a couple of intervals means the archiver has stopped. |
| `weewx_evo_station_last_seen_seconds{station}` | |
| `weewx_evo_station_packets_per_minute{station}` | |
| `weewx_evo_sender_ok{sender}`, `_failures`, `_last_run_seconds`, `_duration_seconds` | Exports and uploads. |

**Per station, not in aggregate.** With one console "something is arriving"
says everything; with ten, the useful figure is which of them has gone quiet,
and an average over all of them hides exactly that.

`_bytes` counts the `-wal` and `-shm` too: a station whose disk fills is
filled by all three, and a figure that leaves them out is the one that looks
fine until it is not.

## Scraping does not cost

Every figure is either already in memory or one indexed query. A `/metrics`
that is expensive to answer becomes a thing scraped every fifteen seconds that
*makes* the problem it is meant to report — so a station's packet rate is one
grouped query over a fifteen-minute window, not a count over the retention
period.

No connection is held. One is opened per scrape and closed with it, for the
reason [`api.py`](API) holds none.

**A gatherer that throws is skipped, not fatal.** The metrics that still work
are how somebody finds out what is wrong. A missing database is not an error
either: a split deployment has the archive on another machine.

## Alerting

This and [notifications](Notifications) overlap on purpose, and the split is
the same one as with Grafana:

- **`notify/` is the alarm that has to work when the rest does not.** It needs
  the live database and an outbound connection, nothing else, and it is what
  tells somebody the station stopped at three in the morning.
- **Prometheus is the picture over time.** How often it happens, whether the
  descriptor count has been climbing for a week, which of ten stations is the
  unreliable one.

An installation that has Prometheus can build the first out of the second.
One that does not still gets told.

```yaml
scrape_configs:
  - job_name: weewx-evo
    static_configs:
      - targets: ["station:8081"]
```

## Tests

```bash
python tools/metrics_test.py
```

Every line is parsed back against the exposition grammar. Prometheus does not
*report* a malformed scrape: it drops it and the target goes stale, which
looks exactly like the process being down — on the day somebody set this up.

→ [API](API) · [Notifications](Notifications) · [Deployment](Deployment) · [Grafana](Grafana)

<!-- covers
src/weewx_evo/metrics.py
-->

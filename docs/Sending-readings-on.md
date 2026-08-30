# Sending readings on

Weather Underground, Windy, CWOP, your own database — the readings themselves,
not the pages built from them.

An **upload** is not an export. An export moves files a feed wrote; an upload
reads the record and sends the numbers. So it does not wait for a feed, and it
can send fifteen years of history in one go.

## Setting one up

**Publishing → Add an upload**, then the account details the service gave you.

```toml
uploads.wu.kind = "wunderground"
uploads.wu.station = "IKIRCH42"
uploads.wu.password = "…"
```

**Try it before trusting it.** Every upload page has a button for that, and it
is worth pressing: most of these services answer a wrong password with a
cheerful `200 OK` and a word in the body, so an upload that is being silently
rejected looks exactly like one that works.

## What is on offer

| | |
|---|---|
| `wunderground`, `pwsweather`, `wow` | the Ambient protocol — Weather Underground defined it, the others copied it |
| `windy` | Windy.com |
| `weathercloud` | Weathercloud |
| `cwop` | APRS-IS, for CWOP and the amateur networks |
| `mqtt` | your own broker, for Home Assistant and the like |
| `influx` | InfluxDB, which is what Grafana reads |
| `webpush` | live readings onto a page you published by FTP |

→ [Uploads](Uploads), [MQTT](MQTT), [Grafana](Grafana)

## Sending the history

An upload takes a list of records oldest-first and remembers where it got to,
so catching up is the same machinery as keeping up:

```bash
weewx-evo upload run --since 2010    # everything from there
weewx-evo upload compare             # both ends counted
```

`compare` is worth knowing about if you send to InfluxDB: **two stores are two
truths**, and a `rebuild` after a correction has to pull the sink along or
Grafana shows one number while your own page shows another, with nothing
saying which is right.

## The units are not yours to guess

Weather Underground wants Fahrenheit and inches of mercury, Windy wants
Celsius and hectopascals. Each upload converts on the way out, from whatever
the archive holds — which may well be what the console sent rather than what
your pages show.

**A missing value is missing, never zero.** A rain gauge that reported nothing
is not a rain gauge that reported 0.0, and a service that is told the second
records a dry hour that never happened.

## More than one place

An upload sends one place's readings, and the coordinates that go with them
come from that place. A registration with a weather service is for one spot, so
two places want two uploads. → [Several places](Places)

## When it stops working

A refused login is said **once**, not once every five minutes. The Publishing
page shows the last run of every upload and what the far end said if it
objected, and consecutive failures are counted — a passing network problem and
a changed password look identical at one failure and nothing alike at three.
→ [Alerts](Alerts)

<!-- watches
src/weewx_evo/uploads/
-->

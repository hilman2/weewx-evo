# Notifications

`notify/`. Telling somebody when the station has stopped working.

The gap this fills is embarrassing once you look for it: **nothing in this
program told anybody anything.** The [watchdog](Deployment) restarted the
process and wrote a log line. A console that stopped uploading at three in
the morning was a flat line on a page nobody opened until the weekend. An FTP
account whose password had changed failed every five minutes for a month.

With one station that is a nuisance. With ten it is the difference between
running an installation and hoping.

Nothing is configured by default.

## Operations, not weather

A closed list, and staying closed is the design:

| | |
|---|---|
| `station_silent` | a console has not sent anything for too long |
| `battery` | a transmitter is reporting a flat battery |
| `sending` | an [export](Exports) or an [upload](Uploads) keeps failing |
| `restarted` | the watchdog restarted this process |
| `heartbeat` | the archiver's loop has stopped going round |

**Not** frost, not a gale, not a rainfall record. A weather threshold is a
matter of taste and belongs somewhere it can be changed without a restart,
which is what [Grafana's](Grafana) alerting is for — and the message that says
the station is dead must not arrive in the same inbox as the one that says it
is cold.

**And nothing that fails when somebody else's equipment is off.** Same rule as
the watchdog, for the same reason: a check that goes red when a console is
unplugged for the winter is a check people learn to ignore. A station that has
*never* been heard from is not silent, it is unconfigured, and that belongs on
the settings page.

## Flapping is the whole design

A threshold with something wandering across it is forty messages a night, and
forty messages a night is a filter rule — which is the same as having built
none of this. Two rules against it:

**Nothing is reported until it has held.** Half an hour by default. A console
that misses one upload is not an event.

**Every alert has an end**, and the end is sent through the same channels. An
operator told at 04:00 that the shed went quiet, and told nothing afterwards,
cannot tell a fixed station from a broken alert.

Between them, a symptom that comes and goes under the threshold produces
nothing at all.

### Silence is measured against the station's own rhythm

A console reporting every sixteen seconds and one reporting every five minutes
cannot share a threshold, and both turn up on the same installation. So the
rule is a multiple of what that station actually does, taken from its own
packets, with the configured figure as a floor.

The **median** gap rather than the mean: a station that was off for an hour
this morning would otherwise look like one that reports hourly, and would be
given an hour of silence before anybody heard about it.

## Channels

```toml
[notify.mail]
kind = "email"
host = "smtp.example.com"
username = "station@example.com"
password = "…"
to = "me@example.com, phone@example.com"

[notify.phone]
kind = "webhook"
url = "https://ntfy.sh/my-station-3f9a2c"
```

| | |
|---|---|
| `email` | `smtplib`, so it costs nothing to have. Everybody has an address. |
| `webhook` | One POST. Covers ntfy, Gotify, Slack, Discord, Telegram and whatever comes next. |
| `mqtt` | Retained, one topic per symptom, cleared by an empty payload. For an installation that already has Home Assistant or Node-RED. |

A fourth is forty lines: an object with `send(event)` and `options()`, same
shape as an upload or an export.

**Two channels, not one.** A message about the network, sent over the network,
is the alert most likely to be the one that does not arrive. `notify list`
says so; it does not enforce it, because it is the operator's network and
their judgement.

### The webhook template

One shape for every service, because the only thing they disagree about is the
body:

```toml
template = '{"text": "{subject}"}'      # Slack
template = '{"content": "{subject}"}'   # Discord
template = "{subject}"                  # ntfy, plain text
```

`{subject} {text} {body} {station} {who} {kind} {severity} {state}` are filled
in, **as JSON** — a station called `Kirchdorf "old"` would otherwise produce a
body the far end rejects as malformed, which reads as the service being down
on the day something has actually gone wrong.

**Not `str.format`**, because JSON and `format` share the braces:
`{"text": "{subject}"}` makes `format` read `"text"` as a field name and
raise, so somebody who typed valid JSON gets a message about a field they
never asked for. Only `{word}` is a placeholder here; `{"` and `{}` are left
alone, and a `{word}` nothing knows is named rather than sent.

### Email

`check()` sends a real message rather than testing the connection. A provider
that accepts the login and then refuses the envelope sender is ordinary, and
no amount of connecting finds it — the four settings people get wrong are the
port, the TLS mode, the authentication and the from address, and only the last
shows up on a send.

The alarm and its all-clear carry a `References` header for the symptom, so a
mail client threads them together rather than showing two unrelated messages a
day apart.

## Commands

```bash
weewx-evo notify list      # what is configured, and what could be
weewx-evo notify check     # send a test message through each
weewx-evo notify status    # what is wrong right now, told or not
```

`status` is the one to reach for when something feels wrong and no message
arrived: it shows the symptoms the runner can see and whether each has been
reported yet.

## Where the state lives

In `live_metadata`, like [`exports/record.py`](Exports), for the same reasons:
the settings page is another process, a restart must not forget what has
already been said, and a program with a database in it does not need a second
place to keep four numbers.

**Not a history.** What is wrong now, and since when. The log has the rest.

`exports/record` also counts **consecutive** failures and dates the run of
them. Nothing can tell a network having a moment from a password somebody
changed by looking at one row saying the last run failed, and three in a row
is the difference.

## Two things the runner does that are not obvious

**It owns its own schedule** rather than being woken by the archiver, because
the symptom it exists for is the archiver having stopped. A check that runs
when a record is written cannot report that no record was written.

**It says nothing for the first five minutes.** A process that has just
started has no heartbeat yet and its runners have not had a turn, so sending
in that window means every restart produces a burst of alarms that clear
themselves a minute later. Symptoms are still *noticed* during it, and dated
from when they began rather than from the end of the settling period.

## Tests

```bash
python tools/notify_test.py
```

The checks that matter are about time: it holds before anybody hears, it
repeats on the scale of a day, it ends, and a symptom flickering under the
threshold produces nothing. The SMTP and HTTP servers are real, on loopback —
what is being checked is which answers mean "stop" and which mean "Tuesday",
and a stub returning a number is a restatement of the code under test.

→ [Exports](Exports) · [Uploads](Uploads) · [Deployment](Deployment) · [Grafana](Grafana)

# Alerts

Being told when the station stops working.

A console that goes quiet at three in the morning is a flat line on a page
nobody opens until the weekend. An FTP account whose password changed fails
every five minutes for a month. Neither says anything to anybody.

## What it will tell you about

A closed list, and it is about **the equipment, not the weather**:

* a console has gone quiet
* a battery is flat
* an export or an upload is failing
* the watchdog restarted the service
* the archiver has stopped going round

No frost, no gale, no "it is going to rain". A weather threshold is a matter of
taste and belongs somewhere you can change it without a restart — Grafana, or
your own script against the API. And a message saying *the station is dead*
must not arrive in the same inbox as one saying *it is cold out*.

## Setting it up

**Publishing → Add a notification.** Three ways out:

| | |
|---|---|
| `email` | an SMTP account |
| `webhook` | Slack, Discord, ntfy, anything that takes a POST |
| `mqtt` | your own broker |

**Send a test.** A mail server accepts the login and then refuses the sender —
that is the normal case with providers, not the exception, so the test sends a
real message rather than opening a connection and calling it proof.

## Why it does not cry wolf

Two rules, and they are the whole design:

**Nothing is reported until it has been true for a while.** A console that
misses one upload is not an event.

**Every alert ends**, over the same channel it arrived on. Somebody who gets
*the shed is silent* at 04:00 and then hears nothing cannot tell a repaired
station from a broken alarm.

Between the two, a symptom that flickers below the threshold produces
**nothing at all**.

## It knows what quiet means for each console

A console reporting every sixteen seconds and one reporting every five minutes
both exist, often on the same installation. The gap that counts as silence is
measured per console, from its own median — not from a number you have to set,
and not from an average, which would give an hour of grace to a station that
happened to be off this morning.

**A console never heard from is not silent.** That is one nobody set up, and it
belongs on the settings page rather than in your inbox.

## A restart says nothing for five minutes

A fresh process knows nothing yet, so it watches before it speaks. Without
that, every restart produces a burst of alerts that resolve themselves a minute
later — the fastest way to teach somebody to ignore them. A symptom found
during those five minutes is dated to when it really started.

→ [Notifications](Notifications), [Metrics](Metrics)

<!-- watches
src/weewx_evo/notify/
src/weewx_evo/watchdog.py
-->

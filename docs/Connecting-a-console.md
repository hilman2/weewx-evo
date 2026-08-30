# Connecting a console

Getting the readings out of the box on the pole and into the record.

Two ways in, and which one you get is decided by the hardware, not by you:

* **It uploads to you.** Anything with a *Custom Server* field — Ecowitt
  gateways, Froggit, Sainlogic, Ambient, La Crosse. You type an address into
  the console and it starts posting.
* **You fetch from it.** A Davis Vantage on a serial cable, a Fine Offset over
  USB, an SDR receiver. Those run as a collector: a process of its own that
  reads the hardware and posts to the same place a console would.

## A console that uploads

The address it needs is your machine, port 8000, and the token as the first
part of the path:

```
http://192.168.1.20:8000/<token>/ecowitt/
```

Set that on the console, and the first upload turns up on the **Consoles**
page under *Seen, not announced* — with its readings already being recorded.
Adopting it there gives it a name and, if you keep more than one place, says
which one it belongs to.

![The consoles page with three consoles and three places](images/wiki-4-consoles.png)

The last part of the path is the protocol. `ecowitt` and `wunderground` cover
almost everything sold; there are six.
→ [Drivers](Drivers)

**Nothing is guessed.** An upload that arrives under a path naming no protocol
falls to `driver` in the settings, and one whose token is wrong gets a 404 —
the same answer as a path that does not exist, so that trying tokens tells the
prober nothing. → [Security](Security)

## Hardware you have to fetch from

`weewx-evo` runs any WeeWX driver as a collector, in its own process, without
WeeWX installed:

```bash
weewx-evo weewx-driver check --conf /etc/weewx/weewx.conf   # builds it, sends nothing
weewx-evo weewx-driver run   --conf /etc/weewx/weewx.conf   # delivers
```

`check` first: it says what the driver needs and what is missing, and it does
not touch the hardware. A serial port that does not answer is a driver hanging
in its own process, where it cannot stop the recording.
→ [Drivers](Drivers#running-a-weewx-driver--ingestweewxshimpy)

## Two consoles in one garden

Both write into the same place, and their readings are merged field by field
while the interval is being built. Where both send the same field, the
**Consoles** page decides which one counts.
→ [Multiple sources](Multiple-Sources)

If the second console is a *second sensor* rather than a second opinion — a
thermometer in the greenhouse, say — give it a role instead, and its
temperature is kept as `extraTemp3` with a history of its own.

If it is at a **different spot**, it wants a place of its own: its own sunrise,
its own barometer. → [Several places](Places)

## Nothing is arriving

```bash
weewx-evo status
```

The **Overview** page answers the same question with more of it: whether
packets are arriving, whether they are being kept, and which step is the one
that stopped. A console that has never been heard from at all is not listed as
silent — that is a console nobody set up, and it says so.

A reading whose field the archive has no column for is **reported, never
dropped in silence**. The Consoles page lists it and offers a column.

→ [Listener](Ingest-Listener), [Ecowitt](Driver-Ecowitt)

<!-- watches
src/weewx_evo/ingest/
src/weewx_evo/stations.py
src/weewx_evo/adminstations.py
src/weewx_evo/collectors.py
-->

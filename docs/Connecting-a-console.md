# Connecting a console

Getting the readings out of the box on the pole and into the record.

**First, install the driver for it.** weewx-evo ships none, so a fresh
installation can receive nothing until one is installed:

```bash
weewx-evo addon list                       # what exists
weewx-evo addon install weewx-evo-ecowitt
```

The settings page does the same under System -> Add-ons. If a console is
already uploading and nothing here can read it, that page says which add-on
would -- so the order above is a convenience, not a requirement.

Three ways in, and which one you get is decided by the hardware, not by you:

* **It uploads to you.** Anything with a *Custom Server* field — Ecowitt
  gateways, Froggit, Sainlogic, Ambient, La Crosse. You type an address into
  the console and it starts posting.
* **It uploads somewhere fixed.** An AcuRite bridge, a LaCrosse LW30x, a
  WeatherFlow hub. There is no field to type an address into, so it is
  brought here by other means and adopted once it arrives.
* **You fetch from it.** A Davis Vantage on a serial cable, a Fine Offset over
  USB, an SDR receiver. Their driver runs as a process of its own, where the
  hardware is, and posts to the same place a console would.

## A console that uploads

The address it needs is your machine, port 8000, and the token as the first
part of the path:

```
http://192.168.1.20:8000/<token>/ecowitt/
```

Set that on the console, and the first upload turns up on the **Consoles**
page under *Seen, not announced* — with its readings already being recorded.
They are in the shared live database, not assigned to an archive.
Adopting it there gives its hardware identity a readable, unique name. To keep
its readings in an archive, select that name on the **Places** page — including
when there is only one place.

The last part of the path is the protocol. `ecowitt` and `wunderground` cover
almost everything sold; there are six.
→ [Drivers](Drivers)

**Nothing is guessed.** An upload that arrives under a path naming no protocol
falls to `driver` in the settings, and one whose token is wrong gets a 404 —
the same answer as a path that does not exist, so that trying tokens tells the
prober nothing. → [Security](Security)

## A console that cannot be told an address

An AcuRite bridge posts to Chaney's servers and a LaCrosse gateway to
`box.weatherdirect.com`; neither has a setting for it. A WeatherFlow hub does
not post at all — it broadcasts on the local network.

Open **Add a console** anyway. Each of them is listed at the bottom of that
page with its own steps: the name that has to resolve to this machine, a
`dnsmasq` line with your address already in it, and the port redirect, because
they all post to port 80. A hub instead needs the UDP port switched on under
*Listener*.

Then it turns up under *Seen, not announced* like any other console, and you
adopt it there. It names itself — an AcuRite bridge with its `id`, a hub with
its serial — so there is nothing to type in.

## Hardware you have to fetch from

`weewx-evo` runs any WeeWX driver in its own process, without WeeWX installed.

Add it under **System → Drivers**, pick your hardware from the list, and its
own settings — serial port, model, whatever else it takes — appear on the page
after. They are read out of the driver, so they are the ones it actually has.

The same list from a terminal, when there is no browser to hand:

```bash
weewx-evo-weewx-driver hardware           # everything this machine can run
weewx-evo-weewx-driver hardware Vantage   # and every setting one of them takes
```

Then start it, where the hardware is:

```bash
weewx-evo-weewx-driver check --collector shed   # builds it, sends nothing
weewx-evo-weewx-driver run   --collector shed   # delivers
```

`check` first: it says what the driver needs and what is missing, and it does
not touch the hardware. A serial port that does not answer is a driver hanging
in its own process, where it cannot stop the recording.
→ [Drivers](Drivers#running-a-weewx-driver)

The thirteen WeeWX ships come with the add-on: Davis Vantage, Fine Offset,
AcuRite, Oregon Scientific, LaCrosse, TE923, Ultimeter, CC3000, WS1. Nothing
further to fetch, and WeeWX does not have to be installed.

A driver that needs a library says so rather than going missing — `needs
pyusb` beside its name in the list. Install the package it names where the
driver runs, or take the extra:

```bash
pip install "weewx-evo-weewx-driver[usb]"      # or [serial], or [all]
```

### If your driver is not in the list

There are a hundred beside those thirteen — weewx-sdr, and one for almost
every console somebody has written for. A driver is one Python file, and
adding it is one command:

```bash
weewx-evo-weewx-driver install ./some-driver.py
weewx-evo-weewx-driver install https://example.org/some-driver.py
```

A file added this way **beats** the shipped copy of the same name, which is
how a driver you have patched for your own hardware gets to run.

### If you already have a weewx.conf

Leave the hardware on *from a weewx.conf* and give the path instead. Nothing
is copied out of that file and nothing is written into it.

```bash
weewx-evo-weewx-driver run --conf /etc/weewx/weewx.conf
```

## Two consoles in one garden

Select both on the same place. Their raw packets already share `live.sdb`; the
archive merges them field by field while the interval is built. Where both send
the same field, the **Places** page decides which one is main.
→ [Multiple senders](Multiple-Sources)

If the second console is a *second sensor* rather than a second opinion — a
thermometer in the greenhouse, say — make it extra for that place, and its
temperature is kept in the selected extra channel with a history of its own.

If it is at a **different spot**, create another place and select it there. The
place owns the coordinates, height and archive file. A console may also be
selected by more than one place. → [Several places](Places)

## Nothing is arriving

```bash
weewx-evo status
```

The **Overview** page answers the same question with more of it: whether
packets are arriving, whether they are being kept, and which step is the one
that stopped. A console that has never been heard from at all is not listed as
silent — that is a console nobody set up, and it says so.

A reading whose field the archive has no column for is **reported, never
dropped in silence**. Open the Place's **Fields** tab to map it or add a
column.

→ [Listener](Ingest-Listener), [Push drivers](Driver-Ecowitt)

<!-- watches
src/weewx_evo/ingest/
src/weewx_evo/stations.py
src/weewx_evo/adminstations.py
src/weewx_evo/collectors.py
tools/console_setup_test.py
-->

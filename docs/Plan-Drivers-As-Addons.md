# Plan: every driver an add-on

Nobody needs this page to run a station. It was the design for taking every
driver and collector out of the core, written before the work so it could be
argued with.

**It is done.** What the core does now is in
[Drivers](Drivers) and in `CLAUDE.md`; this stays for the reasoning, and
because the four questions at the bottom are still open.

Three things came out differently from the plan:

- **One repository per add-on, not one `weewx-evo-drivers`.** The catalogue
  already said why -- separate issues, separate releases, and somebody who is
  not us able to keep one alive.
- **The tests moved with the code, and the captured uploads did not.** A body
  a console actually sent is evidence rather than an implementation, and the
  question it answers is the core's: does a record hold what arrived.
- **Two contracts had to be built before the shim could leave.** A kind of
  collector comes from an entry point, and a kind says what it wants decided
  before its own page exists -- the add-a-collector page called straight into
  the WeeWX driver list, which is add-on knowledge that had walked into the
  core.

## What was decided

- **The core ships no driver at all.** Not the push protocols, not the
  hardware drivers. A fresh installation can receive nothing until somebody
  installs one.
- **Granularity is the protocol, not the vendor.** A Fine Offset console
  doing an Ecowitt custom upload means one add-on: that protocol. Not a
  bundle of six.
- **One repository per protocol**, in the organisation, listed in
  `weewx-evo/weewx-evo-plugins`. That catalogue already exists and already
  says why: *"deliberately a list of pointers and not a monorepo […] the
  mistake to avoid is the one weewx-DWD made"*. Ours, tested, adapted to this
  architecture, supported by us.
- **The push family shares one package**, `weewx-evo-push-common`: the
  `Protocol` base, the mapper, the transport and the seam are 1 614 lines
  against 88 to 1 074 for a protocol, and copying them twelve times is not a
  trade worth making. It is a pip dependency, so the catalogue never learns
  that add-ons can depend on each other.
- **The interface is ours.** A weewx-evo driver is not a WeeWX driver and is
  not a weewx-ultimate-push protocol. What travels between projects is the
  *description* -- field catalogs and parsing -- never the interface.

The reasoning for the first point is that 99 % of installations have one
station. Shipping seven protocols so that one is used is six protocols of
attack surface, import time and settings-page noise for nothing.

## The core does not depend on the tree

Measured before planning, because the whole thing rests on it:

| | |
|---|---|
| Core modules importing `ingest.plugins` | **one** line, `cli.py:2611` |
| `placement.py` importing the mapper | none. It reads `packet.mapping`, the inert spec the driver stored with the packet |

That is the seam already working as intended: a driver says how its names are
to be read *when it delivers*, and the archiver reads that back without ever
loading the driver. Nothing about placement, rebuilding or the archive needs
a driver to be installed.

So the move is not a disentangling. It is a deletion plus a download path.

## What leaves, what stays

Leaving, with today's line counts:

| | Lines |
|---|---|
| `ingest/plugins/` (six push protocols, catalogs, mapper, transport) | 4 723 |
| `ingest/weewxdrivers.py` (the form read out of a WeeWX driver) | 910 |
| `ingest/weewxnames.py` (stand-ins so a WeeWX driver imports without WeeWX) | 613 |
| `ingest/weewxshim.py` (running one as a collector) | 601 |
| `tests/push/` | 1 617 |
| **Total** | **8 464** |

Staying, and the reason each one is not a driver:

- **`ingest/listener.py`** -- the socket, the token, the rate limit, the
  network boundary. It owns the door; add-ons own what comes through it.
- **`ingest/drivers.py`** -- the registry and the interface itself. This
  *becomes* the contract below.
- **`ingest/envelope.py`** (83 lines) -- the JSON a collector posts. Not
  hardware support: it is the door every collector add-on delivers through.
  As an add-on it would be the add-on without which no other add-on works.
- **`ingest/userdrivers.py`** (321 lines) -- how one is installed. Grows into
  the catalogue client.
- **`collectors.py`** -- what a configured collector *is* in the
  configuration. The kinds it can be come from add-ons; the fact that a place
  can have one is core.

## The contract

**It already exists.** An earlier draft of this page said it had to be frozen
first; that was wrong, and measuring it took one grep. The core reads seven
entry-point groups:

```
weewx_evo.drivers   weewx_evo.parsers   weewx_evo.exports   weewx_evo.feeds
weewx_evo.forecast  weewx_evo.notify    weewx_evo.uploads
```

`ingest/drivers.py:695` loads every `weewx_evo.drivers` entry, registers a
class as a factory, and carries on past one that will not import. Then it
calls `plugins.load(self)` for the six that ship in the tree -- and that call
is the only thing the move deletes.

So a driver add-on is a pip package with one line in its `pyproject.toml`,
exactly like `weewx-evo-sftp` already is:

```toml
[project.entry-points."weewx_evo.drivers"]
ecowitt = "weewx_evo_ecowitt:EcowittDriver"
```

What follows is therefore a description of what is there, plus the three
pieces that are not: `steps()`, `detects`, and a shared package for the push
family.

### What an add-on declares

```
name          ecowitt-custom          one add-on, one protocol
label         Ecowitt custom upload   what a list calls it
hardware      GW1000, GW2000, ...     what somebody standing over a box knows
kind          push | poll             how it gets its readings
core          >=0.4,<0.6              which core interface it was built for
```

Then, by kind:

**push** -- `packets(body, meta) -> [Packet]`, plus `response` (the exact
bytes the hardware waits for) and the `DialectSpec` it stores with each
packet. This is `ingest/drivers.Driver` as it stands.

**poll** -- runs in its own process and delivers through the envelope. It
declares what it needs (a serial port, a URL, an API key) and how often. The
core supervises nothing: it hands out an endpoint and a token.

Both may declare:

- `options()` -- its own settings, as `options.Option`, which the settings
  page renders without knowing anything about it. Already true today.
- `unit_groups()` -- what its own fields measure, so a page converts them.
  Already true today (`units.contribute`).
- `place()` -- where a raw name goes, asked when a record is built. Already
  true today.
- `steps()` -- **new.** The wizard, below.
- `detects` -- **new.** How an unknown upload is recognised as this one.

### What the core guarantees

- A packet is stored raw, under the names the sender used, whatever the
  add-on says. An add-on cannot lose a reading.
- `place()` is asked on the read side. A wrong answer is repairable with a
  rebuild.
- An add-on that raises does not take the listener with it.
- An add-on is never asked to reach the archive, the settings file or another
  add-on. It parses, or it polls, and it returns.

The last one is the difference from the current arrangement, where a driver
in the tree could reach anything and simply chose not to.

## One thing to fix on the way

`plugins.load()` registers the bundled six with `replace=True`, and it runs
*after* the entry points. So an installed add-on is loaded, registered, and
then overwritten by the copy in the tree: today, `pip install
weewx-evo-ecowitt` gets you the bundled Ecowitt.

It resolves itself when the tree is emptied, which is why it is a note and
not a fix. It is worth knowing because it makes a test lie: a run that
installs an add-on and then asks the registry for it gets an answer, and the
answer is the wrong object. `type(driver).protocol_class.__module__` is what
tells the two apart.

## The catalogue

A single file in the organisation, fetched to show the list. It has to
describe without downloading, or the first page of a fresh installation needs
seventeen requests.

Per entry: `name`, `label`, `hardware`, `kind`, `core`, the download URL, a
hash, and `detects`.

**`detects` is the point.** With nothing installed, a console set up against
a valid token produces exactly one thing today: a log line
(`listener.py:214`). Nothing in the live table, nothing on any page. That is
about to become the ordinary first-run state, so it has to become the *best*
part of setting up:

1. An upload arrives with a valid token and no driver reads it. The core
   keeps what it saw -- sender, time, a redacted opening -- as a sighting.
2. The catalogue's `detects` patterns are matched against that.
3. The page says: *something is uploading here that looks like an Ecowitt
   custom upload. This add-on reads it.* One button.

The core learns no protocol. It matches strings the catalogue gave it. A
console the operator later switches to a different protocol produces the same
sighting and the same offer, rather than silence.

**Offline is the cost, and it is paid explicitly.** An installation with no
outbound network cannot set itself up from the catalogue.
`weewx-evo driver install <file>` already takes a local path; the wizard has
to offer that route beside the catalogue rather than assume the network.

## The wizard

`drivers.Setup` is already half of it: label, hardware, the fields to type
into the console, the notes around them, whether it brings its own identity,
where the token goes. What it describes is the *console*, not the procedure,
and a poll driver has no equivalent at all -- which is what the Collectors
page looks like today.

`steps()` generalises it: an ordered list, each step one of

- **say** -- text and an illustration; nothing to fill in
- **ask** -- `options.Option` values, rendered by the machinery that already
  renders every settings page
- **tell** -- what to type into the hardware, with `%(address)s`,
  `%(path)s`, `%(token)s` filled in by the page, which is the only thing that
  knows them
- **wait** -- until a packet arrives from this sender, or the poll driver
  answers once

`wait` is what makes it a wizard rather than a form: it ends with *I have
seen your station*, out of the live table, rather than with a saved file and
a hope. `sightings.py` already holds what that needs.

One page renders every add-on's wizard. The page learns nothing about any of
them, the same way `options.py` already works for settings.

## What we are behind on

Our copy is `VERSION = "0.8.0"`. Upstream weewx-ultimate-push is at 0.21.0.
Same author, GPL-3.0-or-later on both sides, so this is an architecture
question and not a licence one.

Six sources exist there that do not exist here, and five of them are polled:

| | |
|---|---|
| rtl_433 | 433/868/915 MHz sensors, over UDP from the `rtl_433` program |
| PurpleAir | PA-II, PA-II-SD, PA-I, polled |
| Davis AirLink | polled |
| Ecowitt gateway API | the same hardware as the push protocol, asked on TCP 45000 |
| Ambient cloud | hardware on an ambientweather.net account, polled |
| Home Assistant | any entity it integrates, over its REST API |

Two things follow.

**The push/poll split is not ours to invent.** Upstream already carries both
in one driver, and the six above are why. An `ecowitt` add-on that pushes and
an `ecowitt-gateway` add-on that polls are the same hardware reached two
ways, and the wizard should offer them together with the difference stated,
not on two pages under two words.

**Bringing them over is a port, not a copy.** The catalogs and the parsing
travel unchanged, as they do today. What does not travel is the interface:
upstream's polled sources sit inside a WeeWX driver's `genLoopPackets`, and
here they are collectors delivering through the envelope. That work is real
and is the bulk of the estimate.

## The WeeWX hardware drivers

Thirteen in the WeeWX tree, GPL-3.0, adoptable with attribution. Today they
run through `weewxshim.py` with stand-ins for the names they import, and
`weewxdrivers.py` reads their configuration form out of the driver file with
an AST walk rather than by importing it.

That machinery works -- `alldrivers_test.py` runs all thirteen against
seeded byte streams, and three simulated devices compare our stand-in
against WeeWX' own code field for field. It moves to the new repository as it
is.

The question the move forces: **thirteen hosted drivers, or thirteen
add-ons?** Hosting keeps them exactly as upstream wrote them, so a fix over
there is a file copy. Adopting them means rewriting each against our
interface, and then they are ours to keep working. The hardware is old, the
protocols do not move, and the number of installations is small.

My reading: **host them, adopt none, and say so on the page.** The shim is
already built, tested and proven against the real thing; rewriting thirteen
drivers to gain nothing a user can see is the expensive half of this plan.
The shim itself becomes one add-on -- "run a WeeWX driver" -- and the driver
files it runs are downloaded beside it.

## Order

1. **Freeze the contract** while the drivers are still in the tree. A change
   costs one commit now and a migration across N repositories later.
2. **`steps()` and the one wizard page**, against the six push protocols and
   the shim that are already here. Only a wizard rendering from the model
   proves the model.
3. **Sightings and `detects`**, with the catalogue file checked in but served
   from the repository. This is the piece that makes an empty installation
   usable, so it comes before the tree is emptied.
4. **Move the tree.** `weewx-evo-drivers`, one directory per add-on, the
   catalogue at its root, the tests moving with the code.
5. **Port what we are behind on** -- the six sources above, poll first, since
   the poll path is the one with no precedent here.
6. **The shop**: install already exists, so this is the catalogue plus the
   pages around it.

Two and three before four, deliberately. Emptying the tree first leaves a
version where nothing can be set up.

## Open, and not for me to decide

- **Trust.** Anything in our organisation is one thing. A driver somebody
  else wrote is another. Does the catalogue carry third-party entries at all,
  and does an add-on need a signature or only a hash?
- **What a removed add-on leaves behind.** `stations.toml` names a driver
  that is gone; the packets stay in the journal and the archive keeps its
  columns. Refuse the removal, or keep the rows unreadable and say so?
- **Version skew.** `core = ">=0.4,<0.6"` is a promise about an interface we
  have not frozen yet. Who bumps it, and does an add-on outside the range get
  refused or warned?
- **Whether `detects` can be wrong.** Two protocols that look alike on a
  short body would offer the wrong add-on. Offering both, ranked, is the safe
  answer and a worse page.

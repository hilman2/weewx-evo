# API

`api.py`. The readings as an answer to a question, rather than as a file.

Every other output this program has is a file: a [feed](Feeds) writes a
directory, an [export](Exports) moves it, a page reads it. That works for the
questions somebody thought of in advance and for nothing else — a client with
a question no plot answers has no way in at all. Home Assistant, a phone app,
a script, Grafana through Infinity: all of them stopped here.

[`series.py`](Series) could already answer every one of those questions. What
was missing was a way to ask.

```toml
api.enabled = true
api.token = ""      # empty: whoever the pages are served to
```

Served from the [web server](Web-Server), on the same port as the pages, at
`/api/v1/`. Off by default.

## The endpoints

| | |
|---|---|
| `GET /api/v1/` | what this answers, so the rest is findable without the source |
| `/archives` | the measurement series there are, and what each covers |
| `/stations` | the known consoles; archive membership comes from each place's selection |
| `/fields` | what is recorded: unit, group, label, and whether a long span is cheap |
| `/current` | the newest record |
| `/series` | a reading over a span |
| `/aggregate` | one number for one span |

```bash
curl 'http://station:8081/api/v1/series?obs=outTemp&start=-7d&aggregate=max&every=day&units=metricwx'
```

```json
{"archive":"default","obs":"outTemp","label":"Outside Temperature",
 "group":"group_temperature","unit":"degree_C","unit_label":"°C",
 "aggregate":"max","every":"day","start":1787408023,"stop":1788012823,
 "time":[…],"values":[23.8,25.7,36.0,21.9,…]}
```

`/fields` is the one a client calls first: it can lay out its own page from
that and then ask only for what the station actually has.

## It calls `series.py`, and that is the point

A second implementation of "the average temperature last week" is exactly the
fault [`chartdata.py`](Plots) describes — two answers, both right on their
own, differing in the third decimal, and nobody able to say which one is the
station's. Everything here is a thin shell over the same reader the feeds use,
and `tools/api_test.py` compares every answer against it rather than against
a typed-in figure.

## Times three ways

A script has an epoch, a person typing into a browser has a date, and a
dashboard has "the last week":

```
start=1787408023            seconds
start=2026-08-20            an ISO date, local where it names no zone
start=-7d                   -30m -12h -7d -4w -1y
```

A span reaching before 1970 is refused rather than passed on: `-100000d` is
one keystroke from `-10000d`, and a negative timestamp reaches `time.localtime`
and raises rather than answering.

## Units

**Every answer names its unit.** The archive keeps what the station wrote,
which may be Fahrenheit on a German station — a number without a unit is the
fault that reached a published page twice through the live push, and an API is
a worse place for it because the reader is a program that will not notice.

`units=us|metric|metricwx` converts on the way out. Without it the archive's
own system is used, and said.

## The limits are not politeness

**A span with no bucket size is refused past ten thousand records.** Ten years
of five-minute readings is a million points: serialising them is a gigabyte of
JSON and a process that dies rather than answers. The refusal names the two
parameters that make it answerable:

```json
{"error":"that span holds more than 10000 records. Add `aggregate` and
          `every` to say how it should be cut, or ask for less."}
```

Every refusal is like that. `400` alone means reading the source, and the
caller is a program somebody is writing.

## Who may ask

Read-only throughout. Nothing here writes, and that is what makes the question
of who may reach it a simple one: the settings page can point the archive at
another file, this can tell you what the temperature was.

It inherits the web server's [network boundary](Security) — private networks
only unless that is changed. `api.token` is for an installation that publishes
to the open internet: the API answers about any span rather than only what a
feed has published. The token goes in `X-Token` or in the query string, because
a header is right for a script and wrong for a browser address bar, and both
are people who will use this.

A wrong token is a **404**, never a 401. Saying "wrong token" confirms there is
something here worth trying tokens against — the same rule as the
[listener](Ingest-Listener).

`/stations` gives names and drivers. It does **not** give identities: an
identity is what a console proves itself with. Roles belong to a console's
membership in a place, not to the console itself.

## Two details

**The API is matched before the feeds.** A feed can be called anything somebody
types, including `api`, and it must not shadow this.

**No connection is held.** One is opened per request and closed with it. The
questions are seconds apart, and a pool of long-lived SQLite handles is the
shape that once took an instance down with 477 descriptors.

## Tests

```bash
python tools/api_test.py
```

The last part runs it through the real web server on loopback, because the
route in is as much a part of this as the answers — including a feed called
`api` sitting next to it.

→ [Series](Series) · [Web-Server](Web-Server) · [Units](Units) · [Security](Security)

<!-- covers
src/weewx_evo/api.py
-->

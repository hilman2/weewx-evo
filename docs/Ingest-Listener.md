# Listener

`ingest/listener.py`. The listener every push driver sits behind.

One process accepts HTTP and UDP, hands the bytes to a driver and writes the
packets that come back into the live table. Drivers open no sockets, check no
tokens and never touch the database — that is the whole point: those three are
where push drivers go wrong, and doing them once means doing them once.

## What it does not do

It does not decide what a reading is called, which of them this installation
wants, or where they go. A packet is stored under the names the console used,
with nothing left out, and all of that is answered when a record is built
→ [Placements](Placements).

For a driver-specific dialect it does persist the driver's `DialectSpec`:
field catalog, units, scale factors, contested names and metadata as strictly
validated JSON. That records how the raw packet can be interpreted without
choosing what any place wants from it. An archive process can therefore
rebuild the packet without loading the driver.

So a place's `primary`, `indoor` and field placements do not change the raw
readings here. They used to, and a wrong one then cost the
measurements rather than a rebuild.

What it does stamp is which driver read the upload. Together with the identity
the hardware gave, that pair is how the packet is recognised afterwards — the
name the console answers to is a lookup, and looking it up later is what lets
you rename one without splitting its series in two.

## `Ingest`

What the listener does with an upload once it has one. Separate from the
transports, so that the same object serves HTTP, UDP and the tests — and so
that a pull driver can be written straight against it.

```python
ingest = Ingest(store, token="…", default_driver="ecowitt",
                registry=drivers.DEFAULT, access=PRIVATE_ONLY, limits=limits)
stored, reason, response = ingest.submit(body, path, peer)
```

| Method | What it means |
|---|---|
| `authorised(path)` | Whether a path carries the token |
| `driver_for(path)` | Pick the driver from the path |
| `submit(body, path, peer)` | Accept an upload. Returns `(packets stored, reason, response)` |
| `status()` | Numbers for `/status` |

The **response comes from the driver**. What a device has to hear is part of its
protocol — an Ecowitt gateway expects `{"errcode":"0","errmsg":"ok"}` and
retries otherwise.

`_redacted()` stores the upload as it arrived, with whatever the driver deems
secret taken out. **Redaction is protocol knowledge**: only the driver knows
that Ecowitt's `PASSKEY` identifies the station.

## The paths

The driver is picked from the path:

```
POST /<token>/               → the default driver
POST /<token>/ecowitt/       → that driver
POST /<token>/json/          → the envelope driver
GET  /<token>/?ID=…&…        → Wunderground protocol, readings in the query string
```

Diagnostics, all behind the token:

| Path | What |
|---|---|
| `GET /<token>/live` | The status page |
| `GET /<token>/` | The same |
| `GET /<token>/status` | JSON: counters, drivers, limits |
| `GET /<token>/recent` | JSON: the last packets, for the page |
| `GET /` (no token) | `weewx-evo`, nothing else |

The diagnostic pages sit on the upload path, because that path is the only thing
keeping strangers out — a page showing what a station is measuring should not be
easier to reach than the endpoint that records it.

## Why the token is in the path

Hardware cannot send headers. An Ecowitt console has a field for host, port and
path — and nothing more. So a path nobody can guess is the practical answer.

That makes the token **guessable** in the sense that someone can try. Hence the
tight limit on failed attempts. → [Security](Security)

## Limits of the core

| | |
|---|---|
| `MAX_BODY` | 1 MiB. Nothing beyond that is read |
| `MAX_RAW` | 8 KiB. That much of the raw upload is kept |

## The transports

### `HttpListener`

`ThreadingHTTPServer`. One slow console must not block the others.

```python
listener = HttpListener(ingest, host="0.0.0.0", port=8000)
listener.start()      # thread
listener.stop()
```

### `UdpListener`

For hardware that broadcasts instead of posting.

```python
UdpListener(ingest, host="0.0.0.0", port=8001, driver="json")
```

A datagram carries no path, so there is no token in it: **the port itself is the
access control**, and the driver is fixed. `0` turns it off, and that is the
default.

### `push()`

```python
push(packets, host="127.0.0.1", port=8000, token="…")
```

This is how a **pull** driver delivers. Going over loopback instead of writing
straight into the database is deliberate: it costs a millisecond and buys
process isolation. A driver that hangs, hangs in its own process.

## Order of the checks

```
1. _permitted()   Is the peer on a network we answer at all?
                  No → 404. Not "wrong network": that would give away
                  that there is something here.
2. Rate limit     Too many requests → 429 with Retry-After.
3. _has_token()   Wrong token → 404 and a failed attempt recorded.
4. driver_for()   Pick the driver.
5. driver.packets(body, meta)
6. store.add_all(packets)
```

**Checking costs nothing, only a real failure pays.** `_has_token()` checks and
counts in **one** place. That used to be split — `submit` counted a wrong token,
the pages did not — and `tools/ratelimit_test.py` now holds it in place. Without
that separation a console would have locked itself out after five **valid**
uploads.

→ [Security](Security)

## The status page

`ingest/statuspage.py`. A page showing what is arriving right now.

It exists for exactly one question, the one you keep asking while setting things
up: *is anything coming in?* Answering it otherwise means SSH, `docker exec` and
a hand-written SQL query.

| | |
|---|---|
| `recent(store, ingest, limit=12)` | The last packets and how it is going |
| `render(title)` | The page. One file, no dependencies |
| `short_source(source)` | Shorten source names to 8 characters |

`HEADLINE` sets what is shown large at the top: outside temperature, humidity,
barometer, wind, rain.

## Configuration

→ [Settings-Reference](Settings-Reference#listener)

```bash
weewx-evo listen --port 8000 --token … --driver ecowitt \
                 --allow private --rate 10
```

<!-- covers
src/weewx_evo/ingest/listener.py
src/weewx_evo/ingest/statuspage.py
tools/ratelimit_test.py
tools/netaccess_test.py
-->

# MQTT

`mqtt.py` and `uploads/mqtt.py`. An MQTT 3.1.1 client out of the standard
library, and the upload that uses it.

## Why this exists

MQTT is how a modern skin comes alive. Belchertown, jas, weewx-wdc and Weather34
all get their live updates from an MQTT broker over websockets. Without one
those skins render completely — and then sit still until somebody reloads the
page.

Since the [Cheetah feed](Feeds) exists in order to run exactly those skins
unchanged, the broker is not an extra.

## Why it is written here

`paho-mqtt` is the obvious answer and a dependency, and this core runs on the
standard library. That is not a slogan: it is what makes `pip install weewx-evo`
work on a Raspberry Pi with no compiler and with no exception in a network
policy. A convenience library is not what you spend that on.

And the trade is smaller than it looks. MQTT 3.1.1 has been frozen since 2014,
the wire format is a byte layout rather than a negotiation, and what a weather
station needs is a fraction of it.

**Deliberately not in it:**

- **QoS 2.** Four packets to deliver a temperature exactly once that will be
  superseded in five minutes. QoS 1 is what every weather skin uses, and
  duplicates are harmless when the payload carries its own timestamp.
- **Session resumption.** A clean session every time. What there would be to
  resume is in the archive, and that is the better store.
- **MQTT 5.** Nothing here needs its properties, and brokers speak 3.1.1 in
  every installation a station will meet.

What is taken seriously is **reconnecting**. A domestic connection drops, a
broker restarts, a container gets rescheduled — and a client that gives up on
the first of those is worse than no MQTT at all: the skin carries on showing
whatever was true at the moment it dropped.

## Two pitfalls, both found by the test

**A QoS 1 publish has to wait for its *own* PUBACK.** A client that takes the
next incoming packet for the acknowledgement passes every simple test — and
breaks the moment somebody also subscribes, because incoming PUBLISH packets
then get in between. The test broker therefore slips one in on purpose.

**If the connection drops during a read, only the read notices.** `_write`
cannot: sending into a socket whose far end has closed succeeds into the kernel
buffer and reports nothing. Without the cleanup at the reading end, the client
believes it is connected, every later publish vanishes, and the log stays
silent.

## The topics are not ours

The layout is that of `matthewwall/weewx-mqtt`, because that is what these skins
are written against, and it is what eight years of installation instructions
tell people to configure.

So it is adopted rather than improved:

- The default topic is `weather`, and every reading goes to `weather/<name>`.
- Names carry a unit suffix — `outTemp_C`, `windSpeed_mph` — from a reduction
  table in which `degree_compass`, `percent` and `uv_index` deliberately stay
  bare.
- The same record additionally goes as one JSON document to `weather/loop`,
  because a browser with one subscription is cheaper than with forty.

Both at once is the default there and here too. A skin uses one or the other,
and nobody has to work out which.

**Retained, by default.** A retained message is handed to a browser the moment
it subscribes — so the page shows the current conditions immediately rather than
an empty dashboard until the next archive record. Without it a skin looks broken
for up to five minutes after every load, and that is the most common complaint
about MQTT weather dashboards there is.

## Live rather than every five minutes

An archive record is a five-minute mean that arrives five minutes late. A
dashboard showing one is out of date for four minutes and fifty-nine seconds.

Which is why the MQTT upload is the only one with the `live` trigger: it reads
the [live table](Database-Live) every few seconds and publishes what is new.

It reads from the database rather than through a callback from the listener —
which is exactly what lets listener and archiver stay separate processes. A live
channel that only worked when both are one process would quietly undo that.

In a split installation where this process has the archive and another has the
packets, the upload falls back to the archive record: late rather than not at
all.

## Home Assistant

`uploads/homeassistant.py`. Home Assistant picks up MQTT topics on its own — but
only when it is told what they are: one retained JSON document per reading, on a
topic under `homeassistant/`.

Publish that once, and the station appears as a device with named, graphed,
unit-aware sensors. No YAML, no restart, nothing typed twice.

Two decisions:

- **Always retained**, whatever `retain` says for the readings. A discovery
  message nobody retained is seen only by a Home Assistant that was running in
  that exact second.
- **Once per connection, not per reading.** The definitions do not change
  between two readings, and forty documents every ten seconds would be most of
  the traffic. After a reconnect they go out again, because a broker restarted
  without persistence has forgotten them.

A wrong `device_class` is not cosmetic: `pressure` on a temperature makes the
trace unreadable, and a unit Home Assistant does not know turns the sensor into
a string with no graph. Millibars and hectopascals are the same thing, and `hPa`
is what Home Assistant leads with.

A daily rainfall total is set to `total_increasing`: it drops back to zero at
midnight, and as `measurement` that would read as negative rain.

## Configuration

```toml
[uploads.broker]
kind = "mqtt"
host = "localhost"
topic = "weather"
# default: live, every 10 seconds
home_assistant = true
```

## Checking it

```bash
python tools/mqtt_test.py
```

A broker on loopback, enough of MQTT 3.1.1 to answer honestly. It is
deliberately strict: it rejects a SUBSCRIBE whose fixed flags are not `0b0010` —
a real broker then closes the connection with no explanation, and that is a long
afternoon.

What is checked is what actually goes over the socket: the byte layout of
CONNECT, that a QoS 1 publish waits for its own PUBACK, that a rejected password
is rejected permanently, and that a dropped connection comes back with its
subscriptions.

`broker_test.py` drives the broker from the other side: with our own client,
and with a websocket built by hand and masked the way a browser masks it. The
last check is the whole chain — a record through the real upload, into our own
broker, out to a page — with nothing else installed.

→ [Uploads](Uploads) · [Live database](Database-Live) · [Feeds](Feeds)

# Security

`netaccess.py`, `ratelimit.py`, and the token policy.

> **As simple as possible, as secure as necessary.**

The usual installation is on a home network: a small machine in a shed or a
cupboard, a console on the same Wi-Fi, and somebody who wants to look at the
settings from a laptop in the kitchen. Everything follows from that.

## Who gets an answer

`netaccess.py`.

**Bound to `0.0.0.0`, answering private networks only.**

Binding to localhost turns the laptop in the kitchen into an SSH tunnel — one
thing too many to explain. Binding to everything and hoping for the best is how
a configuration page ends up on Shodan.

```python
PRIVATE = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12",
           "192.168.0.0/16", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10")
LOOPBACK = ("127.0.0.0/8", "::1/128")
```

A **reverse proxy always connects from loopback** or from the Docker bridge
network, both private — so it works on its own, without anything having to be
opened up. That is why this default holds.

```python
class Access:
    @classmethod
    def parse(cls, setting: str | None) -> Access: ...
    def allows(self, address: str) -> bool: ...
```

| Value | What it means |
|---|---|
| `private` | The default. The networks above |
| `any` | Everything, including the open internet |
| `10.0.0.0/8, 203.0.113.4` | A list of networks and individual addresses |

**Loopback is always added**, whatever is written there: locking yourself out
from your own machine is no security gain.

`PRIVATE_ONLY` and `EVERYONE` are the two ready-made instances.

`warn_if_open(access, what)` says **once** at startup when a service is
answering the whole internet. The open internet is a deliberate decision
(`--allow any`), and a deliberate decision deserves a line in the log.

### Why 404 and not 403

A peer from a network that is not answered gets **404** — the same as a wrong
token.

Saying "wrong network" would confirm that there is something here.

## Two tokens, two ports

| | Can | Port |
|---|---|---|
| Upload token | At worst write a wrong reading | 8000 |
| Admin token | Point the archive at a different file | 8080 |

**The same token for both is refused.**

### Why the token is in the path

Hardware cannot send headers. An Ecowitt console has a field for host, port and
path. So a path nobody can guess is the practical answer.

That makes the token **worth trying** — it shows up in proxy logs, in browser
histories, in referrers. Hence the second, tight limit.

## The two limits

`ratelimit.py`. Two limits, because there are two different things to be afraid
of and one number does not serve both.

| | Default | Why |
|---|---|---|
| **Requests that work** | 10/s per address | A console uploads every eight seconds; a Vantage sends a LOOP packet every two. Even a station with several consoles and a driver catching up after an outage stays under one per second. Ten is headroom |
| **Wrong tokens** | 5/min per address | This is the effective limit. The token is in the path and is therefore guessable |

The second is the one that does something. The first only catches what has gone
wrong.

### Checking costs nothing, only a real failure pays

That is the rule that makes the difference.

```python
limits.has_attempts_left(address)   # asks without paying
limits.failed(address)              # this one pays
limits.succeeded(address)           # a correct token: forget the failures
```

**That was a bug and is now a test** (`tools/ratelimit_test.py`): otherwise a
console would have locked itself out after five **valid** uploads.

The reason was that the check sat in two places — `submit` counted a wrong
token, the diagnostic pages did not. Now `_has_token()` does both in one place.

### The answers

| Situation | Answer | Why |
|---|---|---|
| Wrong token | **404**, always | Saying "too many attempts" would confirm that there is something to attempt |
| Wrong network | **404** | The same |
| Too many requests | **429** with `Retry-After` | This is a **real client** being told to slow down |

The comment in the code puts it briefly: `# 429 here, not 404: this one is a
real client being told to slow down`.

### How it is built

```python
class Bucket:
    """Token bucket: tokens grow at `rate` up to `burst`, every request costs one."""
```

That shape is the right one here: a console that was offline and is posting its
backlog may burst without being turned away.

```python
class Limiter:
    def __init__(self, rate, burst=None, capacity=4096, name="requests"): ...
```

**`capacity` matters.** One entry per address is irrelevant on a home network and
on a public one is a way for a machine to run out of memory. The oldest entries
drop when the table is full.

```python
class Limits:
    """What a service uses: one limit for requests, a tighter one for failures."""
```

`announce(limits, what)` says at startup what is limited — and what is not.

### Behind a reverse proxy

`behind_proxy = true` turns the rate limit off.

Every request then comes from the proxy's address, and a per-address limit would
slow down **everyone except whoever caused it**. Limiting stays with the proxy,
which is the only one that knows the real address.

## A driver in the process

**Cannot be caged.** A driver is Python in the same interpreter, `import
sqlite3` is enough, and no interface stops code from going round it. WeeWX has
the same property.

The layer in between is a **contract, not a cage**: a driver gets a `state` with
`get`/`set`/`delete` on strings, not the `ArchiveStore`. What that does is make
the right thing easy and the wrong thing a visible, deliberate act.

Enforcement happens outside the process:

| Means | Effect |
|---|---|
| `listen` and `archive` split (`deploy/split.yml`) | The listener never opens the archive. A driver inside it **does not have the file** |
| A separate user without write permission on the archive | Makes the question moot |
| `driver install` reads the code | Reports `sqlite3`, `subprocess`, `socket`. A hint, not a guarantee |

→ [Drivers](Drivers), [Deployment](Deployment)

## The container

`deploy/split.yml` additionally sets:

```yaml
read_only: true
tmpfs: [/tmp]
security_opt: [no-new-privileges:true]
cap_drop: [ALL]
```

And the process runs as an unprivileged user (`Dockerfile`, uid 1001). It is
reachable from the internet through Caddy and has no reason to own the files it
writes, beyond writing them.

## Traversal

The web server checks that a resolved path lies **inside** the feed's directory.
A feed's directory is written from a template, and a template that can be made
to write `../../etc` is one that somebody eventually writes by accident.
→ [Web-Server](Web-Server)

## What gets redacted

A raw upload is kept for a while so that it can be attached to an issue.
**Redaction is protocol knowledge** — only the driver knows what is a secret in
its protocol:

```python
SECRETS = ("PASSKEY", "ID", "PASSWORD", "key", "stationkey")   # ecowitt
```

The PASSKEY identifies an Ecowitt station and is what somebody would need in
order to forge its readings. Everything else in an Ecowitt upload is readings.

The admin page too **never** hands a `secret` back: it shows *whether* one is
set. A token that has been displayed once is a token in a screenshot.

## Checking it

```bash
python tools/netaccess_test.py    # who gets an answer
python tools/ratelimit_test.py    # the two limits
python tools/web_test.py          # the directory boundary
```

`netaccess_test.py` drives the servers with a socket whose source address really
is different — **a peer address cannot be forged over TCP**, so this is really
checkable and not mocked.

<!-- covers
src/weewx_evo/netaccess.py
src/weewx_evo/ratelimit.py
-->

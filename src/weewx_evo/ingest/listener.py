"""The listener every push driver sits behind.

One process accepts HTTP and UDP, hands the bytes to a driver, and writes the
packets it gets back to the live table. Drivers do not open sockets, do not
check tokens, and do not touch the database -- which is the whole point: those
three are where push drivers go wrong, and doing them once is doing them once.

Which driver runs is decided by the path (`/<token>/ecowitt/`) or by
configuration. The drivers are plugins and this file knows none of them --
including what to answer with, which is protocol knowledge the driver owns.
See ingest/drivers.py.

It answers 200 to anything a driver accepted and 200 to most of what it could
not read. Weather consoles are not HTTP clients: they send requests with no
Host header and bare newlines for line endings, they ignore status codes, and
some of them stop uploading for an hour after a 4xx. Being strict with them
loses measurements and teaches nobody anything.
"""

from __future__ import annotations

import json
import logging
import socket
import socketserver
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from ..db.live import LiveStore, Packet, sender_id
from ..netaccess import PRIVATE_ONLY, Access
from ..ratelimit import Limits
from . import drivers, statuspage

log = logging.getLogger(__name__)

MAX_BODY = 1 << 20  # 1 MB. No console sends more; anything that does is not one.
#: A kept upload is for reading, so it is capped well below MAX_BODY.
MAX_RAW = 8192
MAX_DIAGNOSTICS = 256
INVALID_DIALECT = "<invalid>"

#: The driver name a sighting gets when nothing could read the upload.
#:
#: Angle brackets so it cannot collide with a real driver: `driver_for`
#: returns a path segment, and a segment cannot contain them.
UNREAD = "<unread>"

#: How much of an unreadable body is kept beside such a sighting.
#:
#: Enough for the catalogue's patterns to recognise a protocol -- a `PASSKEY=`
#: is in the first forty characters of an Ecowitt upload -- and little enough
#: that a credential further in is not carried along. It cannot be redacted:
#: redaction is protocol knowledge, and the driver holding it is the one that
#: is missing.
UNREAD_BYTES = 160


def _first(seen: set, key: object) -> bool:
    """Remember a diagnostic without letting attacker-made names grow forever."""
    if key in seen or len(seen) >= MAX_DIAGNOSTICS:
        return False
    seen.add(key)
    return True


class Ingest:
    """What the listener does with an upload once it has one.

    Kept separate from the transports so the same object serves HTTP, UDP and
    the tests, and so a pull driver can be written against it directly.
    """

    def __init__(self, store: LiveStore, token: str | None = None,
                 default_driver: str = "ecowitt",
                 registry: drivers.Registry | None = None,
                 access: Access = PRIVATE_ONLY,
                 limits: Limits | None = None,
                 stations: object | None = None,
                 sightings: object | None = None,
                 infer_unknown: str = "series") -> None:
        self.store = store
        self.token = token
        self.default_driver = default_driver
        self.registry = registry or drivers.DEFAULT
        #: Which consoles are announced, and what to call them. None means
        #: nothing is announced, which is every installation that has not been
        #: through the settings page yet -- so packets keep the identity their
        #: driver gave them and nothing changes.
        self.stations = stations
        #: Where uploads from anything unannounced are noted.
        self.sightings = sightings
        #: Turns a stored reading into archive column names, for the
        #: status page's headline. The table underneath it shows the
        #: names the console used, which is the point of that page.
        self.placer: object | None = None
        #: Where a raw name nothing has placed is noted, with whatever the
        #: driver would guess about it. The one place inference runs, so
        #: that the read side can be a lookup -- see ingest/proposals.py.
        self.proposals: object | None = None
        #: What to do about a name no catalog knows. Passed to the driver
        #: when a proposal is recorded and nowhere else.
        self.infer_unknown = infer_unknown
        #: Called after packets are stored, for feeds that want every reading
        #: rather than every record. A callback rather than a reference to the
        #: feed runner: the listener has no business knowing feeds exist, and
        #: the two are wired together where both are already in scope.
        self.on_packets: object | None = None
        # Bound to everything, answering only what is on a private network. A
        # console is on the same wifi, and a reverse proxy connects from
        # loopback. Anything further away is a decision somebody makes.
        self.access = access
        self.refused_peers = 0
        # A generous limit on requests, a tight one on wrong tokens. The
        # second is the one that matters: the token is in the path, so it can
        # be guessed at by anyone who reaches the port.
        self.limits = limits or Limits()
        self.accepted = 0
        self.duplicates = 0
        self.rejected = 0
        self.last_packet: float | None = None
        self._undescribed: set[tuple[str, str]] = set()
        #: Which protocols have been let in without a token, so that the
        #: reason is in the log once rather than every eighteen seconds.
        self._untokened: set[tuple[str, str]] = set()
        self._lock = threading.Lock()
        self._sync_sender_labels()

    def _sync_sender_labels(self) -> None:
        """Publish listener-owned names through the live DB boundary."""
        if self.stations is None:
            return
        sync = getattr(self.store, "sync_sender_labels", None)
        if sync is None:
            return
        try:
            sync(self.stations)
        except Exception:
            # A label is presentation metadata. Losing it must be loud, but it
            # must not lose the raw measurement whose canonical sender id is
            # still written with the packet.
            log.exception("could not update sender labels in the live database")

    def authorised(self, path: str, query: str = "", body: bytes = b"",
                   peer: str = "") -> bool:
        """Whether this upload may be recorded. Three ways, one of them not a token.

        The token is a path segment rather than a header because consoles
        cannot send headers. It is the only thing between the open internet and
        the measurement series, so a listener configured without one says so
        loudly at startup.

        `query` is the second place it may sit, and only for one reason:
        Weather Underground protocol consoles have no path field. Host and
        port are all most of them offer, and the path is fixed in firmware --
        so for those the token goes in `PASSWORD`, which every one of them
        has, was always meant to hold a shared secret, and is where an
        operator looks for one. `ID` is accepted too, because a few validate
        the shape of the password field.

        Nothing is weakened by it: the token is a path segment on every other
        upload and lands in the same access logs either way. What would weaken
        it is the alternative people reach for otherwise, which is running the
        listener with no token at all because their console cannot send one.

        And that is exactly what the third way is for. `takes_without_token`
        is the narrow case where no token can exist, because the hardware has
        no field to hold one.
        """
        if self.token is None:
            return True
        if self.token in path.strip("/").split("/"):
            return True
        from urllib.parse import parse_qsl
        for name, value in parse_qsl(query, keep_blank_values=True):
            if name in ("PASSWORD", "ID") and value == self.token:
                return True
        return bool(self.takes_without_token(body, path, peer))

    def own_network(self, peer: str) -> bool:
        """Whether this address could be a console on the same network as us.

        Not `self.access`, which is what the port was opened to and can be
        `any`. This is the narrower question, and it is what makes the answer
        worth anything: a DNS entry pointing hardware here only resolves
        inside the network that serves it, so an upload claiming to be from
        such a console cannot honestly have come from outside one.

        Behind a proxy nothing in this process can answer it. Every request
        arrives from loopback, and who really connected is a header anybody
        can write -- the same reason the rate limiter switches itself off
        there. So this shuts rather than guesses, and the hardware it is for
        is reached with a port redirect, which is what its own instructions
        say to do.
        """
        if self.limits.behind_proxy:
            return False
        return PRIVATE_ONLY.allows(peer)

    def takes_without_token(self, body: bytes, path: str, peer: str) -> str:
        """Which driver may take this upload without one. Empty for none.

        Three protocols here can present no secret at all: an Acurite bridge
        and a LaCrosse gateway post to an address burned into their firmware
        and are pointed at us with a DNS entry, and a WeatherFlow hub
        broadcasts. There is no path to put a token in and no password field
        to put one in either, so requiring one refuses them for the life of
        the installation -- and worse than refuses, because five refusals a
        minute is the wrong-token limit and a bridge uploads every eighteen
        seconds. It locks itself out in under two minutes.

        Which hardware that is, is the driver's to say and not ours:
        `Setup.secret` already carries it (`path`, `password`, or empty), and
        this reads it. So the door opens for a protocol only once somebody has
        installed the driver for it -- and installing the Acurite driver and
        redirecting Chaney's domain at this machine is the same decision said
        twice.

        The three conditions are each load-bearing:

            the network   a DNS redirect does not reach out of it
            a claim       an actual driver recognising it, never the default
            no secret     or the token on an Ecowitt could be skipped by
                          leaving it out of the path

        What this is not is authentication. It is the network standing in for
        one, and what follows is the same as for any unannounced sender: it is
        recorded, it shows up on the page as something nobody announced, and
        the operator says what it is.
        """
        if not body or not self.own_network(peer):
            return ""
        name = self.registry.claimant(body, {"path": path})
        if not name:
            return ""
        setup = drivers.setup_of(self.registry.get(name))
        if setup is None or setup.secret:
            return ""
        if _first(self._untokened, (name, peer)):
            log.info("taking %s uploads from %s without a token: that hardware "
                     "has no field for one, and this address is on a local "
                     "network", name, peer)
        return name

    def driver_for(self, path: str, body: bytes = b"") -> str:
        """Which driver reads this upload.

        The path first, because a console that can be told one has said what
        it is: `/<token>/ecowitt/`. Nothing to guess at, and it costs a string
        comparison.

        Where the path says nothing, the drivers are asked. That happens more
        often than it sounds: an Ambient WS-2902 has no server-path field at
        all and is reached by pointing DNS at us, so the path is whatever its
        firmware burned in; several firmwares refuse to upload with an empty
        path, so people type `index.php?` to get past it. And a path typed
        wrongly is the same situation with worse symptoms -- without this the
        upload goes to the default driver, gets about half its fields placed,
        and looks like a station with dead sensors.

        The core still knows no weather protocol: it asks and compares
        numbers. Which byte in a body means Ecowitt is the Ecowitt driver's
        business, and a driver added later brings its own answer with it.
        """
        for segment in path.strip("/").split("/"):
            if self.registry.known(segment):
                return segment
        if body:
            claimed = self.registry.claimant(body, {"path": path})
            if claimed:
                return claimed
        return self.default_driver

    def submit(self, body: bytes, path: str = "/", peer: str = "?",
               query: str = "") -> tuple[int, str, drivers.Response]:
        """Take one upload. Returns (packets stored, reason, what to answer with).

        The response comes from the driver. What a device needs to hear is part
        of its protocol -- an Ecowitt gateway wants a particular JSON object and
        backs off for an hour if it does not get it -- so the core repeats what
        the driver says rather than deciding for itself.

        `query` is only for consoles that cannot put the token in the path;
        see `authorised`.
        """
        if not self.authorised(path, query, body, peer):
            with self._lock:
                self.rejected += 1
            # Count the guess before reporting it. An address that keeps
            # trying runs out of attempts rather than out of patience.
            self.limits.failed(peer)
            log.warning("rejected upload from %s: bad or missing token", peer)
            return 0, "unauthorised", drivers.DEFAULT_RESPONSE
        self.limits.succeeded(peer)

        name = self.driver_for(path, body)
        driver = self.registry.get(name)
        if driver is None:
            self._unread(name, path, peer, body)
            return 0, f"no driver {name!r}", drivers.DEFAULT_RESPONSE

        response = drivers.response_of(driver)
        meta = {"received": int(time.time()), "source": peer}
        try:
            packets = driver.packets(body, meta)
        except Exception as exc:
            with self._lock:
                self.rejected += 1
            log.warning("the %s driver could not read an upload from %s: %s",
                        name, peer, exc)
            # Answer anyway. A console that gets an error stops uploading, and
            # the next measurement is worth more than the tidy status code.
            return 0, "unreadable", response

        try:
            stored = self._store(packets, driver, name, peer, body)
        except Exception as exc:
            with self._lock:
                self.rejected += 1
            log.exception("could not record an upload from %s via %s", peer, name)
            # Same rule as the driver above, one step further down: a full
            # disk, a locked database or a rule file somebody mistyped is our
            # problem, and none of it is a reason for the console to stop.
            # It measures every few seconds and forgets; this end is where a
            # reading can be recovered from, and only while uploads keep
            # arriving.
            return 0, f"could not store: {type(exc).__name__}: {exc}", response
        return stored, "ok", response

    def _unread(self, name: str, path: str, peer: str, body: bytes) -> None:
        """Something uploaded with the right token and nothing can read it.

        A log line was all this used to be, and that was survivable while the
        protocols shipped with the core: the driver was missing because
        somebody had mistyped a path.

        With the drivers installed one at a time it is the ordinary first-run
        state instead. Console set up, token right, nothing on any page -- and
        the operator is left comparing a log line against a catalogue.

        So it is kept: what arrived, from where, and enough of the body for
        the catalogue's own patterns to say which add-on reads it. The core
        learns no protocol from this; it keeps a string and lets something
        that knows recognise it.
        """
        log.warning("no driver named %r; known: %s",
                    name, ", ".join(self.registry.names()))
        if not self.sightings:
            return
        try:
            # `identity` is the path it came in on, because that is the only
            # thing telling two of these apart: nothing has parsed the body,
            # so there is no PASSKEY and no serial number to key on.
            #
            # Not redacted, and it cannot be: redaction is protocol knowledge
            # and the driver that has it is the one missing. So it is capped
            # hard and marked, and the page prints it as evidence rather than
            # as readings.
            opening = body[:UNREAD_BYTES].decode("utf-8", "replace")
            self.sightings.saw(UNREAD, path or "/", peer,
                               fields=[opening])
        except Exception:
            # A sighting is a convenience. Failing to record one must not
            # change what the console is told, or a full disk would turn into
            # hardware that stops uploading.
            log.debug("could not record an unreadable upload", exc_info=True)

    # -- what a driver went and asked for ---------------------------------

    def begin(self) -> list[str]:
        """Let every driver start whatever it runs on its own.

        Hardware with nowhere to type an address into has to be asked, and
        `Driver.start` is where a driver does the asking. Returns the names
        that started, for the log.

        One that raises is reported and skipped, the same rule as everywhere
        else on this path: the protocols that push still have measurements
        arriving, and losing those over one sensor's bad address is by far
        the worse outcome.
        """
        started = []
        for name in self.registry.names():
            driver = self.registry.get(name)
            begin = getattr(driver, "start", None)
            if begin is None:
                continue
            try:
                begin(lambda body, _name=name: self.fetched(_name, body))
            except Exception:
                log.exception("the %s driver would not start; carrying on "
                              "without whatever it polls", name)
                continue
            started.append(name)
        return started

    def finish(self) -> None:
        """Stop what `begin` started. Safe to call without it."""
        for name in self.registry.names():
            done = getattr(self.registry.get(name), "close", None)
            if done is None:
                continue
            try:
                done()
            except Exception:
                log.exception("the %s driver would not stop cleanly", name)

    def fetched(self, name: str, body: bytes) -> int:
        """One answer a driver asked for, stored as though it had arrived.

        The same door an upload comes through, minus the two things that
        guard the door: no token and no rate limit. Nothing here crossed a
        network boundary this process did not open itself, and asking a
        driver to know the upload token so it could hand it back would be a
        secret travelling in a circle.

        Everything after that is identical -- the same parse, the same raw
        names, the same redaction, the same live table. So a polled sensor
        reaches a page and an archive by the route a pushed one does, and
        nothing downstream has to learn that there are two kinds.
        """
        driver = self.registry.get(name)
        if driver is None:
            log.warning("the %s driver delivered a reading after it was "
                        "unregistered; dropping it", name)
            return 0
        meta = {"received": int(time.time()), "source": "poll"}
        try:
            packets = driver.packets(body, meta)
        except Exception as exc:
            with self._lock:
                self.rejected += 1
            log.warning("the %s driver could not read what it fetched: %s",
                        name, exc)
            return 0
        try:
            return self._store(packets, driver, name, "poll", body)
        except Exception:
            with self._lock:
                self.rejected += 1
            log.exception("could not record what the %s driver fetched", name)
            return 0

    def _store(self, packets: list, driver: object, name: str, peer: str,
               body: bytes) -> int:
        """Put the parsed packets in the table. Everything that can fail."""
        # Keep the upload beside the packet for a while. What a driver could
        # not place is by definition not in the packet, so the parsed version
        # is the one thing that cannot show it -- and getting hold of a raw
        # upload otherwise means reconfiguring a console and waiting.
        raw = None
        if self.store.keep_raw_seconds and packets:
            raw = self._redacted(driver, body)

        stored = 0
        for one in packets:
            packet = self._named(one, name, peer)
            if (packet.dialect is not None
                    and not drivers.valid_dialect_name(packet.dialect)):
                if _first(self._undescribed, (name, INVALID_DIALECT)):
                    log.error(
                        "the %s driver returned an invalid dialect name; its "
                        "readings are kept but cannot be archived", name)
                packet = replace(packet, dialect=INVALID_DIALECT, mapping=None)
            else:
                mapping = drivers.dialect_spec_of(driver, packet)
                if mapping is None:
                    key = (name, packet.dialect)
                    if packet.dialect is not None and _first(
                            self._undescribed, key):
                        log.error(
                            "the %s driver returned raw %r readings without a "
                            "declarative dialect mapping; they are kept, but an "
                            "archive cannot translate them", name, packet.dialect)
                # Always replace it. A driver that labels its names as WeeWX
                # cannot smuggle a large, unvalidated document into the DB by
                # setting mapping while leaving dialect empty.
                packet = replace(packet, mapping=mapping)
            if raw is not None and packet.raw is None:
                packet = replace(packet, raw=raw)
            if self.store.add(packet):
                stored += 1
                self._propose(packet)
            else:
                with self._lock:
                    self.duplicates += 1

        with self._lock:
            self.accepted += stored
            if stored:
                self.last_packet = time.time()
        if stored and self.on_packets is not None:
            try:
                self.on_packets()
            except Exception:
                # A feed that cannot be woken must not cost the reading that
                # was being stored when it happened.
                log.exception("could not hand the reading on to the feeds")
        return stored

    def _propose(self, packet: Packet) -> None:
        """Note any raw name this installation has not placed before.

        The one place inference runs. Costs a set difference on the ordinary
        path -- a console sends the same field names every sixteen seconds,
        so after the first packet there is nothing new and the driver is not
        asked anything.

        Never fatal. A guess that cannot be recorded is a row missing from a
        settings page; the reading itself is already stored, which is what
        makes the guess recoverable at all.
        """
        if self.proposals is None:
            return
        try:
            # A placement is keyed by the immutable sender id. The friendly
            # station name is live-database metadata for pages only; using it
            # here would make a rename change which decision a rebuild reads.
            self.proposals.saw(packet,
                               packet.sender_id,
                               self.registry.get(packet.driver),
                               self.infer_unknown)
        except Exception:
            log.debug("could not record what %r sends", packet.driver, exc_info=True)

    def _named(self, packet: Packet, driver: str, peer: str) -> Packet:
        """Stamp the packet with the driver that read it, and note a stranger.

        The driver name is stamped here rather than by the driver itself
        because this is what knows the name it is registered under -- one
        driver answering two protocols is registered twice, and a driver that
        had to know its own name would be one more thing to keep in step.

        Together with the identity the hardware gave, that pair is how a
        packet is recognised for as long as it is in the table. **The station
        name is not written down**: it is a lookup that changes, and freezing
        it here is what used to split a series in two the moment somebody
        renamed a console.

        **Nothing is refused, and nothing is left out.** An upload from
        something not announced is stored exactly as it arrived and noted on
        the settings page. What a console records, which of its readings this
        installation wants and where they go is decided when a record is
        built, from files somebody can change afterwards -- see
        `placement.py`.
        """
        packet = replace(packet, driver=driver,
                         sender=sender_id(driver, packet.identity))
        if self.stations is None:
            return packet
        # The settings page writes that file and this is a different process.
        # Without re-reading it, a console adopted on the page keeps arriving
        # as a stranger until somebody restarts the service -- and restarting
        # a listener to register a station is what people do not do, after
        # which the page looks broken.
        refresh = getattr(self.stations, "refresh", None)
        if refresh is not None:
            if refresh():
                self._sync_sender_labels()
        if self.stations.by_identity(driver, packet.identity) is None and self.sightings:
            # The raw names, which is what somebody adopting this console
            # actually has to look at. They used to be the mapped ones, so a
            # console whose readings the catalog had not placed showed up with
            # a shorter list than it sent and no way to see the difference.
            self.sightings.saw(driver, packet.identity, peer,
                               fields=sorted(packet.data)[:12])
        return packet

    def _redacted(self, driver: object, body: bytes) -> str | None:
        """The upload as it arrived, with whatever the driver calls secret gone.

        Redaction is protocol knowledge: only the driver knows that Ecowitt's
        PASSKEY identifies the station and that everything else in the body is
        weather. So it is asked, and a driver that does not offer to redact has
        its uploads kept verbatim -- which is the honest default, because the
        alternative is guessing at what matters and getting it wrong.
        """
        try:
            text = body.decode("utf-8", "replace")
        except Exception:
            return None
        if len(text) > MAX_RAW:
            text = text[:MAX_RAW] + "...(truncated)"
        redact = getattr(driver, "redact", None)
        if redact is None:
            return text
        try:
            return str(redact(text))
        except Exception:
            log.exception("driver redaction failed; not keeping the raw upload")
            return None

    def status(self) -> dict:
        first, last = self.store.span()
        report: dict = {
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "rejected": self.rejected,
            "packets_held": self.store.count(),
            "oldest_packet": first,
            "newest_packet": last,
            "last_packet_at": self.last_packet,
            "answers": str(self.access),
            "refused_peers": self.refused_peers,
            "rate_limit": self.limits.status(),
        }
        # Whatever the drivers want to say for themselves -- which consoles
        # they answer to, what they refused. The core does not interpret it.
        by_driver = {}
        for name in self.registry.names():
            driver = self.registry.get(name)
            said = drivers.status_of(driver) if driver is not None else {}
            if said:
                by_driver[name] = said
        if by_driver:
            report["drivers"] = by_driver
        return report


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    ingest: Ingest  # set on the server class

    def log_message(self, fmt: str, *args: object) -> None:
        # BaseHTTPRequestHandler's ordinary line contains the complete
        # request target. Here that is a credential: either the upload token
        # is a path segment or a WU console puts PASSWORD/ID in the query.
        # Keep the useful method/status/size and never format the target.
        if fmt == '"%s" %s %s' and len(args) >= 3:
            method = str(args[0]).split(" ", 1)[0]
            log.debug("%s %s %s %s", self.address_string(), method,
                      args[1], args[2])
        else:
            log.debug("%s HTTP request", self.address_string())

    def _request_length(self) -> int:
        """A single non-negative length for a body this server can parse."""
        if self.headers.get("Transfer-Encoding") is not None:
            raise ValueError("transfer encoding is not supported")
        values = self.headers.get_all("Content-Length", [])
        if len(values) > 1:
            raise ValueError("more than one content length")
        if not values:
            return 0
        raw = values[0].strip()
        if not raw or not raw.isascii() or not raw.isdecimal():
            raise ValueError("invalid content length")
        return int(raw)

    def handle_one_request(self) -> None:
        """Every request, with a net under it.

        `submit` guards the two places a failure is expected -- the driver
        reading a body, and the table taking the result. This catches the
        rest: a header that will not parse, a status page whose data is
        missing, a bug nobody has met yet.

        200 rather than 500, and that is the whole reason this exists. A
        console has no operator and no retry queue: an error is often the
        last thing it does before going quiet, and the fault is at this end
        anyway. The measurement it was carrying is lost either way; the
        thousand after it need not be.

        The log gets the traceback, and the status page counts the upload as
        rejected, so a failure that only ever answers 200 is still visible
        somewhere a person looks.
        """
        self._answered = False
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            # A console that hung up. Common on cheap hardware, and there is
            # nothing to say about it.
            self.close_connection = True
        except Exception:
            log.exception("a request to the listener failed")
            with self.ingest._lock:
                self.ingest.rejected += 1
            if not self._answered:
                try:
                    self._reply(200, drivers.DEFAULT_RESPONSE[0],
                                drivers.DEFAULT_RESPONSE[1])
                except Exception:
                    self.close_connection = True

    def _has_token(self, path: str) -> bool:
        """Check the token and count a wrong one, in one place.

        Both matter and they were split before: `submit` counted a wrong
        token, the pages did not, so a search that only ever asked for
        /<guess>/live was never slowed down at all.
        """
        peer = self.client_address[0] if self.client_address else ""
        if self.ingest.authorised(path):
            self.ingest.limits.succeeded(peer)
            return True
        self.ingest.limits.failed(peer)
        return False

    def _worth_a_body(self, path: str) -> bool:
        """Whether to read this upload's body at all.

        A token in the path settles it here, before a byte of body is read.
        Where there is none the question cannot be settled yet -- hardware
        that carries no token is recognised by what it sends, and that is the
        body -- so this defers to `submit`, which asks properly and counts a
        wrong guess if it was one.

        What it still refuses outright is anything from outside the local
        network, and that is the whole job: without it, anybody who can reach
        the port could announce a long body and send it a byte at a time,
        holding a request thread for as long as they like.
        """
        peer = self.client_address[0] if self.client_address else ""
        if self.ingest.authorised(path):
            self.ingest.limits.succeeded(peer)
            return True
        if self.ingest.own_network(peer):
            return True
        self.ingest.limits.failed(peer)
        return False

    def _permitted(self) -> bool:
        """Whether this peer is on a network we answer at all.

        Checked before the token, and refused with the same 404. Saying "wrong
        network" would tell somebody scanning that there is something here
        worth finding the right network for.
        """
        peer = self.client_address[0] if self.client_address else ""
        if not self.ingest.access.allows(peer):
            self.ingest.refused_peers += 1
            log.warning("refused %s: this listener answers %s",
                        peer, self.ingest.access)
            self._reply(404, b"not found")
            return False
        if not self.ingest.limits.has_attempts_left(peer):
            # Out of wrong guesses. The same 404 a wrong token gets: saying
            # "too many attempts" would confirm there is something to attempt.
            self._reply(404, b"not found")
            return False
        if not self.ingest.limits.allow(peer):
            # 429 here, not 404. This one is a real client being told to slow
            # down, and Retry-After is what tells it by how much.
            self._reply(429, b"slow down", "text/plain", {"Retry-After": "5"})
            return False
        return True

    def _reply(self, code: int, body: bytes, content_type: str = "text/plain",
               headers: dict[str, str] | None = None) -> None:
        self._answered = True
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._permitted():
            # The body is still on the wire. It must not become a second
            # request after the refusal already sent on this connection.
            self.close_connection = True
            return
        path = urlparse(self.path).path
        # Decide whether to wait for a body before waiting for one. Otherwise
        # anybody who can reach the port can occupy a request thread by
        # announcing a long body and sending it one byte at a time. `submit`
        # is where the upload is really authorised; this only decides whether
        # there is any point reading it.
        if not self._worth_a_body(path):
            with self.ingest._lock:
                self.ingest.rejected += 1
            log.warning("rejected upload from %s: bad or missing token",
                        self.client_address[0])
            self.close_connection = True
            self._reply(404, b"not found", headers={"Connection": "close"})
            return
        try:
            length = self._request_length()
        except ValueError:
            with self.ingest._lock:
                self.ingest.rejected += 1
            self.close_connection = True
            self._reply(400, b"invalid request body length",
                        headers={"Connection": "close"})
            return
        if length > MAX_BODY:
            with self.ingest._lock:
                self.ingest.rejected += 1
            # Truncating leaves attacker-controlled bytes on a persistent
            # connection. Refuse the whole upload and close it instead.
            self.close_connection = True
            self._reply(413, b"upload is too large",
                        headers={"Connection": "close"})
            return
        body = self.rfile.read(length) if length else b""

        _stored, reason, response = self.ingest.submit(body, path,
                                                       self.client_address[0])
        if reason == "unauthorised":
            self._reply(404, b"not found")
            return
        self._reply(200, response[0], response[1])

    def do_GET(self) -> None:
        if not self._permitted():
            return
        parsed = urlparse(self.path)
        trimmed = parsed.path.rstrip("/")

        # Diagnostics, all behind the token. They sit on the upload path
        # because that path is the only thing keeping strangers out, and a page
        # showing what a station is measuring should not be easier to reach
        # than the endpoint that records it.
        for suffix, handler in (("/status", self._status),
                                ("/recent", self._recent),
                                ("/live", self._page)):
            if trimmed.endswith(suffix):
                if not self._has_token(parsed.path):
                    self._reply(404, b"not found")
                    return
                handler()
                return

        # Weather Underground protocol stations upload over GET, with the
        # readings in the query string.
        if parsed.query:
            _stored, reason, response = self.ingest.submit(
                parsed.query.encode(), parsed.path, self.client_address[0],
                query=parsed.query)
            if reason == "unauthorised":
                self._reply(404, b"not found")
                return
            self._reply(200, response[0], response[1])
            return

        # The bare token path is the page. Anything else says nothing.
        if self.ingest.token and trimmed.endswith("/" + self.ingest.token):
            self._page()
            return
        self._reply(200, b"weewx-evo\n")

    def _status(self) -> None:
        self._reply(200, json.dumps(self.ingest.status(), indent=2).encode(),
                    "application/json")

    def _recent(self) -> None:
        try:
            body = json.dumps(statuspage.recent(self.ingest.store, self.ingest)).encode()
        except Exception:
            log.exception("could not assemble the status data")
            self._reply(500, b'{"error":"unavailable"}', "application/json")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _page(self) -> None:
        self._reply(200, statuspage.render(), "text/html; charset=utf-8")


class HttpListener:
    """The HTTP half. Threaded, because a slow console must not block the others."""

    def __init__(self, ingest: Ingest, host: str = "0.0.0.0", port: int = 8000) -> None:
        handler = type("Handler", (_Handler,), {"ingest": ingest})
        self.server = ThreadingHTTPServer((host, port), handler)
        self.server.daemon_threads = True
        self.host, self.port = self.server.server_address[:2]

    def serve_forever(self) -> None:  # pragma: no cover - a loop
        log.info("listening for HTTP on %s:%s", self.host, self.port)
        self.server.serve_forever()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Datagram(socketserver.BaseRequestHandler):
    ingest: Ingest
    driver: str

    def handle(self) -> None:
        peer = self.client_address[0] if self.client_address else ""
        if not self.ingest.access.allows(peer):
            self.ingest.refused_peers += 1
            return
        if not self.ingest.limits.allow(peer):
            return
        body = self.request[0]
        # A datagram has no path to carry a token, so the port itself is the
        # access control. Nothing is sent back: there is nobody listening.
        #
        # The driver is asked for rather than fixed. Naming it in the path --
        # which is what this did -- means `driver_for` matches the segment and
        # never reaches detection, and the configured name is `json`: a
        # WeatherFlow hub's broadcast went to the envelope parser, which reads
        # it as JSON and stores `serial_number`, `type` and `obs` as though
        # they were measurements. It is the only protocol here that
        # broadcasts, and it recognises its own datagram, so ask.
        name = self.ingest.registry.claimant(body, {"path": "/"}) or self.driver
        self.ingest.submit(body, f"/{name}/", self.client_address[0])


class UdpListener:
    """The UDP half, for hardware that broadcasts rather than posts."""

    def __init__(self, ingest: Ingest, host: str = "0.0.0.0", port: int = 8001,
                 driver: str = "json") -> None:
        handler = type("Datagram", (_Datagram,), {"ingest": ingest, "driver": driver})
        socketserver.UDPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingUDPServer((host, port), handler)
        self.server.max_packet_size = MAX_BODY
        self.host, self.port = self.server.server_address[:2]

    def serve_forever(self) -> None:  # pragma: no cover - a loop
        log.info("listening for UDP on %s:%s", self.host, self.port)
        self.server.serve_forever()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def push(packets: list[Packet], host: str = "127.0.0.1", port: int = 8000,
         token: str | None = None, timeout: float = 3.0,
         as_driver: str = "json") -> int:
    """Send packets to a listener. This is how a pull driver delivers.

    Going over the loopback rather than writing to the database directly is
    deliberate. It costs a millisecond and buys process isolation: a driver
    that wedges on a USB port, or crashes, takes nothing else with it -- and it
    does not have to be written in Python.

    `as_driver` is the endpoint, and it decides what the listener records
    these packets *as*. The default sends them in as envelopes, which is what
    an unnamed collector is. A configured one sends its own name, so that
    `stations.by_identity(driver, source)` has a driver to match on -- two
    collectors both arriving as `json` would be one driver with two
    identities, and a station announced for either would claim both.
    """
    import urllib.request

    endpoint = (as_driver or "json").strip("/") or "json"
    path = f"/{token}/{endpoint}/" if token else f"/{endpoint}/"
    # The identity, which is what the envelope's `source` means: how this
    # collector names itself, for `stations.by_identity` to match on. Falls
    # back to `source` for a caller holding a packet that has been through a
    # placer and carries the name somebody chose instead.
    body = json.dumps([{
        "dateTime": p.dateTime, "usUnits": p.usUnits,
        "source": p.identity or p.source,
        "kind": p.kind, "interval": p.interval, "data": p.data,
    } for p in packets]).encode()

    request = urllib.request.Request(
        f"http://{host}:{port}{path}", data=body,
        headers={"Content-Type": "application/json"})
    # The URL is built here out of a host and a port, three lines up.
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        response.read()
    return len(packets)


def resolve_bind(host: str) -> str:
    """Turn a bind address into something to print. Cosmetic only."""
    if host in ("", "0.0.0.0", "::"):
        return socket.gethostname()
    return host

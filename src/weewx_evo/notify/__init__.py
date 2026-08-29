"""Telling somebody when the station has stopped working.

The gap this fills is embarrassing when you look for it: **nothing in this
program tells anybody anything.** The watchdog restarts the process and says
so in a log. A console that stopped uploading at three in the morning shows
up as a flat line on a page nobody opens until the weekend. An FTP account
whose password changed fails every five minutes for a month.

With one station that is a nuisance. With ten it is the difference between
running an installation and hoping.

## Operations, not weather

Only what says *this program or its hardware has stopped working*:

    a station has gone quiet
    a battery is flat
    an export or an upload keeps failing
    the watchdog restarted the process, and why
    the archiver's loop has stopped going round

**Not** frost, not a gale, not a rainfall record. Two reasons, and the second
is the real one. A weather threshold is a matter of taste and belongs
somewhere it can be changed without a restart, which is what Grafana's
alerting is for. And an operational alert has to work when the *rest* of this
program does not -- so it is deliberately built out of the two things that
keep working when everything else has stopped: the live database and an
outbound connection.

## Flapping, and the two rules against it

A threshold at 0.0 with a temperature wandering across it is forty messages a
night, and forty messages a night is a filter rule. So:

**Nothing is reported until it has been true for a while.** `Rule.after` is a
duration, not a count of checks, because the checks run on a schedule nobody
should have to think about.

**Every alert has an end.** An operator who gets "the shed has gone quiet" at
04:00 and nothing afterwards cannot tell a fixed station from a broken alert.
`Event.over` is that message, and it is sent through the same channels.

Between the two, a symptom that comes and goes produces one message and one
all-clear, however often it flickers underneath.

## Where the state lives

In `live_metadata`, like `exports/record.py`, for the same reasons: the
settings page is another process, a restart must not forget what has already
been reported, and a program with a database in it does not need a second
place to keep four numbers.

**Not a history.** What is wrong now, and since when. The log has the rest.

## A channel is forty lines

    class MyChannel:
        def send(self, event: Event) -> None:
            ...

        @staticmethod
        def options():
            return [...]

Three are built in. `smtp` because everybody has an address, `webhook`
because one shape covers ntfy, Gotify, Slack, Discord, Telegram and whatever
comes next, and `mqtt` because the client is already here.

**Two channels, not one.** A message about the network, sent over the
network, is the alert most likely to be the one that does not arrive. The
settings page says so; it cannot enforce it.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "weewx_evo.notify"

#: Where the state is kept in the live database.
METADATA_KEY = "notify"

#: How long a symptom has to hold before anybody hears about it, unless the
#: rule says otherwise. Long enough that a console missing one upload is not
#: an event; short enough that a morning's readings are not lost first.
DEFAULT_AFTER = 1800

#: And how long before the same thing is said again. A daily reminder is a
#: reminder; an hourly one is a filter rule.
DEFAULT_REPEAT = 86400


@dataclass(frozen=True, slots=True)
class Event:
    """Something worth telling somebody about."""

    #: What kind of thing this is: `station_silent`, `battery`, `sending`,
    #: `restarted`, `heartbeat`. Stable, because it keys the state.
    kind: str
    #: Which station, export or upload. Empty where the whole process is
    #: meant.
    subject: str
    #: One line, written for somebody reading it on a phone.
    text: str
    #: When it started being true.
    since: float = 0.0
    #: Whether this is the all-clear rather than the alarm.
    over: bool = False
    severity: str = "warning"

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.subject}" if self.subject else self.kind

    def subject_line(self, station: str = "") -> str:
        where = f"{station}: " if station else ""
        if self.over:
            return f"{where}recovered -- {self.text}"
        return f"{where}{self.text}"

    def body(self, station: str = "") -> str:
        lines = [self.subject_line(station)]
        if self.since:
            lines.append(f"Since {time.strftime('%Y-%m-%d %H:%M', time.localtime(self.since))}.")
        if not self.over:
            lines.append("")
            lines.append("Sent by weewx-evo because it has stopped doing "
                         "something it was doing before.")
        return "\n".join(lines)


@runtime_checkable
class Channel(Protocol):
    """Somewhere a message goes."""

    def send(self, event: Event, station: str = "") -> None:
        ...


class BaseChannel:
    """Defaults for a channel. Only `send` has to be written."""

    label: str = "channel"
    summary: str = ""
    #: Whether this one needs the network to be working. Used by the page to
    #: say that two channels of the same kind are one channel.
    outbound: bool = True

    def send(self, event: Event, station: str = "") -> None:
        raise NotImplementedError

    def check(self) -> str:
        """Send a test message and say what happened."""
        try:
            self.send(Event(kind="test", subject="",
                            text="This is a test from weewx-evo.",
                            since=time.time(), severity="info"))
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        return "Sent. If nothing arrives, the address is wrong rather than the settings."

    def close(self) -> None:
        """Release anything held. Optional."""


class NotifyError(Exception):
    """A channel that could not deliver."""


# ---------------------------------------------------------------------------
# What has already been said.
# ---------------------------------------------------------------------------

@dataclass
class Standing:
    """One symptom that is currently true, and what has been sent about it."""

    since: float = 0.0
    #: When it was last reported. Zero means noticed but not yet reported --
    #: it has not been true for long enough.
    told: float = 0.0
    #: How the text read when it was last sent, so a changed figure does not
    #: count as a new alert.
    text: str = ""


class Memory:
    """What is wrong now, and since when, across restarts.

    In the live database, because the settings page is another process and a
    restart must not forget. `exports/record.py` keeps its state the same way
    and for the same reasons.
    """

    def __init__(self, live: Any = None) -> None:
        self.live = live
        self.standing: dict[str, Standing] = {}
        self._load()

    def _load(self) -> None:
        if self.live is None:
            return
        try:
            raw = self.live.get_meta(METADATA_KEY)
        except Exception:
            log.debug("could not read the notification state", exc_info=True)
            return
        if not raw:
            return
        try:
            found = json.loads(raw)
        except ValueError:
            log.warning("the notification state is not readable; starting over")
            return
        for key, entry in (found or {}).items():
            if isinstance(entry, dict):
                self.standing[key] = Standing(
                    since=float(entry.get("since") or 0),
                    told=float(entry.get("told") or 0),
                    text=str(entry.get("text") or ""))

    def save(self) -> None:
        if self.live is None:
            return
        payload = {key: {"since": one.since, "told": one.told, "text": one.text}
                   for key, one in self.standing.items()}
        try:
            self.live.set_meta(METADATA_KEY, json.dumps(payload))
        except Exception:
            # Worth carrying on for: an alert that went out and was not
            # written down is one repeated message, and an alert that never
            # went out because the note failed is silence.
            log.warning("could not write the notification state", exc_info=True)


# ---------------------------------------------------------------------------
# Deciding what to say.
# ---------------------------------------------------------------------------

@dataclass
class Timing:
    """How long a symptom holds before it is said, and how often after."""

    after: float = DEFAULT_AFTER
    repeat: float = DEFAULT_REPEAT


def decide(seen: dict[str, Event], memory: Memory, timing: Timing,
           now: float | None = None) -> list[Event]:
    """What to send, given what is wrong and what has already been said.

    The whole flapping question is in here, and it is two rules:

    A symptom is not reported until it has held for `after`. A console that
    misses one upload is not an event, and treating it as one is how somebody
    ends up filtering these messages into a folder they never open.

    Anything that was reported and has stopped gets an all-clear, at once.
    Waiting there would be the same mistake in the other direction: an
    operator who was told the shed went quiet and hears nothing afterwards
    cannot tell a fixed station from a broken alert.
    """
    now = time.time() if now is None else now
    out: list[Event] = []

    for key, event in sorted(seen.items()):
        standing = memory.standing.get(key)
        if standing is None:
            standing = memory.standing[key] = Standing(since=event.since or now)
        if not standing.since:
            standing.since = event.since or now

        held = now - standing.since
        if not standing.told:
            if held >= timing.after:
                standing.told = now
                standing.text = event.text
                out.append(event)
        elif now - standing.told >= timing.repeat:
            standing.told = now
            standing.text = event.text
            out.append(event)

    for key in sorted(set(memory.standing) - set(seen)):
        standing = memory.standing.pop(key)
        if standing.told:
            kind, _, subject = key.partition(":")
            out.append(Event(kind=kind, subject=subject,
                             text=standing.text or "back to normal",
                             since=standing.since, over=True, severity="info"))

    return out


# ---------------------------------------------------------------------------
# The registry.
# ---------------------------------------------------------------------------

class Registry:
    """The channels this installation has. Same shape as the others."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., object]] = {}
        self._loaded = False

    def register_factory(self, name: str, factory: Callable[..., object]) -> None:
        self._factories[name] = factory

    def factory_for(self, kind: str) -> Callable[..., object] | None:
        self.load()
        return self._factories.get(kind)

    def kinds(self) -> list[str]:
        self.load()
        return sorted(self._factories)

    def describe(self, kind: str) -> str:
        factory = self.factory_for(kind)
        return getattr(factory, "summary", "") if factory else ""

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        from importlib.metadata import entry_points

        for entry in entry_points(group=ENTRY_POINT_GROUP):
            try:
                self.register_factory(entry.name, entry.load())
                log.info("notification channel %r from %s", entry.name,
                         entry.value)
            except Exception:
                log.exception("could not load the channel %r; carrying on",
                              entry.name)

        from . import mqtt, smtp, webhook

        self.register_factory("email", smtp.EmailChannel)
        self.register_factory("webhook", webhook.WebhookChannel)
        self.register_factory("mqtt", mqtt.MqttChannel)


DEFAULT = Registry()


def kinds() -> list[str]:
    return DEFAULT.kinds()


def describe(kind: str) -> str:
    return DEFAULT.describe(kind)


def when_options() -> list:
    """The timing group, which every channel shares."""
    from ..options import Group, Option

    return [
        Group("When it speaks", "", (
            Option("after", "Wait this long before saying anything",
                   kind="duration", default=DEFAULT_AFTER, minimum=60,
                   maximum=86400,
                   help="A console that misses one upload is not an event. "
                        "Long enough that a hiccup is quiet, short enough "
                        "that a morning is not lost."),
            Option("repeat", "Say it again after", kind="duration",
                   default=DEFAULT_REPEAT, minimum=600, maximum=604800,
                   advanced=True,
                   help="For something that is still wrong. A daily reminder "
                        "is a reminder; an hourly one is a filter rule."),
        )),
    ]

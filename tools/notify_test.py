#!/usr/bin/env python3
"""Who hears about it when the station stops, and how often.

The thing worth testing here is not that a message can be sent. It is
**flapping**: a symptom that comes and goes must produce one message and one
all-clear, however often it flickers underneath. Forty messages a night is a
filter rule, and a filter rule is the same as having built none of this.

So the checks are about time:

    it holds for a while before anybody hears
    it is repeated, but on the scale of a day
    it ends, and the end is sent
    and a symptom that flickers under the threshold produces nothing

Three more that are about being useful when things are bad:

**One channel refusing must not stop the others.** The whole reason for
configuring two is that one of them may be the thing that has broken.

**A fresh process says nothing for a few minutes.** It has no heartbeat yet
and the runners have not had a turn, so every restart would otherwise
produce a burst of alarms that clear themselves a minute later.

**The state survives a restart.** It lives in the live database for exactly
that reason, and a restart is when a run of failures otherwise gets lost.

The SMTP and HTTP servers are real, on loopback. A stub that returns a number
is a restatement of the code under test; what is being checked is which
answers mean "stop" and which mean "Tuesday".

    python tools/notify_test.py
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import tempfile
import threading
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import notify, units
from weewx_evo.db.live import LiveStore, Packet
from weewx_evo.exports import record as export_record
from weewx_evo.notify import Event, Memory, Timing, decide
from weewx_evo.notify import rules as notify_rules
from weewx_evo.notify import runner as notify_runner

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


START = 1755648000


def an_event(text: str = "the shed has gone quiet", since: float = START) -> Event:
    return Event(kind="station_silent", subject="schuppen", text=text,
                 since=since)


# ---------------------------------------------------------------------------
# Flapping.
# ---------------------------------------------------------------------------

def test_nothing_is_said_until_it_has_held() -> None:
    """A console that misses one upload is not an event."""
    memory = Memory()
    timing = Timing(after=1800, repeat=86400)
    seen = {"station_silent:schuppen": an_event()}

    check("not at once", decide(seen, memory, timing, START + 60), [])
    check("not after ten minutes",
          decide(seen, memory, timing, START + 600), [])

    said = decide(seen, memory, timing, START + 1900)
    check("but once it has held", len(said), 1)
    check("and it is the symptom", said[0].kind, "station_silent")
    check("not the all-clear", said[0].over, False)


def test_it_is_not_repeated_until_the_day_is_out() -> None:
    memory = Memory()
    timing = Timing(after=1800, repeat=86400)
    seen = {"station_silent:schuppen": an_event()}

    decide(seen, memory, timing, START + 1900)
    check("not an hour later", decide(seen, memory, timing, START + 5500), [])
    check("nor twelve hours later",
          decide(seen, memory, timing, START + 43000), [])
    check("but once a day", len(decide(seen, memory, timing, START + 90000)), 1)


def test_an_alert_that_was_sent_gets_an_all_clear() -> None:
    """The message without which an operator cannot tell a fixed station
    from a broken alert."""
    memory = Memory()
    timing = Timing(after=1800, repeat=86400)
    seen = {"station_silent:schuppen": an_event()}
    decide(seen, memory, timing, START + 1900)

    said = decide({}, memory, timing, START + 3000)
    check("one message", len(said), 1)
    check("and it is the end of it", said[0].over, True)
    check("about the same thing", said[0].key, "station_silent:schuppen")
    check("and nothing is left standing", memory.standing, {})


def test_a_symptom_that_flickers_says_nothing() -> None:
    """On and off under the threshold is the case this is all for.

    Sending on each would be forty messages a night, and forty messages a
    night is a folder somebody never opens.
    """
    memory = Memory()
    timing = Timing(after=1800, repeat=86400)

    said = []
    for minute in range(0, 240, 10):
        now = START + minute * 60
        # True for ten minutes, false for ten, over and over -- and each
        # time it comes back it is freshly true, which is what the rules
        # produce: `stations_silent` dates the silence from the last packet,
        # so a station that reported in between starts the clock again.
        present = ({"station_silent:schuppen": an_event(since=now)}
                   if (minute // 10) % 2 == 0 else {})
        said += decide(present, memory, timing, now)
    check("nothing was ever said", said, [])

    # And the same symptom, once it stays, is said exactly once.
    steady = {"station_silent:schuppen": an_event(since=START + 240 * 60)}
    for minute in range(240, 300, 10):
        said += decide(steady, memory, timing, START + minute * 60)
    check("but a symptom that stays is", len(said), 1)


def test_an_all_clear_only_follows_an_alert() -> None:
    """A symptom noticed and gone before the threshold was never news."""
    memory = Memory()
    timing = Timing(after=1800, repeat=86400)
    decide({"station_silent:schuppen": an_event()}, memory, timing, START + 60)
    check("no all-clear for something never said",
          decide({}, memory, timing, START + 120), [])


def test_a_changed_figure_is_not_a_new_alert() -> None:
    """"Quiet for 40 minutes" becoming "quiet for 50" is the same fault."""
    memory = Memory()
    timing = Timing(after=1800, repeat=86400)
    decide({"station_silent:schuppen": an_event("quiet for 40 minutes")},
           memory, timing, START + 1900)
    said = decide({"station_silent:schuppen": an_event("quiet for 50 minutes")},
                  memory, timing, START + 2500)
    check("said once, not twice", said, [])


def test_the_state_survives_a_restart() -> None:
    """It lives in the live database for exactly this."""
    where = Path(tempfile.mkdtemp()) / "live.sdb"
    timing = Timing(after=1800, repeat=86400)
    seen = {"station_silent:schuppen": an_event()}

    with LiveStore(where) as live:
        memory = Memory(live)
        decide(seen, memory, timing, START + 1900)
        memory.save()

    with LiveStore(where) as live:
        again = Memory(live)
        check("it remembers what is standing",
              sorted(again.standing), ["station_silent:schuppen"])
        check("and that it was already told",
              again.standing["station_silent:schuppen"].told > 0, True)
        check("so it is not sent a second time",
              decide(seen, again, timing, START + 2500), [])


# ---------------------------------------------------------------------------
# The rules.
# ---------------------------------------------------------------------------

class Station:
    def __init__(self, name: str) -> None:
        self.name = name


class Stations:
    def __init__(self, *names: str) -> None:
        self._all = [Station(name) for name in names]

    def all(self) -> list:
        return self._all


def a_live_table(packets: list[tuple[str, float, dict]]) -> LiveStore:
    live = LiveStore(Path(tempfile.mkdtemp()) / "live.sdb")
    for source, when, data in packets:
        live.add(Packet(dateTime=int(when), usUnits=units.METRICWX,
                        data=data, source=source))
    return live


def test_a_station_that_stopped() -> None:
    now = START + 7200
    live = a_live_table(
        # One reporting until a moment ago, one that stopped an hour back.
        [("haus", now - 30 * i, {"outTemp": 20.0}) for i in range(20)]
        + [("schuppen", now - 3600 - 30 * i, {"outTemp": 19.0})
           for i in range(20)])
    try:
        found = notify_rules.stations_silent(
            live, Stations("haus", "schuppen"), now=now)
    finally:
        live.close()

    check("only the one that stopped", sorted(found), ["station_silent:schuppen"])
    check("and it says how long", "hour" in found["station_silent:schuppen"].text
          or "minutes" in found["station_silent:schuppen"].text, True)


def test_silence_is_measured_against_the_station_s_own_rhythm() -> None:
    """A console reporting every sixteen seconds and one reporting every
    five minutes cannot share a threshold."""
    now = START + 7200
    live = a_live_table([("fast", now - 16 * i, {"outTemp": 20.0})
                         for i in range(30)])
    try:
        check("measured, not assumed",
              round(notify_rules.rhythm(live, "fast", now)), 16)
        check("and a station nobody has heard from is not measured",
              notify_rules.rhythm(live, "nobody", now),
              notify_rules.DEFAULT_RHYTHM)
    finally:
        live.close()


def test_a_station_never_heard_from_is_not_silent() -> None:
    """That is an unconfigured station, and belongs on the settings page.

    Same rule as watchdog.py: a check that goes red because somebody else's
    equipment is off is a check people learn to ignore.
    """
    now = START + 7200
    live = a_live_table([("haus", now - 30, {"outTemp": 20.0})])
    try:
        found = notify_rules.stations_silent(
            live, Stations("haus", "never-seen"), now=now)
    finally:
        live.close()
    check("nothing about the one that has never spoken", found, {})


def test_a_flat_battery() -> None:
    now = START + 7200
    live = a_live_table([
        ("haus", now - 60, {"outTemp": 20.0, "txBatteryStatus": 0}),
        ("schuppen", now - 60, {"outTemp": 19.0, "txBatteryStatus": 1}),
    ])
    try:
        found = notify_rules.batteries_flat(live, Stations("haus", "schuppen"),
                                            now=now)
    finally:
        live.close()
    check("only the flat one", sorted(found), ["battery:schuppen"])
    check("and it names the field",
          "txBatteryStatus" in found["battery:schuppen"].text, True)


def test_one_failed_run_is_not_an_event() -> None:
    """A network has moments. Three in a row is a password somebody changed."""
    live = a_live_table([])
    try:
        export_record.write(live, "site", error="connection refused", when=START)
        check("not after one",
              notify_rules.sending_failing(live, ["site"], START + 60), {})

        export_record.write(live, "site", error="connection refused",
                            when=START + 300)
        export_record.write(live, "site", error="connection refused",
                            when=START + 600)
        found = notify_rules.sending_failing(live, ["site"], START + 700)
        check("but after three", sorted(found), ["sending:site"])
        check("and it dates the run of them",
              found["sending:site"].since, float(START))
        check("and says what the far end said",
              "connection refused" in found["sending:site"].text, True)
    finally:
        live.close()


def test_a_check_that_throws_does_not_take_the_others() -> None:
    """The one that still works is the one that says the station is dead."""

    class Broken:
        def all(self):
            raise RuntimeError("no stations file")

    live = a_live_table([])
    try:
        export_record.write(live, "site", error="refused", when=START)
        export_record.write(live, "site", error="refused", when=START + 300)
        export_record.write(live, "site", error="refused", when=START + 600)
        found = notify_rules.everything(live, Broken(), None, ["site"],
                                        now=START + 700)
    finally:
        live.close()
    check("the working check still reported", sorted(found), ["sending:site"])


# ---------------------------------------------------------------------------
# The channels.
# ---------------------------------------------------------------------------

class Post(http.server.BaseHTTPRequestHandler):
    status = 200
    seen: ClassVar[list] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        Post.seen.append((self.path, dict(self.headers), body))
        self.send_response(Post.status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: object) -> None:
        pass


def serving() -> tuple:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Post)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/topic"


def test_a_webhook_body_is_the_template() -> None:
    from weewx_evo.notify.webhook import WebhookChannel

    one = WebhookChannel(url="http://127.0.0.1:1/x",
                         content_type="application/json",
                         template='{"text": {subject}}')
    body = one.body_for(an_event(), station="Kirchdorf")
    import json as json_module

    parsed = json_module.loads(body)
    check("it is valid JSON", "text" in parsed, True)
    check("with the station and the symptom in it",
          parsed["text"], "Kirchdorf: the shed has gone quiet")


def test_a_quotation_mark_cannot_break_the_body() -> None:
    """A station called `Kirchdorf "old"` is a name somebody may type.

    Pasted into a JSON template it produces a document the far end rejects as
    malformed, which reads as the service being down -- on the day something
    has actually gone wrong.
    """
    import json as json_module

    from weewx_evo.notify.webhook import WebhookChannel

    one = WebhookChannel(url="http://127.0.0.1:1/x",
                         content_type="application/json",
                         template='{"text": {subject}}')
    body = one.body_for(an_event(text='the "shed" has gone quiet'))
    parsed = json_module.loads(body)
    check("the quotes survive as text",
          parsed["text"], 'the "shed" has gone quiet')


def test_a_plain_text_body_is_not_quoted() -> None:
    """ntfy prints the body. JSON quotes around it would be in the message."""
    from weewx_evo.notify.webhook import WebhookChannel

    one = WebhookChannel(url="http://127.0.0.1:1/x",
                         content_type="text/plain", template="{subject}")
    check("no quotes around it",
          one.body_for(an_event()).startswith('"'), False)


def test_a_webhook_posts_and_reports(url: str) -> None:
    from weewx_evo.notify import NotifyError
    from weewx_evo.notify.webhook import WebhookChannel

    Post.status, Post.seen = 200, []
    one = WebhookChannel(url=url, headers="Priority: high, Tags: warning")
    one.send(an_event(), station="Kirchdorf")
    check("it posted once", len(Post.seen), 1)
    path, headers, body = Post.seen[0]
    check("to the path", path, "/topic")
    check("with the extra headers", headers.get("Priority"), "high")
    check("and a value with a colon in it survives",
          headers.get("Tags"), "warning")
    check("the body is the message", "gone quiet" in body, True)

    Post.status = 400
    try:
        one.send(an_event())
    except NotifyError as exc:
        check("a refusal says what the far end answered", "400" in str(exc), True)
    else:
        check("a 400 is a refusal", False, True)


def test_an_unknown_placeholder_is_named(url: str) -> None:
    """A template with a typo must say which word, not fail at send time."""
    from weewx_evo.notify import NotifyError
    from weewx_evo.notify.webhook import WebhookChannel

    one = WebhookChannel(url=url, template="{nonesuch}")
    try:
        one.send(an_event())
    except NotifyError as exc:
        check("it names the word", "nonesuch" in str(exc), True)
        check("and lists the ones that exist", "subject" in str(exc), True)
    else:
        check("an unknown placeholder is refused", False, True)


class Smtp(socketserver.StreamRequestHandler):
    """Just enough SMTP to accept one message."""

    messages: ClassVar[list] = []
    refuse: str = ""

    def handle(self) -> None:
        self.wfile.write(b"220 test\r\n")
        body: list[str] = []
        reading = False
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if reading:
                if text == ".":
                    reading = False
                    Smtp.messages.append("\n".join(body))
                    self.wfile.write(b"250 ok\r\n")
                else:
                    body.append(text)
                continue
            head = text.split(" ", 1)[0].upper()
            if head in ("EHLO", "HELO"):
                self.wfile.write(b"250-test\r\n250 HELP\r\n")
            elif head == "MAIL" and Smtp.refuse == "sender":
                self.wfile.write(b"550 sender not allowed\r\n")
            elif head in ("MAIL", "RCPT"):
                self.wfile.write(b"250 ok\r\n")
            elif head == "DATA":
                reading = True
                self.wfile.write(b"354 go ahead\r\n")
            elif head == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


def smtp_serving() -> tuple:
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Smtp)
    server.allow_reuse_address = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_email_sends_and_threads(port: int) -> None:
    from weewx_evo.notify.smtp import EmailChannel

    Smtp.messages, Smtp.refuse = [], ""
    one = EmailChannel(host="127.0.0.1", port=port, security="none",
                       sender="station@example.com", to="me@example.com")
    one.send(an_event(), station="Kirchdorf")
    check("one message", len(Smtp.messages), 1)

    sent = Smtp.messages[0]
    check("the subject says what happened",
          "gone quiet" in sent and "Kirchdorf" in sent, True)
    # So a mail client threads the alarm and its all-clear together rather
    # than showing two unrelated messages a day apart.
    check("and it carries a reference for the symptom",
          "station_silent:schuppen@weewx-evo" in sent, True)

    one.send(Event(kind="station_silent", subject="schuppen",
                   text="the shed has gone quiet", since=START, over=True))
    check("the all-clear says so", "recovered" in Smtp.messages[1], True)


def test_a_refused_sender_is_named(port: int) -> None:
    """The commonest way this is set up wrong, and it only shows on a send.

    A provider that accepts the login and then refuses the envelope sender is
    ordinary, so `check` sends a real message rather than connecting.
    """
    from weewx_evo.notify import NotifyError
    from weewx_evo.notify.smtp import EmailChannel

    Smtp.messages, Smtp.refuse = [], "sender"
    one = EmailChannel(host="127.0.0.1", port=port, security="none",
                       sender="station@example.com", to="me@example.com")
    try:
        one.send(an_event())
    except NotifyError as exc:
        check("it says the sender was refused", "sender" in str(exc).lower(), True)
        check("and which one", "station@example.com" in str(exc), True)
    else:
        check("a refused sender raises", False, True)
    Smtp.refuse = ""


def test_a_channel_with_no_recipient_is_refused_at_setup() -> None:
    from weewx_evo.notify.smtp import EmailChannel

    for missing, why in (({"host": ""}, "no server"), ({"to": ""}, "nobody to tell")):
        settings = {"host": "smtp.example.com", "to": "me@example.com",
                    "sender": "s@example.com", **missing}
        try:
            EmailChannel(**settings)
        except ValueError:
            check(f"{why} is refused at setup", True, True)
        else:
            check(f"{why} is refused at setup", False, True)


# ---------------------------------------------------------------------------
# The runner.
# ---------------------------------------------------------------------------

class Records:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list = []
        self.fail = fail

    def send(self, event, station: str = "") -> None:
        if self.fail:
            raise RuntimeError("this channel is the broken one")
        self.sent.append(event)


def a_runner(live, channels, **kw):
    return notify_runner.Runner(
        [notify_runner.Channel(name=name, channel=one,
                               timing=Timing(after=0, repeat=86400))
         for name, one in channels],
        live=live, settle=0, **kw)


def test_one_channel_refusing_does_not_stop_the_others() -> None:
    """The whole reason for having two."""
    now = START + 7200
    live = a_live_table([("schuppen", now - 7000, {"outTemp": 19.0})
                         for _ in range(1)])
    broken, working = Records(fail=True), Records()
    try:
        runner = a_runner(live, [("broken", broken), ("working", working)],
                          stations=Stations("schuppen"))
        runner.once(now)
    finally:
        live.close()
    check("the working one was told", len(working.sent), 1)


def test_a_fresh_process_says_nothing_for_a_while() -> None:
    """Otherwise every restart is a burst of alarms that clear themselves."""
    now = START + 7200
    live = a_live_table([("schuppen", now - 7000, {"outTemp": 19.0})])
    told = Records()
    try:
        runner = notify_runner.Runner(
            [notify_runner.Channel(name="one", channel=told,
                                   timing=Timing(after=0, repeat=86400))],
            live=live, stations=Stations("schuppen"), settle=300)
        runner._started = now
        check("nothing while settling", runner.once(now + 60), [])
        check("and nothing was sent", told.sent, [])
        check("but it noticed", "station_silent:schuppen" in runner.standing,
              True)

        said = runner.once(now + 400)
        check("once settled, it speaks", len(said), 1)
        # Dated from when the station actually went quiet, not from the end
        # of the settling period.
        check("and dates it from the symptom",
              runner.memory.standing["station_silent:schuppen"].since < now,
              True)
    finally:
        live.close()


def test_the_shortest_wait_wins() -> None:
    """A channel set to speak up quickly does, and the other hears too."""
    runner = notify_runner.Runner([
        notify_runner.Channel("quick", Records(), Timing(after=60, repeat=3600)),
        notify_runner.Channel("slow", Records(), Timing(after=7200, repeat=86400)),
    ])
    timing = runner._timing()
    check("the shortest wait", timing.after, 60)
    check("and the longest repeat", timing.repeat, 86400)


def test_a_channel_kind_can_be_looked_up() -> None:
    check("three are built in", notify.kinds(), ["email", "mqtt", "webhook"])
    for kind in notify.kinds():
        check(f"{kind} says what it is", bool(notify.describe(kind)), True)
        factory = notify.DEFAULT.factory_for(kind)
        check(f"{kind} offers a form", bool(factory.options()), True)


def main() -> int:
    plain = [test_nothing_is_said_until_it_has_held,
             test_it_is_not_repeated_until_the_day_is_out,
             test_an_alert_that_was_sent_gets_an_all_clear,
             test_a_symptom_that_flickers_says_nothing,
             test_an_all_clear_only_follows_an_alert,
             test_a_changed_figure_is_not_a_new_alert,
             test_the_state_survives_a_restart,
             test_a_station_that_stopped,
             test_silence_is_measured_against_the_station_s_own_rhythm,
             test_a_station_never_heard_from_is_not_silent,
             test_a_flat_battery,
             test_one_failed_run_is_not_an_event,
             test_a_check_that_throws_does_not_take_the_others,
             test_a_webhook_body_is_the_template,
             test_a_quotation_mark_cannot_break_the_body,
             test_a_plain_text_body_is_not_quoted,
             test_a_channel_with_no_recipient_is_refused_at_setup,
             test_one_channel_refusing_does_not_stop_the_others,
             test_a_fresh_process_says_nothing_for_a_while,
             test_the_shortest_wait_wins,
             test_a_channel_kind_can_be_looked_up]
    for test in plain:
        try:
            test()
        except Exception as exc:  # a failing test is the finding
            FAILURES.append(f"{test.__name__} raised {type(exc).__name__}: {exc}")

    server, url = serving()
    try:
        for test in (test_a_webhook_posts_and_reports,
                     test_an_unknown_placeholder_is_named):
            try:
                test(url)
            except Exception as exc:
                FAILURES.append(
                    f"{test.__name__} raised {type(exc).__name__}: {exc}")
    finally:
        server.shutdown()
        server.server_close()

    mail, port = smtp_serving()
    try:
        for test in (test_email_sends_and_threads, test_a_refused_sender_is_named):
            try:
                test(port)
            except Exception as exc:
                FAILURES.append(
                    f"{test.__name__} raised {type(exc).__name__}: {exc}")
    finally:
        mail.shutdown()
        mail.server_close()

    if FAILURES:
        print(f"{len(FAILURES)} of {CHECKS} checks failed:\n")
        for failure in FAILURES:
            print(f"  {failure}\n")
        return 1
    print(f"notify: {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

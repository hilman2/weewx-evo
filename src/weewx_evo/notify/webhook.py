"""One POST, and therefore ntfy, Gotify, Slack, Discord, Telegram and Home
Assistant.

Every one of those takes an HTTP request with a message in it, and the only
thing they disagree about is the shape of the body. So there is one channel
with a template rather than six modules, each of which would be forty lines
of the same thing and one of which would be out of date.

    ntfy        https://ntfy.sh/my-station          text/plain, {text}
    Gotify      https://gotify…/message?token=…     JSON, {"message": …}
    Slack       an incoming-webhook URL             JSON, {"text": …}
    Discord     a webhook URL + /slack              JSON, {"content": …}
    Telegram    api.telegram.org/bot<token>/…       JSON, {"chat_id", "text"}

**The placeholders are filled in as JSON**, not pasted. A station called
`Kirchdorf "old"` or an error message containing a quotation mark would
otherwise produce a body the far end rejects as malformed -- which reads as
the service being down, on the day something has actually gone wrong.

**And the substitution is not `str.format`**, because JSON and `format` share
the braces: `{"text": "{subject}"}` makes `format` read `"text"` as a field
name and raise. See `_fill`.

**No list of presets here.** A table of six services in the code is a table
that is wrong within a year; the ones above are in the help text, where being
out of date costs nothing.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

# The same one every upload uses. `http.client` rather than `urllib.request`
# is the convention across this program, and one HTTP helper is better than a
# second implementation of the same four error cases.
from ..uploads import request as http_request
from . import BaseChannel, Event, NotifyError, when_options

log = logging.getLogger(__name__)

TIMEOUT = 20

#: Plain text, which is what ntfy and Gotify's simplest form take. Chosen as
#: the default because it is the one that works with no thinking at all.
DEFAULT_TEMPLATE = "{subject}"

#: Written out here rather than in the option, where the braces of the
#: examples and the braces of the placeholders sit in the same string literal
#: and are hard to read apart.
TEMPLATE_HELP = (
    "What to send. {subject} {text} {body} {station} {who} {kind} "
    "{severity} {state} are filled in. "
    'Slack: {"text": "{subject}"} — '
    'Discord: {"content": "{subject}"} — '
    'Gotify: {"message": "{body}", "title": "{subject}"}')


class WebhookChannel(BaseChannel):
    """Posts one request per event."""

    label = "Webhook"
    summary = ("One POST. Covers ntfy, Gotify, Slack, Discord, Telegram and "
               "anything else that takes a message over HTTP.")

    def __init__(self, url: str = "", method: str = "POST",
                 content_type: str = "text/plain",
                 template: str = DEFAULT_TEMPLATE, headers: str = "",
                 timeout: int = TIMEOUT,
                 after: int = 1800, repeat: int = 86400) -> None:
        self.url = str(url or "").strip()
        self.method = str(method or "POST").strip().upper()
        self.content_type = str(content_type or "text/plain").strip()
        self.template = str(template or DEFAULT_TEMPLATE)
        self.timeout = int(timeout)
        self.after = int(after)
        self.repeat = int(repeat)
        self.headers = _headers(headers)

        if not self.url:
            raise ValueError("the address to post to is needed")
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"{self.url!r} is not an http:// or https:// "
                             f"address")

    def body_for(self, event: Event, station: str = "") -> str:
        """The template with this event in it.

        Every value goes in as JSON, so a quotation mark in a station name
        cannot break the document. For a plain-text body the quotes JSON adds
        would be wrong, so they come off again -- the escaping is about what
        the string contains, not about how it is wrapped.
        """
        wrapped = self.content_type.startswith("application/json")

        def put(value: str) -> str:
            written = json.dumps(str(value))
            return written if wrapped else written[1:-1]

        fields = {
            "text": put(event.text),
            "subject": put(event.subject_line(station)),
            "body": put(event.body(station)),
            "kind": put(event.kind),
            "who": put(event.subject),
            "station": put(station),
            "severity": put("info" if event.over else event.severity),
            "state": put("over" if event.over else "active"),
        }
        return _fill(self.template, fields)

    def send(self, event: Event, station: str = "") -> None:
        body = self.body_for(event, station).encode("utf-8")
        parsed = urllib.parse.urlsplit(self.url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        try:
            status, text = http_request(
                parsed.hostname or "", path, method=self.method, body=body,
                headers={"Content-Type": self.content_type, **self.headers},
                tls=parsed.scheme == "https", port=parsed.port,
                timeout=self.timeout)
        except Exception as exc:
            raise NotifyError(
                f"could not reach {parsed.netloc}: {exc}") from exc

        if status >= 400:
            # The body is where these services say what was wrong with the
            # request, and often the only place. A 400 from Slack means the
            # template, not the network.
            raise NotifyError(f"{parsed.netloc} answered {status}: {text[:200]}")

    def status(self) -> dict:
        # The URL often carries the token, so only the host goes on a page.
        parsed = urllib.parse.urlsplit(self.url)
        return {"host": parsed.netloc, "type": self.content_type}

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("Where", "", (
                Option("url", "Address", kind="text", required=True,
                       placeholder="https://ntfy.sh/my-station",
                       help="For ntfy this is the topic address and nothing "
                            "else is needed. Slack, Discord and Gotify give "
                            "you a URL with a token in it."),
                Option("content_type", "Body type", kind="choice",
                       default="text/plain",
                       choices=(("text/plain", "Plain text (ntfy)"),
                                ("application/json",
                                 "JSON (Slack, Discord, Gotify, Telegram)")),
                       help="What the far end expects. Getting this wrong is "
                            "answered with 400 and a message in the body, "
                            "which `Try it` shows you."),
                Option("template", "Body", kind="text",
                       default=DEFAULT_TEMPLATE,
                       help=TEMPLATE_HELP),
                Option("headers", "Extra headers", kind="text", default="",
                       advanced=True,
                       placeholder="Authorization: Bearer …, Priority: high",
                       help="Name: value, separated by commas. ntfy takes "
                            "Priority and Tags here."),
            )),
            *when_options(),
            Group("How", "", (
                Option("method", "Method", kind="choice", default="POST",
                       choices=(("POST", "POST"), ("PUT", "PUT")),
                       advanced=True),
                Option("timeout", "Give up after", kind="duration",
                       default=TIMEOUT, minimum=5, maximum=120,
                       advanced=True),
            )),
        ]


#: A placeholder: a brace, a plain word, a brace. Nothing else is touched.
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _fill(template: str, fields: dict[str, str]) -> str:
    """Substitute the placeholders, leaving everything else alone.

    Not `str.format`, and this is the whole reason: **JSON and `format` share
    the braces.** A perfectly ordinary Slack template --

        {"text": "{subject}"}

    -- makes `format` read `"text"` as a placeholder and raise, and the
    operator who typed valid JSON gets a message about a field they never
    asked for. Doubling the braces would work and is a rule nobody should
    have to learn to send a webhook.

    So only `{word}` is a placeholder. `{"` is not one, `{}` is not one, and
    a `{word}` nothing knows is named in the error rather than silently left
    in the body -- a template with a typo in it should be fixed, not sent.
    """
    unknown = sorted({name for name in PLACEHOLDER.findall(template)
                      if name not in fields})
    if unknown:
        raise NotifyError(
            f"the template asks for {', '.join(unknown)}, which is not one "
            f"of: {', '.join(sorted(fields))}")
    return PLACEHOLDER.sub(lambda found: fields[found.group(1)], template)


def _headers(text: str) -> dict[str, str]:
    """`Name: value, Name: value` as a dictionary.

    Split on the *first* colon of each part, because a value is often a URL
    or a bearer token and both contain colons.
    """
    found: dict[str, str] = {}
    for part in str(text or "").split(","):
        name, sep, value = part.partition(":")
        if sep and name.strip():
            found[name.strip()] = value.strip()
    return found

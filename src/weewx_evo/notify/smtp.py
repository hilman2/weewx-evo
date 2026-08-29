"""Email, because everybody has an address.

`smtplib` and `email.message`, both in the standard library, so this costs
nothing to have. The whole file is about the four ways a mail server refuses
you and how to say which one it was.

**The trap this is written around:** a station's mail goes out through the
operator's own provider, and the four settings that decide whether it works
(port, TLS, authentication, the from address) are the four somebody guesses
wrong. So `check()` sends a real message rather than testing the connection.
A server that accepts a login and then refuses the envelope sender is
ordinary, and no amount of connecting finds it.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from . import BaseChannel, Event, NotifyError, when_options

log = logging.getLogger(__name__)

#: Long enough for a provider having a slow morning, short enough that the
#: notification thread is not the thing that hangs.
TIMEOUT = 30


class EmailChannel(BaseChannel):
    """Sends one message per event."""

    label = "Email"
    summary = ("A message to an address. Needs an SMTP server, which is "
               "usually the one that already sends this machine's mail.")

    def __init__(self, host: str = "", port: int = 0, security: str = "starttls",
                 username: str = "", password: str = "", sender: str = "",
                 to: str = "", timeout: int = TIMEOUT,
                 after: int = 1800, repeat: int = 86400) -> None:
        self.host = str(host or "").strip()
        self.security = str(security or "starttls").strip().lower()
        # The port follows the security setting rather than sitting under a
        # default of 25, which almost nothing accepts any more.
        self.port = int(port) or {"ssl": 465, "starttls": 587,
                                  "none": 25}.get(self.security, 587)
        self.username = str(username or "").strip()
        self.password = str(password or "")
        self.sender = str(sender or "").strip() or self.username
        self.to = [one.strip() for one in str(to or "").split(",") if one.strip()]
        self.timeout = int(timeout)
        self.after = int(after)
        self.repeat = int(repeat)

        if not self.host:
            raise ValueError("the address of an SMTP server is needed")
        if not self.to:
            raise ValueError("at least one address to send to is needed")
        if not self.sender:
            raise ValueError("a from address is needed; many servers refuse "
                             "a message without one they recognise")

    def send(self, event: Event, station: str = "") -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = ", ".join(self.to)
        message["Subject"] = event.subject_line(station)
        # So a mail client threads the alarm and its all-clear together
        # rather than showing two unrelated messages a day apart.
        message["References"] = f"<{event.key}@weewx-evo>"
        message.set_content(event.body(station))

        try:
            self._deliver(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise NotifyError(
                f"the server refused the username or password: {exc}") from exc
        except smtplib.SMTPSenderRefused as exc:
            raise NotifyError(
                f"the server refused {self.sender!r} as a sender. Many "
                f"providers only accept an address they host: {exc}") from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise NotifyError(
                f"the server refused the recipients: {exc}") from exc
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            raise NotifyError(
                f"could not send through {self.host}:{self.port}: "
                f"{type(exc).__name__}: {exc}") from exc

    def _deliver(self, message: EmailMessage) -> None:
        if self.security == "ssl":
            server: Any = smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout,
                context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        try:
            if self.security == "starttls":
                server.starttls(context=ssl.create_default_context())
                # After STARTTLS the session starts again, and a server that
                # advertised nothing before the handshake advertises
                # authentication after it.
                server.ehlo()
            if self.username:
                server.login(self.username, self.password)
            server.send_message(message)
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                # The message is already sent. A server that hangs up rudely
                # afterwards is not a failed delivery, and reporting it as
                # one would have somebody chasing a message that arrived.
                pass

    def status(self) -> dict:
        return {"host": self.host, "port": self.port,
                "security": self.security, "to": len(self.to)}

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("The server", "", (
                Option("host", "SMTP server", kind="text", required=True,
                       placeholder="smtp.example.com",
                       help="Usually the one your email provider gives you."),
                Option("security", "Security", kind="choice",
                       default="starttls",
                       choices=(("starttls", "STARTTLS (port 587)"),
                                ("ssl", "TLS (port 465)"),
                                ("none", "None (port 25)")),
                       help="STARTTLS is what almost every provider wants. "
                            "The port follows this unless you set one."),
                Option("port", "Port", kind="int", default=0, minimum=0,
                       maximum=65535, advanced=True,
                       help="Zero means the usual one for the security "
                            "setting above."),
                Option("username", "Username", kind="text", default="",
                       help="Leave empty for a server that does not ask."),
                Option("password", "Password", kind="secret", default=""),
            )),
            Group("The message", "", (
                Option("sender", "From", kind="text", default="",
                       placeholder="station@example.com",
                       help="Empty means the username. Many providers refuse "
                            "a from address they do not host, and say so "
                            "only when a message is actually sent."),
                Option("to", "To", kind="text", required=True,
                       placeholder="me@example.com, phone@example.com",
                       help="One address or several, separated by commas."),
            )),
            *when_options(),
            Group("How", "", (
                Option("timeout", "Give up after", kind="duration",
                       default=TIMEOUT, minimum=5, maximum=300, advanced=True),
            )),
        ]

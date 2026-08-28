"""Pushing the current readings to the web host the pages are on.

The problem: a skin published over FTP shows readings as old as the last
upload. Making them live the usual way means an MQTT broker at the station, a
port forwarded through the router, and a certificate -- because a page served
over https cannot open an unencrypted websocket. Three things to get right on
somebody else's network, and the third needs a domain that resolves to a home
connection.

This is one thing. The skin ships a `live.php`; this posts the current
readings to it every few seconds, and it writes them to a file beside itself.
The page then reads that file, which is static and served like any other.

**Every web host runs PHP.** That is the observation the whole approach rests
on: shared hosting where FTP is the only way in still runs PHP, and has for
twenty years.

Three things this buys over a broker:

  * **Nothing is opened.** No port forwarded, no broker reachable, no
    certificate to keep valid. The connection is outbound, like the FTP
    upload that put the page there.
  * **It works from anywhere.** Behind CGNAT, on a mobile connection, on a
    network somebody else administers.
  * **PHP runs when the station writes, not when somebody reads.** Six times
    a minute rather than once per visitor. A hundred people watching a storm
    cost nothing.

What it is not is push all the way to the browser. The page polls the file,
so the readings are as fresh as the interval here -- ten seconds by default,
which is thirty times better than an archive record and not the sub-second
that MQTT gives. For Home Assistant and a dashboard on the local network,
MQTT is still the better answer. The two are not alternatives.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from .. import units
from ..exports.livepush import DATA_FILE, STALE_AFTER
from . import BaseUpload, Posted, Rejected, request, when_options
from .mqtt import NEVER, topic_name

log = logging.getLogger(__name__)


#: How long `live.php` may keep answering 404 before it is taken to mean a
#: wrong token rather than an export that has not run yet.
NOT_YET = 3600.0


class WebPushUpload(BaseUpload):
    """Posts the current readings to a `live.php` on the web host."""

    label = "Push to the website"
    summary = ("The readings straight into the published pages, over the "
               "same connection that uploads them. No broker, no open port.")
    #: What arrives is "now". An older reading posted here would be published
    #: as the current conditions.
    backfill = False

    #: Filled in from an export that carries `live.php`, when this upload
    #: was not given its own. See `from_exports`.
    inferred = False

    def __init__(self, url: str = "", token: str = "",
                 directories: list | str | None = None,
                 unit_system: str = "", append_units: bool = True,
                 trigger: str = "live", every: int = 10,
                 catch_up: int = 0, timeout: int = 20,
                 _inferred: bool = False) -> None:
        self.inferred = bool(_inferred)
        # Directories to write the same document into, for sites this machine
        # serves itself. No PHP and no request: the web server hands out
        # `live.json` like any other file, and the page reads it exactly as it
        # would on a web host. The skin cannot tell the two apart.
        #
        # Several, because a station can serve several sites and the file is a
        # kilobyte. Choosing one of them to be live and leaving the rest stale
        # is not a reading of this setting anybody meant.
        if isinstance(directories, str):
            directories = [directories]
        self.directories = [str(one).strip() for one in (directories or [])
                            if str(one).strip()]
        self.url = str(url or "").strip()
        self.token = str(token or "")
        # The same names the MQTT path uses -- `outTemp_C`, `windSpeed_mph`.
        # A skin that can read one can read the other, and a station that
        # switches between them does not have to change its templates.
        self.unit_system = units.system_from(unit_system) if unit_system else None
        self.append_units = bool(append_units)
        self.trigger = trigger
        self.every = int(every)
        self.catch_up_limit = 0
        self.timeout = int(timeout)
        if not self.url and not self.directories:
            raise ValueError(
                "either a directory to write into, or the address of a "
                "live.php on a web host. An export supplies both: a local one "
                "gives its directory, and one that publishes to a web host "
                "gives the address in 'Address the pages are served at'.")

        self.host = self.path = ""
        self.tls = True
        if self.url:
            if not self.token:
                raise ValueError(
                    "a token is needed to post to a web host. Without one "
                    "anybody who finds the address can write what the page "
                    "shows as the weather. An export that carries live.php "
                    "derives one and sends it up with the files.")
            parts = urlsplit(self.url)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ValueError(f"{self.url!r} is not an http or https "
                                 f"address")
            self.host = parts.netloc
            self.path = parts.path or "/live.php"
            self.tls = parts.scheme == "https"
            if parts.query:
                self.path += "?" + parts.query

    # -- shaping ---------------------------------------------------------

    def document(self, record: dict) -> dict[str, object]:
        """The record as the names and values that go into the file.

        Deliberately the same shape as the MQTT JSON document: a skin that
        reads `weather/loop` reads this, and switching a station from one to
        the other changes no template.
        """
        stored = units.system_from(record.get("usUnits"), default=units.US)
        wanted = self.unit_system or stored
        shaped: dict[str, object] = {}
        for obs, value in record.items():
            if obs in NEVER or value is None:
                continue
            if obs == "dateTime":
                shaped["dateTime"] = int(value)
                continue
            unit, _group = units.unit_of(obs, stored)
            target, _ = units.unit_of(obs, wanted)
            if unit and target and unit != target:
                converted = units.convert(value, unit, target)
                if converted is None:
                    continue
                value = float(converted)
            shaped[topic_name(obs, target or unit, self.append_units)] = value
        return shaped

    # -- sending ---------------------------------------------------------

    def _send(self, record: dict) -> int:
        body = json.dumps(self.document(record),
                          separators=(",", ":")).encode("utf-8")
        status, text = request(
            self.host, self.path, method="POST", body=body,
            headers={
                "Content-Type": "application/json",
                # The token in a header rather than the address: an address
                # ends up in a proxy log and in a browser's history, and this
                # one is written down in the skin's own settings anyway.
                "X-WeeWX-Token": self.token,
                "Content-Length": str(len(body)),
            },
            tls=self.tls, timeout=self.timeout)

        if status == 404:
            # What `live.php` answers to a wrong token, on purpose: saying
            # "wrong token" would confirm there is a right one. So this
            # cannot tell the two apart, and says both.
            # Not believed straight away. `live.php` is carried up by an
            # export, so the answer before that export has run once is a 404
            # that means "not yet" -- and switching off there told somebody
            # to fix settings that were right, fifteen seconds before the
            # file appeared. A wrong token answers 404 for ever, so an hour
            # tells the two apart: longer than any export interval, shorter
            # than leaving it broken.
            raise Rejected(
                f"{self.host}{self.path} answered 404. Either live.php is "
                f"not there, or the token does not match the one in "
                f"live.token beside it.", permanent=True, after=NOT_YET)
        if status == 503:
            raise Rejected(f"{self.host}: {text[:160]}", permanent=True)
        if status == 405:
            raise Rejected(f"{self.host}{self.path} is not a live.php.",
                           permanent=True)
        if status != 200:
            raise Rejected(f"{self.host} answered {status}: {text[:120]}")
        return len(body)

    def _body(self, record: dict) -> str:
        """The document as it goes into the file, both ways round.

        The two fields `live.php` adds are added here too, so a page cannot
        tell the routes apart and needs no second way of reading this one.
        """
        import time

        document = self.document(record)
        document["_received"] = int(time.time())
        document["_stale_after"] = STALE_AFTER
        return json.dumps(document, separators=(",", ":"))

    def _write(self, record: dict) -> list[str]:
        """The same document, into each directory this machine serves.

        Written beside and renamed: half a JSON document is a parse error in
        every browser, and a page that blanks once in a while is the sort of
        fault nobody can reproduce.

        One directory failing does not stop the others. A skin on a full disk
        must not take the live readings off the site next to it.
        """
        body = self._body(record)
        failures = []
        for one in self.directories:
            try:
                where = Path(one)
                where.mkdir(parents=True, exist_ok=True)
                target = where / DATA_FILE
                partial = target.with_suffix(".json.part")
                partial.write_text(body, encoding="utf-8", newline="\n")
                partial.replace(target)
            except OSError as exc:
                failures.append(f"could not write into {one}: {exc}")
        return failures

    def post(self, records: list[dict]) -> Posted:
        result = Posted()
        record = records[-1]
        result.skipped = len(records) - 1

        if self.directories:
            trouble = self._write(record)
            for why in trouble:
                result.failures.append((str(record.get("dateTime")), why))
            if len(trouble) < len(self.directories):
                result.sent = 1

        if self.url:
            try:
                self._send(record)
                result.sent = 1
            except Rejected as exc:
                if exc.permanent:
                    raise
                result.failures.append((str(record.get("dateTime")), str(exc)))
                return result

        if result.sent:
            result.through = int(record.get("dateTime") or 0)
        return result

    def check(self) -> str:
        import time

        sample = {"dateTime": int(time.time()), "usUnits": units.METRICWX,
                  "outTemp": 0.0}
        said = []

        if self.directories:
            trouble = self._write(sample)
            written = len(self.directories) - len(trouble)
            if written:
                said.append(f"wrote {DATA_FILE} into "
                            + ", ".join(self.directories[:4])
                            + (" and more" if len(self.directories) > 4 else ""))
            said.extend(trouble)

        if self.url:
            try:
                self._send(sample)
                where = self.path.rsplit("/", 1)[0] or ""
                said.append(f"{self.host}{self.path} accepted a reading; the "
                            f"page reads it back from {where}/{DATA_FILE}")
            except Rejected as exc:
                said.append(f"refused: {exc}")
            except Exception as exc:
                said.append(f"could not reach {self.host}: {exc}")

        return ". ".join(said) if said else "nothing is configured to send to."

    def status(self) -> dict:
        return {"host": self.host, "path": self.path,
                "directories": self.directories}

    @staticmethod
    def from_exports(settings: object) -> tuple[str, str, list[str]]:
        """Where to send, from the exports that asked for live readings.

        Three things come back: the address of a `live.php` on a web host, the
        token for it, and every directory on this machine to write into. An
        export that publishes the pages already knows all of it -- where they
        end up, what token it writes beside the script, which directory the
        built-in server hands out. Asking again here is how the two drift
        apart, and the way they drift is a token that does not match: a page
        that renders perfectly and never updates.

        Every local directory, but only the first web address. Writing a
        kilobyte into five directories on this disk is free, and picking one
        of five locally served sites to be live is not something anybody
        meant. Posting to a second web host is a second connection over
        somebody else's network, and that is a decision -- so it wants a
        second upload with its own `url`.
        """
        from ..exports.livepush import token_for, url_for

        section = getattr(settings, "config", {}).get("exports") or {}
        token = token_for(str(settings.get("token") or ""))
        url = ""
        directories: list[str] = []
        for _name, configured in sorted(section.items()):
            if not isinstance(configured, dict):
                continue
            if not configured.get("live_push", True):
                continue
            if configured.get("kind") == "local":
                # No script and no address: the file goes straight into the
                # directory the web server is already handing out.
                where = str(configured.get("directory") or "").strip()
                if where and where not in directories:
                    directories.append(where)
                continue
            address = str(configured.get("live_push_url") or "").strip()
            if address and not url:
                url = url_for(address)
        return url, token, directories

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("Where the pages are",
                  "The address and the token fill in by themselves from an "
                  "export that carries `live.php` -- so in the ordinary case "
                  "there is nothing to type here at all. Set them only to "
                  "post somewhere no export of this station publishes to. "
                  "The directory is for a site this machine serves itself, "
                  "where there is no PHP to post to.", (
                      Option("url", "Address of live.php",
                             placeholder="https://example.org/wetter/live.php",
                             help="Empty means: from the export. The address "
                                  "there plus /live.php."),
                      Option("directories", "Or directories on this machine",
                             kind="list",
                             placeholder="data/site",
                             help="For sites this machine serves itself, one "
                                  "per line. No PHP and no request -- the "
                                  "file is written straight into the "
                                  "published directory and the web server "
                                  "hands it out like any other. A page cannot "
                                  "tell the two apart, so a skin needs no "
                                  "change. Empty means: every local export "
                                  "that has live readings switched on. Both "
                                  "this and the address may be set; the same "
                                  "readings go to each."),
                      Option("token", "Token", kind="secret",
                             help="Empty means: derived from the station's "
                                  "upload token, the same way the export "
                                  "derives the one it writes into "
                                  "`live.token` beside the script. Setting "
                                  "one here means setting the same one in "
                                  "that file by hand."),
                  )),
            Group("What is sent", "", (
                Option("unit_system", "Send in", kind="choice", default="",
                       choices=(("", "whatever the station reports"),
                                ("US", "US -- °F, inHg, mph, in"),
                                ("METRIC", "Metric -- °C, mbar, km/h, cm"),
                                ("METRICWX", "Metric WX -- °C, mbar, m/s, mm")),
                       help="The names carry the unit, so changing this "
                            "renames them: a page reading outTemp_C stops "
                            "finding anything when it becomes outTemp_F."),
                Option("append_units", "Put the unit in the name",
                       kind="bool", default=True, advanced=True,
                       help="On. `outTemp_C` rather than `outTemp` -- the "
                            "same names the MQTT path uses, so a skin that "
                            "reads one reads the other."),
            )),
            # Ten seconds by default rather than the record: an HTTP POST is
            # about a tenth of a second, so this is cheap in a way an FTP
            # upload would not be.
            *when_options(trigger="live", every=10, live=True),
            Group("How", "", (
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True),
            )),
        ]

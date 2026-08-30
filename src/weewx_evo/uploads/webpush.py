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

**One document, however many places the site stands in.** `live.php` takes no
filename from the request by design, and one derived token per station means
two documents on one host could not be told apart -- so a site showing several
measurement series carries them all in one file: the home series at the top
level, exactly where it always was, and the rest nested under `archives` with
each slice declaring its own units, timestamp and name. `carry` is how they
get here; `_document` is the shape.

What it is not is push all the way to the browser. The page polls the file,
so the readings are as fresh as the interval here -- ten seconds by default,
which is thirty times better than an archive record and not the sub-second
that MQTT gives. For Home Assistant and a dashboard on the local network,
MQTT is still the better answer. The two are not alternatives.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .. import units
from ..exports.livepush import BUDGET, DATA_FILE, STALE_AFTER
from . import BaseUpload, Posted, Rejected, request, when_options
from .mqtt import NEVER, topic_name

log = logging.getLogger(__name__)


#: How long `live.php` may keep answering 404 before it is taken to mean a
#: wrong token rather than an export that has not run yet.
NOT_YET = 3600.0


@dataclass(frozen=True, slots=True)
class Place:
    """One measurement series this document carries, and how to read it.

    Callables, not readers. This module has no business holding a database
    handle -- the same rule `uploads.runner.Scheduled` states about
    `records` -- and it is what lets a test hand this a lambda returning a
    dict rather than a live table.

    Built where the live table already is (`cli.with_station`), and handed
    over with `WebPushUpload.carry`.
    """

    name: str
    label: str
    #: This place's newest live packet, or None. Called once per document,
    #: so the slices are read microseconds apart -- which is exactly why
    #: each one carries its own `dateTime` and why nothing about a place may
    #: be inferred from the document's.
    packet: Callable[[], dict | None]
    code: str = ""
    #: How often this place actually reports, in seconds, or None where it
    #: cannot be measured. Not a setting, and not a second measurement:
    #: `notify.rules.measured_rhythm` is the one implementation of this in
    #: the tree, and what a caller binds here has to be that function. Two
    #: medians over the same packets are two numbers disagreeing about one
    #: console, and the one that is wrong is whichever the reader is looking
    #: at. `_rhythm_of` refuses that function's un-measured answer rather
    #: than publish a fixed figure as if it had been measured.
    rhythm: Callable[[], float | None] | None = None


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

    #: The measurement series this one document carries, in the order the
    #: pages present them. Attached after construction with `carry` and
    #: never through `settings`: `Schema.parse` keeps only what `options()`
    #: declares, which is why `inferred` above has never once been True in a
    #: running service. Empty on every single-place station, which is what
    #: keeps the document byte for byte what it was.
    carries_places: tuple[Place, ...] = ()

    def __init__(self, url: str = "", token: str = "",
                 directories: list | str | None = None,
                 unit_system: str = "", append_units: bool = True,
                 trigger: str = "live", every: int = 10,
                 catch_up: int = 0, timeout: int = 20,
                 _inferred: bool = False) -> None:
        self.inferred = bool(_inferred)
        #: The places the size limit last pushed out, so the warning is said
        #: once per change rather than six times a minute.
        self._left_out: list[str] = []
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

    def _systems(self, record: dict) -> tuple[int, int]:
        """What this record is in, and what it will be written in.

        One expression rather than two, because `_slice` *declares* the
        system `document()` converted to. Recomputed there they can drift,
        and the drift is a page told it is reading Celsius while the numbers
        are Fahrenheit -- which is the one fault `unit_system` exists to
        make detectable.
        """
        stored = units.system_from(record.get("usUnits"), default=units.US)
        return stored, (self.unit_system or stored)

    def document(self, record: dict) -> dict[str, object]:
        """The record as the names and values that go into the file.

        Deliberately the same shape as the MQTT JSON document: a skin that
        reads `weather/loop` reads this, and switching a station from one to
        the other changes no template.
        """
        stored, wanted = self._systems(record)
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

    def carry(self, places: Sequence[Place]) -> None:
        """The other series this one document is to carry.

        A method rather than a constructor argument, because anything that
        is not a declared `Option` is dropped on the way in: `build_upload`
        runs the settings through `Schema.parse`, which keeps only what
        `options()` names. `_inferred` is the proof -- it has a constructor
        argument, and it has never once arrived.

        One fact in one place: no separate boolean saying whether there are
        any. A boolean and a tuple are two things that can disagree, and the
        disagreement would be an `archives` key holding nothing.

        Two things are settled here rather than at the writing end, because
        this is where the list -- and its length -- is known.
        """
        # A name that is nothing but digits is refused before it can be
        # written. `live.php` decodes the body into PHP, which has one array
        # type: `{"archives":{"0":{...}}}` comes back out as
        # `{"archives":[{...}]}` and then *every* place's lookup on the page
        # finds nothing, not just that one's. `archives.why_not` refuses such
        # a name on the settings page; `_read` does not, so a hand-edited
        # `archives.toml` still reaches here. One place left out beats every
        # place's live values going dead.
        refused = [one.name for one in places if one.name.isdigit()]
        if refused:
            log.warning(
                "%s cannot be carried in the live document: a place whose "
                "name is only digits becomes a numeric key, which the web "
                "host rewrites as a position. Rename it on the archives "
                "page.", ", ".join(refused))
        kept = [one for one in places if not one.name.isdigit()]
        # Fewer than two places is a single-place site, and a single-place
        # site's document has to stay byte for byte what it was: an
        # `archives` key holding one slice that repeats the top level is
        # exactly the change that rule forbids. The gate is here and not in
        # `_document` so that `check()` and `status()` say the same thing.
        self.carries_places = tuple(kept) if len(kept) > 1 else ()

    def _slice(self, place: Place, record: dict) -> dict[str, object]:
        """One place's readings, plus the three things naming them costs.

        Through the same `document()` as the top level, deliberately: a
        second shaping path is a second set of names, and the names are the
        whole contract between this and the cards on the page.
        """
        shaped = self.document(record)
        # Which units the numbers in THIS slice are in, by name. The key
        # suffix carries it too (`outTemp_C`), but only while `append_units`
        # is on -- so it is not something a page may rely on, and this is
        # the field that lets one notice it is about to print 68.2 under a
        # heading that says Celsius. That failure has shipped once, and no
        # page could then detect it.
        #
        # Per slice and not per document because with no `Send in` set each
        # place declares whatever its own console reports, and one console
        # replaced while the other was not is the ordinary case here -- a
        # single declaration would then be right about one of them. With
        # `Send in` set every slice says the same thing, which costs a few
        # bytes and keeps one rule for reading this.
        #
        # Lower case: `deck/tags.py:page_unit_system` writes `data-units`
        # lower and `live-poll.js:unitsAgree` compares the two as strings.
        # Upper case here made every slice look like a unit mismatch, so no
        # value was written and every badge went red on a healthy site.
        # `unitsAgree` now folds the case as well -- an agreement that holds
        # only because both ends happen to spell it the same way breaks the
        # next time either end is touched.
        shaped["unit_system"] = units.name(self._systems(record)[1]).lower()
        # Travelling with the slice, so a page rendered before somebody
        # renamed a place can still name it.
        shaped["label"] = place.label
        if place.code:
            shaped["code"] = place.code
        every = self._rhythm_of(place)
        if every:
            # How often this place reports. Underscore-prefixed like
            # `_received`: it is a fact about the transport rather than a
            # reading, and the page matches cards on a name prefix -- a bare
            # `every` would be found by a card for a column called `every`,
            # which is a column somebody's driver is allowed to have.
            shaped["_every"] = int(every)
        return shaped

    def _document(self, record: dict, *,
                  places: bool = True) -> dict[str, object]:
        """The whole document: the top level, then the places under it.

        The top level is this upload's own series, shaped exactly as it was
        before there were any others. A page published last year, a skin
        from outside and `tools/deck_live_test.py` all keep working with no
        branch in any of them.

        That is also why the duplication below is worth its bytes -- this
        series appears at the top *and* as a slice. A board row for the home
        place carries `data-archive` like every other row, and a reader that
        fell back to the top level for a named place would publish one
        place's readings under another's heading the first time a slice was
        missing: wrong, and it looks live.
        """
        document = self.document(record)
        if not places or not self.carries_places:
            # No key at all, not an empty one. Two reasons, both
            # load-bearing: the single-place document stays byte for byte
            # what it was, and PHP has one array type, so `{}` would come
            # back out of `live.php` as `[]` and a page indexing it would
            # find nothing where it expected a slice.
            return document

        archives: dict[str, object] = {}
        # Measured as it is built, rather than assumed. `live.php` refuses a
        # body over MAX_BODY with a 413, and a 413 six times a minute reads
        # as "the upload is broken" -- so the writer stays under the limit
        # instead of discovering it. Never a truncated slice and never a
        # truncated document: half a JSON document is a parse error in every
        # browser, and that is the fault nobody can reproduce.
        #
        # The 14 is `,"archives":{}`, the wrapper the slices go into. Each
        # slice is then costed as `{"name":{...}}`, whose two braces pay for
        # the comma that will separate it from the next one.
        room = BUDGET - len(json.dumps(document, separators=(",", ":"))) - 14
        left_out: list[str] = []
        for place in self.carries_places:
            packet = self._packet_of(place)
            if not packet:
                # A place that has never reported, or one whose consoles are
                # not announced yet. No slice at all: the page then leaves
                # that row alone, which is what a place added five minutes
                # ago should look like. An empty slice would be `[]` after
                # `live.php`, and a green badge over nothing.
                continue
            one = self._slice(place, packet)
            cost = len(json.dumps({place.name: one}, separators=(",", ":")))
            if cost > room:
                left_out.append(place.name)
                continue
            archives[place.name] = one
            room -= cost
        if archives:
            document["archives"] = archives
        if left_out != self._left_out:
            self._left_out = left_out
            if left_out:
                # Said once per change and not once per push: six times a
                # minute for ever is a log nobody reads, which costs the
                # lines that do matter. And the first few by name, not all
                # of them -- seventy names on one line is the same problem
                # in a different shape.
                named = ", ".join(left_out[:6])
                if len(left_out) > 6:
                    named += f", and {len(left_out) - 6} more"
                log.warning(
                    "the live document is at its size limit; %s left out of "
                    "it. Show fewer places on this site, or split it in two.",
                    named)
        return document

    def _packet_of(self, place: Place) -> dict | None:
        """That place's newest reading, or None if it cannot be had.

        Wrapped, because the callable reaches a database. One place's table
        being locked must not take the whole document down: the document is
        keyed on the top-level place's clock, so a failure here would freeze
        every other place's slice as well -- which is precisely the reading
        the per-slice timestamp exists to prevent.
        """
        try:
            return place.packet()
        except Exception:
            # Not `log.exception`: the traceback is the same one every ten
            # seconds. The name is what somebody acts on.
            log.warning("could not read the live readings for %r; its "
                        "slice is left out of this document", place.name)
            return None

    def _rhythm_of(self, place: Place) -> float | None:
        """How often that place reports, or None if nobody can say.

        Guarded for the same reason as the packet, and separately from it:
        a cadence that cannot be measured is a page falling back to the one
        fixed freshness window, which is what every site had before this.
        Losing the readings over it would be the worse trade by far.

        There is one measurement of this in the tree,
        `notify.rules.measured_rhythm`, and the callable a caller binds has
        to end in it -- a second median over the same packets is two numbers
        disagreeing about one console, and the disagreement is between a
        badge on a page and a message in somebody's inbox.

        `None` is the only "cannot say", and that is why this no longer
        refuses `DEFAULT_RHYTHM`. It did, on the reasoning that a fixed 300
        published as a measurement is indistinguishable from a real one --
        true of the old function, which answered 300 where it could not
        measure. It is also the commonest real answer there is: a console
        reporting every five minutes measures exactly 300.0, and refusing it
        threw away the cadence of most of the stations this exists for.
        """
        if not place.rhythm:
            return None
        try:
            measured = place.rhythm()
        except Exception:
            log.warning("could not measure how often %r reports; its slice "
                        "goes without a cadence", place.name)
            return None
        return None if measured is None else float(measured)

    # -- sending ---------------------------------------------------------

    def _send(self, document: dict[str, object]) -> int:
        body = json.dumps(document, separators=(",", ":")).encode("utf-8")
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

    def _body(self, document: dict[str, object]) -> str:
        """The document as it goes into the file, both ways round.

        The two fields `live.php` adds are added here too, so a page cannot
        tell the routes apart and needs no second way of reading this one.

        The document is built once per push by the caller and handed to both
        routes, so they carry the same places read at the same moment. Two
        builds is two reads of every place's live table, and a `dateTime`
        that differs between the file this machine serves and the file on the
        web host is precisely the difference this method exists to deny.

        Stamped on a copy: `live.php` writes its own `_received` from the
        host's clock, and stamping the shared object would post this
        machine's clock as the host's.
        """
        import time

        stamped = dict(document)
        stamped["_received"] = int(time.time())
        stamped["_stale_after"] = STALE_AFTER
        return json.dumps(stamped, separators=(",", ":"))

    def _write(self, document: dict[str, object]) -> list[str]:
        """The same document, into each directory this machine serves.

        Written beside and renamed: half a JSON document is a parse error in
        every browser, and a page that blanks once in a while is the sort of
        fault nobody can reproduce.

        One directory failing does not stop the others. A skin on a full disk
        must not take the live readings off the site next to it.
        """
        body = self._body(document)
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

        # Built once and handed to both routes. Every place's slice reaches a
        # live table, so building it per route read each of them twice a push
        # -- and, worse, the file this machine serves and the one on the web
        # host would then hold packets read at two different moments, which
        # is the one difference between the routes a page must never see.
        document = self._document(record)

        if self.directories:
            trouble = self._write(document)
            for why in trouble:
                result.failures.append((str(record.get("dateTime")), why))
            if len(trouble) < len(self.directories):
                result.sent = 1

        if self.url:
            try:
                self._send(document)
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
        # `places=False`, and built once for both routes. This answers "can
        # I reach the destination", and a check that also queried four live
        # tables would be slow, and would write a document mixing this
        # made-up reading at the top with four real ones under it -- on the
        # one button somebody presses to find out whether their host is
        # reachable.
        document = self._document(sample, places=False)

        if self.directories:
            trouble = self._write(document)
            written = len(self.directories) - len(trouble)
            if written:
                said.append(f"wrote {DATA_FILE} into "
                            + ", ".join(self.directories[:4])
                            + (" and more" if len(self.directories) > 4 else ""))
            said.extend(trouble)

        if self.url:
            try:
                self._send(document)
                where = self.path.rsplit("/", 1)[0] or ""
                said.append(f"{self.host}{self.path} accepted a reading; the "
                            f"page reads it back from {where}/{DATA_FILE}")
            except Rejected as exc:
                said.append(f"refused: {exc}")
            except Exception as exc:
                said.append(f"could not reach {self.host}: {exc}")

        if self.carries_places:
            # Named, not read -- see the note on `places=False` above.
            how_many = len(self.carries_places)
            said.append(f"carries {how_many} "
                        f"place{'' if how_many == 1 else 's'}: "
                        + ", ".join(one.name
                                    for one in self.carries_places[:6])
                        + (" and more" if how_many > 6 else ""))

        return ". ".join(said) if said else "nothing is configured to send to."

    def status(self) -> dict:
        # The places are in here because `cli._uploads_differ` compares
        # exactly this dict to decide whether a running upload has to be
        # rebuilt. Without them, a place added on the settings page reaches
        # the live document only at the next restart -- the failure mode
        # this project has written down twice, arriving in the one subsystem
        # whose whole job is to say that something has stopped.
        return {"host": self.host, "path": self.path,
                "directories": self.directories,
                "places": [one.name for one in self.carries_places]}

    @staticmethod
    def from_exports(settings: object) -> tuple[str, str, list[str], str]:
        """Where to send, from the exports that asked for live readings.

        Four things come back: the address of a `live.php` on a web host, the
        token for it, every directory on this machine to write into, and the
        units those pages are written in. An
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

        Not the places. Which series the document carries is resolved once,
        by the feed, and attached with `carry` -- see there for why nothing
        that is not a declared `Option` can travel in through `settings`.
        """
        from ..exports.livepush import rendered_units, token_for, url_for

        section = getattr(settings, "config", {}).get("exports") or {}
        token = token_for(str(settings.get("token") or ""))
        url = ""
        directories: list[str] = []
        # The units of whichever export supplies the address, or of the first
        # local one -- the same export whose pages will be reading the file.
        system = ""
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
                    if not system:
                        system = rendered_units(settings, configured)
                continue
            address = str(configured.get("live_push_url") or "").strip()
            if address and not url:
                url = url_for(address)
                # The address wins over a local directory: it is the export
                # somebody configured on purpose, and its pages are the ones
                # this document is for.
                system = rendered_units(settings, configured)
        return url, token, directories, system

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

#!/usr/bin/env python3
"""Neither server dies because something inside it did.

The premise, and it is WeeWX's everywhere: a long-running weather service
answers. Not "answers correctly under every condition" -- that is a promise
nobody can keep -- but *answers*, so that whoever is on the other end learns
something and can go on.

Two ends, and they want opposite status codes:

  the settings page   a person, in a browser. 500 with the reason on it, so
                      the next thing they do is informed. A dropped
                      connection says "connection reset" and nothing else.

  the listener        a console, with no operator and no retry queue. 200,
                      because an error is often the last thing it does
                      before going quiet, and the fault is at this end.

What this measures is the same in both cases: provoke a failure inside a
handler, then check that the request was answered *and* that the request
after it still works. The second half is the one that matters -- a server
that answers once and then cannot take another connection has not survived
anything.

    python tools/resilience_test.py
"""

from __future__ import annotations

import gc
import http.client
import logging
import re
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import admin as admin_mod
from weewx_evo import adminarchives
from weewx_evo import archives as archive_defs
from weewx_evo import config as config_file
from weewx_evo.admin import Admin, AdminServer
from weewx_evo.cli import all_schemas
from weewx_evo.db.live import LiveStore
from weewx_evo.ingest import listener as listener_mod
from weewx_evo.ingest.listener import HttpListener, Ingest
from weewx_evo.ratelimit import Limits

failures: list[str] = []


class Messages(logging.Handler):
    """The rendered log records from one request."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def problem(html: str) -> str:
    """The complaint the page is carrying, if it is carrying one."""
    found = re.search(r'<p class="err">([^<]*)', html)
    return found.group(1).strip() if found else ""


def check(what: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(what)


def get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """Fetch, and treat a dropped connection as the failure it is."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as reply:
            return reply.status, reply.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, http.client.HTTPException,
            ConnectionError) as exc:
        # This is what a server that died looks like from outside.
        return 0, f"{type(exc).__name__}: {exc}"


def post(url: str, body: bytes, timeout: float = 10.0) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, method="POST")
    return get_from(request, timeout)


def get_from(request: urllib.request.Request, timeout: float) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status, reply.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, http.client.HTTPException,
            ConnectionError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def raw_exchange(port: int, request: bytes) -> bytes:
    """One raw HTTP exchange, including pipelined replies if there are any."""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as wire:
        wire.settimeout(10)
        wire.sendall(request)
        # Let a deliberately invalid negative length reach EOF on an old,
        # vulnerable handler too; the test should fail, not leave it blocked.
        wire.shutdown(socket.SHUT_WR)
        answer = bytearray()
        while True:
            try:
                chunk = wire.recv(65536)
            except (TimeoutError, ConnectionResetError):
                break
            if not chunk:
                break
            answer.extend(chunk)
    return bytes(answer)


def response_codes(answer: bytes) -> list[int]:
    return [int(code) for code in re.findall(rb"HTTP/1\.[01] ([0-9]{3})", answer)]


def ambiguous_bodies(port: int, path: str, service: str) -> None:
    for label, headers in (
        ("duplicate content lengths", "Content-Length: 0\r\nContent-Length: 1\r\n"),
        ("unsupported transfer encoding", "Transfer-Encoding: chunked\r\n"),
    ):
        answer = raw_exchange(
            port, (f"POST {path} HTTP/1.1\r\nHost: localhost\r\n"
                   f"{headers}Connection: close\r\n\r\n").encode())
        check(f"{service} refuses {label}",
              response_codes(answer) == [400], repr(response_codes(answer)))


# ----------------------------------------------------------------- the page

def settings_page(work: Path) -> None:
    print("\nThe settings page, for a person")

    path = work / "evo.toml"
    config_file.write(path, {"station": {"name": "Resilience"}},
                      all_schemas(path))
    token = "admin-secret-that-must-not-be-logged"
    admin = Admin(path, lambda: all_schemas(path), token,
                  limits=Limits(rate=0, failures=0))
    server = AdminServer(admin, "127.0.0.1", 0)
    server.start()
    base = f"http://127.0.0.1:{server.port}/{token}"
    try:
        records = Messages()
        old_level = admin_mod.log.level
        admin_mod.log.addHandler(records)
        admin_mod.log.setLevel(logging.DEBUG)
        try:
            status, _ = get(f"{base}/overview")
        finally:
            admin_mod.log.removeHandler(records)
            admin_mod.log.setLevel(old_level)
        check("a page answers to begin with", status == 200, f"status {status}")
        check("the admin token is absent from request logs",
              bool(records.lines) and all(token not in line for line in records.lines),
              repr(records.lines[:2]))

        # Break the thing that builds every page. This is the shape of a real
        # bug: not a bad request, but our own code raising where nobody put a
        # try around it.
        whole = admin_mod.page

        def explode(*_args: object, **_kw: object) -> bytes:
            raise RuntimeError("the page builder blew up")

        admin_mod.page = explode
        try:
            status, body = get(f"{base}/overview")
            check("a handler that raises still answers", status == 500,
                  f"status {status}")
            check("and the answer names the failure",
                  "the page builder blew up" in body)
            check("and says the service is still there",
                  "still running" in body)
        finally:
            admin_mod.page = whole

        status, _ = get(f"{base}/overview")
        check("the request after the failure works", status == 200,
              f"status {status}")

        # The one the user actually met: an upload that is not a database.
        # It has its own handler, so it answers in the page rather than with
        # the blunt 500 above -- but it must still answer.
        status, body = post(f"{base}/setup/upload-archive",
                            b"this is not an SQLite file, not even close")
        check("a raw body where a form belongs answers", status == 400,
              f"status {status}")
        check("and the answer is a sentence, not an empty line",
              len(body.strip()) > 10, repr(body[:60]))

        # The one the user met: a well-formed upload whose contents are not a
        # database. Everything about the request is right, and the thing that
        # fails is our own code opening it.
        edge = "----resilience"
        crlf = "\r\n"
        head = (f"--{edge}{crlf}"
                f'Content-Disposition: form-data; name="archive"; '
                f'filename="weewx.sdb"{crlf}'
                f"Content-Type: application/octet-stream{crlf}{crlf}")
        junk = (head.encode()
                + b"SQLite format 3\x00 but truncated here"
                + f"{crlf}--{edge}--{crlf}".encode())
        request = urllib.request.Request(
            f"{base}/setup/upload-archive", data=junk, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={edge}"})
        status, body = get_from(request, 20.0)
        check("an upload that is not a database answers", status in (200, 400),
              f"status {status}")
        check('and the page it comes back on says so',
              'That upload failed' in body or 'not' in problem(body),
              repr(problem(body)[:90]))
        status, _ = get(f"{base}/overview")
        check("and the page is up afterwards", status == 200, f"status {status}")

        # A request that is malformed before any handler sees it.
        raw = socket.create_connection(("127.0.0.1", server.port), timeout=10)
        raw.sendall((f"GET /{token}/overview HTTP/1.1\r\n"
                     "Content-Length: banana\r\n\r\n").encode())
        try:
            raw.recv(64)
        except OSError:
            pass
        raw.close()
        status, _ = get(f"{base}/overview")
        check("a malformed request does not take the server with it",
              status == 200, f"status {status}")

        answer = raw_exchange(
            server.port,
            (f"POST /{token}/nowhere HTTP/1.1\r\n"
             "Host: localhost\r\nContent-Length: -1\r\n"
             "Connection: close\r\n\r\n").encode())
        check("a negative admin body length is refused",
              response_codes(answer) == [400], repr(response_codes(answer)))
        ambiguous_bodies(server.port, f"/{token}/nowhere", "the admin page")

        # A body that starts with another complete request is the compact
        # form of request smuggling. The declared size is deliberately over
        # the form limit, so a handler that replies without closing will
        # process that body as an authenticated GET on the same connection.
        second = (f"GET /{token}/overview HTTP/1.1\r\nHost: localhost\r\n"
                  "Connection: close\r\n\r\n").encode()
        answer = raw_exchange(
            server.port,
            (f"POST /{token}/nowhere HTTP/1.1\r\nHost: localhost\r\n"
             f"Content-Length: {admin_mod.MAX_FORM + 1}\r\n\r\n").encode()
            + second)
        check("an oversized admin body cannot become another request",
              response_codes(answer) == [413], repr(response_codes(answer)))

        status, _ = get(f"{base}/overview")
        check("the admin page survives refused body lengths",
              status == 200, f"status {status}")

        hostile = '<img src=x onerror="alert(1)">'
        note = adminarchives._file_note(SimpleNamespace(
            exists=True, unreachable=hostile, count=0, size=0, system=""))
        system = adminarchives._file_note(SimpleNamespace(
            exists=True, unreachable="", count=1, size=1, system=hostile))
        check("archive diagnostics are text, not stored markup",
              "<img" not in note and "<img" not in system
              and "&lt;img" in note and "&lt;img" in system)

        # These strings come from ordinary Place form fields. Newlines and
        # control characters must round-trip rather than making the central
        # file unreadable on every process's next refresh.
        odd_label = 'North\n"quoted"\tcontrol:\x01\x7f'
        register_path = work / "escaped-archives.toml"
        register = archive_defs.Register([
            archive_defs.Archive("default", "data/weather.sdb",
                                 label=odd_label)
        ], register_path)
        register.save()
        round_trip = archive_defs.Register.load(register_path).get("default").label
        check("place strings survive TOML escaping",
              round_trip == odd_label, repr(round_trip))

        before = register_path.read_bytes()

        class BrokenRegister(archive_defs.Register):
            def render(self) -> str:
                return 'label = "unterminated\n'

        broken = BrokenRegister(register.all(), register_path)
        # Refusing is the whole point, and how it refuses is not the claim.
        # What the check below reads is the file it did not replace.
        try:
            broken.save()
        except Exception:  # noqa: S110
            pass
        check("invalid rendered TOML cannot replace the last valid file",
              register_path.read_bytes() == before)
    finally:
        server.stop()


# ------------------------------------------------------------- the listener

def listener(work: Path) -> None:
    print("\nThe listener, for a console with no operator")

    store = LiveStore(work / "live.sdb", interval_seconds=60)
    token = "listener-secret-that-must-not-be-logged"
    ingest = Ingest(store, token=token, limits=Limits(rate=0, failures=0))
    server = HttpListener(ingest, "127.0.0.1", 0)
    # Production request threads are daemons so a broken console cannot hold
    # shutdown hostage. This test owns a temporary database, so make teardown
    # wait for every request handler before removing that database on Windows.
    server.server.daemon_threads = False
    server.start()
    base = f"http://127.0.0.1:{server.port}"
    upload = f"{base}/{token}/data/report"
    body = (b"PASSKEY=ABC&stationtype=GW1000&dateutc=now&tempf=68.0"
            b"&humidity=50&baromrelin=29.9")
    try:
        records = Messages()
        old_level = listener_mod.log.level
        listener_mod.log.addHandler(records)
        listener_mod.log.setLevel(logging.DEBUG)
        try:
            status, expected = post(upload, body)
        finally:
            listener_mod.log.removeHandler(records)
            listener_mod.log.setLevel(old_level)
        check("an upload is taken to begin with", status == 200, f"status {status}")
        check("the listener token is absent from request logs",
              bool(records.lines) and all(token not in line for line in records.lines),
              repr(records.lines[:2]))

        # The half `submit` did not guard until now: the driver read the body
        # fine, and putting the result away is what failed. A full disk looks
        # exactly like this.
        whole = store.add

        def refuse(*_args: object, **_kw: object) -> bool:
            raise OSError(28, "No space left on device")

        store.add = refuse  # type: ignore[method-assign]
        try:
            status, said = post(upload, body)
            check("a table that cannot take the reading still answers",
                  status == 200, f"status {status}")
            # Not "some 200": the *same* bytes a working upload gets. A
            # console waits for its protocol's own acknowledgement, and
            # Ecowitt's is not "success" -- guessing at the string here would
            # have passed while telling the hardware something else.
            check("and the console hears exactly what a good upload gets",
                  said == expected, f"{said.strip()!r} vs {expected.strip()!r}")
        finally:
            store.add = whole  # type: ignore[method-assign]

        status, _ = post(upload, body)
        check("the next upload is recorded", status == 200, f"status {status}")

        # Above the guard: something outside `submit` entirely.
        whole_submit = ingest.submit

        def explode(*_args: object, **_kw: object) -> tuple:
            raise RuntimeError("ingest blew up")

        ingest.submit = explode  # type: ignore[method-assign]
        try:
            status, said = post(upload, body)
            check("a failure above the guard answers 200", status == 200,
                  f"status {status}")
            # Here the driver is never reached, so there is nothing to ask
            # what it would have said. The registry's default is the best
            # available answer, and it is a positive one on purpose.
            check("with a positive answer rather than a dropped line",
                  said.strip() == "success", repr(said.strip()))
        finally:
            ingest.submit = whole_submit  # type: ignore[method-assign]

        status, _ = post(upload, body)
        check("and uploads keep working", status == 200, f"status {status}")

        # The status page reads a lot of things that a broken installation
        # does not have. It must not take the upload endpoint with it.
        whole_status = ingest.status

        def no_status(*_args: object, **_kw: object) -> dict:
            raise RuntimeError("status blew up")

        ingest.status = no_status  # type: ignore[method-assign]
        try:
            status, _ = get(f"{base}/{token}/status")
            check("a broken status page answers", status in (200, 500),
                  f"status {status}")
        finally:
            ingest.status = whole_status  # type: ignore[method-assign]

        status, _ = post(upload, body)
        check("and the upload endpoint is untouched by it", status == 200,
              f"status {status}")

        # Counted, not silently swallowed: a failure that always answers 200
        # has to be visible somewhere a person looks.
        check("the failures were counted", ingest.rejected >= 2,
              f"rejected={ingest.rejected}")

        # A console that hangs up mid-upload. Cheap hardware does this.
        raw = socket.create_connection(("127.0.0.1", server.port), timeout=10)
        raw.sendall((f"POST /{token}/data/report HTTP/1.1\r\n"
                     "Content-Length: 500\r\n\r\nhalf").encode())
        raw.close()
        status, _ = post(upload, body)
        check("a console that hangs up mid-upload costs nothing",
              status == 200, f"status {status}")

        answer = raw_exchange(
            server.port,
            (f"POST /{token}/data/report HTTP/1.1\r\nHost: localhost\r\n"
             "Content-Length: -1\r\nConnection: close\r\n\r\n").encode())
        check("a negative listener body length is refused",
              response_codes(answer) == [400], repr(response_codes(answer)))
        ambiguous_bodies(server.port, f"/{token}/data/report", "the listener")

        answer = raw_exchange(
            server.port,
            (f"POST /{token}/data/report HTTP/1.1\r\nHost: localhost\r\n"
             f"Content-Length: {listener_mod.MAX_BODY + 1}\r\n"
             "Connection: close\r\n\r\n").encode())
        check("an oversized listener upload is refused, not truncated",
              response_codes(answer) == [413], repr(response_codes(answer)))

        status, _ = post(upload, body)
        check("the listener survives refused body lengths",
              status == 200, f"status {status}")
    finally:
        server.stop()
        store.close()
        # Handler connections belong to their request threads. They are all
        # joined above; collect the retired thread-local state before Windows
        # removes the temporary SQLite file.
        gc.collect()


def main() -> int:
    print("Resilience: a failure inside is answered, not dropped")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        settings_page(work)
        listener(work)

    print()
    if failures:
        print(f"{len(failures)} failed:")
        for one in failures:
            print(f"  - {one}")
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""A console that is not there: Ecowitt uploads, on the wire, every 16 s.

There is a simulated Davis down to the serial port, a simulated Fine Offset
down to the USB bus and a simulated `rtl_433`. This is the fourth kind of
console: the sort that needs no driver at all because it uploads by itself.
Everything it exercises is the half those three cannot reach -- the socket,
the token in the path, the rate limit, the field map, `stations.toml`, the
live table, and the archiver at the other end of it.

It sends a **recorded** upload rather than an invented one. The field names,
their spelling and their units are the console's, not ours, and a simulator
that made them up would agree with our own parser and with nothing else.
`tests/uploads/hp2561ae_pro.txt` is the shape; the values move and the
clock is now.

    python tools/ecowittsim.py http://box.local:8000/<token>/ecowitt/
    python tools/ecowittsim.py https://weather.example.org/<token>/ecowitt/ \\
        --every 16 --passkey 0000000000000000000000000000BEEF

The token is part of the address and is never written into this file: it is
the one thing between the open internet and somebody's measurement series.

`--once` sends one upload and says what came back, which is the whole of
"can this console reach that listener". Without it, it keeps going until
Ctrl-C, printing a line per upload.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: Beside this file first, then where it lives in the repository. This tool
#: is useful copied onto the machine the console is pretending to stand next
#: to, and there it arrives as two files in one directory.
RECORDED_AT = (HERE / "hp2561ae_pro.txt",
               HERE.parent / "tests" / "uploads"
               / "hp2561ae_pro.txt")

def expected_answer() -> str:
    """What this console has to hear back, read off the protocol itself.

    Ecowitt firmware is stricter than most about the answer -- it wants a
    particular JSON document and treats anything else as a broken server, and
    some models stop trying. So the string is not typed here: it is read from
    the protocol that produces it, and the two cannot drift apart.

    Typed, it was `"success"`, which is the *default* for a protocol that
    names none. This one names one. The simulator then reported FAIL against
    a listener that had accepted the upload and answered correctly -- a
    perfect reading of a healthy system as a broken one.
    """
    try:
        sys.path.insert(0, str(HERE.parent / "src"))
        from weewx_evo_ecowitt.protocols import ecowitt

        return str(getattr(ecowitt.Ecowitt, "answer", "") or "success")
    except Exception:
        return "success"

#: Which fields move, and how far from their recorded value. A console that
#: sends the same number for ever exercises the archiver's arithmetic on a
#: flat line, and a flat line is the one case where a wrong weighting is
#: invisible.
SWINGS = {
    "tempf": 6.0, "tempinf": 2.0, "humidity": 8.0, "humidityin": 4.0,
    "baromrelin": 0.08, "baromabsin": 0.08, "windspeedmph": 3.0,
    "windgustmph": 5.0, "solarradiation": 180.0, "uv": 2.0,
    "soil_ec_temp1": 3.0, "tf_ch1": 4.0, "tf_ch2": 4.0,
}

#: Readings that only ever climb, because that is what a rain counter does.
#: Reset to zero at local midnight the way the console resets them -- an
#: archiver that sees `dailyrainin` fall is looking at a new day, and getting
#: that wrong is a day of rain counted twice.
CLIMBING = ("eventrainin", "hourlyrainin", "dailyrainin", "weeklyrainin",
            "monthlyrainin", "yearlyrainin")


def recorded() -> dict[str, str]:
    """The fixture, as a field map, in the order the console sent it."""
    found = next((one for one in RECORDED_AT if one.is_file()), None)
    if found is None:
        raise SystemExit("no recorded upload; looked in "
                         + " and ".join(str(one) for one in RECORDED_AT))
    raw = found.read_text(encoding="utf-8").strip().splitlines()[0]
    return dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))


def _wobble(value: str, swing: float, phase: float) -> str:
    """One reading, moved plausibly rather than randomly.

    A slow sine plus a little noise: weather is autocorrelated, and a value
    that jumps its whole range between two uploads is one every quality rule
    in `quality.py` would rightly throw away.
    """
    try:
        base = float(value)
    except ValueError:
        return value
    # The one random number in this file decides whether a simulated
    # temperature wobbles by a tenth of a degree. Not a secret.
    moved = base + swing * math.sin(phase) + random.uniform(-swing, swing) * 0.1  # noqa: S311
    if value.isdigit():
        return str(max(0, round(moved)))
    places = len(value.split(".")[-1]) if "." in value else 1
    return f"{max(0.0, moved):.{places}f}"


def upload(fields: dict[str, str], step: int, started: float) -> dict[str, str]:
    """One upload's worth: the recorded fields, now, with the values moved."""
    now = time.time()
    out = dict(fields)

    # UTC, to the second, spaces and all -- the console's own format. And
    # *now*, every time: a listener only trusts a console's clock when it is
    # within an hour of its own, so a simulator with a fixed date passes on
    # the day it is written and never again. That is not hypothetical; it is
    # what `tools/wunderground_test.py` did.
    out["dateutc"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))
    out["runtime"] = str(int(now - started) + 11629)

    phase = step / 40.0
    for name, swing in SWINGS.items():
        if name in out:
            out[name] = _wobble(out[name], swing, phase)

    # A gust is never below the wind it gusted from. Consoles do not send
    # that and a rule that reads one as the other would be measuring our
    # simulator rather than the archiver.
    try:
        if float(out.get("windgustmph", 0)) < float(out.get("windspeedmph", 0)):
            out["windgustmph"] = out["windspeedmph"]
        highest = max(float(out.get("maxdailygust", 0)),
                      float(out["windgustmph"]))
        out["maxdailygust"] = f"{highest:.2f}"
    except (KeyError, ValueError):
        pass

    # Rain climbs, and every counter climbs by the same amount: they are the
    # same rain over different spans. A shower now and then rather than a
    # drizzle for ever, so a dry spell is a thing that happens.
    fell = 0.004 if (step % 90) < 12 else 0.0
    for name in CLIMBING:
        if name not in out:
            continue
        try:
            out[name] = f"{float(out[name]) + fell:.3f}"
        except ValueError:
            pass
    out["rainratein"] = f"{fell * 225:.3f}"
    return out


def send(url: str, fields: dict[str, str], timeout: float) -> tuple[int, str]:
    body = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 # What the firmware calls itself. A listener may log it, and
                 # a simulator that says "python-urllib" is one whose traffic
                 # cannot be told from a script poking at the port.
                 "User-Agent": "HP2561AE_Pro_V2.1.4"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return answer.status, answer.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace").strip()[:200]
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="An Ecowitt console that is not there.")
    parser.add_argument("url", help="the whole address, token and all: "
                                    "http://host:8000/<token>/ecowitt/")
    parser.add_argument("--every", type=float, default=16.0,
                        help="seconds between uploads (default 16, which is "
                             "what these consoles send at)")
    parser.add_argument("--count", type=int, default=0,
                        help="stop after this many (default: keep going)")
    parser.add_argument("--once", action="store_true",
                        help="send one and say what came back")
    parser.add_argument("--passkey", default="",
                        help="the console's own identity. A fresh one is a "
                             "console this installation has never seen, which "
                             "is what makes it a new station")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv[1:])

    fields = recorded()
    if args.passkey:
        fields["PASSKEY"] = args.passkey
    # Not random by default. A console keeps its identity across restarts,
    # and a simulator that invents one every run announces a new station
    # every run -- `stations.toml` fills up with strangers and the page that
    # lists them stops being readable.
    print(f"console {fields['PASSKEY']} -> {args.url}")
    print(f"  every {args.every:g}s, {len(fields)} fields per upload")

    wanted_answer = expected_answer()
    started = due = time.time()
    sent = failed = 0
    wanted = 1 if args.once else args.count
    try:
        while True:
            body = upload(fields, sent + failed, started)
            code, answer = send(args.url, body, args.timeout)
            good = code == 200 and answer == wanted_answer
            sent, failed = sent + int(good), failed + int(not good)
            if not args.quiet or not good:
                mark = "ok  " if good else "FAIL"
                print(f"  {mark} {time.strftime('%H:%M:%S')} "
                      f"{code} {answer!r} tempf={body.get('tempf')} "
                      f"dailyrainin={body.get('dailyrainin')}")
                if not good and code == 404:
                    # The listener answers 404 to a wrong token, always, and
                    # says nothing more: telling a caller "wrong token" is
                    # confirming there is something here worth guessing at.
                    # Which means 404 is also what a wrong *path* looks like.
                    print("       404 is a wrong token or a wrong path -- "
                          "those look the same on purpose.")
            if wanted and (sent + failed) >= wanted:
                break
            # Until the next slot, not for `every` seconds. A console sends
            # every sixteen seconds; sleeping sixteen seconds *after* the
            # request finishes makes it sixteen plus the round trip, which
            # over a remote HTTPS hop was twenty-two -- and it drifts further
            # the slower the far end is. Same reasoning as `schedule.py`: an
            # interval counted from your own last go is one that never lands
            # where it says it does. A slot that has already passed is
            # skipped rather than caught up on, because a console that was
            # offline does not send a backlog.
            due += args.every * max(1, math.ceil((time.time() - due)
                                                 / args.every))
            time.sleep(max(0.0, due - time.time()))
    except KeyboardInterrupt:
        print()
    print(f"{sent} accepted, {failed} not")
    return 0 if sent and not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

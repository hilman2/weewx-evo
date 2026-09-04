"""A page showing what is arriving, right now.

Behind the token, because it sits on the same path the hardware uploads to and
that path is the only thing between the open internet and the measurement
series.

It exists for one question, asked over and over while setting a station up:
*is anything coming in?* Answering it otherwise means an SSH session, a
`docker exec` and a hand-written SQL query, which is a lot of ceremony for
looking at a thermometer.

Deliberately plain. No framework, no build step, no request to anywhere else --
it is served by a listener that may be the only thing running on a Raspberry Pi
with no route to the internet. It polls, rather than holding a connection open:
a console uploads every few seconds, so a two-second poll is live enough, and
an open connection per viewer would tie up a thread in a server that has a
handful.

Nothing secret is rendered. The token is in the address bar and cannot be
helped, but it is never written into the page, and a station's PASSKEY -- which
is what identifies it, and what somebody would need in order to forge its
readings -- is shortened to its first characters.
"""

from __future__ import annotations

import time
from typing import Any

#: How much of a source identifier to show. Enough to tell two consoles apart,
#: not enough to impersonate one.
SOURCE_CHARS = 8

#: Fields worth putting at the top, in this order, when the station sends them.
HEADLINE = (
    ("outTemp", "Outside"),
    ("outHumidity", "Humidity"),
    ("barometer", "Barometer"),
    ("windSpeed", "Wind"),
    ("rainRate", "Rain rate"),
    ("radiation", "Solar"),
)


def short_source(source: str) -> str:
    if len(source) <= SOURCE_CHARS + 2:
        return source
    return source[:SOURCE_CHARS] + ".."


def _headline_from(store: Any, last: int, placer: Any) -> dict:
    """The newest packet in archive column names, for the six figures on top.

    Empty where nothing places, which is a listener with no placement
    configured -- and then the page shows the table alone rather than six
    boxes that would all read "--" without saying why.
    """
    if placer is None:
        return {}
    for packet in reversed(list(store.packets(last - 1, last))):
        placed = placer.place(packet)
        if placed is not None:
            return placed.data
    return {}


def recent(store: Any, ingest: Any, limit: int = 12) -> dict:
    """What the page needs: the last few packets, and how things are going."""
    now = time.time()
    packets: list[dict] = []
    first, last = store.span()

    if last is not None:
        # A window rather than a row count: `packets()` is indexed on time, and
        # the newest few are all anyone is looking at.
        window = max(600, limit * 60)
        placer = getattr(ingest, "placer", None)
        for packet in store.packets(last - window, last, with_raw=True):
            # The names the console used, not the archive columns they will
            # become. This page is for the question "what is arriving", and
            # the field that is *not* being placed is exactly the one a
            # placed view cannot show.
            packets.append({
                "dateTime": packet.dateTime,
                "age": round(now - packet.dateTime, 1),
                "source": short_source(
                    placer.named(packet.driver, packet.identity) if placer
                    else (packet.identity or packet.driver)),
                "kind": packet.kind,
                "fields": len(packet.data),
                "data": packet.data,
                # The upload as it arrived, with the driver's secrets removed.
                # Gone after an hour; the page says so rather than showing an
                # empty box.
                "raw": packet.raw,
            })
        packets = packets[-limit:]
        packets.reverse()

    # Packets per minute over the last five, which is what tells you a console
    # has gone quiet before the age of the last one does.
    rate = None
    if last is not None and first is not None:
        span = min(300, max(1, last - first))
        count = sum(1 for p in store.packets(last - span, last))
        rate = round(count / (span / 60), 1)

    status = ingest.status()
    # The headline is the exception, and it has to be: `outTemp` is an
    # archive column, and the row above holds `tempf`. Placed here so the
    # six named readings say the same thing as every page on the site, while
    # the table underneath goes on showing what actually arrived.
    latest = _headline_from(store, last, placer) if last is not None else {}
    return {
        "now": now,
        "packets": packets,
        "rate_per_min": rate,
        "headline": [
            {"key": key, "label": label, "value": latest[key]}
            for key, label in HEADLINE if key in latest
        ],
        "status": status,
    }


def render(title: str = "weewx-evo") -> bytes:
    """The page itself. One file, no dependencies."""
    return _PAGE.replace("{{TITLE}}", title).encode("utf-8")


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{{TITLE}} live</title>
<style>
  :root {
    --bg: #fbfaf8; --panel: #fff; --line: #e5e1da; --ink: #1d1b18;
    --dim: #6f6a62; --accent: #2f6f4e; --warn: #9a5b1e; --bad: #97321f;
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17161a; --panel: #1f1e23; --line: #322f38; --ink: #eceaf0;
      --dim: #9a94a3; --accent: #79c79b; --warn: #e0a86a; --bad: #e08a76;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .wrap { max-width: 62rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  header { display: flex; align-items: baseline; gap: .75rem; flex-wrap: wrap;
           margin-bottom: 1.25rem; }
  h1 { font-size: 1.25rem; margin: 0; font-weight: 600; letter-spacing: -.01em; }
  .pulse { display: inline-flex; align-items: center; gap: .45rem;
           font-size: .8125rem; color: var(--dim); }
  .dot { width: .5rem; height: .5rem; border-radius: 50%; background: var(--dim); }
  .dot.live { background: var(--accent); animation: beat 2s ease-in-out infinite; }
  .dot.stale { background: var(--warn); }
  .dot.dead { background: var(--bad); }
  @keyframes beat { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
  @media (prefers-reduced-motion: reduce) { .dot.live { animation: none } }

  .cards { display: grid; gap: .75rem; grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
           margin-bottom: 1.25rem; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: .5rem;
          padding: .75rem .875rem; }
  .card .k { font-size: .75rem; color: var(--dim); text-transform: uppercase;
             letter-spacing: .04em; }
  .card .v { font-size: 1.5rem; font-variant-numeric: tabular-nums; margin-top: .15rem;
             font-weight: 600; }

  section { background: var(--panel); border: 1px solid var(--line);
            border-radius: .5rem; margin-bottom: 1rem; overflow: hidden; }
  section > h2 { font-size: .8125rem; text-transform: uppercase; letter-spacing: .04em;
                 color: var(--dim); margin: 0; padding: .7rem .875rem;
                 border-bottom: 1px solid var(--line); font-weight: 600; }
  .body { padding: .875rem; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: .8125rem; }
  th, td { text-align: left; padding: .4rem .875rem; white-space: nowrap; }
  th { color: var(--dim); font-weight: 500; font-size: .75rem;
       text-transform: uppercase; letter-spacing: .03em; }
  tbody tr { border-top: 1px solid var(--line); }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums;
                   font-family: var(--mono); }
  td.mono { font-family: var(--mono); color: var(--dim); }
  tr.fresh td { background: color-mix(in srgb, var(--accent) 9%, transparent); }

  .kv { display: grid; grid-template-columns: auto 1fr; gap: .3rem 1rem;
        font-size: .8125rem; }
  .kv dt { color: var(--dim); }
  .kv dd { margin: 0; font-family: var(--mono); overflow-wrap: anywhere; }
  .empty { color: var(--dim); font-size: .875rem; padding: .5rem 0; }
  footer { color: var(--dim); font-size: .75rem; margin-top: 1.5rem; }
  code { font-family: var(--mono); font-size: .95em; }

  tbody tr.pick { cursor: pointer; }
  tbody tr.pick:hover td { background: color-mix(in srgb, var(--ink) 5%, transparent); }
  tbody tr.open td { background: color-mix(in srgb, var(--accent) 13%, transparent); }
  pre { margin: 0; font-family: var(--mono); font-size: .78125rem; line-height: 1.55;
        white-space: pre-wrap; overflow-wrap: anywhere;
        background: color-mix(in srgb, var(--ink) 5%, transparent);
        border: 1px solid var(--line); border-radius: .35rem; padding: .6rem .7rem; }
  .row { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap;
         margin-bottom: .5rem; }
  button { font: inherit; font-size: .8125rem; padding: .3rem .7rem; cursor: pointer;
           color: var(--ink); background: var(--panel);
           border: 1px solid var(--line); border-radius: .3rem; }
  button:hover { border-color: var(--dim); }
  .hint { color: var(--dim); font-size: .78125rem; }
  .fields { columns: 3 11rem; column-gap: 1.25rem; font-size: .8125rem;
            font-family: var(--mono); }
  .fields div { break-inside: avoid; }
  .fields b { font-weight: 400; color: var(--dim); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{{TITLE}}</h1>
    <span class="pulse"><span class="dot" id="dot"></span>
      <span id="pulse">connecting...</span></span>
  </header>

  <div class="cards" id="cards"></div>

  <section>
    <h2>Arriving</h2>
    <div class="scroll">
      <table>
        <thead><tr>
          <th>Time</th><th>Age</th><th>Source</th><th>Kind</th>
          <th class="num">Fields</th><th>outTemp</th><th>Wind</th>
        </tr></thead>
        <tbody id="rows"><tr><td colspan="7" class="empty">waiting...</td></tr></tbody>
      </table>
    </div>
    <div class="body hint" id="pickhint">Pick a row to see the upload it came from.</div>
  </section>

  <section id="detail" hidden>
    <h2>The upload itself</h2>
    <div class="body">
      <div class="row">
        <button id="copy" type="button">Copy for an issue</button>
        <span class="hint" id="copied"></span>
      </div>
      <pre id="raw"></pre>
      <div class="row" style="margin:.9rem 0 .4rem"><span class="hint">
        What the driver made of it
      </span></div>
      <div class="fields" id="parsed"></div>
    </div>
  </section>

  <section>
    <h2>Listener</h2>
    <div class="body"><dl class="kv" id="listener"></dl></div>
  </section>

  <section>
    <h2>Drivers</h2>
    <div class="body" id="drivers"></div>
  </section>

  <footer>
    Polls every 2&nbsp;s. Behind the upload token, so keep the address to yourself.
    Uploads are kept for an hour and shown with the station identifier removed.
  </footer>
</div>

<script>
(function () {
  "use strict";
  // The page is served from the token path, so everything it asks for is
  // relative to that. No address is built from anything the page was told.
  var base = location.pathname.replace(/\\/+$/, "");
  var dot = document.getElementById("dot");
  var pulse = document.getElementById("pulse");
  var failures = 0;
  // Which packet's body is open, by timestamp. Held across polls so the panel
  // does not shut every two seconds, and dropped when the packet ages out.
  var picked = null;
  var latest = null;

  document.getElementById("copy").addEventListener("click", function () {
    var text = document.getElementById("raw").textContent;
    var said = document.getElementById("copied");
    // The clipboard API needs a secure context, which a listener reached over
    // plain HTTP on a local network is not. Fall back rather than fail.
    function ok() { said.textContent = "copied"; }
    function no() {
      said.textContent = "select the text and copy it";
      var sel = window.getSelection();
      var range = document.createRange();
      range.selectNodeContents(document.getElementById("raw"));
      sel.removeAllRanges();
      sel.addRange(range);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(ok, no);
    } else {
      no();
    }
  });

  function fmt(v) {
    if (v === null || v === undefined) return "\\u2014";
    if (typeof v !== "number") return String(v);
    return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/\\.?0+$/, "");
  }

  function clock(ts) {
    var d = new Date(ts * 1000);
    return d.toTimeString().slice(0, 8);
  }

  function age(seconds) {
    if (seconds === null || seconds === undefined) return "\\u2014";
    if (seconds < 90) return Math.round(seconds) + " s";
    if (seconds < 5400) return Math.round(seconds / 60) + " min";
    return Math.round(seconds / 3600) + " h";
  }

  function paint(d) {
    var newest = d.packets.length ? d.packets[0].age : null;
    var state = newest === null ? "dead"
              : newest < 90 ? "live"
              : newest < 900 ? "stale" : "dead";
    dot.className = "dot " + state;
    pulse.textContent = newest === null
      ? "nothing yet"
      : "last packet " + age(newest) + " ago"
        + (d.rate_per_min ? " \\u00b7 " + d.rate_per_min + "/min" : "");

    var host = document.getElementById("cards");
    host.innerHTML = "";
    d.headline.forEach(function (h) {
      var card = document.createElement("div");
      card.className = "card";
      var k = document.createElement("div");
      k.className = "k";
      k.textContent = h.label;
      var v = document.createElement("div");
      v.className = "v";
      v.textContent = fmt(h.value);
      card.appendChild(k); card.appendChild(v);
      host.appendChild(card);
    });

    var rows = document.getElementById("rows");
    rows.innerHTML = "";
    if (!d.packets.length) {
      var tr = document.createElement("tr");
      var td = document.createElement("td");
      td.colSpan = 7; td.className = "empty";
      td.textContent = "no packets held";
      tr.appendChild(td); rows.appendChild(tr);
    }
    d.packets.forEach(function (p, i) {
      var tr = document.createElement("tr");
      var cls = [];
      if (i === 0 && p.age < 30) cls.push("fresh");
      if (p.raw) cls.push("pick");
      if (picked !== null && p.dateTime === picked) cls.push("open");
      tr.className = cls.join(" ");
      [
        [clock(p.dateTime), "mono"],
        [age(p.age), "mono"],
        [p.source, "mono"],
        [p.kind, ""],
        [String(p.fields), "num"],
        [fmt(p.data.outTemp), "num"],
        [fmt(p.data.windSpeed), "num"]
      ].forEach(function (cell) {
        var td = document.createElement("td");
        td.textContent = cell[0];
        if (cell[1]) td.className = cell[1];
        tr.appendChild(td);
      });
      if (p.raw) {
        tr.addEventListener("click", function () {
          picked = (picked === p.dateTime) ? null : p.dateTime;
          paint(latest);
        });
      }
      rows.appendChild(tr);
    });

    // The chosen packet, if it is still in the window and still has its body.
    var chosen = null;
    for (var j = 0; j < d.packets.length; j++) {
      if (d.packets[j].dateTime === picked && d.packets[j].raw) {
        chosen = d.packets[j];
        break;
      }
    }
    var detail = document.getElementById("detail");
    document.getElementById("pickhint").textContent = d.packets.some(function (p) {
      return p.raw;
    }) ? "Pick a row to see the upload it came from."
       : "Uploads are kept for an hour. These are older, so only what was parsed is left.";

    if (!chosen) {
      detail.hidden = true;
    } else {
      detail.hidden = false;
      document.getElementById("raw").textContent = chosen.raw;
      document.getElementById("copied").textContent = "";
      var parsed = document.getElementById("parsed");
      parsed.innerHTML = "";
      Object.keys(chosen.data).sort().forEach(function (k) {
        var row = document.createElement("div");
        var b = document.createElement("b");
        b.textContent = k + " ";
        row.appendChild(b);
        row.appendChild(document.createTextNode(fmt(chosen.data[k])));
        parsed.appendChild(row);
      });
    }

    var s = d.status;
    var dl = document.getElementById("listener");
    dl.innerHTML = "";
    [
      ["accepted", s.accepted],
      ["duplicates", s.duplicates],
      ["rejected", s.rejected],
      ["packets held", s.packets_held],
      ["oldest", s.oldest_packet ? clock(s.oldest_packet) : "\\u2014"],
      ["newest", s.newest_packet ? clock(s.newest_packet) : "\\u2014"]
    ].forEach(function (pair) {
      var dt = document.createElement("dt");
      dt.textContent = pair[0];
      var dd = document.createElement("dd");
      dd.textContent = String(pair[1] === null || pair[1] === undefined ? "\\u2014" : pair[1]);
      dl.appendChild(dt); dl.appendChild(dd);
    });

    var box = document.getElementById("drivers");
    box.innerHTML = "";
    var drivers = s.drivers || {};
    var names = Object.keys(drivers);
    if (!names.length) {
      var p = document.createElement("p");
      p.className = "empty";
      p.textContent = "no driver reports anything";
      box.appendChild(p);
    }
    names.forEach(function (name) {
      var h = document.createElement("div");
      h.style.marginBottom = ".6rem";
      var strong = document.createElement("div");
      strong.style.fontWeight = "600";
      strong.style.marginBottom = ".25rem";
      strong.textContent = name;
      h.appendChild(strong);
      var dl2 = document.createElement("dl");
      dl2.className = "kv";
      Object.keys(drivers[name]).forEach(function (k) {
        var v = drivers[name][k];
        var dt = document.createElement("dt");
        dt.textContent = k.replace(/_/g, " ");
        var dd = document.createElement("dd");
        dd.textContent = Array.isArray(v) ? (v.join(", ") || "\\u2014")
                       : (v === null ? "\\u2014" : String(v));
        dl2.appendChild(dt); dl2.appendChild(dd);
      });
      h.appendChild(dl2);
      box.appendChild(h);
    });
  }

  function tick() {
    fetch(base + "/recent", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { failures = 0; latest = d; paint(d); })
      .catch(function () {
        failures += 1;
        if (failures > 1) {
          dot.className = "dot dead";
          pulse.textContent = "listener not answering";
        }
      });
  }

  tick();
  setInterval(tick, 2000);
})();
</script>
</body>
</html>
"""

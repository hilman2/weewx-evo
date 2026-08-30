/* Whether a reading is actually live, and how old it is.
 *
 * `live-poll.js` reads the file the station pushed and puts the numbers into
 * the page. What it does not do is say so: a page whose station is pushing
 * and one whose station stopped an hour ago look identical, and a
 * four-hour-old number looks exactly like one from ten seconds ago.
 *
 * That is the failure this file exists for. A dashboard that is quietly wrong
 * is worse than one that is visibly stale.
 *
 * ## Two ways of noticing, and both are needed
 *
 * `live-poll.js` says when it has applied a file, because a poll that finds
 * an unchanged value produces no DOM change to observe -- and a reading that
 * has not moved is still a fresh reading. Without that, a calm afternoon
 * turns every badge red.
 *
 * The MutationObserver is the other half, and it is what makes this work
 * whatever is feeding the page. Anything that writes a value into a card is
 * saying that card is live, and this notices without being told -- so a skin
 * fed some other way keeps its badges.
 *
 * ## What the colours mean
 *
 *   green   this card was updated within FRESH_SECONDS
 *   red     it was not -- either the broker is gone, or this reading is not
 *           in the topic the station publishes
 *   amber   this place's readings arrived in units the page is not written
 *           in, so they were deliberately not written. A different thing to
 *           do about than silence, so a different word and a different
 *           colour
 *
 * The second case is the one worth having. A station that publishes
 * temperature but not soil moisture gives a page where half the cards go live
 * and half never do, and without this nobody finds out why.
 */

(function () {
  "use strict";

  /* How long a card stays green after its last update. Generous on purpose:
   * a station publishing every archive interval rather than every packet
   * sends one every five minutes, and blinking red between them would be
   * technically true and useless. */
  var FRESH_SECONDS = 420;

  /* How long to wait, after connecting, before calling a card that has never
   * updated stale. A packet arrives when it arrives; marking everything red
   * for the first few seconds of every page load is noise. */
  var GRACE_SECONDS = 90;

  /* How many of a place's own reporting intervals may pass before it has
   * stopped. Three, the same number and the same word `tags.place_age` uses
   * when it renders the row this sits beside: two is one late upload. */
  var SILENT_AFTER = 3;

  var TICK_MS = 1000;

  var state = {
    connected: false,
    /* Unix seconds of the last update seen anywhere on the page. */
    lastAny: 0,
    /* Per card: when it last changed. Keyed on the place AND the reading --
     * see `keyOf`. */
    cards: new Map(),
    /* Per place: when anything of its arrived. `""` is a document with no
     * places in it, which is every single-place site. */
    places: new Map(),
    /* The places whose readings arrived in units this page is not written
     * in. Their values are deliberately not written, so they need their own
     * word rather than the one for silence. */
    wrong: new Set(),
    /* Per place: how far apart its readings arrive, in seconds, as the core
     * measured it. Empty until a document carries `_every` -- which no
     * single-place document does, so nothing on those pages moves. */
    rhythm: new Map(),
    /* Whether the poller has spoken. It carries each slice's own timestamp;
     * the observer below has only the clock. */
    polled: false,
    startedAt: now()
  };

  function now() {
    return Math.floor(Date.now() / 1000);
  }

  /* How long this place's readings stay green.
   *
   * Its own measured spacing where the document carried one, three of them
   * -- exactly the judgement the renderer already made about the row and
   * the badge beside it. A sixteen-second console and a five-minute console
   * stand on the same site, and one threshold for both either lets the fast
   * one die quietly or calls the slow one late every time; worse, it makes
   * the browser say something different from what the server printed a
   * second earlier, which is the `chartdata.py` fault one storey up and
   * visible on one screen.
   *
   * The flat window where no spacing arrived, and that is not a corner: the
   * top level of `live.json` carries no `_every`, so every single-place
   * page keeps the one window it has always had. */
  function freshWindow(name) {
    var every = state.rhythm.get(name);
    return every ? every * SILENT_AFTER : FRESH_SECONDS;
  }

  function text(key, fallback) {
    /* The skin's own translations, where the page provided them. Falls back
     * to English rather than to an empty string: a missing translation must
     * not produce a badge with no word in it. */
    var strings = window.deckLiveStrings || {};
    return strings[key] || fallback;
  }

  /* -- the cards ---------------------------------------------------------- */

  /* Everything a live value lands in: the tiles and the board's cells, which
   * carry the same `.stat-title-obs-value > .raw` inside. */
  function cards() {
    return document.querySelectorAll(
      ".card.stat-tile[data-observation], .board-cell[data-observation]");
  }

  /* The ones that carry a badge, which is the tiles and only the tiles. The
   * board says how old a row is once, in its own `.board-age` cell: thirty
   * badges on one screen is not a warning, and a badge inside a cell would
   * put something this file writes inside the subtree the observer below
   * watches -- paint -> mutation -> paint, which is a tab that stops
   * responding within a second of loading. */
  function tiles() {
    return document.querySelectorAll(".card.stat-tile[data-observation]");
  }

  /* A place and a reading, not a reading. A temperature tile for one place
   * and a temperature cell for another are different things and always were:
   * keyed on the observation alone, one console's push marked the other
   * console's card fresh -- which is exactly the failure these badges exist
   * to show. */
  function keyOf(card) {
    return (card.getAttribute("data-archive") || "") + "\u001f" +
           card.getAttribute("data-observation");
  }

  function badgeFor(card) {
    var badge = card.querySelector(".live-badge");
    if (badge) {
      return badge;
    }
    badge = document.createElement("span");
    badge.className = "live-badge";
    /* Announced to a screen reader as a status rather than read out in the
     * middle of the value it sits beside. */
    badge.setAttribute("role", "status");
    /* Beside the card's own label, and specifically NOT inside
     * `.stat-title-obs-value`. That element is what the MutationObserver
     * below watches, so a badge in it makes every paint a mutation and every
     * mutation a paint: the tab stops responding within a second of loading,
     * and every card reads permanently live because the badge's own change
     * counts as a reading arriving. */
    var host = card.querySelector(".label") || card;
    host.appendChild(badge);
    return badge;
  }

  function write(element, className, label, title) {
    /* Only when it differs. Setting textContent to the same string still
     * replaces the text node, and a mutation the observer has to look at
     * every second is a cost for nothing. */
    if (element.className !== className) {
      element.className = className;
    }
    if (element.textContent !== label) {
      element.textContent = label;
    }
    if (element.title !== title) {
      element.title = title;
    }
  }

  function paint() {
    var seconds = now();
    var settling = seconds - state.startedAt < GRACE_SECONDS;

    tiles().forEach(function (card) {
      var when = state.cards.get(keyOf(card)) || 0;
      var badge = badgeFor(card);
      var live = state.connected && when > 0 &&
        seconds - when < freshWindow(card.getAttribute("data-archive") || "");

      if (state.wrong.has(card.getAttribute("data-archive") || "")) {
        /* Its own state, and its own words. "Wrong unit" and "nothing
         * arriving" are different things to do about, and one text in one
         * colour for both is the warning that stands everywhere and is
         * therefore not one. */
        write(badge, "live-badge live-badge--wrong",
              text("wrongUnit", "UNIT"),
              text("wrongUnits",
                   "This console reports in other units than the page is "
                   + "written in."));
      } else if (live) {
        write(badge, "live-badge live-badge--live", text("live", "LIVE"),
              text("liveSince", "Updated") + " " + ago(seconds - when));
      } else if (!state.connected) {
        write(badge, "live-badge live-badge--off", text("offline", "OFFLINE"),
              text("noBroker", "No connection to the live feed."));
      } else if (when === 0 && settling) {
        /* Connected, nothing yet, and it is early. Neither claim is true, so
         * neither is made. */
        write(badge, "live-badge live-badge--waiting", text("waiting", "…"),
              text("waitingFor", "Waiting for the first reading."));
      } else {
        write(badge, "live-badge live-badge--stale", text("stale", "LIVE"),
              when === 0
                ? text("neverSent",
                       "The station does not publish this reading live.")
                : text("lastSeen", "Last live reading") + " "
                  + ago(seconds - when));
      }
    });

    paintRowAges(seconds);
    paintIndicator(seconds);
  }

  /* -- the board's per-row age --------------------------------------- */

  /* One age per row, in words, from that place's own last reading. The
   * renderer already wrote the age of the newest archive record into this
   * cell, so a place nothing has arrived for is left exactly as it was --
   * "vor 3 h" for a silent console and "noch keine Messwerte" for one that
   * has never reported are different sentences, and overwriting either with
   * a guess loses the difference. */
  function paintRowAges(seconds) {
    document.querySelectorAll(".board-age[data-archive]").forEach(function (cell) {
      var name = cell.getAttribute("data-archive");
      var when = state.places.get(name) || 0;
      if (!when) {
        /* Never heard from at all: the renderer said "no readings yet", and
         * that is still true, so it is left exactly as written.
         *
         * A place that HAS records and is merely absent from the document is
         * a different thing, and leaving it alone froze the age the page was
         * rendered with: a row reading "just now" beside a header counting
         * it as not live. Two claims on one screen and the reassuring one
         * wrong. Dated from the render instead, so it ages like the rest.
         * Reachable through the document's size limit, through a split
         * deployment, and on a page left open past the live table's
         * retention. */
        var since = parseInt(cell.getAttribute("data-since"), 10);
        if (!since) { return; }
        when = since;
      }
      var age = seconds - when;
      /* `write` only touches the DOM when the string differs, so the
       * one-second tick over eight rows costs nothing. */
      write(cell, cell.className, ago(age), cell.title);
      /* The same two thresholds the renderer used: amber past one of this
       * place's own spacings, red past three. One state at a time, as the
       * server writes it -- red covers amber.
       *
       * The *spacing* is deliberately not the same number, because the two
       * ages are not the same quantity. The renderer dates this row from
       * the last archive RECORD and judges it against that archive's own
       * interval; here it is dated from the last live PACKET and judged
       * against how often this place's consoles send. A station archiving
       * every five minutes and sending every sixteen seconds is healthy on
       * both readings and dead on both within a minute of stopping -- which
       * is the whole reason for polling at all. Judging packet-age by the
       * archive interval would take fifteen minutes to notice; judging
       * record-age by the packet rhythm would call every healthy station
       * late. */
      var every = state.rhythm.get(name);
      if (!every) {
        /* Nothing could be measured for this place -- too few packets yet,
         * or a split deployment where this process cannot see the live
         * table. The renderer DID judge this row, against that archive's
         * own interval, and wrote its answer into the attributes, so
         * overwriting it with a flat window replaces a measurement with a
         * guess.
         *
         * It did exactly that: `silent` could never become true here and
         * the attribute was cleared unconditionally, so a console dead for
         * a day went from the renderer's red to amber on the first poll.
         * The one state that says "this station has stopped" was
         * unreachable in a browser. The age above still ticks; the
         * judgement stays the renderer's. */
        return;
      }
      var silent = age > every * SILENT_AFTER;
      var stale = !silent && age > every;
      /* Same discipline as `write`: only when the answer changed. */
      if (cell.hasAttribute("data-stale") !== stale) {
        cell.toggleAttribute("data-stale", stale);
      }
      /* Something arrived, so this row's age is now a measured one --
       * including when it is old. Cleared unconditionally, the red on a
       * console that stopped three days ago went away the moment a stale
       * slice for it turned up. */
      if (cell.hasAttribute("data-silent") !== silent) {
        cell.toggleAttribute("data-silent", silent);
      }
    });
  }

  /* -- the indicator in the header ---------------------------------------- */

  function indicator() {
    return document.getElementById("live-indicator");
  }

  function paintIndicator(seconds) {
    var element = indicator();
    if (!element) {
      return;
    }
    var dot = element.querySelector(".live-indicator__dot");
    var label = element.querySelector(".live-indicator__label");
    if (!dot || !label) {
      return;
    }

    if (!state.connected) {
      write(label, label.className, text("offline", "OFFLINE"), label.title);
      element.className = "live-indicator live-indicator--off";
      element.title = text("noBroker", "No connection to the live feed.");
      return;
    }
    if (!state.lastAny) {
      write(label, label.className, text("connecting", "connecting"),
            label.title);
      element.className = "live-indicator live-indicator--waiting";
      element.title = text("waitingFor", "Waiting for the first reading.");
      return;
    }

    /* On a page with places on it the question is how many of them are
     * reporting, not how long ago the most recent one did. "OFFLINE" on a
     * site where three of four consoles are fine is a lie, and this is the
     * one badge everybody looks at. */
    var places = placesOnPage();
    if (places.length) {
      var quiet = [];
      var mismatched = [];
      places.forEach(function (one) {
        /* Reporting, in units this page is not written in. Not the same
         * thing as silence and not the same thing to do about it, so it is
         * counted apart and said in its own words. */
        if (state.wrong.has(one.name)) {
          mismatched.push(one.label);
          return;
        }
        var when = state.places.get(one.name) || 0;
        if (!when || seconds - when >= freshWindow(one.name)) {
          quiet.push(one.label);
        }
      });
      var live = places.length - quiet.length - mismatched.length;
      element.className =
        "live-indicator " +
        (live === places.length ? "live-indicator--live"
         : live ? "live-indicator--stale" : "live-indicator--off");
      write(label, label.className,
            live + " " + text("ofPlaces", "of") + " " + places.length + " " +
            text("placesLive", "live"), label.title);
      var says = [];
      if (quiet.length) {
        says.push(text("placesSilent", "Nothing arriving from") + " " +
                  quiet.join(", "));
      }
      if (mismatched.length) {
        says.push(text("placesWrongUnit", "Wrong units from") + " " +
                  mismatched.join(", "));
      }
      element.title = says.length
        ? says.join(" · ")
        : text("liveSince", "Updated") + " " + ago(seconds - state.lastAny);
      return;
    }

    var age = seconds - state.lastAny;
    element.className =
      "live-indicator " +
      (age < FRESH_SECONDS ? "live-indicator--live" : "live-indicator--stale");
    write(label, label.className, ago(age), label.title);
    element.title =
      text("liveSince", "Updated") +
      " " +
      ago(age) +
      " (" +
      new Date(state.lastAny * 1000).toLocaleTimeString() +
      ")";
  }

  /* Which places this indicator has to speak for, with their names as the
   * reader sees them.
   *
   * Only on a page that shows several places at once -- the board's rows, or
   * a comparison page's chips. On one place's own page the question is
   * whether THIS page's readings are live, and the single clock below
   * already answers it; a count there would be about consoles the reader is
   * not looking at.
   *
   * **Every place the page was rendered with, and none of them left out.**
   * This used to drop a row the renderer had marked `data-silent`, on the
   * reading that the attribute meant "has never written a record --
   * unconfigured, not silent". It does not mean that: `now-board.inc`
   * writes it for `silent` AND for `never`, and `silent` is a console that
   * HAS records and has stopped -- which is precisely the place this
   * indicator exists to report. Three rows on screen, one of them red, and
   * the badge everybody looks at read "2 of 2 live" in green. A place that
   * was never plugged in is quiet too, and it is named in the title, which
   * is the smaller of the two wrongs by a distance.
   *
   * Nothing here is read out of the DOM any more, and that is the second
   * half of the same fix. The answer was cached on the belief that the
   * first call came before any push. It does not: `paintIndicator` returns
   * at `!state.connected` long before it reaches here, and that only turns
   * true inside the `deck:live` handler -- so the first call was inside the
   * FIRST push's `paint()`, after `paintRowAges` had already cleared
   * `data-silent` from every place that push carried. A place missing from
   * the first document was then excluded for the life of the page, and a
   * console that came back was invisible until somebody reloaded.
   * `deckConfig.places` is written once by the renderer and cannot change,
   * so it can be cached with none of that behind it. */
  var roster = null;

  function placesOnPage() {
    if (roster) {
      return roster;
    }
    roster = [];
    if (!document.querySelector(".board-age[data-archive], [data-place-toggle]")) {
      return roster;
    }
    var said = (window.deckConfig && window.deckConfig.places) || [];
    said.forEach(function (one) {
      /* The label, not the name: the name is a URL segment and the reader
       * has never seen it. */
      if (one && one.name) {
        roster.push({ name: one.name, label: one.label || one.name });
      }
    });
    return roster;
  }

  function ago(seconds) {
    /* Said the way a person would. Exact seconds past a minute is precision
     * nobody asked for on a reading that arrives every five. */
    if (seconds < 5) {
      return text("justNow", "just now");
    }
    if (seconds < 60) {
      return Math.floor(seconds) + " " + text("secondsAgo", "s ago");
    }
    if (seconds < 3600) {
      return Math.floor(seconds / 60) + " " + text("minutesAgo", "min ago");
    }
    if (seconds < 86400) {
      return Math.floor(seconds / 3600) + " " + text("hoursAgo", "h ago");
    }
    return Math.floor(seconds / 86400) + " " + text("daysAgo", "d ago");
  }

  /* -- watching ----------------------------------------------------------- */

  function watchCards() {
    var observer = new MutationObserver(function (records) {
      var seconds = now();
      var touched = false;
      records.forEach(function (record) {
        var node = record.target;
        var element = node.closest ? node : node.parentElement;
        if (!element) {
          return;
        }
        /* Our own badge is not a reading arriving. It is kept off this
         * subtree as well (see `badgeFor`), and this is the second lock on
         * the same door: paint -> mutation -> paint is a tab that stops
         * responding, and it is not obvious from either end alone. */
        if (element.closest(".live-badge")) {
          return;
        }
        var card = element.closest(
          ".card.stat-tile[data-observation], .board-cell[data-observation]");
        if (!card) {
          return;
        }
        state.cards.set(keyOf(card), seconds);
        /* Whatever wrote into this card said its place is alive, which is
         * what keeps the badges working for a skin fed some other way. Only
         * until the poller speaks, though: it has the reading's own
         * timestamp, and this callback is a microtask that lands AFTER the
         * event that carried it -- so `now()` here would overwrite a real
         * age with zero, every time, and every row would read "just now"
         * however old its reading was. */
        if (!state.polled) {
          state.places.set(card.getAttribute("data-archive") || "", seconds);
        }
        touched = true;
      });
      if (touched) {
        state.lastAny = seconds;
        paint();
      }
    });

    cards().forEach(function (card) {
      var host = card.querySelector(".stat-title-obs-value");
      if (host) {
        observer.observe(host, {
          childList: true,
          characterData: true,
          subtree: true
        });
      }
    });
  }

  function watchPolling() {
    /* `live-poll.js` says so when it has applied a file, because a poll that
     * finds an unchanged value produces no mutation to observe -- and a
     * reading that has not moved is still a fresh reading. Without this a
     * calm afternoon turns every badge red. */
    document.addEventListener("deck:live", function (event) {
      var seconds = now();
      var detail = (event && event.detail) || {};
      /* Only the places the document actually carried a slice for. Marking
       * every card on the page fresh on any push is what hid the failure
       * these badges exist for: one console silent, seven fine, and every
       * board row green. */
      var alive = detail.archives || {};
      state.connected = true;
      state.polled = true;
      state.lastAny = seconds;
      state.wrong = new Set(detail.wrong || []);
      cards().forEach(function (card) {
        var whose = card.getAttribute("data-archive") || "";
        if (!(whose in alive)) {
          return;
        }
        state.cards.set(keyOf(card), seconds);
      });
      for (var name in alive) {
        /* The slice's own timestamp, not the moment the file was read. A
         * console that stopped an hour ago wrote its last reading an hour
         * ago, and the file being fresh says nothing about that. */
        state.places.set(name, alive[name]);
      }
      /* Kept apart from `alive`, because it outlives it: a place whose
       * units disagree carries no timestamp there, and a place that stops
       * carries no slice at all -- but the window its last reading is
       * judged against is the one it has always reported at. */
      var beats = detail.rhythm || {};
      for (var each in beats) {
        state.rhythm.set(each, beats[each]);
      }
      paint();
    });
  }

  function start() {
    if (!cards().length) {
      /* Not the page with the cards on it. The header indicator is still
       * worth having, so this carries on rather than returning. */
      paintIndicator(now());
    }
    watchPolling();
    watchCards();
    paint();
    /* A card goes stale by the clock, not by an event, so something has to
     * be looking. One second is cheap and makes "just now" mean it. */
    window.setInterval(function () {
      paint();
    }, TICK_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();

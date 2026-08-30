/* Live readings without a broker: read the file the station pushed.
 *
 * The other half of `live.php`. The station POSTs its current readings there
 * every few seconds and it writes them beside itself as `live.json`; this
 * reads that file and puts the numbers into the page.
 *
 * ## Why this exists next to live-updates.js
 *
 * That one takes MQTT over websockets, which needs a broker at the station,
 * a port forwarded through the router and a certificate -- because a page
 * served over https cannot open an unencrypted websocket. On a site
 * published to shared hosting that is three things to get right on somebody
 * else's network.
 *
 * This needs none of them. The file is served by the same web server as the
 * page, over the same https, from the same origin. Nothing is opened
 * anywhere.
 *
 * What it gives up is push: the page polls, so a reading is as fresh as the
 * interval. Ten seconds against an archive record's five minutes.
 *
 * ## Only when there is no broker
 *
 * If `live-updates.js` is on the page, it is doing this job better and this
 * one stays out of the way. Both writing the same values would double every
 * update and make the live badges flicker between them.
 */

(function () {
  "use strict";

  /* Same names as the MQTT document -- `outTemp_C`, `windSpeed_mph` -- so a
   * card is found the same way whichever path is feeding it. */
  var SOURCE = (window.deckLivePoll && window.deckLivePoll.url) || "live.json";
  var EVERY = ((window.deckLivePoll && window.deckLivePoll.every) || 15) * 1000;

  /* Give up after this many consecutive failures and fall back to polling
   * slowly. A file that is not there is not going to appear because we asked
   * a hundred more times, and a page left open overnight should not spend it
   * making requests that 404. */
  var PATIENCE = 5;
  var SLOW = 300000;

  var failures = 0;
  var timer = null;

  /* Both markups, one loop. A board cell carries the same
   * `.stat-title-obs-value > .raw` inside it as a stat tile, so nothing
   * below this line has to know which of the two it is looking at. */
  function cards() {
    return document.querySelectorAll(
      ".card.stat-tile[data-observation], .board-cell[data-observation]");
  }

  /* Which slice of the document this card reads.
   *
   * No `data-archive` means the top level, which is every card on every
   * single-place site and is why those pages did not have to change.
   *
   * A card that NAMES a place and finds no slice for it is left ALONE --
   * never falling back to the top level. That is a different place's
   * readings, and publishing Kirchdorf's temperature in Nordfeld's row is
   * the one outcome worse than a stale value: it is wrong and it looks
   * live. */
  function sliceFor(data, card) {
    var name = card.getAttribute("data-archive");
    if (!name) {
      return data;
    }
    var all = data.archives;
    return (all && all[name]) || null;
  }

  /* The units the page was rendered in, against the units this slice arrived
   * in. They disagree when a console sends Fahrenheit to a page written in
   * Celsius -- and the number, shown with the page's own suffix, would then
   * be silently, plausibly wrong by thirty degrees. So it is not written at
   * all, and the card says so instead, which is a state somebody can see and
   * act on.
   *
   * Skipped when either side does not say: an unnamed system is not a
   * mismatch, and inventing one would be a red badge on a healthy site.
   *
   * Case-folded on both sides. The page writes `metricwx` and the document
   * is written from the same table that spells it METRICWX; comparing them
   * as typed made every slice a mismatch, so no value was ever written and
   * every badge went red on a healthy site. An agreement that holds only
   * because both ends happen to choose the same case is one that breaks the
   * next time either end is touched. */
  function unitsAgree(slice) {
    var page = document.body.getAttribute("data-units");
    var sent = slice.unit_system;
    return !page || !sent ||
      String(page).toLowerCase() === String(sent).toLowerCase();
  }

  function decimals(card) {
    var said = card.getAttribute("data-rounding");
    var places = parseInt(said, 10);
    return isNaN(places) ? 1 : places;
  }

  /* What the skin printed after the number -- " mbar", " °C", " %". Learned
   * from the rendered page rather than rebuilt from `data-unit`, because the
   * skin decides the spacing and the wording and this way it keeps deciding
   * them.
   *
   * Learned once, on the first sight of a card. After that the element holds
   * only what this wrote, so reading it again would learn the empty string --
   * which is the bug this comment is here to stop coming back. Every unit on
   * the page vanished the moment the first reading arrived. */
  function suffixOf(card, element) {
    var known = element.getAttribute("data-live-suffix");
    if (known !== null) {
      return known;
    }
    var printed = element.textContent.trim();
    /* The number, then whatever follows it. A card showing N/A has no number
     * and therefore nothing to learn; `data-unit` is the fallback, and an
     * empty one leaves the value bare, which is what it was. */
    var found = printed.match(/^[-+]?[\d.,]+\s*(.*)$/);
    var suffix = found && found[1] ? " " + found[1].trim() : "";
    if (!suffix) {
      var unit = card.getAttribute("data-unit");
      suffix = unit ? " " + unit : "";
    }
    element.setAttribute("data-live-suffix", suffix);
    return suffix;
  }

  function apply(data) {
    /* The reading's own timestamp, not when the file was written. A station
     * that stopped an hour ago wrote its last reading an hour ago, and the
     * file being fresh says nothing about that. */
    var stamp = data.dateTime;

    /* One entry per place, because one document-level timestamp cannot
     * describe a site where one console is alive and one is dead. The key is
     * the place's name, and `""` is the top level -- which is the whole
     * document on every single-place site. */
    var seen = {};
    /* The places whose slice arrived in units the page is not written in.
     * Kept apart from `seen`: they are reporting, so "nothing arriving" is
     * the wrong thing to say, and stamping them fresh would put a LIVE badge
     * on a number that was never written. */
    var wrong = [];

    /* How often each place reports, as the core measured it (`_every`).
     * How long a reading stays fresh cannot be one number for a whole site:
     * a console pushing every sixteen seconds and one pushing every five
     * minutes stand on the same board, and a single threshold either lets
     * the fast one die quietly or calls the slow one late every time. The
     * renderer already judged each row that way (`tags.place_age`), so a
     * browser judging it by a flat number a second later is two answers to
     * one question, side by side on one screen. Absent from a document that
     * carries no places, which is every single-place site -- and there the
     * flat window stays exactly what it was. */
    var rhythm = {};

    var slices = {};
    if (data.archives && typeof data.archives === "object") {
      for (var name in data.archives) {
        slices[name] = data.archives[name];
      }
    } else {
      slices[""] = data;
    }
    for (var each in slices) {
      if (!unitsAgree(slices[each])) {
        wrong.push(each);
      } else if (slices[each].dateTime) {
        /* Each slice's own timestamp. Taken here rather than from the cards,
         * so a place that reports a reading this page has no card for still
         * counts as alive on the board. */
        seen[each] = slices[each].dateTime;
      }
      /* Taken even from a slice whose units disagree: its readings are not
       * written, but its row still has to say how old they are. */
      if (slices[each]._every) {
        rhythm[each] = slices[each]._every;
      }
    }

    cards().forEach(function (card) {
      var key = card.getAttribute("data-observation");
      if (!key) {
        return;
      }
      var slice = sliceFor(data, card);
      if (!slice || !unitsAgree(slice)) {
        return;
      }
      /* The document carries `outTemp_C`; the card carries `outTemp`. Match
       * on the prefix so the unit suffix does not have to be worked out
       * here -- the station decides it and the page follows. */
      var value = pick(slice, key);
      if (value === undefined || value === null) {
        return;
      }
      var target = card.querySelector(".stat-title-obs-value .raw");
      if (!target) {
        return;
      }
      /* `.raw-sum` holds a day total -- `$day.rain.sum`, under a caption
       * that says "Total". The document carries the current packet, which
       * is a different quantity: written over it, a column that read
       * 7.4 mm reads 0.2 and then 0.0, so a wet afternoon publishes as a
       * dry one under a heading that is still correct.
       *
       * Everywhere, not only on the board. Guarded on the board alone, one
       * site printed 7.4 mm on its overview and 0.2 mm on the place page
       * beside it, for the same place at the same instant -- two answers to
       * one question, which is the fault this codebase treats as cardinal.
       * The stat tile has done this since before there were places, so a
       * one-place page's rain total changes here, once, from wrong to
       * right. That is a change worth naming rather than one worth
       * preserving. */
      if (target.classList.contains("raw-sum")) {
        return;
      }
      var shown = (typeof value === "number"
        ? value.toFixed(decimals(card))
        : String(value)) + suffixOf(card, target);
      /* Written even when it has not changed, and deliberately:
       * `live-status.js` watches for the change to decide whether a card is
       * live, and a value that happens not to have moved is still a fresh
       * reading. Setting the same text still fires the observer. */
      target.textContent = shown;
      /* A card reading the top level of a document that also carries places:
       * its slice is alive, and nothing above put it in `seen`. */
      var whose = card.getAttribute("data-archive") || "";
      if (!(whose in seen) && slice.dateTime) {
        seen[whose] = slice.dateTime;
      }
    });

    if (stamp || Object.keys(seen).length || wrong.length) {
      /* One custom event rather than reaching into the badge code: the two
       * files then know nothing about each other beyond this name. */
      document.dispatchEvent(new CustomEvent("deck:live", {
        detail: {
          dateTime: stamp,
          received: data._received,
          archives: seen,
          wrong: wrong,
          rhythm: rhythm
        }
      }));
    }
  }

  function pick(data, key) {
    if (key in data) {
      return data[key];
    }
    /* `outTemp` against `outTemp_C`. Anchored on the underscore so
     * `outTemp` does not match `outTempMax`. */
    var prefix = key + "_";
    for (var name in data) {
      if (name.indexOf(prefix) === 0) {
        return data[name];
      }
    }
    return undefined;
  }

  function poll() {
    fetch(SOURCE, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error(String(response.status));
        }
        return response.json();
      })
      .then(function (data) {
        failures = 0;
        apply(data);
      })
      .catch(function (why) {
        failures += 1;
        if (failures === PATIENCE) {
          /* Said once, then the interval widens. A console filling with the
           * same line every ten seconds is a console nobody reads. */
          console.info(
            "deck: no live data at " + SOURCE + " (" + why.message + "). " +
            "Checking every five minutes from now on. If the station is " +
            "meant to push here, look at live.php and its token."
          );
          restart(SLOW);
        }
      });
  }

  function restart(every) {
    if (timer !== null) {
      window.clearInterval(timer);
    }
    timer = window.setInterval(poll, every);
  }

  function start() {
    /* MQTT is doing this job better where it is configured. Both writing the
     * same values would double every update and make the badges flicker. */
    if (window.deckLiveMqtt) {
      return;
    }
    poll();
    restart(EVERY);

    /* A background tab does not need to be current, and a phone should not
     * spend its battery on one. Polled again the moment it comes back, so
     * what is on screen is never stale. */
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        if (timer !== null) {
          window.clearInterval(timer);
          timer = null;
        }
      } else {
        poll();
        restart(failures >= PATIENCE ? SLOW : EVERY);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();

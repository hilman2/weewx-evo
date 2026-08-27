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

  function cards() {
    return document.querySelectorAll(".card.stat-tile[data-observation]");
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

    cards().forEach(function (card) {
      var key = card.getAttribute("data-observation");
      if (!key) {
        return;
      }
      /* The document carries `outTemp_C`; the card carries `outTemp`. Match
       * on the prefix so the unit suffix does not have to be worked out
       * here -- the station decides it and the page follows. */
      var value = pick(data, key);
      if (value === undefined || value === null) {
        return;
      }
      var target = card.querySelector(".stat-title-obs-value .raw");
      if (!target) {
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
    });

    if (stamp) {
      /* One custom event rather than reaching into the badge code: the two
       * files then know nothing about each other beyond this name. */
      document.dispatchEvent(new CustomEvent("deck:live", {
        detail: { dateTime: stamp, received: data._received }
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

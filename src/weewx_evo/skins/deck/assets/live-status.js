/* Whether a reading is actually live, and how old it is.
 *
 * `live-updates.js` takes the MQTT feed and rewrites the values in place as
 * packets arrive. What it does not do is say so: a page with a working broker
 * and a page with one that went away ten minutes ago look identical, and a
 * number that is four hours old looks exactly like one from ten seconds ago.
 *
 * That is the failure this file exists for. A dashboard that is quietly wrong
 * is worse than one that is visibly stale.
 *
 * ## Why a MutationObserver and not a second MQTT client
 *
 * The obvious approach is to open our own connection and listen along. It is
 * also wrong: two clients means two subscriptions, two sets of credentials in
 * the page, and a second client id -- and two clients sharing an id take turns
 * kicking each other off the broker, which looks like a flapping network.
 *
 * So this watches the DOM instead. `live-updates.js` is the one asset here
 * that is still a minified bundle (MQTT.js and dayjs), so reaching into its
 * internals would break the next time it is rebuilt. What it changed in the
 * page is a fact that survives that, and "this card changed" is exactly what
 * "this card is live" means.
 *
 * ## What the colours mean
 *
 *   green   this card was updated within FRESH_SECONDS
 *   red     it was not -- either the broker is gone, or this reading is not
 *           in the topic the station publishes
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

  var TICK_MS = 1000;

  var state = {
    connected: false,
    /* Unix seconds of the last update seen anywhere on the page. */
    lastAny: 0,
    /* Per card: when it last changed. */
    cards: new Map(),
    startedAt: now()
  };

  function now() {
    return Math.floor(Date.now() / 1000);
  }

  function text(key, fallback) {
    /* The skin's own translations, where the page provided them. Falls back
     * to English rather than to an empty string: a missing translation must
     * not produce a badge with no word in it. */
    var strings = window.deckLiveStrings || {};
    return strings[key] || fallback;
  }

  /* -- the cards ---------------------------------------------------------- */

  function cards() {
    return document.querySelectorAll(".card.stat-tile[data-observation]");
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
    var host = card.querySelector(".stat-title-obs-value") || card;
    host.appendChild(badge);
    return badge;
  }

  function paint() {
    var seconds = now();
    var settling = seconds - state.startedAt < GRACE_SECONDS;

    cards().forEach(function (card) {
      var key = card.getAttribute("data-observation");
      var when = state.cards.get(key) || 0;
      var badge = badgeFor(card);
      var live = state.connected && when > 0 && seconds - when < FRESH_SECONDS;

      if (live) {
        badge.className = "live-badge live-badge--live";
        badge.textContent = text("live", "LIVE");
        badge.title = text("liveSince", "Updated") + " " + ago(seconds - when);
      } else if (!state.connected) {
        badge.className = "live-badge live-badge--off";
        badge.textContent = text("offline", "OFFLINE");
        badge.title = text("noBroker", "No connection to the live feed.");
      } else if (when === 0 && settling) {
        /* Connected, nothing yet, and it is early. Neither claim is true, so
         * neither is made. */
        badge.className = "live-badge live-badge--waiting";
        badge.textContent = text("waiting", "…");
        badge.title = text("waitingFor", "Waiting for the first reading.");
      } else {
        badge.className = "live-badge live-badge--stale";
        badge.textContent = text("stale", "LIVE");
        badge.title =
          when === 0
            ? text("neverSent", "The station does not publish this reading live.")
            : text("lastSeen", "Last live reading") + " " + ago(seconds - when);
      }
    });

    paintIndicator(seconds);
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
      element.className = "live-indicator live-indicator--off";
      label.textContent = text("offline", "OFFLINE");
      element.title = text("noBroker", "No connection to the live feed.");
      return;
    }
    if (!state.lastAny) {
      element.className = "live-indicator live-indicator--waiting";
      label.textContent = text("connecting", "connecting");
      element.title = text("waitingFor", "Waiting for the first reading.");
      return;
    }

    var age = seconds - state.lastAny;
    element.className =
      "live-indicator " +
      (age < FRESH_SECONDS ? "live-indicator--live" : "live-indicator--stale");
    label.textContent = ago(age);
    element.title =
      text("liveSince", "Updated") +
      " " +
      ago(age) +
      " (" +
      new Date(state.lastAny * 1000).toLocaleTimeString() +
      ")";
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
        var card = node.closest
          ? node.closest(".card.stat-tile[data-observation]")
          : null;
        if (!card && node.parentElement) {
          /* A characterData mutation reports the text node, which has no
           * `closest` of its own. */
          card = node.parentElement.closest(
            ".card.stat-tile[data-observation]"
          );
        }
        if (!card) {
          return;
        }
        state.cards.set(card.getAttribute("data-observation"), seconds);
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

  function watchConnection() {
    /* The bundle shows its own notification when the socket opens and hides
     * it when it closes. That element is the only thing it exposes, so it is
     * what the connected state is read from -- rather than reaching into the
     * bundle's internals, which would break the next time it is rebuilt. */
    var container = document.getElementById("notification-container-mqtt");
    if (!container) {
      return;
    }
    var read = function () {
      var visible =
        container.style.display !== "none" &&
        !container.hidden &&
        container.offsetParent !== null;
      if (visible !== state.connected) {
        state.connected = visible;
        paint();
      }
    };
    new MutationObserver(read).observe(container, {
      attributes: true,
      attributeFilter: ["style", "class", "hidden"]
    });
    read();
  }

  function start() {
    if (!cards().length) {
      /* Not the page with the cards on it. The header indicator is still
       * worth having, so this carries on rather than returning. */
      paintIndicator(now());
    }
    watchConnection();
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

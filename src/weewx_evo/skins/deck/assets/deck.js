/* Deck — the page's own behaviour.
 *
 * What this replaces: twenty-one <script type="module"> tags pointing at
 * IBM's CDN, pulling five different versions of the same web components.
 * Two of those versions defined `bx-tooltip`, the second one lost, and the
 * console said "Attempting to re-define bx-tooltip" on every page.
 *
 * Everything a Carbon component did here is one of five things: a theme
 * switch, an off-canvas menu, tabs, sortable columns, a dialog. Each is
 * twenty lines of the platform, and the platform ships in every browser.
 *
 * No framework, no build step, no bundle. This file is the file that runs.
 */
(function () {
  "use strict";

  var THEME_KEY = "weewx_evo.deck.color-theme";
  var config = window.deckConfig || {};

  /* ------------------------------------------------------------- theme */

  /* Applied in <head> before the page paints -- see the inline snippet in
   * html-head.inc. This half only handles the switch afterwards. */
  function currentTheme() {
    var chosen = document.documentElement.getAttribute("data-theme");
    if (chosen) return chosen;
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }

  function setTheme(name) {
    document.documentElement.setAttribute("data-theme", name);
    try { localStorage.setItem(THEME_KEY, name); } catch (e) { /* private mode */ }
    // The charts read the tokens once, at build time, so they have to be
    // told. Anything that draws listens for this.
    window.dispatchEvent(new CustomEvent("deck:themechange", { detail: name }));
  }

  function wireTheme() {
    var button = document.querySelector("[data-theme-toggle]");
    if (!button) return;
    button.addEventListener("click", function () {
      setTheme(currentTheme() === "dark" ? "light" : "dark");
    });

    // Somebody who never pressed the button follows their system. When it
    // changes under them, the page should follow too.
    var system = window.matchMedia("(prefers-color-scheme: dark)");
    var onChange = function () {
      var stored = null;
      try { stored = localStorage.getItem(THEME_KEY); } catch (e) { /* ignore */ }
      if (!stored) {
        window.dispatchEvent(new CustomEvent("deck:themechange", {
          detail: system.matches ? "dark" : "light",
        }));
      }
    };
    if (system.addEventListener) system.addEventListener("change", onChange);
    else if (system.addListener) system.addListener(onChange);
  }

  /* -------------------------------------------------------------- menu */

  function wireMenu() {
    var button = document.querySelector("[data-menu-toggle]");
    var nav = document.querySelector(".sidenav");
    var scrim = document.querySelector(".scrim");
    if (!button || !nav) return;

    function open(yes) {
      nav.toggleAttribute("data-open", yes);
      if (scrim) scrim.toggleAttribute("data-open", yes);
      button.setAttribute("aria-expanded", yes ? "true" : "false");
      // Off-screen links must be out of the tab order as well, or the
      // focus ring walks into a panel nobody can see.
      if (window.matchMedia("(max-width: 64rem)").matches) {
        nav.toggleAttribute("inert", !yes);
      }
    }

    button.addEventListener("click", function () {
      open(!nav.hasAttribute("data-open"));
    });
    if (scrim) scrim.addEventListener("click", function () { open(false); });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.hasAttribute("data-open")) open(false);
    });

    // Crossing the breakpoint with the panel open would otherwise leave a
    // desktop sidebar marked inert.
    var wide = window.matchMedia("(min-width: 64.001rem)");
    var onWide = function () {
      if (wide.matches) { nav.removeAttribute("inert"); open(false); }
      else if (!nav.hasAttribute("data-open")) nav.setAttribute("inert", "");
    };
    if (wide.addEventListener) wide.addEventListener("change", onWide);
    onWide();
  }

  /* ------------------------------------------------------------- units */

  /* Which unit system somebody chose, kept for next time.
   *
   * The two sets of pages are separate files, so the choice cannot live in
   * the page. It lives in the browser, and a reader who picked Fahrenheit
   * once gets it when they come back -- including when they come back to the
   * address the metric set is published at, which is the one that ends up in
   * a link somebody sent them.
   *
   * Every read and write is guarded: a private window, a browser told to
   * block site data, and a thumbnailer all throw rather than return
   * nothing, and none of them is a reason for the page not to render. */
  var UNITS_KEY = "deck-units";

  function unitsRemembered() {
    try {
      return window.localStorage.getItem(UNITS_KEY);
    } catch (e) {
      return null;
    }
  }

  function rememberUnits(which) {
    try {
      window.localStorage.setItem(UNITS_KEY, which);
    } catch (e) {
      /* Nothing to do about it, and nothing worth saying: the switch still
       * works, it just will not be remembered. */
    }
  }

  /* The same page in the other set, not the other set's front page.
   *
   * Somebody switching units while reading the month page means "this, in
   * Fahrenheit". Sending them to the front page loses where they were, and
   * on a phone that is a scroll back to it. */
  function counterpart(otherBase) {
    var base = (window.deckConfig && window.deckConfig.basePath) || "/";
    var here = window.location.pathname;
    var rest = here.indexOf(base) === 0 ? here.slice(base.length) : "";
    if (otherBase.charAt(otherBase.length - 1) !== "/") otherBase += "/";
    return otherBase + rest;
  }

  function wireUnits() {
    var group = document.querySelector(".unit-switch");
    if (!group) return;
    var link = group.querySelector(".unit-switch__other");
    var showing = group.querySelector(".unit-switch__here");
    if (!link || !showing) return;

    var here = showing.textContent.trim();
    var there = link.getAttribute("data-units-switch") || "";
    link.setAttribute("href", counterpart(link.getAttribute("href") || "/"));
    link.addEventListener("click", function () { rememberUnits(there); });

    /* Landed on the set they did not choose. Sent to the other one, and only
     * ever in that direction: on the far side `here` is what was remembered,
     * so nothing sends them back and there is no loop to guard against. */
    var wanted = unitsRemembered();
    if (wanted && wanted === there && wanted !== here) {
      window.location.replace(link.getAttribute("href"));
      return;
    }
    if (wanted !== here) rememberUnits(here);
  }

  /* -------------------------------------------------------------- tabs */

  function wireTabs() {
    document.querySelectorAll("[role='tablist']").forEach(function (list) {
      var tabs = Array.prototype.slice.call(
        list.querySelectorAll("[role='tab']"));

      function select(tab) {
        tabs.forEach(function (other) {
          var chosen = other === tab;
          other.setAttribute("aria-selected", chosen ? "true" : "false");
          other.tabIndex = chosen ? 0 : -1;
          var panel = document.getElementById(
            other.getAttribute("aria-controls"));
          if (panel) panel.toggleAttribute("hidden", !chosen);
        });
        // Charts inside a panel that was hidden have no size to lay out
        // against, so they come out one pixel wide. Tell them to look
        // again now that the panel is on screen.
        window.dispatchEvent(new Event("deck:relayout"));
      }

      // Which one starts open. The skin says so with `value=` on the
      // list; without that, the first. Nothing does this for us any more,
      // and a page of tabs with every panel hidden looks broken.
      var wanted = list.getAttribute("value");
      var start = tabs.filter(function (tab) {
        return wanted && tab.getAttribute("value") === wanted;
      })[0] || tabs.filter(function (tab) {
        return tab.getAttribute("aria-selected") === "true";
      })[0] || tabs[0];
      if (start) select(start);

      tabs.forEach(function (tab, index) {
        tab.addEventListener("click", function () { select(tab); });
        tab.addEventListener("keydown", function (event) {
          var step = event.key === "ArrowRight" ? 1
                   : event.key === "ArrowLeft" ? -1 : 0;
          if (!step) return;
          event.preventDefault();
          var next = tabs[(index + step + tabs.length) % tabs.length];
          next.focus();
          select(next);
        });
      });
    });
  }

  /* ------------------------------------------------------------ tables */

  /* A table wider than the screen needs its own scroll box, or it is cut
   * off: the page cannot scroll sideways (`overflow-x: clip` on the body,
   * so a chart mid-layout cannot push it), and a fourteen-column year
   * table is 1024 pixels on a 390-pixel phone.
   *
   * Most tables carry the wrapper in their markup. This catches the rest,
   * and any a skin adds later. */
  function wrapTables() {
    document.querySelectorAll("main table").forEach(function (table) {
      var parent = table.parentElement;
      if (parent && parent.classList.contains("table-scroll")) return;
      var box = document.createElement("div");
      box.className = "table-scroll";
      table.replaceWith(box);
      box.appendChild(table);
    });

    // A box that scrolls says so: the shadow at its edge appears while
    // there is more to the right, and goes when there is not.
    document.querySelectorAll(".table-scroll").forEach(function (box) {
      function look() {
        var more = box.scrollWidth - box.clientWidth - box.scrollLeft > 2;
        box.toggleAttribute("data-more", more);
        box.toggleAttribute("data-scrolled", box.scrollLeft > 2);
      }
      box.addEventListener("scroll", look, { passive: true });
      window.addEventListener("resize", look);
      // A panel behind a tab has no width until it is shown, so the
      // answer has to be asked for again then -- and once after the first
      // frame, because at DOMContentLoaded the table has not been laid
      // out and every box reads as fitting.
      window.addEventListener("deck:relayout", look);
      requestAnimationFrame(look);
      look();
    });
  }

  function wireSorting() {
    document.querySelectorAll("table[data-sortable]").forEach(function (table) {
      var head = table.tHead;
      var body = table.tBodies[0];
      if (!head || !body) return;

      Array.prototype.forEach.call(head.rows[0].cells, function (cell, column) {
        if (cell.hasAttribute("data-nosort")) return;
        cell.setAttribute("aria-sort", "none");
        cell.tabIndex = 0;

        function sort() {
          var up = cell.getAttribute("aria-sort") !== "ascending";
          Array.prototype.forEach.call(head.rows[0].cells, function (other) {
            if (other.hasAttribute("aria-sort")) {
              other.setAttribute("aria-sort", "none");
            }
          });
          cell.setAttribute("aria-sort", up ? "ascending" : "descending");

          var rows = Array.prototype.slice.call(body.rows);
          rows.sort(function (a, b) {
            var x = key(a.cells[column]);
            var y = key(b.cells[column]);
            if (x === y) return 0;
            return (x < y ? -1 : 1) * (up ? 1 : -1);
          });
          rows.forEach(function (row) { body.appendChild(row); });
        }

        cell.addEventListener("click", sort);
        cell.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            sort();
          }
        });
      });

      // A cell may say what it sorts by -- a timestamp behind a formatted
      // date, say. Otherwise the number in it, and failing that the text.
      function key(cell) {
        if (!cell) return "";
        var said = cell.getAttribute("data-sort");
        if (said !== null) {
          var asNumber = parseFloat(said);
          return isNaN(asNumber) ? said : asNumber;
        }
        var text = cell.textContent.trim();
        var number = parseFloat(text.replace(/\s/g, "").replace(",", "."));
        return isNaN(number) ? text.toLowerCase() : number;
      }
    });
  }

  /* ------------------------------------------------------------ dialogs */

  function wireDialogs() {
    document.querySelectorAll("[data-dialog]").forEach(function (button) {
      var dialog = document.getElementById(button.getAttribute("data-dialog"));
      if (!dialog) return;
      button.addEventListener("click", function () {
        dialog.showModal();
        window.dispatchEvent(new Event("deck:relayout"));
      });
    });
    document.querySelectorAll("[data-dialog-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        var dialog = button.closest("dialog");
        if (dialog) dialog.close();
      });
    });
  }

  /* -------------------------------------------------- temperature tint */

  /* Optional -- `outTemp_stat_tile_color` on the feed's settings page.
   * Cold is blue, warm is red, and the two ends of the scale are the
   * operator's (`..._min` and `..._max`), because -20 to 40 means one
   * thing in Bavaria and another in Andalusia.
   *
   * The old version computed 600 steps of red, green and blue by hand in
   * its own minified file. One rotation through hue does the same job and
   * can be read. */
  function tintTemperature() {
    if (!config.color_temperature) return;
    var tile = document.querySelector('.stat-tile[data-observation="outTemp"]');
    if (!tile) return;

    var low = parseFloat(config.color_temperature_min);
    var high = parseFloat(config.color_temperature_max);
    var strength = parseFloat(config.color_temperature_transparency);
    if (isNaN(low) || isNaN(high) || high === low) return;

    function paint() {
      var shown = tile.querySelector(".stat-title-obs-value .raw");
      if (!shown) return;
      var text = shown.textContent
        .replace(tile.dataset.unit || "", "")
        .replace(",", ".");
      var value = parseFloat(text);
      if (isNaN(value)) return;
      var part = Math.min(1, Math.max(0, (value - low) / (high - low)));
      // 220 degrees of hue: blue at the cold end, through green and
      // yellow, to red at the warm one. Backwards through the wheel,
      // because red is at 0 and blue at 220.
      var hue = 220 - part * 220;
      tile.style.setProperty("--tint", "hsl(" + hue.toFixed(0) + " 85% 55%)");
      tile.style.setProperty("--tint-strength", isNaN(strength) ? 0.35 : strength);
    }

    paint();
    // The live feed rewrites the reading in place, so the tint has to
    // follow it rather than being set once at load.
    var watched = tile.querySelector(".stat-title-obs-value .raw");
    if (watched && window.MutationObserver) {
      new MutationObserver(paint).observe(watched, {
        characterData: true, childList: true, subtree: true,
      });
    }
  }

  /* --------------------------------------------------------------- go */

  function start() {
    wireTheme();
    wireMenu();
    wrapTables();
    wireUnits();
    wireTabs();
    wireSorting();
    wireDialogs();
    tintTemperature();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  window.deck = { setTheme: setTheme, currentTheme: currentTheme, config: config };
})();

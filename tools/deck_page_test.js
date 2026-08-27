/* Run the skin's own JavaScript against its own rendered page.
 *
 * Everything else about Deck is checked by reading what it produced. That
 * cannot find the one fault that matters most here: a page that renders
 * perfectly and then stops responding. The live badges were painted into the
 * element a MutationObserver was watching, so every paint was a mutation and
 * every mutation a paint. The HTML was correct, every test passed, and the
 * tab locked up a second after it loaded.
 *
 * So this runs it. Called by tools/deck_live_test.py with:
 *
 *     node tools/deck_page_test.js <page.html> <assets-dir> [live.json]
 *
 * It prints one JSON object on stdout and exits 0. Failing is the caller's
 * decision, not this file's.
 */

"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const [pageFile, assetsDir, liveFile] = process.argv.slice(2);

/* What a live document would be, for the run where one is supplied. Fetch is
 * stubbed rather than a server started: the point is the page's own code, and
 * a socket here would only add something else that can fail. */
const live = liveFile ? JSON.parse(fs.readFileSync(liveFile, "utf-8")) : null;

const problems = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (error) => {
  problems.push("script error: " + error.message);
});

const dom = new JSDOM(fs.readFileSync(pageFile, "utf-8"), {
  runScripts: "outside-only",
  pretendToBeVisual: true,
  url: "https://example.org/wetter/",
  virtualConsole,
});
const { window } = dom;

/* jsdom has no matchMedia, and Deck asks it which colour scheme to use. Not
 * a fault in the skin: a browser has it. Stubbed rather than worked around in
 * the page, because a page that checks whether the function exists before
 * calling it is carrying a test's limitation into production. */
window.matchMedia = function (query) {
  return {
    matches: false,
    media: String(query),
    onchange: null,
    addListener: function () {},
    removeListener: function () {},
    addEventListener: function () {},
    removeEventListener: function () {},
    dispatchEvent: function () { return false; },
  };
};

let fetches = 0;
window.fetch = function (where) {
  fetches += 1;
  if (!live) {
    return Promise.resolve({ ok: false, status: 404, json: () => ({}) });
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(live) });
};

/* The measurement, installed before a single line of the page runs. A runaway
 * mutation loop shows up as an unbounded count of MutationObserver callbacks;
 * a page that settles produces a handful and stops.
 *
 * Order matters and got this wrong once: wrapped after the scripts had run,
 * they were already holding the real constructor, the count stayed at zero,
 * and the check passed by measuring nothing. */
let callbacks = 0;
const RealObserver = window.MutationObserver;
window.MutationObserver = function (fn) {
  return new RealObserver(function (records, observer) {
    callbacks += 1;
    return fn(records, observer);
  });
};

/* The two files the page loads. Read off the page rather than named here, so
 * a script that stops being included stops being tested and the count says
 * so. */
const wanted = [...window.document.querySelectorAll("script[src]")]
  .map((tag) => tag.getAttribute("src"))
  .filter((src) => src && !/^https?:/.test(src))
  .map((src) => path.join(assetsDir, path.basename(src)))
  .filter((file) => fs.existsSync(file));

/* Inline scripts first: `window.deckLivePoll` and the translations are set
 * there, and a poller that starts before them polls the wrong file. */
for (const tag of window.document.querySelectorAll("script:not([src])")) {
  try {
    window.eval(tag.textContent);
  } catch (error) {
    problems.push("inline script: " + error.message);
  }
}
for (const file of wanted) {
  try {
    window.eval(fs.readFileSync(file, "utf-8"));
  } catch (error) {
    problems.push(path.basename(file) + ": " + error.message);
  }
}

/* Let the page live for a while: the badges repaint on a one-second timer,
 * and the poller runs on its own. Anything that is going to run away has
 * done so long before this is up. */
const SECONDS = 4;

function badgeCount() {
  return window.document.querySelectorAll(".live-badge").length;
}

function badgeState() {
  const classes = new Set();
  for (const badge of window.document.querySelectorAll(".live-badge")) {
    for (const name of badge.className.split(/\s+/)) {
      if (name.startsWith("live-badge--")) {
        classes.add(name);
      }
    }
  }
  return [...classes].sort();
}

function inWatchedElement() {
  /* The fault itself, asked directly: is any badge inside the element the
   * observer watches? */
  for (const badge of window.document.querySelectorAll(".live-badge")) {
    if (badge.closest(".stat-title-obs-value")) {
      return true;
    }
  }
  return false;
}

/* jsdom's timers are real, so this is real time. Four seconds is the price of
 * catching a class of fault nothing else here can see. */
const started = Date.now();
setTimeout(() => {
  const result = {
    cards: window.document.querySelectorAll(".card.stat-tile[data-observation]")
      .length,
    badges: badgeCount(),
    badgeStates: badgeState(),
    badgeInWatchedElement: inWatchedElement(),
    observerCallbacks: callbacks,
    fetches: fetches,
    seconds: (Date.now() - started) / 1000,
    values: [...window.document.querySelectorAll(".card.stat-tile[data-observation]")]
      .slice(0, 40)
      .map((card) => ({
        obs: card.getAttribute("data-observation"),
        shown: (card.querySelector(".stat-title-obs-value .raw") || {})
          .textContent?.trim(),
      })),
    problems: problems,
  };
  process.stdout.write(JSON.stringify(result));
  process.exit(0);
}, SECONDS * 1000);

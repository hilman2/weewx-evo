/* What a real parser makes of the rendered page.
 *
 * An inline `<svg>` with no `fill` of its own is black. That is invisible on
 * a dark background, and it is invisible in a way nothing else here can
 * find: the markup is correct, the icon is present, the page renders, and
 * half of it is simply not there for anybody using the dark theme.
 *
 * The skin's icons come from a set that leaves `fill` out, so every place
 * that draws one has to supply it. The station logo is the exception and
 * says so in its own markup -- which is exactly the distinction this makes.
 *
 * Called by tools/deck_test.py:
 *
 *     node tools/deck_dom_test.js <page.html> <deck.css>
 *
 * Prints one JSON object on stdout. Judging it is the caller's job.
 */

"use strict";

const fs = require("fs");
const { JSDOM } = require("jsdom");

const page = fs.readFileSync(process.argv[2], "utf-8");
let css = fs.readFileSync(process.argv[3], "utf-8");
css = css.replace(/\/\*[\s\S]*?\*\//g, "");

/* Every selector that gives something a colour. `fill: none` does not count:
 * it is how these icons hide their bounding rectangle. */
const painted = [];
for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
  const body = rule[2];
  if (!/\bfill\s*:/.test(body)) continue;
  if (/\bfill\s*:\s*none\s*[;}]?/.test(body) && !/\bfill\s*:\s*(?!none)/.test(body)) {
    continue;
  }
  for (const one of rule[1].split(",")) {
    const selector = one.trim();
    if (selector && !selector.startsWith("@") && !selector.startsWith("%")) {
      painted.push(selector);
    }
  }
}

const dom = new JSDOM(page);
const d = dom.window.document;

function coloursItself(svg) {
  /* Its own markup says what colour it is: a `fill` attribute anywhere in it
   * that is not `none`, or a `<style>` block that sets one. */
  if ((svg.getAttribute("fill") || "none") !== "none") return true;
  for (const node of svg.querySelectorAll("[fill]")) {
    if ((node.getAttribute("fill") || "none") !== "none") return true;
  }
  /* A `<style>` inside the icon that sets a real colour. Read as values
   * rather than matched with a lookahead: `fill\s*:\s*(?!none)` matches
   * "fill: none" by backtracking over the space, which made every icon in
   * this set look as though it coloured itself and the whole check pass
   * without measuring anything. */
  const style = svg.querySelector("style");
  if (!style) return false;
  for (const found of (style.textContent || "").matchAll(/fill\s*:\s*([^;}]+)/g)) {
    if (found[1].trim() !== "none") return true;
  }
  return false;
}

function where(svg) {
  /* Enough of the ancestry to find it in the templates. */
  const parts = [];
  for (let node = svg.parentElement; node && parts.length < 3;
       node = node.parentElement) {
    const cls = (node.getAttribute("class") || "").trim().split(/\s+/)[0];
    if (cls) parts.unshift("." + cls);
  }
  return parts.join(" ") || "(no class anywhere above it)";
}

const uncoloured = [];
let checked = 0;
for (const svg of d.querySelectorAll("svg")) {
  if (coloursItself(svg)) continue;
  checked += 1;
  const matched = painted.some((selector) => {
    try {
      return svg.matches(selector);
    } catch {
      /* A selector jsdom cannot parse is not evidence either way, and
       * throwing here would report the whole page as uncoloured. */
      return false;
    }
  });
  if (!matched) uncoloured.push(where(svg));
}

/* The days choose which hours are shown below them. `deck.js` wires that
 * from the ARIA attributes alone, so getting them wrong is a section that
 * renders perfectly and does nothing when clicked -- and one a keyboard
 * cannot reach at all. Only a parser can answer this: it turns on ids. */
const tablists = [...d.querySelectorAll("[role='tablist']")].map((list) => {
  const tabs = [...list.querySelectorAll("[role='tab']")];
  const panelOf = (tab) =>
    d.getElementById(tab.getAttribute("aria-controls") || "");
  return {
    tabs: tabs.length,
    /* A tab whose `aria-controls` names nothing is a button wired nowhere. */
    danglingTabs: tabs.filter((tab) => !panelOf(tab)).length,
    selected: tabs.filter((t2) => t2.getAttribute("aria-selected") === "true")
      .length,
    /* Two panels visible is two answers to one question; none is a section
     * that looks broken. Exactly one, before any script has run. */
    visiblePanels: tabs.filter((tab) => {
      const panel = panelOf(tab);
      return panel && !panel.hasAttribute("hidden");
    }).length,
    /* Reachable by keyboard: a `<button>` is, a `<div role="tab">` is not. */
    notFocusable: tabs.filter(
      (tab) => tab.tagName.toLowerCase() !== "button"
               && !tab.hasAttribute("tabindex")
    ).length,
  };
});

process.stdout.write(JSON.stringify({
  rulesThatPaint: painted.length,
  iconsNeedingCss: checked,
  uncoloured: [...new Set(uncoloured)],
  forecastDays: d.querySelectorAll(".forecast-day").length,
  forecastPanels: d.querySelectorAll("[data-test='forecast-hours']").length,
  tablists: tablists,
}));

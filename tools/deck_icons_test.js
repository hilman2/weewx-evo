/* Every icon on the page has a colour, from somewhere.
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
 *     node tools/deck_icons_test.js <page.html> <deck.css>
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

process.stdout.write(JSON.stringify({
  rulesThatPaint: painted.length,
  iconsNeedingCss: checked,
  uncoloured: [...new Set(uncoloured)],
}));

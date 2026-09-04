/* Does a field that only applies sometimes actually fold away?
 *
 * `Option.when`, the renderer's `data-when` and the script that acts on it
 * were all built and none of them was ever used: not one option declared a
 * condition, so every form showed every field and the condition was left in
 * a sentence under it. "Only used with 'on its own schedule'", printed under
 * a field that is meaningless for the three other choices above it.
 *
 * Reading the HTML cannot answer whether it works. The attributes are there
 * either way; what decides is a script running against a parsed document --
 * and the first version of that script read `source.value`, which for a
 * checkbox is "1" whether it is ticked or not. Every field conditional on a
 * switch would have stayed visible forever, with the markup looking right.
 *
 *     node tools/admin_conditional_test.js <page.html>
 *
 * Prints one JSON object on stdout. Judging it is the caller's job.
 */

"use strict";

const fs = require("fs");
const { JSDOM } = require("jsdom");

/* The scripts have to run: this is the whole point. `resources` is left
 * alone -- the page loads nothing from outside, and a test that reached the
 * network would be one that fails on a train. */
const dom = new JSDOM(fs.readFileSync(process.argv[2], "utf-8"),
                      { runScripts: "dangerously" });
const d = dom.window.document;

function state() {
  return [...d.querySelectorAll("[data-when]")].map((field) => {
    const on = field.getAttribute("data-when");
    const wanted = (field.getAttribute("data-when-is") || "").split(" ");
    const source = d.querySelector('[name="' + on + '"]');
    /* Not `input, select, textarea`: a checkbox is preceded by a hidden
     * `__present__x` marker, so the first control in the field is that --
     * and every failure about a switch was reported under a name nobody
     * would recognise. */
    const input = field.querySelector(
      "input:not([type=hidden]), select, textarea");
    return {
      name: input ? input.getAttribute("name") : null,
      on: on,
      wanted: wanted,
      /* What the browser would show. `hidden` is what the script sets. */
      hidden: !!field.hidden,
      /* Whether the field it depends on is even on this page. Without it
       * the field must stay visible: hiding a setting for a reason nobody
       * can see is worse than showing one that does not apply. */
      sourceHere: !!source,
      sourceKind: source ? (source.type || source.tagName.toLowerCase()) : null,
      sourceValue: !source ? null
        : (source.type === "checkbox" ? (source.checked ? "1" : "0")
                                      : source.value),
    };
  });
}

const before = state();

/* And now change what they depend on, the way a person would, and see
 * whether the answer moves. A mechanism that hides the right fields on load
 * and never reacts is one that is wrong the moment somebody uses the form. */
const flipped = [];
for (const field of d.querySelectorAll("[data-when]")) {
  const on = field.getAttribute("data-when");
  const source = d.querySelector('[name="' + on + '"]');
  if (!source || flipped.indexOf(on) >= 0) continue;
  const wanted = (field.getAttribute("data-when-is") || "").split(" ");
  if (source.type === "checkbox") {
    source.checked = !source.checked;
  } else if (source.tagName.toLowerCase() === "select") {
    /* Across the condition, not merely to another value. A select that is
     * already on a value the field does not want has to be moved to one it
     * does -- picking "another value it does not want" changes nothing and
     * makes a working page look frozen, which is what the first version of
     * this did. */
    const showing = wanted.indexOf(source.value) >= 0;
    const other = [...source.options]
      .map((o) => o.value)
      .find((v) => (wanted.indexOf(v) >= 0) !== showing);
    if (other === undefined) continue;
    source.value = other;
  } else {
    continue;
  }
  source.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  flipped.push(on);
}

process.stdout.write(JSON.stringify({
  before: before,
  after: state(),
  flipped: flipped,
}, null, 2));

/* Which form does each button on the settings page actually belong to?
 *
 * Reading the HTML as text cannot answer that. The tags are all present and
 * all balanced; it is the *nesting* that is wrong, and only a parser that
 * follows the HTML rules sees the consequence.
 *
 * The fault this exists for: the Try it and Remove sections were rendered
 * inside the save form. HTML has no nested forms, so a browser drops the
 * inner `<form>` and keeps its `</form>` -- which closes the outer one early.
 * The Save button then belonged to no form at all and did nothing when
 * clicked, and Try it silently submitted a save instead of testing anything.
 * Every export, feed, upload and forecast page was like that.
 *
 * Called by tools/adminpage.py:
 *
 *     node tools/admin_page_test.js <page.html>
 *
 * Prints one JSON object on stdout. Judging it is the caller's job.
 */

"use strict";

const fs = require("fs");
const { JSDOM } = require("jsdom");

const dom = new JSDOM(fs.readFileSync(process.argv[2], "utf-8"));
const d = dom.window.document;

function label(button) {
  return (button.textContent || "").trim();
}

const buttons = [...d.querySelectorAll("button, input[type=submit]")].map(
  (button) => ({
    label: label(button),
    /* `.form` is the browser's own answer, after parsing. A button outside
     * every form reports null, and clicking it does nothing whatsoever. */
    action: button.form ? button.form.getAttribute("action") : null,
  })
);

process.stdout.write(
  JSON.stringify({
    forms: [...d.querySelectorAll("form")].map((f) => f.getAttribute("action")),
    buttons: buttons,
    orphans: buttons.filter((b) => b.action === null).map((b) => b.label),
    /* Fields that no form will submit are the same fault seen from the other
     * side: they render, they take what somebody types, and it goes nowhere. */
    strandedFields: [...d.querySelectorAll("input[name], select[name], textarea[name]")]
      .filter((element) => !element.form)
      .map((element) => element.getAttribute("name")),
  })
);

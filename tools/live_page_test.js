/* Does the live table lay out as a table, or fold to one character a line?
 *
 * Reading the HTML as text cannot answer that. The markup was correct and
 * every test on it was green; what was wrong was which CSS rules applied.
 *
 * The fault this exists for: the table was given `class="stations fields"`,
 * which is the placement form's layout -- `table-layout: fixed`, `width:
 * 100%`, and five hard column widths written for a five-column table. Twelve
 * columns in that share what is left of the width, so every cell wrapped to
 * one character per line and the twelve headings stacked on top of each
 * other. It rendered, it was valid HTML, and it was unreadable.
 *
 * So the question is asked of the *computed* style, which is neither the
 * markup nor the stylesheet alone -- the same method as
 * `tools/deck_icons_test.js`, which asks whether any rule paints an icon.
 *
 * Called by tools/adminlive_test.py:
 *
 *     node tools/live_page_test.js <page.html>
 *
 * Prints one JSON object on stdout. Judging it is the caller's job.
 */

"use strict";

const fs = require("fs");
const { JSDOM } = require("jsdom");

const dom = new JSDOM(fs.readFileSync(process.argv[2], "utf-8"), {
  /* The rows are built by the page's own script from a fetch, and jsdom has
   * no fetch worth giving it. The script is run for its side effect on the
   * document's structure; the rows are put in by hand below, through the
   * same `table()` the page uses -- so what is measured is the class the
   * page assigns and the rules that match it. */
  runScripts: "outside-only",
});
const d = dom.window.document;

/* One table of each kind, built the way the page builds them. Both the
 * class and the column that takes the slack are read out of the page's own
 * script rather than written here -- named here, this would go on passing
 * after somebody changed either, and a test that cannot see its own bug
 * measures nothing. */
function build(className, columns, stretch) {
  const t = d.createElement("table");
  t.className = className;
  const head = d.createElement("tr");
  for (const name of columns) {
    const th = d.createElement("th");
    th.textContent = name;
    if (name === stretch) { th.className = "stretch"; }
    head.appendChild(th);
  }
  const thead = d.createElement("thead");
  thead.appendChild(head);
  t.appendChild(thead);
  const body = d.createElement("tbody");
  const row = d.createElement("tr");
  for (const name of columns) {
    const td = d.createElement("td");
    td.textContent = name === "identity" ? "3178AB6B42A759F51A5A4AD72E37F8DE"
      : "value";
    row.appendChild(td);
  }
  body.appendChild(row);
  t.appendChild(body);
  return t;
}

const COLUMNS = ["seq", "dateTime", "received", "driver", "identity",
  "sender", "dialect", "mapping", "kind", "usUnits", "interval",
  "digest", "data", "raw", "sender name", "age"];

/* The class the *page* assigns, read out of its own script rather than
 * written here. Given a name of its own, this would go on passing after
 * somebody put `stations fields` back -- which is the bug, and a test that
 * cannot see its own bug is a test that measures nothing. */
const script = [...d.querySelectorAll("script")]
  .map((one) => one.textContent)
  .join(" ");
const assigned = /t\.className\s*=\s*'([^']+)'/.exec(script);
const stretch = /var STRETCH\s*=\s*'([^']+)'/.exec(script);

const box = d.querySelector(".scroller") || d.body;
const table = build(assigned ? assigned[1] : "(the page assigns none)",
                    COLUMNS, stretch ? stretch[1] : null);
box.appendChild(table);

const style = (el) => dom.window.getComputedStyle(el);
const td = table.querySelector("tbody td");
const th = table.querySelector("thead th");

console.log(JSON.stringify({
  /* The page has somewhere to scroll it. Without this the widest column
   * decides the width of the page, which on a phone is the whole screen. */
  scroller: !!d.querySelector(".scroller"),
  scrollerOverflowX: d.querySelector(".scroller")
    ? style(d.querySelector(".scroller")).overflowX : "",
  /* `fixed` is what did it: with it the browser takes the widths from the
   * first row and the rules, and ignores what is in the cells. */
  tableLayout: style(table).tableLayout,
  /* And the width must come from the contents, not from the page. */
  tableWidth: style(table).width,
  /* But never narrower than what it is given: `max-content` on its own
     leaves a wide screen empty on the right. */
  tableMinWidth: style(table).minWidth,
  /* One column takes the slack, or widening the window puts a hand's width
     between every pair of columns rather than into the one with the most in
     it. Named, not positional -- the columns come from the schema. */
  stretches: [...table.querySelectorAll("th.stretch")]
    .map((th) => th.textContent),
  /* And the page it sits on is not capped at a reading width. A database
     row is not a paragraph. */
  mainMaxWidth: d.querySelector("main")
    ? style(d.querySelector("main")).maxWidth : "(no main)",
  mainClass: d.querySelector("main")
    ? d.querySelector("main").className : "(no main)",
  /* A cell that may wrap is a cell that will, with twelve of them. */
  cellWhiteSpace: style(td).whiteSpace,
  headWhiteSpace: style(th).whiteSpace,
  /* The rule that broke it, by name: this is the one that made a 32-
   * character identity break between every character. */
  cellOverflowWrap: style(td).overflowWrap,
  /* And the class it is not sharing any more. */
  className: table.className,
}));

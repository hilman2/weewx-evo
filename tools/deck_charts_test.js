/* The charts build themselves from the files, and keep up.
 *
 * The tiles are no longer in the HTML. `charts.js` asks the manifest which
 * plots exist for a span, builds a card for each, fetches that plot's file
 * and draws it -- then asks again a minute later. None of that can be seen
 * by reading the page: the page is one empty div.
 *
 * So this runs it, against a manifest and two chart files served from
 * memory. ECharts needs a canvas jsdom does not have, so it is stubbed --
 * what is under test is which files are asked for and what the DOM becomes,
 * not the drawing.
 *
 *     node tools/deck_charts_test.js <page.html> <charts.js>
 *
 * Prints one JSON object on stdout. Judging it is the caller's job.
 */

"use strict";

const fs = require("fs");
const { JSDOM } = require("jsdom");

const dom = new JSDOM(fs.readFileSync(process.argv[2], "utf-8"), {
  runScripts: "outside-only",
  pretendToBeVisual: true,
  url: "https://example.org/wetter/",
});
const { window } = dom;

/* What the `json` feed writes: an index of what exists, and a file each. */
const NOW = 1787838000;
const MANIFEST = {
  format: 1,
  generated: NOW,
  spans: ["day", "week"],
  plots: [
    { name: "daytempdew", group: "day", title: "Temperatur / Taupunkt",
      unit_label: "°C", obs_types: ["outTemp", "dewpoint"] },
    { name: "dayhum", group: "day", title: "Luftfeuchte",
      unit_label: "%", obs_types: ["outHumidity"] },
    { name: "weektempdew", group: "week", title: "Temperatur / Taupunkt",
      unit_label: "°C", obs_types: ["outTemp", "dewpoint"] },
  ],
};

function chartFile(name, aggregated) {
  const time = [NOW - 7200, NOW - 3600, NOW];
  return {
    name: name,
    format: 1,
    generated: NOW,
    start: time[0],
    stop: NOW,
    unit: "degree_C",
    unit_label: "°C",
    title: name === "dayhum" ? "Luftfeuchte" : "Temperatur / Taupunkt",
    series: [
      Object.assign({
        obs_type: "outTemp", label: "Außentemperatur",
        plot_type: "line", color: "#c0392b",
        time: time, values: [19.5, 20.1, 21.4],
      }, aggregated ? { aggregate_interval: 3600, aggregate_type: "avg" } : {}),
    ],
  };
}

const asked = [];
window.fetch = function (where) {
  asked.push(String(where));
  const name = String(where).split("/").pop().replace(".json", "");
  const body = name === "index" ? MANIFEST : chartFile(name, name[0] === "w");
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  });
};

/* ECharts wants a canvas. What is under test is the wiring, so the drawing
 * is a stub that records what it was handed. */
const drawn = [];
window.echarts = {
  init: function () {
    return {
      setOption: function (option) { drawn.push(option); },
      resize: function () {},
    };
  },
};
window.matchMedia = window.matchMedia || function () {
  return { matches: false, addEventListener() {}, addListener() {},
           removeEventListener() {}, removeListener() {} };
};

window.eval(fs.readFileSync(process.argv[3], "utf-8"));

/* The fetches resolve as microtasks; a turn of the event loop is enough. */
setTimeout(() => {
  const d = window.document;
  const tiles = [...d.querySelectorAll(".diagram-tile")];
  const first = drawn[0] || {};
  const series = (first.series || [])[0] || {};
  const points = series.data || [];

  process.stdout.write(JSON.stringify({
    asked: asked,
    tiles: tiles.length,
    titles: tiles.map((tile) => {
      const heading = tile.querySelector("[data-plot-title]");
      return heading ? heading.textContent.trim() : null;
    }),
    plots: [...d.querySelectorAll("[data-plot]")]
      .map((one) => one.getAttribute("data-plot")),
    charts: drawn.length,
    /* The numbers reached the drawing, and the timestamps came through as
     * milliseconds -- the units ECharts measures a time axis in. */
    firstPoint: points.length ? points[0] : null,
    lastPoint: points.length ? points[points.length - 1] : null,
    seriesName: series.name || null,
  }));
  process.exit(0);
}, 300);

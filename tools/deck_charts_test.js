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
    /* A plot whose readings stopped. The station has the column and the plot
     * is defined, so the file exists and is empty -- evapotranspiration, on
     * a station whose last one was the day before. */
    { name: "dayET", group: "day", title: "Evapotranspiration",
      unit_label: "mm", obs_types: ["ET"] },
    /* A comparison: one reading at two places, and the second place was
     * added yesterday, so its line is a single point. Both cases have to
     * survive -- the series has to be drawn at all, and a series with
     * nothing to join has to show its points or it draws an empty panel
     * beside a legend that names the place. */
    { name: "daycmpoutTemp", group: "day", title: "Außentemperatur",
      unit_label: "°C", obs_types: ["outTemp"],
      archives: ["default", "nordfeld"] },
  ],
};

function chartFile(name, aggregated) {
  if (name === "dayET") {
    /* Written, and empty: nothing fell in the window. */
    return {
      name: name, format: 1, generated: NOW, start: NOW - 7200, stop: NOW,
      unit: "mm", unit_label: "mm", title: "Evapotranspiration",
      series: [{ obs_type: "ET", label: "Evapotranspiration",
                 plot_type: "bar", aggregate_type: "sum",
                 aggregate_interval: "hour", time: [], values: [] }],
    };
  }
  const time = [NOW - 7200, NOW - 3600, NOW];
  if (name === "daycmpoutTemp") {
    return {
      name: name, format: 1, generated: NOW, start: time[0], stop: NOW,
      unit: "degree_C", unit_label: "°C", title: "Außentemperatur",
      places: ["default", "nordfeld"],
      note: "day Mittel · °C · Kirchdorf, Nordfeld",
      series: [
        { obs_type: "outTemp", label: "Kirchdorf", series: "default",
          plot_type: "line", color: "#4282b4",
          time: time, values: [19.5, 20.1, 21.4] },
        { obs_type: "outTemp", label: "Nordfeld", series: "nordfeld",
          plot_type: "line", color: "#d1642a",
          time: [NOW], values: [12.2] },
      ],
    };
  }
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

/* The page's own inline scripts first. `window.deckConfig` is set there and
 * carries the language the tooltips are written in -- run without it, every
 * chart falls back to English and a German page reads AM and PM. */
for (const tag of window.document.querySelectorAll("script:not([src])")) {
  try {
    window.eval(tag.textContent);
  } catch (error) {
    /* A page script needing something not stubbed here is not under test. */
  }
}

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
    /* The cards have to be children of the grid, or the grid holds one item
     * and lays out one chart per row on a screen with room for three. */
    grid: (function () {
      var container = d.querySelector("[data-plots]");
      if (!container) return null;
      return {
        classes: container.getAttribute("class") || "",
        directChildren: container.children.length,
        cardsInside: container.querySelectorAll(".diagram-tile").length,
      };
    })(),
    /* Which language the tooltips are written in. */
    locale: (window.deckConfig && window.deckConfig.chartSpec
             && window.deckConfig.chartSpec.locale) || null,
    /* The numbers reached the drawing, and the timestamps came through as
     * milliseconds -- the units ECharts measures a time axis in. */
    firstPoint: points.length ? points[0] : null,
    lastPoint: points.length ? points[points.length - 1] : null,
    seriesName: series.name || null,
    /* Every chart's series, by name and by whether it shows its points.
     *
     * Reading only the first series of the first chart, a comparison that
     * lost its second line looked exactly like one that kept it. That is
     * what happened: a loop counter reused inside the series loop ended it
     * after the first series, and a page whose whole subject is two places
     * drew one, under a legend of one. */
    seriesNames: drawn.map(function (option) {
      return (option.series || []).map(function (one) { return one.name; });
    }),
    seriesSymbols: drawn.map(function (option) {
      return (option.series || []).map(function (one) {
        return one.showSymbol === undefined ? null : one.showSymbol;
      });
    }),
    /* A bucket's width, which a bar is drawn at. Taken from the next
     * bucket's start, because `aggregate_interval` is sometimes a word. */
    firstWidth: points.length > 1
      ? (points[1][0] - points[0][0]) : null,
  }));
  process.exit(0);
}, 300);

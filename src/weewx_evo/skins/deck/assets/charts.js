/* Deck — the charts.
 *
 * One library where there were three: nivo (React, inside a 1.7 MB bundle
 * whose TypeScript source is not in this repository, so it could not be
 * rebuilt), d3 for some of the diagrams directly, and a full megabyte of
 * Plotly loaded on every page for exactly one chart -- the wind rose.
 *
 * ECharts draws all of it: lines, areas, bars, the wind rose on a polar
 * grid, the gauges, the calendar heat map.
 *
 * The numbers are not computed here. `chartdata.py` already produces
 * converted, rounded series -- that is the whole point of it living in the
 * core rather than in a renderer, and it is why the PNG images and these
 * charts cannot drift apart in the third decimal the way WeeWX's two
 * generators do. This file turns a series into an option object and hands
 * it over.
 *
 * Every chart reads its colours from the CSS tokens, so there is no second
 * palette to keep in step with the stylesheet, and a theme change redraws
 * rather than reloads.
 */
(function () {
  "use strict";

  if (typeof echarts === "undefined") return;

  var charts = [];

  /* ------------------------------------------------------------ tokens */

  function token(name, fallback) {
    var found = getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim();
    return found || fallback;
  }

  /* --------------------------------------------------------- contrast */

  /* WCAG's relative luminance. Not for a score -- for the one question
   * that matters here: can this be seen against what it is drawn on. */
  function luminance(colour) {
    var rgb = toRGB(colour);
    if (!rgb) return null;
    var parts = rgb.map(function (n) {
      n = n / 255;
      return n <= 0.03928 ? n / 12.92 : Math.pow((n + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
  }

  function toRGB(colour) {
    if (!colour) return null;
    var hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(colour).trim());
    if (hex) {
      var digits = hex[1];
      if (digits.length === 3) {
        digits = digits[0] + digits[0] + digits[1] + digits[1] +
                 digits[2] + digits[2];
      }
      var n = parseInt(digits, 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    var numbers = String(colour).match(/-?[\d.]+/g);
    if (/^rgb/i.test(colour) && numbers && numbers.length >= 3) {
      return [+numbers[0], +numbers[1], +numbers[2]];
    }
    if (/^hsl/i.test(colour) && numbers && numbers.length >= 3) {
      return hslToRGB(+numbers[0], +numbers[1] / 100, +numbers[2] / 100);
    }
    return null;
  }

  function hslToRGB(h, s, l) {
    var c = (1 - Math.abs(2 * l - 1)) * s;
    var x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    var m = l - c / 2;
    var t = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
          : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
    return t.map(function (n) { return Math.round((n + m) * 255); });
  }

  function contrast(a, b) {
    var one = luminance(a);
    var two = luminance(b);
    if (one === null || two === null) return null;
    return (Math.max(one, two) + 0.05) / (Math.min(one, two) + 0.05);
  }

  /* A colour that can be seen on the surface it is drawn on.
   *
   * The hue is kept and the lightness moved, so a green stays green. Only
   * where the two are genuinely too close: 2.2:1 is roughly where a line
   * on a chart stops reading as a line. */
  function visible(colour, surface) {
    var ratio = contrast(colour, surface);
    if (ratio === null || ratio >= 2.2) return colour;

    var rgb = toRGB(colour);
    var behind = luminance(surface);
    if (!rgb) return colour;

    // Which way to move: away from the background.
    var towards = behind < 0.5 ? 255 : 0;
    for (var mix = 0.15; mix <= 1.0; mix += 0.15) {
      var lifted = "rgb(" + rgb.map(function (n) {
        return Math.round(n + (towards - n) * mix);
      }).join(",") + ")";
      if (contrast(lifted, surface) >= 2.6) return lifted;
    }
    return towards ? "#ffffff" : "#000000";
  }

  function palette() {
    return {
      ink: token("--ink", "#111"),
      ink2: token("--ink-2", "#555"),
      ink3: token("--ink-3", "#888"),
      line: token("--line", "#ddd"),
      lineSoft: token("--line-soft", "#eee"),
      surface: token("--surface", "#fff"),
      accent: token("--accent", "#1a73e8"),
      font: token("--font", "sans-serif"),
      night: token("--bg-sunk", "#f0f0f0"),
    };
  }

  /* ------------------------------------------------------------ helpers */

  /* A series arrives as [start, stop, value] per bucket. ECharts wants
   * [when, value], and a null value has to stay null: dropping the point
   * would join the line across the gap and invent readings that were never
   * taken. */
  function points(rows) {
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      out.push([row[0] * 1000, row[2] === undefined ? null : row[2]]);
    }
    return out;
  }

  function bucketWidth(rows) {
    if (rows.length < 1) return undefined;
    var first = rows[0];
    if (first.length > 1 && first[1] > first[0]) {
      return (first[1] - first[0]) * 1000;
    }
    return undefined;
  }

  /* strftime, as far as a chart label needs it. The formats come from
   * `skin.conf` (`bottom_date_time_format`), which is where they have been
   * for the life of this skin, so they are what the operator already
   * chose -- and they are strftime, not anybody's chart-library dialect. */
  function timeFormatter(format, locale) {
    if (!format) return undefined;
    return function (value) {
      return strftime(new Date(value), format, locale);
    };
  }

  function strftime(date, format, locale) {
    var pad = function (n, w) {
      n = String(n);
      while (n.length < (w || 2)) n = "0" + n;
      return n;
    };
    var loc = locale || "en-US";
    return format.replace(/%([a-zA-Z%])/g, function (whole, code) {
      switch (code) {
        case "H": return pad(date.getHours());
        case "I": return pad(((date.getHours() + 11) % 12) + 1);
        case "M": return pad(date.getMinutes());
        case "S": return pad(date.getSeconds());
        case "p": return date.getHours() < 12 ? "AM" : "PM";
        case "d": return pad(date.getDate());
        case "e": return String(date.getDate());
        case "m": return pad(date.getMonth() + 1);
        case "y": return pad(date.getFullYear() % 100);
        case "Y": return String(date.getFullYear());
        // The month and weekday names follow the page's language, not the
        // process locale -- the same trap `language.py` names on the
        // Python side, where a container with no locale set answers "May"
        // on a German page.
        case "b": return date.toLocaleDateString(loc, { month: "short" });
        case "B": return date.toLocaleDateString(loc, { month: "long" });
        case "a": return date.toLocaleDateString(loc, { weekday: "short" });
        case "A": return date.toLocaleDateString(loc, { weekday: "long" });
        case "x": return date.toLocaleDateString(loc);
        case "X": return date.toLocaleTimeString(loc);
        case "c": return date.toLocaleString(loc);
        case "%": return "%";
        default: return whole;
      }
    });
  }

  function decimals(spec) {
    var found = /%\.(\d+)f/.exec(spec || "");
    return found ? parseInt(found[1], 10) : null;
  }

  function fixed(value, places, locale) {
    if (value === null || value === undefined) return "–";
    if (places === null) return String(value);
    return Number(value).toLocaleString(locale || "en-US", {
      minimumFractionDigits: places,
      maximumFractionDigits: places,
    });
  }

  /* ------------------------------------------------------ shared option */

  function base(colours, spec) {
    return {
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      animationDuration: 320,
      textStyle: { fontFamily: colours.font, color: colours.ink2 },
      grid: {
        // Room at the top for the unit, which sits above the axis rather
        // than rotated along it: `mbar` read sideways is worse than one
        // line of header.
        left: 4, right: 14, top: 26, bottom: 2,
        containLabel: true,
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: colours.surface,
        borderColor: colours.line,
        borderWidth: 1,
        padding: [8, 12],
        textStyle: { color: colours.ink, fontSize: 12 },
        extraCssText: "border-radius:10px;box-shadow:0 8px 24px -8px rgba(0,0,0,.25)",
        axisPointer: {
          type: "line",
          lineStyle: { color: colours.ink3, width: 1, type: [4, 4] },
        },
        formatter: spec && spec.tooltipFormatter,
      },
    };
  }

  function timeAxis(colours, spec) {
    return {
      type: "time",
      boundaryGap: false,
      axisLine: { lineStyle: { color: colours.line } },
      axisTick: { show: false },
      axisLabel: {
        color: colours.ink3,
        fontSize: 11,
        hideOverlap: true,
        formatter: timeFormatter(spec.bottomFormat, spec.locale),
      },
      splitLine: {
        show: true,
        lineStyle: { color: colours.lineSoft, type: [3, 5] },
      },
    };
  }

  function valueAxis(colours, spec, index) {
    var unit = (spec.units && spec.units[index || 0]) || "";
    return {
      type: "value",
      scale: true,
      name: unit ? unit.trim() : undefined,
      nameLocation: "end",
      nameGap: 10,
      nameTextStyle: { color: colours.ink3, fontSize: 11, align: "left" },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: colours.ink3, fontSize: 11 },
      splitLine: { lineStyle: { color: colours.lineSoft } },
      min: spec.min === undefined ? undefined : spec.min,
      max: spec.max === undefined ? undefined : spec.max,
    };
  }

  /* --------------------------------------------------------------- line */

  function lineOption(spec, colours) {
    var series = [];
    var places = decimals(spec.format);

    for (var i = 0; i < spec.series.length; i++) {
      var one = spec.series[i];
      var colour = visible(one.color || colours.accent, colours.surface);
      var rows = one.data || [];
      // `spec.kind` is what the skin's `type = bar` arrives as. A
      // series may still override it -- a combined chart draws rain as
      // bars against temperature as a line.
      var kind = one.type || spec.kind || "line";

      if (kind === "bar") {
        series.push({
          name: one.label,
          type: "bar",
          data: points(rows),
          barMaxWidth: "80%",
          barCategoryGap: "12%",
          itemStyle: { color: colour, borderRadius: [3, 3, 0, 0] },
          yAxisIndex: one.axis || 0,
        });
        continue;
      }

      series.push({
        name: one.label,
        type: "line",
        data: points(rows),
        yAxisIndex: one.axis || 0,
        // `natural` in the skin's config means a monotone spline: a curve
        // that never overshoots a reading it was given. `smooth: true`
        // would, and an overshoot on a temperature chart is a value the
        // station never recorded.
        smooth: spec.curve === "natural" ? 0.35 : false,
        smoothMonotone: "x",
        showSymbol: false,
        symbolSize: 6,
        // Points on hover only: at five-minute resolution a day is 288 of
        // them and the line disappears underneath.
        emphasis: { focus: "series", scale: 1.6 },
        connectNulls: false,
        lineStyle: { color: colour, width: spec.lineWidth || 2 },
        itemStyle: { color: colour },
        areaStyle: spec.area ? {
          opacity: 1,
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: fade(colour, spec.areaOpacity || 0.22) },
              { offset: 1, color: fade(colour, 0) },
            ],
          },
        } : undefined,
        markLine: spec.marker === undefined ? undefined : {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: spec.markerColor || colours.ink3, type: [4, 4] },
          data: [{ yAxis: spec.marker }],
        },
      });
    }

    var axes = [valueAxis(colours, spec, 0)];
    if (spec.units && spec.units.length > 1 &&
        spec.series.some(function (s) { return s.axis === 1; })) {
      var second = valueAxis(colours, spec, 1);
      second.position = "right";
      second.splitLine = { show: false };
      axes.push(second);
    }

    var option = base(colours, spec);
    option.xAxis = timeAxis(colours, spec);
    option.yAxis = axes;
    option.series = series;

    // A key only where it says something. With one line the heading above
    // the chart has already named it.
    if (spec.series.length > 1) {
      option.legend = {
        top: 0,
        right: 0,
        icon: "roundRect",
        itemWidth: 9,
        itemHeight: 9,
        itemGap: 14,
        textStyle: { color: colours.ink2, fontSize: 11 },
        data: spec.series.map(function (one) { return one.label; }),
      };
      option.grid.top = 34;
    }
    option.tooltip.formatter = function (params) {
      if (!params.length) return "";
      var when = strftime(new Date(params[0].value[0]),
                          spec.tooltipFormat || "%x %X", spec.locale);
      var lines = ['<div style="font-weight:600;margin-bottom:4px">' +
                   escapeHtml(when) + "</div>"];
      params.forEach(function (item) {
        var unit = (spec.units && spec.units[item.seriesIndex]) ||
                   (spec.units && spec.units[0]) || "";
        lines.push(
          '<div style="display:flex;gap:8px;align-items:center">' +
          '<span style="width:8px;height:8px;border-radius:2px;background:' +
          item.color + '"></span>' +
          "<span>" + escapeHtml(item.seriesName || "") + "</span>" +
          '<b style="margin-left:auto;font-variant-numeric:tabular-nums">' +
          fixed(item.value[1], places, spec.locale) + escapeHtml(unit) +
          "</b></div>");
      });
      return lines.join("");
    };

    // Night shading, where the page knows where the sun was. Drawn behind
    // everything as a band rather than a series, so it never appears in a
    // legend or a tooltip.
    if (spec.night && spec.night.length) {
      option.series.push({
        type: "line",
        data: [],
        silent: true,
        markArea: {
          silent: true,
          itemStyle: { color: colours.night, opacity: 0.55 },
          data: spec.night.map(function (band) {
            return [{ xAxis: band[0] * 1000 }, { xAxis: band[1] * 1000 }];
          }),
        },
      });
    }

    return option;
  }

  function fade(colour, alpha) {
    // The tokens are hsl(); a colour with an alpha of zero has to keep its
    // hue or the gradient runs to grey on its way out.
    if (/^hsl/i.test(colour)) {
      return colour.replace(/^hsla?\(/i, "hsla(").replace(/\)$/, " / " + alpha + ")");
    }
    if (/^#/.test(colour)) {
      var hex = colour.slice(1);
      if (hex.length === 3) {
        hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
      }
      var n = parseInt(hex, 16);
      return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," +
             (n & 255) + "," + alpha + ")";
    }
    return colour;
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* ------------------------------------------------------------- vector */

  /* Wind direction as arrows along the time axis. WeeWX's convention, and
   * it is not obvious: a wind *from* the north is drawn as an arrow
   * pointing south, because that is the way the air is going. */
  function vectorOption(spec, colours) {
    var option = base(colours, spec);
    var rows = spec.series[0].data || [];
    var data = [];
    for (var i = 0; i < rows.length; i++) {
      if (rows[i][2] === null || rows[i][2] === undefined) continue;
      data.push([rows[i][0] * 1000, rows[i][2]]);
    }

    option.xAxis = timeAxis(colours, spec);
    option.yAxis = {
      type: "value",
      min: 0, max: 360, interval: 90,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: colours.ink3, fontSize: 11,
        formatter: function (value) {
          // Sixteen points over 360 degrees: one is 22.5, not 45. The
          // wrong divisor put east where north-east belongs.
          var at = Math.round(value / 22.5) % 16;
          return (spec.ordinals && spec.ordinals[at]) || value + "°";
        },
      },
      splitLine: { lineStyle: { color: colours.lineSoft } },
    };
    option.series = [{
      type: "scatter",
      data: data,
      symbol: "path://M12 2 L16 12 L12 9.5 L8 12 Z",
      symbolSize: 13,
      symbolRotate: function (value) { return -value[1]; },
      itemStyle: {
        color: visible(spec.series[0].color || colours.accent,
                       colours.surface),
      },
    }];
    option.tooltip.formatter = function (params) {
      var item = params[0];
      var degrees = item.value[1];
      var name = (spec.ordinals && spec.ordinals[Math.round(degrees / 22.5) % 16]);
      return escapeHtml(strftime(new Date(item.value[0]),
                                 spec.tooltipFormat || "%x %X", spec.locale)) +
             "<br><b>" + Math.round(degrees) + "°" +
             (name ? " " + escapeHtml(name) : "") + "</b>";
    };
    return option;
  }

  /* ---------------------------------------------------------- wind rose */

  /* The chart a megabyte of Plotly was loaded for. Sixteen compass points
   * around, one stacked bar per speed band. */
  function roseOption(spec, colours) {
    var option = base(colours, spec);
    delete option.grid;
    option.tooltip.trigger = "item";
    option.angleAxis = {
      type: "category",
      data: spec.ordinals || [],
      startAngle: 90,
      // Clockwise from north, which is how a compass reads and how every
      // wind vane is marked.
      clockwise: true,
      axisLine: { lineStyle: { color: colours.line } },
      axisTick: { show: false },
      axisLabel: { color: colours.ink2, fontSize: 11 },
      splitLine: { show: true, lineStyle: { color: colours.lineSoft } },
    };
    option.radiusAxis = {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: colours.ink3, fontSize: 10,
        formatter: function (value) { return value + "%"; },
      },
      splitLine: { lineStyle: { color: colours.lineSoft } },
    };
    option.polar = { radius: ["8%", "72%"] };
    option.legend = {
      bottom: 0,
      itemWidth: 10, itemHeight: 10, itemGap: 12,
      textStyle: { color: colours.ink2, fontSize: 11 },
    };
    option.series = (spec.bands || []).map(function (band) {
      return {
        name: band.label,
        type: "bar",
        coordinateSystem: "polar",
        stack: "rose",
        data: band.data,
        itemStyle: { color: visible(band.color, colours.surface) },
        emphasis: { focus: "series" },
      };
    });
    option.tooltip.formatter = function (item) {
      return "<b>" + escapeHtml(item.name) + "</b><br>" +
             escapeHtml(item.seriesName) + ": " +
             fixed(item.value, 1, spec.locale) + "%";
    };
    return option;
  }

  /* -------------------------------------------------------------- gauge */

  function gaugeOption(spec, colours) {
    var places = decimals(spec.format);
    return {
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      series: [{
        type: "gauge",
        min: spec.min, max: spec.max,
        startAngle: 210, endAngle: -30,
        radius: "94%",
        center: ["50%", "58%"],
        progress: {
          show: true, width: 10, roundCap: true,
          itemStyle: {
            color: visible(spec.color || colours.accent, colours.surface),
          },
        },
        axisLine: {
          roundCap: true,
          lineStyle: { width: 10, color: [[1, colours.lineSoft]] },
        },
        pointer: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { distance: 14, color: colours.ink3, fontSize: 10 },
        anchor: { show: false },
        title: { show: false },
        detail: {
          offsetCenter: [0, "-4%"],
          fontSize: 26,
          fontWeight: 600,
          fontFamily: colours.font,
          color: colours.ink,
          formatter: function (value) {
            return fixed(value, places, spec.locale) + (spec.unit || "");
          },
        },
        data: [{ value: spec.value }],
      }],
    };
  }

  /* ----------------------------------------------------------- calendar */

  function calendarOption(spec, colours) {
    var values = (spec.data || []).map(function (row) { return row[1]; })
      .filter(function (v) { return v !== null && v !== undefined; });
    var low = values.length ? Math.min.apply(null, values) : 0;
    var high = values.length ? Math.max.apply(null, values) : 1;
    var places = decimals(spec.format);

    // One calendar per year the data covers. A single range across ten
    // years is 520 week-columns in a row; a year each is the shape the
    // data has, and years stack.
    var years = [];
    (spec.data || []).forEach(function (row) {
      var year = String(row[0]).slice(0, 4);
      if (years.indexOf(year) === -1) years.push(year);
    });
    years.sort();
    if (!years.length) years = [String(new Date().getFullYear())];

    // Sideways where there is no room. Fifty-three columns of sixteen
    // pixels is 850 wide; a phone is 390, the canvas does not scroll, and
    // the months past April were simply not on screen.
    var narrow = window.matchMedia("(max-width: 34rem)").matches;
    var ROW = narrow ? 660 : 140;

    var calendars = years.map(function (year, index) {
      return {
        orient: narrow ? "vertical" : "horizontal",
        top: 40 + index * ROW,
        left: narrow ? 46 : 44,
        right: narrow ? 10 : undefined,
        // Upright: seven columns share the width, and the height is what
        // fifty-two weeks need. Wide: a square, because a day stretched
        // across a card is not a day.
        cellSize: narrow ? ["auto", 11] : [16, 16],
        range: year,
        splitLine: { show: false },
        itemStyle: {
          color: colours.surface,
          borderColor: colours.line,
          borderWidth: 1,
        },
        yearLabel: {
          show: years.length > 1,
          position: narrow ? "top" : "left",
          margin: narrow ? 20 : 30,
          color: colours.ink2,
          fontSize: 12,
          fontWeight: 600,
        },
        dayLabel: {
          color: colours.ink3, fontSize: 10, firstDay: 1,
          nameMap: spec.days || undefined,
        },
        monthLabel: {
          color: colours.ink3, fontSize: 11,
          nameMap: spec.months || undefined,
        },
      };
    });

    return {
      // How tall the whole thing has to be. Read by `build`, which sets
      // the element's height before ECharts measures it.
      height: 40 + years.length * ROW + 40,
      tooltip: {
        backgroundColor: colours.surface,
        borderColor: colours.line,
        borderWidth: 1,
        textStyle: { color: colours.ink, fontSize: 12 },
        extraCssText: "border-radius:10px;box-shadow:0 8px 24px -8px rgba(0,0,0,.25)",
        formatter: function (item) {
          var when = String(item.value[0]);
          var parts = when.split("-");
          var shown = parts.length === 3
            ? strftime(new Date(+parts[0], +parts[1] - 1, +parts[2]),
                       "%x", spec.locale)
            : when;
          return escapeHtml(shown) + "<br><b>" +
                 fixed(item.value[1], places, spec.locale) +
                 escapeHtml(spec.unit || "") + "</b>";
        },
      },
      visualMap: {
        min: low, max: high,
        calculable: false,
        orient: "horizontal",
        left: narrow ? "center" : 44,
        bottom: 0,
        itemWidth: 12, itemHeight: 100,
        textStyle: { color: colours.ink3, fontSize: 11 },
        inRange: { color: spec.colors || [colours.surface, colours.accent] },
        formatter: function (value) {
          return fixed(value, places, spec.locale);
        },
      },
      calendar: calendars,
      series: years.map(function (year, index) {
        return {
          type: "heatmap",
          coordinateSystem: "calendar",
          calendarIndex: index,
          data: (spec.data || []).filter(function (row) {
            return String(row[0]).slice(0, 4) === year;
          }),
        };
      }),
    };
  }

  /* ------------------------------------------------------ month matrix */

  /* Months across, years down. What a day-per-square calendar becomes
   * once the span is longer than a year: twelve columns whatever happens,
   * one row per year, and it fits a phone at twenty years. */
  function matrixOption(spec, colours) {
    var values = (spec.data || []).map(function (row) { return row[2]; });
    var low = values.length ? Math.min.apply(null, values) : 0;
    var high = values.length ? Math.max.apply(null, values) : 1;
    var places = decimals(spec.format);
    var years = spec.years || [];
    var months = spec.months || [];

    // A row per year, plus the header above and the key below. Measured
    // rather than guessed: at 26 the last year was clipped and the key
    // was drawn on top of it.
    var ROW = 34;
    var HEAD = 40;
    // No figures in the squares. The colour behind them runs the whole
    // scale, so no single ink reads on all of them, and an outline thick
    // enough to fix that eats a ten-pixel digit. The exact numbers are in
    // the table below this chart and in the tooltip; what a heat map is
    // for is the shape.
    // No key under the grid. Reserving room for one means predicting how
    // ECharts will divide the rows, and every number tried was wrong by
    // enough to draw the key across the last year. The tooltip names the
    // value and the table under this chart has all of them, so the key
    // was carrying nothing the page did not already say.
    var KEY = 16;
    return {
      height: HEAD + years.length * ROW + KEY,
      animation: false,
      textStyle: { fontFamily: colours.font, color: colours.ink2 },
      grid: {
        // Explicit margins, not `containLabel`. With that on, ECharts
        // grows the grid to fit the axis labels and the last year is
        // pushed off the bottom of the canvas -- eleven years of data
        // drawing ten rows.
        top: HEAD, bottom: KEY, left: 44, right: 8, containLabel: false,
      },
      tooltip: {
        backgroundColor: colours.surface,
        borderColor: colours.line,
        borderWidth: 1,
        textStyle: { color: colours.ink, fontSize: 12 },
        extraCssText: "border-radius:10px;box-shadow:0 8px 24px -8px rgba(0,0,0,.25)",
        formatter: function (item) {
          return escapeHtml(months[item.value[0]] || "") + " " +
                 escapeHtml(years[item.value[1]] || "") + "<br><b>" +
                 fixed(item.value[2], places, spec.locale) +
                 escapeHtml(spec.unit || "") + "</b>";
        },
      },
      xAxis: {
        type: "category",
        data: months,
        position: "top",
        splitArea: { show: true },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: colours.ink3, fontSize: 11 },
      },
      yAxis: {
        type: "category",
        data: years,
        inverse: true,
        splitArea: { show: true },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: colours.ink2, fontSize: 11 },
      },
      // The palette, applied without a key: `visualMap` still maps the
      // values, it is simply not drawn.
      visualMap: {
        min: low, max: high,
        show: false,
        inRange: { color: spec.colors || [colours.surface, colours.accent] },
      },
      series: [{
        type: "heatmap",
        data: spec.data || [],
        itemStyle: { borderColor: colours.surface, borderWidth: 2 },
        emphasis: { itemStyle: { borderColor: colours.ink, borderWidth: 1 } },
        // The number in the square where there is room for it. A grid of
        // colours with no figures is a picture; with them it is a table
        // you can also see the shape of.
        label: { show: false },
      }],
    };
  }

  /* ----------------------------------------------------------- building */

  var BUILDERS = {
    line: lineOption,
    bar: lineOption,
    vector: vectorOption,
    windrose: roseOption,
    gauge: gaugeOption,
    calendar: calendarOption,
    matrix: matrixOption,
  };

  function build(element) {
    var spec;
    try {
      spec = JSON.parse(element.getAttribute("data-chart"));
    } catch (e) {
      // A chart that cannot be read leaves a message where it would have
      // been. Silence here reads as "the station has no data", which is a
      // different and much worse thing to say.
      element.textContent = "chart data could not be read";
      element.classList.add("muted");
      return;
    }
    if (!spec) return;

    // The series themselves are written as globals by the template, one
    // per chart, because a page has forty of them and inlining each into
    // an attribute would repeat every timestamp.
    if (spec.series) {
      spec.series.forEach(function (one) {
        if (typeof one.data === "string") one.data = window[one.data] || [];
      });
    }
    if (typeof spec.data === "string") spec.data = window[spec.data] || [];

    var builder = BUILDERS[spec.kind || "line"] || lineOption;
    var option = builder(spec, palette());
    // A calendar is as tall as the number of years it covers, and ECharts
    // measures the element rather than growing it.
    if (option.height) element.style.height = option.height + "px";
    var chart = echarts.init(element, null, { renderer: "canvas" });
    chart.setOption(option);
    charts.push({ chart: chart, element: element, spec: spec, builder: builder });
    return chart;
  }

  function drawAll() {
    document.querySelectorAll("[data-chart]").forEach(build);
  }

  function redraw() {
    var colours = palette();
    charts.forEach(function (one) {
      var option = one.builder(one.spec, colours);
      if (option.height) one.element.style.height = option.height + "px";
      one.chart.setOption(option, true);
      if (option.height) one.chart.resize();
    });
  }

  function relayout() {
    charts.forEach(function (one) { one.chart.resize(); });
  }

  window.addEventListener("deck:themechange", redraw);
  window.addEventListener("deck:relayout", relayout);
  window.addEventListener("resize", debounce(relayout, 150));

  // A calendar is laid out differently on a narrow screen, and that is a
  // rebuild rather than a resize. Only when the answer actually changes,
  // so an ordinary window drag stays cheap.
  var narrowNow = window.matchMedia("(max-width: 34rem)");
  var onNarrow = function () {
    if (charts.some(function (one) { return one.spec.kind === "calendar"; })) {
      redraw();
    }
  };
  if (narrowNow.addEventListener) narrowNow.addEventListener("change", onNarrow);
  else if (narrowNow.addListener) narrowNow.addListener(onNarrow);

  function debounce(fn, wait) {
    var timer;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", drawAll);
  } else {
    drawAll();
  }

  window.deckCharts = { redraw: redraw, relayout: relayout, all: charts };
})();

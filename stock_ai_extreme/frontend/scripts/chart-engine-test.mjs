/*
 * Chart engine test harness (Phase 11).
 *
 * The charting engine is deliberately pure — maths, OHLCV normalization,
 * geometry and the Plotly model contain no React and no DOM — so it can be
 * exercised directly in Node. This script bundles only those modules with the
 * project's own esbuild (already a dependency of vite), imports the result and
 * asserts the behaviour the spec depends on:
 *
 *   §6   OHLCV normalization (duplicates, ordering, malformed, repair, volume)
 *   §9   indicator calculations are correct and honour "insufficient history"
 *   §10  SMA      §11  EMA      §12  VWAP      §13  Bollinger Bands
 *   §16  drawings live in data space and stay there when they move
 *   §21  price levels are attached to a price, not a pixel
 *   §5   chart styles produce the traces they promise
 *
 * Usage:  node scripts/chart-engine-test.mjs
 * Exit code 1 means at least one assertion failed.
 */
import esbuild from "esbuild";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const engineDir = path.join(root, "src", "lib", "charting");

// Modules under test. `dataSource.ts` is excluded on purpose: it talks to the
// HTTP service layer and is covered by the browser audit instead.
const MODULES = ["math", "indicators", "ohlcv", "geometry", "drawings", "defaults", "plotModel", "annotations"];

// ---------------------------------------------------------------- tiny runner

let passed = 0;
const failures = [];

function check(name, condition, detail = "") {
  if (condition) {
    passed += 1;
    return true;
  }
  failures.push(`${name}${detail ? ` — ${detail}` : ""}`);
  return false;
}

function near(a, b, epsilon = 1e-6) {
  return typeof a === "number" && typeof b === "number" && Math.abs(a - b) <= epsilon;
}

function eq(name, actual, expected) {
  return check(name, Object.is(actual, expected) || actual === expected, `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

function nearCheck(name, actual, expected, epsilon = 1e-6) {
  return check(name, near(actual, expected, epsilon), `expected ~${expected}, got ${actual}`);
}

function throws(fn) {
  try {
    fn();
    return false;
  } catch {
    return true;
  }
}

// ------------------------------------------------------------------- bundling

async function loadEngine() {
  const toPosix = (p) => p.split(path.sep).join("/");
  const entrySource = MODULES.map(
    (name) => `export * from ${JSON.stringify(toPosix(path.join(engineDir, `${name}.ts`)))};`
  ).join("\n");

  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "chart-engine-"));
  const entry = path.join(workDir, "entry.ts");
  fs.writeFileSync(entry, entrySource, "utf8");

  const outfile = path.join(workDir, "engine.mjs");
  await esbuild.build({
    entryPoints: [entry],
    outfile,
    bundle: true,
    format: "esm",
    platform: "node",
    target: ["node18"],
    logLevel: "warning",
  });

  const mod = await import(pathToFileURL(outfile).href);
  return { mod, cleanup: () => fs.rmSync(workDir, { recursive: true, force: true }) };
}

// ----------------------------------------------------------------------- main

const { mod, cleanup } = await loadEngine();
const {
  // math
  mean,
  stdev,
  rollingMean,
  rollingStdev,
  toFiniteNumber,
  // plot model — pure user-zoom interpretation (see §21/§26)
  interpretRelayout,
  // indicators
  calculateSMA,
  calculateEMA,
  calculateVWAP,
  calculateBollingerBands,
  computeIndicators,
  indicatorLabel,
  lineValueAt,
  VWAP_UNAVAILABLE_REASON,
  // ohlcv
  normalizeOHLCV,
  parseTimestamp,
  historyRowsToRaw,
  psxPointsToRaw,
  // geometry
  makeTransform,
  toPixel,
  toData,
  priceToY,
  yToPrice,
  drawingGeometry,
  hitTest,
  anchorAt,
  boundsOfCandles,
  // drawings
  createDrawing,
  createPriceLevel,
  translateDrawing,
  moveAnchor,
  nudgeDuplicatePrice,
  sortPriceLevels,
  priceLevelMeta,
  priceLevelDisplayText,
  formatPrice,
  // defaults
  defaultIndicators,
  createChartInstance,
  datasetFitKey,
  isIntradayRange,
  // plot model
  defaultRange,
  fitRangeForX,
  axisRangeFor,
  parseAxisX,
  pricePaneRect,
  priceDomain,
  barWidthMs,
  tickFormatFor,
  buildTraces,
  buildLayout,
  shouldShowVolume,
  resolveInitialRange,
  nearestIndexByTime,
  // annotations
  buildDrawingLayers,
  buildPriceLevelLayers,
  hitTestDrawings,
  hitTestPriceLevels,
} = mod;

const THEME = {
  text: "#fff",
  textDim: "#aaa",
  grid: "rgba(1,1,1,.1)",
  spike: "rgba(1,1,1,.2)",
  tooltipBg: "#000",
  tooltipBorder: "#333",
  tooltipText: "#fff",
  up: "#0f0",
  down: "#f00",
  volume: "rgba(0,0,255,.4)",
  line: "#08f",
  accent: "#08f",
};

const DAY = 86_400_000;
/** Build a normalized candle series with explicit, easy-to-reason values. */
function series(closes, { volume = 1000, start = Date.UTC(2024, 0, 1), step = DAY } = {}) {
  return closes.map((close, index) => {
    const open = index === 0 ? close : closes[index - 1];
    const high = Math.max(open, close) + 1;
    const low = Math.min(open, close) - 1;
    return {
      timestamp: start + index * step,
      open,
      high,
      low,
      close,
      volume,
      hasVolume: volume !== null,
    };
  });
}

// ------------------------------------------------------------- §6 normalization

{
  const dataset = normalizeOHLCV([
    { timestamp: "2024-05-02", open: 10, high: 12, low: 9, close: 11, volume: 500 },
    { timestamp: "2024-05-01", open: 9, high: 11, low: 8, close: 10, volume: 400 },
    { timestamp: "2024-05-02", open: 10, high: 13, low: 9, close: 12, volume: 700 },
    { timestamp: "bad-date", open: 10, high: 12, low: 9, close: 11, volume: 1 },
    { timestamp: "2024-05-03", open: 12, high: 5, low: 20, close: 13, volume: 900 },
  ]);

  eq("normalizer keeps only valid rows", dataset.points.length, 3);
  eq("normalizer counts rejected rows", dataset.stats.rejected, 1);
  eq("normalizer counts duplicate timestamps", dataset.stats.duplicates, 1);
  eq("normalizer counts out-of-order rows", dataset.stats.outOfOrder, 1);
  eq("normalizer repairs incoherent OHLC rows", dataset.stats.repaired, 1);
  check(
    "normalizer output is chronological",
    dataset.points[0].timestamp < dataset.points[1].timestamp && dataset.points[1].timestamp < dataset.points[2].timestamp
  );
  nearCheck("duplicate keeps the last print", dataset.points[1].close, 12);
  const repaired = dataset.points[2];
  check("repaired candle has a coherent range", repaired.high >= Math.max(repaired.open, repaired.close) && repaired.low <= Math.min(repaired.open, repaired.close));
  eq("repair never invents volume", dataset.stats.missingVolume, 0);
}

{
  const dataset = normalizeOHLCV([
    { timestamp: 1_700_000_000, open: 1, high: 2, low: 0.5, close: 1.5 },
    { timestamp: 1_700_086_400_000, open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 },
  ]);
  eq("missing volume is recorded, not fabricated", dataset.stats.missingVolume, 1);
  const withoutVolume = dataset.points.find((p) => !p.hasVolume);
  check("missing volume becomes hasVolume=false with 0 volume", Boolean(withoutVolume) && withoutVolume.volume === 0);
  const withSeconds = parseTimestamp(1_700_000_000);
  const withMillis = parseTimestamp(1_700_000_000_000);
  eq("epoch seconds and milliseconds normalize to the same instant", withSeconds, withMillis);
}

{
  eq("calendar dates parse as UTC midnight", parseTimestamp("2024-05-01"), Date.UTC(2024, 4, 1));
  check("space-separated datetimes parse", Number.isFinite(parseTimestamp("2024-05-01 10:30")));
  eq("garbage timestamps are rejected", parseTimestamp("not-a-date"), null);
  eq("numeric strings coerce", toFiniteNumber("12.5"), 12.5);
  eq("empty strings do not coerce", toFiniteNumber(""), null);

  const rows = historyRowsToRaw([{ date: "2024-05-01", Open: 1, High: 2, Low: 0.5, Close: 1.5, Volume: 10 }]);
  eq("history adapter maps the API row shape", rows[0].open, 1);
  const psx = psxPointsToRaw([{ time: "2024-05-01 10:00", open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 }]);
  eq("index adapter maps the PSX point shape", psx[0].close, 1.5);
}

// ----------------------------------------------------------------- §9-§13 maths

{
  const values = [1, 2, 3, 4, 5];
  const sma3 = calculateSMA(values, 3);
  eq("SMA has no value before the window completes (1)", sma3[0], null);
  eq("SMA has no value before the window completes (2)", sma3[1], null);
  nearCheck("SMA(3) first value", sma3[2], 2);
  nearCheck("SMA(3) last value", sma3[4], 4);
  const sma10 = calculateSMA(values, 10);
  check("SMA returns nulls when history is insufficient", sma10.every((v) => v === null));
  eq("SMA output aligns with the input length", sma10.length, values.length);
  eq("SMA tolerates a non-positive period", calculateSMA(values, 0)[0], null);

  const ema3 = calculateEMA(values, 3);
  eq("EMA has no value before the seed window", ema3[1], null);
  nearCheck("EMA seeds from the SMA of the first window", ema3[2], 2);
  nearCheck("EMA applies k = 2/(n+1)", ema3[3], 3);
  nearCheck("EMA continues smoothly", ema3[4], 4);
  check("EMA is null for insufficient history", calculateEMA([1, 2], 5).every((v) => v === null));

  const flat = calculateBollingerBands([5, 5, 5, 5, 5], 3, 2);
  nearCheck("Bollinger middle band is the SMA", flat.middle[4], 5);
  nearCheck("Bollinger bands collapse on a flat series (upper)", flat.upper[4], 5);
  nearCheck("Bollinger bands collapse on a flat series (lower)", flat.lower[4], 5);
  const rising = calculateBollingerBands([1, 2, 3, 4, 5], 4, 2);
  const window4 = [2, 3, 4, 5];
  const sd = stdev(window4);
  nearCheck("Bollinger upper = SMA + 2σ", rising.upper[4], mean(window4) + 2 * sd, 1e-9);
  nearCheck("Bollinger lower = SMA − 2σ", rising.lower[4], mean(window4) - 2 * sd, 1e-9);

  const vwapSeries = [
    { timestamp: 1, open: 9, high: 11, low: 9, close: 10, volume: 100, hasVolume: true },
    { timestamp: 2, open: 10, high: 13, low: 11, close: 12, volume: 300, hasVolume: true },
  ];
  const vwap = calculateVWAP(vwapSeries);
  const firstTypical = (11 + 9 + 10) / 3;
  const secondTypical = (13 + 11 + 12) / 3;
  nearCheck("VWAP(1) is the first typical price", vwap[0], firstTypical);
  nearCheck("VWAP is volume weighted", vwap[1], (firstTypical * 100 + secondTypical * 300) / 400);
  const noVolume = calculateVWAP(vwapSeries.map((c) => ({ ...c, volume: 0, hasVolume: false })));
  check("VWAP refuses to fabricate a value without volume", noVolume.every((v) => v === null));

  nearCheck("rollingMean tracks a window", rollingMean([1, 2, 3], 2)[2], 2.5);
  nearCheck("rollingStdev is 0 for a constant window", rollingStdev([2, 2, 2], 3)[2], 0);
}

// --------------------------------------------------- §12/§14 indicator engine

{
  const candles = series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35]);
  const configs = defaultIndicators();
  eq("default catalog enables SMA 20 and SMA 50, nothing else", configs.filter((c) => c.enabled).map((c) => c.id).join(","), "SMA:20,SMA:50");
  eq("indicator labels read like the spec", indicatorLabel(configs[0]), "SMA 20");
  eq("Bollinger label carries the multiplier", indicatorLabel({ type: "BB", period: 20, stdDev: 2 }), "BB 20 / 2");

  const daily = computeIndicators(candles, configs, { intraday: false, datasetKey: "daily" });
  eq("enabled indicators produce a line each", daily.lines.length, 2);
  const sma20 = daily.lines.find((l) => l.indicatorId === "SMA:20");
  nearCheck("SMA 20 line value", lineValueAt(sma20, 19), mean(candles.slice(0, 20).map((c) => c.close)));
  eq("SMA 20 has no value before bar 20", lineValueAt(sma20, 18), null);
  const sma50 = daily.lines.find((l) => l.indicatorId === "SMA:50");
  check("SMA 50 stays undefined on a 26-bar dataset", sma50.values.every((v) => v === null));

  const vwapDaily = computeIndicators(candles, [{ id: "VWAP", type: "VWAP", enabled: true, period: 1, color: "#fff", lineWidth: 1 }], {
    intraday: false,
    datasetKey: "daily-vwap",
  });
  eq("VWAP on daily bars reports why it is unavailable", vwapDaily.unavailable[0]?.reason, VWAP_UNAVAILABLE_REASON);
  eq("VWAP draws nothing when unavailable", vwapDaily.lines.length, 0);

  const intradayCandles = series([10, 11, 10.5, 11.5], { step: 300_000 });
  const vwapIntraday = computeIndicators(intradayCandles, [{ id: "VWAP", type: "VWAP", enabled: true, period: 1, color: "#fff", lineWidth: 1 }], {
    intraday: true,
    datasetKey: "intra-vwap",
  });
  eq("VWAP draws one line intraday", vwapIntraday.lines.length, 1);
  check("VWAP value is finite intraday", Number.isFinite(vwapIntraday.lines[0].values[3]));

  const bb = computeIndicators(
    candles,
    [{ id: "BB:20", type: "BB", enabled: true, period: 20, stdDev: 2, color: "#0f0", lineWidth: 1.2 }],
    { intraday: false, datasetKey: "bb" }
  );
  eq("Bollinger builds three lines", bb.lines.length, 3);
  eq("Bollinger exposes upper/middle/lower roles", bb.lines.map((l) => l.role).sort().join(","), "band,band,middle");
}

// ------------------------------------------------------------- §16/§21 geometry

{
  const rect = { left: 64, top: 12, width: 400, height: 300 };
  const xRange = [Date.UTC(2024, 0, 1), Date.UTC(2024, 0, 11)];
  const yRange = [90, 110];
  const tf = makeTransform(rect, xRange, yRange);
  check("transform builds for a sane frame", Boolean(tf));
  eq("transform refuses a zero-size plot area", makeTransform({ left: 0, top: 0, width: 0, height: 300 }, xRange, yRange), null);
  eq("transform refuses a degenerate range", makeTransform(rect, [1, 1], yRange), null);

  const point = { t: Date.UTC(2024, 0, 6), p: 100 };
  const pixel = toPixel(point, tf);
  nearCheck("centre of the frame maps to the centre (x)", pixel.x, rect.left + 200, 1e-6);
  nearCheck("centre of the frame maps to the centre (y)", pixel.y, rect.top + 150, 1e-6);
  const roundTrip = toData(pixel.x, pixel.y, tf);
  nearCheck("pixel → data round-trips (t)", roundTrip.t, point.t, 1e-3);
  nearCheck("pixel → data round-trips (p)", roundTrip.p, point.p, 1e-9);
  nearCheck("price → pixel Y", priceToY(110, tf), rect.top, 1e-6);
  nearCheck("pixel Y → price", yToPrice(rect.top + 300, tf), 90, 1e-9);

  const anchors = [{ t: xRange[0], p: 95 }, { t: xRange[1], p: 105 }];
  for (const type of ["trendline", "rectangle", "circle", "parabola", "semicircle"]) {
    const shape = createDrawing(type, anchors);
    const geometry = drawingGeometry(shape, tf);
    check(`${type} renders a path`, Boolean(geometry && geometry.path.startsWith("M ")));
    eq(`${type} keeps its two data-space anchors`, geometry?.anchors.length, 2);
    check(`${type} reports bounds`, Boolean(geometry && geometry.bounds.right > geometry.bounds.left));
  }

  const trendline = drawingGeometry(createDrawing("trendline", anchors), tf);
  const startPixel = toPixel(anchors[0], tf);
  check("trendline is hit-testable on its line", hitTest(trendline, startPixel.x, startPixel.y, 6));
  check("trendline is not hit-testable far away", !hitTest(trendline, startPixel.x, startPixel.y + 80, 6));
  eq("anchor hit testing finds the first handle", anchorAt(trendline, startPixel.x, startPixel.y, 9), 0);
  eq("anchor hit testing misses when far", anchorAt(trendline, startPixel.x + 60, startPixel.y, 9), -1);

  const moved = translateDrawing(createDrawing("rectangle", anchors), 2 * DAY, 5);
  nearCheck("translating a drawing shifts t", moved.coordinates[0].t, anchors[0].t + 2 * DAY, 1e-6);
  nearCheck("translating a drawing shifts p", moved.coordinates[1].p, 110);
  const resized = moveAnchor(createDrawing("trendline", anchors), 1, { t: anchors[1].t, p: 111 });
  nearCheck("moving an anchor only touches that anchor", resized.coordinates[1].p, 111);
  nearCheck("moving an anchor leaves the other one alone", resized.coordinates[0].p, 95);

  // A parabola's second anchor must genuinely sit on the curve.
  const parabolaShape = createDrawing("parabola", [
    { t: xRange[0], p: 100 },
    { t: xRange[0] + 2 * DAY, p: 104 },
  ]);
  const parabola = drawingGeometry(parabolaShape, tf);
  const guide = toPixel(parabolaShape.coordinates[1], tf);
  const onCurve = parabola.anchors.some((a) => near(a.x, guide.x, 0.6) && near(a.y, guide.y, 0.6));
  check("parabola passes through its guide anchor", onCurve || hitTest(parabola, guide.x, guide.y, 3));

  const bounds = boundsOfCandles([{ high: 12, low: 8 }, { high: 15, low: 9 }]);
  check("candle bounds pad the extremes", bounds.yMin < 8 && bounds.yMax > 15);
}

// -------------------------------------------------------- §20/§21 price levels

{
  const support = createPriceLevel("SUPPORT", 1234.5);
  eq("price level keeps its type", support.type, "SUPPORT");
  eq("a level stores a name, never a baked-in price", support.label, "Support");
  eq("the chip text is name + live price", priceLevelDisplayText(support), "Support 1,234.50");
  eq("dragging a level re-derives the chip price", priceLevelDisplayText({ ...support, price: 1300 }), "Support 1,300.00");
  eq("a renamed level keeps its name", priceLevelDisplayText({ ...support, label: "Weekly support" }), "Weekly support 1,234.50");
  eq("price level starts visible and unlocked", `${support.visible}/${support.locked}`, "true/false");
  eq("support colour comes from the catalog", priceLevelMeta("SUPPORT").color, "#72BC8F");
  eq("price formatting is 2dp with separators", formatPrice(82451.2), "82,451.20");

  const levels = [createPriceLevel("ENTRY", 100), createPriceLevel("ENTRY", 100), createPriceLevel("TARGET", 120)];
  const nudged = nudgeDuplicatePrice(levels, 100, 2);
  check("duplicate levels are nudged apart", nudged !== 100 && Math.abs(nudged - 100) >= 2);
  eq("a free price is left untouched", nudgeDuplicatePrice(levels, 110, 2), 110);
  eq("levels sort cheapest first", sortPriceLevels([{ price: 5 }, { price: 1 }].map((l) => ({ ...createPriceLevel("SUPPORT", l.price) })))[0].price, 1);

  // Price levels ride on price, so a viewport change must not move them relative
  // to their own level.
  const rect = { left: 0, top: 0, width: 100, height: 100 };
  const tfA = makeTransform(rect, [0, 10], [90, 110]);
  const tfB = makeTransform(rect, [0, 10], [50, 150]);
  nearCheck("level at mid-price is centred in both frames", priceToY(100, tfB), 50, 1e-9);
  check("level stays between the same relative bounds", priceToY(100, tfA) === 50 && priceToY(100, tfB) === 50);
}

// ---------------------------------------------------------------- §4/§5 defaults

{
  const instance = createChartInstance("chart-a", "ogdc", "STOCK", "6M");
  eq("instance symbols normalize", instance.symbol, "OGDC");
  eq("instance opens on volume candles", instance.chartType, "volume-candles");
  eq("instance starts with no annotations", `${instance.drawings.length}/${instance.priceLevels.length}`, "0/0");
  eq("instance starts without a saved viewport", instance.viewport, null);
  check("instance settings are populated", instance.settings.grid && instance.settings.legend);
  eq("intraday classification matches the timeframe system", `${isIntradayRange("1D")}/${isIntradayRange("6M")}`, "true/false");
  eq("fit key changes with the window", datasetFitKey("A", "1M", series([1, 2])) !== datasetFitKey("A", "1M", series([1, 2, 3])), true);
}

// ------------------------------------------------------------ §5/§27 plot model

{
  const candles = series(Array.from({ length: 220 }, (_, i) => 100 + Math.sin(i / 9) * 8));
  const instance = createChartInstance("chart-a", "TEST", "STOCK", "1Y");
  const lines = computeIndicators(candles, defaultIndicators(), { intraday: false, datasetKey: "plot" }).lines;

  const range = defaultRange(candles);
  check("default window is finite", Number.isFinite(range.x[0]) && Number.isFinite(range.x[1]) && range.x[0] < range.x[1]);
  check("default window shows the recent bars", range.x[1] >= candles[candles.length - 1].timestamp);
  check("default y-range brackets the visible prices", range.y[0] < Math.min(...candles.map((c) => c.low)) && range.y[1] > Math.max(...candles.map((c) => c.high)));

  const asAxis = axisRangeFor(range);
  check("axis ranges are ISO strings", typeof asAxis.x[0] === "string" && asAxis.x[0].includes("T"));
  nearCheck("axis range round-trips x", parseAxisX(asAxis.x[0]), range.x[0], 1);
  nearCheck("axis range round-trips y", asAxis.y[1], range.y[1], 1e-9);
  eq("unparseable axis input is rejected", parseAxisX("nope"), null);

  const fitted = fitRangeForX(candles, [candles[10].timestamp, candles[40].timestamp]);
  check("fit honours the requested window", fitted.x[0] <= candles[10].timestamp && fitted.x[1] >= candles[40].timestamp);

  const stored = resolveInitialRange(candles, "k1", { xRange: [1, 2], yRange: [1, 2], fitKey: "k1" });
  eq("a matching viewport is restored", stored.x[0], 1);
  eq("a stale viewport is ignored", resolveInitialRange(candles, "k2", { xRange: [1, 2], yRange: [1, 2], fitKey: "k1" }), null);
  eq("a malformed viewport is ignored", resolveInitialRange(candles, "k1", { xRange: [2, 1], yRange: [1, 2], fitKey: "k1" }), null);

  // The SVG overlay derives its rectangle from these two helpers, so they must
  // agree with the Plotly domains exactly.
  const paneRect = pricePaneRect(1000, 600, true);
  const [priceLo, priceHi] = priceDomain(true);
  const innerH = 600 - 12 - 28;
  nearCheck("overlay pane top matches the price domain", paneRect.top, 12 + innerH * (1 - priceHi), 1e-9);
  nearCheck("overlay pane height matches the price domain", paneRect.height, innerH * (priceHi - priceLo), 1e-9);
  const singlePane = pricePaneRect(1000, 600, false);
  eq("single-pane rect spans the full plot height", singlePane.height, innerH);

  check("bar width follows the sample spacing", near(barWidthMs(candles), DAY * 0.66, 1));
  eq("intraday tick format shows the clock", tickFormatFor("1D"), "%H:%M");
  eq("long-range tick format shows month + year", tickFormatFor("5Y"), "%b %y");

  // Chart styles (spec §5)
  for (const style of ["candles", "volume-candles", "line"]) {
    const styled = { ...instance, chartType: style, volumeVisible: false };
    const traces = buildTraces({ instance: styled, points: candles, lines, name: "TEST", theme: THEME });
    const priceTraces = lines.length + 1;
    eq(
      `${style} plots price plus the volume pane only when the style asks for it`,
      traces.length,
      priceTraces + (shouldShowVolume(styled) ? 1 : 0)
    );
    const hasVolume = traces.some((t) => t.yaxis === "y2");
    eq(`${style} volume trace matches shouldShowVolume`, hasVolume, shouldShowVolume(styled));
    const primary = traces[0];
    eq(`${style} primary trace x aligns with the candles`, primary.x.length, candles.length);
  }
  check("volume-candles always carries volume", shouldShowVolume({ ...instance, chartType: "volume-candles", volumeVisible: false }));
  check("line style honours the volume toggle", !shouldShowVolume({ ...instance, chartType: "line", volumeVisible: false }));

  const layout = buildLayout({
    instance,
    points: candles,
    lines,
    name: "TEST",
    theme: THEME,
    range,
    showVolume: true,
    uirevision: "test",
    dragmode: "pan",
  });
  eq("layout keeps Plotly's modebar out of the way", layout.showlegend, false);
  eq("layout targets the crosshair hover mode", layout.hovermode, "x unified");
  // Regression guard: with numeric (epoch-ms) x values Plotly infers a *linear*
  // axis and labels it with raw milliseconds, so the axis type must be declared.
  eq("the time axis is declared as a date axis", layout.xaxis.type, "date");
  check("the time axis formats its ticks as calendar dates", /%/.test(layout.xaxis.tickformat || ""));
  check("the hover readout formats its heading as a date", /%/.test(layout.xaxis.hoverformat || ""));
  check("layout carries both panes", Boolean(layout.yaxis2));
  nearCheck("volume pane leaves room for price", layout.yaxis.domain[0], 0.26, 1e-9);
  check("shared uirevision keeps user zoom across data updates", layout.uirevision === "test");
  check("price axis is explicitly ranged (no autorange fighting)", layout.yaxis.autorange === false && Array.isArray(layout.xaxis.range));
}

// ------------------------------------------- relayout / viewport interpretation

{
  const base = { x: [Date.UTC(2026, 0, 1), Date.UTC(2026, 6, 1)], y: [100, 200] };
  const iso = (t) => new Date(t).toISOString();
  const full = {
    "xaxis.range[0]": iso(Date.UTC(2026, 1, 1)),
    "xaxis.range[1]": iso(Date.UTC(2026, 2, 1)),
    "yaxis.range[0]": 120,
    "yaxis.range[1]": 180,
  };

  const zoomed = interpretRelayout(full, base);
  eq("a full relayout yields a new window", zoomed.kind, "range");
  eq("relayout parses date-axis strings", zoomed.range.x[0], Date.UTC(2026, 1, 1));
  eq("relayout keeps the reported y-range", zoomed.range.y[1], 180);

  // Plotly occasionally reports one axis at a time (shift-drag, y-only zoom).
  const xOnly = interpretRelayout({ "xaxis.range[0]": iso(Date.UTC(2026, 1, 1)), "xaxis.range[1]": iso(Date.UTC(2026, 2, 1)) }, base);
  eq("an x-only relayout is applied", xOnly.range.x[0], Date.UTC(2026, 1, 1));
  eq("an x-only relayout preserves the y window", xOnly.range.y, base.y);
  const yOnly = interpretRelayout({ "yaxis.range[0]": 90, "yaxis.range[1]": 210 }, base);
  eq("a y-only relayout preserves the x window", yOnly.range.x, base.x);
  eq("a y-only relayout is applied", yOnly.range.y[0], 90);

  // Non-zoom relayouts must never disturb the window.
  for (const [label, payload] of [
    ["a resize", { autosize: true }],
    ["a modebar action", { dragmode: "zoom" }],
    ["a legend click", { "showlegend.0": false }],
    ["an empty payload", {}],
  ]) {
    eq(`${label} is ignored`, interpretRelayout(payload, base).kind, "ignore");
  }

  // Degenerate / inverted axes are treated as "no information", never applied.
  eq("an inverted x-range is ignored", interpretRelayout({ "xaxis.range[0]": iso(2), "xaxis.range[1]": iso(1) }, base).kind, "ignore");
  eq("a zero-height y-range is ignored", interpretRelayout({ "yaxis.range[0]": 5, "yaxis.range[1]": 5 }, base).kind, "ignore");
  const halfBad = interpretRelayout({ ...full, "yaxis.range[1]": "oops" }, base);
  eq("one unusable axis still applies the other", halfBad.range.x[0], Date.UTC(2026, 1, 1));
  eq("one unusable axis keeps the previous window", halfBad.range.y, base.y);

  // Double-click / autorange is a reset, not a range.
  eq("double-click reset is recognised", interpretRelayout({ "xaxis.autorange": true, "yaxis.autorange": true }, base).kind, "reset");
  eq("a single-axis autorange also resets", interpretRelayout({ "yaxis.autorange": true }, base).kind, "reset");

  // Without a base window the only usable outcome is a fully specified one.
  eq("a partial relayout without a base is ignored", interpretRelayout({ "xaxis.range[0]": iso(1), "xaxis.range[1]": iso(2) }, null).kind, "ignore");
  eq("a full relayout without a base still applies", interpretRelayout(full, null).kind, "range");

  // Numeric (non-date) x values must round-trip too — index-like datasets.
  const numeric = interpretRelayout({ "xaxis.range[0]": 10, "xaxis.range[1]": 40, "yaxis.range[0]": 1, "yaxis.range[1]": 2 }, base);
  eq("numeric axis ranges are accepted", numeric.range.x[0], 10);
}

// ------------------------------------------------- hover index resolution

{
  const sparse = [{ timestamp: 100 }, { timestamp: 200 }, { timestamp: 300 }];
  eq("nearest bar resolves the exact hit", nearestIndexByTime(sparse, 300), 2);
  eq("nearest bar resolves forward", nearestIndexByTime(sparse, 290), 2);
  eq("nearest bar resolves backward", nearestIndexByTime(sparse, 210), 1);
  eq("nearest bar resolves before the series start", nearestIndexByTime(sparse, 0), 0);
  eq("nearest bar on an empty series is -1", nearestIndexByTime([], 100), -1);
}

// ------------------------------------------------------- annotation layer model

{
  const rect = { left: 64, top: 12, width: 400, height: 300 };
  const tf = makeTransform(rect, [Date.UTC(2024, 0, 1), Date.UTC(2024, 0, 11)], [90, 110]);
  const shapes = [
    createDrawing("trendline", [{ t: Date.UTC(2024, 0, 2), p: 95 }, { t: Date.UTC(2024, 0, 8), p: 105 }]),
    createDrawing("rectangle", [{ t: Date.UTC(2024, 0, 3), p: 96 }, { t: Date.UTC(2024, 0, 9), p: 104 }]),
  ];
  shapes[1] = { ...shapes[1], visible: false };
  const layers = buildDrawingLayers(shapes, tf);
  eq("hidden drawings are not rendered", layers.length, 1);
  eq("layers preserve drawing order", layers[0] ? 0 : -1, 0);

  const hit = hitTestDrawings(layers, toPixel(shapes[0].coordinates[0], tf).x, toPixel(shapes[0].coordinates[0], tf).y);
  check("hit testing finds a drawing", Boolean(hit) && hit.shape.id === shapes[0].id);
  eq("hit testing ignores empty space", hitTestDrawings(layers, rect.left + 5, rect.top + 295), null);

  const level = createPriceLevel("RESISTANCE", 106);
  const levelLayers = buildPriceLevelLayers([level], tf);
  eq("price levels render as one layer each", levelLayers.length, 1);
  nearCheck("price level row follows the price", levelLayers[0].y, priceToY(106, tf), 1e-9);
  check("price level hit testing finds the line", Boolean(hitTestPriceLevels(levelLayers, levelLayers[0].y, 5)));
  eq("price level hit testing ignores far rows", hitTestPriceLevels(levelLayers, levelLayers[0].y + 40, 5), null);
}

// --------------------------------------------------------------------- summary

cleanup();

console.log(`\nchart engine: ${passed} check(s) passed, ${failures.length} failed\n`);
if (failures.length) {
  failures.forEach((failure) => console.log(`  FAIL  ${failure}`));
  process.exit(1);
}
console.log("All charting-engine assertions passed.");

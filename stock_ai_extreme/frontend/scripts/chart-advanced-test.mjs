import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const __dirname = fileURLToPath(new URL("..", import.meta.url));
// Bundled output lives under node_modules/.cache so a test run never leaves
// build artifacts in the repository root.
const outDir = join(__dirname, "node_modules", ".cache", "neural-market-tests");
mkdirSync(outDir, { recursive: true });

async function bundle(relativePath, outName) {
  const outfile = join(outDir, outName);
  await build({
    entryPoints: [join(__dirname, relativePath)],
    bundle: true,
    format: "esm",
    platform: "node",
    outfile,
    logLevel: "silent",
  });
  return import(`file://${outfile}`);
}

const indicators = await bundle("src/lib/charting/indicators.ts", "chart-indicators.mjs");
const drawings = await bundle("src/lib/charting/drawings.ts", "chart-drawings.mjs");
const geometry = await bundle("src/lib/charting/geometry.ts", "chart-geometry.mjs");
const plotModel = await bundle("src/lib/charting/plotModel.ts", "chart-plotmodel.mjs");

let passed = 0;
const assert = (label, condition) => {
  if (!condition) throw new Error(`FAIL: ${label}`);
  passed += 1;
  console.log(`PASS ${label}`);
};
const closeTo = (a, b, tolerance = 1e-6) => Math.abs(a - b) <= tolerance;

// --- RSI -------------------------------------------------------------------

const rising = Array.from({ length: 40 }, (_, i) => 100 + i);
const risingRsi = indicators.calculateRSI(rising, 14);
assert("RSI is undefined before the first window", risingRsi[13] === null && risingRsi[14] !== null);
assert("RSI is 100 on a monotonic rise", closeTo(risingRsi[risingRsi.length - 1], 100, 1e-6));

const falling = Array.from({ length: 40 }, (_, i) => 200 - i);
const fallingRsi = indicators.calculateRSI(falling, 14);
assert("RSI is 0 on a monotonic fall", closeTo(fallingRsi[fallingRsi.length - 1], 0, 1e-6));

// --- MACD ------------------------------------------------------------------

const series = Array.from({ length: 120 }, (_, i) => 100 + Math.sin(i / 7) * 6 + i * 0.1);
const macd = indicators.calculateMACD(series, 12, 26, 9);
assert("MACD line warms up after the slow EMA", macd.macd[24] === null && macd.macd[25] !== null);
assert("MACD histogram equals line minus signal where both exist", (() => {
  for (let i = 0; i < series.length; i++) {
    if (macd.signal[i] !== null && macd.macd[i] !== null) {
      if (!closeTo(macd.histogram[i], macd.macd[i] - macd.signal[i], 1e-9)) return false;
    }
  }
  return true;
})());

// --- Stochastic ------------------------------------------------------------

const candles = Array.from({ length: 40 }, (_, i) => {
  const close = 100 + Math.sin(i / 5) * 4;
  return { timestamp: i * 86_400_000, open: close - 0.5, high: close + 1, low: close - 1, close, volume: 1000, hasVolume: true };
});
const stochastic = indicators.calculateStochastic(candles, 14, 3);
assert("Stochastic %K is defined after its window", stochastic.k[12] === null && stochastic.k[13] !== null);
assert("Stochastic %K stays within 0..100", stochastic.k.every((v) => v === null || (v >= 0 && v <= 100)));
assert("Stochastic %D lags %K", stochastic.d[13] === null);

const locked = indicators.calculateStochastic(
  Array.from({ length: 20 }, (_, i) => ({ timestamp: i, open: 50, high: 50, low: 50, close: 50, volume: 0, hasVolume: false })),
  14,
  3
);
assert("Stochastic handles a zero-width range without dividing by zero", locked.k[19] === 50);

// --- ATR -------------------------------------------------------------------

const atr = indicators.calculateATR(candles, 14);
assert("ATR is defined at the first complete window", atr[13] === null && atr[14] !== null);
assert("ATR is strictly positive for real bars", atr[atr.length - 1] > 0);
assert("ATR accounts for gaps (true range)", indicators.calculateATR(
  [{ timestamp: 0, open: 10, high: 11, low: 9, close: 10, volume: 0, hasVolume: false },
   { timestamp: 1, open: 20, high: 21, low: 19, close: 20, volume: 0, hasVolume: false },
   { timestamp: 2, open: 30, high: 31, low: 29, close: 30, volume: 0, hasVolume: false }],
  2
)[2] > 10);

// --- Fibonacci -------------------------------------------------------------

const a = { t: 0, p: 100 };
const b = { t: 10, p: 200 };
const retracement = drawings.fibonacciLevels(a, b, "retracement");
assert("Retracement 0% sits at the second anchor", closeTo(retracement.find((l) => l.ratio === 0).price, 200));
assert("Retracement 100% sits at the first anchor", closeTo(retracement.find((l) => l.ratio === 1).price, 100));
assert("Retracement 50% is the midpoint", closeTo(retracement.find((l) => l.ratio === 0.5).price, 150));
const extension = drawings.fibonacciLevels(a, b, "extension");
assert("Extension 161.8% projects beyond the swing", closeTo(extension.find((l) => l.ratio === 1.618).price, 100 + 100 * 1.618));

// --- Measure tool ----------------------------------------------------------

const measured = drawings.measureBetween({ t: 0, p: 100 }, { t: 4 * 86_400_000, p: 110 }, 86_400_000);
assert("Measure reports the price change", closeTo(measured.priceChange, 10));
assert("Measure reports the percent change", closeTo(measured.percentChange, 10));
assert("Measure reports the bar count", measured.bars === 4);
assert("Measure text includes the percentage", drawings.formatMeasurement(measured).includes("10.00%"));

// --- Channel / single-anchor helpers ---------------------------------------

assert("hline and vline are single-anchor shapes", drawings.isSingleAnchorShape("hline") && drawings.isSingleAnchorShape("vline"));
assert("fib-retracement needs two anchors", drawings.isAnchorShape("fib-retracement"));
const offset = drawings.channelOffsetLine(a, b, 25);
assert("Channel offset shifts both endpoints by the same price", closeTo(offset.start.p, 125) && closeTo(offset.end.p, 225));

// --- Renderable geometry ---------------------------------------------------

const rect = { left: 0, top: 0, width: 500, height: 300 };
const tf = geometry.makeTransform(rect, [0, 10], [50, 250]);
assert("Transform builds for a valid frame", tf !== null);

const hline = drawings.createDrawing("hline", [a, a]);
assert("Horizontal line renders across the full plot width", geometry.drawingGeometry(hline, tf).path.includes("M 0.00"));

const vline = drawings.createDrawing("vline", [a, a]);
assert("Vertical line renders across the full plot height", geometry.drawingGeometry(vline, tf).path.includes("L "));

const fib = drawings.createDrawing("fib-retracement", [a, b]);
const fibGeometry = geometry.drawingGeometry(fib, tf);
assert("Fibonacci renders multiple level subpaths", (fibGeometry.path.match(/M /g) || []).length >= 7);

const ray = drawings.createDrawing("ray", [a, b]);
assert("Ray extends past the second anchor", geometry.drawingGeometry(ray, tf).bounds.right > geometry.toPixel(b, tf).x);

const measure = drawings.createDrawing("measure", [a, b]);
assert("Measure renders as a closed region", geometry.drawingGeometry(measure, tf).closed === true);

// --- Sub-pane model --------------------------------------------------------

const subLines = [
  { key: "rsi", label: "RSI 14", indicatorId: "RSI", role: "main", pane: "sub", color: "#fff", width: 1, dash: "solid", values: [50] },
  { key: "sma", label: "SMA 20", indicatorId: "SMA:20", role: "main", color: "#fff", width: 1, dash: "solid", values: [100] },
];
assert("Sub-pane ids are detected once", plotModel.subPaneIndicatorIds(subLines).join(",") === "RSI");
const noSubs = plotModel.paneFractions(true, 0);
assert("With no sub-panes the volume pane is unchanged", closeTo(noSubs.priceBottom, plotModel.VOLUME_FRACTION + plotModel.PANE_GAP));
assert("With no sub-panes the price domain is unchanged", closeTo(plotModel.priceDomain(true, 0)[0], plotModel.VOLUME_FRACTION + plotModel.PANE_GAP));
const withSubs = plotModel.paneFractions(true, 2);
assert("Sub-panes push the price pane up", withSubs.priceBottom > noSubs.priceBottom);
assert("Two sub-panes get two domains", withSubs.subDomains.length === 2);
assert("Sub-pane domains are ordered bottom-up", withSubs.subDomains[0][0] < withSubs.subDomains[1][0]);
assert("Volume sits above the sub-panes", closeTo(withSubs.volumeDomain[0], withSubs.subTotal));

const smallRect = plotModel.pricePaneRect(500, 300, true, 2);
const baseRect = plotModel.pricePaneRect(500, 300, true, 0);
assert("Sub-panes shrink the annotation price rectangle", smallRect.height < baseRect.height);

console.log(`chart-advanced: ${passed} checks passed`);

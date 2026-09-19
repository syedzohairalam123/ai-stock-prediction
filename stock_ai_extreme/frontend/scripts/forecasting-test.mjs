import esbuild from "esbuild";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const outDir = mkdtempSync(join(tmpdir(), "forecasting-"));
const outfile = join(outDir, "forecasting.mjs");
await esbuild.build({
	entryPoints: [join(process.cwd(), "src/lib/forecasting.ts")], bundle: true, format: "esm", platform: "node", outfile, logLevel: "silent",
	plugins: [{ name: "axios-test-stub", setup(build) {
		build.onResolve({ filter: /axios/ }, () => ({ path: "axios-test-stub", namespace: "forecast-test" }));
		build.onLoad({ filter: /.*/, namespace: "forecast-test" }, () => ({ contents: "export default { get: async () => { throw new Error('network disabled in pure test'); } };", loader: "js" }));
	} }],
});
const forecasting = await import(pathToFileURL(outfile).href);
let passed = 0;
const check = (label, condition) => { if (!condition) throw new Error(`FAIL ${label}`); passed += 1; console.log(`PASS ${label}`); };
for (const value of [0, 1, 27, 50, 73, 99, 100]) { const result = forecasting.normalizeProbabilities(value); check(`normalizes ${value}%`, result.yesProbability === value && result.noProbability === 100 - value); }
for (const value of [NaN, Infinity, -1, 101]) { let rejected = false; try { forecasting.normalizeProbabilities(value); } catch { rejected = true; } check(`rejects invalid probability ${String(value)}`, rejected); }
const market = (await forecasting.ForecastService.getForecastMarkets())[0];
check("fallback markets are available", Boolean(market?.id));
check("fallback mode is explicit", market.dataMode === "SIMULATED");
check("history remains binary", market.history.every((point) => point.yesProbability + point.noProbability === 100));
check("history is ordered", market.history.every((point, index, all) => index === 0 || point.timestamp >= all[index - 1].timestamp));
check("sources never invent URLs", market.sources.every((source) => /^https?:\/\//.test(source.url)));
check("probability deltas use percentage points", forecasting.probabilityDelta(market.history, market.yesProbability) === Math.round((market.yesProbability - market.history[market.history.length - 2].yesProbability) * 100) / 100);
console.log(`forecasting: ${passed} checks passed`);

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const __dirname = fileURLToPath(new URL("..", import.meta.url));
const entry = join(__dirname, "src/lib/combination.ts");
const outfile = join(__dirname, "tmp-combination-test.mjs");

await build({
  entryPoints: [entry],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile,
  logLevel: "silent",
});

const combo = await import(`file://${outfile}`);
const { CombinationCalculator, CombinationService, CorrelationService } = combo;

let passed = 0;
const assert = (label, condition) => {
  if (!condition) {
    throw new Error(`FAIL: ${label}`);
  }
  passed += 1;
  console.log(`PASS ${label}`);
};

assert("single selection computes correctly", Math.abs(CombinationCalculator.calculateCombinedProbability([73]) - 73) < 0.0001);
assert("two independent events compute correctly", Math.abs(CombinationCalculator.calculateCombinedProbability([73, 64]) - 46.7) < 0.11);
assert("three independent events compute correctly", Math.abs(CombinationCalculator.calculateCombinedProbability([73, 64, 81]) - 37.8) < 0.11);
assert("zero probability remains valid", CombinationCalculator.calculateCombinedProbability([0]) === 0);
assert("one hundred percent remains valid", CombinationCalculator.calculateCombinedProbability([100]) === 100);
assert("duplicate market prevented", (() => {
  try {
    CombinationService.addSelection([], { id: "m1", title: "A", category: "Tech", status: "OPEN", updatedAt: new Date().toISOString(), yesProbability: 73, noProbability: 27 }, "YES");
    CombinationService.addSelection([{ marketId: "m1", outcome: "YES", probability: 73, probabilitySnapshot: 73, addedAt: new Date().toISOString() }], { id: "m1", title: "A", category: "Tech", status: "OPEN", updatedAt: new Date().toISOString(), yesProbability: 73, noProbability: 27 }, "NO");
    return false;
  } catch {
    return true;
  }
})());
assert("resolved market is rejected", (() => {
  try {
    CombinationService.addSelection([], { id: "m2", title: "Resolved", category: "Finance", status: "RESOLVED", updatedAt: new Date().toISOString(), resolution: "YES", yesProbability: 100, noProbability: 0 }, "YES");
    return false;
  } catch {
    return true;
  }
})());
assert("invalid probability is rejected", (() => {
  try {
    CombinationCalculator.calculateCombinedProbability([101]);
    return false;
  } catch {
    return true;
  }
})());
assert("missing probability is rejected", (() => {
  try {
    CombinationService.addSelection([], { id: "m3", title: "Missing", category: "Finance", status: "OPEN", updatedAt: new Date().toISOString() }, "YES");
    return false;
  } catch {
    return true;
  }
})());
assert("correlation warning is surfaced", CorrelationService.detectPotentialCorrelation([
  { marketId: "m1", outcome: "YES", probability: 70, probabilitySnapshot: 70, addedAt: Date.now().toString() },
  { marketId: "m2", outcome: "YES", probability: 75, probabilitySnapshot: 75, addedAt: Date.now().toString() },
], [
  { id: "m1", title: "Major product launch event this quarter", category: "Tech", status: "OPEN", updatedAt: new Date().toISOString() },
  { id: "m2", title: "Technology product release schedule update", category: "Tech", status: "OPEN", updatedAt: new Date().toISOString() },
]).status === "POTENTIAL_CORRELATION");
assert("stale market status is reported", CombinationService.getFreshnessStatus(new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString()) === "Stale");
assert("current market status is reported", CombinationService.getFreshnessStatus(new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()) === "Current");

console.log(`combination-analysis: ${passed} checks passed`);

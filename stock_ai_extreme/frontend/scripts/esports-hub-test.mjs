/**
 * Phase 21B §28 — esports hub unit tests (pure helpers).
 *
 * Bundles `src/lib/esportsFormat.ts` with esbuild and asserts the display/a11y
 * behaviour the hub depends on: honest N/A for missing values, correct status
 * tones, clock formatting, and the accessible match description (§20). It needs
 * no browser and no network — the live-data paths are covered by the backend
 * feed-service tests and the localhost smoke run.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const entry = join(root, "src", "lib", "esportsFormat.ts");
const outDir = join(root, "node_modules", ".cache", "neural-market-tests");
mkdirSync(outDir, { recursive: true });
const outfile = join(outDir, "esports-format-test.mjs");

await build({
  entryPoints: [entry],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile,
  logLevel: "silent",
});

const fmt = await import(`file://${outfile}`);
const { statusMeta, formatClock, relTime, describeMatch, gameLabel, gameShort, HUB_GAMES, NA } = fmt;

let passed = 0;
const assert = (label, condition) => {
  if (!condition) throw new Error(`FAIL: ${label}`);
  passed += 1;
  console.log(`PASS ${label}`);
};

// ---- status metadata (§4): text + tone for every status ----
assert("live status tone", statusMeta("LIVE").tone === "live" && statusMeta("LIVE").label === "Live");
assert("paused tone", statusMeta("PAUSED").tone === "paused");
assert("map break labelled", statusMeta("MAP_BREAK").label === "Map break");
assert("completed tone", statusMeta("COMPLETED").tone === "completed");
assert("unknown falls back", statusMeta("SOMETHING").label === "Unknown" && statusMeta(null).label === "Unknown");

// ---- clock formatting ----
assert("clock formats mm:ss", formatClock(754) === "12:34");
assert("clock pads seconds", formatClock(65) === "1:05");
assert("clock N/A for null", formatClock(null) === NA && formatClock(undefined) === NA);
assert("clock N/A for negative", formatClock(-1) === NA);

// ---- relTime honest handling ----
assert("relTime N/A for null", relTime(null) === NA);
assert("relTime N/A for garbage", relTime("not-a-date") === NA);
const past = new Date(Date.now() - 5 * 60000).toISOString();
assert("relTime describes the past", relTime(past) === "5m ago");
const future = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString();
assert("relTime describes the future", relTime(future).startsWith("in "));

// ---- game labels ----
assert("known game label", gameLabel("cs2") === "Counter-Strike 2");
assert("unknown game falls back", gameLabel("valorant") === "VALORANT");
assert("short labels", gameShort("lol") === "LoL");
assert("hub games are the three supported", HUB_GAMES.length === 3 && HUB_GAMES.includes("dota2"));

// ---- accessible match description (§20) ----
const base = {
  game_id: "cs2",
  tournament_name: "BLAST Open Porto 2026",
  team_a: { id: "cs2-t7020", name: "Spirit" },
  team_b: { id: "cs2-t11283", name: "Falcons" },
  score_a: 2,
  score_b: 0,
};
const liveLead = describeMatch({ ...base, status: "LIVE" });
assert("live lead description", liveLead.includes("Spirit leads Falcons") && liveLead.includes("2 to 0"));
const tied = describeMatch({ ...base, status: "LIVE", score_a: 1, score_b: 1 });
assert("tied description", tied.includes("tied 1 to 1"));
const done = describeMatch({ ...base, status: "COMPLETED", winner_id: "cs2-t7020" });
assert("completed description names the winner", done.includes("Spirit won"));
const upcoming = describeMatch({ ...base, status: "UPCOMING", score_a: 0, score_b: 0 });
assert("upcoming description", upcoming.includes("versus"));
assert(
  "description never invents a team name",
  describeMatch({ ...base, team_a: { id: "x", name: null }, status: "LIVE" }).includes("Team A")
);

console.log(`\n${passed} esports helper assertions passed.`);

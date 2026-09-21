import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const __dirname = fileURLToPath(new URL("..", import.meta.url));
const entry = join(__dirname, "src/lib/fuzzy.ts");
// Bundled output lives under node_modules/.cache so a test run never leaves
// build artifacts in the repository root.
const outDir = join(__dirname, "node_modules", ".cache", "neural-market-tests");
mkdirSync(outDir, { recursive: true });
const outfile = join(outDir, "fuzzy-test.mjs");

await build({
  entryPoints: [entry],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile,
  logLevel: "silent",
});

const fuzzy = await import(`file://${outfile}`);
const { levenshtein, similarity, distanceBudget, BKTree, fuzzyRank } = fuzzy;

let passed = 0;
const assert = (label, condition) => {
  if (!condition) throw new Error(`FAIL: ${label}`);
  passed += 1;
  console.log(`PASS ${label}`);
};

assert("levenshtein matches the classic example", levenshtein("kitten", "sitting") === 3);
assert("levenshtein is symmetric", levenshtein("ogdc", "ogcd") === levenshtein("ogcd", "ogdc"));
assert("levenshtein handles empty strings", levenshtein("", "abc") === 3 && levenshtein("abc", "") === 3);
assert("identical strings have distance 0", levenshtein("hbl", "hbl") === 0);
assert("similarity is 1 for identical", similarity("lucky", "lucky") === 1);
assert("similarity is between 0 and 1", similarity("lucky", "luck") > 0 && similarity("lucky", "luck") < 1);
assert("distance budget is 0 for tiny queries", distanceBudget("ab") === 0);
assert("distance budget grows with length", distanceBudget("abcd") === 1 && distanceBudget("abcdefgh") === 3);

const tree = new BKTree();
for (const term of ["ogdc", "ppl", "luck", "hbl", "meezan", "kse100"]) tree.insert(term);
assert("BK-tree indexes every term", tree.length === 6);
const typo = tree.search("ogcd", 2);
assert("BK-tree finds a transposition within budget", typo.some((hit) => hit.term === "ogdc"));
assert("BK-tree excludes distant terms", tree.search("ogcd", 0).length === 0);

const universe = [
  { symbol: "OGDC", name: "Oil & Gas Development Company", sector: "Exploration & Production" },
  { symbol: "PPL", name: "Pakistan Petroleum", sector: "Exploration & Production" },
  { symbol: "HBL", name: "Habib Bank", sector: "Banks" },
  { symbol: "MEBL", name: "Meezan Bank", sector: "Banks" },
];
const tokensFor = (item) => [item.symbol, item.name, item.sector];

const typoRank = fuzzyRank(universe, tokensFor, "HBL", { maxDistance: 1 });
assert("fuzzyRank returns the exact symbol at distance 0", typoRank[0]?.item.symbol === "HBL" && typoRank[0].distance === 0);

const misspelled = fuzzyRank(universe, tokensFor, "HABBIB", { maxDistance: 2 });
assert("fuzzyRank survives a doubled letter", misspelled.some((match) => match.item.symbol === "HBL"));

const sectorRank = fuzzyRank(universe, tokensFor, "bank", { maxDistance: 1 });
assert("fuzzyRank matches a sector token", sectorRank.some((match) => match.item.sector === "Banks"));

assert("fuzzyRank returns nothing without a query", fuzzyRank(universe, tokensFor, "").length === 0);

console.log(`fuzzy-search: ${passed} checks passed`);

import esbuild from "esbuild";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const outDir = mkdtempSync(join(tmpdir(), "search-sidebar-"));
const outfile = join(outDir, "search.mjs");
await esbuild.build({
  entryPoints: [join(process.cwd(), "src/lib/searchService.ts")],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile,
  logLevel: "silent",
});
const search = await import(pathToFileURL(outfile).href);
let passed = 0;
const check = (label, condition) => {
  if (!condition) throw new Error(`FAIL ${label}`);
  passed += 1;
  console.log(`PASS ${label}`);
};

const stock = search.searchGlobal("OGDC");
check("ticker search returns OGDC first", stock[0]?.symbol === "OGDC" && stock[0]?.type === "stock");
check("company search finds Habib Bank", search.searchGlobal("Habib Bank").some((item) => item.symbol === "HBL"));
check("sector search finds Banking", search.searchGlobal("Bank").some((item) => item.type === "sector"));
check("index search finds KSE100", search.searchGlobal("KSE100").some((item) => item.type === "index"));
check("search results carry stable ids", search.searchGlobal("OGDC").every((item) => item.id.length > 0));
check("empty query is cheap and empty", search.searchGlobal("").length === 0);
console.log(`search sidebar: ${passed} checks passed`);

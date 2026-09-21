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

const storage = await bundle("src/lib/workspace/storage.ts", "ws-storage.mjs");
const engine = await bundle("src/lib/workspace/engine.ts", "ws-engine.mjs");

const { exportWorkspacesJSON, parseWorkspacesJSON, encodeWorkspaceShare, readSharedWorkspace, buildWorkspaceShareLink } = storage;
const { LAYOUT_VERSION } = engine;

let passed = 0;
const assert = (label, condition) => {
  if (!condition) throw new Error(`FAIL: ${label}`);
  passed += 1;
  console.log(`PASS ${label}`);
};

function makeLayout(workspaceId, symbol = "OGDC") {
  return {
    workspaceId,
    preset: "chart-chat",
    version: LAYOUT_VERSION,
    updatedAt: new Date().toISOString(),
    widgets: [
      {
        id: `w-${workspaceId}`,
        type: "NEW_CHART",
        x: 0,
        y: 0,
        width: 6,
        height: 8,
        visible: true,
        minimized: false,
        maximized: false,
        settings: { symbol, timeframe: "6M" },
      },
    ],
  };
}

function makeSaved(id, name, symbol) {
  const now = new Date().toISOString();
  return { id, name, layout: makeLayout(id, symbol), createdAt: now, updatedAt: now };
}

// --- export / import -------------------------------------------------------

const records = [makeSaved("sw-1", "Desk", "OGDC"), makeSaved("sw-2", "Research", "LUCK")];
const exported = exportWorkspacesJSON(records);
assert("export produces valid JSON", (() => { JSON.parse(exported); return true; })());
assert("export declares a version and timestamp", (() => {
  const parsed = JSON.parse(exported);
  return parsed.version === 1 && typeof parsed.exportedAt === "string";
})());

const reimported = parseWorkspacesJSON(exported);
assert("import round-trips both records", reimported.length === 2);
assert("import preserves the layout", reimported[0].layout.widgets[0].settings.symbol === "OGDC");
assert("import preserves names", reimported[1].name === "Research");

const bareArray = parseWorkspacesJSON(JSON.stringify(records));
assert("import accepts a bare array (no envelope)", bareArray.length === 2);

assert("import rejects invalid JSON", (() => {
  try { parseWorkspacesJSON("{not json"); return false; } catch { return true; }
})());
assert("import rejects an empty document", (() => {
  try { parseWorkspacesJSON(JSON.stringify({ workspaces: [] })); return false; } catch { return true; }
})());
assert("import rejects an old layout version", (() => {
  const stale = makeSaved("sw-old", "Old", "OGDC");
  stale.layout.version = -1;
  try { parseWorkspacesJSON(JSON.stringify({ workspaces: [stale] })); return false; } catch { return true; }
})());

// --- share links -----------------------------------------------------------

const shared = makeSaved("sw-3", "Shared desk", "HBL");
const payload = encodeWorkspaceShare(shared);
assert("share payload is URL-safe base64", /^[A-Za-z0-9_-]+$/.test(payload));
assert("share payload is not plain JSON", !payload.includes("{"));

const decoded = readSharedWorkspace(`?ws=${encodeURIComponent(shared.id)}&w=${payload}`);
assert("share link decodes back to the workspace", decoded !== null && decoded.id === "sw-3");
assert("share link restores the widget settings", decoded.layout.widgets[0].settings.symbol === "HBL");
assert("share link restores the name", decoded.name === "Shared desk");

const link = buildWorkspaceShareLink(shared, "https://example.test/workspace");
assert("share link carries both the id and the payload", link.startsWith("https://example.test/workspace?ws=sw-3&w="));
const fromLink = readSharedWorkspace(link.slice(link.indexOf("?")));
assert("share link re-decodes from its own URL", fromLink !== null && fromLink.id === "sw-3");

assert("missing payload reads as null", readSharedWorkspace("?ws=sw-3") === null);
assert("garbage payload reads as null", readSharedWorkspace("?w=not-base64!!") === null);
assert("empty query reads as null", readSharedWorkspace("") === null);

console.log(`workspace-share: ${passed} checks passed`);

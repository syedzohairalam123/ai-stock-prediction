/*
 * Assistant audit harness (dev-only, Phase 10).
 *
 * Companion to `page-audit.mjs`: that one checks every route, this one checks
 * the AI assistant as a product — the dock, the expanded reading view, the
 * mobile sheet, streaming, Stop, conversation history and console hygiene.
 *
 * It drives an already-running Chrome over the DevTools Protocol using Node's
 * built-in WebSocket, so it needs no dependencies and never enters the bundle.
 *
 * Usage
 *   # 1. backend on :8000 and the dev server on :5173 must already be running
 *   #    (with no AI key the assistant reports "not configured" — that path is
 *   #     also worth auditing; with a key set the answer checks run for real)
 *   # 2. launch Chrome with a debug port:
 *   chrome --remote-debugging-port=9222 --headless=new http://localhost:5173
 *   # 3. run it
 *   node scripts/assistant-audit.mjs
 *
 * Env
 *   SHOT_DIR   directory for the PNG screenshots (default: system temp dir)
 *   AUDIT_BASE frontend base URL (default http://localhost:5173)
 *   AUDIT_API  backend base URL  (default http://127.0.0.1:8000)
 *
 * Exit code 1 means at least one check failed.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const CDP = process.env.AUDIT_CDP || 'http://127.0.0.1:9222';
const BASE = process.env.AUDIT_BASE || 'http://localhost:5173';
const API = process.env.AUDIT_API || 'http://127.0.0.1:8000';
const SHOTS = process.env.SHOT_DIR || path.join(os.tmpdir(), 'assistant-audit');

fs.mkdirSync(SHOTS, { recursive: true });

// Log.enable replays entries buffered before it was enabled, so anything older
// than the run itself (an earlier page load, a request from before a fix) would
// be reported as a failure of this run.
const runStart = Date.now() / 1000;

const results = [];
const aiResponses = [];
const consoleErrors = [];
const consoleWarnings = [];
const exceptions = [];
const failedRequests = [];
const expectedAborts = [];
const inFlightUrl = new Map();
let blockingStatus = false;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const note = (message) => console.log(`      ${message}`);
const check = (name, ok, detail = '') => {
  results.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
};

// --------------------------------------------------------------- CDP plumbing

const targets = await (await fetch(`${CDP}/json/list`)).json();
const target = targets.find((t) => t.type === 'page');
if (!target) throw new Error('no debuggable page target — is Chrome running with --remote-debugging-port=9222?');

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});

let nextId = 0;
const pending = new Map();

socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message);
    pending.delete(message.id);
    return;
  }

  const { method, params } = message;
  if (method === 'Runtime.consoleAPICalled') {
    const line = (params.args || []).map((arg) => arg.value ?? arg.description ?? arg.type).join(' ');
    if (params.type === 'warning') consoleWarnings.push(line);
    else if (params.type === 'error' || params.type === 'assert') consoleErrors.push(line);
  } else if (method === 'Runtime.exceptionThrown') {
    exceptions.push(params.exceptionDetails.exception?.description || params.exceptionDetails.text);
  } else if (method === 'Log.entryAdded' && params.entry.level === 'error') {
    if ((params.entry.timestamp || 0) < runStart - 1) return; // replayed from before this run
    consoleErrors.push(`[log] ${params.entry.text} ${params.entry.url || ''}`);
  } else if (method === 'Network.requestWillBeSent') {
    inFlightUrl.set(params.requestId, params.request?.url || '');
  } else if (method === 'Network.responseReceived') {
    const url = params.response?.url || '';
    if (url.includes('/api/ai/')) {
      // A stopped generation aborts its own stream — that is the feature
      // working, not a failed endpoint.
      aiResponses.push({ url, status: params.response.status, excluded: /stream/.test(url) });
    }
  } else if (method === 'Network.loadingFailed') {
    const url = inFlightUrl.get(params.requestId) || '';
    inFlightUrl.delete(params.requestId);
    // Stop generating aborts the answer's own request on purpose — the feature
    // working, not a broken call — as does the blocked-status check further down.
    if (/\/api\/ai\/stream/.test(url) && /ERR_ABORTED/.test(params.errorText || '')) {
      expectedAborts.push(url.replace(API, ''));
    } else if (blockingStatus && /\/api\/ai\/status/.test(url)) {
      note('status call blocked on purpose');
    } else {
      failedRequests.push(`${params.errorText} ${url.replace(API, '')} (${params.type})`);
    }
  }
};

const send = (method, params = {}) => {
  const id = ++nextId;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    socket.send(JSON.stringify({ id, method, params }));
  });
};

async function evaluate(expression) {
  const reply = await send('Runtime.evaluate', {
    expression: `(() => { ${expression} })()`,
    returnByValue: true,
    awaitPromise: true,
  });
  const { result, exceptionDetails } = reply.result || {};
  if (exceptionDetails) throw new Error(exceptionDetails.exception?.description || 'evaluate failed');
  return result?.value;
}

const count = (selector) => evaluate(`return document.querySelectorAll(${JSON.stringify(selector)}).length;`);

const text = (selector) => evaluate(`
  const el = document.querySelector(${JSON.stringify(selector)});
  return el ? el.textContent.trim() : null;
`);

const click = (selector) => evaluate(`
  const el = document.querySelector(${JSON.stringify(selector)});
  if (!el) return false;
  el.click();
  return true;
`);

const rect = (selector) => evaluate(`
  const el = document.querySelector(${JSON.stringify(selector)});
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, w: r.width, h: r.height,
           bg: cs.backgroundColor, color: cs.color, z: cs.zIndex };
`);

async function waitFor(expression, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    // Wrapped in Boolean(): a raw `document.querySelector(...)` returns a node,
    // which CDP cannot serialize by value and reports as undefined — the wait
    // would then time out on a selector that is plainly present.
    if (await evaluate(`return Boolean(${expression});`)) return true;
    await sleep(150);
  }
  note(`timed out waiting for: ${label || expression}`);
  return false;
}

async function shot(name) {
  const reply = await send('Page.captureScreenshot', { format: 'png' });
  if (reply.result?.data) fs.writeFileSync(path.join(SHOTS, `${name}.png`), Buffer.from(reply.result.data, 'base64'));
}

async function typeInto(selector, value, tag = 'TextArea') {
  await evaluate(`
    const el = document.querySelector(${JSON.stringify(selector)});
    el.focus();
    const setter = Object.getOwnPropertyDescriptor(window.HTML${tag}Element.prototype, 'value').set;
    setter.call(el, ${JSON.stringify(value)});
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  `);
}

// -------------------------------------------------------------------- setup

await send('Runtime.enable');
await send('Page.enable');
await send('Log.enable');
await send('Network.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

// Always start from a first-time visitor: a previously open panel (or a stored
// conversation) would hide the launcher this audit is about to measure.
await send('Storage.clearDataForOrigin', { origin: new URL(BASE).origin, storageTypes: 'local_storage' });
await send('Page.navigate', { url: `${BASE}/stock/OGDC` });

const booted = await waitFor(`document.querySelector('.ai-launcher')`, 45000, 'assistant launcher');
check('app shell and assistant launcher render', booted);
await sleep(1500);

// clientWidth/clientHeight, not innerWidth/innerHeight: the latter include the
// scrollbar, so a dock flush against the right edge would look inset by ~10px.
const viewport = await evaluate(`
  return {
    w: document.documentElement.clientWidth,
    h: document.documentElement.clientHeight,
    innerW: innerWidth,
  };
`);
note(`viewport ${viewport.w}×${viewport.h} (innerWidth ${viewport.innerW})`);

// ------------------------------------------------------------- 1. launcher

const launcher = await rect('.ai-launcher');
check(
  'launcher is visible, anchored bottom-right, and styled',
  launcher && launcher.bottom <= viewport.h + 1 && launcher.right <= viewport.w + 1 && launcher.h > 30 &&
    launcher.bg !== 'rgba(0, 0, 0, 0)',
  launcher ? `${Math.round(launcher.w)}×${Math.round(launcher.h)} bg=${launcher.bg}` : 'missing'
);
note(`launcher label: ${await text('.ai-launcher')}`);
await shot('01-launcher');

// ----------------------------------------------------------------- 2. dock

await click('.ai-launcher');
check('clicking the launcher opens the dock', await waitFor(`document.querySelector('.ai-dock')`, 8000, 'dock'));

// The dock animates in over `ai-slide` (0.18s, starting at translateX(16px)),
// so measuring the moment it appears would report it 16px off the right edge.
await sleep(500);

const dock = await rect('.ai-dock');
check(
  'dock is a right-side rail at full height',
  dock && Math.abs(dock.right - viewport.w) < 2 && Math.abs(dock.top) < 1 && Math.abs(dock.h - viewport.h) < 2,
  dock ? `left=${Math.round(dock.left)} ${Math.round(dock.w)}×${Math.round(dock.h)}` : 'missing'
);
check('dock width is a readable column (320–480px)', dock && dock.w >= 320 && dock.w <= 480, dock ? `${Math.round(dock.w)}px` : '');
check('dock has a real surface colour and stacks above the page', dock && dock.bg !== 'rgba(0, 0, 0, 0)' && Number(dock.z) >= 50, dock ? `${dock.bg} z=${dock.z}` : '');

// The header/main/footer wrappers stay full-bleed on purpose; the docked layout
// reserves the rail with right padding, so the *content* box is what must clear
// the dock — measuring the wrapper's own rect would always look covered.
const gutter = await evaluate(`
  const dock = document.querySelector('.ai-dock');
  if (!dock) return null;
  const dockLeft = dock.getBoundingClientRect().left;
  const probe = (selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const pad = parseFloat(getComputedStyle(el).paddingRight) || 0;
    return { pad: Math.round(pad), contentRight: Math.round(rect.right - pad) };
  };
  return { dockLeft: Math.round(dockLeft), header: probe('.psx-header-container'),
           main: probe('.psx-main'), footer: probe('.psx-footer') };
`);
check(
  'header content is not covered by the dock',
  gutter?.header && gutter.header.contentRight <= gutter.dockLeft + 1,
  gutter?.header ? `content right=${gutter.header.contentRight} (pad ${gutter.header.pad}) vs dock left=${gutter.dockLeft}` : 'no header'
);
check(
  'page main content is not covered by the dock',
  gutter?.main && gutter.main.contentRight <= gutter.dockLeft + 1,
  gutter?.main ? `content right=${gutter.main.contentRight} (pad ${gutter.main.pad})` : 'no main'
);
check(
  'footer content is not covered by the dock',
  !gutter?.footer || gutter.footer.contentRight <= gutter.dockLeft + 1,
  gutter?.footer ? `content right=${gutter.footer.contentRight} (pad ${gutter.footer.pad})` : 'no footer'
);
check('page body is marked docked so the gutter applies', await evaluate(`return document.querySelector('.psx-app').classList.contains('ai-docked');`));
check('desktop scroll is not locked', await evaluate(`return document.body.style.overflow === '';`));

const composer = await rect('.ai-composer');
check('composer is inside the viewport', composer && composer.bottom <= viewport.h + 1 && composer.h > 40, composer ? `bottom=${Math.round(composer.bottom)}` : 'missing');

// "Checking assistant…" is the honest state only while the status call is in
// flight; a header stuck there is the bug (a status request that never settles),
// so wait for it to resolve before judging the copy.
const statusResolved = await waitFor(
  `!new RegExp('Checking assistant').test(document.querySelector('.ai-sub').textContent)`,
  25000,
  'assistant status to resolve'
);
const statusLine = await text('.ai-sub');
note(`header: "${await text('.ai-title')}" / "${statusLine}"`);
check(
  'header reports the provider state honestly',
  statusResolved && /(Live|not configured|unreachable)/i.test(statusLine || ''),
  statusLine || ''
);
await shot('02-dock');

// -------------------------------------------------------------- 3. context

const chips = await evaluate(`return [...document.querySelectorAll('.ai-chip')].map((c) => c.textContent.trim());`);
check('context chips render', Array.isArray(chips) && chips.length >= 3, (chips || []).join(' | '));
check('context identifies the symbol under view', (chips || []).some((c) => /OGDC/.test(c)));
check('context includes the timeframe', (chips || []).some((c) => /Timeframe/i.test(c)));

await click('.ai-chip-btn');
check('"What is sent" expands a transparency panel', await waitFor(`document.querySelector('.ai-context-detail')`, 4000, 'context detail'));
const detailItems = await count('.ai-context-detail li');
check('transparency panel lists what will be attached', detailItems >= 4, `${detailItems} items`);
await shot('03-context-detail');
await click('.ai-chip-btn');

// ---------------------------------------------------------- 4. empty state

const capabilities = await count('.ai-cap');
check('empty state explains the capabilities', capabilities >= 6, `${capabilities} cards`);
// Prompts are either the backend's or the local fallback; both arrive a tick
// after the request settles, and neither is allowed to leave the state blank.
await waitFor(`document.querySelector('.ai-prompt')`, 20000, 'suggested prompts');
const prompts = await evaluate(`return [...document.querySelectorAll('.ai-prompt')].map((p) => p.textContent.trim());`);
check('suggested prompts are offered for this page', Array.isArray(prompts) && prompts.length >= 3, `${(prompts || []).length} prompts`);
note(`first prompt: ${(prompts || [])[0] || 'none'}`);
check('send is disabled while the composer is empty', await evaluate(`return document.querySelector('.ai-round.send').disabled;`));

const mic = await evaluate(`
  const el = document.querySelector('.ai-round.ghost, .ai-round.listening');
  return el ? { title: el.getAttribute('title'), disabled: el.disabled } : null;
`);
note(`voice: ${JSON.stringify(mic)}`);
check('voice input states its support instead of failing silently', Boolean(mic && mic.title), mic?.title || '');
await shot('04-empty-state');

// ----------------------------------------------------------- 5. the answer

const answerExpected = /(Live)/i.test(statusLine || '');
await click('.ai-prompt');

if (answerExpected) {
  check('sending starts a streamed answer', await waitFor(`document.querySelector('.ai-round.stop') || document.querySelector('.ai-caret')`, 25000, 'streaming'));
  note(`thinking indicator visible: ${await evaluate(`return !!document.querySelector('.ai-thinking');`)}`);
  await shot('05-streaming');
  check('the answer completes and releases the composer', await waitFor(`!document.querySelector('.ai-round.stop') && document.querySelector('.ai-msg.assistant .ai-md')`, 120000, 'answer'));
  check('no loader is left behind', !(await evaluate(`return !!document.querySelector('.ai-thinking');`)));

  const structure = await evaluate(`
    const md = document.querySelector('.ai-msg.assistant .ai-md');
    if (!md) return null;
    return {
      headings: md.querySelectorAll('h3, h4, h5').length,
      bullets: md.querySelectorAll('ul li').length,
      ordered: md.querySelectorAll('ol li').length,
      quotes: md.querySelectorAll('blockquote').length,
      bold: md.querySelectorAll('strong').length,
      tables: md.querySelectorAll('table').length,
      factTags: md.querySelectorAll('.ai-tag-fact').length,
      estTags: md.querySelectorAll('.ai-tag-est').length,
      up: md.querySelectorAll('.ai-up').length,
      down: md.querySelectorAll('.ai-dn').length,
      rawMarkdown: /\\*\\*/.test(md.textContent),
      chars: md.textContent.trim().length,
    };
  `);
  note(`rendered structure: ${JSON.stringify(structure)}`);
  check('answers render as structured elements, not raw text',
    structure && structure.headings >= 1 && structure.chars > 100 && structure.rawMarkdown === false,
    JSON.stringify(structure));
  if (structure && structure.tables > 0) note('markdown tables render as real tables');
  if (structure && structure.factTags + structure.estTags > 0) note('provenance labels render as chips');

  const sources = await text('.ai-src summary');
  check('sources panel is attached to the answer', /\(\d+\)/.test(sources || ''), sources || 'none');
  await click('.ai-src summary');
  check('sources expand into attributable items', (await count('.ai-src-item')) >= 1, `${await count('.ai-src-item')} items`);
  await shot('06-answer');

  // ---------------------------------------------------- 6. Enter + Stop
  await typeInto('.ai-field textarea', 'Summarise the risks for OGDC right now');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  check('Enter sends the typed question', await waitFor(
    `[...document.querySelectorAll('.ai-msg.user')].some((m) => /risks for OGDC/.test(m.textContent))`, 8000, 'user message'
  ));
  check('Stop generating appears while answering', await waitFor(`document.querySelector('.ai-round.stop')`, 12000, 'stop button'));
  await sleep(700);
  await click('.ai-round.stop');
  check('Stop releases the stream', await waitFor(`!document.querySelector('.ai-round.stop')`, 15000, 'stop released'));
  check(
    'Stop aborts the answer on the wire rather than leaving it running',
    expectedAborts.length >= 1,
    `${expectedAborts.length} stream abort(s)`
  );
  const afterStop = await evaluate(`
    const stopped = [...document.querySelectorAll('.ai-msg-meta')].some((n) => /Generation stopped/i.test(n.textContent));
    const last = [...document.querySelectorAll('.ai-msg.assistant .ai-bubble')].pop();
    return { stopped, partialLength: last ? last.textContent.trim().length : 0 };
  `);
  check('stopping keeps the partial answer on screen', afterStop.stopped && afterStop.partialLength > 0, JSON.stringify(afterStop));
  check('no loader survives a stop', !(await evaluate(`return !!document.querySelector('.ai-thinking');`)));
  await shot('07-stopped');
} else {
  note('provider is not configured — checking the actionable-failure path instead');
  check('a question without a provider fails loudly and recoverably', await waitFor(
    `document.querySelector('.ai-error') || document.querySelector('.ai-notice')`, 20000, 'error card'
  ));
  const errorText = await text('.ai-error, .ai-notice');
  check('the failure tells the user what to do', /AI_PROVIDER|key|configured/i.test(errorText || ''), (errorText || '').slice(0, 120));
  check('no loader is left behind after a failure', !(await evaluate(`return !!document.querySelector('.ai-thinking');`)));
  await shot('05-error-state');
}

// ------------------------------------------------------------ 7. history

await click('[aria-label="Conversation history"]');
check('history drawer opens', await waitFor(`document.querySelector('.ai-drawer')`, 6000, 'drawer'));
const drawer = await rect('.ai-drawer');
check('drawer is a left panel, not full screen', drawer && drawer.left <= 1 && drawer.w <= 460, drawer ? `${Math.round(drawer.w)}px` : '');

// The list is fetched when the drawer opens, so a spinner is expected — an
// endless one is not. Waiting on the list (not a fixed sleep) is what makes the
// rename check below meaningful.
const listLoaded = await waitFor(
  `document.querySelector('.ai-conv') && !document.querySelector('.ai-drawer-body .ai-state')`,
  25000,
  'conversation list'
);
check('the history list loads instead of spinning forever', listLoaded);
const listedBefore = await count('.ai-conv');
check('conversations are listed', listedBefore >= 1, `${listedBefore} entries`);
await shot('08-history');

// A per-run title: a leftover from an earlier run must never be able to make
// this check pass.
const renameTo = `Audit rename ${new Date().toISOString().slice(11, 19)}`;
const titleBefore = await text('.ai-conv-title');
await click('.ai-conv [aria-label="Rename conversation"]');
await waitFor(`document.querySelector('.ai-conv input')`, 4000, 'rename input');
await typeInto('.ai-conv input', renameTo, 'Input');
await click('.ai-conv [title="Save title"]');
check(
  'rename updates the list in place',
  await waitFor(`${JSON.stringify(renameTo)} === document.querySelector('.ai-conv-title').textContent`, 8000, 'renamed title'),
  `was "${titleBefore}"`
);
// The list updates optimistically, so the PUT is still in flight when the title
// changes on screen — poll for it rather than reading once and racing it.
const readConversations = async () => {
  try {
    return (await (await fetch(`${API}/api/ai/conversations`)).json()).conversations || [];
  } catch (error) {
    note(`could not read the conversations API: ${error.message}`);
    return [];
  }
};
let persisted = await readConversations();
const persistDeadline = Date.now() + 10000;
while (Date.now() < persistDeadline && !persisted.some((c) => c.title === renameTo)) {
  await sleep(500);
  persisted = await readConversations();
}
check(
  'rename persists to the backend',
  persisted.some((c) => c.title === renameTo),
  persisted.map((c) => c.title).join(' | ') || 'no conversations'
);
check('the optimistic rename was not reverted', (await text('.ai-conv-title')) === renameTo, (await text('.ai-conv-title')) || '');
check('rename does not duplicate the conversation', (await count('.ai-conv')) === listedBefore, `${listedBefore} before / ${await count('.ai-conv')} after`);

await click('.ai-conv');
await sleep(2000);
check('opening a conversation restores its messages', (await count('.ai-msg')) >= 2, `${await count('.ai-msg')} messages`);
check('drawer closes after opening', !(await evaluate(`return !!document.querySelector('.ai-drawer');`)));

await click('[aria-label="Conversation history"]');
await waitFor(`document.querySelector('.ai-drawer')`, 6000, 'drawer again');
await click('.ai-btn.pri');
await sleep(900);
check('new conversation clears the thread', (await count('.ai-msg')) === 0);
await shot('09-new-conversation');

// ----------------------------------------------------------- 8. expanded

if (answerExpected) {
  await click('.ai-prompt');
  await waitFor(`document.querySelector('.ai-msg.assistant .ai-md')`, 120000, 'answer for expanded view');
}
await click('[aria-label="Expand panel"]');
await sleep(800);
const wide = await rect('.ai-dock.wide');
check('expanded mode widens the panel', wide && wide.w >= 600, wide ? `${Math.round(wide.w)}px` : 'still a rail');
check('expanded mode uses a backdrop', Boolean(await rect('.ai-backdrop')));check(
  'expanded mode drops the page gutter behind its backdrop',
  !(await evaluate(`return document.querySelector('.psx-app').classList.contains('ai-docked');`))
);
await shot('10-expanded');
await click('[aria-label="Collapse panel"]');
await sleep(500);
check('collapsing returns to the rail', Boolean(await rect('.ai-dock')) && !(await rect('.ai-backdrop')));
check(
  'collapsing restores the page gutter',
  await evaluate(`return document.querySelector('.psx-app').classList.contains('ai-docked');`)
);

// ------------------------------------------------------------- 9. mobile

await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await sleep(1000);
const sheet = await rect('.ai-dock');
check('mobile becomes a full-screen sheet', sheet && Math.abs(sheet.w - 390) < 2 && Math.abs(sheet.h - 844) < 3,
  sheet ? `${Math.round(sheet.w)}×${Math.round(sheet.h)}` : 'missing');
check('mobile sheet starts at the top-left of the viewport', sheet && Math.abs(sheet.top) < 1 && Math.abs(sheet.left) < 1);
const mobileComposer = await rect('.ai-composer');
check('mobile composer sits inside the viewport (keyboard-safe)', mobileComposer && mobileComposer.bottom <= 845 && mobileComposer.h > 40,
  mobileComposer ? `bottom=${Math.round(mobileComposer.bottom)}` : 'missing');
check('no horizontal overflow on mobile', await evaluate(`return document.documentElement.scrollWidth <= 391;`),
  `scrollWidth=${await evaluate('return document.documentElement.scrollWidth;')}`);
const thread = await rect('.ai-thread');
check('the thread keeps its own scroll area on mobile', thread && thread.h > 200, thread ? `${Math.round(thread.h)}px` : '');
await shot('11-mobile-sheet');

await click('[aria-label="Conversation history"]');
await sleep(800);
const mobileDrawer = await rect('.ai-drawer');
check('history drawer fits the mobile screen', mobileDrawer && mobileDrawer.w <= 390, mobileDrawer ? `${Math.round(mobileDrawer.w)}px` : 'missing');
await shot('12-mobile-history');
await click('[aria-label="Close history"]');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await sleep(400);

// ------------------------------------------- 10. unreachable backend (spec V)

// Blocking the status call at the network layer simulates the API being down
// without touching the real backend: the assistant must say so, and must not
// blame a missing provider key.
blockingStatus = true;
await send('Network.setBlockedURLs', { urls: ['*/api/ai/status'] });
await click('[aria-label="Close assistant"]');
await click('.ai-launcher');
await waitFor(`document.querySelector('.ai-sub')`, 8000, 'panel reopened');
const unreachable = await waitFor(
  `/Backend unreachable/i.test(document.querySelector('.ai-sub').textContent)`,
  20000,
  'unreachable status'
);
check(
  'a down backend is reported as unreachable, not as a missing key',
  unreachable,
  (await text('.ai-sub')) || ''
);
const offlineNotice = await text('.ai-notice');
check(
  'the unreachable notice says what to do next',
  /unreachable|start it|check the url/i.test(offlineNotice || ''),
  (offlineNotice || '').slice(0, 130)
);
check('no loader is left behind when the backend is down', !(await evaluate(`return !!document.querySelector('.ai-thinking');`)));
await shot('13-backend-unreachable');

blockingStatus = false;
await send('Network.setBlockedURLs', { urls: [] });
await click('[aria-label="Close assistant"]');
await click('.ai-launcher');
check(
  'status recovers once the backend answers again',
  await waitFor(`/Live/i.test(document.querySelector('.ai-sub').textContent)`, 25000, 'recovered status'),
  (await text('.ai-sub')) || ''
);
await click('[aria-label="Close assistant"]');

// ------------------------------------------------------- 11. hygiene

const assistantErrors = consoleErrors.filter((line) => /ai|assistant|Cannot read|undefined is not|Maximum update/i.test(line));
check('no uncaught exceptions', exceptions.length === 0, exceptions.slice(0, 2).join(' || ') || 'none');
check('no assistant-related console errors', assistantErrors.length === 0, assistantErrors.slice(0, 2).join(' || ') || 'none');

// Regression guard: the assistant's calls are built from VITE_API_URL, which is
// a bare origin in this project. Dropping the `/api` prefix 404s every call
// while the rest of the app keeps working, so assert the real request log.
const aiCalls = aiResponses.filter((entry) => !entry.excluded);
const aiFailures = aiCalls.filter((entry) => entry.status < 200 || entry.status >= 400);
check(
  'every assistant call reached a real endpoint',
  aiCalls.length >= 3 && aiFailures.length === 0,
  aiFailures.length
    ? aiFailures.map((entry) => `${entry.status} ${entry.url.replace(API, '')}`).join(' || ')
    : `${aiCalls.length} calls, all 2xx/3xx`
);

console.log('\n--- diagnostics ---------------------------------------------------');
console.log(`console errors (${consoleErrors.length}):`);
consoleErrors.slice(0, 10).forEach((line) => console.log(`   - ${line.slice(0, 180)}`));
console.log(`console warnings (${consoleWarnings.length}):`);
consoleWarnings.slice(0, 5).forEach((line) => console.log(`   - ${line.slice(0, 180)}`));
console.log(`failed requests (${failedRequests.length}):`);
[...new Set(failedRequests)].slice(0, 6).forEach((line) => console.log(`   - ${line.slice(0, 180)}`));
console.log(`intentional stream aborts (${expectedAborts.length}) [Stop generating]`);

const failed = results.filter((r) => !r.ok);
console.log('\n--- summary -------------------------------------------------------');
console.log(`${results.length - failed.length}/${results.length} checks passed`);
console.log(`screenshots: ${SHOTS}`);
if (failed.length) {
  console.log('FAILED:');
  failed.forEach((f) => console.log(`   - ${f.name}${f.detail ? ` (${f.detail})` : ''}`));
}
process.exit(failed.length ? 1 : 0);

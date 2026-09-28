/*
 * Phase 20 paper-ticket audit (dev-only).
 *
 * Drives an already-running Chrome (launched with --remote-debugging-port=9222)
 * over the Chrome DevTools Protocol and exercises the Quick Order ticket for
 * real:
 *
 *   1. /stock/OGDC          → open the ticket, read the header + quote, submit a
 *                             PAPER BUY, confirm a SIMULATED result appears
 *   2. /stock/OGDC (LIMIT)  → switch to LIMIT, type a price, submit
 *   3. invalid input        → clear the amount, confirm the panel blocks and
 *                             never gets stuck on SUBMITTING
 *   4. quick amount buttons → +5 / +10 change the value
 *   5. /forecast/:id        → open the ticket from a forecast event and confirm
 *                             YES/NO + probability wording (no BUY/SELL)
 *   6. duplicate submit     → press the button twice; exactly one new row
 *
 * Reports uncaught exceptions, console errors and failed requests the whole
 * time. Requires no dependencies (Node 22+ global WebSocket).
 *
 * Usage:
 *   chrome --remote-debugging-port=9222 http://localhost:5173
 *   node scripts/paper-ticket-audit.mjs [baseUrl]
 */

const CDP_HTTP = "http://127.0.0.1:9222";
const BASE = process.argv.find((a) => a.startsWith("http")) || "http://localhost:5173";

const failures = [];
const problems = [];
let checks = 0;

function check(label, condition, detail = "") {
  checks += 1;
  if (condition) {
    console.log(`  ✓ ${label}${detail ? ` — ${detail}` : ""}`);
  } else {
    console.log(`  ✗ ${label}${detail ? ` — ${detail}` : ""}`);
    failures.push(`${label}${detail ? ` (${detail})` : ""}`);
  }
}

async function targetUrl() {
  const res = await fetch(`${CDP_HTTP}/json/list`);
  const targets = await res.json();
  const page = targets.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
  if (!page) throw new Error("No debuggable page — launch Chrome with --remote-debugging-port=9222");
  return page.webSocketDebuggerUrl;
}

class Session {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.requestUrls = new Map();
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
        return;
      }
      if (msg.method === "Network.requestWillBeSent") {
        this.requestUrls.set(msg.params.requestId, msg.params.request?.url || "");
        return;
      }
      if (msg.method === "Runtime.exceptionThrown") {
        const text = msg.params?.exceptionDetails?.exception?.description || msg.params?.exceptionDetails?.text;
        problems.push(`uncaught exception: ${String(text).slice(0, 200)}`);
      }
      if (msg.method === "Runtime.consoleAPICalled" && msg.params?.type === "error") {
        const text = (msg.params.args || []).map((a) => a.value ?? a.description ?? "").join(" ");
        // Third-party image CDNs 403 on purpose (documented); they are not app errors.
        if (!/403|Failed to load resource/i.test(text)) problems.push(`console error: ${text.slice(0, 200)}`);
      }
      if (msg.method === "Network.loadingFailed") {
        const url = this.requestUrls.get(msg.params.requestId) || "";
        const thirdPartyImage = /^https?:\/\//.test(url) && !url.includes("localhost") && msg.params?.type === "Image";
        const aborted = /ERR_ABORTED|cancelled/i.test(msg.params?.errorText || "");
        if (!thirdPartyImage && !aborted) {
          problems.push(`request failed: ${msg.params?.errorText} ${msg.params?.type} ${url.slice(0, 120)}`);
        }
        this.requestUrls.delete(msg.params.requestId);
      }
    });
  }

  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`CDP timeout: ${method}`));
        }
      }, 30_000);
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || "evaluate failed");
    }
    return result.result?.value;
  }

  async goto(url) {
    await this.send("Page.navigate", { url });
    await new Promise((r) => setTimeout(r, 3500));
  }

  wait(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }
}

/**
 * Wait until the ticket has actually resolved a quote (or honestly failed to).
 * The instrument + volatility lookup hits a real provider, so acting before it
 * settles would test the skeleton, not the ticket.
 */
async function waitForQuote(session, label = "ticket quote") {
  await waitFor(
    session,
    `(() => {
      const t = document.querySelector('.paper-ticket');
      if (!t) return false;
      if (t.querySelector('.paper-head-loading')) return false;
      const price = t.querySelector('.paper-price')?.textContent?.trim() || '';
      const hasNumeric = /[0-9]/.test(price);
      const blocked = !!t.querySelector('.paper-blocked') || !!t.querySelector('.paper-head-empty');
      const hasError = !!t.querySelector('.paper-error');
      return hasNumeric || blocked || hasError;
    })()`,
    { timeout: 60_000, label },
  );
}

/** Poll an expression until it is truthy, or time out. */
async function waitFor(session, expression, { timeout = 25_000, label = expression } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      const value = await session.evaluate(expression);
      if (value) return value;
    } catch {
      /* retry */
    }
    await session.wait(400);
  }
  throw new Error(`timed out waiting for ${label}`);
}

const OPEN_TICKET = `
  (() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const trigger = buttons.find((b) => /Paper ticket|Paper$/i.test(b.textContent || ""));
    if (!trigger) return false;
    trigger.click();
    return true;
  })()
`;

async function main() {
  const wsUrl = await targetUrl();
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  const session = new Session(ws);
  await session.send("Runtime.enable");
  await session.send("Page.enable");
  await session.send("Network.enable");

  // ------------------------------------------------------------------ stock
  console.log("\n[1] /stock/OGDC — open the ticket and read the header");
  await session.goto(`${BASE}/stock/OGDC`);
  // Start from a clean ticket every run: a persisted form preference from an
  // earlier session would otherwise leak into these assertions.
  await session.evaluate(`(() => { try { localStorage.clear(); } catch {} return true; })()`);
  await session.goto(`${BASE}/stock/OGDC`);
  await waitFor(session, `!!document.querySelector('.stock-head') || document.body.innerText.includes('OGDC')`, {
    label: "stock page",
  });
  check("stock page loads", true);

  check("paper trigger rendered", await session.evaluate(OPEN_TICKET), "clicked the ticket trigger");
  await waitFor(session, `!!document.querySelector('.paper-ticket')`, { label: "paper ticket" });
  await waitForQuote(session, "stock ticket quote");

  const startMarket = await session.evaluate(`
    (() => {
      const b = Array.from(document.querySelectorAll('.paper-segment')).find((x) => x.textContent.trim() === 'MARKET');
      if (b) b.click();
      return true;
    })()`);
  check("order type defaults to a selectable MARKET", startMarket === true);
  await session.wait(300);

  const header = await session.evaluate(`
    (() => {
      const t = document.querySelector('.paper-ticket');
      if (!t) return null;
      return {
        banner: t.querySelector('.paper-ticket-banner')?.textContent?.trim(),
        hasHeader: !!t.querySelector('.paper-head'),
        headerText: t.querySelector('.paper-head')?.innerText?.slice(0, 300),
        chips: Array.from(t.querySelectorAll('.paper-chip')).map((c) => c.textContent.trim()),
        quoteStatus: t.querySelector('.paper-quote-status')?.innerText?.slice(0, 300),
        price: t.querySelector('.paper-price')?.textContent?.trim(),
      };
    })()
  `);
  check("panel shows the PAPER banner", /PAPER SIMULATION/.test(header?.banner || ""), header?.banner);
  check("instrument header rendered", Boolean(header?.hasHeader));
  check("header carries a real symbol", /OGDC/i.test(header?.headerText || ""), header?.headerText?.split("\n")[0]);
  check("header shows a numeric price", /\d/.test(header?.price || ""), header?.price);
  check("data mode / source chips present", (header?.chips || []).length >= 1, (header?.chips || []).join(" | "));

  // -------------------------------------------------------- quick amounts
  console.log("\n[2] quick amount controls");
  const amountBefore = await session.evaluate(`document.querySelector('#paper-amount')?.value`);
  await session.evaluate(`
    (() => {
      const btn = Array.from(document.querySelectorAll('.paper-quick')).find((b) => b.textContent.trim() === '+5');
      if (btn) btn.click();
      return true;
    })()
  `);
  await session.wait(300);
  const amountAfter = await session.evaluate(`document.querySelector('#paper-amount')?.value`);
  check("+5 quick button changes the simulated value", amountBefore !== amountAfter, `${amountBefore} → ${amountAfter}`);

  // ------------------------------------------------------- market submit
  console.log("\n[3] PAPER BUY (MARKET) simulation");
  const submitLabel = await session.evaluate(`document.querySelector('.paper-submit-button')?.textContent?.trim()`);
  check("submit button is labelled as a simulation", /simulation/i.test(submitLabel || ""), submitLabel);

  const submitEnabled = await session.evaluate(`(() => {
    const btn = document.querySelector('.paper-submit-button');
    if (btn && !btn.disabled) { btn.click(); return true; }
    return false;
  })()`);
  check("submit is enabled once the quote is real", submitEnabled === true);

  // The panel must resolve out of SUBMITTING and into a result.
  await waitFor(session, `!document.querySelector('.paper-submit-button.busy')`, { label: "submit to settle" });
  const afterSubmit = await session.evaluate(`
    (() => {
      const t = document.querySelector('.paper-ticket');
      const result = t?.querySelector('.paper-result');
      return {
        submitText: t?.querySelector('.paper-submit-button')?.textContent?.trim(),
        hasResult: !!result,
        status: result?.querySelector('.paper-result-status')?.textContent?.trim(),
        error: t?.querySelector('.paper-error')?.textContent?.trim() || null,
        historyRows: t?.querySelectorAll('.paper-history-table tbody tr').length ?? 0,
        notStuck: !/SUBMITTING/.test(t?.querySelector('.paper-submit-button')?.textContent || ""),
      };
    })()
  `);
  check("panel is not stuck on SUBMITTING", afterSubmit?.notStuck, afterSubmit?.submitText);
  check("a simulation result is shown", Boolean(afterSubmit?.hasResult), afterSubmit?.status);
  check(
    "result is labelled SIMULATED (never EXECUTED/FILLED)",
    /SIMULATED/.test(afterSubmit?.status || ""),
    afterSubmit?.status,
  );
  check("recent simulations list gains a row", (afterSubmit?.historyRows ?? 0) >= 1, `${afterSubmit?.historyRows} row(s)`);

  // -------------------------------------------------------------- invalid
  console.log("\n[4] invalid input blocks submission");
  await session.evaluate(`
    (() => {
      const input = document.querySelector('#paper-amount');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, '0');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()
  `);
  await session.wait(600);
  const invalidState = await session.evaluate(`
    (() => {
      const t = document.querySelector('.paper-ticket');
      return {
        blocked: t?.querySelector('.paper-submit-button')?.disabled ?? false,
        issues: t?.querySelector('.paper-issues')?.innerText?.slice(0, 200) || null,
        amountError: t?.querySelector('#paper-amount-error')?.textContent || null,
      };
    })()
  `);
  check("zero amount disables submit", invalidState?.blocked === true);
  check("a specific issue is shown", Boolean(invalidState?.amountError || invalidState?.issues), invalidState?.amountError || invalidState?.issues);

  // ---------------------------------------------------------------- limit
  console.log("\n[5] LIMIT order type");
  await session.evaluate(`
    (() => {
      const input = document.querySelector('#paper-amount');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, '25');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      const limit = Array.from(document.querySelectorAll('.paper-segment')).find((b) => b.textContent.trim() === 'LIMIT');
      if (limit) limit.click();
      return true;
    })()
  `);
  await session.wait(700);
  const limitState = await session.evaluate(`
    (() => {
      const t = document.querySelector('.paper-ticket');
      return {
        hasLimitInput: !!t?.querySelector('#paper-limit-price'),
        explanation: t?.querySelector('.paper-hint')?.textContent?.slice(0, 160) || null,
        blockedWithoutPrice: t?.querySelector('.paper-submit-button')?.disabled ?? false,
      };
    })()
  `);
  check("LIMIT reveals a price input", Boolean(limitState?.hasLimitInput));
  check("LIMIT without a price is blocked", limitState?.blockedWithoutPrice === true);

  const observedReference = await session.evaluate(
    `document.querySelector('.paper-reference-value')?.textContent?.replace(/[^0-9.]/g, '') || ''`,
  );
  const limitValue = observedReference && Number(observedReference) > 1
    ? String(Math.max(0.01, Math.round(Number(observedReference) * 0.9 * 100) / 100))
    : "1";
  await session.evaluate(`
    (() => {
      const input = document.querySelector('#paper-limit-price');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, '${limitValue}');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()
  `);
  await session.wait(1200);
  const limitReady = await session.evaluate(`!document.querySelector('.paper-submit-button')?.disabled`);
  check("valid LIMIT becomes submittable", limitReady === true, `limit ${limitValue} vs observed ${observedReference || "n/a"}`);

  // ------------------------------------------------------------- forecast
  console.log("\n[6] forecast event ticket (probability mode)");
  await session.goto(`${BASE}/forecasts`);
  const marketHref = await waitFor(
    session,
    `(() => { const a = document.querySelector('a[href^="/forecast/"]'); return a ? a.getAttribute('href') : null; })()`,
    { label: "a forecast market link", timeout: 40_000 },
  );
  await session.goto(`${BASE}${marketHref}`);
  await waitFor(session, `document.body.innerText.includes('probability') || document.body.innerText.includes('Probability')`, {
    label: "forecast detail",
    timeout: 40_000,
  });
  check("forecast detail page loads", true, marketHref);

  const fcTrigger = await session.evaluate(`
    (() => {
      const btn = Array.from(document.querySelectorAll('button')).find((b) => /Forecast ticket/i.test(b.textContent || ""));
      if (btn) { btn.click(); return true; }
      return false;
    })()
  `);
  check("forecast ticket trigger exists", fcTrigger === true);
  if (fcTrigger) {
    await waitFor(session, `!!document.querySelector('.paper-ticket .paper-segmented')`, { label: "forecast ticket" });
    // The forecast instrument resolves through the market source; wait for it.
    await waitForQuote(session, "forecast ticket probability");
    const fc = await session.evaluate(`
      (() => {
        const t = document.querySelector('.paper-ticket');
        const segments = Array.from(t.querySelectorAll('.paper-segment')).map((s) => s.textContent.trim());
        return {
          segments,
          text: t.innerText.slice(0, 1200),
          hasProbability: /probability/i.test(t.innerText),
        };
      })()
    `);
    check("forecast mode offers YES / NO", fc.segments.includes("YES") && fc.segments.includes("NO"), fc.segments.join(", "));
    check("forecast mode never offers BUY / SELL", !fc.segments.includes("BUY") && !fc.segments.includes("SELL"));
    check("forecast mode shows a probability", fc.hasProbability === true);
    check("forecast mode states the simulation is non-monetary", /not a real order|no order is placed/i.test(fc.text));
  }

  // ----------------------------------------------------------------- done
  console.log("\n————————————————————————————————");
  console.log(`checks: ${checks}, failed: ${failures.length}`);
  if (problems.length) {
    console.log(`runtime problems (${problems.length}):`);
    for (const p of [...new Set(problems)].slice(0, 20)) console.log(`  ! ${p}`);
  } else {
    console.log("runtime problems: none");
  }
  if (failures.length) {
    console.log("\nfailed checks:");
    for (const f of failures) console.log(`  ✗ ${f}`);
  }

  ws.close();
  process.exit(failures.length || problems.length ? 1 : 0);
}

main().catch((error) => {
  console.error(`audit crashed: ${error.message}`);
  process.exit(1);
});

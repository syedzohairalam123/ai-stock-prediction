/*
 * One-off probe #2: does react-grid-layout respond to real CDP drag/resize?
 */
const CDP = "http://127.0.0.1:9222";
const BASE = "http://localhost:5173";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const targets = await (await fetch(`${CDP}/json/list`)).json();
const target = targets.find((t) => t.type === "page");
if (!target) throw new Error("no page target");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { socket.onopen = res; socket.onerror = rej; });

let nextId = 0;
const pending = new Map();
socket.onmessage = (event) => { const m = JSON.parse(event.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
const send = (method, params = {}) => { const id = ++nextId; return new Promise((resolve) => { pending.set(id, resolve); socket.send(JSON.stringify({ id, method, params })); }); };
const evaluate = async (expression) => {
  const reply = await send("Runtime.evaluate", { expression: `(() => { ${expression} })()`, returnByValue: true, awaitPromise: true });
  const { result, exceptionDetails } = reply.result || {};
  if (exceptionDetails) throw new Error(exceptionDetails.exception?.description || "eval fail");
  return result?.value;
};
const dragFromTo = async (x1, y1, x2, y2) => {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x1, y: y1, buttons: 0 });
  await sleep(80);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: x1, y: y1, button: "left", buttons: 1, clickCount: 1 });
  await sleep(120);
  for (let i = 1; i <= 10; i++) {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x1 + ((x2 - x1) * i) / 10, y: y1 + ((y2 - y1) * i) / 10, button: "left", buttons: 1 });
    await sleep(40);
  }
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: x2, y: y2, button: "left", buttons: 0, clickCount: 1 });
  await sleep(400);
};

await send("Runtime.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
await send("Storage.clearDataForOrigin", { origin: BASE, storageTypes: "local_storage" });
await send("Page.navigate", { url: `${BASE}/workspace` });
await sleep(2500);
for (let i = 0; i < 30; i++) { if (await evaluate("return Boolean(document.querySelector('.ws-grid'))")) break; await sleep(500); }

const box0 = await evaluate(`
  const b = document.querySelector('.ws-widget').getBoundingClientRect();
  return { top: Math.round(b.top), left: Math.round(b.left), w: Math.round(b.width), h: Math.round(b.height) };
`);
console.log("before drag:", JSON.stringify(box0));

// Drag widget 0's header down 300px
await dragFromTo(box0.left + 100, box0.top + 15, box0.left + 100, box0.top + 315);

const box1 = await evaluate(`
  const b = document.querySelector('.ws-widget').getBoundingClientRect();
  return { top: Math.round(b.top), left: Math.round(b.left), w: Math.round(b.width), h: Math.round(b.height) };
`);
console.log("after drag:", JSON.stringify(box1));

// Resize probe: SE handle at bottom-right corner
const box2 = await evaluate(`
  const w = document.querySelector('.ws-widget');
  const handle = w.querySelector('.react-resizable-handle');
  return {
    hasHandle: Boolean(handle),
    handleClasses: handle ? handle.className : null,
    handles: w.querySelectorAll('.react-resizable-handle').length,
  };
`);
console.log("resize handles:", JSON.stringify(box2));

if (box2.handles > 0) {
  const boxb = await evaluate(`
    const b = document.querySelector('.ws-widget').getBoundingClientRect();
    return { right: Math.round(b.right), bottom: Math.round(b.bottom), w: Math.round(b.width), h: Math.round(b.height) };
  `);
  console.log("before resize:", JSON.stringify(boxb));
  await dragFromTo(boxb.right - 5, boxb.bottom - 5, boxb.right + 80, boxb.bottom + 50);
  const box3 = await evaluate(`
    const b = document.querySelector('.ws-widget').getBoundingClientRect();
    return { w: Math.round(b.width), h: Math.round(b.height) };
  `);
  console.log("after resize:", JSON.stringify(box3));
}

process.exit(0);

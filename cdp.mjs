#!/usr/bin/env node
// cdp.mjs - evaluate JS in an Electron/Chrome page via CDP (native WebSocket, zero deps)
// Usage: node cdp.mjs "<js-expression>" [port] [titleSubstr]
const expr = process.argv[2];
const port = process.argv[3] || "9222";
const titleSubstr = process.argv[4] || "";

if (!expr) {
  console.error("usage: node cdp.mjs <js> [port] [titleSubstr]");
  process.exit(1);
}

const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = targets.find(t => t.type === "page" && (!titleSubstr || (t.title || "").includes(titleSubstr)))
  || targets.find(t => t.type === "page");
if (!page) {
  console.error("no page target; targets=", targets.map(t => t.title).join(","));
  process.exit(1);
}

const ws = new WebSocket(page.webSocketDebuggerUrl);
let nextId = 0;
const pending = new Map();
ws.addEventListener("message", (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
await new Promise((res, rej) => { ws.addEventListener("open", res); ws.addEventListener("error", rej); });

function send(method, params = {}) {
  return new Promise((resolve) => {
    const id = ++nextId;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
if (r.error) {
  console.error("CDP error:", JSON.stringify(r.error));
  process.exitCode = 1;
} else {
  const res = r.result && r.result.result;
  const val = res && "value" in res ? res.value : (res ? res.description : undefined);
  if (typeof val === "string") console.log(val);
  else console.log(JSON.stringify(val, null, 2));
  if (r.result && r.result.exceptionDetails) {
    console.error("EXCEPTION:", JSON.stringify(r.result.exceptionDetails, null, 2));
    process.exitCode = 2;
  }
}
ws.close();
process.exit(0);

#!/usr/bin/env node
/* Frontend smoke test (no dependencies, no jsdom).

Loads the shipped dist/app.js inside a VM with a minimal DOM/fetch stub, lets
init() finish (it fetches the six datasets and renders every tab), then calls
the exported stExplorer.renderDialogue() across every knot in index.json and
expects zero throws — the same headless check the README describes.

Exit code 0 = everything rendered cleanly; nonzero = a throw was reproduced.
*/
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXPLORER = path.resolve(__dirname, "..");
const DIST = path.join(EXPLORER, "dist");

// ---------------------------------------------------------------------------
// Minimal, honest DOM stub. Element covers what the renderers actually touch;
// anything else is a no-op (permissive) so the app can boot headlessly, but a
// *missing method call* still throws and is reported as a real failure.
// ---------------------------------------------------------------------------
class El {
  constructor(tag) {
    this.tagName = (tag || "div").toUpperCase();
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.attrs = {};
    this.listeners = {};
    this._classSet = new Set();
    this.scrollTop = 0;
    this.scrollLeft = 0;
    this.value = "";
    this.checked = false;
    this.selected = false;
    this.disabled = false;
    this.textContent = "";
    this.innerHTML = "";
  }
  appendChild(c) { if (c != null) this.children.push(c); return c; }
  insertBefore(c) { return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(c)); }
  remove() {}
  get childNodes() { return this.children; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener() {}
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  get classList() {
    const s = this._classSet;
    return {
      add: (...a) => a.forEach((x) => s.add(x)),
      remove: (...a) => a.forEach((x) => s.delete(x)),
      toggle: (c, f) => {
        const has = s.has(c);
        if (f === undefined) { has ? s.delete(c) : s.add(c); return !has; }
        f ? s.add(c) : s.delete(c);
        return f;
      },
      contains: (c) => s.has(c),
    };
  }
  querySelector() { return new El("div"); }
  querySelectorAll() { return []; }
  closest() { return null; }
  focus() {}
  blur() {}
  click() {}
}

const elById = new Map();
const documentStub = {
  getElementById: (id) => {
    if (!elById.has(id)) elById.set(id, new El("div"));
    return elById.get(id);
  },
  createElement: (t) => new El(t),
  querySelector: () => new El("div"),
  querySelectorAll: () => [],
  addEventListener: () => {},
  body: new El("body"),
};

const localStorageStub = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
const historyStub = { state: null, replaceState() {}, pushState() {}, back() {} };
const alertStub = () => {};

const fetchStub = async (url) => {
  const rel = String(url).replace(/^\//, "");
  const p = path.join(DIST, rel);
  if (!p.startsWith(DIST + path.sep)) throw new Error("fetch outside dist: " + url);
  const text = fs.readFileSync(p, "utf-8");
  return { ok: true, status: 200, json: async () => JSON.parse(text) };
};

// ---------------------------------------------------------------------------
// Boot the app in a sandbox.
// ---------------------------------------------------------------------------
const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  Date,
  JSON,
  Math,
  RegExp,
  document: documentStub,
  localStorage: localStorageStub,
  history: historyStub,
  fetch: fetchStub,
  alert: alertStub,
  addEventListener: () => {},
};
sandbox.window = sandbox;
vm.createContext(sandbox);

const appSrc = fs.readFileSync(path.join(DIST, "app.js"), "utf-8");
vm.runInContext(appSrc, sandbox, { filename: "dist/app.js" });

// ---------------------------------------------------------------------------
// Wait for init() (async fetches) to finish, then render every knot.
// ---------------------------------------------------------------------------
const DEADLINE = Date.now() + 20000;

function waitReady() {
  return new Promise((resolve, reject) => {
    const poll = () => {
      // INDEX is a top-level `let` (lexical binding), not a global property:
      // read it through the context's scope chain.
      const stats = vm.runInContext("INDEX ? INDEX.stats : null", sandbox);
      const knotCount = stats ? vm.runInContext("Object.keys(INDEX.knots).length", sandbox) : 0;
      if (stats && knotCount === stats.knots) {
        return resolve(stats);
      }
      if (Date.now() > DEADLINE) {
        return reject(new Error("init() did not complete within the deadline"));
      }
      setTimeout(poll, 25);
    };
    poll();
  });
}

waitReady().then(() => {
  const api = sandbox.window.stExplorer;
  if (!api || typeof api.renderDialogue !== "function" || typeof api.tokensOf !== "function") {
    throw new Error("stExplorer API surface missing from dist/app.js");
  }

  const knots = vm.runInContext("INDEX.knots", sandbox);
  let total = 0;
  const failures = [];
  for (const [name, k] of Object.entries(knots)) {
    k.name = name;
    try {
      api.renderDialogue(k, new El("div"));
      total += 1;
    } catch (err) {
      failures.push({ name, err: err && err.stack ? err.stack : String(err) });
    }
  }

  console.log(`renderDialogue smoke: ${total}/${Object.keys(knots).length} knots rendered, ${failures.length} failures`);
  if (failures.length) {
    for (const f of failures.slice(0, 10)) console.error("  " + f.name + ": " + f.err);
    process.exit(1);
  }

  // The other five tabs rendered during init() without throwing (they did
  // during boot) — report their data volumes as a sanity line, then render
  // the Audiences tab explicitly (both views) and open one of each drawer.
  const q = vm.runInContext("QUEST && QUEST.stats ? QUEST.stats.quests : 0", sandbox);
  const inv = vm.runInContext("INV && INV.stats ? INV.stats.items : 0", sandbox);
  const kn = vm.runInContext("KNIGHTS && KNIGHTS.stats ? KNIGHTS.stats.total : 0", sandbox);
  const sp = vm.runInContext("SPECIAL && SPECIAL.stats ? SPECIAL.stats.total : 0", sandbox);
  const aud = vm.runInContext("AUDIENCE && AUDIENCE.stats ? AUDIENCE.stats : null", sandbox);
  if (!aud || aud.audiences !== 511 || aud.requests !== 34) {
    throw new Error("AUDIENCE dataset did not load (stats=" + JSON.stringify(aud) + ")");
  }
  vm.runInContext("renderAudienceResults()", sandbox);
  vm.runInContext("openAudienceDetail(Object.keys(AUDIENCE.audiences)[0])", sandbox);
  vm.runInContext("openRequestDetail(Object.keys(AUDIENCE.requests)[0])", sandbox);
  // the knot drawer's "Where it comes from" section is built from the AUDIENCE
  // dataset (knotAudiences/knotFuQuests) — open one that has both audiences and
  // follow-up quests to keep that re-pointing locked in.
  vm.runInContext("openDetail('county_quest_enberg_first_audience')", sandbox);

  // Dialogues-tab link filters ("Where it comes from" + cross-link selects).
  // The DOM stub's selects don't carry `options`, so assert through the state/
  // reverse maps instead: the source flags and the audience type/NPC selects
  // must actually narrow visibleKnots().
  vm.runInContext("buildLinkFilterUI()", sandbox);
  const srcAud = vm.runInContext("state.srcAud = true; (() => { const n = visibleKnots().length; state.srcAud = false; return n; })()", sandbox);
  if (!(srcAud > 0)) throw new Error("srcAud filter matched nothing (grest_first_grievance should be an audience)");
  const byAudF = vm.runInContext("state.kf = 'doleances'; (() => { const n = visibleKnots().length; state.kf = ''; return n; })()", sandbox);
  const byAudC = vm.runInContext("state.kc = 'ROLAND_NAME'; (() => { const n = visibleKnots().length; state.kc = ''; return n; })()", sandbox);
  const srcFu = vm.runInContext("state.srcFu = true; (() => { const n = visibleKnots().length; state.srcFu = false; return n; })()", sandbox);
  const srcUq = vm.runInContext("state.srcUq = true; (() => { const n = visibleKnots().length; state.srcUq = false; return n; })()", sandbox);
  const srcSp = vm.runInContext("state.srcSp = true; (() => { const n = visibleKnots().length; state.srcSp = false; return n; })()", sandbox);
  const srcKn = vm.runInContext("state.srcKn = true; (() => { const n = visibleKnots().length; state.srcKn = false; return n; })()", sandbox);
  const inGrest = vm.runInContext("state.kf = 'doleances'; (() => { const r = visibleKnots().some(k => k.name === 'grest_first_grievance'); state.kf = ''; return r; })()", sandbox);
  if (!(byAudF > 0) || !(byAudC > 0)) throw new Error("audience type/NPC filters matched nothing");
  if (!(srcUq > 0) || !(srcSp > 0) || !(srcKn > 0)) throw new Error("unlocks/special/knight source filters matched nothing");
  if (!inGrest) throw new Error("grest_first_grievance knot not in the audience-type result set");
  console.log(`frontend smoke OK (quests=${q} inv=${inv} knights=${kn} special=${sp} audiences=${aud.audiences} requests=${aud.requests} srcAud=${srcAud} srcFu=${srcFu} kf=${byAudF} kc=${byAudC})`);
}).catch((err) => {
  console.error(err.stack || String(err));
  process.exit(1);
});

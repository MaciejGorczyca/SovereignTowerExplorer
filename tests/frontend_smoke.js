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

// DocumentFragment stub: the app uses it to append a section header + its body
// as siblings in the knot drawer.
class Frag {
  constructor() { this.children = []; }
  get childNodes() { return this.children; }
  appendChild(c) { if (c != null) this.children.push(c); return c; }
  remove() {}
}

const elById = new Map();
const documentStub = {
  getElementById: (id) => {
    if (!elById.has(id)) elById.set(id, new El("div"));
    return elById.get(id);
  },
  createElement: (t) => new El(t),
  createDocumentFragment: () => new Frag(),
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
  // Chain of events: doleance + quest-success edges must put the enberg county
  // quest line in order (first_audience → audience_2 → audience_3_interrogation)
  // and leave the final audience in the branch options.
  const chain1 = vm.runInContext("knotChain('county_quest_enberg_first_audience')", sandbox);
  if (chain1.before.length !== 0 ||
      chain1.after[0] !== "county_quest_enberg_audience_2" ||
      chain1.after[1] !== "county_quest_enberg_audience_3_interrogation") {
    throw new Error("chain first_audience wrong: " + JSON.stringify(chain1));
  }
  const chain3 = vm.runInContext("knotChain('county_quest_enberg_audience_3_interrogation')", sandbox);
  if (chain3.before[0] !== "county_quest_enberg_first_audience" ||
      chain3.before[1] !== "county_quest_enberg_audience_2" ||
      !chain3.nextTips.includes("county_quest_enberg_audience_final")) {
    throw new Error("chain audience_3_interrogation wrong: " + JSON.stringify(chain3));
  }
  const chainPlain = vm.runInContext("(() => { const c = knotChain('grest_first_grievance'); return c.before.length + c.after.length + c.prevTips.length + c.nextTips.length; })()", sandbox);
  if (chainPlain !== 0) throw new Error("chain rendered for an unrelated knot: " + chainPlain);
  // Audience-request quest rewards: the "⚑ Request …" success reward must be a
  // clickable request link, and the reward must surface in the "What happens"
  // facts as a request fact row.
  const hireQuest = vm.runInContext("QUEST.quests.quest_enberg_hire_an_assassin", sandbox);
  if (!hireQuest) throw new Error("quest_enberg_hire_an_assassin missing from quests dataset");
  const reqReward = hireQuest.mo[1].sr[0];
  const reqHtml = vm.runInContext(`rewardHtml(${JSON.stringify(reqReward)})`, sandbox);
  if (!/reqlink/.test(reqHtml) || !/data-req="bettie_request_victoria"/.test(reqHtml)) {
    throw new Error("AUDIENCE_REQUEST reward not clickable: " + reqHtml);
  }
  const facts = vm.runInContext("JSON.stringify(questHappensFacts(QUEST.quests.quest_enberg_hire_an_assassin))", sandbox);
  if (!/bettie_request_victoria/.test(facts)) {
    throw new Error("AUDIENCE_REQUEST missing from What happens facts: " + facts);
  }
  const wfr = vm.runInContext("(() => { const row = whatFactRow({ k: 'request', stem: 'bettie_request_victoria' }); const body = row.children[1]; return body ? body.innerHTML : ''; })()", sandbox);
  if (!/Grants audience request/.test(wfr) || !/data-req="bettie_request_victoria"/.test(wfr)) {
    throw new Error("What happens request fact row not clickable: " + wfr);
  }
  console.log(`frontend smoke OK (quests=${q} inv=${inv} knights=${kn} special=${sp} audiences=${aud.audiences} requests=${aud.requests} srcAud=${srcAud} srcFu=${srcFu} kf=${byAudF} kc=${byAudC})`);
}).catch((err) => {
  console.error(err.stack || String(err));
  process.exit(1);
});

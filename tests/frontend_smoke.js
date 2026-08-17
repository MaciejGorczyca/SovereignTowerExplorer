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
      const dlgReady = vm.runInContext(
        "DIALOGUE && DIALOGUE.stats ? DIALOGUE.stats.all : 0", sandbox);
      const endReady = vm.runInContext(
        "ENDINGS && ENDINGS.types ? Object.keys(ENDINGS.types).length : 0", sandbox);
      const audReady = vm.runInContext(
        "AUDIENCE && AUDIENCE.stats ? AUDIENCE.stats.audiences : 0", sandbox);
      if (stats && knotCount === stats.knots && dlgReady === 235 && endReady === 6 && audReady === 511) {
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
  // Task N1: request unlock sources. requestUnlocks() inverts knotRequests()
  // (UnlockAudienceRequest call sites) per request stem; the request drawer
  // renders an "Unlocked by ink" section and the request cards a chip.
  const drawerText = () => {
    const parts = [];
    const walk = (n) => {
      if (!n) return;
      if (n.textContent) parts.push(n.textContent);
      if (n.innerHTML) parts.push(n.innerHTML.replace(/<[^>]+>/g, " "));
      for (const c of n.children || []) walk(c);
    };
    walk(elById.get("drawerpanel"));
    return parts.join(" ").toLowerCase();
  };
  // The DOM stub's innerHTML="" does not detach children (real DOM would), so
  // clear the panel between drawer opens to keep the tree small and honest.
  const clearPanel = () => { elById.get("drawerpanel").children.length = 0; };
  const rowanUnl = vm.runInContext("requestUnlocks().get('rowan_request') || []", sandbox);
  if (!rowanUnl.includes("arlin_introduction_to_act_2") ||
      !rowanUnl.includes("rowan_audience_request_recruitment")) {
    throw new Error("rowan_request unlock sites wrong: " + JSON.stringify(rowanUnl));
  }
  if (vm.runInContext("requestUnlocks().size", sandbox) !== 34) {
    throw new Error("requestUnlocks does not cover all 34 requests");
  }
  clearPanel();
  vm.runInContext("openRequestDetail('rowan_request')", sandbox);
  if (drawerText().indexOf("arlin_introduction_to_act_2") < 0 ||
      drawerText().indexOf("unlocked by ink") < 0) {
    throw new Error("rowan_request drawer missing its unlock sources: " + drawerText());
  }
  for (const [stem, r] of vm.runInContext("Object.entries(AUDIENCE.requests)", sandbox)) {
    const unlocks = vm.runInContext(
      "requestUnlocks().get(" + JSON.stringify(stem) + ") || []", sandbox);
    if (!unlocks.length) continue;
    clearPanel();
    vm.runInContext("openRequestDetail(" + JSON.stringify(stem) + ")", sandbox);
    const txt = drawerText();
    if (txt.indexOf("unlocked by ink") < 0 ||
        !unlocks.some((k) => txt.indexOf(k) >= 0)) {
      throw new Error("request drawer missing unlock rows for " + stem + ": " + txt);
    }
  }
  const rowanCard = vm.runInContext("reqCard('rowan_request', AUDIENCE.requests.rowan_request)", sandbox);
  if (!/unlocked by 2 knots/.test(rowanCard.innerHTML)) {
    throw new Error("rowan_request card missing unlock chip: " + rowanCard.innerHTML);
  }
  if (!vm.runInContext("rhay('rowan_request', AUDIENCE.requests.rowan_request).indexOf('arlin_introduction_to_act_2') >= 0", sandbox)) {
    throw new Error("request unlock knot not indexed in the request haystack");
  }
  // Task N2: divert-reached sub-scene audiences. Audiences whose ink knot is
  // reached via an ink divert inside another, scheduled audience's scene get a
  // divt row ("Plays inside <parent>") resolved from knotIncoming (nearest
  // scheduled ancestor audience); two audience resources sharing one ink path
  // get a dup row on the non-scheduled one ("Same scene as <sibling>").
  const divtRows = vm.runInContext(
    "divertInRows('county_quest_brimwood_3_testimony_2', AUDIENCE.audiences['county_quest_brimwood_3_testimony_2'])", sandbox);
  if (!divtRows.length || divtRows[0].kind !== "divt" ||
      divtRows[0].html.indexOf("county_quest_brimwood_3_before_testimony") < 0 ||
      divtRows[0].html.indexOf("ink-divert") < 0) {
    throw new Error("testimony_2 divert row wrong: " + JSON.stringify(divtRows));
  }
  const brWHtml = vm.runInContext(
    "audienceConditionRows('county_quest_brimwood_3_testimony_2', AUDIENCE.audiences['county_quest_brimwood_3_testimony_2']).join(' | ')", sandbox);
  if (brWHtml.indexOf("county_quest_brimwood_3_before_testimony") < 0) {
    throw new Error("testimony_2 condition row missing parent: " + brWHtml);
  }
  const brCond = vm.runInContext(
    "audienceConditionCount('county_quest_brimwood_3_testimony_2', AUDIENCE.audiences['county_quest_brimwood_3_testimony_2'])", sandbox);
  if (brCond < 1) throw new Error("testimony_2 no gating conditions after N2");
  if (!vm.runInContext("ahay('county_quest_brimwood_3_testimony_2', AUDIENCE.audiences['county_quest_brimwood_3_testimony_2']).indexOf('county_quest_brimwood_3_before_testimony') >= 0", sandbox)) {
    throw new Error("divert parent not in audience haystack");
  }
  const dupRows = vm.runInContext(
    "divertInRows('county_quest_brimwood_3_testimony_1', AUDIENCE.audiences['county_quest_brimwood_3_testimony_1'])", sandbox);
  if (!dupRows.length || dupRows[0].kind !== "dup" ||
      dupRows[0].html.indexOf("county_quest_brimwood_3_before_testimony") < 0 ||
      dupRows[0].html.indexOf("Same scene as") < 0) {
    throw new Error("testimony_1 same-ink row wrong: " + JSON.stringify(dupRows));
  }
  const schedTest1 = vm.runInContext("baseAudienceGates('county_quest_brimwood_3_testimony_1', AUDIENCE.audiences['county_quest_brimwood_3_testimony_1']).length", sandbox);
  if (schedTest1 !== 0) throw new Error("testimony_1 unexpectedly has a base schedule channel");
  const schedBefore = vm.runInContext("baseAudienceGates('county_quest_brimwood_3_before_testimony', AUDIENCE.audiences['county_quest_brimwood_3_before_testimony']).length", sandbox);
  if (schedBefore < 1) throw new Error("before_testimony lost its doleance schedule after N2");
  // the sibling (doleance-scheduled) must NOT gain a dup/divt row — it has real
  // conditions, so divertInRows stays empty there
  const beforeRows = vm.runInContext(
    "divertInRows('county_quest_brimwood_3_before_testimony', AUDIENCE.audiences['county_quest_brimwood_3_before_testimony'])", sandbox);
  if (beforeRows.length) throw new Error("scheduled before_testimony got a spurious N2 row: " + JSON.stringify(beforeRows));
  // one of the divert-reached interventions + a candidacy resolve too
  const brIntRows = vm.runInContext(
    "divertInRows('intervention_brunhilda_brimwood_testimony', AUDIENCE.audiences['intervention_brunhilda_brimwood_testimony'])", sandbox);
  if (!brIntRows.length || brIntRows[0].kind !== "divt" ||
      brIntRows[0].html.indexOf("county_quest_brimwood_3_before_testimony") < 0) {
    throw new Error("brimwood intervention divert row wrong: " + JSON.stringify(brIntRows));
  }
  const cadRows = vm.runInContext(
    "divertInRows('childeric_candidacy', AUDIENCE.audiences['childeric_candidacy'])", sandbox);
  if (!cadRows.length || cadRows[0].kind !== "divt" ||
      cadRows[0].html.indexOf("county_quest_almor_final_success") < 0) {
    throw new Error("childeric candidacy divert row wrong: " + JSON.stringify(cadRows));
  }
  // the "has gating conditions" filter (ASTATE.cond) now also matches these
  const test2Cond = vm.runInContext("(() => { ASTATE.cond = true; const r = visibleAudiences().some(([s]) => s === 'county_quest_brimwood_3_testimony_2'); ASTATE.cond = false; return r; })()", sandbox);
  if (!test2Cond) throw new Error("divert-reached audience not matched by the gating filter");
  clearPanel();
  vm.runInContext("openAudienceDetail('county_quest_brimwood_3_testimony_2')", sandbox);
  if (drawerText().indexOf("county_quest_brimwood_3_before_testimony") < 0 ||
      drawerText().indexOf("ink-divert") < 0) {
    throw new Error("testimony_2 drawer missing the divert row: " + drawerText());
  }
  // Task N4: code-scheduled knight events. Audiences queued directly from game
  // code (no quest/doleance/request/special-`auds`/director/divert channel) carry
  // a `code` field rendered as a Conditions row, counted in the gating badge +
  // acond filter and indexed in the audience haystack.
  const codeCount = vm.runInContext(
    "Object.keys(AUDIENCE.audiences).filter((s) => AUDIENCE.audiences[s].code).length", sandbox);
  if (codeCount !== 4) throw new Error("code-scheduled audiences != 4: " + codeCount);
  const codeEdith = vm.runInContext(
    "codeGateHtml(AUDIENCE.audiences['edith_gimmick_introduction_demon_possession'].code[0])", sandbox);
  if (codeEdith.indexOf("Knight gimmick") < 0 || codeEdith.indexOf("killing quest") < 0 ||
      codeEdith.indexOf("Edith") < 0) {
    throw new Error("edith gimmick code row render wrong: " + codeEdith);
  }
  const codeEdithRows = vm.runInContext(
    "audienceConditionRows('edith_gimmick_introduction_demon_possession', AUDIENCE.audiences['edith_gimmick_introduction_demon_possession']).join(' | ')", sandbox);
  if (codeEdithRows.indexOf("fires after a killing quest completes with Edith") < 0) {
    throw new Error("edith gimmick condition row missing: " + codeEdithRows);
  }
  if (vm.runInContext(
    "audienceConditionCount('edith_gimmick_introduction_demon_possession', AUDIENCE.audiences['edith_gimmick_introduction_demon_possession'])", sandbox) < 1) {
    throw new Error("edith gimmick has no gating conditions after N4");
  }
  if (!vm.runInContext("ahay('edith_gimmick_introduction_demon_possession', AUDIENCE.audiences['edith_gimmick_introduction_demon_possession']).indexOf('killing quest') >= 0", sandbox)) {
    throw new Error("edith gimmick code note not in audience haystack");
  }
  const codeArrivalRows = vm.runInContext(
    "audienceConditionRows('dulahan_candidacy', AUDIENCE.audiences['dulahan_candidacy']).join(' | ')", sandbox);
  if (codeArrivalRows.indexOf("Goberto") < 0 || codeArrivalRows.indexOf("Dulahan") < 0) {
    throw new Error("dulahan candidacy code row missing: " + codeArrivalRows);
  }
  const codeReunionRows = vm.runInContext(
    "audienceConditionRows('lost_child_plotline_groveshire_gavault_confrontation', AUDIENCE.audiences['lost_child_plotline_groveshire_gavault_confrontation']).join(' | ')", sandbox);
  if (codeReunionRows.indexOf("groveshire_gavault_reconciled") < 0 ||
      codeReunionRows.indexOf("brunhilda_countess") < 0) {
    throw new Error("family-reunion code row missing: " + codeReunionRows);
  }
  const codeKutnarRows = vm.runInContext(
    "audienceConditionRows('intervention_tarcus_county_quest_kutnar_first_audience', AUDIENCE.audiences['intervention_tarcus_county_quest_kutnar_first_audience']).join(' | ')", sandbox);
  if (codeKutnarRows.indexOf("KUTNAR_TARCUS_INTERVENTION") < 0 ||
      codeKutnarRows.indexOf("roundtable") < 0) {
    throw new Error("kutnar intervention code row missing: " + codeKutnarRows);
  }
  const codeCondFilter = vm.runInContext(
    "(() => { ASTATE.cond = true; const r = visibleAudiences().some(([s]) => s === 'edith_gimmick_introduction_demon_possession'); ASTATE.cond = false; return r; })()", sandbox);
  if (!codeCondFilter) throw new Error("code-scheduled audience not matched by the gating filter");
  clearPanel();
  vm.runInContext("openAudienceDetail('edith_gimmick_introduction_demon_possession')", sandbox);
  if (drawerText().indexOf("knight gimmick") < 0) {
    throw new Error("edith gimmick drawer missing the code row: " + drawerText());
  }
  // Task N5: legacy-orphan flag. The four `*_classic_recruitment` + two
  // `brizh_*_grievance_first_meeting` audiences are never queued by any channel
  // in the shipped game; they carry `unused` + a `unote` rendered as a
  // Conditions row ("Legacy resource: …"), counted in the gating badge + acond
  // filter, shown as a card badge and indexed into audience search.
  const unusedCount = vm.runInContext(
    "Object.keys(AUDIENCE.audiences).filter((s) => AUDIENCE.audiences[s].unused).length", sandbox);
  if (unusedCount !== 6) throw new Error("unused audiences != 6: " + unusedCount);
  const classicRows = vm.runInContext(
    "audienceConditionRows('rowan_classic_recruitment', AUDIENCE.audiences['rowan_classic_recruitment'])", sandbox);
  if (!classicRows.length || classicRows[0].indexOf("Legacy resource") < 0 ||
      classicRows[0].indexOf("request recruitment") < 0 ||
      classicRows[0].indexOf("shipped game") < 0) {
    throw new Error("classic recruitment unused row wrong: " + JSON.stringify(classicRows));
  }
  const brizhRows = vm.runInContext(
    "audienceConditionRows('brizh_nobles_grievance_first_meeting', AUDIENCE.audiences['brizh_nobles_grievance_first_meeting'])", sandbox);
  if (!brizhRows.length || brizhRows[0].indexOf("orphan knot") < 0) {
    throw new Error("brizh orphan unused row wrong: " + JSON.stringify(brizhRows));
  }
  if (vm.runInContext(
    "audienceConditionCount('brizh_scholars_grievance_first_meeting', AUDIENCE.audiences['brizh_scholars_grievance_first_meeting'])", sandbox) < 1) {
    throw new Error("legacy orphan has no gating condition after N5");
  }
  if (!vm.runInContext("ahay('sagadin_classic_recruitment', AUDIENCE.audiences['sagadin_classic_recruitment']).indexOf('legacy') >= 0", sandbox)) {
    throw new Error("legacy orphan not matched by legacy search");
  }
  const legCondFilter = vm.runInContext(
    "(() => { ASTATE.cond = true; const r = visibleAudiences().some(([s]) => s === 'belladona_classic_recruitment'); ASTATE.cond = false; return r; })()", sandbox);
  if (!legCondFilter) throw new Error("legacy orphan not matched by the gating filter");
  const unusedCard = vm.runInContext(
    "audCard('rowan_classic_recruitment', AUDIENCE.audiences['rowan_classic_recruitment'])", sandbox);
  if (unusedCard.innerHTML.indexOf("legacy") < 0) {
    throw new Error("classic recruitment card missing legacy badge: " + unusedCard.innerHTML);
  }
  clearPanel();
  vm.runInContext("openAudienceDetail('brizh_scholars_grievance_first_meeting')", sandbox);
  if (drawerText().indexOf("legacy resource") < 0 ||
      drawerText().indexOf("orphan knot") < 0) {
    throw new Error("brizh orphan drawer missing the legacy row: " + drawerText());
  }
  // channel 10: knight death-follow-up audiences carry a dd link and search in
  // the audience haystack (both tabs consume the reversed field)
  const ddCount = vm.runInContext("AUDIENCE.stats.with_death_followup", sandbox);
  if (ddCount !== 7) throw new Error("with_death_followup != 7: " + ddCount);
  const ddUrsula = vm.runInContext(
    "AUDIENCE.audiences['ursula_new_gimmick_low_corruption'].dd", sandbox);
  if (!ddUrsula || ddUrsula.length !== 1 || ddUrsula[0][0] !== "ursule" ||
      ddUrsula[0][1] !== "death") {
    throw new Error("ursula gimmick dd wrong: " + JSON.stringify(ddUrsula));
  }
  const ddInKnot = vm.runInContext(
    "(() => { const r = knotAudiences().get('ursula_new_gimmick_low_corruption'); return r ? (r[0] && r[0].dd) : undefined; })()", sandbox);
  if (!ddInKnot || !ddInKnot.length) throw new Error("dd not carried into knotAudiences");
  if (!vm.runInContext("ahay('ursula_new_gimmick_low_corruption', AUDIENCE.audiences['ursula_new_gimmick_low_corruption']).indexOf('ursule') >= 0", sandbox)) {
    throw new Error("death-follow-up knight not in audience haystack");
  }
  // channel 11: knight demission audiences carry a dd "demission" link (with
  // the per-knight variant label) and index in the audience haystack too
  const demCount = vm.runInContext("AUDIENCE.stats.with_demission", sandbox);
  if (demCount !== 29) throw new Error("with_demission != 29: " + demCount);
  const ddAlwena = vm.runInContext("AUDIENCE.audiences['knight_leaving_alwena'].dd", sandbox);
  if (!ddAlwena || ddAlwena.length !== 1 || ddAlwena[0].length !== 2 ||
      ddAlwena[0][0] !== "alwena" || ddAlwena[0][1] !== "demission") {
    throw new Error("knight_leaving_alwena dd wrong: " + JSON.stringify(ddAlwena));
  }
  const ddGwendan = vm.runInContext("AUDIENCE.audiences['gwendan_humble_candidacy'].dd", sandbox);
  if (!ddGwendan || ddGwendan[0].length !== 3 || ddGwendan[0][0] !== "gwendan" ||
      ddGwendan[0][2] !== "humbled") {
    throw new Error("gwendan demission variant wrong: " + JSON.stringify(ddGwendan));
  }
  if (!vm.runInContext("(() => { const r = knotAudiences().get('knight_leaving_alwena'); return r ? (r[0] && r[0].dd.length) : 0; })()", sandbox)) {
    throw new Error("demission dd not carried into knotAudiences");
  }
  if (!vm.runInContext("ahay('knight_leaving_alwena', AUDIENCE.audiences['knight_leaving_alwena']).indexOf('leaves the roundtable') >= 0", sandbox)) {
    throw new Error("demission knight not in audience haystack");
  }
  // channel 13: filler-pack audiences carry a fl link (pack + targeting), the
  // first-grievance knots unlock them (UnlockFillerAudiencesPack), and the
  // pack name indexes in the audience haystack + the knot drawer's row
  const fillerCount = vm.runInContext("AUDIENCE.stats.with_filler", sandbox);
  if (fillerCount !== 234) throw new Error("with_filler != 234: " + fillerCount);
  const flClover = vm.runInContext("AUDIENCE.audiences['clovermont_grievance_emergency'].fl", sandbox);
  if (!flClover || flClover.length !== 3 || flClover[0] !== "clovermont") {
    throw new Error("clovermont filler fl wrong: " + JSON.stringify(flClover));
  }
  const flAcademic = vm.runInContext("AUDIENCE.audiences['brizh_scholars_grievance_copy_cats'].fl", sandbox);
  if (!flAcademic || flAcademic[0] !== "academician") {
    throw new Error("representative filler fl wrong: " + JSON.stringify(flAcademic));
  }
  const flUnlock = vm.runInContext("fillerPackUnlocks().get('clovermont') || []", sandbox);
  if (!flUnlock.includes("clovermont_first_grievance")) {
    throw new Error("filler pack unlock missing: " + JSON.stringify(flUnlock));
  }
  const flInKnot = vm.runInContext("(() => { const r = knotAudiences().get('clovermont_grievance_bakery_problem'); return r ? r.some(x => x.stem === 'clovermont_grievance_bakery_problem' && x.fl && x.fl[0] === 'clovermont') : false; })()", sandbox);
  if (!flInKnot) throw new Error("fl not carried into knotAudiences");
  if (!vm.runInContext("ahay('clovermont_grievance_emergency', AUDIENCE.audiences['clovermont_grievance_emergency']).indexOf('clovermont') >= 0", sandbox)) {
    throw new Error("filler pack not in audience haystack");
  }
  const flSrc = vm.runInContext("fillerSource('clovermont_grievance_emergency', AUDIENCE.audiences['clovermont_grievance_emergency'])", sandbox);
  if (flSrc.indexOf("clovermont") < 0 || flSrc.indexOf("corruption tier 2") < 0 ||
      flSrc.indexOf("clovermont_first_grievance") < 0) {
    throw new Error("fillerSource render missing: " + flSrc);
  }
  vm.runInContext("openAudienceDetail('clovermont_grievance_emergency')", sandbox);
  vm.runInContext("openDetail('clovermont_grievance_bakery_problem')", sandbox);
  // channel 6: county-introduction audiences carry a ci link (county ink id +
  // name key), render a source note, index in the audience haystack and in the
  // knot drawer's audience rows, and surface in the stats
  const ciCount = vm.runInContext("AUDIENCE.stats.with_county_intro", sandbox);
  if (ciCount !== 7) throw new Error("with_county_intro != 7: " + ciCount);
  const ciEnberg = vm.runInContext("AUDIENCE.audiences['county_quest_enberg_1'].ci", sandbox);
  if (!ciEnberg || ciEnberg.length !== 2 || ciEnberg[0] !== "enberg" ||
      ciEnberg[1] !== "ENBERG_NAME") {
    throw new Error("county_quest_enberg_1 ci wrong: " + JSON.stringify(ciEnberg));
  }
  const ciSrc = vm.runInContext("countyIntroSource(AUDIENCE.audiences['county_quest_enberg_1'])", sandbox);
  if (ciSrc.indexOf("Enberg") < 0 || ciSrc.indexOf("neighboring county is rallied") < 0 ||
      ciSrc.indexOf("act 2 or 3") < 0) {
    throw new Error("countyIntroSource render missing: " + ciSrc);
  }
  if (!vm.runInContext("ahay('county_quest_enberg_1', AUDIENCE.audiences['county_quest_enberg_1']).indexOf('county introduction') >= 0", sandbox)) {
    throw new Error("county intro not in audience haystack");
  }
  const ciInKnot = vm.runInContext("(() => { const r = knotAudiences().get('county_quest_enberg_first_audience'); return r ? r.some(x => x.stem === 'county_quest_enberg_1' && x.ci && x.ci[0] === 'enberg') : false; })()", sandbox);
  if (!ciInKnot) throw new Error("ci not carried into knotAudiences");
  vm.runInContext("openAudienceDetail('county_quest_enberg_1')", sandbox);
  // channel 7: ultimatum follow-up audiences carry a um link (ultimatum id +
  // hard deadline cycle), render a source note, index in the audience haystack
  // and in the knot drawer rows, and surface in the stats
  const umCount = vm.runInContext("AUDIENCE.stats.with_ultimatum", sandbox);
  if (umCount !== 6) throw new Error("with_ultimatum != 6: " + umCount);
  const umKL = vm.runInContext("AUDIENCE.audiences['kingslayer_ultimatum_faillure'].um", sandbox);
  if (!umKL || umKL.length !== 2 || umKL[0] !== "kingslayer_ultimatum" ||
      umKL[1] !== 23) {
    throw new Error("kingslayer_ultimatum_faillure um wrong: " + JSON.stringify(umKL));
  }
  const umSrc = vm.runInContext("ultimatumSource(AUDIENCE.audiences['kingslayer_ultimatum_faillure'])", sandbox);
  if (umSrc.indexOf("kingslayer_ultimatum") < 0 || umSrc.indexOf("deadline cycle") < 0 ||
      umSrc.indexOf("23") < 0 || umSrc.indexOf("min_rallied_counties 3") < 0) {
    throw new Error("ultimatumSource render missing: " + umSrc);
  }
  if (!vm.runInContext("ahay('kingslayer_ultimatum_faillure', AUDIENCE.audiences['kingslayer_ultimatum_faillure']).indexOf('ultimatum') >= 0", sandbox)) {
    throw new Error("ultimatum not in audience haystack");
  }
  const umInKnot = vm.runInContext("(() => { const r = knotAudiences().get('ultimatum_kingslayer_failure'); return r ? r.some(x => x.stem === 'kingslayer_ultimatum_faillure' && x.um && x.um[0] === 'kingslayer_ultimatum') : false; })()", sandbox);
  if (!umInKnot) throw new Error("um not carried into knotAudiences");
  vm.runInContext("openAudienceDetail('kingslayer_ultimatum_faillure')", sandbox);
  // Task C (Conditions consolidation): every gating channel lands in the shared
  // audienceGates rows — the enberg intro now shows its rq gate AND county-intro
  // source, the ultimatum scene shows quest follow-ups + um context, a hardcoded
  // scene counts as gated even with no rq, and the "has gating conditions"
  // filter (ASTATE.cond) matches any of those channels (not just rq).
  const enbergCond = vm.runInContext("audienceConditionCount('county_quest_enberg_1', AUDIENCE.audiences['county_quest_enberg_1'])", sandbox);
  if (enbergCond < 2) throw new Error("enberg conditions too few: " + enbergCond);
  const enbergRows = vm.runInContext("audienceConditionRows('county_quest_enberg_1', AUDIENCE.audiences['county_quest_enberg_1']).join(' | ')", sandbox);
  if (enbergRows.indexOf("yohav_dead") < 0 || enbergRows.indexOf("County introduction") < 0) {
    throw new Error("enberg conditions missing gates: " + enbergRows);
  }
  const umRows = vm.runInContext("audienceConditionRows('kingslayer_ultimatum_faillure', AUDIENCE.audiences['kingslayer_ultimatum_faillure']).join(' | ')", sandbox);
  if (umRows.indexOf("quest_ultimatum_kingslayer_default") < 0 || umRows.indexOf("deadline cycle") < 0) {
    throw new Error("ultimatum conditions missing gates: " + umRows);
  }
  const cycCond = vm.runInContext("audienceConditionCount('scriptedquest_assassination_attempt', AUDIENCE.audiences['scriptedquest_assassination_attempt'])", sandbox);
  if (cycCond < 1) throw new Error("hardcoded cycle audience has no gating conditions: " + cycCond);
  const condMatch = vm.runInContext("ASTATE.cond = true; const r = visibleAudiences().some(([s]) => s === 'scriptedquest_assassination_attempt'); ASTATE.cond = false; r", sandbox);
  if (!condMatch) throw new Error("gating filter does not match a cyc-only audience");
  const condNoMatch = vm.runInContext("ASTATE.cond = true; const n = visibleAudiences().length; ASTATE.cond = false; n", sandbox);
  const allAud = vm.runInContext("Object.keys(AUDIENCE.audiences).length", sandbox);
  if (!(condNoMatch > 0) || !(condNoMatch < allAud)) {
    throw new Error("gating filter narrowed nothing or matched everything: " + condNoMatch + "/" + allAud);
  }
  // drawer rendering must not throw on a demission variant either
  vm.runInContext("openAudienceDetail('knight_leaving_arron_dragonheart')", sandbox);
  // the knot drawer's "Where it comes from" section is built from the AUDIENCE
  // dataset (knotAudiences/knotFuQuests) — open one that has both audiences and
  // follow-up quests to keep that re-pointing locked in.
  vm.runInContext("openDetail('county_quest_enberg_first_audience')", sandbox);

  // Task J: free-time dialogue sources (dialogues.json). Affinity dialogs carry
  // their knight + min-affinity gate, conversations their partners/order, and
  // reactions their unlock sources; the knot drawer renders all three and the
  // Dialogues-tab "has a free-time dialogue source" filter narrows.
  const dlg = vm.runInContext("DIALOGUE.stats", sandbox);
  if (dlg.affinity !== 82 || dlg.conversation !== 77 || dlg.reaction !== 76 ||
      dlg.all !== 235 || !(dlg.with_unl > 80)) {
    throw new Error("DIALOGUE stats wrong: " + JSON.stringify(dlg));
  }
  const aff2 = vm.runInContext("DIALOGUE.dialogues.angelica_affinity_2", sandbox);
  if (!aff2 || aff2.t !== "affinity" || !aff2.aff || aff2.aff.k !== "angelica" ||
      aff2.aff.rank !== 5 || aff2.loc !== 2) {
    throw new Error("angelica_affinity_2 gate wrong: " + JSON.stringify(aff2));
  }
  const conv = vm.runInContext("DIALOGUE.dialogues.conversation_brunhilda_gideon", sandbox);
  if (!conv || conv.t !== "conversation" || !conv.conv ||
      !conv.conv.knights.includes("gideon") || conv.conv.o == null || conv.loc !== 13) {
    throw new Error("conversation_brunhilda_gideon wrong: " + JSON.stringify(conv));
  }
  const lady = vm.runInContext("DIALOGUE.dialogues.lady_tower_act_2_reached_reaction", sandbox);
  if (!lady || lady.t !== "reaction" || !lady.unl ||
      !lady.unl.some(([t, v]) => t === "ink" && v === "arlin_introduction_to_act_2")) {
    throw new Error("lady_tower reaction unlock wrong: " + JSON.stringify(lady));
  }
  const marriage = vm.runInContext("DIALOGUE.dialogues.civil_wars_event_marriage_annoying_gwendan_reaction", sandbox);
  if (!marriage || !(marriage.unl || [])
      .some(([t, v]) => t === "ink" && v === "scriptedquest_civil_war_event_nobles_revolt")) {
    throw new Error("gwendan marriage alias unlock wrong: " + JSON.stringify(marriage));
  }
  const affHtml = vm.runInContext("dialogueSourceHtml('angelica_affinity_2')", sandbox);
  if (affHtml.indexOf("affinity dialogue") < 0 || affHtml.indexOf("requires affinity") < 0 ||
      affHtml.indexOf(">5</b>") < 0) {
    throw new Error("dialogueSourceHtml affinity gate missing: " + affHtml);
  }
  const convHtml = vm.runInContext("dialogueSourceHtml('conversation_brunhilda_gideon')", sandbox);
  if (convHtml.indexOf("Knight conversation") < 0 || convHtml.indexOf("plays once") < 0) {
    throw new Error("dialogueSourceHtml conversation missing: " + convHtml);
  }
  const reactHtml = vm.runInContext("dialogueSourceHtml('lady_tower_act_2_reached_reaction')", sandbox);
  if (reactHtml.indexOf("unlocked by") < 0 || reactHtml.indexOf("arlin_introduction_to_act_2") < 0) {
    throw new Error("dialogueSourceHtml unlock missing: " + reactHtml);
  }
  if (!vm.runInContext("hay(INDEX.knots.angelica_affinity_2).indexOf('affinity') >= 0", sandbox)) {
    throw new Error("dialogue source not in knot haystack");
  }
  const srcDl = vm.runInContext("state.src = 'dl'; (() => { const n = visibleKnots().length; state.src = ''; return n; })()", sandbox);
  const allKnots = vm.runInContext("Object.keys(INDEX.knots).length", sandbox);
  if (!(srcDl > 0) || !(srcDl < allKnots)) {
    throw new Error("dialogue-source filter wrong: " + srcDl + "/" + allKnots);
  }
  vm.runInContext("openDetail('angelica_affinity_2')", sandbox);

  // Task K: ending sources (endings.json). The six ending-type cutscenes, the
  // 31 per-character vignettes and the two code-played specials render as knot-
  // drawer "Where it comes from" rows and are indexed into the knot haystack.
  const endReady = vm.runInContext("ENDINGS && Object.keys(ENDINGS.types).length", sandbox);
  if (endReady !== 6 ||
      vm.runInContext("Object.keys(ENDINGS.vignettes).length", sandbox) !== 31 ||
      vm.runInContext("Object.keys(ENDINGS.specials).length", sandbox) !== 2) {
    throw new Error("ENDINGS catalog wrong");
  }
  const cutHtml = vm.runInContext("endingSourceHtml('tyranny_ending_cutscene')", sandbox);
  if (cutHtml.indexOf("Ending cutscene") < 0 || cutHtml.indexOf("WAR") < 0 ||
      cutHtml.indexOf("SWITCH_ENDING_WAR_PATH") < 0) {
    throw new Error("ending cutscene row missing: " + cutHtml);
  }
  const demHtml = vm.runInContext("endingSourceHtml('demon_state_ending')", sandbox);
  if (demHtml.indexOf("Ending cutscene") < 0 || demHtml.indexOf("corruption") < 0) {
    throw new Error("demon-state note missing: " + demHtml);
  }
  const vigHtml = vm.runInContext("endingSourceHtml('ursula_ending')", sandbox);
  if (vigHtml.indexOf("Ending vignette") < 0 || vigHtml.indexOf("Ursula") < 0 ||
      vigHtml.indexOf("roundtable") < 0) {
    throw new Error("ending vignette row missing: " + vigHtml);
  }
  const carinaHtml = vm.runInContext("endingSourceHtml('carina_ending')", sandbox);
  if (carinaHtml.indexOf("Carina") < 0) {
    throw new Error("servant vignette name missing: " + carinaHtml);
  }
  const hildegardHtml = vm.runInContext("endingSourceHtml('hildegard_singing_ending')", sandbox);
  if (hildegardHtml.indexOf("HILDEGARD_SONG") < 0) {
    throw new Error("hildegard special note missing: " + hildegardHtml);
  }
  if (!vm.runInContext("hay(INDEX.knots.ursula_ending).indexOf('ending vignette') >= 0", sandbox)) {
    throw new Error("ending source not in knot haystack");
  }
  vm.runInContext("openDetail('ursula_ending')", sandbox);

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
  // Audience-request unlocks join the chain: UnlockAudienceRequest releases the
  // request's follow-up audience as the next narrative step (bettie_request_victoria
  // from the enberg finale → mana_strala_audience_request_assassin; the victoria
  // call-back from scriptedquest_victoria_final_trials_completed → victoria_come_back_later).
  const reqUnlk = vm.runInContext("(() => Array.from(knotRequests().get('scriptedquest_victoria_events_introduction_wounded_man') || []))()", sandbox);
  if (!reqUnlk.includes("bettie_request_victoria")) throw new Error("knotRequests missed the bettie request: " + JSON.stringify(reqUnlk));
  const enbergFinal = vm.runInContext("knotChain('county_quest_enberg_audience_final')", sandbox);
  if (!enbergFinal.nextTips.includes("mana_strala_audience_request_assassin")) {
    throw new Error("request follow-up audience missing from chain: " + JSON.stringify(enbergFinal.nextTips));
  }
  const victoriaSpine = vm.runInContext("knotChain('scriptedquest_victoria_final_trials_completed')", sandbox);
  if (victoriaSpine.before[0] !== "scriptedquest_victoria_third_trial" ||
      victoriaSpine.after[0] !== "victoria_come_back_later") {
    throw new Error("victoria call-back chain wrong: " + JSON.stringify(victoriaSpine));
  }
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
  // Firing conditions / "how to proc" cross-links:
  // 1. special-instruction reverse links — the knot that a special unlocks
  //    must surface the trigger (GIDEON_VICTORIA_DEAD -> gideon_victoria_dead_reaction).
  const spTrig = vm.runInContext("knotSpecialTriggers().get('gideon_victoria_dead_reaction') || []", sandbox);
  if (!spTrig.includes("GIDEON_VICTORIA_DEAD")) {
    throw new Error("knot special-trigger reverse link missing: " + JSON.stringify(spTrig));
  }
  // 2. cycle scheduling — scripted audiences hardcoded into a cycle resource
  //    (scriptedquest_assassination_attempt is placed in cycle 7) and the
  //    reverse "modifier unexpected outcome follow-up" quest→audience link
  //    (contract_cleankeeper_goose_part_two's modifier -> chester_candidacy).
  const cyc = vm.runInContext("AUDIENCE.audiences.scriptedquest_assassination_attempt.cyc", sandbox);
  if (!cyc || !cyc.includes(7)) {
    throw new Error("cycle scheduling missing for scriptedquest_assassination_attempt: " + JSON.stringify(cyc));
  }
  const chesterFu = vm.runInContext("AUDIENCE.rev.qf.chester_candidacy || []", sandbox);
  if (!chesterFu.some((f) => f.q === "contract_cleankeeper_goose_part_two" && f.k === "unexpected")) {
    throw new Error("modifier unexpected follow-up missing for chester_candidacy: " + JSON.stringify(chesterFu));
  }
  // 3. the knot→audience reverse map must carry the hardcoded cycle, so the
  //    knot drawer explains WHEN the scripted scene plays (scriptedquest_chester -> cycle 2).
  const knotCyc = vm.runInContext("(() => { const row = knotAudiences().get('scriptedquest_chester'); return row && row[0] ? row[0].cyc : null; })()", sandbox);
  if (!knotCyc || !knotCyc.includes(2)) {
    throw new Error("knot drawer audience row missing the hardcoded cycle: " + JSON.stringify(knotCyc));
  }
  // 4. special instructions that schedule an audience must (a) appear in the
  //    audience drawer's reverse map and (b) mark the scheduled audience's knot
  //    as "fires when this special is triggered" (GWENDAN_REFORMED ->
  //    gwendan_humble_candidacy -> candidature_gwendan_the_humble).
  const audSp = vm.runInContext("audSpecials().get('gwendan_humble_candidacy') || []", sandbox);
  if (!audSp.includes("GWENDAN_REFORMED")) {
    throw new Error("audience->special reverse link missing: " + JSON.stringify(audSp));
  }
  const gwendanKnotSp = vm.runInContext("knotSpecialTriggers().get('candidature_gwendan_the_humble') || []", sandbox);
  if (!gwendanKnotSp.includes("GWENDAN_REFORMED")) {
    throw new Error("scheduled-audience knot missing the special trigger: " + JSON.stringify(gwendanKnotSp));
  }
  // 5. conditional special instructions expose their firing conditions
  //    (SOUTHBAY_TARCUS_INTERVENTION only fires while Tarcus is present).
  const cond = vm.runInContext("SPECIAL.instructions.SOUTHBAY_TARCUS_INTERVENTION.cond || []", sandbox);
  if (!cond.length || typeof cond[0] !== "string") {
    throw new Error("special firing conditions missing: " + JSON.stringify(cond));
  }
  const assCond = vm.runInContext("SPECIAL.instructions.ASSASINATION_PLOT_URSULA_FOLLOW_UP.cond || []", sandbox);
  if (!assCond.length || !/Ursule/.test(assCond[0])) {
    throw new Error("multiline special firing condition missing: " + JSON.stringify(assCond));
  }
  console.log(`frontend smoke OK (quests=${q} inv=${inv} knights=${kn} special=${sp} audiences=${aud.audiences} requests=${aud.requests} srcAud=${srcAud} srcFu=${srcFu} kf=${byAudF} kc=${byAudC})`);
}).catch((err) => {
  console.error(err.stack || String(err));
  process.exit(1);
});

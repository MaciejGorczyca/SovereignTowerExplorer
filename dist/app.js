"use strict";

const $ = (id) => document.getElementById(id);

let INDEX = null;           // en metadata + tokens
let LOC = {};               // active locale token overrides (merged)

// technical-layer display toggles (persisted in localStorage)
const SHOW_KEY = "st_tower_ink_show";
const SHOW_DEFAULTS = {
  diverts: true, stitches: true, markers: true, conds: true,
  fPres: true, fSound: true, fSet: true, fReq: true, fState: true,
  fBbc: false,
};
const SHOW_ITEMS = [
  ["diverts", "diverts", "Inline → divert lines: where the flow jumps next (outside choices)"],
  ["stitches", "stitch headers", "Branch / checkpoint section headers (## name)"],
  ["markers", "markers", "(BREAK_n) timed pauses and (NO_CLICK) no-click-to-advance cues"],
  ["conds", "branch conditions", "Conditional branch gates: {var} checks that pick which dialogue variant plays"],
];
const FN_ITEMS = [
  ["fPres", "presentation", "Visual stage direction: SwapExpression, Apparition, Disparition, FlashScreen, animations, LUTs"],
  ["fSound", "sound", "Audio cues: InstructionSound"],
  ["fSet", "var writes", "State assignments: set VAR / set temp / set list"],
  ["fReq", "requirements", "Choice-gating conditions: RequiresTag, RequiresFunds, HintSat, …"],
  ["fState", "game state", "Game-side consequences: UpdateFunds, UnlockQuest, ChangeTaxes, UpdateKnightAffinity, …"],
];
const BBC_ITEMS = [
  ["fBbc", "text effects", "Inline Godot BBCode effects ([b], [i], [shake …], [font_size=N], [wave …]) — hidden by default; the words between tags are kept"],
];
// function-name -> category classification for the {"3", fn, args} tokens
const FN_CATS = {
  pres: new Set(["SwapExpression", "Apparition", "Disparition", "FastDisparition",
    "ApparitionRightCorner", "FlashScreen", "IntenseFlashScreen", "BlackScreenRequested",
    "WhiteScreenRequested", "EllipseAnimationRequested", "UltimatumAnimationRequested",
    "TriggerCustomAnimation", "RevealLUT", "HideLUT", "NextIllustration"]),
  sound: new Set(["InstructionSound"]),
  req: new Set(["HintSat", "RequiresTag", "RequiresFunds", "RequiresMinRomantism",
    "RequiresMinSatisfaction", "RequiresItem", "RequiresKnight", "RequiresTagRanked",
    "RequiresServant", "IsSovereignCentrist"]),
};
function fnCat(name) {
  if (name.startsWith("set:")) return "fSet";
  if (FN_CATS.pres.has(name)) return "fPres";
  if (FN_CATS.sound.has(name)) return "fSound";
  if (FN_CATS.req.has(name)) return "fReq";
  return "fState";
}
function loadShowPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(SHOW_KEY));
    if (p && typeof p === "object" && !Array.isArray(p)) return Object.assign({}, SHOW_DEFAULTS, p);
  } catch (err) {}
  return Object.assign({}, SHOW_DEFAULTS);
}
function saveShowPrefs() {
  try { localStorage.setItem(SHOW_KEY, JSON.stringify(state.show)); } catch (err) {}
}

// "hide game-API (function) knots" filter toggle (persisted in localStorage)
const HIDEFN_KEY = "st_tower_ink_hidefn";
function loadHideFn() {
  try {
    const v = localStorage.getItem(HIDEFN_KEY);
    return v == null ? true : v === "1";
  } catch (err) { return true; }
}
function saveHideFn() {
  try { localStorage.setItem(HIDEFN_KEY, state.hideFn ? "1" : "0"); } catch (err) {}
}

// collapsible drawer-section state (persisted in localStorage)
const CSEC_KEY = "st_tower_csec";
function loadCollapsedSecs() {
  try {
    const arr = JSON.parse(localStorage.getItem(CSEC_KEY));
    if (Array.isArray(arr)) return new Set(arr.filter((x) => typeof x === "string"));
  } catch (err) {}
  return new Set();
}
const collapsedSecs = loadCollapsedSecs();
function saveCollapsedSecs() {
  try { localStorage.setItem(CSEC_KEY, JSON.stringify([...collapsedSecs])); } catch (err) {}
}
// stable per-section key: title with trailing "(<digits> …)" counts stripped,
// so "Appears in dialogue (5 knots)" and "Modifiers (variants 3)" are stable.
function secKey(title) {
  return String(title || "").trim().toLowerCase().replace(/\s*\(\s*\d+[^)]*\)\s*$/, "").trim();
}
// section headers: 0 = top level (h4.qsec, div.sec), 1 = sub (h4.qsec.small)
function secLevel(node) {
  if (node.nodeType !== 1) return -1;
  if (node.classList.contains("qsec")) return node.classList.contains("small") ? 1 : 0;
  if (node.classList.contains("sec")) return 0;
  return -1;
}
// nodes that must never be absorbed into a section body (knot drawer: the
// technical-layer bar and the dialogue itself stay always visible)
function isSecBoundary(node) {
  return node.nodeType === 1 && (node.classList.contains("techbar") || node.classList.contains("dial"));
}
// split a list of sibling nodes into sections: each header of `level` starts a
// section whose body is the following siblings up to the next header; boundary
// nodes and anything before the first header stay as bare items.
function groupSections(children, level) {
  const out = [];
  let cur = null;
  for (const node of children) {
    if (secLevel(node) === level) {
      if (cur) out.push(cur);
      cur = { h: node, body: [] };
    } else if (isSecBoundary(node)) {
      if (cur) out.push(cur);
      cur = null;
      out.push({ bare: node });
    } else if (cur) {
      cur.body.push(node);
    } else {
      out.push({ bare: node });
    }
  }
  if (cur) out.push(cur);
  return out;
}
function buildSectionWrap(header, body) {
  const key = secKey(header.textContent);
  const wrap = document.createElement("div");
  wrap.className = "secwrap";
  header.classList.add("csec-h");
  if (collapsedSecs.has(key)) wrap.classList.add("collapsed");
  header.addEventListener("click", () => {
    const collapsed = wrap.classList.toggle("collapsed");
    if (collapsed) collapsedSecs.add(key); else collapsedSecs.delete(key);
    saveCollapsedSecs();
  });
  wrap.appendChild(header);
  const bodyEl = document.createElement("div");
  bodyEl.className = "secbody";
  for (const n of body) bodyEl.appendChild(n);
  wrap.appendChild(bodyEl);
  return wrap;
}
// turn a freshly-built drawer panel's flat headers into collapsible segments.
function enhanceSections(panel) {
  const top = groupSections(Array.from(panel.children), 0);
  panel.innerHTML = "";
  for (const item of top) {
    if (item.bare) { panel.appendChild(item.bare); continue; }
    const sub = groupSections(item.body, 1);
    const body = [];
    for (const s of sub) {
      if (s.bare) body.push(s.bare);
      else body.push(buildSectionWrap(s.h, s.body));
    }
    panel.appendChild(buildSectionWrap(item.h, body));
  }
}

let state = {
  q: "", spk: "", cat: "", varName: "", varUse: "either",
  fn: "", fnArg: "", fnOp: "=", fnVal: "", hasCh: false, hideFn: loadHideFn(), locale: "en",
  src: "",
  kf: "", kc: "", kq: "", ksp: "",
  show: loadShowPrefs(),
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}
const BBC_TAGS = /\[\/?(?:b|i|center|color|fade|font|font_size|pulse|rainbow|shake|wave|Wave)[^\]]*\]/g;
function stripBbc(s) {
  return String(s).replace(BBC_TAGS, "");
}
function haystack(k) {
  const t = tokensOf(k);
  let text = k.prev;
  for (const tok of t) {
    if (tok[0] === "0") text += (text ? " " : "") + tok[1];
    else if (tok[0] === "2") text += " " + tok[1];
  }
  const aud = (knotAudiences().get(k.name) || []).map((a) => [a.f, ...a.c].join(" ")).join(" ");
  const fuq = (knotFuQuests().get(k.name) || []).map((f) => f.qid).join(" ");
  const sp = (knotSpecials().get(k.name) || []).join(" ");
  return (k.name + " " + k.c + " " + text + " " + k.reads.join(" ") + " " + k.writes.join(" ") + " " + k.funcs.join(" ") + " " + aud + " " + fuq + " " + sp)
    .toLowerCase();
}
const _hcache = new Map();
function hay(k) {
  let h = _hcache.get(k);
  if (h === undefined) { h = haystack(k); _hcache.set(k, h); }
  return h;
}
// relaxed search over a (lowercased) haystack string.
// "&" or "|" splits the query into OR-alternatives; within each alternative
// every whitespace-separated word must appear somewhere in the haystack
// (order/adjacency irrelevant; substring/prefix matching kept).
// e.g. "bucolic diplomacy & demon hunt" matches entries holding all words of
// either phrase — handy for comparing a few entries side by side.
function matchesQuery(hay, q) {
  if (!q) return true;
  const alts = q.toLowerCase().trim().split(/[&|]/).map((s) => s.trim()).filter(Boolean);
  if (!alts.length) return false;
  return alts.some((alt) => alt.split(/\s+/).every((w) => hay.includes(w)));
}

function tokensOf(k) {
  if (k._tokens) return k._tokens;
  const loc = LOC[k.name];
  k._tokens = loc || (INDEX.knots[k.name] ? INDEX.knots[k.name].lines : []);
  return k._tokens;
}

// drive a search <input> with a datalist bound to fake options
function fillSelect(sel, entries, emptyLabel, emptyVal) {
  sel.innerHTML = "";
  const no = document.createElement("option");
  no.value = emptyVal; no.textContent = emptyLabel; sel.appendChild(no);
  for (const [label, value] of entries) {
    const o = document.createElement("option");
    o.value = value; o.textContent = label; sel.appendChild(o);
  }
}

// ---------------------------------------------------------------------------
// function-call arguments: fn -> arg0 -> Set(value) built from knot lines.
// Used to suggest "which tag" + "which value" for the function filter.
// ---------------------------------------------------------------------------
const FN_DATA = new Map(); // fn -> Map(arg0 -> Set(value-string))

function fnNumericArg(args) {
  for (const a of args) {
    const s = String(a);
    if (s !== "" && !isNaN(+s)) return +s;
  }
  return null;
}

function buildFnArgData() {
  FN_DATA.clear();
  for (const k of Object.values(INDEX.knots)) {
    for (const t of k.lines) {
      if (t[0] !== "3" || String(t[1]).startsWith("set:")) continue;
      const args = t[2] || [];
      if (!args.length) continue;
      const a0 = String(args[0]);
      const val = fnNumericArg(args);
      let m = FN_DATA.get(t[1]);
      if (!m) { m = new Map(); FN_DATA.set(t[1], m); }
      if (!m.has(a0)) m.set(a0, new Set());
      if (val !== null) m.get(a0).add(String(val));
    }
  }
}

function fillFnArgList() {
  const dl = $("fnarglist");
  dl.innerHTML = "";
  const m = FN_DATA.get(state.fn);
  if (!m) return;
  const vals = [...m.entries()].sort((a, b) => String(b[0]).localeCompare(String(a[0])));
  for (const [a0, vset] of vals) {
    const o = document.createElement("option");
    o.value = a0;
    o.label = `${a0}  (${vset.size} value${vset.size === 1 ? "" : "s"})`;
    dl.appendChild(o);
  }
}

function fillFnValList() {
  const dl = $("fnvallist");
  dl.innerHTML = "";
  const m = FN_DATA.get(state.fn);
  if (!m || !state.fnArg) return;
  const vset = m.get(state.fnArg);
  if (!vset) return;
  const vals = [...vset].sort((a, b) => +a - +b);
  for (const v of vals) {
    const o = document.createElement("option");
    o.value = v;
    o.label = `${state.fn}(${state.fnArg}, ${v})`;
    dl.appendChild(o);
  }
}

function callMatches(k, fn, argSel, op, valSel) {
  const wantVal = valSel !== "" && valSel != null;
  for (const t of tokensOf(k)) {
    if (t[0] !== "3") continue;
    if (t[1] !== fn) continue;
    const args = t[2] || [];
    if (argSel && args[0] !== argSel) continue;
    if (!wantVal) return true;
    const v = fnNumericArg(args);
    if (v === null) {
      if (op === "=" && args.includes(valSel)) return true;
      continue;
    }
    const rv = +valSel;
    if (isNaN(rv)) continue;
    const ok = op === "<" ? v < rv : op === "<=" ? v <= rv :
               op === "=" ? v === rv : op === ">=" ? v >= rv :
               op === ">" ? v > rv : v !== rv;
    if (ok) return true;
  }
  return false;
}

function buildFilterUI() {
  // speakers: by total occurrence count
  const spkEntries = Object.entries(INDEX.speakers)
    .sort((a, b) => b[1] - a[1])
    .map(([n, c]) => [`${n}  (${c})`, n]);
  fillSelect($("spk"), spkEntries, "Any speaker", "");
  // categories with counts
  const catEntries = Object.entries(INDEX.categories)
    .sort((a, b) => b[1] - a[1])
    .map(([c, n]) => [`${c}  (${n})`, c]);
  fillSelect($("cat"), catEntries, "Any category", "");
  // variable datalist (reads+writes counts)
  $("varlist").innerHTML = "";
  for (const [v, info] of Object.entries(INDEX.variables)) {
    const o = document.createElement("option");
    o.value = v;
    o.label = `${v}  (r:${info.reads} w:${info.writes})`;
    $("varlist").appendChild(o);
  }
  // function/requirement datalist (knot counts)
  $("fnlist").innerHTML = "";
  for (const [f, n] of Object.entries(INDEX.funcs).sort((a, b) => b[1] - a[1])) {
    const o = document.createElement("option");
    o.value = f;
    o.label = `${f}  (${n})`;
    $("fnlist").appendChild(o);
  }
  buildFnArgData();
}

// populate the Dialogues-tab cross-link selects (audience type/NPC, fired-after
// quest, emitted special). Needs QUEST/AUDIENCE/SPECIAL loaded, so it runs after
// init()'s data passes (and on locale switch, since NPC labels localize).
function buildLinkFilterUI() {
  const folders = new Map();
  const chars = new Map();
  const fuQuests = new Map();
  for (const [kn, auds] of knotAudiences()) {
    for (const a of auds) {
      folders.set(a.f, (folders.get(a.f) || 0) + 1);
      for (const c of a.c || []) chars.set(c, (chars.get(c) || 0) + 1);
    }
  }
  for (const [kn, fu] of knotFuQuests()) {
    for (const f of fu) fuQuests.set(f.qid, (fuQuests.get(f.qid) || 0) + 1);
  }
  const fill = (id, entries, emptyLabel) => {
    const sel = $(id);
    const keep = sel.value;
    sel.innerHTML = "";
    const no = document.createElement("option");
    no.value = ""; no.textContent = emptyLabel; sel.appendChild(no);
    for (const [v, c, lab] of entries) {
      const o = document.createElement("option");
      o.value = v; o.textContent = lab != null ? lab : `${v}  (${c})`; sel.appendChild(o);
    }
    sel.value = keep;
  };
  fill("kf", [...folders].sort((a, b) => a[0].localeCompare(b[0])), "Any audience type");
  fill("kc", [...chars]
    .map(([ck, c]) => [ck, c, `${tkey(ck) || ck}  (${c})`])
    .sort((a, b) => a[2].localeCompare(b[2])), "Any audience NPC");
  fill("kq", [...fuQuests]
    .map(([qid, c]) => [qid, c, `${QUEST && QUEST.quests[qid] ? (tkey(QUEST.quests[qid].n) || qid) : qid}  (${c})`])
    .sort((a, b) => a[2].localeCompare(b[2])), "Any quest");
  fill("ksp", Object.entries(SPECIAL.instructions)
    .filter(([, i]) => (i.knots || []).length)
    .map(([n, i]) => [n, (i.knots || []).length])
    .sort((a, b) => a[0].localeCompare(b[0])), "Any special");
}

function visibleKnots() {
  const out = [];
  for (const name of Object.keys(INDEX.knots)) {
    const k = INDEX.knots[name];
    k.name = name;
    if (state.hideFn && k.fn) continue;
    if (state.hasCh && !k.choices) continue;
    if (state.spk && !(k.sp && k.sp[state.spk])) continue;
    if (state.cat && k.c !== state.cat) continue;
    if (state.varName) {
      const r = k.reads.includes(state.varName);
      const w = k.writes.includes(state.varName);
      if (state.varUse === "reads" && !r) continue;
      if (state.varUse === "writes" && !w) continue;
      if (state.varUse === "either" && !r && !w) continue;
    }
    if (state.fn) {
      let hasFn = k.funcs.includes(state.fn);
      if (state.fnArg || state.fnVal) {
        hasFn = callMatches(k, state.fn, state.fnArg,
                            state.fnOp || "=", state.fnVal);
      }
      if (!hasFn) continue;
    }
    if (state.src === "aud" && !knotAudiences().has(name)) continue;
    if (state.src === "fu" && !knotFuQuests().has(name)) continue;
    if (state.src === "in" && !(knotIncoming().has(name) && knotIncoming().get(name).length)) continue;
    if (state.src === "uq" && !knotUnlocks().has(name)) continue;
    if (state.src === "sp" && !knotSpecials().has(name)) continue;
    if (state.src === "it" && !knotItems().has(name)) continue;
    if (state.src === "kn" && !knotKnights().has(name)) continue;
    if (state.kf) {
      const auds = knotAudiences().get(name) || [];
      if (!auds.some((a) => a.f === state.kf)) continue;
    }
    if (state.kc) {
      const auds = knotAudiences().get(name) || [];
      if (!auds.some((a) => (a.c || []).includes(state.kc))) continue;
    }
    if (state.kq) {
      const fu = knotFuQuests().get(name) || [];
      if (!fu.some((f) => f.qid === state.kq)) continue;
    }
    if (state.ksp && !(knotSpecials().get(name) || []).includes(state.ksp)) continue;
    if (state.q && !matchesQuery(hay(k), state.q)) continue;
    out.push(k);
  }
  return out;
}

function renderResults() {
  const list = visibleKnots();
  $("countline").innerHTML =
    `<b>${list.length}</b> of ${Object.keys(INDEX.knots).length} knots`;
  const cards = $("cards");
  cards.innerHTML = "";

  if (!list.length) {
    cards.innerHTML = `<div class="empty">No knots match — adjust filters above.</div>`;
    return;
  }
  const byCat = {};
  for (const k of list) (byCat[k.c] = byCat[k.c] || []).push(k);

  const catOrder = Object.keys(byCat).sort((a, b) => byCat[b].length - byCat[a].length);
  for (const c of catOrder) {
    byCat[c].sort((a, b) => a.name.localeCompare(b.name));
    const grp = document.createElement("section");
    grp.className = "group";
    grp.innerHTML = `<h3>${esc(c)} <span class="cnt">${byCat[c].length}</span></h3>`;
    const grid = document.createElement("div");
    grid.className = "grid";
    for (const k of byCat[c]) grid.appendChild(card(k));
    grp.appendChild(grid);
    cards.appendChild(grp);
  }
}

function card(k) {
  const el = document.createElement("div");
  el.className = "card";
  el.tabIndex = 0;
  const badges = [];
  const spk = k.sp ? Object.keys(k.sp) : [];
  for (const s of spk.slice(0, 3)) badges.push(`<span class="badge speaker">${esc(s)}</span>`);
  if (k.choices) badges.push(`<span class="badge choice">${k.choices} choice${k.choices > 1 ? "s" : ""}</span>`);
  if (k.reads.length + k.writes.length) badges.push(`<span class="badge var">${k.writes.length ? k.writes.length + " ✎" : ""}${k.reads.length && k.writes.length ? " / " : ""}${k.reads.length ? k.reads.length + " ➚" : ""} vars</span>`);
  const fuq = (QUEST ? knotFuQuests() : new Map()).get(k.name);
  if (fuq && fuq.length) {
    const qid = fuq[0].qid;
    const nm = QUEST.quests[qid] ? (tkey(QUEST.quests[qid].n) || qid) : qid;
    badges.push(`<span class="badge quest" title="fires after ${esc(qid)} (${fuq.map((f) => f.kind).join(", ")})">↳ ${esc(nm)}</span>`);
  }
  const auds = knotAudiences().get(k.name);
  if (auds && auds.length) {
    const folders = [...new Set(auds.map((a) => a.f))].join(", ");
    badges.push(`<span class="badge aud" title="played as audience (${esc(folders)})">audience ×${auds.length}</span>`);
  }
  const uq = knotUnlocks().get(k.name);
  if (uq && uq.length) {
    badges.push(`<span class="badge sp-quest" title="unlocks ${esc(uq.join(", "))}">unlocks ${uq.length}</span>`);
  }
  const sp = knotSpecials().get(k.name);
  if (sp && sp.length) {
    badges.push(`<span class="badge sp-ink" title="emits ${esc(sp.join(", "))}">special ×${sp.length}</span>`);
  }
  const kn = knotKnights().get(k.name);
  if (kn && kn.length) {
    badges.push(`<span class="badge req" title="appears in dialogue for ${esc(kn.join(", "))}">knight ×${kn.length}</span>`);
  }

  let prev = esc(state.show.fBbc ? k.prev : stripBbc(k.prev)).replace(/\n/g, " ");
  if (state.q) {
    const low = prev.toLowerCase();
    const q = state.q.toLowerCase();
    let i = low.indexOf(q);
    if (i >= 0) prev = prev.slice(0, i) + "<mark>" + prev.slice(i, i + state.q.length) + "</mark>" + prev.slice(i + state.q.length);
  }

  el.innerHTML = `
    <div class="top">
      <span class="name">${esc(k.name)}</span>
      ${k.fn ? `<span class="fnbadge">fn</span>` : ""}
    </div>
    <div class="prev">${prev || `<i style="opacity:.5">(no dialogue text)</i>`}</div>
    <div class="meta">${badges.join("")}</div>`;
  const open = () => go("knot", k.name);
  el.addEventListener("click", open);
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return el;
}

// ---------------------------------------------------------------------------
// token rendering
// ---------------------------------------------------------------------------
const SPEAKER_COLORS = ["#e8b85a", "#6ea8d8", "#7fc98a", "#d97b6c", "#b691d8", "#5fd0c9"];
function speakerColor(name) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return SPEAKER_COLORS[h % SPEAKER_COLORS.length];
}

function renderDialogue(k, root) {
  const toks = tokensOf(k);
  const stack = [root];                       // open if-blocks (bottom: root)
  let lastLine = null;                        // current .line for "c" continuations
  const mount = (el) => (stack[stack.length - 1].appendChild(el), el);
  const renderToks = (list) => {
    for (const t of list) {
      switch (t[0]) {
        case "0": {
          const sp = t[2] || "";
          if (t[3] === "c" && lastLine) {
            const txt = document.createElement("span");
            txt.className = "txt";
            txt.textContent = state.show.fBbc ? (t[1] || " ") : (stripBbc(t[1]) || " ");
            lastLine.appendChild(txt);
            break;
          }
          const div = document.createElement("div");
          div.className = "line";
          if (sp) {
            const who = document.createElement("span");
            who.className = "who";
            who.style.color = speakerColor(sp);
            who.textContent = sp;
            div.appendChild(who);
          }
          const txt = document.createElement("span");
          txt.className = "txt";
          txt.textContent = state.show.fBbc ? (t[1] || " ") : (stripBbc(t[1]) || " ");
          div.appendChild(txt);
          mount(div);
          lastLine = div;
          break;
        }
        case "1": {
          if (!state.show.markers) break;
          const m = document.createElement("span");
          m.className = "marker";
          m.textContent = t[1];
          m.title = t[1] === "NO_CLICK" ? "no click-to-advance" : "timed pause";
          if (t[2] === "i" && lastLine) lastLine.appendChild(m);
          else { mount(m); lastLine = null; }
          break;
        }
        case "2": {
          const choice = document.createElement("div");
          choice.className = "choice";
          const flg = t[3];
          if (flg != null) {
            const flb = document.createElement("span");
            flb.className = "flg" + (flg & 8 ? " auto" : "");
            flb.textContent = "#" + flg;
            const bits = [];
            if (flg & 1) bits.push("conditional");
            if (flg & 2) bits.push("start-content");
            if (flg & 4) bits.push("choice-content");
            if (flg & 8) bits.push("invisible-default (auto-chosen)");
            if (flg & 16) bits.push("once-only");
            flb.title = "choice flags: " + (bits.join(", ") || "none");
            if (flg & 8) flb.textContent = "#auto";
            choice.appendChild(flb);
          }
          const label = document.createElement("span");
          label.className = "clabel";
          label.textContent = t[1] || "(…continue)";
          choice.appendChild(label);
          if (t[4]) {
            const dst = document.createElement(t[4].startsWith("(") ? "span" : "a");
            dst.className = "dst";
            if (t[4] === "(end)") {
              dst.textContent = "→ dialogue ends";
              dst.title = "this choice ends the dialogue";
              dst.classList.add("meta");
            } else if (t[4] === "(options)") {
              dst.textContent = "→ more options";
              dst.title = "this choice returns to the option list";
              dst.classList.add("meta");
            } else {
              dst.textContent = "→ " + t[4] + (t[6] && t[6].length ? "(" + t[6].join(", ") + ")" : "");
              dst.title = "advances to stitch/knot " + t[4];
              if (INDEX.knots[t[4]]) {
                dst.addEventListener("click", (e) => { e.stopPropagation(); go("knot", t[4]); });
              }
            }
            choice.appendChild(dst);
          }
          if (t[2] && t[2].length) {
            const reqs = document.createElement("div");
            reqs.className = "reqs";
            for (const r of t[2]) {
              const chip = document.createElement("span");
              chip.className = "chip" + (r.startsWith("!") ? " neg" : "");
              chip.textContent = "▣ " + r;
              chip.title = "choice requirement / condition";
              reqs.appendChild(chip);
            }
            choice.appendChild(reqs);
          }
          if (t[5] && t[5].length) {
            const eff = document.createElement("div");
            eff.className = "effs";
            for (const e of t[5]) {
              const chip = document.createElement("span");
              if (e[0].startsWith("set:")) {
                const target = e[1] && e[1][0] !== undefined ? e[1][0] : "";
                const rhs = e[1] && e[1].length > 1 ? e[1][1] : "";
                chip.textContent = "✎ " + e[0].slice(4).replace(/=$/, "") + " " + target + (rhs ? " = " + rhs : "");
              } else {
                chip.innerHTML = "➔ " + esc(e[0]) + ((e[1] || []).length ? "(" + (e[1] || []).map(linkArg).join(", ") + ")" : "");
              }
              chip.title = "effect triggered by this choice";
              eff.appendChild(chip);
            }
            choice.appendChild(eff);
          }
          mount(choice); lastLine = null;
          if (t[7] && t[7].length) {
            // this choice's own follow-up stream (narrative/consequences that play
            // only when this option is chosen) — render it nested under the card
            const flow = document.createElement("div");
            flow.className = "choice-flow";
            const base = stack.length;
            stack.push(flow);
            const savedLast = lastLine;
            lastLine = null;
            renderToks(t[7]);
            stack.length = base;            // drop any if-blocks opened inside here
            lastLine = savedLast;
            if (flow.childNodes.length) choice.appendChild(flow);
          }
          break;
        }
        case "3": {
          if (!state.show[fnCat(t[1])]) break;
          const fn = document.createElement("div");
          fn.className = "fn";
          const name = t[1], args = (t[2] || []);
          if (name.startsWith("set:")) {
            const target = args[0] === undefined ? "" : args[0];
            const rhs = args.length > 1 ? args[1] : "";
            fn.innerHTML = `<span class="set">set ${esc(name.slice(4).replace(/=$/, ""))} ${esc(target)}${rhs ? " = " + esc(rhs) : ""}</span>`;
          } else {
            fn.innerHTML = "⚙ " + esc(name) + "(" + args.map(linkArg).join(", ") + ")";
            fn.title = "game / ink function call";
          }
          mount(fn); lastLine = null;
          break;
        }
        case "4": {
          if (!state.show.diverts) break;
          const d = document.createElement("div");
          d.className = "divert";
          const segs = String(t[1]).split(".").map((s) => s.replace(/\^/g, "")).filter((s) => s);
          const tail = segs.length ? segs[segs.length - 1] : t[1];
          d.textContent = "→ " + tail + (t[2] && t[2].length ? "(" + t[2].join(", ") + ")" : "");
          if (INDEX.knots[tail]) {
            d.title = "advances to knot " + tail;
            d.addEventListener("click", () => go("knot", tail));
          } else if (tail === "(end)") {
            d.title = "this branch ends the dialogue";
          } else if (tail === "(options)") {
            d.title = "this branch loops back to the options";
          } else {
            d.title = "advances to stitch " + tail + "  (" + t[1] + ")";
          }
          mount(d); lastLine = null;
          break;
        }
        case "5": {
          if (!state.show.stitches) break;
          const s = document.createElement("h4");
          s.className = "stitch";
          const params = t[2] && t[2].length ? "(" + t[2].join(", ") + ")" : "";
          s.textContent = t[1] + params;
          mount(s); lastLine = null;
          break;
        }
        case "7": {
          const vars = t[1] || [];
          const exprStr = t[2] || "";
          const blockOpen = t[3] === "1";
          const chost = document.createElement("div");
          chost.className = "cond";
          if (exprStr) {
            const chip = document.createElement("span");
            chip.className = "chip";
            chip.textContent = "if " + exprStr;
            chip.title = "branch condition expression";
            chost.appendChild(chip);
          } else {
            for (const v of vars) {
              const neg = v.startsWith("!");
              const chip = document.createElement("span");
              chip.className = "chip" + (neg ? " neg" : "");
              chip.textContent = (neg ? "unless " : "if ") + v.replace(/^!/, "");
              chip.title = "branch condition variable";
              chost.appendChild(chip);
            }
          }
          chost.title = "branch condition: dialogue variant gated on this variable";
          if (blockOpen) {
            const block = document.createElement("div");
            block.className = "ifblock";
            if (state.show.conds) block.appendChild(chost);
            mount(block);
            stack.push(block);
          } else if (state.show.conds) {
            mount(chost);
          }
          lastLine = null;
          break;
        }
        case "8": {
          if (stack.length > 1) {
            const block = stack.pop();
            if (state.show.conds) {
              const end = document.createElement("div");
              end.className = "cond endif";
              const chip = document.createElement("span");
              chip.className = "chip";
              chip.textContent = "end if";
              chip.title = "conditional branch block ends here";
              end.appendChild(chip);
              block.appendChild(end);
            }
          }
          lastLine = null;
          break;
        }
      }
    }
  };
  renderToks(toks);
}

// Reverse index: variable -> every ink knot that reads it (built once).
let _varRdr = null;
function varReaders() {
  if (_varRdr) return _varRdr;
  _varRdr = new Map();
  if (INDEX) for (const [name, kd] of Object.entries(INDEX.knots)) {
    for (const v of kd.reads || []) {
      if (!_varRdr.has(v)) _varRdr.set(v, []);
      _varRdr.get(v).push(name);
    }
  }
  return _varRdr;
}

// Game-side state mutations the "what happens" box decodes beyond the
// dedicated special/quest/item/affinity rows. `v` is the argument holding the
// *written variable* (sovereign stat, population, tag flag) — when set, the
// row shows the ink knots that read that variable later (the ripple effect).
const STATE_FNS = {
  UpdateSovereignValue:      { icon: "⚖", v: 0,  label: "Sovereign stat" },
  UpdateSatisfaction:        { icon: "☺", v: 0,  label: "Satisfaction" },
  UpdateServantRomance:      { icon: "♡", v: -1, label: "Servant romance" },
  UpdateFunds:               { icon: "¤", v: -1, label: "Sovereign funds" },
  UnlockTag:                 { icon: "🏷", v: 1,  label: "Unlocks tag" },
  UnlockAudienceRequest:     { icon: "📣", v: -1, label: "Unlocks audience request" },
  UnlockFillerAudiencesPack: { icon: "🗂", v: -1, label: "Unlocks filler audiences pack" },
  UnlockSpecialDialogue:     { icon: "💬", v: -1, label: "Unlocks special dialogue" },
  ChangeTaxes:               { icon: "📈", v: -1, label: "Changes taxes" },
  KnightRecruitment:         { icon: "🛡", v: -1, label: "Recruits knight" },
  KnightDemission:           { icon: "👋", v: -1, label: "Knight demission" },
  CountyRallied:             { icon: "🚩", v: -1, label: "County rallies" },
  CountyUnrallied:           { icon: "🚩", v: -1, label: "County unrallies" },
  CountyQuestFailed:         { icon: "❌", v: -1, label: "County quest failed" },
  MajorCharacterIntroduction: { icon: "👤", v: -1, label: "Introduces character" },
  NewCharacterRomanced:      { icon: "♡", v: -1, label: "New romance" },
  InjectMurderedKnight:      { icon: "🗡", v: -1, label: "Injects murdered knight" },
  KillKnight:                { icon: "💀", v: -1, label: "Kills knight" },
  LocationDestroyed:         { icon: "💥", v: -1, label: "Destroys location" },
  UltimatumTriggered:        { icon: "⚔", v: -1, label: "Triggers ultimatum" },
  UltimatumUnset:            { icon: "🕊", v: -1, label: "Lifts ultimatum" },
  GameOver:                  { icon: "🏳", v: -1, label: "Game over" },
};

// Decode a knot's game calls into human-readable "what happens" facts:
// SpecialInstruction (evolution state switches), quest unlocks, equipment
// give/remove, knight affinity shifts, the full game-side mutation set (funds,
// taxes, county state, tags, …), and variable writes — inline in the flow,
// nested in choice effects, and passed as divert/stitch parameters — each
// carrying the ink knots that read the written variable later (the long-term
// consequences).
function whatHappensFacts(k) {
  const facts = [];
  const seen = new Set();
  const knownNames = new Set();   // every entity/var surfaced by a handled call
  const add = (f) => { const key = JSON.stringify(f); if (seen.has(key)) return; seen.add(key); facts.push(f); };
  const handle = (fn, args) => {
    const note = (s) => { if (s != null && String(s) !== "true" && String(s) !== "false") knownNames.add(String(s)); };
    if (fn === "SpecialInstruction") {
      const arg = args[0];
      if (arg != null && arg !== "true" && arg !== "false") { note(arg); add({ k: "special", ukey: String(arg).toUpperCase(), arg: String(arg) }); }
    } else if (fn === "UnlockQuest") {
      // Only the first arg is the quest id; trailing args are modifier indices.
      const qid = args[0];
      const s = qid != null ? String(qid) : "";
      if (s && s !== "false" && s !== "true" && QUEST && QUEST.quests[s]) { note(qid); add({ k: "quest", qid: s }); }
    } else if (fn === "UnlockEquipment" || fn === "RemoveEquipment") {
      if (args.length >= 2) { note(args[1]); add({ k: "item", op: fn === "UnlockEquipment" ? "unlock" : "remove", ref: String(args[1]).toUpperCase() }); }
    } else if (fn === "UpdateKnightAffinity") {
      const a0 = args[0];
      if (a0 != null) {
        note(a0);
        const mapped = knightIndex().get(String(a0).toUpperCase());
        add({ k: "knight", stem: mapped || String(a0), delta: args[1] != null ? String(args[1]) : "" });
      }
    } else if (fn === "AddDoleanceForNextCycle") {
      // arg 0 is the audience resource stem played next cycle, arg 1 its type
      const stem = args[0] != null ? String(args[0]) : "";
      const type = args[1] != null ? String(args[1]) : "";
      if (stem && stem !== "false" && stem !== "true") { note(stem); add({ k: "doleance", stem, type }); }
    } else if (fn.startsWith("set:")) {
      const v = args[0];
      if (v != null && !String(v).startsWith("$")) { note(v); add({ k: "set", var: String(v), value: args[1], temp: fn === "set:temp=" }); }
    } else {
      const st = STATE_FNS[fn];
      if (st && args.length) {
        const varArg = st.v;
        const varName = (varArg >= 0 && args[varArg] != null) ? String(args[varArg]) : null;
        for (const a of args) note(a);
        add({ k: "state", what: st.label, icon: st.icon, args: args.slice(), varArg, var: varName });
      }
    }
  };
  const paramPass = new Set();
  const passArg = (s) => {
    s = String(s);
    if (s === "true" || s === "false" || s.startsWith("$") || !(k.writes || []).includes(s)) return;
    paramPass.add(s);
  };
  for (const t of k.lines) {
    if (!Array.isArray(t)) continue;
    if (t[0] === "3") {
      handle(t[1], t[2] || []);
    } else if (t[0] === "2") {
      // choice effects are stored as [fn, [args...]] pairs (no "3" marker)
      if (Array.isArray(t[5])) for (const e of t[5]) if (Array.isArray(e)) handle(e[0], Array.isArray(e[1]) ? e[1] : []);
      // divert-argument flag writes: choosing this option passes <flag> into
      // the target stitch/knot, which is how many once-flags get set
      if (Array.isArray(t[6])) for (const a of t[6]) passArg(a);
    } else if (t[0] === "4" && Array.isArray(t[2])) {
      for (const a of t[2]) passArg(a);
    } else if (t[0] === "5" && Array.isArray(t[2])) {
      // parameterized stitch: its declared params are written flags
      for (const p of t[2]) passArg(p);
    }
  }
  // Surface the divert/param flag writes too, but only when they actually
  // ripple — read by story knots elsewhere (pure function-signature params like
  // `Amount` in ChangeTaxes never reach here).
  for (const v of paramPass) {
    if (knownNames.has(v)) continue;
    if (!varStoryReaders(v).length) continue;
    add({ k: "set", var: v, value: null, param: true });
  }
  return facts;
}

// "what happens" facts for a quest: the story-var set/clear consequences its
// rewards cause (success, failure, unexpected outcomes, modifier variants),
// each carrying the ink knots that read the var later (the ripple).
function questHappensFacts(q) {
  const facts = [];
  const seen = new Set();
  const add = (f) => { const key = JSON.stringify(f); if (seen.has(key)) return; seen.add(key); facts.push(f); };
  const lists = [];
  if (q.rw) { if (q.rw.s) lists.push(q.rw.s); if (q.rw.f) lists.push(q.rw.f); }
  for (const uo of q.un || []) if (Array.isArray(uo.rw)) lists.push(uo.rw);
  for (const mo of q.mo || []) { if (Array.isArray(mo.sr)) lists.push(mo.sr); if (Array.isArray(mo.fr)) lists.push(mo.fr); }
  for (const list of lists) {
    for (const r of list || []) {
      if (r && r.t != null && rewardName(r.t) === "BOOL_STORY_VAR_MODIF" && r.v) {
        add({ k: "set", var: String(r.v), value: r.b ? "true" : "false" });
      }
      if (r && r.t != null && rewardName(r.t) === "AUDIENCE_REQUEST" && r.item_stem) {
        add({ k: "request", stem: String(r.item_stem) });
      }
    }
  }
  return facts;
}

function setValueText(value) {
  if (typeof value === "string") return (value.startsWith('"') && value.endsWith('"')) ? value.slice(1, -1) : value;
  return value == null ? "" : String(value);
}

// ink knots that genuinely *consume* a variable — excludes pure function
// signatures (e.g. ChangeTaxes reading its `Amount` param) so ripple rows stay
// about narrative knots. A function knot (knot.fn) is only dropped when the
// variable is one of its *declared params*; function knots that genuinely read
// story flags (endings, cutscenes, reactions, conversations — e.g.
// kingslayer_cutscene reading ursula_sent_to_kingslayer) stay as readers.
function varStoryReaders(v) {
  return (varReaders().get(v) || []).filter((kn) => {
    const kd = INDEX.knots[kn];
    if (!kd) return true;
    if (kd.fn && (kd.params || []).includes(v)) return false;
    return true;
  });
}

// "read in N ink knots" ripple row for a written variable/flag
function varReadersHtml(v) {
  const readers = varStoryReaders(v);
  if (!readers.length) {
    const gs = INDEX.variables[v] && INDEX.variables[v].gs;
    return gs
      ? `<div class="readers"><span class="mut">— no ink knot reads it; referenced by the game engine (consumed game-side)</span></div>`
      : `<div class="readers"><span class="mut">— no ink knot reads it; no game-side reference found (may be vestigial)</span></div>`;
  }
  const shown = readers.slice(0, 6);
  const more = readers.length > shown.length ? ` <span class="mut">+${readers.length - shown.length} more</span>` : "";
  const chips = shown.map((kn) => (
    INDEX.knots[kn]
      ? `<a class="chip knobtn knotlink" data-knot="${esc(kn)}">${esc(kn)}</a>`
      : `<span class="chip">${esc(kn)}</span>`
  )).join(" ");
  return `<div class="readers"><span class="mut">read in ${readers.length} ink knot${readers.length > 1 ? "s" : ""}:</span> ${chips}${more}</div>`;
}

// render one state-fact argument: the written variable (bold), a signed
// numeric delta, or a cross-linked quest/item/knight/knot name
function stateArg(a, i, varArg) {
  const s = String(a);
  if (i === varArg) return `<b>${esc(s)}</b>`;
  if (/^-?\d+(\.\d+)?$/.test(s) && Number(s) !== 0) return (Number(s) > 0 ? "+" : "") + s;
  if (INDEX.knots[s]) return `<a class="knotlink" data-knot="${esc(s)}">${esc(s)}</a>`;
  return linkArg(a);
}

function whatFactRow(f) {
  const row = document.createElement("div");
  row.className = "what-row";
  let ic = "⚙", body = "";
  if (f.k === "special") {
    ic = "⚡";
    const inst = SPECIAL && SPECIAL.instructions[f.ukey];
    const link = `<a class="speciallink" data-special="${esc(f.ukey)}">${esc(f.ukey)}</a>`;
    if (inst) {
      const also = (inst.knots || []).length > 1 ? ` <span class="mut">also emitted in ${inst.knots.length} knots</span>` : "";
      body = `<div>SpecialInstruction ${link}${also}</div>`;
      if (inst.note) body += `<div class="what-note">${esc(inst.note)}</div>`;
      else if (inst.signal) body += `<div class="what-note">signal ${esc(inst.signal)}</div>`;
    } else {
      body = `<div>SpecialInstruction ${link} <span class="mut">(not in special catalog)</span></div>`;
    }
  } else if (f.k === "quest") {
    ic = "🔓";
    body = `<div>Unlocks quest ${questIdLink(f.qid)}</div>`;
  } else if (f.k === "item") {
    ic = f.op === "remove" ? "🗑" : "📦";
    const stem = f.ref && invIndex().get(f.ref);
    const ref = (stem && INV.items[stem]) ? invItemLink("", stem) : esc(f.ref);
    body = `<div>${f.op === "remove" ? "Removes" : "Grants"} item ${ref}</div>`;
  } else if (f.k === "knight") {
    ic = "♡";
    const d = f.delta && f.delta !== "0" ? ` <span class="comma">${f.delta > 0 ? "+" + f.delta : f.delta}</span>` : "";
    body = `<div>Changes ${knightLink(f.stem)} affinity${d}</div>`;
  } else if (f.k === "doleance") {
    ic = "📜";
    const aud = f.stem && AUDIENCE && AUDIENCE.audiences[f.stem];
    const stemLink = aud
      ? `<a class="audiencelink" data-aud="${esc(f.stem)}" title="open audience ${esc(f.stem)}">${esc(f.stem)}</a>`
      : esc(f.stem);
    const plays = aud && aud.k && INDEX.knots[aud.k]
      ? ` <span class="mut">→ plays <a class="knotlink" data-knot="${esc(aud.k)}">${esc(aud.k)}</a></span>`
      : "";
    body = `<div>Adds doleance (${stemLink}${f.type ? ", " + esc(f.type) : ""})${plays}</div>`;
  } else if (f.k === "request") {
    ic = "📣";
    const stem = f.stem;
    const link = (AUDIENCE && AUDIENCE.requests[stem])
      ? `<a class="reqlink" data-req="${esc(stem)}" title="open request ${esc(stem)}">${esc(aRequestName(stem))}</a>`
      : esc(stem);
    body = `<div>Grants audience request ${link}</div>`;
  } else if (f.k === "set") {
    ic = "✎";
    const mark = f.param ? ' <span class="mut">(via divert)</span>' : (f.temp ? ' <span class="mut">(temp)</span>' : "");
    body = `<div class="setline"><span class="set">${esc(f.var)}</span>${f.value == null ? "" : " = " + esc(setValueText(f.value))}${mark}</div>${varReadersHtml(f.var)}`;
  } else if (f.k === "state") {
    ic = f.icon || "⚙";
    const parts = (f.args || []).map((a, i) => stateArg(a, i, f.varArg));
    body = `<div>${esc(f.what)}${parts.length ? " (" + parts.join(", ") + ")" : ""}</div>`;
    if (f.var != null) body += varReadersHtml(f.var);
  }
  const icEl = document.createElement("span");
  icEl.className = "what-ic";
  icEl.textContent = ic;
  const bodyEl = document.createElement("div");
  bodyEl.className = "what-body";
  bodyEl.innerHTML = body;
  row.appendChild(icEl);
  row.appendChild(bodyEl);
  return row;
}

// ---------------------------------------------------------------------------
// knot origin maps — reverse lookups for "how does this knot fire"
// ---------------------------------------------------------------------------
let _knotAud = null;   // knot -> [{stem, f, c, rq}]
let _knotFu = null;    // knot -> [{qid, kind}]  (kind: success/failure/unexpected)
let _knotIn = null;    // knot -> [incoming diverting knot names]
let _doleance = null;  // audience stem -> [{knot, type}] scheduling it next cycle
let _knotRequest = null; // knot -> Set(request stems) unlocked via UnlockAudienceRequest

function knotAudiences() {
  if (!_knotAud && AUDIENCE) {
    _knotAud = new Map();
    for (const [stem, a] of Object.entries(AUDIENCE.audiences)) {
      if (!a.k) continue;
      if (!_knotAud.has(a.k)) _knotAud.set(a.k, []);
      _knotAud.get(a.k).push({ stem, f: a.f, c: a.c || [], rq: a.rq || [], cyc: a.cyc || [], dir: a.dir || [], dd: a.dd || [], fl: a.fl || [], ci: a.ci || [] });
    }
  }
  return _knotAud || new Map();
}
function knotFuQuests() {
  if (!_knotFu && AUDIENCE) {
    _knotFu = new Map();
    const push = (knot, qid, kind) => {
      if (!knot || !INDEX.knots[knot]) return;
      if (!_knotFu.has(knot)) _knotFu.set(knot, []);
      _knotFu.get(knot).push({ qid, kind });
    };
    for (const [qid, q] of Object.entries(QUEST.quests)) {
      const fu = q.fu || [];
      const kinds = ["success", "failure"];
      fu.forEach((stem, i) => {
        const a = AUDIENCE.audiences[stem];
        if (a && a.k) push(a.k, qid, kinds[i] || "follow-up");
      });
      for (const uo of q.un || []) {
        const a = uo.fu && AUDIENCE.audiences[uo.fu];
        if (a && a.k) push(a.k, qid, "unexpected");
      }
      for (const mo of q.mo || []) {
        for (const stem of mo.unfu || []) {
          const a = AUDIENCE.audiences[stem];
          if (a && a.k) push(a.k, qid, "unexpected");
        }
      }
    }
  }
  return _knotFu || new Map();
}
function knotIncoming() {
  if (!_knotIn) {
    _knotIn = new Map();
    if (INDEX) for (const [name, k] of Object.entries(INDEX.knots)) {
      for (const d of k.diverts || []) {
        if (!INDEX.knots[d]) continue;
        if (!_knotIn.has(d)) _knotIn.set(d, []);
        _knotIn.get(d).push(name);
      }
    }
  }
  return _knotIn || new Map();
}
// audience stem -> [{knot, type}] — knots scheduling that audience for the next
// cycle via AddDoleanceForNextCycle(stem, type) (flow-level and choice effects).
function doleanceSchedulers() {
  if (_doleance) return _doleance;
  _doleance = new Map();
  if (!INDEX) return _doleance;
  const rec = (fn, args, knot) => {
    if (fn !== "AddDoleanceForNextCycle" || !Array.isArray(args) || !args.length) return;
    const stem = String(args[0]);
    if (!stem || stem === "false" || stem === "true") return;
    if (!_doleance.has(stem)) _doleance.set(stem, []);
    _doleance.get(stem).push({ knot, type: args[1] != null ? String(args[1]) : "" });
  };
  for (const [name, k] of Object.entries(INDEX.knots)) {
    for (const t of k.lines || []) {
      if (!Array.isArray(t)) continue;
      if (t[0] === "3") rec(t[1], t[2] || [], name);
      else if (t[0] === "2" && Array.isArray(t[5])) {
        for (const e of t[5]) if (Array.isArray(e)) rec(e[0], Array.isArray(e[1]) ? e[1] : [], name);
      }
    }
  }
  return _doleance;
}
// knot -> [request stems it unlocks via UnlockAudienceRequest] (flat calls and
// choice effects), mirroring how doleanceSchedulers collects AddDoleanceForNextCycle
function knotRequests() {
  if (_knotRequest) return _knotRequest;
  _knotRequest = new Map();
  if (!INDEX) return _knotRequest;
  const rec = (fn, args, knot) => {
    if (fn !== "UnlockAudienceRequest" || !Array.isArray(args) || !args.length) return;
    const stem = String(args[0]);
    if (!stem || stem === "false" || stem === "true") return;
    if (!_knotRequest.has(knot)) _knotRequest.set(knot, new Set());
    _knotRequest.get(knot).add(stem);
  };
  for (const [name, k] of Object.entries(INDEX.knots)) {
    for (const t of k.lines || []) {
      if (!Array.isArray(t)) continue;
      if (t[0] === "3") rec(t[1], t[2] || [], name);
      else if (t[0] === "2" && Array.isArray(t[5])) {
        for (const e of t[5]) if (Array.isArray(e)) rec(e[0], Array.isArray(e[1]) ? e[1] : [], name);
      }
    }
  }
  return _knotRequest;
}
// ---------------------------------------------------------------------------
// chain of events — the narrative sequence a knot belongs to. Primary edges:
// doleance scheduling (AddDoleanceForNextCycle → the scheduled audience knot),
// quest-success follow-up audiences (unlocking knot → follow-up audience) and
// audience-request unlocks (UnlockAudienceRequest → the request's follow-up
// audience knot). Failure/unexpected follow-ups are alternate branches, not the
// primary chain.
// ---------------------------------------------------------------------------
let _chain = null; // { next: Map(knot -> Set(knot)), prev: Map(knot -> Set(knot)) }
function chainEdges() {
  if (_chain) return _chain;
  _chain = { next: new Map(), prev: new Map() };
  const add = (from, to) => {
    if (!from || !to || from === to) return;
    if (!INDEX || !INDEX.knots[from] || !INDEX.knots[to]) return;
    if (!_chain.next.has(from)) _chain.next.set(from, new Set());
    _chain.next.get(from).add(to);
    if (!_chain.prev.has(to)) _chain.prev.set(to, new Set());
    _chain.prev.get(to).add(from);
  };
  if (AUDIENCE) {
    for (const [stem, scheds] of doleanceSchedulers()) {
      const a = AUDIENCE.audiences[stem];
      if (!a || !a.k) continue;
      for (const s of scheds) add(s.knot, a.k);
    }
    for (const [knot, stems] of knotRequests()) {
      for (const stem of stems) {
        const req = AUDIENCE.requests[stem];
        const a = req && req.fua && AUDIENCE.audiences[req.fua];
        if (a && a.k) add(knot, a.k);
      }
    }
  }
  if (QUEST) {
    for (const [knot, qids] of knotUnlocks()) {
      for (const qid of qids) {
        const q = QUEST.quests[qid];
        if (!q) continue;
        const stem = (q.fu || [])[0];
        const a = stem && AUDIENCE && AUDIENCE.audiences[stem];
        if (a && a.k) add(knot, a.k);
      }
    }
  }
  return _chain;
}
// knot -> { before, after, nextTips, prevTips } — the linear spine of the
// sequence the knot belongs to (following unambiguous single hops) plus the
// branch options where the spine stops. All orderings run earliest → latest.
function knotChain(name, maxLen) {
  const lim = maxLen || 8;
  const { next, prev } = chainEdges();
  const before = [];
  let c = name;
  const seen = new Set([name]);
  while (before.length < lim) {
    const preds = prev.get(c);
    if (!preds || preds.size !== 1) break;
    const p = [...preds][0];
    if (seen.has(p)) break;
    seen.add(p); before.push(p); c = p;
  }
  before.reverse();
  const after = [];
  c = name; seen.clear(); seen.add(name);
  while (after.length < lim) {
    const succs = next.get(c);
    if (!succs || succs.size !== 1) break;
    const s = [...succs][0];
    if (seen.has(s)) break;
    seen.add(s); after.push(s); c = s;
  }
  const nextTips = [...(next.get(c) || [])].filter((t) => !after.includes(t) && t !== name);
  const prevTips = [...(prev.get(before.length ? before[0] : name) || [])].filter((t) => !before.includes(t) && t !== name);
  return { before, after, nextTips, prevTips };
}
// "Chain of events" drawer section (knot): the sequenced spine with the current
// knot highlighted, plus alternate earlier/next options where the spine branches.
function chainSection(name) {
  const ch = knotChain(name);
  const spine = [...ch.before, name, ...ch.after];
  if (spine.length <= 1 && !ch.prevTips.length && !ch.nextTips.length) return null;
  const sec = document.createElement("div");
  sec.className = "sec";
  sec.textContent = "Chain of events";
  sec.title = "The narrative sequence this knot belongs to, in play order: what queues it (doleance scheduling), the audience requests it unlocks, and the quest-success follow-up audiences it leads to.";
  const box = document.createElement("div");
  box.className = "what";
  const flow = document.createElement("div");
  flow.className = "chain";
  flow.innerHTML = spine.map((n) => {
    if (n === name) return `<span class="chain-cur">${esc(n)}</span>`;
    return `<a class="chain-step knotlink" data-knot="${esc(n)}">${esc(n)}</a>`;
  }).join('<span class="chain-arrow">→</span>');
  box.appendChild(flow);
  const addTips = (label, tips) => {
    if (!tips.length) return;
    const row = document.createElement("div");
    row.className = "what-row";
    const chips = tips.map((n) => (INDEX && INDEX.knots[n]
      ? `<a class="chip knobtn knotlink" data-knot="${esc(n)}">${esc(n)}</a>`
      : `<span class="chip">${esc(n)}</span>`)).join(" ");
    row.innerHTML = `<span class="what-ic">➥</span><span class="what-body"><b>${esc(label)}:</b> ${chips}</span>`;
    box.appendChild(row);
  };
  addTips("Earlier events", ch.prevTips);
  addTips("Next events", ch.nextTips);
  const hint = document.createElement("div");
  hint.className = "what-hint";
  hint.textContent = "Sequenced from doleance scheduling (AddDoleanceForNextCycle), audience-request unlocks (UnlockAudienceRequest) and quest-success follow-up audiences; failure/unexpected branches appear as options.";
  box.appendChild(hint);
  const frag = document.createDocumentFragment();
  frag.appendChild(sec);
  frag.appendChild(box);
  return frag;
}
// knot -> [quest ids it unlocks] (from quests.json unlock_knots)
let _knotUq = null;
function knotUnlocks() {
  if (!_knotUq && QUEST) {
    _knotUq = new Map();
    for (const [qid, knots] of Object.entries(QUEST.unlock_knots || {})) {
      for (const kn of knots) {
        if (!INDEX.knots[kn]) continue;
        if (!_knotUq.has(kn)) _knotUq.set(kn, []);
        _knotUq.get(kn).push(qid);
      }
    }
  }
  return _knotUq || new Map();
}
// knot -> [special instruction keys it emits] (from special.json knots)
let _knotSp = null;
function knotSpecials() {
  if (!_knotSp && SPECIAL) {
    _knotSp = new Map();
    for (const [name, i] of Object.entries(SPECIAL.instructions)) {
      for (const kn of i.knots || []) {
        if (!INDEX.knots[kn]) continue;
        if (!_knotSp.has(kn)) _knotSp.set(kn, []);
        _knotSp.get(kn).push(name);
      }
    }
  }
  return _knotSp || new Map();
}
// audience stem -> [special instruction keys that schedule/unlock it as an
// audience (auds)] — "which special instruction makes this audience fire".
let _audSp = null;
function audSpecials() {
  if (!_audSp && SPECIAL) {
    _audSp = new Map();
    for (const [name, i] of Object.entries(SPECIAL.instructions)) {
      for (const aud of i.auds || []) {
        if (!AUDIENCE || !AUDIENCE.audiences[aud]) continue;
        if (!_audSp.has(aud)) _audSp.set(aud, []);
        _audSp.get(aud).push(name);
      }
    }
  }
  return _audSp || new Map();
}
// knot -> [special instruction keys that unlock it as a special dialogue (dlg),
// divert to it (goto), or schedule an audience whose ink knot is this one (auds)]
// — "what makes this knot fire" reverse links.
let _knotSpTrig = null;
function knotSpecialTriggers() {
  if (!_knotSpTrig && SPECIAL) {
    _knotSpTrig = new Map();
    const push = (kn, name) => {
      if (!INDEX.knots[kn]) return;
      if (!_knotSpTrig.has(kn)) _knotSpTrig.set(kn, []);
      _knotSpTrig.get(kn).push(name);
    };
    for (const [name, i] of Object.entries(SPECIAL.instructions)) {
      for (const kn of i.dlg || []) push(kn, name);
      for (const kn of i.goto || []) push(kn, name);
      if (AUDIENCE) for (const aud of i.auds || []) {
        const a = AUDIENCE.audiences[aud];
        if (a && a.k) push(a.k, name);
      }
    }
  }
  return _knotSpTrig || new Map();
}
// knot -> [{stem, op}] items the knot grants (op "grant") or removes (op "remove")
let _knotIt = null;
function knotItems() {
  if (!_knotIt && INV) {
    _knotIt = new Map();
    const push = (kn, stem, op) => {
      if (!INDEX.knots[kn]) return;
      if (!_knotIt.has(kn)) _knotIt.set(kn, []);
      _knotIt.get(kn).push({ stem, op });
    };
    for (const [stem, it] of Object.entries(INV.items)) {
      const s = it.src || {};
      for (const kn of s.ink_unlock || []) push(kn, stem, "grant");
      for (const kn of s.ink_remove || []) push(kn, stem, "remove");
    }
  }
  return _knotIt || new Map();
}
// knot -> [knight stems whose dialogue/story/affinity/career knots include it]
let _knotKn = null;
function knotKnights() {
  if (!_knotKn && KNIGHTS) {
    _knotKn = new Map();
    const add = (kn, stem) => {
      if (!kn || !INDEX.knots[kn]) return;
      if (!_knotKn.has(kn)) _knotKn.set(kn, new Set());
      _knotKn.get(kn).add(stem);
    };
    for (const [stem, k] of Object.entries(KNIGHTS.knights)) {
      for (const kn of k.story || []) add(kn, stem);
      for (const kn of Object.values(k.specd || {})) add(kn, stem);
      for (const kn of Object.values(k.afd || {})) add(kn, stem);
      for (const [, knot] of (k.conv || [])) add(knot, stem);
      if (k.ending) add(k.ending, stem);
      if (k.demo) add(k.demo, stem);
      if (k.callback) add(k.callback, stem);
      for (const kn of k.death || []) add(kn, stem);
    }
    for (const [kn, s] of _knotKn) _knotKn.set(kn, [...s]);
  }
  return _knotKn || new Map();
}
// human-readable suffix for a knight demission dd variant (third element)
const DEMISSION_VARIANT = {
  "violent": " (Arron's violent Dragonheart form)",
  "human": " (Dulahan's human form)",
  "possessed": " (possessed / cursed-helmet form)",
  "humbled": " (Gwendan's reformed humble candidacy)",
};
// human-readable label for an audience's targeted_pop_category enum value
const FILLER_POP_LABELS = { 0: "people", 1: "nobles", 2: "merchants", 3: "scholars" };
let _fillerUnlock = null;   // filler pack -> [knots] calling UnlockFillerAudiencesPack
function fillerPackUnlocks() {
  if (_fillerUnlock) return _fillerUnlock;
  _fillerUnlock = new Map();
  if (!INDEX) return _fillerUnlock;
  const rec = (fn, args, knot) => {
    if (fn !== "UnlockFillerAudiencesPack" || !Array.isArray(args) || !args.length) return;
    const pack = String(args[0]);
    if (!pack || pack === "false" || pack === "true") return;
    if (!_fillerUnlock.has(pack)) _fillerUnlock.set(pack, []);
    _fillerUnlock.get(pack).push(knot);
  };
  for (const [name, k] of Object.entries(INDEX.knots)) {
    for (const t of k.lines || []) {
      if (!Array.isArray(t)) continue;
      if (t[0] === "3") rec(t[1], t[2] || [], name);
      else if (t[0] === "2" && Array.isArray(t[5])) {
        for (const e of t[5]) if (Array.isArray(e)) rec(e[0], Array.isArray(e[1]) ? e[1] : [], name);
      }
    }
  }
  return _fillerUnlock;
}
// human-readable "where it comes from" for a filler-pack audience (the `fl`
// field): the pack it belongs to, who unlocks it (the first-grievance knots
// calling UnlockFillerAudiencesPack — the representative packs are available
// from the start) and the corruption/population weighting the cycle-fill
// random pick applies. Returns HTML ("" when the audience is not a filler).
function fillerSource(stem, a) {
  const fl = a.fl;
  if (!fl || !fl.length) return "";
  const bits = [`Filler scene of the <b>${esc(String(fl[0]))}</b> pack`];
  if (fl[1] != null) bits.push(`targeted at the ${esc(FILLER_POP_LABELS[fl[1]] || ("population " + fl[1]))}`);
  if (fl[2] != null) bits.push(`corruption tier ${esc(String(fl[2]))}`);
  const unlock = fillerPackUnlocks().get(fl[0]);
  if (unlock && unlock.length) {
    const chips = [...new Set(unlock)].map((k) => INDEX.knots[k]
      ? `<a class="chip knobtn knotlink" data-knot="${esc(k)}">${esc(k)}</a>`
      : `<span class="chip">${esc(k)}</span>`).join(" ");
    bits.push(`unlocked by <span class="readers">${chips}</span>`);
  } else {
    bits.push("available from the start");
  }
  bits.push("random pick to fill a cycle, corruption-weighted");
  return bits.join(" — ");
}
// human-readable "where it comes from" for a county-introduction audience (the
// `ci` field): the county whose narrated intro this is, and how the ActManager
// schedules it (act 1->2 / 2->3 transition intros with a per-neighbor shuffle
// delay, or right after a neighboring county is rallied — act_manager.gd:58,102).
// Returns HTML ("" when the audience is not a county introduction).
function countyIntroSource(a) {
  const ci = a.ci;
  if (!ci || !ci.length) return "";
  const name = esc(tkey(ci[1]) || ci[0]);
  return `County introduction of <b>${name}</b> — scheduled when act 2 or 3 starts (a few cycles in, per-neighbor shuffle delay) or when a neighboring county is rallied`;
}
// human-readable rendering of a decoded audience requirement
function audienceReqText(r) {
  const tag = r[0];
  if (tag === "VAR") return `when story var <b>${esc(r[1])}</b> is ${r[2] ? "true" : "false"}`;
  if (tag === "APLAY") return `when <b>${esc(r[1])}</b> has not played yet`;
  if (tag === "KDEAD") return `when ${esc(tkey(r[1]) || r[1])} is dead`;
  if (tag === "KABS") return `when ${esc(tkey(r[1]) || r[1])} is away from the roundtable`;
  return `when ${esc(tkey(r[1]) || r[1])} is at the roundtable`;
}
function originSection(name) {
  const k = INDEX.knots[name];
  if (!k) return null;
  const sec = document.createElement("div");
  sec.className = "sec";
  sec.textContent = "Where it comes from";
  sec.title = "What activates this knot: the special instructions that unlock/divert to it, the quests that fire it as a follow-up audience, the audience resources that play it (with their conditions and cycle scheduling), and the ink knots that divert into it.";
  const box = document.createElement("div");
  box.className = "what";
  const add = (body) => {
    const row = document.createElement("div");
    row.className = "what-row";
    row.innerHTML = `<span class="what-ic">➥</span><span class="what-body">${body}</span>`;
    box.appendChild(row);
  };
  const fu = knotFuQuests().get(name);
  if (fu && fu.length) {
    const by = {};
    for (const f of fu) (by[f.qid] = by[f.qid] || []).push(f.kind);
    for (const [qid, kinds] of Object.entries(by)) {
      add(`Fires after ${questIdLink(qid)} <span class="mut">(${kinds.join(" / ")})</span>`);
    }
  }
  const auds = knotAudiences().get(name);
  if (auds && auds.length) {
    for (const a of auds) {
      const nm = a.c.length ? a.c.map(tkey).join(", ") : a.stem;
      const folder = a.f || a.stem;
      const reqs = a.rq.length ? ` <span class="mut">· ${a.rq.map(audienceReqText).join(", ")}</span>` : "";
      const cyc = a.cyc && a.cyc.length
        ? ` <span class="mut">· hardcoded to play at cycle ${a.cyc.join("/")} (scripted into the cycle timeline — fires regardless of player actions)</span>`
        : "";
      const dir = a.dir.length ? ` <span class="mut">· ${a.dir.map(esc).join("; ")}</span>` : "";
      const dd = a.dd && a.dd.length
        ? ` <span class="mut">· fires when ${a.dd.map((d) => `${kName(d[0])} ${d[1] === "death" ? "dies" : "leaves"}${DEMISSION_VARIANT[d[2]] || ""}`).join(", ")}</span>`
        : "";
      const fl = fillerSource(a.stem, a);
      const flk = fl ? ` <span class="mut">· ${fl}</span>` : "";
      const ci = countyIntroSource(a);
      const cik = ci ? ` <span class="mut">· ${ci}</span>` : "";
      const scheds = doleanceSchedulers().get(a.stem);
      const audTarget = AUDIENCE && AUDIENCE.audiences[a.stem]
        ? `audience ${audienceLink(a.stem)}`
        : `audience <b>${esc(a.stem)}</b>`;
      if (scheds && scheds.length) {
        const from = scheds.map((s) => INDEX.knots[s.knot]
          ? `<a class="chip knobtn knotlink" data-knot="${esc(s.knot)}">${esc(s.knot)}</a>`
          : `<span class="chip">${esc(s.knot)}</span>`).join(" ");
        add(`Comes from <span class="readers">${from}</span> as a <b>${esc(folder)}</b> doleance ${audTarget}${reqs}${cyc}${dir}${dd}${flk}${cik}`);
      } else {
        add(`Played as <b>${esc(folder)}</b> ${audTarget}${reqs}${cyc}${dir}${dd}${flk}${cik}`);
      }
    }
  }
  const spTrig = knotSpecialTriggers().get(name);
  if (spTrig && spTrig.length) {
    const chips = [...new Set(spTrig)].map((n) => `<a class="chip speciallink" data-special="${esc(n)}">${esc(n)}</a>`).join(" ");
    add(`Fires when the <b>special instruction</b> <span class="readers">${chips}</span> is triggered (unlocks/diverts this knot or schedules the audience that plays it)`);
  }
  const inc = (knotIncoming().get(name) || []).slice(0, 24);
  if (inc.length) {
    const chips = inc.map((kn) => INDEX.knots[kn]
      ? `<a class="chip knobtn knotlink" data-knot="${esc(kn)}">${esc(kn)}</a>`
      : `<span class="chip">${esc(kn)}</span>`).join(" ");
    add(`Reached from knots: <span class="readers">${chips}</span>`);
  }
  if (!box.childNodes.length) return null;
  const frag = document.createDocumentFragment();
  frag.appendChild(sec);
  frag.appendChild(box);
  return frag;
}

function openDetail(name) {
  const k = INDEX.knots[name];
  if (!k) return;
  const panel = $("drawerpanel");
  panel.innerHTML = "";
  const head = document.createElement("div");
  head.className = "dhead";
  const sig = (k.params && k.params.length) ? `(${esc(k.params.join(", "))})` : "";
  head.innerHTML = `<h2>${esc(name)}${sig}</h2>${k.fn ? `<span class="fnbadge">fn</span>` : ""}
    <button class="close" id="dback" title="back">←</button>
    <button class="close" id="dclose">✕</button>`;
  head.querySelector("#dback").onclick = () => history.back();
  head.querySelector("#dclose").onclick = () => goClose();
  panel.appendChild(head);

  const sub = document.createElement("div");
  sub.className = "dsub";
  sub.textContent = `${k.c} · ${k.text} text lines · ${k.chars} chars · ${k.choices} choices`;
  panel.appendChild(sub);

  const origin = originSection(name);
  if (origin) panel.appendChild(origin);

  const chain = chainSection(name);
  if (chain) panel.appendChild(chain);

  const facts = whatHappensFacts(k);
  if (facts.length) {
    const sec = document.createElement("div");
    sec.className = "sec";
    sec.textContent = "What happens";
    sec.title = "Decoded game calls of this knot: evolution switches, quest unlocks, item gains/removals, affinity shifts, and variable writes with the ink knots that read them later.";
    panel.appendChild(sec);
    const box = document.createElement("div");
    box.className = "what";
    for (const f of facts) box.appendChild(whatFactRow(f));
    const hint = document.createElement("div");
    hint.className = "what-hint";
    hint.textContent = "Choice-specific consequences appear inline on each choice below.";
    box.appendChild(hint);
    panel.appendChild(box);
  }

  function chipRow(label, arr, cls) {
    if (!arr || !arr.length) return;
    const chips = document.createElement("div");
    chips.className = "chips";
    for (const item of arr) {
      const c = document.createElement("span");
      c.className = "chip " + (cls || "");
      c.textContent = item;
      if (cls === "f") c.addEventListener("click", () => { applyFnFilter(item); });
      else c.addEventListener("click", () => { applyVarFilter(item, cls === "w" ? "writes" : "reads"); });
      chips.appendChild(c);
    }
    const sec = document.createElement("div");
    sec.className = "sec";
    sec.textContent = label;
    panel.appendChild(sec);
    panel.appendChild(chips);
  }
  chipRow("Speakers", Object.entries(k.sp || {}).map(([s, c]) => `${s} ×${c}`));
  chipRow("Functions invoked", k.funcs, "f");
  chipRow("Variables read", k.reads, "r");
  chipRow("Variables written", k.writes, "w");
  chipRow("Diverts", k.diverts, "d");

  const tech = document.createElement("div");
  tech.className = "techbar";
  tech.innerHTML = `<span class="techlabel">technical layer</span>` +
    SHOW_ITEMS.map(([key, label, desc]) =>
      `<label title="${esc(desc)}"><input type="checkbox" data-show="${key}"${state.show[key] ? " checked" : ""}> ${label}</label>`
    ).join("") +
    `<span class="techsub">functions</span>` +
    FN_ITEMS.map(([key, label, desc]) =>
      `<label title="${esc(desc)}"><input type="checkbox" data-show="${key}"${state.show[key] ? " checked" : ""}> ${label}</label>`
    ).join("") +
    `<span class="techsub">text</span>` +
    BBC_ITEMS.map(([key, label, desc]) =>
      `<label title="${esc(desc)}"><input type="checkbox" data-show="${key}"${state.show[key] ? " checked" : ""}> ${label}</label>`
    ).join("");
  for (const chk of tech.querySelectorAll("input[data-show]")) {
    chk.addEventListener("change", () => {
      state.show[chk.dataset.show] = chk.checked;
      saveShowPrefs();
      const sp = $("drawerpanel").scrollTop;
      renderDial(name);
      $("drawerpanel").scrollTop = sp;
    });
  }
  panel.appendChild(tech);

  const dial = document.createElement("div");
  dial.className = "dial";
  dial.id = "dial";
  panel.appendChild(dial);
  renderDial(name);
  enhanceSections(panel);

  $("drawer").hidden = false;
  document.body.style.overflow = "hidden";
}

function renderDial(name) {
  const k = INDEX.knots[name];
  const dial = $("dial");
  dial.innerHTML = "";
  renderDialogue(k, dial);
}
function closeDetail() {
  $("drawer").hidden = true;
  document.body.style.overflow = "";
}

// ---------------------------------------------------------------------------
// navigation history — browser back/forward through opened details.
// Each location is { t: tab, d: null | { k: kind, v: key } }; opening a
// detail, jumping between details, switching tabs or closing the drawer
// pushes an entry; popstate replays the entry without pushing again.
// ---------------------------------------------------------------------------
const INIT_LOC = { t: "ink", d: null };

function activeTab() {
  if ($("tab-quest").classList.contains("active")) return "quest";
  if ($("tab-inv").classList.contains("active")) return "inv";
  if ($("tab-knight").classList.contains("active")) return "knight";
  if ($("tab-special").classList.contains("active")) return "special";
  if ($("tab-aud").classList.contains("active")) return "aud";
  return "ink";
}
function validLoc(loc) {
  if (!loc || !loc.t || !loc.d) return false;
  const k = loc.d.k, v = loc.d.v;
  if (k === "knot") return !!(INDEX && INDEX.knots[v]);
  if (k === "quest") return !!(QUEST && QUEST.quests[v]);
  if (k === "inv") return !!(INV && INV.items[v]);
  if (k === "knight") return !!(KNIGHTS && KNIGHTS.knights[v]);
  if (k === "special") return !!(SPECIAL && SPECIAL.instructions[v]);
  if (k === "aud") return !!(AUDIENCE && AUDIENCE.audiences[v]);
  if (k === "areq") return !!(AUDIENCE && AUDIENCE.requests[v]);
  return false;
}
function openDetailBy(kind, key) {
  if (kind === "knot") return openDetail(key);
  if (kind === "quest") return openQuestDetail(key);
  if (kind === "inv") return openInvDetail(key);
  if (kind === "knight") return openKnightDetail(key);
  if (kind === "special") return openSpecialDetail(key);
  if (kind === "aud") return openAudienceDetail(key);
  if (kind === "areq") return openRequestDetail(key);
}
function applyLoc(loc) {
  if (!loc || !loc.t) loc = INIT_LOC;
  if (activeTab() !== loc.t) switchTab(loc.t);
  if (validLoc(loc)) openDetailBy(loc.d.k, loc.d.v);
  else closeDetail();
}
function pushLoc(loc) {
  const cur = history.state;
  if (cur && JSON.stringify(cur) === JSON.stringify(loc)) return;
  history.pushState(loc, "");
  applyLoc(loc);
}
// navigate to a detail (kind: knot/quest/inv/knight/special/aud/areq) on its own tab
function go(kind, key) {
  const tab = kind === "knot" ? "ink" : (kind === "areq" ? "aud" : kind);
  const loc = { t: tab, d: { k: kind, v: key } };
  if (!validLoc(loc)) return;
  pushLoc(loc);
}
// switch to a tab with no detail open
function goTab(name) { pushLoc({ t: name, d: null }); }
// close the drawer, staying on the current tab
function goClose() { pushLoc({ t: activeTab(), d: null }); }
window.addEventListener("popstate", (e) => {
  applyLoc(e.state && e.state.t ? e.state : INIT_LOC);
});

function applyVarFilter(v, mode) {
  goClose();
  state.varName = v;
  state.varUse = mode || "either";
  $("var").value = v;
  const radios = document.querySelectorAll('input[name=varuse]');
  for (const r of radios) r.checked = (r.value === (mode || "either"));
  renderResults();
}
function applyFnFilter(f) {
  goClose();
  state.fn = f;
  state.fnArg = "";
  state.fnOp = "=";
  state.fnVal = "";
  $("fn").value = f;
  $("fnarg").value = "";
  $("fnval").value = "";
  $("fnop").value = "=";
  fillFnArgList();
  renderResults();
}

// ---------------------------------------------------------------------------
// events
// ---------------------------------------------------------------------------
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

$("q").addEventListener("input", debounce(() => { state.q = $("q").value.trim(); renderResults(); }, 120));
$("spk").addEventListener("change", () => { state.spk = $("spk").value; renderResults(); });
$("cat").addEventListener("change", () => { state.cat = $("cat").value; renderResults(); });
$("var").addEventListener("input", debounce(() => {
  state.varName = $("var").value.trim();
  state.varUse = document.querySelector('input[name=varuse]:checked').value;
  renderResults();
}, 150));
$("fn").addEventListener("input", debounce(() => {
  state.fn = $("fn").value.trim();
  fillFnArgList();
  $("fnarg").value = $("fnarg").value || "";
  fillFnValList();
  renderResults();
}, 150));
$("fnarg").addEventListener("input", debounce(() => {
  state.fnArg = $("fnarg").value.trim();
  fillFnValList();
  renderResults();
}, 150));
$("fnop").addEventListener("change", () => { state.fnOp = $("fnop").value; renderResults(); });
$("fnval").addEventListener("input", debounce(() => {
  state.fnVal = $("fnval").value.trim();
  renderResults();
}, 150));
document.querySelectorAll('input[name=varuse]').forEach(r => r.addEventListener("change", () => {
  state.varUse = r.value; renderResults();
}));
$("hasch").addEventListener("change", () => { state.hasCh = $("hasch").checked; renderResults(); });
$("hidefn").addEventListener("change", () => { state.hideFn = $("hidefn").checked; saveHideFn(); renderResults(); });
$("reset").addEventListener("click", () => {
  state = { ...state, q: "", spk: "", cat: "", varName: "", varUse: "either", fn: "", fnArg: "", fnOp: "=", fnVal: "", hasCh: false, hideFn: loadHideFn(), src: "", kf: "", kc: "", kq: "", ksp: "" };
  $("q").value = ""; $("spk").value = ""; $("cat").value = ""; $("var").value = ""; $("fn").value = "";
  $("fnarg").value = ""; $("fnval").value = ""; $("fnop").value = "=";
  fillFnArgList(); fillFnValList();
  document.querySelector('input[name=varuse][value=either]').checked = true;
  $("hasch").checked = false; $("hidefn").checked = state.hideFn;
  $("src").value = "";
  for (const id of ["kf", "kc", "kq", "ksp"]) $(id).value = "";
  saveHideFn();
  renderResults();
});
$("locale").addEventListener("change", () => switchLocale($("locale").value));

$("src").addEventListener("change", () => { state.src = $("src").value; renderResults(); });
for (const id of ["kf", "kc", "kq", "ksp"]) {
  $(id).addEventListener("change", () => { state[id] = $(id).value; renderResults(); });
}
$("drawerbackdrop").addEventListener("click", goClose);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") goClose(); });
$("drawerpanel").addEventListener("click", (e) => {
  const a = e.target.closest("a.questlink, a.itemlink, a.knightlink, a.knotlink, a.speciallink, a.audiencelink, a.reqlink");
  if (!a) return;
  e.preventDefault();
  e.stopPropagation();
  if (a.classList.contains("questlink")) {
    const qid = a.dataset.qid;
    if (QUEST && QUEST.quests[qid]) go("quest", qid);
  } else if (a.classList.contains("itemlink")) {
    const stem = a.dataset.stem;
    if (INV && INV.items[stem]) go("inv", stem);
  } else if (a.classList.contains("knightlink")) {
    const stem = a.dataset.knight;
    if (KNIGHTS && KNIGHTS.knights[stem]) go("knight", stem);
  } else if (a.classList.contains("knotlink")) {
    const knot = a.dataset.knot;
    if (knot && INDEX.knots[knot]) go("knot", knot);
  } else if (a.classList.contains("speciallink")) {
    const name = a.dataset.special;
    if (SPECIAL && SPECIAL.instructions[name]) go("special", name);
  } else if (a.classList.contains("audiencelink")) {
    const stem = a.dataset.aud;
    if (AUDIENCE && AUDIENCE.audiences[stem]) go("aud", stem);
  } else if (a.classList.contains("reqlink")) {
    const stem = a.dataset.req;
    if (AUDIENCE && AUDIENCE.requests[stem]) go("areq", stem);
  }
});

async function switchLocale(loc) {
  state.locale = loc;
  if (loc === "en") { LOC = {}; renderResults(); if (QUEST) renderQuestResults(); if (INV) renderInvResults(); if (KNIGHTS) renderKnightResults(); if (SPECIAL) { _shair.clear(); buildSpecialFilterUI(); renderSpecialResults(); } if (AUDIENCE) { _ahair.clear(); buildAudienceFilterUI(); renderAudienceResults(); } return; }
  try {
    const resp = await fetch(`locales/${loc}.json`);
    if (!resp.ok) throw new Error(resp.status);
    LOC = await resp.json();
  } catch (err) {
    console.error("locale load failed", err);
    alert("Failed to load locale " + loc);
    $("locale").value = "en";
    LOC = {};
    return;
  }
  // invalidate cached searchable text (tokens change)
  _hcache.clear();
  for (const k of Object.values(INDEX.knots)) k._tokens = undefined;
  renderResults();
  if (QUEST) { _qhair.clear(); populateKnightFilter(); renderQuestResults(); }
  if (INV) { _ihair.clear(); renderInvResults(); }
  if (KNIGHTS) { _khair.clear(); renderKnightResults(); }
  if (SPECIAL) { _shair.clear(); buildSpecialFilterUI(); renderSpecialResults(); }
  if (AUDIENCE) { _ahair.clear(); buildAudienceFilterUI(); renderAudienceResults(); }
  if (SPECIAL && QUEST && AUDIENCE) { buildLinkFilterUI(); renderResults(); }
}

async function init() {
  history.replaceState(INIT_LOC, "");
  const resp = await fetch("index.json");
  INDEX = await resp.json();
  buildFilterUI();
  $("hidefn").checked = state.hideFn;
  renderResults();
  await initQuests();
  await initAudiences();
  await initInventory();
  await initKnights();
  await initSpecial();
  buildLinkFilterUI();
  renderResults(); // re-render ink list now that item/knight links can resolve
  const t = INDEX.stats;
  const parts = [`${t.knots} knots · ${t.choices} choices · ${t.speakers} speakers · ${t.variables} variables · ${t.locales} locales`];
  if (QUEST && QUEST.stats) parts.push(`${QUEST.stats.quests} quests`);
  if (INV && INV.stats) parts.push(`${INV.stats.items} items`);
  if (KNIGHTS && KNIGHTS.stats) parts.push(`${KNIGHTS.stats.total} knights`);
  if (SPECIAL && SPECIAL.stats) parts.push(`${SPECIAL.stats.total} special`);
  if (AUDIENCE && AUDIENCE.stats) parts.push(`${AUDIENCE.stats.audiences} audiences · ${AUDIENCE.stats.requests} requests`);
  $("stats").textContent = parts.join(" · ");
}
init();
window.stExplorer = { renderDialogue, tokensOf };

// ---------------------------------------------------------------------------
// Quests tab
// ---------------------------------------------------------------------------
let QUEST = null; // dist/quests.json

function enumName(e, val) {
  const list = (QUEST ? QUEST.enums[e] : null) || [];
  for (const [v, n] of list) if (v == val) return n;
  return String(val);
}
function enumNames(e, vals) {
  return (vals || []).filter((v) => v != null).map((v) => enumName(e, v));
}
function en(k, loc) { return k == null ? "" : String(k); }
function tkey(key) {
  if (!key) return "";
  const entry = QUEST && QUEST.loc && QUEST.loc[key];
  return (entry && entry[state.locale]) || (entry && entry.en) || key;
}
function locName(loc, nameKey) {
  return nameKey ? tkey(nameKey) : "";
}
function statName(val) { return enumName("Statistics", val); }
function locSel(locations, val) {
  return val == null || val == "" ? "" : locations[val] || "";
}
function typeName(val) { return enumName("QuestTypes", val); }
function catName(val) { return enumName("QuestTags", val); }
function condName(val) { return enumName("ConditionTags", val); }
function rewardName(val) { return enumName("RewardType", val); }
function popName(val) { return enumName("Population", val); }

function rewardText(r) {
  const t = r.t;
  const name = rewardName(t);
  switch (name) {
    case "FUNDS": return `${r.a} gold`;
    case "SATISFACTION": return `${r.a} ${enumName("Population", r.p)} sat.`;
    case "RELIC": return `Relic ${r.item ? tkey(r.item) : "?"}`;
    case "MOUNT": return `Mount ${r.item ? tkey(r.item) : "?"}`;
    case "CONSUMABLE": return `Consumable ${r.item ? tkey(r.item) : "?"}`;
    case "QUEST_ITEM": return `Item ${r.item ? tkey(r.item) : "?"}`;
    case "AFFINITY": return `${r.a > 0 ? "+" : ""}${r.a} affinity ${r.k ? "(" + knightName(r.k) + ")" : ""}`;
    case "CHARACTER_TAG": return `Tag ${enumName("CharacterTags", r.tag)}${r.u ? " (unknown)" : ""}`;
    case "SOVEREIGN_TAG": return `${r.a} ${enumName("SovereignTags", r.sg)}`;
    case "AUDIENCE_REQUEST": return `Request ${r.item ? tkey(r.item) : "?"} ${r.u ? "(unknown)" : ""}`;
    case "LOCATION_TAX": return `${r.a} tax in ${enumName("LocationsID", r.loc)}`;
    case "LOCATION_DESTROYED": return `Destroy ${enumName("LocationsID", r.loc)}`;
    case "BOOL_STORY_VAR_MODIF": return `${r.b ? "set" : "clear"} story var ${r.v}`;
    case "CURRENT_KNIGHT_DEMISSION": return "demission of the current knight";
    case "CHARACTER_DEATH": return `kill ${r.item ? tkey(r.item) : "character"}`;
    case "SPECIAL_INSTRUCTION": return `special instruction ${r.v}${r.e ? " (trigger early)" : ""}`;
    default: return name + (r.a ? " " + r.a : "");
  }
}
function knightName(stem) {
  if (!stem) return "";
  return QUEST && QUEST.knights[stem] ? tkey(QUEST.knights[stem]) : stem;
}
// resolve an item reward to its inventory item stem (by item_stem, else by cid)
function rewardItemStem(r) {
  if (!r) return null;
  if (r.item_stem && INV && INV.items[r.item_stem]) return r.item_stem;
  if (r.item && INV) {
    const s = invalidItemsByCid().get(r.item);
    if (s) return s;
  }
  return null;
}
// reward text with item rewards rendered as clickable inventory links
function rewardHtml(r) {
  if (rewardName(r.t) === "SPECIAL_INSTRUCTION") return specialRewardHtml(r);
  if (rewardName(r.t) === "AUDIENCE_REQUEST") {
    const stem = r.item_stem;
    if (stem && AUDIENCE && AUDIENCE.requests[stem]) {
      return `Request ${requestLink(stem)}`;
    }
    return esc(rewardText(r));
  }
  const stem = rewardItemStem(r);
  if (!stem) return esc(rewardText(r));
  const t = rewardName(r.t);
  return `${t.charAt(0).toUpperCase()}${t.slice(1).toLowerCase()} ${invItemLink(t, stem)}`;
}
// SPECIAL_INSTRUCTION quest rewards: link to the special catalog + its effect note
function specialRewardHtml(r) {
  const key = r.v ? String(r.v).toUpperCase() : "";
  const inst = key && SPECIAL ? SPECIAL.instructions[key] : null;
  const link = inst
    ? `<a class="speciallink" data-special="${esc(key)}">${esc(r.v)}</a>`
    : esc(r.v || "?");
  let s = `special instruction ${link}`;
  if (r.e) s += " (trigger early)";
  if (inst && inst.note) s += ` — <span class="qchip-sub">${esc(inst.note)}</span>`;
  return s;
}
function questLink(a) {
  const s = String(a);
  if (QUEST && QUEST.quests[s]) {
    const nm = tkey(QUEST.quests[s].n) || s;
    return `<a class="questlink" data-qid="${esc(s)}" title="open quest ${esc(s)}">${esc(nm)}</a>`;
  }
  return esc(s);
}
// Like questLink but keeps the raw internal id visible next to the localized
// name, so knot views stay Ctrl+F-searchable by id.
function questIdLink(a) {
  const s = String(a);
  if (QUEST && QUEST.quests[s]) {
    const nm = tkey(QUEST.quests[s].n) || s;
    return `<a class="questlink" data-qid="${esc(s)}" title="open quest ${esc(s)}">${esc(nm)}<span class="qid">(${esc(s)})</span></a>`;
  }
  return esc(s);
}

// case-insensitive lookup: ink args use Camel_Case (e.g. Dragon_Heart) while
// item stems are snake_case and cids / knight stems are lower- or Upper_Case.
let _invIdxMap = null;
let _knightIdxMap = null;
function invIndex() {
  // don't cache a map built before INV loaded (first render happens pre-load)
  if (!_invIdxMap || (_invIdxMap.size === 0 && INV)) {
    _invIdxMap = new Map();
    if (INV) for (const stem of Object.keys(INV.items)) {
      const sk = stem.toUpperCase();
      if (!_invIdxMap.has(sk)) _invIdxMap.set(sk, stem);
      const cid = INV.items[stem].cid;
      if (cid != null) {
        const ck = String(cid).toUpperCase();
        if (!_invIdxMap.has(ck)) _invIdxMap.set(ck, stem);
      }
    }
  }
  return _invIdxMap;
}
function knightIndex() {
  if (!_knightIdxMap || (_knightIdxMap.size === 0 && KNIGHTS)) {
    _knightIdxMap = new Map();
    if (KNIGHTS) for (const stem of Object.keys(KNIGHTS.knights)) {
      _knightIdxMap.set(stem.toUpperCase(), stem);
    }
  }
  return _knightIdxMap;
}
function knightLink(stem) {
  const s = String(stem);
  if (KNIGHTS && KNIGHTS.knights[s]) {
    return `<a class="knightlink" data-knight="${esc(s)}" title="open knight ${esc(kName(s))}">${esc(kName(s))}</a>`;
  }
  return esc(s);
}
// render an argument that may be a quest id, an equipment item or a knight
function specialLink(key, text) {
  return `<a class="speciallink" data-special="${esc(key)}">${esc(text == null ? key : text)}</a>`;
}

function linkArg(a) {
  const s = String(a);
  if (QUEST && QUEST.quests[s]) return questIdLink(s);
  const istem = invIndex().get(s.toUpperCase());
  if (istem) return invItemLink("", istem);
  const kstem = knightIndex().get(s.toUpperCase());
  if (kstem) return knightLink(kstem);
  if (AUDIENCE && AUDIENCE.requests[s]) return requestLink(s);
  if (AUDIENCE && AUDIENCE.audiences[s]) return audienceLink(s);
  const up = s.toUpperCase();
  if (SPECIAL && SPECIAL.instructions[up]) return specialLink(up, s);
  return esc(s);
}

function populateKnightFilter() {
  const s = $("qknight");
  const keep = s.value;
  s.innerHTML = "";
  const no = document.createElement("option");
  no.value = ""; no.textContent = "Any"; s.appendChild(no);
  const kset = new Set();
  for (const q of Object.values(QUEST.quests)) {
    for (const uo of q.un) {
      for (const k of (uo.k || [])) {
        if (k) kset.add(k);
      }
    }
  }
  const klist = [...kset].sort((a, b) => knightName(a).localeCompare(knightName(b)));
  for (const k of klist) {
    const o = document.createElement("option");
    o.value = k; o.textContent = knightName(k); s.appendChild(o);
  }
  s.value = keep;
}

function buildQuestFilterUI() {
  function sel(id, val, opts) {
    const s = $(id);
    s.innerHTML = "";
    const no = document.createElement("option");
    no.value = ""; no.textContent = "Any"; s.appendChild(no);
    for (const o of opts) {
      const el = document.createElement("option");
      el.value = o.value; el.textContent = o.label; s.appendChild(el);
    }
  }
  sel("qtype", "", QUEST.enums.QuestTypes.map(([v, n]) => ({ value: v, label: n })));
  sel("qcat", "", QUEST.enums.QuestTags.map(([v, n]) => ({ value: v, label: n })));
  sel("qloc", "", QUEST.enums.LocationsID.map(([v, n]) => ({ value: v, label: n })));
  sel("qcond", "", QUEST.enums.ConditionTags.map(([v, n]) => ({ value: v, label: n })));
  sel("qstat", "", QUEST.enums.Statistics.map(([v, n]) => ({ value: v, label: n })));
  sel("qreward", "", QUEST.enums.RewardType.map(([v, n]) => ({ value: v, label: n })));
  populateKnightFilter();
}

const QSTATE = {
  q: "", type: "", cat: "", loc: "", cond: "", stat: "", reward: "", knight: "",
  unexp: "", deadline: false, lethal: false, kill: false, linked: false,
  qaud: false, qmo: false,
};

function questHaystack(id, q) {
  const h = [id, q.n, tkey(q.n), q.d, tkey(q.d)];
  for (const [k, v] of Object.entries(q.st)) h.push(statName(k) + " " + v);
  for (const rw of q.rw.s.concat(q.rw.f)) h.push(rewardText(rw));
  for (const uo of q.un) h.push(uo.id);
  if (QUEST.unlock_knots[id]) h.push(...QUEST.unlock_knots[id]);
  for (const c of q.cd) h.push(condName(c));
  for (const s of q.fu) if (s) h.push(s);
  for (const mo of q.mo) {
    h.push("modifier");
    for (const rw of (mo.sr || []).concat(mo.fr || [])) h.push(rewardText(rw));
  }
  return h.join(" ").toLowerCase();
}
const _qhair = new Map();
function qhay(id, q) {
  let h = _qhair.get(id);
  if (h === undefined) { h = questHaystack(id, q); _qhair.set(id, h); }
  return h;
}

function visibleQuests() {
  const out = [];
  for (const [id, q] of Object.entries(QUEST.quests)) {
    if (QSTATE.q && !matchesQuery(qhay(id, q), QSTATE.q)) continue;
    if (QSTATE.type && q.t != QSTATE.type) continue;
    if (QSTATE.cat && q.c != QSTATE.cat) continue;
    if (QSTATE.loc && q.l != QSTATE.loc) continue;
    if (QSTATE.cond && !(q.cd || []).includes(+QSTATE.cond)) continue;
    if (QSTATE.stat && !(q.st || []).some(([s]) => s == QSTATE.stat)) continue;
    if (QSTATE.reward) {
      const all = (q.rw.s.concat(q.rw.f))
        .concat(...(q.un || []).map((uo) => uo.rw || []))
        .concat(...(q.mo || []).map((mo) => (mo.sr || []).concat(mo.fr || [])));
      const has = all.some((r) => r && r.t == QSTATE.reward);
      if (!has) continue;
    }
    if (QSTATE.knight) {
      const has = q.un.some((uo) => (uo.k || []).includes(QSTATE.knight));
      if (!has) continue;
    }
    if (QSTATE.unexp === "1" && !(q.un && q.un.length)) continue;
    if (QSTATE.unexp === "0" && q.un && q.un.length) continue;
    if (QSTATE.deadline && !q.dl) continue;
    if (QSTATE.lethal && !q.lt) continue;
    if (QSTATE.kill && !q.kl) continue;
    if (QSTATE.linked && !(QUEST.unlock_knots[id] && QUEST.unlock_knots[id].length)) continue;
    if (QSTATE.qaud && !(q.fu || []).some(Boolean)) continue;
    if (QSTATE.qmo && !(q.mo && q.mo.length)) continue;
    out.push([id, q]);
  }
  return out;
}

function renderQuestResults() {
  const list = visibleQuests().sort((a, b) => a[0].localeCompare(b[0]));
  $("qcountline").innerHTML =
    `<b>${list.length}</b> of ${Object.keys(QUEST.quests).length} quests`;
  const cards = $("qcards");
  cards.innerHTML = "";
  if (!list.length) {
    cards.innerHTML = `<div class="empty">No quests match — adjust filters above.</div>`;
    return;
  }
  const groups = {};
  for (const [id, q] of list) {
    const g = typeName(q.t) || "?";
    (groups[g] = groups[g] || []).push([id, q]);
  }
  const order = Object.keys(groups).sort();
  for (const g of order) {
    const sec = document.createElement("section");
    sec.className = "group";
    sec.innerHTML = `<h3>${esc(g)} <span class="cnt">${groups[g].length}</span></h3>`;
    const grid = document.createElement("div");
    grid.className = "grid";
    for (const [id, q] of groups[g]) grid.appendChild(questCard(id, q));
    sec.appendChild(grid);
    cards.appendChild(sec);
  }
}

function questCard(id, q) {
  const el = document.createElement("div");
  el.className = "card";
  el.tabIndex = 0;
  const badges = [];
  badges.push(`<span class="badge cat">${esc(catName(q.c))}</span>`);
  if (q.l != null && q.l !== "") badges.push(`<span class="badge loc">${esc(enumName("LocationsID", q.l))}</span>`);
  if (q.dl) badges.push(`<span class="badge deadline">deadline</span>`);
  if (q.kl) badges.push(`<span class="badge kill">killing</span>`);
  if (q.lt !== false) badges.push(`<span class="badge lethal">lethal</span>`);
  if (q.un.length) badges.push(`<span class="badge unexp">${q.un.length} unexpected</span>`);
  if (q.rw.s.length) badges.push(`<span class="badge reward">${q.rw.s.length} reward(s)</span>`);
  const fuCount = (q.fu || []).filter(Boolean).length;
  if (fuCount) badges.push(`<span class="badge aud" title="follow-up ${q.fu.filter(Boolean).join(", ")}">audience ×${fuCount}</span>`);
  if (q.mo && q.mo.length) badges.push(`<span class="badge req">${q.mo.length} modifier${q.mo.length > 1 ? "s" : ""}</span>`);
  const unlock = QUEST.unlock_knots[id];
  const name = q.n ? tkey(q.n) : id;
  const reqTxt = q.st.length
    ? q.st.map(([s, v]) => `${statName(s)} ${v}`).join(", ")
    : "";
  const lockup = unlock && unlock.length
    ? `<div class="lockup">${unlock.map((u) => `<span class="knotlink" title="${esc(u)}">${esc(u)}</span>`).join(", ")}</div>`
    : `<div class="lockup muted">not unlocked in ink</div>`;
  const itemRewards = [];
  const seen = new Set();
  for (const r of q.rw.s.concat(q.rw.f)) {
    const s = rewardItemStem(r);
    if (s && !seen.has(s)) { seen.add(s); itemRewards.push([r, s]); }
  }
  for (const uo of q.un) for (const r of (uo.rw || [])) {
    const s = rewardItemStem(r);
    if (s && !seen.has(s)) { seen.add(s); itemRewards.push([r, s]); }
  }
  const rewRow = itemRewards.length
    ? `<div class="meta rewardrow">🎁 ${itemRewards.map(([r, s]) => invItemLink(rewardName(r.t), s)).join(" ")}</div>`
    : "";
  el.innerHTML = `
    <div class="top"><span class="name">${esc(name)} <i class="qid">${esc(id)}</i></span></div>
    <div class="prev">${reqTxt ? "<b>Req:</b> " + esc(reqTxt) : esc((q.d ? tkey(q.d) : "").slice(0, 160))}</div>
    <div class="meta">${badges.join("")}</div>
    ${rewRow}
    ${lockup}`;
  for (const a of el.querySelectorAll("a.itemlink")) {
    a.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      const stem2 = a.dataset.stem;
      if (!INV || !INV.items[stem2]) return;
      go("inv", stem2);
    });
  }
  el.addEventListener("click", () => go("quest", id));
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") go("quest", id); });
  return el;
}

function rewardsTable(title, rewards, cls) {
  if (!rewards || !rewards.length) return "";
  return `<div class="qrows">
    <h5>${title}</h5>
    ${rewards.map((r) => `<span class="qchip ${cls || ""}">${rewardHtml(r)}</span>`).join("")}
  </div>`;
}

// ---------------------------------------------------------------------------
// Quest → knight/item ranking (affinity, efficiency, items).
// TWO distinct systems per the game's own data:
//   • Affinity  = the knight's PREFERENCES (quest-type + condition likes /
//     dislikes) — "who likes this quest best".
//   • Efficiency = the knight's CHARACTERISTIC tags mapped through the game's
//     per-category/per-condition efficient/inefficient tag lists (tag_library)
//     — "who is good for what". Equipment items that grant those tags (relics,
//     mounts, consumables) are listed separately.
// Stats (strength, agility, …) are deliberately ignored throughout.
// ---------------------------------------------------------------------------

// Efficient/inefficient CharacterTag matches for a quest's category + conditions.
// Each entry: {v: tag value, good: bool, src: category/condition name}.
function questEffEntries(q) {
  if (!QUEST || !QUEST.eff) return [];
  const ent = [];
  const add = (map, key, src) => {
    const row = map && map[String(key)];
    if (!row) return;
    for (const v of row.e || []) ent.push({ v, good: true, src });
    for (const v of row.i || []) ent.push({ v, good: false, src });
  };
  add(QUEST.eff.qt, q.c, catName(q.c));
  for (const cd of q.cd || []) add(QUEST.eff.ct, cd, condName(cd));
  return ent;
}

function pushHit(hits, label, like) {
  if (!hits.some((h) => h.l === label)) hits.push({ l: label, like });
}

// A knight's deduplicated feature list. The same preference/characteristic can
// appear in more than one of the known/unknown/rumor buckets (e.g. POPULAR in
// both u and r); the game stores them as a dictionary keyed by tag, so each
// (type, tag) counts once.
function knightFeats(k) {
  if (!k || !k.feat) return [];
  const seen = new Set();
  return (k.feat.k || []).concat(k.feat.u || [], k.feat.r || []).filter((f) => {
    const key = f.t + "\u0000" + f.n;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// "Who likes this quest": knight quest-type/condition preference features vs
// the quest's category + conditions. Returns [{stem, score, hits[]}] sorted
// best → worst; knights with no matching preference are omitted.
function questAffinityRanking(q) {
  if (!KNIGHTS || !KNIGHTS.knights) return [];
  const cat = catName(q.c);
  const conds = new Set((q.cd || []).map(condName));
  const out = [];
  for (const stem of Object.keys(KNIGHTS.knights)) {
    const k = KNIGHTS.knights[stem];
    const allFeats = knightFeats(k);
    let score = 0;
    const hits = [];
    for (const f of allFeats) {
      if (f.n == null) continue;
      const match =
        f.t === 1 && cat && f.n === cat ? 1
        : f.t === 2 && conds.has(f.n) ? 2
        : 0;
      if (!match) continue;
      const like = f.p === 1;
      score += like ? 1 : -1;
      pushHit(hits, (like ? "likes " : "dislikes ") + f.n, like);
    }
    if (score) out.push({ stem, score, hits });
  }
  out.sort((a, b) => b.score - a.score || kName(a.stem).localeCompare(kName(b.stem)));
  return out;
}

// "Who is most efficient": knight CHARACTERISTIC tags vs the game's
// efficient/inefficient tag lists for the quest's category + conditions.
function questEfficiencyRanking(q) {
  if (!KNIGHTS || !KNIGHTS.knights) return [];
  const ent = questEffEntries(q);
  if (!ent.length) return [];
  const good = new Set(), bad = new Set();
  for (const e of ent) {
    const n = enumName("CharacterTags", e.v);
    if (n === String(e.v)) continue; // unmapped tag value — ignore
    (e.good ? good : bad).add(n);
  }
  if (!good.size && !bad.size) return [];
  const out = [];
  for (const stem of Object.keys(KNIGHTS.knights)) {
    const k = KNIGHTS.knights[stem];
    const allFeats = knightFeats(k);
    let score = 0;
    const hits = [];
    for (const f of allFeats) {
      if (f.t !== 0 || f.n == null) continue; // characteristics only
      if (good.has(f.n)) { score += 1; pushHit(hits, "efficient " + f.n, true); }
      else if (bad.has(f.n)) { score -= 1; pushHit(hits, "inefficient " + f.n, false); }
    }
    if (score) out.push({ stem, score, hits });
  }
  out.sort((a, b) => b.score - a.score || kName(a.stem).localeCompare(kName(b.stem)));
  return out;
}

// Items (relics/mounts/consumables) that grant an efficient/inefficient
// CharacterTag for this quest, sorted best → worst by net tag matches.
function questEfficientItems(q) {
  if (!INV || !INV.items) return [];
  const ent = questEffEntries(q);
  if (!ent.length) return [];
  const byVal = new Map(); // tag value -> {good: [srcs], bad: [srcs]}
  for (const e of ent) {
    if (!byVal.has(e.v)) byVal.set(e.v, { good: [], bad: [] });
    const b = byVal.get(e.v);
    const arr = e.good ? b.good : b.bad;
    if (!arr.includes(e.src)) arr.push(e.src);
  }
  const out = [];
  for (const stem of Object.keys(INV.items)) {
    const it = INV.items[stem];
    const tags = it.tags || [];
    if (!tags.length) continue;
    let score = 0;
    const goodSrc = [], badSrc = [];
    for (const t of tags) {
      const b = byVal.get(t);
      if (!b) continue;
      if (b.good.length) { score += 1; for (const s of b.good) if (!goodSrc.includes(s)) goodSrc.push(s); }
      if (b.bad.length) { score -= 1; for (const s of b.bad) if (!badSrc.includes(s)) badSrc.push(s); }
    }
    if (score) out.push({ stem, it, score, goodSrc, badSrc });
  }
  out.sort((a, b) => b.score - a.score || tkey(a.it.n).localeCompare(tkey(b.it.n)));
  return out;
}

// Reverse of questEfficientItems: for each item, the quests where its tags
// match the quest's efficient/inefficient character tags. Lazily built and
// cached once both datasets are loaded. Each entry: {qid, score, goodSrc, badSrc}.
let _itemQuestEff = null;
function itemQuestEff() {
  if (!QUEST || !INV) return _itemQuestEff || new Map();
  if (_itemQuestEff) return _itemQuestEff;
  const map = new Map();
  for (const [qid, q] of Object.entries(QUEST.quests)) {
    const ent = questEffEntries(q);
    if (!ent.length) continue;
    const byVal = new Map();
    for (const e of ent) {
      if (!byVal.has(e.v)) byVal.set(e.v, { good: [], bad: [] });
      const b = byVal.get(e.v);
      const arr = e.good ? b.good : b.bad;
      if (!arr.includes(e.src)) arr.push(e.src);
    }
    for (const [stem, it] of Object.entries(INV.items)) {
      const tags = it.tags || [];
      if (!tags.length) continue;
      let score = 0;
      const goodSrc = [], badSrc = [];
      for (const t of tags) {
        const b = byVal.get(t);
        if (!b) continue;
        if (b.good.length) { score += 1; for (const s of b.good) if (!goodSrc.includes(s)) goodSrc.push(s); }
        if (b.bad.length) { score -= 1; for (const s of b.bad) if (!badSrc.includes(s)) badSrc.push(s); }
      }
      if (!score) continue;
      let arr = map.get(stem);
      if (!arr) { arr = []; map.set(stem, arr); }
      arr.push({ qid, score, goodSrc, badSrc });
    }
  }
  for (const arr of map.values()) arr.sort((a, b) => b.score - a.score || a.qid.localeCompare(b.qid));
  _itemQuestEff = map;
  return map;
}

// Shared row markup for the affinity / efficiency ranking lists.
function traitRowsHtml(ranked) {
  return ranked.map((r) =>
    `<div class="trankrow">${knightLink(r.stem)} ` +
    `<span class="chip trscore ${r.score < 0 ? "neg" : "pos"}">${r.score > 0 ? "+" : ""}${r.score}</span>` +
    r.hits.map((h) => `<span class="chip ${h.like ? "pos" : "neg"}">${esc(h.l)}</span>`).join(" ") +
    `</div>`).join("");
}

// Chip markup for an item's efficient/inefficient tag matches — same
// "label + sources inside one chip" style as the affinity/efficiency rows.
function effChipHtml(goodSrc, badSrc) {
  const chips = [];
  if (goodSrc && goodSrc.length) chips.push(`<span class="chip pos">efficient ${goodSrc.map(esc).join(", ")}</span>`);
  if (badSrc && badSrc.length) chips.push(`<span class="chip neg">inefficient ${badSrc.map(esc).join(", ")}</span>`);
  return chips.join(" ");
}

// Row markup for one efficient-item entry in the quest drawer.
function effItemRowHtml(r) {
  return `<div class="trankrow">${invItemLink(r.it.type, r.stem)} ` +
    `<span class="chip trscore ${r.score < 0 ? "neg" : "pos"}">${r.score > 0 ? "+" : ""}${r.score}</span> ${effChipHtml(r.goodSrc, r.badSrc)}</div>`;
}

function openQuestDetail(id) {
  const q = QUEST.quests[id];
  if (!q) return;
  const panel = $("drawerpanel");
  panel.innerHTML = "";
  const head = document.createElement("div");
  head.className = "dhead";
  head.innerHTML = `<h2>${esc(tkey(q.n) || id)}</h2>
    <span class="qidbig">${esc(id)}</span>
    <button class="close" id="dback" title="back">←</button>
    <button class="close" id="dclose">✕</button>`;
  head.querySelector("#dback").onclick = () => history.back();
  head.querySelector("#dclose").onclick = goClose;
  panel.appendChild(head);

  const chips = document.createElement("div");
  chips.className = "chips";
  for (const c of [
    `type ${typeName(q.t)}`, `category ${catName(q.c)}`,
    `location ${enumName("LocationsID", q.l)}`,
    `duration ${q.du}`, `knights ${q.nk}`,
    q.dl ? "deadline" : "", q.lt === false ? "non-lethal" : "lethal",
    q.kl ? "killing" : "", q.ct ? "cutscene" : "",
    `damage ${q.dm[0]}–${q.dm[1]}`,
  ].filter(Boolean)) {
    const s = document.createElement("span");
    s.className = "chip";
    s.textContent = c;
    chips.appendChild(s);
  }
  panel.appendChild(chips);

  if (q.d) {
    const desc = document.createElement("p");
    desc.className = "qdesc";
    desc.innerHTML = rich(tkey(q.d));
    panel.appendChild(desc);
  }

  function section(title) {
    const h = document.createElement("h4");
    h.className = "qsec";
    h.textContent = title;
    panel.appendChild(h);
  }
  function rows(list, fmt) {
    if (!list || !list.length) return;
    const t = document.createElement("table");
    t.className = "qtable";
    for (const [a, b] of list.map(fmt)) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td"); td1.textContent = a; td1.className = "k";
      const td2 = document.createElement("td"); td2.innerHTML = b;
      tr.appendChild(td1); tr.appendChild(td2);
      t.appendChild(tr);
    }
    panel.appendChild(t);
  }

  const lock = QUEST.unlock_knots[id];
  if (lock && lock.length) {
    section("Unlocked in ink");
    rows(lock, (k) => ["knot", `<a class="knotlink" data-knot="${esc(k)}">${esc(k)}</a>`]);
  } else {
    section("Unlocked in ink");
    const p = document.createElement("p");
    p.className = "qdesc muted";
    p.textContent = "Never unlocked by any ink knot (variant or dead content).";
    panel.appendChild(p);
  }

  if (q.fu && q.fu.filter(Boolean).length) {
    section("Follow-up audiences");
    rows(q.fu.filter(Boolean), (stem) => {
      const a = (AUDIENCE && AUDIENCE.audiences[stem]) || (QUEST && QUEST.audiences[stem]);
      const knot = a ? a.k : "";
      const nm = a && a.c.length ? a.c.map(tkey).join(", ") : stem;
      const cond = a && a.f ? ` <span class="muted">(${esc(a.f)}${a.rq && a.rq.length ? " · " + a.rq.map(audienceReqText).join(", ") : ""})</span>` : "";
      const au = AUDIENCE && AUDIENCE.audiences[stem] ? ` <a class="audiencelink" data-aud="${esc(stem)}">${esc(stem)}</a>` : "";
      if (knot && INDEX.knots[knot]) {
        return ["audience", `<a class="knotlink" data-knot="${esc(knot)}">${esc(nm)}</a> <span class="muted">(${esc(knot)})</span>${au}${cond}`];
      }
      return ["audience", esc(nm || stem) + au + cond];
    });
  }

  const qfacts = questHappensFacts(q);
  if (qfacts.length) {
    const h = document.createElement("h4");
    h.className = "qsec";
    h.textContent = "What happens";
    panel.appendChild(h);
    const box = document.createElement("div");
    box.className = "what";
    for (const f of qfacts) box.appendChild(whatFactRow(f));
    panel.appendChild(box);
  }

  section("Stat requirements");
  rows(q.st, ([s, v]) => [statName(s), String(v)]);

  if (q.cd.length) {
    section("Conditions");
    rows(q.cd, (c) => ["condition", condName(c)]);
  }

  if (q.rk.length) {
    section("Requested knights");
    rows(q.rk, (k) => ["knight", knightLink(k)]);
  }

  if (q.dl) {
    section("Automatic failure");
    const p = document.createElement("p");
    p.className = "qdesc";
    p.textContent = `after ${q.af || "?"} cycle(s)`;
    panel.appendChild(p);
  }

  if (q.rw.s.length || q.rw.f.length) {
    section("Rewards / consequences");
    if (q.rw.s.length) {
      const h = document.createElement("h5"); h.textContent = "Success"; panel.appendChild(h);
      for (const r of q.rw.s) {
        const d = document.createElement("div"); d.className = "qchip suc";
        d.innerHTML = `⚑ ${rewardHtml(r)}`; panel.appendChild(d);
      }
    }
    if (q.rw.f.length) {
      const h = document.createElement("h5"); h.textContent = "Failure"; panel.appendChild(h);
      for (const r of q.rw.f) {
        const d = document.createElement("div"); d.className = "qchip fail";
        d.innerHTML = `✕ ${rewardHtml(r)}`; panel.appendChild(d);
      }
    }
  }

  if (q.un.length) {
    section("Unexpected outcomes");
    for (const uo of q.un) {
      const box = document.createElement("div");
      box.className = "unbox";
      const parts = [];
      if (uo.k && uo.k.length) parts.push(`knight: ${uo.k.map(knightLink).join(", ")}`);
      if (uo.ch && uo.ch.length) parts.push(`needs tags: ${esc(uo.ch.map((c) => enumName("CharacterTags", c)).join(", "))}`);
      if (uo.st != null) parts.push(esc(`${statName(uo.st)} ${uo.hi ? "≥" : "<"} ${Math.abs(uo.am)}`));
      if (uo.dm) parts.push(esc(`damage ${uo.dm[0]}–${uo.dm[1]}`));
      box.innerHTML = `<span class="unid">${esc(uo.id)}</span>` +
        (parts.length ? `<span class="unwhy">${parts.join(" · ")}</span>` : "");
      if (uo.no) {
        const note = document.createElement("div");
        note.className = "unnote";
        note.innerHTML = `“${rich(tkey(uo.no))}”`;
        box.appendChild(note);
      }
      if (uo.rw && uo.rw.length) {
        const h = document.createElement("h5"); h.textContent = "Reward"; box.appendChild(h);
        for (const r of uo.rw) {
          const d = document.createElement("div"); d.className = "qchip suc";
          d.innerHTML = `⚑ ${rewardHtml(r)}`; box.appendChild(d);
        }
      }
      panel.appendChild(box);
    }
  }
  if (q.mo.length) {
    section(`Modifiers (variants ${q.mo.length})`);
    for (const mo of q.mo) {
      const box = document.createElement("div");
      box.className = "unbox";
      const parts = [];
      if (mo.dm) parts.push(`damage ${mo.dm}`);
      if (mo.nk) parts.push(`knights ${mo.nk > 0 ? "+" : ""}${mo.nk}`);
      if (mo.du) parts.push(`duration ${mo.du > 0 ? "+" : ""}${mo.du}`);
      if (mo.lo != null) parts.push(`location → ${enumName("LocationsID", mo.lo)}`);
      if (mo.st) parts.push(mo.st.map(([s, v]) => `${statName(s)} ${v}`).join(", "));
      if (mo.un) parts.push(`outcomes: ${mo.un.join(", ")}`);
      box.innerHTML = parts.map(esc).join(" · ") || "no stat changes";
      if (mo.sr && mo.sr.length) {
        const h = document.createElement("h5"); h.textContent = "Success"; box.appendChild(h);
        for (const r of mo.sr) {
          const d = document.createElement("div"); d.className = "qchip suc";
          d.innerHTML = `⚑ ${rewardHtml(r)}`; box.appendChild(d);
        }
      }
      if (mo.fr && mo.fr.length) {
        const h = document.createElement("h5"); h.textContent = "Failure"; box.appendChild(h);
        for (const r of mo.fr) {
          const d = document.createElement("div"); d.className = "qchip fail";
          d.innerHTML = `✕ ${rewardHtml(r)}`; box.appendChild(d);
        }
      }
      panel.appendChild(box);
    }
  }

  // --- bottom: three ranking segments (affinity, efficiency, items)
  const qnote = (text) => {
    const p = document.createElement("p");
    p.className = "qdesc muted";
    p.textContent = text;
    panel.appendChild(p);
  };
  const qbox = (html) => {
    const box = document.createElement("div");
    box.className = "unbox";
    box.innerHTML = html;
    panel.appendChild(box);
  };

  const affRank = questAffinityRanking(q);
  if (affRank.length) {
    section("Who likes this quest (affinity)");
    qnote("Quest category + conditions vs each knight's quest/condition preferences. Best → worst.");
    qbox(traitRowsHtml(affRank));
  }

  const effRank = questEfficiencyRanking(q);
  if (effRank.length) {
    section("Who is most efficient");
    qnote("Quest category + conditions vs each knight's characteristics via the game's efficient/inefficient tag lists. Best → worst.");
    qbox(traitRowsHtml(effRank));
  }

  const effItems = questEfficientItems(q);
  if (effItems.length) {
    section("Efficient items");
    qnote("Equipment whose tags match the quest's efficient/inefficient character tags, grouped by type. Best → worst.");
    const groups = {};
    for (const r of effItems) (groups[r.it.type] = groups[r.it.type] || []).push(r);
    const types = EFF_ITEM_TYPE_ORDER.concat(Object.keys(groups).filter((t) => EFF_ITEM_TYPE_ORDER.indexOf(t) < 0));
    for (const t of types) {
      if (!groups[t]) continue;
      const h = document.createElement("h5");
      h.textContent = INV_TYPE_LABELS[t] || t;
      panel.appendChild(h);
      qbox(groups[t].map(effItemRowHtml).join(""));
    }
  }

  // make knot links jump to the dialogue tab
  for (const a of panel.querySelectorAll("a.knotlink")) {
    a.addEventListener("click", () => {
      const knot = a.dataset.knot || a.textContent.trim();
      if (!knot || !INDEX.knots[knot]) return;
      go("knot", knot);
    });
  }
  // make item links jump to the inventory tab
  for (const a of panel.querySelectorAll("a.itemlink")) {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const stem2 = a.dataset.stem;
      if (!INV || !INV.items[stem2]) return;
      go("inv", stem2);
    });
  }

  enhanceSections(panel);

  $("drawer").hidden = false;
  document.body.style.overflow = "hidden";
}

function rich(s) {
  return String(s || "").replace(/\[b\]/g, "<b>").replace(/\[\/b\]/g, "</b>")
    .replace(/\[color=[^\]]*\]/g, "").replace(/\[\/color\]/g, "")
    .replace(/\[[a-z0-9_.\-]+\]/g, "");
}

function switchTab(name) {
  const ink = name === "ink";
  const quest = name === "quest";
  const inv = name === "inv";
  const knight = name === "knight";
  const special = name === "special";
  const aud = name === "aud";
  $("tab-ink").classList.toggle("active", ink);
  $("tab-quest").classList.toggle("active", quest);
  $("tab-inv").classList.toggle("active", inv);
  $("tab-knight").classList.toggle("active", knight);
  $("tab-special").classList.toggle("active", special);
  $("tab-aud").classList.toggle("active", aud);
  $("filters").hidden = !ink;
  $("qfilters").hidden = !quest;
  $("ifilters").hidden = !inv;
  $("kfilters").hidden = !knight;
  $("sfilters").hidden = !special;
  $("afilters").hidden = !aud;
  $("results").hidden = !ink;
  $("qresults").hidden = !quest;
  $("iresults").hidden = !inv;
  $("kresults").hidden = !knight;
  $("sresults").hidden = !special;
  $("aresults").hidden = !aud;
  if (ink) renderResults();
  else if (quest) renderQuestResults();
  else if (inv) renderInvResults();
  else if (knight) renderKnightResults();
  else if (special) renderSpecialResults();
  else renderAudienceResults();
}

async function initQuests() {
  const resp = await fetch("quests.json");
  QUEST = await resp.json();
  buildQuestFilterUI();
  renderQuestResults();
}

$("tab-ink").addEventListener("click", () => goTab("ink"));
$("tab-quest").addEventListener("click", () => goTab("quest"));
$("tab-inv").addEventListener("click", () => goTab("inv"));
$("tab-knight").addEventListener("click", () => goTab("knight"));
$("tab-special").addEventListener("click", () => goTab("special"));
$("tab-aud").addEventListener("click", () => goTab("aud"));

function qdebounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
$("qq").addEventListener("input", qdebounce(() => {
  QSTATE.q = $("qq").value.trim(); _qhair.clear(); renderQuestResults();
}, 120));
$("qtype").addEventListener("change", () => { QSTATE.type = $("qtype").value; renderQuestResults(); });
$("qcat").addEventListener("change", () => { QSTATE.cat = $("qcat").value; renderQuestResults(); });
$("qloc").addEventListener("change", () => { QSTATE.loc = $("qloc").value; renderQuestResults(); });
$("qcond").addEventListener("change", () => { QSTATE.cond = $("qcond").value; renderQuestResults(); });
$("qstat").addEventListener("change", () => { QSTATE.stat = $("qstat").value; renderQuestResults(); });
$("qreward").addEventListener("change", () => { QSTATE.reward = $("qreward").value; renderQuestResults(); });
$("qknight").addEventListener("change", () => { QSTATE.knight = $("qknight").value; renderQuestResults(); });
$("qunexp").addEventListener("change", () => { QSTATE.unexp = $("qunexp").value; renderQuestResults(); });
$("qdeadline").addEventListener("change", () => { QSTATE.deadline = $("qdeadline").checked; renderQuestResults(); });
$("qlethal").addEventListener("change", () => { QSTATE.lethal = $("qlethal").checked; renderQuestResults(); });
$("qkill").addEventListener("change", () => { QSTATE.kill = $("qkill").checked; renderQuestResults(); });
$("qlinked").addEventListener("change", () => { QSTATE.linked = $("qlinked").checked; renderQuestResults(); });
$("qaud").addEventListener("change", () => { QSTATE.qaud = $("qaud").checked; renderQuestResults(); });
$("qmo").addEventListener("change", () => { QSTATE.qmo = $("qmo").checked; renderQuestResults(); });
$("qreset").addEventListener("click", () => {
  Object.assign(QSTATE, { q: "", type: "", cat: "", loc: "", cond: "", stat: "", reward: "", knight: "", unexp: "", deadline: false, lethal: false, kill: false, linked: false, qaud: false, qmo: false });
  $("qq").value = ""; $("qtype").value = ""; $("qcat").value = ""; $("qloc").value = "";
  $("qcond").value = ""; $("qstat").value = ""; $("qreward").value = ""; $("qknight").value = ""; $("qunexp").value = "";
  $("qdeadline").checked = false; $("qlethal").checked = false; $("qkill").checked = false; $("qlinked").checked = false;
  $("qaud").checked = false; $("qmo").checked = false;
  _qhair.clear();
  renderQuestResults();
});

// ---------------------------------------------------------------------------
// Inventory tab (all equipment: relics / mounts / consumables / meals / quest items)
// ---------------------------------------------------------------------------
let INV = null; // dist/inventory.json

const INV_TYPE_ORDER = ["RELIC", "MOUNT", "CONSUMABLE", "MEAL", "QUEST_ITEM"];
const INV_TYPE_LABELS = {
  RELIC: "Relics", MOUNT: "Mounts", CONSUMABLE: "Consumables",
  MEAL: "Meals", QUEST_ITEM: "Quest items",
};
// Quest "Efficient items" grouping order: gear first, then consumables, then
// mounts. (Meals and quest items carry no CharacterTags and never appear.)
const EFF_ITEM_TYPE_ORDER = ["RELIC", "CONSUMABLE", "MOUNT"];
const INV_STATS = ["STRENGTH", "AGILITY", "CHARISMA", "MAGIC", "WITS", "LUCK"];

function invName(it) { return tkey(it.n) || it.cid; }
function statBonusText(idx, val) {
  if (!val) return "";
  return (val > 0 ? "+" : "") + val + " " + INV_STATS[idx];
}
function itemSourceFlags(it) {
  const s = it.src;
  return {
    forge: (s.forge || []).length, stables: (s.stables || []).length,
    witch: (s.witch || []).length, meals: !!s.meals, starting: !!s.starting,
    quests: (s.quests || []).length, ink: (s.ink_unlock || []).length,
    none: !((s.forge || []).length || (s.stables || []).length || (s.witch || []).length
      || s.meals || s.starting || (s.quests || []).length || (s.ink_unlock || []).length),
  };
}
function invReqText(req) {
  if (!req) return "";
  const parts = [];
  if (req.county) parts.push("county " + req.county);
  if (req.pop != null && req.amount != null) parts.push(req.amount + " " + enumName("Population", req.pop));
  if (req.pop != null && req.amount == null) parts.push(enumName("Population", req.pop));
  if (req.stag != null && req.amount != null) parts.push(req.amount + " " + enumName("SovereignTags", req.stag));
  if (req.stag != null && req.amount == null) parts.push(enumName("SovereignTags", req.stag));
  if (req.item) parts.push("consumes " + (tkey(req.item) || req.item));
  return parts.join(" · ") || "no cost";
}
// HTML variant of invReqText: the consumed material item is a clickable link.
function invReqHtml(req) {
  if (!req) return "";
  const parts = [];
  if (req.county) parts.push("county " + esc(req.county));
  if (req.pop != null && req.amount != null) parts.push(esc(req.amount + " " + enumName("Population", req.pop)));
  if (req.pop != null && req.amount == null) parts.push(esc(enumName("Population", req.pop)));
  if (req.stag != null && req.amount != null) parts.push(esc(req.amount + " " + enumName("SovereignTags", req.stag)));
  if (req.stag != null && req.amount == null) parts.push(esc(enumName("SovereignTags", req.stag)));
  if (req.item) {
    const istem = invIndex().get(String(req.item).toUpperCase());
    parts.push("consumes " + (istem ? invItemLink("M", istem) : esc(String(req.item))));
  }
  return parts.join(" · ") || "";
}

const INVSTATE = { q: "", type: "", stat: "", pos: false, tag: "", src: "", iink: false, iex: false, ihs: false, icp: false, imat: false };

function invHaystack(stem, it) {
  const h = [stem, it.cid, it.n, it.d, it.type, tkey(it.n), tkey(it.d)];
  it.st.forEach((v, i) => { if (v) h.push(INV_STATS[i] + " " + v); });
  (it.tags || []).forEach((t) => h.push(enumName("CharacterTags", t)));
  it.src.forge.forEach(([act, req]) => h.push("forge act " + act + " " + invReqText(req)));
  it.src.stables.forEach(([act, req]) => h.push("stables act " + act + " " + invReqText(req)));
  it.src.witch.forEach(([act, req]) => h.push("witch act " + act + " " + invReqText(req)));
  if (it.src.meals) h.push("tavern meal");
  (it.src.quests || []).forEach((qid) => h.push(qid + " " + tkey(QUEST.quests[qid] && QUEST.quests[qid].n)));
  (it.src.ink_unlock || []).forEach((k) => h.push(k));
  (it.src.ink_remove || []).forEach((k) => h.push("removed " + k));
  (it.src.consumed_by || []).forEach((c) => h.push("consumed by " + c.shop + " act " + c.act + " " + (c.by || "")));
  if (it.cp) h.push("complex passive");
  return h.join(" ").toLowerCase();
}
const _ihair = new Map();
function ihay(stem, it) {
  let h = _ihair.get(stem);
  if (h === undefined) { h = invHaystack(stem, it); _ihair.set(stem, h); }
  return h;
}

function hasInvSource(it, which) {
  const s = it.src;
  switch (which) {
    case "forge": return (s.forge || []).length > 0;
    case "stables": return (s.stables || []).length > 0;
    case "witch": return (s.witch || []).length > 0;
    case "meals": return !!s.meals;
    case "starting": return !!s.starting;
    case "quests": return (s.quests || []).length > 0;
    case "ink": return (s.ink_unlock || []).length > 0;
    case "none": return itemSourceFlags(it).none;
    default: return true;
  }
}

function visibleItems() {
  const out = [];
  for (const [stem, it] of Object.entries(INV.items)) {
    if (INVSTATE.type && it.type !== INVSTATE.type) continue;
    if (INVSTATE.stat !== "") {
      const i = INV_STATS.indexOf(INVSTATE.stat);
      if (i < 0 || !it.st[i]) continue;
    }
    if (INVSTATE.pos && it.st.some((v) => v < 0)) continue;
    if (INVSTATE.tag && !(it.tags || []).includes(+INVSTATE.tag)) continue;
    if (INVSTATE.src && !hasInvSource(it, INVSTATE.src)) continue;
    if (INVSTATE.iink && !(it.src.ink_unlock || []).length) continue;
    if (INVSTATE.iex && !it.ex) continue;
    if (INVSTATE.ihs && !it.hs) continue;
    if (INVSTATE.icp && !it.cp) continue;
    if (INVSTATE.imat && !(it.src.consumed_by || []).length) continue;
    if (INVSTATE.q && !matchesQuery(ihay(stem, it), INVSTATE.q)) continue;
    out.push([stem, it]);
  }
  return out;
}

function buildInvFilterUI() {
  const sel = $("itype");
  sel.innerHTML = "";
  const any = document.createElement("option"); any.value = ""; any.textContent = "Any"; sel.appendChild(any);
  for (const t of INV_TYPE_ORDER) {
    const o = document.createElement("option"); o.value = t; o.textContent = INV_TYPE_LABELS[t]; sel.appendChild(o);
  }
  const st = $("istat");
  st.innerHTML = "";
  const any2 = document.createElement("option"); any2.value = ""; any2.textContent = "Any bonus"; st.appendChild(any2);
  for (const s of INV_STATS) {
    const o = document.createElement("option"); o.value = s; o.textContent = s; st.appendChild(o);
  }
  const tag = $("itag");
  tag.innerHTML = "";
  const any3 = document.createElement("option"); any3.value = ""; any3.textContent = "Any"; tag.appendChild(any3);
  const counts = {};
  for (const it of Object.values(INV.items)) {
    for (const t of (it.tags || [])) counts[t] = (counts[t] || 0) + 1;
  }
  const list = Object.entries(counts).sort((a, b) => enumName("CharacterTags", a[0]).localeCompare(enumName("CharacterTags", b[0])));
  for (const [v, c] of list) {
    const o = document.createElement("option");
    o.value = v; o.textContent = `${enumName("CharacterTags", v)}  (${c})`; tag.appendChild(o);
  }
}

function invSourceChips(it) {
  const f = itemSourceFlags(it);
  const chips = [];
  if (f.forge) chips.push(`<span class="badge sp-forge">forge ×${f.forge}</span>`);
  if (f.stables) chips.push(`<span class="badge sp-stables">stables ×${f.stables}</span>`);
  if (f.witch) chips.push(`<span class="badge sp-witch">witch ×${f.witch}</span>`);
  if (f.meals) chips.push(`<span class="badge sp-meals">tavern</span>`);
  if (f.starting) chips.push(`<span class="badge sp-start">starting</span>`);
  if (f.quests) chips.push(`<span class="badge sp-quest">quest ×${f.quests}</span>`);
  if (f.ink) chips.push(`<span class="badge sp-ink">story ×${f.ink}</span>`);
  if (f.none) chips.push(`<span class="badge sp-none">no source</span>`);
  return chips.join("");
}

function renderInvResults() {
  const list = visibleItems().sort((a, b) => invName(a[1]).localeCompare(invName(b[1])) || a[0].localeCompare(b[0]));
  $("icountline").innerHTML = `<b>${list.length}</b> of ${Object.keys(INV.items).length} items`;
  const cards = $("icards");
  cards.innerHTML = "";
  if (!list.length) { cards.innerHTML = `<div class="empty">No items match — adjust filters above.</div>`; return; }
  const groups = {};
  for (const [stem, it] of list) (groups[it.type] = groups[it.type] || []).push([stem, it]);
  for (const g of INV_TYPE_ORDER) {
    if (!groups[g]) continue;
    const sec = document.createElement("section");
    sec.className = "group";
    sec.innerHTML = `<h3>${esc(INV_TYPE_LABELS[g])} <span class="cnt">${groups[g].length}</span></h3>`;
    const grid = document.createElement("div");
    grid.className = "grid";
    for (const [stem, it] of groups[g]) grid.appendChild(invCard(stem, it));
    sec.appendChild(grid);
    cards.appendChild(sec);
  }
}

function invCard(stem, it) {
  const el = document.createElement("div");
  el.className = "card";
  el.tabIndex = 0;
  const stCh = it.st.map((v, i) => v ? `<span class="badge st${v > 0 ? " pos" : " neg"}">${v > 0 ? "+" : ""}${v} ${esc(INV_STATS[i])}</span>` : "").join("");
  const tags = it.tags && it.tags.length ? `<span class="badge quiet">${it.tags.length} tag${it.tags.length > 1 ? "s" : ""}</span>` : "";
  const cost = it.cost != null ? `<span class="badge cost">${it.cost} gold</span>` : "";
  const iq = itemQuestEff().get(stem);
  let effBadge = "";
  if (iq) {
    const eff = iq.filter((r) => r.score > 0).length;
    const ineff = iq.filter((r) => r.score < 0).length;
    if (eff) effBadge += `<span class="badge pos">efficient in ${eff} quest${eff > 1 ? "s" : ""}</span>`;
    if (ineff) effBadge += `<span class="badge neg">inefficient in ${ineff} quest${ineff > 1 ? "s" : ""}</span>`;
  }
  const open = () => go("inv", stem);
  el.innerHTML = `
    <div class="top"><span class="name">${esc(invName(it))}</span>
      <span class="badge type-${esc(it.type.toLowerCase())}">${esc(it.type)}</span>
      <span class="qid">${esc(it.cid)}</span></div>
    <div class="prev">${it.n ? esc(tkey(it.d)).slice(0, 160) : ""}</div>
    <div class="meta">${cost}${stCh}${tags}${effBadge}${invSourceChips(it)}</div>`;
  el.addEventListener("click", open);
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return el;
}

function openInvDetail(stem) {
  const it = INV.items[stem];
  if (!it) return;
  const panel = $("drawerpanel");
  panel.innerHTML = "";
  const head = document.createElement("div");
  head.className = "dhead";
  head.innerHTML = `<h2>${esc(invName(it))}</h2>
    <span class="qidbig">${esc(it.cid)}</span>
    <button class="close" id="dback" title="back">←</button>
    <button class="close" id="dclose">✕</button>`;
  head.querySelector("#dback").onclick = () => history.back();
  head.querySelector("#dclose").onclick = goClose;
  panel.appendChild(head);

  const sub = document.createElement("div");
  sub.className = "dsub";
  sub.textContent = `${it.type} · ${it.cost != null ? it.cost + " gold" : ""} · ${tkey(it.n)}`;
  panel.appendChild(sub);

  const chips = document.createElement("div");
  chips.className = "chips";
  for (const c of [
    it.ex ? "exclusive" : "", it.hs ? "hidden stats" : "",
    it.cp ? "complex passive (+PASSIVE)" : "", it.rr ? "requires refreshes" : "",
    it.ba ? "+" + it.ba + " armor" : "", it.dr ? "duration −" + it.dr : "",
    it.nu && it.nu > 1 ? it.nu + " uses" : "",
  ].filter(Boolean)) {
    const s = document.createElement("span"); s.className = "chip"; s.textContent = c; chips.appendChild(s);
  }
  for (const t of (it.tags || [])) {
    const s = document.createElement("span"); s.className = "chip tag"; s.textContent = enumName("CharacterTags", t); chips.appendChild(s);
  }
  panel.appendChild(chips);

  if (it.d) {
    const desc = document.createElement("p");
    desc.className = "qdesc";
    desc.innerHTML = rich(tkey(it.d));
    panel.appendChild(desc);
  }

  function section(title) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = title; panel.appendChild(h);
  }
  function rows(list, fmt) {
    if (!list || !list.length) return;
    const t = document.createElement("table"); t.className = "qtable";
    for (const [a, b] of list.map(fmt)) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td"); td1.textContent = a; td1.className = "k";
      const td2 = document.createElement("td"); td2.innerHTML = b;
      tr.appendChild(td1); tr.appendChild(td2); t.appendChild(tr);
    }
    panel.appendChild(t);
  }

  section("Statistics");
  rows(it.st.map((v, i) => [INV_STATS[i], v]), ([a, b]) => [a, `<b class="stat${b > 0 ? " pos" : b < 0 ? " neg" : ""}">${b > 0 ? "+" : ""}${b}</b>`]);

  if (it.cp) {
    section("Complex passive");
    const p = document.createElement("p");
    p.className = "qdesc muted";
    p.textContent = "This item carries a passive ability beyond its listed stat bonuses — the game flags it as a '+ PASSIVE'.";
    panel.appendChild(p);
    for (const { tag, note } of (it.psv || [])) {
      const line = document.createElement("div");
      line.className = "trankrow";
      line.innerHTML = `<span class="chip tag">${esc(tag)}</span> <span class="muted">${esc(note)}</span>`;
      panel.appendChild(line);
    }
  }

  const src = it.src;
  let hasSource = false;
  if ((src.forge || []).length) {
    section("Forge (relics)");
    rows(src.forge, ([act, req]) => ["Act " + act, invReqHtml(req) || '<span class="muted">no cost</span>']);
    hasSource = true;
  }
  if ((src.stables || []).length) {
    section("Stables (mounts)");
    rows(src.stables, ([act, req]) => ["Act " + act, invReqHtml(req) || '<span class="muted">no cost</span>']);
    hasSource = true;
  }
  if ((src.witch || []).length) {
    section("Witch tower (consumables)");
    rows(src.witch, ([act, req]) => ["Act " + act, invReqHtml(req) || '<span class="muted">no cost</span>']);
    hasSource = true;
  }
  if (src.meals) {
    section("Tavern meals");
    const p = document.createElement("p"); p.className = "qdesc muted"; p.textContent = "Available to be served as a meal in the tavern."; panel.appendChild(p);
    hasSource = true;
  }
  if (src.starting) {
    section("Starting equipment");
    const p = document.createElement("p"); p.className = "qdesc muted"; p.textContent = "Given at the start of a run."; panel.appendChild(p);
    hasSource = true;
  }
  if ((src.quests || []).length) {
    section("Quest rewards");
    rows(src.quests, (qid) => ["granted by", questLink(qid)]);
    hasSource = true;
  }
  if ((src.ink_unlock || []).length) {
    section("Unlocked in the story");
    rows(src.ink_unlock, (knot) => ["knot", `<a class="knotlink" data-knot="${esc(knot)}">${esc(knot)}</a>`]);
    hasSource = true;
  }
  if ((src.ink_remove || []).length) {
    section("Removed in the story");
    rows(src.ink_remove, (knot) => ["knot", `<a class="knotlink" data-knot="${esc(knot)}">${esc(knot)}</a>`]);
    hasSource = true;
  }
  if ((src.consumed_by || []).length) {
    section("Consumed by");
    rows(src.consumed_by, (c) => [c.shop + " act " + c.act, invItemLink("M", c.by)]);
  }
  if (!hasSource) {
    section("Source");
    const p = document.createElement("p");
    p.className = "qdesc muted";
    p.textContent = "No source found in the resources (variant or debug content).";
    panel.appendChild(p);
  }

  const iq = itemQuestEff().get(stem);
  const iqBox = (rows2, heading, noteText) => {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = heading; panel.appendChild(h);
    const p = document.createElement("p"); p.className = "qdesc muted"; p.textContent = noteText; panel.appendChild(p);
    const box = document.createElement("div"); box.className = "unbox";
    box.innerHTML = rows2.map((r) =>
      `<div class="trankrow">${questLink(r.qid)} ` +
      `<span class="chip trscore ${r.score < 0 ? "neg" : "pos"}">${r.score > 0 ? "+" : ""}${r.score}</span> ${effChipHtml(r.goodSrc, r.badSrc)}</div>`).join("");
    panel.appendChild(box);
  };
  const effRows = (iq || []).filter((r) => r.score > 0);
  const ineffRows = (iq || []).filter((r) => r.score < 0);
  if (effRows.length) iqBox(effRows, "Efficient in quests", "Quests where this item's character tags match the quest's efficient tags. Best → worst.");
  if (ineffRows.length) iqBox(ineffRows, "Inefficient in quests", "Quests where this item's character tags match the quest's inefficient tags. Best → worst.");

  for (const a of panel.querySelectorAll("a.knotlink")) {
    a.addEventListener("click", () => {
      const knot = a.dataset.knot;
      if (!knot || !INDEX.knots[knot]) return;
      go("knot", knot);
    });
  }

  enhanceSections(panel);

  $("drawer").hidden = false;
  document.body.style.overflow = "hidden";
}

async function initInventory() {
  const resp = await fetch("inventory.json");
  INV = await resp.json();
  buildInvFilterUI();
  renderInvResults();
}

function idebounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
$("iqq").addEventListener("input", idebounce(() => { INVSTATE.q = $("iqq").value.trim(); _ihair.clear(); renderInvResults(); }, 120));
$("itype").addEventListener("change", () => { INVSTATE.type = $("itype").value; renderInvResults(); });
$("istat").addEventListener("change", () => { INVSTATE.stat = $("istat").value; renderInvResults(); });
$("ipos").addEventListener("change", () => { INVSTATE.pos = $("ipos").checked; renderInvResults(); });
$("itag").addEventListener("change", () => { INVSTATE.tag = $("itag").value; renderInvResults(); });
$("isrc").addEventListener("change", () => { INVSTATE.src = $("isrc").value; renderInvResults(); });
$("iink").addEventListener("change", () => { INVSTATE.iink = $("iink").checked; renderInvResults(); });
$("iex").addEventListener("change", () => { INVSTATE.iex = $("iex").checked; renderInvResults(); });
$("ihs").addEventListener("change", () => { INVSTATE.ihs = $("ihs").checked; renderInvResults(); });
$("icp").addEventListener("change", () => { INVSTATE.icp = $("icp").checked; renderInvResults(); });
$("imat").addEventListener("change", () => { INVSTATE.imat = $("imat").checked; renderInvResults(); });
$("ireset").addEventListener("click", () => {
  Object.assign(INVSTATE, { q: "", type: "", stat: "", pos: false, tag: "", src: "", iink: false, iex: false, ihs: false, icp: false, imat: false });
  $("iqq").value = ""; $("itype").value = ""; $("istat").value = ""; $("itag").value = ""; $("isrc").value = "";
  $("ipos").checked = false; $("iink").checked = false; $("iex").checked = false; $("ihs").checked = false;
  $("icp").checked = false; $("imat").checked = false;
  _ihair.clear();
  renderInvResults();
});

// ---------------------------------------------------------------------------
// Knights tab (the 24 playable knights: stats, features, prefs, dialogues, links)
// ---------------------------------------------------------------------------
let KNIGHTS = null; // dist/knights.json

const KNIGHT_STATS = ["STRENGTH", "AGILITY", "CHARISMA", "MAGIC", "WITS", "LUCK"];
const KFEAT_LABELS = {
  0: "Characteristic", 1: "Quest-type preference", 2: "Condition preference",
};

function kName(stem) {
  const k = KNIGHTS.knights[stem];
  if (!k) return stem;
  return tkey(k.n) || stem;
}

const KSTATE = {
  q: "", loc: "", stat: "", min: 0, tag: "", meal: "", like: "", dislike: "",
  equip: false, hidden: false, alias: false, rom: false, conv: false, story: false, quest: false,
  evo: false, cback: false,
};

function kHaystack(stem, k) {
  const h = [stem, k.ink, k.n, tkey(k.n), k.loc, k.ending,
    k.nu && tkey(k.nu), k.nr && tkey(k.nr)];
  k.st.forEach((v, i) => { if (v) h.push(KNIGHT_STATS[i] + " " + v); });
  for (const g of ["k", "u", "r"]) for (const f of k.feat[g] || []) {
    h.push(f.n); if (f.d) h.push(tkey(f.d));
  }
  k.meals.forEach((m) => h.push("meal " + m + " " + (tkey("MEAL_" + m) || "")));
  k.lt.forEach((t) => h.push("likes " + t)); k.dt.forEach((t) => h.push("dislikes " + t));
  Object.values(k.equip).forEach((s) => h.push("equip " + s + (INV && INV.items[s] ? " " + tkey(INV.items[s].n) : "")));
  Object.values(k.react).flat().forEach((r) => h.push(tkey(r)));
  (k.story || []).forEach((kn) => h.push(kn));
  for (const group of ["qa", "qu", "qr"]) for (const q of k[group]) h.push(q + " " + (QUEST && QUEST.quests[q] ? tkey(QUEST.quests[q].n) : ""));
  for (const [names, knot] of k.conv) { names.forEach((o) => h.push("with " + kName(o))); if (knot) h.push(knot); }
  for (const evo of k.evo || []) {
    h.push(evo.name, evo.trigger, evo.note || "");
    (evo.stats || []).forEach((v, i) => { if (v) h.push(KNIGHT_STATS[i] + " " + v); });
    (evo.features || []).forEach((f) => { h.push(f.n); if (f.d) h.push(tkey(f.d)); });
    if (evo.relic) h.push("relic " + evo.relic);
    (evo.meals || []).forEach((m) => h.push("meal " + m));
    (evo.removes || []).forEach((t) => h.push("loses " + t));
  }
  return h.join(" ").toLowerCase();
}
const _khair = new Map();
function khay(stem, k) {
  let h = _khair.get(stem);
  if (h === undefined) { h = kHaystack(stem, k); _khair.set(stem, h); }
  return h;
}

function visibleKnights() {
  const min = parseInt(KSTATE.min, 10) || 0;
  const statIdx = KSTATE.stat !== "" ? KNIGHT_STATS.indexOf(KSTATE.stat) : -1;
  const out = [];
  for (const [stem, k] of Object.entries(KNIGHTS.knights)) {
    if (KSTATE.loc && k.loc !== KSTATE.loc) continue;
    if (statIdx >= 0 && (k.st[statIdx] || 0) < min) continue;
    if (KSTATE.tag) {
      const has = ["k", "u", "r"].some((g) => (k.feat[g] || []).some((f) => f.t === 0 && f.n === KSTATE.tag));
      if (!has) continue;
    }
    if (KSTATE.meal && !(k.meals || []).includes(KSTATE.meal)) continue;
    if (KSTATE.like && !(k.lt || []).includes(KSTATE.like)) continue;
    if (KSTATE.dislike && !(k.dt || []).includes(KSTATE.dislike)) continue;
    if (KSTATE.equip && !Object.keys(k.equip || {}).length) continue;
    if (KSTATE.hidden && !((k.feat.u || []).length || (k.feat.r || []).length)) continue;
    if (KSTATE.alias && !(k.nu || k.nr)) continue;
    if (KSTATE.rom && !(k.rom && k.rom[1] > 0)) continue;
    if (KSTATE.conv && !(k.conv || []).length) continue;
    if (KSTATE.story && !(k.story || []).length) continue;
    if (KSTATE.quest && !(k.qa.length || k.qu.length || k.qr.length)) continue;
    if (KSTATE.evo && !(k.evo || []).length) continue;
    if (KSTATE.cback && !k.callback) continue;
    if (KSTATE.q && !matchesQuery(khay(stem, k), KSTATE.q)) continue;
    out.push([stem, k]);
  }
  return out;
}

function buildKnightFilterUI() {
  function sel(id, val, opts) {
    const s = $(id);
    s.innerHTML = "";
    const no = document.createElement("option");
    no.value = ""; no.textContent = "Any"; s.appendChild(no);
    for (const o of opts) {
      const el = document.createElement("option");
      el.value = o.value; el.textContent = o.label; s.appendChild(el);
    }
  }
  sel("kstat", "", KNIGHT_STATS.map((s) => ({ value: s, label: s })));
  const locs = new Set(), tags = new Set(), meals = new Set(), likes = new Set(), dislikes = new Set();
  for (const k of Object.values(KNIGHTS.knights)) {
    if (k.loc) locs.add(k.loc);
    for (const g of ["k", "u", "r"]) for (const f of k.feat[g] || []) if (f.t === 0 && f.n) tags.add(f.n);
    (k.meals || []).forEach((m) => meals.add(m));
    (k.lt || []).forEach((t) => likes.add(t));
    (k.dt || []).forEach((t) => dislikes.add(t));
  }
  const locList = [...locs].sort();
  const tagList = [...tags].sort();
  const mealList = [...meals].sort();
  const likeList = [...likes].sort();
  const dislikeList = [...dislikes].sort();
  sel("kloc", "", locList.map((v) => ({ value: v, label: v })));
  sel("ktag", "", tagList.map((v) => ({ value: v, label: v })));
  sel("kmeal", "", mealList.map((v) => ({ value: v, label: v })));
  sel("klike", "", likeList.map((v) => ({ value: v, label: v })));
  sel("kdislike", "", dislikeList.map((v) => ({ value: v, label: v })));
}

function renderKnightResults() {
  const list = visibleKnights().sort((a, b) => kName(a[0]).localeCompare(kName(b[0])) || a[0].localeCompare(b[0]));
  $("kcountline").innerHTML = `<b>${list.length}</b> of ${Object.keys(KNIGHTS.knights).length} knights`;
  const cards = $("kcards");
  cards.innerHTML = "";
  if (!list.length) { cards.innerHTML = `<div class="empty">No knights match — adjust filters above.</div>`; return; }
  const grid = document.createElement("div");
  grid.className = "grid";
  for (const [stem, k] of list) grid.appendChild(knightCard(stem, k));
  cards.appendChild(grid);
}

function knightCard(stem, k) {
  const el = document.createElement("div");
  el.className = "card";
  el.tabIndex = 0;
  const badges = [];
  if (k.loc) badges.push(`<span class="badge loc">${esc(k.loc)}</span>`);
  if (k.lvl > 1) badges.push(`<span class="badge">lvl ${k.lvl}</span>`);
  if (k.arm) badges.push(`<span class="badge st pos">armor ${k.arm}</span>`);
  const mastered = k.mast.length ? `<span class="badge quiet">mastered: ${k.mast.join(", ")}</span>` : "";
  if (k.nu) badges.push(`<span class="badge alias">alias</span>`);
  if (Object.keys(k.equip).length) badges.push(`<span class="badge sp-quest">equip</span>`);
  if (k.conv.length) badges.push(`<span class="badge sp-meals">chats ${k.conv.length}</span>`);
  if (k.story.length) badges.push(`<span class="badge sp-ink">story ${k.story.length}</span>`);
  const questN = k.qa.length + k.qu.length + k.qr.length;
  if (questN) badges.push(`<span class="badge sp-quest">quests ${questN}</span>`);
  const open = () => go("knight", stem);
  el.innerHTML = `
    <div class="top"><span class="name">${esc(kName(stem))}</span>${k.nu ? `<span class="alias-name">${esc(tkey(k.nu))}</span>` : ""}
      <span class="qid">${esc(stem)}</span></div>
    <div class="meta">${badges.join("")}${mastered}</div>`;
  el.addEventListener("click", open);
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return el;
}

function invalidItemsByCid() {
  const m = new Map();
  if (INV) for (const [stem, it] of Object.entries(INV.items)) {
    if (!m.has(it.cid)) m.set(it.cid, stem);
  }
  return m;
}

function invItemLink(kind, stem) {
  if (INV && INV.items[stem]) {
    return `<a class="itemlink" data-kind="${esc(kind)}" data-stem="${esc(stem)}">${esc(tkey(INV.items[stem].n))}</a>`;
  }
  return `<span class="muted">${esc(stem)}</span>`;
}

function openKnightDetail(stem) {
  const k = KNIGHTS.knights[stem];
  if (!k) return;
  const panel = $("drawerpanel");
  panel.innerHTML = "";
  const head = document.createElement("div");
  head.className = "dhead";
  const aliasLine = k.nu ? ` <span class="alias-name">— ${esc(tkey(k.nu))}${k.nr && tkey(k.nr) !== tkey(k.nu) ? " / " + esc(tkey(k.nr)) : ""}</span>` : "";
  head.innerHTML = `<h2>${esc(kName(stem))}</h2>${aliasLine}
    <span class="qidbig">${esc(k.ink)} · ${esc(stem)}</span>
    <button class="close" id="dback" title="back">←</button>
    <button class="close" id="dclose">✕</button>`;
  head.querySelector("#dback").onclick = () => history.back();
  head.querySelector("#dclose").onclick = goClose;
  panel.appendChild(head);

  const chips = document.createElement("div");
  chips.className = "chips";
  if (k.loc) { const s = document.createElement("span"); s.className = "chip tag"; s.textContent = k.loc; chips.appendChild(s); }
  for (const c of [
    "level " + k.lvl, "max armor " + k.arm,
    "affinity " + (k.aff > 0 ? "+" : "") + k.aff + " [" + k.afmin + "…" + k.afmax + "]",
    "demission ≤ " + k.dem,
    "romance " + k.rom[0] + "…" + k.rom[1],
    k.mast.length ? "mastered: " + k.mast.join(", ") : "",
  ].filter(Boolean)) {
    const s = document.createElement("span"); s.className = "chip"; s.textContent = c; chips.appendChild(s);
  }
  panel.appendChild(chips);

  function section(title) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = title; panel.appendChild(h);
  }
  function rows(list, fmt) {
    if (!list || !list.length) return;
    const t = document.createElement("table"); t.className = "qtable";
    for (const [a, b] of list.map(fmt)) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td"); td1.textContent = a; td1.className = "k";
      const td2 = document.createElement("td"); td2.innerHTML = b;
      tr.appendChild(td1); tr.appendChild(td2); t.appendChild(tr);
    }
    panel.appendChild(t);
  }
  function chipsFrom(items, cls) {
    const w = document.createElement("div"); w.className = "chips";
    for (const it of items) {
      const s = document.createElement("span");
      s.className = cls || "chip";
      s.textContent = it;
      w.appendChild(s);
    }
    panel.appendChild(w);
  }

  section("Statistics");
  rows(k.st.map((v, i) => [KNIGHT_STATS[i], v]), ([a, b]) => {
    const mastered = k.mast.includes(a) ? " ★" : "";
    return [a + mastered, `<b class="stat${b > 0 ? " pos" : ""}">${b}</b>`];
  });

  if (k.lt.length || k.dt.length) {
    section("Sovereign preferences");
    if (k.lt.length) chipsFrom(k.lt.map((t) => "likes " + t), "chip pos");
    if (k.dt.length) chipsFrom(k.dt.map((t) => "dislikes " + t), "chip neg");
  }
  if (k.meals.length) {
    section("Liked meals");
    const byCid = invalidItemsByCid();
    const cells = [];
    for (const m of k.meals) {
      const stemIt = byCid.get(m);
      if (stemIt && INV.items[stemIt]) cells.push(invItemLink("M", stemIt));
      else cells.push(esc(m));
    }
    const p = document.createElement("div"); p.className = "qdesc";
    p.innerHTML = cells.join(" · ") || '<span class="muted">—</span>';
    panel.appendChild(p);
  }

  section("Features");
  for (const [group, label] of [["k", "Known"], ["u", "Unknown (to discover)"], ["r", "Intendant rumors"]]) {
    if (!(k.feat[group] || []).length) continue;
    const h = document.createElement("h4"); h.className = "qsec small"; h.textContent = label; panel.appendChild(h);
    for (const f of k.feat[group]) {
      const box = document.createElement("div");
      box.className = "kfeat t" + f.t;
      let name = f.n || "?";
      if (f.t === 1 || f.t === 2) name += " (" + (f.p ? "likes" : "dislikes") + ")";
      const d = f.d ? ` <span class="kfeat-d">${esc(tkey(f.d))}</span>` : "";
      box.innerHTML = `<b class="kfeat-n">${esc(KFEAT_LABELS[f.t] || "feature")}</b> — ${esc(name)}${d}`;
      panel.appendChild(box);
    }
  }

  if (Object.keys(k.equip).length) {
    section("Preferred equipment");
    const byCid = invalidItemsByCid();
    rows([["relic", k.equip.R], ["consumable", k.equip.C], ["mount", k.equip.M]]
      .filter(([, s]) => s), ([a, s]) => [a, invItemLink("E", s)]);
  }

  if (Object.keys(k.react).length) {
    section("Context reactions");
    const list = Object.entries(k.react).sort();
    rows(list, ([ctx, keys]) => [
      ctx,
      keys.map((rk) => `<span class="react-key">${esc(tkey(rk) || rk)}</span>`).join("<br>"),
    ]);
  }

  if (Object.keys(k.afd).length) {
    section("Affinity dialogues");
    rows(Object.entries(k.afd).sort((a, b) => +a[0] - +b[0]),
      ([lvl, knot]) => [`affinity ${lvl}`, knotLink(knot)]);
  }

  if (Object.keys(k.specd).length) {
    section("Special dialogues");
    rows(Object.entries(k.specd).sort(), ([key, knot]) => [key, knotLink(knot)]);
  }

  if ((k.conv || []).length) {
    section("Knight conversations");
    const list = k.conv.map(([names, knot]) => {
      const partners = (names || []).map((o) => kName(o)).join(", ") || "?";
      return [partners, knot ? knotLink(knot) : '<span class="muted">no ink knot</span>'];
    });
    rows(list, (r) => r);
  }

  if ((k.story || []).length) {
    section(`Appears in dialogue (${k.story.length} knots)`);
    const w = document.createElement("div"); w.className = "chips knotchips";
    for (const kn of k.story) {
      const a = document.createElement("a");
      a.className = "chip knobtn";
      a.href = "#";
      a.textContent = kn;
      a.addEventListener("click", (e) => {
        e.preventDefault();
        if (!INDEX.knots[kn]) return;
        go("knot", kn);
      });
      w.appendChild(a);
    }
    panel.appendChild(w);
  }

  const qGroups = [["Granted affinity", k.qa], ["Involved (unexpected outcome)", k.qu], ["Requires the knight", k.qr]];
  const hasQ = qGroups.some(([, q]) => q.length);
  if (hasQ) {
    section("Quests");
    for (const [label, qs] of qGroups) {
      if (!qs.length) continue;
      const h = document.createElement("h4"); h.className = "qsec small"; h.textContent = label; panel.appendChild(h);
      const p = document.createElement("div"); p.className = "qdesc";
      p.innerHTML = qs.map((q) => questLink(q)).join(" · ");
      panel.appendChild(p);
    }
  }

  if ((k.evo || []).length) {
    section("Evolution paths");
    for (const evo of k.evo) {
      const box = document.createElement("div");
      box.className = "evo";
      const bits = [];
      const trigHtml = (SPECIAL && SPECIAL.instructions[evo.trigger])
        ? `<a class="evo-trigger" data-special="${esc(evo.trigger)}" href="#">${esc(evo.trigger)}</a>`
        : `<code class="evo-trigger">${esc(evo.trigger)}</code>`;
      bits.push(trigHtml);
      const statBits = (evo.stats || [])
        .map((v, i) => v ? `${v > 0 ? "+" : ""}${v} ${KNIGHT_STATS[i]}` : "").filter(Boolean);
      if (statBits.length) bits.push(`<span class="chip pos">${statBits.map(esc).join(" · ")}</span>`);
      if (evo.armor) bits.push(`<span class="chip neg">armor ${evo.armor > 0 ? "+" : ""}${evo.armor}</span>`);
      for (const f of evo.features || []) {
        const d = f.d ? ` <span class="kfeat-d">${esc(tkey(f.d))}</span>` : "";
        bits.push(`<span class="chip">${esc(KFEAT_LABELS[f.t] || "feature")}: ${esc(f.n || "?")}${d}</span>`);
      }
      if (evo.relic) {
        const byCid2 = invalidItemsByCid();
        const stemIt = byCid2.get(evo.relic);
        bits.push("<span class=\"chip\">relic " + (stemIt && INV.items[stemIt] ? invItemLink("E", stemIt) : esc(evo.relic)) + "</span>");
      }
      (evo.meals || []).forEach((m) => bits.push(`<span class="chip">meal ${esc(m)}</span>`));
      (evo.removes || []).forEach((t) => bits.push(`<span class="chip neg">loses ${esc(t)}</span>`));
      let html = `<div class="evo-head"><b>${esc(evo.name)}</b> ${bits.join(" ")}</div>`;
      if (evo.note) html += `<div class="qdesc">${esc(evo.note)}</div>`;
      box.innerHTML = html;
      panel.appendChild(box);
    }
  }

  section("Career");
  const career = [];
  if (k.ending) career.push(["ending path", `<code>${esc(k.ending)}</code>`]);
  if (k.demo) career.push(["roundtable demission audience", esc(k.demo)]);
  for (let i = 0; i < (k.death || []).length; i++) career.push(["death follow-up", esc(k.death[i])]);
  if (k.callback) career.push(["call-back audience request", esc(k.callback)]);
  if (k.dflt) career.push(["default description", esc(tkey(k.dflt))]);
  rows(career, (r) => r);

  for (const a of panel.querySelectorAll("a.knotlink")) {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const knot = a.dataset.knot;
      if (!knot || !INDEX.knots[knot]) return;
      go("knot", knot);
    });
  }
  for (const a of panel.querySelectorAll("a.itemlink")) {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const stem2 = a.dataset.stem;
      if (!INV || !INV.items[stem2]) return;
      go("inv", stem2);
    });
  }
  for (const a of panel.querySelectorAll("a.evo-trigger")) {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const name = a.dataset.special;
      if (!SPECIAL || !SPECIAL.instructions[name]) return;
      go("special", name);
    });
  }

  enhanceSections(panel);

  panel.scrollTop = 0;
  $("drawer").hidden = false;
  document.body.style.overflow = "hidden";
}

function knotLink(knot) {
  const s = String(knot);
  if (INDEX && INDEX.knots[s]) {
    return `<a class="knotlink" data-knot="${esc(s)}">${esc(s)}</a>`;
  }
  return esc(s);
}

async function initKnights() {
  const resp = await fetch("knights.json");
  KNIGHTS = await resp.json();
  buildKnightFilterUI();
  renderKnightResults();
}

function kdebounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
$("kqq").addEventListener("input", kdebounce(() => { KSTATE.q = $("kqq").value.trim(); _khair.clear(); renderKnightResults(); }, 120));
$("kloc").addEventListener("change", () => { KSTATE.loc = $("kloc").value; renderKnightResults(); });
$("kstat").addEventListener("change", () => { KSTATE.stat = $("kstat").value; renderKnightResults(); });
$("kmin").addEventListener("input", kdebounce(() => { KSTATE.min = $("kmin").value; renderKnightResults(); }, 120));
$("ktag").addEventListener("change", () => { KSTATE.tag = $("ktag").value; renderKnightResults(); });
$("kmeal").addEventListener("change", () => { KSTATE.meal = $("kmeal").value; renderKnightResults(); });
$("klike").addEventListener("change", () => { KSTATE.like = $("klike").value; renderKnightResults(); });
$("kdislike").addEventListener("change", () => { KSTATE.dislike = $("kdislike").value; renderKnightResults(); });
$("kequip").addEventListener("change", () => { KSTATE.equip = $("kequip").checked; renderKnightResults(); });
$("khidden").addEventListener("change", () => { KSTATE.hidden = $("khidden").checked; renderKnightResults(); });
$("kalias").addEventListener("change", () => { KSTATE.alias = $("kalias").checked; renderKnightResults(); });
$("krom").addEventListener("change", () => { KSTATE.rom = $("krom").checked; renderKnightResults(); });
$("kconv").addEventListener("change", () => { KSTATE.conv = $("kconv").checked; renderKnightResults(); });
$("kstory").addEventListener("change", () => { KSTATE.story = $("kstory").checked; renderKnightResults(); });
$("kquest").addEventListener("change", () => { KSTATE.quest = $("kquest").checked; renderKnightResults(); });
$("kevo").addEventListener("change", () => { KSTATE.evo = $("kevo").checked; renderKnightResults(); });
$("kcback").addEventListener("change", () => { KSTATE.cback = $("kcback").checked; renderKnightResults(); });
$("kreset").addEventListener("click", () => {
  Object.assign(KSTATE, { q: "", loc: "", stat: "", min: 0, tag: "", meal: "", like: "", dislike: "",
    equip: false, hidden: false, alias: false, rom: false, conv: false, story: false, quest: false,
    evo: false, cback: false });
  $("kqq").value = ""; $("kloc").value = ""; $("kstat").value = ""; $("kmin").value = "";
  $("ktag").value = ""; $("kmeal").value = ""; $("klike").value = ""; $("kdislike").value = "";
  for (const id of ["kequip", "khidden", "kalias", "krom", "kconv", "kstory", "kquest", "kevo", "kcback"]) $(id).checked = false;
  _khair.clear();
  renderKnightResults();
});

// ---------------------------------------------------------------------------
// Special tab (SpecialInstruction catalog: game director switches)
// ---------------------------------------------------------------------------
let SPECIAL = null; // dist/special.json

const SSTATE = { q: "", knight: "", ink: false, quest: false, evo: false };

function sOwner(stem) { return KNIGHTS && KNIGHTS.knights[stem] ? kName(stem) : stem; }

function sHaystack(name, i) {
  const h = [name, i.signal || "", i.note || "", i.knight ? sOwner(i.knight) : "", i.knight || ""];
  for (const k of i.knots || []) h.push(k);
  for (const q of i.quests || []) h.push(q + " " + (QUEST && QUEST.quests[q] ? tkey(QUEST.quests[q].n) : ""));
  for (const k of i.dlg || []) h.push(k);
  for (const k of i.goto || []) h.push(k);
  for (const a of i.auds || []) {
    h.push(a);
    const au = AUDIENCE && AUDIENCE.audiences[a];
    if (au) for (const c of au.c || []) h.push(tkey(c));
    for (const f of (AUDIENCE && AUDIENCE.rev.qf && AUDIENCE.rev.qf[a]) || []) h.push(f.q);
  }
  for (const c of i.affects || []) h.push(c, sOwner(c));
  for (const v of i.vars || []) h.push(v);
  if (i.ending) h.push(i.ending);
  return h.join(" ").toLowerCase();
}
const _shair = new Map();
function shay(name, i) {
  let h = _shair.get(name);
  if (h === undefined) { h = sHaystack(name, i); _shair.set(name, h); }
  return h;
}

function visibleSpecials() {
  const out = [];
  for (const [name, i] of Object.entries(SPECIAL.instructions)) {
    const evo = !!i.knight;
    if (SSTATE.knight && i.knight !== SSTATE.knight) continue;
    if (SSTATE.ink && !(i.knots || []).length) continue;
    if (SSTATE.quest && !(i.quests || []).length) continue;
    if (SSTATE.evo && !evo) continue;
    if (SSTATE.q && !matchesQuery(shay(name, i), SSTATE.q)) continue;
    out.push([name, i]);
  }
  return out;
}

function renderSpecialResults() {
  const list = visibleSpecials().sort((a, b) => a[0].localeCompare(b[0]));
  $("scountline").innerHTML = `<b>${list.length}</b> of ${Object.keys(SPECIAL.instructions).length} special instructions`;
  const cards = $("scards");
  cards.innerHTML = "";
  if (!list.length) { cards.innerHTML = `<div class="empty">No instructions match — adjust filters above.</div>`; return; }
  const grid = document.createElement("div");
  grid.className = "grid";
  for (const [name, i] of list) {
    const el = document.createElement("div");
    el.className = "card";
    el.tabIndex = 0;
    const badges = [];
    if (i.knight) badges.push(`<span class="badge sp-quest">evolution · ${esc(sOwner(i.knight))}</span>`);
    if ((i.knots || []).length) badges.push(`<span class="badge sp-ink">ink ${i.knots.length}</span>`);
    if ((i.quests || []).length) badges.push(`<span class="badge sp-meals">quests ${i.quests.length}</span>`);
    if ((i.dlg || []).length) badges.push(`<span class="badge sp-ink">unlocks ${i.dlg.length}</span>`);
    if ((i.goto || []).length) badges.push(`<span class="badge sp-ink">diverts ${i.goto.length}</span>`);
    if ((i.auds || []).length) badges.push(`<span class="badge aud" title="${esc(i.auds.join(", "))}">audiences ${i.auds.length}</span>`);
    if ((i.cond || []).length) badges.push(`<span class="badge sp-quest" title="${esc(i.cond.join(" · "))}">conditional</span>`);
    if ((i.affects || []).length) badges.push(`<span class="badge sp-quest" title="affects ${esc(i.affects.map(sOwner).join(", "))}">affects ${i.affects.length}</span>`);
    if (i.signal) badges.push(`<span class="badge quiet">${esc(i.signal)}</span>`);
    const open = () => go("special", name);
    el.innerHTML = `
      <div class="top"><span class="name">${esc(name)}</span></div>
      ${i.note ? `<div class="prev">${esc(i.note)}</div>` : ""}
      <div class="meta">${badges.join("")}</div>`;
    el.addEventListener("click", open);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    grid.appendChild(el);
  }
  cards.appendChild(grid);
}

function openSpecialDetail(name) {
  const i = SPECIAL.instructions[name];
  if (!i) return;
  const panel = $("drawerpanel");
  panel.innerHTML = "";
  const head = document.createElement("div");
  head.className = "dhead";
  head.innerHTML = `<h2>${esc(name)}</h2><span class="qidbig">SpecialInstruction${i.signal ? " · " + esc(i.signal) : ""}</span>
    <button class="close" id="dback" title="back">←</button>
    <button class="close" id="dclose">✕</button>`;
  head.querySelector("#dback").onclick = () => history.back();
  head.querySelector("#dclose").onclick = goClose;
  panel.appendChild(head);

  const chips = document.createElement("div");
  chips.className = "chips";
  if (i.knight) {
    const s = document.createElement("span");
    s.className = "chip tag";
    s.textContent = "owner " + sOwner(i.knight);
    chips.appendChild(s);
  }
  if ((i.knots || []).length) {
    const s = document.createElement("span"); s.className = "chip"; s.textContent = "inked in " + i.knots.length + " knots"; chips.appendChild(s);
  }
  if ((i.quests || []).length) {
    const s = document.createElement("span"); s.className = "chip"; s.textContent = "granted by " + i.quests.length + " quests"; chips.appendChild(s);
  }
  panel.appendChild(chips);

  if (i.note) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Effect"; panel.appendChild(h);
    const d = document.createElement("div"); d.className = "qdesc"; d.textContent = i.note; panel.appendChild(d);
  }

  if ((i.cond || []).length) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Firing conditions"; panel.appendChild(h);
    const d = document.createElement("div"); d.className = "qdesc";
    d.textContent = "This instruction only fires when:";
    panel.appendChild(d);
    for (const c of i.cond) {
      const box = document.createElement("div");
      box.className = "qchip";
      box.innerHTML = `<span class="qchip-sub">${esc(c)}</span>`;
      panel.appendChild(box);
    }
  }

  if ((i.knots || []).length) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Emitted by (ink knots)"; panel.appendChild(h);
    const w = document.createElement("div"); w.className = "chips knotchips";
    for (const kn of i.knots) {
      const a = document.createElement("a");
      a.className = "chip knobtn";
      a.href = "#";
      a.textContent = kn;
      a.dataset.knot = kn;
      a.addEventListener("click", (e) => {
        e.preventDefault();
        if (!INDEX.knots[kn]) return;
        go("knot", kn);
      });
      w.appendChild(a);
    }
    panel.appendChild(w);
  }

  if ((i.quests || []).length) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Granted by (quests)"; panel.appendChild(h);
    const d = document.createElement("div"); d.className = "qdesc";
    d.innerHTML = i.quests.map((q) => questLink(q)).join(" · ");
    panel.appendChild(d);
  }

  if ((i.dlg || []).length) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Unlocks special dialogue (knots)"; panel.appendChild(h);
    const w = document.createElement("div"); w.className = "chips knotchips";
    for (const kn of i.dlg) {
      const a = document.createElement("a");
      a.className = "chip knobtn";
      a.href = "#";
      a.textContent = kn;
      a.dataset.knot = kn;
      a.addEventListener("click", (e) => { e.preventDefault(); if (INDEX.knots[kn]) go("knot", kn); });
      w.appendChild(a);
    }
    panel.appendChild(w);
  }

  if ((i.goto || []).length) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Diverts to (ink knots)"; panel.appendChild(h);
    const w = document.createElement("div"); w.className = "chips knotchips";
    for (const kn of i.goto) {
      if (!INDEX.knots[kn]) continue;
      const a = document.createElement("a");
      a.className = "chip knobtn";
      a.href = "#";
      a.textContent = kn;
      a.dataset.knot = kn;
      a.addEventListener("click", (e) => { e.preventDefault(); go("knot", kn); });
      w.appendChild(a);
    }
    panel.appendChild(w);
  }

  if (i.ending) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Ending path"; panel.appendChild(h);
    const d = document.createElement("div"); d.className = "qdesc";
    d.textContent = i.ending;
    panel.appendChild(d);
  }

  if ((i.affects || []).length) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Affects (characters)"; panel.appendChild(h);
    const d = document.createElement("div"); d.className = "qdesc";
    d.innerHTML = i.affects.map((c) => knightLink(c)).join(" · ");
    panel.appendChild(d);
  }

  if ((i.auds || []).length) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Schedules (audiences)"; panel.appendChild(h);
    const d = document.createElement("div"); d.className = "qdesc";
    d.innerHTML = i.auds.map(audienceLink).join(" · ");
    panel.appendChild(d);
  }

  if ((i.vars || []).length) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Sets story variables"; panel.appendChild(h);
    const d = document.createElement("div"); d.className = "qdesc";
    d.textContent = i.vars.join(", ");
    panel.appendChild(d);
  }

  if (i.knight) {
    const h = document.createElement("h4"); h.className = "qsec"; h.textContent = "Owner knight"; panel.appendChild(h);
    const d = document.createElement("div"); d.className = "qdesc";
    const k = KNIGHTS.knights[i.knight];
    d.innerHTML = k ? `<a class="questlink" data-knight="${esc(i.knight)}">${esc(kName(i.knight))}</a>` : esc(i.knight);
    panel.appendChild(d);
  }

  for (const a of panel.querySelectorAll('a[data-knight]')) {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      go("knight", a.dataset.knight);
    });
  }
  for (const a of panel.querySelectorAll("a.questlink")) {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const q = a.dataset.qid;
      if (!QUEST || !QUEST.quests[q]) return;
      go("quest", q);
    });
  }

  enhanceSections(panel);

  panel.scrollTop = 0;
  $("drawer").hidden = false;
  document.body.style.overflow = "hidden";
}

function buildSpecialFilterUI() {
  const sel = $("sknight");
  sel.innerHTML = "";
  const no = document.createElement("option");
  no.value = ""; no.textContent = "Any"; sel.appendChild(no);
  const owners = new Set();
  for (const i of Object.values(SPECIAL.instructions)) if (i.knight) owners.add(i.knight);
  for (const stem of [...owners].sort()) {
    const el = document.createElement("option");
    el.value = stem; el.textContent = sOwner(stem); sel.appendChild(el);
  }
}

async function initSpecial() {
  const resp = await fetch("special.json");
  SPECIAL = await resp.json();
  buildSpecialFilterUI();
  renderSpecialResults();
}

const sdebounce = kdebounce;
$("sqq").addEventListener("input", sdebounce(() => {
  SSTATE.q = $("sqq").value.trim();
  _shair.clear();
  renderSpecialResults();
}, 120));
$("sknight").addEventListener("change", () => { SSTATE.knight = $("sknight").value; renderSpecialResults(); });
$("sink").addEventListener("change", () => { SSTATE.ink = $("sink").checked; renderSpecialResults(); });
$("squest").addEventListener("change", () => { SSTATE.quest = $("squest").checked; renderSpecialResults(); });
$("sevo").addEventListener("change", () => { SSTATE.evo = $("sevo").checked; renderSpecialResults(); });
$("sreset").addEventListener("click", () => {
  Object.assign(SSTATE, { q: "", knight: "", ink: false, quest: false, evo: false });
  $("sqq").value = ""; $("sknight").value = "";
  for (const id of ["sink", "squest", "sevo"]) $(id).checked = false;
  _shair.clear();
  renderSpecialResults();
});

// ---------------------------------------------------------------------------
// Audiences tab (511 audiences + 34 audience requests)
// ---------------------------------------------------------------------------
let AUDIENCE = null; // dist/audiences.json

const ASTATE = { q: "", view: "aud", folder: "", char: "", cond: false, quest: false, audreq: false, reqgrant: false };

function aRequestName(stem) {
  const r = AUDIENCE && AUDIENCE.requests[stem];
  return r ? (tkey(r.n) || stem) : stem;
}
function requestLink(stem) {
  const s = String(stem);
  if (AUDIENCE && AUDIENCE.requests[s]) {
    const name = aRequestName(s);
    const inner = (name && name !== s) ? `${esc(name)} <span class="mut">${esc(s)}</span>` : esc(s);
    return `<a class="reqlink" data-req="${esc(s)}" title="open request ${esc(s)}">${inner}</a>`;
  }
  return esc(s);
}
function audienceLink(stem) {
  const s = String(stem);
  if (AUDIENCE && AUDIENCE.audiences[s]) {
    const a = AUDIENCE.audiences[s];
    const nm = a.c && a.c.length ? a.c.map(tkey).filter(Boolean).join(", ") : s;
    const inner = (nm && nm !== s) ? `${esc(nm)} <span class="mut">${esc(s)}</span>` : esc(s);
    return `<a class="audiencelink" data-aud="${esc(s)}" title="open audience ${esc(s)}">${inner}</a>`;
  }
  return esc(s);
}

function aHaystack(stem, a) {
  const h = [stem, a.k || "", a.f || ""];
  for (const c of a.c || []) h.push(c, tkey(c));
  for (const rq of a.rq || []) h.push(audienceReqText(rq).replace(/<[^>]+>/g, " "));
  for (const f of (AUDIENCE.rev.qf[stem] || [])) {
    h.push(f.q);
    const q = QUEST && QUEST.quests[f.q];
    if (q) h.push(tkey(q.n));
  }
  if (a.cyc && a.cyc.length) h.push("cycle " + a.cyc.join(" "));
  const ci = a.ci;
  if (ci && ci.length) {
    h.push("county introduction", "introduction", ci[0], tkey(ci[1]));
    h.push("act 2", "act 3", "neighboring county", "rallied");
  }
  for (const d of a.dir || []) h.push(d);
  for (const d of a.dd || []) {
    h.push(d[0], kName(d[0]), d[1], DEMISSION_VARIANT[d[2]] || "");
    h.push(d[1] === "death" ? "dies" : "leaves the roundtable");
  }
  const fl = a.fl;
  if (fl && fl.length) {
    h.push(fl[0], "filler", "filler scene", "random pick", "corruption-weighted");
    if (fl[1] != null) h.push(FILLER_POP_LABELS[fl[1]] || ("population " + fl[1]));
    if (fl[2] != null) h.push("corruption tier " + fl[2]);
    for (const k of fillerPackUnlocks().get(fl[0]) || []) h.push("unlocked by " + k, k);
  }
  for (const [rstem, r] of Object.entries(AUDIENCE.requests)) {
    if (r.fua === stem) { h.push(rstem, tkey(r.n), tkey(r.d)); }
  }
  return h.join(" ").toLowerCase();
}
const _ahair = new Map();
function ahay(stem, a) {
  let h = _ahair.get(stem);
  if (h === undefined) { h = aHaystack(stem, a); _ahair.set(stem, h); }
  return h;
}

function rHaystack(stem, r) {
  const h = [stem, tkey(r.n), r.n, tkey(r.d), r.d];
  if (r.ch) h.push(r.ch, tkey(r.ck));
  if (r.cb) {
    h.push("call-back", "callback", "call back", "leaves the roundtable", "invite back", "offer to return");
  }
  if (r.fua) {
    h.push(r.fua);
    const a = AUDIENCE && AUDIENCE.audiences[r.fua];
    if (a) h.push(a.k || "");
  }
  for (const q of r.q || []) {
    h.push(q);
    const rec = QUEST && QUEST.quests[q];
    if (rec) h.push(tkey(rec.n));
  }
  return h.join(" ").toLowerCase();
}
const _rhair = new Map();
function rhay(stem, r) {
  let h = _rhair.get(stem);
  if (h === undefined) { h = rHaystack(stem, r); _rhair.set(stem, h); }
  return h;
}

function visibleAudiences() {
  const out = [];
  for (const [stem, a] of Object.entries(AUDIENCE.audiences)) {
    if (ASTATE.folder && a.f !== ASTATE.folder) continue;
    if (ASTATE.char && !(a.c || []).includes(ASTATE.char)) continue;
    if (ASTATE.cond && !(a.rq || []).length) continue;
    if (ASTATE.quest && !(AUDIENCE.rev.qf[stem] || []).length) continue;
    if (ASTATE.audreq && !reqsFor(stem).length) continue;
    if (ASTATE.q && !matchesQuery(ahay(stem, a), ASTATE.q)) continue;
    out.push([stem, a]);
  }
  return out;
}

function visibleRequests() {
  const out = [];
  for (const [stem, r] of Object.entries(AUDIENCE.requests)) {
    if (ASTATE.char && r.ck !== ASTATE.char) continue;
    if (ASTATE.reqgrant && !(r.q || []).length) continue;
    if (ASTATE.q && !matchesQuery(rhay(stem, r), ASTATE.q)) continue;
    out.push([stem, r]);
  }
  return out;
}

function reqsFor(stem) {
  const out = [];
  for (const [rstem, r] of Object.entries(AUDIENCE.requests)) {
    if (r.fua === stem) out.push(rstem);
  }
  return out;
}

function audCard(stem, a) {
  const el = document.createElement("div");
  el.className = "card";
  el.tabIndex = 0;
  const badges = [];
  badges.push(`<span class="badge aud">${esc(a.f)}</span>`);
  if (a.cyc && a.cyc.length) {
    badges.push(`<span class="badge cyc" title="hardcoded to play at cycle ${esc(a.cyc.join("/"))}">cycle ${esc(a.cyc.join("/"))}</span>`);
  }
  if ((a.rq || []).length) {
    badges.push(`<span class="badge sp-quest" title="${esc(a.rq.map(audienceReqText).join(", "))}">${a.rq.length} condition${a.rq.length > 1 ? "s" : ""}</span>`);
  }
  const fu = AUDIENCE.rev.qf[stem] || [];
  if (fu.length) {
    const qid = fu[0].q;
    const nm = QUEST && QUEST.quests[qid] ? (tkey(QUEST.quests[qid].n) || qid) : qid;
    badges.push(`<span class="badge quest" title="fires after ${esc(qid)} (${fu.map((f) => f.kind).join(", ")})">↳ ${esc(nm)}</span>`);
  }
  if (a.fl && a.fl.length) {
    badges.push(`<span class="badge filler" title="filler scene of the ${esc(a.fl[0])} pack — random pick to fill a cycle, corruption-weighted">filler · ${esc(a.fl[0])}</span>`);
  }
  if (a.ci && a.ci.length) {
    const cn = esc(tkey(a.ci[1]) || a.ci[0]);
    badges.push(`<span class="badge cyc" title="county introduction of ${cn} — scheduled when act 2/3 starts or when a neighboring county is rallied">county intro · ${cn}</span>`);
  }
  const rqstems = reqsFor(stem);
  if (rqstems.length) badges.push(`<span class="badge req" title="${esc(rqstems.join(", "))}">request · ${esc(rqstems.join(", "))}</span>`);
  if (a.k && !INDEX.knots[a.k]) badges.push(`<span class="badge knotless">no knot</span>`);
  const chars = (a.c || []).map(tkey).filter(Boolean);
  const open = () => go("aud", stem);
  el.innerHTML = `
    <div class="top"><span class="name">${esc(stem)}</span></div>
    ${chars.length ? `<div class="prev">${esc(chars.join(", "))}</div>` : ""}
    <div class="meta">${badges.join("")}</div>`;
  el.addEventListener("click", open);
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return el;
}

function reqCard(stem, r) {
  const el = document.createElement("div");
  el.className = "card";
  el.tabIndex = 0;
  const badges = [`<span class="badge req">request</span>`];
  if (r.cb) badges.push(`<span class="badge cb" title="call-back request — offered when ${esc(tkey(r.ck) || r.ch)} leaves the roundtable, to invite them back">call-back</span>`);
  badges.push(`<span class="badge cost">${r.cst} gold</span>`);
  if (r.ch) badges.push(`<span class="badge quiet">${esc(tkey(r.ck) || r.ch)}</span>`);
  if (r.hd) badges.push(`<span class="badge sp-none">hidden</span>`);
  if ((r.q || []).length) badges.push(`<span class="badge sp-quest">granted by ${r.q.length} quest${r.q.length > 1 ? "s" : ""}</span>`);
  const open = () => go("areq", stem);
  el.innerHTML = `
    <div class="top"><span class="name">${esc(aRequestName(stem))}</span><span class="qid">${esc(stem)}</span></div>
    ${r.d ? `<div class="prev">${esc(tkey(r.d))}</div>` : ""}
    <div class="meta">${badges.join("")}</div>`;
  el.addEventListener("click", open);
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return el;
}

function renderAudienceResults() {
  if (!AUDIENCE) return;
  const req = ASTATE.view === "req";
  const list = req
    ? visibleRequests().sort((a, b) => aRequestName(a[0]).localeCompare(aRequestName(b[0])))
    : visibleAudiences().sort((a, b) => a[0].localeCompare(b[0]));
  const total = req ? Object.keys(AUDIENCE.requests).length : Object.keys(AUDIENCE.audiences).length;
  $("acountline").innerHTML = `<b>${list.length}</b> of ${total} ${req ? "requests" : "audiences"}`;
  const cards = $("acards");
  cards.innerHTML = "";
  if (!list.length) { cards.innerHTML = `<div class="empty">Nothing matches — adjust filters above.</div>`; return; }
  const grid = document.createElement("div");
  grid.className = "grid";
  for (const [stem, rec] of list) grid.appendChild(req ? reqCard(stem, rec) : audCard(stem, rec));
  cards.appendChild(grid);
}

function openAudienceDetail(stem) {
  const a = AUDIENCE.audiences[stem];
  if (!a) return;
  const panel = $("drawerpanel");
  panel.innerHTML = "";
  const head = document.createElement("div");
  head.className = "dhead";
  head.innerHTML = `<h2>${esc(stem)}</h2><span class="qidbig">audience · ${esc(a.f)}</span>
    <button class="close" id="dback" title="back">←</button>
    <button class="close" id="dclose">✕</button>`;
  head.querySelector("#dback").onclick = () => history.back();
  head.querySelector("#dclose").onclick = goClose;
  panel.appendChild(head);

  const chips = document.createElement("div");
  chips.className = "chips";
  for (const c of a.c || []) {
    const s = document.createElement("span");
    s.className = "chip tag";
    s.textContent = tkey(c) || c;
    chips.appendChild(s);
  }
  const fu = AUDIENCE.rev.qf[stem] || [];
  const rqstems = reqsFor(stem);
  for (const c of [
    (a.rq || []).length ? `${a.rq.length} condition${a.rq.length > 1 ? "s" : ""}` : "",
    fu.length ? `fires after ${fu.length} quest${fu.length > 1 ? "s" : ""}` : "",
    rqstems.length ? `triggered by ${rqstems.length} request${rqstems.length > 1 ? "s" : ""}` : "",
    a.ci && a.ci.length ? `county introduction of ${tkey(a.ci[1]) || a.ci[0]}` : "",
  ].filter(Boolean)) {
    const s = document.createElement("span");
    s.className = "chip";
    s.textContent = c;
    chips.appendChild(s);
  }
  panel.appendChild(chips);

  const section = (t) => {
    const h = document.createElement("h4");
    h.className = "qsec";
    h.textContent = t;
    panel.appendChild(h);
  };

  section("Plays as ink knot");
  if (a.k && INDEX.knots[a.k]) {
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = knotLink(a.k);
    panel.appendChild(d);
  } else {
    const p = document.createElement("p");
    p.className = "qdesc muted";
    p.textContent = a.k ? `No ink knot named "${a.k}" exists in the story (variant / dead content).` : "This audience carries no ink_path.";
    panel.appendChild(p);
  }

  if (a.c && a.c.length) {
    section("Characters");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.textContent = a.c.map((c) => tkey(c) || c).join(", ");
    panel.appendChild(d);
  }

  if (a.ci && a.ci.length) {
    section("County introduction");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = countyIntroSource(a);
    const p = document.createElement("p");
    p.className = "qdesc muted";
    p.textContent = "This is the scene that introduces the county. The ActManager is the only scheduler: at each act 1→2 / 2→3 transition the act's county intros are queued a few cycles in (per-neighbor shuffle delay, brimwood first), and when a county is rallied the introductions of its not-yet-introduced neighbors follow.";
    panel.appendChild(d);
    panel.appendChild(p);
  }

  const scheds = doleanceSchedulers().get(stem);
  if (scheds && scheds.length) {
    section("Scheduled as doleance by");
    const w = document.createElement("div");
    w.className = "qdesc";
    w.innerHTML = scheds.map((s) => INDEX.knots[s.knot]
      ? `<a class="knotlink" data-knot="${esc(s.knot)}">${esc(s.knot)}</a> <span class="muted">(${esc(s.type)})</span>`
      : `${esc(s.knot)} <span class="muted">(${esc(s.type)})</span>`).join(" · ");
    panel.appendChild(w);
  }

  const spBy = audSpecials().get(stem);
  if (spBy && spBy.length) {
    section("Scheduled by special instruction");
    const w = document.createElement("div");
    w.className = "qdesc";
    w.innerHTML = [...new Set(spBy)].map((n) => `<a class="speciallink" data-special="${esc(n)}">${esc(n)}</a>`).join(" · ");
    panel.appendChild(w);
  }

  if (a.dir && a.dir.length) {
    section("Directed by the game director");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = a.dir.map(esc).join("<br>");
    panel.appendChild(d);
  }

  if (a.fl && a.fl.length) {
    section("Filler scene");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = fillerSource(stem, a);
    const p = document.createElement("p");
    p.className = "qdesc muted";
    p.textContent = "Unlocked packs fill random free cycle slots during a cycle fill (weighted toward the current corruption tier); one audience is picked per pack and removed once played.";
    panel.appendChild(d);
    panel.appendChild(p);
  }

  if (a.cyc && a.cyc.length) {
    section("Hardcoded to play at cycle");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.textContent = `This scene is scripted into the cycle timeline (cycle ${a.cyc.join(", ")}) — it fires at that point regardless of player actions.`;
    panel.appendChild(d);
  }

  if (a.rq && a.rq.length) {
    section("Firing conditions");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = a.rq.map(audienceReqText).join("<br>");
    panel.appendChild(d);
  }

  if (a.dd && a.dd.length) {
    const deaths = a.dd.filter((d) => d[1] === "death");
    const dems = a.dd.filter((d) => d[1] === "demission");
    if (deaths.length) {
      section("Fires when a knight dies");
      const w = document.createElement("div");
      w.className = "qdesc";
      w.innerHTML = deaths.map((d) => {
        const who = (KNIGHTS && KNIGHTS.knights[d[0]]) ? knightLink(d[0]) : esc(kName(d[0]));
        return `Fires when ${who} dies — queued for the next cycle by the death follow-up (the scene is erased from played_audiences first so it can re-fire).`;
      }).join("<br>");
      panel.appendChild(w);
    }
    if (dems.length) {
      section("Fires when a knight leaves the roundtable");
      const w = document.createElement("div");
      w.className = "qdesc";
      w.innerHTML = dems.map((d) => {
        const who = (KNIGHTS && KNIGHTS.knights[d[0]]) ? knightLink(d[0]) : esc(kName(d[0]));
        return `Fires when ${who} leaves the roundtable (demission) — queued at the next cycle reset once the knight's affinity drops to its demission threshold${DEMISSION_VARIANT[d[2]] || ""}.`;
      }).join("<br>");
      panel.appendChild(w);
    }
  }

  if (fu.length) {
    section("Fires after");
    const w = document.createElement("div");
    w.className = "qdesc";
    w.innerHTML = fu.map((f) => `${questLink(f.q)} <span class="muted">(${esc(f.k)})</span>`).join(" · ");
    panel.appendChild(w);
  }

  if (rqstems.length) {
    section("Triggered by request");
    for (const rs of rqstems) {
      const r = AUDIENCE.requests[rs];
      if (!r) continue;
      const box = document.createElement("div");
      box.className = "qchip";
      const parts = [requestLink(rs)];
      if (r.d) parts.push(`<span class="qchip-sub">${esc(tkey(r.d))}</span>`);
      if (r.ch) parts.push(`<span class="qchip-sub">${esc(tkey(r.ck) || r.ch)}</span>`);
      box.innerHTML = parts.join(" — ");
      panel.appendChild(box);
    }
  }

  enhanceSections(panel);

  panel.scrollTop = 0;
  $("drawer").hidden = false;
  document.body.style.overflow = "hidden";
}

function openRequestDetail(stem) {
  const r = AUDIENCE.requests[stem];
  if (!r) return;
  const panel = $("drawerpanel");
  panel.innerHTML = "";
  const head = document.createElement("div");
  head.className = "dhead";
  head.innerHTML = `<h2>${esc(aRequestName(stem))}</h2><span class="qidbig">${esc(stem)}</span>
    <button class="close" id="dback" title="back">←</button>
    <button class="close" id="dclose">✕</button>`;
  head.querySelector("#dback").onclick = () => history.back();
  head.querySelector("#dclose").onclick = goClose;
  panel.appendChild(head);

  const chips = document.createElement("div");
  chips.className = "chips";
  for (const c of [
    `${r.cst} gold`,
    r.cb ? "call-back request" : "",
    r.hd ? "character hidden" : "",
    r.ch ? `character ${tkey(r.ck) || r.ch}` : "",
    (r.q || []).length ? `granted by ${r.q.length} quest${r.q.length > 1 ? "s" : ""}` : "",
  ].filter(Boolean)) {
    const s = document.createElement("span");
    s.className = "chip";
    s.textContent = c;
    chips.appendChild(s);
  }
  panel.appendChild(chips);

  const section = (t) => {
    const h = document.createElement("h4");
    h.className = "qsec";
    h.textContent = t;
    panel.appendChild(h);
  };

  if (r.d) {
    section("Description");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = rich(tkey(r.d));
    panel.appendChild(d);
  }

  if (r.ch) {
    section("Character");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = (KNIGHTS && KNIGHTS.knights[r.ch]) ? knightLink(r.ch) : esc(tkey(r.ck) || r.ch);
    panel.appendChild(d);
  }

  if (r.cb) {
    section("Call-back");
    const d = document.createElement("div");
    d.className = "qdesc";
    const who = (KNIGHTS && KNIGHTS.knights[r.ch]) ? knightLink(r.ch) : esc(tkey(r.ck) || r.ch);
    d.innerHTML = `Unlocked when ${who} leaves the roundtable — a call-back request offering to invite them back.`;
    panel.appendChild(d);
  }

  const fua = r.fua && AUDIENCE.audiences[r.fua];
  if (fua) {
    section("Follow-up audience");
    const d = document.createElement("div");
    d.className = "qdesc";
    const parts = [audienceLink(r.fua)];
    if (fua.k && INDEX.knots[fua.k]) parts.push(knotLink(fua.k));
    d.innerHTML = parts.join(" ");
    panel.appendChild(d);
  }

  if (r.rem && r.rem.length) {
    section("Audiences to remove");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = r.rem.map(audienceLink).join(" · ");
    panel.appendChild(d);
  }

  if (r.exc && r.exc.length) {
    section("Excluded when played");
    const p = document.createElement("p");
    p.className = "qdesc muted";
    p.textContent = "The request is not offered once the following audience has played:";
    panel.appendChild(p);
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = r.exc.map(audienceLink).join(" · ");
    panel.appendChild(d);
  }

  if (r.q && r.q.length) {
    section("Granted by quests");
    const d = document.createElement("div");
    d.className = "qdesc";
    d.innerHTML = r.q.map((q) => questLink(q)).join(" · ");
    panel.appendChild(d);
  }

  enhanceSections(panel);

  panel.scrollTop = 0;
  $("drawer").hidden = false;
  document.body.style.overflow = "hidden";
}

function buildAudienceFilterUI() {
  if (!AUDIENCE) return;
  const folders = new Set();
  const chars = new Set();
  for (const a of Object.values(AUDIENCE.audiences)) {
    folders.add(a.f);
    for (const c of a.c || []) chars.add(c);
  }
  for (const r of Object.values(AUDIENCE.requests)) {
    if (r.ck) chars.add(r.ck);
  }
  const fsel = $("afolder");
  const fkeep = fsel.value;
  fsel.innerHTML = "";
  const fno = document.createElement("option");
  fno.value = ""; fno.textContent = "Any"; fsel.appendChild(fno);
  for (const f of [...folders].sort()) {
    const o = document.createElement("option");
    o.value = f; o.textContent = f; fsel.appendChild(o);
  }
  fsel.value = fkeep;
  const csel = $("achar");
  const ckeep = csel.value;
  csel.innerHTML = "";
  const cno = document.createElement("option");
  cno.value = ""; cno.textContent = "Any"; csel.appendChild(cno);
  const clist = [...chars].map((ck) => [tkey(ck) || ck, ck]).sort((a, b) => a[0].localeCompare(b[0]));
  for (const [lab, ck] of clist) {
    const o = document.createElement("option");
    o.value = ck; o.textContent = lab; csel.appendChild(o);
  }
  csel.value = ckeep;
}

function toggleAudienceOnly() {
  const aud = ASTATE.view === "aud";
  $("aaudonly").hidden = !aud;
  $("areqonly").hidden = aud;
}

async function initAudiences() {
  const resp = await fetch("audiences.json");
  AUDIENCE = await resp.json();
  buildAudienceFilterUI();
  toggleAudienceOnly();
  renderAudienceResults();
}

function adebounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
$("aqq").addEventListener("input", adebounce(() => {
  ASTATE.q = $("aqq").value.trim();
  _ahair.clear(); _rhair.clear();
  renderAudienceResults();
}, 120));
$("aview").addEventListener("change", () => {
  ASTATE.view = $("aview").value;
  toggleAudienceOnly();
  renderAudienceResults();
});
$("afolder").addEventListener("change", () => { ASTATE.folder = $("afolder").value; renderAudienceResults(); });
$("achar").addEventListener("change", () => { ASTATE.char = $("achar").value; renderAudienceResults(); });
$("acond").addEventListener("change", () => { ASTATE.cond = $("acond").checked; renderAudienceResults(); });
$("aquest").addEventListener("change", () => { ASTATE.quest = $("aquest").checked; renderAudienceResults(); });
$("aaudreq").addEventListener("change", () => { ASTATE.audreq = $("aaudreq").checked; renderAudienceResults(); });
$("areqgrant").addEventListener("change", () => { ASTATE.reqgrant = $("areqgrant").checked; renderAudienceResults(); });
$("areset").addEventListener("click", () => {
  Object.assign(ASTATE, { q: "", view: "aud", folder: "", char: "", cond: false, quest: false, audreq: false, reqgrant: false });
  $("aqq").value = ""; $("aview").value = "aud"; $("afolder").value = ""; $("achar").value = "";
  $("acond").checked = false; $("aquest").checked = false; $("aaudreq").checked = false; $("areqgrant").checked = false;
  _ahair.clear(); _rhair.clear();
  toggleAudienceOnly();
  renderAudienceResults();
});
# Sovereign Tower Explorer — repo guide

Static, dependency-free viewer for the game data of *Sovereign Tower*,
extracted from the decompiled Godot project. Ships six tabs in one shell:
**Dialogues** (the "ink" story — the original explorer), **Quests** (312 quest
contracts + unexpected outcomes), **Inventory** (all 149 equipment resources),
**Knights** (the 24 playable knights), **Special** (the 71 `SpecialInstruction`
game-director switches) and **Audiences** (the 511 narrated scenes + the 34
`AudienceRequest` resources that unlock them). It walks the **compiled ink
JSON** directly
(no `.ink` source exists — see `../research/ink_research/REPORT.md` §1 for the extraction
chain), merges the quest/inventory/knight/special/audience resource catalogs built by
`quest_data.py` / `inventory_data.py` / `knights_data.py` / `special_data.py` /
`audience_data.py`,
and outputs a self-contained static site you can `http.server` and open in a
browser.

> Deep structural notes on the ink format live in `../research/ink_research/REPORT.md` — read it for
> *why* the data looks the way it does. This file is the operational guide.

---

## Layout

```
/app                          repo root (see ../README.md for the full map)
  explorer/                   THIS FOLDER — the shipped product
    build_app.py            one build pass: ink stories (in-memory extraction or
                            --from-disk) + the five data passes -> dist/; modes:
                            --extract-ink [dir] (decode only), --save-ink [dir]
    route_pages.py          per-route static pages + SEO shells (standalone CLI
                            too: reads the dist JSONs, no game root needed)
    ink_extract.py          standalone extractor: Godot .res -> master.ink.json
                            (+ per-knot readable txt dumps); CLI + importable
    quest_data.py           quest resources / enums / 6-locale text -> dist/quests.json
    inventory_data.py       equipment resources + buy/quest/ink sources -> dist/inventory.json
    knights_data.py         the 24 knights + dialogue/quest/ink links -> dist/knights.json
    special_data.py         SpecialInstruction catalog joins -> dist/special.json
    audience_data.py        audience + audience-request catalog joins -> dist/audiences.json
    dialogue_data.py        free-time dialogue catalog joins -> dist/dialogues.json
    ending_data.py          ending cutscene + vignette catalog -> dist/endings.json
    web/                    frontend source assets (edited here)
      index.html
      app.js                all UI logic (vanilla JS, no build step)
      style.css
    dist/                   GENERATED — self-contained site, safe to delete & rebuild
      index.html            copies of web/*           (fetch ./index.json)
      app.js                copies of web/*
      style.css
      index.json            en metadata + dialogue tokens (≈3.3 MB)
      quests.json           quest resources, enums, 6-locale loc table (≈1.6 MB)
      inventory.json        all equipment + buy/quest/ink sources
      knights.json          the 24 playable knights + dialogue/quest/ink links
      special.json          the SpecialInstruction catalog (knot/quest/knight joins)
      audiences.json        the audience + audience-request catalog (knot/quest/request joins)
      dialogues.json        the free-time dialogue catalog (affinity/conversation/reaction)
      endings.json          the ending-type cutscenes + per-character vignette catalog
      locales/{fr,de,cmn,ja,ko}.json   dialogue-token overrides (≈2.7–2.9 MB each)
      dialogues/, quests/, inventory/, knights/, special/, audiences/
        <entity>/index.html   per-route static shells (see "Routes / SEO")
    viewer.env              OPTIONAL KEY=VALUE config (see "Paths/config" below)
  ../game/                   game data (SovereignTowerCode, saved_games, optional
                             InkExtracted/en) + extract_save.py
  ../research/               ink_research/REPORT.md — the compiled-ink-format "WHY" doc
                             hosting/REPORT.md — the URL-routing / SEO plan this is built on
```

## Ink source: in-memory by default, on-disk optional

`build_app.py` decodes the compiled ink stories **in-memory** straight from the game's
`.res` chain (`game/SovereignTowerCode/story/<locale>/*.import` → `.godot/imported/*.res`,
same decoding as `ink_extract.py`) — no `master.ink.json` files need to exist on disk,
and nothing is persisted by a plain build (requires pip `zstandard`; hard error if missing).

- `--from-disk` — read `<ink_root>/<locale>/master.ink.json` instead (e.g. the user
  provided extracted knots by placing them under `game/InkExtracted/`). Missing locales
  are skipped with a warning.
- `--extract-ink [dir]` — skip the build; decode the 6 locales and write
  `<dir>/<locale>/master.ink.json` (default `../game/InkExtracted`), then exit. Same output
  as `ink_extract.py`, `python3 ink_extract.py` (standalone CLI, same defaults).
- `--save-ink [dir]` — build, then also write the extracted `master.ink.json` files
  (default `../game/InkExtracted`). Use this if you want to *keep* extracted knots in
  `game/` for agent queries.

The build also runs the resource passes over the Godot tree (`quest_data.py`,
`inventory_data.py`, `knights_data.py` from `build_app.py`) plus a final
`special_data.py` pass that joins the ink story, the quest rewards and the knight
evolution blocks into `dist/special.json`, an `audience_data.py` pass that
joins the audience resources, the audience requests and the quest follow-up /
request-reward links into `dist/audiences.json`, and a `dialogue_data.py` pass
that joins the free-time dialogue resources (affinity dialogs, knight
conversations, reaction/special dialogs) with their affinity gates, conversation
partners/exclusions/order and the ink `UnlockSpecialDialogue` + code unlock
sources into `dist/dialogues.json`, and an `ending_data.py` pass that mines the
ending-type cutscene knots (the EndingManager's `endings_cutscenes_paths` +
`Endings` enum), the `SWITCH_ENDING_*_PATH` special-instruction switches and the
per-character `ending_path` vignettes into `dist/endings.json`. The build only
needs the compiled ink
JSON (`INK_ROOT`) plus the game root (`GAME_ROOT`) as inputs.

Deploy the whole `dist/` directory anywhere; the UI fetches `index.json` and `locales/*.json`
via URL-relative paths, so no server logic is required (GitHub Pages, `file://`, anything).

---

## Routes / SEO

The SPA keeps its navigation state in `history.state` and **mirrors it into the URL** —
every `pushState` writes the matching path and the boot parses `location.pathname` back
into a location, so deep links and refreshes land on the same view (see "Frontend internals"
below). GitHub Pages has **no server-side rewrites** (and `python -m http.server`
neither), so a pushed `/quests/<id>` URL would 404 on refresh. `route_pages.py` fixes that the
only way static hosting allows: **prerender every route as a directory with an `index.html`**.
Each route is a trailing-slash path backed by `<route>/index.html`:

```
/                        dist/index.html              (the copied web shell)
/dialogues/              dialogues/index.html          (canonical → /)
/dialogues/<knot>/       dialogues/<knot>/index.html
/quests/                 quests/index.html
/quests/<quest_id>/      quests/<quest_id>/index.html
/inventory/              inventory/index.html
/inventory/<item_stem>/  inventory/<item_stem>/index.html
/knights/                knights/index.html
/knights/<knight>/       knights/<knight>/index.html
/special/                special/index.html
/special/<name>/         special/<name>/index.html
/audiences/              audiences/index.html
/audiences/<stem>/       audiences/<stem>/index.html
/audiences/requests/<stem>/   audiences/requests/<stem>/index.html
```

Every shell is the shared `web/index.html` markup (so the app boots identically at any
depth — asset tags get a `../`-deep prefix) plus a per-page `<title>` / meta description /
`<link rel="canonical">` / Open Graph / JSON-LD head, and detail pages embed the entity's
text as a visible `<div class="seo-teaser">` for bots. The SPA still renders everything
client-side; the shells exist so every deep link answers 200 with crawlable text.

- **The route tree is derived from the emitted JSONs themselves** — `route_pages.py` walks
  the key maps of `index.json` / `quests.json` / `inventory.json` / `knights.json` /
  `special.json` / `audiences.json` in `out_dir`, so it can never drift from the data, and
  it is deterministic (sorted keys, no timestamps → byte-identical rebuilds).
- **`SITE_BASE`** (CLI `--site-base <url>`, env or `viewer.env`) is the absolute URL of the
  deployment root; it feeds canonical / OG / JSON-LD URLs and must end in `/`. **Set it
  before the final build** (GitHub Pages tolerates relative canonicals poorly); when unset
  the shells use root-relative URLs, which is fine for local serving and `file://`.
- **Trailing slash.** GitHub Pages 301-redirects `/quests/x` → `/quests/x/` automatically,
  so both forms work for humans; the emitted (and canonical) form is the trailing-slash one.
- **`sitemap.xml` + `robots.txt`** are emitted in the same pass. The sitemap lists `/` + the
  five non-alias tab pages + every detail/request route (`/dialogues/` is excluded — it
  canonicalises to `/`), root-relative when `SITE_BASE` is unset or absolute URLs otherwise,
  in stable sorted order with no `lastmod`/`priority`/`changefreq` → byte-identical across
  builds. `robots.txt` is `User-agent: *` / `Allow: /` plus a `Sitemap:` line only when
  `SITE_BASE` is set (the default local build carries no `Sitemap:` line).
- The six tabs' static description blocks (`.tabdesc`, bottom of each results column) live
  in `web/index.html` and therefore land in **every** shell verbatim — bots see the active
  tab's description in each prerendered page.
- Run it standalone without touching the game tree:
  `python3 route_pages.py [out_dir] [--site-base <url>]`.

---

## Pipeline

```
../game/SovereignTowerCode/story/* + .godot/imported/*.res   (in-memory default)
  or  ../game/InkExtracted/<locale>/master.ink.json          (--from-disk)
       │  build_app.py (single pass per locale)
       ▼
dist/index.json       en: 922 knots, 91 speakers, 1,368 variables, 3,477 choices
dist/locales/*.json   only the per-knot dialogue token arrays for non-en locales
```

Knot identity and metadata (speakers, vars, funcs, categories) are **locale-independent** —
only the dialogue text changes. So `index.json` holds everything and each non-`en`
locale ships as a bare `{knotName: [tokens]}` override, lazy-loaded when the user
switches language. Token sets are identical across locales; this was verified.

### Token encoding (`build_app.py` docstring)
Compact arrays to keep JSON small:

| code | meaning |
|---|---|
| `["0", text, speaker?]` | dialogue text; `speaker` = active `Locutor` arg ("" = none) |
| `["1", marker]` | `(BREAK_n)` / `(NO_CLICK)` split out of text runs |
| `["2", label, [req...], flg?, dest?, [eff...]]` | player choice + conditional-var gates (e.g. `gideon_romanced`, `!flag`) + resolved destination + consequence fn calls. Function requirements (`RequiresFunds` etc.) are **not** duplicated here — they live only as `["3"]` flow tokens above the choice, keeping their args. `dest` is a real divert target, or the sentinel `(end)` / `(options)` when the choice closes the dialogue / re-offers the option list — except when the jump is **conditional**: a choice routed through an `if/else` (its follow-up stream at index 7 carries branch diverts) ships an **empty `dest`**, so the card shows no misleading default divert and the branches show where it leads. `eff` = non-presentation game-state fn calls the choice triggers (e.g. `UpdateSovereignValue`, `UnlockQuest`); they appear **only** in the card, not replayed in the flow. |
| `["3", name, [args...]]` | game/ink function call (args from the eval stack) |
| `["3", "set:"+kind, [target, rhs?]]` | variable write: `VAR=` / `temp=` / `list=`. `target` is the variable name; `rhs` (when the compiler emits an eval frame before the write) is the assigned value as an infix expression, e.g. [`"highest", "audacious_value"`] or [`"is_tyran_highest", "tyrannic_value == highest"`]. Param-declaration writes (function params, stitch-local temp re-decls) carry no `rhs`. |
| `["4", target]` | divert (`->`) |
| `["5", stitch]` | stitch section header |
| `["6", instruction]` | `>>>` game instruction line |
| `["7", [vars...], expr?]` | conditional branch gate: `{var: …}` ink check (`c:true` divert) that picks which dialogue variant plays; rendered as `if var` / `unless var` chips. Each var carries its own `!` prefix (per-operand negation, so `a && !b` renders correctly). When the condition uses operators, `expr` is the full infix form (e.g. `"kind_value > highest"`) and the gate renders as a single `if <expr>` chip. |

### How the walker works (the important part)
- A knot is `[[main-content…], {stitches…, "#f":1, "#n":…}]`. `ink_container()` splits
  content vs. named children; the walker is a **linear eval-stack emulation**, mirroring
  the compiled execution order (this is also what the now-removed per-knot txt dumps in
  `InkExtracted/*/knots/` showed — they're regenerable via `ink_extract.py`).
- **Speakers** are resolved via the exact pattern `ev → {"VAR?": X} → {"f()": "Locutor"} → out`
  — the `VAR?` arg *before* a `Locutor` call is the speaker. This is the only reliable way to
  attribute lines; the old txt dumps showed bare `// Locutor()` with no arg. Works for all 6 locales.
- **Choice labels** are assembled from `str … /str` blocks (label text is emitted *inside* the
  `ev` frame). Requirements (`Requires*`, `HintSat`, …) called inside that `str` block are
  attached to the following `["2" …]` choice as `req`s.
- **`out` does not close the `ev` frame.** In ink, `out` ends a *function-call* evaluation; the
  enclosing `ev` frame stays open until its matching `/ev`. The walker honours this, so a choice
  condition that mixes function calls (`Requires*`, `HintModification`, …) with real `VAR?`
  checks keeps its full condition (e.g. `epicrates_plan_known && golden_key_acquired &&
  !corrupted_sovereign`). Negation is tracked **per operand** — a frame-wide `!` flag would
  wrongly negate *every* var of `a && !b`.
- **Choice destinations** are resolved from the choice's `c-N` redirect stub. A stub that
  diverts somewhere meaningful gives a real target (e.g. `lie`, `follow_up`); a stub that ends
  the dialogue (`end` / `->->` opcode) gives the sentinel `(end)`; a stub that self-loops back
  to the option list (the "pick another option" pattern) gives `(options)`. A stub whose jump
  is **conditional** (`if/else` with per-branch diverts) gives **no** card destination — the
  first branch's divert is *not* promoted to the choice's default target; the branch gates and
  their diverts stay in the choice's follow-up stream so the reader sees where each branch leads.
- **Choice effects** (`eff`): game-state fn calls *inside* the choice's stub (`Update*`,
  `UnlockQuest`, `AddFunds`, …) are attached to the choice. Presentation-only calls (`Locutor`,
  `SwapExpression`, `FlashScreen`, `TriggerCustomAnimation`, `SetBackground`, …) are excluded
  from `eff` and instead kept inline in the flow under the "technical" toggle.
- **`present ink function` flag** (`knot.fn`): a knot is an ink-function when its container's
  *last element* is `{"#f": 1}`. Count here is **327**, vs. the report's 297 — the report only
  counted flat functions and missed container-style ones flagged the same way. 327 is correct.
- Marker regex strips `(BREAK_n)` / `(NO_CLICK)` out of text into `["1" …]` tokens.

### Known modelling choices / limitations
- **Linear per-stitch render, not a flow tree.** Conditional temp branches (`g-0`, `g-1`, …)
  aren't nested into branch trees; they're walked inline. Branch **gates** (`{var: …}` checks,
  the `ev VAR? /ev` → `{"->": ".^.b", "c": true}` pattern) *are* surfaced as `["7" …]` condition
  tokens at the point the branch forks — the game reads these variables to pick a variant, so the
  viewer shows them (default on, under the "branch conditions" technical toggle). You get the
  chronological dump of *all* reachable lines, matching the original txt dumps. Building a true
  branch tree out of the numbered containers is future work if ever needed.
- **Choice-label duplication.** A narrated line followed by an identical `[ label ]` appears
  twice (once as `["0"…]`, once as `["2"…]`). Faithful to the source; intentional.
- **Variable read/write is semantic, not just structural.** The compiler only emits
  state-mutating calls as `VAR?` reads (there is no matching `VAR=`), so the walker
  attributes *writes* from the game-API call slots: `UpdateSovereignValue(Kind, -1)`,
  `UpdateSatisfaction(Nobles, 5)`, `UnlockQuest(...)`, etc. mark their slot-0 argument
  as written (see `WRITE_SLOT0_FUNCS` in `build_app.py`). A slot only counts when it
  was pushed as a real variable reference — literal constants like `UpdateFunds(500)`
  are never mislabelled. This is why `Kind` correctly shows reads *and* writes.
- `["3", "set:"+kind, [name]]` tokens for `VAR=`/`temp=`/`list=` are emitted to show state
  writes inline (the second element is the assigned value when an eval frame precedes the
  write); they're hidden by the UI's "hide technical" toggle together with funcs,
  markers, and stitch headers.
- **Synthetic destination sentinels.** `(end)` and `(options)` are not real stitches — they are
  reader-facing markers for compiler stubs that close the dialogue or re-offer options, and are
  rendered as plain, non-clickable "→ dialogue ends" / "→ more options" spans.
- `window.stExplorer = { renderDialogue, tokensOf }` is exported from `dist/app.js`
  (top-level, last line) purely for headless smoke-testing. Harmless, but delete if you want a
  squeaky-clean global scope.

---

## Paths / config (no container paths hardcoded)

Resolution priority, higher wins:

1. CLI args — build: `python build_app.py <ink_root> <out_dir> [game_root]`
        · quests: `python quest_data.py <game_root> [quest_out]` · inventory: `python inventory_data.py <game_root> [out]`
        · knights: `python knights_data.py <game_root> [out]` · special: `python special_data.py <game_root> [out]`
        (special reads `index.json`/`quests.json`/`knights.json` from `[out]`, so run it after those)
        · audiences: `python audience_data.py <game_root> [out]` (reads `index.json`/`quests.json`)
        · dialogues: `python dialogue_data.py <game_root> [out]` (reads `index.json`/`quests.json`/
        `knights.json`/`special.json`, so run it last)
        · endings: `python ending_data.py <game_root> [out]` (new file, no deps on other passes)
2. Environment vars — `INK_ROOT`, `INK_OUT`, `GAME_ROOT`, `SITE_BASE` (build) · `GAME_ROOT`, `QUEST_OUT` (quest data)
        · `INK_SOURCE`, `INK_OUT` (extract)
3. Config file — `viewer.env` (build/quests, shared keys) / `extract.env` (ink_extract.py), `KEY=VALUE`, next to each script
4. Portable defaults:
   - build: ink stories in-memory from `../game/SovereignTowerCode` (see "Ink source"),
     output = `./dist`; `--from-disk` reads `../game/InkExtracted` instead
   - quest data: game root = `../game/SovereignTowerCode`, output = `./dist/quests.json`
   - extract (`./ink_extract.py`): source = `../game/SovereignTowerCode`,
     output = `../game/InkExtracted` (both script-relative)

Relative values in CLI/env/.env resolve against the **working directory**; use absolute paths
(Windows: `C:\…`) for anything you want CWD-independent. `Path` handles both platforms.

`build_app.py` and `quest_data.py` share the `GAME_ROOT` / viewer.env key pair: a quest-data pass
runs inside every `build_app.py` build, so both scripts agree on where `SovereignTowerCode` lives
without duplicating config. You can also run `quest_data.py` standalone to regenerate
`quests.json` into any location.

Example `viewer.env` (any of the keys can be omitted — the portable defaults above already
point into the repo's `game/` folder):
```
INK_ROOT = /app/game/InkExtracted
INK_OUT  = /app/explorer/dist
GAME_ROOT = /app/game/SovereignTowerCode
QUEST_OUT = /app/explorer/dist/quests.json
SITE_BASE = https://user.github.io/repo/   # only needed for the final build
```

---

## Build & run

> Quick-start, full argument reference and troubleshooting live in `BUILD.md`.
> `python3 build_app.py --help` prints the same reference plus the exact paths
> the build would use on your machine.

```bash
python3 build_app.py                       # rebuild dist/ from ../game/InkExtracted
cd dist && python3 -m http.server 8000     # open http://localhost:8000
```

`build_app.py` depends only on the Python stdlib **except the default in-memory ink
extraction**, which needs pip `zstandard` (hard error with install hint if missing —
the game's `.res` files are ZSTD-compressed). `--from-disk` builds stay stdlib-only.

### Rebuild from scratch (fresh checkout)
1. Build: `python3 build_app.py` — extracts all 6 locales in-memory from
   `../game/SovereignTowerCode` and regenerates `dist/` in one pass.
   Alternative: provide extracted knots yourself — `python3 build_app.py --extract-ink`
   (or `python3 ink_extract.py`) writes `game/InkExtracted/*/master.ink.json`, then
   keep them in `game/` and build with `--from-disk` (stdlib-only path).
2. Serve `dist/`.

---

## Frontend internals (web/app.js)

Single-page, zero deps. State lives in one `state` object passed through
`renderResults()` → `visibleKnots()` (filtering) → category-grouped cards.
Per-card searchable text is cached in `_hcache`. Highlighting is substring-based (922 knots,
fine for pure client-side search; no FTS needed at this scale).

**Navigation & URLs.** The history stack stores locations as `{ t: tab, d: null | { k: kind,
v: key } }` (`INIT_LOC = { t: "ink", d: null }`). `pushLoc`/`go`/`goTab`/`goClose` push an entry
**and** write it to the URL; `urlFromLoc(loc)` ⇄ `locFromUrl(path)` are exact inverses mapping
onto the `route_pages.py` directory scheme (`/` for the Dialogues tab, `/dialogues/<knot>/`,
`/quests/`, `/quests/<id>/`, `/inventory/<stem>/`, `/knights/<stem>/`,
`/special/<name>/`, `/audiences/<stem>/`, `/audiences/requests/<stem>/`). On boot `init()`
parses `location.pathname` into the initial location (`history.replaceState`), and once every
dataset has loaded it calls `applyLoc()` once to replay a direct/refresh visit — so a shared
`/quests/<id>/` link opens straight into the quest drawer. `popstate` is deferred until that
point (`navReady`) and prefers `history.state`, falling back to the URL when state is missing;
all `location` access is guarded (`typeof location === "object"`) so the app still boots
headlessly in the frontend smoke VM, and unknown/mistyped paths degrade to the default tab.

Filters (sidebar): text search, speaker, category (17 auto-classified via `classify()`),
variable (read / write / either), **function/requirement** (any game-API call
`RequiresTag`, `RequiresFunds`, `HintSat`, `UpdateSovereignValue`, …) with an optional
**argument/value filter**: pick a function, then its first argument (the tag, e.g. `Kind`),
then an operator (`=`, `<`, `≤`, `>`, `≥`) and a value to compare against the call's numeric
argument — e.g. `RequiresTag` + `Kind` + `≥` + `2` finds every knot requiring Kind *at least* 2.
The arg/value inputs are suggestion lists (`datalist`s) built from the actual call sites in
`index.json`, so only real tags/values are offered. Blank arg = any first argument; blank value
= presence-only (the original function filter). Works for write calls too, e.g.
`UpdateSovereignValue` + `Kind` + `>` + `0` to find where Kind is *raised*,
only-with-choices, hide game-function knots.

A **"Where it comes from"** filter group selects knots by their cross-dataset
links (the reverse maps `knotAudiences`/`knotFuQuests`/`knotIncoming`/
`knotUnlocks`/`knotSpecials`/`knotItems`/`knotKnights`/`knotSpecialTriggers`
built from
`audiences.json`, `quests.json`, `special.json`, `inventory.json` and
`knights.json`): played-as-an-audience, fires-after-a-quest,
reached-from-other-knots, unlocks-a-quest, emits-a-special-instruction,
grants/removes-items, appears-in-knight-dialogue, **has-a-free-time-dialogue-
source** (matches `dialogues.json` — the affinity/knight-conversation/reaction
resources the tower free-time machinery plays) — plus dropdown selects for
the audience **type** (folder), the audience **NPC**, the **quest** that fires
the knot and the **special instruction** it emits. Knot cards carry badges for
these links too (audience ×N, unlocks N, special ×N, knight ×N), so e.g.
`grest_first_grievance` is immediately identifiable as a *doleances* audience
starring Roland. The knot drawer's origin section additionally lists the
**special instructions that unlock or divert to the knot, or schedule the
audience that plays it** ("Fires when the special instruction X is triggered" —
the reverse of the Special tab's `dlg`/`goto`/`auds` links, so
`gideon_victoria_dead_reaction` states that `GIDEON_VICTORIA_DEAD` must fire
first and `candidature_gwendan_the_humble` that `GWENDAN_REFORMED` schedules it).
Every audience row links to the exact audience resource (clickable) and carries
its decoded conditions — the same consolidated "Conditions" gates the Audiences
drawer shows in one place: the audience's `rq` firing requirements ("Story gate" /
"Knight gate" / "Plays only once"), the **hardcoded cycle** when a scene is
scripted into the cycle timeline (e.g. `scriptedquest_chester` → "hardcoded to
play at cycle 2 (scripted into the cycle timeline — fires regardless of player
actions)"), the doleance schedulers and special-instruction schedulers (the ones
with dedicated knot-level rows — quest follow-ups and special triggers — are kept
on their own lines to avoid duplication), the director/intervention notes, knight
death/demission triggers, the filler pack, county introduction and ultimatum
follow-up sources, and the **code-scheduled knight events** (audiences queued
directly by game code rather than any of the above channels — the `code` field:
Edith's killing-quest possession gimmick `edith_gimmick_introduction_demon_possession`,
Goberto's death → Dulahan's `dulahan_candidacy` arrival, the groveshire/gavault
family-reunion `lost_child_plotline_groveshire_gavault_confrontation` 7-gate
check, and the `KUTNAR_TARCUS_INTERVENTION` special-goto reachable
`intervention_tarcus_county_quest_kutnar_first_audience`) — plus the
**divert-reached sub-scene labels** for audiences
never queued by any of those channels: "Same scene as <scheduled sibling>"
(identical ink path, e.g. `county_quest_brimwood_3_testimony_1` = its doleance-scheduled
twin) and "Plays inside <parent audience>" (the nearest scheduled ancestor audience
whose knot diverts into this one, resolved by walking the knot→divert graph — e.g.
`county_quest_brimwood_3_testimony_2` and the 6 brimwood-trial interventions play inside
`county_quest_brimwood_3_before_testimony`, the candidacies inside their county finals,
`intervention_childeric_county_quest_almor_audience_3` inside `county_quest_almor_3`).
When the knot is a **free-time dialogue** (a `dialogues.json`
entry), the origin section adds its own row ("Played as an affinity dialogue of
<knight> (requires affinity ≥ N, plus the state-aware gates)",
"Knight conversation: <knights> — plays once, free time, with its room/state
exclusions/pick order", or "Reaction / special dialogue of <x>: unlocked by the
ink knots calling `UnlockSpecialDialogue`, the romance/golden-key code unlocks,
the dragon-egg/dragon-heart/cursed-helmet item gates and the special-instruction
`dlg` signals"). When the knot is an **ending** (an `endings.json` entry), the
origin section adds its own ending row too: "Ending vignette of <x> — plays at
the end while <x> is alive and at the roundtable (recruited, for servants)", the
main "Ending cutscene (<TYPE>)" with its `SWITCH_ENDING_*_PATH` switching
instruction (or the corruption-gated DEMON_STATE note), or the code-played
special note (`hildegard_singing_ending`, `demon_back_in_time_ending_proposal`).

A **"Chain of events"** section (when the knot is part of a sequence) lays out
the narrative order the knot plays in as a horizontal flow, current knot
highlighted: doleance scheduling (`AddDoleanceForNextCycle` → the audience it
queues for next cycle, of any type) and quest-success follow-up audiences
(unlocking knot → the audience played when the quest succeeds) are followed as
unambiguous single hops; where the chain branches (multiple outcomes, the
Gavault/Groveshire shared choice root, candidacies/grievance intros fired
alongside) the spine stops and the options are listed as **Earlier events** /
**Next events** chips. Failure/unexpected follow-ups are alternate branches, so
`county_quest_enberg_first_audience → county_quest_enberg_audience_2 →
county_quest_enberg_audience_3_interrogation` reads in order, with the final
audience plus the gothild candidacy / Enberg grievance intro as next options.

Detail drawer starts with a **"What happens"** summary: every game-state change
the knot makes, decoded — sovereign stats, funds, taxes, satisfaction, servant
romance, tag unlocks, knight recruitment/demission/death, county rallies /
quest failures, ultimatums, doleances, equipment give/remove, quest unlocks,
`SpecialInstruction` (with the special-conditions catalog note) and **every
variable/flag write**, whether it appears inline in the flow, inside a choice's
effects (`eff`), or is set by passing it as a divert/stitch parameter. Each
flag write carries a "read in N ink knots" ripple list (the long-term
consequences), cross-linking into any of the six tabs. Then the full dialogue
render (`renderDialogue`) with colored speaker labels,
choice boxes with requirement tags, a resolved-destination line ("→ …" link when the choice
diverts, "→ dialogue ends" / "→ more options" when it closes or re-offers), and a
consequences strip listing the game-state calls the choice triggers. A set of
**technical-layer checkboxes** controls what extra plumbing is shown: diverts (jump
targets), stitch headers (branch/checkpoint names, rendered as markdown-style `##` headers),
`(BREAK_n)`/`(NO_CLICK)` markers, branch conditions (`{var: …}` gates — the game reads these
variables to pick a dialogue variant), and **function calls** broken out
into five sub-categories — presentation (`SwapExpression`, `Apparition`, `FlashScreen`, …),
sound (`InstructionSound`), var writes (`set VAR`), requirements (`Requires*`, `HintSat`), and
game-state (`UpdateFunds`, `UnlockQuest`, …). These prefs are persisted in `localStorage`
(`st_tower_ink_show`) and survive refreshes / sessions. Clicking a variable chip applies that
variable filter; diverts link to other knots; the locale `<select>` swaps `LOC` overrides live.

CSS: `style.css`, dark theme, one `@media` breakpoint for mobile.

### Adding a locale
1. In-memory mode picks up any locale whose `.res` import exists under `game/`; for
   `--from-disk`, ensure `../game/InkExtracted/<loc>/master.ink.json` exists (write via
   `python3 build_app.py --extract-ink` or `ink_extract.py`).
2. Append the code to the `LOCALES` tuple in `build_app.py` (order matters: first is used for
   `index.json` metadata — keep `"en"` first).
3. Add an `<option>` in `web/index.html` + `dist` rebuild.

### Adding a filter facet
Extend `state` in `web/app.js`, add the matching UI element in `web/index.html`, and add the
predicate inside `visibleKnots()`. Then `python build_app.py` (only copies web assets + data;
data pass is cached-free and full each time).

---

## Verification quickies

- Rebuild idempotent: `rm -rf dist && python3 build_app.py` regenerates everything including
  the `web/*` copies.
- JS syntax: `node --check dist/app.js`.
- Headless smoke test of the renderer (works with a tiny DOM stub): load `dist/index.json`,
  set `k.name`, call `stExplorer.renderDialogue(k, fakeDiv)`; expect zero throws across all
  922 knots, 18,977 text lines, 3,477 choices rendered.
- Locale parity: `fr.json` key count == `index.json` knot count (922).

## Test suite

`tests/` is a stdlib-only `unittest` suite that locks the current behaviour in
so the build can be refactored (split into smaller modules) without breaking
anything. After a behaviour-preserving refactor, this suite must stay green.

Run the whole thing (a few seconds for the fast layers, tens of seconds total —
the only slow parts are the data passes and the full-build golden test, both of
which print their wall time in the runner's per-module timing table at the end):

```bash
cd /app/explorer
python3 tests/run_tests.py            # default suite — everything EXCEPT the golden build test
python3 tests/run_tests.py --golden   # + golden build test (fresh build vs checked-in dist/)
python3 tests/run_tests.py test_helpers   # filter to one module (substring match)
```

**Golden build test is REFACTOR-ONLY — DO NOT RUN IT for routine work.** It is not
part of the default suite, and it must not be invoked for feature/fix/docs/chore
tasks: it rebuilds the whole app just to confirm a fresh build is byte-identical
to a reference `dist/`, which adds zero value on a non-refactor task and wastes
~20 s of rebuild time double-checking unchanged output (the build is deterministic
— two consecutive builds already match). **Skip it unless you are refactoring**
and need to confirm the build output did not change vs an older, stable ref.
Run it only then:

```bash
python3 tests/run_tests.py --golden              # fresh build vs the checked-in dist/
python3 tests/check_dist_ref.py main             # fresh build vs main's dist/ (the refactor check)
python3 tests/check_dist_ref.py dev              # ... vs dev's dist/
python3 tests/check_dist_ref.py <commit-sha>     # ... vs an older commit
```

`check_dist_ref.py` runs the full suite (including the golden test) with
`EXPLORER_DIST` pointed at the ref's checked-in `dist/`. Any diff = the refactor
changed build output.

Speed notes: the data passes cache their parsed `.tres` / `.gd` files per process
(`TresFile.load`, keyed on path + mtime/size), so repeated passes inside one build
or one test run don't re-read the game tree. `test_data_passes` builds each pass
exactly once and shares it across its test classes instead of re-running the full
tree walk per test.

Layers (each also runs standalone: `python3 tests/test_walker.py`, …):

| file | what it locks in | needs |
|---|---|---|
| `test_helpers.py` | pure helpers of `build_app.py`: `tail_path`, `classify`, `parse_flags`, `expr_to_infix`, token folding, `resolve_paths`… | nothing |
| `test_walker.py` | the compiled-ink Walker's exact token output on verbatim real-game knots (speaker attribution, if/else gates, choice dest/effects, `UnlockQuest` semantic writes) | nothing (fixtures in `tests/fixtures/ink_knots.py`) |
| `test_tresfile.py` | `quest_data.py`'s `.tres`/enum parsing on self-contained fixtures | nothing |
| `test_dist_conformance.py` | schema + cross-dataset invariants of the shipped `dist/` (token encoding, stats self-consistency, locale knot-set parity, id maps) | checked-in `dist/` only |
| `test_data_passes.py` | the data passes over the real game root at the documented volumes (312 quests, 149 items, 24 knights, 71 specials, 511 audiences, 235 dialogs, 6 endings) | `../game/SovereignTowerCode` (skips if absent) |
| `test_build_golden.py` | a **fresh build is byte-identical to the reference `dist/`** — the highest-value regression net for a refactor; **refactor-only, do not run for routine work** (`run_tests.py --golden` or `check_dist_ref.py`, not run by default) | game root + pip `zstandard` (skips if absent) |
| `test_frontend.py` + `frontend_smoke.js` | `node --check dist/app.js` + boots the full app in a VM with a minimal DOM stub, renders every tab, and calls `renderDialogue()` across all 922 knots expecting zero throws | node (skips if absent) |

Guidelines:
- `dist/` is the golden reference for `test_build_golden.py`; when data changes
  *intentionally*, rebuild `dist/` and commit the new golden in the same change.
  The golden test is refactor-only (`--golden`) precisely so routine feature work
  does not pay the full-build cost; only a refactor branch should run
  `check_dist_ref.py`.
- The suite deliberately avoids third-party test runners (no pytest), matching
  the project's no-runtime-deps philosophy.
- Known data quirks the suite acknowledges (documented in the tests):
  per-knot token sequences differ from `en` in ~100-200 knots per locale (the
  translators restructured lines/markers), and 4 secret quest loc keys are
  untranslated.

---

## Data at a glance (en)

| | |
|---|---|
| knots | 922 (327 compiled as ink functions) |
| text | 18,977 lines / ≈1.1 M chars across all knots/stitches |
| choices | 3,477 (all with a resolved destination — or, when the jump is a conditional `if/else`, with the branch diverts carried in the choice's follow-up stream; 1,046 with consequences) |
| speakers | 91 (resolved via `Locutor` eval-stack pattern) |
| variables | 1,368 (298 declared + list items / conditionals read) |
| categories | 17 auto-classified (grievance, affinity, quest, ending, …) |
| locales | en / fr / de / cmn / ja / ko, structurally identical |

`index.json` also carries `listDefs` (the 22 game dictionaries: CHARACTERS, EXPRESSIONS, …),
a `funcs` map (function name → knot count, for the function/requirement filter) and a
`stats` block for the header bar.

The other data files (loaded by the other five tabs) are: `quests.json` (312 quests,
91 quests carrying unexpected outcomes — 10 of which are inline `SubResource`
special outcomes decoded from the quest file itself — 69 modifier variants, 511
audiences, 306 ink-unlocked),
`inventory.json` (149 items, 68 quest-linked, 26 ink-unlocked), `knights.json` (24
knights, 24 ink-linked, 23 with conversations, 7 with evolution paths),
`special.json` (71 instructions: 50 emitted in ink, 19 granted as quest rewards,
12 knight evolutions, 23 with effect cross-links; 12 carry decoded `cond`
firing-condition rows — the tarcus/ursule/epicrate availability gates, the
golden-key quest guards, the almor-duel guard and the traitor-plot guards — with
the `CHECK_FOR_EPICRATE_*` cases inheriting the full `_is_epicrate_available()`
sub-guard set (roundtable-busy, dead, brimwood-trial-ongoing, serpent-knight-met,
cycle-bounds, Epicrate/Marian audience conflict)) and `audiences.json` (511 audiences: 18 with firing
conditions, 20 director-scheduled (serpent-knight reset, civil wars, act-ending victories, Arlin
act intros, Rupin's corruption-gated grievances), 28 special interventions (the ultimatum second
encounters, the king/dragon allied plots, the traitor's-plot intro + murder, Dulahan's human form,
Victoria's betrayal, the nobles' cycle-zero intro, the wolf candidacy, Arlin's reunited-roundtable
reaction, the 15 courier scenes), 7 knight death follow-ups (the death announcements of angelica,
gideon, goberto, gwendan + Ursule's corruption-tiered new-gimmick variants), 29 knight demissions
(the 24 `knight_leaving_*` demission scenes + the variant forms Arron's Dragonheart,
Dulahan human/possessed, Edith possessed and Gwendan's reformed humble candidacy each use),
234 filler-pack scenes (pack + corruption tier + targeted population per audience, in 27
unlockable packs — the four representative packs + 23 region packs — unlocked by the
first-grievance knots calling `UnlockFillerAudiencesPack`), 7 county introductions (the
`county_quest_<id>_1` intros — `ci` — scheduled by the ActManager at act 1→2 / 2→3
transitions or when a neighboring county is rallied), 6 ultimatum follow-up scenes
(the victory/defeat audiences of the kingslayer (deadline 23), dragon-knight (8) and
emperor (45) ultimatums — `um`/`umc`, with the decoded condition sets), 62 fired after
quests (incl. `county_quest_southbay_final_father_dead_tarcus_unexpected`, the inline
special outcome of `quest_southbay_political_instabilities` with `k:[tarcus]` + its
follow-up audience), 4 code-scheduled knight events (the `code` field — audiences queued directly
by game code rather than any scheduling channel: Edith's killing-quest possession gimmick
`edith_gimmick_introduction_demon_possession`, Goberto's death → Dulahan's `dulahan_candidacy`
arrival, the groveshire/gavault family-reunion
`lost_child_plotline_groveshire_gavault_confrontation` 7-gate check and the `KUTNAR_TARCUS_INTERVENTION`
special-goto `intervention_tarcus_county_quest_kutnar_first_audience`, each with its scheduling
note in the Conditions box), 4 knotless, 14 divert-reached sub-scene audiences
(never queued by any channel: their ink knot is reached via an ink divert inside another,
scheduled audience's scene — the 6 brimwood-trial interventions, `county_quest_brimwood_3_testimony_2`,
`intervention_childeric_county_quest_almor_audience_3`, the childeric/ligia/tarcus candidacies,
`goberto_gimmick_introduction_new_armor` and `intro_dragon_knight_grievance` — each labelled in its
Conditions box "Plays inside <parent audience>" resolved from the knot→divert graph, e.g.
`county_quest_brimwood_3_testimony_2` → the doleance-scheduled `county_quest_brimwood_3_before_testimony`,
plus the same-ink duplicate `county_quest_brimwood_3_testimony_1` marked "Same scene as"
`county_quest_brimwood_3_before_testimony`); 6 legacy-orphan flags (the `unused`/`unote` field —
never queued by any channel: the four `*_classic_recruitment` scenes, dead (superseded by the
request recruitment mechanic, whose successor `*_audience_request_recruitment` resources live on),
and the two `brizh_*_grievance_first_meeting` orphan knots, real knots that no doleance /
divert / quest / request / special / director / code source ever plays — each shown as a dashed
`legacy · unused` card badge and a "Legacy resource:" Conditions row); 34 audience
requests — 24 of them `call_back_*` call-backs (flagged `cb`: unlocked when the knight leaves the
roundtable, they invite the knight back), and every request's **ink unlock sources** rendered in
its drawer ("Unlocked by ink": the `UnlockAudienceRequest` call sites — e.g. `rowan_request` is
offered by `arlin_introduction_to_act_2`'s `!groom_recruited` branch plus the recruitment knot's
re-unlock — with the unlock knots cross-linked into the Dialogues tab, an unlock chip on each
request card and the unlock knots indexed into request search)) and `dialogues.json` (235 free-time dialogs — 82 affinity
dialogs, 77 knight conversations (incl. the inline `candidature_alwena`), 76 reaction / special
dialogs — each with its locating room, the affinity-conversation gates (`aff`: knight + min-affinity
rank, incl. the subclass variant dicts: arron violent/kind, dulahan body-possession, edith possessed,
gwendan reformed/repaid, gideon known-origin insert, ursula affinity-4-if-dead, angelica's on-death
replacement and the room-gated rufus/victoria/wolf dialogs), the knight-conversation partners,
state exclusions and pick order (`conv`), and the unlock sources (`unl`: the ink knots calling
`UnlockSpecialDialogue` — all 98 sites resolve, incl. the four `marriage` calls in
`scriptedquest_civil_war_event_nobles_revolt` and Gwendan's runtime `marriage`/`romance_completed`
forks — plus the `romance_completed`/`golden_key`/item code unlocks and the special-instruction
`dlg` signals), 85 with at least one unlock source) and `endings.json` (the game-end context of the
41 `ending`-category knots: the six ending-type main cutscenes — WAR / PEACE_TREATY / MARRY /
SURRENDER / TOWER_DESTRUCTION each switched by its `SWITCH_ENDING_*_PATH` special instruction,
plus the corruption-gated DEMON_STATE epilogue — in `types`; the 31 per-character ending
vignettes (24 knights + 7 servants, `endings.json` `vignettes` keyed by character ink id, played
by the ServantEndingCutscene at game end while the character is alive / at the roundtable, e.g.
`intendant` → `alwena_ending`, `blacksmith` → `carina_ending`, `ursule` → `ursula_ending`); and
the 2 code-played special knots in `specials`: `hildegard_singing_ending` (the `HILDEGARD_SONG`
special instruction) and `demon_back_in_time_ending_proposal` (the demon-room scene)).
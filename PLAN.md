# PLAN — Sovereign Tower Explorer (quests + shared systems)

> Status: **IMPLEMENTED (dialogue + quests + inventory + knights + special + audiences)**

---

## 1. What we are building
A static, dependency-free, single-deploy viewer for the data of *Sovereign Tower*
(the decompiled Godot project in `../game/SovereignTowerCode`), as a **single project** that
absorbs the existing `ink_viewer` and renames it **"Sovereign Tower Explorer"**.

Sections (tabs), added incrementally:

1. **Dialogues** — existing ink view, unchanged (already works: 922 knots, filters, drawer, 6 locales).
2. **Quests** — NEW. Filters + detail drawer over the 312 quest contracts + 90 unexpected outcomes.
3. **Later** (same shell, zero new infra): Knights, Equipment/Relics, Audiences/Requests, Save inspector.
   Shipped since: Knights, Inventory (Equipment/Relics), the **Special** instruction
   catalog and the **Audiences** tab; still future: Save inspector.

### Why merge (vs. keeping projects separate)
Separate projects duplicate shared plumbing and make cross-linking impossible. Cross-links are
the single best feature of this app:

- quest card → "unlocked in `milkford_grievance_apple_pie_recipe`" → jump to that knot's dialogue
- quest follow-up audience → its `ink_path` knot
- county quest chain → sequence of `county_quest_*` knots in order
- reward `RELIC` → the relic resource → every quest that grants it; `CHARACTER_TAG` rewards → knights
- shared tag system (CharacterTags / SovereignTags / ConditionTags) used by dialogue *and* quests

---

## 2. Findings (evidence the data is sufficient)

### Quest system is fully data-driven (no reverse-engineering needed)
- **312 quest resources**: `SovereignTowerCode/content/quests/contract_*.tres` (all `Quest` class).
  Explicit fields: `quest_id`, `quest_name`/`quest_description` (localization keys), `quest_type`,
  `quest_category` (11 `QuestTags`), `quest_location` (38 `LocationsID`), `quest_conditions`
  (21 `ConditionTags`), `stats_requirements` (`Knight.Statistics` → value), `quest_damages` range,
  `duration`, `nb_requested_knights`, `involve_killing`, `quest_can_be_lethal`,
  `success_rewards`, `faillure_consequences`, `success/failure_follow_up_audience`, `cutscene`,
  `has_deadline`, `modifiers`, `extra_conditions`, `requested_knights`.
- **90 unexpected outcomes**: `content/unexpected_outcomes/*.tres` (`SpecialOutcome`): trigger
  conditions (specific knight / required `CharacterTags` / stat threshold), own rewards,
  follow-up audience, damage range, arlin note.
- **48 quests** have `modifiers` (alternate spawn variants, chosen via `unlock_quest` idx param).
- **Outcome model documented in code**: `quest.gd` — score = stats vs requirements + affinity ±
  tag special cases → 8 outcomes (`CRITICAL_FAILURE…CRITICAL_SUCCESS`, `UNEXPECTED_OUTCOME`);
  damages/rewards computed per outcome. `quests_manager.gd` — lifecycle: ink unlock → cycle
  countdown → outcome → rewards + follow-up audience unlock.

### Ink ↔ quest graph is complete
- `UnlockQuest` is an ink knot that emits `>>> unlock_quest : <id>, <idx>` (see parser.gd 43-handler
  instruction table + `UnlockQuest` knot def).
- **333 `UnlockQuest` calls in the ink story; 289 of 312 quest resources are referenced by real IDs**
  (only false positive: demo knot's `placeholder_quest`).
- **511 audience resources** have `ink_path` → knot (54 = county-quest chains, plus candidacies,
  doleances, etc.) → after a quest resolves, follow its follow-up audience into the dialogue view.
- County quests / scripted quests / ultimatums are narrative chains on the ink side
  (`county_quest_*`, `scriptedquest_*`, `ultimatum_*` knots).

### Everything decodable
- Enums in code: `tag_manager.gd` (SovereignTags/CharacterTags/QuestTags/ConditionTags),
  `knight.gd` (`Statistics`), `location.gd` (`LocationsID`), `quest_reward.gd` (`RewardType`).
- Localization: `lang/{en_fr,cmn_ja_de_ko}/*.csv` — `quests.csv` (631 lines) etc. covers
  names/descriptions in 6 locales (en/fr/de/cmn/ja/ko).

### Caveats (be honest in the UI)
- **Exact outcome is runtime-computed** (scores, RNG damage). Viewer shows the *rule table*:
  stat requirements, thresholds, every conditional unexpected outcome, rewards per outcome —
  not a precomputed single path.
- **23 quest resources referenced nowhere** (e.g. `contract_clovermont_vampire_kill`,
  `contract_merchants_false_bank`) — variant/dead content; mark "never unlocked in ink", don't hide.
- **`dist/index.json` stores `UnlockQuest` as bare function names without args** → quest IDs must
  be captured by extending the build pass (small change to the ink walker's arg collection).

---

## 3. Implementation outline (matches existing ink_viewer philosophy: stdlib build, vanilla JS)

### Build (one pipeline, extends `build_app.py`)
- New data pass producing `dist/quests.json` (+ quest section merged into `index.json` if preferred):
  - source: `content/quests/*.tres`, `content/unexpected_outcomes/*.tres`,
    `content/audiences/**/*.tres` (`ink_path`), `content/character_descriptors/**` (knights/names),
    `lang/*/quests.csv` (+ related CSVs) for 6-locale text, enum catalogs from the `.gd` files.
  - `UnlockQuest` args from the ink walker (extend arg collection so quest id + modifier index survive).
  - decode enums to names at build time (do NOT ship raw ints).
- ~312 quest records — trivial size vs. the current ≈3.3 MB ink index. Keep `file://`-deployable.
- Keep `dist/` as the only generated output; `web/` stays the hand-edited source.

### Frontend (reuse existing pattern)
- Add a **tab bar** to `web/index.html`: Dialogues | Quests (…). Locale `<select>` stays global.
- **Quests view** reuses the card + sidebar-filter + detail-drawer pattern from the ink view:
  - Filters: quest_type, category (QuestTags), location, condition tags, stat requirement,
    reward type (+ specific item, e.g. a relic), has unexpected outcome, deadline, unlock-knot present.
  - Card: name, location, type/category chips, requirement summary, rewards summary,
    "unlocked in" knot link(s).
  - Drawer: stats-requirements table; conditions; duration/damage; rewards decoded per outcome
    (success / failure / unexpected) with linked relic/mount/audience names; modifier variants;
    follow-up audience → knot links (jump to dialogue view); "unlocked in" knot links.
  - Cross-system jumps: quest ↔ knot; later knight ↔ quests; relic ↔ quests that grant it.

### Verification (mirror existing)
- Rebuild idempotent: `rm -rf dist && python build_app.py`.
- `node --check dist/app.js`; headless smoke render over all 312 quest cards.
- Quest data cross-check: 289 quests referenced in ink == UnlockQuest calls in `master.ink.json`;
  quest ids in `quests.json` == filenames in `content/quests/`.

### What shipped (2026-08-13)
- `quest_data.py` — pure-stdlib pass: parses `content/quests/*.tres`, `content/unexpected_outcomes/*.tres`
  `SpecialOutcome`s, modifiers sub-resources, follow-up `Audience` files (`ink_path` + characters),
  character descriptors (names), equipment/audience-request/quest-item name keys, and 6-locale text
  from `lang/{en_fr,cmn_ja_de_ko}/*.csv`. Decodes `RewardType`/`QuestTypes`/`QuestTags`/`ConditionTags`/
  `LocationsID`/`Statistics`/`SovereignTags`/`CharacterTags`/`Population` enums **by numeric value**
  (supports non-sequential enums: QuestOutcomes ±, CharacterTags with gaps).
- `build_app.py` now also emits `dist/quests.json` (312 quests, 90 unexpected outcomes, 69 modifiers,
  511 audiences, `unlock_knots` reverse map from `UnlockQuest` ink calls = 306 quests).
- Frontend: **Dialogues | Quests** tabs. Quests tab = 10 filters (search/type/category/location/
  condition/stat/reward/unexpected/deadline/lethal/killing/linked), card grid, detail drawer with
  requirements, conditions, rewards/consequences, unexpected-outcome rule boxes, modifier variants,
  follow-up audiences, and "unlocked in ink" knot links that jump to the dialogue view.
- Caveats surfaced honestly in-data: 4 secret quest keys have no translation (raw key shown);
  6 quests never unlocked in ink (marked "not unlocked in ink"); outcome is shown as a rule table,
  not a single precomputed path.
- New "text effects" technical-layer toggle (2026-08-13): hides inline Godot BBCode effect tags
  (`[b]`, `[i]`, `[shake …]`, `[wave …]`, `[font_size=N]`, `[color]`, …) while keeping the words
  between them. Off by default; applied to dialogue lines, continuations, and card previews.
  Implemented in pure JS (`stripBbc` regex), no 3rd-party library.
- Inventory tab (2026-08-13): all 154 equipment resources (70 relics, 29 mounts, 44 consumables,
  6 meals, 5 quest items) from `inventory_data.py`. Filters: search / type / stat bonus (+ only
  positive) / character tag / acquired-via (forge, stables, witch, meals, starting, quest, story,
  no source) / story-unlock / exclusive / hidden-stats. Card: cost, non-zero stat chips, tag count,
  source badges. Drawer: full stat table, flags (exclusive / hidden stats / complex passive /
  requires refreshes / bonus armor / duration reduction / uses), description, purchase requirements
  per act (county / satisfaction / sovereign-tag / material), and reverse links to granting quests
  (→ Quests tab) and unlocking/removing ink knots (→ Dialogues tab). Names/descriptions localize
  in all 6 locales via the global selector.
- Knights tab (2026-08-13): all 24 playable knights from `knights_data.py`. Card: origin, level,
  armor, mastered stats, aliases, equipment/story/quest badges. Filters: search / origin / stat
  threshold / acquired feature tag / liked meal / liked & disliked sovereign tags / toggles for
  preferred equipment, hidden features, alias, romance, conversations, ink story, quest links.
  Drawer: stat table (mastered ★), affinity & demission profile, romance range, sovereign/meal
  preferences, features split into known / unknown / intendant-rumors (characteristics + quest &
  condition LIKE/DISLIKE prefs with loc descriptions), preferred equipment (→ Inventory tab),
  context reactions (dragon_knight/emperor/kingslayer… dialogue keys), affinity & special dialogue
  knots (→ Dialogues tab), the knight's pair conversations with the partner + ink knot, full story
  knot chips, quest links (affinity / unexpected outcome / requires knight) and career info
  (ending path, demission/death audiences, call-back request).
- Ink `if/else` fix (2026-08-14): the compiled-ink walker only understood `if` (a `c:true` divert
  to a `b` branch) and rendered the compiled `else` — an unconditional `-> b` divert in a sibling
  container — as plain unconditional text (e.g. `county_quest_enberg_first_audience`'s
  `victoria_dead` variant said both the "arrived is--" and "arrived is accompanied by a woman
  with--" lines). The walker now recognises that sibling `else` container and emits the "7" gate
  with the negated condition, keeping the if/else in one block. Balanced across the story
  (544 if-blocks ↔ 544 endifs, 299 else gates), incl. nested ifs (De Morgan negation of compound
  conditions); no token-format or frontend change required.
- "What happens" completeness (2026-08-14): the knot drawer's top summary now decodes **all**
  game-state changes, not just a subset. It walks choice **effects** (`eff` arrays) — previously
  skipped entirely — and the full WRITE_SLOT0-style mutation set (`UpdateSovereignValue`,
  `UpdateFunds`, `ChangeTaxes`, `UpdateSatisfaction`, `UpdateServantRomance`, `UnlockTag`,
  `UnlockAudienceRequest`, `UnlockFillerAudiencesPack`, `UnlockSpecialDialogue`,
  `KnightRecruitment`/`Demission`, `CountyRallied`/`Unrallied`/`CountyQuestFailed`,
  `MajorCharacterIntroduction`, `NewCharacterRomanced`, `AddDoleanceForNextCycle`,
  `InjectMurderedKnight`, `KillKnight`, `LocationDestroyed`, `UltimatumTriggered`/`Unset`,
  `GameOver`), plus flags set by passing them as **divert/stitch parameters**
  (the `_seen`/`from_*`/`choice_*` family). Every written flag lists the ink knots that read it
  later, so e.g. `county_quest_southbay_3`'s `lies_to_ligia = true` now points to the follow-up
  knot that gates on it. Pure function-signature params (e.g. `Amount` in `ChangeTaxes`) are
  excluded so ripple rows stay about narrative knots. Frontend-only change (`web/app.js`).
- `UnlockQuest` arg handling fix (2026-08-14): the drawer's "what happens" box was
  treating *every* argument of an `UnlockQuest(id, idx)` call as a separate quest,
  so a modifier index (e.g. `0`, `1`) rendered extra bogus rows ("Unlocks quest 0"). Now
  only the first argument is read, and the id must resolve to a real quest in the
  catalog (drops the demo knot's `placeholder_quest` false positive too). Frontend-only
  change (`web/app.js`).
- Quests "What happens" (2026-08-14): the quest detail drawer now starts a **"What
  happens"** section (mirroring the knot drawer) listing every story-var set/clear the
  quest's rewards cause — success, failure, unexpected outcomes and modifier variants
  — each with the "read in N ink knots" ripple pointing at the knots that consume the
  var (e.g. `quest_basalt_look_underwater` sets `secret_pathway_known`, read later in
  `county_quest_basalt_isles_2`). Reuses the existing `whatFactRow`/`varReadersHtml`
  machinery; frontend-only change (`web/app.js`).
- Special tab styling alignment (2026-08-14): the Special tab never got added to the
  shared filter-sidebar selector list, so its sidebar/reset-button/card-grid rendered
  unstyled and looked unlike the other tabs. Added `#sfilters` / `#sreset` / `#scards`
  to every shared rule (`style.css`), and reordered the Special card to the standard
  `.top → .prev → .meta` structure used by the Dialogues/Quests/Inventory/Knights tabs
  (dropping the redundant static "SpecialInstruction" `.qid` label). Frontend-only.
- Special tab drawer close fix (2026-08-14): Special cards opened their detail via
  `openSpecialDetail(name)` directly, while every other tab's cards go through
  `go(kind, key)` — the function that pushes the history entry. Because opening a
  Special detail never pushed a new location, a later `goClose()` produced a location
  identical to the current `history.state`, so `pushLoc`'s dedup early-returned and
  `closeDetail()` never ran — the drawer stayed open through the ✕ button, backdrop
  and Esc. Cards now call `go("special", name)`, restoring close (+ browser-back)
  behaviour and matching the other three tabs' navigation. Frontend-only
  (`web/app.js`).
- Special card grid fix (2026-08-14): `renderSpecialResults()` created a `.grid`
  wrapper but never used it — cards were appended straight to `#scards`, which is a
  `flex-column` container, so Special cards rendered full-width stacked (one per
  row) instead of the auto-fill grid every other tab uses. Cards are now appended
  to the grid like the other tabs, giving them the same compact size (more per
  screen) and inheriting the existing 2-line `.prev` truncation. Frontend-only
  (`web/app.js`).
- Special tab locale refresh fix (2026-08-14): `switchLocale()` re-rendered the
  Quests/Inventory/Knights tabs but omitted Special. Because Special cards show the
  localized knight name in the evolution badge and the `#sknight` filter lists
  localized knight names, switching locale left the tab stale. `switchLocale()` now
  also clears the special search cache (`_shair`), rebuilds `buildSpecialFilterUI()`,
  and re-renders the cards — matching the other tabs. Frontend-only (`web/app.js`).
- "consumed game-side" honesty + cross-system consistency (2026-08-14): three fixes.
  (1) `varStoryReaders()` no longer drops every `fn: true` knot — only pure
  function-signature params (e.g. `ChangeTaxes`'s `Amount`) are excluded, restoring
  ~271 genuine narrative readers (endings, cutscenes, reactions, conversations),
  incl. `kingslayer_cutscene` as the reader of `ursula_sent_to_kingslayer`.
  Frontend-only (`web/app.js`).
  (2) `special_data.py` now scans unexpected-outcome rewards (`q.un[].rw`) and
  modifier success/failure rewards (`mo.sr`/`mo.fr`) for SPECIAL_INSTRUCTION grants,
  in addition to `q.rw.s`/`q.rw.f` — 5 more instructions gain their granting-quest
  link (incl. `URSULA_DESTROYED_BY_KINGSLAYER` → `quest_ultimatum_kingslayer_ursula`,
  `DULAHAN_HUMAN`, `GOBERTO_SUPRA_ARMORED`, `DULAHAN_HELMET`, `ARRON_KIND`);
  quest-granted 14 → 19.
  (3) the "no other ink knot reads it (consumed game-side)" fallback is now honest:
  `build_app.py` records which ink variables the engine actually reads/writes
  (`get_variable`/`set_variable` calls in `.gd`/`.cs`, `ink_variables_to_reset`
  arrays) into `index.json` ($gs); when no ink knot reads a flag the frontend now
  says "referenced by the game engine (consumed game-side)" if the scan found it,
  else "no game-side reference found (may be vestigial)" — e.g. `kingslayer_fought`
  is genuinely vestigial. Full rebuild (`build_app.py` + `special_data.py`).
- Knight-evolution coverage completeness (2026-08-14): `EVO_DEFS` in `knights_data.py`
  only covered arron/silgur/gwendan/dulahan, so three real special-instruction-driven
  knight states shipped without evolution blocks → no owner-knight link in
  `special.json` and no "Evolution paths" in the Knights drawer. Added definitions
  for goberto (`GOBERTO_SUPRA_ARMORED`: Supra Armor, +2 STR/+2 AGI/+5 CHA/+4 MAG/+4
  LUCK, +10 armor, gains PERFECT_ARMOR protector), ursule (`URSULA_DESTROYED_BY_
  KINGSLAYER`: Destroyed by Kingslayer, high-corruption stat shift from the
  descriptor's `stats_corruption_high`) and oliver (`OLIVER_MAGIC_GAIN`: Mage
  Formation, +8 MAGIC). Knight evolutions 9 → 12, knights with evolution paths
4 → 7; `special.json` now carries the owner knight + effect note for all three
   previously orphaned instructions. Pure `knights_data.py` change + full rebuild.
- Quest knight/item ranking — affinity, efficiency, items (2026-08-14): the quest
  detail drawer now shows three ranked segments between the conditions and the
  Requested-knights rows, scoring only **traits/preferences** (stats like
  STRENGTH/AGILITY are excluded) across the quest's category **and** all its
  conditions:
  1. **Who likes this quest (affinity)** — knight quest-type/condition
     preferences vs category + conditions (+1 per liked match, −1 per disliked).
     Ranks 290 of 312 quests.
  2. **Who is most efficient** — knight **characteristic** tags matched against
     the game's per-category/per-condition efficient/inefficient tag lists (from
     `systems/autoloads/tag_library.tscn`, e.g. Crowd → efficient `VIRGO_SWORD`/
     `POPULAR`, inefficient `TIMID`). Ranks 307 of 312 quests.
  3. **Efficient items** — equipment whose tags match those efficient/inefficient
     lists (e.g. `virgo_sword` on Crowd), sorted best → worst by net tag matches.
    Present for 300 of 312 quests. A knight's features are deduped by
    (type, tag) across the known/unknown/rumor buckets — the game stores one
    preference/characteristic per tag, so the same tag in `u` and `r` is not
    double-counted. Implementation: `quest_data.py` now emits the game's
    efficiency map as `quests.json` `eff` (`{qt, ct}` → tag lists), plus a
    frontend change (`web/app.js`: `questAffinityRanking` /
    `questEfficiencyRanking` / `questEfficientItems`, `.trankrow` in
    `style.css`).
- Test suite (2026-08-15): added `tests/`, a stdlib-only `unittest` suite (no
  pytest, matching the no-runtime-deps philosophy) that locks the build's current
  behaviour in so it can be refactored into smaller modules without breaking
  anything. Run with `python3 tests/run_tests.py` (77 tests, ~1 min; also
  `python3 tests/test_walker.py` per layer). Layers:
  `test_helpers.py` (pure helpers of `build_app.py`), `test_walker.py` (the
  compiled-ink Walker's exact token output on verbatim real-game knots in
  `tests/fixtures/ink_knots.py` — no game root needed), `test_tresfile.py`
  (`.tres`/enum parsing on self-contained fixtures), `test_dist_conformance.py`
  (schema + cross-dataset invariants of the shipped `dist/`, incl. locale
  knot-set parity — no game root needed), `test_data_passes.py` (the four data
  passes over the real game root at the documented volumes; skips if absent),
  `test_build_golden.py` (a fresh build must be byte-identical to the checked-in
  `dist/` — the highest-value regression net; needs game root + pip `zstandard`,
  skips otherwise), and `test_frontend.py` + `frontend_smoke.js` (node DOM-stub
  boot of the full app + `renderDialogue()` across all 922 knots; skips if node
  absent). The frontend probe reads top-level `let` bindings through
  `vm.runInContext` (lexical scope, not globals). Known data quirks the suite
  acknowledges: per-knot token sequences differ from `en` in ~100–200 knots per
  locale (translators restructured lines/markers), and 4 secret quest loc keys
  are untranslated. `dist/` is the golden reference: intentional data changes
  rebuild `dist/` and commit the new golden in the same change.
- Inventory efficiency + complex-passive explainability (2026-08-15): two
  additions to the Inventory tab mirroring what the quest drawer already showed.
  (1) **Quest efficiency on items**: `itemQuestEff()` builds a cached reverse of
  the quest "Efficient items" ranking (item tags vs the game's per-category /
  per-condition efficient/inefficient CharacterTag lists from `quests.json` `eff`)
  — cards now carry "efficient in N quests" / "inefficient in N quests" badges,
  and the item drawer gains "Efficient in quests" / "Inefficient in quests"
  sections listing the ranked quests (best → worst, with the matched tag sources),
  cross-linked into the Quests tab. Frontend-only (`web/app.js`).
  (2) **Complex passive explained**: `has_complex_passive` was a bare flag with no
  indication of what the passive does. The actual effects live in
  `systems/autoloads/special_cases.gd` as CharacterTag-keyed score/damage/reward
  hooks. `inventory_data.py` now mirrors those hooks in a curated
  `PASSIVE_NOTES` map and emits them as `psv` (tag + effect note) per item — e.g.
  `demon_decoction` → "+100 success score on quests already completed before."
  The item drawer shows a "Complex passive" section (with the in-game '+ PASSIVE'
  context) listing each note; the 11 items whose tags have such hooks are covered.
  Full rebuild (`build_app.py` + `inventory_data.py`).
- Item material-consumption reverse links (2026-08-15): shop purchase requirements
  carry the relic material consumed to craft/forge (`EquipmentRequirement.item`,
  e.g. `demonic_sword` → `DEMON_HEART`, `demon_decoction` → `DEMON_HEART`,
  `dragon_spear`/`potion_of_fire_breathing` → `DRAGON_HEART`). These were only
  shown forward ("consumes X" on the crafted item); the material item itself had
  no "where is it used" info. `inventory_data.py` now mirrors each requirement
  back onto the material item as `src.consumed_by` (`{by, shop, act}`), and the
  Inventory drawer shows a "Consumed by" section with clickable links to the
  crafted items — e.g. `demon_heart` now lists Demonic Sword (forge act 3) and
   Demon Decoction (witch act 3), complementing its existing quest/ink removal
   info. Full rebuild (`build_app.py` + `inventory_data.py`) + frontend
   (`web/app.js`).
- Audiences tab (2026-08-15): the sixth tab, answering "what are all these
  'Played as … audience' rows and where do they come from". New
  `audience_data.py` pass emits `dist/audiences.json`: the full 511-audience
  catalog (`k` ink knot / `f` folder / `c` character name keys / decoded `rq`
  firing conditions — the same schema `quests.json` carries), the 34
  `AudienceRequest` resources (`n`/`d` loc keys, `ch`+`ck` character, `fua`
  follow-up audience, `cst` cost, `hd` hidden flag, `exc` excluding audiences,
  `rem` audiences-to-remove, `q` quests granting it as an AUDIENCE_REQUEST
  reward), and a reverse map `rev.qf` (audience → the quests that fire it as a
  success/failure/unexpected follow-up, 60 audiences).
  Frontend: **Audiences** tab with a view toggle (audiences / requests), folder,
  character, has-conditions and fires-after-quest filters, and searchable cards
  (stem, folder badge, condition badge, `↳ quest` badge, request-trigger badge,
  no-knot badge). Drawers cross-link both directions: an audience shows its ink
  knot (→ Dialogues), characters, decoded conditions, firing quests (→ Quests)
  and triggering requests; a request shows its follow-up audience (→ knot +
  audience), character (→ Knights), cost, excluded/removed audiences and
  granting quests (→ Quests). The knot drawer's "Where it comes from" section
  (`knotAudiences`/`knotFuQuests`) was re-pointed from `QUEST.audiences` to the
  new `AUDIENCE` dataset (quests.json keeps its copy for the quest drawer's
  "Follow-up audiences" rows). Tests: `AudiencesDataPassTest` +
  `test_audiences_json_schema` + golden rebuild + `frontend_smoke.js` renders
  both views and opens audience/request/knot drawers; 80 → 86 tests. Full
  rebuild + docs.
- Cross-dataset filter pass (2026-08-15): the Dialogues tab gains a
  **"Where it comes from"** filter group wired to the reverse maps built over
  the last sessions' datasets — checkboxes for played-as-an-audience,
  fires-after-a-quest, reached-from-other-knots, unlocks-a-quest,
  emits-a-special-instruction, grants/removes-items and
  appears-in-knight-dialogue, plus dropdown selects for audience **type**
  (folder), audience **NPC**, the **quest** firing the knot and the
  **special instruction** it emits (`buildLinkFilterUI()` populates them after
  the data passes load; labels localize on locale switch). The ink search
  haystack now also indexes audience folders/NPCs and follow-up quest ids, and
  knot cards carry audience/unlocks/special/knight badges. New lazy reverse
  maps in `web/app.js`: `knotUnlocks()` (from `quests.json` `unlock_knots`),
  `knotSpecials()` (from `special.json` `knots`), `knotItems()` (from
  `inventory.json` `src.ink_unlock/ink_remove`), `knotKnights()` (from
  `knights.json` `story`/`specd`/`afd`/`conv`/`ending`/`demo`/`callback`/
  `death`). Left-panel pass on the other tabs: Quests gained
  has-follow-up-audience + has-modifier-variants toggles (and the reward-type
  filter now covers modifier + unexpected-outcome rewards); Inventory gained
  complex-passive + consumed-by-other-items toggles; Knights gained
  has-evolution-path + has-call-back-request toggles; Audiences gained
  triggered-by-a-request (audience view) + granted-by-a-quest (request view)
  toggles. `frontend_smoke.js` now asserts the new Dialogues filters narrow
  `visibleKnots()` correctly (srcAud/fu/kf/kc/srcUq/srcSp/srcKn, incl.
   `grest_first_grievance` as a doleances/Roland audience). Frontend-only
   (`web/index.html`, `web/app.js`) + smoke test; all 86 tests green, dist
   rebuilt.
- Quest "Efficient items" grouping + chip alignment (2026-08-15): the quest
  drawer's "Efficient items" list is now split into three categories —
  **Relics**, then **Consumables**, then **Mounts** (the order of the game's
  own types; meals/quest items carry no CharacterTags so never appear) — so a
  player can pick the best item per slot instead of one merged best→worst list.
  Its `chip pos`/`chip neg` chips now put the `<efficient/inefficient> <tag>`
  sources inside the chip itself (`<span class="chip pos">efficient DIPLOMACY
  </span>`), matching the affinity / "Who is most efficient" rows instead of a
  bare label + muted `<span>`. The item drawer's "Efficient in quests" /
  "Inefficient in quests" rows use the same shared `effChipHtml()` markup for
  consistency. Frontend-only (`web/app.js`), dist rebuilt, all 86 tests green.
- Test/build speedup (2026-08-15): the data passes re-read the whole game tree
  repeatedly (every pass re-walked `content/` and re-scanned `systems/` enums),
  which on a slow filesystem turned a single build into ~30s of I/O wait and the
  full test suite into a minute+. Now: `TresFile.load()` caches each parsed
  `.tres` per path+mtime/size (all passes in one process reuse the same parse),
  `load_gd_enum` caches `.gd` file texts so the N enum scans read each file once,
  and `test_data_passes` builds every data pass exactly once per process and
  shares it across its test classes (previously `load_quests()` ran 5× and
  `build_audiences()` per test method). `run_tests.py` prints a per-module
  wall-time table. Suite ~1min+ → sub-40s sandbox (≈5s CPU, rest is cold I/O);
  the fast layers stay <2s. Build unchanged byte-for-byte (golden test green).
   Data passes: `quest_data.py`, `inventory_data.py`, `audience_data.py`,
   `knights_data.py`, `evolution_finder.py`, `tests/`. No `dist/` change.
- Collapsible drawer sections (2026-08-15): every detail drawer (knot, quest,
  inventory, knight, special, audience, request) now groups each section header
  (`h4.qsec` / `div.sec`, incl. nested `qsec small` sub-headers) with its
  following content into a click-to-collapse `.secwrap` block. Collapsed state is
  keyed by normalized section title and persisted in `localStorage`
   (`st_tower_csec`), so it survives refreshes and re-opens. Frontend-only
   (`web/app.js` + `web/style.css`), dist rebuilt, smoke test DOM stub gained a
   `createDocumentFragment`, all 86 tests green.
- "Chain of events" in the knot drawer (2026-08-15): the knot detail panel now
  shows the **narrative sequence** the knot belongs to, answering "what happens
  before/after this scene" for the county-quest / scripted / grievance /
  candidacy chains the cross-referencing work had already linked. A new
  `chainEdges()` map builds directed knot→knot edges from the two real
  sequencing mechanisms in the data — doleance scheduling
  (`AddDoleanceForNextCycle` → the scheduled audience's knot, any type) and
  quest-success follow-up audiences (unlocking knot → `fu[0]` audience knot)
  — and `knotChain()` walks unambiguous single hops both ways to produce a
  linear spine (earliest → latest, current highlighted), stopping at branch
  points where the alternatives are listed as **Earlier events** / **Next
  events** chips (failure/unexpected follow-ups and the Gavault/Groveshire
  shared choice root stay as options rather than tangling the spine). E.g.
  `county_quest_enberg_first_audience → county_quest_enberg_audience_2 →
  county_quest_enberg_audience_3_interrogation` renders in order, with the
  final audience + gothild candidacy + Enberg grievance intro as next options.
  Frontend-only (`web/app.js` + `web/style.css`), dist rebuilt, smoke test
  locks the enberg chain order (and that unrelated knots get no chain), all
  86 tests green.
- Branch-only diverts shown in if/else (2026-08-16): a compiled `if/else`
  whose branches are *pure diverts* (no text/effects) used to render as empty
  gates — `_stub_info` collapsed a choice stub's diverts into a single `dest`
  for the choice card, discarding the else-branch target. The walker now keeps
  any divert that appears inside a conditional branch (`7 …1…`) in the flow,
  and surfaces `end`/loop branch outcomes as `(end)`/`(options)` markers, so
  every conditional branch shows where it leads (e.g.
  `county_quest_enberg_audience_2`: `if polmauz_available →
  polmauz_interrogation_phase / else → end_interrogatory_phases`).
- Choice-scoped follow-up content (2026-08-16): choice stubs that carry real
  follow-up narrative/consequences were previously flattened into a single
  sequential stream, so two mutually-exclusive choices sharing a closing branch
  (e.g. the same "who is next" if/else in `county_quest_enberg_audience_2`'s
  `c-3` and `c-4`) rendered as a duplicated sequence with text sandwiched
  between. A choice's own follow-up tokens are now stored **on the choice
  token** (index 7; index 6 = divert args) and rendered nested inside that
  choice card (`web/app.js` `.choice-flow`), so alternatives display as
  alternatives. Metadata scans traverse the nested streams via
  `walk_tokens()` (reverse UnlockQuest/UnlockEquipment links unaffected).
  Tests: updated walker fixtures (`STUB_COND_DIVERT`, `STUB_END_LOOP`) + a
  dist-conformance assertion that index-7 streams are balanced token lists.
  Full rebuild + docs; all 88 tests green.
- Audience-request quest rewards clickable (2026-08-16): a quest's
  `AUDIENCE_REQUEST` reward (e.g. `⚑ Request The assassination sponsor` in
  `quest_enberg_hire_an_assassin`) is now a link into the Audiences tab's
  request drawer via its request stem (the reward's `item_stem`), using the
  existing `requestLink()`/`reqlink` plumbing. The "What happens" section also
  lists such rewards (`Grants audience request …`) as a `📣` fact row. All
  frontend; dist rebuilt, all 88 tests green.

---

## 4. Future extensions (same shell, no new infra)
- Knights / Characters view (24 knight descriptors + per-knight scripts: stats, affinity,
  preferences, gimmicks; knight ↔ quest preference links) — DONE, Knights tab.
- Equipment / Relics view (154 equipment resources, 70 relics; reverse "which quest grants it") — DONE, Inventory tab.
- SpecialInstruction catalog view (71 director switches: emitting knots, granting quests,
  owner knight evolutions) — DONE, Special tab.
- Audiences / Audience-requests view (511 audiences with `ink_path`, 34 requests) — DONE, Audiences tab.
- Save inspector over `game/SaveExtracted/*.json` (real per-run quest states, ink state).

---

## 5. Open decisions / next step
- **Confirm the merge + naming** ("Sovereign Tower Explorer").
- Confirm scope order: Quests first, then knights/equipment later (recommended) vs. all at once.
- Implementation starts after user confirmation.

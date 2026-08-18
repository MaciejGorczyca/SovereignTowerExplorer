# PLAN — Sovereign Tower Explorer (quests + shared systems)

> Status: **IMPLEMENTED (dialogue + quests + inventory + knights + special + audiences) + routes/SEO + shareable deep-link URLs**

---

## 1. What we are building
A static, dependency-free, single-deploy viewer for the data of *Sovereign Tower*
(the decompiled Godot project in `../game/SovereignTowerCode`), as a **single project** that
absorbs the existing `ink_viewer` and renames it **"Sovereign Tower Explorer"**.

Sections (tabs), added incrementally:

1. **Dialogues** — existing ink view, unchanged (already works: 922 knots, filters, drawer, 6 locales).
2. **Quests** — NEW. Filters + detail drawer over the 312 quest contracts + 103 unexpected outcomes (91 quests).
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
- **103 unexpected outcomes** over 91 quests: 90 as `content/unexpected_outcomes/*.tres`
  (`SpecialOutcome`) plus 10 inlined as `SubResource` inside the quest `.tres`; trigger
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
- `build_app.py` now also emits `dist/quests.json` (312 quests, 91 with unexpected outcomes (103 total), 69 modifiers,
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
- Inventory tab (2026-08-13): all 149 equipment resources (65 relics, 29 mounts, 44 consumables,
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
- Special effect cross-links (2026-08-16): the Special tab's cards and drawers
  now surface what each `SpecialInstruction` *does*, not just the signal name.
  `special_data.py` decodes each match-case body in
  `special_instruction_manager.gd` — `unlock_special_dialogue` (→ the ink knot it
  unlocks, via the owning knight's `specd` map), `StoryController.goto` (→ knot,
  resolved through the `SpecialInstructionManager` exports in
  `story_controller.tscn`), `audience_unlocked_for_next_cycle` /
  `add_audience_in_x_cycle` (→ audience resources), `get_knight_from_name` /
  `trigger_dialogues_unlock_for_knight` (→ affected characters), `set_variable`
  and `EndingManager.Endings.*` — and emits them as new `dlg` / `goto` / `auds` /
  `affects` / `vars` / `ending` fields (+ `linked` stat). Frontend: card badges
  and drawer sections (unlocks special dialogue, diverts to, schedules audiences,
  affects characters, sets story variables, ending path) all cross-link to
  Dialogues / Knights / Audiences, e.g. `GIDEON_VICTORIA_DEAD` →
  `gideon_victoria_dead_reaction` and `VICTORIA_DEAD` → Victoria. Full rebuild;
  all 90 tests green.
- Firing conditions / "how to proc" reverse links (2026-08-16): the audience tab
  now knows the **hardcoded cycle** each scripted scene plays in
  (`quest_data.py` parses `content/cycles/cycle_*.tres` into a per-audience
  `cyc`, e.g. `scriptedquest_assassination_attempt` → cycle 7; audience cards
  carry a "cycle N" badge and the drawer explains the hardcoding). Quest data
  previously dropped the follow-up audiences of *modifier* unexpected outcomes —
  `quest_data.py` now resolves each modifier `unexpected_outcomes`'
  `follow_up_audience` (`mo.unfu`, e.g. `contract_cleankeeper_goose_part_two`
  → `chester_candidacy`), and `audience_data.py` folds them into the
  "which quest fires this audience" reverse map (fires-after-quests 60 → 61),
  so the `candidature_chester` line now links back to its goose quest chain.
  Finally, the Dialogues drawer's "Where it comes from" gained a reverse
  special-link row via a new `knotSpecialTriggers()` map: knots that a
  `SpecialInstruction` unlocks (`dlg`) or diverts to (`goto`) now say "Fires
  when the special instruction X is triggered", so
   `gideon_victoria_dead_reaction` correctly requires `GIDEON_VICTORIA_DEAD`
  (previously the *special* knew it unlocked the knot but the *knot* gave no
  clue what fires it). Full rebuild; smoke test locks cycle + reverse-special +
  modifier-follow-up; all 88 tests green.
- Firing conditions everywhere: knot drawer → audience + conditions
  (2026-08-16): the knot drawer's "Where it comes from" was missing the
  conditions that actually *make* a dialogue fire. The `knotAudiences()` reverse
  map dropped the audience's hardcoded cycle (`cyc`), so a knot played by
  `scriptedquest_chester` showed "Played as doleances audience Chester" with no
  hint that it is scripted into the cycle timeline — while the audience drawer
  said "Hardcoded to play at cycle 2". The map now carries `cyc`, the audience
  row links to the exact audience resource (clickable `audiencelink`), and when
  a cycle is known the row states "hardcoded to play at cycle N (scripted into
  the cycle timeline — fires regardless of player actions)". `knotSpecialTriggers()`
  also gained the specials that *schedule* an audience whose knot this is
  (`auds`), so `candidature_gwendan_the_humble` now says it fires when
  `GWENDAN_REFORMED` is triggered (previously only `dlg`/`goto` reverse links
  existed). Frontend-only (`web/app.js`) + smoke test.
- Special firing conditions + character-manager audience scheduling
  (2026-08-16): two new condition sources now reach the Special and Audiences
  tabs. (1) `special_data.py` decodes the `if`-guard lines inside each
  `special_instruction_manager.gd` case body into a `cond` field (multiline
  guards, joined across `\` continuations, are handled too — e.g.
  `ASSASINATION_PLOT_URSULA_FOLLOW_UP` → "only fires when Ursule is at the
  roundtable", `SOUTHBAY/KUTNAR_TARCUS_INTERVENTION` → "only fires when Tarcus
  is at the roundtable and available", `CHECK_FOR_EPICRATE_*` → Epicrate
  availability, `TRIGGER_RUPIN_APOLOGIES` → Rupin not recruited,
  `SET_UP_FOR_TOWER_DESTRUCTION` → Tower-Destruction ending path,
  `BRING_BACK_TRAITOR` → traitor quest still running); the Special drawer shows
  a "Firing conditions" section and cards get a "conditional" badge. (2)
  `character_special_instructions_manager.gd` signal
  handlers that schedule audiences as a side effect of a special instruction
  (`_on_gwendan_reformed` → `gwendan_humble_candidacy` in ~5 cycles,
  `arron_set_violent` → `arron_dragon_heart_gimmick`, `arron_set_kind` →
  `arron_babydragon_gimmick`, plus knight-death `dulahan_candidacy`) are decoded
  via `load_char_aud_schedules()` and folded into the instruction's `auds` + note;
  the audience drawer gains a "Scheduled by special instruction" reverse section
  (`audSpecials()`), so an audience now shows *who* makes it play. Full rebuild;
  smoke + data-pass tests lock the cycle carry, the audience→special reverse and
  the gwendan/arron scheduled audiences; all 88 tests green.
- Knot-displayed quest ids stay visible (2026-08-16): wherever a knot surfaces a
  quest id as its localized name — the "What happens" `Unlocks quest` row, the
  "Where it comes from" `Fires after` row, and the inline `UnlockQuest` args in
  choice effects / function calls / state rows — the raw internal id now renders
  muted next to the name (e.g. `Hire an assassin (quest_enberg_hire_an_assassin)`),
  so the id stays Ctrl+F-findable without hunting in the ink files. New
  `questIdLink()` helper (`web/app.js`, used only in knot contexts; the Quests /
  Inventory / Knights / Special / Audiences tabs keep the name-only `questLink`)
  + a `.questlink .qid` muted-mono style (`web/style.css`). Frontend-only; all 88
  tests green.
- Director-scheduled audiences (2026-08-16): the 20 narrated scenes the
  `CyclesManager` game-director schedules (channel 8 of the audience-condition
  research) now carry real source notes instead of showing nothing. New
  `quest_data.py` `load_director_audiences()` parses the `CyclesManager` node of
  `systems/autoloads/cycles_manager.tscn` (serpent-knight reset, the 4 civil-war
  revolts, the act-1/2/3 ending victories, Arlin's act-2/3 intros, Rupin's 10
  corruption-gated grievances) and bakes human-readable "Director scene: …" notes
  into a per-audience `dir` field (`quests.json` + `audiences.json`, still
  byte-equal); the civil-war thresholds are parsed live from `cycles_manager.gd`
  (`≤ 18/20/22` at cycles 24/29/34). The Audiences drawer gains a "Directed by
  the cycle director" section, the Dialogues knot "Where it comes from" rows show
  the notes inline, and audience search includes them. Stats + `with_director`;
  tests lock the 20-stem set, the threshold text and the JSON schema; all 89
  tests green.
- Special-intervention audiences (2026-08-16): channel 9 of the audience
  condition research — the narrated scenes the `SpecialInterventionsManager`
  node of `cycles_manager.tscn` plays directly. New `quest_data.py`
  `load_special_interventions()` parses that node (the ultimatum second
  encounters, the four king/dragon allied interventions, the traitor's-plot
  intro + murder, Dulahan's human-form introduction, Victoria's betrayal, the
  nobles' cycle-zero intro, the wolf candidacy, Arlin's reunited-roundtable
  reaction and the 15 `brizh_grievance_the_courier_bringing_quests*` courier
  scenes per act) and hand-writes the guard logic of
  `special_interventions_manager.gd` (`check_for_audiences_phase_special_
  intervention` :44 / `check_for_audience_phase_end_special_intervention` :77)
  into per-audience `dir` notes prefixed "Special intervention:" (same baked
  string style as the director `dir` rows and special.json `cond`). Covers
  `intervention_*`, `scriptedquest_traitors_plot_*`, `intro_nobleman`,
  `wolf_candidacy`, `dulahan_gimmick_intro_human_possession`,
  `scriptedquest_victoria_events_5_betraying`, the two
  `*_ultimatum_before_the_storm` second encounters and all couriers — 28
  audiences (13 single + 15 courier). The Audiences drawer heading is
  generalized to "Directed by the game director" and the stats block gains a
  separate `with_intervention` count (director 20 / interventions 28 stay
  distinct). Audiences 18% → 46% of the catalogue now shows a real source
  (343 no-info before → 28 covered, 246 still no-info: filler 236 + doleances
  minus the covered plots, demissions, death-follow-ups). Tests: new
  `test_intervention_sources` + `with_intervention` assertion; 90 tests green.
- Knight death follow-ups (2026-08-16): channel 10 of the audience-condition
  research — the narrated scenes that play when a knight dies. New
  `quest_data.py` `load_knight_death_followups()` parses each knight
  descriptor's `death_follow_up_audiences_names`
  (`content/character_descriptors/knights/*.tres`) and reverse-maps them onto
  the audience catalog as a new `dd` field (`[[knight_stem, "death"], …]`, the
  same field E4 will later extend with `"demission"` entries). Covers the 7
  `*_death_announcement` / `ursula_new_gimmick_*` audiences — angelica, gideon,
  goberto and gwendan each announce their own death, while Ursule's three
  new-gimmick scenes are the corruption-tiered variants (low/mid/high by death
  count, or the high one during the kingslayer-ultimatum quest) her script
  (`ursula.gd:47`) picks from. Gideon suppresses his while he is the traitor
  during an AUDIENCE phase (`gideon.gd:24`); the scenes are queued for the next
  cycle and erased from `played_audiences` first so they can re-fire
  (knight.gd:139-152). The Audiences drawer gains a "Fires when a knight dies"
  section, the Dialogues knot "Where it comes from" rows append a
  "fires when <knight> dies" suffix, and audience search indexes the knight
  names. Stats + `with_death_followup` (7). Tests: `test_death_followup_sources`
  + `dd` schema assertions in both conformance tests + smoke assertions; 91
  tests green.
- Knight demissions (2026-08-16): channel 11 of the audience-condition
  research — the narrated scenes that play when a knight leaves the
  roundtable. New `quest_data.py` `load_knight_demissions()` parses every
  descriptor's `roundtable_demission_audience_name`
  (`content/character_descriptors/knights/*.tres`) and reverse-maps it onto the
  audience catalog as `dd: [knight, "demission"]` entries (the same field E3
  fills with `"death"`), plus the per-knight variant fields whose subclasses
  override `get_demission_path()` (knight.gd:196) while the knight is in a
  special state: arron.gd:143 `_violent` (Dragonheart form), dulahan.gd:116
  `_human` / `_possessed` (human body vs cursed helmet), edith.gd:81
  `_possessed`, gwendan.gd:161 `_humbled` (her reformed humble candidacy, which
  lives in content/audiences/candidacies). Each variant entry carries an
  optional third `[knight, "demission", label]` element ("violent"/"human"/
  "possessed"/"humbled"). At the next cycle reset once the knight's affinity
  hits its demission threshold, `check_for_demission()` (knight.gd:183) queues
  the chosen scene (no `played_audiences` erase — a demission plays once).
  Covers all 24 base `knight_leaving_*` scenes + the 5 variants = 29 audiences
  (the straggler `knight_leaving_gwendan_humble.tres` has no field pointing at
  it and stays source-less). The Audiences drawer's dd block now splits into
  "Fires when a knight dies" vs "Fires when a knight leaves the roundtable"
  (with the variant note), the Dialogues knot "Where it comes from" rows
  render "fires when <knight> leaves…", and audience search indexes the knight
  names + "leaves the roundtable". Stats + `with_demission` (29);
  `with_death_followup` redefined to count only `"death"` dd entries so the two
  channels stay distinct. Tests: `test_demission_sources` + `dd` schema allows
  the `(2,3)`-length entries in both conformance tests + smoke assertions; 92
  tests green.
- Filler packs (2026-08-16): channel 13 of the audience-condition research —
  the 236 `content/filler_audiences/*.tres` FillerAudience wrappers. New
  `quest_data.py` `load_filler_packs()` parses the wrappers (audience ref +
  `targeted_pop_category` + `corruption_score`) and groups them by the
  `[node name="FillerAudiencesManager"]` pack arrays of cycles_manager.tscn,
  mapping each array to the runtime unlock name of `filler_audiences_manager.gd`
  `_unlock_audience_pack` (:63): the four representative packs
  (academician/aristocrat/shopkeeper/worker, always available from the start)
  + the 23 region/unlock packs (clovermont, grest, … enberg, groveshire,
  gavault, …). Each audience carries a new `fl: [pack, pop_cat, corruption]`
  field (null fields when unset) — 234 of the 237 filler scenes covered (the 2
  duplicate-wrapper audiences + the unwrapped `grest_grievance_emergency` stay
  source-less). The frontend (`fillerPackUnlocks()` re-scanning index.json, same
  pattern as `doleanceSchedulers`) shows which first-grievance knot unlocks each
  pack: the Audiences drawer gains a "Filler scene" section ("Filler scene of
  the <pack> pack — targeted at <population> — corruption tier N — unlocked by
  <knot> — random pick to fill a cycle, corruption-weighted", or "available from
  the start"), the Dialogues knot "Where it comes from" rows append the note,
  the audience cards carry a `filler · <pack>` badge and search indexes the
  pack/population/knot names. Stats + `with_filler` (234). Tests:
  `test_filler_pack_sources` + `fl` schema assertions in both conformance tests
  + smoke assertions; 93 tests green.
- Call-back unlock triggers (2026-08-16): channel 12 of the audience-condition
  research — the 24 `call_back_*` audience requests (e.g. `call_back_angelica`
  → `angelica_come_back`). These are unlocked from ink when the knight leaves
  the roundtable (world_manager.gd:197-198,229) — never granted by a quest —
  and inviting the knight back is their whole purpose. `audience_data.py` now
  marks each with `cb: true` (+ `with_callbacks` stat = 24); the request cards
  gain a `call-back` badge, the request drawer shows a "Call-back" section
  ("Unlocked when <knight> leaves the roundtable — a call-back request offering
  to invite them back", knight cross-linked to the Knights tab), and request
  search indexes "call-back" / "leaves the roundtable" / "invite back". Tests:
  `test_callback_request_sources` (24 requests, knight-descriptor mapping for
  23 knights + alwena's field-less request) + a `cb`-consistency assertion in
  `test_dist_conformance`; 94 tests green.
- Special-instruction guard audit (2026-08-17): E7 of the audience-condition
  research. The special-instruction `cond` decoding only covered 9 of the
  manager's guarded cases (7 `COND_PATTERNS`, and the last case's body was
  polluted by the function tail + the `_is_epicrate_available` helper). Now:
  (1) the case-body parser stops at the end of the match table, so
  `DRAGON_KNIGHT_DEAD` and friends carry only their own lines; (2) the pattern
  table is extended with the golden-key quest guards (`GOLKEN_KEY_FOUND_*`),
  the almor-duel quest guard (`SET_ALMOR_WINNER_GENDER`), the epicrate
  availability variants, the serpent/brimwood variable guards and the
  cycle-bounds guards — every case with an `if`-guard (12) now decodes a `cond`
  row; (3) the `_is_epicrate_available()` helper's sub-guards (busy, dead,
  brimwood trial, serpent knight, cycle-bounds, Epicrate/Marian audience) are
  decoded once and inherited by the `CHECK_FOR_EPICRATE_*` cases that delegate
  to it; (4) `build_special` prints a guard audit task-list of any case whose
  guards still decode to nothing (currently clean). Tests: cond assertions in
  `test_data_passes` (golden-key, almor, epicrate sub-guards, guarded-iff-cond)
  + a `cond` schema check in `test_dist_conformance`; 94 tests green.
- County-introduction sources (2026-08-17): task A of the audience-condition
  research — the narrated scene that introduces each county (the
  `county_quest_<id>_1` audiences) was showing almost no "where it comes from"
  data (`county_quest_enberg_1` only exposed its `yohav_dead` requirement).
  New `quest_data.py` `load_county_introductions()` parses every
  `content/world/counties/*.tres` `county_introduction` field and reverse-maps
  it onto the catalog as `ci: [county ink id, name key]` (7 audiences:
  `county_quest_{almor,brimwood,enberg,isle_of_basalt,kutnar,moonvale,southbay}_1`)
  — the county intros are scheduled by the ActManager (act 1→2 / 2→3
  transition intros with a per-neighbor shuffle delay, or right after a
  neighboring county is rallied; act_manager.gd:58,102). The Audiences drawer
  gains a "County introduction" section (source note + ActManager-only
  scheduler explanation), the Dialogues knot "Where it comes from" rows append
  the note, cards carry a `county intro · <name>` badge and search indexes the
  county names. Stats + `with_county_intro` (7). Tests:
  `test_county_intro_sources` + `ci` schema/stat assertions in both conformance
  tests + smoke assertions; 95 tests green.
- Ultimatum follow-up context (2026-08-17): task B of the audience-condition
  research — the ultimatum outcome scenes (e.g. `kingslayer_ultimatum_faillure`)
  showed their quest-failure links but no ultimatum-level context (the hard
  deadline cycle, the condition sets). New `quest_data.py` `load_ultimatums()`
  parses the 3 `content/ultimatums/*.tres` (`kingslayer` deadline 23,
  `dragon_knight` 8, `emperor` 45) plus `_decode_ultimatum_condition()` for the
  three `*_conditions_set` arrays (MIN_RALLIED_COUNTIES / SATISFACTION_
  REQUIREMENT with PopulationCategory name / MIN_FUNDS), and reverse-maps the
  follow-up quests' success/failure audiences + unexpected-outcome follow-ups
  onto the catalog as `um: [ultimatum_id, target_cycle]` + `umc` (6 audiences:
  `kingslayer_ultimatum_{victory,faillure}`, `dragon_knight_ultimatum_*`,
  `ultimatum_emperor_{victory,defeat}`) — applied inside `load_audience_catalog()`
  so `quests.json` / `audiences.json` stay byte-equal. The Audiences drawer
  gains an "Ultimatum follow-up" section ("Ultimatum <id> — follow-up quest
  failure/success — hard deadline cycle <N> — condition set: …"), the Dialogues
  knot "Where it comes from" rows append the note, cards carry an
  `ultimatum · <id>` badge and search indexes the ultimatum id / deadline /
  condition notes. Stats + `with_ultimatum` (6). Tests:
`test_ultimatum_sources` + `um`/`umc` schema/stat assertions in both
   conformance tests + smoke assertions; 96 tests green.
- Audiences "Conditions" consolidation (2026-08-17): task C of the
  audience-condition research — the audience drawer used to scatter every gate
  across separate sections ("Scheduled as doleance by", "Scheduled by special
  instruction", "Directed by the game director", "Filler scene", "Hardcoded to
  play at cycle", "Firing conditions", "Fires when a knight dies / leaves",
  "Fires after", "Triggered by request") plus the county-intro and ultimatum
  blocks. All of it now renders as ONE "Conditions" segment listing every gate
  in one place, from a single shared source: new `audienceGates()` /
  `audienceConditionRows()` / `audienceConditionCount()` helpers that fold the
  story/knight requirements (`rq`, with "Story gate"/"Knight gate"/"Plays only
  once" labels), hardcoded cycle, quest follow-ups, requests (with cost), the
  doleance schedulers, the special-instruction schedulers, the director /
  intervention notes, knight death/demission triggers, filler pack, county
  introduction and ultimatum follow-up into one ordered row list. The Dialogues
  knot drawer's "Where it comes from" audience rows reuse the same rows
  (dropping the duplicated quest/special kinds that have their own knot-level
  lines), the audience cards' badge now counts all gating conditions (not just
  `rq`), the Audiences filter's "has firing conditions" became "has gating
  conditions" and now matches any channel (rq/cyc/request/quest/doleance/
  special/ci/um/dd/fl), and `aHaystack` indexes the doleance knots + special
  schedulers. The `kName()` helper is null-safe (audience cards render before
  KNIGHTS loads). Frontend-only + smoke assertions; 96 tests green.
- Free-time dialogue sources (2026-08-17): Task J of the knot-source research
  (REPORT_DIALOGUES.md) — the ~240 knots played by the FreeTimeDialogue
  machinery (affinity dialogs, knight conversations, reactions/special dialogs)
  used to show no "Where it comes from" data at all. New `dialogue_data.py`
  emits `dist/dialogues.json`: 235 free-time dialogs (82 affinity, 77 knight
  conversations incl. the inline `candidature_alwena`, 76 reactions), each with
  its locating room, the affinity-conversation gates (`aff`: knight + min
  affinity rank, `aff0` intro flag, plus the state/room gates — arron
  violent/kind, dulahan body-possession, edith possessed, gwendan
  reformed/repaid, gideon known-origin insert at rank 5, ursula's affinity-9
  if-dead dialog, angelica's on-death replacement, rufus post-stables and the
  victoria/wolf witch-tower room dialogs), the conversation partners, per-state
  exclusions and `character_manager.tscn` pick order (`conv`), and the unlock
  sources (`unl`): every one of the 98 ink `UnlockSpecialDialogue` call sites
  resolves (the four `marriage` sites inside
  `scriptedquest_civil_war_event_nobles_revolt` + Gwendan's runtime
  `marriage`/`romance_completed` forks — her annoying/humble and
  pretentious/humble reactions both fire from the same ink site), plus the
  `romance_completed`/`golden_key` code unlocks, the dragon-egg/dragon-heart/
  cursed-helmet item gates and the special-instruction `dlg` signals. The
  Dialogues knot drawer gains per-knot source rows ("Played as an affinity
  dialogue of <x> (requires affinity ≥ N)", "Knight conversation: … plays once,
  free time", "Reaction / special dialogue of <x>: unlocked by <knot|special|
  romance|item>"), the Dialogues search indexes the new texts, and a new "has a
  free-time dialogue source" source toggle filters the knot list. 3 dead
  FreeTimeDialogue resources (gwendan_affinity_minus_1, the two un-referenced
  demon traitor-plot reactions — referenced in no descriptor/manager and with no
  compiled knot) stay catalogued but source-less and are exempted from the knot
  cross-checks. Stats: 82/77/76/235 · 85 with unlock sources · 98 ink sites
  resolved. Tests: `DialoguesDataPassTest` (volume, affinity thresholds,
  conversation gates, unlock resolution) + `test_dialogues_schema` in
  test_dist_conformance + smoke assertions; 101 tests green.

- Ending sources (2026-08-17): Task K of the knot-source research
  (REPORT_DIALOGUES.md) — the ~40 `ending`-category knots (which are neither
  audiences/quests/diverts nor free-time dialogues) used to show no "Where it
  comes from" data at all. New `ending_data.py` emits `dist/endings.json`
  (6 ending types
  in `types`: WAR/PEACE_TREATY/MARRY/SURRENDER/TOWER_DESTRUCTION each mapped to
  its cutscene knot (the EndingManager's `endings_cutscenes_paths` in
  act_manager.tscn + the `Endings` enum) and carrying its `SWITCH_ENDING_*_PATH`
  special-instruction switch, plus the corruption-gated DEMON_STATE epilogue as
  a `note` — no switch exists for it; the 31 per-character ending vignettes in
  `vignettes` (24 knights + 7 servants — the same descriptors Task J parses, via
  a shared `dialogue_data.load_ending_paths()` helper — keyed by character ink
  id as the ServantEndingCutscene routes them, e.g. `intendant`→`alwena_ending`,
  `blacksmith`→`carina_ending`, `ursule`→`ursula_ending`, gated by alive +
  at-the-roundtable (recruited, for servants) when `trigger_end()` runs) and the
  2 code-played specials in `specials` (`hildegard_singing_ending` ← `HILDEGARD_SONG`
  special instruction; `demon_back_in_time_ending_proposal` ← the demon-room
  scene). The Dialogues knot drawer adds per-knot rows "Ending vignette of <x> —
  plays at the end while <x> is alive and at the roundtable" / "Ending cutscene
  (<TYPE>)" / the special notes, and the Dialogues search indexes the new texts.
  39 of the 41 ending knots are covered (the 2 leftovers are Carina's act-1/2
  reactions — `reaction` dialogs already catalogued in dialogues.json). Tests:
  `EndingsDataPassTest` (types/vignettes/specials + full ending-knot coverage)
  + `test_endings_schema` in test_dist_conformance + smoke assertions; 106 tests
  green.
- Donation UI (2026-08-17): a gold "♥ Support" pill sits in the topbar right
  after the tab buttons (full label on every screen size — never collapses to
  an icon), opening a centered donation modal (z-60, above the z-50 detail
  drawer) with Stripe + PayPal links (`target="_blank"`) and a "Not now"
  dismiss. An auto-ask fires from `openDetailBy()` (covers all seven detail
  kinds + back/forward) but is frequency-capped in `localStorage`
  (`st_tower_donate`): a brand-new visitor is never asked until **10 minutes**
  after their first engaged card open (grace), then at most once per
  **22 hours** (cooldown, recorded at show time). Esc closes the modal first
  (the drawer second), the modal has its own dimmed backdrop and never closes
  an open drawer, and the drawer's close also dismisses the modal. Ship-ready:
  full suite green (105 tests) + logic verified in a VM harness.
- Request unlock sources in the request drawer (2026-08-17): task N1 of the
  audience-condition research — `rowan_request`-style AudienceRequests rendered
  their follow-up audience/cost/exclusion but not *where they come from*. The
  request drawer now shows an **"Unlocked by ink"** section: `requestUnlocks()`
  inverts the existing `knotRequests()` reverse map (the `UnlockAudienceRequest`
  call sites) per request stem — all 34 requests resolve ≥1 unlock knot, e.g.
  `rowan_request` ← `arlin_introduction_to_act_2` (+ the recruitment knot's
  re-unlock), `bettie_request_victoria` ← the enberg finale + the victoria intro
  knot, the `call_back_*` requests ← their `*_come_back_later` / candidacy
  knots. Each unlock knot cross-links into the Dialogues tab; a curated gate
  note explains the story-gated branch (rowan: the unlock sits in
  `arlin_introduction_to_act_2`'s `!groom_recruited` branch — only offered when
  the act-2 intro plays and the groom has not been recruited yet; the
  AUDIENCE_PLAYED exclusion still applies once the follow-up audience has run).
  Request cards carry an "unlocked by N knots" chip and request search indexes
  the unlock knot names. Frontend-only (`web/app.js`) + smoke assertions +
  docs; full suite green.
- Divert-reached sub-scene audiences (2026-08-17): task N2 of the audience-condition
  research — 14 audiences still showed no "Conditions" rows because they are never
  queued by any channel: their ink knot is reached via an **ink divert** inside
  another, scheduled audience's scene (or shares its ink path with it). `audienceGates()`
  now appends two label rows to the base scheduling channels (only for audiences
  with no base conditions, so existing gated audiences are untouched): **divt**
  "Plays inside <parent audience> — an ink-divert sub-scene" resolved by walking the
  knot→divert graph upward to the nearest scheduled ancestor audience
  (`divertInParent`, memoized) — `county_quest_brimwood_3_testimony_2` + the 6
  brimwood-trial interventions → `county_quest_brimwood_3_before_testimony`,
  `intervention_childeric_county_quest_almor_audience_3` → `county_quest_almor_3`,
  the childeric/ligia/tarcus candidacies → their county finals,
  `goberto_gimmick_introduction_new_armor` → `county_quest_almor_final_unexpected`,
  `intro_dragon_knight_grievance` → `intro_nobleman` — and **dup** "Same scene as
  <scheduled sibling>" for same-ink duplicate resources
  (`county_quest_brimwood_3_testimony_1` = the scheduled
  `county_quest_brimwood_3_before_testimony`). Rows count as gating conditions
  (badge + `acond` filter) and index into audience search. Frontend-only
  (`web/app.js`) + smoke assertions + docs; full suite green.
- Inline sub-resource special outcomes (2026-08-17): task N3 of the audience-condition
  research — `quest_data.py` only decoded `SpecialOutcome`s referenced as
  **ExtResource files**, so quests that inline the outcome as a `SubResource` in
  their own `.tres` silently produced `un: []`. 9 quests were affected
  (`quest_southbay_political_instabilities` + the 8 competition/grievance
  contracts: anveld demon hunt, avalon ice skating, hydra hunt, moonvale magic
  council spying, rozenn music, spearfishing, volga knife throwing, wolf
  invasion). The `SpecialOutcome` ref resolver now reads both forms (external
  file stem vs. synthesized `<quest>_unexpected[+_N]` id for inline), so 10
  condition-bearing unexpected outcomes decode: the knight conditions (tarcus /
  gideon / oliver / silgur / victoria / the_wolf / rufus), the hydra stat gate,
  the anveld demon-tag requirement, per-outcome rewards and follow-up audiences.
  `quest_southbay_political_instabilities` gains `un` with `k:[tarcus]` +
  `fu: county_quest_southbay_final_father_dead_tarcus_unexpected`, which now
  appears in `audiences.json` `rev.qf` as an unexpected follow-up (61 → 62
  fired-after-quest audiences); quests-with-unexpected 82 → 91. The modifier
  `un` loop and the ultimatum reverse-map read the same refs both ways.
  Data-layer (`quest_data.py`) + tests + docs; rebuild `dist/`; suite green.
- Code-scheduled knight events (2026-08-17): task N4 of the audience-condition
  research — a handful of audiences are queued directly by game code rather than
  by a quest / doleance / request / special-`auds` / director / divert channel,
  so their drawer still showed no Conditions. `quest_data.py` now mines those
  sources into an additive **`code: [[channel, note], …]`** audience field
  (channel 14): the knight descriptors' `new_gimmick_intro_path`
  (edith.tres:86 → `edith_gimmick_introduction_demon_possession`, queued by
  `update_for_kill()` after a killing quest completes with Edith assigned while
  not yet possessed); `character_manager.tscn`'s `family_reunion_audience`
  (→ `lost_child_plotline_groveshire_gavault_confrontation`, the 7-gate
  `_check_for_family_reunion` check) and `dulahan_arrival`
  (→ `dulahan_candidacy`, queued 2 cycles after Goberto dies); and the
  `KUTNAR_TARCUS_INTERVENTION` special-`goto`
  (→ `intervention_tarcus_county_quest_kutnar_first_audience`, re-stated with
  its roundtable/available gate). The frontend renders `code` rows in the
  Consolidated Conditions box (`CODE_SOURCE_LABELS`: Knight gimmick / Family
  reunion / Knight death / Special instruction), counts them in the gating badge
  + `acond` filter and indexes the notes into audience search. Data-layer
(`quest_data.py`) + frontend (`web/app.js`) + tests + docs; rebuild `dist/`;
   suite green.
- Legacy-orphan flags (2026-08-17): task N5 — the final no-conditions audit's
  legacy family. 6 audience resources are never queued by any channel in the
  shipped game: the four `*_classic_recruitment` scenes (dead — their ink path
  never got a compiled knot, the request recruitment mechanic superseded them)
  and the two `brizh_*_grievance_first_meeting` scenes (real knots that exist
  in the compiled story but that no doleance / divert / quest / request /
  special / director / code channel ever references). `quest_data.py` now marks
  them with an additive **`unused: true` + `unote`** audience field
  (channel 15, `load_unused_audiences()` — "legacy recruitment — superseded by
  the … request recruitment; never scheduled in the shipped game" /
  "orphan knot — never referenced by any scheduler; not played in the shipped
  game"). The frontend renders `unote` as a "Legacy resource" row in the
  Consolidated Conditions box, counts it in the gating badge + `acond` filter,
  shows a dashed `legacy · unused` card badge, indexes the note into audience
  search and carries it into the knot drawer's "Where it comes from" audience
  rows (the brizh orphan knots). Covers the last 6 of the 28 no-conditions
  audiences (26/28 solved by N1–N5; the 2+1 documented E4/E5 strays need no
code). Data-layer (`quest_data.py`) + frontend (`web/app.js` + `web/style.css`)
   + tests + docs; rebuild `dist/`; suite green.
- No duplicate item cards (2026-08-18): `.tres` copies of one equipment sharing a
  canonical id (relic_ID / mount_ID / …) were rendered as separate Inventory
  cards — e.g. `demon_heart`, `demon_heart_2/3/4` all = `DEMON_HEART`, each with
  a single "granted by" quest. `inventory_data.py` now merges same-id copies
  into one entry keyed by the base stem, unioning every copy's sources
  (granted-by quests, shop requirements, ink knots, consumed-by materials); the
  surviving resource names live on the item as `stems` and stay resolvable as
  link aliases (quest `item_stem`, knight preferred gear). Fixes the Inventory
  card count 154 → 149 (RELIC 70 → 65).
- Ink `RemoveEquipment`/`UnlockEquipment` choice effects (2026-08-18): the
  item → "Removed in the story" reverse map only scanned top-level
  instructions, missing calls attached to a choice stub (`t[5]` funcs) — e.g.
  `scriptedquest_civil_war_event_scholars_revolt` sacrificing the Dragon/Demon
  Heart. `build_app.py` and `inventory_data.ink_equip_maps` now scan choice-func
  calls too, and `attach_ink_sources` dedupes repeated knots. `dragon_heart` and
  `demon_heart` now list the scholars-revolt knot under "Removed in the story".
- No-duplicate-cards tests (2026-08-18): `test_no_duplicate_item_cards` in
  `test_data_passes.py` (on the real game volumes) and in `test_dist_conformance.py`
  (on shipped dist) assert every inventory item id is unique, so a merged-away
  copy can never render as a second card again. `test_volume` updated to 149.
- Per-route static pages + SEO shells (2026-08-18): `route_pages.py` (new, stdlib, CLI
  `[out_dir] [--site-base <url>]`) prerenders every URL the SPA can open as a
  trailing-slash `<route>/index.html` under `dist/` — the six tab pages, all 922 knot /
  312 quest / 149 item / 24 knight / 71 special / 511 audience detail pages and the 34
  `audiences/requests/*` request pages (2,029 shells at the current volumes). Each shell
  is the shared `web/index.html` markup with depth-correct (`../`-deep) asset tags and a
  per-route `<title>` / meta description / `<link rel=canonical>` / Open Graph / JSON-LD
  head; detail pages embed a visible `.seo-teaser` (`<h1>` + category/prev/name/desc
  text, BBCode stripped, from the six `dist/*.json` alone — loc keys resolved en-first via
  `quests.json#loc`). Routes are derived from the JSON key maps in `out_dir` (sorted →
  byte-identical rebuilds), so they can never drift from the data, and the `/dialogues/`
  alias canonicalises to `/`. `build_app.py` gained the `--site-base` flag +
  `SITE_BASE` env/`viewer.env` key (resolved with the same CLI > env > .env > default
  precedence as the path keys) and calls the pass after `copy_web_assets`. `web/index.html`
  gained the six static `.tabdesc` description blocks (one per results column, copied
  verbatim into every shell); `web/style.css` styles `.tabdesc` + `.seo-teaser`. Tests:
  new `tests/test_route_pages.py` (route counts ↔ dataset keys both directions — no orphan
  route dirs, asset-prefix depth, title/description/canonical, `.seo-teaser`, smoke-stub
  friendliness) + unit tests for the `route_pages` helpers. Full rebuild + golden `dist/`
  with the new route tree.
- Sitemap + robots (2026-08-18): `route_pages.py` now also emits `dist/sitemap.xml` and
  `dist/robots.txt` in the same pass. The sitemap lists every crawlable URL — `/` + the five
  non-alias tab pages (the `/dialogues/` alias canonicalises to `/` and is excluded) + all
  922 knot / 312 quest / 149 item / 24 knight / 71 special / 511 audience / 34 request
  detail routes (2,029 locs at the current volumes) — in stable sorted order with no
  `lastmod`/`priority`/`changefreq`, root-relative or absolute URLs per `SITE_BASE` →
  byte-identical rebuilds. `robots.txt` is `User-agent: *` / `Allow: /` plus a `Sitemap:`
  line only when `SITE_BASE` is set. Tests: new `SitemapRobotsTest` in
  `test_dist_conformance.py` (sitemap parses via `xml.etree`; loc count == Σ datasets +
  tabs; every loc maps to a route page and every route page — except `/dialogues/` — has a
  loc; trailing slashes; no timestamps; robots exists without a `Sitemap:` line in the
  default build). Full rebuild + golden `dist/` with the new files.
- Per-entity SEO text helpers (2026-08-18): `route_pages.py`'s `tkey`/`clean`/`esc` and the
  per-kind `*_bits` teaser builders (quest/knot/knight/item/special/audience/request) now
  have dedicated unit tests — new `TeaserHelpersTest` in `test_route_pages.py` covers one
  known shipped-dist entry per kind (e.g. `contract_cleankeeper_goose_part_two` resolves a
  non-empty en description; `ARRON_KIND` humanises its note prefix to "Arron → Kind") plus a
  whole-corpus invariant (every entity's description/teaser is BBCode- and fragment-free).
  Fix in the same change: `BBC_RE` no longer requires the closing `]`, so a BBCode tag cut
  in half by the 60-char `prev` truncation can no longer leak a `[/font_s` or bare `[/` into
  meta descriptions — `gothild_accept_recruit_reaction` and
  `scriptedquest_follow_up_assassination_attempt_free_prisoner` (and its audience page) were
  affected. Full rebuild + golden `dist/` with the cleaned shells.
- Shareable URL deep links (2026-08-18): the SPA previously kept its whole
  navigation state in `history.state` and never touched the URL, so every open
  entry was `/` and a shared link always landed on the home tab. `web/app.js`
  now maps locations onto the `route_pages.py` URL scheme with an exact inverse
  pair — `urlFromLoc(loc)` (`/`, `/dialogues/<knot>/`, `/quests/`, `/quests/<id>/`,
  `/inventory/<stem>/`, `/knights/<stem>/`, `/special/<name>/`,
  `/audiences/<stem>/`, `/audiences/requests/<stem>/`) and `locFromUrl(path)` —
  and `pushLoc`/`go`/`goTab`/`goClose` write the path with every `pushState`
  (dedupe intact). Boot: `init()` parses `location.pathname` into the initial
  location (`history.replaceState`, guarded `typeof location === "object"` for
  the headless smoke VM) and calls `applyLoc()` once after the datasets load, so
  a directly-linked `/quests/<id>/` (or knot/knight/item/special/audience/
  request) opens straight into that drawer; `popstate` is deferred until then
  (`navReady`) and prefers `history.state`, falling back to the URL. Unknown /
  mistyped paths degrade to the default Dialogues tab through the existing
  `validLoc` guard. Frontend-only (`web/app.js`) + smoke tests (new `location`
  stub — the boot URL is a knot deep link whose drawer must open; urlFromLoc/
  locFromUrl round-trips for all seven kinds incl. requests; applyLoc/go/goClose
  URL + drawer assertions) + docs (README "Routes / SEO" + "Frontend internals");
  rebuild `dist/`; full suite green (145 tests).
- BASE-aware data fetches + teaser removal (2026-08-18): the app resolved every
  `fetch()` URL-relative against the page, so a nested route shell
  (`/quests/<id>/`, `/audiences/requests/<r>/`) booted but fetched from the
  wrong directory. `web/app.js` now computes the app root once at the top —
  `const BASE = document.currentScript.src.replace(/app\.js[^/]*$/, "")`, empty
  without `document.currentScript` (flat `dist/`, the headless smoke VM) — and
  prefixes every data fetch (`index.json`, the six dataset JSONs, `endings.json`
  and `locales/*.json`) with it, so deep-link pages load their data from the
  app root regardless of depth. On boot `init()` also removes the static
  `.seo-teaser` shell block (`document.querySelector('.seo-teaser')?.remove()`,
  guarded — null on the root shell, a stub element in the smoke VM) since the
  SPA re-renders everything client-side. Frontend-only (`web/app.js`) + smoke
  assertion (BASE is "" in the VM sandbox, keeping fetches relative against
  `dist/`; the conformance route-page asset-prefix test already locks the
  matching `../`-depth tags); rebuild `dist/`; full suite green.
- Per-card description lines (2026-08-18): the Knights and Audiences grids now
  carry a `.prev` teaser line like the dialogue cards — the knight card one-liner
  (origin `k.loc` · alias `tkey(k.nu)` when present · `mastered: k.mast` · `N
  quests` from qa/qu/qr) and the audience card its localized characters plus the
  first line of the knot it plays (`INDEX.knots[a.k].prev`, BBCode-stripped,
  `(no dialogue)` fallback when the knot has none). The quest card already
  preferred `tkey(q.d)` over a bare `Req:` line when there are no stat reqs (the
  optional T6 tweak) — no change needed there. Frontend-only (`web/app.js`) +
  smoke assertions (knight origin/mastered/quest-count/alias, audience knot
  first line + no-dialogue fallback); rebuild `dist/`; full suite green.
- Per-tab description blocks (2026-08-18): task T7 — one static `.tabdesc`
  block at the bottom of each results column (ids `inkdesc`/`qdesc`/`idesc`/
  `kdesc`/`sdesc`/`adesc`), 2–4 keyword-bearing sentences with the shipped
  data volumes (922 knots · 91 speakers · 3,477 choices · 1,368 variables · 312
  quests · 149 items · 24 knights · 71 specials · 511 audiences · 34 requests),
  each placed AFTER the column's `#cards` div so every re-render (which only
  replaces the cards grid + the countline) and `switchTab` (which only toggles
  the column's `hidden` flag) leaves them in place; `web/style.css` styles
  `.tabdesc` (muted, top border, small header) and the blocks ride into every
  prerendered route shell verbatim, so bots see the active tab's description on
  each page. The markup + CSS landed with T1's golden `dist/`; this commit adds
  the guard tests: the conformance suite scans ALL route shells for exactly six
  `.tabdesc` blocks (ids in page order, per-block `<h2>` + non-empty body, and
  the after-`#cards` placement), and the smoke test plants sentinels on the six
  blocks before boot and asserts they survive every init-time render plus a full
  `switchTab()` cycle. Frontend + tests + docs; no build-output change; full
  suite green.
- SITE_BASE placeholder inert + placeholder warning (2026-08-18): the shipped
  `viewer.env.example` carried a live `SITE_BASE = https://example.com/explorer/`
  value, so a documented copy to `viewer.env` would have silently baked
  `example.com` canonical / Open Graph / sitemap / robots URLs into every build
  (a wrong SITE_BASE fails quietly — the site still renders, only the SEO head
  points at the wrong origin). The example value is now commented out, with a
  nearby comment pointing at the commented `SITE_BASE = https://<user>.github.io/
  <repo>/` line to uncomment for the real deployment; and `route_pages.py`'s
  `normalize_site_base()` now prints a stderr WARNING (never an error) whenever
  a SITE_BASE looks like a placeholder (`example.com`, `localhost`, `127.0.0.1`,
  `your…`, `<…>`), so a bad value is loud instead of silent. Tests: unit check in
  `test_route_pages.py` (placeholder values warn, a real origin stays silent) and
  a new `ViewerEnvExampleTest` asserting the example file can never enable an
  active SITE_BASE. Docs only + tests — no build-output change, no golden
  `dist/` rebuild.


---

## 4. Future extensions (same shell, no new infra)
- Knights / Characters view (24 knight descriptors + per-knight scripts: stats, affinity,
  preferences, gimmicks; knight ↔ quest preference links) — DONE, Knights tab.
- Equipment / Relics view (149 equipment resources, 65 relics; reverse "which quest grants it") — DONE, Inventory tab.
- SpecialInstruction catalog view (71 director switches: emitting knots, granting quests,
  owner knight evolutions) — DONE, Special tab.
- Audiences / Audience-requests view (511 audiences with `ink_path`, 34 requests) — DONE, Audiences tab.
- Save inspector over `game/SaveExtracted/*.json` (real per-run quest states, ink state).

---

## 5. Open decisions / next step
- **Confirm the merge + naming** ("Sovereign Tower Explorer").
- Confirm scope order: Quests first, then knights/equipment later (recommended) vs. all at once.
- Implementation starts after user confirmation.

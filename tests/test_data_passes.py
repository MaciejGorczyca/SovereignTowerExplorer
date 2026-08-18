"""Integration tests over the real game data (no ink extraction needed).

Runs the five data passes (quests / inventory / knights / special / audiences)
against `game/SovereignTowerCode` and asserts the documented volumes and
invariants. These are the same functions `build_app.py` drives, so they double
as a fast smoke of the data pipeline (they skip cleanly when the game project
is absent). Every pass is built exactly once per process and shared across the
test classes (see `_passes()`); the passes walk the whole game tree, so this is
what keeps the module fast instead of re-reading it once per test class.
"""
import json
import os
import tempfile
import unittest

from helpers import DIST, GAME_ROOT, game_available, load_dist
import quest_data as QD
import inventory_data as ID
import knights_data as KD
import special_data as SD


# Each data pass walks the whole game tree and is by far the most expensive
# thing the suite does (on a slow filesystem a single pass is seconds of I/O).
# Build every pass exactly once per process and share the result across all the
# test classes below; the data is read-only for the tests. This is what keeps
# the suite runnable in seconds instead of a minute+.
_PASSES = {}


def _passes():
    if "quests" not in _PASSES:
        QD.set_game(GAME_ROOT)
        _PASSES["quests"] = QD.load_quests()
        _PASSES["index"] = load_dist("index.json")
        _PASSES["inventory"] = ID.load_inventory(
            quests_data=_PASSES["quests"], game_root=str(GAME_ROOT))
        _PASSES["knights"] = KD.load_knights(
            quests_data=_PASSES["quests"], index=_PASSES["index"],
            game_root=str(GAME_ROOT))
        _PASSES["special"] = _build_to_json(
            lambda tmp: SD.build_special(tmp, _PASSES["quests"], _PASSES["index"],
                                         _PASSES["knights"], game_root=str(GAME_ROOT)),
            "special.json")
        import audience_data as AD
        _PASSES["audiences"] = _build_to_json(
            lambda tmp: AD.build_audiences(tmp, _PASSES["quests"], _PASSES["index"],
                                           game_root=str(GAME_ROOT)),
            "audiences.json")
        import dialogue_data as DD
        _PASSES["dialogues"] = _build_to_json(
            lambda tmp: DD.build_dialogues(tmp, _PASSES["quests"], _PASSES["index"],
                                           _PASSES["knights"], _PASSES["special"],
                                           game_root=str(GAME_ROOT)),
            "dialogues.json")
        import ending_data as ED
        _PASSES["endings"] = _build_to_json(
            lambda tmp: ED.build_endings(tmp, game_root=str(GAME_ROOT)),
            "endings.json")
    return _PASSES


def _build_to_json(build, filename):
    """Run a pass into a temp dir and return its parsed JSON output."""
    with tempfile.TemporaryDirectory() as tmp:
        build(tmp)
        with open(os.path.join(tmp, filename), encoding="utf-8") as f:
            return json.load(f)


@unittest.skipUnless(game_available(), "game/SovereignTowerCode not present")
class QuestsDataPassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quests = _passes()["quests"]

    def test_volume(self):
        self.assertEqual(self.quests["stats"]["quests"], 312)
        # 91 = 82 quests whose SpecialOutcome is an ExtResource file + 9 that
        # inline the outcome as a SubResource in the quest .tres itself
        self.assertEqual(self.quests["stats"]["with_unexpected"], 91)
        # "511 audiences" = every audience resource under content/audiences,
        # each carrying its ink knot, folder and decoded firing requirements
        self.assertEqual(len(self.quests["audiences"]), 511)
        self.assertEqual(self.quests["stats"]["audiences"],
                         len(self.quests["audiences"]))
        # stats counters stay self-consistent with the records
        self.assertEqual(self.quests["stats"]["with_follow_up"],
                         sum(1 for q in self.quests["quests"].values()
                             if any(q["fu"])))

    def test_every_quest_id_matches_a_file(self):
        files = {os.path.splitext(fn)[0]
                 for fn in os.listdir(GAME_ROOT / "content" / "quests")
                 if fn.endswith(".tres")}
        self.assertEqual(set(self.quests["quests"]), files)

    def test_reward_refs_resolve(self):
        bad = []
        for qid, q in self.quests["quests"].items():
            for bucket in ("s", "f"):
                for rw in q["rw"][bucket]:
                    if rw.get("item_stem") and rw["item_stem"] == rw.get("item"):
                        # unresolved stem leaks through as its own name
                        bad.append((qid, rw))
        self.assertEqual(bad, [])

    def test_enums_decoded(self):
        enums = self.quests["enums"]
        for name in ("QuestTypes", "QuestTags", "ConditionTags", "Statistics",
                     "RewardType", "LocationsID", "CharacterTags"):
            self.assertGreater(len(enums[name]), 0, name)

    def test_single_knight_outcomes_carry_the_knight_condition(self):
        # The per-knight SpecialOutcome subclasses store their required knight in
        # a dedicated field (`arron` / `goberto` / `gwendan`) and may omit the
        # base `knights` array entirely (stop_baby_dragon_arron.tres does). The
        # parsed outcome must still expose `k` so the UI shows who to send.
        expected = {
            "arron_dragon_unexpected": "arron",
            "avalon_nessy_animal_friendly_unexpected_cute_arron": "arron",
            "mana_strala_spoiler_unexpected_arron": "arron",
            "stop_baby_dragon_arron": "arron",
            "goberto_unexpected_almor": "goberto",
            "gwendan_indebt_stolen_tiara": "gwendan",
            "scholars_strike_back_gwendan": "gwendan",
        }
        for qid, q in self.quests["quests"].items():
            for uo in q["un"]:
                if uo["id"] in expected:
                    self.assertIn(expected[uo["id"]], uo.get("k", []),
                                  (qid, uo["id"]))

    def test_inline_special_outcomes_are_parsed(self):
        # Some quests inline their SpecialOutcome as a SubResource in the quest
        # .tres (no file under content/unexpected_outcomes/), which the ref
        # resolver must decode instead of skipping. Each of the 9 affected
        # quests gains its condition-bearing unexpected outcome(s).
        expected_cond = {
            "contract_anveld_demon_hunt": ("ch", [50]),
            "contract_avalon_ice_skating_competition": ("k", ["gideon"]),
            "contract_hydra_hunt": ("st", 3),
            "contract_moonvale_magic_council_spying": ("k", ["oliver"]),
            "contract_rozenn_music_competition": ("k", ["gideon"]),
            "contract_spearfishing_competition": ("k", ["silgur"]),
            "contract_volga_camp_knife_throwing_competition": ("k", ["victoria"]),
            "contract_wolf_invasion": ("k", ["the_wolf"]),
            "quest_southbay_political_instabilities": ("k", ["tarcus"]),
        }
        for qid, (key, value) in expected_cond.items():
            with self.subTest(quest=qid):
                q = self.quests["quests"][qid]
                self.assertTrue(q["un"], "%s inline outcome skipped" % qid)
                uo = q["un"][0]
                self.assertTrue(uo["id"])
                self.assertEqual(uo.get(key), value, key)
                self.assertTrue(uo.get("no"), "arlin_note missing")
        # the southbay inline outcome carries its follow-up audience, which the
        # audiences pass must pick up as an unexpected fired-after-quest row
        southbay = self.quests["quests"]["quest_southbay_political_instabilities"]["un"]
        self.assertTrue(any(
            uo.get("fu") == "county_quest_southbay_final_father_dead_tarcus_unexpected"
            for uo in southbay))
        # contract_wolf_invasion inlines TWO outcomes (one per affecting knight)
        wolf = self.quests["quests"]["contract_wolf_invasion"]["un"]
        self.assertEqual(len(wolf), 2)
        self.assertIn("rufus", wolf[1].get("k", []))


@unittest.skipUnless(game_available(), "game/SovereignTowerCode not present")
class InventoryDataPassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quests = _passes()["quests"]
        cls.inv = _passes()["inventory"]

    def test_volume(self):
        st = self.inv["stats"]
        self.assertEqual(st["items"], 149)
        self.assertEqual(st["by_type"]["RELIC"], 65)
        self.assertEqual(st["by_type"]["MOUNT"], 29)
        self.assertEqual(st["by_type"]["CONSUMABLE"], 44)
        self.assertEqual(st["by_type"]["MEAL"], 6)
        self.assertEqual(st["by_type"]["QUEST_ITEM"], 5)

    def test_item_stems_unique(self):
        items = self.inv["items"]
        self.assertEqual(len(items), len({os.path.basename(k) for k in items}))

    def test_no_duplicate_item_cards(self):
        """One card per canonical item id: `.tres` copies sharing an ID (e.g.
        demon_heart_2/3/4 = DEMON_HEART) are merged into a single item instead
        of being shown as separate duplicate cards."""
        items = self.inv["items"]
        ids = [it["cid"] for it in items.values()]
        self.assertEqual(len(ids), len(set(ids)),
                         "duplicate item ids would render as duplicate cards")
        # the merged Demon Heart carries every copy's granted-by quests
        demon = items["demon_heart"]
        self.assertEqual(demon["stems"],
                         ["demon_heart", "demon_heart_2", "demon_heart_3", "demon_heart_4"])
        self.assertEqual(
            set(demon["src"]["quests"]),
            {"contract_anveld_demon_hunt", "quest_almor_fight_demon",
             "quest_ultimatum_kingslayer_ursula", "quest_victoria_gank",
             "quest_victoria_regular_duel", "quest_victoria_surprise_attack"})

    def test_material_consumption_reverse_map(self):
        """Shop requirements with a consumed relic material are mirrored back
        onto the material item as 'consumed by' links."""
        items = self.inv["items"]
        demon = items["demon_heart"]["src"]["consumed_by"]
        self.assertEqual(
            {(c["by"], c["shop"], c["act"]) for c in demon},
            {("demonic_sword", "forge", 3), ("demon_decoction", "witch", 3)})
        dragon = items["dragon_heart"]["src"]["consumed_by"]
        self.assertEqual(
            {(c["by"], c["shop"], c["act"]) for c in dragon},
            {("dragon_spear", "forge", 3), ("potion_of_fire_breathing", "witch", 3)})
        # every reverse link resolves to a real, distinct consuming item
        for stem, it in items.items():
            for c in it["src"]["consumed_by"]:
                self.assertIn(c["by"], items, (stem, c))
                self.assertNotEqual(c["by"], stem)


@unittest.skipUnless(game_available(), "game/SovereignTowerCode not present")
class KnightsDataPassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quests = _passes()["quests"]
        cls.index = _passes()["index"]
        cls.knights = _passes()["knights"]

    def test_volume(self):
        st = self.knights["stats"]
        self.assertEqual(st["total"], 24)
        self.assertEqual(st["ink_linked"], 24)
        self.assertEqual(st["with_convs"], 23)

    def test_every_knight_has_six_stats(self):
        for stem, k in self.knights["knights"].items():
            self.assertEqual(len(k["st"]), 6, stem)


@unittest.skipUnless(game_available(), "game/SovereignTowerCode not present")
class SpecialDataPassTest(unittest.TestCase):
    def setUp(self):
        self.quests = _passes()["quests"]
        self.index = _passes()["index"]
        self.knights = _passes()["knights"]

    def test_volume_and_join(self):
        special = _passes()["special"]
        st = special["stats"]
        self.assertEqual(st["total"], 71)
        self.assertEqual(st["in_ink"], 50)
        self.assertEqual(st["in_quests"], 19)
        self.assertEqual(st["knights"], 12)
        # every quest link resolves to a real quest; every knot to a real knot
        for name, inst in special["instructions"].items():
            for q in inst.get("quests", []):
                self.assertIn(q, self.quests["quests"], (name, q))
            for k in inst.get("knots", []):
                self.assertIn(k, self.index["knots"], (name, k))
            for k in inst.get("dlg", []):
                self.assertIn(k, self.index["knots"], (name, k))
            for k in inst.get("goto", []):
                self.assertIn(k, self.index["knots"], (name, k))
            for a in inst.get("auds", []):
                self.assertIn(a, self.quests["audiences"], (name, a))
            for c in inst.get("affects", []):
                self.assertIn(c, self.knights["knights"], (name, c))
        # the specific case the UI now cross-links
        g = special["instructions"]["GIDEON_VICTORIA_DEAD"]
        self.assertEqual(g["dlg"], ["gideon_victoria_dead_reaction"])
        self.assertIn("gideon", g["affects"])
        v = special["instructions"]["VICTORIA_DEAD"]
        self.assertEqual(v["affects"], ["victoria"])
        self.assertIn("dead", v["note"].lower())
        # firing conditions decoded from the manager's `if` guards
        tarcus = special["instructions"]["SOUTHBAY_TARCUS_INTERVENTION"]
        self.assertTrue(any("Tarcus" in c and "roundtable" in c.lower() for c in tarcus.get("cond", [])))
        # E7: golden-key quest guards and the almor-duel quest guard decode
        gk = special["instructions"]["GOLKEN_KEY_FOUND_KNIGHTS"]
        self.assertTrue(any("quest_angelica_golden_key" in c for c in gk.get("cond", [])))
        gka = special["instructions"]["GOLKEN_KEY_FOUND_ANGELICA"]
        self.assertTrue(any("quest_search_for_the_golden_key" in c for c in gka.get("cond", [])))
        almor = special["instructions"]["SET_ALMOR_WINNER_GENDER"]
        self.assertTrue(any("quest_almor_the_great_duel" in c for c in almor.get("cond", [])))
        # E7: CHECK_FOR_EPICRATE_* inherit the _is_epicrate_available() sub-guards
        epi = special["instructions"]["CHECK_FOR_EPICRATE_1"]
        self.assertTrue(any("serpent knight" in c for c in epi.get("cond", [])))
        self.assertTrue(any("brimwood" in c for c in epi.get("cond", [])))
        self.assertTrue(any("Marian" in c for c in epi.get("cond", [])))
        # E7: every case with an `if`-guard decodes a condition; audit is clean
        instr = SD.load_special_instructions()
        guarded = {k for k, v in instr.items() if SD._guard_expressions(v["body"])}
        self.assertEqual(guarded, set(k for k, v in instr.items() if v.get("cond")))
        self.assertEqual(SD.audit_undecoded_guards(instr), {})
        # character-manager signal→audience scheduling (GWENDAN_REFORMED schedules
        # gwendan_humble_candidacy a few cycles later)
        reformed = special["instructions"]["GWENDAN_REFORMED"]
        self.assertIn("gwendan_humble_candidacy", reformed.get("auds", []))
        self.assertEqual(reformed["knots"], ["gwendan_debt_reveal_reaction"])


@unittest.skipUnless(game_available(), "game/SovereignTowerCode not present")
class AudiencesDataPassTest(unittest.TestCase):
    def setUp(self):
        self.quests = _passes()["quests"]
        self.index = _passes()["index"]

    def test_volume_and_join(self):
        aud = _passes()["audiences"]
        st = aud["stats"]
        self.assertEqual(st["audiences"], 511)
        self.assertEqual(st["requests"], 34)
        self.assertEqual(st["with_conditions"], 18)
        self.assertEqual(st["with_director"], 20)
        self.assertEqual(st["with_intervention"], 28)
        self.assertEqual(st["with_county_intro"], 7)
        self.assertEqual(st["with_ultimatum"], 6)
        self.assertEqual(st["knotless"], 4)
        # the audience catalog must not drift from the quests.json copy
        self.assertEqual(set(aud["audiences"]), set(self.quests["audiences"]))
        for stem, a in aud["audiences"].items():
            self.assertEqual(a, self.quests["audiences"][stem], stem)

    def test_audience_knots_resolve(self):
        aud = _passes()["audiences"]
        # every ink_path must be a real knot except the 4 known dead refs
        KNOWN_MISSING = {
            "belladona_classic_recruitment", "rowan_classic_recruitment",
            "rupin_classic_recruitment", "sagadin_classic_recruitment",
        }
        bad = [s for s, a in aud["audiences"].items()
               if a["k"] and a["k"] not in self.index["knots"]
               and s not in KNOWN_MISSING]
        self.assertEqual(bad, [])
        self.assertEqual(len(KNOWN_MISSING - set(aud["audiences"])), 0)

    def test_rq_well_formed(self):
        aud = _passes()["audiences"]
        for stem, a in aud["audiences"].items():
            for rq in a.get("rq", []):
                self.assertIn(rq[0], ("KAT", "KDEAD", "KABS", "VAR", "APLAY"),
                              (stem, rq))
                self.assertEqual(len(rq), 3 if rq[0] == "VAR" else 2, (stem, rq))

    def test_county_intro_sources(self):
        aud = _passes()["audiences"]
        # channel 6: the county resources' county_introduction field reverse-maps
        # onto the county_quest_*_1 intro audiences (ActManager scheduling)
        for stem, county, name_key in (
            ("county_quest_enberg_1", "enberg", "ENBERG_NAME"),
            ("county_quest_almor_1", "almor", "ALMOR_NAME"),
            ("county_quest_isle_of_basalt_1", "basalt_isles", "BASALT_ISLES_NAME"),
            ("county_quest_brimwood_1", "brimwood", "BRIMWOOD_NAME"),
            ("county_quest_kutnar_1", "kutnar", "KUTNAR_NAME"),
            ("county_quest_moonvale_1", "moonvale", "MOONVALE_NAME"),
            ("county_quest_southbay_1", "southbay", "SOUTHBAY_NAME"),
        ):
            with self.subTest(audience=stem):
                ci = aud["audiences"][stem].get("ci")
                self.assertEqual(ci, [county, name_key], (stem, ci))
                self.assertTrue(aud["audiences"][stem]["c"], stem)
        # every ci entry resolves to a real audience and carries a real county
        for stem, a in aud["audiences"].items():
            ci = a.get("ci")
            if ci is None:
                continue
            self.assertIn(stem, aud["audiences"], stem)
            self.assertEqual(len(ci), 2, (stem, ci))
            self.assertTrue(ci[0] and ci[1], (stem, ci))

    def test_ultimatum_sources(self):
        aud = _passes()["audiences"]
        # channel 7: the ultimatum resources reverse-map the follow-up quests'
        # success/failure audiences onto their ultimatum id + hard deadline cycle
        for stem, uid, cycle, min_counties in (
            ("kingslayer_ultimatum_faillure", "kingslayer_ultimatum", 23, 3),
            ("kingslayer_ultimatum_victory", "kingslayer_ultimatum", 23, 3),
            ("dragon_knight_ultimatum_faillure", "dragon_knight_ultimatum", 8, 1),
            ("dragon_knight_ultimatum_victory", "dragon_knight_ultimatum", 8, 1),
            ("ultimatum_emperor_defeat", "emperor_ultimatum", 45, 7),
            ("ultimatum_emperor_victory", "emperor_ultimatum", 45, 7),
        ):
            with self.subTest(audience=stem):
                um = aud["audiences"][stem].get("um")
                self.assertEqual(um, [uid, cycle], (stem, um))
                umc = aud["audiences"][stem].get("umc", [])
                self.assertTrue(umc, (stem, umc))
                self.assertIn("min_rallied_counties %d" % min_counties, umc,
                              (stem, umc))
        # every um audience is one of the ultimatum outcome scenes and carries a
        # well-formed um/umc pair
        for stem, a in aud["audiences"].items():
            um = a.get("um")
            if um is None:
                continue
            self.assertEqual(len(um), 2, (stem, um))
            self.assertIsInstance(um[0], str)
            self.assertIsInstance(um[1], int)
            self.assertIn(a["f"], ("ultimatums", "county_quests"), stem)
            umc = a.get("umc")
            self.assertTrue(umc, (stem, umc))
            self.assertTrue(all(isinstance(n, str) and n for n in umc), (stem, umc))

    def test_director_sources(self):
        aud = _passes()["audiences"]
        # the CyclesManager director covers the 10 rupin grievances, the 4 civil
        # wars, the serpent-knight reset, both Arlin act intros and the 3
        # act-ending victories
        for stem in (
            "scriptedquest_civil_war_event_people_revolt",
            "scriptedquest_civil_war_event_nobles_revolt",
            "scriptedquest_civil_war_event_merchants_revolt",
            "scriptedquest_civil_war_event_scholars_revolt",
            "scriptedquest_the_serpent_knight_back_in_time",
            "arlin_introduction_to_act_2", "arlin_introduction_to_act_3",
            "rupin_criminal_underground_grievance_1",
            "rupin_criminal_underground_grievance_10",
            "dragon_knight_ultimatum_victory", "kingslayer_ultimatum_victory",
            "ultimatum_emperor_victory",
        ):
            with self.subTest(audience=stem):
                notes = aud["audiences"][stem].get("dir", [])
                self.assertEqual(len(notes), 1)
                self.assertTrue(notes[0].startswith("Director scene"), notes)
        cw = aud["audiences"]["scriptedquest_civil_war_event_people_revolt"]["dir"][0]
        self.assertIn("act 3", cw)
        self.assertIn("18 at cycle 24", cw)
        self.assertIn("34", cw)
        self.assertIn("people", cw)
        rupin = aud["audiences"]["rupin_criminal_underground_grievance_10"]["dir"][0]
        self.assertIn("corruption level reaches 20", rupin)

    def test_intervention_sources(self):
        aud = _passes()["audiences"]
        # the SpecialInterventionsManager node (channel 9) covers the two
        # ultimatum second encounters, the four king/dragon allied plots, the
        # traitor's-plot intro + murder, Dulahan's human form, Victoria's
        # betrayal, the nobles' cycle-zero intro, the wolf candidacy, Arlin's
        # reunited-reaction and all 15 courier scenes
        self.assertEqual(aud["stats"]["with_intervention"], 28)
        for stem in (
            "kingslayer_ultimatum_before_the_storm",
            "dragon_knight_ultimatum_before_the_storm",
            "intervention_gwendan_kingslayer_plot",
            "intervention_ursula_kingslayer_plot",
            "intervention_tarcus_dragon_knight_plot",
            "intervention_silgur_dragon_knight_plot",
            "scriptedquest_traitors_plot_1", "scriptedquest_traitors_plot_2",
            "dulahan_gimmick_intro_human_possession",
            "scriptedquest_victoria_events_5_betraying",
            "intro_nobleman", "wolf_candidacy",
            "arlin_all_counties_reunited_reaction",
            "brizh_grievance_the_courier_bringing_quests",
            "brizh_grievance_the_courier_bringing_quests_15",
        ):
            with self.subTest(audience=stem):
                notes = aud["audiences"][stem].get("dir", [])
                self.assertTrue(any(n.startswith("Special intervention")
                                    for n in notes), (stem, notes))
        kingslayer = aud["audiences"]["kingslayer_ultimatum_before_the_storm"]["dir"]
        self.assertTrue(any("second encounter" in n for n in kingslayer), kingslayer)
        noble = aud["audiences"]["intro_nobleman"]["dir"]
        self.assertTrue(any("cycle zero" in n for n in noble), noble)
        courier = aud["audiences"]["brizh_grievance_the_courier_bringing_quests_15"]["dir"][0]
        self.assertIn("act 3", courier)

    def test_death_followup_sources(self):
        aud = _passes()["audiences"]
        knights = _passes()["knights"]
        # channel 10: the knight resources' death_follow_up_audiences_names
        self.assertEqual(aud["stats"]["with_death_followup"], 7)
        for stem, knight in (
            ("angelica_death_announcement", "angelica"),
            ("gideon_death_announcement", "gideon"),
            ("goberto_death_announcement", "goberto"),
            ("gwendan_death_announcement", "gwendan"),
            ("ursula_new_gimmick_low_corruption", "ursule"),
            ("ursula_new_gimmick_mid_corruption", "ursule"),
            ("ursula_new_gimmick_high_corruption", "ursule"),
        ):
            with self.subTest(audience=stem):
                dd = aud["audiences"][stem].get("dd", [])
                self.assertTrue(any(d == [knight, "death"] for d in dd), (stem, dd))
        self.assertTrue(aud["audiences"]["ursula_new_gimmick_high_corruption"]["dd"],
                        "ursule gimmick variants come from the knight descriptor")
        for stem, a in aud["audiences"].items():
            for d in a.get("dd", []):
                self.assertIn(d[1], ("death", "demission"), (stem, d))
                self.assertIn(d[0], knights["knights"], (stem, d))

    def test_demission_sources(self):
        aud = _passes()["audiences"]
        knights = _passes()["knights"]
        # channel 11: the knight descriptors' roundtable_demission_audience_*
        # fields reverse-map onto the leaving-the-roundtable audiences
        self.assertEqual(aud["stats"]["with_demission"], 29)
        for stem, knight in (
            ("knight_leaving_alwena", "alwena"),
            ("knight_leaving_zolta", "zolta"),
            ("knight_leaving_the_wolf", "the_wolf"),
            ("knight_leaving_ursula", "ursule"),
            ("knight_leaving_epicrates", "epicrate"),
        ):
            with self.subTest(audience=stem):
                dd = aud["audiences"][stem].get("dd", [])
                self.assertTrue(any(d[0] == knight and d[1] == "demission"
                                    for d in dd), (stem, dd))
        variants = {
            "knight_leaving_arron_dragonheart": ("arron", "violent"),
            "knight_leaving_dulahan_human": ("dulahan", "human"),
            "knight_leaving_dulahan_cursed_helmet": ("dulahan", "possessed"),
            "knight_leaving_edith_possessed": ("edith", "possessed"),
            "gwendan_humble_candidacy": ("gwendan", "humbled"),
        }
        for stem, (knight, variant) in variants.items():
            with self.subTest(audience=stem):
                dd = aud["audiences"][stem].get("dd", [])
                self.assertTrue(any(len(d) == 3 and d[0] == knight
                                    and d[1] == "demission" and d[2] == variant
                                    for d in dd), (stem, dd, aud["audiences"][stem]))

    def test_callback_request_sources(self):
        aud = _passes()["audiences"]
        knights = _passes()["knights"]
        # channel 12: the 24 call_back_* requests are unlocked when the knight
        # leaves the roundtable (world_manager.gd:197-198,229); they are never
        # granted by a quest and always point at the knight + a return audience
        self.assertEqual(aud["stats"]["with_callbacks"], 24)
        cb = {stem: r for stem, r in aud["requests"].items() if r.get("cb")}
        self.assertEqual(
            {s for s in cb} - {s for s in aud["requests"] if s.startswith("call_back_")},
            set())
        self.assertEqual(
            {s for s in aud["requests"] if s.startswith("call_back_")} - set(cb),
            set())
        for stem, r in cb.items():
            self.assertTrue(r.get("ch"), stem)
            self.assertTrue(r.get("ck"), stem)
            self.assertTrue(r.get("fua"), stem)
            self.assertFalse(r.get("q"), stem)
        # the knight descriptors' call_back_audience_request fields map onto the
        # requests (23 knights; alwena's request has no descriptor field)
        knight_callbacks = {k: kd["callback"] for k, kd in knights["knights"].items()
                            if kd.get("callback")}
        self.assertEqual(len(knight_callbacks), 23)
        for stem, reqstem in knight_callbacks.items():
            with self.subTest(knight=stem):
                self.assertIn(reqstem, cb)
                self.assertEqual(cb[reqstem]["ch"], stem)

    def test_filler_pack_sources(self):
        aud = _passes()["audiences"]
        # channel 13: the content/filler_audiences FillerAudience wrappers
        # grouped by the FillerAudiencesManager pack arrays of cycles_manager.tscn
        self.assertEqual(aud["stats"]["with_filler"], 234)
        for stem, a in aud["audiences"].items():
            fl = a.get("fl")
            if fl:
                self.assertEqual(len(fl), 3, (stem, fl))
                self.assertIsInstance(fl[0], str, (stem, fl))
                for v in fl[1:]:
                    self.assertTrue(v is None or isinstance(v, int), (stem, fl))
                self.assertEqual(a["f"], "filler", stem)
        clover = aud["audiences"]["clovermont_grievance_emergency"]["fl"]
        self.assertEqual(clover[0], "clovermont")
        academician = aud["audiences"]["brizh_scholars_grievance_copy_cats"]["fl"]
        self.assertEqual(academician[0], "academician")
        # the representative packs need no ink unlocker; the region packs are
        # unlocked by the first-grievance knots (UnlockFillerAudiencesPack)
        unlocks = {}
        for name, k in self.index["knots"].items():
            for t in k["lines"]:
                if not isinstance(t, list) or not t:
                    continue
                if t[0] == "3" and t[1] == "UnlockFillerAudiencesPack" and t[2]:
                    unlocks.setdefault(str(t[2][0]), set()).add(name)
                elif t[0] == "2" and isinstance(t[5], list):
                    for e in t[5]:
                        if isinstance(e, list) and e and len(e) > 1 and e[0] == "UnlockFillerAudiencesPack" and e[1]:
                            unlocks.setdefault(str(e[1][0]), set()).add(name)
        self.assertEqual(unlocks.get("clovermont"), {"clovermont_first_grievance"})
        self.assertEqual(unlocks.get("academician"), None)
        for pack, kns in unlocks.items():
            for kn in kns:
                self.assertTrue(any((aud["audiences"][s].get("fl") or [None])[0] == pack
                                    for s in aud["audiences"]), pack)

    def test_requests_resolve(self):
        aud = _passes()["audiences"]
        for stem, r in aud["requests"].items():
            self.assertTrue(r["n"], stem)
            self.assertTrue(r["fua"] and r["fua"] in aud["audiences"],
                            (stem, r.get("fua")))
            self.assertTrue(r["ch"], stem)
            for x in r.get("exc", []):
                self.assertIn(x, aud["audiences"], (stem, x))
            for x in r.get("rem", []):
                self.assertIn(x, aud["audiences"], (stem, x))
            for q in r.get("q", []):
                self.assertIn(q, self.quests["quests"], (stem, q))

    def test_code_scheduled_sources(self):
        aud = _passes()["audiences"]
        # channel 14: code-scheduled knight events — audiences queued directly
        # from game code (edith.tres `new_gimmick_intro_path`,
        # character_manager.tscn `family_reunion_audience` / `dulahan_arrival`,
        # and the KUTNAR_TARCUS_INTERVENTION special `goto`) rather than by a
        # quest / doleance / request / special-`auds` / director / divert channel
        expect = {
            "edith_gimmick_introduction_demon_possession": ["gimmick"],
            "dulahan_candidacy": ["death"],
            "lost_child_plotline_groveshire_gavault_confrontation": ["family_reunion"],
            "intervention_tarcus_county_quest_kutnar_first_audience": ["special"],
        }
        self.assertEqual(
            {s for s, a in aud["audiences"].items() if a.get("code")},
            set(expect))
        for stem, channels in expect.items():
            with self.subTest(audience=stem):
                code = aud["audiences"][stem].get("code")
                self.assertTrue(code, stem)
                self.assertEqual([c for c, _ in code], channels, stem)
                for c, n in code:
                    self.assertTrue(c and n, (stem, c, n))
        edith = aud["audiences"]["edith_gimmick_introduction_demon_possession"]["code"]
        self.assertTrue(any("Edith" in n and "killing quest" in n
                            for c, n in edith), edith)
        arrival = aud["audiences"]["dulahan_candidacy"]["code"]
        self.assertTrue(any("Goberto" in n and "+2 cycles" in n
                            for c, n in arrival), arrival)
        reunion = aud["audiences"]["lost_child_plotline_groveshire_gavault_confrontation"]["code"]
        self.assertTrue(any("groveshire_gavault_reconciled" in n
                            and "brunhilda_countess" in n
                            and "rallied" in n for c, n in reunion), reunion)
        kutnar = aud["audiences"]["intervention_tarcus_county_quest_kutnar_first_audience"]["code"]
        self.assertTrue(any("KUTNAR_TARCUS_INTERVENTION" in n
                            and "roundtable" in n for c, n in kutnar), kutnar)
        # the code field also rides the quests.json catalog copy
        for stem in expect:
            self.assertTrue(self.quests["audiences"][stem].get("code"), stem)

    def test_unused_legacy_sources(self):
        aud = _passes()["audiences"]
        # channel 15: legacy/orphan audience resources the shipped game never
        # queues. The four `*_classic_recruitment` scenes are dead (their ink
        # path never got a compiled knot; the request recruitment mechanic
        # superseded them) and the two `brizh_*_grievance_first_meeting` knots
        # exist in the compiled story but no channel ever references them.
        expect = {
            "belladona_classic_recruitment",
            "rowan_classic_recruitment",
            "rupin_classic_recruitment",
            "sagadin_classic_recruitment",
            "brizh_nobles_grievance_first_meeting",
            "brizh_scholars_grievance_first_meeting",
        }
        self.assertEqual(
            {s for s, a in aud["audiences"].items() if a.get("unused")},
            expect)
        for stem in expect:
            with self.subTest(audience=stem):
                self.assertEqual(aud["audiences"][stem]["unused"], True, stem)
                note = aud["audiences"][stem].get("unote")
                self.assertTrue(note, stem)
                self.assertIn("shipped game", note, (stem, note))
        for stem in expect:
            if stem.startswith("brizh"):
                self.assertIn("orphan knot",
                              aud["audiences"][stem]["unote"], stem)
            else:
                self.assertIn("request recruitment",
                              aud["audiences"][stem]["unote"], stem)
        # the successors live in the request catalog
        successors = {
            "belladonna_request": "belladona_audience_request_recruitment",
            "rowan_request": "rowan_audience_request_recruitment",
            "rupin_request": "rupin_audience_request_recruitment",
            "sagadin_request": "sagadin_audience_request_recruitment",
        }
        for stem, audstem in successors.items():
            self.assertIn(stem, aud["requests"], stem)
            self.assertIn(audstem, aud["audiences"], stem)
        # the flag also rides the quests.json catalog copy
        for stem in expect:
            self.assertTrue(self.quests["audiences"][stem].get("unused"), stem)
            self.assertTrue(self.quests["audiences"][stem].get("unote"), stem)

    def test_rev_qf_resolves(self):
        aud = _passes()["audiences"]
        for stem, entries in aud["rev"]["qf"].items():
            self.assertIn(stem, aud["audiences"], stem)
            for e in entries:
                self.assertIn(e["q"], self.quests["quests"], (stem, e))
                self.assertIn(e["k"], ("success", "failure", "unexpected"),
                              (stem, e))


@unittest.skipUnless(game_available(), "game/SovereignTowerCode not present")
class DialoguesDataPassTest(unittest.TestCase):
    def setUp(self):
        self.index = _passes()["index"]
        self.dlg = _passes()["dialogues"]
        self.knights = _passes()["knights"]

    def test_volume(self):
        # 82 affinity + 76 conversation dialogue resources + 1 inline
        # (candidature_alwena) + 76 reactions = 235 free-time dialogs
        st = self.dlg["stats"]
        self.assertEqual(st["all"], 235)
        self.assertEqual(st["affinity"], 82)
        self.assertEqual(st["conversation"], 77)
        self.assertEqual(st["reaction"], 76)
        self.assertEqual(len(self.dlg["dialogues"]), st["all"])
        # every entry is one of the three resource folders; all but the 3 known
        # dead resources land in a real knot (the dead FreeTimeDialogue files
        # are referenced by no descriptor/manager and have no compiled knot)
        DEAD = {
            "gwendan_affinity_minus_1",
            "traitors_plot_demon_quest_accept_reaction",
            "traitors_plot_demon_quest_success_reaction",
        }
        for ink, e in self.dlg["dialogues"].items():
            self.assertIn(e["t"], ("affinity", "conversation", "reaction"), ink)
            if ink in DEAD:
                self.assertNotIn(ink, self.index["knots"], ink)
                continue
            self.assertIn(ink, self.index["knots"], ink)

    def test_affinity_gates(self):
        d = self.dlg["dialogues"]
        # angelica: {0: a1, 5: a2, 8: a3} + the on-death replacement at key 10
        self.assertEqual(d["angelica_affinity_1"]["aff"],
                         {"k": "angelica", "rank": 0})
        self.assertTrue(d["angelica_affinity_1"]["aff0"])
        self.assertEqual(d["angelica_affinity_2"]["aff"]["rank"], 5)
        self.assertEqual(d["angelica_affinity_3"]["aff"]["rank"], 8)
        self.assertEqual(d["angelica_affinity_4_knight_dead"]["aff"]["rank"], 10)
        self.assertIn("knight dies", d["angelica_affinity_4_knight_dead"]["aff"]["re"])
        # gideon's known-origin dialog is inserted at rank 5 (his base dict uses
        # 0/3/7), gated on gideon_origins_known
        g = d["gideon_affinity_3_if_gideon_orgins_known"]["aff"]
        self.assertEqual(g["k"], "gideon")
        self.assertEqual(g["rank"], 5)
        self.assertIn("gideon_origins_known", g["re"])
        # variant/room-gated gates carry their note
        rufus = d["rufus_affinity_2"]["aff"]
        self.assertEqual((rufus["k"], rufus["rank"]), ("rufus", 5))
        self.assertIn("stables", rufus["re"])
        victoria = d["victoria_affinity_3"]["aff"]
        self.assertEqual((victoria["k"], victoria["rank"]), ("victoria", 6))
        self.assertIn("witch tower", victoria["re"])
        wolf = d["the_wolf_affinity_2"]["aff"]
        self.assertEqual((wolf["k"], wolf["rank"]), ("the_wolf", 10))
        gwendan = d["gwendan_affinity_3_humble"]["aff"]
        self.assertEqual((gwendan["k"], gwendan["rank"]), ("gwendan", 5))
        self.assertIn("reformed", gwendan["re"])
        ursule = d["ursule_affinity_4_if_died"]["aff"]
        self.assertEqual((ursule["k"], ursule["rank"]), ("ursule", 9))
        # every affinity gate resolves to a real knight and a sane rank
        for ink, e in d.items():
            a = e.get("aff")
            if a:
                self.assertIn(a["k"], self.knights["knights"], ink)
                self.assertIsInstance(a["rank"], int)
                self.assertGreaterEqual(a["rank"], 0, ink)

    def test_conversation_gates(self):
        d = self.dlg["dialogues"]
        c = d["conversation_brunhilda_gideon"]["conv"]
        self.assertEqual(c["knights"], ["brunhilda", "gideon"])
        self.assertIsInstance(c["o"], int)
        # the gambling-tolerant pair: brunhilda_gideon is offered while neither
        # is in an excluded state (ursula's HIGH corruption gate is global)
        self.assertTrue(d["conversation_brunhilda_gideon"]["loc"] is not None)
        # everyone in a conversation is a real descriptor / knight
        for ink, e in d.items():
            cv = e.get("conv")
            if not cv:
                continue
            for kn in cv.get("knights", []):
                found = (kn in self.knights["knights"]
                         or _desc_exists(kn, GAME_ROOT))
                self.assertTrue(found, (ink, kn))
            for excl in cv.get("e", []):
                self.assertIsInstance(excl, list)
                self.assertEqual(len(excl), 2, (ink, excl))
                self.assertTrue(excl[0] and excl[1], (ink, excl))

    def test_unlock_sources(self):
        d = self.dlg["dialogues"]
        st = self.dlg["stats"]
        # every resolved UnlockSpecialDialogue site lands on a dialog (98 raw
        # call sites → 99 resolved including gwendan's runtime marriage/romance
        # alias forks), and the ink-unlock count over dialogs reflects that
        self.assertGreaterEqual(st["ink_unl"], 60)
        self.assertGreaterEqual(st["with_unl"], 80)
        # the four marriage sites in the nobles-revolt knot unlock both gwendan
        leftovers = d["civil_wars_event_marriage_annoying_gwendan_reaction"]["unl"]
        self.assertIn(["ink", "scriptedquest_civil_war_event_nobles_revolt"], leftovers)
        humbles = d["civil_wars_event_marriage_humble_gwendan_reaction"]["unl"]
        self.assertIn(["ink", "scriptedquest_civil_war_event_nobles_revolt"], humbles)
        # reactions unlocked by ink and code:
        self.assertEqual(d["lady_tower_act_2_reached_reaction"]["unl"],
                         [["ink", "arlin_introduction_to_act_2"]])
        self.assertTrue(any(u[0] == "code" and "romance" in u[1]
                            for u in d["brunhilda_full_romance"]["unl"]))
        self.assertTrue(any(u[0] == "item" and "DRAGON_HEART" in u[1]
                            for u in d["arron_get_the_dragon_heart"]["unl"]))
        self.assertTrue(any(u[0] == "item" and "CURSED_HELMET" in u[1]
                            for u in d["cursed_helmet_obtained_dulahan_reaction"]["unl"]))
        # special-instruction dlg unlocks are hooked from special.json
        gv = d["gideon_victoria_dead_reaction"]["unl"]
        self.assertTrue(any(u[0] == "special" and u[1] == "GIDEON_VICTORIA_DEAD"
                            for u in gv), gv)
        # every ink unlock resolves to a real knot; every item unlock names a
        # real quest-item stem
        for ink, e in d.items():
            for typ, val in e.get("unl", []):
                if typ == "ink":
                    self.assertIn(val, self.index["knots"], (ink, val))
                elif typ == "special":
                    self.assertIn(val, _passes()["special"]["instructions"], (ink, val))
                self.assertIsInstance(val, str)
                self.assertTrue(val)


@unittest.skipUnless(game_available(), "game/SovereignTowerCode not present")
class EndingsDataPassTest(unittest.TestCase):
    def setUp(self):
        self.index = _passes()["index"]
        self.end = _passes()["endings"]

    def test_types(self):
        # the six ending types in enum order, each mapping to a real
        # ending-category knot; the five switcheable types carry their
        # SWITCH_ENDING_*_PATH instruction, DEMON_STATE a corruption note.
        types = self.end["types"]
        self.assertEqual(len(types), 6)
        self.assertEqual(list(types),
                         ["WAR", "PEACE_TREATY", "MARRY", "SURRENDER",
                          "TOWER_DESTRUCTION", "DEMON_STATE"])
        self.assertEqual({t["cut"] for t in types.values()},
                         {"tyranny_ending_cutscene", "wisdom_ending_cutscene",
                          "audacity_ending_cutscene", "kind_ending_cutscene",
                          "tower_destruction_ending_cutscene", "demon_state_ending"})
        for name, t in types.items():
            self.assertIn(t["cut"], self.index["knots"], name)
            self.assertEqual(self.index["knots"][t["cut"]]["c"], "ending", name)
            if name == "DEMON_STATE":
                self.assertNotIn("switch", t)
                self.assertIn("corruption", t["note"])
            else:
                self.assertEqual(t["switch"], "SWITCH_ENDING_%s_PATH" % name)

    def test_vignettes(self):
        v = self.end["vignettes"]
        # 24 knights + 7 servants; the game routes the vignette by the
        # character's ink id (alwena is "intendant"; carina is the blacksmith's
        # vignette; ursula_ending is keyed by ursule).
        self.assertEqual(len(v), 31)
        self.assertEqual(v["ursule"], "ursula_ending")
        self.assertEqual(v["intendant"], "alwena_ending")
        self.assertEqual(v["blacksmith"], "carina_ending")
        self.assertEqual(v["witch_belladonna"], "belladonna_ending")
        self.assertEqual(v["lady_tower"], "lady_tower_ending")
        for kid, knot in v.items():
            self.assertIn(knot, self.index["knots"], (kid, knot))
            self.assertEqual(self.index["knots"][knot]["c"], "ending", (kid, knot))

    def test_specials(self):
        # the two code-played ending knots (Hildegard's song + the demon room)
        s = self.end["specials"]
        self.assertEqual(len(s), 2)
        self.assertEqual(set(s), {"hildegard_singing_ending",
                                  "demon_back_in_time_ending_proposal"})
        self.assertIn("HILDEGARD_SONG", s["hildegard_singing_ending"])
        self.assertIn("demon room", s["demon_back_in_time_ending_proposal"])
        for knot in s:
            self.assertIn(knot, self.index["knots"])

    def test_all_ending_knots_covered_by_source(self):
        # the 41 ending-category knots: the 6 cutscenes + 31 vignettes + 2
        # specials = 39; the remaining 2 (carina_ending_act_1/2_reaction) are
        # blacksmith reaction dialogs already catalogued in dialogues.json
        ending_knots = {n for n, k in self.index["knots"].items()
                        if k["c"] == "ending"}
        covered = ({t["cut"] for t in self.end["types"].values()}
                   | set(self.end["vignettes"].values())
                   | set(self.end["specials"]))
        self.assertEqual(len(ending_knots), 41)
        self.assertEqual(len(covered), 39)
        leftover = ending_knots - covered
        self.assertEqual(leftover, {"carina_ending_act_1_reaction",
                                    "carina_ending_act_2_reaction"})


def _desc_exists(stem, game_root):
    """True when a knight/servant descriptor stem exists under the game root."""
    import os
    root = str(game_root)
    for sub in ("content/character_descriptors/knights",
                "content/character_descriptors/servants"):
        if os.path.exists(os.path.join(root, sub, stem + ".tres")):
            return True
    return False


if __name__ == "__main__":
    unittest.main()

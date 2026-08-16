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
        self.assertEqual(self.quests["stats"]["with_unexpected"], 82)
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


@unittest.skipUnless(game_available(), "game/SovereignTowerCode not present")
class InventoryDataPassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quests = _passes()["quests"]
        cls.inv = _passes()["inventory"]

    def test_volume(self):
        st = self.inv["stats"]
        self.assertEqual(st["items"], 154)
        self.assertEqual(st["by_type"]["RELIC"], 70)
        self.assertEqual(st["by_type"]["MOUNT"], 29)
        self.assertEqual(st["by_type"]["CONSUMABLE"], 44)
        self.assertEqual(st["by_type"]["MEAL"], 6)
        self.assertEqual(st["by_type"]["QUEST_ITEM"], 5)

    def test_item_stems_unique(self):
        items = self.inv["items"]
        self.assertEqual(len(items), len({os.path.basename(k) for k in items}))

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

    def test_rev_qf_resolves(self):
        aud = _passes()["audiences"]
        for stem, entries in aud["rev"]["qf"].items():
            self.assertIn(stem, aud["audiences"], stem)
            for e in entries:
                self.assertIn(e["q"], self.quests["quests"], (stem, e))
                self.assertIn(e["k"], ("success", "failure", "unexpected"),
                              (stem, e))


if __name__ == "__main__":
    unittest.main()

"""Conformance tests for the shipped dist/ artifacts (no game data required).

These validate the *contract* the frontend relies on: the token encoding, the
schema of every JSON dataset and the cross-dataset invariants (locale parity,
id maps, stats self-consistency). They run against the checked-in dist/ and are
the layer that still works without the game project present.
"""
import os
import unittest

from helpers import DIST, load_dist

TOKEN_TYPES = {"0", "1", "2", "3", "4", "5", "6", "7", "8"}


class IndexJsonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = load_dist("index.json")

    def test_has_required_sections(self):
        for key in ("inkVersion", "knots", "speakers", "variables",
                    "categories", "stats"):
            self.assertIn(key, self.idx)

    def test_stats_self_consistent(self):
        st = self.idx["stats"]
        self.assertEqual(st["knots"], len(self.idx["knots"]))
        self.assertEqual(st["choices"],
                         sum(k["choices"] for k in self.idx["knots"].values()))
        self.assertEqual(st["speakers"], len(self.idx["speakers"]))
        self.assertEqual(st["variables"], len(self.idx["variables"]))

    def test_knot_schema(self):
        for name, k in self.idx["knots"].items():
            with self.subTest(knot=name):
                for key in ("c", "fn", "lines", "text", "chars", "choices",
                            "reads", "writes", "diverts"):
                    self.assertIn(key, k)
                self.assertEqual(len(k["reads"]), len(set(k["reads"])))
                self.assertEqual(len(k["writes"]), len(set(k["writes"])))

    def test_token_encoding(self):
        bad = []
        for name, k in self.idx["knots"].items():
            for t in k["lines"]:
                if not isinstance(t, list) or not t or t[0] not in TOKEN_TYPES:
                    bad.append((name, t))
                    continue
                if t[0] == "0":
                    self.assertTrue(isinstance(t[1], str))
                    self.assertTrue(isinstance(t[2], str))
                elif t[0] == "2":
                    self.assertTrue(isinstance(t[1], str))
                    self.assertTrue(isinstance(t[3], int))
                    self.assertTrue(isinstance(t[4], str))
                    if len(t) > 7:
                        # per-choice follow-up stream (index 7): a nested token
                        # list whose internal if-blocks are balanced
                        nested = t[7]
                        self.assertTrue(isinstance(nested, list))
                        depth = 0
                        for nt in nested:
                            self.assertTrue(isinstance(nt, list) and nt
                                            and nt[0] in TOKEN_TYPES)
                            if nt[0] == "7" and len(nt) > 3 and nt[3] == "1":
                                depth += 1
                            elif nt[0] == "8":
                                depth -= 1
                        self.assertEqual(depth, 0)
        self.assertEqual(bad, [])

    def test_choices_have_resolved_destination(self):
        # A choice resolves to its destination either on the card (index 4: a
        # real divert target or the (end)/(options) sentinel) or, when the jump
        # is conditional (an if/else routing the choice through per-branch
        # diverts), leaves the card destination EMPTY — the branch-resolved
        # diverts live in its follow-up stream (index 7) instead. So a choice
        # may only have an empty card destination if its follow-up opens a
        # conditional branch block.
        unresolved = []
        for name, k in self.idx["knots"].items():
            for t in k["lines"]:
                if t[0] != "2" or t[4]:
                    continue
                cond_routed = (len(t) > 7 and isinstance(t[7], list) and any(
                    nt[0] == "7" and len(nt) > 3 and nt[3] == "1"
                    for nt in t[7]))
                if not cond_routed:
                    unresolved.append((name, t))
        self.assertEqual(unresolved, [])


class LocaleParityTest(unittest.TestCase):
    """Non-en locales ship token-only overrides.

    The knot set is identical across all 6 locales (the frontend's contract for
    locale switching). Note: per-knot token sequences are NOT byte-identical to
    en in ~100-200 knots per locale — the translated stories restructure lines
    and (BREAK_n) markers in places — so parity is asserted on the knot set and
    on per-token structural validity, not on exact sequence equality.
    """

    @classmethod
    def setUpClass(cls):
        cls.idx = load_dist("index.json")

    def test_locale_knot_set_parity(self):
        locales_dir = DIST / "locales"
        if not locales_dir.is_dir():
            self.skipTest("no dist/locales dir present")
        en_knots = set(self.idx["knots"])
        for path in sorted(locales_dir.glob("*.json")):
            with open(path, encoding="utf-8") as f:
                import json
                loc = json.load(f)
            with self.subTest(locale=path.name):
                self.assertEqual(set(loc), en_knots,
                                 "%s knot set must match index.json" % path.name)

    def test_locale_tokens_structurally_valid(self):
        locales_dir = DIST / "locales"
        if not locales_dir.is_dir():
            self.skipTest("no dist/locales dir present")
        for path in sorted(locales_dir.glob("*.json")):
            with open(path, encoding="utf-8") as f:
                import json
                loc = json.load(f)
            for knot, tokens in loc.items():
                for t in tokens:
                    with self.subTest(locale=path.name, knot=knot, token=t):
                        self.assertTrue(isinstance(t, list) and t
                                        and t[0] in TOKEN_TYPES)


class DatasetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quests = load_dist("quests.json")
        cls.inventory = load_dist("inventory.json")
        cls.knights = load_dist("knights.json")
        cls.special = load_dist("special.json")
        cls.audiences = load_dist("audiences.json")
        cls.index = load_dist("index.json")

    def test_quests_schema(self):
        q = self.quests
        self.assertEqual(q["stats"]["quests"], len(q["quests"]))
        self.assertEqual(q["stats"]["with_unexpected"],
                         sum(1 for x in q["quests"].values() if x["un"]))
        for qid, record in q["quests"].items():
            with self.subTest(quest=qid):
                for key in ("id", "n", "d", "t", "c", "l", "cd", "st",
                            "dm", "du", "nk", "kl", "lt", "dl", "rw", "un",
                            "mo", "fu"):
                    self.assertIn(key, record)
        for qid in q.get("unlock_knots", {}):
            self.assertIn(qid, q["quests"])

    def test_quest_loc_table_covers_names(self):
        q = self.quests
        loc = q["loc"]
        # known untranslated keys (documented in PLAN.md: "4 secret quest keys
        # have no translation, raw key shown"). Any NEW missing key fails.
        KNOWN_MISSING = {
            "QUEST_SEARCH_TRAITOR_DESCRIPTION",
            "QUEST_VICTORIA_KNIGHT_EXFLITRATION_NAME",
            "QUEST_VICTORIA_KNIGHT_EXFLITRATION_DESCRIPTION",
            "QUEST_VICTORIA_SURPRISE_ATTACK_DESCRIPTION",
        }
        missing = []
        for qid, record in q["quests"].items():
            for key in (record["n"], record["d"]):
                if key and key not in loc and key not in KNOWN_MISSING:
                    missing.append((qid, key))
        self.assertEqual(missing, [])

    def test_audiences_schema(self):
        q = self.quests
        self.assertEqual(q["stats"]["audiences"], len(q["audiences"]))
        for stem, a in q["audiences"].items():
            with self.subTest(audience=stem):
                self.assertIn("k", a)
                self.assertIn("f", a)
                self.assertIsInstance(a["c"], list)
                for rq in a.get("rq", []):
                    self.assertIn(rq[0], ("KAT", "KDEAD", "KABS", "VAR", "APLAY"))
                    if rq[0] == "VAR":
                        self.assertEqual(len(rq), 3)
                    else:
                        self.assertEqual(len(rq), 2)
                for d in a.get("dir", []):
                    self.assertIsInstance(d, str)
                    self.assertTrue(d)
                for d in a.get("dd", []):
                    self.assertIn(len(d), (2, 3))
                    self.assertIsInstance(d[0], str)
                    self.assertIn(d[1], ("death", "demission"))
                    if len(d) == 3:
                        self.assertIsInstance(d[2], str)
                        self.assertTrue(d[2])

    def test_audiences_json_schema(self):
        aud = self.audiences
        self.assertEqual(aud["stats"]["audiences"], len(aud["audiences"]))
        self.assertEqual(aud["stats"]["requests"], len(aud["requests"]))
        # the audiences.json catalog must match the quests.json audiences exactly
        self.assertEqual(set(aud["audiences"]), set(self.quests["audiences"]))
        for stem, a in aud["audiences"].items():
            with self.subTest(audience=stem):
                self.assertEqual(a, self.quests["audiences"][stem])
        for stem, r in aud["requests"].items():
            with self.subTest(request=stem):
                for key in ("n", "d", "ch", "ck", "hd", "cst", "fua"):
                    self.assertIn(key, r)
                for lst in ("exc", "rem", "q"):
                    for x in r.get(lst, []):
                        self.assertTrue(isinstance(x, str), (stem, lst, x))
        for stem, entries in aud["rev"]["qf"].items():
            self.assertIn(stem, aud["audiences"], stem)
            for e in entries:
                self.assertIn(e["k"], ("success", "failure", "unexpected"))

    def test_inventory_schema(self):
        inv = self.inventory
        self.assertEqual(inv["stats"]["items"], len(inv["items"]))
        for stem, item in inv["items"].items():
            with self.subTest(item=stem):
                self.assertIn(item["type"],
                              {"RELIC", "MOUNT", "CONSUMABLE", "MEAL", "QUEST_ITEM"})
                self.assertEqual(len(item["st"]), 6)
                for src in ("forge", "stables", "witch", "meals", "starting",
                            "quests", "ink_unlock", "ink_remove", "consumed_by"):
                    self.assertIn(src, item["src"])
                self.assertTrue(isinstance(item["src"]["consumed_by"], list))

    def test_knights_schema(self):
        k = self.knights
        self.assertEqual(k["stats"]["total"], len(k["knights"]))
        for stem, knight in k["knights"].items():
            with self.subTest(knight=stem):
                # compact key schema: 'n' = name loc key, 'st' = 6 stats, 'stem'
                self.assertEqual(knight["stem"], stem)
                self.assertIn("n", knight)
                self.assertEqual(len(knight["st"]), 6)

    def test_special_schema(self):
        s = self.special
        self.assertEqual(s["stats"]["total"], len(s["instructions"]))
        # stats count the instructions carrying each field
        self.assertEqual(s["stats"]["in_ink"],
                         sum(1 for i in s["instructions"].values() if i.get("knots")))
        self.assertEqual(s["stats"]["in_quests"],
                         sum(1 for i in s["instructions"].values() if i.get("quests")))
        self.assertEqual(s["stats"]["knights"],
                         sum(1 for i in s["instructions"].values() if i.get("knight")))
        for name, inst in s["instructions"].items():
            with self.subTest(instruction=name):
                for key, kind in (("knots", list), ("quests", list),
                                  ("signal", str), ("note", str), ("knight", str),
                                  ("dlg", list), ("goto", list), ("auds", list),
                                  ("affects", list), ("vars", list), ("ending", str)):
                    if key in inst:
                        self.assertTrue(isinstance(inst[key], kind), key)
        # new cross-link fields resolve into the other datasets where present
        for name, inst in s["instructions"].items():
            with self.subTest(instruction=name):
                for k in inst.get("dlg", []) + inst.get("goto", []):
                    self.assertIn(k, self.index["knots"], (name, k))
                for a in inst.get("auds", []):
                    self.assertIn(a, self.audiences["audiences"], (name, a))
                for c in inst.get("affects", []):
                    found = any(c == km["stem"] for km in self.knights["knights"].values())
                    self.assertTrue(found, (name, c))


if __name__ == "__main__":
    unittest.main()

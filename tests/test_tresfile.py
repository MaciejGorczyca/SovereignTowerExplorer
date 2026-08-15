"""Tests for the Godot text-resource parsing in quest_data.py (TresFile etc.).

Uses self-contained fixtures under tests/fixtures (a sample quest .tres, an
IntRange ext file and a small enum .gd) so no game data is required.
"""
import os
import tempfile
import unittest
from pathlib import Path

from helpers import TESTS
import quest_data as Q

FIXTURES = TESTS / "fixtures"


class TresFileParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (FIXTURES / "tres" / "quest_sample.tres").read_text(encoding="utf-8")
        cls.tf = Q.TresFile(cls.text, str(FIXTURES / "tres"))

    def test_props(self):
        p = self.tf.props
        self.assertEqual(p["quest_name"], "CONTRACT_BIGGEST_ALIGOT_CONTEST_NAME")
        self.assertEqual(p["quest_id"], "contract_biggest_aligot_contest")
        self.assertEqual(p["duration"], 2)
        self.assertIs(p["is_lethal"], True)

    def test_stats_requirements_dict(self):
        p = self.tf.props
        self.assertEqual(p["stats_requirements"],
                         [{"key": 0, "value": 2}, {"key": 2, "value": 6}])

    def test_conditions_list(self):
        self.assertEqual(self.tf.props["quest_conditions"], [5, 20])

    def test_sub_resource_props(self):
        sp = self.tf.sub_props("Resource_85clu")
        self.assertEqual(sp["reward_type"], 1)
        self.assertEqual(sp["amount"], 1)
        self.assertEqual(sp["_type"], "Resource")

    def test_sub_resource_missing(self):
        self.assertEqual(self.tf.sub_props("nope"), {})

    def test_ext_path(self):
        self.assertEqual(self.tf.ext_path("1"),
                         "res://sub/int_range.tres")

    def test_resolve_sub(self):
        resolved = Q.resolve_sub(
            {"_sub": "Resource_87zq", "reward_type": 4,
             "consumable": {"_ext": "2"}}, self.tf)
        self.assertEqual(resolved["consumable"],
                         {"_path": "res://content/equipment/consumable/magic_aligot.tres"})


class IntRangeTest(unittest.TestCase):
    def test_sub_resource_defaults(self):
        tf = Q.TresFile((FIXTURES / "tres" / "quest_sample.tres").read_text(encoding="utf-8"),
                        str(FIXTURES / "tres"))
        # only `max = 2` is stored -> min defaults to 0, max default is 10
        self.assertEqual(Q.resolve_int_range(tf, {"_sub": "Resource_kjy55"}), [0, 2])

    def test_absent_ref(self):
        tf = Q.TresFile("", "")
        self.assertIsNone(Q.resolve_int_range(tf, None))
        # a _sub ref that doesn't exist falls back to the script defaults
        self.assertEqual(Q.resolve_int_range(tf, {"_sub": "zzz"}), [0, 10])

    def test_ext_resource_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / "sub").mkdir()
            (game / "sub" / "int_range.tres").write_text(
                '[gd_resource type="Script" format=3]\n\n[resource]\nmin = 0\nmax = 7\n',
                encoding="utf-8")
            old_game, old_dir = Q.GAME, Q.QUEST_DIR
            Q.set_game(str(game))
            try:
                tf = Q.TresFile((FIXTURES / "tres" / "quest_sample.tres").read_text(encoding="utf-8"),
                                str(FIXTURES / "tres"))
                self.assertEqual(Q.resolve_int_range(tf, {"_ext": "1"}), [0, 7])
            finally:
                Q.set_game(old_game)


class ValueParsingTest(unittest.TestCase):
    def test_enum_loading_non_sequential(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / "systems" / "autoloads").mkdir(parents=True)
            (game / "systems" / "autoloads" / "enums.gd").write_text(
                (FIXTURES / "gd" / "enums.gd").read_text(encoding="utf-8"), encoding="utf-8")
            old_game, old_dir = Q.GAME, Q.QUEST_DIR
            Q.set_game(str(game))
            try:
                self.assertEqual(Q.load_gd_enum("Statistics"),
                                 [("STRENGTH", 0), ("AGILITY", 1),
                                  ("CHARISMA", 3), ("MAGIC", 4), ("WITS", 5)])
                self.assertEqual(Q.load_gd_enum("CharacterTags"),
                                 [("VIRGO_SWORD", 11), ("POPULAR", 20), ("TIMID", 21)])
                self.assertIsNone(Q.load_gd_enum("DoesNotExist"))
            finally:
                Q.set_game(old_game)

    def test_split_top_nested(self):
        self.assertEqual(Q.TresFile._split_top("1, [2, 3], {4: 5}"),
                         ["1", " [2, 3]", " {4: 5}"])

    def test_needs_continuation(self):
        self.assertTrue(Q.TresFile._needs_continuation("{1: 2"))
        self.assertTrue(Q.TresFile._needs_continuation("[1,"))
        self.assertFalse(Q.TresFile._needs_continuation("simple"))

    def test_parse_value_primitives(self):
        tf = Q.TresFile("", "")
        self.assertEqual(tf._parse_value("42"), 42)
        self.assertEqual(tf._parse_value("-3"), -3)
        self.assertIs(tf._parse_value("true"), True)
        self.assertEqual(tf._parse_value('&"KEY_NAME"'), "KEY_NAME")
        self.assertEqual(tf._parse_value('ExtResource("1")'), {"_ext": "1"})
        self.assertEqual(tf._parse_value('SubResource("x")'), {"_sub": "x"})


if __name__ == "__main__":
    unittest.main()

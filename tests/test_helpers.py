"""Unit tests for the pure helper functions in build_app.py.

These are the small, self-contained building blocks of the build pipeline.
They run with no game data and are the cheapest layer to catch a refactor that
changes a helper's contract.
"""
import os
import unittest
from unittest import mock

from helpers import EXPLORER, GAME_ROOT
import build_app as B


class TailPathTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(B.tail_path(".^.^.^.follow_up"), "follow_up")
        self.assertEqual(B.tail_path(".^.b"), "b")
        self.assertEqual(B.tail_path("c-0"), "c-0")
        self.assertEqual(B.tail_path("global decl"), "global decl")

    def test_empty_and_dots(self):
        self.assertEqual(B.tail_path(""), "")
        self.assertEqual(B.tail_path("."), "")
        self.assertEqual(B.tail_path("..^^^.."), "")

    def test_windows_slash_path(self):
        # dot-segments are what tail_path operates on; the last is returned
        self.assertEqual(B.tail_path("a.b.c"), "c")
        self.assertEqual(B.tail_path("^.^.b"), "b")


class StringifyArgsTest(unittest.TestCase):
    def test_bools_ints_strings(self):
        self.assertEqual(B.stringify_args([True, False, 5, "x"]),
                         ["true", "false", "5", "x"])

    def test_none(self):
        self.assertEqual(B.stringify_args([None]), ["None"])


class IsEffectFnTest(unittest.TestCase):
    def test_state_mutations_are_effects(self):
        self.assertTrue(B.is_effect_fn("set:x"))
        self.assertTrue(B.is_effect_fn("UpdateFunds"))
        self.assertTrue(B.is_effect_fn("UnlockQuest"))

    def test_presentation_is_not(self):
        self.assertFalse(B.is_effect_fn("Locutor"))
        self.assertFalse(B.is_effect_fn("SwapExpression"))
        self.assertFalse(B.is_effect_fn("FlashScreen"))
        self.assertFalse(B.is_effect_fn("RevealLUT"))


class IsNamedChildrenTest(unittest.TestCase):
    def test_named_stitch_dicts(self):
        self.assertTrue(B.is_named_children({"stitch": []}))
        self.assertTrue(B.is_named_children({"a": [1], "b": {}}))

    def test_content_op_dicts(self):
        self.assertFalse(B.is_named_children({"->": ".x"}))
        self.assertFalse(B.is_named_children({"f()": "X"}))
        self.assertFalse(B.is_named_children({"VAR?": "x"}))

    def test_non_dicts(self):
        self.assertFalse(B.is_named_children("x"))
        self.assertFalse(B.is_named_children(None))
        self.assertFalse(B.is_named_children({}))
        self.assertFalse(B.is_named_children([1, 2]))


class TokenKindTest(unittest.TestCase):
    def test_is_bare_temp(self):
        self.assertTrue(B.is_bare_temp(["3", "set:temp=", ["x"]]))
        self.assertFalse(B.is_bare_temp(["3", "set:temp=", ["x", "y"]]))
        self.assertFalse(B.is_bare_temp(["3", "set:VAR=", ["x"]]))

    def test_is_plumbing_write(self):
        self.assertTrue(B.is_plumbing_write(["3", "set:temp=", ["$r"]]))
        self.assertTrue(B.is_plumbing_write(["3", "set:temp=", ["$t"]]))
        self.assertFalse(B.is_plumbing_write(["3", "set:temp=", ["x"]]))


class FoldParamRunsTest(unittest.TestCase):
    def test_folds_bare_temp_run(self):
        tokens = [["5", "sig"],
                  ["3", "set:temp=", ["p1"]],
                  ["3", "set:temp=", ["p2"]],
                  ["0", "text", ""]]
        # compiled order is reversed from declaration order
        self.assertEqual(B.fold_param_runs(tokens),
                         [["5", "sig", ["p2", "p1"]], ["0", "text", ""]])

    def test_keeps_plain_header(self):
        self.assertEqual(B.fold_param_runs([["5", "sig"]]), [["5", "sig"]])


class ExprToInfixTest(unittest.TestCase):
    def test_binary(self):
        self.assertEqual(B.expr_to_infix(["a", "b", "&&"]), "a && b")
        self.assertEqual(B.expr_to_infix(["kind_value", "highest", ">"]),
                         "kind_value > highest")

    def test_negation(self):
        self.assertEqual(B.expr_to_infix(["a", "!"]), "!a")

    def test_empty(self):
        self.assertEqual(B.expr_to_infix([]), "")
        self.assertEqual(B.expr_to_infix(None), "")


class ClassifyTest(unittest.TestCase):
    def test_game_api(self):
        self.assertEqual(B.classify("UpdateFunds"), "game_api_function")

    def test_categories(self):
        cases = [
            ("county_quest_enberg_2", "county_quest"),
            ("candidature_arlin", "candidacy_audience"),
            ("conversation_arlin_silgur", "knight_knight_conversation"),
            ("scriptedquest_traitors_plot_3", "scripted_quest"),
            ("scriptedgrievance_milkford", "scripted_grievance"),
            ("grievance_milkford", "grievance"),
            ("ultimatum_kingslayer", "ultimatum"),
            ("knight_leaving_chester", "knight_leaving"),
            ("arlin_ending", "ending"),
            ("x_affinity", "affinity_conversation"),
            ("come_back_later_arlin", "come_back_later"),
            ("ar_recruit", "recruitment"),
            ("intervention_tarcus", "intervention"),
            ("demon_kingslayer", "demon"),
            ("lost_child", "traitors_plot"),
            # startswith matches take precedence over the `_reaction` suffix
            ("grievance_reaction", "grievance"),
            ("some_reaction", "reaction"),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(B.classify(name), expected)

    def test_default_misc(self):
        self.assertEqual(B.classify("random_name"), "misc")


class ParseFlagsTest(unittest.TestCase):
    def test_plain_positionals(self):
        flags, pos = B.parse_flags(["a", "b", "c"])
        self.assertFalse(flags["from_disk"])
        self.assertEqual(pos, ["a", "b", "c"])

    def test_all_flags(self):
        flags, pos = B.parse_flags(["--from-disk", "--profile",
                                    "--extract-ink", "/tmp/out", "a", "b"])
        self.assertTrue(flags["from_disk"])
        self.assertTrue(flags["profile"])
        self.assertEqual(flags["extract_ink"], "/tmp/out")
        self.assertEqual(pos, ["a", "b"])

    def test_save_ink_without_value(self):
        flags, pos = B.parse_flags(["--save-ink"])
        self.assertEqual(flags["save_ink"], None)
        self.assertEqual(pos, [])

    def test_flag_value_consumption(self):
        flags, pos = B.parse_flags(["--save-ink", "dir"])
        self.assertEqual(flags["save_ink"], "dir")
        self.assertEqual(pos, [])


class ResolvePathsTest(unittest.TestCase):
    def test_defaults(self):
        ink_root, out_dir, game_root = B.resolve_paths([])
        self.assertEqual(out_dir, EXPLORER / "dist")
        self.assertEqual(game_root, GAME_ROOT)

    def test_env_overrides(self):
        with mock.patch.dict(os.environ, {
            "INK_ROOT": "/tmp/ink", "INK_OUT": "/tmp/out", "GAME_ROOT": "/tmp/game"
        }):
            ink_root, out_dir, game_root = B.resolve_paths([])
            self.assertEqual(str(ink_root), "/tmp/ink")
            self.assertEqual(str(out_dir), "/tmp/out")
            self.assertEqual(str(game_root), "/tmp/game")

    def test_cli_wins_over_env(self):
        with mock.patch.dict(os.environ, {"INK_ROOT": "/env/ink", "INK_OUT": "/env/out"}):
            ink_root, out_dir, game_root = B.resolve_paths(["/cli/ink", "/cli/out"])
            self.assertEqual(str(ink_root), "/cli/ink")
            self.assertEqual(str(out_dir), "/cli/out")


class InkContainerTest(unittest.TestCase):
    def test_knot_split(self):
        knot = [["ev", {"VAR?": "x"}, "out", "/ev", "^hi", "\n"], {"#f": 1}]
        content, named = B.ink_container(knot)
        self.assertEqual(len(content), 1)
        self.assertIn("#f", named)

    def test_content_ops_stay_in_content(self):
        content, named = B.ink_container([{"->": ".x"}, {"f()": "Y"}])
        self.assertEqual(len(content), 2)
        self.assertEqual(named, {})

    def test_leaf_dict(self):
        content, named = B.ink_container({"f()": "x"})
        self.assertEqual(content, [{"f()": "x"}])
        self.assertEqual(named, {})


if __name__ == "__main__":
    unittest.main()

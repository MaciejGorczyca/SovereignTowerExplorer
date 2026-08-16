"""Tests for the compiled-ink Walker in build_app.py.

Runs the real `Walker` over verbatim copies of real game knots
(tests/fixtures/ink_knots.py) and asserts the exact token streams, reads,
writes and metadata the current build ships in dist/index.json. This locks the
walker's output contract in place so a refactor of build_app.py can be
verified without breaking it.
"""
import unittest

from helpers import EXPLORER
import build_app as B
from fixtures import ink_knots as F


def walk_knot(node):
    w = B.Walker()
    w.walk(node)
    tok, params = B.finalize_tokens(w.tok)
    return w, tok, params


class WalkerSpeakerAndChoiceTest(unittest.TestCase):
    """test_affinity_angelica: speaker attribution, presentation fns, (end) choice."""

    def test_tokens(self):
        w, tok, params = walk_knot(F.SPEAKER_CHOICE)
        self.assertEqual(params, [])
        self.assertEqual(tok, [
            ["3", "Apparition", ["Angelica"]],
            ["0", " Hello Your Grace!", "Angelica"],
            ["0", "How are you?", "Angelica"],
            ["2", "Hellooooooooooooooooooooooooooooooo", [], 4, "(end)", []],
        ])

    def test_metadata(self):
        w, tok, params = walk_knot(F.SPEAKER_CHOICE)
        self.assertEqual(set(w.speaker_counts), {"Angelica"})
        self.assertIn("Angelica", w.read_counts)
        self.assertEqual(w.choices, 1)


class WalkerIfOnlyTest(unittest.TestCase):
    """ligia_ending: a bare `if` branch must open a block and close with an endif."""

    def test_tokens(self):
        w, tok, params = walk_knot(F.IF_ONLY)
        self.assertEqual(tok, [
            ["0", "Ligia eventually disappeared, and no one ever saw her again.", "Narrator"],
            ["0", "It is said, however, that off the shores of Southbay, sailors were saved by a mysterious mermaid princess...", "Narrator"],
            ["7", ["ligia_romanced"], "ligia_romanced", "1"],
            ["0", "... This mermaid may also have been heard at times near the shores of Grest, singing a melancholy lullaby into the night.", "Narrator"],
            ["8"],
        ])


class WalkerIfElseTest(unittest.TestCase):
    """kingslayer_cutscene: the sibling `-> b` divert must emit a negated else gate."""

    def test_tokens(self):
        w, tok, params = walk_knot(F.IF_ELSE)
        self.assertEqual(tok, [
            ["7", ["ursula_sent_to_kingslayer"], "ursula_sent_to_kingslayer", "1"],
            ["0", "A dull magical tension grips the air as the Kingslayer stands before your knight, impassive.", "Narrator"],
            ["0", "May she emerge from this unscathed...", "Narrator"],
            ["7", ["!ursula_sent_to_kingslayer"], "!ursula_sent_to_kingslayer"],
            ["0", "A dull magical tension grips the air as the Kingslayer stands before your knights, impassive.", "Narrator"],
            ["0", "May they emerge from this unscathed...", "Narrator"],
            ["8"],
        ])


class WalkerFunctionKnotsTest(unittest.TestCase):
    """Game-API function knots: temp params, VAR? reads, WRITE_SLOT0 attribution."""

    def test_update_funds(self):
        w, tok, params = walk_knot(F.FUNCTION_FUNDS)
        self.assertEqual(params, ["Amount"])
        # the temp= write is folded as a knot param, not shipped as a token
        self.assertEqual(tok, [["0", ">>> update_funds : ", ""]])
        # the write is structural (temp= declaration), collected by collect_meta
        self.assertEqual(B.collect_meta(F.FUNCTION_FUNDS)["writes"], {"Amount"})
        # the Amount arg is read (VAR?) inside the ev frame
        self.assertIn("Amount", w.read_counts)

    def test_murdered_knight(self):
        w, tok, params = walk_knot(F.FUNCTION_MURDERED)
        self.assertEqual(params, [])
        self.assertEqual(tok, [])
        # `^{name}` is string interpolation, not a VAR? read — no var metadata
        self.assertEqual(list(w.read_counts), [])


class WalkerChoiceEffectsTest(unittest.TestCase):
    """tortosa_grievance_emergency: choice requirements, dest resolution and
    the UnlockQuest effect attached to the choice card (semantic write)."""

    def test_tokens(self):
        w, tok, params = walk_knot(F.CHOICE_EFFECTS)
        self.assertEqual(params, [])
        self.assertEqual(tok, [
            ["3", "Apparition", ["Cinderbeard"]],
            ["3", "SwapExpression", ["Cinderbeard", "Worried"]],
            ["0", "Ahoy!", "Cinderbeard"],
            ["1", "(BREAK_3)", "i"],
            ["0", " Uh... we've got ourselves a bit of a pirate problem out on the islands.", "Cinderbeard", "c"],
            ["0", "And dragons, too.", "Cinderbeard"],
            ["1", "(BREAK_3)", "i"],
            ["0", " Pirate-ridin' dragons, to be precise.", "Cinderbeard", "c"],
            ["1", "(BREAK_3)", "i"],
            ["0", ".", "Cinderbeard", "c"],
            ["1", "(BREAK_3)", "i"],
            ["0", ". they're firing off cannonballs and breathin' fire all at once.", "Cinderbeard", "c"],
            ["3", "HintModification", ["QUEST", "quest_tortosa_emergency"]],
            ["2", "A squad arrives to the rescue.", [], 4, "accept",
             [["UnlockQuest", ["quest_tortosa_emergency"]]]],
            ["5", "accept"],
            ["3", "SwapExpression", ["Cinderbeard", "Smiling"]],
            ["0", "Nice.", "Cinderbeard"],
            ["1", "(BREAK_3)", "i"],
            ["0", " I'll tell the pirates to mind their manners while we wait.", "Cinderbeard", "c"],
        ])

    def test_semantic_write(self):
        w, tok, params = walk_knot(F.CHOICE_EFFECTS)
        # UnlockQuest's slot-0 arg names the variable it writes (semantic attribution)
        self.assertIn("quest_tortosa_emergency", w.sem_writes)
        # and it was also read once (the VAR? before the call) so it must NOT
        # be double-counted as a pure write
        self.assertGreater(w.read_counts["quest_tortosa_emergency"], 0)


class WalkerMetaTest(unittest.TestCase):
    """collect_meta over the fixtures matches the shipped metadata."""

    def test_meta_choices(self):
        w, tok, params = walk_knot(F.CHOICE_EFFECTS)
        meta = B.collect_meta(F.CHOICE_EFFECTS)
        self.assertEqual(meta["choices"], 1)
        self.assertIn("UnlockQuest", meta["funcs"])
        self.assertIn("HintModification", meta["funcs"])


class WalkerStubCondDivertTest(unittest.TestCase):
    """county_quest_enberg_audience_2: a choice stub whose if/else branches are
    pure diverts must keep those diverts in the flow so the gates are not empty
    and both the if and the else impact are visible."""

    def test_tokens(self):
        w, tok, params = walk_knot(F.STUB_COND_DIVERT)
        self.assertEqual(params, [])
        self.assertEqual(tok, [
            ["2", "Any thoughts on the victim?", [], 5,
             "polmauz_interrogation_phase", [], [],
             [
                 ["7", ["polmauz_available"], "polmauz_available", "1"],
                 ["4", ".^.^.^.^.^.^.polmauz_interrogation_phase"],
                 ["7", ["!polmauz_available"], "!polmauz_available"],
                 ["4", ".^.^.^.^.^.^.end_interrogatory_phases"],
                 ["8"],
             ]],
        ])


class WalkerStubEndLoopTest(unittest.TestCase):
    """lady_tower_act_2_reached_reaction: a choice stub whose if-branch ends the
    dialogue and whose else-branch loops back must surface `(end)`/`(options)`
    as branch outcomes instead of rendering an empty if/else."""

    def test_tokens(self):
        w, tok, params = walk_knot(F.STUB_END_LOOP)
        self.assertEqual(params, [])
        self.assertEqual(tok, [
            ["2", "What do you mean?", [], 5, "(end)", [], [],
             [
                 ["0", "It became necessary to curb the Tower powers.", ""],
                 ["7", ["former_glory_seen"], "former_glory_seen", "1"],
                 ["4", "(end)"],
                 ["7", ["!former_glory_seen"], "!former_glory_seen"],
                 ["4", "(options)"],
                 ["8"],
             ]],
        ])


if __name__ == "__main__":
    unittest.main()

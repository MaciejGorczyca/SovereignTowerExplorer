"""Golden build test: a fresh build must reproduce the checked-in dist/ exactly.

OPT-IN, refactor-only: this test is deliberately NOT part of the default
`tests/run_tests.py` suite (it rebuilds the whole app just to confirm a fresh
build is byte-identical to a reference dist/, which only earns its time on
refactors — not on every feature commit). Include it explicitly with:

    python3 tests/run_tests.py --golden          # default suite + this test
    python3 tests/test_build_golden.py           # standalone
    python3 tests/check_dist_ref.py dev|main     # fresh build vs another ref's dist/

This is the highest-value regression test for a refactor: the build is
deterministic, so after splitting `build_app.py` / the data passes into smaller
modules with no behaviour change, a fresh build must be byte-identical to the
reference `dist/`. Any difference is flagged here (plus a diff summary), so an
intentional data change updates `dist/` and this test in the same commit.

Requires the game project (for in-memory ink extraction) and the `zstandard`
pip package; skips cleanly when either is absent.
"""
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import DIST, EXPLORER, game_available, has_zstandard

BUILD = EXPLORER / "build_app.py"

SKIP_REASON = None
if not game_available():
    SKIP_REASON = "game/SovereignTowerCode not present"
elif not has_zstandard():
    SKIP_REASON = "zstandard pip package not installed"
elif not DIST.is_dir():
    SKIP_REASON = "no checked-in dist/ to compare against"


@unittest.skipUnless(SKIP_REASON is None, SKIP_REASON)
class GoldenBuildTest(unittest.TestCase):
    def test_rebuild_matches_dist(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(BUILD)],
                cwd=str(EXPLORER),
                env={**os.environ, "INK_OUT": tmp},
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0,
                             "build failed:\n%s" % proc.stderr)

            differ = filecmp.dircmp(str(DIST), tmp)
            missing = differ.left_only or differ.right_only
            self.assertEqual(missing, [], "file sets differ: %r" % missing)

            differing = _recursive_diff(differ)
            self.assertEqual(differing, [],
                             "dist/ and fresh build differ: %r" % differing)


def _recursive_diff(dcmp, prefix="dist"):
    diffs = []
    for name in dcmp.diff_files:
        diffs.append(os.path.join(prefix, name))
    for name in dcmp.left_only:
        diffs.append(os.path.join(prefix, name, "(missing in build)"))
    for name in dcmp.right_only:
        diffs.append(os.path.join(prefix, "(missing)", name))
    for sub in dcmp.subdirs.values():
        diffs.extend(_recursive_diff(sub, os.path.join(prefix, sub.left)))
    return diffs


if __name__ == "__main__":
    unittest.main()

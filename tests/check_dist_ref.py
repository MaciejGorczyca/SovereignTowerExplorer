#!/usr/bin/env python3
"""Validate the current build against another git ref's dist/ (golden-by-reference).

The golden test normally checks a fresh build against the *checked-in* dist/.
This script lets you compare against any other branch/commit/tag instead, e.g.
while refactoring on a branch. This is the recommended refactor check: run it
against the base branch before and after the refactor to confirm the build
output is byte-identical (nothing broke, nothing changed):

    python3 tests/check_dist_ref.py main          # current build vs main's dist
    python3 tests/check_dist_ref.py dev           # ... vs dev's dist
    python3 tests/check_dist_ref.py <commit-sha>  # vs dist a few commits ago

It extracts `<ref>:dist/` via `git archive` into a temp dir, points the suite
at it via EXPLORER_DIST, and runs the full test suite (including the opt-in
golden build test via `--golden`). The golden test's fresh build (built into
its own temp dir) is then diffed against that ref's dist.

Requires a git repo at the explorer root and a `dist/` present in <ref>.
"""
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

EXPLORER = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) != 2:
        print("usage: python3 tests/check_dist_ref.py <branch|commit|tag>", file=sys.stderr)
        return 2
    ref = sys.argv[1]

    if not (EXPLORER / ".git").is_dir():
        print("error: no git repo at explorer root", file=sys.stderr)
        return 2

    try:
        subprocess.run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
                       cwd=EXPLORER, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print(f"error: '{ref}' is not a valid branch/commit/tag", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="dist-ref-") as tmp:
        target = Path(tmp)
        tar_bytes = subprocess.run(
            ["git", "archive", ref, "dist"],
            cwd=EXPLORER, check=True, capture_output=True,
        ).stdout
        with tarfile.open(fileobj=__import__("io").BytesIO(tar_bytes)) as tf:
            tf.extractall(target)

        if not (target / "dist").is_dir():
            print(f"error: '{ref}' has no tracked dist/ to compare against", file=sys.stderr)
            return 2

        print(f"checking build against '{ref}' dist/ ({target / 'dist'})")
        env = {**os.environ, "EXPLORER_DIST": str(target / "dist")}
        code = subprocess.call(
            [sys.executable, str(EXPLORER / "tests" / "run_tests.py"), "--golden"],
            env=env)
        return code


if __name__ == "__main__":
    sys.exit(main())

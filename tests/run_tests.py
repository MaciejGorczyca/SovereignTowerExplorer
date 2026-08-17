#!/usr/bin/env python3
"""Canonical test-suite entrypoint for the explorer build pipeline.

Usage:
    python3 tests/run_tests.py                # default suite (no golden build test)
    python3 tests/run_tests.py --golden       # default suite + golden build test
    python3 tests/run_tests.py <pattern>      # filter to one module (substring match)

Loads every `test_*.py` module in tests/ and runs it with stdlib unittest
(no third-party test runner required). Modules that need the game data or a
runtime (zstandard / node) skip cleanly when those are missing.

The golden build test (`test_build_golden`) is deliberately **not** part of the
default suite, and you should NOT run it unless you are doing a REFACTOR task:
it rebuilds the whole app (~20 s) just to confirm the build output is
byte-identical to a reference dist/, which adds zero value for feature/fix/docs
work (the build is deterministic — two consecutive builds already match). On a
refactor only, opt in with `--golden` or compare against another ref's `dist/`
via `python3 tests/check_dist_ref.py <branch|commit>` (which adds `--golden`).
"""
import importlib
import os
import sys
import time
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
EXPLORER = os.path.dirname(TESTS)
for _p in (TESTS, EXPLORER):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MODULES = [
    "test_helpers",
    "test_walker",
    "test_tresfile",
    "test_dist_conformance",
    "test_data_passes",
    "test_frontend",
]

GOLDEN_MODULE = "test_build_golden"


def build_suite(pattern, golden):
    suite = unittest.TestSuite()
    modules = list(MODULES)
    if golden or (pattern and pattern.lower() in GOLDEN_MODULE):
        modules.append(GOLDEN_MODULE)
    for name in modules:
        if pattern and pattern.lower() not in name:
            continue
        mod = importlib.import_module(name)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(mod))
    return suite


class TimedResult(unittest.TextTestResult):
    """TextTestResult that also records wall time per test module.

    Lets agents see exactly where suite time goes (e.g. which data pass or the
    full-build golden test) without changing the run output format.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timings = {}
        self._cur = None
        self._t0 = None

    def startTest(self, test):
        mod = test.__class__.__module__
        if mod != self._cur:
            if self._cur is not None:
                self.timings[self._cur] += time.perf_counter() - self._t0
            self._cur = mod
            self.timings.setdefault(mod, 0.0)
            self._t0 = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        if test.__class__.__module__ != self._cur:
            return
        if self._t0 is not None:
            self.timings[self._cur] += time.perf_counter() - self._t0
            self._t0 = time.perf_counter()


if __name__ == "__main__":
    golden = "--golden" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--golden"]
    pattern = args[0] if args else ""
    start = time.perf_counter()
    suite = build_suite(pattern, golden)
    runner = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult)
    result = runner.run(suite)
    wall = time.perf_counter() - start
    print("\n-- per-module timing --")
    for name, ts in result.timings.items():
        print("  %-28s %6.2fs" % (name, ts))
    print("  %-28s %6.2fs  (total suite)" % ("TOTAL", wall))
    sys.exit(0 if result.wasSuccessful() else 1)

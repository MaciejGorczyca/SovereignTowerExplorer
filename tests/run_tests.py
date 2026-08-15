#!/usr/bin/env python3
"""Canonical test-suite entrypoint for the explorer build pipeline.

Usage:  python3 tests/run_tests.py  [pattern]

Loads every `test_*.py` module in tests/ and runs it with stdlib unittest
(no third-party test runner required). Modules that need the game data or a
runtime (zstandard / node) skip cleanly when those are missing.
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
    "test_build_golden",
    "test_frontend",
]


def build_suite(pattern):
    suite = unittest.TestSuite()
    for name in MODULES:
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
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    start = time.perf_counter()
    suite = build_suite(pattern)
    runner = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult)
    result = runner.run(suite)
    wall = time.perf_counter() - start
    print("\n-- per-module timing --")
    for name, ts in result.timings.items():
        print("  %-28s %6.2fs" % (name, ts))
    print("  %-28s %6.2fs  (total suite)" % ("TOTAL", wall))
    sys.exit(0 if result.wasSuccessful() else 1)

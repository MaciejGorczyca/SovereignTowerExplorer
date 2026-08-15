"""Test suite for the Sovereign Tower Explorer build pipeline.

Run the whole suite with:  python3 tests/run_tests.py
(The `tests/` and `explorer/` directories are added to sys.path here so the
suite also works under `python3 -m unittest discover -s tests`.)
"""
import os
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
_EXPLORER = os.path.dirname(_TESTS)
for _p in (_TESTS, _EXPLORER):
    if _p not in sys.path:
        sys.path.insert(0, _p)

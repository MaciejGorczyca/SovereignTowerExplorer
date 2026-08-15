#!/usr/bin/env python3
"""Diff the generic evolution finder against the manual EVO_DEFS output.

Reads dist/evolutions.json (finder output) and compares it to the evo blocks
produced by knights_data.build_evolutions (EVO_DEFS-driven, also present in
dist/knights.json). Reports per-evolution field mismatches so a human can
reconcile, not silently override.
"""

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def norm_trigger(s):
    return (s or "").upper().strip('"& ')


def load_evo_defs():
    """{stem: {trigger: evo}} from knights.json (EVO_DEFS-driven)."""
    p = SCRIPT_DIR / "dist" / "knights.json"
    if not p.exists():
        return None
    data = json.load(open(p, encoding="utf-8"))
    out = {}
    for stem, k in data.get("knights", {}).items():
        for evo in k.get("evo", []):
            trig = norm_trigger(evo.get("trigger") or evo.get("name"))
            out[(stem, trig)] = evo
    return out


def load_finder():
    data = json.load(open(SCRIPT_DIR / "dist" / "evolutions.json", encoding="utf-8"))
    out = {}
    for stem, evos in data.items():
        for evo in evos:
            trig = norm_trigger(evo.get("trigger") or evo.get("name"))
            out[(stem, trig)] = evo
    return out


def fields_to_compare():
    return ["name", "stats", "features", "relic", "meals", "removes", "armor"]


def diff_fields(a, b):
    """Return list of (field, manual_val, finder_val) for differing fields."""
    diffs = []
    for f in fields_to_compare():
        va, vb = a.get(f), b.get(f)
        if va == vb:
            continue
        diffs.append((f, va, vb))
    return diffs


def main():
    defs = load_evo_defs()
    finder = load_finder()
    if defs is None:
        print("dist/knights.json missing — run build_app.py first")
        return 1

    keys = sorted(set(defs) | set(finder))
    only_manual, only_finder, mismatches = [], [], []
    match = 0
    for key in keys:
        stem, trig = key
        if key not in finder:
            only_manual.append(key)
            continue
        if key not in defs:
            only_finder.append(key)
            continue
        d = diff_fields(defs[key], finder[key])
        if d:
            mismatches.append((key, d))
        else:
            match += 1

    print(f"== mismatched evolutions: {len(mismatches)} ==")
    for (stem, trig), diffs in mismatches:
        print(f"\n{stem} / {trig}")
        for f, va, vb in diffs:
            print(f"  {f:8s} manual={va}")
            print(f"  {'':8s} finder={vb}")
    print(f"\n== manual-only (not found by finder): {len(only_manual)} ==")
    for k in sorted(only_manual):
        print("  ", k, defs[k].get("note", ""))
    print(f"== finder-only (not in EVO_DEFS): {len(only_finder)} ==")
    for k in sorted(only_finder):
        print("  ", k)
    print(f"\nmatched exactly: {match}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
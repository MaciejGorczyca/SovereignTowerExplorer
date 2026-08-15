#!/usr/bin/env python3
"""Sovereign Tower — SpecialInstruction catalog extractor.

Emits `dist/special.json`: the ink/game `SpecialInstruction(...)` catalog.

A `SpecialInstruction` is the game's director instruction that a dialogue knot
emits (or a quest reward grants) to flip a real gameplay switch — most notably
a knight's evolution state. The raw knot drawer usefulness stops at the call
name; this pass decodes it by joining three sources:

1. `systems/autoloads/special_instruction_manager.gd`   — the `match` table:
   instruction name -> the SignalsEventBus signal it fires (best-effort first
   signal per case; used as the human-friendly fallback).
2. the compiled ink story (dist/index.json knot lines)   — which knots emit
   which instruction (`SpecialInstruction(<Arg>)` fn-call args).
3. dist/quests.json (SPECIAL_INSTRUCTION rewards)        — which quests grant
   which instruction as a success/failure reward.

For the knight-evolution instructions the one-line `note` is derived from the
knight evolution blocks (dist/knights.json per-knight `evo`), so the text never
drifts from the stat/feature data shown on the Knights tab. Everything else
falls back to a humanised signal name (or the raw instruction name).

Output shape (dist/special.json):
  instructions:  { "<UPPER_NAME>": {knots: [..], quests: [..],
                                     signal: str, knight: str, note: str} }
  stats:         header counts
"""

import collections
import json
import os
import re
import sys
from pathlib import Path

from quest_data import set_game  # noqa: F401  (kept for API parity with sibling modules)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GAME_ROOT = (SCRIPT_DIR.parent / "game" / "SovereignTowerCode").resolve()

GAME = str(DEFAULT_GAME_ROOT)

STAT_NAMES = ["STRENGTH", "AGILITY", "CHARISMA", "MAGIC", "WITS", "LUCK"]


def set_special_root(root):
    """Point this module's GAME at a given game root (see build_app)."""
    global GAME
    GAME = str(Path(root).expanduser().resolve())

INSTRUCTION_CASE = re.compile(r'^\s*&\s*"([^"]+)"\s*:\s*$')
SIGNAL_EMIT = re.compile(r"SignalsEventBus\.(\w+)\.emit\b")


def load_special_instructions():
    """Parse special_instruction_manager.gd's match table -> {NAME: first signal}.

    Best-effort: each `&"NAME":` case is followed by handler statements; the
    first SignalsEventBus.<signal>.emit found inside a case names its signal.
    """
    path = f"{GAME}/systems/autoloads/special_instruction_manager.gd"
    if not os.path.exists(path):
        return {}
    out = {}
    cur = None
    for line in open(path, encoding="utf-8"):
        m = INSTRUCTION_CASE.match(line)
        if m:
            cur = m.group(1).upper()
            out.setdefault(cur, "")
            continue
        if cur is None:
            continue
        if out[cur]:
            continue
        sm = SIGNAL_EMIT.search(line)
        if sm:
            out[cur] = sm.group(1)
    return out


def _humanize(signal):
    words = [w for w in re.split(r"[_ ]+", signal) if w and w not in ("set", "triggered")]
    return " ".join(w[:1].upper() + w[1:] for w in words) if words else signal


def _knight_evo_notes(knights):
    """trigger instruction -> one-line effect note, from the knight `evo` blocks."""
    notes = {}
    for stem, k in (knights or {}).items():
        for evo in (k.get("evo") or []):
            trig = (evo.get("trigger") or "").upper()
            if not trig:
                continue
            parts = []
            for i, v in enumerate(evo.get("stats") or []):
                if v:
                    parts.append("%s%d %s" % ("+" if v > 0 else "", v, STAT_NAMES[i]))
            feats = [(f.get("n") or "?") for f in (evo.get("features") or [])]
            if feats:
                parts.append("gains " + ", ".join(feats))
            if evo.get("relic"):
                parts.append("gains relic " + evo["relic"])
            if evo.get("removes"):
                parts.append("loses " + ", ".join(evo["removes"]))
            body = "; ".join(parts)
            if evo.get("note"):
                body = (body + "; " + evo["note"]) if body else evo["note"]
            label = "%s → %s" % (stem.title(), evo["name"])
            notes[trig] = (label + ": " + body) if body else label
    return notes


def build_special(out_dir, quests_data, index, knights_data, game_root=None):
    """Write dist/special.json and return the data dict."""
    if game_root is not None:
        set_special_root(game_root)
    instr = load_special_instructions()

    knot_map = collections.defaultdict(list)
    if index and index.get("knots"):
        for name, k in index["knots"].items():
            for t in (k.get("lines") or []):
                if isinstance(t, list) and t[:2] == ["3", "SpecialInstruction"]:
                    for a in (t[2] or []):
                        key = str(a).upper()
                        if key:
                            knot_map[key].append(name)

    si_value = None
    if quests_data:
        for entry in (quests_data.get("enums") or {}).get("RewardType", []):
            if len(entry) == 2 and entry[1] == "SPECIAL_INSTRUCTION":
                si_value = entry[0]
                break
    quest_map = collections.defaultdict(list)
    if quests_data and si_value is not None:
        for qid, q in (quests_data.get("quests") or {}).items():
            for bucket in ("s", "f"):
                for r in (q.get("rw") or {}).get(bucket, []):
                    if r.get("t") == si_value and r.get("v"):
                        quest_map[str(r["v"]).upper()].append(qid)
            # unexpected-outcome rewards grant instructions too (e.g.
            # quest_ultimatum_kingslayer_ursula's URSULA_DESTROYED_BY_KINGSLAYER)
            for uo in (q.get("un") or []):
                for r in (uo.get("rw") or []):
                    if r.get("t") == si_value and r.get("v"):
                        quest_map[str(r["v"]).upper()].append(qid)
            # modifier success/failure rewards
            for mo in (q.get("mo") or []):
                for r in (mo.get("sr") or []) + (mo.get("fr") or []):
                    if r.get("t") == si_value and r.get("v"):
                        quest_map[str(r["v"]).upper()].append(qid)

    evo_notes = _knight_evo_notes((knights_data or {}).get("knights"))
    instr_source = dict(load_special_instructions())

    # union of every instruction name we know about (manager + ink + quests)
    names = set(instr_source) | set(knot_map) | set(quest_map) | set(evo_notes)
    instructions = {}
    for name in sorted(names):
        signal = instr_source.get(name) or ""
        note = evo_notes.get(name)
        if not note and signal:
            note = _humanize(signal)
        if not note:
            note = ""
        inst = {}
        if signal:
            inst["signal"] = signal
        if knot_map.get(name):
            inst["knots"] = sorted(set(knot_map[name]))
        if quest_map.get(name):
            inst["quests"] = sorted(set(quest_map[name]))
        if note:
            inst["note"] = note
        if name in evo_notes:
            # find the owning knight for cross-linking
            for kname, kdata in (knights_data or {}).get("knights", {}).items():
                if any((e.get("trigger") or "").upper() == name for e in (kdata.get("evo") or [])):
                    inst["knight"] = kname
                    break
        instructions[name] = inst

    data = {
        "instructions": instructions,
        "stats": {
            "total": len(instructions),
            "in_ink": len(knot_map),
            "in_quests": len(quest_map),
            "knights": len(evo_notes),
        },
    }
    out_path = Path(out_dir) / "special.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Special instructions: {data['stats']['total']} catalogued · "
          f"{data['stats']['in_ink']} emitted in ink · {data['stats']['in_quests']} as quest rewards · "
          f"{data['stats']['knights']} knight evolutions")
    return data


def main(argv=None):
    args = list(sys.argv[1:]) if argv is None else list(argv)
    game_root = args[0] if len(args) > 0 else ""
    out_dir = args[1] if len(args) > 1 else ""
    game_root = str(Path(game_root).expanduser().resolve()) if game_root else DEFAULT_GAME_ROOT
    set_special_root(game_root)
    out_dir = Path(out_dir).expanduser().resolve() if out_dir else (SCRIPT_DIR / "dist")

    quests_path = out_dir / "quests.json"
    quests_data = json.load(open(quests_path, encoding="utf-8")) if quests_path.exists() else None
    index_path = out_dir / "index.json"
    index = json.load(open(index_path, encoding="utf-8")) if index_path.exists() else None
    knights_path = out_dir / "knights.json"
    knights = json.load(open(knights_path, encoding="utf-8")) if knights_path.exists() else None

    build_special(out_dir, quests_data, index, knights)


if __name__ == "__main__":
    main()
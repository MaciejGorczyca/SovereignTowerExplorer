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
                                     signal: str, knight: str, note: str,
                                     dlg: [..], goto: [..], auds: [..],
                                     affects: [..], vars: [..], ending: str} }
  stats:         header counts

The cross-link fields beyond `knots`/`quests` are decoded from the manager's
match-case bodies:

  dlg      ink knots this instruction unlocks as a special dialogue
           (GIDEON_VICTORIA_DEAD -> gideon_victoria_dead_reaction, via the
           owning knight's `specd` map)
  goto     ink knots the instruction diverts to (StoryController.goto targets,
           resolved through the exported StringName in story_controller.tscn)
  auds     audience resources the instruction schedules/unlocks (add_audience
           / audience_unlocked_for_next_cycle, resolved via the tscn exports)
  affects  knight/character stems the instruction targets directly
           (get_knight_from_name, trigger_dialogues_unlock_for_knight, the
           character of an unlock_special_dialogue)
  vars     story variables the instruction writes (StoryController.set_variable)
  ending   ending path switched to (EndingManager.Endings.X)
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
# effect patterns mined from each match-case body:
DLG_EMIT = re.compile(r'SignalsEventBus\.unlock_special_dialogue\.emit\(\s*&\s*"([^"]+)"\s*,\s*&\s*"([^"]+)"\s*\)')
GOTO_CALL = re.compile(r"StoryController\.goto\(\s*(\w+)\s*,")
AUD_NEXT = re.compile(r"SignalsEventBus\.audience_unlocked_for_next_cycle\.emit\(\s*(\w+)\s*\)")
AUD_ADD = re.compile(r"GameState\.cycles_manager\.add_audience_in_x_cycle\(\s*(\w+)\s*\)")
KL_EMIT = re.compile(r'SignalsEventBus\.trigger_dialogues_unlock_for_knight\.emit\(\s*"([^"]+)"\s*\)')
KN_FROM = re.compile(r'get_knight_from_name\(\s*"([^"]+)"\s*\)')
SET_VAR = re.compile(r'StoryController\.set_variable\(\s*"([^"]+)"\s*')
ENDING = re.compile(r"EndingManager\.Endings\.(\w+)")
IS_DEAD = re.compile(r"\.is_dead\s*=\s*true")

EXT_RESOURCE = re.compile(r'\[ext_resource[^\]]*path="([^"]+)"[^\]]*id="(\d+)"\]')
SCENE_PROP = re.compile(r'(\w+)\s*=\s*(ExtResource\("(\d+)"\)|&"([^"]+)")')

# firing-condition decoders: each `if ...:` guard line inside an instruction's
# case body is turned into a human-readable "how to proc" note. Patterns are
# keyed to the known guard forms in special_instruction_manager.gd.
COND_PATTERNS = [
    (re.compile(r"ursule\s+in\s+\S*roundtable_knights"),
     "only fires when Ursule is at the roundtable"),
    (re.compile(r"tarcus\s+in\s+\S*roundtable_knights\s+and\s+tarcus\.is_available"),
     "only fires when Tarcus is at the roundtable and available"),
    (re.compile(r"epicrate_available\s*:"),
     "only fires when Epicrate is available (recruited, alive, not busy, no Epicrate/Marian audience in the current or next cycle)"),
    (re.compile(r"get_servant_from_name\(\"rupin\"\)\s+in\s+\S*recruited_servants"),
     "only fires while Rupin has not been recruited"),
    (re.compile(r"current_ending\s*==\s*EndingManager\.Endings\.TOWER_DESTRUCTION"),
     "only fires on the Tower-Destruction ending path"),
    (re.compile(r"not\s+is_instance_valid\(traitor\.assigned_quest\)"),
     "only fires when the traitor still has an assigned quest"),
    (re.compile(r"traitor\.assigned_quest\.duration\s*<=\s*0"),
     "only fires while the traitor's quest still has time left"),
]


def _decode_conditions(body):
    """Turn the `if`-guard lines of an instruction body into condition notes.

    A guard may span continuation lines (a line ending in `\\` continues the
    condition on the next line), so the full guard expression is re-joined
    before matching.
    """
    conds = []
    guard = ""
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("if "):
            guard = stripped[3:].rstrip()
        elif guard:
            guard = guard + " " + stripped.rstrip()
        if guard and not guard.endswith("\\"):
            full = guard
            guard = ""
            for rx, note in COND_PATTERNS:
                if rx.search(full):
                    if note not in conds:
                        conds.append(note)
    return conds


def load_special_instructions():
    """Parse special_instruction_manager.gd's match table -> {NAME: effect dict}.

    Returns {NAME: {signal, dlgs, gotos, aud_next, aud_add, kls, knfs, vars,
    endings, killed, cond, body}} where the first signal names the SignalsEventBus
    signal emitted by the case, `cond` lists the decoded `if`-guard firing
    conditions, and the rest are the raw tokens/patterns that build_special
    turns into cross-links.
    """
    path = f"{GAME}/systems/autoloads/special_instruction_manager.gd"
    if not os.path.exists(path):
        return {}
    out = {}
    cur = None
    body = []
    for line in open(path, encoding="utf-8"):
        m = INSTRUCTION_CASE.match(line)
        if m:
            if cur is not None:
                out[cur] = {"body": "\n".join(body)}
            cur = m.group(1).upper()
            body = []
            continue
        if cur is not None:
            body.append(line.rstrip("\n"))
    if cur is not None:
        out[cur] = {"body": "\n".join(body)}
    for name, info in out.items():
        b = info["body"]
        sm = SIGNAL_EMIT.search(b)
        info["signal"] = sm.group(1) if sm else ""
        info["dlgs"] = DLG_EMIT.findall(b)
        info["gotos"] = GOTO_CALL.findall(b)
        info["aud_next"] = AUD_NEXT.findall(b)
        info["aud_add"] = AUD_ADD.findall(b)
        info["kls"] = KL_EMIT.findall(b)
        info["knfs"] = KN_FROM.findall(b)
        info["vars"] = SET_VAR.findall(b)
        info["endings"] = ENDING.findall(b)
        info["killed"] = bool(IS_DEAD.search(b))
        info["cond"] = _decode_conditions(b)
    return out


def load_manager_exports():
    """Resolve SpecialInstructionManager's exported vars via story_controller.tscn.

    The manager .gd references plain @export vars (follow_up_if_ursule_present,
    southbay_divert_if_tarcus_present, rupin_apologies, epicrate_first_*, ...);
    their actual values live on the SpecialInstructionManager node of the scene.
    Returns {var: {"kind": "knot|aud|knight", "value": name-or-stem}}.
    """
    path = f"{GAME}/systems/autoloads/story_controller.tscn"
    if not os.path.exists(path):
        return {}
    ext = {}
    props = {}
    node = False
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        m = EXT_RESOURCE.match(line)
        if m:
            ext[m.group(2)] = m.group(1)
            continue
        if line.startswith('[node name="SpecialInstructionManager"'):
            node = True
            continue
        if node:
            if line.startswith("["):
                break
            m = SCENE_PROP.match(line)
            if m:
                props[m.group(1)] = m.group(2)
    out = {}
    for var, val in props.items():
        m = re.match(r'&"([^"]+)"', val)
        if m:
            out[var] = {"kind": "knot", "value": m.group(1)}
            continue
        m = re.match(r'ExtResource\("(\d+)"\)', val)
        if m:
            p = ext.get(m.group(1), "")
            stem = os.path.splitext(os.path.basename(p))[0]
            if "/content/audiences/" in p:
                out[var] = {"kind": "aud", "value": stem}
            elif "character_descriptors/knights/" in p:
                out[var] = {"kind": "knight", "value": stem}
    return out


# signal handlers in character_special_instructions_manager.gd that schedule
# audiences as a side effect of a special-instruction-emitted signal
CHAR_AUD_FN = re.compile(r'^func (\w+)\(')
CHAR_AUD_ADD = re.compile(r'GameState\.cycles_manager\.add_audience_in_x_cycle\(\s*(\w+)\s*(?:,\s*(\d+))?\s*\)')
CHAR_AUD_NEXT = re.compile(r'SignalsEventBus\.audience_unlocked_for_next_cycle\.emit\(\s*(\w+)\s*\)')


def load_char_aud_schedules():
    """Decode character_special_instructions_manager.gd signal handlers.

    The character manager connects SpecialInstruction signals (gwendan_reformed,
    arron_set_violent, ...) to audience scheduling as a side effect
    (`add_audience_in_x_cycle` — e.g. GWENDAN_REFORMED schedules
    gwendan_humble_candidacy in ~5 cycles), plus a few cycle-transition checks.

    Returns {export_var: {"signal": <handler signal>, "aud": <stem>, "delay": n}}
    for each handler body that schedules an audience, resolved through the
    CharacterSpecialInstructionsManager node exports in character_manager.tscn.
    """
    gd = f"{GAME}/systems/autoloads/character_special_instructions_manager.gd"
    tscn = f"{GAME}/systems/autoloads/character_manager.tscn"
    if not os.path.exists(gd) or not os.path.exists(tscn):
        return {}

    # exports on the CharacterSpecialInstructionsManager node
    ext = {}
    props = {}
    node = False
    for raw in open(tscn, encoding="utf-8"):
        line = raw.strip()
        m = EXT_RESOURCE.match(line)
        if m:
            ext[m.group(2)] = m.group(1)
            continue
        if line.startswith('[node name="CharacterSpecialInstructionsManager"'):
            node = True
            continue
        if node:
            if line.startswith("["):
                break
            m = SCENE_PROP.match(line)
            if m:
                props[m.group(1)] = m.group(2)
    aud_vars = {}
    for var, val in props.items():
        m = re.match(r'ExtResource\("(\d+)"\)', val)
        if not m:
            continue
        p = ext.get(m.group(1), "")
        if "/content/audiences/" in p:
            aud_vars[var] = os.path.splitext(os.path.basename(p))[0]

    # signal name (with_continue_story etc. functions excluded) per function
    fn_map = {}
    cur = None
    body = []
    for line in open(gd, encoding="utf-8"):
        m = CHAR_AUD_FN.match(line)
        if m:
            if cur is not None:
                fn_map[cur] = "\n".join(body)
            cur = m.group(1)
            body = []
            continue
        if cur is not None:
            body.append(line.rstrip("\n"))
    if cur is not None:
        fn_map[cur] = "\n".join(body)

    fn_signals = {}
    ready_body = fn_map.get("_ready", "")
    for mm in re.finditer(r"SignalsEventBus\.(\w+)\.connect\(\s*(_\w+)\s*\)", ready_body):
        fn_signals[mm.group(2)] = mm.group(1)

    out = {}
    for fn, b in fn_map.items():
        signal = fn_signals.get(fn)
        if not signal or not fn.startswith("_on_"):
            continue
        for mm in CHAR_AUD_ADD.finditer(b):
            var = mm.group(1)
            if var in aud_vars:
                out.setdefault(var, []).append({
                    "signal": signal,
                    "aud": aud_vars[var],
                    "delay": int(mm.group(2) or 1),
                })
        for mm in CHAR_AUD_NEXT.finditer(b):
            var = mm.group(1)
            if var in aud_vars:
                out.setdefault(var, []).append({
                    "signal": signal,
                    "aud": aud_vars[var],
                    "delay": 1,
                })
    return out


def _humanize(signal):
    words = [w for w in re.split(r"[_ ]+", signal) if w and w not in ("set", "triggered")]
    return " ".join(w[:1].upper() + w[1:] for w in words) if words else signal


def _effect_note(name, signal, dlg, goto, auds, affects, vars_written, endings,
                 body, killed, kls):
    """Human summary of what the instruction does, from its parsed effects."""
    parts = []
    if killed:
        who = " ".join(a.title() for a in affects)
        parts.append("Marks %s dead" % who)
    if dlg:
        parts.append("Unlocks special dialogue%s" % (" (%s)" % ", ".join(sorted(dlg))))
    if kls:
        parts.append("Unlocks dialogues for %s" % ", ".join(sorted(k.title() for k in kls)))
    if goto:
        parts.append("Diverts to %s" % ", ".join(sorted(goto)))
    if auds:
        parts.append("Schedules audience(s): %s" % ", ".join(sorted(auds)))
    if endings:
        parts.append("Switches to the %s ending path" % endings[0])
    if vars_written:
        parts.append("Sets story vars %s" % ", ".join(vars_written))
    if parts:
        return "; ".join(parts)
    return ""


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
    instr_source = load_special_instructions()
    exports = load_manager_exports()
    char_auds = load_char_aud_schedules()
    all_knots = set(index.get("knots") or {}) if index else set()

    def _affect_char(name):
        return name.strip().lower()

    def _resolve_dlg_knot(char, key):
        """unlock_special_dialogue(char, key) -> the ink knot it unlocks, via the
        owning knight's specd map (gideon_victoria_dead -> gideon_victoria_dead_reaction)."""
        stem = _affect_char(char)
        k = (knights_data or {}).get("knights", {}).get(stem)
        if k:
            knot = (k.get("specd") or {}).get(key)
            if knot in all_knots:
                return knot
        return key if key in all_knots else None

    def _resolve_export(var, kind):
        e = exports.get(var)
        if e and e["kind"] == kind:
            return e["value"]
        return None

    # union of every instruction name we know about (manager + ink + quests)
    names = set(instr_source) | set(knot_map) | set(quest_map) | set(evo_notes)
    instructions = {}
    for name in sorted(names):
        info = instr_source.get(name) or {}
        signal = info.get("signal") or ""
        body = info.get("body") or ""

        dlg = []
        goto = []
        auds = []
        affects = []
        for char, key in info.get("dlgs") or []:
            knot = _resolve_dlg_knot(char, key)
            if knot:
                dlg.append(knot)
            affects.append(_affect_char(char))
        for var in info.get("gotos") or []:
            knot = _resolve_export(var, "knot")
            if knot and knot in all_knots:
                goto.append(knot)
        for var in info.get("aud_next") or info.get("aud_add") or []:
            stem = _resolve_export(var, "aud")
            if stem:
                auds.append(stem)
        # character-special-instructions scheduling: signals the instruction
        # emits also schedule an audience as a side effect (e.g. GWENDAN_REFORMED
        # schedules gwendan_humble_candidacy in ~5 cycles via
        # character_special_instructions_manager.gd)
        char_sched = []
        if signal:
            for entries in char_auds.values():
                for e in entries:
                    if e["signal"] == signal and e["aud"] not in auds:
                        auds.append(e["aud"])
                        d = e["delay"]
                        char_sched.append("%s in ~%d cycle%s" % (e["aud"], d, "s" if d != 1 else ""))
        for provoke in (info.get("kls") or []) + (info.get("knfs") or []):
            affects.append(_affect_char(provoke))
        vars_written = sorted(set(info.get("vars") or []))
        endings = info.get("endings") or []

        note = evo_notes.get(name)
        if not note and (dlg or goto or auds or affects or vars_written or endings):
            note = _effect_note(name, signal, dlg, goto, auds, affects,
                                vars_written, endings, body, bool(info.get("killed")),
                                info.get("kls") or [])
        if not note and signal:
            note = _humanize(signal)
        if char_sched:
            sched_text = "Schedules %s" % "; ".join(char_sched)
            note = (note + "; " + sched_text[0].lower() + sched_text[1:]) if note else sched_text
        if not note:
            note = ""
        inst = {}
        if signal:
            inst["signal"] = signal
        conds = info.get("cond") or []
        if conds:
            inst["cond"] = conds
        if knot_map.get(name):
            inst["knots"] = sorted(set(knot_map[name]))
        if quest_map.get(name):
            inst["quests"] = sorted(set(quest_map[name]))
        if note:
            inst["note"] = note
        if dlg:
            inst["dlg"] = sorted(set(dlg))
        if goto:
            inst["goto"] = sorted(set(goto))
        if auds:
            inst["auds"] = sorted(set(auds))
        if affects:
            inst["affects"] = sorted(set(affects))
        if vars_written:
            inst["vars"] = vars_written
        if endings:
            inst["ending"] = endings[0]
        if name in evo_notes:
            # find the owning knight for cross-linking
            for kname, kdata in (knights_data or {}).get("knights", {}).items():
                if any((e.get("trigger") or "").upper() == name for e in (kdata.get("evo") or [])):
                    inst["knight"] = kname
                    break
        instructions[name] = inst

    stats_links = sum(1 for i in instructions.values()
                      if any(i.get(f) for f in ("dlg", "goto", "auds", "affects", "vars", "ending")))
    data = {
        "instructions": instructions,
        "stats": {
            "total": len(instructions),
            "in_ink": len(knot_map),
            "in_quests": len(quest_map),
            "knights": len(evo_notes),
            "linked": stats_links,
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
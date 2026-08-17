#!/usr/bin/env python3
"""Sovereign Tower — free-time dialogue catalog extractor.

Emits `dist/dialogues.json`: the free-time dialogue catalog — the ~235
`FreeTimeDialogue` resources (affinity dialogs, knight conversations, reaction /
special dialogs) that the game plays through its tower free-time machinery
(knight/garden rooms) rather than as audiences/quests/ink diverts — with each
dialog's affinity gate, conversation partners/exclusions/pick-order and its
unlock sources (the ink `UnlockSpecialDialogue` knots + the code unlocks).
Consumed by the Dialogues tab knot drawer ("Where it comes from") and the new
"has dialogue source" filter.

Sources:
1. `content/dialogues/{affinity_dialogues,knights_conversations_dialogues,reactions}/*.tres`
   — the `FreeTimeDialogue` resources (ink_path, dialogue_location_id room).
2. `content/character_descriptors/{knights,servants}/*.tres` — the per-knight
   `affinity_dialogues` rank dicts, `special_dialogues` key→dialog maps, and the
   subclass variant dicts (arron violent/kind, dulahan body-possession, edith
   possessed, gwendan reformed/repaid, gideon known-origin insert, ursula
   affinity-4-if-dead, angelica on-death key replacement).
3. `content/knight_conversations/*.tres` + `systems/autoloads/character_manager.tscn`
   — conversation partners, dialogue resource, excluded-`<knight>_states` arrays
   and the pick-priority order of the `knight_conversations` array.
4. `dist/index.json` — the ink knots that unlock a dialog via
   `UnlockSpecialDialogue(char, key)` (flow lines + choice effects).
5. `dist/special.json` — the special-instruction signal unlocks (`dlg`).

Output shape (dist/dialogues.json):
  dialogues: { "<ink_path>": {t, loc, ch?, aff?, aff0?, conv?, unl?} }
      t     "affinity" | "conversation" | "reaction"  (resource folder)
      loc   dialogue_location_id (Room enum int)
      ch    character ink ids (dialog owner / conversation participants)
      aff   {"k": knight stem, "rank": min-affinity, "re"?: variant note} —
            the affinity-dialogue gate (rank = key of the affinity_dialogues dict)
      aff0  true for the always-first rank-0 intro dialog
      conv  {"knights": [...], "e": [["<knight>","<State>"], ...],
             "o": pick order} — knight-conversation gate
      unl   [["ink"|"code"|"item"|"special", <value>], ...] — unlock sources
  stats:   header counts
"""

import collections
import json
import os
import re
import sys
from pathlib import Path

from quest_data import TresFile, set_game

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GAME_ROOT = (SCRIPT_DIR.parent / "game" / "SovereignTowerCode").resolve()

GAME = str(DEFAULT_GAME_ROOT)

DIALOG_DIR = "content/dialogues"
CONV_DIR = "content/knight_conversations"
DESC_DIRS = ("content/character_descriptors/knights",
             "content/character_descriptors/servants")
CHAR_MANAGER_TSNC = "systems/autoloads/character_manager.tscn"

FOLDER_TYPES = {"affinity_dialogues": "affinity",
                "knights_conversations_dialogues": "conversation",
                "reactions": "reaction"}

ROOM_NAMES = [
    "Lady Tower room", "Demon room", "Audience room", "Roundtable",
    "Map room", "Intendancy", "Forge", "Stables", "Witch tower",
    "Kitchen", "Training grounds", "Inventory", "Intro room", "Garden",
    "Corridor", "Cellar", "Library",
]

# the per-knight State enums used by the conversation `excluded_<knight>_states`
# arrays (knights_conversation.gd:7-14). Parsed from the subclass .gd when
# present; this favicon/table is the documented fallback.
STATE_ENUMS = {
    "arron": ("Violent", "Kind", "WithEgg"),     # State{Unchanged, Violent, Kind, WithEgg}
    "dulahan": ("Body", "Helmet"),               # State{Unchanged, Body, Helmet}
    "edith": ("Possessed",),                     # State{Unchanged, Possessed}
    "gwendan": ("Reformed", "Repaid"),           # State{Unchanged, Reformed, Repaid}
}

# code / item unlock sources for the special_dialogues keys that have no ink
# call site (report §3.3b) — each maps [type, note]; appended to the dialog's
# `unl` when the owning character declares that key.
CODE_UNLOCKS = {
    "romance_completed": ("code", "romance completed (romantism maxed)"),
    "romance_completed_reformed": ("code", "romance completed as reformed humble gwendan"),
    "full_romance": ("code", "romance completed (romantism maxed)"),
    "death_reaction": ("code", "a knight death — Angelica's grief reaction"),
    "golden_key": ("code", "cycle ≥ 34 with no dead knight — Angelica's golden-key reaction"),
    "get_the_egg": ("item", "DRAGON_EGG quest item"),
    "get_the_dragon_heart": ("item", "DRAGON_HEART quest item"),
    "dulahan_helmet": ("item", "CURSED_HELMET quest item"),
}

# affinity-dialog subclass variant notes (which game state the dialog keys off)
AFF_VARIANT_NOTE = {
    "violent_dialogues": "while Arron is violent (dragonheart state)",
    "kind_dialogues": "while Arron is kind (with-egg state)",
    "body_possession_dialogues": "while Dulahan is body-possessed",
    "possessed_affinity_dialogues": "while Edith is demon-possessed",
    "reformed_new_dialogues": "while Gwendan is reformed/humbled",
    "unreformed_new_dialogues": "after Gwendan repays her debt (unreformed)",
    "post_stables_open_affinity_dialogues": "once the stables room is unlocked",
}

# single-resource affinity-dialog fields: {field: (index field, note)} — the
# knight's script merges the dialog into affinity_dialogues at the index once
# the given room gate is met (rufus post-stables handled above).
SINGLE_AFF_DIALOGS = {
    "victoria": ("sagadin_affinity_dialogue", "sagadin_affinity_dialogue_index",
                 "once the witch tower is unlocked"),
    "the_wolf": ("witch_affinity_dialogue", "witch_affinity_dialogue_index",
                 "once the witch tower is unlocked"),
}

# gwendan intercepts unlock_dialogue (gwendan.gd:124-131): an ink "marriage" /
# "romance_completed" call resolves to the humble variants when reformed and to
# the pretentious / annoying variants when not — both reactions fire from the
# same ink site, so the call also unlocks the alias key.
KEY_INTERCEPTS = {
    ("Gwendan", "romance_completed"): ("romance_completed_reformed",),
    ("Gwendan", "marriage"): ("mariage_annoyoing",),
}

# conversation state-exclusion note template: "not offered while <knight> is <State>"
CONV_EXCL_STATES = frozenset(STATE_ENUMS)


def set_dialogue_root(root):
    """Point this module's GAME at a given game root (see build_app)."""
    global GAME
    GAME = str(Path(root).expanduser().resolve())


def _speaker_for(ink_id):
    """Camel-case an ink id the way the game's dialogues do -> "lady_tower" -> "Lady_Tower"."""
    return "_".join(p[:1].upper() + p[1:] for p in str(ink_id).split("_") if p)


def _ink_path(tf):
    """Resolve a FreeTimeDialogue's ink_path prop (may be `&"name"`) -> str or None."""
    ink = tf.props.get("ink_path")
    if isinstance(ink, dict):
        return None
    if ink is None:
        return None
    s = str(ink).strip()
    if s.startswith("&"):
        s = s[1:]
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        s = s[1:-1]
    return s.strip() or None


def _ext_stem(tf, ref):
    """Ext-resource basename (stem) for a {_ext: id} ref, or None."""
    if not isinstance(ref, dict) or "_ext" not in ref:
        return None
    path = tf.ext.get(ref["_ext"])
    if not path:
        return None
    return os.path.splitext(os.path.basename(path))[0]


def _state_enum(stem):
    """State names (index 0 = Unchanged) for a knight, parsed from its script."""
    gd = f"{GAME}/systems/resources/characters/{stem}.gd"
    if os.path.exists(gd):
        try:
            text = open(gd, encoding="utf-8").read()
            m = re.search(r"enum\s+State\s*\{(.*?)\}", text, re.S)
            if m:
                names = [p.strip() for p in m.group(1).split(",") if p.strip()]
                if names:
                    return names
        except OSError:
            pass
    return list(STATE_ENUMS.get(stem, ()))


def decode_dict(tf, value):
    """Godot Dictionary (parsed to [{key, value}...]) -> {k: parsed value}."""
    out = {}
    if not isinstance(value, list):
        return out
    for entry in value:
        if not isinstance(entry, dict):
            continue
        k = entry.get("key")
        k = str(k).lstrip("&").strip('"') if isinstance(k, str) else k
        out[k] = entry.get("value")
    return out


def _resolve_dlg_ink(tf, ref):
    """Resolve a FreeTimeDialogue ext reference -> its ink knot (or None)."""
    pid = ref.get("_ext") if isinstance(ref, dict) else None
    if not pid:
        return None
    p = tf.ext.get(pid)
    if not p:
        return None
    if p.startswith("res://"):
        p = p[6:]
    path = f"{GAME}/{p}"
    if not os.path.exists(path):
        return None
    dtf = TresFile.load(path, os.path.dirname(path))
    return _ink_path(dtf)


def _room_id(tf):
    """FreeTimeDialogue.dialogue_location_id (Room enum int), None when unset."""
    v = tf.props.get("dialogue_location_id")
    if isinstance(v, int):
        return v
    return None


def load_dialog_resources():
    """Parse the 3 dialogue folders -> {ink_path: {t, loc}}.

    One entry per FreeTimeDialogue resource (an inline sub-resource, e.g. the
    `candidature_alwena` dialog inside the alwena_recruitment conversation, is
    added by load_conversations instead — it has no file of its own).
    """
    out = {}
    for folder, label in FOLDER_TYPES.items():
        d = f"{GAME}/{DIALOG_DIR}/{folder}"
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".tres"):
                continue
            tf = TresFile.load(os.path.join(d, fn), d)
            ink = _ink_path(tf)
            if not ink:
                continue
            loc = _room_id(tf)
            out[ink] = {"t": label}
            if loc is not None:
                out[ink]["loc"] = loc
    return out


def load_conversations():
    """Parse the 77 knight_conversations + the character_manager pick order.

    Returns ({ink_path: {knights, e, o?}}, {ink_path: {t, loc}}) where the second
    dict holds the conversation-tagged catalog entries (dialogues with no own
    file, i.e. the inline `candidature_alwena`, get a fresh entry here).
    """
    d = f"{GAME}/{CONV_DIR}"
    convs = {}
    extra = {}
    if not os.path.isdir(d):
        return convs, extra
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".tres"):
            continue
        tf = TresFile.load(os.path.join(d, fn), d)
        P = tf.props
        knights = []
        for ref in P.get("knights", []) or []:
            s = _ext_stem(tf, ref)
            if s:
                knights.append(s)
        if not knights:
            continue
        ink = None
        dref = P.get("dialogue")
        if isinstance(dref, dict):
            if "_ext" in dref:
                ink = _resolve_dlg_ink(tf, dref)
                loc = None
            else:
                # inline FreeTimeDialogue sub-resource (alwena_recruitment)
                props = tf.sub_props(dref["_sub"])
                ink = _ink_path_s(props)
                loc = props.get("dialogue_location_id")
                if isinstance(loc, int) and ink:
                    extra[ink] = {"t": "conversation", "loc": loc}
        elif isinstance(dref, str):
            # raw path string fallback
            p = dref if dref.startswith("res://") else None
            if p:
                pp = p[6:]
                path = f"{GAME}/{pp}"
                if os.path.exists(path):
                    dtf = TresFile.load(path, os.path.dirname(path))
                    ink = _ink_path(dtf)
        if not ink:
            continue
        entry = {"knights": knights, "t": "conversation"}
        excl = []
        for k, v in P.items():
            if k.startswith("excluded_") and k.endswith("_states"):
                knight = k[len("excluded_"):-len("_states")]
                names = _state_enum(knight)
                for val in v or []:
                    nm = names[val] if isinstance(val, int) and 0 <= val < len(names) else str(val)
                    excl.append([knight, nm])
        if excl:
            entry["e"] = excl
        convs[ink] = entry
    order = _conversation_order()
    if order:
        for i, stem in enumerate(order):
            tf = TresFile.load(f"{d}/{stem}.tres", d)
            dref = tf.props.get("dialogue")
            ink = _resolve_dlg_ink(tf, dref) if isinstance(dref, dict) and "_ext" in dref else None
            if ink and ink in convs:
                convs[ink]["o"] = i
    return convs, extra


def _ink_path_s(props):
    """_ink_path for an already-parsed props dict (inline sub-resource)."""
    ink = props.get("ink_path")
    if ink is None or isinstance(ink, dict):
        return None
    s = str(ink).strip()
    if s.startswith("&"):
        s = s[1:]
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        s = s[1:-1]
    return s.strip() or None


def _conversation_order():
    """index within the character_manager.tscn `knight_conversations` array.

    The pick priority (character_manager.gd:100 pick_knight_conversation iterates
    the exported array in order; first eligible wins). Returns {stem: order}.
    """
    path = f"{GAME}/{CHAR_MANAGER_TSNC}"
    if not os.path.exists(path):
        return {}
    ext = {}
    order = []
    node = False
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        m = re.match(r'\[ext_resource[^\]]*path="([^"]+)"[^\]]*id="(\d+)"\]', line)
        if m:
            ext[m.group(2)] = m.group(1)
            continue
        if line.startswith('[node name="CharacterManager"'):
            node = True
            continue
        if node:
            if line.startswith("["):
                break
            m = re.match(r"knight_conversations\s*=\s*\[(.*)\]$", line)
            if m:
                for ref in re.findall(r'ExtResource\("(\d+)"\)', m.group(1)):
                    p = ext.get(ref, "")
                    if "/content/knight_conversations/" in p:
                        order.append(os.path.splitext(os.path.basename(p))[0])
    return {stem: i for i, stem in enumerate(order) if stem}


def load_descriptors():
    """Parse the knight+servant descriptors -> the dialog ownership maps.

    Returns (specd_by_ink, aff_map, owner) where:
      specd_by_ink  {camel-case ink speaker: {special key: ink knot}}
      aff_map       {ink knot: {"k": stem, "rank": int, "re"?: note, "aff0": bool}}
      owner         {ink knot: [char ink ids...]} (special_dialogues ownership)
    """
    specd_by_ink = {}
    aff_map = {}
    owner = collections.defaultdict(list)
    for desc_dir in DESC_DIRS:
        d = f"{GAME}/{desc_dir}"
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".tres"):
                continue
            stem = os.path.splitext(fn)[0]
            tf = TresFile.load(os.path.join(d, fn), d)
            P = tf.props
            ink_id = str(P.get("character_ink_id") or stem).lstrip("&").strip('"')
            speaker = _speaker_for(ink_id)
            # special_dialogues: key -> dialog knot (reaction / romance dialogs)
            specd = {}
            for key, ref in decode_dict(tf, P.get("special_dialogues")).items():
                knot = _resolve_dlg_ink(tf, ref)
                if knot:
                    specd[str(key)] = knot
                    owner[knot].append(stem)
            if specd:
                specd_by_ink[speaker] = specd
            # affinity_dialogues rank dict -> gate; the subclass variant dicts
            # add their own keys. Same dialog listed twice (edith base+possessed)
            # keeps its first (lowest-rank) gate.
            for field in ("affinity_dialogues", "violent_dialogues", "kind_dialogues",
                          "body_possession_dialogues", "possessed_affinity_dialogues",
                          "reformed_new_dialogues", "unreformed_new_dialogues",
                          "post_stables_open_affinity_dialogues"):
                note = AFF_VARIANT_NOTE.get(field)
                for rank, ref in decode_dict(tf, P.get(field)).items():
                    knot = _resolve_dlg_ink(tf, ref)
                    if not knot:
                        continue
                    gate = {"k": stem, "rank": int(rank)}
                    if note:
                        gate["re"] = note
                    if (isinstance(rank, int) and rank == 0
                            and field == "affinity_dialogues"):
                        gate["aff0"] = True
                    if knot not in aff_map:
                        aff_map[knot] = gate
            # gideon: the known-origin dialog is inserted at affinity_rank_for_origin
            # (5, or 6 when 5 is already taken) once gideon_origins_known is true
            if stem == "gideon":
                rank = P.get("affinity_rank_for_origin", 5)
                ref = P.get("affinity_dialogue_known_origin")
                knot = _resolve_dlg_ink(tf, ref) if isinstance(ref, dict) else None
                if knot and knot not in aff_map:
                    used = set()
                    for r, rref in decode_dict(tf, P.get("affinity_dialogues")).items():
                        if _resolve_dlg_ink(tf, rref) == knot:
                            used.add(int(r))
                    while rank in used:
                        rank += 1
                    aff_map[knot] = {
                        "k": "gideon", "rank": rank,
                        "re": "while the story var gideon_origins_known is set",
                        "aff0": False,
                    }
            # ursule: affinity_4_if_dead plays at affinity ≥ 9 with any corruption
            if stem == "ursule":
                ref = P.get("affinity_4_if_dead")
                knot = _resolve_dlg_ink(tf, ref) if isinstance(ref, dict) else None
                if knot and knot not in aff_map:
                    aff_map[knot] = {
                        "k": "ursule", "rank": 9,
                        "re": "affinity ≥ 9 with any corruption level (re-fires promotion gimmicks)",
                        "aff0": False,
                    }
            # angelica: on a knight death her affinity-4 dialog replaces key at
            # affinity_dialogue_on_death_affinity_threshold
            if stem == "angelica":
                ref = P.get("affinity_dialogue_on_death")
                knot = _resolve_dlg_ink(tf, ref) if isinstance(ref, dict) else None
                thr = P.get("affinity_dialogue_on_death_affinity_threshold", 8)
                if knot and knot not in aff_map:
                    aff_map[knot] = {
                        "k": "angelica", "rank": int(thr),
                        "re": "after a knight dies (replaces key %s)" % thr,
                        "aff0": False,
                    }
            # room-gated single affinity dialogs (victoria + the wolf): merged
            # at the exported index once the witch tower is unlocked
            if stem in SINGLE_AFF_DIALOGS:
                field, idx_field, note = SINGLE_AFF_DIALOGS[stem]
                ref = P.get(field)
                knot = _resolve_dlg_ink(tf, ref) if isinstance(ref, dict) else None
                idx = P.get(idx_field, 5)
                if knot and knot not in aff_map:
                    aff_map[knot] = {"k": stem, "rank": int(idx),
                                     "re": note, "aff0": False}
    return specd_by_ink, aff_map, dict(owner)


def load_code_unlocks(specd_by_ink):
    """{ink knot: [[type, value], ...]} from the code/unlock-table (§3.3b).

    The bulk of the reactions are unlocked by ink (`UnlockSpecialDialogue`);
    the code unlocks are the romance-completed dialogs, Angelica's death/golden-key
    reactions, Arron's dragon-heart/egg reactions and Dulahan's cursed-helmet
    reaction. Each is attached to the dialog the owning character declares.
    """
    out = collections.defaultdict(list)
    for speaker, specd in specd_by_ink.items():
        for key, knot in specd.items():
            if key in CODE_UNLOCKS:
                typ, note = CODE_UNLOCKS[key]
                if key == "death_reaction":
                    note = ("a knight dies — Angelica's grief reaction "
                            "(also merges her on-death affinity dialog at the "
                            "descriptor threshold key)")
                out[knot].append([typ, note])
    return {k: sorted(set(map(tuple, v))) for k, v in out.items()}


def load_ink_unlocks(index, specd_by_ink):
    """{ink knot: [[ink, <unlocker knot>], ...]} from index.json.

    Every `UnlockSpecialDialogue(char, key)` call site (flow lines + choice
    effects) resolves (char, key) to the dialog knot via the descriptors'
    special_dialogues maps. Returns both the per-dialog list and the totals.
    """
    out = collections.defaultdict(list)
    resolved = 0
    for name, k in (index or {}).get("knots", {}).items():
        sites = []
        for t in k.get("lines", []):
            if not isinstance(t, list) or not t:
                continue
            if t[0] == "3" and t[1] == "UnlockSpecialDialogue" and isinstance(t[2], list):
                sites.append(t[2])
            elif t[0] == "2" and isinstance(t[5], list):
                for e in t[5]:
                    if (isinstance(e, list) and e and e[0] == "UnlockSpecialDialogue"
                            and isinstance(e[1], list)):
                        sites.append(e[1])
        for args in sites:
            if len(args) < 2:
                continue
            char, key = str(args[0]), str(args[1])
            specd = specd_by_ink.get(char) or {}
            knot = specd.get(key)
            targets = {key}
            if (char, key) in KEY_INTERCEPTS:
                targets.update(KEY_INTERCEPTS[(char, key)])
            for tkey_ in targets:
                tknot = specd.get(tkey_)
                if tknot:
                    out[tknot].append(name)
                    resolved += 1
    return {k: sorted(set(v)) for k, v in out.items() if v}, resolved


def load_special_unlocks(special):
    """{ink knot: [special-instruction names]} for the `dlg` reactions (special.json)."""
    out = collections.defaultdict(list)
    for name, inst in (special or {}).get("instructions", {}).items():
        for knot in inst.get("dlg", []) or []:
            out[knot].append(name)
    return {k: sorted(set(v)) for k, v in out.items() if v}


def build_dialogues(out_dir, quests_data=None, index=None, knights_data=None,
                    special=None, game_root=None):
    """Write dist/dialogues.json and return the data dict."""
    del knights_data  # reserved for future Knight-tab cross-links (Task J §8.4)
    if game_root is not None:
        set_dialogue_root(game_root)
    set_game(game_root if game_root is not None else GAME)

    catalog = load_dialog_resources()
    convs, extra = load_conversations()
    catalog.update(extra)
    specd_by_ink, aff_map, owner = load_descriptors()
    code_unl = load_code_unlocks(specd_by_ink)
    ink_unl, ink_total = load_ink_unlocks(index, specd_by_ink)
    sp_unl = load_special_unlocks(special)

    dialogues = {}
    for ink in sorted(catalog):
        entry = dict(catalog[ink])
        conv = convs.get(ink)
        if conv:
            entry["conv"] = {k: v for k, v in conv.items()
                             if k not in ("t", "loc")}
        gate = aff_map.get(ink)
        if gate:
            entry["aff"] = {kk: vv for kk, vv in gate.items() if kk != "aff0"}
            entry["aff0"] = gate.get("aff0", False)
        ch = []
        for c in owner.get(ink, []):
            if c not in ch:
                ch.append(c)
        if gate and gate["k"] not in ch:
            ch.insert(0, gate["k"])
        if conv and conv.get("knights"):
            # conversation participants are descriptor stems (kName resolves them)
            for stem in conv["knights"]:
                if stem and stem not in ch:
                    ch.append(stem)
        if ch:
            entry["ch"] = ch
        unl = []
        for typ, val in code_unl.get(ink, []):
            if [typ, val] not in unl:
                unl.append([typ, val])
        for knot in ink_unl.get(ink, []):
            if ["ink", knot] not in unl:
                unl.append(["ink", knot])
        for name in sp_unl.get(ink, []):
            if ["special", name] not in unl:
                unl.append(["special", name])
        # the rank-0 intro dialog also counts as a self-evident gate: no source
        if unl:
            entry["unl"] = unl
        dialogues[ink] = entry

    stats = {
        "affinity": sum(1 for e in dialogues.values() if e.get("t") == "affinity")
        + sum(1 for e in extra.values() if e.get("t") == "affinity"),
        "conversation": sum(1 for e in dialogues.values() if e.get("t") == "conversation"),
        "reaction": sum(1 for e in dialogues.values() if e.get("t") == "reaction"),
        "with_unl": sum(1 for e in dialogues.values() if e.get("unl")),
        "ink_unl": sum(1 for e in dialogues.values()
                       if any(u[0] == "ink" for u in e.get("unl", []))),
        "with_affinity_gate": sum(1 for e in dialogues.values() if e.get("aff")),
        "all": len(dialogues),
    }
    data = {"dialogues": dialogues, "stats": stats}
    out_path = Path(out_dir) / "dialogues.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Dialogues: {stats['all']} free-time dialogs · "
          f"{stats['affinity']} affinity · {stats['conversation']} conversations · "
          f"{stats['reaction']} reactions · {stats['with_unl']} with unlock sources "
          f"({ink_total} ink UnlockSpecialDialogue sites resolved)")
    return data


def main(argv=None):
    args = list(sys.argv[1:]) if argv is None else list(argv)
    game_root = args[0] if len(args) > 0 else ""
    out_dir = args[1] if len(args) > 1 else ""
    game_root = str(Path(game_root).expanduser().resolve()) if game_root else DEFAULT_GAME_ROOT
    set_dialogue_root(game_root)
    out_dir = Path(out_dir).expanduser().resolve() if out_dir else (SCRIPT_DIR / "dist")

    def _load(name):
        p = out_dir / name
        return json.load(open(p, encoding="utf-8")) if p.exists() else None

    build_dialogues(out_dir,
                    quests_data=_load("quests.json"),
                    index=_load("index.json"),
                    knights_data=_load("knights.json"),
                    special=_load("special.json"),
                    game_root=game_root)


if __name__ == "__main__":
    main()
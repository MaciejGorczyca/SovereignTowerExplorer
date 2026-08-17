#!/usr/bin/env python3
"""Sovereign Tower — ending cutscene & vignette catalog extractor.

Emits `dist/endings.json`: the game-end context for the `ending`-category ink
knots. The ~40 ending knots show no "Where it comes from" data because they are
NEITHER audiences/quests/diverts NOR free-time dialogues — they are the ending
*cutscenes* (the type-driven main cutscene + the corruption-gated demon-state
epilogue), the 31 per-character **vignettes** the ServantEndingCutscene plays
in sequence at game end, and the two code-played special knots. Consumed by the
Dialogues knot drawer ("Where it comes from") as "Ending vignette of <x>" /
"Ending cutscene (<type>)" rows.

Sources:
1. `systems/autoloads/act_manager.tscn` — the EndingManager node's
   `endings_cutscenes_paths` dict (ending-type index → cutscene knot),
   index-aligned with the `Endings` enum in `systems/autoloads/ending_manager.gd`.
2. `systems/autoloads/special_instruction_manager.gd` — the `SWITCH_ENDING_*_PATH`
   special instructions that switch the ending type (they are named
   `SWITCH_ENDING_<TYPE>_PATH` by construction; DEMON_STATE has no switch).
3. `content/character_descriptors/{knights,servants}/*.tres` — each character's
   `ending_path` (shared descriptor parser in `dialogue_data.load_ending_paths`),
   routed by character ink id into the `vignettes` map.
4. Hand-verified code sites: the `HILDEGARD_SONG` special instruction plays
   `hildegard_singing_ending` (signals_event_bus.gd:200 → cinematic_skip_overlay.gd:3),
   and the demon-room scene (scenes/rooms/dialogue_rooms/demon_ending_dialogue.gd:15)
   plays `demon_back_in_time_ending_proposal` — both noted in `specials`.

Output shape (dist/endings.json):
  types:     { "<TYPE>": {"cut": <knot>, "switch"?: <SWITCH_ENDING_*_PATH>, "note"?: ...} }
             the six ending types: WAR / PEACE_TREATY / MARRY / SURRENDER /
             TOWER_DESTRUCTION each carry their switching special instruction;
             DEMON_STATE carries a `note` (the corruption-gated epilogue).
  vignettes: { "<character_ink_id>": "<ending_knot>", ... } — the per-character
             vignette played at game end while the character is alive and at the
             roundtable (recruited, for servants).
  specials:  { "<ending_knot>": "<play-source note>", ... } — ending knots played
             by code outside the ServantEndingCutscene.
"""

import json
import os
import sys
from pathlib import Path

from quest_data import set_game
from quest_data import load_gd_enum, TresFile
from dialogue_data import load_ending_paths, set_dialogue_root

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GAME_ROOT = (SCRIPT_DIR.parent / "game" / "SovereignTowerCode").resolve()

GAME = str(DEFAULT_GAME_ROOT)

ACT_MANAGER_TSNC = "systems/autoloads/act_manager.tscn"
SPECIAL_MANAGER_GD = "systems/autoloads/special_instruction_manager.gd"

# the two ending knots played by code outside the ServantEndingCutscene (knot-
# source research §1.4): Hildegard's song via the HILDEGARD_SONG special
# instruction, and the demon-room back-in-time proposal via the demon-ending
# dialogue scene that plays after the credits.
ENDING_SPECIALS = {
    "hildegard_singing_ending": (
        "the HILDEGARD_SONG special instruction — Hildegard's ending song"),
    "demon_back_in_time_ending_proposal": (
        "the demon room scene — the back-in-time proposal after the credits"),
}

# the DEMON_STATE ending has no SWITCH_ENDING_*_PATH: it is the corruption-gated
# epilogue that plays after the main ending when corruption > 0 (kept as a note
# on the types entry, ending_manager.gd:53).
DEMON_STATE_NOTE = "plays after the main ending while the demon corruption is > 0"


def set_ending_root(root):
    """Point this module (and the shared dialogue_data / quest_data parsers)
    at a given game root (see build_app)."""
    global GAME
    GAME = str(Path(root).expanduser().resolve())
    set_dialogue_root(GAME)
    set_game(GAME)


def load_ending_types():
    """{type name: {"cut": knot, "switch"?: name, "note"?: ...}}.

    The five switcheable types (WAR / PEACE_TREATY / MARRY / SURRENDER /
    TOWER_DESTRUCTION) map onto the EndingManager `endings_cutscenes_paths`
    dict (act_manager.tscn) via the `Endings` enum order (ending_manager.gd)
    and carry the `SWITCH_ENDING_*_PATH` special-instruction name; DEMON_STATE
    carries a `note` instead of a switch.
    """
    enums = load_gd_enum("Endings") or []
    tf = TresFile.load(f"{GAME}/{ACT_MANAGER_TSNC}", os.path.dirname(f"{GAME}/{ACT_MANAGER_TSNC}"))
    cuts = {}
    for entry in tf.props.get("endings_cutscenes_paths") or []:
        if isinstance(entry, dict):
            cuts[entry.get("key")] = entry.get("value")
    types = {}
    for name, val in enums:
        cut = cuts.get(val)
        if not isinstance(cut, str) or not cut:
            continue
        entry = {"cut": cut}
        if name == "DEMON_STATE":
            entry["note"] = DEMON_STATE_NOTE
        else:
            # the special-instruction switches are named
            # `SWITCH_ENDING_<TYPE>_PATH` (special_instruction_manager.gd)
            entry["switch"] = f"SWITCH_ENDING_{name}_PATH"
        types[name] = entry
    return types


def build_endings(out_dir, game_root=None):
    """Write dist/endings.json and return the data dict."""
    if game_root is not None:
        set_ending_root(game_root)
    set_ending_root(GAME)

    types = load_ending_types()
    vignettes = load_ending_paths()
    specials = dict(ENDING_SPECIALS)

    data = {
        "types": types,
        "vignettes": {kid: vignettes[kid] for kid in sorted(vignettes)},
        "specials": specials,
    }
    out_path = Path(out_dir) / "endings.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Endings: {len(types)} ending types · {len(data['vignettes'])} "
          f"character vignettes · {len(specials)} code-played specials")
    return data


def main(argv=None):
    args = list(sys.argv[1:]) if argv is None else list(argv)
    game_root = args[0] if len(args) > 0 else ""
    out_dir = args[1] if len(args) > 1 else ""
    game_root = str(Path(game_root).expanduser().resolve()) if game_root else DEFAULT_GAME_ROOT
    out_dir = Path(out_dir).expanduser().resolve() if out_dir else (SCRIPT_DIR / "dist")
    build_endings(out_dir, game_root=game_root)


if __name__ == "__main__":
    main()
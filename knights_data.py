#!/usr/bin/env python3
"""Sovereign Tower — knight / character data extractor (static viewer).

Parses the game's plain-text Godot resources and emits `knights.json` for the
viewer's Knights tab. Mirrors quest_data.py / inventory_data.py conventions
(stdlib only, portable paths).

Sources:
- content/character_descriptors/knights/*.tres  (24 playable knights)
  The Knight resource: name keys (incl. unrevealed/revealed aliases), origin
  location, six Statistics values, max armor, starting level/affinity, romance
  range, liked/disliked SovereignTags, liked meals, CharacterFeature lists
  (known / unknown / intendant rumors), preferred relic/mount/consumable,
  per-context reaction dialogue keys, affinity / special dialogue tables,
  demission and death follow-up audiences, call-back request, ending path.
- content/dialogues/reactions/...tres  affinity & reaction & special dialogues:
  resolves each dialogue reference to its ink knot (ink_path) so the frontend
  can jump into the Dialogues tab.
- content/knight_conversations/*.tres  (77 pair conversations) -> [other knight, ink knot].
- content/world/locations/*.tres  stem -> LocationsID enum (for origin badges).
- dist/index.json   ink speaker -> knots map; knights are matched via their
  character_ink_id (the ink Locutor name, Title-cased per underscore segment).
- dist/quests.json  reverse links: quests that give the knight affinity
  (AFFINITY reward .k == stem), quests with an unexpected outcome involving the
  knight (.k list), quests that require the knight (.rk), plus rewards that kill
  the knight (CHARACTER_DEATH with .item == knight name key).

Output shape (dist/knights.json):
  knights:  { "<stem>": {...} }  — one entry per .descriptor (knight)
  stats:    header counts (total, ink-linked, quest-linked, with conversations,
            romance-capable, preferred-equipment count, alias count)

Run standalone:
  python3 knights_data.py [game_root] [out_path]
or driven by build_app.py (which supplies the already-built quests.json and
index.json for the reverse maps).
"""

import json
import os
import re
import sys
from pathlib import Path

from quest_data import TresFile, load_gd_enum, set_game

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GAME_ROOT = (SCRIPT_DIR.parent / "game" / "SovereignTowerCode").resolve()

GAME = str(DEFAULT_GAME_ROOT)
KNIGHTS_DIR = f"{GAME}/content/character_descriptors/knights"
DIALOGUES_GROUPS = ("affinity_dialogues", "reactions", "knights_conversations_dialogues")
CONVERSATIONS_DIR = f"{GAME}/content/knight_conversations"
LOCATIONS_DIR = f"{GAME}/content/world/locations"
OUT_PATH = str(SCRIPT_DIR / "knights.json")


def set_knights_root(root):
    """Point this module's path globals at a given game root (see build_app)."""
    global GAME, KNIGHTS_DIR, CONVERSATIONS_DIR, LOCATIONS_DIR
    GAME = str(Path(root).expanduser().resolve())
    KNIGHTS_DIR = f"{GAME}/content/character_descriptors/knights"
    CONVERSATIONS_DIR = f"{GAME}/content/knight_conversations"
    LOCATIONS_DIR = f"{GAME}/content/world/locations"

GODOT_DEFAULTS = {
    "max_armor": 5, "starting_level": 1, "starting_affinity": 0,
    "min_affinity": -10.0, "max_affinity": 10.0, "demission_affinity_treshold": -7,
    "min_romantism": 0, "max_romantism": 4,
}

PACKED_STR_ARRAY = re.compile(r"PackedStringArray\((.*)\)", re.S)


def _stripped(s):
    return s.strip().strip('"').lstrip("&").strip()


def parse_packed_string_array(value):
    """PackedStringArray("A", "B") -> ["A", "B"]; else []."""
    if not isinstance(value, str):
        return []
    m = PACKED_STR_ARRAY.search(value)
    if not m:
        return []
    inner = m.group(1)
    return [x.strip().strip('"') for x in inner.split(",") if x.strip()]


def _dialogue_ink_path(dialogue_path):
    """Open a FreeTimeDialogue .tres and return its ink_path (knot) or None."""
    if not dialogue_path:
        return None
    if dialogue_path.startswith("res://"):
        dialogue_path = dialogue_path[6:]
    p = f"{GAME}/{dialogue_path}"
    if not os.path.exists(p):
        return None
    try:
        tf = TresFile.load(p, os.path.dirname(p))
        ink = tf.props.get("ink_path")
        if isinstance(ink, dict):
            return None
        return str(ink) if ink else None
    except Exception:
        return None


def _ext_stem(tf, ref):
    """Ext-resource basename (stem) for a {_ext: id} ref, or None."""
    if not isinstance(ref, dict) or "_ext" not in ref:
        return None
    path = tf.ext.get(ref["_ext"])
    if not path:
        return None
    return os.path.splitext(os.path.basename(path))[0]


def load_locations_dir():
    """{location stem: LocationsID enum name} from content/world/locations/*.tres."""
    out = {}
    if not os.path.isdir(LOCATIONS_DIR):
        return out
    for fn in os.listdir(LOCATIONS_DIR):
        if not fn.endswith(".tres"):
            continue
        try:
            tf = TresFile.load(os.path.join(LOCATIONS_DIR, fn), LOCATIONS_DIR)
        except Exception:
            continue
        lid = tf.props.get("location_ID")
        if isinstance(lid, int):
            out[os.path.splitext(fn)[0]] = lid
    return out


def decode_stats(dict_like):
    """Godot Dictionary {stat_index: value} -> [6 ints] in Statistics order."""
    stats = [0, 0, 0, 0, 0, 0]
    if not isinstance(dict_like, list):
        return stats
    for entry in dict_like:
        if not isinstance(entry, dict):
            continue
        k, v = entry.get("key"), entry.get("value")
        if isinstance(k, int) and 0 <= k < 6 and isinstance(v, int):
            stats[k] = v
    return stats


def decode_dict_value(dict_like):
    """Godot Dictionary -> plain {k: v} where values are already parsed."""
    if not isinstance(dict_like, list):
        return {}
    out = {}
    for entry in dict_like:
        if isinstance(entry, dict):
            out[entry.get("key")] = entry.get("value")
    return out


# ---------------------------------------------------------------------------
# Evolution / state paths for the special-knight scripts.
# The .tres descriptors carry the per-state stat dictionaries, passive
# features, relics and meals; triggers and removed tags come from the custom
# knight scripts (arron.gd / silgur.gd / gwendan.gd / dulahan.gd). A few script
# defaults (stat bonuses, armor malus, tags to drop) are not exported into the
# .tres, so they live here as documented constants.
# ---------------------------------------------------------------------------
STAT_NAMES = ["STRENGTH", "AGILITY", "CHARISMA", "MAGIC", "WITS", "LUCK"]

EVO_DEFS = {
    "arron": [
        {
            "name": "Kind",
            "trigger": "ARRON_KIND",
            "stats": "kind_statistics_value",
            "feature": "kind_passive_to_get",
            "relic": "baby_dragon",
            "removes": ["TIMID"],
            "note": "Finalizes the with-egg path: fires the moment Arron finishes any quest.",
        },
        {
            "name": "Violent",
            "trigger": "ARRON_VIOLENT",
            "stats": "violent_statistics_value",
            "feature": "violent_passive_to_get",
            "meals": "violent_liked_meals",
            "removes": ["TIMID"],
            "note": "Reward of quest_arron_ritual (unlocked by holding the Dragon Heart).",
        },
        {
            "name": "With Egg",
            "trigger": "ARRON_WITH_EGG",
            "note": "Prelude only: no stat change by itself; the Kind path fires on his next completed quest.",
        },
    ],
    "silgur": [
        {
            "name": "Dragon Heart Eaten",
            "trigger": "SILGUR_DRAGON_HEART_EATEN",
            "stats": "dragon_heart_statistics_value",
            "note": "Permanent stat bonus once the dragon heart is consumed.",
        },
    ],
    "gwendan": [
        {
            "name": "Reformed",
            "trigger": "GWENDAN_REFORMED",
            "stats": [2, 0, 1, 0, 1, 0],
            "feature": "reformed_passive_to_get",
            "removes_field": "reformed_tags_to_remove",
            "removes": ["IN_DEBT"],
            "note": "Adds a follow-up audience a few cycles later.",
        },
        {
            "name": "Repaid",
            "trigger": "GWENDAN_UNREFORMED",
            "removes": ["IN_DEBT"],
            "note": "Debt paid back; keeps her normal behaviour.",
        },
        {
            "name": "Magic Gain",
            "trigger": "GWENDAN_MAGIC_GAIN",
            "stats": [0, 0, 0, 8, 0, 0],
            "note": "Permanent +8 MAGIC (script default).",
        },
    ],
    "dulahan": [
        {
            "name": "Cursed Helmet",
            "trigger": "DULAHAN_HELMET",
            "stats": "helmet_possession_statistics_value",
            "note": "Swaps reactions/dialogues; keeps only INATTENTIVE / EXTREMELY_CLUMSY characteristics.",
        },
        {
            "name": "Body Possession",
            "trigger": "DULAHAN_HUMAN",
            "stats": "body_possession_statistics_value",
            "armor": -1,
            "note": "Swaps reactions/dialogues; armor -1 (script default).",
        },
    ],
    "goberto": [
        {
            "name": "Supra Armor",
            "trigger": "GOBERTO_SUPRA_ARMORED",
            "stats": [2, 2, 5, 4, 0, 4],
            "armor": 10,
            "feature": "protector",
            "note": "Almor great-duel unexpected outcome: Goberto dons the supra armor, gaining the PERFECT_ARMOR protector passive and +10 armor (script defaults).",
        },
    ],
    "ursule": [
        {
            "name": "Destroyed by Kingslayer",
            "trigger": "URSULA_DESTROYED_BY_KINGSLAYER",
            "stats": "stats_corruption_high",
            "note": "The Kingslayer ultimatum kills her: deaths_count is pushed past the HIGH corruption threshold, applying the high-corruption stat shift (script defaults).",
        },
    ],
    "oliver": [
        {
            "name": "Mage Formation",
            "trigger": "OLIVER_MAGIC_GAIN",
            "stats": [0, 0, 0, 8, 0, 0],
            "note": "Permanent +8 MAGIC once the magic-degree quest succeeds (script default).",
        },
    ],
}


def build_evolutions(tf, props, enums, stem, finder_evos=None):
    """Evolution-state blocks for the special-knight descriptors (else []).

    Each state: {name, trigger, stats (6 deltas), features[], relic, meals[],
    removes[], armor, note}. "stats"/"feature"/"relic"/"meals"/"removes_field"
    read the .tres; literals come from EVO_DEFS script-default constants.

    When `finder_evos` (evolution_finder output for this stem) is non-empty it
    takes precedence over the manual EVO_DEFS — the finder walks the actual
    signal->method wiring, so it cannot drift. Hand-written EVO_DEFS notes are
    preserved on matching triggers; EVO_DEFS remains the fallback for any stem
    the finder does not cover.
    """
    if finder_evos:
        notes = {d.get("trigger"): d.get("note") for d in EVO_DEFS.get(stem, []) if d.get("note")}
        out = []
        for evo in finder_evos:
            e = dict(evo)
            if notes.get(e.get("trigger")):
                e["note"] = notes[e["trigger"]]
            out.append(e)
        return out
    defs = EVO_DEFS.get(stem)
    if not defs:
        return []
    tag_names = enums.get("CharacterTags", {})
    meal_names = enums.get("MealsID", {})
    out = []
    for d in defs:
        evo = {"name": d["name"], "trigger": d["trigger"]}
        sf = d.get("stats")
        if isinstance(sf, str):
            evo["stats"] = decode_stats(props.get(sf))
        elif isinstance(sf, list):
            evo["stats"] = list(sf)
        if d.get("armor"):
            evo["armor"] = d["armor"]
        if d.get("feature"):
            ref = props.get(d["feature"])
            if isinstance(ref, dict) and "_sub" in ref:
                fp = tf.sub_props(ref["_sub"])
                evo["features"] = [{
                    "t": fp.get("type", 0),
                    "n": tag_names.get(fp.get("character_tag"), fp.get("character_tag")),
                    "d": fp.get("description", ""),
                }]
        if d.get("relic"):
            rstem = _ext_stem(tf, props.get(d["relic"]))
            if rstem:
                evo["relic"] = rstem
        if d.get("meals"):
            evo["meals"] = [meal_names.get(m, m) for m in (props.get(d["meals"]) or [])]
        removes = []
        if d.get("removes_field"):
            for t in (props.get(d["removes_field"]) or []):
                n = tag_names.get(t, t)
                if n not in removes:
                    removes.append(n)
        for t in (d.get("removes") or []):
            if t not in removes:
                removes.append(t)
        if removes:
            evo["removes"] = removes
        if d.get("note"):
            evo["note"] = d["note"]
        out.append(evo)
    return out


def decode_features(tf, refs, enums):
    """CharacterFeature refs -> [{t, n, p?, d?}].

    t: 0=characteristic, 1=quest-type preference, 2=condition preference.
    n = enum display name; p = LIKE(1)/DISLIKE(0) for preferences; d = loc key.
    """
    features = []
    for ref in refs or []:
        if not isinstance(ref, dict) or "_sub" not in ref:
            continue
        props = tf.sub_props(ref["_sub"])
        ftype = props.get("type", 0)
        feat = {"t": ftype}
        if ftype == 1:
            feat["n"] = enums.get("QuestTags", {}).get(props.get("quest_tag"), props.get("quest_tag"))
            feat["p"] = props.get("preference_type", 0)
        elif ftype == 2:
            feat["n"] = enums.get("ConditionTags", {}).get(props.get("condition_tag"), props.get("condition_tag"))
            feat["p"] = props.get("preference_type", 0)
        else:
            feat["n"] = enums.get("CharacterTags", {}).get(props.get("character_tag"), props.get("character_tag"))
        if props.get("description"):
            feat["d"] = props["description"]
        features.append(feat)
    return features


def load_knights(quests_data=None, index=None, game_root=None):
    """Full catalog. `quests_data` = dict from quest_data.load_quests();
    `index` = dist/index.json (ink walker output with per-knot `lines`).
    `game_root` = resolved game project path (defaults to module default)."""
    if game_root is not None:
        set_knights_root(game_root)
    set_game(GAME)
    if not os.path.isdir(KNIGHTS_DIR):
        return {"knights": {}, "stats": {"total": 0}}

    enums = {}
    for name in ("CharacterTags", "QuestTags", "ConditionTags", "Statistics",
                 "SovereignTags", "MealsID", "LocationsID"):
        entries = load_gd_enum(name) or []
        enums[name] = {v: n for n, v in entries}

    # generic finder output (signal->method wiring) for the evo blocks
    try:
        from evolution_finder import build_finder
        finder_by_stem = build_finder() or {}
    except Exception:
        finder_by_stem = {}
    loc_by_stem = load_locations_dir()
    stat_names = enums.get("Statistics", {})

    def tag_names(values, enum):
        return [enums.get(enum, {}).get(v, v) for v in (values or [])]

    # --- ink speaker -> knot list, once -------------------------------
    speaker_knots = {}
    if index and index.get("knots"):
        for kname, kdata in index["knots"].items():
            for token in kdata.get("lines", []):
                if isinstance(token, list) and token[:1] == ["0"] and len(token) > 2 and token[2]:
                    speaker_knots.setdefault(token[2], []).append(kname)

    def speaker_for(ink_id):
        if not ink_id:
            return None
        return "_".join(part[:1].upper() + part[1:] for part in ink_id.split("_") if part)

    # --- knight conversations ------------------------------------------
    conversations = {}  # knight stem -> [[other_stem, knot]]
    if os.path.isdir(CONVERSATIONS_DIR):
        for fn in sorted(os.listdir(CONVERSATIONS_DIR)):
            if not fn.endswith(".tres"):
                continue
            try:
                tf = TresFile.load(os.path.join(CONVERSATIONS_DIR, fn), CONVERSATIONS_DIR)
            except Exception:
                continue
            stems = []
            for ref in tf.props.get("knights", []) or []:
                s = _ext_stem(tf, ref)
                if s:
                    stems.append(s)
            if not stems:
                continue
            knot = None
            dref = tf.props.get("dialogue")
            if isinstance(dref, dict):
                pid = dref.get("_ext")
                knot = _dialogue_ink_path(tf.ext.get(pid)) if pid else None
            for s in stems:
                others = [o for o in stems if o != s]
                conversations.setdefault(s, []).append([others, knot])

    # --- quest cross-links ---------------------------------------------
    quest_links = {os.path.splitext(fn)[0]: {"a": [], "u": [], "r": []}
                   for _ in [None] for fn in os.listdir(KNIGHTS_DIR) if fn.endswith(".tres")}
    if quests_data:
        reward_type = {n: v for n, v in quests_data.get("enums", {}).get("RewardType", [])}
        af_id = reward_type.get("AFFINITY")
        for qid, q in quests_data.get("quests", {}).items():
            for stem, links in quest_links.items():
                for r in list(q.get("rw", {}).get("s", [])) + list(q.get("rw", {}).get("f", [])):
                    if r.get("t") == af_id and r.get("k") == stem:
                        links["a"].append(qid)
                for k in q.get("rk", []) or []:
                    if k == stem:
                        links["r"].append(qid)
                for uo in q.get("un", []):
                    if stem in (uo.get("k") or []):
                        links["u"].append(qid)

    # --- per-knight build ----------------------------------------------
    knights = {}
    for fn in sorted(os.listdir(KNIGHTS_DIR)):
        if not fn.endswith(".tres"):
            continue
        stem = os.path.splitext(fn)[0]
        path = os.path.join(KNIGHTS_DIR, fn)
        tf = TresFile.load(path, KNIGHTS_DIR)
        P = tf.props

        # affinity / special dialogue ink knots
        afd = {}
        for entry in P.get("affinity_dialogues", []) or []:
            if not isinstance(entry, dict):
                continue
            lvl, ref = entry.get("key"), entry.get("value")
            if isinstance(ref, dict) and "_ext" in ref:
                knot = _dialogue_ink_path(tf.ext.get(ref["_ext"]))
                if knot:
                    afd[lvl] = knot

        specd = {}
        for entry in P.get("special_dialogues", []) or []:
            if not isinstance(entry, dict):
                continue
            key, ref = entry.get("key"), entry.get("value")
            if isinstance(key, str):
                key = key.lstrip("&").strip('"')
            if isinstance(ref, dict) and "_ext" in ref:
                knot = _dialogue_ink_path(tf.ext.get(ref["_ext"]))
                if knot:
                    specd[key] = knot

        react = {}
        for entry in P.get("reactions", []) or []:
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            if isinstance(key, str):
                key = key.lstrip("&").strip('"')
            lines = parse_packed_string_array(entry.get("value"))
            if lines:
                react[key] = lines

        # preferred equipment stems (cross-link to inventory tab)
        equip = {}
        for field, kind in (("relic", "R"), ("consumable", "C"), ("mount", "M")):
            s = _ext_stem(tf, P.get(field))
            if s:
                equip[kind] = s

        ink_id = P.get("character_ink_id") or stem
        speaker = speaker_for(str(ink_id))
        story = sorted(set(speaker_knots.get(speaker, []))) if speaker else []
        loc_val = loc_by_stem.get(_ext_stem(tf, P.get("origin_location")) or "")

        ref_passive = {}
        rp_ref = P.get("reformed_passive_to_get")
        if isinstance(rp_ref, dict) and "_sub" in rp_ref:
            props = tf.sub_props(rp_ref["_sub"])
            ref_passive = {
                "t": props.get("type", 0),
                "n": enums.get("CharacterTags", {}).get(props.get("character_tag"), props.get("character_tag")),
                "d": props.get("description", ""),
            }

        knight = {
            "stem": stem,
            "n": P.get("name", ""),
            "nu": P.get("unrevealed_name", ""),
            "nr": P.get("revealed_name", ""),
            "ink": str(ink_id),
            "loc": enums.get("LocationsID", {}).get(loc_val, loc_val) if loc_val is not None else "",
            "st": decode_stats(P.get("statistics_value")),
            "arm": P.get("max_armor", GODOT_DEFAULTS["max_armor"]),
            "lvl": P.get("starting_level", GODOT_DEFAULTS["starting_level"]),
            "aff": P.get("starting_affinity", GODOT_DEFAULTS["starting_affinity"]),
            "afmin": P.get("min_affinity", GODOT_DEFAULTS["min_affinity"]),
            "afmax": P.get("max_affinity", GODOT_DEFAULTS["max_affinity"]),
            "dem": P.get("demission_affinity_treshold", GODOT_DEFAULTS["demission_affinity_treshold"]),
            "mast": [stat_names.get(v, v) for v in (P.get("mastered_stats") or [])],
            "rom": [P.get("min_romantism", GODOT_DEFAULTS["min_romantism"]),
                    P.get("max_romantism", GODOT_DEFAULTS["max_romantism"])],
            "lt": tag_names(P.get("liked_sovereign_tags"), "SovereignTags"),
            "dt": tag_names(P.get("disliked_sovereign_tags"), "SovereignTags"),
            "meals": tag_names(P.get("liked_meals"), "MealsID"),
            "feat": {
                "k": decode_features(tf, P.get("known_features"), enums),
                "u": decode_features(tf, P.get("unknown_features"), enums),
                "r": decode_features(tf, P.get("intendant_rumors_features"), enums),
            },
            "equip": equip,
            "react": react,
            "dflt": P.get("default_description", ""),
            "react0": P.get("neutral_reaction", ""),
            "react1": P.get("liked_reaction", ""),
            "react2": P.get("disliked_reaction", ""),
            "expr": [P.get("neutral_expression", ""), P.get("liked_expression", ""),
                     P.get("disliked_expression", "")],
            "ending": P.get("ending_path", ""),
            "demo": P.get("roundtable_demission_audience_name", ""),
            "death": P.get("death_follow_up_audiences_names", []) or [],
            "callback": P.get("call_back_audience_request", ""),
            "afd": afd,
            "specd": specd,
            "ref_remove": P.get("reformed_tags_to_remove", []) or [],
            "ref_passive": ref_passive,
            "conv": conversations.get(stem, []),
            "story": story,
            "qa": quest_links.get(stem, {}).get("a", []),
            "qu": quest_links.get(stem, {}).get("u", []),
            "qr": quest_links.get(stem, {}).get("r", []),
            "evo": build_evolutions(tf, P, enums, stem, finder_by_stem.get(stem)),
        }
        knights[stem] = knight

    n_total = len(knights)
    stats = {
        "total": n_total,
        "ink_linked": sum(1 for k in knights.values() if k["story"]),
        "quest_linked": sum(1 for k in knights.values() if k["qa"] or k["qu"] or k["qr"]),
        "with_convs": sum(1 for k in knights.values() if k["conv"]),
        "romance": sum(1 for k in knights.values() if k["rom"][1] > 0),
        "equipped": sum(1 for k in knights.values() if k["equip"]),
        "aliased": sum(1 for k in knights.values() if k["nu"] or k["nr"]),
        "evo_knights": sum(1 for k in knights.values() if k["evo"]),
        "evo_states": sum(len(k["evo"]) for k in knights.values()),
    }
    return {"knights": knights, "stats": stats}


def main(argv=None):
    args = list(sys.argv[1:]) if argv is None else list(argv)
    game_arg = args[0] if len(args) > 0 else ""
    out_arg = args[1] if len(args) > 1 else ""

    def coerce(p, default):
        return default if not p else Path(p).expanduser().resolve()

    game_root = coerce(game_arg, DEFAULT_GAME_ROOT)
    set_game(game_root)
    out_dir = coerce(out_arg, Path(OUT_PATH)).parent

    quests_data = None
    qp = out_dir / "quests.json"
    if qp.exists():
        try:
            quests_data = json.load(open(qp, encoding="utf-8"))
        except Exception:
            quests_data = None
    index = None
    ip = out_dir / "index.json"
    if ip.exists():
        try:
            index = json.load(open(ip, encoding="utf-8"))
        except Exception:
            index = None

    data = load_knights(quests_data=quests_data, index=index, game_root=game_root)
    out = coerce(out_arg, Path(OUT_PATH))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    s = data["stats"]
    print(f"Wrote {out}: {s['total']} knights · {s['ink_linked']} ink-linked · "
          f"{s['quest_linked']} quest-linked · {s['with_convs']} with conversations · "
          f"{s['romance']} romance-capable")


if __name__ == "__main__":
    main()
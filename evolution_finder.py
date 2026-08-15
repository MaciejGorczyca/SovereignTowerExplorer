#!/usr/bin/env python3
"""Sovereign Tower — generic knight-evolution finder.

Auto-discovers the knight evolution blocks that `knights_data.EVO_DEFS` used to
carry by hand. It walks the real wiring instead:

1. `systems/autoloads/character_special_instructions_manager.gd`  — its
   `_ready()` block connects `SignalsEventBus.<signal>.connect(_on_<signal>)`,
   and each `_on_<signal>` handler pulls the owning knight via
   `get_knight_from_name("<stem>")` and calls `<knight>.<method>()`. That yields
   the declarative map:  signal -> (knight stem, evolution method).
2. `systems/resources/characters/<stem>.gd` — the evolution method body tells
   what the state change does:
     - `current_state = State.<X>`                          -> evolution name
     - `for stat in <field>.keys(): bonus_stats[...] += ...` -> stat-dictionary
       (values in the knight .tres), or `bonus_stats[Statistics.X] += <var>`
       (scalar `@export` default in the script)
     - `bonus_armor (+=|-=) <var>`                          -> armor delta
     - `(unknown|known)_features.append(<var>)`             -> passive feature
     - `relic = <var>`                                      -> gained relic
     - `for meal in <var>: ... liked_meals.erase(meal)`     -> meals field
     - `remove_<tag>()` / inline `feature.character_tag in <field>` loops
       -> tags dropped (resolved through the script defaults / .tres)
3. `special_instruction_manager.gd` (already parsed by `special_data`) inverts
   signal -> instruction name, which is what `special.json` / `knights.json`
   use as the evolution `trigger`.

A handful of documented irregularities stay as explicit exceptions instead of
heuristics (they are structurally not discoverable from the method body):
   - ursule / URSULA_DESTROYED_BY_KINGSLAYER: `trigger_death_by_kingslayer`
     only bumps `deaths_count`; the actual stat shift is `stats_corruption_high`
     applied later by the corruption system (no `bonus_stats` line in the method).
   - oliver Mage: `trigger_magician_formation` delegates to `trigger_magic_gain()`;
     the finder follows intra-script helper calls.

Usage:
    python3 evolution_finder.py [game_root]
Writes dist/evolutions.json: { "<stem>": [ {evo block}, ... ] } in the same
schema as knights_data.build_evolutions (name/trigger/stats/features/relic/
meals/removes/armor), ready to diff against the manual EVO_DEFS output.
"""

import json
import os
import re
import sys
from pathlib import Path

from quest_data import TresFile, load_gd_enum, set_game
from special_data import load_special_instructions

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GAME_ROOT = (SCRIPT_DIR.parent / "game" / "SovereignTowerCode").resolve()

GAME = str(DEFAULT_GAME_ROOT)

MANAGER_PATH = "systems/autoloads/character_special_instructions_manager.gd"
KNIGHTS_DIR = "content/character_descriptors/knights"
CHARACTERS_DIR = "systems/resources/characters"
OUT_PATH = str(SCRIPT_DIR / "dist" / "evolutions.json")

# stem (.tres name) -> script filename where they differ
GD_FILE_ALIAS = {"ursule": "ursula"}

STAT_NAMES = ["STRENGTH", "AGILITY", "CHARISMA", "MAGIC", "WITS", "LUCK"]

CONNECT_RE = re.compile(r"SignalsEventBus\.(\w+)\.connect\((_on_\w+)\)")
STEM_RE = re.compile(r'get_knight_from_name\("(\w+)"\)')
VAR_KNIGHT_RE = re.compile(r"var (\w+): \w+ = (?:GameState\.)?character_manager\.get_knight_from_name\(\"(\w+)\"\)")
CALL_RE = re.compile(r"(\w+)\.(\w+)\(")

EXCEPTION_FIELDS = {
    # stem -> {method: {"stats": <tres field>}}  (stats not visible in method body)
    "ursule": {
        "trigger_death_by_kingslayer": {"stats": "stats_corruption_high"},
    },
}

NAME_BY_STATE = {
    "Armored": "Supra Armor",
    "Helmet": "Cursed Helmet",
    "Body": "Body Possession",
    "Mage": "Mage Formation",
    "DragonHeartEaten": "Dragon Heart Eaten",
    "WithEgg": "With Egg",
    "Repaid": "Repaid",
    "Reformed": "Reformed",
    "Kind": "Kind",
    "Violent": "Violent",
    "Possessed": "Possessed",
    "Unchanged": None,
}

# method-derived fallback names for evolutions with no State switch
NAME_BY_METHOD = {
    "trigger_death_by_kingslayer": "Destroyed by Kingslayer",
    "trigger_magic_gain": "Magic Gain",
}


def func_blocks(text):
    """Split GDScript text into (name, body) for every top-level `func`."""
    for part in re.split(r"^(?=func )", text, flags=re.M):
        m = re.match(r"^func (\w+)\([^)]*\)(?: -> [^:]*)?:\n", part)
        if not m:
            continue
        yield m.group(1), part[m.end():]


def load_defaults(gd_text):
    """Parse `@export var <name>: <type> = <value>` (incl. multiline dicts)."""
    defaults = {}
    for m in re.finditer(
        r"@export var (\w+):\s*[\w\[\],.<>]+\s*= (\{[^}]*\}|\[[^\]]*\]|-?\d+|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)",
        gd_text, re.M
    ):
        field, val = m.group(1), m.group(2).strip()
        if val.startswith("{") or val.startswith("["):
            defaults[field] = val
        elif val.startswith("-") or val.isdigit() or (val[1:].isdigit() and val[0] == "-"):
            try:
                defaults[field] = int(val)
            except ValueError:
                pass
        else:
            defaults[field] = val.split(".")[-1]  # TagManager.CharacterTags.TIMID -> TIMID
    return defaults


def resolve_default_list(defaults, field):
    """Decode a script-default array/tag list into a plain python list."""
    val = defaults.get(field)
    if not isinstance(val, str):
        return val
    if val.startswith("["):
        return re.findall(r"[\w]+", val)
    if val.startswith("{"):
        return []
    return [val] if val else []


def load_handler_map():
    """{signal: (stem, method)} from the special-instructions manager."""
    path = f"{GAME}/{MANAGER_PATH}"
    if not os.path.exists(path):
        return {}
    text = open(path, encoding="utf-8").read()
    blocks = {name: body for name, body in func_blocks(text)}
    out = {}
    for signal, handler in CONNECT_RE.findall(text):
        body = blocks.get(handler, "")
        varm = VAR_KNIGHT_RE.search(body)
        if not varm:
            continue
        var, stem = varm.group(1), varm.group(2)
        methods = [m for v, m in CALL_RE.findall(body) if v == var]
        if methods:
            out[signal] = (stem, methods[0])
    return out


def read_tres(stem):
    """TresFile + props for a knight descriptor."""
    p = f"{GAME}/{KNIGHTS_DIR}/{stem}.tres"
    if not os.path.exists(p):
        return None, {}
    tf = TresFile.load(p, os.path.dirname(p))
    return tf, tf.props


def decode_stat_dict(props, field):
    """Godot dict prop -> [6 ints] (Statistics order)."""
    stats = [0, 0, 0, 0, 0, 0]
    for entry in (props.get(field) or []):
        if isinstance(entry, dict):
            k = entry.get("key")
            v = entry.get("value")
            if isinstance(k, int) and 0 <= k < 6 and isinstance(v, int):
                stats[k] = v
    return stats


def resolve_stat_scalars(body, defaults):
    """Direct `bonus_stats[Statistics.X] += <var>` lines -> [6 ints]."""
    stats = [0, 0, 0, 0, 0, 0]
    for stat, var in re.findall(r"bonus_stats\[Statistics\.(\w+)\] \+= (\w+)", body):
        if stat in STAT_NAMES:
            val = defaults.get(var)
            if isinstance(val, int):
                stats[STAT_NAMES.index(stat)] += val
    return stats


def find_removes(body, defaults, props, all_blocks=None):
    """Collect dropped tags from inline loops and remove_<tag>() helpers.

    Inline removal loops appear either as erasing matching tags
    (`if not feature.character_tag in <field>: continue`) or unequal tags
    (`if feature.character_tag != <field>: continue`). A `remove_<tag>()`
    helper is resolved through the caller-supplied function blocks.
    """
    removes = []
    seen = set()
    tag_names = _tag_names()
    # stat-loop safe for typed loop vars: `for feature: CharacterFeature in ...`
    loop_re = re.compile(
        r"for \w+(?::\s*[\w.]+)?\s+in\s+(?:known|unknown)_features\.duplicate\(\):(.*?)(?=\n\s*\n|\n\w|\Z)",
        re.S,
    )

    def add_field(field):
        if field in seen:
            return
        seen.add(field)
        names = []
        pval = props.get(field)
        if isinstance(pval, list):
            for item in pval:
                if isinstance(item, int):
                    names.append(tag_names.get(item, str(item)))
        if not names:
            listed = resolve_default_list(defaults, field) or []
            if not isinstance(listed, list):
                listed = [listed]
            for item in listed:
                if item:
                    names.append(item)
        for n in names:
            if n not in removes:
                removes.append(n)

    # inline loops that erase matching tags
    for m in loop_re.finditer(body):
        chunk = m.group(1)
        not_in = re.search(r"not\s+feature\.character_tag\s+in\s+(\w+_tags_to_remove)", chunk)
        neq = re.search(r"feature\.character_tag\s+!=\s+(\w+_tag_to_remove)", chunk)
        if not_in or neq:
            add_field((not_in or neq).group(1))

    # remove_<tag>() helper calls -> chase helper body for its tag field
    for name in re.findall(r"remove_(\w+)\(\)", body):
        hbody = (all_blocks or {}).get("remove_" + name, "")
        if not hbody:
            continue
        not_in = re.search(r"not\s+feature\.character_tag\s+in\s+(\w+_tags_to_remove)", hbody)
        neq = re.search(r"feature\.character_tag\s+!=\s+(\w+_tag_to_remove)", hbody)
        if not_in or neq:
            add_field((not_in or neq).group(1))
    return removes


def _tag_names():
    tags = {}
    for name, val in (load_gd_enum("CharacterTags") or []):
        tags[val] = name
    return tags


def _meal_names():
    meals = {}
    for name, val in (load_gd_enum("MealsID") or []):
        meals[val] = name
    return meals


def parse_method(stem, method, gd_text, props, tf):
    """Effects of one evolution method -> (evo dict, has_state)."""
    blocks = {name: body for name, body in func_blocks(gd_text)}
    body = blocks.get(method, "")
    if not body:
        return None, False
    defaults = load_defaults(gd_text)

    evo = {}

    # name from State enum (fall back to method-derived label)
    sm = re.search(r"current_state = State\.(\w+)", body)
    has_state = sm is not None
    name = NAME_BY_STATE.get(sm.group(1)) if sm else None
    if not name:
        words = [w for w in re.split(r"_+", method) if w and w not in ("set", "trigger")]
        name = " ".join(w[:1].upper() + w[1:] for w in words) if words else method
    evo["name"] = name
    if not sm and method in NAME_BY_METHOD:
        evo["name"] = NAME_BY_METHOD[method]

    # follow intra-script delegation: merged helper <method>_magic_gain() / etc.
    if re.search(r"trigger_magic_gain\(\)", body):
        hb = blocks.get("trigger_magic_gain", "")
        sc = resolve_stat_scalars(hb, defaults)
        body = body + "\n" + hb  # let scalar resolver also read helper bonuses

    # stats: dict-loop fields (from .tres) + scalar defaults
    stats = [0, 0, 0, 0, 0, 0]
    for m in re.finditer(r"for (\w+)(?::\s*[\w.]+)? in (\w+)\.keys\(\):", body):
        var, field = m.group(1), m.group(2)
        seg = body[m.end():]
        if re.search(r"bonus_stats\[%s\] \+= %s\[%s\]" % (re.escape(var), re.escape(field), re.escape(var)), seg):
            d = decode_stat_dict(props, field)
            stats = [a + b for a, b in zip(stats, d)]
    sc = resolve_stat_scalars(body, defaults)
    stats = [a + b for a, b in zip(stats, sc)]
    if any(stats):
        evo["stats"] = stats

    # armor
    am = re.search(r"bonus_armor (\+=|-=) (\w+)", body)
    if am:
        op, field = am.group(1), am.group(2)
        val = defaults.get(field)
        if isinstance(val, int):
            evo["armor"] = val if op == "+=" else -val

    # features (deduped)
    feats = []
    for fld in re.findall(r"(?:unknown|known)_features\.append\((\w+)\)", body):
        ref = props.get(fld)
        if isinstance(ref, dict) and "_sub" in ref:
            sp = tf.sub_props(ref["_sub"])
            tags = _tag_names()
            feat = {
                "t": sp.get("type", 0),
                "n": tags.get(sp.get("character_tag"), sp.get("character_tag")),
                "d": sp.get("description", ""),
            }
            if feat not in feats:
                feats.append(feat)
    if feats:
        evo["features"] = feats

    # relic
    rm = re.search(r"(?<!is_instance_valid\()relic = (\w+)", body)
    if rm:
        ref = props.get(rm.group(1))
        if isinstance(ref, dict) and "_ext" in ref:
            path = tf.ext.get(ref["_ext"])
            if path:
                evo["relic"] = os.path.splitext(os.path.basename(path))[0]

    # meals (skip base liked_meals / known_liked_meals field — not an evo change)
    meals = []
    for m in re.finditer(r"for (\w+)(?::\s*[\w.]+)? in (\w+):", body):
        var, field = m.group(1), m.group(2)
        if field in ("liked_meals", "known_liked_meals"):
            continue
        seg = body[m.end():m.end() + 300]
        if re.search(r"known_liked_meals\.(?:erase|append)\(\s*%s\s*\)" % re.escape(var), seg):
            vals = props.get(field)
            names = _meal_names()
            for v in (vals or []):
                if isinstance(v, int):
                    meals.append(names.get(v, str(v)))
    if meals:
        evo["meals"] = meals

    # removes
    removes = find_removes(body, defaults, props, blocks)
    if removes:
        evo["removes"] = removes

    return evo, has_state


def build_finder():
    """{stem: [ {evo block}, ... ]} from the declarative wiring."""
    set_game(GAME)
    handler_map = load_handler_map()

    # signal -> instruction name(s), inverting load_special_instructions()
    sig_to_instr = {}
    for instr, signal in load_special_instructions().items():
        sig_to_instr.setdefault(signal, []).append(instr)

    out = {}
    for signal, (stem, method) in sorted(handler_map.items()):
        triggers = sig_to_instr.get(signal) or []
        gd_name = GD_FILE_ALIAS.get(stem, stem)
        gd_path = f"{GAME}/{CHARACTERS_DIR}/{gd_name}.gd"
        if not os.path.exists(gd_path):
            continue
        gd_text = open(gd_path, encoding="utf-8").read()
        tf, props = read_tres(stem)

        evo, has_state = parse_method(stem, method, gd_text, props, tf)
        if evo is None:
            continue

        # documented exceptions: fields not visible in the method body
        if stem in EXCEPTION_FIELDS and method in EXCEPTION_FIELDS[stem]:
            for fld in EXCEPTION_FIELDS[stem][method]:
                if fld == "stats":
                    d = decode_stat_dict(props, "stats_corruption_high")
                    if any(d):
                        evo["stats"] = d

        # drop non-evolutions: no State switch and no effect fields at all
        # (e.g. wolf name definition, angelica death-reaction unlock)
        if not has_state and not any(
            evo.get(k) for k in ("stats", "features", "relic", "meals", "removes", "armor")
        ):
            continue

        entry = {"name": evo["name"], "trigger": triggers[0] if triggers else signal}
        for key in ("stats", "features", "relic", "meals", "removes", "armor"):
            if evo.get(key):
                entry[key] = evo[key]
        out.setdefault(stem, []).append(entry)

    return out


def main(argv=None):
    args = list(sys.argv[1:]) if argv is None else list(argv)
    game_root = args[0] if len(args) > 0 else DEFAULT_GAME_ROOT
    game_root = str(Path(game_root).expanduser().resolve())
    set_game(game_root)

    global GAME
    GAME = game_root

    data = build_finder()
    out = Path(OUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    n_evo = sum(len(v) for v in data.values())
    print(f"Wrote {out}: {len(data)} knights · {n_evo} evolutions (generic finder)")
    return data


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Sovereign Tower — equipment / inventory data extractor (static viewer).

Parses the game's plain-text Godot resources and emits `inventory.json` for the
viewer's Inventory tab:

- content/equipment/{relics,mounts,consumable,meals,quest_items}/*.tres
  Every `Equipment` resource: name/description (localization keys), the six
  Knight.Statistics bonuses (STRENGTH, AGILITY, CHARISMA, MAGIC, WITS, LUCK),
  CharacterTags, cost, and the flag surface (bonus_armor, duration_reduction,
  is_exclusive, hidden_stats, requires_refreshes, has_complex_passive) plus
  the subtype ID (relic/mount/consumable/meal ID) and consumable uses.
  Items flagged has_complex_passive also carry `psv`: the mechanical effect
  notes for the character tags they grant (mirroring special_cases.gd).
- systems/autoloads/game_state.tscn  (InventoryManager node)
  Where items can be bought: the forge (relics, per act), the stables (mounts,
  per act), the witch tower (consumables, per act) and the tavern meals. Each
  buy source carries its EquipmentRequirement (county / satisfaction /
  sovereign-tag cost, and the relic material consumed to forge).
- quests.json (already built) reverse map: which quests grant the item
  as a success / failure / unexpected-outcome reward.
- the ink walker's UnlockEquipment/RemoveEquipment calls: which knots hand the
  item out in the story / remove it.

Output shape (dist/inventory.json):
  items:   { "<file stem>": {...} }  — one entry per `.tres` (variants like
           demon_heart_2 are distinct entries sharing a canonical ID)
  stats:   header counts per type, orphan items, etc.

Same stdlib-only / portable-path conventions as quest_data.py. Run standalone:
  python3 inventory_data.py [game_root] [out_path]
or driven by build_app.py (which supplies the quest reward reverse map and the
ink UnlockEquipment/RemoveEquipment knot map).
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GAME_ROOT = (SCRIPT_DIR.parent / "game" / "SovereignTowerCode").resolve()

GAME = str(DEFAULT_GAME_ROOT)
EQUIP_DIR = f"{GAME}/content/equipment"
TSCN_PATH = f"{GAME}/systems/autoloads/game_state.tscn"
OUT_PATH = str(SCRIPT_DIR / "inventory.json")

TYPE_BY_DIR = {
    "relics": "RELIC",
    "mounts": "MOUNT",
    "consumable": "CONSUMABLE",
    "meals": "MEAL",
    "quest_items": "QUEST_ITEM",
}
# Godot omits props equal to their script default; these mirror the .gd defaults.
DEFAULTS = {
    "cost": 20, "bonus_armor": 0, "duration_reduction": 0,
    "is_exclusive": False, "hidden_stats": False, "requires_refreshes": False,
    "has_complex_passive": False,
}

# Mechanical "complex passive" effects. `has_complex_passive` only flags the
# item; what the passive actually does lives in the tag special-cases in
# systems/autoloads/special_cases.gd (score / damage / reward hooks keyed by
# the CharacterTag the item grants). This curated map mirrors those hooks so
# the viewer can explain the passive instead of showing a bare flag.
PASSIVE_NOTES = {
    "WISH_GRANTING_LAMP": "+100 success score on every quest.",
    "DEADLY_WEAPON": "+100 success score on assassination quests.",
    "AMBER_EYE": "+8 success score on quests already completed before.",
    "DEMON_DECOCTION": "+100 success score on quests already completed before.",
    "SADDISTIC": "+1 success score on quests involving killing.",
    "SERRATED_BLADE": "+1 success score on quests involving killing.",
    "GRANNYS_HERBAL_TEA": "+1/−1 success score mirroring the quest's people-satisfaction reward.",
    "FINE_WINE": "+1/−1 success score mirroring the quest's nobles-satisfaction reward.",
    "POTION_OF_FIRE_BREATHING": "+2 damage.",
    "PACK_OF_SERPENT_OIL_VIALS": "Funds rewards scale up with quest duration.",
}

ID_FIELD = {
    "RELICS": "relic_ID", "MOUNT": "mount_ID", "CONSUMABLE": "consumable_ID",
    "MEAL": "meal_ID", "QUEST_ITEM": "id",
}
ID_ENUM = {
    "RELIC": "RelicsID", "MOUNT": "MountsID", "CONSUMABLE": "ConsumableID",
    "MEAL": "MealsID", "QUEST_ITEM": "RelicsID",
}

KV_RE = re.compile(r"^([A-Za-z0-9_/]+) = (.*)$")
EXT_HEADER_RE = re.compile(r'^\[ext_resource type=".*?" path="(.*?)"(?: id="(.*?)")?\]')
SUB_HEADER_RE = re.compile(r'^\[sub_resource type="(.*?)" id="(.*?)"\]')
NODE_HEADER_RE = re.compile(r'^\[node name="([^"]+)"')


def _needs_continuation(val):
    """True when a value has unbalanced brackets (multiline dict/array)."""
    depth, in_str = 0, False
    for ch in val:
        if ch == '"':
            in_str = not in_str
        elif in_str:
            continue
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
    return depth > 0


def set_game(game_root):
    global GAME, EQUIP_DIR, TSCN_PATH
    root = str(Path(game_root).resolve())
    GAME = root
    EQUIP_DIR = f"{root}/content/equipment"
    TSCN_PATH = f"{root}/systems/autoloads/game_state.tscn"


def _init_paths():
    if not EQUIP_DIR:
        set_game(GAME)


# Each enum lookup walks the whole systems/ tree; cache the file texts so all
# enum scans together read every .gd file at most once per process.
_GD_FILE_CACHE = {}


def _gd_text(path):
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    hit = _GD_FILE_CACHE.get(path)
    if hit is not None and hit[0] == sig:
        return hit[1]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    _GD_FILE_CACHE[path] = (sig, text)
    return text


def load_gd_enum(name):
    """Find `enum Name {...}` in the game scripts (mirrors quest_data.load_gd_enum)."""
    target = re.compile(r"enum\s+" + re.escape(name) + r"\s*\{(.*?)\}", re.S)
    for root, _, files in os.walk(f"{GAME}/systems"):
        for fn in files:
            if not fn.endswith(".gd"):
                continue
            text = _gd_text(os.path.join(root, fn))
            m = target.search(text)
            if not m:
                continue
            body = re.sub(r"//.*", "", m.group(1))
            entries = []
            next_val = 0
            for raw in body.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                if "=" in raw:
                    name_, val = raw.split("=", 1)
                    val = int(val.strip())
                    next_val = val + 1
                else:
                    name_, val = raw, next_val
                    next_val += 1
                entries.append((name_.strip(), val))
            return entries
    return None


# --------------------------------------------------------------------------
# Godot text-value parsing (self-contained, tolerant of Godot's omission of
# default properties). Dicts come back as [{key, value}] pairs; refs as
# {"_ext": id} / {"_sub": id} so callers can resolve them against the tables.
# --------------------------------------------------------------------------
def _split_top(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def parse_value(val):
    val = val.strip()
    m = re.match(r'^(ExtResource|SubResource)\("([^"]+)"\)$', val)
    if m:
        return {("_ext" if m.group(1) == "ExtResource" else "_sub"): m.group(2)}
    if val.startswith('&"'):
        return val[2:-1] if val.endswith('"') else val[1:]
    if val.startswith('"'):
        return val[1:-1].replace('\\"', '"') if val.endswith('"') and len(val) >= 2 else val
    if val in ("true", "false"):
        return val == "true"
    if val == "null":
        return None
    if val.lstrip("-").isdigit():
        return int(val)
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1]
        if not inner.strip():
            return []
        return [parse_value(x) for x in _split_top(inner)]
    if val.startswith("{"):
        inner = val[1:-1]
        out = []
        for entry in _split_top(inner):
            if ":" not in entry:
                continue
            k, v = entry.split(":", 1)
            out.append({"key": parse_value(k.strip()), "value": parse_value(v.strip())})
        return out
    return val


class TscnReader:
    """Reads a Godot .tscn: ext_resource table, sub_resource table and the
    per-node property blocks (raw text lines, resolved lazily)."""

    def __init__(self, path):
        self.ext = {}   # id -> path
        self.sub = {}   # id -> {props}
        self.nodes = {}  # name -> [(key, raw_value)]
        lines = open(path, encoding="utf-8").read().splitlines()
        cur_sub = None
        cur_node = None
        i = 0
        n = len(lines)
        while i < n:
            s = lines[i].strip()
            i += 1
            if not s:
                continue
            if s.startswith("[ext_resource"):
                m = EXT_HEADER_RE.match(s)
                if m:
                    self.ext[m.group(2) or m.group(1)] = m.group(1)
                    cur_sub = cur_node = None
                continue
            if s.startswith("[sub_resource"):
                m = SUB_HEADER_RE.match(s)
                if m:
                    self.sub[m.group(2)] = {"type": m.group(1), "props": {}}
                    cur_sub = m.group(2)
                    cur_node = None
                continue
            if s.startswith("[node "):
                m = NODE_HEADER_RE.match(s)
                if m:
                    self.nodes[m.group(1)] = []
                    cur_node = m.group(1)
                cur_sub = None
                continue
            m = KV_RE.match(s)
            if not m:
                continue
            rawval = m.group(2).strip()
            while _needs_continuation(rawval) and i < n:
                rawval += "\n" + lines[i].strip()
                i += 1
            if cur_sub is not None:
                self.sub[cur_sub]["props"][m.group(1)] = rawval
            elif cur_node is not None:
                self.nodes[cur_node].append((m.group(1), rawval))

    def sub_props(self, ident):
        sub = self.sub.get(ident)
        if not sub:
            return {}
        return {k: parse_value(v) for k, v in sub["props"].items()}

    def node_props(self, name):
        props = {}
        for k, raw in self.nodes.get(name, []):
            props[k] = parse_value(raw)
        return props

    def ext_stem(self, ref):
        if not isinstance(ref, dict) or "_ext" not in ref:
            return None
        path = self.ext.get(ref["_ext"])
        if not path:
            return None
        stem = os.path.basename(path)
        if stem.endswith(".tres"):
            stem = stem[:-5]
        return stem


def parse_req(props):
    """Decode an EquipmentRequirement resource into a readable dict.

    Types: None(0) / County(1) / Satisfaction(2) / SovereignTag(3).
    The `item` field is a Relic.RelicsID number (a material consumed to forge).
    """
    if not props:
        return None
    req = {}
    t = props.get("type", 0)
    if props.get("item"):
        req["item"] = props["item"]
    if t == 1:
        req["county"] = props.get("county_id", "")
    elif t == 2:
        req["pop"] = props.get("population_category", 0)
        if props.get("amount"):
            req["amount"] = props["amount"]
    elif t == 3:
        req["stag"] = props.get("sovereign_tag", 0)
        if props.get("amount"):
            req["amount"] = props["amount"]
    if not req:
        req["none"] = True
    return req


def load_equipment():
    """Parse every equipment .tres into items keyed by file stem."""
    items = {}
    for sub in sorted(TYPE_BY_DIR):
        d = os.path.join(EQUIP_DIR, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".tres"):
                continue
            stem = os.path.splitext(fn)[0]
            path = os.path.join(d, fn)
            P = {}
            in_res = False
            lines = open(path, encoding="utf-8").read().splitlines()
            i, n = 0, len(lines)
            while i < n:
                s = lines[i].strip()
                i += 1
                if s == "[resource]":
                    in_res = True
                    continue
                if not in_res or s.startswith("[") or s.startswith("metadata"):
                    continue
                m = KV_RE.match(s)
                if not m:
                    continue
                rawval = m.group(2).strip()
                while _needs_continuation(rawval) and i < n:
                    rawval += "\n" + lines[i].strip()
                    i += 1
                P[m.group(1)] = parse_value(rawval)
            etype = TYPE_BY_DIR[sub]
            st = P.get("statistics_value", [])
            stats = [0, 0, 0, 0, 0, 0]
            for entry in st:
                if isinstance(entry, dict):
                    k, v = entry.get("key"), entry.get("value")
                    if isinstance(k, int) and k < 6 and isinstance(v, int):
                        stats[k] = v
            item = {
                "type": etype,
                "n": P.get("name", ""),
                "d": P.get("description", ""),
                "st": stats,
                "tags": P.get("tags", []) or [],
                "cost": P.get("cost", DEFAULTS["cost"]),
                "ba": P.get("bonus_armor", DEFAULTS["bonus_armor"]),
                "dr": P.get("duration_reduction", DEFAULTS["duration_reduction"]),
                "ex": P.get("is_exclusive", DEFAULTS["is_exclusive"]),
                "hs": P.get("hidden_stats", DEFAULTS["hidden_stats"]),
                "cp": P.get("has_complex_passive", DEFAULTS["has_complex_passive"]),
                "rr": P.get("requires_refreshes", DEFAULTS["requires_refreshes"]),
                "nu": P.get("nb_utilisation", 1) if etype == "CONSUMABLE" else 0,
                "src": {"forge": [], "stables": [], "witch": [], "quests": [],
                        "meals": False, "starting": False,
                        "ink_unlock": [], "ink_remove": [], "consumed_by": []},
            }
            fields = {"key": {"RELIC": "relic_ID", "MOUNT": "mount_ID", "CONSUMABLE": "consumable_ID",
                              "MEAL": "meal_ID", "QUEST_ITEM": "id"},
                      "enum": {"RELIC": "RelicsID", "MOUNT": "MountsID", "CONSUMABLE": "ConsumableID",
                               "MEAL": "MealsID", "QUEST_ITEM": "RelicsID"}}
            fkey, ekey = fields["key"][etype], fields["enum"][etype]
            iid = P.get(fkey)
            item["cid"] = ENUMS_TABLE[ekey].get(iid, item.get("n", stem)) if ENUMS_TABLE.get(ekey) else item.get("n", stem)
            if item["cp"]:
                char_tags = ENUMS_TABLE.get("CharacterTags", {})
                psv = []
                for t in item["tags"]:
                    note = PASSIVE_NOTES.get(char_tags.get(t, ""))
                    if note:
                        psv.append({"tag": char_tags.get(t, t), "note": note})
                if psv:
                    item["psv"] = psv
            items[stem] = item
    return items


ENUMS_TABLE = {}


def load_shop_sources(items, enums):
    """Attach forge / stables / witch / meals / starting sources from game_state.tscn."""
    set_game(GAME)
    if not os.path.exists(TSCN_PATH):
        return
    rdr = TscnReader(TSCN_PATH)
    inv = rdr.node_props("InventoryManager")
    req_tables = {
        "forge": (inv.get("forge_relics"), inv.get("forge_relics_act_2"), inv.get("forge_relics_act_3")),
        "stables": (inv.get("stables_mounts"), inv.get("stables_mounts_act_2"), inv.get("stables_mounts_act_3")),
        "witch": (inv.get("witch_tower_consumables"), inv.get("witch_tower_consumables_act_2"), inv.get("witch_tower_consumables_act_3")),
    }
    for shop, acts in req_tables.items():
        for act, table in enumerate(acts, start=1):
            if not isinstance(table, list):
                continue
            for entry in table:
                if not isinstance(entry, dict):
                    continue
                stem = rdr.ext_stem(entry.get("key"))
                if not stem or stem not in items:
                    continue
                subid = entry.get("value")
                req = None
                if isinstance(subid, dict) and "_sub" in subid:
                    req = parse_req(rdr.sub_props(subid["_sub"]))
                    if req and req.get("item") is not None:
                        req["item"] = enums.get("RelicsID", {}).get(req["item"], req["item"])
                items[stem]["src"][shop].append([act, req])
    meals = inv.get("available_meals") or []
    for ref in meals:
        stem = rdr.ext_stem(ref)
        if stem in items:
            items[stem]["src"]["meals"] = True
    for key in ("starting_relics", "starting_mounts", "starting_consumables"):
        for ref in inv.get(key) or []:
            stem = rdr.ext_stem(ref)
            if stem in items:
                items[stem]["src"]["starting"] = True


def attach_consumed_by(items):
    """Reverse map: which crafted items consume each item as a material.

    Shop requirements carry a `item` field (a Relic.RelicsID material consumed
    to craft/forge, e.g. forging DEMONIC_SWORD consumes DEMON_HEART and the witch
    tower consumes DEMON_HEART for DEMON_DECOCTION). Each material item gets a
    `consumed_by` list so the viewer can show "Consumed by" links on the item
    (the same reverse-linking pattern as the quest / ink source maps).
    """
    by_cid = {}
    for stem, it in items.items():
        by_cid.setdefault(it["cid"], []).append(stem)
    seen = set()
    for stem, it in items.items():
        for shop in ("forge", "stables", "witch"):
            for act, req in it["src"][shop]:
                if not req or not req.get("item"):
                    continue
                for mstem in by_cid.get(req["item"], []):
                    key = (mstem, stem, shop, act)
                    if key in seen:
                        continue
                    seen.add(key)
                    items[mstem]["src"]["consumed_by"].append(
                        {"by": stem, "shop": shop, "act": act})
    for it in items.values():
        it["src"]["consumed_by"].sort(key=lambda c: (c["shop"], c["act"], c["by"]))


def attach_quest_sources(items, quests_data):
    """Reverse map: which quests grant each item as a success/failure/unexp reward."""
    if not quests_data:
        return 0
    rev = {}
    for qid, q in quests_data.get("quests", {}).items():
        for rw in list(q.get("rw", {}).get("s", [])) + list(q.get("rw", {}).get("f", [])):
            stem = rw.get("item_stem")
            if stem:
                rev.setdefault(stem, set()).add(qid)
        for uo in q.get("un", []):
            for rw in uo.get("rw", []):
                stem = rw.get("item_stem")
                if stem:
                    rev.setdefault(stem, set()).add(qid)
    n = 0
    for stem, qset in rev.items():
        if stem in items:
            items[stem]["src"]["quests"] = sorted(qset)
            n += 1
    return n


def attach_ink_sources(items, unlock_map, remove_map):
    """Attach ink knots that UnlockEquipment / RemoveEquipment the item."""
    def fit(map_, key, target):
        for canon, knots in map_.items():
            if canon.upper() == key:
                target.extend(sorted(knots))
    for stem, it in items.items():
        key = it["cid"].upper()
        fit(unlock_map, key, it["src"]["ink_unlock"])
        fit(remove_map, key, it["src"]["ink_remove"])
    return sum(1 for it in items.values() if it["src"]["ink_unlock"])


def load_inventory(quests_data=None, unlock_map=None, remove_map=None, game_root=None):
    """Full catalog build. `quests_data` is the dict from quest_data.load_quests();
    `unlock_map`/`remove_map` are {canonical-ID-upper: [knots]} from the ink walker.
    `game_root` = resolved game project path (defaults to module default)."""
    _init_paths()
    if game_root is not None:
        set_game(game_root)
    global ENUMS_TABLE
    enums = {}
    for name in ("RelicsID", "MountsID", "ConsumableID", "MealsID",
                 "Statistics", "CharacterTags", "SovereignTags", "Population"):
        entries = load_gd_enum(name) or []
        enums[name] = {v: n for n, v in entries}
    ENUMS_TABLE = enums

    items = load_equipment()
    load_shop_sources(items, enums)
    attach_consumed_by(items)
    quest_granted = attach_quest_sources(items, quests_data)
    ink_unlocked = attach_ink_sources(items, unlock_map or {}, remove_map or {})

    by_type = {}
    for it in items.values():
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    no_src = [stem for stem, it in items.items()
              if not (it["src"]["forge"] or it["src"]["stables"] or it["src"]["witch"]
                      or it["src"]["meals"] or it["src"]["starting"]
                      or it["src"]["quests"] or it["src"]["ink_unlock"])]

    stats = {
        "items": len(items),
        "by_type": by_type,
        "quest_granted": quest_granted,
        "ink_unlocked": ink_unlocked,
        "no_source": len(no_src),
    }
    return {"items": items, "enums": {k: v for k, v in enums.items()},
            "stats": stats, "no_source_stems": no_src}


def ink_equip_maps(index):
    """From dist/index.json, collect {canonical-ID-upper: [knots]} for the
    UnlockEquipment / RemoveEquipment story-instruction calls."""
    unlock, remove = {}, {}
    if not index or "knots" not in index:
        return unlock, remove
    for name, k in index["knots"].items():
        for t in k.get("lines", []):
            if t[0] != "3" or t[1] not in ("UnlockEquipment", "RemoveEquipment"):
                continue
            args = t[2] or []
            if len(args) < 2 or not isinstance(args[1], str):
                continue
            canon = args[1].upper()
            (remove if t[1] == "RemoveEquipment" else unlock).setdefault(canon, set()).add(name)
    return {k: sorted(v) for k, v in unlock.items()}, {k: sorted(v) for k, v in remove.items()}


def main(argv=None):
    args = list(sys.argv[1:]) if argv is None else list(argv)
    game_arg = args[0] if len(args) > 0 else os.environ.get("GAME_ROOT", "")
    out_arg = args[1] if len(args) > 1 else os.environ.get("INV_OUT", "")

    def coerce(p, default):
        return default if not p else Path(p).expanduser().resolve()

    game_root = coerce(game_arg, Path(DEFAULT_GAME_ROOT))
    set_game(game_root)
    out_dir = coerce(out_arg, Path(OUT_PATH)).parent
    # reuse the already-built quest + ink catalogs for the reverse maps
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
    unlock, remove = ink_equip_maps(index)
    data = load_inventory(quests_data=quests_data, unlock_map=unlock, remove_map=remove, game_root=game_root)
    out = coerce(out_arg, Path(OUT_PATH))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"Wrote {out}: {stats_text(data['stats'])}")


def stats_text(stats):
    by = ", ".join(f"{k}: {v}" for k, v in sorted(stats["by_type"].items()))
    return (f"{stats['items']} items ({by}) · {stats['quest_granted']} quest-linked · "
            f"{stats['ink_unlocked']} ink-unlocked · {stats['no_source']} with no source")


if __name__ == "__main__":
    main()
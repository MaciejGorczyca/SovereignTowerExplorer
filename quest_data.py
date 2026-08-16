import json
import os
import re
import sys
import csv
from pathlib import Path

# Portable defaults derived from this script's own location (no hardcoded
# /app paths). Any of these can be overridden via CLI args, environment
# variables (GAME_ROOT / QUEST_OUT) or viewer.env — see resolve_paths().
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_ENV_FILE = SCRIPT_DIR / "viewer.env"

DEFAULT_GAME_ROOT = (SCRIPT_DIR.parent / "game" / "SovereignTowerCode").resolve()
DEFAULT_QUEST_OUT = (SCRIPT_DIR / "dist" / "quests.json").resolve()

GAME = str(DEFAULT_GAME_ROOT)
QUEST_DIR = f"{GAME}/content/quests"
AUDIENCE_DIR = f"{GAME}/content/audiences"
QUEST_OUT = str(DEFAULT_QUEST_OUT)

OBJ_PROPERTY = re.compile(r"^([A-Za-z0-9_]+) = ((?:ExtResource|SubResource)\(\"(.*?)\"\))$")
KV_PROPERTY = re.compile(r"^([A-Za-z0-9_]+) = (.*)$")
CHAR_MAP = {"&": "", "'": '"'}

# Per-process caches for the expensive, pure file reads below. The game tree is
# re-read by every data pass in a build (and repeatedly by the test suite); on
# a slow filesystem that I/O dominates wall time. Keying on the resolved path +
# mtime/size keeps the cache correct if the game files ever change mid-process.
_TRES_CACHE = {}
_ENUM_CACHE = {}


def _tres_signature(path):
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)

EXT_HEADER = re.compile(r"^\[ext_resource type=\"(.*?)\" path=\"(.*?)\"(?: id=\"(.*?)\")?\]")
SUB_HEADER = re.compile(r"^\[sub_resource type=\"(.*?)\" id=\"(.*?)\"\]")
SEC_HEADER = re.compile(r"^\[(object|resource)\]")


def load_config() -> dict:
    """Read optional KEY=VALUE viewer.env next to this script (no-op if absent)."""
    cfg = {}
    try:
        text = CONFIG_ENV_FILE.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return cfg
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        cfg[key.strip().upper()] = val.strip().strip('"').strip("'")
    return cfg


def resolve_paths(argv: list = None) -> tuple:
    """Resolve (game_root, quest_out) with this priority (higher wins):
    1. CLI arguments   python3 quest_data.py <game_root> [quest_out]
    2. Environment     GAME_ROOT, QUEST_OUT
    3. viewer.env      GAME_ROOT=..., QUEST_OUT=...
    4. Portable default  <script>.parent.parent/game/SovereignTowerCode, ./dist/quests.json
    """
    cfg = load_config()
    args = list(sys.argv[1:]) if argv is None else list(argv)
    game_arg = args[0] if len(args) > 0 else ""
    out_arg = args[1] if len(args) > 1 else ""

    def pick(arg, env_key):
        if arg:
            return arg
        return os.environ.get(env_key) or cfg.get(env_key) or ""

    game_root = pick(game_arg, "GAME_ROOT")
    quest_out = pick(out_arg, "QUEST_OUT")

    def coerce(p, default):
        if not p:
            return default
        return Path(p).expanduser().resolve()

    return (
        coerce(game_root, DEFAULT_GAME_ROOT),
        coerce(quest_out, DEFAULT_QUEST_OUT),
    )


def set_game(game_root):
    """Point the module-level GAME/QUEST_DIR globals at a given game root.

    Kept callable at import time so build_app.py can share the same resolved
    root without duplicating the resolution logic here in quest_data.py.
    """
    global GAME, QUEST_DIR
    root = str(Path(game_root).resolve())
    if root == GAME:
        return
    GAME = root
    QUEST_DIR = f"{root}/content/quests"


ENUM_ALIASES = {"Population": "PopulationCategory"}

# Every enum lookup walks the whole systems/ tree; cache each .gd file's text
# so the N enum scans (quest/inventory/knights all call this) read every file
# at most once per process. Keyed on path + mtime/size like _TRES_CACHE.
_GD_FILE_CACHE = {}


def _gd_text(path):
    sig = _tres_signature(path)
    hit = _GD_FILE_CACHE.get(path)
    if hit is not None and hit[0] == sig:
        return hit[1]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    _GD_FILE_CACHE[path] = (sig, text)
    return text


def load_gd_enum(name: str):
    key = (GAME, name)
    if key in _ENUM_CACHE:
        return _ENUM_CACHE[key]
    search_name = ENUM_ALIASES.get(name, name)
    target = re.compile(r"enum\s+" + re.escape(search_name) + r"\s*\{(.*?)\}", re.S)
    for root, _, files in os.walk(f"{GAME}/systems"):
        for fn in files:
            if not fn.endswith(".gd"):
                continue
            text = _gd_text(os.path.join(root, fn))
            m = target.search(text)
            if m:
                break
        else:
            continue
        break
    else:
        _ENUM_CACHE[key] = None
        return None
    body = m.group(1)
    entries = []
    next_val = 0
    for raw in body.split(","):
        raw = raw.strip()
        if not raw or raw.startswith("//"):
            continue
        raw = re.sub(r"//.*", "", raw)
        if "=" in raw:
            name_, val = raw.split("=", 1)
            val = int(val.strip())
            next_val = val + 1
        else:
            name_, val = raw, next_val
            next_val += 1
        entries.append((name_.strip(), val))
    _ENUM_CACHE[key] = entries
    return entries


class TresFile:
    @classmethod
    def load(cls, path: str, base_dir: str = None):
        """Parse a .tres file from disk, cached per path+mtime/size.

        All data passes parse the same files repeatedly (quests, inventory,
        knights, audiences all re-read the game tree); on slow filesystems the
        repeated reads+parses dominate wall time. Caching the parsed object at
        this leaf level is safe because no caller mutates a parsed TresFile.
        """
        key = os.path.abspath(path)
        sig = _tres_signature(key)
        hit = _TRES_CACHE.get(key)
        if hit is not None and hit[0] == sig:
            return hit[1]
        with open(key, encoding="utf-8") as f:
            obj = cls(f.read(), base_dir if base_dir is not None else os.path.dirname(key))
        if len(_TRES_CACHE) >= 4096:
            _TRES_CACHE.clear()
        _TRES_CACHE[key] = (sig, obj)
        return obj
    def __init__(self, text: str, base_dir: str):
        self.text = text
        self.base_dir = base_dir
        self.ext = {}  # id -> path
        self.sub = {}  # id -> {type, props}
        self.props = {}
        self.obj = []  # [ext_id | None, type, props]
        self._parse()

    def _parse(self):
        cur = None
        in_block = False
        last_sub_type = None
        block_type = None
        block_props = {}
        block_key = None
        lines = self.text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            if line.startswith("["):
                m = EXT_HEADER.match(line)
                if m:
                    self.ext[m.group(3) or m.group(2)] = m.group(2)
                    in_block = False
                    block_key = None
                    i += 1
                    continue
                m = SUB_HEADER.match(line)
                if m:
                    self.sub[m.group(2)] = {"type": m.group(1), "props": {}}
                    in_block = True
                    block_key = m.group(2)
                    block_type = m.group(1)
                    i += 1
                    continue
                if SEC_HEADER.match(line):
                    in_block = False
                    block_key = None
                    i += 1
                    continue
                i += 1
                continue
            m = KV_PROPERTY.match(line)
            if not m:
                i += 1
                continue
            key = m.group(1)
            val = m.group(2).strip()
            while self._needs_continuation(val) and i + 1 < len(lines):
                i += 1
                val += "\n" + lines[i].strip()
            parsed = self._parse_value(val)
            if in_block:
                self.sub[block_key]["props"][key] = parsed
            else:
                self.props[key] = parsed
            i += 1
        if block_type is not None:
            self.obj.append([None, block_type, block_props])

    @staticmethod
    def _needs_continuation(val):
        depth = 0
        in_str = False
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

    def _ref(self, text, ref_id):
        if text.startswith("ExtResource"):
            return {"_ext": ref_id}
        if text.startswith("SubResource"):
            return {"_sub": ref_id}
        return text

    def _parse_value(self, val):
        val = val.strip()
        m = re.match(r'^(ExtResource|SubResource)\("([^"]+)"\)$', val)
        if m:
            return {("_ext" if m.group(1) == "ExtResource" else "_sub"): m.group(2)}
        if val.startswith('&"') or val.startswith('"'):
            quote = '"'
            if val.startswith('&"'):
                val = val[1:]
            if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                return val[1:-1].replace('\\"', '"')
            return val
        if val in ("true", "false"):
            return val == "true"
        if val.isdigit():
            return int(val)
        if val.lstrip("-").isdigit():
            return int(val)
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            if not inner.strip():
                return []
            return [self._parse_value(x) for x in self._split_top(inner)]
        if val.startswith("{"):
            inner = val[1:-1]
            result = []
            for entry in self._split_top(inner):
                if ":" not in entry:
                    continue
                k, v = entry.split(":", 1)
                k = k.strip()
                result.append(
                    {
                        "key": int(k) if k.isdigit() else k,
                        "value": self._parse_value(v.strip()),
                    }
                )
            return result
        return val

    @staticmethod
    def _split_top(s):
        out = []
        depth = 0
        cur = ""
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

    def ext_path(self, ref):
        return self.ext.get(ref)

    def sub_props(self, ref):
        sub = self.sub.get(ref)
        if not sub:
            return {}
        props = dict(sub["props"])
        props["_type"] = sub["type"]
        return props


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_int_range(filer, ref):
    """Resolve an IntRange (min/max ints) from a _sub/_ext reference.

    Godot omits properties equal to their script default, so a stored IntRange
    with only `max = 2` still means {min: 0, max: 2} (IntRange defaults 0..10).
    Returns [min, max] or None when the reference is absent/unresolvable.
    """
    if not isinstance(ref, dict):
        return None
    if "_sub" in ref:
        props = filer.sub_props(ref["_sub"])
        return [int(props.get("min", 0)), int(props.get("max", 10))]
    if "_ext" in ref:
        p = filer.ext_path(ref["_ext"])
        if not p:
            return None
        if p.startswith("res://"):
            p = p[6:]
        if not p.startswith("/"):
            p = os.path.join(GAME, p)
        if not os.path.exists(p):
            return None
        extf = TresFile.load(p, os.path.dirname(p))
        return [int(extf.props.get("min", 0)), int(extf.props.get("max", 10))]
    return None


def resolve_sub(item, quest_file):
    if not isinstance(item, dict) or "_sub" not in item:
        return item
    props = quest_file.sub_props(item["_sub"])
    out = {}
    for k, v in props.items():
        if isinstance(v, dict) and "_ext" in v:
            v = {"_path": quest_file.ext_path(v["_ext"])}
        elif isinstance(v, list):
            v = [resolve_sub(x, quest_file) for x in v]
        elif isinstance(v, dict) and "key" in v:
            v = {
                "key": v["key"],
                "value": resolve_sub(v["value"], quest_file),
            }
        out[k] = v
    return out


class QuestIndex:
    def __init__(self):
        self.enums = {}
        self.item_stems = {}
        self.char_stems = {}
        self.quest_stems = {}
        self._load_lookup()

    def _load_lookup(self):
        for name in [
            "QuestTypes",
            "QuestTags",
            "ConditionTags",
            "QuestOutcomes",
            "Statistics",
            "RewardType",
            "Population",
            "LocationsID",
            "SovereignTags",
            "CharacterTags",
        ]:
            self.enums[name] = load_gd_enum(name) or []

        def _stem(p):
            return os.path.splitext(os.path.basename(p))[0]

        for root, _, files in os.walk(f"{GAME}/content/equipment"):
            for fn in files:
                if not fn.endswith(".tres"):
                    continue
                p = os.path.join(root, fn)
                t = TresFile.load(p, root)
                if "name" in t.props:
                    self.item_stems[_stem(p)] = t.props["name"]
        for root, _, files in os.walk(f"{GAME}/content/audience_requests"):
            for fn in files:
                if not fn.endswith(".tres"):
                    continue
                p = os.path.join(root, fn)
                t = TresFile.load(p, root)
                if "request_name" in t.props:
                    self.item_stems[_stem(p)] = t.props["request_name"]
        for fn in os.listdir(f"{GAME}/content/equipment/quest_items"):
            if not fn.endswith(".tres"):
                continue
            p = f"{GAME}/content/equipment/quest_items/{fn}"
            t = TresFile.load(p, GAME)
            if "name" in t.props:
                self.item_stems[_stem(p)] = t.props["name"]
        for root, _, files in os.walk(f"{GAME}/content/character_descriptors"):
            for fn in files:
                if not fn.endswith(".tres"):
                    continue
                p = os.path.join(root, fn)
                t = TresFile.load(p, root)
                if "name" in t.props:
                    self.char_stems[_stem(p)] = t.props["name"]
        for fn in os.listdir(QUEST_DIR):
            if not fn.endswith(".tres"):
                continue
            self.quest_stems[os.path.splitext(fn)[0]] = fn


def resolve_quest_ref(ref, quest_file):
    if isinstance(ref, dict):
        if "_path" in ref:
            path = ref["_path"]
            if path.startswith("res://"):
                path = path[6:]
            norm = os.path.basename(os.path.splitext(path)[0])
            return norm
        ref = ref.get("_ext")
    path = quest_file.ext_path(ref)
    if not path:
        return None
    if path.startswith("res://"):
        path = path[6:]
    norm = path
    if norm.endswith(".tres"):
        norm = norm[:-5]
    return norm


TAG_LIBRARY_TSNC = "systems/autoloads/tag_library.tscn"


def load_tag_library():
    """Parse tag_library.tscn -> the game's efficiency tag map.

    Returns (quest_tag_map, condition_tag_map): each maps an enum value to
    {"e": [efficient CharacterTag values], "i": [inefficient CharacterTag
    values]}. The scene defines, per quest category (QuestTags) and per quest
    condition (ConditionTags), which character tags make a knight efficient
    (or inefficient) at the job. This is the "who is good for what" data —
    distinct from preferences, which say who *likes* what.
    """
    path = os.path.join(GAME, TAG_LIBRARY_TSNC)
    qt, ct = {}, {}
    if not os.path.exists(path):
        return qt, ct
    text = open(path, encoding="utf-8").read()
    for block in re.split(r"(?m)^\[node ", text):
        if not block:
            continue
        header, _, body = block.partition("\n")
        if 'type="Node"' not in header:
            continue
        mp = re.search(r'parent="([^"]+)"', header)
        mn = re.search(r'name="([^"]+)"', header)
        if not mp or not mn:
            continue
        parent, node_name = mp.group(1), mn.group(1)
        if parent not in ("QuestTags", "ConditionsTags"):
            continue
        props = {}
        for pm in re.finditer(r"(?m)^([A-Za-z_]+)\s*=\s*(.+)$", body):
            props[pm.group(1)] = pm.group(2).strip()
        is_quest = parent == "QuestTags"

        def ints(s):
            s = (s or "").strip()
            if s.startswith("["):
                s = s[1:]
            if s.endswith("]"):
                s = s[:-1]
            return [int(x.strip()) for x in s.split(",") if x.strip()]

        raw = props.get("quest_tag" if is_quest else "condition_tag")
        key = int(raw) if raw is not None and str(raw).lstrip("-").isdigit() else 0
        entry = {
            "e": ints(props.get("efficient_character_tags")),
            "i": ints(props.get("inefficient_character_tags")),
        }
        (qt if is_quest else ct)[key] = entry
    return qt, ct


# AudienceRequirement.Types values (see audience_requirement.gd)
REQ_KNIGHT_AT_ROUNDTABLE = 0
REQ_KNIGHT_DEAD = 1
REQ_KNIGHT_ABSENT_FROM_ROUNDTABLE = 2
REQ_VARIABLE_CHECK = 3
REQ_AUDIENCE_PLAYED = 4

REQ_TAGS = {
    REQ_KNIGHT_AT_ROUNDTABLE: "KAT",
    REQ_KNIGHT_DEAD: "KDEAD",
    REQ_KNIGHT_ABSENT_FROM_ROUNDTABLE: "KABS",
    REQ_VARIABLE_CHECK: "VAR",
    REQ_AUDIENCE_PLAYED: "APLAY",
}


def _ref_stem(ref, filer):
    """Resolve an ExtResource/SubResource ref to its file stem (or raw id)."""
    p = filer.ext_path(ref.get("_ext")) if isinstance(ref, dict) and "_ext" in ref else None
    if not p:
        return None
    if p.startswith("res://"):
        p = p[6:]
    return os.path.splitext(os.path.basename(p))[0]


def load_cycle_schedule():
    """Parse content/cycles/cycle_*.tres -> {audience stem: [cycle indexes]}.

    The cycle resources hard-code which narrated scenes play at which cycle
    (e.g. scriptedquest_assassination_attempt is placed in cycle_7), which is
    the "fires on a specific cycle" information for scripted events.
    """
    out = {}
    d = f"{GAME}/content/cycles"
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        m = re.match(r"cycle_(\d+)\.tres", fn)
        if not m:
            continue
        cidx = int(m.group(1))
        tf = TresFile.load(os.path.join(d, fn), d)
        for a in tf.props.get("audiences", []):
            stem = _ref_stem(a, tf)
            if stem:
                out.setdefault(stem, []).append(cidx)
    return out


def _decode_requirements(filer, idx, reqs):
    """Decode an Audience's `requirements` (list of AudienceRequirement
    sub-resources) into compact JSON lists for the frontend:

        ["KAT",  <knight name key>]   knight is at the roundtable
        ["KDEAD", <knight name key>]  knight is dead
        ["KABS", <knight name key>]   knight absent from the roundtable
        ["VAR", <var>, <checked>]     story var equals <checked>
        ["APLAY", <audience stem>]    the referenced audience not played yet
    """
    out = []
    for r in reqs or []:
        if not isinstance(r, dict) or "_sub" not in r:
            continue
        props = filer.sub_props(r["_sub"])
        rtype = props.get("type", REQ_KNIGHT_AT_ROUNDTABLE)
        if rtype == REQ_VARIABLE_CHECK:
            out.append(["VAR", props.get("variable_name", ""), bool(props.get("checked", True))])
        elif rtype == REQ_AUDIENCE_PLAYED:
            stem = _ref_stem(props.get("audience"), filer)
            out.append(["APLAY", stem])
        else:
            stem = _ref_stem(props.get("knight"), filer)
            key = idx.char_stems.get(stem) or stem
            out.append([REQ_TAGS.get(rtype, "KAT"), key])
    return out


def load_audience_catalog(idx):
    """Walk content/audiences/** and build the full audience catalog.

    Each audience resource becomes {k: ink_path, f: folder, c: [char name
    keys], rq: [decoded requirements]} — the reverse lookup the knot drawer
    needs ("how does this knot fire, and under what conditions?").
    """
    catalog = {}
    if not os.path.isdir(AUDIENCE_DIR):
        return catalog
    cycles = load_cycle_schedule()
    for root, _, files in os.walk(AUDIENCE_DIR):
        for fn in sorted(files):
            if not fn.endswith(".tres"):
                continue
            path = os.path.join(root, fn)
            tf = TresFile.load(path, root)
            chars = []
            for c in tf.props.get("characters", []):
                stem = _ref_stem(c, tf)
                chars.append(idx.char_stems.get(stem) or stem)
            entry = {
                "k": tf.props.get("ink_path", ""),
                "f": os.path.basename(root),
                "c": [c for c in chars if c],
            }
            cyc = cycles.get(os.path.splitext(fn)[0])
            if cyc:
                entry["cyc"] = sorted(cyc)
            reqs = _decode_requirements(tf, idx, tf.props.get("requirements", []))
            if reqs:
                entry["rq"] = reqs
            catalog[os.path.splitext(fn)[0]] = entry
    return catalog


def load_quests():
    idx = QuestIndex()

    reward_types = {n: v for n, v in idx.enums["RewardType"]}
    stat_vals = {n: v for n, v in idx.enums["Statistics"]}
    pop_vals = {n: v for n, v in idx.enums["Population"]}
    loc_vals = {n: v for n, v in idx.enums["LocationsID"]}
    st_vals = {n: v for n, v in idx.enums["SovereignTags"]}
    tag_vals = {n: v for n, v in idx.enums["CharacterTags"]}

    quests = {}
    audiences = load_audience_catalog(idx)
    knights = {}
    unlocks = {}
    stats = {"quests": 0, "with_unexpected": 0, "with_follow_up": 0, "audiences": len(audiences)}

    files = sorted(os.listdir(QUEST_DIR))
    for fn in files:
        if not fn.endswith(".tres"):
            continue
        qid = os.path.splitext(fn)[0]
        path = os.path.join(QUEST_DIR, fn)
        tf = TresFile.load(path, QUEST_DIR)
        P = tf.props

        def refname(r):
            if r is None:
                return None
            return os.path.basename(os.path.splitext(r)[0])

        name_key = P.get("quest_name")
        desc_key = P.get("quest_description")
        qtype = P.get("quest_type", 0)
        cat = P.get("quest_category", 0)
        loc = P.get("quest_location", 0)
        cond = P.get("quest_conditions", [])
        reqs = P.get("stats_requirements", [])
        if reqs and isinstance(reqs[0], dict):
            reqs = [[e.get("key"), e.get("value")] for e in reqs]
        dm = resolve_int_range(tf, P.get("quest_damages", {}))
        dur = P.get("duration", 1)
        nb = P.get("nb_requested_knights", 1)
        kill = P.get("involve_killing", False)
        lethal = P.get("quest_can_be_lethal", True)
        deadline = P.get("has_deadline", False)
        auto_fail = P.get("cycles_before_automatic_faillure", 1)
        cut = P.get("has_cutscene", False)
        audience_refs = [refname(resolve_quest_ref(r, tf)) for r in (P.get("success_follow_up_audience"), P.get("failure_follow_up_audience"))]
        unexpected = [x for x in P.get("special_outcomes", []) if x not in (None, "null")]
        mods = [x for x in P.get("modifiers", []) if x not in (None, "null")]
        kn_req = [refname(resolve_quest_ref(r, tf)) for r in P.get("requested_knights", []) if r not in (None, "null")]

        q = {
            "id": qid,
            "n": name_key,
            "d": desc_key,
            "t": qtype,
            "c": cat,
            "l": loc,
            "cd": cond,
            "st": [[k, v] for k, v in reqs],
            "dm": dm if dm else [0, 10],
            "du": dur,
            "nk": nb,
            "kl": kill,
            "lt": lethal,
            "dl": deadline,
            "af": auto_fail,
            "ct": cut,
            "rk": kn_req,
            "rw": {"s": [], "f": []},
            "un": [],
            "fu": audience_refs,
            "mo": [],
        }

        def build_rewards(refs, filer):
            out = []
            for r in refs:
                it = resolve_sub(r, filer)
                rt = it.get("reward_type", reward_types.get("FUNDS", 0))
                ro = {"t": rt}
                if rt == reward_types.get("FUNDS"):
                    ro["a"] = it.get("amount", 0)
                elif rt == reward_types.get("SATISFACTION"):
                    ro["a"] = it.get("amount", 0)
                    ro["p"] = it.get("affected_category", 0)
                elif rt in (reward_types.get("RELIC"), reward_types.get("MOUNT"), reward_types.get("CONSUMABLE"), reward_types.get("QUEST_ITEM")):
                    field = {reward_types.get("RELIC"): "", reward_types.get("MOUNT"): "mount", reward_types.get("CONSUMABLE"): "consumable", reward_types.get("QUEST_ITEM"): "quest_item"}[rt] or "relic"
                    rf = it.get(field)
                    stem = refname(resolve_quest_ref(rf, filer)) if rf else None
                    if stem:
                        ro["item"] = idx.item_stems.get(stem) or stem
                        ro["item_stem"] = stem
                elif rt == reward_types.get("AFFINITY"):
                    ro["a"] = it.get("amount", 0)
                    rf = it.get("affected_knight")
                    stem = refname(resolve_quest_ref(rf, filer)) if rf else None
                    if stem:
                        ro["k"] = stem
                elif rt == reward_types.get("CHARACTER_TAG"):
                    ro["tag"] = it.get("character_tag", 0)
                    ro["u"] = it.get("unknown_tag", False)
                elif rt == reward_types.get("SOVEREIGN_TAG"):
                    ro["a"] = it.get("amount", 0)
                    ro["sg"] = it.get("sovereign_tag", 0)
                elif rt == reward_types.get("AUDIENCE_REQUEST"):
                    rf = it.get("audience_request")
                    stem = refname(resolve_quest_ref(rf, filer)) if rf else None
                    if stem:
                        ro["item"] = idx.item_stems.get(stem) or stem
                        ro["item_stem"] = stem
                    ro["u"] = it.get("unknown_tag", False)
                elif rt == reward_types.get("LOCATION_TAX"):
                    ro["a"] = it.get("amount", 0)
                    ro["loc"] = it.get("location", 0)
                elif rt == reward_types.get("BOOL_STORY_VAR_MODIF"):
                    ro["v"] = it.get("variable_name", "")
                    ro["b"] = it.get("variable_status", False)
                elif rt == reward_types.get("CURRENT_KNIGHT_DEMISSION"):
                    pass
                elif rt == reward_types.get("LOCATION_DESTROYED"):
                    ro["loc"] = it.get("location", 0)
                elif rt == reward_types.get("CHARACTER_DEATH"):
                    rf = it.get("targeted_character")
                    stem = refname(resolve_quest_ref(rf, filer)) if rf else None
                    if stem:
                        ro["item"] = idx.char_stems.get(stem) or stem
                        ro["item_stem"] = stem
                elif rt == reward_types.get("SPECIAL_INSTRUCTION"):
                    ro["v"] = it.get("variable_name", "")
                    ro["e"] = it.get("trigger_early", True)
                else:
                    ro["unknown"] = True
                out.append(ro)
            return out

        q["rw"]["s"] = build_rewards([x for x in P.get("success_rewards", []) if x not in (None, "null")], tf)
        q["rw"]["f"] = build_rewards([x for x in P.get("faillure_consequences", []) if x not in (None, "null")], tf)

        for r in unexpected:
            so_path = tf.ext_path(r["_ext"]) if isinstance(r, dict) and "_ext" in r else None
            if not so_path:
                continue
            if so_path.startswith("res://"):
                so_path = f"{GAME}/{so_path[6:]}"
            ustem = refname(so_path)
            sotf = TresFile.load(so_path, os.path.dirname(so_path))
            SP = sotf.props
            uo = {"id": ustem}
            # Knight condition: the base SpecialOutcome stores it in `knights`,
            # but the per-knight subclasses (Arron/Goberto/Gwendan special
            # outcomes) require a single named knight via their own field
            # (`arron` / `goberto` / `gwendan`) and may omit `knights` entirely
            # (e.g. stop_baby_dragon_arron.tres). Collect both, de-duplicated.
            req_knights = [refname(resolve_quest_ref(x, sotf)) for x in SP.get("knights", []) if x not in (None, "null")]
            for field in ("arron", "goberto", "gwendan"):
                ref = SP.get(field)
                if not ref or ref in (None, "null"):
                    continue
                name = refname(resolve_quest_ref(ref, sotf))
                if name and name not in req_knights:
                    req_knights.append(name)
            if req_knights:
                uo["k"] = req_knights
            if SP.get("required_knight_characteristics"):
                uo["ch"] = SP["required_knight_characteristics"]
            if SP.get("stat") is not None:
                uo["st"] = SP["stat"]
                uo["hi"] = SP.get("requires_higher", True)
                uo["am"] = SP.get("amount", -1)
            if SP.get("rewards"):
                uo["rw"] = build_rewards([x for x in SP["rewards"] if x not in (None, "null")], sotf)
            fu = SP.get("follow_up_audience")
            uo["fu"] = refname(resolve_quest_ref(fu, sotf)) if fu not in (None, "null") else None
            dr = SP.get("damage_range")
            if dr is not None and dr != "null":
                dmv = resolve_int_range(sotf, dr)
                if dmv:
                    uo["dm"] = dmv
            uo["no"] = SP.get("arlin_note") or None
            if SP.get("xp_modifier", 1.5) != 1.5:
                uo["xp"] = SP["xp_modifier"]
            q["un"].append(uo)

        for i, m in enumerate(mods):
            it = resolve_sub(m, tf)
            mo = {}
            if it.get("damage_modification", 0):
                mo["dm"] = it["damage_modification"]
            if it.get("stats_requirements_modification"):
                srm = it["stats_requirements_modification"]
                if srm and isinstance(srm[0], dict):
                    srm = [[e.get("key"), e.get("value")] for e in srm]
                mo["st"] = srm
            if it.get("success_rewards_modification"):
                mo["sr"] = build_rewards([x for x in it["success_rewards_modification"] if x not in (None, "null")], tf)
            if it.get("faillure_consequences_modification"):
                mo["fr"] = build_rewards([x for x in it["faillure_consequences_modification"] if x not in (None, "null")], tf)
            if it.get("nb_requested_knights_modification", 0):
                mo["nk"] = it["nb_requested_knights_modification"]
            if it.get("duration_modification", 0):
                mo["du"] = it["duration_modification"]
            if it.get("arlins_note_success_modification") not in (None, "null"):
                mo["ns"] = it["arlins_note_success_modification"]
            if it.get("arlins_note_failure_modification") not in (None, "null"):
                mo["nf"] = it["arlins_note_failure_modification"]
            if it.get("location_modification") not in (None, loc_vals.get("NONE")):
                mo["lo"] = it["location_modification"]
            if it.get("unexpected_outcomes"):
                mo["un"] = []
                for x in it["unexpected_outcomes"]:
                    so_path = tf.ext_path(x["_ext"]) if isinstance(x, dict) and "_ext" in x else None
                    if so_path and so_path.startswith("res://"):
                        so_path = f"{GAME}/{so_path[6:]}"
                    mo["un"].append(refname(so_path) if so_path else None)
                mo["un"] = [u for u in mo["un"] if u]
                # modifier unexpected outcomes can carry their own follow-up
                # audience (e.g. contract_cleankeeper_goose_part_two's modifier
                # outcomes -> chester_candidacy, which plays candidature_chester).
                un_fu = []
                for x in it["unexpected_outcomes"]:
                    so_path = tf.ext_path(x["_ext"]) if isinstance(x, dict) and "_ext" in x else None
                    if so_path and so_path.startswith("res://"):
                        so_path = f"{GAME}/{so_path[6:]}"
                    if so_path:
                        sotf = TresFile.load(so_path, os.path.dirname(so_path))
                        fu = sotf.props.get("follow_up_audience")
                        if fu:
                            un_fu.append(refname(resolve_quest_ref(fu, sotf)) if fu not in (None, "null") else None)
                un_fu = [u for u in un_fu if u]
                if un_fu:
                    mo["unfu"] = un_fu
            q["mo"].append(mo)
            for iu, ustem in enumerate(mo.get("un", [])):
                unlocks.setdefault(ustem, []).append([qid, i + 1])

        for (ans, anf) in ((P.get("success_follow_up_audience"), P.get("failure_follow_up_audience")),):
            for r in (ans, anf):
                if not r:
                    continue
                if isinstance(r, dict):
                    r = r.get("_ext")
                apath = tf.ext_path(r)
                if not apath:
                    continue
                if apath.startswith("res://"):
                    apath = f"{GAME}/{apath[6:]}"
                stem = refname(apath)
                if stem not in audiences:
                    t = TresFile.load(apath, os.path.dirname(apath))
                    chars = [refname(resolve_quest_ref(c, t)) for c in t.props.get("characters", [])]
                    chars = [idx.char_stems.get(c) or c for c in chars]
                    audiences[stem] = {
                        "k": t.props.get("ink_path", ""),
                        "f": os.path.basename(os.path.dirname(apath)),
                        "c": chars,
                    }

        for k in kn_req:
            if k and k in idx.char_stems:
                knights[k] = idx.char_stems[k]
        for uo in q["un"]:
            for k in uo.get("k", []):
                if k in idx.char_stems:
                    knights[k] = idx.char_stems[k]

        quests[qid] = q
        stats["quests"] += 1
        if q["un"]:
            stats["with_unexpected"] += 1
        if any(q["fu"]):
            stats["with_follow_up"] += 1

    def only_children(d, keep):
        return d

    quests = {k: v for k, v in quests.items() if k in idx.quest_stems}

    qt, ct = load_tag_library()

    out = {
        "enums": {
            k: [[v, n] for n, v in entries]
            for k, entries in idx.enums.items()
        },
        "eff": {"qt": qt, "ct": ct},
        "loc": {},
        "knights": knights,
        "audiences": audiences,
        "quests": quests,
        "unlocks": unlocks,
        "stats": stats,
    }
    return out


def collect_loc_keys(quests):
    keys = set()
    for q in quests.values():
        if q["n"]:
            keys.add(q["n"])
        if q["d"]:
            keys.add(q["d"])
        for rw in (q["rw"]["s"], q["rw"]["f"]):
            for r in rw:
                if r.get("item"):
                    keys.add(r["item"])
        for uo in q["un"]:
            if uo.get("no"):
                keys.add(uo["no"])
        for mo in q["mo"]:
            if mo.get("ns"):
                keys.add(mo["ns"])
            if mo.get("nf"):
                keys.add(mo["nf"])
    for k in list(quests.values())[0:0]:
        pass
    return keys


LOCALES = ["en", "fr", "cmn", "de", "ja", "ko"]


def load_loc(keys):
    """Build {loc_key: {locale: text}} from the game's Godot CSV translation files."""
    loc_groups = [("en_fr", ["en", "fr"]), ("cmn_ja_de_ko", ["en", "cmn", "de", "ja", "ko"])]
    loc = {}
    data_en_seen = {}
    for group, locales in loc_groups:
        for fn in sorted(os.listdir(f"{GAME}/lang/{group}")):
            if not fn.endswith(".csv"):
                continue
            path = f"{GAME}/lang/{group}/{fn}"
            with open(path, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    for col, value in row.items():
                        col = col.strip()
                        if col == "key" or col not in locales or not value:
                            continue
                        if col == "en" and group != "en_fr":
                            if data_en_seen.get(row.get("key")):
                                continue
                            data_en_seen[row.get("key")] = True
                        loc.setdefault(row.get("key"), {})[col] = value
    return loc


def main():
    game_root, quest_out = resolve_paths(sys.argv[1:])
    set_game(game_root)

    out = load_quests()
    keys = collect_loc_keys(out["quests"])
    out["locales"] = LOCALES
    out["loc"] = load_loc(keys)
    out["_meta"] = {
        "note": "Generated by explorer/quest_data.py from SovereignTowerCode/content/quests. No comments intended.",
        "locales_count": len(out["locales"]),
        "loc_keys_count": len(keys),
        "quests_count": len(out["quests"]),
        "audiences_count": len(out["audiences"]),
    }
    quest_out.parent.mkdir(parents=True, exist_ok=True)
    with open(quest_out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"Wrote {quest_out}: {len(out['quests'])} quests, {len(keys)} loc keys, {len(out['audiences'])} audiences")

if __name__ == "__main__":
    main()

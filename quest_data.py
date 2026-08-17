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


def _civil_war_thresholds():
    """Parse cycles_manager.gd's civil-war gate: [(cycle, satisfaction threshold)].

    The director checks the lowest population satisfaction each cycle transition
    but only acts on the cycles in `civil_war_cycle_checks` ({24: 18, 29: 20,
    34: 22} via the const thresholds).
    """
    gd = os.path.join(GAME, "systems/autoloads/cycles_manager.gd")
    if not os.path.exists(gd):
        return []
    text = open(gd, encoding="utf-8").read()
    consts = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"const\s+(CIVIL_WAR_THRESHOLD_VALUE_\w+)\s*=\s*(\d+)", text)
    }
    m = re.search(r"civil_war_cycle_checks\s*=\s*\{(.*?)\}", text, re.S)
    if not m:
        return []
    out = []
    for pm in re.finditer(r"(\d+)\s*:\s*(CIVIL_WAR_THRESHOLD_VALUE_\w+)", m.group(1)):
        if pm.group(2) in consts:
            out.append((int(pm.group(1)), consts[pm.group(2)]))
    return sorted(out)


def load_director_audiences():
    """Parse the CyclesManager "director" audiences -> {audience stem: [notes]}.

    These narrated scenes are scheduled by the game director (the CyclesManager
    node of systems/autoloads/cycles_manager.tscn) rather than by quests, ink
    doleance calls, requests or special instructions:

    - `serpent_knight_audience`            — reset when the story goes back in time
    - `civil_war_{people,nobles,merchants,scholars}` — act-3 population revolts,
      gated by the satisfaction thresholds of cycles_manager.gd
    - `act_{1,2}_endng_audience` + `act_3_ending_audience` — the act-finale
      victory scenes that switch acts
    - `arlin_act_{2,3}_intro`              — scheduled right after the act switch
    - `rupin_audiences`                    — corruption-level-gated grievances

    Values are baked human-readable "Director scene: …" notes (same convention
    as special.json's `cond`), one per audience.
    """
    tscn = os.path.join(GAME, "systems/autoloads/cycles_manager.tscn")
    if not os.path.exists(tscn):
        return {}
    director = {}

    def _stem(path):
        if path.startswith("res://"):
            path = path[6:]
        return os.path.splitext(os.path.basename(path))[0]

    lines = open(tscn, encoding="utf-8").read().splitlines()
    ext = {}
    for m in re.finditer(r'\[ext_resource type="[^"]*"[^]]*path="([^"]+)"[^]]*id="(\d+)"\]',
                         "\n".join(lines)):
        ext[m.group(2)] = _stem(m.group(1))

    start = None
    for i, line in enumerate(lines):
        if line.startswith('[node name="CyclesManager"'):
            start = i + 1
            break
    if start is None:
        return {}
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("["):
            end = i
            break

    props = {}
    i = start
    while i < end:
        line = lines[i].strip()
        m = re.match(r"^([A-Za-z0-9_]+)\s*=\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        j = i + 1
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
        while depth > 0 and j < end:
            val += "\n" + lines[j].strip()
            for ch in lines[j]:
                if ch == '"':
                    in_str = not in_str
                elif in_str:
                    continue
                elif ch in "[{(":
                    depth += 1
                elif ch in "]})":
                    depth -= 1
            j += 1
        props[key] = val
        i = max(j, i + 1)

    def refstem(tok):
        m = re.match(r'ExtResource\("([^"]+)"\)', tok.strip())
        return ext.get(m.group(1)) if m else None

    serp = refstem(props.get("serpent_knight_audience", ""))
    if serp:
        director[serp] = [
            "Director scene: the serpent-knight reset — placed into cycle 0 when "
            "the story returns to the act beginning and re-scheduled on "
            "time-travel while the variable serpent_knight_met is false and no "
            "brimwood trial is ongoing (brimwood_trial_ongoing)."
        ]

    for key, label in (("civil_war_people", "people"), ("civil_war_nobles", "nobles"),
                       ("civil_war_merchants", "merchants"), ("civil_war_scholars", "scholars")):
        stem = refstem(props.get(key, ""))
        if stem:
            cw_thresholds = _civil_war_thresholds()
            if cw_thresholds:
                checks = ", ".join("≤ %d at cycle %d" % (v, c) for c, v in cw_thresholds)
            else:
                checks = "≤ 18 at cycle 24, ≤ 20 at cycle 29, ≤ 22 at cycle 34"
            director[stem] = [
                "Director scene: civil war — fires during a cycle fill in act 3 when the %s "
                "hold the lowest satisfaction among the not-yet-triggered populations and "
                "it falls to the threshold (%s)." % (label, checks)
            ]

    act_end_notes = {
        "act_1_endng_audience": "Director scene: act 1 ending — fires on the dragon-knight "
                                "ultimatum victory, then switches the game to act 2.",
        "act_2_endng_audience": "Director scene: act 2 ending — fires on the kingslayer "
                                "ultimatum victory, then switches the game to act 3.",
        "act_3_ending_audience": "Director scene: act 3 ending / game finale — fires on the "
                                 "emperor ultimatum victory to end the game.",
    }
    for key, note in act_end_notes.items():
        stem = refstem(props.get(key, ""))
        if stem:
            director[stem] = [note]

    arlin_notes = {
        "arlin_act_2_intro": "Director scene: Arlin's act 2 introduction — scheduled right "
                             "after the act 1 ending fires (dragon-knight ultimatum victory).",
        "arlin_act_3_intro": "Director scene: Arlin's act 3 introduction — scheduled right "
                             "after the act 2 ending fires (kingslayer ultimatum victory).",
    }
    for key, note in arlin_notes.items():
        stem = refstem(props.get(key, ""))
        if stem:
            director[stem] = [note]

    rupin = props.get("rupin_audiences", "").strip()
    if rupin.startswith("{") and rupin.endswith("}"):
        rupin = rupin[1:-1]
        entries = []
        for chunk in TresFile._split_top(rupin):
            if ":" not in chunk:
                continue
            k, v = chunk.split(":", 1)
            stem = refstem(k)
            if stem and v.strip().isdigit():
                entries.append((int(v.strip()), stem))
        for level, stem in sorted(entries):
            director[stem] = [
                "Director scene: Rupin's criminal-underworld cycle — plays during a cycle "
                "fill once the corruption level reaches %d (after the variable "
                "arlin_speech_about_rupin_heard is true)." % level
            ]

    return director


def load_special_interventions():
    """Parse the CyclesManager "SpecialInterventionsManager" node audiences ->
    {audience ink path: [notes]}.

    These narrated scenes (channel 9 of the audience-condition research) are
    played directly by the game director's second manager node — not by quests,
    ink doleance calls, requests or special instructions. Every node prop value
    is an audience's ink path (StringName); the notes below hand-write the guard
    logic of `special_interventions_manager.gd` (`check_for_audiences_phase_
    special_intervention` at :44 and `check_for_audience_phase_end_special_
    intervention` at :77) as human-readable "Special intervention: …" rows
    (same convention as the director `dir` notes and special.json's `cond`).
    """
    tscn = os.path.join(GAME, "systems/autoloads/cycles_manager.tscn")
    if not os.path.exists(tscn):
        return {}
    lines = open(tscn, encoding="utf-8").read().splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith('[node name="SpecialInterventionsManager"'):
            start = i + 1
            break
    if start is None:
        return {}
    props = {}
    for i in range(start, len(lines)):
        line = lines[i].strip()
        if line.startswith("["):
            break
        m = re.match(r'^([A-Za-z0-9_]+)\s*=\s*(\[.*\]|&".*")\s*$', line)
        if not m:
            continue
        values = re.findall(r'&"([^"]+)"', m.group(2))
        if values:
            props[m.group(1)] = values
    if not props:
        return {}

    # single-scene notes, keyed by the node prop name; the value is the ink path
    single = {
        "kingslayer_second_encounter":
            "Special intervention: kingslayer second encounter — when this scene "
            "sits in a cycle, the phase-start check launches the kingslayer allied "
            "interventions (Gwendan's if she is reformed and available, Ursula's if "
            "she is available, not highly corrupted and has died at least once).",
        "gwendan_intervention":
            "Special intervention: plays during the kingslayer second encounter, "
            "only while Gwendan is reformed and available.",
        "ursula_intervention":
            "Special intervention: plays during the kingslayer second encounter, "
            "only while Ursula is available, not highly corrupted and has died at "
            "least once.",
        "dragon_knight_second_encounter":
            "Special intervention: dragon-knight second encounter — when this scene "
            "sits in a cycle, the phase-start check launches the dragon-knight "
            "allied interventions (Tarcus's if he is available, Silgur's if she is "
            "available).",
        "tarcus_intervention":
            "Special intervention: plays during the dragon-knight second encounter, "
            "only while Tarcus is available.",
        "silgur_intervention":
            "Special intervention: plays during the dragon-knight second encounter, "
            "only while Silgur is available.",
        "traitor_intro_audience":
            "Special intervention: the traitor's-plot introduction — once it has "
            "played, the phase-end check may launch the traitor murder scene "
            "(scriptedquest_traitors_plot_2) under the traitor-plot conditions.",
        "murder_audience":
            "Special intervention: the traitor's-plot murder — fires at the phase "
            "end once the traitor introduction has played and the murder can run "
            "(traitor chosen, within act 2 + 3 cycles, traitor available, a target "
            "chosen, at least two other knights at the roundtable and the "
            "prevention dialogue not played).",
        "dulahan_human_introduction":
            "Special intervention: Dulahan's human-form introduction — fires at the "
            "phase end while Dulahan is at the roundtable in body form (not yet "
            "turned) and the scene has not played yet.",
        "victoria_betrayal":
            "Special intervention: Victoria's betrayal — fires at the phase end once "
            "Victoria has betrayed, and only once.",
        "nobles_intro":
            "Special intervention: the nobles' introduction — the only scene "
            "scheduled at cycle zero (the very first cycle).",
        "wolf_candidacy":
            "Special intervention: fires at the phase end after the variable "
            "angelica_tamed_the_beast_during_almor is true, and only once.",
        "arlin_intervention":
            "Special intervention: fires at the phase end when 11 counties have been "
            "rallied and the golden key is not yet held, and only once (Arlin is "
            "back at the reunited roundtable).",
    }
    # the two encounter audiences already carry cyc via the cycle timeline; make
    # the intervention-manager role explicit on top of that
    courier_act = {
        "act_1_courier_interventions": "act 1",
        "act_2_courier_interventions": "act 2",
        "act_3_courier_interventions": "act 3",
    }

    out = {}
    for key, values in props.items():
        if key in single:
            for path in values:
                out.setdefault(path, [])
                if single[key] not in out[path]:
                    out[path].append(single[key])
        elif key in courier_act:
            for path in values:
                out.setdefault(path, [])
                note = ("Special intervention: courier scene — becomes available "
                        "from %s; fires at a phase end when the courier cooldown "
                        "has elapsed and at most 10 quests are active (random pick "
                        "from the not-yet-played courier pool, once each)."
                        % courier_act[key])
                out[path].append(note)
    return out


def load_knight_death_followups():
    """Parse content/character_descriptors/knights/*.tres -> {audience stem: [[knight, "death"]]}.

    A knight lists the narrated scenes that play when it dies
    (`death_follow_up_audiences_names`); `knight.gd:die()` emits the selected
    follow-up audience for the next cycle (`get_death_follow_up_dialogue()`,
    knight.gd:139-152, erasing it from played_audiences so it can re-fire).
    Per-knight overrides change which of the listed scenes actually plays:
    Ursule (ursula.gd:47-62) picks the low/mid/high-corruption variant by her
    death count (corruption_thresholds 1/3/5, ursula.gd:15-20) or, while on the
    kingslayer ultimatum quest, always the high one; Gideon (gideon.gd:24-28)
    suppresses his follow-up while he is the traitor during an AUDIENCE phase.
    Values are `[knight_stem, "death"]` pairs; `load_knight_demissions()`
    populates the same `dd` field with `"demission"` entries.
    """
    d = f"{GAME}/content/character_descriptors/knights"
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".tres"):
            continue
        knight = os.path.splitext(fn)[0]
        tf = TresFile.load(os.path.join(d, fn), d)
        for aud in tf.props.get("death_follow_up_audiences_names", []) or []:
            out.setdefault(aud, []).append([knight, "death"])
    return out


def load_knight_demissions():
    """Parse content/character_descriptors/knights/*.tres -> {audience stem: [[knight, "demission", variant?]]}.

    A knight leaves the roundtable when its affinity drops to (or below) its
    `demission_affinity_treshold`; at the next cycle reset `check_for_demission()`
    (knight.gd:183-194) schedules the result of `get_demission_path()` as the
    next cycle's audience. The base `roundtable_demission_audience_name` field
    is set on every descriptor, and the per-knight subclasses override
    `get_demission_path()` (knight.gd:196) with a variant audience while the
    knight is in a special state:
    - arron.gd:143 — `roundtable_demission_audience_violent` ("violent") when the
      Dragonheart transformation is active
    - dulahan.gd:116 — `_human` when in the human/body state, `_possessed`
      ("possessed") when wearing the cursed helmet
    - edith.gd:81 — `roundtable_demission_audience_possessed` while possessed
    - gwendan.gd:161 — `roundtable_demission_audience_humbled` ("humbled") when
      reformed (the humble vote-of-candidacy scene, which lives in
      content/audiences/candidacies, not demissions/)
    Values are `[knight_stem, "demission"]` plus an optional third variant label
    — the same field the death follow-ups populate as `[knight, "death"]` (E3).
    """
    d = f"{GAME}/content/character_descriptors/knights"
    fields = (
        ("roundtable_demission_audience_name", None),
        ("roundtable_demission_audience_violent", "violent"),
        ("roundtable_demission_audience_human", "human"),
        ("roundtable_demission_audience_possessed", "possessed"),
        ("roundtable_demission_audience_humbled", "humbled"),
    )
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".tres"):
            continue
        knight = os.path.splitext(fn)[0]
        tf = TresFile.load(os.path.join(d, fn), d)
        for field, variant in fields:
            aud = tf.props.get(field) or ""
            if not aud:
                continue
            entry = [knight, "demission"]
            if variant:
                entry.append(variant)
            out.setdefault(aud, []).append(entry)
    return out


def load_county_introductions():
    """Parse content/world/counties/*.tres -> {audience stem: [county ink id, name key]}.

    Channel 6 of the audience-condition research: a county's
    `county_introduction` field is the narrated scene that introduces it (the
    `county_quest_<id>_1` audiences of the county_quests folder). The ActManager
    is the only scheduler (act_manager.gd): at each act 1->2 / 2->3 transition
    `set_next_counties_introductions()` (:58) schedules the act's county intros
    with a `2 + i*3` (or `2 + i*4` when the act-2 list is short) cycle delay
    (brimwood first, then the shuffled rest), and `_on_county_rallied()` (:102)
    schedules the intros of the not-yet-introduced neighbors of a just-rallied
    county. Values are `[county ink_id, county_name loc key]`.
    """
    d = f"{GAME}/content/world/counties"
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".tres"):
            continue
        tf = TresFile.load(os.path.join(d, fn), d)
        intro = tf.props.get("county_introduction")
        stem = _ref_stem(intro, tf) if intro else None
        if not stem:
            continue
        out[stem] = [tf.props.get("ink_id") or os.path.splitext(fn)[0],
                     tf.props.get("county_name") or ""]
    return out


def _decode_ultimatum_condition(filer, ref, pop_names):
    """Decode one QuestExtraCondition sub-resource into a human note.

    QuestExtraCondition.Types (quest_extra_condition.gd:5-9):
      0 MIN_RALLIED_COUNTIES (the .tres omits `type` for the default 0, so the
        sub-resource carries only min_rallied_counties)
      1 SATISFACTION_REQUIREMENT (type = 1, targeted_population + amount)
      2 MIN_FUNDS (type = 2, amount)
    """
    if not isinstance(ref, dict) or "_sub" not in ref:
        return None
    props = filer.sub_props(ref["_sub"])
    ctype = props.get("type", 0)
    if ctype == 0:
        return "min_rallied_counties %d" % props.get("min_rallied_counties", 0)
    if ctype == 1:
        pop = pop_names.get(props.get("targeted_population", 0), "population")
        return "%s \u2265 %d" % (pop, props.get("amount", 0))
    if ctype == 2:
        return "funds \u2265 %d" % props.get("amount", 0)
    return None


def load_ultimatums(idx):
    """Parse content/ultimatums/*.tres -> {audience stem: {"um": [uid, cycle], "umc": [notes]}}.

    Channel 7 of the audience-condition research: an ultimatum (dragon knight /
    kingslayer / emperor) is a story-level deadline. When it is triggered from
    ink (`UltimatumTriggered`), its `ultimatum_follow_up_quests` become the
    active "face the ultimatum" contracts and gain the selected condition set as
    extra conditions plus a hard `remaining_cycles_before_faillure` deadline
    (targeted_cycle_index - current cycle, ultimatum_manager.gd:67). The narrated
    scenes those quests play as success/failure follow-ups (and their
    unexpected-outcome follow-ups) are the ultimatum's victory/defeat audiences,
    e.g. kingslayer_ultimatum_faillure fired by all five kingslayer quests on
    failure. Values carry `um` (ultimatum id + deadline cycle) and `umc` (the
    decoded condition-set notes, flattened + de-duplicated across the three sets).
    """
    pop_names = {v: n.lower() for n, v in (idx.enums.get("Population") or [])}
    out = {}
    d = f"{GAME}/content/ultimatums"
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".tres"):
            continue
        tf = TresFile.load(os.path.join(d, fn), d)
        P = tf.props
        uid = P.get("ultimatum_id") or os.path.splitext(fn)[0]
        cycle = P.get("targeted_cycle_index", 1)
        umc = []
        for setname in ("first_conditions_set", "second_conditions_set",
                        "third_conditions_set"):
            for ref in P.get(setname, []) or []:
                note = _decode_ultimatum_condition(tf, ref, pop_names)
                if note and note not in umc:
                    umc.append(note)
        for qref in P.get("ultimatum_follow_up_quests", []) or []:
            qstem = _ref_stem(qref, tf)
            if not qstem:
                continue
            qpath = os.path.join(QUEST_DIR, qstem + ".tres")
            if not os.path.exists(qpath):
                continue
            qtf = TresFile.load(qpath, QUEST_DIR)
            for key in ("success_follow_up_audience", "failure_follow_up_audience"):
                ref = qtf.props.get(key)
                astem = _ref_stem(ref, qtf) if ref else None
                if astem:
                    out.setdefault(astem, {"um": [uid, cycle], "umc": list(umc)})
            for sref in qtf.props.get("special_outcomes", []) or []:
                so_path = qtf.ext_path(sref["_ext"]) if isinstance(sref, dict) and "_ext" in sref else None
                if not so_path:
                    continue
                if so_path.startswith("res://"):
                    so_path = f"{GAME}/{so_path[6:]}"
                if not os.path.exists(so_path):
                    continue
                sotf = TresFile.load(so_path, os.path.dirname(so_path))
                fu = sotf.props.get("follow_up_audience")
                astem = _ref_stem(fu, sotf) if fu not in (None, "null") else None
                if astem:
                    out.setdefault(astem, {"um": [uid, cycle], "umc": list(umc)})
    return out


# FillerAudiencesManager pack arrays of systems/autoloads/cycles_manager.tscn
# -> the runtime unlock name. The four "representatives" packs are always
# available from the start (filler_audiences_manager.gd `set_up()`); every
# other name is the argument the ink passes to UnlockFillerAudiencesPack — the
# `_unlock_audience_pack` match on filler_audiences_manager.gd:63, which groups
# the two per-county arrays of each region under the region name (e.g. the
# belthorne + beaconsbury arrays are both unlocked as "groveshire").
FILLER_PACK_NAMES = {
    "academician_filler_audiences": "academician",
    "aristocrat_filler_audiences": "aristocrat",
    "shopkeeper_filler_audiences": "shopkeeper",
    "worker_filler_audiences": "worker",
    "clovermont_filler_audiences": "clovermont",
    "grest_filler_audiences": "grest",
    "milkford_filler_audiences": "milkford",
    "rozenn_filler_audiences": "rozenn",
    "villador_filler_audiences": "villador",
    "belthorne_filler_audiences": "groveshire",
    "beaconsbury_filler_audiences": "groveshire",
    "mavignac_filler_audiences": "gavault",
    "chavignol_filler_audiences": "gavault",
    "pince_harbor_filler_audiences": "southbay",
    "shellington_filler_audiences": "southbay",
    "naoned_filler_audiences": "almor",
    "anveld_filler_audiences": "almor",
    "volga_camp_filler_audiences": "kutnar",
    "laik_valley_filler_audiences": "kutnar",
    "avalon_filler_audiences": "moonvale",
    "pinemaze_filler_audiences": "moonvale",
    "popota_isle_filler_audiences": "basalt_isles",
    "tortosa_isle_filler_audiences": "basalt_isles",
    "ziskov_filler_audiences": "enberg",
    "mana_strala_isle_filler_audiences": "enberg",
    "kralgrun_filler_audiences": "brimwood",
    "mossgart_filler_audiences": "brimwood",
}


def load_filler_packs():
    """Parse the filler-audience packs -> {audience stem: [pack, pop_cat, corruption]}.

    Channel 13 of the audience-condition research: the 236
    `content/filler_audiences/*.tres` FillerAudience wrappers (each wrapping one
    `content/audiences/filler/` scene) grouped by the
    `[node name="FillerAudiencesManager"]` pack arrays of cycles_manager.tscn.
    The pack name is the runtime unlock name of `_unlock_audience_pack`
    (filler_audiences_manager.gd:63): the four "representatives" packs are
    always available from the start, the rest are unlocked when the ink calls
    UnlockFillerAudiencesPack (the first-grievance knots). Values are
    `[pack, targeted_pop_category, corruption_score]` where the two ints are
    baked only when the wrapper sets them (defaults are the game's 0 / PEOPLE).
    """
    d = f"{GAME}/content/filler_audiences"
    if not os.path.isdir(d):
        return {}
    wrappers = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".tres"):
            continue
        tf = TresFile.load(os.path.join(d, fn), d)
        P = tf.props
        wrappers[os.path.splitext(fn)[0]] = {
            "aud": _ref_stem(P.get("audience"), tf),
            "tpc": P.get("targeted_pop_category"),
            "cs": P.get("corruption_score"),
        }

    tscn = os.path.join(GAME, "systems/autoloads/cycles_manager.tscn")
    if not os.path.exists(tscn):
        return {}
    lines = open(tscn, encoding="utf-8").read().splitlines()
    ext = {}
    for m in re.finditer(r"\[ext_resource type=\"[^\"]*\"[^]]*path=\"([^\"]+)\"[^]]*id=\"(\d+)\"\]",
                         "\n".join(lines)):
        ext[m.group(2)] = m.group(1)
    start = None
    for i, line in enumerate(lines):
        if line.startswith('[node name="FillerAudiencesManager"'):
            start = i + 1
            break
    if start is None:
        return {}

    out = {}
    for i in range(start, len(lines)):
        line = lines[i].strip()
        if line.startswith("["):
            break
        m = re.match(r"^([A-Za-z0-9_]+)\s*=\s*(\[.*\])\s*$", line)
        if not m:
            continue
        pack = FILLER_PACK_NAMES.get(m.group(1))
        if not pack:
            continue
        for w in [os.path.splitext(os.path.basename(ext[j]))[0]
                  for j in re.findall(r'ExtResource\("(\d+)"\)', m.group(2))]:
            info = wrappers.get(w)
            if not info or not info["aud"] or info["aud"] in out:
                continue
            out[info["aud"]] = [
                pack,
                info["tpc"] if isinstance(info["tpc"], int) else None,
                info["cs"] if isinstance(info["cs"], int) else None,
            ]
    return out


def load_audience_catalog(idx):
    """Walk content/audiences/** and build the full audience catalog.

    Each audience resource becomes {k: ink_path, f: folder, c: [char name
    keys], rq: [decoded requirements], cyc/scheduled cycles, dir: director +
    special-intervention notes, dd: knight death-follow-up / demission links,
    fl: [filler pack, targeted population, corruption score], ci: [county ink
    id, name key] when the audience is a county introduction} — the reverse
    lookup the knot drawer needs ("how does this knot fire, and under what
    conditions?").
    """
    catalog = {}
    if not os.path.isdir(AUDIENCE_DIR):
        return catalog
    cycles = load_cycle_schedule()
    director = load_director_audiences()
    interventions = load_special_interventions()
    death_followups = load_knight_death_followups()
    demissions = load_knight_demissions()
    filler = load_filler_packs()
    county_intros = load_county_introductions()
    ultimatums = load_ultimatums(idx)
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
            stem = os.path.splitext(fn)[0]
            dirn = director.get(stem)
            if dirn:
                entry["dir"] = list(dirn)
            inotes = interventions.get(entry["k"])
            if inotes:
                entry["dir"] = (entry.get("dir") or []) + list(inotes)
            dde = death_followups.get(stem)
            dms = demissions.get(stem)
            if dde or dms:
                entry["dd"] = list(dde or []) + list(dms or [])
            fl = filler.get(stem)
            if fl:
                entry["fl"] = fl
            ci = county_intros.get(stem)
            if ci:
                entry["ci"] = ci
            um = ultimatums.get(stem)
            if um:
                entry["um"] = um["um"]
                if um["umc"]:
                    entry["umc"] = um["umc"]
            catalog[stem] = entry
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

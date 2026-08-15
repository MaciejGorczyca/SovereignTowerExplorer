#!/usr/bin/env python3
"""
Sovereign Tower — INK story extractor.

The game ships with NO raw .ink or .ink.json files. The compiled ink stories
(one per locale: en/fr/cmn/de/ja/ko) live INSIDE Godot 4.6 binary resources
(RES) produced by the inkgd addon's `ink_json_import_plugin.gd`:

    story/<locale>/master.ink.json        (source, NOT shipped)
        -> imported to
    .godot/imported/master.ink.json-<hash>.res   (shipped inside the pck)

Those .res files are Godot binary resources saved with
ResourceSaver.FLAG_COMPRESS -> "RSCC" magic (ZSTD, block-compressed via
FileAccessCompressed) containing an `InkResource` whose `json` String
property holds the entire compiled ink story for that locale
(JSON with "inkVersion" + "root" knot, all knots/stitches/choices).

This script decodes that chain and extracts each locale's ink JSON:

  RSCC/RSRC .res  --decompress--> Godot binary resource --parse--> InkResource
          --property "json"--> compiled ink JSON  --> saved next to script.

Output layout (outside SovereignTowerCode):
  <output_dir>/<locale>/master.ink.json        raw compiled ink JSON
  <output_dir>/<locale>/knots/index.md         per-knot table of contents
  <output_dir>/<locale>/knots/<knot>.txt       readable dump per top-level knot

Usage:
  python3 ink_extract.py [SovereignTowerCode_dir] [output_dir]

(In the repo layout the defaults are ../game/SovereignTowerCode and
../game/InkExtracted. build_app.py imports the same functions to extract
in-memory — see build_app.py --extract-ink / --save-ink.)

Paths are resolved with this priority (higher wins):
  1. CLI arguments
  2. Environment variables:    INK_SOURCE, INK_OUT
  3. Config file extract.env    (KEY=VALUE, same keys, next to this script)
  4. Portable defaults:        source = ../game/SovereignTowerCode (relative to
                              this script), output = ../game/InkExtracted
                              (also relative to this script)
"""

import json
import os
import re
import struct
import sys
from pathlib import Path

try:
    import zstandard
except ImportError:
    zstandard = None

MAGIC_RSCC = b"RSCC"  # compressed binary resource
MAGIC_RSRC = b"RSRC"  # plain binary resource

# Godot binary resource format version 6 (Godot 4.6),
# see core/io/resource_format_binary.cpp
FORMAT_VERSION = 6

# variant type ids
V_NIL = 1
V_BOOL = 2
V_INT = 3
V_FLOAT = 4
V_STRING = 5
V_VECTOR2 = 10
V_RECT2 = 11
V_VECTOR3 = 12
V_PLANE = 13
V_QUATERNION = 14
V_AABB = 15
V_BASIS = 16
V_TRANSFORM3D = 17
V_TRANSFORM2D = 18
V_COLOR = 20
V_NODE_PATH = 22
V_RID = 23
V_OBJECT = 24
V_INPUT_EVENT = 25
V_DICTIONARY = 26
V_ARRAY = 30
V_PACKED_BYTE_ARRAY = 31
V_PACKED_INT32_ARRAY = 32
V_PACKED_FLOAT32_ARRAY = 33
V_PACKED_STRING_ARRAY = 34
V_PACKED_VECTOR3_ARRAY = 35
V_PACKED_COLOR_ARRAY = 36
V_PACKED_VECTOR2_ARRAY = 37
V_INT64 = 40
V_DOUBLE = 41
V_CALLABLE = 42
V_SIGNAL = 43
V_STRING_NAME = 44
V_VECTOR2I = 45
V_RECT2I = 46
V_VECTOR3I = 47
V_PACKED_INT64_ARRAY = 48
V_PACKED_FLOAT64_ARRAY = 49
V_VECTOR4 = 50
V_VECTOR4I = 51
V_PROJECTION = 52
V_PACKED_VECTOR4_ARRAY = 53

FLAG_NAMED_SCENE_IDS = 1
FLAG_UIDS = 2
FLAG_REAL_T_IS_DOUBLE = 4
FLAG_HAS_SCRIPT_CLASS = 8
RESERVED_FIELDS = 11  # Godot 4.6 binary resource header (was 5 in older 4.x)


class BinaryResourceError(Exception):
    pass


def decompress_resource(data: bytes) -> bytes:
    """Unpack the FileAccessCompressed / plain binary resource envelope."""
    if data.startswith(MAGIC_RSCC):
        if zstandard is None:
            raise BinaryResourceError("zstandard module required for RSCC files")
        cmode, block_size, read_total = struct.unpack_from("<III", data, 4)
        if block_size == 0:
            raise BinaryResourceError("block size 0")
        bc = read_total // block_size + 1
        if 16 + 4 * bc > len(data):
            raise BinaryResourceError("truncated block size table")
        sizes = struct.unpack_from("<%dI" % bc, data, 16)
        off = 16 + 4 * bc
        dctx = zstandard.ZstdDecompressor()
        out = bytearray()
        for i, csize in enumerate(sizes):
            if off + csize > len(data):
                raise BinaryResourceError("truncated compressed block %d" % i)
            blk = data[off:off + csize]
            off += csize
            expected = block_size if i != bc - 1 else (read_total % block_size or block_size)
            out += dctx.decompress(blk, max_output_size=expected + 1024)
        if len(out) != read_total:
            raise BinaryResourceError(
                "size mismatch: expected %d, got %d" % (read_total, len(out)))
        return bytes(out)
    elif data.startswith(MAGIC_RSRC):
        return data[4:]
    raise BinaryResourceError("unrecognized resource magic %r" % data[:4])


class BinaryReader:
    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0
        self.big_endian = False
        self.real64 = False
        self.ver_format = FORMAT_VERSION
        self.string_map = []

    def _f(self, fmt):
        if self.big_endian:
            fmt = ">" + fmt
        else:
            fmt = "<" + fmt
        size = struct.calcsize(fmt)
        if self.pos + size > len(self.buf):
            raise BinaryResourceError("premature end of data at offset %d" % self.pos)
        val = struct.unpack_from(fmt, self.buf, self.pos)
        self.pos += size
        return val[0]

    def u32(self):
        return self._f("I")

    def i32(self):
        return self._f("i")

    def u64(self):
        return self._f("Q")

    def real(self):
        return self._f("d" if self.real64 else "f")

    def skip(self, n):
        self.pos += n

    def raw(self, n):
        if self.pos + n > len(self.buf):
            raise BinaryResourceError("premature end of data at offset %d" % self.pos)
        v = self.buf[self.pos:self.pos + n]
        self.pos += n
        return v

    def ustring(self):
        """save_ustring/get_unicode_string: u32 length (incl. trailing NUL) + utf8."""
        n = self.u32()
        if n == 0:
            return ""
        raw = self.raw(n)
        return raw[:-1].decode("utf-8", errors="replace")

    def string_id(self):
        """_get_string: string table id or inline string (high bit set)."""
        idx = self.u32()
        if idx & 0x80000000:
            n = idx & 0x7FFFFFFF
            return self.raw(n).decode("utf-8", errors="replace")
        try:
            return self.string_map[idx]
        except IndexError:
            raise BinaryResourceError("bad string table id %d" % idx)

    def align4(self):
        while self.pos % 4:
            self.pos += 1


def parse_variant(r: BinaryReader, depth=0):
    t = r.u32()
    if t == V_NIL:
        return None
    if t == V_BOOL:
        return bool(r.u32())
    if t == V_INT:
        return r.i32()
    if t == V_INT64:
        return r._f("q")
    if t == V_FLOAT:
        return r.real()
    if t == V_DOUBLE:
        return r._f("d")
    if t == V_STRING:
        return r.ustring()
    if t == V_STRING_NAME:
        return r.ustring()
    if t == V_NODE_PATH:
        names = r._f("H")
        subname_count = r._f("H") & 0x7FFF
        if r.ver_format < 3:
            subname_count += 1
        r.skip((names + subname_count) * 4)  # string ids
        return "<NodePath>"
    if t == V_RID:
        return "<RID:%d>" % r.u32()
    if t == V_OBJECT:
        objtype = r.u32()
        if objtype == 0:
            return None
        if objtype == 1:  # external resource (old)
            return "<ExtResource: %s>" % r.ustring()
        if objtype == 2:  # internal resource
            return "<SubResource:%d>" % r.u32()
        if objtype == 3:  # external resource index
            return "<ExtResourceIndex:%d>" % r.u32()
        raise BinaryResourceError("unknown object subtype %d" % objtype)
    if t == V_CALLABLE:
        return "<Callable>"
    if t == V_SIGNAL:
        return "<Signal>"
    if t in (V_VECTOR2, V_VECTOR2I, V_RECT2, V_RECT2I, V_VECTOR3, V_VECTOR3I,
             V_VECTOR4, V_VECTOR4I, V_PLANE):
        comps = {V_VECTOR2: 2, V_VECTOR2I: 2, V_RECT2: 4, V_RECT2I: 4,
                 V_VECTOR3: 3, V_VECTOR3I: 3, V_VECTOR4: 4, V_VECTOR4I: 4,
                 V_PLANE: 4}[t]
        r.skip(comps * (8 if t in (V_VECTOR2, V_RECT2, V_VECTOR3, V_VECTOR4, V_PLANE) and r.real64 else 4))
        return None
    if t == V_QUATERNION or t == V_AABB:
        r.skip(4 * (8 if r.real64 else 4))
        return None
    if t == V_BASIS:
        r.skip(9 * (8 if r.real64 else 4))
        return None
    if t == V_TRANSFORM3D:
        r.skip(12 * (8 if r.real64 else 4))
        return None
    if t == V_TRANSFORM2D:
        r.skip(6 * (8 if r.real64 else 4))
        return None
    if t == V_PROJECTION:
        r.skip(16 * (8 if r.real64 else 4))
        return None
    if t == V_COLOR:
        r.skip(16)
        return None
    if t == V_INPUT_EVENT:
        return "<InputEvent>"
    if t == V_DICTIONARY:
        n = r.u32() & 0x7FFFFFFF
        d = {}
        for _ in range(n):
            k = parse_variant(r, depth + 1)
            v = parse_variant(r, depth + 1)
            if k is not None:
                d[k] = v
        return d
    if t == V_ARRAY:
        n = r.u32() & 0x7FFFFFFF
        return [parse_variant(r, depth + 1) for _ in range(n)]
    if t == V_PACKED_BYTE_ARRAY:
        n = r.u32()
        v = r.raw(n)
        r.align4()
        return v
    if t in (V_PACKED_INT32_ARRAY, V_PACKED_FLOAT32_ARRAY, V_PACKED_COLOR_ARRAY):
        n = r.u32()
        r.skip(n * 4)
        return None
    if t in (V_PACKED_INT64_ARRAY, V_PACKED_FLOAT64_ARRAY):
        n = r.u32()
        r.skip(n * 8)
        return None
    if t == V_PACKED_STRING_ARRAY:
        n = r.u32()
        return [r.ustring() for _ in range(n)]
    if t in (V_PACKED_VECTOR2_ARRAY, V_PACKED_VECTOR3_ARRAY, V_PACKED_VECTOR4_ARRAY):
        n = r.u32()
        per = {V_PACKED_VECTOR2_ARRAY: 2, V_PACKED_VECTOR3_ARRAY: 3,
               V_PACKED_VECTOR4_ARRAY: 4}[t] * (8 if r.real64 else 4)
        r.skip(n * per)
        return None
    raise BinaryResourceError("unsupported variant type %d at offset %d" % (t, r.pos - 4))


def parse_binary_resource(payload: bytes):
    """Parse the binary resource stream; return (type, uid, dict of props of main resource)."""
    r = BinaryReader(payload)
    r.big_endian = bool(r.u32())
    r.real64 = bool(r.u32())
    r._f("I")  # ver_major
    r._f("I")  # ver_minor
    r.ver_format = r._f("I")
    if r.ver_format > FORMAT_VERSION:
        raise BinaryResourceError("unsupported format version %d" % r.ver_format)

    rtype = r.ustring()
    importmd_ofs = r.u64()
    flags = r.u32()
    using_uids = bool(flags & FLAG_UIDS)
    r.u64()  # uid
    if flags & FLAG_HAS_SCRIPT_CLASS:
        script_class = r.ustring()
    else:
        script_class = ""
    for _ in range(RESERVED_FIELDS):
        r.u32()

    string_table_size = r.u32()
    r.string_map = [r.ustring() for _ in range(string_table_size)]

    ext_resources = []
    ext_resources_size = r.u32()
    for _ in range(ext_resources_size):
        etype = r.ustring()
        epath = r.ustring()
        if using_uids:
            r.u64()
        ext_resources.append((etype, epath))

    internal_resources = []
    int_resources_size = r.u32()
    for _ in range(int_resources_size):
        ipath = r.ustring()
        ioffset = r.u64()
        internal_resources.append((ipath, ioffset))

    main_props = {}
    for idx, (ipath, ioffset) in enumerate(internal_resources):
        is_main = idx == len(internal_resources) - 1
        r.pos = ioffset
        itype = r.ustring()
        prop_count = r.i32()
        props = {}
        for _ in range(prop_count):
            name = r.string_id()
            if r.ver_format < 3 and name.startswith("_"):
                name = name[1:]
            props[name] = parse_variant(r)
        if is_main:
            main_props = props
    return rtype, script_class, main_props


def extract_ink_story(res_path: Path):
    """Decode one .res; return (story_dict | None, extra info)."""
    data = res_path.read_bytes()
    payload = decompress_resource(data)
    rtype, script_class, props = parse_binary_resource(payload)
    json_str = None
    for key in ("json",):
        v = props.get(key)
        if isinstance(v, str):
            json_str = v
    if json_str is None:
        return None, {"type": rtype, "script": script_class, "props": sorted(props)}
    try:
        story = json.loads(json_str)
    except json.JSONDecodeError:
        return None, {"type": rtype, "script": script_class, "json_invalid": True}
    if "inkVersion" not in story:
        return None, {"type": rtype, "script": script_class, "not_ink": True}
    return story, {"type": rtype, "script": script_class}


def story_locations(root: Path):
    """Yield (res_path, locale) for every known locale import."""
    found = []
    for imp in sorted(root.glob("story/*/master.ink.json.import")):
        locale = imp.parent.name
        m = re.search(r'path="res://(.godot/imported/[^"]+\.res)"', imp.read_text(errors="replace"))
        if not m:
            continue
        rel = Path(m.group(1))
        if rel.parts[0] == ".godot":
            res = root / rel
        else:
            res = root / rel
        if res.exists():
            found.append((res, locale))
    return found


def ink_container(node):
    """Split an ink container into (content_list, named_children_dict).
    Containers are ordered lists of runtime objects, optionally followed by a
    dict of named children (stitches / knots) carrying a '#f' flags key."""
    content = []
    named = {}
    if isinstance(node, dict):
        return [node], {}
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict):
                keys = set(item.keys())
                if any(k.startswith("^") or k in ("#f", "#n", "#t") for k in keys):
                    named.update(item)
                else:
                    content.append(item)
            else:
                content.append(item)
    return content, named


def root_named(story):
    """Return the named-children dict of the story root (knots + global decl)."""
    root = story.get("root")
    if isinstance(root, dict):
        return root
    if isinstance(root, list) and root:
        last = root[-1]
        if isinstance(last, dict):
            return {k: v for k, v in last.items() if k != "#f"}
    return {}


def knot_dump(story: dict, knot: str) -> str:
    """Best-effort readable render of one top-level knot (text, choices, diverts)."""
    named = root_named(story)
    knot_obj = named.get(knot)
    if knot_obj is None:
        return f"(knot {knot} not found)"
    out = ["== %s ==" % knot]

    def is_text(s):
        return (s.startswith("^") and not s.startswith("^->") and not s.startswith("^<-")
                and not s.startswith("^|") and s not in ("^", "^^") and s.strip() != "^")

    def render_object(obj, indent, state):
        if isinstance(obj, str):
            if is_text(obj):
                state["str"] = obj[1:]
                state["any"] = obj[1:]
                out.append(" " * indent + obj[1:])
            return
        if isinstance(obj, list):
            walk(obj, indent, state)
            return
        if not isinstance(obj, dict):
            return
        if "^->" in obj:
            out.append(" " * indent + "-> %s" % obj["^->"])
            return
        if "^<-" in obj:
            out.append(" " * indent + "back <- %s" % obj["^<-"])
            return
        if "->" in obj:
            out.append(" " * indent + "-> %s" % obj["->"])
            return
        if "*" in obj:
            label = state["str"] or state["any"]
            if not label:
                label = obj.get(".")
            out.append(" " * (indent + 2) + "[ %s ]" % label)
            state["str"] = ""
            state["any"] = ""
            return
        if "f()" in obj:
            args = [repr(v) for k, v in obj.items() if k != "f()"]
            out.append(" " * indent + "// %s(%s)" % (obj["f()"], ", ".join(args)))
            return
        if "VAR?" in obj or "VAR=" in obj or "list" in obj or "origins" in obj or "#" in obj:
            return

    def walk(container, indent, state):
        content, named = ink_container(container)
        for item in content:
            render_object(item, indent, state)
        for name, child in named.items():
            if name.startswith("^") or name in ("#f", "#n", "#t"):
                continue
            out.append(" " * indent + "// stitch: %s" % name)
            walk(child, indent + 2, state)

    walk(knot_obj, 0, {"str": "", "any": ""})
    return "\n".join(out) if out else "(empty knot)"


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_ENV_FILE = SCRIPT_DIR / "extract.env"


def _load_config() -> dict:
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


def main():
    cfg = _load_config()

    def pick(arg, env_key):
        if arg:
            return arg
        return os.environ.get(env_key) or cfg.get(env_key) or ""

    root_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    out_arg = sys.argv[2] if len(sys.argv) > 2 else ""
    root_dir = pick(root_arg, "INK_SOURCE")
    out_dir = pick(out_arg, "INK_OUT")
    root_dir = Path(root_dir) if root_dir else (SCRIPT_DIR.parent / "game" / "SovereignTowerCode")
    out_dir = Path(out_dir) if out_dir else (SCRIPT_DIR.parent / "game" / "InkExtracted")
    out_dir.mkdir(parents=True, exist_ok=True)

    locations = story_locations(root_dir)
    if not locations:
        print("No story imports found under %s" % root_dir, file=sys.stderr)
        sys.exit(1)

    extracted = []
    for res_path, locale in locations:
        story, info = extract_ink_story(res_path)
        locale_dir = out_dir / locale
        (locale_dir / "knots").mkdir(parents=True, exist_ok=True)
        if story:
            story_path = locale_dir / "master.ink.json"
            story_path.write_text(json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")
        knots = {}
        global_decl = None
        if story:
            rn = root_named(story)
            for k in sorted(rn.keys()):
                if k == "global decl":
                    global_decl = rn[k]
                else:
                    knots[k] = rn[k]
        if story:
            lines = ["# %s — master.ink.json extracted from %s" % (locale, res_path.name),
                     "", "Compiled ink: inkVersion %s" % story.get("inkVersion"),
                     "Story type: %s" % info.get("type"), ""]
            if global_decl is not None:
                names = []
                seen = set()
                for item in ink_container(global_decl)[0]:
                    if isinstance(item, dict) and isinstance(item.get("VAR="), str):
                        n = item["VAR="]
                        if n not in seen:
                            seen.add(n)
                            names.append(n)
                lines.append("Global variables declared in story (%d):" % len(names))
                lines.append("")
                for i in range(0, len(names), 6):
                    lines.append("  " + ", ".join(names[i:i + 6]))
                lines.append("")
            lines += ["## Knots (%d)" % len(knots), "", "| knot | stitches |", "|---|---|"]
            for k in sorted(knots.keys()):
                content, named = ink_container(knots[k])
                stitch_names = [n for n in named.keys() if n not in ("#f", "#n", "#t")]
                f = locale_dir / "knots" / ("%s.txt" % k)
                f.write_text(knot_dump(story, k), encoding="utf-8")
                lines.append("| %s | %s |" % (k, ", ".join(sorted(stitch_names))))
            (locale_dir / "knots" / "index.md").write_text("\n".join(lines), encoding="utf-8")
        ok = story is not None
        print("%-4s %-34s %-5d %s" % (locale, res_path.name, len(knots), "" if ok else "NO INK STORY"))
        extracted.append((locale, res_path, ok, len(knots)))

    print("\nExtracted to %s" % out_dir)
    for locale, res, ok, nk in extracted:
        print("  %s: %s (%d top-level knots)" % (locale, res.name, nk))
    missing = [l for l, _, ok, _ in extracted if not ok]
    if missing:
        print("FAILED locales: %s" % ", ".join(missing), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
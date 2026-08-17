#!/usr/bin/env python3
"""Sovereign Tower — static viewer build.

Walks the extracted compiled ink JSON (InkExtracted/<locale>/master.ink.json)
directly and emits a compact, browser-friendly dataset:

  dist/index.json                 en metadata + dialogue tokens + dictionaries
  dist/locales/<locale>.json      dialogue tokens only (string overrides)

Knot identity / metadata is locale-independent; only dialogue text differs, so
non-`en` locales ship as token overrides and are lazy-loaded by the frontend.

Token encoding (compact arrays):
  ["0", text, speaker?]   dialogue text (speaker = active Locutor arg, "" = none)
  ["1", marker]           (BREAK_n) / (NO_CLICK)
  ["2", label, [req...], flg?]   player choice + requirement fns
  ["3", "set:…", [target, rhs?]]  variable write (rhs = assigned value, when known)
  ["3", name, [args...]]  game/ink function call
  ["4", divert]           -> target
  ["5", stitch]           stitch section header
  ["6", instruction]      >>> game instruction
  ["7", ["!v"/"v", ...], expr?]  conditional branch gate (c:true divert, per-var
                              negation; expr = infix condition incl. operators).
                              An `if` gate carries a trailing `"1"` (opens a
                              block closed by an "8"); an `else` branch is the
                              same gate re-emitted with the NEGATED condition
                              and no `"1"` (the block stays open until "8").

Variable read/write attribution is semantic, not just structural: state-mutating
game-API calls (UpdateSovereignValue, UpdateSatisfaction, UnlockQuest, …) count
their slot-0 argument as a *written* variable even though the compiler only emits
it as a `VAR?` read (see WRITE_SLOT0_FUNCS below). Literal constants are never
mislabelled — a slot only counts when it was pushed as a real variable reference.

Usage:
  python3 build_app.py [--profile] [--extract-ink [dir]] [--save-ink [dir]] [--from-disk]
                       [ink_root] [out_dir] [game_root]

Modes:
  --profile      print per-phase wall/CPU timings of the build to stdout (a
                 machine-agnostic before/after reference for build-time fixes).
  default      decode the compiled ink stories IN-MEMORY from the game's
               .res chain (game/SovereignTowerCode/story/* -> .godot/imported)
               and build dist/ with all 6 locales — nothing is persisted.
               Requires the `zstandard` pip package (hard error if missing).
  --extract-ink [dir]   skip the build; only decode the 6 locales and write
               <dir>/<locale>/master.ink.json (default ../game/InkExtracted),
               then exit. Same output as ink_extract.py.
  --save-ink [dir]      build as default, then ALSO write the extracted
               master.ink.json files into <dir> (default ../game/InkExtracted).
  --from-disk  read <ink_root>/<locale>/master.ink.json from disk instead of
               extracting (e.g. user-provided extracted knots placed under
               game/InkExtracted). Missing locales are skipped, with a warning.

Paths are resolved with this priority (higher wins):
  1. CLI arguments:          python3 build_app.py <ink_root> <out_dir> [game_root]
  2. Environment variables:  INK_ROOT, INK_OUT, GAME_ROOT
  3. Config file viewer.env  (KEY=VALUE, same keys, next to this script)
  4. Portable defaults:      ink_root  = ../game/InkExtracted  (repo layout:
                            this script is explorer/, data lives in ../game/),
                            out_dir = ./dist,
                            game_root = ../game/SovereignTowerCode
                            (quest data source, used by quest_data.py)

An explicit positional ink_root implies --from-disk.

No absolute/container paths are required anywhere.
"""

import collections
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

from quest_data import (set_game, collect_loc_keys, load_loc, load_quests)
from inventory_data import load_inventory, stats_text

LOCALES = ("en", "fr", "de", "cmn", "ja", "ko")
MARKER_RE = re.compile(r"\((BREAK_[A-Z0-9]+|NO_CLICK)\)")
TMP_RE = re.compile(r"^g-\d+$")
# compiler-generated containers inside knots: choice redirect stubs (c-N),
# conditional-branch stubs (b), hoisted choice-start labels (s-N), temp helpers (g-N)
AUTO_STITCH_RE = re.compile(r"^(c-\d+|b|s\d+|g-\d+)$")
# functions that only drive presentation/audio inside a choice stub — not shown
# as "what this choice causes" effects (kept as inline technical tokens instead)
PRESENTATION_FNS = frozenset({
    "Locutor", "SwapExpression", "FlashScreen", "Disparition", "Apparition",
    "InstructionSound", "TriggerCustomAnimation", "RevealLUT", "HideLUT",
    "BlackScreenRequested", "EllipseAnimationRequested", "WhiteScreenRequested",
})
# game-API functions whose first argument names a game-state variable that the
# call *writes*. The compiler only ever emits these args as `VAR?` reads (there
# is no matching `VAR=`), so without this table sovereign values, satisfaction,
# affinities, quest/unlock flags, etc. would never register as "written".
WRITE_SLOT0_FUNCS = frozenset({
    "UpdateSovereignValue", "UpdateSatisfaction", "UpdateKnightAffinity",
    "UpdateServantRomance", "UnlockQuest", "UnlockTag", "UnlockAudienceRequest",
    "UnlockFillerAudiencesPack", "UnlockEquipment", "RemoveEquipment",
    "ChangeTaxes", "KnightRecruitment", "KnightDemission", "CountyRallied",
    "CountyUnrallied", "CountyQuestFailed", "MajorCharacterIntroduction",
    "NewCharacterRomanced", "AddDoleanceForNextCycle", "InjectMurderedKnight",
    "KillKnight", "LocationDestroyed", "UltimatumTriggered",
})


def is_effect_fn(name):
    """True when a fn call is a real game-state consequence (not presentation)."""
    if name.startswith("set:"):
        return True
    return name not in PRESENTATION_FNS
# keys that mark a dict as a content-op (vs a named-children dict)
CONTENT_OPS = ("f()", "VAR?", "VAR=", "temp=", "list=", "->", "^->", "^<-",
               "*", "flg", "->t->", "CNT?")
# binary operators that may appear as bare strings inside an ev frame
BINARY_OPS = {"==", "!=", "<", ">", "<=", ">=", "&&", "||",
              "+", "-", "*", "/", "%"}


def expr_to_infix(parts):
    """Render a postfix expression (e.g. ['kind_value','highest','>']) as infix."""
    items = [list(p) if isinstance(p, list) else p for p in (parts or [])]
    stack = []
    for p in items:
        if p == "!":
            if stack:
                stack[-1] = "!" + stack[-1]
        elif p in BINARY_OPS:
            if len(stack) >= 2:
                b = stack.pop()
                a = stack.pop()
                stack.append(f"{a} {p} {b}")
        else:
            stack.append(str(p))
    return " ".join(stack) if stack else ""


def tail_path(path: str) -> str:
    """Last meaningful segment of an ink path ('.^.^.^.follow_up' -> 'follow_up')."""
    segs = [s.strip("^") for s in str(path).split(".")]
    segs = [s for s in segs if s]
    return segs[-1] if segs else ""


def stringify_args(args) -> list:
    """Normalize call-site argument values for display (bools/ints -> literals)."""
    out = []
    for a in args:
        if a is True:
            out.append("true")
        elif a is False:
            out.append("false")
        else:
            out.append(str(a))
    return out


def is_named_children(item) -> bool:
    """True when a dict maps stitch names -> sub-containers (vs a content-op dict)."""
    if not isinstance(item, dict) or not item:
        return False
    names = [k for k in item if k not in ("#f", "#n", "#t")]
    if not names:
        return False
    for k in names:
        if (k.startswith("^") or k in CONTENT_OPS
                or not isinstance(item[k], (list, dict))):
            return False
    return True


def is_bare_temp(tok) -> bool:
    """True when a token is a bare `set:temp=` write (no RHS, single target)."""
    return (tok[0] == "3" and tok[1] == "set:temp="
            and len(tok) == 3 and len(tok[2]) == 1)


def is_plumbing_write(tok) -> bool:
    """Compiler-internal temp writes ($r etc, string-interpolation plumbing)."""
    return (tok[0] == "3" and tok[1] == "set:temp=" and tok[2]
            and str(tok[2][0]).startswith("$"))


def walk_tokens(tokens):
    """Yield every token, descending into per-choice follow-up streams.

    Choice-stub follow-ups are stored nested on the choice token (index 7) so
    mutually-exclusive choice content is not flattened into one sequential flow.
    Metadata scans that need every game call must traverse them.
    """
    for t in tokens:
        if not isinstance(t, list) or not t:
            continue
        yield t
        if t[0] == "2" and len(t) > 7 and isinstance(t[7], list):
            yield from walk_tokens(t[7])


def fold_param_runs(tok):
    """Fold runs of bare `temp=` writes into the stitch header that precedes them.

    A parameterized stitch compiles its parameter list as consecutive bare
    `{"temp=": name}` writes at the top of the container (in reverse order,
    because arguments are popped off the eval stack). Grouping them onto the
    header keeps the flow readable and shows the real signature:
        ["5", "ask_for_light", ["is_audacious_highest", ...]]  ->  "name(p, …)"
    """
    out = []
    i = 0
    n = len(tok)
    while i < n:
        t = tok[i]
        if t[0] == "5" and i + 1 < n and is_bare_temp(tok[i + 1]):
            params = []
            j = i + 1
            while j < n and is_bare_temp(tok[j]):
                params.append(tok[j][2][0])
                j += 1
            params.reverse()  # compiled order is the reverse of declaration order
            out.append(["5", t[1], params])
            i = j
            continue
        out.append(t)
        i += 1
    return out

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_ENV_FILE = SCRIPT_DIR / "viewer.env"


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


def resolve_paths(argv: list) -> tuple:
    """Resolve (ink_root, out_dir, game_root) from CLI args, env, viewer.env or defaults."""
    cfg = load_config()
    ink_arg = argv[0] if len(argv) > 0 else ""
    out_arg = argv[1] if len(argv) > 1 else ""
    game_arg = argv[2] if len(argv) > 2 else ""

    def pick(arg, env_key):
        if arg:
            return arg
        return os.environ.get(env_key) or cfg.get(env_key) or ""

    ink_root = pick(ink_arg, "INK_ROOT")
    out_dir = pick(out_arg, "INK_OUT")
    game_root = pick(game_arg, "GAME_ROOT")

    def coerce(p, default):
        if not p:
            return default
        return Path(p).expanduser().resolve()

    default_ink = (SCRIPT_DIR.parent / "game" / "InkExtracted")
    ink_root = coerce(ink_root, default_ink)
    out_dir = coerce(out_dir, (SCRIPT_DIR / "dist"))
    # game project root: sibling of the ink extraction dir by default
    default_game = (default_ink.parent / "SovereignTowerCode")
    game_root = coerce(game_root, default_game)
    return ink_root, out_dir, game_root


class Profile:
    """Lightweight wall/CPU phase instrumentation for the build (--profile).

    tick(label) records a waypoint (cumulative wall+CPU since construction);
    report() diffs consecutive waypoints into per-phase rows sorted by wall
    time and prints them. stdlib-only (time.perf_counter / time.process_time)
    and a no-op when disabled, so the timing overhead is ~1µs per waypoint.
    """

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.segments = []  # (label, wall, cpu) — cumulative since __init__
        self._base_w = time.perf_counter() if enabled else 0.0
        self._base_c = time.process_time() if enabled else 0.0

    def tick(self, label: str) -> None:
        if not self.enabled:
            return
        self.segments.append((label, time.perf_counter() - self._base_w,
                              time.process_time() - self._base_c))

    def report(self, stream=sys.stdout) -> None:
        if not self.enabled or not self.segments:
            return
        self.tick("done")
        rows = []
        prev_w = prev_c = 0.0
        for label, w, c in self.segments:
            rows.append([label, w - prev_w, c - prev_c])
            prev_w, prev_c = w, c
        total_w = sum(r[1] for r in rows)
        total_c = sum(r[2] for r in rows)
        print("", file=stream)
        print("Build phases (wall | cpu | %% of wall):", file=stream)
        for label, wall, cpu in sorted(rows, key=lambda r: -r[1]):
            pct = (100.0 * wall / total_w) if total_w else 0.0
            print("  %-46s %8.3fs %8.3fs %5.1f%%" % (label, wall, cpu, pct),
                  file=stream)
        print("  %-46s %8.3fs %8.3fs %5.1f%%" % ("TOTAL", total_w, total_c, 100.0),
              file=stream)


def parse_flags(argv: list) -> tuple:
    """Split mode flags from positional args.

    Returns (flags, positionals):
      flags["extract_ink"]  dir or None   (--extract-ink [dir])
      flags["save_ink"]     dir or None   (--save-ink [dir])
      flags["from_disk"]    bool          (--from-disk)
      flags["profile"]      bool          (--profile, per-phase build timings)
      flags["help"]         bool          (--help / -h)
    The optional flag values are consumed only when the next token does not
    start with "--"."""
    flags = {"extract_ink": None, "save_ink": None, "from_disk": False,
             "profile": False, "help": False}
    positionals = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--help", "-h"):
            flags["help"] = True
        elif a == "--from-disk":
            flags["from_disk"] = True
        elif a == "--profile":
            flags["profile"] = True
        elif a in ("--extract-ink", "--save-ink"):
            key = "extract_ink" if a == "--extract-ink" else "save_ink"
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                flags[key] = argv[i + 1]
                i += 1
        else:
            positionals.append(a)
        i += 1
    return flags, positionals


def extract_stories(game_root: Path) -> dict:
    """Decode all locale ink stories in-memory from the game's .res chain.

    Returns {locale: story_dict}. Requires `zstandard` — a hard error when it
    is missing, so the user installs it instead of silently degrading."""
    try:
        import zstandard  # noqa: F401
    except ImportError:
        sys.exit("ERROR: in-memory ink extraction needs the `zstandard` pip package "
                 "(pip install zstandard). Alternatively provide extracted knots "
                 "under game/InkExtracted and build with --from-disk.")
    from ink_extract import extract_ink_story, story_locations

    locs = {locale: res for res, locale in story_locations(Path(game_root))}
    if not locs:
        sys.exit("ERROR: no story/*/master.ink.json.import under %s — the in-memory "
                 "extraction needs the game's .res chain (build with --from-disk "
                 "instead, or point GAME_ROOT at the right project)." % game_root)
    stories = {}
    for locale in LOCALES:
        res = locs.get(locale)
        if res is None:
            print("WARNING: no ink resource found for locale %s" % locale, file=sys.stderr)
            continue
        story, _info = extract_ink_story(res)
        stories[locale] = story
    return stories


def write_stories(stories: dict, out_dir: Path) -> None:
    """Persist extracted stories as <out_dir>/<locale>/master.ink.json
    (same format as ink_extract.py's standalone output)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for locale, story in stories.items():
        loc_dir = out_dir / locale
        loc_dir.mkdir(parents=True, exist_ok=True)
        (loc_dir / "master.ink.json").write_text(
            json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")


def story_knots(story: dict) -> dict:
    """Top-level named knots of a compiled ink story (skips "global decl" / "#f")."""
    named = story["root"][-1]
    return {k: v for k, v in named.items() if k not in ("global decl", "#f")}

# --------------------------------------------------------------------------
# knot classification (mirrors the game's naming conventions, from index_ink.py)
# --------------------------------------------------------------------------
# Trees that can never hold the data this scan looks for: plugin/asset dirs with
# no game-driven variable access. Skipping them keeps the walk (and its I/O) off
# ~1.3GB of vendored plugin binaries (addons/sentry) and asset resources.
# `content/`/`scenes/`/`systems/` hold the real game logic and are NOT skipped.
GAME_SIDE_SKIP_DIRS = frozenset({".godot", ".git", "exported", "tmp", "reports",
                                 "addons", "graphics", "fonts"})


GAME_SIDE_CODE_EXTS = frozenset({".gd", ".cs"})


def game_side_referenced_vars(game_root, variables):
    """Return the subset of ink variables the game engine reads/writes directly.

    Matches the two authoritative access paths only — `get_variable("x")` /
    `set_variable("x", …)` calls in Godot/C# scripts and the
    `ink_variables_to_reset` array (the vars the save system persists). A bare
    quoted identifier elsewhere (e.g. an audience-request resource whose id
    happens to share the flag's name) is NOT treated as consumption. Empty when
    game_root is unavailable.
    """
    if not variables or not game_root or not Path(game_root).is_dir():
        return set()
    names = set()
    re_access = re.compile(r'(?:get_variable|set_variable)\s*\(\s*"([A-Za-z0-9_]+)"')
    re_reset = re.compile(r'ink_variables_to_reset\s*=\s*\[(.*?)\]', re.S)
    for root, dirs, files in os.walk(game_root):
        dirs[:] = [d for d in dirs if d not in GAME_SIDE_SKIP_DIRS]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            # Only source/resource files can match; everything else (binaries,
            # .res/.import/.png/.ctex caches, ...) is skipped WITHOUT opening it.
            if ext not in GAME_SIDE_CODE_EXTS and ext not in (".tscn", ".tres"):
                continue
            try:
                with open(os.path.join(root, fn), encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            if ext in GAME_SIDE_CODE_EXTS:
                names.update(re_access.findall(text))
            else:
                for block in re_reset.findall(text):
                    names.update(re.findall(r'"([A-Za-z0-9_]+)"', block))
    return {v for v in variables if v in names}


def classify(name: str) -> str:
    if name[0].isupper():
        return "game_api_function"
    if name.startswith("candidature_"):
        return "candidacy_audience"
    if name.startswith("conversation_"):
        return "knight_knight_conversation"
    if name.startswith("county_quest_"):
        return "county_quest"
    if name.startswith("scriptedquest_"):
        return "scripted_quest"
    if name.startswith("scriptedgrievance_"):
        return "scripted_grievance"
    if name.startswith("grievance_"):
        return "grievance"
    if "_grievance_" in name:
        return "county_grievance"
    if name.startswith("ultimatum_"):
        return "ultimatum"
    if name.startswith("knight_leaving_"):
        return "knight_leaving"
    if name.endswith("_ending") or "ending_cutscene" in name or "ending_" in name:
        return "ending"
    if "_affinity" in name:
        return "affinity_conversation"
    if "come_back_later" in name:
        return "come_back_later"
    if "_recruit" in name or "candidacy" in name:
        return "recruitment"
    if name.startswith("intervention_"):
        return "intervention"
    if "intro" in name:
        return "intro_cutscene"
    if name.startswith("demon_"):
        return "demon"
    if name.startswith("traitors_plot") or name.startswith("lost_child"):
        return "traitors_plot"
    if "_reaction" in name:
        return "reaction"
    return "misc"


def ink_container(node):
    """Split an ink container into (content_list, named_children_dict)."""
    content, named = [], {}
    if isinstance(node, dict):
        return [node], {}
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict):
                if is_named_children(item) or "#f" in item:
                    named.update(item)
                else:
                    content.append(item)
            else:
                content.append(item)
    return content, named


# --------------------------------------------------------------------------
# per-knot dialogue walker -> token stream
# --------------------------------------------------------------------------
class Walker:
    def __init__(self):
        self.tok = []
        self.frames = []
        self.in_str = 0
        self.label = []
        self.reqs = []
        self.speaker = ""
        self.last_text = ""
        self.speaker_counts = collections.Counter()
        self.markers = collections.Counter()
        self.choices = 0
        self.last_cond = None      # pending choice condition: {"ops": [[name, neg], ...]}
        self._fresh_value = False  # a value frame closed on the last /ev (RHS for the next write)
        self.cond_stack = []       # open if/else blocks: {"vars": [...], "expr": str, "in_else": bool}
        self.then_pending = False  # a then-branch just closed; next item decides else-vs-endif
        self.pending = []          # [{idx, tail, done}] choices awaiting dest/effect resolution
        self.sem_writes = set()    # vars written via game-API fn calls (slot-0 arg)
        self.read_counts = collections.Counter()  # per-occurrence VAR? reads

    def emit(self, *args):
        self.tok.append(list(args))

    def is_text(self, s):
        return (s.startswith("^") and not s.startswith("^->")
                and not s.startswith("^<-") and not s.startswith("^|")
                and s not in ("^", "^^"))

    def push_text(self, raw, in_str):
        """Split inline (BREAK_n)/(NO_CLICK) markers out of a ^text run.

        All pieces belong to one in-game dialogue line: the first text chunk
        opens the line (token "0"), later chunks are flagged "c" (continuation,
        appended to the same line), and markers between chunks are flagged "i"
        (inline pause). The reader must not split one line into several.
        """
        text = raw
        pieces = []
        pos = 0
        for m in MARKER_RE.finditer(text):
            if m.start() > pos:
                pieces.append(("txt", text[pos:m.start()]))
            pieces.append(("mark", m.group(0)))
            self.markers[m.group(0)] += 1
            pos = m.end()
        if pos < len(text) or not pieces:
            pieces.append(("txt", text[pos:]))
        is_txt = [k == "txt" for k, _ in pieces]
        for i, (kind, chunk) in enumerate(pieces):
            if kind == "txt":
                if in_str:
                    self.label.append(chunk)
                else:
                    tok = ["0", chunk, self.speaker]
                    if any(is_txt[:i]):
                        tok.append("c")
                    self.emit(*tok)
                    self.last_text = chunk
            else:
                tok = ["1", chunk]
                if any(is_txt[:i]) and any(is_txt[i + 1:]):
                    tok.append("i")
                self.emit(*tok)

    def close_frame(self):
        if not self.frames:
            return
        frame = self.frames.pop()
        fn = frame.get("fn")
        if fn is None:
            self.last_cond = {"ops": [list(o) for o in frame.get("ops", [])],
                              "expr": list(frame.get("expr", [])),
                              "args": list(frame.get("args", []))}
            self._fresh_value = True
            return
        args = frame["args"]
        if fn == "Locutor":
            self.speaker = str(args[0]) if args else ""
            self.speaker_counts[self.speaker] += 1
            return
        if fn in WRITE_SLOT0_FUNCS and args:
            # slot-0 arg is the tracked variable the call mutates, but only when
            # it was pushed as a VAR? reference (never a literal constant).
            if frame.get("ops") and str(args[0]) == str(frame["ops"][0][0]):
                self.sem_writes.add(str(args[0]))
                if self.read_counts[str(args[0])] > 0:
                    self.read_counts[str(args[0])] -= 1
        if frame.get("internal"):
            # compiler hoisted label/divert call (e.g. . ^.s0) — no game function
            self.label = []
            return
        if self.label:
            # a str/ /str literal lived inside this function call: it is a
            # string argument, keep it out of the next choice label
            args.append("".join(self.label))
            self.label = []
        self.emit("3", fn, args)

    def _negate_vars(self, vars_):
        """Flip the `!` prefix on each variable name (for rendering an else gate)."""
        return [("" if v.startswith("!") else "!") + v.lstrip("!") for v in vars_]

    def _negate_expr(self, expr):
        """Logical negation of the gate's infix expression.

        Single bare vars get a `!` prefix; compound expressions are wrapped:
        `!(A && B)` — semantically correct via De Morgan without rewriting the
        operator tree.
        """
        if not expr:
            return ""
        if expr.startswith("!(") and expr.endswith(")"):
            return expr[2:-1]
        if expr.startswith("!") and not any(c in expr for c in (" ", "(", ")")):
            return expr[1:]
        if any(c in expr for c in (" ", "(", ")", "&", "|", "=", "<", ">", "+", "-", "/", "%")):
            return "!(" + expr + ")"
        return "!" + expr

    def _close_ifblock(self):
        """Emit the `"8"` endif for the most recent open block and pop it."""
        if self.cond_stack and not self.cond_stack[-1]["in_else"]:
            self.emit("8")
            self.cond_stack.pop()
        self.then_pending = False

    def item(self, it):
        if isinstance(it, list):
            for x in it:
                self.item(x)
            return
        # if/else bookkeeping: a then-branch just closed, so this item decides
        # whether an `else` container follows or the block simply ends (then a
        # stray unconditional divert to a `b` branch is the compiled `else`).
        if self.then_pending and self.cond_stack and not self.cond_stack[-1]["in_else"]:
            if (isinstance(it, dict) and "->" in it and not it.get("c")
                    and tail_path(it["->"]) == "b"):
                top = self.cond_stack[-1]
                self.emit("7", self._negate_vars(top["vars"]),
                          self._negate_expr(top["expr"]))
                top["in_else"] = True
            else:
                self._close_ifblock()
            self.then_pending = False
        if isinstance(it, str):
            if it == "ev":
                self.frames.append({"args": [], "ops": [], "expr": [],
                                    "fn": None, "internal": False})
            elif it == "/ev":
                self.close_frame()
            elif it == "out":
                # "out" terminates a function-call evaluation; the enclosing
                # ev frame stays open until its matching /ev (ink semantics).
                pass
            elif it == "pop":
                pass
            elif it == "str":
                self.in_str += 1
            elif it == "/str":
                self.in_str = max(0, self.in_str - 1)
            elif it == "!" and self.frames:
                ops = self.frames[-1]["ops"]
                if ops:
                    ops[-1][1] = not ops[-1][1]
                self.frames[-1].setdefault("expr", []).append("!")
            elif it in BINARY_OPS and self.frames:
                self.frames[-1].setdefault("expr", []).append(it)
            elif it == "end" and self.cond_stack:
                # an `end` opcode inside a conditional branch means that branch
                # ends the dialogue — surface it so the branch isn't invisible
                self.emit("4", "(end)")
            elif self.is_text(it):
                self.push_text(it[1:], self.in_str and len(self.label) < 200)
            return
        if not isinstance(it, dict):
            if isinstance(it, (bool, int, float)) and self.frames:
                lit = ("true" if it is True else "false" if it is False else str(it))
                self.frames[-1]["args"].append(lit)
                self.frames[-1]["expr"].append(lit)
            return
        if is_named_children(it):
            for name, child in it.items():
                if name in ("#f", "#n", "#t"):
                    continue
                self.process_named_child(name, child)
            return
        if "^->" in it:
            target = it["^->"]
            args = self.last_cond.get("args") if (self._fresh_value and self.last_cond) else None
            self._fresh_value = False
            self.last_cond = None
            if not self._internal_divert(target):
                if args:
                    self.emit("4", target, stringify_args(args))
                else:
                    self.emit("4", target)
            return
        if "^<-" in it:
            self._fresh_value = False
            return
        if "->" in it:
            target = it["->"]
            if it.get("c") and self.last_cond and self.last_cond["ops"]:
                cond = expr_to_infix(self.last_cond.get("expr", []))
                tok = ["7", [("!" if n else "") + v for v, n in self.last_cond["ops"]],
                       cond]
                if tail_path(target) == "b":
                    # inline conditional branch: its content (the adjacent "b"
                    # container) opens a visible block closed by an "8" endif.
                    tok.append("1")  # block-opening gate flag
                    self.cond_stack.append({"vars": [("!" if n else "") + v
                                                     for v, n in self.last_cond["ops"]],
                                            "expr": cond, "in_else": False})
                self.emit(*tok)
                self.last_cond = None
            args = self.last_cond.get("args") if (self._fresh_value and self.last_cond) else None
            self._fresh_value = False
            self.last_cond = None
            if not self._internal_divert(target):
                if args:
                    self.emit("4", target, stringify_args(args))
                else:
                    self.emit("4", target)
            return
        if "f()" in it and self.frames:
            f = self.frames[-1]
            f["fn"] = it["f()"]
            if "." in f["fn"]:
                f["internal"] = True
            for k, v in it.items():
                if k != "f()":
                    f["args"].append(str(v))
            return
        if "VAR?" in it and self.frames:
            name = str(it["VAR?"])
            self.frames[-1]["args"].append(name)
            self.frames[-1]["ops"].append([name, False])
            self.frames[-1]["expr"].append(name)
            self.read_counts[name] += 1
            return
        if "CNT?" in it and self.frames:
            tail = tail_path(it["CNT?"])
            self.frames[-1]["ops"].append([tail, False])
            self.frames[-1]["expr"].append(tail)
            return
        if isinstance(it.get("*"), str):
            label = "".join(self.label).strip()
            flg = it.get("flg")
            if not label:
                label = (self.last_text if (flg is None or (flg & 4)) else "")
            tail = tail_path(it.get("*") or "")
            reqs = list(self.reqs)
            if self.last_cond and self.last_cond["ops"]:
                reqs += [("!" if n else "") + v for v, n in self.last_cond["ops"]]
            self.emit("2", label, reqs, flg, tail, [])
            self.label = []
            self.reqs = []
            self.last_cond = None
            self._fresh_value = False
            self.pending.append({"idx": len(self.tok) - 1, "tail": tail, "done": False})
            self.choices += 1
            return
        if isinstance(it.get("*"), int):
            self.choices += 1
            return
        for k in it:
            if k in ("VAR=", "temp=", "list="):
                rhs = ""
                if it.get("re") and self.frames and self.frames[-1].get("expr"):
                    # in-place compound write (e.g. `temp x += 1`): the current
                    # open eval frame still holds the full assignment expression
                    rhs = expr_to_infix(self.frames[-1]["expr"])
                    self.frames[-1]["expr"] = []
                    self.frames[-1]["args"] = []
                elif self._fresh_value and self.last_cond and self.last_cond["expr"]:
                    rhs = expr_to_infix(self.last_cond["expr"])
                tok = [it[k]]
                if rhs:
                    tok.append(rhs)
                self.emit("3", "set:" + k, tok)
                self._fresh_value = False
                self.last_cond = None
                return

    def _internal_divert(self, target):
        """Compiler plumbing diverts (auto stubs, index jumps) are not shown."""
        t = tail_path(target)
        return bool(t) and (AUTO_STITCH_RE.match(t) or t.isdigit() or t.startswith("$"))

    def _patch_pending(self, tail, dest, effects, ended=False, loops=False,
                       args=None, followup=None):
        """Attach destination + side-effect calls to the first matching, unresolved choice.

        dest wins when the stub really redirects somewhere; otherwise a `(end)`
        / `(options)` marker tells the reader the choice closes the dialogue or
        loops back to the option list. `followup` (when provided) is the stub's
        own narrative/consequence token stream, attached to THIS choice card so
        mutually-exclusive stubs render as alternatives instead of being
        flattened into a single sequential flow.
        """
        for p in self.pending:
            if p["tail"] == tail and not p["done"]:
                tok = self.tok[p["idx"]]
                if dest:
                    tok[4] = dest
                elif ended:
                    tok[4] = "(end)"
                elif loops:
                    tok[4] = "(options)"
                else:
                    tok[4] = ""
                if effects:
                    tok[5] = list(effects)
                if followup is not None:
                    # index 7 is always the follow-up stream (6 = divert args)
                    if not args:
                        tok.insert(6, [])    # placeholder: this choice has no divert args
                    elif len(tok) < 7:
                        tok.append([])
                    if len(tok) < 8:
                        tok.append(list(followup))
                    else:
                        tok[7] = list(followup)
                elif args:
                    tok.insert(6, list(args))
                p["done"] = True
                return

    def _stub_info(self, child):
        """Walk a compiler redirect stub (c-N) -> (destination, effects, inline, has_text, ended, loops).

        The stub can be a pure redirect (choice -> divert) or hold real follow-up
        content. Returns:
          dest     first meaningful divert target ("" if none)
          effects  game-state fn calls the choice triggers (presentation skipped)
          inline   tokens worth showing in the flow (narrative / technical)
          has_text whether the stub contains real dialogue text
          ended    the stub ends the dialogue (end / return opcode)
          loops    the stub diverts back to the current container (re-offers options)
        """
        sub = Walker()
        sub.walk(child)
        self.sem_writes |= sub.sem_writes
        self.read_counts.update(sub.read_counts)
        dest = ""
        effects = []
        inline = []
        has_text = False
        ended = False
        loops = False
        args = []
        block_depth = 0
        for t in sub.tok:
            if t[0] == "4":
                d = tail_path(t[1])
                if d in ("(end)", "(options)"):
                    # synthesized branch-outcome marker (a branch that ends the
                    # dialogue or loops back to the options) — not a real target
                    inline.append(t)
                    continue
                if len(t) > 2:
                    args = list(t[2])
                if not d:
                    loops = True
                elif (d and not AUTO_STITCH_RE.match(d) and not d.isdigit()
                      and block_depth == 0 and not dest):
                    # only an unconditional, top-level divert names the choice's
                    # destination; a divert inside an if/else branch is shown
                    # inline (the branch gate decides where it actually leads)
                    dest = d
                if block_depth and d:
                    # a divert inside a conditional branch: keep it in the flow so
                    # the if/else block shows where each branch actually leads
                    # (otherwise a divert-only if/else would render as empty gates)
                    inline.append(t)
                elif block_depth and not d:
                    # a branch that loops back to the options: make its impact
                    # visible too (the choice card already shows the "(options)" dest)
                    inline.append(["4", "(options)"])
            elif t[0] == "3":
                if is_effect_fn(t[1]):
                    # game-state consequence: attach to the choice card only
                    effects.append([t[1], list(t[2]) if len(t) > 2 else []])
                else:
                    inline.append(t)
            elif t[0] == "0":
                has_text = True
                inline.append(t)
            elif t[0] == "7":
                inline.append(t)
                if len(t) > 3 and t[3] == "1":
                    block_depth += 1
            elif t[0] == "8":
                inline.append(t)
                block_depth = max(0, block_depth - 1)
            elif t[0] in ("1", "6", "2"):
                inline.append(t)
        raw = json.dumps(child)
        if '"end"' in raw or "->->" in raw:
            ended = True
        return dest, effects, inline, has_text, ended, loops, args

    def process_named_child(self, name, child):
        """Named child of a container: real stitches render, compiler stubs are folded."""
        if AUTO_STITCH_RE.match(name):
            if name.startswith("c-"):
                dest, effects, inline, has_text, ended, loops, args = self._stub_info(child)
                if has_text or inline:
                    # follow-up content is real narrative / consequences: attach it
                    # to THIS choice card (as an alternative branch), not to the
                    # shared flow — otherwise mutually-exclusive choice stubs
                    # flatten into a misleading sequential stream
                    self._patch_pending(name, dest or "", effects, ended, loops,
                                        args, followup=inline)
                else:
                    # pure redirect stub: summarise on the choice line only
                    self._patch_pending(name, dest or "", effects, ended, loops, args)
            elif name == "b" or TMP_RE.match(name):
                # conditional branch / temp helper: real inline flow, walk silently
                self.walk(child)
                if name == "b" and self.cond_stack:
                    if self.cond_stack[-1]["in_else"]:
                        # else branch done: this closes the surrounding if/else block
                        self.emit("8")
                        self.cond_stack.pop()
                    else:
                        # then branch done: the next sibling decides whether an
                        # `else` container follows or the block simply ends
                        self.then_pending = True
            return
        self._patch_pending(name, name, [])
        self.emit("5", name)
        self.walk(child)

    def walk(self, node):
        content, named = ink_container(node)
        for item in content:
            if isinstance(item, str):
                self.item(item)
            elif isinstance(item, list):
                for x in item:
                    self.item(x)
            elif isinstance(item, dict):
                self.item(item)
            else:
                self.item(item)
        if self.then_pending and self.cond_stack and not self.cond_stack[-1]["in_else"]:
            self._close_ifblock()
        for name, child in named.items():
            if name.startswith("^") or name in ("#f", "#n", "#t"):
                continue
            self.process_named_child(name, child)


# --------------------------------------------------------------------------
# metadata pass (vars/funcs/diverts/choices/counts), mirrors index_ink.py
# --------------------------------------------------------------------------
def collect_meta(knot):
    meta = {"funcs": set(), "reads": set(), "writes": set(), "diverts": set(),
            "text_lines": 0, "chars": 0, "choices": 0}

    def visit(node):
        if isinstance(node, list):
            for x in node:
                visit(x)
        elif isinstance(node, dict):
            for k, v in node.items():
                if k == "f()":
                    if "." not in v:
                        meta["funcs"].add(v)
                elif k == "VAR?":
                    meta["reads"].add(v)
                elif k in ("VAR=", "temp=", "list="):
                    meta["writes"].add(v)
                elif k in ("->", "^->", "->t->") and isinstance(v, str):
                    t = tail_path(v)
                    if t and not AUTO_STITCH_RE.match(t):
                        meta["diverts"].add(t)
                elif k == "*":
                    meta["choices"] += 1
                visit(v)
        elif isinstance(node, str):
            if node.startswith("^"):
                t = node[1:]
                if not meta["text_lines"] or meta["text_lines"] < 0:
                    pass
                meta["text_lines"] += 1
                meta["chars"] += len(t)

    visit(knot)
    return meta


def finalize_tokens(tok):
    """Post-process a knot's token stream: fold stitch param runs into headers
    and strip a leading bare-temp run (a parameterized knot/function's params).

    Returns (tokens, leading_params) where leading_params is the reversed
    declaration-order parameter list of the knot itself ("" when none).
    """
    tok = [t for t in tok if not is_plumbing_write(t)]
    tok = fold_param_runs(tok)
    params = []
    while tok and is_bare_temp(tok[0]):
        params.append(tok[0][2][0])
        tok = tok[1:]
    params.reverse()
    return tok, params


def build_quests(out_dir: Path, unlock_map: dict) -> None:
    """Merge the quest resource data (quests.json) into dist/ and attach the
    ink-side "which knots unlock this quest" reverse map."""
    quests_data = load_quests()
    keys = collect_loc_keys(quests_data["quests"])
    quests_data["locales"] = ["en", "fr", "cmn", "de", "ja", "ko"]
    quests_data["loc"] = load_loc(keys)
    quests_data["unlock_knots"] = {qid: sorted(set(knots))
                                   for qid, knots in unlock_map.items()
                                   if qid in quests_data["quests"]}
    quests_data["stats"]["unlock_knots"] = len(quests_data["unlock_knots"])
    with open(out_dir / "quests.json", "w", encoding="utf-8") as f:
        json.dump(quests_data, f, ensure_ascii=False)
    return quests_data


def build_inventory(out_dir: Path, quests_data: dict,
                    equip_unlock: dict, equip_remove: dict, game_root: Path) -> None:
    """Emit dist/inventory.json: all equipment + purchase/quest/ink sources.

    Relies on quests.json (already written) for the item-stem -> quest reverse
    map and on the ink walker's UnlockEquipment/RemoveEquipment knot maps."""
    inv = load_inventory(quests_data=quests_data,
                         unlock_map=equip_unlock, remove_map=equip_remove,
                         game_root=str(game_root))
    with open(out_dir / "inventory.json", "w", encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False)
    from inventory_data import stats_text
    stats_txt = stats_text(inv["stats"])
    print("Inventory: " + stats_txt)


def build_knights(out_dir: Path, quests_data: dict, index: dict, game_root: Path) -> dict:
    """Emit dist/knights.json: all playable knights + dialogue/quest/ink links.

    Relies on quests.json (already written) for the knight -> quest reverse map
    and on index.json's speaker attribution for the ink story-knot lists.
    Returns the data dict (used by build_special for evolution notes)."""
    from knights_data import load_knights
    data = load_knights(quests_data=quests_data, index=index, game_root=str(game_root))
    with open(out_dir / "knights.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    s = data["stats"]
    print(f"Knights: {s['total']} knights · {s['ink_linked']} ink-linked · "
          f"{s['quest_linked']} quest-linked · {s['with_convs']} with conversations"
          + (f" · {s['evo_knights']} with evolution paths" if s.get("evo_knights") else ""))
    return data


def build_special(out_dir: Path, quests_data: dict, index: dict,
                  knights_data: dict, game_root: Path) -> dict:
    """Emit dist/special.json: the decoded SpecialInstruction catalog.

    Joins the ink knots that emit each instruction, the quests that grant it as
    a reward, and (for knight evolutions) the per-state stat/feature notes.
    Returns the data dict (used by the dialogues pass for its dlg reverse)."""
    from special_data import build_special as _build
    return _build(out_dir, quests_data, index, knights_data, game_root=str(game_root))


def build_audiences(out_dir: Path, quests_data: dict, index: dict,
                    game_root: Path) -> None:
    """Emit dist/audiences.json: the audience + audience-request catalog.

    Joins the game audience/request resources with the quest follow-up links
    (which quest fires each audience) and the request quest-reward links."""
    from audience_data import build_audiences as _build
    _build(out_dir, quests_data, index, game_root=str(game_root))


def build_dialogues(out_dir: Path, quests_data: dict, index: dict,
                    knights_data: dict, special: dict, game_root: Path) -> None:
    """Emit dist/dialogues.json: the free-time dialogue catalog.

    Joins the FreeTimeDialogue resources (affinity/conversation/reaction) with
    the affinity gates, conversation partners/exclusions/order and the unlock
    sources (ink UnlockSpecialDialogue knots, special.json dlg, code/item)."""
    from dialogue_data import build_dialogues as _build
    _build(out_dir, quests_data, index, knights_data, special,
           game_root=str(game_root))


def build_endings(out_dir, index, game_root: Path) -> None:
    """Emit dist/endings.json: the ending cutscene + vignette catalog.

    Parses the EndingManager's ending-type → cutscene knot map (act_manager.tscn
    + the Endings enum), the SWITCH_ENDING_*_PATH special-instruction names and
    the per-character ending_path vignettes (shared descriptor parser in
    dialogue_data)."""
    del index  # reserved: cross-knot consistency checks live in the tests
    from ending_data import build_endings as _build
    _build(out_dir, game_root=str(game_root))


def copy_web_assets(out_dir: Path) -> None:
    web = Path(__file__).resolve().parent / "web"
    if not web.exists():
        return
    for name in ("index.html", "app.js", "style.css"):
        src = web / name
        if src.exists():
            (out_dir / name).write_bytes(src.read_bytes())


HELP_TEXT = """\
Sovereign Tower — static viewer build.

USAGE
  python3 build_app.py [FLAGS] [ink_root] [out_dir] [game_root]

  Builds a browser-ready static dataset into <out_dir> from two sources:
    • the compiled ink story  (default: extracted in-memory from the game's
      .res chain, or read from <ink_root>/<locale>/master.ink.json with
      --from-disk), and
    • the Godot project tree  (game_root) — quests, audiences, inventory,
      knights, special instructions, localisations.
  Outputs: index.json, quests.json, inventory.json, knights.json,
  special.json, audiences.json, dialogues.json, locales/<locale>.json, plus
  the web assets (app.js, style.css, index.html) copied from explorer/web.

POSITIONAL ARGUMENTS
  ink_root    dir  Root that contains <locale>/master.ink.json files
                    (only used when ink is read from disk, i.e. --from-disk
                    or when an ink_root is given explicitly).
                    Default: ../game/InkExtracted  (relative to this script).
  out_dir     dir  Output directory for the generated static site.
                    Default: ./dist  (next to this script).
  game_root   dir  Root of the extracted Godot project (contains content/,
                    systems/, lang/). Quest/inventory/knights data source.
                    Default: ../game/SovereignTowerCode.

FLAGS
  -h, --help          Show this help and exit (no build runs).
  --from-disk         Read <ink_root>/<locale>/master.ink.json from disk instead
                      of extracting the ink in-memory from the game .res chain.
                      Missing locales are skipped with a warning.
                      (Giving an explicit positional ink_root implies this.)
  --extract-ink [dir] Ink extraction only — decode the ink stories and write
                      <dir>/<locale>/master.ink.json (default ../game/
                      InkExtracted), then exit. No build is performed.
  --save-ink [dir]    Build as normal, then ALSO write the extracted ink stories
                      to <dir>/<locale>/master.ink.json (default ../game/
                      InkExtracted).
  --profile           Print per-phase wall/CPU timings of the build.

MODES
  default           Extract ink in-memory from the game's .res chain (all 6
                    locales) and build. Requires the `zstandard` pip package
                    (pip install zstandard); hard error if missing.
  --extract-ink     Only decode the ink to disk, then exit.
  --save-ink        Build, then persist the decoded ink to disk.
  --from-disk       Build from pre-extracted master.ink.json files.

PATH RESOLUTION (higher wins)
  1. CLI positional args     python3 build_app.py <ink_root> <out_dir> <game_root>
  2. Environment variables   INK_ROOT, INK_OUT, GAME_ROOT
  3. Config file viewer.env  (KEY=VALUE, same keys, next to this script)
  4. Portable defaults       ink_root = ../game/InkExtracted
                             out_dir  = ./dist
                             game_root = ../game/SovereignTowerCode

ENVIRONMENT / CONFIG KEYS
  INK_ROOT   Same as positional ink_root.
  INK_OUT    Same as positional out_dir.
  GAME_ROOT  Same as positional game_root.

  viewer.env (optional, next to this script) uses the same keys, one per line,
  e.g.:
    GAME_ROOT = /path/to/SovereignTowerCode
    INK_ROOT = /path/to/InkExtracted
    INK_OUT = /path/to/out
  Relative values resolve against the working directory. Comment lines start
  with #. The file is ignored if absent.

RELATED STANDALONE SCRIPTS (same viewer.env)
  quest_data.py   game_root [quest_out]   Emit just dist/quests.json.
  ink_extract.py  game_root [out_dir]     Emit <out_dir>/<locale>/master.ink.json.

EXAMPLES
  python3 build_app.py                                          # default build
  python3 build_app.py --from-disk                              # use extracted ink on disk
  python3 build_app.py --extract-ink                            # only write master.ink.json
  python3 build_app.py C:\\Ink C:\\out C:\\Game                  # all paths explicit (Windows)
  set INK_ROOT=C:\\Ink && python3 build_app.py                   # via environment (Windows)
  GAME_ROOT=/srv/game INK_OUT=/tmp/out python3 build_app.py     # via environment (Linux)
"""


def print_help(argv: list = None) -> None:
    """Print build_app.py --help and, as a debugging aid, the paths that would
    actually be used, following the same resolution priority as the build."""
    argv = list(argv or [])
    print(HELP_TEXT)
    positionals = [a for a in argv if a not in ("--from-disk", "--profile", "--extract-ink",
                                                "--save-ink", "--help", "-h")]
    ink_root, out_dir, game_root = resolve_paths(positionals)
    cfg = load_config()
    cfg_keys = [k for k in ("INK_ROOT", "INK_OUT", "GAME_ROOT") if k in cfg]
    print("RESOLVED PATHS (as the build would use them)")
    print("  ink_root  = %s" % ink_root)
    print("  out_dir   = %s" % out_dir)
    print("  game_root = %s" % game_root)
    if cfg_keys:
        print("  (from viewer.env: %s)" % ", ".join(cfg_keys))
    else:
        print("  (no viewer.env overrides active)")
    for k in ("INK_ROOT", "INK_OUT", "GAME_ROOT"):
        v = os.environ.get(k)
        if v:
            print("  env %-9s = %s" % (k, v))


def main():
    flags, positionals = parse_flags(sys.argv[1:])
    if flags["help"]:
        print_help(sys.argv[1:])
        return
    ink_root, out_dir, game_root = resolve_paths(positionals)
    prof = Profile(flags["profile"])

    # --extract-ink: extraction only, no build
    if flags["extract_ink"] is not None:
        save_dir = Path(flags["extract_ink"]) if flags["extract_ink"] \
            else (SCRIPT_DIR.parent / "game" / "InkExtracted")
        stories = extract_stories(game_root)
        prof.tick("ink extract (in-memory)")
        write_stories(stories, save_dir)
        print("Extracted %d locales to %s" % (len(stories), save_dir))
        prof.tick("write master.ink.json")
        prof.report()
        return

    # ink source: in-memory from the game .res chain (default), or on-disk
    if flags["from_disk"] or positionals:
        stories = {}
        for locale in LOCALES:
            p = ink_root / locale / "master.ink.json"
            if p.is_file():
                with open(p, encoding="utf-8") as f:
                    stories[locale] = json.load(f)
        if not stories:
            sys.exit("ERROR: no master.ink.json found under %s (--from-disk mode). "
                     "Run without --from-disk for in-memory extraction, or place "
                     "extracted knots there (python3 build_app.py --extract-ink)."
                     % ink_root)
    else:
        stories = extract_stories(game_root)
    prof.tick("ink source (%s)" % ("from-disk load" if (flags["from_disk"] or positionals)
                                   else "in-memory extract"))
    missing = [loc for loc in LOCALES if loc not in stories]
    if "en" not in stories:
        sys.exit("ERROR: no en ink story available — the build needs the en locale.")

    set_game(game_root)
    locales_dir = out_dir / "locales"
    locales_dir.mkdir(parents=True, exist_ok=True)

    story, knots = stories["en"], story_knots(stories["en"])
    index = {"inkVersion": story.get("inkVersion"),
             "knots": {}, "speakers": {}, "variables": {}, "categories": {},
             "listDefs": story.get("listDefs", {}), "stats": {}}

    speaker_counts = collections.Counter()
    unlock_map = collections.defaultdict(list)  # quest id -> [knots that call UnlockQuest]
    equip_unlock = collections.defaultdict(list)  # canonical ID -> [knots that UnlockEquipment]
    equip_remove = collections.defaultdict(list)  # canonical ID -> [knots that RemoveEquipment]
    for name, knot in sorted(knots.items()):
        w = Walker()
        w.walk(knot)
        tok, params = finalize_tokens(w.tok)
        for t in walk_tokens(w.tok):
            if t[0] == "3" and t[1] == "UnlockQuest":
                for a in (t[2] or []):
                    if isinstance(a, str) and a and a != "false" and a != "true":
                        unlock_map[a].append(name)
            elif t[0] == "2" and len(t) > 5 and t[5]:
                for e in t[5]:
                    if e and e[0] == "UnlockQuest":
                        for a in (e[1] or []):
                            if isinstance(a, str) and a and a != "false" and a != "true":
                                unlock_map[a].append(name)
            elif t[0] == "3" and t[1] in ("UnlockEquipment", "RemoveEquipment"):
                args = t[2] or []
                if len(args) >= 2 and isinstance(args[1], str):
                    canon = args[1].upper()
                    (equip_remove if t[1] == "RemoveEquipment" else equip_unlock)[canon].append(name)
        m = collect_meta(knot)
        m["writes"] |= w.sem_writes
        m["reads"] = {v for v, n in w.read_counts.items() if n > 0}
        speakers = dict(w.speaker_counts)
        for s, c in speakers.items():
            speaker_counts[s] += c
        preview = ""
        for t in walk_tokens(w.tok):
            if t[0] == "0" and t[1].strip():
                preview = t[1].strip()
                break
        is_fn = isinstance(knot, list) and bool(knot) and knot[-1] == {"#f": 1}
        index["knots"][name] = {
            "c": classify(name),
            "fn": is_fn,
            "params": params,
            "lines": tok,
            "sp": speakers,
            "text": m["text_lines"], "chars": m["chars"],
            "choices": w.choices or m["choices"],
            "funcs": sorted(m["funcs"]),
            "reads": sorted(m["reads"]), "writes": sorted(m["writes"]),
            "diverts": sorted(m["diverts"]),
            "markers": dict(w.markers),
            "prev": preview[:140],
        }
    prof.tick("dialogue index (en walker)")

    # speakers, variables (en as the archetype), category counts, stats
    for s, c in speaker_counts.most_common():
        index["speakers"][s] = c
    var_usage = {}
    for kname, kdata in index["knots"].items():
        for v in kdata["reads"]:
            var_usage.setdefault(v, [0, 0])
            var_usage[v][0] += 1
        for v in kdata["writes"]:
            var_usage.setdefault(v, [0, 0])
            var_usage[v][1] += 1
    index["variables"] = {v: {"reads": n, "writes": w} for v, (n, w) in sorted(var_usage.items())}
    # game-side references: which ink variables the game engine itself reads or
    # writes (StoryController.get_variable/set_variable calls, ink_variables_to_reset
    # entries, quoted identifiers in .gd/.cs/.tscn/.tres). Used by the frontend to
    # tell a real "consumed game-side" flag apart from a vestigial one (no ink knot
    # reads it AND no game-side reference → may be dead data).
    for v in game_side_referenced_vars(game_root, list(index["variables"])):
        index["variables"].setdefault(v, {"reads": 0, "writes": 0})["gs"] = True
    prof.tick("game-side variable scan")
    index["funcs"] = {}
    for kname, kdata in index["knots"].items():
        for f in kdata["funcs"]:
            index["funcs"][f] = index["funcs"].get(f, 0) + 1
    index["categories"] = dict(collections.Counter(k["c"] for k in index["knots"].values()))
    index["stats"] = {
        "locales": len(LOCALES),
        "knots": len(index["knots"]),
        "text_lines": sum(k["text"] for k in index["knots"].values()),
        "text_chars": sum(k["chars"] for k in index["knots"].values()),
        "choices": sum(k["choices"] for k in index["knots"].values()),
        "speakers": len(index["speakers"]),
        "variables": len(index["variables"]),
    }

    # list of knot names per category (frontend grouping) -> keep categories as counts only

    with open(out_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    prof.tick("index.json write")

    quests_data = build_quests(out_dir, unlock_map)
    prof.tick("quests pass")
    build_inventory(out_dir, quests_data, dict(equip_unlock), dict(equip_remove), game_root)
    prof.tick("inventory pass")
    knights_data = build_knights(out_dir, quests_data, index, game_root)
    prof.tick("knights pass")
    special_data = build_special(out_dir, quests_data, index, knights_data, game_root)
    prof.tick("special pass")
    build_audiences(out_dir, quests_data, index, game_root)
    prof.tick("audiences pass")
    build_dialogues(out_dir, quests_data, index, knights_data, special_data, game_root)
    prof.tick("dialogues pass")
    build_endings(out_dir, index, game_root)
    prof.tick("endings pass")

    # other locales: token-only overrides (metadata identical to en)
    for locale in LOCALES:
        if locale == "en" or locale not in stories:
            continue
        lstory, lknots = stories[locale], story_knots(stories[locale])
        loc = {}
        for name, knot in lknots.items():
            w = Walker()
            w.walk(knot)
            tok, _ = finalize_tokens(w.tok)
            loc[name] = tok
        with open(locales_dir / ("%s.json" % locale), "w", encoding="utf-8") as f:
            json.dump(loc, f, ensure_ascii=False, separators=(",", ":"))
    prof.tick("non-en locale passes")

    if missing:
        print("WARNING: skipped missing locales: %s" % ", ".join(missing), file=sys.stderr)
        print("Regenerate with: python3 build_app.py --extract-ink", file=sys.stderr)

    if flags["save_ink"] is not None:
        save_dir = Path(flags["save_ink"]) if flags["save_ink"] \
            else (SCRIPT_DIR.parent / "game" / "InkExtracted")
        write_stories(stories, save_dir)
        print("Saved extracted ink to %s" % save_dir)
        prof.tick("save extracted ink")

    copy_web_assets(out_dir)
    prof.tick("web assets copy")
    print("Wrote %s" % out_dir)
    print(json.dumps(index["stats"], indent=1))
    prof.report()


if __name__ == "__main__":
    main()
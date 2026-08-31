#!/usr/bin/env python3
"""
Sovereign Tower — code-played scanner.

Finds knots / audiences that are referenced directly in game code (GDScript/C# /
scene resources) instead of via the data-driven channels (quest unlock, audience
rq/dir/fl/ci/um/dd/qf, special auds, filler, director). This is the “code” channel
that previously was hardcoded for 4 audiences (edith_gimmick…); the scanner
generalises it and also covers intro knots that are played via _play_dialogue /
StoryController.goto from ServantRoom subclasses.

The scan is stdlib-only, mirrors build_app.py:game_side_referenced_vars, and is
deliberately conservative: only quoted strings that exactly equal a known knot
or audience stem (or a res://…/*.tres path whose stem does) are counted, and
the file must be a code file (.gd/.cs/.tscn) — not a data .tres. The surrounding
snippet is kept so the frontend can render “played via code in map_room.gd:4”.
"""

import os
import re
from pathlib import Path

# Reuse the same skip list as build_app.py so the walk stays off vendored
# plugins and asset caches.
GAME_SIDE_SKIP_DIRS = frozenset({".godot", ".git", "exported", "tmp", "reports",
                                  "addons", "graphics", "fonts"})
CODE_EXTS = frozenset({".gd", ".cs", ".tscn"})

# quoted strings: "foo" or 'foo' or &"foo" (StringName). We capture the inner
# value via the first group that matches.
QUOTED_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'')


def _stem_from_res_path(s: str):
    """If s looks like res://…/foo.tres, return foo, else None."""
    if "res://" not in s or ".tres" not in s:
        return None
    # take last segment after / and strip extension / query
    base = s.rsplit("/", 1)[-1]
    base = base.split(":", 1)[0]
    if base.endswith(".tres"):
        base = base[:-5]
    # stems are lowercase with underscores; validate cheaply
    if base and re.match(r'^[a-z0-9_]+$', base):
        return base
    return None


def collect_code_plays(game_root, knot_set=None, audience_set=None):
    """
    Walk game_root and return {knot: [(rel_path, line_no, snippet)],
                               audience: [(rel_path, line_no, snippet)]}.
    knot_set / audience_set are sets of known ids (from index/audience catalog).

    Knots: .gd/.cs files that define a const/var holding a knot literal
           (e.g. `const X = "knot"`) and later play it via _play_dialogue /
           StoryController.goto are resolved via variable indirection, so the
           *play* line is recorded, not just the definition. Direct literal
           plays (StoryController.goto("knot")) are also caught. Files like
           achievement_manager / quest_cutscene_logic are ignored — they check
           played_knots but don't play them.
    Audiences: only .gd/.cs with an audience hint (add_audience etc.) — .tscn
           filler tables are ignored.
    """
    knot_set = set(knot_set or [])
    audience_set = set(audience_set or [])
    knot_plays = {}
    audience_plays = {}

    seen_knot = set()
    seen_aud = set()

    AUDIENCE_HINT_RE = re.compile(r'StoryController\.goto|_play_dialogue|add_audience|audience_unlocked', re.I)
    KNOT_PLAY_RE = re.compile(r'_play_dialogue|StoryController\.goto|goto\s*\(|dialogue_path|ink_path')
    # const/var that holds a knot string: const NAME = "knot"  or var NAME: String = "knot"
    VAR_DEF_RE = re.compile(r'(?:const|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*String(?:Name)?)?\s*=\s*"([^"]+)"')

    # files that are not play sites (they check, not play)
    SKIP_FILES = {"achievement_manager.gd", "quest_cutscene_logic.gd", "audio_manager.gd"}

    game_root = Path(game_root)
    if not game_root.is_dir():
        return knot_plays, audience_plays

    for root, dirs, files in os.walk(game_root):
        dirs[:] = [d for d in dirs if d not in GAME_SIDE_SKIP_DIRS]
        for fn in files:
            if fn in SKIP_FILES:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext not in CODE_EXTS:
                continue
            is_tscn = ext == ".tscn"
            # audiences: ignore .tscn entirely
            if is_tscn and fn not in ("story_controller.tscn",):
                # keep story_controller.tscn for knot StringName exports that are
                # divert targets (southbay_divert etc.), but otherwise skip
                pass
            fpath = os.path.join(root, fn)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except OSError:
                continue
            rel = os.path.relpath(fpath, game_root)
            text = "".join(lines)

            # file-level play hints: only files that actually play dialogue/audiences
            # are considered code sources. This excludes achievement_manager checks
            # (played_audiences) and audio tables.
            is_knot_play_file = bool(KNOT_PLAY_RE.search(text))
            is_audience_play_file = bool(AUDIENCE_HINT_RE.search(text))

            # build var -> knot map for this file (for indirection)
            var_to_knot = {}
            for m in VAR_DEF_RE.finditer(text):
                var_name, lit = m.group(1), m.group(2).strip()
                if lit in knot_set:
                    var_to_knot[var_name] = lit

            for i, line in enumerate(lines, 1):
                if '"' not in line and "'" not in line and not var_to_knot:
                    # still need to check var usage even without quote on play line
                    has_audience_hint = is_audience_play_file and bool(AUDIENCE_HINT_RE.search(line))
                    has_knot_play = is_knot_play_file and bool(KNOT_PLAY_RE.search(line))
                    if has_knot_play and var_to_knot:
                        for var_name, knot in var_to_knot.items():
                            if re.search(r'\b' + re.escape(var_name) + r'\b', line):
                                key = (knot, rel, i)
                                if key not in seen_knot:
                                    seen_knot.add(key)
                                    snippet = line.strip()[:120]
                                    knot_plays.setdefault(knot, []).append((rel, i, snippet))
                    continue
                has_audience_hint = is_audience_play_file and bool(AUDIENCE_HINT_RE.search(line))
                has_knot_play = is_knot_play_file and bool(KNOT_PLAY_RE.search(line))

                # direct literal knots — only in play files
                if is_knot_play_file and ('"' in line or "'" in line):
                    for m in QUOTED_RE.finditer(line):
                        s = m.group(1) if m.group(1) is not None else m.group(2)
                        if not s:
                            continue
                        s = s.strip()
                        if s in knot_set:
                            if is_tscn and not has_knot_play:
                                continue
                            key = (s, rel, i)
                            if key not in seen_knot:
                                seen_knot.add(key)
                                snippet = line.strip()[:120]
                                knot_plays.setdefault(s, []).append((rel, i, snippet))
                if not is_tscn and has_audience_hint and ('"' in line or "'" in line):
                    for m in QUOTED_RE.finditer(line):
                        s = m.group(1) if m.group(1) is not None else m.group(2)
                        if not s:
                            continue
                        s = s.strip()
                        if s in audience_set:
                            key = (s, rel, i)
                            if key not in seen_aud:
                                seen_aud.add(key)
                                snippet = line.strip()[:120]
                                audience_plays.setdefault(s, []).append((rel, i, snippet))
                        stem = _stem_from_res_path(s)
                        if stem and stem in audience_set:
                            key = (stem, rel, i)
                            if key not in seen_aud:
                                seen_aud.add(key)
                                snippet = line.strip()[:120]
                                audience_plays.setdefault(stem, []).append((rel, i, snippet))

                # variable indirection: line contains _play_dialogue(VAR) or goto(VAR)
                if has_knot_play and var_to_knot:
                    for var_name, knot in var_to_knot.items():
                        if re.search(r'\b' + re.escape(var_name) + r'\b', line):
                            key = (knot, rel, i)
                            if key not in seen_knot:
                                seen_knot.add(key)
                                snippet = line.strip()[:120]
                                knot_plays.setdefault(knot, []).append((rel, i, snippet))

    return knot_plays, audience_plays


def format_code_note(rel, line_no, snippet):
    """Human note for frontend: 'scenes/rooms/shops/map_room.gd:4 — const ARLIN_INTRODUCTION = \"arlin_map_introduction\"'"""
    # keep rel short: if path starts with scenes/ or systems/, keep as is
    return f"{rel}:{line_no} — {snippet}"


# CLI for manual testing
if __name__ == "__main__":
    import json
    import sys
    from quest_data import QuestIndex, load_audience_catalog, set_game
    root = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent.parent / "game" / "SovereignTowerCode")
    set_game(root)
    idx = QuestIndex()
    # load index knots via build_app story? fallback: read dist/index.json if exists
    dist_idx = Path(__file__).parent / "dist" / "index.json"
    if dist_idx.exists():
        idx_data = json.load(open(dist_idx, encoding="utf-8"))
        knots = set(idx_data["knots"].keys())
    else:
        knots = set()
    auds = load_audience_catalog(idx)
    audience_set = set(auds.keys())
    kp, ap = collect_code_plays(root, knots, audience_set)
    print(f"knots code-played: {len(kp)}")
    for k, v in sorted(kp.items())[:20]:
        print(f"  {k}: {v[:2]}")
    print(f"audiences code-played: {len(ap)}")
    for a, v in sorted(ap.items())[:20]:
        print(f"  {a}: {v[:2]}")

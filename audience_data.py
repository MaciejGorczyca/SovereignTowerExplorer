#!/usr/bin/env python3
"""Sovereign Tower — audience catalog extractor.

Emits `dist/audiences.json`: the full audience + audience-request domain, the
reverse links the Quests tab and the "Where it comes from" knot section need,
and the request → quest-reward join. A companion pass to `quest_data.py`, which
keeps the same 511-entry audience catalog inside `quests.json` for the quest
drawer's "Follow-up audiences" rows; this file adds the request catalog and the
reverse "which quest fires this audience" map that only the Audiences tab uses.

Sources:
1. `content/audiences/**/*.tres`           — the 511 `Audience` resources
   (ink knot, folder, characters, decoded firing requirements).
2. `content/audience_requests/*.tres`      — the 34 `AudienceRequest` resources
   (request_name/description loc keys, character, follow-up audience, cost,
   hidden flag, excluding conditions, audiences to remove).
3. dist/quests.json                        — which quest fires each audience as a
   success/failure/unexpected follow-up (`rev.qf`), and which quests grant each
   request as an AUDIENCE_REQUEST reward (request `q`).

Output shape (dist/audiences.json):
  audiences:  { "<stem>": {k, f, c, rq} }       same schema as quests.json
  requests:   { "<stem>": {n, d, ch, ck, hd, cst, fua, exc?, rem?, q?} }
  rev.qf:     { "<audience stem>": [{q, k}, ...] }   k ∈ success/failure/unexpected
  stats:      header counts
"""

import collections
import json
import os
import sys
from pathlib import Path

from quest_data import (QuestIndex, TresFile, _ref_stem, set_game,
                        load_audience_catalog)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GAME_ROOT = (SCRIPT_DIR.parent / "game" / "SovereignTowerCode").resolve()

GAME = str(DEFAULT_GAME_ROOT)


def set_audience_root(root):
    """Point this module's GAME at a given game root (see build_app)."""
    global GAME
    GAME = str(Path(root).expanduser().resolve())


def _stem(ref, filer):
    """Resolve an ExtResource/SubResource ref to its file stem (or None)."""
    return _ref_stem(ref, filer)


def load_audience_requests(idx):
    """Parse content/audience_requests/*.tres -> {stem: request dict}.

    Each request carries its loc keys, the resolved character descriptor stem +
    name key, the follow-up audience stem, cost, hidden flag and the audience
    stems its excluding_conditions / audiences_to_remove reference.
    """
    req_dir = f"{GAME}/content/audience_requests"
    requests = {}
    if not os.path.isdir(req_dir):
        return requests
    for fn in sorted(os.listdir(req_dir)):
        if not fn.endswith(".tres"):
            continue
        path = os.path.join(req_dir, fn)
        tf = TresFile.load(path, req_dir)
        P = tf.props
        stem = os.path.splitext(fn)[0]
        entry = {
            "n": P.get("request_name", ""),
            "d": P.get("description", ""),
            "hd": bool(P.get("character_hidden", False)),
            "cst": int(P.get("audience_request_cost", 10)),
        }
        ch = P.get("character")
        chstem = _stem(ch, tf) if ch else None
        if chstem:
            entry["ch"] = chstem
            entry["ck"] = idx.char_stems.get(chstem) or chstem
        fu = P.get("follow_up_audience")
        fustem = _stem(fu, tf) if fu else None
        if fustem:
            entry["fua"] = fustem
        exc = []
        for x in P.get("excluding_conditions", []) or []:
            if not isinstance(x, dict) or "_sub" not in x:
                continue
            props = tf.sub_props(x["_sub"])
            aud = props.get("audience")
            if aud:
                estem = _stem(aud, tf)
                if estem and estem not in exc:
                    exc.append(estem)
        if exc:
            entry["exc"] = exc
        rem = []
        for x in P.get("audiences_to_remove", []) or []:
            if x in (None, "null"):
                continue
            rstem = _stem(x, tf)
            if rstem and rstem not in rem:
                rem.append(rstem)
        if rem:
            entry["rem"] = rem
        requests[stem] = entry
    return requests


def _request_quest_links(quests_data):
    """Scan quest rewards (success/failure + modifier variants) for
    AUDIENCE_REQUEST grants -> {request stem: [quest ids]}."""
    request_value = None
    for entry in (quests_data.get("enums") or {}).get("RewardType", []):
        if len(entry) == 2 and entry[1] == "AUDIENCE_REQUEST":
            request_value = entry[0]
            break
    if request_value is None:
        return {}
    out = collections.defaultdict(list)
    for qid, q in (quests_data.get("quests") or {}).items():
        for bucket in ("s", "f"):
            for r in (q.get("rw") or {}).get(bucket, []):
                if r.get("t") == request_value and r.get("item_stem"):
                    out[r["item_stem"]].append(qid)
        for mo in (q.get("mo") or []):
            for r in (mo.get("sr") or []) + (mo.get("fr") or []):
                if r.get("t") == request_value and r.get("item_stem"):
                    out[r["item_stem"]].append(qid)
    return {stem: sorted(set(qs)) for stem, qs in out.items()}


def _quest_fired_audiences(quests_data):
    """Reverse map: audience stem -> [{q, k}] of the quests that fire it as a
    follow-up (success / failure / unexpected outcome)."""
    out = collections.defaultdict(list)
    for qid, q in (quests_data.get("quests") or {}).items():
        for i, stem in enumerate(q.get("fu") or []):
            if not stem:
                continue
            kind = "success" if i == 0 else "failure"
            out[stem].append({"q": qid, "k": kind})
        for uo in (q.get("un") or []):
            stem = uo.get("fu")
            if stem:
                out[stem].append({"q": qid, "k": "unexpected"})
        for mo in (q.get("mo") or []):
            for stem in (mo.get("unfu") or []):
                if stem:
                    out[stem].append({"q": qid, "k": "unexpected"})
    return {stem: _dedupe_qf(entries) for stem, entries in out.items() if entries}


def _dedupe_qf(entries):
    seen = set()
    uniq = []
    for e in entries:
        key = (e["q"], e["k"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    return uniq


def build_audiences(out_dir, quests_data, index, game_root=None):
    """Write dist/audiences.json and return the data dict."""
    if game_root is not None:
        set_audience_root(game_root)
    set_game(game_root if game_root is not None else GAME)

    idx = QuestIndex()
    audiences = load_audience_catalog(idx)
    requests = load_audience_requests(idx)
    request_quests = _request_quest_links(quests_data)
    for stem, qs in request_quests.items():
        if stem in requests and qs:
            requests[stem]["q"] = qs
    rev = {"qf": _quest_fired_audiences(quests_data)}

    knots = set(index.get("knots") or {})
    knotless = [s for s, a in audiences.items() if a["k"] and a["k"] not in knots]

    data = {
        "audiences": audiences,
        "requests": requests,
        "rev": rev,
        "stats": {
            "audiences": len(audiences),
            "requests": len(requests),
            "with_conditions": sum(1 for a in audiences.values() if a.get("rq")),
            "knotless": len(knotless),
            "fires_after_quests": len(rev["qf"]),
        },
    }
    out_path = Path(out_dir) / "audiences.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Audiences: {data['stats']['audiences']} catalogued · "
          f"{data['stats']['with_conditions']} with conditions · "
          f"{data['stats']['requests']} requests · "
          f"{data['stats']['fires_after_quests']} fired after quests · "
          f"{data['stats']['knotless']} without an ink knot")
    return data


def main(argv=None):
    args = list(sys.argv[1:]) if argv is None else list(argv)
    game_root = args[0] if len(args) > 0 else ""
    out_dir = args[1] if len(args) > 1 else ""
    game_root = str(Path(game_root).expanduser().resolve()) if game_root else DEFAULT_GAME_ROOT
    set_audience_root(game_root)
    out_dir = Path(out_dir).expanduser().resolve() if out_dir else (SCRIPT_DIR / "dist")

    quests_path = out_dir / "quests.json"
    quests_data = json.load(open(quests_path, encoding="utf-8")) if quests_path.exists() else None
    index_path = out_dir / "index.json"
    index = json.load(open(index_path, encoding="utf-8")) if index_path.exists() else None

    build_audiences(out_dir, quests_data, index, game_root=game_root)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Sovereign Tower — per-route static pages + SEO shells.

Emits one `<route>/index.html` per URL the SPA can navigate to, so every deep
link is a real, bot-crawlable 200 response on GitHub Pages (and on plain
`python -m http.server`). See `../research/hosting/REPORT.md` for the URL
scheme; in short, each route is a trailing-slash directory backed by an
`index.html` shell:

    /                            -> dist/index.html        (copied web asset)
    /dialogues/                  -> dialogues/index.html
    /dialogues/<knot>/           -> dialogues/<knot>/index.html
    /quests/<id>/                -> quests/<id>/index.html
    /inventory/<stem>/           -> inventory/<stem>/index.html
    /knights/<stem>/             -> knights/<stem>/index.html
    /special/<name>/             -> special/<name>/index.html
    /audiences/<stem>/           -> audiences/<stem>/index.html
    /audiences/requests/<stem>/  -> audiences/requests/<stem>/index.html

Each shell is the shared `web/index.html` markup with depth-correct asset
tags (so the app boots from any depth), a per-page
<title>/<meta description>/<link rel=canonical>/Open Graph/JSON-LD head and a
visible `.seo-teaser` block for detail pages. The SPA still renders everything
client-side from `app.js` — the shells exist only so the server can answer the
URL and bots can read a text description per page.

Deterministic: routes are derived from the six `dist/*.json` key maps, written
in sorted key order, and carry no timestamps — two builds are byte-identical.

Reads only `out_dir` (no game root) and the shared `web/index.html` template
(it falls back to the copied `out_dir/index.html`, which `build_app.py` writes
before calling this module). Mirror of the `special_data.py` CLI convention:

    python3 route_pages.py [out_dir] [--site-base https://user.github.io/repo/]
"""

import html
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

SITE_NAME = "Sovereign Tower Explorer"

# (tab internal name, route dir, tab label) — the six shipped tabs
TABS = [
    ("ink", "dialogues", "Dialogues"),
    ("quest", "quests", "Quests"),
    ("inv", "inventory", "Inventory"),
    ("knight", "knights", "Knights"),
    ("special", "special", "Special"),
    ("aud", "audiences", "Audiences"),
]

# detail kinds: (kind, route dir, dataset name, key map name)
DETAILS = [
    ("knot", "dialogues", "index", "knots"),
    ("quest", "quests", "quests", "quests"),
    ("item", "inventory", "inventory", "items"),
    ("knight", "knights", "knights", "knights"),
    ("special", "special", "special", "instructions"),
    ("audience", "audiences", "audiences", "audiences"),
]

# cards container id per kind (where the .seo-teaser goes in each tab column)
CARDS_IDS = {
    "knot": "cards", "quest": "qcards", "item": "icards",
    "knight": "kcards", "special": "scards", "audience": "acards",
}

ITEM_TYPE_LABELS = {"RELIC": "relic", "MOUNT": "mount", "CONSUMABLE": "consumable",
                    "MEAL": "meal", "QUEST_ITEM": "quest item"}

# the same BBCode-ish tags the frontend stripBbc() removes
BBC_RE = re.compile(
    r"\[/?(?:b|i|center|color|fade|font|font_size|pulse|rainbow|shake|wave|Wave)[^\]]*\]")


def esc(s):
    """HTML-escape for attribute/text content."""
    return html.escape(str(s), quote=True)


def strip_bbc(s):
    """Remove Godot BBCode-style tags ([b], [color=#123456]…) from a string."""
    return BBC_RE.sub("", str(s))


def clean(s):
    """BBCode-free, whitespace-collapsed single-line text (for meta descriptions)."""
    return " ".join(strip_bbc(str(s)).split())


def truncate(s, n=200):
    """Collapse whitespace and cut at a word boundary with a trailing ellipsis."""
    s = " ".join(str(s).split())
    if len(s) <= n:
        return s
    cut = s[:n]
    head = cut.rsplit(" ", 1)[0]
    return (head + "…") if head else cut + "…"


def normalize_site_base(site_base):
    """Coerce a SITE_BASE value to a trailing-slash string ("" when unset)."""
    s = (site_base or "").strip()
    if s and not s.endswith("/"):
        s += "/"
    return s


def abs_url(site_base, rel_path):
    """Absolute URL for a route; root-relative when SITE_BASE is unset."""
    p = "/" + (rel_path or "").lstrip("/")
    return site_base + p[1:] if site_base else p


def load_datasets(out_dir):
    """Load the six route-driving JSONs from out_dir (missing files -> None)."""
    out = Path(out_dir)
    loaded = {}
    for name in ("index", "quests", "inventory", "knights", "special", "audiences"):
        p = out / ("%s.json" % name)
        if p.is_file():
            with open(p, encoding="utf-8") as f:
                loaded[name] = json.load(f)
        else:
            loaded[name] = None
    return loaded


def tkey(loc, key):
    """Resolve a loc key to its en text (mirrors the frontend tkey() with the
    locale pinned to en); falls back to the raw key."""
    if not key:
        return ""
    e = (loc or {}).get(key)
    return e.get("en") or key if e else key


def _name_key(loc, key, fallback):
    name = tkey(loc, key)
    return name or fallback


# ---------------------------------------------------------------------------
# per-entity SEO bits: (title part, description, teaser HTML)
# ---------------------------------------------------------------------------
def knot_bits(key, k, loc):
    cat = k.get("c") or ""
    prev = clean(k.get("prev") or "")
    desc = "%s is a %s knot in Sovereign Tower's dialogue corpus." % (key, cat or "dialogue")
    if prev:
        desc += " " + truncate(prev, 180)
    teaser = '<h1>%s</h1>' % esc(key)
    if cat:
        teaser += '<p class="tcat">%s · %s text lines · %s speakers</p>' % (
            esc(cat), k.get("text", 0), len(k.get("sp") or {}))
    if prev:
        teaser += '<p class="tprev">%s</p>' % esc(prev)
    return {"name": key, "desc": desc, "teaser": teaser}


def quest_bits(key, q, loc):
    name = _name_key(loc, q.get("n") or "", key)
    d = clean(tkey(loc, q.get("d") or ""))
    desc = "Quest in Sovereign Tower: %s." % name
    if d:
        desc += " " + truncate(d, 180)
    teaser = '<h1>%s</h1>' % esc(name)
    teaser += '<p class="qid">%s</p>' % esc(key)
    if d:
        teaser += '<p>%s</p>' % esc(truncate(d, 300))
    return {"name": name, "desc": desc, "teaser": teaser}


def item_bits(key, it, loc):
    name = _name_key(loc, it.get("n") or "", key)
    type_label = ITEM_TYPE_LABELS.get(it.get("type"), "item")
    d = clean(tkey(loc, it.get("d") or ""))
    desc = "%s, a %s in Sovereign Tower." % (name, type_label)
    if d:
        desc += " " + truncate(d, 180)
    teaser = '<h1>%s</h1>' % esc(name)
    teaser += '<p class="qid">%s</p>' % esc(key)
    teaser += '<p class="tcat">%s</p>' % esc(type_label)
    if d:
        teaser += '<p>%s</p>' % esc(truncate(d, 300))
    return {"name": name, "desc": desc, "teaser": teaser}


def knight_bits(key, k, loc):
    name = _name_key(loc, k.get("n") or "", key)
    alias = tkey(loc, k.get("nu") or "")
    origin = k.get("loc") or ""
    desc = "Playable knight in Sovereign Tower: %s" % name
    if origin:
        desc += ", from %s" % origin
    if alias:
        desc += " (alias: %s)" % alias
    desc += "."
    teaser = '<h1>%s</h1>' % esc(name)
    teaser += '<p class="qid">%s</p>' % esc(key)
    if origin:
        teaser += '<p class="tcat">origin: %s</p>' % esc(origin)
    if alias:
        teaser += '<p class="tcat">alias: %s</p>' % esc(alias)
    mast = k.get("mast") or []
    if mast:
        teaser += '<p class="tcat">mastered: %s</p>' % esc(", ".join(mast))
    return {"name": name, "desc": desc, "teaser": teaser}


def special_bits(key, s, loc):
    note = clean(s.get("note") or "")
    name = key
    if note and ":" in note:
        name = note.split(":", 1)[0].strip()
    desc = "SpecialInstruction in Sovereign Tower: %s." % name
    if note:
        desc += " " + truncate(note, 200)
    teaser = '<h1>%s</h1>' % esc(name)
    teaser += '<p class="qid">%s</p>' % esc(key)
    if note:
        teaser += '<p>%s</p>' % esc(note)
    return {"name": name, "desc": desc, "teaser": teaser}


def audience_bits(key, a, loc, index):
    chars = [tkey(loc, c) for c in (a.get("c") or [])]
    chars_txt = ", ".join(chars)
    knot = a.get("k") or ""
    prev = ""
    if knot:
        prev = clean((index.get("knots") or {}).get(knot, {}).get("prev") or "")
    desc = "Narrated scene in Sovereign Tower: %s" % key
    if chars_txt:
        desc += " featuring %s" % chars_txt
    if prev:
        desc += ". " + truncate(prev, 180)
    teaser = '<h1>%s</h1>' % esc(key)
    if a.get("f"):
        teaser += '<p class="tcat">folder: %s</p>' % esc(a["f"])
    if chars_txt:
        teaser += '<p class="tcat">characters: %s</p>' % esc(chars_txt)
    if prev:
        teaser += '<p>%s</p>' % esc(prev)
    return {"name": key, "desc": desc, "teaser": teaser}


def request_bits(key, r, loc):
    name = _name_key(loc, r.get("n") or "", key)
    d = clean(tkey(loc, r.get("d") or ""))
    desc = "Audience request in Sovereign Tower: %s." % name
    if r.get("cst"):
        desc += " Costs %s." % r["cst"]
    if d:
        desc += " " + truncate(d, 180)
    teaser = '<h1>%s</h1>' % esc(name)
    teaser += '<p class="qid">%s</p>' % esc(key)
    if r.get("cst"):
        teaser += '<p class="tcat">cost: %s</p>' % esc(r["cst"])
    if d:
        teaser += '<p>%s</p>' % esc(truncate(d, 300))
    return {"name": name, "desc": desc, "teaser": teaser}


ENTITY_BITS = {
    "knot": knot_bits, "quest": quest_bits, "item": item_bits,
    "knight": knight_bits, "special": special_bits,
    "audience": audience_bits,
}


def jsonld_graph(site_base, canonical, tab_rel, tab_label, entity_name):
    """One @graph with a WebSite node (only when SITE_BASE is set, so the build
    stays deterministic and default builds carry no absolute URLs) and a
    BreadcrumbList for the current route."""
    graph = []
    if site_base:
        graph.append({"@type": "WebSite", "@id": site_base,
                      "name": SITE_NAME, "url": site_base})
    home = site_base or "/"
    items = [
        {"@type": "ListItem", "position": 1, "name": SITE_NAME, "item": home},
        {"@type": "ListItem", "position": 2, "name": tab_label,
         "item": (site_base or "") + tab_rel},
    ]
    if entity_name:
        items.append({"@type": "ListItem", "position": 3,
                      "name": entity_name, "item": canonical})
    graph.append({"@type": "BreadcrumbList", "itemListElement": items})
    return {"@context": "https://schema.org", "@graph": graph}


def render_page(template, title, description, canonical, site_base, tab_rel,
                tab_label, og_type, entity_name, depth, teaser="", cards_id=""):
    """One route shell: depth-correct asset tags, per-route head, optional teaser."""
    prefix = "../" * depth
    out = template.replace('href="style.css"', 'href="%sstyle.css"' % prefix, 1)
    out = out.replace('<script src="app.js"></script>',
                      '<script src="%sapp.js"></script>' % prefix, 1)
    head = '  <meta name="description" content="%s">\n' % esc(description)
    if canonical:
        head += '  <link rel="canonical" href="%s">\n' % esc(canonical)
    head += '  <meta property="og:type" content="%s">\n' % og_type
    head += '  <meta property="og:title" content="%s">\n' % esc(title)
    head += '  <meta property="og:description" content="%s">\n' % esc(description)
    if canonical:
        head += '  <meta property="og:url" content="%s">\n' % esc(canonical)
    head += '  <meta name="twitter:card" content="summary">\n'
    head += '  <meta name="twitter:title" content="%s">\n' % esc(title)
    head += '  <meta name="twitter:description" content="%s">\n' % esc(description)
    graph = jsonld_graph(site_base, canonical, tab_rel, tab_label, entity_name)
    head += '  <script type="application/ld+json">%s</script>\n' % json.dumps(
        graph, ensure_ascii=False, separators=(",", ":"))
    out = out.replace("<title>%s</title>" % SITE_NAME,
                      "<title>%s</title>\n%s" % (esc(title), head.rstrip("\n")), 1)
    if teaser and cards_id:
        needle = '<div id="%s"></div>' % cards_id
        if needle in out:
            block = ('<div class="seo-teaser" role="main">\n'
                     + teaser + "\n</div>")
            out = out.replace(needle, block + "\n" + needle, 1)
    return out


# tab-page meta descriptions (keyword-bearing; the in-DOM tabdesc blocks in
# web/index.html carry the longer versions)
TAB_DESCS = {
    "dialogues": "Browse all 922 dialogue knots of Sovereign Tower — 91 speakers, "
                 "3,477 choices, 1,368 variables across 17 categories: county quests, "
                 "scripted quests, grievances, candidacies, endings, reactions and the "
                 "free-time dialogues of the 24 knights, with filters, cross-links and "
                 "full transcripts.",
    "quests": "All 312 quest contracts of Sovereign Tower with their stat requirements, "
              "conditions, deadlines and rewards — 91 with an unexpected outcome, 69 with "
              "modifier variants, each linked to its unlock knot, follow-up audience and "
              "preferred knights.",
    "inventory": "All 149 equipment resources of Sovereign Tower — 65 relics, 29 mounts, "
                 "44 consumables, 6 meals and 5 quest items — with stat bonuses, tags, "
                 "purchase requirements and every quest, shop or story knot that grants them.",
    "knights": "The 24 playable knights of Sovereign Tower with mastered stats, affinity "
               "and demission profiles, known and rumored features, preferred equipment, "
               "liked meals and sovereign tags, pair conversations, evolution paths and "
               "every quest and story knot they appear in.",
    "special": "The 71 SpecialInstruction game-director switches of Sovereign Tower — "
               "knight evolution states, background toggles and raise flags — with their "
               "firing conditions, the ink knots that emit them and the quests that grant them.",
    "audiences": "The 511 narrated Audience scenes and 34 AudienceRequest resources of "
                 "Sovereign Tower, with every gating condition that makes a scene play: "
                 "story and knight requirements, hardcoded cycles, quest follow-ups, "
                 "doleance and special schedulers, filler packs, county introductions and "
                 "ultimatum follow-ups.",
}


def _template_text(out_dir):
    """The shared shell markup: the copied out_dir/index.html (build output) or,
    standalone, the hand-edited web/index.html next to this script."""
    candidates = [Path(out_dir) / "index.html", SCRIPT_DIR / "web" / "index.html"]
    for c in candidates:
        if c.is_file():
            return c.read_text(encoding="utf-8")
    raise SystemExit("ERROR: no shell template found (looked at %s)" %
                     ", ".join(str(c) for c in candidates))


def write_routes(out_dir, datasets, site_base=""):
    """Emit every route shell under out_dir; returns the number of pages written."""
    out = Path(out_dir)
    site_base = normalize_site_base(site_base)
    template = _template_text(out)
    if 'href="style.css"' not in template or '<script src="app.js"></script>' not in template:
        raise SystemExit("ERROR: %s is not the explorer shell template (missing "
                         "style.css/app.js tags)." % (out / "index.html"))

    index = datasets.get("index") or {}
    quests = datasets.get("quests") or {}
    loc = quests.get("loc") or {}

    def write(rel_dir, html_text):
        p = out / rel_dir
        p.mkdir(parents=True, exist_ok=True)
        (p / "index.html").write_text(html_text, encoding="utf-8")

    # tab pages (the /dialogues/ alias canonicalises to the root)
    for tab, tdir, label in TABS:
        rel = tdir + "/"
        canonical = abs_url(site_base, "" if tdir == "dialogues" else rel)
        title = "%s — %s" % (label, SITE_NAME)
        write(rel, render_page(
            template, title, TAB_DESCS[tdir], canonical, site_base, rel, label,
            "website", None, 1))

    # detail pages, per dataset key (sorted for byte-identical rebuilds)
    tab_label = {tdir: label for _, tdir, label in TABS}
    for kind, tdir, dname, kmap in DETAILS:
        data = datasets.get(dname) or {}
        keymap = data.get(kmap) or {}
        bits = ENTITY_BITS[kind]
        for key in sorted(keymap):
            kwargs = {"index": index} if kind == "audience" else {}
            b = bits(key, keymap[key], loc, **kwargs)
            rel = "%s/%s/" % (tdir, key)
            canonical = abs_url(site_base, rel)
            title = "%s — %s" % (b["name"], SITE_NAME)
            write(rel, render_page(
                template, title, b["desc"], canonical, site_base, tdir + "/",
                tab_label[tdir], "article", b["name"], 2,
                teaser=b["teaser"], cards_id=CARDS_IDS[kind]))

    # audience requests live under /audiences/requests/ (one level deeper)
    aud = datasets.get("audiences") or {}
    reqs = aud.get("requests") or {}
    for key in sorted(reqs):
        b = request_bits(key, reqs[key], loc)
        rel = "audiences/requests/%s/" % key
        canonical = abs_url(site_base, rel)
        title = "%s — %s" % (b["name"], SITE_NAME)
        write(rel, render_page(
            template, title, b["desc"], canonical, site_base, "audiences/",
            "Audiences", "article", b["name"], 3,
            teaser=b["teaser"], cards_id=CARDS_IDS["audience"]))

    counts = {"tabs": len(TABS),
              "knots": len((datasets.get("index") or {}).get("knots") or {}),
              "quests": len((datasets.get("quests") or {}).get("quests") or {}),
              "items": len((datasets.get("inventory") or {}).get("items") or {}),
              "knights": len((datasets.get("knights") or {}).get("knights") or {}),
              "specials": len((datasets.get("special") or {}).get("instructions") or {}),
              "audiences": len((datasets.get("audiences") or {}).get("audiences") or {}),
              "requests": len((datasets.get("audiences") or {}).get("requests") or {})}
    total = sum(counts.values())
    print("Route pages: %d shells (%s)" % (
        total, " · ".join("%s %d" % (k, v) for k, v in counts.items())))
    return total


def build_route_pages(out_dir, site_base=""):
    """Load out_dir's datasets and emit all route shells (build_app entry point)."""
    return write_routes(out_dir, load_datasets(out_dir), site_base)


def main(argv=None):
    args = list(sys.argv[1:]) if argv is None else list(argv)
    site_base = ""
    positionals = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--site-base" and i + 1 < len(args) and not args[i + 1].startswith("--"):
            site_base = args[i + 1]
            i += 1
        else:
            positionals.append(a)
        i += 1
    out_dir = Path(positionals[0]).expanduser().resolve() if positionals else (SCRIPT_DIR / "dist")
    write_routes(out_dir, load_datasets(out_dir), site_base)


if __name__ == "__main__":
    main()

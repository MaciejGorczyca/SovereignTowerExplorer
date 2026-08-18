"""Route-page shell tests (dist/ route tree + route_pages.py helpers).

Locks in the per-route static pages build_app.py emits for GitHub-Pages-safe
deep links (see ../research/hosting/REPORT.md): every route directory exists
and carries an index.html, route counts match the dataset key maps exactly
(both directions — no orphan route dirs), asset tags are depth-correct, every
page has a title + meta description + canonical, detail pages embed a visible
.seo-teaser, and shells stay smoke-stub-friendly (no inline scripts / global
references). Runs against the checked-in dist/ only (no game data needed).
"""
import json
import re
import unittest

from helpers import DIST, load_dist
from route_pages import (SITE_NAME, abs_url, normalize_site_base, render_page,
                         strip_bbc, truncate, tkey)

ASSET_RE = re.compile(r'src="([^"]*)app\.js"')
STYLE_RE = re.compile(r'href="([^"]*)style\.css"')

TAB_DIRS = ["dialogues", "quests", "inventory", "knights", "special", "audiences"]


def _route_dirs(dist, top):
    """Route directories directly under dist/<top> (excludes files)."""
    base = dist / top
    if not base.is_dir():
        return []
    return [p.name for p in sorted(base.iterdir()) if p.is_dir()]


class RouteTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_dist("index.json")
        cls.quests = load_dist("quests.json")
        cls.inventory = load_dist("inventory.json")
        cls.knights = load_dist("knights.json")
        cls.special = load_dist("special.json")
        cls.audiences = load_dist("audiences.json")
        # read every route shell once and share the text across the page tests
        # (a few thousand files — avoid re-reading them per test on slow I/O)
        cls.pages = {}
        for p in DIST.rglob("index.html"):
            cls.pages[str(p.relative_to(DIST))] = p.read_text(encoding="utf-8")

    def test_tab_pages_exist(self):
        for d in TAB_DIRS:
            with self.subTest(dir=d):
                self.assertIn("%s/index.html" % d, self.pages,
                              "missing route page %s/index.html" % d)

    def test_route_counts_match_datasets(self):
        """Every dataset key has a detail dir; no extra/orphan detail dirs."""
        expect = [
            ("dialogues", self.index["knots"]),
            ("quests", self.quests["quests"]),
            ("inventory", self.inventory["items"]),
            ("knights", self.knights["knights"]),
            ("special", self.special["instructions"]),
            ("audiences", self.audiences["audiences"]),
        ]
        for top, keymap in expect:
            with self.subTest(dir=top):
                dirs = set(_route_dirs(DIST, top))
                if top == "audiences":
                    dirs -= {"requests"}  # request detail pages live there
                self.assertEqual(dirs, set(keymap),
                                 "%s detail dirs != dataset keys" % top)
        reqs = self.audiences["requests"]
        self.assertEqual(set(_route_dirs(DIST, "audiences/requests")), set(reqs),
                         "audiences/requests dirs != requests dataset keys")

    def test_every_route_dir_has_index_html(self):
        for top in TAB_DIRS:
            base = DIST / top
            for rel, _text in self.pages.items():
                if rel.startswith(top + "/"):
                    with self.subTest(page=rel):
                        self.assertTrue((DIST / rel).is_file())
            # every dir directly under a route root must be a detail page with
            # an index.html (no stray folders) — except audiences/requests/,
            # whose own detail pages are asserted in the counts test
            for d in _route_dirs(DIST, top):
                if d == "requests":
                    continue
                self.assertIn("%s/%s/index.html" % (top, d), self.pages, d)

    def test_asset_prefixes_depth_correct(self):
        cases = [
            ("dialogues/index.html", "../"),
            ("quests/index.html", "../"),
            ("quests/contract_cleankeeper_goose_part_two/index.html", "../../"),
            ("audiences/county_quest_enberg_1/index.html", "../../"),
            ("audiences/requests/ari_knight_request/index.html", "../../../"),
        ]
        for rel, prefix in cases:
            text = self.pages.get(rel)
            self.assertTrue(text is not None, rel)
            with self.subTest(page=rel):
                m = ASSET_RE.search(text)
                self.assertTrue(m, "no app.js tag in " + rel)
                self.assertEqual(m.group(1), prefix)
                m = STYLE_RE.search(text)
                self.assertTrue(m, "no style.css tag in " + rel)
                self.assertEqual(m.group(1), prefix)

    def test_root_page_keeps_plain_asset_refs(self):
        text = self.pages["index.html"]
        self.assertIn('src="app.js"', text)
        self.assertIn('href="style.css"', text)

    def test_title_and_description_nonempty(self):
        for rel, text in self.pages.items():
            if not rel.startswith("quests/"):
                continue
            with self.subTest(page=rel):
                tm = re.search(r"<title>(.*?)</title>", text, re.S)
                self.assertTrue(tm and tm.group(1).strip()
                                and tm.group(1).endswith(SITE_NAME),
                                "missing/bad title: %s" % rel)
                dm = re.search(r'<meta name="description" content="([^"]+)"', text)
                self.assertTrue(dm and dm.group(1).strip(),
                                "missing description: %s" % rel)

    def test_canonical_present(self):
        for rel, text in self.pages.items():
            if rel == "index.html":
                continue  # the root is the copied web shell, not a route page
            with self.subTest(page=rel):
                self.assertIn('<link rel="canonical" href="', text,
                              "no canonical in %s" % rel)

    def test_detail_pages_embed_teaser(self):
        for top, keymap in (("dialogues", self.index["knots"]),
                            ("quests", self.quests["quests"]),
                            ("inventory", self.inventory["items"]),
                            ("knights", self.knights["knights"]),
                            ("special", self.special["instructions"]),
                            ("audiences", self.audiences["audiences"])):
            probe = sorted(keymap)[0]
            rel = "%s/%s/index.html" % (top, probe)
            with self.subTest(page=rel):
                text = self.pages.get(rel)
                self.assertTrue(text is not None, rel)
                self.assertIn('<div class="seo-teaser"', text)
                self.assertIn("<h1>", text)

    def test_request_pages_embed_teaser(self):
        probe = sorted(self.audiences["requests"])[0]
        rel = "audiences/requests/%s/index.html" % probe
        text = self.pages.get(rel)
        self.assertTrue(text is not None, rel)
        self.assertIn('<div class="seo-teaser"', text)
        self.assertIn("<h1>", text)

    def test_shell_is_smoke_stub_friendly(self):
        """Route shells must not add inline scripts or external references the
        frontend smoke VM (no location/document.currentScript) would hit."""
        for rel, text in self.pages.items():
            with self.subTest(page=rel):
                self.assertNotIn("<script>", text)
                self.assertNotIn("document.currentScript", text)
                self.assertNotIn("location.pathname", text)
                self.assertNotIn("window.location", text)

    def test_shells_share_the_six_tabdesc_blocks(self):
        """Every page shell (root + routes) carries all six tabdesc blocks, so
        bots see the active tab's description in each prerendered page."""
        for rel in ("index.html", "quests/index.html",
                    "quests/contract_cleankeeper_goose_part_two/index.html"):
            text = self.pages[rel]
            with self.subTest(page=rel):
                for tid in ("inkdesc", "qdesc", "idesc", "kdesc", "sdesc", "adesc"):
                    self.assertIn('id="%s"' % tid, text, tid)


class RouteHelpersTest(unittest.TestCase):
    def test_normalize_site_base(self):
        self.assertEqual(normalize_site_base(""), "")
        self.assertEqual(normalize_site_base("https://x.io"), "https://x.io/")
        self.assertEqual(normalize_site_base("https://x.io/"), "https://x.io/")

    def test_abs_url(self):
        self.assertEqual(abs_url("", "quests/x/"), "/quests/x/")
        self.assertEqual(abs_url("https://x.io/", "quests/x/"), "https://x.io/quests/x/")
        self.assertEqual(abs_url("https://x.io/repo/", "audiences/requests/r/"),
                         "https://x.io/repo/audiences/requests/r/")
        self.assertEqual(abs_url("https://x.io/", ""), "https://x.io/")

    def test_strip_bbc(self):
        self.assertEqual(strip_bbc("[b][color=815543]goose[/color][/b]"), "goose")
        self.assertEqual(strip_bbc("[shake]Fear[/shake] me"), "Fear me")
        self.assertEqual(strip_bbc("plain"), "plain")

    def test_truncate(self):
        self.assertEqual(truncate("short text", 100), "short text")
        out = truncate("one two three four five", 10)
        self.assertTrue(out.endswith("…") and "two" in out)

    def test_tkey_falls_back(self):
        loc = {"ARRON_NAME": {"en": "Arron", "fr": "Arron"}}
        self.assertEqual(tkey(loc, "ARRON_NAME"), "Arron")
        self.assertEqual(tkey(loc, "MISSING_KEY"), "MISSING_KEY")
        self.assertEqual(tkey(loc, ""), "")

    def test_render_page_depth_and_head(self):
        from route_pages import TAB_DESCS
        tpl = ('<title>%s</title><link rel="stylesheet" href="style.css">'
               '<div id="qcards"></div><script src="app.js"></script>' % SITE_NAME)
        out = render_page(tpl, "T — %s" % SITE_NAME, "desc", "https://x.io/quests/q/",
                          "https://x.io/", "quests/", "Quests", "article", "T", 2,
                          teaser="<h1>T</h1>", cards_id="qcards")
        self.assertIn('href="../../style.css"', out)
        self.assertIn('src="../../app.js"', out)
        self.assertIn('<div class="seo-teaser"', out)
        self.assertIn('<link rel="canonical" href="https://x.io/quests/q/">', out)
        self.assertIn('application/ld+json', out)
        self.assertIn('"name":"Quests"', out)


if __name__ == "__main__":
    unittest.main()

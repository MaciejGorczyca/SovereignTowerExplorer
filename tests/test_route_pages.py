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
from pathlib import Path

from helpers import DIST, load_dist
from route_pages import (SITE_NAME, abs_url, esc, normalize_site_base, render_page,
                         strip_bbc, truncate, tkey,
                         audience_bits, clean, item_bits, knight_bits, knot_bits,
                         quest_bits, request_bits, special_bits)

ASSET_RE = re.compile(r'src="([^"]*)app\.js"')
STYLE_RE = re.compile(r'href="([^"]*)style\.css"')

TAB_DIRS = ["dialogues", "quests", "inventory", "knights", "special", "audiences"]

# the six static per-tab description blocks (`web/index.html`), in page order.
# Placed AFTER their column's #cards container so every re-render (which only
# replaces the cards grid + countline) leaves them in place.
TABDESC_IDS = ["inkdesc", "qdesc", "idesc", "kdesc", "sdesc", "adesc"]
TABDESC_RE = re.compile(r'<div id="([^"]+)" class="tabdesc">(.*?)</div>', re.S)
CARDS_FOR = {"inkdesc": "cards", "qdesc": "qcards", "idesc": "icards",
             "kdesc": "kcards", "sdesc": "scards", "adesc": "acards"}


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
        """Every page shell (root + routes) carries exactly six .tabdesc blocks —
        one per results column, placed AFTER the column's #cards div, each with a
        header and a non-empty paragraph — so tab re-renders (which only replace
        the cards container) never wipe the static descriptions and bots see the
        active tab's block in every prerendered page."""
        for rel, text in self.pages.items():
            with self.subTest(page=rel):
                blocks = TABDESC_RE.findall(text)
                self.assertEqual(
                    len(blocks), len(TABDESC_IDS),
                    "expected exactly six .tabdesc blocks in %s" % rel)
                self.assertEqual(
                    [bid for bid, _ in blocks], TABDESC_IDS,
                    "tabdesc ids != the six results columns in %s" % rel)
                for bid, inner in blocks:
                    self.assertRegex(inner, r"<h2>.+</h2>",
                                     "%s header missing" % bid)
                    pm = re.search(r"<p>(.*)</p>", inner, re.S)
                    self.assertTrue(pm and pm.group(1).strip(),
                                    "%s description body empty" % bid)
                    self.assertLess(
                        text.index('<div id="%s"></div>' % CARDS_FOR[bid]),
                        text.index('<div id="%s"' % bid),
                        "%s must sit after its #%s container" % (bid, CARDS_FOR[bid]))


class RouteHelpersTest(unittest.TestCase):
    def test_normalize_site_base(self):
        self.assertEqual(normalize_site_base(""), "")
        self.assertEqual(normalize_site_base("https://x.io"), "https://x.io/")
        self.assertEqual(normalize_site_base("https://x.io/"), "https://x.io/")

    def test_normalize_site_base_warns_on_placeholders(self):
        """A SITE_BASE that looks like a placeholder warns (never errors), so a
        copy-pasted example value is loud instead of silently poisoning the
        emitted canonical/OG/sitemap URLs."""
        import contextlib
        import io
        for bad in ("https://example.com/", "http://localhost:8000",
                    "https://yourdomain.io/"):
            buf = io.StringIO()
            with self.subTest(site_base=bad):
                with contextlib.redirect_stderr(buf):
                    out = normalize_site_base(bad)
                self.assertTrue(out.endswith("/"))
                self.assertIn("placeholder", buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            normalize_site_base("https://x.io/")
        self.assertEqual(buf.getvalue(), "", "no warning for a real origin")

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

    def test_strip_bbc_truncated_fragments(self):
        """index.json prev is truncated to 60 chars, which can cut a tag in
        half — the leftover [/font_s or bare [/ must not survive either."""
        self.assertEqual(strip_bbc("fealty is yours.[/font_s"), "fealty is yours.")
        self.assertEqual(strip_bbc("Ahaha...[/"), "Ahaha...")
        self.assertEqual(strip_bbc("[shake rate=15]Hi[/shake"), "Hi")
        self.assertEqual(strip_bbc("[font_size=20]It sure[/font_size]"), "It sure")

    def test_clean_collapses_and_strips(self):
        self.assertEqual(clean("  A\n  B   [b]C[/b]  "), "A B C")

    def test_esc(self):
        self.assertEqual(esc('<a href="?x=1&y=2">t</a>'),
                         "&lt;a href=&quot;?x=1&amp;y=2&quot;&gt;t&lt;/a&gt;")
        self.assertEqual(esc("plain"), "plain")
        self.assertEqual(esc(42), "42")

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


class TeaserHelpersTest(unittest.TestCase):
    """Per-entity SEO teaser helpers against known shipped-dist entries (T3).

    Locks in the en-first `tkey` resolution and the clean (BBCode-stripped,
    HTML-safe) description/teaser text the route shells embed, spot-checking one
    representative entry per entity kind plus the BBCode-truncation regression.
    """

    @classmethod
    def setUpClass(cls):
        cls.index = load_dist("index.json")
        cls.quests = load_dist("quests.json")
        cls.inventory = load_dist("inventory.json")
        cls.knights = load_dist("knights.json")
        cls.special = load_dist("special.json")
        cls.audiences = load_dist("audiences.json")
        cls.loc = cls.quests["loc"]

    def test_quest_bits_goose(self):
        key = "contract_cleankeeper_goose_part_two"
        b = quest_bits(key, self.quests["quests"][key], self.loc)
        self.assertEqual(b["name"], "The clean keeper goose, part 2")
        self.assertTrue(b["desc"].startswith(
            "Quest in Sovereign Tower: The clean keeper goose, part 2."))
        self.assertIn("accuse the goose", b["desc"])  # en description resolved
        self.assertNotIn("[", b["desc"])  # BBCode stripped
        self.assertIn("<h1>The clean keeper goose, part 2</h1>", b["teaser"])
        self.assertIn('<p class="qid">contract_cleankeeper_goose_part_two</p>',
                      b["teaser"])

    def test_knot_bits_first_audience(self):
        key = "county_quest_enberg_first_audience"
        b = knot_bits(key, self.index["knots"][key], self.loc)
        self.assertEqual(b["name"], key)
        self.assertIn("county_quest knot", b["desc"])  # category
        self.assertIn("Greetings.", b["desc"])          # prev
        self.assertIn("county_quest · 86 text lines · 3 speakers", b["teaser"])
        self.assertIn("Greetings.", b["teaser"])

    def test_knot_bits_truncated_bbcode_stripped(self):
        """prev cut mid-[font_size] by the 60-char truncation must not leak."""
        key = "gothild_accept_recruit_reaction"
        b = knot_bits(key, self.index["knots"][key], self.loc)
        self.assertIn("My fealty is yours.", b["desc"])
        self.assertNotIn("[", b["desc"])
        self.assertNotIn("[/font", b["teaser"])

    def test_knight_bits_arron(self):
        key = "arron"
        b = knight_bits(key, self.knights["knights"][key], self.loc)
        self.assertEqual(b["name"], "Arron")
        self.assertEqual(b["desc"],
                         "Playable knight in Sovereign Tower: Arron, from DRAKOVIC_CASTLE.")
        self.assertIn("<h1>Arron</h1>", b["teaser"])
        self.assertIn("origin: DRAKOVIC_CASTLE", b["teaser"])
        self.assertIn("mastered: WITS, AGILITY, LUCK", b["teaser"])

    def test_item_bits_demon_heart(self):
        key = "demon_heart"
        b = item_bits(key, self.inventory["items"][key], self.loc)
        self.assertEqual(b["name"], "Demon heart")
        self.assertTrue(b["desc"].startswith("Demon heart, a relic in Sovereign Tower."))
        self.assertIn("A cursed demon heart", b["desc"])
        self.assertNotIn("[", b["desc"])
        self.assertIn("<h1>Demon heart</h1>", b["teaser"])

    def test_special_bits_note_prefix(self):
        key = "ARRON_KIND"
        b = special_bits(key, self.special["instructions"][key], self.loc)
        self.assertEqual(b["name"], "Arron → Kind")
        self.assertTrue(b["desc"].startswith(
            "SpecialInstruction in Sovereign Tower: Arron → Kind."))
        self.assertIn("TRUE_DRAGON_KNIGHT", b["desc"])  # note content
        self.assertIn("<h1>Arron → Kind</h1>", b["teaser"])

    def test_audience_bits_enberg(self):
        key = "county_quest_enberg_1"
        b = audience_bits(key, self.audiences["audiences"][key], self.loc, self.index)
        self.assertIn("featuring Yohav", b["desc"])     # localized chars
        self.assertIn("Greetings.", b["desc"])          # its knot's prev
        self.assertIn("folder: county_quests", b["teaser"])
        self.assertIn("characters: Yohav", b["teaser"])

    def test_request_bits_ari(self):
        key = "ari_knight_request"
        b = request_bits(key, self.audiences["requests"][key], self.loc)
        self.assertEqual(b["name"], "The younger brother of the Basalt brothers")
        self.assertTrue(b["desc"].startswith("Audience request in Sovereign Tower: "))
        self.assertIn("Costs 25.", b["desc"])
        self.assertIn("sell you a griffin", b["desc"])

    def test_every_entity_bits_emits_clean_text(self):
        """Run every helper over every shipped entry: name/desc nonempty and
        free of BBCode or truncation fragments ([/b, [font_s, […) — the text
        that lands in meta descriptions must be plain prose."""
        checks = [
            (knot_bits, self.index, "knots"),
            (quest_bits, self.quests, "quests"),
            (item_bits, self.inventory, "items"),
            (knight_bits, self.knights, "knights"),
            (special_bits, self.special, "instructions"),
            (audience_bits, self.audiences, "audiences"),
        ]
        for fn, ds, key_name in checks:
            for key, record in ds[key_name].items():
                kwargs = {"index": self.index} if fn is audience_bits else {}
                b = fn(key, record, self.loc, **kwargs)
                with self.subTest(fn=fn.__name__, key=key):
                    self.assertTrue(b["name"])
                    self.assertTrue(b["desc"])
                    self.assertNotIn("[", b["desc"])
                    self.assertNotIn("[/", b["teaser"])
        for key, record in self.audiences["requests"].items():
            b = request_bits(key, record, self.loc)
            with self.subTest(fn="request_bits", key=key):
                self.assertTrue(b["name"])
                self.assertTrue(b["desc"])
                self.assertNotIn("[", b["desc"])
                self.assertNotIn("[/", b["teaser"])


class ViewerEnvExampleTest(unittest.TestCase):
    """The shipped viewer.env.example must never enable SITE_BASE: the only
    mention is a commented example, so a copy to viewer.env can never bake a
    placeholder origin into a build (see ../research/hosting/REPORT_FOLLOWUP.md)."""

    ROOT = Path(__file__).resolve().parents[1]

    def test_site_base_example_is_inert(self):
        text = (self.ROOT / "viewer.env.example").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith("SITE_BASE"):
                self.assertTrue(line.lstrip().startswith("# "),
                                "active SITE_BASE in the example: %r" % line)


if __name__ == "__main__":
    unittest.main()

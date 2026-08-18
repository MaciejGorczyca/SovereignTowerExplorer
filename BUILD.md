# Building the Sovereign Tower viewer

This file is the quick-start for running `build_app.py`. For the full reference
(flags, path priority, token format, walker internals) run
`python3 build_app.py --help` — that output mirrors this document and also
prints the exact paths the build would use on your machine.

---

## Quick start

```bash
python3 build_app.py                              # rebuild dist/ (default paths)
cd dist && python3 -m http.server 8000            # serve; open http://localhost:8000
```

That is all a normal rebuild needs. `dist/` is generated and safe to delete;
the build re-creates it from the two inputs described below.

---

## What the build does

`build_app.py` produces a self-contained static site into `out_dir` from two inputs:

1. **The compiled ink story** (the dialogue/script data). By default it is
   decoded in-memory from the game's `.res` chain under `game_root` — no files
   need to exist on disk, but this requires pip `zstandard`. Alternatively, use
   `--from-disk` to read pre-extracted `master.ink.json` files from `ink_root`.
2. **The Godot project tree** (`game_root`) — quests, audiences, inventory,
   knights, special instructions and the 6 locales' text.

Outputs written to `out_dir`:

| file | contents |
|---|---|
| `index.json` | en dialogue metadata + tokenised knots |
| `quests.json` | quest resources, enums, 6-locale text |
| `inventory.json` | all equipment + buy/quest/ink sources |
| `knights.json` | the 24 playable knights + dialogue/quest/ink links |
| `special.json` | the SpecialInstruction catalog joins |
| `audiences.json` | the audience + audience-request catalog joins |
| `locales/<locale>.json` | dialogue-token overrides for fr/de/cmn/ja/ko |
| `app.js`, `style.css`, `index.html` | frontend assets copied from `web/` |
| `dialogues/`, `quests/`, `inventory/`, `knights/`, `special/`, `audiences/` | per-route static shells — one `<entity>/index.html` per URL the SPA can open (see README "Routes / SEO") |

---

## Arguments

Three **positional** arguments, all optional:

| positional | meaning | default |
|---|---|---|
| `ink_root` | dir holding `<locale>/master.ink.json` files (only read with `--from-disk`, or when given explicitly) | `../game/InkExtracted` |
| `out_dir` | output directory for the generated site | `./dist` |
| `game_root` | root of the extracted Godot project (contains `content/`, `systems/`, `lang/`) | `../game/SovereignTowerCode` |

Defaults are relative to the script itself, so a default build works from any
working directory. Relative values you pass are resolved against your **current
working directory**; use absolute paths (`C:\...` on Windows) if you want them
CWD-independent.

### Flags

| flag | effect |
|---|---|
| `-h`, `--help` | print full help + the resolved paths, then exit (no build) |
| `--from-disk` | read ink from `<ink_root>/<locale>/master.ink.json` instead of extracting in-memory (stdlib-only build). Missing locales are skipped with a warning. An explicit positional `ink_root` implies this. |
| `--extract-ink [dir]` | ink extraction only: decode the stories to `<dir>/<locale>/master.ink.json` (default `../game/InkExtracted`), then exit. No build. |
| `--save-ink [dir]` | build as normal, then **also** write the decoded ink to `<dir>/<locale>/master.ink.json` (default `../game/InkExtracted`). |
| `--profile` | print per-phase wall/CPU timings of the build. |
| `--site-base <url>` | absolute URL of the deployed site root (trailing slash optional). Feeds the route shells' canonical / OG / JSON-LD URLs and robots/sitemap; **defaults to the live deployment origin** (`https://maciejgorczyca.github.io/SovereignTowerExplorer/`), so a bare build is already production-absolute — override only if hosting changes. Same key as env/`viewer.env` `SITE_BASE`. |

---

## Serving and deploying (trailing slash)

Every deep link the app can open is prerendered as `<route>/index.html`, so the site works
on any static host with **no server config**:

- **GitHub Pages** (and `python -m http.server`) resolve `/a/b/` → `a/b/index.html`; a
  request for `/a/b` (no slash) is **301-redirected** to `/a/b/` automatically. Refresh or
  share any deep link and it 200s.
- Rich SEO shells per route (title, meta description, canonical, Open Graph, JSON-LD,
  visible teaser for details) are emitted at build time — see `README.md` "Routes / SEO".
- Canonicals are absolute by default: `SITE_BASE` already points at the live deployment
  origin, so the shipped build carries production absolute URLs with no per-environment
  config. Override it (`--site-base`, `SITE_BASE`, `viewer.env`) only if hosting changes.
- If the GitHub Actions Pages workflow ever needs the SITE_BASE for the committed dist, the
  value is decided when `dist/` was built (the workflow itself only deploys).

---

## How paths are resolved

Higher wins. All four sources can supply `ink_root`, `out_dir`, `game_root` (and `SITE_BASE`):

1. **CLI positional args / flags** — `python3 build_app.py <ink_root> <out_dir> <game_root>` (+ `--site-base <url>`)
2. **Environment variables** — `INK_ROOT`, `INK_OUT`, `GAME_ROOT`, `SITE_BASE`
3. **Config file** — `viewer.env` (optional, next to the script), same keys, one per line
4. **Portable defaults** — see the table above

Examples of each:

```bash
# 1. everything explicit (Windows paths)
python3 build_app.py "C:\Users\me\Ink" "C:\Users\me\out" "C:\Users\me\SovereignTowerCode"

# 2. via environment
set GAME_ROOT=C:\Users\me\SovereignTowerCode && python3 build_app.py   (Windows cmd)
GAME_ROOT=/srv/game INK_OUT=/tmp/out python3 build_app.py              (Linux)

# 3. viewer.env next to build_app.py
#    GAME_ROOT = C:\Users\me\SovereignTowerCode
#    INK_ROOT  = C:\Users\me\Ink
#    INK_OUT   = C:\Users\me\out
```

`viewer.env` is `KEY = VALUE` per line; `#` starts a comment. Relative values in
it resolve against your working directory. It is ignored entirely if absent.

---

## Common workflows

```bash
# Rebuild with default paths (needs pip zstandard for the in-memory ink decode)
python3 build_app.py

# Rebuild reading pre-extracted ink from disk instead (no zstandard needed)
python3 build_app.py --from-disk

# Just (re)extract master.ink.json files so you can inspect them / build --from-disk
python3 build_app.py --extract-ink            # writes ../game/InkExtracted/<locale>/master.ink.json

# Build and keep the extracted ink on disk for later use
python3 build_app.py --save-ink

# Diagnose which paths a build would actually use
python3 build_app.py --help
```

After any build: `cd out_dir && python3 -m http.server 8000`, then open
http://localhost:8000 in a browser. The site is fully static (relative fetches),
so it also works from GitHub Pages or `file://`.

---

## Related standalone scripts

These share the same `viewer.env` and can be run on their own:

| script | usage | output |
|---|---|---|
| `quest_data.py` | `python3 quest_data.py <game_root> [quest_out]` | `dist/quests.json` |
| `ink_extract.py` | `python3 ink_extract.py <game_root> [out_dir]` | `out_dir/<locale>/master.ink.json` |

`inventory_data.py`, `knights_data.py`, `special_data.py` also accept
`<game_root> [out]`; `special_data.py` reads `index.json`/`quests.json`/
`knights.json` from `out`, so run it after the others. `audience_data.py`
reads `index.json`/`quests.json` from `out` (run it after those two).

---

## Troubleshooting

- **`ERROR: in-memory ink extraction needs the zstandard pip package`** — install it:
  `pip install zstandard`, or extract the ink once (`--extract-ink`) and build with
  `--from-disk` (stdlib-only).
- **`ERROR: no master.ink.json found under ...` (--from-disk mode)** — there are no
  extracted stories at `ink_root`. Run `python3 build_app.py --extract-ink` once.
- **`ERROR: no en ink story available`** — the build needs the `en` locale; the ink
  source has no `en` story. Check `ink_root`/game `.res` chain.
- **Sizes differ between two machines** — the output is a pure function of the two
  inputs (ink story + game tree). If `quests.json`/`index.json` differ, the inputs
  differ: re-extract the ink (`--extract-ink`) and compare `master.ink.json`, and
  compare the `content/` trees under each `game_root`.

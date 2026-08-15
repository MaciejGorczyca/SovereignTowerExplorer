"""Shared helpers for the explorer test suite (paths, loaders, guards)."""
import json
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
EXPLORER = TESTS.parent
GAME_ROOT = EXPLORER.parent / "game" / "SovereignTowerCode"
DIST = EXPLORER / "dist"

for _p in (str(TESTS), str(EXPLORER)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def game_available() -> bool:
    """True when the full game project (with the compiled-ink story chain) is present."""
    return (GAME_ROOT / "story").is_dir()


def has_zstandard() -> bool:
    try:
        import zstandard  # noqa: F401
        return True
    except ImportError:
        return False


def has_node() -> bool:
    from shutil import which
    return which("node") is not None


def load_dist(name: str):
    """Load a JSON file from the checked-in dist/ directory."""
    with open(DIST / name, encoding="utf-8") as f:
        return json.load(f)


def token_shape(tokens):
    """Locale-neutral structural fingerprint: [token_type, arg_shapes...].

    Text content is ignored; only the encoding shape (the thing a refactor of
    the token stream must preserve) is compared.
    """
    return [[t[0]] + [len(x) if isinstance(x, (list, dict)) else None for x in t[1:]]
            for t in tokens]

"""Frontend sanity checks (node --check + headless render smoke).

`node --check` catches syntax errors in the shipped dist/app.js; the smoke
script (tests/frontend_smoke.js) boots the full app in a VM with a minimal DOM
stub, renders every tab's data, and calls renderDialogue() across all 922
knots expecting zero throws. Skips when node is not installed.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

from helpers import DIST, EXPLORER, has_node

APP_JS = DIST / "app.js"
SMOKE = EXPLORER / "tests" / "frontend_smoke.js"


@unittest.skipUnless(has_node(), "node not installed")
class FrontendTest(unittest.TestCase):
    def test_app_js_syntax(self):
        proc = subprocess.run(["node", "--check", str(APP_JS)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_headless_render_smoke(self):
        proc = subprocess.run(["node", str(SMOKE)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         "smoke failed:\n%s\n%s" % (proc.stdout, proc.stderr))
        self.assertIn("frontend smoke OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()

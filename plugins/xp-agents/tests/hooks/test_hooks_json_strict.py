#!/usr/bin/env python3
"""Pin: hooks.json must parse as strict JSON.

Claude Code rejects non-strict JSON (trailing commas, comments) in hook
manifests. `ruff format` reformats JSON files and can introduce trailing
commas, so ruff.toml carries `extend-exclude = ["**/hooks*.json"]` plus
`force-exclude = true` as defense-in-depth against ad-hoc invocations
like `ruff format .`. This pin catches the symptom if those guards are
ever relaxed.

`HooksJsonTestCase.setUp` already does the strict `json.load`; this test
exists primarily to document the threat model.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _hooks_json import HooksJsonTestCase


class TestHooksJsonStrict(HooksJsonTestCase):
    def test_hooks_json_parses_strict(self):
        self.assertIsInstance(self.data, dict)
        self.assertIn("hooks", self.data)

#!/usr/bin/env python3
"""Tests for plugin_loader.py — plugin-root resolution and guide loading.

Extracted from test_common.py as part of _common.py split (debt
df93d08c853d). The plugin_loader module owns CLAUDE_PLUGIN_ROOT
resolution and the load_xp_values / load_process_guide /
load_teammate_guide helpers; their tests follow.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import plugin_loader


class TestResolvePluginRoot(unittest.TestCase):
    def test_from_env_var(self):
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/opt/plugins/xp"}):
            result = plugin_loader.resolve_plugin_root()
            self.assertEqual(result, Path("/opt/plugins/xp"))

    def test_fallback_to_file_parent(self):
        with patch.dict(os.environ, {}, clear=True):
            result = plugin_loader.resolve_plugin_root()
            # Parent of parent of __file__: scripts/plugin_loader.py -> root
            expected = Path(plugin_loader.__file__).parent.parent
            self.assertEqual(result, expected)


class TestGuideSubstitution(unittest.TestCase):
    """${CLAUDE_PLUGIN_ROOT} must be expanded when loading guides — agent
    Bash in claude -p does not see this env var, so the literal would
    break the documented `${CLAUDE_PLUGIN_ROOT}/smm/append.sh` pattern."""

    def _real_root(self) -> str:
        return str(Path(plugin_loader.__file__).parent.parent)

    def test_load_teammate_guide_substitutes_plugin_root(self):
        text = plugin_loader.load_teammate_guide()
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", text)
        self.assertIn(f"{self._real_root()}/smm/append.sh", text)

    def test_load_process_guide_substitutes_plugin_root(self):
        text = plugin_loader.load_process_guide()
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", text)
        self.assertIn(f"{self._real_root()}/smm/append.sh", text)

    def test_load_teammate_guide_uses_env_var_when_set(self):
        # When CLAUDE_PLUGIN_ROOT is set in env, substitution uses it
        # rather than the __file__ fallback. Use the real plugin root
        # path so the file actually loads.
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": self._real_root()}):
            text = plugin_loader.load_teammate_guide()
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", text)
        self.assertIn(f"{self._real_root()}/smm/append.sh", text)

    def test_load_xp_values_unchanged(self):
        # XP_VALUES.md does not reference ${CLAUDE_PLUGIN_ROOT}, so the
        # substitution helper is not applied — loader returns raw text.
        text = plugin_loader.load_xp_values()
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", text)
        self.assertIn("XP", text)

    def test_loader_re_reads_after_env_changes(self):
        """load_xp_values must reflect the current CLAUDE_PLUGIN_ROOT, not a
        cached value from a previous call. Caching across env mutations was
        a real footgun: a test that called the loader with a bad env would
        poison the result for every subsequent in-process caller.
        """
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/nonexistent/path"}):
            self.assertEqual(plugin_loader.load_xp_values(), "")

        text = plugin_loader.load_xp_values()
        self.assertIn("Extreme Programming", text)


if __name__ == "__main__":
    unittest.main()

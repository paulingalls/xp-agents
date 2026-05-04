#!/usr/bin/env python3
"""Integration tests for write_marker / consume_marker in _preload_base.sh.

Exercises the shell wrappers with shell-sensitive characters in content
to catch string-interpolation fragility (single/double quotes, backslashes).
"""

import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_IN_PROGRESS,
    _IntegrationTestCase,
)

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_PRELOAD_BASE = _PLUGIN_ROOT / "skills" / "_preload_base.sh"
_XP_ACCEPT_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-accept" / "scripts" / "preload.sh"


class TestMarkerShellHelpers(_IntegrationTestCase):
    def _run_shell(self, cmd: str) -> subprocess.CompletedProcess:
        """Source _preload_base.sh and run a shell command in that context."""
        script = f"set -e\nsource {_PRELOAD_BASE}\n{cmd}\n"
        return subprocess.run(
            ["bash", "-c", script],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=self._test_env,
        )

    def test_write_marker_preserves_tricky_content(self):
        cases = [
            ("single_quote", "what's up"),
            ("backslash", r"path\with\backslashes"),
            ("double_quote", 'say "hi" now'),
            ("mixed", 'it\'s a "test" with \\backslash'),
        ]
        for name, tricky in cases:
            with self.subTest(case=name):
                result = self._run_shell(
                    f"write_marker NEEDS_HOUSEKEEPING {shlex.quote(tricky)}"
                )
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                marker_path = self.smm_dir / markers.NEEDS_HOUSEKEEPING.name
                self.assertTrue(
                    marker_path.exists(),
                    f"marker not written; stderr={result.stderr}",
                )
                self.assertEqual(marker_path.read_text(encoding="utf-8"), tricky)
                marker_path.unlink()

    def test_consume_marker_removes_file(self):
        tricky = "hello 'world'"
        result = self._run_shell(
            f"write_marker NEEDS_HOUSEKEEPING {shlex.quote(tricky)}\n"
            f"consume_marker NEEDS_HOUSEKEEPING"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        marker_path = self.smm_dir / markers.NEEDS_HOUSEKEEPING.name
        self.assertFalse(marker_path.exists())


class TestXpAcceptPreloadAcceptActive(_IntegrationTestCase):
    """xp-accept preload arms ACCEPT_ACTIVE iff there are in-progress stories."""

    def test_arms_marker_when_in_progress(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE),
            msg=f"stdout={result.stdout}",
        )

    def test_skips_marker_when_no_in_progress(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_ALL_DONE)
        result = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE),
            msg=f"stdout={result.stdout}",
        )

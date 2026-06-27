#!/usr/bin/env python3
"""Integration tests for the /xp-quality-review preload RISK signal (story-002).

The preload calls risk_classifier on the changed-file set and emits
`RISK=high|low` + `SIGNALS=<file>:<sig>+<sig> ...` lines. The SKILL routes
RISK=high diffs to bounded parallel multi-angle escalation; RISK=low is
the default single-spawn path (today's behavior).

Project-agnosticism: signals are content-shape heuristics, not path
patterns — see system_context principle plugin-project-agnostic. This
test uses synthetic fixtures (one high-content, one low-content) so the
assertion is on what the classifier SEES in any project, not on this
repo's own surface names.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _bases import _PLUGIN_ROOT
from conftest import _IntegrationTestCase

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"

_HIGH_RISK_SRC = """\
import sys
import threading

LOCK = threading.Lock()

def gate(ok: bool) -> None:
    with LOCK:
        if not ok:
            sys.exit(2)
"""

_LOW_RISK_SRC = """\
NAME = "demo"
VERSION = "1.0"
PI = 3.14
"""


class TestQualityReviewRiskGate(_IntegrationTestCase):
    """preload.sh emits RISK=high|low for the changed-file set."""

    def _git(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.tmpdir, capture_output=True, text=True, check=True
        )

    def _checkout_main_clean(self) -> None:
        self._git("checkout", "-f", "main")
        subprocess.run(["git", "clean", "-fd"], cwd=self.tmpdir, capture_output=True)

    def _extract_var(self, stdout: str, name: str) -> str | None:
        prefix = f"{name}="
        for line in stdout.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :]
        return None

    def test_low_risk_docs_fixture_emits_low(self):
        """A staged docs change has no risk signals → RISK=low."""
        self._checkout_main_clean()
        (self.tmpdir / "notes.md").write_text("# heading\n\nplain text\n")
        self._git("add", "notes.md")
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._extract_var(result.stdout, "RISK"), "low")

    def test_low_risk_pure_data_python_emits_low(self):
        """A staged pure-data .py change has no risk signals → RISK=low."""
        self._checkout_main_clean()
        (self.tmpdir / "constants.py").write_text(_LOW_RISK_SRC)
        self._git("add", "constants.py")
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._extract_var(result.stdout, "RISK"), "low")

    def test_high_risk_lock_and_exit_emits_high_naming_file(self):
        """A staged file with lock + exit signals → RISK=high + named in SIGNALS."""
        self._checkout_main_clean()
        (self.tmpdir / "guarded_handler.py").write_text(_HIGH_RISK_SRC)
        self._git("add", "guarded_handler.py")
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._extract_var(result.stdout, "RISK"), "high")
        signals = self._extract_var(result.stdout, "SIGNALS") or ""
        self.assertIn("guarded_handler.py", signals)

    def test_no_changes_emits_low(self):
        """A clean working tree has no changed files → RISK=low."""
        self._checkout_main_clean()
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._extract_var(result.stdout, "RISK"), "low")

    def test_preload_has_classifier_error_fallback(self):
        """Content guard: the preload's safe-fallback line is present.

        A classifier crash must default to RISK=low rather than block the
        increment. Verified by reading preload.sh; the integration runtime
        path is exercised by the other three tests + the classifier's own
        crash-resistance unit tests (missing file, non-.py extension, etc.).
        """
        body = _PRELOAD.read_text()
        self.assertIn("risk_classifier.py", body)
        self.assertIn("RISK=low", body)
        self.assertIn("classifier error", body)

#!/usr/bin/env python3
"""Tests for plugins/xp-agents/skills/xp-end-session/scripts/format_preload.py.

Pins the four-section stdout shape (CANDIDATES / OPEN_QUESTIONS /
MAYBE_ADDRESSED / UNCOMMITTED) so trim refactors can't drift the
contract preload.sh consumers depend on.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, make_event
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_DEBT, EVENT_TYPE_QUESTION

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_FORMAT_SCRIPT = (
    _PLUGIN_ROOT / "skills" / "xp-end-session" / "scripts" / "format_preload.py"
)
sys.path.insert(0, str(_FORMAT_SCRIPT.parent))

import format_preload  # noqa: E402


def _run(smm_dir: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(_FORMAT_SCRIPT), "--smm-dir", str(smm_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


class TestFormatPreloadEmptySMM(_SMMTestCase):
    def test_empty_smm_emits_all_four_section_headers(self):
        out = _run(self.smm_dir)
        self.assertIn("### CANDIDATES", out)
        self.assertIn("### OPEN_QUESTIONS", out)
        self.assertIn("### MAYBE_ADDRESSED", out)
        self.assertIn("### UNCOMMITTED", out)

    def test_empty_smm_uncommitted_count_zero(self):
        out = _run(self.smm_dir)
        # UNCOMMITTED section trails with "0" on its own line
        lines = out.splitlines()
        self.assertEqual(lines[-1], "0")


class TestFormatPreloadPopulated(_SMMTestCase):
    def test_open_question_id_appears_in_open_questions_section(self):
        q = make_event(EVENT_TYPE_QUESTION, content="Why?")
        self._write_events([q])
        out = _run(self.smm_dir)
        # OPEN_QUESTIONS section emits each question id on its own line
        oq_idx = out.index("### OPEN_QUESTIONS")
        la_idx = out.index("### MAYBE_ADDRESSED")
        section = out[oq_idx:la_idx]
        self.assertIn(q["id"], section)

    def test_maybe_addressed_renders_id_and_commit_hashes(self):
        debt = make_event(
            EVENT_TYPE_DEBT,
            content="cleanup",
            files=["scripts/auth.py"],
            ts="2026-01-01T00:00:00+00:00",
        )
        commit = make_event(
            EVENT_TYPE_COMMIT,
            content="cleanup auth",
            files=["scripts/auth.py"],
            ts="2026-01-02T00:00:00+00:00",
            metadata={"commit_hash": "abc1234"},
        )
        self._write_events([debt, commit])
        out = _run(self.smm_dir)
        la_idx = out.index("### MAYBE_ADDRESSED")
        un_idx = out.index("### UNCOMMITTED")
        section = out[la_idx:un_idx]
        # Format: "- {id}\n  - {commit_hash}"
        self.assertIn(f"- {debt['id']}", section)
        self.assertIn("  - abc1234", section)


class TestFormatPreloadInProcess(unittest.TestCase):
    def test_main_calls_draft_summary_run_with_smm_dir(self):
        # In-process test: stub draft_summary.run, verify wire-through
        captured = {}

        def fake_run(smm_dir):
            captured["smm_dir"] = smm_dir
            return {
                "summary": "S",
                "open_questions": ["q1"],
                "maybe_addressed": [{"id": "d1", "commits": ["h1", "h2"]}],
                "uncommitted_count": 3,
            }

        argv = ["format_preload.py", "--smm-dir", "/tmp/x"]
        from io import StringIO

        buf = StringIO()
        with (
            patch.object(format_preload.draft_summary, "run", side_effect=fake_run),
            patch.object(sys, "argv", argv),
            patch.object(sys, "stdout", buf),
        ):
            format_preload.main()
        out = buf.getvalue()

        self.assertEqual(captured["smm_dir"], Path("/tmp/x"))
        self.assertIn("### CANDIDATES", out)
        self.assertIn("S", out)
        self.assertIn("### OPEN_QUESTIONS", out)
        self.assertIn("q1", out)
        self.assertIn("### MAYBE_ADDRESSED", out)
        self.assertIn("- d1", out)
        self.assertIn("  - h1", out)
        self.assertIn("  - h2", out)
        self.assertIn("### UNCOMMITTED", out)
        self.assertIn("3", out)


if __name__ == "__main__":
    unittest.main()

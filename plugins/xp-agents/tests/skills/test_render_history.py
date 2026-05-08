#!/usr/bin/env python3
"""Tests for plugins/xp-agents/skills/xp-kickoff/scripts/render_history.py.

Story-001 of sprint-072: pure-stdlib script that reads session_history.json
and prints a `### LAST_SESSION` block (last 1-2 entries' summary plus open
carry_forward notes) to stdout. Fail-quiet on missing/corrupt/schema-bad
files so the kickoff preload never breaks.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import session_history
from conftest import _SMMTestCase, make_session_history_entry

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_RENDER_SCRIPT = (
    _PLUGIN_ROOT / "skills" / "xp-kickoff" / "scripts" / "render_history.py"
)
sys.path.insert(0, str(_RENDER_SCRIPT.parent))

import render_history  # noqa: E402

_EVENT_ID_RE = re.compile(r"\b[a-f0-9]{12}\b")


class TestRenderHistoryRun(_SMMTestCase):
    """In-process tests for render_history.run() against seeded session_history.json."""

    def test_missing_file_returns_empty_string(self):
        # No session_history.json on disk — fresh install / first session.
        result = render_history.run(self.smm_dir)
        self.assertEqual(result, "")

    def test_one_entry_renders_summary_and_carry_forward(self):
        session_history.save_history(
            self.smm_dir,
            {
                "version": session_history.SCHEMA_VERSION,
                "entries": [
                    make_session_history_entry(
                        ts="2026-05-07T10:00:00+00:00",
                        summary="Shipped session_history pipeline.",
                        carry_forward=[
                            {
                                "note": "Wire kickoff render next session.",
                                "references": ["abc123def456"],
                                "recommendation": "Pick up story-001 first.",
                            }
                        ],
                    ),
                ],
            },
        )

        result = render_history.run(self.smm_dir)

        self.assertIn("### LAST_SESSION", result)
        self.assertIn("Shipped session_history pipeline.", result)
        self.assertIn("Wire kickoff render next session.", result)
        self.assertIn("Pick up story-001 first.", result)

    def test_two_entries_render_both_in_chronological_order(self):
        session_history.save_history(
            self.smm_dir,
            {
                "version": session_history.SCHEMA_VERSION,
                "entries": [
                    make_session_history_entry(
                        ts="2026-05-06T09:00:00+00:00", summary="Older session."
                    ),
                    make_session_history_entry(
                        ts="2026-05-07T09:00:00+00:00", summary="Newer session."
                    ),
                ],
            },
        )

        result = render_history.run(self.smm_dir)

        self.assertIn("Older session.", result)
        self.assertIn("Newer session.", result)
        self.assertLess(result.index("Older session."), result.index("Newer session."))

    def test_more_than_two_entries_renders_only_last_two(self):
        session_history.save_history(
            self.smm_dir,
            {
                "version": session_history.SCHEMA_VERSION,
                "entries": [
                    make_session_history_entry(
                        ts="2026-05-04T09:00:00+00:00", summary="Oldest A."
                    ),
                    make_session_history_entry(
                        ts="2026-05-05T09:00:00+00:00", summary="Middle B."
                    ),
                    make_session_history_entry(
                        ts="2026-05-07T09:00:00+00:00", summary="Newest C."
                    ),
                ],
            },
        )

        result = render_history.run(self.smm_dir)

        self.assertNotIn("Oldest A.", result)
        self.assertIn("Middle B.", result)
        self.assertIn("Newest C.", result)

    def test_event_ids_in_references_are_not_leaked_to_output(self):
        session_history.save_history(
            self.smm_dir,
            {
                "version": session_history.SCHEMA_VERSION,
                "entries": [
                    make_session_history_entry(
                        ts="2026-05-07T10:00:00+00:00",
                        summary="Summary text without event ids.",
                        carry_forward=[
                            {
                                "note": "Note text.",
                                "references": ["aaaaaaaaaaaa", "bbbbbbbbbbbb"],
                                "recommendation": "Recommendation text.",
                            }
                        ],
                    )
                ],
            },
        )

        result = render_history.run(self.smm_dir)

        leaked = _EVENT_ID_RE.findall(result)
        self.assertEqual(leaked, [], f"event ids leaked into output: {leaked}")

    def test_corrupt_json_returns_empty_string(self):
        path = self.smm_dir / session_history.SESSION_HISTORY_FILENAME
        path.write_text("{not valid json", encoding="utf-8")

        result = render_history.run(self.smm_dir)

        self.assertEqual(result, "")

    def test_schema_version_mismatch_returns_empty_string(self):
        path = self.smm_dir / session_history.SESSION_HISTORY_FILENAME
        path.write_text(json.dumps({"version": 99, "entries": []}), encoding="utf-8")

        result = render_history.run(self.smm_dir)

        self.assertEqual(result, "")

    def test_entry_with_empty_carry_forward_renders_summary_only(self):
        session_history.save_history(
            self.smm_dir,
            {
                "version": session_history.SCHEMA_VERSION,
                "entries": [
                    make_session_history_entry(
                        ts="2026-05-07T10:00:00+00:00",
                        summary="Summary only.",
                        carry_forward=[],
                    )
                ],
            },
        )

        result = render_history.run(self.smm_dir)

        self.assertIn("### LAST_SESSION", result)
        self.assertIn("Summary only.", result)


class TestRenderHistorySubprocess(_SMMTestCase):
    """E2E test invoking render_history.py as a subprocess.

    Mirrors how check_session_needs.sh will call it.
    """

    def test_subprocess_with_populated_history_prints_block(self):
        session_history.save_history(
            self.smm_dir,
            {
                "version": session_history.SCHEMA_VERSION,
                "entries": [
                    make_session_history_entry(
                        ts="2026-05-07T10:00:00+00:00",
                        summary="E2E subprocess summary.",
                        carry_forward=[],
                    )
                ],
            },
        )

        result = subprocess.run(
            [sys.executable, str(_RENDER_SCRIPT), "--smm-dir", str(self.smm_dir)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("### LAST_SESSION", result.stdout)
        self.assertIn("E2E subprocess summary.", result.stdout)

    def test_subprocess_with_no_history_file_exits_zero_silently(self):
        result = subprocess.run(
            [sys.executable, str(_RENDER_SCRIPT), "--smm-dir", str(self.smm_dir)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()

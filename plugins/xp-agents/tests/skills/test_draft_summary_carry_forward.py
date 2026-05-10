#!/usr/bin/env python3
"""Tests for draft_summary's carry_forward surfacing path.

Split from test_draft_summary.py at the commit that pushed it past
the 500-line target — keeps each suite single-responsibility.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import unittest

import event_schema
from conftest import _SMMTestCase, make_event

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "skills" / "xp-end-session" / "scripts"))

import draft_summary  # noqa: E402


class TestDraftSummaryCarryForward(_SMMTestCase):
    """Story-002 of sprint-071: carry_forward candidates surfacing."""

    def test_carry_forward_empty_for_clean_session(self):
        # Only commits — no open questions, no high-severity concerns.
        events = [
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="cle000000001",
                content="feat: thing",
                ts="2026-05-08T20:00:00+00:00",
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["carry_forward"], [])

    def test_carry_forward_includes_open_question(self):
        question = make_event(
            event_schema.EVENT_TYPE_QUESTION,
            id="qcf000000001",
            content="why does X happen?",
            ts="2026-05-08T20:01:00+00:00",
            priority=event_schema.PRIORITY_ASSUMED,
        )
        self._write_events([question])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(
            result["carry_forward"],
            [
                {
                    "note": "why does X happen?",
                    "references": ["qcf000000001"],
                    "recommendation": "triage",
                }
            ],
        )

    def test_carry_forward_includes_high_severity_unresolved_concern(self):
        concern = make_event(
            event_schema.EVENT_TYPE_CONCERN,
            id="hcf000000001",
            content="auth bypass possible",
            ts="2026-05-08T20:02:00+00:00",
            severity="high",
        )
        self._write_events([concern])
        result = draft_summary.run(self.smm_dir)
        self.assertIn(
            {
                "note": "auth bypass possible",
                "references": ["hcf000000001"],
                "recommendation": "watch",
            },
            result["carry_forward"],
        )

    def test_carry_forward_excludes_likely_addressed_concern(self):
        # High-severity concern with a file overlap commit after it →
        # appears in likely_addressed → must NOT appear in carry_forward.
        concern = make_event(
            event_schema.EVENT_TYPE_CONCERN,
            id="acf000000001",
            content="bug in a.py",
            files=["a.py"],
            ts="2026-05-08T20:03:00+00:00",
            severity="high",
        )
        commit = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="acf000000002",
            content="fix(a.py): patch",
            files=["a.py"],
            ts="2026-05-08T20:04:00+00:00",
            metadata={
                "action": "commit_success",
                "commit_hash": "abc1230000000000000000000000000000000009",
            },
        )
        self._write_events([concern, commit])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(len(result["likely_addressed"]), 1)
        self.assertEqual(result["likely_addressed"][0]["id"], "acf000000001")
        self.assertEqual(result["carry_forward"], [])

    def test_existing_keys_unchanged_when_carry_forward_added(self):
        # Pin the return-shape contract: M-2 must not rename/drop existing keys.
        events = [
            make_event(
                event_schema.EVENT_TYPE_QUESTION,
                id="exi000000001",
                content="open?",
                ts="2026-05-08T20:05:00+00:00",
                priority=event_schema.PRIORITY_ASSUMED,
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(
            set(result),
            {
                "summary",
                "open_questions",
                "likely_addressed",
                "uncommitted_count",
                "carry_forward",
            },
        )

    def test_carry_forward_truncates_note_to_100_chars(self):
        long_content = "x" * 250
        question = make_event(
            event_schema.EVENT_TYPE_QUESTION,
            id="trc000000001",
            content=long_content,
            ts="2026-05-08T20:06:00+00:00",
            priority=event_schema.PRIORITY_ASSUMED,
        )
        self._write_events([question])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(len(result["carry_forward"][0]["note"]), 100)

    def test_carry_forward_skips_medium_severity_concern(self):
        # Only high-severity concerns are carried forward — medium/low
        # concerns are noise the user can re-triage next session.
        concern = make_event(
            event_schema.EVENT_TYPE_CONCERN,
            id="med000000001",
            content="minor smell",
            ts="2026-05-08T20:07:00+00:00",
            severity="medium",
        )
        self._write_events([concern])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["carry_forward"], [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for draft_summary's CLI/subprocess wire-format path.

Split from test_draft_summary.py at the commit that pushed it past
the 500-line target — keeps each suite single-responsibility. This
suite drives the script as a subprocess (the real invocation shape)
rather than calling draft_summary.run() in-process, pinning the JSON
payload shape and carry_forward content over the wire.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import event_schema
from conftest import _SMMTestCase, make_event

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_DRAFT_SUMMARY_SCRIPT = (
    _PLUGIN_ROOT / "skills" / "xp-end-session" / "scripts" / "draft_summary.py"
)
sys.path.insert(0, str(_DRAFT_SUMMARY_SCRIPT.parent))


class TestDraftSummaryE2E(_SMMTestCase):
    """Story-002 of sprint-070: end-to-end subprocess wire-format pin."""

    def test_e2e_subprocess(self):
        # AC5: synthetic session with mixed events — open question + resolved
        # concern + open high-severity concern + commits — must yield exactly
        # 2 carry_forward refs (the question and the unresolved high concern)
        # over the wire. Pin the JSON shape AND the carry_forward content.
        events = [
            make_event(
                event_schema.EVENT_TYPE_QUESTION,
                id="e2e000000001",
                content="e2e open question?",
                ts="2026-05-08T09:00:00+00:00",
                priority=event_schema.PRIORITY_ASSUMED,
            ),
            make_event(
                event_schema.EVENT_TYPE_CONCERN,
                id="e2e000000002",
                content="resolved concern",
                severity="high",
                ts="2026-05-08T09:01:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_STATUS,
                id="e2e000000003",
                content="resolved by commit",
                ts="2026-05-08T09:02:00+00:00",
                metadata={"resolves": ["e2e000000002"]},
            ),
            make_event(
                event_schema.EVENT_TYPE_CONCERN,
                id="e2e000000004",
                content="open high-severity concern",
                severity="high",
                ts="2026-05-08T09:03:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="e2e000000005",
                content="feat: thing",
                ts="2026-05-08T09:04:00+00:00",
            ),
        ]
        self._write_events(events)
        r = subprocess.run(
            [
                sys.executable,
                str(_DRAFT_SUMMARY_SCRIPT),
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(
            set(payload),
            {
                "summary",
                "open_questions",
                "maybe_addressed",
                "uncommitted_count",
                "carry_forward",
            },
        )
        self.assertEqual(payload["open_questions"], ["e2e000000001"])
        carry_refs = sorted(
            ref for item in payload["carry_forward"] for ref in item["references"]
        )
        self.assertEqual(carry_refs, ["e2e000000001", "e2e000000004"])
        self.assertEqual(len(payload["carry_forward"]), 2)


if __name__ == "__main__":
    unittest.main()

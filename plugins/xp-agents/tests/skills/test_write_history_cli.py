#!/usr/bin/env python3
"""Tests for plugins/xp-agents/skills/xp-end-session/scripts/write_history.py.

Story-003 of sprint-071: thin CLI that reads draft JSON from stdin
(the dict shape produced by draft_summary.run()), persists a new entry
into smm/session_history.json (story-001's module), then runs
prune_resolved against current events.jsonl resolutions.
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

import event_schema
import session_history
from conftest import _SMMTestCase, make_event, run_cli

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_WRITE_HISTORY_SCRIPT = (
    _PLUGIN_ROOT / "skills" / "xp-end-session" / "scripts" / "write_history.py"
)
_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-end-session" / "SKILL.md"


def _draft(
    summary: str = "session narrative",
    carry_forward: list[dict] | None = None,
) -> str:
    return json.dumps(
        {
            "summary": summary,
            "open_questions": [],
            "likely_addressed": [],
            "uncommitted_count": 0,
            "carry_forward": carry_forward or [],
        }
    )


def _run_cli(smm_dir: Path, stdin_text: str) -> subprocess.CompletedProcess:
    return run_cli(_WRITE_HISTORY_SCRIPT, [], smm_dir, stdin_data=stdin_text)


class TestWriteHistoryCLI(_SMMTestCase):
    """Story-003: write_history.py thin CLI."""

    def test_valid_stdin_creates_history_with_one_entry(self):
        # AC1: fresh SMM_DIR + valid draft → 1 entry; exit 0
        result = _run_cli(self.smm_dir, _draft(summary="hello world"))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = session_history.load_history(self.smm_dir)
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["summary"], "hello world")
        self.assertEqual(data["entries"][0]["carry_forward"], [])
        self.assertIn("ts", data["entries"][0])

    def test_carry_forward_persists_when_unresolved(self):
        # Carry-forward refs have no resolution events yet → must persist
        cf = [
            {
                "note": "open question",
                "references": ["q00000000001"],
                "recommendation": "triage",
            }
        ]
        # Seed an open question so the reference lands in events.jsonl
        self._write_events(
            [
                make_event(
                    event_schema.EVENT_TYPE_QUESTION,
                    id="q00000000001",
                    content="open?",
                    ts="2026-05-08T10:00:00+00:00",
                    priority=event_schema.PRIORITY_ASSUMED,
                )
            ]
        )
        result = _run_cli(self.smm_dir, _draft(carry_forward=cf))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = session_history.load_history(self.smm_dir)
        self.assertEqual(data["entries"][0]["carry_forward"], cf)

    def test_carry_forward_pruned_when_referenced_event_already_resolved(self):
        # AC2: draft carries a ref; events.jsonl already resolves it →
        # prune_resolved drops the item before save
        cf = [
            {
                "note": "resolved q",
                "references": ["q11111111111"],
                "recommendation": "triage",
            }
        ]
        self._write_events(
            [
                make_event(
                    event_schema.EVENT_TYPE_QUESTION,
                    id="q11111111111",
                    content="answered?",
                    ts="2026-05-08T10:00:00+00:00",
                    priority=event_schema.PRIORITY_ASSUMED,
                ),
                make_event(
                    event_schema.EVENT_TYPE_ANSWER,
                    id="a11111111111",
                    content="yes",
                    ts="2026-05-08T10:01:00+00:00",
                    references=["q11111111111"],
                ),
            ]
        )
        result = _run_cli(self.smm_dir, _draft(carry_forward=cf))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = session_history.load_history(self.smm_dir)
        self.assertEqual(data["entries"][0]["carry_forward"], [])

    def test_malformed_stdin_exits_nonzero_with_stderr_message(self):
        # AC3: bad JSON → non-zero exit, stderr names the parse error
        result = _run_cli(self.smm_dir, "not json {")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("JSON", result.stderr)
        # session_history.json must NOT exist after failure
        self.assertFalse(
            (self.smm_dir / session_history.SESSION_HISTORY_FILENAME).exists()
        )

    def test_six_invocations_yield_five_entries_oldest_evicted(self):
        # AC5: ring-buffer behavior end-to-end via CLI
        for i in range(6):
            r = _run_cli(self.smm_dir, _draft(summary=f"session {i}"))
            self.assertEqual(r.returncode, 0, r.stderr)
        data = session_history.load_history(self.smm_dir)
        self.assertEqual(len(data["entries"]), 5)
        # Oldest evicted: "session 0" should be gone, "session 5" newest
        summaries = [e["summary"] for e in data["entries"]]
        self.assertEqual(summaries, [f"session {i}" for i in range(1, 6)])


class TestSkillMdStep4(unittest.TestCase):
    """Story-003: SKILL.md must document Step 4 invoking write_history.py."""

    def test_skill_md_step_4_renders_pipe_invocation(self):
        # AC4: SKILL.md mentions piping draft_summary.py into write_history.py
        body = _SKILL_MD.read_text(encoding="utf-8")
        # Step 4 heading exists
        self.assertRegex(body, r"##\s+Step 4")
        # The invocation pipes draft_summary | write_history with --smm-dir
        self.assertRegex(
            body,
            re.compile(
                r"draft_summary\.py.*--smm-dir.*\|\s*\n?\s*python3.*"
                r"write_history\.py.*--smm-dir",
                re.DOTALL,
            ),
        )
        # N=5 retention documented in body
        self.assertIn("N=5", body)


if __name__ == "__main__":
    unittest.main()

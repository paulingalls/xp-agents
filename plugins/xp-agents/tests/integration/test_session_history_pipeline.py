#!/usr/bin/env python3
"""Capstone E2E for the M-2 session_history.json pipeline.

Story-004 of sprint-071. Renders M-2's done-state into an executable
test at the integration scope:

    smm/session_history.py module exports load_history/append_entry/
    prune_resolved. Skill writes both event AND history per invocation.
    Capstone covers ring-buffer eviction at N=5, carry_forward drop
    when references resolve (cascade across sessions), corrupt-file
    rejection, atomic-write symlink rejection through the pipe, and
    two-layer payload distinction.

The LLM is simulated via direct subprocess calls of draft_summary.py
piped into write_history.py — the exact pipe SKILL.md Step 4
instructs the LLM to invoke. Two-session simulation exercises the
cross-session cascade-prune (open question carried forward, then
resolved next session, then dropped from history).

AC-5 reconciliation: sprint.json AC-5 says "session_summary events
AND session_history.json both reflect the same canonical narrative
without divergence". The fix in concern b7cc0664c2e6 made this literal:
draft_summary._build_summary now prefers the latest session_summary
event's content over the mechanical event-log scan when a summary
exists. Mechanical synthesis remains as the fallback for the
format_preload CANDIDATES draft (which runs BEFORE Step 1 has
authored anything). Net: events.jsonl and session_history.json carry
the SAME canonical narrative — fully honoring AC-5's intent.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import event_schema
import session_history
from _bases import _PLUGIN_ROOT, _IntegrationTestCase
from conftest import make_event, run_cli

_SKILL_SCRIPTS = _PLUGIN_ROOT / "skills" / "xp-end-session" / "scripts"
_DRAFT_SUMMARY = _SKILL_SCRIPTS / "draft_summary.py"
_WRITE_HISTORY = _SKILL_SCRIPTS / "write_history.py"


class TestSessionHistoryPipeline(_IntegrationTestCase):
    """Two-session E2E for the draft_summary | write_history pipe."""

    Q_ID = "abcdef000001"
    CONCERN_ID = "abcdef000002"

    def _run_pipe(self) -> subprocess.CompletedProcess:
        """Run `draft_summary | write_history` against the test SMM_DIR."""
        draft = run_cli(_DRAFT_SUMMARY, [], self.smm_dir)
        self.assertEqual(draft.returncode, 0, draft.stderr)
        return run_cli(_WRITE_HISTORY, [], self.smm_dir, stdin_data=draft.stdout)

    def test_session1_persists_carry_forward_for_open_items(self):
        # Session 1: open question + open high-severity concern → both
        # land as carry_forward in session_history.json.
        self._seed_events(
            [
                make_event(
                    event_schema.EVENT_TYPE_QUESTION,
                    id=self.Q_ID,
                    content="should we cache?",
                    ts="2026-05-08T10:00:00+00:00",
                    priority=event_schema.PRIORITY_ASSUMED,
                ),
                make_event(
                    event_schema.EVENT_TYPE_CONCERN,
                    id=self.CONCERN_ID,
                    content="auth bypass risk",
                    ts="2026-05-08T10:01:00+00:00",
                    severity="high",
                ),
            ]
        )
        r = self._run_pipe()
        self.assertEqual(r.returncode, 0, r.stderr)

        history = session_history.load_history(self.smm_dir)
        self.assertEqual(history["version"], 1)
        self.assertEqual(len(history["entries"]), 1)
        refs = {
            ref
            for item in history["entries"][0]["carry_forward"]
            for ref in item["references"]
        }
        self.assertEqual(refs, {self.Q_ID, self.CONCERN_ID})

    def test_session2_prunes_session1_carry_forward_when_resolved(self):
        # Session 1: same as above.
        self._seed_events(
            [
                make_event(
                    event_schema.EVENT_TYPE_QUESTION,
                    id=self.Q_ID,
                    content="should we cache?",
                    ts="2026-05-08T10:00:00+00:00",
                    priority=event_schema.PRIORITY_ASSUMED,
                ),
                make_event(
                    event_schema.EVENT_TYPE_CONCERN,
                    id=self.CONCERN_ID,
                    content="auth bypass risk",
                    ts="2026-05-08T10:01:00+00:00",
                    severity="high",
                ),
            ]
        )
        r1 = self._run_pipe()
        self.assertEqual(r1.returncode, 0, r1.stderr)

        # Session 2: append answer for the question + status with
        # metadata.resolves for the concern.
        ans = self._run_append(
            "--type",
            event_schema.EVENT_TYPE_ANSWER,
            "--agent",
            "test",
            "--references",
            json.dumps([self.Q_ID]),
            "--content",
            "yes — LRU with 5min TTL",
        )
        self.assertEqual(ans.returncode, 0, ans.stderr)

        res = self._run_append(
            "--type",
            "status",
            "--agent",
            "test",
            "--content",
            "auth review complete",
            "--working-on",
            "[]",
            "--metadata",
            json.dumps({event_schema.METADATA_KEY_RESOLVES: [self.CONCERN_ID]}),
        )
        self.assertEqual(res.returncode, 0, res.stderr)

        r2 = self._run_pipe()
        self.assertEqual(r2.returncode, 0, r2.stderr)

        history = session_history.load_history(self.smm_dir)
        self.assertEqual(len(history["entries"]), 2)
        # Session 1's carry_forward should have been pruned by the
        # resolutions session 2 just added.
        self.assertEqual(history["entries"][0]["carry_forward"], [])
        # Session 2 itself emits no fresh carry_forward — both items
        # are now resolved.
        self.assertEqual(history["entries"][1]["carry_forward"], [])

    def test_seven_invocations_yield_five_entries_oldest_evicted(self):
        # No seeded events needed — empty drafts still produce entries.
        for _ in range(7):
            r = self._run_pipe()
            self.assertEqual(r.returncode, 0, r.stderr)
        history = session_history.load_history(self.smm_dir)
        self.assertEqual(len(history["entries"]), 5)
        # Chronological order — entries are appended, never reordered.
        timestamps = [e["ts"] for e in history["entries"]]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_symlink_history_file_rejected_through_pipe(self):
        # session_history.save_history rejects symlink targets per its
        # docstring contract. Exercise it end-to-end through the CLI
        # pipe so the symlink protection holds at the integration
        # boundary, not just in the unit test.
        path = self.smm_dir / session_history.SESSION_HISTORY_FILENAME
        sentinel = self.smm_dir / "_sentinel_history.json"
        sentinel.write_text(
            '{"version": 1, "entries": [{"ts": "2026-01-01T00:00:00+00:00",'
            ' "summary": "preexisting", "carry_forward": []}]}'
        )
        path.symlink_to(sentinel)

        r = self._run_pipe()
        self.assertNotEqual(r.returncode, 0)
        # Pin the failure to the symlink rejection — without this, an
        # unrelated regression in draft_summary | write_history would
        # let the test false-pass on any non-zero exit.
        self.assertIn("symlink", r.stderr)
        # write_history.main()'s try/except must produce a one-line
        # message, not a raw traceback (sprint-close-reviewer 4a2f4ac).
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("write_history failed", r.stderr)
        # The symlink target must NOT have been overwritten.
        self.assertIn("preexisting", sentinel.read_text())

    def test_corrupt_history_file_rejected_and_left_unmodified(self):
        # Pre-corrupt the history file with garbage JSON.
        path = self.smm_dir / session_history.SESSION_HISTORY_FILENAME
        garbage = b"{not json"
        path.write_bytes(garbage)

        r = self._run_pipe()
        self.assertNotEqual(r.returncode, 0)
        # Underlying corrupt file MUST be left untouched.
        self.assertEqual(path.read_bytes(), garbage)
        # Same no-traceback contract as the symlink path.
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("write_history failed", r.stderr)

    def test_history_carries_refined_summary_not_mechanical_scan(self):
        # AC-5 contract (post b7cc0664c2e6 fix): both the events.jsonl
        # session_summary event AND the session_history.json entry carry
        # the SAME refined narrative. Mechanical scan only fills in for
        # the format_preload CANDIDATES draft (raw material the agent
        # reads BEFORE Step 1) — never persisted.
        narrative_marker = "AGENT_NARRATIVE_MARKER_42"
        r = self._run_append(
            "--type",
            event_schema.EVENT_TYPE_SESSION_SUMMARY,
            "--agent",
            "xp-end-session",
            "--content",
            f"Shipped pipeline. {narrative_marker}",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # Append a status event AFTER the narrative — the mechanical scan
        # would pick it up if write_history were still using the synthesis
        # path. Asserts the fast-path beats the synthesis path.
        scan_marker = "MECHANICAL_SCAN_MARKER_99"
        r2 = self._run_append(
            "--type",
            "status",
            "--agent",
            "test",
            "--content",
            f"working on the thing — {scan_marker}",
            "--working-on",
            "[]",
        )
        self.assertEqual(r2.returncode, 0, r2.stderr)

        # Step 4 pipe runs (draft_summary | write_history):
        pipe = self._run_pipe()
        self.assertEqual(pipe.returncode, 0, pipe.stderr)

        # Layer 1 — events.jsonl carries the agent-refined narrative.
        body = (self.smm_dir / "events.jsonl").read_text()
        self.assertIn(narrative_marker, body)
        self.assertIn("session_summary", body)

        # Layer 2 — session_history.json carries the SAME refined narrative.
        history = session_history.load_history(self.smm_dir)
        self.assertEqual(len(history["entries"]), 1)
        persisted = history["entries"][0]["summary"]
        self.assertIn(narrative_marker, persisted)
        # Mechanical scan must NOT leak into the persisted history when a
        # refined session_summary is available — that's the whole point
        # of the fast-path. The status-event scan_marker would appear if
        # the synthesis path had won.
        self.assertNotIn(scan_marker, persisted)
        self.assertNotIn("[status]", persisted)
        self.assertNotIn("[commit]", persisted)

    def test_history_falls_back_to_mechanical_scan_when_no_summary(self):
        # CANDIDATES preload contract: when no session_summary event
        # exists yet (i.e., format_preload runs BEFORE Step 1 has
        # authored anything), draft_summary synthesizes a mechanical
        # event-log narrative for the agent to refine. write_history
        # only runs AFTER Step 1 in normal operation, so this case is
        # rare in the persisted layer — but verifying the fallback path
        # still works guards against a regression where removing the
        # synthesis path entirely would break the format_preload draft.
        scan_marker = "FALLBACK_SCAN_MARKER_77"
        r = self._run_append(
            "--type",
            "status",
            "--agent",
            "test",
            "--content",
            f"working — {scan_marker}",
            "--working-on",
            "[]",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        pipe = self._run_pipe()
        self.assertEqual(pipe.returncode, 0, pipe.stderr)

        # No session_summary event was appended → synthesis path wins,
        # status event surfaces in the persisted summary.
        history = session_history.load_history(self.smm_dir)
        self.assertEqual(len(history["entries"]), 1)
        persisted = history["entries"][0]["summary"]
        self.assertIn(scan_marker, persisted)
        self.assertIn("[status]", persisted)


if __name__ == "__main__":
    unittest.main()

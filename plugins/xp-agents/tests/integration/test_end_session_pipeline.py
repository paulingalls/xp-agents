#!/usr/bin/env python3
"""Capstone E2E integration test for the /xp-end-session pipeline.

Story-004 of sprint-070. Renders milestone M-1's done-state into an
executable test:

    Running /xp-end-session appends one session_summary event per call,
    force-closes/defers open questions via AskUserQuestion, bulk-drops
    maybe-addressed concerns/debts, prints uncommitted-events count.

The LLM (which can't be unit-tested deterministically) is simulated
by direct subprocess invocations of append.sh + smm_cli.py — the
exact CLI calls SKILL.md instructs the LLM to make.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import event_schema
import materialize
import resolution
from _bases import _PLUGIN_ROOT, _IntegrationTestCase
from conftest import make_event
from event_helpers import events_of_type

_PRELOAD_SH = _PLUGIN_ROOT / "skills" / "xp-end-session" / "scripts" / "preload.sh"
sys.path.insert(0, str(_PRELOAD_SH.parent))

import draft_summary  # noqa: E402


class TestEndSessionPipeline(_IntegrationTestCase):
    """Exercise the full /xp-end-session pipeline end-to-end."""

    # 12-char lowercase hex ids — validate_event enforces this for any
    # id surfaced in metadata.resolves (event_schema EVENT_ID_RE).
    Q1_ID = "a11111111111"  # answered in test 2
    Q2_ID = "a22222222222"  # closed via won-fix in test 2
    CONCERN_ID = "c33333333333"
    COMMIT_ID = "c44444444444"  # SMM commit-event id (NOT a git ref)
    # Real git SHA — what MAYBE_ADDRESSED surfaces and what
    # resolved_by_commits should record (post-commit hook writes this
    # into metadata.commit_hash on every commit event).
    COMMIT_HASH = "abc1230000000000000000000000000000000010"

    def setUp(self):
        super().setUp()
        events = [
            make_event(
                event_schema.EVENT_TYPE_SESSION_END,
                id="se0000000001",
                content="prior session ended",
                ts="2026-05-07T00:00:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_CONCERN,
                id=self.CONCERN_ID,
                content="bug in a.py",
                ts="2026-05-08T10:00:00+00:00",
                files=["a.py"],
                severity="medium",
            ),
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id=self.COMMIT_ID,
                content="fix(auth): patch a.py",
                ts="2026-05-08T10:01:00+00:00",
                files=["a.py"],
                metadata={
                    "action": "commit_success",
                    "commit_hash": self.COMMIT_HASH,
                },
            ),
            make_event(
                event_schema.EVENT_TYPE_QUESTION,
                id=self.Q1_ID,
                content="should we retry on timeout?",
                ts="2026-05-08T10:02:00+00:00",
                priority=event_schema.PRIORITY_ASSUMED,
            ),
            make_event(
                event_schema.EVENT_TYPE_QUESTION,
                id=self.Q2_ID,
                content="should we add a metrics counter?",
                ts="2026-05-08T10:03:00+00:00",
                priority=event_schema.PRIORITY_ASSUMED,
            ),
        ]
        for i in range(3):
            events.append(
                make_event(
                    event_schema.EVENT_TYPE_STATUS,
                    id=f"5555555555{i:02x}",
                    content=f"working {i}",
                    ts=f"2026-05-08T10:04:{i:02d}+00:00",
                    working_on=["a.py"],
                )
            )
        # Post-commit concern + debt to exercise the probe-resolvable
        # filter in uncommitted_event_count. The 3 status events above
        # and 2 questions earlier are excluded as noise.
        events.append(
            make_event(
                event_schema.EVENT_TYPE_CONCERN,
                id="c55555555555",
                content="post-commit bug in b.py",
                ts="2026-05-08T10:05:00+00:00",
                files=["b.py"],
                severity="medium",
            )
        )
        events.append(
            make_event(
                event_schema.EVENT_TYPE_DEBT,
                id="c66666666666",
                content="post-commit cleanup in c.py",
                ts="2026-05-08T10:06:00+00:00",
                files=["c.py"],
            )
        )
        self._seed_events(events)

    def test_preload_surfaces_open_questions_and_maybe_addressed_concern(self):
        r = self._run_preload(_PRELOAD_SH)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(self.Q1_ID, r.stdout, "open question Q1 should surface")
        self.assertIn(self.Q2_ID, r.stdout, "open question Q2 should surface")
        # MAYBE_ADDRESSED renders concern ID at top-level with the
        # overlapping commit ID(s) indented beneath. The agent uses these
        # IDs to fetch full content from conversation history (solo
        # commits) or via Read on events.jsonl (teammate commits).
        self.assertRegex(r.stdout, re.compile(rf"^- {self.CONCERN_ID}\b", re.M))
        self.assertRegex(r.stdout, re.compile(rf"^  - {self.COMMIT_HASH}\b", re.M))
        # uncommitted_count = 1 concern + 1 debt = 2 (post-commit only;
        # questions and status events are noise classes excluded from
        # the probe-resolvable filter). End-of-line anchor so "2" matches
        # exactly, not a prefix of 23/200/etc.
        self.assertRegex(r.stdout, r"### UNCOMMITTED\s*\n2\b")

    def test_full_pipeline_simulating_llm_append_calls(self):
        # 1. Run preload — confirms the candidates are surfaced.
        preload = self._run_preload(_PRELOAD_SH)
        self.assertEqual(preload.returncode, 0, preload.stderr)
        self.assertIn(self.Q1_ID, preload.stdout)
        self.assertIn(self.Q2_ID, preload.stdout)
        self.assertIn(self.CONCERN_ID, preload.stdout)

        # 2. Simulate LLM Step 1 — append session_summary event.
        r = self._run_append(
            "--type",
            "session_summary",
            "--agent",
            "xp-end-session",
            "--content",
            "Shipped a.py auth fix; 2 questions open and 1 concern resolved by commit.",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # 3. Simulate LLM Step 2 (answer branch) — answer event for Q1.
        r = self._run_append(
            "--type",
            "answer",
            "--agent",
            "xp-end-session",
            "--references",
            json.dumps([self.Q1_ID]),
            "--content",
            "Yes, retry with exponential backoff capped at 3 attempts.",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # 4. Simulate LLM Step 2 (drop branch) — canonical CLI helper for Q2.
        r = self._run_smm_cli(
            "question",
            "close",
            "--won-fix",
            "--event-id",
            self.Q2_ID,
            "--rationale",
            "out of scope this iteration",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # 5. Simulate LLM Step 3 — auto-judge the maybe-addressed
        # concern as resolved by the git commit hash surfaced in
        # MAYBE_ADDRESSED. Audit trail records both the canonical
        # resolves link AND the git commit hash(es) that informed the
        # decision (resolvable downstream via `git show`).
        r = self._run_append(
            "--type",
            "status",
            "--agent",
            "xp-end-session",
            "--content",
            f"Resolved by {self.COMMIT_HASH}: a.py auth fix landed",
            "--working-on",
            "[]",
            "--metadata",
            json.dumps(
                {
                    "action": event_schema.STATUS_ACTION_END_SESSION_DROP,
                    event_schema.METADATA_KEY_RESOLVES: [self.CONCERN_ID],
                    event_schema.METADATA_KEY_RESOLVED_BY_COMMITS: [self.COMMIT_HASH],
                }
            ),
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # 6. Re-parse events.jsonl and assert final state.
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(skipped, 0, "no events should be skipped on re-parse")
        summaries = events_of_type(events, event_schema.EVENT_TYPE_SESSION_SUMMARY)
        self.assertEqual(len(summaries), 1, "exactly one session_summary event landed")
        # Pin authoring + non-empty content so a regression that wrote
        # an empty/wrongly-attributed summary doesn't pass silently.
        self.assertEqual(summaries[0]["agent_id"], "xp-end-session")
        self.assertGreater(len(summaries[0]["content"]), 0)

        resolutions = resolution.compute_resolutions(events)
        answered = resolutions["answered_question_ids"]
        self.assertIn(self.Q1_ID, answered, "Q1 should be resolved via answer event")
        self.assertIn(
            self.Q2_ID,
            answered,
            "Q2 should be resolved via question_close (metadata.resolves)",
        )
        self.assertIn(
            self.CONCERN_ID,
            resolutions["resolved_concern_ids"],
            "concern should be resolved via end_session_drop status event",
        )

        # 6b. Audit trail — the end_session_drop status event records
        # the commit ID that informed the auto-judge decision.
        statuses = events_of_type(events, event_schema.EVENT_TYPE_STATUS)
        drops = [
            s
            for s in statuses
            if event_schema.event_action(s)
            == event_schema.STATUS_ACTION_END_SESSION_DROP
        ]
        self.assertEqual(len(drops), 1, "exactly one end_session_drop landed")
        self.assertEqual(
            drops[0]["metadata"][event_schema.METADATA_KEY_RESOLVED_BY_COMMITS],
            [self.COMMIT_HASH],
            "audit trail must cite the git commit hash (not SMM event id) "
            "that informed the resolution — agents downstream `git show` it",
        )

        # 7. All new events validate cleanly via the schema.
        for event in events:
            errors = event_schema.validate_event(event)
            self.assertEqual(
                errors, [], f"event {event.get('id')} should validate clean: {errors}"
            )

    def test_pipeline_deferred_concern_resurfaces_in_next_draft(self):
        # Deferral contract: when the agent judges the cited commits
        # do NOT clearly fix a concern, it appends NO event. The next
        # session's preload must re-surface the concern in
        # MAYBE_ADDRESSED so the user/agent gets another shot at it.
        # Reframed from the reviewer's "skip step 5 = no-op" weakness:
        # this test calls draft_summary AGAIN after the deferral and
        # asserts re-surfacing — proves the contract holds across
        # session boundaries, not just that nothing changed.
        first = draft_summary.run(self.smm_dir)
        self.assertEqual(len(first["maybe_addressed"]), 1)
        self.assertEqual(first["maybe_addressed"][0]["id"], self.CONCERN_ID)

        # Agent decides to defer — appends nothing. Simulate by leaving
        # events.jsonl untouched.

        second = draft_summary.run(self.smm_dir)
        self.assertEqual(
            len(second["maybe_addressed"]),
            1,
            "deferred concern must re-surface on next draft",
        )
        self.assertEqual(second["maybe_addressed"][0]["id"], self.CONCERN_ID)
        self.assertEqual(second["maybe_addressed"][0]["commits"], [self.COMMIT_HASH])


if __name__ == "__main__":
    unittest.main()

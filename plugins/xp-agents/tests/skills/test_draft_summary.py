#!/usr/bin/env python3
"""Tests for plugins/xp-agents/skills/xp-end-session/scripts/draft_summary.py.

Story-002 of sprint-070: pure-stdlib helper that parses events.jsonl
from the prior session_end boundary forward and emits JSON
{summary, open_questions, maybe_addressed} for the SKILL.md to consume.
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

import draft_summary  # noqa: E402


class TestDraftSummary(_SMMTestCase):
    """Unit tests for draft_summary.run() against various seeded SMMs."""

    def test_empty_smm(self):
        self._write_events([])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(
            result,
            {
                "summary": "",
                "open_questions": [],
                "maybe_addressed": [],
                "uncommitted_count": 0,
                "carry_forward": [],
            },
        )

    def test_uncommitted_count_no_commits_returns_actionable_total(self):
        # When events.jsonl has no commit yet, every probe-resolvable event
        # (concern/debt/discovery) is counted. Status events are orchestration
        # noise and excluded — see _common.PROBE_RESOLVABLE_TYPES.
        events = [
            make_event(
                event_schema.EVENT_TYPE_STATUS,
                id=f"sta{i:09d}",
                content=f"working {i}",
                ts=f"2026-05-08T12:00:{i:02d}+00:00",
                working_on=["x.py"],
            )
            for i in range(3)
        ] + [
            make_event(
                event_schema.EVENT_TYPE_CONCERN,
                id="cnc000000001",
                content="bug in x.py",
                ts="2026-05-08T12:00:10+00:00",
                files=["x.py"],
                severity="medium",
            ),
            make_event(
                event_schema.EVENT_TYPE_DEBT,
                id="dbt000000001",
                content="cleanup x.py",
                ts="2026-05-08T12:00:11+00:00",
                files=["x.py"],
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        # 3 status (excluded) + 1 concern + 1 debt = 2 actionable
        self.assertEqual(result["uncommitted_count"], 2)

    def test_uncommitted_count_zero_when_last_event_is_commit(self):
        events = [
            make_event(
                event_schema.EVENT_TYPE_STATUS,
                id="sta000000001",
                content="working",
                ts="2026-05-08T13:00:00+00:00",
                working_on=["x.py"],
            ),
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="com000000001",
                content="feat: thing",
                ts="2026-05-08T13:01:00+00:00",
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["uncommitted_count"], 0)

    def test_uncommitted_count_excludes_trailing_session_summary(self):
        events = [
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="com000000003",
                content="feat: thing",
                ts="2026-05-10T19:00:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_SESSION_SUMMARY,
                id="ses000000001",
                content="Session wrap-up",
                ts="2026-05-10T19:01:00+00:00",
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["uncommitted_count"], 0)

    def test_uncommitted_count_excludes_orchestration_noise_among_real_work(self):
        # Decision and session_summary are orchestration events, not
        # probe-resolvable work. Only the post-commit concern counts.
        events = [
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="com000000004",
                content="feat: prior",
                ts="2026-05-10T19:00:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_DECISION,
                id="dec000000002",
                content="picked Y",
                ts="2026-05-10T19:01:00+00:00",
                topic="y-choice",
            ),
            make_event(
                event_schema.EVENT_TYPE_CONCERN,
                id="cnc000000002",
                content="post-commit bug in y.py",
                ts="2026-05-10T19:01:30+00:00",
                files=["y.py"],
                severity="medium",
            ),
            make_event(
                event_schema.EVENT_TYPE_SESSION_SUMMARY,
                id="ses000000002",
                content="Session wrap-up",
                ts="2026-05-10T19:02:00+00:00",
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        # 1 decision (excluded) + 1 concern + 1 session_summary (excluded) = 1
        self.assertEqual(result["uncommitted_count"], 1)

    def test_uncommitted_count_after_commit(self):
        # Only post-commit probe-resolvable events count. Status and decision
        # are orchestration noise — see _common.PROBE_RESOLVABLE_TYPES.
        events = [
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="com000000002",
                content="feat: thing",
                ts="2026-05-08T14:00:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_STATUS,
                id="sta000000002",
                content="post-commit work",
                ts="2026-05-08T14:01:00+00:00",
                working_on=["y.py"],
            ),
            make_event(
                event_schema.EVENT_TYPE_DECISION,
                id="dec000000001",
                content="picked X",
                ts="2026-05-08T14:02:00+00:00",
                topic="x-choice",
            ),
            make_event(
                event_schema.EVENT_TYPE_CONCERN,
                id="cnc000000003",
                content="post-commit regression",
                ts="2026-05-08T14:03:00+00:00",
                files=["y.py"],
                severity="medium",
            ),
            make_event(
                event_schema.EVENT_TYPE_DEBT,
                id="dbt000000002",
                content="cleanup y.py",
                ts="2026-05-08T14:04:00+00:00",
                files=["y.py"],
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        # 1 status + 1 decision (excluded) + 1 concern + 1 debt = 2 actionable
        self.assertEqual(result["uncommitted_count"], 2)

    def test_open_question_surfaces(self):
        # Open question, plus a resolved question (answer event resolves it).
        open_q = make_event(
            event_schema.EVENT_TYPE_QUESTION,
            id="aaaaaaaaaaaa",
            content="open?",
            ts="2026-05-08T01:00:00+00:00",
            priority=event_schema.PRIORITY_ASSUMED,
        )
        resolved_q = make_event(
            event_schema.EVENT_TYPE_QUESTION,
            id="bbbbbbbbbbbb",
            content="resolved?",
            ts="2026-05-08T01:01:00+00:00",
            priority=event_schema.PRIORITY_ASSUMED,
        )
        answer = make_event(
            event_schema.EVENT_TYPE_ANSWER,
            id="cccccccccccc",
            content="yes",
            ts="2026-05-08T01:02:00+00:00",
            references=["bbbbbbbbbbbb"],
        )
        self._write_events([open_q, resolved_q, answer])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["open_questions"], ["aaaaaaaaaaaa"])

    def test_session_boundary_filter(self):
        old_q = make_event(
            event_schema.EVENT_TYPE_QUESTION,
            id="444444444444",
            content="from prior session?",
            ts="2026-05-07T01:00:00+00:00",
            priority=event_schema.PRIORITY_ASSUMED,
        )
        boundary = make_event(
            event_schema.EVENT_TYPE_SESSION_END,
            id="555555555555",
            content="session ended",
            ts="2026-05-07T23:59:00+00:00",
        )
        new_q = make_event(
            event_schema.EVENT_TYPE_QUESTION,
            id="666666666666",
            content="from current session?",
            ts="2026-05-08T05:00:00+00:00",
            priority=event_schema.PRIORITY_ASSUMED,
        )
        self._write_events([old_q, boundary, new_q])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["open_questions"], ["666666666666"])

    def test_no_prior_session_end_uses_whole_log(self):
        only_q = make_event(
            event_schema.EVENT_TYPE_QUESTION,
            id="777777777777",
            content="only event?",
            ts="2026-05-08T06:00:00+00:00",
            priority=event_schema.PRIORITY_ASSUMED,
        )
        self._write_events([only_q])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["open_questions"], ["777777777777"])

    def _seed_long_unbounded_log(self) -> str:
        # 500 stale commits + 1 recent question, no SESSION_END marker.
        # Returns the recent question's id for assertions.
        recent_q_id = "ddd000000001"
        events = [
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id=f"old{i:09d}",
                content=f"old commit {i}",
                ts=f"2026-04-{(i % 28) + 1:02d}T00:00:00+00:00",
            )
            for i in range(500)
        ]
        events.append(
            make_event(
                event_schema.EVENT_TYPE_QUESTION,
                id=recent_q_id,
                content="recent open?",
                ts="2026-05-08T10:00:00+00:00",
                priority=event_schema.PRIORITY_ASSUMED,
            )
        )
        self._write_events(events)
        return recent_q_id

    def test_no_prior_session_end_caps_summary_to_recent_window(self):
        # Backfill / corruption-recovery scenario: cap surfaces the recent
        # tail of the log in the summary instead of the oldest events.
        self._seed_long_unbounded_log()
        result = draft_summary.run(self.smm_dir)
        self.assertIn(
            "[commit] old commit 499",
            result["summary"],
            "expected last commit in cap window; got tail: "
            f"{result['summary'][-200:]!r}",
        )

    def test_no_prior_session_end_preserves_recent_open_questions(self):
        # Same scenario as above, asserting the cap doesn't drop the
        # most recent open question even when buried after 500 commits.
        recent_q_id = self._seed_long_unbounded_log()
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["open_questions"], [recent_q_id])

    def test_summary_prefers_refined_session_summary_event(self):
        events = [
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="ccc000000001",
                content="feat: thing",
                ts="2026-05-10T20:00:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_DECISION,
                id="ddd000000001",
                content="picked X over Y",
                ts="2026-05-10T20:01:00+00:00",
                topic="x-vs-y",
            ),
            make_event(
                event_schema.EVENT_TYPE_SESSION_SUMMARY,
                id="ses000000010",
                content="Refined narrative authored by the agent in Step 1.",
                ts="2026-05-10T20:02:00+00:00",
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(
            result["summary"],
            "Refined narrative authored by the agent in Step 1.",
        )
        # Confirms the synthesized [commit]/[decision] dump is NOT used
        # when a refined session_summary exists.
        self.assertNotIn("[commit]", result["summary"])
        self.assertNotIn("[decision]", result["summary"])

    def test_summary_uses_latest_session_summary_when_multiple(self):
        events = [
            make_event(
                event_schema.EVENT_TYPE_SESSION_SUMMARY,
                id="ses000000020",
                content="First end-session summary.",
                ts="2026-05-10T21:00:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="ccc000000002",
                content="fix: thing",
                ts="2026-05-10T21:01:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_SESSION_SUMMARY,
                id="ses000000021",
                content="Second end-session summary.",
                ts="2026-05-10T21:02:00+00:00",
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["summary"], "Second end-session summary.")

    def test_summary_includes_commit_decision_concern_debt_status(self):
        events = [
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="888888888888",
                content="feat: thing",
                ts="2026-05-08T07:00:00+00:00",
            ),
            make_event(
                event_schema.EVENT_TYPE_DECISION,
                id="999999999999",
                content="chose X over Y",
                ts="2026-05-08T07:01:00+00:00",
                topic="x-vs-y",
            ),
            make_event(
                event_schema.EVENT_TYPE_CONCERN,
                id="aaabbbcccddd",
                content="possible regression",
                ts="2026-05-08T07:02:00+00:00",
                severity="medium",
            ),
            make_event(
                event_schema.EVENT_TYPE_DEBT,
                id="aaabbbcccdde",
                content="cleanup later",
                ts="2026-05-08T07:03:00+00:00",
                files=["x.py"],
            ),
            make_event(
                event_schema.EVENT_TYPE_STATUS,
                id="aaabbbcccddf",
                content="working on x",
                ts="2026-05-08T07:04:00+00:00",
                working_on=["x.py"],
            ),
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        for marker in ("[commit]", "[decision]", "[concern]", "[debt]", "[status]"):
            self.assertIn(marker, result["summary"])

    def test_summary_trimmed_to_budget(self):
        budget = event_schema.get_required_budget(
            event_schema.EVENT_TYPE_SESSION_SUMMARY
        )
        # Each commit content ~150 chars; need >> budget total.
        large_content = "x" * 150
        events = [
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id=f"cccccccccc{i:02d}",
                content=large_content,
                ts=f"2026-05-08T08:00:{i:02d}+00:00",
            )
            for i in range(40)
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        self.assertLessEqual(len(result["summary"]), budget)
        # Tail-preserving trim: ellipsis goes at the head; the most
        # recent event line survives at the tail.
        self.assertTrue(
            result["summary"].startswith("..."),
            f"expected leading ellipsis, got head: {result['summary'][:40]!r}",
        )
        self.assertIn(
            f"[commit] {'x' * 150}",
            result["summary"].splitlines()[-1],
            "expected the last seeded commit to survive the trim",
        )

    def test_summary_trim_respects_budget_with_giant_single_line(self):
        # COMMIT has no content budget (event_schema CONTENT_BUDGETS
        # entry is None) so a single commit content can exceed the
        # 2000-char SESSION_SUMMARY budget. The trim must not overshoot.
        budget = event_schema.get_required_budget(
            event_schema.EVENT_TYPE_SESSION_SUMMARY
        )
        events = [
            make_event(
                event_schema.EVENT_TYPE_COMMIT,
                id="giant0000001",
                content="y" * (budget * 3),
                ts="2026-05-08T11:00:00+00:00",
            )
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        self.assertLessEqual(
            len(result["summary"]),
            budget,
            f"summary len {len(result['summary'])} > budget {budget}",
        )

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

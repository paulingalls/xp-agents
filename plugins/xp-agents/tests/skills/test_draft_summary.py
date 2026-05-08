#!/usr/bin/env python3
"""Tests for plugins/xp-agents/skills/xp-end-session/scripts/draft_summary.py.

Story-002 of sprint-070: pure-stdlib helper that parses events.jsonl
from the prior session_end boundary forward and emits JSON
{summary, open_questions, likely_addressed} for the SKILL.md to consume.
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
                "likely_addressed": [],
                "uncommitted_count": 0,
                "carry_forward": [],
            },
        )

    def test_uncommitted_count_no_commits_returns_total(self):
        events = [
            make_event(
                event_schema.EVENT_TYPE_STATUS,
                id=f"sta{i:09d}",
                content=f"working {i}",
                ts=f"2026-05-08T12:00:{i:02d}+00:00",
                working_on=["x.py"],
            )
            for i in range(5)
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["uncommitted_count"], 5)

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

    def test_uncommitted_count_after_commit(self):
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
        ]
        self._write_events(events)
        result = draft_summary.run(self.smm_dir)
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

    def test_concern_with_file_overlap_surfaces(self):
        concern = make_event(
            event_schema.EVENT_TYPE_CONCERN,
            id="dddddddddddd",
            content="auth bug",
            files=["a.py"],
            ts="2026-05-08T02:00:00+00:00",
            severity="medium",
        )
        commit = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="eeeeeeeeeeee",
            content="fix(auth): patch a.py",
            files=["a.py"],
            ts="2026-05-08T02:01:00+00:00",
        )
        self._write_events([concern, commit])
        result = draft_summary.run(self.smm_dir)
        # likely_addressed is list[{id, commits: list[str]}] — agent uses the
        # commit IDs to fetch full content (conversation history for solo
        # commits, Read on events.jsonl for teammate commits).
        self.assertEqual(len(result["likely_addressed"]), 1)
        self.assertEqual(result["likely_addressed"][0]["id"], "dddddddddddd")
        self.assertEqual(result["likely_addressed"][0]["commits"], ["eeeeeeeeeeee"])

    def test_concern_without_file_overlap_excluded(self):
        concern = make_event(
            event_schema.EVENT_TYPE_CONCERN,
            id="ffffffffffff",
            content="bug in a.py",
            files=["a.py"],
            ts="2026-05-08T03:00:00+00:00",
            severity="medium",
        )
        commit = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="111111111111",
            content="fix(other): touch b.py",
            files=["b.py"],
            ts="2026-05-08T03:01:00+00:00",
        )
        self._write_events([concern, commit])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(result["likely_addressed"], [])

    def test_debt_likely_addressed(self):
        debt = make_event(
            event_schema.EVENT_TYPE_DEBT,
            id="222222222222",
            content="unused fn in c.py",
            files=["c.py"],
            ts="2026-05-08T04:00:00+00:00",
        )
        commit = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="333333333333",
            content="chore: drop unused",
            files=["c.py"],
            ts="2026-05-08T04:01:00+00:00",
        )
        self._write_events([debt, commit])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(len(result["likely_addressed"]), 1)
        self.assertEqual(result["likely_addressed"][0]["id"], "222222222222")
        self.assertEqual(result["likely_addressed"][0]["commits"], ["333333333333"])

    def test_likely_addressed_carries_multiple_commit_ids_for_audit(self):
        # Two commits both touching the concern's file → both IDs land in
        # the audit-trail list, in chronological order. This is the trail
        # the agent passes through to metadata.resolved_by_commits when
        # auto-resolving.
        concern = make_event(
            event_schema.EVENT_TYPE_CONCERN,
            id="audit0000001",
            content="needs two patches",
            files=["m.py"],
            ts="2026-05-08T05:00:00+00:00",
            severity="medium",
        )
        commit1 = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="audit0000002",
            content="fix(m): part 1",
            files=["m.py"],
            ts="2026-05-08T05:01:00+00:00",
        )
        commit2 = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="audit0000003",
            content="fix(m): part 2",
            files=["m.py"],
            ts="2026-05-08T05:02:00+00:00",
        )
        self._write_events([concern, commit1, commit2])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(len(result["likely_addressed"]), 1)
        item = result["likely_addressed"][0]
        self.assertEqual(item["id"], "audit0000001")
        self.assertEqual(item["commits"], ["audit0000002", "audit0000003"])

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
                "likely_addressed",
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

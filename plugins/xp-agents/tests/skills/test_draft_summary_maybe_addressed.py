#!/usr/bin/env python3
"""Tests for draft_summary's maybe_addressed surfacing path.

Split from test_draft_summary.py at the commit that pushed it past
the 500-line target. Covers the concern/debt → file_overlap → commit
→ maybe_addressed pipeline plus commit-hash audit-trail handling.
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


class TestDraftSummaryMaybeAddressed(_SMMTestCase):
    """concern/debt overlap with later commits surfaces in maybe_addressed."""

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
            metadata={
                "action": "commit_success",
                "commit_hash": "abc1230000000000000000000000000000000001",
            },
        )
        self._write_events([concern, commit])
        result = draft_summary.run(self.smm_dir)
        # maybe_addressed is list[{id, commits: list[str]}] — agent uses the
        # git commit hash to fetch full content via `git show`.
        self.assertEqual(len(result["maybe_addressed"]), 1)
        self.assertEqual(result["maybe_addressed"][0]["id"], "dddddddddddd")
        self.assertEqual(
            result["maybe_addressed"][0]["commits"],
            ["abc1230000000000000000000000000000000001"],
        )

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
        self.assertEqual(result["maybe_addressed"], [])

    def test_debt_maybe_addressed(self):
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
            metadata={
                "action": "commit_success",
                "commit_hash": "abc1230000000000000000000000000000000003",
            },
        )
        self._write_events([debt, commit])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(len(result["maybe_addressed"]), 1)
        self.assertEqual(result["maybe_addressed"][0]["id"], "222222222222")
        self.assertEqual(
            result["maybe_addressed"][0]["commits"],
            ["abc1230000000000000000000000000000000003"],
        )

    def test_maybe_addressed_filters_commits_missing_commit_hash(self):
        # Honesty: a commit event without metadata.commit_hash is malformed
        # (post-commit hook always sets it for valid commits). Filter such
        # events from `commits[]` rather than falling back to the SMM
        # event id — the event id is NOT a git ref, and downstream
        # `git show` would silently fail. Empty commits[] (no overlap
        # surfaces maybe_addressed at all) is honest; wrong refs are not.
        concern = make_event(
            event_schema.EVENT_TYPE_CONCERN,
            id="filtertst001",
            content="needs patch",
            files=["h.py"],
            ts="2026-05-08T07:00:00+00:00",
            severity="medium",
        )
        # Commit event with NO metadata.commit_hash (malformed).
        commit_bad = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="filtertst002",
            content="fix(h): patch",
            files=["h.py"],
            ts="2026-05-08T07:01:00+00:00",
        )
        # Commit event WITH metadata.commit_hash (canonical).
        commit_good = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="filtertst003",
            content="fix(h): also patch",
            files=["h.py"],
            ts="2026-05-08T07:02:00+00:00",
            metadata={
                "action": "commit_success",
                "commit_hash": "def4560000000000000000000000000000000007",
            },
        )
        self._write_events([concern, commit_bad, commit_good])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(len(result["maybe_addressed"]), 1)
        self.assertEqual(
            result["maybe_addressed"][0]["commits"],
            ["def4560000000000000000000000000000000007"],
            "commits[] must skip events missing metadata.commit_hash, "
            "not fall back to the (non-git-ref) SMM event id",
        )

    def test_maybe_addressed_emits_git_commit_hash_not_event_id(self):
        # The `commits` field is consumed as a git ref (agents `git show`
        # it to fetch full commit content). The SMM commit-event ID is
        # NOT a git ref — the real git SHA lives in metadata.commit_hash
        # (recorded by the post-commit hook). Regression: prior bug
        # emitted the event ID, which `git show` correctly rejected.
        concern = make_event(
            event_schema.EVENT_TYPE_CONCERN,
            id="hashtest0001",
            content="needs patch",
            files=["g.py"],
            ts="2026-05-08T06:00:00+00:00",
            severity="medium",
        )
        commit = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="hashtest0002",  # SMM event ID — must NOT appear in commits[]
            content="fix(g): patch g.py",
            files=["g.py"],
            ts="2026-05-08T06:01:00+00:00",
            metadata={
                "action": "commit_success",
                "commit_hash": "ae995e32f8ec7a299c517a69773e94803b791a87",
            },
        )
        self._write_events([concern, commit])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(len(result["maybe_addressed"]), 1)
        self.assertEqual(
            result["maybe_addressed"][0]["commits"],
            ["ae995e32f8ec7a299c517a69773e94803b791a87"],
            "commits[] must carry git commit_hash (resolvable by `git show`),"
            " not the SMM commit-event ID",
        )

    def test_maybe_addressed_carries_multiple_commit_ids_for_audit(self):
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
            metadata={
                "action": "commit_success",
                "commit_hash": "abc1230000000000000000000000000000000005",
            },
        )
        commit2 = make_event(
            event_schema.EVENT_TYPE_COMMIT,
            id="audit0000003",
            content="fix(m): part 2",
            files=["m.py"],
            ts="2026-05-08T05:02:00+00:00",
            metadata={
                "action": "commit_success",
                "commit_hash": "abc1230000000000000000000000000000000006",
            },
        )
        self._write_events([concern, commit1, commit2])
        result = draft_summary.run(self.smm_dir)
        self.assertEqual(len(result["maybe_addressed"]), 1)
        item = result["maybe_addressed"][0]
        self.assertEqual(item["id"], "audit0000001")
        self.assertEqual(
            item["commits"],
            [
                "abc1230000000000000000000000000000000005",
                "abc1230000000000000000000000000000000006",
            ],
        )


if __name__ == "__main__":
    unittest.main()

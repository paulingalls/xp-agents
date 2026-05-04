#!/usr/bin/env python3
"""Tests for resolves_probe.py — pure probe-candidate extraction module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import unittest

import _common
import event_schema
import resolves_probe
import worktree
from conftest import _HookTestCase, _ProbeTestHelpers, make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_STATUS,
    METADATA_KEY_PROBE_CANDIDATES,
    METADATA_KEY_PROBE_SELECTION_REASONS,
    SELECTION_REASON_CLOSE_MODE,
    SELECTION_REASON_FILE_OVERLAP,
    SELECTION_REASON_IN_SPRINT_BATCH,
    SELECTION_REASON_KEYWORD,
    SELECTION_REASON_RECENCY,
    STATUS_CONTENT_RESOLVES_PROBE,
)


class TestFindProbeCandidates(_HookTestCase):
    """find_probe_candidates returns open concerns matching commit files."""

    def _seed_concern(self, content: str, files: list[str]) -> str:
        concern = make_event(EVENT_TYPE_CONCERN, content=content, files=files)
        _common.append_safe(self.smm_dir, concern)
        return concern["id"]

    def test_empty_commit_files_returns_empty(self):
        self._seed_concern("Auth leaks", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir, [], [], cwd=str(self.smm_dir)
        )
        self.assertEqual(result, [])

    def test_no_matching_concerns_returns_empty(self):
        self._seed_concern("Other bug", ["scripts/foo.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir, ["README.md"], [], cwd=str(self.smm_dir)
        )
        self.assertEqual(result, [])

    def test_caps_at_five_candidates(self):
        cids = [
            self._seed_concern(f"Concern {i}", ["scripts/auth.py"]) for i in range(7)
        ]
        result = resolves_probe.find_probe_candidates(
            self.smm_dir, ["scripts/auth.py"], [], cwd=str(self.smm_dir)
        )
        self.assertEqual(len(result), 5)
        self.assertEqual([c["id"] for c in result], cids[:5])

    def test_filters_already_resolved_via_resolves_arg(self):
        cid_skip = self._seed_concern("Skip me", ["scripts/auth.py"])
        cid_keep = self._seed_concern("Keep me", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir, ["scripts/auth.py"], [cid_skip], cwd=str(self.smm_dir)
        )
        ids = [c["id"] for c in result]
        self.assertIn(cid_keep, ids)
        self.assertNotIn(cid_skip, ids)

    def test_attaches_selection_reasons(self):
        self._seed_concern("Auth middleware leaks tokens", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            commit_message="fix auth",
        )
        self.assertEqual(len(result), 1)
        cand = result[0]
        self.assertIn("selection_reasons", cand)
        self.assertIsInstance(cand["selection_reasons"], list)
        self.assertIn(SELECTION_REASON_FILE_OVERLAP, cand["selection_reasons"])
        self.assertIn(SELECTION_REASON_KEYWORD, cand["selection_reasons"])


class TestBuildNudgeLines(unittest.TestCase):
    """build_nudge_lines formats grouped nudge with header and trailer."""

    def test_empty_candidates_returns_empty_list(self):
        self.assertEqual(resolves_probe.build_nudge_lines([]), [])

    def test_single_candidate_has_header_item_and_trailer(self):
        candidate = {"id": "abc123def456", "content": "Auth middleware leaks tokens"}
        lines = resolves_probe.build_nudge_lines([candidate])
        self.assertEqual(len(lines), 1)
        block = lines[0]
        self.assertIn("Pick which your commit closes", block)
        self.assertIn("abc123def456", block)
        self.assertIn("Auth middleware leaks tokens", block)
        self.assertIn("Resolves-Event: abc123def456", block)

    def test_multiple_candidates_grouped_with_combined_trailer(self):
        candidates = [
            {"id": "abc123def456", "type": EVENT_TYPE_CONCERN, "content": "Auth leak"},
            {"id": "def456abc123", "type": EVENT_TYPE_DEBT, "content": "Refactor auth"},
        ]
        lines = resolves_probe.build_nudge_lines(candidates)
        self.assertEqual(len(lines), 1)
        block = lines[0]
        self.assertIn("[concern", block)
        self.assertIn("[debt", block)
        self.assertIn("Resolves-Event: abc123def456, def456abc123", block)

    def test_truncated_content_has_ellipsis(self):
        long_content = "x" * 200
        candidate = {"id": "abc", "content": long_content}
        lines = resolves_probe.build_nudge_lines([candidate])
        self.assertIn("x" * 80 + "...", lines[0])

    def test_handles_missing_content(self):
        candidate = {"id": "abc", "content": None}
        lines = resolves_probe.build_nudge_lines([candidate])
        self.assertEqual(len(lines), 1)
        self.assertIn("abc", lines[0])

    def test_shows_event_type(self):
        candidate = {
            "id": "abc123def456",
            "type": EVENT_TYPE_DEBT,
            "content": "Legacy code",
        }
        lines = resolves_probe.build_nudge_lines([candidate])
        self.assertIn("[debt", lines[0])

    def test_header_offers_explicit_none_escape(self):
        candidate = {"id": "abc", "content": "x"}
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("Resolves-Event: none", block)
        self.assertIn("if none apply", block)

    def test_concern_severity_inline_with_id(self):
        candidate = {
            "id": "abc123def456",
            "type": EVENT_TYPE_CONCERN,
            "severity": "high",
            "content": "Auth leak",
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("[concern|high|abc123def456]", block)

    def test_concern_without_severity_falls_back(self):
        candidate = {"id": "abc123def456", "type": EVENT_TYPE_CONCERN, "content": "x"}
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("[concern|unknown|abc123def456]", block)

    def test_close_reviewer_provenance_suffix_includes_mode(self):
        candidate = {
            "id": "abc123def456",
            "type": EVENT_TYPE_CONCERN,
            "severity": "medium",
            "content": "Cross-cutting drift",
            "metadata": {"close_mode": "sprint"},
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("(from sprint-close-reviewer)", block)

    def test_close_reviewer_provenance_suffix_for_plan_mode(self):
        candidate = {
            "id": "abc123def456",
            "type": EVENT_TYPE_CONCERN,
            "severity": "medium",
            "content": "Architectural concern",
            "metadata": {"close_mode": "plan"},
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("(from plan-close-reviewer)", block)

    def test_no_provenance_suffix_without_close_mode(self):
        candidate = {
            "id": "abc123def456",
            "type": EVENT_TYPE_CONCERN,
            "severity": "medium",
            "content": "Plain concern",
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertNotIn("close-reviewer", block)


class _ScoringHelpers:
    """Shared candidate-builder + score caller for TestScoreCandidate and
    TestSelectionReasons. Mixin (no TestCase base) so subclasses don't
    re-run each other's tests via inheritance."""

    NOW = "2026-04-29T00:00:00+00:00"
    RECENT_TS = "2026-04-25T00:00:00+00:00"  # 4 days ago — within 5-day window
    EDGE_TS = "2026-04-23T00:00:00+00:00"  # 6 days ago — outside 5-day window
    OLD_TS = "2026-04-01T00:00:00+00:00"  # 28 days ago — outside window

    def _candidate(self, **kwargs) -> dict:
        base = {
            "id": "abc123def456",
            "type": EVENT_TYPE_CONCERN,
            "content": "Auth middleware leaks tokens",
            "files": ["scripts/auth.py"],
            "ts": self.OLD_TS,
            "metadata": {},
        }
        base.update(kwargs)
        return base

    def _score(
        self,
        candidate,
        *,
        commit_message="",
        commit_files=None,
        now_ts=None,
        active_cycle_id=None,
    ):
        """Convenience: compute haystack/file_set as find_probe_candidates does.

        Mirrors the production code path: commit_file_set is built via
        worktree.normalize_path so candidate files (also normalized inside
        _score_candidate) intersect on the same key shape regardless of
        whether the source path was absolute, relative, or `./`-prefixed.
        Returns the int score only — call `_score_with_reasons` when the
        reasons list is needed.
        """
        score, _ = self._score_with_reasons(
            candidate,
            commit_message=commit_message,
            commit_files=commit_files,
            now_ts=now_ts,
            active_cycle_id=active_cycle_id,
        )
        return score

    def _score_with_reasons(
        self,
        candidate,
        *,
        commit_message="",
        commit_files=None,
        now_ts=None,
        active_cycle_id=None,
    ):
        commit_files = commit_files or []
        haystack_parts = [commit_message] + [Path(f).name for f in commit_files]
        haystack_keywords = resolves_probe._extract_keywords(" ".join(haystack_parts))
        cwd = "/"
        commit_file_set = {worktree.normalize_path(f, cwd) for f in commit_files}
        return resolves_probe._score_candidate(
            candidate,
            haystack_keywords,
            commit_file_set,
            cwd,
            now_ts or self.NOW,
            active_cycle_id=active_cycle_id,
        )


class TestScoreCandidate(_ScoringHelpers, unittest.TestCase):
    """_score_candidate ranks candidates by keyword + file + recency + provenance."""

    def test_keyword_match_in_commit_message_adds_two(self):
        cand = self._candidate(content="Auth middleware leaks tokens", files=[])
        score_with = self._score(cand, commit_message="fix auth bug")
        score_without = self._score(cand, commit_message="fix typo")
        self.assertEqual(score_with - score_without, 2)

    def test_keyword_match_in_file_basename_adds_two(self):
        cand = self._candidate(content="Auth leak", files=[])
        score = self._score(cand, commit_files=["scripts/auth.py"])
        # +2 keyword (auth in basename) + 0 file overlap (cand has no files)
        self.assertGreaterEqual(score, 2)

    def test_keyword_score_capped_at_five_matches(self):
        # 10 keywords all match → score capped at 5*multiplier. Default ts is
        # OLD_TS so multiplier=2 (no recency boost) → cap = 5*2 = 10.
        cand = self._candidate(
            content="alpha bravo charlie delta echo foxtrot golf hotel india juliet",
            files=[],
        )
        score = self._score(
            cand,
            commit_message=(
                "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
            ),
        )
        self.assertLessEqual(score, 10)

    def test_recency_boost_when_within_five_days(self):
        recent = self._candidate(ts=self.RECENT_TS, content="zzz", files=[])
        old = self._candidate(ts=self.OLD_TS, content="zzz", files=[])
        self.assertEqual(self._score(recent) - self._score(old), 1)

    def test_no_recency_boost_at_six_days(self):
        edge = self._candidate(ts=self.EDGE_TS, content="zzz", files=[])
        old = self._candidate(ts=self.OLD_TS, content="zzz", files=[])
        self.assertEqual(self._score(edge) - self._score(old), 0)

    def test_keyword_score_boosted_for_recent_concerns(self):
        """Fresh concerns matching commit keywords get a per-match multiplier
        bump (2→3) on top of the +1 recency reason. Old concerns with the
        same content get only the base 2x. Difference: keyword_count + 1."""
        recent = self._candidate(
            ts=self.RECENT_TS, content="auth middleware leaks tokens", files=[]
        )
        old = self._candidate(
            ts=self.OLD_TS, content="auth middleware leaks tokens", files=[]
        )
        # 4 >=3-char non-stopword tokens overlap (auth, middleware, leaks,
        # tokens). recent gets 4*3=12, old 4*2=8. Plus +1 recency on recent.
        # Total diff = 4 + 1 = 5.
        msg = "fix auth middleware leaks tokens"
        self.assertEqual(
            self._score(recent, commit_message=msg)
            - self._score(old, commit_message=msg),
            5,
        )

    def test_close_reviewer_provenance_boost(self):
        with_close = self._candidate(
            metadata={"close_mode": "sprint"}, content="zzz", files=[]
        )
        without = self._candidate(metadata={}, content="zzz", files=[])
        self.assertEqual(self._score(with_close) - self._score(without), 1)

    def test_file_overlap_baseline_one_per_file(self):
        cand = self._candidate(
            content="zzz", files=["scripts/auth.py", "scripts/foo.py"]
        )
        s_two = self._score(cand, commit_files=["scripts/auth.py", "scripts/foo.py"])
        s_one = self._score(cand, commit_files=["scripts/auth.py"])
        self.assertEqual(s_two - s_one, 1)

    def test_file_overlap_uses_worktree_normalize_path(self):
        """Both candidate.files and commit_file_set are routed through
        worktree.normalize_path so abs/rel/`./`-prefixed forms intersect
        on the git-root-relative key (matches commits.open_issues_matching
        _commit's intersection semantics). Pinned via patch so the test
        asserts the contract without needing a real git repo."""
        from unittest.mock import patch as patch_

        cand = self._candidate(content="zzz", files=["/abs/repo/scripts/auth.py"])
        baseline = self._score(self._candidate(content="zzz", files=[]))

        # Stub normalize_path to map both forms to the same git-relative key,
        # reproducing what the production path delivers inside a real repo.
        def _stub(path, _cwd):
            return path.split("/abs/repo/", 1)[-1].lstrip("/")

        with patch_("worktree.normalize_path", side_effect=_stub):
            score = self._score(cand, commit_files=["scripts/auth.py"])
        # +1 for file overlap on top of baseline.
        self.assertEqual(score - baseline, 1)

    def test_stopwords_do_not_score(self):
        cand = self._candidate(content="the and with for that", files=[])
        score = self._score(cand, commit_message="the and with for that")
        self.assertEqual(score, 0)


class TestSelectionReasons(_ScoringHelpers, unittest.TestCase):
    """_score_candidate also returns the list of signals that contributed."""

    def test_keyword_match_emits_keyword_reason(self):
        cand = self._candidate(content="Auth middleware leaks tokens", files=[])
        _, reasons = self._score_with_reasons(cand, commit_message="fix auth bug")
        self.assertIn(SELECTION_REASON_KEYWORD, reasons)

    def test_file_overlap_emits_file_overlap_reason(self):
        cand = self._candidate(content="zzz", files=["scripts/auth.py"])
        _, reasons = self._score_with_reasons(cand, commit_files=["scripts/auth.py"])
        self.assertIn(SELECTION_REASON_FILE_OVERLAP, reasons)

    def test_recency_emits_recency_reason(self):
        cand = self._candidate(ts=self.RECENT_TS, content="zzz", files=[])
        _, reasons = self._score_with_reasons(cand)
        self.assertIn(SELECTION_REASON_RECENCY, reasons)
        old = self._candidate(ts=self.OLD_TS, content="zzz", files=[])
        _, old_reasons = self._score_with_reasons(old)
        self.assertNotIn(SELECTION_REASON_RECENCY, old_reasons)

    def test_close_mode_emits_close_mode_reason(self):
        cand = self._candidate(
            metadata={"close_mode": "sprint"}, content="zzz", files=[]
        )
        _, reasons = self._score_with_reasons(cand)
        self.assertIn(SELECTION_REASON_CLOSE_MODE, reasons)
        without = self._candidate(metadata={}, content="zzz", files=[])
        _, no_reasons = self._score_with_reasons(without)
        self.assertNotIn(SELECTION_REASON_CLOSE_MODE, no_reasons)

    def test_zero_score_emits_no_reasons(self):
        cand = self._candidate(content="zzz unrelated", files=[], metadata={})
        score, reasons = self._score_with_reasons(cand, commit_message="totally other")
        self.assertEqual(score, 0)
        self.assertEqual(reasons, [])

    def test_reasons_are_deterministic_order(self):
        cand = self._candidate(
            content="auth middleware leaks tokens",
            files=["scripts/auth.py"],
            ts=self.RECENT_TS,
            metadata={"close_mode": "sprint", "close_cycle_id": "abc123def456"},
        )
        _, reasons = self._score_with_reasons(
            cand,
            commit_message="fix auth bug",
            commit_files=["scripts/auth.py"],
            active_cycle_id="abc123def456",
        )
        self.assertEqual(
            reasons,
            [
                SELECTION_REASON_KEYWORD,
                SELECTION_REASON_FILE_OVERLAP,
                SELECTION_REASON_RECENCY,
                SELECTION_REASON_CLOSE_MODE,
                SELECTION_REASON_IN_SPRINT_BATCH,
            ],
        )


class TestInSprintBatchAxis(_ScoringHelpers, unittest.TestCase):
    """5th axis: candidates from the active close-reviewer cycle score even
    without keyword/file/recency overlap. Closes the probe-divert gap where
    in-batch siblings were missed because they had no other tie to the
    current commit."""

    CYCLE = "abc123def456"

    def test_matching_close_cycle_id_adds_one(self):
        cand = self._candidate(
            content="zzz", files=[], metadata={"close_cycle_id": self.CYCLE}
        )
        in_batch = self._score(cand, active_cycle_id=self.CYCLE)
        out_of_batch = self._score(cand, active_cycle_id="otherrrr01234")
        self.assertEqual(in_batch - out_of_batch, 1)

    def test_matching_close_cycle_id_emits_reason(self):
        cand = self._candidate(
            content="zzz", files=[], metadata={"close_cycle_id": self.CYCLE}
        )
        _, reasons = self._score_with_reasons(cand, active_cycle_id=self.CYCLE)
        self.assertIn(SELECTION_REASON_IN_SPRINT_BATCH, reasons)

    def test_different_close_cycle_id_does_not_fire(self):
        cand = self._candidate(
            content="zzz", files=[], metadata={"close_cycle_id": "different01234"}
        )
        score, reasons = self._score_with_reasons(cand, active_cycle_id=self.CYCLE)
        self.assertEqual(score, 0)
        self.assertNotIn(SELECTION_REASON_IN_SPRINT_BATCH, reasons)

    def test_no_active_cycle_does_not_fire(self):
        cand = self._candidate(
            content="zzz", files=[], metadata={"close_cycle_id": self.CYCLE}
        )
        score, reasons = self._score_with_reasons(cand, active_cycle_id=None)
        self.assertEqual(score, 0)
        self.assertNotIn(SELECTION_REASON_IN_SPRINT_BATCH, reasons)

    def test_candidate_without_close_cycle_id_does_not_fire(self):
        cand = self._candidate(content="zzz", files=[], metadata={})
        score, reasons = self._score_with_reasons(cand, active_cycle_id=self.CYCLE)
        self.assertEqual(score, 0)
        self.assertNotIn(SELECTION_REASON_IN_SPRINT_BATCH, reasons)

    def test_axis_is_additive_with_existing_axes(self):
        """In-cycle candidate that ALSO matches keyword/file/recency keeps
        every existing axis contribution and adds +1 for the new one."""
        cand = self._candidate(
            content="auth middleware leaks tokens",
            files=["scripts/auth.py"],
            ts=self.RECENT_TS,
            metadata={"close_mode": "sprint", "close_cycle_id": self.CYCLE},
        )
        with_axis = self._score(
            cand,
            commit_message="fix auth bug",
            commit_files=["scripts/auth.py"],
            active_cycle_id=self.CYCLE,
        )
        without_axis = self._score(
            cand,
            commit_message="fix auth bug",
            commit_files=["scripts/auth.py"],
            active_cycle_id=None,
        )
        self.assertEqual(with_axis - without_axis, 1)


class TestFindActiveCycleId(unittest.TestCase):
    """_find_active_cycle_id picks the most-recent recent concern's
    close_cycle_id from events.jsonl context."""

    NOW = "2026-04-29T00:00:00+00:00"
    RECENT = "2026-04-27T00:00:00+00:00"
    OLDER_RECENT = "2026-04-25T00:00:00+00:00"
    STALE = "2026-04-01T00:00:00+00:00"  # outside 5-day recency window

    def test_returns_most_recent_close_cycle_id(self):
        events = [
            {
                "type": EVENT_TYPE_CONCERN,
                "ts": self.OLDER_RECENT,
                "metadata": {"close_cycle_id": "older0001cyc"},
            },
            {
                "type": EVENT_TYPE_CONCERN,
                "ts": self.RECENT,
                "metadata": {"close_cycle_id": "newest01cyc1"},
            },
        ]
        self.assertEqual(
            resolves_probe._find_active_cycle_id(events, self.NOW),
            "newest01cyc1",
        )

    def test_ignores_stale_concerns_outside_recency_window(self):
        events = [
            {
                "type": EVENT_TYPE_CONCERN,
                "ts": self.STALE,
                "metadata": {"close_cycle_id": "stale001cyc1"},
            },
        ]
        self.assertIsNone(resolves_probe._find_active_cycle_id(events, self.NOW))

    def test_ignores_concerns_without_close_cycle_id(self):
        events = [
            {"type": EVENT_TYPE_CONCERN, "ts": self.RECENT, "metadata": {}},
            {"type": EVENT_TYPE_CONCERN, "ts": self.RECENT},
        ]
        self.assertIsNone(resolves_probe._find_active_cycle_id(events, self.NOW))

    def test_ignores_non_concern_events(self):
        events = [
            {
                "type": EVENT_TYPE_STATUS,
                "ts": self.RECENT,
                "metadata": {"close_cycle_id": "shouldskip00"},
            },
        ]
        self.assertIsNone(resolves_probe._find_active_cycle_id(events, self.NOW))

    def test_empty_events_returns_none(self):
        self.assertIsNone(resolves_probe._find_active_cycle_id([], self.NOW))


class TestFindProbeCandidatesInSprintBatch(_HookTestCase):
    """find_probe_candidates surfaces in-cycle siblings even when they have
    no file/keyword overlap with the staged commit (the divert-gap case)."""

    NOW = "2026-04-29T00:00:00+00:00"
    RECENT = "2026-04-27T00:00:00+00:00"
    CYCLE_ACTIVE = "active01cycle"
    CYCLE_OTHER = "other001cycle"

    def _seed_concern(
        self,
        content: str,
        files: list[str],
        cycle_id: str | None,
        ts: str = RECENT,
    ) -> str:
        metadata = {}
        if cycle_id is not None:
            metadata = {"close_cycle_id": cycle_id, "close_mode": "sprint"}
        c = make_event(
            EVENT_TYPE_CONCERN, content=content, files=files, ts=ts, metadata=metadata
        )
        _common.append_safe(self.smm_dir, c)
        return c["id"]

    def test_sibling_without_file_overlap_surfaces_via_axis(self):
        # Active cycle established by a concern that ALSO has file overlap
        # with the commit (so the active cycle is detected; this concern
        # itself is excluded by the resolves filter below).
        anchor = self._seed_concern(
            "anchor concern", ["scripts/auth.py"], self.CYCLE_ACTIVE
        )
        # Sibling: same cycle, totally different file, no keyword overlap
        sibling = self._seed_concern(
            "completely unrelated text", ["docs/unrelated.md"], self.CYCLE_ACTIVE
        )
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [anchor],
            cwd=str(self.smm_dir),
            commit_message="fix auth",
            now_ts=self.NOW,
        )
        ids = [c["id"] for c in result]
        self.assertIn(sibling, ids)
        sib = next(c for c in result if c["id"] == sibling)
        self.assertIn(SELECTION_REASON_IN_SPRINT_BATCH, sib["selection_reasons"])

    def test_only_in_cycle_sibling_surfaces_among_three(self):
        """E2E AC: 3 close-cycle siblings (1 in-cycle, 2 out-of-cycle) and
        none have file/keyword overlap with the commit. Only the 1 in-cycle
        appears via the new axis."""
        # Anchor: triggers active-cycle detection AND provides the file overlap
        # the existing pipeline needs to start producing candidates.
        anchor = self._seed_concern("anchor", ["scripts/auth.py"], self.CYCLE_ACTIVE)
        in_cycle = self._seed_concern("sibling A", ["docs/a.md"], self.CYCLE_ACTIVE)
        out_b = self._seed_concern("sibling B", ["docs/b.md"], self.CYCLE_OTHER)
        out_c = self._seed_concern("sibling C", ["docs/c.md"], self.CYCLE_OTHER)
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [anchor],
            cwd=str(self.smm_dir),
            now_ts=self.NOW,
        )
        ids = [c["id"] for c in result]
        self.assertIn(in_cycle, ids)
        self.assertNotIn(out_b, ids)
        self.assertNotIn(out_c, ids)

    def test_empty_commit_files_still_surfaces_in_cycle_siblings(self):
        # The in-sprint-batch axis was designed to surface siblings even
        # without file overlap. An early-return on empty commit_files would
        # defeat the axis entirely for amend-no-files commits.
        anchor = self._seed_concern(
            "anchor concern", ["scripts/auth.py"], self.CYCLE_ACTIVE
        )
        sibling = self._seed_concern(
            "unrelated text", ["docs/unrelated.md"], self.CYCLE_ACTIVE
        )
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            [],
            [anchor],
            cwd=str(self.smm_dir),
            now_ts=self.NOW,
        )
        ids = [c["id"] for c in result]
        self.assertIn(sibling, ids)

    def test_no_active_cycle_when_only_stale_close_concerns(self):
        # All close-cycle concerns are outside the recency window → no
        # active cycle → axis fires nowhere → only the file-matching
        # concern surfaces (via existing pipeline).
        old = "2026-04-01T00:00:00+00:00"  # 28 days ago
        file_match = self._seed_concern(
            "file match", ["scripts/auth.py"], cycle_id=None, ts=self.RECENT
        )
        stale_anchor = self._seed_concern(
            "stale anchor", ["docs/x.md"], self.CYCLE_ACTIVE, ts=old
        )
        stale_sibling = self._seed_concern(
            "stale sibling", ["docs/y.md"], self.CYCLE_ACTIVE, ts=old
        )
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            now_ts=self.NOW,
        )
        ids = [c["id"] for c in result]
        self.assertIn(file_match, ids)
        self.assertNotIn(stale_anchor, ids)
        self.assertNotIn(stale_sibling, ids)


class TestSelectionReasonVocabularyCap(unittest.TestCase):
    """The SELECTION_REASON_* vocabulary is capped to keep probe metadata
    payload size bounded and force deliberate review when adding a new
    selector signal.

    Adding a 6th constant requires:
      1. Updating _score_candidate to emit it (in deterministic order)
      2. Bumping this expected count
      3. Reviewing the divert-narrative payload size impact (each probe
         records {cid: [reasons...]} for up to PROBE_CANDIDATE_LIMIT=5
         candidates — adding a constant grows worst-case payload by 5
         strings per probe event).
    """

    def test_exactly_five_selection_reason_constants(self):
        # Substring match catches both public (SELECTION_REASON_*) and
        # private (_SELECTION_REASON_*) — a private constant still grows
        # the divert payload, so it counts toward the cap.
        constants = {n for n in dir(event_schema) if "SELECTION_REASON_" in n}
        self.assertEqual(
            constants,
            {
                "SELECTION_REASON_KEYWORD",
                "SELECTION_REASON_FILE_OVERLAP",
                "SELECTION_REASON_RECENCY",
                "SELECTION_REASON_CLOSE_MODE",
                "SELECTION_REASON_IN_SPRINT_BATCH",
            },
            "Selector-signal vocabulary changed — see this test's docstring "
            "for the deliberate-review checklist before updating the expected set.",
        )


class TestFindProbeCandidatesSorting(_HookTestCase):
    """find_probe_candidates sorts by score descending, ts as tiebreak."""

    def _seed_concern(
        self, content: str, files: list[str], ts: str = "2026-04-01T00:00:00+00:00"
    ) -> str:
        concern = make_event(EVENT_TYPE_CONCERN, content=content, files=files, ts=ts)
        _common.append_safe(self.smm_dir, concern)
        return concern["id"]

    def test_sorts_by_score_descending(self):
        # cid_low: file overlap only (+1)
        cid_low = self._seed_concern("zzz", ["scripts/auth.py"])
        # cid_high: file overlap (+1) + keyword 'tokens' match (+2)
        cid_high = self._seed_concern("tokens leak", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            commit_message="fix tokens issue",
            now_ts="2026-04-29T00:00:00+00:00",
        )
        ids = [c["id"] for c in result]
        self.assertLess(ids.index(cid_high), ids.index(cid_low))

    def test_ts_descending_tiebreak_when_scores_equal(self):
        cid_old = self._seed_concern(
            "zzz", ["scripts/auth.py"], ts="2026-04-01T00:00:00+00:00"
        )
        cid_new = self._seed_concern(
            "zzz", ["scripts/auth.py"], ts="2026-04-15T00:00:00+00:00"
        )
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            now_ts="2026-04-29T00:00:00+00:00",
        )
        ids = [c["id"] for c in result]
        # Both score equally — file overlap +1, neither within 5-day window
        # (old=28d, new=14d). ts-desc tiebreak → newer first.
        self.assertLess(ids.index(cid_new), ids.index(cid_old))


class TestEmitProbeStatus(_ProbeTestHelpers, _HookTestCase):
    """emit_probe_status writes a probe status event to events.jsonl."""

    def test_no_event_when_no_candidates(self):
        resolves_probe.emit_probe_status(self.smm_dir, [], "agent")
        self.assertEqual(self._probes(), [])

    def test_event_written_when_candidates_exist(self):
        candidates = [
            {"id": "abc", "content": "first"},
            {"id": "def", "content": "second"},
        ]
        resolves_probe.emit_probe_status(self.smm_dir, candidates, "main")
        probes = self._probes()
        self.assertEqual(len(probes), 1)
        self.assertEqual(
            probes[0]["content"], f"{STATUS_CONTENT_RESOLVES_PROBE}: 2 candidates"
        )
        self.assertEqual(
            probes[0]["metadata"][METADATA_KEY_PROBE_CANDIDATES], ["abc", "def"]
        )

    def test_event_writes_selection_reasons_per_candidate(self):
        candidates = [
            {
                "id": "abc",
                "content": "first",
                "selection_reasons": [
                    SELECTION_REASON_KEYWORD,
                    SELECTION_REASON_FILE_OVERLAP,
                ],
            },
            {"id": "def", "content": "second", "selection_reasons": []},
        ]
        resolves_probe.emit_probe_status(self.smm_dir, candidates, "main")
        probes = self._probes()
        reasons_map = probes[0]["metadata"][METADATA_KEY_PROBE_SELECTION_REASONS]
        self.assertEqual(
            reasons_map,
            {
                "abc": [SELECTION_REASON_KEYWORD, SELECTION_REASON_FILE_OVERLAP],
                "def": [],
            },
        )

    def test_event_defaults_missing_selection_reasons_to_empty(self):
        candidates = [{"id": "abc", "content": "no reasons attached"}]
        resolves_probe.emit_probe_status(self.smm_dir, candidates, "main")
        reasons_map = self._probes()[0]["metadata"][
            METADATA_KEY_PROBE_SELECTION_REASONS
        ]
        self.assertEqual(reasons_map, {"abc": []})


if __name__ == "__main__":
    unittest.main()

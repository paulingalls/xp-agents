#!/usr/bin/env python3
"""Tests for resolves_probe.py — pure probe-candidate extraction module."""

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import unittest

import _common
import event_schema
import resolves_probe
import worktree
from conftest import (
    _HookTestCase,
    _NormalizePathIdentityMixin,
    _ProbeTestHelpers,
    make_event,
)
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_STATUS,
    METADATA_KEY_PROBE_CANDIDATES,
    METADATA_KEY_PROBE_SELECTION_REASONS,
    METADATA_KEY_PROBE_SNAPSHOT_MAX_TS,
    METADATA_KEY_PROBE_TAIL_TS,
    SELECTION_REASON_CLOSE_MODE,
    SELECTION_REASON_FILE_OVERLAP,
    SELECTION_REASON_IN_BATCH_CLOSE_NO_OVERLAP,
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

    def test_selection_reasons_render_as_why_suffix(self):
        """Story-003 (A): each item line surfaces ALL selection_reasons as
        a `(why: ...)` suffix so the agent sees WHY each candidate was
        picked. No positional cap — concern 684a9d401adc: capping would
        always occlude `in_sprint_batch` / `close_mode` (the signals
        explaining WHY no-file-overlap siblings surfaced, which is exactly
        what sprint-067 retro is targeting). Vocabulary is hard-capped at
        5 by SELECTION_REASON_* contract, so worst-case suffix fits one
        line."""
        candidate = {
            "id": "abc123def456",
            "type": EVENT_TYPE_CONCERN,
            "severity": "medium",
            "content": "Auth leak",
            "selection_reasons": [
                SELECTION_REASON_KEYWORD,
                SELECTION_REASON_FILE_OVERLAP,
                SELECTION_REASON_RECENCY,
                SELECTION_REASON_IN_SPRINT_BATCH,
            ],
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        expected_why = (
            f"(why: {SELECTION_REASON_KEYWORD}, "
            f"{SELECTION_REASON_FILE_OVERLAP}, "
            f"{SELECTION_REASON_RECENCY}, "
            f"{SELECTION_REASON_IN_SPRINT_BATCH})"
        )
        self.assertIn(expected_why, block)

    def test_no_why_suffix_when_selection_reasons_empty(self):
        """Empty/missing selection_reasons → no `(why: ...)` suffix at all,
        so legacy probe payloads (pre-reasons) and zero-signal candidates
        render cleanly without an empty suffix."""
        candidate = {
            "id": "abc123def456",
            "type": EVENT_TYPE_CONCERN,
            "severity": "medium",
            "content": "Plain concern",
            "selection_reasons": [],
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertNotIn("why:", block)

    def test_why_suffix_coexists_with_close_mode_suffix(self):
        """When BOTH close_mode (provenance) and selection_reasons are present,
        both suffixes render — they're independent signals (provenance is for
        attribution, why is for selection rationale)."""
        candidate = {
            "id": "abc123def456",
            "type": EVENT_TYPE_CONCERN,
            "severity": "medium",
            "content": "Cross-cutting",
            "metadata": {"close_mode": "sprint"},
            "selection_reasons": [SELECTION_REASON_FILE_OVERLAP],
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("(from sprint-close-reviewer)", block)
        self.assertIn(f"(why: {SELECTION_REASON_FILE_OVERLAP})", block)

    def test_why_suffix_does_not_break_ready_to_use_trailer_line(self):
        """The trailer line `Ready-to-use trailer: Resolves-Event: <ids>` is
        load-bearing for pre_tool_bash and downstream consumers. Adding the
        per-item `(why: ...)` suffix must NOT bleed into or break that line.
        """
        candidates = [
            {
                "id": "abc",
                "type": EVENT_TYPE_CONCERN,
                "content": "first",
                "selection_reasons": [SELECTION_REASON_KEYWORD],
            },
            {
                "id": "def",
                "type": EVENT_TYPE_CONCERN,
                "content": "second",
                "selection_reasons": [SELECTION_REASON_FILE_OVERLAP],
            },
        ]
        block = resolves_probe.build_nudge_lines(candidates)[0]
        self.assertIn("\nReady-to-use trailer: Resolves-Event: abc, def", block)


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


class TestInBatchCloseNoOverlapWidening(_ScoringHelpers, unittest.TestCase):
    """Widening for batched close-mode siblings without file overlap.

    /xp-story-close batched multi-resolves emit candidates that legitimately
    have files=[] but belong to the active cycle. Without this widening,
    the file-overlap signal alone keeps them below the top-5 cap and they
    fall out — the outside-file-domain divert observed at 33% of recent
    diverts (retro Try #3). When in_sprint_batch + close_mode both fire
    and file_overlap is 0, add +1 score and emit the marker reason so
    the divert classifier doesn't tag them as outside-file-domain.
    """

    CYCLE = "abc123def456"

    def _close_mode_in_cycle_no_overlap(self):
        return self._candidate(
            content="zzz",
            files=[],
            metadata={"close_mode": "sprint", "close_cycle_id": self.CYCLE},
        )

    def test_in_batch_close_no_overlap_adds_one_when_both_signals_fire(self):
        cand = self._close_mode_in_cycle_no_overlap()
        with_widening = self._score(cand, active_cycle_id=self.CYCLE)
        without_widening = self._score(cand, active_cycle_id=None)
        # Without widening: only close_mode fires (+1).
        # With widening: in_sprint_batch (+1) + the new widening (+1) on top.
        self.assertEqual(with_widening - without_widening, 2)

    def test_in_batch_close_no_overlap_emits_marker_reason(self):
        cand = self._close_mode_in_cycle_no_overlap()
        _, reasons = self._score_with_reasons(cand, active_cycle_id=self.CYCLE)
        self.assertIn(SELECTION_REASON_IN_BATCH_CLOSE_NO_OVERLAP, reasons)

    def test_does_not_fire_when_file_overlap_present(self):
        # If file_overlap is already there, the FILE_OVERLAP signal already
        # carries this candidate; widening would double-count.
        cand = self._candidate(
            content="zzz",
            files=["scripts/auth.py"],
            metadata={"close_mode": "sprint", "close_cycle_id": self.CYCLE},
        )
        _, reasons = self._score_with_reasons(
            cand,
            commit_files=["scripts/auth.py"],
            active_cycle_id=self.CYCLE,
        )
        self.assertNotIn(SELECTION_REASON_IN_BATCH_CLOSE_NO_OVERLAP, reasons)

    def test_does_not_fire_without_close_mode(self):
        # In-cycle but not close-mode (e.g. an in-progress concern that just
        # happens to share cycle): widening must not fire.
        cand = self._candidate(
            content="zzz",
            files=[],
            metadata={"close_cycle_id": self.CYCLE},
        )
        _, reasons = self._score_with_reasons(cand, active_cycle_id=self.CYCLE)
        self.assertNotIn(SELECTION_REASON_IN_BATCH_CLOSE_NO_OVERLAP, reasons)

    def test_does_not_fire_without_in_sprint_batch(self):
        # Close-mode but no active cycle (or different cycle): widening
        # must not fire — both signals are required together.
        cand = self._close_mode_in_cycle_no_overlap()
        _, reasons = self._score_with_reasons(cand, active_cycle_id=None)
        self.assertNotIn(SELECTION_REASON_IN_BATCH_CLOSE_NO_OVERLAP, reasons)


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

    Adding a 7th constant requires:
      1. Updating _score_candidate to emit it (in deterministic order)
      2. Bumping this expected count
      3. Reviewing the divert-narrative payload size impact (each probe
         records {cid: [reasons...]} for up to PROBE_CANDIDATE_LIMIT=5
         candidates — adding a constant grows worst-case payload by 5
         strings per probe event).
    """

    def test_exactly_six_selection_reason_constants(self):
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
                "SELECTION_REASON_IN_BATCH_CLOSE_NO_OVERLAP",
            },
            "Selector-signal vocabulary changed — see this test's docstring "
            "for the deliberate-review checklist before updating the expected set.",
        )


class TestFindProbeCandidatesSnapshotFreshness(_ProbeTestHelpers, _HookTestCase):
    """Story-003 (B): when caller passes an `events` snapshot that is
    meaningfully older than `now_ts`, find_probe_candidates re-loads
    events from disk so newer events appear in the candidate set.

    Without this guard, the caller's stale snapshot would silently miss
    events that arrived on disk between snapshot time and probe time —
    leading to spurious `newer-than-snapshot` divert classifications
    when the agent commits with a Resolves-Event id that the freshness
    reload would have surfaced as a candidate.
    """

    def test_stale_events_snapshot_triggers_disk_reload(self):
        """Caller passes events snapshot whose newest ts is well before
        now_ts. find_probe_candidates detects the staleness and re-reads
        events.jsonl, picking up a fresh concern that wasn't in the
        snapshot."""
        old_ts = "2026-04-29T10:00:00+00:00"
        # Old concern is on disk AND in the caller's stale snapshot.
        old_id = self._seed_concern("Old auth concern", ["scripts/auth.py"], old_ts)
        stale_events, stale_resolutions = _common.load_events_with_resolutions(
            self.smm_dir
        )
        # New concern arrives on disk AFTER the caller took its snapshot.
        new_ts = "2026-04-29T10:00:30+00:00"
        new_id = self._seed_concern("Fresh auth concern", ["scripts/auth.py"], new_ts)
        # Caller passes the stale snapshot but now_ts is well after the new
        # concern's ts — staleness threshold MUST trigger a disk reload.
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            events=stale_events,
            resolutions=stale_resolutions,
            now_ts="2026-04-29T10:01:00+00:00",
        )
        ids = {c["id"] for c in result}
        self.assertIn(
            new_id,
            ids,
            "Fresh concern must surface after staleness-triggered reload — "
            "without this, divert classifier spuriously fires "
            "newer-than-snapshot for events on disk at commit time.",
        )
        self.assertIn(old_id, ids, "Old concern must still surface after reload.")

    def test_fresh_events_snapshot_skips_disk_reload(self):
        """When the passed snapshot's newest ts is within the freshness
        threshold of now_ts, find_probe_candidates trusts the snapshot
        and does NOT re-read disk. Verified by mutating the on-disk file
        AFTER snapshotting — the mutation must NOT appear in the result.
        """
        ts = "2026-04-29T10:00:00+00:00"
        old_id = self._seed_concern("Old auth concern", ["scripts/auth.py"], ts)
        snapshot, snapshot_resolutions = _common.load_events_with_resolutions(
            self.smm_dir
        )
        # Disk gains a new concern AFTER snapshot — but now_ts is only a
        # second after the snapshot's newest ts, well within threshold.
        new_id = self._seed_concern(
            "Fresh auth concern", ["scripts/auth.py"], "2026-04-29T10:00:01+00:00"
        )
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            events=snapshot,
            resolutions=snapshot_resolutions,
            now_ts="2026-04-29T10:00:01+00:00",
        )
        ids = {c["id"] for c in result}
        self.assertIn(old_id, ids)
        self.assertNotIn(
            new_id,
            ids,
            "Fresh snapshot must NOT trigger a disk reload — staleness "
            "threshold is the contract that gates the reload.",
        )

    def test_events_none_still_loads_fresh_unchanged(self):
        """Backward-compat: existing callers that pass events=None continue
        to load fresh from disk (no behavior change for the pre-commit hook
        path that doesn't pre-snapshot events)."""
        cid = self._seed_concern(
            "Auth concern", ["scripts/auth.py"], "2026-04-29T10:00:00+00:00"
        )
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            now_ts="2026-04-29T10:01:00+00:00",
        )
        self.assertIn(cid, [c["id"] for c in result])


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

    def test_emit_with_probe_meta_emits_even_when_zero_candidates(self):
        # The most diagnostic case for newer-than-snapshot diverts is the
        # zero-candidate emit — without this, we'd never see the snapshot
        # vs tail-ts evidence for a divert that matters most.
        probe_meta = {
            METADATA_KEY_PROBE_SNAPSHOT_MAX_TS: "2026-04-29T10:00:00+00:00",
            METADATA_KEY_PROBE_TAIL_TS: "2026-04-29T10:00:30+00:00",
        }
        resolves_probe.emit_probe_status(
            self.smm_dir, [], "main", probe_meta=probe_meta
        )
        probes = self._probes()
        self.assertEqual(len(probes), 1)
        meta = probes[0]["metadata"]
        self.assertEqual(
            meta[METADATA_KEY_PROBE_SNAPSHOT_MAX_TS], "2026-04-29T10:00:00+00:00"
        )
        self.assertEqual(meta[METADATA_KEY_PROBE_TAIL_TS], "2026-04-29T10:00:30+00:00")

    def test_emit_with_neither_candidates_nor_probe_meta_returns_silently(self):
        # Regression guard for the original empty-candidates short-circuit:
        # when there's nothing to emit AND no diagnostic metadata, stay
        # silent. Only the probe_meta channel can override the early return.
        resolves_probe.emit_probe_status(self.smm_dir, [], "main", probe_meta=None)
        self.assertEqual(self._probes(), [])

    def test_emit_with_candidates_and_probe_meta_merges_metadata(self):
        candidates = [{"id": "abc", "content": "first"}]
        probe_meta = {
            METADATA_KEY_PROBE_SNAPSHOT_MAX_TS: "2026-04-29T10:00:00+00:00",
            METADATA_KEY_PROBE_TAIL_TS: "2026-04-29T10:00:00+00:00",
        }
        resolves_probe.emit_probe_status(
            self.smm_dir, candidates, "main", probe_meta=probe_meta
        )
        meta = self._probes()[0]["metadata"]
        self.assertEqual(meta[METADATA_KEY_PROBE_CANDIDATES], ["abc"])
        self.assertEqual(
            meta[METADATA_KEY_PROBE_SNAPSHOT_MAX_TS], "2026-04-29T10:00:00+00:00"
        )
        self.assertEqual(meta[METADATA_KEY_PROBE_TAIL_TS], "2026-04-29T10:00:00+00:00")


class TestFindProbeCandidatesOutMeta(_ProbeTestHelpers, _HookTestCase):
    """find_probe_candidates populates out_meta with snapshot/tail timestamps.

    Reinforces the newer-than-snapshot divert diagnosis by capturing both
    the caller's snapshot freshness AND the on-disk tail at probe time —
    so retro_metrics (and humans) can see whether a divert was caused by
    snapshot lag or by something else.
    """

    def test_out_meta_populated_with_snapshot_and_tail_ts(self):
        ts = "2026-04-29T10:00:00+00:00"
        self._seed_concern("Auth concern", ["scripts/auth.py"], ts)
        events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        out_meta: dict = {}
        resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            events=events,
            resolutions=resolutions,
            now_ts="2026-04-29T10:00:01+00:00",
            out_meta=out_meta,
        )
        self.assertEqual(out_meta[METADATA_KEY_PROBE_SNAPSHOT_MAX_TS], ts)
        self.assertEqual(out_meta[METADATA_KEY_PROBE_TAIL_TS], ts)

    def test_out_meta_snapshot_ts_pinned_before_staleness_reread(self):
        # When the caller's snapshot is stale, find_probe_candidates re-reads
        # disk. The pinning contract: snapshot_max_ts MUST reflect the
        # caller's stale value, not the post-reread tail. Otherwise both
        # timestamps equal disk tail and the metric is meaningless.
        old_ts = "2026-04-29T10:00:00+00:00"
        self._seed_concern("Old concern", ["scripts/auth.py"], old_ts)
        stale_events, stale_res = _common.load_events_with_resolutions(self.smm_dir)
        new_ts = "2026-04-29T10:00:30+00:00"
        self._seed_concern("Fresh concern", ["scripts/auth.py"], new_ts)
        out_meta: dict = {}
        resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            events=stale_events,
            resolutions=stale_res,
            now_ts="2026-04-29T10:01:00+00:00",
            out_meta=out_meta,
        )
        self.assertEqual(
            out_meta[METADATA_KEY_PROBE_SNAPSHOT_MAX_TS],
            old_ts,
            "snapshot_max_ts MUST be the caller's pre-reread max, not the "
            "disk tail post-reread; otherwise newer-than-snapshot diverts "
            "are undiagnosable.",
        )
        self.assertEqual(out_meta[METADATA_KEY_PROBE_TAIL_TS], new_ts)

    def test_out_meta_default_none_does_not_break_existing_callers(self):
        ts = "2026-04-29T10:00:00+00:00"
        self._seed_concern("Auth concern", ["scripts/auth.py"], ts)
        # No out_meta passed — pre-existing call shape, must not error.
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            now_ts="2026-04-29T10:00:01+00:00",
        )
        self.assertEqual(len(result), 1)


class TestFindProbeCandidatesDiscovery(_HookTestCase):
    """Discovery events surface as probe candidates the same way concerns
    and debts do, so commits closing a discovery don't force the agent to
    hand-edit a Resolves-Event trailer."""

    NOW = "2026-04-29T00:00:00+00:00"
    RECENT = "2026-04-27T00:00:00+00:00"
    CYCLE_ACTIVE = "active01cycle"

    def _seed_discovery(
        self,
        content: str,
        files: list[str],
        cycle_id: str | None = None,
        ts: str = RECENT,
    ) -> str:
        metadata: dict = {}
        if cycle_id is not None:
            metadata = {"close_cycle_id": cycle_id, "close_mode": "sprint"}
        e = make_event(
            EVENT_TYPE_DISCOVERY,
            content=content,
            files=files,
            ts=ts,
            metadata=metadata,
        )
        _common.append_safe(self.smm_dir, e)
        return e["id"]

    def _seed_concern(self, content: str, files: list[str]) -> str:
        c = make_event(EVENT_TYPE_CONCERN, content=content, files=files)
        _common.append_safe(self.smm_dir, c)
        return c["id"]

    def _seed_debt(self, content: str, files: list[str]) -> str:
        d = make_event(EVENT_TYPE_DEBT, content=content, files=files)
        _common.append_safe(self.smm_dir, d)
        return d["id"]

    def _seed_anchor_in_cycle(self) -> str:
        """Seed an in-cycle anchor concern that triggers _find_active_cycle_id
        and provides the file overlap the upstream pipeline needs."""
        anchor = make_event(
            EVENT_TYPE_CONCERN,
            content="anchor with cycle",
            files=["scripts/auth.py"],
            ts=self.RECENT,
            metadata={"close_cycle_id": self.CYCLE_ACTIVE, "close_mode": "sprint"},
        )
        _common.append_safe(self.smm_dir, anchor)
        return anchor["id"]

    # -- AC #1: file-overlap discoveries surface ------------------------------

    def test_open_discovery_with_file_overlap_surfaces(self):
        """AC #1: an open discovery whose files overlap the commit appears
        in the candidate set."""
        did = self._seed_discovery("Auth assumption broken", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            now_ts=self.NOW,
        )
        self.assertIn(did, [c["id"] for c in result])

    def test_resolved_discovery_does_not_surface(self):
        """A discovery that's already been resolved (e.g. via a prior
        Resolves-Event trailer) MUST NOT appear in the candidate set."""
        did = self._seed_discovery("Already resolved", ["scripts/auth.py"])
        # Resolver references the discovery by id — compute_resolutions will
        # bucket the discovery into resolved_other_ids.
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="resolves the discovery",
            metadata={"resolves": [did]},
            references=[did],
        )
        _common.append_safe(self.smm_dir, resolver)
        events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        self.assertIn(did, resolutions["resolved_other_ids"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            events=events,
            resolutions=resolutions,
            now_ts=self.NOW,
        )
        self.assertNotIn(did, [c["id"] for c in result])

    def test_discovery_filtered_via_resolves_arg(self):
        """Resolves-Event trailer ids passed in as `resolves` filter
        discoveries the same as concerns/debts."""
        did = self._seed_discovery("Skip me", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [did],
            cwd=str(self.smm_dir),
            now_ts=self.NOW,
        )
        self.assertNotIn(did, [c["id"] for c in result])

    # -- AC #2: ranking unchanged across mixed types --------------------------

    def test_mixed_types_ranking_unchanged(self):
        """AC #2: with a mix of concern + debt + discovery all matching the
        same commit by file-overlap, ranking order on those rows mirrors the
        prior concern/debt behavior — ranking is type-agnostic, so equal
        scores tiebreak by ts descending."""
        # All three share the same file, same content shape, distinct ts.
        # Default OLD_TS ("2026-03-12") for both concern/debt; discovery
        # with newer ts so ts-descending tiebreak puts it first.
        cid = self._seed_concern("zzz", ["scripts/auth.py"])
        bid = self._seed_debt("zzz", ["scripts/auth.py"])
        did = self._seed_discovery("zzz", ["scripts/auth.py"], ts=self.RECENT)
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            now_ts=self.NOW,
        )
        ids = [c["id"] for c in result]
        self.assertIn(cid, ids)
        self.assertIn(bid, ids)
        self.assertIn(did, ids)
        # Discovery has the newest ts and a recency boost (within 5 days),
        # so it ranks first; concern/debt tie on score and ts → stable on
        # whichever was appended first (concern before debt).
        self.assertEqual(ids[0], did)

    # -- AC #3 (E2E): discovery surfaces with selection_reasons ---------------

    def test_discovery_carries_file_overlap_selection_reason(self):
        """E2E shape: a surfaced discovery candidate carries the same
        selection_reasons list shape as concerns/debts so build_nudge_lines
        and the probe-status event downstream consumers behave uniformly."""
        did = self._seed_discovery("auth middleware leaks tokens", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            commit_message="fix auth",
            now_ts=self.NOW,
        )
        cand = next(c for c in result if c["id"] == did)
        self.assertIn("selection_reasons", cand)
        self.assertIn(SELECTION_REASON_FILE_OVERLAP, cand["selection_reasons"])

    # -- in-sprint-batch sibling axis now also includes discoveries -----------

    def test_discovery_sibling_via_in_sprint_batch_axis(self):
        """Sibling-batch loop widening: a discovery carrying the same
        close_cycle_id as the active cycle surfaces as an in-batch sibling
        even without file overlap."""
        anchor = self._seed_anchor_in_cycle()
        sibling = self._seed_discovery(
            "sibling unrelated text",
            ["docs/unrelated.md"],
            cycle_id=self.CYCLE_ACTIVE,
        )
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [anchor],
            cwd=str(self.smm_dir),
            now_ts=self.NOW,
        )
        ids = [c["id"] for c in result]
        self.assertIn(sibling, ids)
        sib = next(c for c in result if c["id"] == sibling)
        self.assertIn(SELECTION_REASON_IN_SPRINT_BATCH, sib["selection_reasons"])

    def test_resolved_discovery_excluded_from_sibling_axis(self):
        """A discovery resolved by a prior Resolves-Event MUST NOT surface
        even when its close_cycle_id matches the active cycle — the sibling
        loop's resolved_set must include resolved_other_ids."""
        anchor = self._seed_anchor_in_cycle()
        sibling = self._seed_discovery(
            "sibling unrelated", ["docs/unrelated.md"], cycle_id=self.CYCLE_ACTIVE
        )
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="resolves",
            metadata={"resolves": [sibling]},
            references=[sibling],
        )
        _common.append_safe(self.smm_dir, resolver)
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [anchor],
            cwd=str(self.smm_dir),
            now_ts=self.NOW,
        )
        self.assertNotIn(sibling, [c["id"] for c in result])


class TestCountFileOverlaps(_NormalizePathIdentityMixin, unittest.TestCase):
    """_count_file_overlaps direct pin — covers list-guard, str-guard, and
    normalize_path raising branches that the discovery-flow tests reach
    only transitively. A future refactor that silently zeros the score
    must trip one of these. normalize_path is patched to identity so
    tests don't depend on a real git root.
    """

    CWD = "/tmp/repo"

    def test_non_list_returns_zero(self):
        self.assertEqual(
            resolves_probe._count_file_overlaps("not-a-list", {"a.py"}, self.CWD), 0
        )
        self.assertEqual(
            resolves_probe._count_file_overlaps(None, {"a.py"}, self.CWD), 0
        )

    def test_non_str_elements_skipped(self):
        self.assertEqual(
            resolves_probe._count_file_overlaps(["a.py", 42, None], {"a.py"}, self.CWD),
            1,
        )

    def test_normalize_path_raising_branch_skips_entry(self):
        def _raise(_f, _c):
            raise ValueError("bad")

        worktree.normalize_path = _raise
        self.assertEqual(
            resolves_probe._count_file_overlaps(["a.py"], {"a.py"}, self.CWD), 0
        )


def _pin_sentinel_mtime(smm_dir: Path, iso_ts: str) -> None:
    """Pin the probe-refresh sentinel's mtime to an ISO timestamp.

    Shared by the sentinel-staleness unit tests and the find_probe_candidates
    reload integration test so both assert against deterministic mtime
    arithmetic instead of wall-clock timing.
    """
    epoch = datetime.fromisoformat(iso_ts).timestamp()
    os.utime(resolves_probe.refresh_sentinel_path(smm_dir), (epoch, epoch))


class TestProbeRefreshSentinel(_HookTestCase):
    """Story-002: sentinel-based staleness signal closes the fast-commit gap.

    The 5s wall-clock threshold misses the case where adopt records a
    decision and the user commits within 5s — the snapshot's max_ts is
    near now_ts so the threshold doesn't trip, yet the just-written
    decision is missing from the snapshot. signal_probe_refresh writes
    a sentinel file that the staleness predicate sees, forcing a disk
    reload regardless of the 5s window.
    """

    def test_signal_probe_refresh_creates_sentinel(self):
        sentinel = resolves_probe.refresh_sentinel_path(self.smm_dir)
        self.assertFalse(sentinel.exists())
        resolves_probe.signal_probe_refresh(self.smm_dir)
        self.assertTrue(sentinel.exists())

    def test_no_sentinel_means_only_5s_threshold_applies(self):
        # Snapshot fresh (2s old, well under 5s threshold), no sentinel → not stale.
        now_ts = "2026-05-09T10:00:00+00:00"
        events = [{"ts": "2026-05-09T09:59:58+00:00", "type": EVENT_TYPE_CONCERN}]
        is_stale, _ = resolves_probe._is_events_snapshot_stale(
            events, now_ts, smm_dir=self.smm_dir
        )
        self.assertFalse(is_stale)

    def test_sentinel_postdating_snapshot_marks_stale(self):
        # Snapshot fresh (2s old → 5s threshold won't trip), but sentinel
        # mtime postdates the snapshot's max_ts → must mark stale.
        now_ts = "2026-05-09T10:00:00+00:00"
        max_ts = "2026-05-09T09:59:58+00:00"
        events = [{"ts": max_ts, "type": EVENT_TYPE_CONCERN}]
        resolves_probe.signal_probe_refresh(self.smm_dir)
        # 1s after max_ts → sentinel postdates snapshot.
        _pin_sentinel_mtime(self.smm_dir, "2026-05-09T09:59:59+00:00")

        is_stale, _ = resolves_probe._is_events_snapshot_stale(
            events, now_ts, smm_dir=self.smm_dir
        )
        self.assertTrue(
            is_stale,
            "Sentinel mtime postdating snapshot max_ts MUST mark stale even "
            "when 5s wall-clock threshold is not tripped — closes the "
            "fast-commit gap where adopt-written decisions land within 5s.",
        )

    def test_sentinel_predating_snapshot_does_not_mark_stale(self):
        # Sentinel mtime predates the snapshot's max_ts (e.g. snapshot taken
        # AFTER the last refresh signal) → snapshot is fresh, not stale.
        now_ts = "2026-05-09T10:00:00+00:00"
        max_ts = "2026-05-09T09:59:58+00:00"
        events = [{"ts": max_ts, "type": EVENT_TYPE_CONCERN}]
        resolves_probe.signal_probe_refresh(self.smm_dir)
        # 1s before max_ts → sentinel predates snapshot.
        _pin_sentinel_mtime(self.smm_dir, "2026-05-09T09:59:57+00:00")

        is_stale, _ = resolves_probe._is_events_snapshot_stale(
            events, now_ts, smm_dir=self.smm_dir
        )
        self.assertFalse(is_stale)

    def test_smm_dir_none_falls_back_to_threshold_only(self):
        # Backward compat: callers that don't pass smm_dir get the original
        # 5s-threshold-only behavior. Sentinel cannot be checked without a
        # directory to look in.
        now_ts = "2026-05-09T10:00:00+00:00"
        events = [{"ts": "2026-05-09T09:59:58+00:00", "type": EVENT_TYPE_CONCERN}]
        is_stale, _ = resolves_probe._is_events_snapshot_stale(events, now_ts)
        self.assertFalse(is_stale)


class TestFindProbeCandidatesSentinelReload(_ProbeTestHelpers, _HookTestCase):
    """Story-002 AC#1: find_probe_candidates reloads from disk when the
    refresh sentinel postdates the caller's snapshot, even when the 5s
    wall-clock threshold would not trip.
    """

    def test_sentinel_signaled_reload_surfaces_fresh_concern_within_5s(self):
        # Old concern in caller's snapshot.
        old_ts = "2026-04-29T10:00:00+00:00"
        old_id = self._seed_concern("Old auth concern", ["scripts/auth.py"], old_ts)
        snapshot, snapshot_resolutions = _common.load_events_with_resolutions(
            self.smm_dir
        )
        # Fresh concern arrives on disk after snapshot (within 5s window so
        # the wall-clock threshold alone would NOT trigger reload).
        fresh_ts = "2026-04-29T10:00:01+00:00"
        fresh_id = self._seed_concern(
            "Fresh auth concern", ["scripts/auth.py"], fresh_ts
        )
        # Adopt-style refresh signal.
        resolves_probe.signal_probe_refresh(self.smm_dir)
        # Sentinel postdates snapshot max_ts.
        _pin_sentinel_mtime(self.smm_dir, fresh_ts)

        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            events=snapshot,
            resolutions=snapshot_resolutions,
            now_ts="2026-04-29T10:00:01+00:00",  # only 1s after snapshot max_ts
        )
        ids = {c["id"] for c in result}
        self.assertIn(
            fresh_id,
            ids,
            "Sentinel-signaled refresh MUST trigger disk reload within the "
            "5s window — closes the fast-commit gap.",
        )
        self.assertIn(old_id, ids, "Old concern must still surface after reload.")


class TestSentinelCleanup(_ProbeTestHelpers, _HookTestCase):
    """Story-005: sentinel is consumed on successful reload, persists on failure.

    Without cleanup the sentinel inode persists indefinitely after first
    adopt — every subsequent probe pays a stat()+ISO parse and a backup-
    restore with future-dated mtime would mark all probes stale until the
    snapshot's max_ts caught up. Failure-path persistence is load-bearing:
    if a reload raises and we drop the sentinel anyway, the next probe
    silently misses the refresh signal — re-opening the divert class
    sprint-079 just closed.
    """

    def test_sentinel_unlinked_after_successful_reload(self):
        # Snapshot has an old concern; a fresh concern lands on disk after
        # the snapshot, and the sentinel is signaled with mtime postdating
        # snapshot max_ts → forces reload via the sentinel path (not the
        # 5s wall-clock threshold). After the successful reload, the
        # sentinel must be gone.
        old_ts = "2026-04-29T10:00:00+00:00"
        self._seed_concern("Old auth concern", ["scripts/auth.py"], old_ts)
        snapshot, snapshot_resolutions = _common.load_events_with_resolutions(
            self.smm_dir
        )
        fresh_ts = "2026-04-29T10:00:01+00:00"
        self._seed_concern("Fresh auth concern", ["scripts/auth.py"], fresh_ts)
        resolves_probe.signal_probe_refresh(self.smm_dir)
        _pin_sentinel_mtime(self.smm_dir, fresh_ts)
        sentinel = resolves_probe.refresh_sentinel_path(self.smm_dir)
        self.assertTrue(sentinel.exists(), "precondition: sentinel exists pre-probe")

        resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            events=snapshot,
            resolutions=snapshot_resolutions,
            now_ts="2026-04-29T10:00:01+00:00",
        )

        self.assertFalse(
            sentinel.exists(),
            "Sentinel MUST be unlinked after a successful staleness-triggered "
            "reload — otherwise the inode persists indefinitely and every "
            "subsequent probe pays an extra stat() + ISO parse.",
        )

    def test_sentinel_unlinked_on_cold_load_with_events_none(self):
        # Production callers (pre_tool_bash, pre_tool_skill) invoke with
        # events=None — the cold-load branch. is_stale is False (no
        # snapshot to evaluate), but the load runs unconditionally and
        # the sentinel must be cleaned up so it doesn't persist across
        # subsequent probes. Without this, the d7d2b2f7475d defect
        # ("sentinel persists indefinitely after first adopt") survives
        # in production despite the staleness-branch cleanup.
        self._seed_concern(
            "Auth concern", ["scripts/auth.py"], "2026-04-29T10:00:00+00:00"
        )
        resolves_probe.signal_probe_refresh(self.smm_dir)
        sentinel = resolves_probe.refresh_sentinel_path(self.smm_dir)
        self.assertTrue(sentinel.exists(), "precondition: sentinel exists pre-probe")

        resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            now_ts="2026-04-29T10:00:01+00:00",
        )

        self.assertFalse(
            sentinel.exists(),
            "Sentinel MUST be unlinked after the cold-load branch (events=None) "
            "completes — production callers always take this path; without "
            "cleanup here the sentinel persists indefinitely.",
        )

    def test_sentinel_persists_when_reload_raises(self):
        # Same setup as above, but force the reload path to raise. The
        # sentinel must remain so the NEXT probe call retries the reload
        # — silently dropping the refresh signal would re-open the
        # missing-event divert class sprint-079 just closed.
        from unittest.mock import patch

        old_ts = "2026-04-29T10:00:00+00:00"
        self._seed_concern("Old auth concern", ["scripts/auth.py"], old_ts)
        snapshot, snapshot_resolutions = _common.load_events_with_resolutions(
            self.smm_dir
        )
        fresh_ts = "2026-04-29T10:00:01+00:00"
        self._seed_concern("Fresh auth concern", ["scripts/auth.py"], fresh_ts)
        resolves_probe.signal_probe_refresh(self.smm_dir)
        _pin_sentinel_mtime(self.smm_dir, fresh_ts)
        sentinel = resolves_probe.refresh_sentinel_path(self.smm_dir)

        with (
            patch.object(
                _common,
                "load_events_with_resolutions",
                side_effect=OSError("simulated read failure"),
            ),
            self.assertRaises(OSError),
        ):
            resolves_probe.find_probe_candidates(
                self.smm_dir,
                ["scripts/auth.py"],
                [],
                cwd=str(self.smm_dir),
                events=snapshot,
                resolutions=snapshot_resolutions,
                now_ts="2026-04-29T10:00:01+00:00",
            )

        self.assertTrue(
            sentinel.exists(),
            "Sentinel MUST persist when the reload raises — otherwise the "
            "next probe call silently misses the refresh signal and the "
            "missing-event divert class sprint-079 closed re-opens.",
        )


if __name__ == "__main__":
    unittest.main()

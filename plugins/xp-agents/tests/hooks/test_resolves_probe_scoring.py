#!/usr/bin/env python3
"""Tests for resolves_probe.py candidate scoring axes.

Covers _score_candidate's contributing signals — keyword overlap, file
overlap, recency boost, close-mode provenance, in-sprint-batch axis,
and the in-batch-close-no-overlap widening — plus the selection-reason
vocabulary cap that gates new signals.

Why a separate file: test_resolves_probe.py had grown well past the
project's 500-line budget. The scoring axes + selection-reason
vocabulary form a cohesive cluster around _score_candidate's contract
and split cleanly along feature lines.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import event_schema
import resolves_probe
import worktree
from event_schema import (
    EVENT_TYPE_CONCERN,
    SELECTION_REASON_CLOSE_MODE,
    SELECTION_REASON_FILE_OVERLAP,
    SELECTION_REASON_IN_BATCH_CLOSE_NO_OVERLAP,
    SELECTION_REASON_IN_SPRINT_BATCH,
    SELECTION_REASON_KEYWORD,
    SELECTION_REASON_RECENCY,
)


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


if __name__ == "__main__":
    unittest.main()

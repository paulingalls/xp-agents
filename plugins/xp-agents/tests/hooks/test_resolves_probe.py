#!/usr/bin/env python3
"""Tests for resolves_probe.py — pure probe-candidate extraction module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import unittest

import _common
import resolves_probe
import worktree
from conftest import _HookTestCase, _ProbeTestHelpers, make_event
from event_schema import (
    METADATA_KEY_PROBE_CANDIDATES,
    STATUS_CONTENT_RESOLVES_PROBE,
)


class TestFindProbeCandidates(_HookTestCase):
    """find_probe_candidates returns open concerns matching commit files."""

    def _seed_concern(self, content: str, files: list[str]) -> str:
        concern = make_event("concern", content=content, files=files)
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
            {"id": "abc123def456", "type": "concern", "content": "Auth leak"},
            {"id": "def456abc123", "type": "debt", "content": "Refactor auth"},
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
        candidate = {"id": "abc123def456", "type": "debt", "content": "Legacy code"}
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
            "type": "concern",
            "severity": "high",
            "content": "Auth leak",
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("[concern|high|abc123def456]", block)

    def test_concern_without_severity_falls_back(self):
        candidate = {"id": "abc123def456", "type": "concern", "content": "x"}
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("[concern|unknown|abc123def456]", block)

    def test_close_reviewer_provenance_suffix_includes_mode(self):
        candidate = {
            "id": "abc123def456",
            "type": "concern",
            "severity": "medium",
            "content": "Cross-cutting drift",
            "metadata": {"close_mode": "sprint"},
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("(from sprint-close-reviewer)", block)

    def test_close_reviewer_provenance_suffix_for_plan_mode(self):
        candidate = {
            "id": "abc123def456",
            "type": "concern",
            "severity": "medium",
            "content": "Architectural concern",
            "metadata": {"close_mode": "plan"},
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertIn("(from plan-close-reviewer)", block)

    def test_no_provenance_suffix_without_close_mode(self):
        candidate = {
            "id": "abc123def456",
            "type": "concern",
            "severity": "medium",
            "content": "Plain concern",
        }
        block = resolves_probe.build_nudge_lines([candidate])[0]
        self.assertNotIn("close-reviewer", block)


class TestScoreCandidate(unittest.TestCase):
    """_score_candidate ranks candidates by keyword + file + recency + provenance."""

    NOW = "2026-04-29T00:00:00+00:00"
    RECENT_TS = "2026-04-25T00:00:00+00:00"  # 4 days ago — within 7-day window
    OLD_TS = "2026-04-01T00:00:00+00:00"  # 28 days ago — outside window

    def _candidate(self, **kwargs) -> dict:
        base = {
            "id": "abc123def456",
            "type": "concern",
            "content": "Auth middleware leaks tokens",
            "files": ["scripts/auth.py"],
            "ts": self.OLD_TS,
            "metadata": {},
        }
        base.update(kwargs)
        return base

    def _score(self, candidate, *, commit_message="", commit_files=None, now_ts=None):
        """Convenience: compute haystack/file_set as find_probe_candidates does.

        Mirrors the production code path: commit_file_set is built via
        worktree.normalize_path so candidate files (also normalized inside
        _score_candidate) intersect on the same key shape regardless of
        whether the source path was absolute, relative, or `./`-prefixed.
        """
        commit_files = commit_files or []
        haystack_parts = [commit_message] + [Path(f).name for f in commit_files]
        haystack_keywords = resolves_probe._extract_keywords(" ".join(haystack_parts))
        cwd = "/"
        commit_file_set = {worktree.normalize_path(f, cwd) for f in commit_files}
        return resolves_probe._score_candidate(
            candidate, haystack_keywords, commit_file_set, cwd, now_ts or self.NOW
        )

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
        # 10 keywords all match → score should not exceed 5*2 = 10
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

    def test_recency_boost_when_within_seven_days(self):
        recent = self._candidate(ts=self.RECENT_TS, content="zzz", files=[])
        old = self._candidate(ts=self.OLD_TS, content="zzz", files=[])
        self.assertEqual(self._score(recent) - self._score(old), 1)

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


class TestFindProbeCandidatesSorting(_HookTestCase):
    """find_probe_candidates sorts by score descending, ts as tiebreak."""

    def _seed_concern(
        self, content: str, files: list[str], ts: str = "2026-04-01T00:00:00+00:00"
    ) -> str:
        concern = make_event("concern", content=content, files=files, ts=ts)
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
        # Both score equally — file overlap +1, neither within 7-day window
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


if __name__ == "__main__":
    unittest.main()

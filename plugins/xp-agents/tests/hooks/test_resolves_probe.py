#!/usr/bin/env python3
"""Tests for resolves_probe.py end-to-end candidate selection.

Covers find_probe_candidates (pool entry, cap, filter-resolved, attaches
selection reasons), build_nudge_lines, emit_probe_status, sorting/
tie-break, _find_active_cycle_id, in-sprint-batch + discovery
integration paths over events.jsonl, out-meta plumbing, and the
file-overlap normalizer.

Per-axis scoring + selection-reason vocabulary cap tests live in
test_resolves_probe_scoring.py. Snapshot-staleness + refresh-sentinel
reload tests live in test_resolves_probe_staleness.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import unittest

import _common
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
    SELECTION_REASON_FILE_OVERLAP,
    SELECTION_REASON_IN_SPRINT_BATCH,
    SELECTION_REASON_KEYWORD,
    SELECTION_REASON_RECENCY,
    STATUS_CONTENT_RESOLVES_PROBE,
)


class TestFindProbeCandidates(_ProbeTestHelpers, _HookTestCase):
    """find_probe_candidates returns open concerns matching commit files."""

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

    def test_keyword_only_match_enters_pool(self):
        """Concern matches commit by keyword alone (no file overlap)."""
        cid = self._seed_concern(
            "Auth middleware leaks tokens", ["different/path/file.py"]
        )
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/unrelated.py"],
            [],
            cwd=str(self.smm_dir),
            commit_message="fix auth middleware tokens",
        )
        ids = [c["id"] for c in result]
        self.assertIn(cid, ids, "keyword-only match must enter the pool")
        cand = next(c for c in result if c["id"] == cid)
        self.assertIn(SELECTION_REASON_KEYWORD, cand["selection_reasons"])
        self.assertNotIn(
            SELECTION_REASON_FILE_OVERLAP,
            cand["selection_reasons"],
            "file-overlap reason must not attach when no files overlap",
        )

    def test_keyword_match_does_not_duplicate_file_overlap(self):
        """Concern matching by both file AND keyword appears exactly once."""
        cid = self._seed_concern("Auth middleware leaks tokens", ["scripts/auth.py"])
        result = resolves_probe.find_probe_candidates(
            self.smm_dir,
            ["scripts/auth.py"],
            [],
            cwd=str(self.smm_dir),
            commit_message="fix auth middleware tokens",
        )
        ids = [c["id"] for c in result]
        self.assertEqual(ids.count(cid), 1, "candidate must not appear twice in pool")
        cand = next(c for c in result if c["id"] == cid)
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


class TestFindProbeCandidatesDiscovery(_ProbeTestHelpers, _HookTestCase):
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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for resolves_probe.py candidate pool axes — in-sprint-batch,
out_meta plumbing, and discovery-type integration.

Covers find_probe_candidates' three cohesive cluster sub-pools:

- In-sprint-batch sibling axis (TestFindProbeCandidatesInSprintBatch):
  in-cycle siblings surface even without file/keyword overlap; the
  divert-gap case the axis was built to close.
- out_meta plumbing (TestFindProbeCandidatesOutMeta): snapshot/tail
  timestamps populated correctly, pinned pre-reread, None default
  doesn't break existing callers.
- Discovery type-agnostic surfacing (TestFindProbeCandidatesDiscovery):
  discoveries surface via file-overlap and via the sibling axis the
  same as concerns/debts; resolved discoveries excluded uniformly.

Why a separate file: test_resolves_probe.py had grown to 949 lines
(1.9x the 500-line budget). The three pool axes form a cohesive
cluster that splits cleanly along feature lines, leaving the source
file with end-to-end pipeline tests (TestFindProbeCandidates,
TestBuildNudgeLines, TestEmitProbeStatus, TestFindActiveCycleId,
TestFindProbeCandidatesSorting, TestCountFileOverlaps).

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
from conftest import _HookTestCase, _ProbeTestHelpers, make_event
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_STATUS,
    METADATA_KEY_PROBE_SNAPSHOT_MAX_TS,
    METADATA_KEY_PROBE_TAIL_TS,
    SELECTION_REASON_FILE_OVERLAP,
    SELECTION_REASON_IN_SPRINT_BATCH,
)


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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for resolves_probe.py snapshot-staleness + refresh-sentinel reload.

Covers the two-axis disk-reload contract:

1. Wall-clock staleness — if a caller passes an events snapshot whose
   newest ts is meaningfully older than now_ts, find_probe_candidates
   re-reads events.jsonl so newer events appear in the candidate set.
2. Refresh sentinel — adopt-style writes signal a sentinel file whose
   mtime closes the fast-commit gap where the wall-clock threshold
   alone would miss just-written events landing within 5s.

Lifecycle: the sentinel is consumed on successful reload (so probe
calls don't pay a stat() per call after first adopt) and persists on
failure (so the next probe retries and the missing-event divert class
sprint-079 closed stays closed).

Why a separate file: test_resolves_probe.py had grown past the
project's 500-line budget. The staleness + sentinel tests are a
cohesive subset that splits cleanly along feature lines.
"""

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import resolves_probe
from conftest import _HookTestCase, _ProbeTestHelpers
from event_schema import EVENT_TYPE_CONCERN


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
        # subsequent probes. Without cleanup on the cold-load branch,
        # the sentinel persists indefinitely after first adopt and
        # survives in production despite the staleness-branch cleanup.
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

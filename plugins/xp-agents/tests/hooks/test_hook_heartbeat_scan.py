#!/usr/bin/env python3
"""The per-session heartbeat scan, tested as the primitive it now is.

`hook_heartbeat_scan` was extracted from `hook_liveness` so a second reader
could ask "is THAT session's runtime alive" without importing the verdict
machinery. Its callers' suites cover it end-to-end already; what they cannot
cover is the primitive's own contract at the boundaries — the window's two
ends, the three ways a sibling is unreadable, and the two files the reaping
glob must never match. Those are here.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import hook_heartbeat_scan
import hook_liveness
import marker_names
import markers
import session_markers
from _heartbeat_fixtures import env as _env
from conftest import _HookTestCase

NOW = 1_000_000.0


class _ScanTestCase(_HookTestCase):
    """Plants heartbeats through `markers` rather than `write_heartbeat`.

    The writer reaps as a side effect, which is one of the behaviours under
    test here — planting through it would make the fixture depend on the
    thing being measured.
    """

    def _plant(self, session_id: str, *, at: float = NOW) -> Path:
        marker = session_markers.session_marker(marker_names.HOOK_HEARTBEAT, session_id)
        markers.marker_write(
            self.smm_dir, marker, {"session_id": session_id, "written_at": at}
        )
        return markers.marker_path(self.smm_dir, marker)

    def _names(self) -> set[str]:
        return {p.name for p in Path(self.smm_dir).glob(".hook-heartbeat*")}


class TestWindowHasTwoEnds(unittest.TestCase):
    """`within_window` is the one home for the bounds, so the three scans
    that ask "is this heartbeat still good" cannot drift apart."""

    def test_unageable_is_not_evidence_of_freshness(self):
        self.assertFalse(hook_heartbeat_scan.within_window(None))

    def test_just_inside_the_stale_end_is_within(self):
        self.assertTrue(
            hook_heartbeat_scan.within_window(
                hook_heartbeat_scan.STALE_AFTER_SECONDS - 1
            )
        )

    def test_exactly_at_the_stale_end_is_out(self):
        self.assertFalse(
            hook_heartbeat_scan.within_window(hook_heartbeat_scan.STALE_AFTER_SECONDS)
        )

    def test_ordinary_clock_slew_is_still_within(self):
        """Refusing a working session is the failure that gets a liveness
        check switched off, so the future end is a tolerance, not zero."""
        self.assertTrue(
            hook_heartbeat_scan.within_window(
                -(hook_heartbeat_scan.FUTURE_SKEW_GRACE_SECONDS - 1)
            )
        )

    def test_beyond_the_skew_grace_is_out(self):
        """Unbounded at the far end, one wall-clock step backwards reads as
        fresh forever — the silent unenforcement the heartbeat exists to
        catch."""
        self.assertFalse(
            hook_heartbeat_scan.within_window(
                -(hook_heartbeat_scan.FUTURE_SKEW_GRACE_SECONDS + 1)
            )
        )


class TestSiblingAge(_ScanTestCase):
    """`sibling_age` returns None for every shape it cannot age. Callers
    must treat that as "cannot tell", never as young."""

    def test_a_planted_heartbeat_ages_against_now(self):
        path = self._plant("sess-a", at=NOW)
        self.assertEqual(
            hook_heartbeat_scan.sibling_age(self.smm_dir, path, NOW + 30), 30
        )

    def test_a_missing_file_is_unageable(self):
        path = Path(self.smm_dir) / ".hook-heartbeat-nothinghere"
        self.assertIsNone(hook_heartbeat_scan.sibling_age(self.smm_dir, path, NOW))

    def test_corrupt_json_is_unageable(self):
        path = self._plant("sess-a")
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(hook_heartbeat_scan.sibling_age(self.smm_dir, path, NOW))

    def test_a_non_numeric_timestamp_is_unageable(self):
        marker = session_markers.session_marker(marker_names.HOOK_HEARTBEAT, "sess-a")
        markers.marker_write(self.smm_dir, marker, {"written_at": "yesterday"})
        path = markers.marker_path(self.smm_dir, marker)
        self.assertIsNone(hook_heartbeat_scan.sibling_age(self.smm_dir, path, NOW))

    def test_a_symlinked_heartbeat_is_unageable(self):
        """The read goes back through `marker_read` so symlink rejection
        stays in the one place that owns it."""
        real = self._plant("sess-a")
        link = Path(self.smm_dir) / ".hook-heartbeat-linked"
        link.symlink_to(real)
        self.assertIsNone(hook_heartbeat_scan.sibling_age(self.smm_dir, link, NOW))


class TestReapStaleSiblings(_ScanTestCase):
    """Per-session files would otherwise accumulate one per session forever."""

    def test_an_expired_sibling_is_deleted(self):
        self._plant("ancient", at=NOW)
        keep = self._plant("current", at=NOW + hook_heartbeat_scan.STALE_AFTER_SECONDS)
        hook_heartbeat_scan.reap_stale_siblings(
            self.smm_dir, keep, NOW + hook_heartbeat_scan.STALE_AFTER_SECONDS
        )
        self.assertEqual(self._names(), {keep.name})

    def test_a_fresh_sibling_survives(self):
        """It belongs to a session that may still be running, and deleting
        it would make that session believe its own hooks had stopped."""
        other = self._plant("other", at=NOW)
        keep = self._plant("mine", at=NOW)
        hook_heartbeat_scan.reap_stale_siblings(self.smm_dir, keep, NOW + 60)
        self.assertEqual(self._names(), {other.name, keep.name})

    def test_the_kept_path_is_never_deleted_however_it_ages(self):
        keep = self._plant("mine", at=NOW)
        hook_heartbeat_scan.reap_stale_siblings(
            self.smm_dir, keep, NOW + 10 * hook_heartbeat_scan.STALE_AFTER_SECONDS
        )
        self.assertEqual(self._names(), {keep.name})

    def test_an_unreadable_sibling_is_reaped(self):
        """Unageable is not "leave it forever": a corrupt file would pin a
        name no session can refresh."""
        corrupt = self._plant("corrupt")
        corrupt.write_text("{not json", encoding="utf-8")
        keep = self._plant("mine", at=NOW)
        hook_heartbeat_scan.reap_stale_siblings(self.smm_dir, keep, NOW)
        self.assertEqual(self._names(), {keep.name})

    def test_a_symlinked_sibling_is_left_alone(self):
        real = self._plant("mine", at=NOW)
        link = Path(self.smm_dir) / ".hook-heartbeat-linked"
        link.symlink_to(real)
        hook_heartbeat_scan.reap_stale_siblings(self.smm_dir, real, NOW)
        self.assertTrue(link.is_symlink())

    def test_the_shared_unsuffixed_marker_is_never_reaped(self):
        """The glob deliberately does not match it: on a host that exposes no
        session id, that file is the only heartbeat anyone has."""
        shared = markers.marker_path(self.smm_dir, markers.HOOK_HEARTBEAT)
        markers.marker_write(self.smm_dir, markers.HOOK_HEARTBEAT, {"written_at": NOW})
        keep = self._plant("mine", at=NOW)
        hook_heartbeat_scan.reap_stale_siblings(
            self.smm_dir, keep, NOW + 10 * hook_heartbeat_scan.STALE_AFTER_SECONDS
        )
        self.assertTrue(shared.exists())

    def test_an_unlinkable_sibling_does_not_raise(self):
        """Best-effort: reaping runs from `write_heartbeat`, which every hook
        calls and none of which has a top-level guard."""
        self._plant("ancient", at=NOW)
        keep = self._plant("mine", at=NOW)
        with patch.object(Path, "unlink", side_effect=OSError("nope")):
            hook_heartbeat_scan.reap_stale_siblings(
                self.smm_dir, keep, NOW + 10 * hook_heartbeat_scan.STALE_AFTER_SECONDS
            )


class TestFreshestSibling(_ScanTestCase):
    """ "Is the runtime alive anywhere" — shared by two callers that must
    reach the same answer without sharing a verdict."""

    def test_nothing_planted_is_none(self):
        self.assertIsNone(hook_heartbeat_scan.freshest_sibling(self.smm_dir, NOW))

    def test_the_youngest_age_wins(self):
        self._plant("older", at=NOW - 600)
        self._plant("younger", at=NOW - 5)
        self.assertEqual(hook_heartbeat_scan.freshest_sibling(self.smm_dir, NOW), 5)

    def test_a_stale_sibling_is_not_freshness(self):
        self._plant("stale", at=NOW - hook_heartbeat_scan.STALE_AFTER_SECONDS)
        self.assertIsNone(hook_heartbeat_scan.freshest_sibling(self.smm_dir, NOW))

    def test_an_unreadable_sibling_is_not_freshness(self):
        corrupt = self._plant("corrupt")
        corrupt.write_text("{not json", encoding="utf-8")
        self.assertIsNone(hook_heartbeat_scan.freshest_sibling(self.smm_dir, NOW))

    def test_the_shared_unsuffixed_marker_is_not_a_sibling(self):
        """`check_liveness` reads that one directly; counting it here would
        let a session vouch for itself through the sibling path."""
        markers.marker_write(self.smm_dir, markers.HOOK_HEARTBEAT, {"written_at": NOW})
        self.assertIsNone(hook_heartbeat_scan.freshest_sibling(self.smm_dir, NOW))


class TestTheExtractionKeptOneHomeForTheBounds(_HookTestCase):
    """`hook_liveness` re-exports the window constants because callers and
    tests address them through that module. Two definitions that agreed by
    coincidence would be the drift the extraction must not introduce."""

    def test_the_stale_threshold_is_the_same_object(self):
        self.assertIs(
            hook_liveness.STALE_AFTER_SECONDS,
            hook_heartbeat_scan.STALE_AFTER_SECONDS,
        )

    def test_the_skew_grace_is_re_exported_rather_than_redefined(self):
        """Identity cannot answer this one, so provenance is asserted instead.

        60 sits inside CPython's small-int cache: two independently written
        literals ARE the same object, so an `assertIs` here would pass no
        matter where the value came from — a pin that can only pass, which is
        how the drift it guards against would ship. The claim is about the
        source of the value, so that is what the assertion reads.
        """
        source = Path(hook_liveness.__file__).read_text(encoding="utf-8")
        self.assertIn(
            "FUTURE_SKEW_GRACE_SECONDS = hook_heartbeat_scan.FUTURE_SKEW_GRACE_SECONDS",
            source,
        )
        self.assertEqual(
            hook_liveness.FUTURE_SKEW_GRACE_SECONDS,
            hook_heartbeat_scan.FUTURE_SKEW_GRACE_SECONDS,
        )

    def test_the_writer_still_reaps_through_the_extracted_scan(self):
        """The caller wiring, not just the primitive: `write_heartbeat` is
        the only production reaping trigger."""
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="ancient")):
            hook_liveness.write_heartbeat(self.smm_dir, now=NOW)
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="current")):
            hook_liveness.write_heartbeat(
                self.smm_dir, now=NOW + hook_heartbeat_scan.STALE_AFTER_SECONDS + 60
            )
        names = {p.name for p in Path(self.smm_dir).glob(".hook-heartbeat-*")}
        self.assertEqual(len(names), 1, names)


if __name__ == "__main__":
    unittest.main()

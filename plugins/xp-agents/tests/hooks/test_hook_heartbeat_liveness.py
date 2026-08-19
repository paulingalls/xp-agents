#!/usr/bin/env python3
"""Hook-liveness heartbeat: concurrent sessions, write safety, and the CLI.

Split from test_hook_heartbeat_marker.py, which holds the marker
definition and the staleness predicate.
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

import hook_liveness
import markers
from _heartbeat_fixtures import env as _env
from _heartbeat_fixtures import is_beating
from conftest import _HookTestCase


class TestConcurrentSessionsShareOneSmm(_HookTestCase):
    """The SMM is deliberately shared: spawners export SMM_DIR verbatim, and
    two windows on one repo hash the same git-common-dir to one project-id.

    A single marker keyed on one session id therefore has a last-writer-wins
    bug: every other live session reads a mismatch and is told the plugin is
    probably not loaded.
    """

    NOW = 1_000_000.0

    def _write_as(self, session_id: str, at: float) -> None:
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=session_id)):
            hook_liveness.write_heartbeat(self.smm_dir, now=at)

    def _beating(self, session_id: str, at: float):
        """Is this session beating, as the surviving consumers ask it.

        Was `check_liveness`, which answered about the process it ran in and
        is deleted with the rest of the verdict reader. The property these
        cases are about — each session addresses its OWN record in a shared
        SMM — is unchanged and is what `is_beating` asks.
        """
        return is_beating(self.smm_dir, session_id, now=at)

    def test_a_teammate_heartbeat_does_not_brick_the_lead(self):
        """The normal teammate flow: the lead is live, a teammate starts and
        refreshes the shared SMM, and the lead must stay live."""
        self._write_as("lead", self.NOW)
        self._write_as("teammate", self.NOW + 1)
        self.assertIs(self._beating("lead", self.NOW + 2), True)

    def test_each_session_reads_its_own_heartbeat(self):
        self._write_as("lead", self.NOW)
        self._write_as("teammate", self.NOW + 1)
        self.assertIs(self._beating("teammate", self.NOW + 2), True)

    def test_a_session_that_never_wrote_cannot_be_aged(self):
        """Hooks running elsewhere must not vouch for a session of its own.

        None, not False — there is no record of THIS session to age. The two
        surviving consumers both treat that as "cannot tell" and fall back,
        which is why the helper is three-valued.
        """
        self._write_as("other", self.NOW)
        self.assertIsNone(self._beating("mine", self.NOW + 1))

    def test_stale_sibling_heartbeats_are_reaped_on_write(self):
        """Per-session files must not accumulate forever."""
        self._write_as("ancient", self.NOW)
        self._write_as("current", self.NOW + hook_liveness.STALE_AFTER_SECONDS + 60)
        names = [p.name for p in Path(self.smm_dir).glob(".hook-heartbeat-*")]
        self.assertEqual(len(names), 1, names)

    def test_a_fresh_sibling_is_not_reaped(self):
        self._write_as("peer", self.NOW)
        self._write_as("me", self.NOW + 60)
        names = [p.name for p in Path(self.smm_dir).glob(".hook-heartbeat-*")]
        self.assertEqual(len(names), 2, names)

    def test_a_far_future_sibling_is_reaped_and_vouches_for_nobody(self):
        """A sibling dated far ahead is not evidence of a live runtime.

        Both sibling scans share one bounds helper for this: unreaped, a
        heartbeat dated years out never expires, so it would sit in the
        SESSION_GLOB forever and answer every "is the runtime alive anywhere"
        scan in the affirmative. No verdict can be reached through a sibling
        any more, but the reap and the bound still have to hold — the
        remaining sibling scan feeds the session-mismatch diagnosis.
        """
        self._write_as("clock-ahead", self.NOW + 10 * hook_liveness.STALE_AFTER_SECONDS)
        self._write_as("me", self.NOW)
        names = [p.name for p in Path(self.smm_dir).glob(".hook-heartbeat-*")]
        self.assertEqual(len(names), 1, names)

    def test_the_shared_no_id_marker_is_not_reaped_by_a_per_session_write(self):
        """The reap glob must never widen to `.hook-heartbeat*`.

        Same discipline the in-place locks keep against IN_PLACE_ACTIVE's
        glob: a marker caught by someone else's reap gets deleted as if it
        were theirs. The unsuffixed marker is the only heartbeat a host with
        no discoverable session id has, and no per-session writer owns it.
        """
        with patch.dict(os.environ, _env()):
            hook_liveness.write_heartbeat(self.smm_dir, now=self.NOW)
        self._write_as("someone", self.NOW + hook_liveness.STALE_AFTER_SECONDS + 60)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.HOOK_HEARTBEAT))

    def test_session_id_never_reaches_the_filename_raw(self):
        """A session id is untrusted input; it must not steer a path."""
        self._write_as("../../escape", self.NOW)
        written = list(Path(self.smm_dir).glob(".hook-heartbeat-*"))
        self.assertEqual(len(written), 1, written)
        self.assertNotIn("escape", written[0].name)
        self.assertNotIn("/", written[0].name.removeprefix(".hook-heartbeat-"))

    def test_the_raw_id_is_still_recorded_inside_the_payload(self):
        """Hashing the filename must not cost the diagnostic."""
        self._write_as("sess-readable", self.NOW)
        marker = hook_liveness.heartbeat_marker("sess-readable")
        data = markers.marker_read(self.smm_dir, marker)
        assert isinstance(data, dict)
        self.assertEqual(data["session_id"], "sess-readable")


class TestWriteHeartbeatNeverRaises(_HookTestCase):
    """Recording liveness must not break the hook whose liveness it records.

    `marker_write` rejects a symlinked marker with ValueError and a full or
    read-only SMM with OSError. The hooks that call this have no top-level
    guard, so it swallows — but logs, per `_common.append_safe`'s contract
    that a drop is never silent.
    """

    def test_symlinked_marker_does_not_raise(self):
        target = self.smm_dir / "planted.json"
        target.write_text("{}", encoding="utf-8")
        markers.marker_path(
            self.smm_dir, hook_liveness.heartbeat_marker("sess-a")
        ).symlink_to(target)
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-a")):
            hook_liveness.write_heartbeat(self.smm_dir)  # must not raise

    def test_unwritable_smm_dir_does_not_raise(self):
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-a")):
            hook_liveness.write_heartbeat(self.smm_dir / "no-such-dir")

    def test_the_drop_is_logged_not_silent(self):
        """A heartbeat that never lands reads downstream as 'hooks are not
        running'. That is a false alarm rather than a dangerous one — the
        trace is what tells the two apart."""
        target = self.smm_dir / "planted.json"
        target.write_text("{}", encoding="utf-8")
        markers.marker_path(
            self.smm_dir, hook_liveness.heartbeat_marker("sess-a")
        ).symlink_to(target)
        with (
            patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="sess-a")),
            patch("_common.log_hook_error") as logged,
        ):
            hook_liveness.write_heartbeat(self.smm_dir)
        logged.assert_called_once()
        self.assertIn("write_heartbeat", logged.call_args.args[0])


class TestSessionIdChain(_HookTestCase):
    """Adding a harness must be a data change, not a redesign."""

    def test_agreeing_candidates_resolve_to_the_one_id(self):
        """Supersedes an earlier `first candidate wins` pin.

        That pin set two candidates to DIFFERENT values and asserted the
        earlier one won. Preference no longer decides that case — disagreement
        refuses, because which variable a host owns is runtime state the
        environment does not record. Order now only picks among values that
        agree, where it cannot change the answer, so the observable rule is
        stated that way instead.
        """
        first, second = hook_liveness.SESSION_ID_ENV_CANDIDATES[:2]
        with patch.dict(os.environ, _env(**{first: "one", second: "one"})):
            self.assertEqual(hook_liveness.resolve_session_id(), "one")

    def test_falls_through_to_a_later_candidate(self):
        second = hook_liveness.SESSION_ID_ENV_CANDIDATES[1]
        with patch.dict(os.environ, _env(**{second: "two"})):
            self.assertEqual(hook_liveness.resolve_session_id(), "two")

    def test_empty_value_counts_as_absent(self):
        with patch.dict(os.environ, _env()):
            self.assertIsNone(hook_liveness.resolve_session_id())


if __name__ == "__main__":
    unittest.main()

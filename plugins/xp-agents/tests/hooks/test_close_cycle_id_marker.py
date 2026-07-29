#!/usr/bin/env python3
"""The close-cycle id marker itself: its descriptor, its sweep, its consume.

The merge gate counts open high-severity concerns before letting a close
merge. Scoping that count to ONE close cycle used to be inferred from the
`files` a concern recorded — a planner-supplied list, so a stale path
silently produced a wrong EXCLUSION from the gate whose whole purpose is
not to miss a high-severity concern. This marker replaces the inference:
the close that is running writes its own id.

The property pinned here is **session scoping**. The SMM dir is shared across
worktrees, so one unscoped file is last-writer-wins — which both hides the
first close's concerns and tags a bystander's concern into a close it has
nothing to do with. That is worse than the inference it replaces.

The stamp this marker feeds — and every fail-closed branch of it — is pinned
in `test_close_cycle_id_stamp.py`, which drives the real appender CLI.
"""

import hashlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import hook_liveness
import marker_names
import markers
import session_markers
import session_scope
from _heartbeat_fixtures import env as no_session_env
from conftest import _MARKERS_PY, _HookTestCase, run_cli

# A 12-hex id of the shape generate_id() mints (secrets.token_hex(6)).
_CYCLE = "aaaa11112222"
_OTHER_CYCLE = "bbbb33334444"


def _suffix_for(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


class TestMarkerDefinition(unittest.TestCase):
    """The descriptor itself: text content, and a name one session owns."""

    def test_marker_name_comes_from_marker_names(self) -> None:
        """`smm/marker_names.py` is the only home a filename may have — it is
        the module the appender's pre-write path can reach without importing
        `scripts/`."""
        self.assertEqual(markers.CLOSE_CYCLE_ID.name, marker_names.CLOSE_CYCLE_ID)

    def test_marker_holds_text_not_json(self) -> None:
        """The id is the whole content, and `write_marker` (the shell wrapper
        every close preload uses) passes a string — a json marker would raise
        TypeError inside a `2>/dev/null || true` wrapper and vanish."""
        self.assertEqual(markers.CLOSE_CYCLE_ID.content_type, "text")

    def test_marker_is_session_scoped(self) -> None:
        self.assertTrue(markers.CLOSE_CYCLE_ID.session_scoped)

    def test_filename_carries_the_session_digest(self) -> None:
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-a")):
            self.assertEqual(
                markers.CLOSE_CYCLE_ID.filename(),
                f"{marker_names.CLOSE_CYCLE_ID}-{_suffix_for('sess-a')}",
            )

    def test_two_sessions_get_two_files(self) -> None:
        """The concurrency property: two closes in two worktrees are two
        sessions, and neither may read or clobber the other's id."""
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-a")):
            first = markers.CLOSE_CYCLE_ID.filename()
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-b")):
            second = markers.CLOSE_CYCLE_ID.filename()
        self.assertNotEqual(first, second)

    def test_a_session_id_never_reaches_the_filename(self) -> None:
        """A session id is untrusted input that would otherwise steer a path,
        so it is hashed rather than escaped — the same rule the heartbeat and
        the housekeeping record use."""
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="../../etc/passwd\n")):
            self.assertRegex(
                markers.CLOSE_CYCLE_ID.filename(),
                rf"^{marker_names.CLOSE_CYCLE_ID}-[0-9a-f]{{12}}$",
            )

    def test_no_discoverable_session_id_falls_back_to_the_shared_name(self) -> None:
        """Same degradation `session_markers.session_marker` documents: a host
        exposing no id gets the unsuffixed marker rather than a file keyed on
        the hash of a value no reader addresses."""
        with patch.dict(os.environ, no_session_env()):
            self.assertEqual(
                markers.CLOSE_CYCLE_ID.filename(), marker_names.CLOSE_CYCLE_ID
            )

    def test_scoping_is_the_session_marker_rule_itself(self) -> None:
        """Not "the same shape" — the same code. `session_markers.session_marker`
        builds on `session_scope.scoped_name`, so the hashing rule cannot drift
        between the heartbeat's marker and this one."""
        for session_id in ("sess-a", "", None, "  "):
            with self.subTest(session_id=session_id):
                self.assertEqual(
                    session_markers.session_marker(".m", session_id).name,
                    session_scope.scoped_name(".m", session_id),
                )

    def test_env_candidate_chain_has_one_home(self) -> None:
        """The appender's pre-write path cannot import `scripts/`, so the chain
        lives in `smm/session_scope.py` and hook_liveness reads it from there.
        Two copies would let a new host var be taught to the heartbeat while
        this marker silently degraded to the shared name."""
        self.assertIs(
            hook_liveness.SESSION_ID_ENV_CANDIDATES,
            session_scope.SESSION_ID_ENV_CANDIDATES,
        )


class TestSessionStartSweep(_HookTestCase):
    """A stale id must never outlive its session.

    An id left behind would tag later concerns with a dead close, and because
    the next close mints a DIFFERENT id the gate would then exclude them — a
    fresh fail-open worse than the inference this story removed.
    """

    def test_marker_is_in_the_stale_session_set(self) -> None:
        self.assertIn(markers.CLOSE_CYCLE_ID, session_markers._STALE_SESSION_MARKERS)

    def test_sweep_clears_this_sessions_marker(self) -> None:
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-a")):
            markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
            session_markers.sweep_stale_session_markers(self.smm_dir)
            self.assertFalse(
                markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ID)
            )

    def test_sweep_clears_the_shared_no_id_marker(self) -> None:
        """The leg that actually leaks: with no discoverable session id both the
        old and the new session address the SAME file, so scoping cannot
        separate them and only the sweep can."""
        with patch.dict(os.environ, no_session_env()):
            markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
            session_markers.sweep_stale_session_markers(self.smm_dir)
            self.assertFalse(
                markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ID)
            )

    def test_sweep_leaves_another_sessions_marker_alone(self) -> None:
        """Unlike every other marker in that set, this one CAN belong to a live
        session: a teammate's close in another worktree against the shared SMM.
        Consuming it would untag that close's concerns mid-flight."""
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-other")):
            markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _OTHER_CYCLE)
            other = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID)
        with patch.dict(os.environ, no_session_env(XP_SESSION_ID="sess-mine")):
            session_markers.sweep_stale_session_markers(self.smm_dir)
        self.assertTrue(other.is_file())


class TestMarkerCli(_HookTestCase):
    """The close pipeline's consume step drives the marker through this CLI."""

    def test_marker_is_cli_allowlisted(self) -> None:
        self.assertIn("CLOSE_CYCLE_ID", markers._CLI_ALLOWLIST)

    def test_cli_consume_removes_this_sessions_marker(self) -> None:
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ID, _CYCLE)
        path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID)
        self.assertTrue(path.is_file())
        result = run_cli(_MARKERS_PY, ["consume", "CLOSE_CYCLE_ID"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(path.is_file())

    def test_cli_refuses_to_write_an_empty_id(self) -> None:
        """The CLI's `write` carries no content, and an EMPTY id is worse than
        no marker: the appender's reader then reports a present-but-unusable
        marker on stderr for EVERY concern for the rest of the session — the
        loud line reserved for an armed-but-broken close, fired continuously
        until the operator learns to ignore it. The preloads write this marker
        through the shell helper that can carry the id; the CLI drives the
        consume only, so it must refuse the write rather than arm that noise.
        """
        result = run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ID"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(
            markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ID).exists()
        )

    def test_cli_still_writes_the_markers_a_preload_arms_this_way(self) -> None:
        """Non-vacuity: the refusal is per-marker, not a disabled `write`."""
        result = run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE).exists()
        )

    def test_cli_consume_of_an_absent_marker_is_quiet(self) -> None:
        """The consume runs on both the merge and the abort path, and may run
        twice — it must never turn a finished close into an error."""
        result = run_cli(_MARKERS_PY, ["consume", "CLOSE_CYCLE_ID"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

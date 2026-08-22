#!/usr/bin/env python3
"""In-place-teammate flavor of the TDD gate's session-scoping (story-003).

Split out of test_tdd_gate_session_scope.py when the collapse pins pushed that
file past the project's 500-line cap (a cohesive extraction, not a chronology
split — every test here is about the ENV+MARKER leg an in-place teammate is
detected through, `tdd_check._reader_scope`'s mirror of
`identity.is_worktree_teammate`'s own env leg). Both now delegate to the same
shared `identity.in_place_teammate_name` helper (story-003 dedup).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import tdd_check
import worktree
from _heartbeat_fixtures import coordinate
from _tdd_gate_fixtures import _GateTestCase, filler, session_anchor
from conftest import failing_tests_concern

_IN_PLACE_NAME = "worktree-story-042"
_LEAD_CWD = "/Users/dev/xp-agents"


def _in_place_env_patch(smm_dir: Path, name: str = _IN_PLACE_NAME):
    """The env an in-place teammate's hook process runs under.

    Module-level so both classes below share ONE spelling of it — the same
    duplicate-rule hazard story-011's review flagged for `_resolve`.
    """
    return patch.dict(
        os.environ,
        {"XP_TEAMMATE_NAME": name, "SMM_DIR": str(smm_dir)},
        clear=False,
    )


class TestInPlaceTeammateReaderWindow(_GateTestCase):
    """concern bc32dcfe6905: an IN-PLACE teammate (solo behavior-table branch
    of xp-assign; `spawn_teammate --in-place`) runs in the MAIN checkout, so
    it carries no `worktree-story-` cwd marker for `extract_worktree_name` to
    key on. Detection therefore falls through to the ENV + MARKER leg —
    `XP_TEAMMATE_NAME` guarded by a live in-place marker under `smm_dir`,
    mirroring `identity.is_worktree_teammate`'s own env leg — and
    deliberately NEVER that function's process-cwd fallback (a documented
    leak `_reader_scope` already avoids for the cwd leg). Without this leg an
    in-place teammate fell through to the LEAD branch and read the lead's
    `session_started` anchor as its own window: exactly the shared-log/
    owner-filter hazard the owner mechanism exists to prevent for worktree
    teammates, now reproduced for the in-place shape.
    """

    def _in_place_env(self):
        return _in_place_env_patch(self.smm_dir)

    def test_own_failure_before_lead_clear_anchor_still_blocks(self):
        """Mirrors TestTeammateReaderWindow's worktree-teammate AC1, in-place
        flavor. The failure predates the lead's mid-sprint `/clear` anchor and
        the tree is clean (already committed) — the combination that would
        un-gate under the LEAD's anchor-relative window. An in-place teammate
        has no prior session either, so this must still block."""
        worktree.in_place_marker_path(self.smm_dir, _IN_PLACE_NAME).touch()
        events = [
            failing_tests_concern(agent_id=_IN_PLACE_NAME),
            session_anchor(),
            *filler(3),
        ]
        with self._in_place_env():
            result = self._stop(events, cwd=_LEAD_CWD, dirty=False)
        self.assertIsNotNone(result)
        self.assertIn("failing", str(result).lower())

    def test_foreign_fail_concern_does_not_block_the_in_place_teammate(self):
        """Owner scoping, in-place flavor: a fail concern authored by the lead
        (shared log) must not gate an in-place teammate that can neither see
        nor fix it."""
        worktree.in_place_marker_path(self.smm_dir, _IN_PLACE_NAME).touch()
        events = [failing_tests_concern(agent_id="main"), *filler(3)]
        with self._in_place_env():
            result = self._stop(events, cwd=_LEAD_CWD, dirty=False)
        self.assertIsNone(result)

    def test_own_failure_still_blocks_the_in_place_teammate(self):
        """Control for the test above: its OWN unresolved failure still
        gates it — the narrowing must not also disarm the common case."""
        worktree.in_place_marker_path(self.smm_dir, _IN_PLACE_NAME).touch()
        events = [failing_tests_concern(agent_id=_IN_PLACE_NAME), *filler(3)]
        with self._in_place_env():
            result = self._stop(events, cwd=_LEAD_CWD, dirty=False)
        self.assertIsNotNone(result)

    def test_env_var_without_a_live_marker_falls_back_to_the_lead_window(self):
        """A leaked `XP_TEAMMATE_NAME` with no live marker must not be
        trusted (mirrors identity's own env+marker guard). If it were
        wrongly treated as an in-place teammate, the owner filter would hide
        the LEAD's own in-session failure below; instead it must still
        block, as the lead, which drops only story-worktree authors."""
        events = [session_anchor(), *filler(3), failing_tests_concern(agent_id="main")]
        with patch.dict(
            os.environ,
            {"XP_TEAMMATE_NAME": _IN_PLACE_NAME, "SMM_DIR": str(self.smm_dir)},
            clear=False,
        ):
            result = self._stop(events, cwd=_LEAD_CWD, dirty=False)
        self.assertIsNotNone(result)


class TestInPlaceTeammateIsNotReleasedByCoordination(_GateTestCase):
    """AC-3: the in-place leg of the gate's coordination release.

    By the time the release is considered, `find_last_test_signal` has already
    scoped the read — and an in-place teammate IS scoped, to its own
    `XP_TEAMMATE_NAME`. So a failure that reaches here is provably its own, and
    releasing it because some other agent has a coordination entry abandons a
    red suite it owns. Only the lead, which reads unscoped, can be looking at
    someone else's failure.
    """

    def _coordinate(self, *agent_ids: str) -> None:
        coordinate(self.smm_dir, *agent_ids)

    def test_own_failure_blocks_even_with_another_agent_active(self):
        """The AC. Releases before the owner guard: with `agent_id` absent the
        in-place teammate resolves to `main` (its cwd is the main checkout), a
        foreign entry is present, so `has_active_teammates` said yes."""
        worktree.in_place_marker_path(self.smm_dir, _IN_PLACE_NAME).touch()
        self._coordinate("main", "worktree-story-007")
        events = [failing_tests_concern(agent_id=_IN_PLACE_NAME), *filler(3)]
        with _in_place_env_patch(self.smm_dir):
            result = self._stop(events, cwd=_LEAD_CWD, dirty=False, agent_id=None)
        self.assertIsNotNone(result)

    def test_it_resolves_to_the_key_post_tool_use_writes(self):
        """The stated resolution, pinned rather than left as prose. An in-place
        teammate's cwd is the main checkout, so `resolve_agent_id` answers
        `main` — the SAME key `post_tool_use` writes its coordination entry
        under. Resolving it to `XP_TEAMMATE_NAME` here instead would compare
        against a key space nothing writes, re-opening the fail-open from the
        other side."""
        import identity

        with _in_place_env_patch(self.smm_dir):
            self.assertEqual(
                identity.resolve_agent_id({"session_id": "t", "cwd": _LEAD_CWD}),
                "main",
            )

    def test_the_lead_in_the_same_env_is_still_released(self):
        """Over-arming control. A leaked `XP_TEAMMATE_NAME` with NO live marker
        is the lead, and the lead must keep its release — otherwise "never
        release" would satisfy the block above while quietly deleting the
        behaviour the gate is supposed to have."""
        self._coordinate("main", "worktree-story-007")
        events = [session_anchor(), *filler(3), failing_tests_concern(agent_id="main")]
        with _in_place_env_patch(self.smm_dir):
            result = self._stop(events, cwd=_LEAD_CWD, dirty=False, agent_id=None)
        self.assertIsNone(result)


class TestReaderScopeSharedResolver(_GateTestCase):
    """story-003: `_reader_scope`'s env leg now delegates to
    `identity.in_place_teammate_name` — the same helper `is_worktree_teammate`
    uses — instead of hand-rolling the `SMM_DIR` env read. These pin the
    env-fallback, fail-closed (no init.sh derivation), and zero-cost behaviors
    directly against `_reader_scope` with `smm_dir=None`, the shape any caller
    that omits the param gets (the hook callers thread their validated dir
    instead)."""

    def test_no_param_no_env_fails_closed_to_lead_without_deriving(self):
        """Finding #6 / story-003 fail-closed: no smm_dir param, no SMM_DIR env
        — `_reader_scope`'s env leg must NOT derive the real shared SMM via
        init.sh (a live marker there for a LEAKED name would misread the lead
        as an in-place teammate and hide the lead's own in-session failures).
        It falls back to the lead branch WITHOUT resolving, even with a live
        marker in the (would-be-derived) shared SMM."""
        worktree.claim_in_place_marker(self.smm_dir, _IN_PLACE_NAME)
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _IN_PLACE_NAME}, clear=False):
            os.environ.pop("SMM_DIR", None)
            with patch.object(_common, "resolve_smm_dir") as mock_resolve:
                result = tdd_check._reader_scope([session_anchor()], _LEAD_CWD)
            mock_resolve.assert_not_called()
        self.assertEqual(result, (0, None))

    def test_leaked_env_with_explicit_dir_but_no_live_marker_reads_as_lead(self):
        """A leaked env with an explicit resolvable dir but NO live marker still
        reads as the lead — the marker is checkABLE, never skippable."""
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _IN_PLACE_NAME}, clear=False):
            os.environ.pop("SMM_DIR", None)
            window_start, owner = tdd_check._reader_scope(
                [session_anchor()], _LEAD_CWD, smm_dir=self.smm_dir
            )
        self.assertIsNone(owner)
        self.assertEqual(window_start, 0)

    def test_unresolvable_smm_dir_falls_back_to_lead_window(self):
        """AC3: get_validated_smm_dir returning None must never reach
        in_place_teammate_from_env; falls back to the lead branch."""
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": _IN_PLACE_NAME}, clear=False):
            os.environ.pop("SMM_DIR", None)
            with patch.object(_common, "get_validated_smm_dir", return_value=None):
                with patch("worktree.in_place_teammate_from_env") as mock_marker:
                    _, owner = tdd_check._reader_scope([session_anchor()], _LEAD_CWD)
                mock_marker.assert_not_called()
        self.assertIsNone(owner)

    def test_caller_supplied_dir_wins_over_the_env_for_the_marker_read(self):
        """The gate must evaluate identity against the SAME SMM it read the
        log from: `tdd_stop_gate.run` threads its validated `smm_dir` down, so
        a `SMM_DIR` env pointing at a DIFFERENT dir cannot redirect half the
        read. Here the marker is live only under the env dir — ignoring the
        caller's dir would grant the reader an owner filter that hides this
        lead-authored failure, un-gating a red suite (the disarm direction)."""
        with tempfile.TemporaryDirectory() as other:
            worktree.in_place_marker_path(Path(other), _IN_PLACE_NAME).touch()
            events = [failing_tests_concern(agent_id="main"), *filler(3)]
            with patch.dict(
                os.environ,
                {"XP_TEAMMATE_NAME": _IN_PLACE_NAME, "SMM_DIR": other},
                clear=False,
            ):
                result = self._stop(events, cwd=_LEAD_CWD, dirty=False)
        self.assertIsNotNone(result)

    def test_process_cwd_inside_a_worktree_still_reads_as_the_lead(self):
        """The shared helper carries no cwd leg, so `_reader_scope` still keys
        on the hook-supplied `cwd` ALONE — deliberately unlike
        `is_worktree_teammate`'s `os.getcwd()` fallback. conftest pins
        `identity._process_cwd` to '' globally, so opt back in here: a process
        cwd inside a worktree must NOT turn a lead payload into a teammate
        read, which would hide the lead's own signals behind an owner filter."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_NAME", None)
            os.environ.pop("SMM_DIR", None)
            with patch(
                "identity._process_cwd",
                return_value=f"/tmp/wt/{_IN_PLACE_NAME}",
            ):
                _, owner = tdd_check._reader_scope([session_anchor()], _LEAD_CWD)
        self.assertIsNone(owner)

    def test_no_env_var_never_resolves_smm_dir(self):
        """AC4: with no XP_TEAMMATE_NAME, the lead's hot path pays no
        subprocess — pinned via call count, not vacuously."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_NAME", None)
            os.environ.pop("SMM_DIR", None)
            with patch.object(_common, "get_validated_smm_dir") as mock_resolve:
                tdd_check._reader_scope([session_anchor()], _LEAD_CWD)
            mock_resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()

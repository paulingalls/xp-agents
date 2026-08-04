#!/usr/bin/env python3
"""Hook-liveness heartbeat: concurrent sessions, write safety, and the CLI.

Split from test_hook_heartbeat_marker.py, which holds the marker
definition and the staleness predicate.
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import hook_liveness
import markers
import session_scope
from _heartbeat_fixtures import HOOK_LIVENESS_PY as _HOOK_LIVENESS_PY
from _heartbeat_fixtures import env as _env
from conftest import _HookTestCase, run_cli


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

    def _check_as(self, session_id: str, at: float) -> hook_liveness.Liveness:
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=session_id)):
            return hook_liveness.check_liveness(self.smm_dir, now=at)

    def test_a_teammate_heartbeat_does_not_brick_the_lead(self):
        """The normal teammate flow: the lead is live, a teammate starts and
        refreshes the shared SMM, and the lead must stay live."""
        self._write_as("lead", self.NOW)
        self._write_as("teammate", self.NOW + 1)
        result = self._check_as("lead", self.NOW + 2)
        self.assertTrue(result.live, result.reason)

    def test_each_session_reads_its_own_heartbeat(self):
        self._write_as("lead", self.NOW)
        self._write_as("teammate", self.NOW + 1)
        self.assertTrue(self._check_as("teammate", self.NOW + 2).live)

    def test_a_session_that_never_wrote_is_not_live(self):
        """Hooks running elsewhere must not vouch for a session of its own."""
        self._write_as("other", self.NOW)
        result = self._check_as("mine", self.NOW + 1)
        self.assertFalse(result.live)

    def test_hooks_alive_elsewhere_is_a_distinct_diagnosis(self):
        """'Nothing has ever run' and 'running, but not for you' are
        different problems and must not share a message."""
        nothing = self._check_as("mine", self.NOW)
        self._write_as("other", self.NOW)
        elsewhere = self._check_as("mine", self.NOW + 1)
        self.assertFalse(elsewhere.live)
        self.assertNotEqual(nothing.code, elsewhere.code)
        self.assertNotEqual(nothing.reason, elsewhere.reason)

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

        Both sibling scans share one bounds helper for this: unreaped it would
        accumulate forever, and worse, a session with no discoverable id would
        borrow it as "live on freshness alone" permanently.
        """
        self._write_as("clock-ahead", self.NOW + 10 * hook_liveness.STALE_AFTER_SECONDS)
        with patch.dict(os.environ, _env()):
            borrowed = hook_liveness.check_liveness(self.smm_dir, now=self.NOW)
        self.assertFalse(borrowed.live, borrowed.reason)

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

    def test_no_discoverable_id_accepts_another_session_s_fresh_heartbeat(self):
        """The documented degradation, pinned rather than left to prose.

        A host exposing no session id cannot name its own heartbeat, and a
        hook handed an id in its payload writes a per-session file such a
        reader can never address. Time-only therefore means ANY fresh
        heartbeat counts — demanding the shared marker would refuse a session
        whose hooks are demonstrably running.
        """
        self._write_as("some-other-session", self.NOW)
        with patch.dict(os.environ, _env()):
            result = hook_liveness.check_liveness(self.smm_dir, now=self.NOW + 60)
        self.assertTrue(result.live, result.reason)
        self.assertIn("no session id", result.reason)

    def test_no_discoverable_id_still_refuses_when_every_heartbeat_is_stale(self):
        """The fail-closed half of that degradation."""
        self._write_as("some-other-session", self.NOW)
        with patch.dict(os.environ, _env()):
            result = hook_liveness.check_liveness(
                self.smm_dir, now=self.NOW + hook_liveness.STALE_AFTER_SECONDS
            )
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_NO_MARKER)

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


class TestDisagreeingSessionIdsRefuse(_HookTestCase):
    """A nested launch leaves two ids set, and picking wrong INVERTS the check.

    Hooks key their heartbeat on the id the host handed them, so resolving the
    inherited id addresses the LAUNCHER's heartbeat instead of this session's.
    """

    NOW = 2_000_000.0

    def _conflicted(self):
        return _env(
            CODEX_THREAD_ID="this-hosts-own-id",
            CLAUDE_CODE_SESSION_ID="an-id-from-the-launcher",
        )

    def test_a_launchers_fresh_heartbeat_does_not_read_as_live(self):
        """The regression this class exists for.

        Every not-live path treats an unresolvable id as "degrade to time-only,
        any fresh heartbeat counts" — correct when NO id is discoverable, and a
        fail-open here: under a conflict the launcher's heartbeat is fresh by
        definition, so degrading would vouch for a session whose own hooks never
        loaded. The conflict verdict must therefore precede that degradation.
        """
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID="the-launcher")):
            hook_liveness.write_heartbeat(self.smm_dir, now=self.NOW)

        with patch.dict(os.environ, self._conflicted()):
            result = hook_liveness.check_liveness(self.smm_dir, now=self.NOW + 1)

        self.assertFalse(
            result.live,
            "a conflict must not borrow the launcher's freshness: "
            f"got live with reason {result.reason!r}",
        )
        self.assertEqual(result.code, hook_liveness.CODE_ID_CONFLICT)

    def test_the_refusal_names_both_variables_and_the_way_out(self):
        with patch.dict(os.environ, self._conflicted()):
            result = hook_liveness.check_liveness(self.smm_dir, now=self.NOW)
        for expected in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "XP_SESSION_ID"):
            with self.subTest(names=expected):
                self.assertIn(expected, result.reason)
        self.assertIn(
            "Unset",
            result.reason,
            "naming the variables is half the message: the remedy is "
            "SUBTRACTIVE, and this is the only banner the operator sees",
        )

    def test_the_remedy_the_refusal_prescribes_actually_settles_it(self):
        """A refusal that prescribes an inert step is worse than a terse one.

        Every candidate counts toward the disagreement, XP_SESSION_ID included,
        so `export XP_SESSION_ID=<the real id>` leaves the conflict standing —
        and now blames the variable the operator just set. Following the prose
        must reach a verdict, so the prose is checked against the code that
        judges it rather than reviewed by eye.
        """
        settled = self._conflicted()
        settled["CLAUDE_CODE_SESSION_ID"] = ""  # the inherited one, unset
        with patch.dict(os.environ, settled):
            self.assertEqual(session_scope.conflicting_session_ids(), ())
            self.assertEqual(hook_liveness.resolve_session_id(), "this-hosts-own-id")

        added = {**self._conflicted(), "XP_SESSION_ID": "this-hosts-own-id"}
        with patch.dict(os.environ, added):
            self.assertEqual(
                session_scope.conflicting_session_ids(),
                ("XP_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID"),
                "exporting a third id must NOT be described as a tie-break: it "
                "is one more disagreeing candidate",
            )
            self.assertIsNone(hook_liveness.resolve_session_id())

    def test_a_conflict_is_undetermined_not_determined_not_live(self):
        """Nothing was learned about the runtime, only that identity is unclear."""
        self.assertIn(hook_liveness.CODE_ID_CONFLICT, hook_liveness.UNDETERMINED_CODES)


class TestStatusCLI(_HookTestCase):
    """A shell caller with only the SMM directory must get a usable answer
    without importing any of this module's internals.

    Unlike the cadence CLI, which fail-SAFEs, this one fails CLOSED: every
    path that is not a positive liveness verdict exits non-zero.
    """

    HOST_VAR = "CLAUDE_CODE_SESSION_ID"

    def _run(self, session_id: str = ""):
        return run_cli(
            _HOOK_LIVENESS_PY,
            ["status"],
            self.smm_dir,
            extra_env=_env(**{self.HOST_VAR: session_id}),
        )

    def _plant(self, session_id: str, age: float = 0.0) -> None:
        with patch.dict(os.environ, _env(**{self.HOST_VAR: session_id})):
            hook_liveness.write_heartbeat(self.smm_dir, now=time.time() - age)

    def test_live_exits_zero(self):
        self._plant("sess-a")
        result = self._run("sess-a")
        self.assertEqual(result.returncode, hook_liveness.EXIT_LIVE, result.stdout)

    def test_absent_marker_exits_determined_not_live(self):
        result = self._run("sess-a")
        self.assertEqual(result.returncode, hook_liveness.EXIT_NOT_LIVE)
        self.assertIn("not loaded", result.stdout)

    def test_session_mismatch_exits_determined_not_live(self):
        self._plant("sess-old")
        result = self._run("sess-new")
        self.assertEqual(result.returncode, hook_liveness.EXIT_NOT_LIVE)
        self.assertIn("another session", result.stdout)

    def test_stale_exits_determined_not_live(self):
        self._plant("sess-a", age=hook_liveness.STALE_AFTER_SECONDS + 60)
        result = self._run("sess-a")
        self.assertEqual(result.returncode, hook_liveness.EXIT_NOT_LIVE)
        self.assertIn("stopped", result.stdout)

    def test_unreadable_exits_could_not_determine(self):
        markers.marker_path(
            self.smm_dir, hook_liveness.heartbeat_marker("sess-a")
        ).write_text("{not json", encoding="utf-8")
        result = self._run("sess-a")
        self.assertEqual(result.returncode, hook_liveness.EXIT_UNDETERMINED)
        self.assertIn("cannot be determined", result.stdout)

    def test_the_two_refusal_classes_have_different_exit_codes(self):
        self.assertNotEqual(
            hook_liveness.EXIT_NOT_LIVE, hook_liveness.EXIT_UNDETERMINED
        )
        self.assertNotEqual(hook_liveness.EXIT_LIVE, hook_liveness.EXIT_NOT_LIVE)

    def test_undetermined_does_not_collide_with_the_usage_error_code(self):
        """argparse exits 2 on a bad invocation; that must not read as a
        liveness verdict."""
        usage = run_cli(_HOOK_LIVENESS_PY, ["bogus-subcommand"], self.smm_dir)
        self.assertEqual(usage.returncode, 2)
        self.assertNotIn(
            usage.returncode,
            {hook_liveness.EXIT_LIVE, hook_liveness.EXIT_UNDETERMINED},
        )

    def test_each_not_live_case_prints_a_distinct_reason(self):
        absent = self._run("sess-a").stdout
        self._plant("sess-old")
        mismatch = self._run("sess-new").stdout
        self._plant("sess-a", age=hook_liveness.STALE_AFTER_SECONDS + 60)
        stale = self._run("sess-a").stdout
        printed = [absent, mismatch, stale]
        self.assertEqual(len(set(printed)), len(printed), printed)
        self.assertTrue(all(p.strip() for p in printed))


if __name__ == "__main__":
    unittest.main()

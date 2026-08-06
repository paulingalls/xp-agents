#!/usr/bin/env python3
"""The work-selection preload arms the housekeeping gate ONCE per session.

The gate marker is armed by this preload and CONSUMED by the housekeeper's
SubagentStop handler. That consume is why a naive not-already-armed check cannot
work: once curation completes, "already curated this session" and "never armed"
are the SAME observation on disk, so such a check re-arms in exactly the broken
case. Running work-selection standalone therefore demanded a second curation of
an SMM that had just been curated.

The fix is a second, session-scoped record that nothing consumes — the one
residue that tells the two states apart.

Both directions are pinned, from the same harness, because either alone converts
this bug into its mirror: a "does not re-arm" test passes equally if arming were
deleted outright, and an "arms" test passes equally if the guard were never
added.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import marker_names
import session_scope
from conftest import _PLUGIN_ROOT, _IntegrationTestCase

_WORK_SELECTION_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-work-selection" / "scripts" / "preload.sh"
)

# Two distinct sessions against ONE shared SMM dir — which is the real shape:
# the SMM is shared across worktrees and windows, so the arming record has to be
# session-scoped rather than one file per SMM.
_SESSION_A = "story-016-session-a"
_SESSION_B = "story-016-session-b"


class TestWorkSelectionArmsHousekeepingOncePerSession(_IntegrationTestCase):
    def _run(self, session_id: str) -> subprocess.CompletedProcess:
        """Drive the REAL preload, with the session id the marker scopes on.

        `XP_SESSION_ID` is pinned suite-wide by `_env_hygiene`; overriding it per
        run is how one process stands in for two sessions. Production never sets
        it — it is a candidate the host provides, not an override.
        """
        result = self._run_preload(
            _WORK_SELECTION_PRELOAD, extra_env={"XP_SESSION_ID": session_id}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _gate(self) -> Path:
        """The housekeeping gate marker, at its UNSUFFIXED name.

        Its readers (the Stop gate, the housekeeper's SubagentStop consume)
        resolve the bare name, so the gate itself must not become
        session-scoped — only the record of having armed it.
        """
        return self.smm_dir / marker_names.NEEDS_HOUSEKEEPING

    def _armed_record(self, session_id: str) -> Path:
        return self.smm_dir / session_scope.scoped_name(
            marker_names.HOUSEKEEPING_ARMED, session_id
        )

    def _consume_gate(self) -> None:
        """What the housekeeper's SubagentStop handler does on a finalized run.

        The single fact that makes this bug possible: after this, the gate marker
        is absent for the same reason it is absent in a brand-new session.
        """
        self._gate().unlink()

    def test_a_fresh_session_arms_the_gate(self):
        self._run(_SESSION_A)

        self.assertTrue(
            self._gate().is_file(), "kickoff's housekeeping gate never armed"
        )
        self.assertTrue(
            self._armed_record(_SESSION_A).is_file(),
            "armed without recording that it armed — the next run cannot tell",
        )

    def test_a_second_run_after_curation_does_not_rearm(self):
        """AC-4, and the discriminating case: the gate has been armed AND
        consumed. A check against the gate marker alone sees nothing and re-arms;
        only the residue distinguishes this from a new session."""
        self._run(_SESSION_A)
        self._consume_gate()

        self._run(_SESSION_A)

        self.assertFalse(
            self._gate().is_file(),
            "re-armed a gate already curated this session — a second curation "
            "would be demanded of an SMM that was just curated",
        )

    def test_a_second_run_before_curation_leaves_the_gate_armed(self):
        """The other same-session shape: curation has NOT happened yet. Not
        re-arming must not mean disarming — the gate is still owed."""
        self._run(_SESSION_A)

        self._run(_SESSION_A)

        self.assertTrue(
            self._gate().is_file(),
            "an un-curated gate was dropped by a second work-selection run",
        )

    def test_a_new_session_arms_again(self):
        """AC-5, the mirror direction. Same SMM, same consumed gate, different
        session — this one is owed a curation and must get one.

        Without this, "does not re-arm" is satisfied by never arming at all.
        """
        self._run(_SESSION_A)
        self._consume_gate()

        self._run(_SESSION_B)

        self.assertTrue(
            self._gate().is_file(),
            "a new session was not offered a curation because a PREVIOUS "
            "session's arming record suppressed it",
        )
        self.assertTrue(self._armed_record(_SESSION_B).is_file())

    def test_the_arming_record_is_scoped_per_session(self):
        """The mechanism behind the test above, asserted directly: two sessions
        sharing one SMM dir must not share one record. A single unsuffixed file
        would be last-writer-wins between concurrent windows."""
        self._run(_SESSION_A)
        self._consume_gate()
        self._run(_SESSION_B)

        self.assertNotEqual(
            self._armed_record(_SESSION_A), self._armed_record(_SESSION_B)
        )
        self.assertTrue(self._armed_record(_SESSION_A).is_file())
        self.assertTrue(self._armed_record(_SESSION_B).is_file())

    def test_the_preload_still_emits_its_context(self):
        """Not-degraded control. The arming guard sits at the top of the preload;
        an early `exit` or a `set -e` trip there would leave every assertion
        above green while the skill received no context at all."""
        result = self._run(_SESSION_A)

        self.assertIn("SMM_DIR=", result.stdout)


class TestArmingRecordIsSweptAtSessionBoundary(unittest.TestCase):
    """A host that exposes NO session id resolves the SHARED, unsuffixed name.

    Scoping alone therefore does not give the mirror direction on such a host:
    both sessions address one file, and a leaked record from the previous
    session suppresses this one's curation forever. `CLOSE_CYCLE_ID` is
    session-scoped and in the SessionStart sweep for exactly this reason; this
    record needs the same backstop.
    """

    def test_the_record_is_registered_for_the_session_start_sweep(self):
        import markers
        import session_markers

        self.assertIn(
            markers.HOUSEKEEPING_ARMED, session_markers._STALE_SESSION_MARKERS
        )


if __name__ == "__main__":
    unittest.main()

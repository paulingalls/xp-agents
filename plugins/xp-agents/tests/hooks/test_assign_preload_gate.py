#!/usr/bin/env python3
"""Pin: reading what the assign preload emits must not disarm the plan-review
gate (story-010 AC4).

The preload deleted a LIVE gate marker as its last act, so merely inspecting its
output consumed the gate. Non-mutating is now the default and the consume is
opted into — because the accident happened exactly twice, both times on the
unmarked path.

Split out of `test_spawn_determinism.py` at 651 lines. Two halves, and both are
needed: the behavioural one drives the real preload, the static one proves the
real invocation actually passes the opt-in.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import marker_names
import skill_preload_map
from conftest import _PLUGIN_ROOT, _IntegrationTestCase

_ASSIGN_SKILL = _PLUGIN_ROOT / "skills" / "xp-assign" / "SKILL.md"
_ASSIGN_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"

# The opt-in the real assign invocation passes. Named here once so the prose pin
# and the behavioral pins cannot drift onto two different spellings.
_CONSUME_FLAG = "--consume-gate"


class TestAssignPreloadIsNonDestructiveByDefault(_IntegrationTestCase):
    """Inspecting the preload must not disarm a gate (AC4).

    The marker is a live gate read by the lead's write gate and re-armed by the
    plan-review SubagentStop hook. Its old `rm -f` ran unconditionally as the
    preload's last line, so anyone running the preload to see what it emits
    cleared the gate — which happened twice while this story was being planned.

    An `--inspect` flag would reproduce the accident: the inspector is exactly
    the caller who does not know to pass a flag. So the safe path is the DEFAULT
    and the real invocation opts in.
    """

    def _marker(self) -> Path:
        return self.smm_dir / marker_names.ASSIGN_PENDING

    def _arm(self) -> Path:
        path = self._marker()
        path.write_text("sprint-001 story-001\n")
        return path

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return self._run_preload(_ASSIGN_PRELOAD, args=list(args))

    def test_bare_run_leaves_the_gate_marker(self):
        marker = self._arm()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            marker.is_file(),
            "running the preload for inspection deleted the live gate marker",
        )

    def test_bare_run_still_emits_the_decision_vars(self):
        """Non-mutating must not mean degraded: inspection is only useful if the
        emitted vars are the same ones the real invocation gets."""
        self._arm()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        for var in ("SMM_DIR=", "TEAMMATE_DEFAULT=", "RECOMMENDED_TIER="):
            self.assertIn(var, result.stdout)

    def test_opt_in_consumes_the_marker(self):
        marker = self._arm()
        result = self._run(_CONSUME_FLAG)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.is_file())

    def test_opt_in_consumes_exactly_once_and_a_second_run_is_clean(self):
        """ "Exactly once" has a second half: the consume must not error when the
        marker is already gone, or a re-invoked /xp-assign fails on the preload."""
        marker = self._arm()
        first = self._run(_CONSUME_FLAG)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertFalse(marker.is_file())
        second = self._run(_CONSUME_FLAG)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(marker.is_file())

    def test_opt_in_still_emits_the_decision_vars(self):
        self._arm()
        result = self._run(_CONSUME_FLAG)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TEAMMATE_DEFAULT=", result.stdout)


class TestAssignPreloadConsumeWiring(unittest.TestCase):
    """The static half: the real invocation opts in, via the marker helper."""

    def test_skill_invocation_passes_the_consume_flag(self):
        """The RESOLVER now holds the real assign invocation — if it does not
        opt in, the gate is never consumed and /xp-assign re-arms against
        itself forever.

        Repointed, not weakened. This read the `!`-injected line in SKILL.md
        until that line was deleted and hook-side injection took over; the
        oracle moved with the mechanism, because the resolver is what the
        handler actually runs. Reading the deleted line would have made this
        pin assert against a channel nothing uses.
        """
        invocation = skill_preload_map.resolve_preload_required("xp-assign")
        self.assertIn(
            _CONSUME_FLAG,
            invocation.argv,
            f"the resolved assign invocation does not pass {_CONSUME_FLAG}: "
            f"{invocation.argv}",
        )

    def test_preload_consumes_through_the_marker_helper(self):
        """`rm -f` on a marker path bypasses the marker convention (symlink
        refusal, one spelling of the filename). `consume_marker` already
        exists in the shared preload base."""
        preload = _ASSIGN_PRELOAD.read_text(encoding="utf-8")
        self.assertNotIn(marker_names.ASSIGN_PENDING, preload)
        self.assertIn("consume_marker ASSIGN_PENDING", preload)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Pin: no run of the assign preload disarms the plan-review gate (story-010 AC4).

The preload deleted a LIVE gate marker as its last act, so merely inspecting its
output consumed the gate. Story-010 made non-mutating the DEFAULT and put the
consume behind a `--consume-gate` opt-in, because the accident had happened
exactly twice, both times on the unmarked path.

That opt-in could not survive hook-side injection (story-021). The resolver put
the flag straight into the injected argv, and on the second harness the trigger
for that injection IS a shell read of `SKILL.md` — so a plain `cat` of the assign
body was the opting-in caller, and the accident came back through a door no flag
could close. The consume is gone entirely now; the gate self-clears from sprint
state instead (`lead_gates._unspawned_teammate_story_exists`), so the marker can
outlive the assignment armed but inert.

So the property is no longer "the default is safe" but "there is no unsafe path".
Two halves, and both are needed: the behavioural one drives the real preload,
including with the retired flag, since the arg loop is gone and a stray flag is
now just an ignored argument; the static one proves the script names no
gate-mutating verb at all, which is what stops the consume being reintroduced
under a new opt-in.
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

_ASSIGN_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"

# The retired opt-in. Kept as a literal so the "an unknown argument changes
# nothing" leg passes the flag that used to mean something, rather than an
# invented one that never could.
_RETIRED_FLAG = "--consume-gate"


class TestAssignPreloadNeverDisarmsTheGate(_IntegrationTestCase):
    """No argv reaches a consume, because there is no consume to reach (AC4).

    The marker is a live gate read by the lead's write gate and armed by the
    plan-review SubagentStop hook. Its old `rm -f` ran unconditionally as the
    preload's last line, so anyone running the preload to see what it emits
    cleared the gate — which happened twice while story-010 was being planned,
    and again through the injection path once the flagged form shipped.
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

    def test_the_retired_flag_is_now_an_ignored_argument(self):
        """The arg loop went with the flag, and a `case` with no `*)` arm exits 0
        silently — so a caller still passing the flag must get a NORMAL run, not
        a consume and not an error."""
        marker = self._arm()
        result = self._run(_RETIRED_FLAG)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker.is_file(), f"{_RETIRED_FLAG} still spends the gate")
        self.assertIn("TEAMMATE_DEFAULT=", result.stdout)

    def test_a_run_still_emits_the_decision_vars(self):
        """Non-mutating must not mean degraded: the run is only useful if the
        emitted vars are the ones /xp-assign actually decides on."""
        self._arm()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        for var in ("SMM_DIR=", "TEAMMATE_DEFAULT=", "RECOMMENDED_TIER="):
            self.assertIn(var, result.stdout)

    def test_two_runs_in_a_row_both_leave_the_gate(self):
        """The gate now outlives the act it demanded, so the interesting count is
        not one run but many: /xp-assign is re-invoked once per story in a
        batch, and every one of those runs sees an armed marker."""
        marker = self._arm()
        for attempt in (1, 2):
            with self.subTest(attempt=attempt):
                result = self._run()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(marker.is_file())


class TestAssignPreloadNamesNoGateMutation(unittest.TestCase):
    """The static half: the script cannot spend the gate by any spelling.

    Both spellings are named because they are the two that shipped. `rm -f` on a
    hand-written path was the original; `consume_marker` was its safer
    replacement, and safer is not the same as absent — a marker helper called
    from the preload spends the gate exactly as thoroughly.
    """

    def test_the_preload_neither_names_the_marker_nor_consumes_it(self):
        preload = _ASSIGN_PRELOAD.read_text(encoding="utf-8")
        self.assertNotIn(marker_names.ASSIGN_PENDING, preload)
        self.assertNotIn("consume_marker", preload)

    def test_the_resolved_invocation_passes_no_arguments(self):
        """The injected argv is what a shell read of `SKILL.md` runs, so an
        argument added here is an argument a READ passes. There is nothing left
        for one to switch on today, and this is where a new one would show up."""
        invocation = skill_preload_map.resolve_preload_required("xp-assign")
        self.assertEqual(
            invocation.argv[1:],
            [],
            f"the resolved assign invocation gained an argument: {invocation.argv}",
        )


if __name__ == "__main__":
    unittest.main()

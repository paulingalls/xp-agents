#!/usr/bin/env python3
"""Close-pipeline Step 6 count-concerns CLI, realistic E2E.

Split out of the original test_close_merge_gate.py (which grew past
the 500-line cap). This file keeps the deterministic Step 6
count-concerns CLI realistic E2E tests — synthesizing a real close
cycle by writing concerns through `append.sh` (no mocks, no JSON
forgery), then driving `smm_cli count-concerns` through the same CLI
surface the shared Step 6 abort-default invokes.

The SKILL.md auto-merge override section itself lives in
test_close_merge_gate.py. TEST_COMMAND preload emission tests live in
test_close_merge_gate_test_command.py.

Per-mode shared-content preload emission tests live in
test_close_preloads_emit_shared.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _bases import _PLUGIN_ROOT
from _close_fixtures import _record_quality_block, _record_security_block
from conftest import _IntegrationTestCase, run_cli
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN

_SMM_CLI = _PLUGIN_ROOT / "smm" / "smm_cli.py"

# Realistic close-cycle ids — distinct 12-hex values so cross-cycle
# leakage is visually obvious if a query mis-scopes.
_CYCLE_A = "aaaa11112222"
_CYCLE_B = "bbbb33334444"


class TestStep6CountConcernsRealisticE2E(_IntegrationTestCase):
    """End-to-end: synthesize a real close cycle by writing concerns
    through `append.sh` (no mocks, no JSON forgery), then drive
    `smm_cli count-concerns` through the same CLI surface the shared
    Step 6 abort-default invokes. The combined contract — append.sh
    metadata shape ⇄ count-concerns filter — is what regressed at
    sprint-055 (concern 0825da9526de): the close-reviewer wrote
    quality blocks lacking `close_cycle_id`, so Step 6's count-concerns
    --cycle-id query silently dropped them.

    Realistic event shapes (xp-close-reviewer quality blocks: full
    metadata block per agents/xp-close-reviewer.md; security blocks:
    metadata.kind=security per scripts/_close_pipeline_shared.md
    Step 4.5) are written via real append.sh subprocess calls — the
    only way to catch a future drift between what the appender accepts
    and what the counter filters on.
    """

    def _count_high_concerns_for(self, cycle_id: str) -> int:
        result = run_cli(
            _SMM_CLI,
            ["count-concerns", "--severity", "high", "--cycle-id", cycle_id],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return int(result.stdout.strip())

    def test_high_concern_count_scopes_to_cycle_a_excluding_cycle_b(self) -> None:
        # Cycle A: two reviewer Blocks + one security Block — three high
        # severity concerns total under cycle id A.
        for content, path in [
            ("Block: foo helper duplicates bar helper", "scripts/foo.py"),
            ("Block: missing test for edge case", "scripts/bar.py"),
        ]:
            r = _record_quality_block(self, _CYCLE_A, content, path)
            self.assertEqual(r.returncode, 0, r.stderr)
        r = _record_security_block(
            self,
            _CYCLE_A,
            "Security Block: hardcoded credential in fixture",
            "scripts/sec.py",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # Cycle B noise: a medium-severity quality concern (wrong severity
        # for the count) and a status event (wrong type for the count). No
        # high-severity concern under B, so the cycle-B count is zero.
        r = _record_quality_block(
            self,
            _CYCLE_B,
            "Concern: noise from a parallel close",
            "scripts/noise.py",
            severity="medium",
            source_branch="other-branch",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._run_append(
            "--type", "status",
            "--agent", "xp-sprint-close",
            "--content", "preload: gathered context",
            "--working-on", "[]",
            "--metadata", json.dumps({"close_cycle_id": _CYCLE_B}),
        )  # fmt: skip
        self.assertEqual(r.returncode, 0, r.stderr)

        # Sanity: the four concern writes landed as concern events with
        # the metadata we synthesized — guards against a silent append.sh
        # contract change masking a real bug.
        events = self._read_events()
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(
            len(concerns), 4, f"expected 4 concern events; got {len(concerns)}"
        )
        a_high_concerns = [
            e
            for e in concerns
            if e.get("severity") == "high"
            and e.get("metadata", {}).get("close_cycle_id") == _CYCLE_A
        ]
        self.assertEqual(len(a_high_concerns), 3)
        kinds = sorted(c.get("metadata", {}).get("kind", "") for c in a_high_concerns)
        self.assertEqual(
            kinds,
            ["", "", "security"],
            "cycle A's three high concerns must include exactly one "
            "kind=security (Step 4.5) and two un-kinded quality blocks "
            "(xp-close-reviewer Step 4)",
        )

        # The load-bearing assertion: the deterministic Step 6
        # abort-default count must equal 3 for cycle A and 0 for cycle B,
        # via the same `smm_cli count-concerns` CLI the shared template
        # invokes — no in-process shortcuts.
        self.assertEqual(self._count_high_concerns_for(_CYCLE_A), 3)
        self.assertEqual(self._count_high_concerns_for(_CYCLE_B), 0)

    def test_concurrent_high_concerns_in_two_cycles_stay_isolated(self) -> None:
        # Both cycles file high-severity concerns. The cycle-id filter
        # must isolate them — a leak here is exactly the sprint-055
        # regression class (concern 0825da9526de).
        for content, path in [
            ("Block: cycle A first", "scripts/a1.py"),
            ("Block: cycle A second", "scripts/a2.py"),
        ]:
            r = _record_quality_block(self, _CYCLE_A, content, path)
            self.assertEqual(r.returncode, 0, r.stderr)
        for content, path in [
            ("Block: cycle B first", "scripts/b1.py"),
            ("Block: cycle B second", "scripts/b2.py"),
            ("Block: cycle B third", "scripts/b3.py"),
        ]:
            r = _record_quality_block(self, _CYCLE_B, content, path)
            self.assertEqual(r.returncode, 0, r.stderr)
        r = _record_security_block(
            self,
            _CYCLE_B,
            "Security Block: cycle B hardcoded secret",
            "scripts/b_sec.py",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        self.assertEqual(self._count_high_concerns_for(_CYCLE_A), 2)
        self.assertEqual(self._count_high_concerns_for(_CYCLE_B), 4)


if __name__ == "__main__":
    unittest.main()

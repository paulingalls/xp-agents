#!/usr/bin/env python3
"""The batch-total budget bounding the UNATTENDED --sprint run.

The per-command bound is 2h so a genuinely slow acceptance suite passes
comfortably. But it is PER COMMAND, so a sprint with eight verify-bearing items
can run ~16h — unattended, inside sprint close. Bounding the batch instead of
tightening the item keeps both properties: a slow suite still gets its two
hours, and the whole run still cannot go overnight.

Own file, not folded into the --sprint suite: that suite is at 394 lines and
these cases would push it through the size band (the trap the hardening suite
was split out to avoid). These also pin ONE property — how the batch as a whole
is bounded — across the resolver, the runner, the matrix and BOTH readers of the
verify event, so keeping them together is cohesion, not convenience.

NO TEST HERE SLEEPS. The smallest live budget an int env var can express is 1s,
so every over-budget case would otherwise have to burn real wall-clock in the
commit-time suite — against the recorded convention that commit-time tests
assert structural invariants rather than wall-clock, and flaky under `-n auto`.
The deadline cases script `_now` explicitly and run `_run_sprint` in-process.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import verify_acceptance


class TestBatchBudgetResolver(unittest.TestCase):
    """`_batch_budget` deliberately does NOT reuse `_subprocess_env._env_int`,
    and the divergence is the whole opt-out.

    For a PER-COMMAND timeout a non-positive value is nonsense — `timeout=0`
    makes the runner raise before the command has run at all — so `_env_int`
    correctly folds zero and negatives into the default. For a batch TOTAL,
    non-positive is the only way to say "do not bound my batch": a project whose
    honest sprint verify runs eight hours needs that door, and without it the
    only escape from a false stop is `--force-close`, which bypasses the entire
    acceptance gate rather than this one bound.

    Unset is NOT that door. An opt-in budget would leave the unbounded batch in
    place for everyone who never set the variable — shipped and inert.
    """

    def _budget(self, raw: str) -> int | None:
        with patch.dict(os.environ, {"VERIFY_BATCH_TIMEOUT_S": raw}):
            return verify_acceptance._batch_budget()

    def _unset(self) -> int | None:
        with patch.dict(os.environ):
            os.environ.pop("VERIFY_BATCH_TIMEOUT_S", None)
            return verify_acceptance._batch_budget()

    def test_positive_override_is_honoured(self):
        self.assertEqual(self._budget("60"), 60)

    def test_default_is_four_hours(self):
        # 2x the per-command bound, so no single pathological item can exhaust
        # the batch on its own. Mutation: raise it to match _cmd_timeout and one
        # long item false-stops the whole batch.
        self.assertEqual(self._unset(), 14400)
        self.assertEqual(
            verify_acceptance._DEFAULT_BATCH_TIMEOUT_S,
            2 * verify_acceptance._DEFAULT_CMD_TIMEOUT_S,
        )

    def test_unset_gives_the_default_and_never_disables(self):
        """The ships-inert mutation. If unset returned None the 16h batch
        survives untouched for every project that never sets the variable —
        which is every project, on upgrade."""
        self.assertIsNotNone(self._unset())

    def test_zero_disables_the_budget(self):
        """The documented opt-out, and the divergence from `_env_int`."""
        self.assertIsNone(self._budget("0"))

    def test_negative_disables_the_budget(self):
        self.assertIsNone(self._budget("-1"))

    def test_unparseable_falls_back_to_the_default(self):
        """Unparseable is not consent to run unbounded — it is a typo."""
        self.assertEqual(
            self._budget("not-a-number"), verify_acceptance._DEFAULT_BATCH_TIMEOUT_S
        )

    def test_the_per_command_resolver_is_left_alone(self):
        """AC2's counterpart at the resolver level: the attended path's bound
        keeps `_env_int` semantics, where zero must NOT disable."""
        with patch.dict(os.environ, {"VERIFY_CMD_TIMEOUT_S": "0"}):
            self.assertEqual(
                verify_acceptance._cmd_timeout(),
                verify_acceptance._DEFAULT_CMD_TIMEOUT_S,
            )


if __name__ == "__main__":
    unittest.main()

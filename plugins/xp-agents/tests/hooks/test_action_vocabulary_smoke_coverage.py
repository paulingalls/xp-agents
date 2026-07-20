#!/usr/bin/env python3
"""Capstone smoke test for the deterministic-event-emission doctrine (M3):
the missing-coverage canary.

Split from test_action_vocabulary_smoke.py (was 513 lines) when it crossed
the 500-line cap. This half asserts that every ``STATUS_ACTION_*`` constant
declared in ``event_schema.py`` is accounted for by ``_PRODUCER_CASES``,
``_DOCTRINE_GAPS``, or ``_NON_HOOK_PRODUCERS`` (all defined in
_test_action_vocabulary_smoke_helpers.py). Per-constant emission checks
(does each driver actually emit the right event?) live in
test_action_vocabulary_smoke_emission.py.

1. **Missing-coverage canary** — every ``STATUS_ACTION_*`` constant must
   appear in ``_PRODUCER_CASES`` (driven) or ``_DOCTRINE_GAPS`` (debt
   event filed). A constant absent from both fails this test loud, so a
   future hook that adds a constant without a producer cannot land
   silently.

Doctrine gaps (constants with no producer) are tracked via debt events
referenced by ID in ``_DOCTRINE_GAPS``. This makes the gap legible and
auditable; silent exclusions are not allowed.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-work-selection" / "scripts"
    ),
)

from _test_action_vocabulary_smoke_helpers import (
    _DOCTRINE_GAPS,
    _NON_HOOK_PRODUCERS,
    _PRODUCER_CASES,
    _all_status_action_values,
)
from conftest import _HookTestCase


class TestActionVocabularySmoke(_HookTestCase):
    """Capstone: every STATUS_ACTION_* must be exercised by a driver."""

    def test_missing_coverage_canary(self):
        """Every constant must be in _PRODUCER_CASES or _DOCTRINE_GAPS.

        Keyed on constant *name* — a future constant whose value collides
        with an existing one cannot be silently considered covered.
        """
        constant_names = set(_all_status_action_values())
        covered = set(_PRODUCER_CASES) | set(_DOCTRINE_GAPS) | _NON_HOOK_PRODUCERS
        missing = sorted(constant_names - covered)
        self.assertEqual(
            missing,
            [],
            "STATUS_ACTION_* constants without a producer driver or "
            f"doctrine-gap debt entry: {missing}. Add a driver to "
            "_PRODUCER_CASES or file a debt event and add to _DOCTRINE_GAPS.",
        )


if __name__ == "__main__":
    unittest.main()

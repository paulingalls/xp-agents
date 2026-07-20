#!/usr/bin/env python3
"""Shared test support for the split INTENT link test suite (test_intent*.py).

Not a test module itself (no `test_` prefix) — imported downward only by the
plugins/xp-agents/tests/smm/test_intent*.py siblings. Do not import
test_intent*.py from here.

Relies on the importing test_intent*.py module having already inserted the
`tests/` and `smm/` production dirs onto sys.path (same convention as the
other tests/_*_helpers.py modules, e.g. _lock_helpers.py).
"""

import intent
from conftest import _SMMTestCase

TRY_ID = "aa11bb22cc33"
DEBT_ID = "dd44ee55ff66"


class _IntentTestCase(_SMMTestCase):
    """Adds the two map builders with the try-id scope wired the way production
    wires it, so no test can accidentally hand-pick a friendlier scope."""

    def _retro_map(self, events: list[dict]) -> dict:
        return intent.build_retro_intent_map(events, intent.retro_try_ids(events))

    def _triage_map(self, events: list[dict]) -> dict:
        return intent.build_triage_intent_map(events)

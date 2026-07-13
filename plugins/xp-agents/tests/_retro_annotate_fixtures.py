#!/usr/bin/env python3
"""Shared driver for the retro Try-annotation suites (scripts/retro_history.py).

Extracted when test_retro_history.py crossed the 500-line cap and the
"which id ANSWERS for a Try" suites moved out to test_retro_try_candidate_ids.py
— two test modules now drive `annotate_try_status`, so the driver lives here
rather than being imported test-module-to-test-module. Follows the `tests/_*.py`
convention (_branching_fixtures, _event_fixtures, _lead_gate_fixtures).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import resolution
import retro_history
from conftest import _HookTestCase
from retro_metrics import build_resolutions_map


class _AnnotateTestCase(_HookTestCase):
    """Drives annotate_try_status the way retrospective.py drives it: the
    resolutions map and the intent map both derive from the same event list, so
    a test cannot hand the annotator a combination production never produces.
    """

    def _annotate(self, try_items: list[dict], events: list[dict]) -> list[dict]:
        retros = [{"try": try_items, "keep": [], "fix": []}]
        resolutions_map = build_resolutions_map(resolution.compute_resolutions(events))
        retro_history.annotate_try_status(retros, resolutions_map, events)
        return retros[0]["try_status"]

    def _try(self, try_id: str, content: str = "Carry this Try") -> dict:
        return {"id": try_id, "content": content, "event_refs": []}

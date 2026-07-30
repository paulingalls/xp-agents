#!/usr/bin/env python3
"""A sprint built from (story id, status) pairs.

Shared by the two suites `test_deferred_carryover.py` was split into at 565
lines. Every fixture in both is "a sprint with these stories in these states",
so this factory is the whole of what they have in common. The two underlying
builders are re-exported by identity so neither half reaches past this module.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _cli_helpers import make_story_dict as _make_story
from conftest import make_sprint_dict as _make_sprint

__all__ = ["_make_sprint", "_make_story", "_sprint_with"]


def _sprint_with(*status_pairs: tuple[str, str], sprint_id: str = "sprint-001") -> dict:
    """A sprint whose stories are (id, status) — titles derived from the id."""
    return _make_sprint(
        sprint_id=sprint_id,
        stories=[
            _make_story(id=sid, title=f"Work for {sid}", status=status)
            for sid, status in status_pairs
        ],
    )

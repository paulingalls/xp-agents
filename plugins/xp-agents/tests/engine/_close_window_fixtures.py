#!/usr/bin/env python3
"""Shared fixtures for the two `close_window` suites.

`test_close_window_widening.py` drives `resolve`/`excludes_tag` directly;
`test_close_window_count_concerns.py` drives the same rule end-to-end through
the `count-concerns` CLI the close pipeline actually runs. Both describe ONE
scenario — an enclosing close late in a sprint, and the story-close that ran
earlier in it and left a concern behind — so the scenario lives here rather
than being restated in each file and drifting.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_event
from event_schema import EVENT_TYPE_SPRINT

_SPRINT_START = "2026-07-20T09:00:00+00:00"
_PREV_SPRINT_START = "2026-06-01T09:00:00+00:00"

# The enclosing close being gated, and the story-close that ran earlier in the
# same sprint and left a concern behind.
_ENCLOSING = "eeee00001111"
_STORY_CYCLE = "550011122233"
_PRIOR_SPRINT_CYCLE = "0dd000111222"

# The enclosing close starts LATE in the sprint — that gap between the sprint
# start and CLOSE_START_TS is the hole this story closes.
_CLOSE_START_TS = "2026-07-28T12:00:00+00:00"


def _sprint_start(ts: str = _SPRINT_START, sprint_id: str = "sprint-007") -> dict:
    """A `type=sprint`, `metadata.action=start` event — the sprint window bound.

    Preferred over sprint.json's date-only `started`: better granularity and no
    extra file read, since `count-concerns` already iterates these events.
    """
    return make_event(
        EVENT_TYPE_SPRINT, ts=ts, metadata={"sprint_id": sprint_id, "action": "start"}
    )

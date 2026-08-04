#!/usr/bin/env python3
"""The `count-concerns` CLI path and its concern factory.

Shared by the three suites `test_smm_cli_count_concerns.py` was split into at
640 lines. Note the sibling `test_count_concerns_cycle_isolation.py` keeps its
OWN `_concern`: that one defaults to high severity, stamps a close-cycle id and
omits `files` entirely when asked, because it is exercising the diff-relevance
rule rather than the severity filters. The two factories look alike and are not
interchangeable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_event
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS

_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"


def _concern(severity: str, **kwargs) -> dict:
    """Concern event factory keyed by severity. Other fields kwargs-overridable."""
    return make_event(EVENT_TYPE_CONCERN, severity=severity, files=[], **kwargs)


def _close_started(cycle_id: str, mode: str, ts: str) -> dict:
    """The status event all four close preloads emit (_preload_base.sh:224-233).

    Needed by every fixture that wants a REAL `--cycle-id`, because
    `close_window` reads the close MODE off this event to decide how wide the
    concern gate looks. A cycle with no `close_started` has no readable mode, so
    the gate falls to its widest floor — which is why the suites below now seed
    one whenever they mean to pin the narrow, story-scoped window.
    """
    return make_event(
        EVENT_TYPE_STATUS,
        ts=ts,
        working_on=[],
        metadata={
            "action": "close_started",
            "close_mode": mode,
            "close_cycle_id": cycle_id,
        },
    )

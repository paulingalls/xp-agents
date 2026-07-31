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
from event_schema import EVENT_TYPE_CONCERN

_CLI = Path(__file__).parent.parent.parent / "smm" / "smm_cli.py"


def _concern(severity: str, **kwargs) -> dict:
    """Concern event factory keyed by severity. Other fields kwargs-overridable."""
    return make_event(EVENT_TYPE_CONCERN, severity=severity, files=[], **kwargs)

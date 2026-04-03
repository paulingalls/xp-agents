#!/usr/bin/env python3
"""TeammateIdle hook: TDD enforcement for teammates.

Blocks teammates from going idle when the most recent test run failed.
Uses the shared tdd_check.find_last_test_signal() for consistency
with the Stop hook (tdd_stop_gate.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import tdd_check


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block reason if tests failing, None otherwise."""
    if "teammate_name" not in input_data:
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events = _common.read_events_raw(smm_dir)
    if not events:
        return None

    signal = tdd_check.find_last_test_signal(events)
    if signal == "fail":
        return "Tests are failing. Fix failing tests before going idle."

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        print(result, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)

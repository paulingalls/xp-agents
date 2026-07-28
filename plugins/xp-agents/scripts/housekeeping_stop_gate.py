#!/usr/bin/env python3
"""Stop command hook: block session end until housekeeping has run.

Set by the xp-work-selection preload (step 5 of kickoff). Cleared by
subagent_stop when the housekeeper subagent completes. Defers when
ASKING_USER is set so "Chat about this..." on AskUserQuestion works.

The need marker alone knows two states, but there are three; `housekeeping_flight`
owns the evidence that separates them and explains why it is time-bounded.

What lives here is the wording. The stale message must NOT match the
never-invoked one: same-words-different-cause is what made the original bug
invisible, and a lead who has already waited once needs to be told to
re-invoke rather than wait again.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import housekeeping_flight
import markers

_BLOCK_MESSAGE = (
    "Housekeeping hasn't run yet. Finish /xp-kickoff — invoke the xp-housekeeper "
    "agent via the Agent tool and render the curated SMM before ending."
)

_STALE_MESSAGE = (
    "The xp-housekeeper agent was started but never finished — no curation has "
    f"landed in over {housekeeping_flight.STALE_AFTER_SECONDS // 60} minutes, so "
    "it has stalled or failed. Waiting again will not help: re-invoke it via the "
    "Agent tool (pass run_in_background:false to run it synchronously), then "
    "render the curated SMM before ending."
)

# What to say about each state of the in-flight evidence. Total over the three
# states `housekeeping_flight.state` can return.
_MESSAGE_FOR_STATE: dict[str, str | None] = {
    housekeeping_flight.FRESH: None,
    housekeeping_flight.STALE: _STALE_MESSAGE,
    housekeeping_flight.ABSENT: _BLOCK_MESSAGE,
}


def run(
    input_data: dict, smm_dir: Path | None = None, now: float | None = None
) -> str | None:
    """Return a block message unless housekeeping is done or freshly in flight."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    if not markers.marker_exists(smm_dir, markers.NEEDS_HOUSEKEEPING):
        return None

    if markers.marker_exists(smm_dir, markers.ASKING_USER):
        return None

    return _MESSAGE_FOR_STATE[housekeeping_flight.state(smm_dir, input_data, now)]


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Housekeeping gate — action required.")
    sys.exit(0)

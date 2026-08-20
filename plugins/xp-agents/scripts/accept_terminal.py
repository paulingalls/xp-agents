#!/usr/bin/env python3
"""PostToolUse:Skill|Agent hook: drain ACCEPT_IN_FLIGHT on accept's terminal dispatch.

/xp-accept always ends by invoking exactly one of /xp-schedule (more
stories) or /xp-sprint-review (all done/deferred). That DISPATCH is accept's
deterministic terminal signal — this hook consumes the ACCEPT_IN_FLIGHT marker
there, at the real flip-to-in-progress event.

Dispatch, not the dispatched skill's completion: both terminal skills run
INLINE, so `PostToolUse:Skill` fires when the Skill tool returns the body, not
when the body finishes. /xp-sprint-review only joined that set when story-013
converted it off `context: fork`, whose completion-timed return held the marker
for the whole review; /xp-schedule was always inline. Accept is over once it has
dispatched, so the marker's window now matches accept's own rather than
outliving it — see `sprint_stop_gate._deferred` for what the window suppresses.

Extracted from review_cycle_done.py to restore single-responsibility:
the review-cycle hook should own review-flag lifecycle; the accept
marker has its own lifecycle and its own hook. The legacy implementation
also matched targets via substring (``"schedule" in name``), which
would silently drain on a future skill name containing "schedule".
This hook uses an explicit allowlist (exact match) including the
plugin-qualified ``<plugin>:<skill>`` form. No substring, no surprises.

The drain is idempotent: marker_consume is a no-op when the marker is
unarmed (e.g. the kickoff-tail /xp-schedule).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import markers
import target_routing

# Bare and our-plugin-qualified forms of accept's terminal dispatches.
# Routed through `target_routing.strip_our_namespace` — exact match against
# this set after stripping `xp-agents:` prefix; never substring; third-party
# plugin namespaces are rejected.
_TERMINAL_SKILLS: frozenset[str] = frozenset({"xp-schedule", "xp-sprint-review"})


def _is_terminal_target(target_name: str) -> bool:
    """True iff target_name names one of accept's terminal dispatch skills.

    Accepts both bare (``xp-schedule``) and OUR-plugin-qualified
    (``xp-agents:xp-schedule``) forms via `target_routing.strip_our_namespace`.
    Third-party plugin qualified forms (``otherplugin:xp-schedule``) do NOT
    count — they ship their own `xp-schedule` skill but our ACCEPT_IN_FLIGHT
    marker is scoped to ours.
    """
    bare = target_routing.strip_our_namespace(target_name)
    return bare is not None and bare in _TERMINAL_SKILLS


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Consume ACCEPT_IN_FLIGHT when an accept-terminal skill completes."""
    # Only skill dispatches carry the terminal signal. The xp-sprint-reviewer
    # AGENT is spawned by the /xp-sprint-review SKILL; the skill's own
    # PostToolUse already drains the marker, so the redundant agent-name
    # match the legacy substring code accidentally caught is intentionally
    # NOT replicated here.
    tool_input = input_data.get("tool_input", {})
    target_name = tool_input.get("skill") or ""
    if not _is_terminal_target(target_name):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Idempotent: no-op when unarmed (kickoff-tail /xp-schedule case).
    markers.marker_consume(smm_dir, markers.ACCEPT_IN_FLIGHT)
    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)

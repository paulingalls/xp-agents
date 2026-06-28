#!/usr/bin/env python3
"""PostToolUse:Skill|Agent hook: drain ACCEPT_IN_FLIGHT on accept's terminal dispatch.

/xp-accept always ends by invoking exactly one of /xp-schedule (more
stories) or /xp-sprint-review (all done/deferred). Those completions
are accept's deterministic terminal signal — this hook consumes the
ACCEPT_IN_FLIGHT marker there, at the real flip-to-in-progress event.

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

# Bare and plugin-qualified forms of accept's terminal dispatches.
# Exact match (or endswith for the qualified form) — never substring.
_TERMINAL_SKILLS: frozenset[str] = frozenset({"xp-schedule", "xp-sprint-review"})


def _is_terminal_target(target_name: str) -> bool:
    """True iff target_name names one of accept's terminal dispatch skills.

    Accepts both bare (``xp-schedule``) and plugin-qualified
    (``xp-agents:xp-schedule``) forms. Substring matches do NOT count.
    """
    if not target_name:
        return False
    if target_name in _TERMINAL_SKILLS:
        return True
    # Plugin-qualified: `<plugin>:<skill>`. Compare against the bare form.
    if ":" in target_name:
        _, _, bare = target_name.partition(":")
        return bare in _TERMINAL_SKILLS
    return False


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

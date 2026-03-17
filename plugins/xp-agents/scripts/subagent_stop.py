#!/usr/bin/env python3
"""SubagentStop hook: record subagent completion and run conflict detection.

Appends a minimal status event and checks for structural conflicts
(patterns 2-5, no file_path so pattern 1 is skipped).
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common

# ---------------------------------------------------------------------------
# Path 2: Security review output detection
# ---------------------------------------------------------------------------

# At least one "anchor" signal must match (explicitly security-related)
_SECURITY_ANCHOR_SIGNALS = [
    re.compile(r"security\s+review", re.IGNORECASE),
    re.compile(r"security\s+audit", re.IGNORECASE),
]
# Additional signals that boost confidence (but alone are too generic)
_SECURITY_BOOST_SIGNALS = [
    re.compile(r"no\s+vulnerabilit(?:y|ies)\s+found", re.IGNORECASE),
    re.compile(r"no\s+(?:security\s+)?issues?\s+found", re.IGNORECASE),
    re.compile(r"(?:Critical|High|Medium|Low)\s*:", re.IGNORECASE),
    re.compile(r"vulnerabilit(?:y|ies)", re.IGNORECASE),
]
_SECURITY_REVIEW_THRESHOLD = 2


def _detect_security_review(message: str) -> bool:
    """Detect security review output.

    Requires an anchor signal (security review/audit) plus total
    score >= threshold. Boost signals alone cannot trigger detection,
    preventing false positives from linter output.
    """
    if not message:
        return False
    has_anchor = any(sig.search(message) for sig in _SECURITY_ANCHOR_SIGNALS)
    if not has_anchor:
        return False
    all_signals = _SECURITY_ANCHOR_SIGNALS + _SECURITY_BOOST_SIGNALS
    score = sum(1 for sig in all_signals if sig.search(message))
    return score >= _SECURITY_REVIEW_THRESHOLD


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core SubagentStop logic. Returns context or raises BlockedError."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = input_data.get("agent_id", "subagent")
    try:
        _common._validate_agent_id(agent_id)
    except ValueError:
        return None

    # Minimal completion status
    event = _common.make_event(
        _common.STATUS,
        agent_id,
        f"Subagent {agent_id} completed",
        working_on=[],
    )
    _common.append_safe(smm_dir, event)

    # Conflict detection — patterns 2-5 only (no file_path)
    events = _common.read_events_raw(smm_dir)
    concern_events = _common.detect_conflicts(events, agent_id)
    for concern in concern_events:
        _common.append_safe(smm_dir, concern)

    # Path 2: detect security review output from subagent
    last_message = input_data.get("last_assistant_message", "")
    if isinstance(last_message, str) and _detect_security_review(last_message):
        _common.mark_security_reviewed(smm_dir, input_data.get("cwd", "."))

    # Plan review gate — write marker event for PreToolUse to detect.
    # Don't block (causes re-planning loops) or nudge via reason (silently dropped).
    agent_type = input_data.get("agent_type", "")
    if agent_type == "Plan":
        gate_event = _common.make_event(
            _common.STATUS,
            agent_id,
            "plan_awaiting_review: Plan completed, run /xp-plan-reviewer",
            working_on=[],
        )
        _common.append_safe(smm_dir, gate_event)
        return None

    # Subagent reviewer nudge for non-xp subagents
    return (
        "Run /xp-subagent-reviewer in the background to review this subagent's output."
    )


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)

    if result:
        # SubagentStop doesn't support hookSpecificOutput/additionalContext.
        # Use decision:approve with reason to pass the nudge through.
        print(json.dumps({"decision": "approve", "reason": result}))
    sys.exit(0)

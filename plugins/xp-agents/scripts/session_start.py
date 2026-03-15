#!/usr/bin/env python3
"""SessionStart hook: initialize SMM, inject context.

Runs on startup, resume, and compact. Ensures SMM exists, materializes
the current view, and injects it as additionalContext with behavioral
guide, GUPP, and skills.
Retrospective triggering is handled separately by retrospective.py.
"""

import functools
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import materialize

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GUPP_TEXT = (
    "\n\n---\n"
    "Check the Shared Mental Model for pending work. "
    "Resume immediately. Don't wait for permission."
)

SKILLS_TEXT = (
    "\n\n---\n"
    "**Available Skills (invoke these regularly):**\n"
    "- `/smm-protocol` — Event recording reference. Invoke when recording "
    "decisions, questions, concerns, assumptions, discoveries, or debt\n"
    "- `/xp-values` — XP values as behavioral guide. Invoke when making "
    "design decisions, resolving trade-offs, or evaluating code quality\n"
    "- `/pair-programming` — Pair programming protocol. Invoke when "
    "responding to navigator guidance, resolving reviewer conflicts, "
    "or starting complex work"
)


# ---------------------------------------------------------------------------
# Behavioral guide loader
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _load_behavioral_guide() -> str:
    """Load BEHAVIORAL_GUIDE.md from plugin root. Returns empty string on failure."""
    try:
        plugin_root = _common.resolve_plugin_root()
        guide_path = plugin_root / "BEHAVIORAL_GUIDE.md"
        if guide_path.is_file():
            return "\n\n" + guide_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        pass
    return ""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core session_start logic. Returns additionalContext string or None."""
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    # Skip on clear
    source = input_data.get("source", "")
    if source == "clear":
        return None

    # Ensure SMM exists via init.sh
    if smm_dir is None or not smm_dir.exists():
        plugin_root = _common.resolve_plugin_root()
        init_script = plugin_root / "smm" / "init.sh"
        # Validate script path before executing
        if init_script.is_file() and init_script.stat().st_uid == os.getuid():
            try:
                result = subprocess.run(
                    ["bash", str(init_script)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    smm_dir = Path(result.stdout.strip())
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass

    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        # Graceful: return GUPP + skills even without SMM
        return GUPP_TEXT + SKILLS_TEXT

    # Materialize events into SMM markdown
    materialize.materialize_to_file(smm_dir)
    smm_content = materialize.materialize(smm_dir)

    # Build context: SMM + enforcement + GUPP + skills
    parts: list[str] = []

    if smm_content:
        parts.append(_common.wrap_smm_context(smm_content))

    # Inject enforcement indicator for advisory mode
    # (also emitted per-tool by pre_tool_use.py to survive compaction)
    enforcement = _common.load_enforcement_mode()
    if enforcement == _common.ENFORCEMENT_ADVISORY:
        parts.append("\n[enforcement: advisory]")

    # Behavioral guide — XP rules for the main agent
    guide = _load_behavioral_guide()
    if guide:
        parts.append(guide)

    # Customer proxy subagent nudge — check for missing goals or open questions
    import _append_impl

    events = _common.read_events_raw(smm_dir)
    has_goals = any(e.get("type") == _common.GOAL for e in events)
    # Filter out answered questions to avoid false positive nudges
    resolutions = _append_impl.compute_resolutions(events)
    answered_ids = resolutions["answered_question_ids"]
    has_open_questions = any(
        e.get("type") == _common.QUESTION
        and e.get("priority") in (_common.PRIORITY_BLOCKING, _common.PRIORITY_ASSUMED)
        and e.get("id") not in answered_ids
        for e in events
    )
    parts.append(GUPP_TEXT)
    parts.append(SKILLS_TEXT)

    # Customer proxy nudge goes LAST for maximum salience.
    # No goals = first session on this project — critical to establish direction.
    if not has_goals:
        parts.append(
            "\n\n---\n"
            "**IMPORTANT — FIRST ACTION REQUIRED:** No project goals have been "
            "recorded yet. Before doing ANY other work, invoke the "
            "xp-customer-proxy subagent to ask the user about project goals. "
            "This is a first-session requirement — goals guide all subsequent "
            "decisions, reviews, and retrospectives."
        )
    elif has_open_questions:
        parts.append(
            "\n\n---\n"
            "**ACTION REQUIRED:** There are unresolved blocking or assumed "
            "questions. Invoke the xp-customer-proxy subagent to triage them "
            "before proceeding with work."
        )

    return "".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    context = run(input_data)
    if context is not None:
        _common.hook_output("SessionStart", context)
    sys.exit(0)

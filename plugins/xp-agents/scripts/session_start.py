#!/usr/bin/env python3
"""SessionStart hook: initialize SMM, inject context.

Runs on startup, resume, and compact. Ensures SMM exists, materializes
the current view, and injects it as additionalContext with behavioral
guide, GUPP, and skills.
Retrospective triggering is handled separately by retrospective.py.
"""

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

    # Materialize to file (for preloads to read), but don't inject into context.
    # The fresh SMM will be injected after /xp-session-review completes.
    materialize.materialize_to_file(smm_dir)

    # Write .needs-session-review marker only on fresh session starts.
    # "resume", "compact", "clear" all fire mid-session (e.g., after
    # Stop hook blocks, context compression, or /clear).
    if source == "startup":
        marker = smm_dir / ".needs-session-review"
        marker.touch()

    # Build context: GUPP + skills + behavioral guide only. No SMM, no nudges.
    parts: list[str] = []

    # Inject enforcement indicator for advisory mode
    enforcement = _common.load_enforcement_mode()
    if enforcement == _common.ENFORCEMENT_ADVISORY:
        parts.append("\n[enforcement: advisory]")

    parts.append(GUPP_TEXT)
    parts.append(SKILLS_TEXT)

    # BEHAVIORAL_GUIDE.md is now injected by session_review_done.py
    # (PostToolUse:Skill hook) after /xp-session-review completes,
    # together with the fresh SMM.

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

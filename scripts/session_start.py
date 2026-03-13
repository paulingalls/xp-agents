#!/usr/bin/env python3
"""SessionStart hook: initialize SMM, inject context, trigger retro.

Runs on startup, resume, and compact. Ensures SMM exists, materializes
the current view, and injects it as additionalContext. Triggers retro
instruction when enough unanalyzed events have accumulated.
"""

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

RETRO_THRESHOLD = 5

GUPP_TEXT = (
    "\n\n---\n"
    "Check the Shared Mental Model for pending work. "
    "Resume immediately. Don't wait for permission."
)

SKILLS_TEXT = (
    "\n\n---\n"
    "**Available Skills:**\n"
    "- `/smm-protocol` — When you need to record decisions, questions, "
    "concerns, or conventions to the Shared Mental Model\n"
    "- `/xp-values` — When facing a design decision or trade-off, "
    "consult XP values for guidance\n"
    "- `/pair-programming` — When starting a complex task, "
    "engage pair programming with navigator review"
)

RETRO_INSTRUCTION = (
    "**Action Required: Run a retrospective before starting new work.**\n"
    "There are {count} unanalyzed events since the last retrospective. "
    "Use the Keep/Fix/Try framework with XP values as analytical lenses.\n\n"
)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _count_unanalyzed_events(events: list[dict]) -> int:
    """Count events after the last retrospective event."""
    last_retro_idx = -1
    for i, e in enumerate(events):
        if e.get("type") == "retrospective":
            last_retro_idx = i
    if last_retro_idx == -1:
        return len(events)
    return len(events) - last_retro_idx - 1


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

    try:
        if smm_dir is not None:
            _common._validate_smm_dir(smm_dir)
        else:
            raise ValueError("No SMM dir")
    except ValueError:
        # Graceful: return GUPP + skills even without SMM
        return GUPP_TEXT + SKILLS_TEXT

    # Materialize current view (in-memory, no write-then-read-back)
    smm_content = materialize.materialize(smm_dir)

    # Build context
    parts: list[str] = []

    # Check for retro trigger (only on startup/resume, not compact)
    if source != "compact":
        events = _common.read_events_raw(smm_dir)
        unanalyzed = _count_unanalyzed_events(events)
        if unanalyzed >= RETRO_THRESHOLD:
            parts.append(RETRO_INSTRUCTION.format(count=unanalyzed))

    # Full SMM
    if smm_content:
        parts.append(smm_content)

    # GUPP + skills
    parts.append(GUPP_TEXT)
    parts.append(SKILLS_TEXT)

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

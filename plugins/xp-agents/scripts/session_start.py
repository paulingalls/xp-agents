#!/usr/bin/env python3
"""SessionStart hook: initialize SMM, inject context.

Handles all SessionStart sources (startup, resume, compact, clear).
Ensures SMM exists and injects GUPP and skills as additionalContext.
Sets .needs-kickoff marker on fresh starts (startup, clear).
Retrospective triggering is handled separately by retrospective.py.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import markers
import sprint_state

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GUPP_RESUME = (
    "\n\n---\n"
    "Check the Shared Mental Model for pending work. "
    "Resume immediately. Don't wait for permission."
)

GUPP_STARTUP = (
    "\n\n---\nRun /xp-kickoff before doing anything else, and start immediately."
)

SKILLS_TEXT = (
    "\n\n---\n"
    "**Available Skills (invoke these regularly):**\n"
    "- `/xp-smm-protocol` — Event recording reference. Invoke when recording "
    "decisions, questions, concerns, assumptions, discoveries, or debt"
)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core session_start logic. Returns additionalContext string or None."""
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    source = input_data.get("source", "")

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
        return GUPP_STARTUP + SKILLS_TEXT

    # Write .needs-kickoff marker on fresh starts.
    # "startup" = new session (block until kickoff), "clear" = mid-session
    # reset (nudge only — work may be in progress).
    # "resume" and "compact" fire mid-session — no marker needed.
    if source in ("startup", "clear"):
        markers.marker_write(smm_dir, markers.KICKOFF, source)
        markers.marker_consume(smm_dir, markers.ACCEPT)
        if not sprint_state.product_spec_exists(smm_dir):
            markers.marker_write(smm_dir, markers.NEEDS_PRODUCT_SPEC, source)
        sprint_content = sprint_state.read_sprint_content(smm_dir)
        needs_sprint = sprint_content is None or not sprint_state.has_active_stories(
            sprint_content
        )
        if needs_sprint:
            markers.marker_write(smm_dir, markers.NEEDS_SPRINT, source)

    # Build context: GUPP (source-dependent) + skills.
    gupp = GUPP_STARTUP if source in ("startup", "clear") else GUPP_RESUME
    parts: list[str] = []
    parts.append(gupp)
    parts.append(SKILLS_TEXT)

    # XP_VALUES.md + PROCESS_GUIDE.md are injected by kickoff_done.py
    # (PostToolUse:Skill hook) after /xp-kickoff completes,
    # together with the fresh SMM.

    # M10: Reinject SMM + sprint.md after compaction so the lead's
    # context retains project state and story selection still works.
    if source == "compact":
        smm_file = smm_dir / "SHARED_MENTAL_MODEL.md"
        try:
            smm_content = smm_file.read_text(encoding="utf-8")
            if smm_content.strip():
                parts.append("\n\n" + smm_content)
        except FileNotFoundError:
            pass
        sprint_content = sprint_state.read_sprint_content(smm_dir)
        if sprint_content:
            parts.append("\n\n" + sprint_content)

    return "".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _get_version() -> str:
    """Read plugin version from plugin.json."""
    try:
        plugin_json = _common.resolve_plugin_root() / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        return data.get("version", "?")
    except (OSError, json.JSONDecodeError, ValueError):
        return "?"


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    context = run(input_data)
    if context is not None:
        version = _get_version()
        _common.hook_output(
            "SessionStart", context, f"XP agents (v{version}) active. Run /xp-kickoff."
        )
    sys.exit(0)

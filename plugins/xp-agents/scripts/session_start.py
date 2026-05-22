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
import execution_plan_store
import identity
import markers
import plugin_loader
import smm_cli
import smm_store
import sprint_state
import system_context_store
from system_context_renderer import render_markdown as render_system_context

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


def _is_fresh_start(source: str) -> bool:
    """True when the SessionStart source represents a fresh start.

    ``startup`` is a brand-new session (kickoff_gate hard-blocks until
    /xp-kickoff runs); ``clear`` is a mid-session reset (nudge only).
    Both arm the KICKOFF marker. ``resume`` and ``compact`` are
    continuations of an in-flight session — re-running kickoff would
    redo work just done.
    """
    return source in ("startup", "clear")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _run_teammate(smm_dir: Path | None) -> str | None:
    """Teammate SessionStart: XP Values + Teammate Guide + SMM. No markers."""
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    parts: list[str] = []
    values = plugin_loader.load_xp_values()
    if values:
        parts.append(values)
    guide = plugin_loader.load_teammate_guide()
    if guide:
        parts.append(guide)
    if smm_dir is not None:
        data = system_context_store.load_system_context(smm_dir)
        if data:
            ctx_rendered = render_system_context(data)
            if ctx_rendered.strip():
                parts.append(ctx_rendered)
        smm_data = smm_store.load_smm(smm_dir)
        smm_rendered = smm_cli.render_markdown(smm_data)
        if smm_rendered.strip():
            parts.append(smm_rendered)
    return "\n\n".join(parts) if parts else None


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core session_start logic. Returns additionalContext string or None."""
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    if identity.is_worktree_teammate(input_data):
        return _run_teammate(smm_dir)

    source = input_data.get("source", "")

    if smm_dir is None or not smm_dir.exists():
        plugin_root = plugin_loader.resolve_plugin_root()
        init_script = plugin_root / "smm" / "init.sh"
        # Refuse to exec unless the script is owned by the current user.
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
        return "SMM init failed — xp-agents disabled."

    # Sweep stale CLOSE_CYCLE_ACTIVE/ACCEPT markers only on fresh starts —
    # resume/compact mid-session may have a close-skill or /xp-accept in
    # flight that legitimately holds them.
    if _is_fresh_start(source):
        markers.sweep_stale_session_markers(smm_dir)
        markers.marker_write(smm_dir, markers.KICKOFF, source)
        # Deterministic session-boundary anchor. Main-only — teammates
        # returned above; emitted once per startup/clear fresh start.
        _common.append_safe(
            smm_dir,
            _common.make_event(
                _common.SESSION_STARTED,
                identity.resolve_agent_id(input_data),
                source,
            ),
        )
        if not sprint_state.has_remaining_work(smm_dir):
            execution_plan_store.archive(smm_dir)
            markers.marker_write(smm_dir, markers.NEEDS_EXECUTION_PLAN, source)
        if not sprint_state.system_context_exists(smm_dir):
            markers.marker_write(smm_dir, markers.NEEDS_SYSTEM_CONTEXT, source)
        needs_sprint = not sprint_state.has_active_stories(smm_dir)
        if needs_sprint:
            markers.marker_write(smm_dir, markers.NEEDS_SPRINT, source)

    gupp = GUPP_STARTUP if _is_fresh_start(source) else GUPP_RESUME
    parts: list[str] = [gupp]
    values = plugin_loader.load_xp_values()
    if values:
        parts.append("\n\n" + values)

    # PROCESS_GUIDE.md is injected by kickoff_done.py after /xp-kickoff
    # completes, together with the fresh SMM.

    # Reinject SMM + process guide after compaction so the lead's
    # context retains project state and workflow rules.
    if source == "compact":
        smm_data = smm_store.load_smm(smm_dir)
        rendered = smm_cli.render_markdown(smm_data)
        if rendered.strip():
            parts.append("\n\n" + rendered)
        process = plugin_loader.load_process_guide()
        if process:
            parts.append("\n\n" + process)

    return "".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _get_version() -> str:
    """Read plugin version from plugin.json."""
    try:
        plugin_json = (
            plugin_loader.resolve_plugin_root() / ".claude-plugin" / "plugin.json"
        )
        data = json.loads(plugin_json.read_text())
        return data.get("version", "?")
    except (OSError, json.JSONDecodeError, ValueError):
        return "?"


def _system_message(source: str, version: str) -> str:
    """SessionStart systemMessage; kickoff nudge only on fresh starts."""
    base = f"XP agents (v{version}) active."
    if _is_fresh_start(source):
        return f"{base} Run /xp-kickoff."
    return base


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    context = run(input_data)
    if context is not None:
        version = _get_version()
        source = input_data.get("source", "")
        _common.hook_output("SessionStart", context, _system_message(source, version))
    sys.exit(0)

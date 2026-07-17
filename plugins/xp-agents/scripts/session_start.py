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
from event_schema import METADATA_KEY_RESOLVES
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


def _resolve_prior_goals(events: list[dict], resolutions: dict) -> list[str]:
    """Return sorted ids of unresolved GOAL events emitted before the
    most-recent session_started anchor in ``events``.

    Re-homed from session_end (M3). Only valid for source=='startup', where
    the prior conversation is gone and every open goal is genuinely prior-
    session backlog (callers gate on this — see run()). On 'clear' a goal
    emitted earlier in the SAME live conversation by /xp-kickoff is still
    active and must NOT be resolved. Teammates no longer emit session_end and
    SessionStart is main-only, so main owns the whole shared window: resolve
    all unresolved goals regardless of agent_id, else worktree-story-* goals
    orphan forever.

    The pre-anchor slice pins the pre-anchor-only invariant IN the function
    itself — without it, a future SessionStart-time goal emitter would land
    at/after the anchor in ``events`` and be wrongly resolved as prior-
    session backlog the instant it's emitted. When no anchor exists (very
    first session of a fresh project), the slice no-ops and we resolve the
    entire backlog as before — preserves the no-anchor regression-guard
    pinned by ``test_fresh_start_resolves_all_prior_unresolved_goals``.
    """
    anchor_idx = _common._last_index_of_type(events, _common.SESSION_STARTED)
    if anchor_idx >= 0:
        events = events[:anchor_idx]
    resolved = resolutions["resolved_goal_ids"]
    return sorted(
        e["id"]
        for e in events
        if e.get("type") == _common.GOAL and e.get("id") and e["id"] not in resolved
    )


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _render_review_cadence(cadence: str) -> str:
    """Render the active review cadence so the teammate doesn't depend on the
    lead hand-writing it into the spawn prompt.

    The commit gate enforces the mode mechanically either way; this closes the
    communication gap so the teammate behaves correctly on its own.
    """
    if cadence == "story":
        return (
            "## Review Cadence: per-story\n"
            "Per-commit review is deferred to story-close, which the lead "
            "runs. Commit with the deferral advisory — do NOT run "
            "/xp-quality-review per commit."
        )
    return (
        "## Review Cadence: per-commit\n"
        "Run /xp-quality-review before every commit; the commit gate blocks "
        "an unreviewed commit."
    )


def _run_teammate(smm_dir: Path | None) -> str | None:
    """Teammate SessionStart: XP Values + Guide + cadence + SMM. No markers."""
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    parts: list[str] = []
    values = plugin_loader.load_xp_values()
    if values:
        parts.append(values)
    guide = plugin_loader.load_teammate_guide()
    if guide:
        parts.append(guide)
    if smm_dir is not None:
        parts.append(_render_review_cadence(markers.read_review_cadence(smm_dir)))
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
        # Cadence is session-scoped: a fresh start resets to the careful
        # 'commit' default so a prior session's 'story' choice never leaks.
        # resume/compact (continuations) fall through and preserve it.
        markers.write_review_cadence(smm_dir, markers.DEFAULT_CADENCE)
        markers.marker_write(smm_dir, markers.KICKOFF, source)
        # Deterministic session-boundary anchor + re-homed side-effects (M3).
        # Main-only — teammates returned above; emitted once per startup/clear.
        # Resolve prior-session goals against the PRE-anchor event list so the
        # new anchor isn't counted (append_safe writes to disk, not `events`).
        agent_id = identity.resolve_agent_id(input_data)
        # Goal-resolution only on 'startup': a fresh process whose prior
        # conversation is gone, so open goals are prior-session backlog. On
        # 'clear' the conversation continues and any open goal is still active,
        # so skip the full-log load + resolution pass entirely.
        resolved_goal_ids: list[str] = []
        if source == "startup":
            events, resolutions = _common.load_events_with_resolutions(smm_dir)
            resolved_goal_ids = _resolve_prior_goals(events, resolutions)
        extra = (
            {"metadata": {METADATA_KEY_RESOLVES: resolved_goal_ids}}
            if resolved_goal_ids
            else {}
        )
        _common.append_safe(
            smm_dir,
            _common.make_event(_common.SESSION_STARTED, agent_id, source, **extra),
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

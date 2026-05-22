#!/usr/bin/env python3
"""SessionStart hook: initialize SMM, inject context.

Handles all SessionStart sources (startup, resume, compact, clear).
Ensures SMM exists and injects GUPP and skills as additionalContext.
Sets .needs-kickoff marker on fresh starts (startup, clear).
Retrospective triggering is handled separately by retrospective.py.
"""

import bisect
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import execution_plan_store
import identity
import markers
import plugin_loader
import smm_cli
import smm_store
import sprint_state
import system_context_store
from event_schema import (
    METADATA_KEY_FLAGGED_STALE,
    METADATA_KEY_RESOLVES,
    METADATA_KEY_STALE_SESSION_COUNT,
)
from system_context_renderer import render_markdown as render_system_context

STALE_CONCERN_SESSION_THRESHOLD = 4

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
    """Return sorted ids of all unresolved GOAL events.

    Re-homed from session_end (M3). Only valid for source=='startup', where
    the prior conversation is gone and every open goal is genuinely prior-
    session backlog (callers gate on this — see run()). On 'clear' a goal
    emitted earlier in the SAME live conversation by /xp-kickoff is still
    active and must NOT be resolved. Teammates no longer emit session_end and
    SessionStart is main-only, so main owns the whole shared window: resolve
    all unresolved goals regardless of agent_id, else worktree-story-* goals
    orphan forever.
    """
    resolved = resolutions["resolved_goal_ids"]
    return sorted(
        e["id"]
        for e in events
        if e.get("type") == _common.GOAL and e.get("id") and e["id"] not in resolved
    )


def _sweep_stale_concerns(
    smm_dir: Path,
    events: list[dict],
    resolutions: dict,
    agent_id: str,
) -> None:
    """Emit one flag-concern per open concern that has survived
    STALE_CONCERN_SESSION_THRESHOLD or more SESSION_STARTED anchors.

    Re-homed from session_end (M3), now counting the deterministic
    session_started boundary. Idempotency: a concern that already has an
    unresolved flag-concern pointing back to it (metadata.flagged_stale=True,
    references=[orig_id]) is skipped. `events` is the pre-anchor list, so the
    current session's own anchor is not yet counted toward the threshold.
    """
    resolved_ids = resolutions["resolved_concern_ids"]
    already_flagged: set[str] = set()
    anchor_positions: list[int] = []
    concern_position: dict[str, int] = {}
    for i, e in enumerate(events):
        match e.get("type"):
            case _common.SESSION_STARTED:
                anchor_positions.append(i)
            case _common.CONCERN:
                eid = e.get("id", "")
                if eid:
                    concern_position[eid] = i
                if (
                    eid not in resolved_ids
                    and (e.get("metadata") or {}).get("flagged_stale") is True
                ):
                    already_flagged.update(e.get("references") or [])
    stale = concerns.filter_by_session_age(
        events,
        STALE_CONCERN_SESSION_THRESHOLD,
        resolutions=resolutions,
        anchor_positions=anchor_positions,
    )
    if not stale:
        return
    total_anchors = len(anchor_positions)
    flag_events: list[dict] = []
    for orig in stale:
        orig_id = orig.get("id", "")
        # A flag-concern is itself an open CONCERN, so it surfaces in `stale`
        # once it ages past the threshold. Never flag a flag — that would
        # compound a new flag-of-a-flag every fresh start (the original it
        # references is suppressed via already_flagged, but the flag's own id
        # is not, so without this guard the log grows unbounded).
        if not orig_id or orig_id in already_flagged:
            continue
        if (orig.get("metadata") or {}).get("flagged_stale") is True:
            continue
        anchors_since = total_anchors - bisect.bisect_right(
            anchor_positions, concern_position[orig_id]
        )
        flag_events.append(
            concerns.make_concern(
                content=(
                    f"Concern {orig_id} is stale ({anchors_since} sessions old)"
                    " — triage at next kickoff"
                ),
                severity="low",
                agent_id=agent_id,
                references=[orig_id],
                metadata={
                    METADATA_KEY_FLAGGED_STALE: True,
                    METADATA_KEY_STALE_SESSION_COUNT: anchors_since,
                },
            )
        )
    if flag_events:
        _common.bulk_append_safe(smm_dir, flag_events)


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
        # Deterministic session-boundary anchor + re-homed side-effects (M3).
        # Main-only — teammates returned above; emitted once per startup/clear.
        # Resolve prior-session goals on the anchor and sweep stale concerns,
        # both against the PRE-anchor event list so the new anchor isn't
        # counted toward the staleness threshold (append_safe writes to disk,
        # not to `events`).
        agent_id = identity.resolve_agent_id(input_data)
        events, resolutions = _common.load_events_with_resolutions(smm_dir)
        # Goal-resolution only on 'startup': a fresh process whose prior
        # conversation is gone, so open goals are prior-session backlog. On
        # 'clear' the conversation continues and any open goal is still active.
        resolved_goal_ids = (
            _resolve_prior_goals(events, resolutions) if source == "startup" else []
        )
        extra = (
            {"metadata": {METADATA_KEY_RESOLVES: resolved_goal_ids}}
            if resolved_goal_ids
            else {}
        )
        _common.append_safe(
            smm_dir,
            _common.make_event(_common.SESSION_STARTED, agent_id, source, **extra),
        )
        _sweep_stale_concerns(smm_dir, events, resolutions, agent_id)
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

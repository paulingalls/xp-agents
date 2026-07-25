#!/usr/bin/env python3
"""SessionStart hook: initialize SMM, inject context.

Handles all SessionStart sources (startup, resume, compact, clear).
Ensures SMM exists and injects GUPP and XP_VALUES.md as additionalContext
(plus the rendered SMM and PROCESS_GUIDE.md on the `compact` source).
Sets .needs-kickoff marker on fresh starts (startup, clear).
Retrospective triggering is handled separately by retrospective.py.
"""

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
import smm_dir_resolve
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


# Generous, because this call is not always a path lookup: on the first
# resolution after an upgrade init.sh copies the WHOLE SMM to the new data root
# — twice, counting the pre-rename re-sync — and a process that loses that race
# waits for the winner before answering. Undershooting costs the whole session
# (no retrospective, no event log, no commit gate) on the one session where the
# relocation happens; overshooting costs a slow start that a wedged init.sh
# would have cost anyway. Still well inside the platform's own hook budget. The
# manual tool (migrate_smm_root.py) allows more: a human is watching it.
_INIT_SH_TIMEOUT_SECONDS = 30


def _resolve_via_init_sh() -> Path | None:
    """Resolve the SMM by running init.sh, or None if that fails.

    Refuses to exec unless the script is owned by the current user. Shared with
    the CLI entry point so that check lives in exactly one place — init.sh is
    also what performs the one-time relocation off a host-managed root, so a
    second caller must never reach it through an unguarded path.
    """
    plugin_root = plugin_loader.resolve_plugin_root()
    init_script = plugin_root / "smm" / "init.sh"
    if not (init_script.is_file() and init_script.stat().st_uid == os.getuid()):
        return None
    try:
        result = subprocess.run(
            ["bash", str(init_script)],
            capture_output=True,
            text=True,
            timeout=_INIT_SH_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return None


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


def run(
    input_data: dict,
    smm_dir: Path | None = None,
    *,
    already_resolved: bool = False,
) -> str | None:
    """Core session_start logic. Returns additionalContext string or None.

    ``already_resolved`` says the caller has itself run the init.sh resolution
    and ``smm_dir`` is its verbatim answer, ``None`` included. Retrying it here
    would spend the whole budget a second time on the one case that most needs
    a fast answer — a resolution that came back empty is overwhelmingly one
    that timed out, and a fresh attempt has the same work to redo. In-process
    callers that pass a dir directly leave this False and keep the fallback.
    """
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    if identity.is_worktree_teammate(input_data):
        return _run_teammate(smm_dir)

    source = input_data.get("source", "")

    if not already_resolved and (smm_dir is None or not smm_dir.exists()):
        smm_dir = _resolve_via_init_sh() or smm_dir

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

    # PROCESS_GUIDE.md is injected by review_cycle_done.py (PostToolUse:
    # Skill|Agent) when xp-housekeeper completes, together with the fresh SMM.

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


SMM_ROOT_ADVISORY = (
    "NOTE: the shared mental model still lives under the host-managed plugin "
    "data root, which 'claude plugin uninstall' deletes by default. It relocates "
    "itself automatically, but only once no teammate worktree and no in-place "
    "teammate remain — check for a stale one whose branch never merged. Run "
    "'python3 {tool}' to see what is holding it."
)


def _advisory() -> str:
    """The advisory with a copy-pasteable path to the manual tool.

    Resolved at message time rather than hardcoded: the plugin cache is
    versioned, so a literal path would name whichever release wrote it.
    """
    tool = plugin_loader.resolve_plugin_root() / "scripts" / "migrate_smm_root.py"
    return SMM_ROOT_ADVISORY.format(tool=tool)


def _system_message(source: str, version: str, smm_dir: Path | None = None) -> str:
    """SessionStart systemMessage; kickoff nudge only on fresh starts.

    The at-risk-root advisory rides here rather than in additionalContext for
    two reasons. The USER is the one who has to act on it — the blocker is a
    directory only they can retire. And relocation can stay declined
    indefinitely: the liveness gate keys on a worktree directory existing, and
    nothing removes one whose branch never merged, so a release note is not a
    substitute. A line buried in a context blob is the silent-enforcement
    pattern this change exists to end.
    """
    base = f"XP agents (v{version}) active."
    if _is_fresh_start(source):
        base = f"{base} Run /xp-kickoff."
    if smm_dir is not None and smm_dir_resolve.is_under_plugin_managed_root(smm_dir):
        return f"{base} {_advisory()}"
    return base


def main() -> None:
    """SessionStart entry point: resolve once, run, emit.

    The resolution happens HERE rather than inside ``run`` so that one call
    serves both the run and the at-risk-root advisory. It is not a path lookup
    on the session that matters: init.sh performs the one-time relocation, a
    whole-SMM copy, so a second round-trip would pay for that copy twice — and
    restart it from scratch after a timeout, doubling the wait that made the
    first attempt fail. ``already_resolved`` is what makes that true rather
    than merely intended: it suppresses ``run``'s own fallback resolution, so
    an empty answer here fails fast instead of being retried.

    Skipped for the two branches that return without one. A nested xp- agent is
    the recursion guard and does nothing at all. Teammates keep getting None,
    exactly as ``run``'s own teammate branch does: handing one a resolved dir
    would inject the full SMM render into every teammate's context, and the
    advisory is addressed to the human at the lead session, who is the only one
    who can act on it.
    """
    input_data = _common.read_hook_input()
    resolves = not (
        _common.is_xp_agent(input_data) or identity.is_worktree_teammate(input_data)
    )
    smm_dir = _resolve_via_init_sh() if resolves else None
    context = run(input_data, smm_dir, already_resolved=resolves)
    if context is not None:
        version = plugin_loader.plugin_version()
        source = input_data.get("source", "")
        _common.hook_output(
            "SessionStart",
            context,
            _system_message(source, version, smm_dir),
        )


if __name__ == "__main__":
    main()
    sys.exit(0)

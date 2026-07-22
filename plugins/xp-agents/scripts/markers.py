#!/usr/bin/env python3
"""Marker file infrastructure for the XP-agents plugin.

Consolidates all marker file operations (path, read, write, exists, consume)
into a single module with uniform symlink safety and atomic writes.

Marker definitions are frozen dataclass descriptors. Generic operations
accept a MarkerDef to determine file name and content strategy.
"""

import contextlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import marker_names
import tier_wire
from _append_impl import write_json_atomic, write_text_atomic
from append_validation import validate_agent_id

# ---------------------------------------------------------------------------
# MarkerDef descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarkerDef:
    """Descriptor for a marker file in the SMM directory."""

    name: str
    content_type: Literal["text", "json"]
    agent_scoped: bool = False

    def filename(self, agent_id: str = "") -> str:
        """Return the concrete filename, substituting agent_id if scoped."""
        if self.agent_scoped:
            if not agent_id:
                raise ValueError("agent_id required for agent-scoped marker")
            validate_agent_id(agent_id)
            return self.name.format(agent_id=agent_id)
        return self.name


# ---------------------------------------------------------------------------
# Marker constants
# ---------------------------------------------------------------------------

KICKOFF = MarkerDef(marker_names.KICKOFF, "text")
NEEDS_EXECUTION_PLAN = MarkerDef(marker_names.NEEDS_EXECUTION_PLAN, "text")
NEEDS_SYSTEM_CONTEXT = MarkerDef(marker_names.NEEDS_SYSTEM_CONTEXT, "text")
NEEDS_SPRINT = MarkerDef(marker_names.NEEDS_SPRINT, "text")
ACCEPT = MarkerDef(marker_names.ACCEPT, "text")
ACCEPT_IN_FLIGHT = MarkerDef(marker_names.ACCEPT_IN_FLIGHT, "text")
PLAN_AWAITING_REVIEW = MarkerDef(marker_names.PLAN_AWAITING_REVIEW, "text")
QUESTION_GATE = MarkerDef(marker_names.QUESTION_GATE, "text")
ASKING_USER = MarkerDef(marker_names.ASKING_USER, "text")
ASSIGN_PENDING = MarkerDef(marker_names.ASSIGN_PENDING, "text")
NEEDS_HOUSEKEEPING = MarkerDef(marker_names.NEEDS_HOUSEKEEPING, "text")
CLOSE_CYCLE_ACTIVE = MarkerDef(marker_names.CLOSE_CYCLE_ACTIVE, "text")
REVIEW_CADENCE = MarkerDef(marker_names.REVIEW_CADENCE, "text")
SISTER_TEST_LAYOUT_WARN = MarkerDef(marker_names.SISTER_TEST_LAYOUT_WARN, "text")
TEAMMATE_CONFIG = MarkerDef(marker_names.TEAMMATE_CONFIG, "json")
TDD_TRACKER = MarkerDef(".tdd-{agent_id}.json", "json", agent_scoped=True)
REVIEW_CYCLE = MarkerDef(".review-cycle-{agent_id}.json", "json", agent_scoped=True)
QUESTION_NUDGED = MarkerDef(marker_names.QUESTION_NUDGED, "json", agent_scoped=True)


# ---------------------------------------------------------------------------
# Generic operations
# ---------------------------------------------------------------------------


def marker_path(smm_dir: Path, marker: MarkerDef, agent_id: str = "") -> Path:
    """Return the full path to a marker file."""
    return smm_dir / marker.filename(agent_id)


def marker_exists(smm_dir: Path, marker: MarkerDef, agent_id: str = "") -> bool:
    """Check if a marker file exists (symlink-safe, validates JSON content)."""
    path = marker_path(smm_dir, marker, agent_id)
    if not path.exists() or path.is_symlink():
        return False
    if marker.content_type == "json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return isinstance(data, dict)
        except (OSError, json.JSONDecodeError, ValueError):
            return False
    return True


def marker_read(
    smm_dir: Path, marker: MarkerDef, agent_id: str = ""
) -> str | dict | None:
    """Read a marker file's content. Returns None if missing, symlink, or corrupt."""
    path = marker_path(smm_dir, marker, agent_id)
    if path.is_symlink():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    match marker.content_type:
        case "json":
            try:
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
            except (json.JSONDecodeError, ValueError):
                return None
        case "text":
            return raw.strip()


def marker_write(
    smm_dir: Path, marker: MarkerDef, data: str | dict, agent_id: str = ""
) -> None:
    """Atomically write a marker file. Rejects symlinks."""
    path = marker_path(smm_dir, marker, agent_id)
    if path.is_symlink():
        raise ValueError(f"Refusing to write to symlink: {path}")
    match marker.content_type:
        case "json":
            if not isinstance(data, dict):
                raise TypeError(f"JSON marker requires dict, got {type(data)}")
            write_json_atomic(path, data)
        case "text":
            write_text_atomic(path, data if isinstance(data, str) else str(data))


def marker_consume(
    smm_dir: Path, marker: MarkerDef, agent_id: str = ""
) -> str | dict | None:
    """Read a marker file and delete it. Returns None if missing or symlink."""
    path = marker_path(smm_dir, marker, agent_id)
    if path.is_symlink():
        return None
    result = marker_read(smm_dir, marker, agent_id)
    with contextlib.suppress(OSError):
        path.unlink()
    return result


def warn_once(
    smm_dir: Path,
    marker: MarkerDef,
    message: str,
    agent_id: str,
    *,
    severity: str = "low",
) -> bool:
    """Append a concern at most once per session, gated on a presence marker.

    Replaces the hand-rolled marker_exists / append_concern / marker_write
    dance in sprint_save._warn_sister_skip_once. The caller pre-registers
    `marker` in `_STALE_SESSION_MARKERS` so SessionStart sweeps it — that
    re-arming is what makes the "once per session" semantics honest.

    Errors are suppressed: recording a warn must never cascade into the
    caller's main operation failing. Returns True if the concern fired,
    False if the marker already existed (already-warned this session) OR
    the event failed schema validation (so the next call retries instead
    of being latched off by an orphan marker — `_common.append_safe`
    silently drops validate failures, so the only way the caller can
    detect the drop is to pre-validate here).
    """
    # Lazy import avoids loading concerns/_common at hook-module import time
    # for the many hook scripts that only need marker_exists/write/consume.
    import _append_impl
    import _common
    import concerns

    if marker_exists(smm_dir, marker):
        return False
    try:
        event = concerns.make_concern(message, severity, agent_id)
    except (TypeError, ValueError):
        return False
    # `_common.append_safe` swallows validate errors (the event is silently
    # dropped, no exception). Pre-validate so a malformed event doesn't
    # silently no-op AND latch the marker off for the rest of the session.
    if _append_impl.validate_event(event):
        return False
    with contextlib.suppress(OSError, ValueError):
        _common.append_safe(smm_dir, event)
    with contextlib.suppress(OSError, ValueError):
        marker_write(smm_dir, marker, "")
    return True


# ---------------------------------------------------------------------------
# Review cycle convenience functions (API surface for M2)
# ---------------------------------------------------------------------------

_DEFAULT_REVIEW_CYCLE: dict = {
    "last_review_commit": "",
    "simplify_done": False,
    "quality_review_done": False,
}

_REVIEW_FLAGS = frozenset({"simplify_done", "quality_review_done"})


def read_review_cycle(smm_dir: Path, agent_id: str) -> dict:
    """Read review cycle marker, returning defaults if missing."""
    data = marker_read(smm_dir, REVIEW_CYCLE, agent_id)
    if not isinstance(data, dict):
        return dict(_DEFAULT_REVIEW_CYCLE)
    return data


def write_review_cycle(smm_dir: Path, agent_id: str, data: dict) -> None:
    """Write review cycle marker."""
    marker_write(smm_dir, REVIEW_CYCLE, data, agent_id)


def reset_review_cycle(smm_dir: Path, agent_id: str, commit_hash: str) -> None:
    """Reset review cycle: new commit hash, all flags cleared."""
    data = dict(_DEFAULT_REVIEW_CYCLE)
    data["last_review_commit"] = commit_hash
    write_review_cycle(smm_dir, agent_id, data)


def set_review_flag(
    smm_dir: Path, agent_id: str, flag: str, value: bool = True
) -> None:
    """Set a single review flag (read-modify-write)."""
    if flag not in _REVIEW_FLAGS:
        raise ValueError(f"Invalid review cycle flag: {flag!r}")
    data = read_review_cycle(smm_dir, agent_id)
    data[flag] = value
    write_review_cycle(smm_dir, agent_id, data)


def review_mid_cycle(smm_dir: Path, agent_id: str) -> bool:
    """True when a review cycle is mid-flight for ``agent_id``.

    Mid-cycle = /code-review (or /simplify) has set ``simplify_done`` but
    /xp-quality-review has not yet set ``quality_review_done``. This is the
    single source of truth for both Stop gates that must defer while a review
    is in flight:

    - sprint_stop_gate defers the accept/review nudge mid-cycle.
    - close_cycle_stop_gate defers the close-reviewer nudge during the
      close /code-review's async Step 4b window.

    Load-bearing invariant: a standalone self-find review sets
    ``quality_review_done`` WITHOUT ``simplify_done`` — that is a COMPLETED
    review, not mid-cycle, so it returns False. The old ``any and not all``
    heuristic wrongly treated it as mid-cycle; keeping the predicate here
    means that invariant lives in exactly one place.
    """
    cycle = read_review_cycle(smm_dir, agent_id)
    return bool(cycle.get("simplify_done")) and not cycle.get("quality_review_done")


# ---------------------------------------------------------------------------
# Review cadence convenience functions (session-scoped: commit | story)
# ---------------------------------------------------------------------------

VALID_CADENCES = frozenset({"commit", "story"})
DEFAULT_CADENCE = "commit"


def read_review_cadence(smm_dir: Path) -> str:
    """Read the session review cadence ('commit' | 'story').

    Fail-safe to 'commit' (the careful default) when the marker is
    missing, corrupt, or holds an unrecognized value.
    """
    value = marker_read(smm_dir, REVIEW_CADENCE)
    if isinstance(value, str) and value in VALID_CADENCES:
        return value
    return DEFAULT_CADENCE


def write_review_cadence(smm_dir: Path, cadence: str) -> None:
    """Write the session review cadence. Rejects unknown values (fail loud)."""
    if cadence not in VALID_CADENCES:
        raise ValueError(f"Invalid review cadence: {cadence!r}")
    marker_write(smm_dir, REVIEW_CADENCE, cadence)


# ---------------------------------------------------------------------------
# Assign-gate scope convenience functions (ASSIGN_PENDING payload)
# ---------------------------------------------------------------------------

# The ASSIGN_PENDING payload contract, in ONE place so its writer (the
# plan-review handler in subagent_stop) and its reader (the assign gate's
# predicate in lead_gates) cannot drift apart:
#
#     sprint=<sprint_id>;stories=<id>,<id>,...
#
# Scoped-vs-legacy is a SHAPE question answered by this fixed sentinel, never
# INFERRED from the content. Markers written before the scope existed hold a
# bare agent id, and every content-sniffing rule misreads one side or the
# other: "more than one token" makes a one-story armed set — the common
# frontier shape — read as legacy, leaving the scope inert exactly where it
# matters; "contains a dash" flips `xp-plan-reviewer` to scoped; and story ids
# are unvalidated free strings (sprint_schema.validate_story only checks
# isinstance(str)), so "looks like an id in sprint.json" is both spoofable and
# wrong after a sprint rollover.
#
# The sprint id is recorded because story ids REPEAT every sprint and nothing
# sweeps this marker at a sprint boundary — a bare `story-005` armed last
# sprint would otherwise match a different `story-005` this one. Same hazard
# lead_gates._story_is_spawned defends against on the worktree side.
#
# The marker stays a "text" marker deliberately. Under a "json" MarkerDef
# marker_exists would validate the content, so a legacy text payload would
# read as ABSENT and silently disarm the gate for everyone still holding one.
_ASSIGN_SCOPE_PREFIX = "sprint="
_ASSIGN_SCOPE_SEP = ";stories="


def format_assign_scope(sprint_id: str, story_ids: list[str]) -> str:
    """Encode the stories an assign marker is being armed for."""
    return f"{_ASSIGN_SCOPE_PREFIX}{sprint_id}{_ASSIGN_SCOPE_SEP}{','.join(story_ids)}"


def read_assign_scope(smm_dir: Path, sprint_id: str) -> frozenset[str] | None:
    """The story ids ASSIGN_PENDING was armed for, or None for "no usable scope".

    None is the FAIL-CLOSED answer and every untrustworthy read collapses to
    it: the caller must then fall back to its unscoped behavior, which keeps
    the gate armed. It is returned when the marker is missing, a symlink or
    unreadable (marker_read already covers all three), when the payload
    carries no sentinel (armed before this format existed), when it names a
    DIFFERENT sprint, and when it records an EMPTY set.

    The empty set matters most: read as "nothing is armed" it would let the
    predicate delete a marker the lead still needs. It means the writer told
    us nothing, not that there is nothing to do.

    *sprint_id* is the CURRENT sprint's id; an empty one cannot identify a
    sprint, so it never establishes a match.
    """
    content = marker_read(smm_dir, ASSIGN_PENDING)
    if not isinstance(content, str) or not content.startswith(_ASSIGN_SCOPE_PREFIX):
        return None
    armed_sprint, sep, ids = content[len(_ASSIGN_SCOPE_PREFIX) :].partition(
        _ASSIGN_SCOPE_SEP
    )
    if not sep or not sprint_id or armed_sprint != sprint_id:
        return None
    story_ids = frozenset(sid for sid in ids.split(",") if sid)
    return story_ids or None


# ---------------------------------------------------------------------------
# Teammate config convenience functions (session-scoped JSON marker)
# ---------------------------------------------------------------------------

# Tier-picker vocabulary — single source in smm/tier_wire.py (shared with the
# story executor_model schema and the plan-reviewer recommended_model prose).
VALID_TEAMMATE_TOKENS = tier_wire.TEAMMATE_CONFIG_TOKENS

# Canonical models that may appear as default_model in the marker.
_VALID_TEAMMATE_MODELS = tier_wire.TEAMMATE_MODELS

_FAIL_SAFE_TEAMMATE_CONFIG: dict = {"enabled": True, "default_model": None}

_TEAMMATE_TOKEN_TO_DICT: dict[str, dict] = tier_wire.TOKEN_TO_CONFIG


def read_teammate_config(smm_dir: Path) -> dict:
    """Read the session teammate config.

    Fail-safe to {enabled: True, default_model: None} (inherit) when the
    marker is missing, corrupt, or holds an unrecognized shape. This
    preserves today's behavior — teammates spawn inheriting the orchestrator.
    """
    data = marker_read(smm_dir, TEAMMATE_CONFIG)
    if not isinstance(data, dict):
        return dict(_FAIL_SAFE_TEAMMATE_CONFIG)
    enabled = data.get("enabled")
    default_model = data.get("default_model")
    if not isinstance(enabled, bool):
        return dict(_FAIL_SAFE_TEAMMATE_CONFIG)
    if default_model is not None and default_model not in _VALID_TEAMMATE_MODELS:
        return dict(_FAIL_SAFE_TEAMMATE_CONFIG)
    return {"enabled": enabled, "default_model": default_model}


def write_teammate_config(smm_dir: Path, token: str) -> None:
    """Write the session teammate config from a canonical token.

    Rejects unknown tokens (fail loud). Valid tokens:
    off | haiku | sonnet | opus | fable | inherit
    """
    if token not in VALID_TEAMMATE_TOKENS:
        raise ValueError(f"Invalid teammate config token: {token!r}")
    marker_write(smm_dir, TEAMMATE_CONFIG, _TEAMMATE_TOKEN_TO_DICT[token])


# ---------------------------------------------------------------------------
# Session-start sweep
# ---------------------------------------------------------------------------

# Markers that should never survive across SessionStart. CLOSE_CYCLE_ACTIVE
# leaks when a close-skill aborts before the xp-close-reviewer fork; ACCEPT
# leaks after teammate-worktree close-cycle Edits when /xp-accept's
# no-reviewing-stories path skips the consume; ACCEPT_IN_FLIGHT leaks when
# /xp-accept is abandoned before its terminal dispatch (/xp-schedule or
# /xp-sprint-review completion, where accept_terminal drains it). This sweep
# is the abandonment backstop.
_STALE_SESSION_MARKERS: tuple[MarkerDef, ...] = (
    CLOSE_CYCLE_ACTIVE,
    ACCEPT,
    ACCEPT_IN_FLIGHT,
    SISTER_TEST_LAYOUT_WARN,
    TEAMMATE_CONFIG,
)


def sweep_stale_session_markers(smm_dir: Path) -> None:
    """Clear markers that should never survive across a session boundary.

    Caller must gate to fresh-start SessionStart sources only — resume
    and compact are mid-session continuations where these markers may
    be load-bearing for in-flight close-skills or pending /xp-accept.
    """
    for marker in _STALE_SESSION_MARKERS:
        marker_consume(smm_dir, marker)


# ---------------------------------------------------------------------------
# Agent cleanup
# ---------------------------------------------------------------------------

_AGENT_SCOPED_MARKERS: tuple[MarkerDef, ...] = (
    TDD_TRACKER,
    REVIEW_CYCLE,
    QUESTION_NUDGED,
)


def cleanup_agent_markers(smm_dir: Path, agent_id: str) -> None:
    """Remove all agent-scoped marker files for the given agent."""
    for marker in _AGENT_SCOPED_MARKERS:
        path = marker_path(smm_dir, marker, agent_id)
        with contextlib.suppress(OSError):
            path.unlink()


# ---------------------------------------------------------------------------
# Generic CLI: write|consume <NAME>
# ---------------------------------------------------------------------------


# Allowlist of markers writable/consumable via the CLI. Every other
# non-agent-scoped marker (KICKOFF, ASSIGN_PENDING, PLAN_AWAITING_REVIEW,
# etc.) has its own deterministic writer in a hook or skill — the CLI is
# intentionally NOT a back door for those flows.
# Add a marker here only when a skill prose step needs to drive it.
# ACCEPT_IN_FLIGHT: armed by xp-accept's preload via this CLI. The consume is
# hook-driven (accept_terminal clears it on accept's terminal /xp-schedule or
# /xp-sprint-review dispatch; the SessionStart sweep is the backstop) — no prose
# consume step, but it stays allowlisted because the preload still arms it here.
_CLI_ALLOWLIST = frozenset({"CLOSE_CYCLE_ACTIVE", "ACCEPT_IN_FLIGHT"})


def main(argv: list[str] | None = None) -> int:
    # Lazy import: markers.py loads on every hook invocation; argparse is
    # CLI-only and pulls in textwrap/gettext/re.
    import argparse

    parser = argparse.ArgumentParser(description="Marker file CLI")
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("action", choices=("write", "consume"))
    parser.add_argument(
        "name",
        choices=sorted(_CLI_ALLOWLIST),
        help="MarkerDef constant name (CLI-allowlisted markers only)",
    )
    args = parser.parse_args(argv)

    # argparse choices=_CLI_ALLOWLIST has already rejected unknown
    # names — getattr is guaranteed to resolve a MarkerDef constant
    # since the allowlist names mirror module attributes.
    marker = getattr(sys.modules[__name__], args.name)

    smm_dir = Path(args.smm_dir)
    match args.action:
        case "write":
            marker_write(smm_dir, marker, "")
        case "consume":
            marker_consume(smm_dir, marker)
    return 0


if __name__ == "__main__":
    sys.exit(main())

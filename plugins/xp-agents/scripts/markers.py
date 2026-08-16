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
import session_scope
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
    # One file per session rather than one per SMM dir. The SMM is shared
    # across worktrees and windows, so a single file would be
    # last-writer-wins between concurrent sessions. Resolved from the
    # environment at every call (never cached — the answer depends on
    # os.environ), so a marker written by one session is unaddressable to
    # another rather than silently clobbered.
    session_scoped: bool = False

    def filename(self, agent_id: str = "") -> str:
        """Return the concrete filename, substituting agent_id if scoped."""
        if self.agent_scoped:
            if not agent_id:
                raise ValueError("agent_id required for agent-scoped marker")
            validate_agent_id(agent_id)
            return self.name.format(agent_id=agent_id)
        if self.session_scoped:
            return session_scope.scoped_name(
                self.name, session_scope.resolve_session_id()
            )
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
# Session-scoped record of having armed the gate above. Text, not json: the
# shell `write_marker` wrapper the work-selection preload uses passes a string,
# and a json marker's TypeError would vanish inside its `2>/dev/null || true`.
# MarkerDef.filename() resolves the session id in Python, so the shell side
# needs no session knowledge.
HOUSEKEEPING_ARMED = MarkerDef(
    marker_names.HOUSEKEEPING_ARMED, "text", session_scoped=True
)
CLOSE_CYCLE_ACTIVE = MarkerDef(marker_names.CLOSE_CYCLE_ACTIVE, "text")
# The running close's id, written by all four close preloads and read by the
# appender's pre-write path to tag concerns. Text, not json: the shell
# `write_marker` wrapper every preload uses passes a string, and a json
# marker's TypeError would vanish inside its `2>/dev/null || true`.
CLOSE_CYCLE_ID = MarkerDef(marker_names.CLOSE_CYCLE_ID, "text", session_scoped=True)
REVIEW_CADENCE = MarkerDef(marker_names.REVIEW_CADENCE, "text")
SISTER_TEST_LAYOUT_WARN = MarkerDef(marker_names.SISTER_TEST_LAYOUT_WARN, "text")
TEAMMATE_CONFIG = MarkerDef(marker_names.TEAMMATE_CONFIG, "json")
HOOK_HEARTBEAT = MarkerDef(marker_names.HOOK_HEARTBEAT, "json")
HOUSEKEEPING_IN_FLIGHT = MarkerDef(marker_names.HOUSEKEEPING_IN_FLIGHT, "json")
TDD_TRACKER = MarkerDef(".tdd-{agent_id}.json", "json", agent_scoped=True)
REVIEW_CYCLE = MarkerDef(".review-cycle-{agent_id}.json", "json", agent_scoped=True)
# Separate from REVIEW_CYCLE because the two are keyed on DIFFERENT checkouts:
# the flags on the session that ran the review, this on the repo the commit
# lands in. One file forced every site to pick one owner for both, and the two
# only coincide while the session commits into its own checkout.
REVIEW_WATERMARK = MarkerDef(
    ".review-watermark-{agent_id}.json", "json", agent_scoped=True
)
# What the last review LOOKED AT, so its own fixes don't read as unreviewed work
# next commit. Keyed on the REPO like the WATERMARK: it holds relative paths.
REVIEW_COVERAGE = MarkerDef(
    ".review-coverage-{agent_id}.json", "json", agent_scoped=True
)
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
    `marker` in `session_markers._STALE_SESSION_MARKERS` so SessionStart
    sweeps it — that re-arming is what makes the "once per session"
    semantics honest.

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
# Agent cleanup
# ---------------------------------------------------------------------------

_AGENT_SCOPED_MARKERS: tuple[MarkerDef, ...] = (
    TDD_TRACKER,
    REVIEW_CYCLE,
    REVIEW_WATERMARK,
    REVIEW_COVERAGE,
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
# CLOSE_CYCLE_ID: written by the close preloads (through `write_marker`, which
# carries content the CLI's `write` cannot), consumed by the shared
# close-pipeline prose at the end of the cycle — that consume step is why it is
# allowlisted. CONSUME ONLY: `write` stores an empty id, and an empty id is
# worse than no marker. The appender's reader treats a marker that exists but
# yields no id as an armed-but-broken close and says so on stderr for EVERY
# concern that follows — the loud line that matters, fired continuously until
# the operator learns to ignore it.
_CLI_ALLOWLIST = frozenset({"CLOSE_CYCLE_ACTIVE", "ACCEPT_IN_FLIGHT", "CLOSE_CYCLE_ID"})
_CLI_CONSUME_ONLY = frozenset({"CLOSE_CYCLE_ID"})


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

    # `choices` cannot express "this name only for that action", so the
    # per-action refusal lands here. parser.error exits non-zero with the
    # message — a silent no-op would leave the caller believing it armed
    # something.
    if args.action == "write" and args.name in _CLI_CONSUME_ONLY:
        parser.error(
            f"{args.name} is consume-only via this CLI: `write` would store an "
            f"empty value, which reads as a broken record downstream"
        )

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

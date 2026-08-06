#!/usr/bin/env python3
"""Shared helpers for all hook scripts.

DRY module providing SMM resolution, hook I/O, recursion prevention,
event reading, and watermark management.
"""

import shlex
import sys
from pathlib import Path, PurePosixPath

# Make smm/ importable so we can use _append_impl as the foundational module
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import event_schema as _es
from _append_impl import (
    PRIORITY_ASSUMED,  # noqa: F401
    PRIORITY_BLOCKING,  # noqa: F401
    PRIORITY_INFO,  # noqa: F401
    now_iso,
    write_watermark,  # noqa: F401
)
from _append_impl import resolve_smm_dir as _resolve_smm_dir_impl
from _append_impl import (
    write_json_atomic as _write_json_atomic,
)
from append_validation import validate_smm_dir
from hook_io import (  # noqa: F401 — re-exported by _common for hook scripts
    BlockedError,
    block_output,
    hook_output,
    log_hook_error,
    read_hook_input,
    truncate,
)

# ---------------------------------------------------------------------------
# Event type and priority constants
# ---------------------------------------------------------------------------

# Event types — unprefixed aliases for ergonomics in scripts/. Source of
# truth lives in event_schema.EVENT_TYPE_*; aliasing eliminates the
# parallel-drift class (a prior hand-maintained mirror missed
# session_summary entirely until the schema-budget-derivation cleanup
# caught it).
COMMIT = _es.EVENT_TYPE_COMMIT
CUSTOMER_INPUT = _es.EVENT_TYPE_CUSTOMER_INPUT
CUSTOMER_INTENT = _es.EVENT_TYPE_CUSTOMER_INTENT
DEBT = _es.EVENT_TYPE_DEBT
GOAL = _es.EVENT_TYPE_GOAL
STATUS = _es.EVENT_TYPE_STATUS
DECISION = _es.EVENT_TYPE_DECISION
CONVENTION = _es.EVENT_TYPE_CONVENTION
CONCERN = _es.EVENT_TYPE_CONCERN
DISCOVERY = _es.EVENT_TYPE_DISCOVERY
QUESTION = _es.EVENT_TYPE_QUESTION
ANSWER = _es.EVENT_TYPE_ANSWER
ASSUMPTION = _es.EVENT_TYPE_ASSUMPTION
SESSION_END = _es.EVENT_TYPE_SESSION_END
SESSION_STARTED = _es.EVENT_TYPE_SESSION_STARTED
SESSION_SUMMARY = _es.EVENT_TYPE_SESSION_SUMMARY
SPRINT = _es.EVENT_TYPE_SPRINT
RETROSPECTIVE = _es.EVENT_TYPE_RETROSPECTIVE

# Shared data-file name used across the retrospective subsystem:
# written by scripts/retrospective.py, consumed by the xp-retrospective
# agent, cleaned up by scripts/save_retrospective.py.
RETRO_INPUT_FILENAME = ".retro-input.json"

# Event types that count as actionable unresolved work. Used by the
# honesty signal in /xp-end-session.
PROBE_RESOLVABLE_TYPES = (CONCERN, DEBT, DISCOVERY)


def _last_index_of_type(events: list[dict], etype: str) -> int:
    """Return index of the last event of `etype`, or -1 if none.

    Reverse-scan so complexity is O(events-since-last-match). Foundational
    helper for boundary scans (last SESSION_END, last COMMIT, etc.).
    """
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("type") == etype:
            return i
    return -1


# Fallback cap when no SESSION_STARTED anchor exists. Mirrors
# draft_summary._NO_BOUNDARY_TAIL_CAP by value but kept independent: this one
# caps an index window for current_session_start_index, that one caps a
# summary slice — coupling their tuning would conflate two concerns.
_NO_ANCHOR_TAIL_CAP = 200


def current_session_start_index(events: list[dict]) -> int:
    """Return index of the first event in the current session.

    The current session begins at the most recent SESSION_STARTED event,
    which is itself the first event of that session — so its own index is
    the answer (no +1). The slice events[idx:] therefore INCLUDES the
    anchor, which is intentional: all callers filter by content type inside
    the window. When no anchor exists, return 0 for short logs and a
    positive tail cap (len - _NO_ANCHOR_TAIL_CAP) for long ones, so an
    unbounded "current session" doesn't swallow the whole event log.

    Boundary asymmetry vs the sister `current_session_start_ts`: this
    returns an index whose slice is anchor-INCLUSIVE, while `_ts` is used
    with `e["ts"] > start_ts` which is anchor-EXCLUSIVE. Both are correct
    for their callers — index callers type-filter the window (the anchor is
    a SIBLING_ARTIFACT they ignore), ts callers want events strictly after
    the boundary. A raw-iterating index consumer would see the anchor.
    """
    idx = _last_index_of_type(events, SESSION_STARTED)
    if idx >= 0:
        return idx
    return max(0, len(events) - _NO_ANCHOR_TAIL_CAP)


def current_session_start_ts(events: list[dict]) -> str:
    """Return ts of the most recent SESSION_STARTED event, or "" if none.

    Sister of `current_session_start_index` — returns the boundary
    timestamp instead of the index. Use when callers need a ts comparison
    (e.g., filter by `e["ts"] > start_ts`, which EXCLUDES the anchor —
    unlike the index sister whose slice includes it; see its docstring).
    """
    idx = _last_index_of_type(events, SESSION_STARTED)
    return events[idx].get("ts", "") if idx >= 0 else ""


def uncommitted_event_count(events: list[dict]) -> int:
    """Count actionable unresolved events newer than the most recent commit.

    Only types in PROBE_RESOLVABLE_TYPES (concern/debt/discovery) count.
    Orchestration events (status, goal, retrospective, sprint, decision,
    question, answer, session_summary, etc.) are excluded — they aren't
    actionable work items, and counting them turns the honesty signal
    into noise the user learns to ignore.
    """
    last_commit_idx = _last_index_of_type(events, COMMIT)
    return sum(
        1
        for e in events[last_commit_idx + 1 :]
        if e.get("type") in PROBE_RESOLVABLE_TYPES
    )


def subagent_started_content(agent_id: str) -> str:
    """Canonical content string for subagent start events."""
    return f"Subagent {agent_id} started"


def subagent_completed_content(agent_id: str) -> str:
    """Canonical content string for subagent completion events."""
    return f"Subagent {agent_id} completed"


# Question priorities imported from _append_impl at module level


# ---------------------------------------------------------------------------
# SMM path resolution
# ---------------------------------------------------------------------------


def resolve_smm_dir() -> Path | None:
    """Return the SMM directory or None. Delegates to _append_impl.

    NOTHING here is cached — neither the env-var read nor the init.sh
    subprocess in `_derive_smm_dir` (see its own docstring: a process-local
    cache is unsafe when derivation depends on cwd/env tests may mutate, and
    each hook is a fresh `python3` so it would never hit anyway). Callers on a
    hot path should resolve ONCE and thread the result, not re-call.

    Note: when $SMM_DIR is unset and derivation runs, init.sh creates/seeds
    the SMM directory if it doesn't exist (first-call side effect). When
    $SMM_DIR is set, the env value is returned as-is with no I/O.
    """
    return _resolve_smm_dir_impl()


# ---------------------------------------------------------------------------
# Hook I/O — see hook_io.py (re-exported above by this module)
# ---------------------------------------------------------------------------


# Stays here (not in hook_io.py) because tests patch it as
# patch.object(_common, "_MAX_STDIN_SIZE", ...); hook_io.read_hook_input
# looks it up dynamically off this module so the patch takes effect.
_MAX_STDIN_SIZE = 10_485_760  # 10 MB — large enough to absorb lefthook output


# ---------------------------------------------------------------------------
# Recursion prevention
# ---------------------------------------------------------------------------


def is_xp_agent_id(agent: str) -> bool:
    """True for one of the plugin's own subagents, by name — sole owner of the
    `xp-` prefix rule. Hook payloads go through `is_xp_agent`; bare names (an
    event-log `agent_id`, an already-extracted `agent_type`) come here."""
    return isinstance(agent, str) and agent.startswith("xp-")


def is_xp_agent(input_data: dict) -> bool:
    """Check if this is one of our own agent hooks (xp- prefix)."""
    return is_xp_agent_id(input_data.get("agent_type", ""))


def is_task_notification(prompt: str) -> bool:
    """Check if a prompt is a background agent task-notification, not user input."""
    return isinstance(prompt, str) and prompt.strip().startswith("<task-notification>")


# ---------------------------------------------------------------------------
# Event reading — locked helper
# ---------------------------------------------------------------------------


_WATERMARK_ID_LOAD_EVENTS = "load-events-with-resolutions"


def read_events_locked(smm_dir: Path, slug: str) -> list[dict]:
    """Read events.jsonl under shared flock without advancing the watermark.

    Canonical helper for the
    read_delta_full(smm_dir, slug, update_watermark=False)[0] pattern.
    `slug` is passed to read_delta_full as its `agent_id` — both name a
    watermark scoping key, not a literal agent identifier.
    """
    import read_delta

    return read_delta.read_delta_full(smm_dir, slug, update_watermark=False)[0]


def load_events_with_resolutions(
    smm_dir: Path,
) -> tuple[list[dict], dict]:
    """Read events.jsonl under shared flock and compute resolutions in one call."""
    import resolution

    events = read_events_locked(smm_dir, _WATERMARK_ID_LOAD_EVENTS)
    return events, resolution.compute_resolutions(events)


# ---------------------------------------------------------------------------
# SMM directory validation (imported from _append_impl, with convenience wrapper)
# ---------------------------------------------------------------------------


def try_validate_smm_dir(smm_dir: Path | None) -> Path | None:
    """Validate SMM dir, returning None on failure instead of raising."""
    if smm_dir is None:
        return None
    try:
        validate_smm_dir(smm_dir)
        return smm_dir
    except ValueError:
        return None


def get_validated_smm_dir(smm_dir: Path | None = None) -> Path | None:
    """Resolve and validate SMM directory in one call.

    Combines resolve_smm_dir() + try_validate_smm_dir() to replace
    the 3-line boilerplate pattern used in 24+ hook scripts.
    """
    if smm_dir is None:
        smm_dir = resolve_smm_dir()
    return try_validate_smm_dir(smm_dir)


def extract_file_path(tool_name: str, tool_input: dict) -> str | None:
    """Extract file_path from tool_input for write tools."""
    if tool_name in ("Write", "Edit", "MultiEdit"):
        return tool_input.get("file_path")
    return None


def make_event(event_type: str, agent_id: str, content: str, **extra) -> dict:
    """Build a minimal SMM event dict with standard fields."""
    from event_builder import extract_refs_suffix, generate_id

    event = {
        "id": generate_id(),
        "ts": now_iso(),
        "type": event_type,
        "agent_id": agent_id,
        "content": content,
        "schema_version": 1,
    }
    event.update(extra)
    extract_refs_suffix(event)
    return event


def count_unresolved_concerns(events: list[dict]) -> int:
    """Count concern events that have no resolution."""
    import resolution

    concern_ids = {e["id"] for e in events if e.get("type") == CONCERN and e.get("id")}
    if not concern_ids:
        return 0
    resolved = resolution.compute_resolutions(events)["resolved_concern_ids"]
    return len(concern_ids - resolved)


def write_json_atomic(file_path: Path, data: dict) -> None:
    """Atomic JSON write: tempfile + chmod 600 + rename.

    Caller must ensure file_path.parent is a validated SMM directory.
    Rejects symlink targets to prevent symlink-based overwrites.
    """
    if file_path.is_symlink():
        raise ValueError(f"Refusing to write to symlink: {file_path}")
    _write_json_atomic(file_path, data)


def _run_duplicate_debt_probe(smm_dir: Path, event: dict) -> None:
    """Post-write probe: if event is debt, check for near-duplicates."""
    try:
        import duplicate_debt_probe

        duplicate_debt_probe.run_probe_and_append(smm_dir, event)
    except ImportError:
        pass


def append_safe(smm_dir: Path, event: dict) -> None:
    """Validate and append event. A drop is always logged, never silent.

    Both drop paths — schema-invalid and lock-timeout — go through
    log_hook_error, which mirrors to stderr AND to hook_errors.jsonl. The
    schema branch used to drop with no signal at all: an event missing a
    required field simply never appeared, and the failure looked like nothing
    at all (a marker that never lands is indistinguishable from a marker that
    was never meant to land). Callers must not have to pre-validate to find
    out; that workaround is what this logging replaces.
    """
    import _append_impl

    errors = _append_impl.validate_event(event)
    if errors:
        log_hook_error(
            f"append_safe dropped schema-invalid event: {'; '.join(errors)}",
            error_class="SchemaValidationError",
            event_id=event.get("id"),
            event_type=event.get("type"),
        )
        return

    try:
        _append_impl.append_event(smm_dir, event)
    except _append_impl.LockTimeoutError as e:
        log_hook_error(
            f"append_safe dropped event: {e}",
            error_class=type(e).__name__,
            event_id=event.get("id"),
            event_type=event.get("type"),
        )
    else:
        _run_duplicate_debt_probe(smm_dir, event)


def parse_append_sh_args(command: str) -> dict[str, str]:
    """Parse an append.sh invocation into {flag_name: flag_value}.

    Returns an empty dict when the command is not an append.sh call or
    cannot be tokenized. Uses shlex so any quoting shape round-trips cleanly.

    Cheap substring gate first: this hook fires on every Bash command,
    and shlex.split on a 10k-char heredoc is wasteful when we can skip.
    The token match checks the filename exactly (via PurePosixPath.name)
    so sibling scripts like `fake-append.sh` do not false-positive.
    """
    if "append.sh" not in command:
        return {}
    try:
        tokens = shlex.split(command)
    except ValueError:
        return {}
    for i, tok in enumerate(tokens):
        if PurePosixPath(tok).name == "append.sh":
            rest = tokens[i + 1 :]
            break
    else:
        return {}
    result: dict[str, str] = {}
    j = 0
    while j < len(rest):
        t = rest[j]
        if not t.startswith("--"):
            j += 1
            continue
        # Boolean flag: next token is another --flag or we're at the end.
        if j + 1 >= len(rest) or rest[j + 1].startswith("--"):
            result[t[2:]] = ""
            j += 1
        else:
            result[t[2:]] = rest[j + 1]
            j += 2
    return result


def bulk_append_safe(smm_dir: Path, events: list[dict]) -> None:
    """Filter invalid events, then bulk-append valid ones atomically.

    LockTimeoutError and ValueError are logged + swallowed: the underlying
    write is best-effort (the caller is a hook that must not crash) but
    every dropped batch leaves a structured trace in hook_errors.jsonl.
    """
    import _append_impl

    valid = [e for e in events if not _append_impl.validate_event(e)]
    if not valid:
        return
    try:
        _append_impl.bulk_append(smm_dir, valid)
    except (_append_impl.LockTimeoutError, ValueError) as e:
        log_hook_error(
            f"bulk_append_safe dropped {len(valid)} event(s): {e}",
            error_class=type(e).__name__,
            event_types_sample=[ev.get("type") for ev in valid[:5]],
        )
    else:
        for event in valid:
            _run_duplicate_debt_probe(smm_dir, event)


# Coordination: see coordination.py
# Concerns/conflicts: see concerns.py


# ---------------------------------------------------------------------------
# SMM content wrapping (security: structural delimiters for additionalContext)
# ---------------------------------------------------------------------------


def wrap_smm_context(content: str) -> str:
    """Wrap SMM content in XML tags for safe injection."""
    return f"<smm-context>\n{content}</smm-context>"


# Code-file classification: see code_files.py
# Git-commit detection: see git_commits.py


# Debt lookup: see concerns.py


# write_watermark imported from _append_impl at module level

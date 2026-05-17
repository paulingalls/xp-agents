#!/usr/bin/env python3
"""Concern detection, conflict analysis, semantic references, and debt lookup.

Extracted from _common.py to keep modules focused on a single responsibility.
"""

import bisect
import re
import sys
from collections.abc import Callable
from pathlib import Path

# Ensure smm/ and scripts/ are importable
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent))

import _common
import resolution
from _common import (
    ASSUMPTION,
    CONCERN,
    CONVENTION,
    DEBT,
    DECISION,
    DISCOVERY,
    PRIORITY_BLOCKING,
    QUESTION,
    SESSION_END,
    STATUS,
    bulk_append_safe,
    current_session_start_index,
    make_event,
)
from event_schema import (
    METADATA_KEY_RESOLVES,
    METADATA_KEY_SUPERSEDES,
    get_required_budget,
)
from worktree import normalize_path

_WATERMARK_ID_HAS_UNRESOLVED = "concerns-has-unresolved"
_WATERMARK_ID_RESOLVE = "concerns-resolve"

# ---------------------------------------------------------------------------
# Test concern pattern (shared by bash_post_tool.py and tdd_stop_gate.py)
# ---------------------------------------------------------------------------

TEST_CONCERN_RE = re.compile(
    r"Test (?:failures? detected|run failed|command failed)", re.IGNORECASE
)

# Extracts the topic from a superseded-decision concern. Must stay in
# lockstep with the concern content emitted by pattern #5 below —
# "Superseded decision: topic 'X' has multiple decisions..."
_SUPERSEDED_TOPIC_RE = re.compile(r"^Superseded decision: topic '([^']+)'")

LINT_CONCERN_PREFIX = "Lint errors in "
LINT_RESOLVED_PREFIX = "Lint concern resolved"
TEST_COMMAND_FAILED_PREFIX = "Test command failed"
TEST_FAILURES_PREFIX = "Test failures detected"


def extract_lint_concern_path(content: str) -> str | None:
    """Return the file path embedded in a lint-concern content, or None.

    Concern content shape: "Lint errors in <path>:<details>". Path may be
    relative ("src/app.py") or absolute ("/abs/path/src/app.py") during the
    transition from absolute to project-relative paths.
    """
    if not content.startswith(LINT_CONCERN_PREFIX):
        return None
    return content[len(LINT_CONCERN_PREFIX) :].split(":", 1)[0]


def lint_concern_matches(content: str, rel_path: str) -> bool:
    """Match lint concern for a file, handling both relative and absolute formats.

    During the transition from absolute to project-relative paths, old concerns
    have "Lint errors in /abs/path/src/app.py:" and new ones have
    "Lint errors in src/app.py:". This matcher handles both.
    """
    path_part = extract_lint_concern_path(content)
    if path_part is None:
        return False
    return path_part == rel_path or path_part.endswith("/" + rel_path)


def _find_unresolved(
    events: list[dict],
    matcher: Callable[[str], object],
    resolutions: dict | None = None,
) -> list[dict]:
    """Return unresolved concern events whose content matches *matcher*."""
    if not any(
        e.get("type") == CONCERN and matcher(e.get("content", "")) for e in events
    ):
        return []
    if resolutions is None:
        resolutions = resolution.compute_resolutions(events)
    resolved_ids = resolutions["resolved_concern_ids"]
    return [
        e
        for e in events
        if e.get("type") == CONCERN
        and e.get("id", "") not in resolved_ids
        and matcher(e.get("content", ""))
    ]


def filter_by_session_age(
    events: list[dict],
    min_session_ends: int,
    resolutions: dict | None = None,
    session_end_positions: list[int] | None = None,
) -> list[dict]:
    """Return open concerns whose first appearance is >= min_session_ends
    SESSION_END markers ago.

    Used by session_end's stale-concern sweep to flag long-lived concerns
    for human triage at the next /xp-kickoff retro. Resolved concerns
    (per resolution.compute_resolutions) are excluded. Pass `resolutions`
    AND/OR `session_end_positions` when the caller already computed them
    to avoid the redundant pass over events.
    """
    if resolutions is None:
        resolutions = resolution.compute_resolutions(events)
    resolved_ids = resolutions["resolved_concern_ids"]
    if session_end_positions is None:
        session_end_positions = [
            i for i, e in enumerate(events) if e.get("type") == SESSION_END
        ]
    total_ends = len(session_end_positions)
    return [
        e
        for i, e in enumerate(events)
        if e.get("type") == CONCERN
        and e.get("id", "") not in resolved_ids
        and total_ends - bisect.bisect_right(session_end_positions, i)
        >= min_session_ends
    ]


def has_unresolved_concerns(
    smm_dir: Path,
    matcher: Callable[[str], object],
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> bool:
    """Check whether any unresolved concern matches *matcher*."""
    if events is None:
        events = _common.read_events_locked(smm_dir, _WATERMARK_ID_HAS_UNRESOLVED)
    return len(_find_unresolved(events, matcher, resolutions)) > 0


def resolve_concerns(
    smm_dir: Path,
    matcher: Callable[[str], object],
    agent_id: str,
    label: str,
    events: list[dict] | None = None,
    resolutions: dict | None = None,
    extra_metadata: dict | None = None,
) -> bool:
    """Auto-resolve unresolved concerns whose content matches *matcher*.

    *matcher* receives the event's ``content`` string; any truthy return
    means it matches (works with both ``re.search`` and ``str.startswith``).

    *extra_metadata* is merged into each resolver event's metadata — used
    by callers (e.g. lint resolution) to attach an action discriminator
    alongside the resolves link.

    Returns True if any concerns were resolved.
    """
    if events is None:
        events = _common.read_events_locked(smm_dir, _WATERMARK_ID_RESOLVE)

    unresolved = _find_unresolved(events, matcher, resolutions)
    if not unresolved:
        return False

    base_metadata = extra_metadata or {}
    bulk_append_safe(
        smm_dir,
        [
            make_event(
                STATUS,
                agent_id,
                f"{label}: {c['content'][:60]}",
                working_on=[],
                metadata={**base_metadata, METADATA_KEY_RESOLVES: [c["id"]]},
            )
            for c in unresolved
        ],
    )
    return True


# ---------------------------------------------------------------------------
# Conflict detection (shared by post_tool_use.py and subagent_stop.py)
# ---------------------------------------------------------------------------


def make_concern(
    content: str,
    severity: str,
    agent_id: str,
    references: list[str] | None = None,
    files: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a concern event dict.

    `references` attaches WEAK cascade links.
    `files` records affected file paths for file-overlap resolution.
    `metadata` carries discriminators (e.g. flagged_stale) consumed by
    sweepers and retros.
    """
    extra: dict = {"severity": severity}
    if references:
        extra["references"] = references
    if files:
        extra["files"] = files
    if metadata:
        extra["metadata"] = metadata
    return make_event(CONCERN, agent_id, content, **extra)


def detect_conflicts(
    events: list[dict],
    agent_id: str,
    file_path: str | None = None,
    cwd: str | None = None,
) -> list[dict]:
    """Detect structural conflicts in the event log. Returns concern event dicts.

    When file_path/cwd are None, skip pattern 1 (overlapping working_on).
    Deduplicates: skips concerns whose content already exists in the event log.
    """
    # Collect existing concern state for deduplication and escalation.
    resolutions = resolution.compute_resolutions(events)
    resolved_ids = resolutions["resolved_concern_ids"]
    # Single-pass scan of concern events builds three parallel dedup/escalation
    # structures: content-based dedup (existing_unresolved), refs-based dedup
    # for per-root suppression (existing_unresolved_ref_sets — Pattern 2 emits
    # N concerns when N discoveries cite the same assumption with distinct
    # snippet text; content-only dedup misses), and resolved-recurrence counts
    # for severity escalation. Empty `references` (Pattern 1) skips the
    # ref-dedup set entirely.
    existing_unresolved: set[str] = set()
    existing_unresolved_ref_sets: set[tuple[str, ...]] = set()
    resolved_content_counts: dict[str, int] = {}
    for e in events:
        if e.get("type") != CONCERN:
            continue
        content = e.get("content", "")
        if e.get("id", "") in resolved_ids:
            resolved_content_counts[content] = (
                resolved_content_counts.get(content, 0) + 1
            )
            continue
        existing_unresolved.add(content)
        refs = e.get("references")
        if refs:
            existing_unresolved_ref_sets.add(tuple(sorted(refs)))
    concerns: list[dict] = []

    def _add_concern(
        content: str,
        severity: str,
        references: list[str] | None = None,
        files: list[str] | None = None,
    ) -> None:
        """Append concern only if no unresolved duplicate exists.

        Dedup is two-pronged: skip when the same content already exists
        unresolved, OR when an unresolved concern already references the
        same root set. The ref check catches per-emitter content drift
        (e.g., N teammate agents quoting distinct discovery snippets
        against one assumption).

        Escalates severity based on recurrence: each prior resolved
        instance of the same content bumps severity (low → medium → high).
        `references` attaches a WEAK cascade link to the root event(s) so
        compute_resolutions can close the flag when the root closes.
        """
        if content in existing_unresolved:
            return
        ref_key = tuple(sorted(references)) if references else None
        if ref_key and ref_key in existing_unresolved_ref_sets:
            return
        prior_count = resolved_content_counts.get(content, 0)
        if prior_count >= 2:
            severity = "high"
        elif prior_count >= 1:
            severity = "medium"
        concerns.append(
            make_concern(
                content,
                severity,
                agent_id,
                references=references,
                files=files,
            )
        )
        existing_unresolved.add(content)
        if ref_key:
            existing_unresolved_ref_sets.add(ref_key)

    # 1. Overlapping working_on — another agent claims same file
    if file_path is not None and cwd is not None:
        normalized = normalize_path(file_path, cwd)
        agent_files: dict[str, list[str]] = {}
        for e in events:
            if e.get("type") == STATUS and "working_on" in e:
                agent_files[e.get("agent_id", "")] = e["working_on"]

        for aid, files in agent_files.items():
            if aid == agent_id:
                continue
            norm_files = {normalize_path(f, cwd) for f in files}
            if normalized in norm_files:
                _add_concern(
                    f"Overlapping working_on: agent '{aid}' is also working on "
                    f"'{file_path}'. Coordinate to avoid conflicts.",
                    "medium",
                    files=[normalized],
                )

    # 2. Assumption contradicted by discovery
    assumptions: dict[str, dict] = {}
    for e in events:
        if e.get("type") == ASSUMPTION:
            assumptions[e.get("id", "")] = e
        elif e.get("type") == DISCOVERY:
            for ref in e.get("references", []):
                if ref in assumptions:
                    # Template = 57 chars; split remaining budget across both texts
                    _budget = get_required_budget(CONCERN)
                    _max_text = (_budget - 57) // 2
                    a_text = assumptions[ref]["content"][:_max_text]
                    d_text = e["content"][:_max_text]
                    _add_concern(
                        f"Assumption contradicted: '{a_text}' "
                        f"contradicted by discovery '{d_text}'.",
                        "high",
                        references=[assumptions[ref]["id"]],
                    )

    # 3. Convention violation — decision diverges from convention on same topic
    conventions_by_topic: dict[str, list[dict]] = {}
    for e in events:
        if e.get("type") == CONVENTION:
            topic = e.get("topic", "")
            conventions_by_topic.setdefault(topic, []).append(e)

    for e in events:
        if e.get("type") == DECISION:
            topic = e.get("topic", "")
            if topic in conventions_by_topic:
                refs = set(e.get("references", []))
                conv_ids = {c["id"] for c in conventions_by_topic[topic]}
                if not refs & conv_ids:
                    _add_concern(
                        f"Convention violation: decision on '{topic}' "
                        "diverges from established convention.",
                        "medium",
                        references=[c["id"] for c in conventions_by_topic[topic]],
                    )

    # 4. Stale question — blocking question with no answer after 20+ subsequent events
    question_positions: dict[str, int] = {}
    for i, e in enumerate(events):
        if e.get("type") == QUESTION and e.get("priority") == PRIORITY_BLOCKING:
            question_positions[e.get("id", "")] = i

    answered_ids = resolutions["answered_question_ids"]

    total = len(events)
    for qid, pos in question_positions.items():
        if qid not in answered_ids and (total - pos - 1) >= 20:
            _add_concern(
                f"Stale question: blocking question (id {qid}) has not been answered.",
                "medium",
                references=[qid],
            )

    # 5. Superseded decision — two decisions on same topic with no concern between.
    # Scoped to the current session window: cross-session re-citations of
    # stable topics (e.g. execution-mode, css-prefix-convention) are NOT
    # flagged. Topics whose prior in-window superseded-decision concerns
    # have been resolved are treated as "accepted as additive".
    # Trade-off: a topic acceptance recorded in a prior session is dropped
    # at the window boundary — if the same topic gets a new in-session pair
    # next session, it'll re-fire and require re-acceptance. The cross-
    # session noise reduction outweighs the re-acceptance friction.
    session_events = events[current_session_start_index(events) :]
    # Indices below (concern_pos_list, decisions_by_topic positions)
    # are slice-relative to session_events, NOT the full event log.
    decisions_by_topic: dict[str, list[tuple[int, dict]]] = {}
    concern_pos_list: list[int] = []
    already_accepted_topics: set[str] = set()
    for i, e in enumerate(session_events):
        if e.get("type") == DECISION:
            topic = e.get("topic", "")
            decisions_by_topic.setdefault(topic, []).append((i, e))
        elif e.get("type") == CONCERN:
            concern_pos_list.append(i)
            if e.get("id", "") in resolved_ids:
                m = _SUPERSEDED_TOPIC_RE.match(e.get("content", ""))
                if m:
                    already_accepted_topics.add(m.group(1))

    # concern_pos_list is already sorted (built in event order)
    # Only flag the most recent pair per topic — not every historical pair
    for topic, decs in decisions_by_topic.items():
        if len(decs) < 2:
            continue
        if topic in already_accepted_topics:
            continue
        prev_pos, prev_dec = decs[-2]
        curr_pos, curr_dec = decs[-1]

        # Explicit override: curr decision's metadata.supersedes OR
        # metadata.resolves references the prior decision (full ID or 8+
        # char prefix match, mirroring resolution.resolve_prefix's short-ID
        # convention). Both keys count: `resolves` triggers the cascade
        # auto-closer (STRONG link), so flagging the prior as unresolved
        # would contradict the link hierarchy.
        meta = curr_dec.get("metadata", {})
        declarations = (meta.get(METADATA_KEY_SUPERSEDES) or []) + (
            meta.get(METADATA_KEY_RESOLVES) or []
        )
        prev_id = prev_dec.get("id", "")
        if prev_id and any(
            prev_id == s or prev_id.startswith(s) or s.startswith(prev_id)
            for s in declarations
        ):
            continue

        # Binary search: any concern position in (prev_pos, curr_pos)?
        lo = bisect.bisect_right(concern_pos_list, prev_pos)
        has_concern_between = (
            lo < len(concern_pos_list) and concern_pos_list[lo] < curr_pos
        )
        if not has_concern_between:
            _add_concern(
                f"Superseded decision: topic '{topic}' has multiple "
                f"decisions without an intervening concern.",
                "low",
                references=[prev_id] if prev_id else None,
            )

    return concerns


# ---------------------------------------------------------------------------
# Semantic reference enrichment (shared by post_tool_use.py and plan_review.py)
# ---------------------------------------------------------------------------


def _file_list_contains(paths: list, normalized_target: str, cwd: str) -> bool:
    """Check if any path in list matches normalized_target after normalization."""
    for f in paths:
        if isinstance(f, str):
            try:
                if normalize_path(f, cwd) == normalized_target:
                    return True
            except (ValueError, OSError):
                continue
    return False


def find_related_decisions(events: list[dict], file_path: str, cwd: str) -> list[str]:
    """Find event IDs of decisions/conventions that reference this file."""
    normalized = normalize_path(file_path, cwd)
    related: list[str] = []

    for e in events:
        if e.get("type") not in (DECISION, CONVENTION):
            continue
        # Check working_on field
        working_on = e.get("working_on", [])
        if isinstance(working_on, list) and _file_list_contains(
            working_on, normalized, cwd
        ):
            related.append(e["id"])
            continue
        # Check references field for normalized path matches
        refs = e.get("references", [])
        if isinstance(refs, list) and _file_list_contains(refs, normalized, cwd):
            related.append(e["id"])

    return related


# ---------------------------------------------------------------------------
# Debt lookup
# ---------------------------------------------------------------------------


def find_issues_for_file(events: list[dict], file_path: str, cwd: str) -> list[dict]:
    """Filter debt and concern events whose files array includes the target file."""
    normalized_target = normalize_path(file_path, cwd)
    return [
        e
        for e in events
        if e.get("type") in (DEBT, CONCERN)
        and isinstance(e.get("files"), list)
        and _file_list_contains(e["files"], normalized_target, cwd)
    ]

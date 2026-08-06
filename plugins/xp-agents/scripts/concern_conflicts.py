#!/usr/bin/env python3
"""Conflict detection split out of concerns.py.

Structural conflict detection (working_on overlap, contradicted assumptions,
convention violations, stale questions, superseded decisions) plus the
semantic-reference helpers it shares with ``find_related_decisions``.
Extracted to keep concerns.py under its 500-line budget.

Re-exported from ``concerns`` for back-compat; importers can use either
``from concerns import detect_conflicts`` or ``from concern_conflicts import
detect_conflicts``.
"""

import bisect
import re
import sys
from pathlib import Path

# Ensure smm/ and scripts/ are importable
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent))

import resolution
from _common import (
    ASSUMPTION,
    CONCERN,
    CONVENTION,
    DECISION,
    DISCOVERY,
    PRIORITY_BLOCKING,
    QUESTION,
    STATUS,
    current_session_start_index,
    is_xp_agent_id,
    make_event,
)
from event_schema import (
    METADATA_KEY_REFUTES,
    METADATA_KEY_RESOLVES,
    METADATA_KEY_SUPERSEDES,
    get_required_budget,
)
from worktree import normalize_path

# Extracts the topic from a superseded-decision concern. Must stay in
# lockstep with the concern content emitted by pattern #5 below —
# "Superseded decision: topic 'X' has multiple decisions..."
_SUPERSEDED_TOPIC_RE = re.compile(r"^Superseded decision: topic '([^']+)'")

# Topics that legitimately accrue multiple decisions per session as part of
# the standard workflow. /xp-schedule records execution-mode per frontier;
# users may also re-decide mid-session when scope shifts. Cross-session
# scoping already filters re-citations across SESSION_END boundaries, but
# in-session pairs would trip the detector without this exemption.
# Shared with pre_tool_bash._same_topic_decisions_context so the pre-write
# nudge stays silent on the same topics.
SUPERSEDED_DECISION_EXEMPT_TOPICS: frozenset[str] = frozenset({"execution-mode"})


def _declares_id(meta: dict, target_id: str, *keys: str) -> bool:
    """True if any of *keys* in an event's metadata names *target_id*.

    The one prefix-tolerant id matcher, shared by every "did this event declare
    something about that one" question in this module. Prefix-tolerant in BOTH
    directions to honor the short-ID convention (mirrors
    resolution.resolve_prefix), and empty/falsy declared entries are skipped so
    a stray ``['']`` — which ``startswith("")``-matches every id in the log —
    can't blanket-match.

    Callers must pass a non-empty *target_id*: the same empty-string rule cuts
    the other way round, making ``s.startswith("")`` vacuously true for any
    declaration at all. The two call sites below both guard it. A declaration
    that is not a LIST declares nothing, and only ``resolves`` is type-checked
    at write time — so ``{"refutes": "<id>"}``, the bare string an author writes
    with the brackets dropped, reaches here and iterates as single CHARACTERS,
    each a one-char prefix matching roughly one id in sixteen.
    """
    return any(
        s and (target_id == s or target_id.startswith(s) or s.startswith(target_id))
        for key in keys
        for s in (meta[key] if isinstance(meta.get(key), list) else [])
        if isinstance(s, str)
    )


def _declares_supersession(meta: dict, target_id: str) -> bool:
    """True if an event's metadata declares it supersedes/resolves *target_id*.

    OR semantics across ``metadata.supersedes`` and ``metadata.resolves`` —
    either key counts. Suppresses Pattern 2 (a discovery that has already
    settled the assumption is not an open contradiction) and Pattern 5
    (superseded decision).
    """
    return _declares_id(meta, target_id, METADATA_KEY_SUPERSEDES, METADATA_KEY_RESOLVES)


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
    `metadata` carries discriminators consumed by conflict detectors and
    retros.
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
    # Single-pass scan of concern events builds four parallel dedup/escalation
    # structures: content-based dedup (existing_unresolved), refs-based dedup
    # for per-root suppression (existing_unresolved_ref_sets — Pattern 2 emits
    # N concerns when N discoveries cite the same assumption with distinct
    # snippet text; content-only dedup misses), resolved-recurrence counts
    # for severity escalation (resolved_content_counts), and the flat set of
    # individual ref-ids acknowledged by RESOLVED concerns (resolved_ref_ids).
    # Empty `references` (Pattern 1) skips both ref structures.
    existing_unresolved: set[str] = set()
    existing_unresolved_ref_sets: set[tuple[str, ...]] = set()
    resolved_content_counts: dict[str, int] = {}
    # Individual ref-ids acknowledged by RESOLVED concerns. Pattern 2
    # (assumption contradicted) uses this to stop re-firing: the
    # assumption+discovery events are immutable, so once a human resolves the
    # contradiction it carries no new signal — re-raising (and escalating via
    # resolved_content_counts) every scan is pure noise. Stored flat (not as
    # whole-set tuples) so a resolved concern referencing the assumption
    # alongside other ids still marks the assumption acknowledged. Global, not
    # session-windowed: unlike Pattern 5's decision pairs, an immutable-id
    # contradiction can never become new signal.
    resolved_ref_ids: set[str] = set()
    for e in events:
        if e.get("type") != CONCERN:
            continue
        content = e.get("content", "")
        if e.get("id", "") in resolved_ids:
            resolved_content_counts[content] = (
                resolved_content_counts.get(content, 0) + 1
            )
            refs = e.get("references")
            if refs:
                resolved_ref_ids.update(refs)
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
            # Skip self, and skip the plugin's own subagents: this pattern is
            # about two INDEPENDENT actors racing one file, and an xp-* claim
            # is a subagent working the diff in hand — a reviewer handed the
            # very diff being committed reads as a rival otherwise. Same `xp-`
            # rule the hooks use for recursion prevention.
            #
            # The skip is on the id alone, deliberately: the SMM is shared
            # across worktrees, so ANOTHER teammate's reviewer is suppressed
            # too. Accepted, because the events carry no reliable ownership
            # fence — the session index anchors on the most recent
            # SESSION_STARTED, which may be a different worktree's — and a
            # false negative on a rare relayed claim beats the false positive
            # this fired on every commit. The teammate's OWN id is not xp-*
            # prefixed, so the cross-worktree conflict still fires on it.
            if aid == agent_id or is_xp_agent_id(aid):
                continue
            norm_files = {normalize_path(f, cwd) for f in files}
            if normalized in norm_files:
                _add_concern(
                    f"Overlapping working_on: agent '{aid}' is also working on "
                    f"'{file_path}'. Coordinate to avoid conflicts.",
                    "medium",
                    files=[normalized],
                )

    # 2. Assumption contradicted by discovery — on a DECLARED refutation only.
    #
    # `metadata.refutes` is the trigger, and `references` deliberately is NOT.
    # event_schema makes `references` mandatory and non-empty on every
    # discovery, so a field every discovery must fill cannot carry a claim about
    # any one of them: a discovery that CONFIRMS an assumption references it
    # identically to one that falsifies it. Firing on the bare reference filed
    # three high-severity false concerns in this project's own log — one
    # confirmation, two pairs on unrelated subjects, and zero true positives.
    #
    # The narrowing changes the fail direction on purpose: an author who
    # forgets to declare now loses a flag, where before every author who
    # recorded a discovery gained a false one. Confirmation and refutation are
    # indistinguishable in structure at the reference, and the only other place
    # to look would be the natural-language content — a keyword list that would
    # not survive another project's prose.
    assumptions: dict[str, dict] = {}
    for e in events:
        if e.get("type") == ASSUMPTION:
            assumptions[e.get("id", "")] = e
        elif e.get("type") == DISCOVERY:
            meta = e.get("metadata") or {}
            # Cheap gate before the per-assumption scan: the overwhelming
            # majority of discoveries declare no refutation at all.
            if not meta.get(METADATA_KEY_REFUTES):
                continue
            for assumption_id, assumption in assumptions.items():
                # Empty target: `s.startswith("")` is vacuously true, so an
                # assumption with a missing id would match ANY declaration.
                # Mirrors Pattern 5's prev_id guard.
                if not assumption_id:
                    continue
                if not _declares_id(meta, assumption_id, METADATA_KEY_REFUTES):
                    continue
                # Acknowledged: a prior RESOLVED contradiction for this
                # assumption already exists — stop re-firing (and escalating).
                if assumption_id in resolved_ref_ids:
                    continue
                # Already settled forward by this same discovery: supersession
                # /resolution is the mechanism, not an open conflict.
                if _declares_supersession(meta, assumption_id):
                    continue
                # Template = 57 chars; split remaining budget across both texts
                _budget = get_required_budget(CONCERN)
                _max_text = (_budget - 57) // 2
                a_text = assumption["content"][:_max_text]
                d_text = e["content"][:_max_text]
                _add_concern(
                    f"Assumption contradicted: '{a_text}' "
                    f"contradicted by discovery '{d_text}'.",
                    "high",
                    references=[assumption_id],
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
        if topic in SUPERSEDED_DECISION_EXEMPT_TOPICS:
            continue
        prev_pos, prev_dec = decs[-2]
        curr_pos, curr_dec = decs[-1]
        prev_id = prev_dec.get("id", "")

        # Explicit override: curr decision's metadata declares it supersedes/
        # resolves ANY earlier same-topic decision (see _declares_supersession),
        # not just the immediately-prior one. `resolves` triggers the cascade
        # auto-closer (STRONG link), so flagging an earlier decision as
        # unresolved would contradict the link hierarchy. The `(d.get("id") or
        # "")` guard is required: _declares_supersession(meta, "") is
        # vacuously True (empty-string startswith), so an earlier decision
        # with a missing/empty id must never be treated as superseded.
        meta = curr_dec.get("metadata", {})
        if any(
            (d.get("id") or "") and _declares_supersession(meta, d["id"])
            for _, d in decs[:-1]
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

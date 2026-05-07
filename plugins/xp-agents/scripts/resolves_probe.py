#!/usr/bin/env python3
"""Resolves-trailer probe: find open concerns/debts a commit should auto-link.

Called by:
- pre_tool_bash.run (pre-commit nudge + status event)
- pre_tool_skill.run (quality-review pre-skill probe)
"""

import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import commits
import worktree
from duplicate_debt_probe import STOPWORDS
from event_schema import (
    METADATA_KEY_CLOSE_CYCLE_ID,
    METADATA_KEY_CLOSE_MODE,
    METADATA_KEY_PROBE_CANDIDATES,
    METADATA_KEY_PROBE_SELECTION_REASONS,
    METADATA_KEY_PROBE_SNAPSHOT_MAX_TS,
    METADATA_KEY_PROBE_TAIL_TS,
    SELECTION_REASON_CLOSE_MODE,
    SELECTION_REASON_FILE_OVERLAP,
    SELECTION_REASON_IN_SPRINT_BATCH,
    SELECTION_REASON_KEYWORD,
    SELECTION_REASON_RECENCY,
    STATUS_CONTENT_RESOLVES_PROBE,
)

PROBE_CANDIDATE_LIMIT = 5
_KEYWORD_MATCH_CAP = 5
_RECENCY_DAYS = 5
_TOKEN_RE = re.compile(r"[^a-z0-9_]+")

# Force events.jsonl re-read when caller's snapshot is older than this many
# seconds vs now_ts. Closes the spurious-`newer-than-snapshot` divert
# (sprint-067 retro saw 3) where the agent picked an event that landed on
# disk between snapshot and commit. 5s comfortably exceeds inter-agent race
# windows without triggering reload churn for normal load-and-pass-down.
_SNAPSHOT_STALENESS_THRESHOLD_SECONDS = 5

# Shared trailer-reminder text used by pre_tool_bash in both the soft-nudge
# (parts.append) and hard-block (BlockedError body) paths. Centralized so
# wording stays in lockstep with the trailer-extraction conventions in
# `commits.extract_resolves_trailer`.
TRAILER_REMINDER = (
    "Add Resolves-Event: <id> or Resolves-Event: none to your commit message"
)


def _extract_keywords(text: str) -> set[str]:
    """Tokenize text → lowercase set, drop stopwords and tokens <3 chars."""
    if not text:
        return set()
    tokens = _TOKEN_RE.split(text.lower())
    return {t for t in tokens if len(t) >= 3 and t not in STOPWORDS}


def _events_max_ts(events: list[dict]) -> str:
    """Newest ts in events (lex-compare on ISO-8601 strings); "" when empty.

    ISO-8601 strings lex-compare in chronological order at same precision —
    cheaper than parsing every event's ts. Reused by snapshot/tail telemetry
    capture in find_probe_candidates and the staleness check.
    """
    return max((e.get("ts") or "" for e in events), default="")


def _is_events_snapshot_stale(events: list[dict], now_ts: str) -> tuple[bool, str]:
    """Return (is_stale, max_ts).

    is_stale: True when the newest event in `events` is meaningfully older
    than now_ts. Caller-supplied `events` snapshots can drift behind disk
    between the caller's load and probe time (other agents writing to
    events.jsonl, pre-commit hook latency between subagent emission and
    commit). When that drift exceeds _SNAPSHOT_STALENESS_THRESHOLD_SECONDS,
    the probe re-reads from disk so the candidate set covers events the
    agent plausibly saw on disk by commit time.

    max_ts: the newest event ts (also returned so callers don't iterate
    events a second time for the same value). "" when events is empty.

    is_stale=False on missing/malformed inputs — fail-safe degrades to
    "trust the caller's snapshot" rather than gratuitous re-reads.
    """
    max_ts = _events_max_ts(events) if events else ""
    if not events or not now_ts or not max_ts:
        return (False, max_ts)
    try:
        now_dt = datetime.fromisoformat(now_ts)
        max_dt = datetime.fromisoformat(max_ts)
    except ValueError:
        return (False, max_ts)
    is_stale = (now_dt - max_dt).total_seconds() > _SNAPSHOT_STALENESS_THRESHOLD_SECONDS
    return (is_stale, max_ts)


def _is_recent(event_ts: str, now_ts: str) -> bool:
    """True if event_ts is within _RECENCY_DAYS of now_ts.

    Computes cutoff = (now_date - _RECENCY_DAYS) via timedelta, then lex-compares
    ISO date prefixes (yyyy-mm-dd lex order matches calendar order).
    """
    if not event_ts or not now_ts:
        return False
    event_date = event_ts[:10]
    try:
        now_date = date.fromisoformat(now_ts[:10])
        cutoff = (now_date - timedelta(days=_RECENCY_DAYS)).isoformat()
    except ValueError:
        return False
    return event_date >= cutoff


def _metadata_field(event: dict, key: str) -> str | None:
    """Read event.metadata[key]; None when missing or metadata is not a dict.

    Centralized accessor so every metadata-key reader doesn't repeat the
    `event.get("metadata") or {} → isinstance guard → .get(key) or None`
    shape. Coerces empty-string to None so callers can use `if value:`
    truthiness without re-handling the empty case.
    """
    metadata = event.get("metadata") or {}
    if not isinstance(metadata, dict):
        return None
    return metadata.get(key) or None


def _find_active_cycle_id(events: list[dict], now_ts: str) -> str | None:
    """Return the close_cycle_id of the most-recent recent concern carrying one.

    The "active cycle" is the close-reviewer batch the current commit is
    plausibly working through. Defined as the close_cycle_id of the
    newest concern within _RECENCY_DAYS of now_ts that has the metadata
    key set. Returns None when no such concern exists — keeps the new
    in-sprint-batch axis dormant outside live close cycles.

    Newest-wins tie-break: with concurrent teammate close cycles, the
    "active" cycle is whichever wrote most recently. From a fix-commit's
    perspective in another worktree this is non-deterministic — siblings
    of an older concurrent cycle drop out of the candidate set when a
    newer cycle's concern lands. Acceptable today (probe candidates are
    a hint, not a contract), but if cycle-stickiness becomes load-bearing,
    scope active_cycle_id to events whose source_branch matches the
    current branch (close-reviewer concerns carry `metadata.source_branch`).
    """
    newest_ts = ""
    newest_cycle: str | None = None
    for e in events:
        if e.get("type") != _common.CONCERN:
            continue
        cycle = _metadata_field(e, METADATA_KEY_CLOSE_CYCLE_ID)
        if not cycle:
            continue
        ts = e.get("ts") or ""
        if not _is_recent(ts, now_ts):
            continue
        if ts > newest_ts:
            newest_ts = ts
            newest_cycle = cycle
    return newest_cycle


def _ts_sort_key(candidate: dict) -> float:
    """Convert ISO ts to float for descending sort. Missing/unparseable → 0."""
    ts = candidate.get("ts") or ""
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return 0.0


def _count_file_overlaps(
    cand_files: object, commit_file_set: set[str], cwd: str
) -> int:
    """Count candidate files that intersect commit_file_set.

    Both the per-candidate scorer (where the count contributes to score)
    and `_matching_open_discoveries` (where >0 selects the candidate)
    need the same normalize-and-intersect loop; centralized here.
    """
    if not isinstance(cand_files, list):
        return 0
    n = 0
    for f in cand_files:
        if not isinstance(f, str):
            continue
        try:
            if worktree.normalize_path(f, cwd) in commit_file_set:
                n += 1
        except (ValueError, OSError):
            continue
    return n


def _score_candidate(
    candidate: dict,
    haystack_keywords: set[str],
    commit_file_set: set[str],
    cwd: str,
    now_ts: str,
    *,
    active_cycle_id: str | None = None,
) -> tuple[int, list[str]]:
    """Rank score + the signals that contributed.

    Returns `(score, reasons)`. Reasons are emitted in deterministic order
    (keyword, file_overlap, recency, close_mode, in_sprint_batch) so test
    assertions can pin shape. A signal contributes a reason iff it
    contributed non-zero score — score and reasons are built in lockstep
    so they cannot drift.

    haystack_keywords and commit_file_set are pre-computed once per commit by
    the caller — _score_candidate runs per candidate. commit_file_set members
    are normalized via worktree.normalize_path; candidate files are normalized
    here to match (mirrors commits.open_issues_matching_commit's intersection
    semantics so abs/rel/./ path forms all match).

    active_cycle_id (optional) is the close-reviewer cycle the current commit
    plausibly belongs to (computed once per probe by find_probe_candidates).
    Candidates carrying the same metadata.close_cycle_id score +1 and emit
    SELECTION_REASON_IN_SPRINT_BATCH — closes the divert gap where in-batch
    siblings had no file/keyword tie to the fix commit.
    """
    reasons: list[str] = []

    recency = 1 if _is_recent(candidate.get("ts") or "", now_ts) else 0

    keywords = _extract_keywords(candidate.get("content") or "")
    overlap = keywords & haystack_keywords
    # Recency multiplier: fresh concerns matching commit keywords get 3 per
    # match; stale ones get the base 2. Boost only kicks in with overlap, so
    # recency-only candidates still contribute just the +1 recency reason.
    keyword_multiplier = 3 if recency else 2
    keyword_score = min(len(overlap), _KEYWORD_MATCH_CAP) * keyword_multiplier
    if keyword_score > 0:
        reasons.append(SELECTION_REASON_KEYWORD)

    file_overlap = _count_file_overlaps(
        candidate.get("files") or [], commit_file_set, cwd
    )
    if file_overlap > 0:
        reasons.append(SELECTION_REASON_FILE_OVERLAP)

    if recency:
        reasons.append(SELECTION_REASON_RECENCY)

    provenance = 1 if _metadata_field(candidate, METADATA_KEY_CLOSE_MODE) else 0
    if provenance:
        reasons.append(SELECTION_REASON_CLOSE_MODE)

    candidate_cycle = _metadata_field(candidate, METADATA_KEY_CLOSE_CYCLE_ID)
    in_sprint_batch = 1 if active_cycle_id and candidate_cycle == active_cycle_id else 0
    if in_sprint_batch:
        reasons.append(SELECTION_REASON_IN_SPRINT_BATCH)

    return (
        keyword_score + file_overlap + recency + provenance + in_sprint_batch,
        reasons,
    )


def _matching_open_discoveries(
    events: list[dict],
    resolutions: dict,
    commit_file_set: set[str],
    cwd: str,
) -> list[dict]:
    """Open discoveries whose `files` intersect commit_file_set.

    Mirrors `commits.open_issues_matching_commit`'s intersection semantics
    for the type='discovery' subset; that helper is fixed at concern+debt
    and sits outside this story's file_domain (story-007 owns commits.py
    this sprint). Resolved discoveries fall into the `resolved_other_ids`
    bucket — gated here so a discovery already closed by a prior
    Resolves-Event trailer doesn't re-surface.
    """
    if not commit_file_set:
        return []
    resolved_other = resolutions.get("resolved_other_ids", set())
    return [
        e
        for e in events
        if e.get("type") == _common.DISCOVERY
        and e.get("id") not in resolved_other
        and _count_file_overlaps(e.get("files") or [], commit_file_set, cwd) > 0
    ]


def changed_files(cwd: str) -> list[str]:
    """Return all changed files: staged, unstaged, and untracked new."""
    files: set[str] = set()
    for cmd in (
        ["git", "diff", "HEAD", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if result.returncode == 0:
            files.update(f.strip() for f in result.stdout.splitlines() if f.strip())
    return sorted(files)


def find_probe_candidates(
    smm_dir: Path,
    commit_files: list[str],
    resolves: list[str],
    cwd: str,
    events: list[dict] | None = None,
    resolutions: dict | None = None,
    commit_message: str = "",
    now_ts: str | None = None,
    out_meta: dict | None = None,
) -> list[dict]:
    """Open concerns/debts with file overlap OR in-sprint-batch tie, ranked.

    Score combines keyword match (commit_message + file basenames vs concern
    content), file overlap, recency, close-review provenance, and an
    in-sprint-batch axis (sibling concerns from the same active close-reviewer
    cycle, surfaced even without file/keyword overlap to close the
    probe-divert gap). Sorts by score descending, ts descending as tiebreak.

    When `out_meta` is provided, the probe records snapshot/tail freshness
    telemetry into it: `out_meta["snapshot_max_ts"]` is the newest ts in
    the caller's snapshot at probe entry (BEFORE any staleness reread —
    pinned so the divert classifier can distinguish stale-snapshot from
    other divert classes); `out_meta["tail_ts"]` is the newest ts after
    the staleness check (post-reread when triggered). When they differ,
    the probe re-read disk between caller-snapshot and probe-time.
    """
    # No early-return on empty commit_files: the in-sprint-batch axis must
    # surface siblings regardless of file overlap (empty-stage commits with
    # an active cycle still get sibling candidates).
    # Load events once so both the file-match and in-cycle-sibling lookups
    # share the same snapshot — also lets us derive active_cycle_id without
    # a second disk read.
    resolved_now: str = now_ts if now_ts is not None else _common.now_iso()
    # Pin snapshot_max_ts BEFORE the staleness reread shadows the original
    # value — otherwise both timestamps equal the post-reread tail and the
    # newer-than-snapshot signal is undiagnosable. The staleness check
    # already iterates events to compute max_ts; reuse that value.
    if events is None:
        is_stale, snapshot_max_ts = False, ""
    else:
        is_stale, snapshot_max_ts = _is_events_snapshot_stale(events, resolved_now)
    if events is None or is_stale:
        events, resolutions = _common.load_events_with_resolutions(smm_dir)
    elif resolutions is None:
        import resolution

        resolutions = resolution.compute_resolutions(events)
    if out_meta is not None:
        out_meta[METADATA_KEY_PROBE_SNAPSHOT_MAX_TS] = snapshot_max_ts
        out_meta[METADATA_KEY_PROBE_TAIL_TS] = _events_max_ts(events)

    active_cycle_id = _find_active_cycle_id(events, resolved_now)

    commit_file_set: set[str] = set()
    for f in commit_files:
        try:
            commit_file_set.add(worktree.normalize_path(f, cwd))
        except (ValueError, OSError):
            continue

    open_matches = commits.open_issues_matching_commit(
        smm_dir, commit_files, cwd, events=events, resolutions=resolutions
    )
    matched_ids = {c["id"] for c in open_matches}
    discovery_matches = _matching_open_discoveries(
        events, resolutions, commit_file_set, cwd
    )
    matched_ids.update(d["id"] for d in discovery_matches)
    sibling_matches: list[dict] = []
    if active_cycle_id:
        resolved_set = (
            resolutions["resolved_concern_ids"]
            | resolutions["resolved_debt_ids"]
            | resolutions["resolved_other_ids"]
        )
        sibling_types = (_common.CONCERN, _common.DEBT, _common.DISCOVERY)
        for e in events:
            if e.get("type") not in sibling_types:
                continue
            eid = e.get("id")
            if eid in resolved_set or eid in matched_ids:
                continue
            if _metadata_field(e, METADATA_KEY_CLOSE_CYCLE_ID) == active_cycle_id:
                sibling_matches.append(e)

    unresolved = [
        c
        for c in (open_matches + discovery_matches + sibling_matches)
        if c["id"] not in resolves
    ]
    haystack_parts = [commit_message] + [Path(f).name for f in commit_files]
    haystack_keywords = _extract_keywords(" ".join(haystack_parts))
    scored = []
    for c in unresolved:
        score, reasons = _score_candidate(
            c,
            haystack_keywords,
            commit_file_set,
            cwd,
            resolved_now,
            active_cycle_id=active_cycle_id,
        )
        scored.append((score, reasons, c))
    scored.sort(key=lambda triple: (-triple[0], -_ts_sort_key(triple[2])))
    selected = scored[:PROBE_CANDIDATE_LIMIT]
    for _, reasons, c in selected:
        c["selection_reasons"] = reasons
    return [c for _, _, c in selected]


def build_nudge_lines(candidates: list[dict]) -> list[str]:
    """Format grouped nudge block with header, items, and ready-to-copy trailer.

    Wording is escape-resistant: assumes the commit closes something, with
    `Resolves-Event: none` as the explicit opt-out (not an invited bailout).
    Each item carries `[type|severity|id]` plus a `(from close-reviewer)`
    suffix when metadata.close_mode is set.
    """
    if not candidates:
        return []
    items = []
    for c in candidates:
        raw = c.get("content") or ""
        content = raw[:80] + ("..." if len(raw) > 80 else "")
        etype = c.get("type", "concern")
        # "unknown" is a display-only sentinel — never round-tripped to validation
        severity = c.get("severity") or "unknown"
        tag = f"[{etype}|{severity}|{c['id']}]"
        mode = _metadata_field(c, METADATA_KEY_CLOSE_MODE)
        suffix = f" (from {mode}-close-reviewer)" if mode else ""
        # Surface all reasons (vocabulary capped to 5 by SELECTION_REASON_*
        # contract; ~60 chars worst case fits one line). Concern 684a9d401adc:
        # capping by position would always occlude `in_sprint_batch` /
        # `close_mode` (the signals explaining WHY no-file-overlap siblings
        # surfaced — exactly what sprint-067 retro is targeting).
        reasons = c.get("selection_reasons") or []
        if reasons:
            suffix += f" (why: {', '.join(reasons)})"
        items.append(f"- {tag}: {content}{suffix}")
    ids = ", ".join(c["id"] for c in candidates)
    block = (
        "These open events overlap your staged files. "
        "Pick which your commit closes "
        "(or `Resolves-Event: none` if none apply):\n"
        + "\n".join(items)
        + f"\nReady-to-use trailer: Resolves-Event: {ids}"
    )
    return [block]


def emit_probe_status(
    smm_dir: "Path",
    candidates: list[dict],
    agent_id: str,
    probe_meta: dict | None = None,
) -> None:
    """Write a probe status event to events.jsonl.

    Emits even when `candidates` is empty IF `probe_meta` is provided —
    the zero-candidate emit is the most diagnostic case for
    newer-than-snapshot diverts (no candidate surfaced; was the snapshot
    stale?). When neither is provided, stays silent.
    """
    if not candidates and not probe_meta:
        return
    metadata: dict = {
        METADATA_KEY_PROBE_CANDIDATES: [c["id"] for c in candidates],
        METADATA_KEY_PROBE_SELECTION_REASONS: {
            c["id"]: c.get("selection_reasons", []) for c in candidates
        },
    }
    if probe_meta:
        # probe_meta keys are already METADATA_KEY_* constants (set by
        # find_probe_candidates' out_meta path) — direct merge, no
        # translation layer needed.
        metadata.update(probe_meta)
    event = _common.make_event(
        _common.STATUS,
        agent_id,
        f"{STATUS_CONTENT_RESOLVES_PROBE}: {len(candidates)} candidates",
        working_on=[],
        metadata=metadata,
    )
    _common.append_safe(smm_dir, event)

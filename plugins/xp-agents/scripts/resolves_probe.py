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
    """
    newest_ts = ""
    newest_cycle: str | None = None
    for e in events:
        if e.get("type") != "concern":
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

    cand_files = candidate.get("files") or []
    file_overlap = 0
    if isinstance(cand_files, list):
        for f in cand_files:
            if not isinstance(f, str):
                continue
            try:
                if worktree.normalize_path(f, cwd) in commit_file_set:
                    file_overlap += 1
            except (ValueError, OSError):
                continue
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
) -> list[dict]:
    """Open concerns/debts with file overlap OR in-sprint-batch tie, ranked.

    Score combines keyword match (commit_message + file basenames vs concern
    content), file overlap, recency, close-review provenance, and an
    in-sprint-batch axis (sibling concerns from the same active close-reviewer
    cycle, surfaced even without file/keyword overlap to close the
    probe-divert gap). Sorts by score descending, ts descending as tiebreak.
    """
    # No early-return on empty commit_files: the in-sprint-batch axis must
    # surface siblings regardless of file overlap (empty-stage commits with
    # an active cycle still get sibling candidates).
    # Load events once so both the file-match and in-cycle-sibling lookups
    # share the same snapshot — also lets us derive active_cycle_id without
    # a second disk read.
    if events is None:
        events, resolutions = _common.load_events_with_resolutions(smm_dir)
    elif resolutions is None:
        import resolution

        resolutions = resolution.compute_resolutions(events)

    resolved_now: str = now_ts if now_ts is not None else _common.now_iso()
    active_cycle_id = _find_active_cycle_id(events, resolved_now)

    open_matches = commits.open_issues_matching_commit(
        smm_dir, commit_files, cwd, events=events, resolutions=resolutions
    )
    matched_ids = {c["id"] for c in open_matches}
    sibling_matches: list[dict] = []
    if active_cycle_id:
        resolved_set = (
            resolutions["resolved_concern_ids"] | resolutions["resolved_debt_ids"]
        )
        for e in events:
            if e.get("type") not in ("concern", "debt"):
                continue
            eid = e.get("id")
            if eid in resolved_set or eid in matched_ids:
                continue
            if _metadata_field(e, METADATA_KEY_CLOSE_CYCLE_ID) == active_cycle_id:
                sibling_matches.append(e)

    unresolved = [
        c for c in (open_matches + sibling_matches) if c["id"] not in resolves
    ]
    haystack_parts = [commit_message] + [Path(f).name for f in commit_files]
    haystack_keywords = _extract_keywords(" ".join(haystack_parts))
    commit_file_set: set[str] = set()
    for f in commit_files:
        try:
            commit_file_set.add(worktree.normalize_path(f, cwd))
        except (ValueError, OSError):
            continue
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


def emit_probe_status(smm_dir: "Path", candidates: list[dict], agent_id: str) -> None:
    """Write a probe status event to events.jsonl."""
    if not candidates:
        return
    event = _common.make_event(
        _common.STATUS,
        agent_id,
        f"{STATUS_CONTENT_RESOLVES_PROBE}: {len(candidates)} candidates",
        working_on=[],
        metadata={
            METADATA_KEY_PROBE_CANDIDATES: [c["id"] for c in candidates],
            METADATA_KEY_PROBE_SELECTION_REASONS: {
                c["id"]: c.get("selection_reasons", []) for c in candidates
            },
        },
    )
    _common.append_safe(smm_dir, event)

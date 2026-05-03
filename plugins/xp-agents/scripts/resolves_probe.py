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
    METADATA_KEY_CLOSE_MODE,
    METADATA_KEY_PROBE_CANDIDATES,
    METADATA_KEY_PROBE_SELECTION_REASONS,
    SELECTION_REASON_CLOSE_MODE,
    SELECTION_REASON_FILE_OVERLAP,
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


def _close_mode(candidate: dict) -> str | None:
    """Return candidate's close_mode value (sprint/plan/free) or None."""
    metadata = candidate.get("metadata") or {}
    if not isinstance(metadata, dict):
        return None
    return metadata.get(METADATA_KEY_CLOSE_MODE) or None


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
) -> tuple[int, list[str]]:
    """Rank score + the signals that contributed.

    Returns `(score, reasons)`. Reasons are emitted in deterministic order
    (keyword, file_overlap, recency, close_mode) so test assertions can
    pin shape. A signal contributes a reason iff it contributed non-zero
    score — score and reasons are built in lockstep so they cannot drift.

    haystack_keywords and commit_file_set are pre-computed once per commit by
    the caller — _score_candidate runs per candidate. commit_file_set members
    are normalized via worktree.normalize_path; candidate files are normalized
    here to match (mirrors commits.open_issues_matching_commit's intersection
    semantics so abs/rel/./ path forms all match).
    """
    reasons: list[str] = []

    keywords = _extract_keywords(candidate.get("content") or "")
    overlap = keywords & haystack_keywords
    keyword_score = min(len(overlap), _KEYWORD_MATCH_CAP) * 2
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

    recency = 1 if _is_recent(candidate.get("ts") or "", now_ts) else 0
    if recency:
        reasons.append(SELECTION_REASON_RECENCY)

    provenance = 1 if _close_mode(candidate) else 0
    if provenance:
        reasons.append(SELECTION_REASON_CLOSE_MODE)

    return keyword_score + file_overlap + recency + provenance, reasons


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
    """Open concerns/debts with file overlap, ranked by score, capped.

    Score combines keyword match (commit_message + file basenames vs concern
    content), file overlap, recency, and close-review provenance. Sorts by
    score descending, ts descending as tiebreak.
    """
    open_matches = commits.open_issues_matching_commit(
        smm_dir, commit_files, cwd, events=events, resolutions=resolutions
    )
    unresolved = [c for c in open_matches if c["id"] not in resolves]
    resolved_now: str = now_ts if now_ts is not None else _common.now_iso()
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
            c, haystack_keywords, commit_file_set, cwd, resolved_now
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
        mode = _close_mode(c)
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

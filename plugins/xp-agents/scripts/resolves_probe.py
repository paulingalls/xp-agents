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
from duplicate_debt_probe import STOPWORDS
from event_schema import (
    METADATA_KEY_CLOSE_MODE,
    METADATA_KEY_PROBE_CANDIDATES,
    STATUS_CONTENT_RESOLVES_PROBE,
)

PROBE_CANDIDATE_LIMIT = 5
_KEYWORD_MATCH_CAP = 5
_RECENCY_DAYS = 7
_TOKEN_RE = re.compile(r"[^a-z0-9_]+")


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
    now_ts: str,
) -> int:
    """Rank score: keyword match + file overlap + recency + close-review boost.

    haystack_keywords and commit_file_set are pre-computed once per commit by
    the caller — _score_candidate runs per candidate.
    """
    keywords = _extract_keywords(candidate.get("content") or "")
    overlap = keywords & haystack_keywords
    keyword_score = min(len(overlap), _KEYWORD_MATCH_CAP) * 2

    cand_files = candidate.get("files") or []
    file_overlap = 0
    if isinstance(cand_files, list):
        file_overlap = sum(
            1
            for f in cand_files
            if isinstance(f, str) and Path(f).as_posix() in commit_file_set
        )

    recency = 1 if _is_recent(candidate.get("ts") or "", now_ts) else 0

    metadata = candidate.get("metadata") or {}
    provenance = (
        1 if isinstance(metadata, dict) and metadata.get(METADATA_KEY_CLOSE_MODE) else 0
    )

    return keyword_score + file_overlap + recency + provenance


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
    commit_file_set = {Path(f).as_posix() for f in commit_files}
    scored = [
        (_score_candidate(c, haystack_keywords, commit_file_set, resolved_now), c)
        for c in unresolved
    ]
    scored.sort(key=lambda pair: (-pair[0], -_ts_sort_key(pair[1])))
    return [c for _, c in scored[:PROBE_CANDIDATE_LIMIT]]


def build_nudge_lines(candidates: list[dict]) -> list[str]:
    """Format grouped nudge block with header, items, and ready-to-copy trailer."""
    if not candidates:
        return []
    items = []
    for c in candidates:
        raw = c.get("content") or ""
        content = raw[:80] + ("..." if len(raw) > 80 else "")
        items.append(f"- [{c.get('type', 'concern')}] {c['id']}: {content}")
    ids = ", ".join(c["id"] for c in candidates)
    block = (
        "Overlapping open events — add Resolves-Event trailer "
        "if this commit addresses them:\n"
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
        },
    )
    _common.append_safe(smm_dir, event)

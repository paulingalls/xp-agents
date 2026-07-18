#!/usr/bin/env python3
"""Concern detection, conflict analysis, semantic references, and debt lookup.

Extracted from _common.py to keep modules focused on a single responsibility.
"""

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
    CONCERN,
    STATUS,
    bulk_append_safe,
    make_event,
)

# Conflict-detection group (structural conflicts + semantic reference
# enrichment) lives in concern_conflicts.py to keep this module under its
# 500-line budget. Re-exported here by identity so existing importers and
# mock.patch("...concerns.detect_conflicts") sites keep working unchanged.
from concern_conflicts import (  # noqa: F401
    SUPERSEDED_DECISION_EXEMPT_TOPICS,
    detect_conflicts,
    find_related_decisions,
    make_concern,
)
from event_schema import METADATA_KEY_RESOLVES

_WATERMARK_ID_HAS_UNRESOLVED = "concerns-has-unresolved"
_WATERMARK_ID_RESOLVE = "concerns-resolve"

# ---------------------------------------------------------------------------
# Test concern pattern (shared by bash_post_tool.py and tdd_stop_gate.py)
# ---------------------------------------------------------------------------

TEST_CONCERN_RE = re.compile(
    r"Test (?:failures? detected|run failed|command failed)", re.IGNORECASE
)

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

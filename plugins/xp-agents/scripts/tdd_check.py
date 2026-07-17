#!/usr/bin/env python3
"""Shared TDD check: find the last test signal in the event log.

Extracted from tdd_stop_gate.py for reuse by TeammateIdle and
TaskCompleted hooks (M13). All three hooks need the same logic:
scan events in reverse, skip resolved concerns, return pass/fail/None.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import commits
import concerns
import resolution
from identity import extract_worktree_name, is_teammate_agent_id

# Patterns that indicate test results in status/concern events
TEST_PASS_RE = re.compile(
    r"Tests?:.*\d+\s+passed.*0\s+failed|Tests?\s+passed\b",
    re.IGNORECASE,
)
TEST_FAIL_RE = concerns.TEST_CONCERN_RE


def _session_window_start(events: list[dict], cwd: str) -> int:
    """Index of the first event in the reader's own session window.

    Only the LEAD emits `session_started` (a teammate's session_start.run
    returns early, appending no anchor of its own) — so a `session_started`
    anchor marks the LEAD's session boundary, never a teammate's. A worktree
    teammate lives exactly one session (its worktree is created fresh for one
    story and cleaned up after), so it has no "prior session" to bound
    against: reading the lead's anchor as its own window means a mid-sprint
    lead `/clear` — which appends a fresh anchor AFTER the teammate's
    still-live failure — reclassifies that failure as prior-session, and a
    teammate that already committed its work has a clean tree, silently
    un-gating a genuinely red suite. For a teammate reader the window is
    therefore always 0: every unresolved failure is "this session."

    For any other reader (the lead), the window anchors at the most recent
    `session_started` event, as before.

    Deliberately NOT `_common.current_session_start_index`: with no anchor that
    helper returns `len(events) - 200`, a TAIL CAP rather than a session
    boundary. In a safety gate a tail cap is the DISARM direction — a genuine
    in-session failure older than 200 events would silently stop blocking. With
    no anchor we scan everything instead (precedent: session_start.py's
    prior-backlog slice).
    """
    name = extract_worktree_name(cwd)
    if name and is_teammate_agent_id(name):
        return 0
    anchor = _common._last_index_of_type(events, _common.SESSION_STARTED)
    return anchor if anchor >= 0 else 0


def find_last_test_signal(events: list[dict], cwd: str = ".") -> str | None:
    """Scan events from the end. Return 'pass', 'fail', or None.

    Skips resolved concerns — a resolved test failure should not block.

    A failure from a PRIOR session gates only while the tree is DIRTY. A red
    suite plus uncommitted broken code is still broken, but once the tree is
    clean there is nothing left in the working copy for that failure to be
    about, and it would otherwise gate every future session forever. Nothing
    else un-gates it: `session_start._sweep_stale_concerns` only emits a
    flag-concern, it never resolves the original.

    ONE reverse walk, not two. A passing status has no effect on any gate except
    to short-circuit this scan before an older unresolved failure is reached —
    and that short-circuit is the only non-resolution mechanism by which a later
    green run un-gates an earlier red one. Splitting the walk at the session
    boundary would make {prior FAIL, later prior PASS, dirty tree} newly block.

    `cwd` should be the hook input's `cwd` (the project or teammate-worktree
    root), which is this codebase's authoritative source — the process cwd is a
    known leak (see conftest's `identity._process_cwd` note). It only defaults
    to "." so a caller with no hook input still works; a wrong cwd makes git
    answer nothing, and "nothing" must never read as CLEAN — see below.
    """
    resolved_ids = resolution.compute_resolutions(events)["resolved_concern_ids"]
    window_start = _session_window_start(events, cwd)

    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        content = e.get("content", "")
        etype = e.get("type", "")
        if (
            etype == _common.CONCERN
            and TEST_FAIL_RE.search(content)
            and e.get("id", "") not in resolved_ids
        ):
            if i >= window_start:
                return "fail"
            # Older than this session: the rare path, and the only one that
            # pays for a git call. `get_uncommitted_files`, not the narrower
            # `get_uncommitted_code_files` — the latter drops test files and
            # untracked files, both of which would read CLEAN and disarm the
            # gate on an uncommitted broken test.
            #
            # None means git could not answer (timeout, not a repo), which is
            # NOT the same as a clean tree. Only a positive CLEAN reading may
            # un-gate a real failure; absence of evidence keeps the teeth.
            dirty = commits.get_uncommitted_files(cwd)
            return "fail" if dirty is None or dirty else None
        if etype == _common.STATUS and TEST_PASS_RE.search(content):
            return "pass"
    return None

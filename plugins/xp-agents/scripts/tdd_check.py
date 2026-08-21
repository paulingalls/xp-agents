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
import concerns
import resolution
import worktree_state
from identity import extract_worktree_name, in_place_teammate_name, is_teammate_agent_id

# Patterns that indicate test results in status/concern events
TEST_PASS_RE = re.compile(
    r"Tests?:.*\d+\s+passed.*0\s+failed|Tests?\s+passed\b",
    re.IGNORECASE,
)
TEST_FAIL_RE = concerns.TEST_CONCERN_RE


def _reader_scope(
    events: list[dict], cwd: str, smm_dir: Path | None = None
) -> tuple[int, str | None]:
    """`(window_start, owner)` — the reader's own session window and the
    agent_id its signals must carry, or None to accept any author.

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

    But `events.jsonl` is SHARED across the lead and every sibling teammate,
    so a window of 0 alone would make a teammate gate on any unresolved
    failing-test concern in the whole log — including one authored by the
    lead or a sibling, which this teammate can neither see nor fix. A
    teammate therefore also carries an `owner` (its worktree name, which is
    the agent_id it stamps on its own events): only its OWN test signals gate
    it. The lead reads `owner=None`, which scopes it by WINDOW only — it is not
    an unfiltered read: `find_last_test_signal` applies the author filter this
    value selects, dropping the signals of agents whose working tree is not the
    lead's. `owner=None` means "not scoped to one author", never "accepts every
    author".

    A WORKTREE teammate is caught by `extract_worktree_name(cwd)` above — its
    hook process runs INSIDE the worktree, so cwd carries the
    `worktree-story-` marker. An IN-PLACE teammate (the solo behavior-table
    branch of xp-assign; `spawn_teammate --in-place`) runs in the MAIN
    checkout instead, so its cwd carries no such marker and it would
    otherwise fall through to the lead branch below — misreading the lead's
    anchor as its own window, the exact hazard this function exists to
    prevent. It is caught by a second leg: `identity.in_place_teammate_name`
    — the shared marker-guarded `XP_TEAMMATE_NAME` helper that also backs
    `identity.is_worktree_teammate` and `pre_tool_skill._is_live_teammate`.
    Deliberately NOT `is_worktree_teammate` wholesale: it also falls back to
    the process cwd (`os.getcwd()`) for its cwd leg, a documented leak this
    reader already avoids by using only the hook-supplied `cwd`. A leaked env
    var with no live marker is not trusted either (the same guard
    `in_place_teammate_name` applies) — it falls through to the lead branch
    rather than being silently treated as a teammate, which would hide the
    lead's own in-session signals behind an owner filter for a name that
    never claimed one.

    `smm_dir` locates the marker; when None `in_place_teammate_name` falls
    back to the explicit `SMM_DIR` env (NOT init.sh derivation — deriving the
    shared SMM would let a live in-place marker for a leaked `XP_TEAMMATE_NAME`
    misread the lead as a teammate). With neither a param nor the env, the
    in-place leg is unverifiable and fails closed (lead branch) — never CLOSED
    in the disarming sense, since the lead branch drops only OTHER trees'
    authors and a same-process failure is authored `main`; it only loses the
    tighter teammate-shaped window.

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
        return 0, name

    # WINDOW 0, OWNER None — and the owner is the correction. An in-place
    # teammate runs in the MAIN checkout, so it shares the lead's tree and its
    # events are authored `main` (no worktree segment for
    # `resolve_agent_id_from_cwd` to find). An owner of `XP_TEAMMATE_NAME`
    # therefore matched NOTHING and its gate never fired at all.
    #
    # Reading as the lead is not a degradation, it is the right answer: a red in
    # a tree you share IS yours, whoever ran it, and the author filter below
    # still drops a story worktree's signals for this reader as it does for the
    # lead. The window stays 0 because this teammate lives exactly one session
    # and has no prior one to bound against — that part of the leg was always
    # right.
    if in_place_teammate_name(smm_dir) is not None:
        return 0, None

    anchor = _common._last_index_of_type(events, _common.SESSION_STARTED)
    return (anchor if anchor >= 0 else 0), None


def _is_another_trees_agent(agent_id: object) -> bool:
    """Does `agent_id` name a STORY WORKTREE's agent — a tree that is not ours?

    Only asked by the LEAD's read, and named for what it actually recognises: a
    `spawn_teammate` story worktree, not "somewhere else" in general. While that
    worktree exists its signals cannot be about the lead's tree.

    NOT `isinstance`-free. The value comes off an event, and a truthy non-string
    reaching `.startswith` raises out of a Stop COMMAND hook, whose non-zero exit
    disarms the gate — the same fail-open the falsy guard was added for, one type
    away. House style is the explicit check (`hook_liveness.payload_session_id`).

    An IN-PLACE teammate needs no exemption. `spawn_teammate --in-place` runs in
    the main checkout, so its red suite IS the lead's — and its events are
    authored `main`, not its teammate name: `resolve_agent_id` prefers the
    payload field, which the harness sends only inside a subagent call, so a
    top-level in-place hook falls to `resolve_agent_id_from_cwd` and a
    main-checkout path answers `main`. The prefix test therefore already lets
    those signals through.

    THREE gaps, none of them closable by widening this predicate:

    * A subagent OF a worktree teammate authors under an opaque id (the payload
      field is populated inside a subagent call), indistinguishable from one of
      the lead's own. Filtering opaque ids would drop the lead's real failures,
      the worse error, so the false block survives there — and that is where the
      caller's coordination release still earns its keep.
    * Any other-tree agent NOT named `worktree-story-*` — a harness's own
      worktree, `extract_worktree_name`'s `explore-abc` shape, an Agent-Teams
      teammate — authors `main` and still false-blocks the lead.
    * AFTER the story merges, that code IS in the lead's tree, so an unresolved
      teammate red the lead would once have blocked on is now invisible to it.
      `close_verify_gate` is the backstop that makes this safe, not this filter.
    """
    return isinstance(agent_id, str) and is_teammate_agent_id(agent_id)


def find_last_test_signal_with_author(
    events: list[dict], cwd: str = ".", smm_dir: Path | None = None
) -> tuple[str | None, str | None]:
    """Scan events from the end. Return ('pass'|'fail'|None, author|None).

    `smm_dir` locates the in-place-teammate marker for `_reader_scope`'s env
    leg. All three hook callers (tdd_stop_gate, teammate_idle, task_completed)
    thread the SAME validated dir they read `events` from, so the marker and
    the log always come from one SMM — a caller that passes an explicit
    `smm_dir` must not have the env silently redirect half the read. Omit it
    and the leg self-resolves through `identity.in_place_teammate_name`'s
    shared validated resolver (see `_reader_scope`), which also avoids a
    second `init.sh` derivation per hook.

    The author filter below needs no dir at all: authorship is on the event.

    Skips resolved concerns — a resolved test failure should not block.

    A failure from a PRIOR session gates only while the tree is DIRTY. A red
    suite plus uncommitted broken code is still broken, but once the tree is
    clean there is nothing left in the working copy for that failure to be
    about, and it would otherwise gate every future session forever. Nothing
    else un-gates it — a prior-session failure clears only when its concern is
    resolved or its tree goes clean.

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
    window_start, owner = _reader_scope(events, cwd, smm_dir)

    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        # A worktree teammate shares the log with the lead and siblings; only
        # its OWN test signals (fail concerns AND the pass that would clear
        # them) gate it.
        if owner is not None and e.get("agent_id") != owner:
            continue
        # The LEAD (owner is None) gets the INVERSE of that filter, not no
        # filter — see `_is_another_trees_agent` for which authors and why.
        # Placed ABOVE both branches deliberately: it must drop a teammate's
        # PASS as well as its fail, or a teammate's green run short-circuits the
        # walk below and clears the lead's own red suite.
        if owner is None and _is_another_trees_agent(e.get("agent_id")):
            continue
        author = e.get("agent_id") if isinstance(e.get("agent_id"), str) else None
        content = e.get("content", "")
        etype = e.get("type", "")
        if (
            etype == _common.CONCERN
            and TEST_FAIL_RE.search(content)
            and e.get("id", "") not in resolved_ids
        ):
            if i >= window_start:
                return "fail", author
            # Older than this session: the rare path, and the only one that
            # pays for a git call. `get_uncommitted_files`, not the narrower
            # `get_uncommitted_code_files` — the latter drops test files and
            # untracked files, both of which would read CLEAN and disarm the
            # gate on an uncommitted broken test.
            #
            # None means git could not answer (timeout, not a repo), which is
            # NOT the same as a clean tree. Only a positive CLEAN reading may
            # un-gate a real failure; absence of evidence keeps the teeth.
            dirty = worktree_state.get_uncommitted_files(cwd)
            return ("fail", author) if dirty is None or dirty else (None, None)
        if etype == _common.STATUS and TEST_PASS_RE.search(content):
            return "pass", author
    return None, None


def find_last_test_signal(
    events: list[dict], cwd: str = ".", smm_dir: Path | None = None
) -> str | None:
    """The signal alone, for the callers that do not ask whose it was.

    A projection over the walk above: one reader, one walk, and a named view of
    the part most callers want. (`reader_scope_owner` was the same shape over
    `_reader_scope`'s tuple, and went when its last caller did.)

    Two of the three gates (`teammate_idle`, `task_completed`) genuinely do not
    care about authorship — they gate a single agent on its own scoped read — so
    widening their call sites would buy nothing and touch code this change has no
    business in.
    """
    return find_last_test_signal_with_author(events, cwd, smm_dir)[0]

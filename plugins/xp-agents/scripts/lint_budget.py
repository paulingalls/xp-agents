#!/usr/bin/env python3
"""Commit-time lint budget: constants, and the cut-short-vs-hung timeout message
shared by run_linter_batch and run_linter_stdin.

Split out of lint_runners.py (which crossed the 500-line cap) as a pure move for
the constants, plus the new message helper this story added — see
`docs/completed/` history for story-009 (a spent shared budget must not read as
a hung linter). lint_runners re-exports BATCH_TIMEOUT_CAP_S by identity:
lint_check.py and staged_lint.py both import it as `lint_check.X` /
`lint_runners.X`, and predate this split.
"""

import subprocess

# Commit-time, per batch (run_linter_batch): min(CAP, BASE + PER_PATH * N).
#
# NOT the edit-time number, though it once was. The two have opposite failure
# semantics: an edit-time timeout is silent, while a batch timeout is
# `unverified` and the commit gate fails CLOSED on it — it BLOCKS. And a timeout
# is the one `unverified` cause the agent cannot act on: it can install a missing
# binary, but it cannot make golangci-lint faster. Too small a budget therefore
# blocks every commit in that ecosystem, unfixably.
#
# 5s was safe only while the batch ran ruff and nothing else. The gate now
# dispatches off the linter table, so the batch runs `npx eslint`,
# `golangci-lint run`, `dart analyze` — tools whose COLD START alone (npx bin
# resolution, a TS program build, a package type-check) routinely exceeds 5s on a
# real repo. Budget for a linter that actually works; the CAP still bounds one
# that has genuinely hung.
#
# CEILING, and it is a hard one: the CAP must stay well inside the HARNESS's own
# hook timeout (60s default; pre_tool_bash registers no override). A hook the
# harness kills produces no exit 2 — so overrunning that budget does not fail
# closed, it fails OPEN, and the commit sails through unlinted. That is strictly
# worse than the block we are widening this to avoid. 40s leaves ~20s of headroom
# for the rest of the hook (tier-1 diff scan, git forks, SMM loads). Do NOT raise
# the CAP past that without raising the hook's registered timeout first.
#
# The CAP is a TOTAL, not a per-batch allowance: one commit can run several
# batches (a polyglot repo routes each file to its own linter), and N batches of
# CAP each would breach the ceiling N-fold. staged_lint_gate spends this one
# budget across all of them and passes what is left as `budget_s`; a batch with
# nothing left is UNVERIFIED, which blocks. Bound per-batch alone and the
# ceiling above is only true of a single-language repo.
BATCH_TIMEOUT_BASE_S: float = 30.0
BATCH_TIMEOUT_PER_PATH_S: float = 0.25
BATCH_TIMEOUT_CAP_S: float = 40.0

# How far short of its own ceiling a run must have stopped before its timeout
# message calls it "cut short" instead of "hung". Must exceed staged_lint's
# pre-batch overhead — the git subprocess in `_divergent_from_index` plus
# grouping, spent between `deadline = now + CAP` (staged_lint.py:345) and the
# first batch's own subprocess.run — or a saturated first batch (budget_s
# necessarily a hair under its own ceiling, purely from that overhead) would
# misread as cut short. Kept well above a typical local git-status cost so the
# margin holds on a slower disk too.
_MATERIALLY_SHORT_S: float = 5.0


def own_ceiling_s(path_count: int) -> float:
    """This run's own timeout cap, BEFORE any shared-budget narrowing.

    Lives beside the constants and beside `timeout_message`, which is the one
    thing that interprets the number: a total consumed materially under this
    ceiling is what makes a timeout read as cut short. Both runners derive it from
    here rather than each restating the formula, so the message can never
    describe a ceiling a caller computed differently. The stdin path is just
    the one-path case — it feeds a single file on stdin.
    """
    return min(
        BATCH_TIMEOUT_CAP_S,
        BATCH_TIMEOUT_BASE_S + BATCH_TIMEOUT_PER_PATH_S * path_count,
    )


def timeout_message(
    linter_name: str,
    exc: subprocess.TimeoutExpired,
    *,
    timeout: float,
    own_ceiling: float,
    budget_s: float | None,
    remedy: str | None = None,
) -> str:
    """Build the message for a run_linter_batch / run_linter_stdin timeout.

    The code cannot know WHO spent a shared clock — see the two rejected
    discriminators in lint_runners' commit history — so it never claims to.
    It states two numbers it DOES know for certain: `consumed`, how long this
    run spent in total, and `own_ceiling`, its own cap before any
    shared-budget narrowing. Which side of the margin a reading falls on, and
    what each branch may say, are pinned in test_lint_budget_margin.py.

    `fired < timeout` is the one inference that IS certain, not guessed: the
    only way a run gets less than the nominal slice it was granted is that
    `_run_with_optional_flag_retry` already spent part of that slice on a
    flag-rejected first attempt, and this is the second. Both attempts SHARE
    that one slice — the retry is handed exactly what the first left — so
    together they consumed the whole `timeout`, whatever the split. That
    total is the honest number here, and reporting the retry's remainder
    instead inverts the verdict: a cold `npx eslint` that burns 20s of a
    30.25s slice and then hangs in the remaining 10.25s spent its ENTIRE
    ceiling, yet 10.25 alone reads as cut short.

    The per-attempt split is deliberately not printed. It is knowable only as
    a difference of two numbers that normally render a hair apart ("30.2481s
    of the 30.25s"), a pair that reads as a contradiction while reconciling
    nothing. Naming the second attempt still earns its place — a rejected
    flag is worth knowing about — but the durations stay a single total.
    """
    fired = exc.timeout if exc.timeout is not None else timeout
    is_second_attempt = fired < timeout
    consumed = timeout if is_second_attempt else fired
    second_attempt_note = (
        " — this was the batch's second attempt, after its first was rejected "
        "for an unsupported flag; the duration above covers both, which shared "
        "one slice"
        if is_second_attempt
        else ""
    )

    remedy_note = f". {remedy}" if remedy else ""

    if consumed >= own_ceiling - _MATERIALLY_SHORT_S:
        return (
            f"{linter_name}: timed out after {consumed:g}s"
            f"{second_attempt_note}{remedy_note}"
        )

    budget_note = (
        f", with {budget_s:g}s left of the commit gate's "
        f"{BATCH_TIMEOUT_CAP_S:g}s shared lint budget at the start of this run"
        if budget_s is not None
        else ""
    )
    return (
        f"{linter_name}: ran {consumed:g}s against its own {own_ceiling:g}s "
        f"ceiling{budget_note} — it may have been cut short rather than hung"
        f"{second_attempt_note}{remedy_note}"
    )

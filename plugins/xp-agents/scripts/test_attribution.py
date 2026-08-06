#!/usr/bin/env python3
"""Failure attribution: who do we blame when a Bash command exits non-zero?

`test_parsing` answers "does this command name a test runner, and what did its
output say". This module answers a different question: when the command FAILED,
did the runner actually run and fail?

Those are not the same question, and conflating them is how the TDD gate came
to report "Tests are failing" for a session in which no test ever ran:

  * The runner name can appear as an ARGUMENT rather than as the executable.
    `grep -rn pytest plugins/` names pytest, is not compound, and exits 1 on
    no-match — so blaming the runner for the exit code files a high-severity
    test-failure concern for a run that never happened. (Grepping for the word
    `pytest` while investigating this bug reproduces the bug.)
  * A compound command can short-circuit BEFORE the runner. `validator && pytest`
    exiting 1 is the validator's exit code, not pytest's.

The SUCCESS path needs this module too, and for a while it was believed not to:
"exit 0 means every segment ran, so the runner passed" is false. Every segment
does run, but only `&&` carries a segment's FAILURE out to the overall exit —
`OUT=$(pytest); echo $?` exits 0 over a red suite. `exit_status_proves_runner_passed`
is that direction; the two are mirrors, not an asymmetry.

`head_token` and `ARGUMENT_CONSUMING_HEADS` — "which token of a segment is the
executable, and does it merely consume its arguments as data" — live in
`shell_exit_structure`, which grew a second caller for them. They carry no
framework knowledge, so this module holds none of the shell vocabulary and
`shell_exit_structure` holds none of the runner vocabulary.

Pure — stdlib only, no SMM dependencies.
"""

import git_commits
from shell_exit_structure import (
    ARGUMENT_CONSUMING_HEADS,
    SEGMENT_BREAK_RE,
    head_token,
    outer_exit_reaches_shell,
    shell_c_bodies,
)
from test_parsing import PARSER_STATUS_PARSED, is_test_run, parse_test_results


def is_compound(command: str) -> bool:
    """True when a shell operator introduces a second executable segment.

    Quoted operators are data, not structure — `pytest -k "a && b"` is a single
    command — so the scan runs over `git_commits.strip_quoted` output. A
    `sh -c` body is the exception: it is code, and `sh -c "cd app && pytest"`
    can short-circuit at the `cd` exactly as the unwrapped form does.
    """
    if SEGMENT_BREAK_RE.search(git_commits.strip_quoted(command)):
        return True
    return any(is_compound(body) for body in shell_c_bodies(command))


def _segments(command: str) -> list[str]:
    """Split into executable segments, ignoring operators inside quotes.

    `[::2]` drops the captured operators the split interleaves; this function
    answers "what ran", and the ordering of `sh -c` bodies APPENDED after the
    outer segments is why it cannot also answer "did the runner's exit survive"
    (see `exit_status_proves_runner_passed`).
    """
    parts = SEGMENT_BREAK_RE.split(git_commits.strip_quoted(command))[::2]
    segments = [p.strip() for p in parts if p.strip()]
    for body in shell_c_bodies(command):
        segments.extend(_segments(body))
    return segments


def _segment_framework(segment: str) -> str | None:
    """The framework this ONE segment plausibly EXECUTES, or None. A segment
    headed by an argument-consuming command merely names the runner."""
    framework = is_test_run(segment)
    if framework and head_token(segment) not in ARGUMENT_CONSUMING_HEADS:
        return framework
    return None


def _executing_frameworks(command: str):
    """Yield the framework of each segment that plausibly EXECUTES a runner,
    in command order."""
    for segment in _segments(command):
        framework = _segment_framework(segment)
        if framework:
            yield framework


def runs_test_binary(command: str, framework: str) -> bool:
    """True when some segment plausibly EXECUTES `framework` rather than
    merely mentioning it as an argument."""
    return framework in _executing_frameworks(command)


def executed_framework(command: str) -> str | None:
    """The framework of the first segment that actually runs one, or None.

    Not the same as `is_test_run(command)`, which reads the WHOLE string and
    returns the highest-precedence name anywhere in it — including one that
    appears only as data. In `cat pytest.ini && npm test` the name is pytest but
    the run is jest, and blaming the exit on a framework that never ran loses
    the failure of the one that did.
    """
    return next(_executing_frameworks(command), None)


def _runs_a_runner(text: str) -> bool:
    """Does *text* execute a test runner? The `runs_target` half of
    `shell_exit_structure.outer_exit_reaches_shell`, and the ONLY thing that
    predicate does not already know.

    `_executing_frameworks` rather than `_segment_framework` because the walk
    asks this of whole `sh -c` bodies as well as of already-split segments, and
    a body can be compound: `cat pytest.ini && npm test` reads as a `cat` when
    judged as one segment and as a jest run when split. On an already-split
    segment the two agree — there is nothing left in it to split.
    """
    return next(_executing_frameworks(text), None) is not None


def _outer_exit_proves_runner_passed(command: str) -> bool:
    """`exit_status_proves_runner_passed` for one command's own segments,
    without descending into `sh -c` bodies.

    The walk itself is `shell_exit_structure.outer_exit_reaches_shell`, which is
    pure shell structure and knows no framework names; this function supplies
    the one piece of runner knowledge it needs. Extracted so
    `worktree_differential` can ask the same structural question of a `tsc` or
    `cargo` command, where the runner-aware answer is vacuously True.
    """
    return outer_exit_reaches_shell(command, _runs_a_runner)


def exit_status_proves_runner_passed(command: str) -> bool:
    """True when an overall exit 0 genuinely proves the executed runner passed.

    The mirror of `attribute_failure`, and the premise it corrects is the one
    the note at the top of this module states for the SUCCESS path: "exit 0
    means every segment ran". Every segment does run — but only `&&` carries a
    segment's FAILURE out to the overall exit. `;` and `\\n` discard it, `||`
    masks it, a pipeline reports its last stage, a command substitution
    captures it into a string, and a trailing `&` returns before the runner has
    produced one. Live evidence: `OUT=$(pytest tests/); echo $?`
    exited 0 with a red pytest inside, and every open test-failure concern was
    resolved on the strength of that 0.

    So: exit 0 proves it iff every operator between the runner and the end of
    the command propagates failure, and the runner is not inside a capture.
    Refusing on `is_compound` instead would DEADLOCK the gate — `cd app &&
    pytest` is compound and perfectly honest, and would never clear again.

    Capture is tracked as depth, not as a flat "a `$(` appeared", which is wrong
    in both directions: `cd $(git rev-parse --show-toplevel) && pytest` closes
    its substitution BEFORE the runner (safe, and a flat scan deadlocks it),
    while `echo $(pytest)` has no operator after the runner at all (unsafe, and
    an operator-only scan clears it).

    A `sh -c` body is code, so it is judged by the same rule and the wrapper
    cannot launder a discarded exit in EITHER direction — not an operator
    inside the body (its own recursion, rather than reusing `_segments`, which
    flattens bodies in with the outer segments and discards operator position),
    and not one after the wrapper (`_outer_exit_proves_runner_passed` counts a
    body-runs-a-runner wrapper as a runner-executing segment).

    An operator with NOTHING after it discarded nothing: `pytest tests/\\n` IS
    `pytest tests/`, and a multi-line Bash block ends in a newline. Reading that
    trailing operator as a discard refused ordinary GREEN runs, so the gate
    stopped clearing and the TDD stop gate kept blocking the agent — with
    re-running in the same shape unable to fix it. That is the deadlock
    direction this predicate was written to avoid, arriving through the one
    shape nobody had tested. What makes a trailing operator harmless is the
    absence of a following command, not the operator.

    Conservative by construction, since a wrong True disarms the gate: no
    `set -o pipefail` awareness, and a runner reached through a closing token
    (`$(npm bin)/jest`) reads as captured. A command that executes no runner is
    vacuously True — there is no exit status here to have been swallowed, and
    `executed_framework` is what keeps `grep -rn pytest` from clearing.
    """
    if not _outer_exit_proves_runner_passed(command):
        return False
    return all(
        exit_status_proves_runner_passed(body) for body in shell_c_bodies(command)
    )


def parsed_failed_count(error: str, framework: str) -> int | None:
    """Failed-test count when the payload really parsed as a failing run, else
    None. Shared with `bash_failure`, which reports the count it corroborates.

    `allow_scan_fallback` because this caller is corroborating, not recording.
    The non-zero exit is evidence the parse did not produce; the only open
    question is whom to blame, so an unfamiliar summary shape must not silence
    the answer. `bash_post_tool` takes the strict default for the opposite
    reason — see `parse_test_results`.
    """
    results = parse_test_results(error, framework, allow_scan_fallback=True)
    if results["status"] == PARSER_STATUS_PARSED and results["failed"] > 0:
        return results["failed"]
    return None


def attribute_failure(command: str, error: str) -> str | None:
    """Return the framework to blame for a non-zero exit, or None when the
    exit code cannot honestly be attributed to a test run.

    None does NOT mean "tests passed" — it means "we did not observe a test
    failure", which is the only claim the exit code supports.
    """
    framework = executed_framework(command)
    if framework is None:
        return None
    if not is_compound(command):
        # A single command's exit code IS the runner's. This is what keeps the
        # gate's teeth: a bare failing `pytest` still writes the concern, with
        # or without parseable counts (segfault, collection error, OOM).
        return framework

    # Compound: the exit code may belong to any segment, so require evidence.
    #
    # This branch is LIVE, not dead code, and its liveness does not depend on
    # which stream a given runner prints to. `error` carries the failed
    # command's OUTPUT, not just its stderr — the live payloads this bug was
    # diagnosed from contain a linter's stdout diagnostics verbatim. So the
    # summary line is reachable both for runners that report on stderr
    # (jest/vitest) and for those that report on stdout (pytest et al).
    # Deleting this branch disarms the gate for every compound test failure, in
    # every language.
    return framework if parsed_failed_count(error, framework) is not None else None

#!/usr/bin/env python3
"""Does a shell command's OWN exit status reach the shell's exit status?

Purely STRUCTURAL, and that is the point. A pipe, `;`, a newline, `||`, a
background `&` or a `$(...)` capture discards or captures a command's exit
status, and which of those happened is decidable from the shell string alone.
No knowledge of what the command RUNS is needed, so the same answer holds for a
Python repo, a Rust repo, or a repo with no test runner in it at all.

Extracted from `test_attribution`, which had computed exactly this inside
`_outer_exit_proves_runner_passed` while wrapped in a per-framework runner
vocabulary. Two callers now share one owner:

  * `test_attribution.exit_status_proves_runner_passed` — "did the RUNNER's
    exit status survive", which additionally needs to know which segments run a
    runner, and is *vacuously* True when none do.
  * `worktree_differential.differential` — "is this command's exit status
    comparable across two checkouts at all", which must hold for `tsc
    --noEmit | tee log` and `cargo build | tee log` as much as for a pytest
    pipeline. The vacuous-True direction would have made that guard inert for
    every command a non-Python project declares.

`outer_exit_reaches_shell` is the shared walk, parameterized by which segments
count as "the command under measurement"; `exit_reaches_shell` is the
runner-agnostic entry point, where EVERY segment counts.

Pure — stdlib plus the leaf `git_commits.strip_quoted`, no SMM dependencies.
"""

import re

import git_commits

# Shell operators that introduce a second executable segment. Command
# substitution (`$(`/backtick) is included: its exit status can surface as the
# whole command's, so the segment before it is not unambiguously to blame.
#
# ONE alternation, three uses, deliberately. The group is CAPTURING so `.split`
# interleaves the operators with the segments — which of them matched is the
# whole question `outer_exit_reaches_shell` asks, and a second regex spelling
# the same vocabulary beside this one would drift. Drift here does not raise an
# error; it silently un-arms both callers.
#   * `.search`  — is there a break at all (`test_attribution.is_compound`)
#   * `.split`[::2] — the segments (`test_attribution._segments`)
#   * `.split`[1::2] — the operator after each segment, in order
SEGMENT_BREAK_RE = re.compile(r"(&&|\|\||;|\||\n|\$\(|`)")

# The only operator that carries a preceding failure through to the overall
# exit status: `&&` short-circuits, so the command's non-zero IS the shell's.
# `;` and `\n` discard it, `||` masks it by design, and a pipeline reports its
# LAST stage (no `pipefail` assumed — the conservative reading).
FAILURE_PROPAGATING_OPERATOR = "&&"

# Operators that OPEN a command substitution. A command inside one has its exit
# status captured into a string, so the enclosing command's exit says nothing
# about it. The backtick both opens and closes; `$(` is closed by a `)` glued
# to some later token, which is why depth is tracked rather than flat-scanned.
SUBSTITUTION_OPEN = "$("
SUBSTITUTION_BACKTICK = "`"

# Asynchronous execution: a bare `&` backgrounds the command, so the shell
# returns 0 before it has produced an exit status — the hardest-discarded exit
# there is. Deliberately NOT an entry in the segment alternation above: `2>&1`
# and `&>` are redirects, present in commands that are not compound at all, and
# teaching that alternation about `&` would change `is_compound` — and with it
# the write direction's evidence rule — for every redirect in the codebase. The
# lookaround excludes both redirect forms, and this pattern is read only here,
# where the sole consequence of a false positive is refusing.
ASYNC_RE = re.compile(r"(?<![<>&])&(?![&>])")

# A POSIX shell's `-c` argument is CODE, not data: `sh -c "pytest"` really does
# execute pytest, so quote-stripping the body away would silently stop
# reasoning about every such command — a disarm, the worse direction. The body
# is therefore scanned as an ordinary segment. Two deliberate narrowings keep
# this from becoming a new false-positive source:
#   * POSIX shells only. `python3 -c "import pytest"` and
#     `gh pr create --title "pytest fix"` quote a command they never execute.
#   * The shell must HEAD a segment (start of line or after an operator), so a
#     shell invocation quoted inside another command (`echo "sh -c 'pytest'"`)
#     stays data.
#
# ONE spelling of the invocation itself, shared with `SHELL_C_HEAD_RE` below:
# the two ask different questions of the same launcher (what is its body / does
# this segment invoke one), and a second hand-written copy is how they drift.
_SHELL_C_INVOCATION = r"(?:\S*/)?(?:ba|z|k|da)?sh\s+(?:-\w+\s+)*-\w*c"
_SHELL_C_RE = re.compile(
    r"(?:^|&&|\|\||;|\||\n)\s*" + _SHELL_C_INVOCATION + r"\s+('[^']*'|\"[^\"]*\")"
)

# The same launcher, recognized from the HEAD of an already-split segment.
# `strip_quoted` has deleted the body by then, so the segment reads as a bare
# `sh -c ` that names nothing — see `outer_exit_reaches_shell`, where a wrapper
# whose body runs the thing under measurement must still count as a measured
# segment or every operator AFTER it stops counting.
SHELL_C_HEAD_RE = re.compile(r"^" + _SHELL_C_INVOCATION + r"\b")


def shell_c_bodies(command: str) -> list[str]:
    """The code bodies of any `sh -c '<body>'` launchers heading a segment."""
    return [m.group(1)[1:-1] for m in _SHELL_C_RE.finditer(command)]


def closed_substitutions(segment: str) -> int:
    """How many enclosing command substitutions this segment CLOSES.

    The closing `)` is glued to a token instead of being a segment break, and
    it is not always the last character — `$(git rev-parse --show-toplevel)/app`
    closes mid-token — so closers are counted rather than tested for at the end.
    Parentheses opened AND closed inside the segment (a subshell) balance out
    and close nothing.
    """
    local = closers = 0
    for char in segment:
        if char == "(":
            local += 1
        elif char == ")":
            if local:
                local -= 1
            else:
                closers += 1
    return closers


def outer_exit_reaches_shell(command: str, runs_target) -> bool:
    """Does the exit status of *command*'s own measured segments reach the
    shell's, ignoring what happens inside `sh -c` bodies?

    *runs_target* answers "does THIS text run the thing whose exit status we
    care about". It is the only knowledge this walk does not have on its own,
    and the two callers answer it differently: `test_attribution` asks whether
    a test runner is executed; `exit_reaches_shell` below says yes to any
    non-empty text, because when the WHOLE command is under measurement any
    segment's discarded exit is a discarded exit.

    It is called with two kinds of text and must answer for both: an
    already-split outer segment, and a whole `sh -c` body (which may itself be
    compound). Handing a body to a segment-shaped predicate silently changes
    the answer — `cat pytest.ini && npm test` reads as a `cat` when judged as
    one segment and as a jest run when split — so the contract is stated on
    the text, not on the segment.

    A `sh -c "<body>"` whose BODY runs the target is itself a measured segment
    out here, and has to be recognized as one even though the body is gone:
    `strip_quoted` deletes it, leaving a bare `sh -c `. Without this the
    wrapper launders the very thing this predicate exists to catch —
    `sh -c "pytest" | tee log` sees nothing in the outer scan, so the pipe that
    swallowed its exit has nothing to swallow. Which body belongs to which
    wrapper is not tracked: with more than one `sh -c` in a command, any of them
    running the target arms the rule at the first — over-refusal, the safe
    direction.
    """
    parts = SEGMENT_BREAK_RE.split(git_commits.strip_quoted(command))
    segments, operators = parts[::2], parts[1::2]
    shell_c_runs_target = any(
        runs_target(body.strip()) for body in shell_c_bodies(command)
    )
    open_substitutions: list[str] = []
    target_seen = False

    for i, segment in enumerate(segments):
        stripped = segment.strip()
        runs_it = runs_target(stripped) or (
            shell_c_runs_target and SHELL_C_HEAD_RE.match(stripped) is not None
        )
        if runs_it:
            if open_substitutions:
                return False  # captured — the exit went into a string
            target_seen = True
        if target_seen and not open_substitutions and ASYNC_RE.search(stripped):
            return False  # backgrounded — the shell never waited for it
        # Checked AFTER the target, because a capture's `)` rides on the last
        # token of the very segment that runs it: `echo $(pytest)`.
        for _ in range(closed_substitutions(segment)):
            if open_substitutions and open_substitutions[-1] == SUBSTITUTION_OPEN:
                open_substitutions.pop()
        if i >= len(operators):
            break
        operator = operators[i]
        if operator == SUBSTITUTION_OPEN:
            open_substitutions.append(operator)
        elif operator == SUBSTITUTION_BACKTICK:
            # One backtick both opens and closes; which it is depends only on
            # whether one is already open.
            if open_substitutions and open_substitutions[-1] == SUBSTITUTION_BACKTICK:
                open_substitutions.pop()
            else:
                open_substitutions.append(operator)
        elif (
            target_seen
            and not open_substitutions
            and operator != FAILURE_PROPAGATING_OPERATOR
            and any(later.strip() for later in segments[i + 1 :])
        ):
            return False  # discarded — `;`, `\n`, `||` or a pipe swallowed it
        # `$(` inside a shell_c body: `strip_quoted` removed the body, so the
        # outer scan never sees it. The recursion in `exit_reaches_shell`
        # covers that leg.
    return True


def _every_segment(segment: str) -> bool:
    """Every non-empty segment is under measurement. An empty one is not a
    command — `make test\\n` splits into `make test` and ``, and the trailing
    empty segment must not arm the discard rule for the operator before it."""
    return bool(segment)


def exit_reaches_shell(command: str) -> bool:
    """True when *command*'s own exit status becomes the shell's exit status.

    The runner-agnostic entry point. Every non-empty segment counts as measured,
    so this asks the strictest honest version of the question: is there any
    operator anywhere in this command that discards or captures an exit status
    the caller might have wanted to read?

    Conservative by construction, because a wrong True is what lets a caller
    compare two runs on a number that means nothing. `cd $(git rev-parse
    --show-toplevel) && make test` reads as captured and is refused even though
    its substitution closes before the runner — the runner-aware sibling can
    afford that distinction because it knows which segment is the runner, and
    this one deliberately cannot. Refusing to measure is recoverable (declare a
    simpler command); measuring noise is not.

    A command that runs nothing is vacuously True — there is no exit status here
    to have been swallowed. Callers that need "this is a runnable command" must
    ask that separately.
    """
    if not outer_exit_reaches_shell(command, _every_segment):
        return False
    return all(exit_reaches_shell(body) for body in shell_c_bodies(command))

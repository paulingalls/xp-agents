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

Pure — stdlib only, no SMM dependencies.
"""

import re

import git_commits
from test_parsing import PARSER_STATUS_PARSED, is_test_run, parse_test_results

# Shell operators that introduce a second executable segment. Command
# substitution (`$(`/backtick) is included: its exit status can surface as the
# whole command's, so the runner is not unambiguously to blame.
#
# ONE alternation, three uses, deliberately. The group is CAPTURING so `.split`
# interleaves the operators with the segments — which of them matched is the
# whole question `exit_status_proves_runner_passed` asks, and a second regex
# spelling the same vocabulary beside this one would drift. Drift here does not
# raise an error; it silently un-arms the gate.
#   * `.search`  — is there a break at all (`is_compound`)
#   * `.split`[::2] — the segments (`_segments`)
#   * `.split`[1::2] — the operator after each segment, in order
_SEGMENT_BREAK_RE = re.compile(r"(&&|\|\||;|\||\n|\$\(|`)")

# The only operator that carries a preceding failure through to the overall
# exit status: `&&` short-circuits, so the runner's non-zero IS the command's.
# `;` and `\n` discard it, `||` masks it by design, and a pipeline reports its
# LAST stage (no `pipefail` assumed — the conservative reading).
_FAILURE_PROPAGATING_OPERATOR = "&&"

# Operators that OPEN a command substitution. A runner inside one has its exit
# status captured into a string, so the enclosing command's exit says nothing
# about it. The backtick both opens and closes; `$(` is closed by a `)` glued
# to some later token, which is why depth is tracked rather than flat-scanned.
_SUBSTITUTION_OPEN = "$("
_SUBSTITUTION_BACKTICK = "`"

# Asynchronous execution: a bare `&` puts the runner in the background, so the
# shell returns 0 before a single test has run — the hardest-discarded exit
# there is. Deliberately NOT an entry in the segment alternation above: `2>&1`
# and `&>` are redirects, present in commands that are not compound at all, and
# teaching that alternation about `&` would change `is_compound` — and with it
# the WRITE direction's evidence rule — for every redirect in the codebase. The
# lookaround excludes both redirect forms, and this pattern is read only by
# `_outer_exit_proves_runner_passed`, where the sole consequence of a false
# positive is refusing to clear.
_ASYNC_RE = re.compile(r"(?<![<>&])&(?![&>])")

# Tokens that wrap another executable without being the thing under test, mapped
# to the options each one takes a SEPARATE VALUE for. Peeled so `time grep pytest
# x` is still seen as a grep, not as a test run.
#
# The value map is what keeps the peel from eating the executable. An option zone
# holds two kinds of flag and they consume differently:
#
#   * value-taking (`sudo -u ci grep ...`) — the NEXT token is the flag's value.
#     Not skipping it leaves `ci` as the head, which is in no refusal list, so
#     the grep escapes and a no-match exit 1 is blamed on the runner it grepped
#     for.
#   * boolean (`time -p grep ...`) — the next token IS the executable. Skipping
#     it eats `grep` and leaves `pytest` as the head: same false attribution,
#     arrived at from the opposite direction.
#
# So neither blanket rule is safe, and "consume the value too" — which this did
# unconditionally — is not the conservative choice it looks like. The set of
# wrappers is small, closed, and ours; enumerating their value-taking options is
# the only thing that answers both. An option NOT listed for a wrapper is treated
# as boolean and consumes nothing; `--opt=value` carries its own value and never
# consumes the next token either.
_WRAPPER_VALUE_OPTS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "-C", "-S", "--unset", "--chdir", "--split-string"}),
    "sudo": frozenset(
        {"-u", "-g", "-p", "-C", "-U", "-h", "-r", "-t", "--user", "--group",
         "--prompt", "--close-from", "--other-user", "--host", "--role", "--type"}
    ),
    "time": frozenset({"-o", "-f", "--output", "--format"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "nohup": frozenset(),
    "command": frozenset(),
    "exec": frozenset({"-a"}),
    "stdbuf": frozenset({"-i", "-o", "-e", "--input", "--output", "--error"}),
    "xargs": frozenset(
        {"-n", "-I", "-i", "-P", "-d", "-s", "-E", "-e", "-L", "-a", "--max-args",
         "--replace", "--max-procs", "--delimiter", "--max-chars", "--eof",
         "--max-lines", "--arg-file"}
    ),
}  # fmt: skip
_WRAPPER_TOKENS = frozenset(_WRAPPER_VALUE_OPTS)

# Commands that CONSUME a runner name as data (a search pattern, a filename)
# instead of executing it. When one of these heads the segment, the runner
# token is an argument and the exit code is not the runner's.
#
# This is a refusal list, NOT a whitelist of launchers, and the direction is
# deliberate: an unrecognized head still attributes (today's behavior, gate
# keeps its teeth), whereas an unrecognized LAUNCHER in a whitelist would
# silently stop attributing — a disarm, which is the far worse failure. The
# `test_every_framework_still_attributed` control pins that direction.
_ARGUMENT_CONSUMING_HEADS = frozenset(
    {
        "grep", "egrep", "fgrep", "rg", "ripgrep", "ag", "ack", "git",
        "sed", "awk", "cat", "echo", "printf", "head", "tail", "less", "more",
        "find", "ls", "wc", "sort", "uniq", "cut", "tr", "diff", "jq",
    }
)  # fmt: skip

_ASSIGNMENT_RE = re.compile(r"^\w+=")

# A POSIX shell's `-c` argument is CODE, not data: `sh -c "pytest"` really does
# execute pytest, so quote-stripping the body away would silently stop
# attributing every such failure — a disarm, the worse direction. The body is
# therefore scanned as an ordinary segment. Two deliberate narrowings keep this
# from becoming a new false-positive source:
#   * POSIX shells only. `python3 -c "import pytest"` and
#     `gh pr create --title "pytest fix"` quote a runner they never execute.
#   * The shell must HEAD a segment (start of line or after an operator), so a
#     shell invocation quoted inside another command (`echo "sh -c 'pytest'"`)
#     stays data.
#
# ONE spelling of the invocation itself, shared with `_SHELL_C_HEAD_RE` below:
# the two ask different questions of the same launcher (what is its body / does
# this segment invoke one), and a second hand-written copy is how they drift.
_SHELL_C_INVOCATION = r"(?:\S*/)?(?:ba|z|k|da)?sh\s+(?:-\w+\s+)*-\w*c"
_SHELL_C_RE = re.compile(
    r"(?:^|&&|\|\||;|\||\n)\s*" + _SHELL_C_INVOCATION + r"\s+('[^']*'|\"[^\"]*\")"
)

# The same launcher, recognized from the HEAD of an already-split segment.
# `strip_quoted` has deleted the body by then, so the segment reads as a bare
# `sh -c ` that names no framework — see `_outer_exit_proves_runner_passed`,
# where a wrapper whose body runs a runner must still count as a
# runner-executing segment or every operator AFTER it stops counting.
_SHELL_C_HEAD_RE = re.compile(r"^" + _SHELL_C_INVOCATION + r"\b")

# Shell punctuation that can prefix an executable without being part of its
# name — `(grep ...)` must still read as a grep, or the refusal list below is
# trivially bypassed by a subshell.
_HEAD_PUNCTUATION = "({"


def _shell_c_bodies(command: str) -> list[str]:
    """The code bodies of any `sh -c '<body>'` launchers heading a segment."""
    return [m.group(1)[1:-1] for m in _SHELL_C_RE.finditer(command)]


def is_compound(command: str) -> bool:
    """True when a shell operator introduces a second executable segment.

    Quoted operators are data, not structure — `pytest -k "a && b"` is a single
    command — so the scan runs over `git_commits.strip_quoted` output. A
    `sh -c` body is the exception: it is code, and `sh -c "cd app && pytest"`
    can short-circuit at the `cd` exactly as the unwrapped form does.
    """
    if _SEGMENT_BREAK_RE.search(git_commits.strip_quoted(command)):
        return True
    return any(is_compound(body) for body in _shell_c_bodies(command))


def _segments(command: str) -> list[str]:
    """Split into executable segments, ignoring operators inside quotes.

    `[::2]` drops the captured operators the split interleaves; this function
    answers "what ran", and the ordering of `sh -c` bodies APPENDED after the
    outer segments is why it cannot also answer "did the runner's exit survive"
    (see `exit_status_proves_runner_passed`).
    """
    parts = _SEGMENT_BREAK_RE.split(git_commits.strip_quoted(command))[::2]
    segments = [p.strip() for p in parts if p.strip()]
    for body in _shell_c_bodies(command):
        segments.extend(_segments(body))
    return segments


def _head_token(segment: str) -> str:
    """The executable token of a segment: the first token left after peeling
    shell punctuation, VAR=val assignments, and wrapper commands with their
    options, reduced to its basename.

    A flag is only ever reachable here while still inside a wrapper's option zone
    (`sudo -u ci grep ...` — the executable cannot itself start with `-`), so
    whether it swallows the token after it is a question about THAT wrapper, and
    is answered by `_WRAPPER_VALUE_OPTS` rather than by a blanket rule. Both
    blanket rules mis-attribute (see that table): always-consume eats the `grep`
    in `time -p grep pytest x`, never-consume leaves `ci` heading
    `sudo -u ci grep pytest src/`.

    A flag seen with no wrapper open (`-x foo` — not a shape any real segment
    takes) consumes nothing, which is the same fail-safe direction: the worst it
    can do is attribute.
    """
    tokens = segment.split()
    wrapper = ""  # the wrapper whose option zone we are in, if any
    i = 0
    while i < len(tokens):
        token = tokens[i].lstrip(_HEAD_PUNCTUATION)
        i += 1
        if not token or _ASSIGNMENT_RE.match(token):
            continue
        if token.startswith("-"):
            # `--opt=value` carries its own value; only the separated form can
            # reach forward for the next token.
            if "=" not in token and token in _WRAPPER_VALUE_OPTS.get(
                wrapper, frozenset()
            ):
                i += 1
            continue
        basename = token.rsplit("/", 1)[-1]
        if basename in _WRAPPER_TOKENS:
            wrapper = basename
            continue
        return basename
    return ""


def _segment_framework(segment: str) -> str | None:
    """The framework this ONE segment plausibly EXECUTES, or None. A segment
    headed by an argument-consuming command merely names the runner."""
    framework = is_test_run(segment)
    if framework and _head_token(segment) not in _ARGUMENT_CONSUMING_HEADS:
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


def _closed_substitutions(segment: str) -> int:
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


def _outer_exit_proves_runner_passed(command: str) -> bool:
    """`exit_status_proves_runner_passed` for one command's own segments,
    without descending into `sh -c` bodies.

    A `sh -c "<body>"` whose BODY runs a runner is itself a runner-executing
    segment out here, and has to be recognized as one even though the body is
    gone: `strip_quoted` deletes it, leaving a bare `sh -c ` that names no
    framework. Without this the wrapper laundered the very thing this predicate
    exists to catch — `sh -c "pytest" | tee log` saw no runner in the outer
    scan, so the pipe that swallowed its exit had nothing to swallow, while
    `executed_framework` (which DOES read the body) reported a runner and the
    gate cleared on tee's 0. Which body belongs to which wrapper is not tracked:
    with more than one `sh -c` in a command, any of them running a runner arms
    the rule at the first — over-refusal, the safe direction.
    """
    parts = _SEGMENT_BREAK_RE.split(git_commits.strip_quoted(command))
    segments, operators = parts[::2], parts[1::2]
    shell_c_runs_a_runner = any(
        next(_executing_frameworks(body), None) is not None
        for body in _shell_c_bodies(command)
    )
    open_substitutions: list[str] = []
    runner_seen = False

    for i, segment in enumerate(segments):
        stripped = segment.strip()
        runs_a_runner = _segment_framework(stripped) is not None or (
            shell_c_runs_a_runner and _SHELL_C_HEAD_RE.match(stripped) is not None
        )
        if runs_a_runner:
            if open_substitutions:
                return False  # captured — the exit went into a string
            runner_seen = True
        if runner_seen and not open_substitutions and _ASYNC_RE.search(stripped):
            return False  # backgrounded — the shell never waited for it
        # Checked AFTER the runner, because a capture's `)` rides on the last
        # token of the very segment that runs it: `echo $(pytest)`.
        for _ in range(_closed_substitutions(segment)):
            if open_substitutions and open_substitutions[-1] == _SUBSTITUTION_OPEN:
                open_substitutions.pop()
        if i >= len(operators):
            break
        operator = operators[i]
        if operator == _SUBSTITUTION_OPEN:
            open_substitutions.append(operator)
        elif operator == _SUBSTITUTION_BACKTICK:
            # One backtick both opens and closes; which it is depends only on
            # whether one is already open.
            if open_substitutions and open_substitutions[-1] == _SUBSTITUTION_BACKTICK:
                open_substitutions.pop()
            else:
                open_substitutions.append(operator)
        elif (
            runner_seen
            and not open_substitutions
            and operator != _FAILURE_PROPAGATING_OPERATOR
            and any(later.strip() for later in segments[i + 1 :])
        ):
            return False  # discarded — `;`, `\n`, `||` or a pipe swallowed it
    return True


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
        exit_status_proves_runner_passed(body) for body in _shell_c_bodies(command)
    )


def parsed_failed_count(error: str, framework: str) -> int | None:
    """Failed-test count when the payload really parsed as a failing run, else
    None. Shared with `bash_failure`, which reports the count it corroborates.
    """
    results = parse_test_results(error, framework)
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

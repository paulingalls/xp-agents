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

Note the asymmetry with `is_test_run`, which is deliberately left alone: on the
SUCCESS path "the command contains a runner" is sound, because exit 0 means
every segment ran. It is only the FAILURE path that needs this module.

Pure — stdlib only, no SMM dependencies.
"""

import re

import git_commits
from test_parsing import PARSER_STATUS_PARSED, is_test_run, parse_test_results

# Shell operators that introduce a second executable segment. Command
# substitution (`$(`/backtick) is included: its exit status can surface as the
# whole command's, so the runner is not unambiguously to blame.
_SEGMENT_BREAK_RE = re.compile(r"&&|\|\||;|\||\n|\$\(|`")

# Tokens that wrap another executable without being the thing under test.
# Peeled so `time grep pytest x` is still seen as a grep, not as a test run.
_WRAPPER_TOKENS = frozenset(
    {"env", "sudo", "time", "nice", "nohup", "command", "exec", "stdbuf", "xargs"}
)

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
_SHELL_C_RE = re.compile(
    r"(?:^|&&|\|\||;|\||\n)\s*(?:\S*/)?(?:ba|z|k|da)?sh\s+(?:-\w+\s+)*-\w*c\s+"
    r"('[^']*'|\"[^\"]*\")"
)

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
    """Split into executable segments, ignoring operators inside quotes."""
    parts = _SEGMENT_BREAK_RE.split(git_commits.strip_quoted(command))
    segments = [p.strip() for p in parts if p.strip()]
    for body in _shell_c_bodies(command):
        segments.extend(_segments(body))
    return segments


def _head_token(segment: str) -> str:
    """The executable token of a segment: the first token left after peeling
    shell punctuation, VAR=val assignments, and wrapper commands with their
    options, reduced to its basename.

    A flag is only ever reachable here while still inside a wrapper's option
    zone (`sudo -u ci grep ...` — the executable cannot itself start with `-`),
    so a flag is consumed together with a possible value. Over-consuming an
    attached-value flag (`env -i pytest`) yields an empty head, which attributes
    — the safe direction. Under-consuming would let the grep in `sudo -u ci grep
    pytest src/` masquerade as the head's option and escape the refusal list.
    """
    tokens = segment.split()
    i = 0
    while i < len(tokens):
        token = tokens[i].lstrip(_HEAD_PUNCTUATION)
        i += 1
        if not token or _ASSIGNMENT_RE.match(token):
            continue
        if token.startswith("-"):
            i += 1  # a wrapper option: skip its value too
            continue
        basename = token.rsplit("/", 1)[-1]
        if basename in _WRAPPER_TOKENS:
            continue
        return basename
    return ""


def _executing_frameworks(command: str):
    """Yield the framework of each segment that plausibly EXECUTES a runner,
    in command order. A segment headed by an argument-consuming command merely
    names the runner, so it yields nothing."""
    for segment in _segments(command):
        framework = is_test_run(segment)
        if framework and _head_token(segment) not in _ARGUMENT_CONSUMING_HEADS:
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

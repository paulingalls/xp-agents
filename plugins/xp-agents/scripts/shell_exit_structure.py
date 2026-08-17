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
count as "the command under measurement". `exit_reaches_shell_for` is the whole
composition around it — the rewrite, the walk, the `sh -c` recursion — and
`exit_reaches_shell` is that composition with EVERY segment counting.

Pure — stdlib plus the leaf `git_commits.strip_quoted`, no SMM dependencies.
"""

import re
from collections.abc import Callable

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

# What an elided ARGUMENT substitution leaves behind — see
# `argument_substitutions_as_words`. Any operator-free, non-empty token would
# do; it exists only to keep the surrounding segment non-empty and spaced.
_SUBSTITUTION_WORD = "x"

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

# ---------------------------------------------------------------------------
# WHICH TOKEN OF A SEGMENT IS THE EXECUTABLE.
#
# Moved down here from `test_attribution` when `exit_reaches_shell` needed it to
# tell an ARGUMENT substitution from a COMMAND one. It is shell structure, not
# framework knowledge — no runner name appears in it — and `test_attribution`
# imports UP from this module, so one copy each would only drift.
#
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

# Commands that CONSUME another command's name — or its OUTPUT — as data
# instead of executing it. Two callers, one list:
#
#   * `test_attribution` — when one of these heads a segment, a runner token in
#     it is an argument (`grep -rn pytest src/`) and the exit code is not the
#     runner's.
#   * `_heads_a_command` below — when one of these heads the segment opening a
#     `$(...)`, the substitution is not merely producing an argument for real
#     work: `echo $(make build)` exits 0 over a failed build, and treating that
#     capture as harmless is precisely the fail-open this predicate refuses.
#
# This is a refusal list, NOT a whitelist of launchers, and the direction is
# deliberate: an unrecognized head still attributes (today's behavior, gate
# keeps its teeth), whereas an unrecognized LAUNCHER in a whitelist would
# silently stop attributing — a disarm, which is the far worse failure. The
# `test_every_framework_still_attributed` control pins that direction.
ARGUMENT_CONSUMING_HEADS = frozenset(
    {
        "grep", "egrep", "fgrep", "rg", "ripgrep", "ag", "ack", "git",
        "sed", "awk", "cat", "echo", "printf", "head", "tail", "less", "more",
        "find", "ls", "wc", "sort", "uniq", "cut", "tr", "diff", "jq",
    }
)  # fmt: skip

_ASSIGNMENT_RE = re.compile(r"^\w+=")

# Shell punctuation that can prefix an executable without being part of its
# name — `(grep ...)` must still read as a grep, or the refusal list above is
# trivially bypassed by a subshell.
_HEAD_PUNCTUATION = "({"


def head_token(segment: str) -> str:
    """The executable token of a segment: the first token left after peeling
    shell punctuation, VAR=val assignments, and wrapper commands with their
    options, reduced to its basename. "" when the segment names no executable.

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


def _closing_index(command: str, open_at: int, opener: str) -> int:
    """Index just PAST the substitution opened at *open_at*, or -1 if unclosed.

    Nesting is counted for `$(`, because `$(dirname $(which go))` closes twice
    with one token between; a backtick cannot nest, so its partner is the next
    one. An unclosed opener answers -1 and is left alone — the walk then sees a
    capture that never closes and refuses, which is the safe direction for the
    one input this module cannot parse.
    """
    if opener == SUBSTITUTION_BACKTICK:
        closer = command.find(SUBSTITUTION_BACKTICK, open_at + 1)
        return -1 if closer < 0 else closer + 1
    depth = 0
    for i in range(open_at + len(SUBSTITUTION_OPEN), len(command)):
        if command[i] == "(":
            depth += 1
        elif command[i] == ")":
            if depth == 0:
                return i + 1
            depth -= 1
    return -1


def _heads_a_command(prefix: str) -> bool:
    """Does the text before a substitution already name the thing being run?

    The whole argument-vs-command distinction, and the only place the head-token
    knowledge above is used from this file. `prefix` is everything since the last
    operator, so `head_token` sees one segment.

    A head that is EMPTY means the substitution is the command (`$(cat cmdfile)`)
    or its value is merely being captured (`OUT=$(tsc --noEmit)` — assignments
    peel away, leaving nothing). A head that CONSUMES its arguments as data
    (`echo $(make build)`) means the exit status reaching the shell is the
    consumer's, not the substitution's, which is the same discard by another
    route. Everything else is a command taking a computed WORD.
    """
    head = head_token(SEGMENT_BREAK_RE.split(prefix)[-1])
    return bool(head) and head not in ARGUMENT_CONSUMING_HEADS


def argument_substitutions_as_words(command: str) -> str:
    """*command* with every ARGUMENT substitution replaced by a plain word.

    `pytest -n $(nproc)` is ONE command whose exit status is pytest's; the
    substitution computes an argument, and the shell discards ITS status, not
    pytest's. Treating every `$(...)` as a capture refused that — along with
    `go test $(go list ./...)`, `make -j$(nproc) test` and `pytest
    --rootdir=$(pwd)` — so a project declaring any of them had close auto-merge
    silently switched off, under a reason string naming a `;`, pipe or `&` that
    was nowhere in its command.

    Rewriting rather than teaching the walk about depth is deliberate: the
    substitution's closing `)` rides mid-token on the segment after it, so a
    depth-aware walk would have to re-split that segment to keep the checks that
    must still apply to the text AFTER the close. `pytest -n $(nproc) &` is
    backgrounded and must stay refused; as `pytest -n x &` it simply is.

    A COMMAND substitution is left verbatim, so the walk still sees it and still
    refuses — see `_heads_a_command` for which is which.
    """
    out: list[str] = []
    i = 0
    while i < len(command):
        if command.startswith(SUBSTITUTION_OPEN, i):
            opener = SUBSTITUTION_OPEN
        elif command[i] == SUBSTITUTION_BACKTICK:
            opener = SUBSTITUTION_BACKTICK
        else:
            out.append(command[i])
            i += 1
            continue
        end = _closing_index(command, i, opener)
        if end < 0 or not _heads_a_command("".join(out)):
            # Kept verbatim, unclosed span and all: the walk's job to refuse.
            out.append(command[i:] if end < 0 else command[i:end])
            i = len(command) if end < 0 else end
            continue
        out.append(_SUBSTITUTION_WORD)
        i = end
    return "".join(out)


# A plain shell comment, so it is inert to the command it rides on. Three
# properties earn it: it cannot change what runs, it forces the intent to be
# stated rather than guessed at, and it is greppable in history, so routine
# bypassing is visible rather than silent.
#
# Kept HERE rather than with any one gate: every gate built on the composition
# below refuses the same shape and must be waived by the same words, and an
# agent that has to remember which marker suppresses which gate will type the
# wrong one. It suppresses the PRE-RUN refusals only — `test_attribution`'s
# post-run advisory is untouched, so an agent that knowingly discards a status
# is still told what that cost it, which is information rather than a refusal
# to route around.
EXIT_STATUS_NOT_NEEDED_MARKER = "# exit-status-not-needed"


def exit_status_waived(command: str) -> bool:
    """True when *command* DECLARES the marker, rather than quoting it in a
    message body or argument the way a commit ABOUT one of these gates does —
    see `test_the_marker_cannot_be_forged_by_a_message_body`."""
    return EXIT_STATUS_NOT_NEEDED_MARKER in git_commits.strip_quoted(command)


def exit_reaches_shell_for(command: str, runs_target: Callable[[str], bool]) -> bool:
    """True when the exit status of the segments *runs_target* names survives.

    The composition, in one place, for every caller that needs the whole thing.
    Three parts, none of them new parsing:

      * `argument_substitutions_as_words` FIRST, or every substitution reads as
        a capture. One that merely computes an ARGUMENT does not capture the
        command's status — the command's own status is still what the shell
        reports — and refusing those would refuse ordinary commands whose
        arguments are computed. That direction is not a theoretical worry: it
        silently disabled a consumer for a whole class of projects once already.
      * the walk itself, which is pure shell grammar.
      * the bodies of any `sh -c` wrapper, recursively. The outer walk
        deliberately does not descend into them — it only notices that a body
        runs the target, so the wrapper counts as one measured segment out
        here. Without this leg a wrapper launders any operator INSIDE it.

    *runs_target* chooses the strictness: `_every_segment` asks the strictest
    honest version of the question, a narrower predicate asks only about the
    segments it names. Not every consumer of the walk wants this composition —
    `test_attribution` records why its own may omit the first part.
    """
    if not outer_exit_reaches_shell(
        argument_substitutions_as_words(command), runs_target
    ):
        return False
    # The bodies come from the ORIGINAL command; the recursion re-elides each.
    return all(
        exit_reaches_shell_for(body, runs_target) for body in shell_c_bodies(command)
    )


def exit_reaches_shell(command: str) -> bool:
    """True when *command*'s own exit status becomes the shell's exit status.

    The runner-agnostic entry point: every non-empty segment counts as measured,
    so this asks the strictest honest version of the question — is there any
    operator anywhere in this command that discards or captures an exit status
    the caller might have wanted to read?

    Conservative by construction, because a wrong True is what lets a caller
    compare two runs on a number that means nothing — bounded on the other side
    by the ARGUMENT-substitution line `argument_substitutions_as_words` draws and
    argues, which this inherits from the composition above rather than restates.

    A command that runs nothing is vacuously True — there is no exit status here
    to have been swallowed. Callers that need "this is a runnable command" must
    ask that separately.
    """
    return exit_reaches_shell_for(command, _every_segment)

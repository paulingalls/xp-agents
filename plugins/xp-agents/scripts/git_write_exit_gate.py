#!/usr/bin/env python3
"""Refuse a `git push` or `git commit` whose exit status cannot reach the shell.

On 2026-08-14 a push was piped through `tail -6`. The shell reported `tail`'s
exit 0, the push had been REJECTED, and the failure was read as success — the
log said `3 failed, 9873 passed` two lines above what got quoted. About forty
minutes went into a bug that did not exist.

WHY THESE TWO SUBCOMMANDS. `pre-push` runs the whole suite and `pre-commit` runs
lint, format, types and the staged tests. Those hooks exist to FAIL, and a pipe
replaces their verdict with the pager's — so the one signal they produce is
thrown away. The output being long is exactly why the pipe gets typed, which is
why the refusal names a redirect rather than telling anyone to re-run bare.

WHY FIXED NAMES ARE NOT A LEAK HERE. Its sibling `exit_capture_gate` refuses to
name runners, because the plugin ships to projects in every language and any
fixed list of runner names is inert for most of them. Git is different in kind:
every project using this plugin is a git repo — the shared model, the branching,
the worktrees and the close cycle all assume one — and `push` and `commit` are
universal rather than a vocabulary that goes stale per language. This is the
rare case where fixed names are the correct design, not the shortcut.

A SIBLING, NOT AN EDIT TO THAT GATE. Its docstring states, as its contract, that
it contains no runner name "not in a rule, not in an example"; adding a literal
`push` there would falsify the sentence in the file asserting it. The two share
what is genuinely shared instead — `shell_exit_structure` holds the grammar, the
composition and the escape marker, and neither gate owns a private copy.

WHAT IT WILL NOT CATCH, deliberately. Reads. A piped `git log`, `git status` or
`git diff` loses a status nobody needed, and spreading to the whole git
vocabulary would refuse ordinary work to protect nothing.

WHAT IT MISSES AND WHAT IT OVER-REFUSES, measured at the close review rather
than assumed. `eval "git push | tail"` launders the pipe: only a `sh -c` body is
recursed into, so this joins the deliberate-evasion class the spike catalogues
beside aliases and `$GIT` — and the marker below is the honest way to say "I
meant it". In the other direction, a write inside a compound statement
(`if ...; then git commit; fi`, `for ...; do git push; done`) is refused for the
`;` before `fi` or `done`, which is shell SYNTAX and discards nothing; telling
that apart needs keyword knowledge the shared walk has not got, and over-
refusing a shape agents rarely type is the safe direction.

WHOSE COMMANDS IT BINDS, stated because "needs no shared-model directory" is a
narrower claim than the placement makes. Needing none is what lets the caller put
this above its recursion skip AND above the shared-model lookup — and above that
lookup means it refuses in projects that have no shared model at all, so the
group it binds is EVERY Bash command in an installed project, not just this
plugin's own agents. Its sibling `pre_tool_bash_reviewer_guard` sits in the same
position on the same reasoning but only ever matches two agent names, so the
precedent does not carry the footprint. Deliberate: the status a pipe throws away
is thrown away whether or not a project tracks work here, and the marker is the
release valve. Not free, and not the reviewer guard's blast radius.

Reason-returning, like `pre_tool_bash_reviewer_guard`: this module never raises,
never reads or writes a stream, and never decides an exit code. The caller wraps
the returned reason. It needs no shared-model directory, which is what lets the
caller place it above the recursion skip.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import git_commits
import shell_exit_structure

# `GIT_PREFIX` rather than a bare `git\s+`, because `git -C <path> push` is the
# form agents adopt to avoid cd-poisoning the Stop hooks, and it is what the
# shipped close skills instruct.
#
# The trailing lookahead is WIDER than the `\b(?!-)` its sibling
# `git_commits._COMMIT_OR_MERGE_RE` uses, and the extra characters are each
# paying for a false positive that gate can afford and this one cannot. `-`
# keeps `git commit-tree` out, as there. `.` and `=` keep a CONFIG VALUE out:
# `git -c commit.gpgsign=false log` and `git -c push.default=simple log` are
# reads, and `\b` sits happily between `commit` and `.`, so the narrower
# lookahead read both as writes. That form is the CI identity this project
# documents, so the false positive would have refused ordinary reads on the
# path agents use most. `\w` completes the token boundary the other two imply.
_GIT_WRITE_RE = re.compile(
    git_commits.GIT_PREFIX + r"(?P<subcommand>push|commit)(?![\w.=-])"
)

# A `\`-newline is a line CONTINUATION, not a segment break: the shell joins it
# away before git ever sees it. The walk splits on `\n` regardless, so left
# alone every wrapped invocation reads as two commands with a status-discarding
# newline between them — and an honest `git push \<nl> origin HEAD` is refused
# for an operator that is not there. `git_commits.TOKEN_GAP` exists for the same
# shape and says why: wrapping is ordinary formatting, not evasion. `[ \t]*`
# rather than `\s*`, so a continuation followed by a BLANK line does not eat the
# real break after it.
_LINE_CONTINUATION_RE = re.compile(r"\\\n[ \t]*")

# The operators the shell binds LOOSER than a pipe, and a single `|`, which it
# binds tighter. Both are read only by `_reads_piped_as_words`, whose whole
# subject is that difference in precedence.
_LOOSE_BREAK_RE = re.compile(r"(&&|\|\||;|\n)")
_PIPE_RE = re.compile(r"(?<!\|)\|(?!\|)")
# What an elided read's pipeline leaves behind — any operator-free token would
# do, as in `shell_exit_structure.argument_substitutions_as_words`.
_READ_WORD = " x "


def git_write_named(command: str) -> str | None:
    """The write subcommand *command* names, or None when it names none.

    TEXT-shaped, not segment-shaped: it splits nothing and matches anywhere,
    which is the contract `outer_exit_reaches_shell` documents for its
    predicate — that walk hands it whole `sh -c` bodies, which may themselves be
    compound.

    Two texts, because the two disagree on one shape each. `git "x" push` reads
    as a write only AFTER `strip_quoted` removes the quoted token, while
    `sh -c 'git push'` reads as one only BEFORE it, since the same call deletes
    the body. The walk sees both forms, so a pre-filter blind to either would
    decline to protect a command the walk would have refused.
    """
    for text in (command, git_commits.strip_quoted(command)):
        match = _GIT_WRITE_RE.search(text)
        if match is not None:
            return match.group("subcommand")
    return None


def _reads_piped_as_words(command: str) -> str:
    """*command* with every pipeline that runs no git write reduced to one word.

    `|` binds TIGHTER than `&&`, so `git push && git log | cat` is
    `git push && (git log | cat)`: a failed push short-circuits the list and its
    non-zero IS the shell's, which is the whole reason `&&` is permitted. The
    shared walk cannot see that — it reads operators in sequence with no
    precedence and refuses the first discard anywhere after the write — so the
    composition this refusal PRESCRIBES was itself refused, and the next attempt
    reads the advice, retypes it and is refused again.

    A rewrite rather than a second walk, for the reason
    `argument_substitutions_as_words` is one: the same command, restated without
    a pipe that was never the write's. Four things are left alone, each because
    eliding it would answer a different question than the one asked:

      * a pipeline that RUNS a write — `git push | tail` is the shape this gate
        exists for.
      * a background `&`, which applies to the whole list, write included.
      * a substitution, whose opener the walk must still see and balance.
      * an odd quote count, which means a quoted span crosses this operator, so
        the split did not land where the shell would put it.
    """
    parts = _LOOSE_BREAK_RE.split(command)
    for i in range(0, len(parts), 2):
        part = parts[i]
        if not _PIPE_RE.search(part) or git_write_named(part) is not None:
            continue
        if shell_exit_structure.ASYNC_RE.search(part) or "$(" in part or "`" in part:
            continue
        if part.count('"') % 2 or part.count("'") % 2:
            continue
        parts[i] = _READ_WORD
    return "".join(parts)


def _refusal(subcommand: str) -> str:
    """What to say instead of just "no".

    The failure this prevents is an agent trusting a wrapper's exit status; a
    refusal that does not name the command to type next spends the same time a
    different way. What it must carry, and why each part earns its place, is
    pinned one assertion at a time in `TestTheRefusalSaysWhatToTypeNext` — read
    there rather than here, since a second copy of those four reasons is prose
    that rots against the tests stating them.
    """
    return (
        f"Refusing this `git {subcommand}`: its exit status cannot reach the "
        "shell. A pipe, a redirect followed by `echo $?`, a `$(...)` capture or "
        "a background `&` makes the shell's exit status the wrapper's, not "
        "git's — so a rejected push or a hook-blocked commit reports success, "
        "and the failure surfaces later attributed to something else.\n"
        f"Run it so its own status is the command's: `git {subcommand} ...`. A "
        "leading `cd <dir> &&`, a trailing `&& <next>` and `git -C <path>` all "
        "still count, because `&&` carries a failure through. If the output is "
        f"too long to read as it comes, redirect it — `git {subcommand} ... > "
        "<file> 2>&1` keeps the file and leaves the exit status git's; read "
        "<file> afterwards, and do not add an `echo $?` line, which is the "
        "shape above.\n"
        "If you genuinely do not need this command's status, state that by "
        f"adding the literal marker "
        f"`{shell_exit_structure.EXIT_STATUS_NOT_NEEDED_MARKER}` to the command."
    )


def captured_git_write_block(command: str) -> str | None:
    """Reason to refuse *command*, or None to let it proceed.

    Three conditions, all of which must hold: the command names a write, the
    escape marker is not DECLARED (a message body that merely quotes it is data,
    not a waiver — see `shell_exit_structure.exit_status_waived`), and the
    write's exit status does not survive to the shell.

    The name is read BEFORE the walk rather than after it, and does double duty:
    it is the cheap pre-filter that keeps this off every Bash call that is not a
    git write, and it is what the refusal quotes back. Deriving it afterwards
    would need a second search that could, in principle, find nothing — an
    unreachable branch nothing could test.
    """
    if not command or shell_exit_structure.exit_status_waived(command):
        return None
    joined = _LINE_CONTINUATION_RE.sub(" ", command)
    subcommand = git_write_named(joined)
    if subcommand is None:
        return None
    if shell_exit_structure.exit_reaches_shell_for(
        _reads_piped_as_words(joined), _runs_a_git_write
    ):
        return None
    return _refusal(subcommand)


def _runs_a_git_write(text: str) -> bool:
    return git_write_named(text) is not None

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
# shipped close skills instruct. `(?!-)` keeps `git commit-tree` out — the same
# guard `git_commits._COMMIT_OR_MERGE_RE` uses ten lines from where this
# borrows its prefix.
_GIT_WRITE_RE = re.compile(
    git_commits.GIT_PREFIX + r"(?P<subcommand>push|commit)\b(?!-)"
)


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


def _refusal(subcommand: str) -> str:
    """What to say instead of just "no".

    The failure this prevents is an agent trusting a wrapper's exit status; a
    refusal that does not name the command to type next spends the same time a
    different way. Four things it has to carry: which subcommand was refused,
    that `&&` on either side is still fine (without it the reading is "never
    compose a push", and the next attempt drops the `cd <dir> &&` or the
    `git -C <path>` a worktree run needs), the redirect — which is what the
    agent reaching for `| tail` actually wanted — and the escape marker.
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
    escape marker is absent, and the write's exit status does not survive to the
    shell.

    The name is read BEFORE the walk rather than after it, and does double duty:
    it is the cheap pre-filter that keeps this off every Bash call that is not a
    git write, and it is what the refusal quotes back. Deriving it afterwards
    would need a second search that could, in principle, find nothing — an
    unreachable branch nothing could test.
    """
    if not command or shell_exit_structure.EXIT_STATUS_NOT_NEEDED_MARKER in command:
        return None
    subcommand = git_write_named(command)
    if subcommand is None:
        return None
    if shell_exit_structure.exit_reaches_shell_for(command, _runs_a_git_write):
        return None
    return _refusal(subcommand)


def _runs_a_git_write(text: str) -> bool:
    return git_write_named(text) is not None

#!/usr/bin/env python3
"""Unmerged story-branch delete refusal — split from pre_tool_bash.py to keep
files under the 500-line cap.

story_done_gate.merged_block trusts branch ABSENCE as proof of merge; a raw
`git branch -D <story-branch>` deletes an unmerged one, flipping that proof.
Catch the LITERAL case, NO-OP on anything ambiguous (e.g. a shell var).
"""

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branch_resolution
import branching
import commits
import git_commits
import identity

# `-d`/`-D`/`--delete`, incl. clusters like `-Df` (no other short flag uses d/D).
_DELETE_FLAG_RE = re.compile(r"^(?:--delete|-[A-Za-z]*[dD][A-Za-z]*)$")
# Tokens that END one simple command. `punctuation_chars=True` hands these back as
# tokens of their own, so a chain splits without a regex that cannot see quoting.
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "\n", "(", ")"})


def _simple_commands(command: str) -> list[list[str]]:
    """`command` tokenized as the SHELL would, split into simple commands.

    A tokenizer rather than a regex, and the distinction is the whole fix: a regex
    searching raw text finds `git branch -D <branch>` inside `git commit -m "...
    git branch -D <branch>"` and refuses a commit over what its MESSAGE says --
    the same scar `story_done_gate._MARK_DONE_RE` carries, arriving by a different
    door. To the shell that message is ONE token, so a tokenizer cannot make the
    mistake. Stripping quotes instead (`git_commits.strip_quoted`) would trade the
    bug for its inverse: `git branch -D "<branch>"` would lose its argument and the
    delete would sail through, which is the fail-open this gate exists to close.

    This module's docstring warns that a shlex-based detector was unsound, and it
    was -- it tried to decide which FILES an arbitrary command writes, which is not
    decidable. This decides nothing about effects: it reads back literal tokens and
    the caller no-ops on everything else (`$BR` stays the text `$BR`, matches no
    story id, and yields no delete). Unparseable text (an unbalanced quote) yields
    no commands at all -- the same documented no-op, never a block.

    Heredoc bodies are dropped first: the shell passes them as DATA, so a commit
    message written as a heredoc is prose by the argument above.
    """
    lexer = shlex.shlex(
        git_commits.strip_heredocs(command), posix=True, punctuation_chars=True
    )
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return []

    commands: list[list[str]] = [[]]
    for token in tokens:
        if token in _SHELL_SEPARATORS:
            commands.append([])
        else:
            commands[-1].append(token)
    return [c for c in commands if c]


def _story_branch_deletes(command: str) -> list[tuple[str | None, str]]:
    """`(git -C directory or None, branch)` per literal story-branch delete.

    The `-C` directory is carried OUT rather than discarded: it names the repo the
    delete lands in, and a merge proof evaluated anywhere else is not a proof of
    anything. Recognizing the form and then judging it in the hook's own cwd is
    worse than not recognizing it at all -- the branch is absent there, and absence
    is precisely what this gate treats as proof of a merge.
    """
    deletes: list[tuple[str | None, str]] = []
    for tokens in _simple_commands(command):
        if tokens[0] != "git":
            continue

        # Walk git's GLOBAL options to find the subcommand: `-C <dir>` is the one
        # we must keep, and the rest only have to be stepped over correctly.
        directory: str | None = None
        i = 1
        while i < len(tokens) and tokens[i].startswith("-"):
            if tokens[i] == "-C" and i + 1 < len(tokens):
                directory = tokens[i + 1]
                i += 2
            elif tokens[i] == "-c" and i + 1 < len(tokens):
                i += 2
            else:
                i += 1
        if i >= len(tokens) or tokens[i] != "branch":
            continue

        args = tokens[i + 1 :]
        if not any(_DELETE_FLAG_RE.match(arg) for arg in args):
            continue
        for arg in args:
            if not arg.startswith("-") and identity.extract_story_id(arg):
                deletes.append((directory, arg))
    return deletes


def _unmerged_story_branch_delete_block(
    smm_dir: Path, cwd: str, command: str
) -> str | None:
    """Reason to refuse a recognized story-branch delete, or None to allow.
    Fails CLOSED once a delete is recognized and the base is unresolvable."""
    deletes = _story_branch_deletes(command)
    if not deletes:
        return None

    def _repo_of(directory: str | None) -> str:
        """The repo THIS delete lands in. Its own `git -C` wins; otherwise the
        command's effective cwd, which is what the commit gates already read
        (`cd <wt> && git branch -D ...` retargets just as `-C` does)."""
        if directory is None:
            return commits.parse_effective_cwd(command, cwd)
        path = Path(directory)
        if not path.is_absolute():
            path = Path(cwd) / path
        return str(path)

    base = branch_resolution.resolve_story_base(smm_dir, cwd)
    if base is None:
        named = ", ".join(sorted({branch for _, branch in deletes}))
        return (
            f"Refusing to delete {named}: the story base "
            "branch cannot be honestly resolved, so whether it is merged "
            "is unknowable. Use `delete_branch` (branching.py) or "
            "/xp-story-close, which prove the merge before deleting."
        )
    for directory, branch in deletes:
        repo = _repo_of(directory)
        if not branch_resolution.branch_exists(repo, branch):
            continue
        if branching.is_merged_into(repo, branch, base):
            continue
        return (
            f"Refusing to delete {branch}: it is not merged into {base}. "
            "Deleting it by hand would let the mark-done gate read its "
            "absence as proof of a merge that never landed. Use "
            "`delete_branch` (branching.py) or /xp-story-close instead."
        )
    return None

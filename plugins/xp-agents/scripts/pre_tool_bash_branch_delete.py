#!/usr/bin/env python3
"""Unmerged story-branch delete refusal — split from pre_tool_bash.py to keep
files under the 500-line cap.

story_done_gate.merged_block trusts branch ABSENCE as proof of merge; a raw
`git branch -D <story-branch>` deletes an unmerged one, flipping that proof.
Catch the LITERAL case, NO-OP on anything ambiguous (e.g. a shell var).

`git branch -m/-M <story-branch> <new-name>` (and the current-branch form
`-m/-M <new-name>` when HEAD is on the story branch) makes the branch vanish
just as surely as a delete, so it is judged by the same merge check below.
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
# `-m`/`-M`/`--move`. Unlike `-d`/`-D`, not clustered: `-m`/`-M` take a
# required argument, so git users never combine them with other short flags.
_RENAME_FLAG_RE = re.compile(r"^(?:--move|-[mM])$")
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


def _branch_invocation(tokens: list[str]) -> tuple[str | None, list[str]] | None:
    """`(git -C directory or None, args after the `branch` subcommand)` if
    `tokens` invoke `git branch`, else None.

    Shared by the delete and rename detectors below so the walk over git's
    GLOBAL options (`-C <dir>` is the one worth keeping) is written once.
    """
    if tokens[0] != "git":
        return None

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
        return None
    return directory, tokens[i + 1 :]


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
        invocation = _branch_invocation(tokens)
        if invocation is None:
            continue
        directory, args = invocation

        if not any(_DELETE_FLAG_RE.match(arg) for arg in args):
            continue
        for arg in args:
            if not arg.startswith("-") and identity.extract_story_id(arg):
                deletes.append((directory, arg))
    return deletes


def _story_branch_rename_tokens(command: str) -> list[tuple[str | None, str | None]]:
    """`(git -C directory or None, old_branch)` per `git branch -m/-M`
    invocation. `old_branch` is the literal source name for the two-arg form
    (`-m OLD NEW`), or None for the current-branch form (`-m NEW`) -- this
    function only tokenizes, it does not resolve HEAD; the caller does that
    once it knows which repo to resolve it in.

    Unlike `_story_branch_deletes`, this does NOT filter by story id itself:
    the current-branch form's name isn't known until resolved, so the filter
    has to happen after the caller resolves it.
    """
    renames: list[tuple[str | None, str | None]] = []
    for tokens in _simple_commands(command):
        invocation = _branch_invocation(tokens)
        if invocation is None:
            continue
        directory, args = invocation

        if not any(_RENAME_FLAG_RE.match(arg) for arg in args):
            continue
        positionals = [arg for arg in args if not arg.startswith("-")]
        if len(positionals) >= 2:
            renames.append((directory, positionals[0]))
        elif len(positionals) == 1:
            renames.append((directory, None))
        # Zero positionals (a bare `-m` with nothing to rename) is a git
        # usage error, not a rename -- nothing to recognize.
    return renames


def _unmerged_story_branch_delete_block(
    smm_dir: Path, cwd: str, command: str
) -> str | None:
    """Reason to refuse a recognized story-branch delete, or None to allow.
    Fails CLOSED once a delete is recognized and the base is unresolvable."""
    deletes = _story_branch_deletes(command)
    rename_tokens = _story_branch_rename_tokens(command)
    if not deletes and not rename_tokens:
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

    # A rename AWAY from a story-branch name makes that branch vanish just as
    # surely as a delete -- resolve each one down to the (directory, branch)
    # shape the delete path already understands, so both share one merge
    # check below. The current-branch form (`old is None`) is only resolved
    # HERE, against the repo it actually targets.
    for directory, old in rename_tokens:
        if old is None:
            old = identity.get_current_branch(_repo_of(directory))
        if old and identity.extract_story_id(old):
            deletes.append((directory, old))
    if not deletes:
        return None

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

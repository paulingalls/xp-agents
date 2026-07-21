#!/usr/bin/env python3
"""Unmerged story-branch delete refusal — split from pre_tool_bash.py to keep
files under the 500-line cap.

story_done_gate.merged_block trusts branch ABSENCE as proof of merge; a raw
`git branch -D <story-branch>` deletes an unmerged one, flipping that proof.
Catch the LITERAL case, NO-OP on anything ambiguous (e.g. a shell var).

`git branch -m/-M <old-story-branch> <new-name>` makes the branch vanish just
as surely as a delete, so the two-arg LITERAL form is judged by the same merge
check below. The current-branch shorthand (`-m/-M <new-name>`, one positional)
is a KNOWN, ACCEPTED gap: it names no source branch, so recognizing it would
require resolving live HEAD at PreToolUse -- BEFORE the command runs -- and a
chained `git checkout <story> && git branch -m <new>` would then resolve the
base branch, not the story, and fail open silently. Rather than ship a leg
reliable only when un-chained (false assurance), this gate no-ops on that form,
consistent with its doctrine: catch the LITERAL case, NO-OP on anything
ambiguous.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branch_resolution
import branching
import commits
import identity
import shell_commands

# `-d`/`-D`/`--delete`, incl. clusters like `-Df` (no other short flag uses d/D).
_DELETE_FLAG_RE = re.compile(r"^(?:--delete|-[A-Za-z]*[dD][A-Za-z]*)$")
# `-m`/`-M`/`--move`. Unlike `-d`/`-D`, not clustered: `-m`/`-M` take a
# required argument, so git users never combine them with other short flags.
_RENAME_FLAG_RE = re.compile(r"^(?:--move|-[mM])$")


def _story_branch_vanishings(command: str) -> list[tuple[str | None, str]]:
    """`(git -C directory or None, branch)` per literal command that makes a
    story branch VANISH from its name -- a `-d/-D/--delete` of it, or a two-arg
    `-m/-M/--move OLD NEW` renaming it away. Both are recognized in a SINGLE
    shell-tokenization pass over `command`.

    The `-C` directory is carried OUT rather than discarded: it names the repo the
    delete/rename lands in, and a merge proof evaluated anywhere else is not a proof
    of anything. Recognizing the form and then judging it in the hook's own cwd is
    worse than not recognizing it at all -- the branch is absent there, and absence
    is precisely what this gate treats as proof of a merge.

    Only the LITERAL two-arg rename is recognized: its source name is present in the
    command text, mirroring the delete path's literal-name design. The current-branch
    shorthand (`-m NEW`, one positional) is a documented, accepted gap (see module
    docstring); three-or-more positionals is a git usage error, left for git to
    report rather than misdirected as a delete refusal.
    """
    vanishings: list[tuple[str | None, str]] = []
    for tokens in shell_commands.simple_commands(command):
        invocation = shell_commands.git_invocation(tokens)
        if invocation is None:
            continue
        directory, subcommand, args = invocation
        if subcommand != "branch":
            continue

        if any(_DELETE_FLAG_RE.match(arg) for arg in args):
            for arg in args:
                if not arg.startswith("-") and identity.extract_story_id(arg):
                    vanishings.append((directory, arg))
        elif any(_RENAME_FLAG_RE.match(arg) for arg in args):
            positionals = [arg for arg in args if not arg.startswith("-")]
            if len(positionals) == 2 and identity.extract_story_id(positionals[0]):
                vanishings.append((directory, positionals[0]))
    return vanishings


def _unmerged_story_branch_delete_block(
    smm_dir: Path, cwd: str, command: str
) -> str | None:
    """Reason to refuse a recognized story-branch delete or rename-away, or None
    to allow. Fails CLOSED once one is recognized and the base is unresolvable."""
    deletes = _story_branch_vanishings(command)
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

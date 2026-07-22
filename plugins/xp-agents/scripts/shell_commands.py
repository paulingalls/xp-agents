#!/usr/bin/env python3
"""Shell-command tokenization shared by the PreToolUse:Bash gates.

Two gates now read the same question out of a Bash command -- "which git
invocations does this text actually contain?" -- so the tokenization lives in
one module rather than being re-derived per gate. `simple_commands` splits a
compound chain the way the shell would; `git_invocation` reads one simple
command back as a git call.

Both are deliberately EXTRACTORS, not predicates: they report what is literally
there and decide nothing about effects. Callers no-op on everything else, which
is what keeps the ambiguous cases (`$SUB`, unbalanced quotes) safe by default.
"""

import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import git_commits

# Characters that END one simple command. Membership is tested per CHARACTER,
# not per token, because `punctuation_chars` hands back a RUN of them as a single
# token: `|&` and `;;` are one token each and matched no entry in the exact-token
# set this replaced, so they split nothing.
_SEPARATOR_CHARS = frozenset(";|&\n()")

# `\n` is punctuation here rather than whitespace, and that is the whole reason
# newlines split at all. shlex's default whitespace includes "\n", so it was
# consumed before any separator test could see it and a multi-line block
# collapsed into ONE simple command -- the leading read laundering everything
# behind it. A multi-line block is the ORDINARY shape an agent emits, so that
# left the callers' gates inert by default rather than only under crafting.
# `<>` stay punctuation for tokenizing but are NOT separators: a redirection
# does not end a command.
_PUNCTUATION_CHARS = "();<>|&\n"
_WHITESPACE = " \t\r"


def _is_separator(token: str) -> bool:
    """True when `token` is nothing but separator characters.

    Per-character rather than exact-match so a coalesced run (`|&`, `;;`, a
    blank line's `\\n\\n`) ends a command like the single form it is built from.

    A QUOTED token of only these characters (`git commit -m ";;"`) reads as a
    separator here, because posix mode strips the quotes and nothing downstream
    can tell the two apart. That splits one command into two harmless fragments
    -- it can only ever cause an extra check, never skip one -- so it errs in
    the safe direction, which is the only direction a gate may err in.
    """
    return bool(token) and all(ch in _SEPARATOR_CHARS for ch in token)


def simple_commands(command: str) -> list[list[str]]:
    """`command` tokenized as the SHELL would, split into simple commands.

    A tokenizer rather than a regex, and the distinction is the whole fix: a regex
    searching raw text finds `git branch -D <branch>` inside `git commit -m "...
    git branch -D <branch>"` and refuses a commit over what its MESSAGE says --
    the same scar `story_done_gate._MARK_DONE_RE` carries, arriving by a different
    door. To the shell that message is ONE token, so a tokenizer cannot make the
    mistake. Stripping quotes instead (`git_commits.strip_quoted`) would trade the
    bug for its inverse: `git branch -D "<branch>"` would lose its argument and the
    delete would sail through, which is the fail-open this gate exists to close.

    Returning EVERY simple command, not just the first, is what defeats chaining:
    a caller that checks all of them cannot be slipped past by `git status && git
    reset --hard`.

    This decides nothing about effects: it reads back literal tokens and callers
    no-op on everything else (`$BR` stays the text `$BR` and matches nothing).
    Unparseable text (an unbalanced quote) yields no commands at all -- a
    documented no-op, never a block.

    Heredoc bodies are dropped first: the shell passes them as DATA, so a commit
    message written as a heredoc is prose by the argument above.
    """
    lexer = shlex.shlex(
        git_commits.strip_heredocs(command),
        posix=True,
        punctuation_chars=_PUNCTUATION_CHARS,
    )
    lexer.whitespace_split = True
    lexer.whitespace = _WHITESPACE
    try:
        tokens = list(lexer)
    except ValueError:
        return []

    commands: list[list[str]] = [[]]
    for token in tokens:
        if _is_separator(token):
            commands.append([])
        else:
            commands[-1].append(token)
    return [c for c in commands if c]


def git_invocation(tokens: list[str]) -> tuple[str | None, str, list[str]] | None:
    """`(git -C directory or None, subcommand, args after it)` when `tokens`
    invoke git, else None.

    The walk over git's GLOBAL options is written once here so every caller
    agrees on where the subcommand starts; `-C <dir>` is the one option worth
    carrying out, because it names the repo the command actually lands in and a
    judgment made about any other repo is not a judgment about this command.

    Returns the subcommand rather than testing for an expected one: an allowlist
    must READ what was invoked to compare it against many permitted names, and a
    predicate (`is this git <sub>?`) would force that caller to loop the helper
    once per allowed name. Callers wanting one subcommand compare it themselves.

    A git call with no subcommand at all (`git`, `git --version`) yields None --
    there is nothing to name, and options-only calls modify nothing.
    """
    if not tokens or tokens[0] != "git":
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
    if i >= len(tokens):
        return None
    return directory, tokens[i], tokens[i + 1 :]

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

# Tokens that END one simple command. `punctuation_chars=True` hands these back as
# tokens of their own, so a chain splits without a regex that cannot see quoting.
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "\n", "(", ")"})


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

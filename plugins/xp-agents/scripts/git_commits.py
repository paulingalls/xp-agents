#!/usr/bin/env python3
"""Git command parsing — detects commit-producing git invocations
(commit, merge) for the pre-Bash review-cycle gate and post-Bash commit-
event recording. Tolerates global options like `git -C <path> commit`
and `git -c k=v commit` so agent-style invocations don't bypass detection.
"""

import re

# `git` followed by zero-or-more global options before the subcommand.
# Each option is `-X` (standalone) or `-X <value>` (paired). Covers `-C <path>`
# (the form agents adopt to avoid cd-poisoning Stop hooks), `-c <kv>`,
# `--git-dir=<path>`, `--work-tree=<path>`, `--paginate`, etc. Without this
# tolerance, those forms silently bypass subcommand detection: pre-tool gate
# skips review cycle, post-tool hook skips commit-event recording + marker
# reset, and `commits.get_code_files_for_review` misses unstaged tracked
# files for `git -C add` / `git -C commit -a`.
GIT_PREFIX = r"\bgit(?:\s+-\S+(?:\s+\S+)?)*\s+"


def strip_heredocs(command: str) -> str:
    """Remove heredoc bodies (`<<'DELIM'...DELIM` / `<<DELIM...DELIM`).

    Split out of `strip_quoted` so a caller that must keep quoted arguments can
    still drop heredoc BODIES. A heredoc body is prose the shell passes as data —
    a commit message, most often — and any scanner that reads it is reading what
    a command SAYS rather than what it does. `pre_tool_bash`'s branch-delete
    refusal needs exactly this half: it tokenizes the command with the quotes
    intact (a quoted branch name is a real argument), so it cannot use
    `strip_quoted`, but it must not see a message body either.
    """
    return re.sub(r"<<-?\s*'?(\w+)'?.*?\n.*?\1", "", command, flags=re.DOTALL)


def strip_quoted(command: str) -> str:
    """Remove quoted strings and heredocs to avoid matching inside arguments.

    Public so callers (commits.parse_effective_cwd, bash_post_tool) can
    share one pre-stripped scan target with `is_git_commit` instead of
    each re-stripping the command independently.
    """
    s = strip_heredocs(command)
    # Remove escaped quotes, then quoted strings
    s = s.replace("\\'", "").replace('\\"', "")
    s = re.sub(r"'[^']*'", "", s)
    s = re.sub(r'"[^"]*"', "", s)
    return s


def is_git_commit(command: str, *, scan_target: str | None = None) -> bool:
    """Detect a commit-producing git command (commit or merge), not inside
    quoted arguments. The `(?!-)` lookahead rejects plumbing subcommands
    like `commit-tree` / `merge-tree`.

    `scan_target` lets callers pass a pre-stripped command (via
    `strip_quoted`) so the same Bash invocation isn't quote-stripped
    twice when downstream functions also need it.
    """
    if scan_target is None:
        scan_target = strip_quoted(command)
    return bool(re.search(GIT_PREFIX + r"(?:commit|merge)\b(?!-)", scan_target))

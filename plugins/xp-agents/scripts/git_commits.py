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


def _strip_quoted(command: str) -> str:
    """Remove quoted strings and heredocs to avoid matching inside arguments."""
    # Strip heredocs first (<<'DELIM'...DELIM or <<DELIM...DELIM)
    s = re.sub(
        r"<<-?\s*'?(\w+)'?.*?\n.*?\1",
        "",
        command,
        flags=re.DOTALL,
    )
    # Remove escaped quotes, then quoted strings
    s = s.replace("\\'", "").replace('\\"', "")
    s = re.sub(r"'[^']*'", "", s)
    s = re.sub(r'"[^"]*"', "", s)
    return s


def is_git_commit(command: str) -> bool:
    """Detect a commit-producing git command (commit or merge), not inside
    quoted arguments. The `(?!-)` lookahead rejects plumbing subcommands
    like `commit-tree` / `merge-tree`."""
    return bool(
        re.search(GIT_PREFIX + r"(?:commit|merge)\b(?!-)", _strip_quoted(command))
    )

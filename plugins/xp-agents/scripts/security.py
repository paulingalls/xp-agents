#!/usr/bin/env python3
"""Code-file classification and git commit detection.

Used by pre_tool_bash for the commit detection path and by bash_post_tool
for code-vs-doc tagging on commit events. The security-triage marker
subsystem this module used to host was removed in M-5 (sprint-052) once
Tier 1 patterns + Tier 2/3 LLM review took over the security-review story.
"""

import re
from pathlib import Path

# Non-code suffixes used by is_code_file() for consistent classification
_NON_CODE_SUFFIXES = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".adoc",
        ".tex",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".csv",
        ".plist",
        ".pbxproj",
        ".xcworkspacedata",
        ".xcscheme",
        ".lock",
        ".license",
    }
)

# Dotfiles and special names — matched by full filename (case-insensitive).
# Dotfiles like .gitignore have no suffix in Python (Path(".gitignore").suffix == "").
_NON_CODE_NAMES = frozenset(
    {
        "license",
        "changelog",
        "readme",
        "makefile",
        "dockerfile",
        ".gitignore",
        ".gitattributes",
        ".env",
        ".env.example",
        ".dockerignore",
        ".editorconfig",
        ".prettierignore",
        ".eslintignore",
    }
)


def is_code_file(path: str) -> bool:
    """Return True if the file is likely code (not docs/config/images)."""
    suffix = Path(path).suffix.lower()
    if suffix in _NON_CODE_SUFFIXES:
        return False
    return Path(path).name.lower() not in _NON_CODE_NAMES


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


# `git` followed by zero-or-more global options before the subcommand.
# Each option is `-X` (standalone) or `-X <value>` (paired). Covers `-C <path>`
# (the form agents adopt to avoid cd-poisoning Stop hooks), `-c <kv>`,
# `--git-dir=<path>`, `--work-tree=<path>`, `--paginate`, etc. Without this
# tolerance, those forms silently bypass subcommand detection: pre-tool gate
# skips review cycle, post-tool hook skips commit-event recording + marker
# reset, and `commits.get_code_files_for_review` misses unstaged tracked
# files for `git -C add` / `git -C commit -a`.
GIT_PREFIX = r"\bgit(?:\s+-\S+(?:\s+\S+)?)*\s+"


def is_git_commit(command: str) -> bool:
    """Detect a commit-producing git command (commit or merge), not inside
    quoted arguments. The `(?!-)` lookahead rejects plumbing subcommands
    like `commit-tree` / `merge-tree`."""
    return bool(
        re.search(GIT_PREFIX + r"(?:commit|merge)\b(?!-)", _strip_quoted(command))
    )

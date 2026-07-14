#!/usr/bin/env python3
"""Code-file classification — distinguishes source code from docs/config/
images for the per-commit review cycle and commit tagging.

Used by pre_tool_write for the code-vs-doc gate, by commits/work_signals/
honesty_signals for filtering, and by bash_post_tool for code-vs-doc
tagging on commit events.
"""

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
    """Return True if the file is likely code (not docs/config/images).

    lang-ok: _NON_CODE_SUFFIXES is a DENY list, so the classifier is agnostic by
    construction — everything is code unless proven otherwise. A .rs, .go or .kt
    file is never enumerated anywhere and still classifies correctly by falling
    through. Adding an ALLOW list here would break every language we forgot.
    """
    suffix = Path(path).suffix.lower()
    if suffix in _NON_CODE_SUFFIXES:
        return False
    return Path(path).name.lower() not in _NON_CODE_NAMES


def count_code_files(paths: list[str]) -> int:
    """Number of *paths* that classify as code via ``is_code_file``."""
    return sum(1 for p in paths if is_code_file(p))

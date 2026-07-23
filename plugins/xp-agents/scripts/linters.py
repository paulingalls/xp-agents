#!/usr/bin/env python3
"""The linter registry: which linter claims a file, and how to invoke it.

This module is the plugin's answer to "the user's project is written in
something other than Python". Everything language-specific about linting lives
here, as DATA — a row per linter — and nowhere else. Supporting one more
language is a row in these tables. It is never a branch, and it is never a map
of that language's rule codes (`{eslint: no-unused-vars, clippy: unused_imports}`
would be a hardcoded model of per-language rule *semantics*, which is precisely
the leak the project's cross-language guardrail forbids — and one that
`test_no_language_leak.py` cannot see, because that scanner only reads
file-extension predicates).

Split out of `lint_check` so the tables have one home and `lint_check` stays
under the 500-line cap.

DELIBERATELY NOT MOVED HERE: `subprocess` and `shutil`, and every function that
touches them (`run_linter`, `run_linter_batch`). ~25 tests intercept the linter
by patching `lint_check.shutil.which` / `lint_check.subprocess.run` — module-global
bindings. Had the runner functions moved into this module, those patches would
have silently stopped intercepting and the suite would have shelled out to the
real ruff instead of failing. The tables and `detect_linter_config` touch
neither module, so they move safely; the runners stay put.

The data tables themselves (LINTER_CONFIGS, LINTER_COMMANDS, and the rest) live
in `linter_tables`, imported back here and re-exported by identity, so this file
stays under the 500-line cap too — `linters.LINTER_CONFIGS is
linter_tables.LINTER_CONFIGS`.
"""

from pathlib import Path

from linter_tables import (
    CODE_EXTENSIONS,
    CONFIG_STYLE_FLAGS,
    DEGRADED_LINTERS,
    LINTER_ARGV_SHAPES,
    LINTER_BINARIES,
    LINTER_COMMANDS,
    LINTER_CONFIG_FLAGS,
    LINTER_CONFIGS,
    LINTER_EXTENSIONS,
    LINTER_PRECONDITIONS,
    LINTER_STDIN_SHAPES,
    LINTER_STRICT_FLAGS,
    NO_PER_FILE_ARGV,
    NO_STDIN,
    PATHS_BEFORE_SEPARATOR,
    SEPARATOR_BEFORE_PATHS,
    STDIN_ASSUME_FILENAME,
    STDIN_DISPLAY_NAME_TRAILING_DASH,
    STDIN_FILENAME_TRAILING_DASH,
    STDIN_FILEPATH,
    STDIN_FLAG_AND_FILENAME,
    STDIN_FLAG_WITH_FILENAME,
)

__all__ = [
    "CODE_EXTENSIONS",
    "CONFIG_STYLE_FLAGS",
    "DEGRADED_LINTERS",
    "LINTER_ARGV_SHAPES",
    "LINTER_BINARIES",
    "LINTER_COMMANDS",
    "LINTER_CONFIGS",
    "LINTER_CONFIG_FLAGS",
    "LINTER_EXTENSIONS",
    "LINTER_PRECONDITIONS",
    "LINTER_STDIN_SHAPES",
    "LINTER_STRICT_FLAGS",
    "NO_PER_FILE_ARGV",
    "NO_STDIN",
    "PATHS_BEFORE_SEPARATOR",
    "SEPARATOR_BEFORE_PATHS",
    "STDIN_ASSUME_FILENAME",
    "STDIN_DISPLAY_NAME_TRAILING_DASH",
    "STDIN_FILENAME_TRAILING_DASH",
    "STDIN_FILEPATH",
    "STDIN_FLAG_AND_FILENAME",
    "STDIN_FLAG_WITH_FILENAME",
    "detect_linter_config",
]


def detect_linter_config(
    cwd: str, git_root: str, file_path: str | None = None
) -> tuple[str, str] | None:
    """Walk from file dir (or cwd) up to git_root for linter config.

    With file_path, only returns a linter whose extensions match — finds
    pyproject.toml [tool.ruff] in subdirs, blocks eslint for .py files.
    Returns (linter_name, config_path) or None.

    lang-ok: the extension test routes a file to the linter that claims it, off
    the LINTER_EXTENSIONS table. Supporting one more language is a row in that
    table, not a branch here; an unclaimed extension simply finds no linter.
    """
    file_suffix = Path(file_path).suffix if file_path else None

    if file_path is not None:
        start_path = Path(cwd, file_path).resolve().parent
    else:
        start_path = Path(cwd).resolve()
    root_path = Path(git_root).resolve()

    current = start_path
    while True:
        for config_name, linter, content_check in LINTER_CONFIGS:
            if file_suffix is not None:
                allowed = LINTER_EXTENSIONS.get(linter)
                if allowed is not None and file_suffix not in allowed:
                    continue

            config_path = current / config_name
            if config_path.exists():
                if content_check is not None:
                    try:
                        text = config_path.read_text(encoding="utf-8")
                        if content_check not in text:
                            continue
                    except (OSError, UnicodeDecodeError):
                        continue
                return (linter, str(config_path))

        if current == root_path or current == current.parent:
            break
        current = current.parent

    return None


# Re-exported BY IDENTITY from the invocation module, which is split out to keep this
# file under the 500-line cap. `linters.linter_argv IS linter_invocation.linter_argv`.
#
# LAZILY, via PEP 562, and that is not a style choice. A bottom-of-file
# `from linter_invocation import ...` only works while `linters` is imported FIRST:
# import the invocation module first and it imports these tables, which run to the
# bottom, which re-imports a module that is still half-initialized —
#
#     ImportError: cannot import name '_compile_db_covers' from 'linter_invocation'
#
# Nothing does that today, so it never fired. But in a PreToolUse hook an ImportError
# exits 1, and the harness reads a non-2 exit as NON-BLOCKING: the commit lint gate
# would not fail closed, it would fail OPEN, and the commit would land unlinted. A
# gate taken down by an import order is the failure this release is named after.
#
# Deferring to first attribute access breaks the cycle without forking the function
# into two objects — `linters.linter_argv is linter_invocation.linter_argv` still
# holds, so a patch on either name intercepts the other.
_REEXPORTED = frozenset(
    {
        "_compile_db_covers",
        "degrade_reason",
        "linter_argv",
        "linter_command",
        "linter_stdin_argv",
        "optional_flag_retry",
        "preconditions_met",
    }
)


def __getattr__(name: str):
    if name in _REEXPORTED:
        import linter_invocation

        return getattr(linter_invocation, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

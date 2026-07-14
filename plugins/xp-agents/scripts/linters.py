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
"""

from pathlib import Path

LINTER_CONFIGS = [
    # (config_pattern, linter_name, check_content)
    # Python
    ("ruff.toml", "ruff", None),
    (".flake8", "flake8", None),
    ("pyproject.toml", "ruff", "[tool.ruff]"),
    ("setup.cfg", "flake8", "[flake8]"),
    # JavaScript/TypeScript
    (".eslintrc", "eslint", None),
    (".eslintrc.json", "eslint", None),
    (".eslintrc.js", "eslint", None),
    (".eslintrc.yml", "eslint", None),
    (".eslintrc.yaml", "eslint", None),
    ("eslint.config.js", "eslint", None),
    ("eslint.config.mjs", "eslint", None),
    ("eslint.config.ts", "eslint", None),
    (".prettierrc", "prettier", None),
    (".prettierrc.json", "prettier", None),
    (".prettierrc.js", "prettier", None),
    # Rust (clippy is built into cargo)
    ("Cargo.toml", "clippy", None),
    # Go
    (".golangci.yml", "golangci-lint", None),
    (".golangci.yaml", "golangci-lint", None),
    # Ruby
    (".rubocop.yml", "rubocop", None),
    # C/C++
    (".clang-tidy", "clang-tidy", None),
    (".clang-format", "clang-format", None),
    # Java/Kotlin
    ("checkstyle.xml", "checkstyle", None),
    ("detekt.yml", "detekt", None),
    # PHP
    ("phpcs.xml", "phpcs", None),
    (".php-cs-fixer.php", "php-cs-fixer", None),
    # Dart/Flutter
    ("analysis_options.yaml", "dart-analyze", None),
    # Elixir
    (".credo.exs", "credo", None),
    # C#
    ("stylecop.json", "dotnet-format", None),
    # Swift
    (".swiftlint.yml", "swiftlint", None),
]

LINTER_COMMANDS = {
    # `--output-format=concise` pins ruff to single-line `path:line:col: CODE msg`
    # shape that the parsers below expect. Without it, ruff 0.15+ defaults to
    # multi-line "full" format and the parsers extract zero codes — silently
    # killing the F401/F811 deferral pipeline. Do NOT remove.
    "ruff": ["ruff", "check", "--output-format=concise"],
    "flake8": ["flake8"],
    "eslint": ["npx", "eslint"],
    "prettier": ["npx", "prettier", "--check"],
    "clippy": ["cargo", "clippy", "--", "-D", "warnings"],
    "golangci-lint": ["golangci-lint", "run"],
    "rubocop": ["rubocop"],
    "clang-tidy": ["clang-tidy"],
    "clang-format": ["clang-format", "--dry-run", "-Werror"],
    "checkstyle": ["checkstyle", "-c", "/google_checks.xml"],
    "detekt": ["detekt"],
    "phpcs": ["phpcs"],
    "php-cs-fixer": ["php-cs-fixer", "fix", "--dry-run"],
    "dart-analyze": ["dart", "analyze"],
    "credo": ["mix", "credo"],
    "dotnet-format": ["dotnet", "format", "--verify-no-changes"],
    "swiftlint": ["swiftlint"],
}

# COLUMN: strictness. "Non-zero exit means it found something" is NOT true out of
# the box for every linter — some exit 0 even when they have findings to report,
# and a gate that reads only the exit code would call those runs clean.
#
# A row appears here only when its linter would otherwise lie about having found
# nothing. ruff, flake8, rubocop et al. are absent because they already exit
# non-zero on any finding; adding a redundant flag would just be noise.
#
# This is a flag, not a rule-code map. "--max-warnings=0" says BE STRICT; it does
# not encode what any particular rule of that language means. The linter still
# decides what it found — that distinction is the whole guardrail.
LINTER_STRICT_FLAGS: dict[str, list[str]] = {
    # eslint exits 0 when only warnings fire — and `no-unused-vars` is `warn` in
    # many popular configs, so the headline case (a staged .ts with an unused
    # import) would NOT block without this.
    "eslint": ["--max-warnings=0"],
    # swiftlint exits 0 on warning-severity violations unless told otherwise.
    "swiftlint": ["--strict"],
    # `dart analyze` exits 0 on info-severity lints, which is where its unused
    # import rule lands.
    "dart-analyze": ["--fatal-infos"],
}

# COLUMN: file scope. Some linters cannot judge a single file at all — they lint
# the whole project and exit non-zero on state that has nothing to do with what
# is staged. `cargo clippy -- -D warnings` compiles the entire crate: ONE
# pre-existing warning in a file nobody touched would block EVERY commit in the
# repo, unfixably, because the committing agent cannot fix it by fixing its diff.
#
# The gate DEGRADES on these rows (does not block) rather than blocking on
# whole-project state. That costs commit-time coverage for these ecosystems, and
# it is the right direction to be wrong in: a gate that cannot be satisfied is
# worse than one that stays quiet, because the first thing anyone does with an
# unfixable gate is disable it.
#
# Membership is per-row DATA. Moving a linter to file-scoped means proving it can
# lint one file and report only that file's findings — then delete its row.
PROJECT_SCOPED_LINTERS: frozenset[str] = frozenset(
    {
        "clippy",  # cargo clippy compiles the whole crate
        "checkstyle",  # config-driven project sweep
        "detekt",  # --input defaults to the whole source set
        "credo",  # mix credo walks the project
        "dotnet-format",  # --verify-no-changes covers the solution
    }
)

LINTER_EXTENSIONS: dict[str, set[str]] = {
    "ruff": {".py", ".pyi", ".ipynb"},
    "flake8": {".py", ".pyi"},
    "eslint": {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".vue"},
    "prettier": {
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".css",
        ".scss",
        ".json",
        ".md",
        ".yaml",
        ".yml",
    },
    "clippy": {".rs"},
    "golangci-lint": {".go"},
    "rubocop": {".rb"},
    "clang-tidy": {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"},
    "clang-format": {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"},
    "checkstyle": {".java"},
    "detekt": {".kt", ".kts"},
    "phpcs": {".php"},
    "php-cs-fixer": {".php"},
    "dart-analyze": {".dart"},
    "credo": {".ex", ".exs"},
    "dotnet-format": {".cs"},
    "swiftlint": {".swift"},
}

# Extensions that warrant a "set up a linter" nudge — excludes prettier-only
# formats (md, json, yaml, css) which don't need a real linter.
CODE_EXTENSIONS: frozenset[str] = frozenset(
    ext
    for linter, exts in LINTER_EXTENSIONS.items()
    if linter != "prettier"
    for ext in exts
)

LINTER_BINARIES = {
    "ruff": "ruff",
    "flake8": "flake8",
    "eslint": "npx",
    "prettier": "npx",
    "clippy": "cargo",
    "golangci-lint": "golangci-lint",
    "rubocop": "rubocop",
    "clang-tidy": "clang-tidy",
    "clang-format": "clang-format",
    "checkstyle": "checkstyle",
    "detekt": "detekt",
    "phpcs": "phpcs",
    "php-cs-fixer": "php-cs-fixer",
    "dart-analyze": "dart",
    "credo": "mix",
    "dotnet-format": "dotnet",
    "swiftlint": "swiftlint",
}


def linter_command(linter_name: str) -> list[str]:
    """The argv to invoke `linter_name` with, strictness flags included.

    Single source for both the edit-time (`run_linter`) and commit-time
    (`run_linter_batch`) paths, so the two cannot disagree about how strict the
    linter is. That matters: if the commit gate blocked on a warn-level finding
    that edit-time never surfaced, the agent would be ambushed at commit by a
    rule nothing had told it about.

    Callers append `["--", *paths]` themselves — the flags must land before that
    separator or the linter reads them as filenames.
    """
    return LINTER_COMMANDS[linter_name] + LINTER_STRICT_FLAGS.get(linter_name, [])


def is_file_scoped(linter_name: str) -> bool:
    """Can this linter judge ONE file, and report only that file's findings?

    False for linters that lint the whole project (see PROJECT_SCOPED_LINTERS).
    The commit-time gate must not block on a False row: its non-zero exit may be
    reporting project-wide state the staged diff neither caused nor can fix.

    Unknown rows answer True. A linter nobody classified is far likelier to be a
    normal file-scoped one than a project sweep, and the cost of being wrong that
    way is a too-strict block the agent can actually act on — versus the
    unfixable one that the other default would produce.
    """
    return linter_name not in PROJECT_SCOPED_LINTERS


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

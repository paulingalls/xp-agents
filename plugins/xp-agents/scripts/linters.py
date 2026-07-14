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
    # No `-c` here: the config comes from LINTER_CONFIG_FLAGS + the config that
    # detect_linter_config actually FOUND. Pinning `-c /google_checks.xml` threw that
    # away and judged every Java project by Google's style instead of its own.
    "checkstyle": ["checkstyle"],
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
    # MEASURED, not assumed (clang-tidy 22.1.8): invoked correctly, it FINDS the
    # violation, PRINTS it — and EXITS 0. So correcting its argv without this flag
    # would have CREATED a true false-clean: the gate would read "clean" on a file it
    # had just found a violation in. The argv fix alone was a trap, and only the real
    # binary could say so. See tests/hooks/test_lint_polyglot.py.
    "clang-tidy": ["--warnings-as-errors=*"],
}


# COLUMN: argv shape. WHERE the paths go relative to `--`. Every linter here took
# `[*cmd, "--", *paths]` — "options end, paths follow" — and for exactly one CLI that
# is wrong in a way that silently lints NOTHING.
#
# clang-tidy's synopsis is `clang-tidy [options] <source0>...<sourceN> -- [compiler
# -flags]`: everything AFTER the separator is COMPILER FLAGS. `clang-tidy -- app.c`
# therefore passes app.c to the compiler, not to the linter.
#
# This is a STRUCTURAL column, and the test for that is mechanical: could someone fill
# this row in correctly by reading the tool's `--help`, without knowing a single rule
# name of that language? Yes — it is in the synopsis. That is what separates it from a
# rule-code map (`{eslint: "no-unused-vars"}`), which would need the rule catalog and
# is precisely the leak the cross-language guardrail forbids. `LINTER_STRICT_FLAGS`
# above passes the same test, and is the precedent.
PATHS_BEFORE_SEPARATOR = "paths_before_separator"
SEPARATOR_BEFORE_PATHS = "separator_before_paths"  # the default
# ...and the third answer: there is NO per-file argv. Some CLIs take no source path
# at all — `cargo clippy` lints the CRATE. Handing them one is not a different shape,
# it is a question they cannot be asked, and the honest argv is None.
NO_PER_FILE_ARGV = "no_per_file_argv"

LINTER_ARGV_SHAPES: dict[str, str] = {
    "clang-tidy": PATHS_BEFORE_SEPARATOR,
    # MEASURED against real cargo. The shipped command ALREADY ends in a separator
    # (`cargo clippy -- -D warnings`: everything after `--` goes to rustc), so the
    # default shape appended a SECOND one and built
    #     cargo clippy -- -D warnings -- src/main.rs
    # which rustc rejects with `error: multiple input filenames provided`, exit 101.
    # The commit gate never saw it (the row degrades), but the EDIT-time path read
    # 101 as FINDINGS and raised a lint concern — whose text was a cargo argv error —
    # on every .rs file edited, and `lint_resolution` re-ran the same broken argv to
    # clear it and got 101 again. A concern that can never be resolved, in every Rust
    # project the plugin ships to.
    "clippy": NO_PER_FILE_ARGV,
}


# COLUMN: config flag. How this CLI is TOLD which config to use.
#
# checkstyle has no convention for finding its own config — it needs `-c`. The shipped
# command pinned `-c /google_checks.xml`, which threw away the `checkstyle.xml`
# `detect_linter_config` had just found and judged every Java project by Google's
# style instead of its own.
LINTER_CONFIG_FLAGS: dict[str, list[str]] = {
    "checkstyle": ["-c"],
}


# COLUMN: precondition. A file the PROJECT must have before this linter can be
# invoked at all — not a property of the linter, a property of the checkout.
#
# clang-tidy needs a compile database. Without one it cannot resolve `#include`s, so
# any file with a header in another directory fails to COMPILE:
# `clang-diagnostic-error: 'hdr.h' file not found` — non-zero, with output, which the
# gate's contract reads as FINDINGS. It would refuse the commit over a header path
# that nothing in the diff can fix, and the first thing anyone does with an unfixable
# gate is turn it off. So: no compile DB, no gate. Degrade, and say why.
LINTER_PRECONDITIONS: dict[str, str] = {
    "clang-tidy": "compile_commands.json",
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
#
# The set really answers "can the gate BLOCK on this row?", and there are two
# ways to answer no: the linter cannot judge one file (clippy), or the gate
# cannot invoke it correctly on one (clang-tidy — see below). Both degrade, for
# the same reason: a gate that cannot be satisfied gets disabled.
#
# A REASON, not a bare name. The old set carried only membership, so every degraded
# row was reported to the user with one blanket sentence — "it lints the whole
# project, not one file" — which for clang-tidy was simply FALSE, and this module
# knew it was false. We were lying to the customer in a string. Each row now says
# what is actually true of it, and `staged_lint` prints that.
DEGRADED_LINTERS: dict[str, str] = {
    "clippy": (
        "cargo clippy compiles the whole crate, so a pre-existing warning in a file "
        "nobody touched would block every commit in the repo, unfixably"
    ),
    "detekt": "--input defaults to the whole source set, not the staged files",
    "credo": "mix credo walks the whole project, not the staged files",
    "dotnet-format": "--verify-no-changes covers the whole solution",
    # MEASURED (checkstyle 13.8.0), and the reason Java is NOT gated:
    # checkstyle's exit code counts severity=ERROR violations only. The SAME
    # violation at severity=warning is printed and then exits 0 — which the gate's
    # contract reads as CLEAN. Its CLI has no warnings-as-errors lever (the options
    # are -b -c -d -e -E -f -g -G -h -j -J -o -p -s -t -T -V -w -x; `-w` is TAB
    # WIDTH). So its exit code cannot express "I found something", and the only way
    # to gate it would be to PARSE its report — and the parser WAS the bug (story-005).
    # Degraded honestly, rather than gated in name only.
    "checkstyle": (
        "its exit code counts severity=error only, so a severity=warning violation "
        "reports success — the exit code cannot express what it found"
    ),
}

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
        "is_file_scoped",
        "linter_argv",
        "linter_command",
        "preconditions_met",
    }
)


def __getattr__(name: str):
    if name in _REEXPORTED:
        import linter_invocation

        return getattr(linter_invocation, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

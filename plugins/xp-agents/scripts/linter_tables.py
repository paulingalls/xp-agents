#!/usr/bin/env python3
"""The linter data tables: which linter claims a file, and how to invoke it.

This module is the plugin's answer to "the user's project is written in
something other than Python". Everything language-specific about linting lives
here, as DATA — a row per linter — and nowhere else. Supporting one more
language is a row in these tables. It is never a branch, and it is never a map
of that language's rule codes (`{eslint: no-unused-vars, clippy: unused_imports}`
would be a hardcoded model of per-language rule *semantics*, which is precisely
the leak the project's cross-language guardrail forbids — and one that
`test_no_language_leak.py` cannot see, because that scanner only reads
file-extension predicates).

Split out of `linters` so the tables have one home and `linters` stays under
the 500-line cap. `linters` imports these names back and re-exports them by
identity — `from linters import LINTER_CONFIGS` and `linters.LINTER_COMMANDS`
resolve to the exact same objects defined here.

DELIBERATELY NOT MOVED HERE: `subprocess` and `shutil`, and every function that
touches them (`run_linter`, `run_linter_batch`). ~25 tests intercept the linter
by patching `lint_check.shutil.which` / `lint_check.subprocess.run` — module-global
bindings. Had the runner functions moved into this module, those patches would
have silently stopped intercepting and the suite would have shelled out to the
real ruff instead of failing. The tables and `detect_linter_config` touch
neither module, so they move safely; the runners stay put.

LOAD-BEARING CONSTRAINT: this module must never import from `linters` (no
circular import) — it is pure data, imported DOWN into `linters`.
"""

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
    # The same shape, on the three other rows DEGRADED_LINTERS already says lint
    # the WHOLE PROJECT (not just clippy's crate): detekt's `--input` defaults to
    # the whole source set, `mix credo` walks the whole project, and
    # `dotnet format --verify-no-changes` covers the whole solution. Each was
    # still building an edit-time argv of `[*cmd, "--", <one file>]` — a question
    # none of those CLIs can answer about a single file — which is the identical
    # trap clippy's row was added to close, just not yet closed here.
    "detekt": NO_PER_FILE_ARGV,
    "credo": NO_PER_FILE_ARGV,
    "dotnet-format": NO_PER_FILE_ARGV,
}


# COLUMN: stdin shape. HOW this CLI is handed source text on stdin while still being
# told which PATH that text belongs to — or that it cannot be, which is the default.
#
# The commit gate must judge the bytes in the INDEX, and those bytes are not always the
# bytes on disk. Writing them to a temp copy is what the gate used to do, and every
# copy breaks something: a temp SIBLING (random basename) defeats filename-keyed rules;
# a temp SUBDIR keeps the basename but moves the file one level DOWN, so every
# path-relative resolution the source does — `./util`, `../lib/x` — resolves to a path
# that does not exist. Both properties hold only at the real path, and stdin is how a
# linter reads bytes that are not there.
#
# A SHAPE, not a bool: the argv forms genuinely differ, so a caller handed `True` could
# not build the command. ruff wants a trailing positional `-` (its path argument is what
# selects stdin, and `--stdin-filename` only labels it); eslint wants a `--stdin` flag
# and NO positional; prettier reads piped stdin implicitly and names the path with a
# differently-spelled flag of its own. Nor can the shapes collapse into "flag + form":
# six CLIs spell the same idea six ways, and the spelling IS the data.
#
# STRUCTURAL, by the same mechanical test as the columns above: could someone fill a
# row in by reading the tool's `--help`, without knowing one rule name of that language?
# Yes — each form below is quoted from its own `--help` synopsis. A rule-code map is the
# leak; a flag spelling is not.
#
# Every row is MEASURED against the real binary, never read off a doc page: ruff 0.15,
# eslint v10, prettier 3, and (added when the stdin-less default was found to be
# reopening the gate's own fail-open) flake8 7.3, rubocop 1.81, clang-format 21.
#
# Absent rows answer NO_STDIN, and that default is the SAFE direction: a linter nobody
# has filled in is never invoked with an argv it did not agree to. But it is NOT a free
# default — the caller can no longer judge a divergent file's staged bytes at all, and
# fails closed instead (see staged_lint's branch C). That is a real cost, paid by a
# whole language, so a row belongs here whenever the tool can genuinely take it.
#
# What "genuinely" excludes, and why each is a NO_STDIN we chose rather than forgot:
#   * golangci-lint, clang-tidy, dart-analyze, php-cs-fixer — no stdin source mode.
#   * swiftlint — HAS `--use-stdin`, but no way to name the path with it: MEASURED,
#     it reports the file as `<nopath>`. This column's whole contract is bytes on
#     stdin *while still being told the path*, and a mode that cannot be told the
#     path would silently defeat the config's own `included`/`excluded` rules and
#     block a file the project says to skip. Half the contract is not a row.
#   * phpcs — documents `--stdin-path`, but no PHP toolchain was available to
#     MEASURE it, and this table does not take a doc page's word for it. Debt.
# `--stdin-filename X -` (the trailing `-` is the path arg, and it selects stdin)
STDIN_FILENAME_TRAILING_DASH = "stdin_filename_trailing_dash"
# `--stdin --stdin-filename X`, no positional
STDIN_FLAG_AND_FILENAME = "stdin_flag_and_filename"
# `--stdin-filepath X`, piped stdin read implicitly
STDIN_FILEPATH = "stdin_filepath"
# `--stdin-display-name X -` — ruff's idea, flake8's spelling. Same trailing `-` (the
# path arg is what selects stdin), a different flag name for the label.
STDIN_DISPLAY_NAME_TRAILING_DASH = "stdin_display_name_trailing_dash"
# `--stdin X` — the flag itself TAKES the path (`-s, --stdin FILE`), no positional.
STDIN_FLAG_WITH_FILENAME = "stdin_flag_with_filename"
# `--assume-filename=X`, piped stdin read implicitly when no path is given.
STDIN_ASSUME_FILENAME = "stdin_assume_filename"
# the default: this CLI reads no source on stdin
NO_STDIN = "no_stdin"

LINTER_STDIN_SHAPES: dict[str, str] = {
    "ruff": STDIN_FILENAME_TRAILING_DASH,
    "eslint": STDIN_FLAG_AND_FILENAME,
    "prettier": STDIN_FILEPATH,
    # `--stdin-display-name STDIN_DISPLAY_NAME`: "the name used when reporting
    # warnings and errors ... via stdin". MEASURED (flake8 7.3): a violation on
    # stdin reports at `pkg/app.py:1:1` and exits 1.
    "flake8": STDIN_DISPLAY_NAME_TRAILING_DASH,
    # `-s, --stdin FILE`: "Pipe source from STDIN, using FILE in offense reports".
    # MEASURED (rubocop 1.81): offenses report at `lib/app.rb:1:5`, exit 1.
    "rubocop": STDIN_FLAG_WITH_FILENAME,
    # `--assume-filename=<string>`: "Set filename used to determine the language ...
    # Only used when reading from stdin." MEASURED (clang-format 21): with the
    # shipped `--dry-run -Werror`, a violation reports at `src/a.c:1:4` and exits 1;
    # clean exits 0. Both halves matter — an exit-0-on-findings CLI would need a
    # LINTER_STRICT_FLAGS row too, and this one already has its strictness in
    # LINTER_COMMANDS.
    "clang-format": STDIN_ASSUME_FILENAME,
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


# COLUMN: config-style flags. An option a CLI accepts only in ONE of its own config
# MODES — keyed by the config FILE, because the file is what selects the mode.
#
# Not keyed by linter, and that is the whole point of the column. `--no-warn-ignored`
# is a real eslint option, but only under flat config (added 8.51); under `.eslintrc`
# it is an UNRECOGNISED option, and eslint answers that with exit 2 and nothing linted.
# The gate reads non-zero-with-output as FINDINGS, so a linter-keyed row would block
# EVERY commit in every eslintrc project — an unfixable gate, which is the one failure
# `DEGRADED_LINTERS` exists to avoid. The mode is not knowable from the linter's name;
# it is knowable from the config file `detect_linter_config` already found.
#
# Why the gate needs it at all: `LINTER_STRICT_FLAGS` ships eslint `--max-warnings=0`
# so warn-level rules block. eslint reports "File ignored because of a matching ignore
# pattern" as a WARNING, so once the gate lints files at their REAL paths — where an
# ignore pattern finally matches — that warning trips the threshold and the gate
# refuses a file the project's own config says to skip, with nothing to fix. MEASURED
# against eslint v10: exit 1 by path AND via --stdin-filename; exit 0 with this flag.
#
# Structural, by the same test as the columns above: the row is the flag's own `--help`
# line ("Suppress warnings when the file list includes ignored files") plus which config
# file enables it. No rule name, in any language. The alternative — reading eslint's
# message text — is a rule map by another name, and forbidden.
#
# An absent row adds nothing, which is why an unknown config style is safe by default:
# the tool is invoked exactly as it is today.
CONFIG_STYLE_FLAGS: dict[str, list[str]] = {
    "eslint.config.js": ["--no-warn-ignored"],
    "eslint.config.mjs": ["--no-warn-ignored"],
    "eslint.config.ts": ["--no-warn-ignored"],
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

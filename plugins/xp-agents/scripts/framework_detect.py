#!/usr/bin/env python3
"""Which test framework, if any, a shell command runs.

Split from `test_parsing` when the result-parsing half grew its per-framework
summary anchors. The two halves answer different questions off different
inputs — this one reads a COMMAND LINE before the run, that one reads the
OUTPUT after it — and neither calls the other.

`test_parsing` re-exports `is_test_run`, so every existing importer and
`mock.patch("...test_parsing.is_test_run")` site keeps working unchanged.

Stdlib only (re).
"""

import re

# Bounded lazy-quantifier "0-5 intervening tokens" — the upper bound keeps
# regex engines from backtracking pathologically on long arg lists. The token
# class excludes shell separators so the gap cannot span them: with a bare
# `\S+`, `&&` is an ordinary token and `bun build x.ts && npm test` binds the
# `bun` of one command to the `test` of another, reporting a bun test run
# where none exists.
_FLAG_GAP = r"(?:\s+[^\s;&|]+){0,5}?"
# Reject characters that would extend `test` into a different identifier.
# Includes `.` (file extensions: `bun build test.ts` shouldn't match `test`),
# `-` (kebab tool names: `pnpm exec test-fixture-builder`), and word chars
# (script names: scripts already capture via the colon-suffix group).
_NOT_IDENT_TAIL = r"(?![\w.-])"
# Allow colon-suffixed script names: test, test:unit, test:e2e-live (hyphens
# allowed within the suffix for kebab-case scripts).
_TEST_SCRIPT_TAIL = r"test(?::[\w:-]+)?" + _NOT_IDENT_TAIL

# Package-script / workspace launcher patterns used by is_test_run — the test
# target lives in package.json/config, NOT on the command line. Named as
# constants because the regexes are dense and flag-tolerant; verify_paths'
# classify_path_strategy keys off is_test_run's *return value*, so the
# launcher vocabulary stays here as the single source.
_TURBO_RE = (
    r"\b(?:npx\s+|bunx\s+|pnpm\s+|yarn\s+|bun\s+x\s+)?turbo"
    + _FLAG_GAP
    + r"\s+(?:run\s+)?"
    + _TEST_SCRIPT_TAIL
)
_NX_RES = (
    r"\bnx\s+test\b",
    r"\bnx\s+run\s+\S+:test\b",
    r"\bnx\s+\S+\s+--targets?=test(?:[,\s]|$)",
)
_BUN_SCRIPT_RE = r"\bbun" + _FLAG_GAP + r"\s+(?:run\s+)?" + _TEST_SCRIPT_TAIL
# bun is a hybrid: `bun run <script>` / `bun <script>:<suffix>` are package-
# script aliases (no CLI path, like the npm/pnpm/yarn forms above); bare
# `bun test [<spec>...]` is a direct runner naming spec files as positionals.
# Used by verify_paths.classify_path_strategy to split the two, the same way
# a literal `jest` token disambiguates jest's alias vs. direct forms.
_BUN_ALIAS_RE = r"\bbun" + _FLAG_GAP + r"\s+(?:run\s+\S+|test:[\w:-]+)"
# Shell chain separators. Both bun regexes scan the whole command string, so a
# chained command is judged segment by segment — otherwise a `run <script>`
# token in a LATER segment (`bun test a.test.ts && npm run build`) reads the
# whole chain as an alias and the spec path is lost to the whole-tree sentinel.
_CHAIN_SPLIT_RE = r"&&|\|\||;|\|"
# Anything that ends the run bun's positionals belong to. Redirects join the
# chain separators here because `bun test 2>&1 | tee out.log` puts a
# path-shaped artifact in the scanned region just as surely as `&&` does.
_SHELL_BREAK_RE = r"&&|\|\||;|\||>|<"
# Flags naming the directory the specs are relative to. Their value is
# discarded by the pre-binary skip, so the specs lose the only context that
# made them resolvable.
_CWD_FLAGS = ("--cwd", "-C")
_CWD_FLAG_PREFIXES = ("--cwd=", "-C=")
_GLOB_CHARS = ("*", "?", "[")
# Extensions bun can actually load as a spec file. A positional carrying one
# (or a directory separator) is a path; one carrying neither is a filter.
_SPEC_SUFFIXES = (
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
)
_NPM_SCRIPT_RE = (
    r"\b(?:npm|pnpm|yarn|lerna)" + _FLAG_GAP + r"\s+(?:run\s+)?" + _TEST_SCRIPT_TAIL
)


def is_bun_script_alias(command: str) -> bool:
    """True for bun's package-script alias forms, false for its direct form.

    `bun ... run <script>` and `bun ... <script>:<suffix>` (`bun test:unit`,
    `bun test:e2e-live`) name a package.json script, not a CLI path — alias.
    Bare `bun test [<spec>...]` runs bun's own test binary, naming spec files
    (if any) as positionals — direct, not an alias. Only called once
    `is_test_run` has already returned "bun", so the caller is disambiguating
    a known bun-test command, not detecting one.

    A chain mixing the two forms is NOT an alias: one direct segment means a
    spec path is on the command line, and losing it to the whole-tree
    sentinel is the fail-open this split exists to close (the caller's jest
    branch is biased the same way — any literal `jest` token wins).
    """
    for segment in re.split(_CHAIN_SPLIT_RE, command):
        if re.search(_BUN_SCRIPT_RE, segment) and not re.search(_BUN_ALIAS_RE, segment):
            return False
    return bool(re.search(_BUN_ALIAS_RE, command))


def bun_names_extractable_specs(command: str) -> bool:
    """True when a bun command's positionals are real, comparable spec paths.

    bun's positionals are substring FILTER PATTERNS — `bun test math.test`
    runs `src/math.test.ts` — so a path-shaped token is only sometimes a file.
    Extracting one that isn't demands a proof path no commit can ever touch,
    and an unsatisfiable required path is strictly worse than no path at all:
    the whole-tree sentinel fails OPEN, while a false positive can never go
    green. So this answers conservatively, and every False retreats the caller
    to the sentinel — exactly the behaviour bun commands had before they were
    extracted at all, which is why no retreat here can block a merge.

    Four disqualifiers, each an observed false positive:

    - an alias form (delegated to `is_bun_script_alias`) — no CLI path exists
    - a shell separator or redirect: the scan runs to end of string, so a
      later segment's `| tee out.log` or `&& node build.js` is harvested as a
      spec. Judging bun per-segment instead would have to re-home the leading
      `cd <dir> &&` peel, which is the caller's, so the chain retreats whole
    - a working-directory flag (`--cwd`, `-C`): its value is dropped, leaving
      directory-relative specs compared against repo-relative git output
    - a glob: `src/*.test.ts` is matched by the shell or by bun, never by
      literal string comparison against a changed-file list

    Then at least one positional must LOOK like a file — carry a directory
    separator, or a source-file extension. A bare `math.test` carries neither,
    which is the only lexical signal separating a dotted filter from a real
    spec without touching the filesystem (which extraction never does).
    """
    if is_bun_script_alias(command):
        return False
    if re.search(_SHELL_BREAK_RE, command):
        return False
    tokens = command.split()
    if any(t in _CWD_FLAGS or t.startswith(_CWD_FLAG_PREFIXES) for t in tokens):
        return False
    positionals = [t for t in tokens if not t.startswith("-")]
    if any(g in t for t in positionals for g in _GLOB_CHARS):
        return False
    return any("/" in t or t.endswith(_SPEC_SUFFIXES) for t in positionals)


def is_test_run(command: str) -> str | None:
    """Check if the command is a test run. Returns framework name or None."""
    # Python
    if re.search(r"\bpytest\b", command) or re.search(
        r"python3?\s+-m\s+pytest\b", command
    ):
        return "pytest"
    if re.search(r"python3?\s+-m\s+unittest\b", command):
        return "unittest"

    # JavaScript/TypeScript
    # Playwright — check before generic script aliases; covers
    # `playwright test`, `npx/bunx/pnpm-exec/yarn playwright test`, and
    # `./node_modules/.bin/playwright test` (\b matches at `/`).
    if re.search(r"\bplaywright\s+test\b", command):
        return "playwright"

    # Direct runners. `\b` already matches at `/` boundaries, so a single
    # word-bounded match covers bare invocation, npx/bunx/pnpm-exec/yarn-dlx
    # wrappers, and direct-binary path tails (`./node_modules/.bin/jest`).
    if re.search(r"\bjest\b", command):
        return "jest"
    if re.search(r"\bvitest\b", command):
        return "vitest"
    if re.search(r"\bmocha\b", command):
        return "mocha"

    # Node built-in test runner: `node --test`, `node --test test/**/*.js`
    if re.search(r"\bnode\s+--test\b", command):
        return "node-test"
    # Deno test runner: `deno test`, `deno test src/`
    if re.search(r"\bdeno\s+test\b", command):
        return "deno"

    # Workspace task runners (turbo). Check turbo before bun/pnpm so that
    # `pnpm turbo test` returns "turbo" rather than the pnpm-script form.
    # Turbo accepts `turbo test`, `turbo run test`, with or without a
    # wrapping `npx`/`bunx`/`pnpm`. `--filter=<pkg>` and other flags may
    # appear after `test`.
    if re.search(_TURBO_RE, command):
        return "turbo"

    # nx workspace runner: `nx test <pkg>`, `nx run <pkg>:test`,
    # `nx run-many --target=test`, `nx run-many --targets=test,build`.
    if any(re.search(p, command) for p in _NX_RES):
        return "nx"

    # bun: bare `bun test[:script]` or `bun run test[:script]`, and the
    # workspace form `bun --filter <pkg> test[:script]` (and similar
    # flag-tolerant variants up to 5 intervening tokens).
    if re.search(_BUN_SCRIPT_RE, command):
        return "bun"

    # npm/pnpm/yarn/lerna script aliases — flag-tolerant (covers --filter,
    # --workspace, -w, -F, -r, workspace foreach, workspace <pkg>, run, etc.)
    # bound to 5 intervening tokens. lerna folded in here since it shares
    # the script-alias shape (`lerna run test [--scope=<pkg>]`).
    if re.search(_NPM_SCRIPT_RE, command):
        return "jest"

    # Go
    if re.search(r"\bgo\s+test\b", command):
        return "go"
    # Swift/Xcode
    if re.search(r"\bxcodebuild\b.*\btest\b", command):
        return "xcodebuild"
    if re.search(r"\bswift\s+test\b", command):
        return "swift"
    # Rust
    if re.search(r"\bcargo\s+test\b", command):
        return "cargo"
    # Java/Kotlin — flag-tolerant for monorepo/multi-module forms like
    # `mvn -pl <module> test`, `mvn -pl <module> verify`.
    if re.search(r"\bmvn" + _FLAG_GAP + r"\s+(?:test|verify)\b", command):
        return "maven"
    # Gradle accepts `gradle test`, `./gradlew test`, `./gradlew :module:test`,
    # `./gradlew :module:sub:test` (path-prefixed task name). `\bgradlew\b`
    # subsumes both `./gradlew` and bare `gradlew` invocations.
    if re.search(
        r"\b(?:gradle|gradlew)" + _FLAG_GAP + r"\s+(?::?[\w:-]+:)?test\b",
        command,
    ):
        return "gradle"
    # Ruby
    if re.search(r"\brspec\b", command):
        return "rspec"
    if re.search(r"\bruby\s+-Itest\b", command) or re.search(
        r"\brake\s+test\b", command
    ):
        return "minitest"
    # PHP
    if re.search(r"\bphpunit\b", command):
        return "phpunit"
    # C# / .NET
    if re.search(r"\bdotnet\s+test\b", command):
        return "dotnet"
    # Dart/Flutter
    if re.search(r"\bdart\s+test\b", command) or re.search(
        r"\bflutter\s+test\b", command
    ):
        return "dart"
    # Elixir
    if re.search(r"\bmix\s+test\b", command):
        return "elixir"
    # C/C++ (Google Test, CTest)
    if re.search(r"\bctest\b", command):
        return "ctest"
    return None

#!/usr/bin/env python3
"""Seed a default shared_mental_model.json for new projects.

Scans the project for linter config, tests, git hooks, and CI setup.
Writes an initial SMM dict with XP-aligned Constraints and Risks
based on what's detected (or missing).

Only runs if shared_mental_model.json does not already exist.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

import git_hooks
from _probe import probe_config_file
from smm_schema import SOURCE_SEED, empty_smm
from smm_store import SMM_FILENAME, save_smm

_SEED_TS = "1970-01-01T00:00:00+00:00"

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

# -- Linter configs (catch bugs, anti-patterns) --
_LINTER_CONFIGS = [
    # Python
    "ruff.toml",
    ".flake8",
    ".pylintrc",
    ".mypy.ini",
    # JS/TS
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.js",
    ".eslintrc.yml",
    ".eslintrc.yaml",
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.ts",
    # Rust
    "Cargo.toml",  # clippy via cargo
    # Go
    ".golangci.yml",
    ".golangci.yaml",
    # Ruby
    ".rubocop.yml",
    # C/C++/Objective-C
    ".clang-tidy",
    # Java
    "checkstyle.xml",
    "pmd.xml",
    "spotbugs.xml",
    # Kotlin
    "detekt.yml",
    ".ktlint",
    # PHP
    "phpcs.xml",
    "phpstan.neon",
    "phpstan.neon.dist",
    # Dart/Flutter
    "analysis_options.yaml",
    # Elixir
    ".credo.exs",
    # C#
    "stylecop.json",
    ".editorconfig",  # dotnet analyzers use this
    # Swift
    ".swiftlint.yml",
    # Scala
    ".scalafix.conf",
    "scalafix.conf",
    # Lua
    ".luacheckrc",
    # Haskell
    ".hlint.yaml",
    # Zig — built-in, no config file (detected via zig.zon)
    # Multi-language
    "biome.json",
    "biome.jsonc",
]

# -- Formatter configs (consistent style) --
_FORMATTER_CONFIGS = [
    # Python
    "ruff.toml",  # ruff does both lint + format
    # JS/TS/HTML/CSS/JSON/MD
    ".prettierrc",
    ".prettierrc.json",
    ".prettierrc.yml",
    ".prettierrc.yaml",
    ".prettierrc.js",
    ".prettierrc.cjs",
    ".prettierrc.mjs",
    "prettier.config.js",
    "prettier.config.cjs",
    "prettier.config.mjs",
    # Rust
    "rustfmt.toml",
    ".rustfmt.toml",
    # C/C++/Objective-C
    ".clang-format",
    # PHP
    ".php-cs-fixer.php",
    ".php-cs-fixer.dist.php",
    # Ruby — rubocop does both lint + format
    ".rubocop.yml",
    # Swift
    ".swift-format",
    # Kotlin
    ".editorconfig",  # ktfmt/ktlint use this
    # Elixir
    ".formatter.exs",
    # Scala
    ".scalafmt.conf",
    # Lua
    "stylua.toml",
    ".stylua.toml",
    # Haskell
    ".ormolu",
    "fourmolu.yaml",
    ".fourmolu.yaml",
    # Multi-language
    "biome.json",
    "biome.jsonc",
]

# Content checks for ambiguous config files
_LINTER_CONTENT_CHECKS = {
    "pyproject.toml": "[tool.ruff]",
    "setup.cfg": "[flake8]",
    "build.gradle": "checkstyle",  # Java/Kotlin Gradle projects
    "build.gradle.kts": "checkstyle",
}

_FORMATTER_CONTENT_CHECKS = {
    "pyproject.toml": "[tool.ruff.format]",
    "Cargo.toml": "[profile",  # implies rustfmt via cargo
    "build.gradle": "spotless",  # Java/Kotlin Gradle formatter
    "build.gradle.kts": "spotless",
    "mix.exs": "formatter",  # Elixir mix format config
}

_TEST_DIRS = {"tests", "__tests__", "test", "spec"}

_TEST_FILE_PATTERNS = [
    "test_*.py",
    "*_test.py",
    "*.test.js",
    "*.test.ts",
    "*.test.tsx",
    "*.spec.js",
    "*.spec.ts",
    "*_test.go",
    "*_test.rs",
    "*Test.java",
    "*Test.kt",
    "*Tests.swift",
    "*Tests.m",  # Objective-C (XCTest)
    "*Tests.mm",  # Objective-C++ (XCTest)
    "*Test.cs",
    "*_test.dart",
    "*_test.exs",
    "*_test.lua",
    "*Spec.scala",
    "*Test.scala",
    "*Spec.hs",
    "*_test.zig",
]

# Languages with built-in formatters (no config file to detect).
# We check for source files instead.
_BUILTIN_FORMATTER_GLOBS = [
    "*.go",  # gofmt is built-in
    "*.dart",  # dart format is built-in
    "*.zig",  # zig fmt is built-in
]

_CI_INDICATORS = [
    ".github/workflows",
    ".gitlab-ci.yml",
    "Jenkinsfile",
    ".circleci",
    ".travis.yml",
    "azure-pipelines.yml",
]


def _find_git_root() -> Path | None:
    """Find the git root directory."""
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return Path(root)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def has_linter(root: Path) -> bool:
    """Check if any linter config exists."""
    for config in _LINTER_CONFIGS:
        if probe_config_file(root, config) is not None:
            return True
    for config, content in _LINTER_CONTENT_CHECKS.items():
        if probe_config_file(root, config, content) is not None:
            return True
    return False


def has_formatter(root: Path) -> bool:
    """Check if any code formatter config exists or language has built-in formatter."""
    for config in _FORMATTER_CONFIGS:
        if probe_config_file(root, config) is not None:
            return True
    for config, content in _FORMATTER_CONTENT_CHECKS.items():
        if probe_config_file(root, config, content) is not None:
            return True
    # Languages with built-in formatters — check for source files
    for pattern in _BUILTIN_FORMATTER_GLOBS:
        if list(root.glob(pattern)) or list(root.glob(f"*/{pattern}")):
            return True
    return False


def has_tests(root: Path) -> bool:
    """Check if test files or directories exist.

    Searches up to 3 levels deep for test directories (fast — just names)
    and 2 levels deep for test file patterns (covers monorepos).
    """
    # Check test directories up to 3 levels deep
    for depth in ("", "*/", "*/*/", "*/*/*/"):
        for test_dir in _TEST_DIRS:
            if list(root.glob(f"{depth}{test_dir}/")):
                return True
    # Check for src/test (Maven/Gradle) up to 2 levels
    if (root / "src" / "test").is_dir():
        return True
    for subdir in root.glob("*/"):
        if (subdir / "src" / "test").is_dir():
            return True
    # Check *Tests/ directories (Xcode) up to 2 levels
    for depth in ("", "*/"):
        for d in root.glob(f"{depth}*Tests/"):
            if d.is_dir():
                return True
    # Check test file patterns at root and one level deep
    for pattern in _TEST_FILE_PATTERNS:
        if list(root.glob(pattern)):
            return True
        if list(root.glob(f"*/{pattern}")):
            return True
    return False


def _has_non_sample_pre_commit_content(root: Path) -> bool:
    """A `.git/hooks/pre-commit` exists with real content (not the sample boilerplate).

    Intent-aware fallback: catches scripts a developer wrote but forgot to
    chmod +x. ``git_hooks.will_fire_hook`` is strict and would say False here.
    """
    hook = root / ".git" / "hooks" / "pre-commit"
    # lang-ok: `.sample` is git's own boilerplate suffix in .git/hooks, identical
    # in every repo git creates. It names no programming language.
    if not hook.exists() or hook.name.endswith(".sample"):
        return False
    try:
        content = hook.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return "This hook is invoked" not in content


def has_git_hooks(root: Path) -> bool:
    """Check if git commit hooks are configured (intent-aware).

    True when git would actually fire a hook (framework markers, executable
    pre-commit/pre-push, or a ``core.hooksPath`` override pointing at one),
    OR when a non-executable pre-commit script exists with real content
    (developer intent, even if it won't fire as-is).
    """
    return git_hooks.will_fire_hook(str(root)) or _has_non_sample_pre_commit_content(
        root
    )


def has_ci(root: Path) -> bool:
    """Check if CI/CD is configured."""
    return any((root / indicator).exists() for indicator in _CI_INDICATORS)


# ---------------------------------------------------------------------------
# SMM generation
# ---------------------------------------------------------------------------


def _seed_entry(pillar: str, content: str, **extra: str) -> dict:
    """Build a seed entry with a deterministic ID from content."""
    entry = {
        "id": hashlib.sha256(f"seed:{pillar}:{content}".encode()).hexdigest()[:12],
        "content": content,
        "source": SOURCE_SEED,
        "ts": _SEED_TS,
    }
    entry.update(extra)
    return entry


def generate_smm(root: Path) -> dict:
    """Generate seed SMM as a structured dict based on project analysis."""
    linter = has_linter(root)
    formatter = has_formatter(root)
    tests = has_tests(root)
    hooks = has_git_hooks(root)
    ci = has_ci(root)

    constraints = [
        _seed_entry(
            "constraints",
            "Write tests before implementation (TDD) — red, green, commit, refactor",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Plan before building new features — use plan mode for design",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Small commits — one logical change per commit",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Small files — target 300 lines, max 500. "
            "Large files eat agent context on every read",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Use strict linting — catch bugs and anti-patterns automatically",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Use a code formatter — consistent style keeps diffs clean",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Use git commit hooks — run lint and tests before every commit",
            type="convention",
        ),
        _seed_entry(
            "constraints",
            "Tests are production code — same review cycle, same quality bar. "
            "Never skip or abbreviate reviews for test-only changes",
            type="convention",
        ),
    ]

    risks: list[dict] = []
    if not linter:
        risks.append(
            _seed_entry(
                "risks",
                "No linter configured — add one to catch bugs automatically "
                "(e.g., ruff for Python, eslint for JS/TS, clippy for Rust, "
                "golangci-lint for Go)",
                type="concern",
                severity="problem",
            )
        )
    if not formatter:
        risks.append(
            _seed_entry(
                "risks",
                "No code formatter configured — add one for consistent style "
                "(e.g., ruff format for Python, prettier for JS/TS, gofmt "
                "for Go, rustfmt for Rust)",
                type="concern",
                severity="problem",
            )
        )
    if not tests:
        risks.append(
            _seed_entry(
                "risks",
                "No test files detected — create a test directory and write "
                "tests before implementation",
                type="concern",
                severity="problem",
            )
        )
    if not hooks:
        risks.append(
            _seed_entry(
                "risks",
                "No git commit hooks configured — add lefthook or husky to "
                "run lint and tests on every commit",
                type="concern",
                severity="problem",
            )
        )
    if not ci:
        risks.append(
            _seed_entry(
                "risks",
                "No CI/CD configured — add a workflow to run tests on push",
                type="concern",
                severity="problem",
            )
        )

    wisdom = [
        _seed_entry(
            "wisdom",
            "Run /xp-kickoff at every session start — "
            "it handles retrospective, goals, and housekeeping",
        ),
        _seed_entry(
            "wisdom",
            "Commit after every green test run — "
            "frequent commits keep /xp-quality-review small",
        ),
        _seed_entry(
            "wisdom",
            "Review cadence (commit | story), chosen at kickoff: in commit "
            "cadence run /xp-quality-review before each commit; in story "
            "cadence the per-commit gate defers and /xp-quality-review runs "
            "at /xp-story-close on the cumulative diff. /code-review "
            "(Workflow tool) runs once at free/sprint/plan close; LLM "
            "/security-review fires at close Step 4.",
        ),
        _seed_entry(
            "wisdom",
            "After exiting plan mode, run /xp-review-plan before writing "
            "code — it extracts assumptions, decisions, and risks into the SMM",
        ),
        _seed_entry(
            "wisdom",
            "Keep files small with single responsibility and DRY — "
            "one concern per file, extract when you see duplication "
            "or mixed responsibilities",
        ),
        _seed_entry(
            "wisdom",
            "Fail fast, fail loud — raise exceptions rather than "
            "returning None or empty results when something is wrong",
        ),
        _seed_entry(
            "wisdom",
            "Name things well — use descriptive names over comments. "
            "If you need a comment to explain what, rename instead",
        ),
        _seed_entry(
            "wisdom",
            "Test at boundaries — validate at system edges "
            "(external input, APIs, I/O), trust internal logic. "
            "Test behavior, not implementation",
        ),
    ]

    smm = empty_smm()
    smm["constraints"] = constraints
    smm["risks"] = risks
    smm["wisdom"] = wisdom
    return smm


def main() -> None:
    """Seed SMM if it doesn't exist. Called by init.sh."""
    if len(sys.argv) < 2:
        print("Usage: seed_smm.py <smm_dir>", file=sys.stderr)
        sys.exit(1)

    smm_dir = Path(sys.argv[1])
    smm_file = smm_dir / SMM_FILENAME

    # Only seed if the JSON file doesn't exist.
    # A stale SHARED_MENTAL_MODEL.md may be present — leave it alone.
    if smm_file.exists():
        sys.exit(0)

    root = _find_git_root()
    if root is None:
        sys.exit(0)

    data = generate_smm(root)
    save_smm(smm_dir, data)


if __name__ == "__main__":
    main()

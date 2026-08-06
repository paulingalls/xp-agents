#!/usr/bin/env python3
"""Project feature detection for SMM seeding.

Answers "what does this project already have?" — a linter, a formatter, tests,
git commit hooks, CI. `seed_smm.py` turns those answers into seeded Constraints
and Risks; nothing here knows about pillars or entries.

Split out of `seed_smm.py`, which sat at its recorded file-size ceiling with no
room for a new seeded entry. The two halves grow for different reasons: this
one every time a language's tooling gains a config file, the other when the
seeded content changes.
"""

from pathlib import Path

import git_hooks
from _probe import probe_config_file

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

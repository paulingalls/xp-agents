#!/usr/bin/env python3
"""Seed a default SHARED_MENTAL_MODEL.md for new projects.

Scans the project for linter config, tests, git hooks, and CI setup.
Writes an initial SMM with XP-aligned Constraints and Risks based
on what's detected (or missing).

Only runs if SHARED_MENTAL_MODEL.md does not already exist.
"""

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

_LINTER_CONFIGS = [
    "ruff.toml",
    ".flake8",
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.js",
    ".eslintrc.yml",
    ".eslintrc.yaml",
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.ts",
    "Cargo.toml",  # clippy via cargo
    ".golangci.yml",
    ".golangci.yaml",
    ".rubocop.yml",
    ".clang-tidy",
    "checkstyle.xml",
    "detekt.yml",
    "phpcs.xml",
    "analysis_options.yaml",
    ".credo.exs",
    "stylecop.json",
    ".swiftlint.yml",
    "biome.json",  # biome does both lint + format
    "biome.jsonc",
]

_FORMATTER_CONFIGS = [
    "ruff.toml",  # ruff does both lint + format
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
    ".clang-format",
    ".php-cs-fixer.php",
    "rustfmt.toml",
    ".rustfmt.toml",
    ".editorconfig",
    "biome.json",
    "biome.jsonc",
]

# Content checks for ambiguous config files
_LINTER_CONTENT_CHECKS = {
    "pyproject.toml": "[tool.ruff]",
    "setup.cfg": "[flake8]",
}

_FORMATTER_CONTENT_CHECKS = {
    "pyproject.toml": "[tool.ruff.format]",
    "Cargo.toml": "[profile",  # implies rustfmt via cargo
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
    "*Test.cs",
    "*_test.dart",
    "*_test.exs",
]

_HOOK_INDICATORS = [
    "lefthook.yml",
    ".lefthook.yml",
    ".husky/pre-commit",
    ".pre-commit-config.yaml",
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
        if (root / config).exists():
            return True
    for config, content in _LINTER_CONTENT_CHECKS.items():
        path = root / config
        if path.exists():
            try:
                if content in path.read_text(encoding="utf-8"):
                    return True
            except (OSError, UnicodeDecodeError):
                continue
    return False


def has_formatter(root: Path) -> bool:
    """Check if any code formatter config exists."""
    for config in _FORMATTER_CONFIGS:
        if (root / config).exists():
            return True
    for config, content in _FORMATTER_CONTENT_CHECKS.items():
        path = root / config
        if path.exists():
            try:
                if content in path.read_text(encoding="utf-8"):
                    return True
            except (OSError, UnicodeDecodeError):
                continue
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


def has_git_hooks(root: Path) -> bool:
    """Check if git commit hooks are configured."""
    for indicator in _HOOK_INDICATORS:
        if (root / indicator).exists():
            return True
    # Check for non-sample pre-commit hook
    hook = root / ".git" / "hooks" / "pre-commit"
    if hook.exists() and not hook.name.endswith(".sample"):
        try:
            content = hook.read_text(encoding="utf-8")
            # Skip if it's just the sample content
            if "This hook is invoked" not in content:
                return True
        except (OSError, UnicodeDecodeError):
            pass
    return False


def has_ci(root: Path) -> bool:
    """Check if CI/CD is configured."""
    return any((root / indicator).exists() for indicator in _CI_INDICATORS)


# ---------------------------------------------------------------------------
# SMM generation
# ---------------------------------------------------------------------------


def generate_smm(root: Path) -> str:
    """Generate seed SMM content based on project analysis."""
    linter = has_linter(root)
    formatter = has_formatter(root)
    tests = has_tests(root)
    hooks = has_git_hooks(root)
    ci = has_ci(root)

    # Constraints — XP defaults
    constraints = [
        "Write tests before implementation (TDD) — red, green, commit, refactor",
        "Plan before building new features — use plan mode for design",
        "Small commits — one logical change per commit",
        "Small files — target 300 lines, max 500. "
        "Large files eat agent context on every read",
        "Use strict linting — catch bugs and anti-patterns automatically",
        "Use a code formatter — consistent style keeps diffs clean",
        "Use git commit hooks — run lint and tests before every commit",
    ]

    # Risks — based on what's missing
    risks: list[str] = []
    if not linter:
        risks.append(
            "No linter configured — add one to catch bugs automatically "
            "(e.g., ruff for Python, eslint for JS/TS, clippy for Rust, "
            "golangci-lint for Go)"
        )
    if not formatter:
        risks.append(
            "No code formatter configured — add one for consistent style "
            "(e.g., ruff format for Python, prettier for JS/TS, gofmt for Go, "
            "rustfmt for Rust)"
        )
    if not tests:
        risks.append(
            "No test files detected — create a test directory and write "
            "tests before implementation"
        )
    if not hooks:
        risks.append(
            "No git commit hooks configured — add lefthook or husky to run "
            "lint and tests on every commit"
        )
    if not ci:
        risks.append("No CI/CD configured — add a workflow to run tests on push")

    # Build the SMM
    lines = ["# Shared Mental Model", ""]
    lines.append("## Intent")
    lines.append("- (no goals set yet — run /xp-kickoff to get started)")
    lines.append("")

    lines.append("## Constraints")
    for c in constraints:
        lines.append(f"- {c}")
    lines.append("")

    lines.append("## Risks")
    if risks:
        for r in risks:
            lines.append(f"- {r}")
    else:
        lines.append(
            "- (none detected — project has linter, formatter, tests, hooks, and CI)"
        )
    lines.append("")

    lines.append("## Wisdom")
    lines.append(
        "- Run /xp-kickoff at every session start — "
        "it handles retrospective, goals, and housekeeping"
    )
    lines.append(
        "- Commit after every green test run — "
        "the commit gate enforces the review cycle "
        "(/simplify, /xp-quality-review, /xp-security-triage) "
        "so frequent commits keep reviews small and fast"
    )
    lines.append(
        "- Complete the review cycle before committing code changes — "
        "/simplify → /xp-quality-review → /xp-security-triage → commit"
    )
    lines.append(
        "- After exiting plan mode, run /xp-review-plan before writing code — "
        "it extracts assumptions, decisions, and risks into the SMM"
    )
    lines.append(
        "- Keep files small with single responsibility and DRY — "
        "one concern per file, extract when you see duplication "
        "or mixed responsibilities"
    )
    lines.append(
        "- Fail fast, fail loud — raise exceptions rather than "
        "returning None or empty results when something is wrong"
    )
    lines.append(
        "- Name things well — use descriptive names over comments. "
        "If you need a comment to explain what, rename instead"
    )
    lines.append(
        "- Test at boundaries — validate at system edges "
        "(external input, APIs, I/O), trust internal logic. "
        "Don't write tests for trivially correct code — "
        "test behavior, not implementation"
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Seed SMM if it doesn't exist. Called by init.sh."""
    if len(sys.argv) < 2:
        print("Usage: seed_smm.py <smm_dir>", file=sys.stderr)
        sys.exit(1)

    smm_dir = Path(sys.argv[1])
    smm_file = smm_dir / "SHARED_MENTAL_MODEL.md"

    # Only seed if SMM doesn't exist
    if smm_file.exists():
        sys.exit(0)

    root = _find_git_root()
    if root is None:
        sys.exit(0)

    content = generate_smm(root)
    smm_file.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()

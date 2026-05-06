#!/usr/bin/env python3
"""PostToolUse command hook: run project linter on modified file.

Detects linter configuration, runs linter with timeout, and appends concern
events for lint errors. Warns once if no linter is configured.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import identity
import worktree
from event_schema import STATUS_ACTION_LINT_RESOLVED

# ---------------------------------------------------------------------------
# Linter detection
# ---------------------------------------------------------------------------

_LINTER_CONFIGS = [
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

_LINTER_COMMANDS = {
    # `--output-format=concise` pins ruff to the legacy single-line
    # `path:line:col: CODE message` shape that `_RUFF_LINE_CODE` /
    # `_RUFF_LINE_PATH_CODE` parse. ruff 0.15+ defaults to multi-line
    # "full" format with arrows; without this pin both parsers silently
    # extract zero codes and the F401/F811 deferral pipeline (edit-time
    # filter + staging-time gate + run_linter_batch commit gate) is dead
    # code.
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

_LINTER_EXTENSIONS: dict[str, set[str]] = {
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

# Extensions that warrant a "set up a linter" nudge — excludes non-code
# formats (md, json, yaml, css, etc.) that only formatters like prettier handle.
_CODE_EXTENSIONS: frozenset[str] = frozenset(
    ext
    for linter, exts in _LINTER_EXTENSIONS.items()
    if linter != "prettier"
    for ext in exts
)

_LINTER_BINARIES = {
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
    """Walk from file's directory (or cwd) up to git_root looking for linter config.

    When file_path is provided, starts from the file's parent directory
    and only returns a linter that handles the file's extension. This
    finds e.g. pyproject.toml with [tool.ruff] in a subdirectory, and
    prevents eslint being selected for .py files.

    Returns (linter_name, config_path) or None.
    """
    file_suffix = Path(file_path).suffix if file_path else None

    # Start from the file's directory if available, otherwise cwd.
    # This finds linter configs in subdirectories (e.g., apps/agent/pyproject.toml).
    if file_path is not None:
        file_abs = Path(cwd, file_path).resolve()
        start_path = file_abs.parent
    else:
        start_path = Path(cwd).resolve()
    root_path = Path(git_root).resolve()

    current = start_path
    while True:
        for config_name, linter, content_check in _LINTER_CONFIGS:
            # Skip linters that can't handle this file type
            if file_suffix is not None:
                allowed = _LINTER_EXTENSIONS.get(linter)
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


# ---------------------------------------------------------------------------
# Linter execution
# ---------------------------------------------------------------------------

# Codes deferred until the file is staged for commit. F401 (unused import) and
# F811 (redefinition of unused) false-positive routinely during multi-step
# replace_all migrations: an import added in one Edit and consumed in the next
# fires F401 mid-stream. The commit-gate check in
# pre_tool_bash._staged_ruff_findings (which calls run_linter_batch with
# context="staging") catches truly-unused imports before they ship.
EDIT_DEFERRED_CODES: frozenset[str] = frozenset({"F401", "F811"})

# Code shape shared by all pyflakes-family linters (ruff/pylint/flake8): one or
# more uppercase letters followed by 3-4 digits. Ruff plugin namespaces keep
# growing (F=1, RUF=3, PERF=4, ASYNC=5, ...), so the prefix is unbounded. Single
# source of truth — both the per-line ruff parser (run_ruff) and the summary
# extractor (_summarize_lint_output) consume it.
_PYFLAKES_CODE_SHAPE = r"[A-Z]+\d{3,4}"

# Matches the leading code on a ruff line: "path:line:col: F401 [*] message"
_RUFF_LINE_CODE = re.compile(rf"^\s*[^:\s]+:\d+:\d+:\s+({_PYFLAKES_CODE_SHAPE})\b")
# Same shape but also captures the path — used by run_linter_batch to bucket
# findings back to their source file when ruff is forked over many paths.
_RUFF_LINE_PATH_CODE = re.compile(rf"^([^\s:]+):\d+:\d+:\s+({_PYFLAKES_CODE_SHAPE})\b")


def _eligible_for_linter(linter_name: str, paths: list[str]) -> list[str]:
    """Filter ``paths`` to those the linter handles, preserving order.

    Combines the two guards `run_linter` and `run_linter_batch` need:
    skip flag-shaped paths (argument-injection guard) and skip files
    whose extension the linter doesn't claim. Single source of truth
    so future linter additions don't risk one caller's filter drifting
    from another's.
    """
    allowed = _LINTER_EXTENSIONS.get(linter_name)
    return [
        p
        for p in paths
        if not p.startswith("-") and (allowed is None or Path(p).suffix in allowed)
    ]


def run_linter(linter_name: str, file_path: str, cwd: str | None = None) -> str | None:
    """Run linter on file. Returns error output or None if clean/unavailable.

    cwd is passed to subprocess.run so relative file paths resolve correctly.
    """
    binary = _LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return None

    # `_eligible_for_linter` enforces the argument-injection guard
    # (no leading `-`) and the per-linter extension allowlist; sharing
    # it with `run_linter_batch` keeps the security guard from drifting.
    if not _eligible_for_linter(linter_name, [file_path]):
        return None

    # Use "--" to separate flags from the filename argument
    cmd = _LINTER_COMMANDS[linter_name] + ["--", file_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        if result.returncode != 0:
            output = result.stdout or result.stderr
            return output.strip() if output else "Lint errors detected"
    except subprocess.TimeoutExpired:
        return None
    except (OSError, FileNotFoundError):
        return None

    return None


def run_ruff(
    file_path: str | Path,
    *,
    context: Literal["edit", "staging"],
    cwd: str | None = None,
) -> tuple[list[str], str]:
    """Single source of truth for ruff invocation.

    Runs ruff once, returns (codes, filtered_text). In ``edit`` context,
    codes in EDIT_DEFERRED_CODES (F401, F811) are stripped from both
    outputs — they belong at staging time. In ``staging`` context, all
    codes are reported.

    Returns ([], "") when ruff is unavailable, the file extension is wrong,
    or ruff exits clean. Used by lint_check.run() (edit) and
    pre_tool_bash (staging).
    """
    raw = run_linter("ruff", str(file_path), cwd=cwd)
    if raw is None:
        return ([], "")

    kept_lines: list[str] = []
    codes: list[str] = []
    deferred = EDIT_DEFERRED_CODES if context == "edit" else frozenset()
    for line in raw.splitlines():
        m = _RUFF_LINE_CODE.match(line)
        code = m.group(1) if m else None
        if code and code in deferred:
            continue
        kept_lines.append(line)
        if code:
            codes.append(code)
    text = "\n".join(kept_lines).strip()
    # dedupe preserving order
    return (list(dict.fromkeys(codes)), text)


def run_linter_batch(
    linter_name: str,
    paths: list[str],
    *,
    context: Literal["edit", "staging"],
    cwd: str | None = None,
) -> dict[str, list[str]]:
    """Run linter once over many paths; return {path: codes} per file.

    Generalizes per-file `run_ruff` so commit-gate callers (today
    `pre_tool_bash._staged_ruff_findings`) can fork the linter ONCE
    for all changed files instead of once per file. Output codes are
    filtered the same way `run_ruff` filters: ``edit`` strips
    EDIT_DEFERRED_CODES (F401/F811); ``staging`` keeps everything.

    Per-line parsing is ruff-specific today (uses `_RUFF_LINE_PATH_CODE`).
    Routing by `linter_name` is generic — flake8/eslint siblings can
    join when the per-line parser branches by linter, not before.

    Returns ``{}`` when the linter binary is missing, no eligible paths
    remain, OR ruff times out / fails to spawn. The empty-on-failure
    contract matches `run_linter`/`run_ruff` — the caller treats an
    absent path the same as "linter unavailable" and falls back to
    other gates. Returning `{p: []}` on timeout would silently report
    "all clean" and bypass the F401/F811 commit gate.

    Files the linter saw but with no findings map to ``[]`` so callers
    can distinguish "linted clean" (key present, value empty) from
    "skipped" (key absent).

    Timeout is 10s vs `run_linter`'s 5s — batch covers more files;
    ruff at ~1ms/file gives 10000-file headroom.
    """
    binary = _LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return {}

    eligible = _eligible_for_linter(linter_name, paths)
    if not eligible:
        return {}

    cmd = _LINTER_COMMANDS[linter_name] + ["--"] + eligible
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return {}

    raw = proc.stdout or proc.stderr or ""
    deferred = EDIT_DEFERRED_CODES if context == "edit" else frozenset()

    out: dict[str, list[str]] = {p: [] for p in eligible}
    for line in raw.splitlines():
        m = _RUFF_LINE_PATH_CODE.match(line)
        if not m:
            continue
        path, code = m.group(1), m.group(2)
        if code in deferred:
            continue
        if path in out and code not in out[path]:
            out[path].append(code)

    return out


def _summarize_lint_output(lint_output: str) -> str:
    """Extract error codes from lint output for a concise concern summary.

    Returns e.g. "3 errors (F401, I001)" instead of full ruff/eslint output.
    The agent already sees the full output via additionalContext.

    Supports:
    - ruff/pylint/flake8: uppercase letter + digits (F401, C0114, E302)
    - eslint: kebab-case rules at end of line (no-unused-vars, no-console)
    - eslint plugins: scoped rules (@typescript-eslint/no-explicit-any)
    """
    # ruff/pylint/flake8 codes: F401, I001, C0114, W0611, RUF059, PERF401
    codes = re.findall(rf"\b({_PYFLAKES_CODE_SHAPE})\b", lint_output)
    # eslint rules: "  error  'x' is unused  no-unused-vars" or "(no-unused-vars)"
    eslint_rules = re.findall(
        r"[\s(]((?:@[\w-]+/)?[a-z][\w-]*(?:/[a-z][\w-]*)*)[)\s]*$",
        lint_output,
        re.MULTILINE,
    )
    # Filter eslint noise (common non-rule words that match the pattern)
    _ESLINT_NOISE = frozenset({"error", "warning", "info", "help", "fixable"})
    eslint_rules = [r for r in eslint_rules if r not in _ESLINT_NOISE and "-" in r]
    all_codes = codes + eslint_rules
    unique_codes = list(dict.fromkeys(all_codes))  # dedupe, preserve order
    n = len(all_codes) or 1
    code_str = ", ".join(unique_codes[:5])
    if len(unique_codes) > 5:
        code_str += f", +{len(unique_codes) - 5} more"
    return (
        f"{n} error{'s' if n != 1 else ''} ({code_str})"
        if unique_codes
        else "errors found"
    )


def _has_unresolved_lint_concern(smm_dir: Path, normalized: str) -> bool:
    """Check if an unresolved lint concern exists for this file."""
    return concerns.has_unresolved_concerns(
        smm_dir, lambda c: concerns.lint_concern_matches(c, normalized)
    )


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core lint_check logic. Returns additionalContext with lint errors, or None."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    agent_id = identity.resolve_agent_id(input_data)
    cwd = input_data.get("cwd", ".")

    file_path = _common.extract_file_path(tool_name, tool_input)
    if not file_path:
        return None

    normalized = worktree.normalize_path(file_path, cwd)

    git_root = worktree.resolve_git_root(cwd) or cwd

    config = detect_linter_config(cwd, git_root, file_path=normalized)

    if config is None:
        # Only nudge for code files — non-code (md, txt, yml) doesn't need a linter
        if Path(normalized).suffix not in _CODE_EXTENSIONS:
            return None
        # Nudge once per session — atomic create, no symlink follow
        flag = smm_dir / ".lint-warned"
        try:
            fd = os.open(
                str(flag), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            os.close(fd)
            return (
                "No linter configured. Consider setting one up "
                "(e.g., ruff for Python, eslint for JS/TS)."
            )
        except (FileExistsError, OSError):
            pass  # Already nudged this session or symlink — skip
        return None

    linter_name, _config_path = config

    # Check if binary is available
    binary = _LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return None

    # Route ruff through run_ruff so the edit-time filter (F401/F811 deferred
    # to staging) is the single source of truth for the ruff command line.
    # Gate on parsed codes for ruff: filtered output may retain ruff's
    # "Found N errors." footer even when every individual code was filtered.
    if linter_name == "ruff":
        codes, lint_output = run_ruff(normalized, context="edit", cwd=git_root)
        has_errors = bool(codes)
    else:
        lint_output = run_linter(linter_name, normalized, cwd=git_root) or ""
        has_errors = bool(lint_output)
    if has_errors:
        if not _has_unresolved_lint_concern(smm_dir, normalized):
            summary = _summarize_lint_output(lint_output)
            concern = _common.make_event(
                _common.CONCERN,
                agent_id,
                f"{concerns.LINT_CONCERN_PREFIX}{normalized}: {summary}",
                severity="medium",
                files=[normalized],
            )
            _common.append_safe(smm_dir, concern)
        # Return as additionalContext for immediate feedback
        return f"Lint errors in {normalized}:\n{lint_output}"
    else:
        concerns.resolve_concerns(
            smm_dir,
            lambda c, n=normalized: concerns.lint_concern_matches(c, n),
            "lint-check",
            "Lint concern resolved",
            extra_metadata={"action": STATUS_ACTION_LINT_RESOLVED},
        )

    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output(
            "PostToolUse",
            result,
            "Lint errors found — fix before committing.",
        )
    sys.exit(0)

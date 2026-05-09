#!/usr/bin/env python3
"""PostToolUse hook: run project linter on modified file; append concern on errors."""

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

# Extensions that warrant a "set up a linter" nudge — excludes prettier-only
# formats (md, json, yaml, css) which don't need a real linter.
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
    """Walk from file dir (or cwd) up to git_root for linter config.

    With file_path, only returns a linter whose extensions match — finds
    pyproject.toml [tool.ruff] in subdirs, blocks eslint for .py files.
    Returns (linter_name, config_path) or None.
    """
    file_suffix = Path(file_path).suffix if file_path else None

    if file_path is not None:
        start_path = Path(cwd, file_path).resolve().parent
    else:
        start_path = Path(cwd).resolve()
    root_path = Path(git_root).resolve()

    current = start_path
    while True:
        for config_name, linter, content_check in _LINTER_CONFIGS:
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


# Per-file timeout (run_linter); also the base for run_linter_batch's scaled
# timeout: min(CAP, BASE + PER_PATH * N). Single source so bumps land in both.
LINTER_BASE_TIMEOUT_S: float = 5.0
BATCH_TIMEOUT_PER_PATH_S: float = 0.05
BATCH_TIMEOUT_CAP_S: float = 10.0

# Codes deferred until staging. F401 (unused import) / F811 (redef of unused)
# false-positive during multi-Edit migrations — an import added in one Edit and
# consumed in the next fires F401 mid-stream. pre_tool_bash._staged_ruff_findings
# (run_linter_batch context="staging") catches the real cases at commit time.
EDIT_DEFERRED_CODES: frozenset[str] = frozenset({"F401", "F811"})

# pyflakes-family code shape (ruff/pylint/flake8): [A-Z]+ + 3-4 digits. Ruff
# plugin namespaces keep growing (F, RUF, PERF, ASYNC, ...) so prefix is unbounded.
_PYFLAKES_CODE_SHAPE = r"[A-Z]+\d{3,4}"

# Per-line code: "path:line:col: F401 [*] message"
_RUFF_LINE_CODE = re.compile(rf"^\s*[^:\s]+:\d+:\d+:\s+({_PYFLAKES_CODE_SHAPE})\b")
# Same shape + path capture, used by run_linter_batch to bucket per-file findings.
_RUFF_LINE_PATH_CODE = re.compile(rf"^([^\s:]+):\d+:\d+:\s+({_PYFLAKES_CODE_SHAPE})\b")


def _eligible_for_linter(linter_name: str, paths: list[str]) -> list[str]:
    """Filter paths the linter handles, order-preserving.

    Skips flag-shaped paths (arg-injection guard) and extensions the linter
    doesn't claim. Shared by run_linter and run_linter_batch — single source
    so the security guard can't drift between callers.
    """
    allowed = _LINTER_EXTENSIONS.get(linter_name)
    return [
        p
        for p in paths
        if not p.startswith("-") and (allowed is None or Path(p).suffix in allowed)
    ]


def run_linter(linter_name: str, file_path: str, cwd: str | None = None) -> str | None:
    """Run linter on file. Returns error output, or None if clean/unavailable."""
    binary = _LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return None

    if not _eligible_for_linter(linter_name, [file_path]):
        return None

    # "--" separates flags from filename arg
    cmd = _LINTER_COMMANDS[linter_name] + ["--", file_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=LINTER_BASE_TIMEOUT_S,
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
    """Run ruff once; return (codes, filtered_text).

    edit context strips EDIT_DEFERRED_CODES (F401/F811) — they belong at
    staging. staging keeps everything. Returns ([], "") when ruff is
    unavailable, extension wrong, or exit clean. Single source of truth
    for ruff invocation (used by lint_check.run() and pre_tool_bash).
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

    Filtering matches run_ruff: edit strips F401/F811, staging keeps all.
    Per-line parsing is ruff-specific (_RUFF_LINE_PATH_CODE); routing by
    linter_name is generic — siblings can join when the parser branches.

    Returns {} when binary is missing, no eligible paths, or ruff
    times out / fails to spawn. Absence of a path means "not verified",
    NOT "clean" — callers gating on F401/F811 (pre_tool_bash) MUST treat
    missing paths as fail-closed. Linted-but-clean files map to [] so
    callers can distinguish "clean" (key present) from "skipped" (absent).

    Timeout: min(10, 5 + 0.05 * N) — single-file batches fail fast,
    large batches stay bounded so a hung ruff can't stall a 100-file commit.
    """
    binary = _LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return {}

    eligible = _eligible_for_linter(linter_name, paths)
    if not eligible:
        return {}

    cmd = _LINTER_COMMANDS[linter_name] + ["--"] + eligible
    timeout = min(
        BATCH_TIMEOUT_CAP_S,
        LINTER_BASE_TIMEOUT_S + BATCH_TIMEOUT_PER_PATH_S * len(eligible),
    )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        # Do NOT normalize to {p: [] for p in eligible} on failure — callers
        # gating on F401/F811 must distinguish "not verified" (missing key)
        # from "clean" (key with []), or the gate silently reopens.
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
    """Concise concern summary like "3 errors (F401, I001)".

    Full output already reaches the agent via additionalContext.
    Handles ruff/pylint/flake8 codes and eslint kebab/scoped rules.
    """
    codes = re.findall(rf"\b({_PYFLAKES_CODE_SHAPE})\b", lint_output)
    # eslint: "  error 'x' is unused  no-unused-vars" or "(no-unused-vars)"
    eslint_rules = re.findall(
        r"[\s(]((?:@[\w-]+/)?[a-z][\w-]*(?:/[a-z][\w-]*)*)[)\s]*$",
        lint_output,
        re.MULTILINE,
    )
    _ESLINT_NOISE = frozenset({"error", "warning", "info", "help", "fixable"})
    eslint_rules = [r for r in eslint_rules if r not in _ESLINT_NOISE and "-" in r]
    all_codes = codes + eslint_rules
    unique_codes = list(dict.fromkeys(all_codes))
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
        # Only nudge for code files — non-code (md, json, yml) doesn't need a linter
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
            pass
        return None

    linter_name, _config_path = config

    binary = _LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return None

    # Route ruff through run_ruff so the edit-time filter (F401/F811 deferred to
    # staging) is single source of truth. Gate on parsed codes — filtered output
    # may keep ruff's "Found N errors." footer even when every code was filtered.
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

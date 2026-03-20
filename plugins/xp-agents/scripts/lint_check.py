#!/usr/bin/env python3
"""PostToolUse command hook: run project linter on modified file.

Detects linter configuration, runs linter with timeout, and appends concern
events for lint errors. Warns once if no linter is configured.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns

# ---------------------------------------------------------------------------
# Linter detection
# ---------------------------------------------------------------------------

_LINTER_CONFIGS = [
    # (config_pattern, linter_name, check_content)
    ("ruff.toml", "ruff", None),
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
    (".flake8", "flake8", None),
    ("pyproject.toml", "ruff", "[tool.ruff]"),
    ("setup.cfg", "flake8", "[flake8]"),
]

_LINTER_COMMANDS = {
    "ruff": ["ruff", "check"],
    "eslint": ["npx", "eslint"],
    "prettier": ["npx", "prettier", "--check"],
    "flake8": ["flake8"],
}

# File extensions each linter understands. Skip the file silently if it doesn't match.
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
}

_LINTER_BINARIES = {
    "ruff": "ruff",
    "eslint": "npx",
    "prettier": "npx",
    "flake8": "flake8",
}


def detect_linter_config(cwd: str, git_root: str) -> tuple[str, str] | None:
    """Walk from cwd to git_root looking for linter config.

    Returns (linter_name, config_path) or None.
    """
    cwd_path = Path(cwd).resolve()
    root_path = Path(git_root).resolve()

    current = cwd_path
    while True:
        for config_name, linter, content_check in _LINTER_CONFIGS:
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


def run_linter(linter_name: str, file_path: str) -> str | None:
    """Run linter on file. Returns error output or None if clean/unavailable."""
    binary = _LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return None

    # Guard against argument injection: reject paths that look like flags
    if file_path.startswith("-"):
        return None

    # Skip files the linter doesn't understand
    allowed = _LINTER_EXTENSIONS.get(linter_name)
    if allowed is not None and Path(file_path).suffix not in allowed:
        return None

    # Use "--" to separate flags from the filename argument
    cmd = _LINTER_COMMANDS[linter_name] + ["--", file_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            output = result.stdout or result.stderr
            return output.strip() if output else "Lint errors detected"
    except subprocess.TimeoutExpired:
        return None
    except (OSError, FileNotFoundError):
        return None

    return None


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core lint_check logic. Returns additionalContext with lint errors, or None."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    agent_id = input_data.get("agent_id", "main")
    cwd = input_data.get("cwd", ".")

    file_path = _common.extract_file_path(tool_name, tool_input)
    if not file_path:
        return None

    normalized = _common.normalize_path(file_path, cwd)

    # Detect git root for config walking
    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        git_root = cwd

    config = detect_linter_config(cwd, git_root)

    if config is None:
        # Ask once per project — atomic create, no symlink follow
        flag = smm_dir / ".lint-warned"
        try:
            fd = os.open(
                str(flag), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            os.close(fd)
            question = _common.make_event(
                _common.QUESTION,
                agent_id,
                "No linter configured. Want me to set one up? "
                "(e.g., ruff for Python, eslint for JS/TS)",
                priority=_common.PRIORITY_ASSUMED,
            )
            _common.append_safe(smm_dir, question)
        except (FileExistsError, OSError):
            pass  # Already asked or symlink — skip
        return None

    linter_name, _config_path = config

    # Check if binary is available
    binary = _LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return None

    # Run linter
    lint_output = run_linter(linter_name, normalized)
    if lint_output:
        # Append concern event (record for SMM / retrospective)
        concern = _common.make_event(
            _common.CONCERN,
            agent_id,
            f"{concerns.LINT_CONCERN_PREFIX}{normalized}:\n{lint_output}",
            severity="medium",
        )
        _common.append_safe(smm_dir, concern)
        # Return as additionalContext for immediate feedback
        return f"Lint errors in {normalized}:\n{lint_output}"
    else:
        prefix = f"{concerns.LINT_CONCERN_PREFIX}{normalized}:"
        concerns.resolve_concerns(
            smm_dir,
            lambda c, p=prefix: c.startswith(p),
            "lint-check",
            "Lint concern resolved",
        )

    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)

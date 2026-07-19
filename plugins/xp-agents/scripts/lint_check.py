#!/usr/bin/env python3
"""PostToolUse hook: run project linter on modified file; append concern on errors."""

import os
import re
import shutil
import subprocess  # noqa: F401 — kept so lint_check.subprocess resolves for dotted mock.patch sites; see below
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import identity

# detect_linter_config is re-exported into this namespace on purpose: ~25 tests
# and lint_resolution reach it as `lint_check.detect_linter_config`, and the
# patch sites bind to THIS module. The tables live in `linters` — one home for
# everything language-specific; see that module's docstring.
import marker_names
import worktree
from event_schema import STATUS_ACTION_LINT_RESOLVED

# The linter-invocation group (run_linter, run_ruff, run_linter_batch,
# run_linter_stdin, LintRun, and the timeout constants/regex helpers they alone
# need) moved to lint_runners.py to keep this file under the line cap. Re-
# exported BY IDENTITY: staged_lint.py, lint_resolution.py, and ~89 test patch
# sites all reach these as `lint_check.X`. `subprocess` (imported above) stays
# bound in this module too, unused directly, so that dotted patches like
# mock.patch("lint_check.subprocess.run") keep resolving — they patch the
# shared subprocess module object, which lint_runners imports the same way.
from lint_runners import (  # noqa: F401 — re-exported by identity for staged_lint.py / tests
    _PYFLAKES_CODE_SHAPE,
    BATCH_TIMEOUT_BASE_S,
    BATCH_TIMEOUT_CAP_S,
    BATCH_TIMEOUT_PER_PATH_S,
    EDIT_DEFERRED_CODES,
    LINTER_BASE_TIMEOUT_S,
    LintRun,
    run_linter,
    run_linter_batch,
    run_linter_stdin,
    run_ruff,
)
from linters import (
    CODE_EXTENSIONS,
    LINTER_BINARIES,
    detect_linter_config,
)


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


def lint_invocation_target(
    config_path: str, git_root: str, normalized: str
) -> tuple[str, str]:
    """Return (lint_cwd, file_arg) for invoking a linter on *normalized*.

    The linter runs FROM the config file's directory, not git_root. In a
    monorepo the linter binary lives in the subpackage's node_modules
    (`npx eslint` resolves it by walking up from cwd) and eslint v9 flat
    config resolves `eslint.config.*` relative to cwd — running from the repo
    root finds neither, so every subpackage edit fired a spurious lint concern
    that could never clear. The file arg is realpath'd then made relative to
    the config dir: normalize_path skips symlink resolution but
    detect_linter_config .resolve()s the config path, so both sides must be
    realpath'd before relpath or the result drifts (/var vs /private/var).
    Single source for lint_check.run() and lint_resolution.
    """
    lint_cwd = str(Path(config_path).parent)
    abs_file = Path(normalized)
    if not abs_file.is_absolute():
        abs_file = Path(git_root) / normalized
    file_arg = os.path.relpath(os.path.realpath(str(abs_file)), lint_cwd)
    return lint_cwd, file_arg


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
        # lang-ok: CODE_EXTENSIONS spans the languages a linter nudge can help;
        # an unlisted one just gets no nudge, which is a missing suggestion, not
        # a blocked or misjudged write.
        if Path(normalized).suffix not in CODE_EXTENSIONS:
            return None
        # Nudge once per session — atomic create, no symlink follow
        flag = smm_dir / marker_names.LINT_WARNED
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

    linter_name, config_path = config

    binary = LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return None

    lint_cwd, file_arg = lint_invocation_target(config_path, git_root, normalized)

    # Route ruff through run_ruff so the edit-time filter (F401/F811 deferred to
    # the commit gate) is single source of truth. Gate on parsed codes — filtered
    # output may keep ruff's "Found N errors." footer even when every code was
    # filtered.
    if linter_name == "ruff":
        codes, lint_output = run_ruff(file_arg, cwd=lint_cwd)
        has_errors = bool(codes)
    else:
        lint_output = (
            run_linter(
                linter_name,
                file_arg,
                cwd=lint_cwd,
                root=git_root,
                config_path=config_path,
            )
            or ""
        )
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

#!/usr/bin/env python3
"""PostToolUse hook: run project linter on modified file; append concern on errors."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal, NamedTuple

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import identity
import marker_names
import worktree
from event_schema import STATUS_ACTION_LINT_RESOLVED

# detect_linter_config is re-exported into this namespace on purpose: ~25 tests
# and lint_resolution reach it as `lint_check.detect_linter_config`, and the
# patch sites bind to THIS module. The tables live in `linters` — one home for
# everything language-specific; see that module's docstring.
from linters import (
    CODE_EXTENSIONS,
    LINTER_BINARIES,
    LINTER_EXTENSIONS,
    detect_linter_config,
    linter_command,
)

# Edit-time, per-file (run_linter). Deliberately short: this path is
# interactive, and its timeout is HARMLESS — it returns None, so a slow linter
# just means no nudge on that keystroke.
LINTER_BASE_TIMEOUT_S: float = 5.0

# Commit-time, per batch (run_linter_batch): min(CAP, BASE + PER_PATH * N).
#
# NOT the edit-time number, though it once was. The two have opposite failure
# semantics: an edit-time timeout is silent, while a batch timeout is
# `unverified` and the commit gate fails CLOSED on it — it BLOCKS. And a timeout
# is the one `unverified` cause the agent cannot act on: it can install a missing
# binary, but it cannot make golangci-lint faster. Too small a budget therefore
# blocks every commit in that ecosystem, unfixably.
#
# 5s was safe only while the batch ran ruff and nothing else. The gate now
# dispatches off the linter table, so the batch runs `npx eslint`,
# `golangci-lint run`, `dart analyze` — tools whose COLD START alone (npx bin
# resolution, a TS program build, a package type-check) routinely exceeds 5s on a
# real repo. Budget for a linter that actually works; the CAP still bounds one
# that has genuinely hung.
#
# CEILING, and it is a hard one: the CAP must stay well inside the HARNESS's own
# hook timeout (60s default; pre_tool_bash registers no override). A hook the
# harness kills produces no exit 2 — so overrunning that budget does not fail
# closed, it fails OPEN, and the commit sails through unlinted. That is strictly
# worse than the block we are widening this to avoid. 40s leaves ~20s of headroom
# for the rest of the hook (tier-1 diff scan, git forks, SMM loads). Do NOT raise
# the CAP past that without raising the hook's registered timeout first.
#
# The CAP is a TOTAL, not a per-batch allowance: one commit can run several
# batches (a polyglot repo routes each file to its own linter), and N batches of
# CAP each would breach the ceiling N-fold. staged_lint_gate spends this one
# budget across all of them and passes what is left as `budget_s`; a batch with
# nothing left is UNVERIFIED, which blocks. Bound per-batch alone and the
# ceiling above is only true of a single-language repo.
BATCH_TIMEOUT_BASE_S: float = 30.0
BATCH_TIMEOUT_PER_PATH_S: float = 0.25
BATCH_TIMEOUT_CAP_S: float = 40.0

# Codes deferred until staging. F401 (unused import) / F811 (redef of unused)
# false-positive during multi-Edit migrations — an import added in one Edit and
# consumed in the next fires F401 mid-stream. staged_lint.staged_lint_gate
# catches the real cases at commit time: it blocks on ANY finding the linter
# reports, these two included, so nothing deferred here escapes — it is deferred,
# not excused.
EDIT_DEFERRED_CODES: frozenset[str] = frozenset({"F401", "F811"})

# pyflakes-family code shape (ruff/pylint/flake8): [A-Z]+ + 3-4 digits. Ruff
# plugin namespaces keep growing (F, RUF, PERF, ASYNC, ...) so prefix is unbounded.
_PYFLAKES_CODE_SHAPE = r"[A-Z]+\d{3,4}"

# Per-line code: "path:line:col: F401 [*] message". Used ONLY by run_ruff, the
# edit-time path, where dropping the deferred codes from a report needs to know
# which code each line carries. The commit-time gate deliberately parses
# nothing — see run_linter_batch.
_RUFF_LINE_CODE = re.compile(rf"^\s*[^:\s]+:\d+:\d+:\s+({_PYFLAKES_CODE_SHAPE})\b")


class LintRun(NamedTuple):
    """Outcome of one linter invocation, classified by exit code.

    `status` is the whole contract; `output` is the linter's own text, passed
    through untouched for a human to read. See run_linter_batch.
    """

    status: Literal["clean", "findings", "unverified"]
    output: str


def _eligible_for_linter(linter_name: str, paths: list[str]) -> list[str]:
    """Filter paths the linter handles, order-preserving.

    Skips flag-shaped paths (arg-injection guard) and extensions the linter
    doesn't claim. Shared by run_linter and run_linter_batch — single source
    so the security guard can't drift between callers.

    lang-ok: same LINTER_EXTENSIONS table as detect_linter_config — a linter
    with no entry claims every path (`allowed is None`), so an unlisted language
    is passed through rather than filtered out.
    """
    allowed = LINTER_EXTENSIONS.get(linter_name)
    return [
        p
        for p in paths
        if not p.startswith("-") and (allowed is None or Path(p).suffix in allowed)
    ]


def run_linter(linter_name: str, file_path: str, cwd: str | None = None) -> str | None:
    """Run linter on file. Returns error output, or None if clean/unavailable."""
    binary = LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return None

    if not _eligible_for_linter(linter_name, [file_path]):
        return None

    # "--" separates flags from filename arg
    cmd = [*linter_command(linter_name), "--", file_path]
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


def run_ruff(file_path: str | Path, *, cwd: str | None = None) -> tuple[list[str], str]:
    """Run ruff on one file at EDIT time; return (codes, filtered_text).

    Strips EDIT_DEFERRED_CODES (F401/F811): mid-edit they false-positive, so
    they are deferred to the commit-time gate rather than raised as a concern
    here. Returns ([], "") when ruff is unavailable, the extension is wrong, or
    the run is clean.

    Edit-time only — this is the one place a ruff *code* is still read out of
    ruff's text, and it stays here. The commit-time gate (run_linter_batch)
    classifies by exit code and parses nothing, because it has to work for every
    language the plugin ships to. Nothing calls this at staging time: a staging
    variant would have to re-derive the codes the gate deliberately ignores.
    """
    raw = run_linter("ruff", str(file_path), cwd=cwd)
    if raw is None:
        return ([], "")

    kept_lines: list[str] = []
    codes: list[str] = []
    deferred = EDIT_DEFERRED_CODES
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
    cwd: str | None = None,
    budget_s: float | None = None,
) -> LintRun:
    """Run a linter once over many paths; classify the run by its EXIT CODE.

    The commit-time gate needs to know *that* the linter found something, not
    *what* — so this reports the linter's own output verbatim and never parses
    it. Reading findings out of the text would take a per-language parser, and
    the plugin ships to projects in every language.

    That is not a stylistic preference; the parser WAS the bug. This function
    used to return {path: codes} scraped with a ruff-shaped regex, pre-filling
    every path with [] before parsing — so a linter whose output that regex
    could not read (eslint, clippy, golangci-lint: everything but ruff) parsed
    to zero findings and read back as unanimously clean.

    The exit code is the discriminator, in both directions:

      * exit 0                   → CLEAN. A clean ruff run prints "All checks
        passed!", which parses to nothing — so "nothing to read" MUST mean
        clean here, or the gate would refuse every green commit.
      * non-zero, with output    → FINDINGS. Caller blocks and shows `output`.
      * non-zero, nothing to say → UNVERIFIED. It found something it could not
        tell us about: a bad read, not a pass.
      * binary missing / timeout / spawn failure → UNVERIFIED.
      * a path refused by the arg-injection guard → UNVERIFIED. We declined to
        look at it, which is not the same as having nothing to look at.

    Callers MUST fail closed on UNVERIFIED (SMM constraint: gates fail CLOSED
    on a bad read). CLEAN with no eligible paths is not a bad read — there was
    simply nothing for this linter to look at (no path carried an extension
    this linter claims).

    Timeout: min(CAP, BATCH_BASE + PER_PATH * N) — sized for a real linter's
    cold start (this budget BLOCKS when it runs out, unlike the edit-time one),
    still bounded so a hung linter can't stall a 100-file commit forever.

    `budget_s` narrows that further to the wall clock the CALLER has left. One
    commit can run several batches (a polyglot repo routes each file to its own
    linter), and the CAP bounds only ONE of them — so without a shared budget,
    two hung linters outlive the harness's hook timeout, the harness kills the
    hook, and a killed hook exits no 2: the commit is not blocked, it is waved
    through unlinted. A spent budget is UNVERIFIED, not clean; the caller fails
    closed on it, like any other bad read. See staged_lint.staged_lint_gate.
    """
    binary = LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return LintRun("unverified", f"{linter_name}: `{binary}` is not on PATH")

    # A path the arg-injection guard refuses is one we DECLINED to check, which
    # is not the same as one there was nothing to check in. Silently dropping it
    # and reporting the rest as clean is a fail-open — an unlinted file ships.
    refused = [p for p in paths if p.startswith("-")]
    if refused:
        return LintRun(
            "unverified",
            f"{linter_name}: refused flag-shaped path(s): {', '.join(refused)}",
        )

    eligible = _eligible_for_linter(linter_name, paths)
    if not eligible:
        return LintRun("clean", "")

    cmd = [*linter_command(linter_name), "--", *eligible]
    timeout = min(
        BATCH_TIMEOUT_CAP_S,
        BATCH_TIMEOUT_BASE_S + BATCH_TIMEOUT_PER_PATH_S * len(eligible),
    )
    if budget_s is not None:
        timeout = min(timeout, budget_s)
        if timeout <= 0:
            return LintRun(
                "unverified",
                f"{linter_name}: the commit gate's "
                f"{BATCH_TIMEOUT_CAP_S:g}s lint budget was spent by earlier "
                f"linters — this one never ran",
            )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return LintRun("unverified", f"{linter_name}: timed out after {timeout:g}s")
    except (OSError, FileNotFoundError) as e:
        return LintRun("unverified", f"{linter_name}: failed to run ({e})")

    if proc.returncode == 0:
        return LintRun("clean", "")

    output = (proc.stdout or proc.stderr or "").strip()
    if not output:
        return LintRun(
            "unverified",
            f"{linter_name}: exited {proc.returncode} without saying why",
        )
    return LintRun("findings", output)


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
        lint_output = run_linter(linter_name, file_arg, cwd=lint_cwd) or ""
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

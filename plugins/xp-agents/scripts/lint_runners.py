#!/usr/bin/env python3
"""Linter-invocation primitives: run a linter on one file or a batch of files.

Split out of lint_check.py (which grew past the 500-line cap) as a pure move —
every symbol here keeps its identity; lint_check re-exports them so existing
callers (staged_lint.py, lint_resolution.py, tests) that reach them as
`lint_check.X` keep working unchanged.
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal, NamedTuple

import linters
from linters import LINTER_BINARIES, LINTER_EXTENSIONS

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
    doesn't claim. Shared by every runner — single source so the security guard
    can't drift between callers.

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


def run_linter(
    linter_name: str,
    file_path: str,
    cwd: str | None = None,
    *,
    root: str | None = None,
    config_path: str | None = None,
) -> str | None:
    """Run linter on file. Returns error output, or None if clean/unavailable.

    Routes through `linters.linter_argv` — the SAME builder the commit gate uses.
    They used to place the `--` separately, and that duplication is where clang-tidy's
    broken invocation hid: the commit path was patched around it by degrading the row,
    while this path went on building `clang-tidy -- app.c` and linting nothing.

    A None argv means "must not run here" (an unmet precondition — e.g. clang-tidy in
    a project with no compile database). That is NOT a clean result, but at edit time
    it is reported the same way, because the alternative is raising a concern that
    `lint_resolution` can never clear: `'hdr.h' file not found` is not fixable by
    editing the file the concern is attached to.
    """
    binary = LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return None

    if not _eligible_for_linter(linter_name, [file_path]):
        return None

    # base=cwd: paths resolve where the linter RUNS, not at root. See linter_invocation.
    base = cwd or root or "."
    cmd = linters.linter_argv(
        linter_name, [file_path], root=root or base, config_path=config_path, base=base
    )
    if cmd is None:
        return None
    try:
        result = _run_with_optional_flag_retry(
            cmd,
            config_path,
            lambda argv: subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=LINTER_BASE_TIMEOUT_S,
                cwd=cwd,
            ),
        )
        if result.returncode != 0:
            output = result.stdout or result.stderr
            return output.strip() if output else "Lint errors detected"
    except subprocess.TimeoutExpired:
        return None
    except (OSError, FileNotFoundError):
        return None

    return None


def _run_with_optional_flag_retry(cmd, config_path, run):
    """Run `cmd` via `run`, retrying once without this row's OPTIONAL flags.

    The config-style flags are the only optional part of a composed argv. A tool
    older than the version that introduced one rejects it as an unrecognised
    option — non-zero WITH output, which every caller below reads as FINDINGS, so
    the committer gets an unfixable block naming a flag they never wrote.

    Only the row's declared usage-error exit code earns the retry: MEASURED (eslint
    8.57.1) findings exit 1 and an unsupported flag exits 2, so an ordinary lint
    failure never pays for a second process. See CONFIG_STYLE_FLAGS.
    """
    result = run(cmd)
    retry_cmd = linters.optional_flag_retry(cmd, config_path, result.returncode)
    return run(retry_cmd) if retry_cmd is not None else result


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
    # Resolve run_linter via lint_check's namespace (deferred import avoids the
    # lint_check<->lint_runners cycle) so ~7 test files that do
    # mock.patch("lint_check.run_linter") still intercept this call after the
    # split. Normally lint_check.run_linter IS lint_runners.run_linter (identity
    # re-export), so behavior is unchanged.
    import lint_check

    raw = lint_check.run_linter("ruff", str(file_path), cwd=cwd)
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
    root: str | None = None,
    config_path: str | None = None,
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

    # ONE argv builder, shared with the edit-time path. It also places the paths:
    # clang-tidy takes them BEFORE the separator (everything after `--` is compiler
    # flags), so the old universal `[*cmd, "--", *paths]` handed it zero sources.
    # `base=cwd` for the same reason as run_linter: see linter_invocation.
    base = cwd or root or "."
    cmd = linters.linter_argv(
        linter_name,
        eligible,
        root=root or base,
        config_path=config_path,
        base=base,
    )
    if cmd is None:
        # "Must not run here" — an unmet precondition, or a config-required linter
        # with no config. Not a clean result: we declined to look, and declining to
        # look is a bad read, which fails CLOSED.
        return LintRun(
            "unverified",
            f"{linter_name}: cannot be invoked in this project "
            f"(missing compile database or config) — refusing to report it clean",
        )
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
        proc = _run_with_optional_flag_retry(
            cmd,
            config_path,
            lambda argv: subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            ),
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


def run_linter_stdin(
    linter_name: str,
    path: str,
    blob: bytes,
    *,
    cwd: str | None = None,
    budget_s: float | None = None,
    root: str | None = None,
    config_path: str | None = None,
) -> LintRun:
    """Lint `blob` as if it were the file at `path`; classify by EXIT CODE.

    The commit gate's slow path, for a file whose staged bytes are not the bytes on
    disk. Same contract as `run_linter_batch` — that/what, exit code only, output
    verbatim, callers fail closed on unverified — and it differs in exactly two ways:
    one file per invocation (stdin carries one), and it runs in BINARY mode.

    Binary is not a detail. `staged_blob_bytes` returns raw bytes on purpose (a blob
    may not be UTF-8), and bytes cannot be `input=` to a text-mode process — it raises
    TypeError, which in a PreToolUse hook is an unhandled traceback: exit 1, which the
    harness reads as NON-blocking, and the commit lands unlinted. So the pipe stays
    binary and the linter's own output is decoded here, leniently: it echoes the source
    line it flagged, so its bytes are no more guaranteed to be UTF-8 than the blob's,
    and a findings report must survive a bad byte rather than raise on it.

    Kept local to this path deliberately. `run_linter_batch` passes no stdin and its
    ~25 text-mode patch sites all assume str, so switching it would be a wide change
    bought for nothing.
    """
    binary = LINTER_BINARIES.get(linter_name)
    if not binary or not shutil.which(binary):
        return LintRun("unverified", f"{linter_name}: `{binary}` is not on PATH")

    # Same arg-injection guard as the batch path: a flag-shaped path is one we
    # DECLINED to check, which is not one there was nothing to check in.
    if path.startswith("-"):
        return LintRun("unverified", f"{linter_name}: refused flag-shaped path: {path}")
    if not _eligible_for_linter(linter_name, [path]):
        return LintRun("clean", "")

    base = cwd or root or "."
    cmd = linters.linter_stdin_argv(
        linter_name, path, root=root or base, config_path=config_path, base=base
    )
    if cmd is None:
        return LintRun(
            "unverified",
            f"{linter_name}: cannot be fed source on stdin in this project "
            f"— refusing to report it clean",
        )

    timeout = min(BATCH_TIMEOUT_CAP_S, BATCH_TIMEOUT_BASE_S + BATCH_TIMEOUT_PER_PATH_S)
    if budget_s is not None:
        timeout = min(timeout, budget_s)
        if timeout <= 0:
            # Says what to DO about it, because unusually there IS something.
            # A spent budget normally names a cause the committer cannot act on
            # (nobody can make golangci-lint faster). This one they can: the file
            # is only on this per-file path because its staged bytes differ from
            # the file on disk. Re-stage it and it stops differing, which routes
            # it back through the batched path — N files, one process. An
            # unfixable gate gets switched off; a fixable one gets fixed.
            return LintRun(
                "unverified",
                f"{linter_name}: the commit gate's {BATCH_TIMEOUT_CAP_S:g}s lint "
                f"budget was already spent when {path} came up — it was never "
                f"linted. Its staged bytes differ from the working tree, which "
                f"is why it costs a process of its own; `git add {path}` (if the "
                f"working-tree copy is what you meant to commit) lets it lint in "
                f"the shared batch instead",
            )
    try:
        proc = _run_with_optional_flag_retry(
            cmd,
            config_path,
            lambda argv: subprocess.run(
                argv,
                capture_output=True,
                input=blob,
                timeout=timeout,
                cwd=cwd,
            ),
        )
    except subprocess.TimeoutExpired:
        return LintRun("unverified", f"{linter_name}: timed out after {timeout:g}s")
    except (OSError, FileNotFoundError) as e:
        return LintRun("unverified", f"{linter_name}: failed to run ({e})")

    if proc.returncode == 0:
        return LintRun("clean", "")

    raw = proc.stdout or proc.stderr or b""
    output = raw.decode("utf-8", errors="replace").strip()
    if not output:
        return LintRun(
            "unverified", f"{linter_name}: exited {proc.returncode} without saying why"
        )
    return LintRun("findings", output)

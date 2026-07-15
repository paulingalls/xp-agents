#!/usr/bin/env python3
"""The commit-time lint gate: unresolved lint blocks the commit, in ANY language.

Lifted out of `pre_tool_bash` at the commit that pushed that file over the
500-line cap. It is a cohesive unit in its own right: everything here answers one
question -- may this commit proceed, given what the project's own linters say
about the files it stages?

The language-specific knowledge lives in `linters` (a table row per linter) and
the running of them in `lint_check`. This module only decides what to DO with the
answer, and that decision is deliberately language-blind: it reads an exit code,
never the linter's words.
"""

import contextlib
import os
import sys
import tempfile
import time
from pathlib import Path
from subprocess import run as _git_run

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import lint_check
import linters
import worktree

# The git-index reads below run through a binding captured at import, NOT
# `subprocess.run` looked up live. Reading the index (membership + staged bytes)
# is infrastructure the LINTER invocation sits on top of, and lint tests mock the
# linter by patching `lint_check.subprocess.run` — which, because `subprocess` is
# one shared module object, would otherwise also intercept these git calls and
# make a mocked linter silently mock the index. Tests that mean to control the
# index patch `path_in_index` / `staged_blob_bytes` instead.


def path_in_index(root: str, path: str) -> bool:
    """True if *path* has a blob staged in the index (`git cat-file -e :<path>`).

    Index membership — not working-tree existence — is what separates a file we
    must lint (its staged blob is what the commit carries) from a staged
    DELETION (`:<path>` resolves to nothing → skip). The two diverge exactly
    where `.exists()` gets it wrong: a staged-new-then-worktree-deleted file is
    in the index but off disk; a staged deletion is on disk (still tracked at
    HEAD, dirty) but gone from the index. `git cat-file -e` is a probe, not a
    `--name-only` listing, so it does not breach the single-`--name-only`
    invariant (test_common_path_at_most_one_name_only_call).
    """
    proc = _git_run(
        ["git", "cat-file", "-e", f":{path}"], cwd=root, capture_output=True
    )
    return proc.returncode == 0


def staged_blob_bytes(root: str, path: str) -> bytes | None:
    """The staged bytes of *path* (`git show :<path>`), or None on a bad read.

    Raw bytes, no text decode: a blob may be non-UTF-8, and the linter reads it
    off disk as bytes anyway. None means we could not read a blob the index says
    is there — the caller fails closed on that, never silently skips it.
    """
    proc = _git_run(["git", "show", f":{path}"], cwd=root, capture_output=True)
    if proc.returncode != 0:
        return None
    return proc.stdout


def _cleanup_temps(temp_paths: list[str]) -> None:
    """Remove materialized temp siblings; a crash must not strand them in the repo."""
    for tp in temp_paths:
        with contextlib.suppress(OSError):
            os.unlink(tp)


def _materialize_staged(root: str, paths: list[str]) -> tuple[list[str], str | None]:
    """Write each staged blob to an in-dir temp sibling; return (temp_paths, error).

    For each in-index path, the staged bytes are written to a temp file in the
    file's OWN directory, prefixed with its stem and carrying its EXACT
    extension (`app.py` → `app.tmpXXXX.py`). Same dir + same suffix is required,
    not cosmetic: detect_linter_config walks up from the file's directory keyed
    on its suffix, and eslint/ruff resolve their config + node_modules by
    walking up from cwd — a temp elsewhere would resolve neither.

    KNOWN LIMIT (strictly narrower than the fail-open it replaces): the temp has
    a different NAME than the original, so a linter selecting by exact full
    filename, or one that `force-exclude`s a non-matching name, could skip it.
    The stem prefix + exact suffix keep every extension- and stem-glob matching;
    only an exact-full-name selector (rare) misses. That residual is a missed
    finding on an unusual config; the bug being fixed was a missed finding on
    ordinary partial-add, in any language.

    error is non-None on the FIRST bad read (blob unreadable, or the temp write
    failed) — the caller fails closed. Partial temps are removed before
    returning so a failure strands nothing.
    """
    temp_paths: list[str] = []
    for path in paths:
        blob = staged_blob_bytes(root, path)
        if blob is None:
            _cleanup_temps(temp_paths)
            return [], f"could not read staged blob for {path}"
        abs_path = Path(root) / path
        try:
            fd, tmp = tempfile.mkstemp(
                dir=str(abs_path.parent),
                prefix=f"{abs_path.stem}.",
                suffix=abs_path.suffix,
            )
            try:
                os.write(fd, blob)
            finally:
                os.close(fd)
        except OSError as e:
            _cleanup_temps(temp_paths)
            return [], f"could not materialize staged {path} ({e})"
        temp_paths.append(tmp)
    return temp_paths, None


def _relabel_temps(output: str, originals: list[str], temp_paths: list[str]) -> str:
    """Rewrite the temp siblings' names back to the staged files' real names.

    The linter is pointed at a randomly-named temp sibling, so its output names
    that temp (`app.c3_cjzvr.py:1: ...`) — a path that does not exist and is
    already unlinked by the time the block message reaches the agent, whom we
    then tell to "fix the findings". Each temp basename is a unique mkstemp
    string, so a plain basename substitution restores the real name without
    touching anything else, in any language and whatever path format (relative
    or absolute) the linter prints. Any directory prefix the linter emitted is
    preserved — only the basename is swapped.
    """
    for orig, tmp in zip(originals, temp_paths, strict=True):
        output = output.replace(Path(tmp).name, Path(orig).name)
    return output


def _group_staged_by_linter(
    staged_files: list[str], root: str
) -> dict[tuple[str, str], list[str]]:
    """Group staged paths by the (linter, config) that claims them.

    lang-ok: the routing is a TABLE LOOKUP, not a language test. Each staged file
    is handed to detect_linter_config, which walks up from it for any ecosystem's
    config file and answers off the `linters` tables. A TypeScript repo finds
    eslint, a Go repo finds golangci-lint, a Python repo finds ruff — the same
    code path, no branch per language. Supporting one more language is a ROW in
    linters.py. A file whose ecosystem has no configured linter finds nothing and
    is skipped: a missing linter is not a finding.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for path in staged_files:
        # Lint only what the commit CARRIES. A staged DELETION still names its
        # path, and a linter handed a path with no staged blob reports a read
        # error and exits non-zero — which the exit-code contract reads as a
        # FINDING, blocking the very commit that removes the file, with nothing
        # the agent could fix. The predicate is INDEX membership, not
        # working-tree existence: once the gate lints the staged blob (below),
        # `.exists()` is the wrong test — a staged-new-then-worktree-deleted
        # file is in the index but off disk, and a staged deletion is on disk
        # but gone from the index. Index membership is a byte-level git fact,
        # true in every language.
        if not path_in_index(root, path):
            continue
        config = lint_check.detect_linter_config(root, root, file_path=path)
        if config is None:
            continue
        groups.setdefault(config, []).append(path)
    return groups


def staged_lint_gate(staged_files: list[str], cwd: str) -> list[str]:
    """Commit-time lint gate, in ANY language: unresolved lint blocks the commit.

    Detect each staged file's linter from its ecosystem's own config file, run
    it, and block on what it found — reporting the linter's OWN output and never
    interpreting it. Knowing *that* a linter found something needs only its exit
    code; knowing *what* it found would need a per-language parser, and the
    plugin ships to projects in every language. This is why there is no rule-code
    table here, and why there must never be one.

    Four outcomes, and the middle two are DIFFERENT — do not merge them:

      * no linter config for the file's ecosystem → SKIP. A missing linter is
        not a finding.
      * the linter is project-scoped (clippy et al.) → DEGRADE. It exits non-zero
        for whole-project state the staged diff neither caused nor can fix;
        blocking on that blocks every commit in the repo, unfixably. Returned as
        an advisory, not silence.
      * config present but the linter could not RUN (binary missing, timeout, a
        non-zero exit with nothing to say, or no wall clock left in the shared
        budget) → FAIL CLOSED, block. The project declares it lints; we simply
        could not check. A bad read is not a pass.
      * the linter ran and found something → BLOCK, showing its output.

    Returns advisories (degraded groups) for the caller to surface. Raises
    BlockedError on findings or a bad read. ``staged_files`` is reused from the
    caller to avoid a second `git diff --cached --name-only` invocation
    (invariant: `test_common_path_at_most_one_name_only_call`).

    The bytes checked are the INDEX's, not the working tree's: each staged blob
    is materialized to an in-dir temp sibling (`_materialize_staged`) and the
    linter is pointed at THAT, so a partial-add or an edit-after-add is judged on
    the content the commit actually carries, in both directions. A blob the index
    says is there but we cannot read fails CLOSED (unverified), never a silent
    skip. Residual known-limit: a linter selecting by exact full filename could
    skip the renamed temp — see `_materialize_staged`; strictly narrower than the
    fail-open it replaced.
    """
    # git names staged paths relative to the REPO ROOT, so resolve them there —
    # not against the hook's cwd, which is a subdirectory whenever the agent
    # committed from one.
    root = worktree.resolve_git_root(cwd) or cwd

    advisories: list[str] = []
    findings: list[str] = []
    unverified: list[str] = []

    # ONE budget, spent across every group — not one per group. A polyglot repo
    # routes each staged file to its own linter, so this loop can run several
    # batches, and run_linter_batch's CAP bounds only ONE of them. Two hung
    # linters would therefore outlive the HARNESS's hook timeout, and a hook the
    # harness kills exits no 2 — it does not block, it waves the commit through
    # UNLINTED. Which is why the budget is enforced here, where the batches are
    # counted, and not only where each one is run: the ceiling that keeps this
    # gate failing closed is a property of the whole hook, not of one linter.
    deadline = time.monotonic() + lint_check.BATCH_TIMEOUT_CAP_S

    for (linter_name, config_path), paths in sorted(
        _group_staged_by_linter(staged_files, root).items()
    ):
        # The REAL reason, per row — not one blanket sentence for every degraded
        # linter. The old message told C/C++ users clang-tidy "lints the whole
        # project, not one file", which is false, and linters.py knew it was false.
        reason = linters.degrade_reason(linter_name, root, paths)
        if reason is not None:
            advisories.append(
                f"Commit-time lint skipped for {len(paths)} staged file(s): "
                f"{linter_name} — {reason}. Run it yourself before pushing."
            )
            continue

        # Lint the STAGED bytes, not the working-tree copy: materialize each
        # staged blob to an in-dir temp sibling and point the linter at that. A
        # bad materialize on a file the index says is present is a bad read →
        # unverified → block; NEVER a silent skip.
        temp_paths, error = _materialize_staged(root, paths)
        if error is not None:
            unverified.append(f"{linter_name}: {error} — refusing to report it clean")
            continue
        try:
            # Run FROM the config file's directory, with paths relative to it: in
            # a monorepo the binary lives in that subpackage (`npx eslint`
            # resolves it by walking up from cwd) and eslint v9 resolves its flat
            # config relative to cwd. lint_invocation_target owns BOTH halves of
            # that convention, and we take both from it rather than re-deriving
            # the cwd here: each file arg is a path relative to the cwd THAT call
            # chose. The temp sits in the same dir with the same extension as its
            # source, so the config it resolves is the group's config_path.
            targets = [
                lint_check.lint_invocation_target(config_path, root, tp)
                for tp in temp_paths
            ]
            lint_cwd = targets[0][0]  # constant per group: same config, same dir
            args = [file_arg for _, file_arg in targets]
            run = lint_check.run_linter_batch(
                linter_name,
                args,
                cwd=lint_cwd,
                budget_s=deadline - time.monotonic(),
                root=root,
                config_path=config_path,
            )
        finally:
            _cleanup_temps(temp_paths)
        # The linter named the temp siblings; the agent must see its real files.
        run_output = _relabel_temps(run.output, paths, temp_paths)
        match run.status:
            case "findings":
                findings.append(f"{linter_name}:\n{run_output}")
            case "unverified":
                unverified.append(run_output)

    if findings or unverified:
        lines = ["Staged lint check blocked this commit:", ""]
        lines += findings
        if unverified:
            lines += [
                "Could not verify (a configured linter that cannot run is a bad "
                "read, not a pass):",
                *(f"  {u}" for u in unverified),
            ]
        lines += ["", "Fix the findings, or unstage the file."]
        raise _common.BlockedError(
            "\n".join(lines),
            "Lint findings or an unverifiable linter on staged files.",
        )

    return advisories

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
import shutil
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
    """Remove each materialized file's temp SUBDIR; a crash must strand nothing.

    Each staged blob is written to `<uniquetmpdir>/<original_basename>`, so the
    thing to remove is the whole `<uniquetmpdir>` — a directory mkdtemp created
    for us and nothing else lives in.
    """
    for tp in temp_paths:
        with contextlib.suppress(OSError):
            shutil.rmtree(Path(tp).parent)


def _cleanup_created_dirs(created_dirs: list[str]) -> None:
    """Remove parent dirs we had to create to materialize a staged-new file.

    A staged-new `newdir/foo.py` whose `newdir/` is gone from the working tree
    (the index still carries the blob) is materialized under a freshly-created
    `newdir/` — which must be removed again so the working tree is left exactly
    as it was. `rmdir` only removes an EMPTY dir, so this can never delete real
    content; deepest-first so nested creations unwind cleanly.
    """
    for d in sorted(set(created_dirs), key=lambda p: p.count(os.sep), reverse=True):
        with contextlib.suppress(OSError):
            os.rmdir(d)


def _missing_ancestors(parent: Path) -> list[str]:
    """The dirs in `parent`'s chain that do not yet exist, deepest-first.

    These are exactly the dirs `os.makedirs(parent)` will create — recorded so
    cleanup removes only what we created, never a dir that was already there.
    """
    missing: list[str] = []
    p = parent
    while not p.exists():
        missing.append(str(p))
        if p.parent == p:  # reached the filesystem root
            break
        p = p.parent
    return missing


def _materialize_staged(
    root: str, paths: list[str]
) -> tuple[list[str], list[str], str | None]:
    """Materialize each staged blob; return (temp_paths, created_dirs, error).

    For each in-index path, the staged bytes are written to a UNIQUE temp SUBDIR
    inside the file's own directory, under the file's EXACT original basename
    (`pkg/app.py` → `pkg/tmpXXXX/app.py`). Two properties, both load-bearing:

      * exact basename: a linter rule keyed on the full filename (ruff
        `per-file-ignores`, eslint filename globs, the `__init__.py` /
        `conftest.py` special-cases) matches the materialized file, so a
        legitimate commit is not FALSE-POSITIVE blocked. A random temp name
        would defeat those rules — the inverse of the fail-open this replaces.
      * temp is INSIDE the real parent: detect_linter_config and eslint/ruff
        resolve config + node_modules by walking UP from the file, so the temp
        subdir walks `<tmpXXXX>/ → <parent>/ → …` and resolves the SAME config,
        one transparent extra hop. A temp elsewhere would resolve neither.

    A staged-new file whose parent dir is gone from the working tree (index
    still has the blob) has that dir recreated (`os.makedirs`); the dirs created
    are returned in created_dirs so the caller removes them again, leaving the
    working tree as it was. If a path component is a file (makedirs can't
    resolve), that OSError falls through to the fail-closed block below — the
    honest outcome for a genuinely broken path.

    error is non-None on the FIRST bad read (blob unreadable, or the temp write
    failed) — the caller fails closed. Partial temps and created dirs are
    removed before returning so a failure strands nothing.
    """
    temp_paths: list[str] = []
    created_dirs: list[str] = []

    def _fail(msg: str) -> tuple[list[str], list[str], str]:
        _cleanup_temps(temp_paths)
        _cleanup_created_dirs(created_dirs)
        return [], [], msg

    for path in paths:
        blob = staged_blob_bytes(root, path)
        if blob is None:
            return _fail(f"could not read staged blob for {path}")
        abs_path = Path(root) / path
        parent = abs_path.parent
        try:
            new_dirs = _missing_ancestors(parent)
            os.makedirs(parent, exist_ok=True)
            created_dirs.extend(new_dirs)
            tmp_dir = tempfile.mkdtemp(dir=str(parent))
            tmp = str(Path(tmp_dir) / abs_path.name)
            with open(tmp, "wb") as fh:
                fh.write(blob)
        except OSError as e:
            return _fail(f"could not materialize staged {path} ({e})")
        temp_paths.append(tmp)
    return temp_paths, created_dirs, None


def _relabel_temps(output: str, temp_paths: list[str]) -> str:
    """Rewrite the temp-subdir paths back to the staged files' real paths.

    The linter is pointed at `<parent>/<tmpXXXX>/<basename>`, so its output names
    a path with a `<tmpXXXX>/` segment that does not exist in the real tree and
    is already removed by the time the block message reaches the agent, whom we
    then tell to "fix the findings". The basename is now IDENTICAL to the real
    file, so only the injected temp-subdir segment must be stripped: each subdir
    name is a unique mkdtemp string, so dropping `<tmpXXXX>/` collapses the path
    back to the real one without touching anything else, in any language and
    whatever path format (relative or absolute) the linter printed.
    """
    for tmp in temp_paths:
        tmp_seg = Path(tmp).parent.name
        output = output.replace(f"{tmp_seg}/", "")
        if os.sep != "/":
            output = output.replace(f"{tmp_seg}{os.sep}", "")
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
    is materialized under its EXACT basename in a temp subdir of its own
    directory (`_materialize_staged`) and the linter is pointed at THAT, so a
    partial-add or an edit-after-add is judged on the content the commit actually
    carries, in both directions — and a filename-keyed linter rule
    (per-file-ignores, `__init__.py` special-cases) still matches. A blob the
    index says is there but we cannot read fails CLOSED (unverified), never a
    silent skip.
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
        temp_paths, created_dirs, error = _materialize_staged(root, paths)
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
            # The REAL staged paths, relative to the SAME lint_cwd, aligned 1:1
            # with `args`. A precondition (clang-tidy compile-DB directory
            # coverage) is a fact about the real file, not its temp copy: the temp
            # sits in a subdir of the covered directory and would read as
            # uncovered, degrading a file the DB covers perfectly well. paths and
            # temp_paths share order (built together in _materialize_staged).
            precondition_args = [
                lint_check.lint_invocation_target(
                    config_path, root, str(Path(root) / p)
                )[1]
                for p in paths
            ]
            run = lint_check.run_linter_batch(
                linter_name,
                args,
                cwd=lint_cwd,
                budget_s=deadline - time.monotonic(),
                root=root,
                config_path=config_path,
                precondition_paths=precondition_args,
            )
        finally:
            _cleanup_temps(temp_paths)
            _cleanup_created_dirs(created_dirs)
        # The linter named the temp subdirs; the agent must see its real files.
        run_output = _relabel_temps(run.output, temp_paths)
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

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

import sys
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


def _divergent_from_index(root: str, paths: list[str]) -> set[str]:
    """Which of `paths` hold different bytes in the working tree than in the index.

    ONE `git diff --name-only` over the whole staged set — git names exactly the
    divergent files, and a per-path `git diff --quiet` would cost one process per
    staged file (50 spawns on a 50-file commit), which is the process cost the
    in-place branch exists to avoid.

    git's answer, never a byte comparison of our own. The index stores the file
    as git will commit it, and a clean/smudge filter or an eol/CRLF setting makes
    that legitimately differ from the bytes on disk — raw bytes would read those
    files as divergent and quietly send every one of them down the slow path. git
    applies the same filters it committed them through; it is the only thing that
    can answer this correctly.

    A git read we could not make is answered "divergent" for every path: that is
    the direction that stays CORRECT (the staged bytes are linted either way), it
    only costs speed. Answering "identical" on a failed read would lint the
    working tree on a guess, which is the fail-open this gate exists to close.
    """
    if not paths:
        return set()
    proc = _git_run(
        # -z: git C-quotes paths with non-ASCII or unusual bytes in its default
        # output, so a plain --name-only would hand back a QUOTED path that
        # matches nothing in `paths` — reading an ordinary file as identical.
        ["git", "diff", "--name-only", "-z", "--", *paths],
        cwd=root,
        capture_output=True,
    )
    if proc.returncode != 0:
        return set(paths)
    named = proc.stdout.decode("utf-8", errors="replace").split("\0")
    return {p for p in named if p}


def _record(
    run: lint_check.LintRun,
    linter_name: str,
    findings: list[str],
    unverified: list[str],
) -> None:
    """File one run's outcome under what the caller must DO about it.

    Shared by both branches so they cannot drift: a clean run is silence, findings
    block and show the linter's own words, and an unverified run blocks too — we
    could not read it, and a bad read is not a pass. Which branch produced the run
    is not part of that decision.
    """
    match run.status:
        case "findings":
            findings.append(f"{linter_name}:\n{run.output}")
        case "unverified":
            unverified.append(run.output)


def _lint_in_place(
    linter_name: str,
    config_path: str,
    root: str,
    paths: list[str],
    budget_s: float,
) -> lint_check.LintRun:
    """Lint `paths` where they LIVE — for files the index and tree agree on.

    Linting the real path IS linting the index when the two are identical, so
    this trades away nothing: the bytes the linter reads are the bytes the commit
    carries. What it buys is the two properties no copy can hold at once — the
    exact basename (filename-keyed rules match) AND the exact depth (`./util`,
    `../lib/x` resolve to the same files the source meant) — plus the batching: N
    paths, one process.

    The paths are real, so a precondition (clang-tidy's compile-DB coverage) is
    judged on the file it is a fact about, with nothing to thread through.
    """
    targets = [
        lint_check.lint_invocation_target(config_path, root, str(Path(root) / p))
        for p in paths
    ]
    lint_cwd = targets[0][0]  # constant per group: same config, same dir
    return lint_check.run_linter_batch(
        linter_name,
        [file_arg for _, file_arg in targets],
        cwd=lint_cwd,
        budget_s=budget_s,
        root=root,
        config_path=config_path,
    )


def _lint_staged_bytes(
    linter_name: str,
    config_path: str,
    root: str,
    path: str,
    deadline: float,
) -> lint_check.LintRun:
    """Lint the INDEX's bytes for `path`, which are not the bytes on disk.

    `git show :<path>` piped to the linter, which is told the real path they belong
    to — so the file is judged where it lives without a copy existing anywhere. This
    is the case the gate needs most (a partial add, an edit-after-add: exactly the
    fail-open it was built to close) and the case a copy served worst.

    A blob the index says is there but we cannot read is a bad read → unverified →
    the caller blocks. Never a silent skip.
    """
    blob = staged_blob_bytes(root, path)
    if blob is None:
        return lint_check.LintRun(
            "unverified",
            f"{linter_name}: could not read staged blob for {path} "
            f"— refusing to report it clean",
        )
    lint_cwd, file_arg = lint_check.lint_invocation_target(
        config_path, root, str(Path(root) / path)
    )
    return lint_check.run_linter_stdin(
        linter_name,
        file_arg,
        blob,
        cwd=lint_cwd,
        budget_s=deadline - time.monotonic(),
        root=root,
        config_path=config_path,
    )


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

    The bytes checked are the INDEX's, not the working tree's — so a partial-add
    or an edit-after-add is judged on what the commit actually carries, in both
    directions. Nothing is ever COPIED to achieve that, and the copies are what
    the previous two attempts each broke something on: a linter must see the file
    at its exact basename (filename-keyed rules: per-file-ignores, `__init__.py`
    special-cases) AND at its exact depth (`./util`, `../lib/x`, any path-keyed
    config rule), and no copy holds both. Only the real path does. So:

      * index == working tree (~99% of commits) → lint the real path, batched.
        Linting the real path IS linting the index when they are identical, and
        this cannot reintroduce the fail-open, which requires them to differ.
      * they diverge → pipe `git show :<path>` to the linter and TELL it the real
        path (`_lint_staged_bytes`). Per-file, but divergence is rare.
      * they diverge and the linter reads no stdin → BLOCK, naming the remedy
        (`git add` the path). Unreadable is not clean, and this one IS
        satisfiable — unlike a degraded linter, which is why they differ.

    A blob the index says is there but we cannot read fails CLOSED (unverified),
    never a silent skip.
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

    # ONE git read for the whole commit, before the per-linter loop — asked here
    # rather than per group so a polyglot commit does not pay for it per linter.
    divergent = _divergent_from_index(root, staged_files)

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

        # The file on disk IS the staged blob wherever git says the two agree —
        # so lint it there, batched, and let every path-relative resolution the
        # source does resolve exactly as it will at HEAD.
        in_place = [p for p in paths if p not in divergent]
        if in_place:
            _record(
                _lint_in_place(
                    linter_name,
                    config_path,
                    root,
                    in_place,
                    deadline - time.monotonic(),
                ),
                linter_name,
                findings,
                unverified,
            )

        staged_only = [p for p in paths if p in divergent]
        if not staged_only:
            continue

        # The bytes to judge are not on disk, and every place we could put them is
        # the wrong place — so pipe them, and tell the linter the real path. A CLI
        # that reads no stdin leaves nowhere to put them at all: FAIL CLOSED.
        #
        # This branch advised and let the commit through until it was noticed that
        # doing so reopened the exact edit-after-add fail-open the gate exists to
        # close — for every language whose linter takes no stdin at once. The
        # reasoning that licensed it was that blocking here is "a gate nobody can
        # satisfy". It is not: `git add <path>` satisfies it in one command, and
        # for the case that actually produces this state (staged, then edited on
        # disk) re-staging is what the committer meant to do anyway. That is the
        # line against `degrade_reason` above, which stays an advisory precisely
        # because it is NOT satisfiable — a whole-crate clippy failure is not
        # something the staged diff can fix. Unreadable is not clean.
        if linters.LINTER_STDIN_SHAPES.get(linter_name, linters.NO_STDIN) == (
            linters.NO_STDIN
        ):
            unverified.append(
                f"{linter_name}: the staged bytes of {', '.join(staged_only)} "
                f"differ from the working tree, and {linter_name} reads no source "
                f"on stdin — so what the commit carries cannot be judged without "
                f"moving the file, and moving it is what this gate refuses to do. "
                f"`git add` those paths (or unstage them) so the index and the "
                f"working tree agree, then commit."
            )
            continue

        for path in staged_only:
            # Labelled with the PATH, which this branch is the only one that can
            # do — it runs one file per invocation, so it knows. It has to: a
            # linter told the path on stdin is not obliged to REPEAT it, and one
            # does not (MEASURED: prettier 3 `--check --stdin-filepath x.js`
            # prints `(stdin)`). An unlabelled finding is one the agent cannot
            # locate — the same self-obscuring report the temp copies produced,
            # arriving by a different door. Labelling is not reading: the
            # linter's own words still pass through untouched.
            _record(
                _lint_staged_bytes(linter_name, config_path, root, path, deadline),
                f"{linter_name} ({path}, staged bytes)",
                findings,
                unverified,
            )

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

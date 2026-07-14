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

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import lint_check
import linters
import worktree


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
        # Lint only what is actually THERE. A staged DELETION still names its
        # path, and a linter handed a path that is gone reports a read error and
        # exits non-zero — which the exit-code contract reads as a FINDING,
        # blocking the very commit that removes the file, with nothing the agent
        # could fix. (The old parser hid this by accident: it pre-filled every
        # path to [] and the read error's code fell outside its F401/F811
        # allowlist.) Existence is a byte-level fact, true in every language.
        if not (Path(root) / path).exists():
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

    KNOWN LIMIT: git names the staged PATHS, but the linter reads those paths off
    the WORKING TREE, so the bytes checked are the working tree's, not the
    index's. They differ only when the two diverge (`git add -p`, or an edit after
    the add) — and then the gate judges content the commit does not carry, in
    either direction. Linting the index needs the staged blobs materialized
    somewhere a linter can resolve per-file config from, which is a design
    problem, not an oversight. Recorded as an open concern, not hidden.
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
        if not linters.is_file_scoped(linter_name):
            advisories.append(
                f"Commit-time lint skipped for {len(paths)} staged file(s): "
                f"{linter_name} lints the whole project, not one file, so a "
                f"non-zero exit would report state your diff neither caused nor "
                f"can fix. Run it yourself before pushing."
            )
            continue

        # Run FROM the config file's directory, with paths relative to it: in a
        # monorepo the binary lives in that subpackage (`npx eslint` resolves it
        # by walking up from cwd) and eslint v9 resolves its flat config relative
        # to cwd. lint_invocation_target owns BOTH halves of that convention, and
        # we take both from it rather than re-deriving the cwd here: each file arg
        # is a path relative to the cwd THAT call chose, so a cwd we computed
        # ourselves is only coincidentally the same one. Should the derivation
        # ever change there, re-deriving here would not drift loudly — it would
        # resolve every arg against the wrong directory. One source, one cwd.
        targets = [
            lint_check.lint_invocation_target(config_path, root, p) for p in paths
        ]
        lint_cwd = targets[0][0]  # constant per group: same config, same dir
        args = [file_arg for _, file_arg in targets]
        run = lint_check.run_linter_batch(
            linter_name, args, cwd=lint_cwd, budget_s=deadline - time.monotonic()
        )
        match run.status:
            case "findings":
                findings.append(f"{linter_name}:\n{run.output}")
            case "unverified":
                unverified.append(run.output)

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

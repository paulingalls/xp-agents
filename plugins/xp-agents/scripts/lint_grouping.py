#!/usr/bin/env python3
"""Routing staged and post-commit paths alike to the (linter, config) that claims them.

Split out of `staged_lint._group_staged_by_linter`, which fused this routing to a
git-index membership filter. The post-commit sweep must not inherit that filter —
it deliberately resolves lint concerns on working-tree files that are not in the
commit — so the routing lives here, filter-free, and each caller applies its own
eligibility test on top.

lang-ok: the routing is a TABLE LOOKUP, not a language test. Each path is handed
to detect_linter_config, which walks up from it for any ecosystem's config file
and answers off the `linters` tables. A TypeScript repo finds eslint, a Go repo
finds golangci-lint, a Python repo finds ruff — the same code path, no branch per
language. Supporting one more language is a ROW in linters.py. A file whose
ecosystem has no configured linter finds nothing and is skipped: a missing
linter is not a finding.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import lint_check


def group_paths_by_linter(
    paths: list[str], cwd: str, git_root: str
) -> dict[tuple[str, str], list[str]]:
    """Group `paths` by the (linter, config) that claims them.

    Applies NO eligibility filter of any kind — no index check, no
    `.exists()`. Callers filter first (e.g. staged_lint's index membership,
    a post-commit sweep's `.exists()`).
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for path in paths:
        config = lint_check.detect_linter_config(cwd, git_root, file_path=path)
        if config is None:
            continue
        groups.setdefault(config, []).append(path)
    return groups

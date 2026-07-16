#!/usr/bin/env python3
"""Shared test fixtures for git+SMM tests — split shim.

Canonical import surface for hermetic repo setup, sprint/SMM seeding, and
branch/SHA probes. Any test that needs a temporary git repo should import
from here rather than reproduce the boilerplate inline.

Split per convention 91fcf9b8744d when this file crossed 500 lines (debt
db605069040f, which named the three concerns below). Definitions live in:

  * ``_repo_fixtures``   — ``GIT_ENV``, repo init, commits, worktrees, remotes
  * ``_sprint_fixtures`` — sprint.json / execution_plan.json / system_context
  * ``_branch_probes``   — branch + SHA reads and ref manipulation

Import order mirrors the dependency DAG: the two leaves first, then
``_repo_fixtures``, which imports DOWN from ``_branch_probes``. Callers keep
using ``_branching_fixtures.X`` unchanged — every name below is re-exported
BY IDENTITY (``_branching_fixtures.X is _repo_fixtures.X``), which is why the
65 importing test modules needed no edit.

EVERY public name in the three modules belongs in these lists — a partial
shim is how a caller discovers the split the hard way.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _branch_probes import (  # noqa: F401
    branch_exists,
    checkout_main,
    diverge_tracking_ref,
    get_branch_sha,
    get_current_branch,
    get_current_branch_at,
    get_head_sha,
    git_log_oneline_at,
    make_branch,
    remote_has_branch,
)
from _repo_fixtures import (  # noqa: F401
    GIT_ENV,
    add_bare_remote,
    add_pre_push_hook,
    append_commit,
    create_teammate_worktree_with_commit,
    init_repo,
    init_repo_in_spaced_parent,
    init_repo_with_ignored_worktrees,
    make_commit,
    make_conflicted_merge,
    merge_teammate_branch,
    run_accept_env,
)
from _sprint_fixtures import (  # noqa: F401
    open_concern_event,
    seed_plan,
    seed_sprint_with_stories,
    write_sprint_json,
    write_system_context,
)

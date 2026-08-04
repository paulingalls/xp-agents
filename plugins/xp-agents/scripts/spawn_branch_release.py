#!/usr/bin/env python3
"""Check the main checkout off a branch a teammate worktree is about to take.

Extracted from `spawn_teammate.py` when the teardown wiring pushed it past its
500-line cap — the same "sibling leaf module, name kept importable in
spawn_teammate" split `spawn_args`, `spawn_command`, `spawn_prompt` and
`worktree_bootstrap` already took. One cohesive concern, one caller
(`create_worktree`), and the module it left is the one that spawns.

The name is re-imported by `spawn_teammate`, so `create_worktree` reads THAT
module's global and `patch.object(spawn_teammate, "_release_branch_from_main")`
still intercepts. Patching THIS module would rebind a global nothing reads —
the same seam trap `spawn_teammate`'s run_bootstrap comment documents.
"""

import sys
from pathlib import Path

# All three imports below are scripts/-local siblings that bootstrap smm/ onto
# the path themselves, so — unlike spawn_teammate — this module needs no
# `import worktree` side effect and no `isort: split` barrier to protect an
# ordering. Verified by importing this module with ONLY scripts/ on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import branch_lifecycle
import branch_resolution
import identity

__all__ = ["_release_branch_from_main"]


def _release_branch_from_main(cwd: str, branch: str, smm_dir: Path | None) -> None:
    """Check the main checkout away from `branch` so a worktree can take it.

    No-op unless main is ON that exact branch — the recovery is conditional.

    `branching.py create` leaves the main checkout on the branch it just cut, and
    `git worktree add <path> <branch>` then refuses (exit 128) a branch that is
    already checked out elsewhere, killing the spawn before the agent starts.
    The only thing that ever prevented that was a second, hand-written
    `git checkout "$BASE"` in the assign flow, with nothing enforcing it — so the
    precondition lives here instead of in the caller.

    The base is resolved through the SAME ``--required`` resolver the assign flow
    uses, so the two cannot disagree about what "base" means and neither can
    silently degrade to the release branch. With no `smm_dir` there is no honest
    base to resolve, so this SKIPS rather than guessing one: behavior identical
    to before it existed, git's 128 included. Only positional test callers reach
    that leg — ``--smm-dir`` is required and `main` always passes it.

    NEVER `--force`, and never a stash. Uncommitted work in the main checkout
    must STOP the spawn: this is the same philosophy `cleanup_existing` documents
    above — hand the decision to git, which refuses to clobber modified or
    untracked files. The refusal is a RuntimeError naming the branch, the base
    and git's stderr, because the caller needs an actionable reason and
    CalledProcessError carries none of that in its message. It relays git's
    reason rather than ASSERTING one: a blocked checkout is usually a dirty
    tree, but not always, and prescribing "stash it" for a failure that was
    never about local changes sends the operator after the wrong thing.

    Routed through the SAME retry `branch_lifecycle` uses for its checkout, for
    the same reason and in a strictly worse spot: this one runs immediately
    before a `git worktree add`, i.e. in the middle of a fan-out where sibling
    spawns are mutating the worktree registry and taking the index concurrently.
    Both retried signatures (`index.lock`, a transient "already used by
    worktree" registry misread) are live here, and either one would otherwise
    surface as the refusal above — telling the operator to commit work that is
    not there while the spawn dies.
    """
    if smm_dir is None or identity.get_current_branch(cwd) != branch:
        return
    base = branch_resolution.get_story_base_branch_required(smm_dir, cwd)
    result = branch_lifecycle._git_retry_on_lock(["git", "checkout", base], cwd)
    if result.returncode != 0:
        raise RuntimeError(
            f"The main checkout at {cwd} is on '{branch}', the branch this "
            f"worktree needs, and git refused to check it away to the story "
            f"base '{base}': {result.stderr.strip()}. Not forcing the checkout "
            f"— that would discard whatever is uncommitted in the main "
            f"checkout. Clear what git reports above (commonly: commit or stash "
            f"the changes), then re-run the spawn."
        )

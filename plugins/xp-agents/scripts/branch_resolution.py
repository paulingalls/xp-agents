#!/usr/bin/env python3
"""Resolve SMM state into branch and stage answers.

Extracted from branching.py to keep that module under the 500-line
target. One concern: read the recorded state (system_context's
branching strategy, execution_plan's branch, sprint's branch_name),
check it against what actually exists in git, and produce the branch a
caller should fork from or merge into.

The stage machinery lives here WITH the resolvers rather than in a
third module: every resolver gates on the stage, so splitting them
would create an import cycle instead of avoiding one.

Import direction is strictly one-way — this module imports NOTHING from
branching; branching imports these names back and re-exports them for
backwards compat. Unlike the branch_lifecycle extraction, that means one
definition of ``_git``, not two: ``branching._git is branch_resolution._git``.

Consequence for tests: ``patch("branching.<name>")`` only reaches code
that still LIVES in branching.py. A call path that crosses into this
module resolves the name in THIS module's globals, and such a patch
silently stops applying. Patch the module that owns the caller.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common
import execution_plan_store
import identity
import sprint_store
import system_context_store
from branch_names import branch_name, sprint_branch_name

_DEFAULT_PRIMARY = "main"

_PROTECTED_BRANCHES = {"main", "master"}


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def _load_branching_strategy(smm_dir: Path) -> dict:
    """Read system_context.branching_strategy or {} on any failure."""
    path = smm_dir / "system_context.json"
    if not path.exists() or path.is_symlink():
        return {}
    try:
        ctx = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return ctx.get("branching_strategy") or {}


def _maybe_auto_promote(smm_dir: Path, current: int) -> int:
    """Auto-promote Stage 1 -> Stage 2 (plugin floor). Idempotent.

    Mutates system_context.json's branching_strategy.stage in place
    and emits a one-time decision event. Returns 2 on success; on an
    OSError (read-only SMM, missing dir, lock contention) returns the
    original stage so the next call to get_branching_stage retries the
    promotion. Schema-validation ValueErrors are intentionally NOT
    caught — they signal corrupt input or a code bug and propagate.
    """
    if current != 1:
        return current
    try:
        ctx = system_context_store.load_system_context(smm_dir)
        if ctx is None:
            return current
        ctx.setdefault("branching_strategy", {})["stage"] = 2
        system_context_store.save_system_context(smm_dir, ctx)
        event = _common.make_event(
            "decision",
            "branching",
            "Auto-promoted branching stage 1 -> 2 (plugin floor)",
            topic="branching-stage-auto-promote",
            metadata={"action": "stage_auto_promote", "from_stage": 1, "to_stage": 2},
        )
        _common.append_safe(smm_dir, event)
        return 2
    except OSError as e:  # narrow: ValueError (schema/code-bug) must crash loud
        _common.log_hook_error(
            f"branching auto-promote failed: {e}",
            error_class=type(e).__name__,
            from_stage=1,
            to_stage=2,
        )
        return current


def get_branching_stage(smm_dir: Path) -> int:
    """Return the branching stage. NOT side-effect free.

    A stage=1 read triggers a one-time auto-promotion (file mutation
    + decision event) via `_maybe_auto_promote`. Read-only or locked
    SMMs fail soft and return 1 unpromoted; the next call retries.
    Stage 0/2/3 reads remain pure.
    """
    stage = _load_branching_strategy(smm_dir).get("stage", 0)
    return _maybe_auto_promote(smm_dir, stage)


def get_primary_branch(smm_dir: Path) -> str:
    """Return the repo's primary integration branch.

    Stage 0-2: 'main'. Stage 3: branching_strategy.integration_branch,
    defaulting to 'main' when missing/null. Routes through
    ``get_branching_stage`` so primary-branch reads also fire the
    Stage 1 -> 2 auto-promote — single chokepoint for progression.
    """
    if get_branching_stage(smm_dir) < 3:
        return _DEFAULT_PRIMARY
    bs = _load_branching_strategy(smm_dir)
    return bs.get("integration_branch") or _DEFAULT_PRIMARY


def get_protected_branches(smm_dir: Path, stage: int) -> set[str]:
    """Return the stage-aware set of branches treated as protected.

    Stage 0: empty (branching doctrine inactive).
    Stage 1+: ``{main, master}`` plus ``branching_strategy.protected_branches``
    plus (at stage 3+) ``branching_strategy.integration_branch``. The
    integration branch is the daily fork-and-merge target — committing
    directly to it is the same anti-pattern as committing to main.

    ``stage`` is supplied by callers (rather than re-read here) so the
    stage 1→2 auto-promote side effect in ``get_branching_stage`` fires
    once per hook chain instead of doubling on every protection check.
    """
    if stage < 1:
        return set()
    result = set(_PROTECTED_BRANCHES)
    bs = _load_branching_strategy(smm_dir)
    declared = bs.get("protected_branches") or []
    result.update(declared)
    if stage >= 3:
        integration = bs.get("integration_branch")
        if integration:
            result.add(integration)
    return result


def is_protected_branch(stage: int, branch: str, smm_dir: Path) -> bool:
    return branch in get_protected_branches(smm_dir, stage)


def branch_exists(cwd: str, name: str) -> bool:
    r = _git(["git", "rev-parse", "--verify", f"refs/heads/{name}"], cwd)
    return r.returncode == 0


def match_local_branches(cwd: str, pattern: str) -> list[str]:
    """Run git for-each-ref against `refs/heads/<pattern>` and return short names."""
    r = _git(
        ["git", "for-each-ref", "--format=%(refname:short)", f"refs/heads/{pattern}"],
        cwd,
    )
    if r.returncode != 0:
        return []
    return [b for b in r.stdout.splitlines() if b]


def _recorded_plan_branch(cwd: str, smm_dir: Path) -> str | None:
    """Return execution_plan.branch when set AND a matching local branch exists.

    Prefers exact match. Falls back to a `<branch>-*` suffix-prefix scan
    (anchored on a separator so `plan-feat-*` doesn't match
    `plan-featured`) and prints a stderr note when the fallback fires —
    drift discovery should be visible. Note: get_story_base_branch
    handles sprint slug drift by reconstructing via slugify(goal); plan
    branches glob-scan because the recorded value IS the branch name.
    """
    plan = execution_plan_store.load_plan(smm_dir)
    if plan is None:
        return None
    plan_branch = plan.get("branch")
    if not plan_branch:
        return None
    if branch_exists(cwd, plan_branch):
        return plan_branch
    matches = sorted(match_local_branches(cwd, f"{plan_branch}-*"))
    if not matches:
        return None
    drifted = matches[0]
    print(
        f"note: recorded plan branch '{plan_branch}' not found locally;"
        f" using prefix match '{drifted}'",
        file=sys.stderr,
    )
    return drifted


def get_merge_target(smm_dir: Path, cwd: str) -> str:
    """Return the branch to merge into.

    Plan branch when execution_plan.branch resolves locally (exact match
    preferred, `<branch>-*` prefix-fallback for slug drift); otherwise
    the primary integration branch.
    """
    return _recorded_plan_branch(cwd, smm_dir) or get_primary_branch(smm_dir)


def _recorded_sprint_branch(cwd: str, smm_dir: Path, sprint_id: str) -> str | None:
    """The branch already recorded for THIS sprint_id, if it still exists.

    Keyed on sprint_id, not on "a branch_name is recorded": the next sprint's
    create overwrites the current sprint.json in place, so a stale record for
    the PREVIOUS sprint is routinely on disk when the next sprint's branch is
    cut. Resuming that would hand sprint N+1 sprint N's branch.

    Requires the branch to still exist locally, mirroring get_story_base_branch's
    recorded-then-verify check: a recorded name whose branch is gone is stale, and
    the slug is the better guess (test_resume_re_records_fixing_drift pins that).

    Fails open where get_story_base_branch lets SprintCorruptError fly, because
    this runs BEFORE the stage gate: below the branching floor create_sprint_branch
    must stay a clean no-op even on an unreadable sprint. It buys no silence above
    the floor — set_branch re-raises on the same corruption once the branch is cut.
    Loudness is delegated there, not dropped.
    """
    sprint = sprint_store.load_sprint_fail_open(smm_dir)
    if sprint is None or sprint.get("sprint_id") != sprint_id:
        return None
    recorded = sprint.get("branch_name")
    return recorded if recorded and branch_exists(cwd, recorded) else None


def resolve_sprint_branch_name(
    cwd: str, sprint_id: str, slug: str, smm_dir: Path
) -> str:
    """The branch ``create_sprint_branch`` will use: the one already recorded for
    this sprint_id if it still exists, else one rebuilt from ``slug``.

    Public because branching_cli must ask the SAME question to decide whether it
    is about to create or resume. Deriving that from the slug alone reports a
    resumed re-slice branch as ``created:`` — the slug-built name never exists on
    a re-slice, which is the entire point — and SKILL.md Step 8 routes its
    adopt/rename prompt on that token. One resolver, one answer, both callers.
    """
    return _recorded_sprint_branch(cwd, smm_dir, sprint_id) or branch_name(
        identity.user_namespace(cwd), sprint_id, slug
    )


def get_story_base_branch(smm_dir: Path, cwd: str) -> str:
    """Return the base branch for stories: sprint branch at stage 2+, else primary.

    Prefers sprint['branch_name'] (recorded atomically at create time) and
    falls back to slugify(goal) reconstruction so older sprints written
    before atomic recording still resolve.
    """
    primary = get_primary_branch(smm_dir)
    stage = get_branching_stage(smm_dir)
    if stage < 2:
        return primary

    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return primary

    stored = sprint.get("branch_name")
    if stored and branch_exists(cwd, stored):
        return stored

    user_ns = identity.user_namespace(cwd)
    name = sprint_branch_name(user_ns, sprint["sprint_id"], sprint["goal"])

    if branch_exists(cwd, name):
        return name

    return primary

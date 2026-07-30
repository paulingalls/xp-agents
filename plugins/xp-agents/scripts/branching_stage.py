#!/usr/bin/env python3
"""The branching STAGE, and the branches it makes special.

Extracted from ``branch_resolution.py`` at 501 lines. That module's docstring
warned a third module for the stage machinery would create an import cycle,
"since every resolver gates on the stage". It does not: the dependency runs one
way only. Nothing here calls a resolver — the stage comes from
system_context.json, the primary branch from the stage, and the protected set
from both. So this is a LEAF, and the resolvers import it.

``get_branching_stage`` is NOT side-effect free (a stage-1 read auto-promotes to
the plugin floor), which is the one thing to know before calling it from a new
site. ``get_primary_branch`` routes through it deliberately, to keep progression
on a single chokepoint.

Re-exported from ``branch_resolution`` BY IDENTITY, so every existing
``mock.patch("branch_resolution.get_primary_branch")`` site — and
``branch_resolution._DEFAULT_PRIMARY`` / ``._maybe_auto_promote``, which tests
and prose both name — resolves unchanged.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common
import system_context_store
from system_context_schema import healed_integration_branch

_DEFAULT_PRIMARY = "main"

_PROTECTED_BRANCHES = {"main", "master"}


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
    defaulting to 'main' when missing/null OR when the stored value cannot
    serve as a git ref. Routes through ``get_branching_stage`` so
    primary-branch reads also fire the Stage 1 -> 2 auto-promote — single
    chokepoint for progression.

    The answer is handed to `git checkout` / `git merge` as argv, so a stored
    value that predates the ref-format check is healed HERE rather than
    trusted: `-f` matches the branch-name pattern and would reach git as a
    FLAG. Falling back to primary mirrors what this function already does for
    a null value, and keeps every hook path non-raising. A substitution IS
    logged — it changes a merge/checkout target, which must not be silent.
    """
    if get_branching_stage(smm_dir) < 3:
        return _DEFAULT_PRIMARY
    bs = _load_branching_strategy(smm_dir)
    healed = healed_integration_branch(bs)
    stored = bs.get("integration_branch")
    # Null AND empty both mean "never configured" — the same falsy set the
    # renderer hides and the pre-check `or _DEFAULT_PRIMARY` fell through on.
    # Logging those would fire on every read of a stage-3 repo that never set
    # the field; anything else IS a configured value we are overriding.
    if healed is None and stored not in (None, ""):
        _common.log_hook_error(
            f"branching_strategy.integration_branch {stored!r} is not usable "
            f"as a git ref; resolving the primary branch as "
            f"{_DEFAULT_PRIMARY!r} instead",
            error_class="ValueError",
            integration_branch=stored,
            substituted=_DEFAULT_PRIMARY,
        )
    return healed or _DEFAULT_PRIMARY


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

    Routes the integration branch through the SAME heal helper as
    ``get_primary_branch``, so the raw-JSON reader and the validated loader
    cannot disagree about what the value resolves to. Unlike there, a dropped
    entry is NOT logged: it is the lesser event (one fewer branch treated as
    protected, not a redirected merge), and this runs on every Bash
    PreToolUse.
    """
    if stage < 1:
        return set()
    result = set(_PROTECTED_BRANCHES)
    bs = _load_branching_strategy(smm_dir)
    declared = bs.get("protected_branches") or []
    result.update(declared)
    if stage >= 3:
        integration = healed_integration_branch(bs)
        if integration:
            result.add(integration)
    return result


def is_protected_branch(stage: int, branch: str, smm_dir: Path) -> bool:
    return branch in get_protected_branches(smm_dir, stage)

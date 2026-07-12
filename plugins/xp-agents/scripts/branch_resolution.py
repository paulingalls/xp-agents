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


def ref_exists(cwd: str, ref: str) -> bool:
    """True when ``ref`` resolves to a commit — branch, tag, SHA, or remote ref.

    Deliberately broader than ``branch_exists`` (refs/heads only): a HANDED base
    is legitimately a bare SHA (chained stories fork off a commit) or a remote
    ref, so the trust question for one is "can git resolve this to a commit",
    not "is this a local branch". Empty and whitespace refs resolve to nothing
    and answer False, as they should.
    """
    r = _git(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd)
    return r.returncode == 0


def _verified_local(cwd: str, name: str | None) -> str | None:
    """Return ``name`` only if it is set AND still names a local branch.

    The invariant this module exists to enforce: a RECORDED branch name is
    trustworthy only if it still EXISTS. Branches get deleted, renamed, and
    left behind in other worktrees; sprint.json does not notice. Handing a
    recorded-but-vanished name to `git checkout`/`git merge` as a ref is the
    silent-corruption path — so every recorded name is verified before it is
    returned as an answer.
    """
    return name if name and branch_exists(cwd, name) else None


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
    return _verified_local(cwd, sprint.get("branch_name"))


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

    THIS IS A CREATION ANSWER, NOT A NAVIGATION ANSWER. The name it returns MAY
    NOT EXIST YET — on a fresh sprint it is guaranteed not to, which is the whole
    job. NEVER route a checkout or a merge base through it.

    ``resolve_story_base`` looks like a near-duplicate of this and CANNOT be
    collapsed onto it. That collapse has been proposed once already and rejected;
    the rejection lives HERE, not only in the event log, because the next agent to
    notice the resemblance will read the function, not the SMM. Two reasons, both
    load-bearing:

    1. VERIFICATION POSTURE IS OPPOSITE. This function's fallback arm is
       deliberately UNVERIFIED — it answers "what name WILL create_sprint_branch
       use?", so the branch must be allowed not to exist. resolve_story_base can
       never return such a name: every arm of it that returns a SPRINT branch is
       _verified_local-checked, and when that check fails it returns None rather
       than the unverified name, because it answers "what ref do I hand to `git
       checkout` / `git merge`?" (Its other two arms return the primary branch —
       degradations, not sprint-branch guesses.) Collapsing them would hand git a
       branch that is absent in precisely the fresh-sprint case. That is worse
       than the bug story-008 fixed: a degraded base at least pointed at a real
       branch.
    2. LOUDNESS IS OPPOSITE. This reads through ``load_sprint_fail_open`` because
       it runs BELOW the stage gate, where a corrupt sprint.json must degrade to
       a clean no-op. resolve_story_base reads through the loud ``load_sprint``
       because it runs ABOVE the gate and feeds the branch we merge INTO, where
       silently swallowing corruption is unacceptable. Routing one through the
       other would swallow a corrupt sprint on the merge path.

    (They also take different inputs — this one is handed sprint_id + slug;
     resolve_story_base must load the sprint to find them. That difference is
     real but incidental; the two above are the reasons.)
    """
    return _recorded_sprint_branch(cwd, smm_dir, sprint_id) or branch_name(
        identity.user_namespace(cwd), sprint_id, slug
    )


def _slug_rebuilt_sprint_branch(cwd: str, sprint: dict) -> str:
    """The sprint branch name rebuilt from slugify(goal).

    The fallback candidate for sprints written before create_sprint_branch
    recorded ``branch_name`` atomically. May or may not exist — callers verify.
    """
    return sprint_branch_name(
        identity.user_namespace(cwd), sprint["sprint_id"], sprint["goal"]
    )


def resolve_story_base(smm_dir: Path, cwd: str) -> str | None:
    """The story base branch, or None when the recorded state is DISHONEST.

    Returns the primary branch for the two LEGITIMATE degradations — below the
    branching floor (stage < 2: sprint branches do not exist by design), and no
    sprint at all (free/ad-hoc work). In both, primary is the TRUE answer, not
    a guess, and callers proceed normally.

    Returns None for exactly ONE state: a sprint EXISTS at stage >= 2, but
    neither its recorded ``branch_name`` nor the name rebuilt from
    slugify(goal) names a local branch. There IS a sprint branch we are
    supposed to be based on, and we cannot find it. Any answer is a guess here
    — and the guess the old code made was primary, i.e. the release branch.

    Scoping the None to that one state is deliberate: widen it and the PROBE /
    RESTORE callers (which are right to degrade) start failing too.

    Reads through the LOUD ``load_sprint``. This runs ABOVE the stage gate and
    feeds the branch we merge INTO, so a corrupt sprint.json must raise rather
    than quietly become "no sprint" and hence "primary".
    ``_recorded_sprint_branch`` uses the fail-open loader for the opposite
    reason — it runs BELOW the gate, where a clean no-op is the right answer.
    """
    if get_branching_stage(smm_dir) < 2:
        return get_primary_branch(smm_dir)

    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return get_primary_branch(smm_dir)

    return _verified_local(cwd, sprint.get("branch_name")) or _verified_local(
        cwd, _slug_rebuilt_sprint_branch(cwd, sprint)
    )


def get_story_base_branch(smm_dir: Path, cwd: str) -> str:
    """The story base branch, degrading to primary when it cannot be resolved.

    Byte-identical to the historical behavior, silent primary-fallback included.
    Correct ONLY for callers that PROBE or RESTORE — measure commits_ahead,
    compute a diff range, heal an interrupted checkout. For them primary is a
    serviceable approximation, and raising would take down a gate that is only
    trying to observe.

    Callers that BRANCH FROM or MERGE INTO the answer must use
    ``get_story_base_branch_required``: handing THEM a silent primary cuts story
    branches off the release branch, or merges them into it.
    """
    return resolve_story_base(smm_dir, cwd) or get_primary_branch(smm_dir)


def get_story_base_branch_required(smm_dir: Path, cwd: str) -> str:
    """The story base branch, raising when it cannot be honestly resolved.

    The narrowing sibling of ``resolve_story_base``, in the shape the codebase
    already uses for this (``sprint_store.load_sprint_required``,
    ``execution_plan_store.load_plan_required``): pyright sees ``str``, so
    callers that fork a branch or pick a merge target need no None-check.

    For every caller that BRANCHES FROM or MERGES INTO the result. Raises
    ValueError naming the sprint, both candidate names, the primary branch it
    REFUSED to silently return, and the way out — the whole point is that the
    caller must not proceed on a guess.
    """
    base = resolve_story_base(smm_dir, cwd)
    if base is not None:
        return base

    # None only in the dishonest state, so the sprint loaded and exists — re-read
    # it to name the candidates we could not resolve.
    sprint = sprint_store.load_sprint_required(smm_dir)
    recorded = sprint.get("branch_name") or "(none recorded)"
    rebuilt = _slug_rebuilt_sprint_branch(cwd, sprint)
    raise ValueError(
        f"Cannot resolve the story base branch for {sprint['sprint_id']}: "
        f"neither the recorded branch '{recorded}' nor the name rebuilt from "
        f"the sprint goal '{rebuilt}' exists locally. Refusing to fall back to "
        f"'{get_primary_branch(smm_dir)}' — branching a story off the "
        f"integration branch (or merging one into it) is not what you asked "
        f"for. Fix: if it exists on a remote (sprint branches are pushed when "
        f"one is configured), `git fetch` and check it out locally; else re-cut "
        f"it (`branching.py create-sprint`) or correct sprint.json's "
        f"'branch_name' to a branch that exists."
    )


def trusted_story_base(cwd: str, smm_dir: Path, base: str | None) -> str:
    """The base a story branch forks from — never a guess, never a lie.

    The one entry point ``create_story_branch`` uses, covering both ways a base
    arrives. Both arms of ``_create_or_resume_branch`` turn the result into a
    git ref (`git checkout -b <name> <base>` when creating,
    ``_fast_forward_if_safe`` when resuming), and the RESUME arm is the
    dangerous one: it swallows a base git cannot resolve (`git merge-base
    --is-ancestor <branch> <junk>` merely exits non-zero, so the fast-forward
    silently no-ops) and still reports the branch as resumed.

    base=None — resolve it, RAISING rather than degrading to primary. A silent
    primary cuts the story off the release branch; on the resume arm it
    fast-forwards an existing story branch ONTO primary (a branch with no unique
    commits IS an ancestor of it, so the fast-forward is "safe" by every check we
    have), picking up everything landed since the fork — which story-close then
    merges straight back INTO primary.

    base handed in — verify git resolves it. This is the arm that guards the
    SHIPPED path: the story SKILLs capture a base from `get-base` and always
    pass --base explicitly, so hardening only the base=None arm would leave
    production untouched (decision harden-the-capture-not-the-default).
    """
    if base is None:
        return get_story_base_branch_required(smm_dir, cwd)
    if not ref_exists(cwd, base):
        raise ValueError(
            f"Cannot use '{base}' as the story base: git cannot resolve it to a "
            f"commit. Refusing to create or resume a story branch against a base "
            f"that does not exist — on the resume arm an unresolvable base is "
            f"silently ignored, and the branch is reported as resumed while it "
            f"still points at whatever it was originally forked from. Fix: pass "
            f"a ref that exists, or omit the base entirely to resolve it from "
            f"the sprint."
        )
    return base

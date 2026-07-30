#!/usr/bin/env python3
"""Resolve SMM state into branch and stage answers.

Extracted from branching.py to keep that module under the 500-line
target, then split again at 501 lines into a three-layer stack, each layer
importing only downwards:

    git_refs          does git know this name?          (leaf)
    branching_stage   which stage, primary, protected   (leaf)
    branch_resolution which branch should you use       (this module)

The stage machinery moved out with a caveat retired: the old docstring said a
third module would create an import cycle "since every resolver gates on the
stage", but the dependency only ever ran one way — nothing in the stage
machinery calls a resolver. What is left here is the part that genuinely needs
both layers: read the recorded state (execution_plan's branch, sprint's
branch_name), check it against what actually exists in git, and produce the
branch a caller should fork from or merge into.

Import direction is strictly one-way — this module imports NOTHING from
branching; branching imports these names back and re-exports them for
backwards compat. The same holds for the two layers below, and everything they
define is re-exported HERE by identity: ``branching._git is
branch_resolution._git`` still holds, and so does every
``mock.patch("branch_resolution.<name>")`` site.

Consequence for tests: ``patch("branching.<name>")`` only reaches code
that still LIVES in branching.py. A call path that crosses into this
module resolves the name in THIS module's globals, and such a patch
silently stops applying. Patch the module that owns the caller. The same rule
now applies one layer down: a name patched HERE is not seen by a caller that
lives in ``branching_stage`` or ``git_refs``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# `_common` is no longer called from this module, but it stays imported: it is
# part of the same re-export surface as the names below. Five tests patch
# `branch_resolution._common.log_hook_error` to assert what `get_primary_branch`
# does and does not log, and that still WORKS across the split — patching an
# attribute on the shared `_common` module object is global, so the caller now
# living in `branching_stage` sees it. Drop this import and those tests fail on
# an unresolvable target rather than on behaviour.
import _common  # noqa: F401
import execution_plan_store
import identity
import sprint_store
from branch_names import branch_name, sprint_branch_name

# Re-exported BY IDENTITY, not re-implemented — see the module docstring. The
# `branching`, `branching_core` and every mock.patch site, not dead imports.
from branching_stage import (  # noqa: F401
    _DEFAULT_PRIMARY,
    _PROTECTED_BRANCHES,
    _load_branching_strategy,
    _maybe_auto_promote,
    get_branching_stage,
    get_primary_branch,
    get_protected_branches,
    is_protected_branch,
)
from git_refs import (  # noqa: F401
    _git,
    _verified_local,
    branch_exists,
    match_local_branches,
    ref_exists,
)


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
        identity.user_namespace(cwd, smm_dir), sprint_id, slug
    )


def _slug_rebuilt_sprint_branches(cwd: str, sprint: dict, smm_dir: Path) -> list[str]:
    """Sprint branch names rebuilt from slugify(goal), best candidate first.

    The fallback for sprints written before create_sprint_branch recorded
    ``branch_name`` atomically; they may not exist, so callers verify. TWO of
    them whenever a recorded ``user_namespace`` override differs from the git
    identity, and that is the point: the sprints this fallback exists for
    predate the override being read by anything, so their branches carry the
    GIT-derived prefix. Rebuilding only under the override turns a soft fallback
    into a hard refusal — a None from `resolve_story_base` takes /xp-assign,
    /xp-schedule, /xp-story-close and the branch-delete guard down on a sprint
    that worked before the upgrade.
    """
    namespaces = dict.fromkeys(
        [identity.user_namespace(cwd, smm_dir), identity.git_user_namespace(cwd)]
    )
    return [
        sprint_branch_name(ns, sprint["sprint_id"], sprint["goal"]) for ns in namespaces
    ]


def resolve_story_base(smm_dir: Path, cwd: str) -> str | None:
    """The story base branch, or None when the recorded state is DISHONEST.

    Returns the primary branch for the two LEGITIMATE degradations — below the
    branching floor (stage < 2: sprint branches do not exist by design), and no
    sprint at all (free/ad-hoc work). In both, primary is the TRUE answer, not
    a guess, and callers proceed normally.

    Returns None for exactly ONE state: a sprint EXISTS at stage >= 2, but
    neither its recorded ``branch_name`` nor any name rebuilt from slugify(goal)
    (see ``_slug_rebuilt_sprint_branches``) is a local branch. There IS a sprint
    branch we are supposed to be based on, and we cannot find it. Any answer is
    a guess — and the guess the old code made was primary, the release branch.
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

    for candidate in (
        sprint.get("branch_name"),
        *_slug_rebuilt_sprint_branches(cwd, sprint, smm_dir),
    ):
        verified = _verified_local(cwd, candidate)
        if verified is not None:
            return verified
    return None


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
    rebuilt = ", ".join(
        f"'{name}'" for name in _slug_rebuilt_sprint_branches(cwd, sprint, smm_dir)
    )
    raise ValueError(
        f"Cannot resolve the story base branch for {sprint['sprint_id']}: "
        f"neither the recorded branch '{recorded}' nor the name(s) rebuilt from "
        f"the sprint goal ({rebuilt}) exist locally. Refusing to fall back to "
        f"'{get_primary_branch(smm_dir)}' — branching a story off the "
        f"integration branch (or merging one into it) is not what you asked "
        f"for. Fix: if it exists on a remote (sprint branches are pushed when "
        f"one is configured), `git fetch` and check it out locally; else re-cut "
        f"it (`branching.py create-sprint`) or correct sprint.json's "
        f"'branch_name' to a branch that exists."
    )


def trusted_handed_base(cwd: str, base: str, *, omit_resolves: str) -> str:
    """A base the CALLER handed us — returned only once git can resolve it.

    Guards the arm that every ``--base``-taking command shares, and it is the
    silent one. Both arms of ``_create_or_resume_branch`` turn a base into a git
    ref, but only the CREATE arm has git to reject it (`git checkout -b <name>
    <junk>` fails). On the RESUME arm nothing does: ``_fast_forward_if_safe``
    asks `git merge-base --is-ancestor <branch> <junk>`, which merely exits
    non-zero, so the fast-forward no-ops — and the branch is reported as
    resumed while it still points at whatever it was originally forked from.

    ``omit_resolves`` names what omitting ``--base`` would resolve instead, so
    the way out is specific to the command the user actually ran.
    """
    if not ref_exists(cwd, base):
        raise ValueError(
            f"Cannot use '{base}' as the branch base: git cannot resolve it to a "
            f"commit. Refusing to create or resume a branch against a base that "
            f"does not exist — on the resume arm an unresolvable base is silently "
            f"ignored, and the branch is reported as resumed while it still points "
            f"at whatever it was originally forked from. Fix: pass a ref that "
            f"exists, or omit the base entirely to resolve {omit_resolves}."
        )
    return base


def trusted_story_base(cwd: str, smm_dir: Path, base: str | None) -> str:
    """The base a story branch forks from — never a guess, never a lie.

    The one entry point ``create_story_branch`` uses, covering both ways a base
    arrives.

    base=None — resolve it, RAISING rather than degrading to primary. A silent
    primary cuts the story off the release branch; on the resume arm it
    fast-forwards an existing story branch ONTO primary (a branch with no unique
    commits IS an ancestor of it, so the fast-forward is "safe" by every check we
    have), picking up everything landed since the fork — which story-close then
    merges straight back INTO primary.

    base handed in — ``trusted_handed_base``. This is the arm that guards the
    SHIPPED path: the story SKILLs capture a base from `get-base` and always
    pass --base explicitly, so hardening only the base=None arm would leave
    production untouched (decision harden-the-capture-not-the-default).
    """
    if base is None:
        return get_story_base_branch_required(smm_dir, cwd)
    return trusted_handed_base(
        cwd, base, omit_resolves="the story base from the sprint"
    )

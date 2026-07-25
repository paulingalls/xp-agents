#!/usr/bin/env python3
"""branching_strategy validation and git-ref healing.

Extracted from ``system_context_schema.py`` to keep that file under the
500-line cap (it had reached 560). Re-exported from ``system_context_schema``
BY IDENTITY, matching the ``system_context_entry_validators`` precedent, so
every existing ``from system_context_schema import integration_branch_error`` /
``healed_user_namespace`` reference — and every ``mock.patch`` site targeting
one — resolves unchanged.

The two ``*_error`` / ``healed_*`` pairs exist because these fields reach `git
checkout` / `git branch` as ARGV: the error form is the write-time gate, the
healed form is the use-time fallback. Keeping both halves of both pairs in one
module is the point — a new ref-shaped field should be able to see, in one
file, that it needs both.
"""

from execution_plan_schema import usable_git_ref_name
from schema_helpers import budget_error
from smm_schema import is_iso8601

BRANCHING_STRATEGY_FIELD_MAXLENGTH: dict[str, int] = {
    "rationale": 300,
    "user_namespace": 50,
    # None = never dismissed; ISO 8601 string = dismissed at that time.
    # ISO 8601 with offset is ~32 chars; 50 leaves headroom for fractional
    # seconds + future format variants without re-bumping the budget.
    "stage_prompt_dismissed_at": 50,
}

_BRANCHING_STRATEGY_REQUIRED = frozenset({"stage"})


def integration_branch_error(bs: object) -> str | None:
    """Message when branching_strategy.integration_branch cannot serve as a
    git ref, else None. Null/missing is fine — callers fall back to primary.

    Same class of value as sprint.branch_name and plan.branch, and now held
    to the same rule: ``get_primary_branch`` hands this straight to `git
    checkout` / `git merge` as argv.
    """
    if not isinstance(bs, dict) or bs.get("integration_branch") is None:
        return None
    value = bs["integration_branch"]
    if usable_git_ref_name(value):
        return None
    return (
        "branching_strategy.integration_branch must be a branch name usable as"
        f" a git ref (got {value!r}): slash-separated [A-Za-z0-9._-], no leading"
        " dash (it would reach `git checkout` / `git merge` as a FLAG); use null"
        " to leave it unset"
    )


def healed_integration_branch(bs: object) -> str | None:
    """The stored value when usable as a ref, else None (fall back to primary).

    The SINGLE heal helper, applied where the value is USED rather than where
    it is loaded. Loaders preserve the stored bytes: `branch_resolution`'s
    stage auto-promote does load → mutate → save, so healing inside a loader
    would silently persist the substitute over the branch a user configured.
    """
    if not isinstance(bs, dict):
        return None
    value = bs.get("integration_branch")
    return value if usable_git_ref_name(value) else None


def _usable_ref_segment(value: object) -> bool:
    """True when value is usable as ONE component of a ref — a `/` disqualifies.

    Stricter than ``usable_git_ref_name`` by exactly one rule, and only for
    ``user_namespace``: that value is the FIRST COMPONENT of the branch names
    the plugin later parses with ``^[^/]+/…`` (``is_free_branch``,
    ``is_sprint_branch``, ``extract_story_id``). A two-segment namespace would
    produce ``team/paul/free-…`` — a branch git happily creates and every one
    of those parsers then fails to recognize, so free-close and story-close
    refuse the plugin's own branches. A full ref (integration_branch) is NOT
    held to this: slashes are legitimate there.
    """
    return usable_git_ref_name(value) and "/" not in value


def user_namespace_error(bs: object) -> str | None:
    """Message when branching_strategy.user_namespace cannot serve as a ref
    segment, else None. Absent/empty is fine — callers derive from git identity.

    Same argv class as ``integration_branch``: the value is interpolated into
    branch names (``<user_namespace>/free-…``) that reach `git branch` and
    `git checkout` as argv, so a leading dash would arrive as a FLAG.
    """
    if not isinstance(bs, dict) or "user_namespace" not in bs:
        return None
    value = bs["user_namespace"]
    if not isinstance(value, str) or not value.strip():
        return None
    if _usable_ref_segment(value):
        return None
    return (
        "branching_strategy.user_namespace must be usable as a single git ref"
        f" segment (got {value!r}): [A-Za-z0-9._-], no `/` (it is the first"
        " component of `<namespace>/free-…` branch names the branch helpers"
        " parse), no leading dash (it would reach `git branch` / `git checkout`"
        " as a FLAG); omit it to derive the namespace from git identity"
    )


def healed_user_namespace(bs: object) -> str | None:
    """The stored namespace when usable as a ref segment, else None.

    None means "no override" — ``identity.user_namespace`` then derives from
    git identity as before. Applied where the value is USED, matching
    ``healed_integration_branch``: loaders preserve the stored bytes so a
    substitute is never silently persisted over what a user configured.
    """
    if not isinstance(bs, dict):
        return None
    value = bs.get("user_namespace")
    if not isinstance(value, str) or not value.strip():
        return None
    return value if _usable_ref_segment(value) else None


def _validate_branching_strategy(
    bs: object, *, enforce_budget: bool = True, enforce_ref_format: bool = True
) -> list[str]:
    errors: list[str] = []
    if not isinstance(bs, dict):
        return ["branching_strategy must be an object"]

    for field in _BRANCHING_STRATEGY_REQUIRED:
        if field not in bs:
            errors.append(f"branching_strategy missing required field: {field}")

    if errors:
        return errors

    stage = bs["stage"]
    if not isinstance(stage, int) or isinstance(stage, bool):
        errors.append("branching_strategy.stage must be an integer")
    elif stage < 0 or stage > 3:
        errors.append(f"branching_strategy.stage must be 0-3 (got {stage})")

    if "user_namespace" in bs:
        if not isinstance(bs["user_namespace"], str):
            errors.append("branching_strategy.user_namespace must be a string")
        else:
            if enforce_budget:
                max_len = BRANCHING_STRATEGY_FIELD_MAXLENGTH["user_namespace"]
                actual = len(bs["user_namespace"])
                if actual > max_len:
                    errors.append(
                        budget_error(
                            "branching_strategy.user_namespace", actual, max_len
                        )
                    )
            if enforce_ref_format:
                ns_error = user_namespace_error(bs)
                if ns_error is not None:
                    errors.append(ns_error)

    if "protected_branches" in bs:
        pb = bs["protected_branches"]
        if not isinstance(pb, list):
            errors.append("branching_strategy.protected_branches must be a list")
        else:
            for idx, item in enumerate(pb):
                if not isinstance(item, str):
                    errors.append(
                        f"branching_strategy.protected_branches[{idx}] must be a string"
                    )

    if "integration_branch" in bs:
        ib = bs["integration_branch"]
        if ib is not None and not isinstance(ib, str):
            errors.append(
                "branching_strategy.integration_branch must be a string or null"
            )
        elif enforce_ref_format:
            ref_error = integration_branch_error(bs)
            if ref_error is not None:
                errors.append(ref_error)

    if "rationale" in bs:
        if not isinstance(bs["rationale"], str):
            errors.append("branching_strategy.rationale must be a string")
        elif enforce_budget:
            max_len = BRANCHING_STRATEGY_FIELD_MAXLENGTH["rationale"]
            actual = len(bs["rationale"])
            if actual > max_len:
                errors.append(
                    budget_error("branching_strategy.rationale", actual, max_len)
                )

    if "stage_prompt_dismissed_at" in bs:
        val = bs["stage_prompt_dismissed_at"]
        if val is not None and not isinstance(val, str):
            errors.append(
                "branching_strategy.stage_prompt_dismissed_at must be a string or null"
            )
        elif isinstance(val, str):
            if enforce_budget:
                max_len = BRANCHING_STRATEGY_FIELD_MAXLENGTH[
                    "stage_prompt_dismissed_at"
                ]
                actual = len(val)
                if actual > max_len:
                    errors.append(
                        budget_error(
                            "branching_strategy.stage_prompt_dismissed_at",
                            actual,
                            max_len,
                        )
                    )
            if not is_iso8601(val):
                errors.append(
                    "branching_strategy.stage_prompt_dismissed_at must be"
                    " an ISO 8601 timestamp string"
                )

    return errors

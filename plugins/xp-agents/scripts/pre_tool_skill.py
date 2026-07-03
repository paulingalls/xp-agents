#!/usr/bin/env python3
"""PreToolUse:Skill hook — gate + inject guidance before skills run.

- Teammate gate: block CLI teammates from lead-owned lifecycle skills
  (everything shipped except the review cycle). Teammates implement one story
  and report; the lead coordinates the project (plan, schedule, accept, close).
- /code-review: courage nudge — review every change, act on every finding.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import identity
import target_routing
import worktree

_CODE_REVIEW_COURAGE = (
    "Courage means doing the right thing even when it's uncomfortable. "
    "/code-review identifies correctness bugs but fixes nothing — every "
    "finding comes back unaddressed. Run it on every change, even ones that "
    "'look small'. The fix happens next in /xp-quality-review, where each "
    "valid finding must be addressed (or recorded as debt with a concrete "
    "reason) — never waved off as low-severity, pre-existing, or out of scope."
)

# Every shipped xp-agents skill directory name. Pinned to skills/ by
# test_pre_tool_skill's superset guard, so a NEW skill fails the test until it
# is classified — added to the teammate allowlist below or left lead-owned
# (blocked for teammates by default). Fail-closed: the gate can't silently skip
# a skill that didn't exist when this list was written.
_OUR_SKILLS = frozenset(
    {
        "xp-accept",
        "xp-assign",
        "xp-end-session",
        "xp-free-close",
        "xp-kickoff",
        "xp-plan",
        "xp-plan-close",
        "xp-quality-review",
        "xp-review-plan",
        "xp-scaffold-acceptance",
        "xp-schedule",
        "xp-sprint-close",
        "xp-sprint-review",
        "xp-sprint-start",
        "xp-stage-migration",
        "xp-story-close",
        "xp-system-context",
        "xp-work-selection",
    }
)

# The only xp-agents skill a CLI teammate may invoke: the per-commit review
# cycle. Everything else in _OUR_SKILLS coordinates the project lifecycle and
# belongs to the lead. In per-story cadence the review moves to /xp-story-close
# (lead-owned, blocked here), so a teammate correctly runs no review itself.
_TEAMMATE_ALLOWED_SKILLS = frozenset({"xp-quality-review"})

_TEAMMATE_BLOCK = (
    "This is a lead-owned lifecycle skill — CLI teammates don't run it. "
    "Implement your assigned story (TDD, /xp-quality-review, commit), then "
    "write your report and stop. The lead runs acceptance and close; a "
    "teammate advancing the story lifecycle or merging inverts the flow and "
    "breaks the lead's /xp-accept."
)


def _is_live_teammate(input_data: dict, smm_dir: Path | None) -> bool:
    """True only for a GENUINE live CLI teammate — not a lead with a leaked env.

    A worktree teammate is identified by its cwd path marker (non-leaky). An
    in-place teammate shares the main checkout, so it is recovered from
    XP_TEAMMATE_NAME — a documented leaky var — and trusted ONLY when the
    lifetime-scoped in-place marker spawn_teammate writes is live (the same
    guard commit_handling uses for attribution). Without that marker, a lead
    that inherited a leaked var is NOT a teammate and must not be locked out of
    lead-owned skills.
    """
    cwd_name = identity.extract_worktree_name(input_data.get("cwd", ""))
    if cwd_name and identity.is_teammate_agent_id(cwd_name):
        return True
    env_name = identity.teammate_name_from_env()
    if env_name is None or not identity.is_teammate_agent_id(env_name):
        return False
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    return (
        smm_dir is not None
        and worktree.in_place_teammate_from_env(smm_dir, env_name)
    )


def teammate_block_reason(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Block reason when a CLI teammate invokes a lead-owned lifecycle skill.

    Returns None (allow) for the lead (including a lead with a leaked
    XP_TEAMMATE_NAME but no live in-place marker), for the review-cycle skill,
    for our own xp- subagents (recursion guard), and for non-xp or third-party
    skills (strip_our_namespace → not in _OUR_SKILLS).
    """
    if _common.is_xp_agent(input_data):
        return None
    if not _is_live_teammate(input_data, smm_dir):
        return None
    skill = input_data.get("tool_input", {}).get("skill", "")
    bare = target_routing.strip_our_namespace(skill)
    if bare in _OUR_SKILLS and bare not in _TEAMMATE_ALLOWED_SKILLS:
        return _TEAMMATE_BLOCK
    return None


def run(input_data: dict, **_kwargs) -> str | None:
    """Inject guidance before skills run."""
    if _common.is_xp_agent(input_data):
        return None

    skill = input_data.get("tool_input", {}).get("skill", "")
    # Exact-match the built-in /code-review skill (bare or our-namespace-qualified).
    # Substring matching would catch xp-code-reviewer (our agent, not the skill)
    # and any third-party `otherplugin:code-review` skill.
    if target_routing.strip_our_namespace(skill) == "code-review":
        return _CODE_REVIEW_COURAGE

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    block = teammate_block_reason(input_data)
    if block:
        _common.block_output(block, "Lead-owned skill blocked for CLI teammate.")
        sys.exit(0)
    result = run(input_data)
    if result:
        _common.hook_output("PreToolUse", result)
    sys.exit(0)

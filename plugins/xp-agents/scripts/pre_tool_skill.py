#!/usr/bin/env python3
"""PreToolUse:Skill hook — gate + inject guidance before skills run.

- Teammate gate: block CLI teammates from lead-owned lifecycle skills
  (everything shipped except the review cycle). Teammates implement one story
  and report; the lead coordinates the project (plan, schedule, accept, close).
- /code-review: courage nudge — act on every finding it reports.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import identity
import sprint_state
import sprint_store
import target_routing
import worktree

_CODE_REVIEW_COURAGE = (
    "Courage means doing the right thing even when it's uncomfortable. "
    "/code-review identifies correctness bugs but fixes nothing — every "
    "finding comes back unaddressed. The fix happens next in "
    "/xp-quality-review, where each valid finding must be addressed (or "
    "recorded as debt with a concrete reason) — never waved off as "
    "low-severity, pre-existing, or out of scope. It cannot be launched "
    "with the Skill tool — invoke Workflow instead."
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
    return smm_dir is not None and worktree.in_place_teammate_from_env(
        smm_dir, env_name
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


_ACCEPT_EVIDENCE_BLOCK = (
    "Refusing /xp-story-close: run /xp-accept to verify acceptance first — "
    "/xp-accept drives the close itself once acceptance is confirmed. Driving "
    "/xp-story-close directly merges before acceptance is ever verified."
)


def accept_evidence_block_reason(
    input_data: dict, smm_dir: Path | None = None
) -> str | None:
    """Block a lead-driven /xp-story-close that has no accept evidence.

    Only /xp-story-close is gated — sprint/plan/free close don't require
    per-story acceptance. The evidence signal is a story in `closing` state:
    /xp-accept Step 1.5 CAS-transitions the target story `reviewing → closing`
    immediately before dispatching /xp-story-close, and `closing` is the
    singleton in-pipeline lock (exactly one story at a time), so its presence
    is tight, per-close evidence — present when /xp-accept is driving the
    close, absent when an agent invokes /xp-story-close directly. Teammates
    are handled by ``teammate_block_reason``, which ``__main__`` runs (and
    blocks on) before reaching this gate — so this gate targets the lead
    invocation only.

    Fail posture (gate reads fail CLOSED on bad reads):
    - SMM dir unresolvable -> return None (allow); a missing SMM must never
      block a legitimate close.
    - Sprint missing or with no closing story -> BLOCK; no legit close exists.
    - Sprint present but corrupt/unparseable -> BLOCK (fail closed); the
      corruption is not swallowed into an allow.

    Known residual: `closing` is a singleton, but a lead manually driving a
    raw /xp-story-close of a DIFFERENT story while one story is legitimately
    closing would pass. Bounded by the singleton lock (at most one closing
    story) and far narrower than the prior session-scoped signal.
    """
    if _common.is_xp_agent(input_data):
        return None
    skill = input_data.get("tool_input", {}).get("skill", "")
    bare = target_routing.strip_our_namespace(skill)
    if bare != "xp-story-close":
        return None
    resolved_smm_dir = _common.get_validated_smm_dir(smm_dir)
    if resolved_smm_dir is None:
        return None
    try:
        has_closing = sprint_state.has_closing_stories(resolved_smm_dir)
    except (sprint_store.SprintCorruptError, OSError):
        return _ACCEPT_EVIDENCE_BLOCK
    return None if has_closing else _ACCEPT_EVIDENCE_BLOCK


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
    accept_block = accept_evidence_block_reason(input_data)
    if accept_block:
        _common.block_output(accept_block, "Story close blocked: no accept evidence.")
        sys.exit(0)
    result = run(input_data)
    if result:
        _common.hook_output("PreToolUse", result)
    sys.exit(0)

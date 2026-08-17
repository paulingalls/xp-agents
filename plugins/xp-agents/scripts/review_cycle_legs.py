#!/usr/bin/env python3
"""The review-cycle legs of the SubagentStop hook — which completion means
which flag, and what a finished quality review records.

Extracted from `subagent_stop.py` when it crossed the 450-line band and the
prose floor together. That module dispatches many unrelated completions
(housekeeper, sprint reviewer, plan reviewer, conflict detection); this one
answers a single question — what the review cycle learns when a subagent
finishes — and the reasoning it has to carry about WHICH events fire at
completion is most of its length.

The rule the whole file rests on: SubagentStop fires when a subagent has
actually FINISHED, and it is the only event in the review family that does.
The PostToolUse siblings in `review_cycle_done.py` fire when a tool CALL
returns, which is at launch for an inline skill and equally at launch for an
Agent-tool subagent, because this harness backgrounds them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import identity
import review_records
import target_routing
from event_schema import STATUS_ACTION_QR_COMPLETE

# The share of the SubagentStop budget the coverage scan may spend. hooks.json
# gives this handler 5000ms TOTAL, and `commits._run_git` bounds each call, not
# the set — so the three legs the scan runs would allow 15s and get the handler
# killed part-way. What is left over pays for the two marker writes and the
# event append that follow the scan, which is why this is not the whole budget.
# Kept here rather than in `commits`: the number is a property of THIS hook's
# registration, and `commits` serves callers with no budget at all.
_SCAN_BUDGET_S = 3.0


def _is_code_review(name: str) -> bool:
    """True for the built-in /code-review skill, but NOT our own
    xp-code-reviewer agent (which also contains the substring "code-review").
    Also rejects third-party plugin qualified forms (`otherplugin:code-review`).

    Kept substring-based on the bare/our-namespace form because `agent_id`
    legitimately carries prefix-style instance identifiers like
    `code-review-reuse-1` (pinned by test_code_review_agent_id_sets_flag).
    """
    bare = target_routing.strip_our_namespace(name)
    if bare is None:
        return False
    return "code-review" in bare and "code-reviewer" not in bare


_CODE_REVIEWER_BARE_NAMES: frozenset[str] = frozenset({"xp-code-reviewer"})


def _is_code_reviewer(name: str) -> bool:
    """True only for our xp-code-reviewer agent, bare or our-plugin qualified.

    Exact match, like `_is_quality_review` and for the same reason: a future
    `xp-code-reviewer-helper` must not clear the commit gate. Note the sibling
    `_is_code_review` EXCLUDES this name — it answers a different question
    (did /code-review run) and routing the reviewer there would clear the half
    of the cycle that belongs to a workflow which may never have run.

    Both callers pass `agent_type` and `agent_id`, but `agent_type` is the one
    that fires: every proven sibling handler here matches on it alone, and
    `_is_code_review`'s docstring records that `agent_id` carries instance
    suffixes, which exact match rejects. The `agent_id` disjunct is a latent
    belt for a harness that fills it and leaves `agent_type` empty — not a
    second guard, and not what keeps a helper name out.
    """
    bare = target_routing.strip_our_namespace(name)
    if bare is None:
        return False
    return bare in _CODE_REVIEWER_BARE_NAMES


_QUALITY_REVIEW_BARE_NAMES: frozenset[str] = frozenset({"xp-quality-review"})


def _is_quality_review(name: str) -> bool:
    """True only for the canonical xp-quality-review name (bare or our-plugin
    qualified). Exact-match allowlist — closes both `xp-quality-reviewer*`
    AND `xp-quality-review-*` helper families by construction. The narrower
    `not in name` guard (used by `_is_code_review`) couldn't distinguish
    `xp-quality-review-helper` from a legitimate instance id, so we exit
    that pattern here. No production caller passes a quality-review instance
    id (no test pins one), so exact-match loses nothing today.
    """
    bare = target_routing.strip_our_namespace(name)
    if bare is None:
        return False
    return bare in _QUALITY_REVIEW_BARE_NAMES


def update_review_cycle_flags(smm_dir: Path, input_data: dict) -> None:
    """Set review cycle flags from a subagent's COMPLETION.

    Deliberately not recursion-skipped: the names it matches are xp-* ones.

    This event is the only one in the review family that fires when work has
    actually FINISHED, which is why the flag the commit gate reads is set from
    here. Its PostToolUse sibling fires when a tool CALL returns — at launch for
    an inline skill, and equally at launch for an Agent-tool subagent, which
    this harness backgrounds.

    Three legs, one live. The xp-code-reviewer leg below runs on every quality
    review. The other two are latent on today's Claude payloads and kept for
    the harnesses where they are not: the /xp-quality-review one while that
    skill is inline (an inline skill is not a subagent), the /code-review one
    because its workflow subagents arrive as agent_type `workflow-subagent`
    with an opaque agent_id (measured 2026-08-14), matching neither field —
    `simplify_done` is set by the PostToolUse sibling meanwhile, and that
    launch timing is depended on.
    """
    agent_type = input_data.get("agent_type", "").lower()
    agent_id_val = input_data.get("agent_id", "").lower()

    cwd = input_data.get("cwd", "")

    # The LIVE leg, and the only signal in this family that fires when a review
    # has actually happened. Its own function because it does two writes and
    # emits the lifecycle event, where the latent legs below only set a flag.
    if _is_code_reviewer(agent_type) or _is_code_reviewer(agent_id_val):
        _record_completed_quality_review(smm_dir, cwd, input_data)
        return

    flag: str | None = None
    if _is_code_review(agent_type) or _is_code_review(agent_id_val):
        flag = "simplify_done"
    elif _is_quality_review(agent_type) or _is_quality_review(agent_id_val):
        flag = "quality_review_done"

    if flag is not None:
        review_records.set_review_flag(smm_dir, identity.review_flags_key(cwd), flag)


def _record_completed_quality_review(smm_dir: Path, cwd: str, input_data: dict) -> None:
    """A finished xp-code-reviewer: raise the flag, record what it covered.

    Both writes belong HERE rather than on the PostToolUse:Agent sibling,
    because this harness backgrounds Agent-tool subagents: that hook fires when
    the tool CALL returns, which is at launch. Measured 2026-08-15 — the
    reviewer's own start event was stamped 70ms after the qr_complete the
    sibling emitted for it. Keying on the Agent tool moved the defect from
    skill-launch to agent-launch rather than removing it.

    The COVERAGE has to be written at completion for a second reason: the
    reviewer's fixes are in the working tree by now, and at launch they did not
    exist. Recorded at launch the set would omit exactly the files it exists to
    forgive.

    UNSTAGED IS THE POINT, not an extra. A reviewer edits files and returns;
    nothing stages them. v5.17.0 asked for the default scan, which reads staged
    + committed only, so in the dominant flow it recorded an EMPTY set and the
    fix it shipped did nothing — the next `git add -A && git commit` counted
    the reviewer's own fixes unreviewed and demanded another review. Widening
    is also the honest scope rather than a loosening: the diff the review was
    handed is the working tree's (`git diff HEAD`, staged and unstaged both),
    so the narrower set claimed less than was actually looked at.

    Keyed on the repo, like the watermark, because the paths are repo-relative.
    `commits` is imported lazily — every subagent completion reaches this
    module, only this one needs git.

    ORDER: the two git reads run FIRST and the flag last, so an interrupt
    between them leaves the gate armed rather than cleared — the same direction
    `review_records.end_review_cycle` fails in, for the same reason. Reversed,
    the interrupted state is the very one this release exists to remove: the
    flag raised, no coverage, and the reviewer's own fixes re-arming the gate.
    """
    import commits

    repo_key = identity.review_watermark_key(cwd)
    watermark = review_records.read_review_watermark(smm_dir, repo_key)
    scope = commits.get_code_files_for_review(
        cwd, watermark, include_unstaged=True, scan_budget_s=_SCAN_BUDGET_S
    )
    review_records.write_review_coverage(smm_dir, repo_key, scope)
    review_records.set_review_flag(
        smm_dir, identity.review_flags_key(cwd), "quality_review_done"
    )
    _common.append_safe(
        smm_dir,
        _common.make_event(
            _common.STATUS,
            identity.resolve_agent_id(input_data),
            "Quality review complete",
            working_on=[],
            metadata={"action": STATUS_ACTION_QR_COMPLETE},
        ),
    )

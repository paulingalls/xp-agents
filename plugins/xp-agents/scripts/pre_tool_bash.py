#!/usr/bin/env python3
"""PreToolUse hook for Bash: commit-time review/security/lint gates +
cd-into-worktree-git advisory + decision-time SMM nudges.

No file-modification coordination gate — `pre_tool_write` covers Edit/Write
and trust+merge handles cross-agent Bash file-mods at story-close (see
sprint-105 decision). The shlex-based detector that previously lived here
was unsound; bash isn't statically parseable.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import identity
import markers
import pre_tool_bash_branch_delete
import pre_tool_bash_commit_gates
import pre_tool_bash_reviewer_guard
import resolution
import story_done_gate
from event_schema import METADATA_KEY_RESOLVES, METADATA_KEY_SUPERSEDES

# The gate entry point; canonical home is pre_tool_bash_branch_delete (moved
# there to keep this module under the 500-line cap). A local alias, not a
# compatibility shim: `run` below calls it by this short name. Nothing outside
# this file reaches a moved symbol through `pre_tool_bash`, which is why the
# commit-gate module carries no alias at all.
_unmerged_story_branch_delete_block = (
    pre_tool_bash_branch_delete._unmerged_story_branch_delete_block
)

# ---------------------------------------------------------------------------
# cd-into-worktree-then-git advisory
# ---------------------------------------------------------------------------

# Re-exported so tests can pin the constant; canonical home is identity.
WORKTREE_PATH_FRAGMENT = identity.WORKTREE_PATH_FRAGMENT

# Location-independent: key on the teammate worktree SEGMENT
# (`worktree-story-…`) rather than the legacy `.claude/worktrees/` parent, so the
# advisory fires for BOTH the in-repo placement and the out-of-repo
# `{project-id}/worktrees/` one (story-024) — the cwd poisoning it guards is the
# same wherever the worktree lives. Single non-greedy `[^\n]*?` — one quantifier,
# no nesting — avoids catastrophic backtracking when the trailing `git` never
# appears.
_CD_WORKTREE_GIT_PATTERN = re.compile(
    r"cd\s+\S*"
    + re.escape(identity._TEAMMATE_PREFIX)
    + r"\S+"
    + r"[^\n]*?\bgit\s+(?:commit|add|merge|push)\b"
)

_CD_WORKTREE_GIT_WARNING = (
    "Avoid `cd <worktree> && git ...` — it poisons the orchestrator's cwd, "
    "so the PostToolUse trailer-extract reads the wrong HEAD and "
    "Resolves-Event auto-link silently breaks. Use "
    "`git -C /abs/path/to/worktree ...` instead — a literal path, not a shell "
    "variable: this hook cannot expand one, and a commit whose `-C` target it "
    "cannot resolve is refused."
)

# Recognizing a mark-done INVOCATION lives with the gate it feeds
# (story_done_gate.mark_done_invocations), not here: what counts as marking a story
# done is a property of the gate, and the ACCEPT gate below reads the same answer.

# ---------------------------------------------------------------------------
# Decision-time open-questions nudge
# ---------------------------------------------------------------------------

_QUESTION_CONTENT_LIMIT = 80
_MAX_NUDGE_FIRES = 2


def _open_questions_context(
    smm_dir: Path, agent_id: str, events: list[dict], resolutions: dict
) -> str | None:
    """Build a nudge listing open questions, or None when none remain.

    Tracks per-(question_id, agent_id) fire count via QUESTION_NUDGED marker;
    after _MAX_NUDGE_FIRES fires, that question is muted for this agent.
    """
    if not events:
        return None
    answered = resolutions["answered_question_ids"]

    fire_counts: dict[str, int] = {}
    marker_data = markers.marker_read(smm_dir, markers.QUESTION_NUDGED, agent_id)
    if isinstance(marker_data, dict):
        fire_counts = {k: v for k, v in marker_data.items() if isinstance(v, int)}

    lines: list[str] = []
    counts_changed = False
    for e in events:
        if e.get("type") != _common.QUESTION:
            continue
        qid = e.get("id", "")
        if not qid or qid in answered:
            continue
        count = fire_counts.get(qid, 0)
        if count >= _MAX_NUDGE_FIRES:
            continue
        topic = e.get("topic", "") or "no-topic"
        content = e.get("content", "")[:_QUESTION_CONTENT_LIMIT]
        lines.append(f"{qid} ({topic}): {content}")
        fire_counts[qid] = count + 1
        counts_changed = True

    if counts_changed:
        markers.marker_write(smm_dir, markers.QUESTION_NUDGED, fire_counts, agent_id)

    if not lines:
        return None
    header = (
        "Open questions — consider resolving this decision with "
        "--metadata '{\"resolves\":[...]}':"
    )
    return header + "\n" + "\n".join(lines)


def _parse_metadata_dict(metadata_value: str) -> dict | None:
    """Parse the --metadata JSON string into a dict; None on absent/invalid."""
    if not metadata_value:
        return None
    try:
        parsed = json.loads(metadata_value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _decision_metadata_has_resolves(metadata_value: str) -> bool:
    """True when the --metadata JSON carries a non-empty resolves array."""
    parsed = _parse_metadata_dict(metadata_value)
    return bool(parsed and parsed.get(METADATA_KEY_RESOLVES))


def _decision_metadata_declares_supersedence(metadata_value: str) -> bool:
    """True when --metadata declares supersedes OR resolves of any prior id.

    The supersession nudge fires only when the planner has NOT declared
    supersedence yet — either key (supersedes for flag-suppression, or
    resolves for cascade-closure) counts as a declaration. Mirrors the
    skip-condition in concern_conflicts.py's superseded-decision detector,
    which treats both keys as supersedence declarations.
    """
    parsed = _parse_metadata_dict(metadata_value)
    if not parsed:
        return False
    return bool(
        parsed.get(METADATA_KEY_RESOLVES) or parsed.get(METADATA_KEY_SUPERSEDES)
    )


_SAME_TOPIC_HEADER_TEMPLATE = (
    "Same-topic precedent — topic '{topic}' has unresolved prior "
    "decision(s). If this new decision supersedes one, add "
    '--metadata \'{{"supersedes":["<id>"]}}\' (declares explicit '
    "supersedence; suppresses any same-session flag) or "
    '\'{{"resolves":["<id>"]}}\' (also cascade-closes the prior):'
)


def _same_topic_decisions_context(
    topic: str, events: list[dict], resolutions: dict
) -> str | None:
    """Build a nudge listing unresolved decisions on the same topic, or None.

    Catches silent decision-supersession: planner emits a new decision on
    a topic that already has an open prior decision. The cascade can't
    close any future superseded-decision flag concern unless the planner
    explicitly declares supersedence; this nudge reminds them at the
    moment they're about to write the new decision.
    """
    if not topic or not events:
        return None
    if topic in concerns.SUPERSEDED_DECISION_EXEMPT_TOPICS:
        return None
    resolved = resolution.collect_all_resolved_ids(resolutions)

    lines: list[str] = []
    for e in events:
        if e.get("type") != _common.DECISION:
            continue
        if e.get("topic", "") != topic:
            continue
        did = e.get("id", "")
        if not did or did in resolved:
            continue
        content = e.get("content", "")[:_QUESTION_CONTENT_LIMIT]
        lines.append(f"{did}: {content}")

    if not lines:
        return None
    header = _SAME_TOPIC_HEADER_TEMPLATE.format(topic=topic)
    return header + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core logic. Returns additionalContext string or None. Raises BlockedError."""
    # Reviewer read-only guard — deliberately ABOVE the is_xp_agent skip. Both
    # guarded agents ARE xp- agents, so a guard anywhere below this line would
    # never be reached and would ship inert. The narrow exception to
    # recursion-prevention is safe because this guard forks no agent and reaches
    # no hook — it only reads the payload it was handed and refuses — so there is
    # no recursion path to prevent. It also sits above get_validated_smm_dir
    # because it needs no SMM: the reviewer contract holds whether or not the
    # project has one, and making enforcement conditional on SMM presence would
    # silently disarm it exactly where state is least well tracked.
    reviewer_block = pre_tool_bash_reviewer_guard.reviewer_mutation_block(input_data)
    if reviewer_block:
        raise _common.BlockedError(
            reviewer_block,
            "Reviewer must not mutate git state — inspection is read-only.",
        )

    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)

    tool_input = input_data.get("tool_input", {})
    agent_id = identity.resolve_agent_id(input_data)
    cwd = input_data.get("cwd", ".")
    command = tool_input.get("command", "")

    parts: list[str] = []

    if smm_dir is not None:
        parts.extend(
            pre_tool_bash_commit_gates.commit_gate_parts(
                smm_dir, command, cwd, agent_id
            )
        )

    mark_done = story_done_gate.mark_done_invocations(command)

    if (
        smm_dir is not None
        and mark_done
        and markers.marker_exists(smm_dir, markers.ACCEPT)
    ):
        raise _common.BlockedError(
            "Run /xp-accept to verify acceptance criteria before marking stories done.",
            "Acceptance verification required.",
        )

    # The merge gate. The ACCEPT marker above cannot cover this: /xp-accept's own
    # preload CONSUMES that marker at the start of the run, long before the close
    # merges — so by mark-done time it is gone. This gate is state-derived and
    # evaluated at the instant of mark-done, which is the only moment the answer
    # ("did the merge actually land?") is knowable.
    #
    # `cwd`, not the commit path's effective_cwd: a mark-done command carries no
    # `git -C <path>` prefix to unwrap, and this is the orchestrator's repo, which is
    # where the story's branch and its base actually live.
    if smm_dir is not None:
        for story_id, forced in mark_done:
            if forced:
                continue  # on the record — the CLI writes the debt event
            block = story_done_gate.merged_block(smm_dir, cwd, story_id)
            if block:
                raise _common.BlockedError(
                    f"Refusing to mark {story_id} done: {block}",
                    "Merge not verified — the story's work is not on its base branch.",
                )

    if smm_dir is not None:
        delete_block = _unmerged_story_branch_delete_block(smm_dir, cwd, command)
        if delete_block:
            raise _common.BlockedError(
                delete_block,
                "Unmerged story-branch delete refused — absence must imply merged.",
            )

    if smm_dir is not None:
        args = _common.parse_append_sh_args(command)
        if args.get("type") == _common.DECISION:
            metadata = args.get("metadata", "")
            events, resolutions = _common.load_events_with_resolutions(smm_dir)
            if not _decision_metadata_has_resolves(metadata):
                nudge = _open_questions_context(smm_dir, agent_id, events, resolutions)
                if nudge:
                    parts.append(nudge)
            if not _decision_metadata_declares_supersedence(metadata):
                same_topic = _same_topic_decisions_context(
                    args.get("topic", ""), events, resolutions
                )
                if same_topic:
                    parts.append(same_topic)

    # cd-into-worktree-then-git — advisory only, never blocks
    if _CD_WORKTREE_GIT_PATTERN.search(command):
        parts.append(_CD_WORKTREE_GIT_WARNING)

    # No pre-tool Bash file-modification coordination gate: pre_tool_write
    # handles Edit/Write (the common case), and CLI teammates run in isolated
    # git worktrees so cross-agent damage from `mv`/`sed -i`/redirects only
    # materializes at story-close merge where git is the deterministic safety
    # net. A shlex-based detector that previously lived here was unsound
    # (bash isn't statically parseable); trust+merge is the honest model.

    if not parts:
        return None

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    try:
        result = run(input_data)
    except _common.BlockedError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    if result:
        _common.hook_output("PreToolUse", result)

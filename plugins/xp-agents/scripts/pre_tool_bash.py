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
import branching
import commits
import concerns
import git_commits
import identity
import markers
import pre_tool_bash_branch_delete
import pre_tool_bash_reviewer_guard
import resolution
import security_patterns
import security_scanner
import staged_lint
import story_done_gate
from event_schema import METADATA_KEY_RESOLVES, METADATA_KEY_SUPERSEDES

# The gate entry point; canonical home is pre_tool_bash_branch_delete (moved
# there to keep this module under the 500-line cap).
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
    "Resolves-Event auto-link silently breaks. Use `git -C <worktree> ...` instead."
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
    skip-condition in concerns.py's superseded-decision detector, which
    treats both keys as supersedence declarations.
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
# Verify-touch nudge
# ---------------------------------------------------------------------------


def _verify_touch_nudge(
    smm_dir: Path, effective_cwd: str, command: str, branch: str
) -> str | None:
    """Advisory when the active story's declared verify paths are untouched.

    Fails open at every step — this is a nudge, never a block. Suppressed by
    a [verify-deferred] commit (which records its own debt post-commit) and
    silent off a story branch, when the story declares no verify paths, when
    every path is already touched, or when git can't be read.

    verify_deferred is imported lazily (not top-level): pre_tool_bash loads on
    every Bash call, but only commits reach this helper, so we avoid pulling
    the post-commit dependency tree into the common path.
    """
    from verify_deferred import parse_verify_deferred, untouched_paths_for_story

    if parse_verify_deferred(commits.extract_commit_message(command)) is not None:
        return None
    story_id = identity.extract_story_id(branch)
    if not story_id:
        return None
    untouched = untouched_paths_for_story(smm_dir, effective_cwd, story_id)
    if not untouched:
        return None
    return (
        "Verify-touch advisory: no commit on this branch touches the declared "
        "acceptance-test path(s): " + ", ".join(untouched) + ". Touch them, or "
        "commit with [verify-deferred] <reason> to defer (records a debt)."
    )


# ---------------------------------------------------------------------------
# Unmerged story-branch delete refusal
# ---------------------------------------------------------------------------
# Moved to pre_tool_bash_branch_delete.py (500-line cap); re-exported above via
# identity import so `pre_tool_bash.X IS pre_tool_bash_branch_delete.X` for
# every moved symbol and existing mock.patch("...pre_tool_bash.X") sites keep
# working with zero edits.


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

    # Commit gate: review cycle + tier-1 security + lint. Below the
    # 3+ code-files threshold there is no per-commit security gate
    # (close-skill Step 4 covers the cumulative diff at close).
    if smm_dir is not None and git_commits.is_git_commit(command):
        # EVERY git read below runs in the repo the commit will land in, not in the
        # hook's own cwd. `git -C <worktree> commit` (the form this project tells
        # agents to prefer over `cd`) stages nothing in the main checkout, so a raw
        # `cwd` makes `git diff --cached` come back empty — and an empty diff is not
        # a blocked commit, it is a SILENT one: the tier-1 scan has nothing to scan
        # and the lint gate has no files to group. Both gates no-op, unlinted and
        # unscanned bytes ship, and nothing says so. Parse the target once, here,
        # above the first read.
        effective_cwd = commits.parse_effective_cwd(command, cwd)

        # Tier 1 fires before the review-cycle gate so deterministic
        # patterns block even when /code-review and /xp-quality-review are done.
        diff = commits.get_staged_diff(effective_cwd)
        if diff is None:
            raise _common.BlockedError(
                "Tier 1 security scan could not run: `git diff --cached` failed. "
                "Resolve and retry the commit.",
                "Tier 1 fail-closed: git diff failure.",
            )
        if diff:
            findings = security_scanner.scan_diff(diff, security_patterns.V3_0_PATTERNS)
            if findings:
                lines = [
                    f"  - {f.pattern_name} at {f.file_path}:{f.line_number}"
                    for f in findings
                ]
                raise _common.BlockedError(
                    "\n".join(
                        [
                            "Tier 1 security scan blocked this commit:",
                            *lines,
                            "",
                            "Fix the flagged lines or add `# noqa: secret`.",
                        ]
                    ),
                    "Tier 1 security pattern detected.",
                )

        # Single name-only call shared by the lint gate and downstream
        # checks — one fork instead of two.
        staged = commits.get_staged_files(effective_cwd)

        parts.extend(staged_lint.staged_lint_gate(staged, effective_cwd))

        cycle = markers.read_review_cycle(smm_dir, agent_id)
        code_files = commits.get_code_files_for_review(
            effective_cwd,
            cycle.get("last_review_commit", ""),
            command,
            staged_diff=diff,
        )

        if len(code_files) >= commits.REVIEW_CYCLE_THRESHOLD:
            if markers.read_review_cadence(smm_dir) == "story":
                # Story cadence: review relocates to /xp-story-close (merge).
                # Emit a visible deferral advisory instead of blocking — the
                # tier-1 security and lint gates above stay unconditional.
                parts.append(
                    f"Story cadence: per-commit review deferred to "
                    f"/xp-story-close ({len(code_files)} code files changed "
                    f"since last review). /xp-quality-review runs at story "
                    f"close."
                )
            elif not cycle.get("quality_review_done"):
                # Per-increment review is /xp-quality-review only — the
                # xp-code-reviewer it spawns self-finds correctness. The
                # workflow /code-review runs once at sprint/plan/free close.
                raise _common.BlockedError(
                    f"Run /xp-quality-review before committing — "
                    f"{len(code_files)} code files changed since last review.",
                    "Quality review required before committing.",
                )

        stage = branching.get_branching_stage(smm_dir)
        if stage >= 1:
            branch = identity.get_current_branch(effective_cwd)
            is_escape = commits.is_escape_hatch_commit(command)
            if branching.is_protected_branch(stage, branch, smm_dir) and not is_escape:
                parts.append(
                    f"You're committing directly to {branch} "
                    f"(branching stage {stage}). Use a story branch, or prefix "
                    f"with [release]/[chore]/[sprint-direct] for legitimate "
                    f"main commits."
                )
            elif stage >= 2 and branching.is_sprint_branch(branch) and not is_escape:
                parts.append(
                    f"You're committing directly to sprint branch {branch}. "
                    f"Sprint branches accept merges only. Use a story branch, "
                    f"or prefix with [release]/[chore]/[sprint-direct] for "
                    f"legitimate post-merge work."
                )

            nudge = _verify_touch_nudge(smm_dir, effective_cwd, command, branch)
            if nudge:
                parts.append(nudge)

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

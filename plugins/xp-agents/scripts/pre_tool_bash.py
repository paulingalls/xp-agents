#!/usr/bin/env python3
"""PreToolUse hook for Bash: commit security gate + file-modification detection."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import branching
import commits
import coordination
import identity
import markers
import resolves_probe
import security
import security_patterns
import security_scanner
import story_probe
import worktree
from event_schema import METADATA_KEY_RESOLVES

# ---------------------------------------------------------------------------
# Bash file-modification heuristic
# ---------------------------------------------------------------------------

_FILE_MODIFY_PATTERNS = [
    re.compile(r">\s*(\S+)"),  # redirect: echo > file
    re.compile(r"tee\s+(\S+)"),  # tee file
    re.compile(r"sed\s+-i\S*\s+\S+\s+(\S+)"),  # sed -i expr file
    re.compile(r"mv\s+\S+\s+(\S+)"),  # mv src dest
    re.compile(r"cp\s+\S+\s+(\S+)"),  # cp src dest
]


def detect_bash_target_files(command: str) -> list[str]:
    """Best-effort extraction of files a Bash command might modify."""
    files = []
    for pattern in _FILE_MODIFY_PATTERNS:
        for match in pattern.finditer(command):
            f = match.group(1)
            if f and not f.startswith("-"):
                files.append(f)
    return files


# ---------------------------------------------------------------------------
# Decision-time open-questions nudge
# ---------------------------------------------------------------------------

_QUESTION_CONTENT_LIMIT = 80
_MAX_NUDGE_FIRES = 2


def _open_questions_context(smm_dir: Path, agent_id: str) -> str | None:
    """Build a nudge listing open questions, or None when none remain.

    Tracks per-(question_id, agent_id) fire count via QUESTION_NUDGED marker.
    After _MAX_NUDGE_FIRES fires, that question is muted for this agent.
    """
    events, resolutions = _common.load_events_with_resolutions(smm_dir)
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


def _decision_metadata_has_resolves(metadata_value: str) -> bool:
    """True when the --metadata JSON carries a non-empty resolves array."""
    if not metadata_value:
        return False
    try:
        parsed = json.loads(metadata_value)
    except ValueError:
        return False
    return bool(isinstance(parsed, dict) and parsed.get(METADATA_KEY_RESOLVES))


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core logic. Returns additionalContext string or None. Raises BlockedError."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)

    tool_input = input_data.get("tool_input", {})
    agent_id = identity.resolve_agent_id(input_data)
    cwd = input_data.get("cwd", ".")
    command = tool_input.get("command", "")

    parts: list[str] = []

    # Commit gate: review cycle enforcement
    # Above threshold (3+ code files): simplify → quality review → security triage
    # Below threshold: security triage only for production code commits
    if smm_dir is not None and security.is_git_commit(command):
        # Tier 1 fires before the review-cycle gate so deterministic patterns
        # block even when /simplify, /xp-quality-review, /xp-security-triage
        # have all been satisfied.
        diff = commits.get_staged_diff(cwd)
        if diff is None:
            raise _common.BlockedError(
                "Tier 1 security scan could not run: `git diff --cached`"
                " failed. Resolve the git issue and retry the commit.",
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
                            "Fix the flagged lines or add `# noqa: secret`"
                            " on each intentional line.",
                        ]
                    ),
                    "Tier 1 security pattern detected.",
                )

        cycle = markers.read_review_cycle(smm_dir, agent_id)
        code_files = commits.get_code_files_for_review(
            cwd,
            cycle.get("last_review_commit", ""),
            command,
            staged_diff=diff,
        )

        if len(code_files) >= commits.REVIEW_CYCLE_THRESHOLD:
            if not cycle.get("simplify_done"):
                raise _common.BlockedError(
                    f"Run /simplify before committing — "
                    f"{len(code_files)} code files changed since last review.",
                    "Simplify required before committing.",
                )
            elif not cycle.get("quality_review_done"):
                raise _common.BlockedError(
                    "Run /xp-quality-review before committing.",
                    "Quality review required before committing.",
                )
            elif not cycle.get("security_review_done"):
                raise _common.BlockedError(
                    "Run /xp-security-triage before committing.",
                    "Security triage required before committing.",
                )
        elif not security.security_triaged_exists(smm_dir, agent_id):
            has_code = security.has_staged_code_files(cwd, command, staged_diff=diff)
            if has_code:
                raise _common.BlockedError(
                    "Run /xp-security-triage before committing.",
                    "Security triage required before committing.",
                )
            else:
                security.write_security_triaged(
                    smm_dir, agent_id, exempt_reason="no-code-files"
                )

        stage = branching.get_branching_stage(smm_dir)
        if stage >= 1:
            branch = identity.get_current_branch(cwd)
            is_escape = commits.is_escape_hatch_commit(command)
            if branching.is_protected_branch(stage, branch) and not is_escape:
                parts.append(
                    f"You're committing directly to {branch} "
                    f"(branching stage {stage}). Use a story "
                    f"branch, or prefix with [release]/[chore] "
                    f"for legitimate main commits."
                )
            elif stage >= 2 and branching.is_sprint_branch(branch) and not is_escape:
                parts.append(
                    f"You're committing directly to sprint branch "
                    f"{branch}. Sprint branches accept merges "
                    f"only. Use a story branch, or prefix with "
                    f"[release]/[chore] for legitimate post-merge work."
                )

        staged = commits.get_staged_files(cwd)
        if staged:
            msg = commits.extract_commit_message(command)
            already_resolved: list[str] = []
            has_trailer = False
            if msg:
                already_resolved, _, has_trailer = commits.extract_resolves_trailer(msg)
            story_candidate = story_probe.find_story_candidate(
                smm_dir, cwd, staged, msg or ""
            )
            story_probe.emit_probe_status(smm_dir, story_candidate, agent_id)
            story_nudge = (
                story_probe.build_nudge_line(story_candidate)
                if story_candidate
                else None
            )
            candidates = resolves_probe.find_probe_candidates(
                smm_dir, staged, already_resolved, cwd, commit_message=msg or ""
            )
            if story_nudge:
                parts.append(story_nudge)
            if candidates:
                resolves_probe.emit_probe_status(smm_dir, candidates, agent_id)
                # Concern a47dda9f00bd: advisory nudge → block when no
                # trailer present. `Resolves-Event: none` is the universal
                # escape. Any trailer (even mismatched IDs) is treated as
                # good-faith discharge — we don't compare trailer IDs to
                # candidate IDs because the agent's intent is opaque.
                if not has_trailer:
                    nudge = resolves_probe.build_nudge_lines(candidates)[0]
                    body = (
                        nudge
                        + "\n\n"
                        + resolves_probe.TRAILER_REMINDER
                        + " before re-trying."
                    )
                    if story_nudge:
                        body = story_nudge + "\n\n" + body
                    raise _common.BlockedError(
                        body,
                        "Resolves-Event trailer required:"
                        " open candidates overlap your staged files.",
                    )
            elif not has_trailer:
                parts.append(resolves_probe.TRAILER_REMINDER + ".")

    if (
        smm_dir is not None
        and re.search(r"update-story\s+\S+\s+done\b", command)
        and markers.marker_exists(smm_dir, markers.ACCEPT)
    ):
        raise _common.BlockedError(
            "Run /xp-accept to verify acceptance criteria before marking stories done.",
            "Acceptance verification required.",
        )

    if smm_dir is not None:
        args = _common.parse_append_sh_args(command)
        if args.get("type") == _common.DECISION and not _decision_metadata_has_resolves(
            args.get("metadata", "")
        ):
            nudge = _open_questions_context(smm_dir, agent_id)
            if nudge:
                parts.append(nudge)

    # File-modification heuristic — advisory only, never blocks
    if smm_dir is not None:
        target_files = detect_bash_target_files(command)
        if target_files:
            coord_data = coordination.read_coordination(smm_dir)
            for target_file in target_files:
                normalized_target = worktree.normalize_path(target_file, cwd)
                for aid, entry in coord_data.items():
                    if aid == agent_id:
                        continue
                    for f in entry.get("working_on", []):
                        try:
                            if worktree.normalize_path(f, cwd) == normalized_target:
                                parts.append(
                                    f"Advisory: Agent '{aid}' may be working on "
                                    f"'{target_file}'. Coordinate before modifying."
                                )
                        except (ValueError, OSError):
                            continue

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

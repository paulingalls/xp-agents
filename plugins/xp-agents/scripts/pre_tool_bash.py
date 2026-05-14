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
import git_commits
import identity
import lint_check
import markers
import resolution
import resolves_probe
import security_patterns
import security_scanner
import story_probe
import worktree
from event_schema import METADATA_KEY_RESOLVES, METADATA_KEY_SUPERSEDES

# ---------------------------------------------------------------------------
# Bash file-modification heuristic
# ---------------------------------------------------------------------------

_FILE_MODIFY_PATTERNS = [
    re.compile(r">\s*(\S+)"),  # echo > file
    re.compile(r"tee\s+(\S+)"),
    re.compile(r"sed\s+-i\S*\s+\S+\s+(\S+)"),
    re.compile(r"mv\s+\S+\s+(\S+)"),
    re.compile(r"cp\s+\S+\s+(\S+)"),
]

# ---------------------------------------------------------------------------
# cd-into-worktree-then-git advisory
# ---------------------------------------------------------------------------

# Re-exported so tests can pin the constant; canonical home is identity.
WORKTREE_PATH_FRAGMENT = identity.WORKTREE_PATH_FRAGMENT

# Single non-greedy `[^\n]*?` — one quantifier, no nesting — avoids
# catastrophic backtracking when the trailing `git` never appears.
_CD_WORKTREE_GIT_PATTERN = re.compile(
    r"cd\s+\S*"
    + re.escape(WORKTREE_PATH_FRAGMENT)
    + r"\S+"
    + r"[^\n]*?\bgit\s+(?:commit|add|merge|push)\b"
)

_CD_WORKTREE_GIT_WARNING = (
    "Avoid `cd <worktree> && git ...` — it poisons the orchestrator's cwd, "
    "so the PostToolUse trailer-extract reads the wrong HEAD and "
    "Resolves-Event auto-link silently breaks. Use `git -C <worktree> ...` instead."
)


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
    skip-condition in concerns.py's superseded-decision detector
    (which checks metadata.supersedes for the explicit override).
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
# Staged ruff gate
# ---------------------------------------------------------------------------


def _staged_ruff_findings(
    staged_files: list[str], cwd: str
) -> list[tuple[str, list[str]]]:
    """Run staging-context ruff over each staged .py file.

    Returns [(path, codes), ...] for files with non-empty findings, narrowed
    to lint_check.EDIT_DEFERRED_CODES (F401/F811). Other ruff codes already
    surface as concerns at edit time — do NOT broaden the commit-time block
    beyond the deferral policy. ``staged_files`` is reused from the caller to
    avoid a second `git diff --cached --name-only` invocation
    (invariant: `test_common_path_at_most_one_name_only_call`).

    Fail-closed when the batch is missing any staged .py path so unverified
    F401/F811 cannot ship.
    """
    py_paths = [p for p in staged_files if p.endswith(".py")]
    if not py_paths:
        return []
    per_file = lint_check.run_linter_batch("ruff", py_paths, context="staging", cwd=cwd)
    missing = [p for p in py_paths if p not in per_file]
    if missing:
        raise _common.BlockedError(
            "\n".join(
                [
                    "Staged ruff check could not verify these files:",
                    *(f"  - {p}" for p in missing),
                    "",
                    "Resolve (ruff on PATH? timeout?) and retry the commit.",
                ]
            ),
            "Staged ruff fail-closed: incomplete batch coverage.",
        )
    findings: list[tuple[str, list[str]]] = []
    for path in py_paths:
        codes = per_file.get(path, [])
        deferred = [c for c in codes if c in lint_check.EDIT_DEFERRED_CODES]
        if deferred:
            findings.append((path, deferred))
    return findings


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

    # Commit gate: review cycle + tier-1 security + ruff. Below the
    # 3+ code-files threshold there is no per-commit security gate
    # (close-skill Step 4 covers the cumulative diff at close).
    if smm_dir is not None and git_commits.is_git_commit(command):
        # Tier 1 fires before the review-cycle gate so deterministic
        # patterns block even when /simplify and /xp-quality-review are done.
        diff = commits.get_staged_diff(cwd)
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

        # Single name-only call shared by the ruff gate, the probe, and
        # the trailer reminder — one fork instead of three.
        staged = commits.get_staged_files(cwd)

        ruff_findings = _staged_ruff_findings(staged, cwd)
        if ruff_findings:
            raise _common.BlockedError(
                "\n".join(
                    [
                        "Staged ruff check blocked this commit:",
                        *(f"  - {p}: {', '.join(codes)}" for p, codes in ruff_findings),
                        "",
                        "Fix the flagged imports/redefinitions, or unstage the file.",
                    ]
                ),
                "Ruff F401/F811 detected on staged files.",
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

        stage = branching.get_branching_stage(smm_dir)
        if stage >= 1:
            # `git -C <path>` retargets cwd — branch-check the named path.
            branch = identity.get_current_branch(
                commits.parse_effective_cwd(command, cwd)
            )
            is_escape = commits.is_escape_hatch_commit(command)
            if branching.is_protected_branch(stage, branch) and not is_escape:
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
            probe_meta: dict = {}
            candidates = resolves_probe.find_probe_candidates(
                smm_dir,
                staged,
                already_resolved,
                cwd,
                commit_message=msg or "",
                out_meta=probe_meta,
            )
            if story_nudge:
                parts.append(story_nudge)
            # Empty-candidate emit when probe_meta carries snapshot/tail
            # telemetry — diagnostic signal for newer-than-snapshot diverts.
            if candidates or probe_meta:
                resolves_probe.emit_probe_status(
                    smm_dir, candidates, agent_id, probe_meta=probe_meta
                )
            if candidates:
                # Block when no trailer present. `Resolves-Event: none` is the
                # universal escape. Any trailer (even mismatched IDs) is
                # treated as good-faith discharge — the agent's intent is
                # opaque to us.
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

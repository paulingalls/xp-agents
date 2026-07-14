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
import lint_check
import markers
import resolution
import security_patterns
import security_scanner
import worktree
from event_schema import METADATA_KEY_RESOLVES, METADATA_KEY_SUPERSEDES

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
# Staged lint gate
# ---------------------------------------------------------------------------


def _staged_lint_gate(staged_files: list[str], cwd: str) -> None:
    """Commit-time lint gate: unresolved lint blocks the commit.

    Blocks on any finding the linter reports, and fails CLOSED when it could
    not be run at all (binary missing, timeout, or a non-zero exit with nothing
    to say). Those two are DIFFERENT and must stay so: "we could not check" is
    not "we checked and it was clean".

    The gate reports the linter's own output and never interprets it — knowing
    *that* it found something needs only an exit code, while knowing *what* it
    found would need a per-language parser. ``staged_files`` is reused from the
    caller to avoid a second `git diff --cached --name-only` invocation
    (invariant: `test_common_path_at_most_one_name_only_call`).

    KNOWN LIMIT: git names the staged PATHS, but the linter reads those paths off
    the WORKING TREE, so the bytes checked are the working tree's, not the
    index's. They differ only when the two diverge (`git add -p`, or an edit after
    the add) — and then the gate judges content the commit does not carry, in
    either direction. Linting the index needs the staged blobs materialized
    somewhere a linter can resolve per-file config from, which is a design
    problem, not an oversight. Tracked, not hidden.
    """
    # lang-ok: ruff is Python's linter, so selecting Python paths for it is the
    # dispatch, not an assumption about the project. A Rust or JS repo stages no
    # .py files, the list is empty, and the leg no-ops at the next line — that
    # graceful no-op IS the cross-language behavior. Adding another linter means
    # adding its own dispatch beside this one, never widening this filter.
    py_paths = [p for p in staged_files if p.endswith(".py")]
    if not py_paths:
        return
    # git names staged paths relative to the REPO ROOT, so resolve them there and
    # run the linter there — not from the hook's cwd, which is a subdirectory
    # whenever the agent committed from one. Intentionally the repo root and NOT
    # lint_check.lint_invocation_target's config-dir: ruff is a single global PATH
    # binary that resolves config per-file by walking up from each path, so one
    # batch can span subpackages with different configs. The config-dir convention
    # exists for npx-resolved eslint v9 (local binary + cwd-relative flat config),
    # which this leg never runs.
    root = worktree.resolve_git_root(cwd) or cwd
    # Lint only what is actually THERE. A staged DELETION still names its path,
    # and a linter handed a path that is gone reports a read error and exits
    # non-zero — which the exit-code contract would read as a finding, blocking
    # the very commit that removes the file, with nothing the agent could fix.
    # The old parser hid this by accident (it pre-filled every path to [] and the
    # read error's code was outside its F401/F811 allowlist); exit-code
    # classification removes the accident, so the filter must be explicit.
    # Existence is a byte-level fact, not a language one — this stays correct for
    # every linter the later milestones add.
    live_paths = [p for p in py_paths if (Path(root) / p).exists()]
    if not live_paths:
        return
    run = lint_check.run_linter_batch("ruff", live_paths, cwd=root)
    match run.status:
        case "findings":
            raise _common.BlockedError(
                "\n".join(
                    [
                        "Staged lint check blocked this commit:",
                        "",
                        run.output,
                        "",
                        "Fix the findings, or unstage the file.",
                    ]
                ),
                "Lint findings on staged files.",
            )
        case "unverified":
            raise _common.BlockedError(
                "\n".join(
                    [
                        "Staged lint check could not verify the staged files:",
                        f"  {run.output}",
                        "",
                        "A configured linter that cannot run is a bad read, not "
                        "a pass. Resolve and retry the commit.",
                    ]
                ),
                "Staged lint fail-closed: the linter could not be run.",
            )


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

    # Commit gate: review cycle + tier-1 security + lint. Below the
    # 3+ code-files threshold there is no per-commit security gate
    # (close-skill Step 4 covers the cumulative diff at close).
    if smm_dir is not None and git_commits.is_git_commit(command):
        # Tier 1 fires before the review-cycle gate so deterministic
        # patterns block even when /code-review and /xp-quality-review are done.
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

        # Single name-only call shared by the lint gate and downstream
        # checks — one fork instead of two.
        staged = commits.get_staged_files(cwd)

        _staged_lint_gate(staged, cwd)

        cycle = markers.read_review_cycle(smm_dir, agent_id)
        code_files = commits.get_code_files_for_review(
            cwd,
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
            # `git -C <path>` retargets cwd — branch-check the named path.
            effective_cwd = commits.parse_effective_cwd(command, cwd)
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

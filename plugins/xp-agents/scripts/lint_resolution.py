#!/usr/bin/env python3
"""Lint concern resolution on commit and orphan sweep.

Extracted from bash_post_tool.py — these functions re-run linters on
committed files and auto-resolve matching lint concerns in the SMM.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import resolution
import worktree
from event_schema import STATUS_ACTION_LINT_RESOLVED

_WATERMARK_ID = "lint-resolution"


def check_and_resolve_lint(
    smm_dir: Path,
    cwd: str,
    git_root: str,
    agent_id: str,
    normalized: str,
    label: str,
    events: list[dict] | None,
    resolutions: dict | None,
) -> None:
    """Re-run the linter for *normalized*; resolve matching concerns if clean."""
    import lint_check

    config = lint_check.detect_linter_config(cwd, git_root, file_path=normalized)
    if config is None:
        return
    linter_name, _ = config
    if lint_check.run_linter(linter_name, normalized, cwd=git_root) is not None:
        return
    concerns.resolve_concerns(
        smm_dir,
        lambda c, n=normalized: concerns.lint_concern_matches(c, n),
        agent_id,
        label,
        events=events,
        resolutions=resolutions,
        extra_metadata={"action": STATUS_ACTION_LINT_RESOLVED},
    )


def resolve_lint_on_commit(
    smm_dir: Path,
    cwd: str,
    agent_id: str,
    files: list[str],
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> None:
    """Run linter on committed files and resolve lint concerns for passing ones."""
    if not files:
        return
    git_root = worktree.resolve_git_root(cwd) or cwd
    for file_path in files:
        normalized = worktree.normalize_path(file_path, cwd)
        check_and_resolve_lint(
            smm_dir,
            cwd,
            git_root,
            agent_id,
            normalized,
            "Lint concern resolved on commit",
            events,
            resolutions,
        )


def sweep_orphan_lint_concerns(
    smm_dir: Path,
    cwd: str,
    agent_id: str,
    committed_files: list[str],
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> None:
    """Resolve unresolved lint concerns whose file is now clean but isn't in
    this commit. Catches side-effect fixes (`ruff check --fix` from Bash,
    pre-commit reformatting, cross-file fixes) that don't show up as direct
    edits to the offending file. Files referenced by lint concerns but no
    longer on disk are skipped (manual triage)."""
    if events is None:
        events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    if resolutions is None:
        resolutions = resolution.compute_resolutions(events)

    resolved_ids = resolutions["resolved_concern_ids"]
    committed_set = {worktree.normalize_path(f, cwd) for f in committed_files}

    orphan_paths: set[str] = set()
    for e in events:
        if e.get("type") != _common.CONCERN:
            continue
        if e.get("id", "") in resolved_ids:
            continue
        path_part = concerns.extract_lint_concern_path(e.get("content", ""))
        if path_part is None:
            continue
        normalized = worktree.normalize_path(path_part, cwd)
        if normalized not in committed_set:
            orphan_paths.add(normalized)

    if not orphan_paths:
        return

    git_root = worktree.resolve_git_root(cwd) or cwd
    for normalized in orphan_paths:
        if not (Path(git_root) / normalized).exists():
            continue
        check_and_resolve_lint(
            smm_dir,
            cwd,
            git_root,
            agent_id,
            normalized,
            "Lint concern resolved on sweep",
            events,
            resolutions,
        )

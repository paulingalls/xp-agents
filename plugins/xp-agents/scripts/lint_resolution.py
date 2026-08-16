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
import lint_grouping
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
    """Re-run the linter for *normalized*; resolve matching concerns if clean.

    The per-file fallback: the config-dir monorepo path calls this directly,
    and `_resolve_group` calls it once per path in a group whose batch run
    reported findings — a batch's exit code names no file, so the group's
    clean paths still deserve a look, and this is that look.
    """
    import lint_check

    config = lint_check.detect_linter_config(cwd, git_root, file_path=normalized)
    if config is None:
        return
    linter_name, config_path = config
    # Run the linter from the config file's dir (not git_root) so monorepo
    # subpackage binaries + cwd-relative configs resolve — symmetric with
    # lint_check.run(), or a concern raised there could never clear here.
    lint_cwd, file_arg = lint_check.lint_invocation_target(
        config_path, git_root, normalized
    )
    # config_path and root are threaded through: a checkstyle concern raised by
    # lint_check.run() with the project's config could NEVER clear here if this
    # re-run used a different one — and a clang-tidy concern in a project with no
    # compile database could never clear at all, because 'hdr.h not found' is not
    # fixable by editing the file the concern is attached to.
    if (
        lint_check.run_linter(
            linter_name,
            file_arg,
            cwd=lint_cwd,
            root=git_root,
            config_path=config_path,
        )
        is not None
    ):
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


def _batch_targets(
    config_path: str, git_root: str, paths: list[str]
) -> tuple[str, list[str]]:
    """(lint_cwd, file_args) for a group that all share *config_path*.

    lint_cwd is constant across the group by construction, not an assumption:
    it is Path(config_path).parent, and config_path is half the group key.
    """
    import lint_check

    targets = [
        lint_check.lint_invocation_target(config_path, git_root, p) for p in paths
    ]
    return targets[0][0], [file_arg for _, file_arg in targets]


def _resolve_group(
    smm_dir: Path,
    cwd: str,
    git_root: str,
    agent_id: str,
    linter_name: str,
    config_path: str,
    paths: list[str],
    label: str,
    events: list[dict] | None,
    resolutions: dict | None,
) -> None:
    """Lint one (linter, config) group in a single process; resolve by exit code.

    A batch's exit code names no file (see lint_check.run_linter_batch), so
    the disposition is three-way: clean resolves every concern in the group
    in one bulk append, findings falls back to one run per file in THIS
    group only, and unverified resolves nothing — a bad read is not a pass.
    """
    import lint_check

    lint_cwd, file_args = _batch_targets(config_path, git_root, paths)
    run = lint_check.run_linter_batch(
        linter_name,
        file_args,
        cwd=lint_cwd,
        root=git_root,
        config_path=config_path,
    )
    match run.status:
        case "clean":
            concerns.resolve_concerns(
                smm_dir,
                lambda c: any(concerns.lint_concern_matches(c, p) for p in paths),
                agent_id,
                label,
                events=events,
                resolutions=resolutions,
                extra_metadata={"action": STATUS_ACTION_LINT_RESOLVED},
            )
        case "findings":
            for normalized in paths:
                check_and_resolve_lint(
                    smm_dir,
                    cwd,
                    git_root,
                    agent_id,
                    normalized,
                    label,
                    events,
                    resolutions,
                )
        case "unverified":
            pass


def resolve_lint_on_commit(
    smm_dir: Path,
    cwd: str,
    agent_id: str,
    files: list[str],
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> None:
    """Run linter on committed files and resolve lint concerns for passing ones.

    Groups files by the (linter, config) that claims them and spawns at most
    one linter process per group — see `_resolve_group`. Two caller-side
    filters run first, both before grouping: a flag-shaped path would make
    `run_linter_batch` refuse the whole group (permanently, on a re-sweep),
    and a path with no open lint concern has nothing this loop could ever
    resolve — the common commit needs zero processes, not N.
    """
    if not files:
        return
    git_root = worktree.resolve_git_root(cwd) or cwd
    if events is None:
        events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    if resolutions is None:
        resolutions = resolution.compute_resolutions(events)

    normalized = [worktree.normalize_path(f, cwd) for f in files]
    normalized = [p for p in normalized if not p.startswith("-")]
    normalized = [
        p
        for p in normalized
        if concerns.has_unresolved_concerns(
            smm_dir,
            lambda c, n=p: concerns.lint_concern_matches(c, n),
            events=events,
            resolutions=resolutions,
        )
    ]
    if not normalized:
        return

    groups = lint_grouping.group_paths_by_linter(normalized, cwd, git_root)
    for (linter_name, config_path), paths in groups.items():
        _resolve_group(
            smm_dir,
            cwd,
            git_root,
            agent_id,
            linter_name,
            config_path,
            paths,
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
    longer on disk, or flag-shaped (a malformed `extract_lint_concern_path`
    read), are skipped before grouping — same as `resolve_lint_on_commit`,
    group_paths_by_linter applies no eligibility filter of its own."""
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
    eligible = [
        p
        for p in orphan_paths
        if not p.startswith("-") and (Path(git_root) / p).exists()
    ]
    if not eligible:
        return

    groups = lint_grouping.group_paths_by_linter(eligible, cwd, git_root)
    for (linter_name, config_path), paths in groups.items():
        _resolve_group(
            smm_dir,
            cwd,
            git_root,
            agent_id,
            linter_name,
            config_path,
            paths,
            "Lint concern resolved on sweep",
            events,
            resolutions,
        )
